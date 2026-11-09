# 小米 15 iOS 26 参考仓库对照（2026-10-31）

[hakios-arm64e-dada](https://github.com/superboyyy/hakios-arm64e-dada) 在小米 15（dada，SM8750，Adreno 830）上运行 XNU 12377 和 iOS 26 arm64e 用户态，同样基于 HakiOS，由用户在 10-31 提供。本文记录离线对照后已经采用的做法和仍可借鉴的做法。11-05 核对时对方在 10-31 之后没有更新。

引用格式：`dada:路径:行号` 相对参考仓库根目录；`patch:行号` 指 `dada:kernel/xnu-12377.121.6-dada.patch`；只写文件名的在 `dada:userland/tools/mesa/air/` 或 `dada:userland/userland/src/` 下。我们的图形代码在 `hackios-xnu-kernel/tools/` 下。

## 1. 结论

- 路线：保持 AIR→NIR→freedreno 路径（§3.3）。
- 已采用：
  - 单采样 resolve 与 half 导数两处改动（§3.1）。
  - 驱动实现 `newTextureLayoutWithDescriptor` 与 `newTextureWithBytesNoCopy`（内核 `6ece701`），`bo48` 起应用正常显示。
  - GPU 调频最低 342 MHz、触摸后 1.5 秒、过热逐档下调（`12377-cmd50`），`bo47` 帧率不变。
  - 应用异常文本（§4）；看门狗、DSU、`fastboot boot`（§5）。
  - Wi-Fi 的流直通与低端 DMA 内存（§6.3），面板双缓冲（§6.5）。
- 仍可借鉴、价值较高：充电状态走 ADSP（§6.1）、蓝牙（§6.2）、根卷按需读取（§5）、Metal 设备给所有进程与着色器缓存（§4）。

## 2. 对方的实际进度

- iOS 26 上实测到进主屏、触摸、蓝牙、扬声器（`dada:README.md:20`），没有应用能打开的记录；`dada:base/docs` 的截图来自 iOS 16.5 的 POCO X5 Pro。
- 内核用 7 个核，loader 占 core 0（与我们相同）；默认上限 CPU 2.4 GHz、GPU 660 MHz（`patch:5155`）。
- 两边内核同源，对方的 SM8750 增量集中在 `hakios_dada_*.c` 和 loader。

## 3. 图形与 Metal

### 3.1 已采用的两处改动

- 单采样 resolve：对方只要 storeAction 是 resolve 且 resolveTexture 不为空，就在 endEncoding 时拷贝，不看采样数（`annibalemetal.m:5384-5394,6706-6736`）。我们在 storeAction 为 `MultisampleResolve`、loadAction 异于 Load、像素格式相同时，把 resolve 目标（按 `resolveLevel`）直接当作颜色附件；`ANNIBALE_RESOLVE_BLIT=1` 恢复旧行为。
- 导数：对方 `dfdx`、`dfdy`、`fwidth` 一律按 32 位、按像素计算（`air_intrinsics.c:533-549`），注释记录 half 操作数在 A830 上让 `fwidth.f16` 得到 inf 和 NaN。QuartzCore 里导数操作数为 half 的只有 `glass_background_*_lph` 四个函数。`AIR_COARSE_DERIVATIVES=1` 恢复旧行为。
- `bo45` 同一次开机内逐个关掉这两处，锁屏时间仍显示，时钟由指针槽改动修好（[锁屏壁纸](2026-10-31-mercury-wallpaper.md) §8）。两处保留。

### 3.2 可借鉴、还没做

- 只清屏的通道：对方没有 draw 的通道也执行 load action，每个附件只清自己（`annibalemetal.m:4766-4786`）；我们只读附件 0 的 load action，用 `PIPE_CLEAR_COLOR` 一起清。约 80 行。
- 单个 draw 失败：对方只跳过这一个（`annibalemetal.m:5129-5142`，注释写旧做法出现过黑块）；我们把整个 command buffer 标为错误。约 10 行。
- 拷贝：对方不等 fence，不同块大小走 `pipe->blit`（`air_metal.c:4400-4440`）；我们每次等 fence，要求格式相同。
- function constant：对方把求值为 false 的参数当作不存在，未用到的纹理与采样器补 null 视图（`air_to_nir.c:2492-2510`）。
- 编译：CSO 按 `nir_serialize` 加 blake3 共享（`air_metal.c:5951-6012`）；按常量特化后只翻译走到的块，注释记录 `fixed_frag_lph_cph` 从 8907 条指令降到 25 条（`air_to_nir.c:6326-6380`）。
- 缺 `air.buffer_size` 的 UBO 最多上传 16 KB（我们 64 KB）；A830 停机防护 `widen_scratch` 与 `air_cap_loops`（`air_to_nir.c:5855,5905`）。
- 编码器级别的 LOD 范围（`annibalemetal.m:3833-3870`），注释写没有它时模糊金字塔采样到正在写的那一级；我们丢掉 `lodMinClamp`、`lodMaxClamp`。约 40 行。
- 链接函数：对方读 `groups`（`annibalemetal.m:1791-1838`）；我们只按名字匹配。
- gpu2 补丁里的两项：不透明图层经 alpha 固定为 1 的视图读取，没做时壁纸发白；RenderBox 用 `RGB10A8_2P_XR10`（550/551），我们的库不认识（`dada:gpu2/patches/nativemetal-dada.patch:1317,2534`）。
- 应用相关：结构体 phi 与指针 phi、导入的 IOSurface 给可写绑定、blit 编码器补全、point_coord 做成 `VARYING_SLOT_PNTC` 输入。
- 工具：`metal_bisect` 按时间段轮流跳过一组管线的 draw，`metal_procs` 只让指定进程拿到 Metal 设备（`annibalemetal.m:4870-4920,1543-1580`）；glassref 在 Mac 上让 Apple GPU 与主机版 libannibaleair 逐像素比较同一个 draw（`dada:userland/tools/air/glassref.m`，约 1300 行，MIT）。

QuartzCore 的 `default.metallib` 是 fat 文件，抽出 AIR slice 后 189 个函数里 171 个能翻译，已加入我们的主机语料。

### 3.3 两条 Metal 路径

- 对方打镜像时选（`dada:userland/userland/build.sh:527-551`）：默认是与我们同源的 AIR 路径；`GPU2_PLUGIN=` 换成 UniXNU 前端 → Rust 写的 metal2vulkan（GPL-2.0+ 或 LGPL-3.0+）→ Turnip。gpu2 的读数：backboardd 开机建 213 条管线用 7.7 秒，每条 CoreAnimation 管线编译约 1 秒。
- 取舍：Turnip 带来现成的 resolve、GMEM 选择与管线缓存，代价是编译慢、内存占用大。上游在同一台机器上 Turnip 路线翻页 50～57 帧／秒，直连驱动 100～104（[11-05 对照](2026-11-05-upstream-lessons.md) §4）。

### 3.4 内核 GPU 驱动

- 地址空间：对方所有进程共用 15.5 GB，并记录过 3.5 GB 时海报全开就会耗尽、壁纸变黑。我们的 IOVA 是 `0x10000000`～`0xe0000000`（`adreno8_memory_private.h`）；应用黑屏时先查日志里的 `no GPU addresses`、`no page table for GPU address`、`no memory for a buffer`。
- 新表面清零后对方做 `dc civac`（`MiniIOSurface.cpp:167-181`）；我们只清零，`gpu_coherent=1` 时不受影响。
- 对方两条环加 CP 抢占、backboardd 固定在 ring 0（转写自 Linux，GPL-2.0），另有约 15 行的 `gpu_fair_ms`；我们所有进程共用一个 HWSCHED context。
- 对方读 qfprom 0x138 的速度档熔丝时整颗 SoC 停住；我们在 step 1 读同一地址（`0x221c8138`），K90 上正常，改这段时要留意。

## 4. 应用与用户态

- 应用异常文本（已采用，`12377-cmd49`）：`applog` 选中的程序 exec 时加 `ACTIVITY_LOG_STDERR=1`、`CFLOG_FORCE_STDERR=1`（对方 `patch:56222-56223`）；用法 `applog=1 applog_name=NAME[,NAME...]`。
- CoreAnimation 开关：对方的 `caenv` 在 backboardd、SpringBoard、PosterBoard 里生效（`inject26.c:764-791`），日常带 `CA_DISABLE_INLINE_SDFS=1` 等三项；我们只设进 backboardd。
- IOSurfaceSharedEvent：CoreAnimation 只在 Metal 设备支持 `MTLGPUFamilyApple7` 时才建共享事件（23G90 反汇编），我们的设备默认只声明 Apple1/Common1，这套等待没有启用，SpringBoard 日志里的 `e00002c7` 与绘制结果没有直接关系；profile 提到 Apple7 时才要实现 selector 36～41（对方 `patch:80896` 起）。
- Metal 设备给所有进程：对方 gpu2 路线每个进程都能拿到设备，沙盒进程的内存块 8 MiB（`nativemetal-dada.patch:725-731`）。我们只给 SpringBoard、backboardd、iconservicesagent、MercuryPosterExtension，应用里 `MTLCreateSystemDefaultDevice` 返回 nil。
- 任务拒绝列表：对方放行 bluetoothd、音频、locationd、datamigrator 等（`dada:userland/userland/mkjobs.py:231-241`），没有 bluetoothd 时 audiomxd 每秒查找约 16000 次。放行 datamigrator 前要补齐迁移完成标记（`build.sh:595-616`）。
- 着色器缓存与状态导出：对方进程共用 `com.annibale.m2v-shared`，镜像带上一轮导出的管线包；`stateexport` 经 GPU 导出通道取回 PosterBoard 数据与缓存，带 GPU 的轮次也能取（`stateexport.c`，`init.c:597-701`）。我们取种子的轮次不能带 GPU（[每次开机都是首次开机](2026-10-31-every-boot-is-first-boot.md) §3）。
- exec 期参数：对方 `exec_env`、`exec_swap`、`exec_log`、`exec_deny` 按程序名注入环境变量、替换程序、记录、拒绝启动（`patch:55711-55728,56067-56179`）。我们只有 `JOB_ENV`、`EXT_ENV`；蓝牙需要前两个（[蓝牙接入调研](2026-11-02-bluetooth-bringup.md) §6），约 150 行。

## 5. 引导与迭代效率

已采用（顶层 `bc20def`，实测见[开机次序与性能记录](../progress/2026-10-31-boot-order-and-performance.md) §5）：

- loader v11 起在 K90 上武装看门狗，主机 180 秒不发命令就停止喂狗（对方 `loader.c:2826-2898`）。
- 系统盘装进 Android DSU，由 loader 读入（`hackios-xnu-kernel/xnuloader/loader_dsu.inc`、`tools/k90auto/dsu.py`）；对方只发差异块的 `dsu patch` 没有移植。
- 完整 loader 镜像从 LK `fastboot boot` 起，不刷 `boot_a`，不扣 A 槽重试次数。

仍可借鉴：

- 根卷按需读取：对方内核只带小根镜像，`stage0dsu` 把 `/dev/ufs_dsu` 只读挂到 `/flash` 后切根，块读经 loader 的块服务（`stage0dsu.c`）。我们内核侧的块服务、`/dev/ufs_*` 和 `switch_root` 都有，现在整份系统盘读进内存，种子大小受内核与常驻系统盘之间的空间限制（[11-05 记录](../progress/2026-11-05-defaults-and-charging.md)）。
- 调试手段：关键日志行缓冲（`patch:86330`）、进程因信号退出时打印寄存器与帧链（`patch:87072`）、收尾时按 `stacks=` 逐线程取回溯（`patch:86230`）。
- 带 GPU 的内核回到 loader：对方复位 GMU CM3、关 GPU 的 SMMU context、停 CP 后照常返回（`hakios_dada_gpu.c:3270-3292`）。我们的 `adreno8_quiesce` 做同样四步，但要保留资源时停在 wfe，因为 GMU 留下的 RPMh 投票没有撤销，对方没有处理这一项。

## 6. 平台驱动

### 6.1 充电状态：ADSP 与 pmic_glink

- 对方经 GLINK 通道 `PMIC_RTR_ADSP_APPS` 询问充电信息。小米固件对标准 battmgr 请求答 unsupported，要用小米 MCA 协议：0x2001 充电状态、0x2002 充电器类型、0x2026/27/2a 电池包电压电流温度、0x20002 总线电压（大于 4 V 判定接了充电器）。ADSP 启动需要 `adsp.mdt` 和 `adsp_dtb.mdt`（PAS 0x24）（`patch:21571-21577,24511-24531,26026-26033`）。
- 我们：K90 的充电状态按电量计电流方向推断（`annibale_battery.c`，±50 mA 以内不算充放电）。对方用的 smem、cmd_db、ADSP 内存、IPCC、RSC 地址与 K90 设备树吻合（[K90 硬件地址表](annibale-hw-map.md)），RPMh DRV2 要和 GPU 驱动共用一把锁。ADSP 也是出声的前置（[音量与声音输出调研](2026-11-02-audio-and-volume.md)）。约 1500～2000 行。

### 6.2 蓝牙

对方做到蓝牙打开、BLE 扫描，引脚与 K90 一致，芯片不同（K90 是 kiwi，固件前缀 `hmt`）。见[蓝牙接入调研](2026-11-02-bluetooth-bringup.md)。

### 6.3 SMMU 直通与 4 GB 以下 DMA 内存

对方把外设的流（音频 0x1001、Wi-Fi 0x1401）匹配到最后一个 context bank 并设为不做翻译，loader 在 4 GB 以下预留 128 MB，用 `lowdma=` 交给内核（`patch:12025-12075`）。已用于 Wi-Fi（内核 `f72115c`，见 [Wi-Fi 固件启动记录](../progress/2026-10-31-wifi-firmware-boot.md)），音频可以沿用。

### 6.4 CPU 核数与频率

对方温控 CPU 85/80/95 °C（`patch:5009-5063`），我们 70/65/75 °C（`annibale_cpufreq.c`），阈值不变；`rate7-c7` 加 `cpus=7` 后帧率与对照轮相当（[11-02 轮次记录](../progress/2026-11-02-120hz-gpu-clock-rounds.md)）。

### 6.5 显示控制器直接扫描

对方在 splash 区放两块整帧缓冲，每帧按行拷进后台缓冲后把 SSPP 指过去（`patch:5351`）。已移植为 `fb_flip=2`（`MiniFramebufferFlip.inc`，移自 `hakios_dada_dpu.c`），是 `cycle.py` 的默认参数。

### 6.6 其他

- 电池温度封顶：对方实测电池 43～45 °C 时 iOS 把屏幕压到接近全黑，上报值封顶 35 °C 后恢复（`patch:24812`）。我们原样上报。
- DDR/LLCC：对方没开 memlat 时给 MC0、SH0 一个固定 BCM 投票，注释记录 DDR 停在最低档时每次全屏 pass 多花约 2 ms（`patch:4516,4980`）。我们只有 GPU 经 GMU 投带宽。
- Wi-Fi：对方芯片是 peach，多数轮次固件在第一次射频操作时死掉；K90 的 WCN7850 已能上网（[ath12k 驱动接入记录](../progress/2026-11-01-wifi-ath12k-driver.md)）。相机、手电、马达对方没有超过我们。

## 7. 许可

- 对方 `kernel/`、`base/`、`userland/` 是 HakiOS 的 APSL 2.0（`dada:NOTICE.md:6-8`），移植时保留版权声明；`tools/` 是 MIT，UniXNU 来源的文件是 BSD-2-Clause-Patent。
- `gpu2/` 的 metal2vulkan 是 GPL-2.0-or-later OR LGPL-3.0-or-later，本项目只参考做法，不搬代码。
- 对方的 `mk-ath12k.sh` 构建时拉取 GPL-2.0 代码。本项目的 `mk-ath12k.sh` 取 BSD-3-Clause-Clear 的 ath12k 与 FreeBSD 的 LinuxKPI 头文件（驱动接入记录 §1）。
- 对方脚本硬编码了家目录下的路径，移植时按 AGENTS.md §3 改成相对路径或参数。
