from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, validator
from typing import List, Dict, Optional, Any, Union
from datetime import datetime, timedelta
import logging
import json
import psycopg2
from psycopg2.extras import RealDictCursor

# Import from existing modules
from src.chat_gpt import (
    get_current_user,
    get_db,
    create_notification,
    DB_CONFIG,
    JWT_SECRET,
    JWT_ALGORITHM
)
from src.subscription_management import SubscriptionManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create router for token system integration endpoints
router = APIRouter(
    prefix="/token-system",
    tags=["Token System"],
    responses={404: {"description": "Not found"}}
)

# Models
class EngagementBundleRequest(BaseModel):
    quantity: int
    payment_method_id: Optional[str] = None
    
    @validator('quantity')
    def quantity_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('Quantity must be positive')
        return v

class SystemSettingRequest(BaseModel):
    value: str
    description: Optional[str] = None

# Database initialization
def init_token_system_tables():
    """Initialize token system related database tables"""
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
        logger.info("Token system tables initialized successfully")
    except Exception as e:
        conn.rollback()
        logger.error(f"Error initializing token system tables: {str(e)}")
        raise
    finally:
        conn.close()

class TokenSystemManager:
    """Class to handle token system operations"""
    
    @staticmethod
    async def get_token_usage(user_id: int, conn) -> Dict[str, Any]:
        """Get token usage for a user"""
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Get user's subscription
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
                if subscription.get('is_yearly', False):
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
            cur.execute("""
                SELECT value FROM system_settings
                WHERE key = 'tokens_per_engagement'
            """)
            setting = cur.fetchone()
            tokens_per_engagement = int(setting['value']) if setting else 600
            
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
            usage = await TokenSystemManager.get_token_usage(user_id, conn)
            
            # Get tokens per engagement
            cur.execute("""
                SELECT value FROM system_settings
                WHERE key = 'tokens_per_engagement'
            """)
            setting = cur.fetchone()
            tokens_per_engagement = int(setting['value']) if setting else 600
            
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
            cur.execute("""
                SELECT value FROM system_settings
                WHERE key = 'notification_threshold'
            """)
            threshold_setting = cur.fetchone()
            notification_threshold = float(threshold_setting['value']) if threshold_setting else 0.9
            
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

# API Endpoints
@router.get("/usage")
async def get_token_usage(
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Get token usage for the current user
    
    Returns token usage information including:
    - Tokens used
    - Engagements used
    - Maximum engagements allowed
    - Percentage used
    - Billing cycle dates
    """
    try:
        usage = await TokenSystemManager.get_token_usage(current_user['id'], conn)
        return {
            "status": "success",
            "data": usage
        }
    except HTTPException as e:
        return {
            "status": "error",
            "message": e.detail
        }
    except Exception as e:
        logger.error(f"Error getting token usage: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }

@router.post("/record-engagement")
async def record_engagement(
    engagement_type: str = "standard",
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Record a new engagement for the current user
    
    Each engagement consumes 600 tokens (3 prompts + 3 responses)
    """
    try:
        result = await TokenSystemManager.record_engagement(
            user_id=current_user['id'],
            engagement_type=engagement_type,
            conn=conn
        )
        
        return {
            "status": "success",
            "data": result
        }
    except HTTPException as e:
        return {
            "status": "error",
            "message": e.detail
        }
    except Exception as e:
        logger.error(f"Error recording engagement: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }

@router.post("/purchase-bundle")
async def purchase_engagement_bundle(
    request: EngagementBundleRequest,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Purchase additional engagement bundle
    
    Allows users to purchase additional engagements when they approach their monthly limit
    """
    try:
        result = await TokenSystemManager.purchase_engagement_bundle(
            user_id=current_user['id'],
            quantity=request.quantity,
            payment_method_id=request.payment_method_id,
            conn=conn
        )
        
        return {
            "status": "success",
            "data": result
        }
    except HTTPException as e:
        return {
            "status": "error",
            "message": e.detail
        }
    except Exception as e:
        logger.error(f"Error purchasing engagement bundle: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }

@router.get("/system-settings/{key}")
async def get_system_setting(
    key: str,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Get a system setting value
    """
    try:
        value = await TokenSystemManager.get_system_setting(key, conn)
        
        return {
            "status": "success",
            "data": {
                "key": key,
                "value": value
            }
        }
    except HTTPException as e:
        return {
            "status": "error",
            "message": e.detail
        }
    except Exception as e:
        logger.error(f"Error getting system setting: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }

@router.put("/admin/system-settings/{key}")
async def update_system_setting(
    key: str,
    request: SystemSettingRequest,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Update a system setting (admin only)
    """
    # Check if user is admin
    if current_user.get('role') != 'admin' and current_user.get('role') != 'super_admin':
        return {
            "status": "error",
            "message": "Admin access required"
        }
    
    try:
        result = await TokenSystemManager.update_system_setting(
            key=key,
            value=request.value,
            description=request.description,
            conn=conn
        )
        
        return {
            "status": "success",
            "data": result
        }
    except HTTPException as e:
        return {
            "status": "error",
            "message": e.detail
        }
    except Exception as e:
        logger.error(f"Error updating system setting: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }