# 原生 USB 与调试通道核查（2026-11-12）

本批按[执行计划](../plan/2026-11-12-usb-debugging.md)核查上游原生 USB、本仓控制器归属和调试工具。结论是暂缓在 K90 上接管 DWC3：现有无人值守命令依赖 loader 的固件 USB，当前没有经过验证的交出、停止 DMA 和重新取回协议。宿主诊断工具的修复可以独立推进。

## 1. 上游已有的范围

| 来源 | 已记录结果 | 移植边界 |
|---|---|---|
| [UniXNU/QcomDwc3 固定版本](https://github.com/UniXNU/QcomDwc3/blob/0dd83827279ee070dca7ddb486c90365567cc99d/README.md) | SM8550、iPadOS 27 24A446；USB 2／3 枚举、重新枚举、信任弹窗、Mac 配对和 lockdown 服务启动 | 持续传输、安装应用及 USB 3 反向插线未验收；SM8750 与 23G90 需分别核对 |
| [Pagani SM8750 固定版本](https://github.com/IssacL04/UniXNU-Pagani_SM8750/blob/a84204eccb9b183945072e1b9b63de36c8495097/STAGE6.md) | 第五、六版记录 Windows USB 2.0 枚举、configuration 1、USBMux 激活及连接 62078 | QueryType 超时；信任、配对及服务流量未验证；21H461 的虚表及实例布局适配需按 23G90 重新核对 |

Pagani 固定版本记录中的 v33 仅完成宿主测试和完整构建，尚未真机启动。较早版本的设备结果无法覆盖 v33 的新增改动。

QcomDwc3 的 device 子类继承原系统 `AppleUSBXDCI`，其上保留 `IOUSBDeviceFamily`、`AppleUSBDeviceMux`、configd 的 `USBDeviceConfiguration` 和 `lockdownd`。源码可用于核对寄存器、中断、PHY、供电和角色切换顺序；原生内核驱动及其 ABI 也是必要输入。

本仓 tracked 内核集成源中没有上述 USB 类，已完成的完整内核也未找到 `AppleUSBXDCI`、`AppleUSBDeviceMux`、`IOUSBDeviceController` 或 `QcomDwc3` 符号。23G90 文件系统中的 `IOUSBDeviceFamily.kext` 和 `IOUSBHostFamily.kext` 目录仅包含用户态 PlugIns。本批尚未建立闭源 USB 内核驱动接入自编 XNU 的构建及运行路径。

Pagani 通过 [NativePrelink](https://github.com/IssacL04/UniXNU-Pagani-Drivers/blob/c888efd3ce1b817d13f28783a77cf689cb2255c9/kits/NativePrelink/emit_prelink.py) 从固定 21H461 kernelcache 接入原版 kext，并按原镜像检查 267 个虚表槽、构造器指令、私有字段及 personality。其解析入口要求 ARM64 subtype 0，并依赖 `__PRELINK_INFO` 与 `MH_KEXT_BUNDLE` 布局；23G90 的 arm64e／PAC 和 kernelcache 布局尚未验证。

本仓 `xnu26/build-macos.sh` 明确跳过 kext 符号集，当前没有加载闭源 kext 所需的 exports。接入原生 USB 还需要处理内核构建与 ABI，修改板级 DWC3 驱动无法独立完成。本地 IPSW 材料尚未提供这项分析需要的原版 kernelcache。

用户态同样有启动条件：`hackios-xnu-userland/userland/mkjobs.py` 默认过滤 `lockdown` 和 `usb`，其自动收集路径还排除没有 `MachServices` 的任务。原版 `com.apple.mobile.lockdown` 使用 `Sockets`、`LaunchEvents` 和 `RunAtLoad`，只调整过滤词仍不足以启动该服务。原始 plist 与 `USBDeviceConfiguration.bundle` 本地存在。

上游 DMA 一致性方案和本机 stream、地址宽度的关系见[上游对照 §3.2、§4.1](2026-11-12-upstream-review.md)。本机实际固件的 TRB、事件环、SMMU stream 和 IRQ 仍待定向核查，不能仅凭同 SoC 复用配置。

K90 合并设备树中的 DWC3 地址为 `0x0a600000`，M31 PHY 地址为 `0x088e3000`，IRQ 为 165，SID 为 `0x40`，并声明 `dma-coherent`、`maximum-speed = high-speed`、`dr_mode = otg`。这些是当前设备树配置；物理接口可达到的最终速率仍需验证。本机 repeater 配置与 Pagani 存在差异，移植前需逐项核对。

## 2. 当前 USB 属于 loader

| 源码入口 | 当前行为 |
|---|---|
| `xnuloader/loader_06_usb_entry.inc` 的 `usb_start`、`usb_poll_command` | 通过 Qualcomm `EFI_USB_DEVICE_PROTOCOL` 初始化和启动 USB，分配 IN／OUT 缓冲；轮询固件事件并接收 Fastboot 命令 |
| `xnuloader/loader_03_ufs_block_watch.inc` 的内核运行循环 | loader 所在 CPU 屏蔽固件中断后仍轮询 USB；XNU 运行期间继续处理主机命令 |
| `xnuloader/loader_05_layout_run_kernel.inc` 的 CPU 列表与 RAM 分配 | 将 loader 所在 CPU 从 XNU 列表排除，给 XNU 独立分配 RAM 窗口 |
| `xnuloader/loader_02_platform_cpu_ufs_survey.inc` | 保留 Boot Services，返回后恢复 CPU 的页表和内存属性配置 |

USB 传输缓冲只在收到地址、长度和终态均匹配的完成通知后归还。abort 请求返回和主机超时都不能确认 DMA 停止；`CompleteError` 仍保留相关资源。这些要求已由[USB 请求生命周期](2026-10-25-usb-recovery-lessons.md#3-usb-请求生命周期的约束)记录。

现有 `lc_after_return` 恢复 CPU 中断状态并调用 UFS 的 `hc_take_back`，没有 USB 归还步骤。XNU 的 `loader_return.c` 也没有停止原生 USB 和恢复固件 USB 的流程。

## 3. 接管对无人值守的影响

直接复位 DWC3、重配端点或切换 SMMU 后，固件仍可能轮询原有事件环或继续使用在途缓冲。现有 `getvar`、`oem stop`、`rsh.py`、日志／截图传输和 reboot 命令会同时失去可用前提；当前轮次运行器依靠这些命令结束内核、取回日志并验证 `xnuloader`／`idle`／空常驻区。

控制器停止后的重新使用也缺少契约。本机 Mu-Silicium 的 `Silicon/Qualcomm/QcomPkg/Include/Protocol/EFIUsbDevice.h` 明确规定，`Stop` 停止控制器并清理资源，随后不允许再访问 USB Device Protocol。当前 loader 未调用该接口，无法假设 `Stop` 后再次 `StartEx` 可恢复原 Fastboot 通道。

annibale 的 `Platforms/Xiaomi/annibalePkg/Include/DXE.inc` 引入预编译的 `UsbfnDwc3Dxe`、`UsbDeviceDxe`、`UsbConfigDxe` 和 `UsbInitDxe`。其内部停止、DMA 回收和重初始化行为需要分析实际加载的二进制；其他板型的开源 DWC3 实现无法确认本机行为。

自动复位也有条件。XNU 仍运行期间，loader 的运行循环会更新主机静默计时，XNU 继续发心跳与喂狗；仅 USB 失联不会自然进入静默复位。fallback 自动重启只在内核已经返回并进入该状态后生效，五指退出和定时返回仍依赖 XNU 调度。

因此，当前不安排原生 USB 接管轮，也不把它加入现有相机或性能候选。继续研究需要先完成以下工作：

- 核对实际固件的停止及重初始化调用、事件环和 DMA 归属，确定能否重新建立 Fastboot。
- 定义单一控制器 owner 的交接状态和失败处理，覆盖迟到完成、断线及停止失败的宿主模型。
- 在 loader 内独立验收停止与恢复，不运行 XNU USB 驱动。
- 建立不依赖新 USB 栈、且有明确时间上限的复位路径，再安排枚举、拔插与返回 loader 的设备试验。

## 4. 现有调试方式的可用范围

当前 `rsh.py` 通过轮次请求文件交给唯一运行器发送命令，使用 119 个 UTF-8 字节上限；`fetch.py` 经 `annsh cat` 分片读取文件。两者可以继续用于运行期日志和探针，USB 所有权保持在 loader。安装 IPA、截图、性能采样等现有入口见[k90auto 说明](../../tools/k90auto/README.md)。

网络 SSH 已有历史构建入口：`hackios-xnu-userland/tools/mk-jb.sh` 预装 OpenSSH，`userland/src/boot/init_mount.inc` 准备 Procursus 前缀与用户数据库，`userland/jobs/rc.jobs.ssh` 显式启动只接受密钥的 sshd。该脚本还包含旧演示手势和等待，不能直接替换当前交互轮脚本。

本次检查的本地根盘及 Procursus 输出未找到 sshd 文件，未检查设备运行状态。网络调试后续可以复用 OpenSSH，但需要先确认打包产物、私有认证配置、Wi-Fi 连通和退出清理。SSH 依赖 XNU 与网络服务正常运行，无法承担原生 USB 初始化失败后的独立恢复。

## 5. 宿主工具修复与验证

离线复现确认 `health.py` 的帧号回退检测遗漏普通增长后的重置：序列 `1 → 100 → 2` 与最初的 1 比较，未记录回退。修复将逐条更新上一帧编号；结论仍限定为帧计数重置，进程重启需要 launchd 信息。

`fetch.py` 只读取 `rsh.py` 的 stdout，完整分片及 footer 配上非零退出码也会写入产物并报告成功。本批核对命令状态、分片完整性及进展边界，使用模拟命令完成宿主验证。

`loader-sample-series.py` 另有两个复现问题：没有 +180 秒及之后的样本时，`all([])` 使判定错误地报告后期查询成功；`getvar result` 超时后仍发 `oem log`，与脚本已有的跳过规则不符。本批修正离线结论，查询失败后跳过同一样本的其余采集。脚本保留下一采样点重新枚举后查询的既有策略；枚举成功只能确认设备可见，无法确认 DWC3 端点已经恢复。

| 宿主检查 | 结果 | 覆盖范围 |
|---|---|---|
| `python3 tools/k90auto/tests/test-fetch-health.py` | 12 项成功；同套测试可拒绝旧版 | 远程命令失败、损坏 Base64、分片偏移／footer／大小、无进展、正常分片与空文件、相邻帧号回退 |
| `python3 tools/test-loader-sample-series.py` | 37 项成功；旧版 17 项成功、20 项失败 | 无后期样本和部分应答；超时、非零状态、FAILED、缺少 result 字段后的实际命令序列；正常日志及截图顺序 |
| `python3 tools/k90auto/tests/test-tools.py` | 39 项成功 | 既有命令行工具检查 |

`fetch.py` 的远程命令或协议校验失败会保留已有目标文件，并停止继续请求分片。该保证限于 `fetch.py`；sampler 的 staged 文件采集仍使用原有目标处理方式。sampler 的结论仅统计实际记录的查询结果，无法据此判断画面冻结的原因。

复杂度审查保留三个工具的现有入口，只增加必要的输入检查、相邻计数比较及当前样本提前返回。独立复核检查了失败后的命令数量、文件结果和诊断范围；本批没有运行设备命令，未验证原生 USB 或网络 SSH。
