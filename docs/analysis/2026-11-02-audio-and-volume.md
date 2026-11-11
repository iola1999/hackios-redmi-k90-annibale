# K90 音量与声音输出调研（2026-11-02）

本文回答两件事：音量键、音量提示框和音量值在 iOS 26 上怎样工作起来，以及真正的扬声器出声要做什么。只读调研：读了本仓库源码、Android 设备树、iOS 26 共享缓存和参考仓库 dada（小米 15，同为 SM8750 上的 iOS 26）的内核补丁，没有操作设备，也没有构建。

引用写法：`P:行号` 是 dada 的 `kernel/xnu-12377.121.6-dada.patch`；`dada:` 开头是该仓库里的路径；`DTS:行号` 是解压后的 `docs/analysis/data/annibale.dts.gz`。

本文的源码状态与推断对应 11-02 调研。后续实现与实测见[多媒体验证结果](2026-11-11-multimedia-validation.md)，未完成事项见[多媒体待办](../backlog/multimedia.md)。

## 1. 需要用户决定的事

音频服务、ADSP 与功放实现已落地，相关代码与产物见[多媒体进展](../progress/2026-11-11-multimedia-bringup.md)。扬声器实际出声、保护与麦克风验收见[多媒体待办](../backlog/multimedia.md)。

## 2. 结论

- 音量键、音量提示框和音量值可以先在 iOS 一侧做通，不需要声音硬件。HakiOS 在 iOS 16.5 上就是这样做的：用户态 HAL 插件 `AnnibaleAudio.driver` 提供一个可以路由到的音频设备，iOS 用软件调音量。
- 在我们的 iOS 26 系统盘上，挡住这一步的是两件具体的事：audiomxd 从来没有启动；`AnnibaleAudio.driver` 按 arm64 编译，arm64e 的 audiomxd 加载不了它（推断）。
- 真正出声要 ADSP、AudioReach 图和功放驱动。dada 的通路在 K90 上引脚一一对应，只有功放芯片不同。

## 3. 现在的状态

- 按键：`input26_service.c:363-376,423` 发 HID consumer 页 0x0C 的 0xE9／0xEA。iOS 26 的 SpringBoard（`SBVolumeControl`、`SBAVSystemControllerCache`）从 AVSystemController 读音量，服务端在 audiomxd 里（`SpringBoard.framework` 里的格式串 `Caching newEffectiveVolume: %f from AVSystemController`）。只有 HID 事件时，音量值改不了，提示框不出现或显示旧值（推断，真机没有验证过：唯一一次 iOS 26 的音量键探针落在画面冻结期间）。
- audiomxd：23G90 没有 `mediaserverd`；`usr/libexec/audiomxd` 在系统盘上，但 `hackios-xnu-userland/userland/mkjobs.py:221` 的 DENY 词 `audio` 挡住了 `com.apple.audiomxd`，`tools/k90auto/package.py:276-289` 沿用这张表。audiomxd 承载 `coremedia.systemcontroller.xpc`、`volumecontroller.xpc`、`SystemSoundServer-iOS`、`audio.hapticd` 和 `AudioSession`。它没有卡住或崩溃，只是没有启动。
- 插件：系统盘上有 `AnnibaleAudio.driver`，但 11-01 的产物 `hackios-xnu-kernel/userland/root/lib/AnnibaleAudio.driver/AnnibaleAudio` 是 arm64 的 Mach-O bundle（`build.sh:426`）。
- 系统盘：`VirtualAudio.plugin` 和 115 个 UISounds 都在（`ios165/select-system.py:155-156,201`），`System/Library/Audio/` 下只去掉了 usbaudio 一类插件（[启动程序审计](2026-10-28-launchd-programs-audit.md)）。
- 内核：只有继承自 POCO X5 Pro 的一套：`annibale_audio.c`（`/dev/annibale-audio`、音量 ioctl、`rec_sound` 录音）、`annibale_adsp.c`（旧的 APR 协议、annibale 的地址 0x86700000、没有平台判断）、`annibale_sound.c`、`annibale_speaker.c`（AW88261）、`annibale_guard.c`（软件扬声器保护）、`annibale_mic.c`。没有 SM8750 的音频代码。K90 上不能传 `adsp=1`、`sound=N`、`speaker_probe=N`，它们会去碰 annibale 的地址。

## 4. dada 的做法

- DSP：`annibale_adsp.c` 加了 SM8750 分支（`dadaadsp=1`）：载入 `adsp.mdt` 和第二个镜像 `adsp_dtb.mdt`（TrustZone 镜像 0x24，0x9ed80000），用 RPMh v3 的 TCS 布局，经 GLINK 通道 `adsp_apps` 说 GPR（P:21572-21577、22415-22424、24227-24420、26034）。
- 通路（`hakios_dada_audio.c`，P:1930-1953）：
  - 流 0x1001 在最后一个 context bank 上直通，loader 用 `lowdma=` 在 4 GB 以下给 64 KiB 缓冲（P:2089-2147）。
  - 手写两张 AudioReach 图：副 MI2S 上的 `I2S_SINK`（LPASS 做时钟主，48 kHz 16 位），以及 `WR_SHARED_MEM_EP → PCM_DEC → PCM_CNV`，20 ms 一个周期。
  - GPIO121-124 设为 `i2s1`（P:2635-2648），检查 APM 报就绪（P:2650-2665）。
  - 没有 ACDB，没有 DSP 扬声器保护，也没有用 `annibale_guard.c`。
- 功放（`hakios_dada_amp.c`，P:1669-1923）：两颗 CS35L43，地址 0x40／0x42，在 hub_i2c0 上，用 GPIO64／65 模拟 I2C；复位 GPIO107／108，中断 GPIO84／66；GPIO67 拉低时上面那颗接扬声器。功放自带 DSP 旁路，不需要功放固件，增益固定 18 dB（P:1813、1867）；有声音时上电，静音 5 秒后断电（P:2596-2633）。
- iOS 看到的：不发布 IOKit 或 IOAudio2 的类，`audio_plugin.c` 与我们的完全相同。它的 DENY 表放行了 audiomxd（`dada:userland/userland/mkjobs.py:231-241`），也放行了 `bluetoothd`，因为没有 `bluetoothd` 时 audiomxd 每秒查询蓝牙服务约 16000 次（:232-234）。内核不处理音量，iOS 在软件里缩放采样。
- 能看到的结果：内核开机时放一段 1 kHz、-40 dBFS 的测试音，记录周期是否完成、功放 PLL 是否锁定（P:3584-3631），以及 iOS 送来的数据（P:3653）。README:23 写扬声器能出声；仓库里没有 iOS 的声音从扬声器出来的运行记录，`HISTORY.txt` 46-54 行的音频条目都是麦克风（WCD9395 经 SoundWire），没有结果记录。dada 的身份是 iPhone18,1，我们的是 iPhone18,3。

## 5. K90 的硬件

- 功放在 hub_i2c0（0x980000，SDA GPIO64、SCL GPIO65）（DTS:25697-25760、41942-41966）。设备树和 dtbo 里两组芯片都标为 `ok`，是双供应商设计：
  - `tfa98xx_1@0x36`（复位 GPIO108，中断 GPIO66，听筒／扬声器切换 GPIO67）与 `tfa98xx_2@0x34`（复位 GPIO107，中断 GPIO84）。TFA98xx 是 NXP（现归汇顶）的芯片。
  - SIA9197x，地址 0x6e／0x6c，复位与切换脚相同。
- 复位、中断、切换和总线引脚与 dada 相同。
- I2S（`sec_tdm_pinctrl`）：GPIO121 时钟、123 帧、122 数据入、124 数据出，功能 `i2s1_*`（DTS:30905-30913、7176-7280），与 dada 相同。
- 编解码：WCD9395，加上 LPASS 的 wsa／wsa2／rx／tx／va 宏；`qcom,wsa-max-devs = 0`，没有 WSA 功放。
- ADSP 内存 0x9ee00000、dtb 区 0x9ed80000，与 dada 相同；LPASS 的 SMMU 流号 0x1000～0x13ff（[硬件地图](annibale-hw-map.md)）。
- 后续已按 TFA9865／TFA9866 实现功放驱动，ADSP 与功放读数见[多媒体验证结果](2026-11-11-multimedia-validation.md)。实际出声与保护验收见[多媒体待办](../backlog/multimedia.md)。

## 6. 实施顺序

音频服务、固件加载、AudioReach 图、DMA 缓冲和功放的实现与验证见[多媒体进展](../progress/2026-11-11-multimedia-bringup.md)及[多媒体验证结果](2026-11-11-multimedia-validation.md)。剩余定位与验收统一见[多媒体待办](../backlog/multimedia.md)。

参考代码的文件规模：`hakios_dada_audio.c` 有 1760 行，dada 的 `annibale_adsp.c` 有 4794 行，移植文件须遵守 AGENTS.md §2；dada 的 CS35L43 驱动不适用于 K90 的功放。

## 7. 风险与未知

- iPhone18,3 的音频路由可能与 16.5（iPhone X 的表）和 dada（iPhone18,1）不同。
- TFA 芯片可能需要容器文件才能出声。
- 没有 DSP 扬声器保护，只有软件保护。
- 固件体积会影响载荷的装载方式。
- 同类项目在 Qualcomm 平台上出声时遇到的几处问题（主机时钟 19.2 MHz、128 位换算、缓冲在 4 GiB 以下、传输类型）列在 [11-05 上游对照](2026-11-05-upstream-lessons.md) §1 第 8 项。

当前验收范围与剩余工作见[多媒体待办](../backlog/multimedia.md)。
