# K90 蓝牙接入调研（2026-11-02）

本文回答蓝牙能不能在 K90 的 iOS 26 上起来，以及按什么顺序做。只读调研：读了本仓库源码、Android 设备树、`bluetooth_a` 分区里的固件清单和参考仓库 dada（小米 15，同为 SM8750 上的 iOS 26）的内核补丁，没有操作设备，也没有构建。

引用写法：`P:行号` 是 dada 的 `kernel/xnu-12377.121.6-dada.patch`；`dada:` 开头是该仓库里的路径；`DTS:行号` 是解压后的 `docs/analysis/data/annibale.dts.gz`。

本文的源码状态与推断对应 11-02 调研，后续硬件与 iOS 扫描实测见第 8 节。配对、重连与蓝牙音频的剩余验收见[平台待办](../backlog/platform.md)。

## 1. 需要用户决定的事

`bluetoothd` 已加入系统盘，UART、固件下载与 iOS 接入已完成真机扫描验证，见第 8 节；3 Mbaud 提速已落地，见[11-06 至 11-07 推进记录](../plan/2026-11-06-issues-and-followup.md)。后续验收见[平台待办](../backlog/platform.md)。

蓝牙与 Wi-Fi 共用电源轨和 BT_EN。蓝牙须在 Wi-Fi 上电之后启动，Wi-Fi 在线时不能拉低 BT_EN。

## 2. 结论

- 能做。iOS 26 一侧的接法 dada 已经走通到「蓝牙已打开、BLE 能扫描」：`dada:base/tools/dada-ios.sh:19` 记的是 `verified w94z3: PoweredOn, LE scan`。仓库里没有配对、经典蓝牙或蓝牙音频的记录。
- K90 的蓝牙芯片与 Wi-Fi 是同一颗 WCN7850（kiwi），蓝牙走 SE14 的 UART，电源轨大部分由 Wi-Fi 代码投票打开。实现涉及 SE14 UART 驱动与高通固件下载、给 `bluetoothd` 的 Skywalk 通道、BlueTool 替身，以及系统盘与启动任务的改动，后续实测见第 8 节。
- 12377 内核带 Skywalk：`hackios-xnu-kernel/xnu26/files/config/MASTER.arm64.bcm2837` 的 `DEVELOPMENT` 带 `SKYWALK_DEV`，`out/xnu12377-rate7.bin` 里有 `nx_kpipe_*` 与 `kern_nexus_register_domain_provider`。

## 3. dada 的做法

代码里能看到的部分：

- 传输：SE14（QUP2 SE6，0x898000）的四线 UART，GPIO24 CTS、25 RFR、26 TX、27 RX，功能 1（P:12488-12496）；轮询收发，没有用中断（P:13043-13050）。
- 上电：BT_EN 是 PM8550VE SID5 的 GPIO3，经 SPMI 写（P:12517-12526）；电源轨沿用 Wi-Fi 的 `rails()`、`sleep_clock()`（P:14785-14797），蓝牙只在 Wi-Fi 上电线程里启动。
- 串口：S6 时钟设成 7.3728 MHz，得到 115200 波特，8N1 带流控，一直不提速（P:12578-12647）。
- 固件：按 Linux `btqca` 的顺序读版本（0xFC00/0x19）与板号（0x23），再按 243 字节一段下发 TLV 补丁和 NVM（P:12818-12974）。NVM 下发前改两处：tag 17 关掉带内睡眠、保持 115200，tag 27 关掉深睡。之后发 HCI Reset、Read_BD_ADDR、Read_Local_Version（P:13708-13736）。
- 让 iOS 接受：
  - `bluetoothd` 的环境变量 `BT_HCI_TRANSPORT=H4:POSIX;BT_CHIP=ACI~BT`（`~` 代表空格），由内核在 exec 时注入（P:56146-56182，`dada:base/tools/dada-ios.sh:40-41`）。没有 `BT_CHIP` 时 `bluetoothd` 会崩（`dada:userland/userland/build.sh:682-683`）。
  - BlueTool 换成 73 行的 XPC 替身，对每个脚本都回 0，厂商号回 15（Broadcom）（P:55710-55728，`dada:userland/userland/src/bluetool.c:1-42`）。
  - 内核注册 `com.apple.uart.sk.bluetooth` 控制套接字，getopt `0x5412` 返回 nexus UUID（P:13167-13207），H4 数据走 Skywalk kernel pipe（P:3695-3965）。
  - 发布名为 `bluetooth`、带 `local-mac-address` 的 IOService；没有它时 `bluetoothd` 报 `No bluetooth on this device` 退出（P:81522-81556）。
  - 开机建 `/dev/cu.bluetooth` 与 `/dev/uart.bluetooth`（P:13586-13625）。
  - 内核替芯片回答一部分命令：所有 0xFCxx 厂商命令回状态 0 加 9 字节（P:13387-13502），0x0c5a、0x0c5b 以及 boot-arg `dadabt_fake` 列出的命令同样代答，Supported Commands 的第 18 字节置位 2、3 位（P:13272-13298）。
  - 一份偏好设置关掉苹果低功耗协处理器的扫描（厂商命令 0xfdd7）（`dada:userland/userland/src/init.c:1021-1046`）。
- dada 的芯片是 FastConnect 7900（P:11128），蓝牙固件是 ganges 的 `gng*`（`dada:userland/userland/build.sh:749-751`），与 K90 的不同。补丁按 APSL-2.0 发布（`dada:NOTICE.md`），可以参考移植。

## 4. 我们现在有什么

- `hackios-xnu-kernel/xnu/files/bsd/dev/annibale_bt_probe.c`（boot-arg `bt_probe=1`）：注册两个控制套接字名，只记日志，getopt 回零（:131-144），所以 `bluetoothd` 拿到的是空的 nexus UUID。已编进内核，没有上机跑过。
- BT_EN：`mhi_pcie_power.c:419-442,771-774`（`pcie_bt_en=1`，`cycle.py` 的默认参数带着它），wd11 读回为高（[驱动接入记录](../progress/2026-11-01-wifi-ath12k-driver.md) 3.2）。
- 电源轨：`mhi_pcie_power.c:199-210` 的 Wi-Fi 电源表已经覆盖蓝牙的各路供电和 RF_CLK1。
- 可复用：固件读取 `annibale_image_file("fw", …)`（`mhi_pcie_fw.c:48`）；QUP1 上轮询的 GENI SPI 驱动（`annibale_touch_bus_private.h:253-260`）；loader 已经传入 `mac-address-bluetooth0`（`xnuloader/loader_05_layout_run_kernel.inc:724,731`）。
- iOS 一侧的阻碍：
  - `bluetoothd` 不在系统盘上（§1）。
  - `hackios-xnu-userland/userland/mkjobs.py:218` 的 DENY 含 `bluetooth`。
  - REST 任务去掉了 KeepAlive（`tools/k90auto/package.py:263-266`）。
  - `JOB_ENV` 按空白切分（`package.py:181-186`），`ACI BT` 要转义。

## 5. K90 的硬件

- 芯片：kiwi / WCN7850，`supported-ids 0x1107`（[硬件地图](annibale-hw-map.md)）。
- 串口：SE14 `qcom,msm-geni-serial-hs`，0x898000，`qcom,wakeup-byte = <0xfd>`（高通带内睡眠的唤醒字节），收端唤醒脚 TLMM 27（DTS:25598-25615）；引脚 GPIO24-27，功能 `qup2_se6_l*`（DTS:2090-2213）。与 dada 同一颗 SoC，GCC、TLMM、SE 的偏移应能直接沿用（推断）。
- `bt_kiwi` 节点（DTS:41764-41796）：供电 smpg3、smpi7、smpd1、ldok6、ldof2、ldof3；复位 pm8550ve GPIO3；sw-ctrl GPIO18、wl-reset GPIO16；时钟 rpmhcc 6（`bt_rf_clk1`）。loader 起来时 BT_EN 是带下拉的输入，芯片从 ROM 冷启动。
- 固件（`bluetooth_a` 分区）：`hmtbtfw20.tlv`（275,208 字节，`BTFW.HAMILTON.2.0.1-00450-PATCHZ-1.131051.2`）、`hmtnv20.bin` 和 60 个 `hmtnv20.b<板号>` 变体。dada 的 NVM 文件名格式 `%sbtnv%02x.b%02x`（P:12967）对不上，要改。

## 6. 实施顺序

UART、固件下载与 iOS 接入的实现文件、调用参数和真机结果见第 8 节；3 Mbaud 提速见[11-06 至 11-07 推进记录](../plan/2026-11-06-issues-and-followup.md)。配对、重连、地址一致性与蓝牙音频验收见[平台待办](../backlog/platform.md)。

## 7. 风险与未知

- HAMILTON 与 ganges 不同：芯片拒绝的命令、需要代答的命令、厂商命令的行为大概率不一样。
- 切 BT_EN 可能让 WLAN 固件出错（推断）；第 8 节的 BLE 扫描已与在线 Wi-Fi 同时运行。
- `bluetoothd` 首次启动前需要准备好地址。dada 的任务由 launchd 每 10 秒左右重启（P:81621-81622），本仓后续通过任务 `KeepAlive` 保持服务运行，见第 8 节。
- 内核替芯片回答 Broadcom 的 Write_BD_ADDR，这条命令不到芯片，iOS 报的地址可能和芯片实际地址不同，配对时可能出问题（推断）。
- dada 用的 `bluetoothd` 偏移来自 iPhone18,1 的 23G90，我们的 iPhone18,3 二进制还没有抽出来核对。

剩余验证见[平台待办](../backlog/platform.md)。

## 8. 实测（2026-11-05）

固件打包、硬件启动与 iOS 接入已在 K90 真机通过。实现文件包括内核侧 `hackios-xnu-kernel/xnu/files/bsd/dev/annibale_bt_uart.c`、`annibale_bt_ios.c`、`annibale_btsk.c`、`annibale_bt_private.h`、`iokit/KernelConfigTables.cpp`（`AnnibaleBT` IOService），用户态 `hackios-xnu-userland/userland/src/bluetool.c`、`ios165/select-system.py`（补入 `usr/sbin/bluetoothd` 并更新 DSU 系统盘），以及打包脚本 `tools/k90auto/package.py` 与 `tools/k90auto/cycle.py`（默认带 `bt=4`）。

### 8.1 第 1 步硬件起机（`kernel-12377-st2-r1`）

- SE14（QUP2 SE6，`0x898000`）协议寄存器 `GENI_FW_REVISION_RO` 读出 `0x20a`，协议号为 2（UART），无需额外加载 QUP 固件。
- WCN7850 在 115200 波特下回应 `0xfc00/0x19` 与 `0xfc00/0x23`，ROM 版本为 `0x20`（soc `0x401a0200`），板号为 0，匹配 `/fw/hmtbtfw20.tlv`（275,208 字节，1,134 段）与 `/fw/hmtnv20.bin`（10,305 字节，43 段）。
- 补丁与 NVM 下发耗时约 28 秒，HCI Reset 后读回本地地址 `02:4b:39:30:00:02`、HCI 13／LMP 13、厂商号 `0x001d`（Qualcomm），芯片自启动后主动上报 `BTFW.HAMILTON.2.0.1-00450-PATCHZ-1.131051.2`。
- 内核发起 5 秒 LE 扫描，收到 295 条广播报告、去重后发现 43 个周边 BLE 设备，与在线 Wi-Fi（ath12k，`en0`）同时运行无冲突。

### 8.2 第 2 步接入 iOS 26 与 `0x204a` 扩展广播锁定问题（`st3-r1`、`st4-r1`、`st4-r2`）

- `package.py` 在 `out/fw-bt` 存在时默认开启 `BLUETOOTH=1`：编译 `/annibale/bin/bluetool` 替身并替换 `com.apple.BlueTool.plist`，放行 `mkjobs.py` 的 `bluetooth` 任务，为 `com.apple.bluetoothd.plist` 设置 `KeepAlive=true` 与 `BT_HCI_TRANSPORT=H4:POSIX`、`BT_CHIP=ACI BT`。不必依赖内核 exec 环境注入，launchd 缓存里的 `EnvironmentVariables` 直接生效。
- `st3-r1` 首次跑 `bt=4` 时，`bluetoothd` 连上 `com.apple.uart.sk.bluetooth` 与 Skywalk 通道，完成协议栈初始化（`Stack initialization complete`），但在启动扫描时连续报 `STATUS 712`（HCI 状态码 `0x0c` Command Disallowed），日志记录 `bt: the chip refuses 0x2007 with status 0x0c` 与 `0x200b with status 0x0c`。
- 根因定位：`bluetoothd` 在初始化阶段发送 `0x204a`（`HCI_LE_Read_Periodic_Advertiser_List_Size`）。按 Bluetooth Core Spec Vol 4 Part E §3.1.1，`0x204a` 属于扩展广播命令表（Table 3.2，`0x2035`～`0x204a`）；WCN7850 收到任一扩展广播命令后即将当前会话锁定为 Extended Advertising 模式，拒绝后续传统广播与扫描命令（Table 3.1 的 `0x2007`、`0x200b` `LE_Set_Scan_Parameters`、`0x200c` `LE_Set_Scan_Enable`）。
- 修复与验证：在 `annibale_bt_ios.c` 的 `bt_answer_vendor()` 代答表中加入 `0x204a`（带 1 字节附加载荷 `0x00`，完整代答 `04 0e 05 01 4a 20 00 00`），不向芯片转发该命令。`kernel-12377-st4-r1` 重测后，`0x2007`、`0x200b`、`0x200c` 全部返回状态 0，`bluetoothd[47]` 全程无重启（`pid 47`），扫描状态进入 `Starting(2) --> Scanning(3)`，发现 9 台 BLE 设备并解析出 Apple Continuity 广播（`id:4C`）；控制中心蓝牙按钮高亮为开启，设置主页显示 `Bluetooth On`，点入 `Settings -> Bluetooth` 页面开关为绿色开启、底部显示 `This iPhone is discoverable as "iPhone" while Bluetooth Settings is open.` 与 `Devices` 扫描动画（`kernel-12377-st4-r1/run/tour-sheet.png`）。

