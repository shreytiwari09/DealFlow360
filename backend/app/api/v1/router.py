"""Aggregate router for API v1."""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin,
    approvals,
    auth,
    billing,
    catalog,
    dashboard,
    dealhealth,
    fulfillment,
    health,
    portal,
    quotations,
    reports,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(catalog.router)
api_router.include_router(dashboard.router)
api_router.include_router(quotations.router)
api_router.include_router(approvals.router)
api_router.include_router(fulfillment.router)
api_router.include_router(billing.router)
api_router.include_router(portal.router)
api_router.include_router(admin.router)
api_router.include_router(dealhealth.router)
api_router.include_router(reports.router)
