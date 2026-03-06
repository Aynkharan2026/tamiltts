"""
Stripe Webhook Receiver
Tamil TTS Studio — VoxTN

Stripe is the PRIMARY source of truth for subscription state.
Events handled:
  - checkout.session.completed
  - customer.subscription.updated
  - customer.subscription.created
  - customer.subscription.deleted
  - invoice.payment_failed
"""
import os
import logging
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _get_stripe_event(body: bytes, sig: str):
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        logger.warning("STRIPE_WEBHOOK_SECRET not configured — webhook inactive")
        raise HTTPException(400, "Stripe webhook not configured. Set STRIPE_WEBHOOK_SECRET in environment.")
    try:
        return stripe.Webhook.construct_event(body, sig, secret)
    except stripe.error.SignatureVerificationError as e:
        logger.warning("Stripe signature invalid: %s", e)
        raise HTTPException(400, "Invalid Stripe signature")


def _price_to_plan(price_id: str) -> str:
    mapping = {
        os.environ.get("STRIPE_PRICE_PREMIUM_MONTHLY", ""): "premium",
        os.environ.get("STRIPE_PRICE_PREMIUM_ANNUAL",  ""): "premium",
        os.environ.get("STRIPE_PRICE_BETA",            ""): "beta",
    }
    return mapping.get(price_id, "free")


def _price_to_cycle(price_id: str) -> str:
    return "annual" if price_id == os.environ.get("STRIPE_PRICE_PREMIUM_ANNUAL", "") else "monthly"


def _user_by_customer(customer_id: str, db: Session):
    return db.execute(
        text("SELECT id FROM users WHERE stripe_customer_id = :cid"),
        {"cid": customer_id},
    ).fetchone()


def _upsert_sub(user_id, plan_name, cycle, stripe_sub_id,
                stripe_cid, period_start, period_end, status, db):
    plan = db.execute(
        text("SELECT id FROM subscription_plans WHERE name = :n"),
        {"n": plan_name},
    ).fetchone()
    if not plan:
        logger.error("Plan not found: %s", plan_name)
        return

    now = datetime.now(timezone.utc)
    existing = db.execute(
        text("SELECT id FROM user_subscriptions WHERE user_id = :uid"),
        {"uid": user_id},
    ).fetchone()

    if existing:
        db.execute(text("""
            UPDATE user_subscriptions SET
                plan_id = :plan_id, status = :status,
                billing_cycle = :cycle,
                stripe_subscription_id = :sub_id,
                stripe_customer_id = :cid,
                current_period_start = :ps,
                current_period_end = :pe,
                updated_at = :now
            WHERE user_id = :uid
        """), {"plan_id": str(plan.id), "status": status, "cycle": cycle,
               "sub_id": stripe_sub_id, "cid": stripe_cid,
               "ps": period_start, "pe": period_end, "now": now, "uid": user_id})
    else:
        db.execute(text("""
            INSERT INTO user_subscriptions
                (user_id, plan_id, status, billing_cycle,
                 stripe_subscription_id, stripe_customer_id,
                 current_period_start, current_period_end,
                 created_at, updated_at)
            VALUES
                (:uid, :plan_id, :status, :cycle,
                 :sub_id, :cid, :ps, :pe, :now, :now)
        """), {"uid": user_id, "plan_id": str(plan.id), "status": status,
               "cycle": cycle, "sub_id": stripe_sub_id, "cid": stripe_cid,
               "ps": period_start, "pe": period_end, "now": now})
    db.commit()
    logger.info("Subscription upserted: user=%s plan=%s status=%s", user_id, plan_name, status)


@router.post("/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    body  = await request.body()
    sig   = request.headers.get("stripe-signature", "")
    event = _get_stripe_event(body, sig)
    etype = event["type"]
    data  = event["data"]["object"]
    logger.info("Stripe event: %s", etype)

    if etype == "checkout.session.completed":
        cid = data.get("customer")
        uid = data.get("client_reference_id")
        if cid and uid:
            db.execute(
                text("UPDATE users SET stripe_customer_id = :cid WHERE id = :uid"),
                {"cid": cid, "uid": uid},
            )
            db.commit()
            logger.info("Stripe customer linked: user=%s customer=%s", uid, cid)

    elif etype in ("customer.subscription.updated", "customer.subscription.created"):
        cid   = data.get("customer")
        user  = _user_by_customer(cid, db)
        if not user:
            logger.warning("No user for Stripe customer: %s", cid)
            return {"status": "ok"}
        items      = data.get("items", {}).get("data", [])
        price_id   = items[0]["price"]["id"] if items else ""
        plan_name  = _price_to_plan(price_id)
        cycle      = _price_to_cycle(price_id)
        sub_status = data.get("status", "active")
        ps = datetime.fromtimestamp(data["current_period_start"], tz=timezone.utc)
        pe = datetime.fromtimestamp(data["current_period_end"],   tz=timezone.utc)
        _upsert_sub(str(user.id), plan_name, cycle, data["id"], cid, ps, pe, sub_status, db)

    elif etype == "customer.subscription.deleted":
        cid  = data.get("customer")
        user = _user_by_customer(cid, db)
        if user:
            db.execute(text("""
                UPDATE user_subscriptions
                SET status = 'cancelled', cancelled_at = :now, updated_at = :now
                WHERE user_id = :uid
            """), {"now": datetime.now(timezone.utc), "uid": str(user.id)})
            db.commit()
            logger.info("Subscription cancelled: user=%s", user.id)

    elif etype == "invoice.payment_failed":
        cid  = data.get("customer")
        user = _user_by_customer(cid, db)
        if user:
            db.execute(text("""
                UPDATE user_subscriptions
                SET status = 'expired', updated_at = :now
                WHERE user_id = :uid AND status = 'active'
            """), {"now": datetime.now(timezone.utc), "uid": str(user.id)})
            db.commit()
            logger.warning("Payment failed — subscription expired: user=%s", user.id)

    return {"status": "ok"}
