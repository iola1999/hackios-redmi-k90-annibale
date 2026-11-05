# hackios-redmi-k90-annibale — HackiOS 移植工作区（REDMI K90 / annibale）

把 [HackiOS](https://github.com/oosexgang/hackios-xnu-kernel)（XNU + 未修改的 iOS 用户态）移植到 **REDMI K90（SM8750，代号 `annibale`）**。真机运行未修改的 iOS 26.6.2（23G90，取自 iPhone 17）和本项目维护的 XNU 12377 内核，Android 保留在另一个槽位，随时可以切回。项目仍在实验阶段，其他机型需要独立移植。

## 1. 当前进展

| 方面 | 状态 |
|---|---|
| 桌面与系统应用 | 开机自动解锁进入简体中文主屏；壁纸、图标、日历与天气小组件、控制中心、通知中心可用；设置、Safari、短信、计算器、备忘录、提醒事项等系统应用能打开，文件 App 里有「我的 iPhone」 |
| 双系统与磁盘持久化 | 从机身存储划分 iOS 系统盘与数据盘；闲置槽位刷入 `xnuloader` 后提供 3 秒开机菜单，支持免连电脑启动 iOS 26 或切回 Android；系统设置、主屏布局、已安装应用与用户数据实时落盘 |
| 图形与显示 | Metal 驱动经 Mesa freedreno 在 Adreno 830 上绘制；按 iPhone 17 的 1206×2622 分辨率渲染并适配 120 Hz 面板 |
| 屏幕亮度 | 控制中心与「设置 → 显示与亮度」滑块直接调节屏幕硬件背光 |
| 触摸与按键 | 触摸、电源键、音量键可用；音量键和控制中心的滑块能调音量，还没有声音 |
| Wi-Fi 与蓝牙 | 在「设置 → Wi-Fi」中加入网络后可用 Safari 上网；蓝牙支持扫描、发现与连接外设 |
| 安装应用 | 支持安装并运行已解密的 `.ipa` 应用 |
| 电池与温控 | 显示电量与充电状态；处理器和 GPU 按负载调频，过热时逐档降频 |
| 未完成 | 蓝牙音频、声音输出、摄像头、蜂窝网络、App Store；网页视频播放与天气数据请求正在排查修复；手电与振动在 iOS 26 上还不能用 |

性能：在 120 Hz 屏上，主屏翻页约 90～100 帧／秒，控制中心下拉约 90～94 帧／秒；GPU 最高 1100 MHz，测试期间 GPU 温度最高约 57 °C。

部署与升级提示（完整说明见[双系统分区与持久化部署手册](docs/plan/dual-boot-setup.md)）：

- 首次部署需在 Android root 环境下无损缩小 `userdata` 并划分 iOS 分区，操作前请先备份重要分区与个人数据。
- Android 系统 OTA 更新不会影响 `darwin` 与 `darwin_var` 分区中的 iOS 数据；若完整包更新覆盖了闲置槽位的 `boot` 分区，更新后将 `xnuloader` 重新刷回闲置槽位即可恢复双系统引导菜单。

最新状态和实测数据以[总账](docs/plan/2026-10-23-tracking.md)为准，验收目标见[路线图](docs/plan/2026-10-26-roadmap.md)。

## 2. 用 AI Agent 体验

把下面这段话交给 AI Agent，它会按本文和链接的手册完成检查、准备、分区和启动：

```text
请协助我体验 https://github.com/iola1999/hackios-redmi-k90-annibale 。先阅读 README、AGENTS.md、双系统分区与持久化部署手册和排查与协作手册，问清我的设备容量和电脑环境，只读核对机型、bootloader 解锁状态、当前 Android 槽位和 UFS LUN 0 分区表。建议我先备份重要分区。准备匹配的 K90 构建产物，在我确认空间分配后按部署手册划分 darwin 与 darwin_var 分区，写入 system26.apfs，并将 xnuloader 刷入 Android 之外的闲置槽位。写分区或切换槽位前，列出设备、目标、LBA 范围、文件哈希和恢复命令，等我确认。启动 iOS 26 后先验收桌面，再逐项试用；验证与 Android 的双系统切换并检查数据。不要自动解锁或锁定 bootloader。
```

## 3. 准备

- 设备：已解锁 bootloader 且具备 root 权限（用于首次在线缩容分区）的 REDMI K90、可传数据的 USB 线。
- 电脑：`adb`、`fastboot`、Git、Python 3；构建 iOS 26 的内核和用户态程序需要 Mac 与 Xcode，构建 loader 里的 UEFI 和给 Mesa 打补丁需要 Docker。
- 备份（建议）：写入前备份两个槽位的 `boot`、LUN 0／LUN 4 的 GPT 表等重要数据，方法见[分区备份与恢复](docs/backup/README.md)。Wi-Fi 固件也要从备份的 modem 分区里取。

```sh
git clone --recurse-submodules https://github.com/iola1999/hackios-redmi-k90-annibale.git
cd hackios-redmi-k90-annibale/hackios-xnu-kernel
USERLAND_URL=https://github.com/iola1999/hackios-xnu-userland.git USERLAND_REF=k90-port common/setup.sh
```

`common/setup.sh` 把用户态仓库检出到 `hackios-xnu-kernel/` 目录里，下文的 `userland/`、`tools/mesa/` 等目录来自它，见[内核仓库说明](hackios-xnu-kernel/README.md) §1。

构建产物放在 Git 忽略的目录里，主要是 `hackios-xnu-kernel/out/`：

- 系统盘：`hackios-xnu-kernel/ios26/fetch.sh` 从 iPhone 17 的 iOS 26.6.2 IPSW 取出文件（IPSW 的下载见下文），再在 `hackios-xnu-kernel/userland/` 执行 `IOS=../ios26 bash build.sh`，得到约 5.9 GB 的 `system26.apfs`（含完整本地化语言包与分词资源）；同时生成的 `userland/root/` 是下一项打根盘用的基线。
- 内核：按[内核仓库说明](hackios-xnu-kernel/README.md) §2 构建，再在工作区根目录执行 `python3 tools/k90auto/register-kernel.py 12377-local` 登记。
- 根盘与 Metal 驱动：见 [k90auto 说明](tools/k90auto/README.md)。
- loader 镜像：见下文「构建 loader 镜像」。
- GPU 固件：按 [Adreno 830 固件说明](hackios-xnu-userland/firmware-gen8/README.md) 放进 `hackios-xnu-kernel/fw-gpu/`，构建根盘时复制进去。其中 `gen80000_zap.mbn` 用 `adb pull /odm/firmware/gen80000_zap.mbn` 从手机取。
- Wi-Fi 固件：按备份方法读出 modem 分区（本测试机用 `modem_a`），再执行 `python3 hackios-xnu-kernel/tools/mk-fw-wifi.py extract modem_a.img.gz hackios-xnu-kernel/out/fw-wifi`。脚本从分区镜像的 `image/kiwi/` 取出 WCN7850 固件，启动时自动放入驱动读取的 4 个文件。
- 开机种子（可选）：一份开机稳定后的 `/private/var` 归档，用于首次初始化 `darwin_var` 分区。取法见[每次开机都是首次开机](docs/analysis/2026-10-31-every-boot-is-first-boot.md) §5。

系统盘只用 IPSW 里的三个镜像，在工作区根目录下载并解密（约 10.4 GB，需要 `brew install sevenzip` 和 Python 的 `cryptography` 包）：

```sh
D=hackios-xnu-kernel/out/ipsw/v57/26; mkdir -p $D
URL=https://updates.cdn-apple.com/2026SummerFCS/c2f9fa07-0acc-4038-99f4-d7a4b1ac9c06/iPhone18,3_26.6.2_23G90_Restore.ipsw
python3 tools/ipsw/fetch.py 094-96558-090.dmg.aea $D/os.dmg.aea "$URL" 11481186987
python3 tools/ipsw/fetch.py 094-95851-092.dmg.aea $D/systemos.dmg.aea "$URL" 11481186987
python3 tools/ipsw/fetch.py 094-96441-094.dmg $D/appos.dmg "$URL" 11481186987
for n in os systemos; do
  aea decrypt -i $D/$n.dmg.aea -o $D/$n.dmg -key-value "base64:$(python3 tools/ipsw/aea-key.py $D/$n.dmg.aea)"
done
hackios-xnu-kernel/ios26/fetch.sh
```

构建 loader 镜像（`hackios-xnu-kernel/out/handoff-loader-v17.img`）分三步，完整命令见 [loader 镜像构建](docs/analysis/annibale-uefi-build.md)：

1. 取 UEFI 源码：loader 镜像里的 UEFI 用 Project Silicium 的 [Mu-Silicium](https://github.com/Project-Silicium/Mu-Silicium) 构建，K90 的修改在 [iola1999/hackios-mu-silicium](https://github.com/iola1999/hackios-mu-silicium)。把它的 `k90-port` 分支连同子模块克隆到 `hackios-xnu-kernel/Mu-Silicium/`。
2. 构建 UEFI：用 `docker/build.sh` 生成开发容器镜像，`docker/dev.sh` 进入容器；建符号链接 `Binaries/annibale` → `dodge`，运行 `tools/fixup-mu-nasm.sh` 和 `python3 build_uefi.py -d annibale`，得到 `SILICIUM_UEFI.fd`。
3. 装配镜像：用 `xnuloader/build.sh` 编出 loader，`xnuloader/mkpayload.py` 封成载荷，再用 `mkxnuimg.py` 把 BootShim、UEFI、载荷和设备树装成镜像。

## 4. 划分磁盘分区并安装引导

项目在 UFS LUN 0（`/dev/block/sda`）尾部从 Android `userdata` 无损缩容出两个分区，配合刷入闲置槽位 `boot` 分区的 `xnuloader` 实现双系统与持久化：

- `darwin`（默认 `8 GiB`）：写入 `system26.apfs`，作为 iOS 26 只读系统盘。
- `darwin_var`：挂载为 `/private/var` 可写数据盘，容量按机型存储大小自行指定（例如 256 GB 机型可分 `112 GiB` 给 `darwin_var`、保留约 `111 GiB` 给 Android；512 GB／1 TB 机型按需填写 `--var-gib`）。
- 双启动 `xnuloader`（刷入与当前 Android 相对的闲置槽位 `boot_a` 或 `boot_b`）：开机显示 3 秒启动菜单，倒计时结束免连电脑自动进入 iOS 26；期间按音量键与电源键可选择「Boot iOS 26」、切回另一槽位的「Boot Android」或进入「USB Fastboot Debug Mode」。

在线缩容 `/data`、写入分区表与 `system26.apfs`、刷入 `xnuloader`、处理 Android OTA 更新以及恢复原厂分区表的完整步骤见[双系统分区与持久化部署手册](docs/plan/dual-boot-setup.md)。

## 5. 启动并使用 iOS 26

部署完成后，日常使用直接按电源键开机，等待 3 秒即可进入 iOS 26 桌面：

- 桌面与手势：上滑回主屏、左右翻页、下拉控制中心和通知中心、打开系统应用。
- 无线网络：在「设置 → Wi-Fi」中选择网络并输入密码加入，配置在重启后自动保留。
- 屏幕亮度：在控制中心或「设置 → 显示与亮度」中拖动滑块调节背光亮度。

安装第三方应用（需使用已解密的 `.ipa` 包，安装的应用与数据保存在 `darwin_var` 分区，重启后保留）：

- 手机直接安装：在 Safari 中下载 `.ipa` 文件并在弹窗中点击「下载」，约 10 秒后应用图标出现在主屏。
- 电脑通过 USB 安装（详见 [k90auto 说明](tools/k90auto/README.md)）：

  ```sh
  python3 tools/k90auto/install-ipa.py <轮次目录> App.ipa --open
  ```

若需要连电脑打包并引导新编译的内核或执行自动化测试，见 [k90auto 说明](tools/k90auto/README.md)。

## 6. 双系统切换（iOS 与 Android）

引导目标切换的完整判据与故障恢复见[引导目标切换 SOP](docs/plan/device-boot-target-sop.md)和[双系统分区与持久化部署手册](docs/plan/dual-boot-setup.md) §4：

- **从 iOS 切回 Android**：重启手机，在 `xnuloader` 开机菜单 3 秒倒计时内按音量键选中「Boot Android」并按电源键确认，loader 会自动将活动槽位切到另一槽位并重启进入 Android；也可在 FASTBOOT 下执行 `fastboot -s "$ANDROID_SERIAL" set_active <android槽位> && fastboot -s "$ANDROID_SERIAL" reboot`。
- **从 Android 切回 iOS**：在 Android 的 root 终端或 `adb shell` 中切到 `xnuloader` 所在槽位（0 对应 `a`，1 对应 `b`）并重启，例如 `su -c 'bootctl set-active-boot-slot <0或1> && reboot'`；或在 FASTBOOT 下执行 `fastboot -s "$ANDROID_SERIAL" set_active <loader槽位> && fastboot -s "$ANDROID_SERIAL" reboot`。

## 7. 仓库与目录

| 仓库 | 内容 | 分支 |
|---|---|---|
| [hackios-redmi-k90-annibale](https://github.com/iola1999/hackios-redmi-k90-annibale) | 本仓库：文档、脚本，以及两个子模块的版本 | `main` |
| [hackios-xnu-kernel](https://github.com/iola1999/hackios-xnu-kernel) | XNU、loader、Metal 驱动 | `k90-port` |
| [hackios-xnu-userland](https://github.com/iola1999/hackios-xnu-userland) | 用户态适配、镜像与图形工具 | `k90-port` |
| [hackios-mu-silicium](https://github.com/iola1999/hackios-mu-silicium) | loader 镜像里的 annibale UEFI（Mu-Silicium 副本，单独克隆） | `k90-port` |

本项目基于 [OOSEX GANG](https://github.com/oosexgang) 的 HackiOS 内核与用户态仓库，感谢原作者开放 XNU 移植、loader、用户态适配和图形工具。UEFI 基于 [Project Silicium](https://github.com/Project-Silicium) 的 Mu-Silicium。原有许可证和版权声明保留在各仓库中。

- `docs/plan/`：操作手册与计划；排查前先读[排查与协作手册](docs/plan/debugging-and-collaboration.md)和[真机调试手册](docs/plan/device-test-playbook.md)。
- `docs/analysis/`：调研与分析；`docs/progress/`：真机运行记录。
- `tools/`：主机脚本，无人值守测试见 [k90auto 说明](tools/k90auto/README.md)。
