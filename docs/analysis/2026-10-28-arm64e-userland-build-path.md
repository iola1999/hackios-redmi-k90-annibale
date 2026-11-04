# 26 线 arm64e 用户态产物的宿主构建路径（2026-10-28）

iOS 26 系统盘只带 arm64e 的 dyld 共享缓存，镜像里经 dyld 加载的程序和库都必须是 Apple clang 编出的 arm64e。本文记录这些产物由哪个脚本在宿主上编、怎样核对身份，以及构建上的约束。

26 线内核不在本文范围：它由 `xnu26/build-macos.sh` 在 Mac 上构建，容器里的 `tools/k90auto/build-kernel.py` 只编 xnu-8796（iOS 16.5 线）。步骤见 [k90auto 说明](../../tools/k90auto/README.md) §3，内核源码身份的口径见[排查与协作手册](../plan/debugging-and-collaboration.md) §3。

## 1. 驱动、shim 与注入库：`tools/k90auto/package.py`

- 工具链：`SDK = ["/usr/bin/xcrun", "-sdk", "iphoneos", "clang", "-arch", "arm64e", "-miphoneos-version-min=26.0"]`。`-sdk iphoneos` 解析到宿主默认的 iPhoneOS SDK，2026-10-28 时是 27.1，与 `hackios-xnu-kernel/xnu-deps/26/sdk/iPhoneOS.sdk/System` 那个符号链接指向同一个。
- `build(sources, install_name, flags, out, dynamic=True)`：命令行是 `SDK + flags + ["-fno-objc-arc", *kind, *sources, "-lobjc", "-o", out]`，`dynamic` 为真时 `kind` 是 `["-dynamiclib", "-install_name", install_name]`。它先把命令行写进 `<out>.build.log`，以 `cwd=SRC_ROOT`（`PAYLOAD_SRC_ROOT`，默认 `hackios-xnu-kernel`）编译，再用 `codesign --force --sign -` 做 adhoc 签名。
- 编出的产物：shim（`userland/src/sb_metal_experiment.m`）、驱动（`tools/userland-driver/redwoodmetal.m` 与 `redwooddrawable.m`）、`libredwood-sb26.dylib`（`SB26_SOURCES`），以及按开关编的 `lsprobe`（`PROBE=1`）、`libredwood-xpcwatch.dylib`（`XPCWATCH`）、`libredwood-ax.dylib`（`AX`）。
- 打包：先断言 `BASE`（`out/ios26-resume/air-arm64e-device/on`）的 `root.apfs` 与三个库的哈希，再拷贝它的 `root/`、覆盖新产物，用 `tools/apfs/mkapfs.py -z --plain fw` 打 `root.apfs`。产物、根盘与 `manifest.json` 都在 `out/ios26-resume/bbmetal-device/`，manifest 的 `build_commands` 与 `source_sha256` 记下每条命令行和源摘要。
- `libredwood.dylib`（`userland/src/inject.c`）由 `userland/build.sh` 编，`package.py` 从 `userland/root/lib/` 取，打包前要先跑 `build.sh`。拷进镜像后检查它与 `build.sh` 的产物逐字节相同、cpusubtype 为 `0x80000002`（§4）。

### 1.1 重建这份驱动库的步骤与可复现条件

源码在 `hackios-xnu-kernel/tools/userland-driver/`：两个 `.m`，以及它们 include 的头文件与 `.inc`（`air_metal_copy.h` 也在这份源码集里；`redwoodmetal_mesa.inc` 的 include 写的是同目录）。`tools/k90auto/package.py` 的 `DRIVER_SOURCES` 与 `DRIVER_INCLUDES` 指向该目录。

```
cd hackios-xnu-kernel
/usr/bin/xcrun -sdk iphoneos clang -arch arm64e -miphoneos-version-min=26.0 -O1 \
  -framework Foundation -framework IOKit -framework Metal -fno-objc-arc \
  -dynamiclib -install_name /redwood/lib/libredwoodmetal.dylib \
  tools/userland-driver/redwoodmetal.m tools/userland-driver/redwooddrawable.m \
  -lobjc -o <目录>/libredwoodmetal.dylib
codesign --force --sign - <目录>/libredwoodmetal.dylib
```

**输出文件名必须是 `libredwoodmetal.dylib`。** adhoc 签名把标识符写成 `<文件名>-<UUID>`，输出叫别的名字时签名 blob 随之改写，整份 sha256 完全不同，而 `__TEXT,__text` 与 `LC_UUID` 都一样。同一台机器、同一套 clang（21.0.0、SDK 27.1）重编，结果逐字节相同。

2026-10-29 那份源码的核对值：241,488 字节、sha256 `9d66dd367d09af4d9b526c73c8407627357d1e32d0cd392639bd5e2b35600f26`。源文件路径不写进产物，所以从 `userland/src/` 或 `tools/userland-driver/` 编出的结果相同；能改哈希的只有输出文件名。

## 2. AIR 库：`tools/k90auto/build-air.py`

- AIR 库只由这个脚本编，`package.py` 不编。arm64e 构建只读自己那份源（`out/ios26-resume/mesa-arm64e/mesa-26.2.5/src/compiler/air/`），`tools/mesa/air/` 的改动不复制过去就不会进库，构建照样成功、库照样有效。
- 流程：把 `FILES` 列出的文件复制进 arm64e 树并断言复制生效；`tools/mesa/air/` 里有与构建树不一致、又不在 `FILES` 里的文件时报错，新文件要同时加进 `FILES`。然后 `ninja -C BUILD -j8 TARGET`，把 ninja 的输出 `LIB` 拷成 `OUT`（`out/ios26-resume/bbmetal-device/libredwoodair.dylib`）并 adhoc 签名，最后写 `air-build-record.json`：两侧源摘要、库的字节数与 sha256、`holds` 里各个格式串是否在库里。
- `--check` 只读：只算摘要并打印，不复制、不构建、不写文件。
- 工具链：venv 里的 meson 1.12.1 加 homebrew 的 ninja，bison 排在系统那个前面（前端的 parser 要它），可用 `AIR_VENV`／`AIR_BISON`／`AIR_NINJA` 覆盖。默认 venv 在 `/tmp/mesa-rebase/venv/bin`，重启或清理 `/tmp` 后就没有了。
- 交叉构建配置 `out/ios26-resume/mesa-arm64e/cross.ini`：c／cpp／objc 都是 Xcode toolchain 的 clang 加 `-arch arm64e -isysroot <Xcode>/Platforms/iPhoneOS.platform/Developer/SDKs/iPhoneOS27.1.sdk -miphoneos-version-min=26.0`；ar／ranlib／strip 取自同一个 toolchain，`pkg-config = /usr/bin/false`；`[host_machine]` 是 `system = darwin`、`subsystem = ios`、`cpu_family = aarch64`、`cpu = arm64e`，`needs_exe_wrapper = true`。
- 构建选项在同目录 `cmd_line.txt`：`buildtype = release`、`prefix = /redwood`、`gallium-drivers = softpipe,freedreno`、`freedreno-kmds = msm`、`osmesa = true`、`llvm = disabled`、`gles2 = enabled`、`shader-cache = disabled`、`build-tests = false`。

## 3. 同名的 `libredwoodair.dylib`

- `out/ios26-resume/mesa-arm64e/` 下有不止一个 `libredwoodair.dylib`，字节数与哈希各不相同，核对身份时必须按完整路径。
- ninja 的输出 `mesa-arm64e/build/src/gallium/drivers/freedreno/libredwoodair.dylib` 没有签名，dyld 拒绝加载。`OUT` 是它加 adhoc 签名后的副本，多出的字节是签名。
- `package.py` 检查要打包的 AIR 库是 adhoc 签名，并与 `air-build-record.json` 记的 `library_sha256` 一致，不一致时要求先跑 `build-air.py`。

## 4. 各脚本的分工与架构判据

- `userland/build.sh`（`IOS=../ios26`）：系统盘 `system26.apfs`，以及写进 `userland/obj/` 与 `userland/root/` 的程序和库。V=26 时 `input26-service`、`libredwood-sb26.dylib`、`libredwood-sbmetal-experiment.dylib` 在 Darwin 上用 `xcrun -sdk iphoneos clang -arch arm64e -miphoneos-version-min=26.0` 编并 adhoc 签名，在容器里用 `xnu-clang` 加 `../xnu-deps/26/sdk/iPhoneOS.sdk` 编、`ldid -S` 签名。
- `tools/k90auto/package.py`：§1 那些库，写 `out/ios26-resume/bbmetal-device/`。
- `tools/k90auto/build-air.py`：AIR 库，见 §2。
- 容器里的 clang 18 没有 ptrauth（`__has_feature(ptrauth)` 为 0），编出的 arm64e 缺 LIB64 位，26 线的产物要在有 Apple clang 的宿主上编，见[容器构建修复](../progress/2026-10-28-userland-container-build-fix.md)。

26 线的进程都是 arm64e。arm64 分片的库在 arm64e 进程里不会被装载，dyld 也不留一行说明：库的构造器从不执行，日志里既没有它的横幅也没有架构报错，读起来与「库没被注入」一样。判据用头部，不用文件名：

- `otool -hv <库>` 的 `cpusubtype` 必须是 `0x80000002`（ARM64E 加 LIB64 位），与镜像里其它 arm64e 库一致。
- `userland/build.sh` 在 V=26 的 staging 之后、第一个 `mkapfs` 之前拒绝不是 arm64e 加 LIB64 位的 Mach-O；`package.py` 对 `libredwood.dylib` 做同样的检查，因为那条路径不经 `build.sh` 的闸。
- 签名同样在判据之内。签名会改变文件字节与哈希，所以比哈希要在签名之后做。
- `build.sh` 里 `libredwood.dylib` 的编译行用的是 `$DYN`（`-arch arm64`、iOS 16.5 SDK），编出的是 arm64；`package.py` 的检查会拒绝这份，打包要用 arm64e、iOS 26 SDK 重编并签名的那份。

## 5. 可复现性与新鲜度

- 容器那条 Mesa 构建不是逐字节可复现的，`tools/mk-mesa.sh` 的注释记了实测：同一份源树两次构建，`libOSMesa.8.dylib` 与 `air_run` 字节数相同、内容有大段不同。宿主这条 arm64e meson 构建是否逐字节可复现，没有实测。
- 所以产物哈希相同可以推出源相同，产物哈希不同推不出源不同。重编 AIR 后哈希与记录值不同时，先核 `air-build-record.json` 的 `source_sha256` 与 `tree_sha256`：两侧一致就说明库是按当前源编的。
- 判断产物是不是按当前源编出，用内容哈希，不用 mtime。`package.py` 的 manifest 与 `build-air.py` 的 record 都记了源摘要和产物哈希。
- `build-air.py` 不带 `--check` 时就地覆盖 `OUT`，路径是硬编码的，没有环境变量能改。需要保留上一份库作对照时，先把 `out/ios26-resume/bbmetal-device/` 备份到 Git 忽略的目录。
- 打包或跑轮期间不要运行会写 `out/ios26-resume/` 或 `userland/obj/` 的命令，`build.sh` 也在其中（它写 `userland/obj/`，并 `rm -rf root`）。只读复核不受此限：`build-air.py --check`、`ninja -n` 干跑、`shasum`、`codesign -dv`、`otool`。

## 6. `tools/mesa-patches/*.patch`：补丁可复现，构建树不可重建

- `hackios-xnu-kernel/tools/mesa-patches/` 下有三个补丁（`fixguard6-shadow-counters.patch`、`freedreno-shared-no-shadow.patch`、`transfer-stride-layout.patch`），仓库里没有脚本应用它们。`tools/mk-mesa.sh` 只打 `tools/mesa/*.patch`（`REBASE=26` 时加上 `tools/mesa/rebase-26/*.patch`），并把这些补丁内容的 sha256 写进 `.redwood-patches`。`.redwood-patches` 的值与 `tools/mesa-patches/` 无关。
- arm64e 构建树 `out/ios26-resume/mesa-arm64e/mesa-26.2.5` 不属于任何 git 仓，由 `xnu-deps/build/mesa/mesa-26.2.5` 复制而来（`out/ios26-resume/mesa-arm64e/setup-inputs.json` 的 `source` 字段）。`tools/mesa-patches/` 的改动只存在于这棵构建树里，源树里没有，重新复制一次源树会丢掉它们。
- `air-build-record.json` 只覆盖 `build-air.py` 的 `FILES`（`tools/mesa/air/` 里的文件），补丁改的文件（`freedreno_resource.c`、`u_format.c`、`u_transfer.c` 等）都不在其中，补丁文件本身也不在 `package.py` 记录的源摘要里。查一轮的 AIR 库由什么编出来，`FILES` 读构建记录，补丁改的那些文件读补丁文件的提交；判断库里有没有某段插桩，用 `strings <库> | grep -c '<格式串>'`。

改这类文件分四步（以 `u_format.c` 为例）：

1. 拿改动前树里的那份反向应用旧补丁，得到原文：

```sh
cp out/ios26-resume/mesa-arm64e/mesa-26.2.5/src/util/format/u_format.c post.c
python3 - <<'PY'
t = open('tools/mesa-patches/fixguard6-shadow-counters.patch').read()
i = t.index('--- a/src/util/format/u_format.c\n')
open('/tmp/uf.patch', 'w').write(t[i:])          # 该文件那一段
PY
mkdir -p tree/src/util/format && cp post.c tree/src/util/format/u_format.c
cd tree && patch -p1 -R < /tmp/uf.patch && cp src/util/format/u_format.c ../pristine.c
```

2. 在 `pristine.c` 上改出目标内容，另存为 `new.c`。
3. 生成新段，替换补丁文件里从 `--- a/src/util/format/u_format.c` 那一行到文件末尾的部分：

```sh
diff -u pristine.c new.c \
  | sed -e '1s|^--- .*|--- a/src/util/format/u_format.c|' \
        -e '2s|^+++ .*|+++ b/src/util/format/u_format.c|' > uf-new.patch
```

4. 把新补丁打回 `pristine.c` 的副本，`cmp` 与 `new.c` 比较，一致再拷进构建树。

跑 `build-air.py` 之前先 `cmp <构建树里那份> <按补丁打出来的那份>`，不一致就停下再改。补丁是记录，构建树是编译输入，两者不一致时构建照样成功，唯一的迹象是一轮跑完日志里少几行。
