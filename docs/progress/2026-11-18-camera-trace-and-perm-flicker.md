# 相机编码链观测与定位授权弹窗整屏闪烁（2026-11-18）

本文记录 2026-11-18 三轮相机观测（`cam3-trace`、`cam3-trace2`、`cam3-ane`，内核 `12377-stage4-k7`）得到的拍照落盘线索，以及 `cam3-trace2` 轮 GPU 停转后整屏亮暗闪烁的经过与处理。待办见[多媒体待办 M6](../backlog/multimedia.md)与[系统待办 S21](../backlog/system.md)。轮次目录为 `docs/progress/evidence/k90auto/kernel-12377-stage4-k7-cam3-*`，闪烁现场在 `out/cam-perm-flicker-2026-11-18/`，均为 Git 忽略目录。

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
- 两条消息没有记录被拒的纹理参数。三轮的 `DCIM` 下都只有 `.MISC`，没有照片文件。

## 3. 定位授权弹窗期间的 GPU 停转与整屏闪烁

- `cam3-trace2` 轮打开相机后弹出带地图预览的定位授权（`CoreLocationVanillaWhenInUseAuthPromptPlugin`）。01:38:14 adreno8 报 `external BO health check failed; submissions closed and pages retained until cold reset` 与 `GPU power, HFI or translation check failed`。
- 停转前最后十几次 GPU 提交来自该插件。轮次的 `render-report.txt`「before the GPU stopped」一节列出了这些提交，主机侧合并日志没有缺口。
- 同一秒内，CoreLocation 插件、cameracaptured、backboardd 都以 `exception 1`、访问地址 `0x18` 崩溃。按各进程日志里 `images:` 行的加载基址换算，三处 pc 都是 `libannibaleair.dylib` 偏移 `0x3cf578`，即 `fd_bo_mark_for_dump()` 的第一条指令 `ldr w8, [x0, #0x18]`：GPU 停转后 `fd_bo_new()` 返回 NULL，`upload_shader_variant()` 与 `fd6_build_bindless_state()` 没有检查就传给它。
- 停转后 `AnnibaleGPUUserClient::start` 拒绝所有新客户端（`0xe00002c7`）：`annibale_gpu_recover()` 恒返回 false，`gGPUReported` 置位后不再清除。SpringBoard 重启后拿不到 Metal 设备，在 SiriUICore 内空指针崩溃（未滑移 pc `0x1c6e27ac0`）。本轮 SpringBoard 先后起了 5 个进程，backboardd 重启过一次。
- 这一轮结束时设备照常留在 iOS，之后整屏亮暗交替闪烁、点击无响应。取截图与日志后经 `recover-loader.py` 退回 loader，闪烁停止，没有按键。

## 4. 处理

- `tools/k90auto/cycle.py` 在留机前检查本轮全部日志快照：出现 GPU 停转行，或 SpringBoard 以多于一个进程连接 backboardd，就改为收尾并退回 loader。用 `cam3-trace2` 的日志检查，结果为「the GPU stopped」；宿主测试在 `tools/k90auto/tests/test-cycle-state.py`。
- [AGENTS.md](../../AGENTS.md) 第 5 节新增三条：运行态稳定性巡检、整屏闪烁紧急停、高耗能状态限时保持。

## 5. 下一步

- `CAM-3`：给两处 nil 返回补上被拒纹理的像素格式、平面数、用途与尺寸，复测时找出不满足的条件。
- Espresso 的 ANE 引擎在 K90 上返回 NULL。Espresso 自带的 CPU 回退要求内核报告运行在虚拟机里，这会影响其他读取同一信息的框架，是否采用需要用户决定。
- GPU 停转（S21）：从 `cam3-trace2` 的合并日志查 `external BO health check failed` 的来源。Mesa 在 `fd_bo_new()` 失败后崩溃只发生在停转之后，补空指针检查不能恢复绘制，排在停转原因之后处理。
