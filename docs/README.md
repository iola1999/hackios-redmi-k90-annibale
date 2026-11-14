# 文档入口

项目概况见[仓库 README](../README.md)，维护规则见 [AGENTS.md](../AGENTS.md)。本文按用途和主题索引项目文档；专题中的版本、日期与验证范围决定其适用条件，设备操作以当前手册为准。

## 1. 当前进展、任务与决策

- [进度表](plan/2026-10-23-tracking.md)：项目状态与已完成里程碑。
- [待办与候选](backlog/README.md)：按系统、图形、多媒体、外设、工程分类选择任务。
- [系统后续事项](plan/2026-11-12-system-followup.md)：当前系统批次的执行安排。
- [性能与原生硬件对齐改造方案（2026-11-14）](plan/2026-11-14-performance-and-native-alignment-plan.md)：全仓 18 项过渡方案与性能瓶颈的具体架构设计和分批切分。
- [架构总览](plan/architecture.md)：代码分层、接口与职责。
- [路线图](plan/2026-10-26-roadmap.md)：系统与图形路线选择、约束和验收目标。
- [11-05 用户确认的方向](plan/2026-11-05-next-work.md)：原始要求与后续结果入口。
- [相机设计与硬件资源](plan/camera-plan.md)：早期设计依据，当前结果与待办由文内链接维护。

## 2. 使用、开发与设备操作

- [体验说明](user-guide.md)：Release 合成、安装与日常使用。
- [开发指南](development.md)：源码构建、打包与发布。
- [容器环境](../docker/README.md)：容器承担的构建步骤和环境要求。
- [k90auto 工具说明](../tools/k90auto/README.md)：主机工具的参数、产物与运行方法。
- [分区备份与恢复](backup/README.md)。
- [双系统分区与持久化部署](plan/dual-boot-setup.md)。
- [引导目标切换 SOP](plan/device-boot-target-sop.md)。
- [真机调试手册](plan/device-test-playbook.md)。
- [真机轮运行规则](plan/k90auto-run-protocol.md)。
- [排查与协作手册](plan/debugging-and-collaboration.md)。
- [经验整理 Prompt](plan/experience-review-prompt.md)。

## 3. 构建、版本与工程维护

- [仓库公开与隐私检查记录](analysis/2026-10-23-open-source-readiness.md)。
- [iOS 26.6.2／27.0.1 与 XNU 的内核接口差异（静态分析，2026-10-26）](analysis/2026-10-26-ios26-27-kernel-abi.md)。
- [26 线 arm64e 用户态产物的宿主构建路径（2026-10-28）](analysis/2026-10-28-arm64e-userland-build-path.md)。
- [方案架构审查与全面建议（2026-11-08）](analysis/2026-11-08-architecture-review.md)。
- [用户态与驱动隐式状态机收敛及超长文件拆分（2026-11-09）](analysis/2026-11-09-implicit-state-machines.md)。
- [全工作区早期过渡方案与性能瓶颈源码审计（2026-11-14）](analysis/2026-11-14-temporary-architecture-audit.md)。
- [annibale UEFI 与 loader 镜像构建](analysis/annibale-uefi-build.md)。
- [内核启动参数目录](analysis/boot-args.md)。
- [xnu-8796 内核的 Linux 容器构建](analysis/kernel-build-linux.md)。
- [Mesa 26.2.5 移植层（rebase-26）](analysis/mesa-rebase-2026-10.md)。

相关轮次记录：

- [26 线 userland 的架构要求与容器构建的限制（2026-10-28）](progress/2026-10-28-userland-container-build-fix.md)。

## 4. 存储、引导与恢复

- [Android 系统界面异常与编译缓存修复（2026-10-23）](analysis/2026-10-23-android-systemui-recovery.md)。
- [USB 恢复与减少人工按键的调试经验](analysis/2026-10-25-usb-recovery-lessons.md)。
- [无人值守收尾：从 oem stop 到 idle loader 的实测与人工边界](analysis/2026-10-28-unattended-teardown.md)。
- [跨开机保留数据的可行性与实测（2026-11-05）](analysis/2026-11-05-persistence-feasibility.md)。
- [根文件系统：从 UFS 挂载系统卷](analysis/rootfs-strategy.md)。

## 5. 图形、显示与性能

- [A830 GPU 启动参考](analysis/2026-10-24-a830-command-startup.md)。
- [IOMobileFramebuffer 的 selector 名字与 iOS 26.6 完整表](analysis/2026-10-28-iomfb-selector-names.md)。
- [iOS 26 QuartzCore 静态分析：窗口服务器虚表、槽位与刷新周期（2026-10-29）](analysis/2026-10-29-quartzcore-vtable-26.md)。
- [backboardd 合成路径的处理器开销（2026-10-31）](analysis/2026-10-31-compositor-cpu-path.md)。
- [每次开机都是首次开机（2026-10-31）](analysis/2026-10-31-every-boot-is-first-boot.md)。
- [锁屏壁纸：MercuryPosterExtension 的渲染链路（2026-10-31）](analysis/2026-10-31-mercury-wallpaper.md)。
- [120 Hz 手势帧率的卡点（rt2 离线分析，2026-11-01）](analysis/2026-11-01-120hz-gesture-bottleneck.md)。
- [GPU 升频之后的长帧（2026-11-02）](analysis/2026-11-02-120hz-after-gpu-clock.md)。
- [状态栏时间与电池的横向位置](analysis/2026-11-02-status-bar-layout.md)。
- [ir3 磁盘缓存跨开机实测与根因修复](analysis/2026-11-09-ir3-disk-cache.md)。
- [性能日志核查：持久化、缓存、显示计时与调频（2026-11-13）](analysis/2026-11-13-performance-log-review.md)。

相关轮次记录：

- [A830 GPU 加速桌面（iOS 16.5，2026-10-25～26）](progress/2026-10-26-gpu-desktop-acceleration.md)。
- [iOS 26 可用桌面：解锁、着色器编译、GPU 挂起与图标渲染（2026-10-29 夜～10-30）](progress/2026-10-30-ios26-usable-desktop.md)。
- [iOS 26 开机次序、处理器占用与滑动性能（2026-10-31）](progress/2026-10-31-boot-order-and-performance.md)。
- [120 Hz 与上游做法的真机轮次（2026-11-01）](progress/2026-11-01-120hz-rounds.md)。
- [120 Hz 手势帧率的无人值守轮次（2026-11-02）](progress/2026-11-02-120hz-gpu-clock-rounds.md)。
- [2026-11-08 framebuffer-fetch 探针与设备恢复状态](progress/2026-11-08-fbfetch-validation.md)。
- [2026-11-08 下午性能回退 A/B](progress/2026-11-08-performance-regression.md)。
- [2026-11-08 组件特化 AIR 采集与 draw 关联](progress/2026-11-08-widget-air-dump.md)。
- [2026-11-08 组件解锁转场密集采集与目标 AIR 候选](progress/2026-11-08-widget-dense-transition.md)。
- [2026-11-08 组件 sync draw 与首次黑化关联](progress/2026-11-08-widget-sync-log.md)。
- [锁屏与静置发热治理及显示图形管线优化跟踪（2026-11-09）](progress/2026-11-09-thermal-and-pipeline-optimization.md)。

## 6. 启动服务、应用与系统契约

- [桌面只有 2 个图标：启动参数丢了 launchd 缓存（2026-10-28）](analysis/2026-10-28-ios26-icon-model-and-launchd-cache.md)。
- [iOS 26 镜像里「job 在、程序不在」的全量对照](analysis/2026-10-28-launchd-programs-audit.md)。
- [inheritance port 失败的来源：16.5 launchd 与 26 内核的线上格式错配（2026-10-29）](analysis/2026-10-29-inheritance-port-16v26.md)。
- [开机后的处理器占用与 launchd 任务集（2026-10-31）](analysis/2026-10-31-launchd-jobs-and-boot-cpu.md)。
- [Spotlight 崩溃循环与系统镜像里缺的模型（2026-10-31）](analysis/2026-10-31-spotlight-crash-loop.md)。
- [历次反馈与验收状态复核](analysis/2026-11-08-issue-reassessment.md)。
- [用户态崩溃报告](analysis/2026-11-09-crash-reports.md)。
- [注入钩子清单](analysis/2026-11-09-injection-hooks.md)。
- [应用安装的签名](analysis/2026-11-09-ipa-codesign.md)。
- [Safari 下载与「我的 iPhone」：FileProvider 对文件系统的要求](analysis/2026-11-09-safari-download-fileprovider.md)。
- [持久化、温度与应用管理核查（2026-11-12）](analysis/2026-11-12-system-contracts.md)。

## 7. 硬件、网络与多媒体

- [annibale（REDMI K90 / SM8750「sun」）真机设备树硬件资源图谱](analysis/annibale-hw-map.md)。
- [annibale 触摸、按键、电量与 CPU 拓扑的硬件读法](analysis/2026-10-24-interactive-runtime.md)。
- [MiCode K90 官方内核源码调研（2026-10-24）](analysis/2026-10-25-micode-annibale-reference.md)。
- [K90 Wi-Fi：Android cnss2 的上电与 WLFW 顺序（2026-11-01 实测）](analysis/2026-11-01-android-cnss2-wlan-bringup.md)。
- [K90 音量与声音输出调研（2026-11-02）](analysis/2026-11-02-audio-and-volume.md)。
- [K90 蓝牙接入调研（2026-11-02）](analysis/2026-11-02-bluetooth-bringup.md)。
- [K90 屏幕亮度调节调研（2026-11-02）](analysis/2026-11-02-brightness-control.md)。
- [蓝牙 3 Mbaud 切换与内置应用退出根因及修复](analysis/2026-11-05-app-exits-root-cause-and-fixes.md)。
- [视频解码调研：H.264／HEVC／VP9 在 iOS 26 移植上的播放与 SM8750 硬件解码](analysis/2026-11-05-video-decode.md)。
- [音频播放、相机适配与视频硬解根因定位及架构设计（2026-11-11）](analysis/2026-11-11-multimedia-root-causes-and-design.md)。
- [多媒体验证结果与剩余问题（2026-11-11）](analysis/2026-11-11-multimedia-validation.md)。

相关轮次记录：

- [K90 手电与震动驱动实测（2026-10-26）](progress/2026-10-26-torch-and-haptics.md)。
- [K90 Wi-Fi：PCIe 根复合体 0 勘察与上电（2026-10-26）](progress/2026-10-26-wifi-pcie-survey.md)。
- [K90 Wi-Fi：WCN7850 固件启动（2026-10-31）](progress/2026-10-31-wifi-firmware-boot.md)。
- [K90 Wi-Fi：ath12k 驱动接入（2026-11-01）](progress/2026-11-01-wifi-ath12k-driver.md)。
- [蓝牙、跨开机保留数据与面板调光（2026-11-05）](progress/2026-11-05-bluetooth-persistence-brightness.md)。
- [默认开机参数、充电状态与安装应用（2026-11-05）](progress/2026-11-05-defaults-and-charging.md)。
- [2026-11-08 音频与组件冷启动诊断](progress/2026-11-08-audio-widget-diagnostics.md)。
- [2026-11-08 候选真机验证与音频服务崩溃定位](progress/2026-11-08-candidate-validation.md)。
- [2026-11-08 Wi-Fi 状态栏灰标与 LQM 事件](progress/2026-11-08-wifi-lqm39.md)。
- [音频播放、相机适配与视频硬解进展记录（2026-11-11）](progress/2026-11-11-multimedia-bringup.md)。

## 8. 上游与同类项目对照

- [小米 15 iOS 26 参考仓库对照（2026-10-31）](analysis/2026-10-31-dada-reference-comparison.md)。
- [hakios 上游 10-27～11-01 的可借用做法](analysis/2026-11-01-hakios-upstream-lessons.md)。
- [上游与同类项目 11-01～11-05 的可借用做法](analysis/2026-11-05-upstream-lessons.md)。
- [上游 HakiOS 2.3.4 更新对比与移植分析（2026-11-06）](analysis/2026-11-06-upstream-2-3-4-analysis.md)。
- [上游与同类项目近期更新对照（2026-11-12）](analysis/2026-11-12-upstream-review.md)。

## 9. 跨主题问题与阶段交接

- [11-13 v0.1.3 发布记录](progress/2026-11-13-release.md)：版本选择、当前限制与发布校验。

下列文档保留对应阶段的观察、产物和验证边界。后续任务从待办目录选择，旧轮次的设备状态需要重新读取。

- [11-06 至 11-08 问题与修复记录](plan/2026-11-06-issues-and-followup.md)。
- [HackiOS 遗留问题交接](progress/2026-11-08-handoff.md)。
- [11-09 交接](progress/2026-11-09-handoff.md)。
- [架构审查跟进、亮度同步、相机与触觉反馈推进记录（2026-11-10）](progress/2026-11-10-arch-review-execution.md)。

## 10. 代码仓库中的说明

与实现一起维护的说明留在所属仓库。子模块的上游资料、第三方声明和生成报告沿用各自格式；当前 K90 流程以本工作区的开发指南与专题为准。

- 内核：[仓库 README](../hackios-xnu-kernel/README.md)、[移植接口参考](../hackios-xnu-kernel/docs/PORTING.md)、[宿主检查参考](../hackios-xnu-kernel/docs/checks.md)。
- UEFI：[覆盖文件说明](../hackios-xnu-kernel/uefi/README.md)、[annibale 目标](../hackios-xnu-kernel/uefi/annibale/README.md)。
- 用户态：[仓库 README](../hackios-xnu-userland/README.md)、[AIR 参考](../hackios-xnu-userland/docs/air.md)、[AIR 生成报告](../hackios-xnu-userland/docs/air-report.md)。
- Mesa：[rebase-26 补丁说明](../hackios-xnu-userland/tools/mesa/rebase-26/README.md)。
- 第三方内容：[内核声明](../hackios-xnu-kernel/NOTICES.md)、[Adreno 830 固件说明](../hackios-xnu-userland/firmware-gen8/README.md)。

## 11. 放置与检查

| 内容 | 维护位置 |
|---|---|
| 未完成事项、候选方向与验收条件 | [backlog/](backlog/README.md) |
| 已选批次安排、架构决策与常设操作手册 | `plan/` |
| 原理、根因、调研与实测数据 | `analysis/` |
| 一轮一事的结果与专题链接 | `progress/` |
| 备份范围与恢复说明 | [backup/](backup/README.md) |
| 工具参数、输入与产物 | 对应工具目录的 README |
| 当前公开构建与安装流程 | [开发指南](development.md)、[体验说明](user-guide.md) |

同一事实在所属文档展开，其余位置引用。现有跨用途文档保留路径并注明范围；新文档按上表放置，新增、移动或改名后同步更新本文和所有引用。维护要求详见 [AGENTS.md §1](../AGENTS.md#1-文档写作约定必须遵守)。

在顶层运行 `python3 tools/check-docs.py`，检查三个仓库中 Git 跟踪的 Markdown。检查 Markdown 内联链接、引用式链接的本地目标和标题锚点，以及从顶层 README 到各文档的可达性；顶层另检查二级标题编号、硬换行和超过 500 字符的段落或列表项。链接解析支持普通路径、尖括号包裹路径和一层括号路径；HTML 链接及更复杂的 Markdown 写法需人工核对。外部 URL、命令是否适用于当前版本以及技术结论由阅读源码和实测记录确认。

新文档可用 `python3 tools/check-docs.py docs/路径.md` 单独检查。启动参数目录由 `tools/bootargs.py` 生成，变更参数来源后运行 `python3 tools/bootargs.py --check`；AIR 报告由用户态仓库的 `tools/air/check.sh` 生成。原始日志、截图、转储和构建产物按现有忽略规则保存在本地。
