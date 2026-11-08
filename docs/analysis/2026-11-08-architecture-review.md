# 方案架构审查与上游对照（2026-11-08）

本文是一次离线的架构审查：没有操作设备，没有构建，只读顶层仓库文档、两个子模块在总账记录的提交（内核 `4d8d9b9`、用户态 `5a7ac77`）以及上游与同类项目的公开提交历史。目的是回答三个问题：现行方案是否合理、图形卡顿与渲染错误的结构性原因在哪里、相机与震动等未通外设该怎么推进。结论按优先级给出，供用户决定后再排进[总账](../plan/2026-10-23-tracking.md)。

## 1. 总体判断

主干路线是对的，不建议推翻。iOS 26.6.2 加 `xnu-12377.121.6`、iPhone 17 身份、完整原版三容器系统卷从 UFS 按需读取、`RDWFS001` 内核直写 `darwin_var`、`xnuloader` 双系统，这几项都已在真机闭环，且与上游后来的走向一致（上游 11-03 试过 Turnip 加 metal2vulkan，测得比直连驱动慢一半，仍回到自有驱动）。

真正的结构性风险集中在四处，后文逐一展开：

- 图形管线里有三段「CPU 在环」与一个未查明的正确性缺陷（局部重绘残留），后者迫使整帧重画，吃掉了约四成 GPU 预算并造成静置发热（§2）。
- 渲染正确性依赖 AIR→NIR 翻译器与 freedreno 补丁层，但没有按「材质／玻璃」着色器家族组织的回归样本，问题只能逐个真机复现后再修，用户看到的顶栏、搜索栏、状态栏颜色错就是这一类（§3）。
- R2～R8 几轮「多 Worker 批量集成」一次落地几十处改动，大部分标为「待真机复核」，并已经引发过两次整机级回归（未签名注入库、ADSP DMA 覆盖 Wi-Fi 控制环）。验证债务已经超过验证能力（§6）。
- 注入库里仍有伪造硬件能力的钩子，最直接的例子是 SpringBoard 里把 `CHHapticEngine` 的 `supportsHaptics` 固定为 NO，这与 [AGENTS.md](../../AGENTS.md) §6 冲突，也让震动在 iOS 26 上无论内核修到什么程度都不可能生效（§5.1）。

## 2. 图形管线：现状与开销归因

### 2.1 一帧的路径

| 阶段 | 实现位置 | 性质 |
|---|---|---|
| CoreAnimation 合成（backboardd） | iOS 原生 | GPU 命令由 Metal 接口下发 |
| Metal 驱动 | `hackios-xnu-kernel/tools/userland-driver/redwoodmetal.m`（5420 行）及 `.inc` | 把 Metal 对象映射到 Gallium 状态 |
| AIR 编译与状态层 | `hackios-xnu-userland/tools/mesa/air/`（`air_metal.c` 6782 行、`air_to_nir.c` 3461 行） | AIR 位码→NIR→ir3，运行时编译 |
| Gallium freedreno a8xx | Mesa 26.2.5 加 `tools/mesa/rebase-26/` 17 个补丁 | GMEM 分 bin 渲染，命令流生成 |
| 内核 GPU 服务 | `xnu/files/iokit/Kernel/RedwoodGPU.cpp`、`xnu/files/bsd/dev/adreno8/` | 提交经 HFI 交给 GMU |
| 上屏 | `xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp` 及 `MiniFramebuffer*.inc` | **CPU** 把 1206×2622 缩放拷进 1156×2510 面板内存，再换扫描地址 |

上屏一段的性质决定了几个硬约束。显示控制器只被用来换地址（`fb_flip=2`），缩放、逐行哈希、脏行判定都在 CPU 上由两个内核线程完成；`fb_queue=1` 下 `SwapEnd` 要等上一帧拷完，相邻两帧共用两拍预算。这是 [120 Hz 卡点分析](2026-11-01-120hz-gesture-bottleneck.md) §6 已经量到的链路。

### 2.2 时间花在哪里

下面的数字都来自已有轮次记录，这里只汇总出处，不重复展开。

| 项 | 读数 | 出处 |
|---|---|---|
| backboardd GPU 时间中整屏合成 pass 占比 | 约 87%，其中 tile load／store 原各占两成，补丁 0009／0010 后 load 降约六成 | [GPU 升频之后的长帧](2026-11-02-120hz-after-gpu-clock.md) §6 |
| 整帧重画 vs 脏区 | 整帧重画的 GPU 时间多 72%（`bo49` 对 `bo47`） | `tools/k90auto/package.py` `DIRTY_REGIONS` 注释 |
| 画布 1206×2622 对 1125×2436 | 像素多 15.4%，控制中心下拉 106 → 88 帧／秒 | [状态栏布局分析](2026-11-02-status-bar-layout.md) §6 |
| CPU 缩放拷贝 | 手势期间每帧 3.0～7.3 ms 驱动内时间 | [GPU 升频之后的长帧](2026-11-02-120hz-after-gpu-clock.md) §5 |
| 每次提交的派发延迟 | 约 0.7 ms，与 GPU 忙闲无关，原因未查 | 同上 §3 |
| 静置 | 主屏时钟图标 10 Hz 触发整屏重绘，每秒约 20 次整屏 pass | [11-06 清单](../plan/2026-11-06-issues-and-followup.md) §1.15 |

把这些放在一起看：手势里 GPU 时间超过一拍的帧，主要是整屏 pass 本身大；整屏 pass 之所以每帧都要画，是因为 `CA_DISABLE_DIRTY_REGIONS=1` 还在默认参数里。所以性能路线的第一优先级不是再调频或再省 tile store，而是把脏区重绘的正确性缺陷查清，让 CoreAnimation 回到只画变化区域的原生行为。

### 2.3 用户反馈的四个场景怎么对应

| 场景 | 更可能的机制 | 建议先采的证据 |
|---|---|---|
| 多任务界面卡顿 | 每张应用快照是一块线性 IOSurface 纹理，叠加 `CABackdropLayer` 模糊（compute 下采样）与玻璃材质，一帧多个 pass 加多次提交；每次提交各付 0.7 ms 派发延迟 | 打开 `REDWOOD_PASS_TIMES=1` 在多任务手势里采 5 秒，记每帧 pass 数、compute 派发数与提交次数 |
| 设置底部搜索栏背景色不对 | Liquid Glass 材质：`CABackdropLayer` 加合成滤镜，着色器用 framebuffer fetch 混合，再叠 sRGB 或 10 位 XR 附件 | 见 §3 的格式与混合核对 |
| 顶栏颜色经常不对 | 同上，导航栏的 `_UIBarBackground` 是材质视图；此前曾被钩子涂白，钩子已删，现在剩下的是驱动一侧的问题 | 同上 |
| 状态栏颜色不对 | 状态栏的易读性渐变带合成滤镜（上游在 iOS 16.5 上见到同一症状：`darkenSourceOver` 渐变画成纯白） | 用 `inject_sb26_layers.c` 的图层导出列出状态栏窗口的 `compositingFilter`，再核对驱动对该滤镜对应混合状态的映射 |

上游把状态栏变白与壁纸顶部发红归到一个根因：CoreAnimation 运行时生成的管线落到了错误的着色器变体（上游内核仓库 `3b9db78`）。本项目直接编译每个 `MTLFunction` 自带的 AIR，变体选择不是问题；所以同一症状在这里更可能出在**格式替换、混合状态映射、framebuffer fetch 与附件读写策略**这四处，§3 逐一列出。

## 3. 渲染正确性：结构性可疑点与对策

### 3.1 四处可疑的契约偏差

1. **10 位 XR 格式被静默替换成 8 位。** `MiniIOSurface.cpp` 把 `w30r`／`l10r`／`w30R`／`b3a8` 建成 `BGRA`，驱动再用 `rwd_canonical_pixel_format()` 把 Metal 格式 94 与 550～555 映射为 80／81（`hackios-xnu-kernel/tools/userland-driver/redwood_drawable.h`）。iPhone 17 身份下 CoreAnimation 会为玻璃与壁纸选 XR 格式，超出 [0,1] 的分量被截断，sRGB 与线性的判定（551／553／555 视为 sRGB）也是推断而非从 QuartzCore 读出的对应关系。这是最直接会把半透明材质颜色画偏的一条，建议第一个核对。
2. **framebuffer fetch 的降级路径。** `air_to_nir.c` 把 `air.render_target` 输入翻成 `fb_fetch_output`，Mesa 再降成 `txf_ms_fb`；补丁 0016 用常量图层 0 绕过了 VPC 脏寄存器。这是个合理修补，但 A830 上 fb fetch 在 GMEM 多 bin 与两个颜色附件下的一致性没有专门测试，而 iOS 26 的材质着色器大量依赖它。
3. **附件读写策略的两条补丁有正确性前提。** 0009 把 `MTLLoadActionDontCare` 附件标为内容无效、0010 跳过 `colormask=0` 附件的写回，两者都假设 CoreAnimation 之后不再读这块附件。整屏 pass 的第二个 RGBA16Float 附件正是材质路径可能回读的那块；若某些 pass 确实回读，就会出现「局部区域颜色错、切换控制中心后又对」这种状态依赖的症状。建议做一次 A/B：关掉 0009／0010 跑同一组截图，看搜索栏、顶栏、状态栏是否变化。
4. **混合状态映射。** `air_metal.c` 第 5251 行附近注明某些混合操作按 `max(Cs, Cd)` 处理而忽略因子；合成滤镜（`darkenSourceOver`、`sourceAtop`、`plusL` 等）全靠混合状态与双源混合表达，任何一项映射不精确都会表现为「颜色老是不对」。

### 3.2 对策：建立材质着色器回归样本

现在的做法是真机复现一个修一个，每个修复配一组宿主检查。建议把它升级为一套按着色器家族组织的离线回归：

- 从 23G90 的 QuartzCore `default.metallib` 与 CoreImage metallib 提取玻璃、背景模糊、合成滤镜、SDF 文本这几族着色器及它们在真机日志中出现过的管线描述（附件格式、混合状态、load／store）。
- 宿主侧用 Mac 原生 Metal 渲染同一输入得到参考图，设备侧用现有 `userland/src/tests/metal_drv_test.m`（7799 行，已有大量用例）跑同一描述，做像素差。
- 每条 rebase-26 补丁与 `rwd_canonical_pixel_format()` 这类替换都要在这套样本上过一遍，再进默认参数。

这套样本一旦建立，§3.1 的四条可疑点会在一个下午内得到证实或排除，之后再改 AIR 或 Mesa 补丁也有护栏。

### 3.3 脏区重绘残留的排查方向

「局部重绘留下旧内容」目前只有现象没有归因。结合代码里已有的三处机制，建议按下面顺序排除：

- 导入资源的 shadow 已由 0011 禁止，但 `fd_resource_contents_undefined()`（0009）对 `Load` 附件是否会被误标，尤其是同一 IOSurface 在同一帧被两个 pass 先写后读时。
- `MiniFramebufferRows.inc` 的逐行哈希与脏行覆盖在 CoreAnimation 只提交脏矩形时是否仍按整帧比较（两个脏矩形之间的行未变，但 CoreAnimation 认为显示内容已经是新帧）。
- `fb_flip=2` 双缓冲下，脏区只写进了当前缓冲，上一帧的缓冲没有同步该区域，翻转后露出旧内容。这一条与症状「切一次控制中心就好了」最吻合，也最容易验证：`fb_flip=0` 加 `DIRTY_REGIONS=1` 跑一轮看残留是否消失。

## 4. 性能路线建议（按收益排序）

1. **查清脏区残留、关掉整帧重画。** 预期收益是 GPU 时间约四成、静置功耗与发热显著下降，是 120 Hz 的最大单项余量。判据：`DIRTY_REGIONS=1` 下连续截图无残留，静置整屏 pass 次数接近 0。
2. **上屏零拷贝。** 把 1206×2622→1156×2510 的缩放交给 DPU 的 SSPP 缩放器，GPU 输出缓冲直接扫描，撤掉 CPU 缩放线程与 `fb_queue=1` 串行化。这是内核显示驱动的一项实质工作（寄存器参考 Linux `drm/msm/disp/dpu1` 的 sspp／qseed 路径），需要给 DPU 配 SMMU 映射或使用连续内存。在此之前，低成本的过渡是实现 `SwapWait` 让 `fb_queue=2` 可用（上游同类项目有参考实现）。
3. **验证跨开机着色器与管线缓存真的生效。** `redwood-pipecache-v5.bin` 与 M1 的 `redwood-aircache` 已落地，但没有「开机后编译次数」的读数。首次进多任务、首次打开控制中心的卡顿很可能就是运行时编译。判据：第二次开机后 backboardd 的建管线次数接近 0。
4. **提交派发延迟 0.7 ms。** 每帧多次提交时成倍计入。方向是 HFI 门铃与 GMU 消息队列的路径（`adreno8_hfi.c`），以及更激进的提交合并。
5. **IOSurface 纹理走 UBWC。** 合成器读的都是线性纹理，整屏 pass 的 tile load 就是带宽；上游自有驱动已做 UBWC 纹理，freedreno a8xx 也支持 UBWC 布局，但 IOSurface 在内核侧分配，需要内核与驱动一起约定布局。放在 1、2 之后。
6. **CPU 核数。** 默认 `cpus=4 bootcpu=7`，8 颗 Oryon 只用一半。手势帧率对照（`c7`）无差异，但多任务界面是多进程同时出帧的场景，尚未单独对照。建议用多任务手势再做一次 4 对 7 的对照，连带温度一起记。
7. **画布缩小（828×1792 或 2 倍模式）。** 上游在 SM7325 上换 2 倍画布后滚动 91 → 118 帧／秒，但会与 iPhone 17 身份的 MobileGestalt 查表不一致，且画面变软。建议在 1、2 之前不动这一项，只作为最后的取舍留给用户决定。

不建议的方向：切到 Turnip 加 metal2vulkan（上游同机实测比直连慢一半）、默认 sysmem（本项目 `sm1` 轮总 GPU 时间多 30%）、继续堆 GPU 频率（1100 MHz 已到顶，收益已在 11-02 兑现）。

## 5. 外设未通项的架构判断

### 5.1 震动

事实链有三条：

- iOS 16.5 上 `hv_haptic=4` 经 RedwoodAudio 的「Actuator」设备驱动马达已通过，见[手电与震动实测](../progress/2026-10-26-torch-and-haptics.md) §6。
- iOS 26 上故障寄存器 `0x10`（UVLO）清不掉；R2 M3 加了 UVLO 清除与 `0xf246` 升压使能，但未上机。
- `hackios-xnu-userland/userland/src/inject/inject_sb26.c` 的 `install_haptic_hooks()` 把 `CHHapticEngine` 的 `capabilitiesForHardware` 改成 `supportsHaptics=NO`、`supportsAudio=NO`，`start`／`stop` 直接返回成功。

判断：这个钩子是为了避免 SpringBoard 主线程被触感引擎阻塞而加的表象绕过，但它截断了 CoreHaptics→audiomxd／HAL「Actuator」→`/dev/redwood-haptic` 的原生路径，内核修好也没有波形送到。建议：

- 删除该钩子，把阻塞问题还原到 HAL 插件（`userland/src/services/audio_plugin.c`）的 Actuator 设备属性与 I/O 启动上去解决；`AUDIO=1` 已是默认，正好与扬声器 `AudioQueueStart=-66681` 的排查共用同一套 HAL 契约。
- UVLO 故障按原厂 `qcom-hv-haptics` 的上电顺序核对：先使能升压并等待就绪，再配置 VMAX 与波形，最后清故障；现在的顺序是先清故障再直驱。
- 验收仍分两段：无人值守看故障寄存器为 0 且 HPWR 变化，震感由用户在场确认。

### 5.2 相机

当前树里有两套相机代码：`xnu/files/bsd/dev/redwood/redwood_camera.c`（4269 行，SM7375 可用的裸寄存器方案）与 R6 盲写的 `xnu/files/bsd/dev/annibale/annibale_camera.c`（1134 行，OV50E／CSID TPG，含 Iris 占位），后者没有任何真机读数；R8 又发现注入库未签名，所以此前「0 个摄像头设备」的结论是注入没加载，不是相机代码的结果。

[相机路线](../plan/camera-plan.md)的分级与放弃准则仍然成立，建议严格按它执行而不是继续在 R 轮里批量加代码：

- 第一步不碰 CAMSS：确认签名后的 `libredwood-media.dylib` 在 `cameracaptured`／`mediaserverd` 里加载，用假的 TPG 流让 `FigCaptureDevice` 枚举出一个设备、Camera.app 预览出彩条。这一步只涉及用户态与 iOS 26 的进程归属（16.5 是 mediaserverd，26 要核对 `cameracaptured`）。
- 第二步才是 L1a 的 CPAS／camcc／csid-lite／ife-lite 通路，每一步读回报错，不靠多模块一次落地。
- vendor 的 `com.qti.sensormodule.*.bin` 仍是 L1b 的门；手机下次在 Android 时取出，放入忽略目录。
- `annibale_camera.c` 与 `annibale_iris.c` 在默认启动参数里保持关闭，直到各自第一项真机读数出现。

### 5.3 扬声器、Weather／Maps、硬解

这三项交接文档已有清晰的下一步，这里只补架构层面的判断：

- 扬声器：DSP 侧 OPEN／PREPARE／START 已成功，卡在 AudioQueue 到 HAL 的启动；与 §5.1 一样属于 HAL 插件契约，建议合并成一个「HAL 插件对齐」工作项，用 `sound_test` 探针一起验收。
- Weather／Maps：`fairplayd.H2` 找不到 `com_apple_driver_FairPlayIOKit` 而退出，天气 JWT 签名走 Mescal→FairPlay。这不是网络问题，而是要不要在内核里提供一个 FairPlayIOKit 服务的决策，涉及内容保护实现的边界，建议作为单独议题请用户决定范围，不与网络排查混在一起。
- 硬解：Iris 已改为如实返回不支持，VideoToolbox 走软解并有 12 帧像素校验，这是正确的「不伪造」状态。真实 HFI gen2 会话是大工程，排在图形与音频之后。

## 6. 工程流程与文档治理

- **批量集成与「一轮一个变量」冲突。** R2～R8 每轮合入十到几十处改动，与 [AGENTS.md](../../AGENTS.md) §5 的单变量原则相悖，已造成未签名注入库（R8 才发现）与 ADSP DMA 覆盖 Wi-Fi（§1.15）两次整机回归。建议：未经真机读数的子系统（相机、Iris、传感器、基带、ADSP 音频）一律由启动参数或 `package.py` 开关默认关闭，刷进 `boot_a` 的镜像只带已验收项。
- **验证债务要收口。** [11-06 清单](../plan/2026-11-06-issues-and-followup.md) 已有 149 KB，几十条「待真机复核」散在 9 个章节，违反 §1.11 的 progress 不膨胀原则。建议把它按用途拆开：根因与证据进 analysis，排期进 plan，未复核项收成一张单表（项、镜像哈希、判据、状态），复核完一项删一行。
- **离线回归要成为合入门槛。** 已有 `air_metal_test.c`（6764 行）、`metal_drv_test.m`、`tools/tests/test-adreno8-*.py` 等大量宿主测试，但没有一条「改 AIR 或 Mesa 补丁前必须全绿」的规则写进手册；§3.2 的材质样本也应纳入同一门槛。
- **行数红线。** `redwoodmetal.m` 5420、`air_metal.c` 6782、`air_metal_test.c` 6764、`metal_drv_test.m` 7799、`redwood_camera.c` 4269、`redwood_adreno.c` 3497 行均超 §2 的 1200 行；它们正是本次要大改的文件，动手前先按职责拆（管线／纹理／提交／诊断），否则每次修复都在同一个巨文件里冲突。
- **钩子清单与 §6 对齐。** 建议专门列一张注入钩子表（文件、被替换的方法、理由、是否为表象绕过），现查到的待评估项：`inject_sb26.c` 的 CHHapticEngine 钩子（§5.1）、`inject_sb26_airdrop.inc` 在 `awdl0` 缺失时返回离线单例、`inject_sb26_loc.inc` 与 `inject_app.c` 对网络可达性的重绑定。自动解锁与图层导出类钩子属于测试工具，保留但不进日常镜像。

## 7. 上游与同类项目更新（截至 2026-11-08）

| 仓库 | 当前位置 | 自上次对照以来的变化 | 对本项目的意义 |
|---|---|---|---|
| `oosexgang/hakios-xnu-kernel` | `main` = `63fc2b4`（11-06） | 自 [11-06 对照](2026-11-06-upstream-2-3-4-analysis.md)的 `2631f5d` 之后只有 4 笔：`2423430` 设备树 reg 解析按父节点 cell 宽度、`04aad08` `var-store` 读取工具回退到较旧校验有效的归档，以及两笔合并。图形与驱动无新内容 | `04aad08` 的思路与本项目 `ramfs_disk.inc` 主槽失败回退备槽一致，可作对照；其余无需跟进 |
| `oosexgang/hakios-metal` | `main` = `d36f329` | 11-05 起归档，驱动在内核仓库内开发 | 以后只看内核仓库 |
| `oosexgang/hakios-xnu-kernel` 其他分支 | 新增 `mtk`、`legacy-hackios` | 出现 MediaTek 分支，说明上游在做多 SoC 抽象（`devices/<name>/metal.args`、未知 GPU 拒绝初始化） | 本项目只有 annibale 一个目标，不需要跟进抽象层 |
| `UniXNU/AdrenoMetal` | 新分支 `feat/ipados27-gpu-parity`、`perf/gpu-smoothness`、`fix/gpu-scheduling-and-metal` | UniXNU 开始瞄准 iPadOS 27 | 本项目 27 的评估尚未做（路线图 §3.2），可借其 27 用户态差异记录 |
| `IssacL04/UniXNU-Pagani_SM8750` | `main` = `a84204e`（11-08） | 11-05～11-08 非常活跃：A830 更高动态频率与分档温控、USB 设备模式、Wi-Fi、显示休眠、UFS 持久日志 | **同 SoC**。其 A830 时钟表、USB 设备模式（本项目 iOS 侧 USB 为空白）值得读一遍，注意许可证 |
| `Shad0w23333/UniXNU-OnePlus13T` | `main` = `8c18295` | 11-02 首次开源（iPadOS 17.7.11） | 同 SoC 的 A830 参考，[11-05 对照](2026-11-05-upstream-lessons.md)提到其回移的 ir3 修复 `189ee824` |
| Mesa | 本项目基线 26.2.5 | 社区已有基于 26.3.0 的 Turnip 构建，说明 26.3 已发布或接近发布；`rebase-26/0001`、`0002` 两条 cherry-pick 在 26.3 上可撤 | 评估切到 26.3.x，连带核对 `0006` 关闭的片元纹理预取问题是否已在上游修复 |

上游 11-03～11-05 的做法已在 [11-05 对照](2026-11-05-upstream-lessons.md)与 [11-06 对照](2026-11-06-upstream-2-3-4-analysis.md)中逐条登记，本次没有新增可借用项。需要补一条判断：上游把状态栏变白与壁纸发红两个「颜色不对」最终归到着色器变体选择，并撤掉了此前的滤镜绕过与壁纸场景改写；这与本项目 §3 的思路一致，即颜色错误先找驱动契约，不在 SpringBoard 里改图层。

## 8. 建议的执行顺序与验收判据

| 优先级 | 工作项 | 判据 |
|---|---|---|
| P0 | 脏区重绘残留根因（§3.3），关掉整帧重画 | `DIRTY_REGIONS=1` 连续截图无残留；静置整屏 pass 接近 0；控制中心下拉帧率不降 |
| P0 | 材质着色器回归样本（§3.2），核对 XR 格式替换、fb fetch、0009／0010、混合映射 | 搜索栏、顶栏、状态栏与宿主参考图像素差在阈值内 |
| P0 | 验证管线与 AIR 缓存跨开机生效（§4.3） | 第二次开机 backboardd 建管线次数接近 0 |
| P1 | 上屏零拷贝或先实现 `SwapWait`（§4.2） | 驱动内每帧 CPU 时间降到 1 ms 以下，无撕裂与闪烁 |
| P1 | 删除 CHHapticEngine 钩子，HAL Actuator 与扬声器合并为「HAL 插件对齐」（§5.1、§5.3） | `AudioQueueStart` 返回 0；故障寄存器 0；震感与听感由用户确认 |
| P1 | 未验收子系统默认关闭、11-06 清单拆分收口（§6） | `boot_a` 镜像只带已验收项；待复核单表 |
| P2 | 多任务手势下 `cpus=4` 对 7 的对照；提交派发延迟；UBWC 评估（§4.4～4.6） | 各自一轮对照读数 |
| P2 | Mesa 26.3.x 评估；同 SoC 项目的 A830 时钟表与 USB 设备模式阅读（§7） | 评估文档，不直接合代码 |
| P2 | 相机按 L1a 分级重启（§5.2） | Camera.app 出 TPG 彩条 |

## 9. 需要用户决定的事项

1. 是否立项 DPU 缩放上屏（§4.2）。它是内核显示驱动的实质改动，收益确定但周期不短；若不立项，就只做 `SwapWait` 过渡。
2. 画布是否保持 1206×2622（§4.7）。建议保持，直到 P0 三项做完再看是否还需要用分辨率换帧率。
3. 是否接受「未验收子系统默认关闭」作为刷机镜像的规则，并停止 R 轮式的批量集成（§6）。
4. FairPlayIOKit 服务的范围（§5.3）：只为天气签名提供最小 selector，还是暂缓 Weather／Maps。
5. Mesa 26.3.x 升级的时机，以及是否阅读并借用同 SoC 项目的 A830 时钟表（需先核对许可证）。
