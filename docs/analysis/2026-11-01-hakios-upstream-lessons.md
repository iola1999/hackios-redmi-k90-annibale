# hakios 上游 10-27～11-01 的可借用做法

核对日期 2026-11-01。用户决定不合并上游代码、不跟进上游更新，只从中学习问题的解法和工作流。本文记录逐条核对后的结果：哪些能用在 K90 上、我们的现状、下一步与判据。UniXNU 系列的对照见 [10-29 调研](2026-10-29-upstream-survey.md)，本文不重复。

## 1. 结论

- 可以直接借用的有两组，都落在与上游同源的文件里，改动范围小：120 Hz 链路上我们缺的几处（§3），以及面板缩放在动画中改用最近邻（§4）。
- ir3 在 spill 时关掉 preamble 重编（§5）需要先量，我们没有记录过 CoreAnimation 着色器的 spill 情况。
- 按 pass 记 GPU 时间、用无障碍开关做对照、在独立探针内逐项切换等做法列在 §6、§7。
- `hakios-metal` 本身是面向 A6XX 与 iOS 16.5 的新驱动，按用户决定不跟进。它处理的 GMEM 选择、寄存器去重、丢弃不支持的工作等问题，我们的 gallium 路径已有对应，见 §8。
- 11-01 已实现 §3、§4、§5 与 §7 的无障碍开关，全部默认关闭，内核为 `12377-rate1`。真机轮次与判据见[验证方案](../plan/2026-11-01-rate-scaling-ir3-rounds.md)。

## 2. 核对范围

| 仓库 | 固定版本 | 说明 |
|---|---|---|
| `oosexgang/hakios-xnu-kernel`（旧名 `hackios-xnu-kernel`，旧地址自动跳转） | `main` = `a48d2b2`（2026-11-01） | 10-27 拆仓库时历史被重写，与我们的内核子模块没有共同祖先，`main` 上 766 笔提交；用子模块的 `upstream` 远端 fetch 后只读 |
| `oosexgang/hakios-metal` | `main` = `a097abd`（2026-10-31），195 笔 | C++ 驱动，直接生成 PM4 命令流，Mesa 只用于 NIR→ir3；目标 Adreno 7c+ Gen 3（芯片号 `0x06030500`，A6XX）；插件 `HakiosMetal.m` 面向 iOS 16.5 |
| `oosexgang/hackios-web` | 浅克隆最近 50 笔 | 新版指南；`content/guide/en/metal.md` 停在 10-28 的状态（着色器标为 not yet），比 `hakios-metal` README 旧 |
| `oosexgang/hackios-xnu-userland` | — | GitHub 显示大小为 0，用户态已并入内核仓库 |
| `oosexgang/hakios-uefi` | 未读 | U-Boot 路线，与本项目无关 |

只读副本放在忽略目录 `docs/analysis/local/upstream-2026-11-01/`，没有执行其中的脚本或构建。

公开内核仓库里的 AIR 前端（`tools/mesa/air/`）最后一次实质修改在 10-20，`air_to_nir.c` 为 2220 行，我们的是 3562 行。`hakios-metal` README 提到的前端修复（纹理写入按值定类型、null texture 槽位、function constant 的 supplied 标记等）没有公开，前端这块没有代码可参考，它的描述只能作为测试用例的线索。

## 3. 120 Hz：上游补齐的环节

`bo53` 读 INTF1 帧计数器得到面板约 125 Hz，桌面帧流仍是 60 帧／秒。[120 Hz 方案](../plan/2026-10-29-120hz-refresh-interval.md)已写但没有实现，`MiniIOMobileFramebuffer.cpp` 里没有 `IOMFBDisplayRefresh`。上游 10-30～10-31 在 iOS 16.5 上让同一条链路生效，按顺序是：

| 环节 | 上游做法 | 提交 |
|---|---|---|
| 刷新间隔属性 | 在 `publishModes()` 里 `setProperty("IOMFBDisplayRefresh", …)`。四个键里 `displayMinRefreshInterval`、`displayMaxRefreshInterval`、`displayRefreshStep` 以 2^-32 秒为单位（32.32 定点，120 Hz 为 `2^32/120`），只有 `displayRefreshStepMachTime` 用 mach 时钟 tick。按 tick 填时 CoreAnimation 报出 26844 Hz（`2^32/160000`）。没有覆盖 slot 301 | `b6c1f82`、`0dedaec` |
| 报给 CoreAnimation 的速率与面板分开 | boot-arg `fb_ca_hz=N`。只报 120 时 CoreAnimation 仍按 60 出帧，下面两行补上后才变 | `f6ebf31` |
| 应用的 Info.plist | 构建时给 SpringBoard、`/Applications`、`/System/Library/CoreServices` 下每个应用加 `CADisableMinimumFrameDurationOnPhone = YES`，缺这个键时 CoreAnimation 把每个进程限在 60。plist 写成新文件替换硬链接，原文件不动 | `c7b5f9a`（`mkhighrate.py`） |
| UIKit 的 display link | `UIViewInProcessAnimationManager`（应用进程内的动画，包括翻页回弹）的 display link 请求 20..30，翻页停下后约 0.7 秒按 30 帧／秒出帧。SpringBoard 里给为它创建的 display link 打关联对象标记，丢掉它请求的速率；其它 display link 保留原请求（时钟的 10 与 60、动效的 32）。右滑 78→115 帧／秒，超过 16.7 ms 的帧 17%→1% | `7caa457` |
| CoreAnimation 开关也给 SpringBoard | `caenv=` 原来只给渲染服务器，动画进程同样读这些开关 | `a5620ff` |
| 读回 CoreAnimation 看到的速率 | `fps_info` 打印 `CADisplay` 的模式、`UIScreen.maximumFramesPerSecond` 与 MobileGestalt，先判属性是否生效，再看帧间隔 | `cd72b54` |

iOS 26 侧的静态核对（`hackios-xnu-kernel/tools/dsc/dsc.py`，23G90）：QuartzCore 里有 `IOMFBDisplayRefresh`、`displayMinRefreshInterval`、`displayRefreshStepMachTime`、`CADisableMinimumFrameDurationOnPhone` 四个字符串，UIKitCore 里有 `UIViewInProcessAnimationManager`。26 上这个 display link 是否仍请求 20..30 没有核对。

上游的诊断写法可以照用：`touch_lat=1` 时对每个新建的 display link 和每次速率请求打印一行，调用方用 `dladdr(__builtin_return_address(0))` 换成「镜像名+偏移」。

23G90 的 QuartzCore 读这个键有前提（静态反汇编）：

- `0x183fcf848` 读主 bundle 的 `CADisableMinimumFrameDurationOnPhone`，结果写进字节 `0x1e9cca538`。
- 读这个字节的四处代码都先检查字节 `0x1ecd951f8`（高帧率限制是否生效），为 1 时才看键。
- `0x1ecd951f8` 由设置值 `0x1ecd993bc` 决定：1 为生效，2 为不生效，其余取默认值 `0x1ecd95268`。
- 默认值同样先看设置值 `0x1ecd993c0`；没有设置时，只有字节 `0x1ecd98ccc` 为 1（推断：CoreAnimation 认为显示支持可变刷新）才可能生效。

所以 iOS 26 上改 Info.plist 是否必要，要等内核发布刷新属性之后读这几个值才能判断。实现上系统盘改写做成 `HIGHRATE=1`，`inject_sb26_rate.c` 在 SpringBoard 里打印这几个值；120 Hz 方案 §2 里按纳秒写的间隔已按上游实测的单位更正。

## 4. 面板缩放：动画中用最近邻，静止后双线性重画

- 我们的现状：面板驱动默认双线性（`fb_filter=1`），每帧把 1125x2436 缩放拷进 1156x2510。按行更新（`12377-cmd38`）之后，`bo14` 静止时每帧拷贝中位数 1.6 ms，翻页时 5.4 ms，见[合成路径的处理器开销](2026-10-31-compositor-cpu-path.md) §9。翻页时整帧都变，按行更新省不下这部分。
- 上游 `cd8fdbb` 把默认改为 `fb_filter=2`：有新帧时用最近邻，40 ms（`SETTLE_MS`）没有新帧就用双线性把最后一帧再画一次，静止画面因此是双线性的。上游手机上最近邻每帧 1.7 ms（十帧里最慢一帧 4.3 ms），双线性 3.6 ms（11 ms）。
- 同一提交加了 `fb_pri`，presenter 与 helper 线程默认优先级 92（`BASEPRI_PREEMPT`）。内核默认优先级下这些线程在负载时让给渲染服务器的实时线程，十帧里最慢一帧 10.9 ms。
- 两项都改在与我们同源的 `MiniIOMobileFramebuffer.cpp`。重画需要持有上一帧的 surface 到 40 ms 之后，这与 `bo55` 修过的 swap 槽位放行时机相关；持有期间 CoreAnimation 是否会复用并写入这块 surface，需要先核对。
- 判据：翻页时每帧拷贝中位数低于 5.4 ms；静止 40 ms 后的截图与双线性截图逐像素一致。
- 已实现为 `fb_filter=2` 与 `fb_pri=N`，默认都不开（`MiniFramebufferPacing.inc`）。

## 5. ir3：spill 的着色器关掉 preamble 再编一次

- 上游 `hakios-metal` `9a61305`：CoreAnimation 的 uber shader `fixed_frag_lph_cpf`（102 次采样外加 uniform 分支）开着 preamble 时用满 ISA 能寻址的 48 个 full 寄存器，仍然每个 fiber spill 512 字节、144 次 reload；关掉 preamble 只用 21 个寄存器，不 spill。每个 draw 的 GPU 时间 6.6 ms→2.6 ms。规则是 spill 的 stage 关掉 preamble 再编一次，spill 更少、或 spill 相同而寄存器更少时用新结果。
- 我们的现状：Mesa 26.2.5（下同）的 ir3 对 A8XX 开着 preamble（`ir3_compiler.c` 的 `has_preamble`），文档里没有记录过 CoreAnimation 着色器的 spill 情况。
- 可用的开关：`IR3_SHADER_DEBUG=nopreamble`（`ir3_compiler.c:33`）全局关掉 preamble，但它同时关掉 descriptor prefetch（`ir3_nir.c:1665`），只能用来粗测。变体的 `pvtmem_size`（`ir3_shader.h:733`）非 0 表示用了私有内存。
- 已实现（`tools/mesa/rebase-26/0007`）：用了私有内存的 stage 常开打印一行（私有内存字节数、`max_reg`、preamble 指令数）；`REDWOOD_IR3_SPILL_RETRY=1` 时对有 preamble 的这类 stage 关掉 preamble 再编一次，按上游规则择优。判据是这类 stage 的数量，以及开关前后的 GPU 忙碌比例。

## 6. 按 pass 记 GPU 时间

- 上游 `5e26504`、`f5831e0`：被标记的命令缓冲在每个 pass 开始时、以及收尾等空闲之后让 CP 写 `CP_ALWAYS_ON_COUNTER`（19.2 MHz），按 pass 列出类型、目标尺寸与 draw 数。A635 上的读数：全屏 sysmem 混合的 pass 不论 13 个还是 145 个 draw 都要 14～24 ms；小 draw 的固定开销约 12.4 µs；总线 12.8 GB/s。
- 我们的现状：GPU 统计每 5 秒一行（忙碌比例、提交次数、平均耗时），iOS 26 路径没有按 pass 拆分。freedreno 已支持 `PIPE_QUERY_TIMESTAMP`（`fd6_query.cc:401`），AIR 库可以在 pass 前后各发一次查询。
- 用途：应用打开、玻璃与模糊这类 GPU 负载重的场景归因，以及 §5 的前后对比。`bo15` 显示慢档瓶颈在 backboardd 的处理器时间，所以这项排在 §3、§4 之后。

## 7. 工作流做法

- **无障碍开关做对照**（`a48d2b2`）：boot-arg `ax_rt`、`ax_rm` 在 SpringBoard 启动时调用 libAccessibility 的 `_AXSSetEnhanceBackgroundContrastEnabled`、`_AXSSetReduceMotionEnabled`，打开「降低透明度」与「减弱动态效果」，不改渲染代码就能量出模糊和缩放动画占多少 GPU。iOS 26 的 `libAccessibility.dylib` 导出这两个函数（静态核对），可用于 Liquid Glass 的成本归因。已在 SpringBoard 注入库里实现为同名 boot-arg。
- **独立探针内逐项切换**（`hakios-metal` 的 `--bisect`）：一次开机里把命令流的每组寄存器逐一关掉或换成另一种取值，每项按像素判对错，与本仓库「探针合并」的规则一致。候选问题是 A830 上 4 倍多重采样得到全 0、片元着色器纹理预取读到全 0，两者目前都靠关功能绕开，根因未查。
- **稳态测量**（`3aef7e3`）：同一组手势在开机工作结束之后跑四轮，每 5 秒列出占处理器最多的进程，帧行带出绘制所在的核。我们的轮次已有手势与帧统计，可以补的是「开机工作结束之后再开始计」与按进程的处理器占用。
- **测试程序依赖前端库**（`5889ebc`）：测试程序链接旧版前端库时会按旧代码通过或失败，上游把前端库加进测试程序的依赖。我们的构建用 `built-from-air` 戳判断前端是否变化，主机测试的依赖关系可以按同一条核对。

## 8. 核对后不采用或已有对应

| 上游做法 | 提交 | 核对结果 |
|---|---|---|
| 实现 `IOSurfaceWrapClientImage`（selector 6） | `759b620` | 只服务 GLES 渲染器。`bo63` 早期日志里被拒的 selector 是 17、32、40、41，没有 6 |
| `fb_measure` 读 DSI 帧计数器 | `aea57ed` | `bo53` 已读 INTF1 的 `INTF_FRAME_COUNT` |
| GMEM／sysmem 按代价选择、pass 内寄存器去重、GMEM 中 framebuffer fetch 的顺序 | `da3b052`、`5980a94`、`1dbe3cc`、`0c78612`、`b576ed1` | gallium freedreno 的 a8xx 有 GMEM 路径和 autotune 选择（`freedreno_gmem.c:722`），10-26 已对比过两种模式 |
| 不支持的工作只丢弃这一项，命令缓冲继续执行 | `ce2d5a2` | `hackios-xnu-kernel/tools/userland-driver/redwoodmetal.m` 的 `recordDraw` 已经打印一行后丢弃；`RW_CB_ERROR` 只有定义，没有赋值 |
| 参数缓冲布局与编译共用一把锁，八线程 TSAN 测试 | `5889ebc` | `hackios-xnu-kernel/tools/mesa/air/air_metal.c` 自 10-30 起所有入口用递归锁 `rwa_lock` 串行 |
| 管线采样数与附件不同时按附件的采样数画 | `d2f6009` | 壁纸扩展的管线与渲染通道都是 4 倍（`bo31` 的 `pipeline seen` 行），这条规则解释不了 `bo36` 的全 0；以后开启多重采样时按这条处理 |
| 定时按电源键做锁屏与唤醒 | `b8d4748` | `rwtouch button lock` 已有 |
| 整套 `hakios-metal` 驱动 | — | 寄存器层按 A6XX 写（`a6xx.hpp` 4489 行），插件面向 iOS 16.5，按用户决定不跟进 |
