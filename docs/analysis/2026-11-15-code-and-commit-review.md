# 多轮代码、提交与真机回归审查记录（2026-11-15）

适用范围：`hackios-xnu-kernel`（`k90-port`）、`hackios-xnu-userland`（`k90-port`）及顶层 `tools/`。本文集中记录 2026-11-14 至 2026-11-15 期间多轮提交前差异审查、真机回归复盘、工具链实测验证，以及 2026-11-08 至 2026-11-14 历史 Git 提交回溯审计查明的全部缺陷与跟进状态。未完成事项统一归入[待办目录](../backlog/README.md)跟踪。

## 1. 真机回归根因（桌面纹理异常与无充电提示音）

2026-11-14 真机桌面巡检观察到两项回归现象，经原始日志与源码逐行核对已定位根因并派发返工。

| 编号 | 现象与日志判据 | 源码位置与引入范围 | 根因与修复要求 | 状态 |
|---|---|---|---|---|
| R2-01 | 桌面壁纸右下角出现条纹纹理，内核与用户态日志单轮出现 `1,310` 条 `nil linear texture` | [annibalemetal_texture.inc](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_texture.inc)（工作树未提交改动） | 为非对齐行距线性包装纹理强行置入 `shape.usage \|= 0x80000000u`，污染 `MTLTextureDescriptor` 公开 `usage` 位域并使下游纹理创建失败；改为内部结构体独立布尔字段传递布局标志 | 返工修复中 |
| R2-02 | 开机后无充电提示音，日志记录右声道 `ch1` 停在 `MANSTATE=9` 且后续 `AudioReach` 出现 `9066 ms lost` | [annibale_audio_amp.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_audio_amp.c)、[annibale_audio_reach.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_audio_reach.c)（提交 `487556da` 及工作树） | `tfa986x_start_operating_one` 状态轮询上限缩至 `25 ms` 截断右声道 `0x36` 启动；`annibale_audio_reach.c` 调用 `thread_terminate(current_thread())` 永久销毁音频线程；复审另查出 `build_audioreach_graphs` 同步发送静音使校准时 TDM 已断流、`in_flight_mask` 排空循环缺少超时上限、`reach_feeder_thread` 预热 4 槽后未重检 `inflight < IN_FLIGHT`，以及合并时在空闲关功放分支重现 `thread_terminate` | 返工修复中（见 [M3](../backlog/multimedia.md)） |

## 2. 存储、可写 APFS 与 UFS 驱动缺陷

针对 `487556da` 已合入的 APFS 模块化代码及工作树可写 APFS、UFS 中断改造，静态审计查明以下内核安全与契约缺陷。

| 编号 | 严重度 | 源码位置与引入范围 | 缺陷事实与修复要求 | 状态 |
|---|---|---|---|---|
| ST-01 | 阻断（Ring-0 堆越界） | [apfs_write_ops.inc](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_write_ops.inc)（提交 `487556da` 及工作树） | 跨 `4 KiB` 块边界写入用单次 `if` 处理首尾分块，跨两块以上的写入使 `uint64_t` 计算发生无符号下溢并覆写内核堆；改为按块循环推进偏移与剩余字节 | 返工修复中 |
| ST-02 | 阻断（内核栈溢出） | [apfs_txn.inc](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_txn.inc)（提交 `487556da` 及工作树） | `struct apfs_txn` 与 `txn_cow_omap` 局部数组在 16 KiB XNU 内核栈上单次占用逾 `12.5 KiB`，叠加 VFS 调用栈极易溢出；改为 `kalloc_type`／`kalloc_data` 堆分配 | 返工修复中 |
| ST-03 | 高危（元数据损坏与越界） | [apfs_write_ops.inc](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_write_ops.inc)、[apfs_vnops_write.inc](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_vnops_write.inc)（工作树） | `apfs_setattr` 直接覆写 `inode.mode` 抹掉高 4 位 `APFS_S_IFMT` 文件类型位，并以 `uid != 0` 判断导致 `chown(0, 0)` 被忽略；目录查找按 `strlen(cnp->cn_nameptr)` 读取非 `\0` 结尾组件越界；`setxattr` 未限制分配长度；缺少 `vnop_blockmap` 即调用 `cluster_write` | 返工修复中 |
| ST-04 | 高危（假实现与容量越界） | [apfs_vfsops_sync.inc](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_vfsops_sync.inc)、[apfs_txn.inc](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_txn.inc)、[apfs.h](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs.h)（工作树） | `apfs_flush_dirty_checkpoint` 未落盘即清零脏位返回 0；OMAP 满 112 项静默丢弃更新，检查点环回绕偏移错误；二次复审另发现未被任何单元包含的孤立重复文件 `apfs_vnops_xattr.inc` 与未定义原型残留；单 chunk 位图与单层根页树完成扩容前，`var_apfs=1` 维持默认关闭 | 返工修复中（见 [S18](../backlog/system.md)） |
| ST-05 | 阻断（并发竞争、槽位复用踩踏与脏缓存） | [annibale_ufshc_intr.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_ufshc_intr.inc)、[annibale_ufshc_rw.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_ufshc_rw.inc)（工作树） | GICv3 `INTID 297` 中断处理无锁执行 `wakeup` 与 `hc_give`、散聚 DMA 读缺缓存失效化且局部 `InvalidatePoC_DcacheRegion` 与 `caches_asm.s` 全局符号同名冲突；三次复审另查出同步路径 `hc_complete` 返回前未清除 `hc_active_slots` 与 `hc_pending_slots`，槽位立即复用给新异步请求时会被 `ufshc_process_completions` 在硬件 DMA 仍在途期间误判 `OCS_INVALID` 提前触发 `buf_biodone` 并释放槽位 | 返工修复中 |

## 3. ADSP、共享内存、电源与时钟基础模块缺陷（更早提交回溯）

回溯审计 2026-11-10 至 2026-11-13 内核提交（`7507f4c9`、`2d9a59e0`、`20550698`）查明三项内核内存安全问题与一项全机系统调用开销问题。

| 编号 | 严重度 | 源码位置与提交 | 缺陷事实与修复要求 | 状态 |
|---|---|---|---|---|
| PL-01 | 阻断（Ring-0 持锁死循环与越界） | [annibale_adsp.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_adsp.c)（`7507f4c9`、`2d9a59e0`） | `smem_peek`、`smem_poke` 与 `smem_item_in_partition` 用 32 位加法校验边界，缺少 `padding_data <= size` 与 64 位防溢出判断；`glink_poll_rx` 从共享内存计算 `step_bytes`，32 位回绕、`step_bytes == 0` 或越界会在持有 `glink_rx_lock` 时死循环，且 `count > 64` 清零计数后仍按原 `w1` 步进；`GLINK_TX_DATA_CONT` 续包被直接按首包头部解析，超 `512 B` 分片被丢弃后仍回传 `GLINK_DONE_REUSE` | 已派发修复（见 [P20](../backlog/platform.md)） |
| PL-02 | 阻断（未初始化栈指针释放） | [annibale_adsp.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_adsp.c)、[annibale_adsp_fw.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_adsp_fw.inc)（`7507f4c9`） | `annibale_adsp_boot_thread` 栈变量 `struct fw_image dtb_fw, main_fw` 未零初始化；首项 `fw_load_mdt("adsp_dtb", ...)` 失败触发 `&&` 短路后，`else` 分支对含栈随机值的 `main_fw` 调用 `fw_release` 执行 `kfree_data`，触发内核堆损坏；声明处须显式清零 | 已派发修复（见 [P20](../backlog/platform.md)） |
| PL-03 | 中危（非对齐访问与数据竞争） | [annibale_battery.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_battery.c)（`7507f4c9`） | `annibale_pmic_glink_rx` 将栈上 1 字节对齐的 `uint8_t buf[512]` 强转为 `const uint32_t *` 读取，且更新 `pmic_glink_state` 字段与自增 `seq` 缺少锁或原子操作保护 | 已派发修复（见 [P20](../backlog/platform.md)） |
| PL-04 | 性能架构项（全机 EL1 陷入） | [annibale_mach_timebase.h](../../hackios-xnu-kernel/xnu/files/osfmk/arm/annibale_mach_timebase.h)、`xnu26/patches/42-osfmk%arm64%machine_routines.c.patch`（`20550698`） | 为把 SM8750 硬件 `19.2 MHz` `CNTVCT_EL0` 换算为 iOS 26 期望的 `24 MHz` 时钟滴答，内核清空 `CNTKCTL_EL1_PL0PCTEN \| PL0VCTEN` 并令 `user_timebase_type()` 返回 `USER_TIMEBASE_NONE`，导致全机用户态每次调用 `mach_absolute_time()`／`mach_continuous_time()` 均执行 `SVC` 陷入内核；需结合 23G90 `libsystem_kernel.dylib` 反汇编评估用户态无陷入换算方案 | 归入 [S19](../backlog/system.md) |

## 4. 图形、Metal、密码学与网络缺陷

针对 Wave 1 图形缓冲拷贝、SMMU 页表刷新、ARMv8 密码学扩展与 PCIe MSI 改造，审查拦截了以下寄存器破坏与并发缺陷。

| 编号 | 严重度 | 源码位置与引入范围 | 缺陷事实与修复要求 | 状态 |
|---|---|---|---|---|
| GX-01 | 高危（CPU／GPU 竞争与越线文件净增） | [air_metal.c](../../hackios-xnu-userland/tools/mesa/air/air_metal.c)、[air_metal_copy.inc](../../hackios-xnu-userland/tools/mesa/air/air_metal_copy.inc)、[annibalemetal_blit.inc](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_blit.inc)、[annibalemetal_pipecache.inc](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_pipecache.inc)、[adreno8_smmu.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/adreno8/adreno8_smmu.c)（工作树） | `rwa_buffer_fill` 与 `RW_COPY_BUFFER_TEXTURE` 未等待在途命令即用 CPU 读写 GPU BO；`air_metal.c` 超 1200 行存量文件发生净增长；`air_metal_copy.inc` 误删 `buffer_mirror_pull(dst)` 使后续 `mirror` 写入漏拷，且直接去掉同步等待破坏 `air_copy_test.c` 与 `ANNIBALE_SYNC_DRAWS`（须保留同步入口并新增 `*_nowait` 留待 `-commit` 批量提交）；`adreno8_smmu_tlb_invalidate_range` 早期缺 64 页整刷阈值 | 返工修复中 |
| GX-02 | 高危（Liquid Glass 渲染缺块） | [eagl.c](../../hackios-xnu-userland/userland/src/gfx/eagl.c)（工作树） | 工作树改动擅自把 `blit_targets` 默认值从 `1` 改为 `0`，破坏 Adreno／Freedreno 上的 `EXT_shader_framebuffer_fetch` 帧缓冲回读契约，会导致控制中心模块与桌面图标隔帧缺块；须完整回退该文件改动 | 返工回退中 |
| NW-01 | 阻断（EL1 非法指令崩溃与寄存器损坏） | [mc_ce_arm64.h](../../hackios-xnu-kernel/xnu/files/osfmk/minicrypto/mc_ce_arm64.h)、[mc_ce_arm64.c](../../hackios-xnu-kernel/xnu/files/osfmk/minicrypto/mc_ce_arm64.c)、[mc_provider.c](../../hackios-xnu-kernel/xnu/files/osfmk/minicrypto/mc_provider.c)、[mc_aes.c](../../hackios-xnu-kernel/xnu/files/osfmk/minicrypto/mc_aes.c)（工作树） | 首版漏存 `v8`、`v9`、`v16`、`v17` 且缺 `!ml_at_interrupt_context()`；二次复审查出 `mc_ce_init` 误将 `ID_AA64ISAR2_EL1[11:8]`（`GPA3`）识别为 `RNDR`（实际在 `ID_AA64ISAR0_EL1[63:60]`），且 `mc_provider.c` 未检查 `mc_ce_has_rndr()` 即执行 `mrs s3_3_c2_c4_0` 触发开机 EL1 非法指令崩溃；另查出 7 处 `subs` 内联汇编漏写 `"cc"` 破坏标记、用户态破坏被调者保存寄存器 `d8`（`q8`），以及开机 `mc_aes_selftest` 样本小于 `64 B` 未覆盖 CE 分支 | 返工修复中 |
| NW-02 | 高危（MSI 组映射错位与无中断长睡） | [mhi_pcie.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/mhi/mhi_pcie.c)、[mhi_pcie_fw.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/mhi/mhi_pcie_fw.c)、[annibale_lx.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_lx.c)、[lx_pci.c](../../hackios-xnu-kernel/wifi/lx/ath12k/lx_pci.c)（工作树） | DesignWare RC0 每组 `PCIE_MSI_INTR_STATUS(g)` 映射连续 32 个向量 `g * 32 + b`，`annibale_lx.c` 误写成 `vector % 4` 与 `line + b * 4`，且 `lx_os_irq_msi` 硬编码 `0x40200000` 与 `mhi_pcie_fw.c` 写入的 `mhi_pcie_sink_pa` 失配；同时 `lx_pci.c` 未向 `ath12k` SRNG 提供 MSI 却将 `bus_looks` 改为 `50 ms` 睡眠，`ipcr_thread` 无下行唤醒却改为 `100 ms` 睡眠，须改为统一 MSI 地址并恢复自适应毫秒级短周期 | 返工修复中 |
| NW-03 | 阻断（Wi-Fi 封装与校验和全断） | [lx_80211.c](../../hackios-xnu-kernel/wifi/lx/src/lx_80211.c)、[annibale_net.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_net.c)（工作树） | WCN7850 固件不提供 Ethernet 封装模式，工作树改动强置 `IEEE80211_OFFLOAD_ENCAP_ENABLED` 并在 802.11+LLC／SNAP 帧上硬加 `IEEE80211_TX_CTL_HW_80211_ENCAP`；同时对无硬件 L3／L4 校验和计算的接口调用 `ifnet_set_offload(ifp, IFNET_CSUM_IP \| IFNET_CSUM_TCP \| IFNET_CSUM_UDP)` 使全部出站 IP／TCP／UDP 报文校验和失效，且 `net_thread` 在 `poll == NULL` 分支跳过了每分钟一次的流量统计日志 | 返工修复中 |

## 5. 用户态注入、系统服务与原生契约问题（更早提交回溯）

回溯审计用户态提交（`ab4123b`、`daf4d65`、`134708e`、`5fe5a43`、`01ccb72`）发现两类内存泄漏／文件竞争缺陷，以及若干尚未按 [AGENTS.md §6](../../AGENTS.md#6-根因定位与原生对齐约定必须遵守) 下线的存量方法交换代码。

| 编号 | 类别 | 源码位置与提交 | 缺陷事实与收敛安排 | 状态 |
|---|---|---|---|---|
| UL-01 | 内存泄漏、并发写坏配置与废钩子 | [inject_sb26.c](../../hackios-xnu-userland/userland/src/inject/inject_sb26.c)、[inject_sb26_loc.inc](../../hackios-xnu-userland/userland/src/inject/inject_sb26_loc.inc)、[inject_posterboard.c](../../hackios-xnu-userland/userland/src/inject/inject_posterboard.c)（`ab4123b`、`01ccb72`） | `CFDataCreateWithBytesNoCopy` 返回 `NULL` 时泄漏 `malloc` 缓冲 `buf`；`sb26_ensure_chinese_preferences` 在 `SpringBoard`、`Preferences`、`lsd`、`wifid` 四进程构造函数中并发执行 `open(..., O_TRUNC)` 直写 `.GlobalPreferences.plist`，存在截断竞争导致既有配置丢失（须改用临时文件写入加 `rename` 原子替换并限定单进程初始化）；`inject_posterboard.c` 残留空操作 `mercury_cmdbuf_commit` 钩子 | 已派发修复 |
| UL-02 | CoreFoundation／HID 资源泄漏 | [inject_touch.inc](../../hackios-xnu-userland/userland/src/inject/inject_touch.inc)、[input26_service.c](../../hackios-xnu-userland/userland/src/services/input26_service.c)（`134708e`、`daf4d65`） | `make_service` 与 `make_service_ext` 创建 `pair`、`pairs`、`name`、`CFNumber` 后未释放本地 `+1` 引用；重试失败或提前返回 `NULL` 时泄漏 `struct service`、`properties` 字典及失败轮次的 `IOHIDEventSystemClient` 与 `dispatch_queue` | 已派发修复 |
| UL-03 | 存量方法交换与单应用环境变量 | [inject_sb26_airdrop.inc](../../hackios-xnu-userland/userland/src/inject/inject_sb26_airdrop.inc)、[inject_cellular.inc](../../hackios-xnu-userland/userland/src/inject/inject_cellular.inc)、[inject_sb26_loc.inc](../../hackios-xnu-userland/userland/src/inject/inject_sb26_loc.inc)、[inject_app.c](../../hackios-xnu-userland/userland/src/inject/inject_app.c)（`ab4123b`、`daf4d65`、`5fe5a43`） | 存量代码对 `SFAirDropDiscoveryController`／`MRUMirroringController`／`AVOutputContext`（10 处）、`CTCarrier`／`CTTelephonyNetworkInfo`／`STTelephonyStatusDomainSIMInfo`（8 处）、`SBApplication`／`LSApplicationRecord` 图标标题（8 处）与 `-[WKPreferences init]` 使用方法交换，并在 `inject_app.c` 读取 `/annibale/etc/env/<progname>` 注入单应用环境变量；须分别随 `sharingd`／`mediaremoted`、`CommCenter`／`systemstatusd` 与 LaunchServices 原生契约补齐后逐项移除 | 归入 [ENG-07](../backlog/engineering.md)、[P13](../backlog/platform.md)、[P17](../backlog/platform.md) |

## 6. 构建编排、自动化脚本与无效单测问题

对用户态构建重构（Stage T2）、顶层真机脚本与历史测试提交（`3c57777`、`c9f5c32`）做实测验证后，查明以下工程工具缺陷。

| 编号 | 严重度 | 源码位置与范围 | 缺陷事实与修复要求 | 状态 |
|---|---|---|---|---|
| TL-01 | 阻断（丢失头文件增量依赖与静默丢权限） | [compile_targets.py](../../hackios-xnu-userland/userland/compile_targets.py)、[build.sh](../../hackios-xnu-userland/userland/build.sh)（工作树 Stage T2） | 多源文件目标共用同一 `-MF <target>.d` 覆盖前序依赖；首次建档检测到旧二进制存在即跳过编译；`codesign` 带权限失败时静默回退为空权限签名并删去 Linux 容器 `ldid` 分支；`build.sh` 误删 `GL=1` OSMesa 构建段；二次复审另查出 `parse_depfile` 按调用进程当前目录解析相对路径，从非 `userland/` 目录调用时会漏掉全部 `.inc`／`.h` 依赖 | 返工修复中（见 [ENG-22](../backlog/engineering.md)） |
| TL-02 | 中危（违反留驻桌面约定与超时挂起） | [cycle.py](../../tools/k90auto/cycle.py)（`c9f5c32`、`d3601e6`） | `UNLOCK_WAIT` 超时未解锁时未写 `stop-request`，在 `--hold`（`seconds=0`）下 `rounder.wait()` 永久阻塞；`--hold` 阻塞期间不执行 `render-health.py`，非 `--hold` 则立即停机退回 `xnuloader`，缺少完成巡检出报告后保持设备留在 iOS 桌面运行态的路径 | 归入 Stage T3（见 [ENG-22](../backlog/engineering.md)） |
| TL-03 | 高危（无效伪单测） | 顶层 `3c57777` 及内核 `tools/tests/` 新增脚本 | 历史协作轮次曾在未编译被测 C 代码的情况下，用源码子串搜索或脚本局部变量恒真断言用作单测并返回 0；须删除无被测调用的伪单测，改为编译真实 C fixture 校验实际行为 | 返工清理中 |

## 7. 已复核确认稳健的早期提交基线

以下近期与早期关键提交经逐行阅读核实边界条件、并发锁序与硬件同步语义无误，保留为当前稳定基线。

- [kern_minisandbox_extension.inc](../../hackios-xnu-kernel/xnu/files/bsd/kern/kern_minisandbox_extension.inc)（提交 `20550698`、`2fac3a50`）采用 `os_refcnt` 引用计数、`proc_uniqueid` 与 `proc_pidversion` 双重身份校验、`copyout` 期间 `proc_transstart` 保护、`fork` 继承复制及 `exec`／`exit` 清理，生命周期完整。
- [annibale_rpmh.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_rpmh.c)（`7507f4c9`）、[annibale_camera_smmu.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_camera_smmu.inc)（`20550698`）与 [annibale_iris.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_iris.c)（`edd5177c`、`972ee4b9`）的寄存器轮询超时、SMMU 页表刷写及缓冲归还状态机核查通过。
- [MiniFramebufferRows.inc](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferRows.inc)（`0e0f19bb`）与 [loader_06_usb_entry.inc](../../hackios-xnu-kernel/xnuloader/loader_06_usb_entry.inc)（`aa21b8ec`）的行哈希边界、SWAR 双像素缩放及 DWC3 单请求归属校验未发现越界或重入漏洞。

## 8. 后续跟踪入口与常设审查门禁

上述未结事项已按职责写入各专题待办，后续批次统一按编号推进与销项。

- 存储与时钟基础模块事项归入 [S18](../backlog/system.md)（可写 APFS 扩容与落盘前置契约）与 [S19](../backlog/system.md)（`24 MHz` Mach 时钟用户态快路径评估）。
- 音频、ADSP 与外设契约事项归入 [M3](../backlog/multimedia.md)（双路功放与音频线程恢复）、[P20](../backlog/platform.md)（ADSP SMEM／GLINK 边界防护与固件释放）及 [P13](../backlog/platform.md)、[P17](../backlog/platform.md)（蜂窝与隔空投送原生服务替代）。
- 构建工具与注入钩子下线事项归入 [ENG-07](../backlog/engineering.md)（剩余注入钩子原生化）与 [ENG-22](../backlog/engineering.md)（用户态增量编译与 `cycle.py` 留驻桌面改造）。

按 [AGENTS.md §6](../../AGENTS.md#6-根因定位与原生对齐约定必须遵守) 执行后续批次提交前审查时，主负责人固定核对四项硬指标：全量 `git diff` 无空壳桩函数与公开标志位污染、内核函数单次栈帧远低于 16 KiB 且共享内存输入具备 64 位无符号防回绕校验、增量构建脚本在修改任一 `.h`／`.inc` 后实测触发重新编译、新增测试实际编译链接被测实现且真机验收后保持在 iOS 桌面运行态。
