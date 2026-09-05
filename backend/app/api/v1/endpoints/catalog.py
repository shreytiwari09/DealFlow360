"""Catalogue and customer lookups used by the quotation builder selectors."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, SessionDep
from app.models.catalog import Product
from app.models.customer import Customer
from app.schemas.api import CustomerResponse, ProductResponse

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
