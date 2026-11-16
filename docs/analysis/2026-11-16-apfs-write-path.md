# 可写 APFS：事务引擎与 VFS 接入（2026-11-16）

适用范围：`hackios-xnu-kernel`（`k90-port`）的 [bsd/miscfs/apfs](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/) 与 `hackios-xnu-userland`（`k90-port`）的 [tools/apfs](../../hackios-xnu-userland/tools/apfs/)，随本文同批提交。验证范围只有主机测试和内核编译，真机未验证。init 按 `darwin_var` 的格式选择挂载方式，分区转为 APFS 之前 `/private/var` 仍是 `ANNFS001`（ramfs）。

## 1. 结论

- 写入引擎已重写为单个打开事务加检查点提交。B-tree 支持多层分裂与合并，空间管理器支持多个 chunk，卷与容器两级对象映射和检查点环都随提交推进。旧的 `apfs_txn.inc`、`apfs_txn_btree.inc`、`apfs_write_ops*.inc` 已删除。
- 内核 VFS 已接到新引擎。文件内容走 UBC 与 cluster 层（`vnop_blockmap`、`vnop_strategy`），与 ramfs 对齐的接口均已实现，详见第 5 节。
- 挂载时未带 `MNT_RDONLY` 且卷可写即为可写挂载，boot-arg `apfs_rw=0` 强制只读。系统卷、cryptex 与 `/annibale` 都以 `MNT_RDONLY` 挂载，行为不变。
- `darwin_var` 块 0 是 APFS 容器超级块时，init 把 Data 卷挂到 `/private/var`，否则挂 ramfs。`tools/apfs/annfs-to-apfs.py` 把现有的 `ANNFS001` 分区原地转为 APFS，panic 日志和背光设置改存到容器之外的分区末尾 32 MiB（第 7 节）。真机验收见第 8 节。

## 2. 事务模型

引擎代码在 `apfs_wbt.inc`（B-tree）、`apfs_wspace.inc`（空间管理器）、`apfs_wtx.inc`（事务与提交）、`apfs_wfs.inc`（文件系统记录）、`apfs_wops.inc`、`apfs_wxattr.inc`、`apfs_wclone.inc`（操作），模型说明在 `apfs_wtx.h`。

- 同一时刻只有一个打开的事务。改动过的元数据块留在内存覆盖层（overlay），读路径 `nx_block` 先查覆盖层，所以同一事务内的读能看到未提交的改动。
- 每个操作先完成查找、检查和空间预留，第一次修改之后的失败（设备错误或内存耗尽）会作废整个事务，挂载转为只读，上一个检查点保持有效。
- 提交顺序：等已映射的数据写完成（第 4 节），写出全部新元数据块、检查点映射和临时对象，刷盘，写容器超级块，再刷盘，最后更新块 0 的副本。刷盘通过 `DKIOCSYNCHRONIZECACHE`。
- 数据块在把它们移出文件的那次提交之后才释放（`wsp_free_later`），同一事务内分配又释放的元数据块立即回收。
- 分配出去的块会从元数据缓存中清掉（`wsp_taken`），见第 6 节的问题 2。

## 3. 提交时机

- 第一次改动后约 1 秒（`APFS_WCOMMIT_MS`）。定时提交先把上次提交后写过的文件的脏页推到设备（`apfs_wpush`），再提交。
- 事务中脏元数据块超过 4096 块时，在当前操作末尾立即提交。
- `fsync(2)`（该文件有未提交改动时）、`F_FULLFSYNC`、`F_BARRIERFSYNC`、`IO_SYNC` 写、`sync(2)` 和卸载时提交。`F_FULLFSYNC` 在没有未提交改动时只刷盘。
- 断电时可能丢失的范围：最后约 1 秒内未经 fsync 的改动。已有数据块的原地覆盖不经过检查点，断电时这些块可能是新旧混合内容；元数据始终停在某个完整的检查点。

## 4. 数据路径与写入顺序

- 可写挂载上未压缩的普通文件用 `cluster_read`、`cluster_write`、`cluster_pagein`、`cluster_pageout`。压缩文件保留原读路径，写入和截断返回 `EPERM`。
- `vnop_blockmap` 在写映射时给空洞分配新块，已有块原地写。每个写映射都登记到 `wm_map`，`vnop_strategy` 发出对应缓冲区时扣除，并给缓冲区装上完成回调计入 `wm_io`。
- 提交在持有卷写锁的情况下等 `wm_map` 清空且 `wm_io` 归零，最多等 2 秒（`APFS_WDRAIN_MS`），超时打印一行日志后继续。持锁期间不会产生新的写映射，所以检查点不会指向内容还没写到设备的块。
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
| `annfs-to-apfs.py` 在模拟的 adb 上执行转换、重复执行、`--rollback` 与 `--format` | 转换后逐项比对一致，`apfsck -cw` 无错误；重复执行不改动分区；回退后分区与原分区逐字节相同 |

随机测试按模型逐项比对目录树、内容、扩展属性、链接数与设备号，并对每轮结果运行 `apfsck`。本轮测试查出并修复了下面两个问题。

1. `wr_next` 读取下一条记录时按 4096 字节容量往调用方的 64 字节缓冲区拷值，记录值较长时越界写栈（ASan 报 `stack-buffer-overflow`）。改为由调用方传入缓冲区容量。
2. 提交后释放的元数据块在下一个事务里被分配为数据块（如扩展属性数据流），元数据缓存中仍有旧内容，经 `apfs_read_stream` 读到旧数据。改为分配时清掉这些块的缓存条目。

## 7. 分区末尾与迁移

APFS 容器比 `darwin_var` 小 32 MiB。末尾这 32 MiB 不属于容器，由内核直接读写（[annibale_var_tail.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_var_tail.inc)），以后划为独立分区 `darwin_nvram` 时不影响容器。

| 相对末尾 32 MiB 起点的偏移 | 内容 |
|---|---|
| 0 | 预留给 NVRAM |
| 1 MiB | 背光设置，一个 4 KiB 块（`BLS3` 记录，带 CRC32） |
| 16 MiB | panic 日志，格式与 ANNFS 时相同（`KLOG` 头加文本） |

- 内核启动时读一次 `darwin_var` 块 0：第 32 字节起是 `NXSB` 时按上表使用末尾，否则沿用 ANNFS 的位置（背光在超级块，panic 日志在 64 MiB）。块 0 读出之前不写 panic 日志。
- 背光设置在亮度变化后约 1 秒写出一次，退回 loader 时补写尚未写出的一次。
- 退回 loader 时（`annibale_var_save_on_return`）先把 APFS 卷全部文件的脏页同步写到设备，再提交。
- init 挂载后读 `kern.annibale.panic_log`，把上一次运行的 panic 日志存为 `/private/var/db/panic.log`，再写这个 sysctl 把它标记为已保存。`var_apfs=1` 启动参数已删除。
- ramfs 在元数据槽无效且前 64 MiB 非零时拒绝挂载，不会格式化 APFS 分区。

迁移在 Android root 下经 adb 执行 [annfs-to-apfs.py](../../hackios-xnu-userland/tools/apfs/annfs-to-apfs.py)，数据块原地不动：

1. 读出 `darwin_var` 前 512 MiB 和末尾 32 MiB 保存到本地，传输都用 SHA-256 校验。ANNFS 的两个元数据槽和 panic 日志在前 512 MiB，数据页从 512 MiB 开始。
2. `mkapfs.py --blocks` 在主机上建一个与分区减 32 MiB 等大的空容器，卷角色为 Data。`apfs-tool annfs`（[cmd_annfs.c](../../hackios-xnu-userland/tools/apfs/cmd_annfs.c)）读较新的有效元数据槽，在容器里重建根目录可达的全部对象：inode 号（小于 16 的另行分配）、权限、属主、BSD 标志、四个时间、保护类、文档 ID、同步根标记、扩展属性和硬链接。普通文件的 extent 直接指向原数据页，ANNFS 第 n 页（16 KiB）对应 APFS 块 131072 + 4n 起的 4 块。
3. ANNFS 按 next-fit 在整个分区分配数据页，落在末尾 32 MiB 的页由转换器复制到 512 MiB 以内的新块。转换中的其他分配也都在 512 MiB 以内，所以写回手机的只有镜像的前 512 MiB，脚本在写回前检查镜像 512 MiB 之后没有内容。
4. 写回前 512 MiB 并读回比对。`--rollback` 写回保存的前 512 MiB，分区恢复为 ANNFS，APFS 下的改动丢失。`--format` 不转换，直接建空的 APFS 数据卷。

ANNFS 不记录设备号，迁移后字符设备的设备号为 0；套接字和没有目录项指向的对象不迁移。

## 8. 未完成事项与真机验收

- 真机迁移：在测试机上执行 `annfs-to-apfs.py`，迁移前在 iOS 下记录 `/private/var` 全部普通文件的大小与 SHA-256，迁移后逐一比对；应用、Wi-Fi 网络与设置保留。
- 真机验收：创建、删除、重命名、硬链接、克隆、扩展属性、`mmap` 写入后重启读回；fsync 后立即断电再读回；`kern.apfs_wstats` 无提交失败；背光设置与 panic 日志跨重启保留；主机 `apfsck` 检查拉回的 `darwin_var` 镜像。
- 背光设置目前是自定义记录。计划改为 NVRAM：loader 从末尾的 NVRAM 区读入 `nvram-proxy-data`，内核注册 NVRAM 控制器写回，背光走 `backlight-nits` 变量。
- 真机验收通过后删除 `ramfs_disk*.inc`，并更新 Release 说明与升级步骤。
- 已知限制：`readdir` 按条目位置续读，目录在两次续读之间变化时可能重复或跳过条目；打开中的孤儿文件 `fstat` 报 `nlink` 为 1；不维护写入代数（`va_write_gencount`）。
