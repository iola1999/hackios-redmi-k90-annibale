# 2026-11-28 批 21 真机实测、代码交付与定因汇总（b5r64～b5r66）

本记录汇总批 21 全部已合入代码、宿主单元测试与三轮真机验收（`b5r64`～`b5r66`，均运行内核 `12377-b21`，`21,092,432` B，sha256 `03d43241fd7cfdbfe1ff60529d4bdf7c9fe33233c8a1a015c2935c1022d96b50` 与 `libannibaleair.dylib` `14,422,496` B，sha256 `e5844568ac772c3a75678b0fc782bf68bb5c77935e1ada9af2780b990873d28c`），以及同步产出的离线根因定案与批 22 输入。三轮真机全零 `panic(`、`gpu_fault`、`submissions closed`、`smmu fault` 与 `backlight-off`，`b5r66` 结束后设备继续保持在 iOS 桌面健康运行态（`result: running 0 0`、`ramdisk-state: ready 1ec9000 1ec9000 300000000`）。

## 1. 构建基线与真机轮次总览

| 轮次 | 内核与启动参数 | 打包与注入参数 | 核心结果与实测目录 |
|---|---|---|---|
| `b5r64` | `12377-b21`（默认参数） | `SB26_EXTRA="Weather"` `OSLOG="wifid"` `XPCWATCH="a80211_test"`，`--hold` | `G30` 16 槽位零拒绝、`G7` `324>256` 清零（`176` 次）、`P21` 越过 `4097` 拿到 `6` 条扫描结果（卡在 `associate -3905`）、`M3` 单次 `voldown` `0.457`/`0.45` 一致、`G32` 实证 `SwiftUI.GradientLayer` 已传 `colors=5` 与 `destOut`，`docs/progress/evidence/k90auto/kernel-12377-b21-b5r64/` |
| `b5r65` | `12377-b21` + `fb_dpu_scale=1` | 纯净基线，`--teardown` | DPU `vig0`/`vig1` QSEED3LITE 就绪并实测 `296 frames / 5002 ms`（`59 fps`）、`0` 丢翻页、单线程拷贝 `3.65–5.81 ms`；`shot-00734.png`/`shot-00891.png` 条纹源于 `oem screenshot` 按固定 `1156x2510` 误读 `stride 4864` 内存（行差均值 `16.09 -> 1.19`），安全 `--teardown` 退回，`docs/progress/evidence/k90auto/kernel-12377-b21-b5r65/` |
| `b5r66` | `12377-b21` + `psci_idle=1 psci_cl5=1` | 纯净基线 | `SET_SUSPEND_MODE(OSI)` 返 `4294967293`（`-3` `PSCI_RET_DENIED`），自动回退 `psci_cl5=0` 并维持 `psci_idle=1`（`cpu 0..3 c4 = 163158/157947/108572/79233`、`c4_err=0`、电池 `33 °C`、`cpufreq` `39.1–39.9 °C`、静置 `>45 s` 触控唤醒正常，`locationd[69] userabort` x1），`docs/progress/evidence/k90auto/kernel-12377-b21-b5r66/` |

## 2. 批 21 已合入代码与宿主验证

- **构建与打包修复**：修复 `tools/k90auto/build-air.py`（`176` 行，`FILES` 补入 `air_compute_limits_test.c`）编译产出 `libannibaleair.dylib`（`14,422,496` B）；`tools/k90auto/package.py`（`1199` 行）合入 `inject_sb26_layers_extra.inc`；`userland/build.sh COMPILE_ONLY=1` 与 `xnu12377-b21.bin` 构建全通过。
- **`G30` 阶段 3 切片 1～2（内核上下文与 HFI）**：修改 `adreno8_context_private.h`（`54` L）、`adreno8_context.c`（`832` L）、`adreno8_hfi.c`（`968` L）、`annibale_gpu_dispatch.c`（`387` L）与 `annibale_input.h`（`147` L），实现 `ADRENO8_CONTEXT_SLOTS = 16`、`[31:27]` 5-bit 槽号 + `27`-bit fence 及 `HFI 150` 非合成器单槽隔离。
- **`G30` 阶段 3 切片 1～2（IOKit 队列与宿主单测）**：修改 `AnnibaleGPU.cpp`（`1164` L）、`AnnibaleGPUMemory.inc`（`865` L）、`AnnibaleGPUSubmit.inc`（`478` L）与 `AnnibaleGPUWait.inc`（`93` L），补齐每客户端 `fQueues`/`SubmitQueue` 与 `gGPUStall[16]`；`test-adreno8-context.py`、`test-adreno8-hfi.py`、`test-adreno8-preempt.py`、`test-adreno8-recover.py`、`test-adreno8-g11-hang.py`、`test-annibale-gpu-dispatch.py` 与 `test-annibale-gpu-lifetime.py`（37 场景 `4K`/`16K`）全通过。
- **`G7` compute limits 修复**：`air_metal_dispatch.inc`（`212` L）在 `dispatch_grid()` 第 114 行增加 `!split` 条件避免旧可变工作组上限误拒已验证 `split` CSO，更新 `air_compute_limits_test.c`（`70` L），`test-air-compute-split-limits.py`（`282` L，ASan+UBSan）`4/4 PASS`。
- **`G32` 图层与渐变探针**：`inject_sb26_layers.c`（`1126` L）拆出 `inject_sb26_layers_extra.inc`（`89` L），补齐 `compositingFilter` 实际 `CFString` 输出与 `describe_gradient()`（`super`、`type`、`startPoint`/`endPoint`、`colors` RGBA、`locations`），`arm64e -Wall -Wextra -Werror -fsyntax-only` 零告警。
- **`S7` DPU 缩放阶段 A**：新增 `MiniFramebufferDpuScale.inc`（`419` L）与 `fb_dpu_scale=1`（默认 `0`），更新 `MiniFramebufferFlip.inc`（`557` L）与 `MiniIOMobileFramebuffer.cpp`（`1244` L），支持 `vig0`/`vig1` 左右拆分（`603+603 -> 578+578`）、`BGRA`/`l10r` QSEED3LITE 配置及多图层/`Quiesce`/`PowerOff` 快照恢复；`test-fb-dpu-scale.py`（`341` L，ASan+UBSan）`3/3 PASS`。
- **`P23` 阶段 2（`cluster1 CL5`）**：`psci_smp.c`（`735` L）新增 `psci_cl5=1`（默认 `0`）与 OSI/`9144 us` 门槛、`PSCI_RET_DENIED (-3)` 瞬态退避及 `kern.annibale.cpus` 拆出 `cl5`/`cl5_denied`/`cl5_err`；`test-psci-idle.py`（`367` L，ASan+UBSan）PASS，并由 `bootargs.py` 登记至 `docs/analysis/boot-args.md`。
- **`M4` AE 收敛与播放器诊断**：`camera_isp.c`（`1013` L）为 ADRC `drc` 增加 `0.75/0.25` EMA 平滑（`1%` 重建迟滞）并将 >1 EV 跨度阻尼提至 `0.85`（`test-camera-isp-ae.py` `130` L OK）；`video_player_test.m`（`491` L）补齐脱敏 `NSError` 诊断字段 `error_domain`/`error`/`underlying`（`test-video-player-test.py` `331` L `13/13 OK`）。
- **`P21` Wi-Fi XPC 类型修复**：`a80211_test.c`（`857` L）将 `CWFScanParameters.setSSID:` 入参由 `CFDataRef` 修正为 `CFStringRef`（UTF-8/ISOLatin1），`arm64e` 编译签发与 `test-frame-split.py` 均通过。

## 3. b5r64（基线集成与诊断）真机实测详情

- **`G30` 阶段 3 与 `G7` compute limits**：`render-report.txt` 全轮 `AnnibaleGPU` 66 行正常且零拒绝/零停转；`kernelRec709DownsampleYFilterOrder2` `176` 次调度下 `324 > 256` 报错清零（`0`），`cam_rear.png` 曝光色彩正常。
- **`P21` `cwjoin` 越过 `4097`**：`corewifi-xpc plain=0(p=0xe03) flags8=0(p=0xe03)`、`scan reply err 0x0` 并拿到 `6 scan results`，随后在 `associate` 阶段返回 `Error Domain=com.apple.corewifi.error.wifid Code=-3905`。
- **`M3` 单次 `voldown` 联动**：`bg /annibale/bin/sound_test activate route tone 12 route` 下单次 `voldown 100` 使内核音量从 `1.000: 0.0 dB` 降至 `0.457: 26.0 dB`，紧接独立 `sound_test route` 输出 `volume 0.45`，双端一致降至 `0.50` 以下。
- **`G32` Weather 图层探针与 `G14`/`M4`**：`weather_main.png` 与 `276` 行 `weather-layers-dump.txt` 记录 `layer 8 SwiftUI.GradientLayer` 已传 `colors=5[064b8eff,2765a4ff,427fbbff,699cd0ff,8fb9e6ff]`、`layer 9` 为 `fx=destOut/0+0/- colors=3[00000000,ffffff80,ffffffff]`，排除应用侧未赋色假设（黑屏仍待批 22 根治）；`maps_mode.png` 4 缩略图仍黑（`MapKit.SnapshotService` pid `290` 未在重启列表致 `g31-trace=0`）；`/annibale/share` 仅含 `pattern.bin` 缺带音轨 `.mp4`，`video_player_test` 打印 usage 并确认 `iris_vt: registered SM8750 Iris VPU v3.5 decoders`。

## 4. b5r65（fb_dpu_scale=1）真机实测详情

- **硬件缩放表现与吞吐**：日志输出 `MiniIOMobileFramebuffer: flip: DPU QSEED3LITE scaling ready (578+578x2510, slot 16 MiB, boot fmt 000237ff unpack 03020001)`、`vig0: src 09ce0242 at 00000000, out 09ce0242 at 00000000, addr fc800000 stride 00001210 format 000237ff op 80000000`；驱动实测跑出 `296 frames / 5002 ms`（`59 fps`），零丢翻页、零 `panic`/`gpu_fault`/`smmu fault`，单线程写合并 `memcpy` 耗时 `3.65–5.81 ms`（12.6 MiB），`backboardd` `tl: mt` `46` 次提交 `encode 3900/139`（对比 `b5r64` `38` 次提交 `4219/155`）。
- **截屏条纹根因确证与退回**：`run/thumbs/shot-00734.png` 与 `shot-00891.png` 的横向条纹出自 `xnuloader`（`loader_06_usb_entry.inc:834`）`oem screenshot` 固定按启动几何 `1156×2510`（`stride 4624`）误读 `1206×2622`（64 字节对齐 `stride 4864`）原始内存，DPU 帧缓冲与硬件缩放本身正常；重解释 `shot-00891.png` 的相邻行像素差从 `w=1156` 的 `16.09`、`w=1206` 的 `6.52` 在 `w=1216`（`stride 4864`）骤降至 `1.19`（每 `19.27` 行错一行），轮末通过 `--teardown` 安全退回空闲 `xnuloader`。

## 5. b5r66（psci_idle=1 psci_cl5=1）真机实测详情

- **PSCI OSI 与 C4/CL5 计数**：开机日志输出 `psci: method=smc version=1.1 cpu_suspend=0x3 (osi=1 ext_stateid=1) psci_idle=1 psci_cl5=0` 与 `psci: SET_SUSPEND_MODE(OSI) failed: 4294967293 (?); psci_cl5=0`（`-3` `PSCI_RET_DENIED`），内核安全回退并维持 `psci_idle=1`；`sysctl kern.annibale.cpus` 录得 `cpu 0..3` `c4 = 163158/157947/108572/79233`、`c4_err = 0`（`cl5`/`cl5_denied`/`cl5_err` 均为 `0`）。
- **静置温控、唤醒与巡检**：电池 `33 °C`、`cpufreq` `39.1–39.9 °C`；静置超过 `45 s` 后触控上滑唤醒正常并保存 `home_final.png`；`render-report.txt` `restart`/`gpu` 段无异常，另录得 1 例 `locationd[69] userabort`。

## 6. 批 21 离线定因与批 22 待办输入

- **`G32` 渐变管线离线排查**：解析 `b5r63/backboardd.harvest` 确认 `axial_shading_frag_*` 在 `b5r62`/`b5r63` 中零构建，顶点色线性渐变实际走 `VfxLlnXh + TcmaA2LlnXhfs`（`b5r64` 复用 291 次，以 `INTERP_MODE_NOPERSPECTIVE` 读入 `f16vec4` 并乘 `ubo1[0x94]` 16-bit half）；`b5r64` `weather-layers-dump.txt` 实证 `layer 8`（`type=axial`、`colors=5`、`locs=5`）与无遮罩 `layer 17` 温标条（`colors=17`）均呈黑/不可见（仅 `CGDrawingLayer` 正常），批 22 优先离线回放 `VfxLlnXh + TcmaA2LlnXhfs` 验证 `freedreno` 输出。
- **`S7` 阶段 B 方案**：基于 `b5r65` 实测结果，批 22 在 `kernel_live`/`oem screenshot` 同步上报实时 `scanout` 的 `width`/`height`/`stride`/`fmt` 供截屏按实解码，并用 `fb_threads` 并行拷贝压低 `3.65–5.81 ms` 拷贝耗时。
- **`M3` `0.50` 与 `0.520` 差值定因**：确认 `b5r63` `voldown` + `volup` 使 PVM 净变为 `0`，`VirtualAudio` 按 UI `0.50 -> -23.0 dB`、`0.4375 -> -26.0 dB` 经 `audio_plugin.c` `48 dB` 线性标尺输出 `0.5208`/`0.4583`，再由 `b5r64` 单次 `voldown` 实测 `0.457`/`0.45` 双向印证。
- **`P14` `sensorspd` 缺口定因**：静态反汇编 `adsp.b09` 确认 `adsp_process_group_create_staticpd`（`0xf03bc858`）仅含 `"audiopd"` 与 `"oispd"`；`adsp.b25`/`adsp.b26` 为动态用户 PD `qsh_process`（`pd_mon_image_sw_id = <0x87>`），启动依赖 `/ramfs/qsh.mbn` 或 `/rfs/root/vendor/firmware_mnt/image/qsh.mbn`（当前固件未提取）及 ADSP 宿主 QRTR TFTP/RFS 服务 `0x1000`（`annibale_adsp.c` 尚未实现），转入批 22。
- **`M4` 后摄 PDAF 契约就绪（待 `b5r67` 实测）**：已从 `com.qti.sensormodule.annibale_aac_ovx8000_wide_i.bin` 解码 `GT24P128F`（`0x51`，`0x0000..0x1839` 含 `17×13` GainMap 与 `8×6 Q4` H/V DCC）及 `PDConfigData[6]`（`2560×480` RAW10 `bufferType=4`），并明确 `vfe-lite980` `RDI1=0x600`/`WM1=0x1800` 首轮寄存器诊断点；其余待批 22 跟进项还包括 `P21` `associate Code=-3905`、`S7` 阶段 B 实态尺寸上报与 `fb_threads`、`P23` 修正 `PSCI_SET_SUSPEND_MODE=0x8400000F` 与 32 位符号扩展、`G14` `SnapshotService` 持久化 trace 与带音轨 `.mp4` 冷启动实测。
