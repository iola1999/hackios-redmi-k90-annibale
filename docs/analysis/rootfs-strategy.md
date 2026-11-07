# 根文件系统：从 UFS 挂载系统卷

系统卷放在 UFS `darwin` 分区，由内核 APFS 驱动按需读取。启动阶段的 `md0` 只放小型 `flashboot.apfs` 引导卷中的 `stage0` 与挂载目录，辅助盘 `md1` 放本项目的程序、驱动与固件。系统镜像不再整体读入 loader 常驻区，`/private/var` 由内核直接写入 UFS `darwin_var`。本文描述工作树的启动路径，真机切根与内存回收效果尚待验证。

## 1. 近期提交与审查结论

- 内核 `e8b499c` 与顶层 `bc20def` 加入 DSU 系统镜像读取：loader 把整个镜像读入常驻内存。
- 内核 `08170b1` 把独立启动镜像接到 `darwin` 分区，`rdfile` 仍把整个系统镜像读入内存。
- 内核 `9657ff3` 实现 `/private/var` 文件数据直写 `darwin_var`、按需读入数据页，以及双 32 MiB 元数据槽位；用户态 `fcaf0f5` 接入 UFS 系统卷切根并移除定时归档任务。这两笔提交已有落盘实现，但当时 standalone 和自动跑轮仍使用完整系统镜像的常驻内存路径。
- 2026-11-08 的只读查询得到 `ramdisk-state: ready 160bc1000 160bc1000 300000000`：常驻镜像为 5,917,904,896 字节，约 5.51 GiB。这段内存位于交给 XNU 的窗口内，布局将其纳入 `topOfKernelData`，启动后占用内存。
- 同次真机日志确认 XNU 正在运行，系统卷仍由 `rdfile` 全量载入；`/private/var` 已从 UFS 恢复。旧 loader 的 standalone 入口遗漏 `running` 状态更新，导致 `getvar result` 错报 `idle`；本轮将更新放到共同的内核运行入口。

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

K90 loader 在 USB 单次/分块接收和 DSU 接收入口检查启动卷上限，布局检查也覆盖 `rdimage`、`rdfile` 与 `rdres`。其他平台沿用内存窗口边界，QEMU 的完整系统镜像启动用例通过离线检查。

设备上现存的大镜像需要在保存现场并完成恢复条件检查后清理。旧 loader 的 `idle` 回答不足以确认内核已停止，必须核对运行日志与实际复位结果。

## 5. 数据盘挂载与恢复

只有 `/private/var` 尝试绑定 `darwin_var`。`root_apfs=ufs_darwin` 启动要求该后端可用；设备缺失、内存分配或 I/O 失败都会返回挂载错误，`init` 随即停止初始化与 launchd 启动。

恢复过程校验元数据头、CRC、长度、根节点与记录结构。较新检查点损坏后可以尝试较旧的有效槽；两个槽均无法恢复时停止挂载。首次初始化要求两个完整的 32 MiB 元数据槽全零，这项检查不覆盖后续文件数据区；非零旧格式需要单独迁移。

同步写入实际恢复槽的另一槽，成功后才更新内存中的代数与槽位；写入失败保留待同步状态。有效检查点可以只有根节点。数据文件经内核直接读写 UFS；目录树和块表通过 `fsync`、`F_FULLFSYNC`、`sync` 或当前源码的 1.5 秒延迟任务同步。文件数据原地写入的断电一致性还需单独验证。

## 6. 验证结果与待办

本轮离线验证已通过：主机工具 22 项测试，standalone 与启动安全 11 项测试，loader 接收与布局 887 项检查及 7 项故障注入，原有 loader 生命周期测试，以及切根、数据盘挂载和 RDWFS 恢复测试。RDWFS 测试使用实际 C 函数并开启 AddressSanitizer 与 UndefinedBehaviorSanitizer，覆盖设备缺失、分配/I/O 失败、双槽损坏、空元数据、少量节点、旧槽恢复与写入失败重试。

内核、loader、用户态和辅助盘构建通过。APFS 读取工具确认启动卷包含一个 `stage0` 文件及七个目录。Linux `apfsck` 在本机 macOS 缺少所需头文件，完整文件系统检查未执行；独立引导产物尚未上机。

- 离线：验证真实 XNUP 条目、启动参数、完整容器大小、常驻区上限，以及上传顺序；尺寸或状态不符应在内核运行前失败。
- 产物：用 APFS 检查工具读取启动卷，核对 `/sbin/launchd` 与挂载目录；构建 loader、辅助盘及 standalone，记录各自产物哈希。
- 真机：日志应先出现 `BSD root: md0`，随后确认 `/dev/ufs_darwin` 挂载与根目录切换成功、launchd 缓存绑定成功；记录常驻镜像长度、实际内存窗口与可用内存。
- 持久化：写文件、修改设置、执行同步，再正常重启并读回；另行检查异常复位恢复结果。仅修改启动卷不能完成持久化验收。
