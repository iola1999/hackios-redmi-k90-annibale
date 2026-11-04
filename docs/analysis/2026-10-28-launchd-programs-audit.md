# iOS 26 镜像里「job 在、程序不在」的全量对照

系统镜像里有 `System/Library/LaunchDaemons/com.apple.bluetoothd.plist`，它指向的 `/usr/sbin/bluetoothd` 却不在。这是镜像抽取规则的结果，同类文件不止一个，本文是 2026-10-28 做的全量对照。

## 1. 结论

661 个 launchd job 的程序分布如下：

| 类别 | 数量 |
|---|---|
| 程序在盘上 | 616 |
| 程序在原始镜像里有、抽取时被跳过（§3） | 19 个 job，18 个程序 |
| 程序只在 dyld 共享缓存里、原始镜像的 OS 卷里没有（§4） | 16 |
| 程序写的是裸名字，无法按路径核对（§5） | 8 |
| 没有程序键的配置 plist（§5） | 1 |

抽取流程从不读 launchd plist。它按路径前缀加文件大小挑文件，所以哪些 daemon 能跑，取决于它们的大小和所在目录，与 iOS 是否需要它们无关。三个阈值：`usr/libexec/` 与 `usr/sbin/` 下的程序不超过 10 MB，framework 里 `XPCServices`／`Support`／`Helpers` 下的不超过 32 MB，framework 根目录下的不超过 4 MB。`usr/sbin/bluetoothd` 12,151,072 字节，属于第一类的超限项。

`userland/mkjobs.py` 的 `DENY` 覆盖了表一的大部分：`CommCenter`、`bluetooth`、`locationd`、`backupd`、`audio` 都在 `DENY` 里，所以这些程序缺失目前不影响已登记的任务。要放开其中任何一个，都会遇到同一类缺口，`nearbyd`、`sharingd`、`remindd` 同理。

## 2. 方法

- 工具是 `tools/check-launchd-programs.py`，扫 `System/Library/LaunchDaemons`、`LaunchAgents`、`LaunchAngels` 三处（这个镜像里没有 `LaunchAgents` 目录）。
- 对每个 plist 取 `ProgramArguments[0]`、`Program` 或 `BundleProgram`，先看文件在不在 `ios26/rootfs`，再看路径在不在 `ios26/rootfs.slt`（`7z l -slt` 的技术清单，代表设备上的原始 OS 卷）。
- 判断某个 daemon 在不在盘上，只能读它的 plist 拿到程序路径再去盘上找。按名字猜目录会错：`com.apple.accountsd` 的程序是 `/System/Library/Frameworks/Accounts.framework/accountsd`（88,672 字节），按 `/usr/libexec/accountsd` 找会得出「缺失」。
- 反例核对：已确认在跑的 `linkd`（`/usr/libexec/linkd`）、`appprotectiond`（`/usr/libexec/appprotectiond`）、`accountsd`（`Accounts.framework/accountsd`）、`biomed`（`BiomeStreams.framework/Support/biomed`）全部判为 present。

## 3. 表一：镜像里有、抽取时被跳过（19 个 job，18 个程序）

按触发它的规则分组，大小取自 `rootfs.slt`。

`usr/libexec/` 与 `usr/sbin/` 下超过 10 MB 的程序（`BIG_PROGRAM = 10 << 20`）：

| job | 程序 | 字节 |
|---|---|---|
| `com.apple.locationd` | `/usr/libexec/locationd` | 40,226,848 |
| `com.apple.icloud.searchpartyd` | `/usr/libexec/searchpartyd` | 27,497,168 |
| `com.apple.lskdd` | `/usr/libexec/lskdd` | 21,085,072 |
| `com.apple.lskdP7d` | `/usr/libexec/lskdP7d` | 18,145,952 |
| `com.apple.fairplayd.H2` | `/usr/sbin/fairplayd.H2` | 17,931,488 |
| `com.apple.bluetoothd` | `/usr/sbin/bluetoothd` | 12,151,072 |
| `com.apple.sharingd` | `/usr/libexec/sharingd` | 11,567,744 |
| `com.apple.remindd` | `/usr/libexec/remindd` | 11,426,192 |
| `com.apple.nearbyd` | `/usr/libexec/nearbyd` | 10,878,496 |

framework 的 `Support/` 下超过 32 MB（`size <= 32 << 20`）：`com.apple.CommCenter` 与 `com.apple.CommCenter-noncellular` 两个 job 指向同一个 `/System/Library/Frameworks/CoreTelephony.framework/Support/CommCenter`，35,338,304 字节。

framework 根目录下超过 4 MB（`SMALL = 4 << 20`，非 `Support`／`XPCServices`／`Helpers` 的子路径只按 4 MB 判）：

| job | 程序 | 字节 |
|---|---|---|
| `com.apple.identityservicesd` | `IDS.framework/identityservicesd.app/identityservicesd` | 15,382,336 |
| `com.apple.passd` | `PassKitCore.framework/passd` | 10,566,528 |
| `com.apple.telephonyutilities.callservicesd` | `TelephonyUtilities.framework/callservicesd` | 7,906,144 |
| `com.apple.threadradiod` | `CoreThreadRadio.framework/threadradiod` | 9,600,688 |
| `com.apple.assistantd` | `AssistantServices.framework/assistantd` | 6,496,624 |
| `com.apple.backupd` | `MobileBackup.framework/backupd` | 4,549,904 |
| `com.apple.akd` | `AuthKit.framework/akd` | 4,439,824 |

整个前缀被跳过：`SKIP_SYSTEM_LIBRARY` 里有 `Audio`，`System/Library/Audio/` 下只取 `UISounds/`（`AUDIO` 列出的例外）。`com.apple.usbaudiod` 指 `/System/Library/Audio/Plug-Ins/usbaudio.bundle/usbaudiod`，1,744,400 字节，不在镜像里。

## 4. 表二：只在 dyld 共享缓存里（16 个 job）

这些路径在设备 OS 卷的技术清单里没有，改抽取规则也取不出来，要用就得从共享缓存取出程序再写到盘上。

- App cryptex（`/System/Cryptexes/App/...`，这个镜像里没有那个卷）9 个：`AuthenticationServicesAgent`、`com.apple.Safari.History`、`passwordbreachd`、`SafariBookmarksSyncAgent`、`webbookmarksd`、`browserkitd`、`safarifetcherd`、`webinspectord`、`webpushd`。
- OS cryptex（`/System/Cryptexes/OS/...`）1 个：`com.apple.webkit.adattributiond` 指 `WebKit.framework/Daemons/adattributiond`。
- OS 卷命名空间里但清单没有的 6 个：`/usr/local/bin/cellularcertd`、`/usr/sbin/sntpd`、`/usr/sbin/dietapplecamerad`、`DeviceInterface.framework/Support/deviceinterfaced`、`HealthContent.framework/healthcontentd`、`RealityCamera.framework/realitycamerad`。

## 5. 另外几类

- 8 个 plist 的程序是裸名字，launchd 按路径 spawn，这类 job 能否启动要看 launchd 是否在别处补全路径：`OTACrashCopier`、`aslmanager`、`assetsd`、`cloudphotod`、`ftp-proxy`、`com.apple.photos.ImageConversionService`、`com.apple.photos.VideoConversionService`、`CoreServices/ScreenSharingServer.app/ScreenSharingServer`（最后一个是相对路径）。
- 1 个 plist 没有程序键：`com.apple.jetsamproperties.V57.plist`，是配置项。
- 策略上排除：`com.apple.duetexpertd`（`/usr/libexec/duetexpertd`，98,672 字节，33 项 `MachServices`，其中 `com.apple.proactive.HomeScreenSuggestion.xpc` 与 `com.apple.proactive.SuggestedPages` 与桌面建议相关）程序在盘上，在 `mkjobs.py` 的 `DENY` 里，不进本文的缺口统计。

服务名与 job 名不同时容易误判成缺口：

- `com.apple.duetactivityscheduler` 没有以它命名的 plist，它是 `com.apple.dasd` 的一项 `MachServices`（程序 `/usr/libexec/dasd`，2,572,640 字节，在盘上）。
- `com.apple.coreduetd.context` 由 `com.apple.contextstored` 提供（`CoreDuetContext.framework/Resources/contextstored`，106,256 字节，在盘上）；`com.apple.coreduetd`（`/usr/libexec/coreduetd`，361,696 字节，在盘上）提供的是 `knowledge`、`people`、`pairedsync` 这另一组名字。
- 判定某个服务缺不缺，要先把每个 plist 的 `MachServices` 列全再反查，`tools/check-launchd-programs.py --service NAME` 做的就是这一步。

## 6. 抽取规则在代码里的位置

`ios26/select-system.py` 是 `ios165/select-system.py` 的链接。`wanted_file()` 的入参只有路径与大小，没有任何一处读 launchd plist 或 daemon 名字。

- `BIG_PROGRAM = 10 << 20` 只看 `usr/libexec/` 与 `usr/sbin/`。
- `SMALL = 4 << 20` 与 `wanted_file()` 里的 framework 分支决定 framework 内的程序。
- `SKIP_SYSTEM_LIBRARY` 列了 `Audio` 等整个前缀，`AUDIO` 列出其中仍要取的目录。

## 7. 改抽取规则的代价

- 放宽阈值会改变 `system26.apfs` 的内容与哈希，要重做系统盘和 Android DSU 里那份，之前各轮的读数也不能直接对比。
- 表一的 18 个程序里，`bluetoothd` 是目前唯一要用的，处理见[蓝牙接入](2026-11-02-bluetooth-bringup.md) §1。
- 表二的 16 个要从 dyld 缓存取出程序再写到盘上，比改阈值改动大。

## 8. 打包时的检查

- `tools/k90auto/package.py` 检查 `/redwood/LaunchDaemons` 里程序在 `/redwood/` 下的 job：程序必须在打包的根盘里，缺一个就让打包失败，报错给出 plist 名与程序路径。
- 程序在 `/usr`、`/bin`、`/System` 下的 job 来自系统盘，`package.py` 不打开系统盘，这部分用 `tools/check-launchd-programs.py` 对系统盘检查。

## 9. 待确认

- 表二的 16 个里，`WebKit.framework/Daemons/adattributiond` 只在 OS cryptex 里；两个 cryptex 卷是否被内核挂载、挂在哪，没有查。
- `fairplayd.H2` 在 18 个缺口内，它的缺失有什么影响没有验证。
- 8 个裸名字的 job 里有没有真在跑的，没有查。
- 本文的数字按 2026-10-28 的规则得出。`select-system.py` 改动后要重跑 `tools/check-launchd-programs.py` 才知道缺口有没有变。
