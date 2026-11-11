# 图形与显示待办

本表集中渲染正确性、显示完成与交互性能事项，2026-11-12 整理。当前格式与显示研究属于[系统批次 S6／S7](../plan/2026-11-12-system-followup.md)，AIR／YUV 的实际结果见[多媒体验证](../analysis/2026-11-11-multimedia-validation.md)。其他主题见[待办入口](README.md)。

## 1. 渲染与资源契约

| 编号 | 事项 | 状态与已知条件 | 下一步与验收 | 来源 |
|---|---|---|---|---|
| S6 | XR 与格式 94 精度 | 15 项入口检查复现五处问题；原生 Metal 三路共 24 个像素字一致，局部修复会新增管线／附件不一致 | 完整实现格式 94 的创建、导入、IOSurface 元数据及显示转换；XR 布局单独核对 | [渲染核查 §6](../analysis/2026-11-12-rendering-runtime.md#6-格式-94-的完整路径) |
| G1 | 大组件黑底、白块或蓝块 | 待验证；已有实际 draw／shader 关联与单变量候选，当前画面仍需复核 | 获取实际完整 AIR，检查输入与目标附件，验证修复后的组件冷启动及解锁转场 | [密集转场采集](../progress/2026-11-08-widget-dense-transition.md)、[多媒体验证](../analysis/2026-11-11-multimedia-validation.md) |
| G2 | framebuffer fetch 与多附件 | 待验证；单 BGRA8 dest_0 pass-through 已通过 | 增加 DATA1、多附件、混合、其他格式和 TBDR 场景，与原生 Metal 像素对照 | [fbfetch 结果](../progress/2026-11-08-fbfetch-validation.md)、[架构审查](../analysis/2026-11-08-architecture-review.md) |
| G3 | Mesa alias.rt 与 fsat | 维护补丁已完成；旧版 3／16 失败，修复后 16／16 成功，隔离 iOS 库链接通过 | 验证 A830 像素、16 位 shader 与实际 UI；完整 AIR 语料待恢复宿主工具后运行 | [渲染核查 §2](../analysis/2026-11-12-rendering-runtime.md#2-mesa-aliasrt-与-fsat) |
| G4 | 其他 ir3／A8xx 正确性 | 候选；大缓冲 NUM_ELEMENTS、布尔 subgroup、fquantize2f16 有上游修复 | 先确认本仓调用会生成对应 NIR 或描述符，再按容量边界、部分活跃 lane、subnormal 构造验证 | [上游对照 §5](../analysis/2026-11-12-upstream-review.md#5-mesa) |
| G5 | 启动图标与持续交互 | 待当前镜像复测；旧轮出现图标延迟和短暂空位 | 记录解锁、图标出现、设置完整加载时刻，连续巡检主屏、控制中心、通知中心与大组件 | [问题复核](../analysis/2026-11-08-issue-reassessment.md)、[多媒体验证](../analysis/2026-11-11-multimedia-validation.md) |
| G6 | 可清除纹理与内存回收 | 已复核当前入口仍返回固定状态；资源与 IOSurface、视图、在途命令共享生命周期 | 定义回收及重新使用语义，再验证内存压力下的释放和在途命令 | [渲染核查 §7](../analysis/2026-11-12-rendering-runtime.md#7-构建复杂度与后续验收)、[架构审查](../analysis/2026-11-08-architecture-review.md) |
| G7 | AIR 未覆盖指令与验证语料 | minnum／maxnum 已修复，原生眼镜景深管线真机通过；CCPortrait 82 个模块中 79 个编译成功，余 3 个缺 air.cospi.f16，真机仍有 _antialiasY 初始化失败 | 按实际系统 shader 的输入和精度要求实现 cospi，分别验证编译与 GPU 数值；常规检查基础设施见工程待办 | [多媒体验证 §23](../analysis/2026-11-11-multimedia-validation.md)、[工程待办](engineering.md) |
| G14 | 相机 MPS 输入与 Core Image stitching | MakeBlurMap 通过后，MPSImageAreaMin 因输入为空退出；格式 65 的 IOSurface 导入和 ci_affine_crop 的空 outputNode 被拒 | 先核对 RG16Float／2C0h 的真实布局并补导入；按原生 void 图实现特殊输入节点、执行副作用与 controlDependencies，分别验证返回对象和 GPU 结果 | [多媒体验证 §23](../analysis/2026-11-11-multimedia-validation.md) |

## 2. 显示完成与性能

| 编号 | 事项 | 状态与已知条件 | 下一步与验收 | 来源 |
|---|---|---|---|---|
| S7 | SwapWait、vsync 与 DPU 缩放 | 待研究；SwapWait 直接成功、vsync 使用软件定时器、CPU 执行缩放 | 定义 GPU、拷贝、DPU 接受、扫描与 surface 复用顺序，再评估硬件缩放；验证完成时序、闪烁和长帧 | [系统批次 S7](../plan/2026-11-12-system-followup.md)、[CPU 合成路径](../analysis/2026-10-31-compositor-cpu-path.md) |
| G8 | IOMFB selector 契约 | 74 的两个标量初始化已修复，40 个边界场景及目标编译通过；78／88 等接口仍有缺口 | 复核设备显示调用；继续对照其他 selector 的实际消费者与返回契约 | [渲染核查 §3](../analysis/2026-11-12-rendering-runtime.md#3-selector-74-的输出)、[IOMFB selector §9](../analysis/2026-10-28-iomfb-selector-names.md) |
| G9 | 长帧与真实触摸延迟 | CRC 已完成对照与部署，短窗口显示完成加快；控制中心收回与持续交互帧率尚未验收 | 基于 S9 已验证版本，分开测起手、拖动、抬手动画及面板完成；真实触摸 9.3 ms 间隔与 240 Hz 报告率需独立确认 | [性能回退](../progress/2026-11-08-performance-regression.md)、[开机次序 §6.6](../progress/2026-10-31-boot-order-and-performance.md)、[系统待办 S9](system.md) |
| G10 | 大 attachment 与实际绘制面积 | 候选；局部重绘已默认开启 | 记录 draw scissor、GMEM load/store、CPU／GPU 转换与 scanout，按实际耗时选择优化 | [上游对照 §3.4](../analysis/2026-11-12-upstream-review.md#34-显示颜色绘制范围与-gpu-进度)、[120 Hz 长帧](../analysis/2026-11-02-120hz-after-gpu-clock.md) |
| G11 | GPU 挂起判据 | 候选；A830 使用 HWSCHED，上游 A740 ring 恢复路径不同 | 检查最后一次提交的命令流与 BR／BV／LPAC／GMU 快照，覆盖部分单元有进度、全部无进度和有界失败恢复 | [上游对照 §3.4](../analysis/2026-11-12-upstream-review.md#34-显示颜色绘制范围与-gpu-进度) |
| G12 | 性能对照与可选画布 | 候选；828×1792 画布、逐 draw 计时和常量特化来自旧调研；用户已决定暂不更换壁纸 | 先取得当前固定动作的时序；画布改变需用户选择清晰度与帧率取舍，保留 1206×2622 基线 | [11-05 上游对照](../analysis/2026-11-05-upstream-lessons.md)、[架构审查 §21](../analysis/2026-11-08-architecture-review.md#21-用户决定)、[手势瓶颈](../analysis/2026-11-01-120hz-gesture-bottleneck.md) |
| G13 | prior_copy 根因说明 | 待核对；局部重绘已有实现与实测，文档对根因的归属与提交不一致 | 对照实际提交、加载产物和测试修正文档归属 | [系统契约](../analysis/2026-11-12-system-contracts.md)、[发热与管线记录](../progress/2026-11-09-thermal-and-pipeline-optimization.md) |
| G14 | 面板物理尺寸核对 | 待确认；旧资料同时出现 1156×2510 与 1200×2608 | 核对当前面板模式、DSI／DPU 配置与实际扫描尺寸，保留 iOS 画布尺寸的区别 | [状态栏布局 §6.2](../analysis/2026-11-02-status-bar-layout.md) |
| G15 | GPU 提交、压缩与编译开销 | 性能候选；提交批处理、UBWC、GMEM 选择及编译任务并行均需测量依据 | 先测当前提交、load/store、编译和缓存耗时，再选择批处理、UBWC、GMEM autotune、缓存预生成或编译 worker；逐项对照画面和帧时 | [架构审查 §6、§7.1](../analysis/2026-11-08-architecture-review.md) |
| G16 | QuartzCore 未核对的调用 | 条件候选；is_ready、GLESContext、EAGLServer 的旧分析仍有空缺 | 当前故障或消费者需要这些接口后，再核对虚表、调用条件和返回值；记录系统版本与具体调用点 | [QuartzCore 静态分析 §8](../analysis/2026-10-29-quartzcore-vtable-26.md) |
