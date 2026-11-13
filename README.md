# hackios-redmi-k90-annibale — REDMI K90 上的 iOS 26

把 [HackiOS](https://github.com/oosexgang/hackios-xnu-kernel)（XNU + 未修改的 iOS 用户态）移植到 **REDMI K90（SM8750，代号 `annibale`）**。真机运行未修改的 iOS 26.6.2（23G90，取自 iPhone 17）和本项目维护的 XNU 12377 内核，Android 保留在另一个槽位，随时可以切回。项目仍在实验阶段，目前只在一台 K90 上验证过，其他机型需要独立移植。

## 1. 当前进展

| 方面 | 状态 |
|---|---|
| 桌面与系统应用 | 简体中文锁屏、主屏、控制中心与通知中心可用；设置、Safari 等系统应用能打开，小组件仍有显示异常 |
| 双系统与数据 | 开机菜单选择 iOS 或 Android，无需连接电脑；已安装应用与文件跨正常重启保留 |
| 图形与显示 | Metal 经 Mesa freedreno 在 Adreno 830 上绘制；画布为 1206×2622，刷新配置为 120 Hz |
| 亮度与手电筒 | 系统亮度滑块可调节背光；手电筒及其亮度调节可用 |
| 触摸与按键 | 触摸、电源键和音量调节可用；尚无声音输出 |
| Wi-Fi 与蓝牙 | Wi-Fi 可联网、保存网络并在开机后自动连接；蓝牙可扫描外设 |
| 相机 | 相机能打开，预览黑屏 |
| 视频与网页 | H.264 离线硬解完成 270 帧，连续播放仍未通过；Safari 正文与视频仍有异常 |
| 安装应用 | 预装 TrollStore，支持安装和管理已解密的 `.ipa`／`.tipa` 应用 |
| 电池与温控 | 显示电量与充电状态；处理器和 GPU 按负载调频，过热时逐档降频 |

性能数据来自不同测试轮次：

- [11-08 手势测试](docs/progress/2026-11-08-performance-regression.md#2-五轮结果)：固定翻页约 92.5 帧／秒，按拷贝完成间隔计算。
- [11-09 静置测试](docs/progress/2026-11-09-thermal-and-pipeline-optimization.md#3-分项实施与验证记录)：桌面静置 14 分钟后，CPU 38.4～39.1 °C、GPU 40.5 °C。

[v0.1.3](https://github.com/iola1999/hackios-redmi-k90-annibale/releases/tag/v0.1.3) 人工体验反馈性能较好、渲染错误减少，当前版本的持续交互帧率仍待复测。

最新状态和实测数据以[进度表](docs/plan/2026-10-23-tracking.md)为准，未完成事项与候选方向见[待办目录](docs/backlog/README.md)，架构分层见[架构总览](docs/plan/architecture.md)，验收目标见[路线图](docs/plan/2026-10-26-roadmap.md)。

FairPlay 与 App Store 不作为项目目标。

## 2. 体验

从 [Releases](https://github.com/iola1999/hackios-redmi-k90-annibale/releases) 下载预构建包，按[体验说明](docs/user-guide.md)在自己的电脑上合成引导镜像，再写入手机。整个过程不需要 Xcode 和 Docker。

- 手机：已解锁 bootloader 并获取 root 的 REDMI K90。
- 电脑：macOS 或 Linux，装有 Python 3、7-Zip、`adb` 与 `fastboot`。
- 首次安装要从 Android 的 `userdata` 划出 iOS 系统盘（16 GiB）和数据盘（大小自选），写分区前请先备份个人数据。

体验说明第 1 节有一段提示词，可以直接交给 AI Agent。它会按说明逐步检查和准备，写分区或刷机前先等你确认。

## 3. 开发

从源码构建内核、用户态和引导镜像需要 Mac（Xcode）和 Docker，步骤见[开发指南](docs/development.md)，出 Release 的流程也在其中。排查前先读[排查与协作手册](docs/plan/debugging-and-collaboration.md)和[真机调试手册](docs/plan/device-test-playbook.md)。

- [文档入口](docs/README.md)：[待办与候选](docs/backlog/README.md)、操作手册与执行计划（`docs/plan/`）、调研与实测（`docs/analysis/`）、运行记录（`docs/progress/`）。
- `tools/`：主机脚本，无人值守测试见 [k90auto 说明](tools/k90auto/README.md)，出 Release 与本地合成见 `tools/release/`。

## 4. 仓库

| 仓库 | 内容 | 分支 |
|---|---|---|
| [hackios-redmi-k90-annibale](https://github.com/iola1999/hackios-redmi-k90-annibale) | 本仓库：文档、脚本，以及两个子模块的版本 | `main` |
| [hackios-xnu-kernel](https://github.com/iola1999/hackios-xnu-kernel) | XNU、loader、Metal 驱动 | `k90-port` |
| [hackios-xnu-userland](https://github.com/iola1999/hackios-xnu-userland) | 用户态适配、镜像与图形工具 | `k90-port` |
| [TrollStore](https://github.com/iola1999/TrollStore) | TrollStore 应用安装器与 `trollstorehelper`（iOS 26 / K90 移植分支） | `k90-port` |
| [hackios-mu-silicium](https://github.com/iola1999/hackios-mu-silicium) | loader 镜像里的 annibale UEFI（Mu-Silicium 副本，单独克隆） | `k90-port` |

本项目基于 [OOSEX GANG](https://github.com/oosexgang) 的 HackiOS 内核与用户态仓库，感谢原作者开放 XNU 移植、loader、用户态适配和图形工具。UEFI 基于 [Project Silicium](https://github.com/Project-Silicium) 的 Mu-Silicium。原有许可证和版权声明保留在各仓库中。仓库和 Release 都不含 iOS 文件与手机厂商固件，这些由使用者从自己的 IPSW 和手机中取得。
