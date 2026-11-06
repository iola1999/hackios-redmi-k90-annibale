# annibale 真机调试手册

本手册收集驻留 loader 的安装、手工运行内核、读日志、故障恢复和启动参数。日常启动 iOS 26 用 `tools/k90auto/cycle.py`，见 [README §5](../../README.md#5-启动并使用-ios-26) 与 [k90auto 说明](../../tools/k90auto/README.md)；Android／LK／loader 之间的切换见[引导目标切换 SOP](device-boot-target-sop.md)；USB 命令超时与无应答见 [USB 恢复经验](../analysis/2026-10-25-usb-recovery-lessons.md)。当前进度见[总账](2026-10-23-tracking.md)，操作前仍需确认设备与产物现状。

## 1. 槽位假设与当前启动方式

本项目的脚本按「Android 在 B 槽、loader 写在 A 槽的 boot 分区」编写。`tools/k90auto/cycle.py`、`tools/k90auto/reboot-lk.py`、`tools/k90auto/recover-loader.py` 固定执行 `set_active a`，`recover-loader.py` 还断言 Android 的 `ro.boot.slot_suffix` 为 `_b`。下文命令按这个布局写；Android 在 A 槽的设备需要对调命令里的 a／b，并修改这些脚本。

当前各部分（以 `tools/k90auto/cycle.py` 的默认值为准）：

- loader：`hackios-xnu-kernel/out/handoff-loader-v17.img`（`LOADER`），2026-11-05 起刷在 `boot_a`。Wi-Fi 需要 v16 起的 loader，它在 4 GB 以下给 Wi-Fi 卡留 128 MB 内存；v17 沿用 v16 的 loader，换了 UEFI。`cycle.py` 按 `getvar build-id` 是否含 `a48c7fb`（`LOADER_BUILD`）判断驻留的 loader；不含时经 LK 用 `fastboot boot` 起 v17，不刷写分区。
- 内核：`12377-rate10`（`KERNEL`），由 `make-payload.py` 和根盘打包成载荷，构建方法见 k90auto 说明。
- 系统盘：`hackios-xnu-kernel/userland/system26.apfs`，超过 `0xffffffff` 字节，由双系统 `darwin` 分区或 Android DSU 读入（见 [README §4](../../README.md#4-划分磁盘分区并安装引导) 与[双系统分区与持久化部署手册](dual-boot-setup.md)），或按第 9 节的分块协议经 USB 上传。
- 启动参数：`make-payload.py` 的固定一组加 `cycle.py` 的 `FIXED_ARGS`，见第 8 节与 [k90auto 说明 §8](../../tools/k90auto/README.md#8-渲染问题的无人值守检查)。

每轮收尾的 PSCI 复位会重新启动 `boot_a` 里刷着的 loader。`boot_a` 里 loader 的 build-id 不含 `a48c7fb` 时，每一轮都要多走一次 LK 检查点，所以建议按第 3 节把 v17 刷进 `boot_a`。

## 2. 操作前检查

1. 确认本轮内核、loader、载荷和系统盘的文件大小与 SHA-256；修改源码后重新构建对应产物。`cycle.py`／`run-auto.py` 按 `manifest.json` 自动核对，手工运行时自己核对。
2. 先看 `adb devices -l` 和 `fastboot devices`，把目标 Android／LK 序列号设为环境变量 `ANDROID_SERIAL`；驻留 loader 使用 `xnuloader`。每次切换后重新确认身份，判别方法见 [SOP §1](device-boot-target-sop.md#1-先判当前身份)。
3. 确认当前槽位和 A 槽重试次数。写启动镜像只用 `boot_a`。连续实验会耗尽 A 槽重试次数，LK 随后回退到 B 槽 Android；这时经 ADB 回到 LK 执行 `set_active a` 即可恢复已有 loader，无需重写镜像，见 [SOP §4](device-boot-target-sop.md#4-陷阱均为实测) 第 4 条。
4. 无人值守跑轮遵守 [AGENTS.md](../../AGENTS.md) 第 5 节。

## 3. 安装驻留 loader

loader 镜像 `hackios-xnu-kernel/out/handoff-loader-v17.img` 是 Git 忽略的本地构建产物，构建步骤见 [annibale UEFI 与 loader 镜像构建](../analysis/annibale-uefi-build.md#3-装配-loader-镜像)。其中的 UEFI 源码在 [iola1999/hackios-mu-silicium](https://github.com/iola1999/hackios-mu-silicium) 的 `k90-port` 分支，标签 `loader-v17` 对应 v17 里的 FD。

镜像可以先不刷写：在 LK 执行 `fastboot -s "${ANDROID_SERIAL}" boot <loader 镜像>`，loader 约 18 秒后枚举，不改 `boot_a`，也不扣 A 槽重试次数（[SOP §4](device-boot-target-sop.md#4-陷阱均为实测) 第 1 条）。`cycle.py` 用环境变量 `LOADER_IMAGE=FILE` 指定检查点要起的镜像。

刷写前先进入 LK：Android 可连接时用 `adb -s "${ANDROID_SERIAL}" reboot bootloader`；loader 驻留时用 `reboot-lk.py`（[SOP §2](device-boot-target-sop.md#2-五条切换路径)）；软件入口都不可用时请用户长按电源键和音量下进入 FASTBOOT（[USB 恢复经验 §4](../analysis/2026-10-25-usb-recovery-lessons.md#4-按当前环境选择恢复方式)）。

```sh
fastboot -s "${ANDROID_SERIAL}" getvar product
fastboot -s "${ANDROID_SERIAL}" getvar current-slot
fastboot -s "${ANDROID_SERIAL}" flash boot_a hackios-xnu-kernel/out/handoff-loader-v17.img
fastboot -s "${ANDROID_SERIAL}" set_active a
fastboot -s "${ANDROID_SERIAL}" reboot
fastboot -s xnuloader getvar product
fastboot -s xnuloader getvar build-id
fastboot -s xnuloader getvar screen
```

成功条件为 `product: xnuloader`，`build-id` 与构建时的 `BUILD_ID` 一致（v16 与 v17 都是 `a48c7fbac8fb64e1e8cafe2cf4efc4c79dbae767`）。屏幕几何应为 `1156 2510 4624`，该值来自固件配置，物理面板的显示仍要目视验证。`reboot` 的主机返回结果只能确认命令已发送，后续状态需要另行读取。

## 4. 手工运行内核

`cycle.py` 会完成打包、上传和运行；下面是手工调试时的等价步骤，在 `hackios-xnu-kernel/` 目录下执行。载荷由 `tools/k90auto/make-payload.py` 生成，路径为 `out/handoff-<内核名>-<标签>.bin`。

```sh
STAGE_SYSTEM_IMAGE=userland/system26.apfs STAGE_SYSTEM_WINDOW=0x300000000 bash tools/stage-system.sh
fastboot -s xnuloader stage out/handoff-<内核名>-<标签>.bin
fastboot -s xnuloader oem run
fastboot -s xnuloader getvar result
```

- `stage-system.sh` 会切到 `hackios-xnu-kernel/`，`STAGE_SYSTEM_IMAGE` 按这个目录写相对路径或用绝对路径。系统盘只需在本次 loader 生命周期首次运行或更换镜像时上传；loader 复位后要重新上传。
- `bootcpu=7` 让内核从 MPIDR `0x10100` 的核启动，loader 留在当前 CPU 上处理 USB。
- 结束运行用 `fastboot -s xnuloader oem stop`，再查询 `result`。带 GPU 的载荷（`make-payload.py` 默认 `adreno8=23 adreno8_keep=1 adreno8_return=0`）停止后不返回 loader，约 50 秒后 loader 报 `hung-held`，按第 5、6 节保存日志后复位，过程见[无人值守收尾](../analysis/2026-10-28-unattended-teardown.md)。`GPU_STAGE=0` 打包的载荷不起 GPU，内核可以返回 loader。
- `loader_return_after=N` 让内核限时返回，取消不了 GPU 资源保留；`make-payload.py` 生成的载荷禁止带这个参数。
- 屏幕停在最后一帧时先查询 `result`，避免重复调查已经退出的系统。

## 5. 读取日志和截图

内核运行期间按下面的顺序准备并读取数据，每组串行执行：

```sh
fastboot -s xnuloader oem log
fastboot -s xnuloader get_staged /tmp/hackios-kernel.log
fastboot -s xnuloader getvar screen
fastboot -s xnuloader oem screenshot
fastboot -s xnuloader get_staged /tmp/hackios-screen.raw
```

`oem log` 和 `oem screenshot` 只准备数据，`get_staged` 才把数据传回主机；没有暂存数据时 `get_staged` 得到 `FAIL no staged data`。截图为原始帧缓冲，按 `getvar screen` 的宽、高和每行字节数解码。主机 fastboot CLI 使用 `get_staged`，线上的 USB 协议命令名为 `upload`。

内核返回或 loader 判定 `hung`／`hung-held` 后，loader 已把那一刻的内核日志快照组装进暂存区。顺序是先 `get_staged <名字>.log` 取快照，再 `oem log`、`get_staged <名字>-serial.log` 取 loader 串行日志，最后才 `reboot`。先执行 `oem log` 会走 `compose_logs(NULL, 0)`，清空暂存、只复制 loader 自己的日志（最多 32,767 字节），快照被覆盖。`oem screenshot` 同样会替换暂存内容。

`oem stop` 后 `result` 迟迟不离开 `running` 时，`oem log` 读的是内核实时环形缓冲。先 `oem log` 加 `get_staged /tmp/hackios-stop1.log`，约 2～3 秒后再取一次存为 `stop2.log`，到此为止，不做循环轮询；按取回内容区分内核主动 park 与驱动卡住的三档判据见[无人值守收尾 §4](../analysis/2026-10-28-unattended-teardown.md#4-怎样区分内核主动-park与驱动卡住)。

## 6. 故障定位与恢复

- `result: running`：内核仍在运行，读取 USB 日志判断进度。
- `result: returned ...` 或 `checkpoint ...`：确认没有 held／fault 状态，再取日志、上传下一份内核载荷；同一 loader 生命周期中的 RAM 系统盘可以继续使用。
- `result: hung ...`：先保存可读日志，核对资源保留状态，再复位。
- `result: hung-held ...`、`returned-held ...` 或带 fault：设备可能仍在访问原内核的内存和映射。loader 拒绝 `oem ramdisk`、`download:`、`oem run` 等会改写资源的命令（完整列表见 `xnuloader/loader_01_base_log_dt.inc` 的 `lc_blocked_cmd`），查询、日志、截图和 `reboot` 保留；没有运行中的内核可通知时，`oem stop` 返回 `FAIL`。先按第 5 节保存日志，再 `reboot`，确认 USB 断开、重新枚举和 `result: idle`，随后重新上传系统盘。
- 带 GPU 的内核在普通退出与 panic 返回时都检查 `adreno8_reset_required` 和 `adreno8_memory_retained()`，ACK 成功、失败或分配中途失败都可能要求保留资源；需要保留时内核停在 `adreno8_quiesce()` 不返回，只能复位后再上传下一份内核，源码链见[无人值守收尾 §2](../analysis/2026-10-28-unattended-teardown.md#2-判断依据源码链)。
- 复位后重新枚举且 `result: idle`：loader 已重新启动，先前的 RAM 系统盘需要重新上传。
- `result: reset-failed`：PSCI 复位调用返回，直接读取日志中的返回值；loader 保留 USB 命令循环。
- `result: no-such-core ...`：先保存 loader 原始日志，核对目标 MPIDR 和 PSCI 返回值。屏幕上的旧画面不能用来评估本轮。
- USB 有枚举记录但命令无响应：可能是内核占用 loader 的 CPU、USB 传输等待或固件异常。记录命令、耗时、USB 枚举与画面，按 [USB 恢复经验](../analysis/2026-10-25-usb-recovery-lessons.md)分别排查；设备从 USB 整个消失时的处置也在该文档第 4 节。
- loader 看门狗：主机 180 秒没有发命令时，loader 不再喂 Haven 虚拟看门狗，手机复位后回到 A 槽 loader，A 槽重试用完时回到 B 槽 Android（`HOST_SILENCE_SECONDS`，`xnuloader/loader_04_fault_payload_nvram.inc`）；运行中的内核自己喂看门狗。
- 返回 Android：按 [SOP §2](device-boot-target-sop.md#2-五条切换路径) 先进入 LK，再 `set_active b` 加 `reboot`。loader 的 `reboot` 在 annibale 上只执行 PSCI_SYSTEM_RESET，目标仍由当前槽位决定。
- `oem logwrite` 会覆盖 `boot_a` 开头，不能用于保存启动后的日志；真机调试使用 USB 日志。
- 桌面 wch 串口属于其他设备。手机 UART 为 GENI `0xa9c000`、`115200n8`，当前没有连接调试线，默认保持关闭。
- Android 整组 `pinmux-pins`／`pinconf-pins` 调试读取后曾发生重启。优先使用已保存的设备树和驱动定义，再决定定点读取；读取硬件调试文件前按实现检查副作用。

## 7. 四阶段验收

| 阶段 | 本轮需要取得的结果 |
|---|---|
| loader 已运行 | `getvar product` 返回 `xnuloader`，可读取 loader 日志 |
| 内核已运行 | 内核检查点返回或 USB 日志中出现内核初始化输出 |
| 系统盘已挂载 | 日志出现 `BSD root: md0` 和 APFS System 卷挂载结果 |
| SpringBoard 已显示 | SpringBoard 进程日志、帧缓冲截图和手机实际画面相互确认 |

图形交互验收同时检查 SpringBoard、backboardd、前台应用的 `userabort`／`usertrap` 与断言，并记录 SpringBoard／backboardd 的 PID，可用 `tools/k90auto/ui-health.py`（[k90auto 说明 §6](../../tools/k90auto/README.md#6-界面进程状态检查)）。原始日志可能含 NUL，检索使用文本模式。采集和软件恢复成功后，界面进程中止或重启时功能结果仍记为失败。

## 8. 外设开关（修改 kernel payload 的 cmdline）

`make-payload.py` 固定带 `touchscreen=2 buttons=1 battery=1`，`cycle.py` 的 `FIXED_ARGS` 再加 GPU、120 Hz、触摸轮询和 Wi-Fi 一组，其余参数用 `cycle.py --boot-args` 追加。每轮只增加一个待测参数，先检查 USB 日志和对应的实际行为。触摸、震动、手电不带参数时不做任何动作，QEMU 也不需要它们。

- `touchscreen=2`：annibale Goodix 触摸。先查芯片身份、报告模式和有效触点，再验证用户滑动与点击的坐标及延迟。`ready` 日志和自动操作脚本的手势都不足以完成手指操作验收。`cycle.py` 另带 `touch_poll_us=4000`，每 4 ms 读一次。
- `buttons=1`：音量键与电源键，只读 PMIC，不写入（`annibale_buttons.c`）。音量上是 PMI GPIO slave 1 function `0x18d`，低有效带上拉；电源和音量下是 PMK8550 PON（KPDPWR／RESIN）。事件进 USB 日志的 `buttons:` 行和 `/dev/redwood-input`，`buttons_hv_steps=1..5` 分步诊断。验收依次查看 arbiter、通道表、TYPE/SUBTYPE、引脚状态和 `buttons:` 事件，再核对 iOS 行为。
- `battery=1`：读取 I²C 地址 `0x55` 的 BQ27Z561，经 GPIO52/53 传输并在采样后恢复引脚（`annibale_battery.c`）。检查电量、电压、温度及 `RedwoodBattery` 发布结果；充电状态显示仍不准，见[默认参数与充电状态](../progress/2026-11-05-defaults-and-charging.md)，读法见[桌面交互案例](../analysis/2026-10-24-interactive-runtime.md) §4。
- `cpufreq=1`：按负载调频、空闲降档、触摸短时提频；CPU 达到 70 °C 后降到最低档，低于 60 °C 后恢复。`cpufreq=2` 只报告，`cpufreq=3` 为固定频率对照；日常交互使用模式 1。
- `fbwidth=1206 fbheight=2622 fbpitch=460`：iPhone 17 的画布，`cycle.py` 默认追加在最后，原因见[状态栏布局分析](../analysis/2026-11-02-status-bar-layout.md)。内核缺省是 1125×2436，需要支持 `fbpitch` 的内核；`fbpitch=0` 保留按宽度缩放的密度。
- `pcie=N`：Wi-Fi 卡（WCN7850）执行第 1～N 步，最多 10（`mhi_pcie.c` 文件头）。第 1～6 步是诊断读取，7～9 步启动卡上固件并与 WLFW 服务交换，第 10 步由 ath12k 驱动代替第 7～9 步。`cycle.py` 固定带 `pcie=10` 一组和 `wifi_station=1`，见 [Wi-Fi 驱动记录](../progress/2026-11-01-wifi-ath12k-driver.md)。
- 手电（`annibale_torch.c`，需要内核 `4d6eee3` 及以后）：`torch_secs=3` 亮 3 秒后自动熄灭（驱动内最多 5 秒），`torch_ma=1..500` 调电流，默认 125；`torch=3` 提供 `/dev/redwood-torch` 给 iOS 的 AVFlashlight 与 mediaserverd，单次默认 30 秒，`torch_max_s` 最多 120 秒。驱动先验 TYPE/SUBTYPE 且无 fault 才写，每次写入都回读，遇到 fault 拒绝点亮。
- 震动（`annibale_haptic.c`，需要内核 `5847dd3` 及以后）：`hv_haptic=3` 起内核后直驱马达 30 ms，靠手感验收，没感觉时加 `haptic_amp=128`，仍没有就读 USB 日志的 `haptic:` 行；`hv_haptic=4` 让 iOS 触感反馈经 `/dev/redwood-haptic` 驱动马达，单次最长 1 秒，出现 fault 后停用。
- 更早的内核用 Extended Register Write 写 PMIC，寄存器值不变，驱动在第一次读回不一致时停止，见[手电与震动实测](../progress/2026-10-26-torch-and-haptics.md)。手电与震动在 iOS 16.5 上实测通过，iOS 26 上还不能用。

## 9. 大于单次 fastboot 长度的 RAM 系统盘

`tools/stage-system.sh` 对超过 `0xffffffff` 字节的镜像使用分块协议，要求 `getvar ramdisk-protocol` 返回 `1`，并由 `STAGE_SYSTEM_WINDOW` 提供十六进制内存窗口字节数（`cycle.py` 用 `0x300000000`）。窗口必须按 32 MiB 对齐，并容纳系统盘、loader 保留区与内核运行空间；已分配窗口必须与请求完全一致，调整窗口需重启 loader。较小镜像使用单次上传（`oem ramdisk` 后 `stage`）。

| 命令 | 行为 |
|---|---|
| `getvar ramdisk-protocol` | 返回协议版本 `1` |
| `oem ramdisk begin TOTAL_HEX WINDOW_HEX` | 校验长度和窗口，开始新的顺序上传，清除已发布镜像长度 |
| `download:SIZE_HEX` | 标准 fastboot 数据传输，追加一个完整块；主机脚本使用 256 MiB 块 |
| `getvar ramdisk-state` | 返回状态、已完成块的总字节数、镜像总长度、窗口长度；三个数值均为十六进制 |
| `oem ramdisk none` | 取消上传，清除镜像长度；继续保留内存窗口及现有 USB 缓冲归属 |
| `oem dsu load TOTAL_HEX WINDOW_HEX` | 从手机存储里的 Android DSU 读入系统盘（`run-auto.py` 使用） |
| `oem dsu crc OFFSET_HEX LENGTH_HEX` | 计算一段 CRC，结果用 `getvar dsu-crc` 读；`run-auto.py` 逐 GiB 比对，不一致时 `oem ramdisk none` 后改走 USB |

状态查询只用 `getvar ramdisk-state`。loader 按 `oem ramdisk` 前缀决定下载归属，`begin` 和 `none` 之外的任何 `oem ramdisk` 参数都会清除已发布镜像长度并把下一次 `download:` 指向 RAM 区，`max-download-size` 随即变为 `0xffffffff`。发现该值后用 `oem ramdisk none` 清除归属，确认 `max-download-size` 回到 `0x03700000` 再继续；`reboot-lk.py` 的前置检查会以「Loader download target is not its payload buffer」拒绝这种状态，且不会发出 reboot。

只有全部数据接收完成才发布 `resident_rd_size`。分块短传、非法长度、断线或 USB 通道失效后进入失败状态，拒绝续传和运行，需要取消或重新开始。主机未收到成功应答就停止，不重发含义不确定的块，也不执行内核。最后一块可能已经完整接收但应答未到主机，此时仍需重新查询状态并记录该轮结果。分块短传、断线及重传的固件行为没有单独真机验证。

## 10. 分区备份

写 `boot_a` 或切换槽位前，建议先备份两个槽位的 `boot` 等重要分区，方法见[分区备份说明](../backup/README.md)。
