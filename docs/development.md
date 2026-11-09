# 开发指南

本文说明怎样从源码构建内核、用户态与根盘，组装双系统引导镜像，以及怎样出 Release。只想体验的用户看[体验说明](user-guide.md)即可。接手、排查和真机操作前先读[排查与协作手册](plan/debugging-and-collaboration.md)。

## 1. 环境

- 电脑：构建 iOS 26 的内核和用户态程序需要 Mac 与 Xcode；构建 loader 里的 UEFI、给 Mesa 打补丁需要 Docker（见 [docker/README.md](../docker/README.md)）。另需 `adb`、`fastboot`、Git、Python 3。
- 设备：已解锁 bootloader 且具备 root 权限的 REDMI K90、可传数据的 USB 线。备份方法见[分区备份与恢复](backup/README.md)，Wi-Fi 与蓝牙固件也从备份的分区里取。

下表列出各步骤依赖 macOS 的原因。

| 产物 | 依赖 | 原因 |
|---|---|---|
| 内核（XNU 12377 与 Wi-Fi 驱动） | Xcode | `xnu26/build-macos.sh` 用 Xcode 工具链 |
| 用户态程序、Metal 驱动、注入库 | Xcode | iOS 26 的进程都是 arm64e，带指针认证的 arm64e 只有 Apple clang 能编，见 [arm64e 用户态构建](analysis/2026-10-28-arm64e-userland-build-path.md) |
| AIR 库 `libannibaleair.dylib` | Xcode；补丁准备要 Docker | 同上 |
| 启动卷 `flashboot.apfs`、各程序的签名 | Xcode 的 `ld`、`codesign` | |
| loader 镜像里的 UEFI | Docker | Mu-Silicium 在 Linux 容器里构建 |

合并根盘和封装引导镜像的脚本，以及生成分区表、提取固件的脚本，都是 Python，不依赖 macOS。Release 用户在 macOS 或 Linux 上用 `tools/release/assemble.py` 完成这几步。

## 2. 建立构建树

```sh
git clone --recurse-submodules https://github.com/iola1999/hackios-redmi-k90-annibale.git
cd hackios-redmi-k90-annibale
```

顶层工作区包含 `hackios-xnu-kernel/` 与 `hackios-xnu-userland/` 两个子模块，见[内核仓库说明](../hackios-xnu-kernel/README.md)（[GitHub](https://github.com/iola1999/hackios-xnu-kernel/blob/k90-port/README.md)）§1。构建产物放在 Git 忽略的目录里，主要是 `hackios-xnu-kernel/out/`。

## 3. 下载并解密 IPSW

系统盘只用 IPSW 里的三个镜像，在工作区根目录下载并解密（约 10.4 GB，需要 `brew install sevenzip` 和 Python 的 `cryptography` 包）：

```sh
D=hackios-xnu-kernel/out/ipsw/v57/26; mkdir -p $D
URL=https://updates.cdn-apple.com/2026SummerFCS/c2f9fa07-0acc-4038-99f4-d7a4b1ac9c06/iPhone18,3_26.6.2_23G90_Restore.ipsw
python3 tools/ipsw/fetch.py 094-96558-090.dmg.aea $D/os.dmg.aea "$URL" 11481186987
python3 tools/ipsw/fetch.py 094-95851-092.dmg.aea $D/systemos.dmg.aea "$URL" 11481186987
python3 tools/ipsw/fetch.py 094-96441-094.dmg $D/appos.dmg "$URL" 11481186987
for n in os systemos; do
  python3 tools/ipsw/aea.py $D/$n.dmg.aea $D/$n.dmg
done
hackios-xnu-userland/ios26/fetch.sh
```

`tools/ipsw/aea.py` 是 macOS `aea decrypt` 的 Python 实现，两者解出的镜像逐字节相同；macOS 上也可以继续用 `aea decrypt -i $D/$n.dmg.aea -o $D/$n.dmg -key-value "base64:$(python3 tools/ipsw/aea-key.py $D/$n.dmg.aea)"`。`ios26/fetch.sh` 用 `hdiutil` 挂载镜像，把系统文件复制到 `hackios-xnu-userland/ios26/`，供用户态构建生成启动任务。

## 4. 提取硬件固件

这三类固件要在打包根盘前准备好。

- GPU 固件：按 [Adreno 830 固件说明](../hackios-xnu-userland/firmware-gen8/README.md)（[GitHub](https://github.com/iola1999/hackios-xnu-userland/blob/k90-port/firmware-gen8/README.md)）把 `gen80000_gmu.bin`、`gen80000_sqe.fw`、`gen80000_aqe.fw` 放进 `hackios-xnu-kernel/fw-gpu/`，再用 `adb -s "$ANDROID_SERIAL" pull /odm/firmware/gen80000_zap.mbn hackios-xnu-kernel/fw-gpu/` 从手机取出签名固件。
- Wi-Fi 固件（WCN7850）：从手机读出 `modem_a` 分区，执行 `python3 hackios-xnu-kernel/tools/mk-fw-wifi.py extract modem_a.img.gz hackios-xnu-kernel/out/fw-wifi`。`package.py` 把其中 `amss20.bin`、`regdb.bin`、`bd_p11.elf`、`phy_ucode20.elf` 4 个文件合并进根盘的 `fw/`。
- 蓝牙固件（WCN7850，可选）：从手机读出 `bluetooth_a` 分区，执行 `python3 hackios-xnu-kernel/tools/mk-fw-bt.py extract bluetooth_a.img.gz hackios-xnu-kernel/out/fw-bt`，得到 `hmtbtfw20.tlv`、`hmtbtfw20.ver`、`hmtnv20.bin`。

## 5. 构建内核

按[内核仓库说明](../hackios-xnu-kernel/README.md) §2 构建。执行 `xnu26/build-macos.sh` 之前必须先运行 `hackios-xnu-kernel/tools/mk-ath12k.sh`，生成 `hackios-xnu-kernel/xnu-deps/build/ath12k/out/ath12k.o`；`build-macos.sh` 只在该文件存在时把 WCN7850 的 `ath12k` 驱动与 FreeBSD LinuxKPI 层链接进内核，缺少时编出的内核没有 Wi-Fi。

内核编好后在工作区根目录执行 `python3 tools/k90auto/register-kernel.py 12377-local` 登记，内核复制为 `hackios-xnu-kernel/out/xnu12377-local.bin`。

## 6. 构建用户态与启动卷

在 `hackios-xnu-userland/userland/` 执行：

```sh
IOS=../ios26 bash build.sh                                   # 只要根盘基线时加 COMPILE_ONLY=1
FLASHBOOT=1 FLASHBOOT_ONLY=1 CRYPTEXES=flash bash build.sh   # 只含 stage0 与挂载目录的 flashboot.apfs
```

- 第一条生成根盘基线目录 `userland/root/`；不加 `COMPILE_ONLY=1` 时还生成约 5.9 GB 的合成系统盘 `system26.apfs`。双系统部署直接写入原版三个镜像时只需要基线目录。
- 根盘里会放进本机 `../ssh/authorized_keys` 等 ssh 密钥（存在时）。要分发的构建加 `SHARE=1`，`build-release.py` 发现 ssh 密钥会拒绝出包。
- 系统卷部署在 UFS `darwin` 分区，启动过程见[根文件系统说明](analysis/rootfs-strategy.md)。

## 7. 打包根盘

先按 [arm64e 用户态构建 §6](analysis/2026-10-28-arm64e-userland-build-path.md#6-构建树从仓库重建) 运行 `python3 tools/k90auto/setup-mesa-arm64e.py` 与 `python3 tools/k90auto/build-air.py`，编译并签名 `libannibaleair.dylib`。再在工作区根目录执行 `python3 tools/k90auto/package.py`，打包开关见 [k90auto 说明](../tools/k90auto/README.md) §7。

`package.py` 基于 `userland/root/` 编译并注入 Metal 驱动与各个注入库，合并 Wi-Fi、蓝牙固件，输出 `hackios-xnu-kernel/out/ios26-resume/bbmetal-device/root/`（根盘目录）和同目录的 `root.apfs`。

## 8. 构建 loader 与双系统引导镜像

完整细节见 [loader 镜像构建](analysis/annibale-uefi-build.md)。

1. 取 UEFI 源码：把 [iola1999/hackios-mu-silicium](https://github.com/iola1999/hackios-mu-silicium) 的 `k90-port` 分支连同子模块克隆到 `hackios-xnu-kernel/Mu-Silicium/`。
2. 构建 UEFI：用 `docker/build.sh` 生成开发容器镜像，`docker/dev.sh` 进入容器；建符号链接 `Binaries/annibale` → `dodge`，运行 `tools/fixup-mu-nasm.sh` 和 `python3 build_uefi.py -d annibale`，得到 `SILICIUM_UEFI.fd`，再按该文档第 3 节装配参考 loader 镜像。
3. 合并内核、辅助盘、启动卷与 loader：

```sh
# 1. 编译 xnuloader（BUILD_ID 填 xnuloader/ 所在的源码提交）
(cd hackios-xnu-kernel && EXTRA_CFLAGS=-DDIRECT_PHONE_PLAT BUILD_ID=<40 位提交> xnuloader/build.sh)

# 2. 合并内核、辅助盘和启动卷
python3 hackios-xnu-kernel/xnuloader/mkstandalone.py --no-lz4 \
  --kernel hackios-xnu-kernel/out/xnu12377-local.bin \
  --ramdisk hackios-xnu-kernel/out/ios26-resume/bbmetal-device/root.apfs \
  --boot-image hackios-xnu-userland/userland/flashboot.apfs \
  -o hackios-xnu-kernel/out/standalone-payload.bin

# 3. 用参考 loader 镜像封装 boot-a-ios.img
python3 hackios-xnu-kernel/tools/reseal-loader-img.py \
  hackios-xnu-kernel/out/handoff-loader-v19.img \
  hackios-xnu-kernel/out/standalone-payload.bin \
  -o hackios-xnu-kernel/out/boot-a-ios.img
```

`reseal-loader-img.py` 原样保留参考镜像里的 BootShim、UEFI、设备树和 ramdisk，只替换载荷。

## 9. 部署与真机调试

- 分区、写系统盘、刷入引导镜像和 Android 更新的影响：[双系统分区与持久化部署手册](plan/dual-boot-setup.md)。
- 引导目标切换与陷阱：[引导目标切换 SOP](plan/device-boot-target-sop.md)。
- 驻留 loader、手工运行内核、读日志：[真机调试手册](plan/device-test-playbook.md)。
- 无人值守跑轮与通过 USB 安装 `.ipa`（`install-ipa.py`）：[k90auto 说明](../tools/k90auto/README.md)。

## 10. 出 Release

Release 只放本项目的文件。根盘里来自 IPSW 的文件（launchd 任务与缓存、`/private/var` 模板和少量原样复制的系统文件）和手机厂商固件不进 Release，改为记录生成方法，由用户在本地用 `tools/release/assemble.py` 从自己的 IPSW 和手机重新生成。

1. 三个仓库的改动都已提交并推送，然后在本机重新克隆一份，目录不限。`xnu26/build-macos.sh` 与 `tools/mk-ath12k.sh` 用 `-ffile-prefix-map` 把内核里 `__FILE__` 的路径改成相对源码目录的路径，产物里不再有本机目录；`build-release.py` 仍会检查，发现本机用户目录时拒绝出包。已有构建树里旧的目标文件不会因为参数变化自动重编，所以要用新克隆。
2. 在这份克隆里按第 2～8 节构建全部产物，再执行 `bash hackios-xnu-kernel/tools/android/build.sh` 编译安卓端分区工具。
3. 在工作区根目录执行：

```sh
python3 tools/release/build-release.py vX.Y.Z \
  --kernel hackios-xnu-kernel/out/xnu12377-local.bin \
  --loader-image hackios-xnu-kernel/out/handoff-loader-v19.img \
  --expect-boot hackios-xnu-kernel/out/boot-a-ios.img
```

`build-release.py` 依次做下面几件事，任一项不满足就停止。

- 检查三个仓库没有未提交的改动，记录各自的提交。
- 把根盘目录拆成本项目文件和生成方法：与 IPSW 文件逐字节相同的文件、由 iOS 原文件加上本项目改动得到的 plist、launchd 缓存、`/private/var` 模板、手机固件。
- 用本机的 IPSW 提取结果按生成方法重新生成每个文件，重新打包根盘，结果必须与 `package.py` 输出的 `root.apfs` 逐字节相同。
- 把参考 loader 镜像的载荷换成只含 loader 的最小载荷，作为 Release 里的 loader 外壳；用外壳与参考镜像分别封装，结果必须相同，给了 `--expect-boot` 时还要与它相同。
- 检查包内没有 ssh 密钥和本机用户目录，输出 `out/release/hackios-k90-vX.Y.Z.tar.gz` 与 `.sha256`。末尾的 review 行列出以 Apple 名称命名、但作为本项目文件放进 Release 的文件，发布前逐个确认来源。

4. 发布前在一台 Linux 机器或容器里解包，按[体验说明](user-guide.md)第 4～6 步合成一次，确认输出「holds exactly the release's files」或「byte for byte」；有条件时按第 7 步在真机临时启动。
5. 发布：

```sh
gh release create vX.Y.Z out/release/hackios-k90-vX.Y.Z.tar.gz out/release/hackios-k90-vX.Y.Z.tar.gz.sha256 \
  --title "vX.Y.Z（YYYY-MM-DD）" --notes-file <发布说明>
```

不要勾选「pre-release」：GitHub 的 `releases/latest` 不返回预发布版本，体验说明里「下载最新版」会找不到文件。项目的实验性质写在发布说明里。

## 11. 版本号

Release 的版本号用 `v主版本.次版本.修订号`，从 `v0.1.0` 开始。构建日期写在 Release 标题和 `manifest.json` 里，不放进版本号。

- 修订号：用户只需重新合成并刷入 `boot-ios.img`，分区、系统盘和数据盘都保留。内核、驱动、用户态修复通常属于这一类。
- 次版本号：用户还要做别的操作，例如重写系统盘（换 iOS 版本）、调整分区、清空或迁移 `darwin_var`。发布说明写清楚要做什么。
- 主版本号：保持 0，直到项目不再是实验性质。

每个 Release 绑定一个 iOS 版本：`manifest.json` 记录三个镜像的大小，生成方法记录每个生成文件的 SHA-256，用其他版本的 IPSW 合成时 `assemble.py` 会停下。换 iOS 版本要升次版本号。
