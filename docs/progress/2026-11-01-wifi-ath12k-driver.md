# K90 Wi-Fi：ath12k 驱动接入（2026-11-01）

[固件启动记录](2026-10-31-wifi-firmware-boot.md) 里 WCN7850 已经能进入 mission 模式，WLFW 握手由第 9 步的替身完成。本文记录把 Linux 的 ath12k 驱动编进 12377 内核、由它接管 QMI、copy engine、HTC、WMI 与数据通路，直到 iOS 26 从设置加入 WPA2 网络并上网的改动与根因。顶层提交 `fe5d5f4`、`655f967`、`d0cd74d`，内核子模块提交 `a6262dd`、`a48c7fb`、`6c81426`、`1b17a50`、`05577dc`、`4cd05c9`。

## 1. 改动

- `hackios-xnu-kernel/tools/mk-ath12k.sh`：按 `mk-ath11k.sh` 的做法，构建时取 Linux 7.0.14 的 ath12k（含 `wifi7/`，BSD-3-Clause-Clear）与 FreeBSD 15.1 的 LinuxKPI 头文件，编成 `xnu-deps/build/ath12k/out/ath12k.o`。驱动源码不进仓库。
  - 编译的文件：ath12k 的公共部分与 `wifi7/` 共 33 个；`pci.c`、`mhi.c`、`ahb.c`、debugfs、ACPI、tracing、电源管理不编。
  - 链接后只有 `ath12k_wifi7_pci_init` 一个函数做成桩，它是模块初始化入口，不会被调用。
- `wifi/lx/ath12k/`（新目录，只在 ath12k 构建里使用）：
  - `lx_pci.c`：代替 ath12k 的 `pci.c` 与 `mhi.c`。按 ath12k 的 probe 顺序读硬件版本、装 WCN7850 的参数表、建 copy engine 与数据通路的环，再启动 core。上电调用内核的第 7、8 步；BAR0 的寄存器按 `pci.c` 的窗口规则访问；没有中断，后台线程每 1 ms 查一次 copy engine，驱动打开数据通路后同时查各环组。
  - `lx_mac80211.c`：mac80211 的 wiphy work（ath12k 用它发管理帧、清理扫描）和 `ieee80211_queue_stopped`。
  - `lx_ath12k.h`：LinuxKPI 头文件缺的定义，数值取自 IEEE 802.11be 与 radiotap.org。
- `wifi/lx/include/linux/` 新增 `acpi.h`、`clk.h`、`of_graph.h`、`panic_notifier.h`、`remoteproc/qcom_rproc.h` 的最小实现；`of_reserved_mem.h` 补 `struct reserved_mem`。
- `wifi/lx/patches/`：LinuxKPI 头文件补 `rate_info.eht_ru_alloc`、`struct link_station_info`、`link_sta_statistics`、`eml_cap`、两个 EHT 的 `bss_conf` 字段、`IEEE80211_HW_MLO_MCAST_MULTI_LINK_TX`、ADDBA Response 帧结构；修正 `kmalloc_objs` 把乘积当成 `size_mul` 单参数的错误。
- `wifi/lx/src/`：
  - `lx_base.c`：内存池大小可由构建参数指定（ath12k 用 96 MB，其中 64 MB 给环与固件内存）；ath12k 构建里一页及以上的分配按大小向上取 2 的幂次对齐（上限 16 MB，`12377-cmd61` 起，见 3.1）；补 `skb_copy` 与 `sx_sysinit`。
  - `lx_80211.c` 拆成 `lx_80211.c`（radio、信道、扫描、收发帧）与 `lx_join.c`（加入网络、密钥、block ack、内核侧 station），共享声明放进 `lx_80211.h`；BSS 变化对没有 `bss_info_changed` 的驱动改为分别调用 `vif_cfg_changed` 与 `link_info_changed`。
- 内核 `12377-cmd58`：
  - `pcie=10`：前 6 步照旧，之后不跑第 7～9 步，改为启动驱动（`annibale_lx_start()`）；驱动上电时内核再跑第 7、8 步，随后写 MHI 的 wake 门铃让网卡保持唤醒。
  - `annibale_lx.c` 在 `pcie=10` 时把驱动的内存、寄存器、固件文件、上电请求转给 `mhi_pcie.c`：内存取 loader 留在 4 GB 以下的区域，按页分配；`board.bin`、`regdb.bin`、`m3.bin` 分别对应 RAM 盘 `fw/` 下的 `bdwlan.elf`（`pcie_bdf=` 可改）、`regdb.bin`、`phy_ucode20.elf`。
  - `annibale_lx.h` 新增 `lx_os_radio_registers()`，告诉驱动 BAR0 的位置与大小。
  - `xnu26/build-macos.sh` 在 `ath12k.o` 存在时把它链进内核。
- loader v15（`fastboot boot`，build-id `a6262dd`）：低端内存的申请条件改为 `pcie=7`～`pcie=10`。
- `xnu26/build-macos.sh`：`ath12k.o` 变化时同时删掉 `mach.*.unstripped.noctf`，否则 make 从旧的链接结果复制，内核不会重新链接（`12377-cmd59` 之前一次构建因此得到与 `cmd58` 相同的镜像）。
- 内核 `12377-cmd60`～`cmd68` 的排查手段，默认行为不变的都由启动参数打开：
  - MHI 事件行带开机后的毫秒数；SYS_ERR 时读出 BHI 的 ERRCODE 与三个 ERRDBG。
  - `mhi_pcie_power.c`：s5f、s3g 按本机 OL CPR 投 954 mV、1866 mV（`cmd62` 起，见 [Android cnss2 对照](../analysis/2026-11-01-android-cnss2-wlan-bringup.md) 第 2 节）；上电前读 PMK8550 GPIO3，`pcie_sleep_clock=board` 把它设成睡眠时钟输出（`cmd64`）。
  - `wifi/lx/ath12k/lx_pci.c`：`wifi_hostcap=1` 按 cnss2 的值发主机能力（feature list 0x6，不发 nm_modem），做法是给 `hw_params` 换一份可写的副本（`cmd63`）；驱动日志行带开机后的毫秒数。
  - `mhi_pcie_fw.c`、`mhi_pcie.c`：`pcie_fw=3` 用 RAM 盘里的 `lfw-amss.bin` 与 `lfw-m3.bin`，即 linux-firmware 里给 ath12k 的 WCN7850 固件，手工放进本地固件目录，不进仓库（`cmd65`）。
  - `mhi_pcie_power.c`：`pcie_smps_hpm=1` 给 5 路开关稳压器投高功率模式（`cmd66`）；`pcie_bt_en=1` 在拉高 WLAN_EN 之前拉高 BT_EN（`cmd67`）；`pcie_aop_pdc=1` 经 AOSS QMP 邮箱把 WLAN PDC 的 21 条配置发给 AOP（`cmd68`）。
  - `annibale_qrtr.c`：记下对端的名字服务查询和发往无人端口的数据，`qrtr_answer=1` 回答查询（`cmd67`）。
  - `mhi_pcie_fw.c`：`pcie_rddm=1` 给网卡留 RDDM 转储的接收向量，SYS_ERR 后把转储拷进内核窗口并打印 `fetch:` 行（`cmd68`）；`lx_pci.c` 把 WMI STATS 组的事件按十六进制打印（`cmd68`）。
- `tools/k90auto/package.py`：`WIFI_FW=1` 时另放 `regdb_xiaomi.bin`、`bd_p11*.elf`、`qdss_trace_config*.cfg`，以及本地固件目录里有的 `lfw-*.bin` 与 `network`（`wifi_join=1` 要连的网络名与密码，Git 忽略，清单只记有没有这个文件）。
- 内核 `12377-cmd69`～`cmd76`，第 9 步替身（`mhi_pcie_wlfw.c`）向 cnss2 的做法靠拢，都由启动参数打开：
  - `pcie_mission=7` 走 cnss2 冷启动校准的前半段：校准报告（下载大小取类型 4 段的长度）、calibration 模式、等 CAL_DONE、OFF 模式（`cmd69`）。
  - `pcie_ddr_range=1`、`=2` 在主机能力里发 `ddr_range`，分别是 loader 的低端内存与 cnss2 的窗口；ath12k 的描述表缺成员描述，替身改用补全的副本（`cmd70`～`cmd72`）。
  - `pcie_features=N` 替换主机能力的功能列表（`cmd73`）。
  - FW_INIT_DONE（0x38）与 FW_READY 一样视为固件就绪；`pcie_qdss=1` 在 M3 信息之后 3 秒内两者都没到时下发 `fw/qdss_trace_config_v2.cfg`（消息 0x44）（`cmd74`）。
  - `pcie_mlo=1` 按 cnss2 的值在主机能力里发单芯片 MLO 字段：`max_mlo_peer` 32、1 颗芯片、2 条链路（`cmd75`）。
  - `cmd77` 去掉 FW_INIT_DONE 的处理与 3 秒等待：`wd19` 里固件发的是 FW_READY，且只在收到 QDSS 配置之后发。`pcie_qdss=1` 改为 M3 信息之后直接下发，与 cnss2 相同。这一版还没上机。
- `wifi/lx/ath12k/lx_pci.c`：`wifi_mlo=1` 把 `ab->single_chip_mlo_support` 置位，ath12k 因此在主机能力里发同样的 MLO 字段（`cmd76`）。
- `wifi/lx/src/lx_80211.c`：驱动注册射频时地址为 0，就改用内核的 `wifi_mac`（`cmd78`）；接口没开以太网卸载时，`lx_ethernet_send()` 按 mac80211 的做法组 802.11 数据帧（`cmd80`）。
- `wifi/lx/patches/include-linux-dma-mapping.h.patch` 与 `wifi/lx/src/lx_base.c`：`dma_map_single()` 把指针传下来，不在池里的内存复制进池里的一个槽再交给网卡，解除映射时复制回来（`cmd79`）。
- loader v16（`fastboot boot`，build-id `a48c7fb`）：低端 DMA 内存先按固定地址 `0xA8000000` 申请 128 MB，落在 cnss2 声明的窗口 `0x98000000`～`0xb0010000` 里，避开 loader 自身（`0xA1000000`）与设备树的两段 `lost_reg_mem`；被占用时退回原来的取法（4 GB 以下最高的空闲块）。
- `wifi/lx/src/lx_base.c` 超过 1200 行，idr 与 rhashtable 拆到新文件 `lx_tables.c`。
- `tools/k90auto/run-auto.py`：收尾复位之前，按已存日志里的 `fetch: 名字 地址 长度` 行用 `oem stage` 取回这段内存，存成 `名字.bin`；`test-tools.py` 加了对应用例。
- `xnu/files/bsd/dev/annibale_apple80211.c`：按 iOS 26 的布局读写 SCAN_REQ、SCAN_RESULT、CURRENT_NETWORK 与 ASSOCIATE（`cmd81`，布局见 3.6）。
- `xnu26/patches/31a-libkern%c++%OSKext.cpp.patch`：`OSKext::foreachKextInBacktrace()` 在没有 kext 摘要表时直接返回（`cmd82`，原因见 3.6 的 `wd30`）。
- `tools/k90auto/package.py`：`WIFI_FW=1` 时把 configd 的控制偏好 `com.apple.InterfaceNamer.control.plist`（`ConfigureNewInterfaces` 为真）放进 `fw/`，数据卷模板加两行，开机时复制到 `/private/var/preferences/SystemConfiguration/`。
- `wifi/lx/src/`：`lx_join.c` 每次加入时打印 PMK 的 16 位指纹（SHA-1 的前两字节）；`lx_80211.c` 按驱动的发送报告打印我们每条握手消息是否被接入点确认、未确认或被驱动丢弃（`cmd83`，只加读数）。
- 系统盘：`ios165/select-system.py`（iOS 26 共用）加选 `FontServices.framework/CorePrivate/PingFangUI.ttc`，`userland/system26.apfs` 重建，原因见 3.7。


## 2. 当前配置

- 参数：`tools/k90auto/cycle.py` 的固定参数沿用 `kernel-12377-cmd83-wd32` 的 Wi-Fi 一组：`pcie=10 pcie_power=1 pcie_sleep_clock=board pcie_bdf=bd_p11.elf pcie_smps_hpm=1 pcie_bt_en=1 pcie_aop_pdc=1 pcie_rddm=1 wifi_mlo=1 wifi_mac=<本地管理地址> wifi_station=1`。
- 从设置加入网络并上网必需的三项：`wifi_mlo=1`（3.2）、`wifi_mac=`（3.3）、`wifi_station=1`（3.6）。`pcie_sleep_clock=board` 到 `pcie_aop_pdc=1` 五项是 3.2 排查时逐项换成 Android 的做法留下的，`wd21` 起一直带着，去掉后能否工作没有验证。`pcie_rddm=1` 给网卡留转储的接收向量，SYS_ERR 后才用到。
- loader 要 v16：`pcie=10` 的低端 DMA 内存由 loader 申请，A 槽里刷的 v14 不给，驱动建不起内存池（`wd25`）。驻留版本低于 v16 时，`cycle.py` 先经 LK 启动 v16（[11-05 记录](2026-11-05-defaults-and-charging.md)）。
- 固件文件与提取方法见[固件启动记录](2026-10-31-wifi-firmware-boot.md) §2。`package.py` 放固件时一并放 configd 的 `ConfigureNewInterfaces` 偏好（3.6）；系统盘要带 `PingFangUI.ttc`（3.7）。
- `wifi=1` 不能用：它在 K90 的内核里会同时打开旧芯片的一组选项。

日志里的成功标志：

- probe：硬件版本 `0x40170200`，驱动参数表 `wcn7850 hw2.0`。
- 注册：`IS UP: the radio is registered`，打印射频地址。
- 加入：`THE NETWORK IS JOINED`，en0 链路 up。
- 上网：configd 的 `State:/Network/Global/IPv4` 主接口为 en0；经 `rsh.py` 在设备上跑 `net_test` 的 `resolve`、`reach`、`fetch` 成功。

## 3. 问题与修复

### 3.1 驱动起步与内存对齐（`wd2`、`wd3`）

- 驱动的内存池起点 `0xc77c0000`；BAR0 在 `0x40400000`（2 MiB）。驱动上电时内核的第 7、8 步与替身相同，约 567 ms 进入 mission mode。
- `wd2`（`cmd59`）：回复固件内存请求时超时（`-60`），网卡报 SYS_ERR。替身给固件的两段内存按大小对齐，驱动的分配只按页对齐；`cmd60`、`cmd61` 让一页以上的分配按大小对齐到 2 的幂次（上限 16 MB），内存池扩到 96 MB。
- `wd3`（`cmd60`）：QMI 走到 FW_READY 与 mission 模式；HTC 就绪（2 个发送额度，Control、HTT Data、WMI 三个服务）；WMI service ready、ext、ext2 到达（3 种硬件模式，首选 5 即 DBS）。WMI_INIT 之后约 190 ms SYS_ERR，见 3.2。

### 3.2 固件崩溃：主机能力缺 MLO 字段（`wd3`～`wd21`）

现象：WMI_INIT 之后约 186～190 ms SYS_ERR。之前先收到事件 `0x16005`（ath12k 编号里是 STATS 组的 `WMI_UPDATE_FW_MEM_DUMP_EVENTID`，驱动不处理）。BHI 错误寄存器指向固件 `cmnos_thread_patch.c` 第 1270 行（`wd4`），读法见 [Android cnss2 对照](../analysis/2026-11-01-android-cnss2-wlan-bringup.md) 第 5 节。

每轮换一项 Android 的做法，崩溃位置与时刻都不变，以下各项排除：电压（`wd5`）、睡眠时钟（`wd6`）、板级数据 `bd_p11.elf`（`wd7`）、开关稳压器高功率模式（`wd10`）、BT_EN（`wd11`）、AOP 的 WLAN PDC 配置（`wd12`）。linux-firmware 给 ath12k 的固件 `WLAN.HMT.1.1.c7-00108`（`pcie_fw=3`，`wd8`、`wd9`）547 ms 进入 mission mode，之后同样 SYS_ERR，报同一源文件第 1174 行，没有转储，没有继续追。排查中读到的硬件状态：

- PMK8550 GPIO3（睡眠时钟输出）：`pcie_sleep_clock=board` 写入后读回与 Android 一致，两边的寄存器值见 cnss2 对照第 2 节。
- BT_EN（PM8550VE-F GPIO3）：写入前是输入加下拉，`pcie_bt_en=1` 写入后读回输出高电平。
- QRTR：网卡只发 HELLO 和 WLFW 服务（69）的通告，没有名字服务查询，`qrtr_answer=1` 用不上。
- AOP 邮箱开机时我方链路为 up、通道为 down，内核重新握手后打开，21 条 `wlan_pdc` 消息都被收下。

故障点（`wd12`、`wd13`）：

- `pcie_rddm=1` 留的接收向量被网卡使用，SYS_ERR 后写入 4,837,542 字节，`run-auto.py` 收尾时取回 `rddm.bin`。
- 故障原因 `cmnos_thread_patch.c:1270:0x8Asserted in:0x1f26a9c:0x1f269ac, line#386`：定位服务的初始化（`0x189f7d8`）按 min(n, 3) 与 n − 3 建两个池，n 为 0，n − 3 成了 `0xfffffffd`，ROM 的池分配报 fatal 386。
- `wd13` 用替身单独跑冷启动校准（`pcie=9 pcie_mission=7`），请求 calibration 模式后在同一处崩溃，出错线程的栈从 `0x18b9ad8` 往上与 `wd12` 相同。
- 转储里固件对主机内存的映射：芯片地址 `0x048b0000` 对应主机 `0xca000000`（类型 4 段），`0x04000000` 起对应类型 1 段。

`ddr_range`（`wd14`～`wd17`）：cnss2 在主机能力里发 `ddr_range` = `{0x98000000, 0x18010000}`（SMMU 的 IOVA 窗口），ath12k 不发。这组轮次读到的固件约束：

- ath12k 的 `ddr_range` 描述项缺成员描述，编码器拒绝（-22）；替身改用补全的副本。
- 发了范围时，各项终点的最大值必须等于 `0xb0010000`，否则 fatal 3268（检查在 `0x185dccc` 之前）。
- 范围原样用 cnss2 的窗口、内存不在窗口里时，内存回复后 fatal 2974。
- UEFI 内存表（`oem memmap`）里窗口内只有 `0xa6180000`～`0xa7000000` 这 14 MB 空闲，`0xa8000000` 起是保留，loader v16 的固定地址申请失败，退回 `0xc77c0000`。照 Android 发范围需要 SMMU 翻译。
- 不发 `ddr_range` 时校准与 mission 模式都能完成，这条路线暂停。

根因（`wd18`～`wd20`）：n 来自主机能力里的 `max_mlo_peer`。固件只在主机发了 MLO 那组字段时才写入它；cnss2 对 WCN7850 总会发（`max_mlo_peer` 32），ath12k 只在 PHY capability 报告支持单芯片 MLO 时才发，这版固件报 0。代码路径见 cnss2 对照第 5 节。

- `wd18`：功能列表换成 cnss2 的 0x6 后，M3 信息之后 10 秒内没有 FW_READY，整轮没有崩溃。
- `wd19`：再下发 QDSS 配置（4939 字节，一段），FW_READY 紧接着到达。功能列表为 0x6 时固件要等这份配置，0x18 时不需要。之后请求 calibration 模式，仍是 fatal 386，栈与 `wd13` 相同。
- `wd20`：补上 MLO 字段（`pcie_mlo=1`）后，calibration 模式请求成功，8162 ms 后收到 CAL_DONE（Android 为 8216 ms），OFF 模式成功，没有 SYS_ERR。
- `wd21`：驱动侧用 `wifi_mlo=1`（功能列表保持 0x18，不发 QDSS），WMI_INIT 之后没有 SYS_ERR。
- `wd4`～`wd11` 没有转储，崩溃点同在第 1270 行、ERRDBG 一致，推测同一原因。

### 3.3 射频地址与扫描（`wd21`～`wd23`）

- `wd21`：驱动启动 380 ms 后注册射频。信道：2.4 GHz 14 个、5 GHz 27 个、6 GHz 60 个，监管域 US 允许其中 11、27、60 个。固件给的地址是全 0，驱动不建接口。
- `wd22`：加 `wifi_mac=`（本地管理地址，首字节 0x02）后地址仍为 0。ath12k（Linux 7.0.14）只从 WMI ready 事件取地址，不调 `device_get_mac_address()`；`12377-cmd78` 在 LinuxKPI 的 `ieee80211_register_hw()` 里补上：地址为 0 时用内核的 `wifi_mac`。
- `wd23`：station 接口建立。扫描 98 个信道，13079 ms 完成，听到 12 个接入点（2.4 GHz 9 个、5 GHz 3 个，-20～-96 dBm），网络名与 BSSID 只留在本地日志。扫描之后监管域变为 CN（4 条规则），6 GHz 信道全部不可用。

### 3.4 接收队列描述符不在网卡能访问的内存里（`wd24`）

- 目标网络在 5 GHz 40 信道，-21 dBm，WPA2-PSK、CCMP；密钥 19 ms 算完，信道 20 MHz 设好。
- 驱动登记接入点时失败（-12），前一行是 `memory is given to the radio that it cannot reach (1536 bytes)`。ath12k 的 REO 接收队列描述符（每个 traffic class 一份）用 `kzalloc()` 分配后 `dma_map_single()` 交给硬件，这块内存不在网卡能访问的池里。
- `12377-cmd79` 的改法：LinuxKPI 头文件补丁让 `dma_map_single()` 把指针传下来；不在池里的内存复制进池里的一个 4 KB 槽，网卡拿到槽的地址，解除映射时复制回来并归还槽，最多同时 64 块。ath12k 映射之后到解除映射之间不碰这块描述符。

### 3.5 握手回复的封装（`wd26`、`wd27`）

- `wd26`：接入点登记成功，认证与关联都被接受。四次握手收到第 1 条消息并回了第 2 条，接入点又重发两次第 1 条，3077 ms 后以 reason 15（握手超时）解除认证。
- 原因：握手回复按以太网帧交给驱动（`IEEE80211_TX_CTL_HW_80211_ENCAP`）。ath12k 的 Wi-Fi 7 发送描述符里没有逐帧的封装类型，封装方式取自接口的 bank 配置；这版固件不支持以太网卸载（没有 `WMI_TLV_SERVICE_ETH_OFFLOAD`），接口是 native wifi，硬件把以太网头按 802.11 头解释后发出。ath11k 的描述符有逐帧的封装字段，原来的写法在那边可用。
- `12377-cmd80` 的改法：接口没开以太网卸载时，`lx_ethernet_send()` 按 mac80211 的做法组 802.11 数据帧：发往接入点，接入点有 WMM 时用 QoS data（握手 TID 7，其余 TID 0），类型前加 LLC/SNAP，有密钥后标记受保护，由硬件加密。
- `wd27`：四次握手完成，关联后 114 ms 两把密钥交给驱动，日志出现 `THE NETWORK IS JOINED`，en0 链路 up。en0 收到 375 帧（约 180 KB）局域网广播与组播，组播密钥解密正常。

### 3.6 接入 iOS 26 的网络栈（`wd27`～`wd31`）

内核自己加入网络（`wifi_join=1`）时：

- `wd27`：en0 发出 0 帧。wifid 问 apple80211 的 CURRENT_NETWORK 61 次都被拒绝（error 6），它认为没有连上，configd 也不跑 DHCP。
- `wd28`：经 `rsh.py` 执行 `net_test dhcp en0` 后 0.8 s 拿到 IPv4 地址，路由器的 ARP 已解析，驱动层收发两个方向都通过。域名解析失败，`fetch` 报 `NSURLErrorDomain -1009`：`dhcp en0` 建的服务不在 `Setup:/Network/Service` 里，iOS 26 的 configd 不把它选为主服务，没有 `State:/Network/Global/IPv4`。

改为 `wifi_station=1`：驱动把站点交给内核的 station 接口，wifid 的 apple80211 请求（扫描、信道、当前网络、加入）经它到达驱动，内核不自己加入网络。

- `wd29`：HW_SUPPORTED_CHANNELS、CHANNELS_INFO 都有回答，设置的 Wi-Fi 开关为开；SCAN_REQ（5528 字节）被内核以 EINVAL 拒绝，网络列表为空。`annibale_apple80211.c` 的结构按 iOS 16.5 逆向，对照两版 `IO80211.framework` 的反汇编，iOS 26 改了三项请求：
  - SCAN_REQ 从 5456 字节变为 5528 字节，前 0x1548 字节的布局不变（scan_type 0x34、信道数 0x44、信道表 0x48、flags 0x1308、名字表 0x1314），0x1310 与 0x154c 之后是新字段。
  - SCAN_RESULT 与 CURRENT_NETWORK 的缓冲区从 1164 字节变为 2272 字节：16.5 的字段偏移不变，信息元素的空间从 1024 字节变为 2048 字节，0x8d0 之后是新字段。
  - ASSOCIATE 从 592 字节变为 908 字节，两个认证字段从 16 位变为 32 位，其后所有字段后移 4 字节（名字长度 0x10、BSSID 0x34、密钥长度与类型 0x40、0x44，密钥 0x4c）。
- `12377-cmd81`：扫描请求接受更长的长度、读同样的前缀；扫描结果按调用方给的整个长度清零后填写；连接请求按长度区分两种布局。
- `wd30`：设置列出附近的网络。ASSOCIATE 为 908 字节，认证 0x1/0x8（WPA2-PSK），密钥是 32 字节、类型 6 的 PMK，位置在 0x4c。加入完成后设置一直转圈：en0 没有 UP、没有地址，configd 的 `Setup:` 下没有任何网络服务，wifid 等不到可路由的接口，又重发加入请求。
- 原因：configd 的 InterfaceNamer 在 iOS 上只在数据卷首次开机时给接口建网络服务；之后出现的接口，只有控制偏好 `ConfigureNewInterfaces` 为真时才调用 `SCNetworkSetEstablishDefaultInterfaceConfiguration()`（configd 开源代码 `Plugins/InterfaceNamer/ifnamer.c`）。en0 的命名时刻比 `*START*` 晚 29.5 秒，这时首次开机的配置已经建完。`package.py` 因此把这份偏好放进数据卷模板。
- `wd30` 手动 DHCP 之后不到两分钟内核 panic：trap telemetry 的提交线程（`drain_record_submission_buffer_thread_call`）调用 `OSKext::foreachKextInBacktrace()`，这个内核没有加载过 kext，`gLoadedKextSummaries` 为 NULL，读 `numSummaries` 时 data abort（far 0x8）。`12377-cmd82` 在没有摘要表时直接返回。
- `wd31`（`cmd82`，镜像带 `ConfigureNewInterfaces`）：en0 出现后 configd 建出 Wi-Fi 服务（`DeviceName` 为 en0，IPv4 为 DHCP），服务顺序里只有它。从设置加入 2.4 GHz 的网络后网络打勾，configd 自己跑完 DHCP：`State:/Network/Global/IPv4` 的主接口为 en0，全局 DNS 有服务器，IPv6 也拿到地址。设备上 `resolve` 0.01 s 返回，`reach` 为可达，`fetch http://captive.apple.com/` 与 `fetch https://www.apple.com/` 都是状态 200（后者 256542 字节，1.20 s），保持 900 秒没有 panic。

### 3.7 中文字体（`wd31`、`wd32`）

- `wd31` 的网页与 Wi-Fi 列表里中文显示为带问号的方框。iOS 26 没有 `Fonts/LanguageSupport/PingFang.ttc`，中文字体是 `FontServices.framework/CorePrivate/PingFangUI.ttc`（61 MB），系统盘只从框架目录取小文件，没有选进去。
- 它是可变字体，32 个字形共用 59 MB 的字形表，按字形裁剪省不下空间，整份放进系统盘，`system26.apfs` 从 5,217,959,936 字节变为 5,257,109,504 字节。
- `wd32`：中文与日文正常绘制，`font_test` 的样例回退到 `.PingFangUIDisplaySC-Regular`。韩文仍回退到 LastResort（`Fonts/Core/AppleSDGothicNeo.ttc` 43 MB，没有选进系统盘）。轮后用 `dsu.py install --replace` 把手机 DSU 换成这份系统盘。

## 4. 未解决

- 第一次加入失败：`wd30`、`wd31` 第一次加入 5 GHz 40 信道的网络时，接入点发了 3 次第 1 条消息，我们回了 3 次第 2 条，约 3086 ms 后 reason 15，与输错密码的表现相同；wifid 回到列表后自动重试，后来的加入成功，两次用同一个密码。`wd32` 第一次加入一次成功，第 2 条（155 字节）与第 4 条（133 字节）都被接入点确认，原因仍未定位。
- `cmd83` 的两个读数留在内核里，失败再出现时这样判断：失败与成功两次的 PMK 指纹不同，问题在 wifid 给的 PMK；指纹相同而第 2 条被确认，问题在第 2 条的内容；第 2 条未被确认或被驱动丢弃，问题在发送。
- 韩文字体没有进系统盘，显示回退到 LastResort。
