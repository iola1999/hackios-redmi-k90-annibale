# ir3 磁盘缓存跨开机实测与根因修复

[架构审查](2026-11-08-architecture-review.md) §7.1 把「管线与着色器缓存跨开机生效」列为 P0，判据是第二次开机 backboardd 建管线的次数接近 0。本文记录 2026-11-09 的核对、跨开机黑屏与跨进程未命中根因定位、修复及真机连续两次开机验证结果。

## 1. 现有两层缓存

| 缓存 | 位置 | 内容 | 现状 |
|---|---|---|---|
| AIR 缓存 | `/private/var/db/annibale-aircache` | 驱动拼接函数后的 AIR 位码（`annibalemetal_stitch.inc`） | 真机上有 598 个文件，共 4.4 MB，跨开机保留 |
| ir3 磁盘缓存 | `/private/var/db/annibale-ir3cache/<库 UUID>/mesa_shader_cache` | Mesa ir3 编好的着色器变体（补丁 `0015-ir3-disk-cache-darwin-uuid`） | 已启用跨进程共享与跨开机复用（内核 `0e0f19bb`、用户态 `e052bd4`） |

驱动的进程内管线缓存（`annibalemetal_pipecache.inc`）只在同一进程里复用，不跨开机。

## 2. 初始排查：缓存为空与首次开启后的现象

- `tools/k90auto/setup-mesa-arm64e.py` 在 11-06 改为 `-Dshader-cache=enabled`，但共享构建树 `out/ios26-resume/mesa-arm64e` 建于 10-26，配置保持在 `disabled`，此后没有重新配置。关闭时 Mesa 的 `disk_cache_create()` 编译为空实现并返回 `NULL`，补丁 0015 仍会建出按库 UUID 命名的目录，因此目录存在但没有内容。
- 基线读数：三次开机的启动日志窗口里，backboardd 每次有 15～28 次 1 ms 以上的建管线，合计 53～83 ms；iconservicesagent 38～60 次，合计 137～292 ms；MercuryPosterExtension 8～16 次，合计 92～185 ms。跨开机没有复用。
- 首次打开 `-Dshader-cache=enabled` 连续开机两次（`out/s1109/shadercache/sc1.log`、`sc2.log`）：
  1. 第一次开机（`sc1.log`）：桌面正常，缓存目录下写入 92 个子目录、115 个条目，属主 `uid 501`，目录权限 `0700`。
  2. 第二次开机（`sc2.log`）：backboardd 1 ms 以上的建管线从 75 次降到 4 次（`175 ms` → `27 ms`），但 iconservicesagent 仍有 46 次慢编译（`282 ms`），且解锁后截图全黑。

## 3. 根因定位

核对 `struct ir3_shader_variant` 序列化与 `sc1.log`／`sc2.log` 时间线后，定位到三处独立原因：

1. **`ir3_shader_variant` 序列化完整性核对**：检查 `ir3_shader.h`、`ir3_disk_cache.c`、`ir3_gallium.c`、`fd6_program.cc` 与 `fd6_compute.cc`。`VARIANT_CACHE_START`（`offsetof(struct ir3_shader_variant, info)`）之后的全部变体字段及 `v->bin`、`v->const_state`、`v->imm_state` 均完整序列化并在命中时恢复；`VARIANT_CACHE_START` 之前的链表指针、着色器 stage 与 `bo` 由 `alloc_variant()` 和 `upload_shader_variant()` 重新初始化，不存在未序列化的机器码或寄存器状态。
2. **`sc2.log` 第二次开机黑屏的真实原因**：`sc2.log` 中 `SpringBoard` 在 `06:28:32.849` 进入锁屏，满 30 秒无触摸后锁屏自动熄屏定时器在 `06:29:06.848` 触发（`reason: SB + pocketTouches + backlight-off; displayState: off; digitizerEnabled: NO`）。

   - 200 ms 后（`06:29:07.035`）宿主发送 `com.annibale.unlock`，`inject_sb26.c` 的 `unlock_once()` 在屏幕处于 `backlight-off` 状态下直接调用 `-[SBLockScreenManager unlockUIFromSource:withOptions:]`，返回 `answer=0 locked_after=1` 解锁失败。
   - `06:29:08.272` `backboardd` 清空显示层（`surfaces in layers 0x0 now (0x1 before)`）并关闭触摸，导致后续画面全黑。
3. **`iconservicesagent` 跨进程缓存未命中的原因**：Mesa `src/util/disk_cache_os.c` 默认以 `mkdir(path, 0700)` 创建 `mesa_shader_cache` 及两字符子目录，并以 `open(..., O_RDWR, 0644)` 创建 `index` 与 `marker`。`backboardd`（`uid 501`）率先建出 `0700` 目录后，`iconservicesagent`（`uid 254`，`_iconservices`）访问该目录和 `O_RDWR` 打开 `index` 时因 `EACCES` 失败，`cache->path_init_failed` 置 `true`，导致 `iconservicesagent` 全程无法读写磁盘缓存。

## 4. 修复措施

1. **跨 UID 共享缓存目录与文件权限（`0015-ir3-disk-cache-darwin-uuid.patch`）**：在 `src/util/disk_cache_os.c` 与 `src/freedreno/ir3/ir3_disk_cache.c` 的 `#ifdef __APPLE__` 分支中，缓存目录创建使用 `0777` 并显式 `chmod(path, 0777)`，缓存文件（`index`、`marker`、`<key>.tmp`）使用 `0666` 并显式 `fchmod(fd, 0666)`，使 `root`（`uid 0`）、`mobile`（`uid 501`）与 `_iconservices`（`uid 254`）共享同一缓存目录。同时在 `ir3_disk_cache.c` 增加 `ir3_cache_note()` 里程碑计数日志（`ir3 cache[<proc> <pid>]: <hits> hits, <stores> stores`）。
2. **`mmap(MAP_SHARED)` 脏页关机落盘（`ramfs_disk.inc`）**：Mesa 的 `index` 文件通过 `mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0)` 更新。在 `ramfs_disk_flush_all()` 中遍历所有 `rn_mapped_write` 节点并调用 `ubc_msync(vp, 0, ubc_getsize(vp), NULL, UBC_PUSHDIRTY | UBC_SYNC)`，确保软重启或退回 loader 前 `index` 脏页写回 `ANNFS001`。
3. **解锁前唤醒屏幕（`inject_sb26.c`）**：`unlock_once()` 调用 `-[SBLockScreenManager unlockUIFromSource:withOptions:]` 前先调用 `-[SBBacklightController turnOnScreenFullyWithBacklightSource:1]`，并在 `com.annibale.unlock` 通知回调中若首次仍处于锁定状态则 300 ms 后重试一次，避免恰好撞上 30 秒锁屏熄屏窗口时解锁失败。

## 5. 真机连续开机验证

使用启用 `-Dshader-cache=enabled` 的 `libannibaleair.dylib` 与修复后的内核／用户态打包 `boot-direct.img`（`22,546,432` 字节，SHA-256 `0468a427…`），在 K90 真机连续启动两轮（本地日志与截图保存在 `out/diag-2039/boot-opt1/`）：

| 进程 | 第一次开机（冷缓存建库，`boot1-final.log`） | 第二次开机（热缓存命中，`boot2-desktop.log`） | 第二次开机命中率 |
|---|---|---|---|
| `backboardd`（`uid 501`） | `31 hits, 161 stores`（`ir3 wait` 15 次） | `61 hits, 3 stores`（`ir3 wait` 3 次） | 95.3% |
| `iconservicesagent`（`uid 254`） | `97 hits, 159 stores` | `128 hits, 0 stores` | 100.0% |
| `MercuryPosterExtension`（`uid 501`） | `4 hits, 4 stores` | `8 hits, 0 stores` | 100.0% |

第二次开机解锁后桌面截图（`boot2-later.png`）确认主屏、Dock 与小组件全部正常彩色渲染，无黑屏或白块。`setup-mesa-arm64e.py` 与 `build-air.py` 默认保持 `-Dshader-cache=enabled`。
