# K90 Wi-Fi：PCIe 根复合体 0 勘察与上电（2026-10-26）

`bsd/dev/mhi_pcie.c` 的分阶段勘察（`pcie=N`）与 `bsd/dev/mhi_pcie_power.c` 的上电（`pcie_power=1`）在 K90 上的结果。下一阶段的固件下载与 WLFW 握手见[固件启动记录](2026-10-31-wifi-firmware-boot.md)，ath12k 驱动接入见[驱动接入记录](2026-11-01-wifi-ath12k-driver.md)。文中的内核短 SHA 早于 10-28 的子模块历史压缩，不在当前分支上，说明见[总账](../plan/2026-10-23-tracking.md)开头。

## 1. 结论

- 内核启动时 PCIe 根复合体 0（RC0）没有上电：两个电源域关闭，6 个时钟都停着；WCN7850 的使能脚 GPIO16 和 PERST（GPIO102）都是未驱动的输入，读数为 0。启动固件不初始化 RC0，内核要从电源、时钟、PHY 到 PERST 完整上电。
- 内核 `0fa0f40` 起，`pcie_power=1` 按主线 Linux 的做法给 RC0 和网卡上电，链路进入 L0（Gen1 x2），配置空间读出 `0x17cb:0x1107`；`fadb3a2` 起分配 BAR0 并读到网卡的 MHI 寄存器，状态为 RESET、执行环境 PBL（第 4、5 节）。

## 2. 读寄存器的约束

- 只在两个电源域都开、cfg_ahb／slv_axi／mstr_axi／aux 四个时钟都在运行时才读 RC0 的 parf、PHY、DBI 寄存器（`474d6e9` 起）。读未上电或未供时钟的模块可能让 SoC 挂死，USB 无法恢复。
- K90 的 TLMM 引脚寄存器在 `0xf100000`（主线 `sm8750.dtsi`，`redwood_goodix.c` 的 `board_setup()` 也用这个地址）。原厂设备树 `tlmm` 节点的 reg 是 `0xf000000`，按它读 `0xf000000 + 16 × 0x1000` 时 SoC 停住、USB 无应答；`82b475c` 改用 `0xf100000` 后勘察正常结束，同一轮桌面正常运行。
- `pcie_pause=N` 在每个读取阶段前先打印下一步，再等待 N 秒；主机每 4～5 s 拉一次日志，用最后一行定位停住的位置。

## 3. 上电前的读数（`kernel-pcie5-s23-auto-pins`）

- 电源域：`gcc_pcie_0_gdsc` 为 `0x0222f801`，`gcc_pcie_0_phy_gdsc` 为 `0x02222801`，bit 31 为 0，均关闭。
- 时钟：cfg_ahb、slv_axi、mstr_axi、aux、slv_q2a_axi、pipe 的 CBCR 均为 `0x88000000`，CLK_OFF 置位。
- 引脚（拉电阻按 `msm_gpio` 编码：1 下拉、2 保持、3 上拉；`e7246d0` 前的日志把 1 显示为上拉，3 显示为保持）：GPIO16、18、19、102 为普通 GPIO、输入、下拉，读数 0；GPIO103（CLKREQ）为普通 GPIO、上拉，读数 1；GPIO104（WAKE）为普通 GPIO、下拉，读数 1。

## 4. 上电与链路（`pcie_power=1`）

原厂内核在 SM8750 上通过 CESTA 和 PCIe 状态机管理 RC0 的时钟和电源，设备树的 RC0 节点没有时钟和电源属性。内核 `0fa0f40` 新增 `bsd/dev/mhi_pcie_power.c`，按主线 Linux 的做法直接上电：`pcie-qcom.c` 的 `cfg_1_9_0`（sm8750 回落到 `qcom,pcie-sm8550`）、`phy-qcom-qmp-pcie.c` 的 sm8750 gen3x2 PHY、`gcc-sm8750.c`、`pwrseq-qcom-wcn.c`；电源和 PHY 取值来自原厂设备树。逐步来源列在本地调试目录的 `wifi-pcie-plan/powerup-steps.txt`。顺序：

1. 读 GPLL0 锁定、RSC 版本，在 cmd-db 中查 11 个 RPMh 资源并确认都标为 VRM。
2. PERST（GPIO102）与网卡使能（GPIO16）先输出低电平。
3. 经 apps DRV2 的第 3 个 active 命令槽（TCS2；TCS0 由触摸驱动使用，TCS1 由 adreno8 使用）投票：PHY 的 L1F 880 mV、L3G 1200 mV；网卡的 L3F 1800、L2F 1200、L6K 1800、S5F 954、S4D 976、S1D 976、S3G 1866、S7I 1316 mV；网卡晶振 `rfclka1`。S5F、S3G 高于设备树的 932、1864，取本机 OL CPR 表的要求，见 [cnss2 对照](../analysis/2026-11-01-android-cnss2-wlan-bringup.md) §2。每个电压先与设备树中调节器范围和网卡范围的交集比对，超出即不发送。
4. 两个电源域、aux 19.2 MHz 与 rchng 100 MHz、参考时钟和各分支时钟；核心与 PHY 复位；PARF；原厂 PHY 序列 126 项、pipe 时钟、PHY 启动。
5. 网卡使能拉高，CLKREQ 与 WAKE 切到对应功能；根端口头部，链路目标速率限为 Gen1；使能后 100 ms 释放 PERST，开始链路训练。

睡眠时钟、AOP 的 WLAN PDC 配置、开关稳压器高功率模式、BT_EN 四个选项是后来按 Android 的做法加的，见[驱动接入记录](2026-11-01-wifi-ath12k-driver.md) §1。

实测：

- `kernel-pciepower-s23-auto-power1`（`0fa0f40`）：11 个资源都找到；电源投票、电源域、时钟、PHY 都成功；网卡使能后 sw-ctrl 两脚读到 1；释放 PERST 后 90 ms 内进入 L0，根端口报告 Gen1 x2。配置空间读出 `0x17cb:0x1107`（类 `0x028000`），BAR0 为 2 MiB 64 位内存。
- BAR0 只保留高于其大小的地址位：写 `0x40300000` 读回 `0x40200000`（`91e559d`）。`fadb3a2` 把 BAR0 放在按 2 MiB 对齐的 `0x40400000`，根端口内存窗口与出站 iATU 区域 1 覆盖它。
- MHI 寄存器（`kernel-pciebar2-s23-auto-bar0`）：MHIREGLEN `0x100`，MHIVER `0xdeadbeef`，MHICFG `0x00800080`，通道门铃偏移 `0x300`，事件门铃偏移 `0x700`，BHI 偏移 `0x100`，BHIe 偏移 `0x224`，MHISTATUS 为 0（RESET）。

## 5. BHI 执行环境与 SID 读取（2026-10-27）

`pcie=5` 在上电之后只读 BHI、BHIe 与 PARF 的 SID 配置，不写 SID、SMMU、固件 DMA 或 MHI 门铃。`pcie_power=1` 会启用端点 bus mastering，普通返回保留 PCIe 上电与 BAR 配置，所以这一轮保存日志后做了软件冷复位。

| 项目 | 读数 |
|---|---|
| 链路与端点 | Gen1 x2，端点 `0x17cb:0x1107`，revision `0x1` |
| BAR0 | `0x40400004`，2 MiB 64 位内存；根端口窗口 `0x40400000..0x405fffff`，command 低 16 位为 `0x0006` |
| MHI | `MHICTRL=0`、`MHISTATUS=0`（RESET），其余同第 4 节 |
| BHI | `EXECENV=0`（PBL），`STATUS=0`，`ERRCODE` 与 `ERRDBG1..3` 全部为 0 |
| BHIe | 提交任何向量之前 `TXVECSTATUS=0x8aa6c915` |
| PARF | `BDF_TO_SID_CFG=0x1`，bypass=1；从 RID `0x100` 的 CRC8 索引 `0x15` 起的冲突链读到 22 项，没有 RID `0x100` |

下载固件之前网卡处于 MHI RESET、执行环境 PBL。端点 DMA 地址转换用到的硬件数据：

- 主线设备树把 RID `0`／`0x100` 映射到 SID `0x1400`／`0x1401`。
- 厂商设备树 `msm-arm-smmu-sun-mi.dtsi`：apps SMMU 在 `0x15000000`，长 `0x100000`；PCIe QTB 在 `0x016cd000`，长 `0x1000`，覆盖 SID `0x1400..0x17ff`，IOVA 宽度 32 位；节点带 `qcom,opt-out-tbu-halting`。
- RID→SID 表按 `qcom_pcie_config_sid_1_9_0()` 与厂商 `msm_pcie_config_sid()` 的格式：关 bypass，清零 256 项，按 CRC8-MSB（多项式 `0x07`）写 `RID[31:16] | relative_SID[15:8] | NEXT[7:0]`。SID base 为 `0x1400` 时，RID `0x100` 写在索引 `0x15`，值 `0x01000100`。
- 旧机型 `redwood_wifi.c` 的 `wifi_smmu=1/2` 用的是 WCN6750 的 SID `0x1c00`，不适用于本机。

本机最后的做法（写 SID 表、两个流在最后一个 context bank 上直通、loader 在 4 GB 以下预留 DMA 内存）见[固件启动记录](2026-10-31-wifi-firmware-boot.md) §1。
