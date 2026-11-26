# 批 6：出片后停顿终局归因与人脸链注入通道（2026-11-26）

批 6 开局批次。主线三条：出片后停顿三周调查的终局归因（`tl: C` 内核分段打点+蜂群治理验证）、人脸检测端到端注入通道建设、hwx 权重逆变换项目推进。轮次证据在 `evidence/k90auto/kernel-12377-flipwd9-b5r13/`（不入库），结论摘录如下。

## 1. b5r13 载荷与打点验证

- 内核 flipwd9（sha256 前缀 `18c2aa37`）：捕获 ioctl 分段打点 `tl: C`（`1ba74c75`）+ GPU 分配拒绝错误码拆分（`94659627`）；userland `d121e8d`（蜂群治理+photoimport）。
- `tl: C` 机制首次上机完全成立：5021 行数据全部满足自洽三式（`exp+foc+wait+adv≈tot`、`del≥adv`、`wait≥spin` 均零违例），15fps 下逐帧级数据密度。
- 镜头步进成本直接证实：多步移动 `foc n/(n−1)×10.8ms` 精确符合 GT9764V 步进模型，对焦期峰值 101ms 与此同源。
- 内核 diff 逐行复核为纯测量，不构成相机路径回归变量。

## 2. 出片后停顿终局归因（三周调查收尾）

快门窗峰值主导段是 W（内核捕获 ioctl），W 内分层定罪：

- **采集线程被渲染/编码工作抢占**：捕获窗内 `wait−spin` 缺口 22~43ms（窗外基线 6~10ms），与用户态 H 膨胀帧级同起同落。
- **槽位推进缓存冲刷竞争**：`adv` 从 348µs 基线膨胀到 544~1052µs（最极端 2848µs 在编码写出阶段）。
- **寄存器串行与镜头步进贡献为零**：这不是测量失败，是机制事实，见 §3。

峰值复现条件：b5r6 的 83~104ms 是 30fps 现象——15fps 帧长 66.7ms 吸收全部扰动（b5r13 最大帧间隔 73.5ms 仅比基线多 7ms）。复现需明亮场景 30fps 轮次，暗室 torch（125mA）撑不到 30fps。

## 3. 闪光机制事实（本移植）

b5r13 pass3 真闪光序列（torch 保持熄灭）直读：

- 本移植闪光=torch 常量点亮暖机（210ms），非脉冲；捕获帧沿用预览曝光（`exp 0/0 foc 0/0` 全程），不重测光、不同步速度、不步进镜头。
- torch 常亮与闪光同源（都是 torch 1000/1000）互斥，闪光测量轮必须让 torch 保持熄灭（pass3 手法已验证可行）。
- AutoFocusDuringPreFlash 在 CAF 已收敛时不产生镜头动作。
- 快捷开关只有 Auto↔Off 两态，暗室 Auto 即可触发，可作标准手法。

## 4. 蜂群治理端到端验证通过

静帧渲染 dispatch_apply 从 24 片 USER_INTERACTIVE 降为 ncpu/2 片 QOS_CLASS_UTILITY（纯调度层改动，算法零改动），b5r13 四次捕获对照：

| 组别 | 实现 | demosaic | 渲染窗 H max |
|---|---|---|---|
| 治理组 ×3 | 2 pieces UTILITY | 138~145ms | 22.8ms |
| tmp 文件对照 | 24 pieces USER_INTERACTIVE | 87ms | 21.5ms |

- 开关通道（`/private/var/tmp/annibale_still_swarm` 按每张渲染读取）、pieces 计算、QoS 降级全部按设计工作。
- 代价符合预期：单张渲染墙钟约 1.6~1.7×，接近半宽并行理论 2×，占全捕获管线比例小。
- 治理组 H max 22.8ms vs b5r6 的 56.8ms；15fps 下 H 口径区分度有限，内核维度（spin-gap）方向一致但统计强度不足，30fps 轮次才能给出干净 A/B。
- 注意设备测试轮 boot-args 带 `cpus=4`，实际只有 4 核（pieces=2 由此而来）。

## 5. format-5 崩溃（新发现，已入 backlog M15）

`stream: format 5` 构图后 cameracaptured 立即抛 `NSInternalInconsistencyException 'Unknown pixel format ()'` 连环 abort。触发链：设备静置 4 分钟自动锁屏 → 锁屏右滑误开相机 → 随机滑动驱进高帧率/全分辨率格式族。属潜在 userland 相机设备 bug 被意外触发，非 flipwd9 回归（恢复后同内核同 dylib 完全正常）。首要嫌疑 `csu_resolveFormatIndexForNamedStreamFormat` 格式表映射，详见[多媒体待办 M15](../backlog/multimedia.md)。

驱动教训入库：静置 4 分钟自动锁屏，驱动必须先解锁；锁屏右滑会误开相机。

## 6. 人脸链注入通道两轮判决（photoimport）

- 首轮：裸 Mach-O 被 `PHPhotosErrorDomain 3311 AccessUserDenied` 拒绝，根因报告 `photoimport-3311.md`（kern_minimac 容器外 adhoc 二进制本就带 CS_PLATFORM_BINARY，剩余变量是 bundle identity/usage key/用户域）。
- 修复为最小 `.app`（userland `d62974f`：platform-application+application-identifier+no-container+两条 usage description）。
- 二轮复测：probe 身份读数逐项命中期望（platform-binary yes、cs flags `0x36004001`、entitlement 实读完整、bundle id 正确），但 root 与 mobile(501) 两身份仍 3311。决定性证据：拒绝不出客户端进程——连打 50 次 probe tccd CPU 零累积、TCC.db 48 行零变化、读回 denied 而非 notDetermined。tracev3 残片存在 `System session daemon must not initiate XPC to the User session: endpoint = com.apple.tccd (No such process)`。
- 新头号嫌疑：bootstrap 会话域——sshd 子树在 system session，tccd 是 user session 服务，XPC 路由不到，客户端库在 XPC 失败时合成 denied。mobile 对照轮用的 runas 通道只复制 uid/gid 不复制 bootstrap 会话域，不能证伪用户域假设。TCC preflight 反编译与用户会话执行通道设计离线进行中。
- 附加读数：cs flags 中 CS_ADHOC 未置位（尽管宿主 codesign 报 adhoc）、CS_DEBUGGED 置位（无调试器附加），两项指向 minimac 处置细节待核对，不影响主结论。
- **三轮终局（11-26，TCC 通道闭合）**：反编译钉死合成点——`tcc_authorization_preflight_with_endpoint` 在 XPC 失败后结果容器保持初始值 0（TCC 空间即 denied），PLSC/Photos 三张映射表全链闭合；stock iOS 26.6.2 本不含 launchctl，命令行会话切换无原生入口。PhotoImport 改双形态 UIApplication（无参=SpringBoard 拉起、带参=CLI 对照组），经 TrollStore IPA 安装（install-ipa.py 修复权限集合并——原逻辑整体覆盖重签会丢 tcc.allow/platform-application）。真机判决：用户会话内 `add-only 3 authorized, read-write 3 authorized`，wiki1-3 三张人脸样片 3/3 入库零失败；同一二进制 CLI 对照组同 cs flags 同 entitlement 读回 denied——会话维度对照闭合，唯一变量是出生会话。
- **新阻塞层（人脸链最后一公里）**：3 张人脸片入库后 10 分钟五拍数据库，`ZDETECTEDFACE`/`ZPERSON` 全零、`ZPROCESSINGSTATUS` 冻结、`ZLASTATTEMPTDATE` 停在 11-25——mediaanalysisd 全天零分析尝试。头号嫌疑：powerd 电源属性链断裂（`ExternalConnected=yes` 但 `powerd lists no power source`），dasd 类后台调度电源门控永不满足。该缺陷影响全系统电源门控后台任务，归口排查中。
- 平台事实入库：图标点击是唯一实证拉起通道；`trollstorehelper open` 对 containers 应用一律拒绝（system session 向用户会话发 XPC 同限）；`import` 动作须用 inbox 通道（`stringByAppendingPathComponent` 拼接陷阱）。

## 7. hwx 逆变换线（批 6 长期投资）

前摄 -16808 与相机智能模型（smartcam/personsemantics）只有 H18 ANE 预编译资产、无 CPU 可编译源，唯一解锁路线。进展里程碑：

- M1-M3：hwx 权重逆变换路线验证成立（tap_to_box 18/18 卷积逐字节还原→CPU bundle→e5rt 加载 rc=0）。
- M8：nightmode 4 变体各 16/16、deep_fusion 28/28 结构提取+编译+加载全通；deep_fusion 5x5/4x4 层数值顺序未闭合。
- M9：变换链深度超预期——pixel-unshuffle fusion、large-kernel decomposition、稀疏压缩层叠，逐层逆推成本高。
- M10：**本地编译预言机打通**——Espresso AOT driver harness 可把已知 MIL 常量卷积权重编译出真 H18 `model.hwx`（关键参数 `--e5-compute-units ane --e5-require-ane-resident=strict`），逆变换校验从逆向猜解变为正向对照实验。U_2/U_3 oracle stride 已与 deep_fusion target 匹配；4x4/5x5 lane 内权重以字节交换的 halfword 形式出现。
- M11：deep_fusion 全 28 层数值级闭合——K 是输入通道、C 是输出通道的语义修正后 oracle 与 target stride 全对齐，重编译 H18 kernel segment 2.44MB 逐字节一致，CPU bundle 加载 rc=0。逆变换工具链证可产出功能等价模型。
- M12-M13  pivot 前摄目标：personsemantics-preview-lowfps 定位（63 卷积中 47 个 quantized LUT），BWE5 部署判决**有条件 GO**——相机链无 compute-mask 策略层、可直消费 CPU 制品；macOS 27.0 自带 portable 三联（Apple 分发了 portable quantized blob，绕开 LUT 逆变换）；smartcam 不参与掩码生产不阻塞主线；H18 标签由 chip-id 0x8150 强制，universal 回退在 K90 不可达。
- M14-M15 数值链闭合：classic CPU 端到端推理数值正确（coco 人物图 person max 0.984）；e5/ classic 分叉定位到 **espressoc 序列化 bug 丢失 5 个 deconvolution 的 blob_biases**，补齐后 e5 CPU 输出 49152/49152 元素与 classic 逐字节一致。H18 标签 CPU 部署候选 bundle 已产出（`personsemantics-m15/deploy-candidate/`，主机 e5rt create 全 rc=0）；quantized LUT 反量化公式与 dense 化工具闭合互证。剩余缺口：inputdirect surface 输入执行验证、输出 fp32 tensor 与相机链掩码格式的衔接需真机复核。

工作文档在 `out/goal-1124/batch6/hwx-inversion-m*.md`（不入库）。

## 8. 残余问题与下轮输入

- 30fps 闪光峰值复现需亮室轮次（白天或明亮环境）。
- 蜂群治理内核维度统计强度待 30fps 更长渲染窗。
- 手势回归 b5r13 被锁屏事故污染未覆盖，下轮先解锁再跑。
- ALS 读数疑似不更新（lux 恒 150）。
- OSLOG 缺口：设备无 `/usr/bin/log`，uuidtext 为空导致宿主 log show 无法解析 tracev3，需解决落盘或写解析器。
- 人脸链：TCC 通道已闭合（§6），终验阻塞在 mediaanalysisd 调度——powerd 电源属性链排查中。
- 前摄 -16808：personsemantics 部署候选就绪，部署通路需 overlay 绑定扩展（现行机制只覆盖新路径），b5r14 候选。
- libannibaleair 崩溃族修复（§7.1/7.2）实现完成编译通过，待真机回归。

## 9. b5r14 判决（11-26 深夜）

组合轮四变量（personsemantics CPU overlay、air 0024、format-5 修复、battery_test publish 探针）上机，设备开机后 SpringBoard/backboardd 重启风暴、黑屏转圈未达交互态，-16808 主判决与手势回归未执行。已闭合的三项读数：

- **overlay 部署通路成立**：init 汇总 `25 entries: 25 bound, 0 failed`，personsemantics H18.bundle 成功覆盖系统卷既有路径，远端哈希抽查逐字节一致。部署机制不再构成阻塞。
- **powerd 探针定案 `transport-or-serve`**：`IOPSCreatePowerSource` 返回 `0xe00002cd`，MIG 服务不可达。离线根因分析闭合静态链每一环（plist→launchd.plist 缓存 555 job→powerd init 首句 checkin），launchd lookup 可见性语义不要求 checkin 成功——服务在系统域运行态真实缺席，断点锁定 launchd 运行态端点导入/失效路径。svcprobe 分项探针设计就绪。
- **重启风暴离线定性**：停滞栈符号化落在合并清理销毁非末尾提交撕开 ring 池、slab 自由链遍历 2.5s+；backboardd 窗口内 11/11 实例留有 corpse，SpringBoard 的 `Failed to create remote render context` abort 是失渲染服务后的级联死亡。0024 降级路径全程未触发（`fd bo new failed` 零行），嫌疑在成功路径改动与移植移除的两条上游合并防护上限（`nr_bos>30`/`deferred_cmds>128`）的组合，三候选待带探针的 0025 air 库一轮区分。

b5r15 变量规划：0025 探针库（slab 遍历上限转决定性崩溃、池未死即销毁捕获、flush 后使用捕获）+ svcprobe + personsemantics overlay 不变复测 -16808。工作文档 `out/goal-1124/batch7/b5r14-respawn-storm.md` 与 `powerd-mig-root-cause.md`（不入库）。

## 10. b5r15 判决与主线转向（11-26 深夜）

b5r15（0025 探针库）读数：

- **崩溃机制收窄**：`slab accounting overrun` 在 backboardd 三实例与 cameracaptured 命中——ring slab 自由链遍历超万节点、元数据损坏；cameracaptured 链经 `cleanup_submit`（0024 改动点）。双重归还/UAF/外部写坏未分离，`fd merge bos cap hit` 证明高 BO 合并不是必要条件。内核侧 `external BO health check failed` 致 submissions closed。关联干净：崩溃两轮均 0024 系库、稳定轮均 pre-0024 库。
- **powerd 判决反转**：svcprobe 两趟 `control-visible`（uptime 2s/123s 均可解析、四 sibling 全在、flags8 一致），battery_test publish 转 `publish-path-works` 且 baseline 电池在列——b5r14 的 transport-or-serve 是该轮风暴的连带产物，电源链本身完好，mediaanalysisd 电源门控理论需修正。
- overlay 25/25 再证、staging 36/36 复核通过。

**主线转向决策**：相机链（-16808、人脸链终验）唯一阻塞是 0024 系库的开机风暴，机制审计离线进行；b5r16 用 pre-0024 旧库恢复稳定态一次取三个拖欠判决。相机之外的用户可感知问题（ALS 恒 150、U21 偏色待用户实验、功耗与性能残留）并行排期。工作文档 `out/goal-1124/batch7/`（不入库）。

## 11. b5r16 判决与 slab 审计收口（11-27 凌晨）

b5r16 回退 pre-0024 air 库，四判决如下。

- 稳定性通过：overlay 在场、相机压测、mediaanalysisd GPU 突发与手势全程零崩溃，0024/0025 系库确认为风暴唯一来源。
- 手势首个有效基线整体顺滑：最长翻页间隔 37~58ms，唯一明显停顿为控制中心消退回家转场 159ms。
- -16808 仍复现但失败点上移：`BWE5InferenceProvider` 的 `e5rt_execution_stream_operation_create_precompiled_compute_operation_with_options` 创建失败（m:263）经 Smart Camera Inference Node -31710 到配置 0->15 级联；`LowResPersonSegmentationMask` 零行即 personsemantics 从未被消费，overlay 必要但不充分。
- 人脸链 mediaanalysisd 历史性首次唤醒：embedding 非零资产 47→51 精确对应 4 张入库片；人脸检测仍零产出，与相机同属 E5RT 推理创建失败族；新资产排期未启动，两候选未分离。

slab 审计收口（`out/goal-1124/batch7/slab-corruption-mechanism.md`）：五嫌疑方向全部排除或降级，0024 内无常驻损坏逻辑、并发彻底排除（单递归锁串行化），剩余解释为移植基线潜在缺陷+受害者位移或未插桩路径动态引用失衡——0026 定为诊断轮，决定性探针是 slab_free 推入时双重释放检测（犯罪现场直抓栈）。

**相机线状态封存**：-16808 剩余链为 smartcam/E5RT 算子创建层（BWE5 m:263 待反编译），人脸链待新资产排期候选分离，air 修复链待 0026 诊断轮。三线均有明确下一步但成本高昂，按用户指示主线转向性能功耗与其余用户可感知问题，相机线以离线反编译与诊断轮穿插推进。

## 12. 主线转向后的首轮清点（11-27）

按用户指示主线转向性能功耗与用户可感知功能，首轮离线清点结果：

- **U7 Safari 空白**：11-21 批次已定案修复（Cryptex 嫁接链，内核 `210bf4b0`+userland `03f80d9`），Wi-Fi 关开后 Safari 加载正文在批 1 round1 已有阳性实证；剩余为多页面/JS 重交互/长时稳定收尾验证，6 个探针设计就绪可搭车任意组合轮约 10 分钟。工作文档 `out/goal-1124/batch7/u7-safari-blank.md`。
- **U6 地图色块闪退**：三独立缺陷全部已修复验收（UBO 槽 21 越界重编号、未绑定槽地址零 SMMU 故障全零 BO、深度模板空指针），均在 pre-0024 谱系；剩覆盖缺口（单轮次单地点验收后无任何轮次开过地图），回归轮设计就绪。工作文档 `out/goal-1124/batch7/u6-maps-tiles-crash.md`。
- **ALS 自动亮度**：根因三层断点闭合（boot-arg 门控未开、GCC 时钟寄存器偏移错误——附带独立 bug 必修、驱动无初始化），lux 恒 150 是编译期占位值；persist 分区 registry 实取完整（gls6151 在 I2C bus13 地址 0x31、五通道校准系数全）；修复主推 GPIO bitbang（前摄同总线已跑通的模板），注入链两行修复可先行。工作文档 `out/goal-1124/batch7/als-frozen-root-cause.md`。
- **功耗前提**：powerd 链健康（b5r15 判决反转），后台调度电源门控可满足，功耗测量可建立在可靠电源数据上。

**下一轮真机组合（b5r17 候选组成）**：0026 诊断库开机取证（slab 双重释放犯罪现场）+ ALS P0 纯测量探针（正确偏移时钟采样、引脚电平、cmd-db）+ Safari 收尾探针组 + 地图回归（分级缩放量化门槛）。userland 已入库到 `69cb8e2`（0026 探针），pre-0024 稳定基线为当前打包基线。

## 13. b5r17 判决：双重销毁坐实（11-27）

0026 诊断轮开机即风暴，但诊断目标完全达成：ring 双重销毁坐实——32 进程实例全部 `fd ring double destroy`、refcnt -1、RINGDEAD canary，引用配对失衡是损坏机制；野写方向零证据，GPU 死亡确认为下游并发症（0026 的 abort 在破坏完成前拦截）。三条触发路径（draw 发射/deferred submit 清理/blitter 拷贝）共享同一违例尾链。剩余谜题：pre-0024 稳定而 0024 系开机即崩，静态审计已证 0024 内无常驻损坏逻辑——ring 引用配对对照审查进行中。ALS/Safari/地图三组顺延至稳定轮。pre-0024 基线库已恢复，设备安全停 loader。
