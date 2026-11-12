# 方案架构审查与全面建议（2026-11-08）

本文是一次离线的架构审查与建议汇总：没有操作设备，没有构建，只读顶层仓库文档、两个子模块在进度跟踪记录的提交（内核 `4d8d9b9`、用户态 `5a7ac77`）以及上游与同类项目的公开提交历史。标注「推断」的内容没有直接读数或源码出处，执行前需要核实。用户决定保留在 §21，后续任务与验收按[待办目录](../backlog/README.md)维护。

后续事项按[系统](../backlog/system.md)、[图形](../backlog/graphics.md)、[多媒体](../backlog/multimedia.md)、[外设与电源](../backlog/platform.md)、[工程](../backlog/engineering.md)分别维护。

全文分四部分：§1～§3 是宏观判断与分层架构；§4～§9 是图形、显示、GPU、着色器、输入与正确性的逐层建议；§10～§15 是外设、启动、电源、存储、网络等其他子系统；§16～§20 是工程流程、文档、风险、上游与待决事项。

## 1. 总体判断

主干路线是对的，不建议推翻。iOS 26.6.2 加 `xnu-12377.121.6`、iPhone 17 身份、完整原版三容器系统卷从 UFS 按需读取、`ANNFS001` 内核直写 `darwin_var`、`xnuloader` 双系统，这几项都已在真机跑通，且与上游后来的走向一致（上游 11-03 试过 Turnip 加 metal2vulkan，测得比直连驱动慢一半，仍回到自有驱动）。

真正的结构性风险集中在四处：

- 图形管线里有三段「CPU 在环」与一个未查明的正确性缺陷（局部重绘残留），后者迫使整帧重画，占用了约四成 GPU 预算并造成静置发热（§4）。
- 渲染正确性依赖 AIR→NIR 翻译器与 freedreno 补丁层，但没有按「材质／玻璃」着色器家族组织的回归样本，问题只能逐个真机复现后再修，用户看到的顶栏、搜索栏、状态栏颜色错就是这一类（§8）。
- R2～R8 几轮「多 Worker 批量集成」一次落地几十处改动，大部分标为「待真机复核」，并已经引发过两次整机级回归（未签名注入库、ADSP DMA 覆盖 Wi-Fi 控制环）。验证债务已经超过验证能力（§16）。
- 注入库里仍有伪造硬件能力的钩子，最直接的例子是 SpringBoard 里把 `CHHapticEngine` 的 `supportsHaptics` 固定为 NO，这与 [AGENTS.md](../../AGENTS.md) §6 冲突，也让震动在 iOS 26 上无论内核修到什么程度都不可能生效（§10.1）。

一句话的宏观建议：**接下来一到两个月把「正确、流畅、稳定」做扎实，把外设扩张的节奏降下来。** 具体是三件事：查清脏区残留让 CoreAnimation 回到原生脏区绘制、建立材质着色器回归样本集中解决颜色问题、把未验收子系统从默认镜像里关掉。做完这三件，再按 §19 的顺序推进外设。

## 2. 项目定位与阶段目标

现在的文档里有路线图与进度跟踪，但没有一份写明「这个项目要做到什么程度」的定位。定位不清会让每一轮都在「多修一个外设」与「把现有的做好」之间摇摆，R 轮的膨胀就是结果。建议明确写下三档目标，并把当前阶段定在第一档：

| 档 | 名称 | 定义 | 当前距离 |
|---|---|---|---|
| A | 可信演示 | 桌面与系统应用正确、流畅（120 Hz 手势长帧比例低于 5%）、能跨开机保留数据、能安全切回 Android；无颜色错、无残留、无卡死 | 流畅度接近，正确性与稳定性未达 |
| B | 日用雏形 | 在 A 之上加声音、震动、相机预览与拍照、蓝牙音频、充电正常、时间准确、第三方应用可装可用 | 大部分未通 |
| C | 日用 | 在 B 之上加蜂窝、短信、电话、定位；App Store 不作目标（§12.6） | 未开始 |

每一档的「完成定义」要写成判据表，由无人值守脚本能判的项和必须人在场确认的项分开。路线图 §7 已有一部分，建议扩成按档分列。

## 3. 分层架构与「修在哪一层」的规则

### 3.1 现有分层

| 层 | 位置 | 职责 |
|---|---|---|
| 引导 | `hackios-xnu-kernel/xnuloader/`、Mu-Silicium UEFI | 双系统菜单、载荷装载、槽位与 GPT 维护、故障横幅 |
| 内核平台层 | `xnu/files/osfmk/arm64/`、`xnu/files/pexpert/` | SoC 启动、中断、时钟、PSCI、看门狗 |
| 内核设备驱动 | `xnu/files/bsd/dev/adreno8/`、`bsd/dev/annibale/` | GPU、触摸、按键、电池、ADSP、蓝牙、Wi-Fi、UFS |
| IOKit 替身 | `xnu/files/iokit/Kernel/Mini*.cpp` | 面板、IOSurface、背光、密钥库、网络栈的最小实现，对齐 iOS 框架期望的服务树 |
| 文件系统与持久化 | `xnu/files/bsd/miscfs/ramfs/`、`annibale_ufs*` | `ANNFS001` 直写、UFS 块设备、APFS 只读 |
| 用户态驱动 | `hackios-xnu-kernel/tools/userland-driver/`（Metal）、`hackios-xnu-userland/tools/mesa/air/`（AIR 编译与 Gallium 状态） | Metal 接口到 GPU 命令流 |
| HAL 与服务替身 | `userland/src/services/`（音频 HAL 插件、相机 FigCaptureDevice、输入服务） | 为 iOS 守护进程提供硬件供应商侧的实现 |
| 注入库 | `userland/src/inject/` | 进程内替换：供应商类、诊断、测试辅助 |
| 构建与打包 | `userland/build.sh`、`tools/k90auto/package.py`、`mkjobs.py` | 系统盘、根盘、任务缓存、启动参数 |
| 主机自动化 | `tools/k90auto/` | 起轮、截图、统计、复位 |

### 3.2 建议写死的规则

- **注入库只允许三类用途**：替换 iOS 期望由硬件供应商提供的类（FigCaptureDevice、蓝牙 `bluetool` 替身）；纯诊断（图层导出、速率日志、慢帧栈采样）；测试辅助（自动解锁、合成触摸）。改视图颜色、伪造能力查询、伪造授权结果、改网络可达性都不属于这三类。
- **诊断与测试类注入默认不进 `boot_a` 镜像**，只随 `cycle.py` 的跑轮载荷打包。现在两者共用 `package.py` 的 `INJECT` 列表，建议拆成 `INJECT_SHIP` 与 `INJECT_TEST`。
- **每个硬件能力只在一层实现**：震动在内核驱动加 HAL Actuator，不在 SpringBoard 里拦；亮度在 `MiniAppleARMBacklight` 加 DCS，不在设置里改滑块；网络可达性由内核网络栈与 `configd` 决定，不在应用里重绑定。
- **Mesa 补丁分三类并在文件名里标明**：移植适配（26.x 接口变化、Darwin）、硬件修复（A830 已确认的缺陷）、诊断（计时、探针）。诊断类不进默认构建。

### 3.3 缺一份架构总览文档

仓库没有一份独立的架构文档，新接手者要从 README、路线图、几十篇 analysis 里拼。建议新增 `docs/plan/architecture.md`，内容就是 §3.1 的分层表加每层的入口文件、对外契约（iOS 框架期望的 selector、属性、设备节点）和「修在哪一层」的规则；各 analysis 文档只保留实测数据，不再各自解释一遍架构。

## 4. 图形管线：现状与开销归因

### 4.1 一帧的路径

| 阶段 | 实现位置 | 性质 |
|---|---|---|
| CoreAnimation 合成（backboardd） | iOS 原生 | GPU 命令由 Metal 接口下发 |
| Metal 驱动 | `hackios-xnu-kernel/tools/userland-driver/annibalemetal.m`（5420 行）及 `.inc` | 把 Metal 对象映射到 Gallium 状态 |
| AIR 编译与状态层 | `hackios-xnu-userland/tools/mesa/air/`（`air_metal.c` 6782 行、`air_to_nir.c` 3461 行） | AIR 位码→NIR→ir3，运行时编译 |
| Gallium freedreno a8xx | Mesa 26.2.5 加 `tools/mesa/rebase-26/` 17 个补丁 | GMEM 分 bin 渲染，命令流生成 |
| 内核 GPU 服务 | `xnu/files/iokit/Kernel/AnnibaleGPU.cpp`、`xnu/files/bsd/dev/adreno8/` | 提交经 HFI 交给 GMU |
| 上屏 | `xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp` 及 `MiniFramebuffer*.inc` | **CPU** 把 1206×2622 缩放拷进 1156×2510 面板内存，再换扫描地址 |

上屏一段决定了几个硬约束。显示控制器只被用来换地址（`fb_flip=2`），缩放、逐行哈希、脏行判定都在 CPU 上由两个内核线程完成；`fb_queue=1` 下 `SwapEnd` 要等上一帧拷完，相邻两帧共用两拍预算。这是 [120 Hz 卡点分析](2026-11-01-120hz-gesture-bottleneck.md) §6 已经量到的链路。

### 4.2 时间花在哪里

| 项 | 读数 | 出处 |
|---|---|---|
| backboardd GPU 时间中整屏合成 pass 占比 | 约 87%，其中 tile load／store 原各占两成，补丁 0009／0010 后 load 降约六成 | [GPU 升频之后的长帧](2026-11-02-120hz-after-gpu-clock.md) §6 |
| 整帧重画 vs 脏区 | 整帧重画的 GPU 时间多 72%（`bo49` 对 `bo47`） | `tools/k90auto/package.py` `DIRTY_REGIONS` 注释 |
| 画布 1206×2622 对 1125×2436 | 像素多 15.4%，控制中心下拉 106 → 88 帧／秒 | [状态栏布局分析](2026-11-02-status-bar-layout.md) §6 |
| CPU 缩放拷贝 | 手势期间每帧 3.0～7.3 ms 驱动内时间 | [GPU 升频之后的长帧](2026-11-02-120hz-after-gpu-clock.md) §5 |
| 每次提交的派发延迟 | 约 0.7 ms，与 GPU 忙闲无关，原因未查 | 同上 §3 |
| 静置 | 主屏时钟图标 10 Hz 触发整屏重绘，每秒约 20 次整屏 pass | [11-06 清单](../plan/2026-11-06-issues-and-followup.md) §1.15 |
| 其他进程抢 GPU | 手势窗口里壁纸扩展 519 ms、iconservicesagent 297 ms | [GPU 升频之后的长帧](2026-11-02-120hz-after-gpu-clock.md) §4 |

把这些放在一起看：手势里 GPU 时间超过一拍的帧，主要是整屏 pass 本身大；整屏 pass 之所以每帧都要画，是因为 `CA_DISABLE_DIRTY_REGIONS=1` 还在默认参数里。性能路线的第一优先级是把脏区重绘的正确性缺陷查清，让 CoreAnimation 回到只画变化区域的原生行为，暂不继续调频或省 tile store。

### 4.3 用户反馈的四个场景怎么对应

| 场景 | 更可能的机制 | 建议先采的数据 |
|---|---|---|
| 多任务界面卡顿 | 每张应用快照是一块线性 IOSurface 纹理，叠加 `CABackdropLayer` 模糊（compute 下采样）与玻璃材质，一帧多个 pass 加多次提交；每次提交各付 0.7 ms 派发延迟；首次进入还要编译该场景的管线 | 打开 `ANNIBALE_PASS_TIMES=1` 在多任务手势里采 5 秒，记每帧 pass 数、compute 派发数、提交次数与建管线次数 |
| 设置底部搜索栏背景色不对 | Liquid Glass 材质：`CABackdropLayer` 加合成滤镜，着色器用 framebuffer fetch 混合，再叠 sRGB 或 10 位 XR 附件 | 见 §8 的格式与混合核对 |
| 顶栏颜色经常不对 | 同上，导航栏的 `_UIBarBackground` 是材质视图；此前曾被钩子涂白，钩子已删，现在剩下的是驱动一侧的问题 | 同上 |
| 状态栏颜色不对 | 状态栏的易读性渐变带合成滤镜（上游在 iOS 16.5 上见到同一症状：`darkenSourceOver` 渐变画成纯白） | 用 `inject_sb26_layers.c` 的图层导出列出状态栏窗口的 `compositingFilter`，再核对驱动对该滤镜对应混合状态的映射 |

上游把状态栏变白与壁纸顶部发红归到一个根因：CoreAnimation 运行时生成的管线落到了错误的着色器变体（上游内核仓库 `3b9db78`）。本项目直接编译每个 `MTLFunction` 自带的 AIR，无变体选择问题；同一症状在这里更可能出在格式替换、混合状态映射、framebuffer fetch 与附件读写策略这四处，§8 逐一列出。

### 4.4 脏区重绘残留的排查方向

「局部重绘留下旧内容」目前只有现象没有归因。结合代码里已有的三处机制，建议按下面顺序排除：

- 导入资源的 shadow 已由补丁 0011 禁止，但 `fd_resource_contents_undefined()`（0009）对 `Load` 附件是否会被误标，尤其是同一 IOSurface 在同一帧被两个 pass 先写后读时。
- `MiniFramebufferRows.inc` 的逐行哈希与脏行覆盖在 CoreAnimation 只提交脏矩形时是否仍按整帧比较（两个脏矩形之间的行未变，但 CoreAnimation 认为显示内容已经是新帧）。
- `fb_flip=2` 双缓冲下，脏区只写进了当前缓冲，上一帧的缓冲没有同步该区域，翻转后露出旧内容。这一条与症状「切一次控制中心就好了」最吻合，也最容易验证：`fb_flip=0` 加 `DIRTY_REGIONS=1` 跑一轮看残留是否消失。

## 5. 显示与上屏路径

### 5.1 现状的问题

- CPU 缩放是每帧固定成本，且与 GPU 完成串行；`fb_queue=1` 把两帧的预算绑在一起。
- 「vsync」使用软件定时器，未接显示控制器中断；CoreAnimation 拿到的节拍与真实扫描无关，`fb_beat=0` 用「GPU 完成即上屏」绕开了这点，但撕裂与节拍偏差没有被测量。
- 面板物理分辨率是否为 1200×2608 未核实（[状态栏布局分析](2026-11-02-status-bar-layout.md) §6.2），现在可能存在两次缩放。
- 息屏没有真正关闭面板与显示控制器（推断：关机路径有 `dim_poweroff()`，但日常锁屏息屏的功耗路径没有文档），静置功耗由此偏高。

### 5.2 方向

1. **DPU 缩放零拷贝上屏（结构性修复）。** 让 GPU 输出缓冲直接成为 SSPP 的源，由 QSEED 缩放到 1156×2510，撤掉 CPU 缩放线程与 `fb_queue=1` 串行化。需要：给 DPU 配 SMMU 映射或让 IOSurface 在连续内存里分配；按 Linux `drm/msm/disp/dpu1` 的 sspp／lm／ctl 路径编程；处理 `fb_flip` 已经在用的地址切换与新的缩放配置的原子提交。风险是显示 underflow 与总线投票（DPU 的带宽要向 RPMh 投票）。
2. **真实 vsync。** 用 INTF 的 vsync 中断或 `INTF_FRAME_COUNT` 驱动 `kFBNotifyVSync`，让 CoreAnimation 的节拍对齐扫描；配合 1 可以把 `fb_beat` 的绕过撤掉。
3. **`SwapWait` 与三缓冲（过渡方案）。** 在 1 之前先实现 `SwapWait`（约 150 行，上游同类项目有参考），让 `fb_queue=2` 可用，两帧预算放宽到三拍。要先解决 iOS 26 的 CoreAnimation 只在两块 surface 之间轮换的问题。
4. **核实面板原生分辨率。** 读面板驱动芯片的 DSI 时序，确认 1200×2608 还是 1156×2510；若是前者且能切模式，画布 1206×2622 与面板只差 0.5%，可以少一次缩放。
5. **息屏功耗路径。** 锁屏息屏时关背光、让 DSI 进低功耗、停掉 CPU 缩放线程与 GPU 空闲档，恢复时按原路回来。这是「静置发热」的另一半。

## 6. GPU 驱动与内核提交路径

- **提交派发延迟 0.7 ms。** 每帧多次提交时成倍计入。方向是看 HFI 门铃到 GMU 取走消息之间的路径（`adreno8_hfi.c`），以及是否每次提交都走了一次 GMU 消息队列而未直接写环形缓冲的 `wptr`。
- **提交合并。** `fd-submit-merge.patch` 已把合并上限放到 64 条命令；多任务界面这种多 pass 场景可以再看每帧提交次数能否压到 1～2 次。
- **GPU 优先级队列。** 上游与本项目都量过，backboardd 排在壁纸扩展之后的比例约 9%，收益上限小，暂不做。但如果 §7.3 的壁纸策略不被接受，这一项可以重新评估。
- **ACD 与更高档位。** 现在没有 ACD 表却跑到 1100 MHz，同 SoC 的 UniXNU-Pagani 项目 11-07 做了「更高动态频率加分档温控」，可对照其时钟表与 ACD 数据（先核许可证）。
- **空闲档位与 `adreno8_keep=1`。** 空闲回落到 342 MHz 是合理的；静置发热主要来自整帧重画。脏区修好后再量一次空闲功耗，决定是否需要更低的空闲档或 GMU 的低功耗状态。
- **UBWC 纹理。** 合成器读的都是线性 IOSurface，整屏 pass 的 tile load 就是带宽。freedreno a8xx 支持 UBWC 布局，但 IOSurface 在内核侧分配，需要内核与驱动约定布局并让 CPU 侧（截图、CPU 缩放）能读。放在 §5 的零拷贝之后，因为零拷贝之后 CPU 不再读这块内存，UBWC 的约束会简单很多。
- **GMEM 自动调优。** gallium 的 a8xx 已有 GMEM／sysmem 自动选择；本项目 `sm1` 轮证明默认 sysmem 更慢。保留现状，但多任务场景可以单独量一次 autotune 的选择是否合理。
- **GPU 故障诊断。** 现在 GPU 挂起靠看门狗与复位；建议补一条「挂起时转储最后一次提交的命令流与寄存器快照」的路径，减少真机窗口的消耗。

## 7. 着色器编译、缓存与其他进程

### 7.1 编译成本

运行时编译链是 AIR→NIR→ir3，每条管线首次出现时在 backboardd 的提交线程上编译（是否在渲染线程上没有核实）。`annibale-pipecache-v5.bin` 与 M1 的 `annibale-aircache` 已落地，但没有「第二次开机后编译次数」的读数。首次进多任务、首次打开控制中心的卡顿很可能就是运行时编译。

建议：

- 先量：开机后 5 分钟内 backboardd 与 SpringBoard 的建管线次数与总耗时，第二次开机再量一次。两次相同就是缓存没生效。
- 缓存键要包含 AIR 库与 Mesa 的 UUID（补丁 `0015-ir3-disk-cache-darwin-uuid` 已朝这个方向），否则换库后会命中错误的二进制。
- 构建期预编译：用户 10-28 已允许「把翻译挪到构建期」。可行做法是把真机日志里出现过的全部管线描述收集成清单，在构建根盘时预编译并作为缓存种子放进镜像；上游 11-02 的「compiled stages seeded into the image」就是这条路。
- 编译线程与渲染线程分离：若核实编译确实在渲染线程上，把编译放到独立线程并在首帧用异步管线创建（Metal 本身支持 `newRenderPipelineStateWithDescriptor:completionHandler:`）。

### 7.2 AIR 翻译器的完整性

AIR 翻译器是本项目最独特也最脆弱的一层。目前的失败模式是「遇到不认识的 intrinsic 或构造就拒绝整条管线」，CoreAnimation 建不出管线就终止进程（`bo18` 的 `fmax3.f16`）。建议：

- 把 23G90 的 QuartzCore、CoreImage、UIKit 的 metallib 全部离线跑一遍翻译器，列出所有拒绝项，作为一张「覆盖率表」维护；每修一项消一行。这比等真机踩到再修快得多。
- 给翻译器加 fuzz 级别的回归：同一 metallib 在宿主用 Apple 的编译器与本翻译器各编一遍，比较反汇编的指令数与寄存器数，差异过大的标红。
- 当前 `air_metal.c` 6782 行、`air_to_nir.c` 3461 行，按 intrinsic 族、类型系统、接口（render_target、argument buffer）、采样器拆文件，否则多人同时修会持续冲突。

### 7.3 其他进程的 GPU 占用

- 壁纸扩展 MercuryPosterExtension 在手势窗口占 519 ms GPU，是 backboardd 之外最大的单项。有两个可选策略：换静态壁纸做对照（改变用户体验，需用户决定）；或在 `/private/var` 的壁纸配置里把默认壁纸换成静态图（不改系统镜像，只改种子）。
- iconservicesagent 297 ms：图标首次生成是一次性成本，但「每次开机都是首次开机」的问题若复发会让它每次都付。确认 `/private/var` 直写后图标缓存已跨开机保留。
- SpringBoard 自己 69 ms：可忽略。

## 8. 渲染正确性：可疑契约偏差与回归样本

### 8.1 四处可疑的契约偏差

1. **高精度格式被替换成 8 位。** `MiniIOSurface.cpp` 把 `w30r`／`l10r`／`w30R`／`b3a8` 建成 `BGRA`，驱动的 `ann_canonical_pixel_format()` 再把 Metal 格式 94 与 550～555 映射为 80／81。94 是 `BGR10A2Unorm`；公开 XR 枚举为 552／553 `BGRA10_XR`、554／555 `BGR10_XR`，553／555 的 sRGB 属性已有 SDK 定义，550／551 的私有契约待确认。CoreVideo 的 32 位 RGB、64 位 ARGB 与独立 alpha 平面需要分别实现。当前材质的实际格式分布，以及格式替换与颜色异常的关系仍待测量。先验证普通纹理和 buffer-backed 纹理对格式 94 的不同处理，再核对 XR 布局与扩展范围，见[系统契约核查 §7](2026-11-12-system-contracts.md#7-高精度像素格式的下一项测试)。
2. **framebuffer fetch 的降级路径。** `air_to_nir.c` 把 `air.render_target` 输入翻成 `fb_fetch_output`，Mesa 再降成 `txf_ms_fb`；补丁 0016 用常量图层 0 绕过了 VPC 脏寄存器。这是个合理修补，但 A830 上 fb fetch 在 GMEM 多 bin 与两个颜色附件下的一致性没有专门测试，而 iOS 26 的材质着色器大量依赖它。
3. **附件读写策略的两条补丁有正确性前提。** 0009 把 `MTLLoadActionDontCare` 附件标为内容无效、0010 跳过 `colormask=0` 附件的写回，两者都假设 CoreAnimation 之后不再读这块附件。整屏 pass 的第二个 RGBA16Float 附件正是材质路径可能回读的那块；若某些 pass 确实回读，就会出现「局部区域颜色错、切换控制中心后又对」这种状态依赖的症状。建议做一次 A/B：关掉 0009／0010 跑同一组截图，看搜索栏、顶栏、状态栏是否变化。
4. **混合状态映射。** `air_metal.c` 第 5251 行附近注明某些混合操作按 `max(Cs, Cd)` 处理而忽略因子；合成滤镜（`darkenSourceOver`、`sourceAtop`、`plusL` 等）全靠混合状态与双源混合表达，任何一项映射不精确都会表现为「颜色老是不对」。

另有两处值得核对：sRGB 附件是否由硬件做编码而未在着色器里手算（Gallium 的 `PIPE_FORMAT_*_SRGB` 在 a8xx 上的支持状态）；MSAA 默认关闭（`MSAA=0`）后 CoreAnimation 对 `supportsSampleCount:` 的回答是否让它选了另一条绘制路径。

### 8.2 建立材质着色器回归样本

现在的做法是真机复现一个修一个，每个修复配一组宿主检查。建议把它升级为一套按着色器家族组织的离线回归：

- 从 23G90 的 QuartzCore `default.metallib` 与 CoreImage metallib 提取玻璃、背景模糊、合成滤镜、SDF 文本这几族着色器及它们在真机日志中出现过的管线描述（附件格式、混合状态、load／store）。`ANNIBALE_PASS_LOG=1` 已经能记录附件格式与读写方式，补上管线与混合状态就是完整的回放描述。
- 宿主侧用 Mac 原生 Metal 渲染同一输入得到参考图，设备侧用现有 `userland/src/tests/metal_drv_test.m`（7799 行）跑同一描述，做像素差。
- 每条 rebase-26 补丁与 `ann_canonical_pixel_format()` 这类替换都要在这套样本上过一遍，再进默认参数。

这套样本一旦建立，§8.1 的四条可疑点会在一个下午内得到证实或排除，之后再改 AIR 或 Mesa 补丁也有护栏。

### 8.3 截图判读的自动化

现在异常截图的判据只有「GMEM 分 bin 边界下方出现状态栏蓝色块」一条，其他要人看拼图。建议为固定场景（主屏、设置一级页、设置搜索、控制中心、多任务）各存一张经人工确认的基准图，每轮做结构相似度比较，差异超过阈值的标出区域；颜色类问题会被直接抓住。

## 9. 输入与主线程

- 触摸已到 4 ms 采样与 9.3 ms 事件间隔，上游 11-05 的「按下期间每轮轮询」与「16 ms 空闲轮询」在 11-06 对照里已建议合入，建议确认是否已上机。
- SpringBoard 主线程慢帧栈采样（上游 `stall_watch`，arm64e 需剥 PAC）同样在 11-06 对照里，是定位「拖图标断触」「起手卡 100～300 ms」的直接工具，优先级应高于再加帧率探针。
- 拖图标跨页断触已归因到后台触摸注入工具与 Goodix 单帧漏检；修复后要在真机用真手指复核一次，合成触摸测不出这类问题。

## 10. 外设：震动、手电、相机

### 10.1 震动

事实链有三条：

- iOS 16.5 上 `hv_haptic=4` 经 AnnibaleAudio 的「Actuator」设备驱动马达已通过，见[手电与震动实测](../progress/2026-10-26-torch-and-haptics.md) §6。
- iOS 26 上故障寄存器 `0x10`（UVLO）清不掉；R2 M3 加了 UVLO 清除与 `0xf246` 升压使能，但未上机。
- `hackios-xnu-userland/userland/src/inject/inject_sb26.c` 的 `install_haptic_hooks()` 把 `CHHapticEngine` 的 `capabilitiesForHardware` 改成 `supportsHaptics=NO`、`supportsAudio=NO`，`start`／`stop` 直接返回成功。

判断：这个钩子是为了避免 SpringBoard 主线程被触感引擎阻塞而加的表象绕过，但它截断了 CoreHaptics→audiomxd／HAL「Actuator」→`/dev/annibale-haptic` 的原生路径，内核修好也没有波形送到。建议：

- 删除该钩子，把阻塞问题还原到 HAL 插件（`userland/src/services/audio_plugin.c`）的 Actuator 设备属性与 I/O 启动上去解决；`AUDIO=1` 已是默认，正好与扬声器 `AudioQueueStart=-66681` 的排查共用同一套 HAL 契约。
- UVLO 故障按原厂 `qcom-hv-haptics` 的上电顺序核对：先使能升压并等待就绪，再配置 VMAX 与波形，最后清故障；现在的顺序是先清故障再直驱。
- 验收仍分两段：无人值守看故障寄存器为 0 且 HPWR 变化，震感由用户在场确认。

### 10.2 手电

iOS 26 上读 `0x0018` 报「传输被丢弃」，R2 M3 加了重试容错但未复核。SPMI 仲裁器在 iOS 26 内核里多了电池、充电、传感器几个并发使用者，建议先核对仲裁器通道的互斥与「只映射用到的通道」策略在多使用者下是否仍成立（10-26 的 panic 教训），再看手电本身。

### 10.3 相机

当前树里有两套相机代码：`xnu/files/bsd/dev/annibale/annibale_camera.c`（4269 行，SM7375 可用的裸寄存器方案）与 R6 盲写的 `xnu/files/bsd/dev/annibale/annibale_camera.c`（1134 行，OV50E／CSID TPG，含 Iris 占位），后者没有任何真机读数；R8 又发现注入库未签名，此前「0 个摄像头设备」的结论源于注入未加载，与相机代码本身无关。

[相机路线](../plan/camera-plan.md)的分级与放弃准则仍然成立，建议严格按它执行，停止在 R 轮里批量加代码：

- 第一步不碰 CAMSS：确认签名后的 `libannibale-media.dylib` 在 `cameracaptured`／`mediaserverd` 里加载，用假的 TPG 流让 `FigCaptureDevice` 枚举出一个设备、Camera.app 预览出彩条。这一步只涉及用户态与 iOS 26 的进程归属（16.5 是 mediaserverd，26 要核对 `cameracaptured`）。
- 第二步才是 L1a 的 CPAS／camcc／csid-lite／ife-lite 通路，每一步读回报错，不靠多模块一次落地。
- vendor 的 `com.qti.sensormodule.*.bin` 仍是 L1b 的门；手机下次在 Android 时取出，放入忽略目录。
- `annibale_camera.c` 与 `annibale_iris.c` 在默认启动参数里保持关闭，直到各自第一项真机读数出现。
- 软 ISP（`camera_isp.c`）是 CPU 路径，预览分辨率要压低；拍照走全幅单帧可以接受。长期可以把去马赛克与色彩矩阵写成 compute 着色器交给 GPU，但这是 L2 之后的事。

## 11. 外设：音频、蓝牙、传感器、USB

### 11.1 扬声器与麦克风

DSP 侧 OPEN／PREPARE／START 已成功，卡在 AudioQueue 到 HAL 的启动（`-66681`），HAL 三项接口修复后仍在。这与 §10.1 一样属于 HAL 插件契约，建议合并成一个「HAL 插件对齐」工作项：

- 用 `sound_test` 探针固定复现，逐项对照 iOS 26 的 audiomxd 对 HAL 插件的属性查询序列（反汇编 `audiomxd` 与 `CoreAudio` 的插件加载路径），把插件缺的属性与错误的返回值一次列全。
- 首次 `GET_SPF_STATE` 偶发 250 ms 无回复已改为 5 秒期限，但要记录真实回复延迟分布，确认是 DSP 冷启动还是 GLINK intent 分配的问题。
- 麦克风（`annibale_mic.c`）与扬声器共用 AudioReach 图，扬声器通了再做录音路径。

### 11.2 蓝牙

HCI、BLE 扫描、配对基础已通；音频路由要 A2DP／HFP 的 SCO 或 LE Audio，走 `bluetoothd` 与 `audiomxd` 的 Skywalk 通道，依赖 §11.1 的 HAL 对齐。建议排在扬声器之后。

### 11.3 传感器

加速度、陀螺、距离、光线在高通平台上经 ADSP 传感器核心（SSC）用 QMI 协议访问。R6 的 `annibale_sensors.c` 走的是 QUP I2C 直读，并引发过 XPU SError。建议路线改为：ADSP 已经为音频启动，传感器复用同一 GLINK 通道加 QMI 编码，通过内核发布 iOS 期望的 IOHID 传感器服务（`AppleSPU` 风格）。这条路比直读 I2C 长，但与原厂拓扑一致，也不会与 ADSP 争总线。

### 11.4 iOS 侧 USB 设备模式

目前 USB 只给 loader 调试用，iOS 运行时没有设备模式。这是一个高杠杆项：有了 `usbmuxd`／lockdown 路径，日志、截图、安装应用、崩溃报告都能走 USB，不再依赖 loader 的日志环与 `oem sh`。同 SoC 的 UniXNU-Pagani 项目 11-07 起在做 DWC3 设备模式，可以对照其寄存器序列。电池驱动对 `DCTL.RUN_STOP` 的误判也会随设备模式驱动一起理顺。

## 12. 其他系统能力

### 12.1 Weather、Maps 与 FairPlay

`fairplayd.H2` 找不到 `com_apple_driver_FairPlayIOKit` 而退出，天气 JWT 签名走 Mescal→FairPlay。这属于要不要在内核里提供 FairPlayIOKit 服务的决策，涉及内容保护实现的边界。建议作为单独议题请用户决定范围，不与网络排查混在一起；在决定之前，Weather／Maps 从待办里摘出，避免反复排查网络。

### 12.2 视频硬解

Iris 已改为如实返回不支持，VideoToolbox 走软解并有 12 帧像素校验，这是正确的「不伪造」状态。真实 HFI gen2 会话是大工程，排在图形与音频之后。软解的 NV12 上屏路径（format 500）已有修复候选待上机，先完成该项验证。

### 12.3 时间

PMK8550 秒计数加 Android `persist` 偏移是合理的来源。要补的是网络校时（`timed`）是否生效与跨重启精度的读数，以及时区的来源。

### 12.4 语言、字体、通知

中文名称、网页字体、通知授权弹窗三项都有修复待复核。通知授权一项要特别核对实现方式：如果是在应用里拦截 `UNUserNotificationCenter` 的授权请求，属于 §3.2 禁止的伪造授权；正确方向是让 `usernoted`／`bulletindistributord` 的授权存储在 `/private/var` 里真的落盘。

### 12.5 应用安装与第三方应用

TrollStore 与 `trollstorehelper` 已能装解密的 IPA。几点建议：主屏删除要走 `installd` 或容器卸载，不能只删图标；暂存目录监听建议加上容量与频率上限；LiveContainer 与 SideStore 需要 JIT 或签名绕过，在本内核（无 trust cache、ad-hoc 授予平台二进制标记）上大概率能跑，但要单独记边界。

### 12.6 App Store 与蜂窝

App Store 需要 Apple ID 登录、设备激活与 FairPlay 解密，涉及与 Apple 服务的真实认证，建议明确写为「不作目标」，用侧载替代。蜂窝要 MPSS 启动、QMI 通信，再加一个把 QMI 翻译成 CommCenter 期望的 Apple 基带协议的守护进程，是独立于图形的大工程，放在 C 档。

## 13. 启动、持久化与稳定性

- **开机到可交互的时间。** 用户反馈过图标约一分钟才出现。建议在日志里固定打三个时刻：首帧、图标齐全、首次触摸有响应，并列出这段时间里 CPU 最忙的进程。开机种子（`var.seed`）与跨开机缓存都是为缩短这段时间服务的，要有读数证明。
- **`ANNFS001` 的健壮性。** 已有双槽轮换、主槽失败回退备槽、容量夹紧。建议再加：开机时对元数据做一次完整校验并记录结果；异常复位（看门狗、panic）后的恢复要有专门的测试轮；写入放大与闪存寿命做一次估算（每 1.5 秒一次元数据同步，几十 MiB 的槽位）。
- **崩溃现场。** `KLOG` 16 MiB 硬件直写与 panic 红屏横幅已落地，是正确方向。建议把 `ReportCrash` 的输出目录也放进直写范围，让用户态崩溃跨重启可取。
- **看门狗与关机。** 关机路径已补喂狗与跳回 loader；建议加一个「关机 30 秒内没走完就记录卡在哪一步」的探针，避免再出现 1 分钟黑屏后红屏。
- **内存。** 完整系统卷下空闲约 6.2 GiB，充裕。zone map 16 GB 与压缩池 4 GB 的配置暂不动，但多任务下的压缩与换页行为可以采一次。
- **页大小。** iOS 用户态按 16 KiB 页假设的代码路径（共享缓存映射、`vm_page_size` 查询）与内核实际页大小是否一致，没有在文档里见到核对记录；若内核是 4 KiB 页，某些 mmap 与 `IOSurface` 对齐问题会间歇出现。标为推断，建议核对一次。

## 14. 电源、充电与温控

- 充电属性已对齐小米 MCA `pmic_glink`，拔线状态改为看 VBUS 与电流方向。待复核项是快充协商（PD／PPS 由 ADSP 侧做，内核只下发限流）与电脑 USB 下的掉电。
- 温控现在是内核自有的分档策略（CPU 70／75 °C，GPU 70／75 °C），iOS 侧收不到热状态。路线图 §5.4 的 CLPC 复刻是长期项；短期可以先让 `thermalmonitord` 跑起来并接到真实传感器，这样系统级的降亮度与限帧能工作。
- `cpus=4` 只用了 8 颗 Oryon 的一半。手势帧率对照无差异，但多任务、应用启动、后台安装是多进程并行的场景，尚未单独对照；建议用多任务手势再做一次 4 对 7 的对照，连带温度一起记。
- 电池温度已读到，但还没有纳入充电与降频判断；板载热敏电阻要 SPMI ADC 驱动。

## 15. 存储、网络与双系统

- **存储拓扑**已对齐 iPhone（`disk0s1`→APFS 容器→三个卷），设置里容量口径按 128 GB 容器。保持。
- **Wi-Fi**：首次手动加入失败已修（扫描与关联并发），已存网络重连待复核。建议把 `annibale_sta.c` 的状态机画成图写进 analysis，后续蓝牙共存与省电模式都要在它上面改。
- **双系统与 OTA**：`boot_a` 的 AVB 校验回退问题已查到 ABL 指令级根因并修复。剩下的风险是 Android 完整包 OTA 覆盖闲置槽位的 `boot`，手册已写明重刷即可；建议 loader 在启动菜单里显示自身版本与 `darwin` 分区的系统版本，减少「不知道刷的是哪个」的误判。
- **分区容量**：`darwin` 16 GiB 承载 14 GiB 的三容器，余量不到 2 GiB；若未来要装 iOS 27 的镜像（共享缓存超过 6 GiB），要预留扩容步骤。

## 16. 工程流程

- **批量集成与「一轮一个变量」冲突。** R2～R8 每轮合入十到几十处改动，与 [AGENTS.md](../../AGENTS.md) §5 的单变量原则相悖，已造成未签名注入库（R8 才发现）与 ADSP DMA 覆盖 Wi-Fi 两次整机回归。建议：未经真机读数的子系统（相机、Iris、传感器、基带、ADSP 音频）一律由启动参数或 `package.py` 开关默认关闭，刷进 `boot_a` 的镜像只带已验收项。
- **验证门槛写进手册。** 已有 `air_metal_test.c`（6764 行）、`metal_drv_test.m`、`tools/tests/test-adreno8-*.py` 等大量宿主测试，但缺少「改 AIR 或 Mesa 补丁前必须全部测试成功」的规则；§8.2 的材质样本也应纳入同一门槛。建议在 `debugging-and-collaboration.md` 里加一节「合入前检查清单」。
- **产物身份。** `package.py` 已记录各产物哈希；建议所有注入库与驱动在构造函数里打印自身 UUID，日志里就能直接对上是哪一版，R8 的未签名问题会在第一轮就暴露。
- **真机时间预算。** 每批最多三轮的规则很好；建议再加一条「每周真机窗口先分给 P0 的复核，再分给新功能」，否则新功能会一直挤占复核。
- **子代理分工。** 相互独立的源码与反汇编任务并行是对的；但同一文件不能同时派给两个成员，R6 的「独占文件分工」应成为常规，并在分工表里写明每个成员的验收输出（读数、测试、截图）。
- **行数红线。** `annibalemetal.m` 5420、`air_metal.c` 6782、`air_metal_test.c` 6764、`metal_drv_test.m` 7799、`annibale_camera.c` 4269、`annibale_adreno.c` 3497 行均超 [AGENTS.md](../../AGENTS.md) §2 的 1200 行；它们正是本次要大改的文件，动手前先按职责拆（管线／纹理／提交／诊断），否则每次修复都在同一个巨文件里冲突。

## 17. 文档治理

- **11-06 清单要拆。** [11-06 清单](../plan/2026-11-06-issues-and-followup.md)此前已有 149 KB，几十条「待真机复核」散在 9 个章节，违反 [AGENTS.md](../../AGENTS.md) §1.11 的原则。建议按用途拆开：根因与实测数据进 analysis，排期进 plan，未复核项精简为单表与待办小结。
- **启动参数目录由代码生成。** 启动参数已经超过 60 个，分散在内核注释、`cycle.py`、`package.py` 与多篇文档里。上游用脚本从代码生成参数目录并校验文档（`53c12fa`），建议照做，放在 `tools/` 下，CI 里跑。
- **注入钩子清单。** 建议专门列一张表（文件、被替换的方法、理由、属于 §3.2 的哪一类），现查到的待评估项：`inject_sb26.c` 的 CHHapticEngine 钩子（§10.1）、`inject_sb26_airdrop.inc` 在 `awdl0` 缺失时返回离线单例、`inject_sb26_loc.inc` 与 `inject_app.c` 对网络可达性的重绑定、通知授权的处理方式（§12.4）。自动解锁与图层导出类钩子属于测试工具，保留但不进日常镜像。
- **架构总览**：见 §3.3。
- **经验沉淀**：每轮的排查方法（如本次的「状态栏颜色先查合成滤镜与混合映射」）按 [经验整理 Prompt](../plan/experience-review-prompt.md) 进对应手册，不留在 progress。

## 18. 上游与同类项目更新（截至 2026-11-08）

| 仓库 | 当前位置 | 自上次对照以来的变化 | 对本项目的意义 |
|---|---|---|---|
| `oosexgang/hakios-xnu-kernel` | `main` = `63fc2b4`（11-06） | 自 [11-06 对照](2026-11-06-upstream-2-3-4-analysis.md)的 `2631f5d` 之后只有 4 笔：`2423430` 设备树 reg 解析按父节点 cell 宽度、`04aad08` `var-store` 读取工具回退到较旧校验有效的归档，以及两笔合并。图形与驱动无新内容 | `04aad08` 的思路与本项目 `ramfs_disk.inc` 主槽失败回退备槽一致，可作对照；其余无需跟进 |
| `oosexgang/hakios-metal` | `main` = `d36f329` | 11-05 起归档，驱动在内核仓库内开发 | 以后只看内核仓库 |
| `oosexgang/hakios-xnu-kernel` 其他分支 | 新增 `mtk`、`legacy-hackios` | 出现 MediaTek 分支，说明上游在做多 SoC 抽象（`devices/<name>/metal.args`、未知 GPU 拒绝初始化） | 本项目只有 annibale 一个目标，不需要跟进抽象层 |
| `UniXNU/AdrenoMetal` | 新分支 `feat/ipados27-gpu-parity`、`perf/gpu-smoothness`、`fix/gpu-scheduling-and-metal` | UniXNU 开始瞄准 iPadOS 27 | 本项目 27 的评估尚未做（路线图 §3.2），可借其 27 用户态差异记录 |
| `IssacL04/UniXNU-Pagani_SM8750` | `main` = `a84204e`（11-08） | 11-05～11-08 非常活跃：A830 更高动态频率与分档温控、USB 设备模式、Wi-Fi、显示休眠、UFS 持久日志 | **同 SoC**。其 A830 时钟表、USB 设备模式（本项目 iOS 侧 USB 为空白）、显示休眠值得读一遍，注意许可证 |
| `Shad0w23333/UniXNU-OnePlus13T` | `main` = `8c18295` | 11-02 首次开源（iPadOS 17.7.11） | 同 SoC 的 A830 参考，[11-05 对照](2026-11-05-upstream-lessons.md)提到其回移的 ir3 修复 `189ee824` |
| Mesa | 本项目基线 26.2.5 | 社区已有基于 26.3.0 的 Turnip 构建（The412Banner/Banners-Turnip 的 26.3.0 系列），说明 26.3 已发布或接近发布；`rebase-26/0001`、`0002` 两条 cherry-pick 在 26.3 上可撤 | 评估切到 26.3.x，连带核对 `0006` 关闭的片元纹理预取问题是否已在上游修复 |

上游 11-03～11-05 的做法已在 [11-05 对照](2026-11-05-upstream-lessons.md)与 [11-06 对照](2026-11-06-upstream-2-3-4-analysis.md)中逐条登记，本次没有新增可借用项。需要补一条判断：上游把状态栏变白与壁纸发红两个「颜色不对」最终归到着色器变体选择，并撤掉了此前的滤镜绕过与壁纸场景改写；这与本项目 §8 的思路一致，即颜色错误先找驱动契约，不在 SpringBoard 里改图层。

关于 iOS 27：路线图定的是「26 跑通后评估 27」。27 需要 8 个新系统调用、4 个 MIG 编号、超过 6 GiB 的共享缓存与新的 `posix_spawnattr` 布局，且 27 的内核源码未公开。建议在 A 档完成前不启动评估，但 `darwin` 分区扩容的步骤（§15）可以先写进手册。

## 19. 建议的执行顺序与验收判据

后续事项与验收判据分别见[系统与持久化](../backlog/system.md)、[图形与显示](../backlog/graphics.md)、[多媒体](../backlog/multimedia.md)、[外设与电源](../backlog/platform.md)及[工程待办](../backlog/engineering.md)。

已完成记录：

- 架构总览、启动参数目录与钩子清单已完成，见[架构总览](../plan/architecture.md)、[启动参数目录](boot-args.md)及[注入钩子清单](2026-11-09-injection-hooks.md)。
- §13 崩溃报告跨开机保留，见[用户态崩溃报告](2026-11-09-crash-reports.md)。
- §13 页大小：真机 `hw.pagesize` 与 `vm.pagesize` 都是 16384。
- §16 合入前检查写进[排查与协作手册 §10](../plan/debugging-and-collaboration.md#10-合入前检查)。
- 删除四个表象绕过钩子（含 `CHHapticEngine` 钩子），见[注入钩子清单 §3](2026-11-09-injection-hooks.md#3-结论)。
- §16 产物自报 UUID：已修复 `init26.c` 早期 stderr 重定向与 `dladdr` `LC_UUID` 提取，真机 `verify1..4.log` 已输出各守护进程与驱动的 `LC_UUID`，见 [11-10 架构审查跟进 §2](../progress/2026-11-10-arch-review-execution.md#2-开机三里程碑时间戳与注入库-lc_uuid-自报已完成)。
- 状态栏 Wi-Fi 图标灰显（`SCNetworkReachability` 无默认路由）与控制中心亮度滑块不同步：已完成根因修复与宿主单测，见 [11-10 架构审查跟进 §4、§6](../progress/2026-11-10-arch-review-execution.md)。

## 20. 风险清单

| 风险 | 影响 | 缓解 |
|---|---|---|
| 脏区残留根因不在前三个假设里 | P0 延期，整帧重画继续 | 三个假设各一轮 A/B，三轮后换测法，不靠堆轮次 |
| XR 格式若要真正支持，内核 IOSurface、驱动、Mesa 三层都要改 | 工作量比预期大 | 先用样本验证其是否为颜色错误的主因，再决定范围 |
| DPU 零拷贝需要 DPU 侧 SMMU 与带宽投票 | 显示 underflow、黑屏、真机窗口消耗大 | 先 `SwapWait` 过渡；DPU 工作在独立启动参数后面，默认关 |
| 同 SoC 项目代码许可证不兼容 | 不能直接借用 | 只读其思路与寄存器序列，自己实现 |
| 真机窗口被新功能挤占 | P0 复核拖延 | §16 的时间预算规则 |
| `darwin` 分区余量不足 2 GiB | 未来镜像装不下 | 手册先写扩容步骤 |
| 批量集成再次引发整机回归 | 用户体验倒退，信任下降 | 未验收子系统默认关闭；产物自报 UUID |

## 21. 用户决定

2026-11-09 用户对原列的待决定事项答复如下：

1. 三档定位（§2）：接受，当前阶段定为 A 档，按正确、流畅、稳定的优先级推进，外设降速。
2. DPU 缩放零拷贝上屏（§5.2）：立项，先做可行性验证。
3. 画布 1206×2622（§4.2、§18）：先做性能检查，再决定是否调整。
4. 未验收子系统默认关闭（§16）：不另立规则。用户认为收益不大、会增加复杂度，必要时再做。各子系统已有自己的启动参数，出现回归时把对应参数的默认值关掉即可；批量集成由 [AGENTS.md](../../AGENTS.md) §5「一轮一个变量」约束。
5. 静态壁纸（§7.3）：暂不更换。
6. FairPlayIOKit（§12.1）：不以跑通 FairPlay 为目标；Weather 与 Maps 若依赖它就放弃。
7. App Store（§12.6）：明确不做。
8. Mesa 26.3.x 与同 SoC 项目（§18）：评估升级可行性，有提升就升级。允许参考其他项目；许可证不允许直接复用时做净室复刻，只参考架构设计与逻辑。
9. 架构总览与启动参数目录（§3.3、§17）：已落地，见 §19。
