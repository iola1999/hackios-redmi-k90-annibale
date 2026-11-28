# 2026-11-28 批 22 真机实测、PDAF 验收与调研定因（b5r67～b5r69）

本记录汇总批 22 全部已合入代码、宿主单测、三轮真机验收（`b5r67`～`b5r69`）以及离线只读定因。三轮真机全零 `panic(`、`gpu_fault`、`submissions closed`、`smmu fault`、`bus_ovf` 与 `backlight-off`，`b5r69` 结束后设备健康保持在 iOS 桌面运行态（`result: running 0 0`、`ramdisk-state: ready 1ec9000 1ec9000 300000000`）。

## 1. 构建基线与真机轮次总览

- **内核与用户态产物基线**：`12377-b22`（`hackios-xnu-kernel/out/xnu12377-b22.bin`，sha256 `1ad7d9d0b115b706fd15a6880c40d7d1176fff0fccded381df098f061ed69ea4`）、`12377-b22r2`（`21,109,328` B，sha256 `8e7aa53f51bc21744b9f75f60c20993ce5dea81ff0bcadedf1097d11f8f8949d`）、`libannibaleair.dylib`（`14,422,496` B，sha256 `e5844568ac772c3a75678b0fc782bf68bb5c77935e1ada9af2780b990873d28c`）与 `libannibale-media.dylib`（`201,216` B）。

| 轮次 | 内核与关键配置 | 核心结果与实测目录 |
|---|---|---|
| `b5r67` | `12377-b22`（默认 `cam_pdaf=1`，后开启 `ANNIBALE_G32_PROBE=1`） | 首次跑通 `OVX8000` Mode 24 `VC=1` 双通路（`wm1_cons == exp = 0x8cfbcc0`、`valid=1`）；EEPROM 因小端读数报 `eeprom invalid` 回退 CDAF（`12 moves / 969 ms`）；`g32-probe.txt` `64` 行被状态栏电池 `prim=1` 写满；录得 1 例 `locationd[71] userabort`，`docs/progress/evidence/k90auto/kernel-12377-b22-b5r67/` |
| `b5r68` | `12377-b22r2`（BE16 EEPROM + 跳过 `prim==1` 探针） | BE16 `GT24P128F` 加载成功（`6208 B, inf=325 macro=676, gain_mid=266/256, dcc_center=41.12`）；PDAF `275->182->58->16`（`disp -2.31->-3.22 px`、`sharpness 0.003`）定位出视差极性反向；Weather 下跳过 `prim==1` 后 `g32-probe.txt` 为 `0` 行，`docs/progress/evidence/k90auto/kernel-12377-b22r2-b5r68/` |
| `b5r69` | 复用 `12377-b22r2` + 修正极性 `libannibale-media.dylib` | `OVX8000` PDAF 全程零 CDAF 回退（`focus: searched = 0`）：冷启 `2 moves / 201 ms`（提速约 4.8 倍）、点按两区各 `1 move / 100–101 ms`、切前摄回后摄 `2 moves / 202 ms`，`cam_rear*.png`/`cam_front.png`/`home_final.png` 全清晰，零 `userabort`，`docs/progress/evidence/k90auto/kernel-12377-b22r2-b5r69/` |

## 2. 批 22 已合入并过审的代码与宿主单测

- **共享相机 ABI 与启动参数**：`hackios-xnu-kernel/xnu/files/bsd/sys/annibale_camera.h` 与 `hackios-xnu-userland/userland/src/services/annibale_camera.h`（各 `168` 行，双仓一致）复用 `reserved[5]` 为 `pd_width`/`pd_height`/`pd_stride`/`pd_bytes`/`pd_flags` 并新增分页 `CAMIOC_G_EEPROM`（`_IOWR('C', 3, struct annibale_camera_eeprom)`，`2064` B），保持 `sizeof(annibale_camera_frame)` 与 `RWCTAB03` SHA-256 不变；`docs/analysis/boot-args.md` 新增 `cam_pdaf`（默认 `1`，共 `184` 项）。
- **内核 PDAF 采集与队列清理**：新建 `annibale_camera_pdaf.inc`（`333` 行），接入 `annibale_camera.c`（`1089` L）、`annibale_camera_native.inc`（`734` L）与 `annibale_camera_profile.inc`（`153` L），在 `CAMERA_SLOT_SIZE` 偏移 `CAM_NATIVE_PD_OFFSET = 0x600000` 存放 `VC=1`（`RDI1 0x600 + WM1 0x1800`，不写 `0x1868`，停流/`quiesce` 排空 `WM1_FIFO` 并刷 D-cache）。
- **内核 EEPROM 读取与单测**：`annibale_camera_hw.inc`（`1010` L）新增 `cci0_m1_read_bytes()`（含失败后 `cci0_m1_init()` 复位恢复）与 OD 回退读取 `0x51`（`0x0000..0x183f`）；`test-annibale-camera-native.py`（`55 + 17` 变异）与 `test-annibale-camera-vcm.py`（`6/6`）全通过。
- **用户态 PDAF 与打包**：新建 `camera_pdaf.inc`（`344` 行）并接入 `camera_device_native.inc`（`173` L）与 `camera_device_worker.inc`（`667` L），实现 BE16 `GT24P128F` 解析、均值归一 GainMap、`8×6 Q4` DCC 双线性采样及 RAW10 L/R SAD 亚像素解算（`delta = -disparity * dcc * 2.0f`、`PDAF_MAX_ITERS = 3`）；`test-camera-pdaf.py`（`215` L，ASan+UBSan）PASS、`test-camera-device-ios26.py` `2/2` OK、`test-camera-still-pool.py` `1/1` OK，`package.py`（`1199` L）列入 `annibalemetal_g32_probe.inc` 与 `camera_pdaf.inc`。
- **`P23` PSCI 修复（待 `b5r70` 上机）**：`psci_smp.c`（`739` 行）将 `PSCI_SET_SUSPEND_MODE` 由误用的 `0x8400000E`（`PSCI_SYSTEM_SUSPEND`）修正为 `0x8400000Fu`，对 `psci_call()` 返回值与状态判别补齐 `(int32_t)` 符号扩展并打印 `PSCI_FEATURES(0x8400000Fu)`；`test-psci-idle.py`（`370` L，ASan+UBSan）通过（因每批三轮上限延至批 23 `b5r70` 实测）。
- **`G32` 门控绘制探针**：新增 `annibalemetal_g32_probe.inc`（`327` L，由 `annibalemetal_renderencoder.inc` 内联编译）与 `annibalemetal.m`（`1127` L）接入 `ANNIBALE_G32_PROBE=1`（默认关闭，支持跳过 `prim == 1` `Line` 图元）；`test-g32-probe.py`（`181` L，ASan+UBSan）`3/3` 通过。

## 3. b5r67（12377-b22）真机实测与端序定因

- **PDAF 硬件采集首通与 EEPROM 端序定位**：串口确认 `annibale_cam: pdaf: frame0 buf=0x6 top=0x2300 rdi1_path=0xe11ff8 wm1_cons=0x8cfbcc0 exp=0x8cfbcc0 wm1_fifo=0 ovf=0 valid=1`；`cci0_m1` 成功读出 `GT24P128F` `6208` B（`vendor=0x10`），因按小端解析得到 `af=41986/17665 pd_hdr=0xa00/4352x3328 dcc_h0=0x8902 dcc_v0=0x8a02`（对应大端 `0x02a4=676`、`0x0145=325`、`17×13`、`0x0289`/`0x028a`）报 `eeprom invalid` 并安全回退 CDAF（`464`, `12 moves / 969 ms`、`focus: searched 11` 行），前后摄切换与 `HELD=0`/`EBUSY=0`/`ldob8=0`/`tl: C=41` 正常。
- **`G32` 探针与健康计数**：`ANNIBALE_G32_PROBE=1` 采得 `64` 条 `g32-probe` 输出（`v=VfxLlnXh f=TcmaA2S1LlnXhfu`、`ubo1_94=0x0000/0x3bf6`、`attr0=fmt=29`、`attr3=fmt=27`），进入 Weather 前即被状态栏电池线段（`prim=1`、`sc=929,71,112,52`）占满配额；同轮 `render-report.txt` 录得 1 例 `locationd[71] userabort`。

## 4. b5r68（12377-b22r2）真机实测与极性定因

- **BE16 EEPROM 验收与极性反转验证**：串口记录 `eeprom: gt24p128f 6208 B vendor=0x10 af=676/325 pd_hdr=0xa/17x13 dcc_h0=0x289 dcc_v0=0x28a` 及 `pdaf: eeprom loaded (6208 B, inf=325 macro=676, gain_mid=266/256, dcc_center=41.12)`；PDAF 从 `275 -> 182 -> 58 -> 16`（`disp=-2.31 -> -3.07 -> -3.22 px`、`conf=336..438`、`sharpness 0.003`、`cam_rear.png` 失焦）证实 `SAD(L[x]-R[x+d])` 极性反向，而按 `-(-2.31) * 40.39 * 2.0 = +186.6` 推算 `275 + 186.6 = 462` 与 `b5r67` 实焦 `464` 仅差约 `2 DAC`。
- **`G32` 非 Line 探针输出为零**：跳过 `prim == 1` 后在 Weather 页面打开并截得 `weather_main.png`，`g32-probe.txt` 输出 `0` 条记录，排除 `backboardd` 发出非 `Line` 类型的 `VfxLln*`/`Tcma*Lln*` 绘制可能。

## 5. b5r69（复用 12377-b22r2 + 修正极性用户态）PDAF 实机验收

- **冷启后摄首次收敛**：`pdaf: eeprom loaded (6208 B, inf=325 macro=676, gain_mid=266/256, dcc_center=41.12)`、`pdaf: frame0` `wm1_cons == exp = 0x8cfc0c0 valid=1`；`focus: pdaf start at 275 -> 462 (disp -2.31 px, dcc 40.39, conf 356)` -> `iter 0 at 462 -> 471 (disp -0.11 px, delta 8.7, conf 713)` -> `the lens at 471 after 2 moves in 201 ms`（对比 `b5r67` CDAF `12 moves / 969 ms` 提速约 4.8 倍）。
- **多区域点击与切摄复测**：点按区域 1（`0.5 0.45`）`474 -> 478 -> 481`（`1 moves in 101 ms`）；点按区域 2（`0.35 0.30`）`478 -> 471 -> 467`（`1 moves in 100 ms`，`sharpness 0.786`）；切前摄再回后摄 `275 -> 462 -> 471`（`2 moves in 202 ms`，`disp -2.32 -> -0.11 px`）。全程 `focus: searched = 0`（零回退 CDAF）、`ldob8 = 0`、`tl: C = 172`、零 `userabort`，`cam_rear*.png`/`cam_front.png`/`home_final.png` 均清晰合焦。

## 6. 批 22 离线只读调研与下轮输入

- **`G32` 渐变定位收窄**：批 22 离线对比 `b5r63/backboardd.harvest`、`b5r64` 像素饱和度（`CGDrawingLayer max_sat=115` vs `SwiftUI.GradientLayer max_sat=1`）与 `b5r68` `0` 条非 `Line` `g32-probe`，确认 `backboardd 355` 在 Weather 仅构建 `VfxU10Xh`/`VfxU11Xh`/`VfxXh` + `Timg*`/`Tmua*`/`Tcim*`/`A2*`，下一步静态核查 DSC 中 `QuartzCore` `CAGradientLayer` 的渲染分发路径。
- **`P14` `sensors_pd` 与 ADSP QRTR 方案**：核查 `out/fw-adsp/adsp.b25`（`2,851,848` B）与 `adsp.b26` 已内置传感运行时，真机 `sensors_pd` 已上线 `QRTR 400 (0x190)` 与 `5017 (0x1399)`；`0` 次 `0x1000` TFTP lookup 源于 `SSCRPCD` 未就绪使标志 `0xb2e997a1 == 0` 在 `sns_file_service.c:0xb235acfc` 提前返回，且 `annibale_modem.c:251` 默认关闭 `modem_start_tftp()`；复用方案为拆出独立 `annibale_tftp.inc` 同时注册 `QRTR 0x1000` `instance=2`（ADSP，`adsp.b25` `0xb23d2b48`）与 `0`（Modem）并映射 `out/fw-sensors/` 路径，配合 FastRPC `sensorspd`/`SSCRPCD` UP 就绪。
- **`P21` `associate` `Code=-3905` 定因**：实测与 DSC 核查定位 `-3905` 来自 `wifid` `30 s` 定时器超时，根因为 `IO80211` `_eventRead` `case 9`（`0x25d45d2b8`）在事件位图或线程匹配（`0x25d45d974` 线程不一致错误）阶段跳过 `_dispatchAsyncAssocEvent` 致 `get 21 (ASSOCIATE_RESULT)` 调用数为 `0`；同时 `annibale_apple80211.c:226-229, 940-948` 固定写 `done.flags = 0` 会触发 `_dispatchAsyncAssocEvent` 的 8 秒 `get 21` 轮询超时，批 23 需一并修复投递过滤、`done.flags` 与 `get 21`。
