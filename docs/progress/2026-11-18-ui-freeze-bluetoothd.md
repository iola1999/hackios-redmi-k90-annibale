# 设置与控制中心卡死：bluetoothd 中止与内核 BT 拉起修复（2026-11-18）

本文记录 2026-11-18 凌晨设置与控制中心卡死的现场、bluetoothd 的中止机制、内核 BT 拉起失败的根因与修复验证。待办见[系统待办 S11](../backlog/system.md)与[后续批次 MISC-9](../plan/2026-11-16-followup.md#6-多媒体系统契约蜂窝与工程清理遗留)。卡死现场的截图、日志快照、线程栈与崩溃报告保存在 Git 忽略的 `out/settings-hang-2026-11-18/`，修复验证轮次在 `docs/progress/evidence/k90auto/kernel-12377-bt1-*`。

## 1. 现象与现场

- 设置：锁屏放后台一段时间后再打开，停在「隐私与安全性」页无响应，关掉重开正常；00:10:15 自行恢复。
- 控制中心：00:14:10 长按蓝牙请求展开下拉列表，面板未出现，整机无响应，之后经 `recover-loader.py` 软件恢复，没有按键。
- 日志环冲掉了两次卡死的起点。恢复后重启的那次开机（`s004-reboot.log`）完整记录了 bluetoothd 的中止过程，见第 3 节。

## 2. 控制中心卡死时的线程栈

- SpringBoard 主线程（tid 260）的栈按共享缓存 slide `0x2d7c000` 还原后用 `dsc.py map` 符号化：UIKitCore → ControlCenterUIKit → ControlCenterUI → CoreBluetooth → libxpc → libdispatch → `mach_msg2_trap`，主线程在蓝牙模块展开路径里同步等待 bluetoothd 的 XPC 回复。
- SpringBoard tid 60359、61260 与 backboardd tid 61393 停在同一个 libxpc 同步等待里。
- 卡死期间 bluetoothd 以 pid 674 出现后又退出。设置卡死时的主线程栈没有取到，设置页卡死与 bluetoothd 的关系未确认。

## 3. bluetoothd 的中止机制

- 11-15 的 bluetoothd 崩溃报告为 SIGABRT（`abort() called`），两帧 `0x8150b4`、`0x43a5c` 都在 `bluetoothd` 镜像内，是返回地址。
  - `0x1008150b0` 是 `bl _abort`，所在函数 `0x100814fb0` 记录 `BT Stack Stuck`、`Stack watchdog timeout on thread: %s` 和 `Watchdog_Timer - Stack Mutex try lock failed and watchdog has struck twice -- abort`；`0x100043a58` 是对该函数的调用。
  - 函数以 noreturn 调用结尾时，返回地址正好是下一个函数的开头，按返回地址查函数前要先减 4。
- `s004-reboot.log` 记录了同一机制：`bluetool` 等待 40 s 后报 `bt_ready=0`；00:28:47 bluetoothd 打印 `Searching for transport: "H4"`；00:29:18 打印上述 watchdog 行，`userabort: bluetoothd[46]` 的调用地址换算后是 `0x8150b4 ← 0x43a5c`。
- 内核侧，`/dev/uart.bluetooth` 的 open 和 `com.apple.uart.sk.bluetooth` 的 connect 都轮询等待 `bt_ready`，最长 40 s。bluetoothd 持协议栈互斥锁打开传输层，watchdog 第二次触发（本例 31 s）时中止进程。
- 芯片没有就绪时，bluetoothd 每次重启都在 open 里被自己的 watchdog 中止；持锁期间，同步等待 bluetoothd 的 XPC 客户端全部阻塞。

## 4. 内核 BT 拉起失败的根因

- 11-16 09:00 到 11-18 本批之前的轮次里，有拉起结果的 47 轮只有 `kernel-12377-iris1-cam-home` 一轮成功，其余 46 轮以 `bt: stop: reset: HCI Reset after the firmware failed (0 bytes, status 0xff)` 结束；另有 20 轮日志里没有拉起结果。
- 补丁下载完成后，芯片把自身日志作为 ACL 包发出（句柄 `0x2edc`，即 Linux `btqca.c` 的 `QCA_DEBUG_HANDLE`），负载里有 `04` 字节。
- `annibale_bt_hci.c` 的 `hci_event()` 只认事件包，把负载里的 `04` 当作事件开头，按错误的长度读取，吞掉了后面 HCI Reset 的 Command Complete，3 s 后超时返回 0 字节。成功的那一轮是错位后碰巧重新对齐。
- 驻留 iOS 的两次开机（`s000.log`、`s004-reboot.log`）在固件下载开始后没有进度行，失败点没有日志可查，原因未确认。

## 5. 修复与验证

- `hci_event()` 按 H4 包长整包跳过 ACL 与 SCO 包，`0x2edc` 日志包只打印前两个；声明长度超出接收缓冲的类型字节按噪声丢弃。
- 拉起线程结束而芯片没有进入服务状态时，`annibale_bt_ios_ended()` 置位，open 与 connect 立即返回 `ENXIO`，不再等满 40 s。
- 宿主测试 `hackios-xnu-kernel/tools/tests/test-bt-hci-event.py` 从源码抽出 `hci_event()`，用含 `04` 的日志包加 Command Complete 构造字节流：新实现取到事件；旧实现超时返回 0 字节，与设备日志一致。
- 真机 `kernel-12377-bt1-bt1a`（内核 `12377-bt1`）：
  - 拉起完成，日志依次为 `reset: done`、`handed to bluetoothd`；`bluetool` 在 23 s 时看到 `bt_ready=1`，bluetoothd 连接控制通道等待 0 ms。
  - 控制中心长按连接模块后展开，再长按蓝牙弹出「正在载入…／蓝牙设置…」菜单；设置页蓝牙显示「打开」。
  - 整轮 bluetoothd 保持 pid 46，没有 watchdog 中止。

## 6. 未决事项

- 设置「隐私与安全性」页卡死与 bluetoothd 的关系未确认，复现时取设置主线程栈。
- 对端进程退出后，客户端的同步 XPC 是否按时收到中断错误未验证。
- 驻留 iOS 开机时固件下载停住，见第 7 节。

## 7. 驻留开机的固件下载停住（发布后观察）

`boot_a` 换成 `v0.2.1` 发布镜像（内核与 `12377-bt1` 相同）后，11-18 当天驻留开机 7 次，3 次拉起成功，4 次停在 `bt: hmtbtfw20.tlv: sending 275208 bytes in 1133 pieces, unanswered`，之后没有任何 `bt:` 行，最长观察超过 10 分钟。成功的开机在同一位置之后依次打印 25%～100%、`taken` 与 `done`。日志在 Git 忽略的 `out/handover-2026-11-18/final/`。

| 开机时间 | 之前的状态 | 结果 |
|---|---|---|
| 发布验证时 | 经 LK 刷入 `boot_a` 后重启 | 成功 |
| 04:20 | `mapk1` 轮（蓝牙正常）GPU 停转后退回 loader 空闲态，再 `fastboot reboot` | 成功 |
| 04:34 | `mapk5` 轮（蓝牙正常）GPU 停转、按停止请求收尾后，loader 自动启动 | 停住 |
| 04:45、04:49、04:51 | 上一次驻留开机停住，经 `recover-loader.py` 退回空闲态后 `fastboot reboot` | 都停住 |
| 04:58 | `btcam5` 轮（蓝牙正常）结束后退回空闲态，再 `fastboot reboot` | 成功 |


- 同一天 k90auto 的 7 轮（`cam3d`、`mapk1`～`mapk5`、`btcam5`）用同一内核从 loader 内存启动，蓝牙全部拉起成功。凌晨事故的两次驻留开机（第 4 节）也是这个现象。
- 启动参数的差异只有 `cam=5`、`torch=1`、`gpu_log`、`touch_lat`、`autounlock`、`usertrap`。`btcam5` 轮带上 `cam=5 torch=1` 后照常拉起，这两项排除。剩下的差异是启动方式：轮次从 loader 内存载入内核与根盘，驻留开机由 `boot_a` 镜像从 UFS 启动。
- `annibale_bt_uart_write()` 的等待都有上限，超时会打印 `TX FIFO stays` 或 `not sent`，下载循环失败会打印 `bt: stop:`。这些都没有出现，拉起线程没有从下载循环返回，停在哪里未确认。
- 拉起线程不结束，`annibale_bt_ios_ended()` 不会被调用，`/dev/uart.bluetooth` 的 open 与控制套接字 connect 仍会等满 40 s，第 3 节的 watchdog 中止与卡死风险在这类开机里依然存在。
- 04:45 那次开机里 bluetoothd 经 Skywalk 通道（`btsk_sync_tx` → `bt_ios_put`）发出 HCI 命令，这条路径不检查 `bt_serving`，芯片没有就绪时也会写 UART。该开机里这些命令出现在下载停住之后，不是停住的原因。
- 停住的开机之后接着驻留开机，三次都停住；中间跑过一轮 k90auto 再驻留开机，两次都成功。芯片状态是否跨热重启保留、k90auto 的启动路径是否给芯片重新上电，都未确认。
- 下一步：在停住的开机里用 `kern.annibale.thread_dump` 取内核线程的等待位置；下载循环按片打印进度以确定停在第几片；对比 loader 的 `oem run` 与自动启动两条路径对 BT_EN 和 WCN7850 供电的处理；`bt_ios_put` 在芯片就绪前不写 UART。

