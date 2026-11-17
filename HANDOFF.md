# 双设备共同冲击分析交接说明

本文件记录 GROUPS.md 联动实现的交接不变量，供后续维护者核账。V1 单设备语义见 README.md，组语义见 GROUPS.md；本说明不替代二者，只列出实现层必须保持的不变量及对应模块位置。

## 模块分工

- `runtime_models/groups.py`：组内容规范化（恰好两台设备、设备ID非空互异、冲击概率四项且按 V1 的 1e-12 行和容差接纳）、组摘要（设备顺序+设备ID+固定模型引用+冲击概率的规范 JSON 之 SHA256）、组模型规模限制（1～2 状态、段长键 1～2）。
- `runtime_models/registry.py`：`register_group`/`resolve_group`。登记顺序：结构校验 → 解析模型引用（未知或错误引用为 LookupError）→ 规模校验 → 构造联合采样核并求解唯一平稳分布（不唯一则 StationaryDistributionError）→ 写 `group_revisions` 表（独立命名空间，同内容幂等、异内容 ModelRevisionConflict）。登记失败不落任何行。
- `joint_inference/kernel.py`：把接纳的冲击/转移/段长/发射概率行各除以其行和（Fraction 精确），展开联合相位（两设备残寿命相位的乘积，≤16 个）与带双设备更新标志的联合边。初态是该核的唯一平稳分布，由精确高斯消元判秩保证唯一；瞬态相位零质量合法，周期链合法；不用单设备平衡乘积代替。
- `joint_inference/evidence.py`、`joint_inference/moments.py`：70 位 Decimal 逐步缩放前向证据与同一轨迹一阶/二阶矩积累，沿用 V1 的缩放、证据表示（mantissa/exponent/log/probability）与 1e-50 归一核对。真零证据抛 ZeroEvidenceError 且不发布；极小正证据照常接纳。
- `analysis_tasks/service.py`：`freeze_group`（校验恰好两条已有序列版本、prefix 为非布尔整数 0≤p≤32 且不超过任一版本长度、两条前缀 time 列表完全一致、窗口至多两项；双快照在同一事务内封存）与 `analyze_group`（冻结完整性核验 → 联合核 → 证据 → 矩 → 装配 → 发布）。
- `run_reports/group_windows.py`、`group_report.py`、`validation.py`、`publication.py`、`reader.py`：维度布局（逐窗口逐设备：占用按原状态序，再接 renewals）、报告装配与核账、发布与一致读。

## 运行机制不变量

- 每个采样边界（相邻两记录位置之间）独立于过去抽取一次冲击子集（空/仅A/仅B/双），两台设备共用该次抽取；给定子集与源相位，两设备的转移与段长抽样相互独立。
- 设备在边界更新 ⟺ 剩余寿命为 1 或设备在本次冲击子集中；到期与冲击重合只计一次更新；同状态重置也算更新；更新是设备事件，不是状态变化，也不等同于抽中非空冲击。联合边按 (目标相位, A更新, B更新) 聚合，同一目标相位可同时存在更新边与非更新边（衰减负 1 与重置同长同态），不得合并。
- 占用按当前位置支付；更新按新段起点支付且 1≤t<prefix，起点 0 不支付；最后一次观测后不生成边，尾段无需完成。窗口左闭右开；空窗口全维确定为零。
- 全部冻结观测（两台、全部位置）共同条件化所有统计；均值与完整协方差同序，含跨设备跨窗口项。每设备每窗口占用均值之和等于窗长，且该和与任何维度的协方差为零（发布前与读取时均核验）。
- 有限统计绝对误差目标 1e-8；协方差相减后才转浮点。

## 身份与归档不变量

- 组任务与单设备任务共用 task_id 命名空间：同 ID 同绑定幂等，异绑定或异种类为 TaskIdConflict。`analyze`/`analyze_group`/`read_report`/`read_group_report` 跨类调用以 ValueError 拒绝。
- `input_id` 覆盖完整冻结身份：任务ID、组引用、设备顺序、模型引用、两份快照、有序窗口（GroupTaskBinding.to_data 的 SHA256）。报告正文（不含 receipt）的规范编码、report_sha256 与 receipt_id 计算沿用 run_reports.publication；receipt 为 task_id、input_id、report_sha256、receipt_id 四字段。
- 发布正文、回执与已发布资格在同一事务提交；before_commit 在写入后提交前调用，抛错整体回滚不留半份成果，任务保持冻结可重试；已发布任务重复 analyze_group 返回原成果且不再调用该钩子。读取只读已发布值，不重跑推断；修改返回字典不回写。
- 源更正、输入或返回值修改、关闭重开不改变旧绑定与旧报告；冻结保存组修订、设备顺序与两份确切快照，不自动绑定最新版本。

## 独立核账

`tests/group_oracle.py` 为独立 Fraction 短路径枚举：自行求解联合平稳初相位（不调用生产联合推断代码），枚举冲击子集与各设备转移/段长，以全部观测加权，直接累计完整奖励向量及外积。`tests/test_group_analysis.py` 用它核对信息性发射、混合段长、同状态更新、到期与冲击重合、重复窗口、空前缀、真零/极小正证据、全量条件化与 32 点上限；覆盖共享 vs 独立冲击的不同跨设备协方差（2/9 vs 0）。

## 运行清单

`.pointwise-runtime.json` 的 verify 为 `run_checks.py`：依次运行完整 unittest 回归（含 V1 原 17 项与联合核账）和 `group_examples.py --check` 解析样例核验，任一步失败即返回非零。demo 为 `demo.py`：先跑 V1 流程，再演示共享/独立冲击报告的不同交叉协方差、单台观测更正后关闭重开仍执行并读取旧任务成果、新任务使用新版本，以及 before_commit 发布失败无半份成果、重开后可重试。
