# 多媒体验证结果与剩余问题（2026-11-11）

本文记录音频、相机和视频候选的真机结果。实现与首批宿主测试见[多媒体适配进展](../progress/2026-11-11-multimedia-bringup.md)，底层接口分析见[多媒体根因定位及架构设计](2026-11-11-multimedia-root-causes-and-design.md)。编译、设备初始化和用户可用行为分别验收。

## 1. 已执行候选

| 轮次 | 内核记录 | 结果 |
|---|---|---|
| mm1 | `12377-multimedia-1111` | 约 38.2 秒出现 `Unhandled implementation specific error`，自动恢复 loader 空闲态 |
| mm2 | `12377-multimedia-1111b` | 约 38.9 秒出现同类 panic，自动恢复 loader 空闲态 |
| mm3 | `12377-multimedia-1111c` | 约 31.5 秒出现同类 panic，自动恢复 loader 空闲态 |
| mm4 | `12377-multimedia-1111d` | 约 39.8 秒出现同类 panic，自动恢复 loader 空闲态 |
| mm5 | `12377-multimedia-1111e` | 采样 408.4 秒，未捕获 panic；主动停止后恢复 `xnuloader / idle`，启动卷常驻区为空 |
| cd1 | `12377-codex-1111-iris-diag` | 采样 474.8 秒，未捕获 panic；本地 H.264 播放与设置页打开通过，收尾恢复空闲及空的常驻区 |
| cd2 | `12377-codex-1111-iris-log` | Iris 阶段日志可采集，首个失败为 GCC 视频 AHB 时钟等待超时；未捕获 panic，收尾恢复空闲及空的常驻区 |
| cd3 | `12377-codex-1111-cmd-db` | 66 份采样未捕获 panic；相机 RPMh 请求返回成功，GCC 相机与 MCLK AHB 仍未通过；硬件 H.264 创建返回 `-12906`，收尾恢复空闲及空的常驻区 |
| cd4 | `12377-codex-1111-fixed-ahb` | 固定 AHB 启用检查通过，前后传感器 ID 可读取；45.4 秒触发主机帧停滞判定，探针未完成；未捕获 panic，收尾恢复空闲及空的常驻区 |
| cd5 | `12377-codex-1111-gdsc-status` | 完成 420 秒采样与四条合并探针；Iris 电源与时钟通过，首失败为 SMMU 无可用 context bank；未捕获 panic，收尾恢复空闲及空的常驻区 |
| cd6 | `12377-codex-1111-smmu-cb` | 完成 420 秒采样；SMMU 配置与 PAS9 认证通过，硬解创建仍失败；未捕获 panic，收尾恢复空闲及空的常驻区 |
| cd7 | `12377-codex-1111-smmu-hfi` | 严格 HFI INIT 应答匹配通过，硬解仍失败；约 185 秒出现内核数据访问异常，软件收尾恢复空闲及空的常驻区，见第 8 节 |
| cd11-safe-baseline | `12377-codex-1111-cd11-safe` | 运行 35.872 秒后因 CPU 峰值 71.3°C 请求停止；4 项状态探针完成，功能探针未完成，恢复新版 loader 空闲态及空的常驻区，见第 17 节 |

上述结果来自本地 `docs/progress/evidence/k90auto/` 下各轮的 `returned.log`、`reboot.json` 和 `cycle-mm*.out`。mm5 的最后收尾查询在 12:40 返回空闲；后续独立启动需要重新读取状态。

## 2. 功能验收范围

| 项目 | 已验证 | 剩余问题 |
|---|---|---|
| 音频 | AudioQueue 启动与音频会话激活成功；48,000 帧交付和直写成功；AudioReach 两路图启动，PCM 完成计数持续增长，双功放进入 operating 状态 | 扬声器实际出声、冷启动系统播放器与网页播放待确认 |
| 本地视频 | mm5 的 H.264／HEVC 各解码 30 帧，像素检查通过；cd1 的本地 H.264 播放 23 帧，首帧 739 ms，无像素错误或停顿 | 上述成功解码未要求硬件，Safari 等实际场景待验证 |
| Iris 硬解 | 电源、时钟、SMMU、PAS9 与 HFI INIT 通过；H.264 硬件会话创建与失败回调完成 | 首帧仍收到固件 fatal，尚未输出帧；协议字段和错误回调修复见第 18 节 |
| YUV 合成 | NV12 与 P010 的 BT.601／709／2020 有限域和全域共 12 组通过 | 覆盖测试输入的计算与片元采样，见第 19 节 |
| 相机 | 枚举两台设备，可读取软件测试帧；cd4 固定 AHB 检查通过，后置 ID 为 `0x2121@0x10`、前置 ID 为 `0x5620@0x10` | 真实传感器流和 DMA 尚未验证；新反馈中的相机退出报缓冲区属性错误，旧 `_slmMinMax` 断言与新版辅助盘另行复核，见第 7 节 |
| 界面巡检 | cd1 壁纸可见，设置页可打开；cd2 主屏壁纸和应用名称可见 | 大组件仍有白块／蓝块，cd2 的应用图标位置为空；控制中心和通知中心巡检未验收 |

相机源码中的 `cam_hw_dma_verified` 和 `cam_sensor_streaming` 保持 `false`，读取测试帧只验证软件路径。后续相机验收必须同时取得传感器身份、出流状态和真实帧内容。

cd5 使用 `K90_FREEZE_OFF=1` 完成固定时长采样，保留主机帧观察记录。84 份快照覆盖 415.442 秒，最长相同 `frame_id` 观测为 59.793 秒，另有 6 份快照缺少帧记录；主屏图标仍为空。该轮验证了探针执行与软件收尾，界面持续响应尚未验收。

## 3. 接续验证

- Iris：严格 INIT 已通过，HFI 会话、缓冲区与应答修复已完成宿主检查。RAMFS 页生命周期、VPU 返回和 loader 资源保留修复将组成安全基线，继续验证硬件会话创建和出帧，见第 10、12、15 节。
- 相机：传感器 ID 与原版 SLM 管线构造已通过，继续检查原生会话、CSI／DMA 和真实帧内容。
- 音频与显示：合并音频提交、功放状态、本地播放、亮度和界面巡检，保留需要用户确认的声音与面板观察项。
- 每批最多三轮，读完本批结果后调整测法或单一变量，再继续下一批。每轮收尾核验 `xnuloader / idle` 和空的启动卷常驻区。

## 4. 产物与工具边界

mm5 内核 SHA-256 为 `dc13b6ec4e966fa7a6c0551f1f3eda969256efa6f74b2ace9f2abbbd90ca1ed1`，实际构建树是 `hackios-xnu-kernel/xnu-src/xnu-12377.121.6`。接手检查确认五个未提交移植源文件与该树对应文件一致。

无人值守恢复已加入运行态停机、静默后复位、重新枚举与 `oem recovery`。恢复命令失败、空序列号、身份不符或常驻区未清空均需要停止后续命令并保存现场。

loader 的重试计数查询固定返回 `7`；真实槽位预算以 LK 的查询为准，见第 16 节。临时启动前在 LK 将 A 槽重试恢复为 7，刷入前继续查询实际预算和引导状态。

## 5. 接手后的静态与宿主检查

- `annibale_cmd_db_lookup` 原先用 `strlcpy` 向 8 字节 ID 写入资源名，`mmcx.lvl` 被截成 7 字节和终止符。修复保留完整 8 字节名称，并拒绝超过 8 字节的输入；编译实际查询函数的二进制格式测试通过，恢复原有截断的测试变体按预期失败。
- 原厂 `gcc_sun_probe` 直接设置视频 AHB、相机 AHB 和 MCLK AHB 的启用位，未等待 `CLK_OFF` 清零。原厂 `clk_branch_toggle` 对启用硬件自动门控的时钟也直接返回成功。移植已按分支定义调整等待条件，并读回启用位、拒绝无效读数；cd4 的固定 AHB 检查通过，相机初始化继续推进。
- Iris GDSC 上电完成判据改用原厂 `GDSCR + 4` 的 bit 16，同时要求 `SW_COLLAPSE` 清零。实际函数的寄存器序列测试通过，12 个保护或地址变体按预期失败；cd5 相对 cd4 只改变这项判据，真机电源与时钟检查通过。
- Iris SMMU 原先要求整个 `SCTLR` 为零，候选按架构定义检查 `SCTLR.M` bit 0，保留其他有效 SMR 占用、末尾共享 bypass bank 和 CBAR 类型读回检查。19 个实际初始化函数用例通过，旧基线在 5 项失败，7 个编译变体按预期失败；cd6 使用与 cd5 相同的辅助盘、启动卷和参数，HFI 保持 cd5 来源，真机 SMMU 与 PAS9 检查通过。
- Iris HFI 初始化按原厂应答检查 `session_id=0`、INIT 类型、发送时保存的 INIT 编号与 SUCCESS bit 0，完整消息中的 SYSTEM_ERROR 优先处理。等待预算仍为 `1000 × 250 µs`，耗尽后返回失败；48 个实际构包、队列和初始化用例通过，未修复基线在 34 项失败，19 个编译变体按预期失败，cd7 取得匹配应答。
- `video_combined_test` 增加 P010 和 BT.2020，覆盖 8-bit／10-bit、有限域／全域、BT.601／BT.709／BT.2020 共 12 组。在原生 Metal 上，计算与片元采样的像素检查均通过；移植驱动结果待下一批真机验证。
- AIR 的 call-slot 与 GEP 检查通过 8 项。原版 `CCPortrait` 的 82 个模块均可读取，其中 76 个完成 AIR → NIR → A830 IR3 编译；其余 6 个仍缺 `air.cospi.f16` 或 `llvm.maxnum.{f16,v4f16}`，GPU 执行待验证。
- 反射解析与 Metal 驱动新增原版 SLM 管线检查程序。显式纹理访问标记逐项校验，矛盾标记和非法后缀被拒绝；旧解析器在新增用例失败，修复后通过，82 个原版模块的反射输出保持一致。arm64e AIR、驱动与辅助盘已重新构建并保存，真机管线与 `cameracaptured` 断言待复核。

## 6. 软件恢复与下一批前提

cd4 准备期间，PSCI 复位后首次重新枚举的 A 槽 standalone 已自动启动内核，`oem recovery` 返回 `kernel resources are unavailable for recovery`。随后停止内核并保存日志，设备进入 `returned`；这个停止现场没有再次发送 `oem recovery`，常驻 RAM 保持原状。GPU 日志记录 secure/context 资源保留，UFS 已归还控制器且在途请求为零。

软件恢复结果分开记录：

- 停止态只执行一次 `oem android`，命令返回成功；60 秒内没有 Android 枚举，实际进入 LK Fastboot。
- LK 查询确认 `product=annibale`、`is-userspace=no`、B 槽成功且可启动；`set_active a` 后读回 A 槽重试为 7。
- LK 临时启动完整的 loader-only 镜像，重新枚举后立即执行 `oem recovery`。最终 `product=xnuloader`、`result=idle`、常驻 RAM 为空；本次恢复没有刷写分区。
- 上述检查覆盖驻留 loader 和启动卷状态。GMU／RSC／OOB 与 CP_PIXEL 页归属尚无独立恢复读数，后续轮继续保存 GPU 初始化与收尾日志。

原始恢复命令和状态保存在本地 `docs/progress/evidence/k90auto/codex-device-1111/android-return-loader-once/`。新收尾入口通过 `LOADER_IMAGE` 选择完整调试镜像，经已识别的 LK 或启动完成的 B 槽 Android 返回 loader；终态日志保存后才切换，原停止现场的常驻 RAM 保持原状。恢复失败后停止队列。

旧 loader 的 `reboot-bootloader`／`oem reboot-lk` 在首个匹配 SPMI 通道不可写时提前结束，实际没有设置 LK 引导目标。修复跳过不可写通道，并检查事务完成、错误位和读回值，失败后不复位。46 个实际 helper／调用分支用例通过，旧基线和 16 个保护变体按预期失败；修复已提交为 `14e015ab`，临时启动与返回 LK 已验证，见第 11 节。

共享恢复入口已经过 cd4 起轮前及 cd4、cd5 收尾的真机检查，完整调用耗时分别为 31.509、30.895 和 30.380 秒。`cycle.py` 已改为调用同一入口，再独立校验终态，删除自身重复的复位与清理逻辑。LK 直接切换为唯一 loader 的枚举序列也可通过；重复或混合身份会停止操作。宿主检查通过：恢复 31 项、LK 切换 32 项、工具 39 项、cycle 状态 12 项；旧恢复入口在三项新增场景失败。保留状态配合 `LOADER_IMAGE` 先保存终态和 loader 日志，再通过 `reboot-bootloader` 进入已识别的 LK；旧分支和删除该选择的消融在新增场景均产生 13 个失败断言。

## 7. 手电筒、亮度与相机的新反馈

用户确认手电筒可以点亮，亮度滑块可以改变面板亮度。调整亮度、打开手电筒和空闲期间仍会出现全屏亮度闪烁。以下时间为 2026-11-11 本地时间（UTC+8），操作时间由用户近似记录。

| 时间 | 用户观察 |
|---|---|
| 21:08:04 | 没有操作，全屏亮度闪烁 |
| 21:08:35 左右 | 打开相机，短暂卡住后退出，退出期间亮度闪烁 |
| 21:08:58 前后 | 打开手电筒，全屏亮度闪烁 |
| 21:09:15 | 没有操作，全屏亮度闪烁 |

保存的运行日志在 21:08:33.257 记录相机 `DidStopRunning`、`ErrorStatus=-12780`，21:08:33.297 记录 Camera 客户进程结束。同段还记录 backboardd 的最低亮度及渐变请求；本次日志未出现 `_slmMinMax` 断言。相机退出原因与各亮度请求的实际面板写入继续分别核对。

背光日志记录 `DisplayBrightness.NitsPhysical=120` 被换算为 50.948 nits，随后 `IOMFBBrightnessLevel=7680368` 被换算为 117.193 nits。CoreBrightness 的 `NitsPhysical`／`Nits` 是普通 nits；`brightness-nits`、`IOMFBBrightnessLevel` 和 `DisplayBrightnessNitsNVRAM` 使用 nits × 65536。修复按字段区分单位，停止按数值大小猜测格式。

拖动分支另有亮度计算冲突：源码发布的亮度表在滑块位置 0.5 对应 140 nits，现有线性公式会得到 202.5 nits。该公式会覆盖同一次请求中的原生 nits；候选让亮度始终取原生 nits 或面板值，滑块位置保留触控窗口与保存用途。本次保存日志没有 `DisplayBrightnessSliderPosition`，该分支的触发由宿主输入复现，真机闪烁仍待复核。

背光修复的 56 项实际函数检查通过，旧基线在 27 项失败，16 个编译变体按预期失败。宿主连续四次接收 140 nits／`IOMFBBrightnessLevel=9175040`，均生成相同的面板亮度请求。修复内核已编译打包；物理面板闪烁、滑块操作与手电筒切换尚未复核。

相机在 21:08:33.186／.197 报 `SensorRawOutputBufferPoolRequirements=-12787`，并触发 `sensorRawPixelFormat != 0` 断言；随后建图连续失败，`createStillImageSinkPipelineSessionStorage=-12780`。保存的旧独立启动镜像中的媒体库缺少这项属性，新辅助盘已经包含。cd6 已读回实际加载的 `/annibale/lib/libannibale-media.dylib`，大小为 130,064 字节，SHA-256 为 `1801202847840ddc961fcc59d72bfb78854a10cd1ffac86382178ebbb48e07e6`，UUID 为 `14e79c48-5803-3a80-ada7-27c07e34ca40`；该轮枚举成功，原生相机会话仍待复核。

原始运行日志、进程查询与事件摘录保存在本地 `docs/progress/evidence/k90auto/codex-device-1111/standalone-user-events-2108/`。这些观察来自独立启动的 A 槽系统，cd4、cd5 和新版反射辅助盘的验收结果另行记录。

## 8. SMMU、HFI 与 cd7 提前返回

cd6 的 SMMU 选择 CB81：`CBAR=0x1f300`，原 `SCTLR=0x3e798118` 的 M bit 为零。Iris SID `0x1940`／`0x1947` 配置到 SMR11／12；PAS9 认证完成 15 个 segment、共 `0x800000` 字节。宽松的旧 HFI 分支打印初始化成功，匹配 INIT 应答由 cd7 单独检查。

两轮硬件解码结果如下，均未输出帧。

| 轮次 | H.264 | HEVC |
|---|---|---|
| cd6 | VT 创建返回 `-16155`，`hardware=-1` | VT 创建返回 `-12911`，`hardware=-1` |
| cd7 | 原生 30 秒 deadline 到期，退出码 124，耗时 30,130 ms，未生成创建或帧汇总 | VT 创建返回 `-16155`，退出码 1，耗时 20,497 ms，`hardware=-1` |

cd7 的 INIT 请求编号为 1，应答记录 `session=0`、`id=1`、`flags=0x00000001`，随后打印 `INIT done id=1`。应答类型由本轮匹配的 `HFI_CMD_INIT` 分支确认，日志没有直接打印类型数值；完整消息中未观察到 INIT SYSTEM_ERROR。

cd6 的 84 份快照覆盖 415.107 秒，最长相同 `frame_id` 观测为 55.333 秒，另有 5 份快照缺少帧字段。音频两路各提交 48,000 帧，相机枚举成功且 `hw_dma=0`；主屏图标仍为空。软件采样和收尾已验证，界面持续响应、声音与真实相机帧尚未验收。

cd7 在 21:57:59.164553 首次回答 `result=returned 1448283 0`，前一次查询仍为 `running`。37 份快照覆盖 185.416 秒，未完成计划的 420 秒采样，runner 未发送 `oem stop`。首个 `Kernel data abort` 位于 `memcpy + 40`／`ufshc_write + 548`，访问与修复记录见第 10 节；随后出现 `machine_routines_common.c:1128` 的 DAIF 断言。

cd7 软件恢复完成后，22:01:57 的独立核验确认唯一 `xnuloader`、`result=idle` 和空的常驻 RAM。后续候选与刷写暂停至故障修复，设备保持只读 heartbeat。本轮原始日志和请求记录保存在本地 `docs/progress/evidence/k90auto/kernel-12377-codex-1111-smmu-hfi-cd7/run/`。

## 9. AIR 常规检查与缓存

AIR 的 18 阶段检查在 20:59:44～21:43:54 完成，主检查退出码为 1。与 `bdac522` 的同环境对照确认：456 个常规模块的 reader 输出逐字节相同，编译成败相同，315 个 IR3 指令计数相同；本次发现的失败均与旧版一致。canonical 和拒绝规则保持原样。

- call-slot 专项从旧版 1/8 提高到 8/8，反射 fixture 通过；原版 `CCPortrait` 的编译范围见第 5 节。
- FMA 和 argument-buffer 的参考编译先在 clang 14 的 `ptr` 解析处失败。使用隔离的 LLVM 20 候选后，两版 FMA 三种 flags 全部成功，argument-buffer 均只剩同一条跨成员 phi 拒绝失败；候选未修改生产检查规则。
- Blend 两版均为 25/25 像素一致、7/9 拒绝满足；intrinsic runtime 的 10 个失败、lowering 的 3 个失败与 framebuffer 的 3 个失败均完成旧版对照。
- 真实 GPU、QuartzCore metadata 与设备 Metal 日志尚未覆盖；主检查的退出码 1 保留，用户态源码已阶段提交为 `636e07a`。

Mesa 的 ir3 缓存按同一 AIR 库的 `LC_UUID` 生成 driver ID，并在 shader key 中包含序列化 NIR。cd7 日志中的旧 AIR UUID 与新版产物 UUID 不同，新版将使用不同的驱动缓存目录；本批保留既有缓存版本与键结构。

`package.py` 在编译辅助盘前要求 AIR 构建记录存在，并核对库哈希与驱动反射头哈希。5 项实际校验块检查通过，旧路径在缺记录用例失败；保存的新辅助盘通过实际构建记录核对。

## 10. RAMFS 页生命周期与 UFS 访问异常

使用 cd7 实际内核解析首个访问异常，读源地址在 `ufshc_write()` 拷贝阶段失效。当前请求尚未执行缓存清理、放入 UFS 请求槽或写入 doorbell。

| 字段 | 本轮读数 |
|---|---|
| PC | `0xfffffff007cf7178`，`memcpy + 40` |
| LR | `0xfffffff0075996f0`，`ufshc_write + 548` |
| FAR／x1 | `0xfffffffb25bd4000` |
| x2／ESR | `0x4000`／`0x96000007` |

源码中 `ramfs_store()` 返回裸页面地址，调用方解除 `rm_lock` 后才同步写盘；并发 truncate、resize 或页面回收可以释放该页。修复让 write、pageout 持有同一把锁完成内存更新、同步写盘和页面回收；已有块的部分读取也保留锁。pageout 在锁外分配后重新核对 EOF 与槽位。原有 EIO、uio 计数和 dirty 时序保持。

- `test-ramfs-page-lifetime.py` 编译实际 store、write、pageout、free、resize 与 `ufshc_write`，使用 pthread 和 mmap／munmap 复现释放后拷贝。候选 13/13 通过，旧版 6 项通过、7 项失败，其中 4 项在真实 UFS 拷贝处访问已解除映射的源页。
- 删除写入锁的 4 项检查全部失败，删除部分读取锁的 2 项检查全部失败。已有 sync-errors 与 disk-recovery 检查通过。
- panic-log restore 位于 VFS mount 发布前，clone 位于目录发布前；这两处页面尚未交给外部 vnode 操作。resize 尾块写入已有 `rm_lock` 保护。
- cd7 的具体 vnode 和并发调度尚未取得；宿主复现确认了源码中的生命周期错误，真机复核继续检查相同访问异常。

cd10 使用 193 份冻结源码隔离构建，退出码 0，构建树逐文件哈希匹配。它包含 RAMFS 修复，背光与 HFI 保持 cd7 的选择；该候选没有上传或运行。静态核对发现 VPU 返回清理缺项后，后续运行暂停，先完成第 12 节的保护条件。

## 11. 当前启动分区备份与内含版本

经 B 槽 Android 读取完整 `boot_a`、LUN 0／4 的 GPT 主备头与分区数组。备份大小为 100,663,296 字节，设备与主机 SHA-256 均为 `2150035a74fb6d1370a8c3a2cdcf80122a701c9fd692ce2e96edbad38147836a`；旧备份继续保留。

| 当前 `boot_a` 的 XNUP 条目 | 大小（字节） | 核对结果 |
|---|---:|---|
| `loader.efi` | 148,992 | 旧驻留 loader |
| `kernel` | 20,496,032 | SHA-256 `610b90a7676ef54e3a150223946cc535eb207a17a244b9f0b26e90087bbf00aa` |
| `ramdisk` | 18,558,976 | 媒体库缺 `SensorRawOutputBufferPoolRequirements`，尚未包含 `libannibale-vt.dylib` |
| `rdimage` | 4,194,304 | 与本轮保存的启动卷哈希相同 |

该媒体库 UUID 为 `165fea75-6603-328a-899c-296680472302`，SHA-256 为 `b248d0a44a72b338e6f7068ce243e935971cbd914b9ef166b20b231e5ec11ad5`。第 7 节相机属性错误继续以新版实际加载库复核。

- LUN 0 有 1 对、LUN 4 有 23 对分区使用一个活动类型和一个 inactive GUID，24 对均为 B 相位；另有 13 对保留各自的非 inactive 类型。主备 CRC、分区数组和主机／设备哈希检查通过。
- loader 与 LK 按参与切槽的分区维护 GUID，相同 `_a`／`_b` 后缀不足以判定应交换类型。`countrycode`、`vbmeta_system` 等独立类型条目保持原值。
- 原始 A 相位 GPT 尚未读取；本段只取得 LK 的 `current-slot=a`、A 重试计数 7 与 loader 自身槽位识别。
- 当前分区尾部保留 64 字节 `AVBf` 和 2,432 字节 `AVB0`，元数据偏移为 36,409,344。`boot` 的 SHA-256 hash descriptor 与当前镜像内容不匹配；新完整镜像需要重新生成并校验对应元数据。

`14e015ab` loader-only 已临时启动，`reboot-bootloader` 命令返回成功，6.419 秒重新枚举 LK、6.586 秒完成身份核验。随后临时返回该 loader，并独立确认空闲和空常驻区。本段没有刷写分区。

原始备份、版本解析、GPT 分类与命令结果保存在本地 `docs/progress/evidence/k90auto/codex-device-1111/loader-spmi-backup-1/`。

## 12. Iris 返回停机与内存保留

原生 `qcom_scm_pas_shutdown()` 使用 PIL service `0x02`、command `0x06`、SIP owner、STD SMC64 与一个 VAL 参数 PAS ID 9，对应 `0x42000206`。传输返回和固件结果均为零才算成功。来源为 Linux `a41e364995bbcfa627418a70fe913c35b7510728` 的 `drivers/firmware/qcom/qcom_scm.c` 与 `qcom_scm-smc.c`。

候选在发送 `AUTH_AND_RESET` 前设置 `pas_shutdown_required` 与 `dma_shutdown_unconfirmed`，覆盖请求已生效但回复失败的情况。全局返回发生在其他 CPU 停止后，清理函数直接调用 PAS shutdown，并核对本次使用的两条 SMMU 路由、SCTLR.M 和 TLB 同步；该路径保持锁外执行，避免等待已停止 CPU 持有的 Iris mutex。

原生 Iris 先执行 PAS shutdown，再关闭 VPU 电源，最后释放队列 DMA。SM8750 的电源关闭还包含 NOC 与 VPU idle 检查；本批尚未实现完整硬件停机。PAS 和 SMMU 清理成功后仍保留 `dma_shutdown_unconfirmed`，返回 `loader_jump(3, 9)`，保存日志后通过实际复位恢复。重复返回继续保留内存与映射。

SMMU 配置开始前记录 `smmu_owned` 和 CB／SMR 索引，setup 中途返回也能清理。会话页面释放同步返回 TLB 失败；失败后页面和描述符继续保留，调用方保留会话槽位。

- PAS、SMMU 与实际 `loader_return()` 的 28 项宿主检查通过，覆盖认证成功、请求失败、已执行清理和重复返回；旧返回函数在 27 项失败，9 个保护消融失败。
- 实际 DMA 分配与释放的 11 项检查通过，4 个删除释放／同步保护的编译变体失败。
- loader 提交 `06f259e1` 接受 `loader_jump(3, 9)`，CPU 全部关闭后仍保留资源；`returned-held <log_len> 0` 字段布局保持，设备编号写入日志。下载、清 RAM、再次起核与返回后的 staging 均被拒绝。
- loader 生命周期检查、52 个保护消融、RAM 903 项及相关消融、recovery、build-id 和整份 loader 语法检查通过。实际 recovery 函数模拟确认保存日志后复位；复位未完成则保留原资源。

新 loader 已按该提交隔离构建，嵌入 EFI、XNUP 和 build-id 校验通过；参考镜像的 shim、FD、DTB 与 ramdisk 逐字节相同。临时启动在 31.583 秒内完成，重新枚举后立即执行 recovery，独立核验 build-id、`product=xnuloader`、`result=idle` 和空的常驻区；没有刷写分区。完整安全内核候选已构建，仍待真机复核。

## 13. VideoToolbox 内部参数生命周期

原生 `VTDecompressionSessionCreateWithOptions` 在 `0x1903b8b98` 将 context 内部地址传给 `start_session`；`decode_frame` 在 `0x19018eae0` 接收 context 计数器生成的整数帧 token。驱动原有 `CFRetain`／`CFRelease` 要求 CF 对象头，与这两类参数的调用契约冲突。

修复将 session 作为借用的 opaque handle，frame token 按指针宽度原样保存并送回 `VTDecoderSessionEmitDecodedFrame`。CVPixelBuffer 等 CF 对象继续按原路径释放。原生 invalidate 在 `0x19065186c` 执行，context 随后于 `0x190651a4c` 释放；完整队列与清理顺序已核对。创建路径将计数器初始化为 1，decode 先读取旧值再递增，正常首帧 token 为 1。

- 完整 `test-iris-safety.py` 宿主检查通过；旧 VT 源在非 CF session 与整数 token 两类检查触发 SIGABRT，6 个恢复 CF 引用计数的编译变体失败。
- 使用 `package.py` 相同 SDK 与 VT flags 独立编译、签名 arm64e 库，退出码 0。
- callback 参数、base／derived vtable 槽位和 PAC 已静态核对。cd7 的进程 249 报未知 ObjC class，现场缺少该进程的加载 slide／UUID，仍需带 PID 的阶段日志核对。

## 14. 安全基线与变量隔离

恢复真机使用同时包含 RAMFS、HFI、VideoToolbox 生命周期和全局返回保护的安全基线。先前 cd10 保留原版本及构建记录，本批不执行该候选；安全基线的结果无法单独归因到上述某项修复。

内核与 Metal 驱动修改已提交为 `1c762866`。`cd11-safe` 与 `cd12-backlight` 均已构建成功，两份各含 193 份冻结源码，逐文件比较仅背光源码不同；每次构建后均核对展开树哈希。三份载荷的启动参数和启动卷相同，前两份使用相同内核，后两份使用相同辅助盘。

两份辅助盘通过 `package.py` 的实际 VT 构建函数与标准 `mkapfs.py` 打包。它们包含同一份修复后的 VT 库、H.264／HEVC 320×192 8-bit 样本和 YUV 检查库；逐路径读取内容与元数据后，两份盘之间只有 AIR、Metal 驱动和系统插件三项不同。

| 辅助盘 | SHA-256 | 用途 |
|---|---|---|
| `safe-baseline/root.apfs` | `9cdd72c30d72d9bafa11e5c74b7863e6dea6a317a874b47863ad80647e13e581` | 保留前一批 AIR／Metal 的安全基线 |
| `safe-reflection/root.apfs` | `c8618ac45fe591a2847ca6cb72140f149e033c096142640f8a620c171654f6ca` | 单独验证反射与跨函数指针修复 |

| 内核 | SHA-256 | 用途 |
|---|---|---|
| `cd11-safe` | `2df38d40fa6895b8e4d8d48c238a72d3c34c898316bec6d06e300e7f13b9e4be` | 安全基线，保留旧背光 |
| `cd12-backlight` | `872e5b7862ad2d16413f4185500d0ed0415898a070a001639372596920c337be` | 仅替换背光源码 |

VT 库 SHA-256 为 `38d246c9bfea28177d2260fc5c4d63fb5bb315c4e7683e7881809231cbfa19ec`，与独立 arm64e 构建相同。辅助盘和逐文件差异清单保存在本地 `hackios-xnu-kernel/out/codex-1111-safe-roots/`。

该批计划三轮，各运行 420 秒、只尝试一次，完成同一组多媒体探针与界面采样。第二轮只更换反射辅助盘，第三轮在相同辅助盘上只更换背光内核；任何异常先保存日志并恢复空闲 loader，再调整测法或变量。物理背光闪烁与实际声音保留为用户观察项。

## 15. HFI 会话与缓冲区契约检查

会话候选按原生 HFI 定义使用 HEVC `codec=3` 和 NV12 `color_format=1`，公共 ioctl 的 HEVC 标识保持 `2`。应答按 session、packet ID、类型和错误标志匹配，缓冲区返回还检查索引、地址、端口与长度。输入缓冲保留到固件归还；STOP、CLOSE 或 TLB 同步失败后保留页面和会话槽位。

- 实际构包、会话、缓冲区与调用方检查通过 100 项；38 个删除校验或资源保护的编译变体均未通过检查。
- 初始化检查通过 50 项；旧基线通过 3 项，21 个保护消融均未通过检查。
- 测试记录中的 HFI、私有声明、设备入口和 ioctl 头文件哈希已与本次工作树核对一致。

上述检查覆盖宿主模拟的协议输入和资源生命周期。硬件固件对完整会话及缓冲区配置的接受结果、实际解码帧和返回保护仍待安全候选真机复核。

## 16. 显式 Fastboot 驻留

接续查询发现设备运行旧版独立启动系统。共享恢复入口在 31.539 秒内完成日志保存、LK 槽位检查和 `06f259e1` loader 临时启动；独立核验确认 `result=idle`、`product=xnuloader` 和空的常驻区，分区内容未改动。

该 loader 的自动 fallback 在主机静默 120 秒后复位，看门狗还保留 180 秒主机静默限制；`oem recovery` 没有取消这两项。源码检查另发现菜单绘制期间可处理 recovery，随后初始化语句会清除刚设置的标记。设备再次运行旧系统的具体触发时刻尚未取得，这两处问题通过源码和宿主场景分别检查。

驻留候选复用现有菜单状态：显式 recovery 取消自动 fallback；空闲、无资源保留且 USB 端点正常的驻留状态持续喂看门狗。起核和自动 fallback 撤销驻留，其他状态保持原有恢复限制。菜单标记初始化移到首次 USB 处理之前。

loader 的 `slot-retry-count:a` 固定回答 `7`，真实槽位预算以 LK 查询为准。本次恢复读取 A 槽重试为 `5`，执行 `set_active a` 后读回 `7`；后续批次核验 LK 恢复记录。

驻留修复已提交为 `a1c40aed`，22 份冻结源码与提交逐文件一致。12 个实际函数场景通过；旧版对照和 15 个删除状态检查的编译变体均检测到预期失败。recovery 16 项、完整 loader 语法、build-id 与生命周期保护检查通过。完整 loader-only 镜像已构建。11 月 12 日 00:11:39～00:14:59（UTC+8）静默 200.003 秒，期间未发送设备命令；结束后重新枚举，build-id 保持 `a1c40aed`，`result=idle`、`product=xnuloader` 且常驻区为空。原始记录保存在本地 `loader-residency-1112/`。

## 17. 安全基线的温度停止

11 月 12 日首轮安全基线从 `oem run` 到 `oem stop` 共 35.872 秒，采集 8 份快照。CPU 域 1 在首个 30 秒窗口有 85% 时间运行于 3072 MHz，窗口峰值 71.3°C；主机按本批 70°C 上限停止探针并请求正常收尾。该快照的即时 CPU 读数为 49.2°C／50.4°C，停止条件使用窗口峰值。

- 4 项状态探针完成；SLM 探针已发送，原生反射对象构造通过，管线结果未取得。
- Iris 只执行设备注册，尚未进入硬解探针；该轮没有覆盖 PAS9 与 HFI 会话返回保护。
- 收尾日志确认 UFS 控制器归还、doorbell 为零；没有捕获 panic 或内核数据访问异常。恢复后独立核验 `a1c40aed / idle` 和空的常驻区，LK 的 A 槽重试读回为 7。
- 后两轮未执行。原始记录位于本地 `kernel-12377-codex-1111-cd11-safe-baseline/run/`。

后续使用正常 `cpufreq=1` 完成功能测试，结果见第 18、19 节。当前主机策略为连续三条新 CPU 即时报告达到 80°C 才停止，低于 80°C 重置计数；任一即时读数或区间峰值达到 88°C 立即停止。重复快照不重复计数，环形日志缺少重叠片段时记录采样缺口并保留已有计数。

上述阈值用于本批测试，内核温控保持原配置：每 50 ms 采样，70°C 开始逐档降频，75°C 立即请求最低档，每 30 秒输出统计。当前性能读数见第 20 节。

## 18. 硬解会话失败与原生错误回调

`cd11-safe-baseline-cap` 使用 `cpufreq_mhz=1800` 运行 125.794 秒，最高采样温度为 52.3°C。H.264 的 VT 会话创建成功，`hardware=1`；首帧进入 Iris 后，固件返回 `type=0x04000003 / flags=0x4`，未取得输出帧。原厂 `msm_video.ko` 的错误表将该类型定义为 `HFI_ERROR_FATAL`，当前日志没有更细的参数错误说明。

- OPEN 9 与 SUBSCRIBE 19／20 收到成功应答；START 21 尚无成功应答，输入 PSC、RAW 发布和输出帧均未出现。
- 原厂 `msm_vdec_set_bitstream_resolution` 在 `0x29c50` 使用 `payload_info=1`（U32）；移植发送了 `10`（32_PACKED）。`cd13-iris-u32` 仅修正此输入分辨率字段，五类内部缓冲区大小与已有原生 320×192 样本一致。100 项 HFI 宿主检查通过，将字段退回 10 后，H.264 与 HEVC 构包检查均失败。该字段与固件 fatal 的实际关系仍需真机复核。
- iOS 26 原生 `decode_frame` 调用位于 `0x19018eaf0`，普通错误返回经过日志分支后在 `0x19018eb68` 清零。插件原先只移除本地 token 并返回错误，原生 pending 帧没有完成回调，测试提交 30 帧后耗尽 30 秒 deadline。
- VT 候选为失败帧调用 `VTDecoderSessionEmitDecodedFrame`，轮询失败则完成剩余帧的错误回调。非零 tag 查询失败保留其他待完成帧；已发送完成回调的当前帧不会重复完成。实际函数测试覆盖坏样本、ioctl 失败、回调失败、轮询失败和重复 invalidate；旧源码在新增回调检查失败，arm64e 编译与签名通过。
- 收尾进入 `returned-held`，`PAS 9 shutdown succeeded` 后记录 VPU DMA 完成尚未确认。软件复位恢复 `a1c40aed / idle` 和空常驻区，保留资源的返回路径已在真实 Iris 会话中执行。

本轮原始记录为本地 `kernel-12377-codex-1111-cd11-safe-baseline-cap/run/`。新候选的内核记录为 `kernel-12377-codex-1112-cd13-iris-u32/kernel.json`，与背光候选的 193 份源码逐项比较，仅 HFI 文件不同；辅助盘逐路径比较仅 VT 库内容与对应扩展属性不同。

`cd13-iris-u32-vt-completion` 运行 71.212 秒，采集 15 份快照，最高采样温度 71.7°C。H.264 探针在 30,109 ms 后返回 124；HFI INIT 和 VT 插件注册完成，但日志尚未进入 VT 会话创建或 SESSION OPEN，未覆盖两处修复。PAS9 关闭成功，软件恢复后确认新版 loader 空闲且常驻区为空。后续通过 tracks／reader／create 阶段日志区分等待位置，并在启动采样结束后执行 60 秒 deadline 的硬解探针。

`cd13-iris-u32-p010-profile` 已进入 H.264 硬件会话，首个输入仍收到 `HFI_ERROR_FATAL`，U32 修正未解决该故障。VT 在 5,449 ms 内完成失败回调，`callbacks=1 / dropped=1 / frames=0`，随后 `drain status=0`；错误完成修复通过真机验证。后续 HEVC 与播放器探针未发送，软件收尾恢复新版 loader 空闲及空常驻区。

START 的命令、flags、端口和空 payload 已与原厂 `venus_hfi_start` 核对一致。当前 `iris_drain_dbgq` 只推进调试队列读指针，未输出队列文本；SFR 读取还依赖调试队列非空，session error 分支直接返回。下一步先按原厂 `__flush_debug_queue` 的消息格式保留有界固件诊断，再区分会话配置、DMA 和固件内部错误。

## 19. 正常频率下的独立功能验证

`cd11-safe-reflection` 使用正常 CPU 调频完成 16 项探针，运行 192.899 秒，采集 39 份日志和 4 张截图，最高采样温度 73.3°C。全部探针完成后继续观察约 64 秒，再正常停止；恢复后独立确认新版 loader 空闲、常驻区为空，真实 LK 的 A 槽重试为 7。

| 项目 | 本轮结果 | 验收边界 |
|---|---|---|
| 原版 SLM | `slm_calc` 与 `slm_calc_eyes` 均返回 0，分别匹配 4／6 个参数与绑定 | 原版 Metal 管线构造通过；相机真实传感器流尚未验证 |
| 软件 H.264／HEVC | 各提交、完成并检查 30 帧，回调错误和像素错误均为 0 | 显式禁用硬件解码 |
| NV12 | BT.601／709／2020 的有限域、全域共六组通过 | 计算和片元采样均比较预期色值 |
| P010 | 六组均有色值偏差，计算与片元结果相同；有限域每组 2 个分量检查失败，全域每组 4 个失败 | GPU 命令完成，位深转换继续修复 |
| 相机 | 前后两台设备可枚举，分别列出 33／14 种格式 | 设备与格式枚举成功 |
| 音频 | 会话激活成功，AudioQueue 和设备直写分别交付 48,000 帧 | 实际声音仍需用户确认 |

SLM 两条命令的原生耗时分别为 3,141 ms 和 47,705 ms；后一条日志中的 IR3 等待为 60.637 ms，命令全程耗时需要另行分解。

P010 采样按 16-bit UNORM 读取 bits 15:6 中的 10-bit 值，原 YUV 转换未传递位深。候选在资源键中保留 P010 位深，使用 Mesa 的 `lower_sx10_external`，采样结果先除以 64 以匹配其低位存储契约。6 组 NV12 和 30 组 P010 宿主数值检查通过，覆盖三种矩阵、两种范围和黑／白／中性灰／两组非中性色值；旧代码在 P010 黑色输入上失败。资源键、纹理绑定与 ownership 检查通过。

随后 `cd13-iris-u32-p010-profile` 的 NV12 六组、P010 六组 GPU 检查全部通过，计算与片元采样均为零色值错误，两条探针分别耗时 3,739 ms 和 2,968 ms。本轮最高采样温度为 74.0°C。

本轮跳过已知失败的硬解和依赖硬解的播放器探针，原始记录为本地 `kernel-12377-codex-1111-cd11-safe-reflection/run/`。随后在相同辅助盘和启动参数下仅更换背光内核，运行 209.412 秒并完成同样的 16 项探针，最高采样温度同为 73.3°C，功能结果一致；收尾恢复新版 loader 空闲且常驻区为空。面板闪烁仍需结合物理观察验收。

## 20. 性能采样的结论与下一步

正常频率轮的两次进程采样相隔约 98.16 秒。SpringBoard 累计消耗增加 49.45 CPU 秒，其中用户态 6.74 秒、内核态 42.71 秒；同期 backboardd 增加 5.73 秒，iconservicesagent 增加 8.81 秒。下一轮先对 SpringBoard 做同一时间窗口的线程和内核采样，定位内核态耗时。

- GPU 日志记录最近确认的频率请求为 160 → 342 → 160 MHz；`GPU_SPEED=14` 提供最高档位，当前日志没有持续运行在该档位的结果。
- CPU 3072 MHz 在已读窗口的占比约为 51%～68%，温控限制累计 0～254 ms／30 秒。现有读数没有将温控定位为主要耗时。
- 本轮没有触摸记录，最长连续帧段只有 20 帧；首个 94 帧统计中 93 帧没有内容变化。当前结果不能用于验收持续动画帧率。
- 后续复用 `threads`、`prof` 与 `dump` 采样启动期 SpringBoard，再执行固定控制中心下拉与收回，只统计连续重绘且内容发生变化的区间。CPU、GPU 配置和画布保持一致后，再根据具体耗时调整实现。

本轮发现 `gic_v3_prof_control(false, ...)` 会清空采样表，先关闭再读取的 25 秒窗口没有保留样本。修复后开始采样会重置表，停止采样保留表和丢样计数；真实函数宿主测试与单文件 arm64 编译通过，旧代码在保留样本检查中失败。当前部署候选仍使用冻结的 cd13，临时采用先读取再停止的顺序，继续采集运行期热点。

运行期补采取得 5,927 个样本，另有 109 次记录丢失。主要内核调用链为 `crc32 → ramfs_disk_sync_impl → VNOP_FSYNC → fsync_common`，其次为 UFS 写入完成轮询和全量元数据缓冲区清零／复制。`annsh` 输出上限保留 600 行，已输出记录覆盖 4,275 个样本；低频尾部不完整，样本次数不直接换算成耗时。继续核对 CRC 实现与每次同步的数据量。

固定控制中心操作后的两帧各自相同，但下拉组与收回组之间，状态栏下 98.52% 的像素发生变化。截图标签对应的动作与实际界面有延迟：下拉组仍显示桌面，收回组显示控制中心。日志仅保留一个可用触摸起点，随后首个显示完成相隔约 1,578 ms，连续帧不足以计算正常手势帧率。

## 21. 完整镜像刷入与正常重启

完整候选包含 `a1c40aed` loader、cd13 内核、P010 AIR 与 VT 错误完成修复。临时启动通过，4 MiB 内置启动卷、UFS 切根和 OS／App Cryptex 均正常，SpringBoard 与 backboardd 实际加载的 Metal bundle 和 AIR UUID 与冻结文件一致。17 项探针完成，最高采样温度为 74.0°C；末尾稳定观察后恢复 loader 空闲及空常驻区。

随后向 `boot_a` 写入完整 96 MiB 镜像，设备确认发送和写入成功；正常重启后再次确认内置启动卷、切根和实际加载的库。精简验证运行 81.746 秒，4 项查询全部成功，最高采样温度为 72.1°C。收尾恢复 `a1c40aed / xnuloader / idle`、空常驻区，真实 LK 的 A 槽重试读回为 7。

- 镜像 SHA-256：`fec770a36ee84da02de5795bd4a2b1493f50065cb555bfeffd99a4eea75b5fc4`；内置 XNUP SHA-256：`aeed5b6ba44a2b2190585d630a48bd38ccccdbc6c1213c9a381a4625229a0830`。
- 刷前核对 LK `unlocked=yes`、`boot_a=0x6000000`、A 槽重试为 7、B 槽 successful 且可启动；完整旧 `boot_a` 与 LUN 0／4 的 B 相位 GPT 备份哈希通过。
- 本次未读取物理 `boot_a` 全分区校验哈希，已确认写入应答、正常重启和运行身份。精简轮截图仍处于启动标志，桌面和控制中心观察来自前一轮同镜像临时启动。
- 记录保存在本地 `codex-device-1111/standalone-p010-deploy/`。本镜像不含后续 profiler 停止保留修复、S1／S3 系统修复、S4 卸载库和 CRC 加速候选。
