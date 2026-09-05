"""Catalogue and customer lookups used by the quotation builder selectors."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, SessionDep
from app.models.billing import SubscriptionPlan
from app.models.catalog import Product
from app.models.customer import Customer
from app.schemas.api import CustomerResponse, ProductResponse, SubscriptionPlanResponse

router = APIRouter(tags=["catalog"])


@router.get("/products", response_model=list[ProductResponse])
async def list_products(session: SessionDep, user: CurrentUser) -> list[ProductResponse]:
    rows = (
        (
            await session.execute(
                select(Product)
                .where(Product.is_active.is_(True))
                .options(selectinload(Product.category))
                .order_by(Product.name)
            )
        )
        .scalars()
        .all()
    )
    return [
        ProductResponse(
            id=p.id,
            sku=p.sku,
            name=p.name,
            category_id=p.category_id,
            category_code=p.category.code,
            list_price=p.list_price,
            tax_rate=p.tax_rate,
            item_type=p.item_type,
            is_promoted=p.is_promoted,
        )
        for p in rows
    ]


@router.get("/subscription-plans", response_model=list[SubscriptionPlanResponse])
async def list_subscription_plans(
    session: SessionDep, user: CurrentUser
) -> list[SubscriptionPlanResponse]:
    """The builder's plan picker (FRONTEND.md Screen 4) — one dropdown per
    subscription line, populated from here rather than free text."""
    rows = (
        (
            await session.execute(
                select(SubscriptionPlan)
                .where(SubscriptionPlan.is_active.is_(True))
                .order_by(SubscriptionPlan.name)
            )
        )
        .scalars()
        .all()
    )
    return [
        SubscriptionPlanResponse(
            id=p.id,
            code=p.code,
            name=p.name,
            billing_interval=p.billing_interval,
            interval_count=p.interval_count,
            unit_amount=p.unit_amount,
        )
        for p in rows
    ]


@router.get("/customers", response_model=list[CustomerResponse])
async def list_customers(session: SessionDep, user: CurrentUser) -> list[CustomerResponse]:
    rows = (
        (
            await session.execute(
                select(Customer).where(Customer.is_active.is_(True)).order_by(Customer.name)
            )
        )
        .scalars()
        .all()
    )
    return [CustomerResponse.model_validate(c) for c in rows]
