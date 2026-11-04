# 默认开机参数与充电状态（2026-11-05）

用户要求 Wi-Fi 等已验证的功能默认打开，不再依赖环境变量，并反馈插着充电器、电量较高时状态栏不显示充电。本文记录这一天的改动、轮次与读数。120 Hz 的 dc2 轮记在 [11-02 轮次记录](2026-11-02-120hz-gpu-clock-rounds.md)。

## 1. 改动

- `tools/k90auto/cycle.py`：
  - 固定参数整理为 `FIXED_ARGS`，加上 `touch_poll_us=4000` 与 `kernel-12377-cmd83-wd32` 的 Wi-Fi 一组（`pcie=10` 起到 `wifi_station=1`，不含诊断用的 `net_trace=80`）。
  - 默认内核 `12377-rate7`；`--seed` 缺省时用本地的 `kernel-12377-cmd30-seed3/seed-icons.bin`。
  - 驻留的 loader 不是 v16（build-id 不含 `a48c7fb`）时，先经 LK 用 `fastboot boot` 启动 `out/handoff-loader-v16.img`，不需要再给 `LOADER_IMAGE`。
  - 巡检里设置图标的点按位置由 0.616 改为 0.385。
- `tools/k90auto/package.py`：本地固件目录有 `amss20.bin`、`regdb.bin`、`bd_p11.elf`、`phy_ucode20.elf` 时默认只放这四个文件，约 6.9 MB；`WIFI_FW=1` 仍放入全部文件，`WIFI_FW=0` 不放。
- 内核 `12377-rate8`（rate7 加 `RedwoodBattery.cpp`）：插着电且 DSP 不报放电（status 2）就向 iOS 报充电；充电器在线或充电状态每次变化打印一行 `RedwoodBattery: N%, ...`。

## 2. 轮次

| 轮次目录 | 内核 | 本轮内容 | 结果 |
|---|---|---|---|
| `kernel-12377-rate7-def1`（第一次） | rate7 | 新默认参数，加 `torch=3 hv_haptic=4` | 没有启动：根盘 56.1 MB，内核与常驻系统盘之间只放得下 40.9 MB |
| `kernel-12377-rate7-def1` | rate7 | 同上，Wi-Fi 固件只放四个文件 | 桌面、设置、控制中心正常；Wi-Fi 驱动报 `no thread, or no memory the radio can be given`；手电与振动初始化失败 |
| `kernel-12377-rate7-use1` | rate7 | 默认参数，loader v16，保持 900 秒给用户试用 | Wi-Fi 驱动注册射频（ath12k，固件 `amss20.bin`） |

## 3. 读数

- 根盘大小：基础根盘约 6 MB，开机种子约 23 MB，Wi-Fi 固件目录全部约 27 MB。`wd` 系列轮次不带种子，所以没有遇到上限。
- Wi-Fi 的低端 DMA 内存：`wd` 系列轮次用 `LOADER_IMAGE` 启动 loader v16，命令行带 `lowdma=`；手机 A 槽里刷的 loader 较旧，不给这段内存。use1 经 LK 启动 v16 后命令行有 `lowdma=0x00000000c77c0000`，驱动正常起来。
- def1 的手电：`reading 0x0018 gave: the transfer was dropped`，随后 `the light for iOS stops after 0 times lit: the module said something surprising`；振动：故障寄存器 0x10 清不掉。原因未查，两项不进默认参数。
- def1 的设置里 Wi-Fi 开关显示关闭，那一轮驱动没有起来。use1 中开关状态由用户确认。
- 充电：use1 连着 Mac 的 USB，DSP 报 USB 不在线、状态放电，电流 −106～−1302 mA，电量 99% → 98%；开机后第一次上报是「99%，charging」，之后变为不在线。dc2、def1 的读数相同。

## 4. 待办

- `12377-rate8` 上机：对照充电状态变化行，分清「充电器在线但停充」与「USB 不在线」。前者状态栏应显示闪电。
- 连着 Mac 时 USB 不在线的原因：Android 侧的充电器驱动可能会向 DSP 请求输入电流，iOS 侧没有，需对照 Android 的 battmgr 交互。
