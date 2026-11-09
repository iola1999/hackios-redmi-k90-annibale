# 架构总览

本文列出 K90 移植的分层、每层的代码位置与入口，以及各层之间的接口。各子系统的根因分析和真机读数见对应的 analysis 与 progress 文档。修复落在哪一层按 [AGENTS.md](../../AGENTS.md) 第 6 节执行：在内核、驱动或构建层补齐 iOS 原生框架期望的底层行为。

## 1. 分层

| 层 | 位置 | 职责 | 入口 |
|---|---|---|---|
| 引导 | `hackios-xnu-kernel/xnuloader/`、Mu-Silicium UEFI（`k90-port` 分支） | 驻留 loader：槽位与 GPT 维护、载荷装载、USB 命令、日志与截图 | `xnuloader/loader.c`、`platform_private.h`、`slot_choice.h` |
| 内核平台层 | `hackios-xnu-kernel/xnu/files/osfmk/arm64/`、`xnu/files/pexpert/`、`xnu26/patches/` | SoC 启动、中断、PSCI、返回 loader、对 Apple 文件的改动 | `loader_return.c`、`psci_smp.c`、`gic_v3_irq.c` |
| 内核设备驱动 | `xnu/files/bsd/dev/adreno8/`、`bsd/dev/annibale/`、`bsd/dev/mhi/` | GPU、触摸、按键、电池、音频 DSP、蓝牙、Wi-Fi、UFS、手电、震动 | 各驱动的 `*_init()`，由启动参数选择 |
| IOKit 服务 | `xnu/files/iokit/Kernel/Mini*.cpp`、`Annibale*.cpp` | 面板、IOSurface、背光、密钥库、网络栈、GPU、电池、蓝牙、WLAN 的服务树 | `MiniDrivers.h` |
| 文件系统与持久化 | `xnu/files/bsd/miscfs/ramfs/`、`bsd/miscfs/apfs/`、`bsd/dev/annibale/annibale_ufs*` | `/private/var` 的 `ANNFS001` 直写、UFS 块设备、APFS 只读 | `ramfs.c`、`ramfs_disk.inc` |
| 启动用户态 | `hackios-xnu-userland/userland/src/boot/` | `stage0` 挂载辅助盘，`init` 挂载系统卷并切根 | `stage0.c`、`init.c` |
| 用户态图形驱动 | `hackios-xnu-kernel/tools/userland-driver/`、`hackios-xnu-userland/tools/mesa/` | Metal 接口到 Adreno 命令流，AIR 到 NIR 的翻译 | `annibalemetal.m`、`tools/mesa/air/air_metal.c` |
| HAL 与服务 | `userland/src/services/` | 音频 HAL 插件、相机、输入、蓝牙工具 | `audio_plugin.c`、`input26_service.c`、`camera_device.c` |
| 注入库 | `userland/src/inject/` | 替换 iOS 期望由硬件供应商提供的类，诊断与测试辅助 | `inject.c`、`inject_sb26.c` |
| 应用与安装器 | `TrollStore/`、`userland/src/apps/` | `TrollStore.app`、`trollstorehelper` 与控制端工具 | `TrollStore/RootHelper/main.m`、`annsh.c`、`anntouch.c` |
| 构建与打包 | `userland/build.sh`、`tools/k90auto/package.py`、`tools/release/` | 根盘基线、Metal 驱动与注入库编译、任务缓存、根盘镜像、Release | 见[开发指南](../development.md) |
| 主机自动化 | `tools/k90auto/` | 起轮、截图、统计、复位 | 见 [k90auto 说明](../../tools/k90auto/README.md) |

## 2. 启动链

1. 高通 LK 从 `boot_a` 启动 Mu-Silicium UEFI，UEFI 启动载荷里的 `loader.efi`。loader 识别自身槽位，选择 iOS 或另一侧的 Android，见[引导目标切换 SOP](device-boot-target-sop.md)。
2. loader 把启动卷发布为 `md0`、辅助盘发布为 `md1`，启动内核。
3. `stage0` 把 `md1` 挂载到 `/annibale`，执行 `/annibale/sbin/init`。`init` 从 `/dev/ufs_darwin` 只读挂载系统卷，准备启动任务与驱动挂载点，再通过 `kern.annibale_switch_root` 切换根目录。
4. `/private/var` 由内核持久化层直接读写 `darwin_var` 分区。

各步骤的参数与验证结果见[根文件系统](../analysis/rootfs-strategy.md)，分区与部署见[双系统分区与持久化部署手册](dual-boot-setup.md)。

## 3. 层间接口

- loader 与内核：载荷容器（`xnuloader/mkpayload.py`）、启动参数、设备树，以及 loader 常驻区里的电池缓存。
- 内核与用户态：设备节点 `/dev/annibale-*`、`kern.annibale.*` sysctl、IOKit 服务与属性。用户态头文件 `userland/src/services/annibale_*.h` 是内核 `bsd/sys/` 同名头文件的副本，两边需要同步修改。
- 用户态与 iOS：`AnnibaleMetal.bundle` 与 `AnnibaleAudio.driver` 通过 `init` 绑定到系统卷的 `/System/Library/Extensions` 与 HAL 插件目录；任务缓存 `xpc/launchd.plist` 由 `package.py` 生成。

## 4. 专题文档

- GPU：[A830 命令执行](../analysis/2026-10-24-a830-command-startup.md)、[GPU 桌面记录](../progress/2026-10-26-gpu-desktop-acceleration.md)。
- 桌面与性能：[可用桌面记录](../progress/2026-10-30-ios26-usable-desktop.md)、[开机次序与性能](../progress/2026-10-31-boot-order-and-performance.md)。
- 硬件资源：[硬件资源图谱](../analysis/annibale-hw-map.md)。
- 架构审查与建议：[2026-11-08 架构审查](../analysis/2026-11-08-architecture-review.md)。
