# 26 线 arm64e 用户态产物的宿主构建路径（2026-10-28）

iOS 26 系统盘只带 arm64e 的 dyld 共享缓存，镜像里经 dyld 加载的程序和库都必须是 Apple clang 编出的 arm64e。本文记录这些产物由哪个脚本在宿主上编、怎样核对身份，以及构建上的约束。

26 线内核不在本文范围：它由 `xnu26/build-macos.sh` 在 Mac 上构建，容器里的 `tools/k90auto/build-kernel.py` 只编 xnu-8796（iOS 16.5 线）。步骤见 [k90auto 说明](../../tools/k90auto/README.md) §3，内核源码身份的口径见[排查与协作手册](../plan/debugging-and-collaboration.md) §3。

## 1. 驱动、shim 与注入库：`tools/k90auto/package.py`

- 工具链：`SDK = ["/usr/bin/xcrun", "-sdk", "iphoneos", "clang", "-arch", "arm64e", "-miphoneos-version-min=26.0"]`。`-sdk iphoneos` 解析到宿主默认的 iPhoneOS SDK，2026-10-28 时是 27.1，与 `hackios-xnu-kernel/xnu-deps/26/sdk/iPhoneOS.sdk/System` 那个符号链接指向同一个。
- `build(sources, install_name, flags, out, dynamic=True)`：命令行是 `SDK + flags + ["-fno-objc-arc", *kind, *sources, "-lobjc", "-o", out]`，`dynamic` 为真时 `kind` 是 `["-dynamiclib", "-install_name", install_name]`。它先把命令行写进 `<out>.build.log`，以 `cwd=SRC_ROOT`（`PAYLOAD_SRC_ROOT`，默认 `hackios-xnu-kernel`）编译，再用 `codesign --force --sign -` 做 adhoc 签名。
- 编出的产物：shim（`userland/src/sb_metal_experiment.m`）、驱动（`tools/userland-driver/annibalemetal.m` 与 `annibaledrawable.m`）、`libannibale-sb26.dylib`（`SB26_SOURCES`），以及按开关编的 `lsprobe`（`PROBE=1`）、`libannibale-xpcwatch.dylib`（`XPCWATCH`）、`libannibale-ax.dylib`（`AX`）。
- 打包：基线是 `userland/build.sh` 的暂存目录 `userland/root/`（`BASE`），先在 `hackios-xnu-kernel/userland/` 执行 `IOS=../ios26 COMPILE_ONLY=1 bash build.sh`。`package.py` 把基线打成 `base.apfs` 作比较对象，再拷贝基线、覆盖新产物，用 `tools/apfs/mkapfs.py -z --plain fw` 打 `root.apfs`，两份镜像之间变化的路径必须都在它要改的范围内。产物、根盘与 `manifest.json` 都在 `out/ios26-resume/bbmetal-device/`，manifest 的 `build_commands` 与 `source_sha256` 记下每条命令行和源摘要。
- `build.sh` 在 macOS 上、`IOS=../ios26` 时用 Xcode 的 clang 编动态程序和库（`DYN`，arm64e，`-miphoneos-version-min=26.0`），静态程序（`init`、`child`、`stage0`、`var_store`）仍用 `xnu-clang`，它在 macOS 上用 Xcode 的 `ld` 链接。
- `libannibale.dylib`（`userland/src/inject.c`）由 `userland/build.sh` 编，`package.py` 从 `userland/root/lib/` 取，打包前要先跑 `build.sh`。拷进镜像后检查它与 `build.sh` 的产物逐字节相同、cpusubtype 为 `0x80000002`（§4）。

### 1.1 重建这份驱动库的步骤与可复现条件

源码在 `hackios-xnu-kernel/tools/userland-driver/`：两个 `.m`，以及它们 include 的头文件与 `.inc`（`air_metal_copy.h` 也在这份源码集里；`annibalemetal_mesa.inc` 的 include 写的是同目录）。`tools/k90auto/package.py` 的 `DRIVER_SOURCES` 与 `DRIVER_INCLUDES` 指向该目录。

```
cd hackios-xnu-kernel
/usr/bin/xcrun -sdk iphoneos clang -arch arm64e -miphoneos-version-min=26.0 -O1 \
  -framework Foundation -framework IOKit -framework Metal -fno-objc-arc \
  -dynamiclib -install_name /annibale/lib/libannibalemetal.dylib \
  tools/userland-driver/annibalemetal.m tools/userland-driver/annibaledrawable.m \
  -lobjc -o <目录>/libannibalemetal.dylib
codesign --force --sign - <目录>/libannibalemetal.dylib
```

**输出文件名必须是 `libannibalemetal.dylib`。** adhoc 签名把标识符写成 `<文件名>-<UUID>`，输出叫别的名字时签名 blob 随之改写，整份 sha256 完全不同，而 `__TEXT,__text` 与 `LC_UUID` 都一样。同一台机器、同一套 clang（21.0.0、SDK 27.1）重编，结果逐字节相同。

2026-10-29 那份源码的核对值：241,488 字节、sha256 `9d66dd367d09af4d9b526c73c8407627357d1e32d0cd392639bd5e2b35600f26`。源文件路径不写进产物，所以从 `userland/src/` 或 `tools/userland-driver/` 编出的结果相同；能改哈希的只有输出文件名。

## 2. AIR 库：`tools/k90auto/build-air.py`

- AIR 库只由这个脚本编，`package.py` 不编。arm64e 构建只读自己那份源（`out/ios26-resume/mesa-arm64e/mesa-26.2.5/src/compiler/air/`），`tools/mesa/air/` 的改动不复制过去就不会进库，构建照样成功、库照样有效。
- 流程：把 `FILES` 列出的文件复制进 arm64e 树并断言复制生效；`tools/mesa/air/` 里有与构建树不一致、又不在 `FILES` 里的文件时报错，新文件要同时加进 `FILES`。然后 `ninja -C BUILD -j8 TARGET`，把 ninja 的输出 `LIB` 拷成 `OUT`（`out/ios26-resume/bbmetal-device/libannibaleair.dylib`）并 adhoc 签名，最后写 `air-build-record.json`：两侧源摘要、库的字节数与 sha256、`holds` 里各个格式串是否在库里。
- `--check` 只读：只算摘要并打印，不复制、不构建、不写文件。
- 工具链：venv 里的 meson 1.12.1 加 homebrew 的 ninja，bison 排在系统那个前面（前端的 parser 要它），可用 `AIR_VENV`／`AIR_BISON`／`AIR_NINJA` 覆盖。默认 venv 在 `/tmp/mesa-rebase/venv/bin`，重启或清理 `/tmp` 后就没有了，建法见第 6 节。
- 交叉构建配置 `out/ios26-resume/mesa-arm64e/cross.ini`：c／cpp／objc 都是 Xcode toolchain 的 clang 加 `-arch arm64e -isysroot <Xcode>/Platforms/iPhoneOS.platform/Developer/SDKs/iPhoneOS27.1.sdk -miphoneos-version-min=26.0`；ar／ranlib／strip 取自同一个 toolchain，`pkg-config = /usr/bin/false`；`[host_machine]` 是 `system = darwin`、`subsystem = ios`、`cpu_family = aarch64`、`cpu = arm64e`，`needs_exe_wrapper = true`。
- 构建选项在同目录 `cmd_line.txt`：`buildtype = release`、`prefix = /annibale`、`gallium-drivers = softpipe,freedreno`、`freedreno-kmds = msm`、`osmesa = true`、`llvm = disabled`、`gles2 = enabled`、`shader-cache = disabled`、`build-tests = false`。

## 3. 同名的 `libannibaleair.dylib`

- `out/ios26-resume/mesa-arm64e/` 下有不止一个 `libannibaleair.dylib`，字节数与哈希各不相同，核对身份时必须按完整路径。
- ninja 的输出 `mesa-arm64e/build/src/gallium/drivers/freedreno/libannibaleair.dylib` 没有签名，dyld 拒绝加载。`OUT` 是它加 adhoc 签名后的副本，多出的字节是签名。
- `package.py` 检查要打包的 AIR 库是 adhoc 签名，并与 `air-build-record.json` 记的 `library_sha256` 一致，不一致时要求先跑 `build-air.py`。

## 4. 各脚本的分工与架构判据

- `userland/build.sh`（`IOS=../ios26`）：系统盘 `system26.apfs`，以及写进 `userland/obj/` 与 `userland/root/` 的程序和库。V=26 时 `input26-service`、`libannibale-sb26.dylib`、`libannibale-sbmetal-experiment.dylib` 在 Darwin 上用 `xcrun -sdk iphoneos clang -arch arm64e -miphoneos-version-min=26.0` 编并 adhoc 签名，在容器里用 `xnu-clang` 加 `../xnu-deps/26/sdk/iPhoneOS.sdk` 编、`ldid -S` 签名。
- `tools/k90auto/package.py`：§1 那些库，写 `out/ios26-resume/bbmetal-device/`。
- `tools/k90auto/build-air.py`：AIR 库，见 §2。
- 容器里的 clang 18 没有 ptrauth（`__has_feature(ptrauth)` 为 0），编出的 arm64e 缺 LIB64 位，26 线的产物要在有 Apple clang 的宿主上编，见[容器构建修复](../progress/2026-10-28-userland-container-build-fix.md)。

26 线的进程都是 arm64e。arm64 分片的库在 arm64e 进程里不会被装载，dyld 也不留一行说明：库的构造器从不执行，日志里既没有它的横幅也没有架构报错，读起来与「库没被注入」一样。判据用头部，不用文件名：

- `otool -hv <库>` 的 `cpusubtype` 必须是 `0x80000002`（ARM64E 加 LIB64 位），与镜像里其它 arm64e 库一致。
- `userland/build.sh` 在 V=26 的 staging 之后、第一个 `mkapfs` 之前拒绝非 arm64e 加 LIB64 位的 Mach-O；`package.py` 对 `libannibale.dylib` 做同样的检查，因为那条路径不经 `build.sh` 的闸。
- 签名同样在判据之内。签名会改变文件字节与哈希，所以比哈希要在签名之后做。
- `build.sh` 里 `libannibale.dylib` 的编译行用的是 `$DYN`（`-arch arm64`、iOS 16.5 SDK），编出的是 arm64；`package.py` 的检查会拒绝这份，打包要用 arm64e、iOS 26 SDK 重编并签名的那份。

## 5. 可复现性与新鲜度

- 容器内的 Mesa 构建无法逐字节复现，`tools/mk-mesa.sh` 的注释记了实测：同一份源树两次构建，`libOSMesa.8.dylib` 与 `air_run` 字节数相同、内容有大段不同。宿主这条 arm64e meson 构建在固定 `PYTHONHASHSEED=0` 时逐字节可复现，见第 6 节。
- 所以产物哈希相同可以推出源相同，产物哈希不同推不出源不同。重编 AIR 后哈希与记录值不同时，先核 `air-build-record.json` 的 `source_sha256` 与 `tree_sha256`：两侧一致就说明库是按当前源编的。
- 判断产物是否按当前源码编出，用内容哈希，不用 mtime。`package.py` 的 manifest 与 `build-air.py` 的 record 都记了源摘要和产物哈希。
- `build-air.py` 不带 `--check` 时就地覆盖 `OUT`，路径是硬编码的，没有环境变量能改。需要保留上一份库作对照时，先把 `out/ios26-resume/bbmetal-device/` 备份到 Git 忽略的目录。
- 打包或跑轮期间不要运行会写 `out/ios26-resume/` 或 `userland/obj/` 的命令，`build.sh` 也在其中（它写 `userland/obj/`，并 `rm -rf root`）。只读复核不受此限：`build-air.py --check`、`ninja -n` 干跑、`shasum`、`codesign -dv`、`otool`。

## 6. 构建树从仓库重建

arm64e 构建树 `out/ios26-resume/mesa-arm64e/mesa-26.2.5` 的源码等于 Mesa 26.2.5 的源码包，打上用户态仓库的 `tools/mesa/*.patch` 与 `tools/mesa/rebase-26/*.patch`，再放入 `tools/mesa/annibale-drm` 和 `tools/mesa/air`。真机库里的 shadow 修复、诊断探针与 perf 探针是 `rebase-26/0011`～`0014`，说明见用户态仓库的 `tools/mesa/rebase-26/README.md`。

从零建树：

```sh
# 宿主上一次性准备：meson 与 Mesa 生成代码用的 Python 包，Homebrew 的 ninja 与 bison
python3 -m venv /tmp/mesa-rebase/venv           # 放别处时用 AIR_VENV 指向它的 bin/
/tmp/mesa-rebase/venv/bin/pip install meson==1.12.1 mako==1.4.3 PyYAML==6.0.3 packaging==26.0
brew install ninja bison
# hackios-dev 容器里，hackios-xnu-kernel/ 目录（补丁步骤要 GNU patch）
PREPARE=1 VERSION=26.2.5 SHA256=794b3d1729075dae7ebd47c7283b7ca0cdb5dec668f7f11cc0a5d82f6138a0a5 REBASE=26 tools/mk-mesa.sh
# 宿主上，工作区根目录（Xcode 的 arm64e clang 与 iPhoneOS SDK）
python3 tools/k90auto/setup-mesa-arm64e.py      # 目标目录已存在时拒绝执行
python3 tools/k90auto/build-air.py
```

- 2026-11-05 实测：用上面版本新建的 venv，按上面步骤在另一个目录建的树，源码与真机构建树 `diff -r` 无差异（只差 Python 缓存），编出的 `libannibaleair.dylib` 与真机构建树编出的逐字节相同（未签名 `6c65dc5a…`，签名后 `70f072b2…`）。
- Mesa 的 isaspec 生成器按 Python 集合的顺序写 `build/src/freedreno/isa/encode.h`，这个顺序随每个进程的哈希种子变化，同一份源码两次构建会得到语句顺序不同的 `encode.h` 和不同字节的库。`build-air.py` 与 `setup-mesa-arm64e.py` 因此固定 `PYTHONHASHSEED=0`。
- 改构建树里的 Mesa 源码时同时改 `rebase-26` 的补丁，改完在容器里用 `PREPARE=1` 重打一遍，与构建树 `diff -r` 应无差异，再跑 `build-air.py`。补丁与构建树不一致时构建照样成功，唯一的迹象是一轮跑完日志里少几行。
- `air-build-record.json` 只覆盖 `build-air.py` 的 `FILES`（`tools/mesa/air/` 里的文件）。判断库里有没有某段插桩，用 `strings <库> | grep -c '<格式串>'`。
