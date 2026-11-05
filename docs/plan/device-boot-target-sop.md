# 真机引导目标切换 SOP（Android／LK／loader）

本文件给出 K90 上三种引导目标之间切换的固定命令与成功判据，耗时取自 2026-10-28 至 10-29 的实测。设备序列号通过环境变量 `ANDROID_SERIAL` 提供，loader 固定用 `xnuloader`；同一设备的命令串行执行。

槽位假设：本项目的脚本按「Android 在 B 槽、loader 写在 A 槽的 boot 分区」编写。`tools/k90auto/cycle.py`、`tools/k90auto/reboot-lk.py`、`tools/k90auto/recover-loader.py` 固定执行 `set_active a`，`recover-loader.py` 还断言 Android 的 `ro.boot.slot_suffix` 为 `_b`。下文命令按这个布局写；Android 在 A 槽的设备需要对调命令里的 a／b，并修改这些脚本。

## 1. 先判当前身份

枚举只用 `fastboot devices`，不对尚未出现的序列号发 `fastboot -s xnuloader …`（原因见 §4 第 2 条）。

| 身份 | 判别命令 | 判别串 | 说明 |
|---|---|---|---|
| Android | `adb -s "${ANDROID_SERIAL}" get-state` | `device` | 进一步核 `getprop sys.boot_completed` 与 `getprop ro.boot.slot_suffix` |
| LK fastboot | `fastboot -s "${ANDROID_SERIAL}" getvar product` | `annibale`，且 `getvar is-userspace` 答 `no` | 能答 `current-slot`、`slot-*` 一组变量 |
| Android fastbootd | 同上 | `is-userspace` 答 `yes` | 本项目的实验不走 fastbootd |
| 驻留 loader | `fastboot devices` | 出现 `xnuloader` | 再核 `getvar result` 与 `getvar ramdisk-state` |

`getvar result`、`getvar build-id`、`getvar ramdisk-state` 三个变量只有 loader 答，LK 上问会答 `GetVar Variable not found`，据此判断 loader 有没有驻留。能答这三个变量但状态异常时（例如 `result: hung-held`），loader 本身在运行，异常出在内核或运行状态。

## 2. 五条切换路径

| 起点 → 目标 | 命令 | 成功判据 | 实测耗时 |
|---|---|---|---|
| Android → LK | `adb -s "${ANDROID_SERIAL}" reboot bootloader` | `fastboot devices` 出现该序列号，`getvar product` 答 `annibale` | 8～11 秒 |
| LK → Android | `fastboot -s "${ANDROID_SERIAL}" set_active b`，再 `reboot` | USB 断开后重新枚举，`adb -s "${ANDROID_SERIAL}" get-state` 答 `device`；`sys.boot_completed=1` | 15～19 秒 |
| LK → loader | `set_active a`，再 `reboot` | `fastboot devices` 出现 `xnuloader`，`getvar result` 答 `idle`，`getvar ramdisk-state` 答 `idle 0 0 0` | 17 秒 |
| loader → LK | `python3 tools/k90auto/reboot-lk.py <新目录> --payload hackios-xnu-kernel/out/ios26-resume/reboot-lk-prepare/annibale-reboot-lk-prepare.bin --sha256 6b81e800ae789cf30adbaaa9c98768012e264c66a4e56110c6449cecf93fb7d7 --serial "${ANDROID_SERIAL}"` | 工具输出 `LK FASTBOOT verified on slot <a\|b>`，`result.json` 的 `lk_entered` 为真 | 8 秒 |
| loader 复位（PSCI） | `fastboot -s xnuloader reboot` | 先断开约 10 秒，再重新枚举为 `xnuloader`，`result` 答 `idle`，`ramdisk-state` 答 `idle 0 0 0` | 11 秒 |

- 两个方向都靠 `set_active` 换目标槽再 `reboot`。LK 的 `reboot` 本身只做复位，启动哪个槽由 `set_active` 决定。
- 切到 A 槽前先核 B 槽可用：`slot-successful:b=yes`、`slot-unbootable:b=no`。`reboot-lk.py --return-loader` 会自动检查这两个量，手工切槽时要自己核对。
- 从 loader 回 Android 要两跳：先 `reboot-lk.py` 进 LK，再 `set_active b` 加 `reboot`。loader 自己的 `reboot` 只会回到 A 槽。
- `reboot-lk.py` 的前置条件、记录文件与往返模式见 [k90auto 说明 §5](../../tools/k90auto/README.md#5-软件进入-lk-fastboot)。

## 3. 一次进 loader 的最短序列

从 Android 出发，四条命令、约 30 秒：

```sh
adb -s "${ANDROID_SERIAL}" reboot bootloader
fastboot -s "${ANDROID_SERIAL}" getvar current-slot
fastboot -s "${ANDROID_SERIAL}" set_active a
fastboot -s "${ANDROID_SERIAL}" reboot
```

随后用 `fastboot devices` 等 `xnuloader` 出现，再核 `result: idle` 与 `ramdisk-state: idle 0 0 0`。

## 4. 陷阱（均为实测）

1. LK `fastboot boot <handoff payload>` 不会把 loader 带起来。2026-10-28 两次实测命令都答 `Booting OKAY`，之后 80 与 90 秒内 `xnuloader` 从未枚举，`result`／`build-id`／`ramdisk-state` 都答 `GetVar Variable not found`。命令答 OKAY 不能说明 loader 已驻留，判别只看 `fastboot devices` 与这三个变量。
   - 完整的 loader 镜像（BootShim、FD、XNUP、DTB，例如 `hackios-xnu-kernel/out/handoff-loader-v17.img`）可以 `fastboot boot`：2026-10-31 实测 18 秒后 `xnuloader` 枚举，不刷 `boot_a`，也不扣 `slot-retry-count:a`，见[开机次序与性能记录](../progress/2026-10-31-boot-order-and-performance.md) §5。本地有 v16 镜像时，`cycle.py` 的检查点就用这条路起 v16。
2. 对未枚举的序列号发 `fastboot -s xnuloader getvar …` 会挂住。该客户端进入 `< waiting for xnuloader>` 并可能成为后台作业，与其它 fastboot 客户端并发时会把 USB 命令通道卡住。枚举一律用 `fastboot devices`。
3. LK 的 `reboot` 在目标槽被标为不可引导时无效。实测 `slot-unbootable:b=yes` 时 `reboot` 答 `OKAY` 而设备仍停在 LK；`set_active b` 会清掉这个标志（读回 `slot-unbootable:b=no`），`set_active a` 同样清 A 槽。判断是否真的复位看 USB 是否断开：`ioreg` 250 毫秒采样能看到设备消失再重现，只看命令返回值判断不出来。
4. `slot-retry-count:a` 每跑一轮扣 2 次，约三轮后归 0，LK 随即把 A 槽标成不可引导并回退 B 槽 Android。经 loader 起 iOS 不写成功引导记录，`slot-successful:a` 始终是 `no`，计数器一路递减，与 panic 无关。`set_active a` 把计数重置为 7 并把 `slot-unbootable:a` 清回 `no`。起轮前先读 `slot-retry-count:a`，低于 3 时执行 `set_active a`。`cycle.py` 每 2 轮经 `reboot-lk.py` 进 LK 做一次 `set_active a` 并读回 7；`round-run.py` 只在设备处于 LK 时读这个计数，低于 3 时重置。
5. 安卓侧点屏不能用 `input keyevent`。adb shell 缺 `INJECT_EVENTS`，会抛 `SecurityException`；用 `svc power stayon usb` 能把屏幕点亮。`screencap` 全黑先看 `mWakefulness` 与 `Display State`，两者都是 OFF 时黑屏来自休眠，与面板无关。
6. `reboot-lk.py` 的 `--payload` 必须是 prepare 载荷。误传轮次载荷时，工具 `stage` 后把内核又起了一次并停在 `hung-held`，报 `Probe return timed out; reboot not sent`；那次引导的日志是 `Process 1 exec of /sbin/launchd failed, errno 2`（没有常驻系统盘）。

## 5. 三种复位的差别

同一台设备上的「复位」有三种，清掉的状态不同。

### 5.1 PSCI 复位

- 命令：`fastboot -s xnuloader reboot`。annibale 上 loader 的 `reboot` 分支一律调用 `psci_reset_attempt()`（`xnuloader/loader_06_usb_entry.inc`），该调用返回时 `result` 记为 `reset-failed`。
- 判据：`fastboot devices` 先变空、随后重新列出 `xnuloader`，再读 `getvar result` 得 `idle`、`getvar ramdisk-state` 得 `idle 0 0 0`。`run-auto.py` 的 `reboot.json` 记 `off_seen: true`、`mode: loader`，实测断开到重新可用 16.9～17.8 秒。
- 适用：一轮跑完或内核停住后，把设备带回可再用的 loader。`run-auto.py` 每轮收尾做的就是这一种，复位后启动的是 A 槽 `boot_a` 里刷着的 loader。

### 5.2 宿主冷复位

- 命令：这台设备上没有主机侧命令能做到。`loader_06_usb_entry.inc` 的 `reboot` 分支在 annibale 上只有 PSCI 一条路；要断电只能由人长按电源键强制关机再开机。
- 判据：未实测。
- 何时需要：内核在 `adreno8_quiesce()` 里打印 `adreno8: GPU probe requires host cold reset before reusing kernel memory` 后停在 `wfe` 循环（`xnu/files/bsd/dev/adreno8.c`，触发条件是 `adreno8_reset_required` 或 `adreno8_memory_retained()`）。这条打印表示 GMU 的 RPMh 投票或 GMU 内存没有收回，loader 不应把那段内存再分给下一个内核。实测 GPU 轮次的收尾日志末行都有这句，PSCI 复位后设备仍回到可用 loader，下一轮也能起；PSCI 复位能否清干净 GPU 状态，没有功率计对照之前仍未确定。

### 5.3 走 LK 的整轮重启

- 命令：安卓侧 `adb reboot bootloader` → LK 侧 `fastboot -s "${ANDROID_SERIAL}" set_active a` → `fastboot -s "${ANDROID_SERIAL}" reboot`（或 `fastboot boot <完整 loader 镜像>`）；从 loader 出发时先用 `tools/k90auto/reboot-lk.py` 进 LK。
- 判据：LK 侧 `getvar product` 得 `annibale`、`current-slot` 与切换后一致；进 loader 后 `result: idle` 加 `ramdisk-state: idle 0 0 0`；回安卓后 `adb` 出现 `device`、`sys.boot_completed=1`。
- 实测耗时：安卓到 LK 8～11 秒、LK 到 loader 17 秒、loader 到 LK 8 秒、LK 到安卓 15～19 秒。
- 适用：恢复 A 槽重试次数（§4 第 4 条），以及起一个没有刷进 `boot_a` 的 loader（§4 第 1 条）。`cycle.py` 的检查点就是这一种。

## 6. 连续起轮

无人值守的硬约束见 [AGENTS.md](../../AGENTS.md) 第 5 节：loader 未枚举或序列号为空即停手，每轮收尾校验 `getvar result` 为 idle、`getvar product` 为 `xnuloader`，A 槽重试有预算，一个批次最多 3 轮。设备从 USB 整个消失的形态与处置见 [USB 恢复经验](../analysis/2026-10-25-usb-recovery-lessons.md) 第 4 节。

`cycle.py` 已把起轮前后的检查做进脚本：

- 起轮前要求 `fastboot devices` 里有 `xnuloader`、`result` 为 idle、`ramdisk-state` 为 `idle 0 0 0`，任一项不满足就停止。
- 设备在 Android 时先调 `recover-loader.py` 经 LK 回到 loader。
- 每 2 轮做一次检查点（§5.3），驻留 loader 的 build-id 不含 `a48c7fb`（v16、v17 的 loader）时也先做检查点。
- 载荷、根盘、系统盘的身份由 `make-payload.py`、`run-auto.py` 按 `manifest.json` 的 SHA-256 核对，不符就拒跑。
- 轮次结束后再核一次 loader 状态，不满足就以非零退出。

手工起轮时，在 LK 侧读下面五项并记下，作为下一轮出现异常时的对照基线：

```sh
fastboot -s "${ANDROID_SERIAL}" getvar current-slot
fastboot -s "${ANDROID_SERIAL}" getvar slot-retry-count:a
fastboot -s "${ANDROID_SERIAL}" getvar slot-retry-count:b
fastboot -s "${ANDROID_SERIAL}" getvar slot-unbootable:a
fastboot -s "${ANDROID_SERIAL}" getvar slot-unbootable:b
```

轮次中途发现设备身份与预期不符（例如 `adb devices` 变空、`fastboot devices` 列出 `xnuloader`，或槽位与起轮时读到的不一致），立即停下并报告用户，不自行续跑；身份不符时继续发命令，后续读数无法归因。

轮次收尾停在 loader，不回安卓。回安卓只在两种情况下做：用户要用手机，或接下来较长时间不跑。

## 7. 与其它文档的关系

操作命令、日志读取与故障恢复见[真机调试手册](device-test-playbook.md)；异常后的资源保留与 USB 恢复判断见[USB 恢复经验](../analysis/2026-10-25-usb-recovery-lessons.md)；`reboot-lk.py` 的用法见 [k90auto 说明](../../tools/k90auto/README.md)；轮次怎么跑见[k90auto 运行协议](k90auto-run-protocol.md)。
