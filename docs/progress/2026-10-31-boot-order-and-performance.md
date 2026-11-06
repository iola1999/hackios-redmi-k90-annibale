# iOS 26 开机次序、处理器占用与滑动性能（2026-10-31）

用户在 2026-10-31 反馈：开机后主屏没有图标；没有壁纸和右上角电池图标；滑动卡、机身发热。本文按问题分组列出这一天的轮次与结论。轮次都用 `cycle.py`、四核、`gpu_coherent=1`，各轮内核的改动写在本地轮次目录的 `kernel.json`。

## 1. 轮次

| 轮次 | 内核 | 变量 | 结果 |
|---|---|---|---|
| `xpc1`、`rest1`、`rest2` | `12377-cmd24` | launchd 任务集与 `REST=1` | 见 [launchd 任务集分析](../analysis/2026-10-31-launchd-jobs-and-boot-cpu.md) |
| `hash1` | `12377-cmd24` | AIR 对 buffer 纹理按内容哈希，未变时跳过上传 | backboardd 每 1024 次刷新里 202 次上传 |
| `wait1` | `12377-cmd26` | 等 GPU 时健康检查最多每毫秒一次；`CPU_PREP` 只等该 buffer 最后一次使用 | 控制中心打开由 197 毫秒降到 25 毫秒 |
| `bo1` | `12377-cmd27` | GPU buffer 地址改为 next-fit | 帧率不变，buffer 分配不是瓶颈 |
| `mac1`、`delay1`、`log1`、`style1`、`style2`、`seed1`～`seed3`、`warm1`～`warm6` | `12377-cmd25`～`cmd31` | 开机图标的假设与开机种子 | 见 §4 |
| `bo2`～`bo4` | `12377-cmd32`、`cmd33` | GPU buffer 地址在 512 MB 内循环；`REST=1` 改为默认；温度限制逐档升降 | `bo2`、`bo3` 共 160 次翻页 GPU 没有停用；见 §2、§3 |
| `bo5`～`bo23` | `12377-cmd33`～`cmd44` | backboardd 合成路径 | 见[合成路径的处理器开销](../analysis/2026-10-31-compositor-cpu-path.md) |
| `bo18`～`bo21` | `12377-cmd42`～`cmd44` | 今天视图滚动；系统镜像加 SpotlightResources | 见 [Spotlight 崩溃循环](../analysis/2026-10-31-spotlight-crash-loop.md) |
| `bo24`～`bo42` | `12377-cmd44`～`cmd47` | 壁纸与锁屏时钟 | 见[锁屏壁纸](../analysis/2026-10-31-mercury-wallpaper.md) §4 |
| `bo43`～`bo63` | `12377-cmd48`～`cmd54` | 应用黑屏、局部重绘、Dock 玻璃、闪烁、图标回首屏、触摸、内存 | 见 §6 |

## 2. 处理器占用

`REST=1` 是 `package.py` 的开关，`bo3` 起默认打开，结论见 [launchd 任务集分析](../analysis/2026-10-31-launchd-jobs-and-boot-cpu.md) §1～§3。`bo2` 打包时漏了它，全轮处理器时间 1386 秒（`bo3` 为 309 秒），集群 0 约 70% 的时间在 3072 MHz，最高 77 °C，翻页帧率中位数 20 帧／秒。

## 3. GPU 路径的等待与温控

- 每次绘制的驱动耗时：SpringBoard 由 `rest2` 的 1233.9 微秒降到 `wait1` 的 383.9，backboardd 由 131.2 降到 96.1。`wait1` 之前 `adreno8_context_done` 每次查询都读三套 SMMU 故障寄存器、GMU 中断与 HFI 队列。
- `bo3` 的翻页帧率在约 54 与约 23 帧／秒两档之间切换，与 GPU 频率无关（160 MHz 时也有 56 帧／秒）。慢的时段对应集群 1 的温度限制：读到 70 °C 就降到最低档 1017 MHz，直到所有传感器低于 60 °C。
- `12377-cmd33` 改为逐档升降：达到 70 °C 时每 50 毫秒降一档，低于 65 °C 时每 200 毫秒升一档，之间保持，75 °C 或没有读数时直接到最低档。`bo4` 集群 1 最高 68～71 °C，没有再长时间停在最低档。
- 巡检的陷阱：主屏图标按住约 700 毫秒进入编辑模式，翻页途中进入编辑模式说明有超过 700 毫秒的停顿，之后图标持续抖动，帧率读数不能用。`bo5` 起翻页从屏幕边缘起手，并定期按主屏键。

## 4. 开机图标

首个 SpringBoard 的主线程在启动阶段等 CoreServices 的锁，lsd 在逐个读应用的 Info.plist；重启 SpringBoard 后图标全部出现。根因是每次开机 `/private/var` 都是空的，LaunchServices 数据库要重建，带开机种子的 `warm4` 首个 SpringBoard 显示全部图标。排除过的假设与改法见[每次开机都是首次开机](../analysis/2026-10-31-every-boot-is-first-boot.md)。

## 5. 观测与迭代工具

- `rwsh` 的 `cat PATH [OFFSET]`、`ls PATH`、`rm PATH`，`tools/k90auto/fetch.py` 用 `cat` 分段取回设备上的文件；`tools/k90auto/roundstat.py` 按轮次并排打印手势帧率、每次绘制的驱动耗时与 buffer 纹理上传次数。
- `tools/k90auto/prof.py --threads PID` 把 `dump PID` 的回溯按共享缓存映像命名并合并相同的栈，驱动与 AIR 的地址按 `images: driver ... air ...` 行命名；`12377-cmd28` 起回溯最多 32 帧，`usertrap=1` 只打印用户态异常。
- Android DSU：系统盘经 USB 上传约 123 秒；loader v11 起的 `oem dsu load` 从闪存读入 4.94 GB 用 1.29 秒（`bo45`），v12 起 `oem dsu crc` 加 `getvar dsu-crc` 供 `run-auto.py` 按 1 GiB 分段比对 CRC-32，不一致就改走 USB。磁盘部署见 [README](../../README.md) §4。
- 看门狗：loader v11 起在 K90 上武装，主机 180 秒不发命令就停止喂狗，`oem hang` 实测第 37 秒复位、第 60 秒回到 loader，不需要按键。完整的 loader 镜像可以从 LK 用 `fastboot boot` 引导，约 18 秒后枚举，不刷 `boot_a`，也不扣 A 槽的重试次数。
- 内核录屏：`rec_secs=N rec_ring=1 rec_mb=M` 把上屏的帧缩小后存进预留内存，`hackios-xnu-kernel/tools/recording.py` 转成视频。占着 GPU 的内核不回到 loader，要在轮次停止之前用 loader v13 起的 `oem stage ADDRESS LENGTH` 取回（`tools/k90auto/fetch-recording.sh`，402 MB 用 9.3 秒），收尾会复位。

## 6. 应用、显示与交互（`bo43`～`bo63`）

### 6.1 打开应用黑屏

- `bo44` 起 `applog` 选中的程序能输出异常文本（`12377-cmd49`）：MobileSMS 缺 ChatKit 的 `Assets.car`，`com.apple.Safari.History` 抛 `NSInvalidArgumentException`。
- 系统盘缺文件：`ios165/select-system.py` 的资源目录上限从 4 MB 提到 32 MB，XPC 服务的字符串表与图片按普通规则取，新增 191 个文件。`bo46` 起 MobileSMS 不再中止，屏幕仍黑。
- 驱动缺纹理布局：backboardd 拒收挂着所有应用场景的 `SBMainSwitcherWindow` 的 commit（「CompressedImage port is MACH_PORT_NULL!」，`bo47`）。窗口里的 ATX 壁纸快照由 ImageIO 按驱动的 `newTextureLayoutWithDescriptor` 解码，驱动返回 nil 时数据长度为 0。`redwoodmetal_texture_layout.inc` 实现纹理布局与 `newTextureWithBytesNoCopy` 后（内核子模块 `6ece701`），`bo48` 起应用正常显示。

### 6.2 局部重绘留下旧内容

- 现象（`bo48`）：backboardd 只重画变化区域时，设置里有成块的旧内容，解锁后小组件空白或变色；设 `CA_DISABLE_DIRTY_REGIONS=1` 后正常。
- `package.py` 默认整帧重画，`DIRTY_REGIONS=1` 恢复局部重绘。代价（`bo49` 对 `bo47`）：GPU 每次提交 3.38 对 1.96 毫秒，每帧送面板 910 对 393 行，帧率相当。
- 原因未查。内核按整行哈希把变化的行送到面板，没有用 swap 里的脏区域。

### 6.3 Dock 玻璃只剩边缘高光

- 原因（`bo50`、`bo51` 用 `air_debug.inc` 的开关定位）：`glass_background_no_bleed_lph` 开头读距离场（纹理 4、采样器 1），ir3 把它改成着色器启动前的预取，A830 上读到全 0，片段因覆盖率为 0 被丢弃。
- 修复：Mesa 设备表对 A830 关掉 `has_fs_tex_prefetch`（`hackios-xnu-kernel/tools/mesa/rebase-26/0006-a830-no-fs-tex-prefetch.patch`），`bo52` 起玻璃完整，帧率不变。时好时坏的现象（[锁屏壁纸](../analysis/2026-10-31-mercury-wallpaper.md) §9）与预取的关系没有核实。

### 6.4 显示控制器与交互时闪烁

- `bo53`（`fb_flip=1`，只读显示控制器）：CTL0 以命令模式驱动 INTF1（DSI0），每帧自动刷新一次，`INTF_FRAME_COUNT` 在 200 毫秒里加 25，面板在 120 Hz；VIG0、VIG1 各取 1156x2510 帧缓冲的 578 列。`bo54` 用 `fb_flip=2` 让两块帧缓冲轮流上屏，交互时仍闪烁。
- 原因：iOS 26 的 CoreAnimation 只在两块 surface 之间交替，内核在一块的像素拷完之前就放行了下一次 swap，屏幕上出现画了一半的内容。
- 修复：swap 槽位在像素拷完、录屏记下这一帧之后才放行，`fb_queue` 默认 1（`MiniIOMobileFramebuffer.cpp`，`12377-cmd52`，内核子模块 `ab31785`）。`bo55` 用户确认不再闪烁。

### 6.5 日历、时钟图标回首屏空白

- 现象（`bo57` 录屏）：从今天视图回首屏后，日历图标约 0.9 秒只有玻璃底，时钟约 1.05 秒只有指针。
- 原因：iconservicesagent 的 `-[ISGPUIdleTimer armTimer]` 定 3 秒，到时 `+[RBDevice purgeResources]` 释放 RenderBox 的全部管线，回首屏时重建 48 条。重建期间约一半的样本在 MTLCompilerService，因为 Metal 着色器磁盘缓存要用的 `_iconservices` 主目录 `/var/empty/Library/Caches` 不存在；另一半在 AIR 翻译与 ir3 编译。
- 修复：驱动按两个模块、入口名与附件形状保留渲染管线（`redwoodmetal_pipecache.inc`），48 条里 44 条复用（`bo59`）；`userland/var.skel.extra` 补上缓存目录，属主 `_iconservices`（`bo61`）。开始重画到导入图标纹理由约 1 秒降到 0.24～0.26 秒。

### 6.6 手指拖动不跟手

- 现象（`bo61`）：拖动时触摸采样相隔 36～90 毫秒。`rwtouch` 注入的手势不经过触摸芯片，手势帧率读数反映不出这一点。
- 原因：驱动每 9 毫秒看一次中断线电平，芯片不会一直拉低中断线，多数报告是每 80 毫秒一次的定时读取读到的。
- 修复：`12377-cmd53` 让 TLMM 把中断线的下降沿锁存在状态位里，驱动一并读它（`redwood_goodix.c`）。`bo62` 采样间隔中位数 9.3 毫秒，拖动期间帧率中位数 51.6 帧／秒（`bo61` 为 42.8）。
- 剩余：`touch_poll_us=4000` 实测仍约 9.2 毫秒查看一次，内核线程的睡眠精度约 9 毫秒；芯片报告率按驱动注释是 240 Hz，没有实测。

### 6.7 控制中心切到音乐时重启

- 现象（`bo62`）：backboardd 持有约 925 MB GPU 缓冲时内核报 `RedwoodGPU: no memory for a buffer`，Mesa 申请命令环失败，`fd_bo_heap_alloc` 没有检查空指针，backboardd 退出。
- 原因：内核从第一个进程起给数据分配加保护对象，大小按 2 的幂取整，GPU 的 2～8 MB 缓冲占用的地址空间是自身大小的两倍以上，到约 1 GB 时用完了 2267 MB 的数据地址区间。
- 修复：1 MB 及以上的数据分配不加保护对象（`xnu26/patches/75-osfmk%vm%vm_map_store.c.patch`，`12377-cmd54`，内核子模块 `d62d3b6`），数据区间里不存指针。`bo63` 4 次打开控制中心并翻页，GPU 内存峰值 584 MB，没有崩溃。
- 未改：`fd_bo_heap_alloc` 不检查空指针；驱动的 `setPurgeableState` 不做任何事，CoreAnimation 标成可清除的缓存纹理不会被回收；mediaremoted 反复以异常 6 退出，没有查。

### 6.8 其他

- 充电提示：`12377-cmd48` 起电量计电流在 ±50 mA 以内不算充放电。之后的充电状态见 [11-05 记录](2026-11-05-defaults-and-charging.md)。
- `REST_ALLOW=duetexpertd`（`bo19`）：duetexpertd 启动后报「Failed to initialize datavault for DuetExpertCenterAsset」，退出 16 次，之后的轮次不带它。
- ScreenContinuity 从 `bo18` 起每轮 SIGTRAP 退出 12～16 次，见 [Spotlight 崩溃循环](../analysis/2026-10-31-spotlight-crash-loop.md) §6。
