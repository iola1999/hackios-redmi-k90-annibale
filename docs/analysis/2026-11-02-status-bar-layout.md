# 状态栏时间与电池的横向位置

2026-11-02，离线分析，没有操作设备，也没有构建。问题是 K90 上状态栏的时间和电池离屏幕角落近，但没有贴边：这个位置由什么决定，怎么调。

读的是本机 `23G90__iPhone18,3` 共享缓存里的 UIKitCore、UIKitServices、SpringBoard 和 SpringBoardHome，文中地址都是该缓存的未滑动地址。用 `hackios-xnu-kernel/tools/dsc/` 的缓存读取模块加一段临时的 ObjC 元数据读取脚本（未入库）列出类和方法、反汇编实现，再量截图像素核对。

## 1. 结论

1. 状态栏按 iOS 认定的「屏幕切口」形状选布局类。K90 面板自己的圆角和挖孔不参与计算，iOS 不知道它们。
2. 2026-11-02 之前 `cycle.py` 打的载荷不带 `fbwidth`／`fbheight`／`fbpitch`，画布是内核默认的 1125×2436（375×812 点，screen class 15）。iOS 认定的切口是 iPhone X 的刘海（左缘 83 点，宽 209 点，高 30 点，贴顶），状态栏用 `Split1125`。
3. `Split1125` 把时间放在刘海左侧那块 83 点宽区域的中间，中心距左缘 46.7 点；电池右缘距屏幕右缘约 15 点。没有切口的直角机型用 `LegacyPhone`，图标贴边。两者对照，就是用户看到的「靠角落，但没有贴边」。
4. iPhone 17 画布（`fbwidth=1206 fbheight=2622 fbpitch=460`，402×874 点，screen class 36）的切口是灵动岛，状态栏用 `DynamicSplit`：时间中心距左缘 73.7 点，电池中心在 327.2 点。在 1156 像素宽的面板上，时间中心从约 144 像素移到约 212 像素。
5. 2026-11-02 起 `cycle.py` 默认带上这三个参数，见第 6 节。

## 2. 布局类的选择

`+[_UIStatusBarVisualProvider_Phone visualProviderSubclassForScreen:visualProviderInfo:]`（`0x18a84056c`）读 `-[UIScreen _exclusionArea]`，按切口分三种：

- 没有切口：`_UIStatusBarVisualProvider_LegacyPhone`。
- 切口矩形 y ≤ 0（刘海贴顶）：`_UIStatusBarVisualProvider_Split`。再由 `+[_UIStatusBarVisualProvider_Split visualProviderSubclassForScreen:visualProviderInfo:]`（`0x18a844e04`）在 9 个固定布局类里挑：`Split1125`、`Split1080`、`Split1080_Wide`、`Split1170`、`Split1170_Wide`、`Split1242`、`Split828`、`Split1284`、`Split1284_Wide`。类的 `nativeDisplayWidth` 与屏幕 `_nativeDisplayBounds` 宽度、类的 `notchSize` 与切口宽高都相差不超过 0.0001 才算匹配。
- 切口 y > 0（灵动岛）：`_UIStatusBarVisualProvider_DynamicSplit`。参考宽度不超过 393 点时换成 `DynamicSplitMedium`（`0x18a7173ac`）。

SpringBoard 的状态栏是 SystemStatusUI.framework 的 `STUIStatusBar`，库里有同名的一套 `STUIStatusBarVisualProvider_*`（`Split1125`、`DynamicSplit`、`LegacyPhone` 等）。这一套的常量没有逐个读出，临时脚本解析不了这个库的类表；第 5 节的实测位置与按 UIKitCore 这一套算出的结果相符。

应用内的状态栏按 UIKitCore 这一套计算。这一点是从 UIKitCore 带着全套布局类推断的，没有在设备上抓应用的图层确认。

## 3. 切口矩形的来源

- `-[UIScreen _exclusionArea]`（`0x18916cbe8`）返回 `_displayInfoProvider.exclusionArea`。`_displayInfoProvider`（`0x18916ce58`）取 `_UIScreenInitialDisplayConfigurationLoader` 的 `initialDisplayContext`（`0x189240abc`）：FrontBoard 进程（SpringBoard）用 `+[UISDisplayContext defaultContext]`，应用用 `applicationInitializationContext.mainDisplayContext`。
- SpringBoard 的 `+[UISDisplayContext sb_embeddedDisplayDefaultContext]`（`0x2241e9454`）把 `exclusionArea` 设为 `+[UISDisplaySingleRectShape sb_thisDeviceDisplayShape]`（`0x2241dc5f8`，只算一次）的结果，也就是 `+[UISDisplaySingleRectShape sb_displayShapeForScreenType:]`（`0x2248b1d78`）按 `SBHScreenTypeForCurrentDevice()`（SpringBoardHome）查表。
- 屏幕类型由 MobileGestalt 的屏幕参数决定。`fbwidth`／`fbheight`／`fbpitch` 改变 MobileGestalt 选出的 screen class，切口随之改变。
- 表里的值以像素为单位，再按屏幕类型的原生倍率换成点。表项见第 7.1 节。

`defaultContext` 本身不带切口，SpringBoard 进程里 UIScreen 怎样拿到 `sb_embeddedDisplayDefaultContext` 设置的切口，这一段没有反汇编到。K90 两种画布各自对应哪个屏幕类型，是由实测位置推断的：375 点画布与表中第 3、4 类（默认值）的刘海吻合，402 点画布与第 25、26 类的灵动岛吻合。

## 4. 两种布局的位置公式

刘海布局（`_UIStatusBarVisualProvider_FixedSplit`）：

- 时间中心距左缘为 `leadingCenteringEdgeInset`（`0x18a84d264`）= round(切口左缘 × 0.5 + 屏幕圆角 × 0.15) + 类方法 `leadingCenteringOffset`。屏幕圆角取 `-[UIScreen _displayCornerRadius]`（经 `-[_UIStatusBarVisualProvider_Split cornerRadius]`，`0x18a8458a0`），权重只有 0.15。
- `Split1125` 的 `notchSize` 是 209×30 点，`leadingCenteringOffset` 是 −2/3 点。代入切口左缘 83 点、iPhone X 圆角 39 点：round(41.5 + 5.85) − 0.67 ≈ 46.7 点。
- 右侧以 `trailingCenteringEdgeInset`（`0x18a84d314`）为中心，它等于左侧值加 `trailingCenteringOffset`（`FixedSplit` 为 1 点）。这个中心按信号、Wi-Fi、电池三个图标加两个间距的总宽计算（`_edgeInsetsFromCenteringEdgeInset:trailing:`，`0x18a84d66c`）。只显示电池时，电池排在这组的最右端，右缘距屏幕右缘约 15 点。

灵动岛布局（`_UIStatusBarVisualProvider_DynamicSplit`，区域约束在 `setupInContainerView:`，`0x18a71783c`）：

- `edgeInsets` 为（0, 17, 0, 18），`cutoutEdgeInset` 为 8 点。
- 左区域从左缘 + 17 点到岛左缘 − 8 点，右区域从岛右缘 + 8 点到右缘 − 18 点，图标在各自区域内居中。
- 402 点画布的岛是 x=138.3、y=14、125×36.7 点。时间区域为 17～130.3 点，中心 73.7 点；电池区域为 271.3～384 点，中心 327.7 点。

## 5. 实测对照

面板宽 1156 像素。375 点画布每点 3.083 像素，402 点画布每点 2.876 像素。

| 画布 | 来源 | 时间 | 电池 |
|---|---|---|---|
| 1125×2436（375 点） | `kernel-12377-rate1-rt2/run/cmd-1.log` 的 `com.redwood.layers.StatusBar` 图层导出 | `STUIStatusBarStringView` 41×18，中心 x=47 点 | `STUIStatusBarBatteryView` 24×12，中心 x=348 点，右缘 360 点 |
| 1125×2436（375 点） | `kernel-12377-rate6-pt3/run/shot-00530.raw`（设置页） | 字形 99～188 像素，中心 46.5 点 | 右缘距屏幕右缘 14.3 点 |
| 1206×2622（402 点） | `hackios-xnu-kernel/out/ios26-resume/native-display-device/device-45.png`（2026-10-27） | 字形 154～270 像素，中心 212 像素，即 73.7 点 | 902～980 像素，中心 327.2 点 |

`kernel-*` 轮次目录在 `docs/progress/evidence/k90auto/` 下。表中三处都是 Git 忽略的本地目录。

## 6. 调整方式与当前选择

能改变状态栏位置的输入有三项。

1. 画布：改 `fbwidth`／`fbheight`／`fbpitch`，MobileGestalt 换 screen class，SpringBoard 换切口和布局类。当前采用这一项。
2. 布局常量：在注入库里替换 `STUIStatusBarVisualProvider_Split1125` 的 `+leadingCenteringOffset`／`+trailingCenteringOffset`，每加 1 点，时间右移约 3 像素。只改 SpringBoard 时应用内状态栏不变，应用进程也要注入同样的替换。
3. 切口形状：替换 `_exclusionArea` 或 `sb_displayShapeForScreenType:` 的返回值。同一个矩形还决定灵动岛（SystemAperture）的位置和尺寸，影响面最大，没有采用。

屏幕圆角只以 0.15 的权重进入刘海布局，不作为调整手段。

`tools/k90auto/cycle.py` 从 2026-11-02 起采用第 1 项，在固定参数和 `--boot-args` 之后追加 `fbwidth=1206 fbheight=2622 fbpitch=460`。同一个键出现两次时内核取第一个，所以某一轮仍可用 `--boot-args` 给出自己的画布参数。内核默认值（`MiniIOMobileFramebuffer.cpp` 的 `kFBDefaultWidth`／`kFBDefaultHeight`）保持 1125×2436，iOS 16.5 链路不受影响。

这项改动的影响和验证情况有以下几条。

- 本分析没有起轮。iPhone 17 画布在 2026-10-27 的 K90 上跑过软件合成（[运行记录](../progress/2026-10-27-ios26-k90.md) 第 22 节）和 GPU 160 MHz 档（第 36、38 节）。改动后的第一轮是另一个会话的 `kernel-12377-rate7-dc1`（2026-11-02 02:07），用当前 GPU 与 120 Hz 参数在新画布上运行，该会话报告控制中心下拉从约 106 帧/秒降到 87.9 帧/秒，完整读数以该会话的 11-02 记录为准。
- 每帧像素多 15.4%，GPU 合成和拷进面板的耗时会相应变化。2026-11-02 之后的轮次与之前的 120 Hz 读数比较时，要把画布算作一个变量。
- 同字号在面板上窄约 6.7%。顶部安全区为 62 点，底部 34 点。
- `cycle.py` 巡检用的屏幕比例坐标不需要改。两种画布的主屏图标列中心都在宽度的 0.15、0.38、0.62、0.85 附近；第 4 行中心在 375 点画布为高度的 0.699，在 402 点画布为 0.713，设置图标的点按位置 y=0.70 在两种画布上都落在图标内（402 点画布的图标范围是 0.677～0.749）。
- `fb_flip=2` 翻转的两块缓冲按面板布局分配，画面由合成后缩放写入，与画布尺寸无关（`MiniFramebufferFlip.inc` 文件头说明）。

### 6.1 画布分辨率的取舍

画布取 iPhone 17 真机的 1206×2622、460 ppi（402×874 点），与系统盘的 `iPhone18,3`、V57 身份一致。用户的要求是方案简单、可靠，几个备选按这一条比较如下。

- 与身份一致：MobileGestalt、SpringBoard 的切口表、UIKitServices 的安全区和状态栏布局都按精确像素宽度或机型编号查表。身份与画布不一致时会用到别的机型的布局，1125×2436 画布的状态栏就是这样。
- 缩放到面板：1206 缩到 1156 是 0.9585 倍，两边宽高比相差 0.13%。iPhone 12 mini、13 mini 的面板是 1080×2340，系统按 1125×2436 绘制再缩到 0.96 倍。第 7.1 节表中第 9、10 类与第 15、16 类的切口按 1125 像素宽给出，原生倍率再乘 1.0417（= 1125/1080），按尺寸推断是这两款机型。
- 与 K90 帧缓冲一比一（1156×2510）：没有对应的 iPhone。MobileGestalt 选不出 screen class（2026-10-27 密度给错时返回 none），切口、状态栏和安全区要逐项伪造，不采用。
- 换其他 iPhone 分辨率：例如 1179×2556（393 点）像素比 1206×2622 少 4.6%，但与 V57 身份的 `ArtworkDeviceSubType=2622` 不一致，属于第一条说的不一致情形，不采用。

### 6.2 K90 物理面板分辨率（待核实）

[可行性记录](k90-annibale-feasibility.md)的硬件表引社区设备树：物理面板 1200×2608、480 dpi，1156×2510 是 Android 的渲染分辨率。这一点没有核实。

显示控制器的读数取自 `kernel-12377-rate6-pt3/run/s001.log` 的 `MiniIOMobileFramebuffer: flip:` 行（`fb_flip` 诊断）。

- 两条源管道 `vig0`、`vig1` 的输入尺寸都是 `09ce0242`（578×2510），输出尺寸与输入相同，管道内没有缩放。
- 两个混合器 `lm0`、`lm1` 各输出 578×2510，合计 1156×2510 送往 DSI。
- `intf1` 在 200 毫秒内走了 24 帧（3354 → 3378），即 120 Hz。

如果物理面板确实是 1200×2608，放大发生在面板的驱动芯片里。iOS 画面现在先由内核从 1206×2622 缩到 1156×2510，再由面板放大到 1200×2608，经过两次缩放。1206×2622 与 1200×2608 只差约 0.5%，按面板原生分辨率输出能省掉这两次缩放，但要改面板的工作模式（DSI 命令）和显示控制器时序，属于内核显示驱动的工作，与画布参数无关。第一步是核实面板分辨率，例如查分区备份里 dtbo 的面板节点。

## 7. 静态数据

### 7.1 `sb_displayShapeForScreenType:` 的切口表

单位为像素，函数在 `0x2248b1d78`，跳转表在 `0x224391224`，覆盖屏幕类型 3～30，范围外的类型走另一条分支。矩形按（x, y, 宽, 高）除以原生倍率后交给 `-[UISDisplaySingleRectShape initWithRect:]`。y=0 的是刘海，y>0 的是灵动岛。

| 屏幕类型 | x | y | 宽 | 高 | 备注 |
|---|---:|---:|---:|---:|---|
| 3、4（默认值） | 249 | 0 | 627 | 90 | 按 @3x 为 83、0、209、30 点，iPhone X 刘海，与 `Split1125` 的 `notchSize` 相同 |
| 5、6 | 307 | 0 | 628 | 90 | |
| 7、8 | 187 | 0 | 454 | 64 | |
| 9、10 | 223.5 | 0 | 678 | 103 | |
| 11、12 | 270 | 0 | 630 | 96 | |
| 13、14 | 328 | 0 | 628 | 96 | |
| 15、16 | 301.5 | 0 | 522 | 112 | |
| 17、18 | 343 | 0 | 484 | 101 | |
| 19、20 | 400 | 0 | 484 | 101 | |
| 21、22 | 402 | 34 | 375 | 110 | 393 点宽 |
| 23、24 | 457 | 34 | 376 | 110 | 430 点宽 |
| 25、26 | 415 | 42 | 375 | 110 | 402 点宽，K90 的 iPhone 17 画布 |
| 27、28 | 472 | 42 | 376 | 110 | 440 点宽 |
| 29、30 | 442 | 60 | 376 | 110 | 420 点宽 |

「点宽」一列按 @3x 由 x × 2 + 宽 推算，只用于对应机型。原生倍率取 `_SBHNativeScaleForScreenType`，第 9、10、15、16 类再乘 1.0417，表中没有展开。

### 7.2 UIKitCore 常量

| 符号 | 地址 | 值 |
|---|---|---|
| `-[DynamicSplit edgeInsets]` | `0x18a7175d8` | （0, 17, 0, 18） |
| `-[DynamicSplit cutoutEdgeInset]` | `0x18a717600` | 8 |
| `+[DynamicSplit height]` | `0x18a717450` | 53.667 |
| `DynamicSplitMedium` 宽度门限 | `0x18ae5ff18` | 393 |
| `-[FixedSplit leadingCenteringEdgeInset]` 圆角权重 | `0x18ae56048` | 0.15 |
| `+[FixedSplit trailingCenteringOffset]` | `0x18a84d354` | 1 |
| `+[Split1125 notchSize]` | `0x18a850ea4` | 209×30 |
| `+[Split1125 leadingCenteringOffset]` | `0x18a850ed0` | −0.667 |
| `FixedSplit` 匹配容差 | `0x18ae56400` | 0.0001 |

表中类名省略了前缀 `_UIStatusBarVisualProvider_`。
