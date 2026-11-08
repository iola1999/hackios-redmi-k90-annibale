# Mesa 26.2.5 移植层（rebase-26）

本文记录 Mesa 从 25.0.7 换到 26.2.5 时 fork 补丁的应用结果、`tools/mesa/rebase-26/` 适配层的内容、a8xx 支持的版本依据、iOS 交叉构建和测试脚本在 26.x 上的适配。`tools/mk-mesa.sh`、`userland/build.sh`、`tools/mesa/rebase-26/README.md` 和 `tools/air/` 下的脚本按节号引用本文（第 2、3、6、9 节和 10.3），调整章节时同步检查这些引用。

## 1. 结论

- 基线为 26.2.5 加 rebase-26 适配层：`0001`、`0002` 是两个 a8xx 修复的 cherry-pick，`0003` 恢复 OSMesa 并带上 26.x 适配，之后各补丁的用途见 rebase-26 的 README。`userland/build.sh` 的 GL 分支固定 `REBASE=26 VERSION=26.2.5`；`mk-mesa.sh` 不带参数时仍构建 25.0.7。
- 2026-10-23 的 8 个 fork 补丁在 26.2.5 上：4 个原样应用，1 个可以退役，3 个部分失效；失效内容由 `0003` 重建（第 2 节）。
- 上游删除了 OSMesa，`0003` 从 25.0.7 恢复它（第 3 节）。AIR 前端已迁移到 26.x API（第 4 节）。
- hackios-dev 容器内的 iOS 交叉构建可以复现，交叉产物与主机产物的导出符号集合一致（第 9 节）。

## 2. fork 补丁在 26.2.5 上的应用结果

流程与 `mk-mesa.sh` 相同：解压上游 tarball，依次应用 `tools/mesa/*.patch`，拷入 `src/compiler/air` 和 `src/annibale-drm` 两个直接复制的目录，再应用 rebase-26。tarball 为 archive.mesa3d.org 的 `mesa-26.2.5.tar.xz`，SHA-256 `794b3d1729075dae7ebd47c7283b7ca0cdb5dec668f7f11cc0a5d82f6138a0a5`。

| 补丁 | 26.2.5 上的结果 | 处理 |
| --- | --- | --- |
| air-frontend | 严格应用通过 | 保留 |
| air-metal | 严格应用通过 | 保留 |
| air-ir3 | 失败：上游在 986530d231（25.3+）删除 `ir3_cmdline.c`，8 个 hunk 全部落空；freedreno/meson.build 的 `air_run` hunk 上下文偏移 | 删除 cmdline 部分，`air_run` 声明并入 0003 |
| freedreno-darwin | 失败：`src/freedreno/drm/meson.build` 的 libvdrm TODO hunk 上游已修；`fd6_draw.cc` 的 fb_read 锚点偏移；`freedreno_screen.c` 的 `pipe_screen.ram_size`／sysinfo 已删除；osmesa 三个文件缺失被跳过 | 删除失效 hunk，fb_read 重新定位与 osmesa 钩子并入 0003 |
| osmesa-es-profile | 空跑：`include/GL/osmesa.h`、`osmesa.c` 在 26.x 不存在 | 内容并入 0003 恢复的文件 |
| ir3-round-default | 严格应用通过；`create_cov` 舍入块在 26.2.5 仍没有 else 分支 | 保留 |
| ir3-shift-split | 使用点 hunk 失败：26.x 重写的 `ir3_nir_try_propagate_bit_shift` 只匹配纯 ishl/ishr/ushr，不再拆 `(c+x)>>s` | 可以退役，它修的 bug（`grid_buf[id-1]` 读 0）的成因已在上游消失 |
| ir3-ssbo-subdword | 严格应用失败，默认 fuzz 下两个 hunk 均应用；vanilla 26.2.5 没有 `may_lower_*` 字段，确认补丁生效 | 保留，hunk 上下文待刷新为严格匹配 |

26.1.8 与 26.3.0-rc1 上的失败集合与 26.2.5 基本相同。`REBASE=26` 时 `mk-mesa.sh` 容忍旧补丁的失败或跳过，实际丢弃的 hunk 记在产物目录的 `out/patch.log` 和 `out/patch-survey.txt`。

## 3. OSMesa 恢复

上游 027ccd963b（自 25.1-branchpoint 起）删除了 OSMesa 前后端，替代路线是 EGL surfaceless。iOS 侧没有 EGL 栈，`userland/src/eagl.c` 与 `gl_osmesa.c` dlopen 的是 `libOSMesa.8.dylib`，因此由 `0003-restore-osmesa-26.x-drift-adaptations.patch` 恢复：

1. 反向应用 027ccd963b 的 meson 改动：`meson.options` 加回 `osmesa`，根 `meson.build`、`include/meson.build`、`src/gallium/meson.build` 恢复 `frontends/osmesa` 和 `targets/osmesa`。
2. 从打过补丁的 25.0.7 树取回 9 个文件（`include/GL/osmesa.h`、frontends/osmesa 2 个、targets/osmesa 6 个），其中已含 osmesa-es-profile 与 freedreno-darwin 的 osmesa 钩子。
3. 26.x 适配：
   - `inc_mapi` 不再存在，`inc_glapi` 只在 `src/mesa/glapi` 内可见，三处 meson 改用 `include_directories('../../../mesa/glapi')`。
   - `with_shared_glapi` 变量已删除，targets/osmesa 直接链接 `libglapi`。
   - 26.x 的 shared-glapi 静态库只含调度核心，`gl*` 桩在 `libglapi_bridge`。osmesa 目标不链它时 dylib 不导出任何 `gl*`，加进 `link_whole` 后导出 1300 个。
   - `driParseConfigFiles` 改为 3 参的 `driConfigFileParseParams`，`osmesa_target.c` 的调用点重写。
   - 26.x 删除了 postprocess（`postprocess/filters.h`），`pp_*` 全部去掉，`OSMesaPostprocess` 保留为空函数；本端口从未启用 filter。
   - `src/util/u_sync_provider.c` 在 Darwin 上加 `host_machine.system() != 'darwin'` 门控，因为 annibale-drm 没有 syncobj；Turnip 构建另行编译它（rebase-26 的 0004）。

macOS 主机验证：`nm -gU` 见 1300 个 `_gl*` 和 13 个 `_OSMesa*`；`rebase-26/smoke-osmesa.c` 输出 `GL_VERSION: 3.3 (Compatibility Profile) Mesa 26.2.5 / GL_RENDERER: softpipe`，clear(0.25,0.5,0.75) 读回像素 (64,128,191,255)；`smoke-osmesa-es.c` 用 `OSMESA_ES_PROFILE` 创建出 OpenGL ES 3.1 上下文。

## 4. AIR 前端的 26.x API 迁移

改动都在 `tools/mesa/air/`（copy 目录，源文件本身就是被编译的版本，不另做补丁），`rebase-26/0003` 无需连带修改：

- `PIPE_SHADER_*` 改为 `MESA_SHADER_*`，`enum pipe_shader_type` 与 `gl_shader_stage` 改为 `mesa_shader_stage`，`gl_shader_stage_name` 改为 `_mesa_shader_stage_to_string`。
- `nir_builder.exact` 移除，改用 `b.fp_math_ctrl` 位域：`air_private.h` 的 `air_builder_set_exact()` 清除或设置 `nir_fp_exact`（no_contract、no_reassoc、no_transform），4 处 save/restore 改存 `uint32_t`。
- `nir_block_create(c->nir)` 改为 `nir_block_create(c->b.impl)`；`nir_shader_create` 删除第四个参数；`nir_copy_prop` 改名 `nir_opt_copy_prop`；`unreachable()` 改名 `UNREACHABLE()`。
- `driParseConfigFiles` 同第 3 节改为 `driConfigFileParseParams`；`set_constant_buffer` 去掉 `take_ownership`；`set_sampler_views` 去掉末尾的 bool；`pipe->clear` 从 6 参变为 8 参，新增参数传 `0xf`、`0xff`、NULL。
- `get_compiler_options` 移除，改读 `screen->nir_options[MESA_SHADER_*]`。
- `create_surface` 移除，`pipe_surface` 成为值结构并内嵌在 `pipe_framebuffer_state` 中。`air_metal.c` 与 `air_run.c` 改用 `pipe_surface_init()` 就地填充，销毁时对 `.texture` 调用 `pipe_resource_reference(&…, NULL)`。
- glsl_type 查询回调的返回类型从 int 改为 unsigned。
- `get_compute_param` 移除，改读 `screen->compute_caps`。`subgroup_sizes` 在 26.x 是支持宽度的位掩码（25.0.7 的 freedreno 返回字面 32），取最低位作为执行宽度；softpipe 全零时回退为 1。

macOS 主机上用 softpipe（`AIR_RUN_SOFTWARE=1`）验证：`fragpos.ll` 的 4×4 绘制读回像素 (0,0) 为 (0.5, 0.5, 0, 1)；`tools/air/texopcheck.py` 全量 99 次调用中 74 次命中、18 次 WRONG、7 次拒绝，18 次 WRONG 都是 i16/v4i16 取样，softpipe 无法判定窄于 32 位的类型，7 次拒绝与 userland `docs/air.md` 记录的 16 位结果相符；`tools/air/argbufruncheck.sh` 20/20 通过。

## 5. a8xx 支持的版本依据

- SM8750／Adreno 830（`0xffff44050000`）的真实 devinfo 与 a8xx_gen1 gallium props 由 48be91d1 在 26.1.0 加入；26.0.x 只有 cffdump 用的「FD830」条目，不能使用。
- `CHIP >= A8XX` 运行时分支从 26.0.0 起存在，26.2.5 已齐备。
- 两个 a8xx 修复只在 26.3-branchpoint 之后：`2ee0a5e6`（Indirect buffer needs WFM on a8xx+，改 fd6_barrier 与 fd6_context.cc）和 `779cdb8e`（Fix query barriers for gen8+，改 fd6_query.cc）。它们在 26.2.5 上 cherry-pick 无冲突，即 rebase-26 的 `0001`、`0002`。
- 26.3.0-rc1 自带这两个修复，fork 补丁的失败集合与 26.2.5 相同，`0003` 只有 `freedreno/meson.build` 的 2 个 hunk 需要手工移植。改用 26.3 可以去掉 0001、0002。

## 6. 基线：26.2.5 加 rebase-26

fork 补丁加 rebase-26 适配层后，26.2.5 可以完整构建。构建命令：

```bash
VERSION=26.2.5 SHA256=794b3d1729075dae7ebd47c7283b7ca0cdb5dec668f7f11cc0a5d82f6138a0a5 REBASE=26 tools/mk-mesa.sh
```

- `REBASE=26` 在 `tools/mesa/*.patch` 循环之后按文件名顺序应用 `tools/mesa/rebase-26/*.patch`。rebase-26 是子目录，原有的 `tools/mesa/*.patch` 通配不会收进它，25.0.7 构建因此不受影响。
- 旧补丁在 `REBASE=26` 时允许失败或跳过，其他版本仍要求严格应用（第 2 节）。
- 补丁戳 `mesa-$VERSION/.annibale-patches` 在 `REBASE=26` 时计入 rebase-26 的补丁内容；`out/built-from` 另计入版本号与 `REBASE`，`userland/build.sh` 据此判断库是否过期。两个戳的计算逻辑见 `hackios-xnu-userland/tools/mk-mesa.sh` 与 `hackios-xnu-userland/tools/mesa-stamp.sh`。

## 7. 源码副本与构建树

- `hackios-xnu-kernel/tools/mesa/` 和 `tools/mk-mesa.sh` 属于与内核检出共用工作树的 userland 仓库（`common/setup.sh` 展开，用 `common/ugit` 提交），与 `hackios-xnu-userland/tools/mesa/` 保持同步；补丁说明见 [`tools/mesa/rebase-26/README.md`](../../hackios-xnu-userland/tools/mesa/rebase-26/README.md)。
- iOS 26 的 arm64e AIR 库由 `tools/k90auto/build-air.py` 构建，它的构建树和工具链见 [arm64e 用户态构建路径](2026-10-28-arm64e-userland-build-path.md)。

## 8. 剩余工作

- 补丁栈整理：删除 ir3-shift-split；freedreno-darwin 按功能拆成 drm-meson、bo-iosurface、batch-fb_read、osmesa-target；OSMesa 恢复单独成片；ir3-ssbo-subdword 的 hunk 上下文刷新为严格匹配。
- 26.x 的 a8xx 编译器对 demote 发出自己的 `ir3_DEMOTE`，a6xx 编码器把 DEMOTE 映射为 KILL；7c+ Gen 3 实际使用哪一种，要用 `discardcheck.py` 的 `--emit`／`--check` 在设备上确认（10.3）。

## 9. iOS 交叉构建

### 9.1 结论

在 hackios-dev 容器内执行：

```bash
VERSION=26.2.5 SHA256=794b3d1729075dae7ebd47c7283b7ca0cdb5dec668f7f11cc0a5d82f6138a0a5 REBASE=26 AIR=1 tools/mk-mesa.sh
```

退出码为 0，产物在 `xnu-deps/build/mesa/out/`，均为 Mach-O arm64（2026-10-23）：

- `libOSMesa.8.dylib` 18 659 056 字节，导出 1300 个 `gl*`，与 macOS 主机构建逐名比对一致；
- `libannibaleair.dylib` 13 063 080 字节，31 个 `rwa_*` 导出，与主机构建的数量和集合相同；
- `air_run` 13 620 416 字节，另有 `exported-gl.txt`、`gl.xml`、`built-from`、`built-from-air`。

Mesa 的二进制不按字节复现（25.0.7 实测两次构建相差 9 132 774 字节），所以交叉产物与主机产物的等价按导出符号集合判定，字节哈希只用来固定输入（tarball、补丁栈、镜像内工具）。导出集合一致只覆盖符号名称，类型布局、调用约定、运行行为和着色器结果要在设备上验证。31 这个数是当时的记录，`mk-mesa.sh` 把实际导出列表写进 `out/exports-rwa.txt`。

### 9.2 交叉路径的依赖

- 编译器是 `xnu-deps/host/bin/xnu-clang`：容器原生 clang 18，加 `-target arm64-apple-ios16.5` 和 `--ld-path=$HB/ld64`。`ld64` 是 theos 工具链 `toolchain/linux/iphone/bin/ld` 的符号链接，不在仓库里。
- meson 还需要 `xnu-clang++`（`xnu-deps/setup.sh` 创建的同名分身）。`mk-mesa.sh` 不运行 setup.sh，缺失时自己创建这两个符号链接。
- `install_name_tool` 不在容器 PATH 里，`mk-mesa.sh` 按 `$THEOS/toolchain/linux/iphone/bin` 解析。
- theos 与 SDK 的版本取自 kbuild 容器：theos HEAD `304e0799973e8145f32e4ca2de6c747a84b758ce`，ld64-609（L1ghtmann iOSToolchain），iPhoneOS16.5.sdk。

### 9.3 镜像内容（`docker/Dockerfile`）

- apt 增加 `bison flex patch gawk autoconf automake libtool-bin m4 perl libzstd-dev zlib1g-dev python3-venv ninja-build`。meson 由 `mk-mesa.sh` 的 venv 安装并固定为 1.12.1：26.x 的 meson.build 要求 ≥1.4，Ubuntu noble 的 apt 只有 1.3。
- theos 的 Linux iPhone 工具链是 x86_64 ELF，靠 OrbStack 的 Rosetta 运行，镜像因此 `dpkg --add-architecture amd64` 并安装 `libc6:amd64 libuuid1:amd64 libstdc++6:amd64 libtinfo6:amd64`。两个陷阱：
  - ports 源没有 amd64 索引，加 amd64 架构后 apt 全部 404。ubuntu.sources 的 ports stanza 要写 `Architectures: arm64`，另加主档案源 `Architectures: amd64`，Suites 要带 noble-updates，否则 libc6 版本对不上。
  - `zlib1g` 是 Multi-Arch: same，ports 的 arm64 与主档案的 amd64 版本不同，apt 判定 not installable。镜像绕过 dpkg 数据库，直接解包固定 URL 和 SHA-256 的官方 deb。
- theos 固定在 `304e0799…`，`ENV THEOS=/root/theos`。iOSToolchain 下载 latest，构建时校验 `bin/ld` 与 `install_name_tool` 的 SHA-256；`install-sdk iPhoneOS16.5` 之后校验 `SDKSettings.plist`。上游内容变化会让镜像构建失败。

### 9.4 `mk-mesa.sh` 的 26.x 修正

1. 26.x 删除了 `-Dgallium-vdpau`、`-Dgallium-xa`，meson 对未知选项直接报错，按 VERSION 分支（`LEGACY_TRACKERS`）；25.0.7 行为不变。
2. `REBASE=26` 时旧补丁循环容忍失败；25.0.7 仍严格。
3. `ld64`、`xnu-clang++` 缺失时创建符号链接。
4. `install_name_tool` 使用 `$THEOS` 工具链的显式路径，macOS 主机回退为裸名。
5. `nm` 改为 `llvm-nm`：GNU BFD 2.42 不识别 arm64 Mach-O。
6. 26.x 的 gl.xml 移到 `src/mesa/glapi/glapi/registry/`，按存在性回退。

### 9.5 复现

```bash
cd docker && ./build.sh && ./dev.sh
cd /work/hackios-xnu-kernel
VERSION=26.2.5 SHA256=794b3d1729075dae7ebd47c7283b7ca0cdb5dec668f7f11cc0a5d82f6138a0a5 \
  REBASE=26 AIR=1 tools/mk-mesa.sh
```

补丁栈戳命中时跳过解包，ninja 增量重跑。删除 `xnu-deps/build/mesa/{mesa-26.2.5,build-*,venv}` 回到全新构建，meson setup 到 ninja 完成约 8 分钟（OrbStack，VirtioFS）。验收看 9.1 的导出集合。

## 10. 测试脚本在 26.x 上的适配

### 10.1 `cpuref.py` 不需要 ir3

`cpuref.py` 用 host triple 的 `llc` 编译模块，链接生成的 C harness 运行，再与前端折叠后的 NIR 比较，不经过 ir3。在 26.2.5 的 macOS 产物上运行 `tools/air/loweringcheck.py`（逐模块走同一机制）得到 `20 of 20 modules behaved as expected -- 18 compared against LLVM on this processor, 2 refused by name`。`cpuref.py --all` 覆盖全语料的前提是 `ios165/rootfs` 的 metallib 语料。

### 10.2 `discardcheck.py`

前两段判定（可翻译；NIR 带 `demote`、不带 `terminate`）的 NIR 读数改取 `air2nir` 默认模式的 `nir_print_shader` 输出，`@demote` 判据不变。第三段 ir3 指令检查在 `$IR3` 不存在时打印 SKIPPED，不再阻止前两段和 air_run 的拒绝校验；存在时行为不变，25.0.7 旧树仍可用。`IR3` 指向不存在的路径时结果为 `2 of 2 shapes as expected`，退出码 0。与设备侧的 `--emit`／`--check` 契约不变。

### 10.3 26.x 没有离线 ir3 编译入口

上游在 986530d231（25.3+）删除了 `ir3_cmdline.c`，26.x 没有替代工具：

- NIR 到 ir3 的编译都在 libgallium 内部（`ir3_compiler_nir.c`），需要 screen 和 compiler-options 上下文。
- `src/freedreno/` 的独立工具（`pgmdump2`、`computerator` 等）读取已编译的 program 二进制，用不上；turnip 不在 Darwin 配置里。
- 恢复 cmdline 需要为仍在变化的 a8xx 接口维护一个上游不收的工具，而指令形状本来要在设备上确认（第 8 节）。

因此 `fbfetchcheck.py`、`vattrcheck.py`、`corpus.py --ir3` 与 10.2 同样降级：`$IR3` 存在时行为不变；缺失时 fbfetch 的 isamm 段与 vattr 的 VFD fetch-table 段打印 SKIPPED 并计入通过，corpus 去掉 ir3 列，表格停在 translate。三个脚本都在 stderr 留一行说明，退出码不受影响，`check.sh` 在 26.x 主机上不再因此失败。实测 fbfetch `7 of 7`、vattr `16 of 16`，corpus 对单个 `.bc` 运行 `--ir3` 去掉该列后退出码为 0。这些段落的结果以设备上打印的指令为准。

## 11. 附录：macOS 主机构建命令

前提：已解压 mesa-26.2.5，应用 fork 补丁栈和 `rebase-26/*.patch`，并按 `mk-mesa.sh` 拷入 `src/compiler/air`、`src/annibale-drm`。系统自带的 bison 2.3 过旧，需要 bison ≥ 3（Homebrew）和装有 meson 1.12.1、mako、pyyaml 的 venv。相对 `mk-mesa.sh`，去掉了 26.x 已删除的 `-Dgallium-vdpau`、`-Dgallium-xa`；`-Dshared-glapi=enabled` 仍保留，上游已标记废弃。

```bash
meson setup build-darwin mesa-26.2.5 --wrap-mode=nofallback --prefix=/annibale --libdir=lib \
  --buildtype=release -Db_ndebug=true -Dplatforms= -Dgallium-drivers=softpipe,freedreno \
  -Dfreedreno-kmds=msm -Dvulkan-drivers= -Dglx=disabled -Degl=disabled -Dgbm=disabled \
  -Dosmesa=true -Dllvm=disabled -Dshared-glapi=enabled -Dgles1=disabled -Dgles2=enabled \
  -Dopengl=true -Dzstd=disabled -Dxmlconfig=disabled -Dexpat=disabled -Dshader-cache=disabled \
  -Dvalgrind=disabled -Dlibunwind=disabled -Dglvnd=disabled -Dvideo-codecs= -Dtools= \
  -Dgallium-va=disabled -Dlmsensors=disabled -Dbuild-tests=false
ninja -C build-darwin
```
