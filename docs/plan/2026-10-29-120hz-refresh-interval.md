# 120 Hz 刷新档位：实现方案（2026-10-29）

## 1. 问题

桌面长期停在 60 Hz 满帧流（末帧间隔中位数 16,646 到 16,663 微秒，见[冻结征兆表](2026-10-29-freeze-symptom-table.md)）。按 upstream 的发现，渲染服务器给显示定时器定速靠 `IOMFBDisplayRefresh` 的 `displayMinRefreshInterval`；缺这个属性就退回 1/60 秒的心跳，通用 slot 301 又把最小值固定为 1/60。

## 2. 改法

驱动文件是 `hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp`，实现放在同目录的 `MiniFramebufferPacing.inc`（11-01，内核 `12377-rate1`）。

1. **boot-arg `fb_ca_hz=N` 发布属性**：`publishModes()` 末尾调用 `publish_refresh()`，属性在 `registerService()` 之前进注册表，launchd、backboardd、SpringBoard 起来时都已拿到。不设 `fb_ca_hz` 时不发布，与之前相同。
2. **单位**：`displayMinRefreshInterval`、`displayMaxRefreshInterval`、`displayRefreshStep` 以 2^-32 秒为单位（120 Hz 为 `2^32/120`），只有 `displayRefreshStepMachTime` 用 mach 时钟 tick。按 tick 填时 CoreAnimation 会把面板算成 26844 Hz（上游 hakios `0dedaec` 实测）。最小与最大间隔取同一个值，面板不变速。
3. **不覆盖 slot 301**：上游 hakios 在 iOS 16.5 上只在 `publishModes()` 里设置属性就生效。

帧率另外受应用 Info.plist 的 `CADisableMinimumFrameDurationOnPhone` 与 UIKit display link 的请求速率限制，见[上游做法](../analysis/2026-11-01-hakios-upstream-lessons.md) §3。23G90 的 QuartzCore 只在高帧率限制生效时读这个键。三项的真机轮次与分支见[验证方案](2026-11-01-rate-scaling-ir3-rounds.md) §3。

## 3. 落地顺序与前置条件

先把「属性发出去了」做成可判，再谈间隔：驱动发布时打印一行 `IOMFBDisplayRefresh: N Hz`（带 2^-32 秒与 tick 两种间隔），SpringBoard 的 `sb26: rate` 行读回 CoreAnimation 实际采用的速率与 QuartzCore 的高帧率限制状态（`inject_sb26_rate.c`）。两处打印属于改动本身，不做成可选项；否则间隔不变时分不清「没发出去」与「发出去了但没被采用」。

顺序：驱动打印 → 用户态读回比对 → 再测末帧间隔。前两步不过，第三步的读数不成立。

## 4. 验收

- 主判据：末帧间隔中位数从 16,65x 微秒降到接近 8,333 微秒，且帧号在同样时长内翻倍。
- 间隔不变时先看两处打印：驱动行缺失说明属性没有发布；驱动行在而 `UIScreen.maximumFramesPerSecond` 仍为 60，说明 CoreAnimation 没有采用；采用了而间隔不变，看 `restriction` 与 `plist_key`，再看 display link 请求的速率。
- 不把 120 Hz 当性能基线：帧间隔达标的同一轮要同时记录 `rwa draw:` 每帧绘制数与 hot ticks 分布，否则无法与 60 Hz 轮比较。

## 5. 与 `fb_hz` 的关系

`fb_hz` 只改 vsync 定时器的周期与本驱动的出帧节拍，改不到这条路径：渲染服务器的显示定时器按 `displayMinRefreshInterval` 定速，两者不同层。所以只设 `fb_hz=120` 的轮次不会出现 8.33 毫秒的帧间隔。验证轮同时设 `fb_hz=120` 与 `fb_ca_hz=120`。

## 6. 与 memmove 故障的关系

现有记录不支持「120 Hz 触发该故障」：round E（`fb_hz=120`）与 round F（默认 60）在同一调用点、同一 `pc` 偏移上出了同一个故障，来源见 [roundb 归因](2026-10-28-roundb-memmove-attribution.md)。所以本方案与该故障无因果关系，改完不需要重跑 memmove 判据；若改完 bad access 形态变化，按新现象单独立项，不并进这条。

## 7. 未做与风险

120 Hz 对显示驱动拷贝（`tl: v`）与 SMMU 带宽的影响没有实测，第一次跑 120 Hz 的轮次要单独看 `tl: v` 的三段时间。
