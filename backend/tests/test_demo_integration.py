"""HTTP presentation integration with the existing real Graph and Signal engine.

SQL acquisition and model choices use the Phase 4 boundary fixtures. The service,
API serialization, SignalBatch, explanation pipeline and display adapter run.
"""

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes
from app.api.signal_presentation import present_business_signals
from app.config import Settings
from app.models import QueryResult
from app.querying.business_signals.engine import SignalEngine
from app.retrieval import SchemaIndex
from app.services.askdata_service import AskDataService
import test_query_graph_explanation_migration as graph_fixtures
from test_sales_change import s2_inputs
from test_signal_engine import s1, s2, s3
from test_target_attainment import s1_inputs


class DemoIntegrationTests(unittest.TestCase):
    @contextmanager
    def api(self, signals, failure=None):
        fixture = graph_fixtures.QueryGraphExplanationMigrationTests()
        source = None if failure == "no_signal" else fixture.source_for(signals)
        execution = fixture.execution_for(signals)
        workflow, model = fixture.workflow(source, execution=execution)
        if failure == "llm":
            model.chat.side_effect = RuntimeError("PRIVATE_PROVIDER_ERROR")
        elif failure == "validator":
            model.chat.side_effect = None
            model.chat.return_value = json.dumps({"text": "INVENTED_VALUE_999"})
        with tempfile.TemporaryDirectory() as temporary:
            config = Settings(api_key="", embedding_dimensions=32, session_archive_enabled=False)
            index = SchemaIndex(model, config, Path(temporary) / "schema_index.json")
            service = AskDataService(model, index, signal_source=source)
            service.workflow = workflow
            application = FastAPI()
            application.include_router(routes.router)
            with patch.object(routes, "service", service), TestClient(application) as client:
                token = client.post("/api/auth/login", json={
                    "username": "admin", "password": "admin123",
                }).json()["access_token"]
                client.headers["Authorization"] = f"Bearer {token}"
                yield client, execution, workflow, model

    def test_three_queries_cross_http_service_graph_and_return_three_layers(self):
        scenarios = (
            ("8月各区域目标完成率？", s1),
            ("哪个区域销售下降？", s2),
            ("哪个产品贡献最高？", s3),
        )
        for question, factory in scenarios:
            signals = factory()
            with self.subTest(question=question), self.api(signals) as (client, execution, workflow, model):
                response = client.post("/api/query", json={"query": question, "session_id": "demo-http"})
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["status"], "completed")
                for key in ("sql", "columns", "rows"):
                    self.assertEqual(payload[key], execution[key])
                self.assertEqual(payload["explanation"]["generation_status"], "generated")
                self.assertEqual(payload["analysis"], payload["explanation"]["text"])
                self.assertEqual(len(payload["business_signals"]), len(signals))
                for shown, original in zip(payload["business_signals"], signals):
                    self.assertEqual(shown["signal_type"], original.signal_type)
                    self.assertEqual(shown["status"], original.status)
                    self.assertEqual(shown["computed_value"], original.model_dump(mode="json")["computed_value"])
                    self.assertEqual(shown["business_key"], original.model_dump(mode="json")["business_key"])
                    self.assertNotIn("evidence", shown)
                    for summary, evidence in zip(shown["evidence_summary"], original.evidence):
                        self.assertEqual(set(summary), {
                            "evidence_id", "context_role", "result_id", "column_id", "row_index",
                            "source_fields", "business_key", "formula_refs",
                        })
                        for key in summary:
                            self.assertEqual(summary[key], evidence.model_dump(mode="json")[key])
                saved = workflow.graph.get_state(workflow.run_config(payload["task_id"])).values
                self.assertIsNotNone(saved["signal_batch"])
                self.assertEqual(saved["result"]["business_signals"], payload["business_signals"])
                model.chat.assert_called_once()
                reloaded = client.get(f"/api/tasks/{payload['task_id']}")
                self.assertEqual(reloaded.status_code, 200)
                self.assertEqual(reloaded.json()["business_signals"], payload["business_signals"])
                self.assertEqual(QueryResult.model_validate(payload).model_dump(mode="json"), payload)

    def test_no_signal_llm_and_validator_failures_keep_successful_table(self):
        for failure, status, diagnostic, signal_count in (
            ("no_signal", "unavailable", "NO_SIGNAL_BATCH", 0),
            ("llm", "failed", "LLM_CALL_FAILED", 1),
            ("validator", "validation_failed", "RESPONSE_VALIDATION_FAILED", 1),
        ):
            with self.subTest(failure=failure), self.api(s1(), failure) as (client, execution, _, model):
                response = client.post("/api/query", json={"query": "8月各区域目标完成率？"})
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["status"], "completed")
                for key in ("sql", "columns", "rows"):
                    self.assertEqual(payload[key], execution[key])
                explanation = payload["explanation"]
                self.assertEqual(explanation["generation_status"], status)
                self.assertEqual(explanation["diagnostic_codes"], [diagnostic])
                self.assertEqual(explanation["blocks"], [])
                self.assertEqual(explanation["citations"], [])
                self.assertEqual(explanation["text"], "当前无法生成业务解释。")
                self.assertEqual(len(payload["business_signals"]), signal_count)
                self.assertNotIn("PRIVATE_PROVIDER_ERROR", response.text)
                self.assertNotIn("INVENTED_VALUE_999", response.text)
                self.assertEqual(model.chat.call_count, 0 if failure == "no_signal" else 1)

    def test_empty_batch_is_not_requested_and_keeps_table(self):
        with self.api(s1()) as (client, execution, workflow, model):
            workflow.signal_source = graph_fixtures.QueryGraphExplanationMigrationTests.source_for([])
            response = client.post("/api/query", json={"query": "没有可展示信号"})
            payload = response.json()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(payload["rows"], execution["rows"])
            self.assertEqual(payload["business_signals"], [])
            self.assertEqual(payload["explanation"]["generation_status"], "not_requested")
            model.chat.assert_not_called()

    def test_adapter_obeys_batch_display_indices_and_keeps_undefined_values(self):
        failed = s1(s1_inputs(actual=[["华东", None]]))[0]
        undefined = s2(s2_inputs(baseline=[["华东", "0"]]))[0]
        batch = SignalEngine().build([failed, undefined])
        shown = present_business_signals(batch)
        self.assertEqual([item.signal_index for item in shown], batch.displayable_signal_indices)
        self.assertEqual(len(shown), 1)
        self.assertEqual(shown[0].status, "undefined")
        self.assertIsNone(shown[0].computed_value["change_rate"].value)
        self.assertEqual(shown[0].computed_value, undefined.computed_value)

    def test_projection_is_detached_and_does_not_recompute(self):
        batch = SignalEngine().build(s1())
        before = deepcopy(batch)
        with graph_fixtures.no_upstream_calls():
            shown = present_business_signals(batch)
        shown[0].computed_value.clear()
        shown[0].business_key.components.clear()
        shown[0].evidence_summary[0].formula_refs.clear()
        self.assertEqual(batch, before)

    def test_invalid_or_missing_batch_does_not_publish_display_facts(self):
        for supplied in (None, {}, {"signals": []}, {"version": "invalid"}):
            with self.subTest(supplied=supplied):
                self.assertEqual(present_business_signals(supplied), [])

    def test_legacy_query_result_defaults_to_no_business_signals(self):
        result = QueryResult(task_id="legacy", status="completed", route="database_query", message="查询完成",
                             sql="SELECT 1 AS amount", columns=["amount"], rows=[{"amount": 1}])
        self.assertEqual(result.business_signals, [])
        self.assertIsNone(result.explanation)
        self.assertEqual(QueryResult.model_validate_json(result.model_dump_json()), result)


if __name__ == "__main__":
    unittest.main()
