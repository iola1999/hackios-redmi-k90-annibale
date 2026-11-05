# USB 恢复与减少人工按键的调试经验

## 1. 适用范围与检查顺序

本篇用于排查 USB 命令超时、内核停止及重启后的身份变化。先核对当前执行环境和主机实际返回，再保存可读日志、选择软件恢复入口，并检查复位后的身份。软件恢复无法完成，再请求用户按键。具体命令见[真机调试手册](../plan/device-test-playbook.md)，各引导目标之间的切换见[引导目标切换 SOP](../plan/device-boot-target-sop.md)。

下文的 A／B 槽按本项目脚本的槽位假设书写：Android 在 B 槽、loader 写在 A 槽的 boot 分区，`cycle.py`、`reboot-lk.py`、`recover-loader.py` 固定执行 `set_active a`。Android 在 A 槽的设备需要对调 A／B 并修改这些脚本，见 SOP 开头。

## 2. 先区分主机等待、USB 协议和内核状态

一次主机超时只能确认该请求未在限时内完成。主机进程退出后，设备上的 DMA 请求仍可能存在；再次启动 fastboot 客户端也会继续使用同一个设备端状态。记录命令、耗时、退出码、stdout、stderr、枚举身份及最后成功动作，再判断下一步。`getvar` 经常把正文写入 stderr，检查必须合并两个输出流；退出码之外还要检查 `FAILED` 和预期字段。

USB 枚举确认描述符可见；短命令应答确认协议可达；日志和故障寄存器用于判断内核执行。`hung-held` 是 loader 对内核及资源状态的报告，该状态下仍可有可用的 USB 命令循环。屏幕停止更新也需要按上述层次检查。

GPU 初始化可能已经把内存交给设备或安全固件。日志 `GPU probe requires host cold reset before reusing kernel memory` 对应资源保留与内核停止路径，该函数本身没有 USB 操作。应保存现场并复位，继续保护这些页。`oem stop` 和 `loader_return_after` 受内核所处阶段及资源状态限制，无法保证取消早期停滞或允许重用内存。

`fastboot reboot` 同样需要设备接收并分派 USB 命令。annibale 分支先尝试回复，再调用 PSCI_SYSTEM_RESET；回复失败后仍可能执行复位，最终结果要检查 USB 断开、重新枚举和新身份。loader 停在命令接收之前时，继续发送 reboot 也可能无效。

## 3. USB 请求生命周期的约束

设备提交 IN 传输后，需要持续记录缓冲所有权。主机放弃传输或等待超时，设备仍可能保留在途请求；缺少匹配的终止通知会阻止后续应答。恢复逻辑需要同时处理等待预算、完成事件和缓冲释放条件。

提交 `7160d4d` 的生产实现位于 [loader_06_usb_entry.inc](../../hackios-xnu-kernel/xnuloader/loader_06_usb_entry.inc)，关键约束如下。

- 所有等待都有预算：内核运行、资源保留或固件故障状态为 3 秒，普通命令循环为 10 秒。软件循环的预算仍依赖固件调用能返回。
- 每笔陈旧 IN 请求最多申请一次 abort。abort 返回只说明调用返回；释放缓冲必须取得经过校验的终止通知。
- IN 与 OUT 使用统一事件校验。等待应答期间收到的 OUT 命令完成事件要保留并交付一次，复位命令才能继续执行。
- 空闲命令接收与数据传输分开记录。空闲等待超时后，后续完整命令仍可交付；已经放弃的数据传输迟到后，只结束原请求，不交付旧数据。
- 无法确认终止或结构异常的请求继续保留缓冲，复位后再开始新的生命周期。恢复逻辑不得仅因等待结束就重新使用设备可能仍在访问的内存。

恢复逻辑应复用统一的事件处理。多个事件循环分别消费同一事件源，会增加完成事件遗漏和重复释放的机会；测试需要覆盖事件交错和失败后的下一条有效请求。

## 4. 按当前环境选择恢复方式

同一设备只允许一个任务发送命令。旁路分析通过已保存材料进行；多个 fastboot／ADB 调用应串行执行。每次环境切换后重新枚举，设备参数使用 `ANDROID_SERIAL`，驻留 loader 使用 `xnuloader`。

| 当前观测 | 下一步 | 成功条件 |
|---|---|---|
| `xnuloader` 枚举且短查询有应答 | 按实际 `result` 保存日志；需要恢复则执行 loader reboot | 观察断开及重新枚举，核对 product、完整 build-id 和 `idle` |
| `xnuloader` 枚举但短查询超时 | 停止追加日志／截图传输；确认没有遗留主机客户端后，在有界等待内尝试 reboot | 设备发生复位并读取到新身份；主机收到 OKAY 只覆盖命令应答 |
| 驻留 loader 可达，需要进入 LK，且状态与 RAM 符合 `reboot-lk.py` 前置条件 | 使用 `tools/k90auto/reboot-lk.py` 准备并读回目标字段，再调用 loader reboot | 实际读取到指定设备的 LK product 与槽位；用法见 [k90auto 说明 §5](../../tools/k90auto/README.md#5-软件进入-lk-fastboot) |
| LK fastboot 可达 | 核对 product、current-slot 与 A/B 槽状态，按实验目标选择槽位 | 启动后出现预期 loader 身份及状态 |
| Android 已启动且 ADB 为 `device` | 核对机型与 `ro.boot.slot_suffix`，通过 ADB reboot bootloader 返回 LK | LK 身份可读，再决定是否恢复 A 槽 |
| 软件入口不可达，或可达入口的恢复动作失败 | 保存已有输出，并请用户按电源键＋音量下进入 FASTBOOT | 用户确认画面后，主机重新枚举并查询身份 |
| `adb devices`、`fastboot devices`、`ioreg -p IOUSB` 三处同时查不到设备 | 停止一切命令尝试，请用户长按电源键冷启 | 主机重新枚举；下一轮前先读 `slot-retry-count:a`，不足 3 时先 `set_active a` |
| `adb devices` 列出一行但序列号为空 | 按未枚举处理，只轮询，不发任何命令 | 序列号能原样读出来，才算枚举 |

复位后同时检查 fastboot 与 ADB 枚举。A 槽连续实验启动未标记成功，重试次数耗尽后可能回退到 B 槽 Android。ADB 可用就通过 reboot bootloader 返回 LK，检查 `slot-successful:a`、`slot-unbootable:a` 和 `slot-retry-count:a`，核对 A 槽镜像后再决定是否执行 `set_active a`。

恢复目标要写清楚：回到 loader idle 可以使用已验证的普通 reboot；进入 LK 需要对应的目标切换入口。请求按键前，记录当前状态下的软件恢复尝试及返回。一次调用被中止、空 stdout、真正超时和 USB 断开分别记录。同一故障尚在等待用户操作时，保留一个明确请求即可；收到新的画面或状态反馈，先重新枚举，再决定后续动作。

设备整个从 USB 上消失与「枚举了但不答」的处置不同。2026-10-29 一天内连续起轮十几轮后出现过一次：`adb devices` 曾短暂列出一台但序列号为空，`adb reboot bootloader` 回答 `unknown command`，随后两分钟内 `adb devices` 与 `fastboot devices` 都是空，`ioreg -p IOUSB` 与 `system_profiler SPUSBDataType` 也查不到 `annibale`。这种形态软件侧没有恢复路径，反复发命令只会增加主机残留客户端，唯一做法是请用户长按电源键冷启。由此定下的无人值守约束见 [AGENTS.md](../../AGENTS.md) 第 5 节。

## 5. 把恢复纳入每轮验收

先验证调试通道，再执行可能使内核停止的实验。验收覆盖正常传输、异常后的下一条请求，以及复位后的真实身份。

| 检查场景 | 验收条件 |
|---|---|
| 连续身份查询与空闲后的首条查询 | 均能返回预期字段，记录实际耗时 |
| 完整日志或截图上传 | 实际文件长度与预期一致 |
| 主机中止上传 | 经过配置的等待预算后，下一条查询及后续恢复操作仍可执行 |
| 内核停止并保留资源 | 保存可读日志，检查 loader 查询与 reboot 是否可用 |
| 软件复位 | 先观察 USB 断开，再确认重新枚举、完整 build-id 和预期状态 |
| 复位后进入 Android | 核对 ADB 身份，验证返回 LK 及选择实验槽位的流程 |

每次实验保存输入哈希、启动参数、最后成功阶段、首次失败动作，以及复位后的真实身份。主机模型需要检查错误后的下一条有效命令，真机继续验证固件响应与时序。仅有代码修改、构建成功或设备枚举，恢复验收仍未完成。

上传等待预算应按镜像长度与实测耗时配置。普通采集中止传输会改变设备状态，不能依靠不断杀掉客户端来缩短每轮等待；故障注入应单独安排，并保留恢复入口。已有请求持续无应答后，应切换到身份检查和恢复判断。固件同步调用停滞、完成通知缺失或结构异常、loader CPU／共享硬件受损等情况仍可能需要外部复位。

## 6. 独立双系统引导（boot_a）的故障自愈与免按键恢复

2026-11-06 在真机验证 `boot_a` 独立双系统引导（21 MB LZ4 压缩载荷封装进 `hackios-xnu-kernel/out/boot-a-ios.img`，开机由 `rdfile` 从 UFS `darwin` 分区直读 5.9 GB 系统盘）时，连续排查并解决了五项影响启动耗时与无人值守恢复的问题。

### 6.1 启动早期 UFS 刷屏与读取耗时

- 现象：选择启动系统后屏幕连续刷屏 `ufs: firmware table ...` 与分区信息十余秒。
- 根因：[`loader_02_platform_cpu_ufs_survey.inc`](../../hackios-xnu-kernel/xnuloader/loader_02_platform_cpu_ufs_survey.inc) 的 `inspect_storage()` 默认遍历全部 GPT 分区并对 `bluetooth`、`abl`、`aop`、`xbl`、`tz`、`hyp`、`dsp`、`modem` 共约 290 MB 分区做 FNV-1a 校验；[`loader_06_usb_entry.inc`](../../hackios-xnu-kernel/xnuloader/loader_06_usb_entry.inc) 的 `efi_main()` 在 `block_start()` 与 `inspect_storage()` 之后才打开 `screen_quiet = 1`，导致 UEFI 文本控制台逐行滚屏。
- 修复：`efi_main()` 在 `wdt_arm()` 后立即置 `screen_quiet = 1`；`inspect_storage()` 仅在命令行显式传入 `ufs_probe=1` 时执行全量分区 FNV-1a 校验，日常启动只定位 `darwin` 分区。修复后 5.9 GB `darwin` 分区经 `rdfile_load()` 读入 RAM 实测耗时 1412 毫秒。

### 6.2 启动菜单音量键与电源键 SPMI 直读

- 现象：`HACKIOS K90 BOOT MENU` 界面按音量加、音量减、电源键均无响应。
- 根因：Mu-Silicium 的 `ButtonsDxe` 在 `annibale` 上未把 PMIC 实体按键边沿转换为 `ST->con_in->read_key_stroke` 输入事件。
- 修复：在 [`loader_06a_screen_ui.inc`](../../hackios-xnu-kernel/xnuloader/loader_06a_screen_ui.inc) 中实现 SM8750 SPMI v7 仲裁器直读（通道表 `0x0c400000`、观察者读口 `0x0c440000`），由 `spmi_buttons_init()` 扫描并绑定 PMK8550 `pon_hlos`（`ppid 0x013`，实测通道 581，偏移 `0x10` bit 7 电源键、bit 6 音量减）与 PM8550 `GPIO6`（`ppid 0x18d`，实测通道 610，偏移 `0x10` bit 0 低有效音量加），含双采样消抖与初始按下态过滤。用户按键交互后菜单倒计时立即暂停，等待电源键确认。

### 6.3 停在 `SYSTEM READY` 与 3 分钟看门狗自动重启

- 现象一：独立引导进度条走完停在 `SYSTEM READY`，约 3 分钟后手机自动重启。
- 根因一：通过 `fastboot -s xnuloader oem log` 拉取 3602 行完整日志定位到两处原因：
  1. 独立调用 [`tools/k90auto/package.py`](../../tools/k90auto/package.py) 打包根盘时未传 `PAYLOAD_PROGRAMS`，且 `hackios-xnu-kernel/userland/root/bin/var_store` 与 `userland/root/lib/libredwood*.dylib` 缺少 ad-hoc 签名；`launchd.ios` 完成早期启动 0.5 秒后拉起 `/redwood/bin/var_store` 触发 `userspace panic: unexpected exec of non-platform binary: /redwood/bin/var_store: com.redwood.varstore [48]`，此时 `SpringBoard` 尚未绘制首帧。
  2. 内核 panic 经 [`loader_return.c`](../../hackios-xnu-kernel/xnu/files/osfmk/arm64/loader_return.c) 调用 [`adreno8.c`](../../hackios-xnu-kernel/xnu/files/bsd/dev/adreno8.c) 的 `adreno8_quiesce()`，因 `adreno8_memory_retained()` 为真打印 `adreno8: GPU probe requires host cold reset before reusing kernel memory` 并停在 `wfe`；Core 0 在 [`loader_03_ufs_block_watch.inc`](../../hackios-xnu-kernel/xnuloader/loader_03_ufs_block_watch.inc) 等待 `SILENCE_SECONDS`（50 秒）无心跳后判定 `hung-held` 并进入 `usb_command_loop()`；随后 [`loader_04_fault_payload_nvram.inc`](../../hackios-xnu-kernel/xnuloader/loader_04_fault_payload_nvram.inc) 的高通 Haven 虚拟看门狗（SMC `0x86000007`）在主机静默满 `HOST_SILENCE_SECONDS`（180 秒）后停止喂狗，30 秒咬合超时触发硬件复位。
- 现象二：修复签名后，进度条走满 `5643 / 5643 MB` 且顶部白点仍在左右移动，但屏幕长时间停在 `SYSTEM READY`（`MiniIOSurface: 0 surfaces`）。
- 根因二：
  1. [`hackios-xnu-kernel/userland/build.sh`](../../hackios-xnu-userland/userland/build.sh) 追加 `var.skel.extra` 时包含与基础模板重复的 `/private/var/mobile/Containers`、`/private/var/mobile/Containers/Data`、`/private/var/mobile/Containers/Shared` 目录项；[`init.c`](../../hackios-xnu-userland/userland/src/init.c) 的 `mount_writable()` 遇到已存在目录返回 `EEXIST` 并提前终止，跳过了第 157～158 行 `/private/var/keybags/persona.kb` 的创建，导致 `usermanagerd` 反复崩溃退出、`SpringBoard` 无法完成初始化。
  2. [`loader_dsu.inc`](../../hackios-xnu-kernel/xnuloader/loader_dsu.inc) 的 `dsu_find()` 将 8 GiB 的只读 `darwin` 分区优先返回给 `dsu_store_open()`，因容量不足 12 GiB 跳过创建 `/dev/rufs_dsu_store`，导致 `var_store` 无法读取 `darwin_var` 分区起始处的持久化归档。
  3. 批量重签 `userland/root/bin/` 时未携带 `.entitlements`，导致 `input26-service` 丢失 `com.apple.private.hid.client.event-dispatch` 权限退出。
- 修复：
  1. `userland/build.sh` 合并 `var.skel.extra` 时过滤已存在的 `d\t` 目录项，确保 `/private/var/keybags/persona.kb` 创建成功。
  2. 拆分 `dsu_find_gsi()` 与 `dsu_find()`，`dsu_store_open()` 在无 Android DSU 分区时回退映射 `darwin_var` 的前 4 GiB（`dsu_store_at = 0`）为 `dsu_store`。
  3. 为 `input26-service`、`store_test`、`battery_test`、`keychain_test`、`wifipw_test` 按各自 `.entitlements` 重签，并在 [`mkstandalone.py`](../../hackios-xnu-kernel/xnuloader/mkstandalone.py) 默认启动参数中加入 `epoch=` 时间戳。

### 6.4 LUN 4 Vendor GUID 路径识别与槽位属性同步

- 现象：启动日志报 `slot: maintaining current Slot c`、`slot: LUN 4 not found`，或在 `attr_a=0x37`、`attr_b=0x7a` 时误判 `loader_slot=b`。
- 根因：`UFSDxe` 为 UFS 逻辑单元生成的设备路径是 Vendor GUID 节点 `1.4[85193fd3...]`，不含 messaging UFS 子类型 `0x19`，[`loader_03_ufs_block_watch.inc`](../../hackios-xnu-kernel/xnuloader/loader_03_ufs_block_watch.inc) 的 `device_path_print()` 返回 `lun = 0xff`；[`loader_01_base_log_dt.inc`](../../hackios-xnu-kernel/xnuloader/loader_01_base_log_dt.inc) 的 `print()` 仅支持 `%s`、`%x`、`%d`，不支持 `%c`；`slot_detect()` 原先按 `(attr >> 48) & 0x0f` 比较优先级时把 bit 3（`tries_remaining` 最低位）算入其中，导致 `0x37 & 0x0f = 7` 低于 `0x7a & 0x0f = 10`。
- 修复：[`loader_06a_screen_ui.inc`](../../hackios-xnu-kernel/xnuloader/loader_06a_screen_ui.inc) 的 `lun4_get_bio()` 改为先查 `boot_a` 分区所属 `unit`（默认 4），再匹配 `block_shared.part[i].unit == target_unit` 的整盘 `BlockIo` 句柄；所有槽位日志格式串统一改用 `%s`；`slot_detect()` 改为检查 bit 2（`0x04`，`active` 位）与 bit 7（`0x80`，`unbootable` 位）；`slot_maintain_current()` 将活动槽属性字节写为 `0x6f`（`priority=3, active=1, tries=7, successful=1, unbootable=0`），同时将非活动槽属性字节写为 `0x6a`（`priority=2, active=0, tries=5, successful=1, unbootable=0`），不置 bit 7（`unbootable`）。

### 6.5 无人值守免按键拦截、屏幕 Panic 提示与四层恢复步骤

- 根因分析：旧版 `efi_main()` 在启动菜单结束后才调用 `usb_start()`，macOS 主机完成 USB 枚举需约 1.8 秒，而 `rdfile_load()`（1.41 秒）加 `EARLY_BOOT`（45 毫秒）合计仅 1.46 秒；等主机枚举出 `xnuloader` 时内核已进入 `adreno8_init()`，错过 `EARLY_BOOT` 末尾 [`loader_return.c`](../../hackios-xnu-kernel/xnu/files/osfmk/arm64/loader_return.c) `loader_stop_poll_init` 的干净退回窗口。内核进入 `adreno8_init()` 或 `hung-held` 后，`lc_cmd_denied()` 又会拒绝 `download:`、`oem flash_boot` 和 `oem android`。
- 四层恢复与屏幕故障提示实现（[`loader_06_usb_entry.inc`](../../hackios-xnu-kernel/xnuloader/loader_06_usb_entry.inc)、[`loader_06a_screen_ui.inc`](../../hackios-xnu-kernel/xnuloader/loader_06a_screen_ui.inc)）：
  1. **启动菜单前置 USB 与远程打断**：`efi_main()` 在 `ui_boot_menu()` 之前调用 `usb_start()`，菜单倒计时设为 5 秒并在循环内轮询 `usb_poll_command()`；主机在倒计时期间发送 `fastboot -s xnuloader oem recovery` 可立即打断自动引导并进入 `[3] FASTBOOT USB DIAGNOSTICS`。
  2. **全状态单次强制恢复命令 `oem recovery`**：`fb_command()` 在 `lc_cmd_denied()` 之前响应 `oem recovery`（调用 `slot_unlock_held_recovery()`），在 `annibale`（`skip_ufs_arbitration = 1`）上置 `other_cpu_done = 1` 并调用 `clean_dcache()` 刷至 PoC，清零 `active_watch`／`kernel_resources_held`／`firmware_fault`；当 `running_live != NULL` 时置 `recovery_pending_after_return = 1`，待 `run_kernel()` 退出后再恢复 UEFI 中断掩码（`held_group1`、`held_daif`）。无论设备处于菜单、内核运行态还是 `hung-held` 态，单次执行 `fastboot -s xnuloader oem recovery` 即可回到 `result=idle` 并刷写新镜像。
  3. **独立引导异常退回自动解锁与红屏 Panic 横幅（`boot_fallback_enter()`、`ui_draw_fault_banner()`）**：`run_kernel(0, 0)` 因 panic、同步异常或 50 秒心跳超时返回 `efi_main()` 时，自动调用 `boot_fallback_enter()` 解除 `held` 锁（保留 `out_buf` 中的完整内核日志供 `oem log` 拉取），同时由 `ui_draw_fault_banner()` 向 `0xfc800000` 与 `0xfd400000` 双显示缓冲绘制红底白字 `KERNEL FAULT / HUNG - FASTBOOT RECOVERY` 横幅、故障状态、最后一条 `panic` 行和末尾 14 行内核日志，直观区分「仍在启动」与「已崩溃／卡死」。
  4. **120 秒无主机自动回退 Android（`boot_fallback_check()`）**：进入 `BOOT FALLBACK` 后若 120 秒内没有收到主机 USB 命令，`usb_command_loop()` 自动调用 `slot_set_active_other()` 切换活动槽到 B 槽（Android）并重启，防止脱离电脑时发生看门狗无限重启循环。

