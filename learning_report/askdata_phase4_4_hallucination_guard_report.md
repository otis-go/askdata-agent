# Phase 4.4 Hallucination Guard Report

本阶段为业务信号解释链新增独立的确定性 Response Validator。它将 ExplanationResponse 与当前 PromptPackage 比较，允许已提供事实的受控表达，拒绝事实修改、引用错配和新增自由业务结论。

**结果：Validator 33/33，Explanation 145/145，Business Signal 654/654，Workflow/Service 70/70，backend 1249/1249。** 相对 1216 基线新增 33 项测试。

## 1. Validator 设计

新增 [validator.py](D:/agent_study/askdata_studio/backend/app/querying/explanation/validator.py:171)：

```python
validate_response(
    response: ExplanationResponse,
    package: PromptPackage,
) -> ValidationResult
```

ValidationResult 使用严格、冻结、拒绝未知字段的模型：

| 字段 | 语义 |
| --- | --- |
| `version` | Validator 契约版本 |
| `status` | validated / validation_failed |
| `validated_response` | 校验通过后的独立响应；失败为 None |
| `issues` | 受控错误 code 与结构位置；成功为空 |

`validated` 只表示响应合同与当前包一致，不表示 Signal 已计算成功或解释已经生成。合法的 failed、unavailable、not_requested、validation_failed 状态也可以通过结构校验，保留各自生成状态。

Validator 不修补候选、不替换其中的错误数值，不根据业务常识判断“看起来合理”。非法输入及绕过常规构造的对象被明确拒绝，失败结果不携带候选事实或自由文本。

实现顺序是先检查原始对象树，再进行模型实例重验，最后通过严格 JSON 恢复得到独立对象。这样不会先序列化丢弃隐藏字段，或通过 JSON 转换掩盖错误容器/索引类型。循环、缺字段和未知字段均返回失败。

## 2. 检查规则

| 检查 | 确定性规则 |
| --- | --- |
| 当前输入合同 | 重验 PromptPackage 和响应结构，拒绝未知字段、非法类型及损坏对象 |
| Signal 范围 | 保留当前包的原 Signal 索引和顺序，不允许新增、遗漏、重复或跨 Signal 引用 |
| Formula | formula_id、version、所属 Signal 和操作数引用必须与当前包一致 |
| 数字与单位 | value、unit 逐字一致；不作浮点/Decimal 运算、百分比转换或数值等价推断 |
| Evidence | 按 Signal 作用域内的 EvidenceRef 定位；citation 必须是当前包对应操作数的原摘要 |
| Undefined | 原 status、None、reason_code 保留，不能改为 0 或 computed |
| 受控表达 | block variant、wording 必须属于已有受控表达；text 必须符合既有确定性渲染 |
| 审计与范围 | 原 policy、business key、quality、limitations、notices、omissions 和展示覆盖均保留 |

例如，`0.5` 不能改写成 `50%`、`0.50` 或其他单位，即便调用者认为数值等价。Validator 不负责显示格式转换。

S2 的 undefined Signal 可以包含已计算的 absolute_change：Validator 保留该事实，同时要求 change_rate 继续为 undefined / None。不会因为顶层 undefined 而删除已有子结果，也不会生成增长、下降、已完成等自由结论。

S3 多条 Signal 可以拥有相同 evidence_id，但引用按 `(signal_index, evidence_id)` 区分，不能借用其他 Signal 的 total citation。任何新的表述必须属于现有受控表达，不通过关键词匹配或复杂 NLP 判断。

## 3. Response 流程变化

```text
LLM raw JSON
    → 既有严格解析与受控候选构建
    → ExplanationResponse candidate
    → validate_response(candidate, current_prompt_package)
    → ValidationResult
         ├─ validated → validated_response
         └─ validation_failed → 安全失败 ExplanationResponse
```

现有模型只选择 signal_index、固定 expression_variant 和 summary/operands wording。严格 JSON 解析仍拒绝代码围栏、前后自由文本、重复 key、额外业务值和非法类型；无法构建候选时也进入 validation_failed，不修补模型输出。

[ResponseGenerator](D:/agent_study/askdata_studio/backend/app/querying/response_generator.py:49) 在返回模型生成的候选前调用 Validator。[QueryGraph](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:317) 在附加解释结果前再次使用同一 Validator，防止自定义生成器或其他调用路径返回另一份输入的响应。

原 `response_adapter.validate_response_for_package` 保留为兼容接口，委托新 Validator，不再维护另一套来源比较规则。既有 Prompt Builder、表达词典和 renderer 未改变。

## 4. 失败策略

校验不通过时：

```text
generation_status = validation_failed
diagnostic_codes = [RESPONSE_VALIDATION_FAILED]
presentation_coverage = none
blocks = []
citations = []
text = 固定的解释不可生成说明
```

成功查询的 SQL 表格继续保留。响应不包含被拒绝的数字、自由业务结论或异常原文，不回退到 SQL rows、旧 analysis_context 或历史答案。

模型传输异常仍为 `failed / LLM_CALL_FAILED`；缺 SignalBatch、Prompt 不可用和空事实保留原有状态。新增 validation_failed 明确区分“未能调用模型”和“收到的解释未通过校验”。旧 INVALID_LLM_RESPONSE 诊断仍可恢复历史安全失败记录，新校验拒绝路径使用 RESPONSE_VALIDATION_FAILED。

## 5. 测试

新增 [test_response_validator.py](D:/agent_study/askdata_studio/backend/tests/test_response_validator.py)，33 个测试方法。核心回归包括正常 S1/S2/S3、数字与单位修改、错误 Signal/formula/Evidence 引用、undefined 改 0、unsupported variant、跨 Signal 引用、自由文本、输入不修改、JSON roundtrip 和确定性。

除畸形对象外，还验证“另一份包中合法、自洽的响应”不能作为当前包的解释，确保来源对比有独立作用，而不只是重复 Pydantic 的形状检查。

集成测试验证 Generator 和 Graph 实际使用 Validator，校验失败保留表格且不回灌历史上下文。原迁移测试保留覆盖，只将非法输出的预期状态更新为 validation_failed；模型调用异常仍期望 failed。

独立复核另外发现深度嵌套 raw JSON 的解析 RecursionError 原先会逃出 Generator。现已纳入 validation_failed，并加入 Generator/Graph 联合负向测试，确认没有错误事实发布且表格仍保留。

## 6. 回归结果与范围

| 测试集合 | 结果 |
| --- | --- |
| Response Validator | 33/33 |
| Explanation（原 112 + Validator 33） | 145/145 |
| Business Signal | 654/654 |
| Workflow/Service（执行契约 15 + Graph 30 + Service 25） | 70/70 |
| backend full | 1249/1249 |

分组存在重叠，不相加计算 backend 总数。各分组先独立验证；新增深度 JSON 回归后，再运行全部 Validator 和完整 backend。最终命令是在 `backend` 下执行 `.\.venv\Scripts\python.exe -m unittest discover -s tests -q`，1249 个测试于 33.326 秒内全部通过。测试没有真实远端 LLM 调用，模型输出使用替身。

新增文件为 Validator、测试和本报告；本轮修改的既有文件仅有：

- `response_generator.py`：返回前的 Validator 门禁及 validation_failed 分类。
- `explanation/response_models.py`：新增生成状态及受控诊断 code。
- `explanation/response_adapter.py`：旧校验 helper 委托新 Validator。
- `workflows/query_graph.py`：附加结果前使用新 Validator。
- `test_response_generator_migration.py`、`test_query_graph_explanation_migration.py`：保留原断言，更新校验失败状态预期。

与本轮开始时 124 个源码/测试文件的 SHA-256 快照比较，只有上述 6 个既有文件变化。`git diff --check` 通过。未执行 git add、commit 或 tag，原暂存状态保留；新增 Validator、测试和报告尚未暂存。

本阶段未修改 Phase 3 的 Calculator、SignalEngine、Compatibility、Alignment、Numeric Reader 或 Evidence Builder。Graph 仅替换附加解释前的校验调用，没有增加节点或调整路由。

Guard 保护的是来自 SignalBatch 的业务解释，仍依赖受信上游包的正确性与授权；它不重新确认 metric、期间、Alignment 或计算公式是否适用。既有预处理器普通直接回答与 SQL 执行错误展示属于独立路径，不在本轮范围。

验证结果是本次输入比较的结果，不是安全签名或可跨请求复用的认证凭证。后续恢复已存解释时，仍应针对对应 PromptPackage 重新校验。确定性结论针对固定输入，未宣称远端 LLM 逐字确定。

**未实现：LLM Judge、第二模型、多 Agent 审核、自动业务推理或 Workflow 重构。**
