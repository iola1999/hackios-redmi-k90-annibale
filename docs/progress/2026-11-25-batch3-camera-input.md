# 批 3：前摄满帧、U6 坐实、手势死锁类停顿消除

## 用户问题状态变化

- **U6 地图黑色建筑：已修复**。根因 `ground_fragment` 的 styleColor 在
  `[[buffer(21)]]` 超出 freedreno 的 16 个 UBO 槽读零。真机核验建筑足迹
  浅灰、近黑像素 0.17%（旧现场 2.9%），6 分钟无停转无闪退
  （`kernel-12377-flipwd-u6verify`）。
- **U15 滑动卡顿：已大幅改善**。flip 看门狗内核下 47+28 次手势零死锁型
  停顿，手指移动期 50ms+ 间隔 0 次、首帧 p50 6~16ms（基线 194~411ms）。
  残留停顿归 SpringBoard 主 runloop 长 turn（140~187ms）内的手势处理与
  文本排版（`tl:t` 采样落 CTLineCreateWithAttributedString、
  CFLocaleCopyPreferredLanguages、Gestures 栈），CA bracket 仅 28~31µs；
  GPU fence、IOMFB、CA commit 锁均排除主因。
- **U19 前摄帧率：已修复**。NV12 软解马赛克 NEON 化（userland `c97f3a3`），
  渲染 34ms→10.7~13.8ms，明暗场实测均 30fps 满帧。方向与暗光噪点未决。
- **U8 图库空白：网格已修复**；精选集「固定」行瓷贴仍纯黑
  （round8 坐实），封面纹理路径待查。
- **U21**：快门停顿已修（批 2）；偏色判别未决——round8 输出侧 Cb/Cr
  读数不足以定层，需插件输入侧打点。

## 意外发现（下批候选）

- **Misconfigured Device 告警**：`/System/Library/EventTimingProfiles/
  D22.Default.plist` 缺失（round8 截图实证）。UIKit 事件时序配置缺文件，
  与输入事件时序的关系未评估，先查 cryptex/rootfs 该目录实际内容。
- `tl:l` 存在 8~25s 打印侧间歇（frame 计数照走）——分析时须以 frame
  增量判真伪。
- `tl:t` 采样的 `<redacted>` 帧来自 dyld shared cache 符号表；修法是
  采样侧补 image+offset 输出。

## 提交

- userland `c97f3a3`：软解马赛克与 NV12 写出 NEON 加速
- 证据：`kernel-12377-flipwd-round6/7/8`、`kernel-12377-flipwd-u6verify`
- 分析底稿（不入库）：`out/goal-1124/batch3/`（gesture-flipwd.md、
  p-segment.md、front-cam-fps.md、u6-maps.md、func-backlog.md）

## 批 4 轮 1 追加（2026-11-25，详见 evidence/kernel-12377-flipwd-b4r1）

- **EventTimingProfiles 根因坐实**：os.dmg 本就只发 V57 配置；批 3 手工
  打包漏 `--identity v57 --memsize`（cycle.py 会传），设备以 D22AP
  （iPhone X 身份）运行，UIKit 找 D22 文件不得而告警。批 3 测量身份的
  影响面未评估；批 4 轮 2 重打正确身份验证。
- **U8 根因深掘**：瓷贴黑因合集为空——48 个相册 ZCACHEDCOUNT 全 0、
  Z_33ASSETS 0 行。mediaanalysisd 每天多次崩溃于
  `MPSNeuralNetwork/MPSKey_Compile`（神经网络 Metal 着色器在本机 GPU
  栈编译失败），分析产物从未生成；photolibraryd 在 iOS 26 已并入
  assetsd。
- **U21**：输入侧无 Cb/Cr 打点；旁证 WB 增益 B≈2.84~2.88 异常大。
  待加 isp_stats mean[R,G,B] 打点。
