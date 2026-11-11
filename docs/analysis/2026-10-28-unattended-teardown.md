# 无人值守收尾：从 `oem stop` 到 idle loader 的实测与人工边界

本篇回答两件事：现有收尾路径是否需要人按键，哪些状态人必须到场。判断依据同时给出源码位置和实测数据，源码行号固定于 `hackios-xnu-kernel` 提交 `da3d02c`（内核侧 `xnu/files/osfmk/arm64/loader_return.c`、`xnu/files/bsd/dev/adreno8.c`，loader 侧 `xnuloader/`）。命令与日志读取顺序见[真机手册](../plan/device-test-playbook.md)，USB 层面的恢复规则见[USB 恢复经验](2026-10-25-usb-recovery-lessons.md)。

设备停机与资源回收的后续事项见[外设与电源待办](../backlog/platform.md)。

下文的 A／B 槽按本项目脚本的槽位假设书写：Android 在 B 槽、loader 写在 A 槽的 boot 分区，`cycle.py`、`reboot-lk.py`、`recover-loader.py` 固定执行 `set_active a`。Android 在 A 槽的设备需要对调 A／B 并修改这些脚本，见[引导目标切换 SOP](../plan/device-boot-target-sop.md)开头。

## 1. 结论

- 收尾全程不需要人按键：`oem stop` 后约 50 秒 loader 判 `hung-held`，主机保存日志并 `reboot`，复位直接回到 A 槽 loader；复位落到 B 槽 Android 时，`recover-loader.py` 经 ADB 回到 LK、`set_active a`、再回到 loader，`result` 为 `idle`、`ramdisk-state` 为空。2026-10-28 的收尾单轮实测走完了落到 Android 再自动恢复的整条路径。
- 2026-10-27 的 16 轮实测单轮收尾 67～70 秒，分段见第 3 节。
- 那 50 秒是 loader 对内核心跳的静默预算，内核在这段时间停在停止路径的 park 自旋上。`oem stop` 后 2 秒取到的快照里已经同时有 host-stop banner 和 `adreno8: GPU probe requires host cold reset before reusing kernel memory`，此后日志没有新内容。

## 2. 判断依据：源码链

1. 主机 `oem stop`：loader 把 `running_live->stop` 置 1 并回 OKAY（`xnuloader/loader_06_usb_entry.inc` 的 `oem stop` 分支，`lc_stop_action` 在 live 时返回 `LC_STOP_NOTIFY`），实测应答 0.001 秒返回。
2. 内核每秒一次的 `loader_stop_poll`（`loader_return.c` L521）看到 stop：打印 `--- the host asked for the end of the run: back to the loader ---`（L526），依次调用 `annibale_var_save_on_return()`、`annibale_adreno_stop()`（L531）、`annibale_wifi_stop()`、`annibale_adsp_stop()`，然后 `loader_return()`（L534）。
3. 返回路径进入 `adreno8_quiesce()`（`adreno8.c` L471）：`adreno8_reset_required || adreno8_memory_retained()` 为真时打印「GPU probe requires host cold reset before reusing kernel memory」，随后 `for (;;) wfe`（L476-L481），函数不返回。`adreno8=23 adreno8_keep=1` 的载荷每轮都满足这个条件。
4. 内核不再自增心跳。心跳由每 10 秒的 `hv_wdt_pet` 加一（`loader_return.c` L556、L613-L632），park 之后不再执行。
5. loader 的观察循环在 `seconds_since(last_beat_at) >= SILENCE_SECONDS` 时判 `OTHER_CPU_HUNG`（`xnuloader/loader_03_ufs_block_watch.inc` L852-L858；阈值 `SILENCE_SECONDS 50` 在 `loader_02_platform_cpu_ufs_survey.inc` L410）。资源仍被持有时结果记为 `hung-held`（`loader_05_layout_run_kernel.inc` L935-L941）。
6. held 状态下 `reboot` 仍然放行（`loader_06_usb_entry.inc` L716）：annibale 走 `psci_reset_attempt()`，只有该调用返回才写 `reset-failed`（同处 L719-L727）。held 状态下被拒的是 `oem ramdisk`、`download:`、`oem run` 等写入口（`loader_01_base_log_dt.inc` 的 `lc_blocked_cmd`），查询、日志、截图、`reboot` 不在其中。
7. 复位后 `run-auto.py` 轮询到 loader 重新应答 `idle` 且 RAM 系统盘为空，记为回到 loader；落到 B 槽 Android 时，`run-queue.sh` 在该轮之后调 `recover-loader.py` 恢复 A 槽，`cycle.py` 在下一次起轮前发现设备在 Android 时调用它。

## 3. 判断依据：实测

16 轮 `commands.jsonl` 的时间差（主机单调时钟，同一轮内相对起点）：

| 段 | 观测值 | 轮数 |
|---|---|---|
| `oem stop` → 读到 `hung-held` | 50.5～51.5 秒 | 16 |
| 读到 `hung-held` → 发出 `reboot` | 0.1 秒 | 16 |
| `reboot` → 读到 `result: idle` | 16.8～17.9 秒 | 12 |
| `reboot` → 落到 B 槽 Android | 1.1～22.1 秒 | 4 |

落到 Android 的原因是 A 槽重试次数耗尽（`slot-retry-count:a: 0`、`slot-unbootable:a: yes`），见 [SOP §4](../plan/device-boot-target-sop.md#4-陷阱均为实测) 第 4 条。其中 2 轮的恢复在 `adb devices` 还没有设备时断言退出，`recover-loader.py` 加了 `ADB_WAIT` 等待后能自动恢复（第 5 节）。原始记录在 Git 忽略的 `docs/progress/evidence/k90auto/` 下（`kernel-12377-attr-bbmetal8`～`bbmetal25` 与 `kernel-12377-attr-teardown-a`）。

## 4. 怎样区分「内核主动 park」与「驱动卡住」

两种情况的观测完全一样：心跳停下、50 秒后落到 `hung-held`。loader 的 `hung` 状态本身只表示判定内核无响应，区分只能靠停止后的打印（取法见[真机手册第 5 节](../plan/device-test-playbook.md#5-读取日志和截图)），分三档：

- 没有 host-stop banner（`--- the host asked for the end of the run: back to the loader ---`）：抓取不完整与内核未执行停止回调两种情况无法区分。
- 有 banner、没有冷复位打印：内核主动 park 未确证。
- 出现 `requires host cold reset` 打印：park 确证。典型样子是 banner 之后紧跟 `adreno8: secure service closed; all pages retained until cold reset` 与 `GPU probe requires host cold reset before reusing kernel memory`，HUNG 快照以 `== END OF LOG ==` 结束。

分类以实际取回内容为准，截断就记为截断。

时间关系可以作旁证，不能单独定论：心跳周期 10 秒，若内核在 stop 之后又运行一段才卡死，`hung-held` 会落在 stop 之后 40～50 秒的任意位置；16 轮全部落在 50.5～51.5 秒，与「停止回调在 1 秒内执行完并进入 park」一致。

取日志的顺序决定能不能看到这两行：判到 `hung-held` 后先执行 `oem log` 会走 `compose_logs(NULL, 0)`，把 HUNG 分支预先组装好的快照覆盖成 loader 自己的 32,767 字节串口日志（`log_buf[32768]`，`loader_01_base_log_dt.inc` L86）。`run-auto.py` 判到 `hung-held` 后先 `get_staged` 取快照（`47faef3`），完整快照约 740 KB。

## 5. 只能靠人工离开的状态

| 状态 | 现象 | 现在的处理 | 剩余做法 |
|---|---|---|---|
| `result: running` 长时间不变 | `oem stop` 只置标志，内核的 `loader_stop_poll` 每秒轮询一次；该线程被挡住就永远看不到标志 | `run-auto.py` 在 stop 之后按秒轮询状态（`K90_STOP_WAIT`，默认 70 秒），仍为 running 时保存 `running.log` 并以非零退出，不发复位 | 先补发一次 `oem stop` 并做两次停止后补采；日志里没有 host-stop banner 且心跳仍在增长，判定轮询线程被挡，记录后请人长按电源键。软件恢复需要改内核侧轮询的位置（中断上下文或更高优先级） |
| `result: reset-failed` | `psci_reset_attempt()` 返回了错误，loader 保留 USB 循环 | 尚未遇到过 | 主机对同一状态重试 `reboot` 两次；仍失败则保存日志并请人长按电源键 |
| USB 枚举在、所有命令超时 | 陈旧 IN 未取得终止通知，缓冲区一直被占 | 见 [USB 恢复经验](2026-10-25-usb-recovery-lessons.md) 第 4 节 | 有界等待后重试一次 `reboot`；两次无应答再请人 |
| 复位落到 B 槽 Android 且 adb 未枚举 | 复位后 adbd 需要一段时间才应答 | `recover-loader.py` 在 40 秒内轮询 `adb devices`（`ADB_WAIT`），实测生效 | 仍等不到再请人 |
| A 槽重试次数耗尽 | `slot-retry-count:a: 0`、`slot-unbootable:a: yes`，复位后进 Android | 恢复后 `set_active a` 把重试次数复位为 7；`cycle.py` 每 2 轮经 LK 做一次 | 无 |
| 固件故障分支（`firmware_fault`） | 状态名与 held 同时出现，写入口全部拒绝 | 尚未真机覆盖 | 按 held 处理：保存日志、`reboot`；仍不通再请人 |

`recover-loader.py` 对 `getvar build-id` 只记录、不断言，`run-auto.py` 也只把它写进 `reboot.json`。用 `BUILD_ID` 构建的 loader 读出源码提交（v16 含 `a48c7fb`），没有设 `BUILD_ID` 的旧镜像读出 `unknown`，后者按正常值处理。

## 6. 缩短 50 秒的三条路

当前 `loader_return()` 调用 GPU／Iris 的 `return_quiesce` 后通过 `loader_jump` 返回，Iris 资源仍需保留时使用 reason 3。返回与复位实测见[多媒体验证结果](2026-11-11-multimedia-validation.md)第 12、18 节；完整停机与资源回收见[外设与电源待办](../backlog/platform.md)。
