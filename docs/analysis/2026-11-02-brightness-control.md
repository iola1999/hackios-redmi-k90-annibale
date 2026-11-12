# K90 屏幕亮度调节调研（2026-11-02）

本文回答控制中心和设置里的亮度滑块怎样调到 K90 面板的真实亮度。只读调研：读了 iOS 26 共享缓存（`23G90__iPhone18,3`，下文地址都是未滑动地址）、本仓库源码、Android 设备树和参考仓库 dada 的内核补丁，没有操作设备，也没有构建。`DTS:行号` 是解压后的 `docs/analysis/data/annibale.dts.gz`。

本文的源码状态与推断对应 11-02 调研，11-05 的 DCS 与系统滑块实测见第 9 节。后续单位与持久化修复见[多媒体验证结果](2026-11-11-multimedia-validation.md)，剩余验收见[平台待办](../backlog/platform.md)。

## 1. 需要用户决定的事

DCS 调光已接入系统亮度滑块并默认开启，见第 9 节。实测采用 `0x1a5e` 为面板 DBV 上限；设备树的 `max-level` 为 `0x3fff`，正常亮度与 HBM 的分界尚未确认。当前亮度与持久化验收见[平台待办](../backlog/platform.md)。

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

下表是 11-02 按主线 msm 的 `dsi.xml.h` 和下游 `dsi_ctrl_reg.h` 回忆整理的寄存器偏移，调研时没有本地来源。后续真机读数与实际采用的测试模式 FIFO 路径见第 9 节。

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

`AppleARMBacklight`、IOMFB 属性接收、DCS 发送与回读已完成，调用单位、寄存器读数及滑块实测见第 9 节。后续亮度单位与持久化修复见[多媒体验证结果](2026-11-11-multimedia-validation.md)，低亮度跨重启、滑块与面板一致性及闪烁验收见[平台待办](../backlog/platform.md)。

## 8. 风险与未知

- 面板卡住只能重启恢复。
- 直接使用显示 SMMU 的 DMA 路径在本轮调研时尚未验证，后续采用测试模式 FIFO，SM8750 实测见第 9 节；参考来源见 [11-05 上游对照](2026-11-05-upstream-lessons.md) §1 第 7 项。
- 正常亮度与 HBM 的分界不知道。
- CoreBrightness 要的属性比本文最初列的多，见第 9 节。
- iOS 会因温度压低亮度：dada 遇到过电池温度报 43～45 °C 时 iOS 把屏幕压到接近全黑，它的处理是把报给 iOS 的温度设上限（dada 补丁第 24812 行）。

剩余验证见[平台待办](../backlog/platform.md)。

## 9. 实测（2026-11-05）

代码在内核仓库 `MiniAppleARMBacklight.cpp`、`MiniFramebufferDim.inc` 与 `MiniFramebufferDCS.inc`。

- 只发布带 `IODisplayParameters` 的 `AppleARMBacklight` 不够：backboardd 在 CoreBrightness 里读空指针，反复崩溃（`rate11-w3`）。CoreBrightness 还经背光节点及其父节点读 `backlight-calibration-parameters`（16.16 定点数的字典，`-[CBBacklightNode getBacklightCalibration:]`，`0x1e2731760`）和 `backlight-marketing-table`（16.16 定点数组成的 data），后者缺失时显示初始化失败。
- 两项补齐后（`rate12-br1`），iOS 走 IOMFB 路径：`IOMFBBrightnessLevel` 发到 IOMobileFramebuffer，单位是尼特 × 65536，渐变时每秒约 180 次；`brightness` 与 `brightness-nits` 没有出现在日志里。
- 混合器压暗退路：`fb_dim=1` 时把画面所在 stage 的常量 alpha 设为亮度比例的平方根（按面板 gamma 约 2.2 推断），截图看不出变化，寄存器回读随滑块变化（`rate13-br2`）。这种做法只能变暗，低亮度下有色阶，与第 6 节的拷贝时压暗相同。
- DSI0 寄存器与测试模式 FIFO（`kernel-12377-st2-r1`，`fb_dcs=2`）：只读打印确认 DSI0（`0x0ae94000`）的 `VERSION=0x02090000`、`CTRL=0x000001c5`、`CMD_MODE_DMA_CTRL=0x14000000`、`TRIG_CTRL=0x80000004`（`BLOCK_DMA_WITHIN_FRAME` 已开）、`DMA_CMD_OFFSET=0`。因 `DMA_CMD_OFFSET` 未映射进显示 SMMU，`MiniFramebufferDCS.inc` 采用 `TEST_PATTERN_GEN_CTRL`（`0x158`）的 `CMD_DMA_TPG_EN` 配合 `TEST_PATTERN_GEN_CMD_DMA_INIT_VAL`（`0x168`）直接向 DSI 命令 FIFO 推入 32 位字并触发 `DMA_SW_TRIGGER`（`0x090`），发送前后检查并清除 `ACK_ERR_STATUS`（`0x064`）与 `RDBK_DATA_CTRL`（`0x068`）。
- 固定值发送与 DCS `0x52` 回读校验（`kernel-12377-st2-r2`，`fb_dcs=3`）：向面板发送一次 `51 03 5a`（858），`DMA_DONE` 在 6 微秒内完成，随后发 DCS `0x0a`（`RDDPM`）读回 `0x9c`（Booster ON、Sleep OUT、Display ON）、发 DCS `0x52`（`RDDISBV`）经 `RDBK_DATA0`（`0x06c`）读回 `0x035a`（858），与写入值完全一致。
- 接入系统亮度滑块与默认开启（`kernel-12377-st2-r3`、`kernel-12377-st3-r1`）：`fb_dcs=4`（`DCS_DEFAULT = 4`）将 `IOMFBBrightnessLevel` 的 0～500 尼特线性映射到面板 DBV `5..0x1a5e`（6750），在 `flip_commit()` 帧边界（每 2 帧至多一次）发送 DCS `0x51`，前 8 次变更后自动发 DCS `0x52` 回读核对。控制中心拉低再拉高亮度滑块时，面板依次写入并读回 `2788 -> 22 -> 4726`（`panel reads 2788, 0x0ae4 written last (same)`、`panel reads 22, 0x0016 written last (same)`、`panel reads 4726, 0x1276 written last (same)`），控制中心下拉 102.3 帧／秒、主屏翻页 103.7 帧／秒；`st3-r1` 不传 `fb_dcs` 启动参数，确认默认生效。


