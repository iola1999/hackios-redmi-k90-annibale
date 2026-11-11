# 多媒体待办

本表集中相机、视频与音频的剩余工作，2026-11-12 整理。当前多媒体批次持续更新[验证结果](../analysis/2026-11-11-multimedia-validation.md)，实现状态、运行产物和轮次结果以该文为准。其他主题见[待办入口](README.md)。

## 1. 当前验证

| 编号 | 事项 | 当前边界 | 下一步与验收 | 来源 |
|---|---|---|---|---|
| M1 | Iris 硬件解码出帧 | 进行中；cd16 首条 fatal 明确为 COMV 数量 `host 8 < fw 18`，仍为零帧；原厂输入端口初始最小数量属性缺失 | 单变量验证输入订阅后的 `0x03000124=4`，保持 COMV 8，继续核对数量协商，再验实际解码像素和连续播放 | [多媒体验证 §30](../analysis/2026-11-11-multimedia-validation.md#30-iris-固件错误诊断)、[视频分析](../analysis/2026-11-05-video-decode.md) |
| M2 | 真实相机流与 DMA | 进行中；R16 `1C0h` 导入、CI label 与原版 CI 图数值通过；MPS 数组签名和 process-owned IOSurface 仍有缺口，真实 CSI／IFE DMA 尚未实现 | 验证 MPS 二维数组读取，修复 process-owned IOSurface 导入；按本机 CSID／IFE 契约实现 sensor streaming 与 DMA，再验首尾行真实像素 | [多媒体验证 §28、§31、§33、§34](../analysis/2026-11-11-multimedia-validation.md)、[上游相机对照](../analysis/2026-11-12-upstream-review.md#21-相机-dma-提交顺序与像素布局) |
| M3 | 扬声器实际出声 | 待验证；AudioQueue、PCM 完成及双功放 operating 已有结果 | 先核对功放配置与软件保护；缺少 DSP 扬声器保护的首次出声按原调研使用低增益并由人在场确认。冷启动播放已知音频，结合路由、PCM 完成和听音验收左右声道与音量 | [多媒体验证 §2](../analysis/2026-11-11-multimedia-validation.md)、[音频分析](../analysis/2026-11-02-audio-and-volume.md) |
| M4 | 冷启动播放器与 Safari 视频 | 进行中；冷启动及重复的零幅 AudioQueue／DSP 排空通过，首次 9.239 秒、重复 3.968 秒；路由名称乱码来自 console 的 7 位字符处理 | 分阶段对照 AVPlayer／Safari 冷启动，核对输出设备 ID 的原生含义，软解与硬解分别标明；本地完整播放与网页播放待验 | [多媒体验证 §32](../analysis/2026-11-11-multimedia-validation.md#32-冷启动音频的阶段与排空诊断)、[音频与组件诊断 §2、§3](../progress/2026-11-08-audio-widget-diagnostics.md) |

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
