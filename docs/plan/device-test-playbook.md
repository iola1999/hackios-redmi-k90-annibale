# annibale 真机调试手册

本手册收集驻留 loader 的安装、手工运行内核、读日志、故障恢复和启动参数。开发者诊断轮用 `tools/k90auto/cycle.py`，见 [k90auto 说明](../../tools/k90auto/README.md)；日常启动与切换见[体验说明 §11](../user-guide.md#11-日常使用与切换)；Android／LK／loader 之间的切换细节见[引导目标切换 SOP](device-boot-target-sop.md)；USB 命令超时与无应答见 [USB 恢复经验](../analysis/2026-10-25-usb-recovery-lessons.md)。当前进度见[进度表](2026-10-23-tracking.md)，操作前仍需确认设备与产物现状。本文已按 UFS 系统卷与 4 MiB 启动卷更新；该路径已通过真机切根与重启验证，验收边界见[根文件系统说明](../analysis/rootfs-strategy.md)。

## 1. 槽位假设与当前启动方式

本项目的脚本按「Android 在 B 槽、loader 写在 A 槽的 boot 分区」编写。`tools/k90auto/cycle.py`、`tools/k90auto/reboot-lk.py`、`tools/k90auto/recover-loader.py` 固定执行 `set_active a`，`recover-loader.py` 还断言 Android 的 `ro.boot.slot_suffix` 为 `_b`。下文命令按这个布局写；Android 在 A 槽的设备需要对调命令里的 a／b，并修改这些脚本。

各产物的选择与来源：

- loader：以设备实际 `getvar build-id` 和本轮镜像构建记录核对。`cycle.py` 通过 [`recover-loader.py`](../../tools/k90auto/recover-loader.py) 进入已枚举的空闲 loader；显式指定 `LOADER_IMAGE=FILE` 或设置 `CYCLE_CHECKPOINT=1` 时，经 LK 执行检查点，需要 `ANDROID_SERIAL`。`LOADER_IMAGE` 指定完整调试镜像，未指定时从 A 槽启动；具体步骤见 [k90auto 说明 §8](../../tools/k90auto/README.md#8-渲染问题的无人值守检查)。Wi-Fi 需要 loader 在 4 GB 以下为 Wi-Fi 卡保留 128 MB 内存，v16 起提供这一内存区域。
- 内核：构建后用 `register-kernel.py` 登记，再用 `cycle.py --kernel <内核名>` 选择；缺省值由 [`cycle.py`](../../tools/k90auto/cycle.py) 的 `KERNEL` 定义，新环境需先登记本地构建。`make-payload.py` 从 `kernel.json` 取内核并核对哈希，再与辅助盘打包成载荷，构建与登记见 [k90auto 说明 §1](../../tools/k90auto/README.md#1-前提与产物位置)。
- 系统卷：部署在 UFS `darwin` 分区，由内核 APFS 驱动按需读取。`userland/flashboot.apfs` 是本轮构建为 4 MiB 的启动卷，作为 `md0`；`root.apfs` 是辅助盘 `md1`，挂载到 `/annibale`。部署见[双系统分区与持久化部署手册](dual-boot-setup.md)。
- 启动参数：`make-payload.py` 的固定一组加 `cycle.py` 的 `FIXED_ARGS`，见第 8 节与 [k90auto 说明 §8](../../tools/k90auto/README.md#8-渲染问题的无人值守检查)。

每轮收尾的 PSCI 复位会重新启动 `boot_a` 里的镜像，重新枚举后执行 `oem recovery` 进入 Fastboot 空闲态。`cycle.py` 每轮检查 `slot-retry-count:a`，低于 3 时经 LK 重置重试次数。起轮与收尾均需核验 `product=xnuloader`、`result=idle` 和空的启动卷常驻区，恢复要求见第 6 节。

## 2. 操作前检查

1. 确认本轮内核、loader、载荷、辅助盘和启动卷的文件大小与 SHA-256；修改源码后重新构建对应产物。`cycle.py`／`run-auto.py` 按 `manifest.json` 自动核对，手工运行时自己核对。
2. 先看 `adb devices -l` 和 `fastboot devices`，把目标 Android／LK 序列号设为环境变量 `ANDROID_SERIAL`；驻留 loader 使用 `xnuloader`。每次切换后重新确认身份，判别方法见 [SOP §1](device-boot-target-sop.md#1-先判当前身份)。
3. 确认当前槽位和 A 槽重试次数。写启动镜像只用 `boot_a`。连续实验会耗尽 A 槽重试次数，LK 随后回退到 B 槽 Android；这时经 ADB 回到 LK 执行 `set_active a` 即可恢复已有 loader，无需重写镜像，见 [SOP §4](device-boot-target-sop.md#4-陷阱均为实测) 第 4 条。
4. 无人值守跑轮遵守 [AGENTS.md](../../AGENTS.md) 第 5 节。

## 3. 安装驻留 loader

loader 镜像是 Git 忽略的本地构建产物，构建步骤见 [annibale UEFI 与 loader 镜像构建](../analysis/annibale-uefi-build.md#3-装配-loader-镜像)。将本轮完整 loader 镜像路径设为 `LOADER_IMAGE`，核对文件大小、SHA-256 与构建记录后再操作。其中的 UEFI 源码在 [iola1999/hackios-mu-silicium](https://github.com/iola1999/hackios-mu-silicium) 的 `k90-port` 分支；历史 v17 镜像沿用 v16 的 loader，替换了 UEFI，标签 `loader-v17` 对应其中的 FD。

镜像可以先不刷写：在 LK 执行 `fastboot -s "${ANDROID_SERIAL}" boot "$LOADER_IMAGE"`，2026-10-31 实测 loader 约 18 秒后枚举，不改 `boot_a`，也不扣 A 槽重试次数（[SOP §4](device-boot-target-sop.md#4-陷阱均为实测) 第 1 条）。`cycle.py` 用环境变量 `LOADER_IMAGE=FILE` 指定检查点要起的镜像。

刷写前先进入 LK：Android 可连接时用 `adb -s "${ANDROID_SERIAL}" reboot bootloader`；loader 驻留时用 `reboot-lk.py`（[SOP §2](device-boot-target-sop.md#2-五条切换路径)）；软件入口都不可用时请用户长按电源键和音量下进入 FASTBOOT（[USB 恢复经验 §4](../analysis/2026-10-25-usb-recovery-lessons.md#4-按当前环境选择恢复方式)）。

```sh
fastboot -s "${ANDROID_SERIAL}" getvar product
fastboot -s "${ANDROID_SERIAL}" getvar current-slot
fastboot -s "${ANDROID_SERIAL}" flash boot_a "$LOADER_IMAGE"
fastboot -s "${ANDROID_SERIAL}" set_active a
fastboot -s "${ANDROID_SERIAL}" reboot
fastboot -s xnuloader getvar product
fastboot -s xnuloader getvar build-id
fastboot -s xnuloader getvar screen
```

成功条件为 `product: xnuloader`，`build-id` 与本轮构建时的 `BUILD_ID` 一致。屏幕几何应为 `1156 2510 4624`，该值来自固件配置，物理面板的显示仍要目视验证。`reboot` 的主机返回结果只能确认命令已发送，后续状态需要另行读取。

## 4. 手工运行内核

`cycle.py` 会完成打包、上传和运行；下面是手工调试时的等价步骤，在 `hackios-xnu-kernel/` 目录下执行。载荷由 `tools/k90auto/make-payload.py` 生成，路径为 `out/handoff-<内核名>-<标签>.bin`。

```sh
fastboot -s xnuloader stage out/handoff-<内核名>-<标签>.bin
fastboot -s xnuloader oem ramdisk
fastboot -s xnuloader stage userland/flashboot.apfs
fastboot -s xnuloader getvar ramdisk-state
# 核对长度与窗口后再运行
fastboot -s xnuloader oem run
fastboot -s xnuloader getvar result
```

- 先上传 payload，再执行 `oem ramdisk` 并上传启动卷，使 loader 按本轮 payload 分配内存窗口。运行前核对 `ramdisk-state` 的已接收长度、总长度与启动卷大小一致，窗口与 payload 的 `memsize` 一致；本轮 4 MiB 启动卷和 12 GiB 窗口对应 `ready 400000 400000 300000000`。任一项不符就停止。
- `bootcpu=7` 让内核从 MPIDR `0x10100` 的核启动，loader 留在当前 CPU 上处理 USB。
- 结束运行用 `fastboot -s xnuloader oem stop`，或在触摸屏五指同时按住 1.5 秒（`annibale_input.c` 的 `exit_hold_elapsed()`，退回前自动同步 `/private/var` 并停止 Wi-Fi），再查询 `result`。
- 通过 `fastboot -s xnuloader oem "sh ..."` 执行命令时，命令正文长度必须 `<= 119` 字节（建议统一用 `tools/k90auto/rsh.py`），超长包（`> 511` 字节）会导致 DWC3 `USB_EP_OUT` 返回 `CompleteError` 并在本次启动周期内置 `usb_out_lost = 1` 隔离接收端点，详见 [USB 恢复经验 §6.6](../analysis/2026-10-25-usb-recovery-lessons.md#66-oem-sh-超长命令导致-usb_ep_out-端点永久隔离与五指退回黑盒陷阱)。
- 带 GPU 的载荷（`make-payload.py` 默认 `adreno8=23 adreno8_keep=1 adreno8_return=0`）停止后不返回 loader，约 50 秒后 loader 报 `hung-held`，按第 5、6 节保存日志后复位，过程见[无人值守收尾](../analysis/2026-10-28-unattended-teardown.md)。`GPU_STAGE=0` 打包的载荷不起 GPU，内核可以返回 loader。
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
- `result: returned ...` 或 `checkpoint ...`：先保存终态与日志。下一轮必须重新进入已枚举的 loader，独立核验 `product=xnuloader`、`result=idle` 和空的启动卷常驻区。
- `result: returned ...`、`oem stop` 成功和 annsh 退出码 0 只说明对应调用结束。one-shot loader 在内核返回后会进入 recovery 界面；起轮前检查 `result`、`ramdisk-state`、UFS 在途请求和 GPU 日志。出现 `retained until cold reset` 时，保留原内核内存与映射，保存返回快照后执行共享恢复入口。终态硬校验失败即停止后续轮次。
- recovery 界面的 `getvar screen` 可能返回空值。空的可选显示字段不得阻塞已授权的测试；K90 原始帧按已验证的 1156×2510、每行 4624 字节解码，并保留实际字节数校验。
- standalone 复位后可能直接运行 `boot_a`，读到 `result: running 0 0`。更换候选使用 `tools/k90auto/recover-loader.py <新恢复目录>`，通过 `ANDROID_SERIAL` 和 `LOADER_IMAGE` 选择已识别的设备与完整 loader-only 镜像。工具先停止运行中的内核并保存终态日志，再经 LK 或 B 槽 Android 返回空闲 loader；原停止现场保留常驻 RAM。
- `result: hung ...`：先保存可读日志，核对资源保留状态，再复位。
- `result: hung-held ...`、`returned-held ...` 或带 fault：设备可能仍在访问原内核的内存和映射。loader 拒绝 `oem ramdisk`、`download:`、`oem run` 等会改写资源的命令（完整列表见 `xnuloader/loader_01_base_log_dt.inc` 的 `lc_blocked_cmd`），查询、日志、截图和 `reboot` 保留；没有运行中的内核可通知时，`oem stop` 返回 `FAIL`。先按第 5 节保存日志，再执行共享恢复入口；确认 USB 重新枚举与三项终态硬校验后，按第 4 节上传载荷与启动卷。
- 带 GPU 的内核在普通退出与 panic 返回时都检查 `adreno8_reset_required` 和 `adreno8_memory_retained()`，ACK 成功、失败或分配中途失败都可能要求保留资源；需要保留时内核停在 `adreno8_quiesce()` 不返回，只能复位后再上传下一份内核，源码链见[无人值守收尾 §2](../analysis/2026-10-28-unattended-teardown.md#2-判断依据源码链)。
- 复位后重新枚举且 `result: idle`：loader 已重新启动，按第 4 节重新上传载荷与启动卷。
- `result: reset-failed`：PSCI 复位调用返回，直接读取日志中的返回值；loader 保留 USB 命令循环。
- `result: no-such-core ...`：先保存 loader 原始日志，核对目标 MPIDR 和 PSCI 返回值。屏幕上的旧画面不能用来评估本轮。
- USB 有枚举记录但命令无响应：可能是内核占用 loader 的 CPU、USB 传输等待或固件异常。记录命令、耗时、USB 枚举与画面，按 [USB 恢复经验](../analysis/2026-10-25-usb-recovery-lessons.md)分别排查；设备从 USB 整个消失时的处置也在该文档第 4 节。
- loader 看门狗：`a1c40aed` 起，显式进入 Fastboot 驻留后，只要内核未运行、资源已释放、无固件故障且 USB 端点可用，loader 持续喂 Haven 虚拟看门狗；200 秒无主机命令已验证。其他非运行状态保留 180 秒主机静默期限（`HOST_SILENCE_SECONDS`，`xnuloader/loader_04_fault_payload_nvram.inc`）；运行中的内核自己喂看门狗。复位目标仍由活动槽位与实际重试预算决定，见[驻留验证](../analysis/2026-11-11-multimedia-validation.md#16-显式-fastboot-驻留)。
- 返回 Android：按 [SOP §2](device-boot-target-sop.md#2-五条切换路径) 先进入 LK，再 `set_active b` 加 `reboot`。loader 的 `reboot` 在 annibale 上只执行 PSCI_SYSTEM_RESET，目标仍由当前槽位决定。
- `oem logwrite` 会覆盖 `boot_a` 开头，不能用于保存启动后的日志；真机调试使用 USB 日志。
- 桌面 wch 串口属于其他设备。手机 UART 为 GENI `0xa9c000`、`115200n8`，当前没有连接调试线，默认保持关闭。
- Android 整组 `pinmux-pins`／`pinconf-pins` 调试读取后曾发生重启。优先使用已保存的设备树和驱动定义，再决定定点读取；读取硬件调试文件前按实现检查副作用。

## 7. 四阶段验收

| 阶段 | 本轮需要取得的结果 |
|---|---|
| loader 已运行 | `getvar product` 返回 `xnuloader`，可读取 loader 日志 |
| 内核已运行 | 内核检查点返回或 USB 日志中出现内核初始化输出 |
| 系统卷已挂载并切根 | 日志先出现 `BSD root: md0`，随后确认 `/dev/ufs_darwin` 挂载、根目录切换和 launchd 缓存绑定成功 |
| SpringBoard 已显示 | SpringBoard 进程日志、帧缓冲截图和手机实际画面相互确认 |

图形交互验收同时检查 SpringBoard、backboardd、前台应用的 `userabort`／`usertrap` 与断言，并记录 SpringBoard／backboardd 的 PID，可用 `tools/k90auto/ui-health.py`（[k90auto 说明 §6](../../tools/k90auto/README.md#6-界面进程状态检查)）。原始日志可能含 NUL，检索使用文本模式。采集和软件恢复成功后，界面进程中止或重启时功能结果仍记为失败。

### 7.1 图像审阅与短暂异常

涉及渲染、显示或交互的批次，执行者必须用图像查看工具打开本轮截图，分别记录可见画面、像素探针、进程与日志结果。自动计数和图像规则用于筛选待查画面；实际图像审阅应覆盖下列场景，具体故障与进度见[图形待办](../backlog/graphics.md)。

- 桌面：先查看完整屏幕，再查看两个大组件的原尺寸区域，记录内容是否可读，以及白块／黑块遮挡、错误颜色、裁剪和残留。冷启动、解锁与返回桌面分别观察。
- 多任务：确认应用已显示，再上滑停留进入多任务，横滑查看卡片，最后返回应用。核对卡片内容、边缘、背景与激活后的界面；动作注入成功后仍需用截图确认实际进入的场景。
- 采样：由唯一 device 成员通过现有队列串行采集动作前、转场期间可取得的画面、动作结束及短暂稳定观察的截图。记录动作标识、请求和实际采集时刻、截图间隔、失败与缺样；缩略拼图用于定位，异常帧与相邻帧按原尺寸审阅。
- 短暂异常：截图未覆盖的转场阶段继续记为待验。未拍到既往报告的异常，记录「本次未捕获」及实际覆盖范围；随后调整触发动作、采样相位或有界采样密度，仍遵守每批最多 3 轮和单变量约束。
- 采集边界：先核对截图来源、尺寸、行距与颜色格式。帧缓冲读取覆盖到的显示阶段需按实现确认；物理面板扫描结果单独验收。出现画面与日志不一致，先确认截图的新旧、动作时序及读取位置。
- 截图一致性：当前 [`oem screenshot`](../../hackios-xnu-kernel/xnuloader/loader_06_usb_entry.inc) 直接指向 `SCREEN.base`，随后分块上传，未创建冻结副本。动态更新期间可能跨帧读取，是否发生需另行核对；记录实际传输耗时，不能从请求频率推定有效帧率。
- 录屏：短暂异常可由 device 成员使用有界 `rec_secs`／`rec_start`／`rec_mb` 配置采集，并用 [`recording.py --frames`](../../hackios-xnu-kernel/tools/recording.py) 导出原始采样帧。30 fps 转码可能遗漏短帧；当前[录屏实现](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp) 读取提交的 layer 0 surface，按 `rec_step` 降采样，需结合帧缓冲截图审阅，并记录内存占用与复制开销。
- 性能影响：采图与传输可能改变时序，视觉验证记录采样配置；性能对照保持同样的采样安排，耗时测量窗口中的额外采图单独说明。
- 结果：每项记录轮次与产物、实际场景、截图文件及异常区域、发生阶段和下一项定位步骤。无崩溃、探针通过或单张截图正常，只支持各自检查覆盖的范围；已有可见故障继续保留在待办中。

## 8. 外设开关（修改 kernel payload 的 cmdline）

`make-payload.py` 固定带 `rootdev=md0 root_apfs=ufs_darwin ufs=2 ufs_native=1` 与 `touchscreen=2 buttons=1 battery=1`，`cycle.py` 的 `FIXED_ARGS` 再加 GPU、120 Hz、触摸轮询和 Wi-Fi 一组，其余参数用 `cycle.py --boot-args` 追加。每轮只增加一个待测参数，先检查 USB 日志和对应的实际行为。触摸、震动、手电不带参数时不做任何动作，QEMU 也不需要它们。

- `touchscreen=2`：annibale Goodix 触摸。先查芯片身份、报告模式和有效触点，再验证用户滑动与点击的坐标及延迟。`ready` 日志和自动操作脚本的手势都不足以完成手指操作验收。`cycle.py` 另带 `touch_poll_us=4000`，每 4 ms 读一次。
- `buttons=1`：音量键与电源键，只读 PMIC，不写入（`annibale_buttons.c`）。音量上是 PMI GPIO slave 1 function `0x18d`，低有效带上拉；电源和音量下是 PMK8550 PON（KPDPWR／RESIN）。事件进 USB 日志的 `buttons:` 行和 `/dev/annibale-input`，`buttons_hv_steps=1..5` 分步诊断。验收依次查看 arbiter、通道表、TYPE/SUBTYPE、引脚状态和 `buttons:` 事件，再核对 iOS 行为。
- `battery=1`：读取 I²C 地址 `0x55` 的 BQ27Z561，经 GPIO52/53 传输并在采样后恢复引脚（`annibale_battery.c`）。检查电量、电压、温度及 `AnnibaleBattery` 发布结果；充电状态显示仍不准，见[默认参数与充电状态](../progress/2026-11-05-defaults-and-charging.md)，读法见[桌面交互案例](../analysis/2026-10-24-interactive-runtime.md) §4。
- `cpufreq=1`：按负载调频、空闲降档、触摸短时提频；CPU 达到 70 °C 后降到最低档，低于 60 °C 后恢复。`cpufreq=2` 只报告，`cpufreq=3` 为固定频率对照；日常交互使用模式 1。
- `fbwidth=1206 fbheight=2622 fbpitch=460`：iPhone 17 的画布，`cycle.py` 默认追加在最后，原因见[状态栏布局分析](../analysis/2026-11-02-status-bar-layout.md)。内核缺省是 1125×2436，需要支持 `fbpitch` 的内核；`fbpitch=0` 保留按宽度缩放的密度。
- `pcie=N`：Wi-Fi 卡（WCN7850）执行第 1～N 步，最多 10（`mhi_pcie.c` 文件头）。第 1～6 步是诊断读取，7～9 步启动卡上固件并与 WLFW 服务交换，第 10 步由 ath12k 驱动代替第 7～9 步。`cycle.py` 固定带 `pcie=10` 一组和 `wifi_station=1`，见 [Wi-Fi 驱动记录](../progress/2026-11-01-wifi-ath12k-driver.md)。
- 手电（`annibale_torch.c`，需要内核 `4d6eee3` 及以后）：`torch_secs=3` 亮 3 秒后自动熄灭（驱动内最多 5 秒），`torch_ma=1..500` 调电流，默认 125；`torch=3` 提供 `/dev/annibale-torch` 给 iOS 的 AVFlashlight 与 mediaserverd，单次默认 30 秒，`torch_max_s` 最多 120 秒。驱动先验 TYPE/SUBTYPE 且无 fault 才写，每次写入都回读，遇到 fault 拒绝点亮。
- 震动（`annibale_haptic.c`，需要内核 `5847dd3` 及以后）：`hv_haptic=3` 起内核后直驱马达 30 ms，靠手感验收，没感觉时加 `haptic_amp=128`，仍没有就读 USB 日志的 `haptic:` 行；`hv_haptic=4` 让 iOS 触感反馈经 `/dev/annibale-haptic` 驱动马达，单次最长 1 秒，出现 fault 后停用。
- 更早的内核用 Extended Register Write 写 PMIC，寄存器值不变，驱动在第一次读回不一致时停止，见[手电与震动实测](../progress/2026-10-26-torch-and-haptics.md)。手电筒已获用户确认，iOS 26 下的振动待验收。

## 9. 启动卷与内存窗口检查

在 `hackios-xnu-userland/userland/` 执行 `FLASHBOOT=1 FLASHBOOT_ONLY=1 CRYPTEXES=flash bash build.sh`，生成 `flashboot.apfs`。本轮产物为 4 MiB，包含 `stage0` 与挂载目录。`stage0` 挂载辅助盘并执行 `/annibale/sbin/init`，后者从 UFS 挂载系统卷并切换根目录。

- 启动卷上限为 64 MiB；完整 XNUP 容器上限为 `0x03700000` 字节（55 MiB），以未压缩长度校验。
- `getvar ramdisk-protocol` 应返回 `1`；`getvar ramdisk-state` 返回状态、已接收长度、总长度和窗口长度，三个长度均为十六进制。
- 自动流程先检查 loader idle 且常驻区为空，再按第 4 节顺序上传；接收长度与窗口不匹配即停止。
- 独立启动由 `mkstandalone.py --boot-image ...` 将启动卷写入 `rdimage` 条目，loader 校验布局后复制到常驻区。
- `ufs_native=1` 请求原生 UFS 读取；验收需记录实际读取方式、切根结果与可用内存，详见[根文件系统说明](../analysis/rootfs-strategy.md)。当前完整原版系统已通过真机切根与重启验证。
