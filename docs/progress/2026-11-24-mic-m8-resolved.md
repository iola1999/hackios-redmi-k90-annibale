# 2026-11-24 M8 麦克风定案：TX macro dec1 + RXTX TX_CDC_DMA_TX_3

轮次 `kernel-12377-say49-ubo51`（锁定）、`kernel-12377-say52-ubo54`（默认路径验收）。

## 1. 结论

K90 的麦克风声学链路是：DMIC0 焊盘对（LPI gpio6/7）→ **tx-macro@0x6AE0000 的 decimator 1** → **RXTX LPAIF 的 TX_CDC_DMA_TX_3**（codec-DMA `lpaif_type=1`、`intf_index=4`、`active_channels_mask=1<<1`）→ SG_MIC codec-DMA 源 → SG_CAPTURE（MFC→CNV→ENC→RD_SHMEM）→ `/dev/annibale-mic`。该端口与 redwood 在同架构 LPASS 上已验证的路径一致（`TX_CDC_DMA_TX_3` + decimator 1），K90 声卡自身路由 `"TX DMIC0..5"→"RX_TX DECx_INP"→"TX DECx MUX"` 也指向这块。

此前所有轮次配的 va-macro@0x7660000 找错了 macro 块：K90 的 LPI DMIC 焊盘喂 tx-macro，VA macro 的 codec-DMA（VA_CDC_DMA_TX_n）不连这些焊盘，所以任何 VA 组合都只出 0x8000 轨值或全零。

## 2. 已验证的采集配置

按 say50/ubo52、say51/ubo53 两次排除性实验（固定绑定仍 0 done）与 ubo51 锁定轮的 boot-args 比对定出，缺一不可的或属于已验证序列的：

1. codec-DMA 接口参数：`lpaif_type=1`（RXTX）、`intf_index=4`（TX_CDC_DMA_TX_3）、`active_channels_mask=2`（decimator 1 → AIF slot 1）。
2. `HW_EP_POWER_MODE_CFG=0`（上游同款；之前默认 2 时 DSP 收端口配置但不产数据）。
3. 不发 `HW_EP_DMA_DATA_ALIGN`（上游对 codec-DMA 本就不发这个参数；多发时同样 0 done）。
4. `mic_v41=1` 寄存器序列：FS_CNT 写 0x83 再 0x81（bypass 保持置位使能），VA 侧 ADPT 块 POST_PMU 清使能字段。
5. TX macro 初始化：`MCLK_EN`、同套 FS 序列、`FS_BROADCAST_EN`，然后 `mic_program_dec` 编程 dec1（mux sel=1 即 DMIC0、`TX_PATH_CTL` fs_rate + CLK_EN、HPF 门序列、0dB 增益）。
6. VA macro 侧既有配置全部保留：MCLK/FS/SWR_CONTROL、DMIC_CTL0..3=0xb（en + /16 = 1.2 MHz pad 时钟——DMIC 焊盘时钟全部由 VA DMIC_CTL 生成，消费方在 TX 也一样）、SWR_MIC_CTL init 0xCC、VA dec0 使能（已验证序列的一部分，单独必要性未做消融）、LPI/TLMM 引脚配置。
7. 资源投票：LPASS core、DCODEC core、VA_MCLK、VA_2X_MCLK（19.2 MHz）、TX_MCLK（0x30c）。

已排除的路线：VA macro 的 intf1..3 × dec0..3 × DMIC/SWR 全组合（轨值或零）；SWR_MIC5..10（VA SWR master 起来后从设备枚举 status=0、dev-ids 全零，总线上没有从设备）；WSA/AXI 占位组合。

## 3. 真机录音结果

ubo51（`mic_v41=1 mic_pmode=0 mic_noalign=1 mic_sweep=1`）：
- 扫描表把 `TX_CDC_DMA_TX_3..5` 提前后第一个组合即锁：`sample range -2454..412, 960 interior`，该次捕获 445/448 读 done、末块 1920 字节、loudest 2454；后续每个录制会话重复锁定、同等交付。

ubo54 使用 say52 的默认麦克风配置，关闭了组合扫描。

- `record_test 5` 走 AVAudioRecorder：240000 样本、peak 2047、全程 -38 dBFS，房间底噪级别真实信号；该轮次保存的 WAV 为 `mic/record_test.wav`（2877 个不同采样值）。
- `micloop_test 6 raw tone 2`（新增测试：raw 直读 `/dev/annibale-mic`，第 2 秒起 AudioQueue 播 1000Hz 扬声器音）：录 288000 样本、peak 9819；**1000Hz 处播放前 -108.5 dBFS、播放中 -19.0 dBFS（相差 89.5 dB）**——扬声器音被麦克风真实捕获，端到端声学链路证实。
- 内核日志同轮：TX macro `SWR_DMIC_CTL` 读回 0xe、VA 回读 mclk 0x1/fs 0x1/swr 0x1/dmic 0xb×4、两图 started、READ_BUF 持续 done。

## 4. 代码改动

`xnu/files/bsd/dev/annibale/annibale_mic.c`：

- 默认值改为已验证组合：`mic_lpaif_type=1`、`mic_intf_index=4`、`mic_ch_mask=2`、`mic_pmode=0`、`mic_noalign=1`、`mic_v41=1`；`mic_dmic_sel` 含义改为 TX DEC1 输入 mux。
- TX macro 初始化抽成 `mic_setup_tx_macro(dec, dmic, swr)`，`mic_hw_prepare` 默认调用 `(1, mic_dmic_sel, 0)`；`mic_apply_combo` 的 mac=1 分支复用它。
- `mic_combos` 扫描表把 RXTX TX3..5 组合放最前（每轮从头扫的设计下最优先假设最先测）；表与 `mic_sweep`、`mic_combo=`、其余 `mic_*` boot-args 全部保留备用。

`hackios-xnu-userland`：`userland/src/tests/micloop_test.c` 新增（record_test 框架 + AudioQueue 音调线程 + `raw` 直读模式 + 频段能量分析），入 `compile_targets.py`，用 `record_test.entitlements`。

## 5. 遗留

- AVAudioRecorder 路径在 say49 轮曾出现一次「内核交付 7.08s、WAV 空」的 plugin 写文件问题，ubo54 下 `record_test` 的 AVAudioRecorder 路径连续两次正常交付，未再复现；如再出现按 audiomxd 侧问题排查，内核链路已证无责。
- 其余 DMIC 对（dmic23/45）和 TX decimator/接口的具体接线对应未逐一定案：扫描表在首组合锁定后即停，多麦/立体声映射如以后要立体声可再扫 `{1,4..6}×{dec}×{dmic}`。
- CoreHaptics 马达在 record_test 的 vibrate 模式仍返回 4099（用户态服务侧缺件，内核马达驱动正常），振动关联验证未做成；扬声器音调关联已替代完成声学证实。
