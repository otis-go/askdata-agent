"""Request-bound delivery of already calculated business Signals.

The workflow asks a configured backend source for existing Signals. This
boundary neither selects metrics nor obtains data or runs calculators. The
execution digest detects accidental reuse of a different execution snapshot;
it is not a signature or proof of authenticity.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..querying.business_signals.batch import inspect_signal
from ..querying.business_signals.models import BusinessSignal


NonEmptyText = Annotated[str, Field(min_length=1)]


class DeliveryModel(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="forbid", frozen=True, validate_default=True,
        revalidate_instances="always", allow_inf_nan=False,
    )


class SignalRequest(DeliveryModel):
    """One invocation's identity, without execution data or semantic inputs."""

    task_id: NonEmptyText
    query: NonEmptyText
    session_id: NonEmptyText
    user_id: NonEmptyText | None = None
    route: Literal["database_query", "data_qa"]
    execution_result_id: NonEmptyText | None = None
    execution_digest: NonEmptyText | None = None

    @model_validator(mode="after")
    def execution_binding_matches_route(self) -> Self:
        if self.route == "database_query":
            if self.execution_result_id is None or self.execution_digest is None:
                raise ValueError("database Signal delivery requires an execution identity and digest")
        elif self.execution_result_id is not None or self.execution_digest is not None:
            raise ValueError("QA Signal delivery does not carry a current execution snapshot")
        return self


class SignalDelivery(DeliveryModel):
    """Signals supplied by the configured backend source for this request."""

    request: SignalRequest
    signals: tuple[BusinessSignal, ...]


class SignalSource(Protocol):
    """Trusted backend lookup/delivery service, not a raw-data calculator."""

    def __call__(self, request: SignalRequest) -> SignalDelivery | None: ...


def _require_json_tree(value: object) -> None:
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise TypeError("execution snapshot object keys must be strings")
        for child in value.values():
            _require_json_tree(child)
    elif type(value) is list:
        for child in value:
            _require_json_tree(child)
    elif value is not None and type(value) not in (str, int, float, bool):
        raise TypeError("execution snapshot must contain only JSON values")


def execution_digest(execution_result: dict) -> str:
    """Hash the full validated execution wire snapshot, without interpreting it."""

    if type(execution_result) is not dict:
        raise TypeError("execution_result must be a JSON object")
    _require_json_tree(execution_result)
    canonical = json.dumps(
        execution_result, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _check_model_tree(value: object, ancestors: frozenset[int] = frozenset()) -> None:
    """Reject undeclared or non-JSON object keys before serialization drops them."""

    if not isinstance(value, (BaseModel, dict, list, tuple)):
        return
    if id(value) in ancestors:
        raise ValueError("Signal delivery cannot contain cyclic containers")
    descendants = ancestors | {id(value)}
    if isinstance(value, BaseModel):
        if (set(value.__dict__) - set(type(value).model_fields)
                or value.__pydantic_extra__):
            raise ValueError("Signal delivery contains undeclared model fields")
        children = value.__dict__.values()
    elif isinstance(value, dict):
        if any(type(key) is not str for key in value):
            raise TypeError("Signal delivery object keys must be strings")
        children = value.values()
    else:
        children = value
    for child in children:
        _check_model_tree(child, descendants)


def resolve_signals(delivery: SignalDelivery, request: SignalRequest) -> list[BusinessSignal]:
    """Validate invocation binding and return detached, strictly revalidated Signals.

    SignalEngine retains responsibility for status and display-reference checks.
    This gate performs structural and execution-reference checks only. It does
    not rejudge Compatibility, interpret periods or evaluate business values.
    """

    if type(request) is not SignalRequest or type(delivery) is not SignalDelivery:
        raise TypeError("Signal delivery requires typed request and delivery objects")
    _check_model_tree(request)
    _check_model_tree(delivery)
    if type(delivery.signals) is not tuple:
        raise TypeError("Signal delivery must retain an ordered tuple of Signals")
    # Check the original objects before JSON conversion can normalize an unsafe
    # model_copy edit. Returned issue codes are left to the existing Engine.
    for signal in delivery.signals:
        inspect_signal(signal)
    current_request = SignalRequest.model_validate_json(request.model_dump_json(warnings="error"))
    detached = SignalDelivery.model_validate_json(delivery.model_dump_json(warnings="error"))
    if detached.request != current_request:
        raise ValueError("Signal delivery belongs to another request or execution snapshot")
    if current_request.route == "database_query":
        for signal in detached.signals:
            if signal.status in ("computed", "undefined") and signal.evidence and not any(
                evidence.result_id == current_request.execution_result_id
                for evidence in signal.evidence
            ):
                raise ValueError("each displayable Signal must reference the current execution")
    return list(detached.signals)


__all__ = [
    "SignalRequest", "SignalDelivery", "SignalSource", "execution_digest", "resolve_signals",
]
