# 2026-11-28 批 28 多线验收、帧缓存 YUV 合成与驱动修复（b5r83 活机 + b5r84～b5r86）

本记录汇总批 28（Waves 1–5）的真机验收与驱动改动，覆盖 `b5r83` 零重启活机复测以及 `b5r84`（`12377-b28`）、`b5r85`（`12377-b28r2`）、`b5r86`（`12377-b28r3`）三轮真机验证。四项阶段工作全程零 `panic(`、`gpu_fault`、`submissions closed`、`AnnibaleGPU client refused`、`smmu fault` 与 `No system apps remain`，设备均保持健康 iOS 桌面运行态（`running-held`）。

## 1. 图形与显示验收（G6 可清除纹理、G14 地图模式与 G31 复核）

- **`G6` 可清除 `MTLTexture` 构建核对**：`libannibaleair.dylib` 已导出 `_rwa_texture_set_purgeable` 与 `_rwa_texture_is_purgeable`，`libannibalemetal.dylib` 已编入状态机与 `commit_in_flight` 守卫。
- **`G6` `b5r83` 实机验收通过**：在 `b5r83` 运行 `out/b28-diag/g6_live_test`（`1024×1536` `BGRA8Unorm` `6 MiB`，`exit 0 / 166 ms`），实测 `KeepCurrent` -> `NonVolatile` 回读 `(191,128,64,255)` -> `Volatile` -> `NonVolatile` 像素保持 -> `Empty` 释放显存 -> `Empty->Volatile` -> `Empty->NonVolatile` 重建绘制 `(128,64,191,255)` -> `Empty`，输出 `g6: ALL PASS (fails=0)` 且零故障，`G6` 归入 `graphics.md §3`。
- **`G14` 地图四模式缩略图恢复**：`b5r83` 实拍 `out/b28-diag/maps_mode_b5r83.png` 确认「探索」「驾车」「公共交通」「卫星」4 张缩略图全彩锐利渲染，道路、路况标线与卫星影像正常；`out/b28-diag/g14-maps-b5r83.log`（`21,142` 行，含 `SnapshotService` `36` 行）`draw-failed=0`、零硬件故障。确认随批 27 `is_frag_depth_store_deref()` 修复一并解决，`G14` 归入 `graphics.md §3`。
- **`G31` Safari 标签概览格栅伪影复核**：批 27 缺陷触发时确定性产生全图纯黑 `NaN` 或空输出，而 `G31` 表现为 `y=1000..1300` 区域 `92~96` 像素周期性纯 Alpha 格栅且呈间歇性，属于独立的 RenderPass / Alpha 状态问题，继续留在 `graphics.md §1` 观察并在后续命中同轮抓 `g31-trace.txt` 定位。

## 2. backboardd 0xf1 取消映射清零（air_metal_texture.inc / b5r84）

- **惰性/零冗余 `0x7c` CPU 映射改造**：`buffer_import_handle()` 在 `hackios-xnu-userland/tools/mesa/air/air_metal_texture.inc`（`937` 行）新增 `void *host_bytes` 参数。来自 `rwa_buffer_from_memory()`（`-newBufferWithBytesNoCopy:` / `0x7c`）且持有效 `bytes` 时直接令 `buffer->map = host_bytes; buffer->xfer = NULL;`，省去 `pipe_buffer_map()`（`0xf0`）、`fd_bo_prefault()` 与销毁时持 `rwa_lock` 同步 `IOConnectUnmapMemory64`（`0xf1`）写锁开销；`rwa_buffer_from_surface()` 保持原路径。
- **构建与单测**：新建 `hackios-xnu-userland/tools/mesa/tests/test-air-memory-buffer.py`（`536` 行，ASan+UBSan `-Werror`）通过 `--mutations`（拦截 `4` 项变异），`test-air-rwa-lock-narrowing.py`、`test-air-purgeable.py`、`test-air-frag-depth-store-filter.py`、`test-air-cache-key.py`（`424` 项）、`test-air-cache-store.py`、`test-air-identity.py`（`5/5`）与 `test-fd-bo-cache-reuse.py --mutations`（`11` 项）全过，`libannibaleair.dylib` 刷新至 `LC_UUID = 6DACE8D5-658F-35B3-A6AE-6D58A733705F`。
- **`b5r84` 实测收益**：`weather-scroll-b5r84.log`（`backboardd[38]` 4 个连续 4000 ms 窗）实测 **`0xf1` 降至 `0` 次 / `0 ms`**（对比 `b5r83` `76–83` 次 / `109.3–129.9 ms/5s`），`0xf0` 首窗后降至 `0` 次；天气详情末 5s 滚动窗 `535` 帧达成 **`107.1 fps`**、`dt_max=33.88 ms`、`>20 ms` 间隙由 `25` 次降至 **`4` 次**，`draw-failed=0`。

## 3. S11 batteryintelligenced 崩溃修复（AnnibaleBattery.cpp / b5r85）

- **异常契约定位**：`b5r84` 337 s 触发 `batteryintelligenced`（`pid 234`）崩溃，反汇编 `BatteryAlgorithms` 确认 `validateDataFromDictionaryWithTeq` 向 `convertTeqIntoScalar(NSData*, ...)` 传入 `LifetimeData["TimeAtHighSoc"]` 后调用 `[x19 bytes]`（收到 `OSNumber` 引发 `-[__NSCFNumber bytes]`），且 `ChargerData["VacVoltageLimit"] = 5000` 超出 `[4335, 4505]` 校验区间。
- **修复与宿主单测**：修改 `hackios-xnu-kernel/xnu/files/iokit/Kernel/AnnibaleBattery.cpp`（`340` 行），在 `AnnibaleBattery::dicts()` 为 `LifetimeData` 写入 `TotalOperatingTime=0`、`CycleCountLastQmax` 与 4 字节零值 `OSData` 类型的 `TimeAtHighSoc`，将 `ChargerData["VacVoltageLimit"]` 设为 `4400u`。`test-battery-temperature.py`（`335` 行）`23/23` 通过。
- **跨崩溃窗口真机验收**：`b5r85` 自然运行至 `432.50 s`（完整跨过 `305..350 s` `dailytask` 崩溃窗口），`batteryintelligenced` PID `201 -> 201` 全程存活、`CrashReporter/` 新增 `.ips` 为 `0`、全日志 `userabort` 为 `0`；`b5r86` 亦保持 PID `227` 稳定运行且无新增崩溃。`S11` 中 `batteryintelligenced` 子项归入 `system.md §3`。

## 4. P14 ADSP GLINK 意图排空与 SENSORS_PD 二分（b5r85）

- **GLINK 重入队列修复**：定位 `glink_poll_rx()` 在 `adsp_fastrpc_has_pending()` 为真时提前 `break`，未排空同批跟在 `rx #2` 后的 `GLINK_DONE_REUSE`，导致回退发包因无可用 intent 过早置 `FASTRPC_STAGE_FAILED`。修改 `annibale_adsp.c`（`1199` 行）仅在 `!adsp_fastrpc_rx_has_space()` 时跳出，并在 `annibale_adsp_fastrpc_rpc.inc`（`1034` 行）与 `annibale_adsp_fastrpc.inc`（`714` 行）新增 `tx_pending` 延迟重发与 `adsp_fastrpc_sid_hi()`（`ADSP_FASTRPC_SENSORS_PD` 传 `sid_hi = 0ULL`）。
- **宿主与 `b5r85` 实测结论**：`test-adsp-fastrpc-probe.py`（`774` 行，ASan+UBSan）通过；`b5r85` 开机打通 **`rx #3: INIT_ATTACH(root) -> retval=0 (0)`** 延迟续发回退，同时实证 `SENSORS_PD` 在 `sid_hi = 0ULL` 下仍返 `-2147482608 (0x80000410, AEE_EBADITEM)`，排除了 `compute-cb@2` SMMU SID（`0x1004`）为主因，后续转向 `adsp.b25`/`SSCRPCD`/QMI `servreg` instance `74` 服务就绪契约。

## 5. M4 Safari 带音频彩色视频播放（MiniFramebufferYuv.inc / b5r86）

- **多平面叠加根因**：解码样本 `hackios-xnu-userland/out/av-test-4s.mp4` 120/120 帧全部为彩色 SMPTE 条纹，而 Safari 播放时 `backboardd` 将解码出的 `'420v'` 表面挂到 `IOMobileFramebuffer` layer 2（`layers=0x6: 0 7 381 0`），`MiniIOMobileFramebuffer.cpp` 原先跳过非 32-bit 表面导致挖空区全黑。
- **双平面 YUV 缩放与多层合成**：新增 `hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferYuv.inc`（`477` 行，同步将 `MiniIOMobileFramebuffer.cpp` 从 `1238` 减至 `1187` 行），实现 `'420v'`/`'420f'`（BT.601/BT.709/BT.2020）缩放转换及 `layer 3 -> 0` 预乘 `srcOver` 合成，保持单层 32-bit 快速路径零额外开销。
- **宿主验证与内核构建**：`test-framebuffer-yuv-composite.py`（`239` 行，ASan+UBSan，含 2 项变异）、`test-fb-flip-rows.py`、`test-iomfb-selectors.py`、`test-fb-frame-info.py` 全过，编译产出 `xnu12377-b28r3.bin`（`21,111,160` B，`sha256` `481ff89a983617476ba45b3fa829f91855523256262799ca89d14fa655710297`）。
- **`b5r86` Safari 实机画面验收**：本地 HTTP 提供 `/annibale/share/av-test-4s.mp4` 并在 Safari 点击播放，日志命中 `planar layer 2 surface 182 '420v' 640x360 src=0,0+640x360 dst=0,979+1206x678 yBPR=640 uvBPR=640 ycbcr=6 layers=0x6`；`m4_safari_playing.png`（`2510×1156`）中心 `16:9` 视频区非黑像素占比 **`0.9877`**、均值 RGB **`(107.59, 112.97, 109.51)`**（彩色 SMPTE 条纹与 `00:00:01.067 / 32` 清晰可见）。
- **`b5r86` 播放收尾与声音同步**：`m4_safari_ended.png` 控制栏叠加完整，`daudio: PCM periods`（`slot 0..7`）正常出声，`M4` Safari 带音频视频播放项归入 `multimedia.md §3`。

## 6. P2 VirtualAudioDevice_Actuator HAL 对象 ID 解析与 Haptic 2.0 进度（b5r86）

- **HAL UID 解析修复与文件拆分**：`audio_plugin_actuator.inc`（`416` 行，从 `1166` 行的 `audio_plugin.c` 拆出 `OBJECT_ACTUATOR` 属性）在 Wave 2 对齐了 `VirtualAudioDevice_Actuator` 与 `'dacp'`/`'ptyp'='pact'` 等属性后，`b5r85` 捕获 `'uidd'` + `qualifierSize=0` 触发 `HALS_System.cpp:4511` 长度错误。Wave 5 将主查询改为 `'duid'`（`PROP_SYSTEM_TRANSLATE_UID_TO_DEVICE`）+ 32 B `AudioValueTranslation`，并新增 `'dev#'`/`'uid '` 回退枚举。
- **验证与当前边界**：`test-audio-plugin.py`（`426` 行，ASan+UBSan `-Werror`）`13/13` 通过；`b5r86` 首次实现 **`annibale: audio: actuator HAL object ID resolved: 51`**，`bad qualifier data size` 降至 **`0`**，运行期 `p2-haptic-b5r86.log` 中 `AVHapticClient` `Code=4099` 降至 **`0`** 条（开机 `audiomxd` 仍含 `3` 条 `AVHapticClient.mm:1160/1246/1212`），`sound_test route`（`Speaker`，`volume 0.50`）零退化。`\"=== Initializing Haptic 2.0 Engine ===\"` 尚未触发，剩余阻塞仍在 `com.apple.audio.hapticd` XPC 初始超时（`AVHapticClient.mm:1160`），留在 `platform.md` 跟进。

## 7. 电源硬件只读核查与批 28 轮次总览

- **`S3` / `P8` / `P12` 只读实测（`b5r83`）**：`/annibale/bin/battery_test` 实测 `BQ27Z561` `SOC=96%`、`V=4378 mV`、`I=-139 mA`、`T=34.85 °C`、`from the DSP 1`；`AnnibaleBattery` `DesignCapacity=7100`、`NominalChargeCapacity=6397`、`AppleRawMaxCapacity=6397`、`AppleRawCurrentCapacity=6149`、`CycleCount=84`、`ExternalConnected=yes`、`IsCharging=yes`、`FullyCharged=yes`、`AdapterDetails={Watts=3, AdapterVoltage=5083, Current=500}`。

| 轮次 | 内核与产物版本 | 关键验证与实测目录 |
|---|---|---|
| `b5r83` 活机诊断 | `12377-b27` + `g6_live_test` + Maps | `G6` `ALL PASS (fails=0)`、`G14` `maps_mode_b5r83.png` 4 模式全彩、`S3`/`P8` 读数正常，`out/b28-diag/` |
| `b5r84` | `12377-b28`（`0b747964...`）+ `6DACE8D5` `libannibaleair` | `backboardd[38]` `0xf1` 清零（`0/0ms`）、滚动末窗 `107.1 fps`，`P2` 激活 `device 51`，暴露 `'uidd'` 与 `TimeAtHighSoc` 异常，`docs/progress/evidence/k90auto/kernel-12377-b28-b5r84/` |
| `b5r85` | `12377-b28r2`（`81a47d7e...`） | `S11` 过 `432.50 s`（PID `201->201`、`0` `.ips`/`userabort`）；`P14` 打通 `INIT_ATTACH(root)->0`、`SENSORS_PD` `sid_hi=0` 仍 `0x80000410`，`docs/progress/evidence/k90auto/kernel-12377-b28r2-b5r85/` |
| `b5r86` | `12377-b28r3`（`481ff89a...`）+ `root26.apfs` | `P2` 解析 `HAL ID 51`（`bad qualifier=0`、`Code=4099` 开机 `3`/运行 `0`）；`M4` Safari `'420v'` 彩条+音频播放通过（`0.9877` 非黑、`daudio` 正常），`docs/progress/evidence/k90auto/kernel-12377-b28r3-b5r86/` |
