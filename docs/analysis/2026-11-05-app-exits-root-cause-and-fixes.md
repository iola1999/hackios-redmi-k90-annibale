# 蓝牙 3 Mbaud 切换与内置应用退出根因及修复

本文档记录 HackiOS 在 REDMI K90（SM8750，代号 `annibale`）上蓝牙阶段 3 扫描验证、3 Mbaud 波特率切换实现，以及系统内置应用（提醒事项、计算器、备忘录、语音备忘录）异常退出的根因定位与修复方案。

## 1. 概述与范围

本批工作包含两部分：一是核实蓝牙阶段 3 扫描记录，实现 3 Mbaud UART 波特率切换与 LE 连接事件处理；二是定位桌面内置应用启动退出的根因并完成修复，解决后台守护进程缺失与沙盒容器路径缺失导致的异常终止。

## 2. 蓝牙阶段 3 实测记录与 3 Mbaud 波特率切换

在 `docs/progress/evidence/k90auto/kernel-12377-st4-r2/run/s006.log` 与 `render-report.txt` 的实测记录中，`bluetoothd`（PID 46）在系统启动后保持稳定运行，日志周期性上报主动扫描（`Main:30.00ms/40.00ms`）与被动扫描（`Main:30.00ms/300.00ms`）窗口状态。设备捕获到包含苹果厂商标识 `id:4C` 的 Continuity 广播数据包（如 `4C 00 10 06 ...`、`4C 00 09 08 ...` 与 `4C 00 1C 09 ...`），并向 `'other devices' cache` 写入 11 个独立外设条目，全程无崩溃或重启，蓝牙阶段 3（LE Scan 发现 Continuity 广播）验证通过。

外设配对与 ACL 数据传输需要更高的串口吞吐量，内核在 115200 波特率完成芯片固件载入后需切换至 3 Mbaud。高通 WCN7850 蓝牙芯片通过厂商命令 `OP_QCA_SET_BAUDRATE`（Opcode `0xFC48`）调整芯片波特率，3 Mbaud 对应参数 `0x00 0x00 0x00 0x0F`。SM8750 的蓝牙 UART 位于 GENI SE14，时钟源为 GPLL0_EVEN（300 MHz），3 Mbaud 配合 16 倍过采样需 UART 核心时钟达到 48 MHz。分频参数为 $48 / 300 = 4 / 25$，即 $M=4, N=25, D=42$（寄存器写入值 $D-N = 17$），RCG CFG 分频比写入 1（`0x2601`），GENI 内部采样分频比设为 1。

代码实现分布在 `annibale_bt_uart.c`、`annibale_bt_hci.c` 与 `annibale_bt_ios.c`：
1. `annibale_bt_uart_set_baud()`：配置时钟寄存器（CMD/CFG/M/N/D）并刷新 GENI 采样分频寄存器，提供波特率切换执行入口。
2. `annibale_bt_hci_set_baudrate()`：向控制器发送 `0xFC48` 指令，等待命令完成事件后延时 10 毫秒待电平稳定，再调用 UART 驱动切换主机时钟，支持启动参数 `bt_baud=3000000` 触发。
3. `annibale_bt_ios.c`：拦截用户态下发的 `0xFC48` 并同步主机时钟，在 `bt_ios_take()` 处理 LE 连接完成事件（子事件 `0x01` 与 `0x0a`）与 ACL 链路数据诊断。

## 3. 提醒事项（Reminders.app）退出根因与修复

提醒事项应用在启动后因 XPC 连接超时退出。其依赖的后台守护进程为 `/usr/libexec/remindd`。在根文件系统裁剪脚本 `hackios-xnu-userland/ios165/select-system.py` 中，大型程序过滤阈值为 `BIG_PROGRAM = 10 << 20`（10 MB）。`remindd` 二进制体积为 11.4 MB，被过滤逻辑排除在 `rootfs` 镜像之外，导致应用向 `com.apple.remindd` 发起 XPC 请求时无法拉起服务而退出。

修复方案：在 `hackios-xnu-userland/ios165/select-system.py` 的 `BIG_PROGRAMS_KEPT` 白名单中新增 `'usr/libexec/remindd'`，与已有的 `'usr/sbin/bluetoothd'`（11.6 MB）一并保留。

## 4. 计算器（Calculator.app）与备忘录（MobileNotes.app）退出根因与修复

计算器与备忘录启动时触发 Objective-C 异常终止：`*** Terminating app due to uncaught exception 'NSInvalidArgumentException', reason: '*** -[NSURL initFileURLWithPath:]: nil string parameter'`。异常堆栈显示，Foundation 框架初始化应用沙盒主目录与数据共享目录时调用 `NSHomeDirectory()` 与沙盒容器解析逻辑，因缺少用户容器路径环境变量及目录结构而返回 `nil`，向 `NSURL` 传入空路径导致断言失败。

内核在 `kern_minimac.c` 的 `SANDBOX_SYSCALL_CONTAINER_PATH` 拦截中读取进程环境块的 `CFFIXED_USER_HOME` 定向容器路径。环境块未导出 `CFFIXED_USER_HOME` 时，沙盒系统无法推导数据目录。备忘录同时依赖应用组（AppGroup）共享目录 `group.com.apple.notes`，`/private/var/mobile/Containers/Shared/AppGroup` 不存在时 CoreData 存储初始化直接报错。

修复方案包含四处改动：
1. `tools/k90auto/package.py`：在根文件系统骨架构建逻辑中预先创建应用专有容器目录 `/private/var/mobile/Containers/Data/Application/<UUID>`（计算器、备忘录与提醒事项各自对应固定 UUID）以及备忘录应用组目录 `/private/var/mobile/Containers/Shared/AppGroup/group.com.apple.notes`，设置权限 `0755` 与属主 `mobile:mobile`。
2. `tools/k90auto/package.py`：在启动环境导出列表 `EXT_ENV` 中，为目标应用写入对应的 `CFFIXED_USER_HOME=/private/var/mobile/Containers/Data/Application/<UUID>`、`HOME` 与 `TMPDIR`。
3. `hackios-xnu-userland/userland/src/inject_app.c`：在应用启动注入动态库中增加 `setup_app_container_env()`，在构造函数阶段读取 `/redwood/etc/env/<app>` 配置；独立配置文件缺失时按应用标识匹配预设容器路径并设置环境变量，保证 `NSHomeDirectory()` 返回合法本地路径。
4. `hackios-xnu-userland/userland/var.skel.extra`：加入容器顶层目录结构，与打包脚本保持一致。

## 5. 语音备忘录（VoiceMemos.app）退出根因与暂缓说明

语音备忘录启动后黑屏退出。日志与系统调用显示，应用加载主界面时立即请求启动录音会话（`AVAudioSessionCategoryRecord` 或 `AVAudioSessionCategoryPlayAndRecord`），向 `mediaserverd` 申请输入路由与麦克风采集端点。当前内核与音频服务层尚未接入 SM8750 麦克风硬件编解码器（WCD9395/LPASS ADC）与内核音频录音输入管道（PCM capture stream），`mediaserverd` 返回硬件不可用错误，音频会话初始化抛出异常。该问题待麦克风输入驱动接入后一并处理。

## 6. 验证与代码行数核对

各项改动已完成语法检查与测试：
1. Python 语法编译：`python3 -m py_compile tools/k90auto/package.py hackios-xnu-userland/ios165/select-system.py` 通过。
2. 自动化工具套件测试：`python3 tools/k90auto/test-tools.py` 运行 15 项测试全部通过。
3. 代码行数核对（`AGENTS.md` §2 单文件 1200 行上限）：
   - `hackios-xnu-userland/ios165/select-system.py`：298 行。
   - `hackios-xnu-kernel/xnu/files/bsd/dev/annibale_bt_private.h`：43 行。
   - `hackios-xnu-kernel/xnu/files/bsd/dev/annibale_bt_uart.c`：539 行。
   - `hackios-xnu-kernel/xnu/files/bsd/dev/annibale_bt_hci.c`：646 行。
   - `hackios-xnu-kernel/xnu/files/bsd/dev/annibale_bt_ios.c`：945 行。
   - `hackios-xnu-userland/userland/var.skel.extra`：16 行。
   - `hackios-xnu-userland/userland/src/inject_app.c`：426 行。
   - `tools/k90auto/package.py`：1131 行。
