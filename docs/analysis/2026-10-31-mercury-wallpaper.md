# 锁屏壁纸：MercuryPosterExtension 的渲染链路（2026-10-31）

本文记录默认壁纸由谁绘制、怎样送到屏幕，以及让壁纸和锁屏时钟显示出来的改动。主屏与锁屏从 `bo37` 起显示壁纸，锁屏时钟从 `bo45` 起显示。逐轮读数见[开机次序与性能记录](../progress/2026-10-31-boot-order-and-performance.md) §1。

## 1. 结论

- 默认锁屏海报是 `com.apple.MercuryPoster:configuration:space.dynamic`（PosterBoard 日志里的 `PosterActivated`）。它由 ExtensionKit 扩展 MercuryPosterExtension 用自己 bundle 里的 Metal 着色器（`default.metallib`、`Space.metallib`）和 KTX 纹理绘制，SpringBoard 用 `CALayerHost` 挂载扩展的 context（§2）。
- 壁纸黑屏由一串依次出现的缺口叠成，前一个不去掉就看不到后一个。缺口与改法见 §4，翻译器与驱动的改动见 §5。
- backboardd 拒收 SpringBoard 壁纸窗口的 commit（「CompressedImage port is MACH_PORT_NULL!」）：PosterUIFoundation 默认把海报快照存成 ATX 格式，SpringBoard 为它建的 memory entry 大小为 0。快照改存 PNG 后不再被拒，见 §6。
- 扩展用 4 倍多重采样画壁纸，解析出的 drawable 全部为 0。驱动在没有 `ANNIBALE_MSAA` 时把多重采样请求一律按单采样处理，主屏与锁屏随之显示壁纸，见 §7。
- 锁屏时钟由 backboardd 的 SDF 玻璃管线画出，依赖驱动按 mip 级别绘制、AIR 库接受尺寸不同的附件、AIR 翻译器支持指针存进局部再读回，见 §8。
- 单采样与 `POSTER_METAL` 现在都是默认配置。默认配置下开机全程有壁纸，滑动帧率与温度和没有壁纸的 `bo23` 相当（`bo38`）。

## 2. 壁纸的绘制与挂载

- MercuryPosterExtension 没有 launchd 任务，由 PosterBoard 经 ExtensionKit 拉起。它的标准输出与标准错误是 `/dev/null`。`package.py` 默认给它插入 Metal 设备登记库（`POSTER_METAL=0` 不插入，壁纸为黑色），这是它拿到 Metal 设备的唯一途径。
- 扩展进程里有三个 `PRPosterWindow`。第二个窗口里的 `MercuryPosterExtension.WallpaperMetalView` 是 `CAMetalLayer`，内容为 `CAImageQueue`。渲染通道是 1125x2436、4 倍多重采样。
- SpringBoard 的 `_SBWallpaperSecureWindow` 里，三个 `_UISceneLayerHostContainerView` 分别挂载扩展三个窗口的 context。另有一个 `PBUISnapshotReplicaView`，其下的 `UIImageView` 显示 1125x2436 的海报快照。
- 绘制前扩展先建「coordinator」：创建计算与渲染管线，加载 KTX 纹理。任何一步失败都会打印「couldn’t set up coordinator」，之后不再绘制，也不再提交。

## 3. 观测

- 驱动在检测到标准输出是 `/dev/null` 时，把每行写进 `kern.annibale.say`（`annibalemetal_console.inc`），每行间隔 5 毫秒，内核日志里是 `say PID MercuryPosterExtension: ...`。
- os_log 要在 libSystem 初始化时读到 `OS_ACTIVITY_DT_MODE`，插入库的构造函数运行时已经晚了。`EXT_ENV="MercuryPosterExtension:OS_ACTIVITY_DT_MODE=YES"` 把变量写进根盘的 `/annibale/etc/env/MercuryPosterExtension`；`inject_posterboard.c` 读到文件后设置变量、重新执行一次进程，并把标准错误转进 `kern.annibale.say`。
- backboardd 的「serialization error from context X」之前还有一行 `进程路径 (pid) : 原因`，原因来自 QuartzCore 解码器的报错函数。用 `sb26 layer window N 类名 context X` 行把 context 对到 SpringBoard 的窗口。
- 提交末尾的采样（`ANNIBALE_THUMBS`）有 `res` 一项，采样颜色附件的 resolve 目标。多重采样的附件本身不能采样（`rwa_texture_thumbnail` 拒绝）。
- 宿主机上的 `air2nir --report` 有 `group_free=1` 字段（§5）。
- 内核 `12377-cmd47` 起 `annibale_tl` 一行最长 319 字节，超长时截断并保留换行。原先的上限是 192 字节，`say` 行超长后丢掉换行、与下一行连在一起，64 像素宽的采样行读不出来。
- 插入库的 `__interpose` 拦不到 QuartzCore 对 libsystem_kernel 的调用：共享缓存里这类调用走直接跳转的 stub（`adrp`、`add`、`br`），没有可供 dyld 改写的指针。SpringBoard 的 `mach_make_memory_entry_64` 失败最后由内核探针读到（§6）。

## 4. 缺口与改法

| 缺口 | 读数 | 改法 |
|---|---|---|
| 扩展没有 Metal 设备 | 壁纸黑 | 插入 Metal 设备登记库（`POSTER_METAL`） |
| 扩展的输出全部丢失 | 驱动行和 os_log 都不可见 | 驱动的 `/dev/null` 输出改走 `kern.annibale.say`；`EXT_ENV` 与重新执行（§3） |
| AIR 拒绝管线 | 「couldn’t set up coordinator: Error Domain=AnnibaleMetal Code=1」 | AIR 翻译器的改动（§5） |
| 库拒绝压缩格式 | `albedo-a.ktx` 是 `ASTC_6x6_sRGB`（像素格式 190） | ASTC 与 BC 格式（§5） |
| 顶点阶段的纹理被丢弃 | `space::rasterizeMeshVertex` 在顶点阶段采样 | 驱动处理 `setVertexTexture:` 与 `setVertexSamplerState:`（§5） |
| 绑定检查 | `space::rasterizeBackgroundFragment reads texture 3 and 9 textures were bound` | 运行时选择的纹理可不绑定（§5） |
| blit 缺 selector | 缺 `copyFromTexture:...sliceCount:levelCount:` | `copyFromBuffer:...toTexture:` 与整级拷贝（§5） |
| 网格不能被线程组尺寸整除的派发 | freedreno 没有部分线程组 | `group_free` 的内核降低线程组尺寸（§5） |
| constexpr 的 bicubic 采样器 | 「the shader's own sampler at index 0 asks for filter::bicubic」 | 按 linear 采样 |
| SpringBoard 壁纸窗口的 commit 被拒 | 「CompressedImage port is MACH_PORT_NULL!」 | 海报快照存成 PNG（§6） |
| 多重采样的 drawable 为 0 | resolve 目标颜色与 alpha 都是 0 | 多重采样请求按单采样处理（§7） |

## 5. 翻译器与运行时的改动

AIR 翻译器（`tools/mesa/air/`）：

- 写入运行时计算的 mip 级别的图像（`VariableBlurrer::downsample`）：每个级别占一个图像槽（`image_level_slot`，每个纹理最多 15 级，ir3 共 32 个 bindless 图像），运行时按级别建视图。
- 运行时选择的纹理：`select` 与 `phi` 在纹理之间选择时，指针的 `binding` 置 0，槽号放进 `offset`，采样时作为 `nir_tex_src_texture_offset`。被选择的各个纹理标记为可不绑定（`air_texture_may_be_unbound`），因为应用只绑定选中的那一个（`rasterizeBackgroundFragment` 的四个 gobo 纹理）。
- 空纹理：`air.get_null_texture_*` 与 `air.is_null_texture_*`；对空纹理写入不做事，读取与采样得 0，尺寸为 0。
- 函数调用的聚合参数（`CALL_PARAM_AGG`）、`insertvalue` 进嵌套聚合的 undef 常量、`llvm.smax`／`smin`／`umax`／`umin`。
- 计算着色器是否读线程组（`reads_threadgroup`）：不读线程组位置与尺寸、不用 SIMD 组操作、屏障和线程组内存的内核记为 `group_free`。

验证：宿主机上编译 `air2nir`，对 176 个系统 metallib 加 `Space.metallib` 与扩展的 `default.metallib` 共 11398 个模块比较改动前后的 `--report`。翻译成功从 3590 个增加到 3858 个，没有原先成功、现在失败的模块，原先成功的模块 NIR 指令数全部不变。`Space.metallib` 里 `space::*`、`tori::*`、`VariableBlurrer::*` 全部翻译成功。

运行时（`air_metal.c` 与驱动）：

- 顶点阶段的纹理与采样器：驱动原先丢弃 `setVertexTexture:` 与 `setVertexSamplerState:`，`space::rasterizeMeshVertex` 在顶点阶段采样。
- 压缩格式：ASTC 的 LDR 与 sRGB 两组（186～200、204～218）和 BC1～BC7（130～153）按块规格直接对应 Gallium 格式，只能采样；上传按块计算行宽与层跨度。扩展的 KTX 是 `ASTC_6x6`（`albedo-a.ktx`）、`ASTC_4x4`（`normals-*.ktx`、`jurin_0*`）和 BC1（`jurin_innerglow*`、`jurin_unwrap_mask*`）。
- blit：`copyFromBuffer:...toTexture:` 在命令缓冲执行到它时由处理器从 buffer 写入纹理；`copyFromTexture:...sliceCount:levelCount:` 拆成逐级逐层的区域拷贝。
- 网格不能被线程组尺寸整除的 `dispatchThreads:`：freedreno 没有部分线程组。`group_free` 的内核按维把线程组尺寸降到能整除网格的最大值（`space::updateCylinderVertexPositions` 的 3602 个线程按 2 个一组），其余内核仍拒绝。
- constexpr 的 bicubic 采样器按 linear 采样，与 API 采样器的 cubic 一致；放大处比原图软。

## 6. SpringBoard 的 commit 被拒

- 报错位置：QuartzCore 解码 `CA::Render::CompressedImage` 时端口为空，报「CompressedImage port is MACH_PORT_NULL!」，整次 commit 记为 serialization error。每轮两次，都来自 SpringBoard 的 `_SBWallpaperSecureWindow`。
- CompressedImage 是块压缩格式的图像：构造函数按像素格式 186～218（ASTC）分支。编码时若还没有端口，QuartzCore 调用 `mach_make_memory_entry_64(task, &size, 数据地址, VM_PROT_READ | MAP_MEM_USE_DATA_ADDR | MAP_MEM_VM_COPY, &port, MACH_PORT_NULL)`；解码端用 `mach_vm_map` 把这个 entry 只读映射进 backboardd。端口为空说明 SpringBoard 里这次调用失败了。
- 内核探针 `xnu26/patches/74-osfmk%vm%vm_memory_entry.c.patch` 在 `mach_make_memory_entry_cleanup` 打印每次失败的拷贝型调用，每次开机最多 16 行（内核 `12377-cmd46` 起）。读数是 `SpringBoard[33] copy entry for 0x1154e0000 + 0x0 permission 0x300001 failed 4`，另一个地址 `0x1154e8000` 相同：大小为 0，在参数检查一步返回 `KERN_INVALID_ARGUMENT`。
- 这张图是海报快照：图层转储里 `PBUISnapshotReplicaView` 下的 `UIImageView` 内容是 `<ATX >` 格式的 CGImage。PosterUIFoundation 的 `PUIImageOnDiskFormat` 默认用 ATX 写快照（`+defaultATX`、`+atxWithBlockSize:twiddling:`）。
- 改法：`inject_posterboard.c` 在 PosterBoard、SpringBoard 与扩展里把这两个类方法换成 `+png`。`bo35` 起快照是 `<PNG >`，没有 serialization error。

## 7. 多重采样的 drawable 为空

- 快照改存 PNG 后，backboardd 导入了扩展的 1125x2436 surface（`annibaledrawable: backboardd import N: surface 12` 等），合成链路上没有报错，快照内容是不透明黑色（`mean 000000ff`）。
- 在扩展里打开 `ANNIBALE_SYNC_DRAWS` 与提交末尾的采样（`ANNIBALE_THUMBS`，`ANNIBALE_THUMB_ONLY=res0,out0`）后，1125x2436（surface）与 562x1218 两个 resolve 目标读到的部分全部是 0，颜色与 alpha 都是 0。
- 扩展的渲染通道是 4 倍多重采样，每个 draw 结束时 AIR 库用 blit 把颜色附件 resolve 进 resolve 目标。驱动对 `-supportsSampleCount:4` 默认回答 NO，只在 `ANNIBALE_MSAA=1` 时回答 YES；扩展不问这个结果，照样用 4 倍。
- 扩展打开 `ANNIBALE_ONE_SAMPLE=1` 后，驱动把多重采样纹理和管线都建成单采样，带 resolve 目标的通道直接画进 resolve 目标，主屏与锁屏显示壁纸（`bo37`）。
- 默认行为（`annibalemetal_diag.inc` 的 `rw_one_sample`）：没有 `ANNIBALE_MSAA` 时，驱动对 `-supportsSampleCount:4` 回答 NO，仍要 4 倍的应用拿到单采样。纹理对象照旧报告应用要的采样数，编码器据此区分这类附件与 CoreAnimation 的单采样附件；后者也带 resolve 目标，Metal 规定这时不写 resolve 目标。
- 单采样也去掉了每个带 resolve 目标的 draw 之后对整张 drawable 的 resolve blit。

## 8. 锁屏时钟与玻璃效果

- 时钟的图层：`CSProminentTimeView` 下是 SwiftUI 的 `TitleLabelView`，其中 `SwiftUI.SDFLayer`（`CABackdropLayer` 子类）下挂 `CASDFLayer` 与 `CASDFElementLayer`，后者的内容是 723x267 的 CGImage。时间数字由 backboardd 的 SDF 玻璃管线（`glass_background_lph`、`glass_foreground_sdf_lph`、`glass_background_sdf_no_bleed_lph`）画出。日期走 `BSUIVibrancyEffectView`，一直正常显示。
- 模糊金字塔：玻璃采样的模糊背景由 `variable_blur_downsample_frag_lph` 逐级画进一张 384x256 纹理的各个 mip 级别，每个通道用颜色附件的 `level` 指定级别。驱动原先忽略 `level`，所有通道都画进第 0 级，每个通道开头的清屏又把上一级清掉，玻璃读到的模糊背景为空。驱动改为对 `level` 非 0 的颜色附件建这一级的纹理视图（`annibalemetal_texture.inc` 的 `rw_attachment_level`）。
- 附件尺寸：这些通道的第二个颜色附件没有指定级别，和级别视图大小不同，AIR 库按「所有附件同尺寸」拒绝，一轮里 96 个命令缓冲失败，锁屏闪烁。库改为按所有附件共有的区域绘制，与 Metal 一致。之后 Dock 的玻璃底板显示，时钟仍不显示。
- 时间的 SDF 输入：玻璃管线采样的 SDF 是 SpringBoard 渲染的 `RGhA` 654x270 IOSurface，backboardd 读出为空，玻璃只画出包围盒形状。SpringBoard 每轮有一条 SwiftUI custom effect 管线被拒（`custom_effect_vertex` 加 `ffgea5cmba5dhmhba3`，链接 `custom_fn`）：`custom_fn` 把纹理句柄存进局部结构体 `RB::Layer`。
- 翻译器改动：存进局部（常量偏移的 alloca）的指针记在翻译期的槽里，同一位置读回指针时取回它（`air_ptr_slot.inc`）。宿主机上带 `--link` 的这条管线可以翻译；系统 metallib 语料 11398 个模块翻译成功 3858 个，没有回退。AIR 库重编后 SpringBoard 的管线拒绝为 0，锁屏显示时间（`bo45`）。
- 归因：同一次开机内把 backboardd 的导数切回旧算法（`AIR_COARSE_DERIVATIVES=1`）、把 SpringBoard 的单采样 resolve 切回旧行为（`ANNIBALE_RESOLVE_BLIT=1`）并重启进程，时间都仍然显示，所以时钟是指针槽改动修好的。这两处改动的来由见[参考仓库对照](2026-10-31-dada-reference-comparison.md) §3.1。
- `package.py` 不编译 AIR 库。改了 `tools/mesa/air/` 之后要先运行 `tools/k90auto/build-air.py`，否则打进根盘的还是旧库。

## 9. 未解决

- 扩展里 `IOSurfaceSharedEventAddEventListener failed: e00002c7` 与 `kIOSurfaceMethodSetCoreVideoBridgedKeys failed: e00002c7`：MiniIOSurface 没有实现 selector 40（`IOSurfaceSharedEventAddEventListener`）和 54（`IOSurfaceClientSetCoreVideoBridgedKeys`）。同样没有实现、开机过程中被调用的还有 17（`IOSurfaceClientSetSurfaceNotify`）、32（`IOSurfaceGetGraphicsCommPageAddress`）、41（`IOSurfaceSharedEventRemoveEventListener`），不插入 Metal 设备登记库时也会调用。selector 与函数的对应来自 iOS 26 IOSurface 框架的反汇编。
- 4 倍多重采样的渲染或 resolve 在 A830 上得到全 0，哪一步出错没有查。查时用 `ANNIBALE_MSAA=1` 给扩展打开 4 倍，再用提交末尾的采样读 `res`。
- Dock 的玻璃在进入桌面后先完整，随后一段时间只剩边缘高光，几分钟后恢复（用户反馈）。一直只剩边缘高光的情况来自 A830 的纹理预取读到全 0，`bo52` 起关掉预取后完整显示（`hackios-xnu-kernel/tools/mesa/rebase-26/README.md` 第 6 项）；时好时坏与预取的关系没有核实。
