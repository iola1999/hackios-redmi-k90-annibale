# FairPlay 与 App Store 可行性及第三方仓库调研（2026-11-27）

本文基于 `gh` 实查外部仓库源码与 README，对照看雪 `thread-293705`《IPA-Decrypt：从App Store 原包下载到离线FairPlay 解密的实现-iOS安全》摘要，并结合 `hackios-xnu-userland/userland/src/inject/` 与 `hackios-xnu-kernel/xnu/` 现有实现，评估 REDMI K90（SM8750 / XNU 12377 / iOS 26.6.2 `23G90`）在原生 FairPlay、App Store 与离线解密安装路径上的可行性。既有 `fairplayd.H2` 实测见[历次反馈复核 §3.6](2026-11-08-issue-reassessment.md#36-天气签名与-unfairplay-参考范围)与[架构审查 §12.1、§12.5](2026-11-08-architecture-review.md#121-weathermaps-与-fairplay)。

## 1. 外部目标仓库源码核查

- **`Re13orn/IPA-Decrypt`（下载与模拟执行层，对应看雪 `thread-293705`）**：`apps/ios/Tools/ipatool/{main.go,transfer.patch}`、`apps/ios/Tools/build-ipatool.sh` 与 `AppleAuth` 基于 `majd/ipatool` 实现 App Store / TestFlight 登录、版本选择及带 `SC_Info/*.sinf`/`.supf` 原包下载。iOS 端内嵌 `unicorn-2.1.4`（`unicorn-ios.patch`）模拟客户端 SAP，运行期需 `mmap` + `mprotect(PROT_READ|PROT_EXEC)` 动态执行页权限（`ipalab_can_execute_dynamic_code`）。
- **`Re13orn/IPA-Decrypt`（解密与凭据路径）**：包含两条互不兼容的解密路径——`apps/{ios,macos}/App/FairPlay.swift` 基于 `EthanArbuckle/fairplay-decrypt` 用 16 字节 `credential.bin` 离线解密；`apps/macos/App/MacEnrollment.swift`（`apps/macos/Package.swift` 要求 Apple Silicon 与 `macOS 15+`）调用 `bin/unfairplay`（`DrWhax/unfairplay`）导出已登录 Mac App Store 的本机 FairPlay 快照并解密，仅支持在 Mac 端运行。`CredentialExtraction.swift` 与 `apps/macos/Resources/Extractor/` 内置 `credential-retrieval` 通过 SSH 从越狱机提取 `credential.bin`。
- **`EthanArbuckle/fairplay-decrypt`（离线解密算法）**：`core.py` 与 `decrypt.py` 纯用户态实现 AES-128、MD5 与平方混合网络，覆盖 `.supf`（v3）、`.v5.supf`（v5）、440B/448B `priv` SINF 与 arm64 Mach-O。`derive_work16()` 以 `MD5(name + iviv)` 为 IV、`credential XOR ('0'*16)` 为密钥解开 `priv` 得 16B `work`，`derive_page_key()` 逐 4 KiB 页按 `.supf` 32B 条目派生页密钥解密，并将 `LC_ENCRYPTION_INFO_64`（`0x2C`）的 `cryptid` 置 `0`。
- **`EthanArbuckle/fairplay-decrypt`（16B 凭据提取前提）**：`credential-retrieval/{retrieve.py,credential/credential.c,driver/driver.c,trigger/trigger.c}` 须运行于已越狱（iOS 10+）、已登录目标 Apple ID 且装有至少一个同账号 App 的真机上。其通过 USB SSH 拦截 `fairplayd` 解出的 `uid-layer.bin`（或 Arcade `arcade-capture` + `IC-Info.sido`），再结合 `descriptor_key`（`UniqueDeviceID` + 静态表）与 `driver.c` 调用 `com_apple_driver_FairPlayIOKit` selector `9`/`21` 算出 16B `credential.bin`；取出 `credential.bin` 后，`decrypt.py` 可完全脱离原设备离线运行。
- **`vnc0/fairplay-scinfo`（`SC_Info` 格式与 ImHex 模式）**：`patterns/{sinf,supp,supf,supx}.hexpat` 记录旧版 `.supp`（`0x01`）/ `.supf`（`0x03`）与新版 `.v4.supp`（`0x04`）/ `.v5.supf`（`0x05`，去掉 `LC_CODE_SIGNATURE` 的 20B SHA-1 块）结构差异，以及 `.supx` TLV 索引与 `.sinf` MP4 atom 树（`user`/`key `/`iviv`/`priv`），含 708B RSA-1024 证书与 128B 签名校验，仅作格式参考而无解密实现。
- **`morzelowski/FairPlayed`（免越狱真机解密）**：`fpcore.c`、`main.m` 与 `fpdecrypt.sh` 将目标 App 嵌入开发签名 Helper，经 `mmap(PROT_READ)` 后执行 `SYS_mremap_encrypted`（`489`，传 `cryptid=2` 绕过 `PROT_EXEC` 与 AMFI 校验），直接触发内核 `vm_map_apple_protected` -> `text_crypter_create` -> `FairPlayIOKit` -> `fairplayd` 解密页并回写。运行前提为本机具备完整 `FairPlayIOKit`、活跃 `fairplayd` 且已登录购买该 App 的 Apple ID。
- **纯 AirPlay 与同名无关项目边界**：`mazer666/PhairPlay`（`FairPlay.kt`、`fairplay_jni.c`、`playfair/`）仅处理 AirPlay 2 `POST /fp-setup`（v2/v3）握手与音视频流密钥 `playfair_decrypt`，README 明确不解密 FairPlay DRM 视频，与 IPA 加解密无关。`Hackcraft-Labs/Fairplay` 为红队样本与 IOC 监测框架，`FairPlayTeam/fairplay-docs` 及 `FairPlayTeam` 全组织仓库（`backend-v1`/`v2`、`frontend`、`transcoding-worker`、`discord-bot`、`ShortBlocker`）为开源视频分享平台工程，均与 Apple FairPlay 无关。

## 2. K90 四层面可行性评估

| 评估层面 | 结论 | 核心依据与阻塞条件 |
|---|---|---|
| 1. 原生 `fairplayd.H2` + `FairPlayIOKit` 运行时解密（含 `FairPlayed`、`credential-retrieval`） | ❌ 不可行 | `inject_fairplay.c` 与真机六次加载确认 `fairplayd.H2` 查找 `com_apple_driver_FairPlayIOKit` 返回空 iterator 后 `exit(0)`（`mkjobs.py` 已禁用 `fairplayd.H2`）；`hackios-xnu-kernel/xnu/` 不含 `FairPlayIOKit`、`text_crypter_create` 与 `SYS_mremap_encrypted` 解密路径。原版算法依赖苹果芯片 UID/GID 硬件密钥链（`IOAESAccelerator`），K90 缺少硬件密钥根，无法作为 `FairPlayed` 运行端或 `credential.bin` 提取端 |
| 2. 原生 `AppStore` / `appstored` 登录与直接安装 | ❌ 短期不可行 | `inject_store.c` 与 `inject_store_storefront.inc` 实测 `appstored` 阻塞于 `_ams_localiTunesAccountAfterUpdatingStorefront:` 与 `_AMSFairPlayGetDeviceType`（等待 `fairplayd`）；即使绕过 storefront 校验，真实 Apple ID 登录、`anisette`/`Mescal` 签名、购买授权与加密页运行仍受硬件信任链、Keychain、`fairplayd` 与加密页内核支持阻塞 |
| 3. 宿主机离线下载解密 + `TrollStore` 安装工作流 | ✅ 主力可行路线 | 零依赖 K90 内核改造。在 macOS 宿主机由 `Re13orn/IPA-Decrypt`（Apple Silicon + `macOS 15+` 经 `MacEnrollment` + `unfairplay`，或导入外部已越狱 iOS 10+ 设备提取的 16B `credential.bin`）或 `majd/ipatool` + `EthanArbuckle/fairplay-decrypt`（`decrypt.py --credential`）下载并清零 `cryptid`（常规与 TestFlight App 可解密；Apple Arcade 需单独 Arcade 凭据），再经 K90 已就绪的 `TrollStore.app` / `trollstorehelper` 安装持久化 |
| 3b. K90 机端运行离线解密或下载（进阶可选） | ⚠️ 仅纯解密无阻断，机端下载需验页权限 | 纯离线解密端（`fairplay-decrypt` `core.py`/`decrypt.py` 或 `IPA-Decrypt` `FairPlay.swift`）只用标准 AES/MD5 与 ZIP/Mach-O 读写，可编译运行于 K90（导入外部 `credential.bin` 与加密 IPA 后解密送 `TrollStore`）。若在 K90 机端运行 `IPA-Decrypt` iOS 版下载（`ipatool` + `unicorn-2.1.4`），需另行核查 K90 XNU/AMFI 是否允许匿名页 `mprotect(PROT_READ\|PROT_EXEC)`，且机端仍无法提取 `credential.bin` 或运行 `unfairplay` |
| 4. 同名与纯投屏项目排除 | 已明确排除 | `mazer666/PhairPlay`、`Hackcraft-Labs/Fairplay` 与 `FairPlayTeam/*` 仅处理 AirPlay 2 握手或属同名无关项目，不列入 K90 FairPlay/App Store 路线 |

## 3. 结论与下一步安排

- 维持不在缺少硬件密钥根的 K90 上实现原生 `FairPlayIOKit`、`fairplayd.H2`、`FairPlayed` 与 `AppStore` 直接登录安装。
- 若后续需要打通受 Apple ID 加密分发的第三方 IPA 安装流程，优先按「macOS 宿主机（`IPA-Decrypt` 或 `ipatool` + `fairplay-decrypt`）下载解密 -> K90 `TrollStore` 安装」验证流程。
- 如需在 K90 本机提供离线导入解密能力，仅移植 `fairplay-decrypt` 纯离线解密逻辑即可；若额外追求机端 `ipatool` 登录下载，须先单独验证 `unicorn-2.1.4` `PROT_EXEC` 页权限边界与 AMFI 策略。
