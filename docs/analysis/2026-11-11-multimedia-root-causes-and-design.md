# 音频播放、相机适配与视频硬解根因定位及架构设计（2026-11-11）

本文汇总 REDMI K90（SM8750，代号 `annibale`）在未修改 iOS 26.6.2（`23G90`）用户态下音频播放、相机适配与视频硬解三条链路的静态反汇编结论、寄存器取证数据与分层修复方案。审查原则与分层边界遵循[方案架构审查](2026-11-08-architecture-review.md) §3 与 [AGENTS.md](../../AGENTS.md) §6，前序进展见[11-10 架构审查跟进记录](../progress/2026-11-10-arch-review-execution.md)。

## 1. 问题现象与跨子系统根因总览

前期真机运行与用户反馈暴露出三组相互交织的多媒体故障。音频侧表现为扬声器无声、Safari 报媒体错误 3、Bilibili 播放崩溃以及冷启动 `AVPlayer` 卡顿约 33.7 秒；相机侧表现为 `Camera.app` 预览黑屏、`cameracaptured` 图提交返回 `-12780`、前后置物理传感器未出流；视频侧表现为 10-bit HDR 与 BT.2020 画面合成异常、`VideoToolbox` 缺少 SM8750 Iris VPU 硬件解码能力。

静态反汇编 `dyld_shared_cache`（`23G90__iPhone18,3`）与原厂 Android `vendor_dlkm`／`vendor_boot` 内核模块后，上述故障归纳为九项底层契约缺口。

| 子系统 | 故障现象 | 根因位置 | 修复层级 |
|---|---|---|---|
| 音频守护进程 | `airplayd` 空指针崩溃，`audiomxd` 等待 XPC 30 秒超时触发 Safari 媒体错误 3 | `init.c` 整目录覆盖挂载 `/System/Library/Audio/Plug-Ins/HAL` 遮蔽原厂 `AirPlayHalogen.driver`；`mkjobs.py` 未求值 `#IfFeatureFlagEnabled` 导致 `MachServices` 冲突 | 用户态 `init.c`、`mkjobs.py`、`package.py` |
| 内核时钟换算 | `gettimeofday`／`clock_gettime` 偶发返回 `tv_usec >= 1,000,000`，破坏音视频时钟同步 | `osfmk/arm/rtclock.c` 在 19.2 MHz QTimer 下将 `rtclock_usec_divisor` 截断为整数 `19` | 内核 `rtclock.c` 补丁 |
| 音频 DSP 传输 | PCM 实际吞吐率仅 42,318 Hz，冷启动与停流切换断续，且存在三重数字衰减（合计 `-84 dB`） | `annibale_audio_reach.c` 单槽同步等待加 `delay_for_interval` 串行化；`annibale_adsp.c` 固定 5 ms 轮询；内核两处重复右移衰减 | 内核 `annibale_audio_reach.c`、`annibale_adsp.c` |
| 智能功放驱动 | 物理扬声器无声，I2C 读写未命中真实寄存器表 | 板上双功放实为 NXP TFA9865／TFA9866（`REG_REV = 0x9866`），缺少 `ldob15` 1.8 V 供电、复位／切换 GPIO、OTP 解锁序列与 `0x51[15:8]` 音量位域 | 内核 `annibale_rpmh.c`、`annibale_audio_amp.c` |
| 系统级 Metal 发现 | `Camera.app`、`cameracaptured` 与 `Photos` 调 `MTLCreateSystemDefaultDevice()` 返回 `nil` | `IOAcceleratorES` 默认未发布 `MetalPluginName`，`AnnibaleMetalDevice` 默认 `featureProfile = 0` 低于 `MPSDevice` 与 `NUPlatform_iOS` 要求的 `MTLGPUFamilyApple3` | 内核 `MiniFramebufferUserClient.inc`、用户态 Metal 驱动与打包 |
| 相机图提交 | `BWMultiStreamCameraSourceNode` 建图返回 `-12780` | `SoftISP = true` 触发缺失的 22 键 Raw 缓冲池校验；流缺少 `ModuleInfo`、`TuningParameters` 与 `FaceDetectionConfiguration` | 用户态 `camera_device.c`、`camera_device_stream.inc` |
| 相机硬件通路 | 前后置物理传感器探测失败，`CAMIOC_G_INFO` 标志位反置 | 缺少 `CAM_CPAS`、`gcc_camera_*` 时钟、7 路 PMIC 电源轨、`apps_smmu` 幂等旁路与前置 QUPv3 SE9 I2C 控制器驱动 | 内核 `annibale_camera.c`、`annibale_camera_hw.inc` |
| 视频 YUV 合成 | 10-bit P010（`x420`／`xf20`）导入失败，BT.2020 矩阵缺失，format `500` 尺寸校验过严 | `annibaledrawable.m` 未映射 `R16Unorm`／`RG16Unorm` 双平面，`annibalemetal_yuv.inc` 拒收 `0x10` 用途标志且缺少 `matrix == 9` | 用户态 Metal 驱动与 `air` 着色器层 |
| 视频硬件解码 | `/dev/annibale-iris` 仅返回不支持，高码率 H.264／HEVC 依赖 CPU 软解 | 缺少 SM8750 Iris v3.5（`vpu35_4v.mbn`，PAS `9`）电源时钟、两条 SMMU SID 路由、HFI Gen2 队列协议及 `videocodecd` 的 arm64e `VideoToolbox` 插件 | 内核 `annibale_iris*.c`、用户态 `videotoolbox_iris.c` |

## 2. 音频播放：HAL 目录遮蔽、FeatureFlags、时钟精度、AudioReach 异步流水线与 TFA9866 功放

### 2.1 `airplayd` 崩溃与 `audiomxd` 30 秒 XPC 超时链路

真机崩溃报告显示 `airplayd` 启动后在 `AirPlaySender.framework` 的 `InitializeEndpointManager`（偏移 `+0x194`）发生 `EXC_BAD_ACCESS`（地址 `0x0`），`audiomxd` 随后阻塞在 `FigEndpointManagerCopyAirPlaySingleton` 并在 30 秒后因 CoreMedia XPC 超时退出。反汇编 `AirPlaySender` 与 `AudioServer` 查明了完整调用链。

1. `audiomxd` 初始化音频路由时向 `airplayd` 发起 XPC 请求创建全局 `FigEndpointManager`。
2. `airplayd` 加载 `/System/Library/Audio/Plug-Ins/HAL/AirPlayHalogen.driver` 获取 AirPlay 虚拟音频端点工厂指针，未做非空判空即在 `InitializeEndpointManager + 0x194` 解引用。
3. `hackios-xnu-userland/userland/src/boot/init.c` 的 `mounts[]` 表将单插件目录 `/hal` 整目录绑定挂载到 `/flash/System/Library/Audio/Plug-Ins/HAL`，遮蔽了原厂系统卷下包括 `AirPlayHalogen.driver` 在内的全部 10 个 Apple 原生 HAL 插件。
4. `hackios-xnu-userland/userland/mkjobs.py` 解析 `System/Library/LaunchDaemons/*.plist` 时直接剥离 `#` 条件键而未对照 `System/Library/FeatureFlags/Domain/*.plist` 求值，导致 `com.apple.airplayd.plist` 与 `com.apple.audiomxd.plist` 中互斥的 `#IfFeatureFlagEnabled`／`#IfFeatureFlagDisabled` 分支同时生效并产生 `MachServices` 注册冲突。

针对上述两处缺口，用户态挂载与守护进程缓存生成同步调整。

- 在 `init.c` 中移除 `/hal` 对 `/flash/System/Library/Audio/Plug-Ins/HAL` 的整目录覆盖挂载，改为调用 `synthetic_dir("/flash/System/Library/Audio/Plug-Ins/HAL/AnnibaleAudio.driver")` 仅合成单个插件挂载点，并将 `/annibale/lib/AnnibaleAudio.driver` 绑定其上，保留原厂全部 10 个 HAL 插件可见。
- 在 `hackios-xnu-userland/userland/mkjobs.py` 中读取镜像内 `System/Library/FeatureFlags/Domain/*.plist`，按域与特性名精确求值 `#IfFeatureFlagEnabled` 与 `#IfFeatureFlagDisabled` 的 `#Then`／`#Else` 分支并剔除值为 `false` 的 `MachServices` 项。

### 2.2 19.2 MHz QTimer 下 `absolutetime_to_microtime` 的微秒溢出缺陷

SM8750 的 ARM Generic Timer（QTimer）频率为 `19,200,000 Hz`。XNU 原生 `osfmk/arm/rtclock.c` 初始化时计算 `rtclock_sec_divisor = 19200000`，并将整数商 `rtclock_usec_divisor = 19200000 / 1000000 = 19` 存入微秒除数。

`absolutetime_to_microtime()` 先对 `abstime` 取 `rtclock_sec_divisor` 的余数 `t`（范围 `0 .. 19,199,999`），再计算 `*microsecs = t / rtclock_usec_divisor`。余数落在 `[19,000,000, 19,199,999]` 区间时（每秒最后 `10.42 ms`），`t / 19` 产出 `1,000,000 .. 1,010,526`，直接违反 POSIX `struct timeval` 中 `tv_usec < 1,000,000` 的不变量，导致 CoreAudio 时间戳单调性断言与 `AVPlayer` 音画同步计算跳变。

修复补丁 `xnu26/patches/76-osfmk%arm%rtclock.c.patch` 将该换算改为 `(uint32_t)(((uint64_t)t * USEC_PER_SEC) / rtclock_sec_divisor)`。因 `t < 19,200,000`，`t * 1,000,000 < 1.92e13`，远低于 `uint64_t` 上限，输出严格落在 `0 .. 999,999`。

### 2.3 AudioReach GPR 异步队列与音量链路收敛

`annibale_audio_reach.c` 现有实现每次只向 ADSP 同步发送 1 个 `DATA_CMD_WR_SHMEM_EP_DATA_BUFFER_V2`（`0x0400100a`）缓冲槽，等 `0x05001004`（`WR_DONE`）返回后再调用 `delay_for_interval` 休眠，叠加 `annibale_adsp.c` 固定 `5 ms`／`20 ms` 的 GLINK RX 轮询周期，实测帧率被压低到 `42,318 Hz`（低于标称 `48,000 Hz` 达 11.8%）。此外，PCM 样本在 `fill_period_slot()` 内先做一次位移衰减，又在功放驱动叠加硬件衰减与固定 `-6 dB` 偏置，造成多重增益损失。

内核音频传输层按硬件节拍与单点增益原则重构。

- 在 `annibale_audio_reach.c` 的 8 槽共享内存环上采用 4 槽异步流水线预填充：流启动时连续投递 4 个 `20 ms`（`960` 帧、`3,840` 字节，48 kHz 16-bit 双声道）DMA 槽，每收到一个 `0x05001004` 完成事件立即唤醒馈送线程补充下一个槽位，由 ADSP I2S1 硬件时钟精确维持 `48,000 Hz` 节拍。
- 在 `annibale_adsp.c` 中查询音频活跃状态，音频流运行或队列非空期间将 GLINK RX 轮询间隔缩短至 `1 ms`，空闲超过排空窗口后自动填充静音帧、排空队列并关闭功放电源。
- 删除 `fill_period_slot()` 中的重复位移衰减，保留 `annibale_guard` 扬声器保护器与功放 `0.5 dB` 硬件衰减的单一映射关系。

### 2.4 双路 NXP TFA9865／TFA9866 CoolPWM 智能功放寄存器编程

反汇编原厂 `tfa98xx_dlkm.ko` 并解析 `out/fw-sensors/audio/tfa98xx.cnt`（`1,400` 字节）与设备树节点确认，K90 在 `hub_i2c0`（`GPIO64` SDA、`GPIO65` SCL）上挂载两颗 NXP TFA9865／TFA9866 智能功放（`REG_REV 0x03 = 0x9866`，`tfa_family = 2`，CoolPWM 无内置 DSP）。

- 顶部听筒兼左声道功放：7 位地址 `0x36`（容器名 `'RCV'`），复位引脚 `GPIO108`，听筒／扬声器切换引脚 `GPIO67`（低电平选择扬声器 `'stereo'` 路径），读取 TDM Slot 0。
- 底部右声道功放：7 位地址 `0x34`（容器名 `'SPK'`），复位引脚 `GPIO107`，读取 TDM Slot 1。
- 逻辑供电轨：`cdc-vdd-1p8-supply` 对应 PMIC `pm_humu_l15`（CMD_DB 资源名 `"ldob15"`），经共享 RPMh VRM 辅助模块（`0x16520000`）投票开启 `1800 mV`、HPM 模式 `7`。

对照 `tfa_dev_probe`（`0xe8fc`）、`tfaRunStartup`（`0xaf7c`）、`tfa986x_specific`（`0x11e2c`）、`tfa9865_specific`（`0x12848`）与 `tfa98xx_set_volume_level`（`0x7550`），单颗芯片在 ADSP I2S1 BCLK 启动后执行五步上电序列。

1. 使能 `ldob15` `1800 mV`，拉低 `GPIO67` 保持扬声器路由，对 `GPIO108`／`GPIO107` 执行脉冲复位并检测 I2C 应答极性，校验 `reg 0x03`（`0x9866`）并结合 `reg 0x06` 与 OTP 位域计算扩展硅片修订号。
2. 写入 `reg 0x00 = 0x0002`（`I2CR = 1`）软复位寄存器并置位 `reg 0x90[0] = 1`，随后清零 `PWDN`（`reg 0x00[0] = 0`）与 `OPEN_PROTECT`（`reg 0x04[6] = 0`），轮询 `MANSTATE`（`reg 0x12[3:0]`）到达 `1`。
3. 执行 OTP 与隐藏寄存器二级解锁：写 `reg 0x0f = 0x5a6b`，读 `reg 0xfb` 为 `v`，写 `reg 0xa0 = v ^ 0x005a`，再次写 `reg 0x0f = 0x5a6b` 并写 `reg 0xa1 = 0x005a`。
4. 按扩展硅片修订号写入 `tfa986x_specific`／`tfa9865_specific` 对应的勘误寄存器表，写回 `reg 0x0f = 0x0000` 重新上锁，短暂回到 `PWDN = 1`（`MANSTATE == 0`）并置位 `reg 0x04[6] = 1`。
5. 逐项写入 `tfa98xx.cnt` 的 39 项设备位域与 `'stereo'` 配置文件的 6 项位域：设置 `AUDFS = 8`（`48 kHz`，`reg 0x02[3:0] = 8`），`0x36` 绑定 TDM Slot 0（`reg 0x21[11:8] = 0`），`0x34` 绑定 TDM Slot 1（`reg 0x21[11:8] = 1`），通过 `reg 0x51[15:8]`（位域 `0x5187`，0.5 dB 步进）设置硬件衰减，最后清零 `PWDN`（`reg 0x00[0] = 0`）、置位 `MANSCONF`（`reg 0x01[2] = 1`）与 `AMPE`（`reg 0x00[3] = 1`）并轮询 `CLKS`（`reg 0x11[0] == 1`）确认锁相环稳定。

## 3. 相机适配：全系统原生 Metal 发现、`CMCapture` 图契约与 SM8750 CAMSS 硬件链路

### 3.1 全系统原生 Metal 发现与 `MTLGPUFamilyApple3` 能力对齐

相机与相册管线中的系统进程均通过 `Metal.framework` 的 `MTLCreateSystemDefaultDevice()` 创建 GPU 设备。此前 `MiniFramebufferUserClient.inc` 仅在 `metal >= 2` 时才在 `IOAcceleratorES` 节点上发布 `MetalPluginName` 与 `MetalPluginClassName`，默认 `metal = 1` 下未注入测试钩子的守护进程拿到 `nil`。

此外，`AnnibaleMetalDevice` 默认 `-featureProfile` 返回 `0`（低档特性集），无法通过 `MetalPerformanceShaders` 中 `MPSDevice::GetMPSDevice`（要求 `>= MTLGPUFamilyApple2`）与 `NeutrinoCore` 中 `NUPlatform_iOS.defaultSupportsLiveVideoRendering`（要求 `>= MTLGPUFamilyApple3`）的硬性门控。内核、用户态驱动与打包脚本因此同步更新。

- 在 `MiniFramebufferUserClient.inc` 中只要 `metal >= 1` 即在 `IOAcceleratorES` 上发布 `MetalPluginName = "AnnibaleMetal"` 与 `MetalPluginClassName = "AnnibaleMetalDevice"`。
- 在 `tools/k90auto/package.py` 构建并签名标准插件包 `/lib/AnnibaleMetal.bundle/{AnnibaleMetal,Info.plist}`，通过 `init.c` 暴露到 `/System/Library/Extensions/AnnibaleMetal.bundle`。
- 将 `annibalemetal_device.inc` 的默认 `featureProfile` 提升为 `4`（对应 `MTLGPUFamilyApple3` 与 `MTLGPUFamilyCommon2`），并在 `sb_metal_experiment.m` 中兼容已由系统插件加载器注册的 `AnnibaleMetalDevice` 类。
- 在 `var.skel.extra` 预置全局未压缩 `IOSurface` 分配偏好，确保跨进程相机预览缓冲可直接被 Freedreno 导入。

### 3.2 `CMCapture` 图提交 `-12780` 的剩余属性契约补齐

在[11-10 架构审查跟进记录](../progress/2026-11-10-arch-review-execution.md) §3 完成 `BWMultiStreamCameraSourceNode` 四阶段缓冲池契约的基础上，继续反汇编 `CMCapture` 的 `FigCaptureSession` 建图路径，定位出导致图提交返回 `-12780`（`kFigCaptureSessionError_InvalidConfiguration`）的四项缺失属性。

- `SoftISP` 与降噪方案：流属性声明 `SoftISP = kCFBooleanTrue` 会激活 `BWRawVideoFormatRequirements` 对 22 个传感器 Raw 标定键的强制校验。本驱动在内核／用户态已完成 Bayer 到 `420f`／`420v` 转换，应声明 `SoftISP = kCFBooleanFalse`、`StillImageNoiseReductionAndFusionScheme = 1`，并补齐 6 键 `SensorRawOutputBufferPoolRequirements` 字典。
- 流级 `ModuleInfo`：管线标定节点按流读取 `ModuleInfo`，需返回 `SensorID`（后置广角 `0x050e`、前置 `0x020b`）以及置 `0` 的镜头、对焦、马达与模组厂商标识。
- 设备级 `TuningParameters`：需包含 `DefaultSensorIDs` 以及 `PortTypeBack`／`PortTypeBackCamera`、`PortTypeFront`／`PortTypeFrontCamera` 下的 `FocalLengthCharacterization` 标定表。
- 人脸检测配置：`stream_set_property` 需接纳并保存 `FaceDetectionConfiguration` 与 `ObjectDetectionConfiguration` 而不返回未支持错误。

### 3.3 SM8750 CAMSS 电源时钟、SMMU 旁路与前后置双传感器探测

结合原厂相机与时钟模块二进制及设备树参数，梳理出 SM8750 相机硬件上电与双传感器探测的完整物理参数，并按 [AGENTS.md](../../AGENTS.md) §2 将内核驱动拆分为 `annibale_camera.c` 与 `annibale_camera_hw.inc`（单文件均控制在 1200 行以内）。

1. RPMh VRM 电源轨投票：通过共享互斥模块 `annibale_rpmh.c` 依次使能 `bobb2`（`3296 mV`）、`ldom1`（`1104 mV`）、`ldoi1`（`1152 mV`）、`ldom5`（`1800 mV`）、`ldob10`（`1800 mV`）、`ldom3`（`2800 mV`）、`ldob8`（`2800 mV`），并拉高板上电源使能 `GPIO127`。
2. GCC 与 CAMCC／CPAS 时钟上电：置位 `GCC_APSS_CLOCK_BRANCH_ENA_VOTE_1`（`0x52010`）第 20 位，开启 `GCC_CAMERA_AHB_CBCR`（`0x26004`）、`GCC_CAMERA_XO_CBCR`（`0x26034`）、`nrt_ahb`（`0x26008`）、`rt_ahb`（`0x2600c`）、`cmd_ahb`（`0x26010`）、`hf_axi`（`0x26014`）、`sf_axi`（`0x26024`），再开启 `CAMCC`（`0x0ade0000`）与 `CAM_CPAS`（`0x0ac13000`）GDSC 及分支时钟。
3. `apps_smmu`（`0x15000000`）幂等旁路：遍历 SMR 表查找已有 `SID 0x1c00` 表项，复用已有槽位或分配空闲槽位配置 `S2CR = BYPASS`，杜绝重复开机或重入时的 SMR 冲突故障。
4. 后置与前置传感器探测：后置主摄经 `CCI0`（`0x0ac7b000`，I2C 地址 `0x36`）读取 OmniVision `OV50E` 芯片 ID；前置传感器走独立 QUPv3 GENI SE9 I2C 控制器（`0x00884000`，7 位从机地址 `0x10`，复位引脚 `GPIO117`）读取 `OV20B` 芯片 ID。
5. 修正 `CAMIOC_G_INFO` 返回的 `flags` 极性：硬件探测就绪时置 `0`（实传感器流），回退测试彩条时置回退标志位，消除用户态与内核态对状态位的反向解读。

## 4. 视频硬解与合成：10-bit／BT.2020 YUV 管线、Iris v3.5 内核驱动与 `VideoToolbox` 插件

### 4.1 Metal YUV 合成管线修复（10-bit P010、format `500` 与 BT.2020）

iOS 系统播放器（`AVSampleBufferDisplayLayer`／`FigVideoQueue`）向 CoreAnimation 提交软解或硬解视频帧时使用 `IOSurface` 承载双平面 YUV 纹理。静态核查 `annibaledrawable.m`、`annibalemetal_yuv.inc` 与 `tools/mesa/air/air_metal_yuv.inc` 定位出四处阻断点。

- 10-bit 双平面格式缺失：`annibaledrawable.m` 未处理 `'x420'` 与 `'xf20'`（10-bit P010），需按平面分别映射为 `MTLPixelFormatR16Unorm`（`20`）与 `MTLPixelFormatRG16Unorm`（`60`）。
- format `500` 尺寸比较过严：`annibalemetal_yuv.inc` 要求创建的纹理宽高严格等于平面宽高，而解码器输出常带宏块对齐填充（如 `1088` 行承载 `1080` 有效行），需放宽为 `<=` 平面尺寸。
- 纹理用途位拦截：CoreAnimation 为视频层附加 `MTLTextureUsagePixelFormatView`（`0x10`），需在 `annibalemetal_yuv.inc` 的允许掩码中放行该标志位。
- BT.2020 色彩矩阵缺失：HDR 与广色域视频携带 `matrix == 9`（`ITU_R_2020`），需在 `annibalemetal_yuv.inc`、`air_metal_yuv.h`、`air_metal_yuv.inc` 与 `air_metal_resource_private.h` 中补齐 BT.2020 窄域与全域 YCbCr→RGB 转换系数并重编 `libannibaleair.dylib`。

### 4.2 SM8750 Iris VPU v3.5 硬件架构与固件引导序列

反汇编原厂 `msm_video.ko`（`__power_on_iris35`、`__boot_firmware_iris35`、`sun_reg_preset_table`、`sun_context_bank_table`）与 `videocc-sun.ko`、`gcc-sun.ko` 确认，SM8750 集成 Iris v3.5 视频编解码器（`qcom,sm8750-vidc-v2`，寄存器基址 `0x0aa00000`），配套时钟控制器为 `videocc`（`0x0aaf0000`），固件文件为 `out/fw-iris/vpu35_4v.mbn`（`2,413,256` 字节，ELF32，由 TZ PAS ID `9` 验签加载至保留内存 `0x9c300000`，大小 `0x800000`）。

| 资源类别 | 硬件对象与寄存器／地址 | 配置参数 |
|---|---|---|
| RPMh 电源域 | `mmcx.lvl`、`mxc.lvl` | 经 ARC 投票至 `SVS`／`NOM` 等级后再操作 `videocc` GDSC |
| GCC 视频时钟 | `0x52010` bit 21、`0x32004`（AHB）、`0x32038`（XO）、`0x32008..0x32014`（QMIP AHB）、`0x32018`（AXI0）、`0x32028`（AXI1） | 逐项置位使能并轮询 `CLK_OFF`（bit 31）清零 |
| `videocc` 时钟与 GDSC | `PLL0`（`0x0000`，`L=0x25`）、`MVS0_CMD_RCGR`（`0x8000`）、`MVS0C_GDSCR`（`0x8034`）、`MVS0_GDSCR`（`0x8068`）、`MVS0C_CBCR`（`0x804c`）、`MVS0_CBCR`（`0x807c`） | 先开 `MVS0C`（控制面）GDSC 与存储保持位 `0x8040`，再开 `MVS0`（核面）GDSC 与 `0x8074`，使能分支与 freerun 时钟，最后写入 `sun_reg_preset_table` |
| `apps_smmu` Stage-1 | 非像素上下文 `cb-ns`（`SID 0x1940`，IOVA `0x25800000..0xe0000000`）与像素上下文 `cb-ns-pxl`（`SID 0x1947`，IOVA `0x00100000..0xe0000000`） | 建立 Stage-1 页表；在 `SID 0x1940` 额外映射设备区 QTimer `0x17421000 -> 0xffade000` 与 QDSS `0x00508000 -> 0xffadf000` |
| PAS 固件引导 | TZ SMC `qcom_scm_pas_init_image`／`mem_setup`／`auth_and_reset`（PAS ID `9`） | 将 `vpu35_4v.mbn` 的 `PT_LOAD` 段装载到 `0x9c300000` 并清零 BSS 段（`PH[11,13,15,17,19]`），验签释放复位 |
| HFI 握手机制 | `0x0a0064`（队列基址 IOVA）、`0x0a0068`（`0x300000`）、`0x0a0054`（UC 区基址）、`0x0a005c`（SFR IOVA）、`0x0a0024`（`0xffade000`）、`0x0a0028`（`0x2000`）、`0x0b0078`（`1`）、`0x0a0050`（`1`）、`0x0a0048`（`1`） | 轮询 `0x0a004c` bit 0 置位且 bits `[3:1] == 0`，随后写 `0x0a0148 = 1`、`0x0a0168 = 0` 完成 HFI 命令／消息／调试三队列建链 |

### 4.3 HFI Gen2 解码会话与 `videocodecd` 的 arm64e `VideoToolbox` 插件

内核驱动按职责拆分为三个文件（单文件均在 1200 行以内），分别对应 `annibale_iris.c`（字符设备 `/dev/annibale-iris` 与 ioctl 会话生命周期）、`annibale_iris_hw.c`（RPMh、GCC／`videocc`、`apps_smmu` Stage-1 映射与 PAS `9` 固件装载）、`annibale_iris_hfi.c`（HFI Gen2 数据包封装、系统初始化、H.264 `codec=1`／HEVC `codec=3` 的原生 HFI 解码会话配置、内部暂存缓冲分配与线性 `NV12` `color_format=1` 帧收发；公共 ioctl 的 HEVC 标识保留为 `2`）。

为兼容带 B 帧重排的 MP4／HLS 流，`struct iris_decode_frame` 将 64 位 `in_tag` 写入 `hfi_buffer.timestamp` 并随输出 `HFI_BUFFER_RAW` 透传回 `out_tag`，通过 `IRIS_FRAME_DRAIN` 发送 `HFI_CMD_DRAIN`，匹配命令应答与 drain-last，使用 `IRIS_FRAME_POLL` 读取延迟帧。用户空间输入长度、分辨率与会话槽位在 ioctl 边界执行越界检查。文件描述符关闭后按进程 PID 查找会话，仅在已启动端口 STOP、会话 CLOSE 和 TLB 同步均确认成功后释放页面；失败后保留页面与槽位。

用户态新增 `hackios-xnu-userland/userland/src/inject/videotoolbox_iris.c`（构建为 `libannibale-vt.dylib`），经扩容至 4096 字节的 `kern.annibale.inject`（`09-bsd%kern%kern_exec.c.patch`）注入 `videocodecd`、`mediaserverd`、`com.apple.WebKit.GPU`、`video_decode_test` 与 `video_player_test`。

- 构造函数调用 `IRIS_IOC_GET_INFO` 探测 `/dev/annibale-iris`；仅在返回 `IRIS_INFO_HW_READY` 时调用 `VTRegisterVideoDecoderWithInfo` 注册 `'avc1'`、`'hvc1'` 与 `'hev1'` 硬解器（声明 `IsHardwareAccelerated = kCFBooleanTrue`），硬件未就绪或固件缺失时不注册硬解组件，保留 `VideoToolbox` 原生软解路径。
- 静态核对 `23G90__iPhone18,3` 的 `VideoToolbox`（`0x1903bc894`）确认 `_VTDecoderSessionCreatePixelBuffer` 采用三参数签名 `(session, frameRef, &pixelBuffer)` 并转发至 `_VTDecoderSessionCreatePixelBufferWithOptions`，`CMBaseClass`（版本 1）与 `VTDecompressionBackendClass`（版本 2）函数表均按 iOS 26 arm64e 指针认证鉴别器签名。
- 解码会话解析 `CMFormatDescription` 提取 `avcC`／`hvcC` 参数集（SPS／PPS／VPS），在首个同步帧前拼接 Annex-B 参数集并将长度前缀 NALU 转换为起始码字节流送入 `/dev/annibale-iris`，按 `out_tag` 匹配在途整数 `VTDecodeFrameRef`（保留原始 PTS 与 `sourceFrameRefCon`，token 按原值送回且不执行 CF 引用计数），在 `finishDelayedFrames` 中经 `IRIS_FRAME_DRAIN`／`IRIS_FRAME_POLL` 排空重排帧并写入 `CVPixelBufferPool` 分配的 `'420v'` `IOSurface` 缓冲回调给 `VTDecompressionSession`。

## 5. 背光同步收尾与工程复杂度控制

`MiniAppleARMBacklight.cpp` 的 `bl_take()` 按字段区分亮度单位：`DisplayBrightness.NitsPhysical`／`Nits` 使用普通 nits，IOMFB 与 NVRAM 字段使用 16.16。滑块位置记录交互与保存用途，面板亮度采用原生 nits 或面板值；收到 `s16 <= 0` 或 `value == 0` 的锁屏熄屏通知后下发关光指令，保留 `last_millinits` 与 `ramfs_backlight_save` 中的用户亮度记忆。用户报告的物理闪烁仍待真机复核，时间点与宿主检查见[多媒体验证结果 §7](2026-11-11-multimedia-validation.md#7-手电筒亮度与相机的新反馈)。顶层仓库与 `hackios-xnu-kernel/xnuloader/` 中关于 Fastboot 119／511 字节命令边界及退回态 USB 冷复位恢复的修改同步保留并通过单测。

跨模块修改复用已有资源管理与构建入口，检查结果按实际覆盖范围记录。

- 共享基础设施。相机、音频功放、ADSP 与 Iris VPU 共用互斥序列化的 `annibale_rpmh.c`，消除重复的 CMD_DB 查找与 TCS 轮询实现。
- 遵守 1200 行文件上限。`annibale_camera.c` 拆出 `annibale_camera_hw.inc`，Iris 驱动按设备入口、硬件上电与 HFI 协议拆为三文件，本次涉及的全部源码文件均在 1200 行以内。
- 真实能力上报。相机 `CAMIOC_G_INFO` 与 `videotoolbox_iris` 均按真实硬件就绪状态上报，移除无消费者的投机字段，不伪造硬解标志或掩盖硬件错误。
- 宿主检查与构建。背光、引导安全、任务缓存、音频插件与传输、Metal 与着色器 YUV、相机契约、根盘切换及 Iris／VideoToolbox 的检查结果见[多媒体验证结果](2026-11-11-multimedia-validation.md)。真机起轮与收尾按 [AGENTS.md](../../AGENTS.md) §5 核验；宿主、设备初始化与用户可用行为分别验收。
