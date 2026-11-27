# hackios-redmi-k90-annibale — REDMI K90 上的 iOS 26

把 [HackiOS](https://github.com/oosexgang/hackios-xnu-kernel)（XNU + 未修改的 iOS 用户态）移植到 **REDMI K90（SM8750，代号 `annibale`）**。真机运行未修改的 iOS 26.6.2（23G90，取自 iPhone 17）和本项目维护的 XNU 12377 内核，Android 保留在另一个槽位，随时可以切回。项目仍在实验阶段，目前只在一台 K90 上验证过，其他机型需要独立移植。

## 1. 当前进展

| 方面 | 状态 |
|---|---|
| 桌面与系统应用 | 简体中文锁屏、主屏、控制中心、通知中心、设置、Safari、电话、短信、照片、备忘录、提醒事项与钱包可用，日历等基础组件正常显示，通知中心与锁屏壁纸黑屏及边缘黑带已修复；天气城市列表 4 张卡片已恢复深靛蓝夜空显示，全屏详情页渐变遮罩与桌面天气小组件仍在排查 |
| 双系统与数据 | 开机菜单选择 iOS 或 Android，无需连接电脑；独立系统与数据分区支持持久化设置、故障回溯与已安装应用跨重启保留 |
| 图形与显示 | Metal 经 Mesa freedreno 在 Adreno 830 上硬件渲染（`1206×2622`、`120 Hz`），系统应用、地图与相册网格正常显示；Safari 多标签概览偶现局部显示异常，GPU 出错恢复仍在完善 |
| 亮度与手电筒 | 系统亮度滑块、跨重启亮度恢复与手电筒档位调节可用 |
| 触摸与按键 | 触摸、电源键、音量键及自动锁屏计时可用 |
| 声音 | 双扬声器出声、充电提示音、AAC 本地播放、HLS 流媒体音频与内置麦克风录音可用，音频播放期间音量键调节已生效；独立音量展示路径与蓝牙音频仍在完善 |
| 网络与无线 | Wi-Fi 支持导入本机出厂地址、联网与自动重连，蓝牙支持外设扫描；显式断开后的 Wi-Fi 自动重连、蓝牙配对与音频、蜂窝移动网络与卫星定位仍在开发中 |
| 相机 | 前后摄实时预览、前后摄物理切换与默认上下正立、前摄常规拍照、对焦、曝光补偿、闪光灯拍照、后摄连拍与照片保存可用，已接入后摄对焦马达按需单次供电与软着陆（真机听感待终验）；前摄人像模式暂不可用，复杂光线成像仍在调优 |
| 视频与网页 | H.264 与 HEVC 10-bit 硬件解码、Safari 网页浏览与网页内静音视频播放可用；带音频网页视频冷启动播放偶发失败 |
| 安装应用 | 预装 TrollStore，支持通过电脑或浏览器下载后在系统内安装解密的 `.ipa`／`.tipa` 应用 |
| 电池与温控 | 支持电量与充电状态显示、处理器与 GPU 动态调频及过热降频；连续高负载交互仍有温控限频，深度休眠节能仍在推进 |

最新版本为 [v0.2.4](https://github.com/iola1999/hackios-redmi-k90-annibale/releases/tag/v0.2.4)（2026-11-28），重点修复前后摄物理切换与默认正立、后摄对焦马达按需供电与软着陆、通知中心与锁屏壁纸亮屏、天气城市列表夜空渲染、`rwa_lock` 解耦与 `nircache`、材质回归 18/18 通过、蓝牙 `BT_EN` 硬复位及 FastRPC `apps_smmu`。从 `v0.2.3` 升级只需重新合成并刷入 `boot-ios.img`，从 `v0.2.0`～`v0.2.2` 升级需补采 `wifi-mac` 并重新合成刷入，更早版本需先按 `v0.2.0` 发布说明迁移数据盘，完整更新日志见各版 [Releases](https://github.com/iola1999/hackios-redmi-k90-annibale/releases) 说明。

详细开发追踪与实测记录见[进度表](docs/plan/2026-10-23-tracking.md)、[待办目录](docs/backlog/README.md)、[架构总览](docs/plan/architecture.md)与[路线图](docs/plan/2026-10-26-roadmap.md)。原生 FairPlay 与 App Store 不列入项目目标，离线解密后经 `TrollStore` 安装的可行性评估见[FairPlay 与 App Store 可行性调研](docs/analysis/2026-11-27-fairplay-appstore-feasibility.md)。

## 2. 体验

从 [Releases](https://github.com/iola1999/hackios-redmi-k90-annibale/releases) 下载预构建包，按[体验说明](docs/user-guide.md)在自己的电脑上合成引导镜像，再写入手机。整个过程不需要 Xcode 和 Docker。

- 手机：已解锁 bootloader 并获取 root 的 REDMI K90。
- 电脑：macOS 或 Linux，装有 Python 3、7-Zip、`adb` 与 `fastboot`。
- 首次安装要从 Android 的 `userdata` 划出 iOS 系统盘（16 GiB）和数据盘（大小自选），写分区前请先备份个人数据。

体验说明第 1 节有一段提示词，可以直接交给 AI Agent。它会按说明逐步检查和准备，写分区或刷机前先等你确认。

## 3. 开发

从源码构建内核、用户态和引导镜像需要 Mac（Xcode）和 Docker，步骤见[开发指南](docs/development.md)，生成 Release 的流程也在其中。排查前先读[排查与协作手册](docs/plan/debugging-and-collaboration.md)和[真机调试手册](docs/plan/device-test-playbook.md)。

- [文档入口](docs/README.md)：[待办与候选](docs/backlog/README.md)、操作手册与执行计划（`docs/plan/`）、调研与实测（`docs/analysis/`）、运行记录（`docs/progress/`）。
- `tools/`：主机脚本，无人值守测试见 [k90auto 说明](tools/k90auto/README.md)，生成 Release 与本地合成见 `tools/release/`。

## 4. 仓库

| 仓库 | 内容 | 分支 |
|---|---|---|
| [hackios-redmi-k90-annibale](https://github.com/iola1999/hackios-redmi-k90-annibale) | 本仓库：文档、脚本，以及两个子模块的版本 | `main` |
| [hackios-xnu-kernel](https://github.com/iola1999/hackios-xnu-kernel) | XNU、loader、Metal 驱动 | `k90-port` |
| [hackios-xnu-userland](https://github.com/iola1999/hackios-xnu-userland) | 用户态适配、镜像与图形工具 | `k90-port` |
| [TrollStore](https://github.com/iola1999/TrollStore) | TrollStore 应用安装器与 `trollstorehelper`（iOS 26 / K90 移植分支） | `k90-port` |
| [hackios-mu-silicium](https://github.com/iola1999/hackios-mu-silicium) | loader 镜像里的 annibale UEFI（Mu-Silicium 副本，单独克隆） | `k90-port` |

本项目基于 [OOSEX GANG](https://github.com/oosexgang) 的 HackiOS 内核与用户态仓库，感谢原作者开放 XNU 移植、loader、用户态适配和图形工具。UEFI 基于 [Project Silicium](https://github.com/Project-Silicium) 的 Mu-Silicium。原有许可证和版权声明保留在各仓库中。仓库和 Release 都不含 iOS 文件与手机厂商固件，这些由使用者从自己的 IPSW 和手机中取得。

顶层仓库的原创脚本和文档采用 MIT 许可证。分发副本或实质性部分时，须保留版权声明和许可声明。三个子模块和第三方材料的许可见各自的版权文件。[顶层许可证](LICENSE)
