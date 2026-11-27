# 2026-11-27 批 14 与批 15 真机实测记录（b5r42～b5r47 / flipwd24～flipwd25）

本记录汇总批 14 内核 `xnu12377-flipwd24.bin`（sha256 `b94a722905769c84336ed301ebfd53e983cbd2588efc2fda0076777461e10d02`，`21053864` 字节）与批 15 内核 `xnu12377-flipwd25.bin`（sha256 `fe9d12ab00208188c1ed352e0b96eba524e9adcb428bae5730b623fd0a4a0251`，`21053944` 字节）配合用户态 `c0c7ebda...`（`rwa_lock` 收窄）的六轮真机测试与诊断采证结果。

## 1. 轮次与产物总览

- **批 14（`flipwd24`）**：`b5r42`（`adreno8_preempt=1`）验收 `P6` `BT_EN` `20 ms` 复位脉冲与 `P14` FastRPC GLINK 建立，并查明 `AnnibaleGPU.cpp:1140` 拦截用户态抢占队列；`b5r43`（`modem=3`）查明 `annibale_ipa.c:1011` 整段 `ml_io_map_unmappable()` 触发 `KERN_NO_SPACE`；`b5r44`（`psci_idle=1 adreno8_ifpc=1`）验收 `P23` 联合全功能省电态。
- **批 15（`flipwd25`）**：合入 `AnnibaleGPU.cpp:1140` 优先级放行（`#476`/`#479`）与 `annibale_ipa.c:1011` 分段/分块页对齐映射（`#498`/`#500`）后，`b5r45` 验收 `G30` 第一阶段（`adreno8_preempt=1`），`b5r46` 验收 `P13` `MPSS` `node 0` 与双槽 `QMI_UIM`，`b5r47` 完成 `P21`/`M3`/`S11` 现场诊断采集（经核对 `EVNTEN+WFE` 临时 loader 存在 EL2/USB 人工按键复位风险后按安全分支执行）。

## 2. b5r42：蓝牙硬复位、FastRPC 与 GPU 抢占拦截

- **GPU 抢占内核自检与用户态定因**：内核日志确认 `adreno8: HWSCHED START acknowledged (ifpc=0, preempt=1)`，双上下文完成自检（`context 1 pass 1/2` 返回 `0x22c00001`/`0x22c00002`、`context 2 pass 3` 返回 `0x22c00003`）；`backboardd`（38）与 `SpringBoard`（29..360）因 `annibale_gpu_dispatch.c:67` 上报 `PRIORITIES=2`、Mesa 传入 `r.queue.prio=1` 而被 `AnnibaleGPU.cpp:1140` `r.queue.prio != 0` 拒绝，回落 `backend=none` 并触发 `MPSLibrary.mm:639` 崩溃循环。
- **`P6` `BT_EN` `20 ms` 复位脉冲通过**：内核触发 `PM8550VE-F` `GPIO3` `BT_EN low` 后拉高并切至 `115200 8N1 RTS/CTS`，发送 `hmtbtfw20.tlv`（`275208` 字节 / `1133` 片），随后向 `bluetoothd` 上报 LE 广播并启动 `com.apple.locationd-central-69-47` 扫描，零 CTS 卡死。
- **`P14` FastRPC GLINK 与存储巡检**：记录 `aadsp: fastrpc: channel fastrpcglink-apps-dsp up (lcid=5 rcid=5, intents=4x512B)`，期间入站 `0` 帧（ADSP 等待 AP 发起 `INIT_CREATE`/传感器 PD 读取）；`S1`/`S2`/`S9`/`S20` 录得 `0` 条 `apfs: write` 与 `ufshc` 错误，`locationd`（69）存活，`docs/progress/evidence/k90auto/loader-recover-b5r42` 干净退回空闲 `xnuloader`。

## 3. b5r43：modem=3 分段装载前置与整块映射定因

- **基带镜像鉴权与内存建立通过**：`b5r43` 单变量带 `modem=3` 执行，`PAS_IS_SUPPORTED pas1/38/4` 与 `HYP_ASSIGN(excl)` 通过，`modem_dtb`（`pas=38`）返回 `rc=0`，`MPSS`（`pas=4`）完成 `PAS_INIT_IMAGE`（`hdr_pa=0xcf70d000 mdt_sz=9016`）与 `PAS_MEM_SETUP`（`phys=0x8ba00000 sz=0xf600000 span=0xe400000`）。
- **整段映射触发 `KERN_NO_SPACE` 与收尾**：紧接着触发 `panic(cpu 2): kmem_alloc(..., 257949696, 0x20041): failed with 3 @vm_kern.c:186`（`docs/progress/evidence/k90auto/kernel-12377-flipwd24-b5r43/run/returned.log`），源于 `annibale_ipa.c:1011` 对整块 `0xf600000`（`246 MiB`）调用 `ml_io_map_unmappable()`。关机前 `PAS_SHUTDOWN(modem_dtb, pas=38)` 返回 `rc=0` 并退回空闲 `xnuloader`。

## 4. b5r44：PSCI C4 与 IFPC 联合全功能省电验收

- **联合省电链路同时就绪**：`b5r44` 带 `psci_idle=1 adreno8_ifpc=1` 启动，`psci: method=smc version=1.1 cpu_suspend=0x3 (osi=1 ext_stateid=1) psci_idle=1`、`adreno8: GPU powerup list IOVA=0x10023000 bytes=1592 IFPC=81 preemption=26 dynamic=60` 与 `GPU OOB released for IFPC inter-frame GX collapse` 全部生效。
- **静置温度、频率与电流回落**：`cpufreq` 对比 `[220.616]` 与 `[190.597]` 显示静置 `>15 s` 后 `domain 0` 最热由 `61.6 °C` 降至 `41.8 °C`、最冷降至 `38.4 °C`（`384 MHz` 占 `95%`）；`domain 1` 最热由 `67.4 °C` 降至 `51.2 °C`、最冷降至 `38.7 °C`（`1017 MHz` 占 `95%`）；电池 `BQ27Z561 SOC=94% V=4358 mV I=0 mA T=32.25 °C`。
- **渲染、存储与无人值守退回**：`cycle.py` 退出 `0`，`docs/progress/evidence/k90auto/kernel-12377-flipwd24-b5r44/render-report.txt`（`4590670 bytes`, `0 merge gaps`）无 `restart` 与 `gpu` 停转段，`locationd`（72）、`backboardd`（38）、`SpringBoard`（29）存活；`returned.log`（`43` 份日志独立复核，`55,638` 唯一行）全零 `apfs: write`/`ufshc`/`gpu_fault`（`ufs: native: 269627 reads, 0 errors, 5765201920 bytes`），`oem stop` 干净退回空闲 `xnuloader`。

## 5. b5r45：flipwd25 GPU 双上下文与抢占阶段 1 验收（G30）

- **修复与双端就绪**：`AnnibaleGPU.cpp:1140` 按 `annibale_gpu_parameter(0x07, &prios)` 校验 `r.queue.flags != 0 || r.queue.prio >= prios`（`#476`/`#479`）。`b5r45`（`flipwd25` + `adreno8_preempt=1`）内核通过 `context 1 pass 1/2`（`0x22c00001`/`0x22c00002`）与 `context 2 pass 3`（`0x22c00003`），`backboardd`（38）与 `sbmetal26` 均成功采用 `backend=Adreno (TM) 830`（`apple3=1`）。
- **稳定性与调度采样**：`cycle.py` `12` 步交互与截图全部通过（`rc=0`，`render-report.txt` `5970457 bytes`, `0 merge gaps`），`locationd`（70）、`backboardd`（38）、`SpringBoard`（29）存活无重启，`docs/progress/evidence/k90auto/loader-recover-b5r45/returned.log`（`42` 份日志，`61,210` 唯一行）全零 `gpu_fault`/`submissions closed`/`AnnibaleGPU client refused`/`apfs: write`/`ufshc`；同轮实测 `backboardd` `>90` BO 降至 `1.78%`（`149/8347`，峰值 `99`）、Goodix 触摸间隔 `4.75..4.80 ms` 偶发滑移至 `9.30 ms`（`1/9`）。

## 6. b5r46：flipwd25 MPSS node 0 与双槽 UIM 验收（P13）

- **分段/分块映射修复通过**：`annibale_ipa.c:1011` 改为 `<= 4 MiB` 页对齐分块映射与 BSS 清零（`#498`/`#500`）。`b5r46`（`flipwd25` + `modem=3`）实测 `staged modem phys=0x8ba00000 span=0xe400000 highest=0xe400000 w0=0x5800c00e wlast=0` 与 `PAS_AUTH_AND_RESET(modem, pas=4) -> rc=0`，零 `kmem_alloc` 错误。
- **`MPSS` `node 0` 与双槽 `QMI_UIM` 就绪**：`MPSS SMP2P slave-kernel READY in 2450 ms`，`IPCRTR` 上线（`node 0`）并注册 `QMI` `0x09`/`0x03`/`0x0b`/`0x01`/`0x05`/`0x02`/`0x10`，`rmtfs`（`modemst1`/`modemst2`）与 `tftp`（`mcfg_sw.mbn`）读写通过；`QMI DMS` 切入 `ONLINE`（`operating_mode=0`），`QMI UIM` 正确解析双槽（`slots=2`，`phys_slot0/1` 与 `slot0/1` `apps=0`，当前未插物理 SIM 卡），`QMI NAS` `reg=2 mcc=460 mnc=11`、`QMI LOC` `fixes=17`。
- **交互与进程稳定性**：`cycle.py` `12` 步通过（`rc=0`，`4574784 bytes`, `0 merge gaps`），`CommCenter`（67）、`CommCenterMobileHelper`（99）、`backboardd`（38）、`SpringBoard`（29）持续存活；`locationd[73]` 于 `19:45:42` 出现 `1` 次 `userabort` 后自动重启为 PID `268` 稳定运行。
- **存储巡检与退回**：`run/s020.log` 录得 `1` 次用户态指针 `apfs: write ... failed: 14`（`EFAULT`，已正常回滚），`docs/progress/evidence/k90auto/loader-recover-b5r46/returned-held.log`（`46` 份日志，`50,873` 唯一行）全零 `gpu_fault`/`submissions closed`/`AnnibaleGPU client refused`/`ufshc`/`kmem_alloc`，并干净退回空闲 `xnuloader`。

## 7. b5r47：flipwd25 P21 / M3 / S11 诊断采集

- **`P21`（`a80211_test` 实测）**：`sets 22` `CopyCurrentNetwork -> 0`（Channel `44`、width `80`、RSSI `-29`、SNR `66`）；`mwxjoin` 在 `ScanAsync -> 0`（`scan results 22`）、`Disassociate -> 0` 与 `AssociateAsync -> 0` 后回调返回 `0xffffff9c`；`cwjoin` 发出 `scan request sent`；`leave` `set disassociate(22) -> 0`（内核 `2` 次）后 `CopyCurrentNetwork -> -3903`（未自动重连）。
- **`M3`（`sound_test route` + `anntouch button voldown 100`）**：`sound_test route` 输出 `1 output, volume 0.50` 与乱码设备名 `Speaker "f\t,e#0e ("`（系统输出上下文 `1 device ((none))`）；触发 `voldown` 后 `input26` 送达 `backboardd[38]` `VolumeDecrement page:0xC usage:0xEA down/up`，环形日志未出现 `audio_plugin unknown()` 或 `MediaExperience`/`audiomxd` 音量回调（仅启动期 `audiomxd[65]` `IAPAudioCopyDeviceStates: audioDeviceStates == NULL`）。
- **`S11`（`fhw_test` 与 `b5r46` `locationd[73]` 栈）**：`/annibale/bin/fhw_test` `4/4` 通过（`rc=0`，4 组冷页/追加写入均 `writeData: threw nothing ok`）；`b5r46` `render-report.txt` 记录 `locationd[73]` 于 `19:45:42` `userabort`（`shared cache slide 0x1b034000; called from: 0x1aa10efcc 0x19b1fefd4 0x19b200b90`）；`docs/progress/evidence/k90auto/loader-recover-b5r47` 收敛至空闲 `xnuloader`。
