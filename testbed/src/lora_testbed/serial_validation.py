"""Bounded physical diagnostic check; this is partial IF-01 coverage."""

from typing import Literal

from pydantic import Field, model_validator

from .models import StrictModel


class SerialValidationRequest(StrictModel):
    roles: list[Literal["A", "B"]] | None = Field(default=None, min_length=1, max_length=2)
    cycles: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def distinct_roles(self):
        if self.roles and len(set(self.roles)) != len(self.roles):
            raise ValueError("Choose distinct roles")
        return self


def serial_plan(spec):
    return {
        "catalog_id": "IF-01",
        "mode": "hardware",
        "roles": spec.roles,
        "cycles": spec.cycles,
        "required_nodes": 1,
        "scope": "Identity, ownership, status and advancing uptime diagnostic check",
        "full_procedure": False,
        "full_procedure_passed": False,
        "hardware_validated": False,
        "note": (
            "Full IF-01 qualification requires additional framing, fault, lease and recovery cases"
        ),
    }
