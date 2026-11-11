# 多媒体验证结果与剩余问题（2026-11-11）

本文记录音频、相机和视频候选的真机结果。实现与首批宿主测试见[多媒体适配进展](../progress/2026-11-11-multimedia-bringup.md)，底层接口分析见[多媒体根因定位及架构设计](2026-11-11-multimedia-root-causes-and-design.md)。编译、设备初始化和用户可用行为分别验收。

## 1. 已执行候选

| 轮次 | 内核记录 | 结果 |
|---|---|---|
| mm1 | `12377-multimedia-1111` | 约 38.2 秒出现 `Unhandled implementation specific error`，自动恢复 loader 空闲态 |
| mm2 | `12377-multimedia-1111b` | 约 38.9 秒出现同类 panic，自动恢复 loader 空闲态 |
| mm3 | `12377-multimedia-1111c` | 约 31.5 秒出现同类 panic，自动恢复 loader 空闲态 |
| mm4 | `12377-multimedia-1111d` | 约 39.8 秒出现同类 panic，自动恢复 loader 空闲态 |
| mm5 | `12377-multimedia-1111e` | 采样 408.4 秒，未捕获 panic；主动停止后恢复 `xnuloader / idle`，启动卷常驻区为空 |

上述结果来自本地 `docs/progress/evidence/k90auto/` 下各轮的 `returned.log`、`reboot.json` 和 `cycle-mm*.out`。mm5 的最后收尾查询在 12:40 返回空闲；后续独立启动需要重新读取状态。

## 2. 功能验收范围

| 项目 | 已验证 | 剩余问题 |
|---|---|---|
| 音频 | AudioQueue 启动与音频会话激活成功；48,000 帧交付和直写成功；AudioReach 两路图启动，PCM 完成计数持续增长，双功放进入 operating 状态 | 扬声器实际出声、冷启动系统播放器与网页播放待确认 |
| 本地视频 | H.264／HEVC 各解码 30 帧，像素检查通过；本地 H.264 播放 22 帧，首帧 1277 ms，无像素错误或停顿 | 上述解码未要求硬件，Safari 等实际场景待验证 |
| Iris 硬解 | `/dev/annibale-iris` 与固件可发现 | `VPU not ready flags=0x3`；测试为 `hardware=-1 require_hardware=0`，硬解未通过；日志缺少初始化阶段输出，首个失败阶段待定位 |
| YUV 合成 | 8-bit BT.601／BT.709 的有限域和全域四组像素检查通过 | P010／BT.2020 尚无真机结果 |
| 相机 | 枚举两台设备，可读取软件测试帧 | `CPAS=0`、`titan_top=0`、`clks=0`，前后传感器 ID 为 `0x0000`；真实传感器流和 DMA 尚未验证；`cameracaptured` 在 `MakeBlurMap` 的 `_slmMinMax` 断言处退出 |
| 界面巡检 | 截图覆盖启动、锁屏与主屏 | 后段主屏背景为黑色，多组操作后的截图无变化，设置、控制中心和通知中心巡检未验收 |

相机源码中的 `cam_hw_dma_verified` 和 `cam_sensor_streaming` 保持 `false`，读取测试帧只验证软件路径。后续相机验收必须同时取得传感器身份、出流状态和真实帧内容。

## 3. 接续验证

- Iris：把初始化日志写入 loader 可采集的内核日志，记录电源时钟、SMMU、PAS 和 HFI 的开始与失败阶段；下一轮使用 `video_decode_test --require-hardware`。
- 相机：先检查 GCC 相机 AHB／XO 与 MCLK 时钟，再检查电源、传感器身份与 CSI／DMA；另行分析 `_slmMinMax` 对应的 Metal 计算管线失败。
- 音频与显示：合并音频提交、功放状态、本地播放、亮度和界面巡检，保留需要用户确认的声音与面板观察项。
- 每批最多三轮，读完本批结果后调整测法或单一变量，再继续下一批。每轮收尾核验 `xnuloader / idle` 和空的启动卷常驻区。

## 4. 产物与工具边界

mm5 内核 SHA-256 为 `dc13b6ec4e966fa7a6c0551f1f3eda969256efa6f74b2ace9f2abbbd90ca1ed1`，实际构建树是 `hackios-xnu-kernel/xnu-src/xnu-12377.121.6`。接手检查确认五个未提交移植源文件与该树对应文件一致。

无人值守恢复已加入运行态停机、静默后复位、重新枚举与 `oem recovery`。恢复命令失败、空序列号、身份不符或常驻区未清空均需要停止后续命令并保存现场。

当前 loader 的槽位查询仍返回固定值，无法据其返回的重试计数判断 GPT 实际预算。刷入前通过 LK 查询并恢复实验槽位；loader 的真实槽位查询还需核对 Qualcomm 属性位定义后实现。
