# ir3 磁盘缓存跨开机实测

[架构审查](2026-11-08-architecture-review.md) §7.1 把「管线与着色器缓存跨开机生效」列为 P0，判据是第二次开机 backboardd 建管线的次数接近 0。本文记录 2026-11-09 的核对与真机实测，结论是 ir3 磁盘缓存继续关闭。

## 1. 现有两层缓存

| 缓存 | 位置 | 内容 | 现状 |
|---|---|---|---|
| AIR 缓存 | `/private/var/db/annibale-aircache` | 驱动拼接函数后的 AIR 位码（`annibalemetal_stitch.inc`） | 真机上有 598 个文件，共 4.4 MB，跨开机保留 |
| ir3 磁盘缓存 | `/private/var/db/annibale-ir3cache/<库 UUID>/` | Mesa ir3 编好的着色器变体（补丁 `0015-ir3-disk-cache-darwin-uuid`） | 只有一个空目录 |

驱动的进程内管线缓存（`annibalemetal_pipecache.inc`）只在同一进程里复用，不跨开机。

## 2. ir3 缓存为空的原因

- `tools/k90auto/setup-mesa-arm64e.py` 在 11-06 改为 `-Dshader-cache=enabled`，但上机用的共享构建树 `out/ios26-resume/mesa-arm64e` 建于 10-26，配置一直是 `disabled`，此后没有重新配置过。
- 关闭时 Mesa 的 `disk_cache_create()` 编译成空实现，返回 NULL。补丁 0015 仍会建出按库 UUID 命名的目录，所以目录存在但没有内容。
- 基线读数：三次开机的启动日志窗口里，backboardd 每次有 15～28 次 1 ms 以上的建管线，合计 53～83 ms；iconservicesagent 38～60 次，合计 137～292 ms；MercuryPosterExtension 8～16 次，合计 92～185 ms。跨开机没有复用。

## 3. 打开缓存的实测

只换 `libannibaleair.dylib`（`-Dshader-cache=enabled` 重新编译），内核与其余用户态不变，连续开机两次：

- 第一次开机：桌面正常。缓存目录下写入 92 个子目录、115 个条目，属主 uid 501，目录权限 0700。
- 第二次开机（第一次读缓存）：解锁后约 1 分钟内三次截图全黑。日志窗口里 backboardd 1 ms 以上的建管线从 75 次降到 4 次，两次窗口分别约 70 秒和 50 秒；驱动只打印 1 ms 以上的编译，命中缓存的快速编译看不到，所以这个数字不能直接当命中次数。
- 换回未开缓存的库，同样流程开到桌面。

黑屏和读缓存同时出现，是否由缓存读出的着色器变体造成，还没有单独验证。

## 4. 结论与下一步

- `setup-mesa-arm64e.py` 改回 `-Dshader-cache=disabled`，`test-shader-cache-m1.py` 的断言同步修改。共享构建树已改回关闭并重新编译，库与之前上机的版本逐字节一致。
- 用干净克隆按 11-06 以后的脚本构建的库会打开缓存，出过的 Release 需要核对。
- 要让缓存可用，先在主机上对比同一着色器「新编译」与「从缓存读出」的 `ir3_shader_variant`，找出本项目 ir3 与 fd6 补丁新增、但缓存没有序列化的状态。动手前先量一次建管线耗时里 AIR→NIR 与 ir3 后端各占多少，后端占比小的话，磁盘缓存的收益有限。
