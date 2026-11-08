# 2026-11-08 framebuffer-fetch 探针与设备恢复状态

本轮使用 `out/video-plane-1108/combined/fragment-fix/integrated/verification.json` 中的内核、rootfs 和 boot 作为基线，独立检查 fragment 的 `dest_0` 读取。探针源码只增加 `air_metal_test.c` 的 `--fbfetch` 测试入口，生产 AIR/Metal 源未改。原始结果保存在本地忽略目录 `out/widget-render-1108/fbfetch-microtest/`。

## 1. 离线检查

- 基线 boot 为 `out/video-plane-1108/combined/fragment-fix/integrated/boot-direct.img`，SHA-256 为 `05f00ae32f011474f78406e02efbd902074fd63b41529bfc4f9ee1b19d3b5379`。
- 探针 `air_metal_test` 为 thin arm64e，严格签名通过，SHA-256 为 `14d7f663b45d940f29fa36c13ac38762cc43b6a9d0671f178cbbd888eea32124`。
- `fbfetch.bc` 的 SHA-256 为 `4a59e9d835258eea16fe182ac1ffffa2bcfea7115e6db8a2117f336ca6add4cc`。LLVM 汇编、反汇编和真实 AIR decode 均完成。
- NIR 包含 `uses_fbfetch_output: true`、`FRAG_RESULT_DATA0`、coherent `load_output` 和 `f2f16`。`fbfetchcheck.py` 的 7 项接口检查全部符合预期。
- 当前 Mesa 26.x 树没有独立 `ir3_compiler`，`isamm` 指令检查保留为未验证项。

QuartzCore 通用模块的静态记录显示，`dest_0` 是参数 36 的条件化 `half4` render-target 输入，谓词为 `has_dest_0`。缺少该输入时，通用模块选择 NaN 常量。完整通用模块的离线 decode 在运行时指针参数处返回错误：`intrinsic: a call passing a pointer chosen at run time as argument 2 (block 81, instruction 0, opcode 17)`，没有生成 NIR。证据见 `quartzcore-static-review.json` 和 `fixed_frag_lph_cph.decode.log`。

## 2. 真机像素结果

device 成员使用上述基线临时启动，未写入 `boot_a`。探针和 bitcode 分别通过 fastboot stage，在 A830 上执行一次，rwsh 退出码为 0，耗时 111 毫秒。

测试附件为单采样、单图层、BGRA8Unorm，预填 BGRA `234,234,234,255`，关闭 fixed blending，scissor 为 `632,369 446x446`。fragment 只返回 `dest_0`，逐像素检查整个 scissor。

- 检查像素数为 198916，失配数为 0，零 RGB 像素数为 0。
- 日志包含 `fbfetch: PASS all 198916 scissor pixels retained BGRA 234,234,234,255`。
- 结果见 `device-run/probe-result.json`、`device-run/fbfetch-run.log` 和 `device-verification.json`。

该结果证明独立 pass-through fragment 在本次 A830 路径上能够读回预填的 `dest_0`。它覆盖一个 BGRA8 附件和固定测试状态，尚未覆盖 Calendar work 70 的特化 fragment、其他附件格式、混合、TBDR 或完整系统渲染。

## 3. 停止后的实际设备状态

停止探针后，device 成员保存了运行日志、返回快照和 loader 日志。随后直接读取当前帧缓冲，屏幕显示 `KERNEL FAULT / HUNG - FASTBOOT RECOVERY`、`RETURNED 1444016 0` 和 `WAITING FOR HOST`，截图为 `out/device-recovery-1108/current-screen.png`。

当前 fastboot 状态为 `product=xnuloader`、`result=returned 1444016 0`、`ramdisk-state=ready 400000 400000 300000000`。这个状态不满足下一轮的 `result=idle` 前置条件。

`device-run/teardown-ended-kernel.log` 的末尾记录 UFS 在途请求为 0 和 `== END OF LOG ==`。同一份日志还记录 `adreno8: secure service closed; all pages retained until cold reset`，所以 GPU 资源仍保留到冷复位，不能把 stop 返回或 `returned` 状态写成设备已恢复正常。

loader 源码 `xnuloader/loader_06_usb_entry.inc:1183-1189` 在 one-shot `run_kernel` 返回后调用 `boot_fallback_enter()`，`xnuloader/loader_06a_screen_ui.inc:1041` 固定绘制 recovery 横幅。横幅文字本身不能单独证明内核 panic；当前 recovery 界面、GPU 保留状态和非 idle 状态均为实际观测结果。

本轮日志还包含 Weather、Stocks 和 Home widget 的 `getTimelines`／`getPlaceholders` watchdog。这些用户态故障需要独立排查，不能被探针的像素通过覆盖。

## 4. 后续边界

本轮结束时的恢复判据已写入[设备测试手册](../plan/device-test-playbook.md)，后续启动与主屏验收见[特化 AIR 采集记录](2026-11-08-widget-air-dump.md)。

后续 dump-AIR 轮取得实际 Tbds 模块并完成真实 decode；该模块还读取 `DATA1`。sync-log 轮已在当前保留窗口定位实际黑化 draw，见[sync draw 与首次黑化关联](2026-11-08-widget-sync-log.md)。
