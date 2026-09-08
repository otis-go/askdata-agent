"""Deterministic outer alignment of explicitly selected, already qualified keys.

The receipt binds the complete Policy, selections, declarations and Contexts
checked by Compatibility, plus all normalized result semantics. The entry gate
compares those content bindings before key extraction. Digests detect stale
reuse, not malicious forgery or issuer authenticity.
No Compatibility rules, metric decoding, business formulas or acquisition run.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from ..result_contract import ColumnMetadata
from ..result_understanding.models import BusinessContext
from .alignment_binding import bind_alignment_result
from .compatibility import context_digest
from .receipt_binding import receipt_binding_matches
from .models import (
    AlignmentPair, AlignmentResult, BusinessKey, BusinessKeyComponent,
    ContextCompatibility, ContextRole, DuplicateKey, Issue, SignalInput,
)
from .policies import (
    KeyRule, ProductContributionPolicy, SalesChangePolicy, TargetAttainmentPolicy,
)


_RANK = {"aligned": 0, "insufficient_evidence": 1, "incompatible_context": 2, "unsupported": 3}
_INTEGER_BITS = {
    "TINYINT": (8, True), "SMALLINT": (16, True), "INTEGER": (32, True),
    "BIGINT": (64, True), "HUGEINT": (128, True),
    "UTINYINT": (8, False), "USMALLINT": (16, False), "UINTEGER": (32, False),
    "UBIGINT": (64, False), "UHUGEINT": (128, False),
}


def _token(key: BusinessKey, *, raw: bool = False) -> tuple:
    return tuple((item.domain_id, item.component_id, item.value_type,
                  item.raw_value if raw else item.normalized_value) for item in key.components)


@dataclass
class _Row:
    row_index: int
    key: BusinessKey


@dataclass
class _Index:
    buckets: dict[tuple, list[_Row]] = field(default_factory=dict)
    complete: bool = True


def _representative(rows: list[_Row]) -> BusinessKey:
    # This labels a bucket using an actual observation; it does not choose an
    # ambiguous row for downstream use. All duplicate row indexes are retained.
    return min(rows, key=lambda item: _token(item.key, raw=True)).key


class _Alignment:
    def __init__(self, inputs: dict, receipt: ContextCompatibility, policy: object):
        self.inputs, self.receipt, self.policy = inputs, receipt, policy
        self.roles = list(policy.required_roles)
        self.status = "aligned"
        self.issues: list[Issue] = []
        self.pairs: list[AlignmentPair] = []
        self.missing_left: list[BusinessKey] = []
        self.missing_right: list[BusinessKey] = []
        self.duplicates: list[DuplicateKey] = []
        self.broadcastable = False

    def add(self, status: str, code: str, role: str | None, path: str, message: str,
            key: BusinessKey | None = None) -> None:
        if _RANK[status] > _RANK[self.status]:
            self.status = status
        self.issues.append(Issue(
            code=code, stage="alignment", context_role=role,
            result_id=self.inputs[role].context.result_id if role is not None else None,
            key=key, evidence_paths=[path],
            severity="warning" if status == "insufficient_evidence" else "error", message=message,
        ))

    def receipt_matches(self) -> bool:
        receipt = self.receipt
        if receipt.status != "compatible":
            self.issues.extend(deepcopy(receipt.issues))
            self.add(receipt.status, "COMPATIBILITY_NOT_APPROVED", None, "compatibility.status",
                     "Alignment requires an approved Compatibility result.")
            return False
        if receipt.binding is None:
            self.add("incompatible_context", "COMPATIBILITY_BINDING_MISSING", None, "compatibility.binding",
                     "An unbound receipt cannot authorize Alignment; obtain a new Compatibility result.")
            return False
        if receipt.context_roles != self.roles:
            self.add("incompatible_context", "COMPATIBILITY_ROLE_MISMATCH", None, "compatibility.context_roles",
                     "Receipt roles differ from the supplied role pair.")
        if receipt.result_ids != {role: self.inputs[role].context.result_id for role in self.roles}:
            self.add("incompatible_context", "COMPATIBILITY_RESULT_MISMATCH", None, "compatibility.result_ids",
                     "Receipt execution identities differ from the current inputs.")
        if set(receipt.input_digests) - set(self.roles):
            self.add("incompatible_context", "COMPATIBILITY_DIGEST_MISMATCH", None, "compatibility.input_digests",
                     "Receipt digests contain an unexpected role.")
        for role in self.roles:
            digest = receipt.input_digests.get(role)
            if not digest or not digest.strip():
                self.add("insufficient_evidence", "COMPATIBILITY_DIGEST_UNKNOWN", role, "compatibility.input_digests",
                         "A Context content binding is required before reading keys.")
            elif digest != context_digest(self.inputs[role].context):
                self.add("incompatible_context", "COMPATIBILITY_DIGEST_MISMATCH", role, "compatibility.input_digests",
                         "Context content changed since the supplied Compatibility result.")
        domains = list(dict.fromkeys(rule.domain_id for rule in self.policy.key_rules))
        if receipt.key_domains != domains:
            self.add("incompatible_context", "COMPATIBILITY_KEY_DOMAIN_MISMATCH", None, "compatibility.key_domains",
                     "Receipt key domains differ from the supplied Policy.")
        # Identity references only: no source, aggregation, time or filter
        # eligibility is recomputed. These are not a full Policy digest.
        expected = [(rule.context_role, rule.metric_id, rule.mapping_id, "matched") for rule in self.policy.metric_rules]
        actual = [(ref.context_role, ref.metric_id, ref.mapping_id, ref.match_status) for ref in receipt.normalized_metric_refs]
        if actual != expected:
            self.add("incompatible_context", "COMPATIBILITY_POLICY_REFERENCE_MISMATCH", None, "compatibility.normalized_metric_refs",
                     "Receipt mapping identities differ from the supplied Policy references.")
        declarations = {
            (item.declaration_id, item.declaration_type, item.result_id, item.context_digest)
            for supplied in self.inputs.values() for item in supplied.declarations
        }
        if any((ref.declaration_id, ref.declaration_type, ref.result_id, ref.context_digest) not in declarations
               for ref in receipt.declarations_used):
            self.add("incompatible_context", "COMPATIBILITY_DECLARATION_REFERENCE_MISMATCH", None, "compatibility.declarations_used",
                     "A declaration reference used by Compatibility is absent from the inputs.")
        if not receipt_binding_matches(receipt, self.inputs, self.policy):
            self.add("incompatible_context", "COMPATIBILITY_BINDING_MISMATCH", None, "compatibility.binding",
                     "The complete input snapshot or receipt semantics differ from the checked content.")
        return self.status == "aligned"

    def structure(self, role: str) -> dict[str, ColumnMetadata] | None:
        execution = self.inputs[role].context.execution
        if execution.rows is not None:
            if type(execution.rows) is not list or any(type(row) is not list for row in execution.rows):
                raise TypeError("rows must be positional lists")
        if execution.columns is None:
            self.add("insufficient_evidence", "KEY_METADATA_UNKNOWN", role, "execution.columns",
                     "Column identities and positions must be known to extract keys.")
            return None
        if type(execution.columns) is not list or any(not isinstance(column, ColumnMetadata) for column in execution.columns):
            raise TypeError("columns must contain ColumnMetadata")
        columns = [ColumnMetadata.model_validate(column.model_dump()) for column in execution.columns]
        identities = [column.id for column in columns]
        if len(set(identities)) != len(identities) or [column.ordinal for column in columns] != list(range(len(columns))):
            raise ValueError("column identities and ordinal positions must be unique and consistent")
        if execution.rows is not None and any(len(row) != len(columns) for row in execution.rows):
            raise ValueError("row widths must match column metadata")
        return {column.id: column for column in columns}

    def key_column(self, role: str, rule: KeyRule, column: ColumnMetadata) -> bool:
        path = f"execution.columns[{column.ordinal}]"
        if column.representation_status == "unsupported":
            self.add("unsupported", "KEY_REPRESENTATION_UNSUPPORTED", role, path, "Key representation is unsupported.")
        elif column.representation_status == "lossy":
            self.add("incompatible_context", "KEY_REPRESENTATION_LOSSY", role, path, "Lossy keys cannot establish identity.")
        elif column.dtype is None or column.value_encoding is None or column.representation_status is None:
            self.add("insufficient_evidence", "KEY_METADATA_UNKNOWN", role, path, "Key dtype, encoding and fidelity must be known.")
        elif column.value_encoding != "native_json" or column.dtype not in _INTEGER_BITS.keys() | {"VARCHAR"}:
            self.add("unsupported", "KEY_CODEC_UNSUPPORTED", role, path, "V1 keys require native VARCHAR or integer values.")
        elif (column.dtype == "VARCHAR") != (rule.value_type == "string"):
            self.add("incompatible_context", "KEY_TYPE_MISMATCH", role, path, "Key dtype conflicts with the Policy value type.")
        else:
            return True
        return False

    def extract(self, role: str, columns: dict | None) -> _Index:
        index = _Index()
        supplied = self.inputs[role]
        rules = [rule for rule in self.policy.key_rules if any(source.context_role == role for source in rule.sources)]
        selection = supplied.selection.key_column_ids
        if set(selection) != {rule.component_id for rule in rules} or not rules:
            self.add("incompatible_context", "KEY_SELECTION_MISMATCH", role, "selection.key_column_ids",
                     "Selected key components must cover the Policy role exactly.")
            index.complete = False
            return index
        if len(set(selection.values())) != len(selection):
            raise ValueError("key components must select distinct column identities")
        if columns is None:
            index.complete = False
            return index
        if any(column_id not in columns for column_id in selection.values()):
            raise ValueError("selected key column_id does not exist")
        selected_columns = [columns[selection[rule.component_id]] for rule in rules]
        usable = [self.key_column(role, rule, column) for rule, column in zip(rules, selected_columns)]
        rows = supplied.context.execution.rows
        if rows is None:
            self.add("insufficient_evidence", "KEY_ROWS_UNKNOWN", role, "execution.rows", "Rows are unknown; no counterpart is inferred missing.")
            index.complete = False
            return index
        if not rows:
            self.add("insufficient_evidence", "NO_KEY_ROWS", role, "execution.rows", "No business keys were observed.")
        if not all(usable):
            index.complete = False
            return index
        mappings = [{entry.raw_value: entry.normalized_value for entry in rule.value_mappings} for rule in rules]
        for row_index, row in enumerate(rows):
            components = []
            for rule, column, mapping in zip(rules, selected_columns, mappings):
                value = row[column.ordinal]
                path = f"execution.rows[{row_index}][{column.ordinal}]"
                if value is None:
                    self.add("insufficient_evidence", "NULL_KEY", role, path, "SQL NULL does not establish a business key.")
                    continue
                expected = str if rule.value_type == "string" else int
                if type(value) is not expected:
                    self.add("incompatible_context", "KEY_VALUE_TYPE_MISMATCH", role, path, "Key values cannot be coerced between native types.")
                    continue
                if expected is int:
                    bits, signed = _INTEGER_BITS[column.dtype]
                    lower, upper = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if signed else (0, (1 << bits) - 1)
                    if not lower <= value <= upper:
                        self.add("incompatible_context", "KEY_INTEGER_OUT_OF_RANGE", role, path, "Native integer key exceeds its declared physical dtype.")
                        continue
                if rule.normalization == "explicit_mapping" and value not in mapping:
                    self.add("insufficient_evidence", "KEY_MAPPING_UNKNOWN", role, path, "The explicit value map has no entry for this observed key.")
                    continue
                normalized = mapping[value] if rule.normalization == "explicit_mapping" else value
                components.append(BusinessKeyComponent(
                    domain_id=rule.domain_id, component_id=rule.component_id, value_type=rule.value_type,
                    raw_value=value, normalized_value=normalized,
                ))
            if len(components) != len(rules):
                index.complete = False
                continue
            key = BusinessKey(components=components, periods=deepcopy(self.receipt.periods))
            index.buckets.setdefault(_token(key), []).append(_Row(row_index, key))
        self.find_duplicates(role, index)
        return index

    def find_duplicates(self, role: str, index: _Index) -> None:
        for token in sorted(index.buckets):
            rows = index.buckets[token]
            if len(rows) < 2:
                continue
            key = _representative(rows)
            collision = len({_token(row.key, raw=True) for row in rows}) > 1
            duplicate = DuplicateKey(
                context_role=role, key=key, row_indexes=[row.row_index for row in rows],
                raw_keys=[row.key for row in rows], normalization_collision=collision,
            )
            self.duplicates.append(duplicate)
            self.add("incompatible_context", "DUPLICATE_KEY", role, "execution.rows",
                     "Multiple rows have one business key; no row is selected from the bucket.", key)
            if collision:
                self.add("incompatible_context", "NORMALIZATION_COLLISION", role, "execution.rows",
                         "Different raw business keys map to one normalized key in this Context.", key)

    def broadcast(self) -> bool:
        left_role, right_role = self.roles
        left, right = self.policy.grain_rules
        context = self.inputs[right_role].context
        requested = any(rule.grain == "global_aggregate" for rule in (left, right)) or any(
            self.inputs[role].context.grain.query_grain == "global_aggregate" for role in self.roles)
        if not requested:
            return False
        if right_role != "total" or left.grain != "grouped" or right.grain != "global_aggregate" or right.total_broadcast != "allow_global_total":
            self.add("incompatible_context", "BROADCAST_NOT_AUTHORIZED", right_role, "policy.grain_rules",
                     "Only an explicitly authorized global total can be broadcast.")
            return True
        if any({source.context_role for source in rule.sources} != {left_role} for rule in self.policy.key_rules):
            self.add("incompatible_context", "KEY_DOMAIN_ROLE_MISMATCH", None, "policy.key_rules",
                     "Every broadcast key component must belong exactly to the grouped role.")
        if context.grain.status != "resolved" or context.grain.query_grain is None or context.grain.grouping_columns is None:
            self.add("insufficient_evidence", "BROADCAST_GRAIN_UNKNOWN", right_role, "grain", "Global total structure must be known.")
        elif context.grain.query_grain != "global_aggregate" or context.grain.grouping_columns != [] or self.inputs[left_role].context.grain.query_grain == "global_aggregate":
            self.add("incompatible_context", "BROADCAST_GRAIN_MISMATCH", right_role, "grain", "Broadcast requires a global total and grouped counterpart.")
        if self.inputs[right_role].selection.key_column_ids:
            self.add("incompatible_context", "BROADCAST_KEY_SELECTION", right_role, "selection.key_column_ids", "A global total cannot carry selected business-key columns.")
        rows = context.execution.rows
        if rows is None:
            self.add("insufficient_evidence", "KEY_ROWS_UNKNOWN", right_role, "execution.rows", "Broadcast row presence is unknown.")
        elif len(rows) != 1:
            self.add("incompatible_context", "BROADCAST_ROW_COUNT", right_role, "execution.rows", "An authorized global total must contain exactly one row.")
        self.broadcastable = self.status == "aligned"
        return True

    def outer_pairs(self, left: _Index, right: _Index) -> None:
        for token in sorted(left.buckets.keys() | right.buckets.keys()):
            left_rows, right_rows = left.buckets.get(token, []), right.buckets.get(token, [])
            a = left_rows[0] if len(left_rows) == 1 else None
            b = right_rows[0] if len(right_rows) == 1 else None
            key = _representative(left_rows or right_rows)
            if len(left_rows) > 1 or len(right_rows) > 1:
                status = "ambiguous"
            elif a is not None and b is not None:
                status = "matched"
            elif a is None and left.complete:
                status = "missing_left"
                self.missing_left.append(key)
                self.add("insufficient_evidence", "MISSING_LEFT_KEY", self.roles[0], "execution.rows", "The key is absent from the complete observed left key index.", key)
            elif b is None and right.complete:
                status = "missing_right"
                self.missing_right.append(key)
                self.add("insufficient_evidence", "MISSING_RIGHT_KEY", self.roles[1], "execution.rows", "The key is absent from the complete observed right key index.", key)
            else:
                status = "unresolved"
            self.pairs.append(AlignmentPair(
                key=key, left_key=None if a is None else a.key, right_key=None if b is None else b.key,
                left_row_index=None if a is None else a.row_index, right_row_index=None if b is None else b.row_index,
                status=status,
            ))

    def run(self) -> AlignmentResult:
        if self.receipt_matches():
            columns = {role: self.structure(role) for role in self.roles}
            broadcast_requested = self.broadcast()
            if broadcast_requested:
                if self.broadcastable:
                    left = self.extract(self.roles[0], columns[self.roles[0]])
                    for token in sorted(left.buckets):
                        rows = left.buckets[token]
                        row = rows[0] if len(rows) == 1 else None
                        self.pairs.append(AlignmentPair(
                            key=_representative(rows), left_key=None if row is None else row.key,
                            left_row_index=None if row is None else row.row_index, right_row_index=0,
                            status="ambiguous" if row is None else "matched", broadcast=True,
                        ))
            else:
                expected_roles = set(self.roles)
                if any({source.context_role for source in rule.sources} != expected_roles for rule in self.policy.key_rules):
                    self.add("incompatible_context", "KEY_DOMAIN_ROLE_MISMATCH", None, "policy.key_rules",
                             "Every non-broadcast key component must map both roles.")
                else:
                    self.outer_pairs(*(self.extract(role, columns[role]) for role in self.roles))
        issues = sorted(self.issues, key=lambda issue: (
            self.roles.index(issue.context_role) if issue.context_role in self.roles else len(self.roles),
            issue.code, () if issue.key is None else _token(issue.key), tuple(issue.evidence_paths), issue.message,
        ))
        return AlignmentResult(
            status=self.status, operation=self.receipt.operation,
            left_role=self.roles[0], right_role=self.roles[1],
            key_domain=list(dict.fromkeys(rule.domain_id for rule in self.policy.key_rules)),
            pairs=self.pairs, missing_left_keys=self.missing_left, missing_right_keys=self.missing_right,
            duplicate_keys=self.duplicates, issues=issues,
            broadcastable=self.broadcastable, broadcast_role=self.roles[1] if self.broadcastable else None,
        ).model_copy(deep=True)


def align_context_keys(
    inputs: dict[ContextRole, SignalInput],
    compatibility: ContextCompatibility,
    policy: TargetAttainmentPolicy | SalesChangePolicy | ProductContributionPolicy,
) -> AlignmentResult:
    """Align typed keys from the exact inputs/Policy used for Compatibility.

    Non-approved, unbound or mismatched receipts never enter key extraction.
    Complete content bindings are checked without calling Compatibility again. Identity
    mapping copies raw values unchanged; explicit maps have no implicit fallback.
    Invalid call/positional structures raise TypeError or ValueError. Business
    issues use unsupported > incompatible > insufficient > aligned precedence.
    """
    if type(policy) not in (TargetAttainmentPolicy, SalesChangePolicy, ProductContributionPolicy):
        raise TypeError("a concrete Typed Policy is required")
    if not isinstance(compatibility, ContextCompatibility):
        raise TypeError("compatibility must be ContextCompatibility")
    if type(inputs) is not dict or any(not isinstance(value, SignalInput) for value in inputs.values()):
        raise TypeError("inputs must map explicit roles to SignalInput")
    policy = type(policy).model_validate(policy.model_dump())
    if set(inputs) != set(policy.required_roles):
        raise ValueError("input roles must match the Policy role pair exactly")
    if len({rule.component_id for rule in policy.key_rules}) != len(policy.key_rules):
        raise ValueError("selection component names must be unambiguous")
    if any(not isinstance(value.context, BusinessContext) for value in inputs.values()):
        raise TypeError("each SignalInput must contain BusinessContext")
    compatibility = ContextCompatibility.model_validate(compatibility.model_dump())
    result = _Alignment(deepcopy(inputs), deepcopy(compatibility), policy).run()
    return bind_alignment_result(result, compatibility)


__all__ = ["align_context_keys"]
