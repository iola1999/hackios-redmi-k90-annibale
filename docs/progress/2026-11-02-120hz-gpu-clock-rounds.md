# 120 Hz 手势帧率的无人值守轮次（2026-11-02）

用户在 2026-11-02 把手机交给无人值守验证，目标是手势帧率尽量接近 Android 原生与 iPhone 的 120 帧／秒。本文记录这一天的轮次、身份与读数。前一天的轮次见[120 Hz 轮次记录](2026-11-01-120hz-rounds.md)，逐帧拆分的口径见[120 Hz 手势帧率的卡点](../analysis/2026-11-01-120hz-gesture-bottleneck.md) §2，本轮次的结论与证据见[GPU 升频之后的长帧](../analysis/2026-11-02-120hz-after-gpu-clock.md)。

## 1. 内核与库

内核都在共用构建树 `hackios-xnu-kernel/out/xnu12377-cmd` 里编译，每一份比上一份多一项改动。之后在这棵树里编的内核都会带上这些改动。

| 内核 | 改动 | sha256 前缀 |
|---|---|---|
| `12377-rate2` | `freeBuffer()` 把外部 buffer 的解除映射推迟到释放时最后一次提交完成；`adreno8_bo_unmap` 不再调用 `adreno8_context_wait_idle`；`GPU_LEFT` 由 64 改为 256；GPU 档位表加到 832 MHz | `08ebb0e0` |
| `12377-rate3` | boot-arg `gpu_tl=1`：每次退役打印 `tl: R 栅栏 sub 时刻 sop 时刻 eop 时刻`（GMU always-on 计数，微秒） | `4f7648fb` |
| `12377-rate4` | 第一条 `tl: R` 之前打印一次 `tl: R clock ao 时刻 mach 时刻`，用来对齐两种时钟 | `b3744294` |
| `12377-rate5` | speed bin 232 的档位表加到 1100 MHz（660、734、832、900、967、1050、1100），其他 bin 仍是前 10 档 | `4929ee49` |
| `12377-rate6` | `adreno8_speed=N` 超过档位数时截到最高档并打印一行 | `d14e0ea2` |
| `12377-rate7` | 连续两帧改动九成以上的行、间隔不到 25 ms 时，后 6 帧不做逐行哈希整帧画，再哈希两帧确认；5 秒统计行加 `drawn whole unhashed` | `9608ece8` |

各内核的身份记录在 `docs/progress/evidence/k90auto/kernel-12377-rateN/kernel.json`。

AIR 库与 Metal 驱动：

- `tools/mesa/rebase-26/0008-u-trace-redwood-pass-times.patch`：任务环境变量 `REDWOOD_PASS_TIMES=1` 打开 Mesa 的 GPU 时间戳，按 pass 种类每 5 秒汇总一次，种类名带画布尺寸、GMEM bin 数、颜色附件数和深度／模板格式。pt1、pt2 没有打印汇总，原因是 freedreno 的 tracepoint 类型全是 marker，改为按 `start_`／`end_` 名称前缀配对后从 pt3 起有输出；pt3 的汇总在槽位复用时沿用旧值，hs1 起改正。
- `tools/mesa/rebase-26/0009-fd-resource-contents-undefined.patch` 与 AIR、Metal 驱动的配套改动：一个 pass 里 `MTLLoadActionDontCare` 的颜色附件，在这个 pass 的第一次绘制前标为内容无效，freedreno 不再把它读回 GMEM。库的 sha256 为 `7b9020b3…`，还没有上机（见 §5）。
- 这两份补丁、`0007` 与 AIR 源码在 `.userland.git` `c6f82c5f5` 提交，移植到用户态仓库 `76502ff`；Metal 驱动与内核改动在内核仓库 `ce6e0c2`。`.userland.git` 更早的 `0006` 与 `air_metal.c` 的一处注释仍未移植到用户态仓库。

## 2. 轮次

都用 `cycle.py`、种子 `kernel-12377-cmd30-seed3`，boot-arg 都含 `usertrap=1 touch_poll_us=4000 fb_flip=2 fb_hz=120 fb_ca_hz=120 dl_max=1`。手势帧率用 `gestures.py` 读，单位帧／秒。

| 轮次目录 | 内核 | 本轮变量 | 控制中心下拉 | 左滑 | 右滑 |
|---|---|---|---|---|---|
| `kernel-12377-rate1-gs1` | rate1 | `GPU_SPEED=7`（607 MHz） | 79.2 | 81.6 | 84.5 |
| `kernel-12377-rate3-uf1` | rate3 | 解除映射不再等 GPU 空闲 | 82.5 | 82.2 | 85.4 |
| `kernel-12377-rate4-gs10` | rate4 | `GPU_SPEED=10`（832 MHz） | 93.3 | 92.2 | 93.1 |
| `kernel-12377-rate5-gs14` | rate5 | `GPU_SPEED=14`（1100 MHz） | 92.9 | 94.5 | 92.4 |
| `kernel-12377-rate5-bt0` | rate5 | `fb_beat=0` | 102.9 | 103.5 | 101.3 |
| `kernel-12377-rate5-ff2` | rate5 | bt0 加 `fb_filter=2` | 104.5 | 99.2 | 98.4 |
| `kernel-12377-rate5-pt2` | rate5 | bt0 的开关，tour 2，`REDWOOD_PASS_TIMES=1` | 106.5 | 105.6 | 92.9 |
| `kernel-12377-rate5-pf1` | rate5 | bt0 的开关，tour 2，处理器采样并转储 backboardd | — | — | — |
| `kernel-12377-rate6-best1` | rate6 | `cycle.py` 新默认值，三组手势各重复三次 | 100.7 | 105.8 | 95.5 |
| `kernel-12377-rate6-sk1` | rate6 | `sb_tl=1`（SpringBoard commit 探针），tour 2 | 104.6 | 104.2 | 89.0 |
| `kernel-12377-rate6-pt3` | rate6 | sk1 去掉 `sb_tl`，加 pass 时间 | 108.4 | 105.8 | 87.4 |
| `kernel-12377-rate7-hs1` | rate7 | 整屏动画跳过逐行哈希 | 106.5 | 105.6 | 90.4 |
| `kernel-12377-rate7-sm1` | rate7 | backboardd `FD_MESA_DEBUG=sysmem` | 105.7 | 106.3 | 95.5 |
| `kernel-12377-rate7-dc1` | rate7 | `REDWOOD_DONTCARE_CLEAR=1`；画布 1206×2622 | 87.9 | 98.8 | 92.1 |
| `kernel-12377-rate7-ft3` | rate7 | dc1 加 `fb_threads=3` | 88.3 | 98.1 | 92.6 |
| `kernel-12377-rate7-c7` | rate7 | dc1 加 `cpus=7`，backboardd `REDWOOD_PASS_LOG=1` | 85.6 | 99.3 | 91.2 |

tour 2 修正了设置图标的位置（0.385, 0.70），在手势段前后开关处理器采样，最后 `dump backboardd` 取共享缓存偏移。pt1 是 pt2 之前的第一次 pass 时间尝试，没有汇总输出，读数不采用。

sk1 起各轮都用 tour 2。dc1 起画布是 1206×2622（另一个会话改了 `cycle.py` 的默认值，见[状态栏布局分析](../analysis/2026-11-02-status-bar-layout.md)），帧率只能与同画布的轮次比较。hs1、sm1、dc1、ft3 的 backboardd 都带 pass 时间（`REDWOOD_PASS_TIMES=1`），sm1、dc1 另加表中的环境变量。

## 3. 读数

- 档位：gs1 到 gs14 的日志分别出现 607、832、1100 MHz。832 到 1100 MHz 的手势帧率差在 2 帧／秒以内。
- 解除映射：uf1 起每 5 秒一行的解除映射统计里，最多一个窗口 1005 次，解除映射本身合计 7.0 ms 以内；rt2 同类窗口等 GPU 空闲合计 150～499 ms。
- `fb_beat=0`：GPU 完成后立即显示，不再等驱动自己的节拍，DPU 仍在面板 vsync 锁存地址。bt0 的手势帧率比 gs14 高 8～11 帧／秒，从此成为默认。
- `fb_filter=2`：ff2 与 bt0 的差异在轮次间波动范围内，不采用。
- best1：手势窗口里 3830 帧，88% 用一个节拍；GPU 最高 56.3 °C，CPU 簇最高 59.3 °C，最热的传感器 71.3 °C，CPU 温控上限触发 1～3 次。
- sk1 的 SpringBoard commit 探针（`sb_tl=1`，在主线程 run loop 上夹住 order 2000000 的 commit）整轮只记到 4 次，这个位置看不到 iOS 26 UIKit 的提交，读数不采用，探针代码没有保留。
- hs1：一拍帧 90%，C 的中位数 3.04 ms（best1 为 4.08 ms），每 5 秒最多 129 帧跳过哈希。
- sm1：整轮 backboardd GPU 时间 23.1 s，hs1 为 17.8 s；GPU 最高 56.7 °C。
- dc1：tile load 次数与 hs1 相当，`DontCare` 没有出现在整屏 pass 上，改动已撤回。
- ft3：C 的中位数 2.79 ms（dc1 为 3.34 ms），帧率不变；整屏 pass 有两个颜色附件，没有深度／模板附件。
- c7：帧率与 dc1 相当，GPU 最高 57.5 °C，最热的传感器 70.2 °C。驱动记下的整屏 pass 附件见[GPU 升频之后的长帧](../analysis/2026-11-02-120hz-after-gpu-clock.md) §6。
- best1 的崩溃条目比 pt2 多，按时长折算后持平：usertrap「called from」每分钟 bt0 38 条、pt2 46 条、best1 43 条。新出现的 MessagesBlastDoor 断言与基线已有的 icloudmailagent 断言 pc 低位相同（`…878`）。

## 4. 默认值的变化

`tools/k90auto/cycle.py` 的默认固定参数改为 `gpu_log=1 metal=1 cpufreq=1 fb_threads=2 touch_lat=1 gpu_coherent=1 fb_flip=2 fb_beat=0 fb_hz=120 fb_ca_hz=120 dl_max=1`，打包默认 `GPU_SPEED=14`。`GPU_SPEED`、`CYCLE_FIXED_ARGS`、`CYCLE_CPU_ARGS` 三个环境变量可以覆盖。

## 5. 队列停止

c7 结束后到 dc2 起轮之间主机超过 180 秒没有和 loader 通信，loader 的看门狗复位了手机（`cycle.py` 中 `loader_ready` 处的注释）。dc2 起轮前的检查正好落在复位期间，`cycle.py` 报 `STOP: no xnuloader in fastboot devices`，dc2 没有开始。之后只做了枚举和 `getvar`：`xnuloader` 已重新出现，`result` 为 idle。按 AGENTS.md §5 停止队列，标记文件在本地证据目录 `STOP-2026-11-02-dc2.txt`，等用户指令再起下一轮。

