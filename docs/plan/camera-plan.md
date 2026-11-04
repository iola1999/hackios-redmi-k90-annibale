# 相机路线：annibale（REDMI K90 / SM8750 "sun"）

状态：调研稿，相机还没开始做。本文记录可复用的 redwood（POCO X5 Pro / SM7375 "yupik"）相机栈、K90 的资源与差异、分级路线和放弃准则。CAMSS 各块基址与 sensor 挂线见[硬件资源图谱](../analysis/annibale-hw-map.md) §12。

## 1. 结论

- redwood 的相机栈是端到端能跑的裸寄存器方案：内核 `redwood_camera.c` 出 RAW10 帧，mediaserverd 里的注入库冒充 H10ISP 的 FigCaptureDevice，软 ISP 出图；Camera.app 预览、拍照、点按对焦和手电都有真机回归脚本。
- 用户态没有裁剪或修改相机框架，K90 上要重写的主要在内核与资源层；这部分用户态按 iOS 16.5 写成，在 iOS 26 上要重新核对（§4.2）。
- 最大未知数是主摄 OV50E（光影猎人800，OV 定制）的上电序列、初始化寄存器表与模式表，只存在于设备的 `/vendor/lib64/camera/com.qti.sensormodule.*.bin`；`annibale-backup/` 没有 vendor 分区。
- 估算：L1（单摄预览，先 TPG 后真 sensor）3–5 周加 6–10 个真机窗口，L2（拍照）再加 2–3 周；拿不到 sensor 表就停在 TPG 演示。

## 2. redwood 相机栈

### 2.1 内核：`hackios-xnu-kernel/xnu/files/bsd/dev/redwood_camera.c`

- 纯手写寄存器驱动，不用 IOKit 相机框架和高通固件（不碰 CamX/CHI，不用 ICP 固件）。文件头注释是完整的设计说明。
- boot-arg 分级：`cam=1` 只读勘察；`cam=2` 上电读 chip ID 再下电；`cam=3` 无 sensor，CSID test pattern → RDI0 → IFE-lite0 → 内存；`cam=4` 真 sensor 帧走同一路径；`cam=5` iOS 模式，出 `/dev/redwood-camera`（接口见 `xnu/files/bsd/sys/redwood_camera.h`）。修饰项有 `cam_sensor=`、`cam_pattern=1`（彩条）、`cam_fake=1`（QEMU 假帧）等。
- 硬件路径按 yupik 写：camcc／GDSC／PLL、PM8008i 经手写 I2C 供电、CCI 位时序（含总线卡死恢复）、cam SMMU 只配一个 context；每次写都读回，失败即全下电。K90 上可复用的是骨架、日志、分级与 CCI 时序。
- sensor 初始化序列不在代码里：`hackios-xnu-kernel/tools/camsensor.py` 把 `com.qti.sensormodule.*.bin` 转成 `fw/camera-*.tab`，`tools/camtuning.py` 把 `com.qti.tuned.*.bin` 转成 `fw/camera-*.isp`，由 `userland/build.sh` 从不入库的 `../fw-camera/` 读入。

### 2.2 用户态：`hackios-xnu-userland/userland/src/`

- `inject_media.c` 注入 mediaserverd：`cam=5` 时把 `+[BWFigCaptureDeviceVendor sharedCaptureDeviceVendor]` 的 create 函数换成我们的 FigCaptureDevice；没有相机时只给 FigFlashlight 一个假 vendor（`torch=3` 接 `/dev/redwood-torch`）。
- `camera_device.c`：FigCaptureDevice 加后（wide）、前（front）两条 stream，格式名照抄 iPhone X 的 `CMCapture D22/AVCaptureSession.plist`；wide 有 VCM 点按对焦。
- `camera_isp.c`：黑电平、lens shading、grey-world AWB 加 AE、CCM、sRGB gamma；没有降噪和视频稳像。
- 回归：`rc.jobs.camera`（靠 loader 的假 `/arm-io/isp` 节点出图标）、`rc.jobs.photo`。没有录像。

## 3. K90 侧资源

来源是合并设备树 `docs/analysis/data/annibale.dts.gz`，按节点名查。图谱 §12 没有的内容：

- 节点名与 reg 不一致时以 reg 为准：CSID0 `@ad26000` 对 `0xad27000`，IFE-lite0 `@ad6c000` 对 `0xad6d000`，ICP0 `@ac05000` 对 `0xac06000`，ICP1 `@ac150000` 对 `0xac16000`（ICP L1 不用）。
- CSIPHY2 的 compatible 是 `qcom,csiphy-v2.3.0-p11`；RT-CDM 是 `cam-cdm-intf` 加 `rt-cdm2_2`×5；预留内存 `camera_region 0x9b300000+8M`、`camera_2_region 0x9bb00000+8M`。

| 角色 | 控制总线 | CSI | MCLK／reset | 供电 |
|---|---|---|---|---|
| wide（主摄，AF＋flash） | CCI0 m1 | csiphy-sd-index 3 | MCLK1 19.2 MHz（GPIO90），RESET GPIO6 | VIO 1.8 V、VDIG 1.15 V、VANA 2.8 V（`camera_wide_avdd_ldo`，GPIO127 开关）、VAF 3.1 V、BOB2 2.7 V |
| tele（AF） | CCI1 m0 | sd-index 1 | MCLK3（GPIO92），RESET 113 | VIO 1.8 V、VDIG 1.1 V、VANA 2.8 V、VAF 2.8 V |
| ultra | QUP SE8 I2C `0x880000`，slave 0x7a | sd-index 2 | MCLK2（GPIO91），RESET 3 | VIO 1.8 V、VDIG 1.0–1.2 V、VANA 2.8 V；带 `aon-camera-id` |
| front | QUP SE9 I2C `0x884000`，slave 0x10 | sd-index 4 | MCLK4（GPIO93），RESET 7 | 同构 |

- 主摄：光影猎人800 是 OmniVision OV50E 的小米定制版，50MP、1/1.55"、OIS（[fonearena 发布稿](https://www.fonearena.com/blog/467264#1)）。设备树不含型号与寄存器表，CamX 从 vendor 用户态 bin 探测加载。
- 供电轨是 RPMH PMIC LDO，走 SPMI/RPMH，redwood 的 PM8008i 手写 I2C 经验不适用。

## 4. 结构性差异与最小路线

### 4.1 SM7375 → SM8750 的差异

1. CPAS/CAMNOC/cesta 是新的必经环节：不初始化 CPAS（`0xac13000`，含 RPMH 带宽投票），titan 域起不来；redwood 没有这一步，只能靠读回加报错二分。
2. camcc 换成 `sun-camcc`，GDSC 偏移与时钟 id 要重排，多出 camnoc_rt／cesta 时钟族。
3. CSID980／IFE980 走 RT-CDM 缓冲编程；csid-lite980／ife-lite0 仍在，L1 首选复刻 redwood `cam=3/4` 的 lite 路径，先用 TPG13–15 证明通路。
4. CSIPHY v2.3.0 的 D-PHY 4 lane settle 与时序常数要真机标定。
5. wide／tele 在 CCI 上，redwood 的 CCI 代码可移植；ultra／front 在 QUP GENI I2C 上，L1 用不到。
6. SMMU 至少要配 IFE context 和 RT buffer 区（可用 `camera_region`）。

### 4.2 iOS 侧

redwood 在 iOS 16.5 上的做法：内核出 `/dev/redwood-camera`，loader 加假 `/arm-io/isp` 节点，`inject_media.c` 替换 `BWFigCaptureDeviceVendor`，Camera.app 即可预览与拍照。当前系统是 iOS 26（iPhone 17 身份），以下各项要重新核对：

- 承载 CMCapture 的进程与 vendor 的替换点。
- 属性表与 `AVCaptureSession.plist` 的机型目录（16.5 照抄的是 D22）。
- loader 假 `/arm-io/isp` 节点在 annibale loader 里的注入点。
- iOS 26 的系统进程是 arm64e，注入库要按 arm64e 构建并签名，否则 dyld 不加载。

### 4.3 分级路线

| 级别 | 内容 | 盲写比例 | 真机窗口 | 工作量 |
|---|---|---|---|---|
| L1a 通路验证 | sun-camcc／CPAS／GDSC／SMMU-ife → TPG13 或 CSID TPG → csid-lite0 → ife-lite0 → `camera_region` → `/dev/redwood-camera`，iOS 上看到彩条预览 | 约 70–80% | 4–6 个 | 2–3 周 |
| L1b 真 sensor 预览 | 从 OV50E bin 解出上电序列和一条 4032×3024@~30 的模式，CCI0 初始化 wide，同一 lite 路径出帧 | sensor 表约 50% | 再加 2–4 个 | 再加 1–2 周 |
| L2 拍照 | 全幅模式、eeprom tuning（shading／CCM）、VAF 点按对焦 | tuning 解析约 40% | 再加 3–5 个 | 再加 2–3 周 |
| 暂缓 | 录像、多摄并发、AON、HDR／多帧、IFE980 全量 CDM／UBWC、ICP／OFE | — | — | — |

## 5. 放弃与推迟准则

1. vendor 文件门：拿不到 `com.qti.sensormodule.annibale_*.bin`（或等价的 sensor 驱动），且 `cam=2` 式探针两个真机窗口内读不到 OV50E chip ID，就冻结 L1b／L2，只保留 L1a 的 TPG 演示或不做。手机下次在 Android 时 `adb pull /vendor/lib64/camera`，文件放在 `../fw-camera/`，不入库。
2. CPAS 门：CPAS/CAMNOC 初始化连续 2 个真机窗口不能让 tfe／GDSC 稳定上电，降级为「TPG 内存图加 loader 直接铺帧缓冲」的静态演示，相机整体推迟。
3. 单周真机窗口少于 1 个时只做盲写与离线校验，不启用新的硬件路径。
4. iOS 侧出现必须改用户态才能通过的新依赖时，记录后推迟，不阻塞内核分级验证。

## 6. 待办

- 在合并设备树里反查各 sensor 节点 `cam_*-supply` 的 phandle，得到 PMIC LDO 名与 SPMI 地址；四个 sensor 共用的 `cam_clk-supply = <0x5e>` 疑为 titan GDSC 的 regulator。
- 对照 AOSP `camcc-sun.c` 整理 sun camcc 的时钟 id 表，补进硬件资源图谱。
- 按 TLMM 基址（图谱 §11）把 sensor 节点里的 GPIO 换算成实际编号。
