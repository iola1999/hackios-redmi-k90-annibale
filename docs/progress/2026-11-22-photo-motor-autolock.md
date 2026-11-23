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

之后的轮次里照片仍会间歇性发暗：`w77`、`w79` 的第一张是暗绿（0、18.2、0.3），`w78` 的单张正常，`w79` 连拍的第二、三张正常（159.8、175.4、158.6 与 165.6、172.0、163.5）。命令缓冲之间的时序还有没覆盖到的地方，仍在查。

11-23 更新（`say16-ubo2`/`say16-ubo3`）：暗绿确认是**每个相机会话的第一张**。`ubo3` 会话首拍 `IMG_0083` 为 0.0/18.2/0.3，连拍的 `IMG_0084`/`IMG_0085` 为 150.9/167.4/150.1 与 164.0/171.5/162.3；重新打开相机、等 35 秒预热再拍首张，`IMG_0086` 仍为 0.0/18.3/0.3——与预览预热时长无关，是会话状态而非时钟收敛。由此回看，`w77` 把高位常量缓冲改读 SSBO 得到的暗绿很可能只是它赶上了会话首拍，SSBO 方案被误判。高位常量缓冲（LTM 17 个）已改为折入 15 号槽共享窗口并随本轮上机（无 AIRFAIL、GPU 稳定），但首拍暗绿的根因在别处。

同日深挖（`ubo3` 内核与 mediaserverd 日志）：每次快门实际产生**两张**静态图——请求字典里 `GenerateRedEyeAuxiliaryImage = 1`，`stills_wanted += 2`，第一张静态图（`StillImage Y 9~11`，Cb/Cr 中性）是红眼辅助帧并带 `RedEyeAuxiliaryImage` 附件标记，第二张（`Y 147~158`，Cb 115 Cr 109 偏绿）是照片帧。两张都进 `BWStillImageCoordinatorNode`，`BWPhotonicEngineNode` 每次拍摄只产出一张 2352×1764，`BWPhotoEncoderNode` 编出一张 4032×3024。会话首拍存出的暗绿（0/18/0，与照片帧同色相、亮度约十分之一）有两个候选解释：协调器把第一张红眼辅助帧错当照片帧（其会话级「哪张是主帧」状态未初始化），或 PhotonicEngine 首张处理时读到未写的参数/融合权重把 Y147 帧压暗。下一步：对照首张与第二张进入协调器/引擎的样本缓冲与附件（`emit_sample_buffer` 已在 `inject_media.c` 有挂点，给附件里的 `RedEyeAuxiliaryImage` 与捕获计数加日志即可定别）。

「照片」网格空白（G25）与照片内容无关，仍按原待办跟踪。`mediaanalysisd` 的 `VTMTSComputeFunction1x1` 因没有设置线程组内存长度被拒，影响照片分析，仍未处理。

## 2. 对焦马达异响

声音的来源是镜头一次写入就移动很长的距离：相机打开时从静止位置（0）一步写到中间（512），关闭时直接断电让镜头落回，搜索开始时又跨过半个行程（例如 441 到 768）。原厂马达设置里只有初始化和断电两组寄存器，没有给出移动方式。

内核改为（`annibale_camera_clock.inc` 的 `cam_native_lens_walk`）：

- 超过 64 个位置的移动拆成每步 64、步间 3 ms。
- 上电后从 0 走到目标位置，断电前先走回 0 再断电。

`w15` 上对焦照常：一次搜索 804 ms，预览 30 帧/秒，没有跳帧。声音是否消失需要用户实际听一次确认。

## 3. 自动锁定不生效

11-23 修复。原因是 CommCenter 没有运行，SpringBoard 每秒重置一次空闲计时器。

排查顺序（`kernel-12377-lens2-w14`～`w61`，SpringBoard 侧用 `idlelog=1` 的钩子，backboardd 侧用 `awlog=1`）：

- SpringBoard 应用的计时器是 `warn 40 s、total 60 s`，与「自动锁定 1 分钟」一致；倒计时由 IdleTimerHosting 的 `ITAttentionAwarenessClient` 交给 backboardd 里的 AttentionAwareness 服务。
- 服务本身正常：测试程序 `attn_test` 设 5 s 超时能按时收到 `AWAttentionLostEvent`；触摸事件也送到了服务（`processHIDEvent`，类型 11、掩码 0x8），空闲计时器的客户端对它们「感兴趣」。日志里的「Socket is not connected」和「lost event tag is not a number」来自 SpringBoard 自己的其他注视客户端（HomeGrabberView 等），与空闲计时器无关。
- 真正的问题：SpringBoard 每秒调用一次 `-[AWAttentionAwarenessClient setConfiguration:shouldReset:YES]`（291 s 内 284 次），每次都让 40/60 s 的计时重新开始。重置的原因几乎全是 `TelephonyManager:UpdateSB`。
- 调用链：`SBTelephonyManager` 由 `performSelector:afterDelay:` 周期执行一个状态更新函数，CoreTelephony 的服务连接（`_serverConnection`）不可用时走 `handleCallControlFailure:` → `updateCalls` → `updateSpringBoard` → `resetIdleTimerForReason:@"TelephonyManager:UpdateSB"`。连接不可用是因为 `mkjobs.py` 把 CommCenter 放在 DENY 名单里，`com.apple.commcenter.coretelephony.xpc` 没有应答者。

修复：`mkjobs.py` 不再排除 CommCenter。launchd 按设备树选用 `com.apple.CommCenter-noncellular`（没有基带节点的设备用的变体），AppleBasebandPCI 的 cellular plist 照旧跳过。早先记录的「CommCenter 每 15 秒崩一次」在当前内核上没有复现。

验收（`w61`，默认镜像，USB 供电即插电状态）：开机解锁后静置，背光先降到 6 nits（变暗），随后 panel off（锁屏）。`w60` 里空闲计时器按时收到 40 s、42 s、60 s 三个 lost 事件，CommCenter 开机 5 分半没有重启。

## 4. 「减弱动态效果」

这是本次排查造成的。`kernel-12377-idle4-w5` 为了判断每秒 10 帧的来源，用启动参数 `ax_rm=1` 调了 `_AXSSetReduceMotionEnabled`，这个设置会写进数据分区，之后每次开机都保留。用户已经手动关掉；`w21` 读回 `com.apple.Accessibility.plist`，`ReduceMotionEnabled` 与 `ReduceMotionReduceSlideTransitionsPreference` 都是 0。[k90auto 运行规程 §4](../plan/k90auto-run-protocol.md#4-轮次目录与固定收尾) 增加了一条：判别实验改过的系统设置在这一轮收尾前写回原值。

## 5. 其他发现

- 地图建筑物发黑（G26），11-23 修复。MapKit 快照服务的 `DaVinci::elevated*` 管线先因 `clipDistance` 以数组输出被拒，现在按 NIR 的形式声明为紧凑的 float 数组并逐元素写入（`w26` 起建成）。「地图」应用里建筑块纯黑是另一个原因：
  - 定位：地图进程全部绘制同步并在建筑像素上加像素探针（`ANNIBALE_PIXEL_PROBE`，`w72`），建筑先画成正常颜色，`DaVinci::ground_fragment` 把它写成全透明 00000000，最后的 `Clear` 合成成不透明黑。取回地图实际特化的着色器（`ANNIBALE_DUMP_AIR`），它只算 `styleColor.color × 光照`、alpha 取 `styleColor.color.a`，`styleColor` 在 `[[buffer(21)]]`；同一绘制绑定的第 21 号缓冲内容是 half4(0.791, 0.776, 0.760, 1.0)，即正确的建筑色。
  - 判别：测试程序 `ubo_test`（`ubo21.metal`）在一个计算核里从 `buffer(3)`、`buffer(5)` 读到写入的值，从 `buffer(21)`、`buffer(22)` 读到全 0（`w75`）。freedreno 只给 ir3 声明 16 个常量缓冲（`freedreno_screen.c` 的 `max_const_buffers`），我们直接把 Metal 的缓冲号当成常量缓冲槽和 UBO 块号用。
  - 修复：`air_entry.inc` 在着色器用到 16 号以上的常量缓冲时，按缓冲号顺序把常量缓冲重新编号到 0～15，NIR 的 `load_ubo` 与 `set_constant_buffer` 都用新号（`air_resource.slot`），取缓冲仍按 Metal 的号。
  - 验收（`w76`、`w79`）：`ubo_test` 四项全部读对；地图截图里建筑是浅灰的正常颜色，地图区域近黑像素从约 58,000 降到 0，GPU 没有停转。
  - 遗留：超过 16 个常量缓冲的着色器（相机的 `LTM` 核有 17 个），多出的仍按原号、读到 0，和修复前一样。把多出的改成只读存储缓冲读取后照片发暗（`w77`），原因没有查，这一步没有保留。运行时选择常量缓冲的着色器不重新编号。
- 桌面静止时每秒 10 帧的来源是「时钟」图标的秒针，属于原生行为。`SBHClockApplicationIconImageView` 给秒针建了一个显示链接，`preferredFrameRateRange` 为 10..120、首选 10（`kernel-12377-lens2-w70`，`dl_log=1`，调用方 SpringBoardHome+0x1ad6d8），我们注入的帧率钩子没有改它。`w69` 连续三张截图逐像素比较，每 100 ms 只有约 800 个像素变化，范围 x 971～1014、y 1203～1290（截图坐标），正是时钟图标的位置；同一轮停在「计算器」时 0 帧。
- 这 10 帧的代价：驱动每帧只画变化的行（`fb_rows` 默认开启），一帧约 85 行、在驱动里 3.6～4.0 ms，其中约 2 ms 等 GPU。
- `w63` 把 CoreAnimation 的心跳降到 1 Hz（`caenv=CA_HEARTBEAT_RATE=1`）时静止帧率降到 0.9，但 `w67` 交互时也只剩约 1 帧/秒，心跳是显示时钟的基准节拍，我们按 `fb_ca_hz=120` 发布的 1/120 s 是对的，不能用它降空闲帧率。
- 之前记录的「设置里同样每 100 ms 一次」需要更正：`w70` 停在「设置」时三张截图像素完全不变，交换约 15 次/秒、backboardd 提交约 17 次/秒，但面板上 0 帧变化，用户进程合计 2.0% 单核。这些空交换的来源没有再查，开销可以忽略。
- 宿主 `air2nir` 恢复可用（ENG-25 的一部分）：`util_copy_rect` 调用的 `rwa_copy_rect_guard` 在宿主工具里补了弱定义，`build-air.py` 把 `air2nir.c` 加入复制列表。

## 6. 改动与未验证范围

- 内核：`annibale_camera_clock.inc`（马达分步移动）；`tools/userland-driver` 的拆分派发与 imageblock 尺寸、commit 后立即写回拷贝纹理、计算管线被拒时的 AIRFAIL 转储（不计入每次开机 4 个的名额）。
- 用户态：`tools/mesa/air` 的拆分派发（`air_grid_split`、`rwa_dispatch_split`、按拆分参数与 imageblock 尺寸缓存的编译结果）、`unwritten_pointer`、派发后的 `memory_barrier`、拷贝纹理上传前的读映射、`clipDistance` 数组输出；`inject_sb26_layers.c` 的 `idlelog=1` 探针；测试程序 `shm_test posix` 与 `attn_test`。
- 未验证：马达声音（需要人听）；拆分派发和每次派发后的屏障对其他应用计算性能的影响；照片在白天和室外的颜色；自动锁定的原因（第 3 节）。
