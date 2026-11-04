# 上游与同类项目 11-01～11-05 的可借用做法

核对日期 2026-11-05。按用户决定，上游只借用解法与工作流，不合并代码。上一轮对照见 [11-01 对照](2026-11-01-hakios-upstream-lessons.md)，本文只记新增内容。上游的读数大多来自 POCO X5 Pro（SM7325，A6XX）上的 iOS 16.5，用到 K90 前都要在 A830 与 iOS 26 上重新量。

## 1. 按收益排序的候选

| # | 做法 | 来源 | 我们的现状 | 下一步与判据 |
|---|---|---|---|---|
| 1 | backboardd 环境变量 `CA_FP16_MIN_HEADROOM=1e30`、`CA_ALLOW_EDR_MIRRORING=0`，让 CoreAnimation 不用 16 位浮点帧缓冲 | UniXNU/AdrenoMetal `d2aa73f`、`0055c37`、`9bad6f5` | 23G90 的共享缓存里有这两个变量名（已核对）；整屏 pass 的第二个附件是 RGBA16Float，每帧约 25 MB 写回 | 一轮 `JOB_ENV` 对照：`REDWOOD_PASS_LOG=1` 里第二个附件是否消失，`REDWOOD_PASS_TIMES` 的整屏 pass 时间 |
| 2 | 整屏 pass 逐个 draw 计时；CoreAnimation 的大着色器按常量缓冲内容特化编译 | hakios-metal `e59090f`，hakios-xnu-kernel `512d228`、`d53f3e9` | 只有按 pass 的合计（`rebase-26/0008`），不知道 87% 的整屏 pass 时间落在哪几个 draw | 先打印 backboardd 片段着色器的指令数与常量缓冲读取，再在 sysmem 下给单帧逐 draw 计时 |
| 3 | 画布改为 iPhone XR／11 的 828×1792（2 倍） | hakios-xnu-kernel `09cf881`、`87bf485` | 1206×2622 是为状态栏布局选的（[状态栏布局分析](2026-11-02-status-bar-layout.md)）；像素是 828×1792 的 2.13 倍 | 需用户决定清晰度与帧率的取舍；上游滚动 89～91 → 118 帧／秒，画面变软 |
| 4 | 隐藏或冻结壁纸做对照 | hakios-xnu-kernel `512d228`、`66b8e63`、`348613f`；hakios-metal `583b67f` | sk1 手势窗口里壁纸扩展用了 519 ms GPU 时间 | SpringBoard 注入库加一个隐藏壁纸窗口的通知，一轮对照手势帧率 |
| 5 | 着色器编译结果跨开机保存，并随镜像带一份 | hakios-xnu-kernel `39dd3bb`、`5c819b8`、`8ecae63`；hakios-metal `9d52b51`、`6a77e42`、`3d3400f` | Mesa 构建 `shader-cache` 为 `disabled`（已核对）；驱动的管线缓存只在进程内 | 打开 Mesa 着色器缓存、目录放在 `/private/var/db`、随开机种子带上；判据是开机后编译次数与图标出现时间 |
| 6 | Mesa 26.3 的 ir3 A8xx 修复回移（`189ee824` 等） | Shad0w23333/UniXNU-OnePlus13T | `rebase-26/0006` 关掉了片段着色器纹理预取，可能正是 `189ee824` 修的问题（推断） | 回移后撤掉 0006，看 Dock 玻璃与整屏 pass 时间 |
| 7 | 亮度经 DSI 测试模式 FIFO 发 DCS，不需要 DMA 与 SMMU | ShueiTsuki/data-a-live 补丁 `0139`～`0141`、`0263`～`0264` | [亮度调研](2026-11-02-brightness-control.md) §5、§8 的 DMA 问题未定 | 寄存器偏移来自 SM8850，要在 SM8750 上核对 |
| 8 | 在 Qualcomm 上出声的几处坑 | UniXNU-sheng `dea464e`、`4583f03`、`b49ce39`、`6e892fe`、`1b75289` | [音量调研](2026-11-02-audio-and-volume.md)只有指针 | 音量调研 §7 已列出这几项：主机时钟 19.2 MHz、128 位换算、缓冲在 4 GiB 以下、传输类型；细节在移植出声时核对 |
| 9 | 实现 SwapWait，让 `fb_queue=2` 能和下一帧重叠 | data-a-live `0218` | `MiniIOMobileFramebuffer.cpp` 的 SwapWait 直接返回成功，靠 `fb_queue=1` 保证安全 | 约 150 行；判据是 SwapEnd 阻塞时间与有无闪烁 |
| 10 | A830 打开 ACD | Shad0w23333/UniXNU-OnePlus13T | 我们在没有 ACD 表的情况下跑到 1100 MHz | 固定手势脚本下对比挂起、故障与 GPU 最高温度 |

## 2. 工具与工作流

- 手势按抬手分成拖动段与松手后的动画段分别统计。上游发现拖动时 75～80 帧／秒、松手后多数帧 8.3 ms；`gestures.py` 现在把固定窗口混在一起算。
- 同配置至少重复几次再报数，给中位数和范围。上游把一次 109 的读数更正为 89～91；我们同配置的右滑在 87.4～95.5 之间。
- 对所有线程采样，包括在等待的线程，用来区分编码慢与被阻塞（hakios-xnu-kernel `39dd3bb`、hakios-metal `c7f1348`）。
- 每个 command buffer 的生成、提交、完成时刻（hakios-metal `77305c7`）。上游据此发现 SpringBoard 忙时窗口服务器根本没有生成 command buffer。
- 开机参数清单由脚本从代码生成并校验文档（hakios-xnu-kernel `53c12fa`）。
- 每个修复配一个去掉修复后必须失败的对照测试（hakios-metal `6ee719f`）。

## 3. 对照中发现的本仓库问题

- `redwood_adreno.c` 读 GPU 温度用的是 POCO X5 Pro 的 tsens 地址 `0x0c265000`；K90 的 GPU 传感器在 `0x0c22a000`（`annibale_cpufreq.c` 的 `tsens_groups`）。只影响每分钟一行的 GPU 温度日志，温控降频用的是 `annibale_cpufreq.c`，不受影响。
- `sb26_boot_arg_present()` 按整词匹配，`cycle.py` 默认带 `dl_max=1` 时，在 `--boot-args` 里加 `dl_max=0` 关不掉它；要关就整串替换 `CYCLE_FIXED_ARGS`。

## 4. 不适用

- `fb_beam`（单缓冲写在扫描线后面）：我们用 `fb_flip=2` 双缓冲，上游后来也把收益更正到误差范围内。
- 触摸每 4 ms 采样、提前释放 surface、`metal_defer`：上游没有量出帧率变化，或依赖它自己的命令录制器。
- Turnip 与 metal2vulkan：上游在同机上翻页 50～57 帧／秒，直连驱动 100～104，支持我们留在 gallium。
- 补 `default.metallib`、`luma_boost` 替身等：只因 iOS 16.5 没有 QuartzCore 的 `default.metallib`，iOS 26 自带。
- 默认 sysmem：我们的 sm1 轮总 GPU 时间增加 30%。
- K90 Pro Max（`Typeun/myron-device`）11-01 起缩成只在内存里跑的最小构建，没有新的显示或 GPU 内容；K90 物理面板分辨率在同类项目里没有资料。

## 5. 核对范围

| 来源 | 范围 |
|---|---|
| `oosexgang/hakios-xnu-kernel` | `a48d2b2..87bf485`，41 笔（11-01～11-04） |
| `oosexgang/hakios-metal` | `a097abd..5cb33eb`；155 笔里多数是 11-04 从内核仓库搬来的旧提交，新增约 37 笔 |
| `oosexgang/hackios-web` | 4 笔，文档与读数更正 |
| UniXNU 组织 | GopFramebuffer 到 `e47c1b8`，AdrenoMetal 到 `243d63c`，`devices.toml` 234 条，没有 annibale／K90 |
| 同 SoC 与相近项目 | `IssacL04/UniXNU-Pagani_SM8750`、`Shad0w23333/UniXNU-OnePlus13T`（OnePlus 13T，SM8750／A830），`ShueiTsuki/data-a-live`（SM8850，10-30 归档） |
| `superboyyy/hakios-arm64e-dada` | 10-31 之后没有更新 |

只读副本在 Git 忽略的 `docs/analysis/local/upstream-2026-11-01/` 与 `docs/analysis/local/upstream-2026-11-05/`，没有执行其中的脚本或构建。表中上游提交号与读数来自对方的提交说明和代码，本仓库一侧标「已核对」的条目逐项看过代码或文件，其余是对照时的读法。
