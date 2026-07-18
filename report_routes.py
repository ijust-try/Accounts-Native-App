
from fastapi import APIRouter, Depends, Query
from typing import Optional

from backend import (
    get_monthly_revenue,
    get_monthly_expenses_total,
    get_expense_summary_by_category,
    get_food_revenue_vs_cost,
    get_period_summary,
    get_yearly_summary,
    get_all_payment_summaries,
)
from security import require_owner_or_staff

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/monthly")
def monthly_report(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(...),
    property: Optional[str] = None,
    current_user: dict = Depends(require_owner_or_staff),
):
    rev_df = get_monthly_revenue(month, year, property_=property)
    total_revenue = float(rev_df["amount"].sum()) if not rev_df.empty else 0.0
    total_expenses = get_monthly_expenses_total(month, year, property_=property)
    food = get_food_revenue_vs_cost(month, year)

    return {
        "month": month,
        "year": year,
        "property": property or "All",
        "total_revenue": total_revenue,
        "total_expenses": total_expenses,
        "profit_or_loss": total_revenue - total_expenses,
        "expense_breakdown": get_expense_summary_by_category(month, year, property_=property).to_dict(orient="records"),
        "food_revenue": food["total_food_revenue"],
        "kitchen_cost": food["kitchen_cost"],
        "food_profit": food["food_profit"],
    }


@router.get("/period")
def period_report(
    months_back: int = Query(6, ge=1, le=24),
    property: Optional[str] = None,
    current_user: dict = Depends(require_owner_or_staff),
):
    return get_period_summary(months_back=months_back, property_=property)


@router.get("/yearly")
def yearly_report(
    year: int = Query(...),
    property: Optional[str] = None,
    current_user: dict = Depends(require_owner_or_staff),
):
    return get_yearly_summary(year, property_=property)


@router.get("/defaulters")
def defaulters_report(
    payment_mode: Optional[str] = None,
    current_user: dict = Depends(require_owner_or_staff),
):
    """Guests with an outstanding balance (deposit unpaid or rent balance > 0)."""
    df = get_all_payment_summaries(payment_mode_filter=payment_mode)
    due_only = df[df["alert"] == "red"]
    return due_only.to_dict(orient="records")