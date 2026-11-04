# 分区备份与恢复

写入 loader 前，建议先备份手机上的重要分区。Wi-Fi 固件也从 modem 分区的备份里取。备份文件含有能识别这台手机的数据，保存在 Git 忽略的目录（例如工作区的 `annibale-backup/`）或 `BACKUP_DIR` 指向的位置，不要提交。

## 1. 备份

读取分区需要 Android 已获取 root（本测试机用 KernelSU）。先列出分区名，再逐个读出并压缩：

```sh
adb -s "$ANDROID_SERIAL" shell su -c "ls /dev/block/by-name"
adb -s "$ANDROID_SERIAL" shell su -c "dd if=/dev/block/by-name/boot_a bs=4096 2>/dev/null" | gzip -1 > boot_a.img.gz
```

- 至少备份两个槽位的 `boot`、`init_boot`、`vendor_boot`、`dtbo`，以及 `modem_a`（Wi-Fi 固件来源）。
- 校准与密钥分区 `modemst1`、`modemst2`、`fsg`、`persist`、`keystore`、`devinfo`、`secdata` 也建议备份。本测试机备份了全部不超过 2 GiB 的具名分区，共 123 个，跳过了 `super` 和 `userdata`。
- 核对：在手机上执行 `sha256sum /dev/block/by-name/<分区>`，与 `gunzip -c <分区>.img.gz | shasum -a 256` 的结果比较。

## 2. 恢复

```sh
gunzip -c boot_a.img.gz > boot_a.img
fastboot -s "$ANDROID_SERIAL" flash boot_a boot_a.img
```

- 恢复 `modemst1`、`modemst2`、`fsg`、`persist` 后，关机再开机，让基带重新加载。
- `super` 与 `userdata` 不在这份备份里，刷机或清数据前另行处理。
