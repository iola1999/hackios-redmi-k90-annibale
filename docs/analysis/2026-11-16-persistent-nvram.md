# 持久化 NVRAM 与 `darwin_nvram` 分区（2026-11-16）

适用范围：`hackios-xnu-kernel`（`k90-port`）的 `64f915ce`（loader、内核与 GPT 工具）和 `23bb6098`（GPT 拆分修正），`hackios-xnu-userland` 的 `dd6cc0d`（迁移脚本）。真机为测试机，内核记录 `12377-nvram1`，`boot_a` 里的 loader `build-id` 为 `64f915ce`。此前 NVRAM 每次开机由 loader 新建空镜像，背光存在 `darwin_var` 末尾 32 MiB 的自定义记录（[可写 APFS §7](2026-11-16-apfs-write-path.md#7-分区末尾与迁移)）。

## 1. 结论

- LUN 0 新增 GPT 分区 `darwin_nvram`（32 MiB），位于 `darwin_var` 之后。开头放 2 个 8 KiB 的 NVRAM bank，16 MiB 处放 panic 日志。
- loader 每次启动内核前读出两个 bank，取校验通过、代数最大的一份作为 `/chosen` 的 `nvram-proxy-data`，与 iBoot 交给内核的方式相同。
- 内核的 `AnnibaleNVRAM` 继承 `IONVRAMController`，经平台专家交给 `IODTNVRAM`。XNU 的 `IONVRAMCHRPHandler` 每次同步写下一个 bank，与 iPhone 的 `AppleARMNORNVRAM` 对应。
- 背光改存 NVRAM 变量 `backlight-level` 和 `backlight-nits`，名称与格式取自 iOS 26 kernelcache 中 AppleARMPlatform 内核扩展的字符串；`darwin_var` 末尾的 `BLS3` 记录已删除。
- 真机上 NVRAM 变量、背光和 panic 日志都能跨重启保留；较旧的 bank 写到一半时，loader 读回较新的完整 bank（第 6 节）。

## 2. 分区布局

| 相对 `darwin_nvram` 起点的偏移 | 内容 |
|---|---|
| 0 | bank 0，8 KiB |
| 8 KiB | bank 1，8 KiB |
| 16 MiB | panic 日志，最多 16 MiB（`KLOG` 头加文本，格式与 ANNFS 时相同） |

- 分区类型 GUID 为 `7bf9472d-0d95-5e78-921b-9dcd5f9c61fa`（`darwin-nvram.hackios` 的 uuid5），loader 和内核都按名称找分区。
- bank 是 XNU 的 CHRP 格式：32 字节 Apple 头（签名 `0x5a`、名称 `nvram`、头校验和、Adler-32、代数），其后是 `common` 分区，变量以 `名称=值` 依次存放。
- 测试机的 `darwin_nvram` 为 LBA 64033787..64041978，Android 下是 `sda37`；`darwin_var` 缩为 LBA 36779008..64033786，与其中的 APFS 容器同样大小。
- iPhone 的 panic 日志由 `AppleARMNORPanicLog` 写进 NOR 存储中单独的区域，不经过 NVRAM bank。这里放在同一分区的 16 MiB 处，读写路径见[可写 APFS §7](2026-11-16-apfs-write-path.md#7-分区末尾与迁移)。

## 3. loader

代码在 `xnuloader/loader_04_fault_payload_nvram.inc` 的 `nvram_load()`，在 `run_kernel` 生成设备树时调用。

- 两个 bank 各自检查签名、名称、头校验和与整块的 Adler-32，通过的才算完整，取代数最大的一份。`IONVRAMCHRPHandler::unserializeImage()` 遇到 Adler-32 不符会 panic，所以交给内核的必须是完整的 bank。
- 找到 `darwin_nvram` 时 `nvram-bank-count` 为 2，`nvram-current-bank` 为选中的 bank；两个都不完整时交出空镜像。
- 没有 `darwin_nvram` 时与以前相同：空镜像，`nvram-bank-count` 为 1，NVRAM 只在本次运行内有效。
- 块服务原来只接受写 `darwin_var`，现在也接受写 `darwin_nvram`。内核关闭原生 UFS 驱动、经 loader 读写时需要这一项。

## 4. 内核

- `AnnibaleNVRAMStart()` 在 `annibale_ufs_init()` 末尾执行，此时 `GenericARMPE::start` 已经返回，`IODTNVRAM` 已经建好。`/chosen` 的 `nvram-bank-count` 小于 2 时不注册控制器：旧 loader 给的是空镜像，写回会覆盖分区里保存的 bank。
- `select` 记下 bank，`eraseBank` 不做事（UFS 可以原地改写），`read`、`write` 按 `bank × 8 KiB + 偏移` 读写 `darwin_nvram`，`sync` 发 `SYNCHRONIZE CACHE`。
- 写一个 bank 时先写后 4 KiB，刷写缓存，最后写头部所在的前 4 KiB。中途断电时这个 bank 保留旧的头和旧代数，loader 的 Adler-32 检查和 `findCurrentBank()` 的头部检查都会选另一个 bank。
- 同步时机与 XNU 相同：`IONVRAM-SYNCNOW-PROPERTY`（iOS 的 `nvram` 命令设置变量后会发出）、`PEWriteNVRAMProperty()`、重启与关机时 `IOPMrootDomain` 调用的 `PESyncNVRAM()`。`oem stop`、五指退出和 `loader_return_after` 到时也经 `annibale_var_save_on_return()` 调用 `PESyncNVRAM()`。
- 原生 UFS 写入白名单支持同一 LUN 上的两个 LBA 范围，分别登记 `darwin_var` 和 `darwin_nvram`。`/dev/ufs_darwin_nvram` 与 `/dev/rufs_darwin_nvram` 仍是只读设备，用户态只能经 `IODTNVRAM` 改变量。

## 5. 背光

- 用户调节亮度时（触摸或滑块），`MiniAppleARMBacklight` 把面板值写进 `backlight-level`（十进制），把亮度写进 `backlight-nits`（16.16 nits，`0x%08x`）。这两个变量先进 `IODTNVRAM` 的字典，下一次同步时写进 `darwin_nvram`。
- 启动时背光驱动和 `MiniFramebufferDCS.inc` 先读这两个变量。读不到时退回 `ANNFS001` 超级块里的记录，没有 `darwin_nvram` 的早期安装照旧在那里保存背光。
- iOS 26 kernelcache 中 AppleARMPlatform 的字符串里，`DisplayBrightnessNitsNVRAM`、`backlight-nits`、`0x%08x` 与 `updated NVRAM with level 0x%x` 相邻，推测 AppleARMBacklight 收到 backboardd 的 `DisplayBrightnessNitsNVRAM` 时改写这两个变量，未反汇编确认。本机在用户触摸或拖动滑块之后保存，时机与之不同。
- AppleARMPlatform 的字符串里没有 `IONVRAM-SYNCNOW-PROPERTY`。这里同样只改字典，靠第 4 节的同步时机写回，强制断电会丢掉上次同步之后的调节。

## 6. 真机验证

GPT 改写与 loader 刷写的步骤记录在第 7 节，下表是之后的四轮。前三轮为第一批，第四轮在复盘后单独测试写坏的 bank。

| 轮次 | 操作 | 结果 |
|---|---|---|
| `nvram-r1` | 首次启动；`nvram hackios-nvram-test=r1`；在控制中心拖动亮度滑块 | loader 打印两个 bank 都不完整、交出空镜像；内核登记两个写入范围并注册控制器。`nvram` 设置后立即写 bank 1（代数 2）。拖动后 `nvram -p` 显示 `backlight-level 5972`、`backlight-nits 0x016277cf`（354.468 nits），与驱动最后一次请求一致。`oem stop` 时写 bank 0（代数 3） |
| `nvram-r2` | 正常重启后启动；改为 `r2` 后用 `sysctl debug.panic_test=4` 触发 panic | loader 读到 bank 0 代数 3、bank 1 代数 2，选 bank 0。背光驱动启动值为 5972（354.468 nits），`nvram -p` 中 `r1`、背光与 iOS 写的 `fm-spstatus`、`StartupMute` 都在。改为 `r2` 后写 bank 1（代数 5）。panic 后设备复位，进入 `boot_a` 的默认镜像，init 打印已把上次的 panic 日志存入 `/private/var/db/panic.log`（262,057 字节） |
| `nvram-r3` | 默认镜像经 `oem stop` 收敛后启动 | `nvram -p` 为 `r2` 与同样的背光；`panic.log` 开头是 `HACKIOS KERNEL CRASH LOG`，正文有 `sysctl debug.panic_test=4` 与两行 `PANIC caller ... xnu_vs_xnu panic test`。改为 `r3` 后写 bank 1（代数 9），此时 bank 0 为代数 7 |
| `nvram-r4` | 在 Android 下只改写 bank 0 的后 4 KiB，头部保持代数 7，与写 bank 0 时在写头部前断电的状态相同 | loader 打印 bank 0 不完整、bank 1 代数 9；`findCurrentBank` 也选 bank 1。`nvram -p` 为 `r3` 与原背光。随后改为 `r4`，写入落到 bank 0（代数 11），写坏的内容被覆盖 |

- 改写前后在 Android 下读出的两个 bank 与日志一致：都是 `nvram` 名称、Adler-32 正确，`common` 分区里是 `boot-args=`、`fm-spstatus=YES`、`StartupMute=1`、`hackios-nvram-test=…`、`backlight-level=5972`、`backlight-nits=0x016277cf`。
- 主机测试：`tools/tests/test-loader-nvram.py` 用真实的 `nvram_load()` 覆盖 7 种 bank 组合，并用 zlib 的 Adler-32 和 XNU 的头校验和检查交出的镜像；`tools/tests/test-userdata-dual-carve.py` 覆盖新装划分、拆分、主备属性位不同和 3 种拒绝情况。
- 没有在真机上测：写 bank 时真正断电（第四轮用 Android 写入模拟写到一半的状态）、低亮度的保留、内核经 loader 读写（`ufs_native=0`）时的 NVRAM 写回。

## 7. 改写测试机 GPT 与刷写 loader

- 在 B 槽 Android（root）下读出 LUN 0 前 8 块和末 8 块，以及 `darwin_var` 块 0，手机与主机的 SHA-256 一致后执行 `userdata-dual-carve.py out/... --split-nvram`。工具从块 0 读出 APFS 容器大小，确认容器止于新的 `darwin_var` 末尾才生成新表。
- 测试机主备分区表在 `countrycode`、`vbmeta_system`、`vm-bootsys` 等 5 个 `_a`／`_b` 项的属性位上不同，主表与当前槽位 b 一致。拆分时两份各自修改，属性位保持原样（`23bb6098`）。
- 按工具打印的 `dd` 命令写主表、主头、备表与备头，读回哈希与生成文件一致。Android 重启后 `/dev/block/by-name/darwin_nvram` 指向 `sda37`，大小 33,554,432 字节；分区开头为零，16 MiB 处是上一份已标记保存的 panic 日志（`DLOG`）。
- 第一次把 24,373,248 字节的 loader 镜像刷进 `boot_a` 后，LK 把 A 槽标为不可启动（重试次数 6）并启动 B 槽 Android。原因是 `boot_a` 末尾的 `AVBf` 页脚指向偏移 23,699,456 的 vbmeta，新镜像比上一版大，覆盖了那里，原理见[引导目标切换 SOP §4](../plan/device-boot-target-sop.md#4-常见问题与注意事项均为实测) 第 7 条。
- 改用 AOSP `avbtool`（`android-16.0.0_r4`）的 `add_hash_footer` 生成 96 MiB 镜像，参数取自原厂 `boot_a`：分区名 `boot`、SHA-256、原厂盐值、回滚索引 1769904000、算法 `NONE`。`verify_image` 通过后重刷，`set_active a` 后约 17 秒 loader 枚举，`build-id` 读回 `64f915ce`。

## 8. 未完成事项

- 发布与安装：Release 和体验说明还按两分区布局编写。新装划分已会建出 `darwin_nvram`；已安装的用户需要先转为 APFS 数据卷，再用 `--split-nvram` 拆出分区，步骤见[双系统部署手册 §3](../plan/dual-boot-setup.md#3-写入-ios-系统盘)。`ANNFS001` 数据卷用到分区末尾，不能直接拆分。
- `boot_a` 镜像大小变化时需要带 AVB 哈希页脚，目前靠手工执行 `avbtool`，没有进入构建脚本。
- 内核在 `darwin_nvram` 上没有 `/dev` 以外的诊断接口；查看 bank 内容要在 Android 下读分区，或在 iOS 下用 `nvram -p`。
