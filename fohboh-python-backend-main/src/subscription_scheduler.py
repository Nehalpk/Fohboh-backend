import asyncio
import logging
from datetime import datetime, timedelta
import time
import threading
from typing import Optional, Dict, Any, List
import psycopg2
from psycopg2.extras import RealDictCursor

# Import from existing modules
from src.chat_gpt import get_db, create_notification ,DB_CONFIG
from src.subscription_management import SubscriptionManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SubscriptionScheduler:
    """
    Scheduler for subscription-related tasks
    
    This class handles scheduled tasks like processing trial expirations,
    sending reminders, and handling subscription renewals.
    """
    
    def __init__(self, interval_hours: int = 24):
        """
        Initialize the scheduler
        
        Args:
            interval_hours: How often to run the scheduled tasks (in hours)
        """
        self.interval_hours = interval_hours
        self.running = False
        self.thread = None
    
    def start(self):
        """Start the scheduler in a background thread"""
        if self.running:
            logger.warning("Scheduler is already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        logger.info(f"Subscription scheduler started with {self.interval_hours}h interval")
    
    def stop(self):
        """Stop the scheduler"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
            logger.info("Subscription scheduler stopped")
    
    def _run_scheduler(self):
        """Run the scheduler loop"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        while self.running:
            try:
                # Run the scheduled tasks
                loop.run_until_complete(self._process_scheduled_tasks())
                
                # Sleep until next interval
                for _ in range(self.interval_hours * 60 * 60):
                    if not self.running:
                        break
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Error in subscription scheduler: {str(e)}")
                # Sleep for a shorter time if there was an error
                time.sleep(60)
    
    async def _process_scheduled_tasks(self):
        """Process all scheduled subscription tasks"""
        logger.info("Running scheduled subscription tasks")
        
        try:
            # Process trial expirations
            await self._process_trial_expirations()
            
            # Process subscription renewals
            await self._process_subscription_renewals()
            
            # Send trial reminders
            await self._send_trial_reminders()
            
            # Reset usage counters for new billing periods
            await self._reset_usage_counters()
            
            logger.info("Completed scheduled subscription tasks")
        except Exception as e:
            raise
        except Exception as e:
            logger.error(f"Error processing scheduled tasks: {str(e)}")
    
    async def _process_trial_expirations(self):
        """Process expired trials"""
        try:
            # conn = next(get_db())
            # cur = conn.cursor()
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()
            
            # Find trials that have expired
            cur.execute("""
                SELECT us.*, m.email as user_email, m.full_name as user_name
                FROM user_subscriptions us
                LEFT JOIN managers m ON us.user_id = m.id
                WHERE us.is_trial = true 
                AND us.is_active = true
                AND us.trial_end_date <= CURRENT_TIMESTAMP
            """)
            
            expired_trials = cur.fetchall()
            logger.info(f"Found {len(expired_trials)} expired trials")
            
            for trial in expired_trials:
                # Update subscription to inactive
                cur.execute("""
                    UPDATE user_subscriptions
                    SET is_active = false, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (trial['id'],))
                
                # Add to subscription history
                cur.execute("""
                    INSERT INTO subscription_history
                    (user_id, plan_id, action, details)
                    VALUES (%s, %s, %s, %s)
                """, (
                    trial['user_id'], 
                    trial['plan_id'], 
                    'trial_expired', 
                    '{"expired_at": "' + datetime.now().isoformat() + '"}'
                ))
                
                # Send notification about trial expiration
                await create_notification(
                    user_id=trial['user_id'],
                    title="Trial Expired",
                    message="🚨 Your free trial has expired. Subscribe now to continue using premium features.",
                    type="alert",
                    cat = "subscription",
                    conn=conn
                )
                
                logger.info(f"Processed expired trial for user {trial['user_id']} ({trial.get('user_email', 'unknown')})")
            
            conn.commit()
        except Exception as e:
            if 'conn' in locals():
                conn.rollback()
            logger.error(f"Error processing trial expirations: {str(e)}")
    
    async def _process_subscription_renewals(self):
        """Process subscription renewals"""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()
            
            # Find subscriptions due for renewal
            cur.execute("""
                SELECT us.*, sp.name as plan_name, sp.price_monthly, sp.price_yearly,
                       m.email as user_email, m.full_name as user_name
                FROM user_subscriptions us
                JOIN subscription_plans sp ON us.plan_id = sp.id
                LEFT JOIN managers m ON us.user_id = m.id
                WHERE us.is_active = true
                AND us.is_trial = false
                AND us.auto_renew = true
                AND us.end_date <= CURRENT_TIMESTAMP
            """)
            
            renewals = cur.fetchall()
            logger.info(f"Found {len(renewals)} subscriptions due for renewal")
            
            for renewal in renewals:
                # Calculate new end date
                start_date = datetime.now()
                if renewal['is_yearly']:
                    end_date = start_date + timedelta(days=365)
                    price = renewal['price_yearly']
                else:
                    end_date = start_date + timedelta(days=30)
                    price = renewal['price_monthly']
                
                # Update subscription with new dates
                cur.execute("""
                    UPDATE user_subscriptions
                    SET start_date = %s, end_date = %s, 
                        last_payment_date = CURRENT_TIMESTAMP,
                        next_payment_date = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING *
                """, (start_date, end_date, end_date, renewal['id']))
                
                updated_subscription = cur.fetchone()
                
                # Add to subscription history
                cur.execute("""
                    INSERT INTO subscription_history
                    (user_id, plan_id, action, details)
                    VALUES (%s, %s, %s, %s)
                """, (
                    renewal['user_id'], 
                    renewal['plan_id'], 
                    'subscription_renewed', 
                    '{"renewed_at": "' + datetime.now().isoformat() + 
                    '", "price": ' + str(price) + 
                    ', "is_yearly": ' + str(renewal['is_yearly']).lower() + 
                    ', "new_end_date": "' + end_date.isoformat() + '"}'
                ))
                
                # Send notification about renewal
                await create_notification(
                    user_id=renewal['user_id'],
                    title="Subscription Renewed",
                    message=f"📢 Your subscription to the {renewal['plan_name']} plan has been renewed. " +
                            f"Your next billing date is {end_date.strftime('%Y-%m-%d')}.",
                    type="info",
                    cat = "subscription",
                    conn=conn
                )
                
                logger.info(f"Renewed subscription for user {renewal['user_id']} ({renewal.get('user_email', 'unknown')})")
            
            conn.commit()
        except Exception as e:
            if 'conn' in locals():
                conn.rollback()
            logger.error(f"Error processing subscription renewals: {str(e)}")
    
    async def _send_trial_reminders(self):
        """Send reminders for trials that are about to expire"""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Find trials expiring in the next 3 days
            cur.execute("""
                SELECT us.*, sp.name as plan_name,
                       m.email as user_email, m.full_name as user_name,
                       EXTRACT(DAY FROM (us.trial_end_date - CURRENT_TIMESTAMP)) as days_remaining
                FROM user_subscriptions us
                JOIN subscription_plans sp ON us.plan_id = sp.id
                LEFT JOIN managers m ON us.user_id = m.id
                WHERE us.is_trial = true 
                AND us.is_active = true
                AND us.trial_end_date > CURRENT_TIMESTAMP
                AND us.trial_end_date <= CURRENT_TIMESTAMP + INTERVAL '3 days'
            """)
            
            expiring_trials = cur.fetchall()
            # logger.info(f"Trial record expiring_trials: {expiring_trials}") 

            logger.info(f"Found {len(expiring_trials)} trials expiring soon")

            days_remaining = int(expiring_trials[0]['days_remaining'])

            logger.info(f"Trial record@@@@@@@@@@@@@@@@@@: {days_remaining[0], expiring_trials[0]['user_id'][0]},")  # Will show if it's a dict or tuple   [0]['days_remaining']

                
                # Create notification message based on days remaining
            if days_remaining <= 1:
                    title = "Trial Ending Tomorrow"
                    message = "⚠️ Your free trial ends tomorrow. Subscribe now to avoid losing access to premium features."
                    notification_type = "warning"
            else:
                    title = f"Trial Ending Soon: {days_remaining} Days Left"
                    message = f"⚠️ Your free trial ends in {days_remaining} days. Subscribe now to continue using premium features."
                    notification_type = "warning"
                
                # Send notification
            await create_notification(
                    user_id=expiring_trials[0]['user_id'],
                    title=title,
                    message=message,
                    type=notification_type,
                    cat = "subscription",
                    conn=conn
                )
                
            logger.info(f"Sent trial expiration reminder to user {expiring_trials[0]['user_id']} ({expiring_trials[0].get('user_email', 'unknown')})")
            
            # for trial in expiring_trials:
            #     days_remaining = int(trial['days_remaining'])

            #     logger.debug(f"Trial record: {trial}")  # Will show if it's a dict or tuple   [0]['days_remaining']

                
            #     # Create notification message based on days remaining
            #     if days_remaining <= 1:
            #         title = "Trial Ending Tomorrow"
            #         message = "⚠️ Your free trial ends tomorrow. Subscribe now to avoid losing access to premium features."
            #         notification_type = "warning"
            #     else:
            #         title = f"Trial Ending Soon: {days_remaining} Days Left"
            #         message = f"⚠️ Your free trial ends in {days_remaining} days. Subscribe now to continue using premium features."
            #         notification_type = "warning"
                
            #     # Send notification
            #     await create_notification(
            #         user_id=trial['user_id'],
            #         title=title,
            #         message=message,
            #         type=notification_type,
            #         conn=conn
            #     )
                
            #     logger.info(f"Sent trial expiration reminder to user {trial['user_id']} ({trial.get('user_email', 'unknown')})")
            
            conn.commit()
        except Exception as e:
            raise
        except Exception as e:
            if 'conn' in locals():
                conn.rollback()
            logger.error(f"Error sending trial reminders: {str(e)}")
    
    async def _reset_usage_counters(self):
        """Reset usage counters for new billing periods"""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()
            
            # Find usage records that need to be reset
            cur.execute("""
                SELECT su.*, us.user_id, us.end_date
                FROM subscription_usage su
                JOIN user_subscriptions us ON su.subscription_id = us.id
                WHERE su.reset_date <= CURRENT_TIMESTAMP
                AND us.is_active = true
            """)
            
            usage_records = cur.fetchall()
            logger.info(f"Found {len(usage_records)} usage records to reset")
            
            for record in usage_records:
                # Calculate next reset date
                next_reset = record['end_date']
                
                # Reset usage counter
                cur.execute("""
                    UPDATE subscription_usage
                    SET usage_count = 0, 
                        reset_date = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (next_reset, record['id']))
                
                logger.info(f"Reset usage counter for user {record['user_id']}, type: {record['usage_type']}")
            
            conn.commit()
        except Exception as e:
            if 'conn' in locals():
                conn.rollback()
            logger.error(f"Error resetting usage counters: {str(e)}")

# Create a singleton instance
subscription_scheduler = SubscriptionScheduler()

# Function to start the scheduler
def start_subscription_scheduler():
    """Start the subscription scheduler"""
    subscription_scheduler.start()

# Export the scheduler instance and start function
__all__ = ['subscription_scheduler', 'start_subscription_scheduler']
