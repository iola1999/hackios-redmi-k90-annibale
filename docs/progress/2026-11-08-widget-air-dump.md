# 2026-11-08 组件特化 AIR 采集与 draw 关联

本轮在 `79e8f90b546eb4bb2a5d4d9dcf52b8fff0eef8d9284dc16bbd2663f5106e27e7` 对应的 dump-AIR 候选上采集 Calendar 黑底 draw 的实际 fragment。候选只修改 `/lib/libwidgettrace.dylib`，内核、Metal、AIR、cmdline 和其他辅助盘文件保持 coldstart 候选内容。

## 1. 启动与主屏验收

- 临时 boot 成功，loader 为 `running 0 0`，启动卷状态为 `ready 400000 400000 300000000`。
- 解锁 rwsh 退出码为 0，耗时 6122 毫秒，日志包含 `locked_after=0`。
- 首次 `after-unlock.png` 仍是锁屏封面，未据此确认主屏。
- 后续 `after-home-wait.png` 和 `home-air-correlation.png` 显示完整主屏，Weather 与 Calendar 大组件保持黑底。
- 设备保持运行，本轮未在启动后发送 `oem stop`。

原始证据位于本地忽略目录 `out/widget-render-1108/widget-trace/dump-air-candidate/device-run/run/`，汇总见其中的 `result.json`。

## 2. 特化 AIR 与真实 decode

本轮取得一份完整模块：

| 项目 | 结果 |
|---|---|
| fragment | `TbdsA2Xhfes_Isup_IsrcM1` |
| vertex | `VfxU11Xh` |
| 本次启动 pipeline handle | `0x113cd4000` |
| AIR 长度 | 9104 字节 |
| AIR SHA-256 | `307d36082f4ab944125d4faac3ea5d98567d9452d6fc02caf75f2572fa178ae9` |
| pipeline 创建记录 | `widget-final.log:9863` |
| AIR 记录 | `widget-final.log:9666-9861` |

现有 `air2nir-host` 对该模块解码成功，stderr 为空。NIR 为 34364 字节，SHA-256 为 `4b4cd524468807ee897ae60d48837d5ce4ea1d16241309a7173804d5c8809c02`。

NIR 包含 `uses_fbfetch_output: true`，分别读取 coherent `FRAG_RESULT_DATA0` 和 `FRAG_RESULT_DATA1`，两者都参与后续计算。此前单附件 `dest_0` pass-through 探针没有覆盖 `DATA1` 或多输出读取。

## 3. 尚未建立的关联

保留日志没有 `0x113cd4000` 的实际 draw，也没有符合 `54 vertices / 10 textures / 8 buffers / scissor 632,369 446x446` 的当前启动 draw。相邻 `pipeline seen` 行使用其他 handle，不能用于确认该 pipeline 的附件数。

因此，本轮只建立「pipeline 创建行 → fragment 名 → 完整 AIR」的关联，尚未建立「Calendar 首个黑底 draw → 当前 pipeline」的关联。该模块不能直接认定为历史 `commit 863 / work 70` 的 fragment。

解锁后再次下拉控制中心并返回主屏，rwsh 退出码为 0，主屏截图仍显示黑底组件，但新日志仍没有 sync draw 文本。

## 4. 日志缺口与后续

源码 `redwoodmetal_diag.inc:329-335` 表明，逐 draw 文本只在 `REDWOOD_SYNC_LOG` 开启或当前 commit 仍有逐 draw 缩略图预算时输出。`REDWOOD_SYNC_DRAWS` 单独只保留同步等待；288 张缩略图用完后，后续重绘不再输出目标行。

后续 sync-log 轮已取得实际 draw，并在当前保留窗口内定位首个新黑采样，见[sync draw 与首次黑化关联](2026-11-08-widget-sync-log.md)。
