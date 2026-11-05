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

### 1.4 进入设置子页面时背光短暂变暗再恢复（已修复并验证）

- **现象**：首次打开「设置」或点击进入子页面转场时，屏幕亮度会自主跳变或短暂降低再恢复。
- **根因**：
  1. 通过 [`dsc.py`](../../hackios-xnu-kernel/tools/dsc/dsc.py) 反汇编 iOS 26（23G90）`CoreBrightness` 框架（`SetLogicalBrightnessInternal` `0x1e2640e80`、`Display fade callback` `0x1e263c300`、`ScalerMax`／`ScalerMin` 限制斜坡 `0x1e26417dc`、`AAP` 斜坡 `0x1e2744e40`）并对照内核日志发现：`CoreBrightness` 每次更新亮度时都会同时向 `AppleARMBacklight` 下发 `brightness-nits` 并向 `IOMobileFramebuffer` 下发 `IOMFBBrightnessLevel`，转场期间还会夹杂非正数或 `< 65536` 的瞬态值（如 `404377` 对应 6.17 nits 或小于 1 nit 的过渡值）。
  2. 开机时 `backboardd` 通过 `DisplayBrightnessNitsNVRAM=9175040`（`140.000 nits`）下发 NVRAM 保存的初始亮度，[`MiniAppleARMBacklight.cpp`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniAppleARMBacklight.cpp) 原先未读取该键，面板保持在 loader 留下的 `0x35a`（约 55 nits）直到进入设置页才跳变。
  3. 用户在控制中心或「设置 → 显示与亮度」手动拖动滑块时，`CoreBrightness` 在每个触摸采样帧都会向 `AppleARMBacklight` 连续下发高频 `DisplayBrightness`（每 100 毫秒 30～70 次）及 `DisplayBrightnessSliderPosition`；而在进入「设置」子页面触发自主转场斜坡（`140.0 ↔ 168.0 nits` 或 `168.0 → 158.7 → 168.0 nits`）时，斜坡期间无连续 `DisplayBrightness` 事件。
- **修复**：在 [`MiniAppleARMBacklight.cpp`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniAppleARMBacklight.cpp) 中：
  1. `publish_calibration()` 发布 4 字节 `0` 的 `use-AAP`、`use-cabal` 与 `use-new-AAP-ramp` 属性。
  2. `bl_take()` 支持读取开机 `DisplayBrightnessNitsNVRAM` 立即应用初始亮度（`140.000 nits`），忽略 `IOMobileFramebuffer` 侧的 `IOMFBBrightnessLevel` 以及 `<= 0` 或 `1025..65535` 的瞬态异常值。
  3. 跟踪用户滑块活跃窗口（收到 `DisplayBrightnessSliderPosition` 或 250 毫秒内连续收到 `DisplayBrightness` 时开启 400 毫秒滑块窗口）；在非用户滑块窗口内，过滤变化幅度不超过 25% 的 `CoreBrightness` 自主转场微调斜坡，同时完整保留用户手动拖动滑块的平滑调光。
- **真机验证**：重新编译内核封装进 `boot_a` 重启实测，开机立即应用 `DisplayBrightnessNitsNVRAM=9175040`（`value 2310, 140.000 nits`）；进入「设置」及各子页面转场期间面板背光保持恒定，无闪烁或变暗。

### 1.5 日历（MobileCal）每次打开重复弹出通知权限申请（已修复并验证）

- **现象**：打开日历（`MobileCal`）弹出通知权限请求框，点击「允许」后关闭再重新打开日历，仍每次重复弹出同一权限申请。
- **根因**：
  1. [`tools/k90auto/package.py`](../../tools/k90auto/package.py) 生成根盘 `launchd.plist` 时仅在 `DYLD_INSERT_LIBRARIES` 中注入了 `libredwood.dylib`（仅作用于 `SpringBoard`），未注入通用应用辅助库 `libredwood-ax.dylib`（[`userland/src/ax.m`](../../hackios-xnu-userland/userland/src/ax.m)）；同时 `MobileCal` 启动时调用 `UNUserNotificationCenter` 的 `-requestAuthorizationWithOptions:completionHandler:`，因缺少 `usernotificationsd` 通知授权持久化而每次弹窗。
  2. [`var_store_delta.inc`](../../hackios-xnu-userland/userland/src/var_store_delta.inc) 中 `delta_reset()`、`delta_save()`、`delta_restore()` 原先判断 `if (store_at == 0 || slots <= 1)`，而 `/dev/rufs_dsu_store` 分区模式下 `STORE_AT` 恒为 `0`，导致增量保存被跳过；`delta_is_near_full()` 在 `fd == -1` 时直接调用 `delta_read_head()` 导致 `pread(-1)` 报 `Bad file descriptor`；且当 `delta_save()` 超过 64 MiB 增量上限触发 `out_flush(0)` 返回 `0` 时未回退调用 `save()` 合并基础槽位。
- **修复**：
  - [`tools/k90auto/package.py`](../../tools/k90auto/package.py)、[`userland/src/ax.m`](../../hackios-xnu-userland/userland/src/ax.m) 与 [`userland/src/inject_app.c`](../../hackios-xnu-userland/userland/src/inject_app.c)：将 `/redwood/lib/libredwood-ax.dylib` 纳入 `package.py` 的 `DYLD_INSERT_LIBRARIES`，为 `MobileCal` 绑定固定容器目录 `7DFA02CB-E0A8-4D3C-BF40-4E5F6A7B8C93`，并在 `ax_suppress_notification_prompt()` 中拦截 `UNUserNotificationCenter` 的 `-requestAuthorizationWithOptions:completionHandler:` 直接回调 `handler(YES, nil)`。
  - [`var_store_delta.inc`](../../hackios-xnu-userland/userland/src/var_store_delta.inc) 与 [`var_store_unpack.inc`](../../hackios-xnu-userland/userland/src/var_store_unpack.inc)：移除 `store_at == 0` 限制，在 `delta_is_near_full()` 中当 `fd < 0` 时临时打开 `DEVICE`，并在 `delta_save()` 超出 64 MiB 限制时自动调用 `save()` 合并写入基础槽位。
- **真机验证**：连续多次打开 `MobileCal` 截图确认，直接进入日历主视图，不再弹出通知权限申请框。

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
