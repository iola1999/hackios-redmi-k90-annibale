# iOS 26 QuartzCore 静态分析：窗口服务器虚表、槽位与刷新周期（2026-10-29）

本文用 `hackios-xnu-kernel/tools/dsc/` 解析 iOS 26（23G90，`iPhone18,3`）的 dyld 共享缓存，给 [`inject.c`](../../hackios-xnu-userland/userland/src/inject/inject.c) 里的虚表常量找 iOS 26 的对应值，并读 `CA_HEARTBEAT_RATE` 所在的函数。结论都来自缓存文件与静态反汇编，没有真机验证。

后续虚表核查见[图形与显示待办](../backlog/graphics.md)。

槽位一律写成「vtable + 0x10 + offset」里的 offset，与 `inject.c` 的 `VSLOT` 一致。

## 1. 结论

| 项 | iOS 16.5 | iOS 26 | 类型 |
|---|---|---|---|
| `AppleCLCDDisplay` 虚表 | `0x1d5b44520`（246 槽） | `0x1ee97f868`（320 槽） | 实测 |
| `is_ready` | 0xb0 → `0x1882f0908` | 0xe0 → `0x183f4fdfc` | 推断 |
| `ignore_update_p` | 0x138 → `0x1882e0c90` | 0x150 → `0x183efe30c` | 实测 |
| `begin_update` | 0x170 → `0x1882ddda4` | 0x198 → `0x183efb4d4` | 实测 |
| `finish_update` | 0x178 → `0x1882c8568` | 0x1a0 → `0x183f5631c` | 实测 |
| `CA_HEARTBEAT_RATE` 所在函数 | 0x2d8 → `0x1882d3930` | 0x318 → `0x183f380d8` | 实测 |
| `EAGLServer` 虚表 | `0x1d5b45c58`（62 槽） | `0x1ee982228`（75 槽） | 推断 |
| `renderer` | 0x1a0 → `0x1882e2548` | 0x1b0 → `0x183f37dc0` | 推断 |
| `render_update` | 0x178 → `0x18835770c` | 0x1d8 → `0x183f4a8ac` | 推断 |
| `GLESContext` 虚表 | `0x1d5b3b540`（138 槽） | `0x1ee982ab0`（164 槽） | 推断 |
| 心跳默认周期 | `0x188553b60` = 1/60 秒 | `0x184242688` = 1/60 秒 | 实测 |

「实测」指直接读缓存文件得到、可以重算的值。「推断」指地址与槽值同样可以重算，但类归属或函数对应关系靠构造函数与函数体比对得出，没有运行期验证。

- 26 的槽 0x138 存 `0x184072d88`，函数体只有 `mov w8,#0x7377; ldrb w0,[x0,x8]; ret`，读 `this+0x7377` 的一个字节，与 `ignore_update_p` 无关。
- `inject.c` 仍用 16.5 的常量。在 26 上 `replace_virtual` 读到的槽值与期望值不同，打印 `found …, expected …; left alone`，不装钩子。
- 26 的虚函数顺序相对 16.5 大范围重排，槽位不能按序号换算。例如带 `powering on display and entering flipbook` 字符串的虚函数从 0x108 移到 0x8d8；`EAGLServer` 的 `renderer` 与 `render_update` 在表内的先后顺序反了过来。

## 2. 工具

`hackios-xnu-kernel/tools/dsc/` 直接读拆分的共享缓存文件，不加载缓存。入口是 `dsc.py`，按职责拆成 `cache.py`（缓存与指针解码）、`macho.py`（Mach-O 解析、提取与导出表）、`disasm.py`（反汇编、引用与虚拟调用扫描，依赖 Python 的 capstone）和 `vtables.py`（虚表候选与槽匹配）。缓存格式、指针规则和提取的布局规则写在 `cache.py` 与 `macho.py` 的文件头说明里，参数写在 `dsc.py` 的文件头说明里，示例见 §9。

缓存目录用 `--cache` 指定。不给时先找当前目录下的 `hackios-xnu-kernel/ios26/23G90__iPhone18,3`，再找工具所在 `hackios-xnu-kernel` 目录下的 `ios26/23G90__iPhone18,3`。26 的缓存由 `hackios-xnu-kernel/ios26/fetch.sh` 从 IPSW 取出（85 个文件，4.9 GB）；16.5 的缓存在 `hackios-xnu-kernel/ios165/20F66__iPhone10,3_6/`（43 个文件，arm64）。

| 子命令 | 作用 |
|---|---|
| `info`、`images`、`image` | 头字段与镜像数；镜像地址与路径；一个镜像的段表与节表 |
| `map ADDR ...` | 地址落在哪个子缓存、文件偏移、镜像、段与节 |
| `read`、`disasm` | 十六进制与反汇编，反汇编解析 adrp 页面并标注目标 |
| `vtscan NAME` | 在 `__const` 里找虚表候选（§4） |
| `slots ADDR [--strings]` | 解码虚表槽，可附上槽函数引用的字符串 |
| `vtmatch` | 两个构建的虚表按槽内字符串匹配 |
| `vcalls NAME --offset OFF` | 按槽偏移找虚拟调用点，认 arm64 的 `ldr+blr` 和 arm64e 的 `autda+add+blraa` |
| `refs`、`findstr`、`exports` | 直接 `bl` 与 adrp 数据引用；字符串地址；导出 trie |
| `extract NAME -o PATH` | 抽成独立 Mach-O |

idalib 打不开主缓存文件，`/usr/bin/dyld_info` 对主缓存报 `file not found`，IDA、`otool`、`llvm-objdump`、`nm` 都用 `extract` 的输出。输出只供静态分析：数据段里的指针保持缓存编码，IDA 不还原，代码段不受影响；IDA 的 `imagebase` 等于缓存里的镜像基址（26 为 `0x183ed3000`），地址不用换算。

## 3. 缓存格式与指针解码

- 两份缓存的头同构，共享区都从 `0x180000000` 起。uuid：26 为 `46e741b70e753f19a3080464f4140b00`，16.5 为 `e5420db330d033aa8b7e05b5038bb46d`。images 表 26 有 4315 条、16.5 有 2710 条；合并所有子缓存的 mapping 表后 26 有 106 个 mapping、16.5 有 51 个，地址换文件偏移只靠这张表。
- 16.5 的指针：低 36 位是绝对地址，第 36～43 位带非零标记（见过 0x20、0x80），解码时掩掉，例如 `0x201882e0c90` 解出 `0x1882e0c90`。
- 26 的指针：bit 63 为 1 是带认证的 rebase，目标等于共享区起点加低 32 位；bit 63 为 0 时目标等于共享区起点加低 36 位。这条规则用 `__objc_classlist` 的两项交叉验证过。
- 缓存没有本地符号（`localSymbolsOffset` 与 `localSymbolsSize` 都是 0），导出表只有 C 符号，C++ 类名与 RTTI 字符串搜不到（`AppleCLCDDisplay` 0 次命中）。虚表属于哪个类只能靠构造函数判断。

## 4. 定位虚表的方法

1. 扫描：`vtscan` 在镜像的 `__const` 里找「16 字节零（offset-to-top 与 typeinfo）+ 连续指向本镜像 `__TEXT` 的已解码指针」，`--min-slots` 默认 3。26 的 `__AUTH_CONST.__const` 有 308 个候选，需要按结构再筛。
2. 成组排列：显示类在两个版本里都是四张依次排列、大部分槽共用实现的虚表，最后一张是 `AppleCLCDDisplay`。16.5 是 `0x1d5b35c60`、`0x1d5b37820`、`0x1d5b43d00`、`0x1d5b44520`（各 246 槽）；26 是 `__AUTH_CONST.__const` 开头的 `0x1ee97d9b8`、`0x1ee97e408`、`0x1ee97ee58`、`0x1ee97f868`（各 320 槽，0xa10 字节）。
3. 构造函数：找把「vtable + 0x10」写进 `[x0]` 的工厂函数，比较分配大小、构造参数与尾部字段。`AppleCLCDDisplay` 的工厂在 16.5 是 `0x1883a634c`（分配 0xb20 字节，清零 `[x0+0xb18]`），在 26 是 `0x184075600`（分配 0x7530 字节，清零 `[x0+0x7528]`），构造的第 3、4 个参数都是 0；同组另外两个工厂也一一对应。
4. 唯一字符串或常量：`vtmatch` 按槽函数引用的字符串匹配两个版本的虚表，`findstr`、`refs` 找只出现一次的常量。`AppleCLCDDisplay` 与 `EAGLServer` 都只匹配到一处字符串，这个办法只适合带日志字符串的类。
5. 自检：先在 16.5 上按同一流程读 `inject.c` 的四个 `AppleCLCDDisplay` 槽，读出的值与 `inject.c` 的期望值逐个相同，地址换算、指针解码和「vtable + 0x10 + offset」的约定由此确认。

## 5. AppleCLCDDisplay 的槽

26 虚表 `0x1ee97f868` 的头两个字都是 0。磁盘上的槽存的是 chained 编码，运行期读到的是解码后的地址：

| 槽 | 原始字 | 解码地址 | 函数 |
|---|---|---|---|
| 0xe0 | `0x8016980403f4fdfc` | `0x183f4fdfc` | `is_ready` 的等价逻辑 |
| 0x138 | `0x80156cac04072d88` | `0x184072d88` | 读 `this+0x7377` 的字节 |
| 0x150 | `0x8014b59003efe30c` | `0x183efe30c` | `ignore_update_p` |
| 0x198 | `0x8017679803efb4d4` | `0x183efb4d4` | `begin_update` |
| 0x1a0 | `0x80177d9c03f5631c` | `0x183f5631c` | `finish_update` |

这几个函数在 26 的四张显示类虚表里都落在同一个 offset，与 16.5 的情况一致。各函数的对应依据：

- `ignore_update_p`：保留 16.5 的结构，字段偏移变了。先读 `this+0x293`（16.5 为 `+0x233`）的第 4 位决定是否早退，再读 update 对象 `+0x130`（16.5 为 `+0xf0`）的 0xa 位，写回 `this+0x7368`（16.5 为 `+0x9f2`），返回取反后的布尔值。
- `begin_update`：两边都有立即数 `0x3f80000000000000`（16.5 在 `0x1882ddea4`，26 在 `0x183efb5c0`）。
- `finish_update`：开场都是 `stp d15,d14,[sp,#-0xa0]!`，栈帧 16.5 为 0x720、26 为 0x7a0。
- `is_ready`：两个版本全镜像都只有一条 `mov w2, #-0x7ffffffd`（等待调用的参数 0x80000003），分别在 16.5 的 `is_ready` 与 26 的 `0x183f4fdfc` 里，控制流逐段对应（下表）。26 的函数还打印 `Display::complete_powering_on`，`is_ready` 的判定在 26 上合进了电源完成函数。镜像内没有对 0xe0 的虚拟调用，也没有直接调用者。

| 步骤 | 16.5 `0x1882f0908` | 26 `0x183f4fdfc` |
|---|---|---|
| 守卫 | 标志字 `[this+0x9f2]` 的 bit 3 为 1 | 状态对象 `[this+0x300]` 的 byte+5 为 1 |
| 等待 | 参数 `[this+0x318]`、0、0x80000003 | 参数 `this+0x6460`、0、0x80000003 |
| 等待成功后 | 清 bit 3，加锁调用 (this, 0)，解锁 | 置 byte+4，加锁调用 (this, 0)，解锁 |
| 返回 | bit 2 为 0 时返回 1 | byte+4 非零返回 1，否则返回 byte+5 != 0 |

在 26 上改 `inject.c` 的这组钩子时：

- 同一缓存里虚表与函数共享同一个 slide，启动期可以用差值断言：「槽值减静态函数地址」等于「运行期虚表地址减静态虚表地址」，并要求头两个字为 0。断言失败时按 `replace_virtual` 现有的做法整组跳过并打印原因。
- 四张虚表指向同一批函数，改一张只影响从这张表发出的调用，需要先确认 `CAWindowServer` 实际创建的是哪个类。
- `is_ready` 真机确认前不上钩。

## 6. EAGLServer 与 GLESContext

`EAGLServer`：26 的虚表 `0x1ee982228`（75 槽），基类 `0x1ee98e008`（70 槽）；16.5 是 `0x1d5b45c58`（62 槽）与 `0x1d5b35a88`（57 槽）。对应依据：

- 工厂函数（16.5 `0x1883d1544`，26 `0x1840a1124`）都先调用基类构造并写入基类虚表，末尾把主表 + 0x10 写进 `[this]`，把紧跟主表的第二张表 + 0x10 写进 `[this+0x310]`（26 为 `[this+0x5c0]`），随后读环境变量 `CA_ENABLE_OGL`。
- `render_update`（26 `0x183f4a8ac`）的开头与 16.5 的 `0x18835770c` 逐条对应，两边都引用 `com.apple.GL.event.frameboundary.end`，其中调用 `renderer` 用的槽偏移 16.5 是 0x1a0、26 是 0x1b0。26 另有一张 70 槽表 `0x1ee981ec0` 的同槽函数也引用这条字符串，两张表靠构造函数区分。
- `renderer`（26 `0x183f37dc0`）与 16.5 的 `0x1882e2548` 流程相同：对象里缓存的两个字段为空时创建渲染器对象、写回字段，并在 `[this+0x60]` 上登记；字段偏移从 0x318／0x320 变为 0x5c8／0x5d0。

`GLESContext`：26 的虚表 `0x1ee982ab0`（164 槽），基类 `0x1ee989180`（69 槽）；16.5 是 `0x1d5b3b540`（138 槽）与 `0x1d5b3d128`（54 槽）。对应依据：

- 构造函数 16.5 `0x188400a18` 与 26 `0x1840d1c28` 逐项对应：调用基类构造并写基类虚表，构造参数存进 `[this+0xa8]`／`[this+0x258]`，常数 0x3c000000 写进 `[this+0x800]`／`[this+0xaa0]`，自身虚表 + 0x10 写进 `[this]`，`[this+0x868]`／`[this+0xb08]` 做 `orr #2`，最后用构造参数调用初始化函数。
- 引用 `GL_INVALID_ENUM` 等 9 条错误字符串的函数在 16.5 的 0xa8（`0x1884a82c4`），在 26 的 0xf0（`0x18416374c`）。

## 7. `CA_HEARTBEAT_RATE` 与刷新周期

`0x183f380d8` 返回显示刷新周期，单位秒，默认 1/60（常量 `0x184242688`）。16.5 的 `0x1882d3930` 结构相同，只是字段偏移不同。26 用到的字段：`[this+0x7528]` 结果缓存，`[this+0x7510]` 刷新步长（秒），`[this+0x7508]` 最小刷新间隔，`[this+0x280]` 标志字，`[this+0x290]` 模式字。

26 的计算顺序：

1. `[this+0x7528]` 非零直接返回，为零时按下面的顺序算一次并写回。
2. `getenv("CA_HEARTBEAT_RATE")` 非空时返回 `1.0 / atof(值)`。同镜像有格式串 `heartbeatRate: %g Hz`，输入按 Hz 解释属于推断。值解析不成数字时结果是 +inf，不回退到默认值。
3. 否则返回非零的 `[this+0x7510]`。初始化函数 `0x184070768` 从 IOMFB 属性 `IOMFBDisplayRefresh` 的 `displayRefreshStepMachTime` 读整数，经 `0x183f46e9c` 从 mach tick 换成秒后写进这个字段。
4. 否则 `[this+0x7508]` 非零时返回 `(double)值 × 2^-32`，`[this+0x280] & 0x10` 非零时乘 2^-33。这个字段来自同一属性的 `displayMinRefreshInterval`；上游实测这个键以 2^-32 秒为单位（[上游做法](2026-11-01-hakios-upstream-lessons.md) §2），与这里的换算一致。
5. 都没有时返回 1/60。
6. 最后，`[this+0x290]`（记为 x）不为 -1 时返回值改为 `65536.0 / ((x >> 29) & 0x1ffffff)`，`[this+0x280] & 0x10` 非零且 x 为负时再乘 0.5。这一步不写回缓存，每次调用都重算。字段编码没有确认，写 0x290 的位置没有找到。

调用点：没有直接调用，`vcalls --offset 0x318` 在 26 找到 28 处，分布在 19 个函数（16.5 的 0x2d8 为 32 处）。返回值的用法：

- 经 `0x183f4688c` 换成 tick 后参与截止时间计算（`0x183f33a44`、`0x183f4ad50`）。
- 在 `0x183f4ad50` 里换成频率，存进 `[this+0x628]`；在 `0x183f33a44` 里用于帧间隔直方图。
- 在 `0x18409aa38` 里与槽 0x320 的计数相乘、加基准 tick 后存进 `[obj+0x3e8]`，推断为下一次更新时间。
- 28 处都没有把返回值直接传给 `CFRunLoopTimerCreate`、`CFRunLoopTimerSetNextFireDate`、`dispatch_source_set_timer`、`mach_wait_until` 或 `nanosleep`，定时器周期是否由它决定没有确认。

## 8. 未完成

后续研究与验收见[图形与显示待办](../backlog/graphics.md)，本节保留静态分析的范围。

- `is_ready`：0xe0 指向 `0x183f4fdfc` 只是推断，尚无真机 `AppleCLCDDisplay` 对象的虚表读数。
- `GLESContext` 上 `inject.c` 用的三个槽（`function_supported` 0x378、`function_uniform` 0x388、`compile_shader` 0x060）没有重定位。16.5 的 `function_supported`（`0x1884a9308`）靠 `cmp w9,#0x59` 加字节跳转表分派，26 里没有同形状的函数；`compile_shader` 的 16.5 槽函数 `0x1883fc808` 只有 `mov w0,#0; ret`，与 `inject.c` 注释说的编译着色器不符，原因未查。
- `EAGLServer` 除 `renderer`、`render_update` 外的槽，以及两个基类虚表 `0x1ee98e008`、`0x1ee989180`，只做到基址与槽数，没有逐槽核对。

## 9. 复现命令

在工作区根目录执行，`--cache` 不给时读 26 的缓存。

```text
python3 -I hackios-xnu-kernel/tools/dsc/dsc.py info
python3 -I hackios-xnu-kernel/tools/dsc/dsc.py map 0x1ee97f868 0x183efe30c
python3 -I hackios-xnu-kernel/tools/dsc/dsc.py vtscan QuartzCore
python3 -I hackios-xnu-kernel/tools/dsc/dsc.py slots 0x1ee97f868 --count 320 --strings
python3 -I hackios-xnu-kernel/tools/dsc/dsc.py --cache hackios-xnu-kernel/ios165/20F66__iPhone10,3_6 \
    slots 0x1d5b44520 --count 246 --strings
python3 -I hackios-xnu-kernel/tools/dsc/dsc.py extract QuartzCore -o /tmp/dsc26x/QuartzCore
python3 -I hackios-xnu-kernel/tools/dsc/dsc.py vcalls QuartzCore --offset 0xe0 --offset 0x1b0 --offset 0x318
python3 -I hackios-xnu-kernel/tools/dsc/dsc.py refs QuartzCore 0x183f4fdfc 0x183f380d8 --mode call
python3 -I hackios-xnu-kernel/tools/dsc/dsc.py findstr QuartzCore "complete_powering_on"
python3 -I hackios-xnu-kernel/tools/dsc/dsc.py disasm 0x184072d88 --count 3
python3 -I hackios-xnu-kernel/tools/dsc/dsc.py read 0x184242688 8
```
