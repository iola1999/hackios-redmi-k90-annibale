# 2026-11-27 批 17 阶段实测、根因定位与修复记录（b5r51～b5r54）

本记录汇总批 17 四轮真机测试：`b5r51`、`b5r52`（`xnu12377-flipwd26.bin` `3c2183a3...` + `libannibaleair.dylib` `3d7cec62...` + 重编用户态）、`b5r53`（`flipwd27` panic 定位）与 `b5r54`（`xnu12377-flipwd28.bin` `086625ad...` + 同期用户态），以及 `#637`、`#645`、`#646`、`#648`、`#650`/`#651` 根因与修复结论。

## 1. b5r51：G30 阶段 2 与 nircache 跨重启验证

- **`G30` 阶段 2 + 双上下文抢占启动验收（`#633`/`#634`）**：`b5r51` 带 `gpu_recover=1 adreno8_preempt=1` 启动，`adreno8: HWSCHED START acknowledged (ifpc=0, preempt=1)` 与 `context 1 pass 1/2`（`0x22c00001`/`0x22c00002`）、`context 2 pass 3`（`0x22c00003`）全部通过，`cycle.py` 12 步交互全过（`rc=0`，`render-report.txt` `4443737 bytes`、`0 merge gaps`），`locationd`（70）、`backboardd`（38）与 `SpringBoard`（29）存活无重启。
- **`b5r51` 故障与稳态核查**：`returned.log`（`53` 份日志、`51,545` 唯一行）全零 `gpu_fault`/`submissions closed`/`AnnibaleGPU client refused`/`apfs: write`/`ufshc`，`gpu_recover=1` 处于武装待命状态（本轮未发生真实故障）。
- **`nircache` 跨重启实落盘核查**：`/private/var/db/annibale-nircache/e557fa46-ef99-3b23-9c9e-6779aaeb0e8f/` 跨重启保留磁盘文件，抽检 3 个桶确认存在真实序列化 NIR 文件（`61` 桶 6 个 `2340..9780` B、`0d` 桶 10 个 `2808..34460` B、`95` 桶 7 个 `1548..28668` B）。

## 2. G15 量化对照：b5r45／b5r50／b5r51（#637）

- **`SpringBoard` `AIR -> NIR` 翻译采样清零**：合并 `tl: t` 采样统计显示，管线创建采样从 `b5r45`（无 `nircache`）`7` 条（峰值 `712 ms`）、`b5r50`（冷启建库）`15` 条（峰值 `417 ms`）降至 `b5r51`（热命中）`2` 条（降幅 `71.4%`/`86.7%`）；其中 `air_to_nir` CPU 翻译采样由 `6`/`7` 条降为 **`0` 条**，管线创建主线程轮次峰值由 `712`/`417 ms` 降至 **`59`/`49 ms`**（降幅 `85.9%`～`91.7%`）。
- **伴随帧率与 `G29` 遗留**：`summary.py` 动画帧率 `fps_mv` / `<18 ms` 占比由 `b5r45` `81.2 fps`（`90%`）、`b5r50` `85.1 fps`（`91%`）升至 `b5r51` `90.8 fps`（`92%`）；同时 `b5r51` 仍见 `SpringBoard`/`backboardd` 后台 `prewarm`（跨度 `27.6 s`/`39.7 s`）及 `13` 条 `rwa_texture_destroy` 持 `RWA_LOCK` 等锁（`28..245 ms`），该部分留归 `G29` 继续解耦。

## 3. b5r52：S6 格式 94、ENG-09/G3 像素对比与 S7/G31 采样

- **`S6` Format 94（`'l10r'`）实机全过（`#639`/`#643`）**：`out/b5r52/format94.txt` 记录 `/private/var/tmp/metal-format94-native --driver /annibale/lib/libannibalemetal.dylib` 输出 `ordinary`、`buffer` 与 `surface`（`fourcc=6c313072` `'l10r'`）各 8 像素均零失配（`RESULT native_paths=3 failures=0`，`24/24` 精确匹配）。
- **`ENG-09` / `G3` / `G2` `material_regress_ios` 真机对比**：`out/b5r52/mr_compare.txt` 对照 `out/b5r52/ref/` 完成 18 项（`16/18` 通过）：`G3` 两项（`g3_fsat_bitcast`、`g3_alias_rel_const`）与 `fmt_bgr10a2`（`max_err=1`）、`glass_fbfetch_c0`、`blur_fp16`、`sdf_*`、`mp_*` 等 `16` 项通过；捕获 `2` 项真问题：① `blend_const_color`（`256/256` 失配、`max_err=157`，`setBlendColorRed:green:blue:alpha:` 实际按 `1.0` 输出）；② `glass_fbfetch_c1`（`2/256` 失配、`max_err=0.0014648` 超 `0.001` 容差）。
- **`S7` 与 `G31` 现场采样**：`S7` `ANNIBALE_DAMAGE_PROBE=1` 记录 `damage_probe[11..32]`（`clear=0..2 load=44..270 dontcare=0 draws=487..1795 all_scissored=30/30 union_y=0..2622`），确认局部重绘均走 `load + scissor`；`G31` `ANNIBALE_G31_TRACE=1` 记录 `Maps[368]` `g31-trace` 256 行（`c0=1206x2622 fmt=81`）。`returned.log`（`20,521` 唯一行）全零 `gpu_fault`/`submissions closed`/`apfs: write`/`ufshc`。

## 4. b5r53（flipwd27）panic 定因与 flipwd28 修复（#640/#643/#650/#651）

- **`M1` `HFI_COLOR_FMT_P010` 修正（`#640`/`#643`）**：核实 HFI Gen2 中 `4u` 为 `TP10_UBWC`、线性 `P010` 为 `3u`；`annibale_iris_private.h`（459 L）改为 `3u`，`annibale_iris_buffers.inc`（160 L）补充被拒缓冲诊断打印，`test-iris-hfi-wire.py` 与 `test-iris-safety.py` 全部通过。
- **`P14` `GLINK_RX_INTENT_REQ` 与 `P21` ABI 修复（`#640`/`#643`）**：`annibale_adsp_fastrpc.inc`（626 L）在 `FASTRPC_STAGE_IDLE && !has_intent` 时按 `500 ms` 间隔发送 `GLINK_RX_INTENT_REQ`（`512 B`、最多 10 次），`test-adsp-fastrpc-probe.py` 通过；`a80211_test.c`（830 L）对齐 `CoreWiFi` 回调参数序、`CFDataRef` `setSSID:` 与 `CWFAssocParameters` 并过 `arm64e` `-Werror`。
- **`b5r53` `apps_smmu` panic 定因与 `flipwd28` 修复（`#649`～`#651`）**：`b5r53` 收到 `remote intent #1 id=147 size=512` 后在 `_adsp_fastrpc_service`（`adsp_fastrpc_smmu_configure()`）执行编译器生成的后递增加载 `ldr w3, [x2], #0x4` 读取 `apps_smmu@0x15000000` `SMR(0)`（`far=0xfffffffa0ec90800`），因 `ESR_EL2.ISV=0` 触发 QHEE/Gunyah Synchronous External Abort（`esr=0x96000010`）。
- **`annibale_adsp_fastrpc_smmu.inc` 与 `flipwd28` 核验**：改用非回写内联汇编 `ldr %w0, [%1]`/`str %w0, [%1]` + `__builtin_arm_dsb(0xf)`，补齐 `first_s1` 下界与 `(pages + banks) * pg_sz <= ADSP_APPS_SMMU_SIZE` 越界校验、按 `CBA2R -> CBAR -> CB_SCTLR` 顺序写入及 `& ~0xffu` VMID 掩码复用（298 L）；`test-adsp-fastrpc-probe.py`（572 L，ASan+UBSan）通过，`mach.development.bcm2837` `post-index ldr hits = 0`。

## 5. b5r54（flipwd28）：P14、M1 与 P21 实测推进（#654）

- **构建与稳态**：`xnu12377-flipwd28.bin`（`21073744` B，sha256 `086625ad614554cdef3264b9073fee745f5373913c71bbc42146b3aa2b4f325a`）配合 `libannibaleair.dylib`（`3d7cec62...`）与重编用户态完成 `cycle.py` 12 步交互与截图（`rc=0`，`render-report.txt` `5572169 bytes`, `0 merge gaps`）；`docs/progress/evidence/k90auto/kernel-12377-flipwd28-b5r54/run/returned.log` 全零 `panic`/`gpu_fault`/`submissions closed`/`apfs: write`/`ufshc`，退回空闲 `xnuloader`（`slot-retry-count:a: 7`）。
- **`P14` 阶段 2 推进**：`fastrpcglink-apps-dsp` 建链（`lcid=5 rcid=5, intents=8x1024B`）并收到 `remote intent #1 id=147 size=512`，随后完成 `apps_smmu compute-cb@2 bank=81 slots=(10,11) sids=(0x1004/0x80,0x1044/0x20)` 配置且全程零 panic；下一步停在 `aadsp: fastrpc: adsp_mem_heap 12 MiB <4G allocation failed`。
- **`M1` HEVC Main 10 诊断命中**：`out/b5r54/m1.txt` 返回 `callback sample=1 status=-12909`（`M1_RC=1`）；`returned.log` 记录 `iris: RAW published sid=1 ports=0x6 dpb=7 frame=303104 raw=7`、`reply rejected stage=buffer-or-ack sid=1 hdr=23 id=48 port=2 error=5` 及新增诊断 `iris: rejected buf type=2 idx=0 base=0x60000000 aoff=0 bsz=294912 doff=0 dsz=589824 bflags=0x0`（`dsz=589824 == 2 * bsz=294912`）。
- **`P21` `cwjoin` 实测**：脱敏产物 `out/b5r54/cwjoin.txt` 记录 `activated CWFInterface -> scan request sent -> scan reply err ... results 0x0 -> a80211_test: cwjoin scan error: Couldn't communicate with a helper application.`（`CW_RC=3`，无 abort）。

## 6. 批 17 只读根因与下轮方案（#645/#646/#648）

- **`G7` / `ENG-08` 21 项 `translate` 失败分级（`#645`）**：P1 为 `AppleMetalGLRenderer` `2d_ms` 多重采样 `read`（6 项，由 `air_texture.inc:579-582` `if (read_sampler)` 拦截，`air_texture.inc:921-929` 已有 `nir_texop_txf_ms` 路径）；P2 为 `QuartzCore` `fixed_frag_lph_{cph,cpf}`（2 项，全零默认常量下空指针死分支未折叠，运行期带 60 个函数常量、零拒绝）；P3 为 `QuartzCore` Tile 隐式 `imageblock`（13 项，当前仅报 `Apple1/Common1`，不触发调度）。
- **`b5r52` 4 项现场定因（`#645`）**：`blend_const_color` 源于 `-setBlendColorRed:green:blue:alpha:` 空桩及 `struct rwa_draw`/`air_metal_render_draw.inc` 缺失 `pipe->set_blend_color()`，默认 `{0,0,0,0}` 使 `OneMinusBlendColor` 取 `1.0`；`glass_fbfetch_c1` 为 `y=13->14` 阶跃处 A830 与 Apple GPU 双线性子像素权重 3–5 half-ULP 硬件差异；`damage_probe` 因 `RW_DAMAGE_WINDOW=30` 跨 30 帧取并集而饱和到 `0..2622`，需改为单帧高度分桶统计；`G31` `Maps[368]` 缺少 `descriptor.label` 且 `com.apple.WebKit.GPU` 未启用 `ANNIBALE_G31_TRACE=1`。
- **`G29` `b5r51` Turn 3 `245 ms` 等锁根因与解耦边界（`#646`）**：`b5r51` `SpringBoard 29` 中 `prewarm`（`QOS_CLASS_UTILITY`，150 条管线耗时 `27.6 s`）与 `ir3_get_shader` 在持有全局递归 `rwa_lock` 期间触发，使主线程 `rwa_texture_destroy`（13 条采样 `28..245 ms`）与提交线程 `rwa_render_draw`（`247.6 ms`）同步等锁；可通过独立 `cso_create_lock` 移出 `rwa_render_create_linked` 固定状态与阶段 CSO 创建，并用原子引用计数与短锁延迟清理将常见未绑定纹理的 `rwa_texture_destroy` 移出 `rwa_lock`。
- **`S11` `locationd[73]` 崩溃与 `M3` 音量 `0.50` / `((none))` 定因（`#648`）**：`b5r46` `locationd[73]` 崩溃回溯对应 `apfs: write ino 3387559 resid 126 ioflag 0x100003 failed: 14`（`EFAULT`）使 `-[NSConcreteFileHandle writeData:]` 抛出 `NSFileHandleOperationException` 并调用 `abort()`；`M3` 默认 `0.50` 来自 `PVMGetVolume`（`0.50f`）回退，本地非 AirPlay 端点经 `0x1b3af88e4` 仅更新内存 PVM 且未调用 `vaemSetDeviceVolume`（`'volm'/'outp'`），`AVOutputContext` `((none))` 来自 `VirtualAudio` 未提供 `kFigEndpointProperty_ID`。
