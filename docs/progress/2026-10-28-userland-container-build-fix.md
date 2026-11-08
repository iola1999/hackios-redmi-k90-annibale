# 26 线 userland 的架构要求与容器构建的限制（2026-10-28）

`hackios-xnu-userland/userland/build.sh` 的架构闸门在拒绝时打印本文路径。本文说明 26 线镜像为什么需要 arm64e、容器里的 clang 为什么编不出合格产物、闸门检查什么、哪些观察能推翻它，以及在容器里跑 26 线构建会遇到的问题。26 线产物在宿主上用 `tools/k90auto/package.py` 与 `tools/k90auto/build-air.py` 构建，见 [arm64e 构建路径](../analysis/2026-10-28-arm64e-userland-build-path.md)。

## 1. 为什么需要 arm64e

- 26 线镜像只带 arm64e 的共享缓存：`hackios-xnu-kernel/ios26/23G90__iPhone18,3/` 下只有 `dyld_shared_cache_arm64e*`，系统进程都是 arm64e。
- 加载进 arm64e 进程的库（dylib、bundle）必须是 arm64e 切片，dyld 丢弃 arm64 切片且不打印任何行。两次实测：AIR 库为 arm64 时着色器不翻译、GPU 收不到提交，桌面 9～11 帧／秒，换 arm64e 后 60 帧／秒（`build.sh` 的 AIR 架构检查注释）；2026-10-29 `libannibale.dylib` 为 arm64 时 backboardd 里这个库的功能都没有生效（`tools/k90auto/package.py` 的断言注释）。
- Apple clang 编出的 arm64e 切片 `cpusubtype` 为 `0x80000002`（LIB64 位 `0x80000000` 加 ARM64E 的 2）；容器 clang 18 编出 `0x00000002`，arm64 为 `0x0`。

容器 clang 18 编不出可用的 26 线产物，原因有两条，都在容器里实测过：

1. 容器 clang 18 的 `__has_feature(ptrauth)` 为 0。这比缺头文件更危险：`ptrauth_strip()` 在没有 ptrauth 支持时原样返回，`src/inject_sb26.c` 会把带 PAC 签名的指针当地址用。产物是有效的 Mach-O，装上设备后才在运行时出错。
2. `<ptrauth.h>` 是 clang 资源目录里的头文件，不在 SDK 里。容器 clang 18.1.3 的资源目录 `/usr/lib/llvm-18/lib/clang/18` 有 204 个头文件，没有 `ptrauth.h`，iPhoneOS SDK 的 `usr/include` 里也没有。补一个头文件进去，`__has_feature(ptrauth)` 仍是 0（按上面两条推断，没有实际补了再编）。

## 2. 架构闸门

位置在 `build.sh` 的 staging 完成之后、第一个 `mkapfs` 之前，只在 `V=26` 时运行，拦的是即将进镜像的文件：

- 遍历 `root/`，跳过符号链接与非 Mach-O 文件。
- `MH_DYLIB`、`MH_BUNDLE` 按动态处理；`MH_EXECUTE` 只在有 `LC_LOAD_DYLINKER` 时按动态处理。静态程序（`init`、`child`、`stage0`，都是 `-static -nostdlib` 编的）不进 dyld，不检查。
- 拒绝 fat 文件；动态文件要求 `cputype == 0x100000c` 且 `cpusubtype == 0x80000002`。有拒绝就以退出码 1 结束。
- `COMPILE_ONLY=1` 在闸门之后、写镜像之前退出，用来只验证工具链。

拒绝时的报文只陈述闸门测到的值和它的要求：

```
build.sh: <path> is an arm64 slice (cpusubtype 0x0), and this gate requires 0x80000002
build.sh: <path> is arm64e without the LIB64 bit (cpusubtype 0x2), and this gate requires 0x80000002
build.sh: <path> is a fat binary, and this gate requires one thin arm64e slice
build.sh: <path> is cputype 0xNN, and this gate requires 0x100000c (arm64e)
build.sh: N of the programs staged for this image are not arm64e with the LIB64 bit
build.sh: the 26 line has to be built on a host with Apple clang; a container clang has no ptrauth
build.sh: why this image needs arm64e, and what would falsify it: docs/progress/2026-10-28-userland-container-build-fix.md
```

2026-10-28 对当时装车的根盘（`hackios-xnu-kernel/out/ios26-resume/bbmetal-device/root`）跑一遍：39 个拒绝、8 个通过。39 个都是 arm64（cpusubtype `0x0`）：

- `root/lib` 下 9 个：`libannibale-app`、`-fairplay`、`-media`、`-sb`、`-store`、`-tweaks`、`libannibale.dylib`、`AnnibaleMetal.bundle/AnnibaleMetal`、`AnnibaleAudio.driver/AnnibaleAudio`。
- `root/bin` 下 30 个程序。
- 通过的 8 个：`libannibaleair.dylib`、`libannibalemetal.dylib`、`libannibale-sb26.dylib`、`libannibale-sbmetal-experiment.dylib`、`input26-service`、`lsprobe`、`framewatch`、`mg_test`。

## 3. 哪些观察能推翻这个要求

「被拒的文件在 26 镜像里加载不了」由「镜像只有 arm64e 共享缓存」推出，闸门本身没有测。能推翻它的观察是：任何一份 26 线日志里出现被拒程序的输出。

- 库：推论有实测支持，见 §1 的两例。
- 可执行文件：已有反例。`package.py` 的基础根盘里 `hackios-xnu-kernel/out/ios26-resume/air-arm64e-device/on/root/bin/rwtouch` 是 arm64（cpusubtype `0x0`，`build.sh` 用 `$DYN`，即 `-arch arm64` 加 iOS 16.5 SDK 编出），`cycle.py` 的巡检在 iOS 26 上用它点按和滑动，[总账](../plan/2026-10-23-tracking.md)也记有 26 线日志里 rwtouch 正常。arm64 动态可执行文件能在 26 镜像里运行，闸门拒绝它们比实测需要的更严。2026-11-05 起 macOS 上的 `build.sh` 用 Xcode 的 clang 把动态程序也编成 arm64e，闸门全部通过，闸门保持原样；`base26a` 一轮里 arm64e 的 `rwtouch` 点按、滑动正常。

## 4. 在容器里跑 26 线构建会遇到的问题

- `CoreFoundation/CoreFoundation.h not found`：`hackios-xnu-kernel/xnu-deps/26/sdk/iPhoneOS.sdk` 的 `System`、`Developer`、`Entitlements.plist` 是指向宿主 Xcode SDK 的符号链接（`System` 指向 `/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/Developer/SDKs/iPhoneOS27.1.sdk/System`），容器里没有 `/Applications`，框架头整个不存在。theos 的 `iPhoneOS16.5.sdk` 是另一份 SDK，与此无关。
- `docker/dev.sh` 用 `readlink` 求出这个 SDK 的根，以同一绝对路径只读挂进容器；解析不出或不是目录时打印一行并照原参数启动。`build.sh` 在编译前检查 SDK 能否解析，不能时报 `build.sh: the iOS 26 SDK has no frameworks in this environment`，并说明要以同一绝对路径只读挂载。
- 挂上 SDK 之后，容器构建停在 `src/inject_sb26.c:11` 的 `'ptrauth.h' file not found`，这是 §1 的预期结果。
- `xnu-deps/host/bin/ld64`：`hackios-xnu-kernel/tools/mk-mesa.sh` 用 `[ -e "$LD64" ] || ln -sfn "$THEOS/toolchain/linux/iphone/bin/ld" "$LD64"` 建这个链接。`-e` 跟随符号链接，链接失效时会被改写；宿主和容器的 `$THEOS` 不同，在同一工作区跑过容器构建后，链接指向容器内的路径。该目录被 `.gitignore` 忽略，没有历史可查。这个问题只记录，没有做结构性修复。
- `PREBUILT=1` 静默生效：`build.sh` 在 `PREBUILT` 未设且 PATH 上没有 `ld64` 时自动设为 1，跳过整段编译，改用 `prebuilt/userland`。`libannibalemetal.dylib` 与 `lsprobe` 有「存在且比源文件新」的断言（`lsprobe` 的断言还没有被真实构建触发过）；其余程序按 `if [ -f obj/$t ]` 装进镜像，缺了不装，旧了装旧的。
- `ldid`：26 分支有三处无条件调用 `${LDID:-ldid}`，`set -e` 下找不到就停。容器里 `ldid` 在 `$THEOS/toolchain/linux/iphone/bin/ldid`，不在 PATH；`build.sh` 在 `LDID` 未设且 PATH 上没有时取这个路径并 `export`，因为后面的 python 段从环境读 `LDID`。
- `docker/dev.sh` 的参数展开写成 `${SDK_ARGS[@]+"${SDK_ARGS[@]}"}`：宿主 bash 3.2.57 在 `set -u` 下直接展开空数组会报 unbound variable。`dev.sh` 带 `-it`，没有 pty 的 shell 里会报 `openpty: Operation not permitted`，与挂载是否生效无关。
