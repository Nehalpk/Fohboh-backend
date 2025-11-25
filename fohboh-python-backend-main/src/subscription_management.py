from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, validator
from typing import List, Dict, Optional, Any, Union
from datetime import datetime, timedelta
import logging
import json
import uuid
import psycopg2
from psycopg2.extras import RealDictCursor
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

# Create router for subscription endpoints
router = APIRouter(
    prefix="/subscriptions",
    tags=["Subscription Management"],
    responses={404: {"description": "Not found"}}
)

# Models
class SubscriptionTier(str, Enum):
    FREE_TRIAL = "FREE_TRIAL"
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"
    ENTERPRISE = "ENTERPRISE"

class SubscriptionFeature(BaseModel):
    name: str
    description: str
    enabled: bool = True

class SubscriptionPlanCreate(BaseModel):
    name: str
    description: str
    price_monthly: float
    price_yearly: float
    features: List[Dict[str, Any]]
    max_users_per_location: int
    max_ai_engagements: int
    max_restaurants: int
    max_integrations: int 
    trial_days: int = 7  # Default trial period
    role: str # Role associated with the plan (e.g., "manager", "admin", etc.)

class SubscriptionPlanUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price_monthly: Optional[float] = None
    price_yearly: Optional[float] = None
    features: Optional[List[Dict[str, Any]]] = None
    max_users_per_location: Optional[int] = None
    max_ai_engagements: Optional[int] = None
    max_restaurants: Optional[int] = None
    max_integrations: Optional[int] = None
    trial_days: Optional[int] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None

class UserSubscriptionCreate(BaseModel):
    user_id: int
    plan_id: int
    payment_method_id: Optional[str] = None
    is_yearly: bool = False
    auto_renew: bool = True

class UserSubscriptionUpdate(BaseModel):
    plan_id: Optional[int] = None
    payment_method_id: Optional[str] = None
    is_yearly: Optional[bool] = None
    auto_renew: Optional[bool] = None
    is_active: Optional[bool] = None

class PaymentMethodCreate(BaseModel):
    user_id: int
    payment_type: str  # e.g., "credit_card", "paypal", etc.
    payment_details: Dict[str, Any]  # Encrypted payment details
    is_default: bool = False

# Database initialization
def init_subscription_tables():
    """Initialize subscription-related database tables"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Create subscription_plans table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS subscription_plans (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                is_yearly BOOLEAN DEFAULT false,
                role VARCHAR(50) NOT NULL DEFAULT 'OPERATOR',
                price DECIMAL(10, 2) NOT NULL,
                features JSONB NOT NULL,
                max_users_per_location INTEGER NOT NULL,
                max_ai_engagements INTEGER NOT NULL,
                max_restaurants INTEGER NOT NULL,
                max_integrations INTEGER NOT NULL,
                trial_days INTEGER NOT NULL DEFAULT 7,
                is_active BOOLEAN DEFAULT true,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create user_subscriptions table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_subscriptions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                plan_id INTEGER REFERENCES subscription_plans(id) ON DELETE CASCADE,
                start_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                end_date TIMESTAMP WITH TIME ZONE,
                trial_end_date TIMESTAMP WITH TIME ZONE,
                is_trial BOOLEAN DEFAULT true,
                is_yearly BOOLEAN DEFAULT false,
                auto_renew BOOLEAN DEFAULT true,
                is_active BOOLEAN DEFAULT true,
                payment_method_id INTEGER,
                last_payment_date TIMESTAMP WITH TIME ZONE,
                next_payment_date TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id)
            )
        """)
        
        # Create payment_methods table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payment_methods (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                payment_type VARCHAR(50) NOT NULL,
                payment_details JSONB NOT NULL,
                is_default BOOLEAN DEFAULT false,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create subscription_usage table to track AI engagements
        cur.execute("""
                CREATE TABLE IF NOT EXISTS subscription_usage (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    subscription_id INTEGER REFERENCES user_subscriptions(id) ON DELETE CASCADE,
                    usage_type VARCHAR(50) NOT NULL,
                    usage_count INTEGER DEFAULT 0,
                    reset_date TIMESTAMP WITH TIME ZONE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

                    used_users_per_location INTEGER DEFAULT 0,  
                    used_ai_engagements INTEGER DEFAULT 0,      
                    used_restaurants INTEGER DEFAULT 0,         
                    used_integrations INTEGER DEFAULT 0,
                    UNIQUE(user_id)         
                )
            """)

        
        # Create subscription_history table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS subscription_history (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                plan_id INTEGER REFERENCES subscription_plans(id) ON DELETE CASCADE,
                action VARCHAR(50) NOT NULL,
                details JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Insert default subscription plans if they don't exist
        default_plans = [
            {
                "name": "Free Trial",
                "description": "7-day free trial with full access to all features",
                "role": "OPERATOR",
                "is_yearly": False,
                "price": 0,
                
                "features": json.dumps([
                    {"name": "9 users per location", "enabled": True},
                    {"name": "Up to 10 AI engagements/mo./location", "enabled": True},
                    {"name": "Supervise up to 3 restaurants", "enabled": True},
                    {"name": "Up to 1 integrations", "enabled": True},
                    {"name": "AI Voice Notes & Journal", "enabled": True},
                    {"name": "AI-automated operational prompts", "enabled": True},
                    {"name": "Visual insights board", "enabled": True},
                    {"name": "CSV data file uploads", "enabled": True},
                    {"name": "Access chat history", "enabled": True},
                    {"name": "Document Uploads", "enabled": True},
                    {"name": "Multi-role-based permissions", "enabled": True},
                    {"name": "Onboarding assistance", "enabled": True},
                    {"name": "AI supported and live ticketed support", "enabled": True},
                    {"name": "Early access to AI Companion Agents", "enabled": True}
                ]),
                "max_users_per_location": 2,  # Unlimited
                "max_ai_engagements": 10,
                "max_restaurants": 3,
                "max_integrations": 1,
                "trial_days": 7
            },
            {
                "name": "Basic Plan",
                "description": "7-Day Limited Free Trial for Independent Operators. Core FohBoh Cortexâ„¢ Capabilities, Plus",
                "role": "OPERATOR",
                "is_yearly": False,
                "price": 99.00,
                
                "features": json.dumps([
                    {"name": "Unlimited users per location", "enabled": True},
                    {"name": "Up to 2,500 AI engagements/mo./location", "enabled": True},
                    {"name": "Supervise up to 10 restaurants", "enabled": True},
                    {"name": "1 POS integration via API", "enabled": True},
                    {"name": "AI-automated operational prompts", "enabled": True},
                    {"name": "Visual insights board", "enabled": True},
                    {"name": "CSV data file uploads", "enabled": True},
                    {"name": "Access chat history", "enabled": True},
                    {"name": "Role-based permissions", "enabled": True},
                    {"name": "Onboarding assistance", "enabled": True},
                    {"name": "AI supported and live ticketed support", "enabled": True}
                ]),
                "max_users_per_location": 10,  # Unlimited
                "max_ai_engagements": 2500,
                "max_restaurants": 10,
                "max_integrations": 1,
                "trial_days": 7
            },
            {
                "name": "Premium Plan",
                "description": "Built for power users and chain operators. Core FohBoh Cortexâ„¢ Capabilities, Plus",
                "role": "OPERATOR",
                "is_yearly": False,
                "price": 149.00,
                
                "features": json.dumps([
                    {"name": "Unlimited users per location", "enabled": True},
                    {"name": "Up to 7,500 AI engagements/mo./location", "enabled": True},
                    {"name": "Supervise up to 25 restaurants", "enabled": True},
                    {"name": "Up to 2 integrations (e.g. POS and HR)", "enabled": True},
                    {"name": "AI Voice Notes & Journal", "enabled": True},
                    {"name": "AI-automated operational prompts", "enabled": True},
                    {"name": "Visual insights board", "enabled": True},
                    {"name": "CSV data file uploads", "enabled": True},
                    {"name": "Access chat history", "enabled": True},
                    {"name": "Document Uploads (e.g. inventory, recipes, SOPs)", "enabled": True},
                    {"name": "Multi-role-based permissions", "enabled": True},
                    {"name": "Onboarding assistance", "enabled": True},
                    {"name": "AI supported and live ticketed support", "enabled": True}
                ]),
                "max_users_per_location": 25,  # Unlimited
                "max_ai_engagements": 7500,
                "max_restaurants": 25,
                "max_integrations": 2,
                "trial_days": 0
            },
            {
                "name": "Pro Plan",
                "description": "Built for dynamic power users and chain operators. Core FohBoh Cortexâ„¢ Capabilities, Plus",
                "role": "OPERATOR",
                "is_yearly": False,
                "price": 199.00,
                
                "features": json.dumps([
                    {"name": "Unlimited users per location", "enabled": True},
                    {"name": "Up to 10,000 AI engagements/mo./location", "enabled": True},
                    {"name": "Supervise up to 50 restaurants", "enabled": True},
                    {"name": "Up to 4 integrations (e.g.POS, HR, Inventory)", "enabled": True},
                    {"name": "AI Voice Notes & Journal", "enabled": True},
                    {"name": "AI-automated operational prompts", "enabled": True},
                    {"name": "Visual insights board", "enabled": True},
                    {"name": "CSV data file uploads", "enabled": True},
                    {"name": "Access chat history", "enabled": True},
                    {"name": "Document Uploads (e.g. inventory, recipes, SOPs)", "enabled": True},
                    {"name": "Multi-role-based permissions", "enabled": True},
                    {"name": "Onboarding assistance", "enabled": True},
                    {"name": "AI supported and live ticketed support", "enabled": True},
                    {"name": "Early access to AI Companion Agents access (e.g., PrepList, LaborSmart)", "enabled": True}
                ]),
                "max_users_per_location": 50,  # Unlimited
                "max_ai_engagements": 10000,
                "max_restaurants": 50,
                "max_integrations": 4,
                "trial_days": 0
            },
            {
                "name": "Basic Plan",
                "description": "7-Day Limited Free Trial Single User. Core FohBoh Cortexâ„¢ Capabilities, Plus",
                "role": "Non_Operators",
                "is_yearly": False,
                "price": 39.00,
                
                "features": json.dumps([
                    {"name": "Up to 1,150 AI engagements/mo.", "enabled": True},
                    {"name": "Restaurant-specific prompting", "enabled": True},
                    {"name": "Access to industry documents", "enabled": True},
                    {"name": "Read-only AI data interactions", "enabled": True},
                    {"name": "Limited access to chat history", "enabled": True},
                    {"name": "Community prompt library", "enabled": True},
                    {"name": "AI-supported chatbot support", "enabled": True}
                ]),
                "max_users_per_location": 1,
                "max_ai_engagements": 1150,
                "max_restaurants": 1,
                "max_integrations": 0,
                "trial_days": 7
            },
            {
                "name": "Premium Plan",
                "description": "7-Day Limited Free Trial Single User. Core FohBoh Cortexâ„¢ Capabilities, Plus",
                "role": "Non_Operators",
                "is_yearly": False,
                "price": 89.99,
                
                "features": json.dumps([
                    {"name": "Up to 2,250 AI engagements/mo.", "enabled": True},
                    {"name": "Restaurant-specific prompting", "enabled": True},
                    {"name": "Access to industry documents", "enabled": True},
                    {"name": "Read-only AI data interactions", "enabled": True},
                    {"name": "Community prompt library", "enabled": True},
                    {"name": "Access chat history", "enabled": True},
                    {"name": "AI supported and live ticketed support", "enabled": True}
                ]),
                "max_users_per_location": 1,
                "max_ai_engagements": 2250,
                "max_restaurants": 1,
                "max_integrations": 0,
                "trial_days": 7
            },
            {
                "name": "Basic",
                "description": "7-Day Limited Free Trial for Independent Operators. Core FohBoh Cortexâ„¢ Capabilities, Plus",
                "role": "OPERATOR",
                "is_yearly": True,
                
                "price": 995.00,
                "features": json.dumps([
                    {"name": "Unlimited users per location", "enabled": True},
                    {"name": "Up to 2,500 AI engagements/mo./location", "enabled": True},
                    {"name": "Supervise up to 10 restaurants", "enabled": True},
                    {"name": "1 POS integration via API", "enabled": True},
                    {"name": "AI-automated operational prompts", "enabled": True},
                    {"name": "Visual insights board", "enabled": True},
                    {"name": "CSV data file uploads", "enabled": True},
                    {"name": "Access chat history", "enabled": True},
                    {"name": "Role-based permissions", "enabled": True},
                    {"name": "Onboarding assistance", "enabled": True},
                    {"name": "AI supported and live ticketed support", "enabled": True}
                ]),
                "max_users_per_location": 999999,  # Unlimited
                "max_ai_engagements": 2500,
                "max_restaurants": 10,
                "max_integrations": 1,
                "trial_days": 7
            },
            {
                "name": "Premium",
                "description": "Built for power users and chain operators. Core FohBoh Cortexâ„¢ Capabilities, Plus",
                "role": "OPERATOR",
                "is_yearly": True,
                
                "price": 1430.00,
                "features": json.dumps([
                    {"name": "Unlimited users per location", "enabled": True},
                    {"name": "Up to 7,500 AI engagements/mo./location", "enabled": True},
                    {"name": "Supervise up to 25 restaurants", "enabled": True},
                    {"name": "Up to 2 integrations (e.g. POS and HR)", "enabled": True},
                    {"name": "AI Voice Notes & Journal", "enabled": True},
                    {"name": "AI-automated operational prompts", "enabled": True},
                    {"name": "Visual insights board", "enabled": True},
                    {"name": "CSV data file uploads", "enabled": True},
                    {"name": "Access chat history", "enabled": True},
                    {"name": "Document Uploads (e.g. inventory, recipes, SOPs)", "enabled": True},
                    {"name": "Multi-role-based permissions", "enabled": True},
                    {"name": "Onboarding assistance", "enabled": True},
                    {"name": "AI supported and live ticketed support", "enabled": True}
                ]),
                "max_users_per_location": 999999,  # Unlimited
                "max_ai_engagements": 7500,
                "max_restaurants": 25,
                "max_integrations": 2,
                "trial_days": 0
            },
            {
                "name": "Pro",
                "description": "Built for dynamic power users and chain operators. Core FohBoh Cortexâ„¢ Capabilities, Plus",
                "role": "OPERATOR",
                "is_yearly": True,
                
                "price": 1910.00,
                "features": json.dumps([
                    {"name": "Unlimited users per location", "enabled": True},
                    {"name": "Up to 10,000 AI engagements/mo./location", "enabled": True},
                    {"name": "Supervise up to 50 restaurants", "enabled": True},
                    {"name": "Up to 4 integrations (e.g.POS, HR, Inventory)", "enabled": True},
                    {"name": "AI Voice Notes & Journal", "enabled": True},
                    {"name": "AI-automated operational prompts", "enabled": True},
                    {"name": "Visual insights board", "enabled": True},
                    {"name": "CSV data file uploads", "enabled": True},
                    {"name": "Access chat history", "enabled": True},
                    {"name": "Document Uploads (e.g. inventory, recipes, SOPs)", "enabled": True},
                    {"name": "Multi-role-based permissions", "enabled": True},
                    {"name": "Onboarding assistance", "enabled": True},
                    {"name": "AI supported and live ticketed support", "enabled": True},
                    {"name": "Early access to AI Companion Agents access (e.g., PrepList, LaborSmart)", "enabled": True}
                ]),
                "max_users_per_location": 999999,  # Unlimited
                "max_ai_engagements": 10000,
                "max_restaurants": 50,
                "max_integrations": 4,
                "trial_days": 0
            },
            {
                "name": "Basic",
                "description": "7-Day Limited Free Trial Single User. Core FohBoh Cortexâ„¢ Capabilities, Plus",
                "role": "Non_Operators",
                "is_yearly": True,
                
                "price": 374.00,
                "features": json.dumps([
                    {"name": "Up to 1,150 AI engagements/mo.", "enabled": True},
                    {"name": "Restaurant-specific prompting", "enabled": True},
                    {"name": "Access to industry documents", "enabled": True},
                    {"name": "Read-only AI data interactions", "enabled": True},
                    {"name": "Limited access to chat history", "enabled": True},
                    {"name": "Community prompt library", "enabled": True},
                    {"name": "AI-supported chatbot support", "enabled": True}
                ]),
                "max_users_per_location": 1,
                "max_ai_engagements": 1150,
                "max_restaurants": 1,
                "max_integrations": 0,
                "trial_days": 7
            },
            {
                "name": "Premium",
                "description": "7-Day Limited Free Trial Single User. Core FohBoh Cortexâ„¢ Capabilities, Plus",
                "role": "Non_Operators",
                "is_yearly": True,
                
                "price": 854.00,
                "features": json.dumps([
                    {"name": "Up to 2,250 AI engagements/mo.", "enabled": True},
                    {"name": "Restaurant-specific prompting", "enabled": True},
                    {"name": "Access to industry documents", "enabled": True},
                    {"name": "Read-only AI data interactions", "enabled": True},
                    {"name": "Community prompt library", "enabled": True},
                    {"name": "Access chat history", "enabled": True},
                    {"name": "AI supported and live ticketed support", "enabled": True}
                ]),
                "max_users_per_location": 1,
                "max_ai_engagements": 2250,
                "max_restaurants": 1,
                "max_integrations": 0,
                "trial_days": 7
            }






        ]
        
        for plan in default_plans:
            cur.execute("""
                INSERT INTO subscription_plans 
                (name, description,role, price,  features, 
                max_users_per_location, max_ai_engagements, max_restaurants, 
                max_integrations, trial_days, is_yearly)
                SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                WHERE NOT EXISTS (
                    SELECT 1 FROM subscription_plans WHERE name = %s AND role = %s
                )
            """, (
                plan["name"], plan["description"],plan["role"], plan["price"], 
                plan["features"], plan["max_users_per_location"], 
                plan["max_ai_engagements"], plan["max_restaurants"], 
                plan["max_integrations"], plan["trial_days"], plan["is_yearly"],  plan["name"], plan["role"]
            ))
        
        conn.commit()
        logger.info("Subscription tables initialized successfully")
    except Exception as e:
        conn.rollback()
        logger.error(f"Error initializing subscription tables: {str(e)}")
        raise
    finally:
        conn.close()



import psycopg2
from fastapi import HTTPException
from datetime import datetime
import logging

# Initialize logger
logger = logging.getLogger(__name__)

async def update_usage(
    current_user: dict,  # Current user dictionary (you can use Depends(get_current_user) for FastAPI)
    conn,  # Database connection
    used_users_per_location: bool = False,
    used_ai_engagements: bool = False,
    used_restaurants: bool = False,
    used_integrations: bool = False
):
    try:
        # Fetch the active subscription for the user
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT us.id, sp.max_users_per_location, sp.max_ai_engagements, 
                       sp.max_restaurants, sp.max_integrations
                FROM user_subscriptions us
                JOIN subscription_plans sp ON us.plan_id = sp.id
                WHERE us.user_id = %s AND us.is_active = true
            """, (current_user['id'],))
            subscription = cur.fetchone()

            if not subscription:
                raise HTTPException(status_code=403, detail="User does not have an active subscription")

            # Extract subscription limits from the plan
            subscription_id, max_users_per_location, max_ai_engagements, max_restaurants, max_integrations = subscription["id"], subscription["max_users_per_location"], subscription["max_ai_engagements"], subscription["max_restaurants"], subscription["max_integrations"]
        except Exception as e:
            logger.error(f"Error fetching subscription details: {str(e)}")
            raise HTTPException(status_code=500, detail="Error fetching subscription details")

        # Fetch current usage record for the user
        try:
            cur.execute("""
                SELECT id, used_users_per_location, used_ai_engagements, used_restaurants, used_integrations
                FROM subscription_usage
                WHERE user_id = %s
                LIMIT 1
            """, (current_user['id'],))
            usage = cur.fetchone()
        except Exception as e:
            logger.error(f"Error fetching current usage: {str(e)}")
            raise HTTPException(status_code=500, detail="Error fetching usage data")

        # If no usage record exists, insert a new record with default values
        if not usage:
            try:
                cur.execute("""
                    INSERT INTO subscription_usage (
                        user_id, subscription_id, usage_type, reset_date, 
                        used_users_per_location, used_ai_engagements, used_restaurants, used_integrations
                    ) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s) 
                    RETURNING id
                """, (
                    current_user['id'],  # user_id
                    subscription_id,  # subscription_id
                    'general',  # usage_type (you can customize this based on your needs)
                    None,  # reset_date (you can define a default reset date)
                    1 if used_users_per_location else 0,  # used_users_per_location
                    1 if used_ai_engagements else 0,  # used_ai_engagements
                    1 if used_restaurants else 0,  # used_restaurants
                    1 if used_integrations else 0  # used_integrations
                ))
                usage_id = cur.fetchone()["id"]  # Get the new record ID
                conn.commit()
                return {"status": "success", "message": "Usage record created", "usage_id": usage_id}
            except Exception as e:
                logger.error(f"Error inserting new usage record: {str(e)}")
                conn.rollback()  # Rollback the transaction if insert fails
                raise HTTPException(status_code=500, detail="Error inserting new usage record")

        # If the usage record exists, check if the user exceeded their limits
        try:
            usage_id, current_used_users_per_location, current_used_ai_engagements, current_used_restaurants, current_used_integrations = usage["id"], usage["used_users_per_location"], usage["used_ai_engagements"], usage["used_restaurants"], usage["used_integrations"]

            # Check if the user has exceeded the limits for each usage type
            if used_users_per_location and current_used_users_per_location >= max_users_per_location:
                raise HTTPException(status_code=403, detail="Usage limit for users per location exceeded")
            
            if used_ai_engagements and current_used_ai_engagements >= max_ai_engagements:
                raise HTTPException(status_code=403, detail="Usage limit for AI engagements exceeded")
            
            if used_restaurants and current_used_restaurants >= max_restaurants:
                raise HTTPException(status_code=403, detail="Usage limit for restaurants exceeded")
            
            if used_integrations and current_used_integrations >= max_integrations:
                raise HTTPException(status_code=403, detail="Usage limit for integrations exceeded")
        except Exception as e:
            raise 
        except Exception as e:
            logger.error(f"Error checking usage limits: {str(e)}")
            raise HTTPException(status_code=500, detail="Error checking usage limits")

        # Now, update the usage record based on the flags passed
        try:
            new_used_users_per_location = current_used_users_per_location + 1 if used_users_per_location else current_used_users_per_location
            new_used_ai_engagements = current_used_ai_engagements + 1 if used_ai_engagements else current_used_ai_engagements
            new_used_restaurants = current_used_restaurants + 1 if used_restaurants else current_used_restaurants
            new_used_integrations = current_used_integrations + 1 if used_integrations else current_used_integrations

            # Update the usage record
            cur.execute("""
                UPDATE subscription_usage
                SET used_users_per_location = %s,
                    used_ai_engagements = %s,
                    used_restaurants = %s,
                    used_integrations = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (
                new_used_users_per_location,
                new_used_ai_engagements,
                new_used_restaurants,
                new_used_integrations,
                usage_id
            ))
            conn.commit()
            return {"status": "success", "message": "Usage updated successfully"}
        except Exception as e:
            logger.error(f"Error updating usage record: {str(e)}")
            conn.rollback()  # Rollback the transaction if update fails
            raise HTTPException(status_code=500, detail="Error updating usage record")

    except HTTPException:
        # If an HTTPException is raised, propagate it with proper status code and message
        raise 

    except Exception as e:
        # Catch any generic exceptions that might occur
        logger.error(f"Unexpected error: {str(e)}")
        conn.rollback()  # Rollback the transaction on any error
        raise HTTPException(status_code=500, detail=f"Error updating usage: {str(e)}")


# Subscription Management Class
class SubscriptionManager:
    """Class to handle subscription-related operations"""
    
    @staticmethod
    async def get_user_subscription(user_id: int, conn):
        """Get the current subscription for a user"""
        try:
            cur = conn.cursor()
            
            cur.execute("""
                SELECT 
                    us.*, 
                    sp.name AS plan_name, 
                    sp.features, 
                    sp.max_users_per_location,
                    sp.max_ai_engagements, 
                    sp.max_restaurants, 
                    sp.max_integrations,
                    su.id AS usage_id, 
                    su.usage_type, 
                    su.usage_count, 
                    su.reset_date, 
                    su.created_at AS usage_created_at,
                    su.updated_at AS usage_updated_at,
                    su.used_users_per_location,  
                    su.used_ai_engagements,      
                    su.used_restaurants,         
                    su.used_integrations
                FROM user_subscriptions us
                JOIN subscription_plans sp ON us.plan_id = sp.id
                LEFT JOIN subscription_usage su ON us.user_id = su.user_id
                WHERE us.user_id = %s AND us.is_active = true
            """, (user_id,))

            subscription = cur.fetchone()


            
            
            if not subscription:
                # Check if user exists
                # cur.execute("SELECT id FROM managers WHERE id = %s", (user_id,))
                # user = cur.fetchone()
                
                # if not user:
                #     cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
                #     user = cur.fetchone()
                
                # if not user:
                #     raise HTTPException(status_code=404, detail="User not found")
                
                # User exists but has no subscription - create a free trial
                await SubscriptionManager.create_free_trial(user_id, conn)
                
                # Fetch the newly created subscription
                cur.execute("""
                    SELECT us.*, sp.name as plan_name, sp.features, sp.max_users_per_location,
                           sp.max_ai_engagements, sp.max_restaurants, sp.max_integrations
                    FROM user_subscriptions us
                    JOIN subscription_plans sp ON us.plan_id = sp.id
                    WHERE us.user_id = %s AND us.is_active = true
                """, (user_id,))
                
                subscription = cur.fetchone()
            
                return subscription

                # raise HTTPException(status_code=402, detail="Subscription not found")
            else:
                return subscription
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting user subscription: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def create_free_trial(user_id: int, conn):
        """Create or update a free trial subscription for a user, ensuring only one trial per user"""
        try:
            cur = conn.cursor()
            
            # Check if the user has already used the free trial
            cur.execute("""
                SELECT * FROM subscription_history 
                WHERE user_id = %s AND action = 'trial_started' 
                AND details->>'plan_name' = 'Free Trial'
            """, (user_id,))
            
            trial_history = cur.fetchone()
            
            if trial_history:
                raise HTTPException(status_code=400, detail="User has already used the free trial.")
            
            # Get the free trial plan
            cur.execute("""
                SELECT * FROM subscription_plans 
                WHERE name = 'Free Trial' AND is_active = true
            """)
            
            plan = cur.fetchone()
            if not plan:
                raise HTTPException(status_code=403, detail="Free trial plan not found")
            
            # Get trial period days from system settings if available
            try:
                cur.execute("""
                    SELECT value FROM system_settings
                    WHERE key = 'trial_period_days'
                """)
                setting = cur.fetchone()
                trial_days = int(setting['value']) if setting else plan['trial_days']
            except Exception:
                # If error, use plan's trial days
                trial_days = plan['trial_days']
            
            # Calculate trial end date
            trial_end_date = datetime.now() + timedelta(days=trial_days)
            start_date = datetime.now()
            
            # Check if user already has a subscription
            cur.execute("""
                SELECT * FROM user_subscriptions 
                WHERE user_id = %s
            """, (user_id,))
            
            existing_subscription = cur.fetchone()
            
            if existing_subscription:
                # Update existing subscription
                cur.execute("""
                    UPDATE user_subscriptions
                    SET plan_id = %s,
                        trial_end_date = %s,
                        end_date = %s,
                        is_trial = true,
                        is_active = true,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = %s
                    RETURNING id
                """, (plan['id'], trial_end_date, trial_end_date, user_id))
                
                subscription_id = cur.fetchone()['id']
                
                # Update usage record
                cur.execute("""
                    UPDATE subscription_usage
                    SET reset_date = %s,
                        usage_count = 0,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = %s AND subscription_id = %s
                """, (trial_end_date, user_id, subscription_id))
                
            else:
                # Create new subscription
                cur.execute("""
                    INSERT INTO user_subscriptions
                    (user_id, plan_id, trial_end_date, end_date, is_trial)
                    VALUES (%s, %s, %s, %s, true)
                    RETURNING id
                """, (user_id, plan['id'], trial_end_date, trial_end_date))
                
                subscription_id = cur.fetchone()['id']
                
                # Create usage record
                cur.execute("""
                    INSERT INTO subscription_usage
                    (user_id, subscription_id, usage_type, reset_date)
                    VALUES (%s, %s, %s, %s)
                """, (user_id, subscription_id, 'ai_engagements', trial_end_date))
            
            # Initialize or update token usage record
            try:
                if existing_subscription:
                    cur.execute("""
                        UPDATE token_usage
                        SET tokens_used = 0,
                            engagements_used = 0,
                            billing_cycle_start = %s,
                            billing_cycle_end = %s
                        WHERE user_id = %s AND subscription_id = %s
                    """, (start_date, trial_end_date, user_id, subscription_id))
                else:
                    cur.execute("""
                        INSERT INTO token_usage
                        (user_id, subscription_id, tokens_used, engagements_used, 
                        billing_cycle_start, billing_cycle_end)
                        VALUES (%s, %s, 0, 0, %s, %s)
                    """, (user_id, subscription_id, start_date, trial_end_date))
            except Exception as e:
                # Log error but continue (token tables might not be initialized yet)
                logger.error(f"Error initializing token usage for trial: {str(e)}")
            
            # Add to subscription history
            cur.execute("""
                INSERT INTO subscription_history
                (user_id, plan_id, action, details)
                VALUES (%s, %s, %s, %s)
            """, (
                user_id, 
                plan['id'], 
                'trial_started', 
                json.dumps({
                    "trial_end_date": trial_end_date.isoformat(),
                    "plan_name": plan['name'],
                    "is_renewal": existing_subscription is not None
                })
            ))
            
            conn.commit()
            
            # Send notification to user
            action = "renewed" if existing_subscription else "started"
            await create_notification(
                user_id=user_id,
                title="Free Trial Started!",
                message=f"Your {plan['trial_days']}-day free trial has been {action}. Enjoy full access to all features!",
                type="info",
                cat = "subscription",
                conn=conn
            )
            
            logger.info(f"{'Updated' if existing_subscription else 'Created'} free trial subscription for user {user_id}")
            return subscription_id
        except HTTPException:
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"Error creating/updating free trial: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    @staticmethod
    async def update_subscription(user_id: int, subscription_data: UserSubscriptionUpdate, conn):
        """Update a user's subscription"""
        try:
            cur = conn.cursor()
            
            # Get current subscription
            cur.execute("""
                SELECT * FROM user_subscriptions
                WHERE user_id = %s AND is_active = true
            """, (user_id,))
            
            current_subscription = cur.fetchone()
            if not current_subscription:
                raise HTTPException(status_code=404, detail="Active subscription not found")
            
            # Build update query dynamically based on provided fields
            update_fields = []
            params = []
            
            if subscription_data.plan_id is not None:
                update_fields.append("plan_id = %s")
                params.append(subscription_data.plan_id)
                
                # Get the new plan details
                cur.execute("SELECT * FROM subscription_plans WHERE id = %s", (subscription_data.plan_id,))
                new_plan = cur.fetchone()
                if not new_plan:
                    raise HTTPException(status_code=404, detail="Subscription plan not found")
                
                # Update trial_end_date if changing plans
                if current_subscription['is_trial']:
                    trial_end_date = datetime.now() + timedelta(days=new_plan['trial_days'])
                    update_fields.append("trial_end_date = %s")
                    params.append(trial_end_date)
                    
                    # Also update end_date
                    update_fields.append("end_date = %s")
                    params.append(trial_end_date)
            
            if subscription_data.payment_method_id is not None:
                update_fields.append("payment_method_id = %s")
                params.append(subscription_data.payment_method_id)
            
            if subscription_data.is_yearly is not None:
                update_fields.append("is_yearly = %s")
                params.append(subscription_data.is_yearly)
            
            if subscription_data.auto_renew is not None:
                update_fields.append("auto_renew = %s")
                params.append(subscription_data.auto_renew)
            
            if subscription_data.is_active is not None:
                update_fields.append("is_active = %s")
                params.append(subscription_data.is_active)
            
            # Add updated_at timestamp
            update_fields.append("updated_at = CURRENT_TIMESTAMP")
            
            if not update_fields:
                return current_subscription  # Nothing to update
            
            # Build and execute the update query
            query = f"""
                UPDATE user_subscriptions
                SET {", ".join(update_fields)}
                WHERE user_id = %s AND is_active = true
                RETURNING *
            """
            
            params.append(user_id)
            cur.execute(query, params)
            
            updated_subscription = cur.fetchone()
            
            # Add to subscription history
            history_details = {
                "previous_plan_id": current_subscription['plan_id'],
                "new_plan_id": updated_subscription['plan_id'],
                "changes": {}
            }
            
            if subscription_data.plan_id is not None and subscription_data.plan_id != current_subscription['plan_id']:
                history_details["changes"]["plan_changed"] = True
            
            if subscription_data.is_yearly is not None and subscription_data.is_yearly != current_subscription['is_yearly']:
                history_details["changes"]["billing_cycle_changed"] = True
                history_details["changes"]["is_yearly"] = subscription_data.is_yearly
            
            if subscription_data.auto_renew is not None and subscription_data.auto_renew != current_subscription['auto_renew']:
                history_details["changes"]["auto_renew_changed"] = True
                history_details["changes"]["auto_renew"] = subscription_data.auto_renew
            
            if subscription_data.is_active is not None and subscription_data.is_active != current_subscription['is_active']:
                history_details["changes"]["status_changed"] = True
                history_details["changes"]["is_active"] = subscription_data.is_active
            
            cur.execute("""
                INSERT INTO subscription_history
                (user_id, plan_id, action, details)
                VALUES (%s, %s, %s, %s)
            """, (
                user_id, 
                updated_subscription['plan_id'], 
                'subscription_updated', 
                json.dumps(history_details)
            ))
            
            conn.commit()
            
            # Send notification to user
            await create_notification(
                user_id=user_id,
                title=" ðŸ“¢ Subscription Updated",
                message="Your subscription has been updated successfully.",
                type="info",
                cat = "subscription",
                conn=conn
            )
            
            logger.info(f"Updated subscription for user {user_id}")
            return updated_subscription
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating subscription: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def cancel_subscription(user_id: int, conn):
        """Cancel a user's subscription"""
        try:
            cur = conn.cursor()
            
            # Get current subscription
            cur.execute("""
                SELECT * FROM user_subscriptions
                WHERE user_id = %s AND is_active = true
            """, (user_id,))
            
            subscription = cur.fetchone()
            if not subscription:
                raise HTTPException(status_code=404, detail="Active subscription not found")
            
            # Update subscription to inactive
            cur.execute("""
                UPDATE user_subscriptions
                SET is_active = false, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s AND is_active = true
                RETURNING *
            """, (user_id,))
            
            canceled_subscription = cur.fetchone()
            
            # Add to subscription history
            cur.execute("""
                INSERT INTO subscription_history
                (user_id, plan_id, action, details)
                VALUES (%s, %s, %s, %s)
            """, (
                user_id, 
                subscription['plan_id'], 
                'subscription_canceled', 
                json.dumps({
                    "canceled_at": datetime.now().isoformat(),
                    "was_trial": subscription['is_trial']
                })
            ))
            
            conn.commit()
            
            # Send notification to user
            await create_notification(
                user_id=user_id,
                title=" âš ï¸ Subscription Canceled",
                message="Your subscription has been canceled. You will lose access to premium features at the end of your current billing period.",
                type="warning",
                cat = "subscription",
                conn=conn
            )
            
            logger.info(f"Canceled subscription for user {user_id}")
            return canceled_subscription
        except Exception as e:
            conn.rollback()
            logger.error(f"Error canceling subscription: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def track_usage(user_id: int, usage_type: str, count: int, conn):
        """Track usage for a subscription"""
        try:
            cur = conn.cursor()
            
            # Get current subscription
            cur.execute("""
                SELECT * FROM user_subscriptions
                WHERE user_id = %s AND is_active = true
            """, (user_id,))
            
            subscription = cur.fetchone()
            if not subscription:
                raise HTTPException(status_code=404, detail="Active subscription not found")
            
            # Get or create usage record
            cur.execute("""
                SELECT * FROM subscription_usage
                WHERE user_id = %s AND subscription_id = %s AND usage_type = %s
            """, (user_id, subscription['id'], usage_type))
            
            usage = cur.fetchone()
            
            if not usage:
                # Create new usage record
                cur.execute("""
                    INSERT INTO subscription_usage
                    (user_id, subscription_id, usage_type, usage_count, reset_date)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING *
                """, (
                    user_id, 
                    subscription['id'], 
                    usage_type, 
                    count, 
                    subscription['end_date']
                ))
                
                usage = cur.fetchone()
            else:
                # Update existing usage record
                cur.execute("""
                    UPDATE subscription_usage
                    SET usage_count = usage_count + %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING *
                """, (count, usage['id']))
                
                usage = cur.fetchone()
            
            # If usage type is ai_engagements, also update token usage
            if usage_type == 'ai_engagements':
                try:
                    # Get tokens per engagement from system settings
                    cur.execute("""
                        SELECT value FROM system_settings
                        WHERE key = 'tokens_per_engagement'
                    """)
                    setting = cur.fetchone()
                    tokens_per_engagement = int(setting['value']) if setting else 600
                    
                    # Get current token usage
                    cur.execute("""
                        SELECT * FROM token_usage
                        WHERE user_id = %s AND subscription_id = %s
                        AND billing_cycle_start <= CURRENT_TIMESTAMP
                        AND billing_cycle_end >= CURRENT_TIMESTAMP
                    """, (user_id, subscription['id']))
                    
                    token_usage = cur.fetchone()
                    
                    if token_usage:
                        # Update token usage
                        cur.execute("""
                            UPDATE token_usage
                            SET tokens_used = tokens_used + %s,
                                engagements_used = engagements_used + %s,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                        """, (tokens_per_engagement * count, count, token_usage['id']))
                    else:
                        # Create new token usage record
                        start_date = datetime.now()
                        end_date = subscription['end_date'] or (start_date + timedelta(days=30))
                        
                        cur.execute("""
                            INSERT INTO token_usage
                            (user_id, subscription_id, tokens_used, engagements_used, 
                             billing_cycle_start, billing_cycle_end)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (
                            user_id, 
                            subscription['id'], 
                            tokens_per_engagement * count, 
                            count, 
                            start_date, 
                            end_date
                        ))
                    
                    # Log the engagement
                    cur.execute("""
                        INSERT INTO engagement_logs
                        (user_id, tokens_consumed, engagement_type)
                        VALUES (%s, %s, %s)
                    """, (user_id, tokens_per_engagement * count, 'subscription_usage'))
                    
                except Exception as e:
                    # Log error but continue (token tables might not be initialized yet)
                    logger.error(f"Error updating token usage: {str(e)}")
            
            conn.commit()
            logger.info(f"Tracked {count} {usage_type} usage for user {user_id}")
            return usage
        except Exception as e:
            conn.rollback()
            logger.error(f"Error tracking usage: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def check_subscription_limits(user_id: int, usage_type: str, conn):
        """Check if a user has exceeded their subscription limits"""
        try:
            cur = conn.cursor()
            
            # Get current subscription with plan details
            cur.execute("""
                SELECT us.*, sp.max_ai_engagements, sp.max_restaurants, sp.max_integrations
                FROM user_subscriptions us
                JOIN subscription_plans sp ON us.plan_id = sp.id
                WHERE us.user_id = %s AND us.is_active = true
            """, (user_id,))
            
            subscription = cur.fetchone()
            if not subscription:
                raise HTTPException(status_code=404, detail="Active subscription not found")
            
            # Get current usage
            cur.execute("""
                SELECT * FROM subscription_usage
                WHERE user_id = %s AND subscription_id = %s AND usage_type = %s
            """, (user_id, subscription['id'], usage_type))
            
            usage = cur.fetchone()
            
            if not usage:
                # No usage record yet, so limits haven't been exceeded
                return {
                    "limit_exceeded": False,
                    "current_usage": 0,
                    "limit": subscription.get(f"max_{usage_type}", 0)
                }
            
            # Check if usage exceeds limits
            limit_exceeded = False
            limit = 0
            
            if usage_type == 'ai_engagements':
                limit = subscription['max_ai_engagements']
                limit_exceeded = usage['usage_count'] >= limit
            elif usage_type == 'restaurants':
                limit = subscription['max_restaurants']
                limit_exceeded = usage['usage_count'] >= limit
            elif usage_type == 'integrations':
                limit = subscription['max_integrations']
                limit_exceeded = usage['usage_count'] >= limit
            
            return {
                "limit_exceeded": limit_exceeded,
                "current_usage": usage['usage_count'],
                "limit": limit
            }
        except Exception as e:
            logger.error(f"Error checking subscription limits: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def process_trial_expiration(background_tasks: BackgroundTasks):
        """Process expired trials and send notifications"""
        try:
            conn = next(get_db())
            cur = conn.cursor()
            
            # Find trials that expire today
            cur.execute("""
                SELECT us.*, m.email as user_email
                FROM user_subscriptions us
                LEFT JOIN managers m ON us.user_id = m.id
                WHERE us.is_trial = true 
                AND us.is_active = true
                AND us.trial_end_date <= CURRENT_TIMESTAMP + INTERVAL '1 day'
                AND us.trial_end_date > CURRENT_TIMESTAMP
            """)
            
            expiring_trials = cur.fetchall()
            
            for trial in expiring_trials:
                # Send notification about trial expiring soon
                await create_notification(
                    user_id=trial['user_id'],
                    title=" âš ï¸ Trial Ending Soon",
                    message="Your free trial is ending soon. Subscribe to continue using premium features.",
                    type="warning",
                    cat = "subscription",
                    conn=conn
                )
                
                logger.info(f"Sent trial expiration notification to user {trial['user_id']}")
            
            # Find trials that have already expired
            cur.execute("""
                SELECT us.*, m.email as user_email
                FROM user_subscriptions us
                LEFT JOIN managers m ON us.user_id = m.id
                WHERE us.is_trial = true 
                AND us.is_active = true
                AND us.trial_end_date <= CURRENT_TIMESTAMP
            """)
            
            expired_trials = cur.fetchall()
            
            for trial in expired_trials:
                # Update subscription to inactive
                cur.execute("""
                    UPDATE user_subscriptions
                    SET is_active = false, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING *
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
                    json.dumps({
                        "expired_at": datetime.now().isoformat(),
                        "trial_duration_days": (trial['trial_end_date'] - trial['start_date']).days
                    })
                ))
                
                # Send notification about trial expiration
                await create_notification(
                    user_id=trial['user_id'],
                    title="ðŸš¨ Trial Expired",
                    message="Your free trial has expired. Subscribe now to continue using premium features.",
                    type="alert",
                    cat = "subscription",
                    conn=conn
                )
                
                logger.info(f"Processed expired trial for user {trial['user_id']}")
            
            conn.commit()
            return {
                "expiring_soon": len(expiring_trials),
                "expired": len(expired_trials)
            }
        except Exception as e:
            conn.rollback()
            logger.error(f"Error processing trial expirations: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

# API Endpoints
import json

@router.get("/plans")
async def get_subscription_plans(
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Get all available subscription plans"""
    ROLE = current_user["role"]

    if ROLE != "Non_Operators":
        ROLE = "OPERATOR"

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT * FROM subscription_plans
            WHERE is_active = true AND role = %s
            ORDER BY price ASC
        """,(ROLE,))

        plans = cur.fetchall()

        # Parse JSON features
        for plan in plans:
            if 'features' in plan and plan['features']:
                # Check if 'features' is a string (we need to parse it)
                if isinstance(plan['features'], str):
                    plan['features'] = json.loads(plan['features'])

        return {
            "status": "success",
            "plans": plans
        }
    except Exception as e:
        logger.error(f"Error getting subscription plans: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

from datetime import datetime, timezone
@router.get("/my-subscription")
async def get_my_subscription(
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Get the current user's subscription details"""
    try:
        subscription = await SubscriptionManager.get_user_subscription(current_user['id'], conn)
        
        # Parse JSON features
        if 'features' in subscription and subscription['features']:
            if isinstance(subscription['features'], str):
                subscription['features'] = json.loads(subscription['features'])
                
        # Get usage information
        cur = conn.cursor()
        
        cur.execute("""
            SELECT usage_type, usage_count
            FROM subscription_usage
            WHERE user_id = %s AND subscription_id = %s
        """, (current_user['id'], subscription['id']))
        
        usage = cur.fetchall()
        
        # Format usage data
        usage_data = {}
        for item in usage:
            usage_data[item['usage_type']] = {
                "current": item['usage_count'],
                "limit": subscription.get(f"max_{item['usage_type']}", 0)
            }
        
        # Calculate days remaining in trial or subscription
        days_remaining = 0
        if subscription['is_trial']:
            if subscription['trial_end_date']:
                days_remaining = (subscription['trial_end_date'] - datetime.now(timezone.utc)).days
                if days_remaining < 0:
                    days_remaining = 0
        else:
            if subscription['end_date']:
                days_remaining = (subscription['end_date'] - datetime.now(timezone.utc)).days
                if days_remaining < 0:
                    days_remaining = 0
        
        # Remove id and user_id from subscription before returning
        subscription.pop('id', None)
        subscription.pop('user_id', None)
        
        return {
            "status": "success",
            "subscription": subscription,
            "usage": usage_data,
            "days_remaining": days_remaining
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting my subscription: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/subscribe")
async def subscribe_to_plan(
    plan_id: int,
    is_yearly: bool = False,
    payment_method_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Subscribe to a plan or change current subscription"""
    try:
        # Check if plan exists
        cur = conn.cursor()
        
        cur.execute("SELECT * FROM subscription_plans WHERE id = %s AND is_active = true", (plan_id,))
        plan = cur.fetchone()
        
        if not plan:
            raise HTTPException(status_code=404, detail="Subscription plan not found or inactive")
        
        # Check if user already has a subscription
        cur.execute("""
            SELECT * FROM user_subscriptions
            WHERE user_id = %s AND is_active = true
        """, (current_user['id'],))
        
        existing_subscription = cur.fetchone()
        
        if existing_subscription:
            # Update existing subscription
            subscription_data = UserSubscriptionUpdate(
                plan_id=plan_id,
                is_yearly=is_yearly,
                payment_method_id=payment_method_id
            )
            
            updated_subscription = await SubscriptionManager.update_subscription(
                current_user['id'], 
                subscription_data, 
                conn
            )
            
            return {
                "status": "success",
                "message": "Subscription updated successfully",
                "subscription": updated_subscription
            }
        else:
            # Create new subscription
            # Calculate end date based on billing cycle
            start_date = datetime.now()
            trial_end_date = start_date + timedelta(days=plan['trial_days'])
            
            if is_yearly:
                end_date = start_date + timedelta(days=365)
            else:
                end_date = start_date + timedelta(days=30)
            
            # Create subscription
            cur.execute("""
                INSERT INTO user_subscriptions
                (user_id, plan_id, start_date, end_date, trial_end_date, is_trial, is_yearly, payment_method_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (
                current_user['id'], 
                plan_id, 
                start_date, 
                end_date, 
                trial_end_date, 
                True,  # Start with trial
                is_yearly, 
                payment_method_id
            ))
            
            new_subscription = cur.fetchone()
            
            # Create usage record
            cur.execute("""
                INSERT INTO subscription_usage
                (user_id, subscription_id, usage_type, reset_date)
                VALUES (%s, %s, %s, %s)
            """, (current_user['id'], new_subscription['id'], 'ai_engagements', end_date))
            
            # Add to subscription history
            cur.execute("""
                INSERT INTO subscription_history
                (user_id, plan_id, action, details)
                VALUES (%s, %s, %s, %s)
            """, (
                current_user['id'], 
                plan_id, 
                'subscription_created', 
                json.dumps({
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "is_yearly": is_yearly,
                    "plan_name": plan['name']
                })
            ))
            
            conn.commit()
            
            # Send notification to user
            await create_notification(
                user_id=current_user['id'],
                title="Subscription Started!",
                message=f"You've successfully subscribed to the {plan['name']} plan. Enjoy your premium features!",
                type="infoðŸ“¢",
                cat = "subscription",
                conn=conn
            )
            
            return {
                "status": "success",
                "message": "Subscription created successfully",
                "subscription": new_subscription
            }
    except Exception as e:
        conn.rollback()
        logger.error(f"Error subscribing to plan: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cancel")
async def cancel_subscription_endpoint(
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Cancel the current user's subscription"""
    try:
        canceled_subscription = await SubscriptionManager.cancel_subscription(current_user['id'], conn)
        
        return {
            "status": "success",
            "message": "Subscription canceled successfully",
            "subscription": canceled_subscription
        }
    except Exception as e:
        logger.error(f"Error canceling subscription: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/track-usage")
async def track_usage_endpoint(
    usage_type: str,
    count: int = 1,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Track usage for the current user's subscription"""
    try:
        # Validate usage type
        valid_usage_types = ['ai_engagements', 'restaurants', 'integrations']
        if usage_type not in valid_usage_types:
            raise HTTPException(status_code=400, detail=f"Invalid usage type. Must be one of: {', '.join(valid_usage_types)}")
        
        # Track usage
        usage = await SubscriptionManager.track_usage(current_user['id'], usage_type, count, conn)
        
        # Check if limits are exceeded
        limits = await SubscriptionManager.check_subscription_limits(current_user['id'], usage_type, conn)
        
        if limits['limit_exceeded']:
            # Send notification about limit exceeded
            await create_notification(
                user_id=current_user['id'],
                title=f"Usage Limit Reached",
                message=f"You've reached your {usage_type.replace('_', ' ')} limit. Consider upgrading your plan for more.",
                type="warningâš ï¸",
                cat = "subscription",
                conn=conn
            )
        
        return {
            "status": "success",
            "usage": usage,
            "limits": limits
        }
    except Exception as e:
        logger.error(f"Error tracking usage: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/check-limits/{usage_type}")
async def check_limits_endpoint(
    usage_type: str,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Check if the current user has exceeded their subscription limits"""
    try:
        # Validate usage type
        valid_usage_types = ['ai_engagements', 'restaurants', 'integrations']
        if usage_type not in valid_usage_types:
            raise HTTPException(status_code=400, detail=f"Invalid usage type. Must be one of: {', '.join(valid_usage_types)}")
        
        limits = await SubscriptionManager.check_subscription_limits(current_user['id'], usage_type, conn)
        
        return {
            "status": "success",
            "limits": limits
        }
    except Exception as e:
        logger.error(f"Error checking limits: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/history")
async def get_subscription_history(
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Get subscription history for the current user"""
    try:
        cur = conn.cursor()
        
        cur.execute("""
            SELECT sh.*, sp.name as plan_name
            FROM subscription_history sh
            JOIN subscription_plans sp ON sh.plan_id = sp.id
            WHERE sh.user_id = %s
            ORDER BY sh.created_at DESC
        """, (current_user['id'],))
        
        history = cur.fetchall()
        
        # Parse JSON details
        for item in history:
            if 'details' in item and item['details']:
                if isinstance(item['details'], str):
                    item['details'] = json.loads(item['details'])

        
        return {
            "status": "success",
            "history": history
        }
    except Exception as e:
        logger.error(f"Error getting subscription history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/process-expirations")
async def process_expirations(
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Process expired trials and subscriptions"""
    try:
        # Check if user is admin
        if current_user['role'] != 'SUPER_ADMIN':
            raise HTTPException(status_code=403, detail="Only administrators can process expirations")
        
        # Process expirations in the background
        background_tasks.add_task(SubscriptionManager.process_trial_expiration, background_tasks)
        
        return {
            "status": "success",
            "message": "Processing expirations in the background"
        }
    except Exception as e:
        raise 
    except Exception as e:
        logger.error(f"Error processing expirations: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Admin endpoints for managing subscription plans
@router.post("/admin/plans")
async def create_subscription_plan(
    plan_data: SubscriptionPlanCreate,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Create a new subscription plan (admin only)"""
    try:
        # Check if user is admin
        if current_user['role'] != 'SUPER_ADMIN':
            raise HTTPException(status_code=403, detail="Only administrators can create subscription plans")
        
        cur = conn.cursor()
        
        # Check if plan with same name already exists
        cur.execute("SELECT id FROM subscription_plans WHERE name = %s", (plan_data.name,))
        existing_plan = cur.fetchone()
        
        if existing_plan:
            raise HTTPException(status_code=400, detail=f"Plan with name '{plan_data.name}' already exists")
        
        # Create new plan
        cur.execute("""
            INSERT INTO subscription_plans
            (name, description, price_monthly, price_yearly, features, 
            max_users_per_location, max_ai_engagements, max_restaurants, 
            max_integrations, trial_days)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (
            plan_data.name,
            plan_data.description,
            plan_data.price_monthly,
            plan_data.price_yearly,
            json.dumps(plan_data.features),
            plan_data.max_users_per_location,
            plan_data.max_ai_engagements,
            plan_data.max_restaurants,
            plan_data.max_integrations,
            plan_data.trial_days
        ))
        
        new_plan = cur.fetchone()
        conn.commit()
        
        logger.info(f"Created new subscription plan: {plan_data.name}")
        return {
            "status": "success",
            "plan": new_plan
        }
    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating subscription plan: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/admin/plans/{plan_id}")
async def update_subscription_plan(
    plan_id: int,
    plan_data: SubscriptionPlanUpdate,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Update an existing subscription plan (admin only)"""
    try:
        # Check if user is admin
        if current_user['role'] != 'SUPER_ADMIN':
            raise HTTPException(status_code=403, detail="Only administrators can update subscription plans")
        
        cur = conn.cursor()
        
        # Check if plan exists
        cur.execute("SELECT * FROM subscription_plans WHERE id = %s", (plan_id,))
        existing_plan = cur.fetchone()
        
        if not existing_plan:
            raise HTTPException(status_code=404, detail="Subscription plan not found")
        
        # Build update query dynamically based on provided fields
        update_fields = []
        params = []
        
        if plan_data.name is not None:
            update_fields.append("name = %s")
            params.append(plan_data.name)
        
        if plan_data.description is not None:
            update_fields.append("description = %s")
            params.append(plan_data.description)
        
        if plan_data.price_monthly is not None:
            update_fields.append("price_monthly = %s")
            params.append(plan_data.price_monthly)
        
        if plan_data.price_yearly is not None:
            update_fields.append("price_yearly = %s")
            params.append(plan_data.price_yearly)
        
        if plan_data.features is not None:
            update_fields.append("features = %s")
            params.append(json.dumps(plan_data.features))
        
        if plan_data.max_users_per_location is not None:
            update_fields.append("max_users_per_location = %s")
            params.append(plan_data.max_users_per_location)
        
        if plan_data.max_ai_engagements is not None:
            update_fields.append("max_ai_engagements = %s")
            params.append(plan_data.max_ai_engagements)
        
        if plan_data.max_restaurants is not None:
            update_fields.append("max_restaurants = %s")
            params.append(plan_data.max_restaurants)
        
        if plan_data.max_integrations is not None:
            update_fields.append("max_integrations = %s")
            params.append(plan_data.max_integrations)
        
        if plan_data.trial_days is not None:
            update_fields.append("trial_days = %s")
            params.append(plan_data.trial_days)
        
        if plan_data.is_active is not None:
            update_fields.append("is_active = %s")
            params.append(plan_data.is_active)
        
        # Add updated_at timestamp
        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        
        if not update_fields:
            return existing_plan  # Nothing to update
        
        # Build and execute the update query
        query = f"""
            UPDATE subscription_plans
            SET {", ".join(update_fields)}
            WHERE id = %s
            RETURNING *
        """
        
        params.append(plan_id)
        cur.execute(query, params)
        
        updated_plan = cur.fetchone()
        conn.commit()
        
        logger.info(f"Updated subscription plan: {plan_id}")
        return {
            "status": "success",
            "plan": updated_plan
        }
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating subscription plan: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/admin/plans/{plan_id}")
async def delete_subscription_plan(
    plan_id: int,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Delete a subscription plan (admin only)"""
    try:
        # Check if user is admin
        if current_user['role'] != 'SUPER_ADMIN':
            raise HTTPException(status_code=403, detail="Only administrators can delete subscription plans")
        
        cur = conn.cursor()
        
        # Check if plan exists
        cur.execute("SELECT * FROM subscription_plans WHERE id = %s", (plan_id,))
        existing_plan = cur.fetchone()
        
        if not existing_plan:
            raise HTTPException(status_code=404, detail="Subscription plan not found")
        
        # Check if plan is in use
        cur.execute("""
            SELECT COUNT(*) as count
            FROM user_subscriptions
            WHERE plan_id = %s AND is_active = true
        """, (plan_id,))
        
        active_subscriptions = cur.fetchone()['count']
        
        if active_subscriptions > 0:
            # Instead of deleting, mark as inactive
            cur.execute("""
                UPDATE subscription_plans
                SET is_active = false, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING *
            """, (plan_id,))
            
            deactivated_plan = cur.fetchone()
            conn.commit()
            
            logger.info(f"Deactivated subscription plan: {plan_id} (has active subscriptions)")
            return {
                "status": "success",
                "message": "Plan has active subscriptions and was deactivated instead of deleted",
                "plan": deactivated_plan
            }
        else:
            # No active subscriptions, safe to delete
            cur.execute("DELETE FROM subscription_plans WHERE id = %s RETURNING id", (plan_id,))
            deleted_id = cur.fetchone()['id']
            conn.commit()
            
            logger.info(f"Deleted subscription plan: {plan_id}")
            return {
                "status": "success",
                "message": "Plan deleted successfully",
                "id": deleted_id
            }
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting subscription plan: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/admin/user-subscriptions")
async def get_all_user_subscriptions(
    active_only: bool = True,
    limit: int = 100,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Get all user subscriptions (admin only)"""
    try:
        # Check if user is admin
        if current_user['role'] != 'SUPER_ADMIN':
            raise HTTPException(status_code=403, detail="Only administrators can view all subscriptions")
        
        cur = conn.cursor()
        
        # Build query based on active_only parameter
        query = """
            SELECT us.*, sp.name as plan_name, 
                   COALESCE(m.email, u.email) as user_email,
                   COALESCE(m.full_name, u.full_name) as user_full_name
            FROM user_subscriptions us
            JOIN subscription_plans sp ON us.plan_id = sp.id
            LEFT JOIN managers m ON us.user_id = m.id
            LEFT JOIN users u ON us.user_id = u.id
        """
        
        params = []
        
        if active_only:
            query += " WHERE us.is_active = true"
        
        query += " ORDER BY us.created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        cur.execute(query, params)
        subscriptions = cur.fetchall()
        
        # Get total count for pagination
        count_query = "SELECT COUNT(*) as total FROM user_subscriptions"
        if active_only:
            count_query += " WHERE is_active = true"
        
        cur.execute(count_query)
        total_count = cur.fetchone()['total']
        
        return {
            "status": "success",
            "subscriptions": subscriptions,
            "pagination": {
                "total": total_count,
                "limit": limit,
                "offset": offset
            }
        }
    except Exception as e:
        logger.error(f"Error getting all user subscriptions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Export the init function and router
__all__ = ['init_subscription_tables', 'router']
