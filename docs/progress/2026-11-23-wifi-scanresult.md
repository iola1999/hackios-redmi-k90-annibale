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
- 但 type-1 observer 仍 `results='{(\n)}'`（13:19:05.669）——type-1 扫描真实执行并产出了 15 个网络，observer 集合依旧空。剩余差异收敛到 wifid 侧：要么是 ingest 前的过滤（结算观察者只保留「可作自动加入候选」的网络，`<SSID>` 若不在 wifid 已知网络库则滤光），要么是 type-1 结果的分发路径与 type-2 不同。`ingestScanResults` 输入是 WiFiNetworkRef 数组，其调用方（扫描监视器按请求类型分发）待反汇编确认。
- 旁证：type-2 observer 在 FIFO 后拿到全部 15 个真实网络对象，含 `<SSID>` RSSI=-22——结果管道本身健康。
- 状态：A7 的 CC 电源周期路径（链路、wifid 实况查询、约 330 ms 重连）已验证闭合；图标灰与显式 leave 后不复连仍开，根因收敛为 wifid 侧 type-1 结算观察者无候选网络——下一步查「已知网络库是否含 standing 网络」与 `ingestScanResults` 调用方的分发逻辑。

## 7. tgl15–tgl25：已知网络库为空；mwjoin 播种成功但 AssociateAsync 不发 sets 20

- tgl15 根因确认：`restart wifid` 后读 `/private/var/db/wifi.plist`，`List of known networks: []`——wifid 已知网络库是空的（w81 时代该表有 `<SSID>`，rootfs 重置后丢失）。auto-join 无候选（`relevant passes: ()`），type-1 observer 空集是候选过滤的结果，不是分发问题。
- mwjoin 迭代（`a80211_test.c`）：读 standing 文件拿 SSID+PMK → `WiFiNetworkCreateWithSsid` → `WiFiNetworkSetPassword`（系统钥匙串写成功，PMK 编 64 位 hex 作为 WPA 口令，对应内核 cipher 6）→ `WiFiNetworkSetWPA`（不设则持久化记录 `isWPA=0`，wifid 按开放网络处理）→ `WiFiManagerClientAddNetwork`（返回指针型句柄而非错误码，回读 `CopyMutableNetworks` 确认 count 1：`<SSID>` isWPA=1 enabled=true Channel=44）。
- tgl21 正向结果：已知网络播种后 type-1 observer 输出真实结果（`RJ_<SSID>`、`<SSID>` RSSI=-21 等在集合内）——证实空集主因是「已知网络库为空时候选过滤滤光」，播种后过滤放行。
- 卡点：`WiFiDeviceClientAssociateAsync(device, net, opts, cb)` 各形态都返回 0 但 wifid 从不发 `sets 20`：临时 net/持久化记录（tgl25 `stored 0x100c20ac0`）、opts=NULL/{password}、关联中/leave 后未关联、客户端退出（tgl22 日志证实退出触发 `__WiFiServerClientTerminationCallback ... cleanup state`，挂起关联被回收）vs 存活 30 s（tgl23/25 全程无 sets 20）。wifid 受理请求到发 Apple80211 ASSOCIATE 之间还有内部门槛（UnifiedAutoJoin 状态机或关联参数预填充），IDB 会话反复断线未取到该路径。
- 图标因果链完整：内核 standing join 恢复链路但 wifid 关联状态位无人置 → 图标灰（tgl12 像素证实）；修复方向只剩「让 wifid 自己完成一次关联」或「找到 wifid 认定的等价关联登记入口」。
- 下一步（待做）：反汇编 `WiFiDeviceClientAssociateAsync` 的服务端处理（wifid 内 `__WiFiDeviceManager*` 路径，含 `UnifiedAutoJoinIsStateSuitableForNetworkTransition` 判定），或试 `WiFiManagerClient` 层的 AutoJoin/JoinNetwork 入口；拿到服务端门槛后补齐 mwjoin 参数。

## 8. tgl25 之后：AssociateAsync 为什么从不发 sets 20（wifid 反汇编，部分结论）

- 实测：`WiFiDeviceClientAssociateAsync` 返回 0、客户端进程存活 30 s、已知网络表里有 `<SSID>`（isWPA=1 enabled），wifid 仍然既不打 `[corewifi] __associate Manual Association Requestion` 也不打 `Attempting Apple80211AssociateAsync`——低层关联从未开始。
- `-[WiFiXPCManager __associate:XPCConnection:]`（0x100105fd0）是手动关联的 XPC 入口：它要求请求参数里 `scanResult`→`scanRecord` 非空，合成关联字典后调低层 `sub_1000CFF3C`（= `WiFiDeviceManagerAssociateAsync` 本体，0x1000cff3c，内部含全部 policy/auto-join 判定与 WFLog）。我们的调用没走这条路。
- `sub_1000CFF3C` 共 9 个调用点，其中 `0x1000e4bb8` 是一个 op=1026 的 block（队列任务），`0x1000c7c40` 是 ColocatedSSID 通知回调，`__associate` 是 op=手动；剩余 `sub_1000DB0A4`(0x28c)、`sub_1000F317C`、`sub_1000FF11C`、`sub_10018074C`、`sub_1001A2D38` 未展开。
- 工作假设（待证）：`WiFiDeviceClientAssociateAsync` 走 `WiFiDeviceAssociateAsync`/`...WithCommand` 操作码，进 `__WiFiDeviceAssociateAsyncQueued` 排队器，由 auto-join 引擎在下一次自家扫描出匹配 scanResult 时才放行；我们传的是已知网络持久化记录（无 scanResult/BSSID/IE），且当时已是关联状态（`AutoHotspotStatusAlreadyAssociated` 分支）。引擎既无新扫描结果可用、又可能以「已关联同 SSID」跳过，于是请求挂起不报错。
- 下一步：反汇编 `sub_1000DB0A4`（队列排空函数）看放行条件；并行试 `leave` + 由 wifid 自家扫描产生 scanResult 后再调 `AssociateAsync`（或改发 `WiFiDeviceAssociateAsyncWithCommand` / 同步 `Apple80211Associate`），让请求带得上 scanRecord。

## 9. tgl30：补上 `ScheduleWithRunLoop` 后扫描回调通，scanResult 记录仍不放行

- **此前各轮还有一个更浅的客户端缺陷**：MobileWiFi 客户端要先 `WiFiManagerClientScheduleWithRunLoop(client, runloop, mode)` 把 XPC 连接挂到 runloop，异步回包才会派发。未调度时 `ScanAsync` 返回 0、wifid 侧确实扫描（`WiFiSettlementObserver ... client='a80211_test'`），但回调函数一次都没跑——tgl14–tgl25 里 `AssociateAsync` 的完成回调同理从未送达。
- 修正后（`mwxjoin`：`ScheduleWithRunLoop` → `ScanAsync` → 在回调里取扫描结果记录 → `AssociateAsync(device, scanRecord)`）：扫描回调正常返回 8 个结果（`<SSID>` 在 0/1 位），`AssociateAsync(scan-record 0x101459f70) -> 0`。
- 但 wifid 仍没打 `starting forced association scan`、没发 `sets 20`；16:03:14 只出现 `network session ended/started`（22 ms 间隔、无底层 ioctl，属会话记账事件）。即把记录换成真正的 scanResult 形态后，`AssociateAsync` 请求仍没到 `WiFiDeviceManagerUserForcedAssociation`——§8 的「记录形态门槛」假设被部分证伪，断点在 op-code 分发更上游。
- 顺带观测：客户端退出仍触发 `cleanup state`；`mwxjoin` 全程存活已排除这条干扰。
- 下一步：反汇编客户端 `_WiFiDeviceClientAssociateAsync`（0x264b62074）取它实际发出的 op-code 和参数字典键，再到 wifid 找对应 handler 的前置条件；不要再按「记录形态」猜参数。
- 追加实验（同轮 cmd-20）：先 `WiFiDeviceClientDisassociate`（wifid 确实把链路断了，`the link, 0`），再用扫描记录调 `AssociateAsync`，仍无强制关联扫描、无 `sets 20`——「已关联短路」假设也证伪。注意 wifid 的 WFLog level-3（`Enqueuing command`、`starting forced association scan`、`Currently associated` 同属此级）在本日志里不显示，只能用副作用判定。
- 服务端路径已定位：`WiFiDeviceAssociateAsync`/`WithCommand` → `sub_10006594C`/`sub_1000659DC` → `__WiFiDeviceCommandEnqueue`（`sub_1000297A0`，命令入设备队列，队列泵是 `__WiFiDeviceDispatchQueuedAssociationEvent`/`sub_10006AA48`）→ 执行时进 `WiFiDeviceManagerUserForcedAssociation`（`sub_1000DAD08`，先强制扫描，回调 `sub_1000DB0A4` 用 CFEqual 比对扫描结果再调 `sub_1000CFF3C`）。断点在「入队后队列泵是否放行」或更上游的 XPC 分发：断开后强制扫描连 `sets 10` 都没发，说明命令没排到执行或排在了一个不放行的状态。
- 下一步收窄为：反汇编队列泵 `sub_10006AA48`（0x748 字节，含 `__WiFiDeviceDispatchQueuedAssociationEvent` 引用）看它的放行条件（设备状态字 +52、pending 门、power 门），以及 `WiFiDeviceClientAssociateAsync` 的 XPC op 是否真的落到 `sub_10006594C` 入口。
- 队列机制已查清：`sub_10006AA48` 实际是**关联完成回调**（os_log 输出 `Completed Apple80211AssociateAsync`/`%s Joined:`/`Failed to join`，完成时调 `device+4088` 存的完成函数）。
- 执行侧是 `__WiFiCommandQueueCallback`（`sub_100029DBC`，10 KB 命令分发 switch）：associate 命令进 `__WiFiDeviceAssociateAsyncQueued` 分支（先打 level-3 `Starting %d second(s) timer`，再按 `sub_1000A4BE4`/`sub_10000A850` 网络检查选 EAP/普通路径）。
- tgl30 全程没出现完成回调的 os_log——**命令进了队列但从未执行**：`Enqueue` 只挂进 `device+176` 队列，靠 `__WiFiCommandQueueTimerCallback`（`sub_1001A61A0`）驱动；断开后队列泵可能因前一个关联挂起（`device+5320` in-flight 标志在完成回调里才清零）或 timer 未重新武装而停摆。
- 剩余卡点（精确）：入队到 `sub_100029DBC` 分发之间——查 `sub_100029A58` 入队后谁武装 timer、`sub_1001A61A0` 的触发条件，以及 `device+5320` in-flight 清除时机。这是纯 wifid 用户态问题，与内核驱动无关；原生路径（设置里点选网络）在真机上可用，说明我们的请求缺了原生客户端会填的某个字段或顺序（比如先 `AssociateCancel` 清 in-flight）。

## 10. tgl31/tgl32：灰图标的像素对照与事件载荷根因（内核侧）

- **像素对照成立**（tgl31，say3 内核）：开机 standing 重连后桌面截图 `shot-00789` 的 Wi-Fi 扇形实心白；同一轮 `mwpower 0/1` 电源周期、内核 `the link, 1` 重连成功后，`shot-03689` 的扇形为半透明灰。两条路径内核状态相同，差别在 wifid 学到的关联状态。
- **机制差异**：开机时 wifid 在 join 事件之后启动，靠 `gets` 主动查到当前网络；电源周期时 wifid 活着收到 kev 事件——而内核发 `EVENT_SSID_CHANGED`/`EVENT_BSSID_CHANGED` 的载荷是 `NULL, 0`，`EVENT_POWER_CHANGED` 同样空。wifid 按空 SSID 事件把「当前网络」清掉，图标转灰。
- **修复（内核 `12377-say4`）**：`annibale_apple80211.c` 三处改——
  - `ANNIBALE_STA_LINK` 分支：`SSID_CHANGED` 带 `apple80211_ssid_changed{version, ssid_length, ssid[32]}`，`BSSID_CHANGED` 带 `apple80211_bssid_changed{version, bssid[6]}`，link-up 时填 `state->bss`，link-down 时留空（原生语义：断开即清空）。
  - `ANNIBALE_STA_POWER` 分支：`POWER_CHANGED` 带 `apple80211_power_changed{version, state}`。
  - `sets 564`（FILTER_MONITOR_EVENTS）分支同样改填。
- 验证轮 `tgl32`（say4）：开机 standing 重连 → `mwpower 0/1` → 查 `the link` 与 wifid `gets 1/9` → 截图判图标像素。
- 遗留（未变）：`AssociateAsync` 入队不执行的服务端卡点仍是 §9 的状态——本修复针对「内核代办关联后 wifid 状态学不到」的图标灰，两者是同一症状的不同层面：图标转实心后 `AssociateAsync` 不通仍是独立待办。

## 11. tgl32/tgl33：图标灰修复（say5：POWER 事件延迟到 standing join 完成）

- **say4 实验结论（tgl32）**：SSID/BSSID/POWER 事件载荷填上后，关开 Wi-Fi、内核 `the link, 1` 重连成功，图标**仍灰**（shot-05695 同 say3 表现）。事件载荷完整化是原生对齐的改进（保留），但单独不置 wifid 的关联状态位。
- **决定性实验（tgl32）**：关联状态下 `restart wifid` → wifid 重启枚举到 JOINED → 图标转实心（shot-07049）。与开机实心同一机制：wifid 只在其枚举设备状态的时机把「已关联」记进自己的状态机。
- **根因定版**：`sets 19 power:on` 后 wifid 立即枚举设备状态（日志 8794–8827 一串 gets），而内核把 POWER(1) 事件在 `ops->power()` 返回时即发——枚举全部落在 standing join 完成之前（全部 error 6，STATE=0）。原生 iOS 的关联由 wifid 自己发起，本就不存在这个窗口；我们的 standing 重连是内核代办，POWER(1) 必须等 join 完才能让枚举查到 JOINED。
- **修复（say5，`annibale_sta.c`）**：power-on 且 standing join 会排队时，POWER(1) 事件挂起（`power_report_pending`），在 join 完成时先于 JOIN_DONE/LINK 补发；`ask_power(0)` 取消排队 join 时丢弃该挂起（POWER(0) 照常），`ask_leave` 时补发（radio 仍开，事件不能再等）。
- **tgl33 真机验收**：
  - 时序：`sets 19 on` → `power, 1` 紧贴 `a join is over, 0` + `the link, 1` 出现（延迟生效）。
  - wifid 枚举：`gets 103 CURRENT_NETWORK answered`、`gets 13 STATE=4`（JOINED）、`gets 1 SSID` 返回 12 字节（"<SSID>"）、`gets 9 BSSID` answered；configd 同查同答。
  - 像素：唤醒+解锁后 `shot-01435` 状态栏 Wi-Fi 扇形**实心白**，与 say3 灰图（tgl31 shot-03689）逐项对照成立。
- **边界**：修复的是「内核代办关联对 wifid 可见性」的时机问题；wifid 自家 `AssociateAsync` 队列不执行（§9）与 type-1 observer `{()}`（§6）是独立待办，本修复不含它们。图标实心的机制是「枚举时关联已成立」，wifid 内部关联状态位的具体字段未逐字节核对。
