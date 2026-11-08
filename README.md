# hackios-redmi-k90-annibale — REDMI K90 上的 iOS 26

把 [HackiOS](https://github.com/oosexgang/hackios-xnu-kernel)（XNU + 未修改的 iOS 用户态）移植到 **REDMI K90（SM8750，代号 `annibale`）**。真机运行未修改的 iOS 26.6.2（23G90，取自 iPhone 17）和本项目维护的 XNU 12377 内核，Android 保留在另一个槽位，随时可以切回。项目仍在实验阶段，目前只在一台 K90 上验证过，其他机型需要独立移植。

## 1. 当前进展

| 方面 | 状态 |
|---|---|
| 桌面与系统应用 | 开机进入简体中文锁屏与主屏；壁纸、图标、日历与天气小组件、控制中心、通知中心可用；设置、Safari、短信、计算器、备忘录、提醒事项等系统应用能打开，文件 App 里有「我的 iPhone」 |
| 双系统与磁盘持久化 | 从机身存储划出 iOS 系统盘与数据盘；开机菜单选择进入 iOS 26 或 Android，不需要连电脑；系统设置、主屏布局、已安装应用与用户数据实时保存 |
| 图形与显示 | Metal 驱动经 Mesa freedreno 在 Adreno 830 上绘制；按 iPhone 17 的 1206×2622 分辨率渲染并适配 120 Hz 屏幕 |
| 屏幕亮度 | 控制中心与「设置 → 显示与亮度」的滑块直接调节屏幕背光 |
| 触摸与按键 | 触摸、电源键、音量键可用；音量键和控制中心的滑块能调音量，还没有声音 |
| Wi-Fi 与蓝牙 | 在「设置 → Wi-Fi」中加入网络后可用 Safari 上网；蓝牙支持扫描、发现与连接外设 |
| 安装应用 | 预装「安装包管理器」，可以安装、启动与卸载已解密的 `.ipa` 应用 |
| 电池与温控 | 显示电量与充电状态；处理器和 GPU 按负载调频，过热时逐档降频 |
| 未完成 | 蓝牙音频、声音输出、摄像头、蜂窝网络、App Store；网页视频播放与天气数据请求正在排查修复；手电与振动在 iOS 26 上还不能用 |

性能：在 120 Hz 屏上，主屏翻页约 90～100 帧／秒，控制中心下拉约 90～94 帧／秒；GPU 最高 1100 MHz，测试期间 GPU 温度最高约 57 °C。

最新状态和实测数据以[总账](docs/plan/2026-10-23-tracking.md)为准，验收目标见[路线图](docs/plan/2026-10-26-roadmap.md)。

## 2. 体验

从 [Releases](https://github.com/iola1999/hackios-redmi-k90-annibale/releases) 下载预构建包，按[体验说明](docs/user-guide.md)在自己的电脑上合成引导镜像，再写入手机。整个过程不需要 Xcode 和 Docker。

- 手机：已解锁 bootloader 并获取 root 的 REDMI K90。
- 电脑：macOS 或 Linux，装有 Python 3、7-Zip、`adb` 与 `fastboot`。
- 首次安装要从 Android 的 `userdata` 划出 iOS 系统盘（16 GiB）和数据盘（大小自选），写分区前请先备份个人数据。

体验说明第 1 节有一段提示词，可以直接交给 AI Agent。它会按说明逐步检查和准备，写分区或刷机前先等你确认。

## 3. 开发

从源码构建内核、用户态和引导镜像需要 Mac（Xcode）和 Docker，步骤见[开发指南](docs/development.md)，出 Release 的流程也在其中。排查前先读[排查与协作手册](docs/plan/debugging-and-collaboration.md)和[真机调试手册](docs/plan/device-test-playbook.md)。

- `docs/plan/`：操作手册与计划；`docs/analysis/`：调研与分析；`docs/progress/`：真机运行记录。
- `tools/`：主机脚本，无人值守测试见 [k90auto 说明](tools/k90auto/README.md)，出 Release 与本地合成见 `tools/release/`。

## 4. 仓库

| 仓库 | 内容 | 分支 |
|---|---|---|
| [hackios-redmi-k90-annibale](https://github.com/iola1999/hackios-redmi-k90-annibale) | 本仓库：文档、脚本，以及两个子模块的版本 | `main` |
| [hackios-xnu-kernel](https://github.com/iola1999/hackios-xnu-kernel) | XNU、loader、Metal 驱动 | `k90-port` |
| [hackios-xnu-userland](https://github.com/iola1999/hackios-xnu-userland) | 用户态适配、镜像与图形工具 | `k90-port` |
| [hackios-mu-silicium](https://github.com/iola1999/hackios-mu-silicium) | loader 镜像里的 annibale UEFI（Mu-Silicium 副本，单独克隆） | `k90-port` |

本项目基于 [OOSEX GANG](https://github.com/oosexgang) 的 HackiOS 内核与用户态仓库，感谢原作者开放 XNU 移植、loader、用户态适配和图形工具。UEFI 基于 [Project Silicium](https://github.com/Project-Silicium) 的 Mu-Silicium。原有许可证和版权声明保留在各仓库中。仓库和 Release 都不含 iOS 文件与手机厂商固件，这些由使用者从自己的 IPSW 和手机中取得。
