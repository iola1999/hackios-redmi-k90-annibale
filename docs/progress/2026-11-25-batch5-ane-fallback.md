# 批 5：ANE CPU 回退验证与相机功能修复（2026-11-25）

批 4 把 mediaanalysisd 照片分析管线逐层闭合到 ANE 模型加载层，批 5 主攻这最后一层，同批推进相机对焦、前摄编码、GPU 配速三条支线。到 b5r3 为止的结论：ANE 加载层修复验证通过，执行层撞上跨进程复现的 Espresso `io_error`（status=-2），是 U8 唯一主线阻塞；相机链被证明硬依赖 ANE（`tunneled_ane_op` CPU 拒绝执行），scoped spoof 必须排除 cameracaptured。

## 1. 反编译判别的两个决定性结论

`out/goal-1124/batch5/ane-close.md`：Espresso 读 `kern.hv_vmm_present` 判 VM，命中后 `espresso_create_context` 把引擎改写为 0（CPU 平台）、设备 -1，load_network 层再强制 compute path。苹果自维护的生产路径，GPU/CPU 回退方向成立。

`out/goal-1124/batch5/espresso-status.md`：status=-2 是 io_error，-6 是 invalid_argument/context/device 三类共用；算子未实现与配置不受支持分别是 -9/-12。相机链的 `mrflownet-v2` 模型是单节点 `tunneled_ane_op`，CPU launch 直接拒绝——相机链不能用 CPU 回退，VM spoof 对相机永远是死路。mediaanalysisd 的人脸/场景/质量模型全是常规卷积算子，CPU 路径适配。

## 2. 内核 scoped spoof 与三轮真机

内核 `dd5ca201`：`sysctl_vmm_present` 按进程应答，默认名单 cameracaptured,mediaanalysisd，boot-arg `ane_vmm_procs` 可覆盖。

| 轮 | 变量 | 结果 |
|---|---|---|
| b5r1 | 基线（编码打点 userland `950e7eb`） | 相机正常出片，ANE load failure 签名存在 |
| b5r2 | spoof 双进程 | ANE 加载失败签名归零，但 cameracaptured 内 Espresso CPU 执行 `handle_ex_plan status=-2/-6`，取景器黑、零成片 |
| b5r3 | boot-arg 缩到只剩 mediaanalysisd | 相机恢复（因果链闭合）；mediaanalysisd 加载层打通、CPU 改写行为证据确凿（CNN GPU 管线归零），但执行期 `status=-2` io_error 依旧，err 105 持续 |

三轮证据在 `docs/progress/evidence/k90auto/kernel-12377-flipwd4-b5r{1,2,3}/`。

## 3. U8 当前阻塞与成功口径

`io_error` 跨进程复现（b5r2 cameracaptured、b5r3 mediaanalysisd 同签名），是平台级 Espresso CPU 执行问题。头号嫌疑：MiniIOSurface 软件模拟的 CPU 访问语义与真机差异（对齐/压缩/映射）。抛出点枚举反编译进行中，产出 `out/goal-1124/batch5/espresso-ioerror.md`。

成功口径已闭合（`out/goal-1124/batch5/zresult-semantics.md`）：err 105 = Scene_Embedding 阶段（VCP backbone 推理链失败统一出口）；成功判据 = `MediaAnalysis.sqlite` 的 ZASSET/ZRESULT 转非零、payload blob 非空、`ZIMAGEEMBEDDINGVERSION=77`、ZPROCESSINGSTATUS 到 32767(Done)。验收 SQL 在 `out/goal-1124/batch5/zresult-validation.sql` 与 `photos-analysis-validation.sql`。

## 4. 支线状态

- **对焦框 ❌**：userland `f3a3d4e`（AFStatus 取值修正、FocusNowCommandID 哨兵、AFStable）真机验证未生效——点按后无任何新 FocusNow 命令到达插件，初始命令的完成确认因 `FocusPeakSumArray` 键缺失而不发生，后续命令被状态机拒收。消费路径反编译进行中。
- **前摄 -16808**：`out/goal-1124/batch5/front-xf20-contract.md`——几何触发论被时序证据否定（错误链在首张交付前出现；2496x2496 无 padding 零扩展恰是契约正确形态）。xf20 实验 diff 已按分析结论弃置还原。可疑方向重排：ANE 缺失（前摄专用模型）、capture 建立期、Metal 着色器、GDC 契约。
- **GPU 配速 ✅ 初步**：内核仓库 `a07712d8`（纯 compute 大 commit 分片+深度 1 节流）在 b5r3 生效，51 条 yield 行；桌面翻页补测 109.7fps/92ms+ 为零，与 b5r1 基线持平无回归。出片后缺口对照待专门测量。
- **fence 打点就绪**：内核 `340bee5c`（tl:F 入口行、tl:X 失败行带 retired/last）编译通过未上机，下轮内核候选，判别 respawn 机制用。
- **观测手段教训**：`VM detected` 两行是 INFO 级，oslogwatch 看不到属预期；桌面翻页脚本两轮在 Photos 内无效执行（截图签名相同发现），驱动脚本需确定性回桌面手段。

## 5. 提交清单

内核：`dd5ca201`（vmm 按进程应答）、`a07712d8`（compute 分片配速）、`340bee5c`（fence 打点）。userland：`f3a3d4e`（对焦元数据取值）、`950e7eb`（编码链打点）、`7a84913`（tl:t 修复）。分析文档：`out/goal-1124/batch5/` 下 ane-close/espresso-status/zresult-semantics/front-xf20-contract/fence-wait-probe/fence-respawn/photonic-gpu-plan/text-layout-cost/afstatus-semantics/af-metadata-fix。
