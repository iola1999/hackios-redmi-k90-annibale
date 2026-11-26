# AGENTS.md — hackios-redmi-k90-annibale 工作区约定

HackiOS（XNU + 未修改的 iOS 用户态，当前为 iOS 26.6.2）移植到 REDMI K90（SM8750，代号 `annibale`）的顶层工作区。代码在两个 submodule（`hackios-xnu-kernel/`、`hackios-xnu-userland/`，工作分支均为 `k90-port`），本仓库只放文档、脚本、配置。背景速览见 [README.md](README.md)，文档入口见 [docs/README.md](docs/README.md)，未完成事项与候选方向见[待办目录](docs/backlog/README.md)。

> **严厉禁令**：全工作区禁用内置 `grep` 工具，禁止在 shell 中执行目录级递归 `grep`，严禁对 `out/` 等大目录做任何递归内容检索；违规会直接耗尽主机内存并引发系统大面积查杀进程，细则见 [§8](#8-检索与大目录访问禁令必须遵守)。

## 1. 文档写作约定（必须遵守）

1. **禁止按字符宽度硬换行**。一个段落 = 一行物理行；一个列表项（含有序/无序/嵌套项）= 一行；引用块的一段 = 一行（`> ` 开头，段内不断行）。写新文档、改旧文档时都不要为了"行不太长"而中途折行。理由：硬换行会让 diff 噪音大、段落级修改互相冲突，且渲染前后行为不一致。
2. 唯一允许的行内换行手段是 Markdown 硬换行（行尾两个空格），且仅在确实需要视觉换行时使用。
3. 代码块（``` 围栏内）、表格行、标题行不受本节约束，保持原样。
4. 中英文混排连接处遵循原文风格：西文/数字/反引号片段与中文之间可留一个空格；中文与中文、中文与全角标点之间不加空格。
5. 存量文件若发现硬换行，用本仓库脚本批量修复，不要手工逐行改：`python3 tools/unwrap_md.py [--check] <file.md> ...`（`--check` 只出 diff 不写文件；脚本会保护代码块/表格/标题/列表结构，把续行合并进所属段落或列表项）。
6. 二级标题按每篇文档从上到下连续编号，格式为 `## 1. 标题`、`## 2. 标题`。增删或移动章节后检查编号，并同步修改受影响的页内链接。
7. 仓库文件引用使用项目相对路径；具体设备与备份参数按第 3 节通过环境变量或本地配置提供，可复用 Prompt 的来源会话由执行者填写。
8. **禁止巨型段落与堆砌长句**。一个段落只说一件事，控制在 3～5 句以内；正文单段超过约 500 字符即视为需要拆分。一段里有两个以上独立事实点（判据、时刻、哈希、计数、归属、待办）时，必须拆成列表、表格或子小节，一项一行。不要用逗号、分号、破折号把多个独立事实串成一个长句。理由：巨型单行段落无法扫读、无法定位、无法按点引用，diff 审阅也读不出改了什么。
9. **事实分层存放**。哈希链、mtime、grep 计数、命令原文这类取证细节写进所属小节或专门的实测数据小节，正文只留结论加指针（文档路径或提交哈希）。同一事实只在一份文档展开，其余位置引用，不重复抄写。
10. **过程记录即时清理**。已撤销的结论、已被取代的排期、已结案的待核，删除其过程叙述，只留一行结果与出处。「谁在何时说了什么、后来发现不对」这类日记式往来不入库；确有留存价值的教训提炼成规则写进对应手册，原始往来留在提交说明或不入库的本地记录里。
11. **文档按用途分类，不混装**。backlog 集中未完成事项、候选方向与验收条件，plan 放已选批次的执行安排、架构决策与常设规则，analysis 放结论与实测数据，progress 放一轮一事的记录。progress 文档不得膨胀成跨轮取证档案；跨轮共用的判据、身份规则与校验记录写进 analysis 或归档文档，progress 只留本轮结果与指针。
12. **入口与职责明确。** 全项目专题入口维护在 [docs/README.md](docs/README.md)，AGENTS.md 只保留工作约束与必读操作入口。工具用法放在工具旁的 README，跨仓流程放在顶层开发指南。
13. **区分现行说明与历史记录。** 操作手册引用当前脚本和参数来源，阶段分析注明适用版本、日期及验证范围。新结果更新当前专题和进度摘要，历史记录保留当轮事实并链接后续结果；可变默认值与源码哈希优先引用来源。
14. **新增与移动先核对现有用途。** 同主题内容优先更新已有文档，独立问题再新建并加入文档入口。移动文件或修改标题前，检查顶层及子模块中的链接、脚本和章节引用；导入的上游资料保留原格式与来源，生成文档通过对应脚本更新。
15. **提交前运行文档检查。** `python3 tools/check-docs.py` 只读检查顶层及两个代码子模块的跟踪 Markdown：检查 Markdown 内联链接、引用式链接的本地目标和锚点，以及从顶层 README 到各文档的可达性；顶层另检查二级标题编号、硬换行和长段落。支持范围见[文档入口](docs/README.md#11-放置与检查)。显式传入文件可检查新文档。事实、命令适用范围、隐私与变更归属仍需人工审阅；改动启动参数来源后另运行 `python3 tools/bootargs.py --check`。

## 2. 代码行数约定（必须遵守）

代码类文件（C/Python/Shell 等）单文件控制在 **1200 行以内**，做好合理拆分（按层/按职责拆文件，私有声明走 `*_private.h` 之类的内部头）。确实无法拆分的（如生成表、结构上不可分的单入口状态机），要在文件头写明理由，禁止为了控制行数强行将代码写在一行。存量超标文件不强制回溯，新文件与大改文件必须遵守；判定基准 = 新增的文件和本次改动后净增长的越线文件。

## 3. 隐私信息提交约束（必须遵守）

本约束适用于顶层仓库和两个代码子模块，包括代码、注释、文档、配置、测试样本、提交说明，以及仓库的 PR、Issue、Git LFS 和发布附件。

- 不得提交个人信息或可识别个人设备、环境的真实值，包括本机用户目录、项目目录、挂载盘和 NAS 位置等绝对路径，设备序列号、IMEI／IMSI／ICCID、Android ID、MAC 地址、实际内网地址、主机名、Wi-Fi 名称，以及私有会话标识、会话链接和未经授权公开的个人资料、联系方式、个人文件内容。
- 不得提交密码、API 密钥、访问令牌、私钥、Cookie、认证请求头、设备认证 token 或带凭据的 URL。示例使用明确的占位符；运行所需的真实值通过环境变量、设备参数或未跟踪的本地配置提供。
- 仓库文件引用使用项目相对路径；设备和备份位置使用 `ANDROID_SERIAL`、`BACKUP_DIR` 等参数。程序接口需要的固定系统路径、设备节点和容器路径可保留，内容中不得夹带本机个人目录。公开上游 URL、许可证与版权声明，以及用户已明确允许保留的 Git 提交署名和邮箱，按原有授权保留。
- 原始日志、截图、分区备份、内存转储、会话导出和历史备份保存在 Git 忽略的本地目录。需要提交的摘录或图片必须先脱敏，同时检查文件名、图片文字、EXIF／文本元数据、压缩包和二进制中的可读字符串。
- 提交前逐个检查本次涉及的仓库，审阅暂存差异、新增文件和提交说明；推送前检查本轮将推送的提交范围。检查结果只保留类别和位置，敏感原值留在本地。`.gitignore` 仅影响未跟踪文件，已跟踪文件及已有提交需要另行检查。
- 发现已有提交或发布内容泄露隐私信息后，先报告影响范围并停止继续发布相关内容，再按用户授权处理当前文件、历史提交和托管附件；清理后重新验证。历史改写与服务器旧提交的访问边界见[隐私检查记录](docs/analysis/2026-10-23-open-source-readiness.md)。

## 4. 提交频率约定（必须遵守）

本节约束顶层仓库和两个代码子模块，适用于实现、排查、验收和文档整理。提交必须对应有实质进展、可复核的阶段成果；同一阶段的代码、验证结果、文档和子模块指针一起提交。

- 阶段成果必须能说明完成了什么，以及验证结论或适用边界。例如完成一项功能或根因修复并通过对应检查、完成一批验收并形成明确结论、定稿一项架构决策或可执行的操作规范。独立的文档工作也必须达到这一标准。
- 禁止仅因补充几条进展、一次测试轮读数、状态摘要或待办更新就单独提交，禁止连续提交只有少量工作记录变更的文档。相关记录随对应实现或阶段结论合并提交。
- 同一问题的连续排查、实现和复测归为一个阶段。工作中可以持续更新工作树，原始日志和过渡记录保存在 Git 忽略的本地目录，阶段结束后整理必要结论入库。
- 文件数、记录条数、经过时间、一次会话或一轮测试结束，都不能单独作为提交理由。短时间内连续产生的同类小提交必须在推送前合并。
- 验证耗时较长（真机测试轮、容器构建）也必须遵守上述标准。已完成的实现若已形成可独立审阅和回退的阶段成果，可以先提交，并写清未验证范围；后续零散读数继续累积，形成验收结论后再提交。
- 量化下限：单次提交通常应包含五个以上文件的变更；不足五个文件时先累积到同一阶段的代码、文档与指针齐备再提。禁止只改一两份文档就提交，文档更新随对应实现与验收合并入库。提交信息按仓库历史风格：中文批次或主题开头的完整句，写清完成了什么与验证结论，不写逐文件清单。
- 提交信息不写工具署名、生成标记或协作署名行，只写改动内容与验证结论，风格对齐仓库已有历史提交。
- 两项成果各自完整、能独立审阅和回退，才分开提交。达到阶段完成条件后及时提交；提交说明写清实际改动、验证范围、阶段结论和剩余事项。

## 5. 真机无人值守约束（必须遵守）

无人值守指的是机器自己跑完整轮，不含设备进入需要人按键才能离开的状态。2026-10-29 出现过一次整天连续启动测试轮、loader 从 USB 消失几小时、只能靠长按电源键恢复的事故，以下约束据此确立。

- **启动测试轮前自动从当前状态收敛至驻留 loader。** 下一轮真机测试或更换启动载荷时直接由工具链从当前状态自动收敛到已枚举的 `xnuloader` 并刷入启动：设备处于运行中的 iOS 时先发 `oem stop` 等内核静默后执行 `reboot` 并发 `oem recovery` 锁定 Fastboot 空闲态（硬校验 `getvar result` 为 `idle`、`getvar product` 为 `xnuloader` 且常驻区为空），处于 B 槽 Android 时经 `recover-loader.py` 切回 A 槽 loader。软件恢复失败时记录现场并报告用户。
- **序列号为空视同未枚举。** `adb devices` 列出设备但序列号为空时，除轮询外不发任何命令。序列号必须能原样读出。
- **单轮测试完成后默认留在 iOS 运行态。** 相机、Safari、播放等测试复用同一次开机依次执行，单项完成后清理对应测试进程，整轮验收结束后设备默认保持在 iOS 桌面供观察与交互；更换启动载荷、开启下一轮测试或恢复需要重启的故障时再执行退出收尾（内核 DMA 停止、同步和资源保留要求继续生效，退回 loader 后须满足 `result: idle`、`product: xnuloader` 与常驻区为空三项硬校验）。
- **运行态稳定性巡检。** 留机前和留机期间检查三项：系统进程是否反复重启（日志里 `System shell connected` 之后紧跟 `No system apps remain. Waiting for one to spawn`，或 `ps` 里 SpringBoard、cameracaptured 的 pid 不断变化）；GPU 是否已停转（`submissions closed`、`AnnibaleGPU client refused`，停转后所有新 GPU 客户端都被拒绝）；整屏是否亮暗交替。`cycle.py` 留机前会检查前两项，发现即收尾退回 loader；手动留机或 `--hold` 轮次结束时先读 `render-report.txt` 的 restart 与 gpu 两段。
- **整屏闪烁紧急停。** 整屏亮暗交替闪烁按紧急状态处理：用一次 `oem screenshot` 和 `oem log` 取证，随即经 `recover-loader.py` 退回 loader 停闪，不让它持续。2026-11-18 `cam3-trace2` 轮在定位授权弹窗期间 GPU 停转，SpringBoard 随后反复崩溃重启，轮次结束仍留在 iOS，整屏闪烁持续到软件恢复，据此确立。
- **高耗能状态限时保持。** 相机传感器开启、屏幕高亮度、GPU 高档满载只在测试动作期间保持：单项完成即退出相机或对应应用，亮度回到常规档位；连续诊断轮之间让设备回到桌面待机，不在传感器开启或高亮度下长时间停留。
- **A 槽重试预算与 GPT GUID 相位。** `xnuloader` 启动时会自动维护自身槽位的重试计数与 `_a`／`_b` 分区 `PartitionTypeGUID` 相位；主机侧启动测试轮前仍需检查 `slot-retry-count:a`（低于 3 先 `set_active a`），切槽时确保 LUN 4 与 LUN 0 的活动槽位持有各自的 `PartitionTypeGUID`（非活动槽位为 `77036cd4-...`），防止触发高通 LK `ValidateSlotGuids` 校验失败。
- **连续诊断轮设上限。** 一个批次最多 3 轮，之后停下复盘：读完这一批的读数，改测法或换变量，再启动下一批，不等用户回复。上一批没拿到结论就先改测法，不靠加轮次堆读数。只有设备进入需要人按键的状态，或下一步需要用户授权时，才停下等指令。
- **一轮一个变量，探针合并。** 相关的观测点装进同一份库、同一轮取完；不允许一轮只回答一处小问题，也不允许同一轮换两个变量。
- **设备命令只由 device 成员执行。** lead 只做枚举与只读查询，其余角色不碰 `fastboot`／`adb`。对设备发命令一律带序列号。执行 `fastboot -s xnuloader oem "sh ..."` 时单条命令正文不得超过 119 字节（优先使用 `tools/k90auto/rsh.py`），严禁发送超过 511 字节的 Fastboot 命令以免触发 DWC3 `CompleteError` 导致 `usb_out_lost = 1` 端点隔离（见[USB 恢复与减少人工按键的调试经验 §6.6](docs/analysis/2026-10-25-usb-recovery-lessons.md#66-oem-sh-超长命令导致-usb_ep_out-端点永久隔离与五指退回问题)）。
- **设备离线时转入静态分析与盲写编译。** 设备不在手边或处于等待人工按键复位状态时，不空等设备：立即通过静态反汇编与反编译（工具入口见第 7 节）和源码分析完成根因修复、内核与用户态编译打包验证（`xnu26/build-macos.sh`、`userland/build.sh`、`tools/k90auto/package.py`）并提交推送，待设备恢复上线后集中执行真机复核。

## 6. 根因定位与原生对齐约定（必须遵守）

- **严禁表象绕过（Workaround）与硬编码掩盖。** 遇到功能异常、权限重复弹窗、UI 黑底／白框、图标空白、守护进程退出、主线程卡死或文件操作失败时，必须通过反汇编与反编译（`dsc.py` 与 `idalib-mcp` 入口见第 7 节）、内核／驱动源码与日志查明苹果 iOS 原生框架期望的底层契约（VFS 属性与 vnode 操作、IOKit 服务树与属性、BSD／Mach 系统调用语义、launchd 守护进程与 XPC 服务、系统 Bundle／字体／本地化资源、GPU 着色器 IR 与寄存器语义），在内核、驱动或构建层补齐对应底层能力。
- **明确禁止的做法。** 不得用方法交换（swizzling）强改 UI 视图背景色或伪造通知／权限授权返回值；不得在渲染管线编译失败时回退为固定纯色管线掩盖着色器错误；不得针对单个应用硬编码环境变量绕过通用容器目录初始化；不得用用户态定时轮询打包脚本代替内核块设备直写持久化。
- **存储、分区与设备节点对齐 iPhone 真机拓扑。** 双系统部署采用 UFS LUN 0 独立分区，见[双系统分区与持久化部署手册](docs/plan/dual-boot-setup.md)。
  - `darwin`（默认 16 GiB，`/dev/ufs_darwin`）承载只读 APFS 系统卷与 Cryptex，支持原版未裁剪 `os.dmg + systemos.dmg + appos.dmg` 或 `system26.apfs`。
  - `darwin_var`（`/dev/ufs_darwin_var`）为可写 APFS 容器并挂载其中的 Data 卷；旧版 `ANNFS001` 内核与 `init` 挂载路径已移除，早期安装需先经 `annfs-to-apfs.py` 迁移。
  - `darwin_nvram`（32 MiB，`/dev/ufs_darwin_nvram`）放 NVRAM bank 与 panic 日志：loader 读入 bank 交给 `IODTNVRAM`，内核经 `IONVRAMController` 写回，见[持久化 NVRAM](docs/analysis/2026-11-16-persistent-nvram.md)。
  - 内核 `IOKit` 拓扑为 `disk0 -> disk0s1 -> AppleAPFSContainer (disk1) -> AppleAPFSVolume (disk1s1 System / disk1s2 Data / disk1s3 Preboot)`；`devfs` 的 `/dev/disk*` 节点与 iPhone 真机保持一致。
  - `statfs` 的 `/` 对应 `/dev/disk1s1`、`/private/var` 对应 `/dev/disk1s2`，`f_fstypename` 统一报 `"apfs"`；总容量按 `darwin` 与 `darwin_var` 真实分区字节数之和计算（无 `darwin_var` 时回退 128 GB 十进制口径），扣除系统卷、Cryptex 与 `/private/var` 实际已用空间。
- **子 Agent 与团队成员模型选择。** 派发复杂排查、反汇编分析、内核／驱动编码或 Teamwork 成员任务时，指定使用高能力模型（`inherit`／Gemini 4 Argon 或 `pro`）。
- **主 Agent 过程与产物审查。** 派发子 Agent 或团队成员执行分析、实现、构建与真机测试后，主 Agent 必须在提交或采信结论前亲自审阅实际 `git diff`、构建树同步状态、编译日志与真机原始日志／截图，核查空壳伪实现、底层契约遗漏、锁与中断上下文错误、未提交改动混入打包，以及测试程序返回码为 0 但内核日志已报错等偏差，发现问题立即打回修正。

## 7. 其他

- **协作、进度与备份**：接手、排查、构建和真机操作前阅读 [项目排查与协作手册](docs/plan/debugging-and-collaboration.md)；旧文档与新结果有差异时核对源码、产物和实测时间，设备状态重新读取。项目状态集中维护在[进度表](docs/plan/2026-10-23-tracking.md)，待办在[待办目录](docs/backlog/README.md)，上游参考见[近期对照](docs/analysis/2026-11-12-upstream-review.md)，经验整理复用 [经验整理 Prompt](docs/plan/experience-review-prompt.md)。`annibale-backup/` 为分区备份说明，内容勿删，备份与恢复见[分区备份与恢复](docs/backup/README.md)。
- **构建、发版与引导镜像**：从源码构建与生成 Release 见[开发指南](docs/development.md)，发版按 [Release 执行清单](docs/plan/release-checklist.md) 执行并把新问题写回该清单，用户安装见[体验说明](docs/user-guide.md)。loader 与 UEFI 构建见 [annibale UEFI 与 loader 镜像构建](docs/analysis/annibale-uefi-build.md)，UEFI 源码在 [iola1999/hackios-mu-silicium](https://github.com/iola1999/hackios-mu-silicium) 的 `k90-port` 分支（克隆到 `hackios-xnu-kernel/Mu-Silicium/`）。
- **真机操作与故障恢复**：操作前后先看 `docs/plan/device-test-playbook.md` 的「故障定位与恢复」一节、[双系统分区与持久化部署手册](docs/plan/dual-boot-setup.md) 与 [引导目标切换 SOP](docs/plan/device-boot-target-sop.md)。`xnuloader` 槽位判据见 `hackios-xnu-kernel/xnuloader/slot_choice.h`；从 LK 用 `fastboot boot` 只能临时启动完整 loader 镜像，不能启动单独 handoff 载荷。硬件调试文件的读取也可能访问寄存器，操作前核对范围与恢复方式。
- **USB 异常与系统恢复**：USB 命令超时、内核停止或重启后身份变化，先看 [USB 恢复与减少人工按键的调试经验](docs/analysis/2026-10-25-usb-recovery-lessons.md)；判断无应答前检查 stdout、stderr 与实际耗时，同一设备命令串行执行，请求按键前先记录软件恢复失败结果并合并提示。Android 通知栏、手势条消失或 SystemUI 反复崩溃先看 [系统界面修复记录](docs/analysis/2026-10-23-android-systemui-recovery.md)；系统卷按需读取与启动卷职责见[根文件系统](docs/analysis/rootfs-strategy.md)。
- **反汇编与反编译入口**：查 iOS 26 `dyld_shared_cache` 框架反汇编与虚表槽位用 `hackios-xnu-kernel/tools/dsc/dsc.py`（用法与已知槽位见 [QuartzCore 静态分析](docs/analysis/2026-10-29-quartzcore-vtable-26.md)）；需要 Hex-Rays 伪代码、交叉引用或调用流分析时使用 `idalib-mcp`（先 `idb_list`／`idb_open` 打开目标二进制，再用 `decompile`、`analyze_function`、`xrefs_to`、`lookup_funcs`）。
- **内核构建与日志重定向约束**：XNU 26 内核构建（`hackios-xnu-kernel/xnu26/build-macos.sh`）通过 `RC_NONARCH_CFLAGS` 传入 `-Wno-reserved-identifier -Wno-reserved-macro-identifier` 屏蔽保留标识符告警；执行构建时必须将标准输出与标准错误全量重定向至磁盘日志文件（如 `bash xnu26/build-macos.sh > out/xnu26-build.log 2>&1`），防止未重定向输出倾入终端或工具管道造成缓冲区反压阻塞编译进程。
- **批次与本地产物清理**：每批调试、构建或发布结束后及时清理已不用的临时文件、重复镜像和中间产物，容器卷与独立发布目录同样适用。清理前核对脚本引用、符号链接、挂载和运行进程；保留当前调试输入、可复现基线、未结问题的崩溃报告与转储、分区备份，以及下次发布所需的源码、工具链和原始输入。用途无法确认的文件先保留；按实际占用核算清理结果，硬链接和稀疏文件单独核对。
  - 复制源码树、根目录和镜像时用 APFS 克隆（`cp -c`、`ditto --clone`）或硬链接；候选根目录只放本轮改动的文件，其余引用基线。
  - 轮次证据分两类处理。结论材料保留：`RESULTS.md`、`render-report.txt`、`manifest.json`、`commands.jsonl`、结果 JSON、崩溃报告、截图。原始串口流（`s###.log`、`device-*.log` 等快照序列）在轮次总结写完且批次提交后删除：一轮长测试的串口流可达数 GiB，是全工作区最大的积累来源；evidence 目录被 Git 忽略，有长期价值的内容必须摘录进跟踪的 Markdown，不依赖原始日志留存。
  - 一批工作提交后删除这一批的源码副本、构建目录（`BUILD/`、`build/`）和中间根目录，保留结果 JSON 与截图。清理由跑批的角色在批次收尾时执行，不推到事后。开新一批前先测量 `du -sh docs/progress/evidence out hackios-xnu-kernel/out`，合计超过 20 GiB 时先清理再开批。
  - 上机载荷（`handoff-*.bin`、`xnu*.bin`）只保留文档登记的基线和每条内核线最新一个；中间迭代随批次提交删除，需要时由对应源码与打包输入重建。
  - 截图 `.raw` 转出 `.png` 后即可删除；截图需要批量留存时把 png 转成 jpg（`sips -s format jpeg -s formatOptions 90`）再删原 png。
  - 超过 50 MB 的构建日志在这一批结束后用 `zstd -19 --rm` 压缩。
  - `/tmp` 下挂载的镜像用完即用 `diskutil eject` 卸载；镜像文件删除后，挂载期间仍占用磁盘空间。
  - 每次清理的删除、压缩和克隆清单记录在 `out/cleanup-<日期>/`。

## 8. 检索与大目录访问禁令（必须遵守）

- **全面禁用内置 `grep` 工具与目录级递归 `grep`**：严禁调用 IDE／Agent 内置 `grep` 或全文搜索工具；严禁在 shell 中执行 `grep -r`、`grep -R`、`grep -rl`、`grep -rn`、`egrep -r`、`fgrep -r` 等任何目录级递归检索命令。
- **严禁扫描大目录与产物目录**：严禁对 `out/`、`docs/progress/evidence/`、`docs/analysis/local/`、`hackios-xnu-kernel/out/`、`hackios-xnu-kernel/xnu-src/`、`hackios-xnu-kernel/BUILD/`、`hackios-xnu-userland/out/`、`hackios-xnu-userland/build/`、`annibale-backup/` 以及工作区根目录 `.` 执行任何递归内容检索或宽泛通配正则（如 `.`、`.*`、`^`、`\S`）。严禁以 `glob` 或 `find_file_by_name` 找不到被 `.gitignore` 忽略的文件为由改用 `grep` 扫目录。
- **唯一允许的检索与列举方式**：查已跟踪源码或文档只用 `git grep`（在目标仓库内指定具体子目录与字面关键词，例如 `git -C hackios-xnu-kernel grep -n '<关键词>' -- xnu/files/iokit/Kernel/`）或先用 `git ls-files` 取文件清单；查 `out/` 等未跟踪目录只用 `ls` 或 `find <已知子目录> -maxdepth 2` 按路径列举，禁止不限深度扫描。
- **单文件读取与大文件边界**：检索日志或文本必须点名具体文件路径，先确认单文件体积，再用 `rg -F --max-count`、Python 流式按行读取或 `sed`／`head`／`tail` 提取；对超过 50 MB 的二进制或镜像文件只用 `strings` 管道或流式 `bytes.find`，严禁把整文件读入内存。
- **子代理强制继承**：主 Agent 派发任何子代理或并行任务时，必须在任务说明中明确附带本节禁令，禁止子代理自行调用内置 `grep` 或递归扫描上述目录。
