# 120 Hz、面板缩放与 ir3 重编的真机验证方案（2026-11-01）

本文登记三项改动的真机轮次、开关与判据，判据在读数之前写定。改动来源见[上游做法](../analysis/2026-11-01-hakios-upstream-lessons.md) §3～§5。三项改动默认都关闭，用 boot-arg 或任务环境变量开启，一份内核和一份 AIR 库可以跑完下面所有轮次。

## 1. 载荷身份

| 组件 | 产物 | 来源 |
|---|---|---|
| 内核 `12377-rate1` | `hackios-xnu-kernel/out/xnu12377-rate1.bin`，20,858,224 字节，sha256 `a07ae875…` | `out/xnu12377-cmd` 构建树（`cmd83` 状态）加上 `MiniIOMobileFramebuffer.cpp` 与新文件 `MiniFramebufferPacing.inc`；记录在 `kernel-12377-rate1/kernel.json` |
| AIR 库 | `out/ios26-resume/bbmetal-device/libredwoodair.dylib`，sha256 `70e939e9…` | `build-air.py`，构建树已打上 `tools/mesa/rebase-26/0007`；改动前的库备份为同目录 `libredwoodair.dylib.before-ir3-retry` |
| SpringBoard 库 | `package.py` 每轮从源码编译 | `SB26_SOURCES` 新增 `userland/src/inject_sb26_rate.c` |
| 系统盘 | 不变 | rt1 读到 `restriction=0`，不需要 `HIGHRATE=1` 重建 |

基线是 `kernel-12377-cmd54-bo63`。它在固定参数之外的 boot-arg 是 `usertrap=1 fb_flip=2 touch_poll_us=4000`，并带种子（`var_store=1`）。下面每轮在此基础上只加表中列出的开关。第一批两轮按 `package.py` 的默认值 `GPU_SPEED=3` 打包（GPU 最高 342 MHz），第二批起显式设 `GPU_SPEED=7`（最高 607 MHz，`bo40`～`bo57` 的档位）：

```sh
ANDROID_SERIAL=<序列号> GPU_SPEED=7 python3 tools/k90auto/cycle.py LABEL --kernel 12377-rate1 \
  --boot-args "usertrap=1 fb_flip=2 touch_poll_us=4000 <本轮开关>" \
  --baseline docs/progress/evidence/k90auto/kernel-12377-cmd54-bo63
```

## 2. 新开关与常开打印

| 开关 | 位置 | 作用 | 默认 |
|---|---|---|---|
| `fb_ca_hz=N`（24～480） | 内核 | 发布 `IOMFBDisplayRefresh`，间隔以 2^-32 秒为单位 | 不发布 |
| `fb_filter=2` | 内核 | 有新帧时最近邻，40 ms 没有新帧就用双线性重画最后一帧 | `1`（双线性） |
| `fb_pri=N`（1～95） | 内核 | presenter 与 helper 线程的优先级，上游用 92 | 内核默认 |
| `dl_max=1` | SpringBoard | 丢掉 UIKit 进程内动画（`UIViewInProcessAnimationManager`、`UIKit.InProcessAnimationManager`）的 display link 请求的速率 | 关 |
| `dl_log=1` | SpringBoard | 打印每个新建的 display link 与每次速率请求，带调用方（前 300 行） | 关 |
| `ax_rt=1`、`ax_rm=1` | SpringBoard | 降低透明度、减弱动态效果 | 关 |
| `REDWOOD_IR3_SPILL_RETRY=1` | 加载 AIR 库的进程的环境变量（`JOB_ENV`） | 用了私有内存且有 preamble 的 stage 关掉 preamble 再编一次，择优取用 | 关 |
| `HIGHRATE=1` | `userland/build.sh` 的系统盘步骤 | 每个应用的 Info.plist 加 `CADisableMinimumFrameDurationOnPhone` | 关 |

常开的打印：

- `sb26: rate 30s:` 与 `sb26: rate 120s:` 各两行。第一行是 `UIScreen` 与 `CADisplay` 报的速率；第二行是 QuartzCore 高帧率限制的内部值：`restriction`（限制是否生效）、`restriction_default`、`variable_refresh_seen`、`plist_key`（是否读到 Info.plist 的键）和两个设置值，未初始化的标 `(unset)`。
- 只有 QuartzCore 写这些值的指令与 23G90 逐字节一致时才读，开机时打印 `sb26: rate: QuartzCore restriction stores match`。
- `ir3[进程 pid]:` 每个用了私有内存的 stage 一行（每进程前 64 行），列出私有内存字节数、`max_reg` 与 preamble 指令数。

## 3. 第一批：120 Hz

rt1、rt2 已跑完：CoreAnimation 采用了 120 Hz，`restriction=0`，走分支 C，rt2 加了 `dl_max=1`。读数见[120 Hz 轮次记录](../progress/2026-11-01-120hz-rounds.md)，rt2 的逐帧拆分见[120 Hz 手势帧率的卡点](../analysis/2026-11-01-120hz-gesture-bottleneck.md)。

## 4. 第二批：GPU 档位与面板缩放

开关从 rt2 的 `fb_hz=120 fb_ca_hz=120 dl_log=1 dl_max=1` 起，每轮只加一个变量。顺序依据[卡点分析](../analysis/2026-11-01-120hz-gesture-bottleneck.md) §9：rt2 的长帧大多是 GPU 时间超过一拍。

- R1：打包加 `GPU_SPEED=7`，开关不变。判据：日志有 `RedwoodGPU: GPU at 607 MHz` 且 speed changes 大于 0；`frame-split.py` 的 G 超过一拍的帧比例低于 rt2 的 44%；tour 下拉控制中心那段高于 53.5 帧／秒；记下 GPU 传感器最高温度与温控降档次数。
- R2：再加 `fb_filter=2`。判据：静止时每 5 秒一行的 `frames drawn again filtered` 计数大于 0；手势窗口里 `us each in the driver` 低于对照轮；静止 40 ms 之后的截图与对照轮逐像素一致；`flicker.py` 不出现新的单帧闪烁。
- R3：再加 `fb_pri=92`。判据：`reportFrameTimes` 打印的 95% 分位帧间隔下降；触摸采样间隔（`bo62` 为 9.3 ms）不变差。

结果（11-02）：R1 跑成 gs1，帧率见[11-02 轮次记录](../progress/2026-11-02-120hz-gpu-clock-rounds.md)；之后 GPU 档位继续加到 1100 MHz。R2（`fb_filter=2`）跑成 ff2，与对照轮的差异在波动范围内，不采用。R3（`fb_pri=92`）没有跑：GPU 升频后长帧主要在 GPU 一侧，后续轮次改按[GPU 升频之后的长帧](../analysis/2026-11-02-120hz-after-gpu-clock.md)排。

## 5. 第三批：ir3 关 preamble 重编

不跑：rt1 里用了私有内存的 stage 只有 11 个，在 SpringBoard 与 iconservicesagent，backboardd 没有（[120 Hz 轮次记录](../progress/2026-11-01-120hz-rounds.md) §2）。

## 6. 风险与回退

- `fb_filter=2` 的重画在开始前确认没有等待中的 swap；重画过程中到来的新 swap 对应的 surface 可能正被 CoreAnimation 写入，表现为重画那一帧的局部错乱，下一帧即被替换。R1 的截图与 `flicker.py` 用来发现这一点。
- `HIGHRATE=1` 改的 Info.plist 在应用签名的资源封印范围内。应用打不开时去掉开关重建系统盘。
- 内核在共用构建树 `out/xnu12377-cmd` 里编译。之后在这棵树里编的内核会带上这两个文件，三个开关不设时行为与之前相同。
- 回退 AIR 库：把 `libredwoodair.dylib.before-ir3-retry` 拷回 `libredwoodair.dylib`；构建记录的备份是 `out/ios26-resume/mesa-arm64e/air-build-record.before-ir3-retry.json`。
