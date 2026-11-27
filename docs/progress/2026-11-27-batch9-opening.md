# 批 9 开局：需求侧根因与测量基础设施修复

批 8 收官见 [批 8 文档](2026-11-27-batch8-opening.md) §9。批 9 主线按批 8 判决展开：GPU bo 分配的需求侧治理、黑窗残留形态取证、测量基础设施修复。

## 1. b5r27 判决（11-27 下午）

详细判读 `docs/progress/evidence/k90auto/kernel-12377-flipwd16-b5r27/RESULTS.md`。flipwd16（池 512+尺寸配额）+input26 空闲定时器修复组合轮。

- **池扩容部分命中**：复用率 22.0→45.4%，entry-cap 驱逐降 88.5%，tl:L 同手势段降 27%（88→64 次），commit 慢帧降 58%（12→5）。byte cap 取代 entry cap 成为新约束（byte-cap 驱逐 10370 vs entry-cap 5098），kept MB 峰值 159 顶到 160MB 上限。
- **submit 分段新读数**：room（管线深度等待）仍主导（557/640 事件），但 reap 偶发极大（max 58.7ms，24 事件主导）——大池的收割成本移入视野；backend submit 段 max 22.6ms。
- **空闲定时器修复验证通过**：三分钟稀疏注入无锁屏，测量轮不再需要微拖动维持唤醒。b5r25 黑窗判决确认为测量污染的推论得到交叉支持。
- **黑窗清洁复测**：持续黑扫描未复现。残留形态收窄为 Reminders 首冷开 3 帧黑闪（filmstrip 帧级证据在 `analysis/rec-reminders-cold-1/`），待离线定性。
- 回归全过：翻页 20/20、Safari 8/8、0029 普查十项零。

## 2. 需求侧根因定位（离线）

分析文档 `out/goal-1124/batch9/mesa-bo-cache-investigation.md`。Mesa bo cache/heap 代码与上游逐字节一致且启用，但吸收率远低于设计，三层叠加：

1. AIR 把 ≥4096B 的 MTLBuffer 全标 `PIPE_BIND_SHARED`（air_metal.c:976），SHARED bo 被 heap/cache/idle 三连排除——freedreno 移植将 shareable 按已共享处理，上游 agx 区分两者（agx_bo.h:18-35）。
2. ring flags 小 bo 五进程全轮次直达内核，heap 慢性穿透。
3. 命中链退化：遇忙即停+1-2s 过期+深队列退休延迟。

内核 gemNew 实测 42/s（峰值数百），健康基线应为每秒个位数。

## 3. 0030 修复实施（未验证）

userland `a308ac4`：新增 `_FD_BO_EXPORTED` 仅在 import/export 置位，cache/state/cpuPrep/submit 改按实际导出位判定缓存资格。主机侧补丁 dry-run、build-air.py、静态契约七项通过。真机 gemNew 命中与渲染回归未验证，并入下一轮组合验收。实施说明 `out/goal-1124/batch9/shared-bypass-fix.md`。

## 4. 当前入库状态

- 内核 `b863e000`：池 512+尺寸软配额（b5r27 已验证效益）；flipwd16 注册 sha256 `24b12101…`
- userland `1338ea2`（input26 空闲定时器修复，b5r27 已验证）+`a308ac4`（0030，未验证）
- TrollStore `582b283`：open 误报修复（b5r27 filmstrip 已正常录制）
- 设备停 loader idle，电池 96%

## 5. 批 9 待办（按优先级）

1. 0030 真机验证轮：gemNew 量级是否降至个位数/s、渲染回归、alias 正确性；同轮对照 tl:L 与 xfm 掉拍
2. reap 收割成本治理（58.7ms 偶发极大值，锁内执行）
3. byte cap 160MB 约束评估：扩容或配额调整（需求侧修复落地后重新评估，可能不再是约束）
4. Reminders 首冷开 3 帧黑闪定性（帧级证据已齐，离线分析）
5. 静止重绘 dirty region/全速重绘功耗线（批 8 欠账，仍欠）
6. sensors 线：bitbang 扫描已终结，剩设备树/persist 离线普查与 SE 引擎原生路径
