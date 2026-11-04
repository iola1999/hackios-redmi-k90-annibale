# K90 屏幕亮度调节调研（2026-11-02）

本文回答控制中心和设置里的亮度滑块怎样调到 K90 面板的真实亮度。只读调研：读了 iOS 26 共享缓存（`23G90__iPhone18,3`，下文地址都是未滑动地址）、本仓库源码、Android 设备树和参考仓库 dada 的内核补丁，没有操作设备，也没有构建。`DTS:行号` 是解压后的 `docs/analysis/data/annibale.dts.gz`。

## 1. 需要用户决定的事

1. 是否给面板发 DCS 命令。真实调光要经 DSI 给面板发 `0x51`；发错的包可能让面板驱动芯片卡住，我们没有面板的上电序列和 DSC 配置，卡住后只能重启手机恢复。方案只发 `0x51` 和 `0x53` 两种命令。
2. 亮度上限。面板的 `max-level` 是 0x3fff，出厂上限是 0x1a5e，0x1a5e 以上推测是高亮（HBM）区间。建议先以 0x1a5e 为上限，HBM 以后再说。
3. 如果不发 DCS，退路是在面板驱动拷贝像素时整体压暗（§6），只能变暗，低亮度下渐变会有色阶。

## 2. 结论

- iOS 26 的每一条调亮度路径最后都落到三个键之一：`AppleARMBacklight` 服务上的 `brightness` 与 `brightness-nits`，以及 IOMobileFramebuffer 上的 `IOMFBBrightnessLevel`。我们的内核没有发布带 `backlight-control` 的服务，`MiniIOMobileFramebuffer.cpp` 也没有 `setProperties`，所以现在滑块的调节不会到达内核（推断，日志里没有直接看到）。
- K90 面板跑在 DSI 命令模式（[开机次序与性能记录](../progress/2026-10-31-boot-order-and-performance.md) bo53：CTL0 以命令模式驱动 INTF1，每帧自动刷新），亮度靠 DCS `0x51`。命令模式下面板自己保存最后一帧，暂停像素流不会黑屏（推断）。
- dada 没有做亮度：补丁里两处 brightness／backlight 都与此无关，也没有 DSI、DCS 或面板命令的代码。

## 3. iOS 26 的调用路径

- 入口：控制中心的 `DisplayModule` 和设置把 0～1 的浮点数交给 `BKSDisplayBrightnessSet`，发到 `com.apple.backboard.hid.services`（0x18698c854），在 backboardd 里由 CoreBrightness 的 `BLControl` 处理（推断）。
- 找显示：`-[BLControl findBacklight]`（0x1e2705848）和 `-[CBDisplayContaineriOS findBacklight]`（0x1e2736274）按 `{IOPropertyMatch:{backlight-control:true}}` 匹配；匹配到的服务若 `IOObjectConformsTo(…, "AppleARMBacklight")`（0x1e27363b4），建内置显示模块 `CBDisplayModuleiOS initWithBacklight:queue:display:`。找不到时打印 `Built in display/backlight driver has not been found.`（0x1e2705090）。
- 写入的值（都是 SInt32 的 CFNumber）：
  - 初始化时读背光服务的 `IODisplayParameters` → `brightness` → `value`／`min`／`max`（0x1e2742114～0x1e27421f8）；没有标定数据时用 5／140／400 尼特的默认值（0x1e274224c，推断）。
  - 级别路径：`IORegistryEntrySetCFProperties(背光, {brightness: min + f·(max − min), FadePeriod, [backlight-level]})`（0x1e2754a94～0x1e2754eac）。
  - 尼特路径：`IORegistryEntrySetCFProperty(背光, "brightness-nits", 尼特 × 65536)`，调用方打印 `Setting BL nits value to %f`（0x1e26545dc、0x1e2654718）。
  - IOMFB 路径：`IORegistryEntrySetCFProperty(IOMFB 服务, "IOMFBBrightnessLevel", 尼特 × 65536)`（0x1e2654acc），值变化时才写，服务由 `IOMobileFramebufferCreateDisplayList`、`OpenByName`、`GetServiceObject` 取得，就是我们的 IOMobileFramebuffer。
  - 逐帧同步路径：MobileGestalt `DeviceSupportsFrameSynchronousBrightness` 为真时由 QuartzCore 打开（0x18418bb3c，backboardd 偏好 `SynchronousBrightnessTransactions` 可以覆盖）。打开后 CoreBrightness 关掉 IOMFB 属性路径（0x1e260099c），QuartzCore 调 `IOMobileFramebufferSwapSetBrightness`（0x183f54990），在 swap 记录 +0x354 写标志字节、+0x35e 写一个 double（推测是尼特），同时经 BrightnessControl 的 `BCBrtControlSetNits` 写背光服务的 `brightness-nits`（0x2294d061c）。
  - 回读：BrightnessControl 读 `IODisplayParameters` 里的 `brightness{min,max}`、`BrightnessMilliNits{min,max,value}`、`BrightnessMicroAmps`（0x2294ce8e0），之后读 `BrightnessMilliNits.value`（0x2294d08bc）。
- 选择子 50（`SetBrightnessCorrection`）是 CoreAnimation 发的每块屏幕的修正系数，与滑块无关，见 [IOMFB 选择子名称](2026-10-28-iomfb-selector-names.md)。
- 内核要提供的：一个 `AppleARMBacklight` 类的服务，带 `backlight-control=true` 和 `IODisplayParameters` 字典，在 `setProperties` 里接受 `brightness` 与 `brightness-nits`；IOMobileFramebuffer 接受 `IOMFBBrightnessLevel`。

## 4. K90 面板

面板节点从 DTS:40854 起：

- 调光：DCS `0x51`（`bl_ctrl_dcs`），按 HS 模式发（DTS:40867）；范围 5～0x3fff（DTS:40868-40869），开机初值 0x35a（DTS:40865），出厂上限 0x1a5e（DTS:40883）；`qcom,mdss-dsi-bl-inverted-dbv`，两字节按大端（DTS:40904）。设备树里的例子：`51 34 bc` 开高亮（DTS:41011），`51 00 2e` 是 doze。
- 开机序列含 `35 00`、`53 20`、`51 00 00`、`11`、`29`；`53 28` 打开渐变（DTS:41021）。
- `mdp-transfer-time-us` 7300 µs（DTS:40972），120 Hz 下每帧只有约 1 ms 空闲；`dma-trigger = trigger_sw`，`dma-schedule-line = 1`。
- DSI 控制器：ctrl0 在 0xae94000，长 0x1000，`qcom,dsi-ctrl-hw-v2.9`；INTF1 在 0xae36000（DTS:41195-41208）。面板驱动现有的映射正好止于 0xae94000，DSI 要单独 `ml_io_map`；`flip_clocks()` 已经打开 AHB 时钟（`MiniFramebufferFlip.inc:113`）。
- 正常区间与 HBM 的分界不知道，以 0x1a5e 为上限是推断。

## 5. 从内核发 DCS 命令

下表的寄存器偏移凭主线 msm 的 `dsi.xml.h` 和下游 `dsi_ctrl_reg.h` 回忆得出，本地没有来源，第 2 步上机时先只读核对：

| 偏移 | 寄存器 | 用途 |
|---|---|---|
| 0x004 | CTRL | |
| 0x008 | STATUS | bit1 DMA 忙，bit31 冲突 |
| 0x03C | CMD_DMA_CTRL | bit28 嵌入式，bit26 低功耗 |
| 0x048 | DMA_CMD_OFFSET | 命令缓冲地址 |
| 0x04C | DMA_CMD_LENGTH | |
| 0x084 | TRIG_CTRL | `BLOCK_DMA_WITHIN_FRAME`：等一帧传完再发 |
| 0x090 | DMA_SW_TRIGGER | 写 1 触发 |
| 0x110 | INT_CTRL | bit0 DMA_DONE，写 1 清 |

- 内存里的调光包 8 字节：`03 00 39 C0 51 高字节 低字节 FF`。
- DMA 经显示 SMMU 取数，dada 上只有 splash 区可取（`MiniFramebufferFlip.inc:18`），命令缓冲放在 splash 区末尾；读 `DMA_CMD_OFFSET` 能看到 bootloader 用的地址。

## 6. 退路：拷贝时压暗

- 在 `drawLayer`（`MiniIOMobileFramebuffer.cpp:585`）里按比例缩小像素值。
- 代价：这段拷贝的处理器时间多 10%～30%（推断，现在 p50 约 1.77 ms）；每次改亮度要整帧重画一次，因为 `fb_rows` 平时只画变化的行。
- 效果：每个通道可用的位数变少，低亮度下渐变有色阶；只能比面板当前亮度暗。OLED 上压暗也省电（推断）。
- 另一个选项是用 DPU 的 VIG CSC 或 DSPP PCC 矩阵压暗，不占处理器时间，这些寄存器还没有研究。

## 7. 实施顺序

| 步 | 内容 | 成功判据 | 设备 |
|---|---|---|---|
| 1 | 不重编：跑 `mg_test DeviceSupportsFrameSynchronousBrightness`，在 backboardd 日志里找 `Built in display/backlight` | 知道逐帧同步路径开没开，确认「没找到背光」的现状 | 是 |
| 2 | 新文件（`MiniIOMobileFramebuffer.cpp` 已超过 AGENTS.md §2 的行数上限）：`AppleARMBacklight` 服务，带 `backlight-control`、`brightness{5, 0x1a5e, 0x35a}`、`BrightnessMilliNits`；它和 IOMobileFramebuffer 的 `setProperties` 只记日志；只读打印 §5 的 DSI0 寄存器。不给面板发任何命令 | 拖动滑块时日志里有键、值和频率；看到 `BLOCK_DMA_WITHIN_FRAME` 的状态和 bootloader 的 DMA 缓冲地址 | 是 |
| 3 | boot-arg 打开时发一次 `51 03 5A`，缓冲在 splash 区末尾 | DMA_DONE 置位，`ACK_ERR`、`STATUS` 干净，INTF1 帧计数继续走，人或摄像头确认亮度变化 | 是，需要人看 |
| 4 | 把第 2 步接到第 3 步：`brightness` 直接作为面板亮度值，尼特按线性换算；夹在范围内，每帧最多写一次，写完更新 `value` 和 `BrightnessMilliNits.value` | 滑块从低拖到高时亮度跟着变，面板和帧计数正常 | 是 |
| 5 | 可选：`53 28` 渐变、HBM。自动亮度需要环境光传感器，现在没有 | | 是 |

## 8. 风险与未知

- 面板卡住只能重启恢复。
- DSI 寄存器偏移没有本地来源，要上机核对。
- DSI 的 DMA 能否经 SMMU 取到内存不知道。不经 DMA 的发法（DSI 测试模式 FIFO）见 [11-05 上游对照](2026-11-05-upstream-lessons.md) §1 第 7 项，寄存器偏移来自 SM8850，要在 SM8750 上核对。
- 正常亮度与 HBM 的分界不知道。
- CoreBrightness 要的属性比本文最初列的多，见第 9 节。
- iOS 会因温度压低亮度：dada 遇到过电池温度报 43～45 °C 时 iOS 把屏幕压到接近全黑，它的处理是把报给 iOS 的温度设上限（dada 补丁第 24812 行）。

最有用的第一个真机实验是第 2 步：一次构建，不给面板发命令，就能看到 iOS 实际走哪条属性路径、用什么单位，以及 DSI 的 DMA 是否可用；`mg_test` 可以放在同一轮里跑。

## 9. 实测（2026-11-05）

轮次与读数见 [11-05 记录](../progress/2026-11-05-defaults-and-charging.md) §3.7，代码在内核仓库的 `MiniAppleARMBacklight.cpp` 与 `MiniFramebufferDim.inc`。

- 只发布带 `IODisplayParameters` 的 `AppleARMBacklight` 不够：backboardd 在 CoreBrightness 里读空指针，反复崩溃（`rate11-w3`）。CoreBrightness 还经背光节点及其父节点读 `backlight-calibration-parameters`（16.16 定点数的字典，`-[CBBacklightNode getBacklightCalibration:]`，`0x1e2731760`）和 `backlight-marketing-table`（16.16 定点数组成的 data），后者缺失时显示初始化失败。
- 两项补齐后（`rate12-br1`），iOS 走 IOMFB 路径：`IOMFBBrightnessLevel` 发到 IOMobileFramebuffer，单位是尼特 × 65536，渐变时每秒约 180 次；`brightness` 与 `brightness-nits` 没有出现在日志里。
- 没有发 DCS。退路改用显示控制器的混合器：`fb_dim=1` 时把画面所在 stage 的常量 alpha 设为亮度比例的平方根（按面板 gamma 约 2.2 推断），截图看不出变化，寄存器回读随滑块变化（`rate13-br2`）。这种做法只能变暗，低亮度下有色阶，与第 6 节的拷贝时压暗相同。

