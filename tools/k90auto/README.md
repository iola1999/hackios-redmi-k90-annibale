# K90 无人值守桌面测试

这组脚本在没有人操作手机的情况下完成一轮桌面测试：启动带 GPU 加速的 iOS 26，自动解锁、执行一段固定的点按和滑动，截图并拉取日志，结束后复位回 loader，再汇总帧率、温度、CPU 档位和渲染错误。日常入口是 `cycle.py`（第 8 节）；第 3 节是按目录排队的方式。设备操作的约束见 [AGENTS.md](../../AGENTS.md) 第 5 节，命令细节见[真机调试手册](../../docs/plan/device-test-playbook.md)。

槽位假设：这些脚本按「Android 在 B 槽、loader 写在 A 槽的 boot 分区」编写。`cycle.py`、`reboot-lk.py`、`recover-loader.py` 固定执行 `set_active a`，`recover-loader.py` 还断言 Android 的 `ro.boot.slot_suffix` 为 `_b`。Android 在 A 槽的设备需要对调命令里的 a／b，并修改这些脚本。

## 1. 前提与产物位置

- 设备处于驻留 loader 的 idle 状态（`fastboot -s xnuloader getvar result` 输出 `result: idle`），USB 连接主机；`cycle.py` 也可以从 Android 出发。同一设备一次只跑一个队列。
- loader 用 `hackios-xnu-kernel/out/handoff-loader-v17.img`（`cycle.py` 的 `LOADER`），构建见 [annibale UEFI 与 loader 镜像构建](../../docs/analysis/annibale-uefi-build.md)，刷写见[真机调试手册 §3](../../docs/plan/device-test-playbook.md#3-安装驻留-loader)。
- 主机需要 Python 3.12 或更新版本、`adb`、`fastboot`；截图转换需要 `ffmpeg`，截图统计需要 NumPy。
- 输出目录默认是 `docs/progress/evidence/k90auto`（Git 忽略），可用 `K90_EVIDENCE` 改。一轮的目录是 `kernel-<内核名>-<标签>/`，含 `manifest.json` 和 `run/`（`s###.log` 日志快照、截图、`commands.jsonl`、`reboot.json`、`tour.json`）。
- `run-auto.py` 按 `manifest.json` 校验载荷、辅助盘与启动卷的大小和 SHA-256，核对载荷实际启动参数；要求 loader 报告 `ramdisk-protocol: 1` 且常驻区为空。这里的常驻启动区只接收不超过 64 MiB 的 `flashboot.apfs` 引导卷，系统卷和可变数据都不放入该区域。`EXPECT_PAYLOAD_SHA256`、`EXPECT_ROOT_SHA256`、`EXPECT_BOOT_SHA256` 可再指定期望值，build-id 记入 `reboot.json`。

各产物的来源：

- 系统盘 `hackios-xnu-userland/userland/system26.apfs`：构建见[开发指南](../../docs/development.md) §6，磁盘部署见[双系统分区与持久化部署手册](../../docs/plan/dual-boot-setup.md)。
- 启动卷 `hackios-xnu-userland/userland/flashboot.apfs`：在 `hackios-xnu-userland/userland/` 执行 `FLASHBOOT=1 FLASHBOOT_ONLY=1 CRYPTEXES=flash bash build.sh`，只编译 `stage0` 并生成小型 APFS 启动卷。系统卷从 UFS 挂载，切根路径与待完成的真机验收见[根文件系统说明](../../docs/analysis/rootfs-strategy.md)。
- iOS 26 内核（12377 线）从头构建按[内核仓库说明](../../hackios-xnu-kernel/README.md)（[GitHub](https://github.com/iola1999/hackios-xnu-kernel/blob/k90-port/README.md)）§2，构建完执行 `python3 tools/k90auto/register-kernel.py 12377-<名字>`：内核复制为 `hackios-xnu-kernel/out/xnu12377-<名字>.bin`，记录写进 `kernel-12377-<名字>/kernel.json`，`cycle.py --kernel 12377-<名字>` 和 `make-payload.py` 从这份记录取内核并核对哈希。`cycle.py` 的默认内核 `12377-rate10` 只在本项目的测试机上登记过，新环境要用 `--kernel` 指定。
- iOS 26 内核在 Mac 上增量构建：把改动的文件从 `hackios-xnu-kernel/xnu/files` 复制进 `hackios-xnu-kernel/out/xnu12377-cmd`，在 `hackios-xnu-kernel/` 下按上一版 `kernel-12377-<名字>/kernel.json` 里 `build.command` 记录的命令执行 `xnu26/build-macos.sh`（`KERNEL_UUID` 换新值），产物复制为 `out/xnu12377-<名字>.bin`，再写一份新的 `kernel-12377-<名字>/kernel.json`（`kernel.path`、`kernel.bytes`、`kernel.sha256`）。`make-payload.py` 从这份记录取内核并核对哈希。
- AIR 库：`build-air.py` 是唯一的构建入口，先把 `hackios-xnu-userland/tools/mesa/air/` 的源码复制进 arm64e 构建树再编译、签名，记录写在 `out/ios26-resume/mesa-arm64e/air-build-record.json`；`--check` 只核对。构建树由 `setup-mesa-arm64e.py` 建立，步骤见 [arm64e 用户态构建 §6](../../docs/analysis/2026-10-28-arm64e-userland-build-path.md#6-构建树从仓库重建)。
- 根盘、Metal 驱动与注入库：`package.py`（第 7 节）。
- Wi-Fi 固件：`hackios-xnu-kernel/tools/mk-fw-wifi.py` 从手机的 modem 分区取出，放在 `hackios-xnu-kernel/out/fw-wifi/`。

## 2. 根盘里的操作脚本与 launchd 任务

- `rc.jobs.desktop`：`package.py` 默认的 `etc/rc.jobs`。32 s 滑动解锁，约 120 s 起循环 8 轮，每轮下拉控制中心停 8 s、按 home 收起，再左右翻页。init 每行最多 63 个参数，所以每轮单独一行。
- `jobs/rc.jobs.interactive`：`cycle.py` 用的脚本，只启动 `annsh`、`lsprobe`、`framewatch` 等常驻程序，不碰屏幕；屏幕操作由主机经 `rsh.py`／`tour.py` 发送。
- `jobs/` 下其余 `rc.jobs.*` 是诊断轮的操作脚本，用 `JOBS_SOURCE` 选择。
- `jobs/*.plist`：`package.py` 补进根盘的 launchd 任务（chronod、PosterBoard、replicatord、installd、biomed、ReportCrash、linkd、contextstored、dasd、appprotectiond）。chronod 约 120 s 后启动，installd 以 root 运行，biomed 等保持 Apple 的按需启动；理由写在 `package.py` 的注释里。

## 3. 排队方式跑一轮

```sh
python3 tools/k90auto/make-payload.py NAME LABEL out/ROOT.apfs "EXTRA BOOT-ARGS"
bash tools/k90auto/run-queue.sh docs/progress/evidence/k90auto/kernel-NAME-LABEL ...
bash tools/k90auto/sheets.sh docs/progress/evidence/k90auto/kernel-NAME-LABEL/run    # 可选：PNG 与缩略图拼图
python3 tools/k90auto/summary.py --markdown docs/progress/evidence/k90auto/kernel-NAME-LABEL ...
python3 tools/k90auto/gestures.py docs/progress/evidence/k90auto/kernel-NAME-LABEL ...
python3 tools/k90auto/frame-split.py docs/progress/evidence/k90auto/kernel-NAME-LABEL 120   # 第二个参数是 fb_hz
```

`make-payload.py` 把内核、辅助盘（`hackios-xnu-kernel/` 下的相对路径）和启动参数打成 `hackios-xnu-kernel/out/handoff-NAME-LABEL.bin`，打印本轮目录。固定参数包括 `rootdev=md0 root_apfs=ufs_darwin ufs=2 ufs_native=1 launchd_unsecure_cache=1`、GPU 一组（`adreno8=<GPU_STAGE> adreno8_keep=1 adreno8_return=0 adreno8_speed=<GPU_SPEED>` 等）和 `touchscreen=2 buttons=1 battery=1`，第四个参数追加在后面；载荷禁止带 `loader_return_after`。根设备与 UFS 参数必须各有且只有一项。

| 变量 | 默认值 | 作用 |
|---|---|---|
| `CPU_ARGS` | `cpus=2 bootcpu=7 small_cores_after=0` | CPU 部分的启动参数 |
| `GPU_SPEED` | `3` | GPU 档位上限 `adreno8_speed` |
| `GPU_STAGE` | `23` | `adreno8=`；`0` 不起 GPU，内核可以返回 loader |
| `BOOT_IMAGE` | `hackios-xnu-userland/userland/flashboot.apfs` | 启动卷，大小上限 64 MiB（工作区相对路径） |
| `MEMSIZE`、`IDENTITY` | 无 | 传给 `mkpayload.py` 的 `--memsize`、`--identity` |

iOS 26 用 `MEMSIZE=300000000 IDENTITY=v57`，`cycle.py` 另把 `CPU_ARGS` 设为 `cpus=4 bootcpu=7 small_cores_after=0`。

GPU 档位：`1` 固定 160 MHz；`2`～`N` 时内核按负载和触摸在下限（`adreno8_floor`，默认第 3 档）与第 N 档之间切换。第 3～7 档为 342、389、443、525、607 MHz，8～10 档为 660、734、832 MHz，K90 这颗芯片（speed bin 232）另有 11～14 档 900、967、1050、1100 MHz（`adreno8_cx.c` 的 `adreno8_boot_speeds`，`12377-rate5` 起）。超过本芯片档位数的取值截到最高档（`12377-rate6` 起）；`34209c1` 之前的内核只支持 1。`make-payload.py` 默认 3、`cycle.py` 默认 14，对比轮次时要显式写档位。

`run-queue.sh` 依次运行各目录，每轮默认 420 s，100 s 起每 3 s 截图，每 20 s 拉一次日志（`RUN_SECONDS`；`RUN_TIMING` 格式为 `截图间隔,截图起点,日志间隔`）。它先核对 `manifest.json` 里的载荷存在；复位后退回 Android 时调 `recover-loader.py` 切回 loader；loader 不处于 idle 或该轮失败时停止整个队列。

`run-auto.py` 的其余行为与开关：

- 启动卷：先上传 payload，使 loader 按本轮 `memsize` 分配窗口；再通过 `oem ramdisk` 上传小型 `flashboot.apfs` 启动卷，核对 loader 报告的实际长度与窗口。该卷只提供 `stage0` 和挂载目录，系统卷由内核从 `darwin` 分区按需读取，`/private/var` 由 `darwin_var` 直接持久化。
- 帧停止 `K90_FREEZE_SECONDS`（默认 20）秒后提前收尾；`K90_FREEZE_OFF=1` 按固定时长跑。
- `run/shot-request` 出现时拍一张（`shot-now.py` 写这个文件，`SHOT_ON_ACTION=0` 忽略）；`run/stop-request` 出现时提前收尾。
- `rsh.py ROUND_DIR COMMAND...` 把一行命令（最多 119 字符）交给 `run-auto.py`，经 `oem sh` 发给设备上的 `annsh`，输出从日志取回；内建命令见 `hackios-xnu-userland/userland/src/apps/annsh.c`。输出等待默认为 40 秒，慢原生调用可通过 `RSH_OUTPUT_TIMEOUT` 延长，调用方的子进程期限也要相应放宽。
- `ios-state.py ROUND_DIR [--ls PATH] [--sysctl NAME] [--threads PID]` 通过 `rsh.py` 采集只读状态，默认覆盖进程、`trollstorehelper list`、`/Applications`、下载目录和 IPA 暂存目录，结果写入 `run/ios-state-*.json`。`trollstorehelper list` 列出 `/private/var/containers/Bundle/Application` 中已安装的应用；系统应用可通过 `trollstorehelper open` 和主屏复核。命令返回非零会保留在对应记录中；传输失败停止后续查询，并在报告里标明失败命令。
- `fetch.py ROUND_DIR DEVICE_PATH OUT` 通过 `annsh cat` 分块读回设备文件，检查偏移连续性，任一段缺失就以失败退出。
- 收尾：`oem stop` 后按秒轮询状态（`K90_STOP_WAIT`，默认 70 秒），离开 running 后先 `get_staged` 保存 loader 持有的快照，再取串口日志。自动复位仅接受 `returned`、`returned-held`、`hung`、`hung-held` 及其完整零错误状态；未知状态、格式错误或复位命令失败会停止队列。内核始终不应答时不复位，保存 `running.log` 并以非零退出。`reboot.json` 的 `left` 记复位前的状态，完成条件是 loader 重新应答 idle 且启动卷常驻区为空。源码与实测见[无人值守收尾](../../docs/analysis/2026-10-28-unattended-teardown.md)。

`round-run.py ROUND_DIR [SECONDS] [TIMING]` 是 `cycle.py` 的起轮入口，在 `run-auto.py` 外面加两项：一轮 5 秒内以 `returned` 结束且日志有 `PANIC caller` 时视为早期启动 panic，最多重试 `K90_PANIC_RETRY`（默认 3）次，全部 panic 时以 3 退出；设备处于 LK 时检查 `slot-retry-count:a`，低于 3 先 `set_active a`。

## 4. 判读

- `summary.py` 每轮一行：内核提交、关键启动参数、运行秒数、panic 次数、动画窗口帧率、显示驱动每帧耗时、GL 帧耗时 p50／p90、帧间隔分布（低于 18 ms、18～35 ms、更长）、大核最高温度、最低档时间占比、截图数与异常截图数、崩溃记录数（内核报的进程退出行）。`--verify` 检查合并结果包含每份快照里的帧窗口，缺失时以 1 退出。
- 帧间隔只统计帧数不少于 20 且帧率不低于 10 帧/秒的窗口。`summary.py` 只把 `s[0-9]*.log` 当日志快照，按重叠部分对接，同一窗口只算一次。loader 的日志区是 263,349 字节的头加 1,048,576 字节的环，环满之后开头的内容被覆盖；容量与快照频率见[运行协议](../../docs/plan/k90auto-run-protocol.md)的日志环一节。
- `gestures.py` 按手势统计主动画的帧间隔（控制中心下拉取首帧起 1.8 s，翻页取 600 ms），输出 p50／p95／最长间隔、超过 18 ms 的比例、帧率和触摸到首帧的时间。需要 `touch_lat=1`，加 `glslow=3000` 时还给出窗口服务器每帧绘制时间。
- `frame-split.py` 把每个动画帧拆成 backboardd 交帧（P）、GPU（G）、等节拍（bw）、拷进面板（C）四段，给出长帧归因和每段动画的帧率；需要 `touch_lat=1`。新日志另有 `panel_obs`，表示拷屏完成到观测 `CTL_FLUSH` 清零的上界。带 `tl: l` 时用 `INTF_FRAME_COUNT` 的差值计算显示间隔和长帧分组，`at` 只表示观测时刻；没有 `tl: l` 的旧日志沿用 `shown` 为拷屏开始的 copy 口径，P/G/bw/C 等原有数值不变，不将该口径当作实测面板时刻。
- 异常截图指 GMEM 分 bin 边界下方出现状态栏蓝色块的截图（2026-10-25 的 framebuffer fetch 缓存问题）。其他显示异常要看拼图或由人确认。
- 温度和 CPU 档位来自 `cpufreq=1` 或 `2` 时内核每 30 s 写的日志。`N by temperature, M without a reading` 区分限频由读数触发还是没有读数触发；判断限频是否守住看紧跟的 `hot ticks` 一行。
- backboardd 的 GPU 时间按 pass 拆分：`JOB_ENV` 加 `com.apple.backboardd.plist:ANNIBALE_PASS_TIMES=1` 和 `com.apple.backboardd.plist:FD_GPU_TRACEPOINT=-all,+render_pass,+draw_ib,+compute,+blit,+nondraw,+tile_loads,+tile_stores`，日志每 5 秒打印一组 `pass times`。AIR 库要带 `tools/mesa/rebase-26/0008`，读法见[GPU 提频后的 120 Hz](../../docs/analysis/2026-11-02-120hz-after-gpu-clock.md) §6；带 `0018` 时还会为不低于 2 ms 的 draw 打印 `draw gpu slow`，每个进程每 5 秒最多 4 行。
- 震动、亮度、声音等需要人感知的项目不在判定范围内。

离线检查：`python3 tools/k90auto/tests/test-tools.py` 用临时替身代替 fastboot，覆盖帧间隔分组、快照合并、队列失败后停止、收尾状态、启动卷上传顺序及大小和状态不符的拒绝路径。

## 5. 软件进入 LK FASTBOOT

`reboot-lk.py` 从驻留 loader 进入 LK，不需要人按键。它运行已校验的最小准备载荷：内核以 `annibale_reboot_lk=1 cpus=1` 启动（`hackios-xnu-kernel/xnu/files/bsd/dev/annibale_reboot_probe.inc`），在 PMK8550 SID 0 的 SDAM `0x7148` 写入 bootloader 重启原因 2（保留 bit 0）并读回，再返回 loader；主机确认 prepared 日志后调用 loader 的普通 reboot，读到指定设备的 LK product 和槽位后停止。准备载荷是本地构建产物，放在 Git 忽略的 `hackios-xnu-kernel/out/ios26-resume/reboot-lk-prepare/`。

调用前设备需处于 idle 或无 held 的 returned 状态，启动卷常驻区为空，没有其它主机任务访问该设备；不满足时工具拒绝并保留现有内容，按[真机手册 §6](../../docs/plan/device-test-playbook.md#6-故障定位与恢复)保存日志并复位后再试。

```sh
python3 tools/k90auto/reboot-lk.py docs/progress/evidence/k90auto/reboot-lk-RUN \
  --payload hackios-xnu-kernel/out/ios26-resume/reboot-lk-prepare/annibale-reboot-lk-prepare.bin \
  --sha256 6b81e800ae789cf30adbaaa9c98768012e264c66a4e56110c6449cecf93fb7d7 \
  --serial "${ANDROID_SERIAL}"
```

- `--serial` 缺省时读 `ANDROID_SERIAL`。输出目录必须尚未存在。载荷变更后重新核对完整哈希。
- `--payload` 必须是这份准备载荷；误传轮次载荷时内核会再起一次并停在 `hung-held`，工具报 `Probe return timed out; reboot not sent`。
- 每条命令的 stdout、stderr、退出码、时限和耗时写入 `commands.jsonl`，准备日志与最终状态写入 `prepared.log`、`result.json`。哈希、状态或 prepared 校验失败时不发送 reboot；复位应答丢失后仍有界检查枚举，成功条件是实际读到 LK。
- `--return-loader` 往返回到 loader，用于恢复 A 槽重试次数：在 LK 要求 `slot-successful:b=yes`、`slot-unbootable:b=no`，执行 `set_active a`，读回 `slot-retry-count:a=7`、`slot-unbootable:a=no` 才发回程 reboot；回程要求重新读到同一 build-id 的 xnuloader、`result=idle`、空的启动卷常驻区、协议 1 和下载窗口 `0x03700000`。任一条件不满足就停下并保留现场。只改活动槽位与启动元数据，不刷写镜像，实测往返约 26 秒。

离线检查为 `python3 tools/k90auto/test-reboot-lk.py`，用 fastboot 替身跑 19 项测试，不操作设备。

## 6. 界面进程状态检查

`ui-health.py` 检查同一次启动的多份日志，默认跟踪 SpringBoard 和 backboardd，日志含 NUL 也继续解析。进程中止、异常、断言、内核 panic 或同一进程名出现多个 PID 判为失败；进程记录缺失或断言没有进程前缀要求人工审阅。多次启动的日志必须分开检查，否则正常重启也会触发 PID 变化判定。

```sh
python3 tools/k90auto/ui-health.py docs/progress/evidence/k90auto/RUN/device-*.log \
  --output docs/progress/evidence/k90auto/RUN/ui-health.json
```

`--process Preferences` 等参数增加预期进程。退出码 0 表示进程状态已观察到且未检出上述故障，2 表示失败，3 表示需要审阅；显示内容、手势与帧率另行验收。离线检查为 `python3 tools/k90auto/test-ui-health.py`。

## 7. payload 打包

`package.py` 组装 iOS 26 根盘：用 xcrun clang 编译 shim、Metal 驱动（`hackios-xnu-kernel/tools/userland-driver/`）和 SpringBoard 适配库等 arm64e 库，把 `build-air.py` 签好名的 AIR 库与这些库装进根盘副本，写入 `etc/inject.conf`、backboardd 的 `ANNIBALE_SB_METAL=1` 与 `etc/rc.jobs`，补上 `jobs/` 里的 launchd 任务，用 `mkapfs.py` 打包，最后逐文件回读校验并把哈希写进 `manifest.json`。从工作区根目录运行 `python3 tools/k90auto/package.py`。

基线根盘是 `userland/build.sh` 的暂存目录 `hackios-xnu-userland/userland/root/`（`package.py` 的 `BASE`）。打包前在 `hackios-xnu-userland/userland/` 执行 `IOS=../ios26 bash build.sh`（只要根盘时加 `COMPILE_ONLY=1`，不写镜像），需要 macOS 与 Xcode。`package.py` 把基线打成 `base.apfs`，打包后核对两份镜像之间变化的路径都在它要改的范围内。

产物在 Git 忽略的 `hackios-xnu-kernel/out/ios26-resume/bbmetal-device/`（`root.apfs`、各个库、`manifest.json`、构建日志）。基线没有按 iOS 26 暂存、AIR 库的构建记录或 adhoc 签名不符、变更超出范围，任一项成立就退出；AIR 库漏签名会让 dyld 拒绝加载，整轮退回 CPU 合成。

打包开关（环境变量，`cycle.py` 原样传给 `package.py`）：

| 变量 | 默认 | 作用 |
|---|---|---|
| `JOBS_SOURCE` | `tools/k90auto/rc.jobs.desktop` | 换掉根盘里的 `etc/rc.jobs` |
| `JOBS_DROP` | 空 | 不打包列出的 `jobs/*.plist` |
| `REST` | `1` | 登记其余 iOS 26 任务（`userland/mkjobs.py --rest`），有人查其 Mach 服务时才启动；`REST_ALLOW` 额外放行 DENY 表里的项 |
| `ICON_METAL` | `1` | iconservicesagent 用 Metal 设备；`0` 时软件渲染，设置页图标是灰块 |
| `POSTER_METAL` | `1` | MercuryPosterExtension 插入 Metal 设备登记库；`0` 时壁纸为黑色，见[锁屏壁纸](../../docs/analysis/2026-10-31-mercury-wallpaper.md) |
| `DIRTY_REGIONS` | 关 | `1` 时 backboardd 只重绘变化区域；默认整帧重绘 |
| `MSAA` | 关 | `1` 时 backboardd 与 SpringBoard 的渲染 pass 用 4 倍采样 |
| `WIFI_FW` | 自动 | `out/fw-wifi/` 里有驱动读的四个文件（`amss20.bin`、`regdb.bin`、`bd_p11.elf`、`phy_ucode20.elf`，约 6.9 MB）时放进根盘；`1` 放入全部文件（约 27 MB）；`0` 不放 |
| `AX` | `SpringBoard Preferences MobileSafari Weather MobileSMS MobileNotes MobileMail MobileCal MobileSlideShow Music Maps AppStore Files HelloK90` | 插入 `libannibale-ax.dylib` 的进程；空字符串时不插入。供 `ui.py` 按文字查找和点按；同一个库把状态栏的时间和电池各向屏幕边缘移 12 点（[状态栏布局分析](../../docs/analysis/2026-11-02-status-bar-layout.md) §6）。进程名写进 `kern.exec_inject`，总长不能超过 510 字节 |
| `AUDIO` | `1` | 放行音频任务（audiomxd 等）并把 `AnnibaleAudio.driver` 按 arm64e 重编，音量键、音量条和控制中心的音量滑块可用（还没有声音）；`0` 不放行 |
| `PAYLOAD_PROGRAMS` | 空 | `路径[:路径]`，把重新构建的程序装进根盘 |
| `GPU_SPEED` | `3` | 记进 manifest，与载荷的 `adreno8_speed` 不一致时 `make-payload.py` 拒绝 |

开机自动运行的程序（`jobs/rc.jobs.interactive`，`cycle.py` 在产物存在时打包，构建脚本见 `TrollStore/build_k90.sh`）：

- `trollstorehelper watch`（`TrollStore/RootHelper/main.m`）：开机确保 `TrollStore.app` 已注册到 LaunchServices，并监听 `/private/var/tmp/ipa/`，出现完整的 `.ipa` 就解压签名安装。`trollstorehelper install|remove|list|open|url` 也可以经 `rsh.py` 直接调用。

运行中的操作工具：

- `install-ipa.py 轮次目录 App.ipa [--open]`：经 USB 把 IPA 分块（每块不超过 15 MB）推进内核的 16 MB 收件区，annsh 的 `pull 路径 偏移` 写到 `/private/var/tmp/ipa/`，等 `trollstorehelper list` 出现该应用。需要带 `serve_pushes` 的 `run-auto.py` 和支持偏移的 annsh。
- `ui.py 轮次目录 dump|tap 文字|wait 文字|shot 名称|accessibility`：读各进程 `libannibale-ax.dylib` 写的界面元素（文字和屏幕坐标），按文字点按，代替手写坐标。UIKit 的按钮、提示框和主屏图标能读到；SwiftUI 页面（设置的列表、天气）目前读不到。

其余诊断开关（`PAYLOAD_SRC_ROOT`、`PAYLOAD_AIR_STRINGS`、`PROBE`、`XPCWATCH`、`TOUCH_LAT`、`ANNIBALE_DIAG`、`ROUND_NOTES`）的含义写在 `package.py` 里各变量定义处的注释中。

`JOB_ENV="任务.plist:变量=值 ..."` 给指定任务的 plist 和 launchd 缓存各加一个环境变量，一项一个变量。常用的几个：

- `OS_ACTIVITY_DT_MODE=YES`：os_log 随 stderr 进控制台日志；backboardd、iconservicesagent、chronod 已带。SpringBoard 的 os_log 量大，两次拉取之间日志环会转过多圈，开机解锁那一行被覆盖，不要给它打开。
- `ANNIBALE_SYNC_DRAWS=1`：驱动每个绘制后提交并等待完成，没完成的打印 `sync: commit N work M did not finish`，并以 `AIRFAIL begin hung-vertex`／`hung-fragment` 打出该管线的着色器，用 `hackios-xnu-userland/tools/mesa/air/airfail-extract.py` 取回。每个绘制都要等 GPU，只给怀疑的进程打开。
- `FD_MESA_DEBUG=...`：freedreno 的调试开关，例如 `sysmem` 让所有批次不走 GMEM。
- `IR3_SHADER_DEBUG=vs`／`fs`：把这一类着色器的 NIR 和 A830 机器码打进 stderr，量大，只给一个进程打开。

`EXT_ENV="进程名:变量=值 ..."` 给没有 launchd 任务的进程加环境变量，目前只对 MercuryPosterExtension 生效：变量写进根盘的 `/annibale/etc/env/进程名`，插入的库设置后让进程重新执行一次（`OS_ACTIVITY_DT_MODE` 在 libSystem 初始化时就已读取）。该进程的 stdout／stderr 是 `/dev/null`，输出经 `kern.annibale.say` 进内核日志（`say PID MercuryPosterExtension: ...`）。

## 8. 渲染问题的无人值守检查

`cycle.py` 从工作树跑完一轮：打包、做载荷、上传启动卷并启动，等 SpringBoard 报出 `sb26: boot unlock done` 后执行一段固定的操作与截图，然后提前结束这一轮，写出 `render-report.txt`。日常使用见[体验说明 §11](../../docs/user-guide.md#11-日常使用与切换)。

```sh
ANDROID_SERIAL=<序列号> python3 tools/k90auto/cycle.py LABEL --baseline docs/progress/evidence/k90auto/kernel-NAME-上一轮
python3 tools/k90auto/render-health.py docs/progress/evidence/k90auto/kernel-NAME-LABEL [--baseline 另一轮]
python3 tools/k90auto/tour.py docs/progress/evidence/k90auto/kernel-NAME-LABEL "home@3*2" "settings=/annibale/bin/anntouch tap 0.385 0.70@4*2"
ANDROID_SERIAL=<序列号> python3 tools/k90auto/cycle.py LABEL --kernel 12377-cmd15 --hold --seconds 2400
python3 tools/k90auto/respin.py docs/progress/evidence/k90auto/kernel-NAME-LABEL --env iconservicesagent:-FD_MESA_DEBUG --restart iconservicesagent --wait 30 --tour "home@3*2"
```

- 默认值：内核记录 `12377-st5`（`--kernel`），`--seconds 900`，`jobs/rc.jobs.interactive`，`GPU_SPEED=14`，CPU 参数 `cpus=4 bootcpu=7 small_cores_after=0`。起轮后最多等 420 s 看到开机解锁，等不到就跳过操作。
- 固定启动参数 `FIXED_ARGS`：GPU 与调频（`gpu_log=1 metal=1 cpufreq=1 fb_threads=2 touch_lat=1 gpu_coherent=1`）、120 Hz（`fb_flip=2 fb_beat=0 fb_hz=120 fb_ca_hz=120 dl_max=1`）、`touch_poll_us=4000` 和 Wi-Fi（`pcie=10` 一组与 `wifi_station=1`），诊断开关不放在这里。之后是 `--boot-args`，最后是 `fbwidth=1206 fbheight=2622 fbpitch=460`（iPhone 17 画布，见[状态栏布局分析](../../docs/analysis/2026-11-02-status-bar-layout.md)）。
- `CYCLE_FIXED_ARGS`、`CYCLE_CPU_ARGS`、`GPU_SPEED` 分别替换固定参数、CPU 参数和 GPU 档位。同一个键出现两次时内核取第一个，所以本轮变量是 `FIXED_ARGS` 里的键时要用 `CYCLE_FIXED_ARGS` 整串替换；画布三个键排在最后，可以在 `--boot-args` 里改。`CYCLE_PROGRAMS=路径[:路径]` 往根盘的 `/annibale/bin` 多放程序。
- 起轮前要求 loader 已枚举、`result` 为 idle、启动卷常驻区为空，否则停止；设备在 Android 时先调 `recover-loader.py`。每 2 轮做一次检查点：经 `reboot-lk.py` 进 LK、`set_active a` 并读回 `slot-retry-count:a: 7`，再 `fastboot boot` 起 `LOADER`（或 `LOADER_IMAGE=FILE`）；驻留 loader 的 build-id 不含 `45d97a8` 时也先做检查点。LK 由 `ANDROID_SERIAL` 指定，计数存在 `docs/progress/evidence/k90auto/cycle-state.json`。
- `--hold` 在操作截图后不结束这一轮，跑满 `--seconds` 或收到 `respin.py --stop` 才结束。期间用 `respin.py` 改驱动设置、重启进程，不必重新打包和上传辅助盘；需要 12377-cmd14 起的内核和带 `setenv`、`addenv`、`restart` 的 annsh。SpringBoard 被结束后停在 backboardd 的转圈界面，所以改 SpringBoard 的设置仍要重新起一轮。
  - `--env` 把 `kern.annibale.env` 设为给出的词（`进程名:变量=值` 或 `进程名:-变量`），超过 119 字符时拆成一条 `setenv` 和若干条 `addenv`；不带词时清空。
  - `--restart` 向同名进程发 SIGKILL，由 launchd 重新拉起；驱动在进程加载时把本进程名下的设置写进环境变量，覆盖 plist 里的同名变量，每条打印 `kern.annibale.env: 词`。
  - `--wait` 是重启后等待的秒数（默认 30），`--until` 改为等日志出现指定文字，`--tour` 接着执行 `tour.py` 的步骤。
- `render-health.py` 合并 `s*.log` 后，把驱动、AIR 库、QuartzCore 的 Metal 日志、MiniIOSurface 与 GPU 驱动里的失败行按类别计数，每类写明屏幕上的后果，未归类的列在 unclassified 下；`--baseline` 给出另一轮的计数并标出只在一侧出现的行。驱动的部分拒绝只在首次或 2 的幂次打印，计数 1 或 2 的幂可能代表更多次。
- `tour.py` 的每一步是 `标签=命令@等待秒数*截图张数`，命令经 `rsh.py` 发给 annsh；同一步拍两张以上时比较前后两张，状态栏以下的变化写进 `run/tour.json`，用于发现闪烁。全部截图缩成 `run/tour-sheet.png`，编号与 `tour.json` 一致。
- GPU 挂起后，12377-cmd4 起的内核打印 RBBM 与 CP 状态和各级 IB 在 CP 位置前后的命令字；`python3 tools/k90auto/cp-words.py ROUND_DIR` 把它们按 type 7／type 4 包头解成包名并标出 CP 位置。CP 会预取，停住的包可能在标记之前一两个。
- SpringBoard 的图层树用 annsh 的 `notify com.annibale.layers.<过滤词>` 打到日志里（`all`、`Icon`、`Wallpaper`、`Poster`、`StatusBar`、`Battery`、`Widget`）。过滤词在任意层级匹配图层类或所属视图类，向下再列 3 层；每行是层级、图层类、视图类、尺寸、位置、隐藏与透明度、内容类型和尺寸，用来区分「图层没有内容」和「有内容但没有画出来」。
