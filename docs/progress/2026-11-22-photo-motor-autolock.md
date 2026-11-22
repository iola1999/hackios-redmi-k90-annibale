# 11-22 晚：照片发黑、对焦马达异响与自动锁定

用户 11-22 晚在测试机上报告四件事：拍完的照片在相机左下角、「照片」网格和单张浏览里都是黑的；触发对焦时马达声音明显；「减弱动态效果」被打开过；自动锁定不生效，插电时屏幕一直亮着。本文记这一批的查找与改动，轮次为 `kernel-12377-keep1-w13`、`kernel-12377-lens2-w14`、`-w15`。

## 1. 照片发黑

照片文件本身就是黑的，问题出在拍摄处理，显示与解码都没有问题：

- `IMG_0058.HEIC`（4032×3024）解码后平均 RGB 为 2.1、0.6、7.4，最大 40、22、60。这一阵拍的照片都只有 90～500 KB，之前正常的照片约 1.5 MB。
- 插件交给 CMCapture 的静态图正常（日志 `StillImage: ... Y 121 Cb 112 Cr 141`），变黑发生在之后苹果的照片处理里。

11-23 凌晨修复，原因共五处，按发现顺序：

1. **非整除网格的派发被丢弃（G28）**。每张照片有三次 `dispatchThreads`（588×444、294×222、74×111，线程组 16×32），网格不能整除、核又读取线程组信息，驱动直接丢弃。改为按 Metal 部分线程组的语义拆成至多 8 次整线程组的派发，每次按它在网格里的位置单独翻译（`rwa_dispatch_split`）。
2. **Deep Fusion 的核在翻译时被拒**。`RawDFSyntheticReferenceCRG::kernelRawDFDeepShadowRecovery` 被拒的原因是「a pointer loaded from memory」。用驱动的 AIRFAIL 转储取回 bitcode 后，`metal-objdump` 反汇编显示读出的是纹理句柄：调用方只给一部分 `BandSampler` 写了第二个纹理，内联的 `samplePixel` 在标志为 0 的分支里读它，翻译时这个本地槽位没有存过指针。读未写过的内存在 LLVM 里得到 undef，任何值都合法；现在用最近存进本地的指针代替（`air_ptr_slot.inc` 的 `unwritten_pointer`）。宿主 `air2nir` 翻译这个核成功（1,312 条 NIR 指令）。
3. **拆分派发丢了 imageblock 尺寸**。这三次派发都设置了 32×32 的 imageblock，拆分后按线程组大小翻译，中间纹理只写出几条竖列（`w22` 的缩略图）。`rwa_dispatch_split` 现在带上 `-setImageblockWidth:height:` 的尺寸。
4. **建在缓冲上的纹理，写回放在完成线程**。行字节不是 64 的倍数（544、288）或缓冲没有可导入句柄（16×12 的统计纹理）时，库用拷贝模拟这类纹理。GPU 写过的拷贝要在完成线程上拷回缓冲，下一个命令缓冲在这之前就提交并读了缓冲。现在每次 commit 在 flush 后立即写回（`annibalemetal_commandbuffer_submit.inc`）。
5. **拷贝纹理上传时没有等 GPU**。commit 开始时把缓冲内容上传到拷贝纹理，读的是缓冲的持久映射，在途命令缓冲的 GPU 可能正以缓冲形式写这段内存。现在先对这段范围做一次读映射，等那些写完成（`buffer_texture_upload`）。

另外每次派发后加了 `memory_barrier`。Metal 串行派发的每一次都看得到前面的写入，freedreno 只有被要求时才在同一批次的两次 grid 之间刷新缓存（`fd6_barrier.cc`）。单独这一项没有让照片恢复（`w26`），按语义保留。

判别过程：同步模式（每次派发都等 GPU，`w25`）照片正常；每次派发后只提交不等待（`w27`）仍然暗；每次 commit 后等待命令缓冲完成（`w28`）正常。由此确定问题在命令缓冲之间，排查范围缩到第 4、5 处。

验收（`kernel-12377-lens2-w30`，正常的非同步模式，连拍三张，夜间室内，增益 16 倍）：

| 照片 | 大小 | 平均 RGB |
|---|---|---|
| 修复前 `IMG_0058` | 174 KB | 2.1、0.6、7.4 |
| 第 1～3 处修复后 `IMG_0067`（`w24`） | 235 KB | 0、18.6、0.2 |
| `IMG_0074` | 641 KB | 134.9、177.7、137.8 |
| `IMG_0075` | 590 KB | 157.9、175.6、156.8 |
| `IMG_0076` | 571 KB | 164.0、172.2、161.9 |

相机左下角的缩略图有内容，「照片」单张浏览显示的就是文件内容。画面偏绿来自插件交出的静态图本身（日志 `Y 148 Cb 115 Cr 109`），属于预览与拍照的白平衡，按相机待办 M6 跟踪。修复前拍的照片仍是暗的，需要重拍。

「照片」网格空白（G25）与照片内容无关，仍按原待办跟踪。`mediaanalysisd` 的 `VTMTSComputeFunction1x1` 因没有设置线程组内存长度被拒，影响照片分析，仍未处理。

## 2. 对焦马达异响

声音的来源是镜头一次写入就移动很长的距离：相机打开时从静止位置（0）一步写到中间（512），关闭时直接断电让镜头落回，搜索开始时又跨过半个行程（例如 441 到 768）。原厂马达设置里只有初始化和断电两组寄存器，没有给出移动方式。

内核改为（`annibale_camera_clock.inc` 的 `cam_native_lens_walk`）：

- 超过 64 个位置的移动拆成每步 64、步间 3 ms。
- 上电后从 0 走到目标位置，断电前先走回 0 再断电。

`w15` 上对焦照常：一次搜索 804 ms，预览 30 帧/秒，没有跳帧。声音是否消失需要用户实际听一次确认。

## 3. 自动锁定不生效

用启动参数 `idlelog=1` 在 SpringBoard 里记录空闲计时器（`SBIdleTimerGlobalCoordinator` 的三个方法）：

- 锁屏解除后 SpringBoard 应用的计时器是 `mode: Auto; warn: 40.0s; total: 60.0s`，与「自动锁定 1 分钟」一致，`samplingStartBeforeFirstTimeout` 为 12 秒。
- 3 分钟以上没有触摸，计时器始终没有走到 40 秒的变暗，背光只随环境光变化。这段时间里没有触摸事件。

SpringBoard 一侧设置正确，倒计时在 backboardd 的 AttentionAwareness（`ITAttentionAwareIdleTimer`）。还没有查清的两个方向：注视检测在到期前 12 秒开始采样，这台机器没有原厂 Face ID 的相机，采样结果可能一直被当作「用户在看」；或者有别的事件不断重置计时。插电后常亮与这是同一个问题，iOS 插电时同样会自动锁定。下一步在 backboardd 里记录 AttentionAwareness 的采样与超时回调。

## 4. 「减弱动态效果」

这是本次排查造成的。`kernel-12377-idle4-w5` 为了判断每秒 10 帧的来源，用启动参数 `ax_rm=1` 调了 `_AXSSetReduceMotionEnabled`，这个设置会写进数据分区，之后每次开机都保留。用户已经手动关掉；`w21` 读回 `com.apple.Accessibility.plist`，`ReduceMotionEnabled` 与 `ReduceMotionReduceSlideTransitionsPreference` 都是 0。[k90auto 运行规程 §4](../plan/k90auto-run-protocol.md#4-轮次目录与固定收尾) 增加了一条：判别实验改过的系统设置在这一轮收尾前写回原值。

## 5. 其他发现

- 地图建筑物发黑（G26）：MapKit 快照服务的 `DaVinci::elevated*` 渲染管线曾全部被拒，原因是顶点着色器的 `clipDistance` 输出以数组形式到达（一个或两个元素）。现在按 NIR 的形式声明为紧凑的 float 数组并逐元素写入，光栅化状态打开同样数量的裁剪平面；`w26` 起这些管线都建成，GPU 没有停转。但「地图」应用里的建筑块仍是纯黑（`w30` 截图），应用本身用的是 `PolygonFill` 等其他管线，黑色另有原因，仍在查。
- 每秒 10 帧在「设置」里同样存在，这次的空闲窗口里没有任何触摸事件，来源仍未找到。
- 宿主 `air2nir` 恢复可用（ENG-25 的一部分）：`util_copy_rect` 调用的 `rwa_copy_rect_guard` 在宿主工具里补了弱定义，`build-air.py` 把 `air2nir.c` 加入复制列表。

## 6. 改动与未验证范围

- 内核：`annibale_camera_clock.inc`（马达分步移动）；`tools/userland-driver` 的拆分派发与 imageblock 尺寸、commit 后立即写回拷贝纹理、计算管线被拒时的 AIRFAIL 转储（不计入每次开机 4 个的名额）。
- 用户态：`tools/mesa/air` 的拆分派发（`air_grid_split`、`rwa_dispatch_split`、按拆分参数与 imageblock 尺寸缓存的编译结果）、`unwritten_pointer`、派发后的 `memory_barrier`、拷贝纹理上传前的读映射、`clipDistance` 数组输出；`inject_sb26_layers.c` 的 `idlelog=1` 探针；测试程序 `shm_test posix` 与 `attn_test`。
- 未验证：马达声音（需要人听）；拆分派发和每次派发后的屏障对其他应用计算性能的影响；照片在白天和室外的颜色；自动锁定的原因（第 3 节）。
