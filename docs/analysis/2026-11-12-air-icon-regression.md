# 新 AIR 下的桌面图标缺失（2026-11-12）

cospi-precise 与 CI 独立候选的数值探针通过，首次测试的桌面应用和 Dock 图标却缺失；同一 CI 候选的暖缓存复测中图标恢复，组件异常保留。当前没有定位到首个失败调用。通用显示任务继续核查实际 shader、绑定与绘制输出；相机、Iris 和音频由多媒体任务负责，设备操作仍由其唯一 device 成员执行。

## 1. 画面与缓存读数

原始轮次位于 `docs/progress/evidence/k90auto/`，共同前缀为 `kernel-12377-codex-1112-cd14-`。下表缓存数来自对应 `run/cmd-1.log` 的最后一条 SpringBoard 统计，只描述该进程累计命中与提交写入数。

| 轮次后缀 | 原图结果 | SpringBoard hits／stores | AIR UUID |
|---|---|---|---|
| `minmax-air` | 两张完整桌面中 15 个应用与 4 个 Dock 图标可见，组件仍有浅色块／条 | `6 / 58` | `A1E7F4D6-1D95-3783-8602-07873F121FC0` |
| `heap-metal` | 应用与 Dock 图标可见，组件内容异常 | `64 / 0` | 同 minmax |
| `r16-metal` | 应用与 Dock 图标可见，组件内容异常 | `64 / 0` | 同 minmax |
| `cospi-precise` | 三张稳定截图缺少应用、Dock 图标和组件内容，壁纸、标签与时钟指针可见 | `9 / 55` | `34285D8F-7C0C-3D04-A11A-C14F4B98121B` |
| `ci-stitch` | 两张稳定截图缺少应用、Dock 图标和组件内容 | `10 / 54` | `28000AF1-1B24-3E65-98EE-B56E75DDF140` |
| `ci-warm` | 两张完整桌面中 15 个应用与 4 个 Dock 图标可见，组件内容异常 | `64 / 0` | 同 CI |

minmax 的 `tour.json` 只列四张控制中心截图，轮内还保存了 `shot-00963.raw`、`shot-01291.raw`。本批将这两张按原尺寸解码并实际打开，确认图标可见。已有分析仅按 tour 索引判断截图覆盖范围，遗漏了这两张；本专题以原图复核结果为准。

minmax 的编译写入与可见图标限制了「大量缓存未命中必然导致缺图标」的推断。计数尚未关联具体图标 shader，同轮命中也可能来自其他进程刚写入的缓存。G1 组件内容异常与本次图标缺失分别验收。

## 2. 构建和实际加载范围

| 冻结 AIR | SHA256 |
|---|---|
| minmax 与 CI 重建 baseline | `aa0dc8420a310545ec6cbe98377d66223f1c57f3399ca94648aaab056e449800` |
| cospi-precise | `154d0a130833a6ee31d36a2068ed5647962b3e583ca4d4169887e3fb23fc81f9` |
| CI candidate | `345ab358d36205ce673df1d86a50767f98117a454094717fb4a5efe0fc6f46b0` |

四份冻结构建的编译命令逐字节相同，23 个链接静态库中 22 个相同，仅 `libair.a` 改变。cospi 改动 `air_intrinsics.c.o`，CI 改动 `air_to_nir.c.o` 与 `air_metal.c.o`，两类候选没有共同变化的编译单元。CI 重建 baseline 与原 minmax dylib 逐字节相同；尚未发现共同的后端源码或编译参数变化。

五轮 manifest 中 kernel、cmdline、resident、CPU／GPU 参数相同，辅助盘随候选变化。本批没有逐项比较五份 APFS 的全部文件。进程日志均报告 Adreno 830 与各自 AIR UUID；产物 SHA 来自冻结文件，进程映像尚未逐字节回读。

heap 与 cospi 加载相同 Metal bundle UUID `1978DE94-43C6-380F-A5D9-42153B8E9370`。CI 的 Metal bundle 另含 stitched compute 修改；候选之间的用户态差异需继续按来源区分。

## 3. 缓存契约与已有检查

`0015-ir3-disk-cache-darwin-uuid.patch` 使用加载 AIR 的 Mach-O UUID 生成默认 `/private/var/db/annibale-ir3cache/<UUID>` 目录，并将 UUID 纳入 driver key。指定 `MESA_SHADER_CACHE_DIR` 仍会保留 UUID 对缓存键的影响。shader key 还包含序列化 NIR、波宽、选项、stream output、variant key 与 binning 标记。

IR3 命中缓存后恢复已编译 variant；未命中则执行 NIR post-finalize 和编译。AIR 到 NIR 的前端处理及 shader key 生成仍发生于缓存查询之前。stores 统计 `disk_cache_put` 提交，无法单凭计数确认异步写盘完成。

已有十个可直接解析的 RenderBox 入口在三份前端中生成相同 NIR；相应 A830 variant 的生产 store／retrieve 内存往返保持字段、机器码和 const_state。该检查使用默认零常量，未覆盖运行期专化模块、文件缓存 I/O 和 GPU 执行，本批没有重复运行。

本批扫描五轮分别 57、62、59、60、61 份已保存的命令、快照与收尾日志，每份小于 2 MB。cospi 与 CI 未找到明确归属 SpringBoard、backboardd 或 iconservicesagent 的编译拒绝；对应已记录管线创建成功。日志可能被环形覆盖，两轮也没有实际专化 AIR 导出，当前材料无法关联缺失图标与具体 draw 输入。

原有专化 AIR 缓存 `/private/var/db/annibale-aircache` 使用 library 身份、函数名、专化名和常量；当前路径仅在原生专化失败后读取。它与 IR3 缓存分别记录，尚无该路径参与图标缺失的结果。

## 4. CI 暖缓存复测与因果边界

两轮 manifest 逐字节相同，当前 kernel、root、resident 和 payload 文件哈希均符合记录，打包环境一致。22 项探针顺序相同，仅线程查询的进程号不同；两次桌面采集均没有触摸动作。root SHA256 为 `c987b2ef93de120a6480f9110c4e367cbfb818bdb4c56ac44c0dcd5bf2e7227b`，payload 为 `c9ca366f332b2fe0ea9e0cf6a269915911589d99a6a478e290daf7946607d1c3`。

暖轮的两张原尺寸桌面图已实际打开，图标恢复。启动日志中的 SpringBoard 为 `64 hits / 0 stores`，后续快照达到 `118 / 10`。backboardd 40 的已保存累计计数由 `29 / 3` 增至 `48 / 16`，两条属于同一累计序列。不能据启动阶段的零 stores 推断整轮没有编译。

| 已记录条件 | `ci-stitch` | `ci-warm` |
|---|---|---|
| `oem run` 至首张桌面截图请求 | 91.353 秒 | 88.079 秒 |
| `oem run` 至第二张桌面截图请求 | 119.951 秒 | 113.290 秒 |
| `runtime-settle` 查询的帧号 | 42 | 0 |
| 探针前后帧号 | 145 → 148 | 446 → 857 |

暖轮完成 22 项步骤和两次桌面采集，CI 探针的 128 分量通过；CPU 采样峰值为 72.9 °C，温度记录存在 6 处覆盖间隔。收尾确认 `product=xnuloader`、`result=idle`、`ramdisk-state=idle 0 0 0`，LK A 槽重试数为 7。记录位于该轮根目录的 `completion-summary.json`。

`runtime-settle` 只查询帧号，没有统一的桌面就绪判据。两轮之间运行过 R16 alias 和 Iris 候选，持久化用户数据也没有完整快照或重置校验。当前结果支持继续检查首次编译、首次使用与缓存恢复差异，尚不能将图标恢复单独归因于缓存。

## 5. 下一次诊断的范围与缺口

冷、暖启动日志都记录 `plane_image_stretch_vertex / fdea3ea2ca8fmha4` 进入 `trace commit 7`，可以将它作为首个有名称的候选。日志中的 `194×194`、format `90` buffer texture 尚未关联到该 draw，暂不按这组尺寸过滤。

现有入口的覆盖范围如下：

- `ANNIBALE_DUMP_AIR` 每进程最多导出 16 个名字，每名一次，没有累计字节或时间上限。同名变体会被去重。descriptor 中的 specialization proxy 可能提供未特化模块；stitched proxy 的 `bitcodeData` 只转发 output node，未导出完整 graph、节点模块及参数依赖。当前输出不足以重放完整管线。
- `ANNIBALE_THUMBS` 与 `ANNIBALE_THUMB_DRAWS`／`MATCH` 可以筛选绘制前后的附件和输入纹理。RGBA 各保留高 6 位，可区分透明 alpha 与颜色；`ANNIBALE_SYNC_DRAWS` 仍同步该进程的每条 draw，`THUMB_MATCH` 不限制同步范围。同步和读回会影响时序。
- 缩略图 header 只有 `rwa_texture` 指针，layer 探针已有 IOSurface ID。需要在 draw 侧取得 surface ID、plane、buffer offset／stride 和 parent texture，才能关联两侧；CGImage 上传来源仍需另外核对。
- `audit-pass` 可提供附件尺寸、格式和 load／store；其 pure-black 检查只看 RGB，单独使用无法判断透明图标。

下一步先审查只同步匹配 draw 的有界诊断，再决定实际编译输入的最小导出范围。导出位置应在专化与 linked 输入确定之后，记录实际 entry、模块长度及哈希、常量和图结构；超限或缺模块需明确标记不完整。宿主 runner 的轮次时限无法打断进程内已经阻塞的输出或 GPU 等待。

输入完整后才执行三份冻结前端的离线对照：固定 linked function、管线 shape 和 variant key，关闭磁盘缓存，比较接口、NIR、IR3 机器码及 binning 变体。验收按 PID、pipeline、commit／work 分组核对模块与缩略图，`airdump.py`、`thumbs.py` 返回 0 仍需检查缺项。当前普通系统 metallib 的默认常量检查无法覆盖完整 draw。

共享 AIR／Metal 修改按文件协调。相机的 `air_texture.inc` 与 `AnnibaleMetalStitchedFunction` 当前由多媒体任务维护；通用显示候选使用独立构建目录和冻结工具，交唯一 device 串行执行。

## 6. 本地复核资料

原始报告、逐文件清单与日志摘录保存在 Git 忽略的 `docs/analysis/local/s5-foreground-1112/air-icons/` 和 `air-icons-build/`。minmax 两张原图 SHA256 分别为 `26a52a8c1bec87cf9fb3199165924c89429f06d042057591a0449b48b29e7fe7`、`ccfa9ce57323a472c7e041325f16bfd06904e798d96f35e5ceef42d3a1a57692`。

既有构建与离线检查集中在 `hackios-xnu-kernel/out/codex-1112-cospi-visual/`、`out/codex-1112-ci-stitch/`；数值探针和设备轮次结论见[多媒体验证](2026-11-11-multimedia-validation.md)。本批未修改生产渲染代码，首个失败契约仍待定位。
