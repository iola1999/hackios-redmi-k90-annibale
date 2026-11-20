# 相机预览停帧、照片落盘与开机图标空白的修复（2026-11-20）

本轮接续 [11-19 交接](2026-11-19-handoff.md)第 3 节，处理相机预览停帧、照片不落盘和开机后主屏图标空白三项，并推进麦克风采集。真机轮次为 `cam-a1`（内核 `12377-s6h2`）与 `cam-b1`～`cam-b5`、`cam-c1`（内核 `12377-camb1`～`12377-camc1`），启动参数均为 `modem=3 mic=4`。原始日志与截图在本地 `docs/progress/evidence/k90auto/kernel-<内核>-<轮次>/run/`。

## 1. 结果

| 事项 | 结果 | 验证范围 |
|---|---|---|
| 后摄预览停帧（`bus_ovf=0x1`） | 修复后 5 轮相机 App 预览均未再出现 `capture error` | `cam-b1`、`cam-b2`、`cam-b4`、`cam-b5`、`cam-c1`，其中四轮日志记到 300～603 帧；11-19 的 4 轮在第 4～49 帧停帧 |
| 拍照保存 | `DCIM/100APPLE` 生成 `IMG_0001.HEIC`（303,743 字节）与 `IMG_0002.HEIC`（1,577,399 字节），均为 4032×3024 | `cam-b4`、`cam-c1` 各按一次快门；画面有竖条纹且偏绿，见第 5 节 |
| 开机主屏图标与组件空白 | 修复后 5 次开机首张截图图标与组件齐全 | `cam-b2`～`cam-b5`、`cam-c1`：`cam-b2`、`cam-c1` 逐张查看，其余三轮按 Dock 区域图标像素占比与日志行判定；修复前当天 2 次开机（`cam-a1`、`cam-b1`）均空白 |
| 麦克风 | AudioReach 采集图配置、启动和读回完成，采样仍全零 | `cam-b3` 2,300 余次读回每次 1,920 字节 |

## 2. 后摄预览停帧

### 2.1 排除帧长与曝光

`camera_test` 新增 `stream` 模式：一次会话内按给定的曝光行数、增益和帧长连续取原生帧。`cam-a1` 在 `12377-s6h2` 上依次取 6 组各 30 帧，全部成功。

| 曝光行数／增益／帧长 | 结果 |
|---|---|
| 6218／256／6250 | 30/30，13.6 帧/秒 |
| 6218／256／12500 | 30/30，7.6 帧/秒 |
| 12468／256／12500 | 30/30 |
| 12468／4096／12500 | 30/30 |
| 回到 6218／256／6250，再到 12468／4096／12500 | 各 30/30 |

此前 4 次停帧都带 `fll=12500 exp=12468 gain=4096`。该组合是暗场下自动曝光的上限值，测试机后摄朝下放置，相机 App 每次都会走到这组值。独立工具在同一组值和切换过程中不停帧，停帧与相机 App 运行期间的系统负载同时出现。

### 2.2 CAMNOC 静态 QoS 未写入

`s6g-r3` 日志里 `RT1` 端口（承载 `IFE-lite`）的 QoS 寄存器保持复位值，`scm camnoc_qos(0)` 返回 `-5`。

| 寄存器 | `s6g-r3` 读数 | 原厂表（`cam_cpas_v980_100_camnoc_specific_rt`） |
|---|---|---|
| `priority_lut_low`（`0x4830`） | `0` | `0x55544444` |
| `priority_lut_high`（`0x4834`） | `0` | `0x66666665` |
| `urgency`（`0x4838`） | `0x800` | `0x1c40` |
| `danger_lut`（`0x4840`） | `0` | `0xffffff00` |
| `safe_lut`（`0x4848`） | `0xffff` | `0xf` |

本机设备树带 `enable-secure-qos-update`，原厂 `cam_cpastop_poweron` 经 `qcom_scm_camera_update_camnoc_qos(0, 0, NULL)` 由 TrustZone 写这些表。该调用带三个参数（用例号、缓冲区、字节数），参数描述按 `QCOM_SCM_ARGS(3, VAL, RW, VAL)` 取 `arginfo = 0x83`；本地没有 `qcom_scm.c` 副本，这一取值由改后调用返回 0 确认。原实现传 `1`，且只在 `cam_bcm=1` 下执行。

改动在 [annibale_camera_diag.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_camera_diag.inc) 的 `cam_cpas_qos_init()` 与 [annibale_camera.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_camera.c)：`arginfo` 改为 `0x83`，每次 CPAS 上电都执行两路 QChannel 握手和该调用。`cam-b1` 起日志为 `SCM 0x4200180a returned 0`、`scm camnoc_qos(0) st=0`。

`g2-probe` 轮（`12377-g1a`，`cam_probe=1 cam_bcm=1`）读回 `RT1` 的五个寄存器，与上表原厂值逐项相同：`0x55544444`、`0x66666665`、`0x1c40`、`0xffffff00`、`0xf`。

### 2.3 没有 comp_done 的帧不再锁死设备

原实现在帧超时后把 `/dev/annibale-camera` 留在 `HELD`，重启前无法再打开。[annibale_camera_native.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_camera_native.inc) 现在按下列顺序处理：

- 等帧期间读总线溢出状态（`0x1268`），出现新置位即以 `ENOBUFS` 结束，不再等满 1 秒；配置阶段先清状态，清不掉的旧位不计入。
- 错误为 `ETIMEDOUT` 或 `ENOBUFS` 且传感器已停流：做 CSID 全局复位，确认路径与写入器已关、FIFO 为空，然后把状态记为 `FAILED` 并释放硬件，下一次采集从头初始化。用户态原有的 3 次重试继续生效。
- 其余错误（地址不匹配、寄存器不可读）保持 `HELD`。
- 失败时多打一行 `capture failure:`，含首个 SOF 与溢出的时刻、写入器调试状态和 CAMNOC 错误记录。

这条路径本轮没有在真机上触发，验证来自宿主测试：`test-annibale-camera-native.py` 46 个场景、11 个变异被拒绝，新增超时恢复、溢出恢复、保持流下的溢出恢复、FIFO 卡住仍 `HELD`、残留溢出位不误判 5 个场景。

## 3. 拍照保存

带 `fig_notes` 的 `cam-b1` 给出快门后的首个失败点：

```
Fig assert: "inTexY" at bail (TextureUtilsV4.m:483)
(Fig) signalled err=-73465
Fig assert: "err == 0" at bail (UBProcessorV4.m:1304) - (err=-73465)
```

反汇编（`NRFV4` `0x2a10862cc`、CMImaging `FigMetalContext` `0x234e867e4`）得到的调用关系与三处缺口：

- `TextureUtils fillPaddedAreaInFrame:` 把 'xf20' 输入帧的两个平面按 16 对齐后绑定为纹理：平面 0 用 `MTLPixelFormatR10Unorm_X6`（576），平面 1 用 `MTLPixelFormatRG10Unorm_X12`（578），2352×1764 的平面按 2352×1776 请求。
- `FigMetalContext` 先比较请求尺寸与「平面尺寸加右侧、底部扩展像素」，不满足就返回 nil，不调用 Metal 设备。
- `IOSurfaceClientGetExtendedPixelsOfPlane`（`0x1b2291638`）从平面结构 `+0x88` 起按右、下、左、上读取。[MiniIOSurfaceABI.h](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniIOSurfaceABI.h) 原先按左、右、上、下写入，底部 12 行被读成顶部，绑定在到达驱动前返回 nil。

修复三处：

- 内核按原生顺序写四个扩展像素字段，`test-iosurface-abi.py` 同步。
- [annibaledrawable.m](../../hackios-xnu-kernel/tools/userland-driver/annibaledrawable.m) 的 'x420'／'xf20' 双平面分支接受 576／578，纹理尺寸上限改为平面尺寸加右侧、底部扩展像素。
- [air_metal_formats.inc](../../hackios-xnu-userland/tools/mesa/air/air_metal_formats.inc) 把 576／578 映射到 `R16_UNORM`／`R16G16_UNORM`。A830 没有 `X6R10` 格式，采样值为原值的 65472/65535，写入不清低 6 位。

`cam-b4` 日志出现 `import 20: surface 186 plane 0 'xf20' 2352x1776 ... format 576`，随后 `Delivering still image ... dimensions: 4032x3024 err:0`，`DCIM/100APPLE/IMG_0001.HEIC` 落盘。

## 4. 开机后主屏图标与组件空白

### 4.1 现场

`cam-a1` 开机 15 分钟后主屏仍只有壁纸、Dock 底板、搜索栏和图标文字。SpringBoard 与 iconservicesagent 的线程全部处于等待，`SBIconImageView` 图层没有子层。左右翻页不恢复；打开「设置」再回到主屏，图标与组件立即出现，iconservicesagent 只多用 0.07 秒 CPU。

### 4.2 原因

23G90 的 `SBHomeScreenController` 在 `iconOcclusionReasons` 带锁屏位 `0x10` 期间推迟图标与组件内容。该位有两个写入方：

- `_lockScreenUIWillDismiss:`（`0x224b43ad0`）收到 `SBLockScreenUIWillDismissNotification` 后清位。
- `publisher:didUpdateLayout:withTransition:`（`0x2241fda58`）在回调里按布局元素算出掩码，再向主队列异步投递块执行 `(old & ~0x30) | mask`；布局里有 `com.apple.lock-screen` 元素则掩码带 `0x10`。

注入库在开机约 16 秒调用 `unlockUIFromSource:withOptions:`。此刻带锁屏元素的首个布局回调可能尚未投递，它的块排在清位之后执行，`0x10` 被重新置位。主屏静止期间没有新的布局回调，直到打开应用才重新计算。iPhone 上首个布局远早于用户能解锁的时刻。

### 4.3 修复

[inject_sb26.c](../../hackios-xnu-userland/userland/src/inject/inject_sb26.c) 在解锁前读 `SBHomeScreenController.windowScene.displayLayoutPublisher.currentLayout.elements`，等到其中出现 `com.apple.lock-screen`，再让出一轮主队列后调用解锁；最多等 20 次，超出后照常解锁并打印。解锁 3 秒后打印 `iconOcclusionReasons` 供巡检。未改动任何界面状态。

5 次开机日志一致：

```
sb26: unlock boot: waiting for the lock screen's layout element (wait=1)
sb26: unlock boot: answer=1 locked_after=0
sb26: boot unlock done after 3 attempts
sb26: icons: occlusion reasons 0, lock screen element in the layout 0
```

## 5. 未解决与新发现

1. **快门期间 GPU 停转**：已修复，见第 7 节。
2. **照片画质**：两张照片能辨认场景，带竖条纹并整体偏绿。条纹与 `CAM-1`（`addr[8]==1` 的 256 字节块未写入）一致，偏色待单独核对。
3. **麦克风采样全零**：`SET_CFG CAP_ENC` 的参数 `0x08001006` 换成对转换器与编码器各发 `PARAM_ID_PCM_OUTPUT_FORMAT_CFG`（`0x08001008`），源端补 `HW_EP_FRAME_SIZE_FACTOR`，失败后关闭已开子图，图可正常启动并按 20 ms 读回。另试过三项，结果不变并已撤回：追加 `lpass_audio_hw_vote` 与 `TX MCLK`（`0x30c`）请求；把 0 号抽取器输入依次切到 DMIC0～DMIC5。VA 宏回读为 `MCLK 0x1`、`FS_CNT 0x1`、`TOP_CFG0 0x2`、`DMIC_CTL 0xb`、`ADC_MUX0 0x10/0`、`TX0 0x24/0xc0`，LPI 引脚 6～9 为 `0x6c4/0x2`、`0x4c4/0`。下一步确认 DMIC 时钟脚是否有输出，以及 `CODEC_DMA` 接口取值。
4. **蜂窝 `DMS` 停在 `OFFLINE`**：只做了代码与日志核对。`s6h-r2` 日志中 MPSS 只打开 `modemst1`／`modemst2`，各读一次后写入内存副本；`offline_reason=0`。APPS 侧未提供 TFTP（QRTR 服务 `0x1000`）与 `servreg_notify`（`0x42`），对 `tms/servreg` 的域查询返回 7 项。这些是候选，本轮没有做对照实验。
5. **宿主测试现状**：`tools/run-host-tests.py` 全量为 130 通过、14 跳过、4 失败。4 项失败在本轮改动前的提交上同样失败：`test-annibale-cpufreq.py`、`test-annibale-iris-return.py`、`test-wrapped-surface.py`、`test-air-view-writeback.py`。`test-annibale-audio-intents.py` 因常量筛选漏掉 `PRM_CMD_` 而失败，已修。
6. **CAMNOC QoS 读回**：见第 2.2 节。

## 6. 设备状态

`g1a-r3` 结束后设备留在 iOS 主屏（内核 `12377-g1a`），相机已退出，日志中没有 GPU 停转与 SpringBoard 重启记录。

## 7. 快门期间 GPU 停转

### 7.1 复现与现场

在 `12377-camc1` 上，相机预览 15 秒后间隔 8 秒连按 6 次快门全部正常；预览 75 秒后间隔 7 秒，第 2 次快门时 GPU 停转。两份现场给出同一个提交：

| 现场 | 内核给出的结束原因 | 当时的 GPU |
|---|---|---|
| `cam-b5` | `EOP timeout waiting for 5051`，随后 `submissions closed` | `RBBM_STATUS 0xec1625`，CP 仍在执行 cameracaptured 的单 IB 提交（`0x12f` 字，一次全幅 2352×1776 绘制，4 个纹理） |
| `cam-c1` 复现 | `AnnibaleGPU no answer; last 204186, retired 204182; SMMU fault 0` | 转储时 `RBBM_STATUS 0x1`、各级 IB 剩余为 0，CP 已空闲 |

此前记录里的两个读数不表示地址故障：`UCHE_CLIENT_PF = 0x81` 是初始化写入的值，`SMMU fault 1` 来自提交关闭后置位的内存失败标志，SMMU 故障检查为 `no fault bits set`。`cam-b5` 只按到一次快门。

### 7.2 原因

拍照处理链的降噪融合阶段在一次提交里做全幅绘制，GPU 在低档位时要跑数秒。修复后内核对超过 250 ms 的提交打印一行，三轮读数为 0.4～5.8 秒：

```
adreno8: submission 4785 ran 1391 ms on the GPU
adreno8: submission 5859 ran 5844 ms on the GPU
adreno8: submission 6304 ran 4418 ms on the GPU
```

内核有两处按固定时限把仍在执行的提交判为挂死，并永久关闭提交：

- `adreno8_speed_tick()` 换档前调用 `adreno8_context_wait_idle()`，等待 2 秒未完成即 `context_fail("EOP timeout")`。
- `AnnibaleGPU.cpp` 的 `gpuWait()` 在一次不少于 1 秒的等待落空后报告 `no answer` 并置 `gGPUReported`。

GPU 停止后 backboardd 在 `libannibaleair` 内解引用空指针退出（崩溃报告栈：`subpass_create`、`build_prog_fb_rast`），SpringBoard 随之反复重启。

### 7.3 修复

- [adreno8_context.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/adreno8/adreno8_context.c)：等待时间戳的失败判据改为「管线末端时间戳连续 30 秒没有前进」。GMU 上报的挂死（HFI 150）仍经完成轮询立即结束等待。新增 `adreno8_context_drained()`：限时等待在途提交，未完成返回假且不关闭任何东西。
- [adreno8_hfi.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/adreno8/adreno8_hfi.c)：`adreno8_speed_tick()` 换档前改用上述限时等待（20 ms），提交仍在执行则保持档位，下个周期再试；超过 250 ms 的提交打印时长。
- [AnnibaleGPU.cpp](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/AnnibaleGPU.cpp)：`gpuWait()` 超时只向调用方返回失败；已完成时间戳在这类等待之间连续 30 秒不变才报告 `no answer`。

宿主测试：`test-adreno8-context.py`（新增限时等待未完成不关闭的场景）、`test-adreno8-hfi.py`、`test-annibale-gpu-dispatch.py`、`test-annibale-gpu-lifetime.py` 通过。

### 7.4 验收

内核 `12377-g1a`，每轮预览 75 秒后连按快门：

| 轮次 | 点击 | 相机接受 | 落盘 | 节点错误 | 最长提交 | GPU 停转／SpringBoard 重启 |
|---|---|---|---|---|---|---|
| `g1a-r1`（间隔 7 秒） | 6 | 5 | 5 | 0 | 5,844 ms | 无 |
| `g1a-r2`（间隔 12 秒） | 7 | 7 | 7 | 0 | 4,994 ms | 无 |
| `g1a-r3`（间隔 12 秒） | 7 | 7 | 7 | 0 | 3,726 ms | 无 |

`g1a-r1` 有一次点击落在上一张仍在处理期间，相机没有发起拍摄。

未解决的相邻问题：

- 带 `gpu_tl=1` 的 `g1-tl` 轮在 GPU 正常运行时 backboardd 崩溃一次（`fd_submit_append_bo` 中哈希表为空，调用自 `fd_batch_resource_read_slowpath`），SpringBoard 随之重启一次。原因未查。
- 单张照片的 GPU 处理要 1.4～5.8 秒，期间再按快门不响应。

## 8. 后摄 256 字节半块未写入（CAM-1）的本轮结果

`g2-probe` 与 `g2-prefetch` 两轮用 `camera_test native-back` 取单帧，结果相同：24,000 个 256 字节块中 `addr[8]==0` 的 12,000 块写入，`addr[8]==1` 的 12,000 块全零；`CAMNOC_RT` 错误记录为 `ERRLOG0=0x114`、`ERRLOG1=0x11`、`SBM=0x111101`。照片的竖条纹来自这里。

| 变量 | 轮次 | 结果 |
|---|---|---|
| `MM1`／`MM0`／`SH1`／`SH0`／`MC0`／`ACV` 六项 BCM 票（APPS RSC） | `g2-probe` | 六项返回成功，条纹不变 |
| RT 与 NRT 两路 QChannel | `g2-probe` | 均为 `0x1/0x1`，不变 |
| TrustZone 静态 QoS | `g2-probe` | `RT1` 寄存器与原厂表一致，不变 |
| 写入器 `mmu_prefetch`（`cam_wm_prefetch=1`） | `g2-prefetch` | 不变 |

同轮只读探针：`cam_hf_qtb` 的 fence 请求与应答为 0，两个端口的在途事务快照为 0；`MMSS_NOC` 上 `qnm_camnoc_hf` 两个端口的 QoS 寄存器相同；`apps_smmu` 全局故障寄存器为 0。

剩余候选，均未验证：

- Android 运行态的互连表里，后摄的带宽票全部投在 `cam_ife_2` 这个 DRV 的节点上（`qnm_camnoc_hf_cam_ife_2` 等各 3,125,025 kbps），APPS 侧 `qnm_camnoc_hf` 只有 2,098 kbps。本移植只经 APPS RSC 投票，没有经 `cam_rsc`（`0xadc8000`）的 DRV 投票。
- Android 后摄走 `TFE2`（`0xaca6000`，CAMNOC `RT0` 端口），`IFE-lite` 在 Android 运行态没有启用。改走 `TFE2` 需要重写取帧路径，放到连续流改造时一起评估。
- `cam_hf_qtb` 的 ECATS 地址翻译探针没有做。

照片偏绿需要后摄对着白墙或灰卡测量三通道均值，测试机后摄朝下放置，本轮没有测。「照片」App 打开刚拍的照片也没有验证。

## 9. 麦克风采样全零（M8）的本轮结果

四轮（`g3a-r1`～`g3d-r1`，内核 `12377-g3a`～`12377-g3d`）只加探针，探针已全部撤回，内核源码与 `12377-g1a` 相同。验收未达到：`record_test` 仍为 `peak 0 of 32768`。

| 检查 | 读数 | 结论 |
|---|---|---|
| DMIC 时钟与数据脚（LPI `gpio6`～`gpio9`、`gpio12`、`gpio13`，采集图运行中各读 4,096 次） | 时钟脚 906～1,299 次翻转，数据脚 2,121～2,200 次翻转，高电平约占一半 | 麦克风在输出 PDM 数据 |
| VA 宏寄存器回读 | `MCLK 0x1`、`FS_CNT 0x1`、`TOP_CFG0 0x2`、`DMIC_CTL 0xb`×3、`ADC_MUX0 0x10/0`、`TX0 0x24/0xc0/0xb/0`、`0x410 0x4`、`0x418 0x1` | 写入值均已生效 |
| `CODEC_DMA` 接口取值（每组关闭后重开子图） | VA 的 TX0／TX1／TX2、通道掩码 3 与 `0xf`、RXTX 的 TX0～TX3，共九组 | 全部 `peak 0`；掩码多于一路时 `START SG_MIC` 首次返回 `0x1` |
| 共享内存读回位置（提交读请求前把该槽填 `0xa5`） | 完成后整槽 1,920 字节变为 `0x00`，`flags 0x14` | DSP 写入了本驱动读取的位置，写入的内容是零 |

`lpaif_type = 3`（VA）与 `intf_index = 1`（TX0）与 Linux `audioreach.h` 的定义一致。读回缓冲用写合并方式映射，不经过数据缓存。

剩余候选，均未验证：

- VA 宏抽取器到 LPAIF 之间没有数据：原厂流程除 `VA MCLK`（`0x307`）外是否还请求 2X 或 NPL 时钟，需要对照原厂 `lpass-cdc-va-macro` 模块核对。
- `SG_MIC` 子图的方向与场景属性。
- 源端未发送 `PARAM_ID_HW_EP_POWER_MODE_CFG`（`0x8001176`）与 `PARAM_ID_HW_EP_DMA_DATA_ALIGN`（`0x08001233`）。

需要人确认的听感清单（采到非零波形后）：对着手机说话时录音回放是否清晰、有无爆音；上下两个麦克风各自是否有声。

