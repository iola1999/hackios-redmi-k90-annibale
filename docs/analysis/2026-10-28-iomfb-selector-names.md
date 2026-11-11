# IOMobileFramebuffer 的 selector 名字与 iOS 26.6 完整表

本文给出 IOMobileFramebuffer user client 的 selector 编号、名字和调用形状，供 `hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp` 的 selector enum 与各分支参考。项目 enum 现有 20 个名字，本文为其余 12 个在用的号定名，并核对 72、73、74：12 个都拿到调用形状，其中 11 个有 Apple 的 `kern_*` 符号名且各有两个以上独立公开来源，88 只有调用点与形状。72、73、74 的名字与项目 enum 一致，74 的实现有一处缺陷（第 5 节）。

后续接口核查与验收见[图形与显示待办](../backlog/graphics.md)。

公开检索之外，本文在项目自带的 iOS 26.6 共享缓存（`hackios-xnu-kernel/ios26/23G90__iPhone18,3/dyld_shared_cache_arm64e*`，`IOMobileFramebuffer` 镜像基址 `0x229493000`）上反汇编，从导出 wrapper、对象分派槽、`kern_*` 实现一直追到 `IOConnectCall*` 的 selector 立即数，得到第 4 节的完整表。

## 1. 主表

「独立来源」按不同项目或不同作者计数，同一仓库的多个文件算一个。本地列是在 iOS 26.6 共享缓存上反汇编确认的结果。

| sel | 名字（Apple 符号） | 公开来源 | 独立来源数 | 本地 26.6 复核 |
|---|---|---|---|---|
| 15 | `kern_SetDebugFlags` | S1 S2 S6 | 3 | slot `0xa80`，2 scalar in / 1 scalar out |
| 17 | `kern_SetGammaTable` | S1 S2 S6 | 3 | slot `0xa90`，struct in `0xC0C` = 3084 |
| 18 | `IOMobileFramebufferIsMainDisplay` | S1 S2 S6 S8 | 4 | 导出函数内直接调用，1 scalar out |
| 22 | `kern_SetDisplayDevice` | S1 S2 S6 | 3 | slot `0xaa8`，1 scalar in |
| 27 | `kern_GetGammaTable` | S1 S2 S6 | 3 | slot `0xaa0`，struct out `0xC0C` = 3084 |
| 33 | `kern_EnableDisableVideoPowerSavings` | S1 S2 | 2 | slot `0xb38`，1 scalar in |
| 50 | `kern_SetBrightnessCorrection` | S1 S2 | 2 | slot `0xa70`，2 scalar in，第二个是 display type，取自 `fb+0x888` |
| 68 | `kern_SetParameter` | S1 S2 | 2 | slot `0xb98`，1 scalar in 加 `8 * count` struct in |
| 78 | `kern_SetBlock`，内核 `IOMobileFramebufferUserClient::s_set_block` | S1 S2 S3 S5 | 4 | slot `0xb88`，scalar in = extra+2，struct in 按 4096 分块 |
| 84 | `kern_SetContrast` | S1 S2 S8 | 3 | slot `0xa98`，struct in 4 字节即 float |
| 86 | `IOMFBGainEncoderFinishEncoding` | S1 S2 S5 | 3 | 导出函数内直接调用，struct in `0x48` = 72 / 1 scalar out |
| 88 | 查不到 Apple 符号名 | S1 给调用点，S8 给自拟名 | 0 个命名来源 | `IOMobileFramebufferOpenByName` 内联，1 scalar in |

88 的调用点在 `IOMobileFramebufferOpenByName` 内部（函数 `0x2294bd5a4`，call site `0x2294bdaec`），形式是 `IOConnectCallScalarMethod(conn, 0x58, &displayType, 1, 0, 0)`，只在 open 成功且 `s_thread_notified == 1` 时发一次，传刚打开那个 display 的 display type。同一个 u32 也存在 `fb+0x888`，即 selector 50 的第二个 scalar。S8 把它叫 `SelectDisplay`，这是作者自拟的标签：iOS 26.5 SDK 的 190 个导出里没有 `Select*` 符号，ipsw-diffs 的 framework 符号增删记录里也从未出现。

内核侧有一条推断线索：`Allenwdk/UniXNU-uke` 的 `docs/PROGRESS.md` 记录真机日志 `IOMobileFramebufferUserClient::s_map_display_type ... UserClient display type is 0`，行为是把 userland 传入的 scalar 写进 user client 的 `+0x10c` 再返回 0，时机在 client 打开之后、selector 8／15／8 之前。语义与形状都与 88 吻合，但没有公开来源把 `s_map_display_type` 和 88 写在一起，写进代码注释时要标注为推断。

## 2. 来源清单与派生关系

- S1 `EthanArbuckle/iPhone17-1_18.2_22C152_Restore` 的 `System/Library/PrivateFrameworks/IOMobileFramebuffer.framework/IOMobileFramebuffer.m`，iOS 18.2 / iPhone17,1 / 22C152 的反编译全文。`kern_*` 函数里 selector 是字面常量，`IOMobileFramebufferOpen` 里能看到函数指针表填充（形如 `*(void *)(*a4 + 2712) = kern_SetBlock;`）。15、17、22、27、33、50、68、72、73、74、78、84、86、88 的常量已逐个函数核对。
- S2 `dipa-studio/ios-sweet` 的 `NOTES.md`，来自 iPhone X / iOS 16.7.16 / 20H392 共享缓存的 `ipsw dyld disass --image IOMobileFramebuffer`。有一行完整表 `3 _kern_GetLayerDefaultSurface[ScalarMethod_stub]; 4 _kern_SwapBegin[...] ... 86 _IOMFBGainEncoderFinishEncoding[Method_stub]; UNKNOWN {}`，在 86 处结束。通知 ABI 段落写明 `sel 72 scalars [NotifyCallbackFuncs[type], fb, type, 0]` 与 type 取值（0 HotPlug、1 Power、3 FrameInfo、4 CRC、5 Vsync）。
- S3 Google Project Zero，Ian Beer，《The curious tale of a fake Carrier.app》（CVE-2021-30983）：「The exploit only calls 3 different external method selectors on the AppleCLCD2 user client: 68, 78 and 79. The one with the largest and most interesting-looking input is 78, which corresponds to ... `IOReturn IOMobileFramebufferUserClient::s_set_block(...)`」。这是 78 的内核符号名唯一的直接来源。
- S4 `jsherman212` 的 CVE-2021-30656 文章：L153～L156 给出 external method 74 为 `IOExternalMethodDispatch <s_supported_frame_info, 1, 0, 1, 0x40>`；L143 与 L146 给出 external method 0 = `s_rotate_surface`（3 scalar in），L174 给出 `s_swap_submit` 行 `<0, 0xFFFFFFFF, 0, 0>`。这是 iOS 14 时代的表，74 当时是 1 个 scalar out。
- S5 `ma6x9x/Lum1na` 的 `LabIntelOffsets.m` L235 与 L245，直接读 kernelcache 的 `sMethods`。
  - iOS 26.5（23F77/T8101）：表在 `0xFFFFFFF007EF0C90`，stride `0x18`，「88 rows sel0..0x57」；rows 59-64 与 70-71 是 fn=0 的退役行；row5 的 sin 是 `0x588`，row68 的 sin 是 `0x100`；special sels `0x44`／`0x4e`／`0x4f`／`0x55`（68／78／79／85）会先把整行拷到栈上。
  - iOS 27.0（24A435/T8150）：表在 `0xFFFFFE000832FD70`，stride `0x28`，「93 rows sel0..0x5c」，新增 `+0x20` 的 entitlement 列：row23 `com.apple.private.iomfb.set-block`、row83 `com.apple.private.allow-explicit-graphics-priority`、row86 `com.apple.private.gain-map-access`。
  - 26.5 到 27.0：row5 的 sin 从 `0x588` 变为 `0x6e0`，row68 的 sin 从 `0x100` 变为 `0xffffffff`，rows 78 与 79 的 ci 与 sin 从 0 变为 `0xffffffff`（变长）。这份资料只有行号、大小与 entitlement，没有符号名。
- S6 `samhenrigold/qemu-ios` 的 `docs/research/gap-display-stack-kernel.md` L81，古早 iOS（iPod touch 2G 与 iPhone 3GS 时代）的表：`0xf SetDebugFlags`、`0x11 SetGammaTable(struct)`、`0x12 IsMainDisplay`、`0x16 SetDisplayDevice`、`0x1b GetGammaTable (0xc00 out)`、`0x20 VideoPowerSavings`；`1 SwapSurface`、`2 WaitSurface`、`9 VSync notify on/off`、`0x15 HotPlug notify` 是后来退役的旧方法，对应 S5 的 fn=0 行。
- S8 `orhunnx/beyond2lte-ios` 的 `xnu-overlay/iokit/Kernel/arm/B2LFramebuffer.cpp`，作者称对 iOS 26.6.2 共享缓存做过逆向并给了地址。独立作者，内容未从 ios-sweet 派生。

以下派生不计入独立来源：`lechaukha12/xnu-xzs` 的 `XZSFramebuffer.cpp` 用 `kSweetFB*` 前缀，selector 列表来自 ios-sweet；`Allenwdk/UniXNU-uke` 与 `GFander/UniXNU-kebab` 在文档里署名 ios-sweet；`Floppikrob/ios-galaxy-s8`、`turgayasuk-sketch/ios-topaz`、`edi194/ios-fajita`、`nftuoa/ios-sweet-sagit` 逐字复制同一份 NOTES.md；本项目 `hackios-xnu-kernel` 及其全部 fork 共享同一份 20 个名字的 enum，算一个来源。

另有四条来源没有重新抓取原文核对，引用时要带这个限定：

- `WebKit/WebKit` 的沙盒 profile `Source/WebKit/GPUProcess/mac/com.apple.WebKit.GPUProcess.sb.in` 给 macOS GPU process 授权 `(iokit-method-number 82 88)`，只说明 88 在 macOS 上存在，不给名字。
- `Snapintosh/tools/replay-panel-mode.py` 称 macOS 27 的 `s_set_digital_out_mode` 是 native selector 23。
- `blacktop/symbolicator` 与 ipsw-diffs 的内核 `s_*` 和 framework `_kern_*` 符号词表。
- `Lakr233/vphone-cli` 独立确认 `_kern_SwapEnd` 是 external method 5。

## 3. 本地反汇编方法

共享缓存可用 `hackios-xnu-kernel/tools/dsc/` 读取和反汇编。第 4 节的表依赖下面几步定位：

- 共享缓存：dyld4 拆分缓存，mmap 全部 subcache；主缓存头 magic 是 `dyld_v1`，`mappingOffset` 与 `mappingCount` 在 `0x10`，images 数组在 `0x1c0`，每条 32 字节，形式为 `(address, _, _, pathOffset, _)`。
- 镜像内：`__LINKEDIT` 的 bias 按 `vmaddr - fileoff` 计算，FUNCTION_STARTS 取函数列表，LC_DYLD_EXPORTS_TRIE（`0x80000033`）遍历导出表，再用 capstone 逐函数分析。这个镜像有 779 个函数、202 个导出。
- stub island：这个镜像不经 `__auth_stubs` 调 IOKit，`bl` 的目标是 dyld 的 16 字节 stub island，形式为 `adrp x16,#page; add x16,x16,#off; br x16; brk #1`。解出目标地址再查目标镜像的导出名，三个入口是 `0x22c859ac0` 的 `_IOConnectCallMethod`、`0x22c859ad0` 的 `_IOConnectCallScalarMethod`、`0x22c859ae0` 的 `_IOConnectCallStructMethod`。
- wrapper 到 selector：wrapper 里 `ldr xN, [x0, #slot]` 加 `braaz xN` 取 slot；slot 的值在 `_IOMobileFramebufferOpen`（`0x2294979e0`）与 `_IOMobileFramebufferOpenByName`（`0x2294bd5a4`）里由 `adrp`／`add`／`paciza`／`str x16,[x0,#slot]` 装入。有一批先写栈数组，再用 `str xN,[x0,xM]` 寄存器偏移批量装入，需要跟着 `mov wN,#0xa00` 这类立即数还原。

两个陷阱：

- `__auth_stubs` 的 GOT 槽是 chained fixup 编码，原始值形如 `0x80140000XXXXXXXX`，目标地址是 `0x180000000 + (raw & 0xFFFFFFFFF)`。
- 按「stub 调用点附近的小 w1 立即数」筛 selector 会大量误报，memcpy 与 printf 的长度参数也是小立即数；必须先确认调用目标是 `IOConnectCall*`。

名字都来自符号（S1 与 S2 的 `kern_*`、S3 与 S4 的内核 `s_*`）。selector 编号跨版本会变，调用形状只用来确认版本没有变化，不作命名依据。

## 4. iOS 26.6 完整 selector 表

按 selector 排序，名字取本地导出符号，形状取反汇编里的常量。可以直接作为 26.6 的实现基线。

```
 3 GetLayerDefaultSurface      4 SwapBegin                5 SwapEnd(struct 0x588)
 6 SwapWait                    7 GetID                    8 GetDisplaySize
10 SetTVOutMode               11 SetWSSInfo              12 RequestPowerChange
13 EnableStatistics           14 SetFlags                 15 SetDebugFlags(2 in/1 out)
16 SetTVOutSignalType         17 SetGammaTable(0xC0C in) 18 IsMainDisplay
19 SetWhiteOnBlackMode        20 SwapSignal              22 SetDisplayDevice(1 in)
23 SetDigitalOutMode          24 GetHDCPDownstreamState  25 GetDigitalOutState
27 GetGammaTable(0xC0C out)   28 GetDotPitch             29 GetDisplayArea
30 EnableDisableDithering     31 SetUnderrunColor        33 EnableDisableVideoPowerSavings(1 in)
34 SetVideoDACGain            35 SetLine21Data           41 EnableMirroring
42 GetMirroringCapability     43 SetRenderingAngle       44 SetMirrorContentRegion
47 HDCPSendRequest            48 HDCPGetReply            49 SurfaceIsReplaceable
50 SetBrightnessCorrection(2 in) 51 SetColorRemapMode    52 SwapCancel
53 SetCanvasSize              54 GetMatrix               55 SetMatrix
57 GetColorRemapMode          66 SPLCSetBrightness       67 SPLCGetBrightness
68 SetParameter(1 in + 8*n struct) 69 SwapSetColorMatrix 72 Enable/DisableNotifications(4 in)
73 ChangeFrameInfo([3,index]) 74 SupportedFrameInfo(1 in/2 out/64 struct) 75 FactoryPortal
77 GetCurrentAbsoluteTime     78 SetBlock                79 GetBlock
80 GetLinkQuality             81 SwapCancelAll           82 GetProtectionOptions
83 CopyLayerDisplayedSurface  84 SetContrast(float 4B)   85 GetBufBlock
86 GainEncoderFinishEncoding(72 in/1 out) 87 AnnounceNextSwapTimestamp
88 (OpenByName 内联, display type) 89 SetClamshellState 90 GetDotPitchFloat
91 SwapGetCurrent             92 SwapCancelAllGetCurrent
```

项目 enum 现有的 20 个名字（3、4、5、6、7、8、12、20、25、28、29、52、57、72、73、74、77、79、81、82）在本地 26.6 上全部对得上。83 的 `CopyLayerDisplayedSurface` 与 iOS 14 exploit 文章里的 `s_displayed_fb_surface` 是同一个操作。

另外两个 user client 的编号与 IOMFB 无关，不要混用：`kern_DisplayWall{Enumerate,ValidateConfig,Enable,Disable,Status}` 内部的 3～7 属于 AppleDisplayManager（本地 `_AppleDisplayManagerOpen` 在 `0x2294b79e4`）；`IOMobileFramebufferCalibrationToolboxCommand` 里的 2～5 走 AppleNVMeEAN 连接（本地有字符串 `AppleNVMeEAN` 与 `UserCalibration_EraseEAN`）。

## 5. 72、73、74 与项目 enum 的对照

72 `kFBMethodNotifications`：26.6 上 enable 与 disable 是两个实现。enable 在 `0x2294bb218`、slot `0xa28`，disable 在 `0x2294bb2a0`、slot `0xa30`，都是 `IOConnectCallScalarMethod(conn, 0x48, scalars, 4, 0, 0)`。

- enable 的 4 个 scalar 是 `[NotifyCallbackFuncs[type], fb, type, 0]`，回调函数指针按 type 从 `__AUTH_CONST,__const + 0xe20` 的表里取；disable 是 `[0, 0, type, 0]`。
- 公开名字是 `kern_EnableNotifications` 与 `kern_DisableNotifications`（S1、S2）。导出 wrapper `IOMobileFramebuffer{Enable,Disable}{VSync,Power,HotPlugDetect,NeedSwap,CRC}Notifications` 中，五个 Enable 共用 slot `0xa28`，五个 Disable 共用 slot `0xa30`。
- 项目实现读 `in[0]` 作 callback、`in[2]` 作 type，与 26.6 一致。正常路径会注册 Vsync（type 5）。

73 `kFBMethodChangeFrameInfo`：本地实现在 `0x2294bb314`、slot `0xba8`，形式为 `IOConnectCallScalarMethod(conn, 0x49, scalars, 2, 0, 0)`，scalars 是 `[3, index]`，3 是 framework 硬编码的常量。导出 wrapper `IOMobileFramebufferChangeFrameInfo(fb, bool)` 先调 74 取描述符，把选中的 index 存到 `fb+0x828`，再调 73；74 返回 count 0 时不会调 73。项目实现直接返回 `kIOReturnSuccess`，够用。

74 `kFBMethodSupportedFrameInfo`：内核符号是 `IOMobileFramebufferUserClient::s_supported_frame_info`（S4）。本地实现在 `0x2294bb384`、slot `0xbb0`，形式为 `IOConnectCallMethod(conn, 0x4a, &type, 1, NULL, 0, output, &outputCnt, outputStruct, &structSize)`，`outputCnt` 初值 2、`structSize` 初值 64；返回后 framework 直接取 `*a3 = output[0]`、`*a5 = output[1]`，不检查实际写回几个。

- 项目的 `kFBMethodSupportedFrameInfo` 分支只写 `out[0] = 0` 并把 `scalarOutputCount` 设为 1，再清零 struct。第二个槽位保持调用方栈上的初值 `0xAAAAAAAAAAAAAAAA`，调用方拿到 `0xAAAAAAAA` 作为 selected index。
- count 为 0 时正常路径不使用这个 index。enum 注释 `/* in: type; out: how many, and their tags: none */` 中的「their tags」在公开资料里没有对应，26.6 的实际输出是 2 个 scalar（count 与 selected index）加 64 字节 struct。
- S4 的 iOS 14 表行是 1 scalar in、1 scalar out、`0x40` struct out，18.2 起是 2 scalar out，输出个数不能写死。

## 6. 78 的分块协议与实际调用

框架侧的分块协议有公开定义，payload 内容没有。S1 给出的 `kern_SetBlock(a1=fb, a2=blockType, a3=data, a4=dataSize, a5=extraU32Array, a6=extraCount)` 算法：

- scalar 数组长度为 `a6 + 2`，先全部填 `0xAA`；`scalars[0] = blockType`，`scalars[1] = 0` 作分块偏移，`scalars[2 .. a6+1]` 是 a5 指向的 a6 个 u32，各自零扩展为 u64。
- 循环 `IOConnectCallMethod(conn, 0x4E, scalars, a6+2, data + offset, min(4096, dataSize - offset), 0,0,0,0)`，每次返回后 `scalars[1] += 4096`，直到 `offset >= dataSize` 或返回非 0。没有输出参数。
- 本地 26.6 的 `0x2294bcc3c` 逐条核对一致（`mov w1,#0x4e`，`mov x3,x21` 取 extra+2，`csel x5, x10, x24, hi` 取 min(剩余, 0x1000)，回写为 `ldr x8,[x22,#8]; add x8,x8,#0x1000; str x8,[x22,#8]`）。S5 记录 27.0 上 rows 78 与 79 的输入个数与 struct 大小都是变长，与分块协议一致。

导出 wrapper `IOMobileFramebufferSetBlock` 是纯转发（`ldr x6,[x0,#0xb88]; braaz x6`），公开签名就是上述 6 个参数。`IOMobileFramebufferSwapSetToneMapConfig` 也用 slot `0xb88`，固定传 `blockType = 0x6b`、`dataSize = 0x4c`（76 字节）、`extraCount = 1`。

iOS 26 启动日志中，backboardd 每次 swap 在 SwapBegin(4) 与 SwapEnd(5) 之间调 78 三次，scalar 与 struct 长度为 `[0x32 0x0 0x1 0x4]` 配 64 字节、`[0x32 0x0 0x1 0x5]` 配 64 字节、`[0x33 0x0 0x1 0xc]` 配 656 字节。

- 按协议解读：blockType 为 `0x32`（50）两次、`0x33`（51）一次；chunk offset 都是 0，单次传完；extra u32 分别是 `{1, 4}`、`{1, 5}`、`{1, 0xc}`。
- 656（`0x290`）字节的结构与 tone-map 的 76 字节、74 的 64 字节都不同；三次调用的 blockType 为 `0x32`、`0x33`，没有走 tone-map 的 `0x6b`。

内核侧的准入检查有公开符号 `isSetBlockEnumAllowed` 与 `detectSetBlockClientType`，配 entitlement `com.apple.private.iomfb.set-block`，backboardd 持有它。S5 把这个 entitlement 记在 27.0 的 row23，与 23 是 SetDigitalOutMode 冲突，按语义它更可能属于 row78（第 8 节）。

项目 enum 里没有 78，这三次调用落到默认分支：输出清零、返回 `kIOReturnSuccess`，`selector 78 not implemented` 由 `gFBLogged` 每次启动只打印一次，日志里看不出它每次 swap 都发生。框架侧只在返回非 0 时中断分块循环。

## 7. 查不到的项

- 88 的 Apple 符号名。公开资料只有「`IOMobileFramebufferOpenByName` 内联发出 1 scalar 调用，传 display type」这一事实。
- 78 的 payload 结构，包括 block type `0x32` 与 `0x33` 的含义、64 与 656 字节的字段布局。S1 与 S2 只给框架侧算法，S3 只贴了内核 handler 开头几行，S5 只给行属性。
- 73 的第一个 scalar 为什么恒为 3。S1 与 S2 都显示是 framework 硬编码常量，没有来源解释含义。
- 91 与 92 的公开名字。本地确认 26.6 上 91 是 `IOMobileFramebufferSwapGetCurrent`（slot `0xa00`）、92 是 `IOMobileFramebufferSwapCancelAllGetCurrent`（slot `0xa08`）；S5 记录 27.0 的表有 93 行（sel 0 到 92），与之吻合，但公开资料没有把这两个编号和名字写在一起。

## 8. 冲突与未解释项

- selector 23 的归属。S2 给 `_kern_SetDigitalOutMode`，Snapintosh 称 macOS 27 的 `s_set_digital_out_mode` 是 native selector 23；S5 说 27.0 的 row23 挂 `com.apple.private.iomfb.set-block`。
  - 本地 26.6 支持前者：`_IOMobileFramebufferSetDigitalOutMode`（`0x2294b8afc`）取 slot `0xab0`，`_IOMobileFramebufferOpen` 在 `0x2294982a8` 把 `0x2294bc2c0` 装进 slot `0xab0`，而 `0x2294bc2c0` 调 `IOConnectCallScalarMethod(conn, 0x17, ...)`，即 23。
  - S5 的 row83（`allow-explicit-graphics-priority`，与 83 是 `s_displayed_fb_surface` 吻合）和 row86（`gain-map-access`，与 86 是 GainEncoderFinishEncoding 吻合）都对得上，只有 row23 对不上。S5 这一行可能抄错或串列，没有判定的依据。
- 表长度。S5 说 iOS 26.5 是「88 rows sel0..0x57」（最大 87），而 S1 的 iOS 18.2 framework 已在用 87～90，本地 26.6 还有 91 与 92，两者不能同时成立，S5 的 26.5 行数偏少。
- row68 的 struct 大小。S5 说 26.5 上 `checkStructureInputSize` 是 `0x100`（256），27.0 改为 `0xffffffff`；S1 与本地都显示 framework 按 `8 * count` 传，日志里是 8 字节。XNU 的 `checkStructureInputSize` 是精确比较，8 字节过不了 256 的检查，这一条没有解释。
- 版本相关的大小不能写死：selector 5 的 swap record 依次为 `0x8c`（古早 iOS）、`0x46c`（16.7）、1288（17）、`0x588`（26.5 与 26.6）、`0x6e0`（27.0），本地 26.6 的 `_IOMobileFramebufferOpen` 初始化路径确有 `mov w1, #0x588` 配 `__bzero`；gamma 表在 26.6 上是 `0xC0C`（3084），与 S1 的 18.2 相同，与 S6 古早表的「`0xc00` out」不同。

## 9. 未实现的改动

selector 契约补齐与验收统一记录在[图形与显示待办](../backlog/graphics.md)。

本次记录的一次 iOS 26 启动顺序为 `88 57 18 15 22 8 29 33 79(2056) 79(3164) 74(64) 25 12 79(44) 6 27(3084) 17(3084) 84 50 4 78(656) 78(64) 78(64) 68 5 3`，其中 88、18、15、22、33、27、17、84、50、78、68 未列在本次核查的 enum 中。17 与 27 的 3084、5 的 `0x588` 随 build 变化。

调试打印有两个机制：启动参数 `fbtrace=N` 让每个 selector 的前 N 次调用（默认 3）带进程名打印；`not implemented` 一行由 `gFBLogged` 每次启动只打印一次。三个驱动的日志格式不同：`MiniIOMobileFramebuffer` 与 `MiniIOSurface` 的 selector 是十进制，`MiniAppleKeyStore` 是十六进制。
