# 全工作区早期过渡方案与性能瓶颈源码审计（2026-11-14）

适用范围：`hackios-xnu-kernel`（`k90-port`）、`hackios-xnu-userland`（`k90-port`）及顶层 `tools/` 与 `docs/backlog/`。审计结合当前默认启动参数核实真机热路径，参数来源见 [cycle.py](../../tools/k90auto/cycle.py)、[make-payload.py](../../tools/k90auto/make-payload.py) 及 [mkstandalone.py](../../hackios-xnu-kernel/xnuloader/mkstandalone.py)。

当前默认生效参数为 `rootdev=md0 root_apfs=ufs_darwin ufs=2 ufs_native=1 ufs_write=1 metal=1 cpufreq=1 fb_threads=2 gpu_coherent=1 fb_flip=2 fb_beat=0 fb_hz=120 fb_ca_hz=120 dl_max=1 fbwidth=1206 fbheight=2622 fbpitch=460`。

全仓除计划下线的 `darwin_var` 内存落盘层（[ramfs_disk.inc](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_disk.inc) `ANNFS001`）外，共查明 **6 项 P0 核心热路径瓶颈**、**8 项 P1 轮询与串行瓶颈** 及 **4 项 P2 启动期或遗留路径开销**。各项问题的架构改造方案与寄存器设计，连同文件拆分边界和分批实施计划，统一见 [性能与原生硬件对齐改造方案](../plan/2026-11-14-performance-and-native-alignment-plan.md)。

## 1. 已接入原生硬件能力的基线与第 0 批已落地减负项

### 1.1 原生硬件基线边界

以下路径经源码核实已接入硬件 DMA、硬件缓存一致性或 GICv3 中断，单列于此界定本次审计边界。

- **UFS 31 槽位环形队列扩展（`ufs_native=1`）**：[annibale_ufshc.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_ufshc.c) 将 UEFI 遗留单槽位 UTRD 扩展为 31 个传统 UTRD 槽位，每槽预分配 `256 KiB` 物理连续缓冲。
- **APFS 只读数据面接入 UBC 与多线程解压**：[apfs_vnops.c](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_vnops.c) 与 [apfs_lib.c](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_lib.c) 接入 XNU UBC 页缓存与 VFS `cache_lookup` 名称缓存，块读取及 4 线程 `libdeflate` 解压期间释放挂载锁 `am_lock`；系统卷与 Cryptex 直接在 `/dev/ufs_darwin` 物理偏移上挂载（见 [apfs_vfsops.c](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_vfsops.c)）。
- **Adreno 830 硬件缓存一致性与 GMU 中断**：默认 `gpu_coherent=1`（见 [adreno8.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/adreno8/adreno8.c) 与 [AnnibaleGPUSubmit.inc](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/AnnibaleGPUSubmit.inc)）省去每次 GPU 提交的 CPU PoC 缓存刷写；[adreno8_hfi.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/adreno8/adreno8_hfi.c) 挂载 GICv3 SPI `INTID 336`（`32 + 0x130`）处理 GMU HFI 栅栏中断。
- **GPU 表面零拷贝映射与进程内渲染管线缓存**：[AnnibaleGPUMemory.inc](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/AnnibaleGPUMemory.inc) 对行字节 `64 B` 对齐的 `MiniIOSurface` 直接建立 `kgsl_smmu` CB0 页表映射；[annibalemetal_pipecache.inc](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_pipecache.inc) 提供进程内 96 项渲染管线缓存。
- **Iris VPU 硬件码流解码与 AudioReach 异步播放**：[annibale_iris_hw.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_iris_hw.c) 通过 PAS 9 启动 Iris v3.5 固件并用片内 UBWC DPB 硬解 H.264/HEVC；[annibale_audio_reach.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_audio_reach.c) 在 `64 KiB` 共享 DMA 窗口上以 4 槽位异步 `OP_WRITE` 流水线驱动播放。
- **蓝牙 RX 中断、CPUFreq 调频与 RPMh 投票**：[annibale_bt_ios.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_bt_ios.c) 注册 Skywalk 通道并挂载 GICv3 SPI `INTID 493`（`32 + 0x1cd`）接收中断；[annibale_cpufreq.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_cpufreq.c) 通过 SCMI `0x13` 协议驱动双丛集调频；[annibale_rpmh.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_rpmh.c) 通过 Apps RSC DRV2 Active TCS 寄存器直接发起电源轨硬件投票。
- **USB 控制器运行边界**：DWC3 设备控制器仅在引导阶段 [loader_06_usb_entry.inc](../../hackios-xnu-kernel/xnuloader/loader_06_usb_entry.inc) 工作并在进入 XNU 前停机；XNU 内核态尚未合入 DWC3 驱动（见 [platform.md](../backlog/platform.md)）。

### 1.2 第 0 批已落地的直接减负项（2026-11-14）

第 0 批已针对启动期 I/O 放大、固件逐字节搬运及空闲轮询在代码树完成直接减负改动。

- **开机自检套件门控**：[init.c](../../hackios-xnu-userland/userland/src/boot/init.c) 将 `test_files`、300 文件 `test_writable`、`64 MiB` `test_memory`、`test_processes`、`test_devices` 与 `200 ms` `test_time` 收入诊断参数 `init_selftest=1`（默认关闭），仅保留单次非 PID 1 子进程 `test_dynamic()` 为 iOS 26 `launchd` 预热全局 `vm_shared_region`。
- **固件 FAT16 读取合并与 64 位对齐搬运**：[annibale_ufs_rw.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_ufs_rw.inc) 增加 `4 KiB` FAT16 扇区缓存并将连续簇合并为最高 `256 KiB` UFS 读取；[annibale_adsp_fw.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_adsp_fw.inc) 与 [annibale_iris_hw.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_iris_hw.c) 改为 64 位对齐 `volatile uint64_t` 块写入与清零。
- **空闲轮询去超时与录音限流修复**：[annibale_haptic.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_haptic.c)（原 `250 Hz`）与 [annibale_torch.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_torch.c)（原 `10 Hz`）在空闲态改为无超时 `assert_wait` 事件唤醒；[annibale_mic.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_mic.c) 移除录音采集中每帧末尾冗余的 `20 ms` 固定睡眠，空闲轮询降频并在 `open` 时立即唤醒。
- **APFS 可写基础修正**：[apfs_vnops.c](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_vnops.c) 对可写挂载放行 `FWRITE | O_TRUNC | O_CREAT`，[apfs_vnops_write.inc](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_vnops_write.inc) 在释放 `am_lock` 后执行 `ubc_setsize` 与 `ubc_msync(..., UBC_INVALIDATE)`，[init_mount.inc](../../hackios-xnu-userland/userland/src/boot/init_mount.inc) 用独立 `var_apfs=1` 保护现网 `darwin_var`。
- **桌面注入减负**：[inject_sb26.c](../../hackios-xnu-userland/userland/src/inject/inject_sb26.c) 增加本地化目录哈希缓存，[inject_sb26_layers.c](../../hackios-xnu-userland/userland/src/inject/inject_sb26_layers.c) 默认关闭 `40 s`/`160 s` 图层树自动转储。

## 2. P0 核心热路径瓶颈（6 项）

### 2.1 P0-1 显示输出（`IOMobileFramebuffer`）：全帧行哈希与 CPU 双线性缩放拷贝

- **源码定位**：[MiniIOMobileFramebuffer.cpp](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp)、[MiniFramebufferRows.inc](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferRows.inc)、[MiniFramebufferFlip.inc](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferFlip.inc) 及 [MiniFramebufferScale.h](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferScale.h)。
- **当前过渡方案**：内核未配置 `apps_smmu`（`0x15000000`）显示流 `SID 0x0800` 页表，未驱动 MDSS DPU 12.0（`0x0ae00000`）直扫 `MiniIOSurface` 物理页，沿用 UEFI 遗留的双路 `578 × 2510` SSPP（`VIG0` + `VIG1`）管道配置，仅在 `0xfc800000` Write-Combining 预留区内切换双缓冲地址（`fb_flip=2`）。
- **逐帧 CPU 开销**：默认渲染表面为 `1206 × 2622`（BGRA8），面板预留缓冲为 `1156 × 2510`。每次 `swap_submit` 先唤醒 `fb_threads=2` 工作线程执行 `hashRows` 逐行哈希比对，再唤醒同一组线程执行 `drawRows` 做 CPU 定点双线性插值缩放写入预留区；多图层 `SWAP_LAYERS` 在 CPU 内顺序混合，多平面 YCbCr 表面（`planeCount != 0`）直接被拒绝。
- **量化资源代价**：源表面单帧 `12,648,528 B`（`12.06 MiB`），目标预留区单帧 `11,606,240 B`（`11.07 MiB`）。`120 Hz` 全屏刷新下每帧 `hashRows` 读取最高 `12.65 MB`（`1.52 GB/s`），`drawRows` 再读 `12.65 MB` 并写 `11.61 MB`，单图层合计产生 `2.91～4.43 GB/s` CPU 访存流量与每帧 2 次双线程同步唤醒；相机与视频 NV12 帧也被迫先转为全屏 BGRA8 再经 CPU 缩放拷贝。

### 2.2 P0-2 图形与媒体共享表面（`MiniIOSurface`）：全链路未压缩线性布局

- **源码定位**：[MiniIOSurface.cpp](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniIOSurface.cpp)、[air_metal.c](../../hackios-xnu-userland/tools/mesa/air/air_metal.c)、[annibalemetal_texture.inc](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_texture.inc) 及 [annibale_iris_hfi.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_iris_hfi.c)。
- **当前过渡方案**：`MiniIOSurface::init` 仅按 `bytesPerRow * height` 分配线性页数组，无高通 UBWC 宏块对齐与独立元数据平面分配能力；`air_metal.c` 默认 `ubwc = 0`，`annibalemetal_texture.inc` 对共享 `IOSurface` 固定使用 `FD6_LINEAR`，Iris VPU 解码输出固定配置为线性 `HFI_COLOR_FMT_NV12`。
- **量化资源代价**：Adreno 830 GMEM 写出与采样、桌面合成、视频解码输出与显示扫描全部走未压缩线性突发访问，相比 SM8750 硬件 UBWC v4/v5 多消耗约 `35%～50%` LPDDR5X 带宽与访存功耗，在高帧率合成与 `4K60` 播放下显著加剧内存控制器争用。

### 2.3 P0-3 UFS 块存储数据面：`256 KiB` 中转缓冲拷贝与同步阻塞 `ufs_strategy`

- **源码定位**：[annibale_ufshc.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_ufshc.c)、[annibale_ufshc_rw.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_ufshc_rw.inc) 及 [annibale_ufs_rw.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_ufs_rw.inc)。
- **当前过渡方案**：每个 UTRD 槽位绑定预分配的 `256 KiB` 物理连续中转缓冲 `s->data_pa`，`build_prdt` 只填单段地址。每次 `ufshc_read` 敲门铃前刷写一次 `FlushPoC_DcacheRegion`，DMA 完成后再刷写一次并 `memcpy` 至目标缓冲；`ufshc_write` 同样整块 `memcpy` 加刷缓存。块设备入口 `ufs_strategy` 在调用线程内同步阻塞等待硬件完成后才调用 `buf_biodone(bp)`。
- **量化资源代价**：`500 MB/s` 顺序读负载下，CPU 每秒额外执行 `1.0 GB/s` 的 `dc civac` 缓存行刷写与 `500 MB/s` `memcpy`；同步 `ufs_strategy` 使单线程顺序流无法重叠下发多个 `buf_t`，31 个硬件槽位在单线程路径下退化为队列深度 `1`。

### 2.4 P0-4 可写 APFS（`apfs_rw=1`）：绕过 UBC 聚合、目录契约缺口与每 `4 KiB` 检查点事务

- **源码定位**：[apfs_vnops.c](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_vnops.c)、[apfs_vnops_write.inc](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_vnops_write.inc)、[apfs_write.c](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_write.c)、[apfs_write_ops.inc](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_write_ops.inc) 及 [apfs_txn.inc](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_txn.inc)。
- **功能切换缺口**：`apfs_vnodeop_entries` 尚未实现 `vnop_mkdir`、`vnop_rmdir`、`vnop_symlink`、`vnop_rename`、`vnop_link`、`vnop_mknod`（`/private/var/run` 所需 `AF_UNIX` 套接字节点）、`vnop_setxattr`、`vnop_removexattr` 与 `vnop_pageout`（可写共享 `mmap`），现阶段尚不能直接接管 `/private/var`（`var_apfs=1`）。
- **当前写路径开销**：`apfs_vnop_write` 全程持有 `am_lock`，绕过 XNU `cluster_write` 与 UBC 脏页聚合，按 `4096 B` 循环直写，每次写完 `4 KiB` 立即同步读回做 `memcmp`。追加写每 `4 KiB` 完整执行一轮 `txn_begin -> B-tree 重打包 -> txn_commit` 检查点事务；`txn_modify_btree_root` 每次修改节点都分配 `512 * sizeof(struct rec_slot) = 403,456 B` 解包整页记录。
- **量化资源代价**：追加写每 `4 KiB` 在 3 棵树更新中分配释放 `1.18 MB` 内核堆内存，同步写出并读回数据块、位图、OMAP、B-tree、卷超级块与容器超级块共约 11～13 个块，写放大约 `12×`，同步块 I/O 达 `24～28 次`。顺序追加 `1 MB` 文件产生约 `295 MB` 堆分配释放与逾 `6,000 次` 同步块 I/O，期间整卷读写被 `am_lock` 串行阻塞。

### 2.5 P0-5 相机采集与 ISP：逐帧启停传感器、软件 I2C 与 8 核全软件 Bayer ISP

- **源码定位**：[annibale_camera_native.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_camera_native.inc)、[annibale_camera_hw.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_camera_hw.inc)、[camera_isp.c](../../hackios-xnu-userland/userland/src/services/camera_isp.c)、[camera_device_stream.inc](../../hackios-xnu-userland/userland/src/services/camera_device_stream.inc) 及 [inject_media.c](../../hackios-xnu-userland/userland/src/inject/inject_media.c)。
- **当前过渡方案**：内核仅启用 `csid-lite0`（`0x0ad6d000`）与 `ife-lite0` 原始 RDI 通道，未驱动 Titan 主 IFE/IPE 硬件 ISP。每采一帧执行同步 `ioctl(CAMIOC_CAPTURE)`：复位配置 CSID/VFE、整帧 `bzero` 加双次 `FlushPoC_DcacheRegion`，前摄 `OV20B` 在 `GPIO 4/5`（物理归属 `QUP_2 SE9 I2C` `0x00884000`）上用 `delay(3~4 us)` 软件模拟 I2C 发送 `stream_on`/`stream_off`，按 `1000 us` 轮询 `CAM980_BUF_STATUS` 后经 `uiomove` 拷出 RAW10。用户态 `camera_isp.c` 以 `QOS_CLASS_USER_INTERACTIVE` 跑满 8 核软件执行解包、LSC、CCM、Gamma、去马赛克与 NV12 转换；拍照 HEIC 走纯软件 `VCPHEVC.videocodec`。
- **量化资源代价**：前摄 `OV20B` 单帧 RAW10 `4.52 MiB`，`30 fps` 下产生 `142.07 MB/s` `bzero`、`284.14 MB/s` `dc civac` 与 `142.07 MB/s` `uiomove`；后摄 `OVX8000` 单帧 `5.86 MiB`，`30 fps` 下产生 `184.32 MB/s` `bzero`、`368.64 MB/s` `dc civac` 与 `184.32 MB/s` `uiomove`。逐帧启停传感器把曝光稳定延迟串入每帧周期，8 核软件 ISP 持续占满大核算力。

### 2.6 P0-6 Iris VPU 视频解码桥接：全局单锁、`250 us` 轮询与逐行 `copyout`

- **源码定位**：[videotoolbox_iris.c](../../hackios-xnu-userland/userland/src/inject/videotoolbox_iris.c)、[annibale_iris.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_iris.c) 及 [annibale_iris_hfi.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_iris_hfi.c)。
- **当前过渡方案**：用户态每帧 `malloc` 转换 Annex-B 码流并发起同步 `ioctl(IRIS_IOC_DECODE_FRAME)`。内核以全局互斥锁 `iris_lock` 串行化所有会话，输入池深度为 `1`，每次提交执行 `copyin` 加刷缓存后按 `250 us` 轮询 HFI 队列（未挂载 Iris GICv3 SPI `INTID 206` 中断）。解码输出未直写用户态 `IOSurface`，内核刷写整帧线性 NV12 缓存后按行循环调用 `h + h/2` 次 `copyout` 拷入 `CVPixelBuffer`；HFI 硬件编码尚未接入。
- **量化资源代价**：`1080p60` 下每秒产生 `188.0 MB/s` `dc civac`、`186.6 MB/s` 拷贝与 `97,200 次/秒` `copyout`；`4K60` 下升至 `752.0 MB/s` `dc civac`、`746.5 MB/s` 拷贝与 `194,400 次/秒` `copyout`，叠加 P0-1 显示侧软件缩放拷贝后高码率视频易掉帧。

## 3. P1 高频轮询、软件模拟总线与锁争用瓶颈（8 项）

### 3.1 P1-1 Wi-Fi 与 PCIe/MHI 网络栈：空载 `1,800+ Hz` 轮询、双次拷贝与 `20 MHz` 限速

- **源码定位**：[lx_pci.c](../../hackios-xnu-kernel/wifi/lx/ath12k/lx_pci.c)、[lx_base.c](../../hackios-xnu-kernel/wifi/lx/src/lx_base.c)、[lx_80211.c](../../hackios-xnu-kernel/wifi/lx/src/lx_80211.c)、[mhi_pcie.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/mhi/mhi_pcie.c)、[mhi_pcie_fw.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/mhi/mhi_pcie_fw.c) 及 [annibale_net.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_net.c)。
- **当前过渡方案**：PCIe RC0（`0x01c00000`）MSI 指向空页未绑中断（GIC ITS `0x16040000` `SID 0x1400` 或边缘 SPI `INTID 181..184` 未使用），依赖 5 组常驻轮询线程推进（`wifi-rings` `1,000 Hz`、`wifi-ticks` `500 Hz`、`ipcr_thread` `200 Hz`、`net_thread` `100～500 Hz`、LinuxKPI 等待队列 `200 Hz`），共同争用全局锁 `lx_lock`。网卡注册为 `IFNET_INIT_LEGACY`，收发各经 `mbuf <-> lx_queue <-> Write-Combining lowdma sk_buff` 两次整包拷贝，`dma_free_coherent` 为空实现；`lx_80211.c` 锁死 `20 MHz` 频宽并关闭省电，`mhi_pcie.c` 含 `30 s` 固定睡眠分支。
- **量化资源代价**：纯待机无流量时每秒仍触发 `1,800+ 次` 线程唤醒与数千次 PCIe BAR0 MMIO 读取，阻止 CPU 与 WCN7850 进入低功耗态；`20 MHz` 频宽加双次非缓存拷贝将 Wi-Fi 7 吞吐限制在百兆级。

### 3.2 P1-2 UFS 控制面：`hc_poller` 零睡眠忙等、单门铃队列与缓存刷盘拦截

- **源码定位**：[annibale_ufshc.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_ufshc.c) 与 [annibale_ufshc_rw.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_ufshc_rw.inc)。
- **当前过渡方案**：未挂载 `ufshc@1d84000` GICv3 SPI `INTID 297`（`32 + 0x109`）中断，`UFSHC_IE` 未开启；`hc_complete` 先忙等 `100 us` 读 `UFSHC_UTRLDBR`，超时后唤醒 `hc_poller` 在 `ufshc_inflight != 0` 期间执行零睡眠 MMIO 死循环；硬件停留在单 32 位门铃模式（未启用 UFSHCI v4.0 MCQ `0x01da5000`）；`hc_refusal` 拦截 `SYNCHRONIZE CACHE (0x35)`、`UNMAP (0x42)` 与 FUA。
- **量化资源代价**：大块读写或闪存 GC 超过 `100 us` 时，`hc_poller` 100% 占满 1 颗 CPU 核心轮询寄存器；拦截缓存同步与 `UNMAP` 使可写 APFS 无法下发硬件持久刷盘屏障与块回收。

### 3.3 P1-3 APFS 只读与元数据层：全卷单锁 `am_lock`、无预读与平方级 `readdir`

- **源码定位**：[apfs.h](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs.h)、[apfs_vnops.c](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_vnops.c) 及 [apfs_vfsops.c](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_vfsops.c)。
- **当前过渡方案**：每个挂载点用单把互斥锁 `am_lock` 串行化 `lookup`、`getattr`、`readdir` 与缺页 extent 查找；每次 `read`/`pagein` 获取全局自旋锁 `apfs_MetricsLock` 执行 6 次 `strstr` 子串扫描；未压缩文件按 `128 KiB` 同步切块读取而未接入 `cluster_read_ext` 预读；`apfs_vnop_readdir` 每次调用从目录首项重头遍历 B-tree 跳过前 `idx` 项；底层 `mcache` 仅 `256 项`（`1 MiB`）且采用线性探测。
- **量化资源代价**：多进程冷启动并发缺页在 `am_lock` 与 `apfs_MetricsLock` 上排队；数千项大目录分段 `getdirentries` 退化为 $O(N^2)$ 遍历；`1 MiB` 元数据缓存频繁穿透触发单块读。

### 3.4 P1-4 显示 VSync 与交换节拍：软件定时器模拟 VSync 与单槽位覆盖队列

- **源码定位**：[MiniFramebufferUserClient.inc](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferUserClient.inc)、[MiniFramebufferFlip.inc](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferFlip.inc) 及 [MiniIOMobileFramebuffer.cpp](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp)。
- **当前过渡方案**：VSync 由 `IOTimerEventSource` 按固定 `8,333,333 ns` 软件定时触发，未绑定 MDSS GICv3 SPI `INTID 115`（`32 + 0x53`）与面板 `GPIO_86` Tear-Effect 信号；`SwapWait`（`sMethod[5]`）为空实现直接返回成功，交换队列深度为 `1` 直接覆盖旧帧；`flipSplashPipe` 最长忙等 `20,000 us` 轮询 `FLIP_CTL_FLUSH`。
- **量化资源代价**：软件定时器与面板真实扫描相位脱节造成周期性微卡顿，合成器失去背压节流，持锁忙等阻塞内核线程。

### 3.5 P1-5 GPU 与 Metal 转译栈：共享 32 位 CB0、单队列无抢占与同步 Blit

- **内核源码定位**：[AnnibaleGPU.cpp](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/AnnibaleGPU.cpp)、[adreno8_smmu.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/adreno8/adreno8_smmu.c) 及 [adreno8_hwsched.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/adreno8/adreno8_hwsched.c)。
- **用户态源码定位**：[annibalemetal_commandbuffer_submit.inc](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_commandbuffer_submit.inc)、[annibalemetal_blit.inc](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_blit.inc) 及 [air_metal_copy.inc](../../hackios-xnu-userland/tools/mesa/air/air_metal_copy.inc)；另在 `hackios-xnu-userland/tools/userland-driver/redwoodmetal_*.inc` 残留旧版重复源码。
- **当前过渡方案**：内核侧全机进程共用 `kgsl_smmu` CB0 的 `3.75 GiB` 32 位地址池与单一 `RB0` 队列（无硬件抢占），每次解映射刷写全 ASID TLB；用户态编码期仅向 `_work` 数组追加软件记录，推迟到 `-commit` 在 `rw_commit_lock` 下单线程重放并整块刷新缓冲纹理 BO；每次 `MTLBlitCommandEncoder` 拷贝立即提交并同步 `tu_queue_wait_fence` 等待 GPU 完成；缺少 Compute 管线缓存与磁盘二进制管线缓存。
- **量化资源代价**：后台长耗时着色器无法被 `backboardd` 抢占，连续贴图上传每次都打断 CPU-GPU 流水线同步等待，应用每次冷启动重复编译 AIR/NIR/ir3。

### 3.6 P1-6 内核密码学组件（`minicrypto`）：纯软件查表 AES、标量 SHA 与单锁 PRNG

- **源码定位**：[mc_aes.c](../../hackios-xnu-kernel/xnu/files/osfmk/minicrypto/mc_aes.c)、[mc_digests.c](../../hackios-xnu-kernel/xnu/files/osfmk/minicrypto/mc_digests.c) 及 [mc_provider.c](../../hackios-xnu-kernel/xnu/files/osfmk/minicrypto/mc_provider.c)。
- **当前过渡方案**：使用字节查表 `aes_sbox[256]` 与标量 C 实现 AES 及 SHA-1/256/384/512，未调用 ARMv8/v9 密码学扩展指令；`mc_prng` 在 8 核间争用单把关中断自旋锁。
- **量化资源代价**：可执行页缺页 `CodeDirectory` 哈希校验与内核对称加解密吞吐比 Oryon 硬件指令慢约 `10～30 倍`。

### 3.7 P1-7 音频子系统：ADSP GLINK 轮询、GPIO 模拟功放 I2C 与单槽麦克风

- **源码定位**：[annibale_adsp.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_adsp.c)、[annibale_audio_amp.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_audio_amp.c) 及 [annibale_mic.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_mic.c)。
- **当前过渡方案**：未挂载 `ipcc_mproc@406000` GICv3 SPI `INTID 261`（`32 + 0xe5`）中断，`adsp_worker_thread` 播放期按 `1,000 Hz`、空闲期按 `50 Hz` 轮询 SMEM FIFO 且逐字节 `volatile` 读写；`annibale_audio_amp.c` 在 `GPIO 64/65`（物理归属 `hub_i2c0` `0x00980000`，`INTID 496`）上用软件模拟 I2C 配置双路 TFA9866（`0x34`/`0x36`）并在探测期扫描总线；`annibale_mic.c` 已在第 0 批移除冗余 `20 ms` 睡眠，但录音数据面仍为单槽同步等待。
- **量化资源代价**：ADSP GLINK 常驻产生 `50～1,000 Hz` 唤醒；软件模拟 I2C 启停功放期间占用数十毫秒微秒级忙等延迟；单槽录音在调度抖动下缺少多缓冲容错裕量。

### 3.8 P1-8 外设与后台常驻轮询群（触控、按键、蓝牙 TX、电量计与后台服务）

- **源码定位与当前状态**：
  - **Goodix 触控轮询**：[annibale_goodix.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_goodix.c) 与 [annibale_touch_bus_private.h](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_touch_bus_private.h) 未挂载 `GPIO_162` 下降沿中断（经 `tlmm@f100000` 汇总中断 `INTID 240`）与 `QUP_1 SE2 SPI`（`0x00a88000`，`INTID 387`）GSI/DMA，空闲期仍以 `125 Hz` 轮询引脚并以 `62.5 Hz` 空载读取 `192 B` SPI 帧包。
  - **PMIC 按键与输入服务轮询**：[annibale_buttons.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_buttons.c) 按 `62.5 Hz` 轮询 SPMI PON 状态，[input26_service.c](../../hackios-xnu-userland/userland/src/services/input26_service.c) 另有 `4 Hz` 状态轮询。
  - **蓝牙 SE14 发送轮询与波特率限制**：[annibale_bt_uart.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_bt_uart.c) 发送线程按 `50 Hz` 空载轮询，[bluetool.c](../../hackios-xnu-userland/userland/src/services/bluetool.c) 维持 `115200` 低波特率 FIFO 传输。
  - **基带桩与收尾轮询**：[annibale_modem.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_modem.c)（`5～40 Hz`）、[annibale_ipa.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_ipa.c) 丢包拷贝与 [loader_return.c](../../hackios-xnu-kernel/xnu/files/osfmk/arm64/loader_return.c) `loader_stop_poll`（`10 Hz`）。
  - **电量计模拟 I2C 与服务轮询**：[annibale_battery.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_battery.c) 在 `GPIO 52/53` 上模拟 `QUP_1 SE5 I2C`（`0x00a94000`，`INTID 390`）读取 `BQ27Z561`（`0x55`），另有 [annibale_sensors.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_sensors.c)（`4 Hz`）与 [annsh.c](../../hackios-xnu-userland/userland/src/apps/annsh.c)（`4 Hz`）。（马达与手电筒已在第 0 批去轮询。）
- **量化资源代价**：叠加 Wi-Fi 与音频 GLINK 轮询后，整机黑屏静置每秒仍触发逾 `2,000 次` 定时器唤醒与外设 MMIO 访问，阻碍 Oryon CPU 丛集维持深睡眠驻留。

## 4. P2 启动期开销与遗留路径（4 项）

### 4.1 P2-1 PID 1 开机自检门控与 XNU `xsmall` 内核容量档位

- **源码定位**：[init.c](../../hackios-xnu-userland/userland/src/boot/init.c) 与内核 `scale` 配置。
- **当前状态**：`init.c` 的 300 文件读写与 `64 MiB` 内存扫描已在第 0 批默认关闭；但内核仍沿用早期移植自 `bcm2837` 的 `xsmall` 容量档位，vnode 表、名称缓存及内核区配额偏小，与 K90 的 `16 GiB` LPDDR5X 物理内存不匹配。

### 4.2 P2-2 协处理器固件装载路径与按需并行化

- **源码定位**：[annibale_adsp_fw.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_adsp_fw.inc)、[annibale_iris_hw.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_iris_hw.c) 及 [annibale_ufs_rw.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_ufs_rw.inc)。
- **当前状态**：第 0 批已将 `modem` FAT16 固件读取提速为扇区缓存加 `256 KiB` 连续读，并将约 `70 MiB` 固件搬运改为 64 位对齐块写；后续待 UFS 散聚 DMA 就绪后可直读至预留物理段（认证前），并将非首屏关键协处理器改为后台异步预热。

### 4.3 P2-3 `/private/var/jb` 内存盘全量拷贝、本地化扫描与扩展挂起睡眠

- **源码定位**：[init_mount.inc](../../hackios-xnu-userland/userland/src/boot/init_mount.inc)、[inject_sb26.c](../../hackios-xnu-userland/userland/src/inject/inject_sb26.c)、[inject_posterboard.c](../../hackios-xnu-userland/userland/src/inject/inject_posterboard.c) 及 [inject_sb26_layers.c](../../hackios-xnu-userland/userland/src/inject/inject_sb26_layers.c)。
- **当前状态**：第 0 批已完成 `inject_sb26.c` 本地化探测缓存与 `inject_sb26_layers.c` 自动转储门控；剩余 `/private/var/jb` 每次开机递归拷入 `ramfs`，以及 `inject_posterboard.c` 对挂起态 `MercuryPosterExtension` 在 `-commit` 内调用 `usleep(200000)` 阻塞渲染提交线程。

### 4.4 P2-4 遗留 OpenGL ES 桥接层（`eagl.c`）冗余整帧 FBO Blit

- **源码定位**：[eagl.c](../../hackios-xnu-userland/userland/src/gfx/eagl.c)。
- **当前状态**：默认 `blit_targets = 1` 使 OpenGL ES 应用每帧多做一次约 `50.6 MB` 显存读写 Blit，遇到步幅未按 `64 B` 对齐的 `IOSurface` 时退回全帧 `checksum()` 加 CPU `glReadPixels` 读回。

## 5. 量化瓶颈汇总与改造方案索引

| 编号 | 级别 | 模块与瓶颈摘要 | 核心量化代价 | 改造方案章节与批次 |
| :--- | :--- | :--- | :--- | :--- |
| P0-1 | P0 | `IOMobileFramebuffer` CPU 哈希与双线性缩放拷贝 | `120 Hz` 下 `2.91～4.43 GB/s` CPU 访存 | [方案 §3.1](../plan/2026-11-14-performance-and-native-alignment-plan.md#3-第-2-批显示-dpu-直扫ubwc-表面与-iris-零拷贝p0-1--p0-2--p0-6--p1-4)（第 2 批） |
| P0-2 | P0 | `MiniIOSurface` 全链路未压缩线性布局 | 多消耗 `35%～50%` LPDDR5X 显存带宽 | [方案 §3.2](../plan/2026-11-14-performance-and-native-alignment-plan.md#3-第-2-批显示-dpu-直扫ubwc-表面与-iris-零拷贝p0-1--p0-2--p0-6--p1-4)（第 2 批） |
| P0-3 | P0 | UFS `256 KiB` 中转 `memcpy` 与同步 `ufs_strategy` | `500 MB/s` 读下 `1.0 GB/s` 刷缓存 + `500 MB/s` 拷贝 | [方案 §2.1](../plan/2026-11-14-performance-and-native-alignment-plan.md#2-第-1-批存储底座与可写-apfs-完整切换p0-3--p0-4--p1-2--p1-3)（第 1 批） |
| P0-4 | P0 | 可写 APFS 缺目录/xattr/pageout 且每 `4 KiB` 提交检查点 | 写放大约 `12×`，`1 MB` 追加写分配 `295 MB` 堆内存 | [方案 §2.2](../plan/2026-11-14-performance-and-native-alignment-plan.md#2-第-1-批存储底座与可写-apfs-完整切换p0-3--p0-4--p1-2--p1-3)（第 1 批） |
| P0-5 | P0 | 相机逐帧启停、软件 I2C 与 8 核软件 Bayer ISP | `30 fps` 下 `142～184 MB/s` 拷贝 + 8 核满载 | [方案 §4.1](../plan/2026-11-14-performance-and-native-alignment-plan.md#4-第-3-批相机流式管线与整机中断化去轮询p0-5--p1-1--p1-7--p1-8)（第 3 批） |
| P0-6 | P0 | Iris VPU 全局锁、`250 us` 轮询与逐行 `copyout` | `4K60` 下 `752 MB/s` 刷缓存 + `19.4 万次/秒` `copyout` | [方案 §3.3](../plan/2026-11-14-performance-and-native-alignment-plan.md#3-第-2-批显示-dpu-直扫ubwc-表面与-iris-零拷贝p0-1--p0-2--p0-6--p1-4)（第 2 批） |
| P1-1 | P1 | Wi-Fi `1,800+ Hz` 轮询、双次拷贝与 `20 MHz` 限速 | 待机 `1,800+ 次/秒` 唤醒，吞吐受限于百兆级 | [方案 §4.2](../plan/2026-11-14-performance-and-native-alignment-plan.md#4-第-3-批相机流式管线与整机中断化去轮询p0-5--p1-1--p1-7--p1-8)（第 3 批） |
| P1-2 | P1 | UFS `hc_poller` 零睡眠忙等与拦截刷盘/`UNMAP` | 超 `100 us` I/O 占满 1 核，无持久刷盘屏障 | [方案 §2.1](../plan/2026-11-14-performance-and-native-alignment-plan.md#2-第-1-批存储底座与可写-apfs-完整切换p0-3--p0-4--p1-2--p1-3)（第 1 批） |
| P1-3 | P1 | APFS 全卷单锁 `am_lock`、无预读与 $O(N^2)$ `readdir` | 多进程缺页串行排队，大目录遍历呈平方级退化 | [方案 §2.3](../plan/2026-11-14-performance-and-native-alignment-plan.md#2-第-1-批存储底座与可写-apfs-完整切换p0-3--p0-4--p1-2--p1-3)（第 1 批） |
| P1-4 | P1 | 软件定时模拟 VSync、`SwapWait` 空实现与单槽覆盖 | 扫描相位错开微卡顿，`flipSplashPipe` 忙等 | [方案 §3.1](../plan/2026-11-14-performance-and-native-alignment-plan.md#3-第-2-批显示-dpu-直扫ubwc-表面与-iris-零拷贝p0-1--p0-2--p0-6--p1-4)（第 2 批） |
| P1-5 | P1 | GPU 共享 32 位 CB0、无抢占、串行 `-commit` 与同步 Blit | 贴图上传同步卡顿，冷启动重复编译着色器，残留 `redwoodmetal` | [方案 §5.1](../plan/2026-11-14-performance-and-native-alignment-plan.md#5-第-4-批gpu-与密码学加速及遗留项收敛p1-5--p1-6--p2-1p2-4)（第 4 批） |
| P1-6 | P1 | `minicrypto` 软件查表 AES、标量 SHA 与单锁 PRNG | 签名哈希与内核加密比硬件指令慢 `10～30 倍` | [方案 §5.2](../plan/2026-11-14-performance-and-native-alignment-plan.md#5-第-4-批gpu-与密码学加速及遗留项收敛p1-5--p1-6--p2-1p2-4)（第 4 批） |
| P1-7 | P1 | ADSP GLINK 轮询、功放软件 I2C 与单槽麦克风 | 常驻 `50～1,000 Hz` 唤醒（麦克风冗余睡眠已修） | [方案 §4.3](../plan/2026-11-14-performance-and-native-alignment-plan.md#4-第-3-批相机流式管线与整机中断化去轮询p0-5--p1-1--p1-7--p1-8)（第 3 批） |
| P1-8 | P1 | 触控/按键/蓝牙 TX/电量计等常驻轮询群 | 待机数百 Hz 唤醒与空载 SPI 读取（马达/手电筒已修） | [方案 §4.4](../plan/2026-11-14-performance-and-native-alignment-plan.md#4-第-3-批相机流式管线与整机中断化去轮询p0-5--p1-1--p1-7--p1-8)（第 3 批） |
| P2-1 | P2 | `init.c` 自检门控（已修）与内核 `xsmall` 容量档位 | `16 GiB` 内存机型沿用 `xsmall` vnode/ncache 配额 | [方案 §5.3](../plan/2026-11-14-performance-and-native-alignment-plan.md#5-第-4-批gpu-与密码学加速及遗留项收敛p1-5--p1-6--p2-1p2-4)（第 4 批） |
| P2-2 | P2 | 协处理器固件 64 位装载（已修）与后台异步预热 | 开机前台串行等待固件认证 | [方案 §5.3](../plan/2026-11-14-performance-and-native-alignment-plan.md#5-第-4-批gpu-与密码学加速及遗留项收敛p1-5--p1-6--p2-1p2-4)（第 4 批） |
| P2-3 | P2 | `/private/var/jb` 内存拷贝与 Poster 挂起 `usleep` | 开机拷贝开销；挂起扩展阻塞 `-commit`（缓存/转储已修） | [方案 §5.3](../plan/2026-11-14-performance-and-native-alignment-plan.md#5-第-4-批gpu-与密码学加速及遗留项收敛p1-5--p1-6--p2-1p2-4)（第 4 批） |
| P2-4 | P2 | `eagl.c` 默认 `blit_targets=1` 整帧冗余 FBO Blit | OpenGL ES 每帧多读写约 `50.6 MB` 显存 | [方案 §5.3](../plan/2026-11-14-performance-and-native-alignment-plan.md#5-第-4-批gpu-与密码学加速及遗留项收敛p1-5--p1-6--p2-1p2-4)（第 4 批） |
