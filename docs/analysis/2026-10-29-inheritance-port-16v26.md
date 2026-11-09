# inheritance port 失败的来源：16.5 launchd 与 26 内核的线上格式错配（2026-10-29）

## 1. 结论

- 在 iOS 26 用的 12377 内核上跑 iOS 16.5 的 launchd（系统盘 `userland/system.apfs`），launchd 在 `start()` 里调用 `mach_ports_register` 失败，打印 `could not set up inheritance port` 后 abort（§3）。
- 原因是两边的消息格式对不上：16.5 的 `mach_ports_register` 在线上发一个 OOL 端口数组（由 EXC_GUARD 的 payload 反推，§5）；26 内核对同一 msgh_id 的服务端只接受三个 inline 端口描述符（§4）。
- iOS 26 用户态（`system26.apfs`）在同一内核上能过这一步。按源码与 ABI 表，26 的 `libsyscall` 发的就是三个 inline 描述符（推断，§4）。
- 16.5 用户态不在目标配置范围内，这条失败只在打包时漏写 `SYSTEM`／`SYSTEM_WINDOW` 时出现：`SYSTEM` 的默认值仍是 16.5 那份镜像。`tools/k90auto/system_guard.py` 在打包时拦下这种载荷，判据见 §2。
- boot-arg `ool_port_array_enforced=0` 只让 16.5 客户端不再被 26 内核的 `IPC_SEC_POLICY_RESTRICT_OOL_PORT_ARRAYS` 杀掉，launchd 仍然停在 `mach_ports_register`（§6）。26 配置带不带这个参数，没有做过对照。

## 2. 两份系统盘与打包检查

| 镜像 | 大小（2026-10-29） | 用户态 | launchd 版本串 |
| --- | --- | --- | --- |
| `userland/system.apfs` | 2,492,227,584 | arm64，iOS 16.5 | `libxpc_executables-2462.120.4~11`（2023-04-17） |
| `userland/system26.apfs` | 4,925,816,832 | arm64e，iOS 26 | `libxpc_executables-3102.160.5~128`（2026-07-30） |

- `system_guard.py` 的两条判据：系统盘大小必须在 4～5 GiB 之间；超过 `0xffffffff` 字节的镜像必须带 `SYSTEM_WINDOW`（loader 按分块协议传这么大的镜像）。任一条不满足，`make-payload.py` 报错退出。回放测试是 `tools/k90auto/test-system-guard.py`。
- 两份 launchd 的本地副本：`hackios-xnu-kernel/ios165/rootfs/sbin/launchd`（525,088 字节）与 `hackios-xnu-kernel/ios26/rootfs/sbin/launchd`（620,432 字节）。两者的 `start()` 是同一段代码的两次编译，下文地址两份都给。
- 2026-10-26 在 QEMU 里用 16.5 根文件系统启动 16.5 launchd，同样报 `could not set up inheritance port` 后退出。那条路径没有设备侧的 cmdline、AIR 与 loader 槽位，失败与这些变量无关。

## 3. 失败的调用

「could not set up inheritance port」在两份 launchd 里各出现一次：16.5 那份在 VA `0x10005492b`，26 那份在 `0x10006255b`，唯一的 xref 都在 `start()` 里。os_reason 的 namespace 是 7（`OS_REASON_LIBXPC`），串来自 launchd 自己的代码。`start()` 这一段有三个出口，只有第三个带这条串：

| 调用 | 16.5 地址 | 26 地址 | 失败时的表现 | 16.5 launchd 在 26 内核上 |
| --- | --- | --- | --- | --- |
| `task_set_special_port(mach_task_self, 4, 0)` | `0x100012e90` | `0x10001852c` | 打 `Could not neuter bootstrap port: 0x%x` 后 `exit(1)` | 没有出现 |
| `mach_port_construct(mach_task_self, options, 0x70507, &name)` | `0x100012eb8` → `sub_100012980` | `0x100018558` → `sub_100017FE8` | 打 `Bug in libxpc: mach_port_construct() failed` 后 `__break(1)` | 没有出现 |
| `mach_ports_register(mach_task_self, {name}, 1)` | `0x100012ed0` | `0x10001856c` | 打 `could not set up inheritance port` 后 abort | 命中 |

被登记的端口由 `mach_port_construct` 建出：flags `0x433` = `MPO_SERVICE_PORT`（`0x400`）｜`MPO_STRICT`（`0x20`）｜`MPO_INSERT_SEND_RIGHT`（`0x10`）｜`MPO_QLIMIT`（`0x02`）｜`MPO_CONTEXT_AS_GUARD`（`0x01`），`mpl_qlimit` `0x80`，服务名 `com.apple.xpc.launchd.domain.system`，`mspi_domain_type` 为 7。26 那份的 flags 是 `0x24B3`，多出 `MPO_ENFORCE_REPLY_PORT_SEMANTICS`（`0x2000`）与 `MPO_IMMOVABLE_RECEIVE`（`0x80`），名字与 context 相同。

## 4. 内核侧要求什么

- `osfmk/mach/task.defs:136-146` 用 `#if LIBSYSCALL_INTERFACE` 把这条 routine 分成两个形态：用户侧是 `mach_ports_register(target_task; init_port_set : mach_port_array_t = ^array[] of mach_port_t)`，内核侧是 `_kernelrpc_mach_ports_register3(target_task; port1; port2; port3)`。内核编译的是后者。
- 生成的 `task_server.c` 要求 `msgh_bits & MACH_MSGH_BITS_COMPLEX`、`msgh_body.msgh_descriptor_count == 3`、`Head.msgh_size == sizeof(__Request)`，三个描述符各要求 `type == MACH_MSG_PORT_DESCRIPTOR` 且 `disposition == 17`（`MACH_MSG_TYPE_MOVE_SEND`）。任何一项不符合直接返回 `MIG_BAD_ARGUMENTS`。
- 服务端拿到端口后，`osfmk/kern/ipc_tt.c` 的 `_kernelrpc_mach_ports_register3` 对每个端口调 `ipc_can_stash_naked_send`，失败返回 `KERN_INVALID_RIGHT`。§3 那个端口的类型是 `IOT_SERVICE_PORT`，策略表里 `pol_movable_send` 为 `true`，这一道能过。
- 26 用户态一侧（推断）：`libsyscall/mach/task.c:59-77` 的 `mach_ports_register()` 把名字数组截到 3 个后转调 `_kernelrpc_mach_ports_register3`；26 的 `libsystem_kernel` 里有 MIG 编号 3403 的 `__kernelrpc_mach_ports_register3` 桩（ABI 表 `docs/progress/evidence/ios26-abi/mig-26.tsv`）。桩内三个描述符的 `type` 与 `disposition` 没有逐字节反汇编核对。

## 5. EXC_GUARD 的解码

不带 `ool_port_array_enforced=0` 时，16.5 launchd 在 26 内核上收到 `EXC_GUARD AST: type=0x1 flavor=0x43 target=0x800407 code=0x2000004300800407 subcode=0x300000000000011`：

| 字段 | 值 | 含义 |
| --- | --- | --- |
| `flavor` | `0x43` = 67 | `kGUARD_EXC_DESCRIPTOR_VIOLATION`（`osfmk/mach/port.h`） |
| `subcode` 高字节 | `0x03` | `MPG_FLAGS_INVALID_OPTIONS_OOL_RIGHT`，打包方式是 `MPG_PAYLOAD(flag, a) = (flag << 56) \| a` |
| `subcode` 低 32 位 | `0x11` = 17 | `ip_type(dest_port)`，即 `IKOT_TASK_CONTROL` |
| `code` 低 32 位 | `0x00800407` | 发送方空间里目的端口的名字（`target` 同值） |

`flag` 为 `0x03` 对应 `osfmk/ipc/ipc_policy.c` 里 `!ip_is_port_array_allowed(dest_port)` 的分支，判据是目的端口类型异于 `IOT_CONNECTION_PORT_WITH_PORT_ARRAY`。被杀的消息是 launchd 发给自己 task 控制端口的、带 `MACH_MSG_OOL_PORTS_DESCRIPTOR` 的消息：`ipc_kmsg.c` 对每个 OOL 端口描述符给 `send_dsc_port_arrays_count` 加一，计数非 0 且目的端口类型不符就触发检查。

## 6. 关掉守卫之后

- `ool_port_array_enforced` 只作用于 `ipc_sec_policy_should_apply_ool_port_array()` 这一个回调。置 0 之后 §5 的检查不再拦，消息继续走 `ipc_kmsg_copyin_body`，OOL 端口数组照原样搬成内核描述符。
- 实测：带这个参数后日志里没有 `EXC_GUARD`，`mach_ports_register` 仍返回非 0，停在同一处。
- 推断：这条消息到服务端后不满足 §4 的 MIG 检查，返回 `MIG_BAD_ARGUMENTS`。日志没有打出返回值。前提是带 OOL 端口数组的那条消息就是 inheritance port 的登记消息：`start()` 这一段发给自己 task 控制端口的消息只有 §3 的三个，前两个的 defs 里没有端口数组。
- 要直接确认，需要在 `_kernelrpc_mach_ports_register3` 或 `ipc_kobject_server` 加一处临时打印（返回值、`msgh_id`、`msgh_descriptor_count`），这一步没有做。
