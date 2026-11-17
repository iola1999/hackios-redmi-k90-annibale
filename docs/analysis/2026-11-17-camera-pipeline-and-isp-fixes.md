# 相机预览、前摄连续流与拍照处理链修复（2026-11-17）

本文记录 2026-11-17 第四阶段（内核 `12377-stage4-k5`～`12377-stage4-k7`、真机轮次 `stage4-v5`～`stage4-v7`）针对 `CAM-1`～`CAM-6` 的静态反汇编定位、内核与用户态实现、宿主单测及真机实测结果。相关待办见 [v0.2.0 后续执行批次](../plan/2026-11-16-followup.md#2-相机排查与成像修复)与[多媒体待办](../backlog/multimedia.md)。

## 1. 范围与验证基线

本阶段在可写 APFS 数据卷与 `12377` 内核基线上，完成了前摄 `OV20B40` 供电与连续流采集、前摄关闭后立即复位、后摄 `OV50E40` `2560×1920` 曝光对齐、闪光灯预闪与主闪抓拍联动、`AppleM2ScalerCSCDriver` 内核服务、`IOSurface` 共享事件围栏，以及 `NRFV4.bundle`／`STF.bundle` 拍照处理链 Metal 着色器全量编译。

- 真机环境：REDMI K90（`annibale`），iOS 26.6.2（`23G90`，`iPhone18,3` V57 相机配置），启动参数开启 `torch=3 cam_hw=1 usertrap=1`。
- 实测轮次：`stage4-v5`、`stage4-v6` 与 `stage4-v7`，收尾后设备停留在已解锁 iOS 桌面，电池温度 `36.55 °C`。

## 2. 前摄供电、连续流与停流复位修复

前摄 `OV20B40`（`2592×1458` RAW10，MIPI D-PHY 4-lane，SE9 I2C）此前存在取帧超时（错误码 `60`）以及退出相机后驱动停在 `HELD`、再次打开返回 `EBUSY` 两项问题，定位与修复如下。

1. **RPMh LDO 供电与 SE9 硬件 I2C 回读（`CAM-4`）**：在 [annibale_rpmh.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_rpmh.c) 与 [annibale_camera_hw.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_camera_hw.inc) 通过 RPMh TCS 投票开启 `PM8010M L3M`（VANA `2800 mV`）与相关传感器供电轨，补齐 SE9 GENI 硬件 I2C 与 `OV20B40` `lines << 4` 曝光寄存器格式，并移除 [inject_media.c](../../hackios-xnu-userland/userland/src/inject/inject_media.c) 中旧版 iOS 16.5 偏移写逻辑。
2. **D-PHY 跨帧保持与 CSID RX 锁定（`CAM-4`）**：旧采集路径每帧末尾写入 `off_count` 停止传感器并关闭 `CAM980_RX_CFG0/1`，下一帧重新触发 D-PHY LP→HS 握手时易错过帧起始（SOF）导致 500 ms 超时。[annibale_camera_native.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_camera_native.inc) 新增 `cam_keep_stream`（默认 `1`），在连续取帧正常完成期间保持传感器流与 CSID RX 使能，仅每帧复位 RDI0 路径并更新曝光寄存器。`stage4-v6` 真机实测前摄连续采集 `1,404` 帧、交付 `1,404` 张预览画面，零超时。
3. **停流后 `SW_IMMEDIATE` 复位消除 `HELD`／`EBUSY`（`CAM-5`）**：开启跨帧保持后，`cam_native_release()` 先发 `off_count` 停止传感器 MIPI 时钟并等待 40 ms，再调用 `cam_native_reset(false)`（`RESET_CONFIG = 1`，帧边界复位）。
   - 锁入根因：传感器已停流且 `CAM980_PATH_CFG0` 为 `0`，硬件永远等不到帧结束信号，100 ms 轮询超时后锁入 `ANNIBALE_CAM_CAPTURE_HELD`。
   - 修复：`cam_native_release()` 改为调用 `cam_native_reset(true)`（清零 `RX_CFG0/1` 并执行 `RESET_CONFIG = 0x11`、`RESET_COMMAND = 2` 软件立即复位），同时在 [camera_device_native.inc](../../hackios-xnu-userland/userland/src/services/camera_device_native.inc) 对瞬态 `EBUSY` 增加最多 20 次短重试。
   - 真机验收：`stage4-v7` 连续执行切换前摄、上滑退回桌面、重开相机与再次退回桌面，全程 `3,218` 帧正常停止，零 `HELD`、零 `EBUSY`。

## 3. 后摄预览、曝光对齐与闪光灯抓拍联动

后摄 `OV50E40`（原生 profile 模式 24，`2560×1920` 四合一输出）在曝光、帧率与闪光抓拍上的实测进展如下。

1. **`camnoc_rt_axi` 300 MHz 对照与 `CAM-1` 边界**：在 [annibale_camera_clock.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_camera_clock.inc) 增加 `cam_rt_mhz` 参数并将 `camnoc_rt_axi` 提至 `300 MHz` 对照测试，后摄实时取景与连续流稳定运行（`stage4-v7` 单次会话连续 `3,218` 帧无丢帧挂死），但仅开 `IFE_LITE` 直写路径下的 256B 半块译码限制仍与原厂 `TFE2` 完整 ISP 拓扑相关，保留为后续硬件路径项。
2. **`2560×1920` 曝光对齐与连续流提速（`CAM-2`）**：[annibale_camera_exposure.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_camera_exposure.inc) 对齐模式 24 的行周期（`5,333 ns`）、帧长（`6,250` 行）与黑电平（`64 DN`），配合跨帧保持 MIPI C-PHY 连续流，后摄 `1608×1206` `420f` 预览帧率由 `8.7 fps` 提升至传感器满速约 `30 fps`。
3. **闪光灯状态回报与双帧预闪抓拍（`CAM-6`）**：反汇编 23G90 `CMCapture` 的 `-[BWStillImageCaptureStreamSettings expectedFrameCaptureCount]`（`0x1aeac21c4`）与 `-[BWFigVideoCaptureStream _handleStillImageSampleBuffer:withError:fromTimeMachine:]`（`0x1aed83a9c`）确认以下契约。
   - 协议：闪光抓拍（`captureType = 2`）下发的 `StillImageCaptureNow` 携带 `GenerateRedEyeAuxiliaryImage = 1` 时，管线强制等待 2 帧静态图像（首帧需带 `RedEyeAuxiliaryImage = true` 环境光帧，次帧为主闪帧）。
   - 实现：[camera_device.c](../../hackios-xnu-userland/userland/src/services/camera_device.c) 与 [camera_device_stream.inc](../../hackios-xnu-userland/userland/src/services/camera_device_stream.inc) 完整保存并回报 `FlashMode`，在 `GenerateRedEyeAuxiliaryImage = 1` 时先交付未点亮的预闪辅助帧（`{Exif}.Flash = 16`），随后写 `/dev/annibale-torch` 点亮 `125 mA` 闪光灯（`1000/1000`）预热 2 帧、交付主闪帧（`{Exif}.Flash = 1`）并在抓拍完成后自动熄灭（`0/1000`）。
   - 真机验收：`stage4-v7` 抓拍实测两帧 `2352×1764` `xf20` 依次交付且闪光脉冲按序点亮与熄灭。

## 4. AppleM2ScalerCSCDriver、共享事件与拍照管线编译

iOS 26 `cameracaptured` 在预览缩放与静态图像 PhotonicEngine 处理中依赖多项底层内核与 Metal 编译器契约，逐项定位与实现如下。

1. **`AppleM2ScalerCSCDriver` 内核服务**：反汇编 `CMCapture`（`0x1aea8ea80`、`0x1aeefb37c`）查明 `cameracaptured` 匹配 `AppleM2ScalerCSCDriver` 服务并读取 `IOSurfaceAcceleratorCapabilitiesDict` 下 40 个 `OSNumber` 能力键（之前返回布尔值导致 `OSNumber::unsigned32BitValue` 虚表调用崩溃），且通过外部方法 selector `1` 执行缩放转换、selector `7` 读取 96 字节直方图。新增 [MiniM2Scaler.cpp](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniM2Scaler.cpp)（885 行）实现上述能力字典、NV12／P010／`xf20`／BGRA CPU 缩放转换与直方图输出，`stage4-v6` 与 `stage4-v7` 预览及抓拍期间零 `M2Scaler` 崩溃。
2. **`IOSurface` 与 `MTLSharedEvent` 跨组件围栏**：新增 [MiniIOSurfaceSharedEvent.inc](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniIOSurfaceSharedEvent.inc) 实现 `IOSurfaceRootUserClient` 的 `signal_event`／`wait_event` 方法，并与 [annibalemetal_commandbuffer.inc](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_commandbuffer.inc) 的命令缓冲提交／完成围栏打通；同时在 [annibaledrawable.m](../../hackios-xnu-kernel/tools/userland-driver/annibaledrawable.m) 补齐 `R16Unorm`、`RG16Unorm`、`R8Uint`、`RGBA32Uint` 等计算平面视图格式。
3. **AIR 编译器补齐与 `NRFV4`／`STF` 100% 编译通过**：
   - 稀疏 MRT 空颜色附件、显式与隐式 `imageblock`（[air_imageblock.inc](../../hackios-xnu-userland/tools/mesa/air/air_imageblock.inc)）、SIMD 归约／前缀／shuffle 内建函数（[air_simd.inc](../../hackios-xnu-userland/tools/mesa/air/air_simd.inc)）与指针 `phi`／局部槽位支持合入 Mesa AIR 前端。
   - [air_call.inc](../../hackios-xnu-userland/tools/mesa/air/air_call.inc) 新增 `CALL_PARAM_PTR_SELECT`，支持模块内函数调用传递运行期 `select` 选择的常量缓冲指针，解决 `SoftISP` 的 `H13FastBayerProc::hrdGnuCorrectionQuadra` 编译拒绝。
   - [air_argbuf.inc](../../hackios-xnu-userland/tools/mesa/air/air_argbuf.inc) 与 [air_metal.c](../../hackios-xnu-userland/tools/mesa/air/air_metal.c) 支持参数缓冲嵌套 `air.struct_type_info`（含 LLVM 同构结构体去重回退）、`air.indirect_constant` 行内常量 UBO 读取及 `metal::array` 采样纹理数组成员，解决 `RawDFSyntheticReferenceCRG::kernelRawDFHighlightRecovery`、`kernelRawDFDeepShadowRecovery` 与 `stfGainAdjustedAccumulation` 编译拒绝。
   - 经宿主 `air2nir --report` 实测，`NRFV4.bundle/default.metallib` 全部 `512/512` 个模块与 `STF.bundle/default.metallib` 全部模块均 `translate=ok` 并通过 NIR 校验；`stage4-v7` 真机实测 `BWStillImageProcessingNode` 协调器初始化通过，抓拍时 `cameracaptured` 提交并完成 `12` 个 Metal 命令缓冲且 `errors = 0`。

## 5. 宿主单测与剩余边界

本阶段新增及更新 5 套宿主测试，全部在无设备环境下通过：

- [test-mini-m2scaler.py](../../hackios-xnu-kernel/tools/tests/test-mini-m2scaler.py)：校验 `AppleM2ScalerCSCDriver` 40 项 `OSNumber` 能力键、NV12／BGRA 转换与 selector `7` 直方图边界。
- [test-iosurface-shared-event.py](../../hackios-xnu-kernel/tools/tests/test-iosurface-shared-event.py) 与 [test-metal-shared-event.py](../../hackios-xnu-kernel/tools/tests/test-metal-shared-event.py)：校验 `IOSurface` 共享事件信号唤醒、超时及 `AnnibaleMetal` 命令缓冲同步。
- [test-annibale-camera-native.py](../../hackios-xnu-kernel/tools/tests/test-annibale-camera-native.py)：覆盖连续流保持、关闭重开等 `39` 项 MMIO／DMA 场景与 `9` 项守卫变异（含 `cam_native_release` 退回帧边界复位的负向变异）。
- [test-camera-device-ios26.py](../../hackios-xnu-userland/tools/tests/test-camera-device-ios26.py)：校验 `GenerateRedEyeAuxiliaryImage = 1` 双帧预闪／主闪序列、静态帧元数据及 `EBUSY` 打开重试。

留待下一批次继续推进的两项相机尾项：

- **`CAM-3` 图像压缩编码落盘**：`stage4-v7` 中 `StillImage` 双帧交付与 `NRFV4` Metal 计算管线均已零错误跑通，但 `/private/var/mobile/Media/DCIM/100APPLE` 尚未生成 JPEG／HEIC 文件。11-18 的观测与下一步见[相机观测与闪烁](../progress/2026-11-18-camera-trace-and-perm-flicker.md)；快速重开切后台时 `BWPreviewStitcherNode`（DSC `0x1aeca34c4`）的停流断言仍待排查。
- **`CAM-1` 原厂 `TFE2` 完整写出路径**：当前 `IFE_LITE` RDI0 路径已可支撑 30 fps 实时预览，消除 256B 半块条纹需对照原厂 `TFE2` 寄存器序列进一步验证；11-18 补读结果见[多专题研究 §7](../analysis/2026-11-16-multi-topic-research.md#7-相机)。
