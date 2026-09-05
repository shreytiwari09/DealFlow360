"""Demo and development seed data.

Run with:  docker compose exec backend python -m app.seed

Idempotent: every row is looked up by its natural key and updated in place, so
re-running never duplicates and always converges on the state described here.

The data is shaped deliberately so both PLAN.md Section 16 demo flows work
straight after a single seed run - see `_seed_stock` and the discount tier
matrix for the specific numbers and why they were chosen.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.session import SessionLocal, engine
from app.models import (
    ApprovalChain,
    Customer,
    DiscountTier,
    Permission,
    PriceList,
    PriceListItem,
    Product,
    ProductCategory,
    ProductVariant,
    Role,
    SalesTeam,
    StockLevel,
    SubscriptionPlan,
    UpsellRule,
    User,
    Warehouse,
)
from app.models.enums import BillingInterval, CustomerTier, ItemType, RoleCode

# Dev-only credential. Not a secret: it exists solely so the demo has known
# logins, and it is overridable from the environment. Every account created
# here is a fixture, not a real user.
DEFAULT_PASSWORD = os.environ.get("SEED_DEFAULT_PASSWORD", "DealFlow360!demo")


async def _upsert[T](
    session: AsyncSession, model: type[T], lookup: dict[str, Any], **defaults: Any
) -> T:
    """Fetch by natural key and update, or create. Keeps the seed idempotent."""
    existing = (await session.execute(select(model).filter_by(**lookup))).scalar_one_or_none()

    if existing is None:
        created = model(**lookup, **defaults)
        session.add(created)
        await session.flush()
        return created

    for field, value in defaults.items():
        setattr(existing, field, value)
    await session.flush()
    return existing


# --- Identity and access ---------------------------------------------------

PERMISSIONS: list[tuple[str, str]] = [
    ("deal.create", "Create quotations"),
    ("deal.read_own", "Read quotations they own"),
    ("deal.read_team", "Read quotations owned by their team"),
    ("deal.read_all", "Read every quotation"),
    ("deal.update_own", "Edit quotations they own"),
    ("deal.assign", "Reassign a quotation to another rep"),
    ("deal.approve_manager", "First-level (Sales Manager) approval"),
    ("deal.approve_finance", "Second-level (Finance) approval"),
    ("portal.own_quote.view", "Portal: view own quotation"),
    ("portal.own_quote.negotiate", "Portal: counter-offer and comment"),
    ("fulfillment.manage", "Accept or override warehouse splits, manage backorders"),
    ("billing.manage", "Manage billing schedules, payments and credit notes"),
    ("config.manage", "Configure products, price lists, discount tiers, chains"),
    ("user.manage", "Create users and change roles"),
    ("report.view", "View reports and dashboards"),
    ("audit.view", "Read the audit log"),
]

# Role -> permission codes. This mapping IS the authorization policy; endpoints
# ask for a permission, never for a role (SECURITY_SPEC.md Section 4).
ROLE_PERMISSIONS: dict[RoleCode, list[str]] = {
    RoleCode.ADMIN: [code for code, _ in PERMISSIONS],
    RoleCode.SALES_MANAGER: [
        "deal.create",
        "deal.read_own",
        "deal.read_team",
        "deal.update_own",
        "deal.assign",
        "deal.approve_manager",
        "config.manage",
        "report.view",
        "audit.view",
    ],
    RoleCode.SALES_REP: [
        "deal.create",
        "deal.read_own",
        "deal.update_own",
        "report.view",
    ],
    RoleCode.FINANCE_OPS: [
        "deal.read_all",
        "deal.approve_finance",
        "fulfillment.manage",
        "billing.manage",
        "report.view",
    ],
    # Deliberately tiny. A portal user must never reach an internal screen.
    RoleCode.CUSTOMER: [
        "portal.own_quote.view",
        "portal.own_quote.negotiate",
    ],
}

ROLE_NAMES: dict[RoleCode, str] = {
    RoleCode.ADMIN: "Administrator",
    RoleCode.SALES_MANAGER: "Sales Manager / Approver",
    RoleCode.SALES_REP: "Sales Representative",
    RoleCode.FINANCE_OPS: "Finance / Operations",
    RoleCode.CUSTOMER: "Customer (Portal User)",
}


async def _seed_rbac(session: AsyncSession) -> dict[RoleCode, Role]:
    permissions: dict[str, Permission] = {}
    for code, description in PERMISSIONS:
        permissions[code] = await _upsert(
            session, Permission, {"code": code}, description=description
        )

    roles: dict[RoleCode, Role] = {}
    for role_code, granted in ROLE_PERMISSIONS.items():
        role = await _upsert(session, Role, {"code": role_code}, name=ROLE_NAMES[role_code])
        # The collection must be loaded before it can be assigned: SQLAlchemy
        # diffs the new value against the current contents, and on a freshly
        # inserted row that collection has never been fetched. Under asyncio
        # that implicit load raises MissingGreenlet rather than quietly issuing
        # IO, so it has to be awaited explicitly.
        await session.refresh(role, attribute_names=["permissions"])
        # Assign wholesale rather than appending, so removing a permission from
        # the map above actually revokes it on the next seed run.
        role.permissions = [permissions[code] for code in granted]
        roles[role_code] = role

    await session.flush()
    return roles


async def _seed_users(
    session: AsyncSession, roles: dict[RoleCode, Role], acme: Customer
) -> dict[str, User]:
    password_hash = hash_password(DEFAULT_PASSWORD)

    specs: list[tuple[str, str, RoleCode, int | None]] = [
        ("admin@dealflow360.example", "Ana Admin", RoleCode.ADMIN, None),
        ("manager@dealflow360.example", "Maya Manager", RoleCode.SALES_MANAGER, None),
        ("rep@dealflow360.example", "Raj Rep", RoleCode.SALES_REP, None),
        ("finance@dealflow360.example", "Fiona Finance", RoleCode.FINANCE_OPS, None),
        # The portal user. customer_id is what scopes them to Acme's quotations
        # and nothing else; it is set here because signup can never set it.
        ("portal@acme.example", "Cara Customer", RoleCode.CUSTOMER, acme.id),
    ]

    users: dict[str, User] = {}
    for email, full_name, role_code, customer_id in specs:
        users[email] = await _upsert(
            session,
            User,
            {"email": email},
            password_hash=password_hash,
            full_name=full_name,
            role_id=roles[role_code].id,
            customer_id=customer_id,
        )

    team = await _upsert(
        session,
        SalesTeam,
        {"name": "North Sales Team"},
        manager_id=users["manager@dealflow360.example"].id,
    )
    users["rep@dealflow360.example"].sales_team_id = team.id
    users["manager@dealflow360.example"].sales_team_id = team.id

    await session.flush()
    return users


# --- Commercial master data ------------------------------------------------


async def _seed_customers(session: AsyncSession) -> dict[str, Customer]:
    specs = [
        ("ACME", "Acme Corp", CustomerTier.GOLD),
        ("BETA", "Beta Industries", CustomerTier.SILVER),
        ("GAMMA", "Gamma Ltd", CustomerTier.BRONZE),
    ]
    customers: dict[str, Customer] = {}
    for code, name, tier in specs:
        customers[code] = await _upsert(
            session,
            Customer,
            {"code": code},
            name=name,
            tier=tier,
            email=f"accounts@{code.lower()}.example",
            currency="INR",
        )
    return customers


async def _seed_catalog(
    session: AsyncSession,
) -> tuple[dict[str, ProductCategory], dict[str, Product]]:
    category_specs = [
        ("HW", "Hardware", "Physical goods, healthy margin"),
        ("SVC", "Services", "Delivered by people, thin margin"),
        ("SUB", "Subscriptions", "Recurring revenue"),
    ]
    categories: dict[str, ProductCategory] = {}
    for code, name, description in category_specs:
        categories[code] = await _upsert(
            session, ProductCategory, {"code": code}, name=name, description=description
        )

    # (sku, name, category, list, cost, tax, type, promoted)
    product_specs = [
        (
            "HW-LAPTOP",
            "Business Laptop 14″",
            "HW",
            "100000",
            "70000",
            "18",
            ItemType.ONE_TIME,
            False,
        ),
        ("HW-MONITOR", "27″ 4K Monitor", "HW", "25000", "16000", "18", ItemType.ONE_TIME, False),
        ("HW-DOCK", "USB-C Docking Station", "HW", "12000", "7000", "18", ItemType.ONE_TIME, True),
        # Thin margin on purpose - this is why Services carries a lower ceiling
        # and it is the line the PRD's worked example breaches.
        (
            "SVC-SETUP",
            "Onboarding & Setup Service",
            "SVC",
            "20000",
            "15000",
            "18",
            ItemType.ONE_TIME,
            False,
        ),
        ("SVC-TRAIN", "User Training Day", "SVC", "15000", "11000", "18", ItemType.ONE_TIME, False),
        (
            "SUB-SUPPORT",
            "Premium Support Plan",
            "SUB",
            "1200",
            "400",
            "18",
            ItemType.SUBSCRIPTION,
            False,
        ),
        ("SUB-CLOUD", "Cloud Backup", "SUB", "800", "300", "18", ItemType.SUBSCRIPTION, True),
    ]
    products: dict[str, Product] = {}
    for sku, name, cat, price, cost, tax, item_type, promoted in product_specs:
        products[sku] = await _upsert(
            session,
            Product,
            {"sku": sku},
            name=name,
            category_id=categories[cat].id,
            list_price=Decimal(price),
            cost_price=Decimal(cost),
            tax_rate=Decimal(tax),
            item_type=item_type,
            is_promoted=promoted,
        )

    # Variants (PRD A2), on the product the demo actually uses.
    for value, extra in [("16GB", "0"), ("32GB", "15000")]:
        await _upsert(
            session,
            ProductVariant,
            {
                "product_id": products["HW-LAPTOP"].id,
                "attribute_name": "RAM",
                "attribute_value": value,
            },
            extra_price=Decimal(extra),
            sku_suffix=value,
        )

    return categories, products


async def _seed_price_lists(session: AsyncSession, products: dict[str, Product]) -> None:
    standard = await _upsert(
        session,
        PriceList,
        {"code": "PL-STANDARD"},
        name="Standard Price List",
        customer_tier=None,  # applies to every tier
        currency="INR",
        valid_from=date(2026, 1, 1),
    )
    gold = await _upsert(
        session,
        PriceList,
        {"code": "PL-GOLD"},
        name="Gold Tier Price List",
        customer_tier=CustomerTier.GOLD,
        currency="INR",
        valid_from=date(2026, 1, 1),
    )

    for sku, product in products.items():
        await _upsert(
            session,
            PriceListItem,
            {
                "price_list_id": standard.id,
                "product_id": product.id,
                "min_quantity": Decimal("1"),
            },
            unit_price=product.list_price,
        )
        # Gold customers get better headline pricing before any discount, which
        # is a different lever from the discount ceiling - worth being able to
        # show that the two are independent.
        await _upsert(
            session,
            PriceListItem,
            {
                "price_list_id": gold.id,
                "product_id": product.id,
                "min_quantity": Decimal("1"),
            },
            unit_price=(product.list_price * Decimal("0.95")).quantize(Decimal("0.01")),
        )
        # A volume break, so the price-list complexity is real rather than
        # decorative.
        if sku.startswith("HW-"):
            await _upsert(
                session,
                PriceListItem,
                {
                    "price_list_id": standard.id,
                    "product_id": product.id,
                    "min_quantity": Decimal("10"),
                },
                unit_price=(product.list_price * Decimal("0.92")).quantize(Decimal("0.01")),
            )


# --- Discount governance ---------------------------------------------------

# Locked Business Rules #6. Graduated by margin: Hardware sits at the tier cap,
# Services is stricter, Subscriptions strictest.
#
# Reproduces the PRD Section 10 example exactly: Gold + Hardware = 15,
# Gold + Services = 10.
CEILINGS: dict[str, dict[CustomerTier, str]] = {
    "HW": {CustomerTier.BRONZE: "5", CustomerTier.SILVER: "10", CustomerTier.GOLD: "15"},
    "SVC": {CustomerTier.BRONZE: "3", CustomerTier.SILVER: "7", CustomerTier.GOLD: "10"},
    "SUB": {CustomerTier.BRONZE: "2", CustomerTier.SILVER: "5", CustomerTier.GOLD: "8"},
}


async def _seed_discount_tiers(
    session: AsyncSession, categories: dict[str, ProductCategory]
) -> None:
    for category_code, per_tier in CEILINGS.items():
        for tier, ceiling in per_tier.items():
            await _upsert(
                session,
                DiscountTier,
                {"customer_tier": tier, "category_id": categories[category_code].id},
                max_discount_percent=Decimal(ceiling),
            )


async def _seed_approval_chains(session: AsyncSession, roles: dict[RoleCode, Role]) -> None:
    """Locked Business Rules #2b.

    Bands are half-open: min_score <= score < max_score. A score of exactly 0
    matches no band, which is how "no approval required" is expressed. The 0.01
    floor is the smallest non-zero value a NUMERIC(6,2) score can hold.

    The single-line Finance gate (max line excess > 15) is NOT here - it is a
    guard rail in the risk engine, applied on top of whatever these bands
    return, so retuning them cannot silently disable it.
    """
    specs = [
        ("0.01", "25.00", RoleCode.SALES_MANAGER, 1, "Manager approval"),
        ("25.00", None, RoleCode.SALES_MANAGER, 1, "Manager approval (high risk)"),
        ("25.00", None, RoleCode.FINANCE_OPS, 2, "Finance approval (high risk)"),
    ]
    for min_score, max_score, role_code, step_order, label in specs:
        await _upsert(
            session,
            ApprovalChain,
            {"min_score": Decimal(min_score), "step_order": step_order},
            max_score=Decimal(max_score) if max_score else None,
            required_role_id=roles[role_code].id,
            label=label,
        )


# --- Inventory -------------------------------------------------------------


async def _seed_warehouses(session: AsyncSession) -> dict[str, Warehouse]:
    specs = [
        ("WH-MAIN", "Main Warehouse", "Pune", "1.00"),
        # Higher weight, so the greedy split prefers Main and only reaches here
        # when Main cannot cover the line.
        ("WH-EAST", "East Depot", "Kolkata", "1.50"),
    ]
    warehouses: dict[str, Warehouse] = {}
    for code, name, location, weight in specs:
        warehouses[code] = await _upsert(
            session,
            Warehouse,
            {"code": code},
            name=name,
            location=location,
            shipping_cost_weight=Decimal(weight),
        )
    return warehouses


async def _seed_stock(
    session: AsyncSession,
    warehouses: dict[str, Warehouse],
    products: dict[str, Product],
) -> None:
    """Stock levels chosen to make the demo exercise real paths.

    HW-LAPTOP holds 6 in Main and 3 in East. A demo order for 10 laptops
    therefore SPLITS across both warehouses and still leaves 1 short, creating
    a BACKORDER - covering both halves of PLAN.md Section 16 Flow 1 from one
    order rather than needing two contrived ones.

    HW-DOCK is deliberately empty in Main, so the split must source it from the
    non-preferred warehouse and the shipping weight visibly does something.

    Services and subscriptions are not stocked; they have no rows at all.
    """
    stock = {
        "HW-LAPTOP": {"WH-MAIN": "6", "WH-EAST": "3"},
        "HW-MONITOR": {"WH-MAIN": "20", "WH-EAST": "15"},
        "HW-DOCK": {"WH-MAIN": "0", "WH-EAST": "12"},
    }
    for sku, per_warehouse in stock.items():
        for warehouse_code, quantity in per_warehouse.items():
            await _upsert(
                session,
                StockLevel,
                {
                    "warehouse_id": warehouses[warehouse_code].id,
                    "product_id": products[sku].id,
                    "variant_id": None,
                },
                quantity_on_hand=Decimal(quantity),
                quantity_reserved=Decimal("0"),
                reorder_point=Decimal("5"),
            )


# --- Subscriptions and upsell ----------------------------------------------


async def _seed_subscription_plans(session: AsyncSession) -> None:
    specs = [
        ("PLAN-SUPPORT-M", "Premium Support (Monthly)", BillingInterval.MONTHLY, "1200"),
        ("PLAN-CLOUD-M", "Cloud Backup (Monthly)", BillingInterval.MONTHLY, "800"),
        ("PLAN-SUPPORT-Y", "Premium Support (Yearly)", BillingInterval.YEARLY, "13000"),
    ]
    for code, name, interval, amount in specs:
        await _upsert(
            session,
            SubscriptionPlan,
            {"code": code},
            name=name,
            billing_interval=interval,
            interval_count=1,
            unit_amount=Decimal(amount),
            proration_enabled=True,
        )


async def _seed_upsell_rules(session: AsyncSession, products: dict[str, Product]) -> None:
    """Co-purchase pairings (PRD A6). A lookup table, not a model - PLAN.md
    Section 20 rules out ML here, and a deterministic table cannot embarrass us
    live."""
    specs = [
        ("HW-LAPTOP", "HW-MONITOR", "9.2", "20"),
        ("HW-LAPTOP", "HW-DOCK", "8.5", "20"),
        ("HW-LAPTOP", "SUB-SUPPORT", "7.8", "10"),
        ("HW-LAPTOP", "SVC-SETUP", "6.4", "10"),
        ("HW-MONITOR", "HW-DOCK", "6.0", "20"),
        ("SVC-SETUP", "SVC-TRAIN", "5.5", "10"),
        ("SUB-SUPPORT", "SUB-CLOUD", "4.8", "10"),
    ]
    for trigger_sku, suggested_sku, score, min_margin in specs:
        await _upsert(
            session,
            UpsellRule,
            {
                "trigger_product_id": products[trigger_sku].id,
                "suggested_product_id": products[suggested_sku].id,
            },
            co_purchase_score=Decimal(score),
            min_margin_percent=Decimal(min_margin),
        )


# --- Entry point -----------------------------------------------------------


async def seed() -> None:
    async with SessionLocal() as session:
        roles = await _seed_rbac(session)
        customers = await _seed_customers(session)
        await _seed_users(session, roles, customers["ACME"])
        categories, products = await _seed_catalog(session)
        await _seed_price_lists(session, products)
        await _seed_discount_tiers(session, categories)
        await _seed_approval_chains(session, roles)
        warehouses = await _seed_warehouses(session)
        await _seed_stock(session, warehouses, products)
        await _seed_subscription_plans(session)
        await _seed_upsell_rules(session, products)

        await session.commit()

    print("Seed complete.")
    print()
    print("  Logins (all share the same password):")
    for email in (
        "admin@dealflow360.example",
        "manager@dealflow360.example",
        "rep@dealflow360.example",
        "finance@dealflow360.example",
        "portal@acme.example",
    ):
        print(f"    {email}")
    print(f"  Password: {DEFAULT_PASSWORD}   (dev only - override SEED_DEFAULT_PASSWORD)")
    print()
    print("  Demo shape:")
    print("    Acme Corp is GOLD  -> Hardware ceiling 15%, Services 10%")
    print("    Laptop 12% + Setup Service 18%  -> score 1.33  -> Manager")
    print("    Any single line >15 points over -> Manager + Finance")
    print("    10 laptops -> 6 from Main + 3 from East + 1 backordered")


async def _main() -> None:
    try:
        await seed()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
