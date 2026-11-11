# Docker 环境（M0）

linux/arm64 的 Ubuntu 24.04，用于 Mu-Silicium UEFI 构建、Mesa 补丁准备与 QEMU 运行。镜像带有 python3、7z、clang+lld、dtc、qemu-system-aarch64、edk2-aarch64，以及编译 UEFI 所需的 nasm、iasl、uuid-dev。QEMU 在 OrbStack 里使用 TCG，虚拟机内没有嵌套 KVM。

iOS 交叉工具链也在镜像里：theos、ld64（x86_64，经 OrbStack 的 Rosetta 运行，所以镜像开了 amd64 multiarch）和 iPhoneOS16.5.sdk，版本与 sha256 固定在 Dockerfile 里，`hackios-xnu-kernel/tools/mk-mesa.sh` 可以直接用（见 [Mesa rebase 记录](../docs/analysis/mesa-rebase-2026-10.md)的 iOS 交叉构建一节）。

```sh
./build.sh            # 产出 hackios-dev:latest
./dev.sh              # 进容器，工作区挂在 /work
```

主机装有 Xcode 时，`dev.sh` 读取 `hackios-xnu-kernel/xnu-deps/26/sdk/iPhoneOS.sdk/System` 这个符号链接，把它指向的主机 iOS 26 SDK 按同一绝对路径只读挂进容器，供容器访问框架头文件。iOS 26 的 arm64e 程序仍需在 macOS 上用 Apple clang 构建，依赖和步骤见[开发指南](../docs/development.md#1-环境)。

## 1. 容器内首次初始化

- UEFI：按 [annibale UEFI 与 loader 镜像构建](../docs/analysis/annibale-uefi-build.md#2-构建-fd) 准备 Mu-Silicium 源码并在容器中构建。
- Mesa：容器负责下载、解包和应用补丁；arm64e 构建树与主机编译步骤见 [arm64e 用户态构建 §6](../docs/analysis/2026-10-28-arm64e-userland-build-path.md#6-构建树从仓库重建)。
- iOS 26.6.2 系统文件与用户态：在 macOS 上按[开发指南 §3](../docs/development.md#3-下载并解密-ipsw)和[§6](../docs/development.md#6-构建用户态与启动卷)准备。`ios26/fetch.sh` 使用 `hdiutil`，`userland/build.sh` 使用 Apple clang 与 Xcode 工具。

## 2. headless 跑 QEMU

先准备本轮内核、系统盘与辅助盘，路径由 [`qemu/run-ios.sh`](../hackios-xnu-kernel/qemu/run-ios.sh) 的 `KERNEL`、`IMG`、`ROOT` 选择。锁屏截图用于确认 QEMU 中的桌面启动；K90 真机验收见[真机调试手册 §7](../docs/plan/device-test-playbook.md#7-四阶段验收)。

```sh
cd /work/hackios-xnu-kernel
QEMU_RAM_GB=4 qemu/run-ios.sh 600 &               # 600 秒后自动关机；默认无窗口
qemu/screendump.sh /tmp/ios.png                    # 保存 QEMU 锁屏截图
qemu/touch.py drag up                              # 上滑解屏；qemu/stop.sh 提前停
```

内存：每个 QEMU 实例占用宿主机 2.5～3 GB，`run-ios.sh` 在可用内存不足 3000 MB 时拒绝启动（`QEMU_FORCE=1` 强制启动）。OrbStack 虚拟机的内存是实际上限，不够时调 OrbStack 设置或减小 `QEMU_RAM_GB`。端口：monitor 4444、QMP 4445；多实例用 `QEMU_INSTANCE=n`，端口为 4444+10n 与 4445+10n。

## 3. 性能备注

`/work` 走 VirtioFS，大文件（IPSW 解包、apfs 打包）可能慢；明显变慢时，把树放进容器卷里构建，再把 git 改动写回工作区。
