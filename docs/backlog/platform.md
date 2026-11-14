# 外设与电源待办

本表集中连接、显示电源、温控和其他硬件能力，2026-11-12 整理。当前温度批次见[系统后续事项](../plan/2026-11-12-system-followup.md)，背光与硬件验证见[多媒体验证](../analysis/2026-11-11-multimedia-validation.md)。其他主题见[待办入口](README.md)。

## 1. 已有实现的验收与连接问题

| 编号 | 事项 | 状态与已知条件 | 下一步与验收 | 来源 |
|---|---|---|---|---|
| S3 | 真实温度上报 | 修复、宿主检查与完整内核构建通过，真机读数待验 | 核对电池真实读数、单位、无效值处理、IOKit 消费者和既有手电高温保护 | [系统批次 S3](../plan/2026-11-12-system-followup.md)、[系统契约](../analysis/2026-11-12-system-contracts.md) |
| P1 | 背光闪烁与亮度保留 | 单位与滑块覆盖问题已修复并完成软件对照；11-13 人工确认调光没有闪烁，闪光灯及其亮度调节正常；低亮度跨重启待复核 | 核对最低亮度和连续两次重启后的滑块、原生 nits 与 DBV | [多媒体验证 §7、§19、§70](../analysis/2026-11-11-multimedia-validation.md#70-11-13-人工体验与发布范围)、[亮度分析](../analysis/2026-11-02-brightness-control.md) |
| P2 | 触觉反馈与手电档位 | 手电点亮已确认；触觉端口与事件修复尚需真机验收 | 检查系统触觉事件与马达反馈、手电档位／熄灭和温度限制；面板闪烁合并 P1 观察 | [架构跟进 §5](../progress/2026-11-10-arch-review-execution.md)、[手电与触感记录](../progress/2026-10-26-torch-and-haptics.md) |
| P3 | Wi-Fi 图标、首次连接与重连 | cmd564、LINK／LQM 及主接口重评估已修改，真机待验 | 检查事件送达 wifid／SpringBoard、RSSI 和 wifiActive；测首次连接、重启重连和实际传输 | [LQM39 记录](../progress/2026-11-08-wifi-lqm39.md)、[架构跟进 §6](../progress/2026-11-10-arch-review-execution.md) |
| P4 | 每设备 Wi-Fi MAC | 未实现；发行镜像固定地址，多机同网可能冲突 | 确定每设备地址来源与保存规则，验证重启稳定性和多机同网；记录中使用脱敏值 | [体验说明 §14](../user-guide.md#14-已知问题) |
| P5 | 蓝牙配对、重连与音频 | BLE 扫描及 3 Mbaud 已有实现；端到端配对、重连、A2DP／HFP 等按功能验收 | 检查 iOS 与芯片地址一致性、密钥持久化、原生 HAL 插件可见性、音频路由和真实外设行为；HID、LE Audio 与 Wi-Fi 共存按选定功能独立验证 | [蓝牙分析 §8](../analysis/2026-11-02-bluetooth-bringup.md)、[上游对照 §3.1](../analysis/2026-11-12-upstream-review.md#31-蓝牙会话与音频) |
| P6 | 蓝牙会话与 IBS 时序 | 研究候选；全局 Skywalk 状态与上游 nexus 归属处理不同 | 覆盖旧会话延迟销毁、新会话连接、UART 关钟与 IBS wake 交错；再测连续开关及 bluetoothd 重启 | [上游对照 §3.1](../analysis/2026-11-12-upstream-review.md#31-蓝牙会话与音频) |
| P7 | 蓝牙名称与扫描条件 | 待核查；系统名称配置调用尚未找到 | 对照 CurrentSet、系统名、HCI 名称及设置页；比较 App 与命令行扫描的状态和过滤条件 | [上游对照 §2.6](../analysis/2026-11-12-upstream-review.md#26-蓝牙名称与扫描条件) |
| P8 | 充电状态与功率 | 待当前版本复核；旧记录包括低供电功率问题 | 验证不同供电来源的状态／电流／温度，不改变缺少硬件依据的限流值 | [问题复核](../analysis/2026-11-08-issue-reassessment.md)、[默认项与充电](../progress/2026-11-05-defaults-and-charging.md) |

## 2. 电源与尚未完成的硬件能力

| 编号 | 事项 | 状态与前提 | 下一步与验收 | 来源 |
|---|---|---|---|---|
| S8 | 原生 USB 设备模式 | 已核对上游实现；设备接管暂缓，固件 USB 停止后重用与独立恢复尚未验证 | 先确认固件停止／DMA 回收／重新初始化，建立有界恢复，再核对 23G90 原版 USB 内核组件及 SM8750 参数 | [USB 核查](../analysis/2026-11-12-usb-debugging.md)、[执行计划](../plan/2026-11-12-usb-debugging.md) |
| P9 | 关屏、系统休眠与唤醒 | 未完成；显示电源 selector 直接成功，系统休眠默认禁用 | 分开核对显示提交／诊断绘制停止、面板状态、控制器归属、唤醒源及恢复；实测功耗和唤醒后输入、显示、通信 | [系统批次 S8](../plan/2026-11-12-system-followup.md)、[上游对照 §4.2](../analysis/2026-11-12-upstream-review.md#42-显示关闭固件失败与调频) |
| P10 | 原生温控服务与传感器 | 待研究；CPU／GPU 已有自身温控，thermalmonitord 尚未接入 | 核对 V57 温度服务、板面／电池／芯片传感器区别、通知与失效处理；PMIC ADC 需独立驱动 | [路线图 §5](../plan/2026-10-26-roadmap.md)、[架构审查](../analysis/2026-11-08-architecture-review.md) |
| P11 | CLPC 与动态调频 | cd37 策略参数与软件频率统计已核对，实际时钟及完整限频时长待测；现有负载调频和触摸提升可作为对照 | 核对调度回调、work interval、SCMI／GMU 请求及温控职责，同时记录负载请求、温控上限、下发档位、应答与实际频率；在空闲、交互、持续负载、无效温度读数场景比较帧率、长帧、频率分布、温度与可测功耗 | [调频核查 §5](../analysis/2026-11-13-performance-log-review.md#5-p11策略参数与观测边界)、[路线图 §5.4](../plan/2026-10-26-roadmap.md#54-苹果原生策略分析与复刻clpc)、[上游对照 §3.4](../analysis/2026-11-12-upstream-review.md#34-显示颜色绘制范围与-gpu-进度) |
| P12 | 固件温度保护与 ACD | 待核查；TSENS critical／复位阈值及无 Android 下的固件限频尚无实测 | 根据本机设备树与有效寄存器范围确认保护状态；ACD 需核对板型表，再比较故障、温度和实际工作点 | [路线图 §5.2](../plan/2026-10-26-roadmap.md)、[11-05 上游对照](../analysis/2026-11-05-upstream-lessons.md) |
| P13 | 基带、电话、短信与移动数据 | 尚未功能验收，存在驱动基础代码 | 分别核对 MPSS、QMI、IPA 与 CommCenter 原生契约，选定功能后定义最小验收 | [硬件图谱 §7](../analysis/annibale-hw-map.md)、[架构跟进](../plan/2026-11-06-issues-and-followup.md) |
| P14 | GPS 与运动／环境传感器 | 尚未功能验收，依赖调制解调器或传感器处理器的关系需核实 | 确认硬件及固件服务后逐项接入定位、加速度、陀螺、距离、光线与 iOS 消费者 | [硬件图谱](../analysis/annibale-hw-map.md)、[架构审查](../analysis/2026-11-08-architecture-review.md) |
| P15 | 指纹与安全硬件契约 | 后续研究候选，Touch ID／SEP 前提未建立 | 先核对目标体验、认证边界和可实现范围，再决定是否立项 | [路线图 §4](../plan/2026-10-26-roadmap.md)、[架构审查](../analysis/2026-11-08-architecture-review.md) |
| P16 | GPU／VPU 停止与资源释放 | 待完善；VPU PAS／SMMU 清理已有结果，完整 VPU／NOC 下电与 GPU DDR vote／RSC sleep 仍需核对 | 检查停止顺序、在途 DMA、资源释放和重新启动；与 P9 的休眠验收共用结果 | [多媒体验证 §12、§18](../analysis/2026-11-11-multimedia-validation.md)、[A830 启动 §8、§9](../analysis/2026-10-24-a830-command-startup.md) |
| P17 | AirDrop 与投屏实际传输 | 未完成端到端验证；已有离线返回与界面解阻塞处理 | 核对 AWDL、sharingd、发现、连接和文件／媒体传输，逐阶段记录原生协议所需条件 | [注入钩子分析 §2](../analysis/2026-11-09-injection-hooks.md)、[问题复核 §2](../analysis/2026-11-08-issue-reassessment.md) |
| P18 | 网络校时与跨重启时钟 | 待当前版本复核；已有 PMK8550 硬件对时实现 | 对照网络校时、硬件时钟和重启后系统时间，记录服务、单位及失败阶段 | [架构审查 §12.3](../analysis/2026-11-08-architecture-review.md)、[问题复核](../analysis/2026-11-08-issue-reassessment.md) |
| P19 | DCS 渐变与 HBM | 可选研究；已用 DBV 上限为 0x1a5e，设备树 max-level 为 0x3fff，正常亮度与 HBM 分界未确认 | 先取得本机面板命令与亮度范围来源，再评估 DCS 渐变和 HBM；自动亮度依赖 P14 的环境光输入 | [亮度分析 §1、§7、§8](../analysis/2026-11-02-brightness-control.md) |

蓝牙与 Wi-Fi 共用电源轨和 BT_EN。蓝牙须在 Wi-Fi 上电之后启动，Wi-Fi 在线期间保留 BT_EN，见[蓝牙分析 §1](../analysis/2026-11-02-bluetooth-bringup.md)。
