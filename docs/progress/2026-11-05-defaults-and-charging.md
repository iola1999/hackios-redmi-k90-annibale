# 默认开机参数、充电状态与安装应用（2026-11-05）

用户要求 Wi-Fi 等已验证的功能默认打开，不再依赖环境变量；反馈插着充电器、电量较高时状态栏不显示充电；要求能在 iOS 运行时随时安装 IPA（经 USB 或在手机上下载）。本文记录这一天的改动、轮次与读数。120 Hz 的 dc2 轮记在 [11-02 轮次记录](2026-11-02-120hz-gpu-clock-rounds.md)。

## 1. 改动

- `tools/k90auto/cycle.py`：
  - 固定参数整理为 `FIXED_ARGS`，加上 `touch_poll_us=4000` 与 `kernel-12377-cmd83-wd32` 的 Wi-Fi 一组（`pcie=10` 起到 `wifi_station=1`，不含诊断用的 `net_trace=80`）。
  - 默认内核 `12377-rate8`；`--seed` 缺省时用本地的 `kernel-12377-cmd30-seed3/seed-icons.bin`。
  - 驻留的 loader 不是 v16（build-id 不含 `a48c7fb`）时，先经 LK 用 `fastboot boot` 启动 `out/handoff-loader-v16.img`，不需要再给 `LOADER_IMAGE`。
  - 巡检里设置图标的点按位置由 0.616 改为 0.385。
  - `appinst`、`wifijoin` 已构建时自动打包，`jobs/rc.jobs.interactive` 开机运行 `wifijoin` 与 `appinst watch`。
- `tools/k90auto/package.py`：本地固件目录有 `amss20.bin`、`regdb.bin`、`bd_p11.elf`、`phy_ucode20.elf` 时默认只放这四个文件，约 6.9 MB，有 `network` 文件时一起放入；`WIFI_FW=1` 仍放入全部文件，`WIFI_FW=0` 不放。`AX` 控制插入 `libredwood-ax.dylib` 的进程；`AUDIO=1` 放行音频任务并按 arm64e 重编 `RedwoodAudio.driver`，还没有上机。
- `tools/k90auto/run-auto.py`：处理 `push-request-*.txt`，用 `oem push` 加 `stage` 把文件放进内核的 16 MB 收件区。
- 新工具：`install-ipa.py`（经 USB 分块推送并安装 IPA）、`ui.py`（读界面元素、按文字点按、截图）。
- 用户态（`.userland.git` `1c51c1d21`，移植为 userland `36136c4`）：`appinst`、`wifijoin`、`libredwood-ax`、rwsh 的 `pull 路径 偏移`、Mesa 补丁 0010。
- 内核（`67f8d61`）：电池读数来自电量计 BQ27Z561（`annibale_battery.c`），电流不低于 −50 mA 就算外部供电；`RedwoodBattery.cpp` 在外部供电且状态不是放电时报充电，供电或状态变化时打印一行 `RedwoodBattery: N%, ...`。`12377-rate8` 只含 `RedwoodBattery.cpp` 的改动，`12377-rate9` 两处都含。

## 2. 轮次

| 轮次目录 | 内核 | 本轮内容 | 结果 |
|---|---|---|---|
| `kernel-12377-rate7-def1`（第一次） | rate7 | 新默认参数，加 `torch=3 hv_haptic=4` | 没有启动：根盘 56.1 MB，内核与常驻系统盘之间只放得下 40.9 MB |
| `kernel-12377-rate7-def1` | rate7 | 同上，Wi-Fi 固件只放四个文件 | 桌面、设置、控制中心正常；Wi-Fi 驱动报 `no thread, or no memory the radio can be given`；手电与振动初始化失败 |
| `kernel-12377-rate7-use1` | rate7 | 默认参数，loader v16，保持 900 秒给用户试用 | Wi-Fi 驱动注册射频（ath12k，固件 `amss20.bin`） |
| `kernel-12377-rate8-r8a` | rate8 | 默认参数，巡检同 dc2，带 `REDWOOD_PASS_TIMES=1` | 充电状态按新规则上报；手势帧率与整屏 pass 读数见 §3.1 |
| `kernel-12377-rate8-fp16` | rate8 | 同 r8a，backboardd 加 `CA_FP16_MIN_HEADROOM=1e30`、`CA_ALLOW_EDR_MIRRORING=0` | 整屏 pass 仍是 2 个颜色附件，每次时间不变；不采用 |
| `kernel-12377-rate8-ns1` | rate8 | 同 r8a，AIR 库带 Mesa 补丁 0010（不写回 `colormask` 为 0 的颜色附件） | 截图无差异；tile store 合计下降，手势帧率在波动范围内；保留 |
| `kernel-12377-rate8-app1` | rate8 | 默认参数加 `appinst`、`wifijoin`、`libredwood-ax`，保持运行 | 在手机上装上并启动 HelloK90；`wifijoin` 手动运行时加入网络；Safari 下载 IPA 失败 |
| `kernel-12377-rate8-app2` | rate8 | 同 app1，`wifijoin` 等设备 300 秒，fileproviderd、weatherd 等带 `OS_ACTIVITY_DT_MODE` | 开机时 `wifijoin` 等不到设备；手动加入连续 4 次握手失败（reason 15） |
| `kernel-12377-rate8-app3` | rate8 | 同 app2，`wifijoin` 每 5 秒重建客户端，rwsh 分块 pull，`appinst` 看 Safari 暂存目录 | 开机自动加入网络；USB 与 Safari 两种方式都装上 IPA |

## 3. 读数

### 3.1 默认参数与性能

- 根盘大小：基础根盘约 6 MB，开机种子约 23 MB，Wi-Fi 固件目录全部约 27 MB。`wd` 系列轮次不带种子，所以没有遇到上限。
- Wi-Fi 的低端 DMA 内存：`wd` 系列轮次用 `LOADER_IMAGE` 启动 loader v16，命令行带 `lowdma=`；手机 A 槽里刷的 loader 较旧，不给这段内存。use1 经 LK 启动 v16 后命令行有 `lowdma=0x00000000c77c0000`，驱动正常起来。
- def1 的手电：`reading 0x0018 gave: the transfer was dropped`，随后 `the light for iOS stops after 0 times lit: the module said something surprising`；振动：故障寄存器 0x10 清不掉。原因未查，两项不进默认参数。
- def1 的设置里 Wi-Fi 开关显示关闭，那一轮驱动没有起来。use1 中开关状态由用户确认。
- r8a 与 dc2 之间同时换了内核（rate8）和默认参数（Wi-Fi），帧率不作单变量对比。r8a：控制中心下拉 91.2、左滑 99.9、右滑 91.3 帧／秒，整屏 pass 每次 808 µs，tile store 合计 3.33 s。用户在 use1（rate7、默认参数）手持体验时的读数是 88.9、92.8、86.0。
- fp16 轮的 `REDWOOD_PASS_LOG` 显示颜色 1 的 `writeMask` 为 0，补丁 0010 由此而来。
- ns1 对 r8a：整屏 pass 每次 808 → 787 µs，tile store 合计 3.33 → 2.76 s（次数 112122 → 116029），控制中心下拉 91.2 → 89.2、左滑 99.9 → 101.3、右滑 91.3 → 95.2 帧／秒。tile store 按 bin 计次，次数不随附件数变化；每个整屏 pass 是否都跳过了颜色 1 没有单独核对。
- ns1 手势窗口 1747 帧：一拍 78%，两拍 18%，三拍以上 4%。长帧里 G 超过一拍 287 个，P 超过一拍 91 个；一帧有 4 次以上 backboardd 提交的 328 帧里 72% 是长帧，G 中位数 12.6 ms。

### 3.2 充电

- 电池读数来自电量计，`external` 此前按电流大于 +50 mA 判断，充电器是否在线没有单独来源。use1、r8a 连着 Mac 的 USB：开机后第一次上报为充电、+132 mA，之后电流 −106～−1302 mA，按放电显示。电脑 USB 口给的电流小于手机耗电，这些读数分不出「USB 掉线」和「供电不够」。
- rate8 只改了 `RedwoodBattery.cpp`，电流在 0 附近时 `external` 仍为假，满电停充时仍不显示充电。rate9 把电流不低于 −50 mA 算作外部供电，墙插充电器下的显示还没有实测。

### 3.3 安装应用

- 登记方式：`registerApplicationDictionary:`，`ApplicationType` 为 System，数据容器由 MobileContainerManager 建。app1 用 rwsh 调 `appinst install` 装上 HelloK90，`appinst open` 启动，界面正常。
- USB（app3）：`install-ipa.py` 装 9 KB 的 HelloK90 用时 9 秒；41 MB 的测试 IPA 分 3 块，17 秒装好并启动。
- Safari（app3）：点「下载」后文件出现在 Safari 数据容器的 `Library/Safari/Downloads/<UUID>/`，`appinst watch` 约 10 秒内装好，图标出现在主屏。Safari 自己的下载随后停在下载中（app1 里显示 Task failed）。
- 文件 App 的「浏览」里没有任何位置，所有 App Group 下都没有 `File Provider Storage`；LocalStorageFileProvider 从未启动，原因在查。

### 3.4 Wi-Fi

- app1：`wifijoin` 手动运行，第一次关联就完成四次握手。wifid 的关联回调报 −3902，但链路已经起来，所以 `wifijoin` 改为以 wifid 的当前网络判断成功。
- app1 的目标记录取自扫描里一次 −94 dBm 的读数，其余扫描里同一接入点在 −17～−25 dBm；加入后内核报给 iOS 的信号一直是 −94 dBm，状态栏只有一个点。app3 的目标在 −20 dBm，状态栏满格。
- app2：开机时 `wifijoin` 建的客户端一直列不出设备（en0 约在内核时间 200 秒出现），改为每 5 秒重建客户端后 app3 开机即加入。
- app2：手动加入连续 4 次失败，每次接入点发 3 次第 1 条消息，我们回的第 2 条都没有发出去，解除认证时才报 `WAS DROPPED by the driver`，随后 reason 15。目标信号 −20 dBm，与 app1 成功那次的 −94 dBm 不同，信号读数不能解释发送失败。

### 3.5 视频与天气

- Safari 打开主机上的测试页：H.264 视频报 `err=3:Media failed to decode`；VP9 只到 `loadedmetadata`，`readyState` 停在 1。H.264 依赖硬件解码。
- 天气：「我的位置」页显示「— —」，`locationd` 在 `mkjobs.py` 的 DENY 表里没有启动；列表里的城市也是「— —」，联网正常，weatherd 的日志在 app2 里，原因在查。

## 4. 待办

- `12377-rate9` 上机：墙插充电器、高电量时状态栏应显示闪电。
- Wi-Fi 第 2 条握手消息没有发出：在 ath12k 的发送路径上找原因。
- 加入后的信号读数：关联后不再更新，要改为跟随实际接收信号。
- 文件 App 没有「我的 iPhone」：查 LocalStorageFileProvider 为什么不启动。
- `AUDIO=1` 上机：音量键、音量提示框和音量值。
