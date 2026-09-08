"""Deterministic guards bind controlled explanations to their current facts.

The real S1/S2/S3 producers finish in fixture setup. Tests include responses
which pass their own output contract but describe another input snapshot, so
validation must compare with the actual package rather than trust model shape.
"""

import ast
from copy import deepcopy
import inspect
import json
import unittest
from unittest.mock import Mock, patch

from pydantic import ValidationError

from app.querying import response_generator
from app.querying.explanation import validator
from app.querying.explanation.prompt_builder import PromptPackage, RequestOptions
from app.querying.explanation.response_adapter import (
    render_explanation_response, unavailable_explanation,
)
from app.querying.explanation.response_models import (
    ExplanationResponse, render_block_text, render_response_text,
)
from app.querying.explanation.validator import ValidationResult, validate_response
from app.querying.response_generator import ResponseGenerator
from test_explanation_context import all_keys, no_upstream_calls
from test_response_generator_migration import candidate_for, client_for, package_for
from test_sales_change import s2_inputs
from test_signal_engine import s1, s2, s3
from test_target_attainment import s1_inputs


def replace_path(value, path, replacement):
    """Deliberately bypass model validation to exercise the public guard."""
    if not path:
        return replacement
    first, *rest = path
    if isinstance(first, int):
        items = list(value)
        items[first] = replace_path(items[first], rest, replacement)
        return tuple(items)
    return value.model_copy(update={first: replace_path(getattr(value, first), rest, replacement)})


def self_consistent_response(response):
    """Re-render supplied facts, proving a negative case is locally valid."""
    citations = {item.ref: item for item in response.citations}
    blocks = tuple(block.model_copy(update={
        "text": render_block_text(block.fact, tuple(citations[ref] for ref in block.citation_refs),
                                  block.wording, response.locale),
    }) for block in response.blocks)
    supplied = response.model_copy(update={
        "blocks": blocks,
        "text": render_response_text(blocks, response.notice_blocks, response.omissions, response.locale),
    })
    return ExplanationResponse.model_validate_json(supplied.model_dump_json())


class ResponseValidatorTests(unittest.TestCase):
    @staticmethod
    def response(package):
        return render_explanation_response(package, candidate_for(package))

    def assert_rejected(self, response, package):
        result = validate_response(response, package)
        self.assertIsInstance(result, ValidationResult)
        self.assertEqual(result.status, "validation_failed")
        self.assertIsNone(result.validated_response)
        self.assertTrue(result.issues)
        return result

    def assert_validated(self, response, package):
        result = validate_response(response, package)
        self.assertEqual(result.status, "validated")
        self.assertEqual(result.issues, ())
        self.assertEqual(result.validated_response, response)
        self.assertIsNot(result.validated_response, response)
        return result

    def test_normal_real_s1_s2_s3_responses_preserve_values_and_references(self):
        for factory in (s1, s2, s3):
            with self.subTest(signal=factory.__name__):
                package = package_for(factory())
                response = self.response(package)
                checked = self.assert_validated(response, package).validated_response
                self.assertEqual(tuple(block.fact for block in checked.blocks), package.fact_blocks)
                self.assertEqual(checked.citations, package.reference_blocks)

    def test_locally_valid_numeric_changes_are_rejected_against_original_facts(self):
        package = package_for(s1())
        response = self.response(package)
        for value in ("999", "50%", "0.5000", "0"):
            with self.subTest(value=value):
                changed = replace_path(response, ("blocks", 0, "fact", "facts", "outputs", 0, "value"), value)
                changed = self_consistent_response(changed)
                self.assert_rejected(changed, package)

    def test_locally_valid_unit_change_is_rejected_without_unit_conversion(self):
        package = package_for(s1())
        response = self.response(package)
        for unit in ("percent", "USD", "ten_thousand_CNY"):
            with self.subTest(unit=unit):
                changed = replace_path(response, ("blocks", 0, "fact", "facts", "outputs", 0, "unit_id"), unit)
                self.assert_rejected(self_consistent_response(changed), package)

    def test_formula_identity_or_version_changes_cannot_reuse_an_output(self):
        package = package_for(s2())
        response = self.response(package)
        for field, value in (("formula_id", "attainment_rate"), ("formula_version", "2"),
                             ("signal_index", 99)):
            with self.subTest(field=field):
                changed = replace_path(response, ("blocks", 0, "fact", "facts", "outputs", 0, "ref", field), value)
                self.assert_rejected(changed, package)

    def test_wrong_signal_index_is_rejected_at_block_and_output_scope(self):
        package = package_for()
        response = self.response(package)
        for path in (("blocks", 0, "ref", "signal_index"),
                     ("blocks", 0, "fact", "ref", "signal_index"),
                     ("blocks", 0, "fact", "facts", "outputs", 0, "ref", "signal_index")):
            with self.subTest(path=path):
                self.assert_rejected(replace_path(response, path, 999), package)

    def test_nonexistent_evidence_refs_and_missing_citations_are_rejected(self):
        package = package_for(s1())
        response = self.response(package)
        for path in (("citations", 0, "ref", "evidence_id"),
                     ("blocks", 0, "citation_refs", 0, "evidence_id"),
                     ("blocks", 0, "fact", "facts", "evidence_refs", 0, "evidence_id"),
                     ("blocks", 0, "fact", "facts", "outputs", 0, "input_evidence_refs", 0, "evidence_id")):
            with self.subTest(path=path):
                self.assert_rejected(replace_path(response, path, "NONEXISTENT_EVIDENCE"), package)
        self.assert_rejected(response.model_copy(update={"citations": response.citations[:-1]}), package)

    def test_cross_signal_citations_cannot_borrow_an_existing_reference(self):
        package = package_for()
        response = self.response(package)
        foreign_ref = response.blocks[1].citation_refs[0]
        self.assertNotEqual(foreign_ref.signal_index, response.blocks[0].ref.signal_index)
        for path in (("blocks", 0, "citation_refs", 0),
                     ("blocks", 0, "fact", "facts", "evidence_refs", 0),
                     ("blocks", 0, "fact", "facts", "outputs", 0, "input_evidence_refs", 0)):
            with self.subTest(path=path):
                self.assert_rejected(replace_path(response, path, foreign_ref), package)

    def test_s3_shared_total_identity_is_still_scoped_to_each_signal(self):
        package = package_for(s3())
        response = self.response(package)
        totals = tuple(item for item in response.citations if item.context_role == "total")
        self.assertEqual(totals[0].ref.evidence_id, totals[1].ref.evidence_id)
        self.assertNotEqual(totals[0].ref.signal_index, totals[1].ref.signal_index)
        self.assert_validated(response, package)
        self.assert_rejected(replace_path(response, ("blocks", 0, "citation_refs", 1), totals[1].ref), package)

    def test_locally_valid_evidence_observation_or_location_change_is_rejected(self):
        package = package_for(s1())
        response = self.response(package)
        changes = (
            (("observed_value", "value"), "999"), (("result_id",), "OTHER_RESULT"),
            (("context_digest",), "OTHER_DIGEST"), (("column_id",), "OTHER_COLUMN"),
            (("row_index",), 123), (("ordinal",), 123), (("unit_scale",), "10000"),
        )
        for suffix, value in changes:
            with self.subTest(suffix=suffix):
                changed = replace_path(response, ("citations", 0, *suffix), value)
                self.assert_rejected(self_consistent_response(changed), package)

    def test_locally_valid_policy_identity_change_is_rejected(self):
        package = package_for(s1())
        response = self.response(package)
        for field in ("policy_id", "policy_digest"):
            with self.subTest(field=field):
                changed = replace_path(response, ("blocks", 0, "fact", "facts", field), "OTHER_POLICY")
                self.assert_rejected(self_consistent_response(changed), package)

    def test_old_valid_response_cannot_be_reused_for_changed_package(self):
        original = package_for(s1())
        current = package_for(s1(s1_inputs(actual=[["华东", "120"]])))
        response = self.response(original)
        self.assert_validated(response, original)
        self.assert_rejected(response, current)
        self.assert_validated(self.response(current), current)

    def test_undefined_keeps_a_computed_sibling_without_inventing_a_rate(self):
        package = package_for(s2(s2_inputs(baseline=[["华东", "0"]])))
        response = self.response(package)
        checked = self.assert_validated(response, package).validated_response
        outputs = checked.blocks[0].fact.facts.outputs
        self.assertEqual((outputs[0].status, outputs[0].value), ("computed", "150.00"))
        self.assertEqual((outputs[1].status, outputs[1].value), ("undefined", None))
        self.assertEqual(outputs[1].reason_code, "ZERO_BASELINE")

    def test_undefined_changed_to_locally_valid_computed_zero_is_rejected(self):
        package = package_for(s2(s2_inputs(baseline=[["华东", "0"]])))
        response = self.response(package)
        for value in ("0", "0.5", "-0.5", "1"):
            with self.subTest(value=value):
                changed = replace_path(response, ("blocks", 0, "fact", "facts", "outputs", 1, "status"), "computed")
                changed = replace_path(changed, ("blocks", 0, "fact", "facts", "outputs", 1, "value"), value)
                changed = replace_path(changed, ("blocks", 0, "fact", "facts", "outputs", 1, "reason_code"), None)
                changed = replace_path(changed, ("blocks", 0, "fact", "status"), "computed")
                self.assert_rejected(self_consistent_response(changed), package)

    def test_free_business_claims_cannot_replace_undefined_text(self):
        package = package_for(s2(s2_inputs(baseline=[["华东", "0"]])))
        response = self.response(package)
        for text in ("变化率为0", "销售增长", "销售下降", "目标已完成", "需求提升导致增长"):
            with self.subTest(text=text):
                self.assert_rejected(replace_path(response, ("blocks", 0, "text"), text), package)
                self.assert_rejected(response.model_copy(update={"text": text}), package)

    def test_unsupported_expression_variants_or_wording_are_rejected(self):
        package = package_for(s1())
        response = self.response(package)
        for field, value in (("expression_variant", "invented_business_conclusion_v1"),
                             ("expression_variant", "sales_change_summary_v1"),
                             ("wording", "free form recommendation")):
            with self.subTest(field=field, value=value):
                self.assert_rejected(replace_path(response, ("blocks", 0, field), value), package)

    def test_unsafe_extra_fact_fields_and_arbitrary_block_types_are_rejected(self):
        package = package_for(s1())
        response = self.response(package)
        additions = (
            response.model_copy(update={"recommendation": "SECRET_RECOMMENDATION"}),
            replace_path(response, ("blocks", 0), response.blocks[0].model_copy(update={"reason": "SECRET_REASON"})),
            response.model_copy(update={"blocks": ({"type": "free_business_conclusion", "text": "SECRET_FACT"},)}),
        )
        for changed in additions:
            with self.subTest(changed_type=type(changed.blocks[0]).__name__):
                result = self.assert_rejected(changed, package)
                self.assertNotIn("SECRET_", result.model_dump_json())

    def test_validated_response_is_detached_and_inputs_are_not_modified(self):
        package = package_for()
        response = self.response(package)
        before = deepcopy(package), deepcopy(response)
        result = self.assert_validated(response, package)
        self.assertEqual((package, response), before)
        output = result.validated_response
        self.assertIsNot(output.blocks, response.blocks)
        self.assertIsNot(output.blocks[0], response.blocks[0])
        self.assertIsNot(output.blocks[0].fact, package.fact_blocks[0])
        self.assertIsNot(output.citations[0], response.citations[0])
        with self.assertRaises(ValidationError):
            result.status = "validation_failed"

    def test_rejected_response_and_package_are_not_mutated(self):
        package = package_for(s1())
        response = self_consistent_response(replace_path(
            self.response(package), ("blocks", 0, "fact", "facts", "outputs", 0, "value"), "999"))
        before = package.model_dump_json(), response.model_dump_json()
        self.assert_rejected(response, package)
        self.assertEqual((package.model_dump_json(), response.model_dump_json()), before)

    def test_validation_result_and_validated_response_json_roundtrip(self):
        package = package_for()
        response = self.response(package)
        result = validate_response(response, package)
        restored = ValidationResult.model_validate_json(result.model_dump_json())
        self.assertEqual(restored, result)
        self.assertEqual(ExplanationResponse.model_validate_json(
            restored.validated_response.model_dump_json()), response)
        reloaded_package = PromptPackage.model_validate_json(package.model_dump_json())
        self.assertEqual(validate_response(restored.validated_response, reloaded_package), result)

    def test_validation_failure_json_roundtrip_and_status_invariants(self):
        package = package_for(s1())
        response = self.response(package)
        result = self.assert_rejected(response.model_copy(update={"text": "SECRET_WRONG_TEXT"}), package)
        self.assertEqual(ValidationResult.model_validate_json(result.model_dump_json()), result)
        self.assertNotIn("SECRET_WRONG_TEXT", result.model_dump_json())
        raw = json.loads(result.model_dump_json())
        raw["validated_response"] = json.loads(response.model_dump_json())
        with self.assertRaises(ValidationError):
            ValidationResult.model_validate_json(json.dumps(raw))

    def test_deterministic_a_to_a_and_a_to_b_to_a_success_and_failure(self):
        a, b = package_for(s1()), package_for(s2())
        response = self.response(a)
        first = validate_response(response, a).model_dump_json()
        rejected = validate_response(response, b).model_dump_json()
        self.assertEqual(validate_response(response, a).model_dump_json(), first)
        self.assertEqual(validate_response(response, b).model_dump_json(), rejected)
        self.assertEqual(validate_response(response, a).model_dump_json(), first)

    def test_partial_presentation_and_hidden_audit_notices_remain_bound(self):
        signals = [*s1(), *s1(s1_inputs(actual=[["华东", None]])), *s2()]
        package = package_for(signals, RequestOptions(display_limit=1))
        response = self.response(package)
        self.assert_validated(response, package)
        self.assertTrue(response.omissions)
        self.assertTrue(response.notice_blocks)
        self.assert_rejected(response.model_copy(update={"omissions": ()}), package)
        self.assert_rejected(response.model_copy(update={"notice_blocks": ()}), package)
        other_page = package_for(signals, RequestOptions(display_offset=1, display_limit=1))
        self.assert_rejected(response, other_page)

    def test_non_generated_valid_states_validate_without_claiming_generation(self):
        package = package_for(s1())
        for status, code in (("failed", "LLM_CALL_FAILED"), ("unavailable", "NO_PROMPT_PACKAGE"),
                             ("validation_failed", "RESPONSE_VALIDATION_FAILED")):
            with self.subTest(status=status, code=code):
                response = unavailable_explanation(code, generation_status=status, package=package)
                checked = self.assert_validated(response, package).validated_response
                self.assertEqual(checked.generation_status, status)
                self.assertEqual(checked.blocks, ())
        for signals in ([], s1(s1_inputs(actual=[["华东", None]]))):
            empty = package_for(signals)
            response = unavailable_explanation("NO_DISPLAYABLE_FACTS", generation_status="not_requested", package=empty)
            self.assert_validated(response, empty)

    def test_wrong_types_missing_fields_and_nested_invalid_models_fail_closed(self):
        package = package_for(s1())
        response = self.response(package)
        for value in (None, "text", {}, response.model_dump(), ExplanationResponse.model_construct(),
                      response.model_copy(update={"blocks": None}),
                      replace_path(response, ("blocks", 0, "fact"), None)):
            with self.subTest(response_type=type(value).__name__):
                self.assert_rejected(value, package)
        for value in (None, "text", {}, package.model_dump(), PromptPackage.model_construct(),
                      package.model_copy(update={"fact_blocks": None}),
                      package.model_copy(update={"system_message": "SECRET_INSTRUCTION"})):
            with self.subTest(package_type=type(value).__name__):
                result = self.assert_rejected(response, value)
                self.assertNotIn("SECRET_INSTRUCTION", result.model_dump_json())

    def test_guard_never_calls_upstream_business_logic_or_a_model(self):
        package = package_for()
        response = self.response(package)
        with no_upstream_calls():
            self.assert_validated(response, package)
            self.assert_rejected(response.model_copy(update={"text": "invented"}), package)

    def test_guard_has_no_calculator_llm_acquisition_clock_or_identity_dependency(self):
        tree = ast.parse(inspect.getsource(validator))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
        self.assertFalse(names & {"SqlExecution", "BusinessContext", "ResultContract", "SignalBatch", "Decimal", "float", "ModelClient"})
        self.assertFalse(attributes & {"rows", "columns", "execute", "connect", "chat", "chat_json", "read_numeric_value",
                                       "compute_target_attainment", "compute_sales_change", "compute_product_contribution",
                                       "check_context_compatibility", "align_context_keys", "uuid4", "now", "time"})
        self.assertFalse(any(part in imported.split(".") for imported in imports
                             for part in ("model_client", "random", "uuid", "time", "datetime", "sqlalchemy", "duckdb")))

    def test_response_generator_routes_success_through_the_new_validator(self):
        package = package_for()
        client = client_for(package)
        with patch.object(response_generator, "validate_response", wraps=validate_response) as guard:
            response = ResponseGenerator(client).generate_from_prompt_package(package)
        self.assertEqual(response.generation_status, "generated")
        self.assertEqual(guard.call_count, 1)
        self.assertEqual(guard.call_args.args[1], package)
        self.assertEqual(client.chat.call_count, 1)
        self.assertEqual(validate_response(response, package).status, "validated")

    def test_generator_rejects_raw_inventions_as_validation_failed_without_legacy_retry(self):
        package = package_for(s1())
        for field, value in (("value", "999"), ("unit", "percent"), ("text", "SECRET_FREE_CONCLUSION"),
                             ("expression_variant", "unsupported_business_claim_v1"), ("signal_index", 999)):
            with self.subTest(field=field):
                candidate = candidate_for(package)
                candidate["blocks"][0][field] = value
                client = client_for(package, payload=candidate)
                response = ResponseGenerator(client).generate_from_prompt_package(package)
                self.assertEqual(response.generation_status, "validation_failed")
                self.assertEqual(response.diagnostic_codes, ("RESPONSE_VALIDATION_FAILED",))
                self.assertEqual(response.blocks, ())
                self.assertEqual(response.citations, ())
                self.assertNotIn("SECRET_", response.model_dump_json())
                self.assertEqual(client.chat.call_count, 1)
                client.chat_json.assert_not_called()

    def test_generator_blocks_valid_but_wrong_package_response_from_rendering_boundary(self):
        package = package_for(s1())
        other = package_for(s1(s1_inputs(actual=[["华东", "120"]])))
        wrong = self.response(other)
        with patch.object(response_generator, "render_explanation_response", return_value=wrong):
            response = ResponseGenerator(client_for(package)).generate_from_prompt_package(package)
        self.assertEqual(response.generation_status, "validation_failed")
        self.assertEqual(response.diagnostic_codes, ("RESPONSE_VALIDATION_FAILED",))
        self.assertEqual(response.blocks, ())

    def test_generator_llm_transport_failure_remains_distinct_from_validation_failure(self):
        package = package_for(s1())
        client = client_for(package, error=RuntimeError("SECRET_LLM_TRANSPORT"))
        response = ResponseGenerator(client).generate_from_prompt_package(package)
        self.assertEqual(response.generation_status, "failed")
        self.assertEqual(response.diagnostic_codes, ("LLM_CALL_FAILED",))
        self.assertNotIn("SECRET_LLM_TRANSPORT", response.model_dump_json())

    def test_deep_raw_json_is_validation_failed_and_preserves_graph_table(self):
        payload = "[" * 2000 + "0" + "]" * 2000
        package = package_for(s1())
        client = client_for(package, payload=payload)
        response = ResponseGenerator(client).generate_from_prompt_package(package)
        self.assertEqual(response.generation_status, "validation_failed")
        self.assertEqual(response.diagnostic_codes, ("RESPONSE_VALIDATION_FAILED",))
        self.assertEqual(response.blocks, ())
        self.assertEqual(response.citations, ())
        self.assertEqual(client.chat.call_count, 1)
        client.chat_json.assert_not_called()

        from test_query_graph_explanation_migration import QueryGraphExplanationMigrationTests
        fixture = QueryGraphExplanationMigrationTests()
        workflow, model = fixture.workflow(fixture.source_for(s1()))
        model.chat.side_effect = None
        model.chat.return_value = payload
        result = fixture.invoke(workflow)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.rows, fixture.execution_for()["rows"])
        self.assertEqual(result.explanation.generation_status, "validation_failed")
        self.assertEqual(result.explanation.diagnostic_codes, ("RESPONSE_VALIDATION_FAILED",))

    def test_graph_rechecks_foreign_response_and_keeps_table_without_history_fallback(self):
        from test_query_graph_explanation_migration import QueryGraphExplanationMigrationTests
        fixture = QueryGraphExplanationMigrationTests()
        signals = s1()
        workflow, client = fixture.workflow(fixture.source_for(signals))
        other = package_for(s1(s1_inputs(actual=[["华东", "120"]])))
        workflow.response_generator.finalize = Mock(return_value=self.response(other))
        state = fixture.state()
        before = deepcopy(state)
        result = fixture.invoke(workflow, state)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.rows, fixture.execution_for()["rows"])
        self.assertEqual(result.sql, fixture.execution_for()["sql"])
        self.assertEqual(result.explanation.generation_status, "validation_failed")
        self.assertEqual(result.explanation.diagnostic_codes, ("RESPONSE_VALIDATION_FAILED",))
        self.assertEqual(result.explanation.blocks, ())
        self.assertNotIn("SECRET_", result.analysis)
        self.assertEqual(state, before)
        client.chat.assert_not_called()

    def test_graph_raw_model_hallucination_keeps_table_and_cleans_explanation_state(self):
        from test_query_graph_explanation_migration import QueryGraphExplanationMigrationTests
        fixture = QueryGraphExplanationMigrationTests()
        workflow, client = fixture.workflow(fixture.source_for(s1()))
        client.chat.side_effect = None
        client.chat.return_value = '{"blocks":[],"text":"SECRET_HALLUCINATION 999"}'
        result = fixture.invoke(workflow)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.rows, fixture.execution_for()["rows"])
        self.assertEqual(result.explanation.generation_status, "validation_failed")
        self.assertEqual(result.explanation.citations, ())
        self.assertNotIn("SECRET_", result.analysis)
        saved = fixture.checkpoint(workflow)
        self.assertEqual(saved["explanation_response"], result.explanation.model_dump(mode="json"))
        self.assertFalse(all_keys(json.loads(client.chat.call_args.args[1])) & {
            "sql", "rows", "business_context", "result_contract", "analysis_context",
        })


if __name__ == "__main__":
    unittest.main()
