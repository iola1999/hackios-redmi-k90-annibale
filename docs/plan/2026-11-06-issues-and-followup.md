# 2026-11-06 开机后实测问题与后续跟进清单

本文记录 2026-11-06 `boot_a` 独立双系统引导进入 iOS 26 桌面后，用户在真机交互中反馈的 5 项界面／功能问题，以及上游优化借鉴、外设继续适配与 Android OTA 影响的跟进安排。总账入口见[总账跟踪](2026-10-23-tracking.md)。

## 1. 待排查的 5 项实测问题

### 1.1 控制中心与底部 Dock 图形渲染异常、控制中心亮度条不可见

- **现象**：
  - 控制中心左上连接块、右上媒体块、方向锁定、静音、计算器、相机、屏幕镜像、扫码按钮外围出现不透明白底／浅灰底矩形方框，圆角外区域未被裁剪或混合异常。
  - 控制中心亮度胶囊与音量胶囊外框可见，调节亮度滑块能改变屏幕实际背光，但亮度胶囊内部的白色填充条不显示。
  - 主屏底部 Dock 栏背景外围出现矩形边界框。
- **怀疑方向**：跟进上游改动（内核仓库 `1b3e2b6` 的 `tools/userland-driver/redwoodmetal.m` 单采样 `MTLStoreActionMultisampleResolve` 改为 `endEncoding` 阶段 `rw_record_resolve_blits`、纹理视图 `swizzle` 传递、`TbdsA2Xhf` 拼接快速路径、管线回退 `rw_fallback_render_create`，或用户态仓库 `263e886` 的 `tools/mesa/air/` 空纹理指针 phi 解析、顶点 CSO 缓存、纹理 swizzle 与 `A8_UNORM` 通道映射）引入的混合／采样／Resolve 退化。
- **排查计划**：
  1. 对照 `1b3e2b6` 前后的 `redwoodmetal`（重点检查单采样 `MTLStoreActionMultisampleResolve` 重定向与 `rw_record_resolve_blits`、纹理 `swizzle`）以及 `263e886` 前后的 `libredwoodair.dylib`（重点检查 `A8_UNORM` 采样 swizzle 与 `air_ptr_phi.inc`）。
  2. 通过二分或逐项回退编译 `libredwoodmetal.dylib`／`libredwoodair.dylib`，在真机控制中心与主屏 Dock 截图验证。

### 1.2 设置页总容量显示 0 KB、可用 2.61 GB

- **现象**：「设置 → 通用 → 关于本机／储存空间」中总容量显示为 `0 KB`，可用容量显示为 `2.61 GB`。
- **怀疑方向**：
  - 根文件系统 `/`（`md0`，`system26.apfs`）与 `/private/var`（ramfs 或 `darwin_var`）的 `statfs`／`getattrlistbulk` 块数上报，或 `diskspaced`／`CacheDelete`／`StorageSettings` 读取的 IOKit 存储介质属性缺失总字节数。
  - 检查 `userland/src/inject_sb26.c` 注入 `Preferences` 后的存储容量钩子是否命中当前 iOS 26（23G90）查询路径。
- **排查计划**：抓取打开「关于本机」与「iPhone 储存空间」时的系统调用与日志，定位 `Preferences` 读取总容量的接口并修正返回值。

### 1.3 设置页一级列表图标全部缺失

- **现象**：打开「设置」（`Preferences`）主列表时，各设置项左侧图标全部空白。
- **怀疑方向**：
  - `iconservicesagent` 渲染设置列表小图标时使用的纹理视图 swizzle、单采样 Resolve 或 `ISImageDescriptor` 缓存路径受 `1b3e2b6`／`263e886` 改动影响，或 `var_store` 恢复的旧 `/private/var/containers/Shared/SystemGroup/.../com.apple.iconservices.store` 缓存包含软件渲染时期残留的空位图。
- **排查计划**：检查内核日志中 `iconservicesagent` 与 `Preferences` 的报错及 `redwoodmetal[iconservicesagent]` 的管线／纹理输出，对比清理 iconservices 缓存与回退驱动改动后的图标显示。

### 1.4 进入设置子页面时背光短暂变暗再恢复

- **现象**：在「设置」中点击进入子页面转场时，屏幕亮度会先降低一下再恢复。
- **怀疑方向**：日志显示转场期间 `backboardd` 连续下发 `IOMFBBrightnessLevel=2093882`（31.95 nits）、`404377`（6.17 nits）随后又回到原值；需核对 [`MiniAppleARMBacklight.cpp`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniAppleARMBacklight.cpp) 在 `1b3e2b6` 中新增的滑块防抖逻辑与 [`MiniFramebufferDCS.inc`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferDCS.inc) 处理 `IOMFBBrightnessLevel`／`DisplayBrightness` 瞬态低值时的过滤条件。
- **排查计划**：复盘 `/tmp/k90_cc.log` 中 `03:01:17`～`03:01:19` 的 `MiniAppleARMBacklight` 与 `dcs:` 时间线，拦截非用户拖动滑块触发的瞬态低尼特跳变。

### 1.5 日历（MobileCal）每次打开重复弹出通知权限申请

- **现象**：打开日历（`MobileCal`）弹出通知权限请求框，点击「允许」后关闭再重新打开日历，仍每次重复弹出同一权限申请。
- **怀疑方向**：
  - `usernotificationsd` 或 `tccd` 保存通知授权状态的路径（`/private/var/mobile/Library/UserNotifications` 或 `/private/var/mobile/Library/TCC/TCC.db`）目录缺失、权限不对，或 `usernotificationsd` 未在 launchd 缓存中按需拉起／写入失败。
  - `inject_app.c`／`inject_sb26.c` 对通知中心代理方法做了拦截但未持久化已授权状态。
- **排查计划**：抓取点开日历并点击「允许」时的 `usernotificationsd`、`tccd`、`SpringBoard` 与 `MobileCal` 日志，补齐对应目录或修复通知权限持久化链路。

## 2. 上游优化项与工程工具链跟进

对照[上游对照分析](../analysis/2026-11-05-upstream-lessons.md)与[上游 2/3/4 阶段对照分析](../analysis/2026-11-06-upstream-2-3-4-analysis.md)，逐项核对尚未落地或需验证的优化与工程做法：

1. **已合入待验证／调优项**：
   - `1b3e2b6` 与 `263e886` 已合入顶点着色器 CSO 缓存（`air_metal_vertex_cache.inc`）、空纹理指针 phi 解析（`air_ptr_phi.inc`）、`TbdsA2Xhf` 拼接快速路径、硬件 `crc32x`、增量编译时间戳夹紧与 `var_store` 增量同步；需先排查解决 §1.1 與 §1.3 的图形退化，再实测手势帧率收益。
2. **待继续推进的上游性能与工具链项**：
   - 整屏 pass 逐 draw 计时与高频着色器特化（控制中心下拉与主屏翻页长帧治理）。
   - 跨开机着色器编译缓存（`/private/var/db/redwood-aircache` 与管线缓存随 `var_store` 持久化，消除冷启动首次打开控制中心／应用时的编译卡顿）。
   - Mesa `ir3` A8xx 补丁回移与 `SwapWait`／ACD 调优。
   - 工程链路：保持 [`mkstandalone.py`](../../hackios-xnu-kernel/xnuloader/mkstandalone.py) 与 [`tools/k90auto/package.py`](../../tools/k90auto/package.py) 产物校验一致，防止旧构建产物混入独立引导镜像。

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
