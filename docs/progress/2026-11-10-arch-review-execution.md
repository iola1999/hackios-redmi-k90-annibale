# 架构审查跟进、亮度同步、相机与触觉反馈推进记录（2026-11-10）

本文记录 2026-11-10 围绕 `v0.1.2` 发布、开机三里程碑时间戳与注入库 `LC_UUID` 自报、亮度滑块与物理面板同步、相机流属性与格式描述补齐、触觉反馈（`AVHapticServer`）及状态栏 Wi-Fi 图标的静态分析、代码实现与真机验证进展。汇总入口见[进度表](../plan/2026-10-23-tracking.md)，审查基准见[方案架构审查](../analysis/2026-11-08-architecture-review.md)。

## 1. 进展汇总

| 序号 | 事项 | 涉及模块 | 当前状态 | 结果与出处 |
|---|---|---|---|---|
| 1 | `v0.1.2` 发布与三仓推送 | `tools/release/`、三仓 `k90-port` | 已完成 | 构建并校验 `hackios-annibale-0.1.2-darwin-arm64.tar.gz`，推送顶层与两个代码子模块，发布 GitHub Release `v0.1.2` |
| 2 | 开机三里程碑时间戳与驱动／注入库 `LC_UUID` 自报（审查 §13、§16） | `rc.launchd`、`inject_sb26.c`、`annibalemetal.m`、`userland/src/inject/` | 已真机验证 | 真机 `out/s1110/verify1..4.log` 输出 `[boot-milestone] 1/3..3/3` 及 `backboardd`、`SpringBoard`、`iconservicesagent` 加载的驱动与注入库 `LC_UUID`（内核 `82028632`、用户态 `0d9ebbc`） |
| 3 | 相机设备与流属性及 `CMVideoFormatDescription` 补齐（审查 §10.3） | `camera_device.c`、`camera_device_stream.inc`、`inject_media.c` | 代码已完成，待合并上机验证 | 补齐 `CameraUI` 查询的 9 项设备属性、7 项流属性读写，并在 `IOSurface` 跨进程丢失宽高元数据时回退合成 1080×1920 BGRA 格式描述，消除 `-12710` |
| 4 | 屏幕亮度与控制中心滑块脱节修复 | `MiniAppleARMBacklight.cpp`、`input26_service.c`、`inject.c`、`ramfs_disk.inc` | 已定位根因，正在修复 | 查明 `input26_service.c` 在无硬件 ALS（`SE12 clk=0`）时注册虚拟 ALS 并以整数写入 16.16 定点字段 `FIELD_ALS_ILLUMINANCE`（`150 / 65536 = 0.0023 lux`），触发 `CoreBrightness` 自动降光至 `15.07%`（`32.477 nits`），叠加内核滑块窗口过滤丢弃 `IOMFBBrightnessLevel`，导致物理面板 `400 nits` 与控制中心滑块 `15%` 脱节 |
| 5 | 触觉反馈 `CHHapticEngine` `Code=4099` 与 `AVHapticServer` 启动（审查 §10.1、§11.1） | `GenericARMPE.cpp`、`audio_plugin.c` | 已定位根因，正在修复 | 反汇编确认 `VirtualAudio.plugin` 检查 `MGGetBoolAnswer("cBy4BcYs5YWtFHbBpt4C6A")`（`gIODTPlane` 节点 `"haptics"` 对应 MD5 Base64 `"6S9CvPHPtzHQqKudHSfsag"`）及 `AID8023` 2 通道 `'pact'` 端口映射 |
| 6 | 右上角状态栏 Wi-Fi 图标灰色问题 | `WiFi`／`SystemStatus` 链路 | 排查中 | 结合 `STUIStatusBarWifiSignalView` 渲染状态与 `WiFiManager`／`SystemStatus` 路径继续定位 |
| 7 | `xnuloader` 511 字节 USB Bulk OUT TRB 长度修正（审查 §11.2） | `loader_06_usb_entry.inc` | 待合入 | 将 511 字节控制块接收 TRB 长度对齐为 `max_pkt`（512 字节） |

## 2. 开机三里程碑时间戳与注入库 `LC_UUID` 自报（已完成）

按[方案架构审查](../analysis/2026-11-08-architecture-review.md) §13 与 §16 要求，补齐启动阶段耗时观测与动态库构建身份自检：

- 开机三里程碑时间戳：
  1. `1/3 userspace_init`：`rc.launchd` 启动时经 `sysctlbyname("kern.annibale.say", ...)` 输出内核日志。
  2. `2/3 springboard_checkin`：`SpringBoard` 加载 `libannibale.dylib` 进入构造函数时输出。
  3. `3/3 first_unlock`：首次解锁完成（`SBSRequestPasscodeUnlockAlertUI` 回调）时输出。
- 驱动与注入库 `LC_UUID` 自报：
  1. 原先 `log_own_uuid` 写在共用头文件的 `static __attribute__((constructor))` 中，链接进同一 `.dylib` 的多个编译单元只保留首个构造函数且使用固定 `logged` 标志，且 `backboardd` 不加载 `libannibale.dylib`，只按需加载 `annibalemetal.bundle`。
  2. 改为在每个独立产物入口（`annibalemetal.m`、`inject.c`、`eagl.c`、`compiler.c`、`air_shim.c`、`audio_plugin.c`、`camera_plugin.c`、`cellular.c`）通过 `dladdr` 读取自身 Mach-O 头部的 `LC_UUID` 并拼入进程名与基址输出。
- 真机验证（`out/s1110/verify1..4.log`）：
  - 里程碑读数：`1/3 userspace_init` 在 `3.05 s`，`2/3 springboard_checkin` 在 `11.15 s`，`3/3 first_unlock` 在 `37.45 s`。
  - `backboardd[81]`、`SpringBoard[78]`、`iconservicesagent[112]` 均在内核日志输出各自加载的 `annibalemetal.bundle`、`libannibale.dylib`、`libannibalegles.dylib`、`libannibaleair.dylib` 的完整 `LC_UUID`。

## 3. 相机设备与流属性补齐及 `-12710` 修复（代码已完成）

基于真机相机打开日志与[方案架构审查](../analysis/2026-11-08-architecture-review.md) §10.3 分析，定位到三处缺失并完成代码修改：

- 设备级属性缺口（`hackios-xnu-userland/userland/src/services/camera_device.c`）：
  - `CameraUI` 启动预览时查询 `ZoomFactor`、`VideoZoomFactor`、`TorchLevel`、`FlashMode`、`HDRMode`、`HighDynamicRangeMode`、`SensorOrientation`、`CameraOrientation`、`ModuleInfo`，原先返回 `-12784`（属性不支持）。
  - 在 `device_get_property` 中补齐上述 9 个属性的默认值返回（缩放因子 `1.0`、方向 `90`、闪光灯与 HDR 关闭、模块信息字典）。
- 流级属性缺口（`hackios-xnu-userland/userland/src/services/camera_device_stream.inc`）：
  - `avconferenced`／`cameracaptured` 会话配置阶段读写流的 `FormatIndex`、`ActiveFormatIndex`、`FrameDuration`、`MinFrameDuration`、`MaxFrameDuration`、`VideoZoomFactor`、`StillImageCaptureEnabled`。
  - 在 `stream_get_property` 与 `stream_set_property` 中补齐对应 `CFNumber`、`CFBoolean` 与 30 fps `CMTime`（`1/30 s`）字典返回。
- 跨进程 `IOSurface` 样本缓冲区格式描述 `-12710`（`hackios-xnu-userland/userland/src/inject/inject_media.c`）：
  - `CMVideoFormatDescriptionCreateForImageBuffer` 在 `IOSurface` 经 Mach 端口跨进程传递后若读取不到平面宽高定义会返回 `-12710`（`kFigFormatDescriptionError_InvalidParameter`），阻断预览帧入队。
  - 在 `fig_format_desc_hook` 中当原函数返回非零且输入为非空 `IOSurface`／`CVPixelBuffer` 时，提取宽高（缺失时回退为 `1080×1920`、`kCVPixelFormatType_32BGRA`）调用 `CMVideoFormatDescriptionCreate` 合成有效格式描述。

## 4. 屏幕高亮度与控制中心滑块低位不同步的根因与修复方案

### 4.1 现象与复现链路

用户反馈早上 8 点多的无人值守跑轮后，屏幕实际处于高亮度，但下拉控制中心看到亮度滑块位于很低的位置，手指稍微调整滑块屏幕就立即变暗。结合真机日志（`out/diag-2039/boot-opt1/boot2.log`、`out/s1110/verify1.log`）与 `backboardd`、`BackBoardServices`、`CoreBrightness` 反汇编，完整还原出调用链与脱节原因：

1. `input26_service.c` 注册虚拟 ALS 并写入错误的 16.16 定点照度，触发 `CoreBrightness` 自动将滑块拉低到 15.07%（`32.477 nits`）：
   - 在 SM8750 上，前置环境光传感器 `gls6151` 所在的 QUPv3 SE12 时钟默认关闭（`out/s1110/verify1.log` 第 247 行：`gls6151 (0x31, SE12 clk=0) ... lux=150`），`annibale_sensors.c` 仅返回静态占位的 `als_lux = 150`（`source_flags = ANNIBALE_SENSOR_SRC_DEFAULT`）。
   - `input26_service.c`（第 623 行）无条件向 `IOHIDEventSystem` 注册了 `"Annibale ambient light sensor"`（`HID_USAGE_APPLE_ALS`），使 `CoreBrightness` 的 `-[BrightnessSystemInternal isAlsSupported]`（`0x1e26ab14c`，读取 `"BLControlAlsSupported"`）判定设备具备环境光传感器。
   - 同时，`input26_service.c` 的 `create_als_event()`（第 178 行）调用 `IOHIDEventSetIntegerValue(event, FIELD_ALS_ILLUMINANCE, (CFIndex)lux)` 写入 `0xc000a` 字段；而 `IOKit` 中 `kIOHIDEventFieldAmbientLightSensorIlluminance` 是 16.16 定点数，直接写入整数 `150` 被 `CoreBrightness` 解析为 `150 / 65536.0 = 0.0022888 lux`（接近全黑）。
   - 开机解锁亮屏时，`SpringBoard` 调用 `BKAmbientLightSensorEnableAutoBrightness`（`verify1.log` 第 6540 行：`DisplayAutoBrightnessActive = 1`），`CoreBrightness` 立即根据虚拟 ALS 的低照度在后台把内部亮度（即控制中心滑块位置 `[CBDisplayModuleiOS + 0x150]`）自动渐变到 `0.150717`（15.07%，对应 `32.477 nits`、`panel_v = 474`，见 `verify1.log` 第 8088～8232 行 `brightness change:0.0695523 .. 0.150717 reason:BrightnessSystemDidChange`），并通过 `backboardd`（`0x100088af0`）与 `BackBoardServices`（`BKSSpringBoardDefaults` `0x1869aa5a8`）写入 `com.apple.springboard` 的 `SBBacklightLevel2` 偏好。
2. 内核滑块窗口过滤单向丢弃 `CoreBrightness` 渐变，造成物理面板与控制中心滑块脱节：
   - 提交 `0e0f19bb` 在 `MiniAppleARMBacklight.cpp` 中加入了 `if (value_key == NULL && (bl.user_until == 0 || now > bl.user_until)) return;` 过滤，在非触摸滑块窗口期直接丢弃了 `IOMFBBrightnessLevel` 更新（`out/diag-2039/boot-opt1/boot2.log` 与 `verify1.log` 持续打印 `framebuffer update outside slider window ignored`）。
   - 结果 DSI 物理面板停留在 `400 nits`（100%），而 `CoreBrightness` 与控制中心滑块已被虚拟 ALS 自动拉低到 `14%～15%`（`29.155～32.477 nits`）。
   - 当用户下拉控制中心并微调滑块时，触摸事件打开了 400 ms 窗口，内核突然接受 `CoreBrightness` 从 15% 邻近位置发来的 `32.477 nits`（`panel_v = 474`）请求，屏幕亮度瞬间从 `400 nits` 跳降到 `32.477 nits`，并将 `474` 写入 `ANNFS001` 持久化槽位（导致 `verify1.log` 第 1338 行开机即从 `start 474 (32.477 nits)` 起步）。
3. `DisplayBrightness` 嵌套字典结构解析缺口：
   - 反汇编 `CoreBrightness`（`0x1e262c834..0x1e262d700`）确认其向 `AppleARMBacklight` 下发的 `"DisplayBrightness"` 是嵌套 `OSDictionary`（含 `"Brightness"`、`"Nits"`、`"NitsPhysical"`、`"DisplayBrightnessSliderPosition"`）。
   - `MiniAppleARMBacklight.cpp` 原先只在顶层字典查找 `"DisplayBrightnessSliderPosition"` 并把 `"DisplayBrightness"` 当作 `OSNumber` 读取，导致 `DisplayBrightness` 属性更新一直打印 `DisplayBrightness=?; nothing taken`。

### 4.2 修复方案

1. 移除无硬件支撑的虚拟 ALS 自动降光触发源（`input26_service.c`）：
   - 仅当 `/dev/annibale-sensors` 具有真实硬件 I2C 采样或显式注入标记（`ANNIBALE_SENSOR_SRC_HW_I2C | ANNIBALE_SENSOR_SRC_INJECTED`）时才注册 `"Annibale ambient light sensor"`（`HID_USAGE_APPLE_ALS`）；默认无硬件 ALS 时不注册该虚拟 HID 服务，使 `CoreBrightness` 原生识别无 ALS 硬件而不再后台改写滑块。
   - 修正 `create_als_event()` 中 `FIELD_ALS_ILLUMINANCE` 的 16.16 定点编码（`(CFIndex)lux << 16`）。
2. 移除内核单向丢弃过滤，保持物理面板与控制中心滑块始终 1:1 同步（`MiniAppleARMBacklight.cpp`）：
   - 去掉 `outside slider window ignored` 拦截，任何 `s16 > 0` 的 `IOMFBBrightnessLevel`、`brightness-nits` 或嵌套 `"DisplayBrightness"` 字典更新均立即驱动 DSI 面板并更新 `IODisplayParameters["brightness"]["value"]`。
   - 补齐嵌套 `"DisplayBrightness"` `OSDictionary` 的键值提取与日志打印；仅在 `s16 <= 0`（锁屏熄屏）时关闭面板背光而不覆盖 `bl.last_v`／`bl.last_millinits` 与 `ramfs_backlight_save`。
3. 清理旧脏持久化值并对齐 `SBBacklightLevel2` 与 `ANNFS001`（`ramfs_disk.inc`、`inject.c`）：
   - 将 `ANNFS001` 背光持久化魔数升级为 `ANNFS_BL_MAGIC`（`0x414e4232U`，`'ANB2'`），自动淘汰此前被虚拟 ALS 污染的 `474`（`32.477 nits`）记录，并在 `AppleARMBacklight` 上发布 `"annibale-bl-restored"` 布尔属性。
   - 在 `backboardd` 启动早期（`inject.c`），当 `"annibale-bl-restored"` 为 `false`（尚无用户手动滑块持久化记录）时，将 `com.apple.springboard` 的 `SBBacklightLevel2` 同步初始化为 `1.0`（`400 nits`），确保首次启动及后续跨重启恢复时控制中心滑块位置与物理屏幕亮度严格一致。

## 5. 触觉反馈 `CHHapticEngine` `Code=4099` 根因与修复方案（审查 §10.1、§11.1）

### 5.1 静态反汇编结论

控制中心及系统交互调用 `CHHapticEngine` 时报 `com.apple.CoreHaptics Code=-4898 / NSCocoaErrorDomain Code=4099`，表明 `audiomxd` 未能初始化 `AVHapticServer`。反汇编 `VirtualAudio.plugin` 与 `libMobileGestalt.dylib` 查明完整调用链：

1. `VirtualAudio.plugin` 在 `0x3c0704`（以及 `0x38b448`、`0x3bf79c`、`0x2fc6b0`）创建 `VirtualAudioDevice_Actuator`（`'vzzz'`）前，调用 `MGGetBoolAnswer("cBy4BcYs5YWtFHbBpt4C6A")`；返回 `false` 时直接跳过 `'vzzz'` 设备创建，`AVHapticServer` 因找不到 Haptic Actuator 设备而放弃注册 XPC 服务。
2. `libMobileGestalt.dylib` 中 `"cBy4BcYs5YWtFHbBpt4C6A"` 的处理函数位于 `0x1b22c2984`，内部调用 `0x1b22b214c("IODeviceTree:/product", CFSTR("6S9CvPHPtzHQqKudHSfsag"), 'h')`。
3. `0x1b22b214c` 遍历 `gIODTPlane` 所有节点（`0x1b22b22d4` -> `0x1b22acdbc`），筛选名称首字符为 `'h'` 的节点，计算 `md5("MGCopyAnswer" + 节点名)` 的 Base64 前 22 字符并与 `"6S9CvPHPtzHQqKudHSfsag"` 比对；经校验 `md5("MGCopyAnswerhaptics")` 的 Base64 前 22 字符正为 `"6S9CvPHPtzHQqKudHSfsag"`。
4. 此外，`VirtualAudio.plugin` 的 `ActuatorSettingsFactory_Aspen`（`0x36d648`）在 `AID8023`（`iPhone18,3`）分支要求 `'pact'`（Actuator 硬件端口）提供 2 个输出通道（通道映射 `[0, 1]`），而 `audio_plugin.c` 中 `OBJECT_ACTUATOR`（ID 6）当前仅声明了 `output_channels = 1`。

### 5.2 修复方案

1. 在内核 `GenericARMPE.cpp` 的 `GenericARMPE::populateDeviceTree()` 中向 `/product`（`gIODTPlane`）挂载名称为 `"haptics"` 的 `IOService` 节点，使 `MGGetBoolAnswer("cBy4BcYs5YWtFHbBpt4C6A")` 原生返回 `true`。
2. 将 `hackios-xnu-userland/userland/src/services/audio_plugin.c` 中 `OBJECT_ACTUATOR` 的 `output_channels` 调整为 `2`，满足 `ActuatorSettingsFactory_Aspen` 对 `AID8023` 的双通道映射要求。

## 6. 状态栏右上角 Wi-Fi 图标灰色问题定位（`STUIStatusBarWifiSignalView` `a=0.20`）

### 6.1 渲染与数据流反汇编（`SystemStatusUI.framework` 与 `SpringBoard.framework`）

真机桌面图层树（`verify1.log`）显示右上角 `STUIStatusBarWifiSignalView` 自身 `a=1.00`（坐标 `322,32 19x13`），但其下 3 个信号扇形 `CALayer` 子图层全部处于 `a=0.20`，呈现灰色无信号状态。反汇编 `SystemStatusUI.framework` 与 `SpringBoard.framework` 查明完整契约：

1. `-[STUIStatusBarWifiSignalView _updateActiveBars]`（`0x277a6047c`）遍历 `numberOfBars`（3 格）子图层：仅在 `[self signalMode] == 2` 且 `i < [self numberOfActiveBars]` 时取 `[self activeColor]`（`alpha = 1.0`），其余条件一律取 `[self inactiveColor]`（由 `_backgroundColorForUpdate:entry:` 在 `0x277a603b8` 调用 `colorWithAlphaComponent:0.2` 生成，故子图层 `opacity = 0.20`）。
2. `-[STUIStatusBarWifiItem applyUpdate:toDisplayItem:]`（`0x277a5c608`）根据 `STUIStatusBarDataWifiEntry` 的 `status` 字段设置 `signalView`：
   - `status == 2`（搜索中）：`signalMode = 0`，不更新 `numberOfActiveBars`，3 格全为 `a=0.20`。
   - `status == 3`（非活跃 / 非主接口）：`signalMode = 1`，不更新 `numberOfActiveBars`，3 格全为 `a=0.20`。
   - `status == 5`（活跃连接）：`signalMode = 2`，将 `numberOfActiveBars` 设为 `[entry displayValue]`（即 `signalStrengthBars`，范围 `0..3`）；若 `displayValue == 0`，3 格同样全为 `a=0.20`。
3. `_STUILegacyDataFromData`（`0x277ab8310`）与 `STUIStatusBarDataConverter`（`0x2809b5d38`）从 `SBWiFiManager` 生成 `STUIStatusBarDataWifiEntry`：当 `SBWiFiManager` 判定当前 Wi-Fi 非主接口（`isPrimaryInterface == NO`）时生成 `status = 3`（`inactive`）；当判定为主接口但 `signalStrengthBars == 0` 时生成 `status = 5, displayValue = 0`。

### 6.2 `IO80211`、`wifid` 与 `SBWiFiManager` 反编译查明的根因

结合 `IO80211.framework`（`_Apple80211FilterMonitoringEvent` `0x25d4808d8`、`_eventReadCallbackQueue` `0x25d45cf98`）、`wifid`（`WiFiDeviceScheduleWithQueue` `0x100061EF4`、`WiFiDeviceManagerScheduleWithQueue` `0x1000BF6F0`、`sub_10015117C`、`sub_1001513C4`）与 `SpringBoard`（`SBWiFiManager` `0x22452daa8..0x22452f348`）反编译及 `verify1.log` 实测时序，定位到三处根因：

1. **`SIOCSA80211` `cmd=564`（`Apple80211FilterMonitoringEvent`，32 字节）被拒导致 `WiFiDeviceScheduleWithQueue` 中途退出**：
   - `wifid` 在 `WiFiDeviceScheduleWithQueue`（`0x100061EF4`）中调用 `Apple80211EventMonitoringInit2`（`0x100062228`）并开启 70 个事件位（`0x10006224c..0x1000626b4`）后，在 `0x1000626d0` 调用 `Apple80211FilterMonitoringEvent(*(a1 + 16))`。
   - `Apple80211FilterMonitoringEvent`（`0x25d4808d8`）向内核发送 `SIOCSA80211`（`req_type = 564`、`req_val = 0`、`req_len = 32`，携带 `[ref + 0x14]` 处的 32 字节事件过滤位图）。
   - `annibale_apple80211.c` 的 `set()` 未实现 `case 564:`，在 `verify1.log`（第 10613 行）打印 `apple80211: wifid sets 564 (?), value 0, 32 bytes: REFUSED` 并返回 `EOPNOTSUPP`（`IO80211` 转为 `-3900`）。
   - `WiFiDeviceScheduleWithQueue` 在 `0x1000626d0` 收到非零返回值后直接跳转至错误分支 `0x100062d98`（`"%s: Error: monitoring Apple80211FilterMonitoringEvent failed"`）并提前返回，导致 `0x1000626d8..0x100062aa8` 的全部初始化被跳过：
     - `*(SCDynamicStoreRef *)(device + 152)`（`0x100062734`，`SCDynamicStoreCreate(kCFAllocatorDefault, "WiFiDevice", sub_100033C14, context)`）从未创建，保持 `NULL`；
     - `sub_100150E94(a1)`（`0x100062760`，订阅 `State:/Network/Global/IPv4` 与 `IPv6`）从未执行；
     - `sub_10015117C(a1)`（`0x100062810`，通过 `*(device + 152)` 向 `SCDynamicStore` 写入 `State:/Network/Interface/en0/AirPort`）在调度阶段被跳过，后续调用也因 `*(device + 152) == NULL` 而失败；
     - `sub_1001513C4(a1)`（`0x1000629e0`，`__copyAirPortService` 注册 `State:/Network/Interface/en0/IPv4` 监听）从未执行；
     - `*(_BYTE *)(device + 5312) = 1`（`0x1000629ec`，设备已调度标志）从未置位。
2. **`wifid` 挂载已关联的 `en0` 时缺少初始 `EVENT_LINK_CHANGED(4)` 与非零 RSSI 回退**：
   - 内核 `ath12k` 在 `11:46:42` 已完成 Wi-Fi 关联，而 `wifid` 在 `11:48:13` 才完成 `WiFiManagerCreate` 并调用 `WiFiDeviceScheduleWithQueue` 挂载 `en0`。
   - `WiFiDeviceManagerScheduleWithQueue`（`0x1000BF6F0`）检测到 `en0` 已关联时仅查询 `CURRENT_NETWORK(103)`（`0x1000bfae8`），不会自行合成 `EVENT_LINK_CHANGED(4)`。
   - `annibale_apple80211.c` 的 `give_network`（`cmd=103 CURRENT_NETWORK`）直接赋 `result->rssi = bss->rssi`（当 `state->bss.rssi == 0` 时未回退为 `-55` dBm），`ANNIBALE_STA_LINK` 中 `link.rssi` 与 `lqm.rssi` 在 `state->bss.rssi == 0` 时同样为 `0`。
3. **`NWSystemPathMonitor` 早于 `wifid` 触发 `wifiPrimary=YES` 时的 `SBWiFiManager` 状态同步**：
   - `11:46:44` `configd` 完成 `en0` DHCP 时，`NWSystemPathMonitor` 触发 `-[SBWiFiManager _primaryInterfaceChanged:YES]`（`0x22452f348`）；若此时 `SBWiFiManager->_device`（`+0x20`）或 `_currentNetwork`（`+0x30`）尚未由 `wifid` 填充，命中 `0x22452f3d8` 分支将 `_primaryInterface`（`+0x70`）清零。

### 6.3 修复方案

1. 在 `hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_apple80211.c` 中：
   - `set()` 处理 `case 564:`（`Apple80211FilterMonitoringEvent`）返回 `0`；当此时 `en0` 已处于 `ANNIBALE_STA_JOINED` 状态时，立即向 `PF_SYSTEM` 补发 `EVENT_BSSID_CHANGED(3)`、`EVENT_LINK_CHANGED(4)`（`down = 0`、`rssi = state->bss.rssi ? state->bss.rssi : -55`、`snr = 35`、`noise = -95`）与 `EVENT_LQM_CHANGED(39)`（`rssi_known = 1`、`rssi = link.rssi`），使刚完成事件监听注册的 `wifid` 立即走通 `sub_10006B9EC`（Link Up）与 `sub_1000123E0`（LQM RSSI 更新）。
   - `set()` 兼容 iOS 26 `wifid`/`configd` 下发的其余配置项（`25`、`383`、`471`、`473`、`481`、`483`、`485`、`512`、`539`、`542`、`543`、`544`、`545`、`547`、`548`、`572`、`582`）并返回 `0`。
   - `give_network()` 与 `ANNIBALE_STA_LINK` 在 `bss->rssi == 0` 时统一回退为 `-55` dBm，`noise` 回退为 `-95` dBm，`snr` 设为 `40`。
2. 在 `hackios-xnu-userland/userland/src/inject/inject_sb26.c` 的周期刷新步进（`sb26_stepped_refresh_step`，`+3s..+110s`）中检查 `SBWiFiManager.sharedInstance`：当 `isAssociated` 为真且 `isPrimaryInterface` 为假时，调用 `[wifiMgr _primaryInterfaceChanged:YES]` 触发主接口重评估，并记录 `isPowered`、`isAssociated`、`isPrimaryInterface`、`signalStrengthBars`、`signalStrengthRSSI` 读数。
3. 产物与提交：内核提交 `8c62d586`（登记为 `12377-s1110-v6`，SHA-256 `610b90a7676ef54e3a150223946cc535eb207a17a244b9f0b26e90087bbf00aa`），用户态提交 `bad0a1a`（`root_sha256` `e073fb446dc1b73c37ee245a4234f8aaca2f4ce8579facb350fff0fc27809cd5`），单测 `tools/tests/test-annibale-apple80211-events.py` 通过；当前真机停留在上一轮 iOS 桌面，待设备切回 `xnuloader` 后执行合并轮真机复核。
