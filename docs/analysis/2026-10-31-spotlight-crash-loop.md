# Spotlight 崩溃循环与系统镜像里缺的模型（2026-10-31）

在今天视图里向下滑会打开 Spotlight 搜索。系统镜像缺排序模型时，Spotlight 每次启动都中止，ReportCrash 为每次崩溃写报告，处理器温度升到 66～69 °C。本文记录中止的位置、镜像缺模型的原因与修法，`bo21` 起 Spotlight 不再崩溃。逐轮记录见[开机次序与性能记录](../progress/2026-10-31-boot-order-and-performance.md)。

## 1. 结论

- Spotlight 中止的原因：SpotlightServices 按名字找排序模型 `<名字>.mlmodelc`，系统镜像里没有这些文件，代码把 nil 传给 `+[NSURL fileURLWithPath:]`，抛出的异常没有被捕获。
- 系统镜像缺模型的原因：`ios165/select-system.py`（`ios26/select-system.py` 是它的链接）不从框架目录取 `.mlmodelc`，按 2026-10-26 的选择规则共有 53 个包、506 MB 的模型不在镜像里。
- 修法：选择规则加上 SpotlightResources 的 root 与 English 两个必需资源包的全部文件（21 MB），重建 `system26.apfs`，见 §4。
- 循环期间今天视图滚动每步只有 7～16 帧，修后回到 29～36 帧。循环期间测的滚动帧率不能用来判断合成路径本身的开销（[合成路径的处理器开销](2026-10-31-compositor-cpu-path.md)）。

## 2. 循环的读数

以 `kernel-12377-cmd43-bo20` 为例：

- 第一次中止在今天视图里第二次向下滑结束后约 0.75 秒。之后约每秒 5 次，直到日志结束没有停，内核日志共 664 行 `redwood: proc Spotlight pid N died on signal 6`。
- 同一时段键盘相关进程启动（kbd、InputUI、inputanalyticsd、StickerPickerService），内核多次报「corpse slots full」。
- 两次 `ps` 之间全部进程的处理器时间增加 137.7 秒，其中 ReportCrash 72.5 秒。
- 处理器集群温度在循环前 41～48 °C，循环开始后 66～69 °C，GPU 54～56 °C。

## 3. 中止的位置

- `userabort` 行给出的回溯：`abort` ← libc++abi 的 rethrow ← `objc_exception_throw` ← Foundation ← SpotlightServices `+0x45b64` ← `+0x42d84` ← libdispatch 工作线程。
- SpotlightServices `+0x42c9c` 调用 `+[PRSModelManager cannedInfoForType:directivesPath:modelName:]` 取得模型名与指令文件路径，日志格式串是「[Model loading] loading canned model type %@ model name %@ directive path %@」，之后 `+0x42d80` 调用 `initSpecificModel:error:`。
- `initSpecificModel:error:` 的实现（`+0x45afc`）先拼出 `stringWithFormat:@"%@.mlmodelc"`，再从 `filePathArrayForKey:@"SpotlightServices"` 返回的文件列表里找同名文件，找不到时得到 nil，随后 `fileURLWithPath:` 收到 nil 抛出异常。
- iOS 26.6.2 的 SpotlightResources 把这些模型放在框架内的必需资源包里，例如 `RequiredAssets_root.bundle/AssetData/spotlightservices/spotlight_l2.mlmodelc`。

## 4. 镜像里缺的模型

- `select-system.py` 对框架目录的文件要求不大于 4 MB、扩展名不在 `SKIP_EXT`、路径不含 `.mlmodelc/`。模型目录里的 `.bin`、`.DAT`、`model.mil` 等因此全部不在镜像里。
- 按 2026-10-26 的 `rootfs.slt` 统计，框架与应用里被排除的模型共 506 MB、53 个包，最大的是 CoreSceneUnderstanding（252 MB）、VoiceServices（62 MB）、SpotlightResources（32 MB）。
- `KEEP_MODELS`：SpotlightResources 的 `RequiredAssets_root.bundle` 与 `RequiredAssets_en.bundle` 整包保留，共 39 个文件、21 MB，其中模型 8.5 MB，另有原先因大于 4 MB 被排除的 `parser/lexicon.cache` 与 `safety/safety_resources.map` 各约 6 MB。
- 改了选择规则要重建 `system26.apfs`，装在 Android DSU 里的那份也要重新安装（[README](../../README.md) §5）。

## 5. 修复后的读数

`kernel-12377-cmd44-bo21`，巡检与 `bo20` 相同：

- Spotlight 没有退出记录。
- 两次 `ps` 之间全部进程的处理器时间增加 45.1 秒（`bo20` 137.7 秒），ReportCrash 7.1 秒。
- 今天视图段的处理器集群温度 41～51 °C。

## 6. 未解决

- ScreenContinuity 从 `bo18` 起每轮退出 12～16 次（SIGTRAP，`usertrap` 的 pc 在 ScreenSharingKit `+0x1ef54`，Swift 运行时的陷阱），第一次退出在键盘进程启动之后。它是 REST 登记的按需任务 `com.apple.ScreenContinuityShell`，谁在查找它的服务还没有读数。
- 其余 52 个包的模型仍不在镜像里。哪些进程会在这台设备上加载它们，目前只能等进程退出或报错时逐个发现。已见过一次的是「MCCKitCategorization/TrialLoader.swift:574: Fatal error: model compile error」，`BlackPearl.mlpackage` 读不到，只出现一次，没有形成循环（`bo20`）。
