# 11-24 批 1 测量轮：手势断点、黑带与功能回归

按「一轮一变量、同批最多三轮」跑完三轮真机测量：轮 1 基线、轮 2 同构建换仪表、轮 3 测量内核。原始产物在 Git 忽略的 `docs/progress/evidence/k90auto/kernel-12377-s21-rowhash-round{1,2}/` 和 `kernel-12377-s21-tlb-round3/`，各轮 `RESULTS.md` 在那里；专题分析在 `out/goal-1124/`（`gesture-split/`、`round1/`、`round2/`、`settings-band/hypotheses.md`）。本文只写结论与判别链。

## 1. 本轮改了什么

- 内核 `cd9d23c3`：`touch_lat=1` 时 `kFBMethodSwapBegin` 打 `tl: b ID PID TID NAME at US`，与 `tl: s`（SwapEnd）配对后可在「渲染服务器没收到事务」和「收到但 swap 卡住」之间判别。登记名 `12377-s21-tlb`，sha256 `9da18900`。
- `tools/k90auto/fb_filmstrip.py` `capture_live()`：stage 后校验 `RWREC003` 头；`loader_recording[0]` 会被 `kern.annibale.outbox` 复写，无头时从 loader 日志 `reserved ... at` 行回退真实 PA。此前录屏取回无头的根因。
- 载荷核对：交接记述的规范 AIR 前缀 `2d56f0c97572` 经 manifest 逐文件哈希证明实际构建于 userland `b7c518b`（散点修复与片元数组优化之前）。本次重建于 `ed1b53d` 的签名库 sha256 `ec215364f41d930d`，`build-air.py --check` 58/58 通过，三轮均使用它。

## 2. 逐项结论

### 手势停顿（U2/U15，主线）

- 轮 1 stalls.py 归因：动画中途 20~90ms 的 ≥25ms 停顿全部是 P 段（合成器交付）先迟，G 段 fence wait 只 1~12ms，GPU 从不是瓶颈；4~5s 级「停顿」是手势到位后的合法静止保持。
- 轮 2 inbox 内联把 dump 落点从 ~1.3s 压到 +10~40ms，首次采到动画窗内线程态：backboardd 提交线程（tid 517=`CA::WindowServer::IOMFBServer::thread_body`）11/16 份 RUNNING，即动画期合成器在正常干活。
- 轮 2 顺带三次看门狗 dump（裸 swipe 序列）：全是「冷管线 × page 滑」，滑动 370ms 内 0~1 个跟踪帧、首帧 194~411ms（cc 类滑仅 28~110ms）。dump 显示三进程全部线程等待态、GPU 零提交——断点在「backboardd 已派发触摸」与「渲染服务器收到事务」之间。vsync 是内核软件定时器（`armVSync`），静默期持续送达，排除时钟停走。
- 轮 3 `tl:b` 配对：v3 全部手势暗段内 b→s→latch 配对且 <70ms；慢动画 freeze（frame 1838，7 帧/410ms）内链路仍通、事务以 ~25~37ms 间隔到达——慢在**事务生产侧速率**（上游 CA/SpringBoard），渲染服务器收到即做。cc-down 的 138ms 首帧延迟发生在 SwapBegin **之前**，同属上游。
- 未判明：「1 帧后 ~1.1s 零提交」型冻结（轮 2 的 page-left/right 冷管线例）当时无 `tl:b`，尚不能区分「SpringBoard 没产事务」与「事务投递断」。下批候选：暗段 +80/+200ms 重定时 dump、`tl: split` 补时间戳、primer 触摸对照（本轮 primer 组 9.7ms 首帧已远快于冷管线组均值）。

### U4 打开设置的中下部黑带

- 轮 1 rec_stream 录制不含 `tl: rec` 判别字段（`MiniFramebufferRecord.inc` 流模式按设计省略，已核实源码），不可判；画面帧 153 帧无命中。
- 轮 2 rec_arm 三段（相机驻留冷开 101f、热开 57f、热开 scanout 78f）零命中；`bseq x==y` 仅伴 `band=-1..-1`（未变化帧合法跳绘），三假设嫌疑组合零次；DARK_FRINGE 帧证实打开动画压暗壁纸背景本构建健康。
- 轮 3 变体 B（打开动画 0.35s 处 SIGKILL Preferences 造「带伤快照」再开）：SplashBoard 快照文件无新写、取回两张主快照目检+band_detector 干净；重开录制出现 BLACK_FLASH ×2（帧 39/41，buf=0 全幅近黑帧，~17ms 间隔）——与 U4 常驻/滚动带不同形态。
- 结论：U4 在 5 种触发变体、约 6 段 arm 窗口下均未复现。最高权重解释是版本差——用户 v0.2.1（userland `2244410`）落后当前分支约三天，其间合入其真实命中的 `d8e05f9`（MapKit 崩溃）与 patch `0021`（GPU 停转），同会话 U5/U13 旁证打开动画内容异常只发生在该版本。挂起判据与回退路径（按 `2244410` 重建复测）见 `out/goal-1124/round2/u4-round3-plan.md` §5。

### 其余功能项（轮 1 测量，同版本短回归）

| 项 | 结果 |
|---|---|
| U13 提醒事项启动黑窗 | 未复现：冷开 55 帧录屏仅 1 帧过渡黑（缩放动画帧），欢迎页正常渲染 |
| S5 多任务卡片回「通用」 | 未复现：`drag 0.5 0.999→0.55` 首次实测进切换器，点卡回通用页同 PID |
| U7 Wi-Fi 关开+Safari | 未复现：UI 开关关开后自动回连 `166666666_5G`，example.com 正文完整 |
| U8 照片网格 | 未复现：146 张缩略图全填充、单张页正常 |
| 麦克风（M8 回归） | 通过：record_test -37.9 dBFS、micloop raw tone 98.9 dB 差 |
| U21 快门预览停顿 | **仍存在**：fb 帧间隔实测最大 133.6/132.9ms（与用户报 142~149ms 同量级；快门日志另见照片管线单 dispatch `ir3 wait` 118~152ms，GPU 串行队列被成片处理占用是嫌疑成因） |
| 前摄帧率 | ~26.3 fps（300 帧/11.5s，单照度） |

### 环境与工具

- run-auto 宿主在轮 1 中途无声退出（后台 shell 被回收），轮 2/3 改 nohup 保活后收尾完整（reboot.json/leave-running 写齐）。
- 屏幕 ~60s 自动锁屏在三轮都打断过动作（wake tap+unlock notify 恢复）；轮 3 有 4/6 次启动被 run-auto 判 frozen（`no_new_frame ~21s`），息屏静止与真卡死在串口判据上不可区分，attempt3 的 `max_frame_gap 194.3s` 未定论、已存疑标注。
- `rec_stream` 与 `rec_arm` 的字段差异、frames.jsonl 覆盖核对方法、wall/host 单调钟换算（`wall = host_monotonic + 1791913508.5`）已写进 `out/goal-1124/round1/graphics-review.md`。

## 3. 仍未复现/未测的条件

- U4：见上，按挂起判据处理；用户可回时建议在 v0.2.1 同版本复测或按 `2244410` 重建。
- U21 快门停顿：已成因收窄（GPU 队列被照片管线重 compute 占满嫌疑），未做明暗场/连拍多组。
- 手势暗段内「谁唤醒渲染链」：dump 全等态说明是上游没派活，但 SpringBoard 内部断点（手势识别→CA 提交）用户态不可见，需下一批的定向打点或 dsc 反编译确认 backboardd→SpringBoard 投递半跳。
- 轮 3 `tl:b` 属纯打点，行为路径零改动；`12377-s21-tlb` 仅用于测量，不作为发布候选。
