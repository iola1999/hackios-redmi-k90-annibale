# 阶段六进展：性能优化、图形 CCHE 修复、基带 QMI 上线与相机链推进（2026-11-19）

本阶段（`s6a`～`s6g-r3`，内核 `12377-s6g3`）围绕 `PERF-1`～`PERF-5` 性能优化、桌面条纹与多图标闪烁修复、MPSS 基带 QMI 服务上线以及相机后处理链路推进展开实现与真机验证。

## 1. 性能专项（PERF-1/2/3/5 与 PERF-4 评估）

- **PERF-3（调度性能回调与 IOGPU 角色控制）**：在 `work_interval_ctl` 补齐操作码 `6/7/8`，在 [annibale_cpufreq.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_cpufreq.c) 注册 `sched_perfcontrol_callbacks` v7，并令 [AnnibaleGPU.cpp](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/AnnibaleGPU.cpp) 继承 `IOGPU`（`fClientType == 1` selector `0/2/4/0x21/0x22`）。
- **PERF-3 真机结果**：`s6e-r1` 实测 `setGPURole` 返回 `nil` 错误由 `76/27s` 降至 `0` 次，空闲 CPU 频率降至 `384 MHz (36%)`／`1017 MHz (32%)`。
- **PERF-5（24 MHz Mach 时钟快路径）**：通过补丁 [78](../../hackios-xnu-kernel/xnu26/patches/78-pexpert%arm%pe_identify_machine.c.patch)、[79](../../hackios-xnu-kernel/xnu26/patches/79-osfmk%arm64%genassym.c.patch) 与 [80](../../hackios-xnu-kernel/xnu26/patches/80-osfmk%arm64%locore.s.patch) 在 `locore.s` 的 `el0_synchronous_vector_64_long` 入口加入 `SVC #0x80`（`w16 = -3/-4`）`24 MHz` 无栈切换快路径。
- **PERF-5 真机实测**：`s6e-r2`（`12377-s6e2`）启用 `FD_PERF_DRAW=1` 测得 `rwa clock: 1024 timing marks took 64 us, 62 ns each`（`docs/progress/evidence/k90auto/kernel-12377-s6e2-s6e-r2/run/perf5-clock.log`）。
- **PERF-2（AIR 锁拆分）**：在 [air_metal_texture.inc](../../hackios-xnu-userland/tools/mesa/air/air_metal_texture.inc) 增加原子 `buffer_textures_count` 与 `rwa_buffer_textures_refresh()` 无锁快路径，在 [air_metal.c](../../hackios-xnu-userland/tools/mesa/air/air_metal.c) 将 `prepare_stage_nir()` 移出 `rwa_lock` 并经 `rwa_quad_vbuf_ref()` 共享 `quad_vbuf`。
- **PERF-2（管线缓存与真机效果）**：在 [annibalemetal_pipecache.inc](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_pipecache.inc) 统一 SHA-256 管线缓存键，在 [annibalemetal_buffer_pipeline.inc](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_buffer_pipeline.inc) 移除全局 `rw_compute_limits_lock`。`s6f-r1` 实测 `backboardd` `refresh_max` 由 `s6e-r3` 的 `9,123 us` 降至 `833 us`。
- **PERF-1（APFS 数据盘 3 轮性能基线）**：`s6f-r2`（`12377-s6f2`，可写 APFS `darwin_var`）实测 3 轮冷/热启动耗时为 `Preferences` `30/342/382 ms`、`Calculator` `597/49/436 ms`、`Notes` `148/69/311 ms`、`Safari` `499/468/211 ms`。3 个显示窗口中位数均 `< 9 ms`（p95 `17/59/34 ms`，最高温 `72.9 °C`，`docs/progress/evidence/k90auto/kernel-12377-s6f2-s6f-r2/run/perf1-apfs.log`）。
- **PERF-4 只读评估**：`s6f-r2` 当前 `fb_flip=2` CPU 行拷贝路径 3 窗口平均驱动耗时 `5.3～5.8 ms`（GPU 等待 `1.7～2.5 ms`）。原厂 DPU12 直扫（`WP-2A`）涉及 `annibale_apps_smmu`（`SID 0x0800`）、`MiniIOSurface` DMA 锁页、`VIG0/VIG1 + QSEED4` 与 `INTF_TEAR_INT` 3 槽 `SwapWait`，留待后续专题推进。

## 2. 图形显示与桌面花屏、闪烁根因清除（s6g-r1～s6g-r3）

- **问题拆分**：`s6g-r1`（`adreno8_speed=14`）在空载桌面记录到跨 5 个图标区域（`829` px）的动态闪烁；`s6g-r2`（`adreno8_speed=1` 固定 `160 MHz`）消除了跨图标动态闪烁（差异全集中在时钟秒针），但 `FaceTime`、`相机` 与 `信息` 上的静态 `16x16`／条纹块损坏仍复现，确认桌面存在两类独立缺陷。
- **静态条纹根因**：回溯查明 [0020-fd6-a8xx-state-bindless-and-bo-null.patch](../../hackios-xnu-userland/tools/mesa/rebase-26/0020-fd6-a8xx-state-bindless-and-bo-null.patch) 在 `fd6_barrier.cc` 为 `FD6_INVALIDATE_CCHE` 附加了 `!(flushes & FD6_INVALIDATE_CACHE)`，与 [0003-restore-osmesa-26.x-drift-adaptations.patch](../../hackios-xnu-userland/tools/mesa/rebase-26/0003-restore-osmesa-26.x-drift-adaptations.patch) 同设 `FD6_INVALIDATE_CACHE | FD6_INVALIDATE_CCHE` 冲突并长期跳过 `CP_CCHE_INVALIDATE`。
- **静态条纹修复**：移除 `0020` 的 `fd6_barrier.cc` hunk 后，通过 `tools/k90auto/build-air.py` 重编 `libannibaleair.dylib`（SHA256 `cb71279358438b21`）。
- **动态闪烁修复（`adreno8_speed_tick()`）**：在 [adreno8_hfi.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/adreno8/adreno8_hfi.c) 的 `adreno8_speed_tick()` 中，仅在 `want != adreno8_speed_now` 需要实际切档的情况下调用 `adreno8_context_wait_idle("GPU speed")` 排空在途 4 路批处理再发送 HFI 调频消息。
- **真机验收（`s6g-r3`，`12377-s6g3`，`adreno8_speed=14`）**：运行中 `GPU at 342 MHz, 31 speed changes`；`docs/progress/evidence/k90auto/kernel-12377-s6g3-s6g-r3/run/cche-home-1.png` 与 `cche-home-2.png` 全屏 19 个图标、组件与 Dock 毛玻璃零静态条纹与色块，两帧间 `1816` 变化像素全部位于时钟秒针区域，`docs/progress/evidence/k90auto/kernel-12377-s6g3-s6g-r3/render-report.txt` 记录 `0` 次 GPU 停转与 `0` 次 SpringBoard 崩溃循环。

## 3. 蜂窝基带与 QMI_LOC 定位服务（MPSS / QMI / QRTR）

- **HYP_ASSIGN 与 GLINK/QRTR 打通**：修正 [annibale_ipa.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_ipa.c)、[annibale_modem_boot.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_modem_boot.inc) 与 [annibale_modem.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_modem.c) 的 `HYP_ASSIGN`（`dsm1=(0,0) dsm2=(0,0)`）与 `GLINK` TX 门铃。
- **GLINK 与 QRTR 结果**：`s6e-r2` 完成 `SMP2P READY`（`2450 ms`）与 `SMEM GLINK IPCRTR` 握手；[annibale_qrtr.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_qrtr.c) 补齐 `qrtr_local_servers` 发布并将服务表容量升至 `96`。
- **APPS 侧 QMI 服务上线**：在 [annibale_modem_svc.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_modem_svc.inc) 的 `lowdma` 区间（`[0xce800000, 0xcf600000)`，核对与 Wi-Fi/音频/IPA 零重叠）提供 `MEMSHARE (0x34)`、`RMTFS (0x0e)`（UFS 只读加内存写影子）与 `SERVREG_LOCATOR (0x40)`。
- **7 项 MPSS QMI 服务在线验证**：`s6f-r3`（`12377-s6f3`，`modem=3`）实测 `kern.annibale.modem_state = 4`，`WDS (0x01)`、`DMS (0x02)`、`NAS (0x03)`、`WMS (0x05)`、`Voice (0x09)`、`UIM (0x0b)`、`LOC (0x10)` 全部上线并收到 `QMI LOC registered position report events`，全程 0 崩溃；`s6g-r1` 补齐 `WMS` `qmi_flags == 0x04` 判别与 `UIM TLV 0x10` 偏移解析。
- **`QMI_LOC` 与待验证边界**：`QMI_LOC` 的 `0x1e`/`0x20`/`0x01` 回退掩码改动已通过主机 ASan+UBSan 与 `qmi-test`（`87` 项全过），因 `s6g-r3` 在该轮触发 `MPSS SMP2P READY timeout after 8000 ms`，该回退分支实机回传待下一批重启复测；同时继续排查无 SIM 卡状态下 `DMS` 上电进入 `operating_mode=3 (OFFLINE)` 的前置条件。

## 4. 相机与多媒体（CAM-3 / MiniM2Scaler / Metal IOSurface）

- **CAM-3 `-6680`／`-73343` 修复**：`cam3-fignotes.log` 与 `CoreVideo`/`CMCapture` 反汇编确认 `CoreVideo` 按设备树不注册苹果 UBC 压缩像素格式，而 `CMCapture` 为 `V57` 硬编码开启压缩能力位导致 `BWPixelBufferPool` 返回 `-6680`。[inject_media.c](../../hackios-xnu-userland/userland/src/inject/inject_media.c) 新增 `align_cmcapture_compression_caps()` 并在 `s6f-r3` 实测生效。
- **MiniM2Scaler 旋转与中断修复**：[MiniM2Scaler.cpp](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniM2Scaler.cpp) 将 `kM2FlagTranspose` 更正为顺时针 90° 旋转 `kM2FlagRotate90`（`dst(x, y) -> src(uy, dw - 1 - ux)`），将 `xform != 0` 接入平面直拷贝快路径并用 `fAbortGen` 实现 `kM2MethodAbortTransfers`。`s6g-r3` `docs/progress/evidence/k90auto/kernel-12377-s6g3-s6g-r3/run/cam3-preview.png` 实测预览方向正确。
- **Metal IOSurface 缓冲前端与驱动**：针对 `UBProcessorV4.m:298` `-73465` 调用 `-[MTLDevice newBufferWithIOSurface:]` 的缺口，在 [air_metal_texture.inc](../../hackios-xnu-userland/tools/mesa/air/air_metal_texture.inc) 新增 `rwa_buffer_from_surface()`。
- **Metal IOSurface 缓冲封装**：在 [annibalemetal_buffer_pipeline.inc](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_buffer_pipeline.inc) 与 [annibalemetal_device_caps.inc](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_device_caps.inc) 实现 `-newBufferWithIOSurface:` 与 `-iosurface`（优先 `kAnnibaleSurface` 零拷贝，客户端内存回退 `rwa_buffer_from_memory`）。
- **相机未决事项**：`s6g-r3` 启用 `cam_bcm=1 cam_rt_mhz=300` 后，后摄预览流仍于 `seq=8` 发生 `IFE-lite0` `bus_ovf=0x1` 超时停流（`error=60`），256B 半块条纹（`CAM-1`）与 `DCIM/100APPLE` 照片落盘（`CAM-3`）继续在下一批排查。

## 5. 文档、启动参数与宿主单测

- 运行 `tools/bootargs.py` 更新 [内核启动参数目录](../analysis/boot-args.md)（共 `163` 项参数），使 `tools/bootargs.py --check` 通过；同步修复 [阶段五进展](2026-11-19-stage5-s21-misc9.md) 超 500 字符段落，使 `tools/check-docs.py` 全仓文档检查通过。
- 阶段六核心宿主单测均在最终修改后以退出码 `0` 通过：`test-adreno8-hfi.py`、`test-annibale-gpu-dispatch.py`、`test-annibale-perf2.py`、`test-annibale-perf3.py`、`test-annibale-modem-loader.py`、`tools/qmi-test/run.sh`、`test-annibale-m2scaler.py`、`test-mini-m2scaler.py`、`test-annibale-camera-native.py`、`test-camera-device-ios26.py`。
