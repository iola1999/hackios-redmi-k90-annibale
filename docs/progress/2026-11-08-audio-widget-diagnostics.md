# 2026-11-08 音频与组件冷启动诊断

这一轮使用两个独立候选，分别采集音频完成通知、原生与 Safari 播放对照，以及组件冷启动的首个异常 draw。原始日志与截图、缩略图和设备命令保存在本地忽略目录 `docs/progress/evidence/storage-boot-device-1108/phase11/` 与 `out/widget-render-1108/widget-trace/coldstart-candidate/`。

## 1. 候选与验收边界

| 轮次 | 候选 | 唯一诊断变化 | 结果 |
|---|---|---|---|
| `audio-usertrap` | `e7e7df3b…` | 保留 DSP 与 HAL 候选，增加 `usertrap=1 applog=1` 和真实 PCM 完成摘要 | AudioQueue 与原生 Bunny 完整播放通过；Safari 仍失败并取得 `audiomxd` 异常栈 |
| `widget-coldstart` | `901e62ac…` | 保留 scissor-min Metal，冷启动注入有界 draw 缩略图采集 | 确认主屏后取得 112 张缩略图，定位 Calendar 首次黑底 draw |
| `audio-native-cold` | `e7e7df3b…` | 候选不变，取消 AudioQueue 和 PCM 预热，冷启动直接运行原生 AVPlayer | 首次请求延迟约 31 秒，正确解码后进入 waiting，80 秒总期限到期 |

两个候选均临时启动，未改写 `boot_a`。音频候选不含 format 500 片元修复，因此该轮 Safari 日志中的 NV12 format 500 纹理拒绝仍是已知变量，不能用于评价已验证的视频片元候选。

## 2. PCM 完成与原生 Bunny 播放

独立 AudioQueue 和直接设备写入分别完成 144000 帧提交。新摘要只在校验 `OP_WRITE_DONE` 的 opcode 与周期地址，以及 map handle 和状态字后递增；首个周期及之后每 50 个周期记录一次。

- 独立音频检查后，所有摘要均为 `sent == done`，没有 `PCM completion failed`。
- 原生播放及后续检查期间，完成摘要持续增长，最后记录为 4100/4100。
- 这证明 DSP 已返回真实 PCM 周期完成通知；扬声器实际听感仍需人工验收。

原生 AVPlayer 随后播放含 AAC 音轨的 60 秒 Bunny，进程退出码为 0。探针源码的返回 0 条件包括 ready 和 playing 成立，播放时钟必须前进并收到结束通知，同时要求有效视频帧非零且像素错误为零，因此本轮完整播放通过。日志前 600 行保留了 320 帧 NV12，全部为 640×360、`pixel_error=0`；后续输出达到 rwsh 行数上限，本轮不据此声称总帧数。本轮在原生播放前先执行了 AudioQueue 和直接 PCM 写入。

第三轮使用同一候选，冷启动后不执行 AudioQueue 或 PCM 预热，直接运行原生 AVPlayer。首个 HTTP 请求比进程启动晚约 31 秒，随后 ready 和 playing 成立，可见的 184 帧均为 `pixel_error=0`。播放时钟到约 18.5 秒后 `timeControlStatus` 从 playing 变为 waiting，最终在 84292 毫秒后以 124 退出。该轮 `audiomxd` 未崩溃，PCM 完成摘要达到 3000/3000。

两轮对照确认预热后的完整播放可重复验收项仅限于该初始化顺序；冷启动延迟和播放中等待在本轮仍未解决。后续定位与验收见[多媒体待办](../backlog/multimedia.md)。

## 3. Safari 的 CoreMedia XPC 超时

同一候选和同一 Bunny URL 在 Safari 中仍于约 31 秒后出现媒体错误 3，播放时间停在 0，只取得一个回调帧。原生 AVPlayer 的完整播放与 Safari 失败构成同候选对照。

`audiomxd` 在 Safari 失败时发生 SIGTRAP，`usertrap` 记录了真实异常地址：

- 运行时 PC 为 `0x19fe3ffc4`，shared cache slide 为 `0x8108000`。
- 去除 slide 后 PC 为 `0x197d37fc4`，位于 CoreMedia 的 `_FigUserCrashWithMessage` 中 `brk #1`。
- 调用方地址为 `0x197dcc65c`，对应格式化字符串 `****** Self-terminating due to XPC timeout Server %s Client %@ (%d) %s`。
- 其余已记录返回地址位于 libdispatch 和 libsystem_pthread。

本轮已定位到 CoreMedia 的 XPC 超时。后续请求与会话差异检查见[多媒体待办](../backlog/multimedia.md)。不能通过屏蔽断言或伪造媒体服务成功来通过验收。

## 4. Calendar 首个黑底 draw

冷启动解锁日志包含 `answer=1 locked_after=0`，但紧随命令的截图仍是启动画面，未据此放行。等待后重新截图，确认主屏及 Weather、Calendar 大组件均已出现，随后整理 23 份有重叠的日志快照。

采集覆盖 backboardd 的 `commit 863`、work 65～81，共 112 张缩略图。Calendar 区域的逐像素比较得到以下顺序：

| draw | 输入与输出 |
|---|---|
| work 65 | 输入仍为壁纸，输出首次变为统一 RGB 234 |
| work 66～69 | 输出保持 RGB 234 |
| work 70 | `pre0` 为 RGB 234，`out0` 首次变为 RGB 0 |
| work 71 以后 | 黑色被后续 draw 保留 |

首个异常点因此定位为 `commit 863 / work 70`，pipeline 为 `0x11413aa00`，54 个顶点，scissor 为 `632,369 446x446`。该 draw 使用 10 个纹理和 8 个 buffer，其中槽位 3 输入为 format 115 的 256×1 buffer。相同 pipeline 也出现在 Weather draw。

本轮静态复核尚未找到该 pipeline 的创建行，具体特化名仍未定。QuartzCore 通用 `TbdsA2Xhfcx_Isup_Isrc` 变体读取 `dest_0`，该输入使用 framebuffer fetch；RGB 234 被写成不透明黑也排除了纯 coverage 或 discard。后续结果见[framebuffer fetch 验证](2026-11-08-fbfetch-validation.md)与[组件密集采样](2026-11-08-widget-dense-transition.md)，剩余工作见[图形待办](../backlog/graphics.md)。

## 5. 设备状态与后续

三轮结束均正常执行 `oem stop`，loader 返回 `returned 1444016 0`，UFS 在途请求为 0，控制器已归还。临时 HTTP 视频服务已关闭。

后续工作见[多媒体待办](../backlog/multimedia.md)与[图形待办](../backlog/graphics.md)。
