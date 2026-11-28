# 2026-11-28 批 27 天气详情渲染修复、BO 缓存复用与搜城延迟定位（b5r83）

本记录汇总批 27（`12377-b27` / `b5r83`）三条并行的工作成果与实测结论：修复 `air_metal_render_create.inc` 误删局部变量写入导致的天气详情页与 10 日温标条全黑、合并 Mesa `0032` 与内核 `AnnibaleGPUMemory.inc` 池保护以恢复详情页滚动帧率，以及通过零重启 `oslog` 拆解新城市天气查询链路延迟。`b5r83` 全程零 `panic(`、`gpu_fault`、`submissions closed`、`smmu fault` 与 `No system apps remain`，设备健康留在 iOS 运行态（`running-held`）。

## 1. 线 1：天气详情页、10 日温标条与 N3Oc3mtc4nlnlnl 全黑根因修复

- **根因定位**：`hackios-xnu-userland/tools/mesa/air/air_metal_render_create.inc` 中 `fragment_writes_depth()` 与 `drop_frag_depth_stores()` 只判断 `d->var->data.location == FRAG_RESULT_DEPTH`，漏检 `d->var->data.mode == nir_var_shader_out`。由于 `FRAG_RESULT_DEPTH = 0`，`nir_lower_goto_ifs` 为 `air.any` 分支生成的 `nir_var_function_temp` 局部变量 `path_conditional*` 默认 `location == 0`，在无深度附件管线（`!shape->depth_format`）下被误判并删除全部写入。
- **折叠失效路径与合成触发**：`ir3_nir_post_finalize` 中 `nir_lower_vars_to_ssa` 与 `nir_opt_dead_cf` 随即裁剪掉着色器主体，由 `nir_opt_undef` 折叠出 `NaN (0x7e00)`（`436`/`390`/`492` 输出纯黑）或空着色器（`118`）。同期实测 `Weather` 自身渲染的 `905×1827` `IOSurface` 已含完整蓝天渐变，`backboardd` 在无深度附件合成阶段触发上述误删，导致详情页全屏与第 2～4 行温标条发黑。
- **修复与宿主测试**：在 `air_metal_render_create.inc`（`1133` 行）抽出共用静态辅助函数 `is_frag_depth_store_deref()`，同时要求 `mode == nir_var_shader_out && location == FRAG_RESULT_DEPTH`；在 `air_metal_test_depth.inc`（`823` 行）、`air_metal_test.c`（`1086` 行）与 `tools/mesa/tests/test-air-frag-depth-store-filter.py`（`186` 行）补齐回归用例，重建 `libannibaleair.dylib`（`sha256` 前缀 `ab1fb81f`，`LC_UUID`：`4D509727-1DC8-3BED-A743-75AC83DEB933`）。
- **宿主与离线构建验证**：`test-air-frag-depth-store-filter.py`、`test-air-cache-key.py`（`424` 项）、`test-air-cache-store.py` 与 `test-air-identity.py`（`5/5`）全部通过。
- **真机实测验证（`12377-b27` / `b5r83`）**：真机 `g32_live_diag n3oc` 5 组用例（`118`/`147`/`436`/`390`/`492`）全部 `4096/4096` 非黑通过，`render-report.txt` 显示 `draw-failed=0`、`command-buffer-failed=0`；`b5r83` 截图 `weather_cities.png`、`weather_detail.png` 与 `weather_detail_10day.png` 均完整呈现背景渐变、星空与 10 日温标条和空气质量地图（目录 `docs/progress/evidence/k90auto/kernel-12377-b27-b5r83/`）。

## 2. 线 2：天气详情页滚动卡顿与跨场景 GPU/BO 池复用优化

- **Mesa `0032` 与内核池保护改动**：`hackios-xnu-userland/tools/mesa/rebase-26/0032-fd-bo-cache-reuse-and-stats.patch`（`100` 行，同步更新 `tools/mesa/rebase-26/README.md`）修改 `freedreno_bo_cache.c`：将 `find_in_bucket()` 遇忙条目时的 `break` 改为 `continue` 以复用同桶更早空闲 BO，在 `__APPLE__` 下将 `cache_max_size` 提至 `128 MiB`、保留阈值放宽至 `<= 3s`，并在分配/过期/驱逐路径接入 `fd_bo_stats_note()` 区分 `bo_cache` 与 `ring_cache`。
- **内核大块保护改动**：`hackios-xnu-kernel/xnu/files/iokit/Kernel/AnnibaleGPUMemory.inc`（`872` 行）将 `GPU_KEPT_BYTES` 从 `160 MiB` 提至 `256 MiB`，在 `keep()` 字节上限压力下优先回收超 `gGPUKeptTarget` 档位及 `0..2` 小/中档位以保护 `class 3`（`>= 8 MiB`）。
- **宿主测试与 XNU 编译**：`test-fd-bo-cache-reuse.py --mutations`（`474` 行，`ALL PASS` + `11` 项 0031/0032 变异）、`test-annibale-gpu-lifetime.py --mutations`（`890` 行，`38` 场景 4K/16K + `13` 变异）、`test-adreno8-bo.py`（`28` 场景 + `9` 变异）与 `test-annibale-gpu-dispatch.py`（含 `7` 变异）全过；XNU 编译生成 `xnu12377-b27.bin`（`21,110,528` B，`sha256` 前缀 `370d5a26`）。

| 指标（`weather-scroll-b5r83.log` 详情页滚动对照） | `b5r82` 基线 | `b5r83` 实测 |
|---|---|---|
| `fd bo new slow` | 单帧 `6` 次共 `50.41 ms` | `0` 次 |
| `fd bo stats[38]`（`backboardd`） | 未接入（`bo_hit=0`） | 每 5s 窗 `4080 / 4808 / 6450` 命中，`evict=0` |
| `AnnibaleGPU` `>= 8 MiB` 冷分配 / `class 3` 池 / `evict_bytecap` | `23` 次 / 池空 `0` / `62` 次逐出 | `0` 次 / 池稳态保底 `11` / `0` 次逐出 |
| `backboardd` `0x42 kMsmGemNew` | `258.665 ms/4s`（`235` 次） | `9.435–9.585 ms/5s`（`38–68` 次） |
| `backboardd` `0xf1 IOConnectUnmapMemory64` | `398.380–466.785 ms` | `109.305–129.940 ms/5s`（`76–83` 次） |
| 滚动阶段帧率与最大帧间隔 `dt_max` | 最低阶段 `25 fps`（`dt_max=580.8 ms`） | `97.1–109.4 fps`（`dt_max=47.23 ms`） |

- **剩余稳态优化候选**：后续保留三项候选方向，分别为随 `v0.2.5` 升级 loader 后复验 `fb_dpu_scale=1`、评估 `adreno8_inflight` 深度，以及排查 `backboardd` `0xf1`（`IOConnectUnmapMemory64` 均值约 `2.8 ms`/次）CPU 解除映射耗时。

## 3. 线 3：新城市天气查询延迟拆分定位

- **零重启 `oslog` 采样归属**：`b5r83` 通过 `kern.exec_inject` 临时启用 `Weather`/`weatherd`/`geod`/`nsurlsessiond` 的 `libannibale-oslog.dylib` 采集 `weather-search-oslog-b5r83.log`（`19,245` 行，`line limit reached = 0`）。日志确认交互式搜城、地理编码、JWT Mescal 签名尝试与 CloudKit 兜底均由 `Weather.app` 进程内通过 `WeatherDaemon.framework` 发起（`Weather` `1,399` 条 `oslog`、`geod` `163` 条，`weatherd` 仅 `6` 条 `<APSConnection>` 清理日志，`nsurlsessiond` `0` 条）。
- **点选「武汉市」全链路毫秒拆解**：从触控点选（`1005284.7 ms`）到详情页首帧上屏（`1012562.4 ms`）总耗时 `7,277.7 ms`（`Weather` 内部加载计时 `6.579906 s`），各段如下：
  - 触控响应与收起键盘耗时约 `320 ms`；`geod` 两跳反地理编码经本地代理出口地址完成，第 1 跳复用连接耗时 `52 ms`，第 2 跳在独立 `NSURLSession` 新建连接耗时 `674 ms`（含建连与 TLS 握手 `548 ms`），随后本地 SQLite 缓存遍历未命中耗时约 `7 ms`。
  - **首要阻塞（占加载耗时 `64%`）**：主请求调用 `AMSFairPlayGetHardwareInfo` 固定返回 `-42184`（`AMSErrorDomain code=12`），导致 `AMSMescalFairPlay` 在 `< 1 ms` 内本地失败而未发包；`WeatherDaemon` `RequestRacing` 在不发包的情况下固定等待 `4,203.5 ms` 后才拉起第 2 路重试，于 `3 ms` 内再次以 `-42184` 失败并转入 CloudKit 兜底。
  - **兜底拉取与首帧渲染**：`CKFetchRecordsOperation`（`com.apple.weather.fallback`）拉取耗时 `1,601.3 ms`（期间与后台 `ath12k` 3 信道扫描 `503 ms` 重叠），最后本地读取 `CKAsset` 缓存与构建 `VFXScene` 上屏共耗时 `347 ms`。
- **协议栈核对与技术边界**：全程 DNS 耗时 `0–11 ms`、TCP 建连 `3–7 ms`，不存在 IPv6 AAAA 阻塞或 HTTP/3 QUIC 回退；`-42184` 源于 [FairPlay 与 App Store 可行性研究](../analysis/2026-11-27-fairplay-appstore-feasibility.md) 已记录的硬件密钥根与 `FairPlayIOKit` 缺失边界，不适合通过伪造签名接口绕过。
