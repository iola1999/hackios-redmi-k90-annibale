# 2026-11-28 批 18～批 19 真机实测与代码合流总结（b5r55～b5r60）

本记录汇总批 18（`b5r55`～`b5r57`）与批 19（`b5r58`～`b5r60`）全部真机验收（`12377-flipwd29` `038cd0d3...`、`12377-flipwd30` `7aff0913...` 配合用户态与 `libannibaleair.dylib`）、已过审修复及待入下一批次事项。

## 1. 轮次与核心结论概览

- **`b5r55`（`12377-flipwd29` + `libannibaleair.dylib` `f085bc85...`）**：前后摄恢复物理切换（`camera_avtest` 枚举 2 台设备、`Camera.app` 切摄正常）、`ENG-09` `material_regress_ios` 达成 `18/18 PASS`、天气 `G32` 稀疏 Argument Buffer 三类报错由 `5,377` 降至 `0`（并捕获 4 类 VFX 拒收报错）。
- **`b5r56`（`12377-flipwd29` + `frontcamrot=0`）**：单变量验证 `front-cam-rotation-isp = 0`（`mg_test` 返回 `+0`），`out/b5r56/cam_front.png` 实拍确认前置上下正立，推翻 `b5r7` 误判 `180` 导致的上下倒置。
- **`b5r57`（新版手机 `xnuloader` 默认 `0`，无 `frontcamrot=` + `libannibaleair.dylib` `8c655205...`）**：无参数覆盖下前摄方向与前后摄切换全过；天气 `G32` 前四类报错（`myColorTint`、`air.amplification_id`、`texture view: requested type`、`no texture was encoded` 与 `AIRFAIL`）全部清零，仅余 `fragment_skybox_texture1d`（`1D` vs `1DArray` 视图切片类型）502 次绘制报错；另捕获下拉通知中心全黑（近黑 `97.0%`）。
- **`b5r58`（`12377-flipwd29` + `libannibaleair.dylib` `9cfc731c...` + `#734` + `#739`）**：`rwa_texture_set_view_slices` 与热路径日志降噪生效，Weather 全程 `15` 个 `tl: mt` 窗口全部 `errors = 0`、稳态 `encode max = 0.63–2.36 ms` / `flush max = 0.20–0.98 ms`，城市列表「北京市」卡片首次点亮深靛蓝夜空；`boot_home1.png` 恢复正常（`near_black=0.11%`），并定因通知中心黑屏关联启动期 `backlight-off`。
- **`b5r59`（`loader-shell.img` 无 `frontcamrot=` + `#753` + `libannibaleair.dylib` `ca3461b9...`）**：`boot_nc.png` 通知中心壁纸完整亮屏（`near_black=0.00%`、`backlight-off=0`）；`weather_cities.png` 全部 **4/4 城市卡片**渲染深靛蓝夜空（`errors = 0`、稳态 `encode max 1.03–1.75 ms` / `flush max 0.18–0.27 ms`），详情页全屏天空区仍黑待排查；前摄默认方向 `0` 再次验证正立。
- **`b5r60`（`12377-flipwd30` `7aff0913...` + `root.apfs 0e2e8b9c...` + `#765`）**：`M16` 前摄 `ldob8` 上/断电为 `0`、后摄仅单次 `bobb2` 开关且 `tl: C` 软着陆步进零报错；`Weather` `post_process` 探针确认全屏 `905×1967` 表面已输出 `RGB=[4,0,20]..[40,60,92]`、`A=255` 深靛蓝渐变且 `errors=0`，锁定全屏黑屏出于 `#767` 分支 B（视图遮挡或合成阶段）；`boot_nc.png` `near_black=0.00%` 稳定复现。

## 2. 批 18 已合入过审的修复清单

- **`ENG-09` `blend_const_color` 链路（`#663`/`#665`）**：`air_metal_render.h`（765 行）与 `annibalemetal.m`（1118 行）在 `struct rwa_draw` 末尾追加 `const float *blend_color;`；`air_metal_render_draw.inc`（826 行）调用 `pipe->set_blend_color()`，`annibalemetal_work_private.h`、`annibalemetal_renderencoder.inc` 与 `annibalemetal_commandbuffer.inc` 贯通 `-setBlendColorRed:green:blue:alpha:`。
- **`ENG-09` 容差校准与单测（`#663`/`#665`）**：`material_regress_check.py`（239 行）仅对 `glass_fbfetch_c1` 设 `2e-3` 容差，新增 `test-metal-blend-color.py`（90 行，ASan+UBSan）通过。
- **`G7`/`ENG-08` P1 与 P2（`#663`/`#665`/`#671`/`#672`）**：`air_texture.inc`（991 行）放行 `read_sampler` 下 `t.is_ms` 与 `t.depth` 并复用 `nir_texop_txf_ms`（`test-air-msaa-read.py` 96 行 `PASS: public=2, AppleMetalGLRenderer=6`）。
- **`G7`/`ENG-08` P2 语料剪枝（`#671`/`#672`）**：`air_ops.inc`（344 行）将单侧 `AIR_PTR_NONE` `select` 折为 `nir_imm_zero`、`air2nir.c`（741 行）新增 `--fc INDEX=VALUE[,...]`（`test-air-fc-prune.py` 80 行 `PASS: public=3, QuartzCore=2`），`corpus.py` 翻译率升至 `450/463 (97%)`（`AppleMetalGLRenderer` `274/274`、`QuartzCore` `176/189`）。
- **`S7` 单帧分桶与 `G31` 空 `label` 回退（`#663`/`#665`）**：`annibalemetal_commandbuffer_submit.inc`（872 行）将 `damage_probe` 升级为单帧高度占比分桶（`<25%/25..50%/50..90%/>90%`、`h_p50`/`h_p90`，`test-metal-damage-probe.py` 173 行通过）；`annibalemetal_buffer_pipeline.inc`（518 行）与 `annibalemetal_renderencoder.inc` 为空 `label` 管线回退打印 `fragmentFunction.name`（`test-metal-g31-trace.py` 271 行通过）。
- **`G29` `rwa_lock` 解耦（`#673`/`#674`）**：`air_metal.c`（814 行）与 `air_metal_render_create.inc`（1095 行）等 16 份文件拆出 `rwa_cso_create_lock`、`rwa_vcso_lock`、`rwa_buffer_textures_lock`、`rwa_argbuf_lock` 与 `rwa_deferred_lock`，非 `software` 设备 `rwa_render_create_linked` 脱离 `rwa_lock`、`rwa_texture_destroy`/`rwa_buffer_destroy` 改用原子引用计数与延迟排空队列；`test-air-g29-decoupling.py`（884 行，ASan+UBSan+TSan）通过，`run-host-tests.py air metal` `22 passed`。
- **`G32` 天气稀疏 Argument Buffer（`#685`/`#687`）**：`air_metal_reflect_vertex.inc`（993 行）与 `annibalemetal_compute_argencoder.inc`（1075 行）放行稀疏 `[[id(n)]]` 槽位并按 `max_id` 保证编码长度（`test-metal-argbuf-sparse.py` 181 行通过）。
- **天气 VFX 四项修复（`#710`/`#712`/`#716`）**：`air_argbuf.inc`（636 行）跳过 `[N x i8]`/`i8` 填充、`air_interface.inc`（889 行）接入 `air.amplification_id`、`annibalemetal_texture.inc`（819 行）补齐 `1D <-> 1DArray` 视图兼容、`air_metal_argbuf.inc`（664 行）对 `NULL` 绑定清零槽位（`test-air-weather-vfx.py` 71 行通过）；`build-air.py`（`#716`）产出新版 `libannibaleair.dylib`（`14,422,432` B，sha256 `8c655205150e1f92dc5c9e84c6884b7a34e407f4d473e847721997687a65f13c`）。
- **相机双问题修复（`#702`/`#703`/`#717`/`#718`）**：`81-bsd%kern%hvg_sysctl.c.patch`（79 行）将 `vmm_spoof_procs` 默认值改为 `"mediaanalysisd"`（移除 `cameracaptured`，消除 `BWFigCaptureDevice` 按 VM 策略裁剪后摄流，`test-hvg-vmm-spoof.py` 114 行通过）；`init_mount.inc`（719 行）清理 `com.apple.MobileGestalt.plist` 持久化缓存（`test-init-data-mount.py` 230 行通过）；`xnuloader/loader_01_base_log_dt.inc:836`（902 行）与 `loader_05_layout_run_kernel.inc:488`（1117 行）将 `front_cam_rotation_isp` 默认值改为 `0`。
- **`M16` 后摄 VCM 供电与软着陆修复（`#765`/`#768`）**：`annibale_camera_hw.inc`（918 行）将 `ldob8` 设为按需供电；`annibale_camera_clock.inc`（603 行）按 `cam_vaf_powered` 去重并收窄 `OVX8000_LENS_STEP=32`（`<=64` 改 `16` 步软着陆）；`annibale_camera_exposure.inc`（196 行）与 `camera_device_worker.inc`（586 行）对齐 `OVX8000_FOCUS_DEFAULT=275u`/`MAX=700u`/`AF_FAR=700` 并跨会话复位；`annibale_camera.c`（1072 行）新增 `cam_return_lens_park()` 断电前停泊；`test-annibale-camera-vcm.py`（358 行）6/6 通过。

## 3. b5r55（flipwd29）：相机切换恢复、ENG-09 18/18 与天气稀疏 ArgBuf 实测（#705/#706）

- **产物与稳态**：内核 `12377-flipwd29`（`21,073,744` B，sha256 `038cd0d372616f2bd0b27c321ffb3010909570f0b677d6926598209585738aa9`）+ `libannibaleair.dylib`（`14,422,432` B，sha256 `f085bc85ec2e8a75bd407c43e00b671c2496102cfd30e4c5c52f9cc19e9923c5`）+ 重编用户态；`s127.log`（`16,432` 行）全零 `panic(` / `gpu_fault` / `submissions closed` / `smmu fault` / `No system apps remain` / `AnnibaleGPU client refused`。
- **后摄恢复与切摄验证**：`/annibale/bin/camera_avtest` 枚举 `2 video device(s)`（`Back Camera built-in_video:0, position 1, 55 formats` 与 `Front Camera built-in_video:1, position 2, 52 formats`）；`Camera.app` 实拍 `out/b5r55/cam_{back1,front,back2}.png` 确认后置 `ovx8000`（`format 16`）、`stream: stop -> format 25` `ov20b40` 前置与切回后置 `ovx8000` 均物理切换正常，`mg_test FrontCameraRotationForISP` 返回 `+180`（同时目视发现 `+180` 使前置上下倒置 180°）。
- **`ENG-09` 18/18 全过**：`out/b5r55/mr_compare.txt` 对照 `out/b5r52/ref` 输出 `COMPARE total=18 failed=0`（`blend_const_color max_err=1`、`glass_fbfetch_c1 max_err=0.0014648`、`g3_* max_err=0`）。
- **天气 `G32` 与 `G29` 读数**：稀疏 ArgBuf 三类报错（`a texture/buffer was encoded at id`、`pass_constants_encoder`）由 `5,377` 降至 `0`，`out/b5r55/weather-metal.log`（2,913 行）暴露剩余 4 类 VFX 报错；`SpringBoard` `tl: mt` 共 25 条，冷启编译期 `encode_max = 100.54 ms`（稳态 `1.67–7.78 ms`）。

## 4. b5r56 与 b5r57：前摄默认 0 度收口与天气四项报错清零（#713/#714/#721/#722）

- **`b5r56`（`12377-flipwd29` + `frontcamrot=0`）**：串口日志确认 `front-cam-rotation-isp 0 (K90 mounting angle)`，`mg_test FrontCameraRotationForISP` 返回 `+0`；`out/b5r56/cam_front.png` 天花板与空调出风口在画面顶部、手腕在底部，`cam_back1.png`/`cam_back2.png` 后置直立清晰，确认 `0` 为上下正立。
- **`b5r57` 默认启动（新版手机 `xnuloader`，无 `frontcamrot=` + `libannibaleair.dylib` `8c655205...`）**：`s000.log`+`s094.log`（`17,400` 行）确认 `front-cam-rotation-isp 0` 生效（`mg_test` 返回 `+0`），`out/b5r57/cam_{back1,front,back2}.png` 目视确认前后摄均上下正立且物理切换正常，收尾退回空闲 `xnuloader`。
- **天气 `G32` 4 项清零与残余**：`b5r57` 日志中 `myColorTint`、`air.amplification_id`、`texture view: requested type`、`no texture was encoded at id` 与 `AIRFAIL` 均已清零；天空采样 `nonblack=0/36000, max_rgb=[0,0,0]`，唯一残余为 `fragment_skybox_texture1d` `502` 条（`declares texture N as a texture1d and the texture bound there is a MTLTextureType1DArray`），`#723` 已定位 `annibalemetal_texture.inc:324` 未传递视图类型与切片范围。
- **常规健康与新暴露桌面黑画面（`#725`）**：`b5r57` 全零 `panic`/`gpu_fault`/`submissions closed`/`smmu fault`/`No system apps remain`；同期 `shot-00322.png`（`home-1`）与 `shot-00707.png`（`home-again`）像素差超 24 占比 `26.56%`，下拉通知中心 `shot-00864.png` 近黑像素 `97.0%`（平均 RGB `[0.6, 0.8, 1.1]`，中部 `[0, 0, 0]`）。

## 5. b5r58 与 b5r59：热路径降噪、通知中心亮屏与天气城市卡片点亮（#744/#745/#757/#758）

- **`b5r58` 热路径日志降噪与视图切片类型生效（`#727`/`#729`/`#734`/`#736`）**：合入 `rwa_texture_set_view_slices()`（`libannibaleair.dylib` `9cfc731c...`）、`annibalemetal_console.inc` 默认零 `usleep` 并过滤 `fd tile ring create:`，同时将 `rw_dealloc_print`/`pipeline seen:`/`render targets` 归入 `ANNIBALE_METAL_LOG_VERBOSE`。
- **`b5r58` 天气实测（`#744`/`#745`）**：`Weather` 全程 15 个 `tl: mt` 窗口全部 `errors = 0`，稳态 `encode 8.3–14.5 ms (max 0.63–2.36 ms)`、`flush 3.5–5.0 ms (max 0.20–0.98 ms)`，`weather_cities.png` 「北京市」卡片首次点亮深靛蓝夜空（`RGB=[27, 29, 52]`、`mean=[29.2, 32.7, 55.0]`）。
- **`b5r58` 壁纸生命周期与 `backlight-off` 定位（`#739`/`#741`/`#747`）**：`inject_sb26.c`（899 行）接入 `SBCoverSheet{WillPresent,DidDismiss}Notification` / `SBLockScreenUI*` 与 `1500 ms` 延迟挂起，使 `boot_home1.png` 恢复正常（`near_black=0.11%`、`mid_mean=[150.9, 176.2, 189.3]`）；同时排查确认 `b5r55`/`b5r57`/`b5r58` 下拉通知中心仍黑（`boot_nc.png` `97.58%`）源于 `SpringBoard` 启动超 15 秒期间触发 `SB + pocketTouches + backlight-off` / `DisplayBrightnessFactorWithFade to:0`。
- **`b5r59` `backlight-off` 消除与通知中心全亮（`#753`/`#754`/`#757`/`#758`）**：`inject_sb26.c`（917 行）新增 `sb26_reset_idle_timer()` 在 `boot_unlock()` 与 `wake_screen_for_unlock()` 期间经 `SBIdleTimerGlobalCoordinator -resetIdleTimerForReason:` 重置空闲计时器；`b5r59` 启动期 `backlight-off` 与 `DisplayBrightnessFactorWithFade to:0` 全部清零，`out/b5r59/boot_nc.png` 通知中心壁纸完整亮屏（`near_black=0.00%`、`mean_rgb=[101.74, 154.54, 186.91]`、`mid_mean=[131.51, 179.33, 200.59]`）。
- **`b5r59` 天气 4/4 城市卡片点亮（`#748`/`#750`/`#752`/`#757`/`#758`）**：`air_metal_texels.inc`（`texture_box()` `1D_ARRAY` 改用 `box->z = first_layer + layer`）、`air_metal_copy.inc`、`air_metal_render_draw.inc` 与 `air_metal_clear.inc` 对齐 `first_layer`（`libannibaleair.dylib` `ca3461b9...`）后，`weather_cities.png` 4/4 卡片（萧山区/上海市/北京市/重庆市）全部渲染深靛蓝夜空（`mean_rgb` `[29..39, 32..42, 51..63]`）且 `errors = 0`（稳态 `encode max 1.03–1.75 ms`、`flush max 0.18–0.27 ms`），全屏详情页天空区仍黑待查。
- **`b5r59` 默认相机与系统健康（`#757`/`#758`）**：使用新版默认 `xnuloader`（不传 `frontcamrot=`）开机确认 `mg_test FrontCameraRotationForISP` 返回 `+0` 且前后摄正立切换正常，`s000+s087.log`（19,306 行）全零系统错误。

## 6. b5r60（flipwd30）：M16 后摄 VCM 与 Weather post_process 探针（#773/#775/#776）

- **`M16` 后摄电源去重与 VCM 软着陆验收**：`12377-flipwd30`（SHA-256 `7aff0913ac3dfc1c029f33f31332f2c9d017719d6b202a0260b6d49609e12a39`）+ `root.apfs`（`0e2e8b9c00023d3ff9372aa1ff207ba664f2fd623617d0227ac29ef1d871cdef`）实测，前摄会话 `ldob8` 上/断电计数为 `0`，后摄仅单次 `bobb2 enable=1` 与退出 `enable=0`；`s095.log` `tl: C 111 5827` 记录首帧 `seq 4 foc 8/80521`、`seq 7..33 foc 2/11299..12240`、`seq 36 foc 4/34893` 零报错。
- **`b5r60` 外部边界与启动注记**：原厂模组 `AK7323` OIS 与 `annibale.dts.gz` 为空桩/缺固件（外部边界）；因上轮 `recover-loader.py` 切回 `boot_a` 旧 loader，本轮 `s000.log` 与 `mg_test` 为 `+180`（新 loader 刷入 `boot_a` 后持久化 `0`）。
- **`G32` `post_process` 探针定因（`#767` 分支 B）**：对 `Weather` 注入环境变量采集 `commit 40 work 30` `in 0`（`format 70 905x1967`）与 `out 0`（`format 80 905x1967 surface`），解码 6-bit 缩略图为 `RGB=[4, 0, 20]` -> `[28, 32, 56]` -> `[40, 60, 92]`、`A=255` 深靛蓝夜空渐变且全程 21 个 `tl: mt` 窗口 `errors = 0`，`weather_cities.png` 4/4 卡片持续全亮；锁定全屏 `weather_main.png` 黑屏出于 `#767` 分支 B（`WeatherUI` 视图层级遮挡或 `backboardd` 合成阶段）。
- **通知中心复现与系统健康**：`boot_home1.png` `near_black(<15)=0.11%`（`mean_rgb=[123.93, 162.95, 183.41]`），`boot_nc.png` `near_black(<15)=0.00%`（`mean_rgb=[101.9, 154.71, 187.05]`）；`s103.log`（`19,917` 行）全零 `panic(` / `gpu_fault` / `smmu fault` / `submissions closed` / `No system apps remain` / `AnnibaleGPU client refused` / `lens set-up failed`，收尾退回空闲 `xnuloader`。

## 7. 待后续批次补齐的其余事项

- **`G32` 天气全屏合成黑屏（`#767` 分支 B）**：`Weather` Metal/Freedreno 已正常产出 `905×1967` `A=255` 深靛蓝夜空，Batch 20 继续定位 `WeatherUI` 视图层级遮挡或 `backboardd` 合成阶段原因；同步保留 `M16` 待用户真实听感确认与 `AK7323` 外部边界注记。
- **`ENG-07` 与只读储备方案（`#742`/`#743`/`#774`）**：`libannibale-statusbar.dylib` 拆分方案已备待 Batch 20 实施；`S11`（`apfs_vnops_write.inc` `EFAULT` 用户态指针诊断）与 `G11`（`adreno8_gpu_cp_progress` `IB1/IB2 rem` 与 GX 关闭时 GMU/HFI 转储及 `described` 复位）已完成只读设计待合入。
- **系统推进项（`#679`/`#763`/`#764`）**：`S12`（`chronod` `BiomeStorageError`）、`M1`（`dsz == 2 * bsz`）、`P14`（`adsp_mem_heap 12 MiB <4G`）与 `P21`（`cwjoin` XPC helper）待完成宿主单测与 `@verifier` 审查后在 Batch 20 统一编核验证。
