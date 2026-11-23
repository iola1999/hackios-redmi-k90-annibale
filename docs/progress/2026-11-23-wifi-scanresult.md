# 2026-11-23 A7 Wi-Fi 扫描结果链：按读者游标 + TIMESTAMP 已修，`{()}` 仍在

A7（控制中心关开 Wi-Fi 后状态栏图标灰）排查记录。证据目录：`docs/progress/evidence/k90auto/kernel-12377-scants-ts1/`。

## 1. 本轮变量与改动

- 内核 `xnu12377-scants`（`annibale_apple80211.c` 两处改动）：
  - `gets 11`（SCAN_RESULT）游标改为按读者保存：以 `req_data` 指针为键的 16 槽表替代全局 `result_next`，扫描开始/结束时清表。
  - `give_network` 在应答缓冲 ≥ 0x8E0（2272 字节）时写 iOS 26 扩展字段 `+0x8D0`：`TIMESTAMP = mach_absolute_time 的纳秒数 - age_ms*1e6`（听到时刻）。时钟域依据：IO80211 `sub_25D4897F4` 中 `TIMESTAMP = base_ns + age_seconds*1e9`，基准值为 u64 纳秒。
- 载荷 `handoff-12377-scants-ts1.bin`，启动参数与 sr1/wifidiag1 相同（`wifi_quiet=0 wifi_rejoin=1`、GPU_SPEED=14、4 核）。

## 2. 实测读数（ts1 轮，197.9 s 处帧冻结回收）

- 内核定向扫描（98 信道，按名字找 standing 网络）听到目标网络：ch44 -22 dBm ×65、ch40 -76 dBm ×2；3 信道被动扫描听到 15 个 AP。
- `gets 11`：15 次 answered + 1 次 error 5（EIO），随后 `gets 115` REFUSED 一次。即一个 drain 上下文完整读走 15 条结果，按读者游标生效（sr1 轮为 6 上下文 × 16）。
- `WiFiSettlementObserver _handleScanResults` 仍全部 `results='{(\n)}'`：TIMESTAMP 填充后解析层仍产出空集。TIMESTAMP=0 排除为病根。
- `gets 115`：CopyValue 分派中与 103（CURRENT_NETWORK）同属原始数据拷贝组（LABEL_28），2152 字节缓冲，周期性出现且与扫描完成无强关联——不是取结果的接口。
- 本轮内核 join 只进行到「定向扫描听到目标网络」，随后轮次在 197.9 s 帧冻结，未出现 `station_join` 的接入点选择行、AUTHENTICATION/ASSOCIATION，关联未完成；`gets 103` 全程 error 6。join 完成性本轮未验证，与本次改动无关（同样的帧冻结在 sr1/wifidiag1 也发生过）。

## 3. 当前结论与下一步

- 扫描结果在 ABI 层完整可读（每读者独立游标），TIMESTAMP 也按原生 ns 语义填充。`{()}` 依旧。真机日志无 `Failed to add scan result to list`。
- ts1 轮决定性对照：`scanType=2 client='locationd'` 的 `WiFiSettlementObserver` 拿到**完整 15 个网络**的真实对象（`WiFiScanObserverNetwork` 含 SSID/BSSID/RSSI）——结果→字典→网络对象→observer 的整条管道对被动扫描完全工作。全部 46 条 `scanType=1 client='wifid'` 仍 `{()}`。差别收敛到 type-1（主动）观测上下文本身。
- 事件分发器已拆：`[buf+0x14]` 为事件码，默认路径把 (code,payload) 直接转发客户端回调；code 2（SSID_CHANGED，载荷 8B={status,reason}）、code 4（LINK_CHANGED，≥32B 固定布局，键已全解：IS_LINKDOWN/RSSI/SNR/NOISE/IS_INVOL/REASON/SUBREASON/DEBOUNCE×2，与我方结构一一对应）、code 9（ASSOC_DONE，需 4 字节状态码；无挂起关联记录时不投递）、code 60/63 有内部处理器。请求名表已全解：`gets 115`=POWER_DEBUG_INFO（与扫描无关），`sets 564`=FILTER_MONITOR_EVENTS（iOS 26 wifid 全程未发）。
- `annibale_sta_ask_scan` 在 `asked_join` 挂起时**静默丢弃**扫描并返回 0（712dfd16 引入）：内核 standing 重连期间 wifid 的 `sets 10` 全被吞、无 SCAN_DONE，observer 超时取到空集——这是 join 窗口期 `{()}` 的直接机制。
- 图标层结论（w85）：内核 join 成功（`join over,0`+`link,1`+DHCP）后图标仍灰；`ifconfig en0 down/up` 强制路径重评估后转实心。`mwclient`/CURRENT_NETWORK/PrimaryInterface/AirPort 键全部正常——灰标是 SpringBoard `_primaryInterface` 判定在「网络记录就绪前」被评估过一次后不再重投的状态残留；wifid 对内核代办的关联不触发自己的「已关联→推送客户端」路径（原生 ASSOC_DONE 分派也确认：无挂起关联记录的 ASSOC_DONE 不投递）。
- 原生模型：iOS 26 上 wifid 自己驱动关联（`Apple80211AssociateAsync`），内核不代办。下一轮（nrj0）单变量 `wifi_rejoin=0`：验证 wifid 自扫→自取结果→`sets 20` 自 join→图标实心的原生链路能否闭合；同时观察 type-1 `{()}` 在无内核 join 干扰下是否消失。
- 载荷 `handoff-12377-scants-nrj0.bin`（sha256 e9685d65…），同 ts1 内核仅 `wifi_rejoin=0`。

## 4. tgl9/tgl10：真实电源路径上的重连已闭合（证据目录 `kernel-12377-scansq-tgl9/`、`kernel-12377-scansq-tgl10/`）

两个早期结论经去重后被撤回：s*.log 是同一份增长日志的重叠快照，`cat s*.log` 的行号不是独立事件。

- 撤回「`ifconfig down/up` 触发 PCIe 重初始化、固件静默保活关联」：逐轮核对后，`ifconfig down/up` 从不重启驱动，leave 后 MAC 状态真实归零（`state 4→3→2→1→0`）、`joined` 标志清除、周期性 joined 行停止、tgl6 的 `current network 0x15e02c000` 是 leave 之前的基线读数。leave 后设备保持断连。
- 撤回「重挂时 standing=0」：tgl9 全程只有一次 attach（开机那次，先于 worker 加载 standing 文件），之后的 attach 行全是快照重复。没有观察到 join 之后的 attach。

真实行为（tgl10，内核 `xnu12377-scansq` 含 ask_scan 排队修正 + attach 诊断）：

- `a80211_test mwpower 0`（`WiFiManagerClientSetPower`，即控制中心实际路径）→ wifid `sets 19 (power: off)` → `the link, 0` → `power, 0` → `current network 0x0`、en0 inactive。
- `mwpower 1` → wifid `sets 19 (power: on)` → 驱动重初始化 → `power, 1`（620.56 s）→ `lx: the network that is wanted ... ch44` → MAC `state 0→4` 重新关联 → `a join is over, 0` + `the link, 1`（620.89 s，距 power,1 约 330 ms）。
- `the link, 1` 后 0.2 ms 内 wifid 连发 `gets 103`（CURRENT_NETWORK）×4、`gets 1` SSID、`gets 9` BSSID、`gets 4` CHANNEL，全部 answered——LINK_CHANGED 驱动 wifid 实况刷新，用户态拿到真网络。
- 结论：CC 关开路径的重连本来由 `sta_runs` 电源分支（`annibale_sta.c:203`）承担：`power_on && !was_joined && standing≠0 && !asked_join` 时排 standing join——`!was_joined` 读的是本次「power on」请求前的状态，电源周期下成立。standing 由开机 join 成功后写入（`:219`）并在 `ask_leave` 后保留。
- attach 处的重排代码（`:300`）是互补兜底：驱动重挂（崩恢复、降电重建）时 ops 会重新 attach，那次 attach 同样排 standing join。tgl10 电源路径未走 attach（ops 持续），该路径尚无真机覆盖。
- 待确认：`standing` 的持久性漏洞仍存在理论风险——`ask_join`（`:399`）把 standing 移入 fallback 并清零，若排队的 join 被 `ask_leave`/`ask_power(0)` 取消（`:418-420` 清 asked_join 与 fallback），standing 永久归零，且 worker 的 `standing_checked` 只加载一次。当前真机未观察到 wifid 发 `sets 20`，该序列未触发，暂不改动。
- 待确认：图标像素级验收。`sb26 layer` 的 `a=` 是图层透明度，无法区分实心/灰；本轮冻结（177.6 s）先于脚本收尾，需要截图轮判定。wifid 实况已正确，图标大概率随 CC 自身动作重评估而转实心。
- 残留问题：显式 leave（`sets 22`，非电源周期）后 wifid 只扫不 join——type-1 observer 恒 `{()}` 使 auto-join 无候选。这是另一条断连路径，与 CC 电源路径分开。

## 5. tgl12/tgl13：图标像素证据；WCL 事件实验证伪（证据目录 `kernel-12377-scanev-tgl13/`）

- 像素证据（tgl12，帧解码为 PNG 裁状态栏）：基线关联中 Wi-Fi 图标实心白；`mwpower 0/1` 电源周期重连后（`join over,0`+`link,1` 已发 21 秒）图标仍灰——内核链路全通、wifid 实况查询全对，SpringBoard 仍显示「Wi-Fi 开、未关联」。图标灰 = wifid 不把内核代办的关联记为自己的「已关联」，与 type-1 observer 恒空同源：wifid 自己不发起 join，关联状态位无人置。
- 所谓「~178 s 冻结」部分回合实为自动熄屏：`Notify Blanked: YES` 后无新帧被看门狗记为冻结，设备继续运行（后续 mwclient 仍返回重连后网络字典）。周期 `anntouch tap` 可点亮屏幕。
- tgl13 实验：SCAN_DONE 时按 heard 逐条 post 事件 201（疑 WCL_SCAN_RESULT），载荷用与 gets-11 相同的 apple80211_scan_result 序列化（2272 字节）。结果：type-1 observer 仍全部 `results='{(\n)}'`，与实验前无差别。事件码、载荷布局、投递家族三项至少一项不符，已整体撤回该改动。
- 附带确认：`WiFiSettlementObserver._handleScanResults` 的 `results` 是已过滤集合，不是原始扫描结果——即便数据进了 wifid，显示的也只是「对本次结算有用的网络」。

## 6. tgl14：扫描请求 FIFO 生效，type-1 observer 仍空（证据目录 `kernel-12377-scanq2-tgl14/`）

- 根因再收敛：wifid 在 link-up 后同一毫秒连发 `type 1(11ch) + type 2(3ch) + type 2(3ch,flags 0x2) + type 3(96ch)` 四个 SCAN_REQ，内核 `asked_scan` 只有一格，后到的覆盖先到的——只有 type-3 真跑，type-1 扫描从未执行。
- 修复：`annibale_sta.c` 挂起扫描改 8 槽 FIFO，逐个执行、按序发 SCAN_DONE（内核 `53271fc3`）。tgl14 实测：type-1 的「11 channels, asking, 110 ms」扫描真实跑完（903 ms，15 AP），后续 type-2 扫描也各跑各的。
- 但 type-1 observer 仍 `results='{(\n)}'`（13:19:05.669）——type-1 扫描真实执行并产出了 15 个网络，observer 集合依旧空。剩余差异收敛到 wifid 侧：要么是 ingest 前的过滤（结算观察者只保留「可作自动加入候选」的网络，`166666666_5G` 若不在 wifid 已知网络库则滤光），要么是 type-1 结果的分发路径与 type-2 不同。`ingestScanResults` 输入是 WiFiNetworkRef 数组，其调用方（扫描监视器按请求类型分发）待反汇编确认。
- 旁证：type-2 observer 在 FIFO 后拿到全部 15 个真实网络对象，含 `166666666_5G` RSSI=-22——结果管道本身健康。
- 状态：A7 的 CC 电源周期路径（链路、wifid 实况查询、约 330 ms 重连）已验证闭合；图标灰与显式 leave 后不复连仍开，根因收敛为 wifid 侧 type-1 结算观察者无候选网络——下一步查「已知网络库是否含 standing 网络」与 `ingestScanResults` 调用方的分发逻辑。
