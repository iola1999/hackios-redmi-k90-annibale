# Docker 环境（M0）

linux/arm64 的 Ubuntu 24.04，装齐 HackiOS 构建与 QEMU 运行依赖（python3、7z、clang+lld、dtc、qemu-system-aarch64、edk2-aarch64），另带 nasm、iasl、uuid-dev，用于从源码编译 Mu-Silicium UEFI。QEMU 在 OrbStack 里仍是 TCG（虚拟机内没有嵌套 KVM），与上游 Linux 主机一致，不影响使用。

iOS 交叉工具链也在镜像里：theos、ld64（x86_64，经 OrbStack 的 Rosetta 运行，所以镜像开了 amd64 multiarch）和 iPhoneOS16.5.sdk，版本与 sha256 固定在 Dockerfile 里，`hackios-xnu-kernel/tools/mk-mesa.sh` 可以直接用（见 [Mesa rebase 记录](../docs/analysis/mesa-rebase-2026-10.md)的 iOS 交叉构建一节）。

```sh
./build.sh            # 产出 hackios-dev:latest
./dev.sh              # 进容器，工作区挂在 /work
```

主机装有 Xcode 时，`dev.sh` 读取 `hackios-xnu-kernel/xnu-deps/26/sdk/iPhoneOS.sdk/System` 这个符号链接，把它指向的主机 iOS 26 SDK 按同一绝对路径只读挂进容器；没有这个挂载，iOS 26 的 userland 构建找不到框架头文件（见 `dev.sh` 注释）。

## 1. 容器内首次初始化（两个子模块合成一棵树）

```sh
cd /work/hackios-xnu-kernel          # k90-port 分支
common/setup.sh                      # 把 userland 仓收进 .userland.git，双仓合一棵树
ios165/fetch.sh                      # 7.4GB IPSW，解包到 ios165/extract/
userland/build.sh                    # 产 userland/{root,system}.apfs（REST=1 可换源）
```

## 2. headless 跑 QEMU（验收 iOS 开机的标准方式）

```sh
cd /work/hackios-xnu-kernel
QEMU_RAM_GB=4 qemu/run-ios.sh 600 &               # 600 秒后自动关机；默认无窗口
qemu/screendump.sh /tmp/ios.png                    # 锁屏截图即开机成功的判据
qemu/touch.py drag up                              # 上滑解屏；qemu/stop.sh 提前停
```

内存：每个 QEMU 实例占用宿主机 2.5～3 GB，`run-ios.sh` 在可用内存不足 3000 MB 时拒绝启动（`QEMU_FORCE=1` 强制启动）。OrbStack 虚拟机的内存是实际上限，不够时调 OrbStack 设置或减小 `QEMU_RAM_GB`。端口：monitor 4444、QMP 4445；多实例用 `QEMU_INSTANCE=n`，端口为 4444+10n 与 4445+10n。

## 3. 性能备注

`/work` 走 VirtioFS，大文件（IPSW 解包、apfs 打包）可能慢；明显变慢时，把树放进容器卷里构建，再把 git 改动写回工作区。
