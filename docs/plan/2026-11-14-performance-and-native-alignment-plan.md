# 性能与原生硬件对齐改造方案（2026-11-14）

本文针对 [全工作区早期过渡方案与性能瓶颈源码审计](../analysis/2026-11-14-temporary-architecture-audit.md) 查明的 **6 项 P0**、**8 项 P1** 与 **4 项 P2** 问题给出可直接编码落地的架构设计与硬件中断寄存器参数，并明确数据结构契约、子 Agent 文件切分边界与真机验收判据。

所有改造严格遵守仓库原生对齐红线（见 [AGENTS.md](../../AGENTS.md) §2 与 §6）：单文件代码控制在 `1200` 行以内，按职责拆入独立 `.c` 或 `*_private.h`/`*.inc`；严禁用方法交换掩盖问题或保留轮询绕过底层硬件契约。

## 1. 跨模块核心契约与关键架构决策

本节集中定义影响多个子系统的底层接口、数据模型与安全回退边界，作为后续 4 个实施批次的前置准则。

### 1.1 统一 `apps_smmu`（`0x15000000`）Stage-1 页表服务

当前 `annibale_iris_hw.c` 内置了私有的 39 位三级 Stage-1 页表构建器（`SID 0x1940/0x1947`），`annibale_camera_smmu.inc` 对 `SID 0x1c00` 采用旁路映射，`MiniIOMobileFramebuffer` 与 `lx_pci` 尚未建立各自的 `apps_smmu` 页表。

- **新建内核公共组件**：新增 `hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_apps_smmu.c` 与 `sys/annibale_apps_smmu.h`，统一管理 `apps_smmu@0x15000000`（`qcom,qsmmu-v500`）的 `SMR` 槽位、Context Bank 分配、4 KiB/2 MiB 三级 Stage-1 页表与按 ASID 的 `TLBIVA` 局部失效。
- **设备域划分与属性契约**：
  - **显示域（`SID 0x0800`）**：IOVA 窗口 `0xc0000000 + 0x3fc00000`，页属性使用 `PTE_NORMAL_WB`（Inner Shareable 硬件缓存一致）。切换 UEFI 交接的 `SMR 0x0800` 前，先在同一 Context Bank 内为 `0xfc800000 + 0x2b00000`（`splash_region`）建立恒等映射，确保面板当前在扫帧在切换瞬间零缺页故障。
  - **视频域（`SID 0x1940` 非像素 / `SID 0x1947` 像素）**：复用统一页表分配器，支持 `MiniIOSurface` 物理页直接映射为 HFI `OUTPUT`/`INPUT` 缓冲。
  - **相机域（`SID 0x1c00`）**：36 位 IOVA 空间，映射连续采集环形缓冲池（`PTE_NORMAL_WB` Inner Shareable）。
  - **PCIe 网络域（`SID 0x1400`）**：IOVA 窗口 `0x98000000 + 0x80000000`（避开 MSI 地址窗），映射可缓存 `mbuf`/Skywalk 包池。

### 1.2 `MiniIOSurface` 物理页散聚导出与 UBWC v4/v5 平面布局契约

显示直扫与 Iris/相机零拷贝读写，以及 Adreno UBWC 渲染全部以 `MiniIOSurface` 为共享载体，需在 [MiniIOSurface.cpp](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniIOSurface.cpp) 补齐两项内核契约。

- **物理段导出与 DMA 引用计数**：新增内核接口 `minisurf_lookup_and_pin_pages(uint32_t surface_id, struct minisurf_pseg *segs, uint32_t *nseg_inout)` 与 `minisurf_unpin_pages(uint32_t surface_id)`。当表面正在被 DPU 扫描或 Iris/CAMSS DMA 写入时，通过原子 `dma_pin_count` 延长底层 `IOMemoryDescriptor` 物理页生命周期，防止用户态提前释放表面引发 SMMU 故障。
- **高通 UBWC v4/v5 压缩布局模式**：新增 `MiniIOSurfaceLayout.inc`，对齐 Mesa Turnip `fdl6_layout` 与高通 `VENUS_BUFFER_SIZE` 硬件公式：
  - `BGRA8`/`RGBA8`：宏块 `64 × 16`，分配 `[meta, data]` 两段 `4096 B` 对齐区（`meta_stride = align(DIV_ROUND_UP(w, 64), 64)`，`data_stride = align(w * 4, 256)`）。
  - `NV12`（`420v`/`420f`）：按 `[Y_meta, Y_data, UV_meta, UV_data]` 四段 `4096 B` 对齐布局分配（`Y` 宏块 `32 × 8`、`UV` 宏块 `16 × 8`，步幅 `128 B` 对齐）。
  - **启用条件**：仅在 DPU SSPP 硬件直扫（第 2 批 §3.1）上线后，对无 CPU 直接像素锁定的 GPU/显示/视频表面默认开启 UBWC（可控参数 `surf_ubwc=1`）；若进程对 UBWC 表面调用 `IOSurfaceLock` 请求 CPU 读写，按需触发单次 GPU 解铺平或对带 CPU 访问提示的表面保持线性分配。

### 1.3 可写 APFS 正式接管 `/private/var`（下线 `ANNFS001`）的准入条件

当前 [init_mount.inc](../../hackios-xnu-userland/userland/src/boot/init_mount.inc) 已将内核写能力开关 `apfs_rw=1` 与 `/private/var` 挂载切换开关 `var_apfs=1` 解耦。正式默认开启 `var_apfs=1` 并下线 [ramfs_disk.inc](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_disk.inc) 前必须同时满足四项硬条件。

- 补齐目录、符号链接、硬链接、`rename`、`AF_UNIX` 套接字节点（`mknod`）、扩展属性写删及可写 `mmap`/`pageout` 全部 VNOP。
- 写路径切入 XNU UBC `cluster_write`/`cluster_pageout` 与周期检查点合并，消除每 `4 KiB` 检查点写放大。
- UFS 驱动放行 `SYNCHRONIZE CACHE (0x35)` 硬件刷盘屏障并接入 APFS `txn_commit` 超级块落盘序列。
- 提供幂等迁移工具将 `/dev/ufs_darwin_var`（`disk1s2`）上的现存 `ANNFS001` 数据校验导出、格式化为 APFS Data 卷并回灌校验（操作前按 [分区备份与恢复](../backup/README.md) 留存备份）。

### 1.4 `xnuloader` 截图与 `loader_return` 硬件收尾契约

DPU 切入 `MiniIOSurface` 直扫后，运行期不再每帧向 `0xfc800000` 预留区拷贝像素，需同步维护 `loader_return` 收尾与 `fastboot oem screenshot` 诊断能力。

- 在 `loader_return` 停机收尾阶段（`MiniFramebufferQuiesce`），将当前正在扫描的最后一帧写回 `0xfc800000` 预留槽位 A，把 `VIG0`/`VIG1` 切回预留区物理地址并恢复 `SMR 0x0800` 交接态，确保回到驻留 `xnuloader` 后显示与截图工作如初。
- 运行期调试截图走用户态合成器缓冲抓取或按需单帧回读，零日常帧率损耗。

## 2. 第 1 批：存储底座与可写 APFS 完整切换（P0-3 / P0-4 / P1-2 / P1-3）

### 2.1 UFS 散聚零拷贝与中断异步队列（P0-3 与 P1-2）

目标文件：`hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_ufshc.c`、`annibale_ufshc_rw.inc`、`annibale_ufs_rw.inc`，新增 `annibale_ufshc_intr.inc` 控制单文件行数。

- **多段 PRDT 散聚零拷贝（解决 P0-3 中转 `memcpy`）**：
  - 将每个 UTRD 命令描述符的 PRDT 表容量扩至 `64` 项（每项 `16 B` 共 `1 KiB`/槽，单槽最高覆盖 `64 × 4 KiB = 256 KiB` 非连续物理页）。
  - 在 `ufs_strategy(buf_t bp)` 中直接从 `buf_upl(bp)`（经 `upl_page_info` 获取物理页号；内核虚拟缓冲无 UPL 时按页调用 `kvtophys`）合并物理相邻页填入 PRDT，彻底移除 `s->data` `256 KiB` 整块 `memcpy`。
  - `ufshc@1d84000` 在设备树中挂于 `apps_smmu` `SID 0x0060` 且声明 `dma-coherent`。探测期用 1 块只读金丝雀扇区校验缓存一致性：一致态下省去 `FlushPoC_DcacheRegion`；若 UEFI 将 `SMR 0x0060` 置于非一致旁路，则仅对目标物理页做单次定向缓存清理（写前）或失效（读后），消除原先对中转缓冲的双倍刷写。
- **GICv3 SPI 中断与异步 `ufs_strategy`（解决 P0-3 同步阻塞与 P1-2 忙等）**：
  - 调用 `gic_v3_spi_attach(297, false, ufshc_intr, NULL)` 挂载 `ufshc@1d84000` 电平中断（DT `<0 0x109 4>` -> `INTID 297`）。
  - 配置 `UFSHC_UTRIACR` 中断聚合（阈值 `4` 笔完成或超时 `80 us`）并开启 `UFSHC_IE`（`UTRCE | UE | UTPMS`）；在 `annibale_ufs_quiesce` 返回 `xnuloader` 前清零 `UFSHC_IE` 并调用 `gic_v3_spi_mask(297)`。
  - 在 `struct hc_slot` 记录关联 `buf_t bp` 与分段原子计数：`ufs_strategy` 填好 UTRD 敲门铃后立即返回，允许上层 UBC `cluster_read_ext`/`cluster_pageout` 并发填满 31 个硬件槽位；`ufshc_intr` 读取 `~mmio_r32(UFSHC_UTRLDBR) & active_mask` 回收已完成槽位，分段归零时异步回调 `buf_biodone(bp)`。删除 `hc_poller` 零睡眠死循环，仅保留 `500 ms` 超时看门狗。
- **放行硬件刷盘屏障与 TRIM（解决 P1-2 命令拦截）**：
  - 在 `hc_refusal`（`annibale_ufshc_rw.inc`）中对 `hc_write_lun` 放行三类安全命令：`SYNCHRONIZE CACHE(10)`（`0x35`，`UTRD_DD_NONE`，`expected == 0`）、带 `FUA` 位（`cdb[1] & 0x08`）的 `WRITE(10/16)`（LBA 仍严格限制在 `[hc_write_lba_start, hc_write_lba_end)` 内），以及单段 `UNMAP`（`0x42`，`expected == 24`，解析 16 字节块描述符校验起止 LBA 完全落在可写分区范围内）。
  - 在 `ufs_ioctl`（`annibale_ufs_rw.inc`）补齐 `DKIOCSYNCHRONIZECACHE` 与 `DKIOCUNMAP`，供 APFS 检查点提交与 `spaceman` 空间回收直接调用。UFSHCI v4.0 MCQ（`mcq_sqd` `0x01da5000`）作为独立可选增强放入 `annibale_ufshc_mcq.inc`（`ufs_mcq=1`），默认保持与 `xnuloader` `hc_take_back` 兼容的 31 槽位模式。

### 2.2 可写 APFS 完整功能补齐与 UBC 批量检查点（P0-4）

目标文件：`hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/` 下新增 `apfs_vnops_dir.inc`、`apfs_vnops_xattr.inc`，重构 `apfs_vnops_write.inc`、`apfs_txn.inc` 与 `apfs_txn_btree.inc`。

- **补齐 `/private/var` 所需全部 POSIX / Darwin VNOP**：
  - `apfs_vnop_mkdir` / `apfs_vnop_rmdir`：分配 `vol->next_inum++`，写入 `APFS_TYPE_INODE`（`mode = S_IFDIR | perms`，`nchildren = 0`）与父目录 `APFS_TYPE_DIR_REC`（带 UTF-8 规范化 CRC32C 22 位目录哈希键 `j_drec_hashed_key_t`），维护父目录 `nchildren` 及时间戳并同步更新 VFS 名称缓存；`rmdir` 严格校验 `nchildren == 0`（非空返回 `ENOTEMPTY`）。
  - `apfs_vnop_symlink` / `apfs_vnop_link` / `apfs_vnop_mknod`：符号链接目标写入内联扩展属性 `com.apple.fs.symlink`（`APFS_XATTR_DATA_EMBEDDED`）；硬链接递增目标 `nlink` 并插入新 `DIR_REC`；`mknod` 支持 `S_IFSOCK` 与 `S_IFIFO`，绑定 XNU 本地套接字/管道 `specops`，打通 `/private/var/run/syslog`、`launchd` XPC 套接字等系统路径。
  - `apfs_vnop_rename`：在单次容器事务内原子删除源 `DIR_REC`、处理目标覆盖（目录空检查或普通文件递减 `nlink`，`nlink == 0` 且仍有打开引用时挂入卷孤儿链表，在 `apfs_vnop_inactive` 归零时回收 extent）、插入新 `DIR_REC` 并更新被移动 inode 的 `parent_id` 与名称缓存。
  - `apfs_vnop_setxattr` / `apfs_vnop_removexattr`：`<= 3804 B` 走内联 `APFS_XATTR_DATA_EMBEDDED`；更大属性分配独立 `dstream` 对象 ID（`APFS_XATTR_DATA_STREAM` + `APFS_TYPE_FILE_EXTENT` + `APFS_TYPE_DSTREAM_ID`），满足 `containermanagerd`、代码签名与沙盒元数据需求。
- **接入 UBC `cluster_write` / `cluster_pageout` 与周期批量检查点**：
  - 移除 `apfs_vnops_write.inc` 中持 `am_lock` 的 `4096 B` 同步直写循环，改为持每文件 `an_rwlock` 写锁调用 XNU `cluster_write`，将小粒度写入全部吸收到 UBC 页缓存。
  - 实现 `apfs_vnop_pageout`（调用 `cluster_pageout`，单次聚簇最高 `256 KiB`）并在 `apfs_vnop_mmap` 放开可写共享映射：回写时一次向 `spaceman` 申请一段连续物理块，下发单笔大块 `VNOP_STRATEGY` 写 I/O，将 `[logical_off, phys_bno, byte_len]` 记录进当前打开的容器批次事务 `am_open_txn`，旧块登记入延迟释放队列。
  - **事务批次合并（Epoch Checkpointing）**：每个可写容器维持一个活跃内存事务，累积满 `50 ms`、脏元数据块达 `256` 块、收到 `apfs_vnop_fsync`（`MNT_WAIT`）/`apfs_vfs_sync` 或卸载时才统一执行一次 B-tree/OMAP/spaceman CoW 落盘 -> `DKIOCSYNCHRONIZECACHE` 刷盘屏障 -> 写入新 `nx_superblock_t` 检查点 -> 再次刷盘屏障。移除生产路径默认的写后同步读回 `memcmp`（收入诊断参数 `apfs_verify_write=1`）。
- **原地 B-tree 槽位二分与紧凑重排（消除 `1.18 MB`/事务堆分配抖动）**：
  - 重构 `apfs_txn_btree.inc`：删除 `struct rec_slot[512]`（`403,456 B`）整页解包数组，直接在原 `4 KiB` 节点的 8 字节 `kvloc_t` TOC 区做二分查找，将前缀段、新增或修改键值、后缀段按偏移连续拼入单个 `4 KiB` CoW 新块（仅在空闲区不足时再分配 1 个 `4 KiB` 兄弟块分裂），把每次节点修改的堆分配从 `411 KiB` 压至 `4 KiB`。

### 2.3 APFS 读写锁拆分与元数据线性扩展（P1-3）

目标文件：`hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs.h`、`apfs_vfsops.c`、`apfs_vnops.c`、`apfs_lib.c`。

- **读写锁分级**：将 `am_lock` 改为容器/卷读写锁 `lck_rw_t am_rwlock`，并在 `struct apfs_node` 增加每文件读写锁 `lck_rw_t an_rwlock`。只读查找（`lookup`、`getattr`、`readdir`、`pagein` 查 extent）全部并发持 `am_rwlock` 共享读锁；仅在事务切换根块指针时短暂持写锁。
- **清理热路径字符串扫描**：删除 `apfs_vnop_read`/`apfs_vnop_pagein` 中每次获取 `apfs_MetricsLock` 自旋锁执行的 6 次 `strstr` 路径匹配，改用无锁原子计数器。
- **$O(N)$ 游标式 `readdir` 与预读**：在 `apfs_vnop_readdir` 中将目录项 `(hash22 << 42) | child_oid` 编码进 `uio_offset` 游标，后续分段 `getdirentries` 直接以 $O(\log N)$ B-tree `lower_bound` 定位续读，消除从第 0 项重扫的 $O(N^2)$ 退化；未压缩文件读取改走 `cluster_read_ext` 开启顺序预读；`mcache` 扩至 `2048` 项（`8 MiB`）并改为开放寻址哈希加时钟置换。

## 3. 第 2 批：显示 DPU 直扫、UBWC 表面与 Iris 零拷贝（P0-1 / P0-2 / P0-6 / P1-4）

### 3.1 MDSS DPU 12.0 零拷贝硬件直扫与硬件 TE VSync（P0-1 与 P1-4）

目标文件：`hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp`、`MiniFramebufferFlip.inc`、`MiniFramebufferUserClient.inc`，新增 `MiniFramebufferDPU.inc`。

- **双管道硬件缩放与多图层混合（解决 P0-1 `2.91～4.43 GB/s` CPU 拷贝）**：
  - 基于 §1.1 的 `apps_smmu` `SID 0x0800` 页表，在 `SwapSubmit` 时将待显示 `MiniIOSurface` 直接映射为 DPU IOVA（`0xc0000000` 起）。
  - 针对当前 P11 命令模式面板（`1156 × 2510`，`CTL0` 驱动 `LM0` 左半屏 `578 × 2510` + `LM1` 右半屏 `578 × 2510` -> `INTF1`），使用成对 SSPP 管道直扫源表面：主图层 `1206 × 2622` 由 `VIG0` 扫左半幅（源 `0..603 × 2622` -> 目的 `0..578 × 2510`）、`VIG1` 扫右半幅（源 `603..1206 × 2622` -> 目的 `0..578 × 2510`），启用 SSPP 内置 `QSEED4`（`+0xa00`）硬件缩放器（`phase_step_x = (1206 << 21) / 1156`，`phase_step_y = (2622 << 21) / 2510`）。
  - 放开多平面 YCbCr 表面（`NV12` / `P010`）直扫：将平面 0（Y）与平面 1（UV）IOVA 写入 `VIG0`/`VIG1` 的 `SSPP_SRC0_ADDR` 与 `SSPP_SRC1_ADDR` 并配置 CSC 矩阵；叠加 UI 图层分配 `DMA0/DMA1` 与 `DMA2/DMA3`，在 `LM0`/`LM1` 硬件混合器内执行预乘 Alpha 混合，最后写 `FLIP_CTL_FLUSH` 原子提交。硬件管道可覆盖的全部帧直接跳过 `hashRows`、`drawRows` 与预留区写入（仅在图层数超过硬件管道上限时回退合成）。
- **硬件 TE VSync 中断与 3 槽交换队列（解决 P1-4）**：
  - 调用 `gic_v3_spi_attach(115, false, mdss_mdp_intr, this)` 挂载 `mdss_mdp@ae00000` 中断（DT `<0 0x53 4>` -> `INTID 115`），开启 `INTF1` `INTF_TEAR_INT_EN`（绑定面板 `GPIO_86` TE 信号）与 `CTL0` `CTL_START_IRQ`。
  - `INTF_TEAR_INT` 触发时采集精确硬件时间戳上送 IOKit VSync 回调并停用 `8.333 ms` 软件定时器。
  - 将深度 `1` 的覆盖槽位升级为深度 `3` 的环形交换队列：`SwapWait`（`sMethod[5]`）在在途未扫完帧数 `>= 2` 时通过 `assert_wait` 真实阻塞背压；`CTL_START_IRQ` 确认硬件已切入新帧地址后，立即解绑上一帧 `MiniIOSurface` 的 DMA 引用并唤醒 `SwapWait`，彻底删除 `flipSplashPipe` 的 `20,000 us` 忙等循环。

### 3.2 `MiniIOSurface` UBWC v4/v5 全链路压缩接入（P0-2）

目标文件：`MiniIOSurface.cpp`、`MiniIOSurfaceLayout.inc`、`annibalemetal_texture.inc`、`air_metal.c`、`MiniFramebufferDPU.inc`。

- 按 §1.2 契约在 `MiniIOSurface` 落地 `BGRA8`/`RGBA8` 与 `NV12` UBWC 元数据平面偏移计算，通过字典/平面属性向用户态导出 `meta_offset`、`meta_stride` 与 `ubwc_mode`。
- 在 `annibalemetal_texture.inc` 中对带 `ubwc_mode` 的共享 `IOSurface` 启用 Turnip `FD6_UBWC` 布局并绑定元数据地址；在 `air_metal.c` 打开 `ubwc = 1`；在 `MiniFramebufferDPU.inc` 同步配置 SSPP `FETCH_CONFIG`、`UBWC_STATIC_CTRL` 与 `SRC2_ADDR` 元数据平面地址，实现 GPU 写出至 DPU 扫描全链路压缩传输。

### 3.3 Iris VPU `IOSurface` 零拷贝输出、GICv3 中断与硬件编码（P0-6）

目标文件：`hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_iris.c`、`annibale_iris_hfi.c`、`annibale_iris_hw.c`（新增 `annibale_iris_enc.inc`），用户态 `videotoolbox_iris.c`。

- **解码直写 `MiniIOSurface`（解决 `752 MB/s` 刷缓存与 `19.4 万次/秒` `copyout`）**：扩展 `IRIS_IOC_DECODE_FRAME` 传入目标 `CVPixelBuffer` 的 `iosurface_id`；内核通过 `minisurf_lookup_and_pin_pages` 将该表面物理页直接映射入 Iris `apps_smmu`（线性 NV12 走 `SID 0x1940` 或 UBWC `HFI_COLOR_FMT_NV12_UBWC` 走像素域 `SID 0x1947`），按会话维护 16 项 `(iosurface_id -> iova)` LRU 映射表作为 HFI `OUTPUT` 缓冲。VPU 硬件直接解码落入目标 `IOSurface`，删除整帧 `copyout` 循环。
- **挂载 Iris GICv3 中断与每会话异步队列**：调用 `gic_v3_spi_attach(206, false, iris_vpu_intr, NULL)` 挂载 `qcom,vidc@aa00000` 中断（DT `<0 0xae 4>` -> `INTID 206`）。ISR 清除 `WRAPPER_INTR_STATUS` 与 `A2HSOFTINTCLR` 后唤醒专用 HFI 消息分发线程，按 `session_id` 投递至独立的 `struct iris_session`（每会话独立互斥锁、条件变量与 8 槽位码流输入环），移除 `250 us` 轮询并将全局锁收缩至微秒级命令入队。
- **补齐 HFI 硬件编码**：新增 `annibale_iris_enc.inc` 实现 `HFI_DOMAIN_ENC`（H.264 / HEVC / HEIC 帧内编码），输入端零拷贝映射相机/画布 `MiniIOSurface`，在 `videotoolbox_iris.c` 对接 `VTCompressionSession`，替代高耗时的软件 `VCPHEVC.videocodec`。

## 4. 第 3 批：相机流式管线与整机中断化去轮询（P0-5 / P1-1 / P1-7 / P1-8）

### 4.1 相机硬件 SE9 I2C、连续流式环形缓冲与 Adreno Compute ISP（P0-5）

目标文件：内核 `annibale_camera.c`、`annibale_camera_hw.inc`、`annibale_camera_native.inc`（新增公共 `annibale_geni_i2c.c`），用户态 `camera_device_stream.inc`、新增 `camera_isp_gpu.m`。

- **前摄切换至 `QUP_2 SE9` 硬件 GENI I2C**：前摄 `OV20B` 的物理引脚 `GPIO 4/5` 对应 `qupv3_se9_i2c`（`0x00884000`，`func 1` `qup2_se1_l0/l1`，中断 `INTID 615` = `32 + 0x247`）。编写通用 `annibale_geni_i2c.c` 驱动硬件 `400 kHz` I2C 事务，淘汰微秒级 `delay` 位模拟；后摄 `OV50E` 继续走 `CCI0 Master 1`（`0x0ac7b000`）。
- **连续流式 RDI 环形缓冲与帧完成中断**：
  - 将逐帧复位启停的 `CAMIOC_CAPTURE` 升级为 `CAMIOC_STREAM_START` / `CAMIOC_DQBUF` / `CAMIOC_QBUF` / `CAMIOC_STREAM_STOP` 流式接口。
  - 在 `apps_smmu` `SID 0x1c00` 预映射 4 个共享环形缓冲槽位（用户态只读 `mmap` 或 `MiniIOSurface`），`STREAM_START` 时仅启动传感器一次并配置 `ife-lite0`（`0x0ad6d000`）WM0 连续乒乓写入；挂载 `ife-lite0` 边沿中断 `INTID 638`（`32 + 0x25e`）与 `csid-lite0` 中断 `INTID 637`（`32 + 0x25d`），在 ISR 收到 `CAM980_RDI0_DONE` 时推进写指针并唤醒 `DQBUF`，彻底消除逐帧 `stream_on`/`stream_off`、`bzero` 与 `142～184 MB/s` `uiomove`。
- **Adreno 830 GPU Compute 着色器卸载 8 核软件 ISP**：
  - 新增 `camera_isp_gpu.m`，以 `newBufferWithBytesNoCopy` 零拷贝绑定 `DQBUF` 环形槽位中的 MIPI RAW10 帧，单次调度 Adreno 830 Compute 核函数完成 RAW10 解包、双线性 LSC、Malvar-He-Cutler 去马赛克、3×3 CCM、Gamma 及下采样并直接写入目标 NV12 `IOSurface` 的 Y/UV 纹理平面（单帧 GPU 耗时 `< 1.2 ms`，彻底释放 8 颗 Oryon CPU 核心；原 `camera_isp.c` 仅作 `cam_cpu_isp=1` 诊断回退）。Titan 主 IFE/IPE（`CAM-CPAS` + `RT-CDM`）待提取真机 `sensormodule`/`chromatix` 参数后作为远期迭代。

### 4.2 Wi-Fi 7（WCN7850）PCIe MSI 中断、可缓存 DMA 池、Skywalk 与宽频省电（P1-1）

目标文件：`hackios-xnu-kernel/xnu/files/bsd/dev/mhi/mhi_pcie.c`、`annibale_net.c` 及 `hackios-xnu-kernel/wifi/lx/` 下 `lx_pci.c`、`lx_base.c`、`lx_80211.c`。

- **挂载 PCIe MSI / SPI 中断消除 `1,800+ Hz` 空载轮询**：配置 PCIe RC0（`0x01c00000`）内置 DesignWare MSI 接收器（挂载 GICv3 边沿 SPI `INTID 181..184` = `32 + 0x95..0x98`，或接入 `gic_its@16040000` `SID 0x1400`）。将 MHI 事件环、`ath12k` CE 管道及 DP 收发环绑定到 MSI 向量，`wifi-rings`、`ipcr_thread`、`net_thread` 与 LinuxKPI `wait_event_timeout` 全部改为无轮询 `assert_wait` 事件唤醒；`wifi-ticks` 维护定时器降至关联态 `10 Hz`、网卡关闭态 `0 Hz`，并删除 `mhi_pcie.c` 中的 `30 s` 硬编码睡眠分支。
- **修复 `dma_free_coherent`、可缓存 SMMU 包池与单拷贝/Skywalk 路径**：基于 `apps_smmu` `SID 0x1400`（`0x98000000..0x100000000`）实现带真实回收池的 `dma_alloc_coherent`/`dma_free_coherent`，将收发 `sk_buff` DMA 池由非缓存 Write-Combining 改为 `PTE_NORMAL_WB` 硬件一致可缓存内存；绕过中间 `lx_queue` 环形拷贝，直接在固定映射的 `mbuf` 簇（后续切入 `kern_nexus` Skywalk 通道）上构建 `ath12k` HAL 描述符，并将全局 `lx_lock` 拆分为每 CE/SRNG 自旋锁。
- **解锁宽频、硬件卸载与省电**：移除 `lx_80211.c` 的 `20 MHz` 频宽锁死，放开 `80 MHz` / `160 MHz`（`HE160` / `EHT160`）协商，启用 `ATH12K_HW_TXRX_ETHERNET` 硬件 802.3 封装与校验和卸载，并在熄屏及空闲期下发 WMI `STA_POWERSAVE`（`100 ms` 超时进入 WMM-PS）。

### 4.3 音频 IPCC 中断、功放硬件 GENI I2C 与麦克风 4 槽流水线（P1-7）

目标文件：`annibale_adsp.c`、`annibale_audio_amp.c`、`annibale_mic.c`、`annibale_geni_i2c.c`。

- **IPCC LPASS 中断与 64 位 SMEM FIFO**：在 `annibale_adsp.c` 调用 `gic_v3_spi_attach(261, false, adsp_ipcc_intr, NULL)` 挂载 `ipcc_mproc@406000` 中断（DT `<0 0xe5 4>` -> `INTID 261`），使能 `(IPCC_CLIENT_LPASS = 3, SIGNAL_GLINK = 0)` 与 `SIGNAL_SMP2P = 2` 接收中断。ISR 清中断后直接唤醒 `adsp_worker_thread`，将播放期 `1,000 Hz` 与空闲期 `50 Hz` 轮询全部降为 `0 Hz` 定时唤醒；SMEM FIFO 改为 64 位对齐块拷贝加 `dsb sy`。
- **双功放切入 `hub_i2c0` 硬件 GENI I2C**：将 `annibale_audio_amp.c` 的 `GPIO 64/65` 切换至 `hub_i2c0`（`0x00980000`，中断 `INTID 496` = `32 + 0x1d0`），复用 `annibale_geni_i2c.c` 以硬件 `400 kHz` 访问已知地址 `0x34`/`0x36`（备选 `0x6c`/`0x6e`），删除 112 地址全扫与微秒忙等。
- **麦克风 4 槽异步采集环**：将 `annibale_mic.c` 升级为与 `annibale_audio_reach.c` 对称的 4 槽位共享 DMA `OP_READ` 异步流水线，由 IPCC GLINK 完成事件驱动。

### 4.4 触控 `GPIO_162` 中断、按键中断、QUPv3 总线与后台线程事件化（P1-8）

目标文件：新增 `annibale_tlmm_irq.c`，修改 `annibale_goodix.c`、`annibale_touch_bus_private.h`、`annibale_buttons.c`、`annibale_bt_uart.c`、`annibale_battery.c`、`annibale_modem.c`、`annibale_ipa.c` 及用户态 `input26_service.c`、`bluetool.c`、`annsh.c`。

- **TLMM GPIO 中断分发与 Goodix 触控零空载唤醒**：新增 `annibale_tlmm_irq.c` 挂载 `tlmm@f100000` 汇总中断 `INTID 240`（`32 + 0xd0`），配置 `GPIO_162` 下降沿触发；`annibale_goodix.c` 在无触控时无超时休眠（`0 Hz`），仅在中断触发后通过 `QUP_1 SE2 SPI`（`0x00a88000`，`INTID 387`）GENI DMA 读取 `192 B` 帧包。
- **PMIC 按键中断与 `input26-service` 阻塞读取**：`annibale_buttons.c` 接入 SPMI `intr`（`0x0c4c0000`）PON 边沿中断，`input26_service.c` 改为在字符设备上阻塞读取事件，移除 `62.5 Hz` 与 `4 Hz` 轮询。
- **蓝牙 SE14 高速 DMA、电量计 SE5 硬件 I2C 与后台服务去轮询**：
  - `annibale_bt_uart.c` 发送线程在队列为空时无超时等待条件变量，并在 `bluetool.c` 协商 `3.2 Mbps` 高速波特率加 `GPIO 24/25` 硬件流控与 SE14 GENI DMA。
  - `annibale_battery.c` 将 `GPIO 52/53` 切入 `QUP_1 SE5 I2C`（`0x00a94000`，`INTID 390`）硬件控制器，熄屏期降频至 `30 s` 或由 ADSP `BATTMGR` 通知驱动。
  - 在内核新增阻塞式 `kern.annibale.cmd_wait` 事件唤醒接口供 `annsh` 替代 `4 Hz` 轮询；`annibale_modem.c` 与 `annibale_ipa.c` 在无蜂窝激活时进入无超时挂起态。

## 5. 第 4 批：GPU 与密码学加速及遗留项收敛（P1-5 / P1-6 / P2-1～P2-4）

### 5.1 GPU 与 Metal 转译栈异步化、磁盘管线缓存、每进程页表与重复代码清理（P1-5）

目标文件：内核 `adreno8_smmu.c`、`adreno8_hwsched.c`，用户态驱动 `hackios-xnu-kernel/tools/userland-driver/annibalemetal_*.inc`、`air_metal_copy.inc`，清理 `hackios-xnu-userland/tools/userland-driver/redwoodmetal_*.inc`。

- **清理旧版重复驱动源码**：经核实 `userland/build.sh` 仅编译 `hackios-xnu-kernel/tools/userland-driver/annibalemetal.m`，彻底删除 `hackios-xnu-userland/tools/userland-driver/` 下未被引用的 `redwoodmetal_*.inc` 副本。
- **用户态异步 Blit 合批、缓冲纹理零拷贝与磁盘管线缓存（无内核依赖，可先行并入）**：
  - 修改 `annibalemetal_blit.inc`：移除每次拷贝后的立即提交与 `tu_queue_wait_fence` 同步等待，改为将 `tu_CmdCopyBufferToImage` / `tu_CmdCopyImage` 录制进所属 `MTLCommandBuffer` 的同一 `tu_cmd_buffer`，以 `VkMemoryBarrier2` 衔接后续渲染或计算通道。
  - 修改 `annibalemetal_texture.inc`：对 `offset` 与 `bytesPerRow` 满足 `64 B` 对齐的 Buffer-Backed Texture 直接绑定原 `MTLBuffer` 的 `tu_bo + offset`，省去 `-commit` 时的整块刷新拷贝。
  - 将 `tu_cmd_buffer` 录制前移至编码器执行期（每编码线程独立 `VkCommandPool`），解除 `-commit` 串行重放瓶颈；补齐 Compute PSO 缓存，并将 Turnip `VkPipelineCache` 持久化落盘至应用容器 `Library/Caches/com.apple.metal/`（缓存键绑定 `annibale-air-v2` 与驱动构建哈希）。
- **内核每进程 48 位 SMMU 页表与 `RB0..RB3` 硬件抢占**：在 `adreno8_smmu.c` 为每个 GPU 客户进程分配独立 48 位 Stage-1 `TTBR0` 与 `ASID`（通过 `CP_SMMU_TABLE_UPDATE` 切换，公共环留在 `TTBR1`），解映射时执行按地址区间的 `TLBI VAE1IS`；在 `adreno8_hwsched.c` 向 GMU 注册 `RB0..RB3` 4 级优先级队列，使 `backboardd`（`RB0`）可硬件抢占普通应用长耗时着色器。

### 5.2 `minicrypto` ARMv8/v9 硬件密码学指令接入与每 CPU PRNG（P1-6）

目标文件：`hackios-xnu-kernel/xnu/files/osfmk/minicrypto/` 新增 `mc_ce_arm64.c`，修改 `mc_aes.c`、`mc_digests.c`、`mc_provider.c`。

- 启动期读取 `ID_AA64ISAR0_EL1` 确认 Oryon 核心 `AES`/`PMULL`/`SHA2`/`SHA512`/`RNDR` 特性位。
- 在非中断上下文且输入长度 `>= 64 B` 时，以 XNU `kernel_fpu_begin()` / `kernel_fpu_end()` 保护 NEON 寄存器现场，调用 `aese`/`aesmc`、`pmull`、`sha256h`/`sha256su*` 与 `sha512h`/`sha512su*` 硬件指令处理 `CodeDirectory` 页签名校验与对称加解密（中断上下文保留原标量分支）。
- 将 `mc_prng` 改为 `PERCPU_DECL` 每核独立状态池（以关抢占 `disable_preemption()` 保护本核状态，结合硬件 `RNDR` 补熵），消除 8 核关中断自旋锁争用。

### 5.3 内核容量档位、固件异步预热、`/private/var/jb` 持久化与 `eagl.c` 对齐（P2-1～P2-4）

- **P2-1（内核容量档位升级）**：将内核 `bsd_init` 容量档位由 `bcm2837` 遗留的 `xsmall` 调整为适配 `16 GiB` RAM 的 `large` 档位（`desiredvnodes >= 65,536` 并同步放大名称缓存桶数），减少频繁 vnode 回收。
- **P2-2（协处理器后台异步预热）**：保持 GPU 固件在 `backboardd` 启动前就绪，将 ADSP 启动移入内核后台异步线程与 `init`/`launchd` 启动重叠并行；Iris VPU 保持首次打开 `VideoToolbox` 时按需快速装载。
- **P2-3（`/private/var/jb` 持久化与 Poster 挂起暂停）**：第 1 批 `var_apfs=1` 接管 `/private/var` 后，将 `/private/var/jb` 直接落入 APFS Data 卷（仅在载荷版本戳变更时增量同步文件，免除每次开机 `ramfs` 全量拷贝）；修改 `inject_posterboard.c`，在检测到 `MercuryPosterExtension` 进入场景后台或挂起时直接设 `CADisplayLink.paused = YES` 并跳过 `nextDrawable`，彻底移除 `-commit` 内的 `usleep(200000)`。
- **P2-4（`eagl.c` 零额外 Blit）**：在 `eagl.c` 创建或导入 `CAEAGLLayer` `MiniIOSurface` 时统一按 `64 B` 对齐行步幅，默认设 `blit_targets = 0` 直接向目标表面 FBO 渲染，并删除未对齐时的 `checksum()` 加 `glReadPixels` CPU 读回路径。

## 6. 子 Agent 并行实施切分与验收门禁

下表按互不重叠的文件归属边界切分 9 个工作包，支持后续并行派发子 Agent 实施且无合并冲突。

| 工作包 | 覆盖问题 | 独占文件归属边界 | 关键验收门禁（主机单测 + K90 真机） |
| :--- | :--- | :--- | :--- |
| `WP-1A` | P0-3、P1-2 | `bsd/dev/annibale/annibale_ufshc*`、`annibale_ufs*` | 连续读吞吐提升且无 `memcpy`；`INTID 297` 计数增长、`hc_poller` CPU 占用为 `0%`；`DKIOCSYNCHRONIZECACHE` 与越界 `UNMAP` 拒绝测试全部通过；回 `xnuloader` `idle` 正常 |
| `WP-1B` | P0-4、P1-3 | `bsd/miscfs/apfs/*`、`tools/apfs/*`、`boot/init_mount.inc` | 主机 POSIX 目录/`rename`/`symlink`/socket/`xattr`/并发读写与断电恢复测试全部通过；`1 MB` 追加写块 I/O 次数下降 `> 10×`；开启 `var_apfs=1` 真机完整进桌面并重启持久化校验通过 |
| `WP-2A` | P0-1、P1-4 | `bsd/dev/annibale/annibale_apps_smmu*`、`iokit/Kernel/Mini*Framebuffer*` | `SID 0x0800` 直扫零 SMMU 故障；`120 Hz` 桌面滑动跳过 `hashRows`/`drawRows`；`INTID 115` TE VSync 稳定 `120 Hz`；`ui-health.py` 与退出回 `xnuloader` 截图均通过 |
| `WP-2B` | P0-2、P0-6 | `iokit/Kernel/MiniIOSurface*`、`bsd/dev/annibale/annibale_iris*`、`inject/videotoolbox_iris.c` | UBWC 表面渲染与 DPU 直扫画面无撕裂花屏；`1080p60`/`4K60` 硬解 `copyout` 次数降为 `0`、`INTID 206` 正常唤醒；硬件 HEIC/HEVC 编码产出合规码流 |
| `WP-3A` | P0-5 | `bsd/dev/annibale/annibale_camera*`、`annibale_geni_i2c*`、`services/camera_*` | 前摄 `SE9` 硬件 I2C 通信正常；前后摄 `30 fps` 连续流式 `DQBUF` 零 `uiomove`；GPU Compute ISP 单帧 `< 2 ms`，CPU 占用下降 `> 80%` |
| `WP-3B` | P1-1 | `bsd/dev/mhi/*`、`bsd/dev/annibale/annibale_net.c`、`wifi/lx/*` | PCIe MSI 正常触发，无流量待机 Wi-Fi 线程唤醒 `< 15 Hz`；`80/160 MHz` 关联成功且实测吞吐突破百兆瓶颈，无 DMA 内存泄漏 |
| `WP-3C` | P1-7、P1-8 | `annibale_adsp*`、`annibale_audio_amp.c`、`annibale_mic.c`、`annibale_tlmm_irq.c`、`annibale_goodix.c`、`annibale_buttons.c`、`annibale_bt_uart.c`、`annibale_battery.c`、`apps/annsh.c` | `INTID 261`（IPCC）与 `INTID 240`（`GPIO_162` 触控）正常唤醒；整机黑屏静置总定时器唤醒降至 `< 50 Hz`；温和音量 `sound_test system 1106`、录音、触控、按键、蓝牙与电量读数全部正常 |
| `WP-4A` | P1-5、P2-3、P2-4 | `tools/userland-driver/*`（含删 `redwoodmetal_*`）、`adreno8_smmu.c`、`adreno8_hwsched.c`、`inject/inject_posterboard.c`、`gfx/eagl.c` | 删除重复 `redwoodmetal` 后构建通过；贴图连续上传零 `tu_queue_wait_fence` 阻塞；应用二次冷启动命中磁盘管线缓存；`backboardd` `RB0` 抢占生效 |
| `WP-4B` | P1-6、P2-1、P2-2 | `osfmk/minicrypto/*`、`bsd/kern/bsd_init.c`（容量档位） | `minicrypto` 硬件 CE 与标量参考向量逐字节一致且吞吐提升 `> 10×`；`16 GiB` 机型 `kern.maxvnodes` 升至 `large` 档位且开机时长进一步缩短 |
