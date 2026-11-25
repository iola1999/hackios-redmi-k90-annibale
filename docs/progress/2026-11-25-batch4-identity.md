# 批 4：v57 身份修正、U8/MPS 链定位（2026-11-25）

## 身份修正（轮 b4r2 已验）

批 3 手工打包漏 `--identity v57 --memsize`（cycle.py 会传，手工绕开丢），
设备以 D22AP（iPhone X 身份）运行，UIKit 找不到 D22 的
EventTimingProfiles 而弹 Misconfigured Device 告警（每个 UIKit 进程
启动各一次）。批 4 轮 2 按 cycle.py 重打后：`hw.machine=iPhone18,3`、
`hw.model=V57AP`、memsize 12G 生效，告警消除（boot 主屏、Photos 冷启、
30s 对照均无）；状态栏变为 iPhone 17 布局。手势 hitch 111.2fps/单拍
96%/50ms+ 零次（round8 同档），前摄 pace 不变。**流程缺口待堵**：
make-payload.py 对 iOS 26 载荷应断言 identity/memsize 必填，或手册
写明手工打包必须照抄 cycle.py 参数。批 3 在错误身份下的测量结论
（相机/渲染类）不受影响方向，但身份敏感读数需按新身份复测。

## U8 根因链（轮 b4r1）

瓷贴黑因合集为空：48 相册 ZCACHEDCOUNT 全 0、Z_33ASSETS 0 行。
底层 mediaanalysisd 每天崩溃于 `MPSNeuralNetwork/MPSKey_Compile`——
MPS 神经网络 compute pipeline 创建失败，失败层在 libannibaleair 的
AIR 前端翻译/接口整理（ir3 后端未开始）。11-24 12:47 提交的线程组
指针 phi 修复（userland `369ce48`）在 20:32 重建的 dylib 中，而最新
崩溃样本是同日 18:52——**修复上线后是否还崩无证据**，下轮查新崩溃
报告时间戳。观测缺口：`compute pipeline refused`/`AIRFAIL` 走
rw_print→stdout，mediaanalysisd 输出路径未确认，需核实 console
转发对后台守护进程生效。

## 待盯事件

轮 b4r2 相机退出瞬间 backboardd `[Render] timed out fence` 致 respawn
（38→367）+SpringBoard 重连——fence 超时各轮均有（非致命），致死
首次。单样本待观察。

## 证据

`kernel-12377-flipwd-b4r1/`（身份根因、U8 数据库取证）、
`kernel-12377-flipwd-b4r2/`（身份修正验证）。分析底稿
`out/goal-1124/batch4/mps-crash.md`（待落盘，图形已交结论）。

## 轮 b4r3 追加：MPS 修复后状态

phi 修复 dylib 上线（11-24 20:32）后零新崩溃（含 v57 身份下 b4r2 全程）；
round7 归档有 mediaanalysisd 成功创建并提交多条 MPS/CNN compute
pipeline 的正向记录。但 Photos 前台 3 分钟未触发分析负载（maps 中无
AnnibaleMetal/libannibaleair）——mediaanalysisd 按充电+空闲调度运行，
U8 合集填充留观察动作：设备充电闲置一段时间后查 ZCACHEDCOUNT 是否
开始非零。mediaanalysisd 的 fd 1/2 指向 /dev/console，`compute pipeline
refused`/`AIRFAIL` 若发生会以裸行进 console，近 24h 31 个归档轮零命中。

## 轮 b4r4~b4r6：U8 根因链逐层闭合

mediaanalysisd 分析管线的修复按层推进，每层真机验证后暴露下一层：

1. **MPS phi 编译修复正向验证**（b4r4）：GPU 神经网络推理在 v57 身份下
   首次跑通，commits/completions 42/42 errors 0，进程不再崩溃。
   但分析任务仍 err=105 line=1687 收场。
2. **宽单行 surface**（b4r4 定位、内核 `89d5f3d2` 修复、b4r5 验证）：
   Vision 把约 2.1MiB 平坦张量表示成 2162688x1 单行 L008 surface，
   `MINISURF_MAX_DIMENSION=16384` 直接拒绝。上限放开（体量由
   MINISURF_MAX_ALLOC 约束）+ 几何算术改 64 位防溢出回绕，
   b4r5 该拒绝行归零。
3. **子 surface**（b4r5 定位、内核 `4493aa42` 实现、b4r6 验证）：
   Espresso 在父张量 buffer 上建分块视图（`IOSurfaceOffset` 为父
   backing 绝对坐标、allocSize 继承父值、父子 backing 引用计数
   共享），b4r6 `CreateBufferAliasImplInvalid` 归零，GPU probe
   提交 6 对 26/26 零错误。
4. **当前层：ANE 模型加载**（b4r6 坐实）：新签名
   `ANE model load failure: createProgramInstanceForModel` +
   `Invalid Function Argument: *handle is NULL`。管线越过
   IOSurface 层到达 ANE——本平台无 ANE 设备模拟，方向待查：
   E5RT 是否有 GPU-only 回退路径，或需最小 ANE 设备模拟。
   err=105 line=1687 仍是统一出口，ZRESULT 0 行、
   ZCACHEDCOUNT 全 0、瓷贴仍黑。

U21 偏色判别（b4r4）：mean RGB 打点上真机，后摄书本/前摄天花板
稳态 correctedR/B 均 0.97~1.02 中性——sensor 输入与 AWB 排除，
偏绿签名（Cb 115 Cr 109）本轮未复现，若复现归因 LSC/CCM/NV12/GPU
链。决定性中性面实验物理受阻（设备朝向无均匀浅色面），需人工
reposition 后补跑。

出片后 62~124ms 缺口分层（离线，`out/goal-1124/batch4/post-capture-gap.md`）：
主段=cameracaptured 的 PhotonicEngine GPU 长 work（单 commit
41.7ms）压在 backboardd 合成前；修复方向排序已出。

前摄快门新缺陷（b4r5 发现，`out/goal-1124/batch4/front-encoder-16808.md`）：
前摄静帧交付成功但 `BWPhotoEncoderNode code=-16808`（CMCapture
私有域）、DCIM 无文件——前摄拍照从未验证过，属真实功能缺陷，
待补打点后定层。

其他：runloop 采样打点修复（userland `7a84913`，image+offset
先行 + 15~20ms 加密）；b4r5 第二次 backboardd respawn 样本
（Photos 退出回桌面瞬间），b4r6 未复发；打包漏 boot-args 的
失误留档警示 cycle 参数完整性。

## 证据

`kernel-12377-flipwd-b4r4/`、`kernel-12377-flipwd2-b4r5/`、
`kernel-12377-flipwd3-b4r6/`。19:01 自然分析窗复测 rows 156/157
在 b4r6 boot 内仍有效。
