# K90 蓝牙接入调研（2026-11-02）

本文回答蓝牙能不能在 K90 的 iOS 26 上起来，以及按什么顺序做。只读调研：读了本仓库源码、Android 设备树、`bluetooth_a` 分区里的固件清单和参考仓库 dada（小米 15，同为 SM8750 上的 iOS 26）的内核补丁，没有操作设备，也没有构建。早先的方案（内核按高通流程起芯片、按 Broadcom 回答身份）见 [Wi-Fi 与蓝牙可行性](2026-10-28-wifi-bluetooth-feasibility.md) §3。

引用写法：`P:行号` 是 dada 的 `kernel/xnu-12377.121.6-dada.patch`；`dada:` 开头是该仓库里的路径；`DTS:行号` 是解压后的 `docs/analysis/data/annibale.dts.gz`。

## 1. 需要用户决定的事

1. 系统盘带上 `bluetoothd`。它有 12,151,072 字节，超过 `hackios-xnu-kernel/ios165/select-system.py` 里 `BIG_PROGRAM`（10 MB）的上限，现在不在系统盘上。放进去要重做 `system26.apfs` 和 Android DSU 里那份，系统盘的哈希会变。
2. 蓝牙与 Wi-Fi 共用电源轨和 BT_EN。蓝牙轮次要在 Wi-Fi 上电之后进行，并且 Wi-Fi 在线时不能拉低 BT_EN；两者同时在线的情况 dada 没有验证过（它的蓝牙验证轮把 Wi-Fi 设成只读模式）。
3. 第一阶段按 115200 波特跑，只够 BLE 扫描和 HID 一类低速设备，蓝牙音频要等提速到 3 Mbaud 之后再看。

## 2. 结论

- 能做。iOS 26 一侧的接法 dada 已经走通到「蓝牙已打开、BLE 能扫描」：`dada:base/tools/dada-ios.sh:19` 记的是 `verified w94z3: PoweredOn, LE scan`。仓库里没有配对、经典蓝牙或蓝牙音频的记录。
- K90 的蓝牙芯片与 Wi-Fi 是同一颗 WCN7850（kiwi），蓝牙走 SE14 的 UART，电源轨大部分已经由现有 Wi-Fi 代码投票打开。剩下的工作是四块：SE14 UART 驱动与高通固件下载、给 `bluetoothd` 的 Skywalk 通道、BlueTool 替身、系统盘与启动任务的改动。估计 1200 行左右内核与用户态代码，各文件按 AGENTS.md §2 控制在 1200 行以内。
- 早先文档说 12377 内核没有 Skywalk，这一点不成立：`hackios-xnu-kernel/xnu26/files/config/MASTER.arm64.bcm2837` 的 `DEVELOPMENT` 带 `SKYWALK_DEV`，`out/xnu12377-rate7.bin` 里有 `nx_kpipe_*` 与 `kern_nexus_register_domain_provider`。

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

- `hackios-xnu-kernel/xnu/files/bsd/dev/redwood_bt_probe.c`（boot-arg `bt_probe=1`）：注册两个控制套接字名，只记日志，getopt 回零（:131-144），所以 `bluetoothd` 拿到的是空的 nexus UUID。已编进内核，没有上机跑过。
- BT_EN：`mhi_pcie_power.c:419-442,771-774`（`pcie_bt_en=1`），wd11 读回为高（[驱动接入记录](../progress/2026-11-01-wifi-ath12k-driver.md)）。
- 电源轨：`mhi_pcie_power.c:199-210` 的 Wi-Fi 电源表已经覆盖蓝牙的各路供电和 RF_CLK1。
- 可复用：固件读取 `redwood_image_file("fw", …)`（`mhi_pcie_fw.c:48`）；QUP1 上轮询的 GENI SPI 驱动（`redwood_touch_bus_private.h:253-260`）；loader 已经传入 `mac-address-bluetooth0`（`xnuloader/loader_05_layout_run_kernel.inc:724,731`）。
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

| 步 | 内容 | 成功判据 | 设备 |
|---|---|---|---|
| 0 | 离线：固件按 `BT_FW=1` 打进 RAM 盘 `fw/`（约 0.9 MB）；新文件 `annibale_bt_uart.c`（取 P:12488-12974、13651-13745，改用我们的 `pmic_gpio`、SPMI 锁和 `redwood_image_file`）、`annibale_bt_ios.c`（P:13043-13649）、`annibale_btsk.c`（P:3689-3965）、`RedwoodBT.cpp`；BlueTool 替身 | 能编译，Skywalk 符号能链接 | 否 |
| 1 | 只起硬件：`bt=3`，叠在 `pcie=10 pcie_power=1 pcie_bt_en=1` 之上 | SE14 协议寄存器读出 2（UART）；ROM 版本 0x20；板号对应到现有的 `hmtnv20.b*`；补丁下发后版本串与 `hmtbtfw20.ver` 一致；Reset 成功；厂商号 0x1d；内核自己的 LE 扫描看到至少一台设备 | 是 |
| 2 | 接上 iOS：`bt=4`；`ALLOW=bluetooth`；`bluetoothd` 任务带 KeepAlive 和两个环境变量；BlueTool 指向替身；关掉低功耗扫描的偏好设置；开机时用 loader 的 MAC 设 `local-mac-address`，同一 MAC 写进 NVM tag 2 | 日志出现 `connected to com.apple.uart.sk.bluetooth`、`btsk: channel is connected`、`iOS sends (channel): 01 03 0c 00`；`bluetoothd` 不退出；设置里蓝牙开关为开（截图）。日志里的 `chip refuses 0x…` 行补进下一轮的代答表 | 是，最多 3 轮一批 |
| 3 | 配对一台 BLE 设备（如 HID 键盘）；提速到 3 Mbaud（0xFC48 加 GENI 时钟），收端改中断（GIC SPI 0x1cd） | 配对成功，按键进 iOS | 是 |
| 4 | 蓝牙音频 | 待第 3 步之后再评估 | 是 |

第 2 步与我们的架构有一处不同：我们没有 dada 的 exec 环境注入和可执行文件替换。先改系统盘里任务 plist 的环境变量；如果 launchd 不认（dada 在 w81n1 遇到过），再移植那两个钩子，约 150 行。

## 7. 风险与未知

- SE14 可能没有 UART 固件：协议寄存器读出的值不为 2 时，要先做 QUP 固件加载，工作量大。
- HAMILTON 与 ganges 不同：芯片拒绝的命令、需要代答的命令、厂商命令的行为大概率不一样。
- 与在线 Wi-Fi 共存没有验证：切 BT_EN 可能让 WLAN 固件出错（推断）。
- `bluetoothd` 第一次启动前地址要准备好：dada 靠 launchd 每 10 秒左右重启 `bluetoothd`（P:81621-81622），我们的 REST 任务没有 KeepAlive。
- 内核吞掉了 Broadcom 的 Write_BD_ADDR，iOS 报的地址可能和芯片实际地址不同，配对时可能出问题（推断）。
- dada 用的 `bluetoothd` 偏移来自 iPhone18,1 的 23G90，我们的 iPhone18,3 二进制还没有抽出来核对。

最有用的第一个真机实验是第 1 步：不改 iOS，一轮就能确定 SE14 是否为蓝牙链路、UART 固件在不在、ROM 版本、该用哪个 NVM、补丁是否被接受、射频能否收到广播。
