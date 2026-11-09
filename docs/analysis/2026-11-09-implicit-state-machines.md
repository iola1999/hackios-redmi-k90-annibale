# 用户态与驱动隐式状态机收敛及超长文件拆分（2026-11-09）

本文记录对 `hackios-xnu-userland/userland/src/`、`hackios-xnu-kernel/tools/userland-driver/` 及内核 IOKit 驱动中隐式状态机的全面盘点、状态迁移缺陷修复，以及超长混合职责文件的按职责切分。根据[方案架构审查](2026-11-08-architecture-review.md) §21，App Store 相关模块（`inject_store.c`，SM-14）排除在修改范围外。

## 1. 隐式状态机审计范围与处理结果

本次审计覆盖用户态引导与挂载、核心服务、SpringBoard／PosterBoard／应用层注入钩子、OpenGL ES 兼容层（`eagl.c`），以及 iOS 26 实际打包使用的 `hackios-xnu-kernel/tools/userland-driver/` Metal 驱动与 Drawable 层，盘点各项隐式状态机并在源码内收敛（SM-14 按架构审查 §21 排除）。

| 编号 | 模块 | 源码位置 | 核心问题 | 处理结果 |
|---|---|---|---|---|
| SM-02 | Metal 命令缓冲区生命周期 | `tools/userland-driver/annibalemetal_commandbuffer.inc`、`annibalemetal_completion.inc` | `_status` 同时表达生命周期阶段与执行成败；`-commit` 中途失败导致提前唤醒等待者或信号量漏发；`-addScheduledHandler:` 无锁竞态；`calloc` 失败导致 `-waitUntilCompleted` 永久阻塞 | 已修复 |
| SM-03 | Metal 编码器与 Blit 阶段 | `tools/userland-driver/annibalemetal.m`、`annibalemetal_blit.inc` | Compute 编码器 `_complained` 与 LOD 告警共用同一布尔位导致后续 dispatch 静默丢弃；Clear 跳过时丢失 `_discards`；Blit mipmap 漏设 `textureCount = 1`；`-endEncoding` 可重复入队 | 已修复 |
| SM-04 | Metal 资源与管线所有权 | `tools/userland-driver/annibalemetal.m`、`annibalemetal_texture.inc`、`annibalemetal_pipecache.inc` | Compute／Render 管线未持有 `_owner`；`AnnibaleMetalBuffer` 映射失败返回半初始化对象；IOSurface 首次只读后转渲染目标产生双份拷贝缓冲；管线缓存并发插入重复项 | 已修复 |
| SM-05 | 触控边缘手势与亮屏门控 | `userland/src/services/input26_service.c`、`userland/src/inject/inject_touch.inc` | `waking` 位图与 `fingers[]` 结构体分离，模式切换或丢包后槽位残留旧状态 | 已修复 |
| SM-06 | 相机流与 ISP 3A 状态机 | `userland/src/services/camera_device.c`、`camera_device_stream.inc`、`camera_isp.c` | `running` 与 `graph_running` 拆分导致预热及故障态脱节；`af_now` 跨线程无锁访问；`asked` 布尔位在 IPC 丢包后锁死 AE／AF | 已修复 |
| SM-07 | SpringBoard 解锁与壁纸联动 | `userland/src/inject/inject_sb26.c`、`inject_posterboard.c` | 多路解锁触发缺少统一收敛函数；PosterBoard 晚启动漏收解锁通知；3 处钩子共用单布尔 `hooks_installed` | 已修复 |
| SM-08 | 蜂窝状态缓存与类加载钩子 | `userland/src/inject/inject_cellular.inc`、`inject_app.c` | `cell_cache` 多线程无锁读写；失网退回时残留旧算子与信号格数；在网判定阈值 `>= 3` 与 `>= 4` 混用；`dyld` 回调按单布尔门控全部蜂窝类 | 已修复 |
| SM-09 | `eagl` 帧生命周期与延迟清屏 | `userland/src/gfx/eagl.c`、`eagl_shaders_vblur.inc`、`eagl_groups_plain.inc` | `clear_now()` 未保存／恢复 `GL_COLOR_WRITEMASK` 与 `GL_DEPTH_WRITEMASK`；`group_draw_begin()` 在 `group_read()` 前漏调 `clear_now()`；`frame_end()` 中 `target_to_surface()` 先清 `image->drawn` 导致 `mirror != 0` 跳过 `show_texture()` | 已修复 |
| SM-10 | `eagl` Group 合成与可重入 | `userland/src/gfx/eagl_groups_plain.inc` | `group_draw_begin()` 读取／扁平化纹理前未冲刷挂起清屏，导致读取未清屏旧内容 | 已修复 |
| SM-11 | `eagl` Plain Draw 与模糊链失效 | `userland/src/gfx/eagl.c`、`eagl_groups_plain.inc` | `drawing()` 写入绑定纹理时未失效引用该纹理的 `chains[i].made`；`plain_draw_begin()` 部分分支未初始化 `enabled[3]` 而 `plain_draw_end()` 无条件恢复 | 已修复 |
| SM-12 | Metal 递归提交与完成线程跟踪 | `tools/userland-driver/annibalemetal_commandbuffer.inc`、`annibalemetal_completion.inc` | `rw_commit_lock` 递归锁下内层 `-commit` 返回时将全局 `commit_started`／`commit_in_flight` 清零；异步完成线程等待 `mesa.finish`／`mesa.fence_wait` 时未更新 `fence_wait` 与 `hb_wait` | 已修复 |
| SM-13 | Drawable 呈现队列与表面种子 | `tools/userland-driver/annibaledrawable.m` | 已由 `AnnibaleDrawable` 单调代数与表面生命周期修复覆盖 | 已收敛 |
| SM-14 | App Store 注入与请求状态机 | `userland/src/inject/inject_store.c` | 按[方案架构审查](2026-11-08-architecture-review.md) §21 明确不做 App Store 支持 | 排除 |
| SM-15 | Stage0／Init 切根与引导阶段 | `userland/src/boot/stage0.c`、`init.c`、`init_mount.inc` | UFS `darwin` 按需读取与 `ANNFS001` 持久化切根流程已收敛 | 已收敛 |
| SM-16 | 数据盘恢复与快照落盘 | `userland/src/boot/init_mount.inc` | 早期 `var.tar` 解压恢复已移除，统一由内核 `ANNFS001` 乒乓元数据槽位直写恢复 | 已收敛 |
| SM-17 | 音频与触觉插件句柄生命周期 | `userland/src/services/audio_plugin.c` | `codec_read` 与 `codec_close` 并发无锁操作 `mic`；`get_zero_time_stamp` 使用 O(N) 追赶循环且首次 `anchor == 0` 漏初始化；`actuator_write` 在临时打开失败时永久置 `haptic = -2` | 已修复 |
| SM-18 | Metal 函数特化与 Bitcode 转发 | `tools/userland-driver/annibalemetal_stitch.inc` | `-annibaleUnspecializedFunction` 未检查 `_cachedBitcode` 导致与 `-respondsToSelector:` 契约矛盾；转发方法存在不可达的 `bitcodeData` 分支 | 已修复 |
| SM-19 | 媒体服务与 WebKit VP9 一次性钩子 | `userland/src/inject/inject_media.c`、`inject_app.c` | `replace_one()` 在扫描到类但方法未就绪时提前置 `r->done = true`；`app_enable_webkit_vp9()` 在 `WKPreferences` 加载前每次 `dyld` 回调重复派发 `NSUserDefaults` 写入 | 已修复 |
| SM-20 | SpringBoard RunLoop 卡顿看门狗 | `userland/src/inject/inject_sb26_rate.c` | `stall_watch` 在 `usleep(10000)` 前采样 `began`，睡眠期间开始的 RunLoop turn 需多等一轮才开始计时 | 已修复 |
| SM-21 | 诊断工具等待与退出清理 | `userland/src/apps/framewatch.m`、`annsig.m`、`annsh.c` | `framewatch` 在 `max_dumps == 0` 时不打印达到阈值的停帧日志；`annsig` 在无 `kern.annibale.frames` 环境误触 90 秒停帧中止且重复调用 `continue_all()`；`annsh` 的 `do_spawn()` 被后台继承管道的子进程拖满 25 秒超时 | 已修复 |

## 2. 各状态机修复细节

### 2.1 SM-02 与 SM-12：Metal 命令缓冲区生命周期、递归提交与完成看门狗

- `tools/userland-driver/annibalemetal_work_private.h` 与 `annibalemetal_commandbuffer.inc` 引入显式阶段 `_phase`（`RW_CB_PHASE_RECORDING`、`RW_CB_PHASE_COMMITTED`、`RW_CB_PHASE_SCHEDULED`、`RW_CB_PHASE_FINISHED`）与故障位 `_failed`。
- `-recordWork:` 与 `-commit` 入口校验 `_phase == RW_CB_PHASE_RECORDING`，拦截重复提交与提交后追加工作。
- `-commit` 内的派发失败统一经 `[self failWith:why]` 记录 `_failed = YES` 并先释放旧 `_error`，保持循环继续处理后续工作项，直至进入 `-annibaleCompleteLater:` 后再切换 `_status`、触发信号量并唤醒等待线程。
- `tools/userland-driver/annibalemetal_commandbuffer.inc` 在 `-commit` 持递归锁 `rw_commit_lock` 期间保存外层 `prev_started = commit_started` 与 `prev_in_flight = commit_in_flight`，退出前按需恢复外层状态，防止内层同步提交返回时把外层看门狗状态清零。
- `tools/userland-driver/annibalemetal_completion.inc` 在 `rw_completion_lock` 保护下登记 `-addScheduledHandler:`，在 `calloc` 失败时直接推进到 `RW_CB_PHASE_FINISHED` 并唤醒等待者；在异步完成线程执行 `mesa.finish`／`mesa.fence_wait` 前后同步维护 `fence_wait`、`fence_frame`、`fence_owner`、`fence_tid`、`fence_began_us` 与 `hb_wait`。

### 2.2 SM-03 与 SM-18：Metal 编码器、Blit 与特化函数转发

- `AnnibaleMetalComputeEncoder` 新增独立布尔位 `_warnedLodClamp` 记录采样器 LOD 夹紧告警，保留 `_complained` 专用于空管线或越界线程组拒绝。
- `AnnibaleMetalRenderEncoder` 在 `-recordPassClear` 因附件非 `MTLLoadActionClear` 跳过独立清屏工作项时，将 `_discards` 转移给首个 `-recordDraw:...` 工作项（`work->discards = _discards; _discards = 0;`）。
- `AnnibaleMetalRenderEncoder`、`AnnibaleMetalComputeEncoder` 与 `AnnibaleMetalBlitEncoder` 全部补齐 `_ended` 门控。
- `tools/userland-driver/annibalemetal_blit.inc` 的 `-generateMipmapsForTexture:` 补设 `work->textureCount = 1`，由 `[work retainResources]` 持有目标纹理至命令缓冲区完成。
- `tools/userland-driver/annibalemetal_stitch.inc` 的 `-[AnnibaleMetalSpecializedFunction annibaleUnspecializedFunction]` 在 `_cachedBitcode != nil` 时返回 `nil`，与 `-respondsToSelector:` 保持一致，并移除 `-forwardingTargetForSelector:`、`-methodSignatureForSelector:`、`-forwardInvocation:` 中不可达的 `bitcodeData` 分支。

### 2.3 SM-04：Metal 资源生命周期与管线缓存

- `AnnibaleMetalComputePipeline` 与 `AnnibaleMetalRenderPipeline` 在初始化时 `[device retain]` 持有 `_owner`，在 `-dealloc` 完成 `mesa.compute_destroy`／`rw_pipe_release` 后释放 `_owner`。
- `AnnibaleMetalBuffer -initWithDevice:gpu:length:` 在 `IOConnectMapMemory64` 失败时直接调用 `[self release]` 并返回 `nil`。
- `tools/userland-driver/annibalemetal_texture.inc` 的 `rw_surface_through_copy` 首次为 IOSurface 创建平面拷贝缓冲时，将 `usage` 放宽为 `MTLTextureUsageShaderRead | MTLTextureUsageRenderTarget | MTLTextureUsagePixelFormatView`。
- `tools/userland-driver/annibalemetal_pipecache.inc` 的 `rw_pipe_keep` 在持锁状态下先查重，若同 `(device, key)` 已由并发线程插入则复用已有槽位并销毁多余副本。

### 2.4 SM-05：触控边缘手势与亮屏门控

- `userland/src/services/input26_service.c` 与 `userland/src/inject/inject_touch.inc` 将 `waking` 位图与 `fingers[]` 合并为显式单指状态枚举 `enum ann_finger_state`（`ANN_FINGER_IDLE`、`ANN_FINGER_WAKE_SWALLOWED`、`ANN_FINGER_ACTIVE_INNER`、`ANN_FINGER_ACTIVE_EDGE`）。
- 收到 `TOUCH_MODE_WAKE` 或 `0xff` 重置字节时清空全部槽位状态；收到新的 `ANNIBALE_TOUCH_DOWN` 时按当前坐标重新定界。

### 2.5 SM-06：相机流与 ISP 3A 状态机

- `userland/src/services/camera_device.c` 与 `camera_device_stream.inc` 用 `enum camera_stream_state`（`CAM_STREAM_STOPPED`、`CAM_STREAM_WARMING`、`CAM_STREAM_ACTIVE`、`CAM_STREAM_FAULTED`）统一替代 `running` 与 `graph_running`。
- `stream_begin()` 识别 `CAM_STREAM_FAULTED` 并回收旧线程后重新启动工作线程；`device_relinquish_streams()` 对处于 `WARMING`、`ACTIVE`、`FAULTED` 的流均执行停止与 join。
- `af_now`、`af_locked`、`af_window` 读写统一收归 `s->lock` 保护，触发 `af_now` 时同步重置 `s->isp.af.target = s->isp.af.at` 与 `s->isp.af.wait = 0`。
- `userland/src/services/camera_isp.h` 与 `camera_isp.c` 将单向布尔锁 `asked` 改为 4 帧超时计数 `ae_wait`。

### 2.6 SM-07 与 SM-20：SpringBoard 解锁、壁纸协同与 RunLoop 卡顿检测

- `userland/src/inject/inject_sb26.c` 提取 `sb26_on_unlocked()` 统一收敛开机自动解锁、`com.annibale.unlock` 通知及手动解锁后的动作，移除 `isUILocked` 早期返回 `NO` 时的抢跑通知，并通过 `notify_set_state` 在 `"com.annibale.wallpaper.suspend"` 令牌上持久化 `0`（已解锁）或 `1`（锁屏挂起）。
- `userland/src/inject/inject_posterboard.c` 用位掩码 `s_mercury_hooks_mask`（`PB_HOOK_DISPLAYLINK | PB_HOOK_CMDBUF | PB_HOOK_NOTIFY`）按项追踪钩子安装，启动注册通知后立即调用 `notify_get_state` 同步当前锁屏状态，并在 `mercury_set_suspended()` 内对重复目标状态去重。
- `userland/src/inject/inject_sb26_rate.c` 的 `stall_watch` 线程将 `uint64_t began = turn_began;` 移至 `usleep(10000)` 之后，使睡眠期间开始的 RunLoop turn 立即进入耗时判定。

### 2.7 SM-08 与 SM-19：蜂窝状态缓存、媒体钩子与 WebKit VP9 初始化

- `userland/src/inject/inject_cellular.inc` 为 `cell_cache` 增加 `pthread_mutex_t cell_cache_lock` 保护，`modem_state < 4` 时清空缓存的 `bars`、`rat`、`operator_name`，并将所有在网判定阈值统一为 `modem_state >= 4`。
- `userland/src/inject/inject_app.c` 删除空操作 `watched_container_url_for_group`，将 `install_cellular_hooks()` 改为按类位掩码 `cell_hooks_mask` 追踪已挂载类，并在 `app_enable_webkit_vp9()` 内用 `vp9_defaults_scheduled` 限制 `dlsym` 与 `NSUserDefaults` 主队列派发只执行一次。
- `userland/src/inject/inject_media.c` 的 `replace_one()` 仅在找到目标方法（或记录预期地址不匹配）后置 `r->done = true`。

### 2.8 SM-09、SM-10 与 SM-11：OpenGL ES 兼容层（`eagl`）状态恢复与缓存失效

- `userland/src/gfx/eagl_shaders_vblur.inc` 的 `clear_now()` 保存并恢复 `GL_COLOR_WRITEMASK` 与 `GL_DEPTH_WRITEMASK`，执行延迟清屏期间强制开启颜色四通道与深度写掩码。
- `userland/src/gfx/eagl_groups_plain.inc` 的 `group_draw_begin()` 在调用 `group_read()` 与 `group_flatten()` 前先调用 `clear_now(e)` 冲刷挂起清屏，并在 `plain_draw_begin()` 的所有分支中保存 `enabled[3]` 以匹配 `plain_draw_end()` 的恢复逻辑。
- `userland/src/gfx/eagl.c` 的 `frame_end()` 在首轮循环调用 `target_to_surface()` 清零 `image->drawn` 前，对 `mirror != 0` 的目标纹理先行调用 `show_texture()`；`eagl_shaders_vblur.inc` 的 `drawing()` 在绑定帧缓冲发生绘制时将匹配 `e->colour` 的 `e->chains[i].made` 置 `0`。

### 2.9 SM-17 与 SM-21：音频插件锁保护与诊断工具退出清理

- `userland/src/services/audio_plugin.c` 在 `codec_read()` 与 `codec_close()` 中加 `lock` 保护 `mic` 句柄；`get_zero_time_stamp()` 在 `d->anchor == 0` 时初始化 `d->anchor = now` 并用 O(1) 除法推进周期；`actuator_write()` 仅在 `errno == ENOENT` 时将 `haptic` 标为 `-2`。
- `userland/src/apps/framewatch.m` 在 `max_dumps == 0` 或转储配额耗尽时仍按 `still_seconds` 输出停帧日志；`annsig.m` 在 `frames == 0 && last_frames == 0` 时跳过 90 秒停帧中止并移除 `main()` 返回前与 `atexit(on_exit)` 重复的 `continue_all()`；`annsh.c` 的 `do_spawn()` 在 `poll()` 空闲时通过 `waitpid(pid, &status, WNOHANG)` 检测主子进程退出，防止后台孙进程持有管道写端拖满 25 秒超时。

## 3. 全仓超长代码文件排查与按职责切分

对 `hackios-xnu-kernel` 与 `hackios-xnu-userland` 全仓超过 1200 行的代码文件逐一排查后，将职责混杂的 5 个核心生产文件（`annibalemetal.m`、`inject.c`、`eagl.c`、`MiniIOSurface.cpp`、`MiniIOMobileFramebuffer.cpp`）按职责切分为独立子模块，切分后全部在 1200 行上限以内：

| 原文件 | 原行数 | 切分后主文件与子模块 | 行数 | 职责划分 |
|---|---|---|---|---|
| `tools/userland-driver/annibalemetal.m` | 5415 | `annibalemetal.m`<br>`annibalemetal_device.inc`<br>`annibalemetal_device_caps.inc`<br>`annibalemetal_buffer_pipeline.inc`<br>`annibalemetal_queue.inc`<br>`annibalemetal_renderencoder.inc`<br>`annibalemetal_renderencoder_spi.inc`<br>`annibalemetal_compute_argencoder.inc` | 1095<br>724<br>576<br>381<br>325<br>688<br>673<br>850 | 顶层接口声明与组装<br>设备初始化、管线／采样器／深度模板创建<br>参数编码器、命令队列、库加载与能力查询<br>Buffer 与 Compute／Render 管线对象实现<br>命令队列与信号量提取<br>渲染编码器通道初始化、绑定与绘制<br>渲染编码器存储动作、SPI 桩与生命周期<br>计算编码器与参数编码器实现 |
| `userland/src/inject/inject.c` | 1302 | `inject.c`<br>`inject_touch.inc` | 846<br>457 | backboardd／containermanagerd／powerd 系统钩子与入口<br>backboardd HID 虚拟触控与按键事件派发、帧延迟观测 |
| `userland/src/gfx/eagl.c` | 4228 | `eagl.c`<br>`eagl_shaders_vblur.inc`<br>`eagl_groups_plain.inc`<br>`eagl_entries_context.inc` | 1173<br>1025<br>862<br>1172 | 上下文结构、IOSurface 纹理共享／拷贝与帧起止统计<br>手写 GL 入口、着色器重写、绘制追踪与可变半径模糊（vblur）<br>Plain Program 无着色器绘制、Group 活力层合成与延迟清屏<br>GL 状态入口、调用栈采样与 `EAGLContext` 方法替换（同步扩展 `mkeagl.py` 扫描 `eagl_*.inc`） |
| `xnu/files/iokit/Kernel/MiniIOSurface.cpp` | 1617 | `MiniIOSurface.cpp`<br>`MiniIOSurfaceUserClient.inc` | 1074<br>544 | `MiniIOSurface`／`IOSurfaceRoot` 内核服务、共享页布局与客户端引用表维护<br>`IOSurfaceRootUserClient` 外部方法（selector 分发）与 Mach trap 实现 |
| `xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp` | 1517 | `MiniIOMobileFramebuffer.cpp`<br>`MiniFramebufferUserClient.inc` | 1031<br>487 | `IOMobileFramebuffer` 显示表面、缩放混合、DCS 背光与翻转调度<br>`IOMobileFramebufferUserClient` 外部方法、`IOAcceleratorES` 与启动注册 |

其余超过 1200 行的存量文件经评估保持原状，原因如下：

- `hackios-xnu-kernel/tools/mesa/air/`（`air_metal.c` 6782 行、`air_to_nir.c` 3461 行、`air_run.c` 2093 行、`air_module.c` 1950 行、`air_metal.h` 1438 行）：受 `tools/mesa-stamp.sh` 的 `mesa_air_stamp` 与 `air-build-record.json` 源码哈希强校验保护，任何文件变动都会使预构建 `libannibaleair.dylib` 印章失效，已记入[进度表](../plan/2026-10-23-tracking.md) §2 待后续重编 AIR 时一并按职责拆分。
- `hackios-xnu-userland/userland/src/inject/inject_store.c`（1827 行）：App Store 诊断与钩子模块，按[方案架构审查](2026-11-08-architecture-review.md) §21 明确不做。
- `hackios-xnu-kernel/xnu/files/bsd/miscfs/apfs/`（`apfs_lib.c` 4062 行、`apfs_vfsops.c` 1462 行、`apfs_vnops.c` 1261 行、`deflate_decompress.c` 1208 行）：只读 APFS 容器解析、B-tree 查找与解压算法实现，职责单一且本轮无修改。
- 独立测试与离线工具（`userland/src/tests/metal_drv_test.m` 7799 行、`tools/mesa/air/air_metal_test.c` 6931 行、`userland/src/tests/triangle_app.m` 1273 行、`tools/air/*.py`）：单文件验收测试集，不参与系统运行态镜像。

## 4. 验证结果

- `cd hackios-xnu-userland/userland && COMPILE_ONLY=1 IOS=../../hackios-xnu-kernel/ios26 ./build.sh` 编译通过，产出 `obj/libannibalemetal.dylib`、`obj/AnnibaleMetal`、`obj/libannibale.dylib`、`obj/libannibale-sb26.dylib`、`obj/libannibale-app.dylib`、`obj/libannibale-media.dylib`、`obj/AnnibaleAudio`、`obj/input26-service`、`obj/TrollStore.app`、`obj/trollstorehelper`、`obj/framewatch`、`obj/annsig` 及 `obj/annsh`。
- `./mkeagl.py` 扩展 `eagl_*.inc` 扫描后识别全部 409 个槽位（356 个透传、30 个手写入口、23 个空桩），`src/gfx/eagl.c` 与 `src/gfx/gl_osmesa.c` 编译链接生成 `obj/libannibale-gl.dylib` 通过。
- `python3 tools/k90auto/package.py` 打包验证通过，全部 arm64e 注入库在 `-Wall -Wextra -Werror` 下无警告编译并签名，生成 `root.apfs`（SHA-256 `f580ebf3…`）。
- 用户态与内核宿主单测 `test-audio-plugin.py`、`test-app-network.py`、`test-air-view-writeback.py`、`test_mkjobs.py`、`test-annibale-metal-timing.py`、`test-shader-cache-m1.py`、`test-iosurface-abi.py`、`test-iosurface-bridge.py`、`test-fb-swap.py`、`test-fb-scale.py`、`test-frame-latch.py`、`test-frames.py`、`test-annibale-gpu-lifetime.py`、`test-annibale-input.py` 全部执行成功。
