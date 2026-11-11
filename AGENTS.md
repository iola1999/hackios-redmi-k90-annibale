# AGENTS.md — hackios-redmi-k90-annibale 工作区约定

HackiOS（XNU + 未修改的 iOS 用户态，当前为 iOS 26.6.2）移植到 REDMI K90（SM8750，代号 `annibale`）的顶层工作区。代码在两个 submodule（`hackios-xnu-kernel/`、`hackios-xnu-userland/`，工作分支均为 `k90-port`），本仓库只放文档、脚本、配置。背景速览见 [README.md](README.md)，文档入口见 [docs/README.md](docs/README.md)，未完成事项与候选方向见[待办目录](docs/backlog/README.md)。

## 1. 文档写作约定（必须遵守）

1. **禁止按字符宽度硬换行**。一个段落 = 一行物理行；一个列表项（含有序/无序/嵌套项）= 一行；引用块的一段 = 一行（`> ` 开头，段内不断行）。写新文档、改旧文档时都不要为了"行不太长"而中途折行。理由：硬换行会让 diff 噪音大、段落级修改互相冲突，且渲染前后行为不一致。
2. 唯一允许的行内换行手段是 Markdown 硬换行（行尾两个空格），且仅在确实需要视觉换行时使用。
3. 代码块（``` 围栏内）、表格行、标题行不受本节约束，保持原样。
4. 中英文混排连接处遵循原文风格：西文/数字/反引号片段与中文之间可留一个空格；中文与中文、中文与全角标点之间不加空格。
5. 存量文件若发现硬换行，用本仓库脚本批量修复，不要手工逐行改：`python3 tools/unwrap_md.py [--check] <file.md> ...`（`--check` 只出 diff 不写文件；脚本会保护代码块/表格/标题/列表结构，把续行合并进所属段落或列表项）。
6. 二级标题按每篇文档从上到下连续编号，格式为 `## 1. 标题`、`## 2. 标题`。增删或移动章节后检查编号，并同步修改受影响的页内链接。
7. 仓库文件引用使用项目相对路径；具体设备由 `ANDROID_SERIAL` 或脚本的设备参数选择，备份位置通过本地配置提供。可复用 Prompt 的来源会话由执行者填写。
8. **禁止巨型段落与堆砌长句**。一个段落只说一件事，控制在 3～5 句以内；正文单段超过约 500 字符即视为需要拆分。一段里有两个以上独立事实点（判据、时刻、哈希、计数、归属、待办）时，必须拆成列表、表格或子小节，一项一行。不要用逗号、分号、破折号把多个独立事实串成一个长句。理由：巨型单行段落无法扫读、无法定位、无法按点引用，diff 审阅也读不出改了什么。
9. **事实分层存放**。哈希链、mtime、grep 计数、命令原文这类取证细节写进所属小节或专门的实测数据小节，正文只留结论加指针（文档路径或提交哈希）。同一事实只在一份文档展开，其余位置引用，不重复抄写。
10. **过程记录即时清理**。已撤销的结论、已被取代的排期、已结案的待核，删除其过程叙述，只留一行结果与出处。「谁在何时说了什么、后来发现不对」这类日记式往来不入库；确有留存价值的教训提炼成规则写进对应手册，原始往来留在提交说明或不入库的本地记录里。
11. **文档按用途分类，不混装**。backlog 集中未完成事项、候选方向与验收条件，plan 放已选批次的执行安排、架构决策与常设规则，analysis 放结论与实测数据，progress 放一轮一事的记录。progress 文档不得膨胀成跨轮取证档案；跨轮共用的判据、身份规则与校验记录写进 analysis 或归档文档，progress 只留本轮结果与指针。

## 2. 代码行数约定（必须遵守）

代码类文件（C/Python/Shell 等）单文件控制在 **1200 行以内**，做好合理拆分（按层/按职责拆文件，私有声明走 `*_private.h` 之类的内部头）。确实无法拆分的（如生成表、结构上不可分的单入口状态机），要在文件头写明理由，禁止为了控制行数强行将代码写在一行。存量超标文件不强制回溯，新文件与大改文件必须遵守；判定基准 = 新落地的文件和本次改动后净增长的越线文件。

## 3. 隐私信息提交约束（必须遵守）

本约束适用于顶层仓库和两个代码子模块，包括代码、注释、文档、配置、测试样本、提交说明，以及仓库的 PR、Issue、Git LFS 和发布附件。

- 不得提交个人信息或可识别个人设备、环境的真实值，包括本机用户目录、项目目录、挂载盘和 NAS 位置等绝对路径，设备序列号、IMEI／IMSI／ICCID、Android ID、MAC 地址、实际内网地址、主机名、Wi-Fi 名称，以及私有会话标识、会话链接和未经授权公开的个人资料、联系方式、个人文件内容。
- 不得提交密码、API 密钥、访问令牌、私钥、Cookie、认证请求头、设备认证 token 或带凭据的 URL。示例使用明确的占位符；运行所需的真实值通过环境变量、设备参数或未跟踪的本地配置提供。
- 仓库文件引用使用项目相对路径；设备和备份位置使用 `ANDROID_SERIAL`、`BACKUP_DIR` 等参数。程序接口需要的固定系统路径、设备节点和容器路径可保留，内容中不得夹带本机个人目录。公开上游 URL、许可证与版权声明，以及用户已明确允许保留的 Git 提交署名和邮箱，按原有授权保留。
- 原始日志、截图、分区备份、内存转储、会话导出和历史备份保存在 Git 忽略的本地目录。需要提交的摘录或图片必须先脱敏，同时检查文件名、图片文字、EXIF／文本元数据、压缩包和二进制中的可读字符串。
- 提交前逐个检查本次涉及的仓库，审阅暂存差异、新增文件和提交说明；推送前检查本轮将推送的提交范围。检查结果只保留类别和位置，敏感原值留在本地。`.gitignore` 仅影响未跟踪文件，已跟踪文件及已有提交需要另行检查。
- 发现已有提交或发布内容泄露隐私信息后，先报告影响范围并停止继续发布相关内容，再按用户授权处理当前文件、历史提交和托管附件；清理后重新验证。历史改写与服务器旧提交的访问边界见[隐私检查记录](docs/analysis/2026-10-23-open-source-readiness.md)。

## 4. 提交频率约定（必须遵守）

提交单位是一段一起完成的工作：同一次工作里定稿的几份文档、落地的一处修复和它的验证，合成一笔提交，即使跨多个文件或多个待办项。只有两段工作在不同时间完成、彼此能独立回退时才分开提交。本节约束顶层仓库和两个代码子模块。

- 短时间内连续修改同类内容时合并为一笔提交，不要每改一个文件就提交一次；一批工作做完及时提交，不要长期积压几十个文件的未提交改动。
- 相邻几分钟里连续产出多笔，说明拆得过细；文件数与条目数都不作依据，判断标准是这批改动是否属于同一次工作。
- 验证耗时较长（真机跑轮、容器构建）时，先提交已定稿的部分，验证结果随这一批的收尾一起提交。
- 提交说明写清这一批做了什么、验证到什么程度，阶段结论直接写进提交说明。

## 5. 真机无人值守约束（必须遵守）

无人值守指的是机器自己跑完整轮，不含设备进入需要人按键才能离开的状态。2026-10-29 出现过一次整天连续起轮、loader 从 USB 消失几小时、只能靠长按电源键恢复的事故，以下约束据此写死。

- **起轮前自动收敛至驻留 loader。** 起轮前由工具链将设备收敛到已枚举的 `xnuloader` 且 `getvar result` 为 `idle`、启动卷常驻区为空：运行态先发 `oem stop` 等内核静默后执行 `reboot` 并发 `oem recovery` 锁定独立双启动 loader 的 Fastboot 模式，B 槽 Android 经 `recover-loader.py` 切回 A 槽 loader。软件恢复失败时记录现场并报告用户。
- **序列号为空视同未枚举。** `adb devices` 列出设备但序列号为空时，除轮询外不发任何命令。序列号必须能原样读出。
- **每轮收尾硬校验。** `getvar result` 必须是 `idle`、`getvar product` 必须是 `xnuloader` 且常驻区为空；复位重枚举后立即发 `oem recovery` 锁定 Fastboot 空闲态。任一项不满足，队列停下报用户。
- **A 槽重试预算与 GPT GUID 相位。** `xnuloader` 启动时会自动维护自身槽位的重试计数与 `_a`／`_b` 分区 `PartitionTypeGUID` 相位；主机侧起轮前仍需检查 `slot-retry-count:a`（低于 3 先 `set_active a`），切槽时确保 LUN 4 与 LUN 0 的活动槽位持有各自的 `PartitionTypeGUID`（非活动槽位为 `77036cd4-...`），防止触发高通 LK `ValidateSlotGuids` 校验失败。
- **连续诊断轮设上限。** 一个批次最多 3 轮，之后停下复盘：读完这一批的读数，改测法或换变量，再起下一批，不等用户回复。上一批没拿到结论就先改测法，不靠加轮次堆读数。只有设备进入需要人按键的状态，或下一步需要用户授权时，才停下等指令。
- **一轮一个变量，探针合并。** 相关的观测点装进同一份库、同一轮取完；不允许一轮只回答一处小问题，也不允许同一轮换两个变量。
- **设备命令只由 device 成员执行。** lead 只做枚举与只读查询，其余角色不碰 `fastboot`／`adb`。对设备发命令一律带序列号。执行 `fastboot -s xnuloader oem "sh ..."` 时单条命令正文不得超过 119 字节（优先使用 `tools/k90auto/rsh.py`），严禁发送超过 511 字节的 Fastboot 命令以免触发 DWC3 `CompleteError` 导致 `usb_out_lost = 1` 端点隔离（见[USB 恢复与减少人工按键的调试经验 §6.6](docs/analysis/2026-10-25-usb-recovery-lessons.md#66-oem-sh-超长命令导致-usb_ep_out-端点永久隔离与五指退回黑盒陷阱)）。
- **设备离线时转入静态分析与盲写编译。** 设备不在手边或处于等待人工按键复位状态时，不空等设备：立即通过静态反汇编与反编译（`hackios-xnu-kernel/tools/dsc/dsc.py` 或按需使用 `idalib-mcp` 的 `idb_open`／`decompile`／`analyze_function`）和源码分析完成根因修复、内核与用户态编译打包验证（`xnu26/build-macos.sh`、`userland/build.sh`、`tools/k90auto/package.py`）并提交推送，待设备恢复上线后集中执行真机复核。

## 6. 根因定位与原生对齐约定（必须遵守）

- **严禁表象绕过（Workaround）与硬编码掩盖。** 遇到功能异常、权限重复弹窗、UI 黑底／白框、图标空白、守护进程退出、主线程卡死或文件操作失败时，必须通过反汇编与反编译（`hackios-xnu-kernel/tools/dsc/dsc.py` 或按需调用 `idalib-mcp` 做伪代码反编译、交叉引用与调用流分析）、内核／驱动源码与日志查明苹果 iOS 原生框架期望的底层契约（VFS 属性与 vnode 操作、IOKit 服务树与属性、BSD／Mach 系统调用语义、launchd 守护进程与 XPC 服务、系统 Bundle／字体／本地化资源、GPU 着色器 IR 与寄存器语义），在内核、驱动或构建层补齐对应底层能力。
- **明确禁止的做法。** 不得用方法交换（swizzling）强改 UI 视图背景色或伪造通知／权限授权返回值；不得在渲染管线编译失败时回退为固定纯色管线掩盖着色器错误；不得针对单个应用硬编码环境变量绕过通用容器目录初始化；不得用用户态定时轮询打包脚本代替内核块设备直写持久化。
- **存储、分区与设备节点对齐 iPhone 真机拓扑。** 双系统部署采用 UFS LUN 0 独立分区（[双系统分区与持久化部署手册](docs/plan/dual-boot-setup.md)）：`darwin`（默认 16 GiB，`/dev/ufs_darwin`）承载只读 APFS 系统卷与 Cryptex（支持原版未裁剪 `os.dmg + systemos.dmg + appos.dmg` 或 `system26.apfs`），`darwin_var`（`/dev/ufs_darwin_var`）由内核直写块持久化层（`ANNFS001`，`ramfs_disk.inc`）直接读写物理块并以双 32 MiB 乒乓元数据槽位实时落盘。内核 `IOKit`（`disk0 -> disk0s1 -> AppleAPFSContainer (disk1) -> AppleAPFSVolume (disk1s1 System / disk1s2 Data / disk1s3 Preboot)`）、`devfs`（`/dev/disk*`）与 `statfs`（`/` 对应 `/dev/disk1s1`、`/private/var` 对应 `/dev/disk1s2`，`f_fstypename` 统一报 `"apfs"`，总容量按 128 GB 容器十进制口径计算并扣除系统卷、Cryptex 与 `/private/var` 实际已用空间）与 iPhone 真机保持一致。
- **子 Agent 与团队成员模型选择。** 派发复杂排查、反汇编分析、内核／驱动编码或 Teamwork 成员任务时，指定使用高能力模型（`inherit`／Gemini 4 Argon 或 `pro`）。

## 7. 其他

- 未完成事项集中写[待办目录](docs/backlog/README.md)，已选批次的安排与常设手册写 `docs/plan/`，调研／实测数据写 `docs/analysis/`，过程记录写 `docs/progress/`（按日期命名）。原分析与实测保留，来源文档链接到对应待办主题。
- `annibale-backup/` 是分区备份数据说明，内容勿删。备份与恢复方法见[分区备份与恢复](docs/backup/README.md)。
- 真机操作前后先看 `docs/plan/device-test-playbook.md` 的「故障定位与恢复」一节和[引导目标切换 SOP](docs/plan/device-boot-target-sop.md) 的陷阱。
- 从源码构建与出 Release 见[开发指南](docs/development.md)；Release 用户的合成与安装步骤见[体验说明](docs/user-guide.md)，入口 README 只放进展与入口链接。
- 双系统分区规划、在线缩容、写入系统盘、刷入双启动 `xnuloader`、Android／iOS 切换及 Android 系统内 OTA 影响见[双系统分区与持久化部署手册](docs/plan/dual-boot-setup.md)。引导目标切换细节见[引导目标切换 SOP](docs/plan/device-boot-target-sop.md)：`xnuloader` 启动时按 `boot_a`／`boot_b` 里的镜像识别自身槽位（`loader_slot`）与另一侧 Android 槽位（`android_slot`，判据见 `hackios-xnu-kernel/xnuloader/slot_choice.h`），只有一侧是 loader 镜像时才维护或切换槽位，切槽时同步交换 LUN 4 与 LUN 0 上 `_a`／`_b` 分区的 `PartitionTypeGUID`；从 LK 用 `fastboot boot` 启动完整的 loader 镜像可以临时进 loader，单独的 handoff 载荷不行；枚举只用 `fastboot devices`，不要对未枚举的序列号发命令。
- loader 镜像与其中 UEFI 的构建见 [annibale UEFI 与 loader 镜像构建](docs/analysis/annibale-uefi-build.md)，UEFI 源码在 [iola1999/hackios-mu-silicium](https://github.com/iola1999/hackios-mu-silicium) 的 `k90-port` 分支，克隆到 `hackios-xnu-kernel/Mu-Silicium/`。
- USB 命令超时、内核停止或重启后身份变化，先看[USB 恢复与减少人工按键的调试经验](docs/analysis/2026-10-25-usb-recovery-lessons.md)。判断无应答前检查 stdout、stderr 与实际耗时，区分驻留 loader、LK 与 Android；请求按键前记录当前轮软件恢复失败的结果，同一待用户动作合并提示。同一设备的命令串行执行，异常后的资源保留规则继续遵守。
- Android 通知栏、手势条消失或 SystemUI 反复崩溃时，先看 [系统界面修复记录](docs/analysis/2026-10-23-android-systemui-recovery.md)。该文档也记录早期 userdata 尾部暂存的风险、备份边界和 loader USB 日志读取方法；系统卷从 UFS `darwin` 按需读取，启动卷和辅助盘的职责、当前验证范围见[根文件系统](docs/analysis/rootfs-strategy.md)。设备上的实际启动路径需结合 loader、载荷和切根日志确认。
- 接手、排查、构建和真机操作前阅读 [项目排查与协作手册](docs/plan/debugging-and-collaboration.md)，按其中的前提、操作、成功条件和失败处理执行。旧文档与新结果有差异时核对源码、产物和实测时间，设备当前状态重新读取。
- 硬件资料：设备树资源见[硬件资源图谱](docs/analysis/annibale-hw-map.md)；触摸报告模式、TLMM 地址、BQ 电量、充电状态与 CPU 拓扑见[桌面交互案例](docs/analysis/2026-10-24-interactive-runtime.md)。硬件调试文件的读取也可能访问寄存器，操作前核对范围及恢复方式。
- GPU：A830 的启动阶段、成功判据与关键修复见[A830 命令执行](docs/analysis/2026-10-24-a830-command-startup.md)，GPU 桌面、LPAC 路由与 Mesa CCHE 失效见 [GPU 桌面记录](docs/progress/2026-10-26-gpu-desktop-acceleration.md)。
- iOS 26 桌面：解锁、着色器编译与 GPU 挂起的修复见[可用桌面记录](docs/progress/2026-10-30-ios26-usable-desktop.md)；开机次序与处理器占用见[开机次序与性能](docs/progress/2026-10-31-boot-order-and-performance.md)；近期开机后视觉、亮度、通知权限、Wi-Fi、充电、关机与持久化问题见[11-06 问题与跟进清单](docs/plan/2026-11-06-issues-and-followup.md)。
- 帧率与 120 Hz：手势帧率的卡点见 [120 Hz 手势瓶颈](docs/analysis/2026-11-01-120hz-gesture-bottleneck.md) 与 [GPU 升频之后的长帧](docs/analysis/2026-11-02-120hz-after-gpu-clock.md)。
- 反汇编与反编译分析：查 iOS 26 `dyld_shared_cache` 框架反汇编与虚表槽位用 `hackios-xnu-kernel/tools/dsc/dsc.py`（用法与已知槽位见 [QuartzCore 静态分析](docs/analysis/2026-10-29-quartzcore-vtable-26.md)）；需要查看 Hex-Rays 伪代码、函数级数据流或分析系统守护进程（如 `wifid`、`lsd`、`backboardd`、`coreaudiod`）、`dyld_shared_cache` 分片、引导程序（如 `LinuxLoader.efi`）与固件模块时，按需使用 `idalib-mcp`（先 `idb_list`／`idb_open` 打开目标二进制，再用 `decompile`、`analyze_function`、`xrefs_to`、`lookup_funcs` 做反编译分析）。
- 经验文档优先记录排查方法、底层原理、判断依据和验收边界；已由代码或工具链解决的问题简短提及，具体命令集中在当前操作手册。
- 从会话整理经验的可复用指令见 [经验整理 Prompt](docs/plan/experience-review-prompt.md)，整理方式调整后同步更新该文档。
- 原始日志、截图、转储和本轮产物清单保存在 `.gitignore` 覆盖的本地调试目录，文字结论与必要的日志摘录写进 Markdown；提交前检查父仓库及各子模块的变更归属。
- 项目状态与已完成里程碑集中在[进度表](docs/plan/2026-10-23-tracking.md)，选任务与未完成事项集中在[待办目录](docs/backlog/README.md)。进度表保持简练，待办按主题记录下一步与验收，技术分析和实测只在专题文档展开。上游参考见[近期对照](docs/analysis/2026-11-12-upstream-review.md)。
- **禁止一切目录递归的 shell 检索。** 仓库内不用 `grep -r`／`grep -R`／`rg` 对目录做检索，`docs/`、`out/`、`.git` 与任何含二进制的目录都在禁止范围内。做法只有三种：用检索工具（它按文件读、结果有界）；指名具体文件（`grep -n <模式> <文件>`，一次一个或几个明确文件）；需要跨文件时先 `git ls-files` 拿到白名单再逐文件读，或用 python 逐文件扫描。理由：`docs/progress/evidence/` 有 65 GB，单个文件可达数百 MB 且几乎没有换行，递归一次就能把整份文件当一行读进内存。`| head -N` 不构成保护：匹配数不足时 grep 拿不到 SIGPIPE。
