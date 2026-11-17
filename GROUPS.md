# 双设备共同冲击分析

现有单设备接口、异常、观测修订、窗口及证据规则见 README.md，均须保持。当前工程尚未实现本文件的新入口；group_examples.py 只提供输入、解析预期和调用核验，不包含联合推断答案。

## 新入口与值

在以下现有公开模块增加入口：

- runtime_models.registry.register_group(connection, revision_id, device_models, shock_probs) -> GroupRef
- analysis_tasks.service.freeze_group(connection, task_id, group_ref, sequences, prefix, windows) -> 不可变绑定值
- analysis_tasks.service.analyze_group(connection, task_id, *, before_commit=None) -> dict
- run_reports.reader.read_group_report(connection, task_id) -> dict

GroupRef 在 runtime_models.schema 中公开，是不可变值，具有 revision_id、digest 两个字符串属性；digest 为规范组内容的 SHA256 十六进制摘要。同内容引用应相等。绑定值的相等性表示相同的完整冻结请求，不指定内部布局。

device_models 是按顺序包含恰好两项的列表或元组，每项为 (device_id, ModelRef)。device_id 为不同的非空字符串；两个设备可引用同一个模型。模型引用必须已登记且摘要正确；每个模型限1～2状态，所有段长键限1～2，沿用原模型的状态、表顺序和概率。组修订号为非空字符串。组登记使用独立于单模型修订号的命名空间。

shock_probs 是恰好四项的列表或元组，顺序为：空集、仅第一个设备、仅第二个设备、两个设备。概率只接受有限、非负 int/float，排除 bool；按 V1 的1e-12行和容差校验。为定义严格的组内随机过程，使用时将接纳的冲击、转移、段长及发射概率行各除以其行和；不得改写原单设备模型或改变V1行为。正概率无论多小均按正支持处理，不用数值阈值删边。它与设备顺序、ID、固定模型引用共同构成组内容。输入应复制；同组修订号同内容幂等，异内容拒绝，不允许替换。

## 联合运行机制

每台物理相位为原状态及包含当前位置发射的剩余寿命。在两个相邻采样位置之间，独立于过去抽取一次 shock_probs 指定的冲击子集。对每台设备：

- 剩余寿命为1，或在冲击子集中：从当前状态按原 transition 抽取新状态，再按新状态 durations 抽取新段长。
- 否则：状态不变，剩余寿命减1。

给定冲击子集与源相位，两台设备的转移及段长抽样独立。自然到期与冲击重合只更新一次，同状态重置仍算更新。更新是设备事件，不是状态变化，也不等同于抽中了非空冲击。最后一次观测后不生成边，尾段无需完成。

初始联合相位服从上述采样边界核的唯一平稳分布，允许瞬态相位及周期过程；平稳分布不唯一则登记拒绝，不得用单设备平衡分布乘积代替。零质量的瞬态相位不导致拒绝。每位置的发射沿用各自模型；给定联合相位，两台发射独立。采样轴只使用记录位置，不按 time 差插值。

## 冻结、统计与归档

sequences 是与设备顺序对应、恰好两个已有 SequenceRevision 的列表或元组，可以引用同一序列。分别截取排序后版本的前 prefix 条记录；两条前缀的 time 列表必须完全相同，不比较前缀外时间。prefix 为非布尔整数，0≤prefix≤32且不超过任一版本长度。windows 沿用 WindowRequest，至多两项，保留次序、重叠和重复；空前缀只容许空窗口。冻结保存组修订、设备顺序及两份确切快照，不自动绑定最新版本。

所有统计共同条件于两台全部冻结观测；每窗口依设备顺序输出该设备状态占用及更新次数。dimensions 逐窗口、逐设备连接：该设备按原状态顺序的 [窗口号,设备ID,"occupancy",状态]，再接 [窗口号,设备ID,"renewals",""]。mean 与完整 covariance 使用同序，包含跨设备、跨窗口项。占用按当前位置支付；更新按新段起点支付且1≤t<prefix，起点0不支付；窗口为左闭右开。空窗口确定为零；每设备窗口占用之和等于窗口长度，且该和与任何维度协方差为零。

有限统计的绝对误差不超过1e-8。全部冻结观测的真零证据拒绝且不发布，极小正证据须接纳并沿用 V1 的 evidence 表示；空前缀证据为1。空窗口列表仍核验全部观测，不跳过零证据判定。

报告至少有以下字段；除新增组身份外，正文与回执语义沿用 V1：

- task_id、input_id、prefix、windows、dimensions、evidence、mean、covariance、receipt。
- group_ref：[组修订号,摘要]。
- devices：依设备顺序的列表，每项包含 device_id、model_ref（[原模型修订号,摘要]）、states（原状态名列表）、sequence_ref（[序列号,版本]）、snapshot_id、records（快照记录的 to_data() 列表）。

input_id 覆盖完整冻结身份，包含任务ID、组引用、设备顺序、模型引用、两份快照和有序窗口。receipt 为 task_id、input_id、report_sha256、receipt_id 四字段字典；正文指不含 receipt 的完整报告，其规范编码与摘要、回执ID计算规则沿用 run_reports.publication。摘要不规定组内部序列化布局，但必须确定且覆盖全部组内容。

源更正、输入或返回值修改、关闭重开不得改变旧绑定和报告。组任务与原单设备任务共用 task_id 命名空间；同ID相同绑定幂等，异绑定或异任务种类冲突。读取只读已发布值，不能重跑推断；重复分析已发布任务返回原成果且不再调用 before_commit。两类入口不能将另一类任务误读为本类；跨类调用以 ValueError 拒绝。

发布正文、回执及已发布资格须共同提交；before_commit 与 V1 有相同调用时机和使用限制，抛出时整次回滚并可重试。冻结失败不留下新任务或新快照；登记失败不改变任何已登记内容。

结构、概率、规模或不唯一平稳分布的登记拒绝可用 ModelDefinitionError 或其子类；同组ID异内容用 ModelRevisionConflict；未知或错误组/模型引用用 LookupError。非法冻结请求（含错位时间）用 InvalidTaskRequest；未知序列版本用 LookupError，任务冲突用 TaskIdConflict，未知任务用 UnknownTask。零证据、发布失败、未发布读取和归档完整性分别沿用 ZeroEvidenceError、PublicationError、ReportNotPublished、ArchiveIntegrityError。不得把合法周期过程或带瞬态相位的唯一平衡过程当错误。

## 解析样例与业务验证

两台设备均为单状态 run、恒定段长2、恒定发射 x，两条时间相同的 xx，窗口 [0,2)。dimensions 为 [[0,"A","occupancy","run"],[0,"A","renewals",""],[0,"B","occupancy","run"],[0,"B","renewals",""]]；mean 为 [2,2/3,2,2/3]，两项更新方差均为2/9，所有占用相关协方差为0，证据为1。

- shock_probs=(1/2,0,0,1/2)：两项更新的协方差为2/9。该合法核有瞬态非同步相位。
- shock_probs=(1/4,1/4,1/4,1/4)：两项更新的协方差为0。
- 同样设备，shock_probs=(1,0,0,0)：相位关系存在两个闭类，平稳分布不唯一，登记拒绝。

group_examples.py 提供这些原始输入及一个信息性发射、混合段长的短例。运行 python3.11 -B group_examples.py --fixtures 可查看素材，运行 python3.11 -B group_examples.py --check 可在实现新入口后核验上述解析报告、拒绝边界、幂等与返回值隔离。此核验不是完整正确性参照。

交付联合实现及必要交接不变量说明，并提供独立 Fraction 短路径枚举核账：从联合平稳初相位出发，枚举短例的冲击及各设备转移/段长，以全部观测加权，直接累计完整奖励向量及外积；核对信息性发射、混合段长、同状态更新、到期与冲击重合、重复窗口、空前缀和真零/极小正证据。参照不得调用生产联合推断来充当期望值，不要求枚举长输入。

使用原有 .pointwise-runtime.json，保留 version、kind、setup、verify、demo 的格式约定。verify 须同时运行完整原回归、解析样例和独立联合核账，保持失败退出码；可通过自选包装入口组合。demo 展示真实共享/独立报告的不同交叉协方差，以及更正一台观测后关闭重开仍可执行旧任务、读取旧成果；同时核验新任务使用新版本。对 before_commit 发布失败验证无半份成果、重开后可重试。允许全量重算、展开有限联合相位及复用原矩公式，不要求性能优化；不增加预测、参数学习、在线或多工作者能力。
