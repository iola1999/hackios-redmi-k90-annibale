# hackios-redmi-k90-annibale — HackiOS 移植工作区（REDMI K90 / annibale）

把 [HackiOS](https://github.com/oosexgang/hackios-xnu-kernel)（XNU + 未修改的 iOS 用户态）移植到 **REDMI K90（SM8750，代号 `annibale`）**。真机运行未修改的 iOS 26.6.2（23G90，取自 iPhone 17）和本项目维护的 XNU 12377 内核，Android 保留在另一个槽位，随时可以切回。项目仍在实验阶段，其他机型需要独立移植。

## 1. 当前进展

| 方面 | 状态 |
|---|---|
| 桌面与系统应用 | 开机自动解锁进入主屏；壁纸、图标、小组件、控制中心、通知中心可用；设置、Safari、短信等系统应用能打开 |
| 图形与显示 | 本项目的 Metal 驱动经 Mesa freedreno 在 Adreno 830 上绘制；按 iPhone 17 的 1206×2622 绘制后缩放到面板，刷新率 120 Hz |
| 触摸与按键 | 触摸、电源键、音量键可用 |
| Wi-Fi | 开机后自动加入 `hackios-xnu-kernel/out/fw-wifi/network` 里写的网络，也可以在设置里加入；Safari 能打开网页，中文显示正常 |
| 安装应用 | 能安装并运行任意解密过的 IPA，见 §6 |
| 电池与温控 | 显示电量；插着充电器时显示充电（墙插充电器下待实测）；处理器和 GPU 按负载调频，过热时逐档降频 |
| 未完成 | 蓝牙、声音、亮度调节、摄像头、蜂窝网络、App Store；网页里的 H.264 视频不能播放（没有硬件解码）；天气取不到数据；手电与振动在 iOS 26 上还不能用 |

性能：在 120 Hz 屏上，翻页约 90～100 帧／秒，控制中心下拉约 90 帧／秒；GPU 最高 1100 MHz，无人值守测试中 GPU 温度最高约 57 °C。

限制：

- 系统和运行数据都在内存里，每次开机都是一份干净的系统，设置、安装的应用和应用数据不保留。
- 运行 iOS 时连着电脑的 USB 也不充电，电量会慢慢下降。

最新状态和实测数据以[总账](docs/plan/2026-10-23-tracking.md)为准，验收目标见[路线图](docs/plan/2026-10-26-roadmap.md)。

## 2. 用 AI Agent 体验

把下面这段话交给 AI Agent，它会按本文和链接的手册完成检查、准备和启动：

```text
请协助我体验 https://github.com/iola1999/hackios-redmi-k90-annibale 。先阅读 README、AGENTS.md 和排查与协作手册，问清我的设备和电脑环境，只读核对机型、bootloader 解锁状态、Android 槽位和分区。建议我先备份重要分区。准备匹配的 K90 构建产物，把 iOS 系统盘装进 Android DSU。写分区或切换槽位前，列出设备、目标、文件哈希和恢复命令，等我确认。启动 iOS 26 后先验收桌面，再逐项试用；结束时切回 Android 并检查数据。不要自动解锁或锁定 bootloader、清数据或修改 GPT。
```

## 3. 准备

- 设备：已解锁 bootloader 的 REDMI K90、可传数据的 USB 线。
- 电脑：`adb`、`fastboot`、Git、Python 3；构建 iOS 26 内核需要 Mac，构建 loader 里的 UEFI 需要 Docker。
- 备份（建议）：写入前备份两个槽位的 `boot` 等重要分区，方法见[分区备份与恢复](docs/backup/README.md)。Wi-Fi 固件也要从备份的 modem 分区里取。

```sh
git clone --recurse-submodules https://github.com/iola1999/hackios-redmi-k90-annibale.git
```

构建产物放在 Git 忽略的目录里，主要是 `hackios-xnu-kernel/out/`：

- 系统盘：`hackios-xnu-kernel/ios26/fetch.sh` 从 iPhone 17 的 iOS 26.6.2 IPSW 取出文件（IPSW 需另行下载），再在 `hackios-xnu-kernel/userland/` 执行 `IOS=../ios26 bash build.sh`，得到约 5.3 GB 的 `system26.apfs`。
- 内核、根盘与 Metal 驱动：见 [k90auto 说明](tools/k90auto/README.md)。
- loader 镜像：见下文「构建 loader 镜像」。
- Wi-Fi 固件：按备份方法读出 modem 分区（本测试机用 `modem_a`），再执行 `python3 hackios-xnu-kernel/tools/mk-fw-wifi.py extract modem_a.img.gz hackios-xnu-kernel/out/fw-wifi`。脚本从分区镜像的 `image/kiwi/` 取出 WCN7850 固件，启动时自动放入驱动读取的 4 个文件。
- 开机种子（建议）：一份开机稳定后的 `/private/var`。没有它时，每次开机主屏图标要等系统重建应用列表后才出现。取法见[每次开机都是首次开机](docs/analysis/2026-10-31-every-boot-is-first-boot.md) §5。

构建 loader 镜像（`hackios-xnu-kernel/out/handoff-loader-v16.img`）分三步，完整命令见 [loader 镜像构建](docs/analysis/annibale-uefi-build.md)：

1. 取 UEFI 源码：loader 镜像里的 UEFI 用 Project Silicium 的 [Mu-Silicium](https://github.com/Project-Silicium/Mu-Silicium) 构建，K90 的修改在 [iola1999/hackios-mu-silicium](https://github.com/iola1999/hackios-mu-silicium)。把它的 `loader-v16` 标签连同子模块克隆到 `hackios-xnu-kernel/Mu-Silicium/`。
2. 构建 UEFI：用 `docker/build.sh` 生成开发容器镜像，`docker/dev.sh` 进入容器；建符号链接 `Binaries/annibale` → `dodge`，运行 `tools/fixup-mu-nasm.sh` 和 `python3 build_uefi.py -d annibale`，得到 `SILICIUM_UEFI.fd`。
3. 装配镜像：用 `xnuloader/build.sh` 编出 loader，`xnuloader/mkpayload.py` 封成载荷，再用 `mkxnuimg.py` 把 BootShim、UEFI、载荷和设备树装成镜像。

## 4. 安装驻留 loader

loader 写进 Android 不用的那个槽位的 `boot` 分区，由它从电脑接收内核并启动 iOS。

下文和 `tools/k90auto/` 的脚本都假设 Android 在 B 槽、loader 写在 A 槽：`cycle.py`、`reboot-lk.py`、`recover-loader.py` 固定执行 `set_active a`。先用下面的 `getvar current-slot` 确认 Android 在 `b`。如果在 `a`，要把下文命令里的 `a`、`b` 对调，并修改这几个脚本。

`LOADER_IMG` 用上一节构建的 `hackios-xnu-kernel/out/handoff-loader-v16.img`，Wi-Fi 需要 v16 起的 loader。

```sh
adb -s "$ANDROID_SERIAL" reboot bootloader
fastboot -s "$ANDROID_SERIAL" getvar current-slot
fastboot -s "$ANDROID_SERIAL" flash boot_a "$LOADER_IMG"
fastboot -s "$ANDROID_SERIAL" set_active a
fastboot -s "$ANDROID_SERIAL" reboot
fastboot devices        # 出现 xnuloader 即成功
```

`flash` 会覆盖 `boot_a`，执行前确认槽位和镜像。

## 5. 把系统盘装进 Android DSU

系统盘有 5 GB 多，每次开机经 USB 上传约要 2 分钟，不利于快速迭代。推荐把它装进 Android 的「动态系统更新」（DSU）：系统盘以文件形式存在手机存储里，loader 每次开机直接读入，约 1.4 秒。DSU 只安装、不启用，Android 照常启动。

安装：手机在 Android、屏幕已解锁，在工作区根目录执行。

```sh
ANDROID_SERIAL="$ANDROID_SERIAL" python3 tools/k90auto/dsu.py install --replace
```

- 需要约 25 GB 空闲空间，手机上可能弹出确认，需要点一下。
- 重建系统盘后要重新安装；内容对不上时，启动脚本会自动改走 USB 上传。
- 移除：在 Android 的「开发者选项 → DSU」或安装程序的通知里丢弃。
- 不装 DSU 也能用，启动时自动经 USB 上传，只是每次多等约 2 分钟；`K90_DSU=0` 强制走 USB。

## 6. 启动并使用 iOS 26

手机处于 loader 或 Android 时，在工作区根目录执行：

```sh
ANDROID_SERIAL="$ANDROID_SERIAL" python3 tools/k90auto/cycle.py use1 --hold --seconds 1800 --tour "home@3*1"
```

脚本会打包、读入系统盘、启动 iOS，等进入主屏后保持运行 `--seconds` 秒，到时自动停止并回到 loader。手机在 Android 时会先自动切到 loader。120 Hz、Wi-Fi 等已验证的功能默认打开。有开机种子时加 `--seed 文件`。`use1` 是这次的标签，每次换一个；日志和截图存在 `docs/progress/evidence/k90auto/` 下同名目录。

可以试的：

- 上滑回主屏、左右翻页、下拉控制中心和通知中心、打开系统应用。
- 用 Safari 上网。Wi-Fi 网络名和密码写进 `hackios-xnu-kernel/out/fw-wifi/network`（第一行网络名，第二行密码，Git 忽略），开机后自动加入；没有这个文件时在「设置 → Wi-Fi」里加入，每次开机要重新加入。

安装应用：iOS 运行期间随时可以装，不用重新打包或重启。两种方式：

- 手机上：用 Safari 下载 `.ipa`，在弹出的提示里点「下载」，约 10 秒后图标出现在主屏。Safari 自己的下载提示会停在下载中或显示失败，不影响安装。
- 电脑上：手机连着 USB 时执行下面的命令，装好后自动打开，40 MB 的 IPA 约 20 秒。

  ```sh
  python3 tools/k90auto/install-ipa.py docs/progress/evidence/k90auto/kernel-12377-rate8-use1 App.ipa --open
  ```

IPA 要是解密过的，App Store 的加密 IPA 不能运行，`install-ipa.py` 发送前会检查并提示。装上的应用重启后就没有了。卸载用 `python3 tools/k90auto/rsh.py <轮次目录> /redwood/bin/appinst remove 应用ID`。

提前结束：`python3 tools/k90auto/respin.py docs/progress/evidence/k90auto/kernel-12377-rate8-use1 --stop`。

## 7. 回到 Android

进入原厂 FASTBOOT（iOS 无响应时长按电源键和音量下；从 loader 用软件进入的方法见[引导目标切换 SOP](docs/plan/device-boot-target-sop.md)），切回 Android 所在的 B 槽：

```sh
fastboot -s "$ANDROID_SERIAL" set_active b
fastboot -s "$ANDROID_SERIAL" reboot
```

切槽只改启动选择，A 槽的 loader 保留。要恢复原来的 `boot_a`，用备份的镜像 `flash` 回去即可。

## 8. 仓库与目录

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
