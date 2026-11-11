# 持久化、温度与应用管理核查（2026-11-12）

本批执行安排见[系统后续事项](../plan/2026-11-12-system-followup.md)，未完成事项按主题维护在[待办目录](../backlog/README.md)。

## 1. 范围与基线

本轮按[系统后续事项](../plan/2026-11-12-system-followup.md)处理 S1～S5。起始源码为内核 `a1c40aed`、用户态 `636e07a`。多媒体任务同期修改 Iris、VideoToolbox 和 AIR／YUV；两批分别审阅和提交，构建与真机使用另行协调。

## 2. 退出前全量刷新

`ramfs_disk_flush_all()` 在每个哈希桶只收集前 8 个可写映射 vnode，处理后直接进入下一桶。旧实现还忽略 `ubc_msync()` 和元数据提交的返回值。实际函数宿主测试已复现同桶 19 个文件只处理前 8 个的情况。

当前修复按 inode 游标遍历每个桶，以进入函数时的 `rm_next_ino` 为上界。释放挂载锁后只保留 vnode 与 vid，使用 `vnode_hold()`、`vnode_getwithvid()`、`vnode_drop()` 和 `vnode_put()` 管理引用；节点指针留在持锁范围内。XNU `bsd/sys/vnode.h` 的 hold 契约允许在阻止 reclaim 的文件系统哈希锁内取得引用。

`loader_return.c` 的正常定时退出和主机 stop 路径均在关闭 Wi-Fi、执行 `loader_return()` 前调用刷新；panic 路径跳过这项正常退出刷新。调用顺序保持原样。

- 保留首个失败，继续尝试其余文件；全部映射刷新成功后执行最终元数据提交。
- 映射刷新失败只跳过本次最终提交，周期元数据同步仍独立运行。
- UFS 退出包装函数记录错误及数据可能未保存的信息，再继续原停机流程。
- 固定 inode 上界保证同期持续新建文件不会无限延长本次遍历；同期写入的全局静默仍需单独分析。
- 挂载对象没有新增引用保护，与 `ramfs_disk_unmount()` 并发的安全性仍待处理；本次引用管理只覆盖 vnode。
- 逐项选择 inode 的最坏开销为单桶节点数的平方，未增加长期节点状态、动态引用列表或磁盘格式字段。

| 验证 | 结果 |
|---|---|
| `tools/tests/test-ramfs-flush-all.py` | 16 个实际函数场景通过：同桶 19 个文件、筛选、vnode 失效／回收、首错、元数据失败、回调插删、持续新建与退出日志 |
| 旧版对照 | `a1c40aed` 在同桶遗漏场景失败 |
| 消融 | 9 个删除必要条件或引用操作的变体均触发预期失败 |
| 既有检查 | `test-ramfs-disk-recovery.py`、`test-ramfs-sync-errors.py`、`test-ramfs-page-lifetime.py` 修改前后通过 |
| 真机 | 待映射写入、正常退出和重启读回验证 |

源码位于内核仓库的 `xnu/files/bsd/miscfs/ramfs/ramfs_disk.inc` 与 `xnu/files/bsd/dev/annibale/annibale_ufs.c`，测试位于同仓库 `tools/tests/`。

## 3. 检查点与文件数据区

双份元数据保存 inode、目录和数据块号，文件内容仍写入既有数据块。CRC 与坏槽回退校验元数据完整性，文件数据没有对应的历史版本。

宿主实验复用 `a1c40aed` 的元数据打包、提交、恢复、块分配及数据写入函数，在 1 GiB 模拟盘中包含实际的 512 MiB 数据区起点。每个场景先保存含文件 A 的 generation 1 检查点，随后改变数据区，在不提交新元数据的情况下重新挂载。实验使用 ASan／UBSan，三个场景均完成。

| 场景 | 恢复结果 | 结论边界 |
|---|---|---|
| 原位覆盖已保存文件的一页 | 元数据仍为 generation 1，16,384 字节均为新内容 | 回退元数据不能回退文件内容；普通未同步覆盖是否需要回滚，需先定义契约 |
| 释放旧块并重新分配后写入另一份内容 | 旧文件 A 的块号仍恢复，读出 16,384 字节的新内容 | 旧元数据可能引用已复用的数据块；实验直接调用分配／释放原语，尚未覆盖完整 unlink／create 调用序列 |
| 一页写入完成一半后返回 `EIO` | 元数据仍为 generation 1，旧内容与新内容各 8,192 字节 | 数据写入失败可能留下部分内容；实验未假设 16 KiB 原子写入 |

原始脚本、基线源码副本、生成的 C 程序和输出保存在 Git 忽略的 `docs/analysis/local/system-followup-1112/`。这些结果尚未验证真实 UFS 的掉电行为。

完整 VFS 路径还有一次回收前同步。`ramfs_remove()` 先减少链接数；最后一个引用释放后，XNU 的 `vnode_reclaim_internal()` 经 `vgone()`、`vclean(DOCLOSE)` 调用 `VNOP_FSYNC(MNT_WAIT)`，随后才执行 `VNOP_RECLAIM` 和块释放。`ramfs_fsync()` 提交全挂载元数据，打包会跳过链接数为零的 A，因此正常同步成功后的最新槽已排除 A。

静态核查保留两条待复现路径：回收前 fsync 返回错误，`vclean()` 仍继续回收；或同步成功后，最新槽校验失败而恢复仍含 A 的备用旧槽。分配器只检查当前位图，释放会直接清位；A 与分配游标位于同一 32 位字且没有更低空位时，B 的第一次分配即可复用 A 的块。完整实验需关闭 A 的描述符并解除映射、确认回收发生，再分别注入上述失败；其他 fsync 和延迟提交会改变复现条件。

下一步先覆盖完整 unlink／create 调用序列，再验证延后复用方案。本批保持磁盘格式不变，候选方案仍需实现和验证：

- 保留当前分配位图及两个有效元数据槽引用的块集合，三个集合均未占用的块才允许分配。
- 元数据 payload 固定后、释放锁执行写入前，先保护目标槽本次引用的集合；成功持久化后替换该槽集合，失败后保留新旧集合的并集，以覆盖部分写入。
- 重启后从两个有效槽重建保留集合，再用选中的槽恢复目录树；仅从选中槽重建分配位图仍可能复用另一槽引用的块。
- 8,388,608 个块对应的两个新增位图共 2 MiB，无需新增磁盘格式字段。可分配空间会暂时减少，持续提交失败可能积累保留块，容量统计需区分文件已用空间与当前可分配空间。

该方案只约束块复用。普通未同步覆盖的回滚要求、数据版本保存和 16 KiB 写入原子性仍需分别定义。

`F_FULLFSYNC`／`F_BARRIERFSYNC` 当前调用映射同步和元数据提交；native UFS `WRITE(10)` 未设置 FUA，命令白名单拒绝 `SYNCHRONIZE CACHE(10)`。设备写缓存配置和完成应答语义尚未确认，当前资料不足以判断写入应答后的掉电持久性。

上游 ShengUfs 的 FUA 与缓存刷新实现已核对，来源及差异见[上游对照 §3.3](2026-11-12-upstream-review.md#33-ufs-完成等待与缓存同步)。下一步以其命令编码、完成状态和失败传播为对照，核对本项目写缓存配置、允许的 LUN、完成顺序和设备响应。缓存刷新、原位覆盖与旧槽引用块复用分别验证。

## 4. 电池温度

BQ 的 `Temperature()` 返回 0.1 K，驱动转换为 0.01°C，经 `annibale_battery_state` 发布到 sysctl 与 IOKit。原实现将高于 35°C 的读数限制为 35°C，将负温替换为 25°C；两处备用采样分支还写入固定温度。

当前修复保留有效 BQ 温度，温度读取失败沿用已有采样失败语义，保留上次发布状态。备用电压、电流和容量数据只能与本次成功读取的 BQ 温度一起发布。整数摄氏度按正负对称方式取整，日志保留负的小数温度符号。

原生 iOS 26 `powerd` 在 `0x100031364` 以 `CFNumberGetValue(type=9)` 读取 `Temperature`，后续使用 2500、3500、4000 阈值，与 0.01°C 一致。IOKit 的 32 位整数表示和采样失败后的更新行为由专项测试核对。

手电既有保护使用电池温度大于 45°C 的条件；移除 35°C 截断后，这项条件可接收真实高温读数。CPU／GPU 的独立温控保持原行为，`thermalmonitord` 服务接入另行研究。

`test-battery-temperature.py` 编译实际采样、状态发布、IOKit 属性发布和手电温度保护函数，23 个场景通过；相同测试在 `a1c40aed` 上有 20 个场景失败。测试覆盖负温、高温、转换边界、读取中断、备用数据、充电控制、失败后恢复和旧值保留。macOS 的 `IOCFUnserialize` 与 `CFNumberGetValue` 验证 32 位负整数读取，内核 `OSNumber` 使用替身，设备上的属性读取仍待验证。

缺少温度会暂停整份电池状态发布，首次成功采样前保持未知状态。已有采样循环在失败后立即重试一次；持续缺温度且备用电压有效时，每 5 秒周期可能执行两次采样与充电控制。此次沿用该循环，未新增独立重试状态。

## 5. 应用卸载

iOS 26 的 `SBApplication.uninstall` 经 `SBApplicationController.uninstallApplication:`，转交 `_appLibrary` 的 `FBSApplicationLibrary uninstallApplication:withOptions:completion:`。应用库取得 application identity，再调用 `IXAppInstallCoordinator uninstallAppWithIdentity:options:completion:`。旧钩子先注销和删除目录，再调用原方法，改变了原生卸载前可见的注册与容器状态。

原生带选项入口为 `requestUninstallApplication:options:withCompletion:`，其中 options 为 `NSUInteger`。旧钩子查找的 `uninstallApplication:withOptions:completion:` 未出现在该类方法表中。

`SBApplication` 的可卸载判据为 `applicationInfo.uninstallCapability`；`SBApplicationIcon` 的 `isUninstallSupported` 继承自 `SBLeafIcon`，修改取得的继承方法会影响共享实现。本次删除 `inject_sb26_uninstall.inc` 的 430 行实现及主文件的 include、两处安装调用，保留原生卸载入口与资格判断。

TrollStore 默认注册为 System，并已设置 `IsDeletable`。`SBApplicationInfo._loadFromProxy:` 对 User 设置 capability 1；对 System 按 `isDeletable` 设置 2 或 0。capability 2 还会检查 `removabilityForAppWithIdentity:error:`，设备上的当前注册记录能否通过该检查仍待验证。

| 验证 | 结果与边界 |
|---|---|
| `tools/tests/test-sb-native-uninstall.py` | 12 个宿主场景通过，执行实际 `install_sb26()` 与 image callback，覆盖进程分支、原生方法保持、可删除限制、成功／失败入口、64 位 options 和延迟 completion |
| 旧版与消融 | 旧版有 4 个场景失败；仅恢复卸载方法替换有 3 个失败，仅恢复 eligibility 替换有 2 个失败 |
| arm64e 编译 | 主文件 `-fsyntax-only -Wall -Wextra -Werror` 通过；沿用 `userland/build.sh` 参数完成注入库编译、链接、ad-hoc 签名与严格签名验证 |
| 覆盖限制 | 安装服务和容器变化由替身提供，初始化中的 AirDrop、投屏、日历和地址匹配分支未完整执行 |
| 真机 | 待普通测试应用主屏卸载、Bundle／Data／共享容器处理、失败结果和重启后的注册状态验证 |

静态方法表与反汇编输出保存在本轮 Git 忽略的本地调试目录。TrollStore 自身的 `uninstallApp()` 仍直接删除 Data／Group／Plugin 容器，需作为独立事项检查。

## 6. 应用前台切换

后台启动应用无法转前台的遗留见[应用安装的签名](2026-11-09-ipa-codesign.md)。签名修复与前台切换问题分别验证；尚未确认它与卸载钩子有关。

现有记录只能确认复用后台进程与结束后重新启动的结果不同，尚不足以确定失败层。本轮未修改 RunningBoard、FrontBoard 或应用启动行为。下一次在同一开机内记录三组信息：

- 点击图标前后的 PID、suspended 状态，以及 RunningBoard 的 resume／foreground assertion 完成情况。
- FrontBoard 的 scene 创建或激活请求、应用响应，以及可见 scene 提交情况。
- 同一应用的 LS／FBS application identity、System／User 注册分类和主程序路径是否一致。

优先检查后台进程复用与 scene 激活，其次核对注册类型与身份。

文件系统身份另有独立检查方向。本地 APFS 将底层设备号放在 `f_fsid.val[0]`，容器及卷编号放在 `val[1]`；XNU 的 `fsgetpath` 仅按第一分量查找支持 `PATH_FROM_ID` 的挂载。启动代码可从同一设备挂载 OS／App 的不同容器，因此具备查找歧义的条件。当前设备的实际挂载组合仍待读取，不能据此确定前台切换根因。上游相关回退记录及其验收边界见[上游对照 §4.1](2026-11-12-upstream-review.md#41-pagani-的-usb-与文件身份)。

已准备只读 `fsid-roundtrip` 工具，按指定路径记录 `statfs`、`getattrlist`、`fsgetpath`、再次 `stat` 的结果，核对返回对象的完整 FSID 与 FILEID。macOS 的 7 个路径在 ASan／UBSan 下往返通过，缺失路径、非目录、无路径查询能力及参数错误均返回非零。原生 macOS 的两个查询接口可返回不同 FSID 但仍正确往返，因此仅记录接口间差异，以返回对象身份及 API 结果判断失败。

工具已完成 iOS arm64e 编译、链接和签名检查，源码、清单与二进制保存在本轮本地调试目录。后续设备只读检查覆盖 System、Data、OS／App Cryptex 根目录及实际文件，再加入系统应用和测试应用的 Bundle、主程序及 Data；bindfs 未声明 `PATH_FROM_ID`，其 `ENOTSUP` 单独解释。本轮未运行设备检查。

## 7. 高精度像素格式的下一项测试

本地 Metal SDK 将格式 94 定义为 `BGR10A2Unorm`。当前 `annibalemetal_device.inc` 的普通纹理入口将其转换为 80，`annibalemetal_texture.inc` 的 buffer-backed 入口保留 94；`pixelFormat` 返回创建时保存的格式。Mesa 的 `air_metal_formats.inc` 已将 94 映射为 `PIPE_FORMAT_B10G10R10A2_UNORM`，这项入口差异可先通过宿主测试复现。

S6 首项应调用实际创建入口生成 4×2、格式 94 的纹理，比较传入 Mesa 的格式和返回对象的 `pixelFormat`。像素测试使用非对称 RGB、相邻 10 位码值和四档 alpha，验收两个入口的格式、通道顺序、精度及 alpha 一致。主机原生 Metal 可提供参考像素；A830 渲染结果仍需真机复核。本轮只完成静态核查。

公开 XR 枚举为 552／553 `BGRA10_XR`、554／555 `BGR10_XR`，553／555 的 sRGB 属性已有 SDK 定义；550／551 的私有契约仍待确认。CoreVideo 分别定义 `w30r` 为 32 位 RGB、`w40a` 为 64 位 ARGB、`b3a8` 为 RGB 与 alpha 双平面，后续实现需分别核对布局与扩展范围。

`MiniIOSurface.cpp` 将 `w30r`／`l10r`／`w30R`／`b3a8` 改为 BGRA，`b3a8` 同时失去独立 alpha 平面；IOSurface 导入还会执行格式替换。这些替换与材质颜色异常的关系、当前 iOS 26 调用的实际格式分布尚未测量。S7、S8 仍按计划排队。

本地 Mesa 26.2.5 的 `ir3_alias.c` 与 `instr-a3xx.h` 仍包含上游已修正的两处实现，提交来源见[上游对照 §5](2026-11-12-upstream-review.md#5-mesa)。独立验证分别使用动态索引常量表与 `noaliasrt` 对照，以及整数位运算结果转浮点后执行 `fsat` 的 shader；后者输出到 `RGBA32Float`，避免 UNORM 写回的截断影响观测。需先核对生成指令确实包含相对常量寻址或目标饱和折叠，再比较像素结果。本轮未运行这些 shader，也未确认它们与材质问题有关。

显示侧可参考[上游对照 §3.4](2026-11-12-upstream-review.md#34-显示颜色绘制范围与-gpu-进度)的已知灰阶采样与路径计数。本地帧缓冲当前只绘制每元素 4 字节、无独立平面的格式；半浮点输入应在格式筛选或转换前取样，再检查实际进入的 CPU／GPU／DPU 路径。

## 8. 构建与提交

内核修复提交为 `10f3fd5c`，用户态卸载修复提交为 `f449168`。两个仓库只提交本批文件，多媒体任务的修改继续由其维护。

内核使用独立构建树，从 `cd13-iris-u32` 冻结 193 份移植文件，只替换 S1、S3 的四份生产文件。完整编译与链接退出码为 0；193 份冻结源码与构建树一致，四份修改与提交 `10f3fd5c` 一致。四个目标对象已重新编译，依赖和编译记录指向独立构建树；最终链接的 1,162 个对象全部来自该树。

内核产物为 20,565,272 字节，SHA-256 为 `c241f915bef6cc939492f942c1b07c4bd6a94a47f930a061b30f3a5a7f1ecdfd`。源码清单、选择记录、完整日志与 `build-verification.json` 保存于内核仓库已忽略的 `out/system-followup-1112/`。产物仅用于 S1、S3 目标编译验证，未包含后续 Iris、profiler、CRC 改动；设备对照从当前已验证基线分别选入单项修复。

卸载注入库使用独立输出目录，产物为 arm64e，152,240 字节；UUID 为 `58D1F45E-FE53-3414-A61D-4B7E94738C6F`，SHA-256 为 `a244314a9e85dc18725587bfb7ef3fc8b380c991fc694903f50734b2786ca487`。构建参数、六份项目源码和依赖的前后哈希、签名检查结果保存于本轮本地调试目录的 `s4-userland-build/`。

真机复核由既有 device 成员统一执行，优先安排正常退出后的文件读回、已有电池温度读数和普通可重装应用的卸载。高温边界使用宿主输入验证，异常复位测试需先确认备份与恢复条件。
