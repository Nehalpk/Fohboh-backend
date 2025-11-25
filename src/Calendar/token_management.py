from fastapi import HTTPException, status
from pydantic import BaseModel, validator
from typing import List, Dict, Optional, Any, Union
from datetime import datetime, timedelta
import logging
import json
import psycopg2
from psycopg2.extras import RealDictCursor
import asyncio
from enum import Enum

# Import from existing modules
from src.chat_gpt import (
    get_current_user,
    get_db,
    create_notification,
    DB_CONFIG,
    JWT_SECRET,
    JWT_ALGORITHM
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Models
class TokenUsageCreate(BaseModel):
    user_id: int
    subscription_id: int
    tokens_used: int = 0
    engagements_used: int = 0
    billing_cycle_start: datetime
    billing_cycle_end: datetime

class TokenUsageUpdate(BaseModel):
    tokens_used: Optional[int] = None
    engagements_used: Optional[int] = None
    billing_cycle_start: Optional[datetime] = None
    billing_cycle_end: Optional[datetime] = None

class EngagementBundleCreate(BaseModel):
    user_id: int
    subscription_id: int
    quantity: int
    price: float
    purchase_date: datetime = datetime.now()

class SystemSettingUpdate(BaseModel):
    value: str
    description: Optional[str] = None

# Database initialization
def init_token_tables():
    """Initialize token-related database tables"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Create token_usage table if it doesn't exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                subscription_id INTEGER REFERENCES user_subscriptions(id),
                tokens_used INTEGER DEFAULT 0,
                engagements_used INTEGER DEFAULT 0,
                billing_cycle_start TIMESTAMP WITH TIME ZONE NOT NULL,
                billing_cycle_end TIMESTAMP WITH TIME ZONE NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create engagement_bundles table if it doesn't exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS engagement_bundles (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                subscription_id INTEGER REFERENCES user_subscriptions(id),
                quantity INTEGER NOT NULL,
                price DECIMAL(10, 2) NOT NULL,
                purchase_date TIMESTAMP WITH TIME ZONE NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create engagement_logs table if it doesn't exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS engagement_logs (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                tokens_consumed INTEGER NOT NULL,
                engagement_type VARCHAR(100) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create system_settings table if it doesn't exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                id SERIAL PRIMARY KEY,
                key VARCHAR(100) UNIQUE NOT NULL,
                value TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Insert default system settings if they don't exist
        default_settings = [
            {
                "key": "tokens_per_engagement",
                "value": "600",
                "description": "Number of tokens consumed per engagement (3 prompts + 3 responses)"
            },
            {
                "key": "notification_threshold",
                "value": "0.9",
                "description": "Percentage of usage that triggers notification (90%)"
            },
            {
                "key": "trial_period_days",
                "value": "7",
                "description": "Number of days for free trial"
            },
            {
                "key": "trial_max_engagements",
                "value": "500",
                "description": "Maximum engagements allowed during trial"
            },
            {
                "key": "token_cost_per_1k",
                "value": "0.002",
                "description": "Cost per 1,000 tokens in USD"
            }
        ]
        
        for setting in default_settings:
            cur.execute("""
                INSERT INTO system_settings (key, value, description)
                SELECT %s, %s, %s
                WHERE NOT EXISTS (
                    SELECT 1 FROM system_settings WHERE key = %s
                )
            """, (
                setting["key"], setting["value"], setting["description"], setting["key"]
            ))
        
        # Add max_engagements column to subscription_plans if it doesn't exist
        try:
            cur.execute("""
                ALTER TABLE subscription_plans 
                ADD COLUMN IF NOT EXISTS max_engagements INTEGER DEFAULT 10000
            """)
        except Exception as e:
            logger.error(f"Error adding max_engagements column: {str(e)}")
            # Continue even if this fails
        
        # Add max_engagements_override column to user_subscriptions if it doesn't exist
        try:
            cur.execute("""
                ALTER TABLE user_subscriptions 
                ADD COLUMN IF NOT EXISTS max_engagements_override INTEGER DEFAULT NULL
            """)
        except Exception as e:
            logger.error(f"Error adding max_engagements_override column: {str(e)}")
            # Continue even if this fails
        
        conn.commit()
        logger.info("Token tables initialized successfully")
    except Exception as e:
        conn.rollback()
        logger.error(f"Error initializing token tables: {str(e)}")
        raise
    finally:
        conn.close()

class TokenManager:
    """Class to handle token-related operations"""
    
    @staticmethod
    async def get_system_setting(key: str, conn) -> str:
        """Get a system setting value"""
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            cur.execute("""
                SELECT value FROM system_settings
                WHERE key = %s
            """, (key,))
            
            result = cur.fetchone()
            
            if not result:
                # Return default values for known settings
                defaults = {
                    "tokens_per_engagement": "600",
                    "notification_threshold": "0.9",
                    "trial_period_days": "7",
                    "trial_max_engagements": "500",
                    "token_cost_per_1k": "0.002"
                }
                
                if key in defaults:
                    return defaults[key]
                
                raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")
            
            return result['value']
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting system setting: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def update_system_setting(key: str, value: str, description: Optional[str] = None, conn = None) -> Dict[str, Any]:
        """Update a system setting"""
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Check if setting exists
            cur.execute("""
                SELECT * FROM system_settings
                WHERE key = %s
            """, (key,))
            
            setting = cur.fetchone()
            
            if not setting:
                # Create new setting
                cur.execute("""
                    INSERT INTO system_settings (key, value, description)
                    VALUES (%s, %s, %s)
                    RETURNING *
                """, (key, value, description))
            else:
                # Update existing setting
                if description:
                    cur.execute("""
                        UPDATE system_settings
                        SET value = %s, description = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE key = %s
                        RETURNING *
                    """, (value, description, key))
                else:
                    cur.execute("""
                        UPDATE system_settings
                        SET value = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE key = %s
                        RETURNING *
                    """, (value, key))
            
            updated_setting = cur.fetchone()
            conn.commit()
            
            return dict(updated_setting)
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating system setting: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def get_token_usage(user_id: int, conn) -> Dict[str, Any]:
        """Get token usage for a user"""
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Get user's subscription
            from src.subscription_management import SubscriptionManager
            subscription = await SubscriptionManager.get_user_subscription(user_id, conn)
            
            if not subscription:
                raise HTTPException(status_code=404, detail="No active subscription found")
            
            # Get current token usage for this billing cycle
            cur.execute("""
                SELECT * FROM token_usage
                WHERE user_id = %s AND subscription_id = %s
                AND billing_cycle_start <= CURRENT_TIMESTAMP
                AND billing_cycle_end >= CURRENT_TIMESTAMP
            """, (user_id, subscription['id']))
            
            usage = cur.fetchone()
            
            # If no usage record exists for current billing cycle, create one
            if not usage:
                # Calculate billing cycle dates based on subscription
                start_date = subscription['start_date']
                if subscription['is_yearly']:
                    end_date = start_date + timedelta(days=365)
                else:
                    end_date = start_date + timedelta(days=30)
                
                # Create new usage record
                cur.execute("""
                    INSERT INTO token_usage
                    (user_id, subscription_id, tokens_used, engagements_used, 
                     billing_cycle_start, billing_cycle_end)
                    VALUES (%s, %s, 0, 0, %s, %s)
                    RETURNING *
                """, (user_id, subscription['id'], start_date, end_date))
                
                usage = cur.fetchone()
                conn.commit()
            
            # Get max engagements allowed
            max_engagements = subscription.get('max_engagements_override')
            if not max_engagements:
                # If no override, get from plan
                max_engagements = subscription.get('max_engagements', 10000)
            
            # Calculate percentage used
            engagements_used = usage['engagements_used']
            percentage_used = engagements_used / max_engagements if max_engagements > 0 else 0
            
            # Get tokens per engagement
            tokens_per_engagement = int(await TokenManager.get_system_setting("tokens_per_engagement", conn))
            
            return {
                "user_id": user_id,
                "subscription_id": subscription['id'],
                "tokens_used": usage['tokens_used'],
                "engagements_used": engagements_used,
                "max_engagements": max_engagements,
                "percentage_used": percentage_used,
                "tokens_per_engagement": tokens_per_engagement,
                "billing_cycle_start": usage['billing_cycle_start'],
                "billing_cycle_end": usage['billing_cycle_end'],
                "plan_name": subscription.get('name', 'Unknown Plan'),
                "is_trial": subscription.get('is_trial', False)
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting token usage: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def record_engagement(user_id: int, engagement_type: str, conn) -> Dict[str, Any]:
        """Record a new engagement for a user"""
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Get token usage
            usage = await TokenManager.get_token_usage(user_id, conn)
            
            # Get tokens per engagement
            tokens_per_engagement = int(await TokenManager.get_system_setting("tokens_per_engagement", conn))
            
            # Check if user has reached engagement limit
            if usage['engagements_used'] >= usage['max_engagements']:
                raise HTTPException(
                    status_code=403,
                    detail="You have reached your monthly engagement limit. Please upgrade your plan or purchase additional engagements."
                )
            
            # Update token usage
            cur.execute("""
                UPDATE token_usage
                SET tokens_used = tokens_used + %s,
                    engagements_used = engagements_used + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s AND subscription_id = %s
                AND billing_cycle_start <= CURRENT_TIMESTAMP
                AND billing_cycle_end >= CURRENT_TIMESTAMP
                RETURNING *
            """, (tokens_per_engagement, user_id, usage['subscription_id']))
            
            updated_usage = cur.fetchone()
            
            # Log the engagement
            cur.execute("""
                INSERT INTO engagement_logs
                (user_id, tokens_consumed, engagement_type)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (user_id, tokens_per_engagement, engagement_type))
            
            log_id = cur.fetchone()['id']
            
            # Check if notification threshold reached
            notification_threshold = float(await TokenManager.get_system_setting("notification_threshold", conn))
            new_percentage = (updated_usage['engagements_used'] / usage['max_engagements']) if usage['max_engagements'] > 0 else 0
            
            # Send notification if threshold reached
            notification_sent = False
            if new_percentage >= notification_threshold and usage['percentage_used'] < notification_threshold:
                # Create notification
                await create_notification(
                    user_id=user_id,
                    title="Engagement Limit Approaching",
                    message=f"You've used {int(new_percentage * 100)}% of your monthly engagement allowance. " +
                            f"To ensure uninterrupted service, please consider upgrading your plan or " +
                            f"purchasing additional engagement bundles.",
                    type="warning⚠️",
                    conn=conn
                )
                notification_sent = True
            
            conn.commit()
            
            return {
                "engagement_id": log_id,
                "tokens_consumed": tokens_per_engagement,
                "new_tokens_total": updated_usage['tokens_used'],
                "new_engagements_total": updated_usage['engagements_used'],
                "max_engagements": usage['max_engagements'],
                "percentage_used": new_percentage,
                "notification_sent": notification_sent,
                "engagement_type": engagement_type
            }
        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"Error recording engagement: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def purchase_engagement_bundle(
        user_id: int, 
        quantity: int, 
        payment_method_id: Optional[str] = None,
        conn = None
    ) -> Dict[str, Any]:
        """Purchase additional engagement bundle"""
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Get user's subscription
            from src.subscription_management import SubscriptionManager
            subscription = await SubscriptionManager.get_user_subscription(user_id, conn)
            
            if not subscription:
                raise HTTPException(status_code=404, detail="No active subscription found")
            
            # Calculate price (this would integrate with your pricing model)
            # For now, using a simple calculation
            price_per_engagement = 0.05  # $0.05 per engagement
            total_price = price_per_engagement * quantity
            
            # Record the bundle purchase
            cur.execute("""
                INSERT INTO engagement_bundles
                (user_id, subscription_id, quantity, price, purchase_date)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                RETURNING *
            """, (user_id, subscription['id'], quantity, total_price))
            
            bundle = cur.fetchone()
            
            # Update max_engagements_override in subscription
            current_max = subscription.get('max_engagements_override')
            if not current_max:
                current_max = subscription.get('max_engagements', 10000)
            
            new_max = current_max + quantity
            
            cur.execute("""
                UPDATE user_subscriptions
                SET max_engagements_override = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING *
            """, (new_max, subscription['id']))
            
            updated_subscription = cur.fetchone()
            
            # Add to subscription history
            cur.execute("""
                INSERT INTO subscription_history
                (user_id, plan_id, action, details)
                VALUES (%s, %s, %s, %s)
            """, (
                user_id, 
                subscription['plan_id'], 
                'engagement_bundle_purchased', 
                json.dumps({
                    "bundle_id": bundle['id'],
                    "quantity": quantity,
                    "price": float(total_price),
                    "purchase_date": bundle['purchase_date'].isoformat(),
                    "payment_method_id": payment_method_id
                })
            ))
            
            # Create notification
            await create_notification(
                user_id=user_id,
                title="Additional Engagements Purchased",
                message=f"You have successfully purchased {quantity} additional engagements. " +
                        f"Your new limit is {new_max} engagements.",
                type="success✅",
                conn=conn
            )
            
            conn.commit()
            
            return {
                "bundle_id": bundle['id'],
                "quantity": quantity,
                "price": float(total_price),
                "purchase_date": bundle['purchase_date'],
                "new_max_engagements": new_max
            }
        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"Error purchasing engagement bundle: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def get_engagement_history(
        user_id: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
        conn = None
    ) -> Dict[str, Any]:
        """Get engagement history for a user"""
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Build query
            query = """
                SELECT * FROM engagement_logs
                WHERE user_id = %s
            """
            params = [user_id]
            
            if start_date:
                query += " AND created_at >= %s"
                params.append(start_date)
            
            if end_date:
                query += " AND created_at <= %s"
                params.append(end_date)
            
            query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            
            cur.execute(query, params)
            logs = cur.fetchall()
            
            # Get total count
            count_query = """
                SELECT COUNT(*) as total FROM engagement_logs
                WHERE user_id = %s
            """
            count_params = [user_id]
            
            if start_date:
                count_query += " AND created_at >= %s"
                count_params.append(start_date)
            
            if end_date:
                count_query += " AND created_at <= %s"
                count_params.append(end_date)
            
            cur.execute(count_query, count_params)
            total = cur.fetchone()['total']
            
            return {
                "total": total,
                "limit": limit,
                "offset": offset,
                "logs": [dict(log) for log in logs]
            }
        except Exception as e:
            logger.error(f"Error getting engagement history: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def get_bundle_history(
        user_id: int,
        limit: int = 100,
        offset: int = 0,
        conn = None
    ) -> Dict[str, Any]:
        """Get bundle purchase history for a user"""
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Get bundles
            cur.execute("""
                SELECT * FROM engagement_bundles
                WHERE user_id = %s
                ORDER BY purchase_date DESC
                LIMIT %s OFFSET %s
            """, (user_id, limit, offset))
            
            bundles = cur.fetchall()
            
            # Get total count
            cur.execute("""
                SELECT COUNT(*) as total FROM engagement_bundles
                WHERE user_id = %s
            """, (user_id,))
            
            total = cur.fetchone()['total']
            
            return {
                "total": total,
                "limit": limit,
                "offset": offset,
                "bundles": [dict(bundle) for bundle in bundles]
            }
        except Exception as e:
            logger.error(f"Error getting bundle history: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def reset_usage_counter(user_id: int, conn = None) -> Dict[str, Any]:
        """Reset usage counter for a user (admin only)"""
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Get user's subscription
            from src.subscription_management import SubscriptionManager
            subscription = await SubscriptionManager.get_user_subscription(user_id, conn)
            
            if not subscription:
                raise HTTPException(status_code=404, detail="No active subscription found")
            
            # Reset usage counter
            cur.execute("""
                UPDATE token_usage
                SET tokens_used = 0,
                    engagements_used = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s AND subscription_id = %s
                AND billing_cycle_start <= CURRENT_TIMESTAMP
                AND billing_cycle_end >= CURRENT_TIMESTAMP
                RETURNING *
            """, (user_id, subscription['id']))
            
            updated_usage = cur.fetchone()
            
            if not updated_usage:
                raise HTTPException(status_code=404, detail="No active usage record found")
            
            # Add to subscription history
            cur.execute("""
                INSERT INTO subscription_history
                (user_id, plan_id, action, details)
                VALUES (%s, %s, %s, %s)
            """, (
                user_id, 
                subscription['plan_id'], 
                'usage_counter_reset', 
                json.dumps({
                    "reset_date": datetime.now().isoformat(),
                    "previous_tokens_used": updated_usage['tokens_used'],
                    "previous_engagements_used": updated_usage['engagements_used']
                })
            ))
            
            conn.commit()
            
            return {
                "user_id": user_id,
                "subscription_id": subscription['id'],
                "tokens_used": 0,
                "engagements_used": 0,
                "reset_date": datetime.now()
            }
        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"Error resetting usage counter: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def get_usage_statistics(
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        conn = None
    ) -> Dict[str, Any]:
        """Get usage statistics (admin only)"""
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Build query
            query = """
                SELECT 
                    u.id as user_id,
                    COALESCE(m.email, us.email) as email,
                    COALESCE(m.full_name, us.full_name) as full_name,
                    sp.name as plan_name,
                    tu.tokens_used,
                    tu.engagements_used,
                    COALESCE(s.max_engagements_override, sp.max_engagements) as max_engagements,
                    s.is_trial,
                    s.start_date,
                    s.end_date,
                    tu.billing_cycle_start,
                    tu.billing_cycle_end
                FROM token_usage tu
                JOIN user_subscriptions s ON tu.subscription_id = s.id
                JOIN subscription_plans sp ON s.plan_id = sp.id
                LEFT JOIN (
                    SELECT id, email, full_name FROM managers
                    UNION
                    SELECT id, email, full_name FROM users
                ) u ON tu.user_id = u.id
                LEFT JOIN managers m ON tu.user_id = m.id
                LEFT JOIN users us ON tu.user_id = us.id
                WHERE s.is_active = true
            """
            params = []
            
            if start_date:
                query += " AND tu.created_at >= %s"
                params.append(start_date)
            
            if end_date:
                query += " AND tu.created_at <= %s"
                params.append(end_date)
            
            query += " ORDER BY tu.engagements_used DESC"
            
            cur.execute(query, params)
            usage_data = cur.fetchall()
            
            # Calculate summary statistics
            total_tokens = sum(row['tokens_used'] for row in usage_data)
            total_engagements = sum(row['engagements_used'] for row in usage_data)
            total_users = len(usage_data)
            
            # Group by plan
            plans = {}
            for row in usage_data:
                plan_name = row['plan_name']
                if plan_name not in plans:
                    plans[plan_name] = {
                        "users": 0,
                        "tokens": 0,
                        "engagements": 0
                    }
                
                plans[plan_name]["users"] += 1
                plans[plan_name]["tokens"] += row['tokens_used']
                plans[plan_name]["engagements"] += row['engagements_used']
            
            # Get token cost
            token_cost_per_1k = float(await TokenManager.get_system_setting("token_cost_per_1k", conn))
            total_cost = (total_tokens / 1000) * token_cost_per_1k
            
            return {
                "total_users": total_users,
                "total_tokens": total_tokens,
                "total_engagements": total_engagements,
                "total_cost": total_cost,
                "token_cost_per_1k": token_cost_per_1k,
                "plans": plans,
                "users": [dict(row) for row in usage_data]
            }
        except Exception as e:
            logger.error(f"Error getting usage statistics: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))