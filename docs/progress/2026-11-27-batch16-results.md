# 2026-11-27 批 16 真机实测、代码储备与只读定案记录（b5r48～b5r50）

本记录汇总批 16 三轮真机测试：`b5r48`、`b5r49b`（`flipwd25` + `27dc30a`/`1c2f6a9` 用户态）与 `b5r50`（`xnu12377-flipwd26.bin` + `libannibaleair.dylib` `3d7cec62...` + 重编用户态），以及同步过审的代码与只读定案。

## 1. 轮次与核心结论概览

- **`b5r48`**：`S16` 中文应用名、6 语言网页字体与日历通知授权跨重开保留实机验收通过；生成 `out/b5r48/hevc10.mp4`。
- **`b5r49b`**：`S15` 三份偏好与通知 plist 跨开机字节级一致通过；定位 `M1` HEVC 10-bit `min=7` 越界 `IRIS_DPB_POOL_COUNT=6` 与 `S14` `uicache` 注销失败。
- **`b5r50`**：`S4`/`S14`（`trollstorehelper uninstall` 两次退出 `0` 与重装回归）、`G8`（`selector 18/78/88` `0` 未实现报错）、`G9`（`tl: c` 锁定 `1999..2002 us` 零 `9.3 ms` 跨步）与 `G15`（`/private/var/db/annibale-nircache/` 建全 `256` 桶）实机通过；`M1` 推进至 `port=2` `error=5`、`P14` GLINK 建链、`P21` `cwjoin` 捕获参数反序报错。

## 2. b5r48：S16 中文界面、字体与日历通知实机验收

- **环境与产物**：基于已提交 `TrollStore`（`1c2f6a9`）与 `hackios-xnu-userland`（`27dc30a`）重编用户态（日志 `out/b5r48/{trollstore,userland}-build.log`），配合 `12377-flipwd25` 执行。
- **中文应用名与字体**：`docs/progress/evidence/k90auto/kernel-12377-flipwd25-b5r48/run/tour-sheet.png` 显示主屏系统应用全部为中文标签，`.GlobalPreferences.plist` 实测 `AppleLocale = 'zh_CN'`、`AppleLanguages = ['zh-Hans-CN', 'zh-Hans', 'en-CN', 'en']`；`/private/var/db/fontconfig` 就绪、`fontservicesd`（PID `171`）在线，`out/b5r48/safari_clean.jpg` 确认 Safari 正常渲染简中、英、阿、法、俄、西文，无缺字方框。
- **通知权限保留**：`/System/Library/UserNotifications/Bundles/com.apple.mobilecal.bundle` 存在，`Library.plist` 与 `VersionedSectionInfo.plist` 均记录 `com.apple.mobilecal`；`out/b5r48/cal1.jpg` 与重开 `out/b5r48/cal2.jpg` 均未弹出通知授权弹窗，`docs/progress/evidence/k90auto/loader-recover-b5r48/returned.log` 中 `using a custom data provider` 为 `0`（`S16` 通过）。
- **`M1` 样本准备**：`/annibale/bin/video_decode_test` 确认 `iris_vt: registered SM8750 Iris VPU v3.5 decoders (avc1=0 hvc1=0 hev1=0)`，宿主生成 `out/b5r48/hevc10.mp4`（6.6K，`320x240`，`yuv420p10le`/`hvc1`）。

## 3. b5r49b：S15 跨开机一致性与 M1/S14 阻断定位

- **`S15` 跨开机字节级一致**：重启前后对比 `b5r48` 与 `b5r49b` 读回结果，`.GlobalPreferences.plist`（`370` B）、`Library.plist`（`28704` B）与 `VersionedSectionInfo.plist`（`28704` B）均 `exact_match=True`。
- **`M1` HEVC Main 10 `'x420'` 定位**：运行 `/annibale/bin/video_decode_test --require-hardware /private/var/tmp/hevc10.mp4` 创建硬件会话后，内核解析 10-bit `PSC` 为 `depth=0xa000a min=7`，随后 `decode ioctl` 返回 `errno=102`（`EOPNOTSUPP`，`sample=1 status=-12910`），VPU 正常关闭并断电。定因为 `annibale_iris_private.h:277,279` 固定 `IRIS_DPB_POOL_COUNT = 6u`（`IRIS_RAW_POOL_MAX = 6u`），使 `annibale_iris_hfi.c:691,693` 在 `iris_reconfigure_p010()` 前以 `count (7) > 6` 拒收。
- **`S4`/`S14` 卸载回归定位**：`install-ipa.py` 成功安装 `com.annibale.s14test`（`MCMAppContainer` 位于 `/private/var/containers/Bundle/Application/.../TestApp.app`），`trollstorehelper list` 在案；随后执行 `trollstorehelper uninstall com.annibale.s14test` 返回 `1`（`Error: Unable to register /var/containers/...`、`[uninstallApp] failed to unregister /var/containers/...`），系统应用与 `TrollStore.app` 未受影响。
- **稳定性**：`docs/progress/evidence/k90auto/loader-recover-b5r49b/returned.log` 全零 `gpu_fault`/`submissions closed`/`apfs: write`/`ufshc`，并干净退回空闲 `xnuloader`。

## 4. b5r50（flipwd26）：S4/S14、G8、G9、G15 实机验收与 M1/P14/P21 推进

- **环境与稳定性**：`xnu12377-flipwd26.bin`（`21073616` B，sha256 `3c2183a398dd13340eeec726d5b20f084f7cecc721cccd9f75c32008eee1bc3b`）+ `libannibaleair.dylib`（`14422240` B，sha256 `3d7cec624b4ac2b12e3f094705860428e395552c6ea24661ffe268df59dc77e6`）+ 重编用户态，`86` 份日志（`57,308` 唯一行）全零 `gpu_fault`/`submissions closed`/`smmu fault`/`apfs: write`/`ufshc`，退回空闲 `xnuloader`。
- **`S4` / `S14` 卸载与重装回归全过**：`/annibale/bin/trollstorehelper uninstall com.annibale.s14test` 退出 `0`（日志 `preserving shared/system group ...`），`list` 清零且系统与已有应用完好；重装 `out/b5r49/TestApp.ipa` 成功并再次 `uninstall` 退出 `0`。
- **`G8` / `G9` / `G15` 实机验收通过**：`selector 18/78/88 not implemented` 为 `0` 且 12 步交互通过（`rc=0`）；`annibale_goodix` `tl: c` 采样间隔锁定 `1999..2002 us`（稳定 `500 Hz` 覆盖 `240 Hz`、零 `9.3 ms` 跨步）；`/private/var/db/annibale-nircache/e557fa46-ef99-3b23-9c9e-6779aaeb0e8f/` 建全 256 个桶目录（`out/b5r50/nircache_subdirs.txt` `259` 行）。
- **`M1` / `P14` / `P21` 进展**：`M1` 通过 `min=7` 动态分配（`RAW published sid=1 ports=0x6 dpb=7 frame=303104 raw=7`）并停在固件 `port=2` `id=48` `error=5`；`P14` `fastrpcglink-apps-dsp` 建链（`intents=8x1024B`）；`P21` `cwjoin` 打印 `scan reply 0x0 err 0x10185c000`、`mwxjoin` 在 `the link, 1` 后 30s 超时 `0xfffff0bf`、`leave` 后 `CopyCurrentNetwork -> -3903`（三项已在批 17 `#640`/`#643` 完成定因与修复）。

## 5. 批 16 已合入过审的代码清单

- **`G30` 阶段 2（`#556`/`#559`/`#586`/`#591`）**：实现由 `gpu_recover=1`（默认 `0`）门控的 `annibale_gpu_recover()`，将 `adreno8_bo_stop()` 移出 `annibale_gpu_report()`，支持 `SMMU_CB_FSR`/CM3/软门闩/`context_slots[]` 复位与 `fence` 单调恢复；`test-adreno8-recover.py`、15 套关联单测与 `xnu26` `11/11` `clang` 编译检查通过。
- **`P14` 阶段 2 与基带测试样本（`#574`/`#579`）**：在 `annibale_adsp_fastrpc*.inc` 实现 `compute-cb@2` SMMU S1 bypass、`12 MiB` `adsp_mem_heap`、`fastrpcglink-apps-dsp` 4 KiB 分片重组、`INIT_CREATE_STATIC("sensorspd")` 与 `apps_std` 反向 RPC，并补齐 `test-annibale-modem-loader.py` `TLV 0x10` `14 B` `app_info`；3 套 ASan+UBSan 单测通过，`annibale_adsp.o` 单编零告警。
- **图形与显示（`#543`/`#546`/`#547`/`#548`/`#557`/`#559`/`#564`/`#566`/`#572`/`#575`）**：完成 `S6` 格式 94（`'l10r'` + `l10r_to_bgra()`）、`G6` ObjC `dlsym` 与在途 CB 守卫、`G8` IOMFB selector `18`/`78`/`88`、`G31` `ANNIBALE_G31_TRACE=1` 探针、`M5` 256 槽 `rw_surface_writes` 等待淘汰与边界单测、`G9` Goodix `2000/8000 us` 绝对截止时间两档轮询及 `27/27` 宿主单测同步通过。
- **冷启动缓存、材质回归、Wi-Fi 与发版合规（`#567`/`#570`/`#586`/`#591`/`#553`/`#555`/`#581`/`#583`/`#588`/`#590`/`#574`）**：落地 `/private/var/db/annibale-nircache/` 阶段 1（`air_metal_nircache.inc` 无锁原子读写 + `build-air.py` 91 文件 + `test-air-nircache.py`）、`material_regress` 18 项（16 材质 + 2 `G3`）双端对比、`build-release.py` `THIRD_PARTY_PROVENANCE`（`3/3`）、`a80211_test` `wifid`/keychain 权限修复，并确认 `b5r47` `Speaker "f\t,e#0e ("` 来自日志 7-bit 字符掩码（`'扬声器' & 0x7f`）。

## 6. 批 16 只读定案与归档结论

- **本轮闭环与边界归档项**：`S16`（`b5r48` 实机验收）、`S15`（`b5r49b` 字节一致读回）、`S13`（5 轮完整系统盘 0 崩溃/0 `SIGTRAP`，`#606`）、`M9`（`xnuloader` 0 次 `exit_boot_services` 与同步/终态门闩，`#600`）、`P15`（高通 QSEE TA 与 Apple SEP 硬件信任链外部边界，`#597`）、`P24`（`b5r27` + 4 轮 `AttentionAwareness` `16..46 ms` 零超时，`#609`）。
- **只读定案待办更新**：同步 `ENG-02`（`test-ir3-output-contracts.py` 本地实跑 `0018` `failures=0` 及 13 项外部源清单）、`ENG-07`/`ENG-11`（目标 Mesa `26.3.1`）/`ENG-12`（iOS 27 5 类 ABI 增量）/`ENG-13`/`ENG-14`、`G2`/`G10`/`G11`/`G12`/`G27`、`P2`/`P8`/`P10`/`P11`/`P12`/`P16`/`P17`/`P18`/`P19`、`M6`（14 个 H18-only E5 包与 `V57` 开关）与 `S17`（`CS_DEBUGGED` JIT 边界）。
