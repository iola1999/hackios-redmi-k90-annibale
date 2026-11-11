# 多媒体待办

本表集中相机、视频与音频的剩余工作，2026-11-12 整理。当前多媒体批次持续更新[验证结果](../analysis/2026-11-11-multimedia-validation.md)，实现状态、运行产物和轮次结果以该文为准。其他主题见[待办入口](README.md)。

## 1. 当前验证

| 编号 | 事项 | 当前边界 | 下一步与验收 | 来源 |
|---|---|---|---|---|
| M1 | Iris 硬件解码出帧 | 进行中；hardware=1 会话已创建，首帧仍为固件 fatal；错误回调与 drain 已通过 | 对照 HFI 会话、缓冲类型、布局与响应，要求实际硬件解码帧、像素内容和连续播放通过 | [多媒体验证 §18](../analysis/2026-11-11-multimedia-validation.md)、[视频分析](../analysis/2026-11-05-video-decode.md) |
| M2 | 真实相机流与 DMA | 进行中；前后传感器 ID、设备枚举、SLM 与眼镜景深管线通过，RG16 导入修复后 MPS 滤波已执行；相机后续仍退出 | 先处理 heap protectionOptions、Core Image stitching 与剩余 cospi 指令，见[图形待办 G7／G14](graphics.md)；同轮核对 sensor streaming、CSI／CSID 帧边界、IFE stride、DMA 地址与 ready 顺序、首尾行真实像素 | [多媒体验证 §7、§19、§24](../analysis/2026-11-11-multimedia-validation.md)、[上游相机对照](../analysis/2026-11-12-upstream-review.md#21-相机-dma-提交顺序与像素布局) |
| M3 | 扬声器实际出声 | 待验证；AudioQueue、PCM 完成及双功放 operating 已有结果 | 先核对功放配置与软件保护；缺少 DSP 扬声器保护的首次出声按原调研使用低增益并由人在场确认。冷启动播放已知音频，结合路由、PCM 完成和听音验收左右声道与音量 | [多媒体验证 §2](../analysis/2026-11-11-multimedia-validation.md)、[音频分析](../analysis/2026-11-02-audio-and-volume.md) |
| M4 | 冷启动播放器与 Safari 视频 | 待验证；预热后本地播放已有结果，冷启动等待与 CoreMedia XPC 超时未完成验收 | 对照冷启动／预热的会话、缓冲及进程状态，要求本地完整播放和网页播放；软解与硬解分别标明 | [音频与组件诊断 §2、§3](../progress/2026-11-08-audio-widget-diagnostics.md)、[多媒体验证](../analysis/2026-11-11-multimedia-validation.md) |

NV12／P010 的 BT.601／709／2020、有限域／全域 12 组 GPU 色值检查已经通过，原版 SLM 两条管线构造也已通过。这些结果作为后续回归基线。

## 2. 可选择的后续事项

| 编号 | 事项 | 状态与前提 | 下一步与验收 | 来源 |
|---|---|---|---|---|
| M5 | 视频纹理生命周期与边界尺寸 | 候选；双平面直接采样已有实现 | 奇数宽高、不同 plane stride、在途命令持有 IOSurface、按需转换与释放，要求像素和资源生命周期正确 | [上游对照 §3.5、§5](../analysis/2026-11-12-upstream-review.md) |
| M6 | 相机拍照与调校 | 未验收，依赖 M2 真实预览 | 核对厂商模式和调校数据、全幅输出、黑电平／AWB／AE／CCM、点按对焦及拍照保存 | [相机路线](../plan/camera-plan.md)、[多媒体设计](../analysis/2026-11-11-multimedia-root-causes-and-design.md) |
| M7 | 相机硬件资料核对 | 研究候选；旧设备树待办需结合当前芯片 ID 重核 | 核对 sensor 供电 phandle、PMIC LDO／SPMI、camcc 时钟 ID、TLMM GPIO 及当前使用的 sensor 模式 | [相机路线 §3、§4](../plan/camera-plan.md)、[硬件图谱 §12](../analysis/annibale-hw-map.md) |
| M8 | 麦克风与录音 | 未验收；输入路径与播放分别检查 | 核对音频输入硬件、DMA、HAL 格式与时间戳，验证录音内容及停止恢复 | [音频分析](../analysis/2026-11-02-audio-and-volume.md)、[架构审查](../analysis/2026-11-08-architecture-review.md) |
| M9 | 固件异步失败与 UEFI SCM 阶段 | 研究候选；尚未确定与 Iris fatal 同因 | 验证首次失败后迟到完成不能恢复成功状态；先确认实际启动是否执行 ExitBootServices，再检查 SCM 回调契约 | [上游对照 §4.2、§6](../analysis/2026-11-12-upstream-review.md) |
| M10 | 录像与多摄功能 | 后续候选，依赖真实采集与保存通过 | 录像、多摄、HDR／多帧、AON、硬件 ISP 各自评估依赖与范围，选定目标后再安排实现 | [相机路线 §4.3](../plan/camera-plan.md#43-分级路线) |
| M11 | SLM 管线探针耗时 | 待拆分；slm_calc_eyes 探针总耗时 47,705 ms，同轮 IR3 等待 60.637 ms，探针仅创建管线与反射 | 分开计时设备初始化、库读取、AIR→NIR→IR3 管线编译、反射及销毁；实际 dispatch 需要另行测量 | [多媒体验证 §19](../analysis/2026-11-11-multimedia-validation.md#19-正常频率下的独立功能验证) |
| M12 | 软件解码覆盖与线程开销 | 后续候选；已有 H.264／VP9 路径，AV1 和线程调整按实际需求评估 | 先确认格式、解码器选择和冷启动故障，比较吞吐、CPU、同步及播放结果 | [视频分析 §6](../analysis/2026-11-05-video-decode.md) |

当前按真实传感器、DMA、原生会话和用户可见结果分阶段验收，设备访问与恢复条件遵循[真机手册](../plan/device-test-playbook.md)。蓝牙音频的连接与传输前提见[外设待办](platform.md)。
