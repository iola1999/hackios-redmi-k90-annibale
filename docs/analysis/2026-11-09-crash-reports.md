# 用户态崩溃报告

[架构审查](2026-11-08-architecture-review.md) §13 建议让 `ReportCrash` 的输出跨重启可取。本文记录 2026-11-09 的核对、根因与修复：写报告的 `osanalyticshelper` 原先因为 XPC activity 登记被去掉而反复崩溃，`userland/mkjobs.py` 保留这部分登记后，默认镜像登记它，崩溃报告写进系统目录并跨开机保留。

## 1. 修复前的现状

- `ReportCrash` 已按需登记（`tools/k90auto/package.py` 的 `ON_DEMAND_JOBS`），开机后以 root 运行。
- 报告文件由 `osanalyticshelper` 代 `ReportCrash` 写出。它的任务在 `userland/mkjobs.py` 的 `DENY` 里（关键词 `osanalytics`），默认镜像没有登记，nearbyd、cloudd 等进程以 SIGABRT、SIGTRAP 退出时不留报告。
- iOS 26 的报告目录是 `/private/var/containers/Shared/SystemGroup/systemgroup.com.apple.osanalytics/DiagnosticReports/`。`/private/var/mobile/Library/Logs/CrashReporter/` 下只有 `Assistant`、`DiagnosticLogs`、`com.apple.appstored` 三个目录。

## 2. 只放行 `osanalyticshelper` 的实测

用 `REST_ALLOW=osanalytics` 打包，其余不变：

- `DiagnosticReports/` 下写出 7 份 `.ips`，有 cloudd、nearbyd、MessagesBlastDoorService 和 `osanalyticshelper` 自己的报告，重启后仍在。另有 4 个以点开头的同格式文件名，按命名看是没有改成正式名字的临时文件。
- `osanalyticshelper` 反复以 SIGTRAP 退出，约 30 秒内 5 次，每次运行 0.3～10 秒；没有报告请求时也会退出。4 个请求同时到达时，有一个建文件失败，返回 EEXIST。
- 日志里的 `DREIsRunningInDeviceRecoveryEnvironment: Failed to determine size of buffer to read OSEnvironment value(Invalid argument). Assuming running in normal mode` 是读 `hw.osenvironment` 得到 EINVAL 后按普通模式继续。
- 用 `systrace=1 systrace_name=osanalyticshelpe` 记录这个进程失败的系统调用：只有特性开关 plist 不存在（ENOENT）和 `csops`／`csops_audittoken` 读 DER 权限时的缓冲区长度探测（ERANGE），没有能解释退出的调用。

## 3. 退出位置与根因

- 内核的 `usertrap` 行和它自己的崩溃报告给出同一个位置：去掉 shared cache slide 后是 libxpc `0x197fbbbd8` 的 `brk #1`，触发前的提示是「XPC API Misuse: Given object not of required type. Given: %s, required: %s.」。
- 调用栈从上到下是 libxpc 的 `xpc_dictionary_get_int64`，OSASubmissionClient 的 `0x2676fbaf0`、`0x2676fbc94`、`0x2676fb11c`，再往下是 libxpc 与 libdispatch 的事件派发。
- `0x2676fbaf0` 的前一条指令以 `XPC_ACTIVITY_DELAY` 为键调用 `xpc_dictionary_get_int64`，对象来自 XPC activity 上的一次取值调用。同一段代码按 activity 状态分支，在 CHECK_IN 状态下取出同一个对象，写入 `XPC_ACTIVITY_DELAY`、`XPC_ACTIVITY_INTERVAL`、`XPC_ACTIVITY_GRACE_PERIOD` 后设回 activity，日志文案是「Submission cadences were unchanged for activity %{public}@」。按调用形态判断，这个对象是 `xpc_activity_copy_criteria()` 的返回值，崩溃时它的类型为非字典对象。
- `osanalyticshelper` 的 launchd plist 在 `LaunchEvents` 的 `com.apple.xpc.activity` 下登记了 `submissions.submit`、`state-monitor`、`daily.telemetry` 等 activity 及各自的 `Delay`、`Interval`、`GracePeriod`。`mkjobs.py --rest` 生成按需任务时去掉全部启动条件，`LaunchEvents` 也在其中，所以 activity 以 CHECK_IN 登记时没有 criteria。

## 4. 修复与真机验证

- `mkjobs.py --rest` 只保留 `LaunchEvents` 里的 `com.apple.xpc.activity`，其余启动条件照旧去掉；`DENY` 删去 `osanalytics`。镜像里带 activity 登记的按需任务有 103 个。
- 先用 `REST_ALLOW=osanalytics` 加保留 activity 的镜像验证，再换成默认打包的镜像，两次开机都到可用桌面。`osanalyticshelper` 开机后一直是同一个进程，日志依次出现 S1～S6 并以 `final result 1` 结束，没有新的 `usertrap` 和 XPC API Misuse，也没有它自己的新报告。
- 报告按进程计数，cloudd 和 nearbyd 各到 25 份后不再增加。OSAnalytics 里有「Report of type '%{public}@(%@)' not saved because the limit of %lu logs has been reached」和 `logLimit_309`，按这两处看是框架自带的条数上限。
- 处理器占用：开机约 5～6 分钟后，90 秒内平均占用的处理器数，验证镜像为 0.17，默认打包的镜像为 0.14，期间新出现 anomalydetectiond、sosd、fitnesscoachingd 等进程；开机后 2～4 分钟的读数在 0.8～1.4 之间，主要是 iconservicesagent。没有在同一时间点量修复前的镜像。

## 5. 遗留

- 开机后反复崩溃的几个进程，按报告和内核 `userabort` 行归类如下。地址减去当次开机的 shared cache slide 后查最近的导出符号；nearbyd、MessagesBlastDoorService 与 cloudd 反编译看过检查条件，airplayd 还没有。

| 进程 | 退出方式 | 位置与线索 |
|---|---|---|
| nearbyd | SIGABRT | 断言 `ConstructRegulatoryTxPowerTableMap`（`roseRegulatoryCompliancePowerTables.cpp` 第 1073 行）失败，下面单独说明 |
| MessagesBlastDoorService | SIGTRAP | Swift `assertionFailure`，调用方是 BlastDoor 的 `Sandbox.initialize(sandboxID:)`。这个函数有两处致命检查：进程没有沙盒时报「BlastDoor cannot run unsandboxed.」，进不了 `blastdoor-post-launch` 状态时报「BlastDoor failed to enter post launch sandbox state」。报告没有带出消息文本，但 `sandboxProfileName` 为空，按这一项判断是第一处 |
| cloudd | SIGTRAP | CloudKitDaemon 在 `dispatch_once` 里初始化时，CloudKit 的 `CKSQLiteDatabase.m` 第 1074 行断言「Exception during database transaction: %@」，即数据库事务里抛出了异常。用 `OSLOG=com.apple.cloudd` 打包后日志给出异常：`-[NSPlaceholderString initWithUTF8String:]: NULL cString`，某个返回 C 字符串的调用返回了 NULL，是哪个调用待查。发起这次事务的是 CloudKit 的建库函数，它先执行 `pragma journal_mode = WAL` 与 `pragma encoding = 'UTF-16'`，再以一个 block 开事务，异常出在这个 block 里。同一进程还打印 `volume does not support data protection, stripping SQLITE_OPEN_FILEPROTECTION_* flags` |
| airplayd | SIGSEGV | 读地址 `0x18` 时 `KERN_INVALID_ADDRESS`，只在验证镜像那次开机看过 |

nearbyd 的断言已反编译确认（`/usr/libexec/nearbyd`）：

- 读 UWB 芯片的函数（`0x100483d38`）先查 MobileGestalt 的 `DeviceProximityCapability`。为真时读芯片 ID（`nhGhVMyvrWYe9U2ltAUImg`），`8198` 记为芯片类型 0，`8228` 记为类型 1；为假时打印「UWB not supported」，芯片类型保持初值 2。
- `ConstructRegulatoryTxPowerTableMap`（`0x100495e08`）先按设备类型分支，再按第二个参数分支，取值 0、1、2 与上面的芯片类型对应。设备类型 26（日志里的 `RoseParameterCache: device type 26`）且这个值为 2 时走 `assert(false)`，就是第 1073 行。
- K90 没有苹果的 UWB 芯片，`DeviceProximityCapability` 为假与硬件相符；按这个分支，nearbyd 在这台设备上每次启动都会断言。怎么处理（不登记 nearbyd，或核对设备类型 26 的来源）待定。

- 4 个请求同时到达时出现过一次 EEXIST，修复后没有再观察。
