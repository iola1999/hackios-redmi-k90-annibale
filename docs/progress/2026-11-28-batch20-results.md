# 2026-11-28 批 20 真机实测、代码交付与下批方案（b5r61～b5r63）

本记录汇总批 20 全部三轮真机实测（`12377-b20`、`12377-b20r2`、`12377-b20r3`）、已合入代码与宿主测试结果，以及批 20 产出的离线根因定案与批 21 方案。三轮测试全零 `panic(`、`gpu_fault`、`submissions closed`、`smmu fault` 与 `backlight-off`，`b5r63` 结束后设备继续保持在 iOS 桌面健康运行态（`result: running 0 0`、`ramdisk-state: ready 1ec9000 1ec9000 300000000`）。

## 1. 轮次产物与真机结果总览

| 轮次 | 内核产物（字节 / SHA-256） | 打包与注入参数 | 核心结果与实测目录 |
|---|---|---|---|
| `b5r61` | `12377-b20`（`21,090,608` / `e8d17772...`） | `JOB_ENV="com.apple.backboardd.plist:ANNIBALE_DAMAGE_PROBE=1"`，`etc/inject.conf` `957` B | `M6` 前摄 `-16808`/`-31710` 清零、`M4` 3 槽连拍全过、`S7` `528` 窗全满高转 DPU、`S12` `BiomeStorageError=0`、`S11` `copyio_abort=0`、`P14` `<4G alloc fail=0`（`hyp_assign=(-2,0x56)`），`docs/progress/evidence/k90auto/kernel-12377-b20-b5r61/` |
| `b5r62` | `12377-b20r2`（`21,090,608` / `94f73449...`） | `SB26_EXTRA="Weather"` `OSLOG="wifid"`（`inject.conf` `1009` B），`EXTRA_SHARE` `hevc10.mp4`（`49376` B） | `M1` HEVC Main 10 P010 `15/15 PASS`（`error=5` `0`）、`G32` 锁定 `SwiftUI.GradientLayer (0,0,0,0)` + `L30 destIn` 根因、`P14` 单 VMID `hyp_assign=(-2,0x56)`，`docs/progress/evidence/k90auto/kernel-12377-b20r2-b5r62/` |
| `b5r63` | `12377-b20r3`（`21,090,712` / `36b88feb...`） | `OSLOG="wifid"` `OSLOG_MATCH="corewifi\|ADDED\|MISSING\|FAILED\|INVALIDAT"` `XPCWATCH="a80211_test"` | `P14` `{0x16,0x25} perm=7 hyp_assign=(0,0)` 通过（下卡点 `sensorspd 0x80000484`）、`P21` `cwjoin` 重定位至 `wifid` `ADDED -> INVALIDATED`（`4097`）、`M3` 并发音量键 `1.000->0.457->0.520`、`G31` `WebKit.GPU` `19` 条 trace 与 `backboardd.harvest`（`6,667,716` B）拉取，`docs/progress/evidence/k90auto/kernel-12377-b20r3-b5r63/` |

## 2. 批 20 已合入代码与宿主测试

- **`G11`（`b5r61` 内核与宿主测试）**：改动 `adreno8_private.h`、`adreno8_hfi.c`（`959` 行）、`adreno8_gpu_private.h`、`adreno8_gpu.c`（`985` 行）、`adreno8_context.c`（`624` 行）、`annibale_gpu_dispatch.c`（`309` 行）、`annibale_input.h`、`AnnibaleGPU.cpp`（`1150` 行）与 `AnnibaleGPUWait.inc`（`89` 行），补齐 `IB rem`、GMU 常亮状态、HFI 指针诊断与 GX 掉电守卫；`test-adreno8-g11-hang.py`（`325` 行）与 `test-annibale-gpu-lifetime.py`（37 场景 + 13 变异 + GX-off）全通过。
- **`S11`（`b5r61` 内核）**：`44-osfmk%arm64%sleh.c.patch`（`109` 行）在 `sleh.c:2718` 新增 `copyio_fault_trace()`（原子 `8+8` 配额分记 `locationd` 与其他进程用户态缺页 `EFAULT`），`patch --dry-run`、`git apply --check` 与 `-Weverything` 均退出 `0`。
- **`S12`（`b5r61` 内核与宿主测试）**：`apfs_vnops.c`（`1199` 行）对孤儿非目录节点返回 `va_nlink = 0u`；`test-apfs-wresize-cprotect.py`（`224` 行）新增 case 7 验证通过。
- **`M1`（`b5r61` 内核与宿主测试）**：`annibale_iris_hfi.c`（`1187` 行）在 `s->is_10bit` 下将输出缓冲 `y_stride` 与 `uv_stride` 减半以匹配 HFI 线性布局并保持 `bsz == dsz`；`iris-hfi-wire.fixture.c`（`862` 行）与 `test-iris-hfi-wire.py`（`694` 行）`219+24+92` 项全部通过。
- **`P14`（`b5r61`～`b5r62` 内核与低区配置）**：`b5r61` 在 `annibale_adsp_fastrpc_rpc.inc`（`997` 行）新增 `adsp_fastrpc_lowdma_pick()` 并在 `tools/mk-ath12k.sh`（`187` 行）调整 `LX_POOL_MB=80u`/`LX_RINGS_MB=48u` 留出 `<4G` 连续池；`b5r62`（`1022` 行）加入 `ADSP_FASTRPC_VMID_ADSP_HEAP = 0x25u` 与 `adsp_fastrpc_assign_heap()` 单 VMID 试探。
- **`P14`（`b5r63` 双 VMID 与宿主测试）**：在 `annibale_ipa.c`（`1188` 行）新增 `QCOM_PERM_RWX = 7u` 与 `annibale_tz_assign_mem_perms()`，`annibale_adsp_fastrpc_rpc.inc`（`1027` 行）按双 VMID `{0x16, 0x25}` 试探 `RWX(7)`/`RW(6)`；`test-adsp-fastrpc-probe.py`（`624` 行）与 `test-annibale-modem-loader.py`（`1200` 行）全通过。
- **`M3`（`b5r61` 用户态）**：`audio_plugin.c`（`1174` 行）新增 `speaker_output_scope()`、为 `OBJECT_SPEAKER` 上报 `PropertiesChanged` 并在 `initialize()` 调用 `volume_to_kernel()`；`test-audio-plugin.py`（`257` 行，ASan+UBSan）`10/10` 通过。
- **`M4`（`b5r61` 用户态）**：`camera_device.c`（`1192` 行）、`camera_device_stream.inc`（`968` 行）与 `camera_device_worker.inc`（`597` 行）建立 `STILL_POOL_SLOTS = 3` 缓冲池与 `still_deliver_queue` 解耦投递（`still_prepare()`、`still_dispatch()`、`still_release_slot()`、`still_deliver()`）；`test-camera-still-pool.py`（`229` 行，ASan+UBSan）通过。
- **`M6` 与 `G32`（`b5r61` 用户态）**：`mkcameraresources.py`（`109` 行）补齐 `smartCameraSupported`、`LensSmudgeDetectionSupported`、`geometricDistortionCorrection`、`geometricDistortionCorrectionForSmartCropEnabled` 与 `IntelligentDistortionCorrectionSupported` 五项键值（`test-mkcameraresources.py` `95` 行 `2/2` 通过）；`inject_sb26_layers.c`（`1173` 行）放行 `"Weather"` 进程诊断。
- **`ENG-07` 与打包发布（`b5r61`）**：将 `statusbar26.m`（`124` 行）从 `ax.m`（`170` 行）拆分为独立 `libannibale-statusbar.dylib`，`tools/k90auto/package.py`（`1199` 行）支持 `SB26_EXTRA`，`tools/release/build-all.sh` 切换 `AX="" SHARE=1`，`tools/release/build-release.py`（`435` 行）补齐 `verify_release_root()`；`tools/k90auto/tests/test-ui.py`（`202` 行）`14/14`、`test-tools.py` `52/52` 与 `test-build-release-provenance.py` `4/4` 均通过。
- **`P21` 与诊断工具（`b5r63` 用户态）**：`annsh.c`（`1011` 行）新增 `bg` 内建命令及 `bg_pids[32]` 槽位（`test-annsh-bg.py` `128` 行 ASan+UBSan、`test-annsh-process.py` `7/7` 通过）；`a80211_test.c`（`852` 行）新增 `cwf_show_err()`（打印 `code`/`domain`/`debugDescription`）并同轮对照 `bootstrap_look_up` 与 `bootstrap_look_up2(..., 0, 8)`。

## 3. b5r61（12377-b20）真机实测详情

- **`M6` 前摄 `-16808`/`-31710` 消除**：真机日志 `-16808 = 0`、`-31710 = 0`、`BWE5InferenceProvider` 报错为 `0`；`BWPhotonicEngineNode` 输出 `img=2496x1872@0x13d19d5e0 blk=0 redeye=0 lum=1:87 surf=434 seq=32`，`cam_front.png` 成像上下正立且画面清晰；前摄人像模式仍单独依赖 CPU E5 资源与 Pearl 硬件，未纳入本次修复。
- **`M4` 三槽连拍缓冲与解耦投递**：后摄 4 连拍触发 `BWPhotonicEngineNode`（`seq=9,15,21,27`，`2352x1764 420f`，`blk=0`），`all 3 still RAW slots busy = 0`、`0` skipped、`0 ms in the queue`、`handler_ms = 0 ms`，`render_picture` `125–140 ms` 全移出锁外；预览间隔 `32.1–34.9 ms`（仅暗室 `15 fps` 档为 `66–67 ms`），`ldob8 = 0`，`tl: C` `164` 行（`seq 2 foc 8/96962`、`foc 2/11095..12159`）零报错。
- **`S7` 阶段 2 结案**：`ANNIBALE_DAMAGE_PROBE=1` 全轮采集 `528` 个 30 帧窗口（`15,840` 帧），全部命中 `all_scissored=30/30 h_buckets=0/0/0/30 h_p50=2622 h_p90=2622`，证实基于单帧脏区剪裁无法缩减合成拷贝高度，阶段 2 据此结案并转由 DPU 硬件缩放替代。
- **`G7` 与相机下采样核报错**：离线 `corpus.py` 维持 `450/463 (97%)`，其余 13 项全部为 `Apple4+` 隐式 `air.imageblock`（`metal_profile=4` 下不触发调度）；相机期间命中 `9` 次 `kernelRec709DownsampleYFilterOrder2: 18x18x1 = 324 > 256`。
- **`S12`、`S11`、`ENG-07` 与 `G11`**：`BiomeStorageError = 0` 且 `"Failed to create temporary file" = 0`；`copyio_abort = 0`（同轮另录得 `5` 次 `batteryintelligenced` `userabort`）；`/annibale/etc/inject.conf`（`957` B）正常拆分加载 `libannibale-statusbar.dylib`，`boot_home.png`、`boot_nc.png`、`settings.png`、`cc.png` 均正常；`G11` 随轮运行无回归（真机自然长挂起继续观察）。
- **`P14`、`G31` 与 `G14`**：`lowdma=0x00000000c772d000 lowdma_mb=128` 下 `<4G alloc fail = 0`、`fhw_test` `4/4 rc=0`，但 `adsp_mem_heap pa=0xcdc00000 sz=0xc00000 hyp_assign=(-2,0x56)`；`Maps` 捕获 `136` 条 `g31-trace`（`#0..#135`），`maps_mode.png` 4 个模式缩略图仍黑，`safari_tabs.png` 捕获底部格栅伪影。

## 4. b5r62（12377-b20r2）真机实测详情

- **`M1` HEVC Main 10 硬件解码通过**：`/annibale/bin/video_decode_test /annibale/share/b20-share/hevc10.mp4`（`49376` B）实测输出 `result=pass submitted=15 accepted=15 callbacks=15 frames=15 callback_errors=0 dropped=0 empty=0 pixel_errors=0 hardware=1 output_bytes=6912000`，`iris` 日志 `error=5` 为 `0`。
- **`G32` 天气全屏黑屏根因锁定**：`weather-layers-dump.txt`（`1,754` 行 / `311,489` B）与 `weather_main.png` 显示 10 天预报首行 `L85 CGDrawingLayer 53x4` 渐变可见，第 2～10 行 `SwiftUI.GradientLayer` 全呈 `[0,0,0]`；全部 `SwiftUI.GradientLayer` 输出 `(0,0,0,0)` 导致 `L30`（`backgroundMask`，`fx=__NSCFConstantString` `destIn` `rgb/alpha 0/4`）把原本不透明的 `VFX.VFXCoreView` 夜空（`VfxLlnXh` + `Tcma*Lln*`，归属 `backboardd` 合成）乘零遮黑。
- **`P14` 单 VMID 边界确认**：在 `0xcdc00000` 上连续尝试 `(0x25,0)`、`(0x25,1)` 与 `(0x16,0)`，QHEE 均返回 `hyp_assign=(-2,0x56)`。

## 5. b5r63（12377-b20r3）真机实测详情

- **`P14` 双 VMID 权限分配打通**：内核日志首次打印 `aadsp: fastrpc: adsp_mem_heap pa=0xcdc00000 sz=0xc00000 cnt=2 vmids=0x16,0x25 perm=7 hyp_assign=(0,0)`；随后推进至下一阶段报错 `INIT_CREATE_STATIC(sensorspd)` `-2147482492 (0x80000484)` 与 `INIT_ATTACH_SNS` `-2147482608 (0x80000410)`，`fhw_test` 仍为 `4/4 rc=0`。
- **`P21` `cwjoin` 边界重定因**：`corewifi-xpc plain=0(p=0x1d03) flags8=0(p=0x1d03)` 与 `xpcwatch lookup com.apple.private.corewifi-xpc 1` 确认服务查表成功；`wifid` `oslog`（`115` 行、含 `corewifi` `114` 行）记录 `ADDED XPC CONNECTION a80211_test [pid=344, euid=0, egid=0 uuid=DCF22]` 后立即 `INVALIDATED XPC CONNECTION`（`MISSING=0`、`FAILED=0`），`cwf_show_err` 返回 `code=4097`（`NSXPCConnectionInterrupted` / `NSCocoaErrorDomain`），排除了 `4099` 服务未发现猜测。
- **`M3` 并发按键音量单调生效**：`bg /annibale/bin/sound_test activate route tone 12 route`（`bg pid=346`）并发按 `voldown` 与 `volup` 时，内核实际扬声器音量随按键单调变化：`1.000: 0.0 dB under the loudest` -> `0.457: 26.0 dB under the loudest` -> `0.520: 23.0 dB under the loudest`；单独执行 `sound_test route` 默认路径仍回落显示 `volume 0.50`。
- **`G31`/`G14` 采样与 `backboardd.harvest` 拉取**：`safari_tabs.png`（10 标签页网格）未再现底部格栅伪影，并成功采得 `19` 条 `WebKit.GPU` `g31-trace`（`#0..#18`）；`maps_mode.png` 4 个模式缩略图仍黑；已从设备拉取 `/private/var/db/annibale-pipeharvest/backboardd.harvest`（`6,667,716` B）供批 21 离线分析。

## 6. 批 20 产出的离线根因定案与批 21 方案

- **`kernelRec709DownsampleYFilterOrder2`（`324 > 256`）根因**：批 20 定位 `air_metal_compute.inc:458` 仅在 `!split` 分支更新 `compute->caps.max_threads_per_group`（停留在 `max_reg 47` 对应的 `256`），导致 `air_metal_dispatch.inc:112` 错误拦截已编译通过的 `max_reg 31` `split` CSO（`si.max_threads >= 324`），批 21 修复条件即可放行。
- **`G32` 天气渐变零输出排查**：基于批 20 拉取的 `backboardd.harvest`（`6,667,716` B）在批 21 用 `air2nir` 离线反编译 `VfxLlnXh` 与 `Tcma*Lln*`，定位 `SwiftUI.GradientLayer` 返回 `(0,0,0,0)` 的着色器路径。
- **`S12` 桌面天气小组件「天气不可用」**：批 20 查明 `chronod` 报错源自 `ATXInfoTimelineDonationClient` 缺失 `com.apple.proactive.infoSuggestion.xpc`（`Code=4099`，`error 3 - No such process`），并伴随 `SQLITE_OPEN_FILEPROTECTION_*` 与缺少系统 persona 日志。
- **`G30` 阶段 3、DPU 缩放、PDAF 与 `P23` 阶段 2 设计就绪**：批 20 同步产出 `G30` 阶段 3 设计（16 槽位池、5-bit 槽号 + 27-bit fence 编码、每客户端 `SubmitQueue` 与 `HFI 150/133` 上下文故障隔离）、`S7` DPU QSEED3LITE 硬件缩放方案（`fb_dpu_scale=1` 接管 `vig0`/`vig1`）、`M4` `OVX8000` Mode 24 `VC1` PDAF 方案（`2560×480` RAW10、`GT24P128F` `0x51`、`vfe-lite980` `RDI1=0x600`/`WM1=0x1800`）与 `P23` 阶段 2 设计（`cluster1` `CL5` `0x01000054`、`9144 us`），与 `P14` `sensorspd 0x80000484`、`P21` `wifid INVALIDATED`、`M3` 默认展示口径、`G14` 地图黑缩略图一并转入批 21。
