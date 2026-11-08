# 用户态崩溃报告

[架构审查](2026-11-08-architecture-review.md) §13 建议让 `ReportCrash` 的输出跨重启可取。本文记录 2026-11-09 的核对结果：`/private/var` 本身已经跨开机保留，但设备上目前没有生成崩溃报告。

## 1. 现状

- 开机后 nearbyd、cloudd 等进程反复以 SIGABRT、SIGTRAP 退出，`/private/var/mobile/Library/Logs/CrashReporter/` 下只有 `Assistant`、`DiagnosticLogs`、`com.apple.appstored` 三个目录，没有 `.ips` 文件。
- `ReportCrash` 已按需登记（`tools/k90auto/package.py` 的 `ON_DEMAND_JOBS`），开机后以 root 运行。
- 报告文件由 `osanalyticshelper` 代 `ReportCrash` 写出，它的任务在 `userland/mkjobs.py` 的 `DENY` 里（关键词 `osanalytics`），没有登记。

## 2. 放行 `osanalyticshelper` 的实测

用 `REST_ALLOW=osanalytics` 打包，其余不变：

- `osanalyticshelper` 被 `ReportCrash` 的请求拉起，日志依次是 `helper service invoked for '309' report creation on behalf of ReportCrash`、`helper service creating file`，随后以 SIGTRAP 退出。约 30 秒内退出 5 次，每次运行 0.3～10 秒，没有写出 `.ips` 文件。
- 退出前还有一行 `DREIsRunningInDeviceRecoveryEnvironment: Failed to determine size of buffer to read OSEnvironment value(Invalid argument). Assuming running in normal mode`，按这行的字面意思，它在这一步按普通模式继续。
- 用 `systrace=1 systrace_name=osanalyticshelpe` 记录这个进程失败的系统调用：只有特性开关 plist 不存在（ENOENT）和 `csops`／`csops_audittoken` 读 DER 权限时的缓冲区长度探测（ERANGE，缓冲区不够长时的常规返回；systrace 只记失败的调用，看不到之后的重读）。没有能解释这次退出的失败调用。

## 3. 结论与下一步

- `osanalytics` 继续留在 `DENY`，放行后它反复崩溃，也写不出报告。
- 下一步要找到 SIGTRAP 的位置。SIGTRAP 一般来自用户态的断言或运行时检查，可以用 idalib 反编译 `osanalyticshelper` 与 OSAnalytics 框架里报告落盘的路径，找出「creating file」之后检查的条件，再确定它依赖内核或文件系统的哪一项回答。
