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

未验证部分：`camnoc_rt_base` 只在 `cam_probe` 或 `cam_bcm` 下映射，这几轮没有读回 `RT1` 的 QoS 寄存器。停帧消失与该调用成功同时出现，寄存器实际取值留待带 `cam_probe=1` 的一轮读回。

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

1. **快门期间 GPU 停转**：`cam-b5` 预览 75 秒后间隔 7 秒按两次快门，内核报 `hang UCHE_CLIENT_PF = 0x81 (client 1: BR_SP)`、`context EOP timeout failed; submissions closed`，SpringBoard 随后反复重启，已按紧急停规则退回 loader。`cam-b4` 与 `cam-c1` 各按一次快门未出现。现场在 `kernel-12377-camb5-cam-b5/run/cam-session.log`，尚未定位到提交方与资源。
2. **照片画质**：两张照片能辨认场景，带竖条纹并整体偏绿。条纹与 `CAM-1`（`addr[8]==1` 的 256 字节块未写入）一致，偏色待单独核对。
3. **麦克风采样全零**：`SET_CFG CAP_ENC` 的参数 `0x08001006` 换成对转换器与编码器各发 `PARAM_ID_PCM_OUTPUT_FORMAT_CFG`（`0x08001008`），源端补 `HW_EP_FRAME_SIZE_FACTOR`，失败后关闭已开子图，图可正常启动并按 20 ms 读回。另试过三项，结果不变并已撤回：追加 `lpass_audio_hw_vote` 与 `TX MCLK`（`0x30c`）请求；把 0 号抽取器输入依次切到 DMIC0～DMIC5。VA 宏回读为 `MCLK 0x1`、`FS_CNT 0x1`、`TOP_CFG0 0x2`、`DMIC_CTL 0xb`、`ADC_MUX0 0x10/0`、`TX0 0x24/0xc0`，LPI 引脚 6～9 为 `0x6c4/0x2`、`0x4c4/0`。下一步确认 DMIC 时钟脚是否有输出，以及 `CODEC_DMA` 接口取值。
4. **蜂窝 `DMS` 停在 `OFFLINE`**：只做了代码与日志核对。`s6h-r2` 日志中 MPSS 只打开 `modemst1`／`modemst2`，各读一次后写入内存副本；`offline_reason=0`。APPS 侧未提供 TFTP（QRTR 服务 `0x1000`）与 `servreg_notify`（`0x42`），对 `tms/servreg` 的域查询返回 7 项。这些是候选，本轮没有做对照实验。
5. **宿主测试现状**：`tools/run-host-tests.py` 全量为 130 通过、14 跳过、4 失败。4 项失败在本轮改动前的提交上同样失败：`test-annibale-cpufreq.py`、`test-annibale-iris-return.py`、`test-wrapped-surface.py`、`test-air-view-writeback.py`。`test-annibale-audio-intents.py` 因常量筛选漏掉 `PRM_CMD_` 而失败，已修。
6. **CAMNOC QoS 读回**：见第 2.2 节。

## 6. 设备状态

`cam-c1` 结束后设备留在 iOS 主屏（内核 `12377-camc1`），相机已退出，日志中没有 GPU 停转与 SpringBoard 重启记录。
