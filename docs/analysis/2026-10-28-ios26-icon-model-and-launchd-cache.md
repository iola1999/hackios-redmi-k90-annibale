# 桌面只有 2 个图标：启动参数丢了 launchd 缓存（2026-10-28）

2026-10-28 的 iOS 26 桌面只有 2 个图标、Dock 为空、小组件停在 `Waiting…`。原因是载荷的启动参数少了 `rootdev=md0 launchd_unsecure_cache=1`，launchd 没有收到 `/System/Library/xpc/launchd.plist`。本文记录这条回归的判断依据、iOS 16.5 与 iOS 26 任务集的差集，以及排查登记问题用的探针与统计口径。

10-31 另有一种开机后图标不出现的情况，原因是每次开机 `/private/var` 都是空的，见[每次开机都是首次开机](2026-10-31-every-boot-is-first-boot.md)。

## 1. 结论

- 回归来自启动参数：从 `bbmetal17` 那轮起，载荷不再带 `rootdev=md0 launchd_unsecure_cache=1`。iOS 26 的 launchd 因此没有收到任务缓存，缓存里 733 条 `AppExtensions` 一起丢了（§3）。
- 补回两个参数后（`bbm29`），桌面完整：15 个应用、2 个带名字的小组件、4 个 Dock 图标、2 个页码圆点。
- 缓存缺失能直接解释扩展相关的现象：没有 `AppExtensions` 就没有 `.appex` 宿主进程，chronod 只能报 `Extension not found`，小组件停在 `Waiting…`，壁纸的 posterkit provider 走同一条路。缓存里没有应用清单，图标数从 15 降到 2 的机制没有单独分析。
- 守护进程数量不是桌面内容的决定项。同一份根盘（`33ed5fc9`）、同一份 `system26.apfs`（`d11083be`）、同样 27 条任务的 2026-10-27 12:40 那轮，桌面是 15 个应用、2 个带名字的小组件、4 个 Dock、Search 胶囊。
- 防止再丢：`tools/k90auto/make-payload.py` 把这两个参数写在固定 cmdline 里，最终 cmdline 缺任何一个就断言失败，并把 `required_cmdline` 写进 manifest。

## 2. 差集：16.5 的 388 条与 26 的 31 条

16.5 那份 working payload 的 job 生成走 `userland/build.sh` 的 `IOS_JOBS` 加 `mkjobs.py --rest`。`--rest` 只有 `REST=1` 时才生效，默认不带。

- 默认的 `IOS_JOBS` 是 21 条（`notifyd`、`cfprefsd`×2、`logd`、`syslogd`、`distnoted`、`diagnosticd`、`fseventsd`、`containermanagerd`×2、`runningboardd`、`backboardd`、`mobile.usermanagerd`、`mobilegestalt.xpc`、`lsd`、`powerd`、`analyticsd`、`logd_helper`、`iconservicesagent`、`pluginkit.pkd`、`SpringBoard`），加 `wifid` 是 22 条。
- `--rest` 把 491 个 LaunchDaemon 与 12 个 LaunchAngel 里剩下的、带 MachServices 且程序在盘的全部加上，产物是 388 条。

出处是 `docs/progress/evidence/2026-10-25-codex-gpu-resume/kernel-queue-wait-s23-auto-default/run/s002.log`：启动时会打印 `/redwood/LaunchDaemons` 的内容，去重后 388 个 `.plist`。同一份日志里 `com.apple.mobile.installd` 是 `launching: ipc (mach)` 拉起在 `user/501` 域，它不在那 21 条显式清单里，是被 `lsd` 或别的进程查找时才启动的。`--rest` 保留 MachServices、删掉 `RunAtLoad`／`KeepAlive`／`StartInterval` 与其余启动触发器，所以「388 条」只说明登记条目数，说明不了同时运行的进程数。

2026-10-28 时 iOS 26 侧跑 31 条：`build.sh` 的 23 条（21 条加 `systemstatusd`、`wifid`）加 4 条 `com.redwood.*` 加 `package.py` 的 4 条（`chronod`、`PosterBoard`、`replicatord`、`mobile.installd`）。把同一份 `mkjobs.py --rest` 套 iOS 26 的 628 个 LaunchDaemon 与 32 个 LaunchAngel，得到 535 条。

这条差集成立，但 26 上桌面空另有原因（§1）。缺少的服务后来造成了处理器占用，`package.py` 现在默认 `REST=1`，按需登记其余任务，见[开机后的处理器占用与 launchd 任务集](2026-10-31-launchd-jobs-and-boot-cpu.md)。

## 3. launchd 缓存与启动参数

- iOS 26 的 launchd 不扫描 `LaunchDaemons` 目录，任务与扩展记录都来自 `/System/Library/xpc/launchd.plist`。这份缓存由 `userland/mkcache.py` 用我们的任务表生成、不签名。`launchd_unsecure_cache=1` 让 `launchd_cache_loader` 跳过签名校验直接把它送进去（`mkcache.py` 的文件头写了这条）。
- `launchd_cache_loader` 读 `kern.bootargs`，读到 `launchd_unsecure_cache=` 就打 `Using unsecure cache: %s`，否则走 `SecStaticCodeRef` 加 AMFI 的信任缓存校验。
- 参数在场时日志有三行：`launchd_cache_loader Doing boot task`、`Using unsecure cache: /System/Library/xpc/launchd.plist`、`Cache sent to launchd successfully`。
- 参数缺失时这三行都没有，`Skipping boot-task` 一轮 1000 条。日志里也没有 `Code: …Sig: …`、`cdhash`、`Trying to send bytes` 这些签名路径的输出，loader 在更早的分支就退出了，具体分支没有读。
- `AppExtensions` 是缓存里唯一与扩展有关的键，733 条。`Symlinks` 只有 2 条且都指向 framework 里的 dylib，`SystemLibraryTreeState` 是 framework 清单，两者与图标数无关。
- 参数丢失的时间：按 `manifest.json` 的 `epoch` 排序，在 2026-10-27 16:05 到 16:46 之间。当时 `make-payload.py` 的固定 cmdline 里没有这两个参数，要靠调用方写进 `EXTRA BOOT-ARGS`，没有哪次提交删掉它们。

## 4. 探针 `lsprobe`

- 源码 `hackios-xnu-kernel/userland/src/lsprobe.m`。`PROBE=1` 时 `package.py` 把它编成 `/bin/lsprobe`，并在 `etc/rc.jobs` 开头加两行 `/redwood/bin/lsprobe 60 &` 与 `/redwood/bin/lsprobe 300 &`。它只读，不改系统镜像。
- 两行必须在文件开头且以 `&` 结尾：`init` 逐行执行 `rc.jobs`、每行等结束，追加在手势脚本之后的探针要等手势跑完才启动。
- 打印内容：`LSApplicationWorkspace allApplications` 的应用数与每个 bundle id（括号里是那个 proxy 携带的扩展记录数）、`MobileInstallationLookup` 的条数、`/Applications` 与 `/private/var/staged_system_apps` 的目录项数、`/private/var/mobile/Library/MobileInstallation` 的目录项数、`/private/var/mobile/Library/SpringBoard/IconState.plist` 是否存在，以及进程表与各进程的处理器时间。

## 5. 服务查找失败的统计口径

- 判据是日志里 `Code=4099`（`The connection to service named X was invalidated`）的服务名。报数用 `tools/round-stats.py` 的输出，它按行去重后再按服务名分组。把 `s0xx.log` 重叠快照直接相加会虚高 3 到 4 倍。
- 两类 4099 要分开：`The connection to service named com.apple.X` 是 launchd 查找失败，与登记有关；`The connection to service created from an extension was invalidated` 是扩展连接断开，每行带扩展名，是扩展进程起了又退出的旁证。
- 服务名与 job 名常常不同。`com.apple.duetactivityscheduler` 由 `com.apple.dasd`（`/usr/libexec/dasd`）提供，`com.apple.coreduetd.context` 由 `com.apple.contextstored`（`CoreDuetContext.framework/Resources/contextstored`）提供；`com.apple.coreduetd` 自己提供 knowledge、people、pairedsync 那一组。
- 判断程序在不在盘上，按 plist 的 `ProgramArguments[0]` 去 `ios26/system.manifest` 与抽取出来的 `ios26/rootfs` 上找，不按名字猜目录：`accountsd` 的程序在 `Accounts.framework` 根目录下，按 `/usr/libexec` 找会误判成缺失。完整的「job 在、程序不在」对照见 [launchd 程序审计](2026-10-28-launchd-programs-audit.md)。
- `com.apple.linkd.registry` 在 `biomed` 那一轮占去重后 4099 行的 88%。`linkd` 的 `LaunchEvents` 监听 LaunchServices 的应用注册／注销通知，开机头几秒约有 259 个应用注册，每次通知都可能唤醒它；整轮里 `linkd[pid]` 的 pid 反复变化时，说明它在被反复唤醒又回收。
- `package.py` 的 `EXTRA_JOBS` 按需登记了 `biomed`、`linkd`、`contextstored`、`dasd`、`appprotectiond` 与 `ReportCrash`，各自对应的服务与理由写在 `package.py` 的注释里。
