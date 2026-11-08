# 根文件系统：从 UFS 挂载系统卷

系统卷放在 UFS `darwin` 分区，由内核 APFS 驱动按需读取。启动阶段的 `md0` 只放小型 `flashboot.apfs` 引导卷中的 `stage0` 与挂载目录，辅助盘 `md1` 放本项目的程序、驱动与固件。系统镜像不再整体读入 loader 常驻区，`/private/var` 由内核直接写入 UFS `darwin_var`。2026-11-08 临时启动和刷入 `boot_a` 后重启均已完成真机切根，启动卷常驻长度为 4 MiB。

## 1. 近期提交与审查结论

- 内核 `e8b499c` 与顶层 `bc20def` 加入 DSU 系统镜像读取：loader 把整个镜像读入常驻内存。
- 内核 `08170b1` 把独立启动镜像接到 `darwin` 分区，`rdfile` 仍把整个系统镜像读入内存。
- 内核 `9657ff3` 实现 `/private/var` 文件数据直写 `darwin_var`、按需读入数据页，以及双 32 MiB 元数据槽位；用户态 `fcaf0f5` 接入 UFS 系统卷切根并移除定时归档任务。这两笔提交已有落盘实现，但当时 standalone 和自动跑轮仍使用完整系统镜像的常驻内存路径。
- 2026-11-08 的只读查询得到 `ramdisk-state: ready 160bc1000 160bc1000 300000000`：常驻镜像为 5,917,904,896 字节，约 5.51 GiB。这段内存位于交给 XNU 的窗口内，布局将其纳入 `topOfKernelData`，启动后占用内存。
- 同次真机日志确认 XNU 正在运行，系统卷仍由 `rdfile` 全量载入；`/private/var` 已从 UFS 恢复。旧 loader 的 standalone 入口遗漏 `running` 状态更新，导致 `getvar result` 错报 `idle`；本轮将更新放到共同的内核运行入口。
- 当前工作树的 `annibale` loader 已拒绝 `rdfile` 载荷；主机端 `make-payload.py` 和 `mkstandalone.py` 也禁止自动流程携带该入口。QEMU 仍保留 `rdfile` 以支持离线兼容测试。

## 2. 启动路径

1. loader 把小型启动卷发布为 `RAMDisk`，内核创建 `/dev/md0`。参数为 `rd=md0 rootdev=md0`。这个内存盘只包含启动卷，不包含系统镜像和用户数据。
2. loader 把辅助盘发布为 `RAMDisk1`。`stage0` 将 `/dev/md1` 挂载到 `/redwood`，执行 `/redwood/sbin/init`。
3. `root_apfs=ufs_darwin ufs=2 ufs_native=1` 使 `init` 从 `/dev/ufs_darwin` 只读挂载 APFS 系统卷，准备启动任务与驱动挂载点，再通过 `kern.redwood_switch_root` 切换根目录。
4. 原版三容器部署从 `darwin` 的后续容器挂载 OS/App Cryptex；合成 `system26.apfs` 使用卷内已有的 `/System/Cryptexes/OS` 与 `/System/Cryptexes/App`。
5. `/private/var` 使用内核 `RDWFS001` 持久化层，数据保存在 `darwin_var`。块写入、同步和断电恢复的验收与系统卷读取分别执行。

初始根盘保留 `md0` 的原因是初始化顺序：`IOFindBSDRoot()` 查找初始根设备早于 devfs 挂载后的 `redwood_ufs_init()`，后者才创建 `/dev/ufs_darwin`。现有用户态切根路径可在这些设备节点创建后使用它们。

`ufs_native=1` 请求原生 UFS 读取。内核仍会检查控制器、LUN 与 GPT；原生接管失败可能使用 loader 的块服务。真机验收需要记录实际选中的读取方式。

## 3. 构建与装载

在 `hackios-xnu-kernel/` 执行 `FLASHBOOT=1 FLASHBOOT_ONLY=1 CRYPTEXES=flash bash userland/build.sh`，只编译 `stage0` 并生成 `userland/flashboot.apfs`。该卷有一个文件与七个目录，本轮构建为 4 MiB；驱动固件由辅助盘或 `modem_a` 提供。

- 自动跑轮：`make-payload.py` 记录启动卷的路径、大小和 SHA-256。`run-auto.py` 先校验载荷实际启动参数与 manifest，再确认 loader idle 且常驻区为空；随后先上传 payload，使 loader 按本轮参数分配窗口，再上传启动卷。实际接收长度与窗口均匹配才启动内核。
- 独立启动：`mkstandalone.py --boot-image ...` 将启动卷放入 `rdimage` 条目；loader 校验内存布局后复制它。系统卷的部署按[双系统手册](../plan/dual-boot-setup.md)执行。

## 4. 内存与载荷限制

| 对象 | 限制与位置 |
|---|---|
| 启动卷 | 主机工具与 loader 限制为 64 MiB，位于 `win_base + 128 MiB` |
| 内核与辅助盘 | 位于常驻区之前，打包前检查二者合计的内存布局 |
| XNUP 完整容器 | `0x03700000` 字节，即 55 MiB；`mkpayload.py` 在写文件前检查，压缩后的大小不改变该限制 |
| iOS 26 内存窗口 | payload 使用 `memsize=300000000`，即 12 GiB；运行器核对 loader 实际分配的窗口 |
| 系统卷 | 位于 `darwin`，容量和文件读取由 UFS/APFS 管理 |

K90 loader 在 USB 单次/分块接收和 DSU 接收入口检查启动卷上限，并拒绝 `rdfile` 系统卷预读；布局检查仍覆盖 `rdimage` 与 `rdres`。其他平台沿用内存窗口边界，QEMU 的完整系统镜像启动用例通过离线检查。

本轮已在旧内核正常返回后清理完整系统镜像，再从 LK 临时启动新镜像。旧 loader 的 `idle` 回答不足以确认内核已停止，必须核对运行日志与实际复位结果，操作条件见[引导 SOP](../plan/device-boot-target-sop.md#4-陷阱均为实测)。

## 5. 数据盘挂载与恢复

只有 `/private/var` 尝试绑定 `darwin_var`。`root_apfs=ufs_darwin` 启动要求该后端可用；设备缺失、内存分配或 I/O 失败都会返回挂载错误，`init` 随即停止初始化与 launchd 启动。

恢复过程校验元数据头、CRC、长度、根节点与记录结构。较新检查点损坏后可以尝试较旧的有效槽；两个槽均无法恢复时停止挂载。首次初始化要求两个完整的 32 MiB 元数据槽全零，这项检查不覆盖后续文件数据区；非零旧格式需要单独迁移。

同步写入实际恢复槽的另一槽，成功后才更新内存中的代数与槽位；写入失败保留待同步状态。有效检查点可以只有根节点。数据文件经内核直接读写 UFS；目录树和块表通过 `fsync`、`F_FULLFSYNC`、`sync` 或当前源码的 1.5 秒延迟任务同步。文件数据原地写入的断电一致性还需单独验证。

元数据更新先写目标槽 payload，再提交 header；中断写入可留下 CRC 不匹配的目标槽，恢复时选择另一有效槽。生产函数测试已覆盖 payload 部分写入和 payload 完成后 header 失败，确认已提交槽保留、重挂载成功且后续同步能重新写入损坏槽；删除 payload CRC 检查后测试失败。正常 stop 的同步发生在部分驱动停止之前，期间仍可能产生后续写入，完整停止写入与同步等待仍需处理。

## 6. 验证结果与待办

本轮离线验证已通过：主机工具 26 项测试、起轮状态 5 项测试、standalone 与启动安全 11 项测试、loader 接收与布局 887 项检查及 7 项故障注入、原有 loader 生命周期测试，以及切根、数据盘挂载和 RDWFS 恢复测试。RDWFS 测试使用实际 C 函数并开启 AddressSanitizer 与 UndefinedBehaviorSanitizer，覆盖设备缺失、分配/I/O 失败、双槽损坏、空元数据、少量节点、旧槽恢复与写入失败重试。

内核、loader、用户态、AIR 与辅助盘构建通过。APFS 读取工具确认启动卷包含一个 `stage0` 文件及七个目录。Linux `apfsck` 在本机 macOS 缺少所需头文件，完整文件系统检查未执行。最终启动镜像为 24,031,232 字节，SHA-256 为 `8a187c03a7a723a1c3d921e425bf157a019a76b02ed381918f083312f116ee17`；解压后的完整 XNUP、内核、辅助盘与启动卷均已逐项核对。

本轮启动与刷写的真机结果：

- loader `build-id` 为 `b935d2e5` 对应的完整提交号，运行状态为 `running 0 0`。
- `ramdisk-state` 为 `ready 400000 400000 300000000`：启动卷 4 MiB，XNU 内存窗口 12 GiB。辅助盘为 20,533,248 字节；窗口大小与系统当前可用内存分别记录。
- 日志依次确认 `BSD root: md0`、`/dev/ufs_darwin` 只读挂载、`vfs_switch_root error 0`、OS/App Cryptex 与 `/redwood` 绑定成功。
- 内核完成原生 UFS transfer list 切换和 TEST UNIT READY，LUN 0～5 的 GPT 与原读取结果一致；系统分区由内核 UFS 驱动读取，`darwin_var` 注册了硬件块写入范围。
- `/private/var` 从槽位 1、代数 75024 恢复 21446 个节点与 73261 页，SpringBoard 和 backboardd 启动，锁屏截图已保存。
- 临时启动停止前，`hw.memsize` 为 12 GiB，页大小为 16384 字节；空闲页 457628 页，约 6.98 GiB，wired 页 77614 页，约 1.18 GiB。完整系统镜像的 5.51 GiB 常驻分配已清除。
- 同一镜像写入 `boot_a`，发送和写入均成功；重启后 USB 断开并重新枚举，新 loader 身份、4 MiB 启动卷、UFS 切根和 Cryptex 挂载再次确认。
- 在新系统中只读 `/dev/rufs_boot_a` 的前 24,031,232 字节，SHA-256 与构建镜像完全一致；结果保存于 `boot-readback.log`。
- 持久启动从槽位 1、代数 77738 恢复 21621 个节点与 73923 页。该结果确认正常重启读取了更新后的检查点；指定测试文件、设置和异常复位恢复仍需分别验证。
- 持久启动中创建测试文件并执行 `fsync`、`F_FULLFSYNC` 与 `sync`，前两项均返回 0；`marker-create.log` 记录本轮写入，文件内容在下一批重启后读回。

设备日志与截图保存在本地忽略目录 `docs/progress/evidence/storage-boot-device-1108/phase2/`，分别为 `temporary-ended.log`、`persistent-boot.log` 与 `temporary-screen.png`。源码对应内核 `990b6fcc`、loader `b935d2e5` 和辅助盘用户态 `5a37569`；后续 `net_test` 提交 `6ff56cb` 未包含在该辅助盘中。

- 离线：验证真实 XNUP 条目、启动参数、完整容器大小、常驻区上限，以及上传顺序；尺寸或状态不符应在内核运行前失败。
- 产物：用 APFS 检查工具读取启动卷，核对 `/sbin/launchd` 与挂载目录；构建 loader、辅助盘及 standalone，记录各自产物哈希。
- 真机：日志应先出现 `BSD root: md0`，随后确认 `/dev/ufs_darwin` 挂载与根目录切换成功、launchd 缓存绑定成功；记录常驻镜像长度、实际内存窗口与可用内存。
- 持久化：写文件、修改设置、执行同步，再正常重启并读回；另行检查异常复位恢复结果。仅修改启动卷不能完成持久化验收。

## 7. 完整原版系统卷部署

后续设备部署使用原版 `os.dmg`、`systemos.dmg` 与 `appos.dmg` 三个 APFS 容器，按 4096 字节边界顺序写入 `darwin`。内核继续按需读取系统文件，启动卷与辅助盘提供移植所需的引导、驱动和运行时挂载。完整提取目录用于生成启动任务和分析，设备镜像保留原版 APFS 压缩、文件与元数据。

| 原版容器 | 字节数 | 用途 |
|---|---:|---|
| `os.dmg` | 9,758,048,256 | 系统根卷 |
| `systemos.dmg` | 5,261,754,368 | OS Cryptex |
| `appos.dmg` | 14,680,064 | App Cryptex |
| 合计 | 15,034,482,688 | 约 14.002 GiB |

完整提取已通过。`ios26/full-system.py` 从原始列表生成所有文件的元数据，提取状态记录镜像与准备脚本的 SHA-256；构建前检查该状态。`fetch.sh` 复制完整系统根目录和两个 Cryptex，共享缓存的分析目录通过硬链接复用内容。原始卷中的零字节、不可读普通文件先按原模式和时间创建，随后由 `rsync` 完成目录复制。

用户态编译及配套辅助盘打包通过，启动任务共 553 项，包含 `locationd`、`fairplayd.H2`、`geod` 与 `weatherd`。通知资源直接使用原始系统卷的文件，辅助盘为 18,137,088 字节。完整提取的 6 项测试、切根的 7 个场景和数据盘挂载测试均通过；这些服务的实际启动与内容请求仍需在原版系统部署后检查。

当前生产 APFS 读取代码已编译为主机工具，从三个原始容器读取 12 个文件，与 macOS 完整提取结果的长度及 SHA-256 全部一致。检查覆盖 `launchd`、`locationd`、`fairplayd.H2`、日历通知资源、五个 CoreImage metallib，以及 OS/App Cryptex 中的文件。

完整系统启动镜像为 22,450,176 字节，SHA-256 为 `cff5d9104672098d536ca10ebbf6a9a16986c96c749f006c3bad3df422339109`。解开 Android kernel 的 gzip 后，XNUP 直接包含内核、辅助盘和 4 MiB 启动卷；内核、loader、启动参数与 Metal/AIR 沿用第 6 节的已部署输入。首轮检查完整系统及对应启动任务，图形候选修复另行验证。

`reseal-loader-img.py` 校验容器长度、条目边界、padding 和结束记录，并拒绝 loader 无法解开的 `payload.lz4` 条目。7 项测试通过；BootShim、UEFI、DTB、Android ramdisk 及其余 header 字段保持原值。完整 boot 已通过 LK 临时启动，随后写入 `boot_a` 并重启；物理分区前 22,450,176 字节的完整读回 SHA-256 与上述镜像一致。

`darwin` 已从 8 GiB 扩至 16 GiB，写入上述三个容器后剩余 2,145,386,496 字节。相邻 `darwin_var` 的起始位置后移，容量为 111,669,129,216 字节；末尾、GUID、属性与 Android `userdata` 保持原值。

迁移前，设备正常停止 XNU 并进入 Android。主备 GPT、64 MiB 数据盘元数据、8 GiB 旧系统分区和 4,076,797,952 字节数据盘前缀均已备份，设备重新读取与主机文件的 SHA-256 一致。数据盘槽位 1、代数 81504 有效，槽位 0 的头部有效但 payload CRC 和记录解析失败；两个槽均按原样保存。有效引用全部位于备份前缀内，迁移目标可容纳；本次记录无法确定槽位 0 写入中断的具体时刻。

备份前缀中的 64 MiB 元数据与独立副本一致，从有效检查点引用的数据块读出的 110 字节测试文件也与停止前逐字节一致。备份完成后再次读取主备 GPT，内容保持原值。主任务另行读取两份备份并重复校验长度、SHA-256、元数据和测试文件。

`hackios-xnu-kernel/tools/rdwfs-inspect.py` 校验保存的元数据并计算有效块范围，`hackios-xnu-kernel/tools/darwin-expand-plan.py` 校验当前主备 GPT、分区相邻关系和目标容量，可将候选 GPT 输出到新建主机目录。两组各 21 项测试通过。真实候选主、备文件各改变 10 个字节，全部属于两个分区的边界及相关 CRC，其余字节保留。

迁移已完成。数据盘前缀与三个原始系统容器分别写入、同步并全范围读回，SHA-256 均与输入一致；随后按备份分区表、备份头、主分区表、主头的顺序更新 GPT，各项读回及完整 CRC 校验通过。两个分区的范围发生变化，其余 62 个条目，以及这两个条目的 GUID、属性和名称均保持原值。

迁移后首次运行已读回相同的 110 字节测试文件，`ufs_native=1`、`ufs_write_errors=0`。该轮 12 GiB 物理内存采样中，16 KiB 页的空闲计数为 428,495，约 6.54 GiB；wired 计数为 73,048，约 1.11 GiB。该读数对应首次启动采样，后续应用活动会改变页数。

实际布局、范围及备份校验保存在本地忽略目录 `storage-boot-device-1108/phase3/`，写入与读回结果在 `phase4/`。完整系统镜像已覆盖旧系统及旧数据盘前部，回滚需要恢复内容与原 GPT。本次保留了已有数据盘内容；后续初始化可按测试需要重建 iOS 数据卷。

持久启动的检查结果保存在 `phase4/persistent-migration-verification.json`：

- UFS 系统卷、两个 Cryptex 和迁移后的数据盘均挂载成功，`ufs_native=1`、`ufs_write_errors=0`；启动卷 4 MiB，辅助盘 18,137,088 字节。
- `/private/var` 从槽位 1、代数 91418 恢复 23647 个节点与 86313 页；同一 110 字节测试文件在迁移和多次正常重启后保持一致。
- 11:08:30～31（CST）采样空闲页 408088，约 6.23 GiB；wired 页 91626，约 1.40 GiB。该读数随运行负载变化。
- 桌面能够启动，早期透明的应用图标在原生应用和控制中心交互后恢复；Weather/Calendar 大组件仍为黑底，天气和地图内容请求仍待修复。

部署内核为 `990b6fcc`、loader 为 `b935d2e5`。图形候选及后续数据同步错误处理修复尚未包含在该启动镜像中，按独立变量继续验证。
