# 锁屏与静置发热治理及显示图形管线优化跟踪（2026-11-09）

本文记录 2026-11-09 锁屏静置发热、开机亮度跳变、后台守护进程崩溃循环及图形显示管线 6 项优化的实测归因、根因修复与真机连续开机验证结果。汇总入口见[进度表](../plan/2026-10-23-tracking.md)。

## 1. 基线实测数据与根因归档

基于 `boot-fixed2`（内核 `aa0948db`）开机及锁屏静置日志（本地 `out/diag-2039/live-fixed2-2.log`、`out/diag-2039/live-idle-heat.log`）与 `annsh` 进程采样：

| 观测维度 | 基线实测读数 | 代码位置与根因 |
|---|---|---|
| 锁屏静置温度与频率 | CPU 簇 0 最高 74.0 °C（2227～2400 MHz 占比 >50%），CPU 簇 1 最高 74.8 °C（1209～1958 MHz），GPU 64.5 °C（恒定 1100 MHz） | 锁屏底部 `source rows 2443..2597`（155 行提示条动画）按 120 Hz 变化，因 `CA_DISABLE_DIRTY_REGIONS=1` 触发每秒 120 次 `1206×2622` 全屏 GPU 重绘与内核 CPU 逐行哈希缩放（单帧驱动耗时 13.7～15.2 ms） |
| 桌面静置 GPU 锁频 | 桌面仅时钟图标秒针以 10 FPS 刷新，GPU 每 5 秒工作 152～330 ms（真实占空比 3.0%～6.6%），但频率恒定在 1100 MHz | `xnu/files/bsd/dev/adreno8/adreno8_hfi.c` 的 `adreno8_speed_tick()` 将当前频率耗时按 160 MHz 放大 6.875 倍计算 `permille`，1100 MHz 下真实占空比达 2.91% 即触发直跳 1100 MHz，且需低于 1.45% 持续 500 ms 才降回 342 MHz，中间 10 个频点未使用 |
| 开机亮度先满亮后骤降 | 开机 0.3 s 内核写 `#1 51 1a 5e`（100% 亮度，6750）；约 33 s 后 `backboardd` 解除 `FreezeBrightness`，按 `synchronizeALSPreferencesAndDisplayBrightness` 将面板渐变降至 `0x95`（149，13.475 nits，2.2% 亮度） | `MiniFramebufferDCS.inc` 开机写 `DCS_PANEL_MAX`（`0x1a5e`），`MiniAppleARMBacklight.cpp` 初始发布 400 nits；约 33 s 解冻时 `DisplayBrightnessSliderPosition` 与 `IOMFBBrightnessLevel` 同时下发自动亮度同步值，被误判为滑块拖动而放行 13.475 nits 降光；锁屏超时下发 `0 nits` 时又因 `s16 <= 0` 被丢弃 |
| 后台守护进程崩溃循环 | `nearbyd` 每 15～20 秒 `userabort` 重启一次（PID 335→416），触发 `osanalyticshelper` 写报告落盘 | K90 无苹果 UWB 芯片（`DeviceProximityCapability` 为假，芯片类型 2），`nearbyd` 在 `iPhone18,3`（设备类型 26）分支触发 `ConstructRegulatoryTxPowerTableMap` 断言（见[用户态崩溃报告](../analysis/2026-11-09-crash-reports.md) §5） |

## 2. 优化队列与验证汇总

6 项优化已全部合入并通过宿主单测与 K90 真机连续两次开机（`out/diag-2039/boot-opt1/`，`boot_a` 镜像 `22,546,432` 字节，SHA-256 `0468a427…`）验证：

| 序号 | 优化项 | 涉及模块 | 状态 | 真机验证结果与提交 |
|---|---|---|---|---|
| 1 | GPU 阶梯式按需调频与触摸提频收敛 | `xnu/files/bsd/dev/adreno8/adreno8_hfi.c` | 已完成 | GPU 频率随负载在 160～1100 MHz 共 14 档间按需切换；开机与设置交互期 GPU 44.4～49.8 °C、CPU 53.1～59.7 °C，桌面稳态（14 分钟）降至 CPU 簇 0 38.4 °C、簇 1 39.1 °C、GPU 40.5 °C（160 MHz），较基线降温 24～35 °C（内核 `0e0f19bb`） |
| 2 | 开机沿用上次亮度（阻止 33 s 解冻骤降）及熄屏归零 | `MiniFramebufferDCS.inc`、`MiniAppleARMBacklight.cpp`、`ramfs_disk.inc`、`ramfs_disk_mount.inc` | 已完成 | 无有效持久化记录或记录越界时默认写 `DCS_PANEL_MAX`（6750，400 nits），有效用户记录随 `darwin_var` 挂载恢复；33 s 解冻时的非滑块 `IOMFBBrightnessLevel` 降光被拦截（`framebuffer update outside slider window ignored, keeping 400.000 nits`），开机全程保持 400 nits；锁屏超时 `s16 <= 0` 正常归零熄屏（内核 `0e0f19bb`） |
| 3 | 止住 `nearbyd` 后台守护进程崩溃重启循环 | `userland/mkjobs.py` | 已完成 | `com.apple.nearbyd.plist` 列入 `DISABLED_LAUNCHD_PLISTS`；两次开机日志中 `nearbyd` 启动与崩溃均为 0 次（用户态 `e052bd4`） |
| 4 | CoreAnimation 脏区局部重绘（`DIRTY_REGIONS=1`）残留与停绘根因修复 | `tools/userland-driver/annibalemetal_renderencoder.inc`、`tools/k90auto/package.py` | 已完成 | 修复 `endEncoding` 存在 `prior_copy` 时未同步等待内部拷贝命令完成即返回导致主命令缓冲区读到未完成纹理的竞态；默认开启 `DIRTY_REGIONS=1`，主屏、TrollStore 与设置页渲染无残留，50% 以上帧跳过未变化行（内核 `0e0f19bb`） |
| 5 | 面板上屏与缩放开销优化 | `MiniFramebufferScale.h`、`MiniFramebufferRows.inc`、`MiniIOMobileFramebuffer.cpp` | 已完成 | 预计算 X 方向插值表并以 64 位双像素 SWAR 合成，全屏哈希改为 64 位 8 路步进，跳过无变化帧背光脉冲重写；单帧驱动耗时由 13.7～15.2 ms 降至 3.29～5.28 ms（无变化帧 0.69 ms）（内核 `0e0f19bb`） |
| 6 | `ir3` 着色器磁盘缓存跨开机黑屏与跨进程未命中修复及启用 | `0015-ir3-disk-cache-darwin-uuid.patch`、`inject_sb26.c`、`ramfs_disk.inc`、`setup-mesa-arm64e.py`、`build-air.py` | 已完成 | 补齐跨 UID（`501`／`254`）缓存目录 `0777` 与文件 `0666` 权限、`ramfs_disk_flush_all()` 的 `MAP_SHARED` 脏页 `ubc_msync` 落盘，以及 `inject_sb26.c` 解锁前唤醒屏幕；第二次开机 `backboardd` 命中 `61 hits, 3 stores`（命中率 95.3%），`iconservicesagent` 命中 `128 hits, 0 stores`（命中率 100%），`MercuryPosterExtension` 命中 `8 hits, 0 stores`，桌面图标全彩正常显示（内核 `0e0f19bb`、用户态 `e052bd4`） |

## 3. 分项实施与验证记录

### 3.1 第 1 项：GPU 阶梯式按需调频与触摸提频收敛

- 根因：`adreno8_speed_tick()` 原先只在 `floor`（默认第 3 档，342 MHz）与 `adreno8_speed_asked`（第 14 档，1100 MHz）两档间二元切换，且将当前频率下的工作耗时按 160 MHz 放大 6.875 倍折算 `permille`，1100 MHz 下真实占空比达 2.91% 即锁死 1100 MHz 与最高 DDR 带宽票（`bus = 11`）；触摸提频无条件将 GPU 拉到 1100 MHz 保持 1500 ms。
- 修复（`xnu/files/bsd/dev/adreno8/adreno8_hfi.c`）：
  1. 按当前频点真实工作耗时与目标占空比（65%）计算所需频率 `need_hz = cur_hz * busy_pct / 65`，在 `1..adreno8_speed_asked` 共 14 个频点（160～1100 MHz）及对应 DDR 带宽票间逐级选档。
  2. 空闲最低档 `adreno8_speed_floor` 默认设为 1（160 MHz，DDR 索引 2）；真实占空比高于 75% 时立即升档，低于 35% 持续 2 个周期（200 ms）后平滑降入目标档位。
  3. 触摸提频改为保底第 7 档（607 MHz，持续 350 ms），并在新触摸到达后的首次 GPU 提交（`adreno8_touch_poke()`）立即提频，真实负载超过 65% 时再按需升至更高档位。
- 验证：宿主单测 `tools/tests/test-adreno8-hfi.py` 通过；真机 `boot1-after-settings.log` 与 `boot2-later.log` 显示空闲时 GPU 稳定回落至 160 MHz，14 分钟稳态温度为 CPU 簇 0 38.4 °C、簇 1 39.1 °C、GPU 40.5 °C，电池温度 31.15 °C，电脑普通 USB 端口供电下净放电电流仅 `-71 mA`。

### 3.2 第 2 项：开机沿用上次亮度（阻止 33 s 解冻骤降）及背光门控修复

- 根因：
  1. 开机约 33 s `SpringBoard` 完成启动并解除 `BKSystemApplicationBacklightLockReason` 时，`backboardd` 执行自动亮度偏好同步（`synchronizeALSPreferencesAndDisplayBrightness`），在同一轮属性更新中同时写入 `DisplayBrightnessSliderPosition` 与 `IOMFBBrightnessLevel`，把面板从 400 nits（`0x1a5e`）渐变压低至 13.475 nits（`0x95`）。
  2. `MiniAppleARMBacklight.cpp` 原先只要看到 `DisplayBrightnessSliderPosition` 就开启 2 秒滑块窗口，未能区分「开机首次解冻自动同步」与「用户在控制中心或设置中拖动滑块」；同时 `s16 <= 0`（锁屏超时熄屏下发 `0 nits`）被直接丢弃，导致锁屏超时后背光无法归零。
- 修复（`MiniFramebufferDCS.inc`、`MiniAppleARMBacklight.cpp`、`ramfs_disk.inc`、`ramfs_disk_mount.inc`）：
  1. 在 `ramfs_disk.inc` 盘面头部保留区新增面板亮度持久化字段（`saved_panel_brightness`），用户拖动滑块调光时经 `ramfs_disk_save_brightness()` 记录并在下一次元数据槽位写入时落盘；挂载 `/private/var`（`ramfs_disk_mount.inc`）时若读到合理范围内的非零亮度（`>= 150` DBV），调用 `MiniFramebufferRestoreSavedBrightness()` 恢复面板与 `MiniAppleARMBacklight` 初始值，无记录或记录过暗时默认保持 `DCS_PANEL_MAX`（`6750`，`400.000 nits`）。
  2. `MiniAppleARMBacklight::setProperties()` 忽略开机首次 `DisplayBrightnessSliderPosition` 初始同步，仅在后续滑块值发生实质变化（`delta >= 327`，约 0.5%）时开启 2 秒用户滑块窗口；窗口外到达的 `IOMFBBrightnessLevel` 非零降光请求直接拦截并保留当前亮度。
  3. 放行 `s16 <= 0`（`0 nits`）请求，调用 `MiniFramebufferSetBacklightLevel(0)` 将面板背光归零，唤醒点亮时恢复熄屏前的非零亮度。
- 验证：宿主单测 `tools/tests/test_challenger_m6_backlight.py`、`test-ramfs-disk-recovery.py`、`test-ramfs-sync-errors.py` 通过；真机两次开机全程保持 `6750`（`400.000 nits`），33 s 解冻时日志确认 `framebuffer update outside slider window ignored, keeping 400.000 nits`。

### 3.3 第 3 项：止住 `nearbyd` 后台守护进程崩溃重启循环

- 根因：K90 无苹果 UWB 芯片，`nearbyd` 启动后在 `ConstructRegulatoryTxPowerTableMap` 触发断言崩溃，launchd 每 15～20 秒重新拉起并触发 `osanalyticshelper` 生成崩溃报告落盘。
- 修复（`userland/mkjobs.py`）：将 `com.apple.nearbyd.plist` 加入 `DISABLED_LAUNCHD_PLISTS`，构建根盘时移除该守护进程的常驻拉起配置。
- 验证：宿主单测 `tools/tests/test_mkjobs.py` 通过；真机两次开机全程無 `nearbyd` 进程启动或 `userabort` 记录。

### 3.4 第 4 项：CoreAnimation 脏区局部重绘（`DIRTY_REGIONS=1`）残留与停绘根因修复

- 根因：开启局部重绘（`CA_DISABLE_DIRTY_REGIONS=0`）时，CoreAnimation 在渲染编码器之前通过驱动内部拷贝队列（`_copyQueue`）将上一帧未变化区域拷入当前可绘制纹理。[`annibalemetal_renderencoder.inc`](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_renderencoder.inc) 的 `endEncoding` 原先创建内部 `prior_copy` 命令缓冲区并调用 `[copy_cb commit]`，但未调用 `[copy_cb waitUntilCompleted]` 即返回，外层命令缓冲区随即提交主渲染管线，导致 GPU 在内部拷贝尚未完成时读写同一目标纹理，产生旧帧块残留与后续合成停滞。
- 修复（`annibalemetal_renderencoder.inc`、`tools/k90auto/package.py`）：
  1. 在 `endEncoding` 提交 `copy_cb` 后立即调用 `[copy_cb waitUntilCompleted]`，保证前序纹理拷贝在主渲染命令缓冲区提交前完成。
  2. `tools/k90auto/package.py` 的 `DIRTY_REGIONS` 默认值改为 `"1"`（不注入 `CA_DISABLE_DIRTY_REGIONS=1`）。
- 验证：真机 `boot1-home-p1.png`、`boot1-home-p2.png`、`boot1-real-settings2.png` 与 `boot2-later.png` 显示主屏翻页、TrollStore 与设置页均无局部重绘残留；日志确认 `19 of 40 frames had no row changed`，平均每帧仅重绘变化行。

### 3.5 第 5 项：面板上屏与缩放开销优化

- 根因：`MiniFramebufferScale.h` 与 `MiniFramebufferRows.inc` 原先在每次上屏时对每个目标像素动态计算源坐标与双线性权重，逐通道标量合成，且即使整帧无任何行变化也在每帧末尾重复发送背光脉冲。
- 修复（`MiniFramebufferScale.h`、`MiniFramebufferRows.inc`、`MiniIOMobileFramebuffer.cpp`）：
  1. 在 `MiniFramebufferScale.h` 中增加预计算 X 方向插值表 `MiniScaleXTable`（`x0`、`x1`、`wx`）与 64 位双通道 SWAR 双线性行缩放函数 `mini_scale_row_bilinear_xrgb8888()`，一次处理 2 个输出像素。
  2. 在 `MiniFramebufferRows.inc` 中将全屏脏区检测改为 64 位 8 路步进快速路径，跳过无变化行。
  3. 在 `MiniIOMobileFramebuffer.cpp` 中仅在 `changed_rows > 0` 时执行帧末背光重写。
- 验证：宿主单测 `test-fb-scale.py`、`test-fb-swap.py`、`test-frame-latch.py`、`test-frames.py` 通过；真机 10～14 FPS 桌面刷新窗口中单帧驱动耗时由基线的 `13.7～15.2 ms` 降至 `3.29～5.28 ms`（`3297～5284 us each in the driver`），无变化帧耗时 `0.69 ms`（`691 us`）。

### 3.6 第 6 项：`ir3` 着色器磁盘缓存跨开机黑屏与跨进程未命中修复及启用

- 排查、根因与实现细节见专门文档 [ir3 磁盘缓存跨开机实测与根因修复](../analysis/2026-11-09-ir3-disk-cache.md)。
- 真机连续两次开机实测结果：
  1. 第一次开机（冷缓存建库，`boot1-final.log`）：`backboardd` 记录 `31 hits, 161 stores`，`iconservicesagent` 记录 `97 hits, 159 stores`，`MercuryPosterExtension` 记录 `4 hits, 4 stores`。
  2. 第二次开机（热缓存命中，`boot2-desktop.log`／`boot2-later.log`）：`backboardd` 记录 `61 hits, 3 stores`（命中率 95.3%，`ir3 wait` 等待由 15 次降至 3 次），`iconservicesagent` 记录 `128 hits, 0 stores`（跨 UID `254` 命中率 100%），`MercuryPosterExtension` 记录 `8 hits, 0 stores`（命中率 100%）。
  3. 解锁后桌面截图（`boot2-later.png`）确认所有主屏与 Dock 图标全彩正常渲染，无跨开机黑屏。
