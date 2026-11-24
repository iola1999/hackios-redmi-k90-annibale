# ko/sys.dic 跨 extent 读取与 UFS DMA 对齐

2026-11-24，`kernel-12377-say56-ubo59` 读取韩语分词词典失败。APFS 拼接跨 extent 的压缩片时，将偏移 413 字节的目标地址交给 UFS 块设备。驱动将该地址直接写入要求 4 字节对齐的 PRD（Physical Region Descriptor）。`12377-s21-prdt1` 已在提交 DMA 请求前检查对齐情况，真机已能逐块读出完整词典，内容与主机参考文件相同。

## 1. 原轮次现象

- 35 份 `searchd` 崩溃报告在 `/usr/share/tokenizer/ko/sys.dic` 偏移 `0x71581e` 记录 `SIGBUS` 和 `FS pagein error: 5 Input/output error`。同区间的 `pread` 返回 `EIO`。
- 词典使用 decmpfs type 4。第 113 个压缩片对应解压后的第 1808～1823 个 4 KiB 块。第 111 个压缩片在 ubo58、ubo59 也各失败一次。同机抽查的日语词典及其他压缩文件可读。
- 原卷来自 `os.dmg`（`LuckG23G90.V57OS`，2,382,336 块）。原轮次 UFS 读了 6.2 GB，292,785 个异步请求的控制器错误计数为 0。
- ubo58 指定 `ufs_coherent=0`，ubo59 使用默认值，两轮都读错 piece 113。通过字符设备 `/dev/rufs_darwin` 同步读出的 25,678 字节可解压为完整的 65,536 字节。主机以 XNU zlib 和 libdeflate 分别解压成功。

## 2. 第 113 个压缩片的边界

`apfs-tool piece` 读得资源 fork 内起点为 3,657,315，长度为 25,678。第一个 extent 的逻辑区间为 `[0, 3674112)`，物理起始块为 1,504,377。压缩片在这个 extent 中占 16,797 字节，另有 8,881 字节在它之后。

| `stream_fetch` 对首个 extent 的操作 | 长度 | 目标 |
|---|---:|---|
| 从首个物理块的偏移 3,683 起复制 | 413 字节 | 压缩片开头 |
| 交给块设备直接读取连续的 4 个整块 | 16,384 字节 | 压缩片缓冲起点 + 413 |

`apfs_dev_read_data` 通过 `buf_setdataptr` 将第二笔请求的目标原样交给块设备。缓冲起点按字对齐，加 413 后地址的低两位为 1。旧驱动的 `ufs_build_sg` 将它转换为物理地址，`hc_place_sg` 直接填入 PRD。

以字符设备读出的压缩片为参照，ubo59 日志的 `src[400:412]` 相同，`src[412:424]` 与参照的 `src[413:425]` 相同。差异开始于前缀复制的最后一个字节，符合控制器按 4 字节边界使用目标地址的结果。该窗口以外未逐字节比较。

原内核日志取 FNV 初值 `0x14650fb0739d0383`。用同一初值计算正确压缩片得 `fcc7b117a85719ba`，内核日志为 `f7fd5b9abdea4816`。用 `apfs-tool` 的初值 `0xcbf29ce484222325` 计算正确压缩片得 `8705006c5019afac`。

## 3. 驱动修改与主机测试

`ufs_build_sg` 完成建段后检查每段物理地址和字节数是否按 4 字节对齐。满足要求的块请求继续异步提交。其余请求由 `ufs_strategy` 使用已有的同步路径，在对齐的槽缓冲和调用者的内存之间复制。读写共用这项检查，适用于 UPL 页列表和内核缓冲两种地址来源。[EDK II 的 UFS 缓冲处理](https://github.com/tianocore/edk2/blob/master/MdeModulePkg/Bus/Ufs/UfsPassThruDxe/UfsPassThruHci.c)

运行 `python3 tools/run-host-tests.py ufs-prdt`。测试编译驱动的 `ufs_build_sg` 和 `ufs_strategy`，检查 7 种偏移、3 种缓冲来源（直接地址、临时映射、UPL）的读写，共 42 种组合。测试核对传输方式、完整数据、传输区两侧字节、临时映射释放与请求完成次数。

## 4. 验收范围

| 检查 | 结果 |
|---|---|
| 主机 PRDT 回归测试 | 42 种组合通过 |
| `12377-s21-prdt1` 内核 | XNU 26 编译、链接成功 |
| 主机参考文件 | 完整词典 14,906,940 字节，SHA-256 为 `1f46217be9fb55f7eae09e8081dcf91d665a6d097fe5b44bff293fbabf6d40c1` |
| 压缩片内容 | 同步读出的 piece 113 解压后与参考文件对应区间逐字节相同 |
| 修复后真机 | `kernel-12377-s21-prdt1-device1` 以 4 KiB 为单位读取完整词典，字节数与 SHA-256 均与主机参考文件相同 |

## 5. locationd 写入异常

`locationd` 在 reprompt 回调写入 `allSecondaryCombined` 时出现 `NSFileHandleOperationException`。同路径的 `fhw_test` 能打开并写入文件。已有检查覆盖打开参数、磁盘空间、挂载读写状态和文件属性。内核保留 `apfs_vnop_write` 和 `apfs_vnop_open` 的错误日志，等回调再次失败后核对 errno。
