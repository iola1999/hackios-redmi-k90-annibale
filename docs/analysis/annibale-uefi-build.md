# annibale UEFI 与 loader 镜像构建

驻留 loader 镜像（`hackios-xnu-kernel/out/handoff-loader-vN.img`）是 header v1 的 Android boot 镜像：kernel 段为 `gzip(BootShim + UEFI FD + XNUP 容器)`，后接合并设备树。UEFI FD 用 Mu-Silicium 构建，XNUP 容器里是 `xnuloader/` 编出的 loader。`out/` 是 Git 忽略的本地构建目录，镜像需要按本文自己构建。

## 1. 源码

- [iola1999/hackios-mu-silicium](https://github.com/iola1999/hackios-mu-silicium)：[Project-Silicium/Mu-Silicium](https://github.com/Project-Silicium/Mu-Silicium) 的副本，许可证 BSD-2-Clause。`main` 是上游 `42fe563` 的导入；`k90-port` 增加 `Platforms/Xiaomi/annibalePkg`（从同为 SM8750 的 OnePlus 13R `dodgePkg` 复制后修改）、`Resources/Configs/annibale.toml`，以及 BootManager 里启动 XNU loader 的改动。
- 标签 `loader-v16`：loader v6～v16 镜像里 FD 的源码状态。这些镜像里的 FD 与该状态在 2026-10-23 的构建产物逐字节相同。
- `k90-port` 的最新提交另含 BootShim 严格载荷检查、`XNU_Payload` 保留区和 XnuLoader 更新，内容与内核仓库的 `uefi/mu-silicium.patch`、`uefi/annibale/`、`uefi/files/` 一致，还没有装进真机用的 loader 镜像。各项的取舍见第 4 节。
- 高通 DXE 驱动来自子模块 `Binaries`（Project-Silicium/Device-Binaries）。annibalePkg 引用 `Binaries/annibale/...`，上游没有这个目录，需要建一个指向 `dodge` 的符号链接。
- 设备树 `annibalePkg/FdtBlob/sm8750-xiaomi-annibale.dtb`（956,243 字节）由手机 `vendor_boot` 里的 base DT 与本机 `dtbo` overlay 经 `fdtoverlay` 合并而成。只放 dtbo overlay 时 IortDtDxe 挂起。`Resources/DTBs/annibale.dtb` 是同一文件。
- 面板描述 `annibalePkg/RawFiles/Panel_xiaomi_p11_42_0d_0a_dsc_cmd.xml` 由顶层 `tools/dts2panelxml.py` 从设备树的面板节点生成：1156×2510，DSC 1.2 slice 578×10，cmd 模式，4 lane，339 条 DCS 初始化命令。

## 2. 构建 FD

在 hackios-dev 容器里构建（`docker/build.sh` 生成镜像，`docker/dev.sh` 进入容器，工作区挂在 `/work`，见 [docker/README.md](../../docker/README.md)）。容器里有 stuart（edk2-pytool）、clang、lld 和 nasm。

```sh
# 主机上，工作区根目录
git clone -b loader-v16 --recurse-submodules https://github.com/iola1999/hackios-mu-silicium.git hackios-xnu-kernel/Mu-Silicium

# 容器内
cd /work/hackios-xnu-kernel/Mu-Silicium
ln -s dodge Binaries/annibale
bash /work/tools/fixup-mu-nasm.sh      # 用容器的 nasm 代替 NuGet 依赖，可重复执行
python3 build_uefi.py -d annibale
```

- 产物是 `Build/annibalePkg/RELEASE_CLANGPDB/FV/SILICIUM_UEFI.fd`（3 MiB）。2026-11-05 在 `loader-v16` 的干净副本上按上面的步骤构建成功；产物与真机用的 FD 不逐字节相同（EDK2 产物带构建时的信息，FV 又经过压缩），新产物没有上过真机。
- 工具链是 CLANGPDB，Mu 的 tools_def 没有 GCC5 定义。
- FD 加载地址 `0xA7100000`、大小 `0x300000`，写在 `Resources/Configs/annibale.toml`，与 `hackios-xnu-kernel/common/devices/annibale.conf` 一致。
- 克隆 `-b k90-port` 得到最新提交，其中的改动还没有上过真机。

## 3. 装配 loader 镜像

在 `hackios-xnu-kernel/` 目录执行：

```sh
EXTRA_CFLAGS=-DDIRECT_PHONE_PLAT BUILD_ID=a48c7fbac8fb64e1e8cafe2cf4efc4c79dbae767 xnuloader/build.sh
python3 xnuloader/mkpayload.py -o out/loader-payload-v16.bin loader.efi=xnuloader/loader-phone.efi --identity v57 --usb
PATH="$(brew --prefix llvm)/bin:$PATH" UEFI_TARGET=annibale FD_BASE=0xA7100000 FD_SIZE=0x300000 PAYLOAD_BASE=0xF0000000 \
  python3 mkxnuimg.py -p out/loader-payload-v16.bin -o out/handoff-loader-v16.img
```

- 第一步生成 `xnuloader/loader-phone.efi`。`BUILD_ID` 必须是 40 位小写十六进制的源码提交，装好后由 `fastboot getvar build-id` 读出。`a48c7fb` 是 v16 的源码提交，此后 `xnuloader/` 没有改动；`tools/k90auto/cycle.py` 按 build-id 是否含 `a48c7fb` 判断驻留的 loader 是不是 v16（`LOADER_BUILD`）。2026-11-05 这样重建的 `loader.efi` 与 v16 里的那份只差 PE 头里 3 字节的链接时间戳。`xnuloader/` 改动后，`BUILD_ID` 改填当时的提交，并同步 `cycle.py` 的 `LOADER` 与 `LOADER_BUILD`。
- `mkxnuimg.py` 发现 `Mu-Silicium/BootShim` 时按给定地址重编 BootShim，需要 clang 和 `llvm-objcopy`（macOS 上由 Homebrew 的 llvm 提供）；DTB 取 `Mu-Silicium/Resources/DTBs/annibale.dtb`。
- 不设 `PAYLOAD_CAP` 时编出 176 字节的 shim，与 v6～v16 相同。2026-11-05 用 v16 的载荷和本地 `loader-v16` 状态的 FD 按上面的命令重建，kernel 段（BootShim、FD、XNUP 容器）和 DTB 与 v16 逐字节相同，只有 gzip 压缩流和头部 id 不同。
- `common/build.sh annibale` 会从 `annibale.conf` 带上 `PAYLOAD_CAP=0x03700000`，编出 368 字节的严格版 shim。这种镜像没有在真机上用过。
- 已经有一份 loader 镜像、只换 loader 时，用 `python3 tools/reseal-loader-img.py 参考镜像 新载荷 -o 新镜像`，它原样保留参考镜像的 shim、FD、DTB 和 ramdisk。

装进手机的方法见[真机调试手册](../plan/device-test-playbook.md)。

## 4. `k90-port` 上未进真机的改动

`loader-v16` 之后的那笔提交有三处改动，都还没有上过真机：

| 改动 | 作用 | 取舍 |
|---|---|---|
| XnuLoader 失败路径 | `loader-v16` 在载荷里没有 `loader.efi`、loader 启动失败或返回时，把日志写进 `boot_a` 的第 0 块再冷重启。`boot_a` 正是 loader 镜像所在的分区，这次写入会覆盖镜像头。新版去掉这次写入，并检查每个载荷条目的长度不越过容器末尾 | 新版在失败后关中断原地停机，需要长按电源键恢复，与 AGENTS.md §5 减少人工按键的要求冲突。上机前要定：失败后停机，还是不写存储直接冷重启 |
| `XNU_Payload` 保留区 | 内存映射里保留 `[0xF0000000, 0xF3800000)`，PEI 阶段就把 BootShim 复制载荷的窗口排除出 DXE 可分配范围 | 防止 DXE 把载荷所在的内存分配出去。现有 loader 的载荷只有约 100 KB，没有观察到这类问题 |
| BootShim 严格检查 | 定义 `PAYLOAD_CAP` 时检查 XNUP 容器长度与复制窗口 | 只在 `common/build.sh annibale` 的构建里生效；第 3 节的命令不设 `PAYLOAD_CAP`，生成的 shim 与旧版相同 |

xnuloader 正常运行时不会回到 UEFI：`efi_main` 以 `reboot()` 结束，复位失败时原地循环。所以第一项的失败路径只在载荷损坏或 loader 无法启动时才会走到。验证新 FD 时先从 LK 用 `fastboot boot` 临时启动，不写 `boot_a`。

## 5. 已知事实

- 原厂 `uefi_a` 分区是 AArch64 ELF（入口 `0xa7000000`，单个 RWX LOAD 段 `0x2b3000`），里面的 FV 压缩存放、运行时解出。
- LK 的 `fastboot boot` 偶尔返回 `Load Error`，与镜像无关，重新进入 LK 的 fastboot 后即可。`fastboot reboot fastboot` 进入的是 Android 用户态的 fastbootd，它拒绝未签名的 boot 镜像；回 LK 用 `fastboot reboot bootloader` 或 `adb reboot bootloader`。
- 同平台的 REDMI K90 Pro Max（myron）有 gbl-chainload-myron，可以从 Android 引导链把自建 UEFI 载入内存。本项目没有采用这条路。
