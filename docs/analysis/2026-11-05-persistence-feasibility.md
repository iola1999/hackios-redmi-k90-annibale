# 跨开机保留数据的可行性（2026-11-05）

用户希望 iOS 的设置、加入过的 Wi-Fi 和装上的应用在重启后保留，前提是不刷写、不调整 Android 原有分区。本文只做调研，没有起轮，也没有写闪存。

## 1. 结论

- 现有代码已经能把 `/private/var` 打包成一份带校验的归档（`var_store save`），也能在开机时把归档展开回去（`var_store load`，开机种子走的就是这条路）。缺的是归档存放的位置。
- 不写闪存的做法只有「停轮时交给电脑、下次开机带回来」，现在只在不带 GPU 的轮次可用，日常使用用不上。
- 可行的位置是 DSU 系统盘槽位的尾部：`dsu.py install` 把 5.3 GB 的系统盘补零到 16 GiB 的槽位，后面 10 GiB 多是这个项目自己的空间，loader 每次开机已经在读这个槽位。写这里要由 loader 往 userdata 分区里 DSU 文件所在的扇区写数据。用户 2026-11-05 要求做这一项，写入是否可行、对 Android 有什么影响见 §6。

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
- 用户说过暂不刷写、调整 Android 原有分区。DSU 槽位是 Android 自己的 DSU 安装程序分配的文件，不改分区表，也不改分区大小，写入发生在 userdata 分区里这个文件的扇区上。2026-11-05 用户要求做跨开机保留，先评估影响（§6），暂不改动。
- 第一步可以只读：loader 解析并打印槽位尾部的范围、读出尾部第一个扇区，确认全是零。这一步不写闪存，可以先做。

## 5. 实施顺序（确认后）

| 步 | 内容 | 判据 |
|---|---|---|
| 1 | loader 只读：打印槽位尾部的扩展区，读出尾部开头 | 范围在槽位内，内容全零 |
| 2 | loader 写路径：复用 `loader_03_ufs_block_watch.inc` 的写与回读，目标改为 DSU 尾部，范围检查放在写函数里 | 离线测试覆盖越界、`lp_metadata` 缺失、哈希不符三种拒绝 |
| 3 | 停轮时保存：`var_store watch` 的归档经内核交给 loader 写入尾部两个槽位之一 | 回读一致，日志有槽位号与 CRC |
| 4 | 开机读入：loader 读尾部最新的有效槽位，`var_store load` 展开 | 重启后设置项、加入过的 Wi-Fi、装上的应用还在 |

## 6. DSU 的写入与对 Android 的影响

结论：能写。dada 的 loader 已经在同一种 DSU 文件里原地写数据；风险集中在写错位置，由 loader 端的范围检查、头部哈希核对和回读控制。Android 平时的使用不读这个文件，正常写入不影响 Android（推断，首次写入后要在 Android 里核对）。

### 6.1 为什么能写

- DSU 镜像是 userdata 上的一个固定（pinned）文件，libfiemap 经 dm-linear 直接映射到原始分区写入，没有经过元数据加密，所以存储上的字节就是镜像本身（`hackios-xnu-kernel/xnuloader/loader_dsu.inc` 文件头）。loader 每次开机按 `lp_metadata` 里 `system_gsi` 的扩展区读这个文件，iOS 从读到的内容启动，说明扇区位置与明文这两点在本机成立。
- dada 的 loader 有 `dsu_write`（`dada:base/xnuloader/loader.c:4522`）和 `oem dsu patch`：只在 `system_gsi` 的扩展区内写，每段写完 flush 并回读比较；`dada:base/tools/dada-dsu.sh patch` 用它只发送系统盘里变化的 1 MB 片。我们的 `loader_dsu.inc` 移植自同一份代码，没有带写入部分。
- 我们的 loader 已有写闪存并回读的代码（`loader_03_ufs_block_watch.inc`，`ufs_write=1` 时服务，范围限定在 POCO X5 Pro 的 `darwin` 分区），换目标即可复用。

### 6.2 对 Android 的影响

| 方面 | 影响 | 依据 |
|---|---|---|
| 文件系统 | 只改 DSU 文件自己的数据块，不改文件系统元数据和文件大小 | 写入范围限定在扩展区内 |
| 垃圾回收与 TRIM | 固定文件的块不会被文件系统搬走或丢弃 | AOSP libfiemap 写 DSU 文件时固定文件，未在本机核对 |
| Android 日常使用 | DSU 已安装、未启用，Android 开机不读也不校验这个文件 | 推断，首次写入后在 Android 里看 `gsi_tool status` 与开机是否正常 |
| 丢弃 DSU | 开发者选项、DSU 通知或 `dsu.py install --replace` 会删掉文件，存档随之消失；扇区还给文件系统，loader 之后不得再写 | 每次开机重新解析 `lp_metadata`，找不到就不写 |
| 写错位置 | 写坏 userdata 上 Android 的加密数据或文件系统元数据，无法撤销，可能要清除数据才能恢复 | 由 §4 的三项核对和回读防止 |
| Android 系统更新 | 已装 DSU 时 Android OTA 的行为没有核对 | 未知 |
| 闪存寿命 | 每次停轮写一份 `/private/var` 归档（几十 MB 量级），影响可以忽略 | 推断 |

### 6.3 顺带的好处

同一条写入路径可以像 dada 一样只更新系统盘变化的部分，系统盘改动后不必再从 Android 重装 DSU；`dsu.py record` 已经按 MiB 记下手机上每片的 SHA-1。

