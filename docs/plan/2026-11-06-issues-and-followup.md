# 2026-11-06 开机后实测问题与后续跟进清单

本文记录 2026-11-06 `boot_a` 独立双系统引导进入 iOS 26 桌面后，用户在真机交互中反馈的 5 项界面／功能问题的定位、修复与真机验证结果，以及上游优化借鉴、外设继续适配与 Android OTA 影响的跟进安排。总账入口见[总账跟踪](2026-10-23-tracking.md)。

## 1. 5 项实测问题的根因、修复与真机验证

### 1.1 控制中心与底部 Dock 图形渲染异常、控制中心亮度条不可见（已修复并验证）

- **现象**：
  - 控制中心左上 2×2 连接卡片、右上 2×2 媒体卡片、圆角按钮及主屏底部 Dock 栏外围出现不透明纯白／浅灰矩形方框。
  - 控制中心亮度胶囊外框可见，拖动滑块能改变面板背光，但胶囊内部白色填充条不显示。
- **根因**：
  1. **顶点着色器 CSO 缓存悬垂指针（Use-After-Free）**：[`hackios-xnu-userland/tools/mesa/air/air_metal_vertex_cache.inc`](../../hackios-xnu-userland/tools/mesa/air/air_metal_vertex_cache.inc) 的 `rwa_vertex_cso_cache_put()` 仅浅拷贝 `e->vinfo = *vinfo`，未深拷贝 `vinfo->varyings[i].name` 与 `vinfo->vertex_attributes[i]` 字符串；首个渲染管线编译完成后释放 `air_ctx`，后续命中同一顶点 CSO 缓存的管线在链接片元着色器时读取已释放的 varying 名称，导致 varying 槽位绑定错乱或管线编译失败。
  2. **管线失败回退为空白片元管线与单采样 Resolve Blit 退化**：[`hackios-xnu-kernel/tools/userland-driver/redwoodmetal.m`](../../hackios-xnu-kernel/tools/userland-driver/redwoodmetal.m) 在管线创建失败时调用 `rw_fallback_render_create()` 构造无片元着色器的回退管线，直接把失败图层画成不透明纯白矩形；同时将单采样 `MTLStoreActionMultisampleResolve` 改为 `endEncoding` 阶段 `rw_record_resolve_blits()`，破坏了单采样附件的原地混合。
  3. **`TbdsA2Xhf` 拼接函数选择器与 >64 位函数常量**：[`redwoodmetal_stitch.inc`](../../hackios-xnu-kernel/tools/userland-driver/redwoodmetal_stitch.inc) 的 `RedwoodMetalStitchedFunction` 在 `_cachedBitcode != nil` 时对 `redwoodUnspecializedFunction` 返回底函数 `_function`，导致驱动丢弃拼接后的快速路径字节码；[`air_to_nir.c`](../../hackios-xnu-userland/tools/mesa/air/air_to_nir.c) 的 `air_load_ptr()` 拒绝 `comps * bits > 64` 的向量函数常量（如 `float4`），导致控制中心亮度条与玻璃着色器编译报错。
  4. **SpringBoard 玻璃背景强制涂白钩子**：[`inject_sb26.c`](../../hackios-xnu-userland/userland/src/inject_sb26.c) 中的 `install_bar_background_hooks()` 与 `install_widget_hooks()` 将 `_UIBarBackground`、`_GlassGroupView` 背景层强制设为不透明白底 `rgba(1, 1, 1, 0.9)`。
- **修复**：
  - [`air_metal_vertex_cache.inc`](../../hackios-xnu-userland/tools/mesa/air/air_metal_vertex_cache.inc)：为每个缓存条目分配独立 `e->mem_ctx`，深拷贝 `varyings` 与 `vertex_attributes` 及其名称字符串，并在 `rwa_vertex_cso_cache_destroy()` 中释放。
  - [`redwoodmetal.m`](../../hackios-xnu-kernel/tools/userland-driver/redwoodmetal.m) 与 [`redwoodmetal_pipecache.inc`](../../hackios-xnu-kernel/tools/userland-driver/redwoodmetal_pipecache.inc)：移除 `rw_fallback_render_create()`，恢复单采样 `MTLStoreActionMultisampleResolve` 直接绑定 `_resolve[i]` 纹理。
  - [`redwoodmetal_stitch.inc`](../../hackios-xnu-kernel/tools/userland-driver/redwoodmetal_stitch.inc) 与 [`air_to_nir.c`](../../hackios-xnu-userland/tools/mesa/air/air_to_nir.c)：修正 `_cachedBitcode != nil` 时的选择器响应，并支持 `comps * bits > 64` 的函数常量高位补零加载。
  - [`inject_sb26.c`](../../hackios-xnu-userland/userland/src/inject_sb26.c)：移除 `install_bar_background_hooks()` 与 `install_widget_hooks()`。
- **真机验证**：开机进入主屏并下拉控制中心截图确认，主屏 Dock 与控制中心各模块恢复半透明圆角 Liquid Glass 背景，白底方框完全消失；控制中心亮度滑块内部白色填充条正常渲染。

### 1.2 设置页存储容量显示与 128 GB 容器口径对齐（已修复并落地）

- **现象**：早期「设置 → 通用 → 关于本机」中总容量显示为 `0 KB`、可用 `2.61 GB`；初次接入 `darwin_var` 分区块数后显示为总容量 `129 GB`、可用 `128.22 GB`（未扣除系统卷与 Cryptex 占用，且按二进制 120 GiB 换算成了十进制 129 GB）。
- **根因**：iOS 的 `storagekitd`／`Preferences` 通过 `IOKit` `IOMedia`（`disk0` 的 `Size` 属性）、`statfs()` 与 `getattrlistbulk`（`VOL_ATTR_CAPABILITIES`）按十进制字节（`1 GB = 10^9 B`）计算整机共享 APFS 容器的总容量与可用容量；真实 128 GB iPhone 17 的容器总容量为 `128,000,000,000` 字节（128 GB），可用容量为容器总容量减去 System 卷（9.76 GB）、OS Cryptex（5.26 GB）、App Cryptex（14.68 MB）、Preboot／Recovery（0.54 GB，小计 15.57 GB）以及 `/private/var` 实际已用数据块。
- **修复**：在 [`RedwoodBT.cpp`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/RedwoodBT.cpp) 与 [`redwood_ufs.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/redwood_ufs.c) 中将 `disk0` 容量设为 `128,000,000,000` 字节（128 GB）；在 [`ramfs_getattr.inc`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_getattr.inc) 与 [`apfs_vfsops.c`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_vfsops.c) 中统一由 `redwood_container_total_bytes()`（`128,000,000,000` 字节）与 `redwood_container_free_bytes()`（扣除 15.57 GB 系统与 Cryptex 占用及 `/private/var` 实际已用页）上报 `/` 与 `/private/var` 的 `statfs` 及 `vfs_getattr`，总容量显示为 `128 GB`，初始可用容量约 `112.4 GB` 并随文件写入实时递减。

### 1.3 设置页一级列表图标全部缺失（已修复并验证）

- **现象**：打开「设置」（`Preferences`）主列表时，各设置项左侧图标全部空白。
- **根因**：[`hackios-xnu-userland/tools/mesa/air/air_metal_texture.inc`](../../hackios-xnu-userland/tools/mesa/air/air_metal_texture.inc) 在 `263e886` 中将 `PIPE_FORMAT_A8_UNORM` 纹理的默认采样 swizzle 改写为 `(X, X, X, X)`，破坏了 Gallium `util_format_a8_unorm` 原生的 `(0, 0, 0, R)` 通道映射（着色器读取 `.a` 分量获取遮罩透明度，`.rgb` 应为 0），加之 §1.1 的顶点 CSO 缓存悬垂指针导致图标合成管线异常。
- **修复**：从 [`air_metal_texture.inc`](../../hackios-xnu-userland/tools/mesa/air/air_metal_texture.inc) 移除对 `PIPE_FORMAT_A8_UNORM` 的强制 `PIPE_SWIZZLE_X` 覆盖，配合 §1.1 的顶点 CSO 缓存深拷贝修复。
- **真机验证**：打开「设置」主列表与「通用」子列表截图确认，Apple 账户、飞行模式、Wi-Fi、蓝牙、电池、通用、辅助功能、待机显示、控制中心、墙纸、显示与亮度等全部设置项左侧彩色图标完整显示。

### 1.4 进入设置子页面时背光短暂变暗再恢复与低亮度滑块线性区间（已落地并刷入 `boot_a`，待真机复核）

- **现象**：首次打开「设置」或点击进入子页面转场时，屏幕亮度会自主跳变或短暂降低再恢复；09:05 真机实测反馈进入设置子页面亮度仍会先降再恢复，且控制中心滑块拉到中段以下时面板背光停在约 140 nits。
- **根因**：
  1. 09:05 真机仍运行着 05:34 启动的旧会话（运行时间 12640 秒），08:40 后台 `oem flash_boot` 写入 `boot_a` 未重启运行中的内核。
  2. 通过 [`dsc.py`](../../hackios-xnu-kernel/tools/dsc/dsc.py) 反汇编 iOS 26（23G90）`CoreBrightness` 框架并核对转场日志发现：`CoreBrightness` 在设置子页面转场自主斜坡（`140.0 ↔ 168.0 nits`）的每一帧（约 16 毫秒间隔）也会同时向 `AppleARMBacklight` 下发 `DisplayBrightness`（`{Brightness: ...}`）与 `brightness-nits`，并向 `IOMobileFramebuffer` 下发 `IOMFBBrightnessLevel`。
  3. [`MiniAppleARMBacklight.cpp`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniAppleARMBacklight.cpp) 在 `417bae9` 中把「连续收到 `DisplayBrightness`」也作为开启 `bl.user_until` 滑块窗口的条件，导致自主转场斜坡第 2 帧即误触发 `bl.user_until`，绕过了 25% 自主斜坡过滤；同时 `publish_calibration()` 将 `lMidPanel`／`lMidProduct` 设为 `kBLMilliNitsMid`（140 nits），导致 `CoreBrightness` 在 `DisplayBrightness < 49398` 时把 `brightness-nits` 夹紧在 `9175040`（140 nits）。
- **修复**：
  - 在 [`MiniAppleARMBacklight.cpp`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniAppleARMBacklight.cpp) 中，仅在收到 `DisplayBrightnessSliderPosition`（仅用户实际触摸拖动亮度滑块时由 `CoreBrightness` 发送）时开启 `bl.user_until`（500 毫秒）滑块活跃窗口，`DisplayBrightness` 仅在 `now <= bl.user_until` 时续期窗口。
  - 将 `publish_calibration()` 中的 `lMidPanel` 与 `lMidProduct` 下调为 `fixed_nits(kBLMilliNitsMin)`（5 nits），并在 `n16 == fixed_nits(kBLMilliNitsMid)` 且 `DisplayBrightness < 49398` 时按线性比例映射到 `5..140 nits`。

### 1.5 日历（MobileCal）重复弹出通知权限申请与系统通知 Bundle 根因修复（已落地并打包，待真机复核）

- **现象**：打开日历（`MobileCal`）弹出通知权限请求框，点击「允许」后关闭再重新打开日历，仍每次重复弹出同一权限申请。
- **根因**：
  1. 09:05 从真机取回 `/var/mobile/Library/UserNotifications/Library.plist` 与 `/var/mobile/Library/BulletinBoard/VersionedSectionInfo.plist` 对比发现：`Library.plist` 已登记 `com.apple.mobilecal -> 9258050C-94B0-48D0-BDDE-82BE8E85EA85` 且 `Categories.plist` 已落盘，但 `VersionedSectionInfo.plist` 仅含 `DocumentsApp`、`MobileSMS`、`tips` 三项，缺少 `com.apple.mobilecal` 的 `UNCSectionInfo` 记录。
  2. 通过 [`dsc.py`](../../hackios-xnu-kernel/tools/dsc/dsc.py) 反汇编 iOS 26（23G90）`UserNotificationsCore`（`+[UNCNotificationSourceDescription sourceDescriptionWithBundleIdentifier:]` `0x1de17a668`、`+[UNCNotificationSourceDescription systemSourceDescriptionWithBundleURL:]` `0x1de17aae0`、`-[UNCNotificationSourceDescription setSystemPropertiesFromDictionary:]` `0x1de17b0f4`）与 `UserNotificationsServer`（`-[UNSDefaultDataProviderFactory _queue_notificationSourcesDidInstall:]` `0x299595fd0`、`_queue_createDataProviderWithNotificationSourceDescription:withCompletion:` `0x29959624c`）查明：
     - `sourceDescriptionWithBundleIdentifier:@"com.apple.mobilecal"` 首先在 `/System/Library/UserNotifications/Bundles/` 下查找 `com.apple.mobilecal.bundle`。
     - 原先 [`ios165/select-system.py`](../../hackios-xnu-userland/ios165/select-system.py) 在 `SKIP_SYSTEM_LIBRARY` 中列有 `'UserNotifications'`，构建 `system26.apfs` 时把 `/System/Library/UserNotifications/Bundles/` 下的 100 余个系统通知 Bundle 全部裁掉。
     - 缺失 `com.apple.mobilecal.bundle` 后，`sourceDescriptionWithBundleIdentifier:` 回退调用 `applicationSourceDescriptionWithApplication:` 读取 `/Applications/MobileCal.app/Info.plist`；对于 `applicationType == "System"` 的系统应用，其 `UNUserNotificationCenter` 字典（含 `UNAutomaticallyShowSettings = true`、`UNDaemonShouldReceiveBackgroundResponses = true`、`UNDefaultSettings` 与 5 个日历通知话题 `UNDefaultTopics`）全部存放在 `/System/Library/UserNotifications/Bundles/com.apple.mobilecal.bundle/Info.plist` 中，主应用 `Info.plist` 不含该键，`setSystemPropertiesFromDictionary:` 因 `x19 == nil` 计算出 `useDefaultDataProvider = NO`。
     - 随后 `_queue_createDataProviderWithNotificationSourceDescription:withCompletion:`（`0x29959624c`）检查 `useDefaultDataProvider == NO`，打印错误 `"Do not register notification settings for an app that is using a custom data provider"` 并直接中止，未创建 `UNSDefaultDataProvider`，也未将 `UNCSectionInfo` 写入 `VersionedSectionInfo.plist`。
- **修复**：
  - 从 [`ios165/select-system.py`](../../hackios-xnu-userland/ios165/select-system.py) 的 `SKIP_SYSTEM_LIBRARY` 移除 `'UserNotifications'`，仅过滤 `System/Library/UserNotifications/` 下的 `.car` 与 `.caf` 资源，保留全部 647 个通知配置 plist／strings 文件（合计 4.8 MB）。
  - 在 [`userland/build.sh`](../../hackios-xnu-userland/userland/build.sh) 与 [`userland/src/init.c`](../../hackios-xnu-userland/userland/src/init.c) 中将 `System/Library/UserNotifications` 打入 `root.apfs`（`/redwood/UserNotifications`）并在开机时通过 `kern.apfs_synthetic` 与 `bindfs` 挂载到 `/System/Library/UserNotifications`，无需重刷 5.9 GB `system26.apfs` 即可在 `boot_a` 生效。
  - 从 [`userland/src/ax.m`](../../hackios-xnu-userland/userland/src/ax.m) 中彻底移除 `ax_enable_default_notification_provider()` 方法交换代码。

### 1.6 09:07 用户新反馈的 3 项真机问题与 LK `ValidateSlotGuids` 修复（已落地并打包，待真机复核）

1. **首次连接 Wi-Fi 报错「无法加入」随后自动连上，以及 `ath12k` 调试日志刷屏**：
   - **现象**：09:05:58 左右在「设置 → Wi-Fi」首次点击加入网络时弹窗报错「无法加入」，随后后台自动重试又成功连上。
   - **根因**：
     - 日志刷屏：[`hackios-xnu-kernel/wifi/lx/ath12k/lx_pci.c`](../../hackios-xnu-kernel/wifi/lx/ath12k/lx_pci.c) 默认开启 `ATH12K_DBG_HTC` 且 `__ath12k_dbg()` 未检查 `ath12k_debug_mask`，连上网后 30 秒内打印 14030 行 `htc rx completion ep 2 skb ...`，冲掉了 1 MB 内核日志环形缓冲区。
     - 首次连接握手竞态：[`lx_join.c`](../../hackios-xnu-kernel/wifi/lx/src/lx_join.c) 在收到关联应答（`0x10`）后尚未完成 `station_state(AUTH -> ASSOC)`（`WMI_PEER_ASSOC`）与 `bss_changed(BSS_CHANGED_ASSOC)`（`WMI_VDEV_UP`）时，接入点发来的四次握手第 1 条 EAPOL 消息已在 `wifi-rings` 线程触发 `handshake_message()` 回复第 2 条消息；此时驱动 peer 关联状态尚未就绪，导致第 2 条握手帧被丢弃或超时。
   - **修复**：在 [`lx_pci.c`](../../hackios-xnu-kernel/wifi/lx/ath12k/lx_pci.c) 的 `__ath12k_dbg()` 中增加 `if (!(ath12k_debug_mask & mask)) return;` 并从默认掩码移除 `ATH12K_DBG_HTC`；在 [`lx_80211.h`](../../hackios-xnu-kernel/wifi/lx/src/lx_80211.h)、[`lx_80211.c`](../../hackios-xnu-kernel/wifi/lx/src/lx_80211.c) 与 [`lx_join.c`](../../hackios-xnu-kernel/wifi/lx/src/lx_join.c) 中缓存 `reached < IEEE80211_STA_ASSOC` 阶段收到的 EAPOL 帧，待 `bss_changed(BSS_CHANGED_ASSOC)` 完成后立即重放，并在首次握手未收到 EAPOL 帧返回 `EAUTH` 时在 `boundary_join()` 内自动重试一次。
2. **插着 USB 线无法充电／状态栏不显示充电且电量下降**：
   - **现象**：手机插着电脑 USB 线运行 iOS 26 时，状态栏不显示闪电图标，电量在 3.5 小时内从 84%（4273 mV）降至 75%（4148 mV，电流 `-175`～`-1281 mA`）。
   - **根因**：[`annibale_battery.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale_battery.c) 原先仅从 BQ27Z561 电量计读取净电流 `current_ua`（将 `< -250 mA` 判定为拔出充电器），未检测 USB 控制器物理连接状态；电脑 USB 端口供电功率低于亮屏运行功耗时即被判为未接电源。
   - **修复**：在 [`annibale_battery.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale_battery.c) 中增加 DWC3 设备寄存器（`0x0a60c000`：`DCTL +0x704` bit 31 `RUN_STOP` 与 `DSTS +0x70c` bit 22 `DEVCTRLHLT` 及 `USBLNKSTS < 4`）在线检测，结合电池电流（`>= -150 mA`）上报 `external = 1, status = 1` 与电源适配器信息。
3. **系统内滑动关机后画面卡死在最后一帧**：
   - **现象**：09:07 在 iOS 系统内触发关机并滑动确认后，屏幕一直卡在关机转圈画面无法熄屏关机。
   - **根因**：iOS 关机进入 `halt_all_cpus(FALSE)` 调用 `loader_return()` 退回 RAM 中的 `xnuloader`，而 `MiniIOMobileFramebufferQuiesce()` 将最后一帧拷回主帧缓冲并把混合器亮度恢复为 `DIM_ALPHA_FULL`（100%），面板背光保持常亮。
   - **修复**：在 [`MiniFramebufferDim.inc`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferDim.inc) 与 [`MiniFramebufferFlip.inc`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferFlip.inc) 新增 `dim_poweroff()` 与 `MiniIOMobileFramebufferPowerOff()` 清零双帧缓冲并关闭 OLED 背光；在 `machine_routines.c`（[`52-osfmk%arm64%machine_routines.c.patch`](../../hackios-xnu-kernel/xnu/patches/52-osfmk%arm64%machine_routines.c.patch) 与 [`42-osfmk%arm64%machine_routines.c.patch`](../../hackios-xnu-kernel/xnu26/patches/42-osfmk%arm64%machine_routines.c.patch)）的 `halt_all_cpus()` 中依次执行 `redwood_var_save_on_return()`、外设停机与 `MiniIOMobileFramebufferPowerOff()`；在 [`redwood_threads.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/redwood_threads.c) 增加 `kern.redwood.halt` sysctl，并在 [`inject_sb26.c`](../../hackios-xnu-userland/userland/src/inject_sb26.c) 拦截 `SBPowerDownViewController`／`SBRestartManager`／`FBSystemService` 关机选择器执行 `sync()` 与 `kern.redwood.halt=1`。
4. **09:10 故障回退切槽引发的 LK `ValidateSlotGuids` 报错（`Failed to load/authenticate boot image: Device Error`）**：
   - **根因**：使用 `idalib-mcp` 反编译 `abl_a.img` 中的 `LinuxLoader.efi` 查明，`FindBootableSlot`（`sub_1D1B8`）内的 `ValidateSlotGuids` 比较 `boot_<slot>` 与 `abl_<slot>` 的 16 字节 `PartitionTypeGUID`（偏移 `+0`）：高通 A/B GPT 中活动槽位各分区具有独立的 `PartitionTypeGUID`（`boot` 为 `20117f86-...`，`abl` 为 `bd6928a1-...`），非活动槽位所有分区共用 `77036cd4-03d5-42bb-8ed1-37e5a88baa34`；若两者 `PartitionTypeGUID` 相同（`CompareMem == 0`），`FindBootableSlot` 打印 `"ValidateSlotGuids: BootableSlot %s does not have valid guids"` 并返回 `EFI_DEVICE_ERROR`。09:10:01 `xnuloader` 的 `slot_set_active_other()` 仅改写了 `boot_a`／`boot_b` 的属性（`+48`）而未交换 `_a`／`_b` 分区的 `PartitionTypeGUID`，导致随后执行 `fastboot set_active a` 时 `LinuxLoader.efi` 的 `SetActiveSlot`（`sub_1C21C`）把 `_a` 与 `_b` 的 `PartitionTypeGUID` 反向对调（`boot_a` 带有 `Active = 1` 但 `PartitionTypeGUID` 变成非活动的 `77036cd4-...`）。
   - **修复**：在 [`loader_06a_screen_ui.inc`](../../hackios-xnu-kernel/xnuloader/loader_06a_screen_ui.inc) 中新增 `gpt_swap_ab_type_guids()` 与 `slot_apply_active()`，在维护当前槽位或切换到另一槽位时检查目标槽位 `memcmp(boot_target, abl_target, 16) == 0`，若目标槽位持有非活动 `PartitionTypeGUID` 则同步交换 LUN 4 与 LUN 0 上全部 `_a`／`_b` 分区的 16 字节 `PartitionTypeGUID` 并重算主备 GPT CRC32；同时由 `sde-head.bin`／`sde-tail.bin` 生成 45056 字节的 `gpt_both4_slotb.bin` 与 `gpt_both4_slota.bin`，在 LK Fastboot 下执行 `fastboot flash partition:4 gpt_both4_slotb.bin && fastboot set_active a` 即可恢复 GPT 相位。

### 1.7 `/private/var` 内核直写块持久化（`RDWFS001`）、原版未裁剪 iOS 26 镜像直挂与全仓库根因排查（已落地并打包，待真机复核）

1. **`/private/var` 内核直写 UFS 块持久化（`RDWFS001`）**：
   - **磁盘布局与直写机制**：在 [`ramfs_disk.inc`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_disk.inc)、[`ramfs_fsctl.inc`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_fsctl.inc) 与 [`redwood_ufs_rw.inc`](../../hackios-xnu-kernel/xnu/files/bsd/dev/redwood_ufs_rw.inc) 中为 `/private/var` 实现直接绑定 UFS `darwin_var` 分区（或 `dsu_store`）的内核块级持久化文件系统（魔数 `"RDWFS001"`）：
     - `[0, 32 MiB)` 与 `[32 MiB, 64 MiB)` 为双乒乓元数据槽位（保存全部 inode、目录树、符号链接、扩展属性 xattr 与每个文件的 4 KB 物理块号表，带独立头部与负载 CRC32 校验），`[64 MiB, ...)` 为 4 KB 数据块区（由内核块分配位图管理）。
     - 文件写入（`ramfs_store`）直接将 4 KB 数据页同步写入 `darwin_var` 对应物理块；文件读取（`ramfs_fetch`）按需从 `darwin_var` 物理块缺页读入。
     - 任何目录／文件创建、重命名、截断、删除或属性修改在 20 毫秒聚合窗口内由内核 `thread_call` 自动将元数据提交到乒乓槽位，并在 `fsync()`、`fcntl(F_FULLFSYNC)`、`fcntl(F_BARRIERFSYNC)`、`sync()`、`unmount()` 与关机 `redwood_var_save_on_return()` 时立即同步落盘。
     - 下次开机挂载 `/private/var` 时，内核 `ramfs_disk_mount()` 直接从最新有效槽位恢复完整目录树与块映射并通过 `kern.redwood.var_disk_loaded=1` 通知 `init` 跳过初始种子解包。
2. **苹果原版未裁剪 iOS 26.6.2（`23G90`）三容器镜像 UFS 直挂**：
   - 苹果原版 iOS 26.6.2 IPSW 包含 3 个只读 APFS 容器镜像：`os.dmg`（`9,758,048,256` B，`2,382,336` 块）、`systemos.dmg`（`5,261,754,368` B，`1,284,608` 块）与 `appos.dmg`（`14,680,064` B，`3,584` 块），合计 `15,034,482,688` B（`14.002 GiB`）。
   - 在 [`userdata-dual-carve.py`](../../hackios-xnu-kernel/tools/userdata-dual-carve.py) 中将 `darwin` 分区默认大小调整为 `16 GiB`、`darwin_var` 调整为 `104 GiB`；在 [`init_mount.inc`](../../hackios-xnu-userland/userland/src/init_mount.inc) 与 [`init.c`](../../hackios-xnu-userland/userland/src/init.c) 的 `flash_root()`／`mount_cryptex()` 中支持按块偏移（`0`、`2382336`、`3666944`）直接从 `/dev/ufs_darwin` 挂载原版 `os.dmg`、`systemos.dmg` 与 `appos.dmg`，并通过 `bindfs` 将 `/redwood/lib/RedwoodMetal.bundle` 叠加到 `/System/Library/Extensions/RedwoodMetal.bundle`，保留原版系统的全部通知 Bundle、全部字体、本地化文案与 47 个预装系统应用。
3. **全仓库表象绕过项排查与根因替换**：
   - **文件系统数据保护类（`va_dataprotect_class`）、克隆（`VOL_CAP_FMT_CLONE_MAPPING`）与创建时间（`va_addedtime`）原生支持**：在 [`ramfs.c`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs.c) 与 [`ramfs_getattr.inc`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_getattr.inc) 中补齐 `rn_dataprotect_class`、`va_addedtime`、`VOL_CAP_FMT_PERSISTENTOBJECTIDS`、`VOL_CAP_FMT_CLONE_MAPPING` 与 `VOL_CAP_INT_RENAME_SWAP`，在 [`apfs_vnops.c`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_vnops.c) 中返回 `PROTECTION_CLASS_D`，并移除 [`inject_posterboard.c`](../../hackios-xnu-userland/userland/src/inject_posterboard.c) 的 `NSURL` 钩子。
   - **系统应用数据容器统一制备**：在 [`tools/k90auto/package.py`](../../tools/k90auto/package.py) 的 `INJECT` 列表中将 `MobileCal` 加入 `libredwood-app.dylib`，在 [`inject_app.c`](../../hackios-xnu-userland/userland/src/inject_app.c) 中自动创建容器下的 `Documents`、`Library/Preferences`、`Library/Caches` 与 `tmp` 子目录，并移除 [`ax.m`](../../hackios-xnu-userland/userland/src/ax.m) 中针对 `MobileCal` 的环境变量分支。

### 1.8 主屏大尺寸小组件卡片黑底与控制中心下拉白底切换（已落地并重编 AIR 库，待真机复核）

- **现象**：主屏天气与日历等大尺寸小组件卡片背景显示为不透明纯黑底板；下拉控制中心时背景随高斯模糊金字塔下采样管线切换为正常白色毛玻璃，收起控制中心后卡片背景立刻恢复纯黑。
- **根因**：
  1. 主屏天气与日历大尺寸卡片背景采用 `MTMaterialView` 与 `CABackdropLayer`，材质片元着色器通过片元阶段读取当前帧缓冲颜色（Metal 语法 `[[color(0)]]`，即 Framebuffer Fetch）并在着色器内部混合。
  2. `air_to_nir.c` 将 `air.render_target` 转换为 `nir_load_output` 内联原语（标记 `io_semantics.fb_fetch_output = true`）；随后 Mesa 的 `nir_lower_fb_read.c` 将 `load_output` 降级为纹理读取指令 `nir_texop_txf_ms_fb`，并绑定三维纹理坐标第 3 分量为 `layer = nir_load_layer_id(b)`。
  3. `ir3_nir_lower_layer_id.c` 将 `nir_load_layer_id` 转换为 `load_input(VARYING_SLOT_LAYER)` 插值读取；CoreAnimation 的 2D 矩形绘制管线顶点着色器未输出 `VARYING_SLOT_LAYER`，`ir3_link_shaders` 匹配失败，硬件顶点参数缓存（VPC）未写入对应槽位。
  4. 片元着色器执行 `isamm` 指令从未初始化的 VPC 寄存器 `r1.z` 读取图层编号，读得非零残留数值（`layer >= 1`）；高通 Adreno A830 硬件纹理单元对单图层 2D 表面（`array_size = 1`）执行数组边界断言，图层索引超出范围时硬件返回全零颜色 `(0, 0, 0, 0)`，材质着色器基于全零底色计算混色输出 `rgb(0,0,0)` 与 `alpha(1)`，卡片背景呈现纯黑。
  5. 下拉控制中心时全屏四边形下采样模糊绘制重置了 VPC 寄存器（`r1.z == 0`）或直接采样 2D 模糊纹理，底层像素采样成功，显示为正常浅色底板；收起控制中心恢复 2D 直接合成，VPC 脏寄存器再次引入越界采样，卡片背景变回纯黑。
- **修复**：
  - 在 [`hackios-xnu-userland/tools/mesa/rebase-26/0016-nir-lower-fb-read-zero-layer.patch`](../../hackios-xnu-userland/tools/mesa/rebase-26/0016-nir-lower-fb-read-zero-layer.patch) 与 `nir_lower_fb_read.c` 中，检查片元着色器是否包含 `VARYING_SLOT_LAYER`（`b->shader->info.inputs_read & BITFIELD64_BIT(VARYING_SLOT_LAYER)`）；未包含时直接将图层绑定为立即数常量 0（`nir_imm_int(b, 0)`），阻断 `nir_load_layer_id` 及未链接 `load_input(VARYING_SLOT_LAYER)` 的生成，确保 `txf_ms_fb` 采样坐标第 3 分量为立即数 0。
  - 在 [`hackios-xnu-userland/tools/mesa/air/air_to_nir.c`](../../hackios-xnu-userland/tools/mesa/air/air_to_nir.c)（与内核构建树 `.userland.git` 下的同名文件双向同步）中保持 3461 行零净增长，明确 2D 单图层目标帧缓冲读取的常量图层 0 语义与状态清理。
  - 运行 `python3 tools/k90auto/build-air.py` 完成 `libredwoodair.dylib` 编译与签名。

### 1.9 存储拓扑原生对齐与 ramfs_clonefile 深度拷贝实现（已落地并完成编译验证，待真机复核）

- **现象**：Safari 在完成文件下载后无法将文件移入「我的 iPhone」目录，下载进度停留在完成阶段且无法转存；系统中存储设备树仅有单一 `disk0` 节点，缺少 iPhone 原生的 APFS 容器与角色卷树。
- **根因**：
  1. 原生 iPhone 存储架构由物理磁盘 `disk0`、APFS 分区 `disk0s1`、合成容器 `disk1`（`AppleAPFSContainer`）及各角色卷（`disk1s1` System 卷、`disk1s2` Data 卷、`disk1s3` Preboot 卷）组成。原实现仅注册单个 `IOMedia` 节点且未发布 `AppleAPFSContainer` 与 `AppleAPFSVolume` 服务树，缺少 `APFSRole`、`Roles` 与 `VolumeUUID` 属性。
  2. 内核 `devfs` 缺少 `disk0`、`disk0s1`、`disk1`、`disk1s1`、`disk1s2`、`disk1s3` 及其字符设备 `rdisk*` 节点。
  3. `ramfs` 未注册 `vnop_clonefile` 接口。Safari 下载完成时调用 `copyfile(..., COPYFILE_CLONE)` 或 `fclonefileat()` 执行原子转存，系统调用因接口缺失返回 `ENOTSUP`（35），导致转存失败。
- **修复**：
  - 在 [`RedwoodBT.cpp`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/RedwoodBT.cpp) 中构建 `disk0 -> disk0s1 -> AppleAPFSContainer (disk1) -> AppleAPFSVolume (disk1s1, disk1s2, disk1s3)` 标准服务树，补齐角色掩码（System 为 `0x1`，Data 为 `0x40`，Preboot 为 `0x10`）、卷名、UUID 与内容类型属性。
  - 在 [`redwood_disk_nodes.inc`](../../hackios-xnu-kernel/xnu/files/bsd/dev/redwood_disk_nodes.inc) 中批量创建 `disk0`、`disk0s1`、`disk1`、`disk1s1`、`disk1s2`、`disk1s3`、`disk2`、`disk2s1`、`disk3`、`disk3s1` 及其字符设备；在 [`userland/src/init.c`](../../hackios-xnu-userland/userland/src/init.c) 中增加 `setup_disk_dev_nodes()` 双重确认。
  - 在 [`ramfs_getattr.inc`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_getattr.inc) 中将 `f_fstypename` 设置为 `"apfs"`，`f_mntfromname` 设为 `"/dev/disk1s2"`，卷名返回 `"Data"` 并置位 `VOL_CAP_FMT_CLONE_MAPPING` 与 `VOL_CAP_INT_CLONE`；在 [`apfs_vfsops.c`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/apfs_vfsops.c) 中将根卷设为 `"/dev/disk1s1"`，Cryptex 卷设为 `"/dev/disk2s1"` 与 `"/dev/disk3s1"`。
  - 编写 [`ramfs_clonefile.inc`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_clonefile.inc)，实现常规文件（深拷贝数据页块映射表、物理块分配与扩展属性）、符号链接及目录树递归深拷贝，并在 [`ramfs.c`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs.c) 注册 `vnop_clonefile_desc`，使用户态 `clonefile()` 与 `copyfile(..., COPYFILE_CLONE)` 返回成功。

### 1.10 内核 Panic 与看门狗崩溃日志硬件同步直写与开机自愈（已落地并完成编译验证，待真机复核）

- **现象**：内核在触发 panic 或看门狗复位时，日志仅留存在物理内存环形缓冲区；系统发生硬复位或断电后现场日志丢失，重启后无法获取崩溃调用栈与错误根因。
- **根因**：
  1. [`loader_return.c`](../../hackios-xnu-kernel/xnu/files/osfmk/arm64/loader_return.c) 中的 `loader_panic_log()` 仅将日志写入内存数组；`loader_return()` 在提取日志前先执行了 `redwood_ufs_quiesce()` 释放存储控制器，导致后续无法再写入磁盘；定时器退出与看门狗喂狗路径在内核发生错误时未触发存储同步。
  2. `darwin_var` 分区在元数据槽（0 至 64 MiB）与数据块区（512 MiB 起始）之间存在 448 MiB 连续未分配物理扇区，缺少专用的崩溃日志同步保留区与自愈恢复机制。
- **修复**：
  - 在 [`ramfs_disk.inc`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_disk.inc) 中划定 16 MiB 保留扇区 `RDWFS_PANIC_OFFSET`（[64 MiB, 80 MiB)），定义 `struct klog_head` 双 CRC32（头部与载荷独立校验）强完整性数据结构，魔数采用 `'KLOG'`（`0x474f4c4b`）。
  - 在 [`loader_return.c`](../../hackios-xnu-kernel/xnu/files/osfmk/arm64/loader_return.c) 中实现 `loader_panic_sync_ufs()`，打通 `loader_panic_log()`、`loader_return()`（调整时序在硬件静默前执行落盘）、`hv_wdt_pet()` 看门狗喂狗检测与定时器退出的硬件同步直写链路，调用 `redwood_ufs_var_io()` 将崩溃回溯与控制台上下文同步直写至 UFS。
  - 在 `ramfs_disk.inc` 挂载流程中增加 `ramfs_disk_restore_panic_log()`，开机检测有效头部并校验双 CRC32 后，自动在 `/private/var/db/panic.log` 创建节点并还原崩溃日志，随后将 UFS 头部标记为归档魔数 `'DLOG'`（`0x474f4c44`）并重写校验和，防止开机重复还原。

### 1.11 隔空投送（AirDrop）与控制中心「屏幕镜像」主线程阻塞异步治理（已落地并打包，待真机复核）

- **现象**：点击隔空投送（AirDrop）图标导致整机卡死无响应；下拉控制中心点击「屏幕镜像」菜单时转圈阻塞 10 余秒，期间主线程冻结且无法操作界面。
- **根因**：
  1. AirDrop 互斥锁挂起：SpringBoard 在主线程同步初始化 `SFAirDropDiscoveryController` 时调用 `SFOperationCreate`，尝试与无线 P2P 守护进程建立通信并持有互斥锁；因 K90 平台缺少 `awdl0` 网卡导致底层通信超时并挂起 SpringBoard 主线程。
  2. 屏幕镜像同步轮询阻塞：控制中心在主线程调用 `MRUMirroringController` 的 `availableOutputDevices`，同步触发 `FigRouteDiscovererCopyProperty` 轮询网络投屏终端，耗时达 10 秒并阻塞主线程。
- **修复**：
  - 在 [`inject_sb26_airdrop.inc`](../../hackios-xnu-userland/userland/src/inject_sb26_airdrop.inc) 与 [`inject_sb26.c`](../../hackios-xnu-userland/userland/src/inject_sb26.c) 中拦截 `SFAirDropDiscoveryController` 的 `-init` 方法，使用 `if_nametoindex("awdl0") == 0` 检测网卡，网卡缺失时返回离线单例，阻止主线程调用 `SFOperationCreate`；在 `MobileGestalt` 拦截中针对 `airdrop` 与 `airdrop-p2p` 返回 `kCFBooleanFalse`，使界面保持安全离线状态。
  - 拦截 `MRUMirroringController` 的 `availableOutputDevices`，主线程调用直接返回已缓存设备列表或空列表，消除 10 秒主线程同步等待；将网络路由探测移至后台 GCD 队列 `com.redwood.mru.discovery`，监听系统路由变化通知异步刷新缓存。

### 1.12 主屏日历 App 动态图标透明与位图渲染恢复（已落地并打包，待真机复核）

- **现象**：主屏日历 App 动态图标完全透明，仅显示下层壁纸，缺失日期数字与星期文本。
- **根因**：iOS 26 启用 Liquid Glass 特性时，`-[appearance hasGlass]` 返回 `YES`，导致 `-[SBIconImageView shouldForceBitmapImages]` 返回 `NO`；图标渲染转入 `iconLayerWithInfo:` 路径，该方法对 `ISImage` 发送 `[image ICRIconLayer]`，因未实现该方法返回 `nil`，导致图层内容为空并呈现透明。
- **修复**：在 [`inject_sb26.c`](../../hackios-xnu-userland/userland/src/inject_sb26.c) 与 [`inject_sb26_airdrop.inc`](../../hackios-xnu-userland/userland/src/inject_sb26_airdrop.inc) 的 `software_bitmap_selection` 中检测图标类名，包含 `Calendar` 时强制返回 `YES`，使日历图标走通成熟的 `iconImageWithInfo:` 位图渲染路径；并在 `SBCalendarIconImageProvider` 的 `iconLayerWithInfo:` 增加回退保护，当图层为空时从位图提取 `CGImage` 构造图层。

### 1.13 WebKit VP9 视频软解支持与字体服务（com.apple.fontservicesd）自启动（已落地并打包，待真机复核）

- **现象**：YouTube 等现代网页视频黑屏或提示格式不支持；YouTube 首页部分字符显示为方框问号 `<?>`。
- **根因**：
  1. 现代网页视频广泛采用 VP9 编码，WebKit 在缺少硬件解码器时默认关闭 VP9 支持并拒绝播放视频流。
  2. 网页文字排版依赖 `com.apple.fontservicesd` 进行字体动态加载与索引；此前 `IOS_JOBS` 守护进程列表缺失该服务且 `/var/db/fontconfig` 目录不存在，导致 WebKit 出现字体加载失败与沙盒写入报错。
- **修复**：
  - 在 [`inject_app.c`](../../hackios-xnu-userland/userland/src/inject_app.c) 中挂钩 `-[WKPreferences init]`，激活 `SWVPDecodersAlwaysEnabled` 特性，挂载 WebRTC 内置的 VP9 软件解码入口，写入 `NSUserDefaults` 偏好启用 WebKit 原生 VP9 软解支持。
  - 在 [`userland/build.sh`](../../hackios-xnu-userland/userland/build.sh) 的 `IOS_JOBS` 守护进程列表中加入 `com.apple.fontservicesd`，并在文件系统打包时建立 `/var/db/fontconfig` 目录与 0755 权限。

### 1.14 视频帧 NV12（'420v'）双平面 IOSurface 纹理绑定与 BT.601 转换管线（已落地并打包，待真机复核）

- **现象**：Safari 播放视频时报错拒绝导入纹理，系统日志提示 `MTLPixelFormatYCBCR8_420_2P`（格式 500）单平面导入接口非法。
- **根因**：AVFoundation 解码输出的视频帧普遍采用 NV12（`'420v'`）双平面 `IOSurface`（平面 0 为 R8 亮度分量，平面 1 为 RG8 色度分量）；CoreAnimation 在调用 Metal 驱动 `newTextureWithDescriptor:iosurface:plane:` 时传入格式 500，驱动单平面导入接口判定格式非法并拒绝。
- **修复**：在 [`redwooddrawable.m`](../../hackios-xnu-userland/userland/src/redwooddrawable.m) 与 [`redwooddrawable_420v.inc`](../../hackios-xnu-userland/userland/src/redwooddrawable_420v.inc) 中拦截 `newTextureWithDescriptor:iosurface:plane:`，当传入格式为 500 且 `plane == 0` 时，分别将平面 0 绑定为 R8 纹理，平面 1 绑定为 RG8 纹理；调用 BT.601 Compute Shader 转换管线（`ycbcr_420v_to_rgb`）将 YCbCr 像素转换为 RGBA8 纹理后返回上层渲染树合成。

### 1.15 21:08～21:32 真机实测 8 项问题定位与跟进（Wi-Fi 冲突、静置发热与显示架构、跨页拖动断触、音量滑块、亮度跳变、小组件跷跷板与动态图标切页、关机看门狗横幅、桌面图标位置跨开机保留）

1. **Wi-Fi 无法打开与桌面静置发烫／卡顿**：
   - **现象**：21:02 启动版本（`m6_boot_success.log`）进入桌面后 Wi-Fi 无法开启，即使静置在桌面不操作机身也明显发烫（电池温度从 `35.15 °C` 升至 `43.15 °C`，插着 USB 供电时电池电流仍为 `-452 mA`）。
   - **根因**：
     - [`annibale_audio_reach.c`](../../hackios-xnu-kernel/xnu/files/osfmk/arm64/annibale_audio_reach.c) 的 `reach_feeder_thread` 在 `reach_sent_count == reach_done_count` 且 DSP 未就绪时缺少休眠，导致 1 颗 Oryon 大核以 `4.32 GHz` 在内核态 100% 空转，每秒执行约 670 万次 IPCC 写入与 2.7 万行 `daudio:` 日志打印。
     - `annibale_audio_reach.c` 将 64 KiB DMA 环形缓冲区硬编码在 `lowdma` 起始地址 `0xc776f000`，直接覆盖了 [`mhi_pcie.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/mhi_pcie.c) 与 `ath12k` 在 `lowdma` 头部建立的 MHI／CE／HTC 控制环，导致 WCN7850 在 63.2 秒报 `ctl_resp never came in (-60)` 与 `failed to connect to HTC: -60`，`en0` 接口未能创建。
     - 主屏时钟图标（`SBClockApplicationIconImageView`）秒针以 `10 Hz`（每 `100 ms`）更新，在 [`package.py`](../../tools/k90auto/package.py) 默认开启 `CA_DISABLE_DIRTY_REGIONS=1` 的条件下，每次秒针微动都触发 `backboardd` 全屏 `1206×2622` 重绘（5 个 CommandBuffer、256 次 Draw Call）；随后 [`MiniFramebufferRows.inc`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferRows.inc) 在每次 `SwapEnd` 时由 3 个 `fb_threads` 线程在 CPU 上逐行计算哈希并执行 `1206×2622 -> 1156×2510` 双线性插值缩放（每帧 CPU 耗时 `1.75 ms`），叠加 `cpufreq=1`、`adreno8_keep=1`、`adreno8_speed=14` 固定最高频，造成静置高功耗。
   - **修复与优化**：
     - 在 [`annibale_audio_reach.c`](../../hackios-xnu-kernel/xnu/files/osfmk/arm64/annibale_audio_reach.c) 中为 `reach_feeder_thread` 增加 20 毫秒休眠并关闭刷屏日志，将 64 KiB 音频 DMA 缓冲区移至 `lowdma` 顶部（`lowdma_base + lowdma_size - 64 KiB`），解除对 WCN7850 Wi-Fi DMA 内存的覆盖，确保开机 `pcie_power=1 pcie=10` 默认启用 Wi-Fi。
     - 推进显示链路消除 CPU 缩放中转（对齐 `1156×2510` 物理扫描输出或启用 DPU 12.0 SSPP 硬件缩放）及局部脏矩形重绘（修复 Freedreno 局部更新附件保留以去掉 `CA_DISABLE_DIRTY_REGIONS=1`）。
2. **跨页拖动桌面图标中途断触松开**：
   - **现象**：将应用图标从第二屏拖向第一屏的过程中反复断触，图标中途自行松开。
   - **根因**：
     - 该轮镜像默认打包了 `rc.jobs.desktop`，后台常驻 `/redwood/bin/rwtouch` 每隔数秒向触摸管道注入 `finger=0` 滑动与 `REDWOOD_TOUCH_UP(finger=0)`，直接打断用户物理手指（同为 `finger=0`）的长按拖动，且 [`input26_service.c`](../../hackios-xnu-userland/userland/files/root/bin/input26_service.c) 第 295 行在 `touching == false` 后丢弃后续全部 `REDWOOD_TOUCH_MOVE`。
     - [`redwood_goodix.c`](../../hackios-xnu-kernel/xnu/files/osfmk/arm64/redwood_goodix.c) 的 `goodix_thread` 在 `touching == true` 时每 4 毫秒无视 `PIN_INT` 状态轮询 SPI 读取 `0x10308`，且 `goodix_report()` 对单帧漏检零消抖立即发送 `REDWOOD_TOUCH_UP`。
   - **修复**：在 [`package.py`](../../tools/k90auto/package.py) 中将默认脚本切为 `rc.jobs.interactive` 停掉后台 `rwtouch`；在 [`redwood_goodix.c`](../../hackios-xnu-kernel/xnu/files/osfmk/arm64/redwood_goodix.c) 中改为按 `PIN_INT` 中断采样并增加连续漏检消抖（`missed >= 2` 才上报抬起）；在 [`input26_service.c`](../../hackios-xnu-userland/userland/files/root/bin/input26_service.c) 中将未处于按下状态的 `REDWOOD_TOUCH_MOVE` 自动恢复为 `REDWOOD_TOUCH_DOWN`。
3. **控制中心音量滑块无法调节**：
   - **根因**：[`package.py`](../../tools/k90auto/package.py) 第 395 行 `AUDIO` 默认值为 `"0"`，导致 `com.apple.audiomxd` 被过滤且未打包 `arm64e` 架构的 `RedwoodAudio.driver`。
   - **修复**：将 [`package.py`](../../tools/k90auto/package.py) 中 `AUDIO` 默认值改为 `"1"`。
4. **进入设置页面时屏幕亮度偶发突增或缓慢变暗**：
   - **根因**：开机时面板保持 bootloader 初始 DCS `0x51` 值 `0x35a`（`858`），而 [`MiniAppleARMBacklight.cpp`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniAppleARMBacklight.cpp) 初始上报 `6750`（`400 nits`）时未下发 DCS `0x51`；首次进入设置页触发 `CoreBrightness` 同步滑块位置写入 `0xae4`（`2788`），亮度跳升 3.2 倍；随后第 259 行 `DisplayBrightness` 分支在每次 16 毫秒斜坡回调时不断顺延 `bl.user_until` 窗口，使亮度缓慢下滑。
   - **修复**：在 [`MiniFramebufferDCS.inc`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferDCS.inc) 启动初始化时同步写入初始 DCS 亮度，并在 [`MiniAppleARMBacklight.cpp`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniAppleARMBacklight.cpp) 中移除 `DisplayBrightness` 对 `bl.user_until` 的续期，仅在 `DisplayBrightnessSliderPosition` 数值实际变化时更新背光。
5. **主屏天气与日历小组件滑动时交替变黑（跷跷板現象）及切页时时钟／日历动态图标先显空底板再出内容**：
   - **根因**：
     - 动态图标先空后显：静态图标为预烘位图，而时钟与日历图标在切页滚入视口时实时渲染到 Buffer-backed Texture；[`redwoodmetal_commandbuffer.inc`](../../hackios-xnu-kernel/tools/userland-driver/redwoodmetal_commandbuffer.inc) 与 [`redwoodmetal_completion.inc`](../../hackios-xnu-kernel/tools/userland-driver/redwoodmetal_completion.inc) 在释放 `rw_commit_lock` 后于异步线程执行 `mesa.buffer_textures_writeback`，导致首帧合成时动态前景层尚未回写完成。
     - 小组件交替变黑：同一帧连续渲染两个带背景滤镜／离屏纹理的小组件 Pass 时，[`air_metal.c`](../../hackios-xnu-kernel/tools/mesa/air/air_metal.c) 与 [`air_metal_state.inc`](../../hackios-xnu-kernel/tools/mesa/air/air_metal_state.inc) 在 `draw->discard`（调用 `fd_resource_contents_undefined`）及采样器视图绑定更新（`state_views`）上受滑动脏区与绘制顺序影响，导致其中一个离屏纹理被丢弃或采样到未刷新的全零纹理。
   - **修复**：在包含 Buffer-backed Texture 的 CommandBuffer 完成路径同步执行 `buffer_textures_writeback`；在 [`air_metal.c`](../../hackios-xnu-kernel/tools/mesa/air/air_metal.c) 与 [`air_metal_state.inc`](../../hackios-xnu-kernel/tools/mesa/air/air_metal_state.inc) 中修复多 Pass 离屏纹理切换时的附件保留与采样器视图刷新。
6. **滑动关机后黑屏约 1 分钟、随后跳出红色 `WATCHDOG` 横幅**：
   - **根因**：滑动关机调用 [`MiniFramebufferFlip.inc`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferFlip.inc) 的 `MiniIOMobileFramebufferPowerOff()` 清零双帧缓冲并关闭 `dim_poweroff()`，屏幕立即变黑；但内核关机路径停止了每 10 秒一次的高通 Hypervisor 虚拟看门狗喂狗（`VIRT_WDT_PET = 0x86000007`，超时 65 秒）且未能在超时前完成停核并跳回 `xnuloader`，约 60 秒后触发 Hypervisor 看门狗复位进入 `xnuloader` 红屏 `WATCHDOG` 横幅。
   - **修复**：在 [`GenericARMPE.cpp`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/GenericARMPE.cpp) 与 [`loader_return.c`](../../hackios-xnu-kernel/xnu/files/osfmk/arm64/loader_return.c) 的关机与停核路径中主动执行 `hv_wdt_pet_NOW()` 并在同步 `/private/var` 后立即跳回 `xnuloader`。
7. **桌面图标挪动位置跨开机保留说明与 `RDWFS001` 版本兼容保护**：
   - **此前测试丢失原因**：昨日及今日早些时候（`RDWFS001` 内核块持久化生效前）使用用户态 `var_store` 归档方案，遇看门狗复位或重新解包 `etc/var.seed`（`seed-icons.bin`）即还原为初始桌面布局。
   - **本次关机前挪动图标的状态**：21:02 运行的 `m6_boot_success.log` 已挂载 `darwin_var` 上的 `RDWFS001`（`slot 1, gen 34808, 18266 nodes`，`version = 1u`），用户在关机前将应用从第二屏挪到第一屏后，`SpringBoard` 写入的 `IconState.plist` 已通过 1.5 秒元数据同步线程落盘到 `darwin_var`；[`ramfs_disk.inc`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_disk.inc) 保持兼容 `version == 1u` 与 `2u`（且对 `node_count >= 1000` 的有效快照跳过种子覆盖），下次开机直接恢复该位置。

## 2. 上游优化项与工程工具链跟进

对照[上游对照分析](../analysis/2026-11-05-upstream-lessons.md)与[上游 2/3/4 阶段对照分析](../analysis/2026-11-06-upstream-2-3-4-analysis.md)，当前状态与后续安排如下：

1. **已合入并完成图形验证项**：
   - 顶点着色器 CSO 缓存（`air_metal_vertex_cache.inc`，已修复深拷贝）、空纹理指针 phi 解析（`air_ptr_phi.inc`）、纹理视图 `swizzle`、`TbdsA2Xhf` 拼接快速路径、硬件 `crc32x`、增量编译时间戳夹紧与 `var_store` 64 MiB 增量同步均已在真机正常工作。
2. **待继续推进的上游性能与工具链项**：
   - 整屏 pass 逐 draw 计时与高频着色器特化（控制中心下拉与主屏翻页长帧治理）。
   - 跨开机着色器编译缓存（`/private/var/db/redwood-aircache` 与管线缓存随 `var_store` 持久化，消除冷启动首次打开控制中心／应用时的编译卡顿）。
   - Mesa `ir3` A8xx 补丁回移与 `SwapWait`／ACD 调优。

## 3. 会话内已反馈但尚未投入／待继续攻关的事项

1. **桌面图标与小组件（Widget）渲染异常**：
   - **主屏日历 App 图标完全透明／空白（已落地，待真机复核）**：已由 §1.12 在 `inject_sb26_airdrop.inc` 中强制走位图渲染路径 `iconImageWithInfo:` 并增加图层回退保护修复。
   - **主屏天气与日历大尺寸小组件背景呈黑色（已落地，待真机复核）**：已由 §1.8 在 Mesa 补丁 0016 中对无 `VARYING_SLOT_LAYER` 的 2D 管线回退常量图层 0 修复越界采样。
2. **特定交互卡死、主线程阻塞与崩溃日志跨开机持久化**：
   - **点击隔空投送（AirDrop）图标整机卡死（已落地，待真机复核）**：已由 §1.11 在 `inject_sb26_airdrop.inc` 中检测 `awdl0` 缺失返回离线单例避免主线程持锁超时修复。
   - **下拉控制中心点击「屏幕镜像（投屏）」菜单卡顿转圈 10 余秒（已落地，待真机复核）**：已由 §1.11 拦截投屏设备查询走本地内存缓存并由后台 GCD 队列异步刷新修复。
   - **Safari 输入网址过程中偶发整机卡死并触发看门狗黑屏重启（日志直写已落地，待真机复核）**：已由 §1.10 在 `darwin_var` 划定 16 MiB 专用扇区建立 `'KLOG'` 硬件同步直写与开机自愈机制，崩溃现场日志可在重启后完整提取。
3. **网页字体与视频播放**：
   - **YouTube 首页文字显示为方框问号 `<?>`（已落地，待真机复核）**：已由 §1.13 在 `IOS_JOBS` 纳入 `com.apple.fontservicesd` 自启动并补齐 `/var/db/fontconfig` 权限修复。
   - **网页视频无法播放（已落地，待真机复核）**：已由 §1.13 启用 WebKit VP9 CPU 软解，以及 §1.14 在 `redwooddrawable_420v.inc` 中实现 NV12（`'420v'`）双平面纹理绑定与 BT.601 Compute Shader 转换管线修复；后续继续推进 SM8750 Iris VPU v3.5 硬件解码。
4. **第三方容器应用与内置服务**：
   - **安装并验证 `LiveContainer+SideStore.ipa`**：在 `darwin_var` 直写持久化就绪后安装并验证跨开机保留与运行。
   - **天气（Weather）App 无法获取天气数据**：排查 `weatherd` 对 `locationd`、`kvsd` 与网络状态通知的依赖。

## 4. 外设与子系统继续适配队列

按既有规划继续推进各外设与系统能力适配：

- **蓝牙（第 3、4 步）**：已完成开启、BLE 扫描与配对码弹窗；继续推进蓝牙耳机连接与音频路由、SE14 UART 3 Mbaud 提速（`0xFC48` 加 GENI 时钟）与隔空投送，见[蓝牙接入调研](../analysis/2026-11-02-bluetooth-bringup.md) §6、§8。
- **音量与音频输出**：音量键、HUD 提示框与控制中心音量滑块已接通（`AUDIO=1`）；继续推进 ADSP、AudioReach 与扬声器功放驱动出声，见[音量与声音输出调研](../analysis/2026-11-02-audio-and-volume.md)。
- **视频播放与硬件解码**：先实现 Metal 驱动两平面 YCbCr（`'420v'`）合成并在 `MobileSafari` 中打通 H.264／VP9 软解播放，再推进 SM8750 Iris VPU v3.5 固件加载、HFI gen2 与 VideoToolbox 硬解插件，见[视频解码调研](../analysis/2026-11-05-video-decode.md)。
- **相机**：控制中心打开相机当前为黑屏；提取主摄 OV50E `sensormodule` 配置，推进 CCI／CSIPHY／IFE 与 `cameracaptured` 接入，见[相机路线](camera-plan.md)。
- **手电与振动（iOS 26）**：排查 `rate7-def1` 中手电 `0x0018` 传输丢弃与振动故障寄存器 `0x10` 清除问题，恢复控制中心手电开关与系统触感反馈，见[手电与震动实测](../progress/2026-10-26-torch-and-haptics.md)。
- **充电状态与温控**：墙插充电器与电脑 USB 下验证 `annibale_battery.c` 在线检测与防抖窗口，推进原生 `CLPC` 调频策略分析与复刻，见[路线图 §5.4](2026-10-26-roadmap.md#54-苹果原生策略分析与复刻clpc)。
- **天气、Safari 下载、蜂窝与 App Store**：修复 `weatherd` 依赖服务、Safari 下载文件移入「我的 iPhone」、蜂窝基带与 App Store 登录下载，见[总账跟踪](2026-10-23-tracking.md) §2。

## 5. Android 系统内 OTA 影响结论

已写入[双系统分区与持久化部署手册](dual-boot-setup.md) §5：

- 系统内 OTA（`update_engine`）不刷写 `gpt_both0.bin`，重启时 `resize.f2fs` 仅对齐 GPT 中 `userdata`（`sda34`）的边界，因此 `darwin`（`sda35`）与 `darwin_var`（`sda36`）分区及 iOS 数据完全保留。
- 增量 OTA 会因 `boot`／`init_boot` 已被修改而校验失败，日常更新应使用**完整包 OTA（Full ROM）**。
- 完整包 OTA 会将新版本 Android 写入当前闲置槽位（覆盖原 `xnuloader` 所在槽位的 `boot`）并在重启后切到新槽位；待新版本 Android 开机完成后台快照合并后，将 `xnuloader` 刷入退下来的新闲置槽位即可恢复双启动。

## 6. 第一优先级真机恢复与部署取证（2026-11-06）

### 6.1 物料准备与完整性核对

1. **LUN 4 GPT 相位镜像**：`hackios-xnu-kernel/out/gpt_both4_slotb.bin`（45,056 字节），用于在 LK Fastboot 下写入 `partition:4` 并执行 `set_active a`。
2. **原版三容器镜像**：位于 `hackios-xnu-kernel/out/ipsw/v57/26/`，包含 `os.dmg`（9,758,048,256 字节，2,382,336 块）、`systemos.dmg`（5,261,754,368 字节，1,284,608 块）与 `appos.dmg`（14,680,064 字节，3,584 块），合计 15,034,482,688 字节（14.002 GiB），由 `userdata-dual-carve.py` 写入 16 GiB `sda35`（`darwin`）分区。
3. **独立双系统引导载荷与内核**：`hackios-xnu-kernel/out/boot-a-ios.img`（23,851,008 字节）与最新编译内核 `hackios-xnu-kernel/out/xnu12377-st6.bin`（20,958,824 字节），准备刷入 `boot_a`。
4. **验证应用**：`/Users/fan/Downloads/LiveContainer+SideStore.ipa`（23,607,434 字节），由 `tools/k90auto/install-ipa.py` 执行 ad-hoc 签名并安装。

### 6.2 真机硬件诊断与 USB 状态

1. **USB 物理连接与枚举状态**：主机端 `ioreg -p IOUSB -l` 读出设备物理连接为 `idVendor = 6353`（0x18d1），`idProduct = 53261`（0xd00d），`USB Product Name = "Android"`，`USB Serial Number = "519e5a70"`，`locationID = 51576832`，接口类为 `bInterfaceClass = 255, bInterfaceSubClass = 66, bInterfaceProtocol = 3`（Fastboot）。
2. **端点通信诊断**：控制端点 EP0 可读取描述符，但数据端点 0x01（Bulk OUT）对命令传输无响应。调用 IOKit `WritePipeTO` 返回 `0xe0004051`（`kIOUSBTransactionTimeout`），调用 libusb `libusb_bulk_transfer` 返回 `-7`（`LIBUSB_ERROR_TIMEOUT`）。
3. **主机侧恢复处置**：排查并终止了占用该接口的后台进程 `lghub_agent`，并由主机下发 `libusb_reset_device` 端口复位与 `clear_halt` 清除端点停顿；主机侧复位完成后，设备端 Bulk OUT 端点仍处于无响应状态。
4. **根据真机无人值守约束判定**：依据 [AGENTS.md](../../AGENTS.md) §5 与 [USB 恢复经验](../analysis/2026-10-25-usb-recovery-lessons.md) §4，设备属于「枚举但无应答且软件入口不可达」状态，由用户长按电源键进行硬件复位进入 LK Fastboot。

### 6.3 真机冷启动恢复与 R2 部署取证

1. **冷启动与载荷装配**：设备 519e5a70 完成电源键硬件复位后重新开机，在 16 秒内进入 `xnuloader`（`getvar result` 为 `idle`，`getvar product` 为 `xnuloader`）。载荷通过 `WIFI_FW_MODE="used"`（6.9 MB 固件）及 UFS `darwin_var` 原生持久化彻底消除 `BootShim.S` 55 MiB `PAYLOAD_CAP`（`0x03700000`）限制，打包生成 23,885,824 字节（22.78 MiB）`boot-a-ios.img`（SHA-256 `c74591d44ed0078d91cff014978dae01ea2e9c58057bd6d5a62374bdf27f416a`）。
2. **系统引导与持久化挂载取证**：由 `out/evidence-r2/m6_boot_2215.log`（共 14,573 行）完整记录开机过程。`daudio` 空转已被完全静音，`RDWFS001` 原生文件系统成功挂载并恢复已有 18266 个真实节点，`SpringBoard`（PID 31）与 `backboardd`（PID 41）稳定进入运行状态。
3. **桌面与视觉审计结果**：由 `out/evidence-r2/m6_desktop_2215.png` 确认桌面状态，第 1 屏保留用户挪动的 Triangle 应用图标，状态栏时间 22:39，电池 70% 正常显示充电闪电图标。调用 `visual-audit.py` 生成 `out/evidence-r2/audit_2215.json` 执行视觉审计，判定 `defect_detected = false`，纯黑方块与状态栏穿透均为 0，审计成功通过。

## 7. R2 里程碑（M1～M6）专项攻关与真机闭环验证

### 7.1 M1：跨开机着色器编译磁盘缓存与管线特化

1. **磁盘缓存架构与原子落盘**：在 [`hackios-xnu-userland/tools/mesa/rebase-26/0015-ir3-disk-cache-darwin-uuid.patch`](../../hackios-xnu-userland/tools/mesa/rebase-26/0015-ir3-disk-cache-darwin-uuid.patch) 中引入 Darwin 平台基于 UUID 路径的 IR3 磁盘缓存机制；在 Metal 驱动 [`redwoodmetal_pipecache.inc`](../../hackios-xnu-kernel/tools/userland-driver/redwoodmetal_pipecache.inc)、[`redwoodmetal_stitch.inc`](../../hackios-xnu-kernel/tools/userland-driver/redwoodmetal_stitch.inc) 与 [`redwoodmetal.m`](../../hackios-xnu-kernel/tools/userland-driver/redwoodmetal.m) 中建立 `/private/var/db/redwood-aircache` 持久化目录。着色器写入采用 `NSDataWritingAtomic` 保证崩溃安全性，增加空文件防御逻辑阻断 0 字节损坏文件的无效加载。
2. **管线哈希特化**：驱动以管线名称、输出索引、节点数、bitcode、函数及参数数量构造复合键 `rw_pipe_key` 计算 CRC32 哈希，实现跨开机着色器编译产物精确命中与管线特化，消除首次打开控制中心或转场时的编译卡顿。

### 7.2 M2：天气（Weather）App 与依赖服务链疏通

1. **守护进程白名单与断言防御**：在 [`hackios-xnu-userland/userland/mkjobs.py`](../../hackios-xnu-userland/userland/mkjobs.py) 中将 `locationd` 从 `DENY` 列表中移除，并增加针对 `com.apple.locationd` 与 `com.apple.weatherd` 的显式断言保护，防止依赖服务被意外屏蔽；在 [`tools/k90auto/package.py`](../../tools/k90auto/package.py) 中同步放行 `weatherd` 与 `locationd`，将异常退出的 `com.apple.syncdefaultsd` 纳入 `REST_DENY`。
2. **骨架目录与权限配置**：在 [`userland/var.skel.extra`](../../hackios-xnu-userland/userland/var.skel.extra) 与 [`userland/src/init_mount.inc`](../../hackios-xnu-userland/userland/src/init_mount.inc) 中预置 `/private/var/mobile/Library/SyncedPreferences`、`/private/var/mobile/Library/Weather`、`/private/var/mobile/Library/WeatherDaemon` 以及 `/private/var/db/locationd` 目录结构，设置 UID 501 与 205 所属权，疏通天气数据拉取与位置解析依赖链。

### 7.3 M3：手电 SPMI 传输重试与触感升压转换器使能

1. **手电 SPMI 通信容错**：在 [`hackios-xnu-kernel/xnu/files/bsd/dev/annibale_torch.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale_torch.c) 中针对 `0x0018` 寄存器传输丢弃增加重试逻辑，将偶发通信丢弃降级为非致命事件，保持手电状态机正常推进，消除驱动异常退出。
2. **触感反馈升压使能与故障清除**：在 [`hackios-xnu-kernel/xnu/files/bsd/dev/annibale_haptic.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale_haptic.c) 与 [`annibale_haptic_data.h`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale_haptic_data.h) 中增加对 `0x10` Boost UVLO 欠压锁定故障寄存器的清除处理，并配置 `0xf246` 升压转换器寄存器使能 LRA 线性马达震动输出。

### 7.4 M4：蓝牙 SE14 UART 3 Mbaud 提速与 AudioReach 旁路防空转／DMA 隔离

1. **蓝牙高速波特率与无锁并发**：在 [`hackios-xnu-kernel/xnu/files/bsd/dev/annibale_bt_uart.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale_bt_uart.c)、[`annibale_bt_ios.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale_bt_ios.c) 与 [`annibale_bt_private.h`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale_bt_private.h) 中实现厂商命令 `0xFC48` 协商提速至 3 Mbaud；增加芯片 Command Complete ACK 轮询与波特率回滚保护，采用原子计数器与工作线程 `gic_v3_spi_unmask` 实现 ISR 中断底半部无锁并发。
2. **音频引擎空转消除与 DMA 内存隔离**：在 [`hackios-xnu-kernel/xnu/files/bsd/dev/annibale_audio_reach.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale_audio_reach.c)、[`annibale_audio_amp.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale_audio_amp.c) 与 [`redwood_audio.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/redwood_audio.c) 中为 `reach_feeder_thread` 增加 20 毫秒空闲休眠并静音刷屏日志，消除 1 颗 Oryon 大核 100% 满载空转与每秒 2.7 万行 `daudio` 打印；将 64 KiB 音频 DMA 环形缓冲区迁移至 `lowdma` 顶部（`[0xcf66f000, 0xcf67f000)`），彻底解除与 WCN7850 Wi-Fi 在 `0xc776f000` 的 DMA 内存碰撞。

### 7.5 M5：相机 OV50E／CSID TPG 硬件寄存器与 Iris VPU v3.5 HFI gen2 队列

1. **相机测试图案与 DMA 链路**：在 [`hackios-xnu-kernel/xnu/files/bsd/dev/annibale_camera.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale_camera.c) 中接入 OV50E 传感器配置与 CSID-lite0 测试图案发生器（TPG）14 个硬件寄存器，配置 IFE-lite0 WM0 目标地址 `0x9b300000` 并建立非阻塞帧读取与快照锁，确保相机捕获链路连通。
2. **Iris 硬件解码与 VideoToolbox 插件**：在 [`hackios-xnu-kernel/xnu/files/bsd/dev/annibale_iris.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale_iris.c) 中实现高通 SM8750 Iris VPU v3.5 内核驱动，建立 SCM PAS ID 9 固件真实鉴权、HFI gen2 环形指令／响应队列管理与 SMMU 动态旁路；在 [`hackios-xnu-userland/userland/src/videotoolbox_iris.c`](../../hackios-xnu-userland/userland/src/videotoolbox_iris.c) 中实现 VideoToolbox 硬件解码插件桥接，支持动态分辨率提取与双平面映射。

### 7.6 M6：引导与启动链路综合自愈

1. **显示与背光自愈**：在 [`MiniAppleARMBacklight.cpp`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniAppleARMBacklight.cpp) 与 [`MiniFramebufferDCS.inc`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferDCS.inc) 中锁定 400 nits（`6750`）初始背光，开机下发 DCS `0x51` 并过滤系统自主斜坡，消除屏幕亮度跳变。
2. **文件系统瘦身与分配安全**：在 [`ramfs_disk.inc`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_disk.inc) 中实施 1500 毫秒元数据聚合单趟同步，拆出 [`ramfs_store.inc`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_store.inc) 使 [`ramfs.c`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs.c) 净减少 59 行；修复 [`userland/build.sh`](../../hackios-xnu-userland/userland/build.sh) 中 `ln -sf` 符号链接创建幂等性；全量清除针对可变长内存分配的 `Z_NOFAIL` 标记。
3. **双版本持久化兼容与触控消抖**：在 `ramfs_disk.inc` 中同时兼容 `version == 1u` 与 `2u`，在 `node_count >= 1000` 时保护槽位 1 上的 18266 个真实节点，跨开机完整保留用户挪动的图标位置；在 [`redwood_goodix.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/redwood_goodix.c) 中增加连续漏检消抖（`missed >= 2`），在 [`input26_service.c`](../../hackios-xnu-userland/userland/src/input26_service.c) 中将未处于按下状态的 `MOVE` 自动恢复为 `DOWN`，消除拖动图标中途断触；在 [`GenericARMPE.cpp`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/GenericARMPE.cpp) 与 [`loader_return.c`](../../hackios-xnu-kernel/xnu/files/osfmk/arm64/loader_return.c) 的滑动关机路径中主动执行 `hv_wdt_pet_NOW()` 立即喂狗后安全返回 `xnuloader`。

### 7.7 仓库提交与真机闭环验证总览

1. **各仓库提交记录**：用户态仓库提交 [`a66051f`](https://github.com/iola1999/hackios-xnu-userland/commit/a66051f)、[`c475273`](https://github.com/iola1999/hackios-xnu-userland/commit/c475273)，内核仓库提交 [`40377ec`](https://github.com/iola1999/hackios-xnu-kernel/commit/40377ec)、[`c9225c4`](https://github.com/iola1999/hackios-xnu-kernel/commit/c9225c4)，顶层工作区提交 [`34d1eff`](https://github.com/iola1999/hackios-redmi-k90-annibale/commit/34d1eff) 完成全量总账同步与子模块指针推进。
2. **真机取证与验收结论**：真机刷入 23,916,544 字节 `boot-a-ios.img`（SHA-256 `c42c76f3a9a2fbeefa354e7c67b65d2fa0d919e844a5ba2632e6ee7ae2bc54fc`）后正常开机，Wi-Fi（`en0`）在 61 秒初始化完成并连网，`/private/var` 从 `darwin_var` 加载恢复。

## 8. 全量待解问题与持续跟进总表（合并 2026-11-07 00:46 真机实测与历史累计未闭环问题）

本节汇总用户在整个会话（2026-11-05 至 2026-11-07 01:18）历次真机测试中提出的全部未彻底解决或待真机复核的问题，作为后续多 Worker 并发排查、根因修复与无人值守自动化验证的唯一执行清单。

### 8.1 2026-11-07 真机实测 8 项高优先级问题与需求（第一优先级）

基于 `00:43` 刷入的 `boot-a-ios.img`（SHA-256 `c42c76f3...`）及实测取证日志 `out/evidence-r2/m6_boot_0045.log`、`out/evidence-r2/m6_user_test_0049.log`、`out/evidence-r2/m6_user_test_0051.log`、`out/evidence-r2/m6_user_test_0059.log` 与截图 `out/evidence-r2/m6_desktop_0046.png`：

1. **开机进入桌面后应用图标全空（仅显示文字）、约 1 分钟后才依次出现，且期间桌面无法点击交互**：
   - **现象**：开机进入主屏后，所有应用图标初始均为空白（仅有下方应用名称文字），等待约 1 分钟图标才逐个渲染出来（此前版本还出现过一直无图标、点开设置后才瞬间全出，以及左右切页时时钟和日历动态图标先显空底板再出内容）；在图标未全部生成期间，主屏无法响应点击操作。
   - **现场线索**：`m6_user_test_0049.log` 显示 `iconservicesagent`（PID 211）在开机后持续编译及执行 258+ 条 Metal 渲染管线（`maxCommandBufferCount = 64`，在 `-[_MTLCommandBuffer initWithQueue:]` 信号量阻塞等待），同时 `SpringBoard` 主线程被图标同步生成或 [`inject_sb26.c`](../../hackios-xnu-userland/userland/src/inject_sb26.c) 的 `sb26_stepped_refresh_step` 刷新事务阻塞。
2. **主屏顶部天气与日历大尺寸小组件及负一屏小组件仍为纯黑背景（含滑动跷跷板现象）**：
   - **现象**：主屏顶部的天气与日历两个大尺寸小组件背景依然显示为纯黑色；`m6_desktop_0046.png` 中负一屏日历、天气、提醒事项、屏幕使用时间小组件同样为纯黑背景（电池和 Siri 建议小组件背景正常）。此前实测还观察到下拉控制中心透过背景模糊看时日历组件变白、收起控制中心又变黑，以及桌面滑动时日历与天气组件黑白底色交替变化的跷跷板现象。
   - **现场线索**：`m6_boot_0045.log` 第 12991～12995 行显示 `backboardd` 在渲染小组件材质管线 `com.apple.coreanimation.PRGhAXm_TimgA2Xhfu_Isrc` 时使用 `attachment 0 format 115`（`MTLPixelFormatRGBA16Float`，64 位半精度浮点）与双颜色附件（`colour 2`），且 `chronod`（PID 66）／`WidgetRenderer_Default`（PID 301）绘制的 SwiftUI 小组件归档图层与 [`redwoodmetal.m`](../../hackios-xnu-kernel/tools/userland-driver/redwoodmetal.m)、[`air_metal.c`](../../hackios-xnu-userland/tools/mesa/air/air_metal.c) 多附件混合路径异常。
3. **打开设置进入 Wi-Fi 等子页面时屏幕轻微变亮／闪烁，且首次输入密码连接 Wi-Fi 提示「无法加入网络」（约 `00:46:35` 前几秒），随后才自动连上**：
   - **现象**：设置中 Wi-Fi 可以正常开启，但打开设置或进入 Wi-Fi 等子页面时屏幕亮度仍有轻微跳升或先暗后亮（此外开机苹果 Logo 阶段屏幕亮度偏低）；首次输入密码连接 Wi-Fi 弹窗提示「无法加入网络」，稍后后台才自动连接成功。
   - **现场线索**：`m6_boot_0045.log` 第 12906～13696 行显示 [`MiniAppleARMBacklight.cpp`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniAppleARMBacklight.cpp) 在开机解锁时被 `CoreBrightness` 从 `400 nits` 下调至 `171.403 nits`（`0x1114`），进入设置子页面时 `IOMFBBrightnessLevel` 与 `DisplayBrightness` 再次触发亮度变化；[`lx_join.c`](../../hackios-xnu-kernel/wifi/lx/src/lx_join.c) 首次关联与四次握手（EAPOL）或 `wifid` 超时判定仍存在竞态。
4. **天气（Weather）App 打开后始终无法加载天气详情**：
   - **现象**：连上 Wi-Fi 后打开天气 App，详情页一直无法加载出当前或指定位置的天气数据。
   - **现场线索**：需结合 `weatherd`、`locationd`、定位权限／默认位置供给及 WeatherKit 网络请求（TLS／证书校验／`apsd`／`akd`／`fairplay`）排查具体失败环节。
5. **状态栏显示充电但实际未充入（电量从 44% -> 42% -> 38% 持续下降）与低电量切回 Android 补电应急机制**：
   - **现象**：状态栏显示正在充电图标，但实际未充进去电，电量从早先的 84% -> 75% -> 68% -> 44% -> 42% 一路掉到 38%（`m6_user_test_0059.log` 第 4850、13406、19592 行记录 `BQ27Z561 SOC=42% V=3772..3807 mV I=-159..-1692 mA`，净电流持续为负）。
   - **根因排查与应急补电规程**：
     - **硬件充电修复**：排查 PM8550B SMB2 充电控制器寄存器（USBIN 输入限流 ICL、充电使能位、Type-C／PD 握手档位）与 [`annibale_battery.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale_battery.c)，解除低电流限流使净电流转正。
     - **真机验证低电量保护（应急切回 Android 充电）**：在 PM8550B 充电驱动修复生效前，无人值守脚本及调试过程实时监测 `BQ27Z561 SOC`；当电量低于 `30%～35%` 时，按[引导目标切换 SOP](device-boot-target-sop.md) 临时切回 Android 槽位利用原厂快充补电至安全水位（如 `>= 60%`），再切回 iOS 槽位继续无人值守调试，防止真机因电量耗尽断电停机。
6. **隔空投送（AirDrop）从「接收关闭」切换为「开启接收」无反应（仍显示关闭），且设置内蓝牙显示开启但控制中心蓝牙显示关闭**：
   - **现象**：在设置或控制中心将隔空投送从「接收关闭」改为「所有人／仅联系人」无任何变化，仍保持「接收关闭」；设置列表里蓝牙显示为「打开」，但下拉控制中心看到的蓝牙图标处于「关闭」状态。
   - **现场线索**：`m6_user_test_0049.log` 与 `m6_user_test_0051.log`（第 7558、8086 行）显示 `bt: connected to com.apple.uart.sk.bluetooth (unit 1, waited 40000 ms, ready 0)` 后断开，`bluetoothd` 循环运行 `BlueTool` 启动脚本并上报 `com.apple.Bluetooth.HWFailure`，对 `kCBMsgIdLocalDeviceGetModulePowerMsg` 返回未就绪状态 `0xcafebabe`（导致控制中心判定蓝牙关闭、AirDrop 拒绝开启接收），且 [`inject_sb26_airdrop.inc`](../../hackios-xnu-userland/userland/src/inject_sb26_airdrop.inc) 中对 `SFAirDropDiscoveryController` 与 `airdrop` Gestalt 的离线拦截直接阻止了状态切换。
7. **下拉控制中心展开「隔空投送／投屏（屏幕镜像）」功能后两三秒，以及 `00:58:40` 左右日常操作中，屏幕转菊花重启（`SpringBoard` 崩溃重启）**：
   - **现象**：
     - 在控制中心展开隔空投送或屏幕镜像投屏面板后等待 2～3 秒，屏幕黑屏出现转菊花（`SpringBoard` 进程从 PID 199 崩溃并重生为 PID 294；此前未加异步拦截时则是点击 AirDrop 整机卡死、点击投屏转圈卡死 10 余秒）。
     - 在 `00:58:33`～`00:58:44` 左右日常使用（`MobileSafari`／主屏切换）时，屏幕再次出现黑色转菊花（`BKDisplayRenderOverlaySpinny`），`SpringBoard` 从 PID 371 崩溃退出（`signal 6 / SIGABRT`）并重生为 PID 411。
   - **现场日志与已定位根因（`out/evidence-r2/m6_user_test_0059.log` 第 13522～13546 行）**：
     - 捕获到完整崩溃栈：`userabort: SpringBoard[371] aborts, shared cache slide 0x4da4000; called from: 0x193e7efcc 0x188fd4d70 0x188d02b98 0x188d02884 0x188d05320 0x188d1dd34 0x100e72c4c 0x1c672ffa8 0x1c67df9e8 0x1c67e066c 0x1c2dcc1e4 ...`。
     - 经 `dsc.py` 反汇编符号化确认：`SpringBoardHome`（`0x1c1a3b9e8 -> 0x1c198bfa4`）在 `libdispatch` 后台线程（`0x1c2dcc1e4`）调用 `-[SBCalendarIconImageProvider iconLayerWithInfo:traitCollection:options:]`，进入 [`inject_sb26_airdrop.inc`](../../hackios-xnu-userland/userland/src/inject_sb26_airdrop.inc) 第 310 行的钩子 `sb26_calendar_icon_layer_fallback`（`0x100e72c4c`）：
       1. **ARM64 HFA 寄存器签名不匹配**：`struct SBIconImageInfo`（`CGSize size; double scale; double continuousCornerRadius;`）作为 4 个 `double` 的同质浮点聚合体（HFA）通过浮点寄存器 `d0..d3` 传参，`traitCollection` 与 `options` 实际在通用寄存器 `x2`、`x3`；而 `sb26_calendar_icon_layer_fallback(id self, SEL _cmd, void *info, id tc, unsigned long opts)` 将 `info` 声明为指针占用 `x2`，导致传给原实现 `orig_calendar_layer` 与 `iconImageWithInfo:traitCollection:options:` 的参数及浮点寄存器全部错位。
       2. **后台线程无事务修改 `CALayer` 触发 `CA_ASSERT_MAIN_THREAD_TRANSACTIONS` 断言 `abort()`**：`sb26_calendar_icon_layer_fallback` 第 340 行在后台 GCD 线程直接调用 `[new_layer setContents:cg_img]`（`QuartzCore` `0x183f79d34 -> 0x183f61320 -> 0x183f5e884 -> 0x183f5eb98 -> 0x184230d70`），未包裹 `[CATransaction begin]`／`[CATransaction commit]`，触发 `QuartzCore` 断言 `"CoreAnimation: CA_ASSERT_MAIN_THREAD_TRANSACTIONS is set and an implicit transaction wasn't created on a main thread."` 并直接调用 `abort()` 杀死 `SpringBoard`；此外还需一并核查 `inject_sb26_airdrop.inc` 中 `MRUMirroringController` 后台队列回调的线程安全性。
8. **第三方 IPA 应用在主屏幕长按仅显示「从主屏幕移除」无法彻底卸载，需支持主屏直接卸载并预装原生「IPA 管理器」App（同时清理设备已装测试应用）**：
   - **为什么当前在主屏幕删不掉（根因）**：
     - [`hackios-xnu-userland/userland/src/appinst.m`](../../hackios-xnu-userland/userland/src/appinst.m) 第 520～530 行在向 `LSApplicationWorkspace` 注册应用时，把字典属性写成了 `@"ApplicationType": @"System"` 与 `@"IsDeletable": @NO`（早期为了绕过 `FrontBoard` 对 `User` 类型应用的签名描述文件校验，把第三方 IPA 伪装成了不可删除的系统内置应用）。
     - `SpringBoard` 读取到 `ApplicationType == "System"` 且 `IsDeletable == NO` 后，在主屏长按图标菜单中隐藏了「删除 App」选项，只允许「从主屏幕移除」（移入资源库，保留 Bundle 与数据容器）。
   - **目标方案与实现要求**：
     1. **支持在主屏幕直接彻底卸载（与 App Store 下载的应用体验一致）**：将 [`appinst.m`](../../hackios-xnu-userland/userland/src/appinst.m) 注册字典中的 `@"IsDeletable"` 设为 `@YES`，并打通 `SpringBoard`（`SBApplication`／`SBApplicationController` 的 `isUninstallAllowed` 与 `uninstallApplication:`）到 `LSApplicationWorkspace unregisterApplication:` 及删除 `/private/var/containers/Bundle/Application/<UUID>` 与对应 `MCMAppDataContainer` 数据容器的完整卸载链路，使主屏长按直接出现「删除 App」并可彻底删除。
     2. **预装原生「IPA 管理器」App（`RedwoodInstaller.app`）**：开发并预装一个类似 Android 安装器的图形化管理工具，支持手动扫描与选择已下载的 `.ipa` 文件执行安装（以及从「文件」App／Safari 分享打开 `.ipa` 手动安装），集中展示全部已安装的第三方应用（名称、Bundle ID、版本、占用空间），并提供一键「彻底卸载」与「打开」按钮；启动脚本仅通过该管理器或命令行显式触发安装。
     3. **清理当前设备上已安装且无法手动删除的残留测试应用**：通过 `appinst list` 与 `appinst remove <BUNDLE-ID>`（或在 IPA 管理器中）将用户设备上已安装的测试应用清理干净。

### 8.2 前期累计反馈待真机复核与持续攻关全量清单（第二优先级）

1. **整机静置发热、卡顿掉帧与显示渲染架构优化**：
   - **现象**：手机静置在桌面不操作时温度仍然偏高；长按、滚动、滑动或跨屏操作时偶发掉帧卡顿。
   - **待办**：消除 [`MiniFramebufferRows.inc`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferRows.inc) 每帧 `1206×2622 -> 1156×2510` CPU 双线性缩放与逐行哈希中转开销（对齐原生扫描输出或启用 DPU 12.0 SSPP 硬件缩放）；修复 Freedreno 局部脏区更新附件保留以关闭 `CA_DISABLE_DIRTY_REGIONS=1` 整屏重绘；推进原生 `CLPC` 调频与温控策略，降低空闲态 CPU／GPU 频率与功耗。
2. **存储与文件系统完全对齐苹果真机方案及原版未裁剪系统镜像验证**：
   - **现象与要求**：消除旧 `ramfs` 定时回刷及过渡性元数据方案，确保文件修改实时落盘到 `darwin_var`（无论正常关机或突然断电／看门狗重启均不丢失桌面图标位置、应用数据与权限配置）；在 16 GiB `darwin` 分区实测挂载苹果原版未裁剪 `os.dmg + systemos.dmg + appos.dmg`，彻底杜绝因裁剪 `UserNotifications`、字体、国际化资源引起的日历重复弹通知权限申请、系统界面显示英文、网页字符变问号等问题。
3. **系统内滑动关机、偶发卡死与看门狗崩溃日志持久化复核**：
   - **现象**：此前滑动关机出现过卡在关机转圈画面，或黑屏约 1 分钟后跳出看门狗红色横幅（`WATCHDOG`）挂起且长按电源键难唤醒；Safari 输入网址或日常操作中偶发整机卡死并触发看门狗黑屏重启。
   - **待办**：真机复核滑动关机能否立即保存数据并干净熄屏返回／停机；复核内核 panic 与看门狗超时前向 `darwin_var` `[64M, 80M)` 扇区直写崩溃日志及开机自动还原 `/private/var/db/panic.log` 链路。
4. **网页字体、网页视频软硬解播放、Safari 下载与第三方 IPA 安装验证**：
   - **现象与待办**：真机验证 YouTube 首页文字是否还会显示为方框问号 `<?>`；验证 Safari 播放 H.264／VP9 网页视频（含 `'420v'` NV12 双平面 IOSurface 纹理合成与 SM8750 Iris VPU v3.5 硬件解码）；验证 Safari 下载文件能否正常移入「我的 iPhone」（`ramfs_clonefile`）；安装并验证 `/Users/fan/Downloads/LiveContainer+SideStore.ipa` 跨开机保留与运行。
5. **音量与扬声器音频输出、蓝牙耳机音频路由**：
   - **现象与待办**：控制中心音量滑块已可拖动，需继续打通 ADSP、AudioReach 与扬声器功放实际出声，以及蓝牙耳机配对连接后的音频流路由。
6. **相机、手电筒、震动触感、蜂窝网络与 App Store**：
   - **现象与待办**：修复控制中心打开相机黑屏问题（推进 OV50E 传感器、CCI、CSIPHY、IFE 真实图像流接入）；真机复核控制中心手电筒开关与系统触感震动反馈；后续继续推进蜂窝基带网络、短信、电话与 App Store。
