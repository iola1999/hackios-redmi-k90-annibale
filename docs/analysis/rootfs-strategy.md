# 根文件系统：系统盘怎样进内核

本文记录内核挂载根文件系统的约定、loader 常驻区的布局，以及把系统盘装进常驻区的几条路径。现在的做法是从双系统 `darwin` 分区、Android DSU 或经 USB 读入系统盘，操作见 [README](../../README.md) §4、§5。「路线 D」是 loader 从 GPT 分区预读系统盘的做法，loader 代码里的 `rdfile` 条目仍按它工作，定义见 §4。

## 1. 内核侧：两块 RAM 盘

- 根文件系统是 RAM 盘 `md0`。loader 在设备树 `chosen/memory-map` 写入 `RAMDisk = <pa, size>`，内核的 `IOFindBSDRoot()` 据此 `mdevadd()` 出 `/dev/md0`。boot-arg `rd=md0` 只是设备名。
- payload 里的小根盘（`root.apfs`，iOS 26 为 `root26.apfs`）由 `RAMDisk1` 发布为 `/dev/md1`，挂到 `/redwood`，装本项目的程序、库与启动任务，不作根目录。完整启动两块盘都要给。
- APFS 用 fork 自带的驱动（`xnu/files/bsd/miscfs/apfs/`，Apple OSS 不含 APFS），读为主，支持透明压缩、多卷与 root mount。`memdev.c` 的盘大小改成 64 位，4 GB 以上的盘不溢出；`rd=md*` 时等待 BSD root 的超时从 30 s 缩到 0.1 s。
- 26 线内核用同一套约定：`xnu26/patches/` 同样修改 `memdev.c`、`vfs_conf.c`（注册 `apfs`）和 `IOKitBSDInit.cpp`（`RAMDisk1`）。
- 内核里没有 IOStorageFamily（没有 IOBlockStorageDriver、IOMediaBSDClient），存储都走 BSD cdevsw 加自研 APFS。

成功判据：loader 日志有 `resident image at pa … size …: it is the root (md0), the payload ramdisk is md1`，内核日志有 `BSD root: md0, major 1, minor 0`。重启后日志缺少 resident image 一行时，先恢复完整输入，再查根盘挂载。

## 2. loader 常驻区

- 内核窗口：`choose_window()` 取 UEFI 内存图里最大的空闲块。默认上限 `MAX_MEM_SIZE` 为 6 GB（bootstrap 页表覆盖 8 GB），payload 的 `memsize` 可放大到 `MAX_MEM_SIZE_LIMIT` 14 GB；iOS 26 用 `MEMSIZE=300000000`（12 GiB）。
- 常驻系统盘放在 `win_base + RESIDENT_RD_OFFSET`（`0x08000000`，128 MiB）。可用大小为 `win_size − 128 MiB − RESIDENT_RD_RESERVE`，`RESIDENT_RD_RESERVE` 为 768 MiB，留给内核自己。窗口要先选定，再往常驻区写数据。
- 内核与 payload 的小根盘放在常驻区之前的 128 MiB 里，`tools/k90auto/make-payload.py` 打包时检查小根盘放得下。2026-11-05 的 `12377-rate7` 内核与常驻系统盘之间只剩 40.9 MB，56.1 MB 的根盘没能启动，见 [11-05 记录](../progress/2026-11-05-defaults-and-charging.md)。
- 内核运行时不写常驻区（根只读）。同一个 loader 生命周期里，一次装入可以启动多次内核；整机复位后要重新装入。

## 3. 装入常驻区的路径

| 路径 | 做法 | 用途 |
|---|---|---|
| QEMU | `qemu/run-ios.sh` 用 `memory-backend-file` 把系统盘映进 guest RAM 的常驻地址，payload 条目 `rdres=<字节数，十六进制>` 告诉 loader 大小 | QEMU 回归 |
| USB | `hackios-xnu-kernel/tools/stage-system.sh` 上传：较小的镜像 `oem ramdisk` 后一次上传；超过 0xffffffff 字节的镜像要求 `ramdisk-protocol: 1`，用 `oem ramdisk begin TOTAL WINDOW` 加按 256 MiB 分块的协议，窗口（`SYSTEM_WINDOW`）按 32 MiB 对齐，细节见[真机调试手册](../plan/device-test-playbook.md) | 没装 DSU 时的默认路径，每次约 2 分钟 |
| Android DSU | 系统盘作为 DSU 镜像存在 userdata 里（pinned file）；loader 从 `/metadata/gsi/dsu/<slot>/lp_metadata` 找到 `system_gsi` 的区段，`oem dsu load TOTAL WINDOW` 经 EDK2 BlockIo 读入，`oem dsu crc` 供主机逐 GiB 比对 CRC，不写存储 | 推荐，约 1.4 秒 |
| 路线 D（`rdfile`） | 见 §4 | `mkpayload.py` 与 loader 支持，当前流程不用 |

- QEMU 的 `RD_ADDR=0xFC000000` 是结果：那次 QEMU 选出的窗口基址是 0xF4000000，加 128 MiB 正好落在这里。窗口变化时摆放地址要跟着变。
- 系统盘的磁盘分区部署见 [README](../../README.md) §4 与[双系统分区与持久化部署手册](../plan/dual-boot-setup.md)，读入与回退 USB 的逻辑在 `tools/k90auto/run-auto.py`（[k90auto 说明](../../tools/k90auto/README.md) §3），loader 侧在 `xnuloader/loader_dsu.inc`。

## 4. 路线 D：loader 从 GPT 分区预读

定义：loader 在启动内核之前，用 EDK2 BlockIo 把写在某个 GPT 分区里的系统盘镜像顺序读进常驻区，设好 `resident_rd_size`。内核看到的布局与 QEMU 的 `rdres` 相同，不需要内核存储驱动，boot.img 大小不变。

- payload 条目：`rdfile=<分区>:<字节数>[:<偏移>|tail]`（`xnuloader/loader_04_fault_payload_nvram.inc`），`tail` 表示镜像对齐到分区末尾。读入在 `rdfile_load()`（`xnuloader/loader_01_base_log_dt.inc`），每次最多读 256 KiB。
- 依据：K90 上 EDK2 BlockIo 读可用；写不落地，对 boot_a、misc、metadata、logfs、xbl_sc_logs 五个分区块 0 的写探针回 Android 用 dd 核对都保持原内容。路线 D 只读，不受写的问题影响。
- 镜像要先在 Android 侧 dd 进分区。直接写已挂载的 userdata 尾部不安全：那段区间可能已被文件系统分配，写入后 Android 出现过 SystemUI 问题（因果未确认），见[系统界面修复记录](2026-10-23-android-systemui-recovery.md) §3。
- DSU 解决了镜像放在哪里的问题：镜像同样在 userdata 里，但由 Android 的 libfiemap 分配并固定，loader 只读。

## 5. 容量约束

| 对象 | 大小 | 结论 |
|---|---|---|
| 系统盘 `system26.apfs` | 约 5.3 GB | 只能放常驻区 |
| boot_a／boot_b 分区 | 100,663,296 B（96 MiB，`annibale-backup/20261022-2355/partitions.txt`） | 装不下系统盘 |
| payload 容器 | ≤ 0x04000000 − 4 KiB（64 MiB，`mkxnuimg.py`） | 只装内核、小根盘与参数 |
| LK `fastboot boot` 镜像 | 上限约 2 MiB（超限报 Load Error；2,236,416 B 的 `handoff-loader-v16.img` 能启动） | 只用来启动 loader |
| 常驻区 | `win_size − 128 MiB − 768 MiB` | 5 GB 以上的系统盘要用 `memsize` 放大窗口 |

## 6. 没有做的方向

- 持久化：系统和运行数据都在内存里，`/private/var` 每次开机新建，见[每次开机都是首次开机](2026-10-31-every-boot-is-first-boot.md)。
- 闪存作根：fork 已有 loader 代读 UFS 的中转（`xnu/files/bsd/dev/redwood_ufs.c`，boot-arg `ufs=2` 时 loader 发布共享页，内核出 `/dev/ufs_<GPT 名>`），以及 `root_apfs=` 加 `kern.redwood_switch_root` 的切根，upstream 在 POCO X5 Pro 上用它跑到完整 iOS。K90 上没跑过，annibale 的 loader 设 `skip_ufs_arbitration`，不做 UFS 交接。中转是单深度同步请求，原评估是开机到锁屏要分钟级（未实测）；BlockIo 写不落地，写路径要另找办法。
- 内核原生 UFSHCI 驱动：现有 `xnu/files/bsd/dev/redwood_ufshc.c` 借用 UEFI 已初始化的控制器，只读，没有复位、PHY、UIC 与时钟初始化。SM8750 的 UFSHC 基址 `0x1d84000` 与 redwood 相同，但它是 UFSHCI 4.0 加 MCQ，redwood 的做法需要真机验证。
