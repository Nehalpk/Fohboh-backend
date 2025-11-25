from fastapi import Request, HTTPException, status, Depends
from typing import Optional, Callable, Dict, Any
import logging
from datetime import datetime
import json

# Import from existing modules
from src.chat_gpt import get_current_user, get_db
from src.subscription_management import SubscriptionManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def verify_subscription(
    request: Request,
    call_next,
):
    """
    Middleware to verify subscription status for protected routes.
    
    This middleware checks if the user has an active subscription for routes that require it.
    It also tracks AI engagement usage for relevant endpoints.
    """
    # Define paths that should be checked for subscription
    subscription_required_paths = [
        "/dashboard",  # Dashboard routes
        "/chat",       # Chat routes
        "/rag",        # RAG routes
        "/notes",      # Notes routes
        "/settings",   # Settings routes
        "/upload",     # Upload routes
    ]
    
    # Define paths that should be excluded from subscription checks
    excluded_paths = [
        "/login",
        "/register",
        "/verify",
        "/forgot-password",
        "/reset-password",
        "/subscriptions",  # Subscription management routes should be accessible
    ]
    
    # Define paths that count as AI engagements
    ai_engagement_paths = [
        "/chat",
        "/rag/query",
    ]
    
    # Check if the current path requires subscription verification
    path = request.url.path
    requires_check = any(path.startswith(prefix) for prefix in subscription_required_paths) and \
                    not any(path.startswith(prefix) for prefix in excluded_paths)
    
    # If no check required, proceed with the request
    if not requires_check:
        return await call_next(request)
    
    # Get the authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return await call_next(request)  # Let the auth dependency handle this
    
    try:
        # Get the current user
        token = auth_header.replace("Bearer ", "")
        conn = next(get_db())
        
        # This is a simplified version - in production, you'd use the actual get_current_user function
        # But we need to avoid circular imports
        from src.chat_gpt import JWT_SECRET, JWT_ALGORITHM
        import jwt
        
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        email = payload.get("sub")
        role = payload.get("role")
        
        if not email or not role:
            return await call_next(request)  # Let the auth dependency handle this
        
        cur = conn.cursor()
        
        if role != 'Non_Operators':
            cur.execute("""
                SELECT * FROM managers 
                WHERE email = %s AND active = true
            """, (email,))
            user = cur.fetchone()
        else:
            cur.execute("""
                SELECT * FROM users 
                WHERE email = %s AND active = true
            """, (email,))
            user = cur.fetchone()
        
        if not user:
            return await call_next(request)  # Let the auth dependency handle this
        
        # Check subscription status
        subscription = await SubscriptionManager.get_user_subscription(user['id'], conn)
        
        # If no active subscription, return error
        if not subscription or not subscription['is_active']:
            return JSONResponse(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                content={
                    "status": "error",
                    "detail": "Your subscription is inactive or has expired. Please subscribe to continue using this feature."
                }
            )
        
        # If subscription is in trial mode, check if trial has expired
        if subscription['is_trial'] and subscription['trial_end_date'] < datetime.now():
            # Update subscription to inactive
            cur.execute("""
                UPDATE user_subscriptions
                SET is_active = false, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (subscription['id'],))
            
            conn.commit()
            
            return JSONResponse(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                content={
                    "status": "error",
                    "detail": "Your free trial has expired. Please subscribe to continue using this feature."
                }
            )
        
        # Check if this is an AI engagement path and track usage if needed
        is_ai_engagement = any(path.startswith(prefix) for prefix in ai_engagement_paths)
        
        if is_ai_engagement:
            # Track AI engagement usage
            # We'll do this after the request completes to ensure it was successful
            request.state.track_ai_usage = True
            request.state.user_id = user['id']
        else:
            request.state.track_ai_usage = False
        
        # Proceed with the request
        response = await call_next(request)
        
        # If this was an AI engagement and the request was successful, track usage
        if getattr(request.state, "track_ai_usage", False) and 200 <= response.status_code < 300:
            try:
                await SubscriptionManager.track_usage(
                    user_id=request.state.user_id,
                    usage_type="ai_engagements",
                    count=1,
                    conn=conn
                )
                logger.info(f"Tracked AI engagement for user {request.state.user_id}")
            except Exception as e:
                logger.error(f"Error tracking AI engagement: {str(e)}")
                # Don't fail the request if tracking fails
        
        return response
        
    except Exception as e:
        logger.error(f"Error in subscription middleware: {str(e)}")
        # If there's an error in the middleware, let the request proceed
        # The actual endpoint will handle authentication errors
        return await call_next(request)

# Import this at the end to avoid circular imports
from fastapi.responses import JSONResponse
