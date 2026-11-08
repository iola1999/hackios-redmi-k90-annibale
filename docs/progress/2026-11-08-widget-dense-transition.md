# 2026-11-08 组件解锁转场密集采集与目标 AIR 候选

本轮复用 dump-AIR 候选，boot SHA-256 为 `79e8f90b546eb4bb2a5d4d9dcf52b8fff0eef8d9284dc16bbd2663f5106e27e7`。候选代码未改，主机在解锁转场期间连续保存了 675 份日志快照，覆盖正常画面到黑底的完整切换。

## 1. 首次完整黑化切换

区域缩略图比较在 `commit 1509 / work 48` 找到首个完整黑化 draw：

- `pre0` 的 18 个区域采样均为 RGB 234，`out0` 的 18 个采样均变为 RGB 0。
- attachment 1 的采样没有同步变化。
- draw 使用 54 vertices、10 textures、8 buffers，scissor 为 `634,306 476x476`。
- 本次启动的 pipeline handle 为 `0x1371edc00`，draw 记录位于 `dense-000041.log:10582`。
- 前一 work 47 的 `pre0/out0` 仍保持 RGB 234，后续 draw 保持黑底。

原始记录位于本地忽略目录 `out/widget-render-1108/widget-trace/dump-air-candidate/device-run-dense/run/`，汇总见 `first-black.json` 与 `thumb-black-candidates.json`。采集末尾主机脚本报 `NameError: attempts is not defined`，目标区间的快照与缩略图已完整保存。

## 2. 同 handle 的实际 fragment

`dense-000041.log:9752` 的创建行将 `0x1371edc00` 关联到：

- vertex：`VfxU11Xh`
- fragment：`TmuaBscnA2Xhfsn_IsrcN3Oc3mtc4nlnlnl_Isqr`

本轮 AIR 过滤值为 `Tbds`，没有取得这个 fragment 的完整 AIR。当前证据同时排除了按 Tbds 名称、其他启动的 work 序号或当前同步轮 work 66 替代本次黑化 draw 的做法。

## 3. 目标 AIR 候选

`tmua-air-candidate` 相对 sync-log 候选只把 `ANNIBALE_DUMP_AIR` 改为上述完整 fragment 名。其他 helper 记录、内核、Metal/AIR、同步 draw 和缩略图设置保持一致。

- boot：`out/widget-render-1108/widget-trace/tmua-air-candidate/boot-direct.img`
- boot SHA-256：`6b0ba5d33676ec2878c12099ee839ce3e5853c714844af9737595d9b00706a65`
- 严格签名、辅助盘逐记录比较和 `run.py --verify-only` 已通过。
- 下一轮需要取得同一 fragment 的完整 AIR，并用真实 `air2nir` decode 检查实际输入、输出与 framebuffer fetch。
- 候选尚未进行真机验证，当前没有生产渲染修复。
