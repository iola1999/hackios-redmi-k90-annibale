# iOS 26 可用桌面：解锁、着色器编译、GPU 挂起与图标渲染（2026-10-29 夜～10-30）

本文记录 iOS 26 从开机后停帧到主屏图标全部画对的几个问题，每项写根因、修复和验证轮次。轮次标签（`homecycle1`、`interactive1`、`ffma1`、`lock1`、`render1`～`render93` 等）对应 `docs/progress/evidence/k90auto/` 下的本地目录。`cycle.py`、`tour.py`、`render-health.py`、`respin.py` 的用法见 [k90auto 说明](../../tools/k90auto/README.md) §8。

## 1. 开机自动解锁

- `homecycle1` 的两次自动上划都在锁屏可操作之前：一次落在开机 logo 层上，一次落在背光关闭期间（backboardd 记 `canceling events for suppression reason: backlight dim/off`）。用户手动上划一次即解锁，iOS 26 的解锁路径正常。
- `init` 每行只解析前 63 个词（`userland/src/init.c` 的 `run_command()`），超长的 rwtouch 行在第 63 个词处报 `bad step "swipe"` 退出。`rc.jobs.home-cycle` 每行不超过 49 个词。
- 修复：`userland/src/inject_sb26.c` 从 SpringBoard 启动第 10 秒起每 3 秒查一次 `isUILocked` 并调用 `-[SBLockScreenManager unlockUIFromSource:withOptions:]`，见过锁屏且解锁后停止，最多 60 次。Darwin 通知 `com.redwood.unlock`（`rwtouch notify com.redwood.unlock`）再解锁一次；启动参数 `autounlock=0` 保留锁屏。`package.py` 编这个库并注入 SpringBoard。
- 验证：`interactive1` 日志 `sb26: unlock boot: answer=1 locked_after=0`。

## 2. 着色器编译卡住 SpringBoard

### 2.1 编译队列只有一个线程

- 现象（`homecycle1`）：解锁约 20 秒后停帧，驱动记 `commit 3 has not moved for 2708 ms inside a recorded work`，渲染线程停在 `ir3_get_shader → _util_queue_fence_wait`。
- 原因：编译队列的线程数是在线 CPU 数的一半，`cpus=2` 下只有 1 个。`interactive1` 的 backboardd 编译任务线程 CPU 只占墙钟的 10%，入队到开始最长 2.87 秒，渲染线程等待合计 5.06 秒。
- 修复（`hackios-xnu-kernel/tools/mesa/ir3-compile-steal.patch`）：`util_queue_steal_job()` 把还没开始的任务取走、不发 fence 信号，`ir3_get_shader()` 在本线程编完再发信号。编译队列线程在 Darwin 上设为 `QOS_CLASS_USER_INITIATED`，仍低于渲染线程。`ffma1` 单次等待最长 0.53 秒（`interactive1` 为 1.79 秒）。

### 2.2 `Unhandled ALU op: ffma`

- 现象：SpringBoard 主线程永久停在 `_util_queue_fence_wait`。小白条、上划回主屏、通知中心、控制中心和状态栏时间都由这个线程负责，一起失效。
- 原因：AIR 前端把 Metal 的 `fma()`（非 fast）和 `llvm.fmuladd` 翻成严格融合的 `nir_ffma`（`tools/mesa/air/air_intrinsics.c`、`air_llvm.inc`）。ir3 的 `float_mul_add32` 只声明 `has_fmad` 和 `fuse`，NIR 不为它降级严格 `ffma`，`emit_alu()` 走进 `default` 分支。`ir3_context_error()` 结尾的 `UNREACHABLE("")` 在 release 构建里是 `__builtin_unreachable`，编译线程不再返回。
- 修复（`hackios-xnu-kernel/tools/mesa/ir3-ffma-as-mad.patch`）：`emit_alu()` 把 `nir_op_ffma` 按 `nir_op_fmad` 发射，a6xx 起的 mad 不融合，结果比源码多一次舍入。`ir3_context_error()` 结尾改为 `abort()`，进程带着着色器转储退出，由 launchd 重启。`ffma1` 起小白条出现，控制中心能下拉。

## 3. backboardd 在 fd6 绘制代码里崩溃

- 现象（`ffma1`、`lock1`）：SIGSEGV 在 `fd6_vsc_update_sizes` 一带，`x0` 为 0；`fd_draw_vbo()` 刚确认过 `ctx->batch`，`fd6_draw_vbos` 读到的却是 NULL。`ffma1` 的崩溃前有并发提交（`commit N started while commit N-1 was still running`），`lock1` 没有，推断是 `-commit` 之外的入口（纹理上传与读回、缓冲纹理刷新）从别的线程刷掉了当前 batch。
- 修复：驱动在 `-commit` 进入时取进程内递归锁，`redwoodReturnSlot` 之后释放，完成回调在锁外执行。AIR 库 `air_metal.c` 加进程级递归锁 `rwa_lock`，碰 pipe_context 的 `rwa_*` 入口第一句是 `RWA_LOCKED`，用 `__attribute__((cleanup))` 解锁。`air_metal_copy.inc`、`air_metal_compute.inc` 里也有入口，必须列在 `tools/k90auto/build-air.py` 的 `FILES` 里。

## 4. GPU 挂起：A830 的提前预备代码

### 4.1 现象与归属

- GMU 发 `HFI fatal message 150 data 0x1`（KGSL 编号里 150 是上下文出错，`0x1` 是 GPU 硬件挂起），内核报 `context EOP timeout failed; submissions closed`，GPU 停用到冷启动，CoreAnimation 退回软件合成。
- 所有进程共用一个 GMU context（`adreno8_context_submit`），提交按顺序完成，归属以 HFI 150 里的时间戳和已完成时间戳为准（内核 `12377-cmd2` 起打印）。驱动的 `REDWOOD_SYNC_DRAWS=1`（由 `JOB_ENV` 加给指定任务）每个绘制后提交并等待，没完成的绘制连同两个模块打印出来（`AIRFAIL begin hung-vertex`／`hung-fragment`）。
- 内核在外部缓冲解除映射前等全部提交完成，原上限 200 毫秒（`CONTEXT_WAIT_NS`）超时也关闭提交，`render21` 因此误报一次挂起；`12377-cmd7` 起改为 2 秒，超时打印时间戳并转储 CP。
- 有时间戳确认的挂起绘制都来自 RenderBox。不改着色器时，挂起的片段着色器都经 bindless 描述符 0x37、0x38 读帧缓冲，最常见的是 SpringBoard 的 `primitive__vertex+ffea2ba11dhmha4`。
- CP 转储（`render15`）：IB1 与 IB2 的 `REM_SIZE` 都是 0，CP 已取完全部命令；最后一个包是 `CACHE_FLUSH_TS`，时间戳没有写出。`RBBM_STATUS` 为 0xfe1007：CP、`HLSQ_BUSY`、slice 忙，`PC_BUSY`、`VPC_BUSY`、`UCHE_BUSY`、`VSC_BUSY` 为 0，停住的是着色器一侧。

### 4.2 排除的变量

每轮只改一项，日志确认进程读到了开关，下表各项都仍然挂起。除 `FD_MESA_DEBUG` 选项和图元重启外，这些改动只在当轮构建里，源码不保留。

| 轮次 | 改动 |
|---|---|
| `render8` | `FD_MESA_DEBUG=nolrz` |
| `render11` | 索引绘制开启图元重启（Metal 的索引绘制总是开启，16 位 0xFFFF、32 位 0xFFFFFFFF） |
| `render13` | `discard_fragment` 翻成空操作 |
| `render16` | `FD_MESA_DEBUG=sysmem`，描述符改走普通视图；读帧缓冲前的 `CP_WAIT_FOR_IDLE` 已完成 |
| `render17`～`render20` | `single_prim_mode` 保持 `NO_FLUSH`；层号为常数 0；读而不写的目标改为写全部通道；改用 `LATE_Z` |
| `render24`～`render26` | 片段输入去掉空位；采样号为常数 0；统一读 0 号目标 |
| `render27` | 只读：GPU 读到的 bindless 描述符与 freedreno 写入的逐字相同，寄存器状态与设计一致 |
| `render28`～`render30` | `isam` 代替 `isamm`；坐标为常数 (0, 0)；置上 `BINDLESS_SAMP` |

只有把帧缓冲读取整个换成常数 0（`render21`）时 `ffea2ba11dhmha4` 能完成，随后 `render22`、`render23` 又停在 iconservicesagent 的 `primitive_gradient_vertex` 绘制上。

### 4.3 二分与修复

- `render31` 用 `IR3_SHADER_DEBUG=noaliasrt,noaliastex,nopreamble,noearlypreamble,nodescprefetch` 关掉 ir3 自 A7XX 起的五项可选特性，整轮没有 HFI 150，同步模式下 261 个绘制完成。
- `render32` 只关 `alias.rt`、`alias.tex`，`render33` 只关描述符预取，都仍然挂起。
- `render34` 只关提前预备代码（`noearlypreamble`），没有 HFI 150，218 个绘制完成。挂起绘制的 `SP_PS_CNTL_0.EARLYPREAMBLE` 为 1。
- 修复：设备 Mesa 树 `freedreno_devices.py` 的 A830 条目加 `GPUProps(has_early_preamble = False)`，覆盖从 `a7xx_gen3` 继承的值，A829、A840 不变（`tools/mesa/rebase-26/0004-a830-no-early-preamble.patch`）。`render35` 不设 `IR3_SHADER_DEBUG`，304 个绘制完成，整轮没有 HFI 150。
- 排查工具：内核 cmd7 的 2 秒等待、cmd8 打印 BR 的整条命令树与片段阶段 bindless 描述符、`tools/k90auto/cp-words.py`、`tools/k90auto/cp-state.py`。
- A830 上片段着色器纹理预取读到全 0 的问题见[开机次序与性能记录](2026-10-31-boot-order-and-performance.md) §6。

## 5. 图标与界面的渲染缺口

`package.py` 默认（`ICON_METAL=1`）给 iconservicesagent 注册 Metal；它用软件渲染时 IconRendering 拒绝序列化图标（`TextureIOError.usingSoftwareRenderer`），设置「通用」页的图标是灰块。下表是 GPU 路径上逐个去掉的缺口。

| 现象 | 原因 | 修复 | 轮次 |
|---|---|---|---|
| IOSurface 导入、绘制被拒 | 驱动不认格式 30；AIR 缺格式 90～94；`device` 缓冲偏移对齐要求 64；no-copy buffer 上限 64 KiB | 30 对 `'LA08'`；加 RGB10A2Unorm 等五种；对齐改为 4，与 turnip 相同（`tools/mesa/freedreno-ssbo-offset-4.patch`）；上限 16 MiB | `render1`、`render2` |
| `compute_average_luma` 派发失败 | 线程组内存长度由 `-setThreadgroupMemoryLength:atIndex:` 给出 | AIR `rwa_dispatch_threadgroup`，Gallium 用 `variable_shared_mem` | `render1` |
| backboardd 大量 `got non-success return from kernel` | MiniIOSurface 58 号调用（`IOSurfaceClientQueryTransactionList`）未实现 | 返回成功和空列表（内核 `12377-cmd1`） | `render1` |
| RGBA16Float 表面因行字节数被拒 | 驱动按 128 字节对齐检查行字节数 | 只采样的导入只要求整像素；颜色渲染目标要求 64 字节，由 `fd_gmem_render_tiles` 直接写内存，因为 GMEM 按 16 像素块回写会越过行尾（`tools/mesa/fdl6-linear-import-pitch.patch`） | `render2` |
| 指针 phi 与 `select` 的管线被拒 | 沿循环回边传回的指针；同一缓冲两个位置间的 `select` 与 phi | 偏移进寄存器、对偏移做 `bcsel`；不同资源之间仍拒绝 | `render3`、`render36` |
| 「reads texture 1 and 1 texture was bound」 | 带 `air.arg_unused` 的纹理被列为必须绑定 | `air_to_nir.c` 不登记这类纹理与 API 采样器 | `render36` |
| 45x42、42x42 RGBA16Float 图标表面导入失败 | 每行 384 字节、分配 16384 字节，`fd6_layout.c` 为 GMEM 的 16x4 读写把末级补到 4 行的倍数，布局 16896 字节 | 接受线性、单级、单层且各行都落在内存内的导入，资源标记 `sysmem_only`（`tools/mesa/rebase-26/0005-linear-import-last-level-padding.patch`） | `render36` |
| `unable to allocate sampler state: 4` | 滤波值 2 是 `MTLSamplerMinMagFilterCubic`（SDK 头文件没有） | 按线性采样 | `render37` |
| 纹理视图为空 | 驱动对纹理视图返回 nil | `rwa_texture_view` 可取一段连续的级别；`rwa_texture_generate_mipmaps` 从视图的第一级生成 | `render37`、`render42` |
| 自定义效果管线被拒（`custom_fn.MTL_VISIBLE_FN_REF`） | IconRendering 的 `[[stitchable]]` 函数经 `fragmentLinkedFunctions` 链接进管线 | `-newFunctionWithDescriptor:error:` 先走 `_MTLLibrary` 自己的实现，返回 nil 才用代理；`air_link.inc` 按拼接图顺序内联链接函数；没有片段函数的管线用空片段着色器 | `render39` |
| iconservicesagent 每个 commit 后 SIGTRAP | IconRendering 对纹理底下的 MTLBuffer 取弱引用，nil 时 `brk #1`；驱动 `-buffer` 恒为 nil，结果也不拷回 buffer | 纹理持有 buffer 并如实返回；已写的 buffer 纹理在 `-waitUntilCompleted` 与每次 commit 前拷回（`rwa_buffer_textures_writeback`） | `render45` |
| GPU SMMU 缺页，随后三个进程崩溃 | GPU 读过最后一个 BO 的末尾 | 内核 `12377-cmd11` 给每个 BO 后多留一页，映射到清零的只读页 | `render49` |
| 图标里成块的绿、品红、白色 | `-newBufferWithBytesNoCopy:` 复制调用方内存，GPU 结果只进驱动副本 | `rwa_buffer_set_mirror` 拷回时同时写调用方内存，只写不读（调用方可能已释放）；每批工作前用 `vm_read_overwrite` 读调用方内存，有变化才拷进副本 | `render54`、`render58` |
| 覆盖率填充没有写出像素 | 常量 buffer 偏移原样交给 freedreno，A830 读不是 16 倍数的 UBO 地址时数据错位 | 偏移不是 16 的倍数时按 `air.buffer_size` 拷贝后绑定（`air_metal.c` 的 `bind_stage`） | `render69`、`render70` |
| 图标上一条对角细线 | 翻译路径不跑 `nir_shader_gather_info`，ir3 不开 `PIXLODENABLE`、`LODPIXMASK`，边上的导数读到没有运行的辅助线程 | `air_gather_quad_helpers` 按 `nir_gather_info.c` 的规则补上 | `render71` |
| 文字碎片与黑块 | RGB10A2 的纹理 buffer 对齐答 16、线性纹理答 64，客户端按 64 写 | `minimumTextureBufferAlignmentForPixelFormat:` 返回线性纹理的值 | `render77` |
| 图形里的斜向条纹 | SpringBoard 的图形 IOSurface 行字节数按 32 对齐（50×83 为 224），A830 按 64 的倍数取行距；客户端按自己的行距写，内核补齐无效（`render88`） | 单平面二维、行距不是 64 倍数的 surface 经覆盖其内存的 buffer 纹理拷贝采样，GPU 写过的写回（`redwoodmetal_texture.inc` 的 `rw_surface_through_copy`） | `render89`、`render90` |
| 黑色弧形与边缘黑点 | freedreno 新建资源不清零，距离与模糊滤镜读到所画区域以外的残留 | 新建颜色与深度目标先清零（`texture_start_zeroed`） | `render93` |

## 6. PosterBoard 的数据存储

- `-[PBFPosterExtensionDataStore initWithURL:...]` 返回 nil 且错误为 nil。四处返回 nil 的位置（迁移、bundle ID 迁移、完整性校验、SQLite 打开）只发 `os_signpost`，探针在 `userland/src/inject_posterboard.c`。
- 原因：版本有效要满足 `PFPosterPathURLResourceValues()` 给出的资源值，其中有文件保护等级；RAM 盘所在的卷不支持数据保护，任何版本都无效，从 59 到 61 的迁移每次失败。
- 修复：`inject_posterboard.c` 在 NSURL 的四个 `pbf_*ResourceValues*` 方法里去掉 `NSURLFileProtectionKey`，`render15` 迁移成功。之后 PosterFoundation 用 `fsctl(path, 0xc0084a44, …)` 标记 purgeable 失败，内核提交 `2d70025` 让 APFS 对 `APFSIOC_MARK_PURGEABLE` 返回成功，其余 ioctl 仍回 ENOTTY。
- 默认壁纸由 MercuryPosterExtension 绘制，见[锁屏壁纸](../analysis/2026-10-31-mercury-wallpaper.md)。

## 7. 观测手段的要点

- `REDWOOD_THUMBS=N` 把附件与纹理采成小图打进日志，`tools/k90auto/thumbs.py` 还原。通道截到 [0, 1]；两通道浮点纹理的 R、G 取绝对值，B 记符号（负 R 为 128，负 G 为 64）。深度附件的采样没有输出，原因未查。
- `REDWOOD_DUMP_AIR` 打印设备上特化后的位码，`tools/k90auto/airdump.py` 还原。特化名把前三个常量字按 16 进制半字节从低到高编码，`a`～`p` 表示 0～15，后跟的数字是重复次数；变体名每次开机都变。
- 日志快照是开机日志头加约 1 MB 的环，两次拉取之间输出过多就有缺口。SpringBoard 打开 os_log 会冲掉开机解锁那一行，`cycle.py` 随之跳过巡检。`systrace=1` 要配 `systrace_name=`，否则合并日志从 3 MB 涨到 20 MB。

## 8. 仍未解决

- GPU 停用后的软件合成下，回主屏时 backboardd 在 `ogl-context.cpp` 的 `push_surface` 断言失败，屏幕停在菊花（`render3`、`render6`）。
- 常量 buffer 的拷贝读处理器侧映射，同一次提交里先由 GPU 写的常量块会读到旧内容。no-copy buffer 经驱动 `-contents` 写入的数据到不了调用方内存。
- PosterBoard 在 10-31 的轮次仍报 `PBFPosterExtensionDataStoreErrorDomain -2222`、`FBProcessManager 2`。Bergamota 的 23G90 移植（`tools/sweetnet/sweetpb26.m`）对 PosterBoard 有四处改动，文件保护与 purgeable 两处与本项目重叠，其余两处没有对照。
- 设置页滚动后导航栏的模糊不对（10-30 截图），之后没有单独复查；模糊金字塔的修复见[锁屏壁纸](../analysis/2026-10-31-mercury-wallpaper.md) §8。
- 「关于本机」的歌曲、视频、照片一直是 Loading…，容量为 Zero KB。
