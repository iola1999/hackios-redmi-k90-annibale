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
| cd4 | `12377-codex-1111-fixed-ahb` | 固定 AHB 启用检查通过，前后传感器读取路径返回数值，身份仍待确认，见第 39 节；45.4 秒触发主机帧停滞判定，探针未完成；未捕获 panic，收尾恢复空闲及空的常驻区 |
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
| 相机 | 枚举两台设备，可读取软件测试帧；cd4 固定 AHB 检查通过，后置读值为 `0x2121@0x10`、前置为 `0x5620@0x10`，读取契约缺口见第 39 节 | 传感器身份、真实传感器流和 DMA 尚未验证；新反馈中的相机退出报缓冲区属性错误，旧 `_slmMinMax` 断言与新版辅助盘另行复核，见第 7 节 |
| 界面巡检 | cd1 壁纸可见，设置页可打开；cd2 主屏壁纸和应用名称可见 | 大组件仍有白块／蓝块，cd2 的应用图标位置为空；控制中心和通知中心巡检未验收 |

相机源码中的 `cam_hw_dma_verified` 和 `cam_sensor_streaming` 保持 `false`，读取测试帧只验证软件路径。后续相机验收必须同时取得传感器身份、出流状态和真实帧内容。

cd5 使用 `K90_FREEZE_OFF=1` 完成固定时长采样，保留主机帧观察记录。84 份快照覆盖 415.442 秒，最长相同 `frame_id` 观测为 59.793 秒，另有 6 份快照缺少帧记录；主屏图标仍为空。该轮验证了探针执行与软件收尾，界面持续响应尚未验收。

## 3. 接续验证

- Iris：严格 INIT 已通过，HFI 会话、缓冲区与应答修复已完成宿主检查。RAMFS 页生命周期、VPU 返回和 loader 资源保留修复将组成安全基线，继续验证硬件会话创建和出帧，见第 10、12、15 节。
- 相机：原版 SLM 管线构造已通过；传感器读取存在第 39 节所述缺口，继续检查身份、原生会话、CSI／DMA 和真实帧内容。
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

运行期补采取得 5,927 个样本，另有 109 次记录丢失。主要内核调用链为 `crc32 → ramfs_disk_sync_impl → VNOP_FSYNC → fsync_common`，其次为 UFS 写入完成轮询和全量元数据缓冲区清零／复制。`annsh` 输出上限保留 600 行，已输出记录覆盖 4,275 个样本；低频尾部不完整，样本次数不直接换算成耗时。CRC 优化与后续对照见第 22 节。

固定控制中心操作后的两帧各自相同，但下拉组与收回组之间，状态栏下 98.52% 的像素发生变化。截图标签对应的动作与实际界面有延迟：下拉组仍显示桌面，收回组显示控制中心。日志仅保留一个可用触摸起点，随后首个显示完成相隔约 1,578 ms，连续帧不足以计算正常手势帧率。

## 21. 完整镜像刷入与正常重启

完整候选包含 `a1c40aed` loader、cd13 内核、P010 AIR 与 VT 错误完成修复。临时启动通过，4 MiB 内置启动卷、UFS 切根和 OS／App Cryptex 均正常，SpringBoard 与 backboardd 实际加载的 Metal bundle 和 AIR UUID 与冻结文件一致。17 项探针完成，最高采样温度为 74.0°C；末尾稳定观察后恢复 loader 空闲及空常驻区。

随后向 `boot_a` 写入完整 96 MiB 镜像，设备确认发送和写入成功；正常重启后再次确认内置启动卷、切根和实际加载的库。精简验证运行 81.746 秒，4 项查询全部成功，最高采样温度为 72.1°C。收尾恢复 `a1c40aed / xnuloader / idle`、空常驻区，真实 LK 的 A 槽重试读回为 7。

- 镜像 SHA-256：`fec770a36ee84da02de5795bd4a2b1493f50065cb555bfeffd99a4eea75b5fc4`；内置 XNUP SHA-256：`aeed5b6ba44a2b2190585d630a48bd38ccccdbc6c1213c9a381a4625229a0830`。
- 刷前核对 LK `unlocked=yes`、`boot_a=0x6000000`、A 槽重试为 7、B 槽 successful 且可启动；完整旧 `boot_a` 与 LUN 0／4 的 B 相位 GPT 备份哈希通过。
- 本次未读取物理 `boot_a` 全分区校验哈希，已确认写入应答、正常重启和运行身份。精简轮截图仍处于启动标志，桌面和控制中心观察来自前一轮同镜像临时启动。
- 记录保存在本地 `codex-device-1111/standalone-p010-deploy/`。本镜像不含后续 profiler 停止保留修复、S1／S3 系统修复、S4 卸载库和 CRC 加速候选。

## 22. BSD CRC32 指令加速

ANNFS 同步在持有 `rm_lock` 期间计算完整元数据 payload 的 CRC，原 BSD 实现逐字节查表。提交 `a0e46547` 为 arm64 小端平台加入标量 CRC 指令路径，复用 `gARM_FEAT_CRC32` 能力检测；能力尚未初始化或 CPU 不支持时继续使用原软件实现。API、多项式、输入输出补码、分段续算、持久化格式和写入顺序保持一致。

- 相对上游实现新增 28 行，一个私有函数限定编译目标；没有新增配置、状态或依赖。
- 88,500 项 zlib 对照通过，覆盖软硬路径、五类初值、16 种对齐、短缓冲区、约 32 MiB 输入、分段续算及保护页边界。替换成 CRC32C 的编译变体未通过检查。
- 使用原内核参数单文件编译成功。隔离构建树的全部对象重新链接后与 cd13 逐字节一致；cd14 仅替换 `crc32.o`，其余对象和链接输入相同。
- 宿主五轮中位数：1 MiB 从 1.931 ms 降到 0.0981 ms，16 MiB 从 30.47 ms 降到 1.508 ms。这组数字仅描述宿主 CRC 函数吞吐。

CRC 批次依次执行 cd14 RAM 启动、cd13 同条件对照、cd14 完整镜像刷入后正常重启。三轮使用相同辅助盘、启动参数和 17 项探针，运行时长分别为 213.665、229.330、211.038 秒，最高采样温度分别为 75.2、74.0、73.6°C。全部完成稳定观察与硬收尾，独立确认新版 loader 空闲、常驻区为空，真实 LK 的 A 槽重试为 7。

| 轮次 | profile 时长 | 内核／用户样本 | 丢样 | SpringBoard 内核／用户 CPU 增量 |
|---|---|---|---|---|
| 前一轮 cd13 完整镜像 | 25.016 秒 | 4,290／1,637 | 109 | 17.63／1.63 秒 |
| cd14 RAM | 25.009 秒 | 353／738 | 0 | 3.54／1.60 秒 |
| cd13 同条件对照 | 25.036 秒 | 4,742／1,814 | 128 | 27.91／2.88 秒 |
| cd14 刷入后正常重启 | 25.020 秒 | 239／246 | 0 | 3.37／1.52 秒 |

CPU 增量来自约 68～70 秒的两次进程查询，包含命令与固定手势；profile 只覆盖其中约 25 秒。cd13 对照的 CRC／ramfs 同步调用链重新出现，已打印记录中占 1,803 个样本。cd14 RAM 轮的已打印热点没有这条调用链；刷入轮的 485 个样本全部输出。不同启动进度、缓存和持久化数据规模限制了整体性能归因，样本计数不能换算成耗时或持续帧率。

cd14 成功恢复 71,322 个 ANNFS 节点；随后 cd13 使用原软件 CRC 成功读回 cd14 写出的 73,734 个节点，没有记录 CRC 不匹配或元数据写入失败。该对照覆盖了新 CRC 生成结果与旧读取路径的兼容性。

cd14 出现 `siriactionsd` 的 `NSInvalidUnarchiveOperationException`，以及 `cameracaptured` 在 `MakeBlurMap` 初始化 `_modifyBlurmapGlasses` 时反复断言退出。相机对应原版 `modify_blurmap_glasses_apply`，此前宿主记录已确认其因 `llvm.maxnum.v4f16` 编译失败。Siri 异常原因原文含控制字符，尚未确定根因。控制中心下拉后已有连续显示完成，但收回操作后的截图仍显示控制中心，持续交互帧率未验收。

- cd14 内核 SHA-256：`6f023c357adfa8d6202a71f144d0c7f2ce39465ba048dbbbe247025aae4a0744`。
- 已刷完整镜像 SHA-256：`e2a8db900c864b7b9e73436ae2b4b08240b117c09a7adc15366618e228bb05e0`；XNUP SHA-256：`42592ab9b5213e383d9ab22c1dc6cf0b0780a952163dab857e6bd7411912dac8`。与第 21 节镜像逐条比较，仅内核内容变化。
- 刷入应答、正常 A 槽启动与运行库身份通过，Metal／AIR UUID 与第 21 节冻结文件相同。没有读取物理 `boot_a` 全分区校验哈希。
- 原始记录位于本地 `kernel-12377-codex-1112-cd14-crc-arm-runtime-profile/run/`、`kernel-12377-codex-1112-cd13-crc-control-profile/run/` 与 `codex-device-1111/standalone-crc-deploy/flashed-boot/`。

## 23. 相机眼镜景深着色器的 LLVM 指令

原生 `CCPortrait` 在 `0x2a0cf8464` 将 `modify_blurmap_glasses_apply` 的管线存到 `self + 0x118`，随后检查空值并进入 `MakeBlurMap.m:1227` 的断言路径。旧 AIR 对该着色器返回 `intrinsic: llvm.maxnum.v4f16`，与第 22 节相机进程退出的位置对应。

用户态提交 `2f126f2` 在 `air_llvm.inc` 增加 11 行，将 `llvm.minnum.*` 和 `llvm.maxnum.*` 映射到现有 `nir_fmin`／`nir_fmax`，保留元素位宽、向量形状和单 NaN 的数值返回语义。

- 418 个宿主数值分量检查通过，覆盖 f16／f32 标量与四分量向量、f64 标量、单／双 quiet NaN、无穷、正负零和半精度边界；旧实现拒绝首个新增用例。
- 原版眼镜景深着色器已通过 AIR → NIR → A830 IR3 编译，输出 15,616 字节。原版 `CCPortrait` 的 82 个模块中 79 个编译成功，原有 76 项全部保持成功；其余 3 项仍缺 `air.cospi.f16`。
- 独立 arm64e 构建与签名通过。与 P010 库的 37 项源码哈希比较，仅 `air_llvm.inc` 不同；辅助盘逐路径比较，仅 AIR 库内容及压缩属性变化。

候选 AIR SHA-256 为 `aa0dc8420a310545ec6cbe98377d66223f1c57f3399ca94648aaab056e449800`，UUID 为 `A1E7F4D6-1D95-3783-8602-07873F121FC0`；辅助盘 SHA-256 为 `f876a85ac6ac8eaf57e3ddab1da46372a23aa50a1f3c739ff4c87c5cd6ae34bc`。

首轮以 cd14 内核从 RAM 启动，运行 189.720 秒，17 项探针完成，最高 CPU 采样温度为 75.2°C。实际加载的 AIR／Metal UUID 与冻结文件一致，原生眼镜景深管线成功；SLM 两项管线与反射探针通过，NV12／P010 共 12 组色值检查仍为零错误，相机设备与格式枚举成功。软件收尾恢复新版 loader 空闲、空常驻区与真实 LK 重试 7；UFS 终态累计 82,785 次读取、错误为零。

相机随后在 `MPSImageUnaryKernel.mm:335` 的 `MPSImageAreaMin` 检查中因输入为空退出。失败前记录了格式 65 的 IOSurface 导入被拒，以及 `ci_affine_crop` 的空 `outputNode` 被 stitching 拒绝；另有 `_antialiasY` 初始化失败，对应尚未实现的 `air.cospi.f16`。这些结果尚未覆盖真实相机帧，后续分别核对像素布局、void stitching 图和剩余着色器指令，见[图形待办](../backlog/graphics.md)。

随后将新 AIR 完整镜像刷入 `boot_a` 并正常重启。该轮运行 185.967 秒，17 项探针完成，最高 CPU 采样温度为 74.8°C；SLM 两项、NV12／P010 的 12 组检查与原生眼镜景深管线继续成功，后续 MPS 空输入等失败与 RAM 轮一致。SpringBoard、backboardd 和相机进程的运行库身份与冻结文件匹配；收尾再次确认新版 loader 空闲、空常驻区与真实 LK 重试 7。

该轮固定操作后的截图已从控制中心返回桌面，应用和 Dock 图标可见；天气与日历大组件仍显示空白内容。完整持续动画和物理面板完成时刻尚未验收。

- 已刷镜像 SHA-256：`011337a785b33b4f8bb1f214809f5a22d8271af391abd6215a71342e64e2b104`；XNUP SHA-256：`aabad51f40aa99f9dd08bcc611d6d5b7bac6bf89b3280f87a20a1193369c353a`。与第 22 节镜像比较，仅辅助盘条目变化，内核、loader 和启动参数相同。
- 校验覆盖镜像容器、AVB、输入哈希、写入应答、正常重启与实际运行库身份；没有读取物理 `boot_a` 全分区校验哈希。
- 原始记录位于本地 `kernel-12377-codex-1112-cd14-minmax-air/run/` 与 `codex-device-1111/standalone-minmax-deploy/flashed-boot/`。

## 24. RG16Float 的 IOSurface 导入

SDK 将 Metal 格式 65 定义为 `RG16Float`，CoreVideo 的对应格式为 `TwoComponent16Half`（`2C0h`），每像素包含两个小端 half 分量，共 4 字节。AIR 后端已有 `PIPE_FORMAT_R16G16_FLOAT` 和对应纹理布局；`annibaledrawable.m` 的格式表缺少 65，导致 IOSurface 导入提前返回空值。

内核仓提交 `84371e30` 增加 65 → `2C0h`／4 字节映射，并在格式或几何不匹配的日志中记录实际 FourCC、行距、偏移和纹理尺寸。该改动沿用已有导入路径，未改变 IOSurface 原始字节或格式 94。

- 完整生产文件的宿主测试覆盖 17×5 尺寸、隐式／显式单平面、128／256 字节行距和 0／128 字节偏移。8 组 half 字节与布局检查、拒绝场景和 ASan／UBSan 检查通过；旧代码未通过新增用例。
- 独立构建冻结 30 项输入。旧源码重建的 dylib 与 bundle executable 均与原产物逐字节一致；候选仅更换 `annibaledrawable.m`，arm64e 编译与 Mach-O 签名检查通过。
- 独立 GPU 探针使用相同尺寸、行距和偏移，分别执行整数坐标读取与最近邻采样，再写回两个 half 分量。原生 Metal 的 8 组逐像素检查通过；将 shader 加数改错后，8 组均失败。行内 padding 单独统计；allocation 内的 prefix／suffix 按哨兵检查。
- 真机 A830 的 8 组读取／采样写回全部通过，逐像素错误为零，allocation 内的 prefix、行内 padding 和 suffix 均未变化。该探针覆盖单个隐式平面中的有限 half 数值，未验证 allocation 之外的访问。

候选 dylib SHA-256 为 `2694ad11ce74fdab8e5510809e9076c40f302c4f39b08d63f8538798cf2678da`，UUID 为 `C3285B36-66AC-3601-8E9E-AE38DF879068`；bundle executable SHA-256 为 `000271e32cfbfcea65fa90a1da58132c2ab0b6d6a14067348d7ff219945d3b39`，UUID 为 `BE308971-4917-30CC-AFC4-7EDFA9B71C9F`。构建与探针记录保存在本地 `codex-1112-rg16-metal/`、`codex-1112-rg16-isolated/` 和 `codex-1112-rg16-probe/`。

RAM 验证运行 195.100 秒，最高 CPU 采样温度为 77.1°C；随后完整镜像刷入并正常重启，验证运行 195.039 秒，最高采样温度为 75.2°C。两轮均完成 18 项探针，RG16 的 8 组逐像素检查、SLM 两项管线与反射、NV12／P010 共 12 组色值检查通过。实际加载的新 Metal 与固定 minmax AIR 身份一致；两轮收尾均确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。

- 相机实际导入了 `2C0h`，包括 380×380／1536 字节行距和 256×380／1024 字节行距。原 `MPSImageAreaMin` 空输入断言已消失，后续 `MaxFilter2HRadiusAboveLogCutoff` 管线创建与 GPU 命令完成。
- 当前相机因 `-[AnnibaleMetalHeap protectionOptions]` 未实现而抛出 `NSInvalidArgumentException`。另有进程内存包装 surface 的描述请求返回 `0xe00002c7`；132 像素宽、544 字节行距的纹理不满足 64 字节直接绑定要求，现有实现使用复制路径。这些路径的完整结果仍需分别验证。
- 两轮均使用底部中央上滑。RAM 轮的后续截图仍显示控制中心；刷入轮在主机命令返回后 3.496／4.447 秒的截图已显示桌面，天气与日历大组件仍空白。事件注入完成与界面完成分开记录，尚未确定稳定的交互计时终点。
- 已刷镜像 SHA-256：`8724cde9648c8fd48ba2ff6de4239d45e03d21a5bec9786fb2ee9996e31b7ec7`；辅助盘 SHA-256：`0617b7f4b989c1111814b7600ebe9f33c1f7b9829041206f12c3beb11a7bbc56`。内核、AIR、loader 和启动参数均保持第 23 节版本。
- 校验覆盖 APFS 逐路径差异、镜像容器、AVB、写入应答、正常重启与运行身份；没有读取物理 `boot_a` 全分区校验哈希。原始记录为本地 `kernel-12377-codex-1112-cd14-rg16-metal/run/` 与 `codex-device-1111/standalone-rg16-deploy/flashed-boot/`。

Core Image 的 `ci_affine_crop` 仍需单独实现 stitched compute。原生日志中的图包含 6 个节点、5 个函数和空输出，其中 `MTLFunctionStitchingEarlyReturnNode` 根据 `_ci_early_out` 的结果提前返回；后续节点依赖这次检查，最后执行 `_ci_write_pixel`。Apple 的 `outputNode` 接口允许空值，函数节点的 `controlDependencies` 规定副作用的执行顺序，见 [outputNode](https://developer.apple.com/documentation/metal/mtlfunctionstitchinggraph/outputnode) 与 [函数节点](https://developer.apple.com/documentation/metal/mtlfunctionstitchingfunctionnode)。

- iOS 26 Metal 的原生类元数据确认：纹理和采样器输入使用 `bindIndex`；buffer address 输入另有 `byteOffset`、`dereference`。这些类继承 `NSObject`，现有转换器只识别 `argumentIndex` 和函数节点引用，尚未覆盖这些输入。
- `pipelineForFunction:descriptor:error:` 要求函数提供 `bitcodeData`，随后直接调用 `mesa.compute_create`；当前入口没有接收计算图或生成对应的计算参数反射。
- 修复需同时保留资源绑定、条件提前返回、节点依赖与写纹理行为。现有日志深度未记录各输入的具体绑定索引和偏移，后续需结合原生调用与有界诊断补齐。静态记录位于本地 `codex-1112-ci-stitch/`。

## 25. cospi 指令与相机景深管线

用户态提交 `d3f0d9e` 实现 half／float 标量和向量的 `air.cospi`。计算先约简周期，再通过正弦求值；half 中间量使用 float，保留半整数处的零值与非有限输入的 NaN 分类，f64 明确拒绝。原版 `CCPortrait` 的 82 个模块全部通过 AIR → NIR → A830 IR3 编译，新增通过的三项为 `sparserendering_antialias_y`、`sparserendering_antialias_y_4chan` 和 `sparserendering_add_noise_only`。

- 260 项 AIR 集成检查通过。数值检查覆盖全部 65,536 个 half 编码及 16,384 个 float 边界／随机输入，与独立 double `__cospi` 比较，最大误差分别为 0.500062／1.35295 ULP；检查限值分别为 1／4 ULP。
- Apple GPU 对同一组 81,920 个输入的检查通过。它与宿主 NIR 结果的最大差异为 half 1 ULP、float 2 ULP；零值不检查符号，NaN 不检查 payload 和符号。
- 旧实现拒绝 cospi；直接使用 half 乘以 π 的变体在输入 `0.203125` 超过 1 ULP，检查失败。
- 独立构建比较 14,289 个输入文件，仅 `air_intrinsics.c` 与新增的 `air_math_private.h` 不同。完整 `check.sh` 因默认 `mesa-host` 构建缺失而未执行，上述检查使用隔离的宿主工具完成。

候选 AIR SHA-256 为 `5779c260d79fdda1dc9a13feb55eeb360c21a295a6d14d1ab4914b763c3eca94`，UUID 为 `79A4E537-13FD-33EE-A0CB-2301DA3F4B36`。构建、原版模块与数值记录保存在本地 `codex-1112-cospi/`。

首次 A830 数值探针在 179 ms 后退出 134，Metal 收到空 compute function 并断言；尚未执行数值比较和三条原版管线检查。该轮运行 89.622 秒，完成计划中的 7／19 项，最高 CPU 采样温度为 75.6°C。收尾确认新版 loader 空闲、常驻区为空及真实 LK 重试 7，已部署的 RG16 镜像保持不变。

测试 metallib 的默认目标为 `air64_v29-apple-ios27.1.0`，高于设备 iOS 26.6.2。兼容探针显式使用 `air64_v25-apple-ios16.5.0`／Metal 3.0；提交 `435a0d7` 在创建管线前检查库与函数，失败输出具体阶段并返回 2。兼容探针已在 A830 完成加载和执行；原轮未保留库加载的 NSError。

- 新测试库的 Apple GPU 81,920 项数值检查通过，生成的 A830 IR3 与旧测试库逐字节一致；无效库及缺少 `check` 入口分别返回 2。
- v3 辅助盘相对 v2 仅更换 `/tests/cpi` 和 `/tests/cpi.metallib`，生产 AIR、Metal、内核和启动参数均相同。APFS 逐路径读回、完整镜像容器与 AVB 检查通过。
- 原始记录为本地 `kernel-12377-codex-1112-cd14-cospi-air-v2/run/`、`codex-1112-cospi-probe-v3/` 和 `codex-1112-cospi-root-v3/`。

v3 真机轮确认后端为 A830。数值探针在第 65,541 个下标处失败，即全部 half 输入与前五个 float 输入检查通过，第六个 float 超出 4 ULP 限制。管线和 GPU 命令已完成，数值结果尚未验收。

| 首个失败输入与输出 | 值 |
|---|---|
| float 输入 | `-0x1.fbfffep+5`（`-63.499996185302734`） |
| 宿主 NIR | `-0x1.921fb6p-17`，与 double 参考相差约 0.367 ULP |
| A830 输出 | `-0x1.8ffffep-17`，与 double 参考相差约 69,595.633 ULP |
| 返回值与执行范围 | 87 ms 后返回 1；探针内的三条原版管线检查尚未执行 |

本轮相机自身已创建上述三条原版 cospi 管线；数值失败后的提前收尾没有观察到相机终止异常，也没有验证真实相机帧。该轮运行 90.184 秒，完成 7／19 项，最高 CPU 采样温度为 75.2°C；收尾确认新版 loader 空闲、常驻区为空与真实 LK 重试 7。已部署镜像仍为 RG16，后续独立功能测试使用已验收的 minmax AIR，cospi 继续检查 A830 三角函数指令与编译过程。记录位于本地 `kernel-12377-codex-1112-cd14-cospi-air-v3/run/`。

冻结 Mesa 的 `ir3_nir_trig.py` 将正弦参数再次归一化；实际 IR3 使用非融合 `mad.f32`，两次舍入将上述角度量化为 `-0x1.9p-17`，硬件正弦输出与真机首错吻合。用户态提交 `a3a9261` 在 cospi 已约简的区间内使用 13 次奇多项式，保留逐次 float32 运算，原 half 1／float 4 ULP 限制不变。

- 实际 IR3 不含正弦指令，六个系数与源码的 float32 值一致。按非融合运算检查全部 16,777,217 个非负约简格点及负值对称性，最大误差为 2.03712 ULP。
- 原 81,920 个输入经过 IR3 三角函数转换后，half／float 最大误差分别为 0.499938／1.71412 ULP；旧实现在相同首错输入复现精度失败。260 项 AIR 集成检查与三条原版模块的 A830 编译通过。
- 新探针最多打印八条数值错误，随后输出两种位宽的失败总数，再检查三条原版管线；总 deadline 仍为 30 秒。错误输出着色器触发全部预期失败，最终返回 1。
- 新 AIR SHA-256 为 `154d0a130833a6ee31d36a2068ed5647962b3e583ca4d4169887e3fb23fc81f9`。相对首版 cospi 的冻结输入仅 `air_math_private.h` 不同；候选基于第 26 节已通过的 heap 辅助盘。完整记录位于本地 `codex-1112-cospi-precise/`。

精度修复的 A830 RAM 轮完成全部 81,920 个输入比较，half／float 失败数均为零。相对 double `__cospi` 参考的最大误差分别为 0.000231537／1.71412 ULP；相对宿主 NIR 结果的最大差异分别为 0.499878／0 ULP。三条原版景深管线均创建成功，探针没有提交它们的实际资源执行。该探针在 175 ms 后返回 0。

- 20 项设备命令按预期返回，另完成一次桌面截图步骤；RG16、SLM、NV12／P010 与 G2 正反对照保持预期结果。13 条运行库记录匹配冻结的 heap Metal 与新 AIR。
- 最高 CPU 采样温度为 74.8°C；收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。
- 实际查看完整图和原尺寸局部，应用与 Dock 图标、天气和日历组件内容均缺失，壁纸、标签、状态栏和时钟指针仍可见。三个启动后的截图均有该异常，数值检查通过后仍未通过视觉验收。
- 相机仍在格式 25 导入后发生 MPS 空 source 断言，`ci_affine_crop` 图也仍被拒。当前保持已部署的 heap／minmax 镜像，cospi 候选继续排查桌面图标缺失。
- 原始记录为本地 `kernel-12377-codex-1112-cd14-cospi-precise/run/`，该轮桌面稳定图接收于 03:08:01.980（UTC+8）。截图读取边界见第 27 节。

## 26. 普通 Metal heap 的保护属性

原生 MPSCore 会查询 heap 的 `protectionOptions` 并与请求值比较；iOS 26 的 `MTLIOAccelHeap` 将查询转发给资源，普通资源没有保护对象时返回 0。描述符初始化也将该属性清零。内核仓提交 `102637dc` 为普通 heap 返回 0；描述符请求非零保护选项则在分配前拒绝构造。

- 完整生产 heap 文件的宿主检查使用原生 Metal 描述符，覆盖普通 heap／buffer／texture 的属性、资源归属及计数释放；四种非零保护请求均被拒绝。旧实现缺少 getter、删除拒绝分支的变体分别未通过检查。
- 独立构建冻结 RG16 的 30 项输入，基线两份 Metal 产物均与已验收版本逐字节一致；候选只更换 `annibalemetal_heap.inc`，arm64e 构建与签名检查通过。
- 宿主 fixture 替换了私有父类，并将资源分配交给原生 Metal。A830 上 MPSCore 的实际调用由下述真机轮检查。

候选 dylib SHA-256 为 `f61f38edf80eab1c32876a107ce32ac1ea7e81bea63a118440aa5bad827024be`，UUID 为 `7CBC54BC-20E5-34D7-A54C-A4A0269595A8`；bundle executable SHA-256 为 `5cee1b4e353ea166bbca4c72e83eaae17c80729e8c394bcf332e40810d5902de`，UUID 为 `1978DE94-43C6-380F-A5D9-42153B8E9370`。原生反汇编与构建记录保存在本地 `codex-1112-heap/` 和 `codex-1112-heap-protection/`。

heap 候选基于已验收的 RG16／minmax 辅助盘，只更换两份 Metal 库，并增加 G2 双附件探针。RAM 验证运行 196.699 秒，18 项回归和 G2 两项对照全部完成，最高 CPU 采样温度为 74.8°C。收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。

- 相机不再抛出 `protectionOptions` 缺方法异常；后续创建 2 MiB heap，并执行 `MinFilter2Radius1`、`MaxFilter2Radius1` 管线。
- 下一处失败前连续记录 Metal 格式 25 导入被拒，随后 `MPSImageAreaMin` 因空 source 断言。SDK 将 25 定义为 `R16Float`，CoreVideo 对应 `OneComponent16Half`（`L00h`），每像素 2 字节。原拒绝位置尚未读取实际 surface 的 FourCC 和尺寸。
- G2 双附件正确组 8／8 通过，3,072 像素零错误，返回 0；错误 DATA1 对照的 8 组各检出 63 个错误，返回 1。实际后端为 A830，混合、其他格式与 TBDR 路径仍按[渲染专题 §9](2026-11-12-rendering-runtime.md#9-g2-双附件-framebuffer-fetch)的边界验收。
- 辅助盘 SHA-256：`d2c0fb68d8798ecb2a8ead0fd6a08c878e23834cf3319b77e04ff60840589d16`。原始记录为本地 `kernel-12377-codex-1112-cd14-heap-metal/run/`。

随后将 heap 完整镜像刷入 `boot_a` 并正常重启，最高 CPU 采样温度为 74.8°C。19 项设备命令均按预期返回，另一个视觉步骤因缺少场景确认而未完成；视觉结果见第 27 节。收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。

- SpringBoard 与 backboardd 实际加载的 Metal bundle／AIR UUID 与本节 heap 库和第 23 节 minmax 库一致，实际后端为 A830。
- 已刷完整镜像 SHA-256：`ff15ced4001981ebdded8e0401013fc10faed70291b5cd9ff341ee665906ec77`；XNUP SHA-256：`c579d516e320bf1143f0985ab54f9e404b06a23e2b2e88c353b3c9f70a85430e`。
- 校验覆盖镜像输入、写入应答、正常启动和运行库身份；没有读取物理 `boot_a` 全分区校验哈希。原始记录为本地 `codex-device-1111/standalone-heap-deploy/flashed-boot/`。

内核仓提交 `cd6555e0` 为格式 25 增加 `L00h`／2 字节映射，复用已有单平面导入与后端 `PIPE_FORMAT_R16_FLOAT`。R16 与 RG16 各 8 组完整生产文件的宿主布局、原生 Metal half 读写及拒绝检查通过，ASan／UBSan 未报告问题；旧实现保持 RG16 通过，在新增 R16 映射处失败。真机结果与实际相机 FourCC 的差异见第 28 节。

## 27. heap 轮的实际界面检查

本轮由两名 agent 实际查看完整 1156×2510 截图与原像素组件局部。桌面截图完成接收于 11 月 12 日 02:39:24.902（UTC+8）；该时刻对应主机观察，截图传输约 0.311 秒。

- 天气组件为整块浅白圆角矩形，内部没有天气图形或文字。
- 日历组件顶部与底部为浅白色块，中间矩形区域直接露出壁纸，内部没有日期内容。
- 应用图标、Dock 图标及标签可见。控制中心下拉后的两张图确实显示控制中心；底部上滑后的两张图仍显示控制中心，未确认恢复桌面。
- 本轮没有进入多任务场景，任务卡片的渲染状态尚未检查。

截图来源是 loader 对 `SCREEN.base` 的分块传输，没有冻结副本；动态更新期间可能跨帧读取，本轮尚未确认是否发生，也未覆盖物理面板扫描。完整图、原尺寸局部、五张截图的实际接收时刻与触摸时间窗均保存在上述本地轮目录。视觉检查与后续性能对照的采样范围按[真机手册 §7.1](../plan/device-test-playbook.md#71-图像审阅与短暂异常)记录。

heap 完整镜像正常启动后，再次实际查看完整图和原尺寸组件局部：

- 02:54:11.810（UTC+8）的桌面图中，天气与日历均为上下浅白色块、中间露出壁纸，应用和 Dock 图标及标签可见。
- 原视觉脚本等待桌面确认 25 秒后结束，记录 `complete=false`、`scene_confirmation_missing`，未发出后续手势。该步骤返回 0，原汇总计入了完成项，不能据此判定视觉通过。
- 同一运行器随后串行点击设置。02:55:33.149 的稳定截图显示黑色背景、缩小且变暗的桌面图标与组件，底部有手势条，没有设置界面。两组件均为整块灰色，内容仍缺失。
- 设置前台状态未确认，因此没有继续上滑、横滑或点击任务卡片；本轮仍未覆盖多任务渲染。后续按[前台切换诊断](../plan/2026-11-12-app-foreground.md)关联进程、scene 和实际画面。

上述时刻均为主机接收记录。完整图、原尺寸局部和视觉状态保存在本地 `codex-device-1111/standalone-heap-deploy/flashed-boot/run/`。

后续独立脚本将场景覆盖、可见异常与 loader 恢复分别汇总。缺少确认、拒绝确认、解码超时、缺失或损坏的结果、部分场景、图号不匹配和完整场景仍有异常的离线检查通过；视觉未通过后批次返回失败，同时保留设备恢复状态。旧轮重新判定为视觉未完成、设备可继续测试，修正结果已关联到该轮完成摘要，原始记录保留。

## 28. R16Float 探针与相机实际 FourCC

R16 独立候选基于 heap／minmax 辅助盘，只替换两份 Metal 库并加入探针。A830 的 8 组读取／采样全部通过，覆盖 128／256 字节行距和 0／128 字节偏移；像素错误与 prefix、padding、suffix 的意外变化均为零。探针在 266 ms 后返回 0。

- 20 项设备命令按预期返回，另外完成前后两次桌面截图；RG16、SLM、NV12／P010 与 G2 正反对照保持预期结果。12 条运行库记录匹配 R16 Metal 与固定 minmax AIR。
- 最高 CPU 采样温度为 73.3°C；收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。
- 两张相隔 31.647 秒的截图中，应用和 Dock 图标均可见；天气仍为整块浅白，日历仍为上下浅白、中间露出壁纸。完整图与原尺寸组件局部均已实际查看。
- 辅助盘 SHA-256：`bc8deac8c5f525bc15738b466d2f2d28cab38f55e33e4dd3c3a83a8179a65845`；RAM SHA-256：`d1ac3bb193795a316fb72d85b55a3a823524ad759f12b6c868287506792c4785`。原始记录为本地 `kernel-12377-codex-1112-cd14-r16-metal/run/`。

相机仍因 `MPSImageAreaMin` 的空 source 断言退出。此次日志记录了实际 surface FourCC `1C0h`（`0x31433068`），导入器要求 `L00h`（`0x4c303068`），因此拒绝了 10 次导入。每像素均为 2 字节，三种几何如下；下一步核对 CoreImage 的原生格式转换及 `1C0h` 导入契约。

| 尺寸 | 行距 | 偏移 | allocation |
|---|---|---|---|
| 380×380 | 768 字节 | 0 | 294,912 字节 |
| 128×128 | 256 字节 | 0 | 32,768 字节 |
| 256×380 | 512 字节 | 0 | 196,608 字节 |

内核仓 `e09aed95` 仅为 Metal 25 接受 `1C0h` 别名，保留 canonical `L00h` 与所有布局检查。iOS 26 CoreImage 的正反转换确认 `kCIFormatRh`（`0x805`）对应 `1C0h`，纹理创建选择 Metal 25。完整生产导入器的 48 组检查、原生 GPU 的 22 组读取／采样通过，其中包含上表三种相机布局；旧实现与放宽 Metal 格式限制的变体均失败。

A830 RAM 轮的 22 组读取／采样全部通过，其中 `L00h` 8 组、`1C0h` 14 组，像素与 prefix、padding、suffix 的意外变化均为零；探针在 247 ms 后返回 0。

- 20 项设备命令按预期返回，另完成前后两次截图。RG16 8／8、SLM 2／2、NV12／P010 各 6／6 和 G2 正反对照保持预期结果，16 个进程实例的 Metal／AIR UUID 匹配候选。
- 相机实际 `1C0h` 的 380×380、256×380、256×256、128×128 导入成功，FourCC mismatch 与 `MPSImageAreaMin` 空 source 断言均未出现。相机随后在 `mps_stgf_computeInvertedGuideCovarianceMatrix3` 编译处因二维数组 builtin read sampler 签名被拒而退出，修复见第 33 节。
- 仍有两次 process-owned memory 的 surface 描述失败，以及两个进程的 CI affine crop 错误；这些调用分别继续定位。
- 实际查看完整桌面图和原尺寸局部，图标可见，天气仍为整块浅白，日历仍为上下浅白、中间露出壁纸。
- 最高 CPU 采样温度为 75.2°C，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。原始记录为本地 `kernel-12377-codex-1112-cd14-r16-alias/run/`。

## 29. Core Image stitched compute

用户态 `086926d` 与内核仓 `02d9217f` 增加 GraphSPI 计算图创建路径，复用现有 compute 的生命周期与 NIR 完成处理。图转换保留资源绑定、buffer 偏移和解引用、grid 输入、条件提前返回及节点依赖；原有 visible function 图的结构布局保持一致。

- 原版 `ci_affine_crop` 的五个函数、六个节点经原生 GPU 执行，128 个分量零错误，纹理索引为 1、采样器索引为 5。软件数值检查使用相同索引绑定纹理与采样器，受 softpipe 的 TGSI 表达限制；A830 IR3 编译单独验证 1／5 绑定。
- 原生 GraphSPI 的 opaque constant buffer 反射为 `None`／size 0／alignment 4；12 个 pointer／value 类型用例与原版 CI 图均匹配。驱动只接受该空 constant buffer 形状，访问模式按 SDK 数值保留。
- 去掉 EarlyReturn、忽略 byteOffset、交换访问模式、恢复旧 opaque 转换及使用错误 alignment 的变体均未通过对应检查。跨节点 API sampler 绑定预留于 constexpr sampler 分配之前，scratch 大小先以 64 位计算再检查边界。
- 原始基线 AIR 和 heap Metal 两库重建逐字节一致。独立候选没有包含 cospi 或 R16；候选 AIR UUID 为 `28000AF1-1B24-3E65-98EE-B56E75DDF140`，Metal bundle UUID 为 `8B573294-9EDF-3A6D-B359-D96F575AC606`。
- 隔离 Linux 的 18 阶段 AIR 检查退出码及关键计数与既有基线一致，没有新增失败；完整检查仍返回 1。已有失败包括 reader 的 304 处差异、旧 clang 的 FMA／argbuf 参考解析、部分 min／max／clamp 软件数值、blend 拒绝、lowering、旧 framebuffer fetch 规则及 phi 检查。最终 GraphSPI 反射修正另由宿主重编与原生对照验证，详细范围保存在 `legacy-check-review.json`。

A830 的原版 CI 图探针在 160 ms 后返回 0，命令状态为 4，128 个分量零错误；纹理 1、采样器 5、六节点和五函数均与原生参考一致。实际查看前后完整桌面图与原尺寸组件局部，两张相隔 28.579 秒的图都缺少应用、Dock 图标与组件内容，壁纸、标签、状态栏和时钟指针仍可见，候选未通过视觉验收。

- 20 项设备命令按预期返回，另完成前后两次桌面截图；19 条运行身份与冻结库匹配。最高 CPU 采样温度为 74.0°C；收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。
- 相机已创建 `ci_affine_crop` 和 `ci_affine_swizzle_rgb1` stitched library，随后在 compute pipeline 创建前抛出 `NSProxy doesNotRecognizeSelector:setLabel:` 异常，共记录三次。该异常继续核对函数对象的 label 契约。

保持上述 CI payload、辅助盘和 AIR 完全一致的暖缓存对照中，应用与 Dock 图标恢复可见，组件异常保留。原版 CI 图的 128 个分量再次通过，19 条运行 UUID 匹配；相机仍记录两条 `setLabel:` 异常。20 项设备命令按预期返回，另完成两张截图，最高 CPU 采样温度为 72.9°C，loader 空闲、常驻区为空和真实 LK 重试 7 均通过。

暖缓存对照确认同一 CI 产物在后续启动中可以显示图标，初次缺失的原因仍需检查。完整图与原尺寸局部均已实际查看，缓存计数及图形分析由[图标专题](2026-11-12-air-icon-regression.md)维护，本地原始记录为 `kernel-12377-codex-1112-cd14-ci-warm/`。相机函数对象的 label 修复见第 31 节。

候选构建记录在本地 `codex-1112-ci-stitch/`，真机记录在 `kernel-12377-codex-1112-cd14-ci-stitch/run/`。AIR SHA-256 为 `345ab358d36205ce673df1d86a50767f98117a454094717fb4a5efe0fc6f46b0`，辅助盘 SHA-256 为 `c987b2ef93de120a6480f9110c4e367cbfb818bdb4c56ac44c0dcd5bf2e7227b`。

## 30. Iris 固件错误诊断

原实现直接丢弃 debug ring 的已发布内容，仅在该队列非空时读取 SFR，session error 分支也未采集这两项。原厂 `__flush_debug_queue` 检查消息长度并从 `0x11` 偏移读取文本；原厂队列读取先复制完整消息，再发布 `read_idx`。

内核仓 `609ec21b` 保留上述顺序，每次最多读取 16 条完整消息，检查长度、word 对齐、队列索引、环绕和已发布数据量。SFR 独立读取，长度受声明值与实际 allocation 双重约束；INIT／session error 均触发采集。文本按 240 字节分段输出，4 KiB scratch 由已有 `iris_lock` 保护，诊断函数栈占用为 176 字节。

- 完整生产代码的 31 个 ASan／UBSan 场景与 14 个保护或顺序变体检查通过；旧实现的完整消息、空队列 SFR、session error 三项失败。既有 INIT 50 例、HFI／session 100 例和生命周期回归保持通过。
- cd14 独立完整复链与已验收内核逐字节一致；候选主链接的 1,162 个对象仅 HFI 对象不同，193 份源文件也仅 HFI C 文件变化。RAM 保留 heap／minmax 辅助盘、启动参数和 resident，读回仅 kernel 条目变化。
- 候选内核 SHA-256 为 `26f1283146b8fffa159d709a033df557327c3a163e41dbec5e2878d8c77ae520`，本地构建记录在 `codex-1112-iris-debug/`。

cd15 真机单次 H.264 请求提交 4,909 字节后仍收到 `0x4000003` session error，回调为 `-12909`，submitted／callback 各 1、frames 为 0，探针在 417 ms 后返回 1。SFR 只有 `Init SFR msg, NOT an error`，没有 debug 消息正文；STOP 后 PAS 9 关闭，DMA 资源继续保留至复位。

- 本轮 22 个步骤包含 19 条预期退出命令、1 条硬解失败命令和 2 次截图；功能失败由该硬解请求触发。
- 最高 CPU 采样温度为 72.9°C，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。原始记录为本地 `kernel-12377-codex-1112-cd15-iris-debug/run/`。
- cd16 独立诊断候选在 OPEN 前按原厂设置 `DEBUG_CONFIG=0` 与 `DEBUG_LOG_LEVEL=0x18`，其余 HFI 行为保持 cd15。100 个 HFI／session ASan／UBSan 用例通过，旧版、错误 mask 和错误 payload 变体均失败。

cd16 真机取得首条具体 fatal：`h264DecCalcBufReq(1944): num of col buffer not enough. host 8 < fw 18`，随后记录 `HFI_ERROR_FATAL - vfw_h264_main.c:1948`。submitted／callback 各 1，回调为 `-12909`、frames 为 0；错误发生于 START ACK／PSC 之前。原始记录为本地 `kernel-12377-codex-1112-cd16-iris-fw-log/run/returned-held.log`。

本轮 19 条命令按预期退出，另有一次硬解失败和两次截图。最高 CPU 采样温度为 76.8°C，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。

原厂以输出 buffer 的 `min_count` 同时计算 COMV 字节数并发送 HFI `0x03000193`，当前实现两处固定为 8。进一步反汇编确认原厂首次输入 PSC 订阅后发送 `0x03000124`，其值取自输出 `min_count`；AVC／HEVC 初值为 4，HFI 端口为 bitstream、载荷为 U32。当前实现遗漏了这条初始属性。

cd18 单变量候选只补输入订阅后的 `0x03000124=4`，COMV 仍为 8，其他初始属性、STAGE／PIPE 和后续 PSC 行为保持原样。cd16 独立重链逐字节一致，候选仅 HFI 对象变化。原厂 setter 表、指令字节与交付保存在本地 `codex-1112-iris-input-min/`。

cd18 首次收到 input START ACK，原 COMV fatal 与 session fatal 均未出现。该单变量结果支持初始数量属性缺失导致此前启动错误。输入提交 4,909 字节后仍未收到 PSC、输入或输出 BUFFER 返回；探针在 1,616 ms 后返回 1，frames／output_bytes 均为 0。

- START ACK 对应的命令队列读写位置均为 420。后续 DRAIN 与两次 STOP 将写入位置推进到 436、452、468，读取位置仍为 420；驱动保留 DMA，复位后才完成设备收尾。
- 本轮 19 条命令按预期返回，另有一次硬解失败和两次截图。最高 CPU 采样温度为 74.0°C，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。
- 内核仓 `5ab0eead` 落实四行初始属性补发。100 项 HFI／session ASan／UBSan 检查通过，45 个负例均检出，其中本次新增的六类报文错误分别覆盖 AVC 与 HEVC。
- 真机记录在本地 `kernel-12377-codex-1112-cd18-iris-input-min/run/iris-input-min-review.json`，后续静态核对在 `codex-1112-iris-input-min-production/`。同一首样本经生产 Annex B 转换函数构造后可由 FFmpeg 解出 320×192 单帧；真机 DMA 内容尚未读回。

原厂的 320×192 H.264 初次启动还会发送 PIPE 4、STAGE 1；当前实现尚未设置，两项与 fatal 的因果关系仍待确认。该属性差异与 COMV 容量分别验证，硬解码首帧与实际像素继续待验。

## 31. Stitched function 的 label 契约

原生 CoreImage 在 `newFunction` 后调用 `setLabel:`；`AnnibaleMetalStitchedFunction` 继承 `NSProxy`，缺少该方法会在 compute pipeline 创建前终止相机进程。内核仓 `28af965e` 增加 nullable／copy／atomic 的 label 存储、释放与 `respondsToSelector:`，用户态 `973056e` 为原版 CI 图探针加入对应检查。

- 原生 Metal 的 copy、nil、自赋值、重复设置与 getter 对照通过；完整生产类的 ASan／UBSan 检查通过，旧实现和破坏 copy／释放语义的变体均失败。
- 原生 GPU 的 CI 图 128 个分量保持正确。隔离候选只更换两份 Metal 库与探针，AIR 仍为第 29 节的 `345ab358`，内核、resident 和启动参数保持一致。
- 辅助盘 SHA-256 为 `64416a0d5b7fe442f1b85b5b50a9ae3d3ffe1a2cea6470f0cd70cced79fddee2`，RAM SHA-256 为 `99ce22c6ae81ea9906ccb8fe72c518958b7cbce868d189f79b91d6f33e47894f`。本地交付位于 `codex-1112-ci-label-root/`。

A830 真机的 copy／自赋值／重复设置／nil 检查与原版 CI 图 128 个分量全部通过，探针在 179 ms 后返回 0。20 条设备命令按预期返回，另完成两次截图，19 条运行库 UUID 匹配。最高 CPU 采样温度为 73.6°C，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。

- 两个相机进程均创建 `ci_affine_crop` 与 `ci_affine_swizzle_rgb1` 管线，`setLabel:` 异常消失。随后格式 65 的 process-owned IOSurface describe 返回 `0xe00002c7`，CI dispatch 报纹理 1 缺失，继续核对该内存类型的导入。
- 该候选固定使用 heap／RG16 输入，未包含第 28 节 R16 修复；两个相机进程最后均因格式 25 导入失败，触发 MPS 空 source 断言。
- 两张相隔 25.126 秒的完整图与原尺寸组件局部已实际查看：应用和 Dock 图标可见，天气为整块浅白，日历为上下浅白、中间露出壁纸，组件内容仍缺失。
- 原始记录为本地 `kernel-12377-codex-1112-cd14-ci-label/run/`，相机调用、运行身份和实际图像检查分别保存在 `camera-ci-analysis.json`、`runtime-identities.json` 和 `root-visual-review.json`。

## 32. 冷启动音频的阶段与排空诊断

用户态 `57cb751` 为 `sound_test` 增加可选前置 `--deadline`、单调时间分段、成功 Enqueue 计数、异步 Stop 后的 `IsRunning` 检查与 Dispose 返回检查，原 STEP 语法保持可用。内核仓 `fef4ad25` 使用已有 feeder 状态输出排空摘要，功放配置、发送、保护与增益保持原实现。

- 生产测试函数的 15 项检查、生产 feeder 的 4 项检查及原 transport／intents 回归通过；旧源码未通过新增检查。
- 冻结候选在同次冷启动内运行两个新进程，每次执行 `activate route level 0 tone 3`，每个进程内复用同一 AVAudioSession。每次生成 144,000 帧 48 kHz／s16／stereo 零幅 PCM，随后观察 8 秒排空，音频之前只采集进程状态。
- 验收分别检查 Speaker 路由、全部 Enqueue 成功、accepted／wanted 均为 144,000、Stop／Dispose 成功、`IsRunning=0`，以及 DSP 的 `sent == done`、backlog／inflight／completion_error 为零。DSP 计数为共享累积 period，不能据此推算探针独占的帧数。
- 本地交付位于 `codex-1112-audio-cold/`，真机结果保存在 `kernel-12377-codex-1112-cd16-audio-cold/run/` 的 `audio-review.json` 与 `audio-attempt-timing.json`。

冷启动与同启动的新进程重复均通过零幅 PCM 传输检查，各 36 次 Enqueue 成功并接受 144,000 帧，Stop／Dispose 成功、`IsRunning=0`。两次结束后的独立排空窗口分别记录 sent／done 为 290／290、888／888，backlog、inflight、completion_error 均为零。

| 阶段 | 冷启动首次 | 新进程重复 |
|---|---|---|
| 命令总耗时 | 9,239 ms | 3,968 ms |
| activate 总耗时 | 3,613.854 ms | 593.712 ms |
| category 调用前 | 3,555.742 ms | 587.646 ms |
| AudioQueue 创建 | 2,089.717 ms | 231.421 ms |
| Stop 至观察到停止 | 257.246 ms | 258.802 ms |

category 之前的区间包含 `sharedInstance` 和符号／API 查找，当前采样尚不能进一步归属。该 AudioQueue 探针没有复现此前 AVPlayer／Safari 的 CoreMedia XPC 超时，后续继续独立检查播放器冷启动。

- HAL 在首条音频命令前已打开设备；`audiomxd` 在前、中、后三份快照保持 PID 70，已审日志未见音频服务崩溃、PCM 错误或 XPC 超时。`airplayd` 未出现在这些快照中，直接 MachServices 运行注册记录缺失；包内配置与实际会话响应分别记录。
- 两次 route type／UID 均为 Speaker。friendly name 的输出逐字节等于「扬声器」UTF-8 清除最高位后的结果；XNU `bsd/dev/arm/km.c` 的 `kmoutput` 执行 `& 0x7f`，与控制字节来源一致。getter ABI 与探针字符串使用已核对，AVOutputDevice ID 为 nil 的原生属性含义继续待核。
- 本轮 22 条命令按预期返回，另完成两次截图，8 份运行 Metal／AIR UUID 匹配冻结库；HAL 与探针自身仅完成包内 UUID 核对。最高 CPU 采样温度为 74.8°C，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。
- 实际听音、左右声道、真实录音和网页播放继续分别待验。本地零幅 AVPlayer 播放结果见第 35 节。

## 33. MPS 二维纹理数组读取

原版 `mps_stgf_computeInvertedGuideCovarianceMatrix3` 使用 builtin read sampler 读取二维数组，guideStack 的 access 为 0，mean 的 access 为 1。AIR 前端原来只接受普通二维纹理的七操作数签名；数组形式增加 layer 操作数，导致第 28 节相机编译失败。

用户态 `c6a1cdc` 扩展已有 read sampler 分支，按数组形式调整 offset、lod 与 access 的位置，检查 layer 为 i16 或 i32，并复用 `tex_coord_and_layer` 与 txf。原生 i16 重载同时使用 i16 坐标、layer 和 lod；非零 offset、非法 access、layer 类型及原有 image／depth／MS 限制继续检查。

- 原版 MPS 函数及五个 fixture 均通过 NIR 与 A830 IR3 编译。fixture 覆盖 float read32／sample32／read16、half read32 和普通二维回归，使用三层、三个 mip 及动态坐标、layer、lod。
- Apple GPU 的 2,184 个分量全部正确；强制 layer 0 的变体产生 672 个错误。旧前端拒绝四个数组 fixture，普通二维用例仍通过，三种坏签名在预期检查处拒绝；共 36 项检查通过。
- arm64e 基线重建与已验收 minmax AIR 逐字节一致，候选源文件只改变 `air_texture.inc`。新 AIR SHA-256 为 `024d7857b39dc62b9160e3c1fbc85b30b73746900ba4522048c111b5689bd316`，UUID 为 `8473C785-B244-3DB1-999C-EAF072473612`。
- RAM 基于已验 R16 alias 辅助盘，仅替换 AIR 并增加数组探针，Metal、内核、resident 和启动参数固定。宿主记录在 `codex-1112-mps-read/`，交付在 `codex-1112-mps-array-root/`。
- 本轮冻结源码的完整 AIR 回归共 18 个阶段，退出状态、失败项与计数均与既有基线一致；总退出码仍为 1。当前工作树另行完成完整前端编译及 16 项数组／原版 MPS NIR、IR3、负例和反射检查；组合源码尚未上机。

A830 的五个用例全部完成，状态均为 4，2,184 个分量零错误，探针在 397 ms 后返回 0。相机成功创建 `mps_stgf_computeInvertedGuideCovarianceMatrix3` 与 `mps_stgf_computeCoefficients3`，随后在 `mps_stgf_applyCoefficients3_2d` 的另一个变体创建中失败。

- 提取原版函数后确认 destination 使用 `air.read_write`，读取签名携带 builtin sampler 与 access 3。当前前端仍拒绝该 image 签名，宿主已复现；该问题独立修复。
- 本轮 25 条命令按预期返回，另完成两次截图。最高 CPU 采样温度为 72.5°C，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。
- 两张相隔 27.902 秒的完整桌面与原尺寸组件局部均已实际查看：应用和 Dock 图标可见，天气为整块浅白，日历为上下浅白、中间露出壁纸，组件内容仍缺失。
- 原始记录为本地 `kernel-12377-codex-1112-cd14-mps-array/run/`，数值与相机后续检查保存在 `root-mps-review.json`。原版 read_write 函数及宿主复现保存在 `codex-1112-mps-apply/`。

## 34. 本机 CSID 与 VFE 寄存器核对

本机原厂 `camera.ko` 保留 lite980／lite98x 寄存器表，可与 [SM8750 相机源码的固定版本](https://github.com/OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8750/tree/d50b305f7da9e14715a25120a4ac7b1a4b8b97c3/vendor/qcom/opensource/camera-kernel/drivers/cam_isp/isp_hw_mgr/isp_hw)逐项比较。原始表、函数反汇编和来源哈希保存在本地 `codex-1112-camera-native/`。

| 寄存器 | 相对 `0x0ad6d000` 的偏移 |
|---|---|
| CSID HW version | `0x0000` |
| VFE top HW version | `0x1000` |
| VFE bus HW version | `0x1200` |
| CSI2 CFG0／CFG1 | `0x0200`／`0x0204` |
| RDI0 CFG0／CFG1／CTRL | `0x0500`／`0x0504`／`0x0508` |
| VFE RDI0 image_addr／frame_incr | `0x1704`／`0x1708` |

内核仓 `8b3ad685` 将 `annibale_camera_hw.inc` 的 VFE 版本读取偏移由 `0x0a00` 修正为 `0x1000`。相机翻译单元独立编译通过，诊断与修改前一致；实际版本值待真机回读。该改动只修正版本读取，sensor streaming 与 CSI／IFE DMA 仍未实现。

- 原厂 expanded-memory 分支将 DMA 地址右移 8 位写入 `image_addr`，低 8 位写入 `addr_cfg`，`frame_incr` 同样右移 8 位。该分支由内存模式状态选择，当前 SMMU bypass 配置尚未确认对应的硬件地址模式。
- 原厂 WM 启动先设置 packer、可选 prefetch 与 context，再写 enable；`stop_wm` 清除 cfg 并复位软件状态，该函数内没有 DMA 完成轮询。资源释放仍需核对外围停止流程。
- 当前 8 MiB 帧缓冲使用 `kmem_alloc`，调用没有物理连续约束；首地址加偏移的线性 DMA 方式尚未成立。
- 本地 vendor／odm 镜像是按需填充的 sparse cache。本轮四条只读命令补取目录块，回复的 base64、连续偏移和末尾 next 均通过检查；只将所需范围写入新的本地 clone，旧 cache 保持原样。
- 后续三条只读命令补齐 camera 目录 inode，vendor／odm 目录的 8／50 条内联记录均通过独立结构检查。odm 目录包含 annibale 的 `ovx8000` 主摄、`ov20b40` 前摄及其他厂商模块；相关插件与 sensormodule 内容继续按 NID 补取。
- `sensor_config.json` 的 761 字节已完整读回并通过 JSON 解析，其 O1／IMX06／JN5／IMX858／HP9 命名与上述模块目录不同。当前日志仍报告后摄 `chip_id=0x2121`、前摄 `0x5620`；实际型号继续以传感器寄存器与模块表的匹配结果确认。
- 两份新 clone 保留每轮补取范围；旧 cache 与前一轮 clone 保持原样。`dump.erofs` 的目录显示仍因缺少父路径 inode 报错，单独验证的内联目录结果保存在本地 `codex-1112-camera-native/metadata-v2/`。
- 第三批三条只读命令补齐 sensor／sensormodule inode 与一处父路径，回复格式和连续偏移通过检查，写入新的 `metadata-v3` clone。16 个文件的 extent 均覆盖完整逻辑长度；sensor 插件的压缩数据为 12～28 KiB，sensormodule 为 56～640 KiB，内容尚未取全。路径显示仍受另一处缺失 inode 影响，后续按 NID 与已验证的 extent 定点读取。
- 第四批三条只读命令补齐两份 OVX8000、Sunny OV08F 与 Sunny OV20B40 插件数据，写入新的 `metadata-v4` clone。按 NID 提取的四个 ELF 长度分别为 68,184、68,184、51,736 和 51,672 字节，均与 inode 逻辑长度一致，退出码为 0 且 stderr 为空；前一份 clone 保持原样。厂商 sensormodule 配置仍待取全，插件文件名仅确认固件包含这些候选。
- 四个插件的 `GetSensorLibraryAPIs` 只设置版本字段与曝光、温度、模式切换等算法回调，已核对入口反汇编及其写入的字段；这些入口未提供 ID 配置。具体身份、电源、初始化和出流表继续从 sensormodule 提取，分析记录见本地 `codex-1112-camera-identity/plugin-api-audit.json`。

## 35. 本地 AVPlayer 冷启动与重复播放

独立 RAM 候选使用 cd16 音频排空内核，只增加 `audio_player_test` 与三秒零幅 WAV。探针直接创建 `AVPlayerItem` 和 `AVPlayer`，保持默认音频会话与音量，不提前调用 activate；文件为 48 kHz／s16／stereo、144,000 帧，没有视频轨。

冷启动首次与同次启动的新进程重复均返回 0，ready、playing、advanced、ended 全部成立，failed／stalls 均为 0。两次最终播放时间均为 `144000/48000`，并完成 cleanup。

| 阶段 | 冷启动首次 | 新进程重复 |
|---|---|---|
| 命令总耗时 | 6,382 ms | 3,968 ms |
| AVPlayerItem 创建 | 2,342 ms | 64 ms |
| 首次观察到 playing | 3,203 ms | 119 ms |
| 收到 ended | 6,355 ms | 3,957 ms |

本轮总耗时差为 2,414 ms，其中 item 创建耗时差为 2,278 ms。该区间继续拆分资源创建、库加载与服务请求，当前数据只覆盖这一轮首次／重复对照。

- 两次独立排空窗口分别为 sent／done 290／290、888／888，backlog、inflight、completion_error 均为 0。日志同时有系统提示音请求，累积 DSP period 计数不能换算为该 WAV 独占的帧数。
- `audiomxd` 在三份进程快照中保持 PID 71；`airplayd` 在首次播放后出现，PID 177 在重复播放后保持。重复播放的最大采样时钟曾达到 3.463650165 秒，最终停止位置回到 3 秒。
- 本轮 24 个步骤均按预期完成，包含两次桌面截图；最高 CPU 采样温度为 74.8°C，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。
- 两张相隔 23.664 秒的完整图已实际查看：应用与 Dock 图标可见，首张缺少应用／组件标签和 Wi-Fi 标记，第二张恢复；天气与日历内容持续缺失。该界面变化单独记录，播放验收以原生事件、最终位置和 DSP 排空为准。
- 原始结果与冻结输入保存在本地 `kernel-12377-codex-1112-cd16-audio-player/` 和 `codex-1112-audio-player/`。本轮覆盖本地音频播放，实际听音、HTTP、Safari 和带视频轨播放仍需分别验证。

## 36. 进程自有 IOSurface 的相机输入

`AnnibaleGPUMemory.inc` 的 `surfaceBuffer` 在返回几何信息之前拒绝 `IOSurfaceAddress` 存储，错误为 `kIOReturnUnsupported`。原来对齐的行距与 offset 只尝试直接导入，导致相机原版 CI 图缺少纹理输入。

内核仓 `018a9e06` 保留 describe 的精确返回值，仅在上述错误后选择已有 buffer／copy 路径。已有 plane 校验、cache、IOSurface 持有、提交前 refresh 与完成后 writeback 继续复用，没有新增缓存或同步状态；其他导入错误仍返回失败。

- 29 项宿主检查通过；旧基线导入失败，恢复对齐拒绝、放宽全部错误、移除 refresh、移除 writeback 四个消融均失败。
- A830 的两种布局为 row 128／offset 64 与 row 256／offset 128，覆盖 wrapper 创建后的 CPU 更新、调用方释放 IOSurface 后的 GPU 提交，以及每次命令完成后的后续读写。六个阶段的像素、保护区和 padding 差异均为 0，探针耗时 386 ms。
- 原版 CI 五函数／六节点图从 process-owned RG16 输入读取纹理 1、采样器 5，128 个分量零错误、状态为 4，耗时 367 ms。
- 两个相机进程均继续创建 `ci_affine_crop`、`ci_affine_swizzle_rgb1` 与后续 Min／MaxFilter。该单变量候选固定使用 CI-label 输入，随后仍由已有格式 25 拒绝触发 `MPSImageAreaMin` 的空 source 断言；R16 修正尚未与本候选组合上机。
- 本轮 25 条命令按预期返回，另完成两张桌面截图。运行 Metal／AIR UUID 匹配，最高 CPU 采样温度为 74.0°C，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。

不同 usage 的 wrapper 可能创建独立 copy 资源；同一 command-buffer 内先写入一个、再读取另一个会得到旧值，宿主已复现这一既有缺口。本轮只读相机输入与跨已完成命令的读写通过，通用别名读写仍待修复。

完整桌面与原尺寸组件局部已实际查看，应用／Dock 图标及标签可见，两组件均为上下浅白、中间壁纸，内容仍缺失。原始结果在本地 `kernel-12377-codex-1112-cd14-wrapped-surface/run/`，功能、身份与相机阶段分别见 `functional-review.json`、`runtime-identities.json` 和 `camera-key-events.json`。

## 37. Iris STAGE 与 SMMU 权限故障

cd19 以 cd18 为基线，只增加原厂当前 320×192 progressive AVC 样本对应的 `STAGE=1` 属性。PIPE、COMV 8、初始输出 minimum 4 与等待时长保持一致；首个 collect timeout 合并读取三条 HFI 队列头及已有 SMMU context bank 的 FSR。固定 STAGE 值仅用于该样本的诊断。

- OPEN、两次订阅与 input START 均收到应答；PSC、输入／输出 BUFFER 返回和解码帧数均为 0，回调仍为 `-12909`，单次探针耗时 1,300 ms。
- 首次 input 后命令队列为 429／429，消息队列为 80／80，调试队列为 0／0。cd18 的对应命令位置为 420／420；9 个 DWORD 的差值与新增 STAGE 属性长度一致，处理进度尚无改善。
- 后续 DRAIN／STOP 写位置依次为 445、461、477，读位置保持 429。三次 collect 与两次 STOP 超时，DMA 资源保留至复位。
- SMMU CB 81 的 FSR 为 `0x408`，包含 AArch64 格式与权限故障位；translation fault、stalled status 和 multiple faults 位均为 0。本轮未采 input 前的 FSR、FAR 或访问属性，故障发生时点与缓冲归属仍待定位。
- 本轮 19 条常规命令按预期返回，硬解请求失败，另完成两张桌面截图。最高 CPU 采样温度为 73.3°C，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。

下一轮核对普通 DMA 页的访问权限，并合并记录初始化后、input 前和首次超时的故障状态、地址与映射归属。原始结果位于本地 `kernel-12377-codex-1112-cd19-iris-stage/run/iris-stage-review.json`，日志行号按 LF 分隔计算。

## 38. MPS read_write 的 level 0 读取

原版 `mps_stgf_applyCoefficients3_2d` 通过 builtin sampler 读取标记为 `air.read_write` 的目标纹理。AIR 前端此前遗漏该 metadata 的 read 位，并拒绝 image 的 builtin read 签名；本轮修正这两处，沿用已有 `image_load`，仅接受常量 level 0。非零或动态 LOD 继续返回明确错误，原有无 sampler 的 image 读取分支保持原样。

- 宿主探针覆盖 2D／array、float／half、i16／i32 坐标的八种组合；4,032 个分量零错误。移除写入的消融产生 2,688 个差异，九种无效签名均被拒绝，原版 MPS apply 的 NIR／IR3 编译通过。
- A830 八个用例均为完成状态 4，初始读取、同一 command-buffer 内后续独立读取和 CPU 回读均为零错误，合计 4,032 个分量，探针耗时 1,136 ms。原 MPS 数组探针的 2,184 个分量仍全部正确。
- 相机进程已创建 applyCoefficients3／4 的 2D／array 及 Sampling 管线，随后继续创建 histogram、Downscale、CornerDetect、NccMatch 和 AffineSolver。日志仍记录 buffer wrapper 无可导入 handle 与 `output node(null)` 拒绝；该轮保持 MPSarray 的 Metal 基线，尚未组合 CI 图与第 36 节的 process-owned IOSurface 修正。记录期间未见 cameracaptured 的 userabort，实际相机图像与传感器输入仍待验证。
- 本轮 27 个步骤按预期完成，包含两张桌面截图与三条相机 metadata 读取。最高 CPU 采样温度为 76.0°C，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。

该 RAM 库基于冻结的 MPSarray runtime，仅改动两处 AIR 源文件。当前仓库完整 AIR 源码的独立组合构建也已通过，read_write 的 85 项检查、read-array、原版 apply／covariance 的 NIR／IR3 与反射检查均符合预期。

冻结 runtime 的完整 18 阶段回归耗时 44 分 18 秒，各阶段退出码及规范化结果摘要均与 MPSarray 基线一致，既有失败仍为第 1、5、6、11、12、13、15 阶段，套件退出码为 1。第 18 阶段未提供设备 compute 日志，其通过范围仅为脚本正常退出；本节真机数值检查使用单独的八用例探针。生产修正与探针已提交到用户态仓 `753a0fb`。

原始产物在本地 `codex-1112-mps-apply/`，组合检查见其 `current-integration/validation.json`；真机结果在 `kernel-12377-codex-1112-cd14-mps-rw-level0/run/`，相机后续阶段见 `camera-key-events.json`。

## 39. 相机身份读取契约

当前 `cci0_m1_read8()` 返回首个 `READ_DATA` word 的低 8 位。原厂 `camera.ko` 的 `cam_cci_read` 跳过首 word 的低字节，首个数据字节取 bits 15:8；低字节用于 SID 日志。后摄日志中的 `0x2121` 和 `rev=0x21` 与 slave7 `0x10` 的 read SID 一致，现有读值不足以确认传感器型号或 revision。

- 原厂在 completion 和事务状态检查后要求 `READ_BUF_LEVEL == (num_byte >> 2) + 1`；当前实现仅等待 FIFO 非空，缺少完成 IRQ、错误 IRQ 和预期字数校验。
- 前摄 GPIO 接收的每个数据位及 ACK 周期忽略 `od_i2c_scl_high()` 失败。日志未记录实际命中的 ID 寄存器，`0x5620` 保留为软件读值，尚未通过有效读取与厂商配置匹配。
- 原厂 `cam_sensor_match_id` 使用配置中的寄存器、地址宽度、数据宽度、mask 和 expected ID。当前实现只排除 `0x0000`／`0xffff`，真实型号还需按本机配置匹配。

静态定位基于本机提取的 `camera.ko`：首字节跳过和移位位于 `.text+0x15e734`／`0x15e81c`，FIFO 字数检查位于 `0x15e69c`～`0x15e6a8`，配置 ID 比较位于 `0x18d478`～`0x18d4e8`。相关源码与反汇编核对记录保存在本地 `codex-1112-camera-identity/`，后续独立候选将修正数据字节位置、完成检查和 GPIO 错误传播，再验证实际读值。

独立行为候选与附加诊断候选各通过 34 个宿主场景，七项消融均检出相应问题；基线及两份候选的内核翻译单元编译成功，归一化路径与行号后的警告一致。错误或超时后停止后摄 CCI 及其 GPIO 探测，恢复重试需另行验证 master reset 完成。cd22 真机结果见第 44 节，生产文件保持原样。

## 40. HTTP AVPlayer 冷启动与重复播放

本轮沿用第 35 节的内核、辅助盘、探针和零幅 WAV，只将输入改为 HTTP URL。首次及新进程重复播放均收到 ended，随后原始 CMTime 均为 `144000/48000`；各自 GET 的实际写入范围完整覆盖 WAV header 与 PCM，内容哈希一致且 `write_error` 为空。

| 阶段 | 首次 | 新进程重复 |
|---|---|---|
| item 创建 | 3,500 ms | 46 ms |
| player 创建 | 50 ms | 2 ms |
| ready／playing，距探针开始 | 55,645 ms | 256 ms |
| ended，距探针开始 | 58,781 ms | 3,398 ms |
| 原生命令总耗时 | 58,855 ms | 3,421 ms |
| 完整 WAV GET 写出耗时 | 54.3 ms | 43.9 ms |

首次 `NSURLSessionDataTask` 在探针开始后约 3.55 秒已创建。后续日志记录 en0 在 17.612～18.615 秒出现、36.709～37.719 秒连接成功，IPv4 更新和网络路径评估出现在 53.798～55.487 秒。请求等待与网络启动重叠，日志尚未给出 URLSession 的 wait reason 或路径满足的精确时刻，具体阻塞条件继续核对。该时间范围由同一次探针的 elapsed 标记限定，未跨主机和设备时钟相减。

- 两次播放器 session 的 `IsPlayingOutput` 起止均能按顺序关联 HAL playing／stopped，HAL 均记录 `0 frames not taken`。各自播放附近的全局 DSP sent／done 增量均为 290，独立结束窗口分别排空至 888／888 与 1178／1178，backlog、inflight 和 completion_error 均为 0。
- 首次命令起点缺少 DSP 计数样本，等待期间还播放了系统音；目标开始输出前已观测到 598／598 排空。共享计数没有逐播放器帧归属，目标 144,000 帧的 DSP 完整传输仍待单独确认。
- 本轮 27 个步骤按预期完成，包含两张桌面截图和三条相机 metadata 读取。最高 CPU 采样温度为 72.5°C，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7；HTTP 服务已退出。

播放器终态、HTTP 完整交付、目标 session／HAL 顺序和全局排空分别通过。实际听音、Safari 与带视频轨播放继续独立验证。原始结果位于本地 `kernel-12377-codex-1112-cd16-audio-http/run/`，阶段与验收分别见 `http-startup-analysis.json`、`audio-review.json` 和 `root-functional-review.json`。

## 41. Iris 普通 DMA 权限与 PSC 返回

cd20 以第 37 节的 cd19 为基线，普通 NC／WB 数据页增加 AP_UNPRIV 位，PTE 分别由 `0xf03`／`0xf07` 改为 `0xf43`／`0xf47`。原厂映射路径从 attrs 决定 `IOMMU_PRIV`，普通数据 DMA 清除该标志并设置 AP_UNPRIV；Device 页与 PAS 固件装载路径保持原样。

- 初始化后与 input 发布前的 CB 81 FSR 均为 `0x400`，两次采样的故障位为 0。本轮 input 后未触发 collect timeout，故障地址与页表诊断未执行，input 后 FSR 仍缺少采样。
- OPEN、两次订阅和 input START 均收到应答，首次收到一个 SETTINGS_CHANGE 及九项 PSC 属性。输入／输出 BUFFER 返回、RAW 发布和解码帧数仍为 0，单次探针耗时 303 ms，回调为 `-12909`。
- 首个解析错误为 crop 属性 `0x03000105` 的 payload type：固件返回 U64（3），当前解析器只接受 64_PACKED（13）。depth、coded frames、color 的实际类型均为 32_PACKED（10），当前分支只接受 U32／ENUM；这些差异均会返回 EIO。
- 原厂 `handle_session_property` 按类型检查最短长度，再按属性读取数据；crop 读取两个 32 位值，depth／coded frames／color 各读取一个。类型修正及真机解析结果见第 43 节，现有长度、port、flags 检查继续保留。

普通 DMA 权限修正及既有测试扩展已提交到内核仓 `638ab9ec`，11 个权限／资源生命周期场景通过，八类错误版本均被检出。真机验证范围为当前 320×192 AVC 与 STAGE1 诊断配置；STAGE1 和临时诊断未合入生产，完整解码、像素及其他格式尚未通过。

本轮最高 CPU 采样温度为 71.7°C，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。内核已完成 PAS shutdown，未确认完成的 DMA 资源保留至复位。

原始结果位于本地 `kernel-12377-codex-1112-cd20-iris-dma-permission/run/iris-dma-permission-review.json`，原厂映射核对与生产补丁检查位于 `codex-1112-iris-dma-permission/`。

## 42. Safari 原生打开接口返回失败

使用第 40 节的同一 HTTP 音频页面，原生打开接口约 10,084 ms 后返回 false。辅助程序将 BOOL 为 0 统一打印为 `it REFUSES`；现有返回值不足以确认失败来自 SpringBoard、URL handler、权限检查或等待超时。

- `SBSOpenSensitiveURLAndUnlock` 使用 `LSApplicationWorkspace` 的 `openSensitiveURL:withOptions:`，options 只有 `__UnlockDevice:@YES`。该方法转到带 `NSError **` 的变体，现有调用传入 NULL，具体错误未被采集。
- 请求前日志记录 `deviceIsLocked=YES`；后续路径通过 `_LSDOpenService` 的同步代理发送 `openURL:fileHandle:options:completionHandler:`。约十秒耗时的来源仍需定位。
- 服务端仅收到主机健康检查，设备 GET、page-ready、点击和播放均为 0。后置回归与相机 metadata 读取未执行，Safari 播放尚未进入验收阶段。
- HTTP 服务与控制进程均已退出，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。短轮没有 CPU 即时温度报告，周期采样覆盖不足。

后续单次探针的阶段结果见第 45 节。原始结果位于本地 `kernel-12377-codex-1112-cd16-audio-safari/run/safari-review.json`。

## 43. Iris PSC 类型修正与输出缓冲数量

cd21 保持第 41 节的 DMA 权限及诊断配置，crop 新增接受 U64，depth／coded frames／color 新增接受 32_PACKED；已有类型与长度、port、flags 检查保留。真机九项 PSC 全部解析，`seen=required=0x5fb`。

| 属性 | 返回值 |
|---|---|
| resolution | `0x14000c0`，320×192 |
| crop 左上／右下 | `0`／`0` |
| profile／level | `2`／`3` |
| depth | `0x80008` |
| coded frames | `1` |
| minimum output count | `6` |
| POC | `0` |
| color | `0x21202` |

该轮 RAW pool 容量为 4，PSC 要求 6 个输出缓冲，`iris_start_output()` 因容量检查返回 EOPNOTSUPP（102）。RAW 配置、RESUME 与 output START 尚未发送，BUFFER 返回与解码帧数均为 0；单次探针耗时 460 ms，回调仍为 `-12909`。缓冲数量修正后的解码结果见第 46 节。

生产修正已提交到内核仓 `e1f85a98`，不包含 STAGE1 或临时属性日志。实际应用后的源码通过 124 项 ASan／UBSan 场景，49 类消融均被检出；单文件均未超过 1,200 行。

本轮完成 19 条常规命令、一次硬解请求与两张桌面截图。最高 CPU 采样温度为 73.3°C，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。原始结果位于本地 `kernel-12377-codex-1112-cd21-iris-psc-types/`，宿主检查位于 `codex-1112-iris-psc-types/production-applied-check/`。

## 44. 相机读取有效性与 V5 模块提取

cd22 以第 40 节的内核和辅助盘为基线，只修正第 39 节的 CCI 数据字节位置、事务完成检查与 GPIO 时钟错误传播，并增加 ID 读取日志。VFE 版本寄存器 offset 仍为 `0xa00`，CCI 时钟仍为 19.2 MHz，未加入 sensor streaming。

- 启动快照 `s005.log` 第 6741 行记录后摄 slave `0x10` 首次读取 `0x300a` 成功，`READ_BUF_LEVEL=1`、raw 为 `0x560a5621`、payload 为 `0x56`。下一行的 `0x300b` 读取见到相同 IRQ `0x01011000`，但实际 FIFO level 为 0，因此拒绝此次事务并停用后续后摄探测，汇总 ID 为 `0x0000`。
- 上述 IRQ 的 RD_DONE 与 Q0_REPORT 均置位，error mask 未命中。空 FIFO 事务的 `raw=0`／`payload=0` 是未读取数据的初始化值；首次成功事务的 payload 则来自 FIFO bits 15:8。
- 前摄 GPIO 读取 `0x300a=0x56`、`0x300b=0x20`，数据位与 ACK 时钟检查均通过。这两个寄存器的读值仍需与厂商指定的 ID 地址、数据宽度、mask 和 expected ID 对应，型号尚未验收。
- VFE 版本仍返回 0，`hw_dma=0`，本轮没有真实相机像素或 CSI／IFE DMA 结果。

三条 metadata 读取各返回 28,704 字节／598 行，起始 offset、连续性、base64、终止状态和 next 均通过检查；各取所需的 28,672 字节写入新副本，原 metadata-v4 保持原样。前两段已提取完整 Sunny OV20B40 front_i 模块，长度为 156,424 字节，四个 section 连续且均在文件范围内，尾部 CRC32 与前部文件内容匹配。

该模块使用 `Parameter Parser V5.2.1 (2408261003)`，现有 `camsensor.py` 只接受 V3.0.1。现阶段确认文件完整性，V5 的 sensorDriverData 字段布局继续核对；AAC wide_i 仅取得首段压缩数据，完整后摄模块尚未提取。

本轮 24 个步骤按预期完成，包含两张桌面截图和上述三条读取。最高 CPU 采样温度为 73.3°C，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。原始日志见本地 `kernel-12377-codex-1112-cd22-camera-read/run/camera-read-events.json`，模块边界与 CRC32 检查见 `codex-1112-camera-native/metadata-v5/v5-container-review.json`。

## 45. Safari 打开前的锁状态查询耗时

独立探针使用同一 LS 方法与 `__UnlockDevice` 选项，并保留 NSError 输出。该轮在打开前调用 `SBSSpringBoardServerPort()` 与 `SBGetScreenLockStatus()`，两次调用所在的查询阶段共耗时 29.338195 秒；记录尚未拆分两者各自的耗时。

- 查询返回码为 0，`locked_raw=0`、`passcode_raw=0`。这些值对应查询完成时刻，开机最初的锁定状态仍以同期系统日志为准。
- `defaultWorkspace` 随后正常返回，探针开始调用原生 `openSensitiveURL:withOptions:error:`，但进程 30 秒总期限即将用尽。日志只有 `open-begin`，没有 `open-end`，BOOL 与 NSError 均缺失。
- 原生命令以 124 退出，耗时 30,340 ms；该结果仅确认探针达到总期限，原先约十秒返回 false 的原因仍待定位。
- 最高 CPU 采样温度为 73.6°C，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7；HTTP 服务及控制进程均已退出。

后续候选去掉前后锁查询，原生打开函数、options 和单次调用保持一致。准备阶段与打开方法分别计时，30 秒仍为进程总期限；完整 `open-end` 结果见第 48 节。候选通过五项宿主检查、arm64e 构建与签名校验，既有辅助盘文件内容均保持一致。

本轮阶段数据位于本地 `kernel-12377-codex-1112-cd16-safari-opener/run/opener-phases.json`；后续候选与独立包检查位于 `codex-1112-safari-open-direct/`。

## 46. Iris RAW 协商后完成 30 帧硬解

cd23 只调整第 43 节的 RAW 缓冲数量。OPEN 前保留初始 4 块，收到 PSC 后按固件 minimum 追加，实际发布 `max(4, minimum)` 块；容量上限沿用 DPB 的 6 块。本轮 minimum 为 6，RAW 与 DPB 均发布 6 块，随后收到 RESUME、RAW START 和 BUFFER 应答。

- 320×192 H.264 单次请求提交、接受、回调和出帧均为 30，`hardware=1`、`require_hardware=1`、`software=0`。错误回调、丢帧、空帧和布局检查错误均为 0，原生退出码与 rsh 退出码均为 0，总耗时 770 ms。
- 输出为 NV12，有效 Y／UV 数据共 2,764,800 字节。主机从实际测试 APFS 核对样本，再用单线程 FFmpeg 软件 H.264 解码；30 帧有效 Y／UV 区域的 FNV1a64 逐帧全部一致。设备尚未回传原始像素转储；探针的 `pixel_errors` 仅检查格式、布局与可读性，内容核验来自上述独立哈希对照。
- 输入 STOP、RAW STOP 与 CLOSE 均收到应答，随后记录 `close done`，对应会话缓冲全部释放和解除映射。退出时的全局 PAS／SMMU 保留记录对应另一组资源，仍按复位要求处理。
- 最高 CPU 采样温度为 73.6°C，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。该轮为 RAM 测试，完整部署镜像保持原版本。

生产实现按成功分配数维护 `raw_count`，返回索引、取帧与重新入队均检查该数量；释放扫描全部槽位，覆盖映射失败后保留的资源。零数量、容量、DPB 实际字节数和 RAW IOVA 范围检查保留，重复或变化 PSC 仍拒绝。实际源码通过 160 项 ASan／UBSan 场景、64 类消融和三个内核单元编译，已与相机 CCI 读取修正合入内核仓 `496e356d`。

cd23 仍包含 STAGE1 诊断设置；通用 STAGE 规则与重复会话结果见第 50 节，1280×768 STAGE2 结果见第 55 节。连续播放及其他格式尚未验收。

本轮原始结果位于本地 `kernel-12377-codex-1112-cd23-iris-raw-count/`；软件参考与逐帧对照位于 `codex-1112-iris-raw-count/reference-check/comparison.json`，生产检查位于同目录的 `production-applied-check/` 与 `production-applied-compile/`。

## 47. 相机 CCI 中断清除后连续读取成功

cd24 以第 44 节为基线，仅将 `CCI_IRQ_GLOBAL_CLEAR_CMD` 从 `0xc10` 修正为 `0xc00`。本机原厂 `camera.ko` 的 `cam_cci_irq` 向 `0xc00` 写入 1；`0xc10` 对应 IRQ_MASK_1，原厂在相邻路径对该寄存器执行 mask 读改写。

| 后摄寄存器 | payload | FIFO level | IRQ | 读取结果 |
|---|---|---|---|---|
| `0x300a` | `0x56` | 1 | `0x00011000` | 成功 |
| `0x300b` | `0x50` | 1 | `0x00011000` | 成功 |
| `0x300c` | `0x45` | 1 | `0x00011000` | 成功 |

后摄三次读取连续完成，诊断汇总为 `wide=0x5650`、revision `0x45`、slave `0x10`、bus 1。前摄仍读得 `0x300a/0x300b=0x56/0x20`。VFE 仍返回 0、`hw_dma=0`，真实图像尚未取得。

本轮末尾读取后摄 V5 数据区，原生退出码为 0、耗时 227 ms，但 telemetry 插入一行 Base64 中间，rsh 输出缺少后半行，连续性校验失败后结束采集。四份原始日志均保留相同的前 20 字符和后 44 字符；合并后另存派生回复，598 行／28,704 字节通过严格连续性检查，七个 LZ4 extent 按预期解出 62,369 字节。原始回复与日志保持原样。

第 49 节的组合轮补取 HAL 目录 inode 后，两段回复写入新的 metadata-v6，范围与回读检查通过。`dump.erofs` 因缺少祖先 inode 输出错误；直接解析目标 inode 与 inline 目录，十条目录记录与 CLI 列表一致，已定位四个本机 CamX HAL 文件。原 CLI 失败记录保留，完整文件提取见第 54 节。

后摄 `sensorDriverData` 的 slaveAddress 为 `0x20`，ID 地址为 `0x300a`，expected ID 为 `0x5650`，mask 为 `0xffff`；本轮 `0x300a/0x300b=0x56/0x50` 与这组字段相符。完整模块校验见第 54 节，本机 V5 parser 的字段与调用路径核对见第 56 节。

最高 CPU 采样温度为 74.4°C，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7。生产修正已随内核仓 `496e356d` 提交，保留已修正的 VFE offset `0x1000`；本轮 RAM 候选仍用旧 offset `0xa00`，VFE 新地址需要单独真机复核。生产测试通过 34 项场景、7 类身份消融和 3 类 MMIO 消融。

本轮结果位于本地 `kernel-12377-codex-1112-cd24-camera-global-clear/`；缺失 offset 与回复校验见其 `run/metadata-gap-review.json`。恢复过程与 ID 对照见 `codex-1112-camera-identity/v5-schema/cd24-recovery/`；原厂寄存器核对、编译及宿主检查位于 `codex-1112-camera-global-clear/`。

## 48. Safari 打开接口取得 LS 超时错误

direct 探针去掉第 45 节的锁查询，取得完整 `open-end`。原生打开方法耗时 12.949221 秒，返回 false；NSError 为 `NSPOSIXErrorDomain`、code 60，`_LSFile=LSDispatchUtils.mm`、`_LSFunction=_LSDispatchWithTimeout`、`_LSLine=147`。进程总耗时 13,110 ms，原生与 rsh 退出码均为 1，`defaultWorkspace` 调用耗时 10 µs。

方法返回后执行一次进程查询，并保存 8.242 秒日志窗口。窗口后段的 `s008.log` 记录 MobileSafari 启动，以及包含 `com.apple.mobilesafari` 的 FBS 前台布局；需结合完整启动时序分析 LS 等待的完成回调。服务端全程仅收到主机健康检查，页面 GET 与 page-ready 均为 0，页面播放仍待验证。

本轮单次调用后结束，没有重试。最高 CPU 采样温度为 73.3°C，收尾确认新版 loader 空闲、常驻区为空和真实 LK 重试 7；HTTP 服务与控制进程均已退出。

静态调用路径为 `_LSSpringBoardCall` → `FBSOpenApplicationService`，默认 Mach endpoint 为 `com.apple.frontboard.systemappservices`，service identifier 为 `com.apple.frontboard.open`。应用打开路径经 `springBoardQueue` 提交异步请求，相关等待期限为 10 秒；该队列属于调用 LS 的进程，队列名称不足以确定 SpringBoard 主线程状态。

`_LSDispatchWithTimeout` 超时后写入共享错误，已提交的 FBS 请求继续执行；晚到 completion 保留已有错误。这解释了返回 code 60 后仍出现 Safari 启动与前台布局。12.949221 秒中的排队、IPC 和启动耗时尚未分段；现有同步探针也未记录内部 FBS 回调时刻。

最终日志在内核时间 255.703 秒记录 `Lightweight corpse enqueued for MobileSafari`。该行仅记录轻量异常回溯入队，尚无进程退出结论，其与 `oem stop` 的先后关系也未建立。设备探针、内核前缀、日志墙钟和主机单调时间尚未校准，当前仅按各自时间域和快照顺序报告，未计算跨时间域的精确延迟。

完整返回值、阶段计时和最终日志位于本地 `kernel-12377-codex-1112-cd16-safari-open-direct/`，静态分析位于 `codex-1112-safari-open-direct/rootcause/report.json`。下一轮保持单次原生调用与 30 秒进程期限，以已有解锁完成和 Home Screen 日志作为调用前提，继续核对请求、前台与页面事件。

## 49. 相机 CI、MPS 与纹理修正组合验证

组合辅助盘使用已分别验证的 CI stitching、read_write level 0、数组纹理、R16 别名与 process-owned IOSurface 只读输入修正。内核、启动参数和常驻启动卷保持 RW 基线；辅助盘仅替换 AIR 与两份 Metal 库，增加三个缺失探针。实际 APFS 回读确认 722 个既有文件内容一致，完整 bundle 签名通过。

| 真机探针 | 组合结果 |
|---|---|
| read_write level 0 | 8 项、4,032 分量，写前／写后／回读错误均为 0 |
| 数组纹理 | 5 项、2,184 分量，错误为 0 |
| R16 与格式别名 | 22 项，像素、前后保护区与行 padding 检查通过 |
| RG16 | 8 项，像素及保护区检查通过 |
| CI stitching | 6 节点、5 函数、128 分量通过，label 检查通过 |
| IOSurface wrapper | 两种布局各三个阶段，像素、保护区与 padding 错误均为 0 |
| CI 与 wrapper 组合 | 128 分量通过，wrapped RG16 输入已执行 |

该轮共执行 28 步，包含上述七个探针、原有相关回归、两张桌面截图及一条 HAL metadata 读取；原生与 rsh 退出码均符合预期，G2 数据错误对照返回 1。完整桌面与原尺寸截图显示图标可见；天气仍为整块浅白，日历仍为上下浅白、中间显示壁纸，小组件内容缺失。

`cameracaptured` 继续构建多条 CI 管线。日志仍记录 affineGPUMetal、EdgeDrawingLineDetector、软件闪光、Warp、CMIPost 与 ColourConstancy 的部分预热失败，真实传感器流与图像 DMA 尚未验收。同一 command buffer 内不同 usage copy wrapper 的写后读旧值限制保持第 36 节范围。

本轮最高 CPU 采样温度为 74.4°C，采样器记录两个覆盖缺口。独立恢复记录确认 loader 空闲、常驻区为空和真实 LK 重试 7。原始结果位于本地 `kernel-12377-codex-1112-cd14-camera-combined/`，逐项数值、日志位置与画面检查见其 `run/combined-root-review.json`；组合包输入与 APFS 核对位于 `codex-1112-camera-combined-root/`。

## 50. Iris 通用 STAGE 规则与重复会话

cd26 以第 46 节为基线，只将固定 STAGE1 改为原厂普通 AVC／HEVC 解码的尺寸规则：宽高各小于 1280，且按 16 向上取整后的宏块数小于 3600，使用 STAGE1；其余尺寸使用 STAGE2。OPEN 的 `coded_frames` 与 `low_latency` 使用原厂默认值 0，当前 AVC 输入检查仍拒绝隔行与尺寸变化；PSC 的 coded-frames 位含义须与 OPEN capability 分别处理。

- 同一轮执行两次相同的 320×192 H.264，各提交、接受、回调和出帧 30，`hardware=1`、`software=0`，错误计数均为 0。原生与 rsh 退出码均为 0，探针耗时分别为 920 ms 和 278 ms；这两个耗时包含会话建立与测试程序工作，尚无持续播放性能结论。
- 从软件参考 NV12 重新计算有效 Y／UV 区域的 FNV1a64，两次共 60 帧全部一致。两次都收到 minimum 6 的 PSC，发布 6 块 RAW。
- 两个不同 wire session 分别完成输入 STOP、RAW STOP 与 CLOSE，应答的 session、type、port 和 packet ID 均匹配。`close done` 对应输入、内部和 RAW 缓冲释放、解除映射与 TLB 同步；第二次会话复用已清理槽位。
- 13 步全部完成，最高 CPU 采样温度为 72.9°C，采样器记录一个覆盖缺口。收尾确认 loader 空闲、常驻区为空和真实 LK 重试 7。

生产修改仅增加尺寸计算与 OPEN 属性，未增加会话状态或 ABI，已提交为内核仓 `37121a16`。实际源码通过 181 项 ASan／UBSan 场景、75 类消融及内核编译；20 组临界尺寸和 STAGE2 报文已有宿主覆盖。本轮样本计算结果为 STAGE1；去掉临时诊断后的结果见第 52 节，STAGE2 真机结果见第 55 节。HEVC 和持续播放尚待验证。

原始结果位于本地 `kernel-12377-codex-1112-cd26-iris-stage-rule/`；逐帧与释放核对见其 `run/iris-stage-rule-review.json` 和 `run/pixel-reference-comparison.json`，宿主检查位于 `codex-1112-iris-stage-rule/production-applied-check/`。

## 51. VFE 版本地址真机复核与 HAL 元数据

cd27 以第 47 节为基线，只将 VFE 版本寄存器 offset 从 `0xa00` 改为 `0x1000`，对应已提交的生产修正 `8b3ad685`。本机原厂 `camera.ko` 的 `vfe_lite98x_top_common_reg` 首项为 `0x1000`；设备树中的 IFE-lite 范围为 `0xad6d000+0x2800`，实际读取地址 `0xad6e000` 位于该范围内。

- `s006.log` 两处初始化记录均读得 VFE-lite0 `0x20050000`，此前旧地址返回 0。CSID-lite0 仍为 `0x30000004`，初始化继续完成。
- 主摄仍连续读得 ID `0x5650`、revision `0x45`，前摄为 `0x5620`。`camera_avtest` 正常退出，仅覆盖枚举与格式；`hw_dma=0`，没有真实图像输出。
- 本轮 13 步完成，最高 CPU 采样温度为 73.3°C；采样器记录两个覆盖缺口，峰值仅限已取得的读数。收尾确认 loader 空闲、常驻区为空和真实 LK 重试 7。

末尾一条 HAL inode 读取取得 598 行／28,704 字节，连续性、Base64 与终止 offset 均通过检查；所需 28,672 字节写入新的 metadata-v7 并回读一致，metadata-v6 保持原样。四个 HAL 的逻辑范围和物理 extent 均连续，完整文件提取见第 54 节。

| HAL 文件 | 逻辑字节数 | 压缩字节数 | extent 数 |
|---|---|---|---|
| `camera.qcom.sm8750.so` | 16,272,168 | 11,427,840 | 2,790 |
| `camera.qcom.so` | 10,156,616 | 7,401,472 | 1,807 |
| `com.qti.chi.offline.so` | 645,104 | 401,408 | 98 |
| `com.qti.chi.override.so` | 7,310,560 | 5,128,192 | 1,252 |

`dump.erofs` 仍报告缺少祖先 inode，路径显示 `(not found)`；上述目标 inode 与区段数据来自本轮已读取范围，原始 stderr 保留。该读取方式每次 `cat` 取得约 28 KiB，完整读取这四个压缩文件约需 851 次命令；完整提取采用第 54 节的 Android 只读流程。

本轮原始记录位于本地 `kernel-12377-codex-1112-cd27-camera-vfe-version/`，寄存器核对见其 `run/camera-vfe-root-review.json`；HAL 区段核对见 `codex-1112-camera-native/metadata-v7/extent-review.json`。

## 52. Iris 生产配置重复解码通过

cd28 使用当前生产 Iris HFI、硬件和会话三个实现，其他 1,159 个内核对象保持 cd26 冻结版本。唯一变量为移除 Iris 临时诊断，包括逐帧 FSR 读取、逐项 PSC 打印、超时寄存器与页表采样，以及 OPEN 前的两条固件日志属性。生产的有限 HFI 日志、PSC 摘要和错误处理保留。

- 两次相同的 320×192 H.264 请求各提交、接受、回调和出帧 30，均为硬件解码，错误、丢帧和空帧为 0。每次输出 2,764,800 字节，共 60 帧有效 Y／UV 区域的 FNV1a64 全部匹配重新计算的软件参考。
- 两个 wire session 分别取得输入 STOP、RAW STOP 与 CLOSE 的匹配成功应答，随后记录 `close done`。结合本轮冻结源码，该分支要求输入、内部和 RAW 缓冲解除映射、TLB 同步与释放全部成功；本轮未记录逐页解除映射日志。
- 两次探针耗时分别为 1,289 ms 和 273 ms，包含初始化与用户态加载，当前没有性能提升比例。移除临时诊断后，重复会话与内容校验仍通过。
- 13 步完成，最高 CPU 采样温度为 75.6°C，采样器记录五个覆盖缺口，峰值仅覆盖已取得读数。独立收尾检查确认 loader 空闲、常驻区为空和真实 LK 重试 7。

本轮仍为 RAM 测试，完整部署镜像保持原版本。结论覆盖上述三个生产 Iris 实现和该 H.264 样本；1280×768 STAGE2 结果见第 55 节，其他尺寸、HEVC、低延迟、动态重配置与持续播放尚待验证。全局 PAS／SMMU 退出资源继续按复位要求处理。

原始结果位于本地 `kernel-12377-codex-1112-cd28-iris-production/`；独立核对见其 `run/iris-production-review.json`、`run/pixel-reference-comparison.json` 和 `run/loader-recovery/root-hard-check.json`。

## 53. Safari 就绪后原生打开成功

本轮保持第 48 节的内核、辅助盘、原生探针、URL、options 和单次调用，只增加调用前提：本轮日志已有 boot unlock done，最新 Main Display 布局为 Home Screen，前后两次 `ps` 中 SpringBoard、lsd 与 backboardd 的 PID 一致。三项条件在主机 helper 启动后 49.821417 秒满足，共享启动期限仍为 120 秒。

- 日志仅有一次 `open-begin`，`openSensitiveURL:withOptions:error:` 返回 true，`error_present=0`。方法耗时 1.150740 秒，原生与 rsh 退出码均为 0，探针总耗时 1,158 ms。
- 后置进程快照已有 MobileSafari、WebContent 和 Networking；三个就绪检查进程的 PID 保持一致。原生 FBS 布局记录 Safari 位于前台。
- 后置日志窗口为 8.1443 秒，服务端完整请求记录仅包含主机健康检查，设备页面 GET 与 page-ready 均为 0。页面加载及媒体播放尚未验收。
- 4 步完成，最高 CPU 采样温度为 72.5°C，采样器记录一个覆盖缺口。收尾确认 loader 空闲、常驻区为空和真实 LK 重试 7。

该结果支持开机就绪条件与第 48 节的超时有关，尚未确定旧轮排队、IPC 或回调处理中的具体等待。后续保持原生调用条件，按页面事件结束观察，并检查网络就绪和 WebKit 请求；原生接口成功、应用前台与页面完成分别记录。

原始记录位于本地 `kernel-12377-codex-1112-cd16-safari-ready/`，完整核对见其 `run/safari-ready-review.json`。就绪控制器的 9 项测试覆盖 11 个模拟场景，包括旧 Home Screen 失效、未完成快照、PID 变化、期限耗尽和零重试。

本轮实际链接的 `corpse.o`、冻结源码及最终内核指令已核对。`Lightweight corpse enqueued` 位于 `EXC_GUARD` 的轻量回溯分支，该分支收集回溯并加入 `thread_backtrace_queue` 后返回，没有终止 task；日志缺少 guard code、subcode 与调用来源，外层行为尚未确认。核对记录见本地 `codex-1112-safari-open-direct/rootcause/corpse-linked-inputs.json`。

## 54. 本机相机 HAL 与完整 V5 模块提取

通过一次 B 槽 Android 启动，以普通 adb 权限只读取得第 51 节的四个 HAL，以及 AAC OVX8000 wide_i 和 Sunny OV20B40 front_i 两个模块，共 36,393,206 字节。每个文件均核对手机端长度与 SHA-256，再与本地回读比较；前摄模块还与此前完整样本的 SHA-256 一致。

提取和恢复共耗时 67.0857 秒，回程只执行一次既有恢复流程。独立检查确认 loader 空闲、常驻区为空，真实 LK 的 A 槽重试为 7；未改变 HAL 或传感器模块内容。

完整后摄模块的 CRC、四个 section 和符号区边界检查通过，文件还与此前取得的前缀和恢复的数据片段逐字节一致。本机 `camera.qcom.sm8750.so` 依赖 `camera.qcom.so`；V5 的 `SensorDriverData::Load`、`SensorDriverDataClass::LoadModule` 和 `CreateProbeCmd` 定义位于后者，解析对象到探测命令的字段核对见第 56 节。

原始文件与命令记录位于本地 `codex-device-1111/android-camera-extraction/run/`，逐文件独立核对见其 `root-file-review.json`。HAL 与 V5 解析结果位于 `codex-1112-camera-identity/v5-schema/`，真实传感器流与图像 DMA 仍待实现和验证。

## 55. 1280×768 STAGE2 硬解通过

cd29 保持第 52 节的内核、原生探针、启动参数与常驻启动卷，仅替换辅助盘中的 H.264 样本。新样本保留原画面的 5:3 比例、15 fps 和 30 帧，宽高各扩大四倍；SPS 无裁剪，尺寸规则选择 STAGE2。实际 APFS 回读的 719 个路径中，718 个保持一致。

- 单次请求提交、接受、回调和出帧均为 30，`hardware=1`、`require_hardware=1`、`software=0`；错误、丢帧、空帧和布局错误均为 0。
- NV12 有效数据共 44,236,800 字节。30 帧的有效 Y／UV 区域 FNV1a64、显示时间戳、尺寸与字节数全部匹配独立软件参考。设备没有回传原始像素转储。
- PSC minimum 为 6，RAW 与 DPB 均发布 6 块。输入 STOP、RAW STOP 与 CLOSE 分别收到匹配应答，随后记录 `close done`；按冻结源码，该分支要求会话缓冲解除映射、TLB 同步和释放成功。
- 原生与 rsh 退出码均为 0，探针总耗时 1,201 ms。该数字包含会话初始化与测试程序工作，持续播放和性能收益尚未测量。
- 12 步完成，最高 CPU 采样温度为 76.0°C，采样器记录两个覆盖缺口。收尾确认 loader 空闲、常驻区为空和真实 LK 重试 7。

本轮为 RAM 测试，完整部署镜像保持原版本。全局 PAS／SMMU 退出仍按复位要求处理。原始结果位于本地 `kernel-12377-codex-1112-cd29-iris-stage2/`，独立核对见其 `run/iris-stage2-root-review.json`、`run/root-pixel-reference-comparison.json` 和 `run/loader-recovery/root-hard-check.json`。

## 56. 本机 HAL 的传感器身份契约

第 54 节取得的 `camera.qcom.so` 包含 V5 的实际解析器。静态核对沿 `SensorDriverData::Load`、`CreateProbeCmd` 和 `CreateI2CInfoCmd`，确认模块字段的读取偏移、对象成员和原厂探测命令一致；该过程未加载执行 HAL。

| 字段 | 主摄 wide_i | 前摄 front_i |
|---|---|---|
| 模块 slaveAddress | `0x20` | `0x20` |
| CCI 7 位地址 | `0x10` | `0x10` |
| ID 起始寄存器 | `0x300a` | `0x300b` |
| 地址／数据宽度 | 2／2 字节 | 2／2 字节 |
| 期望 ID | `0x5650` | `0x2042` |
| mask | `0xffff` | `0xffffffff` |

两个模块各有一条 `ModuleConfiguration`，slave override flag 均为 0。原厂 CCI 配置将模块的 `0x20` 右移一位，得到 `0x10`；原厂 CCI／QUP 的两字节读取均以第一个 payload 字节为高位。I²C frequency enum 为 3，与 CCI 源时钟频率分别记录。

前摄此前取得 `0x300a/0x300b=0x56/0x20`，旧组合为 `0x5620`。原厂身份需要读取 `0x300b/0x300c`，cd30 的补读结果见第 58 节；按本机起始地址、宽度、端序、期望值与 mask 处理的正式身份读取结果见第 59 节。

精确指令地址、文件偏移与原始字节见本地 `codex-1112-camera-identity/v5-schema/hal-identity-contract.json`；独立文件核对见同目录 `root-hal-identity-review.json`。cd30 的冻结输入、编译与 24 项宿主场景及 4 类消融结果位于 `codex-1112-camera-front-id/`。真实传感器流与图像 DMA 尚未验证。

## 57. Safari 页面传输与脚本完成，单帧正文仍空白

本轮沿第 53 节保持内核、辅助盘、原生探针、URL、options 与启动就绪条件。原生打开成功后，以完整页面 GET、page-ready 和 Safari 前台状态作为事件完成条件，最多观察 90 秒；期间增加前后两次只读接口查询，结束保存一张截图。

- 原生只调用一次，返回 true，NSError 为空。方法耗时 8.811783 秒，探针耗时 8,866 ms，原生与 rsh 退出码均为 0。
- 目标 GET 返回 200，HTML 的 1,900 字节全部写出，内容 SHA-256、响应范围与长度匹配，`write_error=null`。随后收到 page-ready，最新完整 Main Display 记录为 Safari primary。
- GET 开始和 page-ready 分别位于主机观测原生成功后 26.839078 秒和 26.963755 秒；三者均使用本机主机单调时间。该延迟超出第 53 节的后置观察窗口，不能据此确定旧轮最终会否完成加载。
- 前置接口查询显示 en0 已 UP／RUNNING，尚无 IPv4；后置查询已有 IPv4。`net_test show` 的退出码没有包含接口查询结果，接口状态按输出字段单独核对。
- 实际截图中 Safari 状态栏、地址栏和工具按钮可见，网页正文为均匀浅灰，测试页文字、播放按钮与状态文字均未显示。截图请求和主机确认完成分别位于 page-ready 后 3.065396 秒和 4.093128 秒；本轮仅有这一帧，后续是否显示内容尚未覆盖。
- 6 条命令完成，最高 CPU 采样温度为 73.3°C，采样器记录一个覆盖缺口。HTTP 服务与控制进程退出，收尾确认 loader 空闲、常驻区为空和真实 LK 重试 7。

冻结 HTML 在发送 page-ready 前已给状态元素赋值，页面文字与按钮的默认样式要求可见。当前结果确认页面传输和脚本执行完成，单帧画面未通过内容验收。下一次页面观察先区分延迟显示与持续空白，媒体播放保持未验收。

本轮 WebKit GPU 对 surface 48 的第三次提交包含 33 个 work 和 10 条管线，完成记录的错误数为 0；随后 backboardd 导入同一 surface，并记录合成提交、完成和 display marker。该 BGRA 对象的行宽为 4,864 字节、offset 为 0，冻结源码使用直接共享导入；现有记录没有该 surface 的像素，尚不能定位内容缺失发生在哪一步。

原始结果位于本地 `kernel-12377-codex-1112-cd16-safari-page-ready/`；页面事件、接口与截图分别见其 `run/page-observation.json`、`run/network-before.json`、`run/network-after.json` 和 `run/root-page-visual-review.json`。页面观察控制器的 19 项宿主测试通过，覆盖完整响应、部分响应、缺失脚本事件、超时、原生失败、温控与传输停止。

## 58. 前摄补读确认原厂 ID

cd30 沿第 51 节的冻结内核和辅助盘，仅在前摄 `0x300a/0x300b` 均读取成功后补读 `0x300c`。三个字节分别为 `0x56/0x20/0x42`，三次事务均成功；按原厂起始寄存器组合 `0x300b/0x300c`，得到期望 ID `0x2042`。本轮诊断保持旧识别返回 `0x5620`，未改变传感器启用行为。

- 主摄仍取得 `0x5650`、revision `0x45`，VFE 为 `0x20050000`，CSID 为 `0x30000004`。
- `camera_avtest` 的原生与 rsh 退出码均为 0，耗时 398 ms，枚举两个视频设备，后摄 33 种格式、前摄 14 种格式。`hw_dma=0`，真实传感器流与图像 DMA 尚未取得。
- 12 步完成，最高 CPU 采样温度为 75.2°C，采样器记录三个覆盖缺口。独立收尾确认 loader 空闲、常驻区为空和真实 LK 重试 7。
- 两张桌面截图相隔 6.111 秒，均缺少应用／Dock 图标主体及小组件主体，壁纸、标签、时钟指针、状态栏与 Dock 背景可见。该轮沿用 cd27 的 audio-player 辅助盘，当前没有将画面缺失归因于相机诊断的对照。

cd30 的逐字节补读只确认寄存器值；后续正式两字节身份读取的实现、宿主检查与真机结果见第 59 节。

原始结果位于本地 `kernel-12377-codex-1112-cd30-camera-front-id/`，独立核对见其 `run/camera-front-id-root-review.json` 与 `run/loader-recovery/root-hard-check.json`。正式身份读取候选、行为补丁和验证范围见本地 `codex-1112-camera-configured-id/delivery.json`。

## 59. 正式两字节身份读取通过

cd31 沿第 51 节的冻结内核和辅助盘，仅改变相机身份读取：CCI 与 GPIO 路径按第 56 节的原厂起始地址、两字节事务、端序、期望值和 mask 判断成功。候选保留逐事务诊断；去掉诊断后，行为与内核提交 `84e3437e` 一致。其他内核对象保持冻结版本，本轮没有验证完整当前源码组合。

- 后摄 CCI 从 `0x300a` 读得 `0x5650`，前摄 GPIO I²C 从 `0x300b` 读得 `0x2042`，两者均记录 sensor matched。CSID 与 VFE 版本保持第 58 节结果。
- `camera_avtest` 枚举两个视频设备，原生与 rsh 退出码均为 0，耗时 216 ms。`hw_dma=0`，真实传感器流与图像 DMA 尚未取得。
- 相隔 6.182 秒的两张桌面截图中，应用与 Dock 图标可见；天气组件为浅色块，日历组件中间显示壁纸、上下为浅色块，组件内容仍缺失。该截图覆盖桌面，未显示相机预览。
- 12 步完成，最高 CPU 采样温度为 72.5°C，采样器记录五个覆盖缺口。收尾确认 loader 空闲、常驻区为空和真实 LK 重试 7。

生产身份读取的 60 项宿主场景、20 类消融及编译已通过。真机结果支持两字节身份事务与原厂配置匹配；后续仍需传感器 streaming、CSI 接收和 DMA 像素验收。

原始结果位于本地 `kernel-12377-codex-1112-cd31-camera-configured-id/`，事务与画面见其 `run/camera-configured-id-events.json` 和 `run/visual-observation.json`；候选与生产源码的对应关系见本地 `codex-1112-camera-configured-id-cd31/final-review.json`。

## 60. 270 帧离线硬解完成，逐帧记录缺一条

cd32 保持第 55 节的生产 Iris 内核、探针和启动参数，仅将辅助盘的 H.264 视频延长到 270 帧、18 秒媒体时间。实际 APFS 的 719 个路径中，718 个保持一致；样本内容由原 30 帧序列重复九次。命令使用 `--frames 271`，使读取器在提交 270 帧后继续检查 EOF。

- 探针统计提交、接受、回调和出帧均为 270，`hardware=1`、`require_hardware=1`、`software=0`；错误、丢帧、空帧和布局错误为 0，输出有效数据 398,131,200 字节。
- 独立扫描 48 份原始日志，回收到 269 个唯一回调。其有理数 PTS、duration、源样本编号、NV12 尺寸与字节数、有效位和 FNV1a64 全部匹配软件参考，未发现冲突或不匹配。
- 参考帧 247（源样本 249、PTS 为 `247/15`）的回调记录缺失，源样本 3 的提交记录也缺失，各快照均未恢复这两条输出。未发现 `annsh dropped` 提示，输出缺失原因尚未确定；独立像素校验仅覆盖已恢复的 269 帧。
- `limit_reached=0`、`reader_status=2`，四个 marker 与最终 drain 均成功。PSC minimum、RAW 与 DPB 数量均为 6；输入 STOP、RAW STOP 与 CLOSE 取得匹配应答，随后记录 `close done`。
- 原生与 rsh 退出码均为 0，探针耗时 3,784 ms。12 步完成，最高 CPU 采样温度为 74.4°C，采样器记录三个覆盖缺口。收尾确认 loader 空闲、常驻区为空和真实 LK 重试 7。

该探针只离线解码视频，没有显示、按媒体时钟等待或音频播放。18 秒为样本媒体时长，实时播放尚未验收；重复内容也未覆盖每帧独立变化的输入。会话缓冲关闭成功，全局 VPU DMA 退出仍按复位要求保留资源。

原始结果位于本地 `kernel-12377-codex-1112-cd32-iris-sustained/`。已有比较见其 `run/claude-pixel-reference-comparison.json`，独立核对见本地 `codex-resume-1112/cd32-independent-review.json`；辅助盘逐路径比较见本地 `codex-1112-iris-sustained-root/logical-comparison.json`。

## 61. Safari 三帧正文持续空白

本轮保持第 57 节的内核、辅助盘、HTML、原生打开探针和就绪条件，仅将页面完成后的单张截图改为相邻两张及稍后一张。原生打开调用一次，返回 true，NSError 为空，方法耗时 0.561653 秒，探针耗时 577 ms；完整 GET 返回 200 并写出相同的 1,900 字节 HTML，随后收到 page-ready，Main Display 保持 Safari primary。

| 截图 | 请求距 page-ready | 主机确认取得距 page-ready | 可见结果 |
|---|---|---|---|
| 首张 | 2.765 秒 | 3.587 秒 | 状态栏与浏览器按钮可见，正文浅灰，测试页文字及播放按钮缺失 |
| 相邻张 | 3.595 秒 | 4.416 秒 | 与首张相同 |
| 稍后张 | 10.134 秒 | 10.972 秒 | 与首张相同 |

三份原始截图的 SHA-256 相同，实际看图也确认上述内容。该结果覆盖 page-ready 后约 11 秒，正文在这一窗口内持续空白；更晚显示尚未覆盖。三张截图来自 framebuffer，物理面板呈现未单独验证。

本轮 backboardd 加载的 AIR UUID 为 `A1E7F4D6-1D95-3783-8602-07873F121FC0`，对应第 23 节的 minmax AIR；Metal bundle UUID 为 `1978DE94-43C6-380F-A5D9-42153B8E9370`，对应第 26 节记录的版本。该轮延续原冻结用户态库，未覆盖第 49 节的组合库；当前画面缺失与库版本的因果关系尚未验证。

6 条命令及三张截图完成，最高 CPU 采样温度为 73.6°C，采样器未记录覆盖缺口。服务端退出，收尾确认 loader 空闲、常驻区为空和真实 LK 重试 7。网页文字未通过可见内容验收，本轮没有点击或媒体播放结果。

原始结果位于本地 `kernel-12377-codex-1112-cd16-safari-page-visual/`，事件与截图时间见其 `run/page-observation.json` 和 `run/page-foreground-shots.json`；控制器差异和收尾核对见本地 `codex-device-1111/safe-batch-safari-page-visual/`。

## 62. AVPlayer 首帧前的空会话排空阻止输入

cd33 沿第 60 节的冻结内核、270 帧样本、辅助盘和启动参数，仅将离线探针改为 `video_player_test --deadline 60 /annibale/bin/h264.mp4`。该探针读取 AVPlayerItemVideoOutput，不显示视频。

- ready、playing、advanced 和 ended 均为 1，媒体时钟最终为 `6912000/384000`，即 18 秒；输出帧数与字节数均为 0，`has_new` 始终为 0。原生与 rsh 退出码均为 1，探针耗时 21,482 ms。
- `iris_vt[344]` 创建 Iris 会话后，在首次 decode 前发布 DRAIN；固件返回匹配 ACK，未返回 DRAIN_LAST，收集输出超时。随后出现首个 decode 请求，内核仍处于 draining，未发布 bitstream 输入。
- 会话 STOP／CLOSE 后记录 `close done`。最高 CPU 采样温度为 73.6°C，温控采样没有覆盖缺口；收尾确认 loader 空闲、常驻区为空和真实 LK 重试 7。

源码核对发现 `iris_vt_finish_delayed_frames` 即使没有 pending 帧也调用 `IRIS_IOC_FLUSH_SESSION`。内核在首次输入和 PSC 前对空会话执行 DRAIN，缺少 DRAIN_LAST 后保留 draining 状态，后续输入返回 EBUSY。iOS 26 的 `VTDecompressionSessionFinishDelayedFrames` 沿派生类槽位 `0x38` 调用该方法，签名判据为 `0xbfc3`。

内核提交 `f9b6215d` 使用已有 `next_input_idx`，直接完成尚未发布输入的会话 flush。错误、closing 和端口检查保持原顺序，已发布输入的会话继续要求 ACK、LAST 与输入归还。该改动覆盖 `IRIS_IOC_FLUSH_SESSION`；显式 `IRIS_FRAME_DRAIN` 的处理保持原样。

新增回归场景能使旧实现失败，修复后 185 项 HFI／会话场景和 77 类编译消融通过。RAM 候选只重建 HFI，另外 1161 个链接对象及编译依赖摘要均已核对；真机复核见第 63 节。

原始结果位于本地 `kernel-12377-codex-1112-cd33-avplayer-video/`，原生输出见其 `run/probe-avplayer-video.txt`。修复前后测试、构建对应关系和复杂度审阅见本地 `codex-1112-iris-empty-flush/`；真实连续出帧、显示与音频仍待验收。

## 63. 空会话 flush 修复后取得三帧，连续播放仍未通过

cd34 保持第 62 节的 AVPlayer 探针、辅助盘、样本、启动参数与控制器，仅替换 HFI 中的空会话 flush 行为。首次输入随后成功发布，PSC 完成，RAW 与 DPB 均发布 6 块；首帧前的排空超时未再出现。

- 原生探针记录 ready、playing、advanced 和 ended 均为 1，最终媒体时钟为 18 秒。收到 3 帧 1280×768 NV12，PTS 分别为 0、1/15、2/15 秒，有效数据共 4,423,680 字节；首帧在探针开始后 851 ms 取得，后续直到结束没有新输出。
- 原生 summary 和 rsh 退出码为 0，探针自身的验收条件只要求取得有效帧及结束事件。持续出帧没有通过本轮验收。
- 按同一样本、相同 PTS 的软件 NV12 参考核对，首帧有效区哈希匹配，后两帧不匹配。AVPlayer 输出转换及硬解参考状态的归属仍需分别定位。
- 本轮记录 264 条 `VT-DS` 错误 `-12909`，首条位于第四次 bitstream 输入发布之后。现有有限 HFI 回复日志未取得该次 ioctl 的 errno，后续按输入归还与 RAW 输出顺序继续核对。
- 12 项探针完成，最高 CPU 采样温度为 73.6°C，采样器记录三个覆盖缺口。收尾确认 loader 空闲、常驻区为空和真实 LK 重试 7。

原始结果位于本地 `kernel-12377-codex-1112-cd34-avplayer-empty-flush/`，原生记录和逐帧参考比较分别见其 `run/probe-avplayer-video.txt` 与 `run/root-frame-reference-review.json`。本轮推进了首次输入和首帧；持续播放、完整像素正确性、显示与音频仍待验收。

## 64. 原厂 V5 模式与寄存器导出

内核工具提交 `e67048ab` 为 `camsensor.py` 增加 `--json MODULE.bin OUT.json`，按已提取本机 HAL 的 V5.2.1 布局导出传感器身份、供电、模式时序、流配置、初始化与启停寄存器。JSON 保留每条流的 VC 列表、CFA 原始枚举、寄存器操作顺序、数据与延迟；现有内核表格式仍由 V3 入口生成。

- 前摄模块含 6 个模式、6 条流及 6 个 VC 值；主摄模块含 31 个模式、67 条流及 123 个 VC 值。两份模块共 13,237 条寄存器设置，全部导出字段与原始数据逐项一致。
- 前摄 mode 4 为 2592×1458、30.003 fps、VC0 RAW10、4-lane D-PHY、settle 31 ns，共 81 条模式设置，可用于下一步核对 PHY 和接收配置。
- 主摄 mode 24 与 27 均含两条流。mode 29 同时满足单条流、单 VC，为 1280×720、480 fps、3-trio C-PHY；选用它需要独立核对相应速率与带宽。
- 4 项测试、CLI 输出及错误输入保护通过，两份完整原厂输入均解码成功；24 个重算 CRC 的结构或语义损坏输入被拒绝。解析器检查模块长度、CRC、池引用、数组长度与有来源的字段范围。

真实 streaming、CSI 接收和 DMA 仍需实现。当前前置条件包括 SM8750 PHY 的 D-PHY／C-PHY 表与 lane mask、CSID lite980 和 VFE lite98x 寄存器、DMA 连续地址或 SMMU 映射、RAW 布局与缓存同步，以及停止完成后再释放资源。导出 JSON 供静态核对，当前内核尚未消费该输出。

原厂文件、HAL 指令、寄存器逐项核对、模式候选与硬件前置条件集中在本地 `codex-1112-camera-identity/v5-schema/v5-modes-validation.json`。该批没有新增设备操作，真实图像仍待验收。

## 65. RAW 先返回与输入区域复用顺序

第 63 节后核对源码发现，`iris_receive` 每次处理一份 HFI message；`iris_collect_output` 取得 RAW 后可以立即返回，当前 bitstream BUFFER 尚未归还。下一次普通输入在接收回复前检查 `input_queued`，返回 EBUSY；用户态插件将 ioctl 失败转换为 `-12909`。cd34 的日志没有记录该次 errno，尚未确认这处顺序与全部错误的对应关系。

宿主使用生产 HFI／会话函数复现 RAW 先返回、精确 INPUT BUFFER 稍后返回的顺序。旧实现完成第一次调用后仍持有输入，第二次提交得到 EBUSY；修改后第一次调用等待输入归还，第二次提交成功。多个 RAW 先返回仍保留后续帧，缺输入和错误 SID／index 场景继续保留输入内容与 DMA 资源。

内核提交 `4490b52f` 仅在普通 collect 中等待精确输入归还后取得 RAW，复用 `raw_state`／`raw_done`。入口的输入持有检查、POLL、DRAIN 与关闭顺序保持原样。190 项 HFI／会话场景和 78 类编译消融通过，删除等待条件会使顺序测试失败；父任务独立复跑 190 项通过。

候选只重建 HFI，1161 个对象保持冻结版本，并完成编译依赖与链接输入摘要核对。真机复核见第 67 节；第 63 节的后两帧差异继续单独定位。宿主复现见本地 `codex-1112-iris-input-order-review/validation.json`，构建及复杂度核对见本地 `codex-1112-iris-input-order/`。

## 66. Safari 绘制诊断前发生原生退出

本轮沿第 61 节的冻结内核、AIR、页面与原生打开探针，仅在两份 Metal 库加入已有的匹配绘制诊断。选择 `buffer_image_blit`，从第二次匹配开始，最多同步两次并采集六份 64×64 缩略图；输入、输出和绘制前的 attachment 分别使用 `in0`、`out0`、`pre0`。

- 原生打开返回成功，探针耗时 473 ms；Main Display 两次记录 Safari primary。MobileSafari 随后记录 `userabort` 与 `SIGNAL 6`，显示布局转为 home，控制器结果为 `foreground_lost`。
- 退出前记录 `NSInvalidUnarchiveOperationException` 及调用栈；具体归档对象和异常触发契约仍待静态定位。
- 页面 GET、完整响应与 page-ready 均为 0，三张页面截图未取得。匹配 draw 与缩略图样本也为空，该轮没有覆盖正文像素与合成验收。
- WebKit GPU 进程实际加载候选 Metal bundle 与冻结 AIR，两个 command-buffer 均 completed、errors 为 0；`buffer_image_blit` 管线与匹配同步尚未触发。当前日志未支持将退出归因于该同步。
- 13 条采集命令完成，runner 与 helper 退出码均为 0；这些结果覆盖采集流程。最高 CPU 采样温度为 75.2°C，采样器记录一个覆盖缺口。HTTP 服务和控制进程退出，收尾确认 loader 空闲、常驻区为空和真实 LK 重试 7。

候选的 26 项匹配绘制检查、10 项控制器检查与冻结输入核对通过。本批三轮至此结束；下一批先验证第 65 节的 Iris 输入归还修复，Safari 先核对异常调用栈，再安排同页面诊断。没有取得缩略图的原因需结合页面未完成与原生退出判断。

原始结果位于本地 `kernel-12377-codex-1112-cd33-safari-matched/`，退出与前台时序见其 `run/s018.log`，采集边界见 `run/page-observation.json` 和 `run/safari-thumbnail-review.json`；冻结输入及运行库核对见本地 `safari-matched-1112/delivery.json`，本批汇总见本地 `codex-device-1111/continuation-device-batch-1112.json`。

## 67. 输入归还修复后仍只有三帧

cd35 保持第 63 节的 AVPlayer 探针、辅助盘、270 帧样本和启动参数，仅替换第 65 节的 HFI 输入归还行为。371 项编译依赖及其他 1161 个链接对象逐项核对通过，本轮内核对应提交 `4490b52f`。

- 原生与 rsh 退出码均为 0，探针耗时 19,506 ms。ready、playing、advanced 和 ended 均为 1，最终媒体时钟为 18 秒；输出仍为 3 帧，PTS 为 0、1/15、2/15 秒，有效数据共 4,423,680 字节。
- 三帧有效区哈希与第 63 节一致；按同一样本、相同 PTS 的软件参考比较，首帧匹配，后两帧仍有差异。连续播放与像素验收仍未通过。
- 保存的完整快照最多包含 264 条 `VT-DS err=-12909`，首条紧随第四次输入 `index=3/tag=4`。没有取得显式 HFI、firmware、buffer mismatch、data-corrupt 或 collect timeout 错误行；该检查仅覆盖已保存的日志，首次失败 ioctl 的实际状态仍需定位。
- 输入 0 与输入 1 之间完成三次 DRAIN／RESUME。源码中的 `iris_vt_finish_delayed_frames` 即使没有 pending 帧仍调用 flush；原生排空契约与参考帧状态的关系继续静态核对。
- 关闭记录 `ioctl close retained slot=1 error=5` 与 `device close retained slot=1 error=5`。会话关闭未完成，相关 DMA 资源按失败规则保留。
- 12 条采集命令完成，最高 CPU 采样温度为 72.1°C，采样器记录六个覆盖缺口。收尾确认 loader 空闲、常驻区为空和真实 LK 重试 7。

桌面前后截图中应用与 Dock 图标可见；天气组件为均匀浅色块，日历组件上下为浅色块、中间显示壁纸，组件内容仍缺失。该探针没有视频显示层，截图只覆盖桌面。

原始结果位于本地 `kernel-12377-codex-1112-cd35-avplayer-input-order/`。逐帧比较与物理行号复核见其 `run/root-result-review.json`，关闭、温控及恢复见 `run/device-review.json`，截图范围见 `run/device-visual-review.json`。本批第一轮功能验收未通过；下一轮改用 Safari 异常观测，Iris 先核对帧间排空和首个失败状态。

## 68. 逐帧文件报告的宿主验证

用户态提交 `ad4c86c` 为 `video_decode_test` 与 `video_player_test` 增加 `--report-file PATH`。离线探针写入每条 callback，播放器探针写入每个实际取得的帧，保留 PTS、布局、有效字节数与 FNV1a64；播放器控制台继续按原有频率采样，控制台与文件复用同一帧内容及计时。

报告使用排他创建，已有文件保持内容。正常收尾写入 `stage=report_complete`；文件写入或关闭失败会使原生退出码失败。报告保持打开直到解码回调或播放器清理结束，进程 deadline 仍覆盖文件收尾。

- 两套主机测试各 12 项通过，覆盖实际软件像素比较、逐帧报告、已有文件保护及原有超时和输入场景。
- 同一 270 帧长样本的软件解码取得完整 270 条 callback、270 个唯一 PTS，全部哈希匹配参考，有效数据 398,131,200 字节，原生退出码为 0。
- 已有报告的验证返回退出码 1、errno 17，文件摘要保持一致；3 ms deadline 返回 124，报告文件已创建且没有完成记录。
- 两份最终 iOS arm64e 探针以 `-Wall -Wextra -Werror` 编译链接通过。文件报告尚未覆盖真机硬解与连续播放。

实现只增加各探针自己的文件句柄与输出目标，复用已有帧统计和格式。去掉文件输出会再次使完整像素校验依赖控制台回收。宿主数据、最终编译对应关系与复杂度审阅保存在本地 `codex-1112-video-frame-reports/`。

## 69. Safari 异常与本轮网络缺口

cd36 沿第 66 节的冻结内核、Metal、AIR、页面和打开探针，仅为 MobileSafari 增加有输出上限的未捕获异常观测。异常处理器保存并调用原处理器，原生框架方法保持原样。

- 同一 MobileSafari PID 的注册线程与异常线程分别取得记录。异常为 `NSInvalidUnarchiveOperationException`，`__NSCoderError` 的 domain 为 `NSCocoaErrorDomain`，code 为 4866。
- 底层错误为 `EncodingError.invalidValue`，debugDescription 原文为 `Unable to create a string from the sandbox extension token`；顶层错误记录 `Unable to encode the given top-level value as a property list`。
- 两次接口查询均在 Safari 打开后执行，en0 为 UP／RUNNING，IPv4 地址为空。主机 HTTP 健康请求只覆盖主机，设备路由与设备访问测试服务尚未验证；本轮页面加载、正文与视频验收无效。
- 13 条采集命令完成，最高 CPU 采样温度为 72.1°C，采样器记录一个覆盖缺口。HTTP 服务和控制器退出，收尾确认 loader 空闲、常驻区为空和真实 LK 重试 7。

静态核对发现，`libsystem_sandbox` 的请求 5 在成功返回后直接使用输出缓冲作为 extension token；MiniSandbox 该分支返回成功却未写入输出。原生库的失败分支释放缓冲并返回 NULL，Foundation 可继续处理这一结果。内核改为返回 `ENOTSUP`，宿主回归和冻结单对象编译通过；后续真机结果及 Safari 的 NULL 消费路径见第 72 节。

后续先观察开机后的 Wi-Fi 自动连接与已保存网络设置，连接可用后再继续页面和视频测试。原始结果位于本地 `kernel-12377-codex-1112-cd36-safari-exception/`，网络与异常范围见其 `run/device-final-network-exception-review.json`；原生分支分析见本地 `safari-exception-1112/native-exception-current-review.json`，修复与构建见 `safari-sandbox-1113/`。

## 70. 11-13 人工体验与发布范围

本轮使用第 65 节的输入归还内核和 minmax AIR／heap Metal 辅助盘，记录位于本地 `kernel-12377-codex-1113-cd37-wifi-user-review/manifest.json`。该轮由用户操作并观察，以下结果覆盖该次启动。

- 开机等待后 Wi-Fi 自动连接；用户在 01:18 反馈此前约一分钟操作卡顿，性能分析见第 73 节。
- 闪光灯可用，亮度调节正常；屏幕亮度调整期间没有闪烁。
- 01:25:15 前后的相机操作没有闪退，顶部绿色隐私指示灯亮起，预览黑屏；真实图像采集仍未通过。
- 用户在 01:30:04 反馈此前约十秒停顿，对应窗口的原因尚未定位，分析范围见第 73 节。
- 用户随后反馈整体性能较好、图形渲染错误与功能异常减少。这是本次体验反馈，尚无同条件的版本间帧率与错误数量对照。

`v0.1.3` 按用户选定的范围采用最近验证的组合。已出现首次启动图标缺失的较新 AIR 候选继续单独验证，相机 DMA 开发继续保留在日常工作区。发布构建、版本来源和校验记录见[11-13 发布记录](../progress/2026-11-13-release.md)。

## 71. cd38 至 cd40 的采集边界与控制器修正

本批三轮均未到达页面或 Iris 视频命令。结果按已执行步骤记录，采集流程结束与功能验收分别核对。

| 轮次 | 已执行范围 | 停止原因 | 最高 CPU 采样温度 | 温控覆盖缺口 |
|---|---|---|---|---|
| cd38 | 14 项中完成 6 项；第七项已投递 | annsh 起止输出被日志穿插，严格完成解析未通过 | 74.8°C | 0 |
| cd39 | 14 项中完成 8 项；七项诊断设置均取得退出码 0 | 最新快照已缺失早期解锁记录，控制器错误报告 `startup_readiness_timeout` | 73.3°C | 2 |
| cd40 | 前 5 条设备状态命令成功，第六项为主机截图脚本 | Python 缺少 NumPy，`tour.py` 导入失败，视频命令未投递 | 72.1°C | 2 |

- cd39 保持 cd38 的载荷与全部 14 项命令，仅把原有 45 秒主机等待移到第一条命令之前。`s008.log` 已保存 `sb26: boot unlock done after 2 attempts`，`s035.log` 仍保存 Home Screen；一次性事件已离开最新滚动窗口。
- 本地控制器修正分别保存本轮已完成快照中的解锁事件与最新 Main Display 状态。cd39 的实际快照复现旧版错误；修正后的八项检查通过，传输完成、完整 LF、文件稳定性与进程身份检查继续生效。真机复核尚未执行。
- cd40 保持 cd35 的视频、命令、启动参数、辅助盘其他内容和内核其他对象，只增加 HFI 首次拒绝回复及原始 VT ioctl errno 观测。已核对 371 项依赖、1161 个未变对象与 1172 项冻结链接来源；两份 VT 产物严格签名检查通过。视频步骤未执行，本轮没有首个 HFI／VT 错误数据。
- 三轮 runner 均退出 0，helper 均退出 1。相关进程结束后分别独立确认 loader 空闲、常驻区为空，真实 LK 重试计数均为 7；三轮至此结束。

原始结果分别保存在本地 `kernel-12377-codex-1113-cd38-safari-sandbox/`、`kernel-12377-codex-1113-cd39-safari-wait/` 与 `kernel-12377-codex-1113-cd40-iris-first-failure/`，各轮结论见 `run/device-final-review.json`。控制器回归见本地 `codex-1113-safari-readiness/review.json`，Iris 交付与本批复盘见本地 `codex-1113-iris-first-failure/`。

下一批使用已有、包含 NumPy 的 Python 环境；全部四个主机脚本的导入、历史原始截图解析和 FFmpeg 拼图已验证，载荷与命令序列保持 cd40 版本。该调整只涉及主机运行环境。

## 72. Safari 原生容器 token 与 NULL 消费

cd39 在显式打开命令执行前启动 MobileSafari，保存到 `SIGNAL 11 at 0x0`。23G90 共享缓存反汇编确认，SafariCore 的 `_WBSSetUpAccessToAppDataContainerWithIdentifier` 调用 `_container_copy_sandbox_token` 后直接调用 `_sandbox_extension_consume`，两次调用之间没有 NULL 检查。消费入口先执行 `strcmp(token, "invalid")`，与本轮故障地址和调用栈一致。

cd39 的请求 5 返回 `ENOTSUP`，原生库释放输出缓冲并返回 NULL。内核提交 `24d33d91` 已实现文件 extension 的签发、消费和普通 handle 释放；Safari 的容器初始化、正文和视频仍待真机复核。

| 请求 | 已确认的 iOS 26 参数布局 | 输出与生命周期 |
|---|---|---|
| 5，签发 | 56 字节；class、type、resource、flags、token 输出指针、pid、pidversion，各占 8 字节 | 原生库分配 16,368 字节，成功前须写入完整、以 NUL 结束的 token；失败释放缓冲并保留 errno |
| 6，消费 | 24 字节；token 指针、含 NUL 的长度、64 位 handle 输出指针 | 验证 token 与目标身份，消费记录独立持有实际资源，返回 handle |
| 7，释放 | 24 字节；handle、零值、文件路径指针；普通释放的路径为 NULL | 释放当前 owner 的 handle，保留其他消费者；`release_file` 的路径语义仍需核对 |

容器客户端从 XPC token 数组或容器 token 字段复制最多 2,048 个字符。Safari 消费后释放 token 字符串与容器查询，本函数没有保存或释放 handle；消费记录须持续到显式释放或进程终止。请求 80 的输出类型和 `release_file` 的路径语义仍待核对。

原版 `ContainerManagerCommon` 的四份容器配置分别指定 `com.apple.sandbox.container`、`com.apple.sandbox.application-group`、`com.apple.sandbox.system-container` 和 `com.apple.sandbox.system-group`。守护进程通过 `ReplyContainerTokens` 数组返回 token，客户端按容器索引复制字符串；原版 `containermanagerd` 具有 `com.apple.private.security.container-manager` entitlement。

实现范围与验证结果如下：

- 请求 5 支持文件 `type=0`、目标 audit 标志 `flags=0x30000`，校验目标 pid、pidversion、uniqueid，以及签发者的 vnode/DAC 权限；四种容器 class 另校验目录类型与 container-manager entitlement。
- issued 对象持有实际 vnode；每次消费创建独立的 owner 与 64 位 handle 引用，并再次校验 vnode/DAC。用户复制失败会回滚新增资源。
- fork 复制独立引用；spawn 在进入 EL0 前通过 exec hook 清理临时引用。exec 清理 consumed 引用与失效 issued 身份，目标退出清理其全部 issued 引用，签发者退出保留目标资源。
- 199 项宿主断言、原容器检查和完整 XNU 链接通过。候选沿用 cd41，仅替换 `kern_minimac.o`，其余 1,161 个 filelist 对象及额外链接输入保持一致。
- MiniSandbox 的全局策略保持既有非强制配置；本次验证范围为文件 extension 生命周期。宿主的 VFS、进程和锁使用 stub，真机调度与页面行为仍需验证。

原生参数、分发路径及生命周期来源集中在本地 `safari-extensions-1113/native-contract-review.json`，冻结输入与独立审阅见同目录 `lead-review.json`；cd39 原始片段保存在 `safari-sandbox-1113/`。

## 73. 启动与十秒停顿的性能分析

cd37 的已有日志覆盖用户指定的 01:17～01:18 和 01:29:54～01:30:04 窗口。设备事件时间由相邻墙钟与设备微秒时间关联，主机读取时间只标记快照取得时间；线程异步输出会影响具体事件的时间定位。

- 启动窗口的 SpringBoard 主循环记录到 16.655119 秒与 3.431839 秒的长处理，均发生在开始至提交前；对应提交区间各为一微秒。
- 第一段长处理的主线程堆栈含 `rw_library_new_function_with_descriptor`、`fsync` 与 `__rename`，后续一段含 `CARenderServerCreateSnapshots`。单个系统调用、锁等待和 UFS 写入耗时尚未测量。
- 后续十秒窗口没有输入投递记录，只有一个呈现帧。采样器在处理年龄达到两秒后停止输出，已有数据缺少长暂停堆栈，原因尚未定位。
- 已有快照按完整错误行去重后共有 562 次 `full_fsync` errno 28，其中 20 次落在后续十秒窗口，启动窗口没有这类错误。错误涉及四份 WAL，`bluetoothd` 的设备数据库占 555 次；失败位置及其与界面停顿的关系尚未确认。

`F_FULLFSYNC` 先执行共享映射页写回，再执行全卷元数据同步。冻结源码中可返回 ENOSPC 的分支包括页或索引数组分配失败、磁盘块位图分配失败，以及元数据打包超过 32 MiB 槽位。UFS I/O 层没有生成这个错误码；现有错误行缺少具体返回分支与耗时。

开机恢复计数对应 135,060 个节点和 598,341 个非零块引用，占数据区容量的上限为 8.82%；运行峰值未知。元数据已知下限为 20.83 MiB，槽位有效容量扣除该下限后的差为 11.17 MiB；目录项、xattr、空洞索引和对齐长度尚未取得，实际余量未知。

内核仓提交 `2b3863b` 修改 `rw_air_cache_store()`：磁盘位码与当前内容相同就保留已有文件；文件缺失、内容变化或读取失败继续执行原有原子写入。实现复用已有磁盘内容与 Foundation 比较，没有新增缓存状态或后台写入线程。

主机测试使用真实 Foundation 与临时文件系统，覆盖重复内容保留文件身份、内存淘汰后磁盘命中、内容替换、文件缺失及写入失败后重试。旧实现的重复文件检查失败，修改后通过；arm64e Metal dylib、bundle 编译链接与严格签名检查通过。该修复尚未打包上机，性能收益待测。

时间关联、窗口读数、堆栈、采样器限制和缓存验证集中在本地 `codex-1113-startup-perf/`，ENOSPC 返回分支与容量计算见其中 `full-fsync-review.json`。

保存内容复核确认，启动窗口有 34 条 `CARenderServerCreateSnapshots` 的 Mach IPC 等待样本，最长为 1968 ms；完整等待时长未知。十秒窗口有 181 条 SpringBoard 主线程样本，最长为 102 ms；另有 35 条相机着色器编译队列等待，最长为 189774 μs，各线程区间可能重叠。这些读数未确定用户停顿的原因。

旧日志仍保留，11 份来源和两段原始窗口校验通过，复核结果位于本地 `codex-1113-saved-user-stall-review/`。按用户后续指令，本项保存内容分析结束。

后续诊断轮确认元数据打包超过槽位容量，并记录到 14.258 秒的 `rm_lock` 等待，具体范围见[第 81 节](#81-ramfs-元数据槽位与同步等待)。该轮与用户指定的旧窗口分别记录，二者的因果关系仍未确认。

## 74. 前摄原生首帧的清理异常

内核提交 `00518e64` 实现前摄原厂 mode 4 与单帧 DMA，用户态提交 `3a83298d` 实现 RAW worker、实际 `TorchLevel` 和 `camera_test native`。本批第二轮使用冻结候选启动该测试，内核在 CAPTURE 完成输出前触发 `Unhandled implementation specific error`，没有取得原生退出状态或 RAW 文件。

本轮实际 unstripped 内核将 PC 定位到 `cam_native_release()` 内联的 `cam_smmu_release()`。异常指令为恢复 slot 12 的 saved S2CR 写入；此前禁用路由已执行。捕获进入清理前的失败位置和 saved CB／S2CR 值未取得，仍需按本机原厂 SMMU 初始化与撤销契约核对。

| 项目 | 本轮结果 |
|---|---|
| 命令与进程 | `camera_test` 实际启动；主机 rsh 被终止，`host_exit=-15`，`native_exit=null` |
| 捕获与像素 | 没有 CAPTURE 完成状态，未读回 RAW；真实像素与预览仍待验 |
| 异常 | `pc=0xfffffff0075ef608`、`lr=0xfffffff0075ef5bc`、`esr=0x96000010`、`far=0xfffffff8de224c30` |
| 收尾 | 运行器首次读到 `returned-held` 后停止，elapsed 61.909 秒；软件恢复及独立 loader 空闲、空常驻区校验通过 |
| 温度 | 完整日志峰值 73.6°C；温控 helper 有一个覆盖缺口 |

候选、原始日志、异常窗口、地址定位和恢复记录保存在本地 `codex-1113-camera-native-first-frame/`。预期 RAW 格式与大小仅用于后续读回校验，本轮没有像素验收结果。

## 75. 空 FinishDelayedFrames 修复后的三帧结果

本批第三轮保持 cd41 内核、270 帧样本、启动参数与其余辅助盘内容，仅更新用户态提交 `8caf4a6a` 的空 `FinishDelayedFrames` 入口检查。两份探针增加已有的逐帧文件报告接口，父版本重建与 cd41 逐字节一致；实际 APFS 的 719 个路径中，生产变化仅为 VT 库，另外两处变化为报告探针。

| 项目 | 本轮结果 |
|---|---|
| 原生播放器 | 同一 annsh 序列确认退出 0，耗时 19,529 ms；输出 3 帧，收到 EOS，stalls=0 |
| 首次 Iris 错误 | `HFI_INFO_DATA_CORRUPT`，`sid=1 / hdr=29 / port=2`；随后 ioctl 为 `mode=0 / tag=7 / bytes=6812 / errno=5` |
| 主机采集 | helper 漏识别正常完成信息，记录 `native_exit=null`、`delivery_rc=3`，完成 0/5；完整报告未读回，离线 decode 未执行 |
| 验收 | 连续 270 帧验收失败；完整逐帧像素与播放器实际 Iris 会话归属未验证 |
| 收尾 | controller=1、runner=0、helper=1；121.818 秒后运行器、helper 及其子进程全部结束，独立 loader 空闲、空常驻区与真实 LK retry=7 校验通过 |
| 温度 | 日志与 helper 峰值均为 74.0°C；helper 有一个覆盖缺口 |

`rsh.py` 将原生输出写到 stdout，将完成信息写到 stderr。两者合并到文件后，stdout 的缓冲内容使完成信息插入一条视频日志中，helper 的行首匹配失败；原始命令应答和同序列退出行均已保留。

主机工具在输出完成信息前刷新 stdout。宿主回放使用本轮原始日志和实际 `rsh.py` 邮箱流程：旧版本复现完成信息没有独立成行，修改后保留一条完整完成行，两版退出码均为 0。该检查没有设备操作，下一批使用修正后的工具。

候选、原始窗口、退出码来源和恢复记录保存在本地 `codex-1113-iris-empty-finish/`，输出顺序回放见 `codex-1113-rsh-output-order/review.json`。本批三轮结束；后续继续核对每帧损坏信息与同包 BUFFER 的归属，并按原生契约完成 DMA 归还和错误回调。

## 76. 文件 extension 候选的 Safari 打开超时

新批第一轮使用内核提交 `24d33d91` 的文件 extension 生命周期候选。相对 cd41 只替换 MiniSandbox 对象，辅助盘、启动参数和页面输入保持一致。主机等待 annsh-ready 后 45 秒再执行一次原生打开，等待期间上传临时签名 opener 并完整读回核对；开机前没有网络查询。

| 项目 | 本轮结果 |
|---|---|
| 原生打开 | `LSApplicationWorkspace openSensitiveURL:withOptions:error:` 返回 false；方法耗时 10.338598 秒，`NSPOSIXErrorDomain` code 60，出处为 `LSDispatchUtils.mm:147 / _LSDispatchWithTimeout` |
| 命令交付 | 同一 annsh 序列 5 退出 1，耗时 10,587 ms，投递应答为 0；后置进程查询与临时 opener 删除均退出 0 |
| 页面与视频 | 没有设备 HTTP 请求；原生失败分支未取得正文画面，视频未执行，clock、EOS 和媒体错误均未观测 |
| 收尾与温度 | controller、batch、runner、helper 均退出 0；全部登记进程组结束后，独立核对 loader 空闲、常驻区为空和真实 LK retry=7；峰温 74.4°C，两个当前温度报告，覆盖缺口为 0 |

MiniSandbox 日志确认请求 5、6、7 的全局首次入口已执行，未记录 Safari 对应 token、consume 返回值或 handle。现有显示日志没有本轮 boot unlock done、Home Screen 或实际 MobileSafari 启动记录；Main Display 的已保存布局为 backlightState=0。具体等待位置仍需核对。

第 48 节已确认 LS 超时后已提交的 FBS 请求仍可继续执行。本轮控制器在原生失败后立即结束页面分支，晚到请求与实际失败画面缺少观察。后续保持单次打开与既有期限，补齐该分支的页面等待和截图，再判断应用启动、正文及视频结果。

本轮输入与原始数据保存在本地 `codex-1113-safari-file-extensions/`，完整返回、HTTP 与恢复核对见 `run/device-final-review.json`；显示及启动记录见 `run/lead-ls-window.json`。

## 77. 相机 SMMU 配置的寄存器读回差异

本批第二轮使用内核提交 `8ef92708` 的 Stage-1 旁路与释放顺序修复，仅替换相机对象；辅助盘、启动卷和 `camera_test` 复用上一轮输入。正式配置的 `CAM_NATIVE_TRACE` 默认为 0，本轮候选显式启用。

| 项目 | 本轮结果 |
|---|---|
| 原生采集 | `camera_test native` 退出 1，耗时 619 ms；同序列完成信息仅一条，投递应答为 0 |
| 首次失败 | SMMU bank 5 的 SCTLR 读回 `0xa5f0066`，期望 `0xa5f1066`，相差 bit 12；随后返回配置错误 5 |
| 采集状态 | `state=5 error=5 flags=0`；尚未启用 DMA，未取得 RAW 文件或首尾行像素，后续状态步骤未执行 |
| 收尾 | controller=0、runner=0、helper=1；94.862 秒后全部登记进程组结束，独立核对 loader 空闲、常驻区为空及真实 LK retry=7 |
| 温度 | 峰温 70.5°C，当前温度报告一条，监测覆盖缺口为 0 |

本轮选中 slot 10、bank 5，context 偏移为 `0x85000`；CBA2R 为 `0x1`，CBAR 为 `0x1f300`。初始 SCTLR 为 `0x3577e102`，配置后的首次读回差异出现在 `cmd-1.log` 第 14451 行。该位的有效条件与读回语义仍需核对，真实 RAW 和连续预览尚未验证。

后续提交 `14acadd1` 将固定 M=0 配置的 ASIDPNE 请求设为 0，使用系统 ASID namespace；完整寄存器读回、DMA 停止与同步失败后的资源保留继续生效。原厂旁路配置仍请求 bit 12，具体读回 0 的原因未知。

43 项 SMMU 场景、18 项消融、37 项 native 场景及 8 项消融通过。默认与 trace 内核完整链接，分别相对上一轮仅改变五条 MOVZ 的常量位，其余字节相同；候选包的 43 项宿主回归通过，真机复核待执行。

本轮输入和原始数据保存在本地 `codex-1113-camera-smmu-native-frame/`。完整原生窗口、SMMU 窗口及功能与恢复结果分别见 `run/device-camera-native-window.log`、`run/device-camera-smmu-window.log` 和 `run/device-final-review.json`。

## 78. 同包损坏帧处理后的 165 帧结果

本批第三轮使用内核提交 `e954ef8a` 与用户态提交 `438e0caf`，按同一 HFI 消息校验损坏 RAW 的 DMA 身份，并按精确 out_tag 完成对应 token 的 BadData／FrameDropped／NULL image 回调。其他 pending 帧继续处理；系统错误、畸形消息、BUFFER_OVERFLOW 和停止、关闭、TLB 失败后的保护保持原样。

| 项目 | 本轮结果 |
|---|---|
| 原生播放器 | native、主机与投递退出码均为 0，耗时 23,513 ms；收到 EOS，原生摘要记录 frames=165、pixel_errors=0、stalls=0 |
| 完整逐帧文件 | 165 帧、165 个唯一 PTS、243,302,400 有效字节；153 帧 FNV 与同 PTS 参考一致，12 帧不同，缺少 105 个参考 PTS |
| 首个损坏消息 | `sid=1 / hdr=29 / port=2`；同包 RAW 为 `index=0 / base=0x60000000 / tag=2`，有效数据 1,474,560 字节 |
| 验收范围 | 格式、几何、有效字节数、PTS 递增和末行计数通过；完整 270 帧与像素验收失败，离线 decode 步骤未执行，播放器与 Iris 会话归属尚待独立核对 |
| 收尾 | controller=1、runner=0、helper=1；140.127 秒后全部登记组结束，独立核对 loader 空闲、空常驻区及真实 LK retry=7 |
| 温度 | 日志与监测峰值均为 72.1°C，当前温度报告三条，覆盖缺口为 0 |

主机 helper 的 summary 解析只接受无进程前缀的行，本轮原生输出具有 `[video_player_test 303]` 前缀，原始摘要已完整保存。私有候选修正该解析，原始日志及八项回放通过；270 帧验收继续失败。原轮输入与运行记录保持原值。

本批三轮结束。下一批 Safari 保留单次打开后的完整 90 秒观察，相机复核第 77 节的固定请求修正；Iris 继续核对参考帧损坏、排空语义及播放器取帧遗漏，下一轮需要取得同轮离线回调来区分输出缺失与显示取帧缺失。

输入、逐帧报告及完整原生窗口保存在本地 `codex-1113-iris-frame-errors/`，独立复算与恢复核对见 `run/lead-final-review.json`，首错原始窗口见 `run/device-iris-first-error-window.log`。主机解析回放见本地 `codex-1113-iris-summary-replay/review.json`。

同轮完整日志的四段 VMC 统计合计 268 帧解码、2 帧丢弃。iOS 26 反汇编确认每次统计后计数清零，四段可以相加；播放器报告与解码数相差 103 帧，这些图像的像素尚未取得。原生日志还列出报告缺失的 PTS `6、266/15、267/15`。

12 个 FNV 差异全部位于首个 GOP，两条同包 `DATA_CORRUPT` 对应 P 参考帧。当前 DRAIN／RESUME 的域、端口、标志和原因值与原厂解码会话一致；实际 pending 的 DRAIN 与尾部 FLUSH 继续保留。分段原始行、计数清零指令及原厂模块对照集中在本地 `codex-1113-iris-165-analysis/lead-vmc-review.json` 和 `native-contract-review.json`，完整播放器 Iris 会话归属仍待核对。

## 79. 单次 Safari 打开后的完整观察

新批第一轮沿用第 76 节的设备输入，仅调整主机采集：原生打开返回后仍观察完整 90 秒，并取得三张完整截图。启动流程保持 annsh-ready 后等待 45 秒，再执行一次原生打开。

| 项目 | 本轮结果 |
|---|---|
| 原生打开 | native 与主机均退出 1，投递退出 0，耗时 10,345 ms；BOOL=false，`NSPOSIXErrorDomain` code 60，方法耗时 10.189459 秒 |
| 晚到窗口 | 原生完成后观察 90.021553 秒；三张 RAW 内容相同，画面仍停在 Apple／100%／显示交接界面 |
| 页面与视频 | 没有设备 HTTP 请求或 DOM 回报；Main Display backlightState=0，Safari 未显示，视频未执行 |
| 收尾与温度 | 登记进程组全部结束，独立核验 loader 完整 build、idle、空常驻区与 recovery 锁定，真实 LK retry=7；峰温 71.3°C |

本批第三轮的 RAMFS 诊断候选继续使用同一打开与采集流程，正文实际可读。页面 GET、完整响应和 DOM `page-ready` 回报各一条，加载发生在原生完成后约 56.7 秒。单次结果尚未确认正文能在重复冷启动中及时显示。

| 请求 | 原生方法与返回 | 完成后观察 | 可见结果 |
|---|---|---|---|
| 正文 | 10.146130 秒，BOOL=false，POSIX code 60；native 退出 1，耗时 10,162 ms | 90.019822 秒 | Safari 正文和浏览器控件实际显示 |
| 视频 | 10.026610 秒，BOOL=false，POSIX code 60；native 退出 1，耗时 10,111 ms | 90.017059 秒 | 三张截图仍显示正文；没有视频页面 GET、回报、时钟推进或 EOS |

六张 RAW 各 11,606,240 字节，内容相同。正文与视频的功能结果分别保留，原生打开的十秒超时仍需定位。诊断轮的输入、存储读数与收尾见[第 81 节](#81-ramfs-元数据槽位与同步等待)。

第一轮原始数据保存在本地 `codex-1113-safari-late-window/`；第三轮保存在 `codex-1113-fsync-safari-window/`。两轮的完整原生命令窗口、HTTP 事件、截图和独立核验分别见各自 `run/device-final-review.json` 与 `run/lead-post-run-review.json`。

## 80. ASIDPNE 修正后的相机 TCR2 差异

本批第二轮使用内核提交 `14acadd1`，仅替换相机对象，保留原辅助盘、启动卷和原生采集命令。ASIDPNE=0 通过此前的 SCTLR 检查，下一处完整回读差异位于 TCR2。

| 项目 | 本轮结果 |
|---|---|
| 原生采集 | native 与主机均退出 1，投递退出 0，耗时 578 ms；prepare／CSID error=0 |
| 首次差异 | `bank=5 reg=0x10 value=0x70 expected=0x10`；`0x10` 为 TCR2，TTBR0 偏移为 `0x20` |
| 资源与像素 | 随后 SMMU error=5，资源保持 HELD=5；尚未启用 DMA，未取得 RAW |
| 清理阶段 | SCTLR 读回 `0xa5f0066 expected=0`；最后清 SCTLR 的写入尚未执行 |
| 收尾与温度 | 登记进程组全部结束，独立核验 loader idle、空常驻区、recovery 锁定与真实 LK retry=7；峰温 72.5°C |

ARM IHI0062D.c §16.5.39 将差异 `0x60` 定义为 TBI0 bit 5 与 TBI1 bit 6，涉及完整 64 位 tagged ATS 地址。冻结 trace 对象确实写入 `0x10`，后续 TCR／TTBR 写入没有重叠；本机读回两个 TBI 位为 1 的具体原因仍未知。后续按实际地址宽度与 ATS 使用条件核对真实请求，完整寄存器比较、DMA 停止、同步失败后的资源保留继续生效。

原始窗口保存在本地 `codex-1113-camera-asidpne-native-frame/`，首错位于 `returned-held.log` 的 LF13522。原生命令窗口为 LF13422～LF13529，独立核验见该轮 `run/lead-post-run-review.json`；寄存器定义与冻结指令对照保存在本地 `codex-1113-camera-tcr2-contract/`。

后续 TCR2 请求修正已通过配置并取得 CAPTURE 完成报告，RAW 读回仍失败，见[第 83 节](#83-tcr2-修正后的采集报告与-raw-读回)。

## 81. RAMFS 元数据槽位与同步等待

本批第三轮只替换开启 `RAMFS_SYNC_ORIGIN_DIAG=1` 的冻结 `ramfs.o`。其他 1,161 个 filelist 对象、10 个显式链接输入、辅助盘、启动卷及 Safari 流程保持一致，1,174 项输入核验通过。诊断代码保存在本地忽略目录，正式构建开关默认为 0。

首次完整错误来自元数据打包超过槽位有效容量：`used=33550336 needed_end=33550488 cap=33550336`。`needed_end` 是首次被拒记录的结束位置，完整所需容量尚未取得。该出口尚未执行本次 payload 或 super 写入。

| 已保存日志范围 | 结果 |
|---|---|
| 字段完整、按文本去重的诊断记录 | 41,477 条，其中 errno 28 为 41,468 条；另有 23 条交错或字段缺失记录 |
| 恢复状态 | slot 1、generation 740584、137,084 nodes |
| `metadata.lock` | `ino=2 tid=1787`，等待 14.258136 秒，errno=0 |
| `metadata.slot_limit`／`fsync.metadata` | 同一 tid 分别为 14.271794 秒与 14.271800 秒，errno=28 |
| `mapping` | `ino=14752 tid=3046`，8.002285 秒，errno=0；该阶段的具体组成仍需核对 |

上述数量仅覆盖已保存快照中的不同日志文本，多层诊断可以来自同一次同步，不能推出操作总数。`metadata.lock` 从调用 `lck_mtx_lock(&rm->rm_lock)` 前计时，到获得锁后记录；14.258 秒主要覆盖锁等待。后两项包含该等待和随后的约 13.6 ms 打包，单次 UFS 写入耗时尚未由这组数据确定。

该轮的 Safari 结果见[第 79 节](#79-单次-safari-打开后的完整观察)。controller、batch、runner 和 helper 均退出 0，helper 完成 6/6 项，server 正常结束为 -15。峰温 74.4°C，当前温度报告七份，覆盖缺口五个，没有热停止。

全部登记进程组结束后，独立核验 loader 完整 build、idle、空常驻区与 recovery 锁定通过，真实 LK retry=7。本批三轮结束，继续核对锁持有者、重复同步和元数据容量组成；保持现有数据、双 32 MiB 槽位原子性及持久化边界。

冻结来源与构建核验保存在本地 `codex-1113-fsync-safari-window/`，原始阶段记录、67 份日志清单和 14 个原生 JSON 事件见 `run/device-final-review.json` 及 `run/device-log-windows/`。后续锁等待与容量分析集中在本地 `codex-1113-fsync-result-analysis/`。

## 82. 同轮硬解报告与 24 MHz 播放时钟

本批第一轮取得播放器与离线解码的完整逐帧报告。第三轮保留同一辅助盘、样本、启动卷、参数和测法，只替换三个时钟对象；其余 1,159 个 filelist 对象保持一致。

| 项目 | 第一轮 | 24 MHz 私有候选 |
|---|---|---|
| 播放器正式退出与耗时 | 0，21,999 ms | 0，20,902 ms |
| 播放器完整报告 | 164 帧，152 帧 FNV 匹配，12 帧不同，缺 106 个 PTS | 268 帧，256 帧 FNV 匹配，12 帧不同，缺 `1/5、2/5` |
| 离线硬解 | 270 帧及所有 FNV 匹配，2,911 ms | 270 帧及所有 FNV 匹配，3,517 ms |
| 播放器原生命令窗口的 AudioSessionClock 警告 | 13 条 | 0 条 |
| 离线解码窗口的同类警告 | 0 条 | 0 条 |

两轮播放器的 12 个 FNV 差异都位于首个 GOP，差异 PTS 和实际哈希逐字相同。第三轮四段 VMC 统计合计 268 帧解码、2 帧丢弃，全部注明硬件解码；播放器已取得这 268 帧。`1/5、2/5` 对应此前的两个损坏参考帧，首个 GOP 的损坏仍需定位。

私有候选将 19.2 MHz 硬件计数换算为 24 MHz Mach ticks，并将 Mach 定时期限换算回硬件计数。用户态选择 `USER_TIMEBASE_NONE`，通过标准取时接口取得换算后的时间；硬件定时器频率保持 19.2 MHz。

iOS 26 共享缓存的直接计数指令扫描已完成，相关 USER_TIMEBASE 与 CONT_HWCLOCK 分支有标准取时路径。缓存外系统二进制、动态代码和系统调用成本仍有验证边界；本轮使用私有链接内核，发布资格尚未验证。后续生产集成见[第 86 节](#86-时钟生产集成与默认构建)。

两个原生步骤均正式退出 0，报告均完整读回。第三轮播放器收到 EOS、stalls=0，离线解码的 create／drain 硬件属性、270 个 sample、PTS、格式和 398,131,200 有效字节通过。真实 pending DRAIN、EOF FLUSH、DMA 停止与 HELD 保护继续保留，完整播放和像素验收仍失败。

本批三轮已复盘，全部登记进程组结束，三轮独立 loader 空闲、空常驻区、recovery 锁定及真实 LK retry=7 核验通过。第三轮 139 项冻结输入、101 份原始文件、归档和原始窗口均经独立核对。

第一轮数据保存在本地 `codex-1113-iris-all-callbacks/`，第三轮在 `codex-1113-audio-24mhz-iris/`；各轮独立复算见 `run/lead-post-run-review.json`。时钟源码、换算与直接计数分支检查集中在本地 `codex-1113-audio-clock-analysis/`，完整播放器代理与内核会话的 IPC 绑定仍缺直接记录。

## 83. TCR2 修正后的采集报告与 RAW 读回

本批第二轮使用内核提交 `9b5011dd`，将旁路域的 TCR2 请求设为 `AS|TBI0|TBI1`。相对上一相机轮只替换相机对象，辅助盘、启动卷和原生采集命令保持一致。

| 项目 | 本轮结果 |
|---|---|
| CAPTURE 报告 | `state=3 error=0 flags=0x3f sequence=1` |
| 帧几何 | 2592×1458，stride=3248，bayer=2 |
| 保存报告 | RAW payload 为 4,735,584 字节，含公共帧头的文件为 4,735,704 字节 |
| 正式完成与读回 | 退出行被 Wi-Fi 日志交错破坏；`native_exit=null`、host_exit=3，helper 0/3，RAW 未读回 |
| 停止与同步 | 已记录 pipeline powered down 与 SMMU bypass complete=1 |
| 验收范围 | 实际 RAW 内容、物理 CFA、连续采集吞吐与 Camera 预览均未验证 |

公共帧头按 C ABI 为 120 字节，sequence／time 偏移为 40／48；128 字节是 profile 结构大小。原冻结 parser 使用了 128 字节，本轮输入和失败结果保留原值；新的独立 parser 已校正头部、保存长度和首尾行位置。

新 parser 的 8 项主机检查、6 项消融和 2 项既有用户态回归通过，C 宿主 ABI 执行及 Darwin arm64e 编译通过。下一轮先以完整正式完成状态读回 RAW，再验证同 fd 连续 CAPTURE 与原生预览路径。

本轮 48 项冻结输入、43 份原始日志和原始窗口核验通过，独立 loader 空闲、空常驻区、recovery 锁定及真实 LK retry=7 通过。`fsr=0x400` 不命中当前源码的 fault mask，完整含义仍待核对。

相机输入与原始数据保存在本地 `codex-1113-camera-tcr2-native-frame/`，独立审核见 `run/lead-post-run-review.json`；正确帧头、RAW10 与 CFA 的主机校验集中在本地 `codex-1113-camera-readback-review/`。内核日志与 TTY 的交错问题正在通过独立私有候选验证。

## 84. RAMFS 零尾候选与 Safari 读回失败

新批第一轮保留上一 Safari 轮的辅助盘、启动卷、页面和打开接口，只替换元数据 writer 的末尾零块扫描。既有 annsh-ready 后自然等待 45 秒，随后上传并读回原生 opener。

19 份原始日志按完整语法及时间字段去重后，有 9,262 条完整 `ramfs-sync` 记录，均返回 errno=28。多层记录可以来自同一次同步，各阶段数量分别列出。

| 项目 | 已保存结果 |
|---|---|
| 恢复状态 | slot 0、generation 740621、137,110 nodes、601,571 非零块引用 |
| 首个容量拒绝 | `used=33550192 needed_end=33550344 cap=33550336` |
| `metadata.slot_limit` | 3,086 条完整返回记录 |
| `fsync.metadata`／`barrier_fsync.metadata` | 2,965／119 条完整返回记录 |
| 最大完整 `fsync.metadata` | 290,708 µs；同线程 `metadata.slot_limit` 为 290,699 µs |
| 索引数组分配 | 三组 `grow_slots`／`store.grow_slots` 记录，`Z_NOWAIT` 分配失败后返回 ENOSPC |

零尾扫描后仍触及 32 MiB 槽容量出口，实际节省字节量和完整待写容量尚未取得。本轮没有保存完整的 `metadata.lock`／`metadata.wait`／`metadata.total` 成功记录；既有诊断只输出错误或耗时至少两秒的记录，快速成功和缺失记录仍有观测边界。

opener 拉取正式退出 0，耗时 78 ms。随后 fetch 报 `expected offset 58656, got 58704`；原始 58,656 字节行前缀被相邻 fsync 日志拆开，整文件读回失败。Safari 正文、视频打开和截图均未执行，持久化成功与性能改善均未验证。

89 份原始来源、归档、三个原始字节窗口、19 份 FS 索引和 59 项冻结输入经独立核对。全部登记进程组结束，完整 loader、idle、空常驻区、recovery 锁定及真实 LK retry=7 核验通过。

本轮原始数据与独立审核位于本地 `codex-1113-ramfs-zero-tail-safari/run/`，FS 分支与去重统计位于 `codex-1113-ramfs-zero-tail-review/`。旧十秒停顿的保存内容分析见[第 73 节](#73-启动与十秒停顿的性能分析)，二者的因果关系尚未确认。

## 85. 正式相机采集完成与 Wi-Fi 日志交错

新批第二轮使用第 83 节实际 TCR2 相机对象，保留辅助盘、启动卷、参数及 `camera_test native`。相对该基线只更换三个 console／TTY 对象，并将主机 parser 校正为公共 120 字节帧头。

| 项目 | 已保存结果 |
|---|---|
| 原生采集 | 正式退出 0，2,593 ms；唯一完成记录、delivery_rc=0 |
| 采集状态 | `state=3 error=0 flags=0x3f sequence=1` |
| 保存报告 | 2592×1458，stride=3248，bayer=2，4,735,704 字节 |
| RAW 读回 | fetch 报 `expected offset 7632, got 7728`，host_exit=1 |
| 原始失败行 | 7,632 与 7,680 字节行内容连续完整，行首分别含 Wi-Fi 日志片段；7,728 字节行完整 |
| 验收边界 | 宿主 RAW、首尾行、物理 CFA、连续采集与 Camera 预览均未取得 |

实际 `annibale_wifi_say()`／`annibale_wifi_tell()` 在完整 console 捕获前仍逐字符调用 `loader_log_putc()`。这条前置路径使相机读回行进入 Wi-Fi 日志中间，严格行首解析失败。早期主机夹具只覆盖整条 console 输出，遗漏了该实际调用路径。

Wi-Fi 的 `printf` 副本还会通过 255 字节的 console print buffer 分段；本轮有一条含换行的 350 字节 peer-assoc 记录可触发该分支。只替换四个逐字符循环的私有候选通过短 scan 记录复现，长记录仍失败，后续继续修正完整记录的输出路径。

本轮 74 项冻结输入、67 份原始来源、归档和三个原始窗口经独立核对。全部六个登记进程组结束，完整 loader、idle、空常驻区、recovery 锁定及真实 LK retry=7 核验通过；未重跑失败轮。

本轮原始数据与独立审核位于本地 `codex-1113-camera-console-raw/run/`；正确 filelist 与全链接核验位于 `codex-1113-console-record-analysis/full-link/`，Wi-Fi 实际路径复现位于 `codex-1113-wifi-console-record/`。临时载荷继续保留私有诊断范围。

## 86. 时钟生产集成与默认构建

内核提交 `865b235d` 完成第 82 节时钟候选的生产集成，涉及四份 XNU 补丁、补丁清单和一份 37 行共享头。共享头复用既有 PExpert 频率字段，分别在硬件取时和 RTC 写入处转换单位。

| 入口或字段 | 当前单位与处理 |
|---|---|
| 硬件计数、decrementer 与 WFE | 保持 19.2 MHz |
| Mach 取时与期限 | 24 MHz；取时计算 `floor(5 * hardware_ticks / 4)`，写 decrementer 计算 `ceil(4 * mach_interval / 5)` |
| 用户态取时 | 发布 `USER_TIMEBASE_NONE=0`、`CONT=0`，通过标准取时接口取得 Mach ticks，关闭 EL0 原始计数器访问 |
| 其他板型与频率组合 | 转换条件不成立，取时和期限保持原值 |

`mk-ath12k.sh`、头文件导出和完整默认内核构建均退出 0。五份展开源码与私有候选逐字相同，10 个对象函数窗口及 21 个最终内核函数窗口通过核验；stripped 与 unstripped 的对应指令相同。

生产预处理确认 `ANNIBALE_IRIS_BUFFER_DIAGNOSTICS=0`，`ANNIBALE_IRIS_HOST_TEST` 未定义；本次未增加诊断默认开关。57 份封存文件与 108 个不同路径的文件身份经独立核对，最终内核没有构建目录或本机用户目录字符串。

本轮完成源码集成、整数换算、默认构建和最终产物检查，新的完整生产内核尚未上机。系统调用实际开销、可听音质、卡顿及跨时基休眠恢复仍待实测；私有候选的播放结果继续以第 82 节为准。

生产来源、整数检查、完整构建和独立审核保存在内核仓本地 `codex-1113-audio24-production/` 的 `production-review.json`、`production-clock-test-results.json`、`production-build-review.json` 与 `lead-review.json`。

## 87. 相机第三轮与原生预览的后续范围

本批第三轮只替换实际 Wi-Fi 日志的完整记录输出对象，保留第 85 节的相机、辅助盘、启动卷和命令。原生采集正式退出 0，耗时 1009 ms；完整宿主 RAW 验收仍失败。

| 项目 | 已保存结果 |
|---|---|
| 采集状态 | `state=3 error=0 flags=0x3f sequence=1`，唯一完成记录，delivery_rc=0 |
| 保存报告 | 2592×1458，stride=3248，bayer=2，4,735,704 字节 |
| RAW 读回 | `expected offset 1471056, got 1471200`；宿主未取得完整文件与首尾行 |
| 原始失败行 | 三条 RAW 数据完整，行首包含 `adreno8: page tables published...` 的分段日志 |
| 温度与收尾 | 峰温 71.7°C，六份有效温度报告、两处采样缺口；全部登记进程组结束，完整 loader、idle、空常驻区、recovery 锁定与真实 LK retry=7 通过 |

实际 `adreno8_say()` 将已格式化日志逐字符写入 loader，能够破坏严格 RAW 行首。该入口修复尚未实现；日志入口扩展已结束，后续功能验证继续使用现有工具。

cd37 的默认 Camera 请求 `PortTypeBack`、format 5，`configure:` 返回 int 0 后，`BWGraph _resolveFormats:` 返回 `-666`；停止记录为 0 frames／0 pictures。保存内容缺少具体 connection 与 requirements，尚未区分 attached-media 条件冲突和 common buffer format 解析失败。

当前前摄声明三个 profile／ISP 格式，后摄 formats 为空并提供闪光灯控制。后续独立验证原生 Camera 切换前摄后的格式解析、pool、Start 和可见帧；同 fd 连续采集、完整 RAW 与真实后摄仍各自待验。

95 项冻结输入、191 份原始来源、120,555,423 字节归档内容和五段原始窗口经独立核对。本批三轮均结束，失败轮未重跑；原始结果位于本地 `codex-1113-camera-wifi-record/`，原生 graph 分析位于 `codex-1113-camera-cd37-graph-review/`。临时诊断继续只用于私有载荷。

## 88. 原生打开与解码输出顺序

本批第一轮在 annsh-ready 后自然等待 45 秒，再使用第 79 节的原生打开接口与页面。opener 完整读回通过，Safari 正文打开正式退出 1，耗时 10,060 ms；随后完整观察 90 秒，正文 HTTP 请求为 0，视频未执行。三张相同截图均显示 Apple 启动进度与启动控制台，正文未通过验收。

第二轮保留既有辅助盘、启动卷、参数、样本和测法，只在 HFI START 前发送 `HFI_PROP_DECODE_ORDER_OUTPUT=0x0300015b`，类型为 U32、端口为 BITSTREAM、值为 1。

| 项目 | 第二轮已保存结果 |
|---|---|
| 播放器原生完成 | 退出 0，20,317 ms |
| 完整报告 | 43,728 字节，224 帧全部 FNV 匹配，`pixel_errors=0` |
| 首个 GOP | 30 帧全部存在并匹配参考，第 82 节的 12 个差异 PTS 在本轮匹配 |
| 缺少的参考 PTS | 索引 39～84，共 46 帧；相邻采样耗时由 4,784 ms 跳至 7,953 ms，间隔 3,169 ms |
| VMC 统计 | 同一 VMC 的四段 recent stats 合计解码 270 帧，丢弃及输出迟到均为 0 |
| 离线步骤 | 主机关闭检查失败后停止，离线 decode 与报告未执行 |

播放器按 host time 向 `AVPlayerItemVideoOutput` 取得最新帧，逐幅同步计算 FNV 并运行 NSRunLoop。本轮缺口位于上述采样间隔，VMC 统计和播放器保存数量分别记录。完整固件 BUFFER token 与 VT emit 的逐帧归属仍缺，完整播放和 270 帧像素验收继续失败。

输出端口 STOP 与 CLOSE 回包在播放器 annsh 退出后完成，随后 TLB 清理成功；`iris: close done slot=1 wire=1` 位于退出后的第 8 个 LF 行。旧主机检查要求 open／close 同处原生命令起止窗口，未覆盖代理异步销毁。下一批调整为离线 decode／完整报告后再运行 player／完整报告，原报告解析、参数和内核 STOP／CLOSE／TLB／HELD 保护保持一致。

第三轮沿用第 87 节的内核、payload、辅助盘和启动卷，只将测试入口改为打开系统 Camera。annsh-ready 后自然等待 45 秒，使用盘内 `/annibale/bin/trollstorehelper open com.apple.camera`，随后取得实际截图。

| 项目 | 第三轮已保存结果 |
|---|---|
| 原生打开 | 正式退出 0，104 ms，delivery_rc=0 |
| FBS 前台状态 | Camera PID 270 已记录 `ForegroundRunning`、`foreground:[com.apple.camera]` 和 `Fullscreen` |
| 实际画面 | 首张完整 1156×2510 截图显示 SpringBoard 桌面，Wi-Fi 图标可见；该截图未显示 Camera 界面 |
| 操作与验收 | 未发送 tap 或 home，前摄未测；可见 Camera 界面与预览未通过验收 |
| 温度 | 峰温 75.6°C，未触发温控停止 |

原生 scene 同步提交可以提前发送无错误的打开完成回调，后续 scene 更新继续执行。上述打开完成、FBS 前台状态和实际画面各自保留；对应日志位置与调用路径见本地 `codex-1113-safari-native-resume/camera-helper-third-lifecycle.json`。后续通过实际桌面图标进入 Camera，再按本轮截图操作前摄切换按钮；原生 graph 与可见帧分别验收。

本批三轮全部登记进程组结束，独立 loader 空闲、空常驻区、recovery 驻留与真实 LK retry=7 核验通过。失败轮未重跑，生产源码未因上述测量调整而改变。

原始结果和独立审核保存在本地 `codex-1113-safari-console-record/`、`codex-1113-iris-order-run/`、`codex-1113-camera-native-preview/` 的本轮 `run/lead-post-run-review.json`。采样与资源所有权核对位于 `codex-1113-iris-order-result-resume/analysis.json`。

## 89. Iris 完整像素与播放验收

本次持续运行使用第 88 节的输出顺序候选，先完成离线解码，再执行 AVPlayer 播放。两个步骤的 270 个唯一 PTS 和逐帧 FNV 均匹配独立软件参考。验证覆盖同一份 1280×768、15 fps、18 秒 H.264 样本。

| 项目 | 本次保存结果 |
|---|---|
| 离线原生完成 | 退出 0，3144 ms；submitted、accepted、callbacks、frames 均为 270 |
| 离线内容 | 270 个唯一 PTS、sample 1～270、sample 与 PTS 对应、全部 FNV、duration 与错误状态通过 |
| 离线硬件 | create／drain 的 hardware=1，software=0；callback_errors、dropped、empty、pixel_errors 均为 0 |
| 像素布局 | NV12，1280×768，每帧有效字节 1,474,560，合计 398,131,200 字节 |
| 离线报告传输 | 首次读取缺少 48 字节，宿主未生成完整报告；内容结论来自已保存的完整原生回调日志 |
| 播放器原生完成 | 退出 0，18695 ms；ready、playing、advanced、ended 均为 1，stalls=0 |
| 播放器报告 | 完整读回 52,622 字节；270 帧、270 个唯一 PTS、全部 FNV 及原有完整覆盖检查通过 |
| 播放时钟 | 到达约 18.001127 秒，结束通知通过 |

| 原生播放关联 | 本次保存结果 |
|---|---|
| 进程与会话 | 播放器 PID 396、mediaplaybackd PID 353、Iris 服务 PID 290，以及同一次播放的 player／item tag、VMC 和唯一新建 decoder 已关联 |
| VMC 统计 | 四段 decoded 合计 270，dropped 与 late 均为 0 |

离线 wire 1 和播放器 wire 2 均保存了 INPUT STOP、RAW STOP、CLOSE 的请求及成功回复，随后出现各自的 `close done`。候选源码在全部 session buffers 释放成功后才输出该记录；释放要求 SMMU unmap 和 TLB 同步成功。

`video_player_test` 没有 UIView、AVPlayerLayer 或屏幕提交，本节只验收输出像素、媒体时钟、结束状态和会话关闭。可见视频播放使用 Safari 的实际画面另行验收。样本每 30 帧重复一次，逐帧校验的覆盖范围保留该内容周期限制。

内核提交 `b562c3c5` 仅增加 START 前的 `HFI_PROP_DECODE_ORDER_OUTPUT` 设置及常量定义。本次真机使用私有链接载荷，只替换一个 HFI 对象，其余 1161 个链接对象保持原内容。

| 生产与宿主验证 | 本次结果及范围 |
|---|---|
| 默认 HFI 单对象 | 编译成功，`ANNIBALE_IRIS_BUFFER_DIAGNOSTICS=0` |
| 对象字符串 | 没有本机用户目录字符串 |
| 协议与诊断场景 | 213 项协议场景和 24 项诊断场景均成功 |
| 错误变体 | 92 组变体执行的 111 个预期失败场景均被拒绝 |
| 完整默认生产内核 | 构建通过，默认 `ANNIBALE_IRIS_BUFFER_DIAGNOSTICS=0`；新的完整产物尚未上机 |
| HEVC | 本次仅验证宿主协议 |

完整默认构建、实际编译输入和最终产物检查通过，详细审核位于内核仓本地 `codex-1113-iris-order-production-build/production-build-review.json`。

| 完整默认产物 | 本次结果 |
|---|---|
| 链接与编译参数 | 1,162 条链接对象记录、1,135 条 C／C++ 编译参数通过核对 |
| 展开源码 | 202 份文件与跟踪来源一致 |
| 最终属性调用 | 属性、端口、载荷类型和值符合源码 |
| 剥离前后代码 | 两个非空代码段共 10,479,036 字节逐字一致 |
| 路径字符串 | 没有本机源码、工作区或用户目录字符串 |
| 内核字节数 | 20,569,392 |
| SHA-256 | `c0b3c30c2991c9d40a68e508ef8534e743d43927df0d599a8cf7f65270a5925a` |
| 源码提交 | `b562c3c5f1659c801636cd5a6e8e3b8b525a102d` |

完整回调、播放器报告、原始会话日志和独立审核保存在本地 `codex-1113-iris-order-result-resume/` 与 `codex-1113-iris-live/final-review/audit.json`。默认单对象编译和协议场景结果保存在内核仓本地 `codex-1113-iris-order-production-check/`，完整构建与审核位于 `codex-1113-iris-order-production-build/`。

## 90. Safari 正文与网页硬解播放

本次与第 89 节共用一次 iOS 开机，正文页和视频页通过既有原生打开接口进入。单项测试结束后系统继续运行，随后验证相机配置。

| 项目 | 本次保存结果 |
|---|---|
| 正文请求与脚本 | HTTP 200，完整写出 1,900 字节；收到 `page-ready`，attempt=0、error=0 |
| 正文实际画面 | `shot-13567.png`、`shot-15691.png` 的按钮与 JSON 可读，Wi-Fi 图标可见 |
| 视频 HTTP | 页面返回 200；MP4 范围请求返回 206，响应完整写出 |
| 首次视频结束 | `ended/complete`，time=duration=18、error=0、readyState=4；`shot-16904.png` 显示最后一帧 |
| 原生视频格式 | `avc1 (HW decoder)`，420v，1280×768 |
| 播放中画面 | 同页通过原生按钮重播，投递后 3.011／10.017 秒取得 `shot-19420.png`／`shot-19490.png`，图案位置和方向发生变化 |
| 播放中页面时钟 | 两图最后一次 `timeupdate` 分别为约 3.005／9.776 秒，paused=false、error=0 |
| 重播末图 | `shot-22345.png` 为 pause，time=duration=18、error=0；播放按钮动作正式退出 0，136 ms |
| 原生硬解归属 | Iris 插件 PID 290、wire 4、对应 VMC 与 `com.apple.WebKit(697)` 播放路径关联 |
| VMC 输出统计 | 五段 decoded 合计 1+79+91+90+9=270，dropped、black-frame replacement、output-late 均为 0；末次 PTS 约 17.933 秒 |

源样本将 30 帧／2 秒的图像序列重复 9 次，烧录计时和图像索引随周期重复。两张播放中截图分别显示 0.933 秒／索引 14 与 1.933 秒／索引 29，结束画面也显示索引 29。当前结果确认周期内画面变化，整 30 帧周期的偏移仍有样本限制。

本次视频静音，音频输出继续单独验收。截图与最后一次 `timeupdate` 没有逐帧同步，可见播放的观察范围为上述三处时刻及结束状态。

本次没有新增 Safari 功能修复。原始请求、页面事件、截图和运行日志位于本地 `codex-1113-live-tests/http/` 与 `codex-1113-iris-order-result-resume/`；原生播放器归属和统计复核集中在 `codex-1113-safari-native-resume/live-safari-hardware-review.json`。

### 90.1 非周期样本的可见播放

新的 18 秒 H.264 样本保留 1280×768、15 fps、270 帧和原 AAC 包，每帧的图像、全局帧号、FNV 与 SHA-256 均不重复。重新编码改变了码率与 SPS／PPS；第二次软件解码的全部帧摘要和帧号标记通过核对。样本与独立参考位于本地 `codex-1113-safari-nonperiodic/`。

宿主在前次播放结束、活跃媒体请求为 0 后替换 HTTP 服务中的样本，页面和服务保持原值。随后同次开机执行一次原生打开，正式退出 1，耗时 10,031 ms，原接口只返回 Boolean false。

该失败调用没有新增 HTTP 请求或页面事件，视频、重播和截图均未执行。随后通过保留原生 NSError 的一次 `openURL:withOptions:error:` 调用打开同页；UnlockDevice 与 sensitive 选项保持原生调用值，返回 accepted=true，耗时约 230.201 ms，NSError 为空，正式退出 0，360 ms。前次十秒失败的具体原因仍未知。

| 非周期播放 | 本次保存结果 |
|---|---|
| 视频 HTTP | 完整写出 3,388,071 字节，实体摘要与非周期样本一致 |
| 首播结束 | `ended/complete`、time=duration=18、error=0；`shot-65622.png` 显示全局 FRAME 269／269、PTS 17.933 |
| 原生重播操作 | 同页播放按钮只触摸一次，正式退出 0，123 ms |
| 重播第一幅 | 请求在投递后约 3.042 秒，`shot-66940.png` 为 FRAME 040、PTS 2.666；页面 timeupdate 约 2.755、paused=false、error=0 |
| 重播第二幅 | 请求在投递后约 10.040 秒，`shot-67012.png` 为 FRAME 148、PTS 9.866；页面 timeupdate 约 9.777、paused=false、error=0 |
| 重播末图 | `shot-67142.png` 为 FRAME 269、PTS 17.933，页面为 pause、time=18、error=0；本次没有新增 ended 事件 |

四幅画面和页面事件经独立核对。截图请求时间、实际画面帧号与页面最后一次 timeupdate 各自保留，三者没有逐帧同步。该样本没有图像周期重复；本次复用了已运行媒体测试的开机，独立开机后的结果见第 90.3 节，音频验收继续待完成。

原始调用、HTTP 区间、截图与运行状态位于本地 `codex-1113-iris-order-result-resume/` 的 `run/lsop-safari-final-report.json`。单项结束后设备继续运行，随后以同一样本验证离线与 AVPlayer 的完整像素输出。

### 90.2 非周期样本的离线像素与播放器差异

同次开机的离线解码原生退出 0，耗时 2,463 ms。完整报告中的 270 个 PTS、原包 sample、NV12 FNV 与独立软件参考全部匹配，总有效像素为 398,131,200 字节。创建与 drain 均报告 hardware=1，software=0；读取到 EOF，未触发帧数上限。

AVPlayer 原生退出 0，耗时 18,400 ms，报告 ended=1、stalls=0、媒体时钟到达 18 秒，共取得 268 帧。完整报告第一次读取缺少一行，未重取；现有 stdout 中七条帧记录经核对，五条匹配，两条早期 B 帧存在以下差异。

| PTS | 独立参考 FNV | AVPlayer 取得的 FNV |
|---|---|---|
| 1/15 秒 | `a8988a6ef9a6fbda` | `d9cdb4ec1476dde0` |
| 2/15 秒 | `073de4a17e389c5b` | `1ca6d6e83d5ab6f2` |

上述两个摘要没有匹配参考中的其他帧。播放器完整像素验收失败，少取两帧的具体 PTS 尚未确认；硬件输出、VT 交付和 AVPlayer 取帧之间的差异来源继续待查。原生代理缓冲的定点分析未发现足以修改分配 token 或输出 token 的依据，现有缓冲、DRAIN／EOF FLUSH 与 DMA 保护保持。

独立逐帧核对与静态分析位于本地 `codex-1113-iris-nonperiodic/review.json` 和 `static-review.json`。本次设备样本的完整文件 SHA 未读回，源文件 SHA、传入字节与离线全部解码帧分别核对；单次运行快照未取得本次会话关闭归属。

### 90.3 新开机的首项媒体测试

更换 Front 相机载荷后，沿既有 annsh-ready 自然等待 45 秒，再打开同一非周期视频页。此前没有运行离线解码或 AVPlayer CLI。原生打开只执行一次，正式退出 0，耗时 1,036 ms；视频播放与重播结束后设备继续运行。

| 观察项 | 本次保存结果 |
|---|---|
| 页面传输 | HTTP 200，完整写出 1,892 字节 |
| 视频传输范围 | MP4 范围请求返回 206，实体摘要与源样本一致；两段写出抛出 `BrokenPipeError`，完整文件传输字节数未确认 |
| 首播中段 | `shot-03220.png` 显示正文、Wi-Fi 图标和 FRAME 149／PTS 9.933；页面 time 约 9.884、paused=false、error=0 |
| 首播结束 | `shot-05262.png` 为 FRAME 269／PTS 17.933，页面 `ended/complete`、time=duration=18、error=0 |
| 原生重播 | 播放按钮只触摸一次，正式退出 0，耗时 128 ms |
| 重播第一幅 | 投递后约 3.045 秒请求 `shot-06032.png`，FRAME 35／PTS 2.333；页面 time 约 2.253、paused=false、error=0 |
| 重播第二幅 | 投递后约 10.027 秒请求 `shot-06103.png`，FRAME 143／PTS 9.533；页面 time 约 9.524、paused=false、error=0 |
| 重播末图 | 投递后约 23.046 秒请求 `shot-06230.png`，FRAME 269／PTS 17.933；页面 pause、time=18、error=0，没有新增 ended 事件 |

实际图片与页面记录经独立核对，确认新开机后的正文可见及上述时刻的视频推进。视频保持静音，完整像素比较和音频继续分别验收；本次未取得可归属到该播放会话的新硬解统计。原始结果位于本地 `codex-1113-camera-native-preview/consumer-candidate/evidence/`，集中记录为 `safari-final-report.json` 和 `safari-root-visual-review.json`。

### 90.4 首个 GOP 的完整像素与交付复核

同次开机安装私有 VT 观测库后，仅运行一次 AVPlayer helper，正式退出 0，耗时 18,796 ms。新进程实际加载 UUID `0501E106-64E1-3397-B7D5-7C40659AB0AD`，与候选库一致；两份定点记录和完整报告各读取一次。

| 观察项 | 本次保存结果 |
|---|---|
| 完整播放器报告 | 268 帧、268 个唯一 PTS；241 帧的有效 NV12 FNV 匹配独立参考，27 帧失败 |
| 失败范围 | 全部位于首个 GOP 的帧 1～29；帧 0 与帧 30～269 全部匹配 |
| 缺失 PTS | `1/5` 秒与 `2/5` 秒 |
| 首批输入 | tag 1～8 的原包长度与 FNV 均匹配参考 |
| 两条早期 B 帧 | ioctl 返回后的 FNV 已与参考不同；Emit 前和 player 读取的摘要与 ioctl 阶段一致，数值见第 90.2 节 |
| 完整字节读回 | 五份 NV12 各一次上传，正式退出 0、HTTP 200；设备、回执与宿主 SHA-256／FNV 全部一致，每份 1,474,560 字节 |
| 首 I 帧 | ioctl、Emit 前、player 三份完整文件逐字相同，匹配参考 |
| B 帧文件范围 | 仅取得 player 的两份完整文件；producer 的 RAW 定点未命中，硬件输出与内核复制仍待区分 |
| 实际画面 | player 的 PTS `1/15` 秒图像有大面积灰色及残缺文字、色块，与完整参考不同 |

MP4 的 video edit list 使用 `media_time=2048`、timescale=15360。Producer 的样本 PTS／DTS 比 player 与参考多 `2/15` 秒；该偏移解释了原观测器未保存两个 B 帧的 producer RAW，不能用未命中的文件作像素判断。

首包 tag 1 后依次出现 DRAIN、首 I 帧输出和 `eof_flush pending=0`，随后才输入 tag 2～8。当前原生 `FinishDelayedFrames` 与 HFI DRAIN／RESUME 的参考帧契约继续核对；上述顺序尚未确认是首个 GOP 错误的根因。现有 DRAIN、真正 EOF FLUSH、DMA 停止及同步保护保持。

普通卸载私有 VT union 返回 errno 16（`Resource busy`），挂载与源目录保留，设备继续运行。原始报告、五份文件、edit list 解析与逐帧复核集中在本地 `codex-1113-iris-nonperiodic/experiment/run-1/`，独立记录为 `root-player-and-time-review.json`、`root-edit-list-review.json` 和 `root-five-frame-byte-review.json`。

### 90.5 首包 Finish 的离线对照

同次开机依次运行同一份私有 `video_decode_test`，输入同一份非周期 H.264。两次运行使用独立进程，仅第二次在提交首包后调用一次公共 `FinishDelayedFrames`；既有 marker 未加入中途 Wait，真正 EOF 的等待路径保持。

| 观察项 | 常规解码 | 首包后 Finish |
|---|---|---|
| 原生退出与耗时 | 0，3,836 ms | 1，3,735 ms |
| 提交／接受／回调 | 各 270 | 各 270 |
| 可用像素帧 | 270 | 268 |
| 完整像素比较 | 270 帧匹配 | 241 帧匹配，27 帧失败 |
| 失败及缺失范围 | 全部匹配 | 首个 GOP 的帧 1～29 中有 27 帧失败；帧 3、6 无像素，分别对应 PTS `1/5`、`2/5` 秒 |
| 首包后 Finish | 未调用 | 位于 submit 1 返回与 submit 2 之间，返回 0，回调计数从 0 增至 1 |
| 错误回调 | 0 | sample 2、5 均为 status=`-12909`、flags=`0x2`、bytes=0 |
| 最终状态 | hardware=1、reader EOF、最终等待返回 0 | hardware=1、reader EOF、最终等待返回 0 |

两次原生 stdout 均保存完整的 270 个 callback，sample 无重复，PTS 与参考的偏移为 0。常规解码的独立报告完整取回；首包 Finish 的独立报告取回失败，逐帧比较直接使用该次完整 stdout。27 个错误帧的 FNV 与第 90.4 节 AVPlayer 的对应帧全部相同，缺失帧也相同；帧 0 和帧 30～269 全部匹配。

公共 Finish 已在离线路径复现相同的像素与缺帧范围。随后只增加启动身份输出再执行一次首包 Finish，CLI 已加载和当前可见的 VT UUID 均为 `0501E106-64E1-3397-B7D5-7C40659AB0AD`；原生汇总仍为 270 回调、268 帧、两条错误，正式退出 1，耗时 4,184 ms。

该身份运行的 stdout 保存 269 条唯一回调，缺少 sample 251，不能用于完整 270 帧验收。实际 CLI PID 对应的 producer 文件单次读取返回 `No such file or directory`，HFI DRAIN 和 Close 归属尚未取得；运行身份及原始返回保存在本地 `codex-1113-iris-drain-native/startup-identity/run-1/`。

原始调用和复核集中在本地 `codex-1113-iris-nonperiodic/midfinish/run-1/`，逐帧记录为 `control-review.json`、`finish-first-stdout-pixel-review.json` 和 `root-finish-player-comparison.json`。设备保持运行。

### 90.6 排空恢复的输出发布顺序

[Linux 有状态解码器规范](https://docs.kernel.org/userspace-api/media/v4l/dev-decoder.html#drain)要求 Drain 后的 `V4L2_DEC_CMD_START` 保留排空前全部状态。原厂 `msm_vdec_start_cmd` 先调用 `queue_deferred_buffers` 发布 RAW 输出缓冲，成功后再调用 `msm_vidc_process_resume`；实际调用已经追踪到 `venus_hfi_queue_buffer` 的 HFI 发布。

当前 `iris_finish_drain` 先发送 BITSTREAM 和 RAW 的 RESUME，再重新发布 `IRIS_RAW_HOST` 缓冲，顺序与原厂有差异。单变量候选仅把原有 RAW 发布循环移到两个 RESUME 之前，flags、reason 和状态条件保持，净新增代码为 0 行。

独立复核确认，重新发布只覆盖 HOST 缓冲；仍由固件持有的 QUEUED 缓冲跳过。DRAIN ACK、LAST 和输入归还检查保持，发布成功后才设置 QUEUED；失败由 `iris_collect_output` 保存至 session，原有 Close 和 DMA 资源保留条件继续生效。

候选的 213 项协议用例、24 项诊断用例和 8 项定向次序及失败用例成功，92 个删除保护的变体被拒绝；原顺序在实际 HFI 次序断言失败。独立记录保存在本地 `codex-1113-iris-order-audit/`。

私有内核和载荷构建通过，当前基线内核重新链接后逐字相同。1,172 项冻结链接输入和两套 372 项编译依赖核对通过，filelist 的 1,162 个对象仅替换 Iris HFI；载荷仅 kernel entry 改变，Camera、时钟、控制台、辅助盘、启动卷与启动参数保持原值。

新候选的首包 Finish 测试取得完整回调，首 GOP 故障仍然复现。

| 观察项 | 本次保存结果 |
|---|---|
| 执行与回调 | 正式退出 1，耗时 4,181 ms；270 条唯一回调 |
| 像素 | 268 帧有像素，241 帧匹配，27 帧不匹配；帧 0 及 30–269 匹配 |
| 缺帧与错误 | 缺少第 3、6 帧；错误回调为 sample 2、5，status=-12909、flags=2、bytes=0 |
| 时间戳 | PTS 偏移为 0 |
| 错误帧对照 | 27 个错误帧的 FNV 与第 90.5 节原首包 Finish 及 AVPlayer 对应帧全部相同 |

RAW 发布顺序修改没有改变本样本的首 GOP 故障。候选继续留在私有诊断目录，下一步核对排空后的参考状态和缓冲所有权。

原厂反汇编、私有候选及输入审核集中在本地 `codex-1113-iris-drain-native/` 和其 `raw-before-resume/` 子目录。完整 stdout、逐帧复核及原测试对比分别为 `finish-after-first-native.log`、`root-runtime-CLI-review.json` 和 `root-runtime-original-comparison.json`；本项 helper 已结束，设备保持 iOS 运行。

### 90.7 原生解码的执行进程

本轮客户端实际加载的 VT 库 UUID 已确认，既有 console 的 create、start、decoder 和 session 记录位于 `videocodecd`。客户端 PID 对应的诊断文件单次读取返回 ENOENT；客户端库加载记录仅覆盖该进程。

原版 `VTDecompressionSessionCreate` 把 options 传为 NULL。原生选择逻辑在服务进程判定与本地创建偏好均为 0 的分支调用 remote wrapper，XPC 名称分别为 `com.apple.coremedia.videocodecd.decompressionsession.xpc` 和 `com.apple.coremedia.decompressionsession.xpc`；前者由原版 `com.apple.videocodecd.plist` 发布。服务端 handler 在服务进程再次调用 `CreateWithOptions`，本地创建从该进程的 FigRegistry 取得 factory。

上述静态路径与已有 console 的进程归属一致。服务端实际库 UUID 尚未取得，诊断文件写入失败仍需结合其原生 open／write 返回值判断。定向反汇编、缓存代码摘要及本轮 console 行号保存在本地 `codex-1113-iris-drain-native/execution-owner/`。

## 91. 相机 Front 原生配置

同次开机已经从桌面进入 Camera 并操作前摄切换，`shot-09687.png` 显示相机控件和隐私指示灯，预览仍为黑屏。原始截图和操作记录位于本地 `codex-1113-iris-order-result-resume/`。

原 V57 配置中的 `Front Virtual Camera` 生成 deviceType 11，请求 `PortTypeFrontSuperWide`，既有日志记录返回 -12780。新增 canonical `Front Camera` 条目沿原生名称规则生成 position 2、deviceType 2，并请求现有 `PortTypeFront`。

候选仅新增上述设备，原九个设备和其他顶层字典保持原值。三档 `420f` 输出与当前 mode4 profile、FES 几何和 fps 对应，静态来源及配置差异位于本地 `codex-1113-camera-native-preview/front-wide/source-review.json` 和 `config-review.json`。旧载荷的资源安装结果及输入边界见第 91.1 节，匹配载荷的真实采集与预览结果见第 91.2 节。

### 91.1 运行态安装与相机输入边界

私有安装 helper 通过 `com.apple.private.bindfs-allow` entitlement 执行只读资源挂载，正式退出 0，耗时 147 ms，errno=0。随后精确匹配的 Camera／cameracaptured 进程收到 SIGKILL；该命令不等待新进程启动。

图标触摸后两张完整截图相隔约 215.1 秒，均显示部分桌面和中部黑色区域，没有 Camera 控件或前摄切换按钮。没有继续切换前摄，也没有取得新的 Front／RequestStreams 记录。挂载与源文件保持原状，设备继续运行；原始结果位于本地 `codex-1113-iris-order-result-resume/` 的 `run/front-v3-install-result.json`。

本节所记旧载荷的相机输入与第 83 节的真实采集候选存在以下差异。

| 输入 | 当前轮已核对的范围 |
|---|---|
| 辅助盘媒体库 | `/annibale/lib/libannibale-media.dylib` 为旧版三 stream 库；保存到的 cameracaptured 加载 UUID 与该库一致，加载记录早于资源挂载 |
| 传感器 profile | 辅助盘缺少 `/annibale/fw/camera-ov20b-front-mode4.tab` |
| 相机内核接口 | 当前镜像只识别旧 `G_INFO`，没有 profile／CAPTURE 实现，也不发布 `FRONT_MODE4` |
| 新消费者校验 | 新媒体库要求 `FRONT_MODE4`；缺少该位会返回 `ENOTSUP` |
| 软件诊断路径 | 当前轮的 1920×1080 几何与旧软件诊断帧入口对应 |

仅安装媒体库与 profile 无法完成真实预览。匹配载荷需同时使用已验证的 TCR2 相机实现、新消费者与原厂 profile；Iris、时钟和控制台输入保留已通过的版本。后续匹配载荷的结果见第 91.2 节。

### 91.2 匹配载荷的连续 RAW 与黑屏预览

更换匹配的相机载荷后，先完成第 90.3 节的 Safari 测试，再安装 canonical Front V57 资源并精确重启 Camera／cameracaptured。五步安装全部正式退出 0，挂载 errno=0；设备继续运行。

| 观察项 | 本次保存结果 |
|---|---|
| 连续采集 | 同一 fd 完成三次 CAPTURE 与完整 read，单次 helper 正式退出 0，耗时 2,023 ms |
| 每次采集状态 | state=3、error=0、flags=0x3f，sequence 为 1、2、3，time 递增 |
| 文件与声明几何 | 每文件 4,735,704 字节，含 120 字节 `RWFRAME1` 头；2592×1458、stride=3248、RAW10、bayer=2、sensor=2 |
| 完整读回 | 三文件各一次 Wi-Fi 上传，正式退出 0、HTTP 200；设备、接收回执和宿主整文件 SHA-256 全部一致，总字节 14,207,112 |
| RAW 内容 | 三帧均很暗且有水平条纹，按声明 RAW10 解码无法辨认正常室内场景；用户确认前摄无遮挡 |
| 原生前摄操作 | 切换正式退出 0，耗时 127 ms；`shot-14268.png` 与约十秒后的 `shot-14358.png` 显示前摄控件，预览均黑屏，两份 framebuffer RAW 摘要一致 |
| 媒体库归属 | 载荷中的媒体库 UUID 已核对；本次新进程实际加载 UUID 及 pool、Start、首帧记录尚未取得 |

三份原始 RAW 的空间分布经独立核对。每份包含 9,249 个完整的 512 字节块，每块前 256 字节有数据、后 256 字节全零，另有 96 字节尾段。按声明 stride 保留原始字节偏移，仅解码完整落在有数据区域中的 RAW10 像素组，三帧范围分别为 52–82、48–84、50–82，均值约 64.8；这些读数没有确认物理 CFA 或真实场景内容。

实际运行内核的缓存维护为 `dc civac`、步长 64 字节及 `dsb sy`；读回复制每次完整复制 256 字节并同步增加源、目标地址。固定零区域的来源继续核对传感器模式、CSI 与 DMA 写入布局；完整传输和连续采集已经通过，真实图像及原生预览验收失败。

原始 RAW、接收回执和独立复核位于本地 `codex-1113-camera-live-execution/`，集中记录为 `raw-review/three-raw-host-review.json` 和 `raw-review/root-periodic-zero-review.json`。操作及预览结果位于 `codex-1113-camera-native-preview/consumer-candidate/evidence/` 的 `capture3-summary.json` 和 `front-preview-root-visual-review.json`。

### 91.3 原生打开成功后的输出配置

同次开机的独立单帧 helper 完成 profile 安装、CAPTURE 与完整 read，正式退出 0，耗时 1,068 ms。同一 fd 返回 state=3、error=0、flags=0x3f，文件长度 4,735,704 字节；该文件保存在设备，未再次上传。用户确认拍摄环境为正常室内，前摄无遮挡。

随后安装仅记录原生打开各阶段返回值的私有媒体库，并重启 Camera／cameracaptured。新进程实际加载 UUID `837C7A3A-B6D9-3F08-BAA3-BA9BA7201224`；观测默认关闭，关闭后产物与此前媒体库逐字相同。

| 观察项 | 本次保存结果 |
|---|---|
| profile 文件 | open 成功，fstat 长度 6,440，read 一次返回 6,440；errno 均为 0 |
| 原生设备打开 | 枚举及 worker 的 open 均成功；第一次 G_INFO 返回 0、flags=0x4c |
| profile 安装 | write 返回完整 6,464 字节；第二次 G_INFO 返回 0、flags=0x6c；errno 均为 0 |
| Front 请求 | 三个格式，RequestStreams 返回 0，stream 保持 WARMING=1 |
| 首帧采集 | read 返回 4,735,704；state=3、error=0、flags=0x3f、sequence=1；RAW 几何与第 91.2 节相同 |
| 原生输出 | 六个输出的 config、pool、handler 均为空，enabled=0；首帧后至归还 stream 未记录 Start 或输出配置入口 |
| 停止 | stop 记录 136 帧，worker 最终 137 帧，交付图片为 0；测试 helper 全部结束 |
| 实际预览 | 切 Front 正式退出 0，127 ms；等待约十秒后的 `shot-77653.png` 仍黑屏 |

本次原生打开与 RAW 采集已经执行，预览输出尚未进入缓冲池和回调路径。继续核对原生格式发布、RequestStreams 后的输出配置与 Start 契约，RAW 固定零区域仍按第 91.2 节独立调查。

观测文件一次完整取回 22,071 字节，包含此前进程和本次新进程的记录。本次按实际新 UUID 及 PID 选择记录，完整返回、输出字段和图像索引集中在本地 `codex-1113-camera-native-preview/native-open-runtime/run-1/device-final-review.json`，设备保持 iOS 运行。

### 91.4 控制请求后的属性调用

新增属性观测仅记录现有回调的返回值。默认关闭后的对象和签名库与第 91.3 节输入逐字相同；生产源码保持原文件。新 cameracaptured 实际加载 UUID `8B6A5E19-DB50-3CBF-9F27-B95A6F5E519F`，本次连续 100 条记录完整取回。

| 观察项 | 本次保存结果 |
|---|---|
| Front 属性与格式 | SupportedProperties 有 53 项，所查九项的 mask=0x1ff；formats 有 3 项，返回 0 |
| 控制请求 | RequestStreams 返回 0，stream 保持 WARMING；MultipleOutputSupportEnabled 设置返回 0 |
| 属性返回 | 共 9 次观测调用，status 全部为 0 |
| 后续读取 | 没有 Clock、ModuleInfo、FormatIndex 或三项输出属性回调 |
| 原生输出 | 没有 configure、pool、prepare 或 Start 记录；首次 worker 最终 136 帧，交付图片为 0 |
| 实际预览 | 切换前摄并等待约十秒后的 `shot-18741.png` 仍黑屏；helper 已结束，设备保持运行 |

原版 `BWFigCaptureDevice -requestControlOfStreams:clientPriority:` 在 RequestStreams 成功后逐流设置 MultipleOutputSupportEnabled，并返回控制请求结果。必需的 Clock 读取位于另一个方法 `BWFigVideoCaptureDevice -_initWithCaptureDevice:…`，ModuleInfo 读取位于随后的视频 stream 初始化。

当前记录已覆盖控制请求成功后的属性调用，视频包装器的必需读取尚未出现。下一步追踪 Generic Vendor 设备到视频包装器和 graph 初始化的调用关系。对应方法入口、读取位置与完整记录保存在本地 `codex-1113-camera-native-preview/output-setup-observation/` 和 `format-consumption-review/`。

### 91.5 单帧 A5 预填的保留范围

本次以已上机的 RAW-before-RESUME Iris 内核为基线，只把 Camera 提交前的预填调用由全零改为 `memset(..., 0xa5, ...)`。相机 profile、DMA 停止与同步、Iris 对象、辅助盘、启动卷和启动参数保持原输入；冻结链接输入和载荷差异经独立审核。

| 观察项 | 本次保存结果 |
|---|---|
| 单帧采集 | helper 正式退出 0，耗时 1,015 ms；STOPPED、error=0、flags=0x3f、completed=1 |
| 完整读回 | 一次 POST，正式退出 0、HTTP 200；4,735,704 字节，设备、接收回执和宿主整文件 SHA-256 相同 |
| RAW 归属 | `RWFRAME1` 的 sequence、time 与采集记录相同，保存前与宿主 RAW FNV 相同 |
| 原零区域 | 9,249 个完整 512 字节块的后 256 字节全部保留 A5，共 2,367,744 字节 |
| 其余区域 | 每块前 256 字节均有区别于预填值的数据，96 字节尾段也有数据 |
| 声明 RAW10 相位 | 保留原行首和字节偏移，共 465,016 个完整组；像素范围 52–82、均值约 64.0 |

原零区域没有显示采集内容替换预填值的结果。下一步核对 WM、CPAS 的 DMA 写入范围与字节使能，并独立确认 CPU 缓存可见性。前半段仍很暗，真实场景内容和曝光继续保留为待确认项。

原始 RAW 留在本地 `codex-1113-camera-prefill-a5/run-1/raw-frames/`，单变量构建、执行返回和独立分析集中在 `codex-1113-camera-prefill-a5-on-iris/`，完整字节统计为 `root-raw-review.json`。本项测试进程已结束，设备保持 iOS 运行。
