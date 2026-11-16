# 瞬态渲染回归、桌面图标与服务阻塞定位修复（2026-11-17）

本文记录 `v0.2.0` 后出现的桌面图标偏色、长按与转场瞬态渲染异常、钱包黑屏及负一屏地图快照失败的根因、逐帧录屏工具与真机验证结果（内核 `12377-stage3c`／`12377-stage3d`，轮次 `stage3-r2`～`stage3-r4`）。任务上下文见 [v0.2.0 后续执行批次](../plan/2026-11-16-followup.md)。

## 1. 内核逐帧录屏与微秒级日志关联（TOOL-8）

应用启闭黑闪、多任务横带和长按闪烁只持续 1～3 帧（8～50 ms），单次 USB 截图耗时 80～150 ms，难以稳定抓到故障帧。本次新增内核帧缓冲环形录制与主机拼接诊断链路，用法见 [k90auto 说明](../../tools/k90auto/README.md#9-内核逐帧录屏与拼接检测)：

- [MiniFramebufferRecord.inc](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferRecord.inc) 在开机早期预分配 96 MiB 物理连续缓冲（`RWREC003`，`402×874` RGB24，最多连续保存 104 帧），由 `sysctl kern.annibale.rec_arm`（负数直接采样物理 DPU 在屏扫描缓冲）与 `kern.annibale.rec_info` 按需启停。
- 每录制一帧输出一行微秒级 `tl: rec` 日志，包含 `swap_id`、送显缓冲下标、`set`／`clr` 掩码、4 层 `IOSurfaceID`、脏行区间 `band`、双缓冲序号 `bseq` 与 `allDirty`，与 `tl: s` 提交进程及 `annibalemetal`／`adreno8` 报错同源对齐。
- [fb_filmstrip.py](../../tools/k90auto/fb_filmstrip.py) 自动拉取录制块与 `loader.log`，拼接序列帧长图 `filmstrip.png`，并检测整屏黑闪（`BLACK_FLASH`）、中部横向黑带（`HORIZ_BAND`）、隔帧交替闪烁（`FLICKER_ALT`）与边缘暗带（`DARK_FRINGE`），宿主单测见 [test-fb-filmstrip.py](../../tools/k90auto/tests/test-fb-filmstrip.py)。

## 2. 桌面「相机」与 App Store 图标偏色（MISC-6／G22）

`iconservicesagent` 渲染液态玻璃分层图标时，通过 `MTLTextureDescriptor.swizzle` 为单通道与双通道遮罩纹理指定通道重映射（含 `MTLTextureSwizzleZero` 常量零通道）。排查发现两处缺失：

- [annibalemetal_device.inc](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_device.inc) 与 [annibalemetal_texture.inc](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_texture.inc) 创建根纹理、缓冲包装纹理与 `IOSurface` 导入纹理时未读取描述符的 `swizzle` 属性，仅在创建子纹理视图时下发重映射。
- [air_metal_texture.inc](../../hackios-xnu-userland/tools/mesa/air/air_metal_texture.inc) 用 `swizzle_r..a` 非零判断纹理是否带自定义重映射，枚举值 `0`（`PIPE_SWIZZLE_X` 与 `MTLTextureSwizzleZero`）导致含零通道重映射的纹理退回格式默认映射，把金属银外框染黑并冲淡白色笔画。

补齐描述符 `swizzle` 传递并在 `struct rwa_texture` 增加显式 `bool swizzled` 标志后，宿主单测 [test-air-view-writeback.py](../../hackios-xnu-userland/tools/tests/test-air-view-writeback.py) 覆盖零通道重映射与视图继承（含 2 项回归变异检查）。`stage3-r2`～`stage3-r4` 清空 `systemgroup.com.apple.lsd.iconscache` 重建并跨重启复核，「相机」银灰外框与深蓝镜片、App Store 白色「A」字层次均恢复正常。

## 3. 长按闪烁、转场黑闪与多任务横向黑带（MISC-7／MISC-8）

2026-11-16 合入 `542`（`RGB8_444_2P`／`_RB4`）与切换可写 APFS 数据盘后，新出现长按桌面图标黑边、「文件」长按整屏闪烁、应用启闭瞬态黑帧及多任务中部横向黑带。通过 `fb_filmstrip.py` 关联 104 帧序列与 GPU 日志，查明四处独立根因：

1. **Adreno 830 SMMU 页表槽位上限与空叶扫描**：
   - [adreno8_private.h](../../hackios-xnu-kernel/xnu/files/bsd/dev/adreno8/adreno8_private.h) 中 `adreno8_gpu_space.tables` 原固定为 `1024`（仅覆盖 `2,040 MiB` 至 `0x8f800000`）。切换可写 APFS 后常驻进程增多，4 KiB 小缓冲切碎低地址，`backboardd` 申请多任务半屏 `1214×1390` 等 `12～29 MiB` 模糊缓冲时在 `0x8f800000` 因无页表槽位被拒，产生多任务中部横向黑带。
   - 将 `tables` 扩至 `2064`（覆盖全部 4 GiB 32 位 IOVA 的 1 张 L0、4 张 L1 与 2,048 张 L2），并在 [adreno8_smmu.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/adreno8/adreno8_smmu.c) `adreno8_space_find_range` 整块跳过未建表的 2 MiB 空叶。
2. **`542` 计算核转换冲掉 3D 批次脏位与采样绑定**：
   - [air_metal.c](../../hackios-xnu-userland/tools/mesa/air/air_metal.c) 在 `rwa_render_draw` 内采样 `542` 纹理时中途调用 `rgb2p_convert` 分发计算核；Mesa `fd_launch_grid` 调用 `fd6_launch_grid`（末尾执行 `fd_context_all_clean`）后直接恢复原 3D `ctx->batch` 而未置脏上下文，导致同 pass 后续绘制漏发常量缓冲、视口与裁剪状态，引发图标图集拉伸与交替闪烁。
   - 新增 [0019-fd6-zero-unbound-texture-slots.patch](../../hackios-xnu-userland/tools/mesa/rebase-26/0019-fd6-zero-unbound-texture-slots.patch) 在恢复 3D 批次时调用 `fd_context_all_dirty`，并在 [air_metal_rgb2p.inc](../../hackios-xnu-userland/tools/mesa/air/air_metal_rgb2p.inc) 新增 `rgb2p_prepare_bindings` 将平面预转换移至 `state_framebuffer` 之前。
3. **尾部可空纹理槽位残留旧描述符**：`fd_set_sampler_views` 原用 `util_last_bit(valid_textures)` 截断尾部 `NULL` 视图，片上 `SB6_FS_TEX` 残留旧纹理描述符致使 `is_null_texture`（`txs == 0`）误判产生黑边。`0019` 保留调用方显式清零的槽位数并在 `fd6_texture_key` 纳入 `num_textures`，对未绑定槽位写入全零 `dummy_view`。
4. **帧缓冲双缓冲脏行序号与拼接管线缓存键**：
   - [MiniIOMobileFramebuffer.cpp](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp) 初始化 `RowJob` 栈变量并在单层非全屏送显时清零未覆盖边带，[MiniFramebufferRows.inc](../../hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniFramebufferRows.inc) 补判 `fAllChangedSeq > job->bufferSeq`（单测见 [test-fb-flip-rows.py](../../hackios-xnu-kernel/tools/tests/test-fb-flip-rows.py)）。
   - [annibalemetal_pipecache.inc](../../hackios-xnu-kernel/tools/userland-driver/annibalemetal_pipecache.inc) 将拼接节点 `args`、`after` 与 `constantValues` 纳入 SHA-256 管线缓存键。

`stage3-r4` 在屏扫描录制实测结果如下：

| 录制场景 | 修复前异常计数 | `stage3-r4` 帧数与关联率 | `stage3-r4` 异常计数与 GPU 报错 |
|---|---|---|---|
| 主屏长按应用图标弹出菜单 | `FLICKER_ALT: 46` | 104 帧（3,599.7 ms），104/104 关联 | 全部为 `0`，`0` 条 GPU 报错 |
| 热启动「设置」并上推返回桌面 | `BLACK_FLASH: 1, HORIZ_BAND: 1, FLICKER_ALT: 42` | 104 帧（2,516.4 ms），104/104 关联 | `BLACK_FLASH: 0, HORIZ_BAND: 0`，`0` 条 GPU 报错 |
| 上推进入多任务并点击最近卡片 | `HORIZ_BAND: 1`（`0x8f800000` 分配失败） | 104 帧（2,196.9 ms），104/104 关联 | `BLACK_FLASH: 0, HORIZ_BAND: 0`，`0` 条 GPU 报错 |
| 「文件」下载目录长按条目弹出菜单 | `BLACK_FLASH: 1, FLICKER_ALT: 36` | 95 帧（2,664.6 ms），95/95 关联 | `BLACK_FLASH: 0, HORIZ_BAND: 0, FLICKER_ALT: 0`，`0` 条 GPU 报错 |

## 4. 「钱包」黑屏与负一屏地图组件修复（MISC-1）

- **「钱包」10 秒黑屏（`G20`）**：采样调用栈确认 `Passbook` 主线程经 `passd` 同步等待 `locationd`，而 `locationd` 在 `SAPInit` 向 `HostSpecialPort 17`（`com.apple.fairplayd.versioned`）发送同步 MIG 请求 `5395`；无 FairPlay 硬件时 `fairplayd.H2` 立即退出，但 `launchd` 继续持有端口接收权使消息无限挂起。在 [mkjobs.py](../../hackios-xnu-userland/userland/mkjobs.py) 屏蔽 `fairplayd.H2`（保留 `fairplaydeviceidentityd`）后，`SAPInit` 立即返回 `KERN_INVALID_CAPABILITY`，`Passbook` 在 2 秒内正常渲染卡片页（平均亮度 `157.57`）。
- **负一屏地图快照与 `542` 对照（`G1`／`G19`）**：[air_metal_copy.inc](../../hackios-xnu-userland/tools/mesa/air/air_metal_copy.inc) 为同资源重叠 `blit` 增加临时中转纹理，[air_metal_allocation.inc](../../hackios-xnu-userland/tools/mesa/air/air_metal_allocation.inc) 为可渲染颜色纹理自动补齐 `PIPE_BIND_RENDER_TARGET`；负一屏地图小组件正常渲染底图，`MapKit.SnapshotService` 零报错。[rgb8-444-2p.m](../../hackios-xnu-userland/tools/air/rgb8-444-2p.m) 新增 `--render` 模式覆盖 `542` 渲染混合与双线性采样，宿主原生 Metal 与 Adreno 830 实测均零像素误差。
