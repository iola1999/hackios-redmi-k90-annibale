# 批 5：ANE CPU 回退验证与相机功能修复（2026-11-25）

批 4 把 mediaanalysisd 照片分析管线逐层闭合到 ANE 模型加载层，批 5 主攻这最后一层，同批推进相机对焦、前摄编码、GPU 配速三条支线。到 b5r3 为止的结论：ANE 加载层修复验证通过，执行层撞上跨进程复现的 Espresso `io_error`（status=-2），是 U8 唯一主线阻塞；相机链被证明硬依赖 ANE（`tunneled_ane_op` CPU 拒绝执行），scoped spoof 必须排除 cameracaptured。

## 1. 反编译判别的两个决定性结论

`out/goal-1124/batch5/ane-close.md`：Espresso 读 `kern.hv_vmm_present` 判 VM，命中后 `espresso_create_context` 把引擎改写为 0（CPU 平台）、设备 -1，load_network 层再强制 compute path。苹果自维护的生产路径，GPU/CPU 回退方向成立。

`out/goal-1124/batch5/espresso-status.md`：status=-2 是 io_error，-6 是 invalid_argument/context/device 三类共用；算子未实现与配置不受支持分别是 -9/-12。相机链的 `mrflownet-v2` 模型是单节点 `tunneled_ane_op`，CPU launch 直接拒绝——相机链不能用 CPU 回退，VM spoof 对相机永远是死路。mediaanalysisd 的人脸/场景/质量模型全是常规卷积算子，CPU 路径适配。

## 2. 内核 scoped spoof 与三轮真机

内核 `dd5ca201`：`sysctl_vmm_present` 按进程应答，默认名单 cameracaptured,mediaanalysisd，boot-arg `ane_vmm_procs` 可覆盖。

| 轮 | 变量 | 结果 |
|---|---|---|
| b5r1 | 基线（编码打点 userland `950e7eb`） | 相机正常出片，ANE load failure 签名存在 |
| b5r2 | spoof 双进程 | ANE 加载失败签名归零，但 cameracaptured 内 Espresso CPU 执行 `handle_ex_plan status=-2/-6`，取景器黑、零成片 |
| b5r3 | boot-arg 缩到只剩 mediaanalysisd | 相机恢复（因果链闭合）；mediaanalysisd 加载层打通、CPU 改写行为证据确凿（CNN GPU 管线归零），但执行期 `status=-2` io_error 依旧，err 105 持续 |

三轮证据在 `docs/progress/evidence/k90auto/kernel-12377-flipwd4-b5r{1,2,3}/`。

## 3. U8 当前阻塞与成功口径

`io_error` 跨进程复现（b5r2 cameracaptured、b5r3 mediaanalysisd 同签名），是平台级 Espresso CPU 执行问题。头号嫌疑：MiniIOSurface 软件模拟的 CPU 访问语义与真机差异（对齐/压缩/映射）。抛出点枚举反编译进行中，产出 `out/goal-1124/batch5/espresso-ioerror.md`。

成功口径已闭合（`out/goal-1124/batch5/zresult-semantics.md`）：err 105 = Scene_Embedding 阶段（VCP backbone 推理链失败统一出口）；成功判据 = `MediaAnalysis.sqlite` 的 ZASSET/ZRESULT 转非零、payload blob 非空、`ZIMAGEEMBEDDINGVERSION=77`、ZPROCESSINGSTATUS 到 32767(Done)。验收 SQL 在 `out/goal-1124/batch5/zresult-validation.sql` 与 `photos-analysis-validation.sql`。

## 4. 支线状态

- **对焦框 ❌**：userland `f3a3d4e`（AFStatus 取值修正、FocusNowCommandID 哨兵、AFStable）真机验证未生效——点按后无任何新 FocusNow 命令到达插件，初始命令的完成确认因 `FocusPeakSumArray` 键缺失而不发生，后续命令被状态机拒收。消费路径反编译进行中。
- **前摄 -16808**：`out/goal-1124/batch5/front-xf20-contract.md`——几何触发论被时序证据否定（错误链在首张交付前出现；2496x2496 无 padding 零扩展恰是契约正确形态）。xf20 实验 diff 已按分析结论弃置还原。可疑方向重排：ANE 缺失（前摄专用模型）、capture 建立期、Metal 着色器、GDC 契约。
- **GPU 配速 ✅ 初步**：内核仓库 `a07712d8`（纯 compute 大 commit 分片+深度 1 节流）在 b5r3 生效，51 条 yield 行；桌面翻页补测 109.7fps/92ms+ 为零，与 b5r1 基线持平无回归。出片后缺口对照待专门测量。
- **fence 打点就绪**：内核 `340bee5c`（tl:F 入口行、tl:X 失败行带 retired/last）编译通过未上机，下轮内核候选，判别 respawn 机制用。
- **观测手段教训**：`VM detected` 两行是 INFO 级，oslogwatch 看不到属预期；桌面翻页脚本两轮在 Photos 内无效执行（截图签名相同发现），驱动脚本需确定性回桌面手段。

## 5. 提交清单

内核：`dd5ca201`（vmm 按进程应答）、`a07712d8`（compute 分片配速）、`340bee5c`（fence 打点）。userland：`f3a3d4e`（对焦元数据取值）、`950e7eb`（编码链打点）、`7a84913`（tl:t 修复）。分析文档：`out/goal-1124/batch5/` 下 ane-close/espresso-status/zresult-semantics/front-xf20-contract/fence-wait-probe/fence-respawn/photonic-gpu-plan/text-layout-cost/afstatus-semantics/af-metadata-fix。

## 6. 结构性发现：espresso 模型权重被 Apple 发货剥离

b5r3 的 io_error 反编译排查（`out/goal-1124/batch5/espresso-ioerror.md`）把嫌疑从 IOSurface 语义（已排除：拷贝路径不检查 lock 返回值、内存持续映射）转向模型文件读取。rootfs 全量盘点（`out/goal-1124/batch5/stripped-weights.md`）坐实：**93 个 espresso 条目缺 portable weights，只发 `.H18.espresso.hwx` ANE 预编译件**；err105 的 backbone（`mubb_md7/md8`）连 portable net/shape 都不存在，只有 `H18.bundle` 编译件。被剥清单恰与 mediaanalysisd 人脸/场景管线（SCL、facerec×2、landmarksflow、torso×3、pet×2、shotflow、anst）逐项重合。这解释了 macOS VM 照片分析从不工作的公开现象：CPU 回退代码路径存在，但模型资产不在系统里。

含义：CPU 回退方向本身正确，但 iOS 资产内无解，weights 必须外部来源。首选路径=macOS 26.6.2 x86_64 安装包（Intel 无 ANE 必发 portable 权重，URL 实测有效），hwx 逆向还原为第二路径（权重重排/交织，成本高）。获取与版本核对进行中；`mubb_md7/md8` 在 macOS 侧的形态决定 U8 方向生死。

## 7. 权重获取与部署路径（b5r4 后）

macOS 26.6.2 x86_64 安装包（18.4GB，自研分段下载 9.9 分钟）提取核对完成（`out/goal-1124/batch5/macos-weights-verdict.md`）：**U8 方向闭环可行**。iOS 未剥的 12 个 Vision weights 与 macOS 同名文件逐字节一致率 12/12——Apple 对同版本模型跨平台发位相同权重。93 条被剥清单中 26 条 net 逐字节一致可直接部署；err105 链关键模型（facerec、SceneNet v5 共享权重、VisionCore 全套）均可恢复。**生死项 mubb_md7/md8 backbone 在 macOS 以便携 mlmodelc（MIL+完整权重）存在**，输出张量名与 iOS H18.e5 内嵌字符串逐一吻合。

部署设计（`weights-deployment.md`）结论：Vision/场景/人脸权重属纯文件补位零争议，进行中；backbone 有架构障碍——iOS MediaAnalysis 硬编码 `precompiled=1` 无回退，便携 MIL 路径是活代码但 backbone 到不了。候选零分歧路径：macOS/iOS Espresso 均含 jit 平台编译能力（e5 manifest 编译命令原含 jit 目标但不分发），**离线把 mlmodelc 编译成 jit/CPU 平台 e5 产物部署为预编译件则运行时零改动**——可行性调研进行中。相机侧注意：全部 27 个 ImagingNetworks（deep_fusion/deep_transfer/nightmode 全系）同样只发编译件且 macOS 不存在同款，相机增强功能权重来源是更难的开放问题。

## 8. 出片后缺口归因修正（b5r4 测量推翻 GPU 假说）

`post-capture-gap-v2.md`：99/108ms 缺口在 PhotonicEngine GPU 链开始**之前**封账，GPU 配速从原理上无法影响它。主嫌疑改为两段约 100ms 静帧 CPU 渲染（24 片 USER_INTERACTIVE dispatch_apply 与预览渲染争 CPU）；编码段 2.7s 内平均帧处理升至 17.2ms。下一步先加逐帧采集/阶段日志再定修复（QoS 降级/限宽/合并双渲染候选）。

## 9. 方向与对焦修复

对焦：b5r4 真机验证通过（见第 5 节提交清单）。方向链（`camera-orientation.md`）：U19 前摄=像素域 180° 与 CMCapture 装机补偿双重叠加；U9=静帧 ExifOrientation=6 硬编码。userland `f1e6d74` 修复实现（帧传感器原生交付、DeviceOrientation 接通、对照开关保留），b5r5 真机验证进行中。

## 10. b5r6 与性能线三项落地

b5r6 出片后打点采集（`kernel-12377-flipwd5-b5r6/RESULTS.md`）：峰值帧间隔 4/4 由 W 段（等帧）主导且复发于闪光帧下一帧——**用户态 CPU 争抢对峰值不成立**，缺口落在内核捕获路径（CAMIOC_CAPTURE 内串行曝光 I2C 写+镜头步进+帧等待）。b5r4 的 60ms 间隙结案=闪光测光保持。下一步：内核侧 W 分解打点或零成本实验（无闪光快门对照）。

性能修复两项入库：内核 `14a4dbf3`（提交深度等待目标快照固定——连锁重估缺陷修复 + WriteRead 四族打点 tl:D/d/L/S/I）、`a20bd189`（shader pipeline 进程内收割+预热，手势卡顿 air 侧 22% 的修复）。内核 `7bcfcd0b`（绑定挂载前置两补丁）已注册 flipwd6。归因文档：`kernel-submit-blocking.md`（饱和窗机制坐实、手势窗头号嫌疑=统计块持锁 IOLog）、`p-phase-attribution.md`（GPU 翻译层 44%+UI 对象图 39%）、`shader-compile-offpath.md`（预热机制设计与苹果 pipelinelib 对照）。

## 11. 权重部署通路定案：绑定挂载免写系统卷

`weights-deploy-channel.md`：md1 辅助盘体积排除（余量不足 100MB vs 需求 411MB）；**bindfs+合成条目通路成立**——内核补丁仅两处一行级（已入库），暂存 /private/var（oem push/sftp 现存通道），绑定在 launchd 前完成时序安全。mubb 编译 harness 端到端打通（`e5-compile-harness.md`）：md7/md8×jit/universal×双入口 8 组合全编译成功且本机真实执行数值互证，jit 产物为部署首选（263MB、main_video 26ms）；universal 是合法编译目标、加载无清单平台校验、部署纯增量与 H18 无竞争。

## 12. 绑定部署实现与前摄安装角（b5r6 后）

用户实测定案前摄预览顺时针错 90°：MG `FrontCameraRotationForISP=270` 是 iPhone18,3 装机值，与 K90 物理安装角不符；turned 开/关差 180° 两端都不对，正确修正在 90/270 自由度。覆盖实现进行中（硬件描述修正语义）。

权重绑定部署实现入库（userland `b685dac`、顶层 `9ec72c8`）：init 启动段 `bind_weights()` 在 restore_var 后、launchd 前执行，22 文件+2 目录共 24 条清单按尺寸校验，单条失败记账继续。annsh 新增 mv 内建（119 字节命令行限制下分片写入的两阶段落位所需）。push-weights.py 写入通道就绪，423MB 推送已先行上设备（与镜像验证解耦，幂等可重跑）。

b5r7 组合轮变量清单：flipwd6 内核 + 权重绑定首验（L0 探针→全量）+ MG 前摄安装角候选试值 + 无闪光快门对照（出片后缺口）+ 提交修复/shader 预热/对焦/方向回归。

## 13. 权重推送完成与 b5r7 组合轮（进行中）

权重暂存 423.4MB 全部就位（sftp 约一分钟 6~7MB/s，verify 32/32 尺寸匹配）。通路事实：USB fastboot 通道约 1.1MB/s 且当前启动态设备 annsh 无 mv 内建（新镜像自愈）；push-weights 的 mv 校验已改目录正面确认尺寸（工作树未提交）。sshd 留存作快通道（192.168.1.185）。

安装角覆盖三层就绪：内核 frontcamrot= 启动参数、userland MGGetSInt32Answer interpose+缓存 watcher、mg_test 可查设备树路径。候选序 180（预测正确）→0→90，代数推导见 front-mg-rotation.md。

b5r7 组合轮验证项：绑定 24 条计数、mediaanalysisd err105/ZRESULT 判据、安装角三值试拍、无闪光快门对照（出片后 W 段）、tl:D/d/L/S/I 首采+手势回归。git 历史已按阶段归并（顶层 18→7、内核 12→6、userland 11→8，内容逐字节一致，备份分支 backup-pre-squash-1125）。

## 14. 前摄安装角定案 180（文字靶标终验）

b5r7 截图矩阵因设备移动无法远程定案，改用文字靶标机器可判终验：用户持书于前摄，远程依次写 /private/var/tmp/annibale_front_cam_rotation_isp 四值并重启相机截图。结果单调旋转族：270 侧躺（故障态）、**180 横平正立（正确）**、0 倒立、90 族内另侧。证据 rotlive-f{90,180,0}.png 与 rotlive-front-base.png（270 基线）。代数含义：donor iPhone18,3 设备树 270 与 K90 物理安装角差 90°，与用户顺时针错 90° 实测吻合。设备已恢复 180。待办：mkidentity 源头固化 180（实验文件退役）、成片方向链随 -16808 修复回归、front-mg-rotation.md 的候选序预测（180 居首）实证正确但旋转方向推导符号需按实测复核。

b5r7 其他结论：权重绑定机制端到端成立 10/24（APFS_SYNTH_MAX 64 余量仅 10，flipwd7 已放大 128 并注册，反汇编实证 5 字节差异）；mediaanalysisd 失败点后移（err102/Scene_Scenenet 新形态）；无闪光快门峰值不消失（闪光作案否定，指向渲染抢占）；shader 预热写入侧断头调查中；Wi-Fi 未入网原因待查。 已根因修复：打包手抄参数串漏 wifi_mac，fw-wifi/mac 默认文件机制因文件缺失未生效；已重建该文件（gitignored）。

## 15. b5r8：权重 24/24 全量绑定落地，失败点移入执行期

flipwd7（APFS_SYNTH_MAX 128）生效：启动日志 `24 entries: 24 bound, 0 failed`，mubb universal.bundle 完整目录树设备侧可见。mediaanalysisd 失败形态显著变化：`Espresso::handle_ex_plan status=-2` io_error 本轮零行（权重装载层打通的方向性证据），SceneNet 与 Vision Code=9 消失；残留 `E5RT op failed`×60、`Empty embedding results`，err105 缓增、ZRESULT/ZASSET 仍为 0。`<private>` 脱敏遮住执行期失败细节，明文抓取列为下一跳。

前摄安装角 180 源头固化（loader 默认值，frontcamrot= 保留覆盖）首轮回归：启动日志两处 `front-cam-rotation-isp 180 (K90 mounting angle)`，覆盖文件本 boot 从未存在，预览截图房间端正。开放点：mg_test（MGCopyAnswer）读回 270 与设备树 180 分层不一致，相机链（MGGetSInt32Answer）行为正确，功能层面以实测为准。手势回归：静默窗翻页/控制中心/设置三组 92ms+ 全零，此前「92ms+ every 1.4s」坐实为启动 tour 混淆。shader harvest 目录意外已有文件增长（var.skel 修复未进本轮；推测曾有 root 进程建立过目录后持留），写入侧机制可用的实证但来路未定位，记开放点。

## 16. b5r9：oslog 明文解锁，E5RT getattrlist EINVAL 判决

oslogwatch 私有字节补丁生效（首行 `oslog: trace privacy byte set; private payloads serialize`），mediaanalysisd 明文首捕。失败链闭合为两条严格 1:1 交替日志：`E5RT op failed: getattrlist failed with error = 22`×54 + `Invalid Function Argument: handle is NULL`×54（级联）。`Error loading file:`/`Error mapping file:`/`handle_ex_plan` 全部零行——**权重文件读不进的 io_error 假设证伪**。失败位置锁定在 `e5rt_execution_stream_operation_create_precompiled_compute_operation_with_options` 算子创建的文件系统探测环节（getattrlist 返 EINVAL），早于 Espresso plan 执行；消费端确实按绑定路径找到算子包并进入创建流程。相机链旁证：`BWE5InferenceProvider.m:263` 同一创建 API 同样失败——**该文件系统探测缺口同时阻塞 mediaanalysisd 与相机两条链，修一处解两链**。候选根因两个：合成绑定条目不支承 getattrlist 部分属性位，或 HackiOS APFS 对该属性组合返 EINVAL；idalib 反编译与内核属性位审计双路调查已派（`e5rt-getattrlist-reversing.md`/`kernel-getattrlist-audit.md` 产出中）。SQLite：err105 64→66（两张新片进失败积压），ZRESULT/ZASSET 仍 0。

其余：Wi-Fi 恢复入网（192.168.1.185 DHCP 新租约），sshd/sftp 快通道实测 11MB/s 逐字节一致，后续轮次取证速率量级提升。shader harvest 双路通畅：写入 `128 pipelines recorded`、回放 SpringBoard 70+cameracaptured 205+backboardd 342 replayed，`cannot mkdir` 零计数——预热机制端到端成立。新开放点：SpringBoard/backboardd 启动早期各重启一次（pid 29→313、38→309，wifid termination 回调+ReportCrash CPU 增长），死因未定位。前摄方向复核通过；明暗场帧率测量连续两轮缺手段（需注入或外设计帧）。遗留：boot_a 未刷写（临时 fastboot boot 载体），t1 Photos.sqlite 未拉取（可用 sftp 快通道补）。

## 17. getattrlist 根因闭合与 flipwd8（提交待 b5r10 验证）

双路独立调查（`e5rt-getattrlist-reversing.md` + `kernel-getattrlist-audit.md`）收敛同一根因：E5RT `FileUpdateIdentifier` 用 `ATTR_CMN_CRTIME|GEN_COUNT|FILEID` 三元组做编译缓存指纹，自研 APFS 磁盘层 write_generation_counter 早已解析（apfs_lib.c:1545）但 `apfs_vnop_getattr` 漏报 va_write_gencount；E5RT 未请求 RETURNED_ATTRS，VFS 对未支承属性统一返 EINVAL——无 fallback 直穿 API 边界，全系统 E5RT 加载全灭（batteryintelligenced 同日志命中）。修复=`apfs_vnops.c` 一行 VATTR_RETURN（ramfs 已有同款先例），bindfs 与部署形态零改动。已构建注册 **flipwd8**（反汇编实证：+5 指令，write_gen 装入 vap 并置 supported bit42）。b5r10 判决轮进行中：err105/ZRESULT/ZASSET 三判据+相机链同 API 观察。附带：`boot-respawn/BRIEF.md`——backboardd 早期死亡=SIGSEGV 于 libannibaleair（Mesa/Freedreno 资源路径，16 份历史报告两族签名），SpringBoard 系被 RunningBoard 级联；崩溃报告管道被 1357 份积存 .ips 配额堵塞（b5r10 起预清）。write_gen 写路径递增与 VOL_CAP 声明列为可选补强未做。

## 18. compute device types 掩码归因（相机链分层结论）

b5r10 与 flipwd8 判决（`kernel-12377-flipwd8-b5r10/RESULTS.md`）：getattrlist EINVAL 与 handle NULL 各 54→0，err105 积压 66→59（7 资产完成处理移出失败表），W/H 武装 7 窗口×15 行验证，崩溃报告通道疏通。ZRESULT 未填充——房间测试片无人脸属合理空，人脸样片终验专项进行中。

`e5rt-compute-units.md`：`none allowed compute device types` 唯一宿主是 Quagga 推理 flags mapper（usesANEOnly 跳过 CPU/GPU；mask 位 1=CPU 2=GPU 4=ANE）。分层结论：**mediaanalysisd 的生死在我们部署的 universal/jit CPU 产物**（isPrecompiled=1 分支无 mask 覆盖，stock H18-only bundle 必空；离线编译 CpuInference/JitCall 产物才有活路——这正是已部署形态，终验看人脸样片轮）；**相机链 smartcam/personsemantics 只有 H18/hwx 编译件且无 MIL/espresso.net 可重编译源资产**，CPU 化无料，长期解只有 hwx 逆变换路线（3~10 人日判决见 hwx-weights-feasibility.md）——前摄 -16808 若与此同源，同受其制。air-crash-families.md：backboardd 早期死亡=内核 BO 分配失败+用户态 Mesa/Freedreno 全链无 NULL 防护（0020 补丁部分防护无降级策略且可能未入构建树），死亡延迟到首用时刻；修复优先级与错误码拆分取证配套已列，批 6 立项。

## 19. U8 核心链终验通过（人脸样片，b5r10 运行态）

`kernel-12377-flipwd8-b5r10/face-test/RESULTS-face-test.md`：**场景 embedding 链端到端打通且拿到内容级证据**——3 张人脸肖像覆盖注入 err105 待重试资产后全部完成处理：err105 行移除、embedding v77/scene v100 版本列写入、ScenePrint 768 维 float32 blob 全部 L2=1 单位化，人脸片两两余弦 0.990-0.995 vs 房间对照 0.696-0.704（网络真实读取图像内容），4 个场景 ID 人脸片独有。成功信号持久化在 **Photos.sqlite 侧**而非 MediaAnalysis.sqlite——zresult-validation.sql 判据看错库，待修正；实际 b5r10 轮内持久化已开始。全窗 E5RT/getattrlist/mmap 错误扫描全零，APFS 修复在真实推理负载下持续成立。**U8 从「系统里不存在分析能力」转为「核心链已验证运行」**，批 5 主线目标达成。

残留分层：(a) 人脸检测未通——ZDETECTEDFACE 全库 0，FaceAnalyzer 报 `Failed to analyze resource`，头号嫌疑 `NV12 plane requires Metal format` 拒绝（Vision 人脸链直喂 NV12 surface 进 Metal 推理，embedding 链经 vImage 转 ARGB 绕行所以幸存）——驱动侧输入格式缺口，批 6 调查。(b) 调度发现：dasd 空闲维护在本平台不起作用，err105 重试须由图库变更触发（相机新拍后数分钟内爆发处理），后续轮次设计须遵守。(c) `ZMEDIAANALYSISTIMESTAMP` 语义未解。

## 20. NV12 格式修复与批 6 开局（未提交待验）

`nv12-metal-format.md`：488 行拒绝归因闭合——VideoToolbox VTMetalTransferSession 对 NV12 plane 请求 R32Uint(plane0)/R16Uint(plane1) 整数别名直绑，`ann_surface_plane` 校验缺口在自家翻译层。修复实施完成未提交：`annibaledrawable.m` +8/-3 行接受两别名（view_bpp 语义：R32Uint texel=4 luma 字节、R16Uint texel=1 个 CbCr element），主机红绿 harness 与 arm64e 编译通过。b5r11 终验轮进行中：拒绝行清零、import 行出现、ZDETECTEDFACE/ZFACEANALYSISVERSION 非零为人脸链打通判据；触发须用图库变更（dasd 空闲调度不起作用）。批 6 排队：libannibaleair 崩溃族治理（air-crash-families.md §7 四级修复+错误码拆分取证）、前摄 -16808 定因、U21 偏色待用户中性面、zresult-validation.sql 口径修正（成功信号在 Photos.sqlite 侧）。

## 21. NV12 修复验证与 -16808 起源闭合（批 5 收官）

b5r11/b5r12 两轮迭代（`kernel-12377-flipwd8-b5r11`/`b5r12` RESULTS）：NV12 修复真机验证通过——plane1 的 `VTMTSComputeFunction1x1` R32Uint 变体补收后拒绝行 52→0，转换输出探针从全零到 nz/mx/sum 非零，FaceAnalyzer 输入级错误消失。内核 `39f6d210` 入库。**人脸端到端终验差最后一公里**：人脸分析只在「新导入资产」上运行，无人值守的导入通道缺失（覆盖注入不触发重处理、拍屏物理不可行），注入通道建设已立项。新调度事实：mediaanalysisd 空闲期完全停摆，后续轮次无需长等待窗。

-16808 起源闭合（`front-16808-origin.md`）：非编码器问题——产生点是 BWPhotonicEngineNode 的 coordinator 建立缓存失败态，「0->15」的 15=IDC（智能畸变校正）控制器建立阶段，致命机理是 `LowResPersonSegmentationMask` 推理产物缺失（人物分割掩码为 ANE-only 编译资产），与 compute-units 锁为同根；前摄 FrontSuperWide 畸变校正必需、后摄跳过所以不对称。另发现 IDC 插件只带 g18p 预编译归档而 AnnibaleMetal 不支持 native binary archives（潜在独立问题）。**前摄拍照修复依赖 hwx 逆变换线**——项目已启动（里程碑 1：双有模型逐位还原验证）。

air 崩溃族取证前置完成：0020 补丁审计虚惊（分析树过时，构建树实际已含）；错误码拆分入库（内核 `94659627` + userland `21c1bb4`）——三子原因（wired memory/8192 句柄/IOVA 跨度）下次失败时可直接读日志区分。已知构建系统缺口：annibale-drm 复制不进 build-air.py 校验机制，手工同步中。
