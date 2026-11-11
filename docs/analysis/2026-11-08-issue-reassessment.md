# 历次反馈与验收状态复核

本次复核读取了用户指定的 Anti Gravity 会话中的 32 条用户消息，并对照 [11-06 问题清单](../plan/2026-11-06-issues-and-followup.md)、当前源码和保留的运行日志。原始消息和日志保存在 Git 忽略的本地目录。本文保留该次用户反馈、分析与验收条件，后续事项统一维护在[待办入口](../backlog/README.md)。

具体事项按[系统](../backlog/system.md)、[图形](../backlog/graphics.md)、[多媒体](../backlog/multimedia.md)、[外设与电源](../backlog/platform.md)及[工程](../backlog/engineering.md)分类；下表状态对应原分析轮次，当前批次结果由各主题链接维护。

## 1. 目标与完成条件

修复桌面卡顿、大组件黑底、壁纸与玻璃效果异常、苹果服务请求失败、音频无声和视频播放失败，同时复核下表中的其他历次反馈。系统卷从 UFS 按需读取，文件变更经内核写入 `darwin_var`；正常启动保留锁屏，无人值守测试按运行参数自动解锁。

先用日志、源码和系统框架反汇编确认底层契约，再修改内核、驱动或构建过程。每项记录触发操作、实际失败、修复与测试范围。可重复的离线检查覆盖错误处理和数据布局，真机检查覆盖实际服务、画面、硬件和重启读回；编译成功只确认产物可以生成。

提交和推送以同一批定稿的修改及验证为单位。设备操作由指定成员串行执行，起轮和收尾检查按[排查手册](../plan/debugging-and-collaboration.md)与[设备测试手册](../plan/device-test-playbook.md)执行。每批至多三轮，读完结果并调整测试后再开始下一批。依赖外部设备或听感的项目记录人工验收边界。

## 2. 全部反馈与验收条件

| 范围 | 用户反馈或要求 | 当前可确认的状态 | 验收条件 |
|---|---|---|---|
| 系统卷与内存 | 整个系统镜像占用约 5 GiB 内存不可接受 | 新版已刷入 `boot_a` 并重启完成 UFS 切根，启动卷常驻 4 MiB，内存采样见[根文件系统](rootfs-strategy.md) | 当前启动路径已通过；后续构建继续核对产物身份与常驻长度 |
| 完整系统文件 | 使用完整系统卷 | 16 GiB 系统分区中的原版三容器共约 14.002 GiB，写入、全范围读回、GPT 和持久启动已通过；完整 boot 读回哈希一致 | 系统部署已通过；继续检查原生应用内容请求 |
| 数据持久化 | 文件直接落盘；输入法、Wi-Fi、语言和桌面位置跨重启保留 | 当前常用镜像正常重启后恢复 UFS 数据盘，110 字节测试文件的摘要保持一致；设置与异常复位仍待逐项验证 | 写入与同步后正常重启读回文件及设置；单独检查异常复位恢复 |
| 开机交互 | 图标约一分钟才出现，期间不能点击；卡在苹果 Logo | 曾出现多种回归，最后反馈未逐项复核 | 记录首帧、图标完整与首次响应时刻，检查关键进程启动、退出和主线程等待 |
| 大组件与图形 | 天气、日历大组件黑底，滑动或控制中心切换后黑白变化；刚解锁并上滑封面时两个组件颜色正常，进入桌面后才变黑；壁纸和玻璃效果曾消失 | dense 轮已捕获 Calendar 从 RGB 234 到 RGB 0 的完整 draw 切换，并关联到 `TmuaBscnA2Xhfsn_IsrcN3Oc3mtc4nlnlnl_Isqr`，目标 AIR 待取 | 关联首个异常 draw 的实际特化 fragment、完整 AIR 和 pre/out 像素，再检查对应底层契约；修复后连续截图复核组件与系统界面 |
| 流畅度与功耗 | 翻页、切应用卡顿，静置发热，拖图标跨页断触 | 五轮同轨迹温控 A/B 显示完整内核回退将首次 swap 中位数从 72.35 ms 降到 30.35 ms；单独替换为 `01cf` 前内核未复现该改善，固定翻页等效帧率为 72.73，当前尚未形成生产修复，见[11-08 性能回退](../progress/2026-11-08-performance-regression.md) | 拆分 `990b6fcc..4fa0d162` 的内核改动，保留 Metal/AIR 像素正确性；补测面板显示与设置内容完整加载时刻，并检查静置 CPU/GPU 占用、温度和持续刷新 |
| 亮度 | 进入设置子页明暗变化；滑块大部分区间无法调暗 | 旧修复后用户仍报告异常 | 固定滑块进出同一页面，核对 CoreBrightness 属性、目标亮度与面板 DCS 回读；覆盖滑块全范围 |
| 苹果服务与浏览器 | Weather、Maps 无内容；Safari 曾无法联网，打开 Apple 页面后桌面重启 | 本轮 DNS 与普通 HTTPS 成功；Weather 仍无温度、Maps 地图区空白，原生日志记录服务查找失败 | 分别记录天气详情、地图瓦片和 Safari 请求的 DNS、路由、TLS、HTTP/XPC 结果及内容；复核相关进程崩溃 |
| Wi-Fi | 首次加入报错后后台连接；保存网络丢失；要求构建指南写清驱动接入；状态栏 Wi-Fi 图标从中午起持续灰色，设置页显示满格 | 状态栏依赖 LQM 事件生成 `SCALED_RSSI`，设置页可读取扫描结果的真实 RSSI；驱动缺少 `EVENT_LQM_CHANGED(39)` 的缺口已补齐并通过生产函数测试，单变量真机候选正在隔离，见[LQM39 修复与边界](../progress/2026-11-08-wifi-lqm39.md) | 确认事件到达 `wifid` 和 SpringBoard，核对状态栏、设置页和实际 RSSI；若仍灰显，单独检查 `isPrimaryInterface` 与 `isFallingBackToCellular`；新网络首次加入和已存网络重启重连继续验收 |
| 系统时间 | 比实际慢 41 分钟；要求使用底层时钟 | 当前代码和日志使用 PMK8550 秒计数及 Android `persist /time/ats_*` 偏移 | 记录启动时间源，重启后与参考时钟比较，检查网络校时结果 |
| 音频与麦克风 | Spotify 和网页显示播放但扬声器无声；音量滑块效果不明；要求录音 | AudioQueue 启动成功，PCM 完成通知达到 sent/done 4100/4100；预热后的原生 Bunny 完整播放通过，冷启动直接播放在约 18.5 秒进入 waiting，Safari 仍报媒体错误 3；实际听感未验证 | 记录冷启动与播放中等待的缓冲和会话状态，恢复 Safari 触发的 CoreMedia XPC 超时参数；检查功放和录音数据，扬声器与麦克风结果留人工复核 |
| 视频 | 网页 H.264/VP9 播不了，硬解不可用 | 真机原生 H.264 软解的 12 帧像素均与独立解码一致；强制硬解在 VT 创建返回 `-12906`，Iris HFI 与 VideoToolbox ABI 仍需实现 | 软件画面呈现与网页播放继续验证；硬件解码需真实固件会话、完成响应和正确像素 |
| 充电与电量 | 拔线仍显示充电；原装快充在 iOS 下不能充入；电脑 USB 下状态曾错误 | 用户确认过电脑供电时电量从 68% 增至 69%，其他条件未完成验收 | 分别记录插线、拔线、电脑与充电器场景的在线状态、VBUS、电流、温度和电量变化；外部换线需人工配合 |
| 蓝牙与 AirDrop | 设置与控制中心状态不一致；切所有人无效；后来显示所有人但其他 iPhone 看不到 | 接收模式显示和实际发现/传输须分别检查 | 核对 HCI、BLE、AWDL、sharingd 和配对状态；耳机路由、另一台设备发现及文件传输需外部设备配合 |
| 相机 | 预览黑屏，切视频闪退；要求合并外设实现 | 枚举格式成功记录仍缺真实传感器图像验证 | 核对传感器、CCI/CSIPHY/IFE、帧到达和像素变化；相机预览及切换录像不退出 |
| 手电、触感、传感器 | 手电、震动、环境光、接近传感器均需检查 | 早期结果不能覆盖当前镜像 | 检查真实设备配置、回读和数据变化；亮灭、触感及遮挡/光照刺激需人工或外部设备 |
| 语言、字体、通知 | 中文设置下应用名称变英文；网页字符方框；日历反复询问通知权限 | 旧文档列有修复，缺当前镜像逐项复核 | 检查中文名称、目标网页字体、通知授权读写及重启保留 |
| 应用安装与文件 | 主屏无法彻底卸载；要求预装应用安装器、清理测试应用、安装 LiveContainer+SideStore；Safari 下载完成后仍显示「下载中」，下载文件需能移入文件 App | `TrollStore.app` 已在 `/annibale/Applications`，由 `trollstorehelper register-system` 装进 `MCMAppContainer` 并注册到 LaunchServices | 核对 `trollstorehelper open com.opa334.TrollStore`、TrollStore 界面和主屏图标。覆盖安装、启动、主屏删除、容器清理、重启保留，以及 Safari 下载完成状态、文件落盘和分享安装 |
| 引导、关机与复位 | 多次进入 Android；苹果 Logo 长时间停留；滑动关机黑屏后看门狗复位；要求 SOP 记录原因 | 本轮确认旧 loader 报错 idle 与恢复命令清除资源状态的问题 | 检查槽位和 GUID，实际进入目标系统；正常关机走电源关闭路径；故障后保留真实状态和日志 |
| 手动与自动解锁 | 手动开机停在锁屏，无人值守才自动解锁 | 用户确认过手动锁屏行为与解锁体验 | 分别核对独立启动和自动跑轮的参数与结果 |
| 蜂窝与 App Store | 要求蜂窝网络、短信、电话及 App Store | 尚未完成端到端验证 | 检查真实基带状态；注册网络、通话和登录下载依赖 SIM、网络及登录凭据，单独记录边界 |

## 3. 本轮已确认的实现问题

### 3.1 存储与 loader

整盘常驻和数据持久化是两个独立路径。本轮已正常停止旧内核、清理完整系统镜像，并从 LK 临时启动小型启动卷加 UFS 切根的新镜像；真机锁屏与旧数据恢复已确认。`darwin_var` 直写和 UFS 切根的提交、大小与验证见[根文件系统](rootfs-strategy.md)。

旧 `oem recovery` 在内核仍运行或资源未释放时清除占用标志，并回报 idle；启动失败返回也调用相同代码。修复后该命令只在资源可用时取消启动菜单，故障返回保留结果与资源状态。生产函数测试覆盖 16 组占用状态，主机脚本接受 `idle` 和 `idle 0 0`，拒绝带非零字段或多余字段的 idle 回答。

数据卷卸载原来忽略最后一次元数据同步错误，仍释放缓冲区和挂载引用。修复沿原调用路径返回错误，保留重试所需资源；卸载先在锁内摘除回调，再解锁并等待，使用原生 `THREAD_CALL_OPTIONS_ONCE` 处理运行中再次排队的情况。映射页的 `ubc_msync()` 错误也传回 `setattr`、`read`、`write`、`fsync` 和 full/barrier sync。

生产函数的 ASan/UBSan 测试、真实线程的 ThreadSanitizer 检查及 11 项消融通过，XNU 增量编译和链接成功。修复已随 `01cf6f5b` 所含内核刷入 `boot_a`。普通 stop 完成卸载与 UFS 排空；真实重启后，完整 boot 物理读回摘要和 110 字节测试文件均一致。异常复位恢复的后续验证见[系统待办](../backlog/system.md)。

### 3.2 清屏与附件

Metal 驱动原来只传递首个颜色附件的清屏颜色，并根据 IOSurface、尺寸或附件数改写不透明黑色的 Alpha。AIR 又将清屏与 draw 绑定，没有 draw 的 pass 和零顶点 draw 可能丢失清屏。修复逐附件传递颜色，并通过既有工作队列执行独立清屏。

离线测试直接调用生产清屏入口，检查附件颜色、Load 保留、Alpha、空绘制和参数边界；恢复共用首附件颜色后测试失败。本轮新镜像的主屏和控制中心往返截图仍复现 Weather/Calendar 大组件黑底，图标、壁纸、Dock 与控制中心玻璃可见。该轮清屏修复尚未解决组件画面，后续 GPU 输出核查见[图形待办](../backlog/graphics.md)。

后续像素探针确认五种格式的清屏、原生 `CARenderer`、`CASDFLayer` 填色，以及四附件和 blit 均通过。另有两处可复现的接口差异：

- AIR 先把 viewport 限制到附件范围，再计算顶点变换，导致越界 viewport 的采样位置错误。修复保留调用方的原始矩形，由 framebuffer 和 scissor 限制光栅化范围；生产映射代码的 5 项主机检查通过，旧实现失败 4 项。
- Metal texture view 构造固定传入空 IOSurface 和 plane 0，丢失原纹理身份。修复继承原纹理的 IOSurface 与 plane；实际方法的 6 项检查通过，旧方法全部失败。

扩展后的运行测试在宿主原生 Metal 的默认、越界 viewport、IOSurface 及组合场景中通过。真机对照结果如下：

- A 轮仅更新 AIR：越界 viewport 通过，IOSurface 身份检查仍失败。
- B 轮再更新 Metal：两项均通过，清屏、多附件、blit、IOSurface 像素与释放检查也通过。
- B 轮 Home→控制中心→Home 往返正常，两个组件仍为黑底；另记录过日历图标短暂空白和一次设置页上半部黑屏，后续验收见[图形待办](../backlog/graphics.md)。

后续发现 texture view 的写入未更新原纹理的 buffer 写回记录。修复让各级 view 直接引用原纹理，共用已有写回记录并保留其生命周期；写入标记无需遍历全局纹理。

- 五组生产函数 ASan/UBSan 检查通过，覆盖原纹理、buffer 提前释放和多级 view；四项故障变体被识别。
- 真机 B 的 buffer 写回检查有 136 个像素错误，GPU 模式的非对齐行距 IOSurface 也有 136 个错误；C 轮仅更新 AIR 后，软件与 GPU 模式各项错误均降为 0。
- C 轮软件视频解码的 12 帧摘要仍与 ffmpeg 一致；Home→控制中心→Home 往返后，两个大组件仍为黑底。

SpringBoard 的显式图层诊断增加了有界 SDF 参数读取；两个组件由 `WidgetRenderer_Default` 的远程图层提供内容，draw 输入、输出与远程 surface 的后续核查见[图形待办](../backlog/graphics.md)。A/B 结果与画面在本地忽略目录 `storage-boot-device-1108/phase5/`，C 结果在 `phase6/`，写回探针与候选在 `out/widget-render-1108/view-writeback/`。

实际组件渲染发生在 backboardd。首批 `glass_background_sdf` 像素采样覆盖 Dock 区域，纹理槽位 3 的壁纸输入和输出均有正确颜色；该批没有覆盖顶部组件。后续 scissor 过滤增加最小宽高，并在两轮已有 draw 上通过回放；热加载轮最终停在锁屏，未取得顶部组件缩略图。

冷启动采集已确认主屏，并覆盖 `commit 863` 的 112 张缩略图；Calendar 在 work 65 从壁纸变为 RGB 234，work 70 的 `pre0` 仍为 234，`out0` 首次变为 RGB 0。RGB 234 被写成不透明黑排除了纯 coverage 或 discard；独立 `dest_0` pass-through 已通过。后续 dense 轮保留了完整正常到黑底切换，并将同次黑化 draw 关联到 `TmuaBscnA2Xhfsn_IsrcN3Oc3mtc4nlnlnl_Isqr`，目标 AIR 候选已构建待验，见[解锁转场密集采集](../progress/2026-11-08-widget-dense-transition.md)。

原提取规则遗漏了 CoreImage 的五个较大 metallib 和多份 `.scube` 文件。完整系统部署包含这些资源，当前运行记录尚未确认两个组件使用了哪些缺失文件。后续验收见[图形待办](../backlog/graphics.md)，原始探针、截图与对照日志保存在本地忽略目录 `out/widget-render-1108/` 和 `storage-boot-device-1108/phase2/`。

完整原版卷首次启动早期，应用图标和两个组件内容透明，文字、壁纸、时钟指针与 Dock 可见；原生应用启动及 Home→控制中心→Home 交互后，应用图标恢复，两个组件仍为黑底。该轮保持原 Metal/AIR 输入，尚未使用两项候选修复。图标首次显示延迟和组件黑底的后续事项见[图形待办](../backlog/graphics.md)。

生产 APFS 读取工具读取了 14 个图标资源与字体文件，共 194,500,130 字节，长度及 SHA-256 均与完整提取结果一致。该检查覆盖多个 `Assets.car`、图标遮罩和四个字体文件，未覆盖压缩文件及设备 UFS/UBC/pagein 路径。原始结果在本地忽略目录 `out/persistence-audit-1108/`。

### 3.3 音频与网络

ADSP 请求失败后原实现可产生模拟成功响应，共享内存映射也可使用固定句柄继续执行。播放完成计数因此缺少真实 DSP 完成通知。本轮按 GPR/AudioReach 协议检查回复、数据包和失败传播；实际扬声器播放验收见[多媒体待办](../backlog/multimedia.md)。

后续修正 GLINK 写指针的锁内读取、完整的 14 字段 READ_DONE 响应和采集有效长度；电源、图启动或 DMA 失败向调用方返回错误。生产函数测试通过，11 个回归变体被拒绝，完整 XNU 构建成功。背光处理保留既有 400 毫秒滑块窗口，接受窗口内分开发送的 nits/framebuffer 更新，滑块范围的后续验收见[外设与电源待办](../backlog/platform.md)。

完整系统日志确认两颗功放可读取 revision `0x9866`；DSP 状态查询和内存映射完成后，Speaker 图创建失败并停止播放。该轮日志尚未确认原生音频客户端的 PCM 已到达功放，后续 OPEN 包和 DSP 回复结果见下文。

GLINK 的 `DONE_REUSE` 原来把远端公布的缓冲区容量改成固定 2048 字节，并可能覆盖仍在传输的记录。修复保留原容量，`RX_DONE` 释放记录；发送队列写入失败会归还该次传输占用的 intent。接收游标和 intent 分配分别加锁，避免 PMIC 与 GPR 并发修改同一状态。

18 个主机场景通过，旧实现失败 7 个；删除 PMIC 发送失败后的归还操作会使重试测试失败。XNU 编译和链接成功，日志记录实际应答是否收到、opcode 和状态字段。

另以 `990b6fcc` 重建得到与真机 B 完全相同的内核，再只加入本组三个音频源文件。真机状态查询和内存映射成功，扬声器 OPEN 因缺少可用 intent 失败：固件公布 116 项，驱动固定数组只保存前 16 项；这些项容量均为 128 字节，无法发送 296 字节的 OPEN 请求。

修复改为按公告分配记录，保留容量和传输归属，收到 `RX_DONE` 后释放。19 项生产函数 ASan/UBSan 检查通过，包括真实的 116 项公告顺序、不同长度请求和分配失败恢复；旧实现无法取得 296 字节请求所需的记录。真机已收到状态查询、内存映射、Speaker/Play OPEN、I2S/PCM 配置及两组 PREPARE/START 的成功回复。一次启动曾在首条状态查询的 250 毫秒期限内未收到回复，后续集成内核启动完成上述全部操作；该次超时原因尚未确定。

当前常用镜像的 `AudioQueueStart` 返回 `-66681`（`kAudioQueueErr_CannotStart`）。直接写入 144000 帧 PCM 完成并记录两颗功放上电；现有日志没有逐包 PCM 完成计数，真实输出与听感尚未通过验收。原始结果在本地忽略目录 `storage-boot-device-1108/phase8/`。

HAL 插件修正三项独立接口问题：重新启动 I/O 时间线后更新 timestamp seed，PCM 写失败或短写返回错误，Actuator 启停保留 Speaker 计数。完整生产接口表的九个主机测试场景通过，旧实现有六个场景失败，五项故障变体被识别；arm64e 插件已上机，AudioQueue 错误仍为 `-66681`。新增探针显式请求原生 AVAudioSession playback category 和 activation，两项均成功；随后 AudioQueue 仍失败，HAL 未记录 playing。

同一内核再次出现首次 `GET_SPF_STATE` 在 250 毫秒内无回复。`4d8d9b9a` 将该查询的期限改为上游控制请求使用的 5 秒，并记录成功回复耗时；XNU 编译、生产传输检查与打包通过，其他命令期限保持原值。

后续真机候选中首次查询实际在 255 微秒内回复，独立 AudioQueue 已启动并提交 144000 帧；该轮不能证明期限变化与成功的因果关系。Bunny 原生 AVPlayer 在 117 帧正确视频后遇到 `audiomxd` SIGTRAP 和媒体服务复位，见[候选真机验证](../progress/2026-11-08-candidate-validation.md)。

新一轮在完整 `OP_WRITE_DONE` 校验后记录完成摘要，所有读数均为 sent/done 相等，最后达到 4100/4100，未出现完成校验失败。原生 Bunny 带 AAC 音轨已完整播放到结束，可见的 320 帧均为 640×360、`pixel_error=0`；rwsh 截断后续逐帧日志，因此不统计总帧数。本轮在原生播放前先执行了 AudioQueue 和直接 PCM 写入，冷启动直接运行 AVPlayer 与实际听感的验收见[多媒体待办](../backlog/multimedia.md)。相关诊断见[音频与组件冷启动诊断](../progress/2026-11-08-audio-widget-diagnostics.md)。

取消预热的冷启动对照中，首个 HTTP 请求延迟约 31 秒，随后输出 184 帧可见的正确像素；播放时钟到约 18.5 秒后进入 waiting，80 秒总期限到期。该轮 `audiomxd` 未崩溃，PCM 完成达到 3000/3000。冷启动播放的独立验收、等待原因、缓冲状态和 stall 核查见[多媒体待办](../backlog/multimedia.md)。

网络审查发现应用注入库强改路径可达性与 DNS 状态；内核的容器路径查询存在实现，原生设置接口却直接返回成功且不保存路径。本轮按系统库反汇编确认容器接口和生命周期，补上 setter、凭据引用与 exec 属性处理。打包器已移除固定应用 UUID、固定应用环境变量和 Weather/Maps 专用目录，保留通用容器父目录；应用数据目录由 MobileContainerManager 根据 bundle identifier 创建。Weather/Maps 请求失败的后续核查见[系统待办](../backlog/system.md)。

`net_test` 增加整次调用期限，超时返回 124；DNS、TCP、HTTP 与地址检查失败返回 1，HTTP 成功要求 2xx。完整生产源码的 9 项主机行为测试和 arm64e 严格编译通过，原生应用内容请求的后续验收见[系统待办](../backlog/system.md)。

应用请求日志改为记录 host/path 摘要、HTTP 状态和错误 domain/code，保留原方法调用与 `errno`，限制输出长度。`ANNIBALE_NET_TRACE=1` 可观察 23G90 两个任务完成入口，安装前检查实时方法签名；原生 Foundation 对象测试及六项故障变体检查通过，诊断库已上机。`geod` 的完成日志包含 HTTP 200/304 与实际接收字节数，早期两条请求返回 `NSURLErrorDomain=-1009`；`nsurlsessiond` 也完成一次 HTTP 200 请求。Weather 的目标请求只记录 resume，采样期内未找到对应完成记录。

本轮截图中 Weather 温度仍显示「--」，Maps 停在打开定位服务的提示框。提示框关闭后的瓦片加载尚未检查，该轮成功请求的具体用途尚未关联；记录位于本地忽略目录 `storage-boot-device-1108/phase9/`。

本轮持久启动的网络结果如下，原始日志保存在 `storage-boot-device-1108/phase2/` 本地忽略目录：

- Global DNS、IPv4、IPv6 与 Proxies 键已读取；Apple 测试页完成 DNS 和 HTTPS 请求，返回 200。
- GeoServices 裸配置 URL 返回 HTTP 400，WeatherKit 基址返回 HTTP 200；这些请求确认传输已完成，尚未覆盖地图瓦片或天气鉴权内容。
- 原生 Weather 显示温度「--」，Maps 地图区空白。Weather/weatherd 查找 `fairplayd`、`locationd` 相关 Mach 服务失败，Weather/Maps 还记录 `kvsd` 查找失败；后续系统文件与服务启动结果见下文，剩余事项见[系统待办](../backlog/system.md)。

设备与旧主机输入均确认缺少 `/usr/libexec/locationd` 和 `/usr/sbin/fairplayd.H2`，helper 的 job cache 因实际文件缺失而未登记这些服务。完整原版系统启动后，两文件均可读取，`locationd` 和 `geod` 已运行；`fairplayd.H2` 可被实际启动，但随后以 `exit(0)` 退出，launchd 延后重试。`syncdefaultsd` 仍受现有任务排除规则限制，服务与内容请求的后续验收见[系统待办](../backlog/system.md)。

`syncdefaultsd` 的排除依据来自 iOS 16.5 的 nil 路径异常。23G90 的 `changeTokenURLForStoreConfiguration:xpcConnection:error:` 先通过 `sandbox_container_path_for_audit_token` 查询客户端容器，失败后查询 MobileContainerManager 的 `com.apple.kvs` 容器，并处理空结果；本次尚未取得实际返回值，后续核查见[系统待办](../backlog/system.md)。隔离候选保留原始服务 plist 的 mobile 身份与两个 Mach service，只比完整系统基线增加该项任务，缓存从 553 项变为 554 项；这项任务受打包器的两个过滤层限制，候选尚未部署。

23G90 `fairplayd.H2` 导入 `IOConnectCallStructMethod`、`IORegistryEntryFromPath` 和 `IORegistryEntryCreateCFProperty`。可选诊断库记录 selector、长度、返回值、属性类型及主程序内的调用偏移；只观察程序自身的调用，保留参数、CF 所有权、iterator 状态、`errno` 和 `dlerror()`。认证内容、属性值、路径文本和启动参数内容均不输出。

生产函数的普通及 ASan/UBSan 检查通过，19 项故障变体被识别，arm64e 严格编译及签名校验通过。项目 launchd 会过滤任务中的 `DYLD_*` 环境变量，诊断注入通过 `/etc/inject.conf` 和 `kern.exec_inject` 配置。

真机六次加载均记录 `IOServiceMatching("com_apple_driver_FairPlayIOKit")` 后取得空 iterator，`IOIteratorNext` 返回 0，随后正常退出；尚未调用 `IOServiceOpen` 或读取产品属性。23G90 反汇编确认该失败分支直接退出，当前内核缺少对应服务。

原版驱动的 userclient 初始化只分配 24 字节状态，selector 22/23 返回查询值；selector 21/26 的输出由原算法计算。驱动存在 `IOAESAccelerator` 调用及 UID/GID 相关操作，首次开机请求是否进入这些分支仍待确认。服务注册、消息接口和实际算法尚未实现，静态地址与接口记录在本地忽略目录 `out/fairplay-probe/static/`。

按进程复核同一轮日志，Weather 和 WeatherWidget 均查找 `com.apple.fairplayd` 及 `com.apple.fairplayd.versioned`，返回服务不存在；Maps 与地图组件已确认的失败涉及 `locationd`、`kvsd`。Weather 的 JWT 签名调用见第 3.6 节，Maps 的 FairPlay 依赖尚未确认。

### 3.4 时间来源

当前实现位于 `annibale_ufs_rw.inc` 的 `annibale_ufs_sync_rtc()`：从 PMK8550 读取秒计数，从 Android `persist` 分区读取 `/time/ats_2` 或 `/time/ats_1` 偏移，再调用 `PESetUTCTimeOfDay()` 与 `clock_initialize_calendar()`。本轮保留日志中有 RTC 同步成功记录；网络校时及跨重启精度的后续验证见[外设与电源待办](../backlog/platform.md)。

### 3.5 Iris 硬解接口

静态分析确认原路径提交自造的 8-word 解码包、固定返回 session、忽略完成状态，并在 VideoToolbox 侧声明未注册的 callback 和不匹配的 Emit ABI。该路径会让上层看到注册或解码调用成功，无法证明硬件产生了帧。

本轮内核 Iris OPEN、DECODE、CLOSE ioctl 均返回 `EOPNOTSUPP`，用户态创建 decoder 返回 `kVTVideoDecoderMalfunctionErr` 并清空实例；未完成的 HFI 会话不会进入打包路径。后续 `352e8a32` 同时使设备 open 返回 `EOPNOTSUPP`，删除错误的上电、PAS、队列和 IRQ 路径，避免打开设备就写入固件区；整份驱动测试、5 个错误变体和完整 XNU 构建通过，该修改已随集成内核刷入当前 `boot_a`。真实 HFI gen2 INIT、OPEN、BUFFER、完成队列、VideoToolbox 私有 ABI 和硬件帧输出未在该轮通过验收；后续实现与实测见[多媒体验证结果](2026-11-11-multimedia-validation.md)，剩余事项见[多媒体待办](../backlog/multimedia.md)。

同笔提交修正 DSC v5 认证指针的 34 位偏移解析，并让虚表入口传入指针所在映射地址。8 项布局与入口测试、3 个实际指针反汇编检查通过，后续原生 ABI 分析使用该工具版本。

新增原生 `AVAssetReader`/`VTDecompressionSession` 诊断程序，记录每帧时间戳、尺寸、NV12 有效像素摘要和实际硬件解码属性，进程期限覆盖读取、提交与排空。10 项主机测试通过：生成的 12 帧 H.264 在软解与主机硬解下均与 ffmpeg 独立解码一致；损坏 NAL、硬件要求未满足和超时均返回失败。arm64e 构建与签名通过。

完整系统持久启动中的同一段视频验证如下，原始结果在 `storage-boot-device-1108/phase4/video-native-verification.json`：

- 软件模式退出 0，耗时 684 毫秒；12 次提交均接受并输出 12 帧，回调、丢帧与像素检查错误均为 0，276480 字节有效 NV12 数据的逐帧摘要与 ffmpeg 一致。
- 强制硬件模式退出 1，耗时 524 毫秒；会话创建返回 `-12906`，没有提交样本或输出帧。
- 软件路径记录 `kIOSurfaceMethodSetCoreVideoBridgedKeys failed: e00002c7`。23G90 对应 selector 54，清理 bridged values 使用 trap 8；该轮内核均未实现。

内核 `4fa0d162` 已实现 selector 54 和 trap 8/9，按 userclient 保存注册键，清理 values 与 bulk 属性并返回实际 seed。宿主原生实验核对了连接隔离、替换、空数组、删除后的 seed、无效地址和 bulk 清理；生产函数 ASan/UBSan、三项消融与 XNU 构建通过。集成内核的真机 VT 软件解码及 AVPlayer 本地、HTTP 播放均输出 12 帧正确像素，日志中的 selector 54 失败提示已消失。

该项验证覆盖内存中的软件解码输出，网页播放、GPU 合成与实际硬件解码仍未通过。

独立 `AVPlayer` 探针保留默认解码、缓冲与音频会话行为，检查 ready、播放状态、时钟前进、结束通知及 `AVPlayerItemVideoOutput` 的实际像素。验证结果如下：

- 九项主机测试通过，正常样本取得 12 帧，逐时间戳摘要与 ffmpeg 一致。
- 损坏媒体数据可能正常结束却输出零帧，探针据此返回失败。
- 真机 1626 毫秒完成播放，ready、playing、时钟前进和结束通知均通过；输出 12 帧、276480 字节，逐时间戳摘要与 ffmpeg 一致。该探针检查视频输出，屏幕呈现继续单独验证。

`AVPlayer` 新增显式 HTTP(S) 输入，保持原生解码与缓冲行为。真机 HTTP 播放在 1557 毫秒内完成，12 帧、276480 字节的逐时间戳摘要与 ffmpeg 一致；Safari 的启动等待继续在 WebKit 路径检查。

NV12 修复前，Y、UV plane 在真机均导入失败。实际打包的 Metal 驱动原来拒绝多 plane IOSurface；内核仓库 `a445beb3` 改为读取各 plane 的尺寸、行距与偏移，供直接导入和非对齐复制共用，并在缓存键中区分 plane。宿主原生与真机像素检查均通过：Y plane 的 512 字节和 UV plane 的 256 字节逐项一致，命令状态为 completed。

同一段 H.264 的 Safari 页面已返回媒体错误 3，首次记录只有一帧，网页播放尚未通过。实际 backboardd 日志显示 CoreAnimation 请求 Metal format 500，驱动仍按单 plane 格式校验而拒绝导入。原生 format 500 会按 surface 的视频范围与 YCbCrMatrix 把 Y/UV 转成 RGB；对应实现已提交。真机四组 compute 采样通过，fragment 输出偏绿且释放阶段发生 signal 11；Safari 本轮仍停在首帧前并返回媒体错误 3。

后续定位到 YUV 转换新增的 UV 槽位未进入 `textures_used`，IR3 因此少计片元纹理；另修正 Metal texture 未持有 device 的生命周期。`bc376ea`、`1bd05897` 已提交，生产 NIR 及释放方法检查通过。真机四组 compute 与 fragment 颜色逐项一致，探针正常退出；Safari 仍报媒体错误 3，Bunny 原生 AVPlayer 在正确视频输出后遇到 `audiomxd` SIGTRAP，见[候选真机验证](../progress/2026-11-08-candidate-validation.md)。

后续同候选对照中，原生 Bunny 已完整播放，Safari 仍在约 31 秒后出现媒体错误 3。`audiomxd` 的真实异常 PC 去除 shared cache slide 后位于 CoreMedia `_FigUserCrashWithMessage`，调用方使用 `Self-terminating due to XPC timeout` 格式化字符串。该超时的底层原因尚未确认，相关调用分析见[音频与组件冷启动诊断](../progress/2026-11-08-audio-widget-diagnostics.md)。Server、Client 参数及 WebKit 触发请求的后续核查见[多媒体待办](../backlog/multimedia.md)。

### 3.6 天气签名与 UnfairPlay 参考范围

23G90 的 `WDSJWTAuthenticatorService.generateToken(for:endpoint:)` 构造含 `bundleId` 的 JSON。`WDSJWTMescalSigner.sign(data:bundleIdentifier:)` 对其计算 SHA-1，经 `AMSMescal` 调用 `AMSMescalFairplaySession` 签名。结果经过 Base64 编码，写入 `X-Apple-ActionSignature`，随 `POST …/token` 请求申请 JWT。

原生工厂也有按配置选择 HMAC 的分支。本次未确认运行请求选择的分支、FairPlay IPC 方法及 IOKit selector，也未验证签名和服务端响应。GeoServices、MapKit 的直接依赖、本镜像字符串和符号未发现 FairPlay/Mescal 调用标识；该检查未覆盖 Maps 全部间接组件。

函数入口与请求构造地址分别为 `0x1b85627cc`、`0x1b857b70c`、`0x1b8563634`，`AMSMescalSession` 创建 FairPlay session 的 initializer 为 `0x193398b10`。定向反汇编、六框架审计脚本与结果在本地忽略目录 `out/apple-services-audit-1108/weather-fairplay/`。

[UnfairPlay](https://github.com/DrWhax/unfairplay/tree/c1753f4076fceccbf3e97625ea88c0609869e978) 此次审查版本为 `c1753f4`。它从已登记 Mac 的 FairPlay 状态恢复模型，用于同一登记关系下的个性化 IPA、SINF/SUPF 与 Mach-O 加密页处理。其格式解析、输入校验和失败测试可供后续应用安装研究参考；当前代码未提供 Mescal 请求签名、天气 JWT、地图请求或 `fairplayd` 的 IPC/IOKit 实现。本次只读源码，未运行登录状态采集或解密操作。

## 4. 验证边界

设备已通过正常 stop 返回 loader，再经 prepare 载荷进入 LK；本轮最终镜像临时启动成功，随后写入 `boot_a` 并完成重启复核。系统卷切根与更新后的数据检查点恢复均成功。运行日志中出现 BackgroundShortc 用户进程 abort，服务崩溃的后续核查见[系统待办](../backlog/system.md)。

主机运行器只对已支持的结束状态执行复位，未知状态、非零错误字段或格式异常均保存日志并停止队列；复位命令失败也记录为失败。已有 hung 状态恢复流程保留。30 项主机行为检查通过，最终仍需重新读取 loader 身份、idle 和空启动卷状态，才能开始下一轮。

当前批次的验证安排与产物记录见[系统](../backlog/system.md)、[图形](../backlog/graphics.md)、[多媒体](../backlog/multimedia.md)及[外设与电源](../backlog/platform.md)待办中的专题链接。画面检查同时使用连续截图、渲染日志和进程状态；图像差异结果需要结合内容判断。离线测试未覆盖的硬件效果保留为待验收项。
