# IPA 管理器的签名

IPA 管理器用 `appinst`（`hackios-xnu-userland/userland/src/apps/appinst.m`）安装 IPA 时，自己给应用主程序生成 ad-hoc 签名。用户反馈过重启后点击已安装应用无法启动，本文记录这个问题的原因、定位方法和修复，结论来自 2026-11-09 的真机排查。

## 1. 现象

- 重启后从图标启动 Kumone，应用不出界面。
- 内核日志依次出现 `unable to create a validated cs_blob object: 85`、`load code signature error 4 for file "KumoneIOS"`，随后是 `map_with_linking_np: ... region 0, not code signed`。
- 85 是 `EBADEXEC`。本机内核的 `cs_process_global_enforcement()` 为假，`parse_machfile()` 遇到签名加载失败只记日志，进程照常创建；dyld 映射主程序时发现没有签名，应用不出界面。

## 2. 原因

`load_code_signature()` 从文件读出签名后交给 `cs_validate_csblob()` 检查结构，有两处问题：

- CodeDirectory 布局：`appinst` 写的版本号是 `0x20100`。这个版本的 CodeDirectory 在第 44 字节有 `scatterOffset` 字段，`appinst` 却把标识符字符串从第 44 字节写起。`cs_validate_codedirectory()` 把标识符的前 4 字节（`Kumo`，`0x4b756d6f`）读成 `scatterOffset`，超出 CodeDirectory 长度，返回 `EBADEXEC`。
- 页哈希次序：签名指向的 load command（`LC_CODE_SIGNATURE` 与 `__LINKEDIT` 的大小）在文件第 0、1 页里。原实现先算页哈希再改这些字段，两页的哈希对应的是改之前的内容。

## 3. 定位方法

- 读路径：在内核构建树临时加诊断输出（未入库），签名检查失败时立即重读同一段数据并比较。两次读到的 135008 字节完全相同，排除 ramfs 与 UFS 读路径。
- 结构检查：按 `cs_validate_csblob()` 与 `cs_validate_codedirectory()` 的条件，在设备上逐项检查安装后的主程序签名，得到 `scatterOffset` 越界这一项。
- 页哈希：逐页计算 SHA-256 与 CodeDirectory 比较，修复前第 0、1 页不一致。

## 4. 修复

- 标识符改从第 48 字节写起，`scatterOffset` 保持 0，表示没有 scatter 向量。
- 先改写 load command，再计算页哈希。
- 用旧版 `appinst` 安装的应用，需要用新版重新安装一次才会换上新签名。

## 5. 真机结果

用户态提交 `8a3eb6f` 的 `appinst` 重新安装 Kumone 后：

- 签名结构检查全部通过，4195 页哈希全部一致。
- 同一次开机里从图标启动，显示应用界面。
- 重启后，开机时系统在后台拉起的 KumoneIOS 加载签名没有报错；结束这个进程后点图标，应用正常显示界面。
- 遗留：开机时后台拉起的 KumoneIOS 进程，点图标后没有切到前台，原因未查。
