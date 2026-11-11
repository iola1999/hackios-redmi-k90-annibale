# 2026-11-06 开机后实测问题与后续跟进清单

本文保留问题分析与已有结果；未完成事项集中在[待办目录](../backlog/README.md)。

本文记录 2026-11-06 至 11-07 期间 `boot_a` 独立双系统引导进入 iOS 26 桌面后，真机交互实测问题的根因定位与修复记录。当前验收状态以[11-08 复核](../analysis/2026-11-08-issue-reassessment.md)与[进度表](2026-10-23-tracking.md)为准。

## 1. 11-06 实测问题的根因、修复与验证

### 1.1 控制中心与底部 Dock 图形渲染异常、控制中心亮度条不可见

- **现象**：
  - 控制中心左上 2×2 连接卡片、右上 2×2 媒体卡片、圆角按钮及主屏底部 Dock 栏外围出现不透明纯白或浅灰矩形方框。
  - 控制中心亮度胶囊外框可见，拖动滑块能改变面板背光，但胶囊内部白色填充条不显示。
- **根因**：
  1. **顶点着色器 CSO 缓存悬垂指针（Use-After-Free）**：[`hackios-xnu-userland/tools/mesa/air/air_metal_vertex_cache.inc`](../../hackios-xnu-userland/tools/mesa/air/air_metal_vertex_cache.inc) 的 `ann_vertex_cso_cache_put()` 仅浅拷贝 `e->vinfo = *vinfo`，未深拷贝 `vinfo->varyings[i].name` 与 `vinfo->vertex_attributes[i]` 字符串；首个渲染管线编译完成后释放 `air_ctx`，后续命中同一顶点 CSO 缓存的管线在链接片元着色器时读取已释放的 varying 名称，导致 varying 槽位绑定错乱或管线编译失败。
  2. **管线失败回退为空白片元管线与单采样 Resolve Blit 退化**：[`hackios-xnu-kernel/tools/userland-driver/annibalemetal.m`](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal.m) 在管线创建失败时构造无片元着色器的回退管线，把失败图层画成不透明纯白矩形；同时将单采样 `MTLStoreActionMultisampleResolve` 改为 `endEncoding` 阶段执行 resolve blit，破坏了单采样附件的原地混合。
  3. **`TbdsA2Xhf` 拼接函数选择器与大于 64 位的函数常量**：[`annibalemetal_stitch.inc`](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_stitch.inc) 的 `AnnibaleMetalStitchedFunction` 在 `_cachedBitcode != nil` 时对 `annibaleUnspecializedFunction` 返回底函数 `_function`，导致驱动丢弃拼接后的快速路径字节码；[`air_to_nir.c`](../../hackios-xnu-userland/tools/mesa/air/air_to_nir.c) 的 `air_load_ptr()` 拒绝 `comps * bits > 64` 的向量函数常量（如 `float4`），导致控制中心亮度条与玻璃着色器编译报错。
  4. **SpringBoard 玻璃背景强制涂白钩子**：[`inject_sb26.c`](../../hackios-xnu-userland/userland/src/inject/inject_sb26.c) 中的 `install_bar_background_hooks()` 与 `install_widget_hooks()` 将 `_UIBarBackground`、`_GlassGroupView` 背景层强制设为不透明白底 `rgba(1, 1, 1, 0.9)`。
- **修复**：
  - [`air_metal_vertex_cache.inc`](../../hackios-xnu-userland/tools/mesa/air/air_metal_vertex_cache.inc)：为每个缓存条目分配独立 `e->mem_ctx`，深拷贝 `varyings` 与 `vertex_attributes` 及其名称字符串，并在销毁缓存时释放。
  - [`annibalemetal.m`](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal.m) 与 [`annibalemetal_pipecache.inc`](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_pipecache.inc)：移除纯白回退管线，恢复单采样 `MTLStoreActionMultisampleResolve` 直接绑定 `_resolve[i]` 纹理。
  - [`annibalemetal_stitch.inc`](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_stitch.inc) 与 [`air_to_nir.c`](../../hackios-xnu-userland/tools/mesa/air/air_to_nir.c)：修正 `_cachedBitcode != nil` 时的选择器响应，支持 `comps * bits > 64` 的函数常量高位补零加载。
  - [`inject_sb26.c`](../../hackios-xnu-userland/userland/src/inject/inject_sb26.c)：移除 `install_bar_background_hooks()` 与 `install_widget_hooks()`。
- **验证**：开机进入主屏并下拉控制中心截图确认，主屏 Dock 与控制中心各模块恢复半透明圆角 Liquid Glass 背景，白底方框消失；控制中心亮度滑块内部白色填充条正常渲染。

### 1.2 设置页存储容量显示与 128 GB 容器口径对齐

- **现象**：早期「设置 → 通用 → 关于本机」中总容量显示为 `0 KB`、可用 `2.61 GB`；初次接入 `darwin_var` 分区块数后显示为总容量 `129 GB`、可用 `128.22 GB`（未扣除系统卷与 Cryptex 占用，且按二进制 120 GiB 换算成十进制 129 GB）。
- **根因**：iOS 的 `storagekitd` 与 `Preferences` 通过 `IOKit` `IOMedia`（`disk0` 的 `Size` 属性）、`statfs()` 与 `getattrlistbulk`（`VOL_ATTR_CAPABILITIES`）按十进制字节（`1 GB = 10^9 B`）计算整机共享 APFS 容器的总容量与可用容量；128 GB iPhone 17 的容器总容量为 `128,000,000,000` 字节，可用容量为容器总容量减去 System 卷（9.76 GB）、OS Cryptex（5.26 GB）、App Cryptex（14.68 MB）、Preboot／Recovery（0.54 GB，小计 15.57 GB）以及 `/private/var` 实际已用数据块。
- **修复**：在 [`AnnibaleBT.cpp`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/AnnibaleBT.cpp) 与 [`annibale_ufs.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_ufs.c) 中将 `disk0` 容量设为 `128,000,000,000` 字节；在 [`ramfs_getattr.inc`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_getattr.inc) 与 [`apfs_vfsops.c`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_vfsops.c) 中统一由 `annibale_container_total_bytes()` 与 `annibale_container_free_bytes()` 上报 `/` 与 `/private/var` 的 `statfs` 及 `vfs_getattr`，总容量显示为 `128 GB`，初始可用容量约 `112.4 GB` 并随文件写入实时递减。

### 1.3 设置页一级列表图标全部缺失

- **现象**：打开「设置」（`Preferences`）主列表时，各设置项左侧图标全部空白。
- **根因**：[`hackios-xnu-userland/tools/mesa/air/air_metal_texture.inc`](../../hackios-xnu-userland/tools/mesa/air/air_metal_texture.inc) 在 `263e886` 中将 `PIPE_FORMAT_A8_UNORM` 纹理的默认采样 swizzle 改写为 `(X, X, X, X)`，破坏了 Gallium `util_format_a8_unorm` 原生的 `(0, 0, 0, R)` 通道映射（着色器读取 `.a` 分量获取遮罩透明度，`.rgb` 应为 0），加之 §1.1 的顶点 CSO 缓存悬垂指针导致图标合成管线异常。
- **修复**：从 [`air_metal_texture.inc`](../../hackios-xnu-userland/tools/mesa/air/air_metal_texture.inc) 移除对 `PIPE_FORMAT_A8_UNORM` 的强制 `PIPE_SWIZZLE_X` 覆盖，配合 §1.1 的顶点 CSO 缓存深拷贝修复。
- **验证**：打开「设置」主列表与「通用」子列表截图确认，全部设置项左侧彩色图标完整显示。

### 1.4 进入设置子页面时背光短暂变暗再恢复与低亮度滑块线性区间

- **现象**：首次打开「设置」或点击进入子页面转场时，屏幕亮度会短暂降低再恢复；控制中心滑块拉到中段以下时面板背光停在约 140 nits。
- **根因**：
  1. 通过 [`dsc.py`](../../hackios-xnu-kernel/tools/dsc/dsc.py) 反汇编 iOS 26（23G90）`CoreBrightness` 框架并核对转场日志确认：`CoreBrightness` 在设置子页面转场自主斜坡（`140.0 ↔ 168.0 nits`）的每一帧（约 16 毫秒间隔）也会同时向 `AppleARMBacklight` 下发 `DisplayBrightness` 与 `brightness-nits`，并向 `IOMobileFramebuffer` 下发 `IOMFBBrightnessLevel`。
  2. [`MiniAppleARMBacklight.cpp`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniAppleARMBacklight.cpp) 在 `417bae9` 中把连续收到 `DisplayBrightness` 也作为开启 `bl.user_until` 滑块窗口的条件，导致自主转场斜坡第 2 帧即误触发 `bl.user_until`；同时 `publish_calibration()` 将 `lMidPanel`／`lMidProduct` 设为 `kBLMilliNitsMid`（140 nits），导致 `CoreBrightness` 在 `DisplayBrightness < 49398` 时把 `brightness-nits` 夹紧在 `9175040`（140 nits）。
- **修复**：
  - 在 [`MiniAppleARMBacklight.cpp`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniAppleARMBacklight.cpp) 中，仅在收到 `DisplayBrightnessSliderPosition`（仅用户实际拖动亮度滑块时发送）时开启 `bl.user_until`（500 毫秒）滑块活跃窗口。
  - 将 `publish_calibration()` 中的 `lMidPanel` 与 `lMidProduct` 下调为 `fixed_nits(kBLMilliNitsMin)`（5 nits），并在 `n16 == fixed_nits(kBLMilliNitsMid)` 且 `DisplayBrightness < 49398` 时按线性比例映射到 `5..140 nits`。

### 1.5 日历（MobileCal）重复弹出通知权限申请与系统通知 Bundle

- **现象**：打开日历（`MobileCal`）弹出通知权限请求框，点击「允许」后关闭再重新打开日历，仍每次重复弹出同一权限申请。
- **根因**：
  1. 对比 `/var/mobile/Library/UserNotifications/Library.plist` 与 `/var/mobile/Library/BulletinBoard/VersionedSectionInfo.plist` 发现：`Library.plist` 已登记 `com.apple.mobilecal`，但 `VersionedSectionInfo.plist` 缺少 `com.apple.mobilecal` 的 `UNCSectionInfo` 记录。
  2. 通过 [`dsc.py`](../../hackios-xnu-kernel/tools/dsc/dsc.py) 反汇编 `UserNotificationsCore`（`+[UNCNotificationSourceDescription sourceDescriptionWithBundleIdentifier:]` `0x1de17a668`、`-[UNCNotificationSourceDescription setSystemPropertiesFromDictionary:]` `0x1de17b0f4`）与 `UserNotificationsServer`（`_queue_createDataProviderWithNotificationSourceDescription:withCompletion:` `0x29959624c`）查明：`sourceDescriptionWithBundleIdentifier:@"com.apple.mobilecal"` 首先在 `/System/Library/UserNotifications/Bundles/` 下查找 `com.apple.mobilecal.bundle`。裁剪版系统盘缺少该目录后回退读取 `/Applications/MobileCal.app/Info.plist`，而系统应用的 `UNUserNotificationCenter` 字典存放在 `/System/Library/UserNotifications/Bundles/com.apple.mobilecal.bundle/Info.plist` 中，主应用 `Info.plist` 不含该键，`setSystemPropertiesFromDictionary:` 计算出 `useDefaultDataProvider = NO`，导致 `_queue_createDataProviderWithNotificationSourceDescription:withCompletion:` 打印 `"Do not register notification settings for an app that is using a custom data provider"` 并中止，未写入 `VersionedSectionInfo.plist`。
- **修复**：
  - 在 [`ios26/full-system.py`](../../hackios-xnu-userland/ios26/full-system.py) 中保留 `System/Library/UserNotifications/` 下的 647 个通知配置 plist／strings 文件，并在 [`userland/build.sh`](../../hackios-xnu-userland/userland/build.sh) 与 [`userland/src/boot/init.c`](../../hackios-xnu-userland/userland/src/boot/init.c) 中挂载 `/System/Library/UserNotifications`；双系统部署直接挂载原版未裁剪 `os.dmg` 时自带完整通知 Bundle。
  - 从 [`userland/src/inject/ax.m`](../../hackios-xnu-userland/userland/src/inject/ax.m) 移除通知授权方法交换代码。

### 1.6 Wi-Fi 首次连接竞态、USB 充电检测、滑动关机与 LK `ValidateSlotGuids` 修复

1. **首次连接 Wi-Fi 报错「无法加入」随后自动连上，以及 `ath12k` 调试日志刷屏**：
   - **根因**：[`hackios-xnu-kernel/wifi/lx/ath12k/lx_pci.c`](../../hackios-xnu-kernel/wifi/lx/ath12k/lx_pci.c) 默认开启 `ATH12K_DBG_HTC` 且 `__ath12k_dbg()` 未检查 `ath12k_debug_mask`，连网后 30 秒内打印 14030 行 `htc rx completion` 冲掉内核日志环；[`lx_join.c`](../../hackios-xnu-kernel/wifi/lx/src/lx_join.c) 在收到关联应答（`0x10`）后尚未完成 `WMI_PEER_ASSOC` 与 `WMI_VDEV_UP` 时，接入点发来的 EAPOL 四次握手第 1 帧已触发回复第 2 帧，因驱动关联状态未就绪被丢弃。
   - **修复**：在 [`lx_pci.c`](../../hackios-xnu-kernel/wifi/lx/ath12k/lx_pci.c) 的 `__ath12k_dbg()` 中检查 `ath12k_debug_mask` 并移除默认 `ATH12K_DBG_HTC`；在 [`lx_80211.h`](../../hackios-xnu-kernel/wifi/lx/src/lx_80211.h)、[`lx_80211.c`](../../hackios-xnu-kernel/wifi/lx/src/lx_80211.c) 与 [`lx_join.c`](../../hackios-xnu-kernel/wifi/lx/src/lx_join.c) 中缓存 `reached < IEEE80211_STA_ASSOC` 阶段收到的 EAPOL 帧，待 `bss_changed(BSS_CHANGED_ASSOC)` 完成后重放，并在首次握手返回 `EAUTH` 时自动重试一次。
2. **插着 USB 线状态栏不显示充电且电量下降**：
   - **根因**：[`annibale_battery.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_battery.c) 原先仅从 BQ27Z561 电量计读取净电流 `current_ua`（将 `< -250 mA` 判为拔出充电器）；电脑 USB 端口默认 500 mA 供电低于亮屏功耗时被判为未接电源。
   - **修复**：在 [`annibale_battery.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_battery.c) 中结合 USB 控制器链路状态、PMIC `usbin` 与 `pmic_glink` VBUS 在线检测上报外部电源与充电状态。
3. **系统内滑动关机后画面停在最后一帧**：
   - **根因**：iOS 关机进入 `halt_all_cpus(FALSE)` 调用 `loader_return()` 退回 RAM 中的 `xnuloader`，而 `MiniIOMobileFramebufferQuiesce()` 将最后一帧拷回主帧缓冲并把混合器亮度恢复为 `DIM_ALPHA_FULL`（100%），面板背光保持常亮。
   - **修复**：在 [`MiniFramebufferDim.inc`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferDim.inc) 与 [`MiniFramebufferFlip.inc`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferFlip.inc) 新增 `dim_poweroff()` 与 `MiniIOMobileFramebufferPowerOff()` 清零双帧缓冲并关闭 OLED 背光；在 [`42-osfmk%arm64%machine_routines.c.patch`](../../hackios-xnu-kernel/xnu26/patches/42-osfmk%arm64%machine_routines.c.patch) 的 `halt_all_cpus()` 中依次执行持久化同步、外设停机与 `MiniIOMobileFramebufferPowerOff()`；在 [`annibale_threads.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_threads.c) 增加 `kern.annibale.halt` sysctl，并在 [`inject_sb26.c`](../../hackios-xnu-userland/userland/src/inject/inject_sb26.c) 拦截关机选择器执行 `sync()` 与 `kern.annibale.halt=1`。
4. **切槽引发 LK `ValidateSlotGuids` 报错（`Failed to load/authenticate boot image: Device Error`）**：
   - **根因**：反编译 `abl_a.img` 中的 `LinuxLoader.efi` 查明，`FindBootableSlot`（`sub_1D1B8`）内的 `ValidateSlotGuids` 比较 `boot_<slot>` 与 `abl_<slot>` 的 16 字节 `PartitionTypeGUID`：高通 A/B GPT 中活动槽位各分区具有独立的 `PartitionTypeGUID`，非活动槽位共用 `77036cd4-03d5-42bb-8ed1-37e5a88baa34`；若两者相同则打印 `"ValidateSlotGuids: BootableSlot %s does not have valid guids"` 并返回 `EFI_DEVICE_ERROR`。`xnuloader` 原先切槽仅改写 GPT 属性位而未交换 `_a`／`_b` 分区的 `PartitionTypeGUID`。
   - **修复**：在 [`loader_06a_screen_ui.inc`](../../hackios-xnu-kernel/xnuloader/loader_06a_screen_ui.inc) 中新增 `gpt_swap_ab_type_guids()` 与 `slot_apply_active()`，在维护或切换活动槽位时检查目标槽位 `PartitionTypeGUID`，若持有非活动 GUID 则同步交换 `_a`／`_b` 分区的 `PartitionTypeGUID` 并重算主备 GPT CRC32。

### 1.7 `/private/var` 内核直写块持久化（`ANNFS001`）与原版未裁剪三容器镜像直挂

1. **`/private/var` 内核直写 UFS 块持久化（`ANNFS001`）**：
   - 在 [`ramfs_disk.inc`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_disk.inc)、[`ramfs_fsctl.inc`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_fsctl.inc) 与 [`annibale_ufs_rw.inc`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_ufs_rw.inc) 中为 `/private/var` 实现直接绑定 UFS `darwin_var` 分区的内核块级持久化文件系统（魔数 `"ANNFS001"`）。
   - `[0, 32 MiB)` 与 `[32 MiB, 64 MiB)` 为双乒乓元数据槽位（保存全部 inode、目录树、符号链接、xattr 与 4 KB 物理块号表，带独立头部与负载 CRC32 校验），`[64 MiB, ...)` 为保留区与 4 KB 数据块区。
   - 文件写入（`ramfs_store`）直接将 4 KB 数据页同步写入 `darwin_var` 物理块；读取（`ramfs_fetch`）按需从物理块缺页读入；目录与属性修改由内核线程自动聚合提交到乒乓槽位，并在 `fsync()`、`sync()`、`unmount()` 与关机时立即落盘。
2. **原版未裁剪 iOS 26.6.2（`23G90`）三容器镜像 UFS 直挂**：
   - 在 [`userdata-dual-carve.py`](../../hackios-xnu-kernel/tools/userdata-dual-carve.py) 中将 `darwin` 分区默认大小设为 `16 GiB`；在 [`init_mount.inc`](../../hackios-xnu-userland/userland/src/boot/init_mount.inc) 与 [`init.c`](../../hackios-xnu-userland/userland/src/boot/init.c) 中支持按块偏移（`0`、`2382336`、`3666944`）直接从 `/dev/ufs_darwin` 挂载原版 `os.dmg`、`systemos.dmg` 与 `appos.dmg`（共 14.002 GiB），并通过 `bindfs` 将 `/annibale/lib/AnnibaleMetal.bundle` 叠加到 `/System/Library/Extensions/AnnibaleMetal.bundle`。
3. **文件系统属性与数据容器初始化**：
   - 在 [`ramfs.c`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs.c) 与 [`ramfs_getattr.inc`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_getattr.inc) 中补齐 `rn_dataprotect_class`、`va_addedtime`、`VOL_CAP_FMT_PERSISTENTOBJECTIDS`、`VOL_CAP_FMT_CLONE_MAPPING` 与 `VOL_CAP_INT_RENAME_SWAP`；在 [`apfs_vnops.c`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_vnops.c) 中返回 `PROTECTION_CLASS_D`，并移除 [`inject_posterboard.c`](../../hackios-xnu-userland/userland/src/inject/inject_posterboard.c) 的 `NSURL` 钩子。
   - 在 [`inject_app.c`](../../hackios-xnu-userland/userland/src/inject/inject_app.c) 中自动创建容器下的 `Documents`、`Library/Preferences`、`Library/Caches` 与 `tmp` 子目录。

### 1.8 主屏大尺寸小组件卡片黑底与 `nir_lower_fb_read` 图层索引修复

- **现象**：主屏天气与日历等大尺寸小组件卡片背景显示为不透明纯黑底板；下拉控制中心时背景随模糊下采样管线切换为白色毛玻璃，收起控制中心后恢复纯黑。
- **根因**：主屏大组件背景采用 `MTMaterialView` 与 `CABackdropLayer`，片元着色器通过 Framebuffer Fetch（`[[color(0)]]`）读取当前帧缓冲颜色。Mesa 的 `nir_lower_fb_read.c` 将其降级为 `nir_texop_txf_ms_fb` 并绑定第 3 分量为 `nir_load_layer_id(b)`，再由 `ir3_nir_lower_layer_id.c` 转为 `load_input(VARYING_SLOT_LAYER)`；CoreAnimation 的 2D 管线顶点着色器未输出 `VARYING_SLOT_LAYER`，片元着色器从未初始化的 VPC 寄存器读取非零图层索引，触发 Adreno A830 对单图层 2D 表面（`array_size = 1`）越界采样返回 `(0, 0, 0, 0)`。
- **修复**：在 [`hackios-xnu-userland/tools/mesa/rebase-26/0016-nir-lower-fb-read-zero-layer.patch`](../../hackios-xnu-userland/tools/mesa/rebase-26/0016-nir-lower-fb-read-zero-layer.patch) 与 [`air_to_nir.c`](../../hackios-xnu-userland/tools/mesa/air/air_to_nir.c) 中，对未包含 `VARYING_SLOT_LAYER` 的片元着色器直接将图层索引绑定为立即数常量 `0`。后续实测表明冷启动小组件黑底还涉及 `dest_0` pass-through 与 `TmuaBscnA2Xhfsn_IsrcN3Oc3mtc4nlnlnl_Isqr` 管线，进一步排查见[解锁转场密集采集](../progress/2026-11-08-widget-dense-transition.md)。

### 1.9 存储拓扑原生对齐与 `ramfs_clonefile` 实现

- **现象**：Safari 下载完成后调用 `fclonefileat()`／`copyfile(..., COPYFILE_CLONE)` 转存文件时返回 `ENOTSUP`（35）；系统存储设备树仅有单一 `disk0` 节点，缺少 iPhone 原生的 APFS 容器与角色卷树。
- **修复**：
  - 在 [`AnnibaleBT.cpp`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/AnnibaleBT.cpp) 中构建 `disk0 -> disk0s1 -> AppleAPFSContainer (disk1) -> AppleAPFSVolume (disk1s1, disk1s2, disk1s3)` 服务树，补齐角色掩码（System `0x1`、Data `0x40`、Preboot `0x10`）、卷名、UUID 与内容类型属性。
  - 在 [`annibale_disk_nodes.inc`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_disk_nodes.inc) 与 [`userland/src/boot/init.c`](../../hackios-xnu-userland/userland/src/boot/init.c) 中创建 `disk0`～`disk3s1` 及其字符设备 `rdisk*` 节点。
  - 在 [`ramfs_getattr.inc`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_getattr.inc) 中将 `f_fstypename` 设为 `"apfs"`、`f_mntfromname` 设为 `"/dev/disk1s2"` 并置位 `VOL_CAP_FMT_CLONE_MAPPING` 与 `VOL_CAP_INT_CLONE`；编写 [`ramfs_clonefile.inc`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_clonefile.inc) 并在 [`ramfs.c`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs.c) 注册 `vnop_clonefile_desc`。

### 1.10 内核 Panic 与看门狗崩溃日志硬件同步直写与开机自愈

- **现象**：内核触发 panic 或看门狗复位时，日志仅留在物理内存环形缓冲区；硬复位或断电后现场日志丢失。
- **修复**：在 [`ramfs_disk.inc`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_disk.inc) 中划定 `darwin_var` 的 `[64 MiB, 80 MiB)` 为 16 MiB 崩溃日志保留扇区 `ANNFS_PANIC_OFFSET`（魔数 `'KLOG'`，头部与载荷双 CRC32 校验）；在 [`loader_return.c`](../../hackios-xnu-kernel/xnu/files/osfmk/arm64/loader_return.c) 中实现 `loader_panic_sync_ufs()`，在硬件静默前将崩溃回溯与控制台上下文同步直写至 UFS；下次开机挂载时由 `ramfs_disk_restore_panic_log()` 还原至 `/private/var/db/panic.log` 并将头部标记为 `'DLOG'`。

### 1.11 隔空投送（AirDrop）与控制中心「屏幕镜像」主线程阻塞治理

- **现象**：点击隔空投送（AirDrop）图标导致整机卡死无响应；下拉控制中心点击「屏幕镜像」菜单时转圈阻塞 10 余秒。
- **根因**：SpringBoard 在主线程同步初始化 `SFAirDropDiscoveryController` 时调用 `SFOperationCreate` 等待无线 P2P 守护进程，因缺少 `awdl0` 网卡超时挂起主线程；控制中心在主线程调用 `MRUMirroringController` 的 `availableOutputDevices` 同步触发 `FigRouteDiscovererCopyProperty` 轮询耗时 10 秒。
- **修复**：在 [`inject_sb26_airdrop.inc`](../../hackios-xnu-userland/userland/src/inject/inject_sb26_airdrop.inc) 与 [`inject_sb26.c`](../../hackios-xnu-userland/userland/src/inject/inject_sb26.c) 中拦截 `SFAirDropDiscoveryController` 的 `-init` 方法，检测无 `awdl0` 时返回离线桩单例；拦截 `MRUMirroringController` 的 `availableOutputDevices`，主线程直接返回缓存列表，将路由探测移至后台 GCD 队列异步刷新。

### 1.12 主屏日历 App 动态图标透明与位图渲染恢复

- **现象**：主屏日历 App 动态图标透明，缺失日期数字与星期文本。
- **根因**：iOS 26 启用 Liquid Glass 时，`-[SBIconImageView shouldForceBitmapImages]` 返回 `NO`，图标走 `iconLayerWithInfo:` 对 `ISImage` 发送 `[image ICRIconLayer]` 返回 `nil`。
- **修复**：在 [`inject_sb26.c`](../../hackios-xnu-userland/userland/src/inject/inject_sb26.c) 与 [`inject_sb26_airdrop.inc`](../../hackios-xnu-userland/userland/src/inject/inject_sb26_airdrop.inc) 的 `software_bitmap_selection` 中检测图标类名包含 `Calendar` 时返回 `YES`，使其走 `iconImageWithInfo:` 位图渲染路径。

### 1.13 WebKit VP9 视频软解开关与字体服务（`com.apple.fontservicesd`）自启动

- **现象**：网页视频提示格式不支持；网页部分字符显示为方框问号 `<?>`。
- **修复**：在 [`inject_app.c`](../../hackios-xnu-userland/userland/src/inject/inject_app.c) 中为 WebKit／Safari 进程启用 `SWVPDecodersAlwaysEnabled`；在 [`userland/build.sh`](../../hackios-xnu-userland/userland/build.sh) 的 `IOS_JOBS` 中加入 `com.apple.fontservicesd` 并建立 `/var/db/fontconfig` 目录。

### 1.14 视频帧 NV12（`'420v'`）双平面 IOSurface 纹理绑定与 BT.601 转换管线

- **现象**：Safari 播放视频时报错拒绝导入格式 500（`MTLPixelFormatYCBCR8_420_2P`）纹理。
- **修复**：在 [`annibaledrawable.m`](../../hackios-xnu-kernel/tools/userland-driver/annibaledrawable.m) 与 [`annibalemetal_yuv.inc`](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_yuv.inc) 中拦截 `newTextureWithDescriptor:iosurface:plane:`，传入格式 500 且 `plane == 0` 时分别将平面 0 绑定为 R8、平面 1 绑定为 RG8，调用 BT.601 Compute Shader（`ycbcr_420v_to_rgb`）转换为 RGBA8 纹理。

### 1.15 AudioReach 空转与 Wi-Fi DMA 冲突、跨页拖动断触、音量滑块及关机看门狗喂狗

1. **AudioReach 空转与 WCN7850 Wi-Fi DMA 冲突**：
   - [`annibale_audio_reach.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_audio_reach.c) 的 `reach_feeder_thread` 在 DSP 未就绪时缺少休眠，导致单核 100% 空转并刷屏 `daudio:` 日志；同时将 64 KiB 音频 DMA 缓冲硬编码在 `lowdma` 起始地址 `0xc776f000`，覆盖了 [`mhi_pcie.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/mhi/mhi_pcie.c) 与 `ath12k` 的控制环，导致 WCN7850 报 `ctl_resp never came in (-60)`。
   - **修复**：为 `reach_feeder_thread` 增加 20 毫秒休眠并关闭刷屏日志，将 64 KiB 音频 DMA 缓冲移至 `lowdma` 顶部（`[0xcf66f000, 0xcf67f000)`）。
2. **跨页拖动桌面图标中途断触松开**：
   - 镜像此前默认打包了 `rc.jobs.desktop`，后台常驻 `anntouch` 注入滑动与抬起事件打断物理手指拖动；同时 [`annibale_goodix.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_goodix.c) 对单帧漏检立即上报 `ANNIBALE_TOUCH_UP`。
   - **修复**：[`package.py`](../../tools/k90auto/package.py) 切换为 `rc.jobs.interactive`；在 [`annibale_goodix.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_goodix.c) 中增加连续漏检消抖（`missed >= 2` 才上报抬起）；在 [`input26_service.c`](../../hackios-xnu-userland/userland/src/services/input26_service.c) 中将未处于按下状态的 `ANNIBALE_TOUCH_MOVE` 恢复为 `ANNIBALE_TOUCH_DOWN`。
3. **控制中心音量滑块与关机看门狗超时**：
   - 将 [`package.py`](../../tools/k90auto/package.py) 中 `AUDIO` 默认值改为 `"1"`，打包 `AnnibaleAudio.driver` 并放行 `audiomxd`。
   - 在 [`GenericARMPE.cpp`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/GenericARMPE.cpp) 与 [`loader_return.c`](../../hackios-xnu-kernel/xnu/files/osfmk/arm64/loader_return.c) 的关机与停核路径中主动执行 `hv_wdt_pet_NOW()`，在同步 `/private/var` 后立即跳回 `xnuloader`，消除关机黑屏 60 秒后触发 Hypervisor 看门狗红屏横幅的问题。

## 2. 11-06 至 11-07 多轮推进记录（R2～R8）

1. **蓝牙 3 Mbaud、手电与触感容错（R2，内核 `40377ec`、用户态 `a66051f`）**：
   - 在 [`annibale_bt_uart.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_bt_uart.c) 与 [`annibale_bt_ios.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_bt_ios.c) 中实现厂商命令 `0xFC48` 协商提速至 3 Mbaud 与 ISR 无锁并发。
   - 在 [`annibale_torch.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_torch.c) 中对 `0x0018` 寄存器传输丢弃增加重试；在 [`annibale_haptic.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_haptic.c) 中清除 `0x10` Boost UVLO 故障并配置 `0xf246` 升压寄存器。
   - 引入 Darwin 平台基于 UUID 路径的 ir3 磁盘缓存补丁（[`0015-ir3-disk-cache-darwin-uuid.patch`](../../hackios-xnu-userland/tools/mesa/rebase-26/0015-ir3-disk-cache-darwin-uuid.patch)）；后续实测开启后第二次开机解锁全黑，默认保持关闭，见[ir3 磁盘缓存跨开机实测](../analysis/2026-11-09-ir3-disk-cache.md)。
2. **SpringBoard 崩溃修复、多颜色附件清屏掩码与应用安装收敛（R3～R5）**：
   - **SpringBoard HFA 寄存器签名与 `CATransaction` 修复**：`SpringBoardHome` 在后台线程调用 `-[SBCalendarIconImageProvider iconLayerWithInfo:traitCollection:options:]` 时，`struct SBIconImageInfo`（4 个 `double`）作为 ARM64 同质浮点聚合体（HFA）通过 `d0..d3` 传参，而 [`inject_sb26_airdrop.inc`](../../hackios-xnu-userland/userland/src/inject/inject_sb26_airdrop.inc) 原先将其声明为 `void *` 占用 `x2` 导致参数错位，且在后台线程无事务调用 `[new_layer setContents:]` 触发 `CA_ASSERT_MAIN_THREAD_TRANSACTIONS` `abort()`。修正 HFA 结构体签名并包裹 `[CATransaction begin]`／`[CATransaction commit]` 后崩溃消除。
   - **Metal 与 AIR 8 颜色附件清屏掩码**：在 [`annibalemetal.m`](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal.m) 与 [`air_metal.c`](../../hackios-xnu-userland/tools/mesa/air/air_metal.c) 中遍历全部 8 个颜色附件，将每个附件的 `MTLLoadActionClear` 编码至 `draw->discard` 高 8 位并按位设置 `PIPE_CLEAR_COLOR0 << i` 与动态 `colormask`，修复 `iconservicesagent` 在 3 颜色附件模式下附件 1、2 未清屏导致的图标灰底问题。
   - **应用安装与卸载**：注册第三方应用时将 `IsDeletable` 设为 `@YES`，收敛后台 `watch` 仅监听暂存目录（消除开机轮询解压导致的 `ramfs` 膨胀），并预装 `TrollStore.app` 与 `trollstorehelper`。
   - **loader 切槽保护**：在 [`loader_06_usb_entry.inc`](../../hackios-xnu-kernel/xnuloader/loader_06_usb_entry.inc) 的 `oem android` 中校验 `kernel_resources_held`，内核未完全停止时拒绝切槽。
3. **外设驱动骨架、小米 MCA `pmic_glink` 充电对齐与按需自动解锁（R6～R7，内核 `39f0e46`、`b8a5926`，用户态 `9ff8901`、`732d49d`）**：
   - 新增 SM8750 CAMSS（[`annibale_camera.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_camera.c)）、LPASS ADSP（[`annibale_adsp.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_adsp.c)）、麦克风（[`annibale_mic.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_mic.c)）、环境光与接近传感器（[`annibale_sensors.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_sensors.c)）及 MPSS 基带（[`annibale_modem.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_modem.c)、[`annibale_qmi.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_qmi.c)）驱动代码。
   - 对照 Android 15 `qcom_subpmic.ko` 遥测，在 [`annibale_battery.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_battery.c) 中修正 `PMIC_RTR_ADSP_APPS`（owner `0x800a`）属性 ID：`0x2019`（`input_suspend = 0`）、`0x2003`（`chg_enable = 1`）、`0x2008`（`input_current_limit = 2500 mA`）、`0x2005`（`charge_current = 3000 mA`），并放开 `spmi_read_reg()` 只读观察窗读取与 `glink_q_write()` 队列余量等待。
   - 在 [`mkstandalone.py`](../../hackios-xnu-kernel/xnuloader/mkstandalone.py) 中默认设置 `touch_lat=0` 与 `gpu_log=0`，移除后台 `framewatch` 周期全线程栈转储；[`inject_sb26.c`](../../hackios-xnu-userland/userland/src/inject/inject_sb26.c) 改为仅在启动参数含 `autounlock=1` 时自动解锁，日常启动默认停留在锁屏界面。
4. **ABL `LoadImageAndAuthVB2` 回退根因、4K 扇区 `modem_a` 固件读取与注入库签名修复（R8，内核 `07f0efb9`、`fa20d390`）**：
   - **`boot_a` AVBf／AVB0 校验回退 Android**：反汇编 `LinuxLoader.efi` 的 `LoadImageAndAuthVB2`（`0x3a6d4`）与 `avb_vbmeta_image_verify`（`0x44744`）查明，`boot_a` 末尾 `0x05ffffc0` 的 `AVBf` 页脚指向 `vbmeta_offset = 0x022b9000`；该处 `"AVB0"` 头被早期 51.3 MiB 大镜像覆盖后返回码为 `2`（转成槽位校验返回码 `6` `ERROR_INVALID_METADATA`），不在解锁放行掩码 `0x39`（`{0, 3, 4, 5}`）内，导致 ABL 调用 `HandleActiveSlotUnbootable(0)` 将 `boot_a` 标为 `unbootable` 并切回 B 槽；同时无 AVB 属性时 ABL 检查 `boot.img` 偏移 `0x2c` 的 `os_version != 0`。在 [`reseal-loader-img.py`](../../hackios-xnu-kernel/tools/reseal-loader-img.py) 中传入 `--os_version 15.0.0 --os_patch_level 2026-02` 并恢复 `boot_a` 偏移 `0x022b9000` 的 `AVB0` 块后解决，详见[引导目标切换 SOP §4](device-boot-target-sop.md#4-陷阱均为实测)。
   - **4K 扇区 + VFAT LFN `modem_a` 固件读取与 TrustZone SMC 互斥**：修复 [`annibale_ufs_rw.inc`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_ufs_rw.inc) 的 `annibale_ufs_fat16_fw_read()` 支持 4096 字节逻辑扇区与 VFAT LFN 长文件名，从 `modem_a` 成功读取 `adsp_dtb.mdt` 与 `adsp.mdt`；在 [`adreno8.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/adreno8/adreno8.c) 导出 `adreno8_init_done`，令 `annibale_adsp_boot_thread()` 等待 Adreno 830 完成初始化后再发起 TrustZone PAS SMC 调用，消除并发 `SMC_EBUSY` 导致 GPU 退回软件渲染的问题。
   - **注入库签名与启动早期崩溃修复**：[`package.py`](../../tools/k90auto/package.py) 改为每次从源码编译并 ad-hoc 签名 `libannibale.dylib`、`libannibale-media.dylib` 与 `libannibale-app.dylib`；修复 [`inject_app.c`](../../hackios-xnu-userland/userland/src/inject/inject_app.c) 在 `Foundation` 初始化前调用 `NSUserDefaults` 导致的早期崩溃，并从 [`inject_cellular.inc`](../../hackios-xnu-userland/userland/src/inject/inject_cellular.inc) 移除因共享缓存 `__LINKEDIT` `fileoff` 无符号减法下溢触发 `SIGSEGV` 的 `rebind_image_symbols()`。
   - **相机 V57 格式匹配与硬件时钟对时**：在 [`camera_device.c`](../../hackios-xnu-userland/userland/src/services/camera_device.c) 与 [`camera_device_stream.inc`](../../hackios-xnu-userland/userland/src/services/camera_device_stream.inc) 中补齐 `SIFREnabled`、`FrontEndScalerOutputWidth` 与 `'x420'` 像素格式（`camera_avtest` 实测匹配后摄 30、前摄 24 种格式）；在 [`annibale_ufs_rw.inc`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_ufs_rw.inc) 的 `annibale_ufs_sync_rtc()` 中结合 PMK8550 硬件秒计数器与 Android `persist /time/ats_*` 偏移初始化系统时间。

## 3. 持续跟进与复核入口

- 历次反馈的逐项静态核对、真机实测状态与未完成项边界：[11-08 复核](../analysis/2026-11-08-issue-reassessment.md)。
- 架构审查、三档优先级与用户决定：[方案架构审查](../analysis/2026-11-08-architecture-review.md)。
- Android 系统内 OTA 对双系统分区的影响与恢复步骤：[双系统分区与持久化部署手册 §5](dual-boot-setup.md#5-android-系统内更新ota与槽位轮换)。
