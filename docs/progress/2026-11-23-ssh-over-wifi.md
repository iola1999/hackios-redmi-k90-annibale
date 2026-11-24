# 2026-11-23 Wi-Fi 下的 SSH 调试（ENG-21）真机验证

轮次 `kernel-12377-say9-tgl40`，设备 en0 `<DEVICE_IP>`（standing `<SSID>`），宿主 `<HOST_IP>` 同段直连。

## 1. 结果

SSH over Wi-Fi 全链路验证通过：密钥认证登入、远端命令执行、交互式 zsh、sftp 双向传输、sshd 可控退出。SSH 依赖 iOS 网络栈正常运行，不能替代 loader 通道做恢复（与既有结论一致）。

## 2. 产物来源

- `tools/mk-jb.sh` 从 `apt.procurs.us` 现取 bootstrap-iphoneos-arm64（rootless 1800 套件）+ Sileo 2.5.1，产出 `jb/root/var/jb`（127M，6926 项，含 openssh-server 9.7p1）。`jb/` 与 `fw-*` 一样不进仓库。
- `ssh/` 目录（仓库外，gitignore 白名单天然排除）：`ssh-keygen` 现生成 `ssh_host_ed25519_key(.pub)` 主机密钥与 `id_eng21(.pub)` 登录密钥，`authorized_keys` 为登录公钥。`build.sh` 的既有 `var.skel` 通道把三者写进 `/private/var/root/.ssh`（600/700 权限）。

## 3. 关键障碍与绕过

1. **boot volume 装不下 jb**：`FLASHBOOT=1 CRYPTEXES=flash` 把 jb 接进 `flashboot.apfs` 后镜像 79MB，超过 `make-payload.py` 的 64MB 常驻启动镜像上限（`MAX_BOOT_IMAGE_BYTES`）。该路径只适合刷入 UFS 后走 `/private/preboot/jb`。
2. **系统镜像路径同理**：`sysroot/jb` → `/jb` 只存在于 system26.apfs（11G），本轮启动用 `root_apfs=ufs_darwin` 挂的是先前刷入、无 jb 的 UFS 系统。
3. **运行期落盘（本次验证路径）**：held 轮次里 `oem push` 暂存宿主文件到 `kern.annibale.inbox`（单件 ≤16MB），`annsh pull PATH` 以 755 写盘——但 inbox 只留最后一次推送，必须推送、pull 逐件交替；`annsh` 无 `mkdir`，现编 30 行 `mkdirtool`（iphoneos sdk、无签名即可执行）建 `/var/jb` 目录树。
4. **libiosexec 读库文件不读平文本**：`getpwnam` 走 `/var/jb/etc/{pwd.db,spwd.db}`，由 `pwd_mkdb -p -d /var/jb/etc master.passwd` 在设备上现生成；OpenSSH 的 privsep 用户名是 `sshd`（非 Procursus 的 `_sshd`），passwd/group/master.passwd 需补 `sshd:*:75`。
5. **登录 shell**：`/annibale/bin/annsh` 是 mailbox 轮询守护，作 login shell 会挂住会话；改推 `zsh` + `libpcre.1` + `libncursesw.6`，`master.passwd` 里 root/mobile 的 shell 改为 `/var/jb/usr/bin/zsh`。

## 4. 推送清单（host → 设备）

| 来源 | 设备路径 |
|---|---|
| `jb/.../usr/sbin/sshd`、`pwd_mkdb` | `/var/jb/usr/sbin/` |
| `libiosexec.1`、`libcrypt.2`、`libpam.2`、`libmd.0`、`libcrypto.3`、`libpcre.1`、`libncursesw.6` | `/var/jb/usr/lib/` |
| `usr/bin/zsh`、`usr/bin/false` | `/var/jb/usr/bin/` |
| `usr/libexec/sftp-server` | `/var/jb/usr/libexec/` |
| 改编 `passwd`/`master.passwd`/`group`、`ssh/moduli`、最小 `sshd_config` | `/var/jb/etc/`、`/var/jb/etc/ssh/` |

## 5. 验证记录

- `sshd -e -h /var/root/.ssh/ssh_host_ed25519_key -o UsePAM=no -o PasswordAuthentication=no -o PermitRootLogin=prohibit-password -o AuthorizedKeysFile=/var/root/.ssh/authorized_keys -o PidFile=/var/jb/var/sshd.pid` 后台常驻，pid 406。
- `ssh -i ssh/id_eng21 root@"$DEVICE_IP" '/bin/ps -A'`：返回真实进程表（launchd 1、SpringBoard 29、wifid 34、backboardd 38）。
- 交互会话：`localhost#` 提示符、`UID=0`、`pwd` → `/var/root`、`exit` 干净关闭。
- `sftp`：`put` 上传 31B 测试文件、`get` 取回 `/var/jb/etc/passwd`、`ls -l` 正常。
- `annsh kill 15 406` 后 `ssh` 报 `Connection refused`——进程可控、端口关闭。
- zsh 提示 `zsh/zle` 模块缺失（行编辑增强，未推送 `/var/jb/usr/lib/zsh/`），不影响命令执行。

## 6. 配套代码改动

- `userland/src/apps/annsh.c`：新增 `mkdir [-p] PATH` 与 `chmod MODE PATH` 内建（运行期落盘场景不再需要外挂 mkdirtool）。
- `tools/k90auto/cycle.py`：`JOBS_SOURCE` 从硬编码改为可被环境覆盖（默认仍为 `rc.jobs.interactive`），`rc.jobs.ssh` 这类候选任务脚本可以直接跑整轮。

## 7. 持久化路径（未做）

- 把 jb 装进 UFS 系统镜像（`sysroot/jb` → `/jb`）刷机一次后，init 每次开机自动把 `/var/jb` 建成符号链接树，ssh/密钥经 `var.skel` 常驻——这是 `init_mount.inc` 设计的正路，代价是一次完整刷机。
- 或每次开机重复本文的运行期落盘（推送 12 件、跑 `pwd_mkdb`、起 sshd），可作为 `rc.jobs` 任务脚本或 rsh 序列固化。
