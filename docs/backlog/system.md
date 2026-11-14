# 系统与持久化待办

本表集中系统服务、应用管理与存储的未完成事项，2026-11-12 整理。正在执行的系统批次保留在[系统后续事项](../plan/2026-11-12-system-followup.md)，实现、构建及真机状态以[系统契约核查](../analysis/2026-11-12-system-contracts.md)为准。其他主题见[待办入口](README.md)。

## 1. 当前批次

| 编号 | 事项 | 当前边界 | 下一步与验收 | 来源 |
|---|---|---|---|---|
| S1 | 退出前全量刷新 | 遍历遗漏、错误上报和 vnode 生命周期已修复，宿主检查与完整内核构建通过，真机读回待验 | 同桶至少 9 个可写映射文件，正常退出后重启读回；另核对退出期间继续写入和并发卸载的边界 | [系统批次 S1](../plan/2026-11-12-system-followup.md)、[系统契约](../analysis/2026-11-12-system-contracts.md) |
| S2 | 异常复位与写缓存一致性 | 元数据双槽恢复已有实现；数据页原位覆盖、立即复用和设备写缓存仍需分析 | 完整 VFS 场景覆盖回收前 fsync 失败、备用旧槽恢复；核对 F_FULLFSYNC、WRITE FUA、SYNCHRONIZE CACHE 与 UFS 缓存；明确正常重启与异常复位的保证范围 | [系统契约 §3](../analysis/2026-11-12-system-contracts.md)、[上游对照 §3.3](../analysis/2026-11-12-upstream-review.md#33-ufs-完成等待与缓存同步) |
| S4 | 原生应用卸载 | 重复删除逻辑已移除，宿主及目标库检查通过，真机待验 | 用可重装测试 App 验证资格检查、数据容器清理、错误回调、卸载后重装 | [系统批次 S4](../plan/2026-11-12-system-followup.md)、[注入钩子分析](../analysis/2026-11-09-injection-hooks.md) |
| S5 | 后台应用切回前台 | 固定诊断轮的设置冷启动已显示首页，进程与 scene 对照成功；历史后台复用仍待复现 | 确认后台实例及启动来源，再同轮对照复用、重新启动和多任务卡片 | [执行计划](../plan/2026-11-12-app-foreground.md)、[核查记录](../analysis/2026-11-12-app-foreground.md) |
| S9 | 持久化同步的 CPU 开销 | 已提交检查点接近槽位上限，AIR 缓存占用最多，生产 C 复算完成；容量失败状态修复已通过宿主故障、并发检查及完整内核链接，真机待验 | 核对缓存增长与运行态待写容量，对照未变化请求与真实变化后的同步；保留双槽原子性和失败返回；验收设备锁等待、固定交互长帧及退出读回 | [性能核查 §2](../analysis/2026-11-13-performance-log-review.md#2-s9容量失败与重复同步)、[执行安排](../plan/2026-11-12-system-followup.md#5-性能分析与验证安排)、[渲染核查 §5](../analysis/2026-11-12-rendering-runtime.md#5-元数据打包的重复写入)、[零尾候选](../analysis/2026-11-11-multimedia-validation.md#84-ramfs-零尾候选与-safari-读回失败) |

S3 温度上报列在[外设与电源](platform.md)，S6／S7 列在[图形与显示](graphics.md)，S8 列在[外设与电源](platform.md)。当前批次已有负责人，接续前先核对其最新结果与修改范围。

## 2. 可选择的后续事项

| 编号 | 事项 | 状态与已知条件 | 下一步与验收 | 来源 |
|---|---|---|---|---|
| S10 | 文件身份往返 | APFS 改用原生挂载身份分配，15 项宿主检查和目标编译通过；只读设备工具已就绪 | 验证 System、Data、Cryptex 和应用文件的实际往返；另查 APFS／ramfs／IOKit 的卷 UUID 一致性 | [渲染核查 §4](../analysis/2026-11-12-rendering-runtime.md#4-apfs-文件身份)、[系统契约 §6](../analysis/2026-11-12-system-contracts.md#6-应用前台切换) |
| S11 | 系统服务崩溃 | 待当前镜像复测；旧记录包括 cloudd 的 NULL cString 与 MessagesBlastDoorService 空 sandboxProfileName；cd14 新增 siriactionsd 解归档异常 | 先确定复现频次与原生输入，再修复对应服务、资源或内核契约 | [崩溃报告 §5](../analysis/2026-11-09-crash-reports.md)、[多媒体验证 §22](../analysis/2026-11-11-multimedia-validation.md#22-bsd-crc32-指令加速) |
| S12 | Weather 与 Maps 内容 | 待当前镜像复测；旧轮 Weather 无温度、Maps 停在定位提示，geod 已有 HTTP 200／304 | 分别记录网络、定位、服务响应和界面结果；复核 syncdefaultsd 的容器返回值及两层任务过滤，按首个失败阶段处理 | [问题复核 §3.3](../analysis/2026-11-08-issue-reassessment.md#33-音频与网络) |
| S13 | Spotlight 与 ScreenContinuity 复核 | 条件候选；完整系统盘已部署，旧轮有 ScreenContinuity SIGTRAP | 先用当前镜像确认是否仍复现，再核对实际调用与资源；旧裁剪镜像的缺失数量仅作历史记录 | [Spotlight 分析](../analysis/2026-10-31-spotlight-crash-loop.md) |
| S14 | TrollStore 卸载与共享容器归属 | 待核查；TrollStore 的 uninstallApp() 在原生卸载前删除容器，Group 已有多使用者检查，删除使用 error:nil | 检查 Group 使用者枚举完整性、容器删除顺序及错误传播，验证卸载后其他应用的数据和重装状态；S4 负责原生卸载 | [系统契约 §5](../analysis/2026-11-12-system-contracts.md)、[注入钩子分析](../analysis/2026-11-09-injection-hooks.md) |
| S15 | 偏好与跨开机数据覆盖 | 待验证；正常重启检查点与测试文件已有读回结果 | 逐项验证系统设置、Wi-Fi、桌面布局、应用数据及更新后的偏好；异常复位属于 S2 | [根文件系统 §5、§6](../analysis/rootfs-strategy.md) |
| S16 | 中文、字体与通知权限复测 | 已有资源与实现，用户可见结果待当前镜像复核 | 检查中文应用名、目标网页字体、通知授权及重启后状态 | [问题复核 §2](../analysis/2026-11-08-issue-reassessment.md)、[架构审查 §12.4](../analysis/2026-11-08-architecture-review.md) |
| S17 | LiveContainer／SideStore 兼容性 | 后续候选；原生安装与前台切换由 S4／S5 跟进 | 按选定应用检查安装、签名、JIT、启动和数据持久化，记录各阶段实际限制 | [问题复核 §2](../analysis/2026-11-08-issue-reassessment.md)、[架构审查 §12.5](../analysis/2026-11-08-architecture-review.md) |

Weather 的 Mescal 依赖继续按原调研记录；FairPlay 与 App Store 不在本轮范围内。
