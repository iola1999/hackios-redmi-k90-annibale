# xnu-8796 内核的 Linux 容器构建

本文记录 xnu-8796（iOS 16.5 内核线）在 Linux 容器 `kbuild` 里的构建方法。这条线的构建依赖 Linux 主机工具和 theos，所以放在容器里；容器常驻复用，`docker start kbuild` 即可。

iOS 26 用的 12377 内核在 Mac 上用 `hackios-xnu-kernel/xnu26/build-macos.sh` 构建，不走这个容器，见 [arm64e 构建路径](2026-10-28-arm64e-userland-build-path.md) §0 与 [k90auto 说明](../../tools/k90auto/README.md) §3。

## 1. 容器与依赖

```sh
docker volume create kb
docker run -d --name kbuild --platform linux/amd64 \
  -v kb:/work -v $PWD/hackios-xnu-kernel:/src:ro ubuntu:22.04 sleep infinity
```

- **必须 `--platform linux/amd64`**：theos 的 Linux cctools/ld64 只有 x86_64；OrbStack 的 Rosetta 透明加速，性能可接受（全量 -j8 约 35 分钟）。`docker/Dockerfile` 的 arm64 镜像（Mesa 与 userland 交叉构建）用同一份 theos 工具链，因此加装了 amd64 运行库。
- apt（tuna 源）：`git curl ca-certificates tar xz-utils make clang lld python3 perl flex bison m4 autoconf automake libtool pkg-config zlib1g-dev gawk file unzip zstd libzstd-dev bzip2 zip binutils uuid-dev libssl-dev libxml2-dev libbz2-dev liblzma-dev libncurses-dev python-is-python3`

## 2. theos（XNU 的 SDK 与链接器）

```sh
git clone --depth 1 https://github.com/theos/theos.git /root/theos
curl -sL https://github.com/L1ghtmann/llvm-project/releases/latest/download/iOSToolchain-x86_64.tar.xz \
  | tar -xJ -C /root/theos/toolchain/        # 提供 toolchain/linux/iphone（ld64 等）
/root/theos/bin/install-sdk iPhoneOS16.5     # 提供 sdks/iPhoneOS16.5.sdk
```

## 3. 构建步骤（容器内，仓库克隆在 /work/repo）

```sh
git clone -b k90-port file:///src /work/repo
bash xnu/apply.sh            # 拉 apple-oss-distributions/xnu 的 xnu-8796.121.2 并打 redwood 补丁
bash xnu-deps/setup.sh       # stage1 host 工具(mig/tcsh/unifdef) + SDK 缝合；stage2 两个静态库
bash xnu-build.sh -j8 BUILD_DSYM=0 KEXT_CREATE_SYMBOL_SET=/bin/true
```

产物：`xnu-src/xnu-8796.121.2/BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837`。

## 4. 已知构建问题与处理

前两项的修复已提交进仓库，其余靠 apt 包或构建参数处理。

| 症状 | 根因 | 修复 |
|---|---|---|
| `strlcat` 未定义（SETUP/replacecontents） | glibc<2.38 无 BSD 字符串函数 | hostcompat.h 加 static inline（仓库 63f0f01） |
| `-ftrivial-auto-var-init=zero` 报错 | xnu-clang 包装器一律丢弃 enable flag，而 Ubuntu clang≤19 需要它 | 包装器加一次性能力探测缓存（kernel 仓库 b7ac03a） |
| `uuid/uuid.h` 找不到 | 缺 uuid-dev | apt 装上 |
| tcsh 配置失败 | 缺 libncurses-dev | apt 装上 |
| `--minimize: command not found`（DSYMUTIL） | Linux 无 dsymutil | `BUILD_DSYM=0`（dSYM 我们不用） |
| `check_all_exports`: exported name not in import list | 新 clang 生成的 C++ 符号与 Apple 参考清单不一致（Apple 用 LTO 收敛） | `KEXT_CREATE_SYMBOL_SET=/bin/true` 旁路；注意值必须是存在的文件（make 会把它当依赖），不能用裸 `true` |
| lldbmacros `env: python` | ubuntu 无 `python` 别名 | `python-is-python3` |

改了 `hostcompat.h` 后旧 `.o` 不会自动重编（没有头文件依赖），要 `rm -rf BUILD/obj/SETUP`。

## 5. 换入 payload 的流程

`tools/k90auto/build-kernel.py NAME` 自动完成这一步：在容器里构建内核子模块的 HEAD 提交（未提交的修改不进入内核），产物复制为 `hackios-xnu-kernel/out/handoff-mach-NAME`，再做两项构建后检查：每个改动的源文件都有比它新的目标文件，`EXPECT_STRINGS` 列出的字符串出现在内核里。脚本拒绝 `12377` 开头的名字。

手工换入 `prebuilt/` 的做法（`prebuilt/mach.development.bcm2837` 原是上游交付物）：

```sh
docker cp kbuild:/work/repo/xnu-src/xnu-8796.121.2/BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837 \
  hackios-xnu-kernel/prebuilt/mach.development.bcm2837
# 更新 prebuilt/SHA256SUMS 对应行 → 重跑 mkpayload/mkxnuimg → QEMU 回归（qemu/run-ios.sh）
```

已知差异：本项目构建 `BUILD_LTO=0`（构建脚本默认），上游交付物带 LTO，体积 15.2MB 对 15.6MB；功能是否等价以 QEMU 回归为准。

## 6. userland overlay 与版本核对

以下命令在主机的仓库检出中执行。内核的 `common/setup.sh` 把 userland 检出到同一构建树，以 `.userland.git` 管理；它与顶层并列的 userland 子模块是两份检出，需要分别核对版本。首次建立构建树使用以下命令，之后比较 overlay 与顶层固定的 userland commit；分支已经前进时，在干净工作树中对齐到选定版本。

```sh
cd hackios-xnu-kernel
USERLAND_URL=https://github.com/iola1999/hackios-xnu-userland.git USERLAND_REF=k90-port common/setup.sh
common/ugit rev-parse HEAD
git -C ../hackios-xnu-userland rev-parse HEAD
```

已有构建树先检查状态。`common/setup.sh` 会尝试更新既有 overlay，保留其他任务的未提交修改；宿主缺失依赖按脚本输出补齐。
