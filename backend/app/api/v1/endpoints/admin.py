"""Admin configuration — FRONTEND.md Screens 16-18, PRD A2 and A3.

Everything here is gated by the single `config.manage` permission, which the
seed already grants to both Admin and Sales Manager (RoleCode.SALES_MANAGER
holds it for exactly the reason PRD A3 states: "Sales Manager... configures
discount tiers and approval chains"). FRONTEND.md's own wireframe draws the
Product Catalog screen as Admin-only and the Discount Tiers screen as
Admin + Sales Manager — two different permissions would model that more
precisely, but the backend's RBAC design already committed to one
`config.manage` permission covering all of "products, price lists, discount
tiers, approval chains" (see PROJECT_CONTEXT.md's Important Technical
Decisions and `app/seed.py`'s `PERMISSIONS` list). Splitting it now would be
redefining an existing locked decision for a screen-level distinction the PRD
itself does not insist on; not raised as a question given how low-stakes it
is — a Sales Manager seeing the product catalogue is not a security problem.

Master data is archived, never hard-deleted (`ArchivableMixin`) — a historical
quotation may still reference an old category or product.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import SessionDep, require_permission
from app.models.audit import AuditAction
from app.models.catalog import Product, ProductCategory
from app.models.enums import ItemType
from app.models.policy import ApprovalChain, DiscountTier
from app.models.rbac import Role, User
from app.schemas.api import (
    AdminProductResponse,
    ApprovalChainResponse,
    CreateApprovalChainRequest,
    CreateDiscountTierRequest,
    CreateProductCategoryRequest,
    CreateProductRequest,
    DiscountTierResponse,
    ProductCategoryResponse,
    RoleOptionResponse,
    UpdateApprovalChainRequest,
    UpdateDiscountTierRequest,
    UpdateProductRequest,
)
from app.services import audit

router = APIRouter(prefix="/admin", tags=["admin"])

CanConfigure = Annotated[User, Depends(require_permission("config.manage"))]

_DP2 = Decimal("0.01")


def _q2(value: Decimal) -> Decimal:
    """Quantize to 2dp, matching every Numeric(x, 2) column this module
    writes to (percentages and money alike). Without this, a value set
    directly from a request body (e.g. a bare `16`) prints without trailing
    zeros in the same response that shows every DB-round-tripped value as
    `"16.00"` — the same cosmetic fixed in `services/{billing,portal,
    quotation}.py`; this is that pattern's next occurrence."""
    return value.quantize(_DP2, rounding=ROUND_HALF_UP)


_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


# --- Roles (for the approval-chain role picker) -----------------------------


@router.get("/roles", response_model=list[RoleOptionResponse])
async def list_roles(session: SessionDep, user: CanConfigure) -> list[RoleOptionResponse]:
    rows = (await session.execute(select(Role).order_by(Role.name))).scalars().all()
    return [RoleOptionResponse(id=r.id, code=r.code, name=r.name) for r in rows]


# --- Discount tiers ----------------------------------------------------------


def _tier_response(tier: DiscountTier) -> DiscountTierResponse:
    return DiscountTierResponse(
        id=tier.id,
        customer_tier=tier.customer_tier,
        category_id=tier.category_id,
        category_name=tier.category.name,
        max_discount_percent=tier.max_discount_percent,
        is_active=tier.is_active,
    )


@router.get("/discount-tiers", response_model=list[DiscountTierResponse])
async def list_discount_tiers(
    session: SessionDep, user: CanConfigure
) -> list[DiscountTierResponse]:
    """The ceiling matrix behind the blended risk score (Locked Business
    Rules #1 and #6). Screen 18 renders this as one tier x category grid,
    which is the actual shape of the data — FRONTEND.md's wireframe draws it
    as two separate tables (tier-only, category-only), but the real ceiling
    has always been per (tier, category) pair; showing it as two independent
    tables would misrepresent how a ceiling is actually looked up.
    """
    rows = (
        (
            await session.execute(
                select(DiscountTier)
                .options(selectinload(DiscountTier.category))
                .order_by(DiscountTier.category_id, DiscountTier.customer_tier)
            )
        )
        .scalars()
        .all()
    )
    return [_tier_response(t) for t in rows]


@router.post(
    "/discount-tiers", response_model=DiscountTierResponse, status_code=status.HTTP_201_CREATED
)
async def create_discount_tier(
    request: Request, payload: CreateDiscountTierRequest, session: SessionDep, user: CanConfigure
) -> DiscountTierResponse:
    category = await session.get(ProductCategory, payload.category_id)
    if category is None:
        raise HTTPException(status_code=422, detail="Unknown category.")

    existing = (
        await session.execute(
            select(DiscountTier).where(
                DiscountTier.customer_tier == payload.customer_tier,
                DiscountTier.category_id == payload.category_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A ceiling for this tier and category already exists — edit it instead.",
        )

    tier = DiscountTier(
        customer_tier=payload.customer_tier,
        category_id=payload.category_id,
        max_discount_percent=_q2(payload.max_discount_percent),
        created_by=user.id,
    )
    session.add(tier)
    await session.flush()

    await audit.record(
        session,
        action=AuditAction.CONFIG_CHANGED,
        user_id=user.id,
        resource="discount_tier",
        resource_id=tier.id,
        reason=(
            f"created {payload.customer_tier}/{category.name} ceiling at "
            f"{payload.max_discount_percent}%"
        ),
        request=request,
    )
    await session.commit()
    await session.refresh(tier, attribute_names=["category"])
    return _tier_response(tier)


@router.put("/discount-tiers/{tier_id}", response_model=DiscountTierResponse)
async def update_discount_tier(
    request: Request,
    tier_id: int,
    payload: UpdateDiscountTierRequest,
    session: SessionDep,
    user: CanConfigure,
) -> DiscountTierResponse:
    tier = (
        await session.execute(
            select(DiscountTier)
            .where(DiscountTier.id == tier_id)
            .options(selectinload(DiscountTier.category))
        )
    ).scalar_one_or_none()
    if tier is None:
        raise _NOT_FOUND

    old = tier.max_discount_percent
    tier.max_discount_percent = _q2(payload.max_discount_percent)
    await audit.record(
        session,
        action=AuditAction.CONFIG_CHANGED,
        user_id=user.id,
        resource="discount_tier",
        resource_id=tier.id,
        reason=(
            f"{tier.customer_tier}/{tier.category.name} ceiling {old}% -> "
            f"{payload.max_discount_percent}%"
        ),
        request=request,
    )
    await session.commit()
    return _tier_response(tier)


# --- Approval chains ---------------------------------------------------------


def _chain_response(chain: ApprovalChain) -> ApprovalChainResponse:
    return ApprovalChainResponse(
        id=chain.id,
        min_score=chain.min_score,
        max_score=chain.max_score,
        required_role_id=chain.required_role_id,
        required_role_name=chain.required_role.name,
        required_role_code=chain.required_role.code,
        step_order=chain.step_order,
        label=chain.label,
        is_active=chain.is_active,
    )


@router.get("/approval-chains", response_model=list[ApprovalChainResponse])
async def list_approval_chains(
    session: SessionDep, user: CanConfigure
) -> list[ApprovalChainResponse]:
    """Locked Business Rules #2's routing bands, as configurable rows.

    NOTE: the single-line Finance gate (`max(line_excess) > 15`) is
    deliberately NOT here — see `policy.py`'s own docstring on
    `ApprovalChain`. It is a guard rail constant in `risk.py`, not a
    PRD-mandated configurable, and this screen must not imply it can be
    edited.
    """
    rows = (
        (
            await session.execute(
                select(ApprovalChain)
                .options(selectinload(ApprovalChain.required_role))
                .order_by(ApprovalChain.min_score, ApprovalChain.step_order)
            )
        )
        .scalars()
        .all()
    )
    return [_chain_response(c) for c in rows]


@router.post(
    "/approval-chains", response_model=ApprovalChainResponse, status_code=status.HTTP_201_CREATED
)
async def create_approval_chain(
    request: Request, payload: CreateApprovalChainRequest, session: SessionDep, user: CanConfigure
) -> ApprovalChainResponse:
    role = await session.get(Role, payload.required_role_id)
    if role is None:
        raise HTTPException(status_code=422, detail="Unknown role.")

    chain = ApprovalChain(
        min_score=_q2(payload.min_score),
        max_score=None if payload.max_score is None else _q2(payload.max_score),
        required_role_id=payload.required_role_id,
        step_order=payload.step_order,
        label=payload.label,
        created_by=user.id,
    )
    session.add(chain)
    await session.flush()

    await audit.record(
        session,
        action=AuditAction.CONFIG_CHANGED,
        user_id=user.id,
        resource="approval_chain",
        resource_id=chain.id,
        reason=(
            f"created band [{payload.min_score}, {payload.max_score}) "
            f"step {payload.step_order} -> {role.name}"
        ),
        request=request,
    )
    await session.commit()
    await session.refresh(chain, attribute_names=["required_role"])
    return _chain_response(chain)


@router.put("/approval-chains/{chain_id}", response_model=ApprovalChainResponse)
async def update_approval_chain(
    request: Request,
    chain_id: int,
    payload: UpdateApprovalChainRequest,
    session: SessionDep,
    user: CanConfigure,
) -> ApprovalChainResponse:
    chain = (
        await session.execute(
            select(ApprovalChain)
            .where(ApprovalChain.id == chain_id)
            .options(selectinload(ApprovalChain.required_role))
        )
    ).scalar_one_or_none()
    if chain is None:
        raise _NOT_FOUND

    chain.min_score = _q2(payload.min_score)
    chain.max_score = None if payload.max_score is None else _q2(payload.max_score)
    chain.step_order = payload.step_order
    chain.label = payload.label
    chain.is_active = payload.is_active

    await audit.record(
        session,
        action=AuditAction.CONFIG_CHANGED,
        user_id=user.id,
        resource="approval_chain",
        resource_id=chain.id,
        reason=f"updated band [{payload.min_score}, {payload.max_score}) step {payload.step_order}"
        + ("" if payload.is_active else " (deactivated)"),
        request=request,
    )
    await session.commit()
    return _chain_response(chain)


# --- Product categories -------------------------------------------------------


def _category_response(category: ProductCategory) -> ProductCategoryResponse:
    return ProductCategoryResponse(
        id=category.id,
        code=category.code,
        name=category.name,
        description=category.description,
        is_active=category.is_active,
    )


@router.get("/categories", response_model=list[ProductCategoryResponse])
async def list_categories(session: SessionDep, user: CanConfigure) -> list[ProductCategoryResponse]:
    rows = (
        (await session.execute(select(ProductCategory).order_by(ProductCategory.name)))
        .scalars()
        .all()
    )
    return [_category_response(c) for c in rows]


@router.post(
    "/categories", response_model=ProductCategoryResponse, status_code=status.HTTP_201_CREATED
)
async def create_category(
    request: Request, payload: CreateProductCategoryRequest, session: SessionDep, user: CanConfigure
) -> ProductCategoryResponse:
    existing = (
        await session.execute(select(ProductCategory).where(ProductCategory.code == payload.code))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="A category with this code already exists.")

    category = ProductCategory(
        code=payload.code, name=payload.name, description=payload.description, created_by=user.id
    )
    session.add(category)
    await session.flush()

    await audit.record(
        session,
        action=AuditAction.CONFIG_CHANGED,
        user_id=user.id,
        resource="product_category",
        resource_id=category.id,
        reason=f"created category '{payload.name}'",
        request=request,
    )
    await session.commit()
    return _category_response(category)


# --- Products ------------------------------------------------------------------


def _product_response(product: Product) -> AdminProductResponse:
    return AdminProductResponse(
        id=product.id,
        sku=product.sku,
        name=product.name,
        description=product.description,
        category_id=product.category_id,
        category_name=product.category.name,
        unit=product.unit,
        list_price=product.list_price,
        cost_price=product.cost_price,
        tax_rate=product.tax_rate,
        item_type=product.item_type,
        is_promoted=product.is_promoted,
        is_active=product.is_active,
    )


@router.get("/products", response_model=list[AdminProductResponse])
async def list_admin_products(
    session: SessionDep, user: CanConfigure
) -> list[AdminProductResponse]:
    """Screen 16. Unlike `GET /products` (the builder's picker, active-only),
    this includes archived products too — the KPI card on Screen 16 counts
    both ("128 active, 9 archived")."""
    rows = (
        (
            await session.execute(
                select(Product).options(selectinload(Product.category)).order_by(Product.name)
            )
        )
        .scalars()
        .all()
    )
    return [_product_response(p) for p in rows]


@router.get("/products/{product_id}", response_model=AdminProductResponse)
async def get_admin_product(
    product_id: int, session: SessionDep, user: CanConfigure
) -> AdminProductResponse:
    product = (
        await session.execute(
            select(Product).where(Product.id == product_id).options(selectinload(Product.category))
        )
    ).scalar_one_or_none()
    if product is None:
        raise _NOT_FOUND
    return _product_response(product)


@router.post("/products", response_model=AdminProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    request: Request, payload: CreateProductRequest, session: SessionDep, user: CanConfigure
) -> AdminProductResponse:
    category = await session.get(ProductCategory, payload.category_id)
    if category is None:
        raise HTTPException(status_code=422, detail="Unknown category.")
    existing = (
        await session.execute(select(Product).where(Product.sku == payload.sku))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="A product with this SKU already exists.")

    product = Product(
        sku=payload.sku,
        name=payload.name,
        description=payload.description,
        category_id=payload.category_id,
        unit=payload.unit,
        list_price=_q2(payload.list_price),
        cost_price=_q2(payload.cost_price),
        tax_rate=_q2(payload.tax_rate),
        item_type=ItemType(payload.item_type),
        is_promoted=payload.is_promoted,
        created_by=user.id,
    )
    session.add(product)
    await session.flush()

    await audit.record(
        session,
        action=AuditAction.CONFIG_CHANGED,
        user_id=user.id,
        resource="product",
        resource_id=product.id,
        reason=f"created product '{payload.name}' ({payload.sku})",
        request=request,
    )
    await session.commit()
    await session.refresh(product, attribute_names=["category"])
    return _product_response(product)


@router.put("/products/{product_id}", response_model=AdminProductResponse)
async def update_product(
    request: Request,
    product_id: int,
    payload: UpdateProductRequest,
    session: SessionDep,
    user: CanConfigure,
) -> AdminProductResponse:
    """Note: `item_type` is NOT editable here. A live product's item_type
    (one_time vs subscription) drives which billing path a NEW quotation line
    takes, but existing lines have already snapshotted their own `line_type` —
    changing it on the master record after the fact would not retroactively
    change history, and would only create the illusion that it could."""
    product = (
        await session.execute(
            select(Product).where(Product.id == product_id).options(selectinload(Product.category))
        )
    ).scalar_one_or_none()
    if product is None:
        raise _NOT_FOUND

    category = await session.get(ProductCategory, payload.category_id)
    if category is None:
        raise HTTPException(status_code=422, detail="Unknown category.")

    product.name = payload.name
    product.description = payload.description
    product.category_id = payload.category_id
    product.unit = payload.unit
    product.list_price = _q2(payload.list_price)
    product.cost_price = _q2(payload.cost_price)
    product.tax_rate = _q2(payload.tax_rate)
    product.is_promoted = payload.is_promoted
    product.is_active = payload.is_active

    await audit.record(
        session,
        action=AuditAction.CONFIG_CHANGED,
        user_id=user.id,
        resource="product",
        resource_id=product.id,
        reason=f"updated product '{product.name}'" + ("" if payload.is_active else " (archived)"),
        request=request,
    )
    await session.commit()
    await session.refresh(product, attribute_names=["category"])
    return _product_response(product)
