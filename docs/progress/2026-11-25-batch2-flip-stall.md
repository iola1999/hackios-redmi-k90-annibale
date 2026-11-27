# 批 2：U21 快门停顿修复与真停机制定位

两轮真机（flipwd 内核回归轮、F1 验机轮）与两处修复，对应用户问题 U21 及多轮日志中反复出现的亮屏卡死（与手势停顿同族）。

## 1. 真停机制（新增根因结论）

亮屏下画面定格 9.6~36.7 秒、随后自行恢复的事件，断点在显示控制器的翻页应答层，两段问题叠加：

1. **硬件侧**：`flip_point()` 向 CTL 写入 FLUSH 后，硬件偶发不清位（`INTF_FRAME_COUNT` 全程 ~120Hz 计数、面板 DCS 应答正常，说明时序引擎和面板处于运行状态）。卡住的具体原因待寄存器转储确认。
2. **内核侧**：`flip_latch()` 只在下一笔交换的 `show()` 里消费，而 presenter 空队列时无限期休眠；上游 backboardd 又等锁存确认才提交下一笔交换。观察与提交互相等待，一笔未应答的翻页锁住整条管线。

恢复样本：一次背光写后约 21ms pending 被观察。`dim_write()` 背光路径向 FLUSH 写入 `dim.flush | FLIP_CTL_FLUSH_CTL`，LM stage 位与卡住的 pipe 位不相交，置入新位后 CTL 服务该次 flush 时连带清掉旧位，即重新向 FLUSH 置新位是实际解开卡死的寄存器写。

### 修复（kernel `c80abfda`）

presenter 空转休眠在 `flip.pending` 置位时改为 25ms 限界休眠，超时复查：

- FLUSH 已清 → 按 `show()` 原路径消费锁存（`tl:l`、帧时间统计照常）；
- pending 超 2s 未清 → 转储 CTL layer/top/flush/start/intf/fetch 与 INTF1/2 的 status/engine/config/tear/autorefresh/read-pointer 一次，然后按验证过的恢复模式重发：`flip_point` 重描 + `dim_write` 重断言 mixers flush；此后每秒重发一次，8s 后停手交回下一笔交换自查。

**验证状态**：轮 5/轮 6 共 2400s 混合用例与 ~9 次息屏循环，看门狗 0 误报、0 多余转储；1500s 内未遇到真停事件，kick 路径与转储内容待下一次自然发生的事件确认。正常路径零行为差异（pending 由同线程复查，锁存消费代码原样提取为 `noteLatch`）。

## 2. U21 快门预览停顿（已修复）

用户报后摄快门后 142~149ms 预览停顿。根因：cameracaptured 的 worker 单线程被静帧 CPU 渲染（`StillImage 2352x1764`，约 106~112ms）占满，预览交付整窗断供。

### 修复（userland `14ba138`，F1）

Still* 输出改经每路 stream 自己的串行 dispatch queue，worker 只入队不再渲染；退出前排空。成片计数移到实际交付点，闪光灯在入队点熄灭。

**真机验证**（轮 6，三次快门）：渲染窗内预览 `tl:l` 最大间隔 17.4/23.9/68.2ms（基线 133.6ms 全程断供）；`pace:` giving pictures 回 16~19ms 区间；成片 HEIC 相册可开、闪光/对焦/前摄帧率无回归。

**残留**：出片完成后仍有 62~124ms `tl:l` 缺口——静帧编码与 PhotonicEngine 在共享 HFI context 上串行加 CPU 争抢，属另一机制，列为后续候选（原分析中的 F3/F4 方向）。

## 3. 证据目录

- `docs/progress/evidence/k90auto/kernel-12377-flipwd-round5/`：看门狗静默回归（600s 用例 + 900s 息屏循环）
- `docs/progress/evidence/k90auto/kernel-12377-flipwd-round6/`：F1 快门读数、成片验证
- 分析底稿（不入库）：`out/goal-1124/batch2/u21-shutter.md`、`stop-order.md`、`flip-watchdog.md`

## 4. 未决

- CTL 不清 FLUSH 的硬件侧原因（等看门狗转储自然触发后判读）
- 前摄 ~26.3fps：NV12 软解马赛克约 34ms/帧超 33.3ms 预算（同族 worker 占用问题，尚未修）
- 出片后 62~124ms 缺口（F3/F4 方向）
