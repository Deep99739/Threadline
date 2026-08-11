from __future__ import annotations

from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.unit.test_models import TENANT, evidence, snapshot
from threadline.invariants import InvariantViolation, validate_snapshot


@given(st.uuids().filter(lambda value: value != TENANT))
def test_arbitrary_foreign_tenant_is_rejected(foreign_tenant: UUID) -> None:
    foreign_evidence = evidence(tenant_id=foreign_tenant)

    with pytest.raises(InvariantViolation, match="cross-tenant"):
        validate_snapshot(snapshot(evidence_items=(foreign_evidence,), claims=(), verifications=()))
