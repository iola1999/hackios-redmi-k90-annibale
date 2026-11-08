# backboardd 合成路径的处理器开销（2026-10-31）

本文记录 2026-10-31 为滑动卡、发热和电池图标缺失在 backboardd 合成路径上做的改动与读数。读数都来自 60 Hz、1125×2436 画布、GPU 最高 342～607 MHz 的 `bo` 系列轮次；120 Hz 之后的帧率与瓶颈见 [GPU 升频之后的长帧](2026-11-02-120hz-after-gpu-clock.md)。逐轮读数见[开机次序与性能记录](../progress/2026-10-31-boot-order-and-performance.md)。

## 1. 结论

- §3～§15 的改动之后，主屏翻页快档中位数从 `bo5` 的 49.3 帧／秒升到 52.8～56.2，今天视图慢档从 28.0 升到 37～40，backboardd 每帧处理器时间约 5.8 ms（`bo17`）。
- 没有反应的滑动是 `/dev/annibale-touch` 有两个读者，backboardd 里的输入线程在有 `input26-service` 时不再起（§12）。
- GPU 在 607 MHz 时约一半时间空闲，今天视图慢档的瓶颈在 backboardd 的处理器时间（§16）。

## 2. 帧率的两档

- 主屏页每帧约 75 次绘制，今天视图（小组件页）约 410～430 次，翻页帧率因此分两档。从第 1 页向右滑会进入今天视图，同一组翻页里两档交替出现。
- 0.57 秒的手势窗口中不低于 45 帧／秒的算快档，5～45 帧／秒的算慢档。
- `bo10` 慢档每帧 GPU 执行约 12 ms（342 MHz），GPU 没有满载。

## 3. 描边线宽

- 电池图标的外框与填充是 `CAShapeLayer` 的描边，backboardd 用管线 `TcmaA2LlnXhf` 画成 `MTLPrimitiveTypeLine`。
- AIR 建光栅化状态时没有设线宽，freedreno 在 `fd6_rasterizer.cc` 按 `linehalfwidth = line_width / 2` 写半宽，半宽为 0 的线段不出像素。Metal 的线段固定 1 像素宽，AIR 改为 `.line_width = 1.0f`（`tools/mesa/air/air_metal.c`）。

## 4. 调用方内存的 buffer

- 原来 `newBufferWithBytesNoCopy:` 的 buffer 是 AIR 另分配的拷贝，每次提交前 `buffer_mirror_pull` 用 `vm_read_overwrite` 读回调用方的整块内存并按行哈希。
- 内核 `AnnibaleGPUUserClient` 的 `kAnnibaleMemory`（0x7c，`AnnibaleGPUMemory.inc` 的 `memoryBuffer`）用 `IOMemoryDescriptor::withAddressRange` 包住调用方的地址范围，按只读方向 `prepare`（只读内存按读写方向会返回 `KERN_PROTECTION_FAILURE`），做成带 `MSM_BO_GPU_READONLY` 的 GEM buffer。AIR 的 `rwa_buffer_from_memory` 经 `resource_from_handle` 导入，`annibalemetal.m` 的 `initWithBytesNoCopy` 失败时退回拷贝。
- 映射回同一进程用 `kIOMapGuardedSmall`（`12377-cmd36`）。不加标志时得到原地址，释放 buffer 会把调用方自己的内存解除映射（`bo7` backboardd 崩溃）；加 `kIOMapUnique` 时解除映射再走一次 `doMap`，内核 data abort（`bo8`）。
- `bo9` 的处理器采样里没有 `buffer_mirror_pull`，慢档中位数 26.3 → 30.0 帧／秒。

## 5. 提交合并

- freedreno 的 `fd_submit_sp_flush` 只在 `should_defer`（待提交的 buffer 不超过 30 个、命令不超过 128 条）成立且 `has_shared` 不成立（不引用共享 buffer，或管道设了 `no_implicit_sync`）时合并。backboardd 每帧引用 IOSurface，原来每次刷新都单独提交。
- `tools/mesa/fd-submit-merge.patch`：Darwin 上不按共享 buffer 阻止合并，AnnibaleGPU 不按共享 buffer 给提交排序；待合并的命令上限 64 条，内核单次提交最多接受 82 条（`GPU_A830_SUBMIT_CMDS`）。AIR 的 `rwa_flush` 用 0 超时的 `fence_finish` 交出提交，fence 留给 `rwa_finish` 等。
- 今天视图每个显示间隔的提交次数中位数 `bo9` 33、`bo10` 3。每帧驱动耗时 25.3 → 16.8 ms，其中 `fd_batch_resource_read_slowpath`（读正被另一个批次写的资源时先提交那个批次）从 9.3 降到 0.5 ms。

## 6. 探针的开销

- 10-29 起为排查慢绘制加的分段计时（`tools/mesa/fd6-draw-seg-slow.patch` 等）在每个时间点还调用 `thread_info` 读线程处理器时间、`getrusage` 读缺页数，每次绘制共约 10 次 `thread_info`、8 次 `getrusage`。
- `bo11` 改为只读时钟（`tools/mesa/fd-probe-wall-only.patch`），AIR 去掉 `thread_cpu_us`。每次绘制的 `draw_vbo` 38.3 → 9.1 µs，今天视图每帧驱动耗时 16.8 → 4.4 ms，相邻刷新间隔 35.7 → 23.8 ms，backboardd 全轮处理器时间 158.6 → 97.2 秒。
- 慢档帧率只从 35.1 升到 36.8 帧／秒，瓶颈已不在驱动的处理器时间。

## 7. buffer 纹理导入的大小

- 建在调用方内存 buffer 上的纹理，导入（`buffer_texture_alias`）在 `bo11` 大多失败：`fd_screen_bo_from_handle` 收到的大小是 0，Gallium 的布局检查不通过，退回拷贝。
- `tools/mesa/fd-import-size.patch` 改传 `winsys_handle.size`，AIR 导入时填上 buffer 的大小；导入的 buffer 预取页面时只读不写。`bo12`（`12377-cmd37`）三个进程打印出的 48 次导入全部成功。

## 8. freedreno 的 madvise

- freedreno 的 buffer 缓存每次放入、取出 buffer 都经 IOKit 调一次 `madvise`，AnnibaleGPU 保留所有 buffer，总是回答「保留」。`tools/mesa/fd-madvise-skip.patch` 在 Darwin 上直接返回「保留」，不进内核。
- `annibale_drm.c` 每 4 秒按 ioctl 编号打印调用次数与耗时（`annibaledrm[PID]: calls in N ms, selector:calls/us ...`）。

## 9. 面板按行更新

- 面板驱动 `MiniIOMobileFramebuffer` 每帧把源图像缩放拷进 1156×2510 的面板内存，两个线程分担。`bo13` 里（1125×2436 源图像）屏幕静止时每帧拷贝中位数 8.2 ms，翻页时 8.6 ms。
- `12377-cmd38` 对源图像每行算一个哈希（四路 FNV），没有行变化的帧直接跳过，有变化时只画变化行覆盖的面板行段（`MiniFramebufferRows.inc`）。只在第 0 层单独一个 surface 时启用，boot-arg `fb_rows=0` 关闭。
- `bo14`：静止时每帧拷贝中位数 1.6 ms，翻页时 5.4 ms。翻页时整帧都变，按行更新省不下这部分；整屏动画跳过哈希见 [GPU 升频之后的长帧](2026-11-02-120hz-after-gpu-clock.md) §5。

## 10. GPU 频率

- 设备树（`docs/analysis/data/annibale.dts.gz` 的 `qcom,gpu-pwrlevel-bins`）有六张档位表，160～832 MHz 各档的 level、总线投票与 ACD 值相同，900 MHz 一档的总线投票不同。本机 speed bin 为 232（0xe8），对应第 2 张表。
- `12377-cmd39` 在 `adreno8_cx.c` 加 389、443、525、607 MHz 四档，level 与总线投票取自设备树。之后加到 1100 MHz 的档位见 [k90auto 说明](../../tools/k90auto/README.md)，调频与温控规则见 `hackios-xnu-kernel/xnu/files/bsd/dev/adreno8_hfi.c` 里 `adreno8_speed_tick` 前的注释。
- `bo15`（`GPU_SPEED=7`）：今天视图翻页时 GPU 忙碌比例从 94%（342 MHz）降到 56%，GPU 最高 49.8 °C；慢档 38.2 帧／秒，没有随 GPU 变快而提高。

## 11. GPU 完成中断

- 设备树 GMU 节点的「hfi」中断是 SPI 0x130（INTID 336），电平触发，GMU 往消息队列写消息（包括提交完成的 `TS_RETIRE`）时触发。
- `12377-cmd40` 起等 GPU 的线程睡到这个中断（`adreno8_hfi.c`，`gpu_irq=0` 退回每 200 µs 轮询），最长睡 2 ms；100 ms 内超过 20000 次中断时屏蔽中断，退回轮询。
- `bo16`：静止时每 5 秒约 50 次中断。快档 60 个窗口，中位数 56.2 帧／秒，0.57 秒窗口出 36 帧（63 帧／秒）的比 `bo15` 多。

## 12. 没有反应的手势

- 现象：`bo16` 的 84 步里 7 次滑动没有出帧，内核记下了全部触摸采样，之后没有 `tl: Q`、`tl: s`、`tl: v`。停住的触点被当成长按，主屏或今天视图进入编辑模式。
- 原因：`/dev/annibale-touch` 有两个读者，`input26-service` 与 `libannibale.dylib` 在 backboardd 里起的输入线程（`inject.c` 的 `input_start()`，2026-10-29 起随 `package.py` 的 `INJECT` 装进 backboardd，`00810fb`）。每个采样只被先拿到锁的一方读走，两边都丢弃没有见过按下的移动与抬起，按下与抬起落在不同读者时 backboardd 里的触点一直停在按下状态。
- 判读：backboardd 开机日志第二次「digitizer attached」带「*** already have a main display digitizer」；没有反应的滑动在 `TouchEvents` 里没有「contact 1 presence: none」，下一次按下记「range-in for pathIndex with existing contact -- using existing」。
- 改法：`inject.c` 在 `/annibale/LaunchDaemons/com.annibale.input26.plist` 存在时不调用 `input_start()`，打印「annibale: input: input26-service reads the touch queue, so no service of ours」；`libannibale.dylib` 仍注入 backboardd，提供 `tl: b`。`userland/build.sh` 对 `inject.conf` 有同样的冲突检查，`package.py` 没有。
- `bo23`（`12377-cmd44`）：开机日志只有一块触摸屏，40 次翻页每次 30～33 帧，今天视图 16 次滚动每次 27～32 帧。
- 看门狗（`12377-cmd42` 起）：手指采样开始一个手势 400 ms 后面板仍没有新帧，就转储 backboardd、SpringBoard 与 `input26-service` 的线程，并打印 `/dev/annibale-touch` 里没读走的采样数；`12377-cmd44` 起主屏键不触发，卡顿转储要求最后一个手指采样在 100 ms 以内。

## 13. 探针的开销（二）

- `bo16` 里 `mach_absolute_time` 占 backboardd 用户态样本的 18%，来自 freedreno 与 AIR 里每次绘制仍读时钟的计时点。
- `tools/mesa/fd-perf-off.patch` 让这些计时点只在环境变量 `FD_PERF_DRAW=1` 时读时钟，`fd_bo_cpu_prep` 与 AIR 的 `draw_mark()` 同样处理。
- `bo17`：`mach_absolute_time` 降到 1%，backboardd 全轮处理器时间 124.7 → 54.7 秒，按出帧数折算每帧约 9.3 → 5.8 ms。`bo17` 进今天视图的一步失败，今天视图的帧比 `bo16` 少，这个比值偏低多少没有读数。

## 14. 今天视图里 backboardd 退出

- `bo18` 在今天视图上下滚动时 backboardd 以 SIGABRT 退出 4 次（退出原因的命名空间是 CoreAnimation）。每次退出前 AIR 拒绝了片段着色器 `TimgBadcA2S1Xhfu_Ialp` 的管线（「intrinsic: air.fmax3.f16」），CoreAnimation 建不出这条管线就终止进程。
- `tools/mesa/air/air_intrinsics.c` 增加浮点、有符号与无符号整数的 `min3`、`max3`、`median3`，`median3` 按 `max(min(x, y), min(max(x, y), z))` 展开。`bo19` 同一段巡检 backboardd 没有退出。

## 15. 计算着色器派发不等 GPU

- 原来 `rwa_dispatch_threadgroup` 在 `launch_grid` 之后刷新并等这次派发的 fence，`bo19` 今天视图里每次派发 1.4～3.2 ms。
- AIR 新增 `rwa_dispatch_nowait`（`tools/mesa/air/air_metal_dispatch.inc`），派发留在批次里，随命令缓冲的 `rwa_flush` 提交，命令缓冲在那次刷新的 fence 上完成（`annibalemetal_completion.inc`）。`fd_context_flush` 把同一上下文的其他批次排在前面（`fd_bc_add_flush_deps`），所以这个 fence 也覆盖派发的批次。
- 原有的三个派发入口仍然等待，AIR 测试程序和 `ANNIBALE_SYNC_DRAWS` 走这些入口。
- `bo23` 下拉搜索：每次派发 22～79 µs，没有 GPU 未完成的报错，模糊背景正常。

## 16. 未解决

- 今天视图每帧约 410 次绘制，处理器时间在 CoreAnimation、驱动与内核之间如何分配，没有按帧的读数。`bo18`～`bo20` 今天视图滚动的 21～26 帧／秒是在 Spotlight 崩溃循环期间测的，不能用来判断合成路径的开销；没有循环时（`bo21`）每步 29～36 帧，见 [Spotlight 崩溃循环](2026-10-31-spotlight-crash-loop.md)。
- `bo17` 里 backboardd 内核态样本 1522 个、用户态 904 个，前几项是开中断处（`ml_set_interrupts_enabled_with_debug`）与 workqueue 锁的自旋（`hw_lck_ticket_contended`），来自 libdispatch workloop 线程的唤醒与停放；哪些队列在频繁唤醒没有读数。
- 采样器（`tools/k90auto/prof.py`）记录中断时被打断的位置，关中断期间执行的函数记在开中断处。按进程的处理器时间以 `ps` 为准。
- ScreenContinuity 每轮 SIGTRAP 退出，见 [Spotlight 崩溃循环](2026-10-31-spotlight-crash-loop.md) §6。
