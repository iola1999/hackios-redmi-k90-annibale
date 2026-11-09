# A830 GPU 启动参考

本文记录 SM8750 Adreno 830 在本项目 `adreno8` 驱动中的启动顺序、成功判据、关键修复和仍未确认的条件。源码在 `hackios-xnu-kernel/xnu/files/bsd/dev/adreno8/adreno8*.c`，阶段编号和启动参数以 [`adreno8.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/adreno8/adreno8.c) 文件头为准。2026-10-26 起阶段 1～23 全部通过，桌面由 Mesa freedreno 在 A830 上绘制，见 [GPU 桌面记录](../progress/2026-10-26-gpu-desktop-acceleration.md)。

厂商参考固定为 [OnePlusOSS SM8750 `d50b305`](https://github.com/OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8750/tree/d50b305f7da9e14715a25120a4ac7b1a4b8b97c3/vendor/qcom/opensource/graphics-kernel) 的 graphics-kernel 和 [OnePlus 内核 `6028f47`](https://github.com/OnePlusOSS/android_kernel_oneplus_sm8750/tree/6028f47faddaa27700f8dd3a1d83906ea8f27170)。下文 `文件:L行号` 形式的引用都在 graphics-kernel 目录内。

## 1. 硬件身份与固件

- 运行设备树为 `qcom,adreno-gpu-gen8-0-1`，chip ID `0x44050001`，型号 `Adreno830v2`。厂商 gen8_0_0 与 gen8_0_1 的 catalog 除 revision 和 compatible 外相同。
- GENERAL_10 写入 revision `0x08000100`，必须先于 CM3 解除复位（`d6e7015`）。
- 固件族为 `gen80000`，本机 Android 启动日志和厂商 gen8_0_0 配置一致。按相近 chipid 选出的 gen80200 配置（18 MiB GMEM、revision `0x08020100`）不适用本机。
- 实验固件取自 linux-firmware，见[固件说明](../../hackios-xnu-userland/firmware-gen8/README.md)（[GitHub](https://github.com/iola1999/hackios-xnu-userland/blob/k90-port/firmware-gen8/README.md)）。GMU、SQE、AQE 与本机 Android 文件的 SHA-256 一致；zap 不同，PAS 认证使用本机 Android 里的 `/odm/firmware/gen80000_zap.mbn`（12088 字节，SHA-256 `297318258cb36e5cf6205332a424735c0f9c8f4ba3f9382a6b1d409431b136f7`）。
- 最低工作点为 160 MHz、level `0x32`、DDR 索引 2，是运行设备树六个频率档组共有的最低档（`189ba55`）。更高档位见 [k90auto 说明](../../tools/k90auto/README.md)的 `GPU_SPEED`。

| 文件 | 大小 | 装载方式 |
|---|---|---|
| GMU 固件 | `0x15a50` 字节 | 零长度记录的第四个字段是预分配字节数；检查记录边界和页级重叠，写入后逐段读回 |
| `gen80000_sqe.fw` | 111476 字节 | 跳过前 4 字节 |
| `gen80000_aqe.fw` | 25044 字节 | 跳过前 4 字节 |
| `gen80000_zap.mbn` | 12088 字节 | 提取 metadata，经 PAS 装载可重定位段（第 5 节） |

## 2. 启动顺序

厂商 gen8_0_0（`adreno-gpulist.h:L2932-L2973`）选择 `adreno_gen8_hwsched_gpudev`，驱动按这条 HWSCHED 路径实现，对照 `adreno_gen8_hwsched.c:L824-L867`、`adreno_gen8_hwsched_hfi.c:L2209-L2357` 和 `adreno_gen8_hwsched.c:L570-L634`：

1. 读取 SQE、AQE，分配 powerup list，准备 GMU 内存并启动 GMU。
2. 发送性能表、带宽表和 FEATURE_CTRL，在 `CORE_FW_START` 之前启用 HWSCHED。
3. 启用默认 GPU context（CB0）并设置 SCM aperture，早于 START，与厂商 probe 顺序一致（`45fafb7`）。
4. `CORE_FW_START` 后配置 preemption、LPAC、AQE，发送 `START`；主机处理 `F2H_MSG_MEM_ALLOC` 和 `F2H_MSG_GMU_CNTR_REGISTER`，直到本次 START 的最终 ACK（`adreno_gen8_hwsched_hfi.c:L1449-L1735`）。
5. 申请 `oob_gpu`，按 `gen8_start()` 配置寄存器，清除旧故障，写入 SQE/AQE 基址。
6. 经 `ISSUE_CMD_RAW` 提交 CP_INIT 并等待空闲，认证 zap，再提交 `CP_SET_SECURE_MODE(0)`。

厂商的传统 ring 路径（`adreno_gen8_gmu.c:L2556-L2625`）不被 gen8_0_0 选择。驱动的 `adreno8_direct_ring=1` 只作诊断，超时路径采样 CP、RBBM 和全局故障状态（`aef3da7`、`2d75c8f`）。

## 3. 阶段与成功判据

`adreno8=N` 执行阶段 1～N，任一阶段失败即停止。阶段 15 起要求 `adreno8_keep=1`，资源保留到冷复位。

| 阶段 | 内容 | 成功判据 |
|---|---|---|
| 1 | QFPROM、CMD DB、BCM | speed_bin=232；BCM 按 `unit:u32,width:u16,vcd:u8,reserved:u8` 解析 |
| 2～4 | GPUCC、CX 上电、CX／RSCC／GBIF | GDSCR 从 `0x0222f801` 变为 `0xfa22f800`；退出时恢复原配置 |
| 5 | 时钟 | RCG UPDATE 与分支启用完成，GMU BCR 保持 0；默认 GMU 时钟源为 19.2 MHz 晶振 |
| 6～7 | GMU 寄存器、DTCM | CM3 处于复位，两个字写入、读回并恢复原值 |
| 8 | SMMU 识别 | 24 个 stream match、21 个 context，ATOSNS=1（无硬件 ATOS） |
| 9～11 | GMU 映射、固件、启动 | S2CR 读回 `0x302`；固件逐段读回一致；`INIT_RESULT=0x100` |
| 12～13 | HFI、性能表与带宽表 | `HFI_CTRL_STATUS=1`，版本 `0x20070001`；消息 15、3 获 ACK |
| 14 | HWSCHED START | 每条 MEM_ALLOC 的大小、对齐、flags 与回复都检查；最终 ACK 匹配本次请求 |
| 15 | 最低档 DCVS | 160 MHz／BW2（消息 30）获 ACK |
| 16 | GPU context 0 只读校验 | 寄存器、stream 0 路由（`0x300`）、完整页表和 FSR 通过 |
| 17 | OOB、GPU 寄存器、CP_INIT | powerup 表与 SQE/AQE 基址读回正确；CP_INIT 获 ACK 且空闲；GPU SMMU 无新增故障 |
| 18～20 | zap、退出 secure、scratch | PAS 13 认证成功；`CP_MEM_WRITE` 写入 scratch，CPU 读回预期值 |
| 21 | 诊断 | 故障、队列、电源和计数器状态可读 |
| 22 | 标准 HWSCHED context | 两条非特权 IB 的 SOP／EOP 写回，timestamp 正确，注销成功 |
| 23 | 服务发布 | 标准 context 自测成功后启用外部 BO 映射，`AnnibaleGPU` 注册成功 |

## 4. 地址空间与页权限

| context | stream | 用途 |
|---|---|---|
| CB0 | SID 0（`gfx3d_user`）、SID 1（`gfx3d_lpac`） | GPU 默认地址空间，TTBR0 |
| CB2 | SID 5，精确匹配 | GMU；厂商为 GPU 保留 context 0／1，其他客户端从 2 起分配 |
| CB3 | SID 2（`gfx3d_secure`） | 安全资源 |

SMMU 使用 4 KiB granule，XNU 分配页为 16 KiB，页表逐个 4 KiB 地址调用 `kvtophys`，允许物理不连续。GMU 的 S2CR 为 SHCFG=NSH、PRIVCFG=DEFAULT，TRANS=`0x302`、FAULT=`0x20300`。叶子页采用 NC、outer-shareable、AF、nG，MAIR index 0 为 Normal Non-cacheable：

| 用途 | 权限 | PTE 属性 |
|---|---|---|
| SQE/AQE | 只读、可执行 | `0xec3` |
| privileged ring | privileged 只读、不可执行 | `0xe83 \| (3ULL << 53)` |
| powerup list、scratch | privileged 读写、不可执行 | `0xe03 \| (3ULL << 53)` |
| GMU 映射 | privileged，bit 6 必须为 0 | `0xf03` |

GMU 叶子的 bit 6 置位时页面允许 EL0 写入，AArch64 禁止 privileged 指令从这类页执行，表现为 CB2 FSR=`0x8`、FSYNR0=`0xd0063`，`INIT_RESULT` 停在 0。SQE 基址寄存器为 `0x816/0x817`，AQE0 为 `0x818/0x819`，AQE1 为 `0x81a/0x81b`（dword offset）。

START 期间固件请求 kind 5 安全缓冲（`CSW_PRIV_SECURE`，flags `0x1007`），显式关闭 preemption 后仍会请求：

- MP_ASSIGN（`0x42000c16`，arginfo `0x1117`）把数据页从 HLOS（VMID 3）移交 CP_PIXEL（VMID 10）读写；页表保留 HLOS 读写并给 CP_PIXEL 只读。移交前从 TTBR 根遍历全部缓冲（`537f970`），移交后 CPU 不再访问这些页。
- 安全 IOVA 从 trusted base `0xf0000000` 起分配，普通缓冲从 `0x10000000` 起（`9134960`）。
- 同次启动完成移交、CB3 配置和路由读回（`0x303`）后才回复 MEM_ALLOC。之后允许普通分配和原请求的精确重放，新的安全 handle 被拒绝；START 失败则停止服务，资源保留到冷复位（`744092c`，见 [`adreno8_memory.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/adreno8/adreno8_memory.c)）。

## 5. CP 初始化与 zap

`gen8_cp_init_cmds()`（`adreno_gen8.c:L607-L650`）生成 10 dword：

```text
TYPE7(CP_THREAD_CONTROL, 1), BIT(27)
TYPE7(CP_ME_INIT, 7), 0x14b, 3, 0x20000000, 2,
pwrup_iova_lo, pwrup_iova_hi, BIT(31)
```

powerup list 由 `gen8_start()` 配置完寄存器后读取生成，本机 1560 字节。RAW 提交先检查 ACK，再等待 `GPU_CX_BUSY_STATUS.bit23=0`，超时 200 ms。CP_INIT 成功并空闲后才加载 zap。

zap 预留区为 `0x9b09a000`、大小 `0x2000`，本机设备树与厂商一致。认证顺序：

1. metadata 由文件开头 `0x94` 字节和文件 `0x2000` 处的 hash 段 `0xf38` 字节拼接，总长 `0xfcc`。
2. 唯一 `PT_LOAD` 位于文件 `0x1000`，`p_filesz=p_memsz=0x3b4`，带 relocatable 标志，重定位到预留区起点，装载 `0x1000` 字节。
3. PAS ID 13：`INIT_IMAGE(metadata_pa)` → `MEM_SETUP(0x9b09a000, 0x1000)` → 复制加载段 → `AUTH_AND_RESET(13)`。
4. metadata 必须物理连续、4 KiB 对齐、非缓存访问；每次调用同时检查 SMC transport 返回和服务返回值。认证失败后不再发送 secure-mode 命令。

## 6. LPAC 路由：CP_INIT 停滞的根因

HWSCHED 的 RAW131（H2F CP_INIT）发布后整机复位，普通 HFI 直接 ring 的 CP_INIT 超时，原因相同：LPAC 微引擎使用的 SMMU stream 没有路由。

- 直接 ring 超时时 GFSR 为零，WPTR 已发布，RPTR 不动。`CP_SQE_STAT` 索引 0 读出 BR 的 PC 停在 `0xe3`、BV 停在 `0x4a`，对照 `gen80000_sqe.fw`（版本 `01500077`）反汇编，两处都在启动屏障里循环读 `THREAD_SYNC`。
- `THREAD_SYNC` 初值 `0x7`，BR、BV、LPAC 分别清除 bit 0、1、2；LPAC 的 bit 2 始终未清。
- 驱动按厂商值写 `CP_SMMU_STREAM_ID_LPAC = 0x101`，LPAC 取微码使用 SID 1，SMMU 当时只为 SID 0 和 SID 5 建了 SMR／S2CR。
- `adreno8_space_route()` 在 match 3 写入 SID 1，S2CR 指向 context 0（Linux msm 也把 SID 0、1 放在同一个 domain）。顺序为先置 fault、写 SMR 并读回，再切到 translate 并检查无故障；失败时恢复 fault（`a10067e`，主机测试 `b7d3b95`）。

修复后直接 ring 的 CP_INIT 被消费且空闲，HWSCHED 的 CP_INIT 获 ACK，随后 zap、退出 secure、scratch 写回和标准 context 的 SOP／EOP 通过。直接 ring 诊断取得结果后主动停止，仍会打印阶段 17 `FAILED`，判断要读具体完成条件。

## 7. 其他关键修复

- GPU 寄存器的 CPU 映射为 `0x03d00000 + 0x40000`，索引乘 4 前检查边界（`7faa7c1`）；MMIO 写前、读后的屏障按厂商顺序（`a473130`）。
- CB0 启用后调用 SMC `0x42000c1b`（`qcom_scm_kgsl_set_smmu_aperture`），参数 `0xffff0000` 和三个 `0xffffffff`（`ae92c8a`）。
- 回读检查忽略不保留的位：SCTLR 的 ASIDPNE（bit 12），TCR2 只读为 1 的 TBI0／TBI1（bits 6:5）。FSR 的 `[10:9]` 是翻译格式字段，有效故障掩码为 `FSR_ALL=0xc00001fe`（`3a4d388`）。
- GPU 运行后 CB0 TCR 的 EPD1（bit 23）读回为 0；TTBR1 为 0 且 IOVA 都在 TTBR0 范围内时容忍该值（`4d93f52`）。
- HFI 表 840 字节，对齐 16 字节后接三个 4096 字节队列（`0x350`、`0x1350`、`0x2350`），缓冲物理连续、单一 uncached view（`4361a43`）。
- CM3 启动前分配 4096 字节 VRB 和 16384 字节 trace，VRB 地址写入 GENERAL11（`3eb09e0`）。
- FEATURE_CTRL 的 ACK 要求 data 与第四字 error 都为 0（`b81835d`）；依赖票置 bits 31:14，160 MHz 为 `0xffffc2ff`（`bc3a141`）。
- producer 索引写入后立即写 doorbell（`d9c871c`）。退出路径直接复位 CM3、关闭 SMMU；空的 HFI33 slumber 消息得不到 ACK。
- `GEN8_TPL1_DBG_ECO_CNTL` 按本机 KGSL 取 `0x10000000`（`bf5e18a`）。
- 阶段 22 的 EOP 写回后 GMU 队列读指针可能稍晚追上，最多等待 20 ms（`3d9c53f`）。平台识别按 GIC 重分发器基址 `0x16080000`（`33808b4`）。
- 映射提交、TLB 同步或解除映射失败后保留 IOVA 和 descriptor，停止后续提交（`9771edf`）。
- Mesa 在 a8xx 首个读帧缓冲的 draw 前追加 CCHE 失效（userland `94e4c97`），分析见 GPU 桌面记录第 3 节。
- `adreno8_gmuclk=1／2` 的时钟路径配出 GMU 650／HUB 200 MHz，START 后 GMU 降为 500 MHz（`0813b2f`、`98b40e3`），并把 AHB 超时写为 `0x1b12`（`5c99f63`）。该路径要求 `touchscreen=0`，带触摸的运行使用默认晶振。

## 8. 排查约束

- 阶段 15 起资源保留到冷复位。CP 停止、GPU／GMU 无剩余访问、SMMU 关闭且 TLB 同步完成后才能释放映射内存，完整关闭流程尚未实现。
- 队列索引发布后 GMU 可能已读取命令。`adreno8_fine=1` 的暂停位于访问打印与实际写入之间，最后一行打印不能证明写入已执行。
- 厂商冷启动的首条 RAW 是 CP_INIT。CP_INIT 之前发送 NOP 是否有效未确认，不能用它代替 CP_INIT 的检查。
- 命令停滞且故障寄存器为零时，读各单元的 SQE PC，对照实际固件找出等待条件（第 6 节）。
- 主机测试要读取生产配置：`7faa7c1` 之前的测试自带 `0x40000` 窗口，漏掉了生产声明只映射 `0x10000` 的错误。
- XNU 复位后，Android 侧只读到 PMIC 缓存的 PS_HOLD、WARM_RESET、HARD_RESET，pstore 为空，TZ 日志加密，无法定位原因。
- Apps DRV2 的 ARC 读写与触摸初始化共用 TCS 和 IRQ 寄存器。ACTIVE 写入 CX 请求值 3 完成后读回仍为 0，读回值的含义未确认。

## 9. 仍未确认的条件

- CB0 TCR EPD1 的写入方；扩大地址范围或复用到其他 context 前要重新核对。
- GFSR 为零时为何没有报告 LPAC 的取指故障。
- LPAC 参与当前固件的启动同步，裁减 LPAC、preemption 或 warmboot 前要核对固件和厂商配置。
- 厂商首次启动投票最低 DDR 带宽 2,136,718 KB/s，驱动沿用继承的 host DDR 投票，去掉继承状态后能否启动未验证。
- RSC sleep 要求 `FIRST_BOOT_DONE`（`adreno_gen8_gmu.c:L355-L389`），已检查的 gen8 驱动没有 RSC／PDC sequence RAM 初始化代码，`CORE_FW_START` 后直接请求 sleep 的条件未确认。
- 失败注入的设备行为只有主机模型覆盖；物理电压和长时功耗未测量。
