# Safari 下载与「我的 iPhone」：FileProvider 对文件系统的要求

Safari 下载完成后，文件要交给 FileProvider 的 LocalStorage 域，落到「文件」App「我的 iPhone」的「下载」目录。这条路径在本机上依次卡在七处：开机没有 persona，`/private/var` 不回答 sync-root fsctl 和 `FSIOC_CAS_BSDFLAGS`，不支持文档 ID、`RENAME_EXCL`、目录统计请求和写入代数。本文记录每一处的现象、原生行为和修复位置，真机结果见第 9 节。

## 1. 开机补齐 persona

- 现象：`usermanagerd` 没有建立系统与用户 persona，fileproviderd 拿不到用户会话，LocalStorage 域不出现。
- 原因：启动参数 `rd=md0` 让 `launchd` 跳过开机任务，`usermanagerd --init` 是其中之一。
- 修复：用户态 `userland/rc.launchd` 在 `exec /sbin/launchd.ios` 之前运行 `/usr/libexec/usermanagerd --init`，与原生开机任务做同一件事。开机后 persona 99、199、100、1000、200 都存在。
- 另一条路：`launchd` 读 `kern.bootargs`，其中含字面串 `rd=md0` 时打印「Restore environment starting.」并按恢复环境处理。内核在 `bsd_init.c` 与 `IOKitBSDInit.cpp` 里对 `rd` 与 `rootdev` 一视同仁，`xnuloader/mkstandalone.py` 的默认参数两个都给了，只留 `rootdev=md0` 时根盘不变、`launchd` 不再判为恢复环境。代价是 `launchd` 内置的开机任务会按非恢复模式执行。`/sbin/launchd` 内嵌的任务表里，`mount-phase-1`、`mount-phase-2`（`mount -P 1`／`-P 2`）、`fsck`、`dirs_cleaner`、`launchd_cache_loader` 标了 `RequireSuccess` 与 `RequireRun`，`data-protection`（`seputil`）、`fsck-safe`、`tzinit` 标了 `RequireSuccess`，`recovery-mode` 会执行 `nvram auto-boot=false`；`usermanagerd --init` 本身只标了 `AllowCrash`。这些任务在本机的 `/private/var` 直写持久化、没有 SEP 的条件下能否通过没有验证，`nvram` 一项还会写引导变量，所以没有在真机上直接试。

## 2. sync-root fsctl

LocalStorage 域把自己的 `File Provider Storage` 目录标为 sync root，并用 `'J' 72`（设置与读取）和 `'J' 74`（最近的 sync-root 祖先）检查每一项。ramfs 在 `ramfs_fsctl.inc` 回答这三个调用，标记随节点保存。

## 3. `FSIOC_CAS_BSDFLAGS`

revisiond 用 BSD flags 的比较交换给 LocalStorage 新建的每一项设置 `UF_TRACKED`。`vfs_syscalls.c` 检查调用者的权限后把交换交给文件系统，HFS 与 APFS 都实现了它。ramfs 不回答时返回 `ENOTTY`，「下载」目录建不出来。`ramfs_cas_bsdflags()` 在挂载锁内读出当前 flags 写入 `actual_flags`，与 `expected_flags` 相同才换成 `new_flags`。

## 4. 文档 ID

- 现象：LocalStorage 扩展报 `fgetattrlist(3) failed; error 22`，随后 `GSLibraryGetOrAllocateDocumentId failed`，`createItemBasedOnTemplate` 返回 POSIX 22，fileproviderd 报错，`DOCDownloadSettings` 取不到下载目录，Safari 显示任务失败。
- 调用：systrace 记录到 `fgetattrlist`，common 属性 `0x140000`（`ATTR_CMN_FLAGS | ATTR_CMN_DOCUMENT_ID`），选项 `0x20`（`FSOPT_ATTR_CMN_EXTENDED`），返回 22。请求里没有 `ATTR_CMN_RETURNED_ATTRS`，文件系统不提供 `va_document_id` 时 `getattrlist` 返回 `EINVAL`。
- 原生行为：APFS 给带 `UF_TRACKED` 的项分配卷内唯一的文档 ID，并在卷能力里报告 `VOL_CAP_FMT_DOCUMENT_ID`。
- 修复（内核 ramfs）：
  - `ramfs_track()` 在节点带 `UF_TRACKED` 且还没有文档 ID 时，从挂载的计数器分配一个。新建、克隆、`setattr` 改 flags 和 CAS 四处调用它。
  - `getattr` 返回 `va_document_id`，卷能力加上 `VOL_CAP_FMT_DOCUMENT_ID`。
  - 文档 ID 写进 `darwin_var` 的节点记录，记录格式升到版本 3，恢复时重建计数器。内核不读取旧版本的记录，旧数据盘挂载失败，要先清空元数据槽位再开机重建 `/private/var`，步骤见[双系统部署手册 §3](../plan/dual-boot-setup.md#3-写入-ios-系统盘)。

## 5. `RENAME_EXCL`

- 现象：fileproviderd 把占位文件移进「下载」目录时，`renameatx_np()` 带 `RENAME_EXCL` 调用失败，下载失败。
- 调用：VFS 层确认目标名不存在后，把 `VFS_RENAME_EXCL` 交给 `VNOP_RENAMEX`；ramfs 之前只接受无标志和 `VFS_RENAME_SWAP`，其余返回 `ENOTSUP`。
- 修复：`ramfs_renamex()` 把 `VFS_RENAME_EXCL` 按普通重命名处理，在挂载锁内发现目标名已存在时返回 `EEXIST`，与 APFS 一致。

## 6. 目录统计请求

- 现象：LocalStorage 扩展的 `identifierForItemAtURL` 返回 `ENOTTY`，下载在占位文件移进「下载」之后被回滚。
- 调用：扩展给包类项目取标识前发 `APFSIOC_MAINTAIN_DIR_STATS`（`'J' 2`，参数为 `uint64_t` 标志）。Safari 的 `NAME.download` 占位由 BrowserEngineKit 的 Intermediary 进程建成空的普通文件，所以文件也会收到这个请求。
- 修复：ramfs 不维护目录统计，`ramfs_ioctl()` 对这个请求直接返回 0。统计查询（`'J' 32`）仍不回答，FileProvider 与 libc 的 `dirstat_np()` 收到错误后改为遍历目录。

## 7. 写入代数

- 现象：`identifierForItemAtURL` 的 `fgetattrlist` 返回 22。
- 调用：common 属性 `0x6180009`，其中 `0x80000` 在 `FSOPT_ATTR_CMN_EXTENDED` 下是 `ATTR_CMN_GEN_COUNT`。和文档 ID 一样，文件系统不提供 `va_write_gencount` 时 `getattrlist` 返回 `EINVAL`。
- 原生行为：APFS 与 HFS 给普通文件保存写入代数，内容每变一次加一，并在卷能力里报告 `VOL_CAP_FMT_WRITE_GENERATION_COUNT`。
- 修复：节点新增 `rn_write_gen`，`ramfs_touch()` 在非目录内容变化时加一，回绕时跳过 0；`getattr` 返回它，卷能力加上对应位。代数存进节点记录原来的保留字段，记录格式仍是版本 3，旧记录读出 0，表示内容还没变过。

## 8. 修复位置

| 层 | 文件 |
|---|---|
| 用户态启动 | `hackios-xnu-userland/userland/rc.launchd` |
| 内核 ramfs | `xnu/files/bsd/miscfs/ramfs/ramfs_fsctl.inc`、`ramfs.c`、`ramfs_vnops.inc`、`ramfs_getattr.inc`、`ramfs_clonefile.inc`、`ramfs_rename.inc` |
| 持久化格式 | `ramfs_disk.inc`、`ramfs_disk_restore.inc`、`ramfs_disk_mount.inc`，主机工具 `tools/annfs-inspect.py` |

## 9. 真机结果

2026-11-09 真机验证，内核源码与提交 `01dc100f` 一致：

- Safari 下载 4,001,101 字节的 IPA 完成，文件写入 LocalStorage 的 `File Provider Storage/Downloads`。
- 「文件」App「我的 iPhone > 下载」显示这个文件，大小 4 MB。
- IPA 管理器「安装包」列表显示这个文件，从这里安装的应用见 [IPA 管理器的签名](2026-11-09-appinst-codesign.md)。
- 截图与 systrace 日志保存在本地调试目录 `out/s1109/`。
