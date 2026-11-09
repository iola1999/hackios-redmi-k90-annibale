# 上游 HakiOS 2.3.4 更新对比与移植分析（2026-11-06）

本文档梳理上游 `oosexgang/hakios-xnu-kernel` 仓库 HakiOS 2.3.4 版本（提交范围 `a3975b6..2631f5d`）的五项更新，逐项对比本仓库 REDMI K90（`annibale`，SM8750，iOS 26.6.2 `23G90`）的当前实现，给出每项更新的参考价值与合入决策。

## 1. 上游 2.3.4 提交清单

| 提交哈希 | 主题 | 涉及模块 | K90（`annibale`）适用性 |
| --- | --- | --- | --- |
| `81b5dd2` | 按下期间每轮轮询触摸芯片，抬指延迟由最高 169 ms 降至约 5 ms | `annibale_goodix.c`、`annibale_focaltech_private.h` | 直接适用，解决 `annibale` 抬指与慢速滑动尾段偶发 80 ms 延迟 |
| `a3975b6` | 每 8 次滑动输出一次笔画级延迟统计（首点移动、采样间隔、抬指延迟） | `annibale_input.c` | 直接适用，提供内核侧实指触摸延迟汇总 |
| `539d35e` | 慢速帧直接用双线性过滤绘制，并在二次重绘前检查 `MiniIOSurface::drawn` | `MiniIOMobileFramebuffer.cpp`、`MiniFramebufferPacing.inc` | 直接适用，消除静止桌面时钟跳秒引起的画面抖动与复用表面半帧闪烁 |
| `3b9db78`（上半） | SpringBoard 主线程 RunLoop 慢帧栈采样线程 `stall_watch` | `inject_sb.c`（对应本仓 `inject_sb26_rate.c`） | 去掉 `arm64e` 指针签名（PAC）后直接适用，定位实指长按、滑动起手 100～300 ms 主线程阻塞 |
| `3b9db78`（下半） | CoreAnimation 着色器名称按汉明距离匹配 451 个预提取变体（`hm_ca_nearest`） | `hakios-metal/driver/HakiosMetalCA.m` | 本仓在 iOS 26 上直接编译 `MTLFunction` 内置 AIR 位码，已从根因解决，无需照搬变体表 |
| `f8976bc` / `9da1523` / `d18f6bd` | 多机型兼容性保护：`fb_intf` 显式开关、机型专属 `metal.args`、未知 GPU 芯片 ID 拒绝初始化 | `MiniIOMobileFramebuffer.cpp`、`hakios-metal/`、`tools/build.sh` | 本仓 `MiniFramebufferFlip.inc` 默认 `fb_flip=0` 已带保护，未知 GPU 拒绝策略可参考 |
| `95c956b` | 将 `hakios-metal/` 合入内核主仓单仓库构建 | `hakios-metal/`、`tools/build.sh` | 本仓 Metal 驱动已在 `hackios-xnu-kernel/tools/userland-driver/`，AIR 编译器在 `hackios-xnu-userland/tools/mesa/` |

## 2. 触摸抬指延迟与笔画统计（`81b5dd2`、`a3975b6`）

### 2.1 问题机理与上游改动

触摸线程 `poll_thread` 默认只在检测到 GPIO 中断线为低电平（或 `annibale` 的 TLMM 边沿锁存置位）时调用 `chip_poll()`，其余时刻每隔 `idle_looks` 轮做一次无条件轮询。

在本仓库当前的 `hackios-xnu-kernel/xnu/files/bsd/dev/annibale_goodix.c` 中：

- `idle_looks = 80000 / poll_us`，对应 80 ms 的空闲轮询周期（上游 `annibale` 改动前为 `160000 / poll_us`，对应 160 ms）。
- 手指按下并保持接触或慢速移动直到停下再抬起时，若芯片在上一帧被读取的瞬间更新了抬指状态（0 触点报告），或者单次下降沿在清锁存窗口内未被捕获，`poll_thread` 会等待整整一个 `idle_looks`（本仓 80 ms，上游 169 ms）才读出抬指报告。
- 手指抬起事件延后 80 ms 送达 `backboardd` 与 `SpringBoard`，会导致惯性滚动起手速度估算偏低、轻点（Tap）与长按（Long Press）判定拖尾。

上游 `81b5dd2` 与 `a3975b6` 做了三处改动：

1. 新增 `chip_touching()`，检查当前是否有任一触点处于 `contact[i].down == true` 状态；只要有手指按下，每一个 `poll_us` 周期（`annibale` 上为 4 ms）都无条件调用 `chip_poll()` 读取芯片，不再依赖 GPIO 中断线或 80 ms 空闲轮询周期。
2. 无手指按下时，将 `idle_looks` 从 `80000 / poll_us`（80 ms）缩短到 `16000 / poll_us`（16 ms），即使起手第一帧漏掉中断边沿，最坏延迟也控制在 16 ms 以内。
3. 在 `annibale_input.c` 中新增 `touch_feel_add()`，每完成 8 次单指触摸笔画（`DOWN -> MOVE... -> UP`）在内核日志打印一行汇总：`first move after X ms`、`moves Y ms apart`、`lift Z ms after last move`，直接量化实指操作在驱动层的采样间隔与抬指延迟。

### 2.2 对 K90（Goodix GT9916K）的验证与合入方案

本仓 K90 使用 Goodix GT9916K（`TOUCH_GOODIX`），芯片固件仅在新一帧坐标或抬指报告就绪时将 `touch_address` 首字节 `report[0]` 置为 `GOODIX_STATUS_TOUCH`（`0x80`），驱动读完后向 `touch_address` 写回 `0`。

在 `goodix_poll()` 中，若芯片尚未产出新帧，`report[0] == 0`，函数在第 319 行直接返回，不会清空 `contact[i].down` 状态；一旦手指抬起，芯片写入 `report[0] = 0x80, count = 0`，下一次 4 ms 轮询即可立即读出并发送 `ANNIBALE_TOUCH_UP`。因此 `chip_touching()` 按下期间每轮轮询对 Goodix GT9916K 完全安全，可直接合入 `annibale_goodix.c` 与 `annibale_input.c`。

## 3. 静止画面抖动与表面复用半帧闪烁（`539d35e`）

### 3.1 问题机理与上游改动

为降低滑动期间的 CPU 缩放耗时，`MiniIOMobileFramebuffer` 支持 `fb_filter=2`（滑动期间用最近邻插值快速缩放，静止满 `SETTLE_MS = 40 ms` 后由 `settle()` 用双线性插值重绘一遍）。

本仓当前 `hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferPacing.inc` 的 `fb_filter=2` 存在两处缺陷：

1. **静止桌面每秒 10 次画面微抖**：解锁进入主屏幕后，状态栏或时钟图标的定时刷新以约 10 fps（帧间隔约 100 ms，大于 `SETTLE_MS = 40 ms`）提交整屏帧。每一帧到达时先按最近邻插值绘制（抽掉第 25 列与第 67 行像素），40 ms 后 `settle()` 再按双线性插值重绘一遍。结果静止画面上的图标边缘与文字笔画每秒钟在最近邻与双线性之间来回跳动 10 次。
2. **手势起手时复用表面导致半帧闪烁**：`show()` 完成后立即唤醒 `SwapEnd`，CoreAnimation 随即回收该 `MiniIOSurface` 并让 GPU 往里渲染下一帧。若 40 ms 后 `settle()` 触发时下一帧已开始在同一个 `MiniIOSurface` 上渲染但尚未提交 Swap，`settle()` 会把正在渲染一半的表面重新缩放到屏幕上。

上游 `539d35e` 的修复方法：

1. 在 `IOMobileFramebuffer` 中记录连续快帧计数 `fFastFrames`：仅当上一帧距今不超过 `SETTLE_MS`（40 ms）时递增 `fFastFrames`，否则归零；只有从第 3 个连续快帧起（`fFastFrames >= 2`）才使用最近邻插值，单独到达的慢帧（如 10 fps 时钟刷新或手势最后一帧）直接一步使用双线性插值绘制，无需 40 ms 后二次重绘。
2. 在 `show()` 中记录每个图层表面展示时的 GPU 提交序号 `shownDrawn[layer] = surfaces[layer]->drawn`；40 ms 后执行 `settle()` 前，逐层核对 `surfaces[layer]->drawn == shownDrawn[layer]`，若 GPU 已经复用该表面启动了新提交，则立即放弃本次 `settle()`。

### 3.2 对 K90 的合入方案

本仓 `MiniIOSurface`（`MiniIOSurface.h` 第 66 行）已维护 `uint32_t drawn` 字段，`MiniFramebufferPacing.inc`（166 行）也已独立成文件。将该两项判定合入 `MiniFramebufferPacing.inc` 与 `MiniIOMobileFramebuffer.cpp`，可在保持 `MiniIOMobileFramebuffer.cpp` 零净增行的前提下彻底消除 `fb_filter=2` 下的静止抖动与复用闪烁。

## 4. SpringBoard 主线程慢帧栈采样（`3b9db78` `stall_watch`）

### 4.1 问题机理与上游发现

上游在排查实指滑动与长按偶发 100～300 ms 停顿时发现：内核触摸线程在 4 ms 内已将样本送入队列，但 `SpringBoard` 主线程在同一个 RunLoop 周期内耗时达到 100～325 ms 才调用 `CA::Transaction::commit()`。

为定位主线程在慢周期内具体执行的函数，上游在 `inject_sb.c` 中注册了主线程 `CFRunLoopObserver`（监听 `kCFRunLoopBeforeSources | kCFRunLoopAfterWaiting` 进入与 `kCFRunLoopBeforeWaiting | kCFRunLoopExit` 退出），并启动一个轻量后台线程 `stall_watch`：

- 仅在 `touch_lat=1` 开启时运行。
- 主线程单次 RunLoop 周期超过 25 ms 时唤醒，每隔 50 ms（25 ms、75 ms、125 ms……）挂起主线程约 20 µs，沿帧指针链（`fp`）回溯最多 14 层调用栈，通过 `dladdr` 解析符号名与偏移并写入 `kern.annibale.say`（输出 `tl: t <ms> <sym+off> <sym+off> ...`）。

### 4.2 对 K90（iOS 26 `arm64e`）的适配要点

这一诊断工具直接对应本仓当前正在排查的「长按、滚动、滑动偶发卡顿」。

在 K90 的 iOS 26.6.2（`arm64e`）环境下移植到 `hackios-xnu-userland/userland/src/inject_sb26_rate.c` 时，需要注意一处架构差异：

- 上游 iOS 16.5 运行在去掉 PAC 的 `arm64` 镜像上，栈帧中的返回地址 `frame[1]` 可直接传给 `dladdr()`。
- 本仓 iOS 26.6.2 运行在 `arm64e` 下，栈上保存的 `lr`（`frame[1]`）带有 `ptrauth_key_return_address`（IB 密钥）签名，传给 `dladdr()` 前必须先用 `ptrauth_strip((void *)frame[1], ptrauth_key_return_address)`（或掩掉高 16 位内核/用户态 PAC 位）剥离指针签名，否则 `dladdr()` 会匹配失败并只输出裸十六进制地址。

## 5. CoreAnimation 运行时着色器变体与壁纸/小组件渲染（`3b9db78` `hm_ca_nearest`）

### 5.1 上游在 iOS 16.5 上的问题与解法

在 iOS 16.5 上，上游 `hakios-metal` 使用从 `dyld_shared_cache` 离线提取的 451 个预编译 CoreAnimation 着色器变体（`HakiosMetalCA.m`）。主屏幕默认壁纸、状态栏下方阴影或桌面小组件请求运行时生成的着色器标签（格式 `T...B...D...A...S...L...X..._I...`，如 `B2_XC0` 双三次采样或 `S1` 源 alpha 预乘）不在 451 个预提取变体中时，旧代码回退到了 `backboardd` 内置 `default.metallib` 的唯一通用变体，导致默认壁纸顶部发红、状态栏下方出现白条、小组件内容缺失。上游 `3b9db78` 通过解析标签特征位并搜索汉明距离最近的预提取变体（`hm_ca_nearest`）修复了这一现象。

### 5.2 与本仓 K90（iOS 26.6.2）架构的对比

本仓 K90 在 iOS 26.6.2 上采用了不同的着色器编译路线：

- `hackios-xnu-kernel/tools/userland-driver/annibalemetal.m` 通过 `libannibaleair.dylib`（`air_to_nir.c`）在运行时直接将每个 `MTLFunction` 携带的完整 AIR 位码编译为 Adreno Gen8（A830）原生指令，并持久化到 `/var/db/annibale-pipecache-v5.bin`，不存在「只预提取 451 个变体、其余回退到错误变体」的限制。
- 本仓此前在 iOS 26 上遇到的桌面小组件黑块、壁纸色彩异常与图标模糊，根因分别是 AIR 指针 `phi` 节点未向后追踪空纹理绑定（已在 `hackios-xnu-userland/tools/mesa/air/air_ptr_phi.inc` 修复）以及单采样 `MultisampleResolve` 渲染通道未复制背景纹理（已在 `hackios-xnu-kernel/tools/userland-driver/annibalemetal_blit.inc` 修复）。
- 因此，上游的 `hm_ca_nearest` 变体近似匹配无需移植到本仓；其排查思路印证了保留完整 `MTLFunction` AIR 实时编译管线在 iOS 26 上的必要性。

## 6. 多机型兼容性保护与仓库结构（`f8976bc`、`9da1523`、`d18f6bd`、`95c956b`）

1. **DPU 接口寄存器读取保护（`f8976bc`）**：上游将 `MiniIOMobileFramebuffer` 中读取 `MDSS_MDP_INTF` 帧计数器的诊断代码放入 `fb_intf=1` 开关后，防止在未开启 DISPCC 时钟的 SoC 上触发总线挂起。本仓 `MiniFramebufferFlip.inc` 默认 `gFlip = 0`、`gDim = 0`、`gDcs = 0`，且在访问寄存器前先通过 `flip_clocks()` 检查 `mdss_gdsc` 与 `disp_cc_mdss_ahb_clk`，已具备同等保护。
2. **未知 GPU 芯片 ID 安全拒绝（`d18f6bd`）**：上游在 `HakiosMetalDevice` 初始化时校核内核汇报的 Adreno `chip_id`，若不在已支持列表则直接返回 `nil`，让 CoreAnimation 安全回退到 CPU 渲染而不触发进程崩溃循环。本仓 `annibale_adreno.c` 与 `annibalemetal.m` 已针对 A830（`chip_id = 0x44050000` / Gen8 `8030001`）做精确匹配。
3. **机型配置分离（`9da1523`）**：上游新增 `devices/<name>/metal.args` 存放各机型专属的 Metal/显示启动参数，构建脚本按机型加载。

## 7. 本仓执行结论

基于以上对比，本仓立即合入三项有直接收益的改进：

1. 在 `hackios-xnu-kernel/xnu/files/bsd/dev/annibale_goodix.c` 与 `annibale_input.c` 中合入 `chip_touching()` 按下期间每轮轮询、16 ms 空闲轮询以及 `touch_feel_add()` 每 8 次滑动延迟统计（对应上游 `81b5dd2`、`a3975b6`）。
2. 在 `hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferPacing.inc` 与 `MiniIOMobileFramebuffer.cpp` 中合入 `fFastFrames` 连续快帧过滤判定与 `settle()` 前的 `shownDrawn` 表面复用校验（对应上游 `539d35e`）。
3. 在 `hackios-xnu-userland/userland/src/inject_sb26_rate.c` 中合入适配 `arm64e` PAC 剥离的 `stall_watch` 主线程慢帧采样器（对应上游 `3b9db78`），用于捕获实指滑动与长按时的 SpringBoard 主线程阻塞调用栈。
