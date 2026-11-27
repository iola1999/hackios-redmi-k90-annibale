# 批 8 开局：0029 修复验证、背光去重、运动真值、传感器引脚扫描（2026-11-27）

批 7 收官判决见 `2026-11-27-batch7-user-visible.md` §1-17。批 8 首轮 b5r24 组合四组判决上机，本文档记录物料与 work order，结果落地后接续。

## 1. 物料

| 项 | 值 |
|---|---|
| 内核 | `hackios-xnu-kernel/out/xnu12377-flipwd13.bin` sha256 `8b26469fdf4f95f65f2770a76ff450c80835683c279a1e9d4eea4619d93a8c61`，commit `2120c6c1` 干净 |
| 内核内容 | bl_dedup svc 去重（`d3e9b7c8`）、bt H4 startup 重组（`15bc378b`）、sensors_scan 扫描（`2120c6c1`） |
| rootfs | bbmetal-device/root.apfs，含 xfm 探针（userland `ec4e1dc`）、默认 air 库 pre-0024 基线 `ec215364` |
| 轮换库 | `libannibaleair-0029.dylib` sha256 `24477c65347c30e993c033fb601c265506942ae0e9128dc636dd0e49e695d298`（userland `b04b65f`） |

顶层 `8db0550` 子模块指针入库；cycle.py FIXED_ARGS 已移除 sensors_hw_i2c（`8cd1c64`，止血——该参数与 Wi-Fi 同组必 panic 或杀 USB）。

## 2. b5r24 work order 摘要

boot-args：FIXED_ARGS + `gpu_tl=1 dl_log=1 bl_trace=1 xfm_log=1 sensors_scan=1` + tdump 武装。四组判决：

1. 0029 真机验证——判读标准 `out/goal-1124/batch7/0029-implementation.md` §6：健康 hist `create1 subref2 subdel1 emitdel0`，三类违规探针零命中；风暴复现则取证回退 pre-0024 继续其余测量
2. bl_dedup——`backlight-svc-dedup-implementation.md` §4：dup/def 行出现、dwr 极少、方向反转与 millinits 流自身一致、开机早期兜底不黑屏；加做滑块拖动取证
3. xfm 运动真值——`transform-hook-implementation.md`：确认 installed 行，翻页 settle 段 transform 序列覆盖
4. sensors 扫描——`sensors-scan-implementation.md`：P1 三组引脚 0x31/0x47/0x2c ACK 判读，0x47+0x2c 同答为 stk6a2x 总线强签名

Safari 多标签用已校准命令 `drag 0.565 0.932 0.565 0.30 216 200 1`，首次+重复各两轮。

## 3. 并行离线线

- `3739400f` 活跃 settle 卡顿 rwa 阻塞分析（SpringBoard 主 RunLoop 458ms 长轮、commit 418 耗时 112ms、rwa_texture_create mutex——真实用户可见卡顿的核心现场）

## 4. 磁盘与 housekeeping

磁盘 109Gi 可用（evidence 16G+out 45G+kernel/out 21G），暂不紧迫；删除或压缩前需向用户确认范围。批 7 文档已全量入库；out/goal-1124 分析文档为 gitignore 本地产物。

## 5. b5r24 判决（11-27 凌晨，flipwd13 组合轮）

四组判决全部落定，全文 `docs/progress/evidence/k90auto/kernel-12377-flipwd13-b5r24/RESULTS.md`：

1. **0029 修复验证通过**：24 分钟全轮（启动+20 翻页+3 滑块+Safari 两轮）双重普查——analysis 快照正则加 run/s*.log 按行哈希去重 519552 条唯一行全量——`fd ring double destroy`/`in suballoc slot`/`sink install`/`duplicate take`/hist/`submissions closed`/userabort 全零。对照 0028 在 b5r23 boot 阶段即风暴，**0029 可接替基线地位**。双重释放风暴链（自 0024 合并以来卡死全部图形修复上岗）终结。
2. **bl_dedup 达标**：mfb 第二写来源零漏网（blk 1843/wr 0）；svc 分工 wr 1838/dup 1564/def 565/defdrop 542/dwr 仅 23。稳态面板 DBV 反转 9 次 vs bn 请求流 8 次——抖动消除达标；dcs check 读回 8/8 全部 same（b5r23 证据缺口补齐）。开机亮度抖动修复链闭合：仲裁（b7fa3fa3）+svc 去重（d3e9b7c8）双双验证。
3. **xfm 探针工作正常**：installed 行命中，全轮 26 批跨 780s、最大 n=87、dropped=0，覆盖翻页/控制中心/Safari 三类手势。运动真值数据首次到手，离线分析进行中。
4. **sensors 扫描否定性结果**：P1 三组引脚（gpio20/21、12/13、8/9）× 3 轮 × 3 地址共 27 次探测全部 NACK，pin mux 干净恢复、Wi-Fi 零干扰。三条总线排除。下一步：P2/P3 八对候选（36/37、48/49、hub 70/71、72/73、76/77、82/83、206/207、80/81）经 boot-arg 自定义组零编译成本搭车下轮；若仍全 NACK 则转向供电轨投票（sensor_vddio+sensor_vdd_4 双轨）与 SSC 占用分支。

收尾：设备退回 loader idle 三项校验通过；pre-0024 已恢复默认库；电池 96%/32°C。噪声：batteryintellige userabort 4 次未影响测量。

## 6. 批 8 后续方向

- 性能线：xfm 运动真值分析定三类空洞占比；ioctl 放大器内核修复实施中（`0d0f0391`，小 bo 入池+读型免大锁+per-ioctl 打点）；修复方向排序与依据 `out/goal-1124/batch7/active-gap-rwa-analysis.md` §5，kevent 段定性 `out/goal-1124/batch8/kevent-segment-verdict.md`（收益并入方向 1/2）
- sensors 线：P2/P3 扫描搭车+b 供电轨分支预案
- 图形线：0029 验证通过解除上岗封锁，下一轮起 0029 系库可作为默认载荷——air 崩溃族修复（0024 系列）终于能真机发挥效益；提醒事项黑窗、设置黑带等 backlog 图形项恢复排期评估

## 7. ioctl 放大器修复入库与 b5r25 放行（11-27 凌晨）

内核 `c9ff36a1`（合并提交，原逐修复提交已并入）：小 bo 入池（256KB 以下 2 幂分桶、GPU_KEPT 48→128）、gemInfo 免大锁（release 发布内存引用+acquire 读）、全部 ioctl 预检无锁化（两次锁往返降为一次）、`gpu_io_log=1` 新增 per-ioctl queue/held/total 打点。实施与安全论证 `out/goal-1124/batch8/ioctl-amplification-fix.md`。flipwd14 注册 sha256 `be4ca6d371c529be56d0f40bf3e8f8fd2e766ee2050d0b1799f3b273d784fb91`。

运动真值人工抽查先行定性（穷尽量化进行中）：**动画位置在 25-34ms 掉拍期间持续推进**（g46/g49 直接证据）——real-stutter 坐实在生产/呈现路径；H3 暂停零样本；H2 静止段须剔除但属干净无运动形态。修复优先级判断不变：SpringBoard/RenderBox/Metal/rwa 生产路径。kevent 段闭合到调用级：RenderBox+0x236ac 是 dispatch_sync_f 族调用（工作函数 0x196a58df0→0x196a58e20 大渲染工作项），等待对象为本进程渲染线程在制品，收益并入方向 1/2（`out/goal-1124/batch8/kevent-segment-verdict.md`）。

b5r25 已放行（agent f818b879）：flipwd14+0029+`gpu_io_log=1 xfm_log=1`+sensors P2/P3 扩展扫描（36/37、48/49、hub 70/71、72/73、76/77、82/83、206/207、80/81）+图形回归搭车（提醒事项黑窗、设置黑带）。批 8 已用两轮，剩一轮预算。

## 8. b5r25 判决（11-27 上午）

详细判读 `docs/progress/evidence/k90auto/kernel-12377-flipwd14-b5r25/RESULTS.md`。四组判决：

- **ioctl 放大器修复机制性强命中**：gemInfo 23637 次调用 queue/held 全零退出锁竞争；keep 池复用率 24.3% vs 4.9%；bo 分配量降 70%（23864 vs 79026）；gemNew 快速路径 p50 9µs。tl:L 尾部未干净下降，剩余瓶颈在 gemNew 未命中与 submit 路径。
- **xfm 弱命中**：全口径多节拍间隔 271→191（-30%），活跃 settle 掉拍 68→61/22 手势，全部仍是动画推进的 real-stutter。
- **sensors 扩展扫描证伪空闲池假设**：gpio36/37 或 48/49 的 bitbang 是启动致死动作（1~2 秒内内核死亡 USB 断联）；hub SE3/5/7 引擎被 SSC 活跃占用；默认三对扫描机制完好。内核需逐引脚打点定位致死相位后才能继续。
- **图形回归负判决**：Preferences/Reminders 前台全幅扫描输出纯黑（含状态栏，mean/std 0.0），回桌面恢复；Safari 正常。fb 内存本身全零，指向合成/扫描输出级问题。flipwd14 相对 flipwd13 唯一内核增量是 ioctl/keep 池改动，小 bo 复用正确性是首要嫌疑。逐帧证据因 trollstorehelper 误报 open 失败缺失（tooling bug 待修）。

## 9. b5r26 判决与批 8 收官（11-27 中午）

详细判读 `docs/progress/evidence/k90auto/kernel-12377-flipwd15-b5r26/RESULTS.md`。批 8 三轮预算（b5r24/25/26）用完，批次收官。

### 9.1 四组判决

- **keep 池缺口成因直读**：miss 96.2% 为尺寸类无条目（flags 仅 3.8%）；驱逐 86.8% 因 128 条目上限（字节上限仅 2/159 窗口顶满）；in_pool p99=128 顶满。行动项明确：GPU_KEPT 扩容或尺寸配额分桶。
- **submit 尾部分段**：锁内 87% 是 room 深度等待（GPU 管线背压），flush 近零符合 gpu_coherent 预期；最坏 backboardd room 29.8ms。结论改写性能线：瓶颈在 GPU 管线吞吐与深度，锁竞争治理已近收益尽头。
- **黑窗未复现**：保持唤醒后提醒事项/设置冷开完整渲染，zero-swap 全轮零命中。b5r25 的持续黑扫描与 pocketTouches 误锁链一致——测量污染嫌疑大于渲染缺陷。残留冷开转场单帧黑闪。G18 族定性需按此复核。
- **回归通过**：0029 十项风暴标记全零、Safari 多标签渲染完整。

### 9.2 sensors bisect 终结扫描线

gpio36/37 与 48/49 各自独立致死；hub 六对被 SSC 引擎门控构造性不可探测（SE3/5/7 恒活跃被跳过）。bitbang 扫描路线终结。sensors 线下一步只剩两条：设备树/persist 离线普查找正确引脚，或改用 SE 引擎原生路径而非 bitbang。pocketTouches 误触发与 sensors 线耦合，ALS/prox 定位价值上升。

### 9.3 测量学教训（沉淀为规则）

注入触摸不重置空闲定时器，设备 1-2 分钟自动回锁污染测量——b5r25 黑窗判决即受此影响。链式+微拖动范式已沉淀在轮次脚本。内核侧需确认 anntouch 是否喂 BMUserActivity。

### 9.4 批 9 候选输入

1. GPU_KEPT 扩容+尺寸配额分桶（判决 1 直接行动项，离线实施）
2. GPU 管线背压深挖：backboardd 单笔提交 90 buffers 的构成与管线深度瓶颈（生产静默同根因族）
3. anntouch 空闲定时器修复（测量基础设施）
4. 静止重绘 dirty 设计（功耗线，仍欠）
