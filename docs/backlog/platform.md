# 外设与电源待办

本表集中连接、显示电源、温控和其他硬件能力，2026-11-12 整理。当前温度批次见[系统后续事项](../plan/2026-11-12-system-followup.md)，背光与硬件验证见[多媒体验证](../analysis/2026-11-11-multimedia-validation.md)。其他主题见[待办入口](README.md)。

## 1. 已有实现的验收与连接问题

| 编号 | 事项 | 状态与已知条件 | 下一步与验收 | 来源 |
|---|---|---|---|---|
| S3 | 真实温度上报 | 修复、宿主检查与完整内核构建通过，真机读数待验 | 核对电池真实读数、单位、无效值处理、IOKit 消费者和既有手电高温保护 | [系统批次 S3](../plan/2026-11-12-system-followup.md)、[系统契约](../analysis/2026-11-12-system-contracts.md) |
| P2 | 触觉反馈与手电档位 | 手电点亮已确认；触觉端口与事件修复尚需真机验收 | 检查系统触觉事件与马达反馈、手电档位／熄灭和温度限制 | [架构跟进 §5](../progress/2026-11-10-arch-review-execution.md)、[手电与触感记录](../progress/2026-10-26-torch-and-haptics.md) |
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
| P13 | 基带、电话、短信与移动数据 | 11-20 补上 APPS 侧 TFTP 服务（`/readwrite/` 内存文件、`/readonly/firmware/` 读固件卷）后 MPSS 读完 MCFG，`DMS` 从 `OFFLINE` 进入 ONLINE，`NAS` 开始搜网，见[11-20 基带进展](../progress/2026-11-20-modem-tftp.md)；`UIM` 报告卡不存在 | 核对卡槽检测与供电，使 `UIM` 读到卡；之后对接 CommCenter 与状态栏信号，再做数据面（IPA） | [硬件图谱 §7](../analysis/annibale-hw-map.md)、[架构跟进](../plan/2026-11-06-issues-and-followup.md)、[阶段六进展](../progress/2026-11-19-stage6-modem-camera-graphics.md) |
| P14 | GPS 与运动／环境传感器 | 11-20 `QMI_LOC` 事件注册补上客户端名与客户端类型两个 TLV 后成功（`mask=0x187`），15 秒探测收到会话状态、引擎状态和位置上报（技术掩码 `0x2`，无卫星），见[11-20 基带进展 §4](../progress/2026-11-20-modem-tftp.md#4-qmi_loc-事件注册) | 在室外或窗边延长探测，确认卫星上报；对接 `locationd`／`geod`；运动与环境传感器另列 | [硬件图谱](../analysis/annibale-hw-map.md)、[架构审查](../analysis/2026-11-08-architecture-review.md)、[阶段六进展](../progress/2026-11-19-stage6-modem-camera-graphics.md) |
| P15 | 指纹与安全硬件契约 | 后续研究候选，Touch ID／SEP 前提未建立 | 先核对目标体验、认证边界和可实现范围，再决定是否立项 | [路线图 §4](../plan/2026-10-26-roadmap.md)、[架构审查](../analysis/2026-11-08-architecture-review.md) |
| P16 | GPU／VPU 停止与资源释放 | 待完善；VPU PAS／SMMU 清理已有结果，完整 VPU／NOC 下电与 GPU DDR vote／RSC sleep 仍需核对 | 检查停止顺序、在途 DMA、资源释放和重新启动；与 P9 的休眠验收共用结果 | [多媒体验证 §12、§18](../analysis/2026-11-11-multimedia-validation.md)、[A830 启动 §8、§9](../analysis/2026-10-24-a830-command-startup.md) |
| P17 | AirDrop 与投屏实际传输 | 未完成端到端验证；已有离线返回与界面解阻塞处理 | 核对 AWDL、sharingd、发现、连接和文件／媒体传输，逐阶段记录原生协议所需条件 | [注入钩子分析 §2](../analysis/2026-11-09-injection-hooks.md)、[问题复核 §2](../analysis/2026-11-08-issue-reassessment.md) |
| P18 | 网络校时与跨重启时钟 | 待当前版本复核；已有 PMK8550 硬件对时实现 | 对照网络校时、硬件时钟和重启后系统时间，记录服务、单位及失败阶段 | [架构审查 §12.3](../analysis/2026-11-08-architecture-review.md)、[问题复核](../analysis/2026-11-08-issue-reassessment.md) |
| P19 | DCS 渐变与 HBM | 可选研究；已用 DBV 上限为 0x1a5e，设备树 max-level 为 0x3fff，正常亮度与 HBM 分界未确认 | 先取得本机面板命令与亮度范围来源，再评估 DCS 渐变和 HBM；自动亮度依赖 P14 的环境光输入 | [亮度分析 §1、§7、§8](../analysis/2026-11-02-brightness-control.md) |
| P20 | iOS 关机与重启后 loader 的处理 | 实现完成、待验证：内核把关机或重启请求带给 loader，从菜单启动的单次运行据此调用 PSCI `SYSTEM_OFF` 或复位；主机发起的运行仍回到 Fastboot（内核 `6acd5c59`） | 刷入新 loader 后从菜单启动 iOS：重启能回到菜单并再次进入 iOS；关机后整机断电，长按电源键能正常开机（需人在场） | [11-21 真机体验问题 §1](../progress/2026-11-21-user-test-issues.md#1-用户报告的问题) |
| P21 | Wi-Fi 连接后连续扫描 | 11-22 修复：删除扫描结束后补发的链路事件（`1d94a404` 引入），`w1` 连接后 395 秒扫描 12 次，wifid 不再占处理器，开机自动连接后图标正常。遗留：在「设置」里关闭再打开 Wi-Fi 后图标三道弧都是灰色（IP 与路由正常），`v0.2.2` 同一操作为实心；保留部分补发的两种做法都没有改善 | 查关开之后 wifid 与系统状态栏的 Wi-Fi 状态来源（`STWifiStatusDomain` 一侧读到的状态），以及内核自行重连 standing 网络与 wifid 自动加入的关系 | [待机发热对照 §8](../analysis/2026-11-22-idle-heat-vs-android.md#8-已做的修复与复测) |
| P22 | 交互期间的温度限频 | 11-22 三轮：处理器最热读数在开机后 80 秒内到 71～75 °C，手势期间每 30 秒最多 35 次触到 70 °C 上限，应用内滚动随之从 118 降到 86～95 帧/秒；相邻两次读数最大相差 16.7 °C。loader 在 0 号核上的轮询、面板拷贝与 GPU 最高档的功耗没有测量 | 先修 `P21`，再做固定起始温度的基线；一轮一个变量测 loader 轮询加等待、GPU 档位上限、`cpus=7`；对照原厂 `tsens` 核对读数跳变。阈值不放宽 | [全局现状分析 §3.4](../analysis/2026-11-22-global-review.md#34-温度与限频) |
| P23 | 待机功耗与原厂 Android 的差距 | 11-22 同机对照：Android 待机时处理器传感器 31～33 °C，95% 的时间在 556 MHz，各核 66%～99% 的时间处于断电状态；iOS 去掉扫描循环后仍为 45～68 °C，两个调频域 84%～93% 的时间停在 2,400／2,438 MHz。用 `cpufreq_mhz=600` 封顶后为 43～48 °C。源码确认：处理器空闲只有等待中断一级，loader 的 0 号核无等待轮询，静止桌面每秒约 10 帧，GPU 帧间断电被关闭 | 抬频只在连续出帧或触摸时生效（11-22 已完成，待机最热读数 39.5～48 °C）；找出静止桌面每秒 10 帧的来源（减弱动态效果没有去掉它）；loader 轮询加等待；接入 PSCI `CPU_SUSPEND`；打开 GPU 帧间断电；在 Android 上挂载 debugfs 对照时钟、电源轨与总线票。验收为静置 10 分钟与 30 分钟的最热读数、电池温度、最低档时间占比、每秒中断数与出帧数 | [待机发热对照](../analysis/2026-11-22-idle-heat-vs-android.md) |
| P24 | 自动锁定不生效、插电后常亮 | 11-22 晚：SpringBoard 应用了 warn 40 s、total 60 s 的空闲计时器，3 分钟无触摸仍不变暗；倒计时在 backboardd 的 AttentionAwareness。11-23 已修复：CommCenter 被 mkjobs 排除，SBTelephonyManager 每秒以 TelephonyManager:UpdateSB 重置空闲计时器；放开 CommCenter（noncellular 变体）后 `w61` 静置变暗再锁屏 | 在 backboardd 里记录 AttentionAwareness 的注视采样与超时；核对没有 Face ID 相机时采样的结果 | [11-22 晚记录 §3](../progress/2026-11-22-photo-motor-autolock.md#3-自动锁定不生效) |

蓝牙与 Wi-Fi 共用电源轨和 BT_EN。蓝牙须在 Wi-Fi 上电之后启动，Wi-Fi 在线期间保留 BT_EN，见[蓝牙分析 §1](../analysis/2026-11-02-bluetooth-bringup.md)。
