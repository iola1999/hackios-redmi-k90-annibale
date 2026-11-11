# 后台应用切回前台排查（2026-11-12）

本批处理[系统待办 S5](../backlog/system.md)，接续[系统契约 §6](../analysis/2026-11-12-system-contracts.md#6-应用前台切换)。已有记录显示，同一应用复用开机后台进程后未显示界面，结束进程再启动则可见；当前缺少失败现场的 RunningBoard assertion 和 FrontBoard scene 回应，根因尚未确认。

## 1. 目标与范围

验收为同一测试应用连续前后台切换后出现正确可见的 scene。失败记录需定位首个未完成步骤，覆盖图标或原生打开请求、进程唤醒、scene 创建／更新、应用回应和内容提交。

- 先核查现有诊断、23G90 原生框架调用及本仓实现，再决定必要修复。
- 同一次开机对照复用后台进程与结束后重新启动，分别保存阶段日志、身份和截图。
- 保留现有应用与用户数据；身份异常先记录原值，未经定位不重装、不清理容器或注册库。
- S10 文件身份修复按[渲染核查 §4](../analysis/2026-11-12-rendering-runtime.md#4-apfs-文件身份)独立验证，当前结果尚未确认其与 S5 的因果关系。

## 2. 分工与输入

| 工作 | 内容 | 交付 |
|---|---|---|
| 注册与路径 | LS／FBS application identity、System／User 分类、Bundle／主程序／Data 路径 | 实际 API、静态契约与只读查询范围 |
| 原生生命周期 | RunningBoard foreground／resume assertion、FrontBoard scene 请求及应用回应 | 函数与调用关系、首个缺失响应的判据 |
| 诊断工具 | 现有 `ios-state.py`、层树、AX、线程和阶段日志 | 采集缺口、可复现工具错误及宿主验证 |
| 集成核查 | 内核挂起／恢复、版本与产物关系 | 目标编译、对照计划、结果与提交 |

原始输出保存在 Git 忽略的本地调试目录，分析结论记录于[应用前台切换核查](../analysis/2026-11-12-app-foreground.md)。多媒体、S9 和 G2 候选各自保留；本批不修改 AIR 或当前设备队列。

## 3. 设备对照安排

设备由协调任务确认的唯一 device 成员操作。本批先完成离线工作，再交付只读诊断和同轮对照步骤，合并进适合的设备批次。

每个阶段记录目标 PID、启动身份、主程序路径、可查询的挂起状态、assertion／scene 日志和截图。结束后重新启动会产生新 PID，`ui-health` 等进程稳定性检查按阶段执行。scene 的 `valid`、`active`、`content`、`layers` 和 `clientProcess` 可先复用 `notify com.annibale.layers.all`；这些状态与画面共同核对。

### 3.1 候选与采集入口

诊断产物集中在 Git 忽略的 `hackios-xnu-userland/out/s5-foreground-delivery/device/`。`annsh` 与 `app-identity` 安装到辅助盘的 `bin/`，scene 诊断随 `libannibale-sb26.dylib` 构建。`package.py` 的 `PAYLOAD_PROGRAMS` 可加入两个程序，保留原有列表；最终轮次清单需核对实际打包的版本、签名与摘要。

完整设备候选已按 heap 基线独立装配，逐路径和载荷检查见[核查记录 §8](../analysis/2026-11-12-app-foreground.md#8-独立诊断候选与固定采集)。诊断轮保留基线内核与 AIR，新增日志和查询会增加开销，S9 性能测量使用独立配置。

`ROUND`、`PID`、`BUNDLE_ID` 由执行者填写。以下命令经现有 `rsh.py` 通道执行，设备操作仍由唯一 device 成员负责：

```sh
python3 tools/k90auto/ios-state.py "$ROUND" --process "$PID" --threads "$PID"
python3 tools/k90auto/rsh.py "$ROUND" /annibale/bin/app-identity "$BUNDLE_ID"
python3 tools/k90auto/rsh.py "$ROUND" notify com.annibale.layers.all
```

采集前后保存主机单调时间、对应日志区间与截图。核对层树的 `begin`、`end`、`(cut)` 及 getter 未知值。无 scene 的后台实例可能没有层树记录，需要原生日志覆盖进程启动完成、assertion 和恢复调用。

### 3.2 首轮固定采集

先用一次设置打开复核现有黑底画面。冻结脚本与配套工具，固定截图解释器路径并记录环境版本后交给唯一 device，采集期间无需聊天确认。基线检查 AX 图标与坐标，点击后按 +0.5、+3、+10 秒调用截图，再采一次进程、线程、AX 和 layers。请求总时限 150 秒，传输失败或超时向原 runner 请求停止，具体顺序与覆盖范围见[核查记录 §8.2](../analysis/2026-11-12-app-foreground.md#82-一次设置打开的采集范围)。

先实际查看原图和诊断记录，再确定下一批动作；多任务另排批次。点击前没有后台进程就只覆盖设置冷启动尝试，进程是否创建仍需 after PID 与日志确认。后台复用的完整验收继续按下节执行。

首轮已完成：+3 秒、+10 秒截图显示设置首页，进程与前台 scene 对照成功。缺少原后台实例，历史复用场景继续待验；具体采样窗口与诊断缺口见[核查记录 §9](../analysis/2026-11-12-app-foreground.md#9-设置冷启动的固定采集结果)。

### 3.3 同一次开机的对照

| 阶段 | 操作 | 成功条件或失败记录 |
|---|---|---|
| 后台实例 P1 | 确认开机后台启动来源，记录身份及状态，再点击同一图标 | PID 是否保持、`finishedLaunching`、assertion／resume、scene 请求与回应、画面 |
| P1 任务卡片 | 保存图标激活后的现场，再进入多任务并选择同一应用卡片 | 卡片是否存在、内容／遮挡／裁剪，以及选择后 P1 和 scene 是否保持 |
| 重新启动 P2 | 保存 P1 现场并确认应用无未保存编辑后，仅结束 P1；确认退出，再点击同一图标 | 新 PID、相同注册与主程序路径、scene 建立或激活结果 |
| 连续切换 | P2 正常显示后，连续两次退到主屏再点击同一图标，并通过多任务卡片激活该应用 | 每次都有正确可见 scene，记录 PID、响应完成及内容提交 |

每个阶段单独运行 `ui-health.py`。`trollstorehelper open` 若用于对照，单独记录该触发方式；其返回值来自 `openApplicationWithBundleID:`，实际可见性仍由 scene 和画面确认。

多任务观察先确认画面实际进入任务切换器，并核对卡片对应的应用与 scene。逐张打开截图原图或局部，分别记录卡片内容、遮挡、裁剪和激活后完整界面；scene／AX、像素探针与日志用于定位，画面结论单独记录。短暂异常未被采到的部分保留为未覆盖或未复现，并核对采样时刻后调整下一批。

同轮保留进入应用、进入多任务、横向切换卡片、点选卡片和返回主屏的实际画面。loader 截图通过 USB 分块读取 framebuffer，动态画面的跨帧读取影响尚待确认；短暂问题按需使用已有有界录屏，并记录 layer 0 来源、降采样配置与采集开销，具体要求沿用[协作手册](debugging-and-collaboration.md)。

出现失败就保存首个未完成步骤的相关信息。原生日志覆盖不足后，先据已获取的 PID、identity、scene ID 与 transaction ID 决定需要增加的诊断，再安排下一批。

原生 USB 接管继续按[USB 核查](../analysis/2026-11-12-usb-debugging.md)暂缓。本批完成后清理已被最终产物替代的临时文件，保留未结问题的输入、基线、日志及可复现资料。
