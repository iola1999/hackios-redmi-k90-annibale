# annibale 触摸、按键、电量与 CPU 拓扑的硬件读法

本文整理 K90 触摸、实体按键、电量与充电状态、CPU 拓扑和 GPU 早期初始化的硬件事实与判断方法，主要来自 2026-10-23～10-24 的真机调试，之后的改动在文中标出处。通用方法见[项目排查与协作手册](../plan/debugging-and-collaboration.md)，命令见[真机调试手册](../plan/device-test-playbook.md)，设备树资源见[硬件资源图谱](annibale-hw-map.md)。

## 1. 外设地址与访问前提

| 对象 | 核对结果 | 判断方法 |
|---|---|---|
| TLMM GPIO | 厂商 DT 资源为 `0x0f000000 + 0x202000`；主线 SM8750 的 GPIO 寄存器窗口为 `0x0f100000 + 0x102000`，寄存器按 GPIO 号乘 `0x1000` 访问 | 资源起点与 GPIO 寄存器起点分开算，核对 `0x100000` 的子窗口偏移只加了一次 |
| RPMh 命令数据库 | DT 声明在 `0x81c60000 + 0x20000`；从 SMEM 扫描时在 `0x81d9e004` 触发同步外部异常；改为定点读取后找到 `ldob12 = 0x40a00`（触摸 I/O 电源） | 先按 DT 确定资源范围再定点读，不从旧机型的布局推扫描范围 |
| GCC 时钟 | SM8750 的 QUP1 AHB 时钟寄存器偏移为 `0x23140`／`0x23144`，SE2 的时钟停止标志在 bit 31 | 名称相同也要逐项核对寄存器偏移与位域 |
| 机型识别脚 | annibale 没有旧机型的触摸识别脚，代码用占位值 `NO_STRAP=1000`；早期诊断打印把它当 GPIO 号去读 | 占位值要在访问前处理，诊断代码同样遵守板型约束 |

- 旧的 TLMM 地址计算少了 `0x100000`，诊断输出停在 GPIO43 配置读取之前，随后设备回到 Android。改正后同组 GPIO 与时钟读数正常，供电与 SPI 初始化继续执行。地址错误期间各次重启的完整异常原因没有全部取得。
- 在 Android 里整组读取 `pinmux-pins`／`pinconf-pins` 调试文件后也丢过 USB、设备回到 Android，没有区分是哪一项读取。调试文件的读取可能调用驱动、访问硬件；不要整组读，先从保存的 DT、驱动源码和单项状态核对。
- 触摸节点声明了 `trusted-touch` 与 `tvm`，访问前要检查所有权与访问路径；仅凭这一点不能认定上面的重启由权限拒绝造成。

## 2. 触摸：传输与报告模式

- 芯片：Goodix，固件报 `BERLIN`／`9916K`，坐标范围 `1156 × 2510`。报告地址 `0x10308`，头长 8，每个触点 8 字节；命令地址 `0x10174`。
- 传输：驱动（`xnu/files/bsd/dev/annibale_goodix.c`、`annibale_touch_bus_private.h`）先试 GENI SPI 引擎的 FIFO 模式。引擎没有 SPI 固件、FIFO 接口被禁用（`GENI_IF_DISABLE_RO` bit 0 为 1）或芯片不应答时，改用 GPIO 模拟 SPI；两根数据脚哪根是输入没有资料，两种都试。2026-10-24 的日志读到 GENI `interface 0x1`，走的是 GPIO 模拟。
- 报告模式：读到稳定的芯片身份、版本校验也有效时，报告内容仍可能全为零。K90 的固件要先关原始帧上报、再开坐标上报：`0x90` 数据 `02 00`，`0x91` 数据 `01`，命令长度与校验按数据长度计算。做法取自 MiCode `vendor_xiaomi_proprietary_touch-driver` 仓 `warsaw-w-oss` 分支 `warsaw/goodix_9916k/goodix_brl_hw.c` 的 `goodix_htc_enable()`（同芯片的其他机型）；Android 日志里原厂驱动也走 THP（`goodix_ts_probe IN THP`）。加上这两条命令后日志出现连续的 `goodix: finger 0 at ...`。
- 中断线：驱动不用中断，线程按 `touch_poll_us`（默认 8000 us）查中断线电平。K90 的中断线不会一直拉低到报告被读走，所以驱动同时读 TLMM 锁存的下降沿（`GPIO_INTR_STATUS` bit 0，打开 raw status 后即使中断关闭也会锁存），线电平和锁存位都没有变化时每 80 ms 也读一次报告（`annibale_goodix.c`，`kernel-12377-cmd52-bo61`）。`cycle.py` 用 `touch_poll_us=4000`。
- 逐层核对顺序：驱动开关 → 芯片身份与校验 → 报告模式 → 有效触点 → `/dev/annibale-touch` → 用户态注入 → 界面响应时间。芯片应答、内核坐标日志和实际手势分别记录，`touch screen ready` 一行不能代替输入验收。`rwtouch` 注入的手势不经过芯片，要与手指操作分开统计。

## 3. 实体按键

三个键都是 PMIC 的输入，与 SoC 的 TLMM 无关：

- 电源键：PMK8550 上电模块（PON，ppid `0x013`）的 KPDPWR_N。
- 音量下：同一 PON 模块的 RESIN_N。
- 音量上：PM8550 自己的 GPIO6（ppid `0x18d`，上拉，按下拉低）。

驱动 `xnu/files/bsd/dev/annibale_buttons.c`（`buttons=1`）经 PMIC 仲裁器 v7 只读访问，PON 与 GPIO6 分别对应仲裁器通道 581、610，类型与输入配置核对通过后才采信读数。定位这类硬件要同时记下控制器、外设地址和通道。

## 4. 电量与充电状态

- 电量计：Android 的设备树和 I²C 设备 `uevent` 确认是 TI BQ27Z561，地址 `0x55`，挂在 QUP1 SE5，SDA／SCL 为 GPIO52／53；同一总线还有地址 `0x6e` 的充电泵。旧的 PMIC FG／SDAM 路径读不到有效电量。
- 读法：`xnu/files/bsd/dev/annibale_battery.c`（`battery=1`）用 GPIO 开漏模拟 I²C 读标准命令，每次采样后恢复两根引脚的配置。读电量也会改动 GPIO 状态，要检查总线占用、异常退出与恢复；并发访问的情形没有全部验证。电量计自己写闪存时可能把 SCL 拉低 40.08 ms，驱动按此等待。
- 样本检查：电量、电压、温度超出范围的样本直接丢弃（10-24 首个样本温度为 `65535`，被拒）。有效样本约 95%、4377～4381 mV、34.75～34.85 °C，iOS 电源服务收到 95%。UEFI 缓存的读数与 BQ 的读数是两个来源，日志要按发布者和时间解释。
- 充电状态：BQ 路径用有符号电流推导，电流超过 +50 mA 判为充电，低于 −50 mA 判为放电（`CHARGE_FLOW_UA`；接近充满时电流在 0 附近几十 mA 内摆动，一次 +17 mA 的样本曾让 iOS 显示 5 秒「充电」）。电流方向只反映电池净电流；USB 是否连接、充电器是否在线、充电策略都要另一个来源。iOS 26 上充电器在线与充电状态取自 DSP 的电池管理（`xnu/files/iokit/Kernel/AnnibaleBattery.cpp`），连着 Mac 时显示不准的现状与待办见[默认参数与充电状态](../progress/2026-11-05-defaults-and-charging.md)。

## 5. CPU 拓扑

- 设备树的 CPU 地址为 `0x0`～`0x500`（六个核）和 `0x10000`、`0x10100`（两个高性能核）。loader 的 `platform_annibale.core_mpidr` 按物理核号列出这张表，`small_cores = 0x3f` 标出前六个；`bootcpu=7` 对应 MPIDR `0x10100`。
- 旧代码按 `core << 8` 换算地址，`bootcpu=7 cpus=2` 时 loader 尝试 MPIDR `0x700`，固件返回 PSCI 错误（`no-such-core 6 0`），内核没有进入。修复用逐核 MPIDR 表，并在内核 CPU 查找、secondary 入口和 GIC SGI 编码里保留 Aff2，设备生成脚本也输出完整表。只改 loader 的启动地址，其他使用者仍会截断核心身份。
- 带 L2 access penalty 标记（loader 的 small-core）的非启动核默认在开机 28 秒后才启动（`xnu/files/iokit/Kernel/GenericARMPE.cpp`，`small_cores_after=S`，0 为立即启动）。早期日志里的 `1 of 2 processors are running` 不说明第二个核启动失败，要看完整生命周期的日志。`cycle.py` 用 `cpus=4 bootcpu=7 small_cores_after=0`。

## 6. GPU 早期初始化的硬件读法

GPU 阶段定义与后续验收见 [A830 命令执行案例](2026-10-24-a830-command-startup.md)，这里只留早期阶段确认的硬件读法。GMU 是运行管理固件的 GPU 管理单元，HFI 是主机与 GMU 固件的通信接口。

- QFPROM 速度档熔丝：Linux v6.17 的 `qfprom.c` 用对齐的 `readl`，本机 DT 的 `bits = <0 9>` 描述所需字段。对 `0x221c8138` 做两次字节读取时设备复位；改成一次对齐的 32 位读取再取低 9 位（`& 0x1ff`）后读到 `0x400400e8`，speed bin 为 232（`0xe8`）。`speed_bin` 与 SKU 来自不同字段。
- 固件型号：本机 Android 日志与厂商配置指向 gen80000，按相近编号选 gen80200 是错的。资料冲突时回查实际使用方和本机运行记录，换型号后重新检查所有派生参数。
- GMU 的 SMMU 配置：旧代码混用了 TBU stream 范围长度与匹配掩码，GMU 还占用了厂商留给 GPU 的 context，启用 stream 翻译时触发同步外部异常。按本机 DT 与厂商分配规则改为 SID5 精确匹配、context 2，并调整 SHCFG 后，启用与退出通过。
- GMU 固件页权限：超时路径要读故障寄存器，读到的记录是 `GMU SMMU fault 0x8 at 0:0x4000, syndrome 0xd0063`。原页允许非特权写入，AArch64 翻译规则禁止特权指令从这种页取指；只清除 AP bit6 后记录 `GMU firmware started: result 0x100`。
- SMMU 回读：两次回读检查分别遇到未保留的可选提示位和固定读值字段。差异按字段定义解释，只放宽有依据的检查，并用测试确认必要位写入失败时仍会停止。
- HFI 队列报告版本 2.7.1。厂商代码同时有普通 HFI 与 HWSCHED 两条路径，本机产品配置选 HWSCHED，两条路径的 START 前置顺序不同。
