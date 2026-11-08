# 视频解码调研：H.264／HEVC／VP9 在 iOS 26 移植上的播放与 SM8750 硬件解码

调研日期 2026-11-05。只做了静态分析与已有日志的读取，没有构建、没有对设备发命令。凡标「推断」的结论没有在设备上验证过。地址均为 23G90 共享缓存未滑动前的地址，用 `hackios-xnu-kernel/tools/dsc/dsc.py` 可复查。

## 1. 结论摘要

- H.264 的软件解码器在系统里，而且已经解出了画面：fp1 轮打开测试页后约 1 秒，backboardd 收到一张 `'420v'`、640×360 的 IOSurface（与测试视频同尺寸），我们的 Metal 驱动拒绝把这种两平面 YCbCr 格式做成纹理，同一张 surface 被拒绝至少 16384 次。黑屏、时间停在 0、随后 `err=3` 的直接原因很可能是合成这一步（推断，见 §2.2）。
- VP9 没有任何可用的解码器：AVD 没有注册，iOS 版 WebKit 自带的 libvpx VP9 软件解码器只在内部开关 `SWVPDecodersAlwaysEnabled` 打开时才注册，Safari 正式版不会去设这个开关。
- 最先该做的是 YCbCr（`420v`／`420f`）合成，它同时是软件解码、WebKit VP9 软件解码和以后硬件解码的共同前提。其次是开 WebKit 的 VP9 软件解码。Iris 硬件解码要内核驱动加 VideoToolbox 解码插件，工作量以周到月计。
- dada 参考项目没有做视频解码，只调了 HEIC 用的 VCPHEVC 线程数。

## 2. 现在为什么放不出来

### 2.1 解码走哪条进程链

- iOS 26 已没有 mediaserverd：`ios26/rootfs.slt` 里没有 `usr/sbin/mediaserverd`，也没有它的 LaunchDaemon。`userland/src/inject_media.c` 头注释里「VideoToolbox 在 mediaserverd 里为别的进程解码」写的是 iOS 16 的结构，在 iOS 26 上不成立。
- 播放器在 mediaplaybackd：特性开关 `CoreMedia/SeparatePlayerProcess` 为 Enabled（`rootfs/System/Library/FeatureFlags/Domain/CoreMedia.plist`），WebKit GPU 进程里的 AVPlayer 把播放交给 mediaplaybackd。
- 解码在 videocodecd：`CoreMedia/SeparateCodecProcess` 为 Enabled，`MediaplaybackdUseOutOfProcessDecode` 为 FeatureComplete。
  - VideoToolbox 的判断函数是 `VTVideoCodecService_ShouldUseSeparateCodecProcessForDecode`（0x190601218，读 `CoreMedia/SeparateCodecProcess`）和 `VTVideoCodecService_ShouldUseOOPDecodeForVideoPlayer`（0x190601398，读 `MediaplaybackdUseOutOfProcessDecode`）。
  - 远端服务名 `com.apple.coremedia.videocodecd.decompressionsession`（字符串 0x1906a73c6）。
  - 带 `com.apple.videotoolbox.decode-in-process` 权限（字符串 0x1906a4c05）的进程留在本进程解码（推断：按字符串用途判断，未反汇编使用处）。
- 资源解析在 mediaparserd：fp1 打开测试页约 204 秒后的 `ps`（命令序号 80，输出在 `docs/progress/evidence/k90auto/kernel-12377-rate10-fp1/run/s111.log`）列出 mediaplaybackd（365）、mediaparserd（366）、videocodecd（368）、com.apple.WebKit.GPU（313）。

### 2.2 H.264：软件解码器已注册，第一帧到了合成器

- VideoToolbox 自带一张解码器表，逐项 `dlopen`＋`dlsym`＋调用注册函数，没有条件判断（0x1904de12c～0x1904de324，辅助函数 0x1904de340；桩 0x190696ea8／0x190696eb8 解析为 `_dlopen`／`_dlsym`）。表中与本题有关的项：
  - `/System/Library/VideoCodecs/H264SW.videocodec` → `VCPAVCRegisterDecoder`
  - `/System/Library/VideoCodecs/VCPHEVC.videocodec` → `VCPHEVCRegisterDecoder`
  - `/System/Library/VideoDecoders/AVD.videodecoder` → `AVDRegister`
  - `/System/Library/VideoDecoders/AV1SW.videodecoder` → `AV1RegisterDecoder`
- `VCPAVCRegisterDecoder`（0x29ffc9a74，一次性执行体 0x29ffc9aa0）无条件调用 `VTRegisterVideoDecoderWithInfo('avc1', {kVTVideoDecoder_IsHardwareAccelerated: kCFBooleanFalse}, 0x29ffc99a0)`（桩 0x2a2a57460 解析为 `_VTRegisterVideoDecoderWithInfo`）。字符串里有 `com.apple.coremedia.JVTlib`、`ThreadCountH264SWDecoder`，是一套带多线程的完整 H.264 软件解码器。
- `AVDRegister`（0x2a03fb694）先调用 0x2a04191f4（内含 `AppleAVDCheckPlatform`），返回非 0 就跳过全部注册。我们的内核没有 AppleAVD（`xnu/files/iokit/Kernel/` 下只有 Mini*／Annibale* 替身），所以 AVD 不注册（推断：按控制流，未在设备上读注册表）。`avc1` 只剩 H264SW 可选。
- 解码确实发生了：fp1 的 `s070.log` 第 17024 行起，backboardd 的 Metal 驱动报 `no drawable (1): format 500 usage 0x1: surface 134 ('420v', 640x360, 1028 bytes a row): pixel format 500 is MTLPixelFormatYCBCR8_420_2P: YCbCr in TWO PLANES, and this import serves one`。这一行在 mediaplaybackd 启动（第 16862 行，07:25:48.987）之后、它的下一条日志（第 17693 行，07:25:49.911）之前。
- 同一张 surface 134 的拒绝计数到 16384（驱动只在 2 的幂次打印，`annibalemetal.m` 的 `RW_AGAIN`），全程没有出现第二个视频 surface。
- 拒绝的出处：`userland/src/annibaledrawable.m` 第 425～448 行，缺三样东西：内核 `kAnnibaleSurface` 只报平面数、不报每个平面的偏移和行长（`AnnibaleGPU.cpp:849`），Gallium 侧没有对应的两平面格式，没有 YCbCr→RGB 转换。MiniIOSurface 本身已按 `IOSurfacePlaneInfo` 建平面（`MiniIOSurface.cpp` 第 510～534 行）。
- 推断的失败链：合成器拿不到纹理，图像队列的队头一直不被消费；解码输出池耗尽后流水线停在第一帧，时间停在 0，播放器最后报错，WebKit 把 AVPlayerItem 失败映射成 `MEDIA_ERR_DECODE`。videocodecd 在页面打开约 200 秒后只用了 0.05 秒 CPU、2 个线程，与「只解了很少几帧」相符。没有 mediaplaybackd／videocodecd 的 os_log，无法确认播放器报的具体错误码。
- 另一个需要排除的干扰项：测试页由 `python3 -m http.server` 提供，Python 3.13 的这个服务器不支持 Range 请求（`http/server.py` 里没有 `Content-Range`），而 Apple 要求给 iOS 提供媒体的服务器支持字节范围请求。第一帧在 1 秒内就到了合成器，这次 H.264 失败的主因大概率在合成一侧（推断）；MSE 和拖动进度仍会受 Range 支持的影响。

### 2.3 VP9：没有可用的解码器

- 系统解码器表里没有软件 VP9；`vp09` 只有 AVD 会注册（硬件）。
- WebKit 的软件 VP9 来自 libwebrtc：`libwebrtc.dylib` 导出 `webrtc::registerWebKitVP9Decoder()`（0x29c169d24）。按 WebKit 主线源码（`Source/WebKit/GPUProcess/GPUProcess.cpp` 第 344～350 行、`Source/WebCore/platform/graphics/cocoa/VP9UtilitiesCocoa.mm` 第 208～226 行），GPU 进程只在 `shouldEnableSWVP9Decoder()` 为真时注册它，条件是 `SWVPDecodersAlwaysEnabled || (!vp9HardwareDecoderAvailable() && !systemHasBattery())`。iOS 上 `systemHasBattery()` 固定返回 true（`Source/WebCore/platform/cocoa/SystemBattery.mm` 第 50～52 行），所以只剩那个开关。
- iOS 上 `isVP9DecoderAvailable()` 只看 `SWVPDecodersAlwaysEnabled` 和 `vp9HardwareDecoderAvailable()`（`VP9UtilitiesCocoa.mm` 第 218～224 行），后者来自 GPU 进程里的 `VTIsHardwareDecodeSupported('vp09')`。
- 现象与此相符（推断）：WebKit 自己的 WebM 解析器（`MediaPlayerPrivateWebM`，WebCore 字符串 0x1a3681b2a）读出了元数据，readyState 到 1；没有解码器，没有帧，停在 `loadedmetadata`。
- VideoToolbox 对 VP9 还有一道门：`VTIsHardwareDecodeSupported`（0x1903bc288）对 `vp09` 额外加入 `kVTVideoDecoderSpecification_AllowVP9Decode`（0x1e66d49c0）；MediaToolbox 有 `kFigPlayerOptionKey_AllowVP9Decode`、`kFigAssetOptionKey_AllowVP9Decode` 等选项。VP9 只对显式允许的调用方开放（推断：按符号用途判断）。

### 2.4 日志缺口

- 所指的 `kernel-12377-rate8-app2` 轮里，mediaplaybackd 与 videocodecd 的 plist 带 OS_ACTIVITY_DT_MODE（653／2281 字节），但日志在 02:31 结束，测试页在 02:33:52 才打开（主机服务器日志），这一轮没有解码期间的记录。
- 02:33:52 那次打开落在 `kernel-12377-rate8-app3`，该轮的这两个 plist 没有带 OSLOG（591 字节），控制台只记下 mediaplaybackd 的两行启动信息。
- fp1 同样没有这两个进程的 os_log。§2.2 的结论来自 backboardd 的 Metal 驱动日志和 `ps`。

## 3. iOS 自带的软件解码

### 3.1 各编码的解码器与限制

| 编码 | 系统里的软件解码器 | 注册情况 | Safari 能否用到 |
|---|---|---|---|
| H.264 | `H264SW.videocodec`（JVTlib） | 无条件注册，`IsHardwareAccelerated` 为 false | 已在用；卡在 YCbCr 合成（§2.2） |
| HEVC | `VCPHEVC.videocodec` | 注册函数 `VCPHEVCRegisterDecoder`（0x2a00dbf7c），iOS 16 上已用于 HEIC（`inject_media.c` 头注释） | 渐进式 mp4 走 AVPlayer，预计与 H.264 卡在同一处（推断）；MSE 里的 HEVC 能力检查未核对 |
| VP9 | 无（只有 AVD 硬件） | — | 需要 WebKit 的 libvpx 解码器（§3.2） |
| AV1 | `AV1SW.videodecoder`，带 `AV1SW.metallib` | `AV1RegisterDecoder`（0x2a02a3430）无条件注册 `av01`，`IsHardwareAccelerated` false，类 ID `com.apple.videotoolbox.videodecoder.av1.sw` | WebKit 在 iOS 上要求 `VTIsHardwareDecodeSupported('av01')`（`AV1UtilitiesCocoa.mm` 第 213～236 行）；MediaToolbox 有 `UseSWAV1`、`Remaker_EnableDecodeAppleOnlySWAV1`，软件 AV1 只给 Apple 自己的场景用（推断） |

WebCore 里还静态链接了 dav1d（字符串 `dav1d_open` 等，0x1a366eaaa 起）和 libvpx（`LibWebRTCVPXInternalVideoDecoder`），它们服务 WebRTC／WebCodecs。WebCodecs AV1 的开关 `WebCodecsAV1Enabled` 状态为 preview。

### 3.2 能用的开关与注入点

- `SWVPDecodersAlwaysEnabled`：iOS 26 WebKit 里有这个键和说明「Always enable VPx software decoders」（字符串 0x19fd67247、0x19fd67223）。主线 `UnifiedWebPreferences.yaml` 里它的状态是 `internal`，默认值只在 iOS 模拟器上为 true。
- Safari 正式版设不到它（推断：按主线源码，iOS 26.6 的 WebKit 版本可能略有差别）：
  - `-[_SFBrowserContentViewController _initializeWebKitExperimentalFeatures]`（SafariServices，0x1d79d6a5c）只遍历 `+[WKPreferences _experimentalFeatures]`，从 Safari 的 defaults 读值后调 `_setEnabled:forExperimentalFeature:`。
  - `_experimentalFeatures` 只含 developer／testable／preview／stable 状态的特性（WebKit 主线 `Source/WebKit/UIProcess/WebPreferences.cpp` 第 109～121 行），internal 特性在 `_internalDebugFeatures` 里。
  - IPSW 里没有 `WebKitInternalSettings.bundle`（`rootfs.slt` 无此路径），这个开关也不在 `defaultsOverridable` 之列，写 defaults 无效。
- 可行的做法（推断，未试）：
  - 在 MobileSafari 里注入一个库，创建网页视图前对 `SWVPDecodersAlwaysEnabled` 调用 `-[WKPreferences _setEnabled:YES forInternalDebugFeature:]`。WebKit 会把它带进 GPU 进程偏好，GPU 进程随后注册 libwebrtc VP9 解码器，网页进程那边 `isVP9DecoderAvailable()` 也成立。
  - 退而求其次：在 com.apple.WebKit.GPU 里直接调用 `webrtc::registerWebKitVP9Decoder()`。网页进程对 VP9 的判断仍为假，这条路不完整。
  - init 已有按进程名插入库的机制（`s001.log`：`init: library insertion: ... SpringBoard backboardd ...`），对 MobileSafari、com.apple.WebKit.GPU、videocodecd 是否按同样的进程名匹配，未核对。
- 软件解码线程数：
  - H.264：`ThreadCountH264SWDecoder`，与 CFString `com.apple.coremedia` 相邻（H264SW 的 `__cfstring` 0x2b28e4bc0、0x2b28e4be0），偏好域为 `com.apple.coremedia`（推断）。
  - HEVC：dada 仓库的 `userland/userland/var/mobile/Library/Preferences/com.apple.VideoProcessing.plist` 注释写明 VCPHEVC 把该域的每个键当作选项，默认只用一个线程，他们设了 `threading=auto`、`max-threads=7`。
- 环境变量：没有找到能让 Safari 改用软件解码的环境变量。H.264 本来就走软件，不需要开关。

### 3.3 1080p 软件解码的 CPU 估算（推断）

- 依据一：树莓派 5（4 个 Cortex-A76，2.4 GHz）上 Android 的 `c2.ffmpeg.h264.decoder` 播 1920×1080、10.4 Mbps、30 帧时，编解码服务占 40.1% CPU，0 丢帧（emteria，来源见 §7）；文中没说百分比按单核还是全部核计。
- 依据二：dav1d 0.5 在骁龙 835 上用 4 个大核解 1080p AV1 能超过 60 帧（Ewout ter Hoeven 的 dav1d 测评）。
- 换算到 SM8750 的高性能核（Oryon），1080p30 大约是：H.264 一个核的 15%～60%，HEVC 与 VP9 约为 H.264 的 1.5～2 倍，AV1 约 2～3 倍。Apple 自家 JVTlib、VCPHEVC、AV1SW 的效率没有数据，估算只按 ffmpeg／dav1d 的量级。
- 默认 `cpus=4`（loader 依次取 0x10100、0x10000、0x500、0x400），1080p30 的 H.264／VP9 软件解码放得下；4K60 不现实。
- 准确数字要靠 §6 第 0 步的 `vt_test` 在本机测。

## 4. SM8750 硬件解码

### 4.1 硬件与主线驱动

- SM8750 的视频块是 Iris VPU v3.5，主线 `drivers/media/platform/qcom/iris` 已支持，平台数据 `sm8750_data` 在 `iris_platform_vpu3x.c`（Krzysztof Kozlowski 的系列「media: iris: Add support for SM8750 (VPU v3.5)」）。设备树节点在 `arch/arm64/boot/dts/qcom/sm8750.dtsi`，默认 `status = "disabled"`，注释写明固件由厂商签名，只在有签名固件的板子上打开。
- 主线声明的解码格式：H.264、HEVC、VP9、AV1（`iris_fmts_vpu3x_dec`）。第三方项目 sm8750-video-accel 在小米平板（代号 piano）上实测：H.264、HEVC（含 Main10）、VP9 解码可用，AV1 解码在最后一步提交失败；编码只有 H.264、HEVC。
- 主线 iris 目录 67 个文件约 690 KB 源码，HFI gen2 与缓冲区尺寸公式占大头（`iris_vpu_buffer.c` 91 KB、`iris_hfi_gen2.c` 82 KB）。

| 资源 | 主线 sm8750.dtsi／驱动中的值 |
|---|---|
| 寄存器 | `0x0aa00000`，长 `0xf0000`；videocc 在 `0x0aaf0000` |
| 中断 | GIC SPI 174，高电平 |
| 固件内存 | `video_mem` 位于 `0x9c300000`，8 MB，no-map；我们的硬件图谱也记了这块（`docs/analysis/annibale-hw-map.md` 第 238 行） |
| 电源域 | `VIDEO_CC_MVS0C_GDSC`（venus）、`VIDEO_CC_MVS0_GDSC`（vcodec0，硬件控制）、RPMh 的 MXC 与 MMCX |
| 时钟 | `GCC_VIDEO_AXI0/AXI1`，videocc 的 `MVS0C`、`MVS0`、两个 freerun；videocc 只有一个 Taycan ELU 锁相环 `video_cc_pll0`（`drivers/clk/qcom/videocc-sm8750.c`） |
| 复位 | `GCC_VIDEO_AXI0/AXI1_CLK_ARES`，videocc 两个 freerun ARES |
| 互连 | `MASTER_APPSS_PROC → SLAVE_VENUS_CFG`（cpu-cfg），`MASTER_VIDEO_MVP → SLAVE_EBI1`（video-mem） |
| SMMU | apps SMMU，流 ID `0x1940`、`0x1947`，`dma-coherent` |
| 工作点 | 240～630 MHz，各档对应 MXC／MMCX 的 RPMh 等级 |
| 固件加载 | PAS ID 9（`iris_firmware.c` 的 `IRIS_PAS_ID`），mdt 装进 `video_mem` 后 `auth_and_reset`，再调用 `qcom_scm_mem_protect_video_var(0, 0x25800000, 0x01000000, 0x24800000)` |
| 设备地址上限 | `dma_mask = 0xe0000000 - 1` |

### 4.2 固件

- 不能用 linux-firmware 里的通用 `qcom/vpu/vpu35_p4.mbn`：小米设备只认厂商签名的文件（推断，依据是 piano 的做法和 dts 的注释）。piano 用的是从原厂 odm 分区取出的 `vpu35_4v.mbn`，经设备树的 `firmware-name` 加载（blu-sharky/piano-firmware PR #4）。
- K90 备份里的 modem 分区（`annibale-backup/20261022-2355/modem_a.img.gz`，用 `tools/mk-fw-wifi.py` 的 FAT16 读取器列出 `image/` 下 461 个文件）没有 vpu 固件。备份里没有 super／odm／vendor 分区，固件要由 device 成员在 Android 下从 odm 或 vendor 分区只读取出，做法与 `gen80000_zap.mbn` 相同。具体路径未核对，预计在 `/odm/firmware/` 或 `/vendor/firmware/` 下（推断）。

### 4.3 XNU 驱动要做的事

可复用的现有代码：

- `adreno8_zap.c` 已经走通 PAS（`0x42000201` init_image、`0x42000202` mem_setup、`0x42000205` auth_and_reset，PAS ID 13）；视频改用 PAS ID 9，再加一个 `MP_VIDEO_VAR` 调用（服务 0x0c、命令 0x08，按 Linux `qcom_scm` 的编号推得 `0x42000c08`，未核对）。
- `adreno8_clock.c` 已有 GPUCC 的 Taycan ELU 锁相环与 RCG2 序列，`adreno8_cx.c` 有 GDSC 操作，`adreno8_rpmh.c` 有 apps RSC DRV2 的 ARC 投票。videocc 用同一类锁相环。
- `mhi_pcie.c` 已能只读访问 apps SMMU（`0x15000000`）。

要新写的部分：

1. 上电：RPMh 投 MMCX、MXC 等级；互连的 BCM 带宽投票（现有代码只有 ARC，没有 BCM，`drivers/interconnect/qcom/sm8750.c` 有节点表）；开 `GCC_VIDEO_AHB/AXI0/AXI1`，配 `video_cc_pll0`，开 MVS0C、MVS0 的 GDSC 与时钟，按 `iris_vpu35_power_on_hw` 与 `iris_vpu35_vpu4x_power_on_controller` 的顺序。
2. 固件：把厂商签名的 mbn 按段装进 `0x9c300000`，PAS 鉴权并复位，设置 CP 内存区间。
3. SMMU：为流 `0x1940`／`0x1947` 配 apps SMMU 的上下文（一级页表，地址 0～`0xe0000000`），固件的非像素区间从 `0x01000000` 开始。
4. 启动 HFI：分配命令、消息、调试三条队列和 SFR（4 KB 对齐，`iris_hfi_queue.h`），把队列表地址写进 CPU_CS 寄存器，等控制器初始化完成，接 SPI 174 中断。
5. HFI gen2 解码会话：系统初始化、打开会话、设置码流与输出属性、按公式分配内部缓冲（BIN、COMV、NON_COMV、LINE、PERSIST、DPB 等）、送码流、取帧、分辨率变化事件、排空与 EOS。
6. 输出格式：用线性 NV12（行长与行数按 Iris 的对齐），直接写进按同样布局创建的 `'420v'` IOSurface，避免拷贝。

### 4.4 接到 iOS

- 做 AppleAVD 兼容的 IOKit 服务不可行：`AVD.videodecoder` 在用户态自己拼 Apple AVD 硬件的寄存器命令和补丁表（字符串如 `Failed to add %s %s buffer to patch list`、`decodeGetRenderTargetRef`），与 Iris「整段码流交给固件」的接口层次不同，翻译不过去。
- 可行做法是自己的 VideoToolbox 解码插件，和 Apple 自带插件用同一个 SPI：`VTRegisterVideoDecoderWithInfo(codec, {kVTVideoDecoder_IsHardwareAccelerated: true, ...}, createInstance)`，解码类通过 `VTDecoderSessionEmitDecodedFrame`、`VTDecoderSessionCreatePixelBuffer` 等导出函数交帧（VideoToolbox 导出表里都有）。
- 插件要在每个解码或查询能力的进程里注册：videocodecd（AVPlayer 与 MSE 的远端解码）、com.apple.WebKit.GPU（`VTIsHardwareDecodeSupported` 的结果决定 WebKit 是否认为有 VP9／AV1／HEVC 硬件）。`VTIsHardwareDecodeSupported` 只查本进程注册表里带 RequireHardware 规格的解码器（0x1903bc288 调 0x1901898f0），插件注册后它会返回 true（推断）。
- 插件与内核之间：仿照现有 `/dev/annibale-*` 设备节点或 IOKit 用户客户端，提供打开会话、送码流（共享内存）、送输出 IOSurface（内核把页映射进 SMMU）、取事件这几个调用。
- 插件侧的工作：从 `avcC`／`hvcC`／`vpcC`／`av1C` 取参数集，H.264／HEVC 把长度前缀改成起始码，按呈现时间交帧，实现 `FinishDelayedFrames` 与刷新。解码类的方法表布局要从 H264SW 的 `createInstance`（0x29ffc99a0）反推。

### 4.5 最难的未知

- PAS 鉴权：厂商签名的 vpu35 固件能否用我们的调用顺序通过鉴权，TZ 是否还要求额外的内存分配给 VMID（hyp assign）。
- apps SMMU：在 Gunyah 下由我们编程一级上下文是否被允许，流 `0x1940`／`0x1947` 当前的路由状态。
- videocc 锁相环与 MMCX 供电：loader 交接后 videocc 的初始状态未读过。
- HFI gen2 协议和缓冲区尺寸公式的体量，以及固件对内部缓冲布局的要求。
- iOS 侧：解码插件 SPI 的方法表与属性键；`AllowVP9Decode` 等规格如何影响插件被选中；YouTube 看到「有 VP9／AV1 硬件」后会选更高码率，需要真的能解。
- 这条路同样依赖 §2.2 的 YCbCr 合成。

## 5. dada 是否做了视频解码

没有。dada 只读克隆里与编解码有关的只有两处：README 提到 Camera.app 能拍 HEIC 照片；`userland/userland/var/mobile/Library/Preferences/com.apple.VideoProcessing.plist` 给 VCPHEVC 开多线程（§3.2）。没有 VideoToolbox 插件、Iris 驱动、视频固件或 Safari 视频相关的改动（按 `git ls-files` 逐文件扫描 `VTDecompress`、`VideoToolbox`、`AppleAVD`、`videocodecd`、`vp9`、`iris`、`vpu` 等关键字）。它的 `inject_media.c` 与我们同源，头注释同样是 iOS 16 的说法。

## 6. 建议顺序（成本低、收益先到的在前）

0. 诊断一轮，不改代码：
   - 测试页换成支持 Range 的服务器，先用 `curl --range 0-99` 确认只回 100 字节。
   - 给 `com.apple.mediaplaybackd`、`com.apple.videocodecd` 开 OSLOG，backboardd 保持安静，控制台能留下播放器的错误码。
   - 写一个 `vt_test`：带 `com.apple.videotoolbox.decode-in-process` 权限和不带各跑一次，对 `h264.mp4` 的样本做 `VTDecompressionSession` 解码，记录帧数、`UsingHardwareAcceleratedVideoDecoder`、每帧 CPU 时间。§3.3 的估算可以换成实测。
1. YCbCr 两平面合成（`420v`／`420f`）。按 `annibaledrawable.m` 列的三项实现：`kAnnibaleSurface` 报每个平面的偏移与行长，Gallium 侧拆成 R8＋R8G8 两个平面，着色器里做 YCbCr→RGB。CoreAnimation 对 500 号格式的采样期待 RGB 还是 YCbCr 原值，要先看它的着色器确认（未核对）。
   - 备选：在 mediaplaybackd 里把解码输出改成 `'BGRA'`，让 VideoToolbox 做格式转换，合成器就能用。转换可能走 VideoToolbox 的 Metal 计算核，同样会碰到 YCbCr 纹理，风险未评估。
2. 调软件解码线程：`ThreadCountH264SWDecoder`、`com.apple.VideoProcessing` 的 `threading`／`max-threads`；看情况试 `cpus=7`。
3. VP9 软件解码：在 MobileSafari 里打开 WebKit 内部开关 `SWVPDecodersAlwaysEnabled`，确认 GPU 进程注册了 libwebrtc 的 VP9 解码器，webm 能出帧（依赖第 1 步）。
4. Iris 硬件解码：
   - 先取 K90 自己的 vpu35 固件。
   - 在内核里上电、加载固件、起 HFI，用一个命令行工具把 H.264 裸流解成 NV12 文件，验证固件、电源和 SMMU。这一步与 iOS 无关。
   - 再做 VideoToolbox 插件，注入 videocodecd 与 com.apple.WebKit.GPU。
5. AV1：Safari 只认硬件 AV1，等第 4 步；软件 AV1 收益低。

## 7. 来源

- 设备日志：`docs/progress/evidence/k90auto/kernel-12377-rate10-fp1/run/s070.log`（第 16470、16862、17024、17693 行）、`s111.log`（`ps`）、`cmd-reply-*.json`（命令序号 58 打开测试页、80 执行 `ps`，相隔 204 秒）；`kernel-12377-rate8-app2`、`kernel-12377-rate8-app3` 的 `s001.log`（plist 大小）。
- 共享缓存：VideoToolbox、H264SW.videocodec、VCPHEVC.videocodec、AVD.videodecoder、AV1SW.videodecoder、WebKit、WebCore、libwebrtc.dylib、SafariServices、MediaToolbox，地址见正文。
- 系统文件：`hackios-xnu-kernel/ios26/rootfs/System/Library/FeatureFlags/Domain/CoreMedia.plist`、`.../LaunchDaemons/com.apple.videocodecd.plist`、`com.apple.mediaplaybackd.plist`、`ios26/rootfs.slt`。
- 项目代码：`hackios-xnu-kernel/userland/src/annibaledrawable.m`、`annibalemetal.m`、`inject_media.c`、`userland/mkjobs.py`、`userland/build.sh`、`xnu/files/iokit/Kernel/MiniIOSurface.cpp`、`xnu/files/bsd/dev/adreno8_zap.c`、`adreno8_clock.c`、`adreno8_rpmh.c`、`mhi_pcie.c`。
- WebKit 主线源码（2026-11-05 取）：
  - [GPUProcess.cpp](https://github.com/WebKit/WebKit/blob/main/Source/WebKit/GPUProcess/GPUProcess.cpp)
  - [VP9UtilitiesCocoa.mm](https://github.com/WebKit/WebKit/blob/main/Source/WebCore/platform/graphics/cocoa/VP9UtilitiesCocoa.mm)
  - [AV1UtilitiesCocoa.mm](https://github.com/WebKit/WebKit/blob/main/Source/WebCore/platform/graphics/cocoa/AV1UtilitiesCocoa.mm)
  - [SystemBattery.mm](https://github.com/WebKit/WebKit/blob/main/Source/WebCore/platform/cocoa/SystemBattery.mm)
  - [UnifiedWebPreferences.yaml](https://github.com/WebKit/WebKit/blob/main/Source/WTF/Scripts/Preferences/UnifiedWebPreferences.yaml)
  - [WebPreferences.cpp](https://github.com/WebKit/WebKit/blob/main/Source/WebKit/UIProcess/WebPreferences.cpp)
  - [WebPreferencesCocoa.mm](https://github.com/WebKit/WebKit/blob/main/Source/WebKit/UIProcess/Cocoa/WebPreferencesCocoa.mm)
- Linux 主线（2026-11-05 取）：[iris 驱动目录](https://github.com/torvalds/linux/tree/master/drivers/media/platform/qcom/iris)、[sm8750.dtsi](https://github.com/torvalds/linux/blob/master/arch/arm64/boot/dts/qcom/sm8750.dtsi)、[videocc-sm8750.c](https://github.com/torvalds/linux/blob/master/drivers/clk/qcom/videocc-sm8750.c)、[SM8750 Iris 补丁 v3 封面信](https://www.spinics.net/lists/kernel/msg5832734.html)、[SM8750 Iris 设备树 v2](https://patchew.org/linux/20250806-b4-sm8750-iris-dts-v2-0-2ce197525eed@linaro.org/)。
- 第三方：[code002-2/sm8750-video-accel](https://github.com/code002-2/sm8750-video-accel)、[blu-sharky/piano-firmware PR #4](https://github.com/blu-sharky/piano-firmware/pull/4)、[Arch linux-firmware-qcom 文件列表](https://archlinux.org/packages/core/any/linux-firmware-qcom/files/)。
- Range 要求：[Apple Safari Web Content Guide「Creating Video」](https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/SafariWebContent/CreatingVideoforSafarioniPhone/CreatingVideoforSafarioniPhone.html)。
- CPU 估算依据：[emteria：树莓派 Android 视频解码](https://emteria.com/blog/raspberry-pi-android-video-decode-limits)、[dav1d 0.2.0 测评](https://medium.com/@ewoutterhoeven/dav1d-0-2-0-covering-all-pcs-including-mobile-eac3e43868c2)、[AV1 解码性能测评](https://medium.com/@ewoutterhoeven/av1-is-ready-for-prime-time-part-2-decoding-performance-d3428221313)。
