from fastapi import Request, HTTPException, status
from typing import Optional, Callable, Dict, Any
import logging
from datetime import datetime
import json

# Import from existing modules
from src.chat_gpt import get_current_user, get_db
from src.token_system_integration import TokenSystemManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def token_usage_middleware(
    request: Request,
    call_next
):
    """
    Middleware to track token usage for API requests
    
    This middleware checks if the user has enough tokens for token-consuming endpoints
    and records token usage after successful requests.
    """
    # Define paths that consume tokens
    token_consuming_paths = [
        "/chat",       # Chat endpoints
        "/rag/query",  # RAG query endpoints
        "/dashboard",  # Dashboard endpoints
        "/analyze",    # Analysis endpoints
        "/generate"    # Generation endpoints
    ]
    
    # Define paths that should be excluded from token checks
    excluded_paths = [
        "/login",
        "/register",
        "/verify",
        "/forgot-password",
        "/reset-password",
        "/token-system",  # Token system management endpoints
        "/subscriptions", # Subscription management endpoints
        "/static",        # Static files
        "/docs",          # API documentation
        "/redoc",         # API documentation
        "/openapi.json"   # OpenAPI schema
    ]
    
    # Check if the current path consumes tokens
    path = request.url.path
    consumes_tokens = any(path.startswith(prefix) for prefix in token_consuming_paths)
    excluded = any(path.startswith(prefix) for prefix in excluded_paths)
    
    # If path doesn't consume tokens or is excluded, proceed with the request
    if not consumes_tokens or excluded:
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
        
        # Check token usage
        try:
            usage = await TokenSystemManager.get_token_usage(user['id'], conn)
            
            # Check if user has reached token limit
            if usage['engagements_used'] >= usage['max_engagements']:
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={
                        "status": "error",
                        "message": "You have reached your monthly engagement limit. Please upgrade your plan or purchase additional engagements."
                    }
                )
            
            # Store user_id in request state for later use
            request.state.user_id = user['id']
            request.state.track_token_usage = True
            
        except Exception as e:
            logger.error(f"Error checking token usage: {str(e)}")
            # If there's an error checking token usage, let the request proceed
            # The actual endpoint will handle any issues
        
        # Process the request
        response = await call_next(request)
        
        # If request was successful and we should track token usage, record the engagement
        if (response.status_code < 400 and 
            getattr(request.state, "track_token_usage", False) and 
            hasattr(request.state, "user_id")):
            try:
                # Determine engagement type based on path
                engagement_type = "api_request"
                if path.startswith("/chat"):
                    engagement_type = "chat"
                elif path.startswith("/rag/query"):
                    engagement_type = "rag_query"
                elif path.startswith("/dashboard"):
                    engagement_type = "dashboard"
                elif path.startswith("/analyze"):
                    engagement_type = "analysis"
                elif path.startswith("/generate"):
                    engagement_type = "generation"
                
                # Record the engagement asynchronously
                import asyncio
                asyncio.create_task(
                    TokenSystemManager.record_engagement(
                        user_id=request.state.user_id,
                        engagement_type=engagement_type,
                        conn=conn
                    )
                )
                
                logger.info(f"Recorded token usage for user {request.state.user_id} - path: {path}")
            except Exception as e:
                logger.error(f"Error recording token usage: {str(e)}")
                # Don't affect the response if there's an error recording usage
        
        return response
        
    except Exception as e:
        logger.error(f"Error in token usage middleware: {str(e)}")
        # If there's an error in the middleware, let the request proceed
        # The actual endpoint will handle any issues
        return await call_next(request)
