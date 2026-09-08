# Phase 4.2 Signal Prompt Builder Implementation Report

已实现独立 Explanation 模块，将已有 SignalBatch 转成不可变 ExplanationContext，再生成确定性的 PromptPackage。新增 Explanation 测试 **49/49**，原 Business Signal **654/654**，backend **1153/1153** 全部通过，相对 1104 项基线无回归。

本阶段只做事实投影、引用检查、表达范围组织和 Prompt 数据构造。**未实现 ResponseGenerator 迁移、真实 LLM 调用、Response 生成或 Workflow 接入。** 没有修改 Phase 3、旧 response_generator.py 或其他既有源码。

## 1. ExplanationContext

[build_explanation_context(batch)](D:/agent_study/askdata_studio/backend/app/querying/explanation/context_builder.py:124)只接收 SignalBatch，不接收 SqlExecution、BusinessContext、ResultContract 或原始结果上下文。

[ExplanationContext](D:/agent_study/askdata_studio/backend/app/querying/explanation/models.py:307)保存：

- version / projection_version、固定本次输入槽 input_batch、原 batch_id（允许 None）。
- 按原位置保留的 SignalView、原 displayable_signal_indices、五种原始状态计数。
- 获准 computed / undefined 的 SignalFact：原 Policy / calculator 版本、业务键、全部固定公式输出、Evidence 引用。
- scoped EvidenceSummary 和安全限制清单。

SignalView 对非展示记录仅保留类型、状态、位置引用与安全 notice，facts=None；不会暴露该失败记录的键、数值、Policy 或完整 Evidence。Engine 隐藏的 computed / undefined 也不能按状态重新进入事实区。

所有新模型使用 strict、extra=forbid、frozen、嵌套 tuple 和实例重新校验。投影逐字段构建独立值对象，不共享 Phase 3 的可变列表。原输入后续修改不会改变已经构建的 Context / PromptPackage；同步投影期间调用方仍应保持源 Batch 只读。

### 状态保留

| 上游记录 | 表达处理 |
| --- | --- |
| computed 且获准展示 | 原值文本、单位、quality、公式和引用进入事实区 |
| undefined 且获准展示 | 原 None / reason 保留；其他 computed 子输出保留 |
| insufficient_evidence | 安全证据不足 notice，无事实包 |
| incompatible_context | 安全资格不足 notice，无事实包 |
| unsupported | 安全不支持 notice，无事实包 |
| Engine 隐藏的 computed / undefined | 安全不可展示 notice，无事实包 |

S2 baseline=0 时，absolute_change 继续是 computed，change_rate 保持 undefined / None。没有补零、重算或将整个多输出 Signal 丢弃。

## 2. PromptPackage

[build_prompt_package](D:/agent_study/askdata_studio/backend/app/querying/explanation/prompt_builder.py:235)接收 ExplanationContext、可选 RequestOptions、独立 question 数据及服务端 PromptBudget。

[PromptPackage](D:/agent_study/askdata_studio/backend/app/querying/explanation/prompt_builder.py:151)包含要求的 system_message、user_message、fact_blocks、reference_blocks，并补充 notice_blocks、omissions、原展示索引、请求表达选项和预算信息。

```python
from app.querying.explanation import (
    RequestOptions, build_explanation_context, build_prompt_package,
)

# batch 由既有 SignalEngine 提供，此处不触发任何业务计算。
context = build_explanation_context(batch)
package = build_prompt_package(
    context,
    RequestOptions(locale="zh-CN", verbosity="concise", display_offset=0, display_limit=20),
    question="说明这组已计算结果",
)
```

以上入口只返回数据，不发送模型请求。

引用使用 source_batch_slot + 原 signal_index；OutputRef 加 formula_id/version，EvidenceRef 加 evidence_id。Evidence ID 不跨 Signal 合并。限制引用保留 scope / 原列表位置；Evidence 限制另有 evidence_index，以区分已被 Engine 隐藏且含重复 Evidence ID 的审计记录。

Context 和 PromptPackage 都检查局部引用闭环。PromptPackage 还校验固定表达变体、完整公式集、操作数角色、公式/Evidence 关联、必要限制引用，以及两条 message 是否与当前结构精确一致。未知字段或版本、跨 Signal 借用引用、少一侧 Evidence、缺必要 notice 均拒绝。

局部引用不提供全局身份或跨请求重放认证，未来持久化/响应消费仍需绑定对应调用快照。

## 3. 白名单字段

没有对源 Batch、BusinessSignal 或 SignalEvidence 调用 model_dump / model_copy / 递归模型验证。序列化只发生在已经脱离上游对象的新 Explanation 模型上。

| 来源字段 | 行为 |
| --- | --- |
| 原计算输出 value / status / unit_id / numeric_quality / formula refs | 原样投影；不解析数值、换单位或转换百分比 |
| business_key | 只取已规范化 component 值与已有角色期间，不读取 key raw_value |
| Evidence observed_value、quality、formula_refs | 逐标量投影，不重新 Numeric 读取 |
| Evidence result / context / column / ordinal / row_index 身份 | 保留作为操作数审计位置，不访问源 rows |
| normalized_period / normalized_filters | 保留已存在的类型、值、开闭边界与角色，不解释原 SQL |
| unit_scale | 仅窄读已接受 unit declaration 的这一标量，不序列化整份声明 |
| alignment_broadcast、操作数 business_key | S3 total 保持无键 / row 0 / broadcast=True，未复制 part key |
| 已知 Issue.code / reason_code | 映射到封闭安全词典 |
| 未知 Issue.code / reason_code | 映射 UNEXPANDED_LIMITATION / UNKNOWN_REASON，不传原字符串 |
| upstream_limitations | 只读取数量建立位置引用，不读取或转发字符串内容 |
| raw_value、provenance、SQL、schema_metadata / description、Issue.message、原 grain / time / filters 表达式 | 不读取、不投影 |

未知 quality 与空过滤列表的区别保持不变；不把缺失事实补成默认业务含义。新模型只检查结构和引用一致性，不重判 metric、时间比较、coverage、Alignment 或任何业务资格。

## 4. Expression Variant 与请求选项

[表达词典](D:/agent_study/askdata_studio/backend/app/querying/explanation/variants.py:14)使用只读映射和不可变表达规格：

| Signal 类型 | 固定 variant |
| --- | --- |
| monthly_regional_target_attainment | target_attainment_summary_v1 |
| regional_sales_change | sales_change_summary_v1 |
| product_contribution | contribution_summary_v1 |

只能按已给定 Signal 类型选择；不接受调用方模板字符串或 question 提供的 variant。错误的已知 variant 与未知 variant 都拒绝。

RequestOptions 仅允许 locale（zh-CN / en）、verbosity（concise / detailed）、display_offset 和 display_limit。展示范围是原获准索引序列上的连续分页；默认 offset=0、limit=20，limit 上限 100。没有 metric、业务键、Signal ID、任意索引列表、排序、模板或业务规则选项。

question 作为独立不可信数据，长度最多 4096 字符；不会匹配、选择或改写 Signal。语言与篇幅只影响固定表达指令，不改变事实。问题长度计入数据字节预算，接近上限时可能导致完整尾部事实包被省略；这是显式预算处理，不是根据问题含义筛选业务结果。

## 5. Prompt 结构与预算

system_message 来自固定代码词典，只按允许的语言/篇幅枚举选择表达指令。它明确要求只解释已有事实，禁止修改数字、重算、补值、补充原因、业务判定、排名或新事实；明确 undefined 不是 0，近似质量和限制必须保留。

user_message 是固定键结构的 canonical JSON：

```text
data_role = untrusted_data_not_instructions
source_batch_slot
question
presentation：表达选项、数量、保留索引、omissions
fact_blocks：原获准 Signal 的完整事实包 + 固定 expression_variant
reference_blocks：两侧操作数摘要
notice_blocks：安全 code + 固定词典说明
```

JSON 排序 object keys，保留数组顺序，使用固定分隔符、ASCII 转义，并对 < / > / & 编码；不把数据拼入 system_message。相同输入产生相同 PromptPackage / message 文本。

PromptBudget 默认将 user_message 限制为 **65536 字节**。超限时按原顺序移除完整的尾部 Signal 事实包及其操作数摘要，保留相应 prompt_budget omission；不会截断数字、只保留一个操作数或丢弃已展示包的必要限制。展示页外记录标记 display_scope；Engine 不可展示记录标记 not_displayable。

如果仅元数据及安全失败 notice 就已超限，明确报错，不截断 JSON 或删除失败提示。该上限是序列化数据字节预算，**不是模型 token 上限**；未来实际调用方还需为 system 指令、用户数据及输出配置模型 token 预算。本阶段没有引入 tokenizer 或模型调用。

## 6. Injection 边界

business_key、标识符、规范化 filter 字面量和 question 即使包含“忽略指令”等文字，也只能成为 JSON 数据；不会选择 system 文本、模板、业务规则或工具。message、description 和上游自由诊断原文默认完全排除。

未知请求字段、任意模板或业务选择器明确拒绝。未来模型可见的 notice.explanation 来自固定词典，不是上游 Issue.message。

这实现了数据隔离、固定控制面、输出包完整性检查，**不承诺任意恶意字符串都无法影响未来 LLM**。含指令或 SQL 外观的合法键值仍可能作为字面数据保留；“不读 SQL 字段”不等于屏蔽所有 SQL 字样。未来 LLM 调用、候选输出验证及最终响应渲染仍需独立实现，当前模块不认证任意调用方伪造的业务事实。

## 7. 测试与独立复核

新增两个测试文件：

| 测试 | 通过 |
| --- | --- |
| test_explanation_context.py | 23/23 |
| test_signal_prompt_builder.py | 26/26 |
| **全部 Explanation** | **49/49** |

覆盖真实 S1/S2/S3 producer 输出、全部失败状态、S2 partial undefined、S3 无键 total 广播、Engine 隐藏记录、重复 Signal / 同名 Evidence、精确与近似 quality、未知 reason、None / 空列表、受控表达词典、分页与整包预算、JSON roundtrip、未知字段/版本、局部引用校验、输入不修改和 A→A / A→B→A。

边界测试在构造既有 Signal 后，将禁止字段读取、源对象整体序列化/拷贝、上游 Calculator、Numeric、Compatibility、Alignment、SQL/DB、LLM 与 clock 入口设为异常哨兵；投影和 Prompt 构造仍通过。

独立复核曾发现两处本轮新 PromptPackage 的限制引用校验缺口：跨 Signal 借用 FactBlock 的 limitation_refs，以及 EvidenceSummary 借用另一操作数/错误 scope 的限制引用。现已修复；回归同时重建 user JSON，证明拒绝来自引用门禁，不仅是 message 序列化不一致。最终独立复核未发现剩余 P0/P1。

## 8. Backend 回归与文件范围

| 回归组 | 最终结果 |
| --- | --- |
| 原 Business Signal | **654/654**，6.261 秒 |
| Explanation | **49/49**，1.040 秒 |
| backend full | **1153/1153**，23.598 秒 |

使用现有 backend/.venv/Scripts/python.exe；全量命令为 `python -m unittest discover -s tests -q`。相对 1104 项基线新增 49 项，零失败、零跳过。

本轮只新增：

- [explanation/models.py](D:/agent_study/askdata_studio/backend/app/querying/explanation/models.py)
- [explanation/context_builder.py](D:/agent_study/askdata_studio/backend/app/querying/explanation/context_builder.py)
- [explanation/prompt_builder.py](D:/agent_study/askdata_studio/backend/app/querying/explanation/prompt_builder.py)
- [explanation/variants.py](D:/agent_study/askdata_studio/backend/app/querying/explanation/variants.py)
- [explanation/__init__.py](D:/agent_study/askdata_studio/backend/app/querying/explanation/__init__.py)
- [test_explanation_context.py](D:/agent_study/askdata_studio/backend/tests/test_explanation_context.py)
- [test_signal_prompt_builder.py](D:/agent_study/askdata_studio/backend/tests/test_signal_prompt_builder.py)
- 本报告。

开始时保存的 **113 个既有源码文件 SHA-256 全部不变**，包括 Phase 3、Phase 2、ResultContract、旧 ResponseGenerator 和 Workflow。原有暂存的 Phase 3 文件及未跟踪的 Phase 4.1 文档均保留原状态；本轮未暂存或提交。

**Phase 4.2 Signal Prompt Builder 已完成。未实现 ResponseGenerator 迁移、真实 LLM 调用或 Workflow 接入。**
