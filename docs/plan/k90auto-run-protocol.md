# k90auto 真机轮运行规则

本文记录真机轮的载荷记录、轮次目录与收尾、计数口径、日志容量和失败处理，`tools/k90auto/` 与 `tools/round-stats.py` 按这些规则实现。命令与参数见 [k90auto 说明](../../tools/k90auto/README.md)，设备安全约束见 `AGENTS.md` §5，收尾路径的实测见[无人值守收尾](../analysis/2026-10-28-unattended-teardown.md)，排查方法见[排查与协作手册](debugging-and-collaboration.md)。

## 1. 设备访问与一轮的设计

- 同一时刻只允许一个 fastboot／adb 客户端：两个客户端同时 `getvar` 曾留下未终止的 IN 请求，只能复位恢复。设备命令都带序列号，枚举类也带。
- 一轮只改一个变量，起轮前写下变量、能回答问题的日志行和判据。其他变化（换库、换内核、换探针）用 `ROUND_NOTES="变化一;变化二"` 打包，写进 manifest 的 `round_notes`。
- 性能轮的手势要落在会重绘的界面上，静止的主屏不重画。轮次时长属于验收口径，不随故障缩短。
- `rc.jobs` 由 `init.c` 的 `run_rc()` 逐行执行，每行 `wait4` 等它结束，行尾 `&` 只 fork。整轮都要运行的探针和采样放在文件最前，放在末尾会等手势跑完才启动。

## 2. 载荷记录：这一轮跑的是什么

- `make-payload.py` 在 `docs/progress/evidence/k90auto/kernel-<NAME>-<LABEL>/manifest.json` 写下 payload、根盘、系统盘的字节数与 SHA-256，把打包记录抄进 `pack` 段，并断言 `root_sha256` 等于根盘哈希、`gpu_speed` 与 cmdline 的 `adreno8_speed` 一致。manifest 不手改。
- `pack` 回答这一轮的六项构成：内核 `kernel`、驱动 `driver_sha256`、AIR 库 `air_sha256` 与 `air_sources`、作业 `jobs_effective` 与 `jobs_dropped`、手势脚本 `jobs_source`、探针 `probe_sources`。作业集合只读 `jobs_effective`（从 launchd 缓存读回）；`JOBS_DROP` 只用于一轮内临时排除。
- 工作树状态只记录、不阻止打包：`package.py` 查 `common/ugit status --short` 和顶层 `tools/k90auto`，写进 `worktree_status`。两个库每次从工作树重编，未提交改动会进驱动；`touch` 不改内容，`status` 看不出来。
- manifest 记的是应该跑什么，从 apfs 解出的文件是实际跑了什么，不一致以 apfs 为准。内核以 `kernel` 段哈希为准，HEAD 号只说明从哪份源码起编。
- AIR 库记源码摘要（`air-build-record.json` 的 `source_sha256:<文件>`、`tree_sha256:<文件>`）和库的 sha256。同一棵树重链得到的库 sha 可复现，库 sha 不同说明构建输入有摘要没覆盖的差异。
- 配方对账两层：pack 字段与本轮配方逐项对，不设的开关写出依据（`package.py` 漏设开关不报错，只让镜像多或少一个文件）；`changes` 里每个 `null→sha` 新增条目归到 `EXTRA_JOBS`／`PROBE`／`PAYLOAD_PROGRAMS` 之一，归不到的就是缺口。
- 载荷构成变了，用 `image-diff.py` 把新镜像与上一轮实际跑过的镜像逐条目比较。`package.py` 的断言以基础镜像为参照，查不出本来就不在基础镜像里的文件消失：round F 漏设 `PAYLOAD_PROGRAMS`，镜像缺 `framewatch`，断言全过，整轮采样为零。
- `run-auto.py` 起轮前按 manifest 重算哈希，不一致拒跑，日志第一行是 `GUARD payload=<前 16 位> root=<前 16 位> dir=<目录名>`；`run/` 非空也拒跑。打包每次重建 `root.apfs`，旧轮次目录不能重跑，要重建载荷。
- `build-air.py` 不带 `--check` 会就地覆盖 `bbmetal-device/libredwoodair.dylib`，三个同名库与构建路径见 [arm64e 构建路径](../analysis/2026-10-28-arm64e-userland-build-path.md)。

## 3. 改了但没生效

改动落在一处、生效点在另一处时，源码改过说明不了产物。每处改动都从产物读回来验证：产物里相关串 `grep -c` 非零，或 apfs 解出的文件与新编译的哈希一致。实例：

- `userland/build.sh` 里 `obj/libredwoodmetal.dylib` 的编译在 `if [ -d $IOS/rootfs/usr/lib ]` 与 `if [ -z "$PREBUILT" ]` 之内，拷进 `root/lib/` 在两层之外。`IOS` 默认 `../ios165`（本机没有 rootfs），`ld64` 不在 `PATH` 时 `PREBUILT` 自动置 1，任一情形都跳过编译、照常装箱，10 月 23 日的驱动因此进了 10 月 28 日的镜像。`build.sh` 现在装箱前断言目标文件比源文件新。
- 改了 `build.sh` 追加进 `var.skel` 的行，不重跑 `build.sh` 不进载荷。
- `build-air.py` 曾漏复制 `air_to_nir.c`，构建读的是树里的旧副本且不报错；复制清单本身也要断言。
- `package.py` 的 `add_diag` 曾只改内存缓存、没写回 `xpc/launchd.plist`。
- `bsd/conf/files` 有那一行而文件没编进去；内核提交落在 `out/xnu12377` 而不在顶层仓。
- 追加到 `rc.jobs` 的行因上一行缺换行符，被拼进了同一行。

四处源码与产物可能不同步的位置各有判法：

| 位置 | 怎么判断过期 |
|---|---|
| `build.sh` 追加的骨架行 | `package.py` 比对 `userland/var.skel.extra` 与打包根的 `etc/var.skel`，缺行时补上并打印 `rerun userland/build.sh`，manifest 的 `skeleton_appended` 非空说明基础根旧了 |
| 内核 | `make-payload.py` 用 `kernel.json` 的 sha256 核对内核文件 |
| AIR 副本 | `package.py` 比对库与 `air-build-record.json` 的 `library_sha256`；`PAYLOAD_AIR_STRINGS` 的格式串不在库里也失败 |
| plist 拷贝 | `tools/k90auto/jobs/*.plist` 会被 `add_extra_jobs` 改写，没有自动判据，手工与 `ios26/rootfs/System/Library/LaunchDaemons/` 的原件比 sha256 |

- 新增的日志行编进内核之前，它没有出现不能用来下结论。
- 判某段代码在不在树里看符号存在与否，不看出现次数；`.rej` 只说明某块没打上，那块的能力可能由另一条补丁提供。
- 说明性文字写进文档，不写进补丁头：`tools/mesa/*.patch` 的正文参与 `.redwood-patches` 的哈希，改一行注释就会让 `mk-mesa.sh` 重打补丁链、重编整个库。

## 4. 轮次目录与固定收尾

- 轮次目录 `docs/progress/evidence/k90auto/kernel-<NAME>-<LABEL>/`（Git 忽略）含 `manifest.json` 与 `run/`：`s###.log` 快照、`shot-#####.raw` 截图、`commands.jsonl`、`reboot.json`。
- 性能轮收尾跑 `summary.py --verify`、`summary.py --markdown`、`gestures.py` 和 `tools/round-stats.py`，参数都是轮次目录；`cycle.py` 另写 `render-report.txt`。
- `--verify` 检查快照并集等于合并结果且无重复，非 0 时本轮不计成功。所有快照都缺同一段时它照样通过，覆盖看 `coverage:` 行。
- `reboot.json` 的 `left`、`reset`、`seconds`、`mode` 说明收尾路径，`logs` 记各日志字节数，`shots` 是截图张数，`frozen` 记冻结时的帧号与空档。判断跑完看 `run-*.log` 的 `SAMPLED_SECONDS` 是否约等于设定时长。
- 一轮收尾前不读它的目录，读了标 `partial, through s0NN`。
- 截图与快照间隔：`run-auto.py` 默认 `0,100,20`（不截图、每 20 秒一份日志），`run-queue.sh` 默认 `3,100,20`，`cycle.py` 传 `0,0,5`。一张截图约 11.6 MB，和日志共用 USB 通道。按需截图用 `shot-now.py`，文件名 `shot-{int(elapsed*10):05d}.raw`（`shot-01002.raw` 是第 100.2 秒）。
- 冻结即收尾：桌面出现后连续 `K90_FREEZE_SECONDS`（默认 20）秒无新帧，打 `FROZEN_AT <elapsed>` 并收尾；`K90_FREEZE_OFF=1` 关闭，`cycle.py` 默认关闭。
- 等一轮结束用 `wait-round.py`，等一个动作的现场用 `action-probe.py`，不用固定 `sleep`。
- 检索只按文件点名读 `run/s0*.log` 这类文本（`AGENTS.md` §6）。BSD grep 的内存约为最长无换行段的 3 倍；带上下文窗口的正则在 14 MB 的 `libredwoodair.dylib` 上比 `-F` 慢 79 倍。多 GB 镜像先 `strings` 或流式 `bytes.find`。

## 5. 计数与判读口径

报出去的行数一律用 `tools/round-stats.py` 的输出，`round-gate.py` 用同样的文件集合和去重规则。

- 文件集合只有 `run/s[0-9]+.log`。`summary.py` 的 `merged_log()` 还读 `returned.log`、`hung-held.log`、`running.log`，两套数不一致以 `round-stats.py` 为准。
- 快照故意重叠，计数前按整行去重，默认报唯一行数；跨快照求和只能判断出现过没有（逐份 `grep -c` 曾把 86 行数成 1,516）。行数与串出现次数分开报。
- `Code=4099` 按服务名计数：两轮总数相近，分开后 `com.apple.coreduetd.context` 是 3→0。
- 帧 id 用 `^tl: v (\d+)`，`done` 只用于判断帧是否落在触摸区间；交换提交用 `^tl: s (\d+) \S+ at (\d+)$`。帧洞从帧 id 和 `tl: s` 判断，不用 `ready` 间隔：同一批帧的 `ready` 集中在很窄的区间里，会把空档前的一批帧算进空档。
- 触摸样点 `tl: p TYPE FINGER X Y at US`：TYPE 1 按下、2 移动、3 抬起，坐标 0～65535。`tl: p` 与 `served as a copy` 只在 2 的幂次打印（`RW_AGAIN`），条数只说明发生过；次数读 `kern.redwood.frames` 这类不节流的计数器。
- 报 0 前先列文件清单，没有文件与 0 行是两个结论；以 0 作否定写明覆盖时段，零命中附 `ring coverage`。
- 报缺失写出完整匹配串和位置：`installd[` 与 `[installd]` 是两个串。拿行数当调用次数前读完整的一行：`grep -c "resolve "` 曾把一句警告算成 354 次 resolve。
- 比较两轮的绘制计数前，用 `screens` 段确认两轮停在同一界面（亮样本比例 `<0.005` 黑、`>0.10` 主屏、其余锁屏）。截图读数写清是整轮还是某个窗口。
- 累计量先除以次数再算占比，平均值同时给中位数。窗口内命中数要和窗口外同样长窗口比较（`commit has run for` 这类高基率告警任何 3 秒窗口都会命中）。时刻重合只说明同时出现，因果需要能单独移除其中一个的对照。
- `cpufreq:` 的 `in 30 s:` 是 30 秒窗口直方图，`hot ticks N of …` 是热段内直方图，按 domain 分开读。
- 帧间隔落在显示节拍整数倍上（60 Hz 时 16.67 ms，`fb_hz=120` 时 8.333 ms）是分频，要看间隔分布。
- `fps`（整轮）、`fps_mv`（排除不小于 90 ms 空档）、`static`（静止占比）都受静止期影响，不跨轮比较；排轮次和验收用 `gestures.py` 的手势口径。
- 读帧率前先看 `coverage:` 行：跨度不足轮次时长一半只报局部值，识别到的手势少于注入次数报「样本不足」。`round-gate.py` 六条判据（触摸覆盖帧流、单次触摸 30 秒以上、其中至少 1650 帧、手势数等于注入数、帧 id 无跳变、交换间隔不超过 1.5 秒）任一不满足，结论也写「样本不足」。
- `memorystatus_perform_idle_demotion() timed out stuck process N [name]` 只说明进程跨过两个 aging 期限仍未 idle，服务空闲时也会出现（58 个轮次目录里最干净的一轮也有）。被判进程属于 `pkd`／`extensionkitservice`／`iconservicesagent` 时 `--verify` 打 `registration:` 行，该轮帧率只作参考。补服务类改动看效果：`containers_entries=` 非 0、某个服务的 `Code=4099` 归零。

## 6. 日志环容量与快照频率

- 内核日志区是 263,349 字节的固定头加 1,048,576 字节的滚动环，单份快照最大 1,311,925 字节（roundb、round C、round D 实测）；`round-stats.py` 的 `RING_BYTES = 1024 * 1024` 是环的大小。头与环的接缝落在一条日志行中间，按轮次实测，拼接在这一处对不上是正常的。
- 环能装多少秒随插桩量变化，以 `ring coverage` 段为准：bbm29 的环里 `tl:` 占 63.1%、驱动打印 8.7%、iOS 日志不到 10%，单份约装 15～20 秒；`freeze` 轮约 178 秒。
- 快照间隔要短于单份环能装的时长。零命中可采信要同时满足：单份环时长大于快照间隔，快照并集覆盖要排除的时刻（按 `tl:` 基线对齐）。
- 拉长历史只能调大 loader 侧的环或减少插桩，改环要同时改内核与 loader 的内存布局；`oem logwrite` 写到 `boot_a` 开头，与日志容量无关。
- 开机后头几十秒的事从控制台日志取不到（日志 65 KB/s 时，`launchd` 开机 0.5 秒的行在第一次快照前就被覆盖）。进程是否被拉起这类判据由探针在运行时读取（`PROBE=1` 的 `lsprobe`），日志里没有记成「该轮未保留」。

## 7. 符号化 pc 走 stub 的系统调用号

`libsystem_kernel` 的 stub 是 `mov x16,#imm` 加一条 `svc`，取立即数查内核的 `mach_trap_table` 与 `syscalls.master` 得到系统调用名，不按偏移猜名字；slide 为 `0xffffffff` 表示该任务没有设置过，`pc` 不可读。工具是 `tools/k90auto/stubsym.py`（`e566027`），解码与按 `.46` 子缓存 mapping 表定位文件偏移的办法写在它的 docstring 里。2026-10-28 用它读出的六个主导 `pc` 全是 `mach_msg2_trap`、`ulock_wait` 这类普通阻塞调用。

## 8. 失败与重试

不需要停下的情形：

- 复位后落到 B 槽 Android：`run-queue.sh` 和 `cycle.py` 调 `recover-loader.py`，在 40 秒内等 adb，确认唯一一台 B 槽 annibale 后经 LK `set_active a` 回到 loader。
- 开机约一秒就 panic 返回（early startup 的 UBSAN trap，或 `ml_get_max_cpu_number()` 断言）：`round-run.py` 把上次的 `run/` 移到 `run-attempt-<n>/` 重跑，`K90_PANIC_RETRY` 默认 3 次。
- 快照缺一两份而收尾正常，本轮有效。单条 `getvar`／`oem log` 超时一次，可手动重试该命令，最多 2 次。

停下处理，不重跑：

- loader 未枚举、`result` 不为 idle 或序列号为空，以及需要按键、切槽、重刷：按 `AGENTS.md` §5 停手并报用户。
- `--verify` 不过且重拉一次快照仍不过：先修合并或采集工具。哈希与 manifest 不符、打包或编译失败同样先修。
- 同一路径连续失败 3 次：换测法或改代码后再排。失败签名对这一代载荷是新的：先在历史轮次里按文件点名搜同一签名，没有先例就先分析、写下重试理由，再消耗下一次启动。

收尾、失联与 panic：

- 任何 panic 交还 loader 时，`adreno8_quiesce()` 在需要复位或内存仍被保留时进入 `wfe` 循环，所以 panic 后设备停在 `hung-held`、要主机冷复位。loader 在内核静默满 50 秒后才报 `hung-held`，`run-auto.py` 在 `oem stop` 后按秒轮询（`K90_STOP_WAIT` 默认 70 秒），保存日志再复位。
- 起轮断言只看 `result` 是否 idle，`fresh_loader()` 还要求 `ramdisk-state` 匹配 `idle 0 0 `，收尾验证按后者。
- 中途失联先拉取日志环再发 stop，环可能被覆盖或随 stop 丢失。`liveness-watch.sh` 查 `commands.jsonl` 的 mtime，停滞 150 秒写 `LIVENESS-ALERT`。中途结束一轮要确认 python 子进程已退出（round F 曾在结束队列后子进程又运行约 4 分钟），再收尾到 fresh idle。
- `EXC_GUARD`（namespace 23）的 flavor `0x43`（`RESTRICT_OOL_PORT_ARRAYS`）可用 boot-arg `ool_port_array_enforced=0` 关闭；`0x7`、`0x9`、`0xa`、`0x42` 只能改 `ipc_policy.c` 的策略表。
- 自己加的检查阻止了一轮真机测试，就用放行开关或删掉它，在该轮说明里记一行（阻止了什么、怎么放行、原本要查什么），不停下来等。

## 9. 长跑轮（静置观测）

- 超过一小时的轮次排在一批最后，开跑后不再安排其他真机任务；保持一轮不结束用 `cycle.py --hold --seconds N`。
- 时长按要覆盖的事件定：`[timeline.store]` 把扩展身份重试排在开机后 1 小时，观察它要 4200 秒以上。
- 只解锁、不跑手势循环；需要屏幕不灭时每 20～30 秒点一次状态栏。
- 温度护栏：`cpufreq=1` 的 30 秒窗口 `hottest` 连续两次超过 78 °C 立即中止，记录温度、时刻与已跑时长，按有效结果入库。
- 静置段日志约 2～7 KB/s，快照间隔 180 秒。判据以日志为准，静置轮的帧率与手势数字不引用。
