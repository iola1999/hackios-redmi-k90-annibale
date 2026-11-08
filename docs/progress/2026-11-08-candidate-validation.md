# 2026-11-08 候选真机验证与音频服务崩溃定位

本轮接手[暂停交接](2026-11-08-handoff.md)中的两个候选，按每轮一个变量完成三轮真机检查。原始日志、截图、逐帧结果和设备命令保存在本地忽略目录 `docs/progress/evidence/storage-boot-device-1108/phase10/`，进度队列见[总账](../plan/2026-10-23-tracking.md)。

## 1. 候选与验证范围

| 轮次 | 唯一变化 | 结果 |
|---|---|---|
| `video-fragment` | format 500 的 UV 片元纹理计数与 Metal device 生命周期修复 | 四组 GPU 检查通过；Safari 合成与媒体服务仍未通过 |
| `audio-timeout` | 首次 DSP 状态查询期限改为 5 秒，保留既有 HAL 修复 | 独立 AudioQueue 启动和 PCM 提交成功；期限与成功的因果关系尚未证明 |
| `video-bunny` | 同一视频候选，测试媒体换成含 AAC 音轨的 `bunny.mp4` | WebKit 仍报媒体错误 3；原生 AVPlayer 输出正确视频后遇到 `audiomxd` SIGTRAP |

三个候选均使用临时启动，`boot_a` 保留原已验证版本。视频服务仅绑定本机测试端口，本轮结束后已关闭。

## 2. 视频片元与释放检查

候选 `05f00ae3…` 的四组 compute 与 fragment 输出逐项一致，覆盖视频/全范围和 BT.601/BT.709 组合。每组命令状态均为 completed，`errors=0`，探针在 157 毫秒内以退出码 0 结束，未再出现退出阶段 signal 11。

无音轨的原始 H.264 页面仍能取得一个解码帧，canvas 中彩条颜色正确，但原生 video 元素随后报媒体错误 3，播放时间停在 0。该结果确认 format 500 的片元颜色与释放问题已修复，网页的后续解码、媒体服务和视频层呈现仍需分别验收。

`bunny.mp4` 含 60 秒 H.264 视频和 AAC 立体声音轨。WebKit 播放同样在约 30 秒等待后报媒体错误 3，没有取得首帧。测试页已增加轮次标识，并通过真实点击原生播放控件启动非静音播放。

原生 AVPlayer 对同一 Bunny URL 的检查覆盖解码像素、播放时钟和媒体服务状态：

- 输出 117 帧 NV12，640×360，逐帧 `pixel_error=0`，累计有效像素数据 40,435,200 字节。
- 播放时钟前进到约 9.681 秒，随后 player 与 item 均返回 `AVErrorMediaServicesWereReset`（`-11819`）。
- 日志紧邻记录 `audiomxd` SIGTRAP；`AudioConverterSe` 的 SIGKILL 是 launchd 在宿主退出后清理进程作用域服务。
- 原生视频解码在崩溃前正常，带音频播放的当前阻塞转为 `audiomxd` 约 30 秒周期崩溃及其媒体服务复位。

## 3. 独立 AudioQueue 与 DSP

候选 `3a4df005…` 的首次 `GET_SPF_STATE` 在 255 微秒内收到真实回复，扬声器与播放图完成 OPEN、配置、PREPARE 和 START。原生会话探针覆盖会话激活、队列启动和直接设备写入：

- AVAudioSession category 与 activation 成功。
- `AudioQueueStart=0`，144000/144000 帧交给原生队列，HAL 记录 playing。
- 直接写 `/dev/redwood-audio` 的对照也完成 144000 帧。

实际回复远低于原 250 毫秒期限，本轮不能证明 5 秒期限消除了旧偶发超时，也不能把 AudioQueue 成功单独归因于期限变化。可以确认的是，本次 DSP 初始化成功后，旧 `-66681` 没有复现。

现有 PCM 计数只在完整校验 `OP_WRITE_DONE` 的周期地址、map handle 和状态字后递增。下一轮增加低频完成摘要，要求 sent/done 相等、done 覆盖至少 150 个音频周期且没有 `PCM completion failed`；实际听感仍留人工验收。

## 4. 下一轮测法调整

`rwsh dump audiomxd` 后远程命令队列发生阻塞，后续请求没有完成。本轮已停止该入口，下一轮使用 `usertrap=1 applog=1` 获取异常 PC、寄存器和返回地址，并优先读取 ReportCrash 原始报告。

组件静态复核发现，上一轮热加载后仍停锁屏，退出码 0 的触摸脚本不能证明解锁成功。下一轮改用冷启动采集，以 `locked_after=0` 或 `sb26: boot unlock done` 加主屏截图作为前置条件，再比较首个组件命中帧的输入、pre/out 和附件。

长帧分析确定先补硬件刷新时刻与逐 draw GPU 时间线，再决定 shader、command buffer 或写回路径的修改。FairPlay 诊断先观察非空 iterator 后的真实 Open 和 selector，未还原的操作返回实际不支持，不生成签名结果。

## 5. 设备与交接状态

最后一轮已正常执行 `oem stop`，loader 为 `product=xnuloader`、`result=returned 1444016 0`，构建号为 `b935d2e5…`。UFS 在途请求为 0，控制器已归还；驻留启动卷已清为 `ramdisk-state=idle 0 0 300000000`。

本轮没有改写 `boot_a`，其中仍保留 `fa407241…` 版本。临时 HTTP 服务已停止，后续候选和验证脚本分别保存在 `out/audioqueue-start-1108/`、`out/widget-render-1108/` 与本轮 evidence 目录。
