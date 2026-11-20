# 基带离开 OFFLINE 与定位注册：APPS 侧 TFTP 服务、固件卷按路径读取、QMI_LOC 客户端标识（2026-11-20）

本轮处理 [11-19 交接](2026-11-19-handoff.md)第 3 节的「`DMS` 停在 `OFFLINE`」。真机轮次 `g4a-r1`～`g4f-r1`（内核 `12377-g4a`～`12377-g4f`，启动参数 `modem=3 mic=4`）。原始日志在本地 `docs/progress/evidence/k90auto/kernel-<内核>-<轮次>/run/`。

## 1. 结果

| 验收级别 | 结果 | 依据 |
|---|---|---|
| `DMS` 进入 LPM 或 ONLINE | 达到 | `g4d-r1`：`operating_mode=5`，`SET_OPERATING_MODE result=0 err=0`，随后 `operating_mode=0` |
| `UIM` 读到卡 | 未达到 | `slots=2 slot0=(card=0 ...)`，卡状态为不存在；原因未查 |
| `QMI_LOC 0x21` 注册成功并收到卫星或定位上报 | 达到，上报不含卫星 | `g4f-r1`：`0x21`（`mask=0x187`）`result=0`，`START` 后收到 `fix_session_state=1`、`engine_state=1` 和位置上报（`tech=0x2`，`sv_used=0`），`sv_info count=0` |

`g4d-r1` 中 `NAS` 的注册状态为 2（搜索中），并报告了网络的 MCC／MNC。全程没有向 UFS 写入。

## 2. 原因

MPSS 启动后经 QRTR 上的 TFTP 服务（服务号 4096）读写文件。它先写 `/readwrite/server_check.txt`，写成功后才读取 `/readonly/firmware/image/modem_pr/mcfg/` 下的配置。APPS 侧此前没有这个服务，MPSS 读不到配置，停在 `operating_mode=3`。

四轮各改一个变量：

| 轮次 | 变量 | 现象 |
|---|---|---|
| `g4a-r1` | 发布服务 4096，记录请求并答复「文件不存在」 | MPSS 反复写 `/readwrite/server_check.txt`；`DMS` 仍为 3 |
| `g4b-r1` | `/readwrite/` 用内存文件 | 写入成功后 MPSS 请求 `mcfg_ddr/rf/rf_config_0940_0_0.mbn`、`mcfg_hw/mbn_hw.dig`、`mcfg_sw/mbn_sw.dig` 等只读文件；`DMS` 仍为 3 |
| `g4c-r1` | `/readonly/firmware/` 读固件卷 | 读到文件后 MPSS 崩溃：`dog_hal_common.c:178:DOG detects stalled initialization` |
| `g4d-r1` | 数据块发送等待 GLINK 接收 intent | MPSS 共发出 244 个读请求并读完，`DMS` 到 0 |

`g4c-r1` 的崩溃来自发送路径：`mpss_qrtr_send()` 在 MPSS 没有足够大的接收 intent 时发出 `RX_INTENT_REQ` 并返回 `EAGAIN`，数据块没有重发，MPSS 等待超时后初始化看门狗触发。

## 3. 实现

- [annibale_modem_tftp.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_modem_tftp.inc)：TFTP 服务端，支持 `blksize`、`timeoutms`、`tsize`、`wsize`、`rsize`、`seek` 选项。块大小上限 7,168 字节，使数据块连同报头不超过 QRTR 数据报的 8,192 字节。
  - `/readwrite/`：内存文件，最多 16 个、每个不超过 1 MiB，重启后清空。
  - `/readonly/firmware/`：映射到 modem 固件卷的根目录，整文件读入内存，保留最近 4 个文件。MPSS 用带 `rsize`／`seek` 的多个请求分段读同一个文件。
  - 其余路径答复「文件不存在」并记录文件名。
  - 读会话记录下一个待发块和窗口末尾；发送返回错误时停下，由基带线程每个周期调用的 `modem_tftp_poll()` 继续发送，单次最多占用 20 ms。
- [annibale_ufs_rw.inc](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_ufs_rw.inc)：FAT16 读取改为按路径逐级查找（`annibale_ufs_fat16_path_read()`），支持子目录、长文件名和跨簇目录。原有的 `annibale_ufs_fat16_fw_read()` 改为读取 `image/<文件名>` 的封装，ADSP、IPA、MPSS、Iris 的固件加载仍走它。

宿主测试：新增 `test-annibale-modem-tftp.py`（写入与回读、窗口、`rsize`／`seek`、固件卷、发送被推迟后的续传、拒绝与大小上限）和 `test-annibale-ufs-fat16.py`（测试内生成 FAT16 卷；8.3 与长文件名、多级与跨簇目录、不连续文件；3 个手工变异被拒绝）。

固件加载回归：`g4d-r1` 日志中 ADSP 鉴权就绪、`modem_dtb` 与 `modem` 的 `PAS_INIT_IMAGE` 成功、播放图启动。

## 4. QMI_LOC 事件注册

`DMS` 进入 ONLINE 后 `0x21` 的返回不变。`g4e-r1` 用临时探针在一次开机内逐条发送 `QMI_LOC` 消息（探针已撤回）：

| 消息 | 结果 |
|---|---|
| `0x3b`（读引擎锁）、`0x4b`（读工作模式） | `result=0` |
| `0xc3`（密钥 `0xbaabcdef`） | `err=57` |
| `0x21`，`mask=0x187` 或 `0x01`，只带事件掩码 | `err=48` 后 `err=3`，或 `err=3` |
| `0x21`，`mask=0x01`，另带 TLV `0x10`（客户端名 `gps`）与 TLV `0x11`（客户端类型 1） | `result=0` |

[annibale_modem.c](../../hackios-xnu-kernel/xnu/files/bsd/dev/annibale/annibale_modem.c) 的两条注册请求都补上这两个 TLV。`g4f-r1` 中首条（`mask=0x187`）即成功，原有的 15 秒定位探测收到会话状态、引擎状态和位置上报，结束后引擎状态回到 2。位置上报的技术掩码为 `0x2`，没有卫星参与；测试机在室内，探测窗口 15 秒。

## 5. 未解决

1. `UIM` 报告卡不存在。测试机是否插卡、卡槽检测与供电由谁负责，本轮没有核对。
2. 卫星定位没有验证：15 秒窗口内 `sv_info count=0`。需要在室外或窗边延长探测时间，并对接 `locationd`。
3. 固件卷里长度为 0 的文件按不存在处理。
4. `servreg_notify`（`0x42`）、`servreg` 域表与 `RMTFS` 的 `force_sync` 三个候选没有单独验证；`DMS` 已能进入 ONLINE，它们对 `UIM` 与定位是否有影响未知。
5. iOS 侧（CommCenter、状态栏信号）没有对接，本轮只到内核 QMI 客户端读数。
