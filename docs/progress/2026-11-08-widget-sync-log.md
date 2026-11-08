# 2026-11-08 组件 sync draw 与首次黑化关联

本轮在 dump-AIR 候选上只增加 `REDWOOD_SYNC_LOG=1`，保留同步 draw、缩略图和 AIR 设置。boot SHA-256 为 `afe5659307ee6c4a22ed7407a17b250e3756fe4cb9801c4ebf987731b35db0c4`，没有重编内核或修改生产 Metal/AIR 源码。

## 1. 真机状态

- 首次解锁命令退出码为 0，但 `locked_after=1`，截图仍是锁屏。
- 同一轮再次解锁后 `locked_after=0`，主屏截图确认 Weather 与 Calendar 大组件为黑底。
- 下拉控制中心并返回后，黑底仍然可见。
- 设备最后保持 `running 0 0`，启动卷状态为 `ready 400000 400000 300000000`。

原始日志与截图位于本地忽略目录 `out/widget-render-1108/widget-trace/sync-log-candidate/device-run/run/`。

## 2. 首个保留窗口内的黑化 draw

对 `unlock-retry-home.log` 的缩略图逐像素比较，输入副本与解码结果保存在 `device-run/unlock-thumb-analysis/`。每个附件取得 16×16 采样，以下计数只代表采样像素。

| commit / work | pre0 → out0 结果 | pipeline | scissor |
|---|---|---|---|
| `1338 / 66` | 21 个像素由非零 RGB 变为 RGB 0，attachment 1 不变 | `0x115d9dc00` | `635,270 493x493` |
| `1338 / 70` | 两个附件均无采样变化 | `0x112340000` | `635,270 493x493` |
| `1338 / 73` | 一个像素由 RGB 0 变为非零 RGB | `0x110b0c000` | `635,270 493x493` |

work 66 的 draw 使用 6 vertices、10 textures 和 8 buffers，记录于 `unlock-retry-home.log:7597`。同一 handle 的创建行位于 `unlock-retry-home.log:7462`，实际 fragment 为 `TimgBscnA2Xhfsn_IsrcN3Oc3mtc4nlnlnl`，vertex 为 `VfxU10Xh`。

这份保留窗口从 commit 1338 的 work 66 开始，work 66 是窗口内首个产生新黑像素的 draw。更早日志没有完整保留，因此它还不能替代整次启动的首次黑化位置。

## 3. Tbds 关联的适用范围

当前 Calendar 区域的 work 73 使用 `TbdsA2Xhfes_Isup_IsrcM1`，完整 AIR 为 9104 字节，SHA-256 为 `307d36082f4ab944125d4faac3ea5d98567d9452d6fc02caf75f2572fa178ae9`。该 pipeline 在解锁前也执行过全屏 draw，见 `unlock-retry-home.log:3924` 的 commit 1326 / work 50。

Weather 区域的 commit 1338 / work 57 使用另一个 Tbds pipeline `0x1126c8e00`，创建行位于 `unlock-retry-home.log:7266`。这些记录建立了当前区域、draw、pipeline 和 AIR 的对应关系，但像素比较已排除把 Tbds 或 work 73 直接当成本窗口黑化起点的做法。

本轮 AIR 过滤值仍为 `Tbds`，没有取得 work 66 对应的 `TimgBscn…` 模块。历史 `commit 863 / work 70` 的 54-vertex、446×446 签名在本轮没有出现，不能跨启动按 work 序号或 fragment 名称归并。

## 4. 后续密集采集

后续 dense 轮保留了正常到黑底的完整切换，实际 fragment 为 `TmuaBscnA2Xhfsn_IsrcN3Oc3mtc4nlnlnl_Isqr`，目标 AIR 候选已构建，见[解锁转场密集采集](2026-11-08-widget-dense-transition.md)。
