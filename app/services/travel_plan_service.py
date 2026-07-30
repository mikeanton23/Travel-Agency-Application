# -*- coding: utf-8 -*-

from sqlalchemy.orm import joinedload

from app.db.database import SessionLocal
from app.db.models import TravelPlan, Destination


def normalize_text(value):
    return " ".join((value or "").replace("\n", " ").split()).strip()


def get_saved_travel_plan(
    destination_id: int,
    month: str,
    travelers: str,
    continent: str,
    days: int,
    budget: float,
    user_preferences: str,
):
    """
    Load an existing saved travel plan if the same user search parameters exist.
    """

    db = SessionLocal()

    try:
        normalized_preferences = normalize_text(user_preferences)

        plan = (
            db.query(TravelPlan)
            .options(joinedload(TravelPlan.destination))
            .filter(TravelPlan.destination_id == destination_id)
            .filter(TravelPlan.month == month)
            .filter(TravelPlan.travelers == travelers)
            .filter(TravelPlan.continent == continent)
            .filter(TravelPlan.days == int(days))
            .filter(TravelPlan.budget == float(budget))
            .filter(TravelPlan.user_preferences == normalized_preferences)
            .order_by(TravelPlan.updated_at.desc())
            .first()
        )

        if plan:
            print(f"[TRAVEL PLAN] Loaded saved plan for destination_id={destination_id}")
            return plan.plan_markdown

        print(f"[TRAVEL PLAN] No saved plan found for destination_id={destination_id}")
        return None

    finally:
        db.close()


def save_travel_plan(
    destination_id: int,
    month: str,
    travelers: str,
    continent: str,
    days: int,
    budget: float,
    user_preferences: str,
    plan_markdown: str,
):
    """
    Save or update a generated travel plan.
    """

    db = SessionLocal()

    try:
        normalized_preferences = normalize_text(user_preferences)

        existing = (
            db.query(TravelPlan)
            .filter(TravelPlan.destination_id == destination_id)
            .filter(TravelPlan.month == month)
            .filter(TravelPlan.travelers == travelers)
            .filter(TravelPlan.continent == continent)
            .filter(TravelPlan.days == int(days))
            .filter(TravelPlan.budget == float(budget))
            .filter(TravelPlan.user_preferences == normalized_preferences)
            .first()
        )

        if existing:
            existing.plan_markdown = plan_markdown
            db.commit()
            print(f"[TRAVEL PLAN] Updated saved plan for destination_id={destination_id}")
            return existing

        plan = TravelPlan(
            destination_id=destination_id,
            month=month,
            travelers=travelers,
            continent=continent,
            days=int(days),
            budget=float(budget),
            user_preferences=normalized_preferences,
            plan_markdown=plan_markdown,
        )

        db.add(plan)
        db.commit()
        db.refresh(plan)

        print(f"[TRAVEL PLAN] Saved new plan for destination_id={destination_id}")
        return plan

    except Exception as e:
        db.rollback()
        print(f"[TRAVEL PLAN ERROR] Save failed: {e}")
        raise

    finally:
        db.close()


def delete_saved_travel_plan(plan_id: int):
    """
    Delete one saved travel plan.
    """

    db = SessionLocal()

    try:
        plan = db.query(TravelPlan).filter(TravelPlan.id == plan_id).first()

        if not plan:
            print(f"[TRAVEL PLAN] Plan not found: {plan_id}")
            return False

        db.delete(plan)
        db.commit()

        print(f"[TRAVEL PLAN] Deleted plan_id={plan_id}")
        return True

    except Exception as e:
        db.rollback()
        print(f"[TRAVEL PLAN ERROR] Delete failed: {e}")
        raise

    finally:
        db.close()


def get_all_saved_travel_plans(limit: int = 30):
    """
    Return latest saved travel plans.
    Useful later for a 'Saved Trips' page.
    """

    db = SessionLocal()

    try:
        plans = (
            db.query(TravelPlan)
            .options(joinedload(TravelPlan.destination))
            .order_by(TravelPlan.updated_at.desc())
            .limit(limit)
            .all()
        )

        print(f"[TRAVEL PLAN] Loaded {len(plans)} saved plans")
        return plans

    finally:
        db.close()