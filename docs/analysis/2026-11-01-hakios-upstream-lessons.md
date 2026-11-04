# hakios 上游 10-27～11-01 的可借用做法

核对日期 2026-11-01。用户决定不合并上游代码、不跟进上游更新，只从中学习问题的解法和工作流。本文记录逐条核对的结果：已采用的写结果与提交号，未采用的写理由。之后一轮对照见 [11-05 对照](2026-11-05-upstream-lessons.md)。

## 1. 核对范围

| 仓库 | 固定版本 | 说明 |
|---|---|---|
| `oosexgang/hakios-xnu-kernel`（旧名 `hackios-xnu-kernel`，旧地址自动跳转） | `main` = `a48d2b2`（2026-11-01） | 10-27 拆仓库时历史被重写，与我们的内核子模块没有共同祖先；用子模块的 `upstream` 远端 fetch 后只读 |
| `oosexgang/hakios-metal` | `main` = `a097abd`（2026-10-31） | C++ 驱动，直接生成 PM4 命令流，Mesa 只用于 NIR→ir3；目标 A6XX（Adreno 7c+ Gen 3），插件面向 iOS 16.5 |
| `oosexgang/hackios-web` | 浅克隆最近 50 笔 | 新版指南 |

只读副本放在忽略目录 `docs/analysis/local/upstream-2026-11-01/`，没有执行其中的脚本或构建。上游 `hakios-metal` README 提到的 AIR 前端修复（纹理写入按值定类型、null texture 槽位、function constant 的 supplied 标记等）没有公开，只能作为测试用例的线索。

## 2. 已采用

| 做法 | 上游提交 | 本项目的结果 |
|---|---|---|
| 刷新间隔属性 `IOMFBDisplayRefresh`：`displayMinRefreshInterval`、`displayMaxRefreshInterval`、`displayRefreshStep` 以 2^-32 秒为单位，只有 `displayRefreshStepMachTime` 用 mach tick；报给 CoreAnimation 的速率与面板分开 | `b6c1f82`、`0dedaec`、`f6ebf31` | `fb_ca_hz=N`（`MiniFramebufferPacing.inc`，内核 `ce6e0c2`）；`rate1-rt1` 起 CoreAnimation 按 120 Hz 出帧，`fb_hz=120 fb_ca_hz=120` 是 `cycle.py` 的默认参数 |
| SpringBoard 里丢掉 UIKit 进程内动画的 display link 请求的速率 | `7caa457` | `dl_max=1`，默认打开；iOS 26 的类名是 `UIKit.InProcessAnimationManager`（16.5 是 `UIViewInProcessAnimationManager`）（userland `76502ff`） |
| 读回 CoreAnimation 看到的速率；`touch_lat=1` 时打印每个 display link 的创建与速率请求，调用方换成「镜像名+偏移」 | `cd72b54` | `sb26: rate` 行与 `dl_log=1`（`inject_sb26_rate.c`，userland `76502ff`） |
| 按 pass 记 GPU 时间（CP 写 `CP_ALWAYS_ON_COUNTER`） | `5e26504`、`f5831e0` | 改用 Mesa 的 GPU 时间戳实现为 `REDWOOD_PASS_TIMES=1`（`tools/mesa/rebase-26/0008`，userland `76502ff`），见 [GPU 升频之后的长帧](2026-11-02-120hz-after-gpu-clock.md) |

## 3. 已实现、默认关闭

| 做法 | 上游提交 | 结果 |
|---|---|---|
| 每个应用的 Info.plist 加 `CADisableMinimumFrameDurationOnPhone` | `c7b5f9a` | `HIGHRATE=1`（`userland/mkhighrate.py`）；`rt1` 读到 QuartzCore 的高帧率限制 `restriction=0`，不需要 |
| 面板缩放在动画中用最近邻，停住 40 ms 后双线性重画 | `cd8fdbb` | `fb_filter=2`；`rate5-ff2` 与对照轮的差异在轮次间波动范围内，不采用 |
| presenter 与 helper 线程优先级 92 | `cd8fdbb` | `fb_pri=N`；没有单独跑，GPU 升频后长帧主要在 GPU 一侧 |
| ir3 对 spill 的 stage 关掉 preamble 再编一次，择优 | `hakios-metal` `9a61305` | `REDWOOD_IR3_SPILL_RETRY=1`（`rebase-26/0007`）；`rt1` 里用了私有内存的 stage 只有 11 个，在 SpringBoard 与 iconservicesagent，每个 512 字节、`max_reg` 不超过 11，backboardd 没有，没有上机对比 |
| 用「降低透明度」「减弱动态效果」两个无障碍开关量模糊和缩放动画的 GPU 占用 | `a48d2b2` | `ax_rt`、`ax_rm`（SpringBoard 注入库）；文档里没有对照轮次的读数 |

记录轮次见 [120 Hz 轮次记录](../progress/2026-11-01-120hz-rounds.md) 与 [11-02 轮次记录](../progress/2026-11-02-120hz-gpu-clock-rounds.md)。

## 4. 没有采用或已有对应

| 上游做法 | 提交 | 理由 |
|---|---|---|
| CoreAnimation 开关（`caenv=`）也给 SpringBoard | `a5620ff` | 还没有做；我们的 `caenv` 只设进 backboardd |
| 稳态测量：开机工作结束之后再计手势，每 5 秒列出处理器占用最多的进程 | `3aef7e3` | 还没有做；我们的轮次已有手势与帧统计 |
| 测试程序把前端库加进依赖 | `5889ebc` | 我们用 `built-from-air` 戳判断前端是否变化，主机测试的依赖可以按同一条核对 |
| 独立探针内逐项切换寄存器组（`hakios-metal` 的 `--bisect`） | 无 | 候选问题是 A830 上 4 倍多重采样得到全 0，现在靠关功能绕开 |
| 实现 `IOSurfaceWrapClientImage`（selector 6） | `759b620` | 只服务 GLES 渲染器；我们日志里被拒的 selector 是 17、32、40、41 |
| `fb_measure` 读 DSI 帧计数器 | `aea57ed` | `bo53` 已读 INTF1 的 `INTF_FRAME_COUNT` |
| GMEM／sysmem 按代价选择、pass 内寄存器去重、GMEM 中 framebuffer fetch 的顺序 | `da3b052`、`5980a94`、`1dbe3cc`、`0c78612`、`b576ed1` | gallium freedreno 的 a8xx 有 GMEM 路径和 autotune 选择（`freedreno_gmem.c:722`） |
| 不支持的工作只丢弃这一项，命令缓冲继续执行 | `ce2d5a2` | `redwoodmetal.m` 的 `recordDraw` 已经打印一行后丢弃 |
| 参数缓冲布局与编译共用一把锁 | `5889ebc` | `air_metal.c` 所有入口用递归锁 `rwa_lock` 串行 |
| 管线采样数与附件不同时按附件的采样数画 | `d2f6009` | 解释不了壁纸扩展 4 倍多重采样的全 0；以后开启多重采样时按这条处理 |
| 定时按电源键做锁屏与唤醒 | `b8d4748` | `rwtouch button lock` 已有 |
| 整套 `hakios-metal` 驱动 | 无 | 寄存器层按 A6XX 写（`a6xx.hpp` 4489 行），插件面向 iOS 16.5，按用户决定不跟进 |
