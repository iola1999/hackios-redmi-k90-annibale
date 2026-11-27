# 多媒体待办

本表集中相机、视频与音频的剩余工作，2026-11-27 同步批 1～批 15a 实测与审核更新。当前多媒体批次持续更新[验证结果](../analysis/2026-11-11-multimedia-validation.md)，实现状态、运行产物和轮次结果以该文为准。其他主题见[待办入口](README.md)。

## 1. 当前验证

| 编号 | 事项 | 当前边界 | 下一步与验收 | 来源 |
|---|---|---|---|---|
| M1 | Iris 硬件解码出帧 | 周期 H.264、非周期 270 帧 AVPlayer 播放（11-24）、1080p H.264 300 帧、HEVC Main 8 位（`320×192`、`322×194`）、Main 10 系统播放器 12 帧（`cfec166`）及 VPU 停机断电（`7a5a57fb`）均已验证。批 11/13 已完成两项剩余缺口修复并通过宿主验证（待真机专轮复核）：① 中途排空切片 1（`1bf8e11f`/`17929ae`：`iris_finish_drain()` 等两条 `HFI_CMD_RESUME` ACK，`videotoolbox_iris.c` 跳过重复 `FLUSH` 并重置 `sent_params`）；② 原生 Main 10 `P010` 切片 2（`#417`/`#422`：`IRIS_IOVA_SESSION_STRIDE` 扩至 `96 MiB`，`annibale_iris_hfi.c` 放行 HEVC `0x000a000au` + `iris_reconfigure_p010()` 切 `HFI_COLOR_FMT_P010=4u` 与 2 B/像素 stride，`videotoolbox_iris.c` 放行 `hvcC` `2/2` 协商 `'x420'`，`test-iris-hfi-wire.py --mutations` `208+24` 用例 + `91` 项变异与 `COMPILE_ONLY=1` 通过） | 真机专轮复核切片 1 中途排空与切片 2 原生 HEVC Main 10（`'x420'`）出帧；保持 DMA 停止、TLB 同步及 HELD 保护 | [完整验收](../analysis/2026-11-11-multimedia-validation.md#89-iris-完整像素与播放验收)、[硬解后停机与 HEVC 像素](../analysis/2026-11-11-multimedia-validation.md#121-播放结束后的-vpu-停机11-24)、[Main 10 选择](../analysis/2026-11-11-multimedia-validation.md#122-hevc-main-10-的系统播放与解码器选择11-24) |
| M2 | 真实相机流与 DMA | 前摄 `OV20B40` 连续流（`1,404` 帧零超时）、后摄 `OV50E40` 连续流（`3,000` 帧 `29.9 fps`）、`system_cache_cfg` 整帧写入（`6e902c09`）与曝光滞后消除亮度循环（`c9cc846c`）均已验证 | 复核场景明暗大幅变化时的曝光收敛，单独测量前摄曝光；保持 DMA 停止与缓存同步保护 | [相机管线与 ISP 修复](../analysis/2026-11-17-camera-pipeline-and-isp-fixes.md)、[11-21 真机体验问题 §11、§12](../progress/2026-11-21-user-test-issues.md#11-后摄条纹cam-1) |
| M3 | 扬声器实际出声与音量控制 | `AudioReach` 常驻喂数与双路 TFA9866（`operating`）已合入 Wave 1，AAC AudioQueue 本地播放、HLS 与 `1 kHz` 环回音调通过；11-27 确认顶部 `'RCV'`（`0x36`）接 slot 0（左声道）、底部 `'SPK'`（`0x34`）接 slot 1（右声道），`annibale_buttons.c:331` 与 `input26_service.c:269,677` 成对上报 `0x0C:0xE9/0xEA`（`BUILT_IN=1`）。批 15 只读反汇编 `23G90`（`#498`/`#516`/`#526`）定位 `0.50` 默认回退（`pvmGetDefaultVolume` `0x1b3ab9560` / `0x1b3be28c8` `fmov s0, #0.50`）与 `didNotChange`（`MXSMPerformVolumeOperation` `0x1b3aae584` `[sp, #0xc5]=1`，取决于 `MXSM_checkFigVol` `{1,3,4}`、`CMVAEndptMgr`/`VAEM_CurrentRouteHasVolumeControl` 与 `VAE_PortID`）；`audio_plugin.c` 已实现 `OBJECT_SPEAKER`/`OBJECT_SPEAKER_VOLUME` 并经 `unknown()` 记录未实现选择器 | 在交互窗口运行 `sound_test route` 并触发音量减键，同步抓取 `audio_plugin` `unknown()` 输出与 `MediaExperience`/`audiomxd`/`SpringBoard` 日志，先实测命中路径再补齐缺失属性或控制类，并人工听辨左右声道与上下扬声器方向 | [多轮代码审查 §1](../analysis/2026-11-15-code-and-commit-review.md#1-真机回归与系统应用闪退根因)、[11-24 交接 §4](../progress/2026-11-24-handoff.md#4-基本功能与其他渲染回归) |
| M4 | 冷启动播放器与 Safari 视频 | Safari 正文、JS 交互与断网重连已在 `b5r18`（`U7`）全部验证通过；新开机首项媒体测试静音 H.264 到片尾已通过，带音频冷启动播放与偶发打开失败仍待验证 | 复核带音频的首次播放、容器 token 消费、目标 DSP 帧归属与输出设备 ID；新失败需保留原生 NSError | [批 7 进展 §2](../progress/2026-11-27-batch7-user-visible.md#2-b5r18-四判决11-27-下午pre-0024-基线稳定轮-41-分钟)、[网页硬解播放](../analysis/2026-11-11-multimedia-validation.md#90-safari-正文与网页硬解播放) |

NV12／P010 的 BT.601／709／2020、有限域／全域 12 组 GPU 色值检查已经通过，原版 SLM 两条管线构造也已通过。这些结果用作后续回归基线。

## 2. 可选择的后续事项

| 编号 | 事项 | 状态与前提 | 下一步与验收 | 来源 |
|---|---|---|---|---|
| M5 | 视频纹理生命周期与边界尺寸 | 候选；双平面直接采样已有实现 | 奇数宽高、不同 plane stride、在途命令持有 IOSurface、按需转换与释放，要求像素和资源生命周期正确 | [上游对照 §3.5、§5](../analysis/2026-11-12-upstream-review.md) |
| M6 | 相机拍照、前摄 `-16808` 与画质调校 | 后摄拍照（`F1` 队列 `14ba138`、`tl: C` + 蜂群治理 `2 pieces QOS_CLASS_UTILITY`）、对焦（`GT9764V` `10.8 ms` 子步与矩阵外接框）、曝光补偿、强制闪光回读及前摄 `30 fps` NEON 满帧（`c97f3a3`）和 `180` 安装角（`b5r7`/`b5r8`）均已验证。仍余三项：① 前摄拍照 `-16808` 经反汇编 `BWE5InferenceProvider.m:263`（`0x1aee561c0..0x1aee565e8` -> `_e5rt_execution_stream_operation_create_precompiled_compute_operation_with_options` 报 `-31710`）确认全程走预编译算子且 `Smart Camera Inference Node` 先加载自身 H18-only `smartcam` 预编译 E5 模型而中止（`b5r16` 仅覆盖 `personsemantics`）；② `tl:l` 出片后 `62–124 ms` 缺口与 `30 fps` 亮室闪光复测；③ 暗光／室外／照片偏色（`U21`）需人工中性面复核，马达异响需人听确认 | 为 `Smart Camera Inference Node` 加载的全部预编译 E5 模型补齐 CPU 预编译包并核实 `sharedANEMemoryProvider != nil` 兼容性；在 `30 fps` 亮室复测闪光峰值与蜂群治理；补充暗光／室外／中性面实拍验收 | [批 3 进展](../progress/2026-11-25-batch3-camera-input.md)、[批 5 进展 §14、§21](../progress/2026-11-25-batch5-ane-fallback.md#14-前摄安装角定案-180文字靶标终验)、[批 6 进展 §4、§7、§11](../progress/2026-11-26-batch6-stall-verdict.md#11-b5r16-判决与-slab-审计收口11-27-凌晨) |
| M7 | 相机硬件资料核对 | 256 字节条纹根因已由 `system_cache_cfg` 复位（`6e902c09`）结案，TFE2 单帧验证已写全整帧；`TFE2` 路径保留作为以后需要硬件 ISP 处理时的选项 | 需要硬件 ISP 管线时再启用并核对 `TFE2` 完整路径 | [相机管线与 ISP 修复 §2、§3](../analysis/2026-11-17-camera-pipeline-and-isp-fixes.md#2-前摄供电连续流与停流复位修复)、[11-21 真机体验问题 §11](../progress/2026-11-21-user-test-issues.md#11-后摄条纹cam-1) |
| M9 | 固件异步失败与 UEFI SCM 阶段 | 研究候选；尚未确定与 Iris fatal 同因 | 验证首次失败后迟到完成不能恢复成功状态；先确认实际启动是否执行 ExitBootServices，再检查 SCM 回调契约 | [上游对照 §4.2、§6](../analysis/2026-11-12-upstream-review.md) |
| M10 | 录像与多摄功能 | 后续候选，依赖真实采集与保存通过 | 录像、多摄、HDR／多帧、AON、硬件 ISP 各自评估依赖与范围，选定目标后再安排实现 | [相机路线 §4.3](../plan/camera-plan.md#43-分级路线) |
| M11 | SLM 管线探针耗时 | 待拆分；slm_calc_eyes 探针总耗时 47,705 ms，同轮 IR3 等待 60.637 ms，探针仅创建管线与反射 | 分开计时设备初始化、库读取、AIR→NIR→IR3 管线编译、反射及销毁；实际 dispatch 需要另行测量 | [多媒体验证 §19](../analysis/2026-11-11-multimedia-validation.md#19-正常频率下的独立功能验证) |
| M12 | 软件解码覆盖与线程开销 | 后续候选；已有 H.264／VP9 路径，AV1 和线程调整按实际需求评估 | 先确认格式、解码器选择和冷启动故障，比较吞吐、CPU、同步及播放结果 | [视频分析 §6](../analysis/2026-11-05-video-decode.md) |

当前按真实传感器、DMA、原生会话和用户可见结果分阶段验收，设备访问与恢复条件遵循[真机手册](../plan/device-test-playbook.md)。蓝牙音频的连接与传输前提见[外设待办](platform.md)。

## 3. 已解决归档

| 编号 | 事项 | 解决结论与验证范围 | 来源 |
|---|---|---|---|
| M8 | 默认麦克风录音（DMIC0） | 11-24（`say52-ubo54`，内核 `6e19aa93`、用户态 `082040c`）锁定 `TX macro dec1` + `RXTX TX_CDC_DMA_TX_3`，`record_test` 保存 5 s WAV、`micloop_test` `1 kHz` 环回净增 `89.5 dB` 验收通过；其余多麦（`dmic23/45`）与立体声映射按需补充 | [11-24 麦克风录音验证](../progress/2026-11-24-mic-m8-resolved.md) |
| M13 | IOSurface copy wrapper 别名读写 | 批 14（`#454`/`#457`）在 `air_metal_texture.inc`（714 行）、`air_metal_copy.inc`（296 行）与 `air_metal.c` 新增 `buffer_texture_sync_aliases()` 并把 `rwa_buffer_textures_refresh()` 拆为两阶段：对同一 `rwa_buffer` 或共享 `mirror` 重叠区间的写后读先下载写端再经 `mirror_read()` 刷新目标映射，`!t->backing || written_buffer_textures == 0` 快速路径保持只读相机输入零额外开销；`test-air-surface-alias.py`（ASan+UBSan `-Werror`）、`test-air-rwa-lock-narrowing.py`（TSan + ASan+UBSan）与 `arm64e` 编译均通过 | [多媒体验证 §36](../analysis/2026-11-11-multimedia-validation.md#36-进程自有-iosurface-的相机输入) |
| M14 | 相机对焦框闪烁与 `FocusNow` | `b5r4`（用户态 `00cfcc4` 补写 `FocusPeakSumArray` + `f3a3d4e` `AFStatus`）真机验证三次点按依次生成 `CommandID 3/4/5`、对焦框 `+1.6 s` 出现 `+3.7 s` 消失符合原生节奏；后续仅动态场景连续对焦与相位对焦像素读出列为 `M6` 可选优化 | [11-21 真机体验问题 §4](../progress/2026-11-21-user-test-issues.md#4-开发分支上的复现结果)、[批 5 进展 §9](../progress/2026-11-25-batch5-ane-fallback.md#9-方向与对焦修复) |
| M15 | `format 5` 构图触发 `cameracaptured` 崩溃 | 生产代码已在用户态 `2632484`（`camera_formats_ios26.inc` `populate_outputs`）补齐 `IntermediateTap` 输出项；11-27 补齐 `test-camera-device-ios26.py` 全量格式 `IntermediateTap` 与 `FormatIndex=5` 回归用例（`2/2` 成功、`build.sh` 编译通过）；真机 `format 5` 专项切流可随后续相机轮抽检 | [批 6 进展 §5](../progress/2026-11-26-batch6-stall-verdict.md#5-format-5-崩溃新发现已入-backlog-m15) |
