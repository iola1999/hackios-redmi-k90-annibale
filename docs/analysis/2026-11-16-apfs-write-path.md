# 可写 APFS：事务引擎与 VFS 接入（2026-11-16）

适用范围：`hackios-xnu-kernel`（`k90-port`）的 [bsd/miscfs/apfs](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/) 与 `hackios-xnu-userland`（`k90-port`）的 [tools/apfs](../../hackios-xnu-userland/tools/apfs/)，随本文同批提交。主机测试见第 6 节；2026-11-16 测试机已迁移到 APFS 并上机验证，结果见第 8 节。init 按 `darwin_var` 的格式选择挂载方式，分区转为 APFS 之前 `/private/var` 仍是 `ANNFS001`（ramfs）。

## 1. 结论

- 写入引擎已重写为单个打开事务加检查点提交。B-tree 支持多层分裂与合并，空间管理器支持多个 chunk，卷与容器两级对象映射和检查点环都随提交推进。旧的 `apfs_txn.inc`、`apfs_txn_btree.inc`、`apfs_write_ops*.inc` 已删除。
- 内核 VFS 已接到新引擎。文件内容走 UBC 与 cluster 层（`vnop_blockmap`、`vnop_strategy`），与 ramfs 对齐的接口均已实现，详见第 5 节。
- 挂载时未带 `MNT_RDONLY` 且卷可写即为可写挂载，boot-arg `apfs_rw=0` 强制只读。系统卷、cryptex 与 `/annibale` 都以 `MNT_RDONLY` 挂载，行为不变。
- APFS 挂载开启扩展安全：ACL 存在 `com.apple.system.Security` 扩展属性里，由 VFS 读写和检查，与 iOS 相同。容器目录的权限位是 000，访问靠 ACL。
- `darwin_var` 块 0 是 APFS 容器超级块时，init 把 Data 卷挂到 `/private/var`，否则挂 ramfs。`tools/apfs/annfs-to-apfs.py` 把现有的 `ANNFS001` 分区原地转为 APFS，容器比分区小 32 MiB，末尾这一段之后拆为 `darwin_nvram`（第 7 节）。真机验收见第 8 节。

## 2. 事务模型

引擎代码在 `apfs_wbt.inc`（B-tree）、`apfs_wspace.inc`（空间管理器）、`apfs_wtx.inc`（事务与提交）、`apfs_wfs.inc`（文件系统记录）、`apfs_wops.inc`、`apfs_wxattr.inc`、`apfs_wclone.inc`（操作），模型说明在 `apfs_wtx.h`。

- 同一时刻只有一个打开的事务。改动过的元数据块留在内存覆盖层（overlay），读路径 `nx_block` 先查覆盖层，所以同一事务内的读能看到未提交的改动。
- 每个操作先完成查找、检查和空间预留，第一次修改之后的失败（设备错误或内存耗尽）会作废整个事务，挂载转为只读，上一个检查点保持有效。
- 提交顺序：等已映射的数据写完成（第 4 节），写出全部新元数据块、检查点映射和临时对象，刷盘，写容器超级块，再刷盘，最后更新块 0 的副本。刷盘通过 `DKIOCSYNCHRONIZECACHE`。
- 数据块在把它们移出文件的那次提交之后才释放（`wsp_free_later`），同一事务内分配又释放的元数据块立即回收。
- 分配出去的块会从元数据缓存中清掉（`wsp_taken`），见第 6 节的问题 2。

## 3. 提交时机

- 第一次改动后约 1 秒（`APFS_WCOMMIT_MS`）。定时提交先把上次提交后写过的文件的脏页推到设备（`apfs_wpush`），再提交。
- 事务中脏元数据块超过 4096 块时，在当前操作末尾立即提交。在 `vnop_blockmap` 里超过时改由定时提交线程立即执行，因为这次映射要等 blockmap 返回后才会发出。
- `fsync(2)`（该文件有未提交改动时）、`F_FULLFSYNC`、`F_BARRIERFSYNC`、`IO_SYNC` 写、`sync(2)` 和卸载时提交。`F_FULLFSYNC` 在没有未提交改动时只刷盘。`fsync` 和 `IO_SYNC` 写拿到卷写锁时，如果等锁期间别的提交已经包含了这个文件的改动，就不再提交。
- 断电时可能丢失的范围：最后约 1 秒内未经 fsync 的改动。已有数据块的原地覆盖不经过检查点，断电时这些块可能是新旧混合内容；元数据始终停在某个完整的检查点。

## 4. 数据路径与写入顺序

- 可写挂载上未压缩的普通文件用 `cluster_read`、`cluster_write`、`cluster_pagein`、`cluster_pageout`。压缩文件保留原读路径，写入和截断返回 `EPERM`。
- `vnop_blockmap` 在写映射时给空洞分配新块，已有块原地写。每个写映射都登记到 `wm_map`，`vnop_strategy` 发出对应缓冲区时扣除，并给缓冲区装上完成回调计入 `wm_io`。
- 提交先等 `wm_map` 清空，再等 `wm_io` 归零。`cluster_io` 可能只发出一个映射的一部分（例如截到页边界），剩余部分要等它下一次调用 `vnop_blockmap` 才发出，所以映射在 20 ms（`APFS_WDRAIN_HELD_MS`）内没有全部发出时，提交放开卷写锁，等到全部发出再取回锁。已发出的写不需要锁就能完成，等 `wm_io` 时持锁。检查点在持锁、映射全部发出且写全部完成后写出，不会指向内容还没写到设备的块。
- 等待上限 2 秒（`APFS_WDRAIN_MS`）。超时说明有映射被 cluster 层放弃，这些页仍是脏页，之后会重新映射；内核打印未发出的映射（文件号、文件内偏移、块数，最多 4 个）后继续提交。
- `vnop_blockmap` 先登记映射，再标记事务有改动，事务满时也不在 blockmap 里提交。
- 写入扩展文件时先在元数据中把长度设好（新增部分为空洞），数据页在推出时才分配块，提交早于数据推出时，崩溃后新增部分读作零。
- 用新文件替换旧文件的 `rename` 先推出源文件的脏页，提交在这些写完成后才进行。
- 延迟分配的空间检查：可用块少于本次写入块数加 16384 块（64 MiB，`APFS_WSPARE_BLOCKS`）时 `write(2)` 返回 `ENOSPC`。

## 5. 与 ramfs 对齐的接口

| 接口 | 实现 |
|---|---|
| `create`、`mkdir`、`mknod`（套接字、FIFO、字符和块设备）、`symlink`、`link` | `apfs_vnops_dir.inc`，创建后清掉目录的否定名称缓存 |
| `remove`、`rmdir` | 文件仍被打开时移入私有目录成为孤儿，`vnop_inactive` 回收；挂载时回收崩溃留下的孤儿 |
| `rename`、`renamex`（`RENAME_SWAP`、`RENAME_EXCL`） | 被替换的目标仍被打开时同样成为孤儿 |
| `setattr`、`setxattr`、`removexattr` | 超过 3804 字节的扩展属性存为独立数据流，上限 1 MiB |
| `clonefile` | 文件、符号链接和整棵目录树的深拷贝，见下 |
| `FSIOC_CAS_BSDFLAGS` | 设置 `UF_TRACKED` 时分配文档 ID，`getattr` 返回 `va_document_id` |
| APFS fsctl `'J' 2`、`68`、`72`、`74` | 目录统计与可清除标记只应答；同步根标记存为 inode 内部标志 `APFS_INODE_IS_SYNC_ROOT` |
| `statfs` | 容器总量为 `darwin` 分区与 `darwin_var` 容器之和，可用量为数据容器的空闲块；无可写数据卷时沿用 ramfs 的数值 |

`clonefile` 拷贝数据，副本有自己的块；APFS 原生做法是共享 extent、写时复制，本引擎还没有共享 extent 的引用计数。拷贝在卷写锁内进行，大文件或大目录克隆期间其他文件系统操作会等待。克隆前先把源文件（目录克隆时是整个卷）的脏页同步写到设备。

可写挂载的统计读 `sysctl kern.apfs_wstats`：提交次数、写出块数与耗时、提交失败次数、等待超时次数和空闲块数。

## 6. 主机验证

| 测试 | 结果 |
|---|---|
| `tools/apfs/write-tests.sh` | 92 项通过 |
| `test_wfs_random.py` 默认 8 轮 × 300 次操作，含断电测试 | 通过；每次设备写之后断电，`apfsck -w` 都读到一个完整检查点 |
| `test_wfs_random.py --rounds 30 --no-crash` | 通过 |
| `test_wfs_random.py --big --ops 2500`（文件系统树多层、对象映射多层） | 通过 |
| ASan 与 UBSan 构建下的随机测试和写入测试 | 通过 |
| 内核 `xnu26/build-macos.sh` | 编译通过，APFS 目录下无新增错误 |
| `tools/apfs/test_annfs.py`：随机 `ANNFS001` 分区转换，含硬链接、稀疏页、超长扩展属性、文档 ID 和落在末尾 32 MiB 的数据页 | 20 轮 × 140 个对象通过；每轮写回前 512 MiB 后 `apfsck -cw` 无错误，`apfs.py` 读出的每个对象与模型一致 |
| `test_annfs.py --objects 20000`（文件系统树多层，转换中途多次提交） | 2 轮通过 |
| ASan 与 UBSan 构建下的 `test_annfs.py` | 通过 |
| 真机 `darwin_var` 备份（70,784 个对象、358 个硬链接、13,374 个扩展属性）在主机上转换 | 1.4 秒完成，`apfsck -cw` 无错误；与迁移前在 iOS 下记录的文件清单比对元数据，45,941 个文件中 45,621 个一致，其余是记录清单之后仍在变化的日志和数据库文件 |
| `annfs-to-apfs.py` 在模拟的 adb 上执行转换、重复执行、`--rollback` 与 `--format` | 转换后逐项比对一致，`apfsck -cw` 无错误；重复执行不改动分区；回退后分区与原分区逐字节相同 |

随机测试按模型逐项比对目录树、内容、扩展属性、链接数与设备号，并对每轮结果运行 `apfsck`。主机上的 apfsck 由 [build-apfsck.sh](../../hackios-xnu-userland/tools/apfs/build-apfsck.sh) 构建：固定 apfsprogs 版本，应用 `apfsprogs-host.patch`（macOS 上用 `pread` 代替 `mmap`，接受 iOS 使用的保护类 7）。测试和真机备份的转换查出并修复了下面三个问题。

1. `wr_next` 读取下一条记录时按 4096 字节容量往调用方的 64 字节缓冲区拷值，记录值较长时越界写栈（ASan 报 `stack-buffer-overflow`）。改为由调用方传入缓冲区容量。
2. 提交后释放的元数据块在下一个事务里被分配为数据块（如扩展属性数据流），元数据缓存中仍有旧内容，经 `apfs_read_stream` 读到旧数据。改为分配时清掉这些块的缓存条目。
3. B 树节点分裂时按顺序装满前面的节点，乱序插入时反复分裂会留下大量半空节点。转换真机备份时文件系统树长到 8 层，第 16 个事务返回 `EFBIG`。改为分裂时把记录按大小平均分到同样数量的节点（`wn_even`），同一份备份转换后文件系统树 3 层，每个节点约 30 条记录（原来 4～5 条）。

## 7. 分区末尾与迁移

迁移时 APFS 容器比 `darwin_var` 小 32 MiB，末尾这 32 MiB 不属于容器。2026-11-16 起这一段拆成独立的 GPT 分区 `darwin_nvram`，存放 NVRAM bank 和 panic 日志（[annibale_nvram.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_nvram.inc)），布局、loader 与内核的读写见[持久化 NVRAM](2026-11-16-persistent-nvram.md)。

- panic 日志写在 `darwin_nvram` 的 16 MiB 处，格式与 ANNFS 时相同（`KLOG` 头加文本）。没有 `darwin_nvram` 时，内核启动后读一次 `darwin_var` 块 0：`ANNFS001` 的 panic 日志仍在 64 MiB 处，APFS 不写 panic 日志。
- 退回 loader 时（`annibale_var_save_on_return`）先把 APFS 卷全部文件的脏页同步写到设备，再提交。
- init 挂载后读 `kern.annibale.panic_log`，把上一次运行的 panic 日志存为 `/private/var/db/panic.log`，再写这个 sysctl 把它标记为已保存。`var_apfs=1` 启动参数已删除。
- ramfs 在元数据槽无效且前 64 MiB 非零时拒绝挂载，不会格式化 APFS 分区。
- panic 日志在 panic 开始时（`loader_panic_log`）写一次，退回 loader 前（`loader_return`）带上 panic 缓冲区和控制台日志末尾再写一次。没有发生 panic 的退回不写。v0.1.2 起的版本在这一步因中断关闭返回 `EBUSY`，ANNFS 的 64 MiB 处和 APFS 的末尾都从未写入过。
- 这时中断已屏蔽，不能用 `hc_lock`，也不能休眠。`annibale_klog_write` 经 `ufs_part_io` 改走 `ufshc_write_polled`：UTRL 的最后一个槽位只留给它，单独写门铃并轮询门铃位，上一次轮询写还没结束时先等它完成。
- `loader_panic_sync_ufs` 屏蔽 A、I、F 三位。只屏蔽 I、F 时，被调用代码里的 `ml_set_interrupts_enabled(FALSE)` 会因部分屏蔽断言失败。同一时刻只有一个处理器填写并写出日志缓冲区，其他处理器最多等 5 秒，超时放弃；同一处理器在写日志时再次 panic 则直接接手。

迁移在 Android root 下经 adb 执行 [annfs-to-apfs.py](../../hackios-xnu-userland/tools/apfs/annfs-to-apfs.py)，数据块原地不动：

1. 读出 `darwin_var` 前 512 MiB 和末尾 32 MiB 保存到本地，传输都用 SHA-256 校验；分区表已有 `darwin_nvram` 时容器覆盖整个分区，不读末尾。ANNFS 的两个元数据槽和 panic 日志在前 512 MiB，数据页从 512 MiB 开始。
2. `mkapfs.py --blocks` 在主机上建一个与分区减 32 MiB（有 `darwin_nvram` 时为整个分区）等大的空容器，卷角色为 Data。`apfs-tool annfs`（[cmd_annfs.c](../../hackios-xnu-userland/tools/apfs/cmd_annfs.c)）读较新的有效元数据槽，在容器里重建根目录可达的全部对象：inode 号（小于 16 的另行分配）、权限、属主、BSD 标志、四个时间、保护类、文档 ID、同步根标记、扩展属性和硬链接。普通文件的 extent 直接指向原数据页，ANNFS 第 n 页（16 KiB）对应 APFS 块 131072 + 4n 起的 4 块。
3. ANNFS 按 next-fit 在整个分区分配数据页，落在末尾 32 MiB 的页由转换器复制到 512 MiB 以内的新块。转换中的其他分配也都在 512 MiB 以内，所以写回手机的只有镜像的前 512 MiB，脚本在写回前检查镜像 512 MiB 之后没有内容。
4. 写回前 512 MiB 并读回比对。`--rollback` 写回保存的前 512 MiB，分区恢复为 ANNFS，APFS 下的改动丢失。`--format` 不转换，直接建空的 APFS 数据卷。

ANNFS 中有两类 APFS 不允许的状态，转换器按 APFS 的规则处理：

- 文档 ID 小于 3 的对象（APFS 保留这一范围）改用新的文档 ID。
- 带 `UF_COMPRESSED` 标志但没有 `com.apple.decmpfs` 扩展属性的文件去掉这个标志。真机备份中有 12,562 个这样的文件，抽查到的都在微博应用的安装包和应用目录里。内核 `setattr` 也按 XNU `decmpfs_update_attributes` 的规则处理：只有文件已有 decmpfs 头、且同一次调用不改大小时，才允许设置 `UF_COMPRESSED`。

ANNFS 不记录设备号，迁移后字符设备的设备号为 0；套接字和没有目录项指向的对象不迁移。

## 8. 未完成事项与真机验收

### 8.1 真机验收结果

2026-11-16 在测试机上执行。内核为 `hackios-xnu-kernel` 的 `7cb8a4df`，含第 8.4 节第 1～4 项修复。

| 项目 | 结果 |
|---|---|
| 迁移 | B 槽 Android 下执行 `annfs-to-apfs.py`，约 24 秒。70,784 个对象、358 个硬链接、13,374 个扩展属性；1,908,217 个块原地接管，没有复制；1 个文档 ID 改号，12,562 个文件去掉 `UF_COMPRESSED`；`apfsck -cw` 无错误 |
| 挂载 | 内核打印 `apfs: volume "Data" is writable`，init 打印 `mounted the APFS data volume on /private/var`；桌面、壁纸、小组件、应用布局与 Wi-Fi 网络保留 |
| 文件比对 | 迁移前在 iOS 下记录 `/private/var` 的文件清单（45,941 项，含权限、属主、链接数、大小与 SHA-256），约 2 小时、7 次 iOS 启动后再记录一次：44,497 项相同，内容变化 373 项，元数据变化 168 项，新增 1,728 项，删除 903 项。变化都在偏好设置、Spotlight、Biome、缓存和数据库这类运行中会改写的目录，应用包、照片与 MobileAsset 下没有内容变化 |
| 连续读取 | 两次全量读取 `/private/var`（约 8 GB），相隔约 3 分钟，差异只在上面这类目录；期间没有 UFS 错误，也没有 panic |
| 写入后重启读回 | 重命名、硬链接、克隆后改写副本、扩展属性、删除、`mmap` 写、稀疏文件、截断共 10 项，写入后正常退回 loader，重启后全部读回正确 |
| 提交统计 | `kern.apfs_wstats` 提交失败次数为 0 |
| 背光设置、panic 日志 | 未验证：这几轮没有调节亮度；panic 日志当时写不出去，第二轮的结果见第 8.2 节，背光跨重启见[持久化 NVRAM §6](2026-11-16-persistent-nvram.md#6-真机验证) |

### 8.2 第二轮：提交次数、数据写等待与 panic 日志

2026-11-16 下午在同一台测试机上执行，内核依次换了几版，最终版本为 `hackios-xnu-kernel` 的 `d8d9f8a9`，含第 8.4 节第 5～7 项修复。panic 测试用的版本与最终版本只差提交等待的调整，panic 路径相同。`kern.apfs_wstats` 增加了按原因统计的提交次数、等数据写的累计与最长时间（分持锁和放开锁两部分）和最长单次提交时间。

| 项目 | 结果 |
|---|---|
| 提交次数 | 修复前内核解锁后约 1.5 分钟：2,461 次提交，其中 `fsync` 1,801 次，`F_FULLFSYNC`／`F_BARRIERFSYNC` 594 次，定时提交 38 次，`IO_SYNC` 23 次，`sync` 4 次。提交本身累计 6,385 ms，平均约 2.6 ms，最长 16 ms。提交次数基本都由应用的同步请求触发 |
| 等数据写超时 | 同一时段等数据写累计 14,227 ms，其中 7 次到了 2 秒上限，每次都是 1 个映射只发出一部分、在途写为 0（例如文件 1075659 偏移 7647232 处 12 块里 3 块未发出），即第 8.4 节第 5 项。修复后解锁 7 分钟内 3,570 次提交，0 次超时 |
| 开机时的等待 | 解锁后约 10 秒内大量进程同时 `fsync`。第一版修复只要有映射未发出就放开写锁，等数据写累计 22,250 ms（各提交线程相加），单次最长 1,047 ms，panic 后的那次开机单次最长 3,232 ms。加上先持锁等 20 ms 和 `fsync` 合并提交（`67a07ebd`）后，累计 9,670 ms，单次最长 1,238 ms，其中 8,685 ms 在放开锁的阶段，原因见第 8.4 节第 5 项。改为等全部映射发出再取锁后（`d8d9f8a9`），解锁后约 10 秒累计 391 ms，约 70 秒时 393 ms；单次最长 56 ms，持锁部分最长 21 ms |
| 等待的组成 | 诊断内核（未入库）分开记录放开锁后的各段时间：19 次放开锁，放开时已有的映射平均约 5 ms 发完（最长 41 ms）；从登记到发完最慢的映射 142 ms，没有超过 200 ms 的；放开期间新登记的映射没有带来额外等待；重新取锁累计约 50 ms |
| panic 日志 | 用 `sysctl debug.panic_test=4`（两个处理器同时 panic）触发。修复前，日志头有效但正文 CRC 不符，init 没有保存，见第 8.4 节第 7 项。修复后，下次开机 init 保存 `/private/var/db/panic.log`（262,057 字节），含两个处理器的 `PANIC caller ... xnu_vs_xnu panic test` 与 `haltRestart`，`kern.annibale.panic_log` 随后返回 0 字节 |
| panic 后读回 | 两次 panic 前都用 `apfsw write` 写入并 `fsync`，下次开机数据卷正常挂载，`apfsw check` 10 项全部正确 |

### 8.3 与 ANNFS 的对比

同一台手机、同一批载荷的 A/B 没有做过：分区转为 APFS 后，回到 ANNFS 要执行 `--rollback`，迁移后的改动会丢失。下表来自已有轮次的记录和两边的代码，内核与载荷不完全相同，结论只到这个粒度。

| 项目 | ANNFS | APFS |
|---|---|---|
| 一次同步写出的元数据 | 每次检查点把全部元数据打包后整份写出。迁移前 70,784 个对象，payload 17,098,088 字节 | 只写这次改动的元数据块。解锁后约 70 秒 2,281 次提交共写 106,640 块（约 437 MB），平均每次约 190 KB |
| 同步次数与写入量 | 2026-11-16 上午连续 8 轮，每轮（开机加 2～4 分钟）检查点代数增加约 3,100～3,300，按 17 MB 一次估算每轮约 50 GB | 提交次数同一量级（解锁后约 70 秒 2,281 次），每次写入量约为 ANNFS 的 1/90 |
| 同步时其他操作的等待 | 打包在 `rm_lock` 内进行，所有文件操作等它。2026-11-13 的诊断轮一次打包 13.6 ms（139,271 个节点），等锁区间里打包时间占 84%（[性能核查 §2](2026-11-13-performance-log-review.md#2-s9容量失败与重复同步)） | 最长提交 16 ms，等数据写持锁部分最长 21 ms |
| 开机到解锁 | 2026-11-16 当天 15 轮：多数约 25 秒，其余 30～35 秒 | 第 8.4 节第 5 项修复后 7 轮：15～21 秒 |
| 没有对比的项目 | 大文件顺序读写吞吐、小文件随机读、应用启动时间 | 同左 |

开机到解锁的时间从主机命令记录算出：`oem run` 到第一份含 `sb26: boot unlock done` 的串口日志，日志约每 5 秒取一次，误差在 5 秒以内。检查点代数取自每轮开机时的 `ramfs: loaded /private/var from disk` 行，相邻两轮之差即上一轮写出的检查点数。严格的对比需要一块能单独格式化的分区，或者接受回滚。

### 8.4 上机发现并修复的问题

1. `vfs_conf.c` 里 apfs 类型带 `MNT_RDONLY`，`mount_common()` 把它加到每次挂载上，`/private/var` 挂成只读。`tzinit` 写入失败后退出，内核随即 panic。已从类型表删除这个标志（`xnu26/patches/20-bsd%vfs%vfs_conf.c.patch`），其他 APFS 挂载都自己带 `MNT_RDONLY`。
2. APFS 挂载没有开启扩展安全，VFS 忽略 ACL，只按权限位检查。iOS 的容器目录是 000、属主 -2，访问全靠 ACL，迁移前的备份里有 136 个这样的目录。SpringBoard（`BSUIMappedImageCache`）和 installcoordinationd 建目录失败后反复崩溃；在同一个容器目录下以 uid 501 建目录可以复现 `EACCES`。ramfs 挂载时调用 `vfs_setextendedsecurity()`，所以以前没有出现。APFS 挂载现在同样调用，并上报 `VOL_CAP_INT_EXTENDED_SECURITY`。
3. 上机后 `apfsck` 报 `Compressed file: missing decmpfs xattr`，对应 `dirs_cleaner` 下一个新建的 `.mlmodel` 文件：带 `UF_COMPRESSED`，没有 decmpfs 扩展属性，数据全是空洞。`FSIOC_CAS_BSDFLAGS` 由 VFS 直接交给文件系统，不经过 `vnode_setattr`，`setattr` 里的 decmpfs 规则对它不生效，现在 CAS 处理按同一规则去掉这个标志。设置标志的具体调用没有抓到。
4. UFS 异步完成判断有竞争。`hc_ring()` 在 `hc_lock` 内先把槽位标为活动，再写门铃；完成线程不加锁比较活动位和门铃寄存器，会把已标记但还没写门铃的槽位当成已完成：读到初始的 `OCS f`，返回 `EIO` 并归还槽位，控制器随后把数据 DMA 到已释放的页里，内核以 `pmap_assert_free` panic。当天的日志里只有 APFS 数据卷的轮次出现过 `OCS f`，APFS 读写大量走异步路径。完成线程现在在 `hc_lock` 内确认门铃位已清除后再清除活动位。修复后两次全量读取都没有 `OCS f`。

5. 提交等数据写时与 `vnop_blockmap` 互相等待。`cluster_io` 可能只发出一个映射的前一部分（例如一次事务的缓冲区数到了 `max_trans_count` 时截到页边界），剩下的块要等下一轮 `vnop_blockmap` 后才发出；提交此时持有卷写锁等这个映射，blockmap 等这把锁，直到 2 秒超时。超时后提交丢掉这条映射照常写检查点，检查点可能指向还没写入的块，等待期间卷上其他文件操作也都阻塞。现在映射 20 ms 内没有发完时，提交放开写锁，等全部发出再取回锁（第 4 节）。第一版修复放开锁后，任何一次唤醒（例如在途写归零）都会重新取锁，映射还没发完又放开，每次取锁都排在其他等锁的线程后面，开机时单次等待达到 1～3 秒。`vnop_blockmap` 原先在分配新块后、登记映射前就可能因事务满而提交，现在先登记映射，事务满时交给定时提交线程。
6. panic 日志写不出去：`loader_panic_sync_ufs` 屏蔽中断后调用 `annibale_ufs_var_io`，后者在中断关闭时返回 `EBUSY`。现在改走 `ufshc_write_polled`，并且只在发生 panic 后写（第 7 节）。原先每次退回 loader 和 `hv_wdt_pet` 都会调用这条路径，有了可用的写路径后，不加这个条件会在每次退回时覆盖上一次的 panic 日志。
7. 两个处理器同时 panic 时日志正文损坏。原先的锁等 100 万次失败后照样写，两个处理器会同时改写同一个缓冲区。这次 panic 中还出现了一次 `ml_set_interrupts_enabled` 的部分屏蔽断言（DAIF 为 `0xc0`），引起第二次 panic，没有回溯，调用点不确定。现在锁等不到就放弃，屏蔽 A、I、F 三位，轮询写先等上一次写完成，详见第 7 节；修复后的一次测试没有再出现这个断言。

### 8.5 未完成事项与第二阶段收尾（2026-11-16）

- 物理拔电／长按硬断电后的 `fsync` 读回未在无人值守轮次执行（会进入需人工按键恢复状态）；已在 `ufshc_write_polled` 补齐 64 KiB 分块 `FUA`（`cdb[1] = 0x08`）与轮询 `SYNCHRONIZE CACHE(10)`（`0x35`），消除 SoC 复位时 UFS 易失写缓存丢失末尾 32 KiB 块的问题，并在双核并发 `panic_test=4` 复位后完整验证校验和读回（`stage2-r4`）。
- panic 跨核停止与调用栈回溯已在第二阶段补齐（`stage2-r4`）：`GenericARMPE::haltRestart` 忽略非终态通知，`model_dep.c` 增加 `psci_panic_stop_loser`、跳过空 `coresight_base` 的 `dbgwrap` 并放宽 `DebuggerXCallEnter` 同步等待上限至 100 ms，`loader_return.c` 提取 `panic_info` 文本段；双核并发 `panic_test=4` 后 `/private/var/db/panic.log` 完整产出 4 核寄存器、26 帧回溯与 `Stackshot Succeeded`（298,754 字节）。
- 持久化 NVRAM 与 `darwin_nvram` 分区（含 `ufs_native=0` 经 loader 块服务写回与解锁后亮度保留）已完成真机验证，见[持久化 NVRAM](2026-11-16-persistent-nvram.md)。
- 内核 `ramfs_disk*.inc` 与 `init` 按 ANNFS 挂载路径已在第二阶段移除（`S25` 结案）；保留 `annfs-to-apfs.py`、`apfs-tool annfs` 与 `annfs-inspect.py` 供旧安装迁移，`darwin_var` 非 APFS 时 `init` 输出迁移提示并停机。APFS 下实测卸载 183.7 MB `Weibo` 耗时 5.76 s、卸载 24.4 MB `bili` 耗时 0.43 s、覆盖重装耗时 5.35 s（`S21`、`S23` 结案）。
- 已知限制：`readdir` 按条目位置续读，目录在两次续读之间变化时可能重复或跳过条目；打开中的孤儿文件 `fstat` 报 `nlink` 为 1；暂不维护写入代数（`va_write_gencount`）。
