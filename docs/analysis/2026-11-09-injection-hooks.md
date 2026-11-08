# 注入钩子清单

本文按[架构审查](2026-11-08-architecture-review.md) §17 的建议，列出 `boot_a` 镜像里每个注入库替换了哪些方法或函数，并按审查 §3.2 的三类用途归类：替换 iOS 期望由硬件供应商提供的类、纯诊断、测试辅助。三类之外的条目标为「待评估」，它们改变了 iOS 自身的行为或返回值，按 [AGENTS.md](../../AGENTS.md) 第 6 节应改到内核、驱动或构建层，或者确认后删除。清单来自 2026-11-09 打包产物的 `etc/inject.conf` 与 `userland/src/inject/` 源码，未逐条上机验证。

## 1. 注入范围

| 库 | 注入的进程 | 源码 |
|---|---|---|
| `libannibale-sbmetal-experiment.dylib` | SpringBoard、backboardd、iconservicesagent、MercuryPosterExtension | `sb_metal_experiment.m` 与 `sb_metal_*.inc` |
| `libannibale.dylib` | backboardd，仅在 `TOUCH_LAT=1` 打包时 | `inject.c` |
| `libannibale-sb26.dylib` | SpringBoard、PosterBoard、MercuryPosterExtension、Preferences、lsd、wifid | `inject_sb26*.c`、`inject_sb26_*.inc` |
| `libannibale-media.dylib` | cameracaptured、mediaserverd | `inject_media.c`，相机实现在 `userland/src/services/camera_device.c` |
| `libannibale-app.dylib` | 计算器、备忘录、提醒事项、日历、设置、信息、天气、地图、Safari 与 WebKit 进程等 | `inject_app.c`、`inject_app_network.inc` |
| `libannibale-ax.dylib` | SpringBoard、设置、Safari、天气、信息、备忘录、邮件、日历、文件 | `ax.m`、`statusbar26.m` |

## 2. 逐项归类

| 库 | 替换对象 | 源码中的用途说明 | 归类 |
|---|---|---|---|
| sbmetal-experiment | Metal 设备注册（`sb_metal_registration_sequence.inc` 等） | 让进程拿到本项目 Metal 驱动的设备 | 供应商类替换 |
| libannibale | `touch_lat=1` 时的主线程观察者 | 测量触摸到上屏的延迟，需要 `TOUCH_LAT=1` 打包 | 诊断 |
| sb26 | `-[SBLockScreenManager unlockUIFromSource:withOptions:]` 与 `com.annibale.unlock` 通知 | 主机自动解锁 | 测试辅助 |
| sb26 | `CHHapticEngine` 的能力查询与启停 | 报告无震动能力，启停直接返回 | 待评估：审查 §10.1 建议改为 HAL Actuator |
| sb26 | `SBPowerDownViewController`、`SBRestartManager`、`FBSystemService` 的关机方法 | 关机改走本项目的关机路径 | 待评估：关机应由内核 reboot 路径对齐 |
| sb26 | `-[SBLockdownManager _setupActivationState]` | 改写激活状态 | 待评估：改写系统状态 |
| sb26 | `-[SBIconImageView shouldForceBitmapImages]` | 没有 Metal 设备时强制位图图标 | 待评估：渲染层的替代路径 |
| sb26 | `SFAirDropDiscoveryController`、`AVOutputDeviceDiscoverySession`、`MRUMirroringController` | `awdl0` 缺失时返回离线结果 | 待评估：审查 §17 已列出 |
| sb26 | 日历图标 `iconLayerWithInfo:traitCollection:options:` | 图标图层取不到时的替代图层 | 待评估：渲染层的替代路径 |
| sb26 | `SBApplication`、`SBIcon`、`FBSBundleInfo`、`LSBundleRecord`、`LSApplicationProxy` 的显示名，`CFBundleCopyBundleLocalizations` | 从 `InfoPlist.loctable` 取中文名 | 待评估：审查 §12.4 的语言问题 |
| sb26 | `MGCopyAnswer` | 设置与 SpringBoard 查询 `DiskUsage` 时，总容量取 `kern.annibale.darwin_bytes` 与 `kern.annibale.darwin_var_bytes`，可用空间取 `/private/var` 的 `statfs` | 待评估：替换了 MobileGestalt 的回答 |
| sb26 | `SBApplicationController` 卸载方法、`isDeletable`、`isUninstallSupported` | 桌面删除应用改由本项目的安装器处理 | 待评估：应用管理 |
| sb26 | `inject_sb26_rate.c`、`inject_sb26_layers.c` | 帧率与图层导出 | 诊断 |
| media | `BWFigCaptureDeviceVendor` 等相机类 | 提供 FigCaptureDevice | 供应商类替换 |
| app | `posix_spawn`、文件复制、网络任务完成回调 | 记录应用退出原因与网络任务结果后调用原实现 | 诊断 |
| app | `-[WKPreferences init]` | 在 Safari 与 WebKit 进程打开 VP9 | 待评估：改变 WebKit 偏好 |
| ax | `com.annibale.ax` 通知时导出界面元素 | 主机按名字定位控件 | 测试辅助 |
| ax | 状态栏 `cutoutLayoutGuide` | 无灵动岛时把时间与电量向屏幕边缘移动 | 待评估：界面布局放在测试辅助库里，只在注入的进程生效 |

## 3. 结论

- 审查 §3.2 建议诊断与测试类注入不进 `boot_a` 镜像。按上表，`libannibale-ax.dylib` 属于测试辅助，却随默认镜像注入 9 个进程；其中的状态栏布局是用户可见行为，需要先拆出来再决定去留。
- `inject.c` 的窗口服务器与亮度钩子按 iOS 16.5（20F66）的地址校验，23G90 上这些地址落在 GeoServices 里，校验不通过，钩子不安装。默认镜像因此不再把 `libannibale.dylib` 注入 backboardd，真机开机到桌面、触摸翻页正常。
- `inject.c` 原有的 `+[MCMUserIdentityCache personasAreSupported]` 钩子只在 containermanagerd 里安装，iOS 26 镜像不把库注入这个进程，开机也已补齐 persona，本轮已删除。
- 待评估项按审查 §19 的优先级排期，每项改到对应层之后从本表删去。
