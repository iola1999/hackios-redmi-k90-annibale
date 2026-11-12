# 相机路线：annibale（REDMI K90 / SM8750 "sun"）

本文保留早期相机栈设计与设备树资源分析。当前传感器身份、原生会话和真机结果见[多媒体验证](../analysis/2026-11-11-multimedia-validation.md)，未完成事项集中在[多媒体待办](../backlog/multimedia.md)。CAMSS 各块基址与 sensor 连接见[硬件资源图谱](../analysis/annibale-hw-map.md) §12。

## 1. 结论

- 相机栈采用裸寄存器方案：内核 `annibale_camera.c` 出 RAW10 帧，mediaserverd／cameracaptured 里的注入库冒充 H10ISP 的 FigCaptureDevice，软 ISP 出图；Camera.app 预览、拍照、点按对焦和手电都有回归脚本。
- 用户态没有裁剪或修改相机框架，K90 上主要适配内核 CAMSS 寄存器与 iOS 26 CMCapture 契约（§4.2）。
- 早期资料按 OV50E（光影猎人 800，OV 定制）分析主摄，模式表来源为设备的 `/vendor/lib64/camera/com.qti.sensormodule.*.bin`。当前工作以实际读取的传感器 ID 与厂商表匹配结果为准，见[多媒体验证](../analysis/2026-11-11-multimedia-validation.md)。

## 2. annibale 相机栈

### 2.1 内核：`hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_camera.c`

- 纯手写寄存器驱动，不用 IOKit 相机框架和高通固件（不碰 CamX/CHI，不用 ICP 固件）。文件头注释是完整的设计说明。
- boot-arg 分级：`cam=1` 只读勘察；`cam=2` 上电读 chip ID 再下电；`cam=3` 无 sensor，CSID test pattern → RDI0 → IFE-lite0 → 内存；`cam=4` 真 sensor 帧走同一路径；`cam=5` iOS 模式，出 `/dev/annibale-camera`（接口见 `xnu/files/bsd/sys/annibale_camera.h`）。修饰项有 `cam_sensor=`、`cam_pattern=1`（彩条）、`cam_fake=1`（QEMU 假帧）等。
- 硬件路径包含 `sun-camcc`／CPAS／GDSC／PLL、SPMI LDO 供电、CCI 位时序（含总线卡死恢复）、cam SMMU context 配置；每次写都读回，失败即全下电。
- sensor 初始化序列不在代码里：`hackios-xnu-kernel/tools/camsensor.py` 把 `com.qti.sensormodule.*.bin` 转成 `fw/camera-*.tab`，`tools/camtuning.py` 把 `com.qti.tuned.*.bin` 转成 `fw/camera-*.isp`，由 `userland/build.sh` 从不入库的 `../fw-camera/` 读入。

### 2.2 用户态：`hackios-xnu-userland/userland/src/`

- `inject_media.c` 注入 mediaserverd：`cam=5` 时把 `+[BWFigCaptureDeviceVendor sharedCaptureDeviceVendor]` 的 create 函数换成我们的 FigCaptureDevice；没有相机时只给 FigFlashlight 一个假 vendor（`torch=3` 接 `/dev/annibale-torch`）。
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

- 早期型号资料：发布稿将光影猎人 800 记为 OmniVision OV50E 的小米定制版，50MP、1/1.55"、OIS（[fonearena 发布稿](https://www.fonearena.com/blog/467264#1)）。设备树不含型号与寄存器表，当前适配需结合实际 chip ID 与 CamX vendor 表确认。
- 供电轨是 RPMH PMIC LDO，走 SPMI/RPMH，annibale 的 PM8008i 手写 I2C 经验不适用。

## 4. SM8750 硬件要点与最小路线

### 4.1 SM8750 硬件要点

1. CPAS/CAMNOC/cesta 是必经环节：不初始化 CPAS（`0xac13000`，含 RPMH 带宽投票），titan 域起不来；靠寄存器读回加报错二分验证。
2. camcc 为 `sun-camcc`，包含 camnoc_rt／cesta 时钟族与对应 GDSC 偏移。
3. CSID980／IFE980 走 RT-CDM 缓冲编程；csid-lite980／ife-lite0 仍在，L1 首选 `cam=3/4` 的 lite 路径，先用 TPG13–15 验证通路。
4. CSIPHY v2.3.0 的 D-PHY 4 lane settle 与时序常数要真机标定。
5. wide／tele 在 CCI 上；ultra／front 在 QUP GENI I2C 上，L1 用不到。
6. SMMU 至少要配 IFE context 和 RT buffer 区（可用 `camera_region`）。

### 4.2 iOS 侧

早期适配由 `/dev/annibale-camera`、loader 的 `/arm-io/isp` 节点及 `inject_media.c` 中的 vendor／source 替换组成。iOS 26 的承载进程、V57 格式与属性、arm64e 构建和签名要求的核查结果见[多媒体设计](../analysis/2026-11-11-multimedia-root-causes-and-design.md)与[验证结果](../analysis/2026-11-11-multimedia-validation.md)。

### 4.3 分级路线

当前按真实传感器流与 DMA（M2）、拍照与调校（M6）、硬件资料（M7）、录像与多摄（M10）分别验收，依赖、下一步和完成条件集中在[多媒体待办](../backlog/multimedia.md)。TPG 结果仅覆盖测试图路径，真实预览需要实际传感器帧。

## 5. 放弃与推迟准则

执行条件遵循[真机调试手册](device-test-playbook.md)和 [AGENTS.md](../../AGENTS.md)。设备暂不可用期间继续静态分析与构建；硬件表、供电或原生契约缺少来源的部分明确记录未知项，再安排能验证该项的设备检查。

原版用户态约束继续有效。新依赖与现有适配目标冲突时，记录具体接口和原因，再调整对应阶段的范围。厂商相机文件保存在本地，文件来源与使用方式见 §2.1。

## 6. 待办

sensor 供电 phandle、PMIC LDO／SPMI、camcc 时钟 ID 和 TLMM GPIO 核对集中在[多媒体待办 M7](../backlog/multimedia.md)。四个 sensor 共用的 `cam_clk-supply = <0x5e>` 在早期分析中推断为 titan GDSC regulator，仍需结合当前设备树和原厂驱动确认。
