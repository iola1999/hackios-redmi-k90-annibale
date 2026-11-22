# 11-22 晚：照片发黑、对焦马达异响与自动锁定

用户 11-22 晚在测试机上报告四件事：拍完的照片在相机左下角、「照片」网格和单张浏览里都是黑的；触发对焦时马达声音明显；「减弱动态效果」被打开过；自动锁定不生效，插电时屏幕一直亮着。本文记这一批的查找与改动，轮次为 `kernel-12377-keep1-w13`、`kernel-12377-lens2-w14`、`-w15`。

## 1. 照片发黑

照片文件本身就是黑的，问题出在拍摄处理，显示与解码都没有问题：

- `IMG_0058.HEIC`（4032×3024）解码后平均 RGB 为 2.1、0.6、7.4，最大 40、22、60。这一阵拍的照片都只有 90～500 KB，之前正常的照片约 1.5 MB。
- 插件交给 CMCapture 的静态图正常（日志 `StillImage: ... Y 121 Cb 112 Cr 141`），变黑发生在之后苹果的照片处理里。

已经找到的两处原因：

- **非整除网格的派发被丢弃（G28）**。每张照片都有三次 `dispatchThreads`（588×444、294×222、74×111，线程组 16×32）因为网格不能整除、核又读取线程组信息，被驱动直接丢掉。这一批实现了按 Metal 部分线程组语义的拆分派发：网格拆成至多 8 次整线程组的派发，每次按它在网格里的位置单独翻译（`rwa_dispatch_split`）。`w13` 上这三条报错消失，照片 `IMG_0059` 的颜色随之改变（平均 RGB 18、0.1、1.5），但仍然很暗。
- **Deep Fusion 的一个核被拒（新发现）**。`RawDFSyntheticReferenceCRG::kernelRawDFDeepShadowRecovery` 在建管线时被 AIR 前端拒绝，原因是「a pointer loaded from memory (argument buffers)」：核从参数缓冲里读出一个指针再去访问。AIR 前端目前把缓冲映射为绑定槽位，没有按 GPU 地址访问全局内存的路径。这是照片仍然发暗的下一处原因，需要在 AIR 前端支持从内存读出的缓冲地址（ir3 的全局内存访问），跟踪见[图形待办 G28](../backlog/graphics.md)。

「照片」网格空白（G25）与照片内容无关，仍按原待办跟踪。同一批日志里 `mediaanalysisd` 的 `VTMTSComputeFunction1x1` 也因为没有设置线程组内存长度被拒，影响照片分析，没有查。

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

这是本次排查造成的。`kernel-12377-idle4-w5` 为了判断每秒 10 帧的来源，用启动参数 `ax_rm=1` 调了 `_AXSSetReduceMotionEnabled`，这个设置会写进数据分区，之后每次开机都保留。用户已经手动关掉。以后这类判别实验需要在轮次结束时把设置改回去。

## 5. 其他发现

- 地图建筑物发黑（G26）：MapKit 的 `DaVinci::elevated*` 渲染管线全部被拒，原因是顶点着色器的 `clipDistance` 输出以一个元素的数组到达（`air_to_nir.c` 拒绝数组形式的输出）。修法写在该处注释里：输出按元素类型声明，返回时写第 0 个元素。本批没有改。
- 每秒 10 帧在「设置」里同样存在，这次的空闲窗口里没有任何触摸事件，来源仍未找到。

## 6. 改动与未验证范围

- 内核：`annibale_camera_clock.inc`（马达分步移动）；`tools/userland-driver` 的拆分派发（`annibalemetal_compute_argencoder.inc`、`annibalemetal_commandbuffer_submit.inc`、`annibalemetal_mesa.inc`、`annibalemetal_work_private.h`）。
- 用户态：`tools/mesa/air` 的拆分派发（`air_grid_split`、`rwa_dispatch_split`、按拆分参数缓存的编译结果）；`inject_sb26_layers.c` 的 `idlelog=1` 探针。
- 未验证：马达声音（需要人听）、拆分派发对其他应用的计算核的影响（只在相机上跑过）、自动锁定的原因。
