# 渲染、文件身份与元数据打包核查（2026-11-12）

本批按照[执行计划](../plan/2026-11-12-rendering-runtime.md)处理 G3、G8、S9、S10，并完成 S6 的入口复现与原生参考。设备继续由多媒体任务统一操作，本批结果来自源码、iOS 26 共享缓存、宿主测试和目标编译。

内核与驱动测试提交为 `a75b0016`，Mesa 补丁与测试提交为 `0c0f37f`。两笔提交均未部署到设备。

## 1. 结果与验证范围

| 事项 | 结果 | 尚需验证 |
|---|---|---|
| G3：Mesa alias.rt 与 fsat | 加入维护补丁；实际 ir3 测试旧版 3／16 失败，修复后 16／16 成功 | A830 像素输出及实际 UI 是否触发这两种错误 |
| G8：selector 74 | 初始化 count、selected index 两个输出，保留较短缓冲容量边界；40 个宿主场景及目标编译通过 | 当前设备显示调用与画面回归 |
| S9：元数据打包 | 复制有效数据后只清零 padding，保留空 xattr 数据的清零语义；与旧版逐字节对照通过 | 设备上的同步持锁耗时、UFS 等待和交互帧时 |
| S10：APFS 文件身份 | 使用 XNU 原生挂载身份分配器；15 个宿主场景及目标编译通过 | System、Cryptex、应用路径的实际 `fsgetpath` 往返 |
| S6：格式 94 | 复现五处入口契约问题；原生 Metal 三条路径共 24 个像素字一致；参考程序完成 arm64e 编译与签名 | 完整格式支持、A830 输出与 CoreAnimation 软件渲染契约 |

## 2. Mesa alias.rt 与 fsat

补丁位于 `hackios-xnu-userland/tools/mesa/rebase-26/0018-ir3-alias-relative-and-fsat.patch`。构建入口已经按顺序读取该目录的补丁，无需新增开关或修改共享构建脚本。

- 相对寻址常量不能作为 `alias.rt` 的别名目标。旧实现删除了仍需动态索引的输出；修复后保留该输出。绝对常量与立即数的合法别名优化保持有效。
- `fsat` 只能合并到支持浮点饱和的指令类别。旧实现对整数加法和 XOR 的输出合并后生成 `add.u (sat)`／`xor.b (sat)`；修复后保留独立的 `max.f (sat)`。
- 测试调用实际 `ir3_create_alias_rt`、NIR finalize、`ir3_compile_shader_nir` 及 ISA assembler／disassembler。16 项检查包含合法优化、单次使用和多次使用的对照。

宿主测试使用独立解包的 Mesa 26.2.5 源码和构建目录。两个修改目标与已有 prepared 树的对应源码一致，补丁 dry-run 通过。上游修复及版本来源见[上游对照 §5](2026-11-12-upstream-review.md#5-mesa)。这些编译器问题与已有组件黑底的因果关系、GPU 像素及 16 位 shader 仍未验证。

隔离 iOS 构建完成 822 个步骤，成功链接 arm64e `libannibaleair.dylib`。目标平台为 iOS，最低版本 26.0，SDK 27.1，库大小 14,131,584 字节。输入来自 Mesa 26.2.5 包、当前 31 份基础补丁、20 份 rebase 补丁及仓库中的 AIR／annibale-drm；基础补丁中 14 项按既有 26.x 规则部分失败后继续，rebase 补丁全部成功。输入摘要及完整日志保存在 `hackios-xnu-userland/out/g3-ir3-ios/`，库未部署。

`tools/air/check.sh -q` 已执行，但默认 `build/mesa-host` 缺少 `air2nir`，脚本在运行语料前退出。该结果不能计入 AIR 语料通过数。另发现默认 prepared 树仍引用缺失的 `redwood-drm`，故本批从固定源码包独立重建；共享构建目录保持原样。

## 3. selector 74 的输出

23G90 中 `kern_SupportedFrameInfo` 位于 `0x2294bb384`，请求两个标量及 64 字节结构。调用方将两个输出初始化为 `0xAAAAAAAAAAAAAAAA`，返回后直接读取 count 和 selected index。旧驱动只写第一个输出，并将返回数量设为 1。

`MiniFramebufferUserClient.inc` 现在按调用方容量写入至多两个零值。count 为 0 的语义保持不变，selected index 有确定初值。容量为 0 或 1 的调用保持在缓冲区边界内，结构输出仍按已有长度清零。

`hackios-xnu-kernel/tools/tests/test-fb-frame-info.py` 提取实际分支，覆盖标量容量 0／1／2／4、结构容量 0／1／63／64／65 及空指针，共 40 个组合。ASan／UBSan 和 canary 检查通过；旧版对原生调用形状失败。既有 `test-fb-swap.py` 同时通过。接口来源与其他 selector 缺口见[selector 核查 §5](2026-10-28-iomfb-selector-names.md#5-727374-与项目-enum-的对照)。

## 4. APFS 文件身份

旧实现以设备号作为 `fsid.val[0]`，把容器与卷索引编码进 `val[1]`。`mount_lookupby_volfsid`、`vfs_getbyid` 等 XNU 消费者只按 `val[0]` 查找；同设备多容器或多卷因此可能选中错误的挂载。不同卷具有相同 inode 编号时，查找可以成功却返回另一对象。

`apfs_mount_common` 改为调用 `vfs_getnewfsid(mp)`。根挂载和普通挂载共用此入口，挂载属性更新保持原有身份。`am_rdev` 继续保存底层设备号。

属性与查找路径已逐项核对：

- `apfs_vnops.c` 的 `va_fsid` 读取所属 mount 的 `val[0]`；`vn_stat` 将其用于 `st_dev`。
- `getattrlist` 的 `ATTR_CMN_DEVID` 使用同一字段；`ATTR_CMN_FSID` 通过原生 fallback 返回完整 mount fsid。
- `fsgetpath` 允许 `{st_dev, 0}` 输入，`/.vol` 和其他按卷 ID 查找的入口也依赖首字段。修改完整 fsid 比较无法同时解决这些调用。

`tools/tests/test-fsid-lookup.py` 提取实际 APFS 分配语句及 XNU 分配、查找函数。15 项测试覆盖同设备跨容器、同容器跨卷、同 inode、目标仅存在于第二卷、`{st_dev, 0}`、重新挂载、查找失败及引用归还。旧版 6 项失败，修复后与原生分配对照均为 15／15 成功，ASan／UBSan 通过。测试使用 mount／vnode 替身，实际路径遍历由[系统契约中的只读工具](2026-11-12-system-contracts.md#6-应用前台切换)继续验证。

原生分配器保证当前挂载身份唯一。旧数字 fsid 在重启且挂载顺序变化后可能对应另一卷，专项诊断单独记录这一边界。APFS 当前返回容器 UUID，ramfs UUID 由动态 fsid 派生；卷 UUID 与 IOKit 的一致性仍需单独处理。

## 5. 元数据打包的重复写入

`ramfs_disk_pack_locked` 在复制符号链接、块号表、xattr 和目录项名字前，先清零整段输出。修改后复制有效字节，再清零对齐填充。xattr 的 `rx_size > 0 && rx_data == NULL` 分支仍将声明的数据区清零，inode 记录的保留字段和 padding 继续初始化。

磁盘格式、CRC、提交顺序与锁范围保持原样。测试直接比较两个版本输出的完整缓冲、返回值、节点数量和 payload 长度，并检查写入边界。ASan／UBSan 下共 31,890 次比较通过，覆盖长度 0～31、块表洞、删除节点、socket、空目标、空块表、空 xattr 数据和逐字节 `ENOSPC` 容量边界。恢复、卸载重试和 callout 生命周期的既有测试也通过。

宿主性能对照使用 `clang -O2`，关闭 sanitizer，先预热，再交替执行旧版与新版，各采集 9 组并比较中位数。小数据每组 1,000 次，较大数据每组 20 次。fixture 中节点共用输入块表和 xattr 数据，测量仅包含已预热的打包函数，未包含锁等待、CRC 或 UFS 写入。

| 节点数 | 每节点 xattr／块号数 | payload 字节 | 旧版中位数 | 新版中位数 | 变化 |
|---|---|---|---|---|---|
| 256 | 16 字节／4 | 51,200 | 9.951 µs | 9.864 µs | −0.87%，差异较小 |
| 70,000 | 64 字节／4 | 17,360,000 | 1,185.950 µs | 1,111.200 µs | −6.30% |
| 4,096 | 4,096 字节／256 | 21,659,648 | 499.100 µs | 338.050 µs | −32.27% |

测试复核修正了一处基准程序的无用分配，并补充空 xattr 用例。分别删除符号链接、块表、xattr padding、空 xattr 值、目录项的五处清零操作后，五个消融版本均被字节比较拒绝。`-O2` 汇编保留实际打包调用、`memcpy` 和 `bzero`。上述测量无法推导设备上的交互改善幅度。

## 6. 格式 94 的完整路径

格式 94 是 `BGR10A2Unorm`。23G90 的 `-[CAMetalLayer setPixelFormat:]` 在 `0x183fe9c2c` 比较 94，并在 `0x183fe9c98`／`0x183fe9c9c` 合成 FourCC `0x6c313072`，即 `l10r`。Mesa 对应 `PIPE_FORMAT_B10G10R10A2_UNORM`，每像素 4 字节，包含 B10／G10／R10／A2。

当前问题分布在多个入口：

| 路径 | 当前行为 |
|---|---|
| 普通纹理、渲染管线 | canonicalizer 将 94 改为 80 |
| buffer-backed 纹理 | 保留 94 |
| 用户态格式表与 IOSurface 导入 | 使用 BGRA FourCC，导入资源改为 80；原生 l10r 导入被拒绝 |
| MiniIOSurface | 将 l10r 改为 BGRA，组件描述仅处理 BGRA／RGBA 的 8 位通道 |
| framebuffer | 单平面 4 字节资源按 8 位通道复制、缩放和混合，`RowJob` 未携带格式 |

`tools/tests/test-metal-format94.py` 执行实际普通纹理、buffer-backed、pipeline、IOSurface 方法和布局辅助函数，后端分配及内核查询由替身提供。15 项检查中复现五处具名问题；默认命令验证诊断结果，`--require-correct` 会因这些问题返回失败。临时只移除 canonicalizer 的 94 转换后，仍有四项失败，并新增 pipeline94／import80 不一致。

`tools/tests/metal-format94-native.m` 在原生 macOS Metal 上检查普通纹理、buffer-backed 和 l10r IOSurface 三条路径。每条采样后写入格式 94 的渲染目标，8 个像素覆盖非对称 RGB、相邻 10 位码值与四档 alpha，共 24 个像素字逐字一致。iOS arm64e 版本已编译、链接、签名并通过严格签名校验，尚未在 A830 执行。

本批保留现有生产行为，交付诊断测试。完整修复至少涉及 canonicalizer、FourCC／导入映射、MiniIOSurface 元数据及 framebuffer 格式转换，还需核对 CoreAnimation 软件渲染器的 l10r 目标。XR 550～555 的私有语义和既有 UI 错误的触发条件分别研究。

## 7. 构建、复杂度与后续验收

内核三个修改目标 `MiniIOMobileFramebuffer.cpp`、`apfs_vfsops.c`、`ramfs.c` 均使用此前完整内核构建记录的参数，在独立输出目录编译通过。此次为目标文件编译，未重新链接完整内核，也未部署。命令、依赖、摘要和日志保存在忽略目录 `hackios-xnu-kernel/out/rendering-runtime-1112/`。

复杂度审查保留原有函数边界：文件身份使用已有分配器，显示接口只补输出，元数据优化只调整写入范围，Mesa 修复通过已有补丁入口维护。S6 的局部修改会新增格式不一致，故调整为完整路径分析与可复现测试。

后续设备验收按单变量执行：G3 检查动态常量索引和整数／位运算后 clamp 的像素；S10 检查实际挂载和文件对象往返；G8 检查显示查询及转场；S9 对照打包耗时和交互帧时。S6 的参考程序可复用，但完整生产支持尚未实现。

可清除纹理的后续工作还涉及 IOSurface、纹理视图和在途命令共同持有的资源。当前 `setPurgeableState` 返回固定值、`isPurgeable` 返回 NO；实际回收前需定义资源生命周期及重新使用语义，单独改变返回值无法完成回收。详见[图形待办 G6](../backlog/graphics.md)。

## 8. S9 单变量候选与测量准备

### 8.1 候选输入

S9 已基于设备使用的 CRC 内核准备独立候选，尚未打包或部署。冻结 428 个编译依赖、1,162 个 filelist 对象、5 个额外对象与 3 个 archive 后，基线重链接和冻结源码重编 `ramfs.o` 均逐字一致；候选仅替换 pack 函数的清零范围，保留基线旧 `flush_all` 及其余对象。

| S9 产物 | SHA256 | 状态 |
|---|---|---|
| CRC 基线 `crc-arm.bin` | `6f023c357adfa8d6202a71f144d0c7f2ce39465ba048dbbbe247025aae4a0744` | 与隔离重链接、重编 ramfs 后的内核逐字一致 |
| pack 候选 `candidate.bin` | `2cc80b03dbd33d9c0ce6faff77c6b6c047711aff2ec3797486c3e96c7c85a18c` | 20,548,832 字节；仅含本批 pack 修改，未在设备运行 |

输入、命令、差异与复核脚本保存在忽略目录 `hackios-xnu-kernel/out/s9-pack-1112/`，`verify-s9.py` 复核通过。现有日志支持触摸事件、渲染提交及显示函数完成的时序分析，尚未提供 pack 函数独立耗时或物理面板扫描完成时间。

### 8.2 动作与测量范围

多媒体轮的底部上滑注入了 40 个事件，命令返回 0、设备侧耗时 379 ms，但返回约 3.6／4.7 秒后的截图仍显示控制中心。该动作不进入 S9 性能样本。收尾日志只覆盖后续约 61.1 秒，没有该动作的 `tl:p` 记录，无法重建其首帧时序。

下一次交互轮先验证「已确认桌面 → 控制中心展开」，设置列表从固定位置滚动可作为备选。动作前截图确认起点，动作后确认指定内容，再间隔采图观察稳定性。`tour.json` 的 `changed_share` 比较同一动作的两个后截图，动作前后的差异需要另行核对；恢复起点的动作也需验证。

对照采用触摸按下后的固定 2 秒窗口。2 秒是本次试验参数，无法据此确定动画已经完成；截图安排在窗口外。两版本固定用户态及库摘要、启动参数、持久化起始状态、启动后等待时间、手势和采集安排；持久化状态无法复原时记录差异，暂不作单变量归因。

| 指标 | 计算与限制 |
|---|---|
| 首个后续显示函数完成延迟 | 首个 `done > touch_down` 减去 `touch_down`；该帧可能在触摸前已提交，仅作代理指标 |
| 固定窗口帧间隔 | 窗口内相邻 `done` 差值的数量、p50、p95、最大值；保留 ≥90 ms 的间隔 |
| 长间隔与覆盖 | ≥90 ms 次数、最长间隔、帧 ID 缺口及窗口末尾距最后一个 `done` 的时间；缺失样本注明不足 |
| 显示函数阶段 | `shown−ready`、`done−shown`，同时检查 IOSurface 等待超时 |
| latch 观测 | 连续 `tl:l` 的观测间隔与有效 frame-counter 差值；无法取得物理面板扫描完成时刻 |
| 内容变化 | 截图确认指定内容出现及后续观察间隔内是否稳定；无法取得精确转场完成时间 |

`tl:p` 记录进入内核触摸队列，`tl:i posted/read/sent` 记录输入服务读取和 HID 调用返回。`tl:i` 只采集该服务启动后的前 128 个样本，后续缺少这些记录仍需结合其他观测判断。手势识别需结合实际内容变化确认。

`summary.py --verify`、`gestures.py --each` 和 `frame-split.py` 可继续辅助分析。`gestures.py` 从首个 `done` 开始取窗口，`frame-split.py` 从触摸按下开始，两者部分统计会排除 ≥90 ms 间隔；底部上滑还会被前者按 `swipe-right`／600 ms 分类。旧 iOS 16.5 验收阈值不用于本次 S9 对照，最终报告使用上表的统一口径。

`ramfs_disk_sync_impl()` 尚未分别计时 pack、锁等待、CRC 与 UFS 写入；`annsh exit … ms` 仅提供整个命令的设备侧耗时，中断采样也无法换算 pack 实耗。宿主函数基准和设备 UI 时序分别报告。

### 8.3 性能统计的缺样处理

`gestures.py` 原来的 `report_pulls()` 对全部间隔 ≥90 ms 的窗口除零，对空样本计算中位数也会异常；主入口还会移除不足两个间隔的窗口，使混合样本遗漏缺样部分。修复保留所有窗口，继续采用至少两个间隔的要求；缺少可测时长的窗口显示 `n/a`，整组报告 `insufficient samples`，汇总保留长间隔总数和最长值。

`tools/k90auto/tests/test-gestures.py` 的 13 项检查成功，旧版同套检查出现 6 个异常和 5 个断言失败。分别移除时长保护、最少间隔数、整组缺样判断、最长间隔判断及恢复主入口的短窗口过滤，五组消融均被测试拒绝。手势分类、窗口及原有阈值保持原值；该修复处理统计失败，S9 的测量口径仍以 §8.2 为准。

## 9. G2 双附件 framebuffer fetch

新增独立探针 `hackios-xnu-userland/tools/air/fbfetch-mrt.m` 和 `.metal`，通过公共 Metal render API 检查两张 BGRA8Unorm 纹理。CPU 预填或同一 encoder 内先 draw 写入、原位或交换写回、正常或反序附件绑定组合成 8 个场景；每场检查两张纹理的完整 16×12 像素，包括 scissor 外保留区域。

Apple GPU 上 8 个场景共 3,072 个像素逐字节一致。将 DATA1 故意改读 DATA0 后，8 个场景均检测到错误，每场 63 个像素失配。输入使用 0／255 通道，测试不使用数值容差。独立审查后，运行错误与像素失配分别返回 2 和 1；文件写入失败对照验证了这一区分。探针沿用已有数值测试的 30 秒执行上限，超时返回 124。

iOS shader 按 `air64-apple-ios16.5.0`、Metal 3.0 独立编译；可执行文件为 arm64e、最低 iOS 26.0、SDK 27.1，签名与严格校验通过。现有宿主 `air2nir` 实际解码五个函数，并检查 pass／swap 的 DATA0、DATA1 coherent 读取与各自输出；人工核对了两者保留／交换的 SSA 写入关系。现有 `air-ir3-host` 仅接受 compute 入口，未用于证明这些 vertex／fragment 的 A830 编译结果。

源码、构建方法与设备短命令见[探针说明](../../hackios-xnu-userland/tools/air/fbfetch-mrt.md)。产物、原生像素和命令清单保存在忽略目录 `hackios-xnu-userland/out/g2-fbfetch-mrt-delivery/`。A830 尚未运行；其他格式、fixed blending、MSAA、memoryless 附件、TBDR 路径选择及实际系统 shader 仍需独立检查。
