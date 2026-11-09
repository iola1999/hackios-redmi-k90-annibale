# 双系统分区与持久化部署手册

本文记录 REDMI K90（`annibale`）在 UFS LUN 0（`/dev/block/sda`）上划分 iOS 26 专用分区、写入系统盘与双启动 `xnuloader`，并在 iOS 26 与 Android 之间切换的步骤。

## 1. 分区规划

UFS LUN 0（`/dev/block/sda`）逻辑块大小为 4096 字节，原厂分区表末尾的 `userdata`（`/dev/block/sda34`，经 `dm-default-key` 映射为 `/dev/block/dm-55` 挂载到 `/data`）一直延伸到磁盘末尾。双系统部署从 `userdata` 尾部无损缩容出一块空间，新增两个分区（类型 GUID 均为 APFS Container `7C3457EF-0000-11AA-AA11-00306543ECAC`）：

- `darwin`（默认 `16 GiB`，Android 侧 `/dev/block/sda35`，XNU 侧 `/dev/ufs_darwin`）：存放原版未裁剪 iOS 26 系统镜像（`os.dmg` + `systemos.dmg` + `appos.dmg`，共 15.03 GB）或 `system26.apfs`，作为 iOS 26 只读系统盘挂载。
- `darwin_var`（自定义大小，Android 侧 `/dev/block/sda36`，XNU 侧 `/dev/ufs_darwin_var`）：挂载为 `/private/var` 可写数据盘，由内核直写块持久化层（`ANNFS001`）经 `annibale_ufshc` 原生 `WRITE(10)` 实时落盘。

不同整机存储容量可按需传入 `--var-gib` 调整划分大小；下文以 **256 GB 机型划分 120 GiB（16 GiB `darwin` + 104 GiB `darwin_var`）** 为例，512 GB／1 TB 等机型或不同空间分配需求请按实际情况填写 `--var-gib`，并以 `userdata-dual-carve.py` 根据本机 GPT 计算出的块数与 LBA 为准：

| 分区名 | Android 节点 | XNU 节点 | 256 GB 机型示例 LBA 范围 | 示例容量 | 用途 |
|---|---|---|---|---|---|
| `userdata` | `/dev/block/sda34` | `/dev/ufs_userdata` | `3518464..32584698` | 110.879 GiB | Android `/data` 分区（56,415 个 2 MB 主段） |
| `darwin` | `/dev/block/sda35` | `/dev/ufs_darwin` | `32584704..36779007` | 16.000 GiB | iOS 26 只读系统盘（存放 `os.dmg + systemos.dmg + appos.dmg` 或 `system26.apfs`） |
| `darwin_var` | `/dev/block/sda36` | `/dev/ufs_darwin_var` | `36779008..64041978` | 104.000 GiB | iOS 26 `/private/var` 可写数据盘（`ANNFS001` 直写持久化） |

## 2. 在线缩容与写入 GPT 分区表

Android 每次开机时，`fs_mgr` 会调用 `resize.f2fs` 将 `/data` 文件系统扩回 `userdata` 分区的大小。因此在线缩小 `/data` 与写回新 GPT 分区表必须在同一个 Android root 会话内连续完成，中途不要重启。

操作前确认 `/data` 剩余可用空间充足（`adb -s "$ANDROID_SERIAL" shell df -h /data`），并已按[分区备份与恢复](../backup/README.md)备份重要分区与个人数据。

下文的 `sda34`、`dm-55`、总块数和 LBA 都是测试机的值。在本机先用 `adb -s "$ANDROID_SERIAL" shell su -c "ls -l /dev/block/by-name/userdata"` 和 `adb -s "$ANDROID_SERIAL" shell su -c "grep ' /data ' /proc/mounts"` 查出 `userdata` 的分区节点与 `/data` 所在的 `dm` 节点，命令里的数值以这两条和 `userdata-dual-carve.py` 的输出为准。

```sh
# 1. 编译并推送在线缩容工具，读取本机 LUN 0 总块数并导出主备 GPT 表与 f2fs 超级块
bash hackios-xnu-kernel/tools/android/build.sh
adb -s "$ANDROID_SERIAL" root
adb -s "$ANDROID_SERIAL" push hackios-xnu-kernel/tools/android/f2fs-resize /data/local/tmp/f2fs-resize
adb -s "$ANDROID_SERIAL" shell chmod 755 /data/local/tmp/f2fs-resize
mkdir -p out/gpt-carve
BLOCKS=$(($(adb -s "$ANDROID_SERIAL" shell blockdev --getsize64 /dev/block/sda | tr -d '\r') / 4096))
adb -s "$ANDROID_SERIAL" shell "dd if=/dev/block/sda bs=4096 count=8" > out/gpt-carve/gpt-head.bin
adb -s "$ANDROID_SERIAL" shell "dd if=/dev/block/sda bs=4096 skip=$((BLOCKS - 8)) count=8" > out/gpt-carve/gpt-tail.bin
adb -s "$ANDROID_SERIAL" shell "dd if=/dev/block/dm-55 bs=4096 count=1" > out/gpt-carve/userdata-meta-before.bin

# 2. 生成新主备 GPT 表（--var-gib 104 为 256 GB 机型示例，其他容量机型按需调整）
python3 hackios-xnu-kernel/tools/userdata-dual-carve.py out/gpt-carve --root-gib 16 --var-gib 104

# 3. 按脚本输出的 Execution Sequence 块数与 seek 偏移执行缩容并写回主备 GPT 表
#    （下述数值为 256 GB 机型 64041984 块示例，其他容量机型请替换为脚本实际打印的命令）
adb -s "$ANDROID_SERIAL" shell "/data/local/tmp/f2fs-resize /data 29065728"
adb -s "$ANDROID_SERIAL" push out/gpt-carve/gpt-head.new /data/local/tmp/gpt-head.new
adb -s "$ANDROID_SERIAL" push out/gpt-carve/gpt-tail.new /data/local/tmp/gpt-tail.new
adb -s "$ANDROID_SERIAL" shell "dd if=/data/local/tmp/gpt-head.new of=/dev/block/sda bs=4096 skip=2 seek=2 count=2 conv=notrunc,fsync"
adb -s "$ANDROID_SERIAL" shell "dd if=/data/local/tmp/gpt-head.new of=/dev/block/sda bs=4096 skip=1 seek=1 count=1 conv=notrunc,fsync"
adb -s "$ANDROID_SERIAL" shell "dd if=/data/local/tmp/gpt-tail.new of=/dev/block/sda bs=4096 skip=4 seek=64041980 count=4 conv=notrunc,fsync"
```

## 3. 写入 iOS 系统盘

`darwin` 分区支持直接写入苹果原版未裁剪的 3 个 iOS 26 APFS 容器镜像（`os.dmg` 9.76 GB、`systemos.dmg` 5.26 GB、`appos.dmg` 14.68 MB，按 4096 字节块边界顺序拼接，总计 15.03 GB），也支持写入合成单容器镜像 `system26.apfs`。未重启前用脚本输出的 `darwin` 起始 LBA 作为 `seek`（256 GB 机型示例为 `32584704`），重启后可直接按块偏移写入 `/dev/block/by-name/darwin`（`/dev/block/sda35`）：

```sh
# 写入苹果原版未裁剪三容器镜像（os.dmg @ LBA+0, systemos.dmg @ LBA+2382336, appos.dmg @ LBA+3666944）
IPSW_DIR=hackios-xnu-kernel/out/ipsw/v57/26
adb -s "$ANDROID_SERIAL" push "$IPSW_DIR/os.dmg" /data/local/tmp/os.dmg
adb -s "$ANDROID_SERIAL" shell "dd if=/data/local/tmp/os.dmg of=/dev/block/sda bs=4096 seek=32584704 conv=notrunc,fsync && rm -f /data/local/tmp/os.dmg"
adb -s "$ANDROID_SERIAL" push "$IPSW_DIR/systemos.dmg" /data/local/tmp/systemos.dmg
adb -s "$ANDROID_SERIAL" shell "dd if=/data/local/tmp/systemos.dmg of=/dev/block/sda bs=4096 seek=$((32584704 + 2382336)) conv=notrunc,fsync && rm -f /data/local/tmp/systemos.dmg"
adb -s "$ANDROID_SERIAL" push "$IPSW_DIR/appos.dmg" /data/local/tmp/appos.dmg
adb -s "$ANDROID_SERIAL" shell "dd if=/data/local/tmp/appos.dmg of=/dev/block/sda bs=4096 seek=$((32584704 + 3666944)) conv=notrunc,fsync && rm -f /data/local/tmp/appos.dmg"
```

`darwin_var` 的持久化格式（`ANNFS001` 超级块或节点记录）变化后，内核不读取旧数据：两个元数据槽位均无有效超级块且不全为零时，`/private/var` 挂载失败，开机停在 launchd 之前。这时在 LK 下把 `darwin_var` 前 64 MiB（两个 32 MiB 元数据槽位）写零，下次开机重建空的 `/private/var`，已安装的应用、Wi-Fi 网络和设置随之清空，需要保留的先备份：

```sh
head -c 67108864 /dev/zero > zero64m.img
fastboot -s "$ANDROID_SERIAL" flash darwin_var zero64m.img
fastboot -s "$ANDROID_SERIAL" reboot
```

## 4. 刷入双启动 loader 与切换系统

REDMI K90 采用 A/B 双槽位设计，当前正在运行的 Android 可能位于 `a` 槽或 `b` 槽。独立双系统引导镜像（[开发指南](../development.md) §8 的 `boot-a-ios.img`，或 Release 用户合成的 `boot-ios.img`，含已链接 `ath12k.o` 的内核、带 Wi-Fi 固件的 `root.apfs` 与 `loader-phone.efi`）应刷入与当前 Android 相对的**闲置槽位**（若 Android 在 `b` 槽则刷入 `boot_a`；若 Android 在 `a` 槽则刷入 `boot_b`）：

```sh
adb -s "$ANDROID_SERIAL" reboot bootloader
fastboot -s "$ANDROID_SERIAL" getvar current-slot   # 查看当前 Android 所在槽位（a 或 b）

# 以当前 Android 在 b 槽、将 loader 刷入闲置的 a 槽为例（若 Android 在 a 槽则改为 boot_b 与 set_active b）：
fastboot -s "$ANDROID_SERIAL" flash boot_a "$LOADER_IMG"
fastboot -s "$ANDROID_SERIAL" set_active a
fastboot -s "$ANDROID_SERIAL" reboot
```

`xnuloader` 启动时读取 `boot_a` 与 `boot_b` 开头的镜像头：header v1 且 kernel 段为 gzip 的是 loader 镜像，原厂 Android 的 boot 镜像是 header v4。只有一侧是 loader 镜像时，那一侧记为自身槽位（`loader_slot`），另一侧记为 Android 槽位（`android_slot`），不需要固定哪个槽位是 A 或 B。两侧均非 loader 镜像（从 LK 用 `fastboot boot` 临时启动）或两侧都是时，loader 不改动任何槽位属性，菜单不显示槽位，「Boot Android」直接重启进入当前活动槽位，USB 刷写命令也会拒绝执行。刷入后的启动与切换方式（详见[引导目标切换 SOP](device-boot-target-sop.md)）：

- **日常开机进 iOS 26**：按电源键开机，`xnuloader` 自动维护自身槽位的 `slot-retry-count`，显示启动菜单并倒计时 5 秒；倒计时结束后自动加载内核、挂载 `darwin` 与 `darwin_var` 进入 iOS 26 桌面。
- **从开机菜单切回 Android 或调试模式**：在 5 秒倒计时内按音量上／下键移动光标，按电源键确认，可选「Boot iOS 26」、「Boot Android」（自动将活动槽位切换到另一侧的 `android_slot` 并重启）或「USB Fastboot Debug Mode」。
- **从 Android 切回 iOS 26**：在 Android 的 root 终端 App 或 `adb shell` 中将活动槽位切到 `xnuloader` 所在槽位（`0` 对应 `a` 槽，`1` 对应 `b` 槽）并重启，例如 `su -c 'bootctl set-active-boot-slot 0 && reboot'`；或在 FASTBOOT 模式下执行 `fastboot -s "$ANDROID_SERIAL" set_active <loader槽位> && fastboot -s "$ANDROID_SERIAL" reboot`。

## 5. Android 系统内更新（OTA）与槽位轮换

Android 的 Virtual A/B 系统更新（`update_engine`）在后台将新版本系统写入当前的**闲置槽位**，并在重启后将活动槽位切换到新槽位。对双系统分区与引导的具体影响如下：

- **iOS 分区与用户数据完全保留**：系统内 OTA（`update_engine`）只更新 A/B 槽位固件分区（`boot_a/b`、`init_boot_a/b`、`vendor_boot_a/b`、`dtbo_a/b`、`vbmeta_a/b` 等）与 `super` 动态分区（快照 COW 文件暂存在 `/data/gsi/ota`），不会刷写 `gpt_both0.bin`。重启时 Android `fs_mgr` 的 `resize.f2fs` 仅按当前 GPT 表中 `userdata`（`sda34`）的起止块数对齐文件系统，因此 UFS LUN 0 上的 `darwin`（`sda35`）与 `darwin_var`（`sda36`）分区及 iOS 26 持久化数据不受影响。
- **增量 OTA 更新**：`update_engine` 会校验源槽位（当前 Android 槽位，若已刷入 Magisk／KernelSU 则 `boot` 或 `init_boot` 哈希已变）及部分目标槽位分区的原厂哈希，校验不通过会拒绝安装。若要安装增量 OTA，需先恢复原厂未修改的 `boot`／`init_boot` 镜像；日常升级建议直接在系统更新中下载并安装**完整包 OTA（Full ROM）**。
- **完整包 OTA 更新与恢复双启动步骤**：
  1. `update_engine` 会直接把新版本 Android 的 `boot`、`init_boot`、`vendor_boot`、`super` 等写入原先存放 `xnuloader` 的闲置槽位（例如原 Android 在 B 槽、loader 在 A 槽，完整 OTA 会把新 Android 写进 A 槽，覆盖 `boot_a` 中的 `xnuloader`）。
  2. 若当前 Android 已 Root 且希望更新后保留 Root，在系统更新提示「立即重启」前，先打开 Magisk／KernelSU 选择「安装到未使用的槽位（OTA 后）」。
  3. 重启进入新版本 Android（此时活动槽位已轮换到新槽位，如 A 槽，原 B 槽退为闲置槽位），等待系统后台完成 Virtual A/B 快照合并（`update_engine` 状态回到 idle）。
  4. 将 `xnuloader` 镜像刷入退下来的新闲置槽位（如 `fastboot -s "$ANDROID_SERIAL" flash boot_b "$LOADER_IMG"`）并切槽（`fastboot -s "$ANDROID_SERIAL" set_active b`），即可恢复双启动。
- **原厂 Fastboot 线刷包（`flash_all.sh`）**：原厂线刷脚本会刷写 `gpt_both0.bin` 重建 LUN 0 分区表并执行 `fastboot erase userdata`，这会抹除 `darwin` 与 `darwin_var` 分区。日常升级不要执行未裁剪 `gpt_both0.bin` 的 `flash_all.sh`。

## 6. 恢复原厂分区表

如需移除 `darwin` 与 `darwin_var` 并把空间归还给 Android `userdata`，在 Android root shell 下将第 2 节备份的 `out/gpt-carve/gpt-head.bin` 与 `out/gpt-carve/gpt-tail.bin` 按相同 `dd` 偏移写回 `/dev/block/sda`，随后重启 Android，系统 `fs_mgr` 的 `resize.f2fs` 会自动将 `/data` 扩回完整分区大小。
