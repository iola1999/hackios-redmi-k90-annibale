# MiCode K90 官方内核源码调研（2026-10-24）

本文记录小米官方（MiCode）公开的 K90 内核源码、它与项目已固定的 OnePlusOSS SM8750 厂商源码的文件对应关系，以及对本项目有用的部分。调研只读，没有改代码、没有操作设备。本地浅克隆保存在 Git 忽略的调研归档目录，目录内 `ARCHIVE-MANIFEST.txt` 记有主仓 HEAD 与各归档文件的 sha256，可用来复核本文引用的快照。

## 1. 来源

- 主仓 [MiCode/Xiaomi_Kernel_OpenSource](https://github.com/MiCode/Xiaomi_Kernel_OpenSource) 分支 `annibale-w-oss`，HEAD `f66f8c8bcbe38044fab61d44ea7f7c224f82b3ea`，提交说明「Kernel: Xiaomi kernel changes for REDMI K90 / POCO F8 Pro Android W」，2026-03-13，Linux 6.6.57。
- 设备树仓 [MiCode/kernel_devicetree](https://github.com/MiCode/kernel_devicetree) 分支 `annibale-w-oss`，HEAD `32fd4ddcedd46baa579643b3894c37c0fccccb91`。提交说明含「Patch based on QualComm release TAG: LA.VENDOR.15.4.0.r1-15000-r1.0.r1_00044.1」，对应的 QTI tag 没有单独核对。
- 显示驱动仓 [MiCode/vendor_opensource_display-drivers](https://github.com/MiCode/vendor_opensource_display-drivers/tree/4a586833e811c8ec53e6924116505b5724a90c2d) 分支 `annibale-w-oss`，HEAD `4a586833e811c8ec53e6924116505b5724a90c2d`，434 个文件，只有 SDE，没有 adreno。
- 比较基准：项目固定的 [OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8750](https://github.com/OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8750/tree/d50b305f7da9e14715a25120a4ac7b1a4b8b97c3)（`d50b305`）。厂商目录的 `vendor-revision.json` 只记录仓库与 SHA，没有逐文件的上游来源。
- 检索范围：MiCode 组织下 80 个仓库的名称（没有 graphics／gpu 相关的仓库）加上述三个仓库的 `annibale-w-oss` 分支。

## 2. MiCode 源码里的结构与 GPU 相关声明

- 构建继承：主仓 `build.config.msm.annibale` 引用 `msm-kernel/build.config.msm.sun`（SM8750 平台代号 sun）；`annibale.bzl` 加载 `xiaomi_sm8750_common.bzl` 与 `sun.bzl`。
- 主仓结构：`arch/arm64/boot/dts/vendor` 是指向设备树仓的符号链接；`modules.list.msm.annibale` 没有 GPU 模块；`sun.bzl` 的模块清单有 gpucc-sun.ko、arm_smmu.ko、secure_buffer.ko，没有 msm_drm 与 kgsl。
- GPU 驱动不在 MiCode 源码里：范围内找不到 gen8 的 gmu／hfi／hwsched 与 kgsl 核心；主仓 `drivers/gpu/drm/msm/adreno` 只有 a2xx～a6xx（主线 6.6）；设备树仓 `qcom/sun.dtsi` L2617 只有空节点 `msm_gpu: qcom,kgsl-3d0@3d00000 { };`。GPU 驱动的参考仍是 OnePlusOSS 那份，QTI googlesource 的 msm-modules/graphics 镜像也有同名 `adreno_gen8_hwsched.c`（如 [15.0.0 标签副本](https://android.1.googlesource.com/kernel/msm-modules/graphics/+/refs/tags/android-wear-15.0.0_r0.12/adreno_gen8_hwsched.c)），与 K90 的 gen80000 固件是否配套没有核对。
- GPU SMMU（设备树仓 `qcom/msm-arm-smmu-sun.dtsi`）：节点 `kgsl_smmu@3da0000`，reg `0x3da0000` 长 `0x40000`，`qcom,use-3-lvl-tables`；电源域 `GPU_CC_CX_SMMU_GDSC`，时钟 `gpu_cc_hlos1_vote_gpu_smmu`，带宽路径 `MASTER_GPU_TCU`→`SLAVE_EBI1`。节点注释写明：GDSC 开启且 CPU 进入 cpuidle 时必须保持 DDR 带宽投票，否则 DDR 可能掉电。`qcom,actlr` 为 `<0x000 0x3ff 0x32B>`，注释「All CBs of GFX: +15 deep PF」。
- `gpu_qtb@3de8000`：reg `0x3de8000` 长 `0x1000`，`qcom,stream-id-range = <0x0 0x400>`，`qcom,iova-width = <49>`。
- `iommus` 的含义：`kgsl_smmu` 的 `#iommu-cells = <2>`，主仓 `drivers/iommu/arm/arm-smmu/arm-smmu.c` L2646-L2658 的 `arm_smmu_of_xlate` 把 `args[0]` 装入 `ARM_SMMU_SMR_ID`、`args[1]` 装入 `ARM_SMMU_SMR_MASK`。因此 debug 用例 `usecase5_kgsl` 的 `iommus = <&kgsl_smmu 0x7 0x0>` 是 stream ID 0x7、掩码 0 的精确匹配，与 CB7 无关，不能用来推断 GPU 的 CB 路由；`usecase4_apps_secure` 的 `qcom,iommu-vmid = <0xa>`（注释 VMID_CP_PIXEL）同样只是 apps SMMU 的 debug 用例。
- CB 分配：主仓 `arm-smmu-qcom.c` L471 起的 `qcom_adreno_smmu_alloc_context_bank` 对 GPU 设备取 start=0、count=2，注释写明 CB0／CB1 留给 GPU 切换页表，非 GPU 设备从 CB2 起。

## 3. K90 专有的设备树内容

固定比较集之外、MiCode 新增的文件（都在设备树仓）：

- `qcom/annibale-sm8750.dtsi`：mitee OEM VM（`oem_vm_mem@f8800000` 0x3800000、`oem_vm_shm@fc000000` 0x400000、gunyah-label=3、binding-core=<4 5 6>）与 gh-secure-vm-loader 的 memory-region 引用。运行时是否实际使用没有查证。
- `qcom/annibale-sm8750-overlay.dts`：`qcom,msm-id` 四组（618／639／0x100026a／0x100027f）与 `xiaomi,miboard-id = <0xB 0>`。
- `reserved_memory_control/sun_standard_node_info.txt`：sun 保留区的名称与大小清单（hwfence-shmem 0x2dd000、gpu_microcode_region 0x2000、tz_merged_region 0x600000、trust_ui_vm_region 0x5000000 等）。
- 保留区 `qcom/sun.dtsi` L3895 的 `gpu_microcode_region@9b09a000`（no-map，0x2000）与 L3981 `hwfence-shmem`（no-map，0xd4e23000、0x2dd000）：两个 label 在 sun.dtsi 与 annibale dtsi 里没有引用节点，主仓 drivers/ 里也没有使用方。用途要从 graphics 侧的源码确认；保留区清单不能作为 XNU 使用这些区域的依据。
- 没有读的 dtsi：`qcom/sm8750-xiaomi-common.dtsi`、`qcom/sm8750-ir-sensor-common.dtsi`、`qcom/annibale-charger-common.dtsi`、`qcom/annibale-nfc-pinctrl.dtsi`。查充电状态时可以先读 `annibale-charger-common.dtsi`。

## 4. 与固定厂商源码的文件对应

MiCode 一侧都在主仓 `f66f8c8`，设备树文件在设备树仓。只做了文件级比较，运行影响没有逐个分析。

| 固定厂商源码 | MiCode 文件 | 差异 |
|---|---|---|
| qcom_scm.c | drivers/firmware/qcom_scm.c | 44 行：固定侧独有 `qcom_scm_update_rollback_version`（BOOT 0x1E）；READ_ONCE／smp_load_acquire 写法不同 |
| qcom_scm-smc.c | drivers/firmware/qcom_scm-smc.c | 5 行：MiCode 独有小米的 `tzdbg_log_wq` |
| arm-smmu-qcom.c | drivers/iommu/arm/arm-smmu/arm-smmu-qcom.c | 2 行：compat 表 |
| arm-smmu.c | drivers/iommu/arm/arm-smmu/arm-smmu.c | 55 行：固定侧有 OnePlus 的 pm-runtime autosuspend 与 EPROBE_DEFER 私有补丁；对 context 复位行为的影响没有逐段评估 |
| qtee_shmbridge.c | drivers/firmware/qtee_shmbridge.c | 字节相同 |
| secure_buffer.c | drivers/soc/qcom/secure_buffer.c | 字节相同 |
| io-pgtable-arm.c | drivers/iommu/io-pgtable-arm.c | 字节相同 |
| qcom-io-pgtable-alloc.c | drivers/iommu/qcom-io-pgtable-alloc.c | 字节相同 |
| qcom-io-pgtable-arm.c | drivers/iommu/qcom-io-pgtable-arm.c | 字节相同 |
| secure_buffer.h | include/soc/qcom/secure_buffer.h | 字节相同 |
| qtee_shmbridge.h | include/linux/qtee_shmbridge.h | 字节相同 |
| msm-arm-smmu-sun.dtsi | 设备树仓 qcom/msm-arm-smmu-sun.dtsi | 字节相同 |

- `qcom_scm_assign_mem`（MiCode `qcom_scm.c` L1234）、`qcom_scm_assign_mem_regions`（L1327）与 `gh_scm_assign_mem` 声明（qcom_scm.h L294）两侧都有，接口行为的差异没有评估。
- 页归属移交链（固定厂商副本）：`kgsl_sharedmem.c` 的 `kgsl_lock_sgt`（L596-L624）对 sg_table 调用 `hyp_assign_table`（L604），后者由 secure_buffer.c L586 导出，内部经 `_hyp_assign_table` 逐项移交；`kgsl_unlock_sgt`（L634）同样调用它归还归属。secure 分配路径在 `kgsl_sharedmem.c` L1586、L1717 调用 `kgsl_lock_sgt`，`adreno.c` L3852-L3893 在 secure 恢复路径（`KGSL_MEMDESC_HYPASSIGNED_HLOS` 条件）调用它。HFI 文件里没有直接的 SCM 调用。
- `kgsl_iommu.c`、`kgsl_sharedmem.c`、`adreno_gen8_hwsched_hfi.c`、`sun-gpu.dtsi` 四个固定副本与本地保存的 OnePlus 完整 tree JSON（`d50b305`，`truncated=false`）逐路径比对 git blob SHA1 一致；tree 的网络侧来源没有重新验证。

## 5. 对本项目的用处

- 安全移交：secure_buffer.c、qtee_shmbridge.c 及其头文件两侧字节相同，可直接用来核对页移交的实现，§4 的移交链是厂商驱动按页移交的写法。
- 电源与 SMMU：§2 的 GDSC、投票时钟、带宽路径与 DDR 投票约束是官方设备树的静态声明，可用来核对 SMMU 配置与电源依赖；实际寄存器读回与断电恢复顺序以真机为准。
- 局限：MiCode 源码不含 GPU 驱动；逐文件上游来源、`qcom_scm*.c` 与 `arm-smmu.c` 差异的影响、保留区的使用方都没有核实。
