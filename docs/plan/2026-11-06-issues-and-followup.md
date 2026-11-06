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

### 1.2 设置页总容量显示 0 KB、可用 2.61 GB（已修复并验证）

- **现象**：「设置 → 通用 → 关于本机」中总容量显示为 `0 KB`，可用容量显示为 `2.61 GB`。
- **根因**：`/private/var` 挂载在内存文件系统 `ramfs` 上，[`hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs.c`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs.c) 的 `ramfs_vfs_statfs()` 原先按物理内存页上限（`RAMFS_PAGES_MAX = 786432` 页，约 3.22 GB）上报 `f_blocks` 与 `f_bfree`，扣去已用页后 `statfs("/private/var")` 仅报告约 `2.61 GB` 可用；同时未接入 UFS `darwin_var` 分区真实块数。
- **修复**：在 [`redwood_ufs.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/redwood_ufs.c) 中导出 `redwood_ufs_darwin_var_blocks()` 返回 `darwin_var` 分区真实 4 KB 块数（`29360128` 块 = 112 GiB），并在 [`ramfs.c`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs.c) 的 `ramfs_vfs_statfs()` 中按该分区块数上报 `f_blocks`、`f_bfree` 与 `f_bavail`（连同 8 GiB 系统盘合计 120 GiB ≈ 十进制 129 GB）。
- **真机验证**：进入「设置 → 通用 → 关于本机」截图确认，总容量显示 `129 GB`，可用容量显示 `128.22 GB`。

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

### 1.5 日历（MobileCal）重复弹出通知权限申请与原生授权持久化（已落地根因修复并打包，待真机复核）

- **现象**：打开日历（`MobileCal`）弹出通知权限请求框，点击「允许」后关闭再重新打开日历，仍每次重复弹出同一权限申请。
- **根因**：
  1. 09:05 从真机取回 `/var/mobile/Library/UserNotifications/Library.plist` 与 `/var/mobile/Library/BulletinBoard/VersionedSectionInfo.plist` 对比发现：`Library.plist` 已登记 `com.apple.mobilecal -> 9258050C-94B0-48D0-BDDE-82BE8E85EA85` 且 `Categories.plist` 已落盘，但 `VersionedSectionInfo.plist` 仅含 `DocumentsApp`、`MobileSMS`、`tips` 三项，缺少 `com.apple.mobilecal` 的 `UNCSectionInfo` 记录。
  2. 通过 [`dsc.py`](../../hackios-xnu-kernel/tools/dsc/dsc.py) 反汇编 iOS 26（23G90）`UserNotificationsServer` 与 `UserNotificationsCore` 查明：iOS 26 上通知服务在 `SpringBoard` 进程内运行，`-[UNSDefaultDataProviderFactory _createDefaultDataProvidersForSourceDescriptions:]` 要求 `-[UNCNotificationSourceDescription useDefaultDataProvider]` 为真且（若 `-[UNCNotificationSourceDescription requiresTopics]` 为真则 `defaultTopics` 非空），否则把应用归入 `_restrictedSourceDescriptions` 并跳过创建 `UNSDefaultDataProvider` 与 `BBSectionInfo`，导致授权状态无法写入 `VersionedSectionInfo.plist`。
  3. `/System/Library/UserNotifications/Bundles/com.apple.mobilecal.bundle/Info.plist` 声明了 `UNRequiresTopics = true`，而其话题由 `calaccessd` 动态注册、`defaultTopics` 为空，导致 `MobileCal` 未能注册到 `BulletinBoard`。
- **修复**：
  - 在 [`userland/src/ax.m`](../../hackios-xnu-userland/userland/src/ax.m) 中移除先前的 `ax_suppress_notification_prompt()` 表象钩子，改为在 `SpringBoard` 进程内安装 `ax_enable_default_notification_provider()`：令 `-[UNCNotificationSourceDescription useDefaultDataProvider]` 返回 `YES`，并在 `defaultTopics` 为空时令 `-[UNCNotificationSourceDescription requiresTopics]` 返回 `NO`，使系统应用均正常创建 `UNSDefaultDataProvider` 并将用户点击「允许／不允许」后的 `UNCSectionInfo` 持久化写入 `/var/mobile/Library/BulletinBoard/VersionedSectionInfo.plist`。

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

## 2. 上游优化项与工程工具链跟进

对照[上游对照分析](../analysis/2026-11-05-upstream-lessons.md)与[上游 2/3/4 阶段对照分析](../analysis/2026-11-06-upstream-2-3-4-analysis.md)，当前状态与后续安排如下：

1. **已合入并完成图形验证项**：
   - 顶点着色器 CSO 缓存（`air_metal_vertex_cache.inc`，已修复深拷贝）、空纹理指针 phi 解析（`air_ptr_phi.inc`）、纹理视图 `swizzle`、`TbdsA2Xhf` 拼接快速路径、硬件 `crc32x`、增量编译时间戳夹紧与 `var_store` 64 MiB 增量同步均已在真机正常工作。
2. **待继续推进的上游性能与工具链项**：
   - 整屏 pass 逐 draw 计时与高频着色器特化（控制中心下拉与主屏翻页长帧治理）。
   - 跨开机着色器编译缓存（`/private/var/db/redwood-aircache` 与管线缓存随 `var_store` 持久化，消除冷启动首次打开控制中心／应用时的编译卡顿）。
   - Mesa `ir3` A8xx 补丁回移与 `SwapWait`／ACD 调优。

## 3. 外设与子系统继续适配队列

按既有规划继续推进各外设与系统能力适配：

- **蓝牙（第 3、4 步）**：已完成开启与 BLE 扫描（`bt=4`）；继续推进 BLE 外设配对、SE14 UART 3 Mbaud 提速（`0xFC48` 加 GENI 时钟）与蓝牙音频路由，见[蓝牙接入调研](../analysis/2026-11-02-bluetooth-bringup.md) §6、§8。
- **音量与音频输出**：音量键、HUD 提示框与控制中心音量滑块已接通（`AUDIO=1`）；继续推进 ADSP、AudioReach 与扬声器功放驱动出声，见[音量与声音输出调研](../analysis/2026-11-02-audio-and-volume.md)。
- **视频播放与硬件解码**：先实现 Metal 驱动两平面 YCbCr（`'420v'`）合成并在 `MobileSafari` 中打通 H.264／VP9 软解播放，再推进 SM8750 Iris VPU v3.5 固件加载、HFI gen2 与 VideoToolbox 硬解插件，见[视频解码调研](../analysis/2026-11-05-video-decode.md)。
- **相机**：提取主摄 OV50E `sensormodule` 配置，推进 CCI／CSIPHY／IFE 与 `cameracaptured` 接入，见[相机路线](camera-plan.md)。
- **手电与振动（iOS 26）**：排查 `rate7-def1` 中手电 `0x0018` 传输丢弃与振动故障寄存器 `0x10` 清除问题，恢复控制中心手电开关与系统触感反馈，见[手电与震动实测](../progress/2026-10-26-torch-and-haptics.md)。
- **充电状态与温控**：墙插充电器下验证 `annibale_battery.c` 防抖窗口，推进原生 `CLPC` 调频策略分析与复刻，见[路线图 §5.4](2026-10-26-roadmap.md#54-苹果原生策略分析与复刻clpc)。
- **天气、Safari 下载、蜂窝与 App Store**：修复 `weatherd` 依赖服务、Safari 下载文件移入「我的 iPhone」、蜂窝基带与 App Store 登录下载，见[总账跟踪](2026-10-23-tracking.md) §2。

## 4. Android 系统内 OTA 影响结论

已写入[双系统分区与持久化部署手册](dual-boot-setup.md) §5：

- 系统内 OTA（`update_engine`）不刷写 `gpt_both0.bin`，重启时 `resize.f2fs` 仅对齐 GPT 中 `userdata`（`sda34`）的边界，因此 `darwin`（`sda35`）与 `darwin_var`（`sda36`）分区及 iOS 数据完全保留。
- 增量 OTA 会因 `boot`／`init_boot` 已被修改而校验失败，日常更新应使用**完整包 OTA（Full ROM）**。
- 完整包 OTA 会将新版本 Android 写入当前闲置槽位（覆盖原 `xnuloader` 所在槽位的 `boot`）并在重启后切到新槽位；待新版本 Android 开机完成后台快照合并后，将 `xnuloader` 刷入退下来的新闲置槽位即可恢复双启动。
