# K90 Wi-Fi：WCN7850 固件启动（2026-10-31）

[PCIe 勘察与上电](2026-10-26-wifi-pcie-survey.md)之后，网卡停在 MHI RESET、执行环境 PBL，剩下的问题是 apps SMMU 怎么处理端点 DMA。小米 15 参考仓库（同为 SM8750）的做法是让外设的流直通、在 4 GB 以下预留 DMA 内存（[参考仓库对照](../analysis/2026-10-31-dada-reference-comparison.md) §6.3）。本文记录按这套做法把 WCN7850 固件启动到 mission 模式的 PCIe 第 7～9 步。之后由 ath12k 接管 QMI 与数据通路，见[驱动接入记录](2026-11-01-wifi-ath12k-driver.md)。

## 1. 改动

- loader v14（`xnuloader/loader_05_layout_run_kernel.inc`）：载荷参数里有 `pcie=7`～`pcie=9` 时，用 AllocateMaxAddress 在 4 GB 以下申请 128 MB，经 `lowdma=`、`lowdma_mb=` 交给内核；网卡只能访问 32 位地址，内核内存都在 4 GB 以上。只在第一次请求时申请，之后各轮沿用。v15、v16 的变化见驱动接入记录 §1。
- 第 7 步（`pcie=7`，要求 `pcie_power=1`，`xnu/files/bsd/dev/mhi_pcie_fw.c`，内核 `f72115c`）：
  - PCIe 控制器打开 BDF→SID 表，RID 0x100 写在槽位 0x15，对应流 0x1401；
  - apps SMMU 给流 0x1400、0x1401 各分一个空闲匹配项，指向最后一个 context bank，该 bank 设为不做地址转换；流已有匹配或最后一个 bank 正在转换时停止，不给网卡上电；
  - 按 ath12k 的 WCN7850 流程给网卡上电（LTSSM、热复位、清中断与 BHIe 门铃、全局复位、MHI 复位），MSI 指向一页没人读的内存，关 ASPM；
  - 用 UniXNU 的 MhiBoot（`mhi_boot.c`，BSD-2-Clause-Patent）经 BHI 下载引导程序，READY 后写 MHI context，请求 M0，再经 BHIe 下载完整固件，等 mission mode；
  - 固件取 RAM 盘 `fw/` 下的 `amss20.bin`（SoC 版本寄存器的主版本为 2 时）或 `amss.bin`，`pcie_fw=1`／`2` 可指定。
- 第 8 步（`pcie=8`，`f72115c`）：填写通道 20、21（IPCR）的 context，各发一条 START_CHAN，在通道 21 上放接收缓冲，按 QRTR v1 读包，回应网卡的 HELLO，打印它报出的服务。
- QRTR 路由从 `annibale_wifi.c` 拆到 `annibale_qrtr.c`，GLINK 与 MHI 两种链路共用；第 8 步改为把通道 21 收到的包交给路由，后台线程每 5 ms 读一次两个事件环，路由同时作为 QMI 的传输层（`15aed86`）。
- 第 9 步（`pcie=9`，`mhi_pcie_wlfw.c`，`15aed86`）按 ath12k 对 WCN7850 的顺序发消息：PHY 能力、登记要收的通知、主机能力；收到 REQUEST_MEM 后从 4 GB 以下内存分配并回复；收到 FW_MEM_READY 后取目标能力，下发 `regdb.bin`、板级数据与 M3（`phy_ucode20.elf`），再等 FW_READY。`pcie_mission=1` 时继续发日志开关、CE 配置（不含 shadow 寄存器）与 mission 模式。
- 板级数据：固件不给板号（0xff）时按 Android cnss2 的规则用 `bdwlan.elf`，`pcie_bdf=` 可手动指定（`551b569`）；有板号时用 `bdwlan.eNN`。
- 消息描述取自 ath12k（BSD-3-Clause-Clear），由 `hackios-xnu-kernel/tools/mk-wlfw-ath12k.sh` 在构建时按固定标签取文件、核对哈希后生成到构建目录，不进仓库。Linux 的 MHI host 与 QMI 库是 GPL-2.0，不用。

第 9 步在 ath12k 接管后只用作对照（驱动接入记录 §3.2 的冷启动校准）。

## 2. 固件文件

- 提取：`python3 hackios-xnu-kernel/tools/mk-fw-wifi.py extract <modem 分区镜像> hackios-xnu-kernel/out/fw-wifi`。脚本读 modem 分区镜像（`.img` 或 `.img.gz`）里的 `image/kiwi/`，不解包，同时写 `manifest.json`（名字、大小、SHA-256、来源镜像）。用本机分区里的固件，不用网上下载的版本：要启动的是手机校准时用的那份 amss。
- `cycle.py` 的默认配置用到四个文件：`amss20.bin`、`regdb.bin`、`bd_p11.elf`、`phy_ucode20.elf`。`tools/k90auto/package.py` 在本地固件目录里有这四个文件时默认只放它们（约 6.9 MB），`WIFI_FW=1` 放入全部文件，`WIFI_FW=0` 不放；文件进 RAM 盘的 `fw/`，清单记录各自的 SHA-256。全部放入约 27 MB，和开机种子一起超过内核与常驻系统盘之间的 40.9 MB（[11-05 记录](2026-11-05-defaults-and-charging.md)）。

## 3. 结果

`kernel-12377-cmd55-wf1`（`pcie=8 pcie_power=1`，loader v14 经 `fastboot boot` 启动）：

- loader 在 4 GB 以下申请到 `0xc77c0000` 起的 128 MB。
- apps SMMU 有 127 个流匹配项（用了 5 个）、83 个 context bank，最后一个（82）原先没有配置，SCTLR 的 M 位为 0。流 0x1400、0x1401 分到匹配项 5、6，都指向 bank 82，读回一致。
- SoC 版本寄存器 `0x40170200`，主版本 2，固件用 `amss20.bin`（6,426,688 字节，13 段）。
- 网卡全局复位后 MHI 状态 `0xff04`（SYS_ERR），MHI 复位后回到 RESET、PBL。
- BHI 提交后 96 ms 进入 READY，101 ms 执行环境变为 SBL；BHIe 下载完整固件，565 ms 时执行环境 2（AMSS），MHI 状态 M0。
- 第 8 步：通道 20、21 的 START_CHAN 都以代码 1 完成，context 状态 2（RUNNING）。网卡是 QRTR 节点 7，发来 HELLO；回 HELLO 后它报出服务 69（WLFW）版本 1、实例 1，在端口 1。桌面照常进到首屏。

`kernel-12377-cmd56-wf2`（`pcie=9`）：

- PHY 能力、通知登记、主机能力都回 success（各约 6 ms）。PHY 能力报 2 个 radio，没有给板号，不支持单芯片 MLO。
- 主机能力发出后 34 ms 收到 REQUEST_MEM：类型 1（DDR）7,536,640 字节、类型 4（CALDB）8,454,144 字节，都从 4 GB 以下分配并回复成功；11 ms 后收到 FW_MEM_READY。
- 目标能力：chip 0x2、family 0x4、SoC `0x40170200`，固件 `WLAN.HMT.2.0-02977-QCAHMTSWPL_V1.0_V2.0_SILICONZ-1.117143.8`（2025-11-04 构建），板号 0xff。
- `regdb.bin`（24,278 字节）分 4 段下发，23 ms 被接受；之后按板号拼出的 `bdwlan.eff` 不存在，停在板级数据。

`kernel-12377-cmd57-wf3`（`pcie=9 pcie_mission=1`）：

- 板级数据用 `bdwlan.elf`（88,860 字节，ELF 类型），分 15 段，85 ms 被接受。
- M3 用 `phy_ucode20.elf`（299,660 字节），放在 `0xc9880000`，M3 信息请求成功；之后收到 FW_READY，距服务出现 175 ms。
- 日志开关、CE 配置（9 个管道、14 条服务映射，不含 shadow 寄存器）、mission 模式都回 success，模式一条用了 61 ms。从查找服务到这里共 253 ms。之后到轮次结束，事件环上没有错误事件，WLFW 服务没有消失。
