# K90 Wi-Fi：ath12k 驱动接入（2026-11-01）

[固件启动记录](2026-10-31-wifi-firmware-boot.md) 里 WCN7850 已经能进入 mission 模式，WLFW 握手由第 9 步的替身完成。本文记录把 Linux 的 ath12k 驱动编进 12377 内核、由它接管 QMI、copy engine、HTC、WMI 与数据通路的改动、判据与轮次。

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
  - `pcie=10`：前 6 步照旧，之后不跑第 7～9 步，改为启动驱动（`redwood_lx_start()`）；驱动上电时内核再跑第 7、8 步，随后写 MHI 的 wake 门铃让网卡保持唤醒。
  - `redwood_lx.c` 在 `pcie=10` 时把驱动的内存、寄存器、固件文件、上电请求转给 `mhi_pcie.c`：内存取 loader 留在 4 GB 以下的区域，按页分配；`board.bin`、`regdb.bin`、`m3.bin` 分别对应 RAM 盘 `fw/` 下的 `bdwlan.elf`（`pcie_bdf=` 可改）、`regdb.bin`、`phy_ucode20.elf`。
  - `redwood_lx.h` 新增 `lx_os_radio_registers()`，告诉驱动 BAR0 的位置与大小。
  - `xnu26/build-macos.sh` 在 `ath12k.o` 存在时把它链进内核。
- loader v15（`fastboot boot`，build-id `a6262dd`）：低端内存的申请条件改为 `pcie=7`～`pcie=10`。
- `xnu26/build-macos.sh`：`ath12k.o` 变化时同时删掉 `mach.*.unstripped.noctf`，否则 make 从旧的链接结果复制，内核不会重新链接（`12377-cmd59` 之前一次构建因此得到与 `cmd58` 相同的镜像）。
- 内核 `12377-cmd60`～`cmd68` 的排查手段，默认行为不变的都由启动参数打开：
  - MHI 事件行带开机后的毫秒数；SYS_ERR 时读出 BHI 的 ERRCODE 与三个 ERRDBG。
  - `mhi_pcie_power.c`：s5f、s3g 按本机 OL CPR 投 954 mV、1866 mV（`cmd62` 起，见 [Android cnss2 对照](../analysis/2026-11-01-android-cnss2-wlan-bringup.md) 第 2 节）；上电前读 PMK8550 GPIO3，`pcie_sleep_clock=board` 把它设成睡眠时钟输出（`cmd64`）。
  - `wifi/lx/ath12k/lx_pci.c`：`wifi_hostcap=1` 按 cnss2 的值发主机能力（feature list 0x6，不发 nm_modem），做法是给 `hw_params` 换一份可写的副本（`cmd63`）；驱动日志行带开机后的毫秒数。
  - `mhi_pcie_fw.c`、`mhi_pcie.c`：`pcie_fw=3` 用 RAM 盘里的 `lfw-amss.bin` 与 `lfw-m3.bin`，即 linux-firmware 里给 ath12k 的 WCN7850 固件，手工放进本地固件目录，不进仓库（`cmd65`）。
  - `mhi_pcie_power.c`：`pcie_smps_hpm=1` 给 5 路开关稳压器投高功率模式（`cmd66`）；`pcie_bt_en=1` 在拉高 WLAN_EN 之前拉高 BT_EN（`cmd67`）；`pcie_aop_pdc=1` 经 AOSS QMP 邮箱把 WLAN PDC 的 21 条配置发给 AOP（`cmd68`）。
  - `redwood_qrtr.c`：记下对端的名字服务查询和发往无人端口的数据，`qrtr_answer=1` 回答查询（`cmd67`）。
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

## 2. 判据（读数之前登记）

| 读数 | 通过 | 不通过时 |
|---|---|---|
| probe | 读到硬件版本主号 2，打印驱动参数表名 `wcn7850 hw2.0` | 记录读到的版本与出错的初始化步骤 |
| 上电与 QMI | 第 7、8 步与 `wf3` 相同；ath12k 自己的 QMI 走到 FW_READY | 记录 ath12k 停在哪条 QMI 消息、错误码 |
| HTC 与 WMI | copy engine 收到 HTC ready，WMI service ready 与 ready 事件到达 | 记录最后一条 WMI 日志与 copy engine 状态 |
| 注册 | 60 秒内出现 `IS UP: the radio is registered`，打印固件给的地址 | 记录驱动的 flag 与最后的 WARN／ERROR |
| 扫描 | `wifi_scan=1` 的扫描完成并列出周围网络 | 记录扫描请求的返回值与扫描事件 |
| 加入网络 | `wifi_join=1`：认证、关联、四次握手通过，日志出现 `THE NETWORK IS JOINED` | 记录停在哪一步（没听到目标网络、认证、关联、握手）与状态码 |
| 数据收发 | `net_trace=` 打出的 en0 帧里，DHCP 请求发出且收到回复，之后有双向的 IP 帧 | 记录发出与收到的帧类型与数量；地址只留在本地日志 |
| 桌面 | 与 `wf3` 一样进到首屏 | 对照 PCIe 步骤与 GPU 的时间先后 |

## 3. 轮次

| 轮次目录 | 内核与 loader | 参数 | 结果 |
|---|---|---|---|
| `kernel-12377-cmd58-wd1` | `12377-cmd58`，loader v14 | `pcie=10 pcie_power=1 wifi_scan=1`，末尾另加 `pcie=9` | 无效：内核取到的是 `pcie=9`，跑了第 9 步替身，结果与 `wf3` 相同（FW_READY，桌面正常），驱动没有启动 |
| `kernel-12377-cmd59-wd2` | `12377-cmd59`，loader v15 | `pcie=10 pcie_power=1 wifi_scan=1` | 驱动启动并完成 probe 与上电；QMI 停在固件内存请求的回复，超时；网卡报 SYS_ERR |
| `kernel-12377-cmd60-wd3` | `12377-cmd60`，loader v15 | 同 `wd2` | 前四项判据中 probe、上电与 QMI、HTC 与 WMI service ready 通过；WMI_INIT 发出后约 190 ms 网卡 SYS_ERR，没有等到 ready 事件 |
| `kernel-12377-cmd61-wd4` | `12377-cmd61`，loader v15 | 同 `wd2` | 与 `wd3` 相同，WMI_INIT 后约 186 ms SYS_ERR；BHI 错误寄存器指向固件 `cmnos_thread_patch.c` 第 1270 行 |
| `kernel-12377-cmd62-wd5` | `12377-cmd62`，loader v15 | 同 `wd2` | s5f 954 mV、s3g 1866 mV 之后崩溃不变：WMI_INIT 后约 186 ms SYS_ERR，ERRDBG 四个值与 `wd4` 相同。电压排除 |
| `kernel-12377-cmd64-wd6` | `12377-cmd64`，loader v15 | 同 `wd2`，加 `pcie_sleep_clock=board` | GPIO3 读回与 Android 相同，崩溃不变。睡眠时钟排除 |
| `kernel-12377-cmd64-wd7` | `12377-cmd64`，loader v15 | 同 `wd6`，加 `pcie_bdf=bd_p11.elf` | `bd_p11.elf` 被固件接受，崩溃不变。板级数据排除 |
| `kernel-12377-cmd65-wd8` | `12377-cmd65`，loader v15 | 同 `wd7`，加 `pcie_fw=3` | linux-firmware 固件进入 mission mode；下发 `bd_p11.elf` 最后一段后约 160 ms SYS_ERR，同一源文件 `cmnos_thread_patch.c`（第 1174 行） |
| `kernel-12377-cmd65-wd9` | `12377-cmd65`，loader v15 | `pcie=10 pcie_power=1 pcie_sleep_clock=board pcie_fw=3 pcie_bdf=lfw-bdf.bin`，不扫描 | linux-firmware 固件配 linux-firmware 的高通参考板 BDF：BDF、M3 被接受，FW_READY；请求 mission 模式后 SYS_ERR，仍是 `cmnos_thread_patch.c` 第 1174 行 |
| `kernel-12377-cmd66-wd10` | `12377-cmd66`，loader v15 | 同 `wd7`，加 `pcie_smps_hpm=1` | 5 路开关稳压器的投票带上高功率模式；崩溃与 `wd7` 相同。稳压器模式排除 |
| `kernel-12377-cmd67-wd11` | `12377-cmd67`，loader v15 | 同 `wd10`，加 `pcie_bt_en=1` | BT_EN 读回为高；崩溃位置不变，只有 ERRDBG1 从 0x21 变成 0x1。网卡没有发过名字服务查询 |
| `kernel-12377-cmd68-wd12` | `12377-cmd68`，loader v15 | 同 `wd11`，加 `pcie_aop_pdc=1 pcie_rddm=1` | AOP 收下 21 条 PDC 配置，崩溃不变。RDDM 转储取回：固件的故障原因是 RAM 分配失败的断言 |
| `kernel-12377-cmd69-wd13` | `12377-cmd69`，loader v15 | `pcie=9 pcie_mission=7`，供电与探针同 `wd12` | 替身的校准：请求 calibration 模式后立即 SYS_ERR，故障原因与 `wd12` 相同 |
| `kernel-12377-cmd70-wd14` | `12377-cmd70`，loader v15 | 同 `wd13`，加 `pcie_ddr_range=1` | 无效：主机能力消息在本机编码失败（-22），没有发出 |
| `kernel-12377-cmd71-wd15` | `12377-cmd71`，loader v15 | 同 `wd14` | 主机能力带上 `ddr_range` 后被接受；固件在处理内存回复时报 fatal 3268 |
| `kernel-12377-cmd72-wd16` | `12377-cmd72`，loader v15 | 同 `wd15`，`pcie_ddr_range=2` | 范围原样用 cnss2 的窗口，主机能力被接受；内存回复后报 fatal 2974 |
| `kernel-12377-cmd72-wd17` | `12377-cmd72`，loader v16 | 同 `wd16` | 无效：`0xA8000000` 被 UEFI 占用，低端内存退回 `0xc77c0000`，结果与 `wd16` 相同 |
| `kernel-12377-cmd73-wd18` | `12377-cmd73`，loader v16 | 同 `wd13`，加 `pcie_features=6` | 网卡不再崩溃；M3 信息之后 10 秒内没有 FW_READY，替身停在这里，见 3.6 |
| `kernel-12377-cmd74-wd19` | `12377-cmd74`，loader v16 | 同 `wd18`，加 `pcie_qdss=1` | QDSS 配置被接受后 FW_READY 到达；请求 calibration 模式后 SYS_ERR，故障与 `wd13` 相同，见 3.6 |
| `kernel-12377-cmd75-wd20` | `12377-cmd75`，loader v16 | 同 `wd19`，加 `pcie_mlo=1` | 校准完成：8162 ms 后 CAL_DONE，OFF 模式成功，没有 SYS_ERR，见 3.6 |
| `kernel-12377-cmd76-wd21` | `12377-cmd76`，loader v16 | 同 `wd12`，加 `wifi_mlo=1` | 驱动启动 380 ms 后注册射频，没有 SYS_ERR；固件没有 MAC 地址，没有建接口，见 3.7 |
| `kernel-12377-cmd76-wd22` | `12377-cmd76`，loader v16 | 同 `wd21`，加 `wifi_mac=` | 与 `wd21` 相同，地址仍为 0：ath12k 不向设备要地址，见 3.7 |
| `kernel-12377-cmd78-wd23` | `12377-cmd78`，loader v16 | 同 `wd22` | 建出 station 接口，扫描 13 秒，听到 12 个接入点，没有 SYS_ERR，见 3.7 |
| `kernel-12377-cmd78-wd24` | `12377-cmd78`，loader v16 | 同 `wd23`，去掉 `wifi_scan=1`，加 `wifi_join=1 net_trace=80` | 找到目标网络；登记接入点失败（-12）：接收队列描述符不在网卡能访问的内存里，见 3.8 |
| `kernel-12377-cmd79-wd25` | `12377-cmd79`，A 槽 loader v14 | 同 `wd24` | 无效：没有触发检查点，旧 loader 不留低端 DMA 内存 |
| `kernel-12377-cmd79-wd26` | `12377-cmd79`，loader v16 | 同 `wd24` | 认证、关联通过；四次握手超时（reason 15）：握手回复按以太网帧发出，硬件当成 802.11 帧，见 3.8 |
| `kernel-12377-cmd80-wd27` | `12377-cmd80`，loader v16 | 同 `wd24` | 加入网络；en0 收到 375 帧，发出 0 帧（iOS 没有发起 DHCP），见 3.8 |
| `kernel-12377-cmd80-wd28` | `12377-cmd80`，loader v16 | 同 `wd24`，加入后经 `rsh.py` 发 `net_test` | DHCP 拿到地址，ARP 解析了路由器；iOS 26 不把这个服务选为主服务，解析与取网页失败，见 3.8 |

### 3.1 驱动起步（`wd2`～`wd4`）

- 驱动的内存池起点 `0xc77c0000`；BAR0 在 `0x40400000`（2 MiB），硬件版本 `0x40170200`，参数表 `wcn7850 hw2.0`。驱动上电时内核的第 7、8 步与 `wf3` 相同，约 567 ms 进入 mission mode。
- `wd2`：回复固件内存请求时超时（`-60`）。替身给固件的两段内存按大小对齐，驱动的分配只按页对齐；`12377-cmd60`、`cmd61` 让一页以上的分配按大小对齐到 2 的幂次（上限 16 MB），内存池扩到 96 MB。`wd2` 没有 ath12k 的调试行，原因是 `mk-ath12k.sh` 检查重编的脚本路径有误，`cmd60` 起改正。
- `wd3`：QMI 走到 FW_READY 与 mission 模式；HTC 就绪（2 个发送额度，Control、HTT Data、WMI 三个服务）；WMI service ready、ext、ext2 到达（3 种硬件模式，首选 5 即 DBS）。WMI_INIT 之后约 190 ms SYS_ERR。
- `wd4`：M3 改为对齐后崩溃不变。WMI_INIT 之后先收到事件 `0x16005`（ath12k 编号里是 STATS 组的 `WMI_UPDATE_FW_MEM_DUMP_EVENTID`，驱动不处理），约 180 ms 后 SYS_ERR。BHI 错误寄存器指向固件 `cmnos_thread_patch.c` 第 1270 行，读法见 [Android cnss2 对照](../analysis/2026-11-01-android-cnss2-wlan-bringup.md) 第 5 节。

### 3.2 逐项换成 Android 的做法（`wd5`～`wd12`）

每轮换一项，崩溃位置与时刻都不变，这些项全部排除：电压（`wd5`）、睡眠时钟（`wd6`）、板级数据 `bd_p11.elf`（`wd7`）、开关稳压器高功率模式（`wd10`）、BT_EN（`wd11`）、AOP 的 WLAN PDC 配置（`wd12`）。同时读到的仍然有用的事实：

- PMK8550 GPIO3（睡眠时钟输出）：loader 起的系统里是输入加下拉（MODE_CTL 0、DIG_PULL_CTL 0x4），Android 是 func1 输出（MODE_CTL 0x01、DIG_PULL_CTL 0x05、DIG_OUT_SOURCE_CTL 0x02）。`pcie_sleep_clock=board` 写入后读回与 Android 一致。
- BT_EN（PM8550VE-F GPIO3）：写入前是输入加下拉，`pcie_bt_en=1` 写入后读回输出高电平。
- QRTR：网卡只发 HELLO 和 WLFW 服务（69）的通告，没有名字服务查询，`qrtr_answer=1` 用不上。
- AOP 邮箱开机时我方链路为 up、通道为 down，内核重新握手后打开，21 条 `wlan_pdc` 消息都被收下。
- `wd12` 打印的 `0x16005` 内容是 16 字节：TLV 标签 0x18d、长度 8，两个值 `0xc7d9f640`、`0x24024`，第一个值落在驱动的内存池里。

### 3.3 linux-firmware 的固件（`wd8`、`wd9`）

`pcie_fw=3` 换成 linux-firmware 给 ath12k 的 WCN7850 固件 `WLAN.HMT.1.1.c7-00108`，547 ms 进入 mission mode。配 `bd_p11.elf` 时在 BDF 最后一段之后约 160 ms SYS_ERR；配 linux-firmware 的参考板 BDF（`lfw-bdf.bin`）时在请求 mission 模式后 SYS_ERR。两次都报同一源文件的第 1174 行，没有转储，没有继续追。

### 3.4 RDDM 转储与故障点（`wd12`、`wd13`）

- `pcie_rddm=1` 留的接收向量被网卡使用，SYS_ERR 后写入 4,837,542 字节，`run-auto.py` 收尾时取回 `rddm.bin`。格式与读法见 [Android cnss2 对照](../analysis/2026-11-01-android-cnss2-wlan-bringup.md) 第 5 节。
- 故障原因 `cmnos_thread_patch.c:1270:0x8Asserted in:0x1f26a9c:0x1f269ac, line#386`：定位服务的初始化（`0x189f7d8`）按 min(n, 3) 与 n − 3 建两个池，n 为 0，n − 3 成了 `0xfffffffd`，ROM 的池分配报 fatal 386。
- `wd13` 用替身单独跑冷启动校准（`pcie=9 pcie_mission=7`），请求 calibration 模式后在同一处崩溃，出错线程的栈从 `0x18b9ad8` 往上与 `wd12` 相同。
- 转储里固件对主机内存的映射：芯片地址 `0x048b0000` 对应主机 `0xca000000`（类型 4 段），`0x04000000` 起对应类型 1 段。

### 3.5 `ddr_range`（`wd14`～`wd17`）

cnss2 在主机能力里发 `ddr_range` = `{0x98000000, 0x18010000}`（SMMU 的 IOVA 窗口），ath12k 不发。这一组轮次证实的固件约束：

- ath12k 的 `ddr_range` 描述项缺成员描述，编码器拒绝（`wd14`，-22）；替身改用补全的副本。
- 发了范围时，各项终点的最大值必须等于 `0xb0010000`，否则 fatal 3268（`wd15`，检查在 `0x185dccc` 之前）。
- 范围原样用 cnss2 的窗口、内存不在窗口里时，内存回复后 fatal 2974（`wd16`）。
- UEFI 内存表（`oem memmap`）里窗口内只有 `0xa6180000`～`0xa7000000` 这 14 MB 空闲，`0xa8000000` 起是保留，loader v16 的固定地址申请失败（`wd17`）。照 Android 发范围需要 SMMU 翻译。

不发 `ddr_range` 时校准与 mission 模式都能完成（3.6、3.7），这条路线暂停。

### 3.6 根因：MLO 字段（`wd18`～`wd20`）

- `wd18`：功能列表换成 cnss2 的 0x6 后，M3 信息之后 10 秒内没有 FW_READY，整轮没有崩溃。
- `wd19`：再下发 QDSS 配置（4939 字节，一段），FW_READY 紧接着到达。功能列表为 0x6 时固件要等这份配置，0x18 时不需要。之后请求 calibration 模式，仍是 fatal 386，栈与 `wd13` 相同。
- 对照转储与反汇编，n 来自主机能力里的 `max_mlo_peer`。固件只在主机发了 MLO 那组字段时才写入它；cnss2 对 WCN7850 总会发（`max_mlo_peer` 32），ath12k 只在 PHY capability 报告支持单芯片 MLO 时才发，这版固件报 0。代码路径见 [Android cnss2 对照](../analysis/2026-11-01-android-cnss2-wlan-bringup.md) 第 5 节。
- `wd20`：补上 MLO 字段后，calibration 模式请求成功，8162 ms 后收到 CAL_DONE（Android 为 8216 ms），OFF 模式成功，没有 SYS_ERR。
- `wd4`～`wd11` 没有转储，崩溃点同在第 1270 行、ERRDBG 一致，推测同一原因。

### 3.7 ath12k 扫描（`wd21`～`wd23`）

- `wd21`：`wifi_mlo=1`（功能列表保持 0x18，不发 QDSS），WMI_INIT 之后没有 SYS_ERR，驱动启动 380 ms 后注册射频。信道：2.4 GHz 14 个、5 GHz 27 个、6 GHz 60 个，监管域 US 允许其中 11、27、60 个。固件给的地址是全 0，驱动不建接口。
- `wd22`：加 `wifi_mac=`（本地管理地址，首字节 0x02）后地址仍为 0。ath12k（Linux 7.0.14）只从 WMI ready 事件取地址，不调 `device_get_mac_address()`；`12377-cmd78` 在 LinuxKPI 的 `ieee80211_register_hw()` 里补上：地址为 0 时用内核的 `wifi_mac`。
- `wd23`：射频注册时有地址，station 接口建立。扫描 98 个信道，13079 ms 完成，听到 12 个接入点（2.4 GHz 9 个、5 GHz 3 个，-20～-96 dBm），网络名与 BSSID 只留在本地日志。扫描之后监管域变为 CN（4 条规则），6 GHz 信道全部不可用。
- 判据「注册」「扫描」通过。加入网络与数据收发还没验证：`wifi_join=1` 要本地固件目录里的 `network` 文件（第一行网络名，第二行密码），由用户提供。

### 3.8 加入网络（`wd24`～）

- `wd24`：`12377-cmd78`，参数同 `wd23`，去掉 `wifi_scan=1`，加 `wifi_join=1 net_trace=80`，本地 `network` 文件放进 RAM 盘。起轮前手机在 Android（A 槽重试用完回退到 B 槽），`cycle.py` 经 LK 自动回到 loader。
  - 目标网络在 5 GHz 40 信道，-21 dBm，WPA2-PSK、CCMP；密钥 19 ms 算完，信道 20 MHz 设好。
  - 驱动登记接入点时失败（-12），前一行是 `memory is given to the radio that it cannot reach (1536 bytes)`。原因：ath12k 的 REO 接收队列描述符（每个 traffic class 一份）用 `kzalloc()` 分配后 `dma_map_single()` 交给硬件，这块内存不在网卡能访问的池里。
  - `12377-cmd79` 的改法：LinuxKPI 头文件补丁让 `dma_map_single()` 把指针传下来；不在池里的内存复制进池里的一个 4 KB 槽，网卡拿到槽的地址，解除映射时复制回来并归还槽。ath12k 映射之后到解除映射之间不碰这块描述符。
- `wd25`：无效。起轮前没有触发检查点，跑的是 A 槽里刷着的旧 loader（v14），它不给 `pcie=10` 留低端 DMA 内存，驱动没有建起内存池。
- `wd26`：同 `wd25`，强制检查点，用 `fastboot boot` 起 loader v16。
  - 接入点登记成功，认证与关联都被接受（我们是它的第 5 个 station）。四次握手收到第 1 条消息并回了第 2 条，接入点又重发两次第 1 条，3077 ms 后以 reason 15（握手超时）解除认证。
  - 原因：我们的握手回复按以太网帧交给驱动（`IEEE80211_TX_CTL_HW_80211_ENCAP`）。ath12k 的 Wi-Fi 7 发送描述符里没有逐帧的封装类型，封装方式取自接口的 bank 配置；这版固件不支持以太网卸载（没有 `WMI_TLV_SERVICE_ETH_OFFLOAD`），接口是 native wifi，硬件把以太网头当成 802.11 头发出。ath11k 的描述符有逐帧的封装字段，原来的写法在那边可用。
  - `12377-cmd80` 的改法：接口没开以太网卸载时，`lx_ethernet_send()` 按 mac80211 的做法组 802.11 数据帧：发往接入点，接入点有 WMM 时用 QoS data（握手 TID 7，其余 TID 0），类型前加 LLC/SNAP，有密钥后标记受保护，由硬件加密。
- 第九批第一轮 `wd27`：`12377-cmd80`，参数同 `wd26`。
  - 判据「加入网络」通过：四次握手完成，关联后 114 ms 两把密钥交给驱动，日志出现 `THE NETWORK IS JOINED`，en0 的链路变为 up。
  - en0 收到 375 帧（约 180 KB），都是局域网里其他设备的广播与组播（SSDP、mDNS、ARP、IGMP 等），组播密钥解密正常。en0 发出 0 帧，iOS 没有发起 DHCP，判据「数据收发」未通过。
  - 原因：`wifi_join` 由内核自己加入网络，wifid 问 apple80211 的 CURRENT_NETWORK 61 次都被拒绝（error 6），它认为没有连上，configd 也不跑 DHCP。以前那台设备靠开机任务 `net_test wifi` 补一个 DHCP 请求，这个任务只在启动参数有 `wifi=1` 时才动作，而 `wifi=1` 在 K90 的内核里会同时打开旧芯片的一组选项，不能用。
- 第九批第二轮 `wd28`：内核与参数同 `wd27`。日志出现 `THE NETWORK IS JOINED` 后，经 `rsh.py` 在设备上依次执行 `net_test dhcp en0`、`waitaddr en0 12`、`resolve`、两次 `fetch`（http 与 https）、`reach`。判据：拿到 IPv4 地址，域名能解析，两次 `fetch` 都有状态行。
  - 开机约 100 s 后加入网络。`net_test dhcp en0` 之后 0.8 s en0 拿到 IPv4 地址；服务状态里有路由器、DNS 服务器，路由器的 ARP 已解析。驱动层收发两个方向都通过。
  - 域名解析立即失败，两次 `fetch` 报 `NSURLErrorDomain -1009`（离线），`reach` 为不可达。configd 没有 `State:/Network/Global/IPv4`，全局 DNS 为空：`dhcp en0` 建的服务不在 `Setup:/Network/Service` 里（Setup 下一个服务都没有），iOS 26 的 configd 不把它选为主服务。以前那台设备的 iOS 16.5 用同样的做法能解析、能取网页。
  - 结论：Wi-Fi 驱动的扫描、加入网络、收发都已在本机验证；应用能上网还差 iOS 26 网络栈的接入（configd 的网络服务与主服务选择，或者 wifid 经 apple80211 驱动加入网络），属于用户态集成，另开一项。

