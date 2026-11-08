# A830 GPU 加速桌面（iOS 16.5，2026-10-25～26）

本文记录 iOS 16.5 桌面第一次由 A830 绘制的结果：CP 启动的根因、显示异常的修复、无人值守测试方法和帧率结论。iOS 16.5 后来被 iOS 26 取代，内核的 `adreno8` 驱动和 Mesa freedreno 在 iOS 26 上继续使用。GPU 启动细节见 [A830 启动参考](../analysis/2026-10-24-a830-command-startup.md)，iOS 26 上的 120 Hz 与更高 GPU 档位见 [GPU 升频之后的长帧](../analysis/2026-11-02-120hz-after-gpu-clock.md)。

## 1. 结论

- A830 阶段 14～23 全部通过，`AnnibaleGPU` 注册成功。CoreAnimation 经 `eagl.c → OSMesa → freedreno` 在 GPU 上绘制，渲染器为「OpenGL ES 3.2 Mesa 26.2.5; Adreno (TM) 830」。
- 触摸（`touchscreen=2`）与 GPU 路径可以同时工作，用户在设备上确认滑动、翻页和控制中心可用。
- 主屏标签旁的闪烁色块和控制中心背景异常由 Mesa 的 CCHE 失效修复（userland `94e4c97`）。
- 双核、向量化缩放和 SCMI 大核调频后，显示驱动每帧从约 21 ms 降到 1.3～2.8 ms。GPU 提交排队、新建缓冲区提速和健康检查复用后，控制中心下拉 58.7 帧/秒（帧间隔 p95 17.5 ms），左右翻页 58.8／60.8 帧/秒，整轮 78% 的帧间隔低于 18 ms。
- GPU 档位随负载和触摸在 160～342 MHz 之间切换（内核 `ffca661`），每帧绘制 p50 从 13.2 ms 降到 9.6 ms。Turnip 探针在 iOS 上通过枚举、传输、计算和绘制读回。

## 2. CP 启动的根因

HWSCHED 的 RAW131 复位和直接 ring 的 CP_INIT 超时都来自 LPAC 微引擎的 SMMU stream（SID 1）没有路由：BR、BV 在启动屏障里等待 `THREAD_SYNC`，LPAC 始终没有清自己的位。内核 `a10067e` 把 SID 1 路由到 GPU context 0 后，CP_INIT、zap、退出 secure、scratch 和标准 context 均通过。分析见 A830 启动参考第 6 节。

阶段 23 到桌面之间还修正了 `adreno8_gmuclk=2` 的阶段准入（`4d2aa99`）、服务发布时的平台识别（`8eebac5`、`33808b4`）、GPU 运行后 CB0 TCR 的 EPD1 读回（`4d93f52`）和阶段 22 的队列读指针等待（`3d9c53f`），见 A830 启动参考第 7 节。

## 3. 显示异常：framebuffer fetch 读到另一个 bin

- 色块在源图中为 16×4 像素并按 16×4 对齐，连续 4 行形状相同；CPU 缓存行只覆盖一行 16 像素，排除 CPU 侧缓存一致性。
- 色块颜色与状态栏一带的壁纸相同，用户在闪烁区域看到过电池图标。12 MiB GMEM 扣除 6 个 CCU 的缓存区后，1125×2436 的帧需要两个 bin，`bin_h` 按 32 对齐为 1248；色块从源图第 1248 行开始，下半个 bin 显示了上半个 bin 同一相对位置的内容。`FD_MESA_DEBUG=sysmem`（不分 bin）时主屏色块消失。
- 色块集中在 CoreAnimation 使用 framebuffer fetch 的图标标签和控制中心材质处。上游 hackios 在 A642L 上遇到过同类问题，修法是在第一个读帧缓冲的 draw 前清理 CCU 并失效 UCHE（`fd6_draw.cc` 的 Darwin 补丁）。A8xx 的纹理读取路径多一级 CCHE，Mesa 26.2.5 在该位置没有失效它。

修复在同一位置对 `CHIP >= A8XX` 追加 `FD6_INVALIDATE_CCHE`，写在 `tools/mesa/rebase-26/0003-restore-osmesa-26.x-drift-adaptations.patch`（userland `94e4c97`）。无人值守对照中，修复前 94 张截图 31 张有色块，修复后 95 张为 0 张，用户目视确认无闪烁、控制中心正常；显示帧率和 GL 帧耗时在采样波动范围内不变。Mesa 环境变量经 `eagl.c` 的 `glenv=NAME=VALUE` 启动参数传入。

## 4. 无人值守测试方法

这一轮建立的方法已整理成 [`tools/k90auto/`](../../tools/k90auto/README.md)：

1. 根盘的 `etc/rc.jobs` 换成 `rc.jobs.desktop`：32 s 滑动解锁，约 120 s 起循环 8 轮，每轮下拉控制中心停 8 s、按 home 收起，再左右翻页。init 每行最多 63 个参数，每轮单独一行。
2. `run-auto.py` 每 20 s 拉一次日志，100 s 起每 3 s 截一次全分辨率图；`run-queue.sh` 依次运行多个载荷，退回 Android B 槽时调用 `recover-loader.py` 切回 A 槽 loader，loader 不处于 idle 时停止队列。
3. 截图转 PNG 后，按面板坐标第 1286～1400 行统计状态栏蓝色像素，判断 bin 边界处的色块。
4. `gestures.py` 按手势统计主动画：控制中心取首帧起 1.8 s，翻页取首帧起 600 ms，需要 `touch_lat=1`。

这一轮 A 槽重试次数用尽、退回 Android B 槽出现过两次，都由恢复脚本处理，没有人工按键。载荷必须带 `buttons=1 battery=1`，漏掉时按键和电量显示会消失，`make-payload.py` 已固定这两项。

## 5. 帧率与性能

### 5.1 CPU 调频与温控

- SM8750 的 CPU 时钟和电压由 CPUCP 固件管理，经 SCMI 性能协议（0x13）请求档位：共享内存 `0x17b4e000`，门铃 `0x17830000 + 0x104`。
- 固件报告两个性能域：`NCC0`（簇 0）16 档 384～3532 MHz；`NCC1`（两颗大核）16 档 1017～4320 MHz。`NCC1` 的可持续频率为 4089.6 MHz，可持续档索引却是 15（4320 MHz），内核按频率选不超过可持续频率和 `cpufreq_mhz` 的最高一档。
- `annibale_cpufreq.c`（内核 `95b5606`）：每 50 ms 取本域最忙的核心，目标频率为当前频率 × 忙碌比例 ÷ 0.8，取不低于目标的最低一档；升档立即执行，降档要持续 200 ms。触摸后 300 ms 内不低于 2438 MHz。上限取 `cpufreq_mhz`（默认 3100）与可持续频率中较低者。
- 温控：本簇任一传感器达到 70 °C 时降到最低档 1017 MHz，全部低于 60 °C 后恢复；没有有效读数时停在最低档。`cpufreq=2` 只报告，`cpufreq=3` 固定上限档，同样受温控约束。
- 真机结果：调频轮 83%～93% 的时间在 1017 MHz，帧间隔分布与固定 3.07 GHz 相同。温控在启动后桌面加载的 30 s 内触发过，最高 73.6 °C，30 s 内可在 60 °C 与 70 °C 之间往返 20 多次；之后操作期间最高 48～61 °C。

### 5.2 显示驱动与设备树竞态

- 显示驱动每帧把 1125×2436 双线性缩放到面板 1156×2510，`MiniFramebufferScale.h` 在四个面板像素对应四个相邻源像素时用向量代码。
- GPU 路径每帧调用 `annibale_platform_is_annibale()`，经 `find_entry()` 的静态游标 `startingP` 并发遍历设备树，运行 4～6 分钟后 panic「Device tree pointer outside of device tree region」。平台判断改为启动时算一次（`2249d0b`），`SecureDTFindEntry()` 每次调用使用自己的游标（`940e513`）。

### 5.3 GPU 提交路径

控制中心的模糊背景有多个渲染 pass，Mesa 在 glFlush 时逐个提交。原来 `adreno8_context_submit()` 排队前等上一次提交执行完，且等待期间持有 `gGPULock`。依次修改：

- `968ac2d`：最多 `adreno8_inflight`（默认 4，取值 1～8）个提交同时排队；队列写满时等 GMU 读走，超过 200 ms 才判定失败。控制中心主动画 40.3 → 53.9 帧/秒，超过 18 ms 的帧间隔 44% → 7%。
- `19cb049`：IOVA 从记录的最低空闲页开始查找，叶表按 2 MB 直接定位。
- `d4df543`：只清理本次改动的页表项，健康检查只在分配 IOVA 和提交映射时各做一次；发布页表平均耗时 118 µs → 3 µs。两项合起来，控制中心窗口每个新建缓冲区的中位数 2.09 ms → 0.20 ms，每帧绘制 p95 83.8 ms → 21.5 ms。
- `00259e5`：上一次完整健康检查（约二十个 GPU、GMU、SMMU 寄存器加一次 HFI 队列读取）通过后 1 ms 内只看 BO 状态，故障最晚在 1 ms 后发现。之后控制中心 58.7 帧/秒，帧间隔 p95 17.5 ms。

`db0dc22` 从 GMU 的 TS_RETIRE 通知取每次提交的 sop 与 eop，160 MHz 下每次提交 GPU 工作 1.0～1.7 ms，GPU 忙碌占比 12%～15%；剩余帧时间在窗口服务器的 glFlush（每帧 7～13 ms），freedreno 运行在 `u_threaded_context` 上，glFlush 等驱动线程执行完已排队的绘制。`adreno8_inflight=8` 与 4 结果相同；大核固定 3072 MHz 没有减少剩余慢帧；`FD_MESA_DEBUG=sysmem` 让每帧绘制 p50 从 13.7 ms 降到 11.2 ms，同一时刻的截图与 GMEM 模式逐像素比较差值不超过 8；带宽和功耗变化没有测量，默认未改。

### 5.4 GPU 档位

- `34209c1` 增加 222、342 MHz 两档，经 HFI 消息 30（`GX_BW_PERF_VOTE`）请求，GMU 应答后才算切换。`adreno8_speed=1` 固定 160 MHz，2、3 是允许达到的最高档。
- `ffca661` 在提交路径上最多每 100 ms 判断一次：GPU 工作时间换算到 160 MHz 的占比达到 20%，或最近 300 ms 内有触摸，升到 `adreno8_speed` 指定的档位；连续 500 ms 低于 10% 降回 160 MHz。任一 GPU 传感器达到 70 °C 或没有有效读数时请求 160 MHz，全部低于 60 °C 后恢复；GMU 不应答某次请求后本次运行不再切换。
- 结果：控制中心 58.8 帧/秒，每帧绘制 p50 9.6 ms，与固定 342 MHz 相同；静止时停在 160 MHz。静止桌面每次提交的 GPU 工作时间在 342 MHz 与 160 MHz 下之比约 2.1，接近频率比 2.14，据此判断 GMU 按请求改变了时钟；没有直接的时钟读数。GPU 传感器最高 43.6 °C，GPU 温控未触发。
- 连续 30 轮操作（1260 s）没有 panic，控制中心 59.0 帧/秒，GPU 档位切换 178 次。三核时控制中心 8% 的帧间隔超过 18 ms，双核为 2%～4%，默认继续使用双核。

## 6. Turnip 探针

内核 `34209c1` 上，探针枚举到 `Adreno (TM) 830`，1 MB 填充与复制、compute shader 写 4096 个字、64×64 三角形绘制三项读回都正确。所需的 Mesa 修改：没有 `HAVE_LIBDRM` 时 `drmGetDevices2` 是空实现，Turnip 构建要定义它；XNU 不允许 EL0 读 `CTR_EL0`，缓存行大小改从 sysctl `hw.cachelinesize` 取。修改在 `tools/mesa/rebase-26/0004-turnip-msm-darwin.patch`（userland `24641cc`），用 `TURNIP=1 REBASE=26 tools/mk-mesa.sh` 构建。内核 `811abcb` 只接受 `MSM_PARAM_COMM` 和 `MSM_PARAM_CMDLINE` 两种 `SET_PARAM`，未知参数不再一律成功。

## 7. 遗留问题

- CB0 TCR EPD1 的写入方未确认，见 A830 启动参考第 9 节。
- `adreno8_gmuclk=2` 的 GMU 时钟路径与触摸共用 Apps DRV2，两者不能同时使用；带触摸的运行使用晶振 GMU 时钟。
- 温控阈值 70 °C／60 °C 是保守取值，长时间高负载下的温度和整机功耗没有测量。
