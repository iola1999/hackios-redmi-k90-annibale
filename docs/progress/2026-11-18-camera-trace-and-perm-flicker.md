# 相机编码链观测与定位授权弹窗整屏闪烁（2026-11-18）

本文记录 2026-11-18 三轮相机观测（`cam3-trace`、`cam3-trace2`、`cam3-ane`，内核 `12377-stage4-k7`）与两轮复测（`cam3d`、`mapk1`，内核 `12377-bt1`）得到的拍照落盘线索，`cam3-trace2` 轮 GPU 停转后整屏亮暗闪烁的经过与处理，以及地图快照服务崩溃的修复。待办见[多媒体待办 M6](../backlog/multimedia.md)与[系统待办 S21](../backlog/system.md)。轮次目录为 `docs/progress/evidence/k90auto/kernel-12377-stage4-k7-cam3-*` 与 `kernel-12377-bt1-{cam3d,mapk1}`，闪烁现场在 `out/cam-perm-flicker-2026-11-18/`，均为 Git 忽略目录。

## 1. Espresso 上下文观测

- `cam3-trace` 轮在 `libannibale-media.dylib` 里加了只记日志的 interpose，覆盖 Espresso 与 CMPhoto 的 14 个 C 接口，以 `-undefined dynamic_lookup` 链接。dylib 正常加载进 cameracaptured，原有 ObjC hook 照常生效。
- 打开相机后记录到 3 次 `espresso_create_context`：引擎 `10006` 两次、`10007` 一次，`dev=-1`，返回值都是 0（NULL）。
- 与静态分析对应：`Espresso::hardware::supports_platform(10007)` 先查 ANE 是否存在，K90 上为否；`espresso_create_context` 只有在 `is_virtual_machine()` 成立时才把引擎改成 CPU。
- 后两轮改用 tbd 两级弱导入链接后 interpose 命中数为 0，这种链接方式没有保留，interpose 也没有入库。
- 设备日志含二进制字节，检索时 `grep` 要加 `-a`，否则只输出「Binary file matches」，容易误判为没有匹配。

## 2. 快门前后的错误

- `cam3-ane` 轮里，`ANE model load failure: ... Program load failure (0x3) @ GetANEFModel` 与 `Invalid Function Argument: *handle is NULL. @ operator()` 在打开相机后、按快门之前就已出现（快照 `s018`，第一次快门在 `s019`）。它是否阻断照片保存未确认。
- 按快门后，静态图处理链运行了 `defringe_still`、`StyleEngineImage::CopyPlaneToArray` 等计算管线，随后 Metal 驱动在 cameracaptured 里两次返回 nil：
  - `combined YCbCr requires a two-plane, single-level sampled surface`（`annibalemetal_yuv.inc`）
  - `RGB2P requires a two-plane, single-level sample/render surface`（`annibalemetal_rgb2p.inc`）
- 三轮的 `DCIM` 下都只有 `.MISC`，没有照片文件。被拒纹理的参数见第 4 节。

## 3. 定位授权弹窗期间的 GPU 停转与整屏闪烁

- `cam3-trace2` 轮打开相机后弹出带地图预览的定位授权（`CoreLocationVanillaWhenInUseAuthPromptPlugin`）。01:38:14 adreno8 报 `external BO health check failed; submissions closed and pages retained until cold reset` 与 `GPU power, HFI or translation check failed`。
- 停转前最后十几次 GPU 提交来自该插件。轮次的 `render-report.txt`「before the GPU stopped」一节列出了这些提交，主机侧合并日志没有缺口。
- 停转的直接原因是 SMMU 翻译错误：`gpu SMMU fault 0x2 at 0:0, syndrome 0xe0002`（FSR 为翻译错误，FSYNR0 为读访问），GPU 读了 IOVA 0；内核记录的最近 4096 次分配里没有 BO 覆盖这个地址。日志里「nearest live above」给出的是地址最低的有效 BO，不能说明访问来自哪个进程。某次绘制引用了地址为 0 的资源，具体是哪类绑定未确认。
- 同一秒内，CoreLocation 插件、cameracaptured、backboardd 都以 `exception 1`、访问地址 `0x18` 崩溃。按各进程日志里 `images:` 行的加载基址换算，三处 pc 都是 `libannibaleair.dylib` 偏移 `0x3cf578`，即 `fd_bo_mark_for_dump()` 的第一条指令 `ldr w8, [x0, #0x18]`：GPU 停转后 `fd_bo_new()` 返回 NULL，`upload_shader_variant()` 与 `fd6_build_bindless_state()` 没有检查就传给它。
- 停转后 `AnnibaleGPUUserClient::start` 拒绝所有新客户端（`0xe00002c7`）：`annibale_gpu_recover()` 恒返回 false，`gGPUReported` 置位后不再清除。SpringBoard 重启后拿不到 Metal 设备，在 SiriUICore 内空指针崩溃（未滑移 pc `0x1c6e27ac0`）。本轮 SpringBoard 先后起了 5 个进程，backboardd 重启过一次。
- 这一轮结束时设备照常留在 iOS，之后整屏亮暗交替闪烁、点击无响应。取截图与日志后经 `recover-loader.py` 退回 loader，闪烁停止，没有按键。

## 4. 复测：被拒纹理的参数

`cam3d` 轮在驱动的两处 nil 返回里打印了纹理描述与 IOSurface 平面尺寸，流程为打开相机、点两次快门、列 `DCIM`、回到桌面。

| 路径 | 像素格式 | 纹理 | IOSurface 平面 | 用途 |
|---|---|---|---|---|
| combined YCbCr（`annibalemetal_yuv.inc`） | 500 | 2D，2×2，单层、单级、单采样 | 2 个，平面 0 为 8×8 | `0x7` |
| RGB2P（`annibalemetal_rgb2p.inc`） | 540 | 2D，2×2，单层、单级、单采样 | 2 个，8×8 与 4×4 | `0x7` |

- 两处唯一不满足的条件是用途：`0x7` 含 ShaderWrite（`0x2`），驱动与 Mesa `rwa_texture_combine_rgb2p()` 只接受 ShaderRead、RenderTarget、PixelFormatView（`0x15`）。Mesa 的 `rwa_texture_combine_yuv()` 只生成采样纹理，`rwa_texture_combine_rgb2p()` 支持采样与渲染，两者都没有着色器写入，放开检查前需要先在 Mesa 里实现双平面纹理的写入。
- 两条拒绝各出现一次，在回到桌面之后，cameracaptured 正在创建 `colorCubeFragment2D`、`cubeColorConvertFrag` 等渲染管线；之后它继续创建 `edld_kernels`、`idc_utilitiesKernels`、`icpw_kernels` 计算管线，没有崩溃。8×8 表面上的 2×2 纹理是否只用于初始化检查未确认。
- 打开相机后、第一次快门之前，`deferredmediad` 开始创建 RAW 去马赛克、`RawDF` 融合、`StyleEngineImage` 与 `FlexGTC` 计算管线，最后一条是 `FlexGTCHistogramLumaAndGain`，之后本轮没有它的日志。
- 轮次结束后 `DCIM` 只有 `.MISC`，`PhotoData/Caches/ClientServerTransactions` 为空，照片没有进入 assetsd 的导入流程。
- 本轮没有出现定位授权弹窗，也没有 GPU 停转。

## 5. 地图快照服务崩溃与 GPU 停转复现

- 四轮相机测试里 `com.apple.MapKit.SnapshotService` 都以 `exception 1`、访问地址 `0x308` 崩溃。按 `images:` 行换算，pc 是 `libannibaleair.dylib` 偏移 `0x3115e4`，即 freedreno `batch_draw_tracking()` 读 `fd_resource(pfb->zsbuf.texture)->valid`：绑定的深度模板状态打开了深度测试，渲染通道却没有深度附件，`zsbuf.texture` 为 NULL。
- `rwa_depth_stencil_create()` 对任何 `MTLDepthStencilState` 都打开深度测试，绘制时照原样绑定。Metal 在渲染通道没有深度／模板附件时不做这两项测试，Gallium 要求前端自行关闭。用户态仓库 `tools/mesa/air/air_metal.c` 改为：没有深度／模板附件的绘制绑定全零的深度模板状态。
- `mapk1` 轮用新的 AIR 库打开相机、按快门，再打开「地图」。快照服务提交了 28 个带追踪的命令缓冲，没有崩溃。
- 「地图」启动后立即弹出定位授权，弹窗里的地图预览为黑色。随后 GPU 以同样的 `SMMU fault 0x2 at 0:0` 停转，停转前最后的提交仍来自 `CoreLocationVanillaWhenInUseAuthPromptPlugin`（每次 131 个缓冲、415 字），与 `cam3-trace2` 相同。弹窗插件进程内用 VectorKit 渲染地图（`DaVinci::ground`、`SolidRibbon`、`GlyphWithNormalHalo` 等管线）。
- `cycle.py` 判定「the GPU stopped」后没有留机，`oem recovery` 因内核保留资源被拒，随后经 `recover-loader.py` 退回 loader 空闲态，没有按键。两次停转都发生在定位授权弹窗显示期间，打开「地图」触发弹窗可以作为复现步骤，复现率还没有统计。

## 6. 处理

- `tools/k90auto/cycle.py` 在留机前检查本轮全部日志快照：出现 GPU 停转行，或 SpringBoard 以多于一个进程连接 backboardd，就改为收尾并退回 loader。用 `cam3-trace2` 的日志检查，结果为「the GPU stopped」；宿主测试在 `tools/k90auto/tests/test-cycle-state.py`。
- [AGENTS.md](../../AGENTS.md) 第 5 节新增三条：运行态稳定性巡检、整屏闪烁紧急停、高耗能状态限时保持。

## 7. 下一步

- `CAM-3`：找出快门后拍照结果停在哪一步（相机应用的拍照回调、cameracaptured 编码节点或 `deferredmediad`）。确认 2×2 组合纹理在拍照链里会被使用后，再在 Mesa 实现双平面纹理的着色器写入。
- Espresso 的 ANE 引擎在 K90 上返回 NULL。Espresso 自带的 CPU 回退要求内核报告运行在虚拟机里，这会影响其他读取同一信息的框架，是否采用需要用户决定。
- GPU 停转（S21）：用「打开地图、等待定位授权弹窗」复现，找出弹窗插件的 VectorKit 绘制里引用 IOVA 0 的绑定（纹理、缓冲或描述符）。Mesa 在 `fd_bo_new()` 失败后崩溃只发生在停转之后，补空指针检查不能恢复绘制，排在停转原因之后处理。
