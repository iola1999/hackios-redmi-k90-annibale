# K90 Wi-Fi：WCN7850 固件启动（2026-10-31）

PCIe 链路、BAR0 与 MHI 寄存器的勘察见 [PCIe 勘察与上电记录](2026-10-26-wifi-pcie-survey.md)：网卡停在 PBL，固件还没下载，卡在 apps SMMU 怎么处理端点 DMA。小米 15 参考仓库（同为 SM8750）已把它的网卡启动到 WMI，做法见 [参考仓库对照](../analysis/2026-10-31-dada-reference-comparison.md) §6.3。本文记录按这套做法启动 WCN7850 固件的改动、判据与轮次。

## 1. 改动

- loader v14（`xnuloader/loader_05_layout_run_kernel.inc`）：载荷参数里有 `pcie=7`～`pcie=9` 时，在 4 GB 以下申请 128 MB，经 `lowdma=`、`lowdma_mb=` 交给内核。只在第一次请求时申请，之后各轮沿用。
- 内核 `12377-cmd55`，PCIe 勘察的第 7 步（`pcie=7`，要求 `pcie_power=1`，`xnu/files/bsd/dev/mhi_pcie_fw.c`）：
  - PCIe 控制器打开 BDF→SID 表，RID 0x100 写在槽位 0x15，对应流 0x1401；
  - apps SMMU 给流 0x1400、0x1401 各分一个空闲匹配项，指向最后一个 context bank，该 bank 设为不做地址转换；流已有匹配或最后一个 bank 正在转换时停止；
  - 按 ath12k 的 WCN7850 流程给网卡上电（LTSSM、热复位、清中断与 BHIe 门铃、全局复位、MHI 复位），MSI 指向一页没人读的内存，关 ASPM；
  - 用 UniXNU 的 MhiBoot（`mhi_boot.c`）经 BHI 下载引导程序，READY 后写 MHI context，请求 M0，再经 BHIe 下载完整固件，等 mission mode；
  - 固件取 RAM 盘 `fw/` 下的 `amss20.bin`（SoC 版本寄存器的主版本为 2 时）或 `amss.bin`，`pcie_fw=1`／`2` 可指定。
- `tools/k90auto/package.py` 的 `WIFI_FW=1` 把本地从 modem 分区解出的 `amss.bin`、`amss20.bin` 放进 RAM 盘的 `fw/`，清单记录两者的 SHA-256。

## 2. 判据（读数之前登记）

| 读数 | 通过 | 不通过时 |
|---|---|---|
| SID 表与 SMMU | 打印 `stream 0x1401 passes through` 或已有匹配可直通 | 记录 SMR／S2CR 与最后一个 bank 的状态，下一轮只读这些寄存器 |
| BHI | 进入 `waiting for READY`，随后 `contexts` | 记录 BHI 状态与错误码；USB 中断或手机复位时下一轮加 `pcie_pause=25` 定位最后一步 |
| BHIe 与 mission mode | `the end ... done`，执行环境 2（AMSS） | 记录停在哪个阶段、BHIe 状态与执行环境 |
| 桌面 | 与 `bo63` 一样进到桌面 | 对照 PCIe 步骤与 GPU 的时间先后 |

## 3. 轮次

| 轮次目录 | 内核与 loader | 参数 | 结果 |
|---|---|---|---|
| `kernel-12377-cmd55-wf1` | `12377-cmd55`，loader v14（`fastboot boot`） | `pcie=8 pcie_power=1`，`WIFI_FW=1` | 四项判据都通过，读数见下 |

`wf1` 的读数：

- loader 在 4 GB 以下申请到 `0xc77c0000` 起的 128 MB。
- apps SMMU 有 127 个流匹配项（用了 5 个）、83 个 context bank，最后一个（82）原先没有配置，SCTLR 的 M 位为 0。流 0x1400、0x1401 分到匹配项 5、6，都指向 bank 82，读回一致。
- SoC 版本寄存器 `0x40170200`，主版本 2，固件用 `amss20.bin`（6,426,688 字节，13 段）。
- 网卡全局复位后 MHI 状态 `0xff04`（SYS_ERR），MHI 复位后回到 RESET、PBL。
- BHI 提交后 96 ms 进入 READY，101 ms 执行环境变为 SBL，写入 context 后请求 M0；BHIe 下载完整固件，565 ms 时执行环境 2（AMSS），MHI 状态 M0。
- 第 8 步：通道 20、21 的 START_CHAN 命令都以代码 1 完成，context 状态 2（RUNNING）。网卡是 QRTR 节点 7，发来 HELLO；我们回 HELLO 后，它报出服务 69（WLFW）版本 1、实例 1，在端口 1。
- 桌面照常进到首屏。

## 4. 第 9 步：WLFW 握手

改动：

- QRTR 路由从 `redwood_wifi.c` 拆到 `redwood_qrtr.c`，GLINK 与 MHI 两种链路共用；第 8 步改为把通道 21 收到的包交给路由，后台线程每 5 ms 读一次两个事件环，路由同时作为 QMI 的传输层。
- 第 9 步（`pcie=9`，`mhi_pcie_wlfw.c`）按 ath12k 对 WCN7850 的顺序发消息：PHY 能力、登记要收的通知、主机能力；收到 REQUEST_MEM 后从 4 GB 以下内存分配并回复；收到 FW_MEM_READY 后取目标能力，下发 `regdb.bin`、`bdwlan.eNN`（NN 为板号）与 M3（`phy_ucode20.elf`），再等 FW_READY。`pcie_mission=1` 时继续发日志开关、CE 配置（不含 shadow 寄存器）与 mission 模式。
- 消息描述取自 ath12k（BSD-3-Clause-Clear），由 `hackios-xnu-kernel/tools/mk-wlfw-ath12k.sh` 在构建时按固定标签取文件、核对哈希后生成到构建目录，不进仓库。

判据（读数之前登记）：

| 读数 | 通过 | 不通过时 |
|---|---|---|
| PHY 能力、通知登记、主机能力 | 三条都回 success | 记录 result／error，对照 ath12k 的字段 |
| 内存 | 收到 REQUEST_MEM，回复 success | 记录各段类型与大小 |
| 板级数据 | 目标能力给出板号，regdb、BDF、M3 都被接受 | 记录被拒的文件与分段 |
| FW_READY | 10 秒内收到 | 记录停在哪一步；下一轮试 `pcie_sleep_clock=internal` |

| 轮次目录 | 内核 | 参数 | 结果 |
|---|---|---|---|
| `kernel-12377-cmd56-wf2` | `12377-cmd56` | `pcie=9 pcie_power=1`，`WIFI_FW=1` | 停在板级数据：固件没有给板号（0xff），按板号拼出的 `bdwlan.eff` 不存在 |
| `kernel-12377-cmd57-wf3` | `12377-cmd57` | `pcie=9 pcie_power=1 pcie_mission=1`，`WIFI_FW=1` | 四项判据都通过，mission 模式也被接受 |

`wf2` 的读数：

- 第 7、8 步与 `wf1` 相同：564 ms 进入 mission mode，HELLO 与 WLFW 服务都在。
- PHY 能力、通知登记、主机能力都回 success（各约 6 ms）。PHY 能力报 2 个 radio，没有给板号，不支持单芯片 MLO。
- 主机能力发出后 34 ms 收到 REQUEST_MEM：类型 1（DDR）7,536,640 字节、类型 4（CALDB）8,454,144 字节，都从 4 GB 以下分配并回复成功；11 ms 后收到 FW_MEM_READY。
- 目标能力：chip 0x2、family 0x4、SoC `0x40170200`，固件 `WLAN.HMT.2.0-02977-QCAHMTSWPL_V1.0_V2.0_SILICONZ-1.117143.8`（2025-11-04 构建），没有给板号。
- `regdb.bin`（24,278 字节）分 4 段下发，23 ms 被接受。
- Android 的 cnss2 在板号为 0xff 时用 `bdwlan.elf`，`12377-cmd57` 改成同样的规则，并加 `pcie_bdf=` 手动指定。

`wf3` 的读数：

- 板级数据用 `bdwlan.elf`（88,860 字节，ELF 类型），分 15 段，85 ms 被接受。
- M3 用 `phy_ucode20.elf`（299,660 字节），放在 `0xc9880000`，M3 信息请求成功。
- 发出 M3 信息后收到 FW_READY，距服务出现 175 ms。
- `pcie_mission=1`：日志开关、CE 配置（9 个管道、14 条服务映射，不含 shadow 寄存器）、mission 模式都回 success，模式一条用了 61 ms。从查找服务到这里共 253 ms。
- 之后到轮次结束，事件环上没有错误事件，WLFW 服务没有消失。
- 未确认：三轮的首屏截图都在解锁后 3 秒拍摄，图标还没画完（iconservicesagent 正在建管线）；Wi-Fi 是否影响桌面要在一轮完整的桌面巡检里确认。

## 5. 下一步

固件现在停在 mission 模式，等主机通过 copy engine 建立 HTC 与 WMI。后面的数据面（CE 环、HTC、WMI 初始化、HAL／DP 环、扫描与关联、WPA2）按可行性分析里的 Plan B 走：在现有 `wifi/lx` 兼容层上编译 ath12k（BSD-3-Clause-Clear，构建时取源码），MHI 主机接口用第 7、8 步的代码实现，QMI 用 `redwood_qmi.c`，QRTR 用 `redwood_qrtr.c`。Linux 的 MHI host 与 QMI 库是 GPL-2.0，不用。
