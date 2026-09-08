# Phase 4.1 Response Contract Design Document

本阶段只设计 SignalBatch → ResponseGenerator 的数据契约。**推荐采用白名单 ExplanationContext 与结构化 ExplanationResponse；text 是经引用验证后的呈现结果。**

以下新模型、适配器、表达词典、验证器及迁移步骤均为拟议设计，尚未实现。本轮没有修改代码、调用 LLM、实现 Prompt、迁移 ResponseGenerator 或改动 Workflow；没有读取实际 SQL rows、把 BusinessContext 用作解释输入或重新计算 Signal。

## 1. 旧 ResponseGenerator 调查与问题

### 1.1 当前入口

| 方法 | 输入 | 输出 |
| --- | --- | --- |
| answer_qa | query: str、context: str | 自由文本 str |
| finalize | query、SqlExecution、schema_context、analysis_context | 字典：valid、reason、title、analysis |

[response_generator.py:25](D:/agent_study/askdata_studio/backend/app/querying/response_generator.py:25)的 QA 入口调用 model_client.chat；[finalize:34](D:/agent_study/askdata_studio/backend/app/querying/response_generator.py:34)调用 chat_json。

SqlExecution 包含 sql、success、columns、rows、error，以及可选 result_contract / result_id；finalize 仍读取前三类结果数据，未消费后两者，也未消费 SignalBatch / SignalEvidence。[原类型](D:/agent_study/askdata_studio/backend/app/querying/models.py:9)。

finalize 将 query、SQL、columns、前 table_row_limit 行、Schema 和历史分析文本拼入模型输入；[默认行数限制为 50](D:/agent_study/askdata_studio/backend/app/config.py:69)。输出 valid 经过 bool 转换，缺失默认 True；reason / title / analysis 经过字符串转换和默认值补充。这是现有代码事实，不代表新契约应保留这些行为。

### 1.2 当前调用与消费

查询路径在执行结果恢复和 ResultContract 一致性校验之后，直接调用 finalize，没有中间的 SignalBatch 节点：[query_graph.py:295](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:295)、[query_graph.py:403](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:403)。

QA 路径还会拼接 short_term_context、recent_result_context、analysis_context；这些上下文的生成代码包含 SQL、columns、截取 rows 和旧 analysis：[query_graph.py:177](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:177)、[session_context.py:204](D:/agent_study/askdata_studio/backend/app/services/session_context.py:204)。因此只替换 finalize，不能完成解释入口迁移。

[ResultBuilder.completed](D:/agent_study/askdata_studio/backend/app/workflows/result_builder.py:84)将 final.valid 映射为 QueryResult.completed / failed，将 analysis / title 用于结果说明和标题，reason 未进入 QueryResult。它还根据列名包含“额、数、率、平均、目标”划分指标与维度。

[QueryResult](D:/agent_study/askdata_studio/backend/app/models.py:62)同时承载 SQL / columns / rows 和 analysis；[前端](D:/agent_study/askdata_studio/frontend/src/App.vue:580)分别展示表格、SQL、说明。未来禁止解释层消费 rows，不等于必须删除执行结果表格 UI；两条数据通路应在接口上分离。

### 1.3 旧路径问题

1. **解释与业务判定混合。** 模型被要求检查结果是否能回答问题，valid 又影响 API 成败；解释生成不能覆盖 execution 或 Signal 状态。
2. **缺少来源闭环。** title / analysis 没有逐项 Signal、公式输出和 Evidence 引用。
3. **样本不足以证明业务资格。** 截取的 rows 不携带已验证的 metric、period comparison、Numeric quality、coverage 或 undefined 语义。
4. **契约过于宽松。** 缺 valid 默认成功；字符串 `"false"` 经 bool 转换也为 True，不能作为可信状态。
5. **旧上下文可回灌。** 历史 analysis 和任意分析表文本可能再次成为新回答的事实来源。
6. **自由文本混合。** query、Schema 描述、表格标题、SQL 文本和旧回答可能携带指令式文本。
7. **列名猜测不能继承。** 旧 ResultBuilder 的指标启发式不能成为新解释层 metric 判断依据。

以上是后续迁移需要解决的问题，本轮不修复旧代码。

## 2. ExplanationContext 设计

### 2.1 数据边界

```text
唯一业务事实来源：SignalEngine 产出的 SignalBatch
       │
       ├── 审计侧：原 Batch / Signal / Evidence 只读引用，完整保存
       │
       └── 纯白名单适配：ExplanationContext
                    ↓ 按表达预算选择完整事实包
              ExplanationView（未来模型可见数据）
                    ↓
              结构化表达候选 → 引用验证 → 渲染
```

拟议入口为 build_explanation_context(batch, request_options)。batch 必须是受信 SignalEngine 已产出的当前 SignalBatch；request_options 仅含用户问题、语言、篇幅和可选的批次内范围选择，不提供业务事实。

入口不接受 SqlExecution、ResultContract、SQL、rows、Schema、BusinessContext 或任意 context 字符串；不得以“Evidence 不够”为由补读它们。只访问 SignalBatch 内已有的 Signal 与 Evidence 白名单字段；raw_value、provenance 和原始语义表达式不属于该白名单。

完整 Batch 的保留属于调用服务的审计记录，不作为 ExplanationContext 的可序列化嵌套字段，防止误把整个对象 model_dump 后送给模型。ExplanationContext 是表达投影，不是新的 BusinessSignal、SignalEvidence 或新的业务资格证明。

### 2.2 拟议字段

| ExplanationContext 字段 | 来源 / 约束 |
| --- | --- |
| version | 新解释契约版本，拟为 `1` |
| projection_version | 白名单与显示词典版本；不替代业务 Policy version |
| source_batch_slot | 固定本次请求内的 `input_batch`；不是全局 ID |
| batch_id | 只透传现有值，允许 None；不生成 UUID、时间或随机身份 |
| signals | 与原 batch.signals 一一对应的 SignalView，保持原位置和原状态 |
| displayable_signal_indices | 原 Batch 展示索引的精确副本；适配层不能扩大 |
| evidence_refs | Signal 内作用域的 Evidence 引用及允许披露的摘要 |
| limitations | 全部限制的引用清单，加安全 code / 展示类型；原文留在原记录 |
| status_counts | 透传原 Batch 状态计数，不代表可展示数量 |
| request_options | question、locale、verbosity、requested_signal_indices；不可信请求数据 |

created_context_refs 单独保存在服务的非序列化审计旁表，透传 batch.created_contexts 的已有身份；它不是 ExplanationContext 的传输字段，也不是 BusinessContext 对象。

SignalView 必须包含 signal_index、原 signal_type / status、展示资格以及限制引用。只有 index 位于 displayable_signal_indices 的记录才能拥有可用于回答的事实包。被 Engine 隐藏的 computed 仍保留原 status，但 facts 不暴露；不得按 status 再推导展示资格。

可展示事实包包括原有业务键、Policy / calculator 版本、每个 ComputationResult 的 formula_id / version、status、原 value 字符串、unit_id、numeric_quality、reason_code 和操作数 Evidence 引用。保留实际 None / 空列表的区别，不做默认值填充。

上下文不包含通用 metadata / extras / arbitrary dict 扩展口，未知字段和未知契约版本明确拒绝。身份字段是定位数据；任何字符串都不因处于已验证模型中就成为行为指令。

### 2.3 引用与快照

当前 signal_id / batch_id 可为 None，Evidence ID 只在一个 Signal 内唯一。[Signal 定义](D:/agent_study/askdata_studio/backend/app/querying/business_signals/models.py:630)、[Batch 定义](D:/agent_study/askdata_studio/backend/app/querying/business_signals/batch.py:226)。V1 使用：

| 引用 | 结构 |
| --- | --- |
| SignalRef | source_batch_slot + signal_index |
| OutputRef | SignalRef + formula_id + formula_version |
| EvidenceRef | SignalRef + evidence_id |
| LimitationRef | source_batch_slot + scope + signal_index? + evidence_id? + limitation_index |

scope 是封闭枚举：batch、signal、evidence_numeric、evidence_upstream、presentation；最后一项定位本次视图固定的 omission / notice 表。不同 scope 的位置字段按各自结构校验，不接受任意 JSONPath 或属性路径。相同 evidence_id 出现在两个 Signal 时仍是两个引用；重复传入同一 Signal 也按批次位置分别保留，不跨 Signal 合并 Evidence。

引用仅在同一请求封装的输入快照内有效，不能脱离快照跨 Batch 重用。后续持久化应共同保存源 Batch 审计记录、ExplanationContext、视图选择和已验证响应，由已有任务/存储关联定位；本阶段不设计新的全局身份算法。input_batch + index 本身不能检测跨请求重放，必须依赖服务的调用关联和归档封装；不能将裸候选重新绑定到另一个 Batch。单独到达且无法关联源快照的答案不能猜测引用目标。

未来适配器在调用开始时建立一次不可变白名单投影；模型返回后只对这份投影校验和渲染，不重新从可变对象抽取字段。原 Batch / Evidence 在调用期间按只读约束持有；若无法保证其稳定，拒绝该调用或从已固定的审计记录读取。Phase 3 的浅冻结不等于嵌套对象深隔离，不得声称现有层已经解决并发修改。

## 3. SignalBatch 消费与展示规则

### 3.1 原资格与表达选择分开

ExplanationView 是唯一允许进入未来模型输入的数据包：只含 prompt_signal_indices 对应的完整 Signal 事实包、它们的 Evidence 摘要、必要的安全限制，以及表达范围说明。

必须满足：prompt_signal_indices 是 displayable_signal_indices 的保序子集；不重编号、不重算排名、不根据模型评分选择。requested_signal_indices 如未提供，范围为全部原始索引；如提供，必须是合法、无重复的原索引，按原批次顺序消费。

最终未进入表达的数据全部记录 disposition：超出请求范围、Engine 不允许展示、预算未包含、字段无法安全披露等。**表达省略不是业务总体不完整，更不是 TopN 资格声明。**

### 3.2 状态规则

| Signal 状态 / 条件 | 进入模型事实区 | 用户呈现 | 审计保留 |
| --- | --- | --- | --- |
| computed，且原索引获准 | 是 | 展示原公式值、单位、quality 及引用 | 完整原 Signal / Evidence |
| undefined，且原索引获准 | 是 | 已计算子输出正常展示；undefined 项按 reason_code 解释，value 仍为 None | 原原因及 Evidence |
| insufficient_evidence | 否 | 固定“证据不足”提示，可按请求范围给状态摘要 | 完整失败记录 |
| incompatible_context | 否 | 固定“输入不具备计算资格”提示，不自行分析资格失败 | 完整失败记录 |
| unsupported | 否 | 默认隐藏详细诊断；保留“当前能力不支持”的固定提示或计数 | 完整失败记录 |
| computed / undefined 被 Engine 隐藏 | 否 | 固定“该结果未通过展示检查”提示 | 原状态及 Engine limitation |

非展示状态可通过独立的安全 notice 区说明，不能因生成 notice 而进入事实区。原 message 不直接进入模型。

S2 baseline=0 的例子：顶层 undefined、absolute_change computed、change_rate undefined。必须同时保留已计算绝对差和未定义比例；不得整条丢弃，也不得将比例写成 0、Infinity 或 NaN。

空 Batch、没有获准索引、或预算容不下一个完整事实包时，返回固定的无可展示事实/表达范围不足说明，可不调用模型；不能退回 rows 或旧 analysis 补答案。

## 4. LLM 职责边界

| 允许 | 不允许 |
| --- | --- |
| 在已有 Signal 范围内组织自然语言与结构化总结 | 计算、加总、相减、相除、重算或修改数字 |
| 将用户问题关联到已提供的结果引用，必要时请求明确范围 | 按列名或描述猜 metric、source、aggregation |
| 选择获准的表达变体、标题类型和展示段落 | 判断时间邻接、月份有效性、coverage、Alignment 或 Compatibility |
| 转述已给定的 status、reason_code 和 quality | 把 approximate 改为 exact，把 undefined 改为 computed |
| 依据引用回答“这个已有结果是什么、采用哪些输入” | 推导原因、风险、建议、排名、显著性或其他上游未产出的事实 |

“结构化总结”可以按已有 Signal 类型和业务键组织，不包含跨 Signal 的总额、平均值、最大值或新排名。S1 的比率不自动授权“已达标/未达标”判断；S2 的数值差不自动授权因果解释；S3 的稳定展示顺序不表示贡献排名。

Evidence 的 formula refs 只用于说明已采用公式，不授权模型再次执行公式。V1 原样展示数值文本，不将 0.5 自行转换为 50%，不换单位、不再舍入；后续如需要显示格式变换，必须另行设计确定性呈现规则。

用户问题超出已有 Signal 时，只能说明目前没有对应计算结果或请求明确范围。不能使用常识、用户声称的数字、历史自由文本或其他来源补出业务答案。此层不规划查询，也不触发新 Signal 计算。

## 5. Evidence 暴露策略

### 5.1 完整记录保留，模型只看摘要

[SignalEvidence](D:/agent_study/askdata_studio/backend/app/querying/business_signals/models.py:520)包含 provenance、SchemaBinding、原始语义表达式和上游自由文本；它可用于审计，但不适合作为默认 Prompt payload。

Evidence 摘要由白名单投影产生，不通过 LLM 先“压缩”成新事实，也不重新调用 Evidence Builder。

| 字段组 | 模型可见策略 |
| --- | --- |
| EvidenceRef、context_role、formula refs | 必需；本次请求内短引用可映射回完整身份 |
| observed_value.presence / value、numeric_quality | 按原值提供；只用已有 observation，不读取 raw_value 或 rows |
| metric_semantic 的已接受 ID、aggregation | 提供有限字段；人类标签来自受控词典，不使用 Schema description 猜含义 |
| 业务键、normalized_period、normalized_filters | 仅投影已接受的类型、规范值和边界；不带原 SQL 表达式，不重新推断 |
| unit_id、unit_scale | 仅提取已接受声明中的标量，记录来源引用；不发送整个声明对象 |
| alignment_broadcast、操作数 business_key | 保留现有事实；S3 total key=None，不复制 part key |
| 必要 limitations / numeric issues | 提供安全 code 与版本化固定说明，保留原引用 |
| result_id / context_digest / column_id / ordinal / row_index、版本 | 在服务引用表中完整保存；模型可用 EvidenceRef，审计 UI 可解析这些身份 |
| raw_value、provenance、submitted_sql | 不向模型暴露，适配器不读取其内容 |
| schema_metadata、完整 grain / filters / time 对象、source 表达式 | 不直接暴露；只能通过已定义标量白名单 |
| Issue.message、description、upstream_limitations 原文 | 默认只留审计侧，不作为模型指令或事实摘要 |

normalized_period / filters 来自 Evidence 已捕获的资格结果，不重新读取 BusinessContext。缺失的摘要字段仍为未知，不从 expression / table name / description 补全。

同一 Signal 的多个公式共享该 Signal 内的两份摘要；例如 S2 不为两项公式重复展开四个操作数。多个 S3 Signal 指向同一 total 时，仍保留各自 scoped EvidenceRef；V1 不新增跨 Signal 的全局 Evidence 去重身份。

### 5.2 未知限制

已知 reason_code / Issue.code 通过代码库维护的版本化词典变成固定显示说明。自由文本不控制词典或模板。未知 code 不让模型猜含义；用固定“存在未展开的限制/未提供可解释原因”提示，并保留原 LimitationRef。

只有 upstream_limitations 原文而没有安全 code 时，同样保留引用并发出一般限制提示，不能静默丢弃后声称无任何限制。无法安全投影完整必需事实包时，省略整个 Signal 的模型事实包并记录原因，而不是删除不利条件后展示。

### 5.3 预算规则

未来必须配置并记录 budget_profile_version、最大 Signal 事实包数、单个文本字段上限、总序列化字节上限，以及所选模型的输入/输出 token 预算。具体额度在实现阶段结合模型和样本确定，本设计不声称已有容量测量。

按原顺序选择完整事实包；一个包至少包含业务键/范围、全部固定公式、操作数对、单位、quality、必要 period/filter 与限制。不能截断数字、身份、单位、公式引用或只保留一个操作数；不能移除质量或 coverage 限制换取篇幅。

包放不下则记录在 omission manifest；响应固定提示还有哪些范围未展开，可由用户选择后续页。最终实际请求应预留可信指令、用户问题及输出预算，超限时缩小完整包集合或返回预算不足，禁止依赖模型静默截断。

原 Batch 与审计记录始终完整。omission manifest 可在服务侧保留完整索引，在模型端仅给有界范围信息；这类计数只是呈现元数据，不是业务指标计算。

## 6. Prompt Injection 边界

BusinessSignal 顶层没有通用 description 字段，但 [Issue.message](D:/agent_study/askdata_studio/backend/app/querying/business_signals/models.py:150)、Evidence 内的 Schema 描述、上游限制、业务键、source / domain / metric ID、filter 字面量都可能含自由文本。数字和值已获准用于业务计算，不代表任何随附字符串具有指令权限。

| 信任类别 | 可承担的职责 |
| --- | --- |
| 开发者维护的契约枚举、白名单、显示词典 | 控制允许字段、表达类型和处理规则 |
| 受信 producer 的 typed facts | 提供当前受支持范围内的业务事实；始终作为数据 |
| 用户问题、键名/键值、ID、描述、message 等文字 | 仅作为不可信文本数据；不得修改规则、角色或工具权限 |

拟议防线：

1. 只构造白名单数据包，不拼接原 Batch、Evidence 或历史 context 全文。
2. 系统行为由受控配置定义；用户内容和数据值放在独立结构化数据区，不拼成 system/developer 指令。
3. 必需的 key/filter 字符串保持字面数据语义，限制长度并正确转义。不能“清洗”后把不同 key 当成同一个；超限时不展示该完整包并保留审计原值。
4. 不接受数据内容提供的模板、表达规则、路径、角色标记或工具调用。引用只能解析到本次已批准的表项。
5. 未来解释模型无 SQL、DB、执行工具或审计原文读取能力；缺证据时停止表达，不能自行补查。
6. 输出按严格契约验证并安全呈现，禁止把任意 HTML、外部链接或图片指令作为可信结果渲染。

结构化分隔和转义是防御措施，不能单独证明模型未受指令式数据影响。因此本设计同时要求最小权限和输出引用验证；这与 [OWASP Prompt Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)关于间接注入、指令/数据分离、输出检查和权限限制的建议一致。

本阶段不编写实际 Prompt，不新增注入过滤器或第二个判定模型，也不承诺防住任意恶意字符串。

## 7. Response 输出契约

### 7.1 决策：结构化答案为主

仅输出 text 无法保证 Signal 引用关系。拟议分成模型候选与应用最终响应两步：

```text
模型候选：组织选择 + 受控表达变体 + 引用
       ↓ 应用校验，按引用取回既有事实
ExplanationResponse：已验证结构 + 引用清单 + 渲染 text
```

V1 的业务事实句采用受控 block / expression_variant：允许模型选择中性的表达变体和段落组织，事实槽位由 OutputRef / EvidenceRef / LimitationRef 填充。不是让模型返回一个新 value 字段，再相信它和原值相同。

“带了引用的任意自由文本”仍可能把真实数字说成错误因果、排名或达标结论。引用存在不证明自然语言含义成立。因此 V1 不将无约束业务论述直接发布为可信答案；开放自由业务解释需要后续独立设计，不能只靠 JSON 合法或另一次 LLM 判分声称可信。

### 7.2 候选契约

候选只允许以下封闭字段，不允许任意 code、SQL、URL、value、unit、status 覆写或自由事实正文：

| CandidateBlock 字段 | 含义 |
| --- | --- |
| kind | fact / undefined_reason / evidence_basis / limitation / scope_notice / insufficient_support |
| signal_ref | 相关 Signal 的本地引用；无 Signal 的范围说明可以为空 |
| output_refs | 引用已有公式结果，不创建新公式 |
| evidence_refs | 仅引用相关输出已关联的操作数 Evidence |
| limitation_refs | 仅引用该记录已有或本次呈现生成的限制 |
| expression_variant | 版本化受控表达变体；不是可执行模板文本 |

fact 只能引用 computed 子输出；undefined_reason 必须引用 undefined 子输出并使用其 reason_code。evidence_basis 仅转述已有操作数和公式关联，不输出自己的计算值。insufficient_support 说明此表达层不能提供所问的新指标或原因，不能声称数据源中不存在该业务事实。

不允许使用暗含数值比较或因果判断的表达变体。V1 标题同样使用受控类别，如结果概览、计算依据；不能输出“表现最佳地区”等未经上游证明的标题。

### 7.3 最终响应字段

| ExplanationResponse 字段 | 产生方与含义 |
| --- | --- |
| version | 应用设定的解释输出契约版本 |
| source_batch_slot、batch_id | 应用绑定当前输入，不信任模型自报来源 |
| generation_status | 应用设置 generated / fallback / not_requested / failed；不代表业务计算状态 |
| presentation_coverage | 应用设置 complete / partial / none；仅描述请求范围内获准事实包的呈现程度，不证明回答已解决自然语言问题 |
| blocks | 校验通过的受控结构与原事实引用 |
| included_signal_indices | 已实际呈现的获准索引，保持原序 |
| omissions / notices | 未展开原因及引用；原始失败仍在审计记录中 |
| citations | 应用按引用解析形成的来源清单，不允许模型生成来源 URL |
| text | 从已验证 blocks 与原始事实槽位渲染；可兼容未来 analysis 字段 |

presentation_coverage 的判定基于 requested_signal_indices 与原 displayable_signal_indices 的交集：交集中存在事实包，且其全部固定输出（含 undefined 原因）和必要限制均已呈现，才为 complete；已呈现部分事实包但仍有省略为 partial；没有呈现任何完整事实包为 none。仅有失败 notice 的响应也是 none。请求范围内不获准的记录仍须有相应 notice / omission，不能用 complete 暗示它们计算成功。

generation_status 与 presentation_coverage 不取代 execution.success、Signal.status 或各公式 status。模型不再返回控制业务成功与否的 valid。

以下仅为契约示意，不来自运行数据，也不是已实现类：

```json
{
  "kind": "fact",
  "signal_ref": {"source_batch_slot": "input_batch", "signal_index": 0},
  "output_refs": [{
    "source_batch_slot": "input_batch", "signal_index": 0,
    "formula_id": "attainment_rate", "formula_version": "1"
  }],
  "evidence_refs": [],
  "limitation_refs": [],
  "expression_variant": "neutral_result_v1"
}
```

应用根据该 OutputRef 获取原 value / unit / quality，并自动补齐原 input_evidence_ids 对应的引用；模型未显式列举 Evidence 不表示依据可以丢失。模型若提供 EvidenceRef，则必须与这些引用一致，不能借用其他 Signal 的同名 ID。

### 7.4 验证与失败行为

未来验证器只做结构、引用和表达约束检查，不计算公式或重新判断业务资格：

- 引用只能来自本次固定视图；不能引用隐藏、预算未包含或其他 Batch 的事实。
- 公式 ID / version、操作数角色、Evidence 引用必须对应；不可接受任意路径。
- 数字、单位、quality、status、期间与键值来自固定投影，不由模型写回。
- 受控表达变体必须适用于对应块类型和已有状态；未知 variant / 字段拒绝。
- 默认概览包含本页全部事实包；模型省略项必须被应用补齐为事实块或在 omissions 中显式列出，必要原因和限制由应用强制呈现。
- 不直接流式展示未经验证的模型业务文本。

候选错误或模型不可用时，应用可使用同一份事实包生成固定结构 fallback；禁止自动改数、修补引用、默认 valid=True 或退回旧 rows 路径。错误、无可展示数据和预算不足分别记录，不改变任何 Signal。

投影、引用验证和固定渲染应保持确定性；未来 LLM 选择的表达可以变化，不把措辞稳定性等同于 Phase 3 的计算确定性。

## 8. 未来迁移方案

以下按后续授权逐步实施，本轮不启动任何一步：

1. **实现契约与纯适配器。** 在新解释模块实现 ExplanationContext、白名单投影、引用解析和预算清单；不改 Phase 3 Contract / Calculator / Evidence Builder。
2. **实现结构化输出校验与固定渲染。** 先用人工候选验证事实槽位、失败状态和引用，不依赖真实 LLM。
3. **接入受限表达生成。** ResponseGenerator 仅消费 ExplanationView；模型只有受控表达选择权限，不保留 SqlExecution / rows / BusinessContext fallback。
4. **同时迁移查询解释与数据 QA。** 替换 finalize 与 answer_qa 的事实入口。历史问答只能通过存储关联取回已有、获准的 SignalBatch；旧 analysis、分析表、SQL rows 不能继续回灌。V1 一次解释一个明确 Batch，跨快照比较须上游另行产出 Signal。
5. **再调整 Workflow / API。** 后续 QueryState 增加独立信号与解释状态；保留现有执行结果校验。ResultBuilder 不再用 LLM valid 决定计算资格，不再把列名启发式当作新解释事实。
6. **迁移前端与归档。** 原始执行表格可以保留独立 UI；结构答案、text 与引用独立传递。旧 analysis 可映射为渲染 text，不能因此丢弃结构及审计关联。
7. **最后验证完整边界。** 两个入口都不再把原始结果送入解释器，历史与错误 fallback 也无绕行路径后，才声明应用已完成 SignalBatch-only 迁移。

未来验收至少覆盖：五种状态、S2 部分 undefined、S3 广播依据、重复 Signal / 同名 Evidence ID、隐藏索引、预算整包省略、未知限制、空批次、跨快照引用、非法输出、数字篡改、注入式 key/message/description、JSON 回读、输入不修改，以及 LLM 失败不影响 execution / Signal 状态。

## 9. 本轮交付与保留边界

本轮仅新增本文档。113 个既有源码文件保持不变；没有新增类、函数、Prompt、测试或运行行为。仅进行静态源码与契约检查，没有读取运行表格数据或重新计算 Signal。

最近已验证基线仍为 Business Signal 654/654、backend 1104/1104，来自 [Phase 3 Final Audit](D:/agent_study/askdata_studio/learning_report/askdata_phase3_final_audit_report.md)。本轮纯文档设计没有重新执行回归，也不声称上述新契约已有测试通过。

待实现阶段确定的配置包括模型 token 预算、受控表达词典和持久化关联的具体存储结构；不改变本设计已确定的单一事实入口、局部引用、状态保留与禁止重算原则。

**Phase 4.1 Response Contract Design 已完成。本轮未修改代码，未实现 LLM 调用、Prompt、ResponseGenerator 迁移或 Workflow 接入。**
