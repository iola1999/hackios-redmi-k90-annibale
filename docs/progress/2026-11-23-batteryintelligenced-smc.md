# 2026-11-23 batteryintelligenced 重复中止（S11 项内）

## 1. 根因

`ubo15` 轮系统服务中止统计新出现 `batteryintelligenced` 37 次同栈 `userabort`。取二进制反汇编：崩溃在 `-[BatteryAlgorithmsInit init]` 构造 `@{@"smcData": self.smcKeys, @"systemState": self.deviceState}` 时向 `initWithObjects:forKeys:count:` 插入 nil 对象（`objects[0]`），抛 `NSInvalidArgumentException`，launchd 反复拉起。

`smcKeys` 的赋值在 `init` 内（0x1ddc）：`init` 先经 `IOServiceMatching("IOPMPowerSource")` + `IORegistryEntryCreateCFProperties` 取第一个电源服务的注册表属性（`battData`），再要求 `battData["BatteryData"]`、`battData["ChargerData"]`、`BatteryData["LifetimeData"]` 均为 `NSDictionary`，全部通过才构造 `smcKeys` 字典，任一失败 `smcKeys` 为 nil。属性里缺失的叶子字段被包装成 `NSNull`，安全；缺的是字典本身才致命。我们的 `AnnibaleBattery`（`IOPMPowerSource` 子类）只发布了标准电量键，没有这三个嵌套字典——`smcKeys` 恒 nil，崩溃环成立。

## 2. 改动

- `xnu/files/iokit/Kernel/AnnibaleBattery.cpp` 的 `report()` 在每次电量上报时同步发布 `BatteryData`（含 `LifetimeData` 子字典、`CycleCount` 叶子）与 `ChargerData` 两个 `OSDictionary`——daemon 的崩溃环拆开。say21。
- `xnu/files/iokit/Kernel/AnnibaleSMC.cpp`：类名 `AppleSMC` 的 `IOService` 加 `AppleSMCUserClient`，SMC 结构调用统一回 `kSMCKeyNotFound`（0x84）。这是 daemon 另一条 SMC 路径（`algoWriteValidSmcKeys:` 经 `sub_1000015C8` 读键信息+键值）需要的服务，与本崩溃无关但保留——没有这个服务，该路径的 daemon 功能拿到 `kIOReturnNotFound`。
- `xnu26/patches/30-iokit%conf%files.patch` 加编译项；`annibale_battery_init` 在平台校验后调 `AnnibaleSMCStart()`。

## 3. 过程记录

先后两次把 daemon 进程的崩溃归错位置：

- 第一次定位停在 `smcKeys` 的取值来源 `sub_100001748`（AppleSMC 键查询封装），据此做了 AppleSMC 兼容服务。`sub_100001748` 及其上层 `sub_1000015C8` 确实走 `IOServiceMatching("AppleSMC")`，但只被 `algoWriteValidSmcKeys:` 调用，与 `init` 里 `smcKeys` 的赋值路径无关。
- ubo17（say20，仅 AppleSMC）日志后来复核：`batteryintellige` 的 `userabort` 实际 71 次（pid 153→402→437→488 同栈），「pid 常驻」结论来自未覆盖崩溃段的快照。AppleSMC 服务对 `init` 崩溃无影响。
- 把 `init` 全函数反编译后才看到 `smcKeys` 真正的赋值点（0x1ddc）和它依赖的 `IOPMPowerSource` 属性树。教训：定位 nil 值来源必须看到 ivar 的写入点，不能只追到被赋值的 getter 或同名字段的读取函数。

## 4. 真机验收

✅ `kernel-12377-say21-ubo18`：全轮 67 段日志 `batteryintellige` 的 `userabort` 0 次、全部进程 `userabort` 0 次；`batteryintelligenced` 单 pid 146 常驻（启动至复测 90 s+ 无替换），映射 `default_factors_BATTERYINTELLIGENCE_BATTERY_ANALYSIS(_TTL)_fbs.bin` 模型文件越过 init 进入算法工作；本轮 0 次 AIRFAIL、无 panic。

基线：ubo15 同栈 37 次、ubo16（无服务）31+ 次、ubo17（仅 AppleSMC）71 次（pid 153→402→437→488 轮换）。

## 5. 边界

- `BatteryData`/`ChargerData` 里 daemon 读不到的叶子（`AlgoChemID`、`Serial`、`VacVoltageLimit` 等）在 daemon 侧落 `NSNull`——不崩，但算法拿这些字段时没有数据。
- `AnnibaleBattery` 在第一次电量上报时注册服务；daemon 若先于第一次上报启动仍会见不到服务（后续重启时恢复）。
- AppleSMC 应答为空键表：`algoWriteValidSmcKeys:` 路径的功能拿到「键不存在」语义而非数据。
