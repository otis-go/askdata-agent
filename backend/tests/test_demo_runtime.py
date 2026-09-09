"""Demo composition tests over real CSV -> DuckDB -> compiled QueryWorkflow.

Only the model transport and explicitly advertised failure modes are fixtures.
No calculator, semantic stage, SignalEngine, PromptBuilder or Validator is
replaced by these tests. Existing production routes are exercised with auth.
"""

import csv
from decimal import Decimal
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import routes
from app.config import BASE_DIR, Settings
from app.demo_integration import SCENARIOS, create_demo_service
from app.main import app
from app.querying.business_signals.batch import SignalBatch
from app.querying.explanation.prompt_builder import PromptPackage
from app.querying.explanation.validator import validate_response
from app.querying.result_understanding.builder import build_business_context
from app.database import SCHEMA
from app.model_client import ModelClient
from app.querying.result_contract import ResultContract
from app.workflows.signal_delivery import SignalDelivery


class DemoRuntimeTests(unittest.TestCase):
    def service(self, failure="none"):
        # Disable real model access in automated checks; live connectivity is
        # an explicit manual acceptance run with the configured credentials.
        return create_demo_service(llm="fixture", failure=failure, config=Settings(api_key=""))

    def submit(self, service, scenario=SCENARIOS[0], user="demo_admin"):
        return service.submit(scenario.question, f"test-phase5-{scenario.kind}", user_id=user)

    def state(self, service, result):
        return service.workflow.graph.get_state(service.workflow.run_config(result.task_id)).values

    def test_three_scenarios_traverse_real_graph_and_current_result_binding(self):
        service = self.service()
        for scenario, count, kind in zip(SCENARIOS, (4, 4, 12), (
            "monthly_regional_target_attainment", "regional_sales_change", "product_contribution",
        )):
            with self.subTest(scenario=scenario.kind):
                result = self.submit(service, scenario)
                self.assertEqual(result.status, "completed")
                self.assertEqual(len(result.rows), count)
                self.assertEqual(len(result.business_signals), count)
                self.assertEqual(result.explanation.generation_status, "generated")
                self.assertIn("fixture", result.result_title)
                self.assertIn(scenario.period_label, result.interpretation.time_range)
                saved = self.state(service, result)
                execution = saved["execution_result"]
                contract = ResultContract.model_validate(execution["result_contract"])
                self.assertEqual(contract.execution.provenance.engine, "duckdb")
                self.assertTrue(contract.execution.provenance.sql_submitted)
                self.assertEqual(build_business_context(contract, SCHEMA).understanding_status, "resolved")
                batch = SignalBatch.model_validate_json(json.dumps(saved["signal_batch"]))
                package = PromptPackage.model_validate_json(json.dumps(saved["prompt_package"]))
                self.assertEqual(len(batch.signals), count)
                self.assertEqual(validate_response(result.explanation, package).status, "validated")
                self.assertEqual(result.sql, execution["sql"])
                self.assertEqual(result.rows, execution["rows"])
                for signal in result.business_signals:
                    self.assertEqual(signal.signal_type, kind)
                    self.assertEqual(signal.status, "computed")
                    self.assertIn(contract.result_id, {item.result_id for item in signal.evidence_summary})
                    for value in signal.computed_value.values():
                        self.assertEqual(value.numeric_quality.source_fidelity, "approximate")
                # The original prompt gate carries projected facts, not SQL.
                self.assertNotIn(result.sql, package.user_message)
                self.assertEqual(service.workflow._deliveries, {})

    def test_original_csv_drives_visible_table_and_existing_calculated_values(self):
        service = self.service()
        with (BASE_DIR / "data/databases/askdata_mock/orders_current.csv").open(encoding="utf-8-sig", newline="") as handle:
            paid = [row for row in csv.DictReader(handle) if row["status"] == "已支付"
                    and "2026-08-01" <= row["order_date"] < "2026-09-01"]
        expected_total = sum((Decimal(row["paid_amount"]) for row in paid), Decimal(0))
        s1, s2, s3 = [self.submit(service, scenario) for scenario in SCENARIOS]
        self.assertAlmostEqual(sum(row["sales_amount"] for row in s1.rows), float(expected_total), places=6)
        self.assertEqual(s1.business_signals[1].computed_value["attainment_rate"].value, "2.111902100000")
        self.assertEqual(s2.business_signals[1].computed_value["change_rate"].value, "-0.282948395517")
        self.assertEqual(len(s3.rows), len({row["product_id"] for row in paid}))
        # All products remain visible; descending table order is not a new
        # rank Signal or a top-N subset in the contribution denominator.
        self.assertEqual(s3.rows[0]["product_id"], 102)
        self.assertAlmostEqual(sum(row["sales_amount"] for row in s3.rows), float(expected_total), places=6)
        top = next(signal for signal in s3.business_signals if signal.business_key.components[0].normalized_value == 102)
        self.assertEqual(top.computed_value["contribution_rate"].value, "0.110198778230")
        self.assertTrue(any(notice.code == "PARTITION_WITHIN_RELATIVE_TOLERANCE" for notice in s3.explanation.notice_blocks))

    def test_failure_modes_preserve_real_sql_table_and_independent_signal_state(self):
        baseline = self.submit(self.service())
        for failure, status, code, signal_count in (
            ("no-signal", "unavailable", "NO_SIGNAL_BATCH", 0),
            ("llm", "failed", "LLM_CALL_FAILED", 4),
            ("validator", "validation_failed", "RESPONSE_VALIDATION_FAILED", 4),
        ):
            with self.subTest(failure=failure):
                service = self.service(failure)
                result = self.submit(service)
                self.assertEqual(result.status, "completed")
                self.assertEqual(result.sql, baseline.sql)
                self.assertEqual(result.columns, baseline.columns)
                self.assertEqual(result.rows, baseline.rows)
                self.assertEqual(len(result.business_signals), signal_count)
                self.assertEqual(result.explanation.generation_status, status)
                self.assertEqual(result.explanation.diagnostic_codes, (code,))
                self.assertNotIn("DEMO_INVALID_RESPONSE", result.analysis)
                self.assertIn(failure, result.interpretation.time_range)
                if failure == "validator":
                    saved = self.state(service, result)
                    package = PromptPackage.model_validate_json(json.dumps(saved["prompt_package"]))
                    invalid = service.workflow.response_generator.finalize(package)
                    self.assertEqual(invalid.generation_status, "generated")
                    self.assertEqual(validate_response(invalid, package).status, "validation_failed")

    def test_delivery_from_another_execution_is_rejected_without_losing_table(self):
        service = self.service()
        original = service.workflow.signal_source

        def stale(request):
            delivery = original(request)
            return SignalDelivery(request=request.model_copy(update={"execution_digest": "stale-execution"}), signals=delivery.signals)

        service.workflow.signal_source = stale
        result = self.submit(service)
        self.assertEqual(len(result.rows), 4)
        self.assertEqual(result.explanation.diagnostic_codes, ("INVALID_SIGNAL_DELIVERY",))
        self.assertEqual(result.business_signals, [])

    def test_http_auth_query_uses_existing_frontend_response_contract(self):
        service = self.service()
        with patch.object(routes, "service", service), TestClient(app) as client:
            self.assertEqual(client.post("/api/query", json={"query": SCENARIOS[0].question}).status_code, 401)
            login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
            self.assertEqual(login.status_code, 200)
            headers = {"Authorization": "Bearer " + login.json()["access_token"]}
            response = client.post("/api/query", headers=headers, json={"query": SCENARIOS[0].question, "session_id": "phase5-http"})
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertEqual(result["explanation"]["generation_status"], "generated")
            self.assertEqual(len(result["business_signals"]), 4)
            self.assertEqual(len(result["rows"]), 4)
            self.assertEqual(result["analysis"], result["explanation"]["text"])
            self.assertIsNone(result["retrieval"])
            self.assertIsNone(result["schema_graph"])
            self.assertEqual(result["workflow_mode"], "phase5_demo_catalog")
            self.assertIn("fixture", result["interpretation"]["time_range"])

    def test_history_permission_is_enforced_for_fixed_demo_sql(self):
        result = self.submit(self.service(), SCENARIOS[1], user="demo_current_sales")
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.rows, [])
        self.assertEqual(result.business_signals, [])
        self.assertEqual(result.explanation.diagnostic_codes, ("EXECUTION_UNAVAILABLE",))

    def test_fixed_catalog_rejects_other_questions(self):
        service = self.service()
        result = service.submit("查询所有客户", "unknown-demo", user_id="demo_admin")
        self.assertEqual(result.status, "failed")
        self.assertIn("三个固定问题", result.analysis)
        self.assertEqual(service.workflow._deliveries, {})

    def test_duplicate_target_source_keys_are_not_hidden_by_sql_grouping(self):
        service = self.service()
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "askdata_mock"
            shutil.copytree(BASE_DIR / "data/databases/askdata_mock", folder)
            path = folder / "sales_targets.csv"
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows.append(next(row for row in rows if row["target_month"] == "2026-08"))
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            service.workflow.database_engine.database_root = Path(temporary)
            result = self.submit(service)
        self.assertEqual(len(result.rows), 4)
        batch = SignalBatch.model_validate_json(json.dumps(self.state(service, result)["signal_batch"]))
        self.assertTrue(batch.signals)
        self.assertTrue(all(signal.status == "incompatible_context" for signal in batch.signals))
        self.assertEqual(result.business_signals, [])
        self.assertEqual(result.explanation.diagnostic_codes, ("NO_DISPLAYABLE_FACTS",))

    def test_live_transport_uses_original_model_client_and_cannot_fall_back_to_fixture(self):
        service = create_demo_service(llm="live", config=Settings(api_key=""))
        with patch.object(ModelClient, "chat", side_effect=RuntimeError("transport unavailable")) as call:
            result = self.submit(service)
        call.assert_called_once()
        self.assertEqual(result.explanation.generation_status, "failed")
        self.assertEqual(len(result.rows), 4)
        self.assertNotIn("fixture", result.result_title)


if __name__ == "__main__":
    unittest.main()
