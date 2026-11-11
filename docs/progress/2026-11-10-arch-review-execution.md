# 架构审查跟进、亮度同步、相机与触觉反馈推进记录（2026-11-10）

本文记录 2026-11-10 围绕 `v0.1.2` 发布、开机三里程碑时间戳与注入库 `LC_UUID` 自报、亮度滑块与物理面板同步、相机流属性与格式描述补齐、触觉反馈（`AVHapticServer`）及状态栏 Wi-Fi 图标的静态分析、代码实现与真机验证进展。汇总入口见[进度表](../plan/2026-10-23-tracking.md)，审查基准见[方案架构审查](../analysis/2026-11-08-architecture-review.md)。

## 1. 进展汇总

| 序号 | 事项 | 涉及模块 | 当前状态 | 结果与出处 |
|---|---|---|---|---|
| 1 | `v0.1.2` 发布与三仓推送 | `tools/release/`、三仓 `k90-port` | 已完成 | 构建并校验 `hackios-annibale-0.1.2-darwin-arm64.tar.gz`，推送顶层与两个代码子模块，发布 GitHub Release `v0.1.2` |
| 2 | 开机三里程碑时间戳与驱动／注入库 `LC_UUID` 自报（审查 §13、§16） | `rc.launchd`、`inject_sb26.c`、`annibalemetal.m`、`userland/src/inject/` | 已真机验证 | 真机 `out/s1110/verify1..4.log` 输出 `[boot-milestone] 1/3..3/3` 及 `backboardd`、`SpringBoard`、`iconservicesagent` 加载的驱动与注入库 `LC_UUID`（内核 `82028632`、用户态 `0d9ebbc`） |
| 3 | 相机 `BWMultiStreamCameraSourceNode` 四阶段生命周期对齐与格式表补齐（审查 §10.3） | `camera_device.c`、`camera_device_stream.inc`、`inject_media.c` | 代码已完成，单测通过，待上机验证 | 反汇编 `CMCapture` 还原 `configure:`、`allocateOrReuseBufferPoolsFromSourceNode:`、`prepareForCurrentConfigurationToBecomeLive`、`start:` 四阶段完整调用链，补齐 `Depth` 输出槽位、`Metadata` 10 项掩码与缩略图配置、`VideoOutputConfigurations` 合并保留与 `BufferPoolCountForCaptureStream` 默认值、9 种像素格式与 `V57` 格式表，宿主单测 `test-camera-device-ios26.py` 通过 |
| 4 | 屏幕亮度与控制中心滑块脱节修复 | `MiniAppleARMBacklight.cpp`、`input26_service.c`、`inject.c`、`ramfs_disk.inc` | 代码已完成，单测通过，待上机验证 | 查明 `input26_service.c` 在无硬件 ALS（`SE12 clk=0`）时注册虚拟 ALS 并以整数写入 16.16 定点字段 `FIELD_ALS_ILLUMINANCE`（`150 / 65536 = 0.0023 lux`），触发 `CoreBrightness` 自动降光至 `15.07%`（`32.477 nits`），叠加内核滑块窗口过滤丢弃 `IOMFBBrightnessLevel`，导致物理面板 `400 nits` 与控制中心滑块 `15%` 脱节，宿主单测 `test_challenger_m6_backlight.py` 通过 |
| 5 | 触觉反馈 `CHHapticEngine` `Code=4099` 与 `AVHapticServer` 启动（审查 §10.1、§11.1） | `GenericARMPE.cpp`、`audio_plugin.c`、`init26.c` | 代码已完成，单测通过，待上机验证 | 反汇编确认 `VirtualAudio.plugin` 检查 `MGGetBoolAnswer("cBy4BcYs5YWtFHbBpt4C6A")`（`gIODTPlane` 节点 `"haptics"` 对应 MD5 Base64 `"6S9CvPHPtzHQqKudHSfsag"`）及 `AID8023` 2 通道 `'pact'` 端口映射，补齐 `audio_plugin.c` 属性与 `com.apple.audio.AVHapticServer` XPC 注册，宿主单测 `test-audio-plugin.py` 通过 |
| 6 | 右上角状态栏 Wi-Fi 图标灰色问题 | `annibale_apple80211.c`、`inject_sb26.c` | 代码已完成，单测通过 | 补齐 `SIOCSA80211` `cmd=564`（`Apple80211FilterMonitoringEvent`）处理与已关联 `en0` 的初始 `EVENT_LINK_CHANGED(4)`／`EVENT_LQM_CHANGED(39)` 推送及 `SBWiFiManager` 主接口重评估 |
| 7 | `xnuloader` 511 字节 USB Bulk OUT TRB 长度修正（审查 §11.2） | `loader_06_usb_entry.inc` | 已完成 | 将 511 字节控制块接收 TRB 长度对齐为 `max_pkt`（512 字节） |

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

## 3. 相机 `BWMultiStreamCameraSourceNode` 四阶段生命周期反汇编与完整对齐（审查 §10.3）

### 3.1 `verify4.log` 复现现象与 `CMCapture` 四阶段原生调用链

在 `out/s1110/verify4.log` 中启动 `Camera.app` 时，`cameracaptured` 成功创建 `AnnibaleCaptureDevice` 并由 `device_request_streams` 拉起后台 `worker` 线程（`/dev/annibale-camera` 稳定产出 `4096×3072` 原始帧），但 `stream_set_property` 仅收到 `FormatIndex = 3` 与 `VideoOutputHandlers`，随后报 `stream: an output not here: Depth`，从未收到 `VideoOutputConfigurations`、`VideoOutputsEnabled` 与 `stream_start`。使用 `dsc.py` 反汇编 iOS 26（`23G90__iPhone18,3`）`CMCapture` 中 `BWMultiStreamCameraSourceNode` 的完整生命周期，查明其四阶段原生调用链与全部契约要求：

1. **阶段 1：`-[BWMultiStreamCameraSourceNode configure:]`（`0x1ae99f16c` -> `0x1ae99fb20`）**：
   - `0x1ae9a0bd0` 调用 `-[BWFigCaptureStream setFormatIndex:]`（`0x1ae9a0cd8`），向流写入 `kFigCaptureStreamProperty_FormatIndex`（`0x1e6e5e1b8`）。
   - `0x1ae9c74bc` 选择首选输出端口：`_preferredPreviewOutput`（`+0x9a8`）设为 `"PrimaryScaler"`（`0x1e6e5edc8`），`_preferredVideoOutput`（`+0x9b0`）设为 `"SecondaryScaler"`（`0x1e6e5ede0`），`_stillImageOutput`（`+0x988`）设为 `"StillImage"`（`0x1e6e5ede8`）。
   - `0x1ae9c79f4` 构建 `VideoOutputHandlers` 字典：在 `0x1ae9c7b08..0x1ae9c7b38` 检查 `(1 << _deviceType) & 0x1e7ffc`（广角相机 `_deviceType == 2` 恒命中），**无条件向 `VideoOutputHandlers` 字典加入 `"Depth"`（`0x1e6e5eda8`）的 `PixelBufferHandler`**，再调用 `setProperty:kFigCaptureStreamProperty_VideoOutputHandlers`。若驱动不接受 `"Depth"` 或缺少后续阶段所需的属性配置，`configure:` 无法进入缓冲池分配阶段。
   - `0x1ae9ac204` 在 `0x1ae9ac284` 调用 `copyProperty:kFigCaptureStreamProperty_VideoOutputConfigurations`，遍历 `0..21` 输出槽位读取各输出字典的 `BufferPoolBytesPerRowAlignmentRequirement`（`0x1e6e5ecf0`，存入 `slot + 0x6c`）与 `BufferPoolPlaneAlignmentRequirement`（`0x1e6e5ed00`，存入 `slot + 0x70`），同时读取 `SupportedOutputs` 中各输出的 `SupportedPixelFormats`、`SashimiRawPixelFormat`（`0x1e6e5ea38`）、`SushiRawPixelFormat`（`0x1e6e5ea40`）。
   - `0x1ae99fccc..0x1ae9a0b20` 按需调用 `0x1aee31d04`（`PreLTMThumbnailConfiguration`）、`0x1aee31e4c`（`LTMThumbnailConfiguration`）、`0x1aee321d4`（`PostColorProcessingThumbnailConfiguration`）、`0x1aee3231c`（`WeightSegmentMapConfiguration`）、`0x1aee32630`（`LightSourceMaskConfiguration`）、`0x1aee327bc`（`KeypointDescriptorDataConfiguration`）、`0x1aee328dc`（语义掩码 `HumanFullBodiesMaskConfiguration`／`HumanHairMaskConfiguration`／`HumanSkinsMaskConfiguration`／`SkyMaskConfiguration`），从 `VideoOutputConfigurations[@"Metadata"]` 读取上述 10 项子配置字典的 `Width`、`Height`、`PixelFormat`、`DataBufferSize`、`BufferPoolBytesPerRowAlignmentRequirement`、`BufferPoolPlaneAlignmentRequirement`、`BufferPoolCountForCaptureStream` 构建 `BWVideoFormatRequirements`。若缺少任一子字典，对应辅助函数返回 `nil` 并终止节点配置。
2. **阶段 2：`-[BWMultiStreamCameraSourceNode allocateOrReuseBufferPoolsFromSourceNode:]`（`0x1aea19998`）**：
   - `BWGraph` 完成全图格式协商后调用该方法。
   - `0x1aea199d0` 调用 `0x1aea1af70` -> `0x1aee38068` -> `0x1aea1e274` -> `0x1ae9afc70`（及 `0x1ae9d3610`、`0x1ae9c9544`）：根据各 `BWNodeOutput` 协商后的 `resolvedVideoFormat` 构建包含 `"PrimaryScaler"`、`"SecondaryScaler"`、`"StillImage"` 等输出字典（含 `"Width"`、`"Height"`、`"CropRect"`、`"PixelFormat"`、`"MaxOutputFrameRate"`）的字典 `x21`，在 `0x1aea1e574` 首次调用 `[stream setProperty:kFigCaptureStreamProperty_VideoOutputConfigurations value:x21]`。
   - 紧接着在 `0x1aea199f8..0x1aea19a0c` 调用 `[stream copyProperty:kFigCaptureStreamProperty_VideoOutputConfigurations]`，并在 `0x1aea19b80..0x1aea1a630` 遍历已启用输出槽位：从驱动返回的 `VideoOutputConfigurations[outputID]` 中读取 `"BufferPoolCountForCaptureStream"`（`0x1e6e5ecf8`，在 `0x1aea19eec` 读取）与 `BWNodeOutput` 的 `retainedBufferCount` 相加作为容量 `capacity`（`x20`），调用 `-[BWPixelBufferPool initWithVideoFormat:capacity:name:...]`（`0x1af2103c0`）创建 `BWPixelBufferPool`。若驱动未在 `VideoOutputConfigurations[outputID]` 中提供非零 `"BufferPoolCountForCaptureStream"` 且下游 `retainedBufferCount == 0`，池容量为 `0` 会导致 `BWPixelBufferPool` 创建返回 `nil`（`0x1aea1ac38`）并中止。
   - 池创建成功后，在 `0x1aea1a5b4..0x1aea1a628` 生成仅含 `@{ @"BufferPool": cvPixelBufferPool, @"RetainedBufferCount": @(N) }` 的字典并在 `0x1aea1aba0` **第二次调用 `[stream setProperty:kFigCaptureStreamProperty_VideoOutputConfigurations]`**。若驱动的 `setProperty:VideoOutputConfigurations` 直接用新字典覆盖旧字典而非按字段合并，会丢失首次写入的 `"Width"`、`"Height"`、`"PixelFormat"`、`"CropRect"`，导致后续缩放或重配置读取失败。
3. **阶段 3：`-[BWMultiStreamCameraSourceNode prepareForCurrentConfigurationToBecomeLive]`（`0x1aea24618`）**：
   - 调用父类准备方法并初始化内部同步状态。
4. **阶段 4：`-[BWMultiStreamCameraSourceNode start:]`（`0x1aea24bcc`）**：
   - `0x1aea24e74` 调用 `0x1aea58340(self, 1, 1, 0)`：若启用了 `"Metadata"` 子输出，在 `0x1aea58878` 调用 `setProperty:VideoOutputConfigurations` 写入 `@{ @"Metadata": ... }`；随后在 `0x1aea588f8..0x1aea58910` 调用 `[stream setProperty:kFigCaptureStreamProperty_VideoOutputsEnabled value:enabledDict]` 开启 `"PrimaryScaler"`、`"SecondaryScaler"`、`"StillImage"` 等输出。
   - `0x1aea24e9c` 调用 `[self->_captureStream start]`（`0x1af238f60`），进入 `camera_device_stream.inc` 的 `stream_start()` 将流状态置为 `CAM_STREAM_ACTIVE`，开始通过 `PixelBufferHandler` 向预览与拍照管线投递图像帧。

### 3.2 修复实现（`camera_device.c`、`camera_device_stream.inc`、`inject_media.c`）

1. **输出槽位与像素格式补齐**：
   - `OUTPUTS` 扩充为 6 项（`"PrimaryScaler"`、`"SecondaryScaler"`、`"StillImage"`、`"StillImageQuadra"`、`"StillImageRaw"`、`"Depth"`），`worker()` 帧投递循环跳过 `"Depth"` 槽位，使阶段 1 无条件注册 `"Depth"` handler 时正常接纳。
   - `output_info()` 支持 9 种像素格式（`PF_420F`、`PF_420V`、`PF_X420`、`PF_XF20`、`PF_P422`、`PF_PF22`、`PF_X422`、`PF_XF22`、`PF_BGRA`）及 `SashimiRawPixelFormat`、`SushiRawPixelFormat`、`FocusPixelDataSupported`；`deliver()` 支持 10-bit Bi-Planar（`x420`／`xf20`）平面左移 8 位写入。
   - 前后置相机格式表补齐 `V57/AVCaptureSession.plist`（`iPhone18,3`）要求的 30 fps／60 fps、`FESCompanion`、`DepthCompanion`、`ActionCameraCompanion` 与 `FrontVirtual` 全部条目。
2. **`VideoOutputConfigurations` 读写契约完整对齐**：
   - `stream_copy_property("VideoOutputConfigurations")` 对全部 6 个输出槽位始终返回包含默认 `"BufferPoolBytesPerRowAlignmentRequirement": 64`、`"BufferPoolPlaneAlignmentRequirement": 64`、`"BufferPoolCountForCaptureStream": 6` 的字典（合并已设置的 `"Width"`、`"Height"`、`"PixelFormat"`、`"BufferPool"` 等键值），满足阶段 1（`0x1ae9ac204`）与阶段 2（`0x1aea19998`）的对齐及池容量计算。
   - `stream_copy_property("VideoOutputConfigurations")` 在 `"Metadata"` 下完整返回全部 10 项子配置（含新增的 `"PreLTMThumbnailConfiguration"`、`"LTMThumbnailConfiguration"`、`"PostColorProcessingThumbnailConfiguration"`），并合并 `stream_set_property` 写入的 `"Metadata"` 覆盖项。
   - `stream_set_property("VideoOutputConfigurations")` 对每个输出槽位采用字典键值合并（`CFDictionaryCreateMutableCopy` + 逐键更新），确保阶段 2 第二次写入 `BufferPool` 时保留阶段 2 首次写入的 `Width`、`Height`、`PixelFormat`、`CropRect`。
3. **四阶段生命周期日志观测与宿主单测**：
   - 在 `inject_media.c` 中为 `BWMultiStreamCameraSourceNode` 的 `configure:`、`allocateOrReuseBufferPoolsFromSourceNode:`、`prepareForCurrentConfigurationToBecomeLive`、`start:` 挂载轻量日志包装，上机即可直接核验四阶段返回值。
   - 新增宿主单测 `hackios-xnu-userland/tools/tests/test-camera-device-ios26.py`，模拟 `BWMultiStreamCameraSourceNode` 四阶段完整属性读写与两阶段 `VideoOutputConfigurations` 合并保留契约，编译与运行验证通过。

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

1. 仅在真实硬件传感器就绪时注册 ALS（`input26_service.c`）：
   - 仅当 `/dev/annibale-sensors` 具有真实硬件 I2C 采样或显式注入标记（`ANNIBALE_SENSOR_SRC_HW_I2C | ANNIBALE_SENSOR_SRC_INJECTED`）时才注册 `"Annibale ambient light sensor"`（`HID_USAGE_APPLE_ALS`）；默认无硬件 ALS 时仅注册加速度与陀螺仪 HID 服务，使 `CoreBrightness` 原生识别无 ALS 硬件。
   - 修正 `create_als_event()` 中 `FIELD_ALS_ILLUMINANCE` 的 16.16 定点编码（`(CFIndex)lux << 16`）。
2. 保持物理面板与控制中心滑块始终 1:1 同步（`MiniAppleARMBacklight.cpp`）：
   - 任何 `s16 > 0` 的 `IOMFBBrightnessLevel`、`brightness-nits` 或嵌套 `"DisplayBrightness"` 字典更新均立即驱动 DSI 面板并更新 `IODisplayParameters["brightness"]["value"]`。
   - 补齐嵌套 `"DisplayBrightness"` `OSDictionary` 的键值提取与日志打印；仅在 `s16 <= 0`（锁屏熄屏）时关闭面板背光而不覆盖 `bl.last_v`／`bl.last_millinits` 与 `ramfs_backlight_save`。
3. 升级背光持久化魔数并对齐 `SBBacklightLevel2` 与 `ANNFS001`（`ramfs_disk.inc`、`inject.c`）：
   - 将 `ANNFS001` 背光持久化魔数升级为 `ANNFS_BL_MAGIC`（`0x424c5332U`，`'BLS2'`），并在 `AppleARMBacklight` 上发布 `"annibale-bl-restored"` 布尔属性。
   - 在 `backboardd` 启动早期（`inject.c`），当 `"annibale-bl-restored"` 为 `false`（尚无用户手动滑块持久化记录）时，将 `com.apple.springboard` 的 `SBBacklightLevel2` 同步初始化为 `1.0`（`400 nits`），确保首次启动及后续跨重启恢复时控制中心滑块位置与物理屏幕亮度严格一致。
   - 更新宿主单测 `hackios-xnu-kernel/tools/tests/test_challenger_m6_backlight.py`，校验 1:1 滑块／面板同步、嵌套 `"DisplayBrightness"` 字典解析与 `'BLS2'` 持久化契约并通过。

## 5. 触觉反馈 `CHHapticEngine` `Code=4099` 根因与修复方案（审查 §10.1、§11.1）

### 5.1 静态反汇编结论

控制中心及系统交互调用 `CHHapticEngine` 时报 `com.apple.CoreHaptics Code=-4898 / NSCocoaErrorDomain Code=4099`，表明 `audiomxd` 未能初始化 `AVHapticServer`。反汇编 `VirtualAudio.plugin` 与 `libMobileGestalt.dylib` 查明完整调用链：

1. `VirtualAudio.plugin` 在 `0x3c0704`（以及 `0x38b448`、`0x3bf79c`、`0x2fc6b0`）创建 `VirtualAudioDevice_Actuator`（`'vzzz'`）前，调用 `MGGetBoolAnswer("cBy4BcYs5YWtFHbBpt4C6A")`；返回 `false` 时直接跳过 `'vzzz'` 设备创建，`AVHapticServer` 因找不到 Haptic Actuator 设备而放弃注册 XPC 服务。
2. `libMobileGestalt.dylib` 中 `"cBy4BcYs5YWtFHbBpt4C6A"` 的处理函数位于 `0x1b22c2984`，内部调用 `0x1b22b214c("IODeviceTree:/product", CFSTR("6S9CvPHPtzHQqKudHSfsag"), 'h')`。
3. `0x1b22b214c` 遍历 `gIODTPlane` 所有节点（`0x1b22b22d4` -> `0x1b22acdbc`），筛选名称首字符为 `'h'` 的节点，计算 `md5("MGCopyAnswer" + 节点名)` 的 Base64 前 22 字符并与 `"6S9CvPHPtzHQqKudHSfsag"` 比对；经校验 `md5("MGCopyAnswerhaptics")` 的 Base64 前 22 字符正为 `"6S9CvPHPtzHQqKudHSfsag"`。
4. 此外，`VirtualAudio.plugin` 的 `ActuatorSettingsFactory_Aspen`（`0x36d648`）在 `AID8023`（`iPhone18,3`）分支要求 `'pact'`（Actuator 硬件端口）提供 2 个输出通道（通道映射 `[0, 1]`），而 `audio_plugin.c` 中 `OBJECT_ACTUATOR`（ID 6）当前仅声明了 `output_channels = 1`。

### 5.2 修复方案

1. 在内核 `GenericARMPE.cpp` 的 `GenericARMPE::populateDeviceTree()` 中向 `/product`（`gIODTPlane`）挂载名称为 `"haptics"` 的 `IOService` 节点，使 `MGGetBoolAnswer("cBy4BcYs5YWtFHbBpt4C6A")` 原生返回 `true`。
2. 将 `hackios-xnu-userland/userland/src/services/audio_plugin.c` 中 `OBJECT_ACTUATOR` 的 `output_channels` 调整为 `2`，补齐 `'aunt'`、`0x70636d64`、`'bchn'` 与 `mSampleSize=2`，并在 `init26.c` 为 `audiomxd` 登记 `com.apple.audio.AVHapticServer` Mach 服务；宿主单测 `hackios-xnu-userland/tools/tests/test-audio-plugin.py` 验证通过。

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
3. 产物与提交：内核提交 `8c62d586`..`e7d652b4`（登记为 `12377-s1110-v6`，SHA-256 `610b90a7676ef54e3a150223946cc535eb207a17a244b9f0b26e90087bbf00aa`），用户态提交 `bad0a1a`..`32ffefa`（`root_sha256` `e79915ca85dcb9cfffa06e1e64d715efb590757475f366db3ce3ff25a5d1d2c8`），单测 `test-annibale-apple80211-events.py`、`test_challenger_m6_backlight.py`、`test-audio-plugin.py`、`test-camera-device-ios26.py` 全部通过。剩余真机验收见[平台待办](../backlog/platform.md)。
