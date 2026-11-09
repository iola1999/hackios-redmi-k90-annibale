# 用户态与 Metal 驱动隐式状态机收敛（2026-11-09）

本文记录对 `hackios-xnu-userland/userland/src/` 与 `hackios-xnu-kernel/tools/userland-driver/` 中隐式状态机的全面盘点、状态迁移缺陷修复，以及 `annibalemetal.m` 的按职责切分。根据[方案架构审查](2026-11-08-architecture-review.md) §21，App Store 相关模块（`inject_store.c`）排除在本次修改范围外。

## 1. 审计范围与分类汇总

本次审计覆盖用户态核心服务、应用安装器、SpringBoard／PosterBoard／应用层注入钩子，以及 iOS 26 实际打包使用的 `hackios-xnu-kernel/tools/userland-driver/` Metal 驱动与 Drawable 层，识别出 8 组跨变量或跨进程的隐式状态机。

| 编号 | 模块 | 源码位置 | 核心问题 | 处理结果 |
|---|---|---|---|---|
| SM-01 | IPA 安装器与 `appinst` 协同 | `userland/src/apps/appinst.m`、`userland/src/apps/installer_app.m` | `openURL:` 导入文件写进 `INBOX_DIR` 被 `appinst watch` 后台抢占删除；`clean_test_apps()` 把安装器注册回 `/annibale/Applications`；标记文件忽略注册退出码；GUI 状态靠分散布尔量维护 | 已修复 |
| SM-02 | Metal 命令缓冲区生命周期 | `tools/userland-driver/annibalemetal_commandbuffer.inc`、`annibalemetal_completion.inc` | `_status` 同时表达生命周期阶段与执行成败；`-commit` 中途失败导致提前唤醒等待者或信号量漏发；`-addScheduledHandler:` 无锁竞态；`calloc` 失败导致 `-waitUntilCompleted` 永久阻塞 | 已修复 |
| SM-03 | Metal 编码器与 Blit 阶段 | `tools/userland-driver/annibalemetal.m`、`annibalemetal_blit.inc` | Compute 编码器 `_complained` 与 LOD 告警共用同一布尔位导致后续 dispatch 静默丢弃；Clear 跳过时丢失 `_discards`；Blit mipmap 漏设 `textureCount = 1`；`-endEncoding` 可重复入队 | 已修复 |
| SM-04 | Metal 资源与管线所有权 | `tools/userland-driver/annibalemetal.m`、`annibalemetal_texture.inc`、`annibalemetal_pipecache.inc` | Compute／Render 管线未持有 `_owner`；`AnnibaleMetalBuffer` 映射失败返回半初始化对象；IOSurface 首次只读后转渲染目标产生双份拷贝缓冲；管线缓存并发插入重复项 | 已修复 |
| SM-05 | 触控边缘手势与亮屏门控 | `userland/src/services/input26_service.c`、`userland/src/inject/inject.c` | `waking` 位图与 `fingers[]` 结构体分离，模式切换或丢包后槽位残留旧状态 | 已修复 |
| SM-06 | 相机流与 ISP 3A 状态机 | `userland/src/services/camera_device.c`、`camera_device_stream.inc`、`camera_isp.c` | `running` 与 `graph_running` 拆分导致预热及故障态脱节；`af_now` 跨线程无锁访问；`asked` 布尔位在 IPC 丢包后锁死 AE／AF | 已修复 |
| SM-07 | SpringBoard 解锁与壁纸联动 | `userland/src/inject/inject_sb26.c`、`inject_posterboard.c` | 多路解锁触发缺少统一收敛函数；PosterBoard 晚启动漏收解锁通知；3 处钩子共用单布尔 `hooks_installed` | 已修复 |
| SM-08 | 蜂窝状态缓存与类加载钩子 | `userland/src/inject/inject_cellular.inc`、`inject_app.c` | `cell_cache` 多线程无锁读写；失网退回时残留旧算子与信号格数；在网判定阈值 `>= 3` 与 `>= 4` 混用；`dyld` 回调按单布尔门控全部蜂窝类 | 已修复 |

## 2. 各状态机修复细节

### 2.1 SM-01：IPA 安装器与 `appinst`

- `userland/src/apps/installer_app.m` 新增独立暂存目录 `/private/var/tmp/installer-staged`（`STAGED_DIR`），`openURL:` 导入的 `.ipa` 先拷入 `STAGED_DIR` 并弹窗确认，避免被 `appinst watch` 在用户点击前安装并 unlink。
- `installer_app.m` 用显式枚举 `InstallerUIState`（`INSTALLER_UI_IDLE`、`INSTALLER_UI_CONFIRMING`、`INSTALLER_UI_BUSY`）替代分散的 `_busy` 与 `_pendingOpenPath`，并将 `clean` 与 `remove` 移入后台队列执行。
- `userland/src/apps/appinst.m` 的 `ensure_installer_bundle()` 核对 `LSApplicationProxy.bundleURL.path` 是否指向 `/private/var/containers/Bundle/Application/<UUID>/AnnibaleInstaller.app`，仅在 `register_system_app()` 返回 `0` 时写入 `.annibale-source-sha256`。
- `clean_test_apps()` 末尾改调 `ensure_installer_bundle()`，保持数据卷 bundle 容器注册路径一致。
- `watch()` 增加单文件 3 次重试计数，达到上限后才记入 `done` 集合并保留原文件供排查。

### 2.2 SM-02：Metal 命令缓冲区生命周期

- `tools/userland-driver/annibalemetal_work_private.h` 与 `annibalemetal_commandbuffer.inc` 引入显式阶段 `_phase`（`RW_CB_PHASE_RECORDING`、`RW_CB_PHASE_COMMITTED`、`RW_CB_PHASE_SCHEDULED`、`RW_CB_PHASE_FINISHED`）与故障位 `_failed`。
- `-recordWork:` 与 `-commit` 入口校验 `_phase == RW_CB_PHASE_RECORDING`，拦截重复提交与提交后追加工作。
- `-commit` 内的派发失败统一经 `[self failWith:why]` 记录 `_failed = YES` 并先释放旧 `_error`，保持循环继续处理后续工作项，直至进入 `-annibaleCompleteLater:` 后再切换 `_status`、触发信号量并唤醒等待线程。
- `tools/userland-driver/annibalemetal_completion.inc` 在 `rw_completion_lock` 保护下登记 `-addScheduledHandler:`，并在 `-annibaleCompleteLater:` 遇到 `calloc` 失败时直接推进到 `RW_CB_PHASE_FINISHED`、广播 `rw_completion_done` 并执行回调，防止 `-waitUntilCompleted` 死锁。

### 2.3 SM-03：Metal 编码器与 Blit 编码状态

- `AnnibaleMetalComputeEncoder` 新增独立布尔位 `_warnedLodClamp` 记录采样器 LOD 夹紧告警，保留 `_complained` 专用于空管线或越界线程组拒绝，解决首次遇到非默认 LOD 范围后静默丢弃后续全部 compute 派发的问题。
- `AnnibaleMetalRenderEncoder` 在 `-recordPassClear` 因附件非 `MTLLoadActionClear` 跳过独立清屏工作项时，将 `_discards` 转移给首个 `-recordDraw:...` 工作项（`work->discards = _discards; _discards = 0;`）。
- `AnnibaleMetalRenderEncoder`、`AnnibaleMetalComputeEncoder` 与 `AnnibaleMetalBlitEncoder` 全部补齐 `_ended` 门控，防止 `-endEncoding` 后继续编码或重复入队结束标记。
- `tools/userland-driver/annibalemetal_blit.inc` 的 `-generateMipmapsForTexture:` 补设 `work->textureCount = 1`，由 `[work retainResources]` 持有目标纹理至命令缓冲区完成。

### 2.4 SM-04：Metal 资源生命周期与管线缓存

- `AnnibaleMetalComputePipeline` 与 `AnnibaleMetalRenderPipeline` 在初始化时 `[device retain]` 持有 `_owner`，在 `-dealloc` 完成 `mesa.compute_destroy`／`rw_pipe_release` 后释放 `_owner`。
- `AnnibaleMetalBuffer -initWithDevice:gpu:length:` 在 `IOConnectMapMemory64` 失败时直接调用 `[self release]`（内部关闭已分配的 GEM 句柄）并返回 `nil`。
- `tools/userland-driver/annibalemetal_texture.inc` 的 `rw_surface_through_copy` 首次为 IOSurface 创建平面拷贝缓冲时，将 `usage` 放宽为 `MTLTextureUsageShaderRead | MTLTextureUsageRenderTarget | MTLTextureUsagePixelFormatView`，消除先采样后作为渲染目标时的双缓冲分裂。
- `tools/userland-driver/annibalemetal_pipecache.inc` 的 `rw_pipe_keep` 在持锁状态下先查重，若同 `(device, key)` 已由并发线程插入则复用已有槽位并销毁多余副本。

### 2.5 SM-05：触控边缘手势与亮屏门控

- `userland/src/services/input26_service.c` 与 `userland/src/inject/inject.c` 将 `waking` 位图与 `fingers[]` 合并为显式单指状态枚举 `enum ann_finger_state`（`ANN_FINGER_IDLE`、`ANN_FINGER_WAKE_SWALLOWED`、`ANN_FINGER_ACTIVE_INNER`、`ANN_FINGER_ACTIVE_EDGE`）。
- 收到 `TOUCH_MODE_WAKE` 或 `0xff` 重置字节时清空全部槽位状态；收到新的 `ANNIBALE_TOUCH_DOWN` 时按当前坐标重新定界，消除丢包后的陈旧状态残留。

### 2.6 SM-06：相机流与 ISP 3A 状态机

- `userland/src/services/camera_device.c` 与 `camera_device_stream.inc` 用 `enum camera_stream_state`（`CAM_STREAM_STOPPED`、`CAM_STREAM_WARMING`、`CAM_STREAM_ACTIVE`、`CAM_STREAM_FAULTED`）统一替代 `running` 与 `graph_running`。
- `stream_begin()` 识别 `CAM_STREAM_FAULTED` 并回收旧线程后重新启动工作线程；`device_relinquish_streams()` 对处于 `WARMING`、`ACTIVE`、`FAULTED` 的流均执行停止与 join。
- `af_now`、`af_locked`、`af_window` 读写统一收归 `s->lock` 保护，触发 `af_now` 时同步重置 `s->isp.af.target = s->isp.af.at` 与 `s->isp.af.wait = 0`。
- `userland/src/services/camera_isp.h` 与 `camera_isp.c` 将单向布尔锁 `asked` 改为 4 帧超时计数 `ae_wait`，防止单次 IPC 丢包锁死后续曝光与对焦更新。

### 2.7 SM-07：SpringBoard 解锁与壁纸挂起协同

- `userland/src/inject/inject_sb26.c` 提取 `sb26_on_unlocked()` 统一收敛开机自动解锁、`com.annibale.unlock` 通知及手动解锁后的动作，移除 `isUILocked` 早期返回 `NO` 时的抢跑通知，并通过 `notify_set_state` 在 `"com.annibale.wallpaper.suspend"` 令牌上持久化 `0`（已解锁）或 `1`（锁屏挂起）。
- `userland/src/inject/inject_posterboard.c` 用位掩码 `s_mercury_hooks_mask`（`PB_HOOK_DISPLAYLINK | PB_HOOK_CMDBUF | PB_HOOK_NOTIFY`）按项追踪钩子安装，启动注册通知后立即调用 `notify_get_state` 同步当前锁屏状态，并在 `mercury_set_suspended()` 内对重复目标状态去重。

### 2.8 SM-08：蜂窝状态缓存与类加载钩子

- `userland/src/inject/inject_cellular.inc` 为 `cell_cache` 增加 `pthread_mutex_t cell_cache_lock` 保护，`modem_state < 4` 时清空缓存的 `bars`、`rat`、`operator_name`，并将所有在网判定阈值统一为 `modem_state >= 4`。
- `userland/src/inject/inject_app.c` 删除空操作 `watched_container_url_for_group`，并将 `install_cellular_hooks()` 改为按类位掩码 `cell_hooks_mask` 追踪已挂载的 CoreTelephony／SystemStatus 类，直到目标类全部就绪前保持逐镜像检查。

## 3. `annibalemetal.m` 按职责切分

原 `hackios-xnu-kernel/tools/userland-driver/annibalemetal.m` 单文件达 5,415 行。本次在不改变编译单元预处理展开顺序与导出符号的前提下，按职责切分为主文件与 7 个 `.inc` 模块，并将 `rw_blend_line`／`rw_blend_result` 归入 `annibalemetal_diag.inc`，使 `tools/userland-driver/` 下全部 28 个源码文件均控制在 1200 行以内：

| 文件 | 行数 | 职责范围 |
|---|---|---|
| `annibalemetal.m` | 1095 | 顶层说明、Mesa／AIR 接口结构声明、私有基类与驱动类 `@interface` 声明、顶层 `#include` 组装 |
| `annibalemetal_device.inc` | 724 | `AnnibaleMetalDevice` 初始化、编译器连接、Compute／Render 管线创建、Sampler 与 DepthStencil 状态创建 |
| `annibalemetal_device_caps.inc` | 576 | `AnnibaleMetalDevice` 参数编码器创建、命令队列、库加载、特性集与 GPU 族能力查询、`MTLCreateSystemDefaultDevice` |
| `annibalemetal_buffer_pipeline.inc` | 381 | `AnnibaleMetalBuffer`、`AnnibaleMetalComputePipeline`、`AnnibaleMetalRenderPipeline` 实现及纹理／状态子模块引入 |
| `annibalemetal_queue.inc` | 325 | 队列信号量提取、`AnnibaleMetalCommandQueue` 实现与 `RW_CB_*` 状态常量 |
| `annibalemetal_renderencoder.inc` | 688 | `AnnibaleMetalRenderEncoder` 通道初始化、资源绑定、清屏与绘制记录、视口／裁剪／模板状态设置 |
| `annibalemetal_renderencoder_spi.inc` | 673 | `AnnibaleMetalRenderEncoder` 存储动作、常驻声明、`<MTLRenderCommandEncoderSPI>` 桩方法、`-endEncoding` 与 `-dealloc` |
| `annibalemetal_compute_argencoder.inc` | 850 | `AnnibaleMetalComputeEncoder`、`AnnibaleMetalArgumentEncoder` 实现与 `_MTLFunction` 参数编码器运行时方法替换 |

## 4. 验证结果

- `cd hackios-xnu-userland/userland && COMPILE_ONLY=1 IOS=../../hackios-xnu-kernel/ios26 ./build.sh` 编译通过，产出 `obj/libannibalemetal.dylib`、`obj/AnnibaleMetal`、`obj/libannibale.dylib`、`obj/libannibale-sb26.dylib`、`obj/libannibale-app.dylib`、`obj/libannibale-media.dylib`、`obj/input26-service`、`obj/AnnibaleInstaller.app` 及 `obj/appinst`。
- `python3 tools/k90auto/package.py` 打包验证通过，全部 arm64e 注入库在 `-Wall -Wextra -Werror` 下无警告编译并签名，生成 `root.apfs`（SHA-256 `a3a118f4…`）。
- 宿主单测 `test-annibale-metal-timing.py`、`test-shader-cache-m1.py`、`test-metal-texture-lifetime.py`、`test-app-network.py`、`test-air-view-writeback.py`、`test_mkjobs.py` 全部执行成功。
- `tools/userland-driver/` 下全部 28 个文件及本次修改的用户态源码文件均满足 `AGENTS.md` §2 的 1200 行上限（存量文件 `inject.c` 保持 1302 行零净增长）。
