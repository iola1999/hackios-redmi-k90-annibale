# 体验说明

本文面向想在自己的 REDMI K90 上体验 iOS 26 的用户：从 Release 下载预构建包，在电脑上用自己的 IPSW 和手机固件合成引导镜像，再划分分区、写入系统盘并刷入引导镜像。全程不需要 Xcode 和 Docker。

项目仍在实验阶段，目前只在一台 256 GB 的 K90 上验证过。写分区和刷机有风险，开始前请备份个人数据。

## 1. 交给 AI Agent

把下面这段话交给 AI Agent，它会按本文做完检查和准备，再分区、启动：

```text
请协助我体验 https://github.com/iola1999/hackios-redmi-k90-annibale 。按仓库里的 docs/user-guide.md 操作，遇到细节再读其中链接的手册。先问清我的电脑系统、手机存储容量和想给 iOS 数据盘分多少空间；只读核对机型、bootloader 解锁状态、root、当前 Android 槽位和 UFS LUN 0 分区表，并建议我先备份。从 Releases 下载最新版并校验，准备 IPSW、读取手机固件、合成引导镜像，划分区之前先临时启动确认屏幕能显示开机菜单。每次写分区、写系统盘、刷引导镜像或切换槽位前，列出设备、目标分区、LBA 范围、文件哈希和恢复方法，等我确认。不要解锁或锁定 bootloader。
```

## 2. 准备条件

手机：

- REDMI K90（代号 `annibale`），bootloader 已解锁，Android 已用 Magisk 或 KernelSU 获取 root。
- `/data` 剩余空间要能让出 iOS 的两个分区：系统盘 16 GiB，数据盘大小自选。写系统盘时还要在 `/data/local/tmp` 暂存单个最大约 9.8 GB 的文件。

电脑（macOS 或 Linux；Windows 请用 WSL，未验证）：

- Python 3.10 或更新版本，以及 Python 包 `cryptography`（`pip install cryptography`，Ubuntu 也可以 `apt install python3-cryptography`）。
- 7-Zip 23 或更新版本：macOS 用 `brew install sevenzip`，Ubuntu 24.04／Debian 12 用 `apt install 7zip`。
- Linux 另外需要 LZFSE 库，用于解密 IPSW：`apt install liblzfse1`。
- `adb` 与 `fastboot`，以及约 30 GB 空闲磁盘空间。

开始前按[分区备份与恢复](backup/README.md)备份两个槽位的 `boot` 等分区和个人数据。下文命令里的 `$ANDROID_SERIAL` 是手机的序列号（`adb devices` 第一列），每条设备命令都带上它。

## 3. 下载 Release

在 [Releases](https://github.com/iola1999/hackios-redmi-k90-annibale/releases) 下载 `hackios-k90-vX.Y.Z.tar.gz` 和同名的 `.sha256` 文件，校验后解包：

```sh
shasum -a 256 -c hackios-k90-vX.Y.Z.tar.gz.sha256    # Linux 可用 sha256sum -c
tar xzf hackios-k90-vX.Y.Z.tar.gz
cd hackios-k90-vX.Y.Z
```

- 包里有内核、loader 与启动卷，本项目的根盘文件，以及合成脚本和安卓端分区工具；不含 iOS 文件和手机厂商固件。
- `manifest.json` 记录版本号、构建日期、对应的 iOS 版本（目前是 iOS 26.6.2，23G90）和三个仓库的源码提交。
- 下文命令都在解包后的目录里执行。

## 4. 准备 iOS 系统镜像

从 Apple 的服务器下载 iPhone 17 的 IPSW 里的三个磁盘镜像并解密，约下载 10.4 GB，解密后约占 15 GB：

```sh
python3 tools/release/assemble.py ipsw ipsw
```

完成后 `ipsw/` 里有 `os.dmg`、`systemos.dmg` 与 `appos.dmg`。下载中断可以重新执行同一条命令，已下载完的镜像会跳过。

## 5. 读取手机固件

GPU、Wi-Fi 与蓝牙固件从你自己的手机读出，Android 开机并连接电脑后执行：

```sh
mkdir -p fw
adb -s "$ANDROID_SERIAL" pull /odm/firmware/gen80000_zap.mbn fw/
adb -s "$ANDROID_SERIAL" shell su -c "dd if=/dev/block/by-name/modem_a bs=4096 2>/dev/null" | gzip -1 > fw/modem_a.img.gz
adb -s "$ANDROID_SERIAL" shell su -c "dd if=/dev/block/by-name/bluetooth_a bs=4096 2>/dev/null" | gzip -1 > fw/bluetooth_a.img.gz
```

这些文件属于手机厂商，只用于自己的手机，不要分享或提交到任何仓库。

## 6. 合成引导镜像

```sh
python3 tools/release/assemble.py build --ipsw ipsw --modem fw/modem_a.img.gz \
  --bluetooth fw/bluetooth_a.img.gz --zap fw/gen80000_zap.mbn -o out
```

脚本从 IPSW 取出需要的系统配置，按 Release 记录的改动重新生成，再合并固件，得到 `out/root.apfs` 与 `out/boot-ios.img`。每个生成的文件都会和 Release 记录的 SHA-256 比对，不一致时脚本会停下并报出文件名。脚本最后会输出下面三种结论之一。

- 「both images are byte for byte the release's」：两个镜像与 Release 测试时的完全一致。
- 「holds exactly the release's files」：根盘里的文件与 Release 完全一致；电脑上的 zlib 版本不同，压缩出的字节不同，不影响使用。
- 「firmware differs from the tested version」：手机固件版本与测试机不同，其余文件与 Release 一致；这种组合没有测试过。

## 7. 临时启动，检查屏幕

划分分区前，先从内存临时启动 Release 包里的 loader 外壳 `payload/loader-shell.img`，确认这台手机的屏幕能显示开机菜单。外壳里只有 loader，不带内核，这一步不写入手机：

```sh
adb -s "$ANDROID_SERIAL" reboot bootloader
fastboot -s "$ANDROID_SERIAL" boot payload/loader-shell.img
```

- 约 20 秒后屏幕出现「HACKIOS K90 BOOT MENU」和 5 秒倒计时，菜单项后面不显示槽位，因为两个 `boot` 分区里都还没有 loader 镜像。
- 在倒计时内选「[2] BOOT ANDROID」并按电源键确认，手机重启回到 Android。不操作时倒计时结束后屏幕显示「NO KERNEL - FASTBOOT MODE」，进入 USB 调试模式，执行 `fastboot -s xnuloader reboot` 或长按电源键重启，同样回到 Android。
- 屏幕一直黑屏或花屏时停止后续步骤，长按电源键回到 Android，并在 Issues 里附上手机型号与 Android 版本。loader 里的屏幕配置取自测试机，其他批次的屏幕可能不兼容。

## 8. 划分分区

按[双系统分区与持久化部署手册](plan/dual-boot-setup.md#2-在线缩容与写入-gpt-分区表)第 2 节，在同一个 Android root 会话里缩小 `/data` 并写入新的分区表，中途不要重启。

- 手册用到的脚本 `hackios-xnu-kernel/tools/userdata-dual-carve.py` 已在 Release 包的同一路径下。
- 手册第一步编译的 `f2fs-resize` 不用自己编译，改为推送 Release 包里的 `android/f2fs-resize`。
- 手册里的 `sda34`、`dm-55`、LBA 等数值来自测试机，以本机实际读到的值和脚本打印的命令为准。

## 9. 写入系统盘

按部署手册[第 3 节](plan/dual-boot-setup.md#3-写入-ios-系统盘)把三个镜像写入 `darwin` 分区，命令里的 `IPSW_DIR` 改成第 4 步的 `ipsw`。`seek` 偏移以第 8 步脚本打印的 `darwin` 起始 LBA 为准。

## 10. 刷入引导镜像

先查当前 Android 所在的槽位，再把引导镜像刷进另一个槽位。下面以 Android 在 `b` 槽为例；Android 在 `a` 槽时改用 `boot_b` 与 `set_active b`：

```sh
adb -s "$ANDROID_SERIAL" reboot bootloader
fastboot -s "$ANDROID_SERIAL" getvar current-slot
fastboot -s "$ANDROID_SERIAL" flash boot_a out/boot-ios.img
fastboot -s "$ANDROID_SERIAL" set_active a
fastboot -s "$ANDROID_SERIAL" reboot
```

loader 开机时检查两个槽位的 `boot` 分区，装着 loader 镜像的是 iOS 这一侧，另一侧是 Android，不需要额外设置。

## 11. 日常使用与切换

- 开机进 iOS 26：按电源键开机，开机菜单倒计时 5 秒后自动进入 iOS 26。
- 从 iOS 切回 Android：重启后在倒计时内选「[2] BOOT ANDROID」并按电源键确认，loader 会切换活动槽位并重启进入 Android。
- 从 Android 切回 iOS：在 root 终端或 `adb shell` 里把活动槽位切到 loader 所在的槽位（`0` 对应 `a`，`1` 对应 `b`）并重启，例如 `su -c 'bootctl set-active-boot-slot 0 && reboot'`。
- 联网：在「设置 → Wi-Fi」中加入网络，重启后自动保留。
- 安装应用：用 Safari 下载已解密的 `.ipa`，下载完成约 10 秒后图标出现在主屏；也可以打开「安装包管理器」查看、启动或卸载已安装的应用。

## 12. 升级

Release 的版本号是 `v主版本.次版本.修订号`，升级方式取决于哪一段变了。

- 只有修订号变化（例如 `v0.1.0` → `v0.1.1`）：按第 3、5、6 步合成新的 `boot-ios.img`，按第 10 步刷进 loader 所在的槽位即可，数据保留。第 4 步的 `ipsw/` 可以沿用。
- 次版本号或主版本号变化：可能需要重写系统盘、调整分区或清空数据盘，按该版本的发布说明操作。

Android 系统更新对双系统的影响分三种情况。

- 系统内 OTA 不改动 `darwin` 与 `darwin_var`，iOS 数据保留。
- 完整包 OTA 会把新 Android 写进 loader 所在的槽位，覆盖引导镜像。更新完成后把 `boot-ios.img` 刷进新的闲置槽位并切换过去即可，细节见部署手册第 5 节。
- 原厂线刷包的 `flash_all.sh` 会重建分区表并清空 `userdata`，`darwin` 与 `darwin_var` 也会被抹掉。

## 13. 卸载

1. 切回 Android，按部署手册[第 6 节](plan/dual-boot-setup.md#6-恢复原厂分区表)写回第 8 步备份的分区表，重启后 `/data` 自动扩回原来的大小。
2. 在 LK 的 fastboot 里把第 2 步备份的原厂 `boot` 刷回 loader 所在的槽位。

## 14. 已知问题

- 只在一台测试机上验证过；屏幕、存储容量或 HyperOS 版本不同的机器可能无法显示或启动，先按第 7 步检查。
- 内核启动参数里的 Wi-Fi MAC 地址是固定值，所有人的手机相同；同一个网络里接入两台时会冲突。
- 功能完成情况见 [README](../README.md) 的进展表，排查方法见[排查与协作手册](plan/debugging-and-collaboration.md)。
