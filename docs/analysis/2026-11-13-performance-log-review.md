# 性能日志核查：持久化、缓存、显示计时与调频（2026-11-13）

## 1. 范围与阶段结论

本次核查使用 iOS 26.6.2（23G90）的 cd37 旧窗口、后续 fsync 诊断轮、11-13 STAGE1 的两个桌面事件、冻结源码及宿主分析结果。旧窗口源码复核以内核 `20550698` 为起点；生产修复的实际输入见所属小节清单。各轮参数和输入分别核对，不合并不同轮次的耗时。执行安排见[系统后续事项 §5](../plan/2026-11-12-system-followup.md#5-性能分析与验证安排)。

| 方向 | 已确认结论 | 当前验证边界 |
|---|---|---|
| STAGE1：返回桌面卡顿 | 21:59:33 附近的连续显示提交相隔约 4.14 秒，间隔在 backboardd 进入显示驱动前已形成 | 同窗有 SpringBoard 主线程 Metal 专化和文件操作采样；原生专化、缓存写入与同步的耗时尚未分开，见 §3.4 |
| STAGE1：图标透明 | 两个现场窗口均已保存；原生可见性为 2 的分支会延迟图标更新 | 本轮缺少可见性、动画断言和图层内容状态，图标恢复原因待确认，见 §3.5 |
| S9：持久化同步 | 已提交检查点接近槽位上限，AIR 缓存占用最多；容量失败状态修复省去未变化请求的重复打包 | 宿主故障、并发检查及完整内核链接通过；运行态待写容量和设备收益待验证 |
| G15：缓存与启动 | 常量归档失败后的旧键包含实例地址，相同值的新对象生成不同键；稳定键和旧缓存读取已通过宿主检查，候选完成 arm64e 构建 | 旧文件的完整输入关联、实际内容重复率、真机收益及各等待阶段占比待验证；观测需覆盖实际 renderer bundle |
| S7／G9：显示 | 现有复制区间包含取锁、上一帧 flush 等待、哈希、缩放和显示提交；私有分段计时候选已完成 arm64 对象编译 | CPU 缩放占比、计时开销及物理面板完成时刻尚未取得 |
| P11：调频 | cd37 实际策略参数与 11-09 说明不同；日志记录成功应答后的请求档位 | 实际时钟、完整温控限频时长与功耗归因待测 |

S9 修改保持 ANNFS001 version 3 和双槽提交顺序，处理容量失败后的重复工作。生产候选完成完整内核链接，STAGE1 匹配候选完成 handoff 装配；真机验收待完成。此前零尾候选的真机失败范围见[多媒体验证 §84](2026-11-11-multimedia-validation.md#84-ramfs-零尾候选与-safari-读回失败)。

用户指定的旧十秒停顿仍缺少持锁线程与界面进程的关联，根因未确认；保存内容与窗口结论见[多媒体验证 §73](2026-11-11-multimedia-validation.md#73-启动与十秒停顿的性能分析)。

## 2. S9：容量失败与重复同步

### 2.1 已确认的锁竞争

后续诊断轮的容量出口和最长锁等待见[多媒体验证 §81](2026-11-11-multimedia-validation.md#81-ramfs-元数据槽位与同步等待)。本次按独立 pack 记录复算该等待区间，未重复计入外层同步记录。

| 项目 | 结果 |
|---|---|
| 等待区间内的其他线程 | 41 个 tid |
| 完整失败打包记录 | 760 次；inode／xattr／dirent 出口分别为 745／12／3 次 |
| 打包区间并集 | 12.037835 秒，占该锁等待区间 84.4278% |
| 取得锁后的本次打包 | 13.629 ms，随后返回 ENOSPC |

诊断轮使用的 [`ramfs_disk_sync_impl()`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_disk.inc) 在容量失败出口保留 `rm_meta_dirty`。后续同步重新取得 `rm_lock` 并全量打包。该出口尚未执行本次 payload／super 写入，以上读数无法确定 UFS 写入耗时。

私有 pack 失败输出在持锁期间执行，阶段计时结束后仍有打印开销；正式源码没有该容量失败打印。760 次遍历和锁竞争已确认，诊断输出的额外锁持有时间与生产版本等待量仍需分开测量。

本次调用路径核查发现，`fcntl(F_FULLFSYNC)` 经一次 `VNOP_IOCTL` 进入 [`ramfs_ioctl()`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_fsctl.inc)，先写回共享映射页，再同步一次元数据。所查 vnode pager 与 cluster 路径未出现第二次 `VNOP_FSYNC`；`F_BARRIERFSYNC` 的回退条件为 ENOTTY、ENOTSUP、EINVAL，ENOSPC 不触发该分支。连续失败来自后续同步请求，当前调用路径未确认内部重复同步。

### 2.2 已提交检查点的容量组成

ANNFS001 version 3 的记录由 [`ramfs_disk_pack_locked()`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_disk.inc) 写入、[`ramfs_disk_unpack()`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs_disk_restore.inc) 恢复。每槽 payload 上限为 33,550,336 字节；变长段分别按 8 字节对齐。

| 类别 | 字节组成 |
|---|---|
| inode | 144 字节固定头，加对齐后的软链接目标和文件块索引 |
| 文件块索引 | 每项 4 字节，包含内部空洞索引 |
| xattr | 8 字节固定头，加对齐后的名称与值 |
| 目录项 | 16 字节固定头，加对齐后的名称 |

已正常停止文件系统后取得完整双槽前缀，宿主与设备的长度及校验值一致。来源分区为 111,669,129,216 字节；64 MiB 前缀覆盖两个元数据槽。当前布局的 panic 区为 64～80 MiB，文件数据区从 512 MiB 开始，布局以生产源码中的常量为准。

| 最新检查点项目 | 结果 |
|---|---|
| 槽位与恢复检查 | 两槽均通过 CRC、结构和范围检查；slot0 为 gen802937，slot1 为 gen802936 |
| 节点数 | 两槽均为 139,271 |
| payload／上限／剩余 | 33,550,192／33,550,336／144 字节 |
| inode 固定记录 | 20,055,024 字节 |
| 目录项 | 10,581,520 字节，其中名称为 7,806,227 字节 |
| 文件块表 | 2,152,128 字节 |
| xattr | 760,440 字节 |
| 软链接目标及填充 | 1,080 字节 |
| 恢复后完整重打包增长 | 0 字节 |
| 零尾扫描可节省 | 464 字节 |

全部节点从 root 可达。未发现重复物理块、目录内重名、inode 内重复 xattr、链接计数不一致或目录环。以上结果覆盖已提交检查点；容量失败后尚未写入的节点与变化仍需运行态统计。

`RW_AIR_CACHE_DIR` 对应的 `/private/var/db/annibale-aircache` 是占用最多的子树。

| AIR 缓存子树项目 | 结果 |
|---|---|
| 常规文件 | 94,039 个，其中 93,965 个名称为 64 位十六进制键加 `.air` |
| 文件总长度 | 694,519,248 字节；p50 为 6,848 字节，p90 为 9,488 字节，p99 为 19,056 字节，最大为 30,752 字节 |
| 元数据总量 | 22,565,944 字节，占最新 payload 的约 67.26% |
| inode／目录项／块表 | 13,541,760／8,271,880／752,304 字节 |
| xattr | 0 字节 |

该统计包含缓存目录自身的 144 字节 inode，父目录中的 40 字节目录项另计。其余 74 个文件均使用 `.dat.nosync<hex>.<suffix>` 命名，总长度为 545,056 字节、元数据为 14,200 字节。只按字节减去这些记录，槽位余量也仅增加到 14,344 字节。

文件内容尚未采集，相同 AIR 的重复份数和缓存键的实际输入尚未确定。原始名称保存在本地忽略目录，以上分类未删除快照记录或设备文件。

三个冻结 writer 分别对两槽执行生产 C 的 unpack→pack，六次完整 payload 结果均与容量模型一致。逐 inode 的目录项、xattr 与块索引语义一致；hash 插入后的记录顺序发生变化，比较按记录语义进行。复算结果位于本地 `out/codex-1113-capacity-deep-review/real-checkpoint-c-roundtrip.json`。

后续本地容量分类工具复用 [`annfs-inspect.py`](../../hackios-xnu-kernel/tools/annfs-inspect.py) 的校验与槽位选择，新增统计的范围如下。

- 校验继续覆盖 CRC、版本、结构和范围，关系检查只输出结果。
- 容量统计覆盖分类字节数、内部／末尾零索引及恢复后重打包差异。
- 8 项宿主检查成功，覆盖 696 字节夹具分类、短表恢复增长、零尾节省、CRC 失败回退、重复名称与块引用、root 可达性及目录环。

运行态容量候选通过原生 `ffsctl` 和持有 vnode 的 `VNOP_IOCTL` 读取锁内完整统计；普通自定义 `ioctl` 不通过 XNU 的 VREG／VDIR 分派。候选的权限、错误返回、锁释放、容量边界与 arm64 对象检查已完成，实际设备读数待取得。现有格式记录都有生产消费者，尚未确认可删除的记录。

本地结果位于顶层 `out/codex-1113-ramfs-capacity-resume/device-prefix-analysis.json`；目录分类与运行态候选位于 `out/codex-1113-capacity-deep-review/`。原始锁记录和冻结核验位于内核仓 `out/codex-1113-fsync-result-analysis/`。原始目录名、xattr 和设备输入继续保存在忽略目录。

有界内容采集工具按最新有效槽的块表重建所选文件，保留内部空洞、原长度、名称与属性。采集范围由同一正常停止窗口的新元数据重新计算；历史块表与后续活动数据不能直接配套。

- 同一停止窗口先后读取完整 64 MiB 元数据，并核对分区身份、实际读取长度与源端／宿主 SHA-256；停止和数据写入结束状态由设备测试方记录，元数据相同仍不足以确认原块内容版本。
- 上限为 160 个文件、每文件 64 KiB 正文、4 MiB 数据范围；历史预览选中 74 个临时命名文件与 64 个 `.air`，正文为 1,023,408 字节，扇区对齐后读取 1,318,912 字节。
- 相同长度和 SHA-256 的正文再次逐字节比较，结果只覆盖样本；旧键路径、属性、原生再生成条件和缓存命中来源继续分别核对。
- 44 项独立合成夹具检查成功，覆盖重建、内部空洞、摘要、截断与采集状态错误；真实 AIR 内容尚未取得。

采集脚本、运行态资料清单与核验位于 `out/perf-goal-1114-cache-recovery/`。原始内容由忽略目录保存，设备读取由唯一 device 成员执行。

### 2.3 容量失败状态与验证

[`ramfs_mount`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs.c) 的 `rm_meta_state` 替换原 dirty 布尔值，只保存一份同步状态。

| 状态 | 同步行为 | 重新尝试的条件 |
|---|---|---|
| `RAMFS_META_CLEAN` | 无变化直接成功；首次 `gen=0` 初始化在等待其他同步结束后执行 | 元数据或内容变化 |
| `RAMFS_META_DIRTY` | 持锁打包，成功后执行原双槽写入 | ENOMEM、UFS EIO 保持该状态；分配或 I/O 期间的变化也保留 |
| `RAMFS_META_SLOT_FULL` | 最大槽容量打包失败后保存该状态；无变化的后续请求直接返回 ENOSPC | `ramfs_disk_dirty_locked()` 接收到真实变化后转回 DIRTY |

共享映射写回、vclean 与退出同步仍按各自职责执行。SLOT_FULL 只省去没有变化的重复打包；容量不足继续阻止同步和卸载成功。卸载失败继续保留 mount、缓冲与 callout，vclean 的既有错误后回收边界见 §2.4。

验证执行生产函数，结果如下。

- 固定输入下，8 个线程共发起 200 次后续同步；旧实现新增 200 次 pack，候选新增 0 次。两者均返回 ENOSPC，均未执行 UFS 写入。
- 真实变化后重新打包；移除一个大 xattr 后提交成功。首次 `gen=0` 满槽、并发首次同步、ENOMEM 重试、分配／I/O 期间变化、callout 与卸载失败资源保留均已覆盖。
- recovery 在 ASan／UBSan 下成功；sync-errors、flush-all、page-lifetime 成功；pack 完成 31,890 次完整字节比较。七个消融变体均编译成功并触发相应断言。
- 独立 arm64 对象编译成功，与基线相比没有新增未定义符号。编译仍有既有 SDK 路径和类型警告。
- 完整生产基线链接逐字重现；候选只替换一个 `ramfs.o`，其余 1,166 个实际对象及库输入哈希一致。候选完整链接、UUID 处理与 strip 成功，最终为 20,569,392 字节，无未定义符号和新增链接诊断。

宿主结果验证失败语义和重复工作减少，设备锁等待与交互帧时仍需真机对照。验证清单位于 `out/codex-1113-sync-recurrence/production-review.json`，目标编译输入和对象位于内核仓 `out/performance-followup-1113/`，完整链接交付位于顶层 `out/codex-1113-s9-full-link/manifest.json`。

相机诊断载荷使用早期 `ramfs_disk_flush_all()` 遍历与 void 返回契约，以及每次原子写入 AIR 的版本。生产 S9 候选继承已提交的完整刷新修复，直接替换该载荷包含多个执行差异。

匹配相机基线的 S9 对照复用 `out/codex-1113-s9-camera-ab/` 中已验证的 RAMFS 对象与源码审核。STAGE1 和曝光基线的 RAMFS 对象均与旧纯 S9 基线逐字相同，旧 `flush_all` 和完整 writer 保持相同；该对照只验证未变化请求的重复打包。

| STAGE1／曝光装配检查 | 结果 |
|---|---|
| 基线复现 | 两个基线的 stripped／unstripped 内核及 handoff 均逐字复现各自冻结输入 |
| 链接差异 | 每个对照的 1,172 项实际链接输入仅替换 RAMFS；各自的 HFI 与 Camera 对象保持相同 |
| handoff 差异 | 只有 kernel 条目变化，其余条目字节相同 |
| 真机范围 | 启动、功能回归、同步耗时与交互帧时待设备成员验证 |

- STAGE1 装配清单位于 `out/codex-1113-s9-stage1-ab/manifest.json`。
- 曝光装配的 runner 清单位于 `out/codex-1113-s9-exposure-ab/manifest.json`，链接与 handoff 检查位于同目录的 `build-review.json` 和 `runner-preflight-review.json`。
- 执行与恢复安排分别保存在两个目录的 `device-plan.json`。相机或音频输入继续变化后，应先复现选定的新基线，再仅替换 RAMFS；已有 handoff 只适用于各自清单的冻结输入。

### 2.4 启动清理的变化与耗时

启动自检创建并删除 300 个文件，回收经 `vclean(DOCLOSE) → VNOP_FSYNC → ramfs_fsync` 逐项同步全卷。同步成功后的最新检查点排除已删除文件，随后释放块；同步失败后的回收和备用旧槽仍有待复现路径，见[系统契约 §3](2026-11-12-system-contracts.md#3-检查点与文件数据区)。

| 零尾诊断轮中的清理项 | 结果 |
|---|---|
| 文件及目录同步 | 300 个文件加 1 个目录，均返回 errno28 |
| 同步区间跨度 | 3.802700 秒 |
| 301 项同步耗时合计 | 3.792903 秒 |
| 单项 p50 | 11.444 ms |

每次删除均产生真实变化并使 SLOT_FULL 失效，这部分仍需重新打包。以上耗时包含锁等待、打包、调度与诊断配置的影响；输出开销尚未分离。复算记录位于 `out/codex-1113-capacity-deep-review/init-cleanup-review.json`。

### 2.5 满槽变化后的容量预检

私有候选在现有单一状态中新增 `RAMFS_META_SLOT_FULL_CHANGED`，保留最近满槽后收到 dirty 通知的状态。

- 连续 dirty 通知继续保留 SLOT_FULL_CHANGED，普通 DIRTY 同步保持一次 writer。
- 仅 `SLOT_FULL_CHANGED` 先计算当前容量；容量仍超限后直接返回 ENOSPC，状态恢复为 SLOT_FULL。
- 容量计算和序列化共用 `ramfs_disk_pack_locked()`，预检与 writer 在同一次 `rm_lock` 持有期间执行。
- 容量已恢复后执行原 writer；pack 成功后将状态设为 CLEAN，再执行 CRC 与双槽提交。
- 提交期间的有效 dirty 通知及 EIO 将状态设为 DIRTY，后续请求按普通 DIRTY 处理。
- dirty 通知范围沿用生产实现，包含既有 seed 完成请求。候选没有增加变化检测或另一份容量状态。

持锁宿主计时覆盖 dirty 与 sync 前缀，截止于 pack 完成。每类保存 18 对记录，以下采用逐对百分比变化的中位数。

| 路径 | 相对生产 S9 的耗时变化 |
|---|---|
| 普通成功 | −0.439%，小幅差异仅覆盖宿主样本 |
| 满槽变化后恢复成功 | +46.772%，增加一次容量遍历 |
| 变化后仍 ENOSPC | −56.597%，省去 writer 的复制工作 |

上述计时未覆盖 CRC、UFS、vnode／page flush、内核锁竞争或真实请求比例。启用前需取得变化后仍满槽和恢复成功的实际次数，并比较完整同步与交互耗时。

- 两份真实树各有 139,271 个节点，原 payload 距上限 144 字节；增加合法的 280 字节 root xattr 后超限 136 字节，移除后恢复成功。
- 31,890 次字节比较、241 项状态／故障检查、8 个真实固定槽位场景成功；9 项消融均由对应断言检出。
- 并发 dirty 与 payload EIO 场景返回 EIO，保留 DIRTY、旧检查点和失败卸载资源；故障清除后的重试与实际恢复读回成功。67 项显式断言在 ASan／UBSan 下通过，范围仅覆盖该 payload 暂停顺序。
- 仅两份源码变化，净增 26 行。arm64 对象没有新增未定义符号；普通 writer 的常量 `store` 判断经内联消除，`__text` 减少 272 字节。
- 独立审核完成 2,746 项只读核验。
- 两份私有 pack／recovery 测试适配净增 28 行，基线／候选对照和四组相关恢复检查成功；三项适配消融由对应断言检出。

完整内核装配及设备分段耗时仍待完成。

候选清单位于 `out/ramfs-slot-full-preflight-1114/manifest.json`，最终计时为同目录的 `locked-cost-profile/cost-checks/result.json`；独立审核位于 `out/ramfs-slot-full-preflight-independent-1114/review.json`。

并发 dirty 与 payload EIO 的范围位于 `out/ramfs-slot-full-preflight-eio-1114/review.json`。另外两个宿主并发场景共 146 项显式断言在 ASan／UBSan 下通过。

| 并发场景 | 已验证结果 | 故障与适用范围 |
|---|---|---|
| payload 完成后暂停 super，修改元数据并返回 EIO | 保留 DIRTY、旧检查点和失败卸载资源；清故障后提交并重新 mount 读回成功 | 失败 super 请求写入 0 字节 |
| 满槽恢复提交后重新 mount，在普通 DIRTY 扩容期间加入一个等待线程 | 首次 ENOMEM 保留 DIRTY、原缓冲和旧检查点；等待者完成扩容、提交及读回 | 一个额外线程实际进入 `msleep`，第二次扩容前清除分配故障 |

满槽后的 `SLOT_FULL_CHANGED` 已持有最大槽缓冲，容量恢复成功的 count＋writer 路径没有扩容分配。上表的扩容发生于重新 mount 取得较小合法缓冲后，验证普通 DIRTY 分配与等待契约。

场景、源码、编译命令与断言索引位于 `out/ramfs-slot-full-preflight-final-faults-1114/manifest.json` 和同目录的 `review.json`。部分 super 写入后的槽位选择、更多等待者及真实 UFS 行为仍待验证。

测试适配补丁与范围位于 `out/ramfs-slot-full-preflight-integration-1114/manifest.json`。两份测试的完整正文保留，本次只执行受适配影响的检查；生产集成需先应用匹配的 RAMFS 候选，再同步测试补丁。

## 3. G15：专化与缓存写入

### 3.1 缓存键与已有修复

两段旧长处理、堆栈与 ENOSPC 分布见[多媒体验证 §73](2026-11-11-multimedia-validation.md#73-启动与十秒停顿的性能分析)，本次不重复展开窗口数据。

内核 `2b3863b5` 已修改 [`annibalemetal_stitch.inc`](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_stitch.inc)，相同 AIR 内容保留现有文件；宿主与 arm64e 验证已完成，真机收益待测。当前入口仍先调用原生 `_MTLLibrary` 函数专化，再检查缓存文件内容，原生专化与其他编译等待继续存在。

缓存键依次按 `respondsToSelector` 选择 `installName`、`filePath` 或 `label`。已选属性值为空后，代码以 library 对象地址 `%p` 作为标识；`constantValues` 通过 `NSKeyedArchiver` 或 `description` 加入哈希。不同对象地址会生成不同文件键，实际检查点中的文件是否由这条路径重复生成仍需核对。

iOS 26 的公开 `MTLFunctionConstantValues` 分配入口创建 `MTLFunctionConstantValuesInternal`。内部类的 `description` 合并 `NSObject` 的 `<%s: %p>` 格式与常量字典，实例地址由 `self` 直接提供。归档失败分支据此加入实例地址。

macOS 27.0（26A428）的原生 Metal 最小复现验证了该分支，结果与 iOS 26 静态结论分别记录。

- 8 个同时存活、常量值相同的对象全部 `isEqual:`，原生 `hash` 只有一个值；现行缓存键与 `description` 各有 8 个不同值。
- 归档返回 nil，`encodeWithCoder:` 不响应，`classForKeyedArchiver` 保持内部类，replacement 返回原对象。
- 相同空集合与 `copy` 也产生不同键；同一对象修改常量值后键发生变化。

该实现会在相同常量值的新实例之间保存不同缓存文件，相同内容比较只复用同一键下的文件。设备上的实际调用分支与相同内容关联尚未取得，宿主和静态结果位于本地 `out/air-cache-key-semantics-1113/`。

`NSCache` 的 256 项限制只作用于进程内缓存，磁盘目录没有容量和生命周期回收。下一步核对 library 的稳定标识、常量值的原生序列化契约及相同内容关联；容量统计见 §2.2。

原生 `serializedConstantDataForFunction:dataSize:errorMessage:` 返回匹配函数常量的连续字节，记录包含索引、`MTLDataType` 和 packed 值；索引查找先于名称查找。调用需要真实函数反射信息，nil 函数只返回零计数。错误消息指针须有效，成功后释放返回缓冲的职责属于调用方。

同值按名称／索引设置、反向插入及同时存在同名索引值的宿主输入产生相同字节；值修改后字节与原生 32 字节摘要改变。原生常量的三分量向量采用 packed 长度，通用 `MTLDataTypeGetSize` 包含填充，数组 `data` getter 没有长度字段。稳定键原型使用基础函数的完整 `bitCodeHash`、名称与专化名称的 UTF-8 字节，以及原生 serializer 的准确长度。字段按长度区分，nil 与显式常量集合分别记录。

生产稳定键的 65 项宿主检查成功，使用原生 macOS Metal 函数与常量序列化；三分量向量的函数反射由本地夹具提供。

- 8 个相同值的新实例生成一个键；按名称／索引设置、反向插入及索引优先的输入等价。
- 常量值、基础函数内容或专化名称变化后，键发生变化；nil 函数与类型错误不生成键。
- Float3／Half3／Bool3／Long3 的序列化长度分别为 19／13／10／31 字节，包含 4 字节计数和 3 字节记录头；尾部填充变化不影响键，packed 值变化会改变键。
- 描述符 options、pipelineOptions、applyFunctionConstants、种类及 compilerFlags 高位分别参与区分；全零摘要、缺少必要 getter 和未核对的描述符输入不生成键。
- 8 个线程共计算 256 个键，原生序列化的同值结果一致。

原生 `newFunctionWithName:` 的 Archive／File／Data 与 Proxy 查找使用已有函数记录，所查函数工厂与公共反射路径未进入 CompilerService。File 首次读取反射可以同步调用 `fseek`／`fread`；Data 从已有字节区读取。键生成安排在原生专化调用之后，基础函数由调用方持有，32 字节摘要指针随该函数释放。

描述符的 `options`、`pipelineOptions` 和 `applyFunctionConstants`、完整 `compilerFlags`、原生性能统计 getter、内部构建标志及两个编译环境输入已纳入键。非空 `privateFunctions`／`binaryArchives`、任何非 nil `pluginData` 和未核对的描述符类不生成键；成功的原生返回继续保留。新键使用 `annibale-air-v2` 命名空间，旧文件的完整输入关联仍未知。

原生 fast-math 路径保留首次 `getenv` 指针；该设置需从 Metal 首次相关读取起保持不变。`MTL_DISABLE_MULTITHREADED_COMPILATION` 的所查路径每次读取环境，再按数值生成 request 字段；当前键保留环境字符串。项目的通用设置入口位于进程构造阶段，尚未找到构造完成后专门修改这两个变量的调用。运行期修改环境后的复用未验证。

[`test-air-cache-key.py`](../../hackios-xnu-kernel/tools/tests/test-air-cache-key.py) 另有 334 项调用路径、配置与兼容读取检查，使用生产 hooks、Foundation 缓存和原生描述符；saved IMP、函数与配置导出由夹具提供。65 项原生检查与上述 334 项均在 ASan／UBSan 下成功。

| 验证范围 | 结果 |
|---|---|
| 原生返回与辅助路径 | 两条 saved IMP 各调用一次，基础查找一次；native／base 相同对象、缓存命中、未缓存代理、直接基础返回及 Objective-C 异常的持有与释放通过 |
| 配置与失败返回 | 缺少配置导出、serializer 的 nil／error 返回、错误缓冲释放及 nil key 跳过 bitcode getter 通过；环境修改夹具仅验证摘要输入 |
| 旧缓存读取 | 两条 hook 的 v2 miss、nil key 和空文件均可读取旧 AIR；v2 优先、原生成功只写 v2、旧命中保持原身份、caller error 与持有数通过 |
| 并发调用 | 8 个线程共 160 次调用，返回、saved IMP 次数、基础查找次数和持有数通过 |
| 消融检查 | 13 个缺失输入、持有错误或重复调用变体，以及 4 个旧缓存兼容变体均编译成功，并由对应断言检出 |
| 目标构建 | 冻结生产基线与候选的 Metal dylib 完成 arm64e 编译、链接和签名；复用对应对象完成原生 MH_BUNDLE 链接与签名；没有新增警告，新增导入在 23G90 DSC 中找到 |

原生接口与独立审核位于本地 `out/air-cache-key-semantics-1113/`，生产检查和目标构建位于 `out/codex-1113-air-key-fix/`。原生 serializer 的 C 层分配失败与 iOS 运行态尚未覆盖。相机基线与生产库分别冻结，生产库直接替换相机对照会包含其他源码差异。

旧缓存命中向 render／link 消费者提供专化 AIR；未命中后的基础代理没有再保存原专化 AIR，所查消费者未读取保留的 `annibaleConstantValues`。全部旧 AIR 可再生成仍待实测，兼容路径按以下范围保留。

- 原生专化失败且 v2 缓存没有非空内容后，继续按原 helper 生成旧键并读取旧文件，包括 v2 不生成键的请求。
- 原生成功只写 v2，旧命中保持旧键身份，不转存 v2；旧文件缺少完整编译输入关联。
- 旧 helper 与冻结基线逐字一致，仅函数名变化；所查原生路径未发现修改 caller name、常量对象、描述符或 library 标识的操作。
- 旧键中的对象地址仍限制跨进程复用，全部旧文件继续保留；恢复选择见本地 `out/codex-1113-capacity-recovery-options/`。

最终生产源码 SHA-256 为 `79edacf0b72c54fdc8c70109a90165331e54c511fac9c06c32ef594af9c3558b`；399 项检查清单位于 `out/codex-1113-air-key-fix/final-production-checks/result.json`。最终 Metal dylib 的 arm64e 构建、导入、警告和基线复用核验位于同目录的 `metal-final-delivery-manifest.json`，bundle 的对象、Info.plist 与导入核验位于 `target-metal-bundle/manifest.json`。这些生产产物尚未上机。

### 3.2 当前长处理的观测边界

稳定输入轮记录了一条总长 9.609322 秒的 `tl: a`。本轮冻结注入库匹配实际载荷，24 MHz Mach 时间换算已核对；时间值按微秒解释。该记录缺少 PID 和 TID，邻近 SpringBoard 采样与提交支持进程归属推断，重叠的短记录仍无法分配进程。

| 区间内观测项 | 结果与边界 |
|---|---|
| WOKE→COMMIT／COMMIT→DONE | 9.609321 秒／1 微秒；两个观察器边界不能覆盖全部 CoreAnimation 工作 |
| SpringBoard `tl: t` 采样 | 35 条，采样年龄 33～1972 ms；31 条包含 `rw_library_new_function_with_descriptor`，10 条顶层为 `fsync` |
| 其他文件操作 | 包含 getattrlist、fstat、write、mkdir、open、unlink、close 与文件缓存读取 |
| 采样范围 | `stall_watch` 仅在年龄小于 2 秒时输出；后约 7.6 秒缺少栈采样，中间帧缺库名与偏移 |
| 界面切换 | 两次 Home 输入和 Camera 转后台在长区间之前；区间内没有新的 `tl: p` 输出 |
| 渲染提交 | 区间中已有实际渲染提交；末尾 SpringBoard commit258 的 completion total 为 57.827 ms |

现有栈无法区分原生 Metal 内部写入与 `rw_air_cache_store`，也无法由采样次数计算 `fsync` 的耗时占比。观察器安装行无条件打印；本轮实际产生了上述采样，其他进程的安装结果仍需分别确认。

最新尾部快照中有 169 条完整的 bluetoothd WAL `full_fsync` errno28，另有一条截断文本；计数仅适用于该快照。长区间内未找到对应错误，容量失败与这条长记录的因果关系尚未确定。复算和冻结来源位于本地 `out/perf-current-run-1113/report.json`。

后续应按同一 PID、TID 和调用 ID 测量原生专化、缓存内容比较、fsync／rename 和 RenderServer 请求，并取得超过 2 秒的有界采样。已有缓存文件复用修复先做匹配输入对照。现有资料尚不足以选择增加编译线程或提交批处理，缓存验证记录位于内核仓本地 `out/codex-1113-startup-perf/`。

纯观察候选的 baseline 与 disabled 三库逐字复现实际相机 root，原键与每次 `NSDataWritingAtomic` 保持相同。当前开机版清单与采集契约位于 `out/g15-stage-1113-camera-late-window/`，恢复使用该清单记录的三份实际基线库。

- 窗口为 Mach 绝对微秒 `[1000000000,7200000000)`，SpringBoard 主线程每个进程最多采样 256 次。时钟不按进程启动或库载入重置；采集前核对日志的 `at`，预算耗尽后限定覆盖范围。
- 安装成功判据为 G15 hooks `1/1`、SB26 watcher 创建结果 `0` 与 observer `1`、SBMetal observers `1/1/1`；三库安装记录与实际采样需按 PID、主线程 TID 和载入库核对。库文件哈希与进程实际载入分别确认。
- 原生专化与整个项目 store 分别计时，后者保留一次原子写入。read／compare 字段为零，flag 16 未使用；key、bitcode getter、cache lookup 和基础函数查找仍有未计时区间，原子写内部 fsync／rename 尚未拆分。
- 同一调用记录包含旧键分支、常量归档分支及成功取得字节的内容 SHA-256，可统计不同键下的相同内容。嵌套区间包含子调用，耗时按区间关系计算。
- 栈采样在超过 2 秒后每 500 ms 执行，12 秒停止；应保留最长处理结束后至少 12 秒的日志。观察器与线程挂起会占用时间，宿主检查没有测得设备采样开销。

当前开机版只改变原候选的两个窗口宏；新 Metal 库及未变化的两份观察库均完成目标核对，新窗口的 21 项宿主检查成功。原 `[120000000,720000000)` 候选保存在 `out/g15-stage-1113-camera-baseline/`，读数按实际载入版解释。

### 3.3 实际驱动载入与观测覆盖

late-window 的 47 份日志已核对长度与 SHA-256。三份候选 dylib 在联合挂载路径的文件身份通过校验，SpringBoard 新进程的实际调用还使用单独打包的 `AnnibaleMetal.bundle`，该 bundle 未包含 G15 观测代码。

| 对象与覆盖项 | 核查结果 |
|---|---|
| SB26 候选 | PID858 的 loaded UUID 为 `130b4e17-7bd6-3651-a0c9-a3fb580731ab`，与候选一致；watcher 创建和 observer 加入成功 |
| 实际 Metal bundle | 日志 UUID 为 `1978de94-43c6-380f-a5d9-42153b8e9370`；从本轮 root 提取的 bundle 字节匹配 pack 清单及 UUID |
| bundle 的输出函数 | `rw_print` 与 `rw_image_uuid` 均为本地符号；UUID 来自该函数所在映像的 LC_UUID |
| G15／SBMetal 安装与调用 | installed 行与 native／store 阶段记录均为 0，未取得分段耗时或内容重复率 |
| 固定动作与界面 | 控制中心动作 0 次，桌面没有出现；SpringBoard 仍有原生 UI 启动及 Metal pipeline／command-buffer 活动 |
| 恢复 | 正常停止后原三库 SHA／UUID 复核成功，loader 的 product、result 与常驻区校验通过 |

候选文件可见性和实际观测执行需要分别校验。后续合并探针需覆盖原生 `MetalPluginName`／`MetalPluginClassName` 选择的 bundle 与 `_MTLLibrary` hooks，并确认安装、实际调用和固定动作都有记录。当前资料没有匹配的主线程等待栈，启动阻塞函数仍待定位。

原始窗口及函数来源核验位于 `out/g15-stage-1113-camera-late-window/runtime-analysis/`，恢复核验位于 `out/codex-1113-iris-finish-native/stage1/device-runtime/`。

### 3.4 STAGE1：cilicili 返回桌面的等待

21:59:33 附近的连续显示提交间隔在 backboardd 交给显示驱动前已形成。SpringBoard 主线程同期出现 Metal 函数专化、文件操作和同步采样，各阶段耗时仍待分开测量。

本小节与 §3.5 使用同次 STAGE1 开机的日志。16 份窗口快照与 `cmd-5.log` 已核对长度和 SHA-256，原始输入保存在 `out/codex-1113-iris-finish-native/stage1/device-runtime/preserved-console/`。

| 输入身份 | 已核对的值 |
|---|---|
| kernel SHA-256 | `07cea6462675b2d9d76ce80ce3c6ba0aec500767e9c3beec9623792da70fcbcd` |
| root SHA-256 | `8029b3ba238ded0ae4f059876f75318eb3beb2c7bf65549d099224ce14bc0dae` |
| 实际 Metal bundle SHA-256 | `5cee1b4e353ea166bbca4c72e83eaae17c80729e8c394bcf332e40810d5902de` |
| 进程 | SpringBoard PID31；backboardd PID39 |
| 图标窗口快照 | `s045.log`～`s052.log`，保存时间 21:54:52.860～21:55:27.722 |
| 返回桌面窗口快照 | `s097.log`～`s104.log`，保存时间 21:59:13.239～21:59:48.188 |

保存时间只描述宿主取得快照的时刻。第一窗没有 wall／host 配对，墙钟从同次开机第二窗的 21 组配对外推。配对显示值相差 1 ms，第一窗邻近日志与外推值约差 0.1 秒；绝对时间精度尚未测量。

界面布局记录在 21:59:24.572 包含 home-screen 与 `cc.bili`，21:59:28.299 仅保留 home-screen。21:59:34.007 的原生媒体记录向已在后台暂停的 `cc.bili` PID259 发出 stop。

| 长处理的近似墙钟区间 | `tl: a` 时长 | 同一日志片段的 SpringBoard 主线程采样 |
|---|---|---|
| 21:59:25.157～21:59:28.322 | 3.165697 秒 | 35 条；31 条含 `rw_library_new_function_with_descriptor`，10 条首 PC 为 `fsync` |
| 21:59:28.323～21:59:29.607 | 1.284889 秒 | 23 条；首 PC 均为 `mach_msg2_trap`，请求目标未知 |
| 21:59:29.607～21:59:33.705 | 4.097605 秒 | 36 条；34 条含 `rw_library_new_function_with_descriptor`，5 条首 PC 为 `fsync` |

最后一段 `tl: a` 为 `678857489 → 682955094` 微秒，其中第一个 commit 观察点前为 4.097564 秒，两个 commit 观察点相隔 41 微秒。该原始行缺少 PID／TID，采样计数按明确的日志片段归类；并发或缓冲输出的绝对归属仍有边界。

| 连续显示记录 | 结果 |
|---|---|
| 提交身份 | backboardd PID39／TID472，swap10206 → swap10207 |
| 交给驱动的时刻 | `678865387 → 683006236` 微秒，相隔 4.140849 秒 |
| present → ready | 两端分别为 2,034／2,502 微秒 |
| ready 间隔 | 4.141317 秒，近似为 21:59:29.617～21:59:33.759 |

最后一段日志片段有 34 条 SpringBoard pipeline 后段计时，合计 4,949 微秒，最大 2,499 微秒。该计时从前序 bitcode 提取、原生专化和 AIR store 之后开始，记录之和也包含可能重叠的调用。

同片段有 12 条 bluetoothd SQLite `full_fsync` ENOSPC。这些错误与该段等待的因果关系尚未确认。

两个操作窗口中的 36 条首 PC 为 `fsync` 的采样，均在 descriptor hook 前保留三个隐藏帧。这批采样优先归入项目 AIR 原子 store；实际 bundle 已将 store 内联到 hook，Foundation 原子写入路径与该栈形状相符。采样器只记录 PC 和 FP 链，`fsync` 的 svc／正常返回段省略直接调用方；错误处理段另有栈帧，原日志缺少 PC 偏移和隐藏地址。

已核对的 Metal archiveUsage 数据库同步路径在同一采样规则下至少保留五个中间帧。该比较只覆盖所查调用链，各阶段耗时及长区间后半段仍需运行态核对。地址、实际 bundle 调用位置与来源 SHA 位于 `out/perf-goal-1114-native-specialization/two-window-fsync-conclusion.json`。

私有地址采样候选复用同一次 thread state 和 FP 遍历。

- 保存 PC、LR、前四个 FP 返回地址及实际帧数。
- 每次成功挂起至多追加一条 `tl: r`，正文加换行最多 227 字节，经一次 `kern.annibale.say` 输出。
- 新增地址字段相对于启用 `RW_G15_STAGE=1` 的冻结采样器，保持挂起、状态读取次数和采样条件。

- 地址行与符号行按 PID、TID、turn、at 和 age 关联，缺失与冲突分别保留。
- `at` 沿用挂起请求前的时刻，实际状态取得稍晚。
- 真机 LR 认证、输出耗时与限流丢弃仍待验证。
- 默认及显式禁用版逐字复现冻结对象与旧观测库。

契约和目标核验位于 `out/perf-goal-1114-native-specialization/sampler-address-candidate/manifest.json`。

后续解析选用 `out/stall-address-parser-1114-v2/parse-stall-addresses.py`。

- 有效 raw 地址在符号内容缺失、冲突和状态矛盾中继续保留。
- `paired=true` 要求一份有效 raw 地址版本、一份一致符号版本，并符合符号内容与 `n` 的一致性条件；该字段只描述显式字段关联。
- `symbolic_content_complete` 保持未知。
- 修订版的 254 项宿主检查和 55 项独立检查成功。
- 原 sampler 清单及其中的旧解析器继续封存。

修订审核位于 `out/stall-address-parser-v2-independent-1114/review.json`。

两个采样观察器的起点分别核对，旧 watcher 只覆盖处理前约 2 秒。采样次数只说明观察到的函数，耗时占比待取得逐请求的 native、bitcode getter、store 与同步起止后计算。

结构化结果位于 `out/codex-1113-iris-finish-native/stage1/runtime-analysis/cilicili-return-home-stall-review.json`。同目录的 `event-report-verification.json` 核对 17 份输入、716 处原文位置和区间计算，`native-clock-domain-review.json` 保存时钟函数与墙钟换算来源。

### 3.5 STAGE1：图标透明与恢复后的卡顿

用户报告解锁后图标持续透明，横向翻页正常，21:55:08 底部上滑触发缩放后图标全部出现并短暂卡顿。现有日志确认该附近存在连续显示间隔和 SpringBoard 主线程等待，图标恢复原因仍缺少运行态状态。

| 图标窗口中的观测项 | 结果与边界 |
|---|---|
| 最长 `tl: a` | `415566690 → 421742013` 微秒，共 6.175323 秒，近似为 21:55:06.317～21:55:12.492 |
| commit 观察点 | 第一个观察点前为 6.175119 秒，两个观察点相隔 204 微秒 |
| 主线程采样 | 同片段 35 条，30 条含 `rw_library_new_function_with_descriptor`，9 条首 PC 为 `fsync`；年龄为 40～1,984 ms |
| 连续 ready 间隔 | swap1069 → 1070 为 2.821070 秒；swap1071 → 1072 为 3.406359 秒 |
| SpringBoard pipeline 后段 | 同片段 32 条，合计 114,731 微秒，最大 12,326 微秒；计时范围见 §3.4 |

该 6.175323 秒的 `tl: a` 原始行也缺少 PID／TID，SpringBoard 主线程采样按该日志片段记录。该区间跨越多个显示阶段，用户报告的短暂卡顿与整个观察器区间尚未逐帧对应。

第一窗包含底部上滑和横向触摸，用户时刻缺少对应触摸标识；触发恢复的具体输入待状态快照确认。更早的 6.306076 秒 ready 间隔在约 21:54:59.892 结束，单独保留在本地报告。

iOS 26.6.2 的原生调用流已核对以下更新条件。

| 原生状态或路径 | 已确认行为 |
|---|---|
| `SBIconImageView.updateImageAnimated:` | `contentVisibility == 2` 后设置 delayed 标志并返回；离开 2 且 delayed 为真后清标志并再次更新 |
| `canUpdateImage` | 两个图像／布局动画标志均为假，且 `_imageUpdateDisableAssertions.count == 0` 后允许更新 |
| 动画和断言结束 | 两类动画完成回调清标志并调用原生更新；最后一个禁用更新断言失效也调用更新 |
| `iconManagerContentVisibility` | `iconOcclusionReasons & 0x12` 非零返回 2 |
| 锁屏初始化与解除 | 初始化按 coverSheet 的 `isVisibleAndNotDisappearing` 设置 `0x10`；main-display scene 收到 `SBLockScreenUIWillDismissNotification` 后清该位并重算 |
| WillDismiss 转发 | CoverSheet 准备消失前的 `_appearState == 2` 才请求转发，通知经过原生事件队列 |
| 布局 publisher | SpringBoard elements 中的 `com.apple.lock-screen`／`com.apple.InCallService` 分别形成 `0x10`／`0x20`，main queue 更新 `(old & ~0x30) | mask` 后重算 |

`SBLockScreenManagerUnlockAnimationDidFinish` 的已查回调自身未清除 `0x10`。现场还需读取遮挡位、可见性、动画标志和断言数，才能确定哪项条件延迟更新。

| STAGE1 自动解锁的核对项 | 结果与边界 |
|---|---|
| 原生入口 | 23G90 的 `unlockUIFromSource:withOptions:` 编码为 `B28@0:8i16@20`，返回 BOOL，source 为 int32_t |
| 实际 SB26 调用指令 | W2 写入 24，X3 写入 nil；已查 hook 保留原 IMP 调用和 BOOL 返回值 |
| 启动触发条件 | `unlock_once` 在 `isUILocked == 1` 后请求解锁；其返回 1 只记录已请求，现场原生 answer 尚未取得 |
| 尚缺的运行态状态 | 准备消失前的 appearance、通知收到顺序和事件队列状态；System／Cryptex 的实际 SpringBoard 主映像 UUID 尚未捕获 |

调用指令、原生 ABI 与启动来源核对位于 `out/icon-occlusion-root-1114/stage1-unlock-audit/stage1-unlock-audit.json`。已查 shim 通过上述原生入口请求 CoverSheet 消失，图标恢复原因仍需同一 PID 的通知和状态读数。

`ICRIconLayer` 保存继承 `RBLayer` 的实际渲染子层，`displayIcon:` 与 `layoutSublayers` 向该子层复制显示数据并设置 `setNeedsDisplay`。判定内容需查看该子层的输出与屏幕像素，父 CALayer 的 `contents` 可为 nil。旧 SB26 的 `icons_ready` 仅按 `displayName` 计数，未检查这两项。

| 原生渲染条件 | 已确认行为 |
|---|---|
| `ICRIconRenderingLayer.drawInDisplayList:` | 读取 `finalizedIcon`；空值直接返回，未加入图标绘制 |
| `RBLayer` 可见与后台状态 | 不可见或后台状态为 true 后延后绘制；可见、待重绘且前台的路径请求同步更新 |
| `RBLayer` 显示列表与队列 | 显示列表在派发 RenderBox 队列前生成 |
| QuartzCore 可见性传播 | context ID 和父层可见位决定内部 layer 的 bit 28；`RBLayer` 与 `ICRIconRenderingLayer` 继承的 `_defersDidBecomeVisiblePostCommit` 返回 false，已查路径直接执行可见回调 |
| RenderBox 输出 | scheduled 回调将 surface 送入 CAImageQueue；completed 回调处理命令错误和资源收尾 |

`RBDevice` 初始化的备用分支通过 `proc_pidoriginatorinfo` 读取 originator 后台状态，前台通知清除其后台标志。23G90 wrapper 和 STAGE1 链接内核的返回契约相符；实际初始化分支、后台值和通知收到时刻仍缺少运行态记录。

上述调用流与 198 个反汇编范围的来源核对位于 `out/icon-stall-stage1-1113/icon-renderbox-final-static-summary.json`，内核返回契约核对位于 `stage1-originator-bg-contract.json`。两个现场未找到 RenderBox 原生前后台或渲染失败记录，该输出的实际覆盖范围仍需确认。

渲染子层的 finalized 内容、visible／pending 位、后台值与 surface 入队时刻仍待采集。下述状态候选覆盖 SpringBoard 的更新条件及已有 content view 的 type／generation，屏幕像素另由截图核对。

只读状态候选的读取范围和目标构建已完成核对，清单位于 `out/icon-stall-stage1-1113/probe/manifest.json`。

- 显式 `com.annibale.icons.state` 请求在 main queue 有界遍历，最多 8 次请求、1,024 个尝试节点、32 个图标和 64 层深度；输出原生状态、对象身份、type／generation 及各自 availability。
- 锁屏的两种原生通知由独立 observer 接收，记录接收时刻、TID 与 main 标志，再排入 main queue 读取已有对象。私有 getter 校验 23G90 的 IMP 与 ABI；coverSheet 仅读取已创建对象。
- 原始基线与禁用版对象／签名库逐字一致；启用版完成 arm64e 编译、链接与严格签名核验，13 项新增导入在 23G90 DSC 中找到。
- 候选复用已核对的长处理采样：2 秒后每 500 ms 采样，12 秒停止。快照自身的 start／end 需单独计时，运行态安装、getter availability、通知次序与观测开销待测。

原生 getter 和调用流来源位于 `out/icon-stall-stage1-1113/icon-readonly-getter-contract.json`，最终源码复核位于 `probe-static-review.json`。现场结果位于 STAGE1 `runtime-analysis/desktop-bottom-swipe-stall-review.json`；候选已装入 §3.6 的观测 root，运行态待验证。

私有 v2 在同一 main queue 回调中增加 `isAppGestureActive` 和已有 delegate → context → provider → layoutState 的读取，跳过会检查断言的 scene 包装方法。`unlockedEnvironmentMode` 的原生值为 0 undefined、1 home-screen、2 app-switcher、3 application；缺对象、getter 不可用和返回 nil 分别记录。mode 3、手势未活动与遮挡位 `0x2` 对应所查应用隐藏路径，锁屏位 `0x10` 还需结合通知和后续布局更新判断。

v2 的 31 个宿主分支、arm64e 构建与严格签名检查成功；disabled 与实际基线逐字一致，相对旧 enabled 没有新增导入，旧候选的 98 份文件 SHA 保持不变。交付和读取边界位于 `out/icon-stall-stage1-1113/probe-layout-state-v2/handoff.json` 与 `collection-contract.json`。准备消失入口的瞬时 appearance、事件队列状态、首次可见像素及设备观测开销仍待采集，v2 尚未装入 root。

宿主图标解析器使用一个已确认顺序的日志流，保留原始片段和行号，分别检查字段／分片完整性与快照首尾、图标数量和对象关联。availability、nil 和原生 -1 分开保存；同 PID 插入日志、缺片、截断或缺少结束片均保留不完整或歧义结果。

解析器的 164 项分片与状态检查、4 项 CLI 检查成功，正文来自保留原 31 项断言的私有 formatter 夹具。完整记录仍需实际加载身份和采集来源；顺序恢复、整次请求缺失及多次对象读取之间的状态变化另行核对。来源与检查位于 `out/icon-state-parser-1114/manifest.json`。

### 3.6 合并观测的装配与计时边界

已封存的完整观测 root 复现曝光基线并完成装配，用于同轮读取图标状态和 G15 分段。该候选保留诊断基线的旧缓存键、原生调用次数与每次原子写入；S9 和生产稳定键修复分别验证。

后续私有 SB26 已合并图标 v2 与上述地址采样。

- 禁用库逐字复现实际 STAGE1 基线。
- 仅 v2 的库逐字复现封存 v2。
- 合并版只替换 rate 对象，导入、部署目标和依赖保持 v2 的值。
- 严格签名检查成功。

实际链接输入与库身份位于 `out/g15-icon-address-1114/manifest.json`。

该合并库使用冻结的 STAGE1 链接输入，尚未装入新 root。测试方选定新的相机／音频基线后，先复现其输入，再装配 compact G15、图标和地址观测，并建立同一观测 root 的纯 S9 对照。

合并采集契约位于 `out/perf-collection-contract-1114/collection-contract-v2.json`，明确四份冻结库、三份解析器及各自原契约的来源。

- 地址 parser 的路径及关联判据按修订版执行，采样和计时范围继续按原契约核对。
- 单次新增地址字段的比较范围见 §3.4。
- 合并库相对于实际 STAGE1 的采样窗口由 2 秒扩展到 12 秒，2 秒后间隔为 500 ms。
- 合并采样与输出的总开销仍待设备验证。
- 图标 parser 按 LF 保留行号及原始 NUL 字节，NUL 进入记录完整性判断；输入顺序由采集来源确认。
- G15 parser 保存 installed／budgets／cap；安装身份、配额和 cap 一致性由后续分析核对，`record_set_complete` 只覆盖该解析器的记录判据。NUL 删除和续片处理需核对原始字节。
- 新 root 保留选定基线中的 drawable、相机和音频变化，再重新核对实际链接输入及安装身份。

| 装配检查 | 结果与范围 |
|---|---|
| 曝光基线复现 | root 与 handoff 逐字复现冻结输入 |
| root 内容 | 720 个路径无增删，仅替换 Metal bundle、Metal dylib、SB26 与 SBMetal 四份库；对应压缩 xattr 随文件内容变化，其余文件与元数据一致 |
| handoff 内容 | 只有 ramdisk 条目变化；内核、常驻区和启动参数保持曝光基线 |
| 签名范围 | 独立 Mach-O 的严格签名检查通过；组装的 bundle 路径下，基线和候选均缺少资源封套，原资源布局与签名保留，原生加载待验证 |
| 交付来源 | runner、四份替换库及其私有源码按清单记录；装配清单位于 `out/codex-1113-g15-icon-observation/manifest.json`，检查位于同目录的 `build-review.json` |

G15 的 renderer bundle 和 dylib 均包含观测代码，只采集 SpringBoard 主线程；运行态需分别确认两个映像的安装与实际调用。时间起点沿用开机 Mach 时钟，每个映像的三个预算分别计数。

| Mach 绝对微秒区间 | 每个映像的调用上限 |
|---|---|
| `[0,120000000)` | 64 次 |
| `[120000000,600000000)` | 128 次 |
| `[600000000,900000000)` | 128 次 |

- 新记录按同一轮次、PID、映像 UUID 与调用 ID 归类，TLS parent 只关联同一映像的嵌套调用。旧解析器先过滤 `tl: g x` 行以满足固定语法；legacy b／e／h 字段缺少映像 UUID，跨映像计量使用 x 记录解析器。
- 各阶段使用 e 记录中的起止值，分别计时原生专化、一次既有 bitcode getter 和原 store；原子写入的起止位于 store 内部，fsync 与 rename 仍未单独计时。
- 完整输出根据 begin／end、写入 flag 4 和摘要 origin 1 确认 getter／store 的预期记录；缺少这些进入标记的可选阶段仍可能全部丢失。精简输出在 result 中附带 `phases` 位图，分别用 1／2／4 标记原生专化、getter 和 store 已进入，解析器据此检查预期 end，并核对写入标志、摘要来源及原生返回。
- 字节摘要读取原生返回或原缓存读取路径已有的 NSData，可统计不同键下的相同返回内容；磁盘文件的完整内容关联仍需独立核对。
- 下一轮分别确认两个映像的安装、各窗口的预算、已捕获数量、`cap` 和不完整记录，图标状态、用户动作和显示 swap ID 使用同一时间域关联。

日志输出在调用线程上同步锁定 FILE、写入并 flush，实际等待取决于输出路径。

- 最终使用 say stream 的非空未过滤行或 255 字节片段会调用 sysctl，再请求 `usleep(5000)`。
- 直接输出到普通 stdout 的路径没有上述等待；构造阶段继承的转发流按最终 callback 判断，映像之间的转发需读取实际输出路径。
- 完整模式的正常有效 store 样本最多输出 12 条 G15 记录；12 条各使用单一 say 片段后，请求等待合计 60 ms。实际开销还包含 sysctl、锁、调度及其他日志。

- 阶段的 begin 日志位于对应测量起点之前；嵌套 hook 的输出仍计入外层 native。
- `log_us` 只累计当前样本的部分打印；native 异常的结束记录在保存 `done` 后打印并继续增加 `log_us`。`total−log_us` 仍包含嵌套观察、字节摘要计算和其他未分段工作，无法给出扣除观测后的耗时。
- 设备上的输出与线程采样开销待测，S9 对照需要选择相同观测 root 并核对两轮采集量。

G15 的窗口、输出与计时契约位于 `out/g15-stage-1113-stage1-bundle-observation/collection-contract.json`，输出与解析审核位于 `out/g15-stage-1113-stage1-bundle-independent-review/output-parser-final-review.json`。合并装配的独立审核位于 `out/codex-1113-g15-icon-observation/independent-review/review.json`。

私有精简版保留旧缓存键、原生调用顺序与原子写入，正常有效 store 样本输出 7 条 G15 记录。每条使用单一 say 片段后，请求等待合计 35 ms；转发前缀可能增加片段数。

- identity 和 native begin 继续在原生调用前输出；getter／store begin 仅读时钟，三个阶段的 end 在 wrapper 收尾后统一输出，保留各阶段边界处的 flags。
- `pre_summary_us` 位于延后报告之前；嵌套 hook 输出仍可能计入外层 native，字节摘要与全部报告开销仍需单独解释。
- 宿主契约、并发与 TLS、独立配额、原生／getter 异常和受控计时检查成功；19 项记录缺失、截断、冲突、计时错误及阶段位图矛盾的输入由解析器检出。
- arm64e dylib 与 MH_BUNDLE 均构建并通过独立签名检查；默认完整模式和禁用模式的对象及签名库与冻结版本逐字一致，精简版导入集合保持一致。

精简版清单、采集契约与解析器位于 `out/g15-1114-compact-observation/`。原 STAGE1 链接对象的 say handler 已核对：每秒最多输出 200 行，超量计数并返回成功，下一时间窗输出丢弃数量。对应对象、反汇编和源码来源位于该目录的 `console-source-review.json`。

冻结的 `rw_print`、say 和转发回调已通过 73 项宿主检查，覆盖 16 个输出与分片场景；格式串来自实际 compact 对象。宽字段夹具限制 identity 的 ID／parent 不超过 320、identity start 小于 900 秒，其余字段按类型宽度检查。该夹具测量格式容量和请求等待，设备上的输出选择、锁等待、sysctl 和调度耗时仍待测量。

| 夹具输出路径 | 七条记录的 say 片段数 | 请求等待 |
|---|---|---|
| 直接 say | 7 | 35 ms |
| 继承一层转发前缀后进入 say | 10 | 50 ms |
| 普通 stdout，包括继承转发 | 0 | 0 ms |

结果与边界输入位于 `console-host-results.json`。单片段上限为 255 个非换行字节；续片缺少调用身份，解析器逐行检查记录完整性。后续对照需核对两侧实际片段、丢弃数量及不完整记录，普通 stdout 的 flush 等待也需保留。

完整观测 root 继续封存。精简库尚未装入设备候选，后续装配需使用设备测试方选定的相机／音频基线，并重新核对库来源、root 差异及实际采集量。

固定动作、图标状态和性能收益由设备窗口验证，安排见[系统后续事项 §5](../plan/2026-11-12-system-followup.md#5-性能分析与验证安排)。

### 3.7 AIR 大目录查找与名称缓存

两槽的 AIR 目录恢复顺序逐条一致。当前 [`ramfs_dir_find()`](../../hackios-xnu-kernel/xnu/files/bsd/miscfs/ramfs/ramfs.c) 按 TAILQ 线性查找，目录组成见 §2.2。

- 68 字节未命中访问全部 94,039 个条目，执行 93,965 次 `memcmp`。
- 预热宿主中位为 149～153 µs。该计时仅覆盖热内存遍历，设备累计耗时待测。

| 普通同目录成功分支 | AIR 叶子查找次数 |
|---|---|
| 旧 Atomic store | 8 次 |
| 当前 store，内容相同 | 1 次 |
| 当前 store，继续 Atomic 写入 | 9 次 |

这组计数排除重试和错误分支。

- 已查 Foundation 的 `options=1` 进入临时文件与替换流程。
- 成功 close 位于 rename 之后。
- 实际 NSData 动态 IMP 仍需现场核对。

当前 vnode 使用 `VNFS_NOCACHE | VNFS_CANTCACHE`。通用 VFS 已为 unlink 和独立被覆盖目标执行 purge；正项缓存启用前还需确认以下条件。

- 同父 rename 的源正项失效，以及跨父 rename 的旧父 generation 更新。
- swap 两侧名称和两份旧父 generation 的处理。
- hardlink 别名的查询名称、父目录、hash 与 vnode 身份关系。
- `vnode_create` 与 `rn_vp`／`rn_vid` 写回的名称缓存发布顺序。

- 普通 rename syscall 的同 vnode 分支会提前返回。
- 直接调用 `ramfs_rename_common` 的同节点 no-op 成功分支仍更新身份。
- SWAP 的同节点成功分支保持 `changed=false`，身份更新条件未满足。

上述并发条件由源码推演，实际 XNU 并发与别名行为待验。

下一步保持现有 flags，按同 PID／TID 记录各操作的查找次数、访问条目数、累计耗时及锁等待，再与 G15 store 区间关联。

- 独立审核完成 142 项复算。
- 26 份 ASM 的 19,240 条指令与实际 DSC 字节逐条一致。

分析和审核分别位于 `out/air-directory-lookup-1114/review.json` 与 `out/air-directory-lookup-independent-1114/review.json`。

## 4. S7／G9：显示计时范围

cd37 manifest 中五份 framebuffer 源码与本次复核源码一致；该轮参数包括 `touch_lat=1 fb_threads=2 fb_flip=2 fb_beat=0 fb_hz=120 fb_ca_hz=120`。以下数据仅描述该诊断配置的启动窗口。

| 项目 | 结果与含义 |
|---|---|
| 完整 `tl: v` | 241 条 |
| `C=done−shown` | p50 7.947 ms、p90 9.177 ms、最大 19.986 ms |
| `tl: l` | 228 条；记录读取到 CTL_FLUSH 清零的时刻 |
| swap 379 | done 到 latch 观察相隔 18.555329 秒，真实完成时刻未知 |

[`MiniIOMobileFramebuffer.cpp`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp) 在取得 `fLock` 和执行 `flip_target()` 前记录复制起点。[`MiniFramebufferFlip.inc`](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferFlip.inc) 的 `flip_target()` 可等待上一帧 CTL_FLUSH，随后还有哈希、缩放与显示提交。上述 C 值描述整个区间，CPU 缩放耗时需单独采样。

上一帧的 CTL_FLUSH 状态在下一次 `show()` 才被读取，静置会延后观察。该 latch 时间无法给出物理面板扫描完成时刻。cd37 启动窗口有 `tl: Q`，没有 `tl: R` 或 `pass times`，提交到 surface-ready 的区间也包含派发、排队及完成检测。

阶段采样需要按同一 swap ID 区分取锁、flush 等待、哈希、缩放、提交和完成观察，并分别覆盖连续重绘与静置。物理面板完成与 surface 复用规则需另核对硬件完成条件。原始数据位于本地 cd37 轮的 `s021.log` 与 `s166.log`，旧窗口校验见 §1 引用。

私有 `MiniIOMobileFramebuffer.cpp` 候选在 `tl: V` 中按同一 swap ID 输出 lock／target／dirty／rows／submit 五段壁钟耗时，日志在解锁后执行。禁用路径的时钟调用数和设备操作顺序与基线一致，settle 默认不采样。

8 项宿主检查、4 个错误计时变体和既有 latch／frames 检查成功。候选与本地基线的 arm64 对象均编译成功，287 个未定义符号完全一致，435 项依赖已核对；两者各有 19 条相同警告、0 条错误。完整链接、打包、运行与计时开销仍待验证，候选及核验位于 `out/display-stage-1113/`。

## 5. P11：策略参数与观测边界

cd37 manifest 中 [`adreno8_hfi.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/adreno8/adreno8_hfi.c)、[`annibale_cpufreq.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_cpufreq.c) 和 `AnnibaleGPUSubmit.inc` 的哈希与本次复核源码一致。11-09 调频说明中的参数与该轮源码存在差异；该轮策略以下表和源码为准，旧温度实测保留其原验证范围。

| 项目 | cd37 实际源码 |
|---|---|
| GPU 负载 | 按 160 MHz 归一化，目标 35% |
| 升／降档条件 | 归一化负载 ≥20%／<10%，降档等待 500 ms |
| 触摸请求 | 请求 `adreno8_speed_asked`，触摸窗口默认 300 ms，实际下发受温控上限约束 |
| GPU MHz 日志 | 最近 HFI 成功应答后的请求档位，未回读实际工作时钟 |
| CPU 档位分布 | SCMI `LEVEL_SET` 成功后的软件状态驻留统计 |
| `hot ticks` | 有效温度达到 70°C 的采样周期数；配套 `hot_at` 统计相应时长 |

CPU 的温控上限可在温度下降后继续限制频率，`hot ticks` 没有覆盖全部限频时间。旧启动窗口存在短暂温控触发；十秒停顿邻近报告覆盖较长区间，缺少逐秒对应，现有数据不足以解释主线程长处理或确定功耗来源。

后续同时记录负载请求、温控上限、下发档位、应答与实际频率，并累计温控上限低于普通上限的时间。原生 CLPC 接入仍需核对调度回调、work interval 和驱动接口；本次未实施策略替换。24 MHz Mach 时间修复后的轮次需按各自产物解释。
