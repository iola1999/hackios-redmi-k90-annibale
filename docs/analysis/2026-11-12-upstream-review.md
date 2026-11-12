# 上游与同类项目近期更新对照（2026-11-12）

本轮接续 [11-05 上游对照](2026-11-05-upstream-lessons.md)和 [11-06 HakiOS 对照](2026-11-06-upstream-2-3-4-analysis.md)，检查近期公开提交、分支、PR 与源码，并对照本项目当前实现。日期按北京时间记录；上游实测结果保留其设备、系统版本和验收边界。本轮只做静态核查，未运行上游脚本、构建或设备测试。

## 1. 核对范围

覆盖 HakiOS、UniXNU、Pagani 等同类移植，以及 Mesa 和 Mu-Silicium。各节保留核对版本、公开来源、本仓对应位置与适用限制；可选择的后续工作集中在[待办目录](../backlog/README.md)。

HakiOS 的近期开发主要发生在 `mtk` 分支。`main` 相对上次记录的 `2631f5d` 新增 4 笔提交，其中 2 笔为合并提交，实际修复为存档读取和设备树地址解析，见[提交对比](https://github.com/oosexgang/hakios-xnu-kernel/compare/2631f5d...63fc2b4633bac3af8e57dadab9f5a8d4cb940438)。

| 仓库与分支 | 本轮核对版本 | 最近提交日期 | 变化 |
|---|---|---|---|
| [hakios-xnu-kernel/main](https://github.com/oosexgang/hakios-xnu-kernel/tree/63fc2b4633bac3af8e57dadab9f5a8d4cb940438) | `63fc2b4` | 11-06 | 合入 PR #53、#54 |
| [hakios-xnu-kernel/mtk](https://github.com/oosexgang/hakios-xnu-kernel/tree/a962798418fa1ebaa06554a69955803860907c6b) | `a962798` | 11-11 | MediaTek 快照、相机、蓝牙、电量及全新环境构建验证 |
| [hakios-metal](https://github.com/oosexgang/hakios-metal/commit/d36f329e2684a1968b7c1a0ceee1661472cb707a) | `d36f329` | 11-05 | 宣布迁入内核仓库，之后没有新提交 |
| [hackios-xnu-userland](https://github.com/oosexgang/hackios-xnu-userland/commit/2573c4a8d80ed143e534d16b5a386efa5b06ccbb) | `2573c4a` | 10-26 | 宣布迁入内核仓库，之后没有新提交 |
| [hackios-web](https://github.com/oosexgang/hackios-web/commit/72a5a9a93a75a38005529f1f25c6f61a7c4d2418) | `72a5a9a` | 11-05 | 同步 2.3.4 文档及仓库迁移 |
| [hakios-sm7325](https://github.com/oosexgang/hakios-sm7325/commit/04fbfff933f52faf203a55aca9dd5680092e6ec5) | `04fbfff` | 10-28 | 本轮时间范围内没有新提交 |
| [hakios-uefi](https://github.com/oosexgang/hakios-uefi/commit/687fa6c6a5a70f43184de92980e0a76eea5f2c4b) | `687fa6c` | 10-28 | 默认分支没有新提交；PR #2 尚未合并 |
| [hakios-mt6768](https://github.com/oosexgang/hakios-mt6768/commit/ad65e1f4b3ba479e9d7ada98f17398b83cc6f285) | `ad65e1f` | 11-10 | 后摄预览、BLE 扫描和经典蓝牙连接至配对请求阶段 |

内核仓库最新 Release 仍为 10-22 的 [v0.1.0](https://github.com/oosexgang/hakios-xnu-kernel/releases/tag/v0.1.0)。本轮所述近期行为来自分支提交；独立 Metal、用户态仓库的迁移说明只更新代码所在位置。

## 2. HakiOS

### 2.1 相机 DMA 提交顺序与像素布局

11-08 的 [相机提交 `03383df`](https://github.com/oosexgang/hakios-mt6768/commit/03383dfbb281c0769f3c6793eea159cb8b5c5f98)报告 Infinix Hot 20（MT6768、iOS 16.5）后摄可在 Camera.app 显示实时预览，传感器输出为 4080×3072、约 14 fps。拍照保存、录像、自动对焦及其他摄像头尚未验收。

其[相机排查记录](https://github.com/oosexgang/hakios-mt6768/blob/03383dfbb281c0769f3c6793eea159cb8b5c5f98/docs/camera-x6826b.md)给出两项可借鉴的诊断结果：

- DMA 只写入头部、像素区保持为空，原因是按寄存器地址排序回放快照，提前写入 buffer-ready。按原厂 HAL 的顺序先写数据地址、头地址，再设置 ready，才收到完整数据。
- 持续缺少约 20% 图像高度，原因是把每像素 1 字节的 DMA 输出按 packed RAW10 的每像素 1.25 字节处理。实际 stride 改为 4080 后收到全部 3072 行；改变时钟和等待时间未解决此前的布局错误。

我方已读取传感器 ID，真实传感器流和 DMA 的验收范围见[多媒体验证结果](2026-11-11-multimedia-validation.md)。对应源码为 [annibale_camera.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_camera.c)及 [annibale_camera_hw.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_camera_hw.inc)。

最小验证可以在一轮中保留 CSID 帧边界、IFE 输出尺寸与 stride、DMA 地址及提交顺序、实际变化字节数和首尾行内容。这样可以分别判断传感器出流、接收器收帧、DMA 写入和图像解码是否通过。MTK 的寄存器、IOMMU 配置和帧完成判据需要按 SM8750 原厂驱动重新核对。

### 2.2 相机原生会话的检查顺序

上述提交的 [camera_device.c](https://github.com/oosexgang/hakios-mt6768/blob/03383dfbb281c0769f3c6793eea159cb8b5c5f98/userland/camera/camera_device.c)记录了 Camera.app 建图所需的条件：

- `tccd` 提供相机授权服务；上游缺少该服务期间，会话在请求流之前退出。
- `ModuleInfo` 与系统 CameraSetup 配置匹配，图构建过程中读取的 `VideoOutputsColorInfo` 等属性需要返回符合契约的值。
- 图调用 `Start` 并启用输出后才能交付帧；提前调用输出处理器曾触发 `mediaserverd` 崩溃。
- 每个输出使用图提供的 `BufferPool`，宽高和像素格式从池中的缓冲区读取。

我方 [camera_device.c](../../hackios-xnu-userland/userland/src/services/camera_device.c)已有 processing session、ModuleInfo、颜色信息与 iOS 26 的 `SensorRawOutputBufferPoolRequirements`；[camera_device_stream.inc](../../hackios-xnu-userland/userland/src/services/camera_device_stream.inc)使用图的 BufferPool，并按 `CAM_STREAM_ACTIVE` 控制交帧。参考价值集中在检查顺序，现有实现无需重复加入。

原生会话验证应记录建图、`RequestStreams`、`Start`、首帧回调和停止的结果，并保存首个失败属性及实际加载库版本。iOS 16.5 的类表槽位、传感器匹配值与 iOS 26 分别核对；当前反射、缓冲属性及传感器验证结果仍以[多媒体记录](2026-11-11-multimedia-validation.md)为准。

### 2.3 双槽存档按完整内容校验后恢复

11-06 合入的 [PR #54](https://github.com/oosexgang/hakios-xnu-kernel/pull/54)包含[提交 `04aad08`](https://github.com/oosexgang/hakios-xnu-kernel/commit/04aad08c8e2f86ee97599490cd0b740b55715274)，修正主机端 `var-store-read.py` 的槽位选择：按代次从新到旧读取并校验完整内容 CRC，内容损坏或截断才尝试旧槽，底层读错误继续返回。测试覆盖空存档、相同代次、两个槽都损坏及旧实现失败对照。

我方 [ramfs_disk_mount.inc](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_disk_mount.inc)已按代次检查元数据槽；读取或解包失败后清理部分恢复的数据，仅 `EINVAL` 允许继续尝试旧槽。[恢复测试](../../hackios-xnu-kernel/tools/tests/test-ramfs-disk-recovery.py)已有旧槽恢复场景。

可借鉴的检查是核对主机读取器与内核恢复规则是否一致，覆盖内容 CRC 损坏、截断、底层读错误和合法空存档。上游使用完整存档槽；我方 `ANNFS001` 的元数据槽与数据块分开存放。该修复无法解决数据页原位覆盖或释放块立即复用的问题，这部分分析见[系统契约核查](2026-11-12-system-contracts.md)。

### 2.4 设备树地址与参数位宽

11-06 合入的 [PR #53](https://github.com/oosexgang/hakios-xnu-kernel/pull/53)包含[提交 `2423430`](https://github.com/oosexgang/hakios-xnu-kernel/commit/2423430572f8e9e41d33de16917840678c3632dd)，将 `soc-args.py` 改为按直接父节点的 `#address-cells` 和 `#size-cells` 解析 `reg`。原实现遇到 2+2 布局会生成零 IPCC／AOSS 地址并成功退出。

新实现支持 1／2 个地址 cell 和 0／1／2 个长度 cell，检查不完整 tuple 与消费者字段溢出。该提交只用合成 DTB 验证，未实现 `ranges` 地址转换，也未验证真实设备树。

本项目未跟踪该生成器。后续从设备树提取 CAMSS、SMMU 或 IPA 配置时，可以采用同类合成输入，分别核对地址、tuple 步长和内核参数位宽，再用本机 DTB 与原厂驱动定义对照。涉及总线地址转换的节点需要单独处理 `ranges`。

### 2.5 全新环境构建与发布验证

北京时间 11-11 的[提交 `a962798`](https://github.com/oosexgang/hakios-xnu-kernel/commit/a962798418fa1ebaa06554a69955803860907c6b)记录了一次从空目录 clone 到桌面的构建验证，环境为 Intel Mac、macOS 14.0、Command Line Tools 15.3，无 Homebrew。具体步骤和边界见[构建记录](https://github.com/oosexgang/hakios-xnu-kernel/blob/a962798418fa1ebaa06554a69955803860907c6b/docs/from-a-clone.md)。

这次验证发现并修复 SDK 链接树不完整、宿主 xcrun 未指定 SDK、链接器来源未声明、`7zz` 命名以及 GNU 命令依赖。上游完成内核、loader、iOS 提取、系统盘和 CPU 绘制桌面验证；Mesa、Linux 构建和相机等外设未覆盖。

我方 [mac-env.sh](../../tools/mac-env.sh)明确配置 Homebrew coreutils，[用户态构建脚本](../../hackios-xnu-userland/userland/build.sh)仍使用 `cp -al`、`stat -c`，这些属于当前构建环境约定。可借鉴的方法是用干净 checkout、明确的依赖清单和隔离输出目录执行[开发指南](../development.md)，核对未跟踪固件、SDK 和历史构建产物是否影响重建。现有 iOS 26／arm64e 工具链要求保持原有依据。

### 2.6 蓝牙名称与扫描条件

11-10 的[提交 `ad65e1f`](https://github.com/oosexgang/hakios-mt6768/commit/ad65e1f4b3ba479e9d7ada98f17398b83cc6f285)报告 BLE 扫描、Settings 发现设备及经典蓝牙连接至 `User_Confirmation_Request`。配对完成、密钥重连、A2DP／HFP／HID 和 LE GATT 尚未验证。

其[蓝牙记录](https://github.com/oosexgang/hakios-mt6768/blob/ad65e1f4b3ba479e9d7ada98f17398b83cc6f285/docs/bluetooth-x6826b.md)指出 Settings 名称来自 `SCDynamicStoreCopyComputerName`。上游等待 `configd` 创建 `CurrentSet` 后才调用 `SCPreferencesSetComputerName`、commit、apply，防止只有名称的文件提前被读取为系统网络配置。

我方 [AnnibaleBT.cpp](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/AnnibaleBT.cpp)已发布 `bluetooth` 服务与 `local-mac-address`；本轮扫描的用户态源码未找到对应系统名称设置调用。最小核查可以只读比较 `CurrentSet`、系统名称、HCI `Write_Local_Name` 和设置页显示。

上游还发现无应用 bundle 的命令行扫描程序会得到未知前台状态，扫描过滤条件与应用不同。可用实际 App 和命令行程序对照观察 `BKSApplicationStateMonitor`、服务过滤条件及广告报告交付；上游强制前台状态和修改扫描类型的钩子只说明其测试前提，不能用于验收本项目的原生扫描行为。

### 2.7 其他更新与旧建议边界

- [PR #57](https://github.com/oosexgang/hakios-xnu-kernel/pull/57)新增 ARMv8.0、GIC 安全组和虚拟定时器自检相关适配，尚未合并；可供扩展机型参考，K90 当前没有直接采用需求。
- [UEFI PR #2](https://github.com/oosexgang/hakios-uefi/pull/2)处理 Android boot header v4 下的载荷查找，尚未合并；K90 的独立 loader 构建与启动范围见[UEFI 与 loader 构建](annibale-uefi-build.md)。
- [SM8735 Issue #59](https://github.com/oosexgang/hakios-xnu-kernel/issues/59)仍停在 USB／RPMh 初始化失败，报告中的成功范围为固件与 loader 输出，USB 枚举和内核启动尚未通过。
- 旧对照建议按下期间每 4 ms 无条件轮询触摸；当前 [annibale_goodix.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_goodix.c)按中断或 16 ms 周期读取。采用旧建议前需要核对当前触摸协议与此前调整原因。

## 3. UniXNU

### 3.1 蓝牙会话与音频

[QcaBluetooth](https://github.com/UniXNU/QcaBluetooth/blob/986d6319d1d2819b27ed2c9786776f10bf63cc76/README.md)记录 sheng、iPadOS 27.0.1 上配对 AirPods Pro、重启重连、A2DP、电量和降噪控制通过。HFP／SCO、系统休眠与空闲耗电未验收。这组真机结果来自组件拆分前版本，最新子模块组合仍待复核。

11-06 的 [`1212d2a`](https://github.com/UniXNU/QcaBluetooth/commit/1212d2afd8994bb71d8ccb3d44aaa8417b910b89)处理旧会话延迟销毁：bluetoothd 先关闭控制 socket，Skywalk channel 稍后销毁，可能晚于新会话建立。修复将 closing 绑定到所属 nexus，清理 rings，并在 busy 归零后唤醒等待者。

本仓 `annibale_bt_ios.c` 的 `btsk_pre_disconnect()`／`btsk_disconnected()` 忽略 nexus 参数，直接修改全局 `btsk_up` 和 `btsk_rx_pp`。目前只确认了结构差异；最小验证为旧会话断开、新会话连接、旧 channel 延迟销毁，再检查新会话收发和连续开关蓝牙。

11-11 的 [`986d631`](https://github.com/UniXNU/QcaBluetooth/commit/986d6319d1d2819b27ed2c9786776f10bf63cc76)处理 IBS wake 与 UART 关钟的时序：控制字节重新申请时钟，暂时拒绝发送后按间隔重试，已有宿主验证。[`ab043e6`](https://github.com/UniXNU/UniXNU-sheng/commit/ab043e668f)将 `BTAudioHALPlugin.driver` 加入覆盖后的 HAL 目录。两项分别适合后续低功耗时序测试和系统盘插件可见性检查。

### 3.2 原生 USB

11-06 的 [`f0d190d`](https://github.com/UniXNU/QcomDwc3/commit/f0d190d3d568cebcc32ee6ff339e164dc2b196db)增加 `QcomDwc3Xdci : AppleUSBXDCI` 与 `QcomDwc3Xhci : AppleUSBXHCI`，为原生 USB 栈提供寄存器、中断、电源、PHY 和角色切换。

[固定版本验证记录](https://github.com/UniXNU/QcomDwc3/blob/0dd83827279ee070dca7ddb486c90365567cc99d/README.md)报告 USB 3 线 10 Gbps、USB 2 线 480 Mbps 枚举、重新枚举、信任弹窗、Mac 配对和 lockdown 服务启动通过。持续传输、安装应用、USB 3 反向插线尚未验收；host 模式只确认 xHCI 命令完成。

AppleUSBXDCI 本身不做缓存维护，上游为 USB stream 配置独立 SMMU context 和 write-back inner-shareable 映射。角色切换先停止旧栈、复位 core，再配置新角色。本仓 USB 由 loader 使用，实施前需要确定控制器交接及恢复条件，再逐项核对 SM8750 的 stream、PHY、时钟、中断和 23G90 私有 ABI。PHY 文件的 GPL-2.0-only 与其他文件的许可证分别核对。

### 3.3 UFS 完成等待与缓存同步

11-09 的 [`fd420df`](https://github.com/UniXNU/ShengUfs/commit/fd420df000f43213d9cd019725abff0849c98c72)加入 32 槽、IRQ 完成、页对齐 PRDT 直接 DMA 和 panic 保留槽；11-11 的 [`34ff541`](https://github.com/UniXNU/ShengUfs/commit/34ff541dec)调整短时轮询与 IRQ 等待。最新组合完成宿主测试和目标编译，尚未真机验收。

本仓已有 32 项列表及最多 31 个业务槽，也有短轮询和后台 poller。可比较命令完成、线程恢复、slot 等待、最老在途请求与 bounce copy 开销；宿主验证应覆盖逆序完成、BUSY／TASK SET FULL、超时后资源保留和 panic 保留槽。

[RootCommands.h](https://github.com/UniXNU/ShengUfs/blob/57f031c99d7f69ffa611626bebaeab0731e93254/RootCommands.h#L553)已有 `hostWrite4k(..., fua)` 和 `hostSyncCache()`，分别设置 WRITE(10) FUA 位和发送 SYNCHRONIZE CACHE(10)。这是本轮新核对的既有实现。本仓 `annibale_ufshc_rw.inc` 白名单自检拒绝 `0x35`，可据此核查 `F_FULLFSYNC` 与设备写缓存契约。ANNFS 数据页覆盖和释放块复用另见[系统契约核查](2026-11-12-system-contracts.md)。

### 3.4 显示颜色、绘制范围与 GPU 进度

| 来源 | 新增观测或修复 | 本仓可用方式与边界 |
|---|---|---|
| [GopFramebuffer `d711e8c`](https://github.com/UniXNU/GopFramebuffer/commit/d711e8c9de) | half-float 中心像素原始值采样 | 用已知灰阶分别检查线性值与编码值，核对 IOSurface、Metal 输出及 scanout |
| [GopFramebuffer `b0d812d`](https://github.com/UniXNU/GopFramebuffer/commit/b0d812d578efa2acb005b66f73168891719af09a) | 呈现格式及 CPU／GPU／DPU 路径计数 | 区分格式拒绝、转换和最终呈现路径，服务 XR 与缩放排查 |
| [AdrenoMetal `54ac1a0`](https://github.com/UniXNU/AdrenoMetal/commit/54ac1a006d274a9b8ca66b13d1db2f5d09e92900) | 大 pass 的 attachment 面积、scissor 包围矩形和空 pass 统计 | 本仓已有局部重绘；继续区分局部 draw 与全屏转换，scissor 面积只给绘制范围上界 |
| [Adreno740 `9578923`](https://github.com/UniXNU/Adreno740/commit/95789237473c8bc72be86f2bb4166b11ad0f0f20) | CP 仍有进度的长作业重新开始无进度计时 | 作者记录两轮未挂起；本仓 HWSCHED 与其 ring 恢复路径不同，先参考诊断判据 |
| [Adreno740 `2a91aa1`](https://github.com/UniXNU/Adreno740/commit/2a91aa1a14a33e970aa73795274ff361caefbd71) | BR 等待 BV 期间同时观察 BV 指针、IB 与剩余字数 | 核对 A830 hang dump 是否覆盖 BR／BV／LPAC／GMU，分别测试部分单元前进和全部停止 |

[调频修复 `abfc15a`](https://github.com/UniXNU/UniXNU-sheng/commit/abfc15a6e0)发现 busy counter 的微小非零值会使 idle 判据持续失败。其新阈值尚无帧时收益结论，K90 需要先核对自身 governor 输入、空闲噪声和实际频率。

### 3.5 双平面视频与渲染策略

11-11 的 [`7841a9f`](https://github.com/UniXNU/AdrenoMetal/commit/7841a9fc3dadecdf5ded4231042613b5de3f6529)为 NV12／P010 双平面 IOSurface 增加直接采样，在限定 ShaderRead 场景下减少 RGBA16F 中间图像，其他 binding 按需物化。宿主测试覆盖像素一致性、物化和在途 surface 引用，尚未真机验证。

本仓已实现双平面组合采样，NV12／P010 12 组 GPU 色值检查通过，见[多媒体验证结果 §19](2026-11-11-multimedia-validation.md#19-正常频率下的独立功能验证)。可补奇数宽高、不同 plane stride、原始 IOSurface 释放后命令仍在途的检查。

最新 [AdrenoMetal 渲染策略 `9ddfaf2`](https://github.com/UniXNU/AdrenoMetal/commit/9ddfaf2327)按 pass 选择 GMEM／sysmem，已取代此前全 pass 强制 GMEM 的设置。该实现使用 Turnip，本仓使用 gallium；现有结果适合参考统计维度，尚不足以支持更换图形后端。

## 4. 同 SoC 与其他移植

### 4.1 Pagani 的 USB 与文件身份

IssacL04 的 SM8750 移植在 11-07 至 11-08 更新了原生 USB、SMMU 与虚表绑定。[DMA 修复](https://github.com/IssacL04/UniXNU-Pagani_SM8750/commit/278fb682a10d924dcd44647b01fb964690ade697)按实际 SMMU IDR 使用 36-bit 地址；[重复 SID 修复](https://github.com/IssacL04/UniXNU-Pagani_SM8750/commit/976f6a011c7c39800dc538b0f83f541b640d72a5)在停止控制器后只处理同一 stream 的精确重复项；[ABI 修复](https://github.com/IssacL04/UniXNU-Pagani_SM8750/commit/afe9e05e9976ae93d95ddafa8b0486876638cce0)逐项核验 21H461 的 267 个虚表槽和实例布局。

[实机记录](https://github.com/IssacL04/UniXNU-Pagani_SM8750/blob/a84204eccb9b183945072e1b9b63de36c8495097/STAGE6.md)确认 Windows 上 USB 2.0 枚举、configuration 1、USBMux 激活和连接 62078；lockdownd 查询与 Trust 尚未通过。源码新改动包含在设备仓 `.ci-inputs/` 的 v33 包内，单看组件仓日期会漏掉这些内容。K90 首轮仍需验证交出控制器、原生枚举和归还 loader。

同项目的 [`e5a3d1f`](https://github.com/IssacL04/UniXNU-Pagani_SM8750/commit/e5a3d1f92c46c2503e7e80b45582ed57df195348)单独修改 union SystemOS 的 `statfs.f_fsid`，`getattrlist`／`fsgetpath` 保留原映射。该轮出现应用加载崩溃，随后在 [`a84204e`](https://github.com/IssacL04/UniXNU-Pagani_SM8750/commit/a84204eccb9b183945072e1b9b63de36c8495097)撤回；修复后的真机恢复待验。

本仓 ramfs 与 APFS 的静态检查未发现同一处替换。可对 System、Data、Cryptex 和应用 bundle 执行 `statfs → getattrlist → fsgetpath → stat`，检查往返对象及重启后的文件引用。后续已准备只读往返工具，并发现本仓 APFS 同设备多容器的查找歧义条件，宿主与目标构建结果见[系统契约 §6](2026-11-12-system-contracts.md#6-应用前台切换)。当前资料没有确定本仓应用前台切换失败的原因。

### 4.2 显示关闭、固件失败与调频

- [Pagani 显示关闭](https://github.com/IssacL04/UniXNU-Pagani_SM8750/commit/38ba795cf49fff3adc253d9e7d405debf3cbdc99)同时停止诊断绘制，报告灭屏全黑、亮屏恢复；没有系统休眠和功耗结论。本仓 `kFBMethodRequestPowerChange` 直接返回成功，需要先核对 23G90 selector 参数及所有 framebuffer 写入者。
- [Pagani Wi-Fi 后续](https://github.com/IssacL04/UniXNU-Pagani_SM8750/commit/a84204eccb9b183945072e1b9b63de36c8495097)保留首次失败，阻止重复 `FW_READY` 和迟到 `CAL_DONE` 清除失败状态，并区分校准分配容量和已下载长度。新候选仍待真机，尚未联网；可为本仓 Wi-Fi／Iris／ADSP 提供异步失败测试场景。
- [Pagani A830 调频](https://github.com/IssacL04/UniXNU-Pagani_SM8750/commit/58cddb1b785b7215ab7b8b37a8f72b98695165bd)加入逐档温控、触摸与唤醒提升，最高 734 MHz，持续负载未量化。本仓已有最高 1100 MHz、触摸提升与温控，板型阈值需要独立来源。

### 4.3 无新增与承接项目

| 项目 | 核对结果 |
|---|---|
| [superboyyy/hakios-arm64e-dada](https://github.com/superboyyy/hakios-arm64e-dada) | `f1ae906`，10-31 后没有新提交 |
| [Typeun/myron-device](https://github.com/Typeun/myron-device) | `d9b6be4`，11-01 后没有新提交 |
| [Shad0w23333/UniXNU-OnePlus13T](https://github.com/Shad0w23333/UniXNU-OnePlus13T) 及设备、Adreno830、Drivers、common、构建器组件 | 相关源码停在 11-05 凌晨，未发现新增真机验收 |
| [ShueiTsuki/data-a-live](https://github.com/ShueiTsuki/data-a-live) | 已归档，最后 `d2c7089` 为支持入口调整 |
| [yechenan/data-a-live](https://github.com/yechenan/data-a-live/commit/a437318cd6ec8aca85a4cad6c3c26281be4fbfd0) | 11-11 调整 xnu-8796 的 IORPC.h 以兼容 Xcode 26 iig；本仓 XNU 12377 暂无对应采用需求 |
| [code002-2/sm8750-video-accel](https://github.com/code002-2/sm8750-video-accel) | 最近推送为 10-09，本轮窗口没有新增提交 |

## 5. Mesa

官方发布说明已列出 [26.3.0](https://gitlab.freedesktop.org/mesa/mesa/-/blob/mesa-26.3.0/docs/relnotes/26.3.0.rst)与 [26.2.7](https://gitlab.freedesktop.org/mesa/mesa/-/blob/mesa-26.2.7/docs/relnotes/26.2.7.rst)。本仓使用 26.2.5 加移植补丁，本轮核对了 `build-air.py` 指向的实际展开源码。

| 提交 | 行为与适用范围 | 本仓核对与最小验证 |
|---|---|---|
| [alias.rt `8511f446`](https://gitlab.freedesktop.org/mesa/mesa/-/commit/8511f446715cc79ccd72bbd1c26471135d774dea) | 相对常量不能用 alias.rt 表达，旧实现可能读成 c0.x；已回移 26.2.7 | 实际 ir3_alias.c 仍缺相对寻址排除，A830 启用 has_alias_rt；用动态常量索引输出颜色做原生 Metal／A830 对照 |
| [fsat `5a9db0be`](https://gitlab.freedesktop.org/mesa/mesa/-/commit/5a9db0be64e090164930593c6cd13d08ad45123f) | 只对 cat2／cat3 浮点指令合并浮点饱和，旧判断可能允许整数或位运算 | 本仓 is_sat_compatible 仍为旧实现；用整数／位运算结果参与浮点 clamp 的最小 shader 对照 |
| [A8xx 描述符 `2d2b3a98`](https://gitlab.freedesktop.org/mesa/mesa/-/commit/2d2b3a986e870b5dc59a4ec03165e25a37eec6f0) | DESC_BUFFER 使用 32-bit NUM_ELEMENTS，修复大缓冲元素计数回绕；已回移 26.2.7 | 本仓 fd6_view.cc 仍拆成 WIDTH／HEIGHT；针对容量边界测试，当前桌面故障未确认触发该条件 |
| [布尔 subgroup `9b0a38ca`](https://gitlab.freedesktop.org/mesa/mesa/-/commit/9b0a38cabb83e9f82c2f831123064720200b1a36) | 非活动源 lane 可能保留旧寄存器值，shuffle／broadcast 后将布尔结果归一到 0／1 | 本仓有 simd_shuffle 映射；确认目标 AIR 生成 1-bit NIR 后再构造部分活跃 subgroup 测试 |
| [fquantize2f16 `d520ae90`](https://gitlab.freedesktop.org/mesa/mesa/-/commit/d520ae902ede90f4e3bc44bf3871030896971647) | gen8 开启专门 lowering 处理 FP16 subnormal | 先核对 AIR 是否生成该 NIR 操作及原生数值要求，再做数值边界检查 |
| [NV12 尺寸 `988037f5`](https://gitlab.freedesktop.org/mesa/mesa/-/commit/988037f55378f077e9129b3df17729ea16337fd5) | 单 BO NV12 的 UV 尺寸按奇数宽高向上取整，保持 UBWC 布局一致 | 本仓双平面包装已向上取整；该上游资源路径是否使用需另查，可补奇数尺寸测试 |

上述修复提供具体复现条件，目前未确认它们与 K90 组件白块、蓝块或材质颜色异常同因。版本升级需同时验证 OSMesa 恢复、Darwin DRM 和已有 A830 补丁；逐项回移与整体升级的维护成本另见[工程待办](../backlog/engineering.md)。

## 6. Mu-Silicium 与启动边界

11-08 的 [`44f6c98`](https://github.com/Project-Silicium/Mu-Silicium/commit/44f6c98f76d7e9c0b8458461ce9d5b8b0985f1fc)注册 `ExitBootServices` 回调，调用 `ScmExitBootServicesHandler()`，提交说明称其用于修复操作系统侧 TZ 驱动问题。本仓 Mu-Silicium 对应 `PlatformBootManager.c` 尚无该调用。

需要先确认 K90 实际启动是否经过这个阶段、SCM protocol 是否提供相同方法，以及哪些硬件状态会被改变，再评估与 ADSP／Iris 初始化的关系。当前资料没有确定 HFI fatal 的原因，也未完成 K90 构建或真机验证。

## 7. 任务入口与核对边界

后续选择和执行状态统一放在[待办与候选](../backlog/README.md)。本轮新增参考分别关联[系统](../backlog/system.md)、[图形与显示](../backlog/graphics.md)、[多媒体](../backlog/multimedia.md)、[外设与电源](../backlog/platform.md)及[工程维护](../backlog/engineering.md)。

UniXNU 还核对了 ArmCpu、ArmDTPlatform、DarwinBoot、ShengHidInput、AppleKeyStoreState、Ath12kWifi 的近期提交；QcomBaseband、ArmSmmu4K、VerifiedRoot 的默认分支在本窗口没有新提交。设备目录已有 339 条记录，包含同机不同作者副本，未发现普通 K90／annibale；主仓最近 30 项 PR 已查看，未逐项审查全部开放 PR。

本轮来源为官方仓库的提交、源码、说明与公开实测记录。后续实施需要按当前源码、加载产物和设备结果重新确认适用条件；不同 SoC、系统版本及图形后端的结果各自保留范围。
