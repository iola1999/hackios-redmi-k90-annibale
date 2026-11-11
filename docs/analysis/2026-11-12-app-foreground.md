# 后台应用前台切换核查（2026-11-12）

本批按[执行计划](../plan/2026-11-12-app-foreground.md)核查 S5。最新固定采集轮中，设置冷启动后的两张截图已显示首页，进程和 scene 诊断可用。历史后台进程复用故障及此前黑底画面的根因仍待确认，完整 assertion／scene 对照尚缺。

## 1. 已有结果与当前边界

[应用签名记录 §5](2026-11-09-ipa-codesign.md#5-真机结果)确认重新签名安装后应用可从图标启动；后续开机后台拉起的进程复用时未显示界面，结束后再次启动可见。该记录没有给出失败阶段的 PID 状态、RunningBoard assertion 或 FrontBoard scene 回应。

S10 已使用 `vfs_getnewfsid` 分配 APFS 挂载身份，宿主检查与目标文件编译通过，设备往返待验。具体修改见[渲染核查 §4](2026-11-12-rendering-runtime.md#4-apfs-文件身份)，本批不据此推定 S5 根因。

## 2. 原生启动与恢复契约

本批检查 23G90 的 FrontBoard、FrontBoardServices、RunningBoard、RunningBoardServices 和 UIKitCore。以下地址均未加运行 slide；原始反汇编、方法表和输入清单保存在 Git 忽略的 `docs/analysis/local/s5-foreground-1112/`。

### 2.1 已有后台进程的启动分支

`FBApplicationProcessLaunchTransaction::_begin`（`0x1aa77eb44`）先调用 `processForIdentity:`。已有进程处于 `isPendingExit` 时建立退出子事务；正常已有进程进入 `_queue_launchProcess:`（`0x1aa77f850`）。

| 条件 | 后续操作 | 现场需确认 |
|---|---|---|
| 已有进程，`finishedLaunching=true` | `_queue_finishProcessLaunch:YES` | 该实例的启动完成状态与身份 |
| 已有进程，`finishedLaunching=false` | `_executeBlockAfterLaunchCompletes:` | 原启动是否完成、完成回调是否发生 |
| 没有已有进程 | `_createProcessFutureWithExecutionContext:error:` | 新实例的创建结果及启动错误 |

复用与重新启动会进入不同分支。当前尚无失败现场的 `finishedLaunching`，不能确定问题发生在等待启动完成的步骤。

### 2.2 assertion 与任务恢复

`FBWorkspace::_updateProcessAssertionState`（`0x1aa773df4`）创建 `RBSAssertion`，调用 `acquireWithError:` 并保存结果与 NSError。原生日志包括 `Workspace assertion acquired:`、`Workspace state did change:`，状态原因包括 `assertion acquisition failed!` 和 `awaiting concrete target`。

`RBProcess::_applyState:`（`0x26ce6df44`）将工作提交给 `processStateApplicationQueue`。lifecycle-managed 进程的 `preventSuspend` 变化可进入恢复函数 `0x26ce6e06c`，执行顺序如下：

1. 检查进程分类，输出 `Resuming task.`。
2. 清除对象中的 suspended 标记。
3. 调用 `pid_resume`，成功后调用 `notify_resume_pid`。

现场需保留 `pid_resume() returned error`、`pid_resume() returned unexpected error` 和 `notify_resume_pid() failed` 的完整行，并核对线程状态。对象的 `isSuspended=false` 无法单独确认两个调用成功。

本仓 XNU 的 `pid_suspend`／`pid_resume` 经权限及 MAC 检查后调用 `task_pidsuspend`／`task_pidresume`；已检查的移植补丁没有替换这些调用。`MACH_TASK_BASIC_INFO.suspend_count` 返回 `task->user_stop_count`，包括 `TASK_HOLD_PIDSUSPEND` 持有的计数；它无法区分每次暂停的发起者。

### 2.3 scene 请求与回应

| 阶段 | 23G90 入口或日志 | 失败边界 |
|---|---|---|
| 服务端创建／重连 | `FBWorkspaceScene` 的 create 函数 `0x1aa78f4d8`；`Sending scene create.`／`Sending scene reconnect.` | 请求发出后仍需确认应用回应 |
| 服务端更新 | update 函数 `0x1aa792314`；`sceneID:updateWithSettingsDiff:transitionContext:completion:` | settings diff 与 transition context 决定是否发送 |
| 应用端查找 scene | `FBSWorkspaceScenesClient` 更新入口 `0x1a475f9f0` | 缺项通过 completion 返回 domain `FBSWorkspaceScenesClient`、code `1`；日志为 `No FBSScene exists for provided identity.` |
| 应用端连接状态 | 内部更新函数 `0x1a475fb64` | 存在 `Ignoring update for disconnected scene.` 分支 |
| UIKit 处理 | `UIApplicationSceneClientAgent` `0x1893715fc` → `UIScene` `0x1892c0f04` | 更新后安排回应，部分操作在 CATransaction commit 后执行 |
| 服务端完成 | `FBSceneObserver::scene:didCompleteUpdateWithContext:error:` `0x1aa7803e0` | 关联 scene ID、transaction ID 和错误 |

`_hasCalledRunWithMainScene=false` 分支会继续处理 scene 更新；本批未发现该值直接阻止回应的分支。它与历史故障的关系仍待现场确认。

## 3. 应用注册身份与可执行文件

`FBSApplicationInfo::initWithApplicationProxy:`（`0x1a4773d5c`）经 `fbs_correspondingApplicationRecord`、`identities.firstObject` 和 `fbs_processIdentityForApplicationIdentity` 派生身份。仅比较 Bundle ID 无法覆盖 persona 与进程身份的差异。

`LSApplicationIdentity::initForRecord:personaWithAttributes:`（`0x18169c420`）从 Bundle ID 和 persona 属性构造 `identityString`；已检查的构造路径未见数值 FSID 参与该字符串。FBS 初始化还读取 proxy 的 `canonicalExecutablePath`（`0x1a47740a4`），该 getter 将 `bundleExecutable` 与解析符号链接后的 Bundle URL 组合。

新增只读工具 `hackios-xnu-userland/tools/tests/app-identity.m`，按 Bundle ID 查询 LS proxy、record、application identity、派生的 FBS process identity，并对 Bundle／主程序路径执行 `stat`。FBS 对象由工具新建，SpringBoard 已缓存对象的状态仍需通过 scene 和原生日志核对。

缺失应用可能返回非空但无效的 LS proxy，直接传入 FBS 初始化会触发原生断言。工具先检查 proxy 的 `isInstalled`、`appState.isValid`、Bundle URL、LS record 及 FBS 对应 record 的 application／process identity，缺项就保留查询错误并跳过 FBS 初始化。

当前 `xpcproxy_idversion` 默认值为 `0`，xpcproxy 执行服务后保留 `p_idversion`，相关实现位于 `hackios-xnu-kernel/xnu26/patches/09-bsd%kern%kern_exec.c.patch`。本批记录实际 audit token 和 `versionedPID` 以供对照，尚未建立该配置与 S5 的因果关系。

## 4. 诊断实现与范围

### 4.1 进程查询

`annsh process PID` 使用 `KERN_PROC_PID`、`proc_pidpath` 和 task name port，输出以下信息：

- PID、PPID、UID、BSD 状态、flags、启动时间和主程序路径。
- 主程序当前路径的 `st_dev`／`st_ino`、8 个原始 audit token word。
- `MACH_TASK_BASIC_INFO` 的 `user_stop_count` 和 resident bytes。

查询前后核对进程启动时间，并在路径与任务信息查询两端核对 audit token。调用失败、返回长度异常或身份变化会输出 `snapshot incomplete` 并返回 `1`；获得的 task name port 在查询结束后释放。工具不请求 task control port。

这些查询依次执行，结果没有原子快照保证。`snapshot complete` 仅表示查询成功且未检测到身份变化；文件替换、未改变 audit token 的 exec 或读取后的状态变化仍需结合阶段日志解释。

`tools/k90auto/ios-state.py --process PID` 将该查询加入现有采集，并保留每条命令的退出码。采集报告的 `status=complete` 表示命令列表已执行完，仍需检查各命令的 `exit`。脚本同时修正了 CLI 读取不存在的 `args.sysctls` 属性的问题。

### 4.2 scene 与画面

`notify com.annibale.layers.all` 复用 SpringBoard 主队列上的层树查询。现有字段包括 `valid`、`active`、`content`、`layers`、`clientProcess` 和 `clientSettings`；本批扩展启动完成、待退出、task state、versioned PID、scene identity 与 foreground settings，并检查 getter 的实际 ABI。

采集需核对 `begin`／`end` 和 `(cut)`。该入口只输出请求后的状态，无法记录此前的请求与回应顺序；缺少 scene 的进程也可能不在层树内。旧版缺少 `isValid`／`isActive` getter 会输出 `255`，这类读数记为未知。

`ui.py` 现会传播 rsh／fetch 失败并停止后续动作，旧 AX 文件保留供排查，失败下载的结果不再参与点击。`tour` 仅在截图分支导入，dump／tap／wait 无需 numpy。AX 注入的默认应用列表不含本次历史故障应用，实际可见性仍需截图确认。

### 4.3 原生日志

诊断候选使用 `applog=1 applog_name=SpringBoard,runningboardd,Preferences`。`applog_name` 按文件名前缀限制额外注入的 `OS_ACTIVITY_DT_MODE`、`ACTIVITY_LOG_STDERR` 和 `CFLOG_FORCE_STDERR`。

`applog=1` 还会将所有程序 spawn OPEN 动作中 fd 1／2 的 `/dev/null` 改为 `/dev/console`，这项重定向不受名称过滤。相关实现为 `exec_applog_path` 与 `exec_applog_oslog`，位于 `hackios-xnu-kernel/xnu26/patches/09-bsd%kern%kern_exec.c.patch`。构建清单保留原有参数并记录新增项，性能读数仅描述该诊断配置。

`xpcwatch` 只统计连接与服务查找，无法给出 assertion 或 scene 消息内容。原生日志仍缺某阶段的请求／回应时，再为缺失阶段增加有限诊断；当前没有修改原生生命周期或 scene 方法。

## 5. 验证状态

用户态实现与测试已提交为 `48e62db`。最终产物及逐文件摘要保存在 Git 忽略的 `hackios-xnu-userland/out/s5-foreground-delivery/manifest.json`；设备已完成一次设置冷启动采集，结果见 §9。

| 项目 | 已完成 | 待验证 |
|---|---|---|
| `annsh process` | 7 项宿主测试成功，包含真实本进程／子进程／已退出 PID、查询失败、身份变化与端口释放；iOS arm64e 链接与签名检查成功；设备 Preferences 身份与计数查询成功 | 后台复用失败阶段的计数与恢复调用 |
| `ios-state.py` | 8 项宿主测试成功，覆盖 CLI、原查询顺序、普通失败保留、传输失败停止；设备组合已完成前后两阶段采集，普通查询失败被保留 | 后台复用失败阶段的完整状态 |
| `ui.py` | 10 项宿主测试成功；旧版同套检查有 8 项失败；既有 tools 39 项、ui-health 8 项成功；现场图标前提和四张截图已取得 | Preferences 完整 AX 列表及多任务 |
| scene 扩展 | 12 场景、68 项宿主检查成功；旧版同测有 34 项失败；沿用 `build.sh` 四源文件命令完成 arm64e 链接与签名检查；设备前台 scene 字段已与设置画面对照 | 后台实例复用的启动、恢复与 scene 回应 |
| LS／FBS identity | 7 项实际探针宿主检查及 12 项 ABI／异常辅助检查成功，缺失应用和错误指针 ABI 的消融检查均失败；arm64e 链接与签名检查成功；iOS 查询保留两个不存在 selector 的错误，其余 LS／FBS 字段可读 | 两个 record inode getter 的版本差异、历史应用的注册身份 |
| S5 行为 | 失败阶段与判据已整理 | 同一应用连续前后台切换的设备验收 |

实现复核保留现有 annsh、rsh 和层树入口，进程信息没有在 LS 工具中重复查询。scene 与 SDF 共用 getter ABI 校验；尚缺的请求／完成记录先通过原生日志采集。三个目标产物独立构建，完整诊断候选已按 heap 基线装配，产物检查见 §8。

## 6. 设备对照与剩余问题

具体步骤见[执行计划 §3](../plan/2026-11-12-app-foreground.md#3-设备对照安排)。同一次开机先保存后台实例 P1 的失败现场，再对照结束后重新启动的 P2，最后验证 P2 连续前后台切换。P1／P2 分开运行 `ui-health.py`，避免重启产生的多个 PID 混入单阶段稳定性统计。

首个缺失步骤按以下顺序定位：图标请求、目标身份与 PID、原启动完成、workspace assertion、任务恢复、scene 请求、应用回应、内容提交。没有 scene 的后台进程优先通过原生日志核对 `finishedLaunching`；层树为空无法确认该字段。

尚需确认开机后台启动的发起者、launch intent、lifecycle-managed 分类及失败现场。S10 文件身份和 S5 分别验收，原生 USB 按[USB 核查](2026-11-12-usb-debugging.md)继续暂缓。

## 7. 已有截图审阅

已实际打开多媒体 `kernel-12377-codex-1112-cd14-heap-metal` 轮的汇总图，并将 `shot-01066.raw`、`shot-01231.raw` 按 `1156×2510 BGRA` 解码，分别查看原尺寸图。原始文件及 `tour.json` 保存在该轮的 `docs/progress/evidence/k90auto/` 目录，解码图保存在本专题的本地目录。

| 截图 | 采集记录时间（UTC） | 实际可见内容 | 覆盖边界 |
|---|---|---|---|
| `shot-01066.raw` | `2026-11-11T18:39:24.902181+00:00` | 桌面天气组件整块浅色，日历组件上、下为浅色条，中段露出壁纸；两者未见正常内容 | 确认桌面组件异常仍存在；根因由图形专项继续核查 |
| `shot-01231.raw` | `2026-11-11T18:39:41.364650+00:00` | 仍显示控制中心及底部手势条 | 未覆盖多任务卡片、目标应用 scene 或激活后的完整界面 |

时间来自主机发现截图文件的记录。`cc-close` 命令完成记录为 `18:39:36.543819+00:00`，第二张关闭后截图约晚 4.82 秒；该时间间隔无法给出设备准确采帧时刻。已有图未显示退出控制中心，后续先确认实际进入多任务，再判断卡片内容和激活结果。

### 7.1 正常重启后打开设置

后续 `standalone-heap-deploy/flashed-boot` 轮的 `desktop-full.png` 和 `foreground-full.png` 已实际打开查看。桌面图中天气、日历两个组件均为上下浅色条、中间露出壁纸；点击设置后的第二张图为黑色背景，桌面缩小并变暗，底部手势条可见，未见设置内容。该轮未执行多任务，任务卡片仍未覆盖。

该轮文件位于 `docs/progress/evidence/k90auto/codex-device-1111/standalone-heap-deploy/flashed-boot/run/`。以下时间为 `2026-11-11` UTC；原生系统日志使用次日 `+0800`：

| 时间 | 已记录状态 | 来源 |
|---|---|---|
| `18:55:27.125027` | 请求点击设置，坐标 `0.616, 0.715` | `tour-actions.jsonl` |
| `18:55:27.419` | FrontBoard 发布 `com.apple.Preferences-default` 前台布局；随后出现 Preferences PID 404 初始化 | `returned-held.log` |
| `18:55:29.807173` | 点击命令返回 0 | `tour-actions.jsonl` |
| `18:55:30.488819` | backboardd 收到 Preferences context `F1F1C120` 的 `unspecified -> foreground` | `returned-held.log` |
| `18:55:30.615929` | 第一张点击后截图仍显示桌面 | `tour.json` 的 `shot-01884.raw` |
| `18:55:31.628` | Preferences scene 获得 `hasKeyboardFocus` | `returned-held.log` |
| `18:55:32.039466` | bluetoothd 的状态监视器报告 PID 404、`foreground-running`、`isAlive: true` | `returned-held.log` |
| `18:55:33.149760` | 第二张图为黑底、缩小且变暗的桌面，未显示设置内容 | `tour.json` 的 `shot-01909.raw`，已查看 `foreground-full.png` |

日志已确认进程启动与前台状态发布。scene 内容是否完成提交、进入合成以及最终显示仍缺信息。第二张截图是单个采样，无法据此判定异常持续时间。

同一窗口中，backboardd 多次拒绝 FourCC `0x5f524234`、2 planes 的 IOSurface，`0x12`／`0x10` 创建 MTLTexture 失败；scene 进入前台后的相关日志为 `18:55:30.624988`／`18:55:30.625256`，后续出现在 `18:55:31.442847` 和 `18:55:31.706971`。该格式在点击前的 `18:54:59.990` 已被拒绝，WidgetRenderer 也报告相同失败。格式映射与原生布局见[渲染核查 §10](2026-11-12-rendering-runtime.md#10-_rb4-双平面-rgb-导入)。当前未找到这些 surface 与 Preferences scene 的明确对应，格式失败与本次黑底的因果关系待查。

`probe-after-processes.txt` 实际采样于 `18:54:37.839–40.635`，线程查询于 `18:54:40.636–42.427`，均早于点击。点击后约 406 ms 的自动线程样本仅覆盖 SpringBoard、backboardd 和 input26-service，早于后续 scene 前台更新；它无法描述第二张截图阶段的 Preferences 线程状态。

下一轮在异常画面窗口采集本批 scene 字段、Preferences 的 `process PID`／`threads PID` 和实际截图，分别判断内容尚未准备与已有内容但合成失败。采集顺序在起轮前固定，基线和点击后的有界采样不再等待聊天回复。

### 7.2 历史后台复用场景的前提

历史记录只有显示名 Kumone 和主程序名 KumoneIOS，未记录 Bundle ID、后台启动请求或原始轮次。当前 heap RAM 轮的两份进程采样均未见 KumoneIOS。默认启动脚本和 watcher 没有明确启动该应用的命令，通用后台调度服务仍在运行。

后续复现历史后台场景前，先从实际安装的 Info.plist 读取 Bundle ID／主程序名，再查询 LS/FBS 身份，并在点击前记录后台实例的 PID 与启动时间。点击前未出现后台实例就记录「历史后台启动前提未覆盖」，冷启动及设置打开结果分别归档。

## 8. 独立诊断候选与固定采集

### 8.1 镜像检查

候选保存在 Git 忽略的 `hackios-xnu-kernel/out/s5-foreground-1112/`，使用已验证 heap 辅助盘为基线。独立构建只替换 `/bin/annsh`、`/lib/libannibale-sb26.dylib` 并新增 `/bin/app-identity`；逐路径比较为 719 → 720 项，目录 `/bin` 的 nlink 从 48 改为 49，其余目录及文件内容保持一致。

| 产物 | 字节 | SHA256 |
|---|---:|---|
| `root.apfs` | 21,524,480 | `f2fb21ee8835b6be26072a322c72dd5a7842642e9c968167dfbc15ccb8bba43e` |
| `candidate.bin` | 42,074,232 | `9389df359a8497e0fd2a4e8cd66e6a1f08057a1a3f215af53c9dcb5d7dbaf6c7` |
| `manifest.json` | 120,652 | `6b8615901a641bea060c1f4387d9e3f55e46598dc3b560586415416e2a680ff5` |

源产物与 APFS 回读文件均通过严格签名检查。XNUP 的 kernel、memsize、identity 与基线逐字节相同；AIR、CPU／GPU 参数和常驻启动卷保持基线内容，命令行只追加 §4.3 的两个日志参数。完整比较保存在同目录的 `payload-check.json` 和 `delivery.json`。候选已由唯一 device 执行一次采集，结果见 §9。

### 8.2 一次设置打开的采集范围

`docs/analysis/local/s5-foreground-1112/s5-visual.py` 复用既有 runner、rsh、ios-state、AX 和截图接口，21 项宿主检查成功，设备工具调用均由 mock 替代。测试另用真实本机子进程验证超时清理，包括父进程先退出、孙进程忽略 SIGTERM 的情况。

8 份来源文件已逐字复制到同目录的 `frozen/`，保留来源相对目录结构；冻结副本在工作区之外再次通过 21 项测试，所有项目脚本依赖指向冻结目录。`frozen/manifest.json` 保存推荐命令、逐文件 SHA256 及外部 Python 3.14.6／NumPy 2.5.4 信息，清单 SHA256 为 `4169fd9b96d4671178ded901b0e40e0f7635f658cdb636da3d73fb3d7b1dd3bf`。

固定顺序如下：

1. 获取基线原始截图、SpringBoard 和可选 Preferences PID、进程／线程状态，查询一次 `app-identity com.apple.Preferences`，采集 AX 和 layers。
2. AX 必须包含唯一的 SpringBoard「设置」图标、类名包含 `SBIconView`，预定坐标必须落在图标 frame 内；缺少前提就保留基线并结束。
3. 只点击一次设置。以点击命令返回为起点，在 +0.5、+3、+10 秒调用截图，中间不插入完整状态查询。
4. 最后再采一次进程／线程、AX 和 layers，结束采集。原图逐张审阅后再安排多任务批次。

请求总时限为 150 秒，单次 rsh、截图、状态和 AX 上限分别为 18、20、45、25 秒。传输退出 2／3、嵌套 fetch 传输失败或超时会停止追加请求，并向原 runner 写 `stop-request`；恢复仍由原 device 执行。完整执行有 14 个直接子进程，AX 之外至多 28 条 annsh 命令；AX 的分片数量取决于实际文件，受时间上限约束。

截图目标时刻指宿主调用 `tour.take_shot()` 的时刻，设备采帧与面板呈现时间未测得。调用晚于计划 0.5 秒或错过时点会单独记录。`capture_complete` 仅表示计划截图及其调用窗口满足要求；`foreground_visibility` 保持 `unknown`，多任务保持 `not_covered`，画面结论由原图审阅补充。

该入口只查询 SpringBoard 已安装的 layers 诊断。输出中的 window context 属于其本地窗口，Preferences 的 context 未必出现；无 hosted scene 的进程仍需原生日志与 `process PID`。基线缺少后台 Preferences 时，本轮覆盖设置冷启动尝试，进程是否创建由 after PID 与日志确认；历史后台复用场景继续待验。

## 9. 设置冷启动的固定采集结果

### 9.1 原图与时序

`kernel-12377-codex-1112-cd14-s5-foreground` 轮使用 §8 的诊断候选与冻结脚本，先等待桌面稳定 60 秒，再执行采集。完整采集耗时 107.994 秒，四张图均满足计划调用窗口，未发生传输失败、超时或遗漏时点。原始资料位于该轮的 `docs/progress/evidence/k90auto/` 目录。

四张 BGRA 原始图均已按 `1156×2510` 解码并实际打开原尺寸 PNG。下表的相对时间以点击命令返回为起点，记录宿主调用截图 API 至返回的区间；设备采帧与面板呈现时刻未测得。

| 原始截图 | API 调用／返回相对时间 | 原图可见内容 |
|---|---|---|
| `shot-00744.raw` | `-45.234 / -44.321 s` | 桌面应用与 Dock 图标可见；天气、日历仍为上下浅色条，中间露出壁纸 |
| `shot-01201.raw` | `+0.565 / +1.487 s` | 模糊过渡画面，状态栏和手势条可见，未见设置内容 |
| `shot-01223.raw` | `+3.070 / +3.688 s` | 设置首页标题、账户区、列表和搜索栏可见 |
| `shot-01296.raw` | `+10.062 / +10.984 s` | 设置首页内容继续可见 |

本次诊断配置下的设置冷启动已显示内容。此前黑底画面未在这组采样中复现；诊断请求和日志会改变运行开销，当前无法解释两轮结果差异。原图审阅与文件摘要保存在 Git 忽略的 `docs/analysis/local/s5-foreground-1112/device-review/visual-review.json`；原始 `result.json` 中的 visibility 保留采集器输出 `unknown`。

### 9.2 进程、身份与 scene

- 基线未出现 Preferences；点击后查询到 PID 366，主程序为 `/Applications/Preferences.app/Preferences`，`user_stop_count=0`，`snapshot complete`。主程序路径的 dev／inode 与基线 identity 的当前路径 `stat` 一致。
- SpringBoard 前后均为 PID 32，启动时间、audit token 和路径文件身份一致。
- after 层树中，Preferences scene 为 `valid=1`、`active=1`、`content=2`、`layers=1`、`finishedLaunching=1`、`isPendingExit=0`、`taskState=2`、`isForeground=1`、`activityMode=0`。hosted context 与 scene 客户端 settings 中记录相同 context ID，页面内容已由原图确认。
- after 完整状态查询在点击命令返回后 `+13.780～+41.817 s` 执行，AX 为 `+41.818～+59.533 s`，layers 命令为 `+59.534～+61.725 s`。这些字段描述后续查询阶段，无法还原最初过渡画面的状态。

### 9.3 保留的采集缺口

`app-identity` 返回 1 并保留有效 JSON。LS 的 System 分类、安装与有效状态、FBS 派生身份及路径 `stat` 均可读；`LSApplicationRecord` 的 `bundleInode`、`executableInode` 抛出 unrecognized selector，未获得这两个字段。当前结果不能用于比较 LS record 内部保存的 inode 与路径 inode。

基线 layers 达到 1500 行并标记 `(cut)`；after 为 1493 行，含完整 end 标记。after AX 仅输出「设置」「搜索」两项，完整列表节点未覆盖。两阶段默认 `downloads` 查询均返回 1，其余状态命令的结果逐项保存在报告。

本轮覆盖一次冷启动，后台实例复用、多任务和连续前后台切换仍待按执行计划验证。请求与回应的完整日志时序也尚未逐项核对。下一批先取得历史应用身份与后台启动前提，再对照相同 PID 的激活结果；本轮页面可见结果不用于结束 S5。
