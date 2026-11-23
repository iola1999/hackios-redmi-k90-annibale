# 2026-11-24 batteryintelligenced 启动竞态残余（S11 项内）

## 1. 根因

[11-23 batteryintelligenced 电源属性树](2026-11-23-batteryintelligenced-smc.md) §5 记录的边界这次发生了：`AnnibaleBattery` 在第一次电量上报时才注册服务，而 `batteryintelligenced` 的 XPC activity 回调里的 `dispatch_once`（即 `-[BatteryAlgorithmsInit init]`，构造 `@{@"smcData": ..., @"systemState": ...}`）可以早于 ADSP 电量管理器的首个上报触发。此时 `IOServiceMatching("IOPMPowerSource")` 匹配不到服务，属性树为 nil，`smcKeys`/`deviceState` 成员为 nil，向 `initWithObjects:forKeys:count:` 插 nil 抛 `NSInvalidArgumentException`。

与首次修复（say21）的差别：那次是结构性的（`BatteryData`/`ChargerData` 字典一直缺），每次 init 必崩、launchd 循环拉起 37 次；这次是启动时序竞态，每次开机最多崩一次，重拉时服务已存在即恢复。设备崩溃报告里 `batteryintelligenced-2026-11-23-012805.ips` 即为该窗口的中止，崩溃帧与 say21 前同栈。

## 2. 改动

- `xnu/files/iokit/Kernel/AnnibaleBattery.cpp`：服务创建抽为 `make_service()`；新增 `AnnibaleBatteryStart()` 在内核早期创建服务，`placeholders()` 在 attach 前发布空的 `BatteryData`（含 `LifetimeData`）/`ChargerData` 骨架；`report()` 的 dict 发布块抽为 `dicts(cycles)`，骨架与真实读数共用同一形状。首条读数到达后 `report()` 正常填充全部属性。
- `xnu/files/bsd/dev/annibale/annibale_battery.c`：`annibale_battery_init` 在 `AnnibaleSMCStart()` 之后调用 `AnnibaleBatteryStart()`，不受 `battery=` 启动参数影响（禁用电量采集时服务仍在，属性骨架为空）。

## 3. 真机验收

`kernel-12377-say53-ubo55`：内核 init 阶段服务注册成功（无 `the power source service failed to register`）；首条读数日志 `AnnibaleBattery: the battery's power source is up: 96%, charging` 正常；全轮无 `userabort`；`batteryintelligenced` 单 pid 153 常驻；CrashReporter 无新增 batteryintelligenced `.ips`（最新一份停在修复前的 `2026-11-23-012805`）。`locationd` pid 69 本轮亦存活（其 `writeData:` 中止是另一条根因，见 backlog S11，本轮不能作为其修复证据）。

## 4. 边界

- 服务存在但尚无读数的窗口内，电源属性只有骨架字典，`CurrentCapacity`/`MaxCapacity` 未发布，powerd 读到的无电池状态是瞬时的，首个上报的 `kIOPMMessageBatteryStatusHasChanged` 触发重读。
- `battery=0` 时服务保持骨架状态，与「禁用电量采集」语义一致。
