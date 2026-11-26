# 批 7：用户可感知功能主线（2026-11-27）

批 6 收官时按用户指示主线转向性能功耗与用户可感知功能，相机线封存为离线穿插。本批开局状态：pre-0024 air 基线稳定（b5r16/b5r18 两轮满载验证），0024 系库的双重销毁机制诊断链推进中。

## 1. 离线清点判决（11-26 深夜至 27 凌晨）

- U6 地图、U7 Safari 均已在历史批次修复，本轮为证据链复核确认，见批 6 文档 §12。
- ALS 根因三层断点闭合，修复链实施入库（内核 GCC 偏移修正+bitbang 采集链+诊断探针套件、userland input26 注册链、cycle.py 固化 sensors_hw_i2c），待真机诊断轮。
- 录音链前提修正：DMIC0 单声道采集链 11-24 已端到端验收（record_test.wav 实测信号、环路 89.5dB），只剩语音备忘录 App 级验收未做，可搭车组合轮。工作文档 `out/goal-1124/batch7/audio-recording-chain.md`。
- powerd 电源链健康（svcprobe 连续三轮 control-stable-visible），功耗测量前提具备。

## 2. b5r18 四判决（11-27 下午，pre-0024 基线稳定轮 41 分钟）

- **Safari 收尾通过**：P1-P4 全过——进程组存活、三页面渲染完整、JS 交互正常、Wi-Fi 关开后 4 秒回连且 bing.com 完整渲染。单点观察：知乎链接点按后白屏一次无崩溃记录，判非平台缺陷；MobileSafari 一次 ExcUserFault（is_simulated、进程未死）归档备查。U7 修复判定成立。
- **地图回归通过**：8 次冷启干净、分级缩放瓦片全渲染、近黑像素 0.134%~0.152%、卫星图完整、10 分钟静置无进程更替、CrashReporter 零 Maps 条目。U6 判据全部满足。新观察项：模式选择器四预览缩略图持续纯黑（疑 MapKit 缩略渲染缺口，低优先）；3D/深色模式未测记入偏差。
- **人脸链阴性复现**：4 个新资产五拍全零推进，mediaanalysisd 全开机 CPU 仅 0.16 秒——本轮无 b5r16 式 catchup 突发（差异变量：本轮无相机阶段、屏幕全程常亮）。证据偏向稳态电源门控候选；决定性实验（熄屏+充电窗口）列为后续轮次候选。口径修正：iOS 26 无 ZPROCESSINGSTATUS 表，ZMADREQUEST 零行不能推出通知未发。
- **控制中心 159ms 停顿为测量伪影**：`tl: f` 口径实为 GPU 等待行而非翻帧时间戳；改 `tl: v done` 口径后两轮转场本体最长单帧 24~40ms 均顺滑，大间隔全落在转场结束后的静态停帧尾部。性能线此项闭合。

方法学修正入库：帧间隔统计一律用 `tl: v done` 帧到位口径（tools/frames.py 标准）；face-analyze.py 的 schema 已按 iOS 26 修正（旧版 ZASSET 列名查询静默失败，回读 b5r16 前结论时注意）。

## 3. air 双重销毁诊断链状态

- b5r17 定案：ring 双重销毁（32 实例 refcnt -1+RINGDEAD），引用配对失衡，野写排除，GPU 死亡为下游并发症。
- 静态审计收敛：全部可枚举路径配平、与上游逐行一致；失衡在 pre-0024 同样潜伏（0024 只改触发覆盖），修复目标是失衡机制本身。三种形态（重复移交/无探针递归 flush/batch cache 时序）可证伪枚举，工作文档 `out/goal-1124/batch7/ring-double-destroy-location.md`。
- 0027 探针库就绪（per-ring 8 槽引用转移史，主机测试三场景通过），`libannibaleair-0027.dylib` 已交付。一轮切分三形态直出失衡点 site id。

## 4. b5r19 组合规划

0027 诊断库 + flipwd10 内核（ALS 修复链）+ `sensors_probe=1` boot-args。ALS 探针在内核层执行不受用户态风暴影响，0027 风暴取证与 ALS 测量同轮互不妨碍；若意外稳定则加测 ALS 用户态链路。磁盘警示：evidence+out+kernel/out 约 77G 超门槛，批 7 中段需安排归档清理。

## 5. b5r19 判决（11-27 傍晚，flipwd10+0027 诊断轮）

**双重销毁风暴未触发**：boot1 稳定 35 分钟+、boot3 复稳 6 分钟，370 万行日志违例零命中；锁屏合成+控制中心+翻页手势的触发面已有实质覆盖。两种解释未分：观测者效应（历史存储改变分配布局/时序压制潜伏缺陷）或触发面不足（boot1 停锁屏无相机激励）。区分设计：0026 复跑统计或主屏深度激励对照。

**新回归——flipwd10 在 uptime 11.7~11.9s 系统性切断 fastboot USB 采收通道**（三次启动一致，flipwd9 同通道 41 分钟无此现象）。ALS 探针输出结构性不可采收（P0a 固定 10 秒采样结果必然落在死亡窗口）。根因调查进行中，头号嫌疑：bitbang TLMM 写穿或供电轨投票副作用（boot2 无 probe 同死，主路径必有此行为）。

**ALS 用户态链路阻断在镜像陈旧**：input26 修复与 svcprobe 均未入镜像（镜像未经重建），重建已派。内核层注入链验证通过（sysctl 150→500→150 写读一致）。内核传感器驱动桥接报告已出（gls6151/stk6a2x 附着、校准值读出、SE10/SE12 clk=0 确认总线空闲）。

方法学入库：手动复跑必须 kern.bootargs 活体核验（boot2 外来参数事故）；日志环跨软重启有地层残留，考古不可信只有实时采收可靠；flipwd9/10 的 kern.version 不可区分，指纹用独有横幅。

## 6. b5r20 判决（11-27 夜，flipwd9+0027 对照轮）

**犯罪现场到手**：风暴开机 10 秒内复现，17 起双重销毁历史完全一致 `create1→subref2→subdel1→emitdel0→emitdel-1`——第五个 del 全为 site 7 emitdel，发射/unref 系对同一 ring 双重放权，形态甲坐实、形态乙排除（`flush inside emit` 零行）、违例 ring 非 tile 族。修复分析收尾中。

**USB 对照成立**：flipwd9 采收通道全程 607 秒存活，坐实 USB 死亡为 flipwd10 内核线回归。bisection 排期：flipwd10+sensors_hw_i2c=0 分离硬件接入与驱动存在性，并入后续轮次。

**b5r19 稳定 paradox 重读**：同一 0027 库在 flipwd9 完整复现风暴——0027 不普遍压制缺陷；b5r19 稳定更可能来自内核时序差异或触发面未覆盖，严格归因需 flipwd10 同载荷对照。新谜题记档：缺陷在用户态库而触发依赖内核版本——与 batch cache 时序因子（形态丙）相容，触发是时序敏感的确定逻辑。

**物料链修复验证**：input26 修复版与 svcprobe 首次真正入载荷（sha256 双核验），svcprobe 第四轮 control-stable-visible。userland 镜像重建+打包链重跑流程闭环。

## 7. b5r21 判决（11-27 夜，USB bisection 短轮）

alive60：移除 `sensors_hw_i2c` 后 USB 采收通道全程 180 秒零中断（465/465 探针），11.7s 窗口密集通过。USB 死亡由 sensors 硬件接入路径（bitbang/桥接/重试）引起，驱动存在性排除。轨投票在 b5r19/21 无 sensors_rails boot-arg 时按代码路径不发生——TLMM MMIO 写入为头号嫌疑，与相机 bitbang 的差异点：sensors 在开机早期执行、每 2 秒重试持续冲击、另配置 IRQ GPIO163/35 输入。相机 bitbang 同 TLMM 操作在相机轮次不伤 USB，差异在时机/频率/引脚集合。

**新观测优先项**：用户实测开机到桌面时亮度轻微抖动（21:55:00~02 精确时间窗，正值 b5r21 采收启动内）——日志关联分析进行中。候选方向：input26 ALS 注册修复首次真正生效致自动亮度首次激活、显示管线初始化交接、面板模式切换。

## 8. 亮度抖动机制闭合（11-27 夜，b5r21 采收直读）

用户报告窗口墙钟 21:55:00~02 对齐内核 uptime 28.3~30.5 秒。机制：开机亮度冻结 5 秒后，用户操作触发自动亮度启用（21:54:55.5 `BKAmbientLightSensorEnableAutoBrightness userInteractedWithUI:YES`），控制环以占位常数 150 lux 为输入开始收敛——亮度以约 100 毫秒步进、每步约 0.0004 的幅度连走约 60 步，从 0.161 降到 0.135，中途 21:54:55.41 有一次方向反复；用户窗口正处收敛尾部，21:55:00.311 收敛完成后稳定。抖动根因与 ALS 恒 150 同族：输入无物理意义+步进施加可见。主修复即 sensors 硬件接入线；中间处置（input26 停发占位数据）已决策实施，细节见 als-implementation 后续节。分析全文 `out/goal-1124/batch7/boot-brightness-wobble.md`。

## 9. 性能线开工（用户指定优先：翻页+Safari 多标签）

离线盘点产出 `out/goal-1124/batch7/perf-gesture-measurement-design.md`。关键存量结论：桌面翻页全部 ≥50ms 间隔在此前批次已定到 backboardd 交付迟（P 段），P 内构成 GPU 翻译层 44%+UI 对象图 39%；落定段整节拍阶梯三候选（CA 自适应降生产/真实停顿/测量伪影）未分；ltr 方向 iconservicesagent GPU 提交与卡顿无相关性。Safari 多标签无任何历史测量，候选排序 MobileSafari 主线程快照解码+布局居首，测量核心为首次/重复对照。触摸翻倍异常定性为轮次级瞬态（b5r16 出现、b5r18 同内核零翻倍），根因未定位，以输入完整性门禁规避。b5r22 测量轮已按设计放行。

## 10. ring 修复链：崩溃点精确定位与修复设计

`out/goal-1124/batch7/emitdel-double-release-fix.md`：反汇编证据钉死崩溃在**首次发射**（fd6_draw.cc:614），循环漏清 num_groups 嫌疑排除（源码重置完好）；向量乙（跨发射陈旧引用）被证据链封死——emit 结构体为每次 draw 的栈对象。收敛为向量甲：同一次首次发射内同一流式环指针进入两个 take 槽，第一次消费销毁后第二次 del 出 -1。修复三层：主修复入组点同环重复入组时 fd_ringbuffer_ref 补齐所有权（约 10 行，正确路径零行为变化）；加固层消费即清槽+清零 num_groups（3 行）；探针 sharpen 记录 group_id+pass 序号（0028 库）。实施进行中。

## 11. b5r22 判决（11-28 凌晨，flipwd9+pre-0024 性能测量轮）

用户点名两场景的首次有效测量。注入翻倍伪影排除（32/32 门禁通过）。**翻页落定段大停顿全部为生产侧静默**：216~225ms 巨档窗内 SpringBoard 主线程零长忙样本、零 GPU/fence/拷贝/面板长尾，迟到在 backboardd SwapBegin 启动之前；rtl 序列后首次 ltr 巨档确定性复现（与 b5r16 的 219ms 签名一致）。`ir3 wait` 与翻页窗零共现、温控排除。g2-rtl-1 的 10Hz 段存两种读法未分：动画结束后静态重绘（cpufreq 源码注释记载静止桌面约 10Hz 重绘）vs boost 失效低速自持——下一轮补画面运动真值+cpufreq 逐次换挡日志+巨档窗线程栈三连 dump+dl_log。Safari 多标签手势触发坐标未校准通过（y0.945 上滑未可靠触发），总览界面本身渲染完整。离线分解全文 `out/goal-1124/batch7/b5r22-offline-decomposition.md`。

## 12. ring 修复链收口与亮度抖动复核更正

**0028 修复入库**（userland `e908b11`）：入组点同环重复入组补偿引用+消费清槽+group/pass 归属探针，主机 harness 全过、反汇编抽查通过、产物 `libannibaleair-0028.dylib` 就绪。共享通道具体位置仍离线不可定，0028 真机轮的 duplicate-take 归属行一轮即可钉死。**亮度抖动复核更正**：内核侧分解（`brightness-wobble-2155.md`）推翻初版两判断——ALS 输入链未参与（input26 注册零行）、高 uptime 行属本次启动；抖动主因核定为**背光输出层多来源竞争**（背光服务属性与 IOMFBBrightnessLevel 两路写同一 dcs.want，精度相位不同致物理写值交替）。修复方向：单写来源仲裁+bl_trace 逐笔追踪。初版文档已标注取代关系。

## 13. 批 7 收尾状态

真机三轮上限已用（b5r20/21/22）。下一批组成候选：b5r23 = 0028 真机验证（duplicate-take 归属+风暴是否消除）+ 性能补采 instrumentation（cpufreq 换挡日志、巨档窗线程栈、dl_log、运动真值）+ Safari 多标签触发坐标研究。磁盘 evidence+out+kernel/out 约 80G 超门槛待清。

## 14. b5r23 物料就绪过程（11-28）

五项性能补采 instrumentation 入库：cpufreq 逐次换挡日志（tl: cf 带三位 boost 状态）、flow-gap 线程 dump（40Hz 以上帧流缺口 60/160ms 两次，sysctl 武装——巨档实测起点在抬手后 615ms，定时方案被反证改为事件驱动）、dl_log 时间戳、tdsym 符号化脚本、QuartzCore 全零 CAFrameRateRange 语义复核（dl_max=1 hook 语义正确）。背光单写来源仲裁入库：bl_arb 默认开，服务首个正亮度请求后唯一写面板，早期 framebuffer 兜底、关屏锁存；b5r21 数据回放预测抖动窗变为单调不增零反向。Safari 触发设计落盘：首选 drag 胶囊中心（0.565,0.932)→(0.565,0.30) 216ms+停留，flick 根因修正已实施入库，双击 `•••` 备选。内核 `b86440fd`、userland `157a861`，flipwd11 构建与镜像重建进行中。

## 15. b5r23 判决（11-28 凌晨，flipwd11 组合轮）

**0028 未修复双重释放，但归属数据到手**：首发即风暴，hist 新形态 `create1→subdel0→emitdel-1`——ring 只有创建引用，submit 删到 0 后 emit 再删到 -1；`fd state duplicate take` 触发 111 次（缺陷路径确实经入组点）但 double destroy 仍 5 起；emitdel 带 group 28 pass 14/34——**group 28 的具体状态族是下一轮分析的钥匙**。pre-0024 降级全程稳定，输入门禁 28/28。

**性能归因决定性推进**：flow-gap dump 8/8 命中真实停顿窗（首次 60~102ms、二次 203~209ms 进窗）。窗内 SpringBoard 主线程在 GSEventRunModal 等待、backboardd CA 线程在 runloop 等待、input26 在 read——**全部空闲等待，无 Metal 编码/GPU 提交/内核等待链，且 CPU 仍在 2.4~2.8GHz**。cpufreq 低速自持假设（H1）死亡：不是没频率，是根本没人来生产。209ms 巨档连静止 10Hz 重绘节奏都中断，指向 CA 动画→静止模式切换本身的空洞。剩余关键测量：运动真值（页面是否还在动）。

**Safari 总览首次有效测量**：trigger=drag-hold 校准成功。首次进入 drag 段最长 90.3ms、settle 65ms；重复进入 drag 70~91ms、settle 90~97ms——**重复进入无预热收益**，首用管线假设不成立，成本在每次进入的生产侧。用户感知的卡顿有定量坐实。

**背光仲裁部分有效**：mfb 写 117 笔全阻断、svc 253 笔全通过，但面板 DBV 仍交替（166 笔升 86 降 79）——**残余交替在 svc 路径内部**：CoreBrightness 对服务本身也混用 NitsPhysical 整数档与 brightness-nits 定点两类键形。下轮迭代：svc 路径内去重键形。

**sensors 线重大发现**：`sensors_hw_i2c=1` 组合连续三次在 QRTR/MHI 门铃写路径 panic——**sensors 探测用 GPIO16/17，而 GPIO16 是 PCIe 电源序列的 WCN7850 卡 enable**。引脚冲突实锤，这同时极可能是 b5r19 USB 11.7s 死亡的机制（bitbang 每 2 秒重试持续扳动 Wi-Fi enable）。传感器 SE12 引脚分配需要重新核对硬件依据。

**环境噪声记录**：extensionkitservice/iconservicesagent/pkd registration stuck 判定，测量环境存在系统服务注册退化。

## 16. 离线判决四连（11-28）

**运动真值离线判定**（`out/goal-1124/batch7/settle-gap-motion-truth.md`）：100~225ms 空洞分两类，不能合并裁决。晚期巨档（b5r23 g1-rtl-1 209ms、b5r22 pair26/36 225/216ms）与稳定 10Hz 空洞高置信度为静止重绘——巨档开始前 250ms 以上已进入静止基线命令形态（1478/1492 words），空洞内零生产提交、线程全等待，应从用户可见慢帧统计剔除。

**真正的用户可见卡顿收窄到活跃 settle 空洞**：b5r23 g1-ltr-1 的 141/149ms 空洞全部处于同一 SpringBoard 主 RunLoop 458ms 长轮内，空洞内动画提交持续，阻塞形态为 kevent→libdispatch→RenderBox→QuartzCore 链、IOKit/DRM map/command write、`rwa_texture_create` mutex 等待、`rwa_render_clear`，单笔 commit 418 耗时 112ms。

H1 cpufreq 死（空洞始于 2.4GHz 以上）、H3 无支持。下轮最小补采设计完成：SBIconScrollView transform/contentOffset 采样 hook（实施中），分析口径改 active/static/transition 三分类。

**GPIO16 冲突定案**（`out/goal-1124/batch7/gpio16-conflict-investigation.md`）：sensors 引脚分配错误在 bus_instance→SE 推导第一环（「减一」映射纯猜测被反证），GPIO16/17 电气性属于 WCN7850，无共存空间。新主导假设：bus_instance 即全局 SE 编号——gls6151 在 SE13=GPIO20/21、stk6a2x 在 SE11=GPIO12/13（SE10-13 在厂商 DT 中作为连续四整块 disabled，传感器岛总线池格局）。行动项：sensors_hw_i2c 与 Wi-Fi 永不同轮（已执行）；下轮零风险扫描 gpio12/13/20/21 的 0x31/0x47 ACK 定案真实引脚；离线补证三项（DTB 引脚普查、persist 全条目分布、MiCode dtsi）。

**0028 失败归因**（`out/goal-1124/batch7/0028-failure-analysis.md`）：group 28=FD6_GROUP_PRIM_MODE_SYSMEM 确证。核心新发现——受害环 subref 缺失是真实未加：5 起 double destroy 全部 `create1→subdel0→emitdel-1`（安装引用若执行过替换后应为 1）、9 起 in-slot 违规全部 refcnt 0 首销毁。主导假设：fd_submit_sp_new_ringbuffer 顺序中，安装 ref 执行时 flags 未初始化（slab 自由链垃圾），hackios 特有 sink 跳过逻辑读垃圾 flags bit5 约半数误判 sink 跳 ref——上游 ref 无条件，此偏离是 hackios 引入。

duplicate take 成因结案为 slab 复用别名（0xe0 步长同页族、构建位序相邻组对），补偿在所有权链下游救不了上游缺失。0029 方向：flags 前移初始化或安装路径无条件 ref，反汇编验证已派出。

**背光 svc 去重入库**（内核 `d3e9b7c8`）：b5r23 数据分析证实两类键形是同一控制迭代成对下发（对内中位 64µs、111/112 对满足 NP=floor(bn)），抖动机制为突发首写锁存整数 DBV 下一帧再写精确值的系统性锯齿。实现：16.16 写即时应用并刷新参考，整数写匹配 floor(参考) 则抑制、不匹配挂起 2ms 等精确写（`bl_dedup` 默认 1）；回放 b5r23 序列方向反转 208→2 且残余与 millinits 流自身一致。

熄屏安全：关屏写取消挂起并使参考失效。蓝牙脏文件归属清理（内核 `15bc378b`，H4 startup event 重组修复+主机测试，flipwd11 已含）。flipwd12 构建中。

## 17. suballoc 安装引用缺失验证定案（11-28）

反汇编+源码双重证实（`out/goal-1124/batch7/suballoc-ref-verification.md`）：安装 ref 确实被 is_sink 条件跳过（patch 0024 把上游无条件递增改为条件递增，libannibaleair-0028 反汇编 tbz bit5 分支直接证据）；flags 写入确实晚于安装 ref（上游顺序相同，上游安全只因 ref 不读 flags）。**假设机制有一处修正**：slab 自由链不覆盖对象体（next/owner/magic 在对象起始地址之前的 24 字节元素头内）——残留真正来源是首用元素的 malloc 垃圾（bit5 约半数置位），复用世代若前世代完成 init 则 flags 合法、ref 必执行、确定性安全；池结构（子池随 submit 建销、页面 orphan 后跨 submit 零复用）放大首用占比。0029 修复定案为 flags 前移一行（refcnt=1 相邻处、安装路径之前），行为与上游逐点一致；init 失败路径的 slab_free 偏离一并处理。探针全保留+新增一次性安装点断言。
