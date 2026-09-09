"""Opt-in Phase 5 demo composition; never imported by the production entrypoint.

Only the three published questions use this fixed query catalog. Acquisition is
real: DuckDB reads the existing CSVs and the existing semantic builder captures
their SQL. Explicit catalog attestations supply the business authority that SQL
cannot prove. All qualification, alignment, arithmetic, prompt construction and
response validation remain in their original implementations.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, replace
from threading import Lock
from typing import Literal

from .config import Settings, settings
from .database import SCHEMA
from .errors import PipelineStageError
from .model_client import ModelClient
from .models import QueryResult
from .querying.business_signals.alignment import align_context_keys
from .querying.business_signals.compatibility import (
    check_context_compatibility, context_digest, filter_scope_digest,
)
from .querying.business_signals.models import InputDeclaration, ProductContributionInput, SignalInput
from .querying.business_signals.policies import NumericRules, TargetAttainmentPolicy
from .querying.business_signals.product_contribution import compute_product_contribution
from .querying.business_signals.product_contribution_policy import product_sales_contribution_v1
from .querying.business_signals.sales_change import compute_sales_change
from .querying.business_signals.sales_change_policy import monthly_sales_change_v1
from .querying.business_signals.target_attainment import compute_target_attainment
from .querying.response_generator import ResponseGenerator
from .querying.result_understanding.builder import build_business_context
from .retrieval import SchemaIndex
from .security import AccessScope
from .services.askdata_service import AskDataService
from .workflows.query_graph import QueryWorkflow
from .workflows.signal_delivery import SignalDelivery, SignalRequest, execution_digest


LlmMode = Literal["live", "fixture"]
FailureMode = Literal["none", "no-signal", "llm", "validator"]
DATABASE = "askdata_mock"
ISSUER = "phase5-demo-catalog-v1"
ROLE_TABLES = {"actual": "orders_current", "target": "sales_targets",
               "current": "orders_current", "baseline": "orders_history",
               "parts": "orders_current", "total": "orders_current"}


@dataclass(frozen=True)
class DemoScenario:
    question: str
    kind: str
    title: str
    roles: tuple[str, str]
    period_label: str


SCENARIOS = (
    DemoScenario("8月各区域目标完成率？", "s1", "各区域目标完成率", ("actual", "target"), "2026-08"),
    DemoScenario("哪个区域销售下降？", "s2", "各区域销售变化", ("current", "baseline"), "2026-08 对比 2026-07"),
    DemoScenario("哪个产品贡献最高？", "s3", "全部产品销售贡献", ("parts", "total"), "2026-08"),
)


def _scenario(question: str) -> DemoScenario:
    # Punctuation normalization is presentation only; no new metric selection.
    normalized = question.strip().rstrip("?？")
    for scenario in SCENARIOS:
        if normalized == scenario.question.rstrip("？"):
            return scenario
    raise PipelineStageError("demo_catalog", "此演示入口仅支持页面提供的三个固定问题。")


def _source(role: str, field: str) -> dict:
    return {"database": DATABASE, "table": ROLE_TABLES[role], "field": field}


def demo_sql(scenario: DemoScenario, role: str) -> str:
    """Author-owned fixed SQL. ORDER BY retains every group; no top-N selection."""
    table = ROLE_TABLES[role]
    if role == "target":
        return ("SELECT region, SUM(target_amount) AS sales_amount FROM sales_targets "
                "WHERE target_month = '2026-08' GROUP BY region ORDER BY region")
    lower, upper = (("2026-07-01", "2026-08-01") if role == "baseline"
                    else ("2026-08-01", "2026-09-01"))
    key = "product_id" if scenario.kind == "s3" else "region"
    projection = "" if role == "total" else key + ", "
    grouping = "" if role == "total" else f" GROUP BY {key}"
    ordering = "" if role == "total" else (" ORDER BY sales_amount DESC, product_id" if scenario.kind == "s3" else " ORDER BY region")
    return (f"SELECT {projection}SUM(paid_amount) AS sales_amount FROM {table} "
            f"WHERE order_date >= '{lower}' AND order_date < '{upper}' "
            f"AND status = '已支付'{grouping}{ordering}")


def _numeric_rules() -> NumericRules:
    # DuckDB reads the supplied CSV amounts as DOUBLE. The already supported
    # reporting profile preserves that approximate source quality explicitly.
    return NumericRules(profile="reporting_approx_v1", accepted_encodings=["native_json", "decimal_text"],
                        allow_binary_float=True, reconciliation="relative_tolerance", relative_tolerance="1e-12")


def _target_policy() -> TargetAttainmentPolicy:
    """Explicit demo actual-to-target basis; no formula implementation here."""
    roles = ("actual", "target")
    metric_ids = {"actual": "actual_paid_sales", "target": "regional_monthly_sales_target"}
    policy = TargetAttainmentPolicy.model_validate({
        "policy_id": "phase5-monthly-regional-target-v1", "definition_digest": "pending",
        "supported_contract_versions": {"result_contract": ["1"], "business_context": ["1"], "business_signal": ["1"]},
        "metric_rules": [{"context_role": role, "metric_id": metric_ids[role], "mapping_id": f"{role}-paid-map",
                          "allowed_sources": [_source(role, "target_amount" if role == "target" else "paid_amount")],
                          "allowed_aggregations": ["SUM"]} for role in roles],
        "relationship_rules": [{"relationship_id": "paid-target-basis-v1", "operation": "divide",
                                "left_role": "actual", "right_role": "target", "left_metric_id": metric_ids["actual"],
                                "right_metric_id": metric_ids["target"], "metric_relationship": "actual_to_target"}],
        "grain_rules": [{"context_role": role, "grain": "grouped", "grouping_sources": [_source(role, "region")]} for role in roles],
        "key_rules": [{"domain_id": "sales-region", "component_id": "region", "value_type": "string",
                       "sources": [{"context_role": role, "source": _source(role, "region")} for role in roles]}],
        "time_rules": {"relationship": "same_calendar_month", "sources": [
            {"context_role": role, "domain_id": "sales-calendar",
             "allowed_sources": [_source(role, "target_month" if role == "target" else "order_date")],
             "accepted_precision": "month" if role == "target" else "date",
             "accepted_range": "month_equality" if role == "target" else "closed_open_month"} for role in roles]},
        "filter_rules": {"comparison": "role_specific_metric_basis", "require_metric_basis_declaration": True,
                         "roles": [{"context_role": role, "required_conditions": [] if role == "target" else [
                             {"domain_id": "payment-status", "source": _source(role, "status"), "operator": "=",
                              "value": {"value_type": "string", "value": "已支付"}}]} for role in roles]},
        "numeric_rules": _numeric_rules(), "missing_rules": {},
        "duplicate_rules": {"source_uniqueness_required_roles": ["target"]},
        "completeness_rules": {"population": "require_scope_declaration"},
        "declaration_rules": [{"context_role": role,
                               "required_types": ["unit", "time_domain", "row_selection", "population", "snapshot_revision"]
                                                 + (["source_key_uniqueness", "metric_basis"] if role == "target" else []),
                               "accepted_issuer_kinds": ["fixture_catalog"], "accepted_issuer_refs": [ISSUER],
                               "accepted_evidence_grades": ["trusted_declaration"]} for role in roles],
        "unit_rules": {}, "limitation_rules": {},
        "formula_refs": [{"output_key": "attainment_rate", "formula_id": "attainment_rate", "input_roles": list(roles)}],
        "snapshot_rules": {"relationship": "same_revision"},
    })
    canonical = json.dumps(policy.model_dump(mode="json", exclude={"definition_digest"}), sort_keys=True, separators=(",", ":"))
    return policy.model_copy(update={"definition_digest": "demo-policy:sha256:" + hashlib.sha256(canonical.encode()).hexdigest()})


def _signal_input(scenario, role, context, revision, unique_targets) -> SignalInput:
    """Issue catalog attestations bound to the real result and semantic digest.

    CNY, paid-target basis and complete fixture population are demo-catalog
    declarations, never inferred from SQL aliases. Source key uniqueness is
    checked against the current target CSV before it can be declared.
    """
    is_target = role == "target"
    key = "product_id" if scenario.kind == "s3" else "region"
    domain = "product-id" if scenario.kind == "s3" else "sales-region"
    metric = _source(role, "target_amount" if is_target else "paid_amount")
    temporal = _source(role, "target_month" if is_target else "order_date")
    metric_column = context.execution.columns[-1].id
    columns = [column.id for column in context.execution.columns]
    lower, upper = (("2026-07-01", "2026-08-01") if role == "baseline" else ("2026-08-01", "2026-09-01"))
    population = "phase5-paid-sales-fixture-population-v1"
    scope = {"source_fields": [binding.source.model_dump() for binding in context.query_bindings.bindings],
             "period": {"domain_id": "sales-calendar", "calendar": "gregorian", "precision": "date",
                        "lower": lower, "upper": upper, "lower_inclusive": True, "upper_inclusive": False},
             "population_scope_ref": population, "filter_scope_ref": filter_scope_digest(context),
             "key_domains": [domain], "target_version": "phase5-target-plan-v1" if is_target else None}
    claims = {
        "unit": {"source_fields": [metric], "unit_id": "CNY", "unit_scale": "1", "display_scale": 2},
        "time_domain": {"source_fields": [temporal], "domain_id": "sales-calendar", "calendar": "gregorian",
                        "precision": "month" if is_target else "date", "comparison_domain": "iso_month_text" if is_target else "date"},
        "row_selection": {"mode": "absent"},
        "population": {"population_scope_ref": population, "coverage": "complete",
                       "partition_key_domains": [domain] if scenario.kind == "s3" else []},
        "snapshot_revision": {"dataset_ref": "phase5-existing-csv-dataset", "revision_ref": revision},
    }
    if is_target:
        claims["source_key_uniqueness"] = {"source_fields": [_source(role, "region"), temporal],
                                           "key_domains": [domain, "sales-calendar"],
                                           "uniqueness": "unique" if unique_targets else "duplicate"}
        claims["metric_basis"] = {"metric_id": "regional_monthly_sales_target", "counterpart_metric_id": "actual_paid_sales",
                                  "basis_id": "paid-target-basis-v1", "status_value": "已支付"}
    declarations = [InputDeclaration.model_validate({
        "declaration_id": f"{role}-{name}-v1", "declaration_type": name, "result_id": context.result_id,
        "context_digest": context_digest(context), "column_ids": columns, "issuer_kind": "fixture_catalog",
        "issuer_ref": ISSUER, "basis_ref": f"demo-catalog:{role}:{name}", "claims": {name: claim},
        "evidence_grade": "trusted_declaration", "scope": scope,
    }) for name, claim in claims.items()]
    return SignalInput(context=context, selection={"metric_column_id": metric_column,
                       "key_column_ids": {} if role == "total" else {key: columns[0]}}, declarations=declarations)


class DemoModelClient(ModelClient):
    """Explicit transport fixture/failure switch; never used by app.main."""
    def __init__(self, config, mode: LlmMode, failure: FailureMode):
        super().__init__(config)
        self.mode, self.failure = mode, failure

    def chat(self, system: str, user: str, *, temperature: float | None = None) -> str:
        if self.failure == "llm":
            raise RuntimeError("Demo injected model transport failure")
        if self.mode == "live":
            return super().chat(system, user, temperature=temperature)
        payload = json.loads(user)
        # Fixture chooses presentation identifiers only. It never writes the
        # explanation, business values, formulas, SQL or evidence.
        return json.dumps({"blocks": [{"signal_index": block["ref"]["signal_index"],
                                       "expression_variant": block["expression_variant"], "wording": "summary"}
                                      for block in payload["fact_blocks"]]})


class _InvalidDemoResponseGenerator(ResponseGenerator):
    def finalize(self, package):
        response = super().finalize(package)
        # Corrupt a real generated response, then let the unchanged graph-level
        # ResponseValidator reject it. No validation result is mocked.
        return response.model_copy(update={"text": "DEMO_INVALID_RESPONSE 999"})


class DemoQueryWorkflow(QueryWorkflow):
    def __init__(self, model_client, schema_index, config, *, mode, failure):
        self.mode, self.failure = mode, failure
        self._deliveries = {}
        self._delivery_lock = Lock()
        super().__init__(model_client, schema_index, config, signal_source=self._deliver)
        if failure == "validator":
            self.response_generator = _InvalidDemoResponseGenerator(model_client)

    def _deliver(self, request):
        with self._delivery_lock:
            return self._deliveries.pop(request.task_id, None)

    def _preprocess(self, state):
        scenario = _scenario(state["query"])
        return {**self._clear_explanation(), "execution_result": None, "result": {},
                "intent": {"action": "database_query", "confidence": 1.0, "reason": "Phase 5 固定 Demo 目录", "source": "demo_catalog"},
                "standalone_query": f"{scenario.question}（{scenario.period_label}，已支付订单，全部分组）",
                "rewritten": True, "extraction": {"time_expressions": [scenario.period_label]}, "execution_log": []}

    def _retrieve_schema(self, state):
        scenario = _scenario(state["query"])
        tables = list(dict.fromkeys(ROLE_TABLES[role] for role in scenario.roles))
        return {"database_names": [DATABASE], "schema_graph": {"tables": [{"id": table} for table in tables]},
                "schema_context": "固定 Demo SQL 目录", "retrieval": {}, "clarification": None}

    def _revision(self):
        folder = self.database_engine.database_root / DATABASE
        digest = hashlib.sha256()
        for name in sorted(set(ROLE_TABLES.values())):
            digest.update(name.encode())
            digest.update((folder / f"{name}.csv").read_bytes())
        return "csv:sha256:" + digest.hexdigest()

    def _prepare_single_database(self, state):
        scenario = _scenario(state["query"])
        scope = AccessScope.from_dict(state["access_scope"])
        revision = self._revision()
        executions = {role: self.database_engine.execute(DATABASE, demo_sql(scenario, role), scope) for role in scenario.roles}
        failed = next((item for item in executions.values() if not item.success), None)
        primary = failed or executions[scenario.roles[0]]
        payload = self._execution_payload(primary)
        if failed is None and self.failure != "no-signal":
            with (self.database_engine.database_root / DATABASE / "sales_targets.csv").open(encoding="utf-8-sig", newline="") as handle:
                target_keys = [(row["region"], row["target_month"]) for row in csv.DictReader(handle) if row["target_month"] == "2026-08"]
            unique_targets = len(set(target_keys)) == len(target_keys)
            if revision != self._revision():
                raise PipelineStageError("demo_capture", "演示CSV在读取期间发生变化，请重试。")
            inputs = {role: _signal_input(scenario, role, build_business_context(execution.result_contract, SCHEMA), revision, unique_targets)
                      for role, execution in executions.items()}
            options = {"database": DATABASE, "accepted_issuer_kinds": ["fixture_catalog"],
                       "accepted_issuer_refs": [ISSUER], "numeric_rules": _numeric_rules()}
            policy = (_target_policy() if scenario.kind == "s1" else monthly_sales_change_v1(**options) if scenario.kind == "s2"
                      else product_sales_contribution_v1(**options, allow_global_total=True))
            compatibility = check_context_compatibility(inputs, policy, operation="compare" if scenario.kind == "s2" else "divide")
            alignment = align_context_keys(inputs, compatibility, policy)
            if scenario.kind == "s1":
                signals = compute_target_attainment(inputs["actual"], inputs["target"], compatibility, alignment, policy)
            elif scenario.kind == "s2":
                signals = compute_sales_change(inputs["current"], inputs["baseline"], compatibility, alignment, policy)
            else:
                signals = compute_product_contribution(ProductContributionInput(**inputs), compatibility, alignment, policy)
            request = SignalRequest(task_id=state["task_id"], query=state["query"], session_id=state["session_id"],
                                    user_id=scope.user_id, route="database_query", execution_result_id=primary.result_id,
                                    execution_digest=execution_digest(payload))
            with self._delivery_lock:
                self._deliveries[request.task_id] = SignalDelivery(request=request, signals=tuple(signals))
        return {"workflow_mode": "phase5_demo_catalog", "clarification": None, "mcp_execution": payload,
                "mcp_tool_trace": [], "direct_sql": primary.sql, "sql_source": "demo_catalog"}

    def _execute_single_database(self, state):
        update = super()._execute_single_database(state)
        scenario = _scenario(state["query"])
        result = QueryResult.model_validate(update["result"])
        label = "真实 LLM" if self.mode == "live" else "fixture 验证模式（未调用真实 LLM）"
        if self.failure != "none":
            label += f" · 故障注入：{self.failure}"
        result.result_title = f"{scenario.title} · {'真实 LLM' if self.mode == 'live' else 'fixture'}"
        # No retriever or schema-graph builder ran in this fixed catalog path.
        # Their existing UI widgets expect full production payloads, so omit
        # the optional public sections instead of exposing partial objects.
        result.retrieval = None
        result.schema_graph = None
        result.steps = ["固定 Demo 问句与只读 SQL 目录", "原 DuckDB 执行真实 CSV 查询",
                        "原 Semantic Layer 构建 BusinessContext", "显式 Demo 声明 + 原 Compatibility / Alignment / S1-S3"]
        if result.interpretation:
            result.interpretation.time_range = f"{scenario.period_label} · {label}"
            result.interpretation.assumptions = ["已支付订单；CNY；固定演示目录声明完整期间与目标口径",
                                               "原 DOUBLE 数据使用既有 reporting_approx_v1；保留近似品质",
                                               "全部分组，未做 TopN 截断"]
        for item in update["execution_log"]:
            if item.get("stage") == "execute_duckdb":
                item["via"] = "demo_catalog_duckdb"
        result.execution_log = update["execution_log"]
        result.tool_calls = []
        update["result"] = result.model_dump(mode="json")
        return update


def create_demo_service(*, llm: LlmMode = "live", failure: FailureMode = "none", config: Settings | None = None) -> AskDataService:
    if llm not in ("live", "fixture") or failure not in ("none", "no-signal", "llm", "validator"):
        raise ValueError("Unknown demo mode")
    config = replace(config or settings, session_archive_enabled=False, short_term_summary_enabled=False)
    client = DemoModelClient(config, llm, failure)
    index = SchemaIndex(client, config)
    service = AskDataService(client, index)
    service.workflow = DemoQueryWorkflow(client, index, config, mode=llm, failure=failure)
    return service


def create_demo_app(*, llm: LlmMode = "live", failure: FailureMode = "none"):
    # Existing routes, auth and CORS remain the HTTP contract. This assignment
    # occurs only in a dedicated demo process, never in the normal entrypoint.
    from .api import routes
    from .main import app
    routes.service = create_demo_service(llm=llm, failure=failure)
    app.title = "AskData Studio — Phase 5 Demo"
    return app
