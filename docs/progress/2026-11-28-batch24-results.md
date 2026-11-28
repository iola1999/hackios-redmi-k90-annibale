# 2026-11-28 批 24 真机实测、P21/S11 修复与发版前检查（b5r73～b5r75）

本记录汇总批 24 全部已合入代码、宿主单测、三轮真机验收（`b5r73`～`b5r75`）以及批 25 与 `v0.2.5` 发版前置核查输入。三轮真机全零 `panic(`、`gpu_fault`、`submissions closed`、`AnnibaleGPU client refused`、`smmu fault`、`backlight-off`、`No system apps remain` 与 `crash`，`b5r75` 结束后设备健康保持在 iOS 桌面运行态（`running-held`）。

## 1. 构建基线与真机轮次总览

- **内核与用户态基线**：`12377-b24`（`hackios-xnu-kernel/out/xnu12377-b24.bin`，`21,110,528` B，sha256 `fdd6a73b8b27d6a48d7f6024ba716c3f9b0127f78233f5858ad40720584b4143`，版本串已固定含 `; builder:xnu12377[...]`），配合更新后的 `a80211_test`、`cycle.py` 与 `render-health.py`。

| 轮次 | 内核与关键配置 | 核心结果与实测目录 |
|---|---|---|
| `b5r73` | `12377-b24` + `JOB_ENV="com.apple.backboardd.plist:ANNIBALE_G32_PROBE=1"`，`--teardown` | `P21` `cwjoin` `exit 0`（`associate reply err 0x0`、`0` 次 `-3905`）与 `leave` 约 `6 s` 后自动重连；`S11` `0` 次 `apfs-write`/`copyio_abort`/`userabort: locationd`；`P14` `INIT_ATTACH(root) -> 0`；`G32` `g32-buf-tex` `256×1 fmt=115` 有效非 NaN，`docs/progress/evidence/k90auto/kernel-12377-b24-b5r73/` |
| `b5r74` | `12377-b24` + `RWA_BUFFER_TEXTURE_COPY=1` + `ANNIBALE_G32_PROBE=512` + `Weather:ANNIBALE_G31_TRACE=64`，`--stop` | 点进「萧山区」详情页在 `RWA_BUFFER_TEXTURE_COPY=1` 下背景与第 2～3 行温标仍纯黑（均值 `[14.72, 14.79, 14.35]`，排除 `buffer_texture_alias`）；`Weather 271` 编译 `14` 条 `particle_quad`（`0 refused`）后稳态 `dispatch = 0`；定因首屏缺相机图标出自 `cycle.py` 缺 `cam=5`（`mg_test` 返回 `false`、`IconState.plist` 保留索引 `[5]`），`docs/progress/evidence/k90auto/kernel-12377-b24-b5r74/` |
| `b5r75` | `12377-b24` + `cam=5` + `REST_ALLOW="duetexpertd"` + `SB26_EXTRA="Weather"` + `ANNIBALE_G32_FILTER=N3Oc3mtc4nlnlnl` + `Weather:ANNIBALE_G31_TRACE=256`，留机运行 | 首屏恢复「相机」图标（15 图标 + 4 Dock、`mg_test` 返回 `true`）；`duetexpertd[328]` 正常退出而天气小组件仍受 `chronod` persona/`bssendp` 影响；`g32-probe.txt` 精确捕得全屏与温标 `N3Oc3mtc4nlnlnl`（`fbuf4` `off=3384`/`32816` 均有非零参数），`docs/progress/evidence/k90auto/kernel-12377-b24-b5r75/` |

## 2. 批 24 已合入并过审的代码与宿主单测

- **`P21` 内核事件集群与用户态测试（`#1013`/`#1015`/`#1041`）**：新增 `--fuzz=0` 补丁 `83-bsd%kern%kern_event.c.patch`（`33` L，已入 `xnu26/patches/series`），在 `kev_post_msg()` 对 `total_size > MLEN && total_size <= MCLBYTES` 改用 `m_getcl` 簇 mbuf 消除 `500 B` `EVENT_ASSOC_DONE` 与 `512 B` `LQM` 的 `EMSGSIZE` 静默丢包；`annibale_apple80211.c`（`1137` L）打印 `kev_post_msg()` 非零错误；`a80211_test.c`（`861` L）补齐 `leave`（`sets 22`）；`test-annibale-apple80211-events.py`（`233` L）与 `test-wp3b-wifi-native.py` 均通过。
- **`S11` `bcopy_phys_internal` 抢占修复（`#1003`/`#1004`/`#1041`）**：新增 `--fuzz=0` 补丁 `84-osfmk%arm64%loose_ends.c.patch`（`75` L，已入 `series`），在 `use_copy_window_dst`/`src` 涉及用户态地址时先在开抢占态分块中转至 `256 B` 栈缓冲，消除 `mp_disable_preemption()` 区间内调 `copyin`/`copyout`；`test-bcopy-phys-copyin-preempt.py`（`242` L，ASan+UBSan，`2/2` 含 7 组场景）通过。
- **`ENG-01` `newvers.pl` 固定构建者（`#1008`/`#1010`/`#1041`）**：新增 `--fuzz=0` 补丁 `85-config%newvers.pl.patch`（`12` L，已入 `series`）读取 `$ENV{'KERNEL_BUILDER'}`，并在 `12377-b24` 内核串实测生效。
- **`P14` `INIT_ATTACH` 参数修复（`#1016`/`#1017`）**：`annibale_adsp_fastrpc*.inc`（`630`/`1027` L）统一设置 `msg.client_id = 1` 并经 `adsp_fastrpc_build_invoke()` 为 `INIT_ATTACH (rmid=0)` 传入 `SCALARS(0, 1, 0)` 与 4 B 小端 `pidA = 1`，移除误用 `rmid=10` 分支；`test-adsp-fastrpc-probe.py`（`703` L，ASan+UBSan）通过。
- **`G32` 扩展探针与侧车过滤（`#1005`/`#1007`/`#1011`/`#1012`/`#1033`/`#1034`）**：`annibalemetal_work_private.h`（`135` L）、`annibalemetal_texture.inc`（`835` L）与 `annibalemetal_g32_probe.inc`（`758` L）扫描全槽位纹理、采样 `newTextureWithDescriptor:offset:` 底层 `MTLBuffer` 并新增 `ANNIBALE_G32_FILTER` 与 `fbuf4` 输出（`test-g32-probe.py` `297` L `6/6`）；`render-health.py`（`253` L）放宽 `"g32-"` 侧车匹配。
- **`cycle.py` `cam=5` 恢复（`#1039`/`#1041`）**：`tools/k90auto/cycle.py`（`343` L）在 `FIXED_ARGS` 补回 `cam=5` 对齐 `mkstandalone.py` 并清理旧注释；`test-cycle-state.py` `14/14`、`test-make-payload.py` `6/6`、`test-tools.py` `53/53` 与 `bootargs.py --check` 均通过。

## 3. b5r73（P21/S11/P14 验收与 G32 采样）真机实测详情

- **`P21` 主动关联与 `leave` 自动重连通过**：`a80211_test cwjoin` 退出 `0`（`45020 ms`，`cwjoin: associate reply err 0x0`，`0` 次 `-3905`、`0` 次 `kev_post_msg` 错误、`0` 次 `wifid sets 483/481` 轮询，`apple80211` 正常输出 `the station says: a join is over, 0` 与 `the link, 1`）；`a80211_test leave`（`set disassociate(22) -> 0`、`the link, 0`）在约 `6 s` 后自动扫描并重连至 `the link, 1`（`wifid processIPv4Changes: - lastJoinReason:Auto`）。
- **`S11` 零复现与 `P14`/`G32` 推进**：全轮 `apfs-write`、`apfs: write`、`copyio_abort` 与 `userabort: locationd` 均为 `0`；`P14` 首次打通 `aadsp: fastrpc: INIT_ATTACH(root) -> retval=0 (0)`（`rx #2 len=24 hdr=0x20100 0 0 0`），`INIT_CREATE_STATIC(sensorspd)` 仍返 `-2147482492 (0x80000484)`、`adsp_listener_init2` 返 `-2147482610 (0x8000040e)`、`sensors-ssc: SNS_CLIENT online at node 5 port 18`；`G32` `g32-buf-tex` 捕得 `256×1 fmt=115` 有效非 NaN `half4`（`nz=256/256 nan=0`），`weather_main.png` 4/4 城市卡片正常。

## 4. b5r74（RWA_BUFFER_TEXTURE_COPY=1、VFX 追踪与相机图标定因）真机实测详情

- **详情页排除 `buffer_texture_alias` 与粒子调度定位**：点进「萧山区」详情页（`weather_detail.png` `19° 有风`），在 `RWA_BUFFER_TEXTURE_COPY=1` 生效下背景与 10 日预报第 2～3 行温标条仍为纯黑（全图均值 `[14.72, 14.79, 14.35]`、天空与卡间 `[0, 0, 0]`，仅第 1 行 `CGDrawingLayer` 温标有色），排除了 `buffer_texture_alias`；`Weather 271` 启动期 `commit 22..25` 运行计算 `dispatch`（`work kind 4`）、调用 `-[MTLArgumentEncoder constantDataAtIndex:]` 并编译 14 条带 `MTLLinkedFunctionsInternal` 的 `particle_quad`（`0 refused`），随后至 `905×1967`（`sf=68..70`）恒为 `dispatch 0` 且零 `particle_quad` 绘制。
- **首屏缺失「相机」图标定因**：`mg_test` 实测 `still-camera`/`rear-facing-camera`/`front-facing-camera`/`camera-flash`/`auto-focus-camera` 均为 `false`（仅 `video-camera=true`），而拉回解析的 `IconState.plist`（`3720` B）与 `DesiredIconState.plist`（`3714` B）在 `iconLists[0][5]` 仍保留 `'com.apple.camera'`；定因 `b5r55` 起 `init_mount.inc` 清空持久化 MobileGestalt 缓存而 `cycle.py` `FIXED_ARGS` 缺少 `cam=5`（`mkstandalone.py` 默认已包含 `cam=5`）。

## 5. b5r75（cam=5、duetexpertd 与 N3Oc3mtc4nlnlnl 探针）真机实测详情

- **首屏相机图标恢复与 `S12` 实测**：`tour-sheet.png`（`home`、`home-final`）主屏第 1 行第 4 格恢复「相机」图标（`15` 图标 + `4` Dock），`mg_test still-camera rear-facing-camera` 返回 `true`；`REST_ALLOW="duetexpertd"` 下 `duetexpertd[328]` 正常退出（`Wifi` 客户端清理），`chronod` 仍录 `No active persona/ system persona detected` 与 `bssendp` pid `-1`（`135`），桌面天气小组件仍显示「天气不可用」。
- **`N3Oc3mtc4nlnlnl` 探针捕获详情页现场**：`g32-probe.txt`（64 条命中）捕获全屏背景 `TimgA2Xhfsn_IsrcN3Oc3mtc4nlnlnl`（`#52`，`t3=fmt115:256x1` `nz=256/256 nan=0`、`fbuf4 off=3384`、`fbuf5=0.0078`、`attr0=[0..1206 x 0..2622]`）与第 2～4 行温标 `TmuaA2Xhfsn_IsrcN3Oc3mtc4nlnlnl_Isup`（`#53..#62`，`fbuf4 off=32816` 16 B 对齐仍黑）。
- **`Weather` 退场家族与详情页图层状态**：`g32-probe` 同期捕获 `TimgA2Xhf_IxrgN3Oc3mtc4nlnlnlXq` / `TcimA2Xhfs_IxrgN3Oc3mtc4nlnlnlXq`；`Weather` `SwiftUI._UIInheritedView` 与 `WeatherVFXView`/`VFXCoreView` 在 `b5r75` 均为 `a=1.00`，`g31-trace`（`231` 条）为 `905×1967 post_process`。

## 6. 批 24 离线定因与批 25 / v0.2.5 发版输入

- **`G32` 天气两项缺陷转入批 25**：`#1026` 反汇编证实 `WeatherUI`/`VFX` `supportsFamily:` 不会在 `metal_profile=4` 关闭粒子层；`b5r75` 将子问题 A 收敛至 `N3Oc3mtc4nlnlnl` 色彩转换（EOTF + 3×3 矩阵 `fbuf4`）在 AIR->NIR/IR3 的计算异常与 `WeatherVFXView` `destOut` 合成，子问题 B 收敛至 `WeatherVFXConditionBackground` / `VFX` 为何在 `commit 22..25`（`constantDataAtIndex:`）后停止 `particle_quad` 与稳态 `dispatch`。
- **`P14` 与 `v0.2.5` 发版输入**：`P14` 下一步聚焦 `adsp.b25`/`SSCRPCD` 与 `sensorspd` `0x80000484`/`adsp_listener_init2` `0x8000040e` 所需服务发现；`v0.2.5` 发版审计（`#1002`）已确认 `83`/`84`/`85` `--fuzz=0`、`test-build-release-provenance.py`（`4/4`）、`test-localfiles.py`（`8/8`）与 `test-assemble-wifi.py`（`4/4`）均通过，并需在发版时刷入批 23 新版 `xnuloader` 联动验证 `S7` 阶段 B（`getvar screen`/`oem screenshot`）。
