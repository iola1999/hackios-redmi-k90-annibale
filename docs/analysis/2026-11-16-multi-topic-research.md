# 多专题并行研究与真机复现（2026-11-15～16）

适用范围：内核 `12377-wave1r4f`（`c7bd8555`）及之后的候选内核，iOS 26.6.2（23G90）。2026-11-15 晚起，8 个研究成员按专题做静态分析与历史日志核对，不操作设备；主会话在 `wave1-r4f` 同一次开机上做真机复现。本文记录各专题的结论、出处、决策与跟踪状态，新结果到来时更新对应小节和 §1 总表。

各成员的完整笔记与脚本在本地 `out/research-2026-11-15/<专题>.md` 与同名目录（Git 忽略），真机截图、探针与日志在 `out/research-2026-11-15/device/`。下文只保留结论与可复核的出处。

## 1. 总表

| 专题 | 结论 | 状态 | 待办 |
|---|---|---|---|
| IPA 在「文件」、分享菜单、TrollStore 选择器中无反应 | MiniSandbox 不接受 Seatbelt 修饰位，FileProvider 包装对象建不出来；分享面板的界面进程（Angel）没有被 RunningBoard 拉起 | 修饰位修复 `ipa-r1` 真机通过：选择器与「文件」单击可用；「打开方式」为空是原生行为；分享面板研究中 | 见 §2.5、§2.6 |
| 桌面与负一屏组件白块、透出壁纸 | 驱动声明 Apple3 却没实现 542 `RGB8_444_2P`（`_RB4`） | 根因已定位，待实现 | [G1](../backlog/graphics.md)、[S11](../backlog/system.md) |
| 蜂窝数据、电话与短信 | 基带在 SoC 内部；固件从未加载，MPSS 没有启动过 | 路线已定，第一步待实现 | [P13](../backlog/platform.md) |
| 开发工具链 | USB 带宽够用，慢在主机轮询节奏与取文件通道 | outbox 快速取文件已真机验证，其余待实现 | [ENG-21](../backlog/engineering.md)、[S8](../backlog/platform.md) |
| 待办目录整理 | 若干条目可关闭、合并或需更新状态，有编号冲突 | 建议已出，待应用 | 见 §6 |
| 相机 | 三处缺陷叠加：会话没有相机输入、前摄只输出黑电平、RAW 半块丢失；后摄另缺格式发布 | 待跑一轮纯观测探针 | [M2](../backlog/multimedia.md) |
| 硬件解码与流媒体音频 | 无尺寸 IOSurface 的分配大小自 `2fac3a50` 起为 0，创建 AAC AudioQueue 时 audiomxd 退出；1080p H.264 被拒且占住槽位 | IOSurface 修复 `media-r1` 真机通过：AAC 本地播放与 HLS 正常，audiomxd 不再退出；Iris 裁剪与拒绝后关闭 `iris-r1` 真机通过：1080p 本地播放 300 帧，被拒会话释放槽位；首包 Finish 待实现 | [M1、M3、M4](../backlog/multimedia.md) |
| 真机性能 | 首次使用路径（专化等待、AIR 翻译与进程级锁）最重，其次是调频与 4 核、CPU 面板拷贝 | 待 3 轮基线采集 | [G9、G15](../backlog/graphics.md)、[S9](../backlog/system.md)、[P11](../backlog/platform.md) |

## 2. IPA 在「文件」、分享菜单与 TrollStore 选择器中无反应

### 2.1 现象与真机复现

用户报告：「文件」里下载的 `.ipa` 点开没有反应；分享菜单无法把 `.ipa` 交给 TrollStore；TrollStore 内从文件选择 `.ipa` 后也没有反应。2026-11-15 在 `wave1-r4f` 上复现：

- 「我的 iPhone > 下载」中有 3 个 IPA，图标显示为 TrollStore 图标。
- 单击 IPA 没有任何反应，前后进程表没有新增进程，内核日志没有 `userabort`。
- 长按能弹出上下文菜单，说明触摸和「文件」自身界面正常；菜单里「快速查看」没有反应，「打开方式」显示「没有可用 App」。
- TrollStore「Install IPA File」能弹出选择器、进入「下载」；选中 IPA 后触摸到达 `backboardd`，选择器停在原处。
- `Files`、`com.apple.DocumentManager.Service`、`fileproviderd`、`filecoordinationd`、`LocalStorageFileProvider`、`TrollStore` 的线程都处于空闲等待。

### 2.2 已排除的环节

- 类型与认领：`.ipa` 的 UTType 为 `com.apple.itunes.ipa`（declared）；TrollStore 登记为 System 类型应用，声明 `public.tar-archive`、`com.apple.itunes.ipa`、`com.opa334.trollstore.tipa`。
- LaunchServices 查询：以 root 和 uid 501 分别用 `LSDocumentProxy documentProxyForURL:isContentManaged:sourceAuditToken:` 与 `LSApplicationWorkspace applicationsAvailableForOpeningDocument:` 查询，可打开该文件的应用都只有 TrollStore。
- 打开链路：探针调用 `LSApplicationWorkspace openURL:withOptions:error:` 打开下载目录里的 IPA，返回成功，TrollStore 弹出 Kumone 的安装确认框。

### 2.3 根因

- 内核 `kern_minisandbox_extension.inc`（`c7bd8555`）的签发入口只接受两种 flags：不指定目标进程时必须为 0，指定目标进程时必须正好为 `0x30000`，其他一律返回 `ENOTSUP`。
- 23G90 的 FileProvider `-[NSURL fp_issueSandboxExtensionOfClass:report:error:]`（缓存地址 `0x1acac4afc`）调用 `sandbox_extension_issue_file`，不指定目标进程，flags 固定带 NOFOLLOW（`0x20`），`report:NO` 时再加 NO_REPORT（`0x10`）。QuickLook 的包装类写法相同（`0x2412c7040`）。
- `FPSandboxingURLWrapper initWithURL:extensionClass:report:error:`（`0x1acac4768`）签发失败即返回 nil。三条路径都依赖这个包装：选择器选中后经 fileproviderd 解析书签或直接使用服务端包装；「文件」点开走默认应用或 QuickLook 分支；分享菜单拷贝给其他应用时经 `UISUISecurityScopedResource scopedResourceWithFileURL:allowedAccess:` 创建包装。
- LaunchServices 打开、分享菜单准备、UIKit 与 sharingd 签发时 flags 为 0，从 `wave1-r4e` 起已可用，所以上面的探针打开能成功。

真机读数（探针 `out/research-2026-11-15/ipa/bin/ipaprobe`，`wave1-r4f`）：

- `sandbox_extension_issue_file` 与 `sandbox_extension_issue_file_to_process` 在 flags 为 0 时都成功并可 consume；flags 为 `0x2`、`0x4`、`0x8`、`0x10`、`0x20`、`0x30`、`0x40`、`0x80`、`0x100`、`0x200` 时都返回 NULL，`errno=45`。flags 为 `0x1` 时返回 7 字节令牌、consume 返回 0，libsandbox 在用户态单独处理这一位。
- `FPSandboxingURLWrapper` 只读与读写两种都返回 nil，错误为 `NSPOSIXErrorDomain Code=45 "couldn't issue sandbox extension com.apple.app-sandbox.read..."`。

### 2.4 修复

libsandbox 导出的修饰位常量（23G90 `0x2a536e5f0` 起）：DEFAULT 0、CANONICAL `0x2`、PREFIXMATCH `0x4`、NO_REPORT `0x10`、NOFOLLOW `0x20`、NO_STORAGE_CLASS `0x40`。`sandbox_extension_issue_file` 传 `flags & ~0x30000`，`sandbox_extension_issue_file_to_process` 传 `flags | 0x30000`。

内核改动（`kern_minisandbox_extension.inc`，内核提交 `4627a236`）：

- 按 `flags & 0x30000` 区分有无目标进程；无目标进程时 pid 与 pidversion 必须为 0，有目标进程时只支持文件类型。
- 放行上面 5 个修饰位；NOFOLLOW 以 `VNODE_LOOKUP_NOFOLLOW` 查找路径，其余 4 个只影响 Seatbelt 的路径匹配与拒绝上报，当前策略不限制文件访问，不需要动作。
- 其余位继续返回 `ENOTSUP`，并打印 `minisandbox: extension issue from <进程>[<pid>] not supported: type … flags … pid …`，最多 16 行。
- 宿主夹具 `tools/tests/minisandbox-extension.fixture.c` 新增无目标 `0x20`、`0x30`、`0x46` 与 generic `0x10` 的签发和消费、带目标 `0x30032`、`0x30004`、未知位与缺目标位的拒绝用例；`test-minisandbox-issue.py` 331 项检查通过。

不采用的做法：恢复监听下载目录自动安装，或让 TrollStore 直接扫描「下载」目录。两者都绕过 FileProvider 与沙盒扩展契约，违反 [AGENTS.md §6](../../AGENTS.md#6-根因定位与原生对齐约定必须遵守)。

### 2.5 验证与遗留

内核 `12377-ipa1`（20,697,432 字节，SHA-256 `4575516a1b66…`）一轮只改这一个变量，`ipa-r1` 于 2026-11-16 00:00 开机，8 份采样日志头均为 `== XNULOADER run (usb) ==`，`payload entry 'kernel' size 13bd158` 与登记一致。

| 检查 | 修复前（`wave1-r4f`） | 修复后（`ipa-r1`） |
|---|---|---|
| 探针 `sbx`，flags `0x10`／`0x20`／`0x30` | NULL，`errno=45` | 有令牌并可 consume |
| 探针 `fpw` 只读／读写 | `wrapper=nil`，Code=45 | `wrapper=yes` |
| TrollStore「Install IPA File」选中 IPA | 无反应 | 弹出 Kumone 安装确认框 |
| 「文件」单击 IPA | 无反应 | 打开快速查看页（「iOS App」「4 MB」与分享按钮） |
| 快速查看页的分享按钮 | 未能到达 | 面板弹出但为空白卡片，见 §2.6 |
| 长按「打开方式」 | 「没有可用 App」 | 仍为「没有可用 App」，默认项「通过“快速查看”预览」已勾选，见 §2.6 |

截图与日志在 `out/research-2026-11-15/device/ipa-r1/`。验证时没有点「Install」，安装确认框以 Cancel 关闭。

- 进度表「Safari 下载的文件……可直接从 TrollStore 选择安装」来自提交 `6ce41fb` 更换 TrollStore 时的改写，11-09 的真机验证（`528f0a2`）只覆盖「文件」能看到下载与旧工具以 root 列目录，选择器与分享安装没有实测记录。这是测试条件不同，不属于回归；进度表措辞待改。
- 未确认：本项目的无目标令牌格式与原生不同，是否有调用方解析令牌内容。

### 2.6 分享面板空白与「打开方式」为空

分享面板：

- 面板内容由 `SharingUIService.app` 在远程场景中绘制。ShareSheet 用 `identityForAngelJobLabel:` 与 `_UISceneHostingController initWithProcessIdentity:sceneSpecification:` 托管场景，场景角色为 `UISceneSessionRoleShareSheet`。
- 它的 launchd 任务 `com.apple.sharinguiservice` 是 LaunchAngel，唯一的 Mach 服务标有 `_ExperimentalNonLaunching`，launchd 不会因服务查找而启动它，只能由 RunningBoard 按场景请求拉起。`ipa-r1` 点分享后没有新进程出现，面板是空白卡片。
- 本项目由 `mkjobs.py --rest` 把 LaunchAngel 与 LaunchDaemon 一起登记进任务缓存，`NonLaunching` 标记保留，同类 Angel 共 40 个。`package.py` 的 `EXTRA_JOBS` 注释记录过同一现象：PosterBoard 也是 Angel，当时为了让壁纸出现去掉了它的 `NonLaunching`。

`share-r1` 观测轮（内核 `12377-media1`，runningboardd 与 sharingd 以 `OS_ACTIVITY_DT_MODE=YES` 启动，只输出 error 级日志，原始日志在 `out/research-2026-11-15/device/share-r1/`）读数：

- sharingd 在设备时间 00:22:53.116 打出 `Activating com.apple.sharing.sharesheet`；点分享后的截图停在快速查看页，没有面板。
- runningboardd 在 00:22:52.130 记录 `Process start failed to launch/find job with error Error Domain=NSPOSIXErrorDomain Code=22 "Invalid argument" UserInfo={NSLocalizedDescription=Trying to launch a daemon, agent, or angel as an app.}`。error 级日志不含任务名，是否对应 `com.apple.sharinguiservice` 待确认。
- runningboardd 在 00:22:51～00:23:05 共 9 次记录 `Rejecting launch request because [osservice<com.apple.SpringBoard>:29] is not entitled to launch processes`。23G90 原版 SpringBoard 的 `com.apple.runningboard.*` 权限里没有名称上对应启动进程的键，RunningBoard 的判定条件与 SpringBoard 在原生系统上是否也被拒，交给静态分析。
- 开机早期 8 次 `parseAdditionalProperties for RB launch proccess has no RunningBoardLaunchedIdentity`，与任务缓存中的登记方式是否有关待查。

其他日志行：

- `extensionkitservice` 的 type 1 签发：`prepareWithLaunchConfiguration:reply:`（ExtensionFoundation `0x184c048d0`）对每个扩展调用 `sandbox_extension_issue_mach_to_process`，扩展类 `com.apple.pluginkit.plugin-service`，资源为扩展的 serviceName，目标为宿主进程（PosterBoard、chronod）。签发失败与消费失败都只记日志，扩展进程照常启动；MiniSandbox 不限制 mach-lookup，所以它不是分享面板、海报或组件异常的原因。
- `privilege 12010`、`12011` 是 `PRIV_SKYWALK_OBSERVE_ALL`、`OBSERVE_STATS`。Skywalk 打开 nexus 控制器时依次探测，任一通过即可；sharingd 有 register-user-pipe 权限，原生系统上前两次探测同样被拒，不影响分享。

「打开方式」为空是原生行为：菜单由 CoreServicesUI 的 `CSUIOpenWithFlow` 构建，`CSUIOpenWithMenuConfiguration` 默认 `requireOpenInPlace` 为 YES，LaunchServices 据此只留声明支持原地打开的应用；TrollStore 的 `LSSupportsOpeningDocumentsInPlace` 为 false，被排除。探针用的 `applicationsAvailableForOpeningWithError:` 没有这个条件，所以能拿到 TrollStore。原生上把 `.ipa` 交给 TrollStore 的入口是分享菜单。

MiniSandbox 与原生 Sandbox.kext 签发行为的剩余差异（23G90 kernelcache 签发函数 `0xfffffe000a421010`）：

| 位或类型 | 原生 | 当前（`4627a236`） |
|---|---|---|
| 0x2 CANONICAL | 规范路径检查，不通过返回 EPERM | 放行，不检查 |
| 0x4 PREFIXMATCH | 文件类型返回 ENOTSUP，其他类型记入令牌 | 放行 |
| 0x8 | 只允许文件类型 | ENOTSUP |
| 0x2000、0x4000、0x8000 | 允许 | ENOTSUP |
| 0x10000 单独（按 pid） | 支持，pidversion 取进程当前值 | ENOTSUP |
| 其余位 | EINVAL | ENOTSUP |
| type 1 mach、type 2 iokit 指定目标 | 支持，令牌追加服务名 | ENOTSUP 并记日志 |

这些差异目前没有对应的用户可见故障，对齐工作记为后续项。

## 3. 桌面与负一屏组件

### 3.1 真机现象

- 主屏天气、日历两个大组件一直是上白、中部透出壁纸、下白的形状；负一屏多个组件同样，电池组件始终正常。
- 2026-11-15 23:44 连拍：右滑进入负一屏后约 0.5 秒，日历组件还能看到「15」「初七」「周日」「今天无日程」，但中部已有透出壁纸的横带；约 1.0 秒起所有 WidgetKit 组件内容消失，之后不再变化（`out/research-2026-11-15/device/today/`）。
- 白带宽度固定 124 面板像素，白色恒为 (235,235,235)，透出区沿组件长边展开。
- SpringBoard 图层导出（`notify com.annibale.layers.Widget`）只到 `CHUISWidgetHostViewControllerView` 一层，0.2 秒与 2 秒两次结构相同，`contents=none`、无背景色；内容层由远程进程托管，现有导出看不到。

### 3.2 根因

- `_RB4`（`0x5f524234`）是 Metal 542 `RGB8_444_2P`：两个全尺寸平面，plane 0 存 G，plane 1 存 B、R，无 alpha。布局与宿主实测见[渲染核查 §10](2026-11-12-rendering-runtime.md)。
- RenderBox 对不透明、未指定像素格式的图层，在设备对 `supportsFamily` Apple1～Apple3 连续回答支持时选择 542（23G90 `0x196a8063c`、`0x196a43710`、`0x196a3627c`）；QuartzCore 只要求 Apple1 就把 `_RB4` 映射到 542（`0x184156e84`、`0x183efa560`）。
- 驱动默认 profile 4 声明 Apple3，但 542 在 `annibalemetal_texture.inc:713-719` 与 `annibaledrawable.m:528` 被拒绝。`wave1-r4f` 中 `WidgetRenderer_Default` 的 8 次提交都没有绘制，每次提交前都拒绝一次 `_RB4`；`backboardd` 只对 `0x4e`、`0x4f` 两个 surface 失败 22 次，对应桌面两个组件。
- 推测：白色是组件背景，只画在内容层不透明矩形之外；负一屏先显示的是快照，随后切换到 `_RB4` 格式的实时内容。

### 3.3 下一步

- 在驱动已有的双平面 RGB 路径（540／543／544，目前只支持 4:2:0 与 4:2:2）上补 542 的导入与渲染目标。只实现采样不够：组件进程仍写不进去，未写入的 `_RB4` 会显示为黑块。渲染中间纹理需改为可混合的格式。
- 这些文件 11-14 随相机工作加入，改动前与相机工作协调。宿主读取探针 `hackios-xnu-userland/tools/air/rgb8-444-2p.md` 与新的渲染探针先通过。
- 验收：`_RB4` 拒绝与 `Failed to allocate MTLTexture` 都为 0，`WidgetRenderer_Default` 的提交有实际绘制，组件不再透出壁纸。不使用 `metal_profile=1` 做对照，它一次改变多个变量。
- 未确认：白带由哪一层按什么规则跳过；用户所说的黑色块来源；格式 523 的 FourCC；`_RB4` surface 的实际尺寸。

## 4. 蜂窝数据、电话与短信

- 接入方式：基带在 SoC 内部。控制面走 SMEM GLINK 的 `IPCRTR` 通道（QRTR 上的 QMI），数据面走 IPA v5.5，设备树地址 `0x3e00000`，没有 PCIe 外置基带。
- 当前状态：`annibale_modem_init` 每次开机都运行，3950 份真机日志都停在 `modem.mdt not present`，MPSS 从未启动，GLINK、QMI、SIM 都没有真机记录。
- 固件读取缺陷：modem 固件在 `modemfirmware_a` 分区（`modem.mdt` 加 `b00`～`b42`，最大的 `b29` 为 48.6 MB），读取器只扫 `modem_a`／`modem_b`（`annibale_ufs_rw.inc:560`）。同一路径上 FAT 回退限制单文件 4 MiB（`annibale_ipa.c:574`）；`ipa_fws` 段 paddr 为 0，被 `annibale_ipa.c:664` 拒绝；IPA 基址写成 `0x1e00000`（`annibale_ipa.c:51`）。
- 修好查找后 `modem=0` 也会加载并复位 `modem_dtb` 与 `ipa_fws`（`annibale_modem.c:977-988`），修查找前先加门控。
- iOS 侧：23G90 对应的基带为 MAV25，kext 为 `AppleBasebandM20`、`AppleBasebandPCI`、`AppleBasebandPCIMAVControl`、`AppleBasebandPCIMAVPDP`、`AppleIPAppender`；用户态 `libPCITransport` 使用 `sahara`、`qmux1`、`qmux2` 管道，协议同为 QMI（QMUX 封装）。
- 同类项目 UniXNU/QcomBaseband（BSD-2，SC7180 + iOS 17）在内核发布 Apple 基带 IOKit 类，做 QMUX 与 QRTR 桥接、私有服务应答和 IPA；作者自述做到读 SIM、LTE 注册与 IPv4 上网，本项目未复核。
- 阻塞：AP 侧缺 rmtfs、servreg、TFTP、IPA QMI 服务（现有 QRTR 只有客户端接口，依赖关系按 Linux 角色划分推测）；IPA／GSI 未实现；iOS 26 ABM 对 MAV25 的启动要求未知。
- 路线（按顺序）：修固件读取与门控，补 QMP、ARC 投票与 SMP2P；真机一轮 `modem=3` 读 PAS 返回码、ready／handover 位、IPCRTR 与 QRTR 服务列表；实现 rmtfs、servreg、TFTP，验收读出 SIM 状态并完成注册；IPA 数据面拿到 IP；Apple 基带 IOKit 层让 CommCenter 原生运行，之后删除 `inject_cellular` 的方法交换与可写 sysctl。
- 未确认：DSM 区域分配是否必须（不做可能触发 XPU 违规并整机复位）；没有 rmtfs 时 modem 的表现；小米固件 `DATA40_CNTL` 上是否有 QMUX；VoLTE 语音通路。

## 5. 开发工具链

基于 85 轮 `commands.jsonl` 的统计：

| 操作 | 读数 |
|---|---|
| 截图 | USB 部分 p50 0.34 s（n=303），约 40 MB/s；宿主转 PNG 半尺寸 0.14 s；370 张原始数据占 4.3 GB，`docs/progress/evidence/k90auto/` 共 9.9 GB |
| `rsh.py` 往返 | 设备端 p50 4 ms（n=1064），主机端 p50 约 3 s；`run-auto.py` 只在发送后 2／5／10／18 s 读日志（`run-auto.py:329`） |
| `fetch.py` 取文件 | 走 `annsh cat`，约 10 KB/s |
| 一轮到桌面解锁（`wave1-r4f`） | 约 62～67 s：打包 6.8 s，恢复到 loader 27.6 s（其中复位到重新枚举 26 s），上传 1.5 s，`oem run` 到解锁 25～30 s，发现解锁到截图 6～11 s |

已核实的问题：

- 运行中可以高速取文件，loader 与内核都不用改。2026-11-15 真机验证：annsh `outbox` 写出 71,376 字节文件后，按日志里的物理地址执行 `oem stage` 与 `get_staged`，SHA-256 与原件一致，用时 0.07 s。
- `cycle.py` 固定带 `fb_flip=2`，`oem screenshot` 只读缓冲 A，缓冲 B 在屏上时截到的是上一帧或正在绘制的帧（`MiniFramebufferFlip.inc:5-9`），频率未量化。
- 命令邮箱只有一个槽（`annibale_threads.c:331-343`），连续发送会覆盖前一条，目前靠调用方串行。
- 1 MB 日志环最短只覆盖 2.8 s，日志量大时命令输出可能在读取前被覆盖。
- `trollstorehelper open／url` 已实现（`TrollStore/RootHelper/main.m:971-986`），本地没有构建产物，`rc.jobs` 里对应一行静默失败。
- SpringBoard 图层导出只认已注册的过滤词，向下最多 3 层，看不到远程托管的内容层。

改进清单（按收益排序）：

1. `run-auto.py` 发送命令后每 0.2 s 跟读日志直到结束行，`rsh.py` 轮询改为 0.1 s；模拟 p50 从 2.7 s 降到 0.46 s。
2. `fetch.py` 改用 outbox 加 `oem stage`，失败时退回 `cat`。
3. 截图转 PNG 后删除原始数据。
4. 构建 `trollstorehelper` 或新增独立的打开应用程序，`cycle.py` 打包前检查程序存在。
5. 启动阶段每 1 s 取一份日志快照并写解锁标记，每轮预计少 4～8 s。
6. annsh 新增内建命令执行收件区里的文本，绕开 119 字节限制且不改 ABI。
7. loader 侧合批：截图读当前扫描输出的缓冲；复位前写持久标记，下次启动直接停在 Fastboot，消除恢复竞态（旧记录 28 次中失败 2 次）。
8. 图层导出支持任意类名过滤与更深层级。
9. Wi-Fi 上的 annsh TCP 或 SSH（ENG-21）在 1～6 之后评估；原生 USB（S8）暂缓。annsh 继续只依赖 C 与 libSystem，需要框架或权限的功能做成独立程序。

## 6. 待办目录整理建议

以下为整理建议，尚未应用到待办表；应用时逐条核对出处。

- 关闭或合并：G14（相机 MPS／CI）关闭，剩余部分分别归 M13、G7／G5、M2；G7 的指令覆盖与语料并入 ENG-08，图标部分清空 AIR 缓存冷启动一轮后决定；M11 并入 G15；G4 并入 ENG-11；S11 拆分，`WidgetRenderer` 归 G1，`audiomxd` 归 M4，`bluetoothd` 归 P6。
- 更新状态：S18 改为「待实现」，并写清检查点落盘尚未验证、`var_apfs=1` 默认关闭（`c7bd8555` 提交说明的「检查点刷新」指去掉未落盘即清脏位的实现与写入顺序调整）；S10 写入 R2-04 的 `F_GETPATH` 结果；S16、P3、P8 按 `wave1-r4f` 截图缩小范围；G5、ENG-05、ENG-06、ENG-07、ENG-15 按新提交同步；G12 引用的用户决定改为架构审查 §21 第 3 项；G19、S20 改为条件项。
- 编号冲突：graphics.md 有两个 G14，面板尺寸一项改为 G20；系统批次的 S8 在待办中拆成 S8 与 P9，README 未说明；提交 `91fe491`、`487556da` 说明里的 M1、M2、M4 与待办编号含义不同；性能方案里的「P11 面板」与 P11 CLPC 同名；S1、S3、S4 引用的 `10f3fd5c`、`f449168` 不在 `k90-port` 上，代码实际随 `c722b945`、`a0621f5` 合入。
- 低成本候选：G13 只需改文档（`0e0f19bb` 对 `renderencoder.inc` 的实际改动只有 `setScissorRects`，两仓 `git log -S prior_copy` 为空）；ENG-22 在宿主侧补 `root/` 权限比对；ENG-20 把 `loader_05_layout_run_kernel.inc:626` 追加的 `rd=md0` 改为 `rootdev=md0`，随下次 loader 重建验证；一轮观察与一轮重启读回可关闭或收窄约 12 项；G8 用 `wave1-r4f` 渲染报告列出的未实现 selector（IOMFB 16 个、MiniIOSurface 5 个）替换原文。
- 需要用户决定：S17、P15、M10。

## 7. 相机

现象：`wave1-r4f` 中相机应用能打开，拍摄界面完整，预览全黑。三处缺陷叠加，只修其中一处出不了图。

- 会话没有相机输入：§91.9 记录 `parsedCameraSourceConfigurations` 为 nil，11-14 run-2 的 Parse-input count=0，图不启动。`wave1-r4f` 中 catalog 阶段 Generic 请求 positions 1 与 0 都返回 -12780（`s003.log:12359-12379`，CMCapture `0x1aedb0e44` 处 `copyStreamsFromDevice` 的失败分支）；旧库时期前摄请求 position 2 能成功。推测与 `01ccb72` 有关：前摄端口改为 FrontSuperWide（`camera_device.c:153-157`），`mkcameraresources.py:55` 仍插入 Front Camera 描述。
- 前摄只输出黑电平：三轮 6 帧均值 63.97～64.04，σ≈1.05；曝光从 256 行加到 2000 行并加 4 倍增益，均值只涨 0.03～0.06 DN，比预期低约三个数量级。之前看到的条纹来自未写入的半块。
- RAW 半块丢失：保留下来的半块地址与 RAW10 相位正确，缺失的一半没有写到相邻半块。推测丢失发生在 WM 之后的总线上（设备树 `cam_hf_qtb` 有两个端口，内核没有配置 CAMNOC）。查清丢失的半块是否写到别的物理地址之前，不开长时间连续预览。
- 前摄 VANA 对应 PM8010M L3M（SPMI SID `0xC`，基址 `0x4200`），内核只看投票命令返回值，从没读回使能或过流状态。
- 后摄：曝光辅助函数只认 4096×3072（`annibale_camera_exposure.inc:47-51`），实际 profile 为 2560×1920；91.x 时期内核不发布 `BACK_MODE24`，后摄只建了手电筒 stream，formats 为空；HEAD 上后摄没有观测记录，后摄采集从没在真机上跑过。

下一步：一轮纯观测探针，依次读 PM8010M LDO1／3／5 状态、传感器寄存器、CAMNOC 错误记录器与 SMMU 全局故障寄存器、AVFoundation 设备清单、cameracaptured 的 Generic 与会话解析、Camera.app 截图、前摄双曝光 RAW，最后单拍一帧后摄（首次上机，失败可能保留资源）。按读数定下一轮的单个变量，修复顺序为设备发布、前摄供电或初始化、半块写入路由、后摄。

未确认：HEAD 上相机会话的实际状态（`wave1-r4f` 日志止于 23:10:53，没有覆盖相机时段）；PM8010 状态寄存器位定义与 QTB 寄存器布局；`inject_media.c` 沿用 iOS 16.5 时期的替换（稳定化固定为 0、跳过 GNR 节点等）对 iOS 26 建图的影响。

## 8. 硬件解码与流媒体音频

- 无尺寸 IOSurface：内核提交 `2fac3a50`（11-14）起，只给 `IOSurfaceAllocSize`、不带宽高的 IOSurface 分配大小为 0（`MiniIOSurface.cpp:615`）；宿主复现中，回退到上一版返回按页对齐的请求大小。AudioToolboxCore 建这种 surface 后检查分配大小，偏小即抛出 `bad IOSurface`（`0x18fe351a8`、`0x18fe352d4`），audiomxd 未捕获而退出。`wave1-r3` 两次创建 AAC AudioQueue，各在 4 ms 内跟着一次 audiomxd 退出（`s015.log:8968`、`8984`）；11-13 的同类运行正常。审查文档 §1 记的「缺少 `AudioConverterService`」不准确，这个服务当时已启动。
- 当前内核复现（2026-11-16 00:08，`ipa-r1`，内核含 `2fac3a50`）：`video_player_test --deadline 30` 播放 10 秒 720p H.264 加双声道 AAC 的本地样片，日志出现 `Creating AudioQueue with format:'aac '` 后紧接 `libc++abi: terminating` 与 `userabort: audiomxd[87]`，播放器返回 AVFoundation -11819，audiomxd 由 launchd 重启为 pid 430。
- 影响：经 mediaplaybackd 的播放（Bilibili）在 `wave1-r3` 实测退出；Safari、Music 与普通 AVPlayer 走同一路径，推测同样退出。`wave1-r4e`、`wave1-r4f` 没有出现 audiomxd 退出，是因为这两轮没有创建 AAC 队列。
- 1080p 硬解：宽高不是 16 倍数的 H.264 在 Iris 上一律被拒（`annibale_iris_hfi.c:659-660`），`wave1-r3` 中 Bilibili 四个 1080p 会话都因此失败；原厂驱动按对齐尺寸分配缓冲、按裁剪区输出（`msm_vdec.c:1342-1416`）。被拒的会话关闭时保留 DMA、不释放槽位，4 个槽占满后同一次开机所有硬解返回 -12911。
- 首包 Finish 的 27 帧错误与两帧缺失：第一个 IDR 帧的输出被固件扣住，要等下一个输入或 DRAIN；插件在 Finish 时遇到未出帧就发 DRAIN（`videotoolbox_iris.c:885`、`891`），DRAIN 后 sample 2 与 sample 5（P 帧）被固件标为数据损坏。推测固件把 DRAIN 当成流结束、丢掉参考帧，错误延续到帧 30 的下一个 IDR；原生解码器的 Finish 不触发硬件排空。

IOSurface 修复：只给大小、没有宽高的 surface 不再按空的几何尺寸截断，按页对齐保留请求大小；带宽高的 surface 保持 `2fac3a50` 的行为（`MiniIOSurface.cpp`，`test-iosurface-abi.py` 新增 3 种请求大小的用例，内核提交 `1ffe6abc`）。内核 `12377-media1` 一轮只改这一个变量，`media-r1` 于 2026-11-16 00:12 起验证：

| 检查 | 结果 |
|---|---|
| 本地 720p H.264 加 AAC，10 s | 出现 `Created new AudioQueue for format:'aac '`，300 帧、像素错误 0，`result=pass`；audiomxd pid 85 不变 |
| 本地双声道测试音（左 1 kHz、右 440 Hz 同时） | 播完，用户听到声音，同时响时分不出左右 |
| 本地分时测试音（先左 3 s，再右 3 s） | 用户确认两段来自不同扬声器，哪段在上、哪段在下未确认 |
| HLS（主机临时 HTTP 服务，Wi-Fi 拉流，20 s） | 12 次请求，599 帧，无卡顿，`result=pass`；audiomxd 不变 |
| 本地 1080p | 音频播完、视频 0 帧；Iris PSC 报 `resolution=0x7800440`（1920×1088），关闭时 `close retained slot=1 error=102`，槽位保留到重启，与上面的分析一致 |

HTTP 方式播放 mp4 返回 AVFoundation -11850，原因是 Python `http.server` 不支持按字节范围请求，测 mp4 要用本地文件或支持 Range 的服务。Safari 测试页四种媒体还没测。

Iris 修复（`annibale_iris_hfi.c`，内核提交 `c9b9828a`）：

- PSC 按原厂 `msm_vdec.c` 的布局解析编码尺寸与裁剪：`CROP_OFFSETS` 第一个字为 `left << 16 | top`，第二个为 `right << 16 | bottom`。只接受左上角不裁剪、裁剪后正好等于会话宽高，且 RAW 步长、行数和 5 种内部缓冲按编码尺寸计算后都不超过打开时分配值的情况。原厂驱动在 PSC 时按编码尺寸重建内部缓冲（`msm_vdec_input_port_settings_change`），本驱动不重建，放不下时拒绝。
- PSC 未通过上述主机侧检查时，会话标记为主机拒绝。关闭时如果错误仍是这次拒绝、RAW 端口未启动且硬件在线，按正常顺序 STOP 码流端口、CLOSE，再释放 DMA；固件或协议错误仍保留 DMA。
- 宿主测试 `test-iris-hfi-wire.py` 新增 640×474 编码为 640×480 的接受用例、裁剪不符的拒绝用例和拒绝后正常关闭的用例，3 个对应变异均被检出：204 个用例、90 个变异检查通过；其余 Iris 宿主测试通过。

内核 `12377-iris1`（20,697,480 字节，SHA-256 `89e7b55dba0c…`）一轮只改这一个变量，`iris-r1` 于 2026-11-16 00:36 开机，采样日志头为 `== XNULOADER run (usb) ==`、`payload entry 'kernel' size 13bd188`：

| 检查 | 结果 |
|---|---|
| 本地 1080p H.264 加 AAC，10 s | PSC `resolution=0x7800440 crop=0x0/0x8`，`RAW published`；300 帧、像素错误 0，`result=pass`；`close done slot=1` |
| 隔行 H.264 720×480（MBAFF），连续 5 次 `video_decode_test --require-hardware` | PSC 因非逐帧编码被拒，测试返回失败；5 次都是 `close done slot=1`，没有 `close retained` |
| 之后 `video_decode_test --require-hardware` 播 1080p | 60 帧，`hardware=1`，`result=pass` |
| 之后本地 720p H.264 加 AAC | 300 帧，`result=pass` |

日志与样片在 `out/research-2026-11-15/device/iris-r1/`。修复前同一 1080p 样片在 `media-r1` 中视频 0 帧、槽位保留到重启。

后续：B 轮插件单独提交参数集，看第一帧能否自己出来；C 轮强制在第 7 帧后 DRAIN，验证参考帧是否失效。左上角裁剪、编码尺寸超过打开时分配的流仍被拒绝，出现实际需求时再按原厂做法在 PSC 时重建内部缓冲。

未确认：`2fac3a50` 截断带尺寸 surface 的 AllocSize 的来源；还有哪些系统组件使用无尺寸 IOSurface；长时间播放的主机时钟与 DSP 消费速率偏差；M13 本次未分析。

## 9. 真机性能

- 解锁后黑屏：显示层为空，驱动把面板清零，`wave1-r4f` 黑 1.20 s、`wave1-r4b` 黑 0.47 s。推测主屏内容与壁纸进程（51.35 s 才注册）尚未提交。
- 首次使用路径：解锁卡顿期间 SpringBoard 主线程 32 个采样中，23 个停在原生函数专化调用内的 `kevent_id`，5 个在 AIR 翻译。AIR 进程级锁覆盖整个管线创建（`air_metal.c:4892`），提交与完成写回也取这把锁；205 ms、238 ms 的单次写回尖峰是否由此造成为推测。
- 长帧组成（`wave1-r4b` 手势窗口）：GPU 段超过一拍 121 帧，backboardd 段超过一拍 58 帧；3 拍以上的帧 backboardd 段中位数 26.9 ms。
- 面板拷贝占 14.4% 时间，43% 的 swap 要等上一帧拷完；设置页静止时每秒 10 帧，每帧仍拷 1,943～1,970 行、耗时 12～14.5 ms。
- 调频：出帧期间 CPU 有 34%～80% 时间停在 384／1017 MHz；XNU 性能控制回调未注册（`machine_routines_common.c:766`）。
- 持久化：`/private/var` 的写入按页同步写穿并持有 `rm_lock`，每次 fsync 全量重写元数据；开机后 185 s 内 242,280 次 UFS 写请求，在总耗时中的占比未知。
- 打开设置后的 0.47 s 内，`_RB4` 双平面 surface 反复建纹理失败；是否就是 G18「半屏黑色窗口」的原因为推测，与 §3 同源。
- RunningBoard 给进程设 GPU 角色失败：`share-r1` 日志 27 s 内 76 次 `setGPURole:pid: failed due to nil IOGPU device ref`，驱动没有发布 RunningBoard 能找到的 IOGPU 服务。前后台切换时 GPU 优先级是否因此不随进程状态调整，待查 RunningBoard 的匹配条件。

瓶颈排序：首次使用路径 > CPU／GPU 调频与只开 4 核 > CPU 面板拷贝 > 持久化同步 > Mach 时钟陷入。

下一步：G15 把编译移出 AIR 锁，确认 MTLCompilerService 缓存第二次开机命中，再加 AIR 到 NIR 的翻译缓存，判据是第二次开机从解锁到帧节奏稳定不超过 1 s；P11 注册性能控制回调，按每帧截止时刻提档，同批做 `cpus=7` 单变量对照，温度守住 70 °C；S7／G10 单层 BGRA 由 DPU 直接扫描，先查清设置页 10 Hz 帧的整块行变化来源。真机采集 3 轮：R1 基线、R2 同载荷复跑、R3 `cpus=7`。

未确认：专化等待的对端；解锁后显示层为空的成因；持久化写入的组成与锁等待；用户态取时陷入的开销与频率；自动解锁实际延迟 13.6～21.5 s（应为 4 s）的原因。

## 10. 决策

| 日期 | 决策 | 决定方 | 依据 |
|---|---|---|---|
| 2026-11-15 | 蜂窝接入后，CommCenter 下发的 Apple PRI／GRI 运营商配置确认收下后丢弃，生效的是基带自带配置 | 用户 | Apple 运营商配置无法用于高通基带固件；同类项目做法相同 |
| 2026-11-15 | IPA 问题按内核接受 Seatbelt 修饰位修复，不采用监听下载目录或扫描「下载」目录的方案 | 主会话 | §2.3 根因；AGENTS.md §6 |
| 2026-11-15 | 组件修复补 542 的导入与渲染目标，不用 `metal_profile=1` 对照，不只实现采样 | 主会话 | §3.2、§3.3 |

## 11. 真机运行异常

| 时间 | 轮次与内核 | 现象 | 处理 |
|---|---|---|---|
| 2026-11-16 00:20 | `share-r1` 首次，`12377-media1` | `oem run` 后约 1 s 设备从 USB 消失，重新枚举后 loader 自动启动 `boot_a` 常驻镜像（日志头 `== XNULOADER v3 ==`，内核 `0x1398ce0`）；`run-auto.py` 判为 `RESET_FALLBACK_DETECTED`。同一内核在 `media-r1` 正常启动，复位发生在用户态之前，与本轮打开的日志输出无关；复位前的内核日志没有保存 | 原始记录改名为 `kernel-12377-media1-share-r1-fallback`，同配置重跑 |
