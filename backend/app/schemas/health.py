"""Response DTOs for health endpoints.

Explicit response models, not raw dicts - SECURITY_SPEC.md Section 6 requires
API responses to be shaped by DTOs so internal fields can never leak by
accident.
"""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    environment: str
    database: Literal["ok", "unavailable", "not_checked"]
