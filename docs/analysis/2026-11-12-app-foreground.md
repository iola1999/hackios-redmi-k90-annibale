# 后台应用前台切换核查（2026-11-12）

本批按[执行计划](../plan/2026-11-12-app-foreground.md)核查 S5。当前仅确认历史记录中的后台进程复用与重新启动结果不同，尚未获得同一开机的完整 assertion／scene 对照，应用前台切换根因待确认。

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

先复用已有日志入口。在诊断候选中使用 `applog=1 applog_name=SpringBoard,runningboardd,<可执行文件名>`，按文件名前缀启用 `OS_ACTIVITY_DT_MODE`、`ACTIVITY_LOG_STDERR` 和 `CFLOG_FORCE_STDERR`。构建清单保留原有参数并记录本轮新增项，日志开启后的性能数据只用于该诊断配置。

`xpcwatch` 只统计连接与服务查找，无法给出 assertion 或 scene 消息内容。原生日志仍缺某阶段的请求／回应时，再为缺失阶段增加有限诊断；当前没有修改原生生命周期或 scene 方法。

## 5. 验证状态

用户态实现与测试已提交为 `48e62db`。最终产物及逐文件摘要保存在 Git 忽略的 `hackios-xnu-userland/out/s5-foreground-delivery/manifest.json`；当前设备尚未加载本批诊断。

| 项目 | 已完成 | 待验证 |
|---|---|---|
| `annsh process` | 7 项宿主测试成功，包含真实本进程／子进程／已退出 PID、查询失败、身份变化与端口释放；iOS arm64e 链接、签名检查成功 | K90 目标应用的权限、身份与计数 |
| `ios-state.py` | 8 项宿主测试成功，覆盖 CLI、原查询顺序、普通失败保留、传输失败停止 | 与新 annsh 的设备组合 |
| `ui.py` | 10 项宿主测试成功；旧版同套检查有 8 项失败；既有 tools 39 项、ui-health 8 项成功 | 现场 AX 及截图 |
| scene 扩展 | 12 场景、68 项宿主检查成功；旧版同测有 34 项失败；沿用 `build.sh` 四源文件命令完成 arm64e 链接与签名检查 | SpringBoard 实际缓存对象与画面对照 |
| LS／FBS identity | 7 项实际探针宿主检查及 12 项 ABI／异常辅助检查成功；缺失应用和错误指针 ABI 的消融检查均失败；arm64e 链接与签名检查成功 | iOS 查询权限、注册状态与进程身份对照 |
| S5 行为 | 失败阶段与判据已整理 | 同一应用连续前后台切换的设备验收 |

实现复核保留现有 annsh、rsh 和层树入口，进程信息没有在 LS 工具中重复查询。scene 与 SDF 共用 getter ABI 校验；尚缺的请求／完成记录先通过原生日志采集。三个目标产物独立构建，完整设备候选仍由唯一 device 所属任务按当轮基线装配。

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
