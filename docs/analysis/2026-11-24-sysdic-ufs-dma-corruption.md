# UFS 异步读数据错位定位：ko/sys.dic piece 113（进行中）

调查起点：`searchd` 高频崩溃（35 份报告，`SIGBUS` / `FS pagein error: 5 Input/output error`）全部指向 `/usr/share/tokenizer/ko/sys.dic` 偏移 `0x71581e`。截至内核 `12377-say56`（ubo59）已定位到字节级：内核经 UFS 异步 DMA 取回的数据与盘上不同，在取回缓冲偏移 4095 处丢一字节。写路径的 `locationd` `writeData:` 中止另案插桩待命中（见 §7）。

## 1. 现象与影响面

- 真机复现：`pagein_test2` 对 `ko/sys.dic` 第 1808–1823 块 `pread` 确定性 EIO，`mmap` 同一区间 SIGBUS；piece 边界为 1776–1791（piece 111）与 1808–1823（piece 113）。
- `ko/sys.dic` 为 decmpfs type 4 压缩文件（资源 fork），损坏区即 piece 113 的压缩片（`off 3657055 len 25678`）。
- 单点性：同设备 `ja/sys.dic`（20 MB）与约 15 个其余压缩文件全部正常；ubo58 起 piece 113 每轮稳定失败约 950 次，piece 111 偶发（ubo58、ubo59 各一次 `first=1776`）。
- UFS 计数器：异步路径 `ufs_native_requests=292785`、`errors=0`、读取 6.2 GB，整体健康，仅此 piece 确定性失败。

## 2. 已排除项

- 盘上数据完好：iOS 版 `apfs-tool`（`/var/tmp/atool2`）在设备直读 `/dev/rufs_darwin`，piece 113 物理块 1504377 起连续，原始字节 FNV `8705006c5019afac`，用户态 zlib 解出 65536 字节（FNV `83549053696a62ad`）。与内核共用同一份 `apfs_lib.c`。
- 系统卷为原厂 `os.dmg`（`LuckG23G90.V57OS`，2,382,336 块），非 mkapfs 构建。
- zlib 无罪：xnu 1.2.3 与 libdeflate 在主机对同一批原始字节均解出 65536；内核两条解码路径都失败。
- 缓存一致性参数：`ufs_coherent=0`（启用 PRDT 逐段 `FlushPoC_DcacheRegion`）不改结果，piece 113 仍 `got=605`。
- 同步路径对照：用户态经 `/dev/rufs_darwin` 的 `ufshc_read`（槽缓冲 + memcpy）取回字节正确；只有内核块设备的 `ufshc_strategy_async`（SG 直 DMA 入 `sc->raw`）路径出错。

## 3. 字节级定位（say56，ubo59）

失败日志（每轮约 950 次）：

```
apfs: piece 113 read/decode failed (5): type 4 plen 25678 want 65536 got 605
    zin 437 zerr -3 src 78 5e 4c 5d poff 3657315 fnv f7fd5b9abdea4816
apfs: piece 113 src[400:424]: 95 78 c7 0f 52 29 1f 6a 26 54 d3 f6 61 55
    91 31 c3 b9 e0 a1 64 3a de 72
```

与设备上正确字节逐位比对：

- `src[400:412]` 与正确数据一致；内核 `src[412]=0x61` 等于正确数据的 `src[413]`，正确的 `src[412]=0x96` 缺失，其后全部左移一字节。
- 缺失点对应 `sc->raw` 偏移 `3683 + 412 = 4095`，即取回缓冲第一个 4 KiB 页的末字节（本内核 `PAGE_SHIFT = 12`）。
- `zerr -3`（`Z_DATA_ERROR`）：zlib 消费 437 字节后撞到错码，与一字节缺失导致的解码失步吻合；`got 605` 即失步前输出。
- 取回数据 FNV `f7fd5b9abdea4816` ≠ 盘上 `8705006c5019afac`，坐实 DMA 交付字节与盘上不同。

## 4. 假设与代码审查状态

最吻合的模型：第二个 PRD 段的物理地址比其目标页低 1 字节。此时第二段首字节覆盖 `sc->raw[4095]`，其后流数据整体前移，`sc->raw[8191]` 保留旧值（未验证，say56 只打印了 `src[400:424]` 一个窗口）。次选模型：控制器按 PRD 声明长度切分流时某段长度少 1，预测形态不同（`buffer[4095]` 为旧值且 `buffer[4096]=stream[4095]`），与实测不符，可排除。

已审查未找到 -1 来源的环节：

- `ufs_build_sg`（`annibale_ufshc_rw.inc:467`）：无 UPL 时 `kvtophys` 逐页建段，合并条件 `pa + len == pa'`。
- `hc_place_sg`（同文件 397）：PRD 项 `{pa_lo, pa_hi, 0, len-1}`，UTRD 的 PRDT 偏移与段数正确。
- `ufshc_dcache_sg_poc`（`annibale_ufshc.c:295`）：按物理地址逐页 cache 维护。
- `scratch_get`（`apfs_lib.c:3355`）：`sc->raw`（`kalloc_data`，物理不连续）每次请求独占。

## 5. 下一步（say57）

`ufshc_strategy_async` 按 `first_lba == 34089973 && blocks == 8`（`ufs_lun_offset[darwin]/4096 + 1505269`）打印：

- `ufs_build_sg` 输出的每段 `{pa, len}`；
- 写入 UCD 的 PRD 双字原文；
- 完成后 `sc->raw` 的 `[4080:4112]` 与 `[8176:8208]` 两窗口，看 `buffer[8191]` 是否为旧值，区分「段地址 -1」与其他形态。

备选旁证：失败后同 LBA 走同步槽路径重读比对首差异偏移，改动较大，优先级次于段表输出。

## 6. 现场与复现

- 轮次 `kernel-12377-say56-ubo59` 持有中（iOS 桌面）；boot-args 无 `ufs_coherent`（取默认值），`ufs_coherent=0` 实验已在 ubo58/ubo59 完成。
- 复现：`push-request` 写入 `/tmp/pagein_test2` → `pull /var/tmp/pt 0` → `chmod 755 /var/tmp/pt` → `/var/tmp/pt`，`ko/sys.dic` 行报 `bad_blks` 与 `first`。
- 参照数据：piece 113 原始字节 base64 在 `docs/progress/evidence/`（atool `piece` 命令输出留存）；主机可复算 FNV `8705006c5019afac`。
- 改动未提交：内核 `apfs_lib.c`（say54–56 插桩）、`apfs_vnops_write.inc`（写路径错误日志）；用户态 `apfs-tool` 新增 `piece` 子命令、`img.c` 原始设备尺寸回退、`dpw_test.c`/`fhw_test.m` 诊断程序。

## 7. 并案：locationd writeData 中止

`locationd` 每次 reprompt 周期在 `allSecondaryCombined` 的 `writeData:` 上 `abort`（`NSFileHandleOperationException`）。已排除：fd 打开参数（`open_dprotected_np` flags 原样透传）、磁盘空间、只读挂载、文件属性；真路径真调用的 `fhw_test` 全部通过。崩溃只发生在周期回调，需 `apfs_vnop_write` 错误路径插桩（say54 起已编入）等下次 reprompt 命中后读 errno。是否与本节 DMA 读损坏同源待 errno 确认。
