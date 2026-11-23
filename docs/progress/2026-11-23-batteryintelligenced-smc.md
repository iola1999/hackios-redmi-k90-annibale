# 2026-11-23 batteryintelligenced 重复中止（S11 项内）

## 1. 根因

`ubo15` 轮系统服务中止统计新出现 `batteryintelligenced` 37 次同栈 `userabort`。取二进制反汇编：崩溃在 `-[BatteryAlgorithmsInit init]` 构造 `@{@"smcData": self.smcKeys, @"systemState": self.deviceState}` 时向 `initWithObjects:forKeys:count:` 插入 nil 对象，抛 `NSInvalidArgumentException`，launchd 反复拉起（ubo15 日志里 pid 130→383→405→414）。

`smcKeys` 只是 ivar getter，赋值来源 `sub_100001748` 走 `IOServiceMatching("AppleSMC")` 枚举 SMC 键。SM8750 没有 SMC 设备，服务查找返回 `kIOReturnNotFound`，键表始终未赋值，`smcKeys` 恒 nil。

## 2. 改动

平台层补最小 `AppleSMC` 兼容服务，不动 Apple 二进制：

- `xnu/files/iokit/Kernel/AnnibaleSMC.cpp`：类名 `AppleSMC` 的 `IOService`（`IOServiceMatching` 是类匹配，匹配类名与其子类，`setName` 不起作用）加 `AppleSMCUserClient`。`IOConnectCallMethod`/`IOConnectCallStructMethod` 的键读写统一回 `kSMCKeyNotFound`（0x84，SMCParamStruct 偏移 0x28 状态字节）并回填 0xA8 字节应答结构，调用方得到空但非 nil 的键表。
- `xnu26/patches/30-iokit%conf%files.patch` 加编译项；`annibale_battery_init`（`xnu/files/bsd/dev/annibale/annibale_battery.c`）在平台校验后、battery 门控前调 `AnnibaleSMCStart()` 注册——daemon 需要它，与我们的电量计驱动是否启用无关。

## 3. 过程记录

第一版（say19）两处错误，ubo16 真机证伪：

- 调用点加在构建树 `xnu-src` 的 `annibale_battery.c`，`build-macos.sh` 每次构建把 `xnu/files` 覆盖层同步进 xnu-src，未入库的调用点被还原，`AnnibaleSMCStart` 无人调用。
- 服务类命名 `AnnibaleSMC` 只配 `setName("AppleSMC")`，不满足类匹配。即使注册成功 `IOServiceMatching("AppleSMC")` 仍查不到。

ubo16 轮日志据此看到 daemon 继续中止（pid 155 有 31 条 userabort 后换成 408）。第一次「零中止」结论来自尚未覆盖崩溃段的日志快照，复核后作废。

## 4. 真机验收

`kernel-12377-say20-ubo17`：`batteryintelligenced` pid 153 常驻，60 秒复测 pid 不变；全轮日志 `batteryintellige` 的 `userabort` 0 次（ubo15 同口径 37 次、ubo16 31+ 次），全部进程 `userabort` 0 次；映射了 `default_factors_BATTERYINTELLIGENCE_BATTERY_ANALYSIS(_TTL)_fbs.bin` 模型文件——越过原崩溃点进入算法初始化。本轮 0 次 AIRFAIL、无 panic。

## 5. 边界

- 服务应答是空键表：所有 SMC 键查询返回 not-found。daemon 能继续跑，但任何依赖 SMC 键值的功能拿到的是「键不存在」语义而非数据。
- daemon 越过崩溃点后是否触达下一个缺失的平台服务，本轮只观察到常驻与模型文件映射，未逐条跟踪其后续请求。
