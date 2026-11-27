# 工程、构建与系统版本待办

2026-11-27 同步批 1～批 15a 实测与审核更新。本文记录尚未完成的工程事项、验收条件和来源；历史结果保留在对应分析或进展文档中。其他主题见[待办入口](README.md)。

## 1. 构建、发布与测试环境

| 编号 | 事项 | 状态 | 下一步与验收条件 | 来源 |
|---|---|---|---|---|
| ENG-01 | 后续正式 Release 的干净克隆验证 | 待下一次发布执行 | 从已提交的顶层仓库及子模块重新克隆，按开发指南重建内核、用户态、AIR、UEFI、loader 和 Android 分区工具；记录源码与工具链版本。`build-release.py` 的根盘重建、loader 封装、隐私检查通过，再在 Linux 或容器按体验说明完成合成校验。 | [开发指南 §10](../development.md#10-生成-release)、[发布脚本](../../tools/release/build-release.py) |
| ENG-02 | adreno8 与 ir3 的外部输入对照测试 | 2026-11-16 统一运行主机测试：mic、payload、mkpayload 等全部成功；13 个 `test-adreno8-*.py` 与 `test-ir3-output-contracts.py` 缺少外部输入时跳过，尚未在提供输入的环境中运行 | 按脚本里的版本与 SHA-256 准备 graphics-kernel 源码、`msm_kgsl.ko`、厂商内核时钟源码、MiCode 内核与上游 adreno 源码，设置环境变量后运行 `python3 tools/run-host-tests.py adreno8 ir3`；验收为这 14 项全部成功，或逐项记录失败位置并区分输入版本、源码断言与环境错误 | [合入前检查](../plan/debugging-and-collaboration.md#10-合入前检查)、[主机测试入口](../../tools/run-host-tests.py) |
| ENG-21 | Wi-Fi 下的 SSH 调试 | 11-23 `tgl40` 验证运行期落盘（`oem push` + `annsh pull` 写入 `/var/jb`，sshd、zsh、sftp 均实测可用）；持久化需装进 UFS 系统镜像再刷机一次或每次开机脚本化落盘 | 按需补齐 `zsh/zle` 模块并决定是否编入后续系统盘或 `rc.jobs` 脚本；SSH 仍依赖 iOS 网络栈，不作恢复通道 | [SSH 真机验证记录](../progress/2026-11-23-ssh-over-wifi.md)、[USB 与调试方式核查 §4](../analysis/2026-11-12-usb-debugging.md#4-现有调试方式的可用范围) |

## 2. Mesa、AIR 与代码维护

| 编号 | 事项 | 状态 | 下一步与验收条件 | 来源 |
|---|---|---|---|---|
| ENG-06 | AIR 主文件与超长文件按职责拆分 | 批 14/15 已将 `tools/mesa/air/` 超标文件清零（`air_module.c` 988 + 2 `.inc`、`air_run.c` 1174 + 1 `.inc`、`air_to_nir.c` 971 + 3 `.inc`、`air_metal_test.c` 1077 + 7 `.inc`、`air_metal.h` 673 + `air_metal_render.h` 763、`air_metal.c` 751 + 7 `.inc` 均 `<= 1200` 行且过审）；`userland/` 与 `tools/` 的 `metal_drv_test.m`（1078 + 8 `.inc`）、`triangle_app.m`（762 + 1 `.inc`）、`inject_store.c`（1064 + 1 `.inc`）、`camera_isp.c`（1011 + 1 `.inc`）、`camera_device_stream.inc`（888 + 1 `.inc`）与 `metalcheck.py`（920 + `metalcheck_sweep.py` 488）均已拆分过审（`#510`/`#529`/`#533`），全仓 C/ObjC/头文件已清零超标 | 拆完下表最后 2 份 Python 辅助脚本（`intrincheck.py` 与 `kinput.py`），使 `hackios-xnu-userland` 全仓源码与脚本均 `<= 1200` 行 | [架构审查 §7.2](../analysis/2026-11-08-architecture-review.md#72-air-翻译器的完整性)、[§16](../analysis/2026-11-08-architecture-review.md#16-工程流程)、[AGENTS.md §2](../../AGENTS.md#2-代码行数约定必须遵守) |
| ENG-07 | 剩余注入钩子逐项核对原生契约 | 待逐项评估 | 按实际消费者检查关机、激活状态、图标、AirDrop、显示名、WebKit 偏好和状态栏布局；记录原生调用要求与底层缺口，完成内核、驱动或构建层修复后移除对应钩子。每项验收覆盖原消费者与未注入进程；诊断和测试用途单独确认。 | [注入钩子 §2](../analysis/2026-11-09-injection-hooks.md#2-逐项归类)、[§3](../analysis/2026-11-09-injection-hooks.md#3-结论) |

ENG-06 在 `hackios-xnu-userland/` 全仓 C/ObjC/头文件已清零，仅余 2 份 Python 辅助脚本：

| userland 仓库文件 | 当前行数 |
|---|---:|
| `tools/air/intrincheck.py` | 2452 |
| `tools/air/kinput.py` | 1451 |

## 3. 着色器覆盖与对照验证

| 编号 | 事项 | 状态 | 下一步与验收条件 | 来源 |
|---|---|---|---|---|
| ENG-08 | 23G90 着色器清单与最小 corpus | 批 14（`#472`/`#473`）更新 `metallib.py`（`112` 行，解包 `0xCAFEBABE` Fat 容器）、`air_env.py`（`81` 行）、`corpus.py`（`381` 行，默认 A830 `0x44050001`、单列 `archives` 与 `ir3 SKIPPED`）与 `test-corpus-discard.py`（`4/4` 通过）；`23G90` `corpus.py --ir3`（`QuartzCore`、`CoreImage` 等）实测 `container 3971/3971`、`reader 3971/3971`、`translate 549/3971`（`QuartzCore 174/189`、`AppleMetalGLRenderer 268/274`、`CoreImage/default 60/60`、`PortraitFilters 36/36`、`AV1SW 11/11`，`ir3 SKIPPED 549`、`archives SKIPPED 5`） | 在具备离线/真机 A830 IR3 编译器与 GPU 执行环境的节点补跑 IR3 编译与执行统计；为拒绝项提炼可公开的自编最小 shader | [架构审查 §7.2](../analysis/2026-11-08-architecture-review.md#72-air-翻译器的完整性)、[多媒体验证 §5](../analysis/2026-11-11-multimedia-validation.md#5-接手后的静态与宿主检查)、[corpus.py](../../hackios-xnu-userland/tools/air/corpus.py) |
| ENG-09 | 材质样本的原生 Metal 与 A830 像素对照 | 批 15（`#537`）完成只读审计：定稿 6 类可公开样本（双附件 fbfetch、RGBA16Float 模糊、混合状态矩阵、A8/R8 SDF、`81`/`71`/`115`/`94` 格式契约、`DontCare`/`writeMask=0` 多 Pass）及容差判据（UNORM `<= 1 LSB`、sRGB `<= 2 LSB`、`RGBA16Float <= 2 ULP`），并确认 `metal_drv_test.m` 绑定 iOS 私有符号且缺目标格式/混合/写掩码支持 | 新增纯公共 Metal API 双端对比程序（如 `material_regress.m` + `material_regress_check.py`），先在 macOS 宿主固化 6 类参考像素，待设备开测时在 A830 对比验证 | [架构审查 §8.2](../analysis/2026-11-08-architecture-review.md#82-建立材质着色器回归样本) |
| ENG-10 | Mesa 26 主机检查跳过的 A830 指令与执行语义 | 批 14（`#472`/`#473`）接入 `air_env.py`（默认 `0x44050001`、`TemporaryDirectory`、`materialize_metallib()`）：`discardcheck.py`（`442` 行）输出 `2 of 2 shapes as expected; ir3: 0 compiled, 2 SKIPPED (chip 0x44050001)`、`fbfetchcheck.py`（`313` 行）`7/7` 通过、`vattrcheck.py`（`623` 行）`16/16` 并完成 `QuartzCore` 18/37 顶点着色器 58 个输入属性核对 | 在实际 A830 配置执行 discard/demote、framebuffer fetch 与 vertex fetch 编译和像素结果对照，汇总时保持单列 `SKIPPED` | [Mesa 分析 §8](../analysis/mesa-rebase-2026-10.md#8-剩余工作)、[§10.2](../analysis/mesa-rebase-2026-10.md#102-discardcheckpy)、[§10.3](../analysis/mesa-rebase-2026-10.md#103-26x-没有离线-ir3-编译入口) |

`tools/air/check.sh` 当前默认读取 iOS 26 的 AV1SW、AppleMetalGLRenderer 和 PortraitFilters 共四个 metallib 文件，缺少输入会退出。ENG-08 需要扩充框架覆盖范围，并明确本地原版库与可公开测试样本的存放边界；已有局部编译结果见来源文档。

## 4. 系统版本与低优先级候选

| 编号 | 事项 | 状态 | 下一步与验收条件 | 来源 |
|---|---|---|---|---|
| ENG-11 | Mesa 26.3.x 升级评估 | 已授权评估；有收益即可升级 | 以官方发布内容确认目标版本，核对补丁可撤项及 A830 相关修复；结合 ENG-04、ENG-05、ENG-08～10 验证编译、行为与性能。保留 26.2.5 对照读数，再决定是否更换默认基线。 | [架构审查 §18](../analysis/2026-11-08-architecture-review.md#18-上游与同类项目更新截至-2026-11-08)、[§21 第 8 项](../analysis/2026-11-08-architecture-review.md#21-用户决定) |
| ENG-12 | iOS 27 用户态与内核 ABI 评估 | 已有静态差异记录，完整评估待做 | 重新确认目标 IPSW 与公开 XNU 版本，逐项核对系统调用、MIG、共享缓存窗口、`posix_spawnattr` 和已存在接口的语义；分开记录可沿用、需要实现和仍未知的契约。评估结果须覆盖构建、启动与当前日用功能的回归范围。 | [路线图 §3](../plan/2026-10-26-roadmap.md#3-系统版本升级)、[ABI 分析](../analysis/2026-10-26-ios26-27-kernel-abi.md) |
| ENG-13 | 后续系统镜像容量与 `darwin` 扩容流程 | 条件项，目标镜像需要扩容后执行 | 按实际镜像测量容量，复用现有 `darwin-expand-plan.py` 的离线规划与测试，补齐目标容量下的备份、数据搬移、校验及回退步骤；先验证新旧 GPT、`darwin_var` 已用块与回退数据完整，再安排设备操作。 | [架构审查 §15](../analysis/2026-11-08-architecture-review.md#15-存储网络与双系统)、[扩容规划工具](../../hackios-xnu-kernel/tools/darwin-expand-plan.py)、[规划测试](../../hackios-xnu-kernel/tools/tests/test-darwin-expand-plan.py) |
| ENG-14 | loader 菜单显示自身与系统版本 | 低优先级候选 | 复用已有 `build-id`，确定 `darwin` 系统版本的可验证来源；菜单显示与实际 loader、系统卷一致，来源缺失或读取失败时明确显示未知。当前菜单的 iOS 标题仍固定为 `iOS 26`。 | [架构审查 §15](../analysis/2026-11-08-architecture-review.md#15-存储网络与双系统)、[菜单实现](../../hackios-xnu-kernel/xnuloader/loader_06a_screen_ui.inc) |
| ENG-15 | 多任务下的压缩与换页行为 | 低优先级候选 | 固定多任务负载，采集内存占用、压缩与换页活动及前台响应；先形成读数与异常定位，再决定是否调整 zone map 或压缩池配置。 | [架构审查 §13](../analysis/2026-11-08-architecture-review.md#13-启动持久化与稳定性)、[路线图 §3.3](../plan/2026-10-26-roadmap.md#33-ios-26-移植的决策) |
| ENG-16 | 多进程场景的 `cpus=4` 与 `cpus=7` 对照 | 低优先级候选 | 固定其余参数，分别测量多任务手势、应用启动与后台安装的耗时、长帧和温度；按单变量轮次比较结果后决定核心配置。已有普通手势对照范围见原分析。 | [架构审查 §14](../analysis/2026-11-08-architecture-review.md#14-电源充电与温控)、[§19](../analysis/2026-11-08-architecture-review.md#19-建议的执行顺序与验收判据) |
| ENG-17 | 超出现有选择的系统架构调整 | 条件项，需用户决定 | iOS 27 差异较小时切换已有授权；若评估要求改变设备身份、内核路线或构建平台，先说明具体契约差异、迁移成本与功能影响，再请用户选择。Linux 构建、PAC、调度和内存配置按路线图列出的重评条件触发。 | [路线图 §3.2](../plan/2026-10-26-roadmap.md#32-选择-ios-26-与-iphone-17)、[§3.3](../plan/2026-10-26-roadmap.md#33-ios-26-移植的决策) |

## 5. 许可证与分发维护

| 编号 | 事项 | 状态 | 下一步与验收条件 | 来源 |
|---|---|---|---|---|
| ENG-19 | 后续 Release 的第三方内容分发核对 | 随发布内容复核 | 逐项核对预构建固件、设备提取资料与其他第三方文件的来源和分发许可；许可或来源未确认的内容使用本地提取流程。验收包含发布清单与 `build-release.py` review 输出中各文件的来源说明。 | [开源准备记录](../analysis/2026-10-23-open-source-readiness.md)、[开发指南 §10](../development.md#10-生成-release) |

## 6. 已解决归档

| 编号 | 事项 | 解决结论与验证范围 | 来源 |
|---|---|---|---|
| ENG-24 | k90auto 环境检查、恢复超时与 `tracev3` 离线解码 | 全部残余已闭环验证：`test-tools.py`（52 项）、`recover-loader.py` 重枚举等待、`cycle.py` NumPy 检查、`prof.py` 共享缓存过滤、内核日志互斥去重（`say3` `1308->82`）、`annsh sysctl`（`9146fd0`）、`trollstorehelper`（`582b283`）、`test-annibale-gpu-dispatch.py`、`test-annibale-apple80211-events.py`、`make-payload.py` `--memsize`/`--identity` 校验（`6/6`、`b349219`）；批 14（`#442`/`#444`）新增 `build-logarchive.py`（`530` 行）离线提取 `23G90__iPhone18,3`（`hcsd` v2）与 `ios26/{rootfs,cryptex,cryptex-app}`（`0x66778899` v2.1）组装 `.logarchive`（全量产出 `uuidtext=3520`/`dsc_uuids=4315`/`dsc_ranges=7114`、`test-build-logarchive.py` `4/4` 含本机 `/usr/bin/log show --archive --style json` 通过） | [全局现状分析 §6](../analysis/2026-11-22-global-review.md#6-工具链)、[批 6 进展 §8](../progress/2026-11-26-batch6-stall-verdict.md#8-残余问题与下轮输入)、[离线组装脚本](../../tools/k90auto/build-logarchive.py) |
| ENG-25 | 宿主侧着色器回放 | 11-24 在 macOS 重建 `air2nir`、`air_run` 与顶点回放程序（内核 `fdf59ad4`、用户态 `ab2eb6c`），使用 `g25capture1` 两次图库绘制的特化顶点 AIR 在 `llvmpipe` 与 Mac Metal 逐像素对比，差异均为 `0/16,384`，已验收 `G25` 顶点几何 | [构建与回放步骤](../../tools/k90auto/README.md#81-用-mac-回放图库的顶点着色器) |
| ENG-03 | AIR 参考编译的 LLVM 基线 | 批 14（`#485`/`#487`）固定 Homebrew LLVM `22.1.7`（支持 opaque `ptr`）并更新 `tools/air/argbufcheck.py`（`1112` 行）：将跨不同成员指针 `phi`（`air_ptr_phi.inc` `resolve_pointer_phi_places()` / `AIR_VAL_PTR_SELECT`）移入正向 `cases()`（16/16 字与参考编译一致）、在 `a sampler and two textures` 区分 `llvmpipe` 与 `softpipe`、保留 8/8 有效拒绝用例；`argbufcheck.py`（5/5 正向 + 8/8 拒绝）与 `ffma_contractcheck.py` 全过 | [多媒体验证 §9](../analysis/2026-11-11-multimedia-validation.md#9-air-常规检查与缓存)、[argbufcheck.py](../../hackios-xnu-userland/tools/air/argbufcheck.py) |
| ENG-04 | Mesa 补丁按支持版本严格应用 | 批 14（`#511`/`#518`）拆分为 `tools/mesa/*.patch`（11 份共用）、`rebase-25/*.patch`（20 份 `25.0.7` 专用）与 `rebase-26/*.patch`（39 份 `26.2.5` 专用，刷新 `ir3_nir.c` `.modes` 与 `0024` `freedreno_query_acc.c` 上下文并剔除 `26.x` 失效 hunk），`mk-mesa.sh`（303 行）/`mesa-stamp.sh`（42 行）/`mk-host.sh`（120 行）启用 `--fuzz=0`；`mesa-26.2.5.tar.xz` `50/50` 零 reject/skip/fuzz 通过，与 `mesa-arm64e` `diff -rq` 一致，macOS 宿主与 iOS `arm64e` `libannibaleair.dylib` 双端构建通过 | [Mesa 分析 §2](../analysis/mesa-rebase-2026-10.md#2-fork-补丁在-2625-上的应用结果)、[mk-mesa.sh](../../hackios-xnu-userland/tools/mk-mesa.sh) |
| ENG-05 | OSMesa 恢复补丁与平台适配分开维护 | 批 14（`#470`/`#473`）将原 `0003` 拆为 `0003-restore-osmesa.patch`（13 个纯 OSMesa 文件，剔除 6 个 CI/文档回滚噪音）与 `0003b-darwin-26.x-adaptations.patch`（3 个非 OSMesa 26.x 文件：`fd6_draw.cc`、`freedreno/meson.build`、`src/util/meson.build`），更新 `rebase-26/README.md` 与文档引用；`--fuzz=0` 零 reject/fuzz/skip，`smoke-osmesa.c` 与 `smoke-osmesa-es.c` 链接 `libOSMesa.8.dylib` 通过 | [Mesa 分析 §3](../analysis/mesa-rebase-2026-10.md#3-osmesa-恢复)、[smoke-osmesa.c](../../hackios-xnu-userland/tools/mesa/rebase-26/smoke-osmesa.c) |
