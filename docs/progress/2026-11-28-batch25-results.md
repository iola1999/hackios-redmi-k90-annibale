# 2026-11-28 批 25 真机实测、VFX 参数缓冲反射与天气卡片渲染（b5r76～b5r82）

本记录汇总批 25（Parts 1–7）在 `hackios-xnu-userland`、`hackios-xnu-kernel` 合入的桌面相机图标延续验证、VFX 参数缓冲与 Metal 渲染反射实现、未使用及条件资源裁剪、宿主全量验证结果，以及衔接 `b5r75` 基线的七轮真机实测（`b5r76`～`b5r82`）。`b5r76`～`b5r82` 全程零 `panic(`、`gpu_fault`、`submissions closed`、`AnnibaleGPU client refused`、`smmu fault`、`backlight-off` 与 `No system apps remain`，`b5r82` 首次在城市列表卡片渲染出蓝天渐变、日光晕与光斑效果，设备健康留在 iOS 运行态（`running-held`）。

## 1. 基线与 b5r76～b5r82 真机实测递进

批 25 全部七轮真机测试沿用已验证内核 `12377-b24`（sha256 `fdd6a73b8b27d6a48d7f6024ba716c3f9b0127f78233f5858ad40720584b4143`），同步保留批 24 恢复的 `cycle.py` `FIXED_ARGS` `cam=5` 参数（`b5r75`～`b5r82` 首屏第 1 行第 4 格「相机」图标均正常，无回退）。`b5r76`～`b5r82` 实测递进如下：

| 轮次 | 核心改动与配置 | `draw-failed` / `cb-failed` | 关键阻断与实测结果 | 实测目录 |
|---|---|---|---|---|
| `b5r76` | `-constantDataAtIndex:` 真实字节偏移 + `G32` `fbuf2`/`fbuf4[0..20]` 扩展探针 | `0` / `0` | `-constantDataAtIndex:` 与 `argbuf` 报错为 `0`；`OSLOG="Weather"` 捕获 `191` 条 `Missing reflection in [RP]`；补齐 `fbuf2=0.000` 与 `fbuf4[0..20]` 读数 | `docs/progress/evidence/k90auto/kernel-12377-b24-b5r76/` |
| `b5r77` | `MTLRenderPipelineReflection` 全链路 + NIR Cache 补反射与顶点缓存深拷贝 | `0` / `0` | `Missing reflection in [RP]` 降至 `101`；`s022`～`s026` 累计 `1173` 条 `two members of the argument buffer global_constants_encoder` | `docs/progress/evidence/k90auto/kernel-12377-b24-b5r77/` |
| `b5r78` | `air_entry.inc` UAF 修复 + 607/607 语料结构/矩阵/纹理反射补齐 | `0` / `0` | `global_constants_encoder` 与 `Missing reflection in [RP]` 均清零；`Weather` 命中 `VFX/Metal+Extensions.swift:367: Fatal error: Unsupported dataType`（`SIGNAL 5`） | `docs/progress/evidence/k90auto/kernel-12377-b24-b5r78/` |
| `b5r79` | 间接纹理/指针反射、`setIsIndirectArgumentBuffer:`、`newArgumentEncoderWithBufferBinding:` 与稀疏 `id > 63` | `822` / `822` | `Unsupported dataType` 与 `Weather` 崩溃均清零；首通 `fragment_skybox_texture1d` + `composite`；暴露 `particle_quad_frag` `vrr_map`（`id 12`）未编码 `822` 次（`795 + 27`） | `docs/progress/evidence/k90auto/kernel-12377-b24-b5r79/` |
| `b5r80` | 未使用/条件 argbuf 成员追踪、`argbuf_member`/`check_bindings`/`bind_stage` 放行与 NIR Cache v2 字段 | `579` / `578` | `vrr_map` 报错清零（`822 -> 0`）；暴露 `particle_quad_vert reads buffer 13 and 7 buffers were bound`（Weather `578` + `cameracaptured` `1`） | `docs/progress/evidence/k90auto/kernel-12377-b24-b5r80/` |
| `b5r81` | `air.arg_unused`/`air.function_constant` 直接资源标记、`mark_unused_direct_resources()` 与格式标签 `v3` | `602` / `602` | `reads buffer 13` 清零，`check_bindings()` 通过；暴露 `yuv_key_for()` 未跳过 `r->unused` `shadowMap`（`id 23`）失败 `602` 次（`590 + 12`） | `docs/progress/evidence/k90auto/kernel-12377-b24-b5r81/` |
| `b5r82` | `yuv_key_for()`、`rgb2p_prepare_bindings()`、`argbuf_member()`、`rwa_module_textures()`、`build_vertex_state()` 跳过 `r->unused` | `0` / `0` | `18` 条 `Weather tl: mt` 共 `410 completed / 0 errors`（稳态 `draw 20–23 us of 448`）；`weather_cities.png` 萧山区 `17° 晴` 首次渲染蓝天渐变与日光晕光斑；详情页 `905×1967` 背景仍黑 | `docs/progress/evidence/k90auto/kernel-12377-b24-b5r82/` |

## 2. VFX 参数缓冲内联常量与完整 Metal 渲染反射实现

- **内联常量成员偏移与 scratch-ctx UAF 修复（Parts 1、3）**：用户态在 `nir_air.h`（`526` 行）新增 `struct air_argbuf_const_member` 与 `air_shader_info.argbuf_constants[]`（独立于 `resources[]`），在 `air_private.h`（`314` 行）记录 `air_argbuf.alignment`，由 `air_argbuf.inc`（`662` 行）按 `air.arg_type_align_size` 与嵌套字节偏移导出常量成员，并在 `air_metal.h`（`676` 行）定义 `RWA_ARGBUF_CONSTANT = 3` 与 `rwa_argbuf_member.{offset, size}`。
- **UAF 修复与驱动同步**：`air_entry.inc`（`701` 行）在释放临时上下文 `ctx` 前将 `info->argbuf_constants` 与各项 `.name` 复制到调用方 `mem_ctx`，消除 `global_constants_encoder` `id 0` 重复成员错判。内核用户态驱动同步 `annibalemetal.m`（`1130` 行）结构体布局，在 `annibalemetal_compute_argencoder.inc`（`1087` 行）重写 `-constantDataAtIndex:` 按 `(id, RWA_ARGBUF_CONSTANT)` 查表返回 `(char *)bytes + _offset + found->offset` 并校验缓冲区边界。
- **完整 `MTLRenderPipelineReflection` 全链路（Parts 2、3）**：`air_reflection.h`（`28` 行）与 `air_reflection.c`（`898` 行）提供 `air_stage_reflection()`、`air_module_reflect()` 与 `air_reflection_clone()`，统一由 `reflect_struct_from_md()` 解析 `air.struct_type_info`（含嵌套结构体、`sub_id`、`elem_count > 0` 数组包装、重复字段检查）、`packed_*` 向量、矩阵包装、`short`/`ushort`/`char`/`uchar` 纹理、11 项阶段内建、`MTLBindingType 24..27`、`void*` 无类型缓冲及 `air.function_constant` 条件绑定。
- **反射缓存保活与 Metal 桥接**：`air_metal_reflection.h`（`113` 行，双仓逐字节一致）定义 `struct rwa_render_reflection` 与 `rwa_render_get_reflection()`；`air_entry.inc`、`air_metal.c`（`815` 行）、`air_metal_vertex_cache.inc`（`234` 行）与 `air_metal_render_create.inc`（`1127` 行）支持顶点缓存深拷贝、NIR 缓存补反射与无片元 depth-only 管线；内核侧经 `annibalemetal_mesa.inc`（`227` 行）、`annibalemetal_reflection.inc`（`372` 行）与 `annibalemetal_device.inc`（`823` 行）接入 `AnnibaleMetalRenderReflection`（兼容 `vertexBindings` 与 `fragmentBindings`）。
- **间接纹理/指针反射与稀疏 `id > 63` 支持（Part 4）**：`air_reflection.c` 新增 `parse_texture_type_name()` 填充 `texture_type`/`texture_data_type`/`depth_texture`/`access`、`MTLDataTypePointer (60)` pointee 描述及 `is_argument_buffer = 1`；`annibalemetal_reflection.inc` 接入 `MTLTextureReferenceTypeInternal`、`MTLPointerTypeInternal` 与 `setIsIndirectArgumentBuffer:`；`annibalemetal_device_caps.inc`（`775` 行）实现 `-newArgumentEncoderWithBufferBinding:` 展平嵌套结构体与成员类型。
- **稀疏槽位扩容**：`air_metal_resource_private.h`（`308` 行）、`air_metal_argbuf.inc`（`707` 行）、`air_metal_reflect_vertex.inc`（`1043` 行）与 `annibalemetal_compute_argencoder.inc` 移除 `id >= 64` 拒绝与 `1ull << id` 移位未定义行为，`rwa_argbuf_slot.id` 按 `sl->id == id` 查找并支持动态扩容至 `RWA_MAX_ARGBUF_SLOTS = 1024`，`annibaleReady:for:` 允许已声明稀疏 `id > 63`（支撑 `particle_quad_frag` `id=200..231` 与 `sceneBuffers` `id=500..571`）。

## 3. 未使用与条件参数缓冲成员、直接资源裁剪与 NIR Cache

- **参数缓冲入口块活跃度追踪（Part 5）**：`nir_air.h` 为 `struct air_resource` 新增 `bool unused;`；`air_private.h`、`air_cfg.inc`（`595` 行）、`air_call.inc`（`706` 行）、`air_link.inc`（`322` 行）与 `air_argbuf.inc` 在入口基本块（`is_entrypoint && bi == 0`，递归/链接函数置 `false`）追踪 `argbuf_load()` 访问状态；`air_entry.inc` 在 UBO 槽压缩前统一标注 `r->unused` 与 `r->nullable`，压缩与 `nir->info.num_*` 计数跳过 `r->unused`，同时在 `rwa_module_argbufs()` 与 `argbuf_mask_of()` 保留完整声明布局。
- **直接资源未使用裁剪与条件修饰（Part 6）**：`air_interface.inc`（`903` 行）对直接 `air.buffer`/`air.texture`/`air.sampler` 识别 `air.arg_unused`（置 `unused`）与 `air.function_constant`（置 `nullable`）；`air_entry.inc` 新增 `mark_unused_direct_resources()` 在优化后扫描入口函数全部 SSBO/UBO/Image/Tex/Sampler 指令，将仅存入局部结构体而未解引用的直接资源（如 `particle_quad_vert` `buffer 13`）标为 `unused` 并重算 `nir->info`。
- **绑定校验与辅助通道 `unused` 适配（Parts 5–7）**：`air_metal_argbuf.inc`（`argbuf_member()`）、`air_metal_bind.inc`（`check_bindings()`、`bind_stage()`）、`air_metal_yuv.inc`（`180` 行，`yuv_key_for()`）、`air_metal_rgb2p.inc`（`415` 行，`rgb2p_prepare_bindings()`）、`air_metal_reflect_vertex.inc`（`rwa_module_textures()`、`build_vertex_state()`、`count_resources()`）与 `air_metal_compute.inc`（`597` 行）统一跳过 `r->unused`、放行 `r->nullable`（采样器回落 `default_sampler(device)`），同时保留无条件成员与 `destroyed`/类型/偏移拒绝。
- **NIR Cache 序列化同步（Parts 5–6）**：`air_metal_nircache.inc`（`803` 行）将 `NIRC_VERSION` 升至 `2u`、缓存格式标签升至 `"annibale-nircache-v3"`，并完成 `r->unused`、`argbuf_constants[]`、`indirect_argument_index` 与 6 项 `rwa_reflection_type` 字段读写同步。

## 4. G32 探针验证与细节页黑底现状

- **`N3Oc3mtc4nlnlnl` 实测排除输入/矩阵误差**：`annibalemetal_g32_probe.inc`（`778` 行）在 Part 1 扩展采集 `fbuf2`（`lod_bias`）与 `fbuf4[0..20]`（`168 B`），`b5r76` 在 `TimgA2Xhfsn_IsrcN3Oc3mtc4nlnlnl` 捕得 `fbuf2=0.000`、`fbuf4` Oklab/LMS 矩阵与 `t3=fmt115:256x1`（`nz=256/256 nan=0`）。按实测输入离线逐项计算输出有效天蓝色与彩色温标像素，排除了 `fbuf2`/`fbuf4` 参数本身归零。
- **`b5r82` 城市卡片点亮与详情页留存目标**：`b5r82` 的 `weather_cities.png` 中「萧山区 `17° 晴`」卡片已完整渲染蓝天渐变背景、日光晕与光斑特效，其余城市卡片因无天气数据保留 `--`；`weather_detail.png` 文字、小时预报太阳图标与 10 天预报条正常显示，全屏 `905×1967`（`fmt=80`）背景仍为纯黑且本轮未开 `g31-trace` 注入，需在后续先抓取 `b5r82` `555×165` 卡片与 `905×1967` 详情页对比 `g31-trace` 定位背景输出差异。

## 5. 宿主全量验证与规范核查结果

所有修改/新增文件均经 `wc -l` 核查在 `1200` 行以内（用户态最大 `air_metal_render_create.inc` `1127` 行，内核仓最大 `annibalemetal.m` `1130` 行），双仓 `git diff --check` 退出码均为 `0`，最后一次编辑后全部宿主测试与语料门禁均成功通过：

- **用户态 ASan+UBSan `-Werror` 单测**：`hackios-xnu-userland/tools/mesa/tests/` 下 `test-air-argbuf-constants.py`（`294` 行）、`test-air-render-reflection.py`（`407` 行）、`test-air-argbuf-unused.py`（`854` 行，`7/7`）、`test-air-nircache.py`（`526` 行），以及 `tools/air/` 下 `test-air-fc-prune.py`（`public=3, QuartzCore=2`）、`test-air-weather-vfx.py` 全部成功。
- **内核用户态驱动 ASan+UBSan `-Werror` 单测**：`hackios-xnu-kernel/tools/tests/` 下 `test-metal-argbuf-sparse.py`（`409` 行）、`test-g32-probe.py`（`306` 行，`6/6`）与 `tools/userland-driver/metal_reflection_test.m`（`379` 行）全部成功。
- **编译器检查与 607 着色器语料门禁**：`arm64e -mios-version-min=17.0 -fsyntax-only` 检查 `annibalemetal.m` 退出码 `0`；`VFX.framework/default.metallib`（`576/576`）+ `WeatherUI.framework/default.metallib`（`26/26`）+ `WeatherUI.framework/ForegroundEffectShaders.metallib`（`5/5`）共计 `607/607` `air_module_reflect`（ASan+UBSan）通过，`fail = 0`。
