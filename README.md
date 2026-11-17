# 设备运行观测分析归档

Python 3.11标准库工程。登记有限显式持续时间模型，接纳观测更正，冻结输入，计算条件占用与真实更新的联合统计，并在SQLite中归档可重开读取的成果。

## 运行

在项目根目录执行：

```sh
python3.11 -B -m unittest discover -s tests -t . -v
python3.11 -B demo.py
```

测试与演示的磁盘数据库仅放在各自临时目录，结束后清理。演示先冻结任务，再更正观测，模拟提交前失败，关闭重开后执行旧新任务并读取成果。

## 公开接口

连接由archive.connect(path=":memory:")创建，使用者负责connection.close()。连接应保持该函数设置的自动提交模式；业务入口自行管理事务，不要在调用外包裹自行提交的事务。返回的引用及绑定为不可变值，报告为独立字典。

- runtime_models.registry.register_model(connection, revision_id: str, definition: ModelDefinition) -> ModelRef
- observations.sequences.revise_observations(connection, sequence_id: str, records: Iterable[ObservationRecord]) -> SequenceRevision
- analysis_tasks.service.freeze(connection, task_id: str, model_ref: ModelRef, sequence_revision: SequenceRevision, prefix: int, windows: Iterable[WindowRequest]) -> TaskBinding
- analysis_tasks.service.analyze(connection, task_id: str, *, before_commit: Callable[[], None] | None = None) -> dict
- run_reports.reader.read_report(connection, task_id: str) -> dict

before_commit是在正文、回执及状态写入后、事务提交前调用的可选故障测试钩子。它只应用于抛出故障或从其他连接观察已提交状态，不得操作当前连接或提交事务。已发布任务不再运行该钩子。

```python
from archive import connect
from examples import two_state, observation_batch
from runtime_models.registry import register_model
from observations.sequences import revise_observations
from analysis_tasks.requests import WindowRequest
from analysis_tasks.service import freeze, analyze
from run_reports.reader import read_report

connection = connect()
try:
    model = register_model(connection, "machine-v1", two_state())
    sequence = revise_observations(connection, "machine", observation_batch("abba"))
    freeze(connection, "analysis-1", model, sequence, 4,
           [WindowRequest(0, 3), WindowRequest(1, 4)])
    result = analyze(connection, "analysis-1")
    assert read_report(connection, "analysis-1") == result
finally:
    connection.close()
```

## 输入与身份

ModelDefinition(states, transition, durations, emissions)接受有限列表或元组。状态为有序非空唯一字符串；transition是方阵；durations每状态一行(正整数段长, 概率)；emissions每状态一行(非空符号, 概率)。概率接受int/float，排除bool，必须有限、非负，每行和与1之差不超过1e-12。键不能重复。段间转移须不可约，允许周期链及自转移。输入复制为规范不可变元组。平稳方程利用离对角概率构造，并对原转移表核验1e-10残差；不依赖迭代收敛。同模型修订ID同内容幂等，异内容拒绝。

ObservationRecord(identity, source_revision, time, symbol)的身份、符号为非空字符串，源修订及时间为带符号64位整数，排除bool。源修订按整数比较。序列内不同身份的最终时间必须不同，按时间排序后形成确定版本；推断采样位置为该版本的0至N-1，不对时间差插值。同身份同源修订异内容，包括历史旧版及批内冲突，整批拒绝。所有记录先校验，再提交；旧版不覆盖最高版，纯重复/旧版不增加序列版本。历史接收过的旧版内容也保留用于冲突检查。更高源修订形成新的记录引用及版本，即使符号不变。首次空批次建立空版本。

freeze必须指定已有模型引用、已有序列版本及合法前缀，不自动选择最新版本。WindowRequest(left, right)满足0<=left<=right<=prefix，边界为非布尔整数。保留请求顺序、重叠与重复。相同任务ID相同绑定幂等，异绑定拒绝。快照保存确切记录，更正与重开不影响旧绑定。空前缀证据为1，只允许(0,0)窗口。

## 条件运行统计

段间平稳质量为pi，平均段长加权和为mu。初始状态s、含当前发射的剩余寿命r具有质量pi[s]*P(D_s>=r)/mu。剩余寿命大于1时递减；等于1时按转移矩阵及新段长分布更新。相同状态的新段也算更新。末次观测后不生成边，未完成尾段合法。

所有窗口共同条件于全部冻结观测。窗口按采样位置解释，左闭右开。占用按发射位置支付；更新按新段起点支付，且1<=t<N，截取起点不支付。输出维度逐窗口连接：每个状态的占用，随后是renewals。dimensions中每项为[窗口编号, "occupancy", 状态]或[窗口编号, "renewals", ""]。

mean与covariance使用相同维度顺序，后者为完整联合协方差，包括跨窗口及同状态隐藏更新的波动。窗口外观测也参与条件化。空窗口全部为零，重复窗口保持完全相关。有限核账值绝对误差目标为1e-8。

推断使用70位Decimal逐步缩放，并沿相同轨迹积累完整一阶和二阶矩；协方差相减后才转浮点。evidence包含十进制mantissa字符串、整数exponent、log_evidence、probability和probability_representable。证据为mantissa*10**exponent，正证据不能表示为普通浮点时probability为None，标志为false，不能以0替代。全部路径质量确实为零才拒绝。

报告包含输入指纹、模型和序列引用、快照、前缀、状态/窗口/维度顺序、证据、mean、covariance、receipt。receipt保存任务、输入指纹、正文SHA256和确定性回执ID。报告层验证身份、形状、有限性、对称性、方差及占用守恒，不重新推断，也不截零掩盖错误。

## 失败及归档

结构错误为ModelDefinitionError，概率或不可约性错误为其子类ProbabilityValidationError；平稳求解错误为StationaryDistributionError。同ID异内容为ModelRevisionConflict；未知或错误模型引用为UnknownModelReference。存储模型指纹不一致为ModelRegistrationError。

观测错误为InvalidObservation、RevisionConflict或SequenceConsistencyError。未知序列版本为LookupError；快照错误为SnapshotReferenceError。非法冻结请求为InvalidTaskRequest，同任务ID冲突为TaskIdConflict，未知任务为UnknownTask。

真零证据为ZeroEvidenceError，数值异常为InferenceNumericalError/ArithmeticError；冻结输入不一致为AnalysisExecutionError。发布前核账拒绝为ReportValidationError。提交前故障为PublicationError，原异常保留在__cause__。没有报告为ReportNotPublished；归档正文、回执或绑定不完整为ArchiveIntegrityError。

模型登记失败不覆盖旧模型；观测批次失败不改变任何记录或版本；冻结失败回滚新快照。计算失败不创建报告。发布用同一事务提交报告、回执及任务已发布状态，失败整体回滚，任务继续保持冻结可重试。read_report在一致读事务中读取归档值，不运行推断；修改返回字典不能回写。已发布任务再次analyze返回同一成果和回执。

## 模块与回归

runtime_models负责模型结构、概率、平稳分布、持久化及登记；observations负责记录、整批更正、版本、快照及存储；analysis_tasks负责请求、绑定、目录、存储及编排；duration_inference负责初始残寿命、相位边、证据及联合矩；run_reports负责窗口奖励、报告核账、发布和读取。archive.py提供连接和可嵌套事务边界。

- tests/test_preparation.py：登记、更正、整数修订、不可约性和整批冲突。
- tests/test_duration_analysis.py：平衡截取、隐藏更新、尾段、端点、重复与重叠窗口、全观测条件化、证据和冻结边界。
- tests/test_report_validation.py：交接身份、矩阵、守恒、归档完整性和内存数据库回滚重试。
- tests/test_archive.py：真实磁盘关闭重开、冻结新旧口径、读取隔离及提交前失败重试。
- tests/oracle.py：Fraction独立枚举初始段长和年龄、真实更新以及未完成尾段，不调用生产推断内核。

不提供参数学习、模型选择、在线计算、不规则采样插值、预测、告警或可视化。
