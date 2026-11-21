# Release 执行清单

每次发版按本清单从上到下执行。命令和脚本行为见[开发指南 §10](../development.md#10-生成-release)，版本号规则见[开发指南 §11](../development.md#11-版本号)；本清单列出每一步的检查点，以及以前发版时出过的问题和现在的检查方法。发版中遇到新问题，修好后把检查写回本清单，与发布记录一起提交。

## 1. 定版本号与发布范围

- 按开发指南第 11 节定版本号。要调整分区、迁移或清空 `darwin_var`、换 iOS 版本时升次版本号；用户只需重新合成并刷入 `boot-ios.img` 时升修订号。
- 三个仓库各自执行 `git log <上一版标签>..HEAD`，按用户可见的变化归类。每一条进展都要有提交说明、进度表或专题文档里的真机或主机验证来源，没有来源的不写进发布说明。
- 按用户的来源版本分别列出升级操作：只刷引导镜像、迁移数据盘、调整分区，还是重写系统盘。每种操作都要对应体验说明或部署手册里的一节，发布说明只写顺序和链接。

## 2. 发版前的仓库状态

- 三个仓库的改动已提交并推送。提交前运行 `python3 tools/check-docs.py` 和改动相关的主机测试，推送前按 AGENTS.md 第 3 节检查推送范围的隐私信息。
- 判断某个改动有没有进入发布分支时，用 `git log k90-port -- <文件>` 看文件历史，再比对文件内容。只看某个提交是否为祖先会误判：内容可能经整合提交合入。v0.2.0 准备时曾以为硬件 CRC32 没有合入，实际 11-13 已由内核 `c722b945` 合入，`v0.1.4` 也带着它。
- 日常工作区的构建树不能作为发布依据。`xnu26/build-macos.sh` 只把覆盖目录里的文件复制进 `xnu-src`，不会还原已经不在覆盖目录里的文件，构建过其他分支后树里会留下那些文件。发布一律在新克隆里构建，并按第 4 节比对内核字节。

## 3. 新克隆与仓库外的输入

在工作区旁边新建克隆，目录名带版本号，例如 `git clone --recurse-submodules https://github.com/iola1999/hackios-redmi-k90-annibale.git ../hackios-release-vX.Y.Z`，再按开发指南第 10 节第 2 步复用 IPSW、提取结果、固件和参考 loader。

- `hackios-xnu-userland/fw-camera` 在日常工作区是指向 `../hackios-xnu-kernel/out/fw-camera` 的符号链接，`cp -R` 只复制链接本身。开发指南第 10 节第 2 步的命令同时复制 `hackios-xnu-kernel/out/fw-camera` 目录；漏掉时 `build-all.sh` 开头报缺少 `com.qti.sensormodule.*`。
- `build-all.sh` 的 ios 步骤把 `hackios-xnu-kernel/out/ipsw/v57/26` 作为 `IPSW_DIR` 传给 `fetch.sh`（顶层 `36dbbfb`）。此前 `fetch.sh` 按内核检出里的 `ios26` 链接推算 IPSW 目录，新克隆还没有这个链接，ios 步骤报 `no ../out/ipsw/v57/26/os.dmg`。
- 内核检出里指向用户态仓库的链接（`userland`、`ios26`、`tools/apfs`、`tools/mesa`）由 `package.py` 启动时补建，不需要手工创建。
- 需要的 Docker 镜像：`hackios-dev:latest`（Mesa 补丁准备）和 `ubuntu:24.04` 的 arm64、amd64 两个平台（Linux 版 `apfs-tool`，第一次构建会联网拉取镜像和软件包）。

## 4. 构建与比对

在新克隆根目录执行 `tools/release/build-all.sh > out-build-all.log 2>&1`，每一步的日志在 `out/release-build/<步骤>.log`。脚本退出码为 0 只说明每一步的命令成功，下面几项还要逐一核对。

- 每一步的用时与上一版对照，明显偏快或偏慢时先读日志再继续。v0.2.0 在本机（30 核）上内核全量构建约 80 秒、Mesa 37 秒、打包 9 秒；`v0.1.4` 的内核用了约 40 分钟，当时告警屏蔽没有生效，日志约 800 MB。
- 内核：新克隆的 `hackios-xnu-kernel/out/xnu12377-local.bin` 与最后一次真机验证的内核比 SHA-256。不同时先查清差异来源，不能直接发布。v0.2.0 与 `12377-nvram1` 逐字节相同。日常增量构建按 [k90auto 说明](../../tools/k90auto/README.md)每次换新的 `KERNEL_UUID`，发布构建用 `xnu26/build-macos.sh` 的默认值，两者的 LC_UUID 不同；比对前先把真机内核的 LC_UUID 改成默认值，再比 SHA-256。
- loader：`build-all.sh` 用最后一个改动 `xnuloader/` 的提交作为 `BUILD_ID`，与测试机上 `fastboot -s xnuloader getvar build-id` 读到的值对照。
- 引导镜像：`python3 -I hackios-xnu-kernel/prebuilt/avb/avbtool.py info_image --image hackios-xnu-kernel/out/boot-a-ios.img` 显示 96 MiB 的镜像和指向 vbmeta 的页脚。原因见第 9 节的 AVB 页脚一项。
- `apfs-tool`：`out/apfs-tool/` 里有 `apfs-tool-Darwin`、`apfs-tool-Linux-x86_64`、`apfs-tool-Linux-aarch64`。macOS 版用 `lipo -info` 确认含 arm64 与 x86_64，`vtool -show-build` 的 `minos` 为 13.0，`otool -L` 只依赖 `/usr/lib` 下的系统库；Linux 版用 `file` 确认为静态链接。
- 每个 `apfs-tool` 都用转换测试跑一遍：`APFS_TOOL=<程序> python3 hackios-xnu-userland/tools/apfs/test_annfs.py --rounds 2 --objects 3000`。测试用 `hackios-xnu-userland/xnu-deps/build/apfsprogs/apfsck/apfsck` 检查结果，新克隆里没有它，在日常工作区运行，或先在新克隆执行 `build-apfsck.sh`。`tools/apfs` 自上一版没有改动、程序与上一版发布记录的 SHA-256 相同时，至少跑本机架构一遍。x86_64 的 macOS 版用 `arch -x86_64` 包一层，Linux 版用 `docker run --platform linux/<平台>` 包一层，并把 `/var/folders` 挂到容器里的同一路径。

## 5. 生成发布包

在新克隆根目录执行开发指南第 10 节第 4 步的 `build-release.py`，带上 `--expect-boot hackios-xnu-kernel/out/boot-a-ios.img`。

- 报「firmware this script does not know」时，根盘 `fw/` 里多了手机来源的文件，按开发指南第 10 节「发布配方的维护」补生成配方、`assemble.py` 的输入和体验说明第 5 步。改动先在日常工作区提交推送，克隆里 `git pull` 和 `git submodule update` 后再生成；改之前可以把改过的脚本复制进克隆，用 `--allow-dirty -o out/release-trial` 试跑，试跑后还原。

- 解包核对文件清单：新增的脚本和程序都在包里（v0.2.0 起包括 `annfs-to-apfs.py`、`build-apfsck.sh`、`apfsprogs-host.patch`、`avbtool.py` 和三个 `apfs-tool`），`manifest.json` 的三个提交与已推送的提交一致。
- 末尾的 review 行逐个确认来源，「property list edits carry N bytes」与上一版对照没有明显增大。
- 生成手机固件的脚本（`camsensor.py`、`camtuning.py`）在 `userland/build.sh` 里的参数有变化时，同步 `build-release.py` 的 `CAMERA_PROFILES`、`CAMERA_TUNINGS` 和 `assemble.py` 的调用。`build-release.py` 不重新生成这些文件，参数不一致只在第 6 节合成时报「the phone's firmware differs」。
- `assemble.py` 或 `localfiles.py` 有改动时，按开发指南第 10 节第 5 步在 Linux 容器里解包合成一次。

## 6. 上机验证

用发布包在 macOS 上执行一次 `assemble.py build`，把得到的 `boot-ios.img` 刷进测试机，确认用户拿到的镜像能启动。设备操作遵守 AGENTS.md 第 5 节。

- 经 `tools/k90auto/reboot-lk.py` 从驻留 loader 进入 LK，记录 `fastboot getvar max-download-size`。loader 外壳有变化时，按体验说明第 7 步用 `fastboot boot payload/loader-shell.img` 临时启动一次，看到开机菜单后再回到 LK。
- `fastboot flash boot_a`、`set_active a`、`reboot`，确认 loader 的 `build-id`、内核版本与第 4 节一致，默认镜像自动启动到锁屏和主屏。
- 体验说明里新增或改动的命令，在测试机的 Android 下原样执行一遍，再用读出的文件合成刷机用的镜像。
- 按本版的进展逐项抽查，至少覆盖需要用户操作的部分（v0.2.0 为 APFS 数据卷、NVRAM 与背光、panic 日志保存）。功能结论看用户最终看到的状态：背光要看开机完成后的亮度，不能只看驱动启动时的值。
- 验证结束后设备留在 iOS 桌面。

## 7. 发布说明

发布说明分四节：本版进展、已知问题与验证范围、安装与升级、源码。

- 进展只写有来源的结果，数字与出处一致；验证只在一台测试机上完成的写明。
- 安装与升级按来源版本分别写。需要用户执行命令的，给出完整命令或带标签的文档链接（`blob/vX.Y.Z/...`），写明顺序、每一步失败时数据是否已改动、能否回退。
- 已知问题包括本版新引入的风险和没有验证的路径。
- 中文写作规则同其他文档：直接写结论和操作，不写宣传语。

## 8. 发布、标签与记录

- `gh release create vX.Y.Z <tar.gz> <.sha256> --title "vX.Y.Z（YYYY-MM-DD）" --notes-file <发布说明>`，不勾选 pre-release。发布后用 `gh release view` 核对附件摘要与本地一致。
- 三个仓库在发布提交上打 `vX.Y.Z` 标签并推送。
- 写发布记录 `docs/progress/<日期>-release-vX.Y.Z.md`（范围、产物摘要、构建与上机校验、本次发现的问题），进度表加一行，文档入口加链接；本次遇到的新问题同时写进本清单第 9 节。

## 9. 历次发版遇到的问题

| 版本 | 问题 | 处理与现在的检查 |
|---|---|---|
| v0.1.4 | 新克隆缺少内核检出里指向用户态仓库的未跟踪链接，`package.py` 和 Mesa 准备步骤找不到文件 | `package.py` 启动时补建（第 3 节） |
| v0.1.4 | 日常 Mesa 构建树缺补丁 `0018`，从仓库重建的 AIR 库与设备上的不同 | `build-air.py` 比对补丁摘要后才构建 |
| v0.1.4 | `build-macos.sh` 的告警屏蔽参数不生效，全量构建日志约 23 万条告警 | 已修正；第 4 节对照各步骤用时 |
| v0.1.4 | GPU 固件的文档位置写错；相机寄存器表、`AVCaptureSession.plist` 和 Angel 任务的缓存键没有发布配方 | 已补齐；新增手机来源文件时按开发指南第 10 节「发布配方的维护」处理 |
| v0.1.4 | 设备恢复时 `oem recovery` 两次中一次赶不上启动菜单窗口 | 上机前按[引导目标切换 SOP](device-boot-target-sop.md) 收敛到 `idle` 的驻留 loader |
| v0.2.0 | 复制输入时 `fw-camera` 只复制了符号链接 | 开发指南第 10 节第 2 步同时复制 `hackios-xnu-kernel/out/fw-camera`（第 3 节） |
| v0.2.0 | 新克隆的 ios 步骤找不到 IPSW | `build-all.sh` 显式传入 `IPSW_DIR`（第 3 节） |
| v0.2.0 | 把已合入的硬件 CRC32 误判为只在本地构建树里 | 按文件历史和内容判断（第 2 节）；第 4 节比对内核字节 |
| v0.2.0 | 测试机刷入 24,373,248 字节的 loader 镜像后，A 槽被 LK 标为不可启动：`boot_a` 末尾残留的 AVB 页脚指向 23,699,456 字节处的 vbmeta，被新镜像覆盖 | `reseal-loader-img.py` 输出 96 MiB 并带镜像自己的页脚（内核 `db943b83`）；第 4 节检查 `info_image` |
| v0.2.0 | 根盘新增由手机 Chromatix 调校文件生成的 `fw/camera-*.isp`，`build-release.py` 报未知固件 | `build-release.py` 加 `CAMERA_TUNINGS`，`assemble.py` 从 `--camera` 目录读取调校文件，体验说明第 5 步增加读取命令（第 5 节） |
| v0.2.0 | `camtuning.py` 说明把调校文件的手机路径写成 `/vendor/lib64/camera/`，实际在 `/odm/lib64/camera/` | 体验说明新增的命令在测试机上原样执行（第 6 节） |
| v0.2.0 | 发布说明草稿按驱动启动值写了「亮度跨重启保留」，发布镜像上 CoreBrightness 随后把亮度设为 140 nits | 功能结论按开机完成后用户看到的状态核对（第 6 节） |
| v0.2.0 | 本机编出的 `apfs-tool` 的 `minos` 是本机系统版本（27.0），并依赖 Homebrew 的 OpenSSL 动态库；Linux 上新写入引擎用到的 `ENOATTR`、`__unused` 和 `os/base.h` 在 glibc 里没有 | macOS 版用 CommonCrypto 并指定最低 macOS 13，Linux 版补兼容头并静态链接（用户态 `c86af29`）；第 4 节检查依赖并逐个跑转换测试 |
| v0.2.1 | 在新克隆里运行 `test_annfs.py` 报找不到 `apfsck` | 在日常工作区运行或先编译 `apfsck`（第 4 节） |
| v0.2.2 | 新克隆的内核与真机验证的 `12377-lens` 有 16 字节不同，位置是 LC_UUID：日常构建每次换 `KERNEL_UUID`，发布构建用固定值 | 把真机内核的 LC_UUID 改成默认值后比 SHA-256（第 4 节） |
| v0.2.2 | `camtuning.py` 改为按传感器模式的读出区域映射镜头阴影表（内核 `aa069aef`），多了模块文件和模式号两个参数；`assemble.py` 仍只传调校文件，用户合成的 `camera-*.isp` 与根盘里的不同，合成时报「the phone's firmware differs」 | `CAMERA_TUNINGS` 同时记录模块文件和模式号，`assemble.py` 一并传给 `camtuning.py`。`build-release.py` 不重新生成手机固件，这类差异只在第 6 节合成时出现；生成固件的脚本参数有变化时，对照 `userland/build.sh` 检查发布配方 |
