# 11-21 真机体验问题：长录屏、逐项复现与修复

用户在 14:56～15:02 用手机上的 `v0.2.1` 版本（Release 包，用户态 `2244410`）完整操作了一遍，报告了下面十余个问题。本文记录问题清单、取证、录屏工具和逐项结论；上一批的状态见 [11-20 交接](2026-11-20-handoff.md)。

## 1. 用户报告的问题

时间为用户操作时的北京时间。

| 编号 | 时间 | 现象 |
|---|---|---|
| U1 | 约 14:56:46 | 上滑进入桌面后，「日历」和「时钟」两个图标是透明的 |
| U2 | 约 14:56:59 起 | 桌面左右翻页时图标出现过程有卡顿，持续掉帧 |
| U3 | — | 相机预览有条纹；对焦方框一直闪烁；预览延迟大；画面左右反 |
| U4 | — | 从相机返回后打开「设置」，动画过程中屏幕中间偏下出现一条从左到右、较高的黑色区域；再次打开仍出现 |
| U5 | — | 「设置」底部搜索框背景为深色，状态栏文字为浅色（浅色模式下应为深色）；向上滚动一点后恢复 |
| U6 | 约 14:59:20、14:59:40 | 「地图」画面有大量深色、黑色色块，定位正常；几秒后闪退，两次 |
| U7 | 约 15:00:40～15:01:06 | Safari 新打开的页面始终空白、一直加载中，多个网页相同；此前 Safari 可用 |
| U8 | 约 15:01:53 | 「照片」显示 35 张照片，网格预览区全空白，滚动条正常 |
| U9 | 约 15:02:16 | 「照片」中单张照片可以打开和缩放，但左右反转，放大后方向变对 |
| U10 | — | 在 iOS 里触发关机后，loader 停在异常状态，没有处理关机请求 |

## 2. 取证

用户的操作结束后，在同一次开机里立即取得了以下内容，原始文件在 Git 忽略的 `docs/progress/evidence/k90auto/user-1121/`。

- 内核日志环只覆盖 15:02:52 之后约 66 秒，其中约四分之三是 Wi-Fi 驱动的调试行和每次扫描打印的邻近网络列表，用户操作时段的日志已被覆盖。
- `CrashReporter` 目录有当天三份报告：`com.apple.MapKit.SnapshotService`（14:56:43）、`ExcUserFault_MobileSafari`（15:00:55）、`analyticsd`（14:51:30）。14:59 前后没有 `Maps` 的崩溃报告。`annsh ls` 输出上限 600 行，该目录共约 1,030 项，未列出的部分没有检查。
- 地图快照服务的崩溃：线程 14 在 `libannibaleair.dylib` 的 `batch_draw_tracking`（偏移 `0x3115e4`）读地址 `0x308`，与用户态 `d8e05f9`（11-18）修复的崩溃是同一位置。`v0.2.1` 的用户态 `2244410` 早于该提交，不含这项修复。
- Safari：15:08 用 `trollstorehelper url` 打开网页，页面空白，进程列表里没有任何 `com.apple.WebKit.*` 进程，`MobileSafari` 本身在运行。报告 `ExcUserFault_MobileSafari` 是 `MobileSafariUI` 主动生成的 `WEBKIT` 命名空间模拟崩溃，不是进程退出。同一张截图里状态栏只看得到电池，时间文字与浅色背景同色，与 U5 是同类现象。

用户手机上的版本落后开发分支三天的修复（开机图标空白、「照片」绘制、快门期间 GPU 停转等，见 [11-20 交接](2026-11-20-handoff.md)），所以每一项先在开发分支的构建上复现，再定位。

## 3. 长录屏

原有的内核录屏（`fb_filmstrip.py`）把画面存进 96 MiB 缓冲，最多约 100 帧、3 秒多，录满即停，适合截取短暂闪烁。这一批改为可以持续录制：

- 内核 `kern.annibale.rec_stream=N`（`MiniFramebufferRecord.inc`）：每秒最多记录 N 帧（1～30），缓冲写满后覆盖最旧的帧，每写完一帧就把该帧和头部刷到内存。两帧间隔小于 1/N 秒时跳过后一帧；跳过的帧之后没有新帧时，间隔到期后补录一次在屏扫描缓冲，保证动画的最后一帧被录下。录制尺寸为面板的三分之一（385×836），缓冲约容纳 104 帧，每秒 10 帧时约 10 秒。
- 主机 `tools/k90auto/screenrec.py`：测试轮期间由 `run-auto.py` 在每次循环里经 `oem stage` 读出新帧，编码成固定帧率的 `screen.mp4`，每帧左上角印上估算的北京时间和内核时间；`frames.jsonl` 记录每帧的内核时间。命令、点按和日志快照照常进行。
- 启动参数 `wifi_quiet=1` 同时关掉每次扫描打印的邻近网络列表，只保留汇总行，延长日志环能覆盖的时间。

用法写在 `screenrec.py` 文件头。

## 4. 开发分支上的复现结果

内核 `12377-rec1`／`12377-rec2`，开发分支用户态，自动解锁后按用户的操作顺序用 `tour.py` 回放并全程录屏（`kernel-12377-rec1-rec2/run/rec-flow2`、`rec-flow3`、`rec-maps1`）。

| 编号 | 结果 |
|---|---|
| U1 | 开机约 2 分钟后「日历」「时钟」图标正常；解锁瞬间的状态没有录到，待从开机起录屏复核 |
| U3 | 预览条纹复现（CAM-1）；对焦框、延迟、左右反待逐项判读。另复现一次相机黑屏（物理连续缓冲区申请失败），已修复，见第 7 节 |
| U4 | 从相机返回后两次打开「设置」，每秒 10 帧的录屏里没有黑色横带 |
| U5 | 「设置」的状态栏文字和底部搜索框颜色正常；滚动中搜索框背景有一帧偏深，待放大核对 |
| U6 | 复现：「地图」中地球视图出现大片黑色扇区，随后 GPU 停转，见第 5 节 |
| U7 | 复现：页面空白、一直加载，没有 `com.apple.WebKit.*` 进程；已修复，见第 6 节 |
| U8 | 「照片」打开在「精选集」页，「固定」一行的三个缩略图是黑块；「图库」页网格空白（`kernel-12377-m2log-m2a`） |
| U9 | 开发分支不复现，见第 7 节 |

## 5. 地图触发的 GPU 停转与整屏闪烁（S21）

### 5.1 现场

15:25:41 打开「地图」时 GPU 上下文发生 SMMU 翻译故障（地址 `0:0`，`UCHE_CLIENT_PF` 客户端 `BR_SP`），提交方是 Maps。内核关闭全部提交，之后：

- backboardd 的命令缓冲全部超时，显示驱动等 500 ms 后把没画完的两个画面（surface 419 和 2）照原样轮流上屏，即用户看到的整屏亮暗交替。
- SpringBoard 约每 5 秒崩溃重启一次，backboardd 也重启过一次。

### 5.2 停转后的显示

`MiniIOMobileFramebuffer::show()` 改为：图层的画面没画完、且 GPU 已经关闭提交（`annibale_gpu_ready()` 为假）时，这次交换不上屏，面板保持最后一帧已完成的画面；GPU 正常时仍是等 500 ms 后照原样上屏。`12377-rec2` 上复现停转（第 9 次重开，故障地址 `0:0x40`）：内核打印一次 `the GPU has stopped; the panel keeps its last frame`，录屏在停转时刻之后没有新帧，相隔 4 秒的两张截图状态栏以下 0 个像素不同。

### 5.3 根因

判别实验（`kernel-12377-rec2-s21b`）：只给 Maps 设 `IR3_SHADER_DEBUG=nopreamble,nocache` 与 `MESA_SHADER_CACHE_DISABLE=true`，其余不变，连续重开 20 次没有停转，地图正常绘制。此前 13 轮里 11 轮在 10 次内停转。

- 这一代 GPU 上 freedreno 用着色器前导码装载常量（`fd6_load_shader_consts_via_preamble`）：前导码在绘制开始时用 `ldc` 读着色器用到的每个 UBO 范围，不看主程序的分支。
- `fd6_emit_ubos()` 给没有绑定缓冲的 UBO 槽写 `A6XX_UBO_DESC(i, NULL, 0, 0)`，即地址 0。停转批次的命令流里，顶点阶段的 UBO 表 0 号槽、片元阶段 22 槽的表里 15 个槽都是地址 0。
- Metal 允许着色器在运行时不访问的缓冲参数不绑定。前导码读到这类槽，就读地址 0 加偏移，与故障地址 0、0x40、0x80 一致；关掉前导码后常量改由 CP 推送，CP 跳过空槽。

修复（用户态 `tools/mesa/rebase-26/0021-fd6-zero-unbound-ubo-slots.patch`）：每个上下文分配一块 64 KiB 全零、GPU 只读的 BO，未绑定的 UBO 槽指向它，大小填满 64 KiB。

- `fd_context` 的私有 BO 表原来只有 3 个位置（`control_mem`、`zero_desc_mem`、`bcolor_mem` 已占满），新增的第四个越界写坏了计数，backboardd 开机约 10 秒崩溃（`kernel-12377-rec2-s21c`）。补丁同时把表扩到 4 个。
- 验收（`kernel-12377-rec2-s21d`，前导码照常开启）：同样的步骤连续重开 20 次，没有 SMMU 故障，没有停转，SpringBoard 与 backboardd 全程各一个 pid。地球视图画出正常的陆地和海洋，此前同一画面是大片黑色扇区。

### 5.4 遗留

地图上的建筑物仍是纯黑块，修复前后相同，与停转无关，另行排查（U6 的剩余部分）。

## 6. Safari 空白页（U7）

### 6.1 直接原因

`kernel-12377-rec2-saf1` 用 `OSLOG=MobileSafari`（`oslogwatch.c`，把进程的 os_log 转进内核日志）看到：

- WebKit 查 `com.apple.WebKit.Networking`、`com.apple.WebKit.GPU` 的扩展记录时，LaunchServices 返回 `-10814`（找不到该扩展记录），随后 `Error launching process`，所以没有任何 WebKit 进程。
- 五个扩展都在 `/System/Cryptexes/OS/System/Library/ExtensionKit/Extensions/` 下，缺的是 LaunchServices 数据库里的登记。

### 6.2 根因

- 删掉 LaunchServices 数据库、重启 lsd 让它整库重建（`kernel-12377-rec2-lsd1`）：lsd 经 InstalledContentLibrary 登记了五个 WebKit 扩展，Safari 正常打开网页。
- 同一镜像重启一次（`lsd2`）：lsd 的开机首启工作打印 `Cleaning ephemeral mobile containers` 与 `Marking container at /private/preboot/Cryptexes/OS/ for removal`，WebKit 扩展随这个容器从数据库删除。
- 反编译 CoreServices：这一步逐个检查数据库里的容器，FSNode 不等于 `rootVolumeNode`、`systemDataVolumeNode`、`prebootVolumeNode`、`userDataVolumeNode` 之一的容器在开机时删除。`_LSServer_NodeIsOnTrustedCryptex` 同样要求文件所在卷是根卷或 Preboot 卷，再用 `fsctl(FSIOC_GET_GRAFT_INFO)`（`'J'` 102）确认文件在嫁接里。
- iOS 用 graftdmg 把 Cryptex 嫁接进 Preboot 卷，Cryptex 里的文件属于 Preboot 卷。本移植此前由 init 把 Cryptex 作为独立的 APFS 卷挂载在 `/private/preboot/Cryptexes/OS`，卷节点是这个挂载点，lsd 把它当成临时容器；内核对 `FSIOC_GET_GRAFT_INFO` 返回 ENOTTY（lsd 日志 `couldn't get cryptex info ... Code=25`）。

LaunchServices 只在数据库缺失或损坏时整库重建，开机不会重新登记 Cryptex 内容，所以每次重建后只有当次开机 Safari 可用。

### 6.3 修复

- 内核 APFS 驱动实现嫁接（`bsd/miscfs/apfs/apfs_graft.inc`）：被嫁接卷的 vnode 属于宿主卷的挂载，statfs 与文件系统 ID 都是宿主的；嫁接根目录的 inode 号是宿主目录的 inode 号，其余对象的 inode 号从 `(N + 1) << 60` 起，不会与宿主的对象标识重叠；`FSIOC_GET_GRAFT_INFO` 按 xnu `bsd/sys/fsctl.h` 的结构返回。
- init 用本移植的 `APFS_IOC_GRAFT` 把 OS 与 App 两个 Cryptex 嫁接到 `/private/preboot/Cryptexes/`，内核不认这个 fsctl 时回退为挂载。
- 已装机设备的数据库里这几条记录已经删掉：以嫁接方式启动的第一次开机，init 删除一次 LaunchServices 数据库并写入 `/private/var/db/.annibale-cryptex-grafted`，lsd 启动时重建，与 iOS 更新后的处理相同。

### 6.4 验证

| 轮次 | 内核 | 结果 |
|---|---|---|
| `kernel-12377-graft1-graft1` | `12377-graft1` | 两个 Cryptex 均以嫁接方式接入（OS Cryptex 4692 个对象），系统正常启动；整库重建后 Safari 启动三个 WebKit 进程 |
| `kernel-12377-graft1-graft2` | 同上，同一镜像重启 | lsd 首启工作不再打印 `Marking container`；没有重建数据库，Safari 打开百度并显示图文 |
| `kernel-12377-graft2-graft3` | `12377-graft2`，带一次性重建的 init | init 删除 2 个数据库文件，lsd 开机重建；Safari 启动三个 WebKit 进程，百度图文正常 |

## 7. 单张照片左右反转（U9）与相机黑屏

### 7.1 U9

内核 `12377-m2log` 带启动参数 `m2_log=1` 时，`MiniM2Scaler` 为每个进程每种转换打印一行（标志、格式、尺寸）。`kernel-12377-m2log-m2a` 打开一张照片：

- 「照片」先用 M2Scaler 把 1606×1204 的图旋转成 1206×1608（标志 `0x3004`，rot90），作为打开时的整屏图；放大后的分块不经过这一步。
- 用户手机上的 `v0.2.1` 内核早于 `0f213aee`（11-19）。该提交之前 rot90 按转置实现（`tx = uy, ty = ux`），转置等于旋转加左右镜像，所以打开时左右反、放大后正常。
- 开发分支上 rot90 已是顺时针旋转：同一张照片打开时与放大后的方向一致。

### 7.2 相机黑屏与拍摄按钮扫描

`kernel-12377-m2log-m2a` 在「照片」之后打开「相机」，预览一直是黑的，期间 backboardd 每秒约 740 行 `setScanningActive:YES/NO button:cameraCapture pid:29` 与 `no services (yet?), pending`。同一现场的内核日志：

- 17:33:26 打开「相机」后，内核两次 `vm_page_find_contiguous(num=1024, ...)` 找不到连续页，`annibale_cam: failed to allocate camera frame buffer`，两个摄像头的 `/dev/annibale-camera` 都打开失败（`EIO`）。
- 插件只为后摄建了一个仅带闪光灯的流（`the device made: 1 streams`），CMCapture 随后约每秒 200 次请求并交还这个流（`streams given back 11000 times`），从未启动采集。
- SpringBoard 的拍摄按钮扫描随会话状态每次开关一次，所以扫描日志是采集会话循环的结果。

根因：内核驱动每次打开摄像头时用 `kmem_alloc_contig` 申请 16 MB 物理连续的两帧缓冲区，关闭时释放。CSID/VFE 写物理地址（cam_hf_qtb 的 Stage 1 旁路），缓冲区必须连续；系统运行一段时间后物理内存碎片化，找不到 16 MB 连续空闲页。

修复（内核 `annibale_camera.c`）：启动时在 `annibale_camera_init` 申请这块缓冲区并一直保留，打开时只在启动时申请失败的情况下重试，关闭不再释放。每次采集准备时 `cam_native_prepare` 之后会清零两帧，保留缓冲区不会带出上次会话的内容。

`kernel-12377-graft3-btn1` 从桌面打开「相机」，申请成功、预览正常，backboardd 只有一组 `setScanningActive:YES`，没有循环；U3 的对焦框闪烁和延迟与这个循环无关，待单独判读。

验证：`kernel-12377-camreg-cam1` 启动日志没有申请失败；连续三次先打开「照片」再打开「相机」，三次预览都正常。这一轮的内核日志快照里没有 `failed to allocate camera frame buffer` 和 `streams given back N times`，插件每次建出两个流（`the device made: 2 streams`）。

遗留：`/dev/annibale-camera` 打开失败时，插件仍为后摄建一个只带闪光灯的流，CMCapture 会反复请求和交还它。缓冲区改为启动时申请后，这条路径只在启动时就申请失败的情况下出现。
