# 多媒体待办

本表集中相机、视频与音频的剩余工作，2026-11-13 整理。当前多媒体批次持续更新[验证结果](../analysis/2026-11-11-multimedia-validation.md)，实现状态、运行产物和轮次结果以该文为准。其他主题见[待办入口](README.md)。

## 1. 当前验证

| 编号 | 事项 | 当前边界 | 下一步与验收 | 来源 |
|---|---|---|---|---|
| M1 | Iris 硬件解码出帧 | 周期 H.264 的完整像素、时钟及会话关闭通过；非周期常规离线 270 帧匹配，首包后公共 Finish 复现 AVPlayer 首 GOP 的 27 帧像素错误及两帧缺失；RAW 发布先于 RESUME 的候选取得完整 270 回调，错误帧散列及缺帧与原测试一致；七次回调完成后公共 Finish 返回成功，270 帧匹配，实际中途 DRAIN 未发生；实际创建位于 videocodecd，服务端库 UUID 待确认；完整默认生产内核上机待复核 | 核对排空后的参考状态、缓冲所有权及实际服务端库，形成有原厂来源的修复；复核完整默认生产内核；继续验证 HEVC 等格式和边界尺寸，保持 DMA 停止、TLB 同步及 HELD 保护 | [首包 Finish 对照](../analysis/2026-11-11-multimedia-validation.md#905-首包-finish-的离线对照)、[七次提交后的 Finish](../analysis/2026-11-11-multimedia-validation.md#908-七次提交后的公共-finish)、[恢复顺序结果](../analysis/2026-11-11-multimedia-validation.md#906-排空恢复的输出发布顺序)、[执行进程](../analysis/2026-11-11-multimedia-validation.md#907-原生解码的执行进程)、[完整验收](../analysis/2026-11-11-multimedia-validation.md#89-iris-完整像素与播放验收)、[生产时钟](../analysis/2026-11-11-multimedia-validation.md#86-时钟生产集成与默认构建) |
| M2 | 真实相机流与 DMA | 连续三帧及完整 RAW 读回通过；原生打开、profile 安装与首帧成功；9 次观测属性均返回 0，控制请求后的必需 Clock、ModuleInfo 读取未出现；Front Generic 原流成功，未观察到 Video initializer，六路输出配置为空，预览仍黑；A5 单帧与复制前物理页缓存同步均确认全部原零块后半段保留预填值；用户确认正常室内、前摄无遮挡，真实场景仍无法辨认，后摄 formats 为空 | 核对 Source 选择、激活及 graph 初始化的原生返回，修复可见预览；核对实际厂商 WM 的写入配置、DMA 范围与缓存可见性，再核对曝光及真实场景；保持停止与同步保护；后摄核对厂商 profile 和采集路径 | [Generic 请求范围](../analysis/2026-11-11-multimedia-validation.md#916-generic-stream-到视频包装器的调用范围)、[物理页同步结果](../analysis/2026-11-11-multimedia-validation.md#917-raw-复制前的物理页缓存同步)、[属性调用](../analysis/2026-11-11-multimedia-validation.md#914-控制请求后的属性调用)、[A5 预填范围](../analysis/2026-11-11-multimedia-validation.md#915-单帧-a5-预填的保留范围)、[连续 RAW 与预览](../analysis/2026-11-11-multimedia-validation.md#912-匹配载荷的连续-raw-与黑屏预览)、[上游相机对照](../analysis/2026-11-12-upstream-review.md#21-相机-dma-提交顺序与像素布局) |
| M3 | 扬声器实际出声 | 待验证；AudioQueue、PCM 完成及双功放 operating 已有结果 | 先核对功放配置与软件保护；缺少 DSP 扬声器保护的首次出声按原调研使用低增益并由人在场确认。冷启动播放已知音频，结合路由、PCM 完成和听音验收左右声道与音量 | [多媒体验证 §2](../analysis/2026-11-11-multimedia-validation.md)、[音频分析](../analysis/2026-11-02-audio-and-volume.md) |
| M4 | 冷启动播放器与 Safari 视频 | 新开机首项媒体测试的正文可读，非周期静音 H.264 首播到达 ended，重播画面推进到第 269 帧及 18 秒末位置；周期样本已有 Iris 解码 270 帧的归属统计；音频待验，此前一次打开失败的原因仍未知 | 复核带音频的首次播放、容器 token 消费、目标 DSP 帧归属与输出设备 ID；新的打开失败需保留原生 NSError | [新开机播放](../analysis/2026-11-11-multimedia-validation.md#903-新开机的首项媒体测试)、[网页硬解播放](../analysis/2026-11-11-multimedia-validation.md#90-safari-正文与网页硬解播放)、[输出与时钟](../analysis/2026-11-11-multimedia-validation.md#89-iris-完整像素与播放验收)、[音频与组件诊断 §2、§3](../progress/2026-11-08-audio-widget-diagnostics.md) |

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
| M13 | IOSurface copy wrapper 别名读写 | 已复现；不同 usage 创建的 copy 资源在同一 command-buffer 内写后读得到旧值，跨已完成命令的读写通过 | 核对可共享的 usage／资源布局与原生顺序，验证同一 IOSurface 多 wrapper 的写后读；修复期间保留只读相机输入的验收范围 | [多媒体验证 §36](../analysis/2026-11-11-multimedia-validation.md#36-进程自有-iosurface-的相机输入) |

当前按真实传感器、DMA、原生会话和用户可见结果分阶段验收，设备访问与恢复条件遵循[真机手册](../plan/device-test-playbook.md)。蓝牙音频的连接与传输前提见[外设待办](platform.md)。
