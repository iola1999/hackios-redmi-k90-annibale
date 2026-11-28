# 2026-11-28 批 23 真机实测、代码交付与根因定位（b5r70～b5r72）

本记录汇总批 23 全部已合入代码、宿主单测、三轮真机实测（`b5r70`～`b5r72`）以及批 24 离线/真机根因输入。三轮真机全零 `panic(`、`gpu_fault`、`submissions closed`、`smmu fault` 与 `backlight-off`，`b5r72` 结束后设备继续保持在 iOS 桌面运行态（`result: running 0 0`、`ramdisk-state: ready 1ec9000 1ec9000 300000000`）。

## 1. 构建基线与真机轮次总览

- **构建产物基线**：`12377-b23`（`hackios-xnu-kernel/out/xnu12377-b23.bin`，`21,110,528` B，sha256 `a314aebac80271d64728b1e99ab6f19bcc7689c6b7a2934b6974ac915287f190`）、`libannibaleair.dylib`（sha256 `f02c6ec0b7ab5ea9af399f69b0d2ae792e5308063fe8530f3f0c32b2839132e1`）、`/annibale/share/av-test-4s.mp4`（`442,098` B，sha256 `bb9d2b5368985480994ca0024a70c5b8021e60628fe00bea84b09e99109f8277`）与 `/annibale/bin/vol_ls`（`50K`）。

| 轮次 | 内核与关键配置 | 核心结果与实测目录 |
|---|---|---|
| `b5r70` | `12377-b22r2` + `psci_idle=1 psci_cl5=1` | 首次打通 `PSCI_SET_SUSPEND_MODE(OSI)` `feat=0 ret=0` 与 `cpu 0/1 cl5=3`（`cl5_denied=0`/`cl5_err=0`、`33 °C`、触控唤醒正常、`apfs: write = 0`），`docs/progress/evidence/k90auto/kernel-12377-b22r2-b5r70/` |
| `b5r71` | `12377-b23` + `JOB_ENV="com.apple.backboardd.plist:ANNIBALE_G32_PROBE=1"`，`--teardown` | `M4` `av-test-4s.mp4` `exit 0`（`120` 帧音视频）、`S10` 5 路径 `vol_ls fsid` 全过、`M3` `1/16..7/16` 连续无截断、`G32` 锁定 `buffer_texture_alias` 与 `[[texture(3)]]` LUT、`P14` `QRTR 0x1000 inst 0x201` 发布成功、`P21` 定因 `kev_post_msg > MLEN` `EMSGSIZE`、`S11` 定因 `bcopy_phys_internal` 关抢占 `copyin`，`docs/progress/evidence/k90auto/kernel-12377-b23-b5r71/` |
| `b5r72` | `12377-b23` + `fb_dpu_scale=1`（`fb_threads=2`），保持运行态 | `13` 窗口 `1699` 帧、`0` 丢翻页，`each in the driver` 加权均值 `2694.8 us`（`2.69 ms`）；`tour-sheet.png` 条纹确证源于机内旧版 `xnuloader`（`adb193ad...`）；再现 1 例 `locationd[70] apfs: write ... failed: 14`，`docs/progress/evidence/k90auto/kernel-12377-b23-b5r72/` |

## 2. 批 23 已合入并过审的代码与宿主单测

- **`P21` Wi-Fi 事件契约与过滤（`#977`/`#981`）**：`annibale_apple80211.c`（`1134` L）在关联期间置 `join_result = 0xffff`、`JOIN_DONE` 置 `done.flags = 1` 并对不足 `20 ms` 快速同网延迟投递 `EVENT_ASSOC_DONE`，`case 564` 按 `32 B` `EVENT_FILTER` 经 `event_allowed()` 过滤；`test-annibale-apple80211-events.py`（`194` L）与 `test-wp3b-wifi-native.py` 均通过。
- **`P14` 双实例 TFTP 与 FastRPC 回退（`#977`/`#981`）**：以独立 `annibale_tftp.inc`（`690` L）替换 `annibale_modem_tftp.inc`，`annibale_adsp.c`（`1199` L）与 `annibale_modem.c`（`1196` L）分别发布 `QRTR 0x1000` `instance=2`/`0`；`annibale_adsp_fastrpc*.inc`（`636`/`1028` L）加入 `ROOT_PD`/`SENSORS_PD` `INIT_ATTACH_SNS` 回退与 `adsp_fastrpc_active_pd`；5 项宿主测试全通过。
- **`G32` 扩展纹理与渐变绘制探针（`#960`/`#961`）**：`annibalemetal_g32_probe.inc`（`526` L）、`annibalemetal_texture.inc`（`831` L）与 `annibalemetal_work_private.h`（`133` L）扩展 `ANNIBALE_G32_PROBE=1`（默认关闭）捕获 `height == 1` / `256×1..4` `format 115` 创建写入与 `tex0`/`fbuf5`/`attr1` 绘制；`test-g32-probe.py`（`221` L，ASan+UBSan）`4/4` 通过。
- **`G29` 计算管线锁解耦与 `prewarm` 让出（`#972`/`#976`/`#980`/`#981`）**：`air_metal_compute.inc`（`595` L）将 `compute_create`/`rwa_compute_materialize` 拆为三段无嵌套 `RWA_CSO_CREATE_LOCKED`（新增 `compute_compile_variable_cso()` 与锁外 `dup_cso` 释放）；`annibalemetal.m`（`1127` L）与 `annibalemetal_prewarm.inc`（`800` L）在 `commit_in_flight != 0` 时短让出；`test-air-g29-decoupling.py`（`1023` L，ASan+UBSan+TSan）与 `test-air-compute-split-limits.py` `4/4` 通过。
- **`S7` 阶段 B 内核与 `xnuloader`（`#985`/`#986`）**：`loader_return.c`（`1056` L）与 `xnuloader`（`loader_02` `936` L、`loader_04` `664` L、`loader_06` `1199` L）实现 `KERNEL_LIVE_MAGIC6`（`0x364556494c554e58ULL`）实时 `scanout` 上报与 `getvar screen`/`oem screenshot` 动态暂存；`MiniFramebufferDpuScale.inc`（`475` L）、`MiniFramebufferFlip.inc`（`559` L）、`MiniFramebufferRows.inc`（`483` L）与 `MiniIOMobileFramebuffer.cpp`（`1238` L，净减 `6` L）接入 `fb_threads` 并行拷贝 `dpu_scale_copy_rows()`。
- **`S7` 阶段 B 主机工具与单测（`#985`/`#986`）**：新增 `tools/k90auto/shotraw.py`（`131` L）解码填充 `stride` 与 `l10r`，同步更新 `run-auto.py`/`sheets.sh`/`tour.py`/`ui.py`/`visual-audit.py`/`summary.py`；`test-fb-dpu-scale.py` `4/4`、`test-fb-flip-rows.py`、`test-shotraw.py` `4/4`、`test-tour.py` `7/7`、`test-ui.py` `14/14`、`test-tools.py` `53/53` 与全部 loader 单测通过。
- **`M4`、`S10` 与健康诊断工具（`#951`/`#952`/`#965`/`#967`/`#973`/`#975`/`#978`/`#981`）**：生成并经 `build.sh`（`633` L）/`package.py`（`1199` L 净 `0`）条件打包 `av-test-4s.mp4`；`vol_ls.c`（`455` L）新增只读 `fsid` 子命令（`test-vol-ls-fsid.py` `111` L `3/3` 通过）；`render-health.py`（`253` L）新增 `apfs-write` 签名与 `g31-trace.txt`/`g32-probe.txt` 侧车保留。

## 3. b5r70（psci_idle=1 psci_cl5=1）真机实测详情

- **PSCI OSI 与 Cluster1 CL5 打通**：开机日志记录 `psci: set_suspend_mode feat=0 (supported) ret=0 (success)` 与 `psci: method=smc version=1.1 cpu_suspend=0x3 (osi=1 ext_stateid=1) psci_idle=1 psci_cl5=1`；`sysctl kern.annibale.cpus` 读出 `cpu 0` `c4 149035 cl5 3`、`cpu 1` `c4 144740 cl5 3`、`cpu 2` `c4 100882 cl5 0`、`cpu 3` `c4 73840 cl5 0`（全部 `c4_err=0`、`cl5_denied=0`、`cl5_err=0`）。
- **温控、触控与健康巡检**：电池 `33 °C`，`cpufreq` domain 0 `39.1–44.6 °C`（`384 MHz 96%`）、domain 1 `39.5–47.3 °C`（`1017 MHz 95%`）、`hot ticks 0`；触控唤醒正常并保存 `home_final.png`；全轮 `apfs: write` 与 `locationd userabort` 均为 `0`。

## 4. b5r71（综合集成与定因采集）真机实测详情

- **`M4`、`S10` 与 `M3` 实机验收**：
  - `M4`：`video_player_test /annibale/share/av-test-4s.mp4` `exit 0`（`result=pass frames=120 pixel_errors=0 stalls=0 output_bytes=41472000 elapsed_ms=4808 first_frame_ms=661`）。
  - `S10`：`3` 组 `/annibale/bin/vol_ls fsid` 对 `/`、`/System/Library/CoreServices/SystemVersion.plist`、`/private/var`、`/private/var/mobile` 与 `/private/preboot` 全数 `exit 0`（`sf_fsid == ga_fsid`、`ino == fileid`、`roundtrip=ok`）。
  - `M3`：音频通路下连续 `7` 次 `voldown` 实测内核音量平滑下降：`1.000 (0.0 dB) -> 0.520 -> 0.457 -> 0.395 -> 0.332 -> 0.207 -> 0.145 -> 0.082 -> 0.020 (47.0 dB)`（仅最低归零档 `sound_test route` 输出 `volume 0.00`，`1/16..7/16` 连续无提前静音）。
- **`G32`、`P14`、`P21` 与 `S11` 实机定位**：
  - `G32`：`g32-tex-new` 捕获 `256×1 fmt=115` 渐变 LUT 均通过 `-[MTLBuffer newTextureWithDescriptor:offset:bytesPerRow:]` 走零拷贝 `buffer_texture_alias` 创建且 `g32-tex-wr = 0`；`backboardd 38` 构建 `TimgBdsoA2Xhfn_Isrc`/`TmuaA2Xhfsn_*`/`TimgA2S1Xhfun_Isrc`，结合 `llvm-dis` 查明 LUT 绑在 `[[texture(3)]]` 与 `[[texture(9)]]`/`[[buffer(5)]]`（探针仅查 `tex0` 导致绘制零命中），且着色器含 `NaN/Inf -> (0,0,0)` 分支。
  - `P14`：`QRTR 0x1000 inst 0x201` 向 node 5/7 广播 `err=0`；FastRPC `INIT_ATTACH(root)` 返 `0x8000040e`、`INIT_ATTACH_SNS` 返 `0x80000410`。
  - `P21`：串口实证 `the station says: a join is over, 0` 与 `EVENT_LINK_CHANGED`（`72 B <= MLEN`）送达 `wifid`，锁定真因为 `kev_post_msg()`（`bsd/kern/kern_event.c:8916-8928`）在 `total_size > MLEN` 时以 `EMSGSIZE` 静默拦截 `500 B` 的 `EVENT_ASSOC_DONE`（及 `512 B` `LQM`）。
  - `S11`：`apfs-write` 捕得 `apfs: write ino 3501469 resid 60 ioflag 0x100003 failed: 14` 与 `copyio_abort(vm): locationd[68] far=0x11735c000 ... __bcopyin res=5`，定因 `bcopy_phys_internal()` 命中 `use_copy_window_dst` 时在 `mp_disable_preemption()` 内调 `copyin` 触发冷页 `vm_fault` 返 `KERN_FAILURE (5)`。

## 5. b5r72（fb_dpu_scale=1 + fb_threads=2）真机实测详情

- **DPU 并行拷贝吞吐**：全轮 `13` 窗口共 `1699` 帧（`0 gave up`、`0 flips not taken within 40 ms`、`0 panel rows drawn a frame`），`each in the driver` 加权均值 `2694.8 us`（`2.69 ms`，范围 `783–4753 us`，对比 `b5r65` 单线程 `3.65–5.81 ms` 缩短约 `1–2 ms`）。
- **截屏条纹定因与常规巡检**：`run/reboot.json` 证实机内驻留旧版 `xnuloader`（`loader_build_id = adb193ad74d666207a452f47fd19f472821e27d1`，尚未包含 `KERNEL_LIVE_MAGIC6`）；对 `12` 张 `run/png/shot-*.png` 按 `w=1216 stride 4864` 重算相邻行差由 `12.80–30.51` 降至 `1.07–1.84`，待后续重刷批 23 `xnuloader` 后配合 `shotraw.py` 复验；同轮再现 `1` 例 `locationd[70]` `apfs: write ... failed: 14`。

## 6. 批 23 离线只读定因与批 24 输入

- **`M6` 前摄人像模式边界定案**：遍历 `ios26/rootfs/System/Library/ImagingNetworks/` 全部 `121` 项确认 `14/14` 个 `*.E5.espresso.bundle` 均仅含 H18 ANE `.hwx` 二进制、`0` 份 `*.weights`，且前摄人像深度依赖 Pearl TrueDepth IR 硬件，确认为外部硬件与固件边界。
- **`S12` `ATXInfoTimelineDonationClient` 服务来源**：核查 `com.apple.proactive.infoSuggestion.xpc` 位于系统镜像 `com.apple.duetexpertd.plist`（`/usr/libexec/duetexpertd` `98,672` B），当前受 `mkjobs.py` `DENY` 与 `package.py` `REST_ALLOW` 过滤；`package.py:648-655` 已支持通过 `REST_ALLOW="duetexpertd"` 放行并自动剥离冲突的 `HomeScreenSuggestion.xpc`。
- **批 24 定点修复点**：`P21` 在 `kev_post_msg()` 对 `total_size > MLEN && <= MCLBYTES` 改用簇 mbuf（`m_getcl`）并记录 `post()` 错误码；`P14` 反汇编 `adsp.b09` `fastrpc_kprocess` / `adsp_process_group_create` 明确 `0x8000040e`/`0x80000410` 参数；`G32` 扩展探针扫描 `[[texture(3)]]`/`[[texture(9)]]` 并采样底层 `MTLBuffer` 配合 `RWA_BUFFER_TEXTURE_COPY=1` 对照；`S11` 查明 `bcopy_phys_internal` 触发 `use_copy_window_dst` 条件并消除关抢占 `copyin`；`S7` 随更新 `xnuloader` 验证 `oem screenshot` + `shotraw.py`。
