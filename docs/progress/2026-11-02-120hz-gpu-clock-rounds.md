# 120 Hz 手势帧率的无人值守轮次（2026-11-02）

用户在 2026-11-02 把手机交给无人值守验证，目标是手势帧率尽量接近 Android 原生与 iPhone 的 120 帧／秒。本文记录这一天的改动、轮次与读数（dc2 在 11-05 补跑）。前一天的轮次见[120 Hz 轮次记录](2026-11-01-120hz-rounds.md)，逐帧拆分的口径见[120 Hz 手势帧率的卡点](../analysis/2026-11-01-120hz-gesture-bottleneck.md) §2，结论与拆分结果见[GPU 升频之后的长帧](../analysis/2026-11-02-120hz-after-gpu-clock.md)。

## 1. 内核与库

内核都在共用构建树 `hackios-xnu-kernel/out/xnu12377-cmd` 里编译，每一份比上一份多一项改动，之后在这棵树里编的内核都会带上这些改动。

| 内核 | 改动 |
|---|---|
| `12377-rate2` | `freeBuffer()` 把外部 buffer 的解除映射推迟到释放时最后一次提交完成；`adreno8_bo_unmap` 不再调用 `adreno8_context_wait_idle`；`GPU_LEFT` 由 64 改为 256；GPU 档位表加到 832 MHz |
| `12377-rate3` | boot-arg `gpu_tl=1`：每次退役打印 `tl: R 栅栏 sub 时刻 sop 时刻 eop 时刻`（GMU always-on 计数，微秒） |
| `12377-rate4` | 第一条 `tl: R` 之前打印一次 `tl: R clock ao 时刻 mach 时刻`，用来对齐两种时钟 |
| `12377-rate5` | speed bin 232 的档位表加到 1100 MHz（660、734、832、900、967、1050、1100），其他 bin 仍是前 10 档 |
| `12377-rate6` | `adreno8_speed=N` 超过档位数时截到最高档并打印一行 |
| `12377-rate7` | 连续两帧改动九成以上的行、间隔不到 25 ms 时，后 6 帧不做逐行哈希整帧画，再哈希两帧确认；5 秒统计行加 `drawn whole unhashed` |

AIR 库与 Metal 驱动：

- `tools/mesa/rebase-26/0008-u-trace-annibale-pass-times.patch`：任务环境变量 `ANNIBALE_PASS_TIMES=1` 打开 Mesa 的 GPU 时间戳，按 pass 种类每 5 秒汇总一次。freedreno 的 tracepoint 类型全是 marker，补丁按 `start_`／`end_` 名称前缀配对。
- `tools/mesa/rebase-26/0009-fd-resource-contents-undefined.patch` 与 AIR、Metal 驱动的配套改动：一个 pass 里 `MTLLoadActionDontCare` 的颜色附件，在这个 pass 的第一次绘制前标为内容无效，freedreno 不再把它读回 GMEM。没有开关，库里一直生效，dc2 起上机。
- 这两份补丁、`0007` 与 AIR 源码在 `.userland.git` `c6f82c5f5` 提交，移植到用户态仓库 `76502ff`；Metal 驱动与内核改动在内核仓库 `ce6e0c2`。

## 2. 轮次

都用 `cycle.py`、种子 `kernel-12377-cmd30-seed3`，boot-arg 都含 `usertrap=1 touch_poll_us=4000 fb_flip=2 fb_hz=120 fb_ca_hz=120 dl_max=1`。轮次目录是 `kernel-12377-<内核>-<轮次>`，例如 `kernel-12377-rate7-dc2`。手势帧率用 `gestures.py` 读，单位帧／秒。

| 轮次 | 内核 | 本轮变量 | 控制中心下拉 | 左滑 | 右滑 |
|---|---|---|---|---|---|
| gs1 | rate1 | `GPU_SPEED=7`（607 MHz） | 79.2 | 81.6 | 84.5 |
| uf1 | rate3 | 解除映射不再等 GPU 空闲 | 82.5 | 82.2 | 85.4 |
| gs10 | rate4 | `GPU_SPEED=10`（832 MHz） | 93.3 | 92.2 | 93.1 |
| gs14 | rate5 | `GPU_SPEED=14`（1100 MHz） | 92.9 | 94.5 | 92.4 |
| bt0 | rate5 | `fb_beat=0` | 102.9 | 103.5 | 101.3 |
| ff2 | rate5 | bt0 加 `fb_filter=2` | 104.5 | 99.2 | 98.4 |
| pt2 | rate5 | bt0 的开关，tour 2，`ANNIBALE_PASS_TIMES=1` | 106.5 | 105.6 | 92.9 |
| pf1 | rate5 | bt0 的开关，tour 2，处理器采样并转储 backboardd | — | — | — |
| best1 | rate6 | `cycle.py` 新默认值，三组手势各重复三次 | 100.7 | 105.8 | 95.5 |
| sk1 | rate6 | `sb_tl=1`（SpringBoard commit 探针），tour 2 | 104.6 | 104.2 | 89.0 |
| pt3 | rate6 | sk1 去掉 `sb_tl`，加 pass 时间 | 108.4 | 105.8 | 87.4 |
| hs1 | rate7 | 整屏动画跳过逐行哈希 | 106.5 | 105.6 | 90.4 |
| sm1 | rate7 | backboardd `FD_MESA_DEBUG=sysmem` | 105.7 | 106.3 | 95.5 |
| dc1 | rate7 | `ANNIBALE_DONTCARE_CLEAR=1`；画布 1206×2622 | 87.9 | 98.8 | 92.1 |
| ft3 | rate7 | dc1 加 `fb_threads=3` | 88.3 | 98.1 | 92.6 |
| c7 | rate7 | dc1 加 `cpus=7`，backboardd `ANNIBALE_PASS_LOG=1` | 85.6 | 99.3 | 91.2 |
| dc2 | rate7 | dc1 的开关，AIR 库换成带 `0009` 的一份，11-05 | 95.5 | 100.2 | 89.8 |

- tour 2 修正了设置图标的位置（0.385, 0.70），在手势段前后开关处理器采样，最后 `dump backboardd` 取共享缓存偏移。sk1 起各轮都用 tour 2。
- dc1 起画布是 1206×2622（`cycle.py` 的默认值，见[状态栏布局分析](../analysis/2026-11-02-status-bar-layout.md)），帧率只能与同画布的轮次比较。
- hs1、sm1、dc1、ft3 的 backboardd 都带 pass 时间（`ANNIBALE_PASS_TIMES=1`）。

## 3. 读数

- 档位：gs1 到 gs14 的日志分别出现 607、832、1100 MHz，832 到 1100 MHz 的手势帧率差在 2 帧／秒以内。
- 解除映射：uf1 起每 5 秒一行的解除映射统计里，最多一个窗口 1005 次，解除映射本身合计 7.0 ms 以内；rt2 同类窗口等 GPU 空闲合计 150～499 ms。
- `fb_beat=0`：GPU 完成后立即显示，不再等驱动自己的节拍，DPU 仍在面板 vsync 锁存地址。bt0 的手势帧率比 gs14 高 8～11 帧／秒，从此成为默认。
- best1：手势窗口里 3830 帧，88% 用一个节拍；GPU 最高 56.3 °C，CPU 簇最高 59.3 °C，最热的传感器 71.3 °C，CPU 温控上限触发 1～3 次。
- best1 的崩溃条目比 pt2 多，按时长折算后持平：usertrap「called from」每分钟 bt0 38 条、pt2 46 条、best1 43 条。新出现的 MessagesBlastDoor 断言与基线已有的 icloudmailagent 断言 pc 低位相同（`…878`）。
- hs1：每 5 秒最多 129 帧跳过哈希。sm1：GPU 最高 56.7 °C。c7：GPU 最高 57.5 °C，最热的传感器 70.2 °C。
- dc1：tile load 次数与 hs1 相当，`ANNIBALE_DONTCARE_CLEAR=1` 对整屏 pass 没有作用。
- dc2：整屏 pass 每次 907 → 795 µs；tile load 次数相当（72692 对 67911），每次 51 → 18 µs，合计 3.46 → 1.30 s。控制中心下拉 5 次的帧率是 90.1、112.5、81.5、80.1、114.1，dc1 是 85.8、110.4、64.0、71.5、110.5。截图与 dc1 逐张一致，崩溃条目不多于 dc1，最热的传感器 72.1 °C（dc1 为 75.2 °C）。

## 4. 默认值的变化

11-02 起 `tools/k90auto/cycle.py` 的固定参数加上 `fb_flip=2 fb_beat=0 fb_hz=120 fb_ca_hz=120 dl_max=1`，打包默认 `GPU_SPEED=14`。`GPU_SPEED`、`CYCLE_FIXED_ARGS`、`CYCLE_CPU_ARGS` 三个环境变量可以覆盖。当前的完整固定参数见 [k90auto 说明](../../tools/k90auto/README.md)。
