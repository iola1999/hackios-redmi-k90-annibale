# 批 9 收官与批 10 开局：需求侧治理、锁外释放与 ADSP 传感器发现

批 8 收官见[批 8 文档](2026-11-27-batch8-opening.md) §9。批 9（`b5r27`～`b5r29`）完成需求侧根因定位、Mesa `0030` 验证、`AnnibaleGPU` `reap` 锁外释放、`MiniFramebuffer` 静止主屏优化、Reminders 黑闪与 `G18` 审计及 Sensors 离线设备树普查；批 10（`b5r30` 起）接续推进 Mesa `0031` 与 ADSP `IPCRTR` 原生传感器链路。

## 1. b5r27 判决（11-27 下午，批 9 第 1/3 轮）

详细读数见 `docs/progress/evidence/k90auto/kernel-12377-flipwd16-b5r27/RESULTS.md`。本轮为 `flipwd16`（keep 池 512 项与尺寸软配额）加 `input26` 空闲定时器修复（用户态 `1338ea2`）组合轮。

- **池扩容部分命中**：复用率由 `22.0%` 升至 `45.4%`，`entry-cap` 驱逐降 `88.5%`，同手势段 `tl:L` 降 `27%`（`88` 至 `64` 次），`commit` 慢帧降 `58%`（`12` 至 `5`）。`byte-cap`（`10,370` vs `entry-cap` `5,098`）接替成为约束，`kept_mb_max` 顶到 `160 MiB`。
- **submit 分段新读数**：`room`（管线深度等待）占 `557/640` 事件，`reap` 在锁内偶发极大值（`max 58.7 ms`，`24` 次主导，`s142.log` 累计 `438,039 us`），`backend submit` 最大 `22.6 ms`。
- **空闲定时器修复验证通过**：三分钟稀疏注入无自动锁屏，测量轮不再需要微拖动维持唤醒，交叉印证 `b5r25` 持续黑扫描源自自动锁屏与误触污染。
- **黑窗清洁复测**：持续黑扫描未复现，仅余 Reminders 首冷开 3 帧黑闪（`analysis/rec-reminders-cold-1/`）。
- **回归全过**：翻页 `20/20`、Safari `8/8`、`0029` 十项风暴标记全零。

## 2. 需求侧根因定位与 0030 实施（11-27 下午）

离线分析（`out/goal-1124/batch9/mesa-bo-cache-investigation.md`）查明内核 `gemNew` 实测 `42/s`（峰值数百）来自三层叠加：

1. **第 1 层**：AIR 对大于等于 `4096 B` 的 `MTLBuffer` 一律标 `PIPE_BIND_SHARED`（`air_metal.c:976`），freedreno 把可共享视作已共享，导致该类 BO 被 `heap`/`cache`/`idle` 全部排除。
2. **第 2 层**：带 `ring->flags`（`0x402`/`0x2`/`0x3`）的小 BO 与 `FD_BO_NOMAP`（`0x4`）绕过 `ring_heap` / `default_heap`，五个进程全轮次直达内核。
3. **第 3 层**：`find_in_bucket()` 与 `heap_clean()` 遇忙条目即停（`break`），且缓存 `1–2 s` 过期叠加深队列延迟导致复用命中率低。

用户态 `a308ac4`（`0030-fd-shared-potential-cacheable.patch`）新增 `_FD_BO_EXPORTED`，仅在 `import`/`export` 置位并按实际导出位判定缓存资格，产出 `libannibaleair-0030.dylib`（SHA-256 `008b7e65...`），主机补丁与七项静态契约检查通过。

## 3. b5r28 判决（11-27 下午，批 9 第 2/3 轮，0030 验证）

`b5r28` 沿用 `flipwd16`（内核 `24b12101...`）并替换 `0030` AIR 库，与 `b5r27` 保持单变量对照（`docs/progress/evidence/k90auto/kernel-12377-flipwd16-b5r28/`，`87` 份日志、`264,915` 条去重行）：

- **稳定性与回归全过**：`0` GPU 停转、`0` SMMU 故障、`0` `mfb: zero-swap`、`0` `0029` 风暴标记、`0` SpringBoard 重启环、`0` panic；Stage 2 翻页 `20/20`、Safari `8/8`、桌面 19 图标与 Safari 10 标签缩略图全部正常。
- **0x110 慢分配消除**：全轮去重 `242` 次 `fd bo new slow` 中仅 `2` 次带 `0x110`；全轮 `0x42` `gemNew` `33,199` 次（`85.10/s`，1 s 峰值 `1,261/s`），Keep 池 `54` 窗 `reuse=0.4179`。
- **同手势对照（`b5r28` vs `b5r27`，20/20 横滑）**：`Q_n` 同为 `4,558`；`tl:L` 总数 `61` vs `64`，总和 `194,413 us` vs `230,089 us`（`-15.5%`），最大单次 `7,114 us` vs `14,784 us`（`-51.9%`）；`0x46` submit 尾部总和 `62,902 us` vs `92,264 us`（`-31.8%`）；`0x42` `gemNew` 次数 `8,182` vs `8,944`（`-8.5%`）。
- **残留毛刺归因**：`b5r28` 全轮 `reap` 仍有 `3` 次主导尖峰（`s021.log:13114` 单次 `158,708 us`），源于 `submit()`/`gemClose()` 在 `gGPULock` 内无上限遍历 `fLeft` 并同步执行 `IOMemoryDescriptor::release()` 与 `MiniIOSurfaceDrop()`；剩余 `gemNew` 仍由第 2/3 层造成。

## 4. b5r29 判决与批 9 离线定案（11-27 下午，批 9 第 3/3 轮）

`flipwd17`（内核 SHA-256 `3c0419d1...`）合入两项相互独立的内核修复并搭配 `0030` AIR 上机（`docs/progress/evidence/k90auto/kernel-12377-flipwd17-b5r29/`，`89` 份日志、`259,763` 条去重行）：

- **`AnnibaleGPU` 锁外 `reap` 与有界预算（通过）**：`AnnibaleGPU.cpp`（`1194` 行）、`AnnibaleGPUMemory.inc`（`832` 行）与 `AnnibaleGPUSubmit.inc`（`366` 行）新增 `gpu_garbage` 延迟释放队列（容量 `32`），将 `reap`/`keep`/`gemNew` 扫描限定为 `16` 项，在释放 `gGPULock` 后调用 `gpuGarbageFlush()`；同步落实 `keep` 池 `§8.1`/`§8.3`。`b5r29` 全轮 `328` 条去重 `tl: is` 中 `reap` 耗时降至 `p50=0 / p90=0 / p99=2,086 us / max=3,402 us`（降幅 **`94.2%..97.9%`**），累计 `18.15 ms`。
- **19 段受控横滑三轮对齐（`b5r27` -> `b5r28` -> `b5r29`）**：`tl:L` 最大单次锁等待由 `14,784 us` 降至 `7,114 us` 再降至 **`5,399 us`**（总降幅 **`-63.5%`**）；`0x46` 锁内最大持锁由 `14,845 us` 降至 `12,030 us` 再降至 **`5,350 us`**（总降幅 **`-64.0%`**）。
- **`MiniFramebuffer` 静止主屏优化（通过）**：`MiniFramebufferRows.inc`（`388` 行）与 `MiniIOMobileFramebuffer.cpp`（`1248` 行，净增 `0`）在帧间隔大于等于 `25 ms`（覆盖 10 Hz 时钟秒针）时改为单核内联 `hashRows`，新增 `shouldParallelDraw()` 对小于 `128` 行的脏带内联 `drawRows`，并将 `ROWS_UNHASHED` 从 `16` 收紧至 `4`。`b5r29` 15 秒静止主屏窗口（`n=450` vs `b5r27 n=240`）显示 `tl: v` `p90` 由 `3,388 us` 降至 **`2,068 us`（`-39.0%`）**，`p50=1,936 us`，零辅助核心唤醒（每秒省去 `40` 次跨核唤醒）；5 秒窗 `drawn whole unhashed` 最大 `20` 次（`b5r27` 常为 `60–91` 次）；翻页 `20/20`、Safari `8/8` 与截图全部无回归。
- **Reminders 3 帧黑闪与 `G18` 审计结案**：逐帧比对 `b5r27` `rec-reminders-cold-1`（f35–f37 持续 `28 ms`）及 `b5r28` `rec-settings-cold-1`（f23 持续 `10 ms`）、`rec-reminders-cold-1`（f23–f27 持续 `38 ms`），确认状态栏电量与底部指示条均以 `255` 亮度正常合成，`backboardd` 提交每帧 `0.8 ms` 退休，`mfb: zero-swap` 与 `cleared_black` 均为 `0`，有快照的 `cold-2` 黑帧全部归零。该现象属于首冷开缺少 SplashBoard 启动快照时桌面先撤出、应用首帧晚到的转场空窗；原 `G18` 持续黑窗与设置黑带在当前基线未复现。
- **Sensors 离线设备树普查定案**：检查 `sm8750-xiaomi-annibale.dtb:9758` 确认 `qcom,gpios-reserved` 包含十进制 `gpio36..39`（`qupv3_1` SE1）、`gpio48..51`（`qupv3_1` SE4）与 `gpio74`（`hub_i2c5`），属 TZ/HYP XPU 保留引脚，解释了 `b5r25`/`b5r26` 在数秒内复位的直接原因；同时发现 `qupv3_0_i2c_hub` 6 条空闲 SE（`hub_i2c3/4/6/7/8/9`）此前因 `active-mask` 复用被跳过。据此确立路线 A：通过已就绪的 `adsp_pas` SMEM GLINK `IPCRTR` 接入 `QMI SNS_CLIENT`（`0x190`）。

## 5. 批 10 开局：b5r30 与 b5r31 进展（11-27 傍晚）

批 10 首轮 `b5r30`（`flipwd18` SHA-256 `6dc425ae...` + Mesa `0031` SHA-256 `1ce0b092...`，`docs/progress/evidence/k90auto/kernel-12377-flipwd18-b5r30/`）：

- **ADSP `IPCRTR` 实测打通 `QMI SNS_CLIENT 0x190`**：`annibale_adsp_ipcrtr.inc`（`187` 行）与 `annibale_adsp.c`（`1191` 行）接入 SMEM GLINK `IPCRTR`，`annibale_sensors_scan.inc`（`382` 行）加入 `qcom,gpios-reserved` 9 脚硬禁访保护。`s001.log` 在 ADSP 启动后 `200 ms` 内实测建链并收到 `HELLO FROM NODE 5` 及 **`qrtr: a service: 400 (0x190), version 1, instance 0, at node 5 port 18`**（无需 `pd_mapper`），同时确认 ADSP 实际 QRTR 节点号为 `5`（非设备树链路号 `2`）。
- **Mesa `0031` 吞吐收益（`b5r30`）**：`0031-fd-heap-and-cache-reuse.patch` 将 `0x402`/`0x2`/`0x3` 纳入 `ring_heap`、非 image `0x4` 纳入 `default_heap` 并调整缓存命中与字节上限。实测 `ring_heap=865,928`、`def_heap=14,036`（`0x402=0`、`0x4=3`），Keep 池复用率从 `0.4388` 升至 **`0.8034`**，tour `tl: is > 2 ms` 从 `112` 条降至 **`6` 条（`-94.6%`）**，`room` 累计等待从 `275,676 us` 降至 **`300 us`**。
- **Mesa `0031` 两条阻塞缺陷（`b5r30`）**：`saf-first-a-overview.png` 白色背景与网页标题出现黑色水平短条与斑点伪影（`saf-repeat-a-overview.png` 与 `s4-home-final.png` 正常）；`evict=33,959`、`0x204 made=40,298`，整轮 `gemNew` 仍达 `119.61/s`。
- **`b5r31`（批 10 第 2/3 轮，`flipwd19` `a6a3cf1d...`）**：`QRTR_NODE_ADSP=5u` 与 `annibale_sensors_ssc.inc`（`685` 行，经 `sensors_ssc_tick` 规避 `qrtr_calling` 锁重入）验证 `SNS_CLIENT online at node 5 port 18`，`"ambient_light"` 与 `"proximity"` 的 `SUID lookup` 均返回 `QMI resp txn=1/2 res=0 err=0 sns_err=0`；`15 s` 桌面静置 `tl: v` 为 `p50=1,795 us / p90=2,201 us`（`0` GPU 停转、`0` SpringBoard 重启环）。
- **Sensors `0x0021` `REPORT_IND` 全链打通（`b5r32`，`flipwd20` `34f7d062...`）**：修正 `QMI_SNS_CLIENT_REPORT_IND=0x0021u` 与 `SNS_STD_CLIENT_PROCESSOR_APSS=1u` 后，`s002.log` 收到 `QMI ind #1 msg=0x0021 len=69`（`SUID event "ambient_light" count=0`）与 `QMI ind #2 msg=0x0021 len=65`（`SUID event "proximity" count=0`）。已在 `annibale_qrtr.c`（`719` 行）放开 `node 5` `QRTR_NEW_LOOKUP` 零终止应答与控制日志，并在 `annibale_sensors_ssc.inc`（`700` 行）追加 `\"registry\"`／`\"accel\"` 查询（已过审待批 11 首轮实测）。
- **Mesa `0031 v2` 实测与阻断（`b5r32`，`0bd5766f...`）**：`fd bo stats`（141 窗）命中率升至 **`69.0%`**（`bo_hit=58,891`、`bo_miss=26,453`、`evict=20,508` 集中于 `backboardd`），`0x42` 均值降至 **`76.71/s`（`-35.9%`）**；20 门禁严格对照 `b5r29`：`0x42` `tl:L` 降至 `3` 次/`8.2 ms`（**`-91.2%`**），`room` 降至 `24,093 us`（**`-90.7%`**），`backboardd` `>90` BO 提交降至 `140` 笔（**`-91.0%`**）。`saf-first-{a,b}-overview.png` 仍复现 `96×96` 设备像素网格周期性黑条伪影（已排除未清零假设），阻断合入。
- **`M15` 与批 10 收官复盘**：`M15`（`format 5`）修复（`2632484` `IntermediateTap`）与 `test-camera-device-ios26.py`（`1198` 行）回归通过；`G30` 查明 5 处复位锁死卡点，批 11 首轮先以纯用户态 `0031` 切片 A 二分定位 Safari 伪影，同步推进 `P13` 多槽 `QMI_UIM`（已过审）与 `P21`/`P23`/`S11`。

## 6. 批 11 二分定案与 0031 切片 B（b5r33、b5r34）

- **`b5r33`（批 11 第 1 轮，`flipwd20` + `0031` 切片 A 纯 `bo_cache`，`docs/progress/evidence/k90auto/kernel-12377-flipwd20-b5r33/`）**：回退 `default_heap`、`ring_heap` 与 `heap_clean` 至 `0030` 基线，仅保留 `bo_cache`（`8780dff2...`）。实测 `saf-first-{a,b}-overview.png` 仍复现 `96×96` Alpha 周期伪影（`y=1000..1300` `alpha > 100` 达 `883`/`1,537`），`0x42` 回升至 `195.09/s`（`70,905/363.4 s`）、`verdict12` `tl: is >2ms = 119`（`room=298,903 us`）、`fd bo stats` `evict=57,726`（`bo_hit=79.2%`），翻页 `20/20`、Safari `8/8`、全部健康项为 `0`。
- **`b5r34`（批 11 第 2 轮，`flipwd20` + `0031` 切片 B 纯 heap，`docs/progress/evidence/k90auto/kernel-12377-flipwd20-b5r34/`）**：保留 `ring_heap`（`0x402`/`0x2`/`0x3`）、`default_heap`（`0x4`）、`heap_clean` `continue` 与 `fd bo stats`（`256` 行补丁，`4cac7c2f...`），将 `freedreno_bo_cache.c` 与 `tools/mesa/air/` 恢复 `0030` 基线。
- **`b5r34` 实测吞吐与稳定性**：全轮 `0x42` 降至 **`31.70/s`**（`14,482/456.8 s`）、`made=13,930`、`evict=0`、`verdict12` `tl: is >2ms = 6`、`room sum = 84,202 us`（较 `b5r33` 降 `71.8%`），Keep 池 `made=6,784`/`kept_again=7,698`/`max_kept_mb=160`；翻页 `20/20`、Safari `8/8`、全部停转与故障标记为 `0`。
- **同口径 20 门禁严格对照（`b5r29` `0030` -> `b5r34` `0031` 切片 B）**：`gate20_merged` 中 `tl:L` `64 -> 50`（`-21.9%`，`0x42` 段 `33 -> 11` `-66.7%`）、`0x42` `10,607 -> 4,539`（`-57.2%`）、`tl:is` `103 -> 16`（`-84.5%`，`room` `259,689 -> 41,360 us` `-84.1%`）、`tl:Q` buffers `605,916 -> 196,694`（`-67.5%`）、`>90 BO` `24.33% -> 4.34%`（`-87.0%`，`SpringBoard`/`WidgetRenderer` 均归零）；`matched_19` 同轨手势 `slow commits` `10 -> 5`（`backboardd` `6 -> 0`）、`tl:is` `75 -> 16`（`-78.7%`）。
- **Safari `96×96` 伪影跨轮定案（解除 `0031` 阻断，立项 `G31`）**：`b5r34` 仍见 `saf-{first-a,repeat-a,repeat-b}-overview.png` 黑斑；跨轮核查 `b5r24..b5r34` 全部 44 张概览截图实证自 `b5r24`（`flipwd13`）起该 `92` 像素（约 `96` 设备像素，`RGB=(0,0,0)`、纯 Alpha 通道、`period=92 frac<=2 = 0.832..0.973`）网格伪影即已间歇复现（`b5r24` `fa:1484/fb:0/ra:923/rb:1331`，`b5r27` `480/358/202/1051`，`b5r28`/`b5r29` 偶发全零曾造成误判）。该伪影与 `0030`/`0031` 无关，已独立立项为 [图形待办 `G31`](../backlog/graphics.md#1-渲染与资源契约)，并锁定 `0031` 切片 B（`4cac7c2f...`）为最终合入版。

## 7. 批 11 最终轮（b5r35 / flipwd21）收官与后续事项

- **`b5r35` 实测基线与稳定性（`12377-flipwd21` `d9b52ee0...` + `0031` 切片 B `4cac7c2f...` + `adreno8_ifpc=1`，`docs/progress/evidence/k90auto/kernel-12377-flipwd21-b5r35/`）**：翻页 `20/20`、Safari `8/8`、`s4-home-final.png` 主屏 19 图标与组件完整，全轮 `0` GPU 停转、`0` SMMU 故障、`0` `mfb: zero-swap`、`0` `0029` 风暴、`0` SpringBoard 重启环。
- **`b5r35` 吞吐与 `ifpc=1` 功耗门控对照**：全轮 `0x42` `21.75/s`（`14,398/661.8 s`）、`made=13,682`、`evict=0`；高频连续翻页 `gate20_merged`（`165.669 s`）`tl:is=17`（`sub_max=45 us`）、`>90 BO` 降至 `173/5,104`（`3.39%`，全在 `backboardd`）；稀疏窗 `verdict12` `tl:is >=2ms = 6` 中 `sub` 占 `60,204 us`，对应 `IFPC=81` 功率门控冷唤醒。
- **`b5r35` 四项新内核观测结果**：① `adreno8: HWSCHED START acknowledged (ifpc=1)`（`IFPC=81 preemption=26 dynamic=60`，全轮与 15 s 静置零停转）；② `psci: method=smc version=1.1 cpu_suspend=0x3 (osi=1 ext_stateid=1)`（确认支持 OSI 与 Extended StateID）；③ `sensors-ssc` 四项 `SUID lookup`（`ambient_light`、`proximity`、`registry`、`accel`）均收到 `QMI resp res=0 err=0 sns_err=0` 与 `QMI ind #1..#4 msg=0x0021`（`count=0`，`node 5` 未发 `QRTR_NEW_LOOKUP`）；④ `modem` 本轮未传 `modem=1`（`annibale-modem: modem=0`），留待专用轮。
- **下一阶段待验证与后续项**：`P13` 多槽 `QMI_UIM`（带 `modem=1` 上机）、`M1` Iris 中途排空切片 1 真机复核、`S7` `ANNIBALE_DAMAGE_PROBE=1`（`arm64e` 编译通过）、`P23` `lc_watch_round` `EVNTEN+WFE` 临时 loader 实测与 `psci_idle=1`（`0x04`）、`G29` `rwa_lock` 收窄到 `texture_start_zeroed()` 内、`S11` `locationd` `writeData:` 崩溃、`G30` 5 卡点复位与抢占、`G31` Safari `96×96` Alpha 伪影独立排查。
