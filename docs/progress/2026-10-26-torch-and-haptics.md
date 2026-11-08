# K90 手电与震动驱动实测（2026-10-26）

手电驱动 `bsd/dev/annibale_torch.c` 和震动驱动 `bsd/dev/annibale_haptic.c` 在 K90 上的写法与无人值守实测。实测在 iOS 16.5 上完成；iOS 26 上两项还不能用（§1）。启动参数的含义见[真机调试手册](../plan/device-test-playbook.md)第 8 节，硬件节点见[硬件资源图谱](../analysis/annibale-hw-map.md) §5。

## 1. 结论

- 手电（iOS 16.5）：`torch_secs=2 torch_ma=50` 时，驱动依次写入安全定时器、目标电流、模块使能和通道 0 使能，每次写入都读回一致，报告通道 0 以 50 mA 点亮 2 s 后熄灭。`torch=3` 时 iOS 经 AVFlashlight 和 mediaserverd 控制手电，控制中心出现手电按钮（§4）。
- 震动（iOS 16.5）：`hv_haptic=3` 时，驱动完成配置（1300 mV、5714 µs 周期、闭环制动、正弦波形），以幅度 0x60 直驱马达 30 ms，故障寄存器为 0。`hv_haptic=4` 时，长按图标弹出快捷菜单，iOS 播放的触感经 `/dev/annibale-haptic` 驱动马达（§6）。
- PMIC 写入必须用 Extended Register Write Long（仲裁器操作码 0）；用 Extended Register Write（操作码 2）写 1～4 字节时 K90 上寄存器值不变（§2）。
- 仲裁器写通道窗口只映射用到的通道各 4 KB；只映射前 64 KB 或整个 4 MB 窗口都导致过 panic（§3）。
- iOS 26（`kernel-12377-rate7-def1`，11-05）：手电初始化报 `reading 0x0018 gave: the transfer was dropped`，随后 `the light for iOS stops after 0 times lit: the module said something surprising`；震动的故障寄存器 0x10 清不掉。原因没有查，两项不进默认参数，见[默认参数与充电状态](2026-11-05-defaults-and-charging.md)。
- 灯是否实际亮起、马达是否实际振动，都没有人在场确认。

## 2. SPMI 仲裁器写入

两个驱动经 PMIC 仲裁器 v7（版本 `0x70020000`，896 个通道）访问 PMIC：读走观察窗口 `0xc440000`，写走通道窗口 `0xc500000`，每个通道 `0x1000` 字节，布局按 Linux `drivers/spmi/spmi-pmic-arb.c`。

- 读取用 Extended Register Read（操作码 13），按键驱动和这两个驱动的读数都与原厂设备树和寄存器定义一致。
- 用操作码 2 时，手电驱动把安全定时器 `0x3e` 从 `0x93` 写为 `0x13`，仲裁器报告传输完成且没有错误位，读回仍为 `0x93`，驱动按规则停止全部写入。
- Linux 的 `regmap-spmi-ext` 对 16 位寄存器地址发送 Extended Register Write Long（操作码 0），annibale 的 `annibale_torch.c` 也用操作码 0。手电（内核 `4d6eee3`）和震动（内核 `1f83244`）改用操作码 0 后，同一写入读回一致。操作码 2 写入无效的原因没有确认。
- 手电驱动在读回不一致时会在 1 ms 后再读一次并一起报告，用于区分寄存器延迟更新和写入无效。

## 3. 手电

模块为 PM8550（SPMI slave 1）的 flash LED，寄存器 `0xee00`，仲裁器通道 617，写入方为系统 0（APPS）。启动时读到的状态：type `0x18`、subtype `0x07`，无实时故障和锁存故障，安全定时器 `0x93`（定时器使能，200 ms），strobe `0x01`。

- 写通道窗口的映射：通道 617 位于 `0x269000`。只映射前 64 KB 时写入地址落在映射之外，Kernel data abort（`861f9bd`）；映射整个 4 MB 窗口时启动早期 `kmem_alloc(..., 4194304, ...)` 返回 3（`KERN_NO_SPACE`，`f1f2665`）。内核 `5557759` 起只映射用到的通道各 4 KB，并在发现模块后才映射，之后没有 panic。
- 原厂驱动 `leds-qti-flash.c` 在探测和关闭时清除安全定时器使能位，只在闪光模式下设置。本驱动点亮前清除该位，熄灭时恢复启动时的值。
- 内核 `4d6eee3`、`d4df543`、`5847dd3` 的三轮都点亮 2 s 后熄灭，熄灭后模块使能、电流档位、strobe 和通道 0 目标电流均为 0。

## 4. iOS 手电（`torch=3`）

内核 `a56627f` 在 `torch=3` 时创建 `/dev/annibale-torch`，接口与 POCO X5 Pro 相同：写入 32 位档位 0～1000（`torch_ma` 的千分之几，0 为关），读出当前点亮的档位。根盘中 `libannibale-media.dylib` 的 FigFlashlight 替换直接使用这个设备。

- 安全限制：点亮期间每 100 ms 检查一次仍处于点亮状态、没有实时故障、电池温度不超过 45 °C；单次点亮最长 `torch_max_s`（默认 30 s，最多 120 s），到时熄灭，直到 iOS 写入 0 后才能再次点亮。点亮状态下改变档位只写 ITARGET。
- loader 在任何 `torch=N` 时告诉 iOS 相机有闪光灯，控制中心因此显示手电按钮。
- 实测（内核 `00259e5`）：mediaserverd 报告「the kernel has a flashlight (/dev/annibale-torch)」，AVFlashlight 的 `hasFlashlight`、`available` 都为 YES。档位 1.0 时 ITARGET `0x03`，通道 0 以 50 mA 点亮；档位 0.25 时 ITARGET `0x00`（12.5 mA）；档位 850 时 ITARGET `0x02`（37.5 mA）；关闭时通道和模块使能清零。
- 用 `rwtouch` 点按控制中心的手电按钮，3 轮里 mediaserverd 每轮先收到档位 850、内核点亮，再收到 0、内核熄灭。
- 时长上限生效过一次：另一个进程新建的 AVFlashlight 读到档位已是 0，没有向 mediaserverd 发出关闭，灯保持点亮，内核在亮满 30 s 时熄灭。

## 5. 震动

模块为 PMIH010x（SPMI slave 7）的 HV haptics：驱动 `0xf000`、波形引擎 `0xf100`、升压 `0xf200`，对应仲裁器通道 648、649、650，写入方为系统 0；通道 577、578 是同一组外设的另一组通道，写入方为系统 3。

- 只读检查（`hv_haptic=1`）：驱动和波形引擎 revision `0x5.0x1`，升压 `0x1.0x1`，故障 0，实时状态 `0x8`，HPWR 0，阻抗读数 0，FIFO ready 1。
- `FAULT_CLR`（`0xf066`）是写 1 清除的命令寄存器，写入后自动归零，不能做读回比较（`d4df543` 写 `0x07` 后读回 0，驱动因此停止，模块保持使能）。内核 `5847dd3` 起，写 `FAULT_CLR` 后改为检查故障状态寄存器 `0xf00c` 为 0；只要写过寄存器，退出路径和 quiesce 都关闭模块。
- 内核 `5847dd3`：VMAX `0x1a`、制动模式 `0x41`、波形选择 `0x11` 写入并读回一致；直驱 30 ms 后故障寄存器为 0，HPWR 从 0 变为 `0x3`，阻抗读数仍为 0。

## 6. iOS 触感反馈（`hv_haptic=4`）

`hv_haptic=4` 时内核创建 `/dev/annibale-haptic`，根盘中 AnnibaleAudio 插件把 iOS 在「Actuator」设备上播放的波形写入这个设备，驱动按波形峰值直驱马达，单次最长 1 s，出现故障即停止使用马达。

内核 `ffca661` 的一轮里，解锁后做 6 轮操作，每轮长按「备忘录」图标 1.2 s、按 home 收起快捷菜单，再下拉控制中心和左右翻页：

- 截图中长按后出现「备忘录」的快捷菜单。
- 驱动记录 7 次短触感和 1 次持续振动。短触感中 6 次波形峰值为 23519／32768，按 `0x60` 直驱；1 次峰值 906，按 `0x3e` 直驱。持续振动在 iOS 停止播放后 301 ms 结束。整轮没有故障，运行 420 s 没有 panic。

## 7. 剩余工作

- iOS 26：查清手电读 `0x0018` 时传输被丢弃、震动故障寄存器 0x10 清不掉的原因（§1）。
- 人工确认：`torch_secs=2` 时闪光灯是否亮 2 s 后熄灭；`hv_haptic=3` 时开机后是否有一次约 30 ms 的振动；`hv_haptic=4` 时长按图标是否有震感；控制中心手电按钮点按后灯是否实际亮灭。
