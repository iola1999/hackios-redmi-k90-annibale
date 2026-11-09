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
- 从运行中的 iOS 退回驻留 loader：除主机执行 `fastboot -s xnuloader oem stop` 外，也可在触摸屏五指同时按住 1.5 秒（`annibale_input.c` 的 `EXIT_FINGERS=5`、`EXIT_HOLD_MS=1500`），内核依次调用 `annibale_var_save_on_return()` 同步 `/private/var`、`annibale_wifi_stop()` 停止 Wi-Fi，再经 `loader_return()` 退回 `xnuloader`（`getvar result` 答 `returned ...`）。
- `reboot-lk.py` 的前置条件、记录文件与往返模式见 [k90auto 说明 §5](../../tools/k90auto/README.md#5-软件进入-lk-fastboot)。

表中的 `idle` 判据适用于等待主机载荷的调试镜像。内置 standalone 的日常镜像会自动启动 iOS，需要核对 `build-id`、`running 0 0`、启动卷实际长度和启动日志；2026-11-08 的镜像使用 4 MiB 启动卷。`run-auto.py` 和 `cycle.py` 只接受空闲且常驻区为空的 loader，更换正在运行的镜像按 §4 第 8 条先正常停止并保存日志。

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

1. LK `fastboot boot <handoff payload>` 无法拉起 loader。2026-10-28 两次实测命令都答 `Booting OKAY`，之后 80 与 90 秒内 `xnuloader` 从未枚举，`result`／`build-id`／`ramdisk-state` 都答 `GetVar Variable not found`。命令答 OKAY 不能说明 loader 已驻留，判别只看 `fastboot devices` 与这三个变量。
   - 完整的 loader 镜像（BootShim、FD、XNUP、DTB，例如 `hackios-xnu-kernel/out/handoff-loader-v17.img`）可以 `fastboot boot`：2026-10-31 实测 18 秒后 `xnuloader` 枚举，不刷 `boot_a`，也不扣 `slot-retry-count:a`，见[开机次序与性能记录](../progress/2026-10-31-boot-order-and-performance.md) §5。本地有 v16 镜像时，`cycle.py` 的检查点就用这条路起 v16。
2. 对未枚举的序列号发 `fastboot -s xnuloader getvar …` 会挂住。该客户端进入 `< waiting for xnuloader>` 并可能成为后台作业，与其它 fastboot 客户端并发时会把 USB 命令通道卡住。枚举一律用 `fastboot devices`。
3. LK 的 `reboot` 在目标槽被标为不可引导时无效。实测 `slot-unbootable:b=yes` 时 `reboot` 答 `OKAY` 而设备仍停在 LK；`set_active b` 会清掉这个标志（读回 `slot-unbootable:b=no`），`set_active a` 同样清 A 槽。判断是否真的复位看 USB 是否断开：`ioreg` 250 毫秒采样能看到设备消失再重现，只看命令返回值判断不出来。
4. `slot-retry-count:a` 每跑一轮扣 2 次，约三轮后归 0，LK 随即把 A 槽标成不可引导并回退 B 槽 Android。经 loader 起 iOS 不写成功引导记录，`slot-successful:a` 始终是 `no`，计数器一路递减，与 panic 无关。`set_active a` 把计数重置为 7 并把 `slot-unbootable:a` 清回 `no`。起轮前先读 `slot-retry-count:a`，低于 3 时执行 `set_active a`。`cycle.py` 每 2 轮经 `reboot-lk.py` 进 LK 做一次 `set_active a` 并读回 7；`round-run.py` 只在设备处于 LK 时读这个计数，低于 3 时重置。
5. 安卓侧点屏不能用 `input keyevent`。adb shell 缺 `INJECT_EVENTS`，会抛 `SecurityException`；用 `svc power stayon usb` 能把屏幕点亮。`screencap` 全黑先看 `mWakefulness` 与 `Display State`，两者都是 OFF 时黑屏来自休眠，与面板无关。
6. `reboot-lk.py` 的 `--payload` 必须是 prepare 载荷。误传轮次载荷时，工具 `stage` 后把内核又起了一次并停在 `hung-held`，报 `Probe return timed out; reboot not sent`；那次引导的日志是 `Process 1 exec of /sbin/launchd failed, errno 2`（历史启动路径缺少常驻系统盘）。
7. `boot_a` 分区尾部残留 `AVBf` 页脚且偏移 `0x022b9000` 的 `AVB0` 块被覆盖时，LK 执行 `set_active a && reboot` 会在第 1 次引导立即将 `boot_a` 标为 `unbootable` 并回退 B 槽 Android：
   - 高通 ABL（`LinuxLoader.efi`）的 `LoadImageAndAuthVB2`（`0x3a6d4`）调用 `avb_slot_verify`（`0x43af0`）与 `load_and_verify_vbmeta`（`0x44374`）校验链式分区 `"boot_a"`。
   - `boot_a` 分区总长 96 MiB（`0x06000000`），分区末尾 `0x05ffffc0` 处的 64 字节 `AVBf` 页脚指向 `vbmeta_offset = 0x022b9000`（34.72 MiB）、`vbmeta_size = 0x00000980`。
   - 曾写入过超过 `34.72 MiB` 的镜像（如 51.3 MiB 旧镜像）覆盖了 `0x022b9000` 处的 `"AVB0"` 魔数，而后续刷入 23 MiB 的 `boot-a-ios.img` 仅覆盖 `[0, 0x01700000)`，保留了 `0x022b9000` 的非 AVB 数据与 `0x05ffffc0` 的 `AVBf` 页脚。
   - `avb_vbmeta_image_verify`（`0x44744`）在 `0x022b9000` 未读到 `"AVB0"`，返回 `2`（`AVB_VBMETA_VERIFY_RESULT_INVALID_VBMETA_HEADER`）；在跳转表 `0x44758` 中，返回码 `4`（哈希不匹配）与 `5`（签名不匹配）在解锁状态下按 `allow_verification_error` 放行，而返回码 `2` 直接跳转 `0x44998` 打印 `"boot_a: Data does not look like a vbmeta image.\n"` 并无条件返回 `6`（`AVB_SLOT_VERIFY_RESULT_ERROR_INVALID_METADATA`）。
   - `LoadImageAndAuthVB2`（`0x3af3c`）仅放行位掩码 `0x39`（返回码 `{0, 3, 4, 5}`），遇到返回码 `6` 立即跳转 `0x3aa3c` 调用 `HandleActiveSlotUnbootable(0)`（`0x1cd34`），在第 1 次尝试即将 `boot_a` 置为 `unbootable=1`（`attrs=0x00b2000000000000`，`retries=6`）并切回 B 槽启动 Android。
   - 此外，`LoadImageAndAuthVB2`（`0x3be58`）在无 AVB 属性时检查 `boot.img` 头部偏移 `0x2c` 的 `os_version`，若为 `0` 则报 `"Boot image header OS version == 0 \n"` 拒绝启动；`reseal-loader-img.py` 必须向 `mkbootimg.py` 传入 `--os_version 15.0.0 --os_patch_level 2026-02`（写入 `0x1e0001a2`），且 `boot_a` 偏移 `0x022b9000` 与 `0x05ffffc0` 必须保持有效 `AVB0`／`AVBf` 配对。
8. 重刷运行中的 standalone 前，先执行一次 `fastboot -s xnuloader oem stop`，等待内核真实返回，并核对 `result`、次级核心停止与 UFS 控制器归还日志。2026-11-08 实测旧内核正常响应 stop，随后得到 `idle 0 0`、`cores_off` 和 `ufs: the kernel came back`；保存日志并清理常驻启动卷后，可用 prepare 载荷进入 LK。旧 loader 的 standalone 入口会在内核运行期间误报 `idle`，旧 `oem recovery` 还会强制修改资源状态，不能据其返回值执行刷写；新 loader 已修正状态更新和资源检查。`oem log` 会覆盖 staging，完整内核日志须先取回。返回后的 recovery 判定、屏幕核对和 GPU 冷复位要求见[设备测试手册](device-test-playbook.md#6-故障定位与恢复)。
9. standalone 将 4 MiB 启动卷嵌入 `rdimage`，由 `init` 挂载 UFS `darwin` 系统卷并切根；2026-11-08 临时启动已验证切根、Cryptex 挂载、数据盘恢复与锁屏显示，见[根文件系统说明](../analysis/rootfs-strategy.md)。封装自包含 `boot-a-ios.img` 必须使用 `mkstandalone.py` 生成的未压缩 `XNUP` 容器 `out/standalone-payload.bin`，直接传给 `reseal-loader-img.py`：
   - 第一步：`python3 hackios-xnu-kernel/xnuloader/mkstandalone.py -k hackios-xnu-kernel/out/xnu12377-st4.bin -r hackios-xnu-kernel/out/ios26-resume/bbmetal-device/root.apfs --boot-image hackios-xnu-userland/userland/flashboot.apfs -o hackios-xnu-kernel/out/standalone-payload.bin`（内部调用 `mkpayload.py` 将 `loader.efi`、`kernel`、`ramdisk`、`rdimage`、`cmdline` 打包为未压缩 `XNUP` 容器 `standalone-payload.bin`）。
   - 第二步：`python3 hackios-xnu-kernel/tools/reseal-loader-img.py hackios-xnu-kernel/out/handoff-loader-v19.img hackios-xnu-kernel/out/standalone-payload.bin -o hackios-xnu-kernel/out/boot-a-ios.img`（将 `BootShim + FD + standalone-payload.bin` 整体经 zlib level 9 压缩并封装为 `boot-a-ios.img`）。
   - 严禁将 `standalone-payload.bin.lz4` 直接传给 `reseal-loader-img.py`（头部为 `LZ4S`，非 `XNUP`），也严禁再用 `mkpayload.py` 把 `payload.lz4=` 二次包装进外层 `XNUP` 容器（`parse_payload()` 只解析顶层 `kernel` 与 `ramdisk` 条目，遇到 `payload.lz4` 条目会报 `no kernel in payload: entering Fastboot debug mode`）。
10. `xnuloader` 空闲界面 120 秒超时切槽（`xnuloader/loader_06a_screen_ui.inc` 的 `boot_fallback_check()`）：旧逻辑在 loader 空闲界面连续 120 秒未收到主机 fastboot 命令时，会执行 `slot_set_active_other()` 切换活动槽位并重启进 Android；当第 9 条导致 `xnuloader` 未能自动启动 iOS 时，设备会在 120 秒后自动切回 B 槽重启进 Android。`boot_fallback_check()` 现已改为仅刷新 `host_last_cmd` 保持在当前槽位驻留。
11. `tools/k90auto/package.py` 默认从 `hackios-xnu-userland/userland/` 读取用户态源码编译注入库，并基于 `hackios-xnu-userland/userland/root/` 打包 `root.apfs`。
12. `hackios-xnu-kernel/xnu26/build-macos.sh` 默认在 `$XNU26_ROOT/out/xnu12377-cmd` 目录编译内核，而仓库跟踪的内核增量源码位于 `$XNU26_ROOT/xnu/files/`。已在 `xnu26/build-macos.sh` 开头加入自动同步逻辑，将 `xnu/files/` 下变更的文件复制并更新时间戳到 `out/xnu12377-cmd/`，防止修改 `xnu/files/` 后编出旧版内核对象。

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

- 起轮前要求 `fastboot devices` 精确列出一个 `xnuloader`、`product` 为 `xnuloader`、`result` 完整回答为 `idle` 或 `idle 0 0`，且 `ramdisk-state` 为 `idle 0 0 <window>`。`window` 可以是尚未分配的 `0`；非零状态字段、重复回答或命令失败均停止。
- loader 未枚举即写入本地 `cycle-stop.json` 并停止；设备恢复由独立操作执行。
- 每 2 轮做一次检查点（§5.3），驻留 loader 的 build-id 不含 `a48c7fb`（v16、v17 的 loader）时也先做检查点。
- 载荷、辅助盘、启动卷的身份由 `make-payload.py`、`run-auto.py` 按 `manifest.json` 的 SHA-256 核对，不符就拒跑。实际载荷参数固定包含 `rootdev=md0 root_apfs=ufs_darwin ufs=2 ufs_native=1`。上传顺序为 payload、`oem ramdisk`、启动卷；运行前核对接收长度与内存窗口。
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
