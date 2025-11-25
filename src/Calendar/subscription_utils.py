from fastapi import HTTPException, status, Depends
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import logging
import json
import asyncio
from functools import wraps

# Import from existing modules
from src.chat_gpt import get_current_user, get_db, create_notification
from src.subscription_management import SubscriptionManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def check_subscription_feature(
    user_id: int,
    feature_name: str,
    conn = None
) -> bool:
    """
    Check if a user's subscription includes a specific feature
    
    Args:
        user_id: The user ID to check
        feature_name: The name of the feature to check
        conn: Database connection
        
    Returns:
        True if the feature is available, False otherwise
    """
    try:
        # Get user's subscription
        subscription = await SubscriptionManager.get_user_subscription(user_id, conn)
        
        if not subscription or not subscription['is_active']:
            return False
        
        # Parse features JSON
        features = []
        if 'features' in subscription and subscription['features']:
            if isinstance(subscription['features'], str):
                features = json.loads(subscription['features'])
            else:
                features = subscription['features']
        
        # Check if feature is enabled
        for feature in features:
            if feature.get('name') == feature_name and feature.get('enabled', False):
                return True
        
        return False
    except Exception as e:
        logger.error(f"Error checking subscription feature: {str(e)}")
        return False

async def check_subscription_limit(
    user_id: int,
    limit_type: str,
    conn = None
) -> Dict[str, Any]:
    """
    Check if a user has exceeded a subscription limit
    
    Args:
        user_id: The user ID to check
        limit_type: The type of limit to check (e.g., 'ai_engagements', 'restaurants', 'integrations')
        conn: Database connection
        
    Returns:
        Dictionary with limit information
    """
    try:
        return await SubscriptionManager.check_subscription_limits(user_id, limit_type, conn)
    except Exception as e:
        logger.error(f"Error checking subscription limit: {str(e)}")
        return {
            "limit_exceeded": True,  # Assume exceeded on error to be safe
            "current_usage": 0,
            "limit": 0
        }

async def track_feature_usage(
    user_id: int,
    usage_type: str,
    count: int = 1,
    conn = None
) -> Dict[str, Any]:
    """
    Track usage of a subscription feature
    
    Args:
        user_id: The user ID
        usage_type: The type of usage to track (e.g., 'ai_engagements', 'restaurants', 'integrations')
        count: The amount to increment usage by
        conn: Database connection
        
    Returns:
        Dictionary with usage information
    """
    try:
        return await SubscriptionManager.track_usage(user_id, usage_type, count, conn)
    except Exception as e:
        logger.error(f"Error tracking feature usage: {str(e)}")
        return None

async def get_trial_status(
    user_id: int,
    conn = None
) -> Dict[str, Any]:
    """
    Get the status of a user's trial
    
    Args:
        user_id: The user ID
        conn: Database connection
        
    Returns:
        Dictionary with trial status information
    """
    try:
        subscription = await SubscriptionManager.get_user_subscription(user_id, conn)
        
        if not subscription:
            return {
                "has_trial": False,
                "is_active": False,
                "days_remaining": 0
            }
        
        is_trial = subscription.get('is_trial', False)
        is_active = subscription.get('is_active', False)
        
        days_remaining = 0
        if is_trial and is_active and subscription.get('trial_end_date'):
            days_remaining = (subscription['trial_end_date'] - datetime.now()).days
            if days_remaining < 0:
                days_remaining = 0
        
        return {
            "has_trial": is_trial,
            "is_active": is_active,
            "days_remaining": days_remaining,
            "trial_end_date": subscription.get('trial_end_date').isoformat() if subscription.get('trial_end_date') else None
        }
    except Exception as e:
        logger.error(f"Error getting trial status: {str(e)}")
        return {
            "has_trial": False,
            "is_active": False,
            "days_remaining": 0
        }

async def send_trial_reminder(
    user_id: int,
    days_remaining: int,
    conn = None
) -> bool:
    """
    Send a reminder notification about trial expiration
    
    Args:
        user_id: The user ID
        days_remaining: Number of days remaining in trial
        conn: Database connection
        
    Returns:
        True if notification was sent, False otherwise
    """
    try:
        # Get user details
        cur = conn.cursor()
        
        cur.execute("""
            SELECT email, full_name FROM managers WHERE id = %s
            UNION
            SELECT email, full_name FROM users WHERE id = %s
        """, (user_id, user_id))
        
        user = cur.fetchone()
        
        if not user:
            return False
        
        # Create notification message based on days remaining
        if days_remaining <= 0:
            title = "Trial Expired"
            message = "Your free trial has expired. Subscribe now to continue using premium features."
            notification_type = "alert🚨"
        elif days_remaining == 1:
            title = "Trial Ending Tomorrow"
            message = "Your free trial ends tomorrow. Subscribe now to avoid losing access to premium features."
            notification_type = "warning⚠️"
        elif days_remaining <= 3:
            title = f"Trial Ending Soon: {days_remaining} Days Left"
            message = f"Your free trial ends in {days_remaining} days. Subscribe now to continue using premium features."
            notification_type = "warning⚠️"
        else:
            title = f"Trial Status: {days_remaining} Days Remaining"
            message = f"You have {days_remaining} days left in your free trial. Enjoy all premium features!"
            notification_type = "info📢"
        
        # Send notification
        await create_notification(
            user_id=user_id,
            title=title,
            message=message,
            type=notification_type,
            cat = "subscription",
            conn=conn
        )
        
        return True
    except Exception as e:
        logger.error(f"Error sending trial reminder: {str(e)}")
        return False

def require_subscription_feature(feature_name: str):
    """
    Decorator to require a specific subscription feature for an endpoint
    
    Args:
        feature_name: The name of the feature to require
        
    Returns:
        Decorator function
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Get current user from kwargs
            current_user = kwargs.get('current_user')
            conn = kwargs.get('conn')
            
            if not current_user or not conn:
                # If dependencies aren't available, proceed with the function
                # The actual endpoint will handle authentication errors
                return await func(*args, **kwargs)
            
            # Check if user has the required feature
            has_feature = await check_subscription_feature(
                user_id=current_user['id'],
                feature_name=feature_name,
                conn=conn
            )
            
            if not has_feature:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Your subscription does not include the '{feature_name}' feature"
                )
            
            # Proceed with the function
            return await func(*args, **kwargs)
        
        return wrapper
    
    return decorator

def require_subscription_limit(limit_type: str):
    """
    Decorator to check a subscription limit for an endpoint
    
    Args:
        limit_type: The type of limit to check
        
    Returns:
        Decorator function
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Get current user from kwargs
            current_user = kwargs.get('current_user')
            conn = kwargs.get('conn')
            
            if not current_user or not conn:
                # If dependencies aren't available, proceed with the function
                # The actual endpoint will handle authentication errors
                return await func(*args, **kwargs)
            
            # Check if user has exceeded the limit
            limit_check = await check_subscription_limit(
                user_id=current_user['id'],
                limit_type=limit_type,
                conn=conn
            )
            
            if limit_check.get('limit_exceeded', False):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"You have reached your {limit_type.replace('_', ' ')} limit. Please upgrade your subscription."
                )
            
            # Track usage after the function completes
            result = await func(*args, **kwargs)
            
            # Track usage asynchronously
            asyncio.create_task(
                track_feature_usage(
                    user_id=current_user['id'],
                    usage_type=limit_type,
                    count=1,
                    conn=conn
                )
            )
            
            return result
        
        return wrapper
    
    return decorator

# Export utility functions
__all__ = [
    'check_subscription_feature',
    'check_subscription_limit',
    'track_feature_usage',
    'get_trial_status',
    'send_trial_reminder',
    'require_subscription_feature',
    'require_subscription_limit'
]