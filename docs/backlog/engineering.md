# 工程、构建与系统版本待办

2026-11-12 按当前文档与源码整理。本文记录尚未完成的工程事项、验收条件和来源；历史结果保留在对应分析或进展文档中。本轮只核对文件与脚本，没有重新运行构建、测试或真机轮次。其他主题见[待办入口](README.md)。

## 1. 构建、发布与测试环境

| 编号 | 事项 | 状态 | 下一步与验收条件 | 来源 |
|---|---|---|---|---|
| ENG-01 | 后续正式 Release 的干净克隆验证 | 待下一次发布执行 | 从已提交的顶层仓库及子模块重新克隆，按开发指南重建内核、用户态、AIR、UEFI、loader 和 Android 分区工具；记录源码与工具链版本。`build-release.py` 的根盘重建、loader 封装、隐私检查通过，再在 Linux 或容器按体验说明完成合成校验。 | [开发指南 §10](../development.md#10-生成-release)、[发布脚本](../../tools/release/build-release.py) |
| ENG-02 | adreno8 与 ir3 的外部输入对照测试 | 2026-11-16 统一运行主机测试：mic、payload、mkpayload 等全部成功；13 个 `test-adreno8-*.py` 与 `test-ir3-output-contracts.py` 缺少外部输入时跳过，尚未在提供输入的环境中运行 | 按脚本里的版本与 SHA-256 准备 graphics-kernel 源码、`msm_kgsl.ko`、厂商内核时钟源码、MiCode 内核与上游 adreno 源码，设置环境变量后运行 `python3 tools/run-host-tests.py adreno8 ir3`；验收为这 14 项全部成功，或逐项记录失败位置并区分输入版本、源码断言与环境错误 | [合入前检查](../plan/debugging-and-collaboration.md#10-合入前检查)、[主机测试入口](../../tools/run-host-tests.py) |
| ENG-03 | AIR 参考编译的 LLVM 基线 | 候选验证未完成 | 固定可解析 opaque `ptr` 的参考工具链，重跑 FMA 与 argument-buffer 对照；单独定位仍拒绝的跨成员 phi。验收记录要区分参考编译器错误与 AIR 语义差异，再决定是否更新生产检查规则。 | [多媒体验证 §9](../analysis/2026-11-11-multimedia-validation.md#9-air-常规检查与缓存) |
| ENG-21 | Wi-Fi 下的 SSH 调试 | 11-23 tgl40 真机验证通过：`tools/mk-jb.sh` 现取 Procursus 1800 bootstrap（含 openssh-server 9.7p1）生成 `jb/root/var/jb`（127M，仓库外）；jb 前缀装进 `flashboot.apfs` 后 79MB 超过载荷 64MB 常驻启动镜像上限，验证改走运行期落盘——`oem push` + `annsh pull` 把 sshd、5 个 rpath 依赖、passwd/master.passwd/group、`pwd_mkdb`、zsh 等 10 件写入 `/var/jb`（ramfs），`mkdirtool`（无签名即可执行）建目录。设备 en0 得 `<DEVICE_IP>` 后 `/var/jb/usr/sbin/sshd` 后台常驻：宿主密钥认证登入成功、远端命令执行（`ps -A` 进程表）、交互 zsh（`localhost#` 提示符）、sftp 子系统双向传输、`kill` 后 22 端口关闭全部实测 | annsh 新增 `mkdir -p`/`chmod` 内建已提交；落地为持久路径需把 jb 装进 UFS 系统镜像（`/jb`）再刷机一次，或每次开机重复运行期落盘；zsh 缺模块（zle 行编辑）未推送；SSH 不能替代 loader 通道做恢复 | [SSH 真机验证记录](../progress/2026-11-23-ssh-over-wifi.md)、[USB 与调试方式核查 §4](../analysis/2026-11-12-usb-debugging.md#4-现有调试方式的可用范围) |
| ENG-24 | k90auto 的环境检查、恢复超时与日志质量 | 11-22 三轮遇到：解释器缺 NumPy 时 `tour.py` 报错而轮次照常进行；`tests/test-tools.py` 的 52 项里 43 项因 `run-auto.py` 导入 `screenrec` 而不通过；`recover-loader.py` 在 loader 重新枚举期间 8 秒超时退出；日志行成对重复、不同来源的行串在一行；`prof.py` 没有共享缓存偏移时符号归属错误；`annsh` 的 `sysctl` 不支持前缀。11-22 晚已处理：`test-tools.py` 复制 `screenrec.py` 后 52 项全部通过；`recover-loader.py` 在重新枚举期间继续等待；`cycle.py` 开头检查 numpy；`prof.py` 没有偏移时不再给共享缓存地址命名。剩余：日志成对重复（各驱动的输出同时写 loader 日志并 `printf`，控制台输出开启时 `printf` 也进 loader 日志）与 `annsh` 的 `sysctl` 前缀。11-23 晚：各驱动的 `say()`/`traceLine`/`ustacks_say` 统一改为互斥写法——`printf` 能跑时不再显式写 loader 日志（`console_write` 无条件 `loader_log_putc`），跑不了时用 `loader_log_line` 整行写；say3 内核真机 `kernel-12377-say3-tgl28` 相邻重复行 1308→82，内核驱动前缀全部归零，剩余重复消息含用户态输出和连续事件。11-24 在原始快照中找到全部带时间戳的相邻重复行，独立的 16 个控制台标记各出现一次，见[用户态输出复核](../progress/2026-11-23-log-dedup.md#5-用户态输出复核11-24)。11-23 晚收尾：`sysctl NAME` 为节点时按 `{0,3}`/`{0,2}`/`{0,1}` 原生 SPI 枚举整棵子树（userland `9146fd0`），tgl29 真机 `sysctl kern.annibale` 枚举成功、普通叶子与 `NAME=NUMBER` 写入不变 | 按[全局现状分析 §6](../analysis/2026-11-22-global-review.md#6-工具链)的表逐项处理；验收为新环境按说明一次跑通一轮、`test-tools.py` 全部通过、恢复脚本在重新枚举期间重试成功、合并后保留原始事件数，每条带序号的测试消息只出现一次 | [全局现状分析 §6](../analysis/2026-11-22-global-review.md#6-工具链) |
| ENG-25 | 宿主侧着色器回放 | 11-24 在 macOS 构建 air2nir、air_run 与顶点回放程序。g25capture1 取回图库两次绘制的特化顶点 AIR 及各自的 7 个输入缓冲区。llvmpipe 与 Mac Metal 逐像素比较，两个样本的覆盖差异均为 0/16,384 | 已验收 G25 顶点几何。图库纹理与混合效果见 G25 真机记录 | [构建与回放步骤](../../tools/k90auto/README.md#81-用-mac-回放图库的顶点着色器) |

## 2. Mesa、AIR 与代码维护

| 编号 | 事项 | 状态 | 下一步与验收条件 | 来源 |
|---|---|---|---|---|
| ENG-04 | Mesa 补丁按支持版本严格应用 | 待整理 | 为支持的基线保留各自补丁集合，清理 26.x 已失效的 hunk，刷新 `ir3-ssbo-subdword` 上下文；核对 25.0.7 消费者后处理 `ir3-shift-split`。从干净 tarball 应用时要求零 reject、零 skip、零 fuzz，并完成主机与 iOS 交叉构建。 | [Mesa 分析 §2](../analysis/mesa-rebase-2026-10.md#2-fork-补丁在-2625-上的应用结果)、[§8](../analysis/mesa-rebase-2026-10.md#8-剩余工作)、[mk-mesa.sh](../../hackios-xnu-userland/tools/mk-mesa.sh) |
| ENG-05 | OSMesa 恢复补丁与平台适配分开维护 | 待整理 | 将 OSMesa 恢复从 `0003` 的其他 26.x 适配中拆出，按职责整理 `freedreno-darwin.patch`。运行现有 GL、GLES smoke 程序，核对当前导出符号集合、上下文创建与像素读回；更换 Mesa 后复核 EAGL 消费路径。 | [Mesa 分析 §3](../analysis/mesa-rebase-2026-10.md#3-osmesa-恢复)、[§8](../analysis/mesa-rebase-2026-10.md#8-剩余工作)、[smoke-osmesa.c](../../hackios-xnu-userland/tools/mesa/rebase-26/smoke-osmesa.c)、[smoke-osmesa-es.c](../../hackios-xnu-userland/tools/mesa/rebase-26/smoke-osmesa-es.c) |
| ENG-06 | AIR 主文件与测试文件继续按职责拆分 | 部分拆分，剩余项见下表 | 在对应文件发生大改前，沿现有资源、翻译阶段和测试职责继续拆分；保留接口与资源生命周期约束，避免新增转发层。新文件和本次大改文件满足行数约定，相关宿主测试及 arm64e 构建通过。 | [架构审查 §7.2](../analysis/2026-11-08-architecture-review.md#72-air-翻译器的完整性)、[§16](../analysis/2026-11-08-architecture-review.md#16-工程流程)、[AGENTS.md §2](../../AGENTS.md#2-代码行数约定必须遵守) |
| ENG-07 | 剩余注入钩子逐项核对原生契约 | 待逐项评估 | 按实际消费者检查关机、激活状态、图标、AirDrop、显示名、WebKit 偏好和状态栏布局；记录原生调用要求与底层缺口，完成内核、驱动或构建层修复后移除对应钩子。每项验收覆盖原消费者与未注入进程；诊断和测试用途单独确认。 | [注入钩子 §2](../analysis/2026-11-09-injection-hooks.md#2-逐项归类)、[§3](../analysis/2026-11-09-injection-hooks.md#3-结论) |

ENG-06 的行数取自 2026-11-12 工作树。AIR 已有 `air_metal_*.inc`、指针槽、argument buffer、GEP、调用、phi 和采样器分片，后续拆分沿这些职责进行。

| userland 仓库文件 | 当前行数 |
|---|---:|
| `tools/mesa/air/air_metal.c` | 6782 |
| `tools/mesa/air/air_metal.h` | 1438 |
| `tools/mesa/air/air_metal_test.c` | 6931 |
| `tools/mesa/air/air_module.c` | 1950 |
| `tools/mesa/air/air_run.c` | 2093 |
| `tools/mesa/air/air_to_nir.c` | 3407 |
| `userland/src/tests/metal_drv_test.m` | 7799 |

## 3. 着色器覆盖与对照验证

| 编号 | 事项 | 状态 | 下一步与验收条件 | 来源 |
|---|---|---|---|---|
| ENG-08 | 23G90 着色器清单与最小 corpus | 部分模块已验证，完整清单待补 | 离线枚举 QuartzCore、CoreImage、UIKit 的目标 metallib，分别记录读取、AIR→NIR、A830 IR3 编译和 GPU 执行结果；为拒绝项提炼可公开的自编最小 shader。验收时每项失败都有具体模块、输入、阶段与复现命令。 | [架构审查 §7.2](../analysis/2026-11-08-architecture-review.md#72-air-翻译器的完整性)、[多媒体验证 §5](../analysis/2026-11-11-multimedia-validation.md#5-接手后的静态与宿主检查)、[corpus.py](../../hackios-xnu-userland/tools/air/corpus.py) |
| ENG-09 | 材质样本的原生 Metal 与 A830 像素对照 | 未开始 | 为玻璃、背景模糊、合成滤镜和 SDF 文本固定输入、附件格式、混合状态及 load/store；在 Mac 原生 Metal 与 `metal_drv_test.m` 执行相同描述。先确定各样本可解释的误差判据，再用像素结果验证格式替换与相关 Mesa 补丁。 | [架构审查 §8.2](../analysis/2026-11-08-architecture-review.md#82-建立材质着色器回归样本) |
| ENG-10 | Mesa 26 主机检查跳过的 A830 指令与执行语义 | 待设备验证 | 用实际 A830 配置复核 discard/demote、framebuffer fetch 和 vertex fetch；`discardcheck.py` 的默认 chip ID 需要按目标覆盖。记录实际指令与像素结果，汇总检查时单列 `SKIPPED`，不计作该阶段已通过。 | [Mesa 分析 §8](../analysis/mesa-rebase-2026-10.md#8-剩余工作)、[§10.2](../analysis/mesa-rebase-2026-10.md#102-discardcheckpy)、[§10.3](../analysis/mesa-rebase-2026-10.md#103-26x-没有离线-ir3-编译入口) |

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
| ENG-18 | 顶层仓库许可证 | 待用户选择 | 顶层当前没有 `LICENSE` 或 `COPYING`。先说明可选许可证对本项目脚本与文档的适用范围，由用户选定后添加许可证，并与子模块既有声明保持清楚的归属关系。 | [开源准备记录 §5](../analysis/2026-10-23-open-source-readiness.md#5-检查边界与后续维护) |
| ENG-19 | 后续 Release 的第三方内容分发核对 | 随发布内容复核 | 逐项核对预构建固件、设备提取资料与其他第三方文件的来源和分发许可；许可或来源未确认的内容使用本地提取流程。验收包含发布清单与 `build-release.py` review 输出中各文件的来源说明。 | [开源准备记录](../analysis/2026-10-23-open-source-readiness.md)、[开发指南 §10](../development.md#10-生成-release) |
