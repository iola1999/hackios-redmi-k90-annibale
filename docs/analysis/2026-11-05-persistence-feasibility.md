# 跨开机保留数据的可行性（2026-11-05）

用户希望 iOS 的设置、加入过的 Wi-Fi 和装上的应用在重启后保留，前提是不刷写、不调整 Android 原有分区。本文只做调研，没有起轮，也没有写闪存。

## 1. 结论

- 现有代码已经能把 `/private/var` 打包成一份带校验的归档（`var_store save`），也能在开机时把归档展开回去（`var_store load`，开机种子走的就是这条路）。缺的是归档存放的位置。
- 不写闪存的做法只有「停轮时交给电脑、下次开机带回来」，现在只在不带 GPU 的轮次可用，日常使用用不上。
- 可行的位置是 DSU 系统盘槽位的尾部：`dsu.py install` 把 5.3 GB 的系统盘补零到 16 GiB 的槽位，后面 10 GiB 多是这个项目自己的空间，loader 每次开机已经在读这个槽位。写这里要由 loader 往 userdata 分区里 DSU 文件所在的扇区写数据，这一步需要用户决定（§4）。

## 2. 已有的部件

| 部件 | 现状 | 出处 |
|---|---|---|
| 归档格式 | 两个槽位轮流写，先清零槽头，再写归档，最后写槽头；`load` 先校验 CRC-32 再展开，归档损坏时保持空白的 `/private/var` | `hackios-xnu-kernel/userland/src/var_store.c` 文件头 |
| 停轮时保存 | `var_store watch` 向内核登记，回到 loader 前内核等它保存，有超时 | `var_store.c`、内核 `redwood_ufs.c` 的 `redwood_var_save_on_return` |
| 开机展开 | `var_store=1` 时 init 用根镜像里的 `etc/var.seed` | `tools/k90auto/package.py` 的 `SEED` |
| loader 写闪存 | 只在命令行有 `ufs_write=1` 时服务写请求，范围限定在 POCO X5 Pro 的 `darwin` 分区，写后回读比较 | `xnuloader/loader_03_ufs_block_watch.inc` |
| DSU 读取 | 从 `/metadata` 里 `lp_metadata` 的 `system_gsi` 表项取扩展区（userdata 的扇区号），整份读进常驻内存 | `xnuloader/loader_dsu.inc` |

K90 上没有 `darwin` 分区，`var_store` 的闪存路径用不上，开机种子靠根镜像带入，根镜像只剩约 40 MB 的余量。

## 3. 三种存放位置

| 位置 | 写闪存 | 容量 | 问题 |
|---|---|---|---|
| 电脑（停轮时经 `outbox` 取回，下次作为种子带入） | 不写 | 受根镜像余量约 40 MB 限制，超出要改走 USB 收件区 | `outbox` 只在不带 GPU 的轮次可用；手机要连着电脑结束这一轮 |
| DSU 系统盘槽位尾部 | 写 userdata 分区里 DSU 文件的扇区 | 槽位 16 GiB，系统盘 5.3 GB，尾部可留几 GB | 需要 loader 的写路径；DSU 重装时数据随之清空 |
| DSU 的 userdata 镜像（安装时建的 2 GiB） | 同上 | 2 GiB | `lp_metadata` 里这个分区的名字与扩展区没有核对过 |

第二种最直接：loader 已经解析出槽位的扩展区并且整份读入，开机时多读尾部一段就能交给 `var_store load`，不经过根镜像，也就没有 40 MB 的限制。

## 4. 风险与需要的决定

- 写入落在 userdata 分区上。扩展区算错会写坏 Android 的用户数据，后果无法撤销。写之前至少要做三项核对：每次开机重新解析 `lp_metadata`；槽位开头的扇区与电脑上记录的系统盘哈希一致（`dsu.py record` 已经按 MiB 记了 SHA-1）；写入范围不越过槽位末尾和系统盘之后的约定起点。
- 在 Android 里丢弃 DSU 之后，那片扇区会还给文件系统。loader 找不到 `lp_metadata` 时必须不写，这一条要有离线测试。
- 用户说过暂不刷写、调整 Android 原有分区。DSU 槽位是 Android 自己的 DSU 安装程序分配的文件，不改分区表，也不改分区大小，但写入仍然发生在 userdata 分区的扇区上，属于这句话的边界情况，要用户确认后再做。
- 第一步可以只读：loader 解析并打印槽位尾部的范围、读出尾部第一个扇区，确认全是零。这一步不写闪存，可以先做。

## 5. 实施顺序（确认后）

| 步 | 内容 | 判据 |
|---|---|---|
| 1 | loader 只读：打印槽位尾部的扩展区，读出尾部开头 | 范围在槽位内，内容全零 |
| 2 | loader 写路径：复用 `loader_03_ufs_block_watch.inc` 的写与回读，目标改为 DSU 尾部，范围检查放在写函数里 | 离线测试覆盖越界、`lp_metadata` 缺失、哈希不符三种拒绝 |
| 3 | 停轮时保存：`var_store watch` 的归档经内核交给 loader 写入尾部两个槽位之一 | 回读一致，日志有槽位号与 CRC |
| 4 | 开机读入：loader 读尾部最新的有效槽位，`var_store load` 展开 | 重启后设置项、加入过的 Wi-Fi、装上的应用还在 |
