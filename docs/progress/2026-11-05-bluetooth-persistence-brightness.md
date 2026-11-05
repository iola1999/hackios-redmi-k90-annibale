# 蓝牙、跨开机保留数据与面板调光（2026-11-05）

本文记录 2026-11-05 完成的蓝牙接入、跨开机保留 `/private/var`、DSI 面板背光调节、GPU 温度传感器地址修正、韩文字体与 `bluetoothd` 入盘、Mesa `fd_bo_heap_alloc` 空指针检查及内核增量编译加固的改动与实测轮次。各项的原理与证据细节分别见[蓝牙接入调研](../analysis/2026-11-02-bluetooth-bringup.md) §8、[跨开机保留数据的可行性与实测](../analysis/2026-11-05-persistence-feasibility.md) §7、[屏幕亮度调节调研](../analysis/2026-11-02-brightness-control.md) §9 与[项目排查与协作手册](../plan/debugging-and-collaboration.md) §3。

## 1. 改动

- 跨开机保留 `/private/var`（`dsu_store`）：
  - `hackios-xnu-kernel/xnuloader/loader_dsu.inc`：在 16 GiB DSU 槽位的末尾 4 GiB（偏移 12 GiB 起，1,048,576 个 4096 字节块）登记合成块区 `dsu_store`，提供 `dsu_store_write()`，按 `system_gsi` 的扩展区换算 userdata 扇区并做越界检查、写前比对与写后回读校验。
  - `hackios-xnu-kernel/xnuloader/loader_02_platform_cpu_ufs_survey.inc`、`loader_03_ufs_block_watch.inc`：`ufs_crc32()` 改用 ARMv8 硬件指令 `crc32x`／`crc32b`（loader v19，`45d97a8`），`ufs_write=1` 放行 `dsu_store` 写入。
  - `hackios-xnu-kernel/xnu/files/bsd/dev/redwood_ufs.c`、`hackios-xnu-userland/userland/src/var_store.c`：设备路径改为 `/dev/rufs_dsu_store`，双槽位每槽 2 GiB（`0x80000000` 字节）。
- 面板背光调节（DCS `0x51`／`0x52`）：
  - `hackios-xnu-kernel/xnu/files/iokit/Drivers/KernelBuiltIn/ARM/AppleARMPE/MiniFramebufferFlip.inc`：通过 DSI0（`0x0ae94000`）DMA FIFO 发送 MIPI DCS `0x51`（`MIPI_DCS_SET_DISPLAY_BRIGHTNESS`，长包 `0x39`，大端 2 字节 DBV）并用 `0x52`（短包 `0x14`）回读校验；`IOMFBBrightnessLevel` 的毫尼特数换算为面板 DBV `1..0x1a5e`（6,750），默认开启 `DCS_DEFAULT = 4`。文件保持在 1,212 行。
- 蓝牙接入（SE14 UART + Skywalk + `RedwoodBT`）：
  - `hackios-xnu-kernel/xnu/files/bsd/dev/annibale_bt_uart.c`、`annibale_bt_ios.c`、`annibale_btsk.c`、`annibale_bt_private.h`、`iokit/KernelConfigTables.cpp`：实现 SE14（`0x898000`）115200 波特 4 线 UART 驱动、WCN7850 TLV／NVM 下载、`com.apple.uart.sk.bluetooth` 控制套接字、Skywalk kernel pipe 通道、`RedwoodBT` IOService，并在 `bt_answer_vendor()` 代答厂商命令及 `0x204a`（避免芯片锁入扩展广播模式而拒绝 `0x2007`／`0x200b`）。
  - `hackios-xnu-userland/userland/src/bluetool.c`、`ios165/select-system.py`、`tools/k90auto/package.py`：新增 `bluetool` XPC 替身；系统盘选入 `usr/sbin/bluetoothd`（12.15 MB）与韩文字体 `AppleSDGothicNeo.ttc`（32.23 MB）并更新手机 DSU；`package.py` 默认开启 `BLUETOOTH=1`。
- 其他修复与构建加固：
  - `hackios-xnu-kernel/xnu/files/osfmk/arm64/redwood_adreno.c`：K90 GPU 温度传感器地址改为 `0x0c22a000`（tsens2），并在 `adreno8_gpu8_keep` 路径每秒调用 `redwood_adreno_minute()`。
  - `hackios-xnu-userland/tools/mesa/rebase-26/0015-fd-bo-heap-null-check.patch`：`fd_bo_heap_alloc` 检查 `util_vma_heap_alloc` 返回 0 与 `bo_new` 返回 `NULL`，重编并签名 `libredwoodair.dylib`（`5a6a3cbabf49f6ff`）。
  - `hackios-xnu-kernel/xnu26/xcrun`、`xnu26/build-macos.sh`：过滤 `-Werror` 下宿主 Clang 21 触发的 `-Wreserved-identifier`；剥离外层 GNU Make 传入的 `-j`；在运行 `config` 后夹紧 `DOCONFDEPS` 与生成 `Makefile`／`assym.s` 的时间戳，避免修改 `conf/files` 触发 2 小时全量重编。
  - `tools/k90auto/cycle.py`：默认内核更新为 `12377-st4`，`FIXED_ARGS` 默认包含 `ufs=2 ufs_write=1 var_store=1 var_save_ms=60000 bt=4`。

## 2. 轮次

| 轮次目录 | 内核 | 本轮变量 | 结果 |
|---|---|---|---|
| `kernel-12377-st2-r1` | `12377-st2` | `ufs=2 bt=3 fb_dcs=2` + `VARSTORE_SHOW=1` | `dsu_store` 识别 4,096 MB（双槽均为空）；DCS 写 `0x0200` 回读 512；蓝牙下发 `hmtbtfw20.tlv`／`hmtnv20.bin`，5 秒 LE 扫描发现 43 台设备；GPU 温度读出 50.8～52.3 °C |
| `kernel-12377-st2-r2` | `12377-st2` | `ufs=2 ufs_write=1 var_save_ms=30000 fb_dcs=3` | DCS 写 512 与 2,788 回读一致；软件逐位 `ufs_crc32` 耗时过长，30 秒只写完 28,672 块 |
| `kernel-12377-st2-r3` | `12377-st2` + loader v19 | `ufs=2 ufs_write=1 var_save_ms=60000 fb_dcs=4` | 硬件 CRC-32 下 `var_store` 5,300 毫秒将 `/private/var`（28,724 条目，410.7 MB，CRC `0x2c8947ea`）写入 `slot 0`（generation 1）；DCS 随滑块走通 `2788 -> 22 -> 4726`；切回 Android 运行 2 小时并更新含 `bluetoothd` 的 DSU 系统盘 |
| `kernel-12377-st3-r1` | `12377-st3` | `--seed ""` + `ufs=2 ufs_write=1 var_store=1 var_save_ms=60000 bt=4` | 从闪存 `slot 0` 展开 `/private/var`（11,580 目录、5,260 文件、61 符号链接），主屏 15 图标齐全、Wi-Fi 自动连上；停轮 5,000 毫秒写入 `slot 1`（generation 2，CRC `0xfa947c2e`）；默认 `DCS_DEFAULT=4` 回读 2,788；`bluetoothd` 因 `0x204a` 触发芯片扩展广播锁定而在 `0x2007`／`0x200b` 收到 `0x0c` |
| `kernel-12377-st4-r1` | `12377-st4` | `--seed ""` + `bt=4 var_store=1`（代答 `0x204a`） | `bluetoothd[47]` 全程无重启，LE 扫描进入 `Scanning(3)` 并发现 9 台 BLE 设备；控制中心与 `Settings -> Bluetooth` 开关均为开启；手势 `cc-pull` 94.4、`swipe-left` 98.1 帧／秒 |
| `kernel-12377-st4-r2` | `12377-st4` | `cycle.py` 新默认参数 + `--seed ""` + Mesa 补丁 `0015` | 从闪存 `slot 1`（generation 2）展开，开机后 `bluetoothd[46]` 直接从磁盘恢复上一次缓存的 `'other devices'` 并继续扫描发现 11 台设备；停轮时 4,620 毫秒将 `generation 3`（27,967 条目，414,817,560 字节，CRC `0xbf8430a9`，写入 100,250 块、跳过 1,024 块）写入 `slot 0` |

## 3. 读数与结论

- 跨开机保留数据：loader v19 使用硬件 `crc32x` 后，410～415 MB 的 `/private/var` 归档写入加回读校验耗时 4.6～5.3 秒；Android B 槽日常运行与 `gsi_tool status` 不受影响；不带 `etc/var.seed` 启动时 `init` 直接从 `dsu_store` 连续跨轮（`slot 0 -> slot 1 -> slot 0`，generation 1～3）恢复桌面、设置、Wi-Fi 与蓝牙设备缓存。
- 面板背光调节：`DCS_DEFAULT = 4` 默认启用后，无需额外启动参数即可按系统尼特数经 DSI0 调节面板 DBV 并由 `0x52` 回读确认，手势帧率（`cc-pull` 94.4、`swipe-left` 98.1 帧／秒）与开启前基线一致。
- 蓝牙：WCN7850 的 `BTFW.HAMILTON.2.0.1` 收到 `0x204a` 后会禁用传统 LE 扫描命令，内核代答 `0x204a` 后 `bluetoothd` 稳定运行并完成 BLE 扫描与设置页展示。后续配对、3 Mbaud 提速与蓝牙音频留在下一阶段。
