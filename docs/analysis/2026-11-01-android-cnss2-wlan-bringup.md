# K90 Wi-Fi：Android cnss2 的上电与 WLFW 顺序（2026-11-01 实测）

ath12k 在 K90 上跑到 WMI_INIT 后固件崩溃（[ath12k 驱动接入记录](../progress/2026-11-01-wifi-ath12k-driver.md)）。为了逐项对照，在 Android（B 槽，KernelSU）开机后读取了 cnss2 的日志。本文记录 Android 在这台手机上给 WCN7850 供电、启动固件、走 WLFW 的实际做法，以及与我们 `pcie=10` 路径的差异。

## 1. 来源

- `dmesg`，以及挂载 debugfs 后 `ipc_logging/` 下的 `cnss`、`cnss-long`、`mhi_1107_00.01.00` 三个缓冲区。
- `regulator/regulator_summary`，PMK8550 的 regmap（`regmap/0-00/registers`）。
- 原始文件在本地证据目录 `docs/progress/evidence/k90auto/android-cnss-20261101/`（Git 忽略）。其中含本机 MAC 地址与芯片序列号，摘录时不要带出。

## 2. 供电

- probe 时按设备树的 `qcom,pdc_init_table` 给 AOP 发 14 条 `wlan_pdc` 消息，设定 rf（s3g、s7i、s1d）与 bb（s4d、s5f）两组资源的升压值、降压值和使能。
- 8 路 regulator 按 io、io12、ant-share、vdd、aon、dig、rfa1、rfa2 的顺序打开，然后拉高 WLAN_EN（GPIO16），再枚举 PCIe RC0。
- 收到 target capability 后，cnss2 按固件给的 OL CPR 表算出这块芯片要的电压，再给 AOP 发一次升压值和降压值，见下表。
- FW init done 之后，cnss2 撤掉这 8 路 regulator 的 apps 投票（日志 `Removing vote`），之后由 WLAN PDC 按芯片的请求升降压。mission 模式下 `regulator_summary` 里 vdd-wlan 与 vdd-wlan-aon 的请求下限只剩 500 mV。

OL CPR 表与我们的投票（mV）：

| PMIC 资源 | 固件条目（要求 → 平台电压） | AOP 升压值／降压值 | `12377-cmd61` 及以前的 apps 投票 |
|---|---|---|---|
| s1d | VDD_PMU_AON_I 850 → 866；VDD095_PMU_BT 900 → 914；VDD09_PMU_RFA_I 850 → 914 | 914 ／ 880（设备树） | 976 |
| s5f | VDD095_PMU 940 → 954，睡眠 420 → 414 | 954 ／ 414 | 932 |
| s4d | VDD095_MX_PMU 960 → 974，睡眠 589 → 586 | 974 ／ 586 | 976 |
| s7i | VDD13_PMU_PCIE_I 1025 → 1042；VDD13_PMU_RFA_I 1300 → 1314 | 1314 ／ 972（设备树） | 1316 |
| s3g | VDD19_PMU_PCIE_I 1850 → 1866；VDD19_PMU_RFA_I 1850 → 1866 | 1866 ／ 1844（设备树） | 1864 |

s5f 与 s3g 两路，我们的投票低于这块芯片的要求。`12377-cmd62` 起改为 954 mV 与 1866 mV。

PMK8550 的 GPIO3（设备树 `alt_sleep_clk_default`）在 Android 下是 func1、输出、无上下拉、使能（MODE_CTL 0x01、DIG_PULL_CTL 0x05、DIG_OUT_SOURCE_CTL 0x02、EN_CTL 0x80）。cnss2 日志 `qcom,sleep-clk-support is 0`，即芯片用板上送来的睡眠时钟。经 loader 起的系统里，这个引脚是启动固件留下的输入加下拉（MODE_CTL 0、DIG_PULL_CTL 0x4、DIG_OUT_SOURCE_CTL 0，`wd5` 读数），没有时钟输出；设备树的这条 pinctrl 只在 Linux 的 PMIC GPIO 驱动加载时生效。

## 3. WLFW：两次启动

cnss2 先做一次冷启动校准，再断电重启进 mission 模式。设备树有 `qcom,wlan-cbc-enabled`，日志 `WLAN register driver deferred for Calibration`。

第一次（校准）：

1. 主机能力：客户端 1、WAKE MSI data 13、`cal_done` 0、IOVA 从 0x98000000 起 0x18010000 字节、feature list 0x6。没有 nm_modem。
2. REQUEST_MEM：类型 1 0x730000 字节、类型 4 0x810000 字节，回复后收到 FW_MEM_READY。
3. target capability，随后按 OL CPR 发 AOP 消息（第 2 节）。
4. REGDB 用 `regdb_xiaomi.bin`（24,278 字节，与 `regdb.bin` 内容不同）。
5. BDF 用 `bd_p11.elf`（88,788 字节），日志 `hwid=0x90000 Using DEFAULT bdf`、`Host BDF config: HW_XPA: 1 CalDB: 0`。
6. M3 用 `phy_ucode20.elf`；QDSS 配置用 `qdss_trace_config_v2.cfg`。
7. FW init done 后发天线切换请求（固件拒绝，err 94）、校准文件报告，再请求 CALIBRATION(7) 模式。
8. 8216 ms 后收到 CAL_DONE，请求 OFF 模式，拉低 WLAN_EN，关掉 8 路 regulator。

第二次（mission）：

1. 重新上电，主机能力同上，只是 `cal_done` 为 1。
2. REQUEST_MEM 回复的地址与第一次相同（类型 4 是校准数据所在的段，内容保留）。
3. REGDB、BDF、M3、QDSS 同上，FW init done 后取 DMS MAC、发 WLAN MAC、ini（fw_log_mode 1）、WLAN 配置（shadow 寄存器 v3 共 36 条）、MISSION(0) 模式。
4. 从 WLFW 服务出现到 mission 模式约 150 ms；之后 qcacld 的 WMI ready 在 mission 模式请求后约 180 ms 到达。

## 4. 与 `pcie=10` 路径的差异

| 项 | Android cnss2 | ath12k（`12377-cmd61`） |
|---|---|---|
| 电压 | 第 2 节的 OL CPR 值，之后交给 PDC | apps 固定投票，s5f 932、s3g 1864，不配 PDC |
| 睡眠时钟 | PMK8550 GPIO3 输出 32 kHz | 引脚是输入加下拉，没有时钟（`12377-cmd64` 起 `pcie_sleep_clock=board` 可设成 Android 的配置） |
| 冷启动校准 | 先校准再 mission，`cal_done` 1 | 不校准，`cal_done` 0 |
| BDF | `bd_p11.elf` | `bdwlan.elf`（高通参考板的默认文件） |
| REGDB | `regdb_xiaomi.bin` | `regdb.bin` |
| feature list | 0x6 | 0x18（QDSS_CFG_MISS、PCIE_PERST_NO_PULL） |
| nm_modem | 不发 | 0xe（内部睡眠时钟、host C-state、PCIe 全局复位） |
| QDSS 配置 | 下发 | 不下发 |
| MLO 字段 | 发，`max_mlo_peer` 32（cnss2 源码，日志不打印） | 不发：PHY capability 报 `single_chip_mlo_support` 0 |
| PCIe | Gen2，运行中在 Gen1／Gen2 间调整 | 限 Gen1 |

固件版本相同（`WLAN.HMT.2.0-02977`），M3 相同。feature list 0x6 的两个位在 ath12k 的头文件里没有定义，名称待按 cnss2 源码核对。

## 5. 崩溃位置

`wd4` 的 SYS_ERR 读出 BHI ERRDBG2 0x1500729、ERRDBG3 0x4f6。0x1500729 落在 `amss20.bin` 只读数据段里，是字符串 `cmnos_thread_patch.c` 的地址；同段有一条断言记录 `{行号 0x4f6, 0x01414020, 0x01500729}`，所以崩溃点是 `cmnos_thread_patch.c` 第 1270 行。固件是 Hexagon 代码，ELF 头写的是 ARM。

`wd12` 用 `pcie_rddm=1` 取回了网卡的 RDDM 转储（本地 `kernel-12377-cmd68-wd12/run/rddm.bin`，4,837,542 字节）：

- 开头是目录：版本 1，头长 0x208，每项 0x40 字节，依次是起始地址、物理地址、长度、20 字节描述、20 字节文件名。数据按目录顺序紧接在头后面。
- 目录的 8 项：`Q6-SFR`（0x50 字节，故障原因）、`Q6-SRAM`（0x1400000 起 4 MB）、`WLAON_DUMP`、三段 ETB 跟踪（SoC 32K、Q6 2K、WCSS 32K）、`PHYA-M3`、`PHYB-M3`（各 0x48000）。
- 故障原因：`cmnos_thread_patch.c:1270:0x8Asserted in:0x1f26a9c:0x1f269ac, line#386`。第 1270 行是固件致命错误的统一出口：`Asserted in` 后面是调用致命错误函数（`0x1279434`）处的返回地址和上一层的返回地址，`line#N` 是传给它的编号。`wd15` 的 `line#3268` 能在 `amss20.bin` 里对上 `r0 = 0xcc4` 加 `call 0x1279434`，可以印证这种读法。`:0x8` 的含义未知。
- `Q6-SRAM` 里有出错线程的栈，按 Hexagon 的帧链（每帧 `{上一帧, 返回地址}`）走出 25 层。从线程入口往上依次经过 copy engine 的处理、一次间接分发、带 `Coex pmac pre sleep`／`RTT pmac post awake` 字符串的函数，最后由 `0x18ca524` 构造的对象经 `0x18ca790`（`r4 = 0x200` 后跳到 ROM 的 `0x1f26964`）分配内存，ROM 里报 fatal 386。请求的元素个数是 `n - 3`，`n` 为 0，详见[驱动接入记录](../progress/2026-11-01-wifi-ath12k-driver.md) 3.4。
- `0x1f2xxxx`、`0x1cbxxxx`、`0x12xxxxx` 不在 `amss20.bin` 的任何段里，推测是芯片 ROM，看不到代码。
- `Q6-SRAM` 里还有固件的开机控制台文字，含两行 `Thread create: can't allocate Tcb.. entry 0x12b0074`、`entry 0x1293838`。出错线程的栈底正是 `0x1293838` 开始的函数，所以这两行不表示线程没有建成；没有 Android 的转储对照，不能判断它们是否正常。

ERRDBG1 在 Android 固件下是 0x21 或 0x1，含义仍未知。

n 的来源（`wd19` 的转储加 `amss20.bin` 反汇编）是主机能力里的 `max_mlo_peer`：

- `wls_init`（`0x18b84e8`，含字符串 `wls_init`）在 `0x18b8b38` 读配置对象的 `+0x10c`，作为 n 交给 `0x189f7d8`；后者按 min(n, 3) 和 n − 3 建两个池。
- 配置对象的 `+0x10c` 在 `0x18b9a4c` 写入，取全局字 `0x15610f0` 的第 10～25 位。`wd12`、`wd13`、`wd19` 的转储里这个字都是 0。
- `0x15610f0` 的这几位由 `0x1a2c784` 写入（`0x1a2c700` 也写这个字，只改第 6～9 位），n 取 `0x1536142` 处的 16 位值。`0x1a2c784` 唯一的直接调用在主机能力（消息 0x34）的处理函数 `0x182a59c` 里。
- 处理函数把解码后的整条主机能力消息（0x238 字节）拷到 `0x1535f38 + 0xc8`，因此 `0x1536142` 是消息结构体的偏移 0x142，即 `max_mlo_peer`。偏移按 ath12k 的 `qmi_wlanfw_host_cap_req_msg_v01` 计算；处理函数读 `feature_list_valid`、`feature_list` 的位置（0x159、0x160）与这个布局一致。
- 写入条件：`mlo_chip_id`、`mlo_group_id`、`max_mlo_peer`、`mlo_num_chips` 四个 valid 都不为 0，`mlo_chip_id` 为 0，`mlo_num_chips` 不超过 1。

cnss2 的 `cnss_wlfw_host_cap_parse_mlo()` 对 KIWI、MANGO、PEACH 总会发这组字段：`mlo_capable` 1、chip id 0、group id 0、`max_mlo_peer` 32、1 颗芯片、2 条链路（hw link id 0、1）。来源是 LineageOS `android_kernel_qcom_sm8650-modules` 的 `qcom/opensource/wlan/platform/cnss2/qmi.c`（lineage-22.2 分支），比本机的平台早一代；本机日志里主机能力的几行在这份源码里都有对应的打印，MLO 字段本身不打印。ath12k 只在 PHY capability 报告 `single_chip_mlo_support` 时才发这组字段，这版固件报的是 0。`wd20` 补上这组字段后校准完成。
