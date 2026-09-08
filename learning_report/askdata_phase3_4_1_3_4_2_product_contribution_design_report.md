# Phase 3.4.1–3.4.2 Product Contribution Design Report

本阶段交付 Product Contribution 的输入契约与 Policy 设计。**没有实现 S3 calculator 或公式，没有修改 S1/S2、基础契约或测试，没有执行 SQL、数据库查询或测试套件。**

报告区分现有能力与未来实现要求；文中的新输入容器、具体 Policy profiles、广播 Evidence 扩展及计算步骤均为设计，不是已经新增的代码。

**Business Scope Report：** V1 仅支持 Sales Contribution，表示一个品类或产品的实付销售额在指定总体销售额中的占比。业务语义为 actual_paid_sales，实际聚合必须为 SUM(paid_amount)。不支持 profit、margin、risk contribution，也不产生 alert、risk、recommendation。

未来唯一输出为 BusinessSignal(signal_type=product_contribution)，computed_value 仅有 contribution_rate。公式定义为 part_sales / total_sales；本轮不求值。

## 1. 输入契约

拟新增 ProductContributionInput，作为两个既有 SignalInput 的薄容器：

```text
ProductContributionInput（拟议结构，未实现）
  parts: SignalInput   必填
  total: SignalInput   必填

SignalInput（已存在）
  context: BusinessContext
  selection: SignalSelection
  declarations: list[InputDeclaration]
```

不重复添加 metric 名称、分母数值、完整性布尔值或自行生成的 result_id。既有 [SignalInput](D:/agent_study/askdata_studio/backend/app/querying/business_signals/models.py:278)保存各自 Context 身份与捕获事实；两个结果不合并为一次执行。

| 项目 | parts | total |
| --- | --- | --- |
| 职责 | 指定总体在唯一产品维度上的完整分区 | 同一总体的独立全局销售总额 |
| query_grain | grouped | global_aggregate |
| grouping_columns | 恰好一个获准 category 或 product_id 来源 | [] |
| metric selection | 明确的 SUM(paid_amount) column_id | 明确的 SUM(paid_amount) column_id |
| key_column_ids | {category: parts_key_id} 或 {product_id: parts_key_id} | {} |
| 行数 | 至少一个可定位 key，且不超过 numeric_rules.max_parts | 恰好一行 |
| auxiliary_column_ids | 默认 {}；不通过辅助列自动推导覆盖证明 | 默认 {}；额外列不自动成为 key 或分母 |

parts 与 total 的 result_id、column_id、context_digest 分别保留。column_id 属于对应 result_id，不能跨执行按 alias 匹配。total 不从 parts 加总生成，也不从任意一行挑选出来。

Policy、ContextCompatibility 和 AlignmentResult 独立于该容器传入未来入口：

```text
compute_product_contribution(
  inputs: ProductContributionInput,
  compatibility: ContextCompatibility,
  alignment: AlignmentResult,
  policy: ProductContributionPolicy
) → list[BusinessSignal]
```

这是后续接口设计，当前没有新增函数。必填角色缺失、None 或类型不正确属于调用契约错误；合法 Context 的空/未知 rows 属于业务证据不足。两者都不触发查询补齐，不伪造 result_id。

## 2. Policy

复用已有 [ProductContributionPolicy](D:/agent_study/askdata_studio/backend/app/querying/business_signals/policies.py:359)，不另建平行 Policy 模型。拟定义两个具体 profile：

| profile / version | parts 的唯一分区 |
| --- | --- |
| category_sales_contribution_v1 / 1 | category |
| product_sales_contribution_v1 / 1 | product_id |

| Policy 域 | V1 设计 |
| --- | --- |
| signal_type / required_roles | product_contribution / [parts, total] |
| supported contract versions | 当前 ResultContract、BusinessContext、BusinessSignal 版本 1 |
| metric_rules | 两角色均 actual_paid_sales、明确来源、实际 SUM |
| relationship_rules | divide；parts → total；equivalent；相同 metric_id |
| grain/key rules | 单一获准 parts 分区；独立无键 global total |
| time_rules | same_bounded_period，date、Gregorian、bounded_range |
| filter_rules | mapped_equal；明确的已支付条件；additional_conditions=reject；HAVING=reject |
| completeness_rules | complete_query_output、require_untruncated、require_known_equal_counts、require_complete_partition_and_total |
| declaration_rules | 两角色均需 unit、time_domain、row_selection、population、snapshot_revision |
| unit_rules | same_unit_and_scale；conversion=forbid |
| snapshot_rules | 首版具体 profiles 使用 same_revision |
| numeric_rules | 默认 decimal_exact_v1；近似来源须显式授权 |
| formula_refs | contribution_rate / 1，input_roles=[parts,total] |

未来 Policy factory 必须显式接收数据库身份及接受的 issuer kinds/refs，不默认授予 fixture 或生产声明权限。当前两个 profiles 使用既有数据集的已支付字面量“已支付”。如果其他数据源使用“paid”，必须先批准对应来源的状态映射和具体 Policy，不能把任意调用方字符串直接授权为已支付。若未来 factory 暴露 paid_status_value 参数，也必须验证它属于该批准映射；不自动翻译或归一化。

Policy ID、version 和实际 definition_digest 都要进入绑定。摘要应由展开默认值后的真实规则内容确定，不能只接受调用方填入的字符串。继续沿用确定性 canonical serialization，不引入 clock、UUID 或随机身份。

**未来必须增加具体 profile 支持范围门禁。** 当前泛型 ProductContributionPolicy 固定了类型与角色，但允许调用方定义其他 metric/grain；纯捕获探针中，显式授权 customer_id 的泛型 Policy 能通过 Compatibility/Alignment。未来 S3 只能接受上述两个已批准 profile 的实际规则范围，不能仅凭 Policy 类型、ID 或 compatible 标签授权 region/customer/profit 等业务。

该门禁仅检查规则定义。Compatibility 仍负责实际 Context 的资格判断，计算器不重复检查 metric、time、filter、unit。

## 3. Metric rules

首版两个具体 profiles 均明确授权：

| role | source | metric semantic | aggregation |
| --- | --- | --- | --- |
| parts | 调用方指定数据库的 orders_current.paid_amount | actual_paid_sales | SUM |
| total | 同库 orders_current.paid_amount | actual_paid_sales | SUM |

采用独立的 parts/total 结果，但以同一受信数据集版本、期间、非时间过滤和 population 为依据。当前 profile 不自动加入 orders_history、products 表的金额来源或任意同名字段；扩展来源须另行明确授权。

必须按数据库、表、字段的完整来源及实际 aggregation 匹配，要求相应 SchemaBinding。Schema 的 role/default aggregation、output_name、expression 展示文字不能授权口径。

拒绝 order_amount、AVG、COUNT、缺失聚合、相似字段和相同 alias 不同来源。缺失 lineage 或无法确定来源时返回 insufficient_evidence，不猜测 paid_amount。[现有来源与聚合检查](D:/agent_study/askdata_studio/backend/app/querying/business_signals/compatibility.py:263)可以复用。

## 4. Grain rules

| profile | parts grouping source | key component / domain | key value type |
| --- | --- | --- | --- |
| category_sales_contribution_v1 | orders_current.category | category / product-category | string |
| product_sales_contribution_v1 | orders_current.product_id | product_id / product-id | integer |

每次只能选择一种分区，不能同时使用 category+product_id，也不能自动压平层级、聚合 region/customer 或把 grouped total 当 global total。

category 保留已捕获字符串；product_id 采用获准整数 dtype/native_json，拒绝 bool、字符串数字或隐式类型转换。默认 identity normalization；没有显式映射就不 trim、改大小写、补零或合并产品。重复 key、NULL key、归一化碰撞不合格。

orders_current.product_id 虽在 Schema 中被描述为 foreign_key，仍须通过显式 Policy 和 selection 授权；不会因为 role 是 foreign_key 或 dimension 自动选择粒度。products.category 等其他来源不因标签相似自动视为同一分区。

## 5. Broadcast rules

只有以下条件全部成立，才能将 total 的同一个真实单元提供给各 parts：

1. 当前 Compatibility 操作为 divide，角色顺序严格为 [parts,total]，已验证 compatible 且 receipt 绑定当前完整输入与 Policy。
2. total 是已解析的 global_aggregate，grouping_columns=[]，selection.key_column_ids={}。
3. total rows 已知且恰好一行；计数和完整性自洽。该行数值是否有效由后续 Numeric Reader 判断。
4. Policy 明确开启 global total broadcast；其他完整性、期间、过滤、单位和快照资格均通过。
5. Alignment 状态为 aligned，且完整输出绑定当前 Compatibility receipt。

用户要求的 `allow_global_total=True` 对应现有 [GrainRule.total_broadcast](D:/agent_study/askdata_studio/backend/app/querying/business_signals/policies.py:63) 的值 **allow_global_total**。不新增与之可能冲突的第二个持久化布尔字段。若未来 factory 提供布尔参数，它只映射到此枚举，省略/False 不授权广播。

合格 Alignment 应具备：broadcastable=True、broadcast_role=total；每个 pair 为 matched、broadcast=True，left_row_index 指向实际 part，right_row_index=0，right_key=None。仅 broadcastable=True 不足以授权计算。

[现有 Alignment](D:/agent_study/askdata_studio/backend/app/querying/business_signals/alignment.py:253)已支持该形状。未来计算器只验证绑定及形状，不重新提取 key。多行 total、带 key、grouped total、未授权广播均拒绝，不取第一行。total 的 business_key 保持 None，不复制 part 的 key。

## 6. Completeness rules

**完整 SQL 输出不等于完整业务总体。** 指定总体 U 由明确来源、期间、获批准过滤、population_scope_ref 和 dataset/revision 共同界定。total 必须覆盖整个 U；parts 必须完整划分同一个 U。

| 证据层 | 两侧要求 |
| --- | --- |
| 执行输出 | success=True；complete_query_output；truncated=False；rows/columns 已知；returned_rows=total_rows=len(rows) |
| 查询口径 | 角色 grain、metric、time、filters 合格；无 HAVING |
| 结果选择 | 当前输入绑定的受信 row_selection 声明，mode=absent |
| 总体覆盖 | 受信 population.coverage=complete；两角色 population_scope_ref 一致 |
| 分区覆盖 | parts 的 population.partition_key_domains 恰好对应选定分区 domain |
| 快照 | 相同已证明 dataset/revision；不以 captured_at 相近作为同版本证明 |

total 返回一行、返回的数值看起来很大、两侧都 complete_query_output、parts 加总恰好等于 total，都不能单独证明 U 被完整覆盖。

以下必须拒绝或返回不足：

- total 声明 LIMIT、OFFSET、TopN 或其他 row selection：incompatible_context。即使单行 global aggregate 的 LIMIT 1 看似无影响，V1 也不豁免。
- parts TopN、只观察部分产品却声明完整分布：不合格。
- total coverage=incomplete：incompatible_context；coverage=unknown 或缺失声明：insufficient_evidence。
- parts 缺选定 domain 的完整 partition 证明：insufficient_evidence。
- truncated=True/partial_query_output：不合格；完整性或计数未知：证据不足。

[冻结接口没有结构化 LIMIT/TopN 字段](D:/agent_study/askdata_studio/learning_report/askdata_phase3_0_signal_contract_policy_design.md:507)。Signal 不解析或扫描 SQL 来补证据：无 row-selection 声明意味着“未证明无选择”，不能声称 SQL 一定包含或一定没有 LIMIT。声明签发方必须为当前 source/period/filter/population/snapshot 的覆盖负责；摘要绑定不认证声明真实性。

声明内容至少绑定 declaration_id、result_id、context_digest、所选 column_ids、issuer/basis、source_fields、period、filter_scope_ref、population_scope_ref 和分区 domain。结果或声明改变后必须重新取得资格证明。

特别区分三个字段：total.selection.key_column_ids={}；total 声明的 scope.key_domains 仍包含本次 product-category 或 product-id 域；total 的 population.partition_key_domains 可以为 []。scope 中的域是分析范围绑定，不表示 total 真的按该键分组。

## 7. Time rules

S3 采用 **same_bounded_period + bounded_range**，不是 S2 的相邻月比较。双方必须具有同一 Gregorian/date time domain、相同起止、相同开闭性和 WHERE scope，期间已知、有界、非空。

V1 显式使用各自 orders_current.order_date。示例：两边都是 [2026-08-01,2026-09-01) 可以继续；parts August、total July 必须拒绝；一侧有时间、另一侧没有，或两侧都无明确期间，均不能当作“全部历史”。

本设计也允许双方明确使用相同的非整月窗口，例如 [2026-08-05,2026-08-21)。require_complete_period 在此表示所声明窗口的完整覆盖，不要求窗口必须是整自然月。两边边界或开闭不同即不合格，不自动做日期表达式等价转换。

time_domain 声明、捕获时间约束及结构化过滤必须一致；不根据表名、当前日期或 Schema label 推断期间。现有 [S3 期间比较](D:/agent_study/askdata_studio/backend/app/querying/business_signals/compatibility.py:624)支持该规则。

## 8. Filter rules

首版 profiles 使用明确授权的 status='已支付' 条件，双方非时间过滤映射后严格一致。这里的已支付字面量属于具体来源的批准映射，不是可任意替换的参数。缺一侧 paid 条件、值不同、不同来源冒用相同 alias 或额外未授权条件均拒绝。

不是只比较两边是否“都出现 status”：还必须符合 Policy 指定的来源、操作符、typed literal 和 WHERE scope。字符串 paid 与已支付不自动视为同义，不能从 metric alias 猜测已支付口径。

V1 additional_conditions=reject，HAVING=reject，不提供过滤蕴含、任意布尔表达式、地区口径自动转换或不对称筛选桥接。若将来需要特定地区等子总体，需先显式定义两侧一致的受批准过滤 profile，再取得针对该总体的新声明。

## 9. Unit rules

两个操作数必须具备已被 Compatibility 接受、绑定对应 metric/source 与当前 Context 的 unit 声明。unit_id 与 unit_scale 必须一致；未知单位不能因“两边都未知”视作一致。

不猜 CNY，不自动把元/万元换算，不转换货币。display_scale 仅为展示信息，不修改工作数或默认将金额量化两位。未来输出 contribution_rate 使用 ratio，记录十进制比例文本，百分比格式留给展示层。

Numeric 沿用已冻结规则：默认 decimal_exact_v1；DOUBLE/FLOAT 必须显式选择 reporting_approx_v1 并允许 binary float。Decimal/整数保持 exact；任一参与该比率的操作数为 approximate，该输出保持 approximate。源质量与公式舍入质量分开记录。

未来使用局部 Decimal precision=80、ROUND_HALF_EVEN，输入幅度和 scale 沿用 NumericRules；最终比率量化 12 位，金额不预量化。Numeric Reader 是唯一数值入口，本阶段不实现读取编排或求值。

## 10. Failure cases

| 情况 | 设计结果 / 责任 |
| --- | --- |
| 缺 parts/total 必填字段、None 或非法模型形状 | 调用契约错误；不生成虚构结果身份 |
| parts 空且无可定位 key | context 级 insufficient_evidence；不输出虚构产品或“全部为零” |
| total 空、rows 未知或必要元数据未知 | insufficient_evidence；不能广播或补零 |
| grouped/multiple-row total、total key selection 非空 | incompatible_context；不取第一行 |
| parts duplicate/normalization collision | Alignment incompatible_context |
| parts NULL key | Alignment insufficient_evidence |
| missing/unknown coverage、row-selection、time、unit、revision | insufficient_evidence |
| LIMIT/TopN、已知不完整、metric/grain/time/filter/unit/population/revision 冲突 | incompatible_context，或既有明确 unsupported 状态 |
| Policy/input/声明/receipt 语义变化，旧/缺失绑定，Alignment 来源或内容不符 | incompatible_context，在 Numeric 前拒绝 |
| NULL part/total、Numeric 不可读 | 保留 Reader 状态与观察事实，整个分区不生成贡献率 |
| 任一输入为负 | incompatible_context，不计算负销售构成 |
| total=0，所有已知 parts=0，其他资格充分 | 各已定位 part 的 contribution_rate=undefined；原因 ZERO_TOTAL |
| total=0，却有正 part | incompatible_context；分区矛盾优先于零分母 |
| part=0、total>0，其他核对通过 | 未来允许正常零贡献 |
| part>total 或分区和不符且超出获准核对容差 | incompatible_context，不改分母、不修正金额 |
| parts 行数超过 numeric_rules.max_parts | unsupported；整体拒绝，不截断后继续 |

S3 采用**全分区门控**。任一 part 缺失证据或不可读，便不能完成完整分区核对，不沿用 S2 某地区失败而其他地区独立计算的策略。仅在全分区资格、Numeric 和一致性检查均通过后，才允许未来生成比率。

现有 Context 没有应出现产品的完整名册。某产品未出现在 rows 中，不能凭 Schema 或其他产品推断它应存在、值为零或精确的 missing key；完整覆盖依赖受信 partition 证明。若未来要求逐个列出未出现产品，需要另行设计显式 expected-key 证据。

### 分区核对与零策略

沿用 [Phase 3.0 S3 设计](D:/agent_study/askdata_studio/learning_report/askdata_phase3_0_signal_contract_policy_design.md:625)：独立 total 与完整分区声明先成立，数值和仅作为额外一致性检查。本阶段只确定规则，不实现核对或公式。

- 默认 reconciliation=exact，分区和须精确等于独立 total，part 不超过 total。
- approximate 来源许可不自动开启核对容差。仅显式 reconciliation=relative_tolerance 时，采用现有字段 relative_tolerance=1e-12。
- 本设计确定相对核对基准为独立 total 的绝对值：分区残差及单项超出 total 的正差都不得大于 abs(total)×1e-12；边界等号允许。
- 当前 NumericRules 没有绝对容差字段，不增加隐藏金额 epsilon，不把早期建议当已实现配置。
- 精确零按 Reader 工作值判断；任何极小正 part 都不能在 total=0 时被容差抹去。容差不用于覆盖证明、单位转换或把输出截到 [0,1]。
- 比率量化后相加可能不精确等于 1；不调整最后一项来掩盖舍入。
- 中间分区和使用完整局部精度；输入幅度限制不用于裁剪中间和。max_parts 默认上限沿用 10000，超限拒绝。

ZERO_TOTAL、分区不一致及超限等未来计算阶段原因码需要在实施时固定；当前 Compatibility 的 compatible 只说明其阶段资格，不表示 total 非 NULL、非负或比率已可计算。

## 11. Calculator implementation plan

以下是后续阶段的实施顺序，本轮不执行这些实现：

1. 落地薄 ProductContributionInput 与两个显式 Policy factory；版本、来源、单一 grain、已支付字面量、issuer、broadcast 和实际定义摘要均明确。
2. 复用 Compatibility(divide) 和 Alignment，由调用方准备当前证明；S3 入口验证 receipt 对完整输入快照的绑定、具体 profile 范围、操作/角色、Alignment 来源及广播形状，不重跑上游资格逻辑。
3. 落地下面的最小广播 Evidence 扩展，并先验证旧 S1/S2 wire 和数值行为保持不变。
4. 验证 max_parts 和全局门禁，使用 Numeric Reader 读取唯一 total 一次、每个 part 一次；不直接从 rows 取得金额。
5. 收集所有 Numeric 结果，再处理全分区失败、非负域、零总额及独立分母一致性；全部完成后才执行固定 contribution_rate 公式。
6. 生成单个 BusinessSignal 列表，按已有规范 key 顺序输出；复用共享 Evidence Builder；完成专项回归和后续 S3 Audit。

未来实现仍不接 Agent、LLM、SQL、数据库、SignalBatch、Engine 或 Workflow。signal_id 沿用当前未冻结策略，不引入 UUID、timestamp 或随机 ID。

### Evidence 设计需求与现有缺口

复用 SignalEvidence，不另建 S3 专属证据模型。每个未来 Signal 的两个 Evidence ID 为 parts:metric 与 total:metric，公式引用 contribution_rate / 1；BusinessSignal 保存 Policy ID、version、实际 digest，current_value 对应 part，reference_value 对应 total。

| 内容 | part Evidence | total Evidence |
| --- | --- | --- |
| result_id / context_digest / column_id / ordinal | parts 的真实身份 | 独立 total 的真实身份 |
| row_index / value | 当前 part 行与 Reader 观察值 | 真实 row_index=0 与同一 Reader 观察值 |
| business_key / key_values | 当前已对齐的产品或品类 key | None / [] |
| source、SUM、grain、period、filters、unit、quality | 来自既有 Context、Compatibility 和 Numeric 事实 | 同左，保留 global_aggregate 与其完整性依据 |
| formula_refs | contribution_rate / 1 | contribution_rate / 1 |
| 广播关系 | 所属 pair 使用 global total broadcast | 同一 pair 的 total 操作数，无伪造 key |

现有 [SignalEvidence](D:/agent_study/askdata_studio/backend/app/querying/business_signals/models.py:483)及 Builder 已能保存 total 的真实 row=0、值和空业务键；现有 [测试](D:/agent_study/askdata_studio/backend/tests/test_signal_evidence.py:502)定义了这种事实保留。**当前模型没有显式 broadcast 字段。**

最小未来扩展拟为 `alignment_broadcast: bool | None`：它表示本 Evidence 所属 pair 的广播事实，复制已验证 AlignmentPair.broadcast；context_role=total 标识被广播的分母。不能靠 total 一行或 global label 自行推断 True。

该字段只在未来 S3 路径显式投影。旧路径保持 None，并仅省略此新增 None 字段，不能通过全局 exclude_none 删除旧 Evidence 原本合法的 null 字段，也不能给 S1/S2 无条件新增 False。序列化兼容性必须列为实施验收。

Evidence Builder 不重读 total，也不算贡献率或分区和；相同 total NumericReadResult 可用于各 part 的证据组装。缺失/未读/NULL/拒绝必须忠实记录，不伪造 total_value=0。BusinessSignal 保存计算值，Evidence 只保存依据。

## 12. Testing plan

下面是未来测试设计，不是本轮已经通过的 S3 calculator 测试。前 9 个核心用例中的实际 Context 资格与广播条件先验证真实 Compatibility/Alignment 阶段；Case 9 的新鲜越界 Policy 支持范围门禁，以及 Case 10 的零总额结果，需等未来 S3 profile/Calculator 实施后验证。

| Case | 输入条件 | 预期 |
| --- | --- | --- |
| 1 | category 完整分区 + 独立单行 global total，全部声明充分 | compatible；aligned；total row 0 广播 |
| 2 | product_id 整数分区 + global total | 同上；字符串/bool 替代 key 类型拒绝 |
| 3 | total 多行 | incompatible_context，无广播、不取首行 |
| 4 | total 带 key selection 或 region grouping | incompatible_context |
| 5 | total 存在 LIMIT/TopN 声明，即使 complete_query_output、单行 LIMIT 1 | ROW_SELECTION_PRESENT；缺声明则 ROW_SELECTION_UNKNOWN，不读 SQL |
| 6 | total truncated=True / partial output | 拒绝；未知完整性返回不足 |
| 7 | periods 不同、单侧缺时间、domain/开闭不一致 | 拒绝或明确不足；两侧同一有界非整月可通过 |
| 8 | 非时间 filter 不同或 total 缺已支付条件 | 拒绝 |
| 9 | order_amount、AVG、COUNT、相同 alias 不同 source | 拒绝；新鲜越界 Policy 也须由 S3 profile 门禁拒绝 |
| 10 | total=0，所有可读 parts=0，完整分区与其他条件充分 | 未来各比例 undefined / ZERO_TOTAL，无 Infinity、NaN、默认比例 0 |

补充测试分组：

- 完整性：部分/未知 population、缺 partition domain、相同金额但遗漏零值产品且无覆盖证明、snapshot 不同、受信 issuer 缺失或声明错绑。数值相等不得补足覆盖。
- 绑定：当前 Policy/selection/声明/rows/period/filter 变化，旧 receipt、旧 Alignment、篡改 pair 或广播标记，必须在 Numeric 之前拒绝。
- Key：parts 乱序、duplicate、NULL、归一化碰撞、region/customer、category+product_id 混合 grain；不得自动聚合或丢行。
- 缺失：空 parts、空 total、未知 rows、NULL part/total；任一 part 不可读时所有比率都不生成，保留真实 Evidence。
- 数值：非负约束、part=0/total>0、total=0 有正 part 的矛盾、极小非零、exact 与 approximate、非法 codec、精度与 max_parts 边界。
- 核对：exact 非零残差拒绝；relative 阈值以内、恰等于、刚超过；part>total 同阈值；不能用容差把零分母变成普通除法或修正最后一项。
- Evidence：两个 result_id/column_id/row_index/value、公式及 Policy version、total row=0/空 key、显式广播事实、读取次数 N+1；不包含 computed_value。
- Purity/确定性：所有输入与 NumericReadResult 不变、返回结果不共享可变容器、A→A、A→B→A、JSON roundtrip；无 clock/random/UUID、SQL/DB/LLM/上游重跑。
- 兼容性：未来最小 Evidence 扩展不得改变 S1/S2 既有输出；实施完成后运行 S3、Evidence、S1、S2、全部 Business Signal 与 backend 回归。

本轮完成的是静态契约核查及 **24 项纯模型/捕获 fixture 现有能力探针**，没有新增测试文件、运行 S3 公式或执行数据库操作。其中确认了获授权 source/domain 下的通用广播、LIMIT 1/TopN 与覆盖拒绝、相同有界非整月支持、重复/NULL key 拒绝，以及泛型 Policy 仍可授权 customer grain 的范围缺口。product_id 探针仅验证重新绑定来源/域后的通用广播，仍使用 string key，未验证本设计要求的 integer product profile；该验收明确留在未来 Case 2。

既有回归基线为上一轮审计的 backend 988/988；**本轮未重跑 backend 全量，不将该基线报告为新的测试结果。** 后续实现需以该基线验证无回归。

本轮 133 个既有文件哈希保持一致，仓库仅新增本设计报告，未 stage/commit。当前已完成输入及规则设计；ProductContributionInput、具体 Policy factory、广播 Evidence 字段、分区数值核对和 S3 公式均留待后续实施。
