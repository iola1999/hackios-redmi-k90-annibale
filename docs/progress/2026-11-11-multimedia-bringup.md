# 音频播放、相机适配与视频硬解进展记录（2026-11-11）

本轮完成音频播放、相机适配、视频硬件解码与 YUV 合成以及背光／时钟收尾项的全链路代码落地、13 组宿主单测验证与内核／用户态产物构建。根因定位、静态反汇编依据与模块设计见[多媒体根因定位及架构设计](../analysis/2026-11-11-multimedia-root-causes-and-design.md)，前序事项见[11-10 架构审查跟进记录](2026-11-10-arch-review-execution.md)。

## 1. 首批落地变更概览

跨 `hackios-xnu-kernel`（提交 `7507f4c9`）、`hackios-xnu-userland`（提交 `023e088`）与顶层打包脚本 `tools/k90auto/package.py` 共完成四部分工作，所有新增与修改源码文件均控制在 1200 行以内。

- 共享基础设施、时钟与背光。新增互斥序列化的 `annibale_rpmh.h`／`annibale_rpmh.c` 统一服务音频、相机与 Iris VPU 的 CMD_DB 查询及 TCS 投票；`76-osfmk%arm%rtclock.c.patch` 修复 19.2 MHz QTimer 下 `absolutetime_to_microtime` 的微秒溢出；`MiniAppleARMBacklight.cpp` 优先响应用户滑块并在熄屏通知下保留持久化亮度；`09-bsd%kern%kern_exec.c.patch` 将 `exec_inject_conf` 扩容至 4096 字节。
- 音频播放链路。`init.c` 改为合成单插件目录挂载 `AnnibaleAudio.driver`，保留原厂 `AirPlayHalogen.driver` 等 10 个 HAL 插件可见以消除 `airplayd` 空指针崩溃；`mkjobs.py` 对照 `System/Library/FeatureFlags/Domain/*.plist` 求值条件键消除 `audiomxd` XPC 冲突；`annibale_audio_reach.c`、`annibale_adsp.c` 与 `annibale_audio_amp.c` 完成 4 槽异步 GPR 流水线、1 ms 活跃轮询及双路 NXP TFA9865／TFA9866 CoolPWM 功放寄存器初始化。
- 相机适配与系统级 Metal 发现。`MiniFramebufferUserClient.inc`、`annibalemetal_device.inc` 与 `package.py` 发布 `AnnibaleMetal.bundle` 并将默认 `featureProfile` 对齐至 `MTLGPUFamilyApple3`；`camera_device.c` 与 `camera_device_stream.inc` 补齐 `SoftISP = false`、`ModuleInfo`、`TuningParameters` 与 `FaceDetectionConfiguration`；`annibale_camera.c` 与 `annibale_camera_hw.inc` 补齐 SM8750 CAMSS 7 路电源、时钟、`apps_smmu` `SID 0x1c00` 幂等旁路及前后置 OV50E／OV20B 探测。
- 视频 YUV 合成与 Iris VPU v3.5 硬解。`annibaledrawable.m`、`annibalemetal_yuv.inc` 与 `air_metal_yuv.inc` 支持 10-bit P010（`x420`／`xf20`）、宏块对齐尺寸、用途位 `0x10` 与 BT.2020 矩阵；`annibale_iris*.c` 实现 `/dev/annibale-iris`（`videocc`、双 SMMU Stage-1、PAS `9` `vpu35_4v.mbn`、HFI Gen2 H.264／HEVC 解码与 B 帧时间戳排空）；`videotoolbox_iris.c` 构建为 `libannibale-vt.dylib`，按硬件就绪状态向 `VideoToolbox` 注册 `'avc1'`、`'hvc1'` 与 `'hev1'` 硬解器。

## 2. 首批编译打包与产物摘要

内核经 `xnu26/build-macos.sh` 编译链接并登记为 `12377-multimedia-1111`，用户态经 `build-air.py`、`COMPILE_ONLY=1 bash build.sh`、`package.py`（`GPU_SPEED=14`）与 `make-payload.py` 完成根盘与引导载荷组装。

| 产物 | 路径 | 字节数 | SHA-256 前 16 位 |
|---|---|---|---|
| XNU 12377 内核 | `hackios-xnu-kernel/out/xnu12377-multimedia-1111.bin` | `20,531,784` | `5764624396cd7e3a` |
| AIR 着色器动态库 | `hackios-xnu-userland/tools/mesa/air/libannibaleair.dylib` | 已重编并签名 | `1d14be1483eecfc5` |
| Metal 驱动动态库 | `out/ios26-resume/bbmetal-device` 内 `libannibalemetal.dylib` | 已重编并签名 | `45fc92eebd9059a3` |
| 辅助根盘镜像 | `hackios-xnu-kernel/out/ios26-resume/bbmetal-device/root.apfs` | `21,311,488` | `5787d7e80ea3a17a` |
| 引导载荷镜像 | `hackios-xnu-kernel/out/handoff-12377-multimedia-1111-preflight.bin` | `41,844,152` | `68367db3be002f80` |

## 3. 宿主回归单测结果

在宿主环境依次执行内核、引导程序、Metal／AIR 与用户态共 13 组单测，全部通过。

| 测试项 | 覆盖范围 | 结果 |
|---|---|---|
| `hackios-xnu-kernel/tools/tests/test-iris-safety.py` | `/dev/annibale-iris` 惰性初始化、4 类编译回归拦截、`videotoolbox_iris.c` 门控、Annex-B 转换与 B 帧排空 | 通过 |
| `hackios-xnu-kernel/tools/tests/test_challenger_m6_backlight.py` | 背光滑块 `1:1` 同步、熄屏亮度记忆与 5,000 次随机事件 | 通过 |
| `hackios-xnu-kernel/tools/tests/test-hw-drivers.py` | 背光映射与电池回差控制 | 通过 |
| `hackios-xnu-kernel/tools/tests/test-annibale-audio-transport.py` | GPR 响应校验、GLINK 锁与 PCM V2 完成计数、8 类回归拦截 | 通过 |
| `hackios-xnu-kernel/tools/tests/test-annibale-audio-intents.py` | GLINK RX intent 生命周期、容量与并发收包 | 通过 |
| `hackios-xnu-kernel/xnuloader/test_boot_safety.py` | `xnuloader` 槽位识别、命令边界与退回安全（13 项） | 通过 |
| `sb_metal_test_sequence`／`sb_metal_test_compression_preference` | 原生 `AnnibaleMetal.bundle` 发现、`featureProfile` 与未压缩 `IOSurface` 偏好（12+2 项） | 通过 |
| `hackios-xnu-userland/userland/test_mkjobs.py` | `#IfFeatureFlagEnabled`／`#IfFeatureFlagDisabled` 求值与 `MachServices` 过滤 | 通过 |
| `hackios-xnu-userland/tools/tests/test-audio-plugin.py` | `AnnibaleAudio.driver` CoreAudio HAL 接口契约 | 通过 |
| `hackios-xnu-userland/tools/tests/test-camera-device-ios26.py` | iOS 26 `CMCapture` 四阶段缓冲池、`ModuleInfo`、`TuningParameters` 与 `SoftISP` 属性契约 | 通过 |
| `hackios-xnu-userland/tools/tests/test-flash-root.py` | UFS 系统卷挂载、`AnnibaleAudio.driver` 单插件合成挂载与 7 种故障场景 | 通过 |
| `hackios-xnu-userland/tools/tests/test-video-decode-test.py` | `video_decode_test` 硬解要求门控、损坏样本与超时保护（10 项） | 通过 |
| `hackios-xnu-userland/tools/tests/test-video-player-test.py` | `video_player_test` 像素采样、播放结束判据与异常流处理（10 项） | 通过 |

## 4. 真机验证与剩余问题

mm1～mm4 出现启动 panic；mm5 采样约 408 秒，未捕获 panic，主动停止后恢复 loader 空闲态。音频提交与本地视频播放通过，扬声器实际出声待确认。Iris 硬件未就绪，相机仍输出软件测试帧；P010／BT.2020 与界面交互尚未验收。各轮结果、产物和接续检查见[多媒体验证结果](../analysis/2026-11-11-multimedia-validation.md)。
