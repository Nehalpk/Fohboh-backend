import os
import logging
from fastapi import HTTPException, Request, Depends, APIRouter
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
import stripe as stripe_integration
from typing import Optional
import psycopg2
from psycopg2.extras import RealDictCursor

from src.chat_gpt import get_current_user, get_db, DB_CONFIG, create_notification

#BASE_URL = "https://fohboh-restaurant-env-staging-octalooptechnologies-projects.vercel.app"
BASE_URL = "https://staging.fohboh.ai"
# Create router
router = APIRouter(
    prefix="/stripe",
    tags=["Stripe Integration"]
)

# Stripe setup
stripe_integration.api_key = os.getenv("STRIPE_SECRET_KEY", "sk_live_x9HAiu3vlPPR3jBGBu9cR3dP")
endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_HSQIOLGpb1bJ2jM5QD2VUFBpxa1Iihno")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Models
class PaymentCheckoutSessionRequest(BaseModel):
    email: EmailStr
    plan_id: int


class PaymentResponse(BaseModel):
    payment_id: str
    email: str
    amount: float
    status: str
    session_id: str
    created_at: datetime
    updated_at: datetime


# Initialize payment tables
def init_payment_tables():
    """Initialize payment related database tables"""
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        # Create payments table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                payment_id VARCHAR(100) UNIQUE,
                user_id INTEGER ,
                email VARCHAR(255),
                amount DECIMAL(10,2),
                currency VARCHAR(3),
                status VARCHAR(20),
                session_id VARCHAR(100),
                subscription_id INTEGER ,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        logger.info("Payment tables initialized successfully")

    except Exception as e:
        logger.error(f"Error initializing payment tables: {str(e)}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


@router.post("/create-checkout-session")
async def create_checkout_session(
        request: PaymentCheckoutSessionRequest,
        current_user: dict = Depends(get_current_user),
        conn=Depends(get_db)
):
    try:
        cur = conn.cursor()

        # Get subscription plan details
        cur.execute("""
            SELECT * FROM subscription_plans WHERE id = %s
        """, (request.plan_id,))

        plan = cur.fetchone()
        if not plan:
            raise HTTPException(status_code=404, detail="Subscription plan not found")

        plan_price = plan['price']  # if plan['is_yearly'] else plan['price_monthly']

        # Create Stripe checkout session
        session = stripe_integration.checkout.Session.create(
            customer_email=request.email,
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': plan['name'],
                    },
                    'unit_amount': int(plan_price) * 100,
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f'{BASE_URL}/payments/success',
            cancel_url=f'{BASE_URL}/payments/cancel',
        )

        # Store payment info in database
        cur.execute("""
            INSERT INTO payments (
                payment_id, user_id, email, amount, currency, status, session_id, subscription_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            session.payment_intent,
            current_user['id'],
            request.email,
            plan_price,
            'usd',
            'pending',
            session.id,
            request.plan_id
        ))

        conn.commit()
        # ✅ Notify user: Payment is being processed
        await create_notification(
            user_id=current_user.get("id"),
            title="💳 Payment Processing",
            message=f"Your payment of amount {plan_price} is being processed for plan {plan['name']}. You will be notified once it is confirmed.",
            type="info",
            cat="subscription",
            restaurant_id=None,
            conn=conn
        )

        return {"session": session}

    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating checkout session: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Update imports at the top
import json
from stripe.error import SignatureVerificationError


# ...existing code...

@router.post("/webhook")
async def stripe_webhook(request: Request, conn=Depends(get_db)):
    try:
        payload = await request.body()
        payload_str = payload.decode('utf-8')
        sig_header = request.headers.get('stripe-signature')

        logger.info(f"Received webhook - Signature: {sig_header}")

        if not sig_header:
            raise HTTPException(status_code=400, detail="No signature header")

        try:
            event = stripe_integration.Webhook.construct_event(
                payload=payload_str,
                sig_header=sig_header,
                secret=endpoint_secret
            )
        except ValueError as e:
            logger.error(f"Invalid payload: {str(e)}")
            raise HTTPException(status_code=400, detail="Invalid payload")
        except SignatureVerificationError as e:
            logger.error(f"Invalid signature: {str(e)}")
            raise HTTPException(status_code=400, detail="Invalid signature")

        # Log the event type for debugging
        logger.info(f"Webhook event type: {event.type}")

        # Begin a new database transaction
        cur = conn.cursor()

        if event.type == 'checkout.session.completed':
            session = event.data.object

            # Update payment status
            cur.execute("""
                UPDATE payments 
                SET status = 'completed', updated_at = CURRENT_TIMESTAMP
                WHERE session_id = %s
            """, (session.id,))

            # Ensure that payment session exists
            cur.execute("""
                SELECT * FROM managers WHERE id = (
                    SELECT user_id FROM payments WHERE session_id = %s
                )
            """, (session.id,))

            current_user = cur.fetchone()
            if current_user:
                # Check if there's already an inactive subscription for this user
                cur.execute("""
                    SELECT id FROM public.user_subscriptions 
                    WHERE user_id = %s
                """, (current_user['id'],))
                existing_subscription = cur.fetchone()

                # Delete the existing inactive subscription if it exists
                if existing_subscription:
                    cur.execute("""
                        DELETE FROM public.user_subscriptions WHERE user_id = %s
                    """, (current_user['id'],))

                # Get the subscription plan associated with the payment
                cur.execute("""
                    SELECT * FROM subscription_plans WHERE id = (
                        SELECT subscription_id FROM payments WHERE session_id = %s
                    )
                """, (session.id,))
                PLAN = cur.fetchone()

                if PLAN:
                    is_yearly = PLAN['is_yearly']
                    end_date = datetime.now() + timedelta(days=365 if is_yearly else 30)

                    # Insert the new subscription record
                    cur.execute("""
                        INSERT INTO public.user_subscriptions (
                            user_id, plan_id, end_date, 
                            is_trial, is_yearly, is_active, payment_method_id
                        ) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        current_user['id'],  # user_id
                        PLAN['id'],  # plan_id
                        end_date,  # end_date
                        False,  # is_trial
                        is_yearly,  # is_yearly
                        True,  # is_active
                        1  # payment_method_id (assumed value)
                    ))

            # Commit the transaction after all the operations
            conn.commit()
            await create_notification(
                user_id=current_user.get("id"),
                title="✅ Payment Successful",
                message=f"Your payment of ${PLAN['price']:.2f}  has been successfully processed.",
                type="success",
                cat="subscription",
                restaurant_id=None,
                conn=conn
            )
            await create_notification(
                user_id=current_user.get("id"),
                title="🎉 Subscription Activated",
                message=f"You've successfully subscribed to the **{PLAN['name']}** plan! Enjoy premium features until **{end_date.strftime('%B %d, %Y')}**.",
                type="success",
                cat="subscription",
                restaurant_id=None,
                conn=conn
            )


        elif event.type in ['payment_intent.payment_failed', 'payment_intent.canceled']:
            payment_intent = event.data.object
            status = 'failed' if event.type == 'payment_intent.payment_failed' else 'cancelled'

            cur.execute("""
                UPDATE payments
                SET status = %s, updated_at = CURRENT_TIMESTAMP
                WHERE payment_id = %s
            """, (status, payment_intent.id))

            conn.commit()
            await create_notification(
                user_id=current_user.get("id"),
                title=" Payment Failed",
                message=f"Your payment of ${PLAN['price']:.2f} for the **{PLAN['name']}** plan has been not processed till {end_date}.",
                type="alert",
                cat="subscription",
                restaurant_id=None,
                conn=conn
            )

        return {"status": "success", "event": event.type}

    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        conn.rollback()  # Rollback any changes in case of error
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/payment-history")
async def get_payment_history(
        current_user: dict = Depends(get_current_user),
        conn=Depends(get_db)
):
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT 
                payment_id,
                email,
                amount,
                currency,
                status,
                session_id,
                created_at,
                updated_at
            FROM payments
            WHERE user_id = %s AND email = %s
            ORDER BY created_at DESC
        """, (current_user['id'], current_user['email']))

        payments = cur.fetchall()

        return payments

    except Exception as e:
        logger.error(f"Error retrieving payment history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
