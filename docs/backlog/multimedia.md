# 多媒体待办

本表集中相机、视频与音频的剩余工作，2026-11-27 同步批 1～批 10 实测更新。当前多媒体批次持续更新[验证结果](../analysis/2026-11-11-multimedia-validation.md)，实现状态、运行产物和轮次结果以该文为准。其他主题见[待办入口](README.md)。

## 1. 当前验证

| 编号 | 事项 | 当前边界 | 下一步与验收 | 来源 |
|---|---|---|---|---|
| M1 | Iris 硬件解码出帧 | 周期 H.264、非周期 270 帧 AVPlayer 播放（11-24）、1080p H.264 300 帧、HEVC Main 8 位（`320×192`、`322×194`）、Main 10 系统播放器 12 帧（`cfec166`）及 VPU 停机断电（`7a5a57fb`）均已验证。11-27 推进两项剩余缺口：① 中途排空切片 1 已实现并通过主机复核（`annibale_iris_hfi.c` `iris_finish_drain()` 对 `HFI_PORT_BITSTREAM`／`HFI_PORT_RAW` 的 `HFI_CMD_RESUME` 逐条等待 `iris_wait_reply(..., 500u)` ACK 并传播错误码；`videotoolbox_iris.c` `iris_vt_finish_delayed_frames()` 记录 `drain_completed` 跳过重复 `IRIS_IOC_FLUSH_SESSION` 并重置 `sent_params = false`；`test-iris-hfi-wire.py` `204+24` 用例与 `COMPILE_ONLY=1` `build.sh` 通过），待真机复核；② 原生 Main 10 存在 4 处 8-bit 硬编码门控（`videotoolbox_iris.c:534,611` 拒 10-bit `hvcC` 且固定 `'420v'`/`1B` 步长、`annibale_iris_hfi.c:686,707` 仅放行 `0x00080008u` 与 `HFI_COLOR_FMT_NV12=1u`） | 先在真机复核切片 1 中途排空修复，再在专用轮推进切片 2（`0x000a000au` + `HFI_COLOR_FMT_P010` / `'x420'`）；保持 DMA 停止、TLB 同步及 HELD 保护 | [完整验收](../analysis/2026-11-11-multimedia-validation.md#89-iris-完整像素与播放验收)、[硬解后停机与 HEVC 像素](../analysis/2026-11-11-multimedia-validation.md#121-播放结束后的-vpu-停机11-24)、[Main 10 选择](../analysis/2026-11-11-multimedia-validation.md#122-hevc-main-10-的系统播放与解码器选择11-24) |
| M2 | 真实相机流与 DMA | 前摄 `OV20B40` 连续流（`1,404` 帧零超时）、后摄 `OV50E40` 连续流（`3,000` 帧 `29.9 fps`）、`system_cache_cfg` 整帧写入（`6e902c09`）与曝光滞后消除亮度循环（`c9cc846c`）均已验证 | 复核场景明暗大幅变化时的曝光收敛，单独测量前摄曝光；保持 DMA 停止与缓存同步保护 | [相机管线与 ISP 修复](../analysis/2026-11-17-camera-pipeline-and-isp-fixes.md)、[11-21 真机体验问题 §11、§12](../progress/2026-11-21-user-test-issues.md#11-后摄条纹cam-1) |
| M3 | 扬声器实际出声与音量控制 | `AudioReach` 常驻喂数与双路 TFA9866（`operating`）已合入 Wave 1，AAC AudioQueue 本地播放、HLS 与 `1 kHz` 环回音调通过；11-27 确认顶部 `'RCV'`（`0x36`）接 slot 0（左声道）、底部 `'SPK'`（`0x34`）接 slot 1（右声道），且 `annibale_buttons.c:331` 与 `input26_service.c:269,677` 成对上报 `0x0C:0xE9/0xEA`（含按下／抬起／时间戳／`BUILT_IN=1`）均无结构缺口，CoreAudio 软件音量模式下 `0.50` 断点收敛到 `SBVolumeControl -> AVSystemController -> audiomxd` XPC/路由环节 | 真机触发音量减键并同步抓取 `SpringBoard`（`SBVolumeControl`/`AVSystemController`）与 `audiomxd` 日志定位拒绝原因，并人工听辨确认左右声道与上下扬声器方向 | [多轮代码审查 §1](../analysis/2026-11-15-code-and-commit-review.md#1-真机回归与系统应用闪退根因)、[11-24 交接 §4](../progress/2026-11-24-handoff.md#4-基本功能与其他渲染回归) |
| M4 | 冷启动播放器与 Safari 视频 | Safari 正文、JS 交互与断网重连已在 `b5r18`（`U7`）全部验证通过；新开机首项媒体测试静音 H.264 到片尾已通过，带音频冷启动播放与偶发打开失败仍待验证 | 复核带音频的首次播放、容器 token 消费、目标 DSP 帧归属与输出设备 ID；新失败需保留原生 NSError | [批 7 进展 §2](../progress/2026-11-27-batch7-user-visible.md#2-b5r18-四判决11-27-下午pre-0024-基线稳定轮-41-分钟)、[网页硬解播放](../analysis/2026-11-11-multimedia-validation.md#90-safari-正文与网页硬解播放) |

NV12／P010 的 BT.601／709／2020、有限域／全域 12 组 GPU 色值检查已经通过，原版 SLM 两条管线构造也已通过。这些结果用作后续回归基线。

## 2. 可选择的后续事项

| 编号 | 事项 | 状态与前提 | 下一步与验收 | 来源 |
|---|---|---|---|---|
| M5 | 视频纹理生命周期与边界尺寸 | 候选；双平面直接采样已有实现 | 奇数宽高、不同 plane stride、在途命令持有 IOSurface、按需转换与释放，要求像素和资源生命周期正确 | [上游对照 §3.5、§5](../analysis/2026-11-12-upstream-review.md) |
| M6 | 相机拍照、前摄 `-16808` 与画质调校 | 后摄拍照（`F1` 队列 `14ba138`、`tl: C` + 蜂群治理 `2 pieces QOS_CLASS_UTILITY`）、对焦（`GT9764V` `10.8 ms` 子步与矩阵外接框）、曝光补偿、强制闪光回读及前摄 `30 fps` NEON 满帧（`c97f3a3`）和 `180` 安装角（`b5r7`/`b5r8`）均已验证。仍余三项：① 前摄拍照 `BWPhotoEncoderNode -16808` 定位在 `BWE5InferenceProvider`（`m:263`）加载 `LowResPersonSegmentationMask`（`H18.hwx` 仅 ANE），`hwx` 逆变换已产出 `personsemantics` CPU 部署包并验证 `25/25` overlay 覆盖，仍在 `Smart Camera Inference Node -31710` 失败；② `tl:l` 出片后 `62–124 ms` 缺口与 `30 fps` 亮室闪光复测；③ 暗光／室外／照片偏色（`U21`）需人工中性面复核，马达异响需人听确认 | 反编译 `BWE5InferenceProvider` `m:263` 打通前摄语义掩码执行；在 `30 fps` 亮室复测闪光峰值与蜂群治理；补充暗光／室外／中性面实拍验收 | [批 3 进展](../progress/2026-11-25-batch3-camera-input.md)、[批 5 进展 §14、§21](../progress/2026-11-25-batch5-ane-fallback.md#14-前摄安装角定案-180文字靶标终验)、[批 6 进展 §4、§7、§11](../progress/2026-11-26-batch6-stall-verdict.md#11-b5r16-判决与-slab-审计收口11-27-凌晨) |
| M7 | 相机硬件资料核对 | 256 字节条纹根因已由 `system_cache_cfg` 复位（`6e902c09`）结案，TFE2 单帧验证已写全整帧；`TFE2` 路径保留作为以后需要硬件 ISP 处理时的选项 | 需要硬件 ISP 管线时再启用并核对 `TFE2` 完整路径 | [相机管线与 ISP 修复 §2、§3](../analysis/2026-11-17-camera-pipeline-and-isp-fixes.md#2-前摄供电连续流与停流复位修复)、[11-21 真机体验问题 §11](../progress/2026-11-21-user-test-issues.md#11-后摄条纹cam-1) |
| M9 | 固件异步失败与 UEFI SCM 阶段 | 研究候选；尚未确定与 Iris fatal 同因 | 验证首次失败后迟到完成不能恢复成功状态；先确认实际启动是否执行 ExitBootServices，再检查 SCM 回调契约 | [上游对照 §4.2、§6](../analysis/2026-11-12-upstream-review.md) |
| M10 | 录像与多摄功能 | 后续候选，依赖真实采集与保存通过 | 录像、多摄、HDR／多帧、AON、硬件 ISP 各自评估依赖与范围，选定目标后再安排实现 | [相机路线 §4.3](../plan/camera-plan.md#43-分级路线) |
| M11 | SLM 管线探针耗时 | 待拆分；slm_calc_eyes 探针总耗时 47,705 ms，同轮 IR3 等待 60.637 ms，探针仅创建管线与反射 | 分开计时设备初始化、库读取、AIR→NIR→IR3 管线编译、反射及销毁；实际 dispatch 需要另行测量 | [多媒体验证 §19](../analysis/2026-11-11-multimedia-validation.md#19-正常频率下的独立功能验证) |
| M12 | 软件解码覆盖与线程开销 | 后续候选；已有 H.264／VP9 路径，AV1 和线程调整按实际需求评估 | 先确认格式、解码器选择和冷启动故障，比较吞吐、CPU、同步及播放结果 | [视频分析 §6](../analysis/2026-11-05-video-decode.md) |
| M13 | IOSurface copy wrapper 别名读写 | 已复现；不同 usage 创建的 copy 资源在同一 command-buffer 内写后读得到旧值，跨已完成命令的读写通过 | 核对可共享的 usage／资源布局与原生顺序，验证同一 IOSurface 多 wrapper 的写后读；修复期间保留只读相机输入的验收范围 | [多媒体验证 §36](../analysis/2026-11-11-multimedia-validation.md#36-进程自有-iosurface-的相机输入) |

当前按真实传感器、DMA、原生会话和用户可见结果分阶段验收，设备访问与恢复条件遵循[真机手册](../plan/device-test-playbook.md)。蓝牙音频的连接与传输前提见[外设待办](platform.md)。

## 3. 已解决归档

| 编号 | 事项 | 解决结论与验证范围 | 来源 |
|---|---|---|---|
| M8 | 默认麦克风录音（DMIC0） | 11-24（`say52-ubo54`，内核 `6e19aa93`、用户态 `082040c`）锁定 `TX macro dec1` + `RXTX TX_CDC_DMA_TX_3`，`record_test` 保存 5 s WAV、`micloop_test` `1 kHz` 环回净增 `89.5 dB` 验收通过；其余多麦（`dmic23/45`）与立体声映射按需补充 | [11-24 麦克风录音验证](../progress/2026-11-24-mic-m8-resolved.md) |
| M14 | 相机对焦框闪烁与 `FocusNow` | `b5r4`（用户态 `00cfcc4` 补写 `FocusPeakSumArray` + `f3a3d4e` `AFStatus`）真机验证三次点按依次生成 `CommandID 3/4/5`、对焦框 `+1.6 s` 出现 `+3.7 s` 消失符合原生节奏；后续仅动态场景连续对焦与相位对焦像素读出列为 `M6` 可选优化 | [11-21 真机体验问题 §4](../progress/2026-11-21-user-test-issues.md#4-开发分支上的复现结果)、[批 5 进展 §9](../progress/2026-11-25-batch5-ane-fallback.md#9-方向与对焦修复) |
| M15 | `format 5` 构图触发 `cameracaptured` 崩溃 | 生产代码已在用户态 `2632484`（`camera_formats_ios26.inc` `populate_outputs`）补齐 `IntermediateTap` 输出项；11-27 补齐 `test-camera-device-ios26.py` 全量格式 `IntermediateTap` 与 `FormatIndex=5` 回归用例（`2/2` 成功、`build.sh` 编译通过）；真机 `format 5` 专项切流可随后续相机轮抽检 | [批 6 进展 §5](../progress/2026-11-26-batch6-stall-verdict.md#5-format-5-崩溃新发现已入-backlog-m15) |
