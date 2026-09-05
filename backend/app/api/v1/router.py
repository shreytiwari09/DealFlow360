"""Aggregate router for API v1.

Feature routers (auth, quotations, approvals, fulfillment, billing, portal,
reporting) are registered here as each is built in Phase 3 onward.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import health

api_router = APIRouter()
api_router.include_router(health.router)
