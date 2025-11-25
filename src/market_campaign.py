from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import uuid
from datetime import datetime, timedelta, timezone
import statistics
from src.chat_gpt import get_current_user, get_db, DB_CONFIG
from src.subscription_management import update_usage
import random
from typing import List, Dict
import os
import boto3
from pathlib import Path


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# AWS S3 Configuration
BUCKET_NAME = "my-audio-demo"
s3_client = boto3.client(
    's3',
    region_name='us-east-1',
    aws_access_key_id='AKIA6G75DKGISWQMC7CR',
    aws_secret_access_key='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'
)

# Router
router = APIRouter(prefix="/campaigns", tags=["Marketing Campaigns"])


# Pydantic Models for Campaign Generation
class CampaignGenerationRequest(BaseModel):
    campaign_goal: str = Field(..., description="What is your campaign goal? (e.g., increase sales, brand awareness, customer retention)")
    campaign_title: str = Field(..., description="Campaign title")
    content_type: str = Field(..., description="Content type (e.g., social media posts, email marketing, blog content, advertisements)")
    target_audience: str = Field(..., description="Who is your target audience? (e.g., young adults, families, business professionals)")
    brand_tone: str = Field(..., description="Brand tone (e.g., friendly, professional, playful, authoritative, casual)")
    promotion_focus: str = Field(..., description="What do you want to promote? (e.g., new product, special offer, brand values)")
    
    class Config:
        schema_extra = {
            "example": {
                "campaign_goal": "Increase restaurant foot traffic and online orders",
                "campaign_title": "Taste the Difference Campaign",
                "content_type": "Social media posts and email marketing",
                "target_audience": "Food enthusiasts aged 25-45 in urban areas",
                "brand_tone": "Friendly and appetizing",
                "promotion_focus": "New seasonal menu items and weekend specials"
            }
        }


class BrandContentRequest(BaseModel):
    brand_tone: str = Field(..., description="Brand tone (e.g., friendly, professional, playful, casual, exciting)")
    content_type: str = Field(..., description="Content type: email or sms")
    promotion_content: str = Field(..., description="What do you want to promote?")
    
    class Config:
        schema_extra = {
            "example": {
                "brand_tone": "friendly and exciting",
                "content_type": "email",
                "promotion_content": "Our new summer collection with 30% off limited time offer"
            }
        }


class BrandContentResponse(BaseModel):
    status: str
    generated_content: str
    content_type: str
    brand_tone: str
    promotion_content: str
    generated_at: str


class AddCustomerRequest(BaseModel):
    customer_name: str = Field(..., description="Customer name")
    email: str = Field(..., description="Customer email address")
    phone: str = Field(..., description="Customer phone number")
    customer_type: str = Field(..., description="Customer type: frequent_diners, new, weekend_visitor, high_valued, lapsed_customer")
    
    class Config:
        schema_extra = {
            "example": {
                "customer_name": "John Doe",
                "email": "john.doe@example.com", 
                "phone": "+1234567890",
                "customer_type": "frequent_diners"
            }
        }


class AddCustomerResponse(BaseModel):
    status: str
    message: str
    customer_data: Dict[str, Any]
    records_created: int
    customer_type: str


class SendCampaignRequest(BaseModel):
    schedule_time: Optional[datetime] = Field(None, description="Optional schedule time for sending campaign (ISO format). If not provided, campaign will be sent immediately.")
    
    class Config:
        schema_extra = {
            "example": {
                "schedule_time": "2024-01-15T14:30:00"
            }
        }


class SaveToLibraryRequest(BaseModel):
    campaign_id: str = Field(..., description="The campaign ID to save to library")
    generated_content: str = Field(..., description="The generated content to save")
    content_type: str = Field(..., description="The content type of the campaign")
    
    class Config:
        schema_extra = {
            "example": {
                "campaign_id": "abc123",
                "generated_content": "This is the generated campaign content to save to library...",
                "content_type": "Email marketing"
            }
        }


class CampaignGenerationResponse(BaseModel):
    status: str
    campaign_data: Dict[str, Any]
    generated_at: str
    usage_tokens: Optional[int] = None


class SocialMediaCampaignRequest(BaseModel):
    campaign_goal: str = Field(..., description="What is your campaign goal?")
    campaign_title: str = Field(..., description="Campaign title")
    social_media_platform: str = Field(..., description="Social media platform (facebook, instagram, tiktok)")
    caption: str = Field(..., description="Post caption/description")
    visibility: str = Field(..., description="Who can see this post (public, private)")
    allow_comments: bool = Field(default=True, description="Allow users to comment")
    allow_duet: bool = Field(default=False, description="Allow duet (TikTok only)")
    allow_stitch: bool = Field(default=False, description="Allow stitch (TikTok only)")
    
    class Config:
        schema_extra = {
            "example": {
                "campaign_goal": "increase brand awareness",
                "campaign_title": "Summer Vibes Campaign",
                "social_media_platform": "tiktok",
                "caption": "Check out our amazing summer collection! #summer #fashion #trending",
                "visibility": "public",
                "allow_comments": True,
                "allow_duet": True,
                "allow_stitch": True
            }
        }


class SocialMediaCampaignResponse(BaseModel):
    status: str
    campaign_data: Dict[str, Any]
    upload_status: Dict[str, Any]
    platform_response: Optional[Dict[str, Any]] = None
    generated_at: str


@router.post("/generate-campaign", response_model=CampaignGenerationResponse)
async def generate_marketing_campaign(
    request: CampaignGenerationRequest,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):

    try:
        logger.info(f"🎯 Generating marketing campaign for user {current_user['email']}")
        
        # Check user permissions
        if current_user["role"] == "Non_Operators":
            raise HTTPException(
                status_code=403,
                detail="Access denied for non-operators."
            )
        
        # Initialize OpenAI client
        from openai import OpenAI
        client = OpenAI(
            api_key="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"
        )
        
        # Create comprehensive prompt for campaign generation
        campaign_prompt = f"""
        You are an expert marketing strategist and campaign creator. Generate a high-performing marketing campaign based on the following input.

        📋 CAMPAIGN REQUIREMENTS:
        • Goal: {request.campaign_goal}
        • Title: {request.campaign_title}
        • Content Type: {request.content_type}
        • Target Audience: {request.target_audience}
        • Brand Tone: {request.brand_tone}
        • Promotion Focus: {request.promotion_focus}

        Based on the content type, follow these specific formatting guidelines:

        {"-"*60}

        If the content type is **Email Marketing**, generate the following in a structured email format:
        • Subject line
        • Email body (with personalized greeting, compelling hook, benefit-driven copy, CTA, and signature)
        

        If the content type is **SMS** or **Text**, create a short, punchy, and personalized message:
        • Maximum 160 characters (if possible)
        • Clear and compelling CTA
        • Avoid links 

        {"-"*60}

        Now create the marketing content accordingly.
        """

        logger.info("🤖 Calling OpenAI GPT-4 for campaign generation...")
        
        # Generate campaign using OpenAI GPT-4
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system", 
                    "content": "You are a world-class marketing strategist and campaign creator with expertise in digital marketing, brand strategy, and customer psychology. Create comprehensive, actionable marketing campaigns that drive results."
                },
                {
                    "role": "user", 
                    "content": campaign_prompt
                }
            ],
            max_tokens=2500,
            temperature=0.7,
            top_p=0.9
        )
        
        campaign_content = response.choices[0].message.content
        usage_tokens = response.usage.total_tokens if response.usage else 0
        
        logger.info(f"✅ Campaign generated successfully with {usage_tokens} tokens")
        
        # Structure the campaign data
        campaign_data = {
            "campaign_title": request.campaign_title,
            "campaign_goal": request.campaign_goal,
            "content_type": request.content_type,
            "target_audience": request.target_audience,
            "brand_tone": request.brand_tone,
            "promotion_focus": request.promotion_focus,
            "generated_campaign": campaign_content,
            "campaign_id": str(uuid.uuid4()),
            "created_by": {
                "user_id": current_user["id"],
                "user_email": current_user["email"],
                "user_role": current_user["role"]
            },
            "campaign_metadata": {
                "tokens_used": usage_tokens,
                "model": "gpt-4",
                "generation_timestamp": datetime.now().isoformat()
            }
        }
        
        # Save campaign to database
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO marketing_campaigns 
                (user_id, campaign_title, campaign_goal, content_type, target_audience, 
                 brand_tone, promotion_focus, generated_content, campaign_id, tokens_used)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                current_user["id"],
                request.campaign_title,
                request.campaign_goal,
                request.content_type,
                request.target_audience,
                request.brand_tone,
                request.promotion_focus,
                campaign_content,
                campaign_data["campaign_id"],
                usage_tokens
            ))
            conn.commit()
            logger.info("💾 Campaign saved to database")
        except Exception as db_error:
            logger.warning(f"⚠️ Could not save to database: {db_error}")
            # Continue anyway - generation was successful
        
        # Update usage tracking
        try:
            await update_usage(
                current_user=current_user,
                conn=conn,
                used_ai_engagements=True
            )
        except Exception as usage_error:
            logger.warning(f"⚠️ Could not update usage tracking: {usage_error}")
        
        logger.info(f"🎉 Campaign generation completed for {current_user['email']}")
        
        return CampaignGenerationResponse(
            status="success",
            campaign_data=campaign_data,
            generated_at=datetime.now().isoformat(),
            usage_tokens=usage_tokens
        )
        
    except Exception as e:
        logger.error(f"❌ Error generating marketing campaign: {e}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate marketing campaign: {str(e)}"
        )


@router.post("/brand-content-generator", response_model=BrandContentResponse)
async def generate_brand_content(
        request: BrandContentRequest,
        current_user: dict = Depends(get_current_user),
        conn=Depends(get_db)
):
    """
    🎨 Brand Content Generator

    Simple endpoint that takes brand tone, content type (Email/SMS/Text), and what you want to promote,
    then generates content using GPT-4 accordingly.
    """
    try:
        logger.info(f"🎨 Generating brand content for user {current_user['email']}")

        # Check user permissions
        if current_user["role"] == "Non_Operators":
            raise HTTPException(
                status_code=403,
                detail="Access denied for non-operators."
            )

        # Validate content type (only Email and SMS/Text are allowed)
        allowed_types = ["email", "sms/text"]
        if request.content_type.lower() not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail="Content type must be either 'Email' or 'SMS/Text'"
            )

        # Initialize OpenAI client
        from openai import OpenAI
        client = OpenAI(
            api_key="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"  # Keep secret keys secure
        )

        # Create prompt based on content type
        if request.content_type.lower() == "email":
            prompt = f"""
            Create an email marketing content with the following specifications:

            Brand Tone: {request.brand_tone}
            What to Promote: {request.promotion_content}

            Please generate:
            1. Subject Line
            2. Email Body (including greeting, main content, and call-to-action)

            Make sure the tone is {request.brand_tone} and effectively promotes: {request.promotion_content}
            """
        else:  # SMS/Text
            prompt = f"""
            Create an SMS marketing message with the following specifications:

            Brand Tone: {request.brand_tone}
            What to Promote: {request.promotion_content}

            Requirements:
            - Keep it under 160 characters
            - Include a clear call-to-action
            - Make the tone {request.brand_tone}
            - Effectively promote: {request.promotion_content}
            """

        logger.info("🤖 Calling OpenAI GPT-4 for content generation...")

        # Generate content using OpenAI GPT-4
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert marketing copywriter specializing in compelling content that converts."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=1000,
            temperature=0.7,
            top_p=0.9
        )

        generated_content = response.choices[0].message.content or "Content generation failed"

        logger.info(f"✅ Content generated successfully")

        # Generate unique campaign ID
        campaign_id = str(uuid.uuid4())

        # Save content to campaign_library
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO campaign_library (
                    user_id, campaign_id, generated_content, content_type, saved_at
                ) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            """, (
                current_user["id"],
                campaign_id,
                generated_content,
                request.content_type
            ))
            conn.commit()
            logger.info(f"💾 Content saved to campaign_library with ID: {campaign_id}")
        except Exception as db_error:
            logger.error(f"❌ Failed to save to campaign_library: {db_error}")

        # Update usage tracking
        try:
            await update_usage(
                current_user=current_user,
                conn=conn,
                used_ai_engagements=True
            )
        except Exception as usage_error:
            logger.warning(f"⚠️ Could not update usage tracking: {usage_error}")

        logger.info(f"🎉 Brand content generation completed for {current_user['email']}")

        return BrandContentResponse(
            status="success",
            generated_content=generated_content,
            content_type=request.content_type,
            brand_tone=request.brand_tone,
            promotion_content=request.promotion_content,
            generated_at=datetime.now().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error generating brand content: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate brand content: {str(e)}"
        )


def init_marketing_tables():
    """Initialize marketing and customer tables"""
    try:
        from src.chat_gpt import DB_CONFIG
        import psycopg2
        
        # Ensure DB_CONFIG is properly formatted
        if isinstance(DB_CONFIG, dict):
            conn = psycopg2.connect(**DB_CONFIG)
        else:
            raise ValueError("DB_CONFIG is not a valid dictionary")
        
        cur = conn.cursor()
        
        # Create customers table
        # cur.execute("""
        #             CREATE TABLE IF NOT EXISTS customers (
        #                 id SERIAL PRIMARY KEY,
        #                 customer_id VARCHAR(100) UNIQUE NOT NULL,
        #                 customer_name VARCHAR(255),
        #                 email VARCHAR(255),
        #                 phone_number VARCHAR(50),
        #                 date DATE NOT NULL,
        #                 paid_amount DECIMAL(10,2) NOT NULL DEFAULT 0
        #             )
        #         """)

        # Create marketing campaigns table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS marketing_campaigns (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                campaign_title VARCHAR(255) NOT NULL,
                campaign_goal TEXT,
                content_type VARCHAR(255),
                target_audience TEXT,
                brand_tone VARCHAR(100),
                promotion_focus TEXT,
                generated_content TEXT,
                campaign_id VARCHAR(100) UNIQUE NOT NULL,
                tokens_used INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create campaign schedules table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS campaign_schedules (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                campaign_id VARCHAR(100) NOT NULL,
                campaign_title VARCHAR(255) NOT NULL,
                target_audience TEXT NOT NULL,
                status VARCHAR(50) NOT NULL DEFAULT 'scheduled',
                ctr DECIMAL(5,2) DEFAULT 0.00,
                date_of_submission TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                schedule_time TIMESTAMP WITH TIME ZONE NOT NULL,
                sent_at TIMESTAMP WITH TIME ZONE NULL,
                total_recipients INTEGER DEFAULT 0,
                successful_sends INTEGER DEFAULT 0,
                failed_sends INTEGER DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create campaign library table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS campaign_library (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                campaign_id VARCHAR(100) NOT NULL,
                generated_content TEXT NOT NULL,
                content_type VARCHAR(255) NOT NULL,
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # # Create social media campaigns table
        # cur.execute("""
        #     CREATE TABLE IF NOT EXISTS social_media_campaigns (
        #         id SERIAL PRIMARY KEY,
        #         user_id INTEGER NOT NULL,
        #         campaign_id VARCHAR(100) NOT NULL,
        #         campaign_title VARCHAR(255) NOT NULL,
        #         campaign_goal TEXT,
        #         platform VARCHAR(50) NOT NULL,
        #         media_url TEXT NOT NULL,
        #         caption TEXT,
        #         visibility VARCHAR(50),
        #         allow_comments BOOLEAN,
        #         allow_duet BOOLEAN,
        #         allow_stitch BOOLEAN,
        #         upload_status JSON,
        #         platform_response JSON,
        #         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        #     )
        # """)
        #
        conn.commit()
        conn.close()
        logger.info("✅ Marketing tables initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error initializing marketing tables: {e}")
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()
        return False



async def get_customer_insights(conn):
    try:
        cur = conn.cursor()
        logger.info("🔍 Starting customer insights analysis...")

        # Check if table exists and has data first
        cur.execute("SELECT COUNT(*) FROM customer")
        result = cur.fetchone()
        total_count = result["count"] if result else 0
        logger.info(f"📊 Total records in customers table: {total_count}")
        
        if total_count == 0:
            logger.warning("⚠️ No data found in customers table")
            return {
                "status": "success",
                "data": {
                    "total_customers": 0,
                    "frequent_diners": 0,
                    "weekend_visitors": 0,
                    "high_valued_customers": 0,
                    "lapsed_customers": 0,
                    "new_customers": 0
                },
                "message": "No customer data available",
                "generated_at": datetime.now().isoformat()
            }

        # Query 1: Total unique customers
        logger.info("🔍 Query 1: Total unique customers")
        cur.execute("SELECT COUNT(DISTINCT customer_id) FROM customer")
        result = cur.fetchone()
        total_customers = result["count"] if result and result.get("count") is not None else 0
        logger.info(f"✅ Total customers: {total_customers}")

        # Query 2: Frequent diners (more than 5 visits)
        logger.info("🔍 Query 2: Frequent diners")
        cur.execute("""
            SELECT COUNT(*) FROM (
                SELECT customer_id FROM customer GROUP BY customer_id HAVING COUNT(*) > 5
            ) AS frequent
        """)
        result = cur.fetchone()
        frequent_diners = result["count"] if result and result.get("count") is not None else 0
        logger.info(f"✅ Frequent diners: {frequent_diners}")

        # Query 3: Weekend visitors
        logger.info("🔍 Query 3: Weekend visitors")
        cur.execute("""
            SELECT COUNT(DISTINCT customer_id)
            FROM customer
            WHERE visit_date IS NOT NULL 
            AND visit_date != '' 
            AND EXTRACT(DOW FROM visit_date::DATE) IN (0, 6)
        """)
        result = cur.fetchone()
        weekend_visitors = result["count"] if result and result.get("count") is not None else 0
        logger.info(f"✅ Weekend visitors: {weekend_visitors}")

        # Query 4: High value customers (spent more than $500)
        logger.info("🔍 Query 4: High value customers")
        cur.execute("""
            SELECT COUNT(*) FROM (
                SELECT customer_id FROM customer GROUP BY customer_id HAVING SUM(paid_amount) > 500
            ) AS high_spenders
        """)
        result = cur.fetchone()
        high_value = result["count"] if result and result.get("count") is not None else 0
        logger.info(f"✅ High value customers: {high_value}")

        # Query 5: Lapsed customers (haven't visited in 30 days)
        logger.info("🔍 Query 5: Lapsed customers")
        thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).date()
        cur.execute("""
            SELECT COUNT(*) FROM (
                SELECT customer_id, MAX(visit_date::DATE) AS last_visit
                FROM customer
                WHERE visit_date IS NOT NULL AND visit_date != ''
                GROUP BY customer_id
                HAVING MAX(visit_date::DATE) < %s
            ) AS lapsed_customers
        """, (thirty_days_ago,))
        result = cur.fetchone()
        lapsed = result["count"] if result and result.get("count") is not None else 0
        logger.info(f"✅ Lapsed customers: {lapsed}")

        # Query 6: New customers (first visit in last 7 days)
        logger.info("🔍 Query 6: New customers")
        seven_days_ago = (datetime.utcnow() - timedelta(days=7)).date()
        cur.execute("""
            SELECT COUNT(*) FROM (
                SELECT customer_id, MIN(visit_date::DATE) AS first_visit
                FROM customer
                WHERE visit_date IS NOT NULL AND visit_date != ''
                GROUP BY customer_id
                HAVING MIN(visit_date::DATE) >= %s
            ) AS new_customers
        """, (seven_days_ago,))
        result = cur.fetchone()
        new_customers = result["count"] if result and result.get("count") is not None else 0
        logger.info(f"✅ New customers: {new_customers}")

        response_data = {
            "status": "success",
            "data": {
                "total_customers": total_customers,
                "frequent_diners": frequent_diners,
                "weekend_visitors": weekend_visitors,
                "high_valued_customers": high_value,
                "lapsed_customers": lapsed,
                "new_customers": new_customers
            },
            "generated_at": datetime.now().isoformat()
        }
        
        logger.info(f"✅ Customer insights generated successfully: {response_data}")
        return response_data

    except Exception as e:
        logger.error(f"❌ Error in get_customer_insights: {e}")
        logger.error(f"❌ Error type: {type(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/customer-insights")
async def customer_insights(
    current_user: dict = Depends(get_current_user),
    conn=Depends(get_db)
):
    return await get_customer_insights(conn)


@router.get("/latest-campaign")
async def get_latest_campaign(
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    📋 Get Latest Generated Campaign
    
    Retrieve the most recent AI-generated campaign for the current user.
    Returns only the latest campaign based on creation date.
    
    Returns:
        The most recent generated campaign content and metadata
    """
    try:
        logger.info(f"🔍 Fetching latest campaign for user {current_user['email']}")
        
        # Check user permissions
        if current_user["role"] == "Non_Operators":
            raise HTTPException(
                status_code=403,
                detail="Access denied for non-operators."
            )
        
        cur = conn.cursor()
        
        # Get the most recent campaign for the user
        cur.execute("""
            SELECT 
                campaign_id,
                campaign_title,
                campaign_goal,
                content_type,
                target_audience,
                brand_tone,
                promotion_focus,
                generated_content,
                created_at,
                tokens_used
            FROM marketing_campaigns 
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (current_user["id"],))
        
        result = cur.fetchone()
        
        if not result:
            logger.warning(f"⚠️ No campaigns found for user {current_user['id']}")
            raise HTTPException(
                status_code=404,
                detail="No campaigns found. Please generate a campaign first."
            )
        
        campaign_data = {
            "campaign_id": result["campaign_id"],
            "campaign_title": result["campaign_title"],
            "campaign_goal": result["campaign_goal"],
            "content_type": result["content_type"],
            "target_audience": result["target_audience"],
            "brand_tone": result["brand_tone"],
            "promotion_focus": result["promotion_focus"],
            "generated_campaign": result["generated_content"],
            "created_at": result["created_at"].isoformat() if result["created_at"] else None,
            "tokens_used": result["tokens_used"]
        }
        
        logger.info(f"✅ Latest campaign retrieved successfully for user {current_user['email']}")
        
        return {
            "status": "success",
            "data": campaign_data,
            "message": "Latest campaign retrieved successfully",
            "retrieved_at": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error retrieving latest campaign for user {current_user['id']}: {e}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve latest campaign: {str(e)}"
        )


@router.post("/social-media-campaign", response_model=SocialMediaCampaignResponse)
async def create_social_media_campaign(
    campaign_goal: str = Form(..., description="What is your campaign goal?"),
    campaign_title: str = Form(..., description="Campaign title"),
    social_media_platform: str = Form(..., description="Social media platform (facebook, instagram, tiktok)"),
    caption: str = Form(..., description="Post caption/description"),
    visibility: str = Form(..., description="Who can see this post (public, private)"),
    allow_comments: bool = Form(default=True, description="Allow users to comment"),
    allow_duet: bool = Form(default=False, description="Allow duet (TikTok only)"),
    allow_stitch: bool = Form(default=False, description="Allow stitch (TikTok only)"),
    media_file: UploadFile = File(..., description="Video or image file to upload"),
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    🚀 Create & Post Social Media Campaign

    Upload media and create a social media campaign that gets posted directly to your chosen platform.

    Supported Platforms:
    - 📘 Facebook (images, videos)
    - 📸 Instagram (images, videos, stories)
    - 🎵 TikTok (videos with duet/stitch options)

    Features:
    - File upload to secure cloud storage
    - Platform-specific optimization
    - Privacy controls (public/private)
    - Interaction settings (comments, duet, stitch)
    - Campaign tracking and analytics

    Returns:
        Campaign details, upload status, and platform posting results
    """
    try:
        logger.info(f"🎯 Creating social media campaign for user {current_user['email']} on {social_media_platform}")
        
        # Check user permissions
        if current_user["role"] == "Non_Operators":
            raise HTTPException(
                status_code=403,
                detail="Access denied for non-operators."
            )
        
        # Validate platform
        valid_platforms = ["facebook", "instagram", "tiktok"]
        if social_media_platform.lower() not in valid_platforms:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid platform. Must be one of: {', '.join(valid_platforms)}"
            )
        
        # Validate visibility
        valid_visibility = ["public", "private"]
        if visibility.lower() not in valid_visibility:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid visibility. Must be one of: {', '.join(valid_visibility)}"
            )
        
        # Validate file type
        if not media_file.content_type:
            raise HTTPException(status_code=400, detail="Could not determine file type")
            
        allowed_types = [
            "image/jpeg", "image/png", "image/gif", "image/webp",
            "video/mp4", "video/avi", "video/mov", "video/wmv", "video/quicktime"
        ]
        
        if media_file.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type. Allowed: images (JPEG, PNG, GIF, WebP) and videos (MP4, AVI, MOV, WMV)"
            )
        
        # Generate campaign ID
        campaign_id = str(uuid.uuid4().hex[:12])
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Upload file to S3
        try:
            # Create S3 path
            user_folder = f"user_{current_user['id']}"
            platform_folder = social_media_platform.lower()
            s3_folder = f"campaigns/social_media/{user_folder}/{platform_folder}/{campaign_id}"
            
            # Get file extension
            file_extension = Path(media_file.filename or "file").suffix.lower()
            if not file_extension:
                file_extension = ".mp4" if "video" in media_file.content_type else ".jpg"
            
            # Generate filename
            filename = f"{campaign_title.lower().replace(' ', '_')}_{timestamp}{file_extension}"
            s3_key = f"{s3_folder}/{filename}"
            
            # Upload to S3
            content = await media_file.read()
            s3_client.put_object(
                Bucket=BUCKET_NAME,
                Key=s3_key,
                Body=content,
                ContentType=media_file.content_type,
                Metadata={
                    "campaign_id": campaign_id,
                    "user_id": str(current_user["id"]),
                    "platform": social_media_platform,
                    "original_filename": media_file.filename or "unknown"
                }
            )
            
            media_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}"
            
            upload_status = {
                "success": True,
                "media_url": media_url,
                "file_size": len(content),
                "file_type": media_file.content_type,
                "s3_key": s3_key
            }
            
            logger.info(f"✅ Media uploaded to S3: {s3_key}")
            
        except Exception as e:
            logger.error(f"❌ S3 upload failed: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to upload media file: {str(e)}"
            )
        
        # Platform-specific posting logic
        platform_response = {}
        
        try:
            if social_media_platform.lower() == "tiktok":
                platform_response = await post_to_tiktok(
                    media_url=media_url,
                    caption=caption,
                    visibility=visibility,
                    allow_comments=allow_comments,
                    allow_duet=allow_duet,
                    allow_stitch=allow_stitch,
                    user_id=current_user["id"]
                )
            elif social_media_platform.lower() == "instagram":
                platform_response = await post_to_instagram(
                    media_url=media_url,
                    caption=caption,
                    visibility=visibility,
                    allow_comments=allow_comments,
                    user_id=current_user["id"]
                )
            elif social_media_platform.lower() == "facebook":
                platform_response = await post_to_facebook(
                    media_url=media_url,
                    caption=caption,
                    visibility=visibility,
                    allow_comments=allow_comments,
                    user_id=current_user["id"]
                )
                
        except Exception as e:
            logger.error(f"❌ Platform posting failed for {social_media_platform}: {e}")
            platform_response = {
                "success": False,
                "error": str(e),
                "message": f"Media uploaded successfully but posting to {social_media_platform} failed"
            }
        
        # Save campaign to database
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO social_media_campaigns (
                    user_id, campaign_id, campaign_title, campaign_goal,
                    platform, media_url, caption, visibility,
                    allow_comments, allow_duet, allow_stitch,
                    upload_status, platform_response, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP
                )
            """, (
                current_user["id"], campaign_id, campaign_title, campaign_goal,
                social_media_platform, media_url, caption, visibility,
                allow_comments, allow_duet, allow_stitch,
                json.dumps(upload_status), json.dumps(platform_response)
            ))
            conn.commit()
            
            logger.info(f"✅ Social media campaign saved to database: {campaign_id}")
            
        except Exception as e:
            logger.error(f"❌ Error saving social media campaign to database: {e}")
            # Continue even if database save fails
        
        # Update usage tracking
        try:
            await update_usage(
                current_user=current_user,
                conn=conn,
                used_ai_engagements=True
            )
        except Exception as e:
            logger.warning(f"Failed to update usage: {str(e)}")
        
        return {
            "status": "success",
            "campaign_data": {
                "campaign_id": campaign_id,
                "campaign_title": campaign_title,
                "campaign_goal": campaign_goal,
                "platform": social_media_platform,
                "caption": caption,
                "visibility": visibility,
                "allow_comments": allow_comments,
                "allow_duet": allow_duet,
                "allow_stitch": allow_stitch,
                "media_url": media_url
            },
            "upload_status": upload_status,
            "platform_response": platform_response,
            "generated_at": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error creating social media campaign: {e}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create social media campaign: {str(e)}"
        )


# Social Media API Integration Functions
async def post_to_tiktok(media_url: str, caption: str, visibility: str, 
                        allow_comments: bool, allow_duet: bool, allow_stitch: bool, user_id: int):
    """
    Post video to TikTok using TikTok API
    
    Note: This requires TikTok Developer Account and OAuth setup
    """
    try:
        # TODO: Implement actual TikTok API integration
        # Required: TikTok Developer App, OAuth token, API credentials
        
        logger.info(f"📱 Posting to TikTok: {caption[:50]}...")
        
        # Placeholder response - replace with actual TikTok API call
        return {
            "success": True,
            "platform": "tiktok",
            "post_id": f"tiktok_{user_id}_{int(datetime.now().timestamp())}",
            "post_url": f"https://tiktok.com/@username/video/{user_id}",
            "message": "Video uploaded to TikTok successfully!",
            "engagement_settings": {
                "allow_comments": allow_comments,
                "allow_duet": allow_duet,
                "allow_stitch": allow_stitch
            },
            "visibility": visibility,
            "note": "This is a simulation. Actual TikTok API integration required."
        }
        
    except Exception as e:
        logger.error(f"❌ TikTok posting failed: {e}")
        return {
            "success": False,
            "platform": "tiktok",
            "error": str(e),
            "message": "Failed to post to TikTok"
        }


async def post_to_instagram(media_url: str, caption: str, visibility: str, 
                           allow_comments: bool, user_id: int):
    """
    Post media to Instagram using Instagram Basic Display API
    
    Note: This requires Facebook Developer Account and Instagram Business Account
    """
    try:
        # TODO: Implement actual Instagram API integration
        # Required: Facebook App, Instagram Business Account, Access Token
        
        logger.info(f"📸 Posting to Instagram: {caption[:50]}...")
        
        # Placeholder response - replace with actual Instagram API call
        return {
            "success": True,
            "platform": "instagram",
            "post_id": f"instagram_{user_id}_{int(datetime.now().timestamp())}",
            "post_url": f"https://instagram.com/p/{user_id}",
            "message": "Media uploaded to Instagram successfully!",
            "engagement_settings": {
                "allow_comments": allow_comments
            },
            "visibility": visibility,
            "note": "This is a simulation. Actual Instagram API integration required."
        }
        
    except Exception as e:
        logger.error(f"❌ Instagram posting failed: {e}")
        return {
            "success": False,
            "platform": "instagram",
            "error": str(e),
            "message": "Failed to post to Instagram"
        }


async def post_to_facebook(media_url: str, caption: str, visibility: str, 
                          allow_comments: bool, user_id: int):
    """
    Post media to Facebook using Facebook Graph API
    
    Note: This requires Facebook Developer Account and Page Access Token
    """
    try:
        # TODO: Implement actual Facebook API integration
        # Required: Facebook App, Page Access Token, Graph API setup
        
        logger.info(f"📘 Posting to Facebook: {caption[:50]}...")
        
        # Placeholder response - replace with actual Facebook API call
        return {
            "success": True,
            "platform": "facebook",
            "post_id": f"facebook_{user_id}_{int(datetime.now().timestamp())}",
            "post_url": f"https://facebook.com/{user_id}/posts/{int(datetime.now().timestamp())}",
            "message": "Media uploaded to Facebook successfully!",
            "engagement_settings": {
                "allow_comments": allow_comments
            },
            "visibility": visibility,
            "note": "This is a simulation. Actual Facebook Graph API integration required."
        }
        
    except Exception as e:
        logger.error(f"❌ Facebook posting failed: {e}")
        return {
            "success": False,
            "platform": "facebook",
            "error": str(e),
            "message": "Failed to post to Facebook"
        }


@router.post("/send-campaign/{campaign_id}")
async def send_campaign_to_customers(
    campaign_id: str,
    request: Optional[SendCampaignRequest] = None,
    current_user: dict = Depends(get_current_user),
    conn=Depends(get_db)
):
    """
    📧 Send Campaign to Target Customers
    
    Retrieves a campaign by ID and either sends it immediately or schedules it for later
    based on the schedule_time parameter.
    
    Parameters:
    - campaign_id: The ID of the campaign to send
    - schedule_time: Optional datetime for scheduling (ISO format). If not provided, sends immediately.
    
    Target Audiences:
    - All customers
    - Frequent diners 
    - Weekend visitors
    - High-valued customers
    - Lapsed customers
    - New customers
    
    Content Types:
    - Email (if content_type contains 'email')
    - SMS (if content_type contains 'SMS')
    """
    try:
        logger.info(f"🚀 Starting campaign send for campaign_id {campaign_id}")
        
        # Check user permissions
        if current_user["role"] == "Non_Operators":
            raise HTTPException(
                status_code=403,
                detail="Access denied for non-operators."
            )
        
        cur = conn.cursor()
        
        # Get campaign details
        cur.execute("""
            SELECT 
                campaign_id,
                campaign_title,
                campaign_goal,
                content_type,
                target_audience,
                brand_tone,
                promotion_focus,
                generated_content,
                created_at,
                user_id
            FROM marketing_campaigns 
            WHERE campaign_id = %s
        """, (campaign_id,))
        
        campaign = cur.fetchone()
        if not campaign:
            raise HTTPException(
                status_code=404,
                detail=f"Campaign with ID {campaign_id} not found"
            )
        
        # Check if current user owns this campaign or has permission
        if (current_user["role"] not in ["SUPER_ADMIN"] and 
            campaign["user_id"] != current_user["id"]):
            raise HTTPException(
                status_code=403,
                detail="Access denied. You can only send your own campaigns."
            )
        
        logger.info(f"📋 Campaign found: {campaign['campaign_title']}")
        logger.info(f"🎯 Target audience: {campaign['target_audience']}")
        logger.info(f"📱 Content type: {campaign['content_type']}")
        
        # Get target customers based on audience
        target_customers = await get_target_customers(campaign['target_audience'], conn)
        
        if not target_customers:
            return {
                "status": "warning",
                "message": f"No customers found for target audience: {campaign['target_audience']}",
                "campaign_info": {
                    "campaign_id": campaign_id,
                    "campaign_title": campaign['campaign_title'],
                    "target_audience": campaign['target_audience']
                },
                "sent_count": 0,
                "timestamp": datetime.now().isoformat()
            }
        
        # Handle optional request body
        if request is None:
            request = SendCampaignRequest(schedule_time=None)
        
        # Check if scheduling is requested
        if request.schedule_time:
            # Convert current time to UTC (timezone-aware)
            current_time = datetime.now(timezone.utc)

            # If schedule_time is naive (no timezone), assume it's in UTC
            schedule_time = request.schedule_time
            if schedule_time.tzinfo is None:
                schedule_time = schedule_time.replace(tzinfo=timezone.utc)

            # Validate the schedule time is in the future
            if schedule_time <= current_time:
                raise HTTPException(
                    status_code=400,
                    detail="Schedule time must be in the future"
                )
            # Save scheduled campaign to database
            try:
                cur.execute("""
                    INSERT INTO campaign_schedules (
                        user_id, campaign_id, campaign_title, target_audience,
                        status, date_of_submission, schedule_time, total_recipients
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    current_user["id"],
                    campaign_id,
                    campaign['campaign_title'],
                    campaign['target_audience'],
                    'scheduled',
                    datetime.now(timezone.utc),
                    request.schedule_time,
                    len(target_customers)
                ))
                conn.commit()
                
                logger.info(f"✅ Campaign scheduled successfully for {request.schedule_time}")
                
                return {
                    "status": "scheduled",
                    "message": f"Campaign scheduled successfully for {request.schedule_time.strftime('%Y-%m-%d %H:%M:%S')}",
                    "campaign_info": {
                        "campaign_id": campaign_id,
                        "campaign_title": campaign['campaign_title'],
                        "target_audience": campaign['target_audience'],
                        "content_type": campaign['content_type']
                    },
                    "schedule_details": {
                        "schedule_time": request.schedule_time.isoformat(),
                        "total_recipients": len(target_customers),
                        "status": "scheduled"
                    },
                    "timestamp": datetime.now().isoformat()
                }
                
            except Exception as e:
                logger.error(f"❌ Error saving scheduled campaign: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to schedule campaign: {str(e)}"
                )
        
        else:
            # Send immediately
            logger.info("📧 Sending campaign immediately...")
            
            # Determine communication method
            content_type_lower = campaign['content_type'].lower()
            is_email = 'email' in content_type_lower
            is_sms = 'sms' in content_type_lower
            
            # Send campaign messages
            sent_count = 0
            failed_count = 0
            sent_details = []
            
            for customer in target_customers:
                try:
                    if is_email and customer.get('email'):
                        # Send email
                        success = await send_campaign_email(
                            customer['email'],
                            customer.get('customer_name', 'Valued Customer'),
                            campaign
                        )
                        if success:
                            sent_count += 1
                            sent_details.append({
                                "type": "email",
                                "recipient": customer['email'],
                                "customer_name": customer.get('customer_name', ''),
                                "status": "sent"
                            })
                        else:
                            failed_count += 1
                            sent_details.append({
                                "type": "email",
                                "recipient": customer['email'],
                                "customer_name": customer.get('customer_name', ''),
                                "status": "failed"
                            })
                    
                    elif is_sms and customer.get('phone'):
                        # Send SMS
                        success = await send_campaign_sms(
                            customer['phone'],
                            customer.get('customer_name', 'Valued Customer'),
                            campaign
                        )
                        if success:
                            sent_count += 1
                            sent_details.append({
                                "type": "sms",
                                "recipient": customer['phone'],
                                "customer_name": customer.get('customer_name', ''),
                                "status": "sent"
                            })
                        else:
                            failed_count += 1
                            sent_details.append({
                                "type": "sms",
                                "recipient": customer['phone'],
                                "customer_name": customer.get('customer_name', ''),
                                "status": "failed"
                            })
                
                except Exception as e:
                    logger.error(f"❌ Error sending to customer {customer.get('customer_email', customer.get('phone_number', 'unknown'))}: {str(e)}")
                    failed_count += 1
                    sent_details.append({
                        "type": "email" if is_email else "sms",
                        "recipient": customer.get('customer_email', customer.get('phone_number', 'unknown')),
                        "customer_name": customer.get('customer_name', ''),
                        "status": "error",
                        "error": str(e)
                    })
            
            # Calculate CTR (simplified - using sent_count as engagement metric)
            ctr = (sent_count / len(target_customers) * 100) if target_customers else 0
            
            # Save immediate send record to database
            try:
                cur.execute("""
                    INSERT INTO campaign_schedules (
                        user_id, campaign_id, campaign_title, target_audience,
                        status, ctr, date_of_submission, schedule_time, sent_at,
                        total_recipients, successful_sends, failed_sends
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    current_user["id"],
                    campaign_id,
                    campaign['campaign_title'],
                    campaign['target_audience'],
                    'sent',
                    ctr,
                    datetime.now(timezone.utc),
                    datetime.now(timezone.utc),  # schedule_time same as sent_at for immediate sends
                    datetime.now(timezone.utc),
                    len(target_customers),
                    sent_count,
                    failed_count
                ))
                conn.commit()
                logger.info("💾 Campaign send record saved to database")
            except Exception as e:
                logger.warning(f"⚠️ Could not save campaign send record: {e}")
            
            logger.info(f"✅ Campaign send completed: {sent_count} sent, {failed_count} failed")
            
            return {
                "status": "sent",
                "message": f"Campaign sent immediately to {sent_count} customers",
                "campaign_info": {
                    "campaign_id": campaign_id,
                    "campaign_title": campaign['campaign_title'],
                    "target_audience": campaign['target_audience'],
                    "content_type": campaign['content_type']
                },
                "results": {
                    "total_customers_found": len(target_customers),
                    "sent_count": sent_count,
                    "failed_count": failed_count,
                    "ctr": round(ctr, 2),
                    "communication_method": "email" if is_email else "sms" if is_sms else "unknown"
                },
                "details": sent_details,
                "timestamp": datetime.now().isoformat()
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error sending campaign {campaign_id}: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send campaign: {str(e)}"
        )


async def get_target_customers(target_audience: str, conn) -> List[Dict[str, Any]]:
    """Get customers based on target audience type"""
    try:
        cur = conn.cursor()
        customers = []
        
        target_audience_lower = target_audience.lower()
        
        if "all customers" in target_audience_lower:
            # Get all customers
            cur.execute("""
                SELECT DISTINCT email, customer_name, phone,
                       SUM(paid_amount) as total_spent
                FROM customer
                WHERE email IS NOT NULL AND email != ''
                GROUP BY email, customer_name, phone
            """)

            
        elif "frequent diners" in target_audience_lower:
            # Customers with more than 5 visits
            cur.execute("""
                SELECT email, customer_name, phone, 
                       SUM(paid_amount) as total_spent, COUNT(*) as visit_count
                FROM customer 
                WHERE email IS NOT NULL AND email != ''
                GROUP BY email, customer_name, phone
                HAVING COUNT(*) > 5
            """)
            
        elif "weekend visitor" in target_audience_lower:
            # Customers who visited on weekends
            cur.execute("""
                SELECT DISTINCT email, customer_name, phone, 
                       SUM(paid_amount) as total_spent
                FROM customer 
                WHERE email IS NOT NULL AND email != ''
                AND visit_date IS NOT NULL AND visit_date != '' 
                AND EXTRACT(DOW FROM visit_date::DATE) IN (0, 6)
                GROUP BY email, customer_name, phone
            """)
            
        elif "high-valued customers" in target_audience_lower or "high valued customer" in target_audience_lower:
            # Customers who spent more than $500
            cur.execute("""
                SELECT email, customer_name, phone, 
                       SUM(paid_amount) as total_spent
                FROM customer 
                WHERE email IS NOT NULL AND email != ''
                GROUP BY email, customer_name, phone
                HAVING SUM(paid_amount) > 500
            """)
            
        elif "lapsed customer" in target_audience_lower:
            # Customers who haven't visited in 30 days
            thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).date()
            cur.execute("""
                SELECT email, customer_name, phone, 
                       SUM(paid_amount) as total_spent, MAX(visit_date::DATE) as last_visit
                FROM customer 
                WHERE email IS NOT NULL AND email != ''
                AND visit_date IS NOT NULL AND visit_date != ''
                GROUP BY email, customer_name, phone
                HAVING MAX(visit_date::DATE) < %s
            """, (thirty_days_ago,))
            
        elif "new" in target_audience_lower:
            # Customers with first visit in last 7 days
            seven_days_ago = (datetime.utcnow() - timedelta(days=7)).date()
            cur.execute("""
                SELECT email, customer_name, phone,
                       SUM(paid_amount) as total_spent, MIN(visit_date::DATE) as first_visit
                FROM customer
                WHERE email IS NOT NULL AND email != ''
                AND visit_date IS NOT NULL AND visit_date != ''
                GROUP BY email, customer_name, phone
                HAVING MIN(visit_date::DATE) >= %s
            """, (seven_days_ago,))

            
        else:
            # Default to all customers if target audience not recognized
            logger.warning(f"⚠️ Unrecognized target audience: {target_audience}, defaulting to all customers")
            cur.execute("""
                SELECT DISTINCT email, customer_name, phone, 
                       SUM(paid_amount) as total_spent
                FROM customer 
                WHERE email IS NOT NULL AND email != ''
                GROUP BY email, customer_name, phone
            """)
        
        results = cur.fetchall()
        customers = [dict(row) for row in results] if results else []
        
        logger.info(f"📊 Found {len(customers)} customers for target audience: {target_audience}")
        return customers
        
    except Exception as e:
        logger.error(f"❌ Error getting target customers for {target_audience}: {str(e)}")
        return []


async def send_campaign_email(email: str, customer_name: str, campaign: dict) -> bool:
    """Send campaign email to customer with personalized content"""
    try:
        from src.smtp_send_email import send_email_api
        
        generated_content = campaign['generated_content']
        
        # Parse subject line and email body from generated_content
        subject_line = ""
        email_body = ""
        
        if "Subject Line:" in generated_content:
            # Extract subject line
            content_parts = generated_content.split("Subject Line:", 1)
            if len(content_parts) > 1:
                subject_part = content_parts[1].split("Email Body:", 1)[0].strip()
                subject_line = subject_part
                
                # Extract email body
                if "Email Body:" in generated_content:
                    body_part = generated_content.split("Email Body:", 1)[1].strip()
                    email_body = body_part
                else:
                    email_body = generated_content
        else:
            # Fallback if no structured format
            subject_line = f"{campaign['campaign_title']} - {campaign['promotion_focus']}"
            email_body = generated_content
        
        # Personalize the content by replacing placeholders
        personalized_subject = subject_line.replace("[Customer's Name]", customer_name)
        personalized_subject = personalized_subject.replace("[Customer Name]", customer_name)
        personalized_subject = personalized_subject.replace("{customer_name}", customer_name)
        
        personalized_body = email_body.replace("[Customer's Name]", customer_name)
        personalized_body = personalized_body.replace("[Customer Name]", customer_name) 
        personalized_body = personalized_body.replace("{customer_name}", customer_name)
        
        # Convert plain text to HTML with proper formatting
        html_body = personalized_body.replace('\n\n', '</p><p style="margin: 10px 0; color: #555;">')
        html_body = html_body.replace('\n', '<br>')
        
        # Create professional HTML email template
        html_content = f"""
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{personalized_subject}</title>
        </head>
        <body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f4f4f4;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; padding: 0;">
                
                <!-- Header -->
                <div style="background-color: #2c3e50; padding: 20px; text-align: center;">
                    <h1 style="color: #ffffff; margin: 0; font-size: 24px;">{campaign['campaign_title']}</h1>
                </div>
                
                <!-- Main Content -->
                <div style="padding: 30px 20px;">
                    <p style="margin: 0 0 20px 0; color: #555; font-size: 16px; line-height: 1.6;">
                        {html_body}
                    </p>
                </div>
                
                <!-- Footer -->
                <div style="background-color: #ecf0f1; padding: 20px; text-align: center; border-top: 1px solid #bdc3c7;">
                    <p style="margin: 0; color: #7f8c8d; font-size: 14px;">
                        <strong>Campaign:</strong> {campaign['campaign_goal']}<br>
                        <strong>Promotion:</strong> {campaign['promotion_focus']}
                    </p>
                    <p style="margin: 10px 0 0 0; color: #95a5a6; font-size: 12px;">
                        Thank you for being a valued customer!
                    </p>
                </div>
                
            </div>
        </body>
        </html>
        """
        
        logger.info(f"📧 Sending email to {email} with subject: {personalized_subject[:50]}...")
        
        return send_email_api(email, personalized_subject, html_content)
        
    except Exception as e:
        logger.error(f"❌ Error sending campaign email to {email}: {str(e)}")
        return False


async def send_campaign_sms(phone_number: str, customer_name: str, campaign: dict) -> bool:
    """Send campaign SMS to customer"""
    try:
        from src.chat_gpt import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER
        
        try:
            from twilio.rest import Client
        except ImportError:
            logger.error("❌ Twilio library not installed. Install with: pip install twilio")
            return False
        
        # Create SMS message (SMS has character limits)
        message_text = f"Hi {customer_name}! {campaign['campaign_title']}: {campaign['promotion_focus']}. {campaign['generated_content'][:1000]}..."
        
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=message_text,
            from_=TWILIO_PHONE_NUMBER,
            to=phone_number
        )
        
        return True if message.sid else False
        
    except Exception as e:
        logger.error(f"❌ Error sending campaign SMS to {phone_number}: {str(e)}")
        return False


@router.get("/all-campaigns")
async def get_all_campaigns(
        current_user: dict = Depends(get_current_user),
        conn=Depends(get_db)
):
    """
    📋 Get All Generated Campaigns

    Retrieve all AI-generated campaigns for the current user.
    Returns campaigns ordered by creation date (newest first).

    Returns:
        List of all generated campaigns with content and metadata
    """
    try:
        logger.info(f"🔍 Fetching all campaigns for user {current_user['email']}")

        # Check user permissions
        if current_user["role"] == "Non_Operators":
            raise HTTPException(
                status_code=403,
                detail="Access denied for non-operators."
            )

        cur = conn.cursor()

        # Get all campaigns for the user
        cur.execute("""
            SELECT 
                campaign_id,
                campaign_title,
                target_audience,
                status,
                date_of_submission, 
                ctr
            FROM campaign_schedules 
            WHERE user_id = %s
            ORDER BY created_at DESC
        """, (current_user["id"],))

        results = cur.fetchall()

        if not results:
            logger.warning(f"⚠️ No campaigns found for user {current_user['id']}")
            return {
                "status": "success",
                "data": [],
                "count": 0,
                "message": "No campaigns found. Generate your first campaign!",
                "retrieved_at": datetime.now().isoformat()
            }

        campaigns_data = []
        for result in results:
            campaign_data = {
                "campaign_id": result["campaign_id"],
                "campaign_title": result["campaign_title"],
                "target_audience": result["target_audience"],
                "status": result["status"],
                "date_of_submission": result["date_of_submission"],
                "ctr": result["ctr"],
            }
            campaigns_data.append(campaign_data)

        logger.info(f"✅ {len(campaigns_data)} campaigns retrieved successfully for user {current_user['email']}")

        return {
            "status": "success",
            "data": campaigns_data,
            "count": len(campaigns_data),
            "message": f"Successfully retrieved {len(campaigns_data)} campaigns",
            "retrieved_at": datetime.now().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error retrieving campaigns for user {current_user['id']}: {e}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve campaigns: {str(e)}"
        )

@router.get("/customers-by-type")
async def get_customers_by_type(
    customer_type: str,
    current_user: dict = Depends(get_current_user),
    conn=Depends(get_db)
):
    """
    👥 Get Customers by Type
    
    Returns customer details based on customer type with the same logic as customer insights.
    
    Parameters:
    - customer_type: One of ('All', 'Frequent diners', 'Weekend visitor', 'High-valued', 'Lapsed customer')
    
    Returns:
    - Name, Email, Phone, Type, Date for each customer
    """
    try:
        logger.info(f"🔍 Fetching customers by type: {customer_type}")
        
        # Check user permissions
        if current_user["role"] == "Non_Operators":
            raise HTTPException(
                status_code=403,
                detail="Access denied for non-operators."
            )
        
        # Validate customer_type parameter
        valid_types = ['All', 'Frequent diners', 'Weekend visitor', 'High-valued', 'Lapsed customer']
        if customer_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid customer_type. Must be one of: {', '.join(valid_types)}"
            )
        
        cur = conn.cursor()
        customers = []
        
        if customer_type == "All":
            # Get all customers with their types
            customers = await get_all_customers_with_types(cur)
        else:
            # Get customers of specific type
            customers = await get_customers_by_specific_type(cur, customer_type)
        
        logger.info(f"✅ Found {len(customers)} customers of type: {customer_type}")
        
        return {
            "status": "success",
            "customer_type": customer_type,
            "total_customers": len(customers),
            "customers": customers,
            "retrieved_at": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error fetching customers by type {customer_type}: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch customers: {str(e)}"
        )



async def get_all_customers_with_types(cur) -> List[Dict[str, Any]]:
    """Get all customers and categorize them by all applicable types"""
    try:
        # First get all unique customers
        cur.execute("""
            SELECT DISTINCT email, customer_name, phone, 
                   SUM(paid_amount) as total_spent, COUNT(*) as visit_count,
                   MAX(visit_date) as last_visit_date,
                   MAX(visit_date::DATE) as last_visit_date_parsed
            FROM customer 
            WHERE email IS NOT NULL AND email != ''
            GROUP BY email, customer_name, phone
        """)
        
        all_customers_data = cur.fetchall()
        customers_with_types = []
        
        # Calculate date thresholds
        thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).date()
        seven_days_ago = (datetime.utcnow() - timedelta(days=7)).date()
        
        for customer_row in all_customers_data:
            customer_email = customer_row["email"]
            customer_types = []
            
            # Check if frequent diner (more than 5 visits)
            if customer_row["visit_count"] > 5:
                customer_types.append("Frequent diners")
            
            # Check if weekend visitor
            cur.execute("""
                SELECT COUNT(*) as weekend_visits
                FROM customer 
                WHERE email = %s
                AND visit_date IS NOT NULL AND visit_date != '' 
                AND EXTRACT(DOW FROM visit_date::DATE) IN (0, 6)
            """, (customer_email,))
            weekend_result = cur.fetchone()
            if weekend_result and weekend_result["weekend_visits"] > 0:
                customer_types.append("Weekend visitor")
            
            # Check if high-valued (spent more than $500)
            if customer_row["total_spent"] and float(customer_row["total_spent"]) > 500:
                customer_types.append("High-valued")
            
            # Check if lapsed customer (haven't visited in 30+ days)
            if (customer_row["last_visit_date_parsed"] and 
                customer_row["last_visit_date_parsed"] < thirty_days_ago):
                customer_types.append("Lapsed customer")
            
            # Check if new customer (first visit in last 7 days)
            cur.execute("""
                SELECT MIN(visit_date::DATE) as first_visit
                FROM customer 
                WHERE email = %s
                AND visit_date IS NOT NULL AND visit_date != ''
            """, (customer_email,))
            first_visit_result = cur.fetchone()
            if (first_visit_result and first_visit_result["first_visit"] and 
                first_visit_result["first_visit"] >= seven_days_ago):
                customer_types.append("New customer")
            
            # Only include customers who have specific types
            if customer_types:
                # Create customer record with combined types
                customers_with_types.append({
                    "name": customer_row["customer_name"] or "",
                    "email": customer_row["email"] or "",
                    "phone": customer_row["phone"] or "",
                    "type": ", ".join(customer_types),  # Combine all types
                    "date": customer_row["last_visit_date"] or "",
                    "visit_count": customer_row["visit_count"],
                    "total_spent": float(customer_row["total_spent"]) if customer_row["total_spent"] else 0
                })
        
        return customers_with_types
        
    except Exception as e:
        logger.error(f"❌ Error getting all customers with types: {str(e)}")
        return []


async def get_customers_by_specific_type(cur, customer_type: str) -> List[Dict[str, Any]]:
    """Return customers of a specific type: Weekend visitor, Frequent diner, High-valued, or Lapsed customer."""
    try:
        customers = []
        thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).date()

        if customer_type == "Frequent diners":
            cur.execute("""
                SELECT email, customer_name, phone, 
                       SUM(paid_amount) AS total_spent, COUNT(*) AS visit_count,
                       MAX(visit_date) AS last_visit_date
                FROM customer
                WHERE email IS NOT NULL AND email != ''
                GROUP BY email, customer_name, phone
                HAVING COUNT(*) > 5
            """)
            rows = cur.fetchall()

        elif customer_type == "Weekend visitor":
            cur.execute("""
                SELECT email, customer_name, phone, 
                       SUM(paid_amount) AS total_spent, COUNT(*) AS visit_count,
                       MAX(visit_date) AS last_visit_date
                FROM customer
                WHERE email IS NOT NULL AND email != ''
                  AND visit_date IS NOT NULL
                  AND EXTRACT(DOW FROM visit_date::DATE) IN (0, 6)
                GROUP BY email, customer_name, phone
            """)
            rows = cur.fetchall()

        elif customer_type == "High-valued":
            cur.execute("""
                SELECT email, customer_name, phone, 
                       SUM(paid_amount) AS total_spent, COUNT(*) AS visit_count,
                       MAX(visit_date) AS last_visit_date
                FROM customer
                WHERE email IS NOT NULL AND email != ''
                GROUP BY email, customer_name, phone
                HAVING SUM(paid_amount) > 500
            """)
            rows = cur.fetchall()

        elif customer_type == "Lapsed customer":
            cur.execute("""
                SELECT email, customer_name, phone, 
                       SUM(paid_amount) AS total_spent, COUNT(*) AS visit_count,
                       MAX(visit_date::DATE) AS last_visit_date
                FROM customer
                WHERE email IS NOT NULL AND email != ''
                  AND visit_date IS NOT NULL
                GROUP BY email, customer_name, phone
                HAVING MAX(visit_date::DATE) < %s
            """, (thirty_days_ago,))
            rows = cur.fetchall()

        else:
            return []

        for row in rows:
            customers.append({
                "name": row["customer_name"] or "",
                "email": row["email"] or "",
                "phone": row["phone"] or "",
                "type": customer_type,
                "date": str(row.get("last_visit_date") or ""),
                "visit_count": row.get("visit_count") or 0,
                "total_spent": float(row.get("total_spent") or 0)
            })

        return customers

    except Exception as e:
        logger.error(f"❌ Error getting customers of type {customer_type}: {str(e)}")
        return []


@router.get("/scheduled-campaigns")
async def get_scheduled_campaigns(
    current_user: dict = Depends(get_current_user),
    conn=Depends(get_db)
):
    """
    📅 Get Scheduled Campaigns
    
    Retrieve all scheduled campaigns for the current user.
    Shows campaigns that are scheduled but not yet sent.
    
    Returns:
        List of scheduled campaigns with their details and status
    """
    try:
        logger.info(f"🔍 Fetching scheduled campaigns for user {current_user['email']}")
        
        # Check user permissions
        if current_user["role"] == "Non_Operators":
            raise HTTPException(
                status_code=403,
                detail="Access denied for non-operators."
            )
        
        cur = conn.cursor()
        
        # Get all scheduled campaigns for the user
        cur.execute("""
            SELECT 
                cs.id,
                cs.campaign_id,
                cs.campaign_title,
                cs.target_audience,
                cs.status,
                cs.ctr,
                cs.date_of_submission,
                cs.schedule_time,
                cs.sent_at,
                cs.total_recipients,
                cs.successful_sends,
                cs.failed_sends,
                cs.created_at
            FROM campaign_schedules cs
            WHERE cs.user_id = %s
            ORDER BY cs.schedule_time ASC
        """, (current_user["id"],))
        
        results = cur.fetchall()
        
        if not results:
            logger.info(f"⚠️ No scheduled campaigns found for user {current_user['id']}")
            return {
                "status": "success",
                "data": [],
                "count": 0,
                "message": "No scheduled campaigns found.",
                "retrieved_at": datetime.now(timezone.utc).isoformat()
            }
        
        campaigns_data = []
        for result in results:
            campaign_data = {
                "id": result["id"],
                "campaign_id": result["campaign_id"],
                "campaign_title": result["campaign_title"],
                "target_audience": result["target_audience"],
                "status": result["status"],
                "ctr": float(result["ctr"]) if result["ctr"] else 0.0,
                "date_of_submission": result["date_of_submission"].isoformat() if result["date_of_submission"] else None,
                "schedule_time": result["schedule_time"].isoformat() if result["schedule_time"] else None,
                "sent_at": result["sent_at"].isoformat() if result["sent_at"] else None,
                "total_recipients": result["total_recipients"],
                "successful_sends": result["successful_sends"],
                "failed_sends": result["failed_sends"],
                "created_at": result["created_at"].isoformat() if result["created_at"] else None
            }
            campaigns_data.append(campaign_data)
        
        logger.info(f"✅ {len(campaigns_data)} scheduled campaigns retrieved successfully for user {current_user['email']}")
        
        return {
            "status": "success",
            "data": campaigns_data,
            "count": len(campaigns_data),
            "message": f"Successfully retrieved {len(campaigns_data)} scheduled campaigns",
            "retrieved_at": datetime.now(timezone.utc).isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error retrieving scheduled campaigns for user {current_user['id']}: {e}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve scheduled campaigns: {str(e)}"
        )


@router.get("/campaigns-summary")
async def get_campaigns_summary(
    current_user: dict = Depends(get_current_user),
    conn=Depends(get_db)
):
    """
    📊 Get Campaigns Summary
    
    Retrieve campaign summary with specific fields: campaign_title, target_audience, 
    status, ctr, and date_of_submission from campaign_schedules table.
    
    Returns:
        List of campaigns with summary information
    """
    try:
        logger.info(f"🔍 Fetching campaigns summary for user {current_user['email']}")
        
        # Check user permissions
        if current_user["role"] == "Non_Operators":
            raise HTTPException(
                status_code=403,
                detail="Access denied for non-operators."
            )
        
        cur = conn.cursor()
        
        # Get campaign summary data for the user
        cur.execute("""
            SELECT 
                campaign_title,
                target_audience,
                status,
                ctr,
                campaign_id,
                date_of_submission
            FROM campaign_schedules 
            WHERE user_id = %s
            ORDER BY date_of_submission DESC
        """, (current_user["id"],))
        
        results = cur.fetchall()
        
        if not results:
            logger.info(f"⚠️ No campaigns found for user {current_user['id']}")
            return {
                "status": "success",
                "data": [],
                "count": 0,
                "message": "No campaigns found.",
                "retrieved_at": datetime.now(timezone.utc).isoformat()
            }
        
        campaigns_data = []
        for result in results:
            campaign_data = {
                "campaign_title": result["campaign_title"],
                "target_audience": result["target_audience"],
                "campaign_id": result["campaign_id"],
                "status": result["status"],
                "ctr": float(result["ctr"]) if result["ctr"] else 0.0,
                "date_of_submission": result["date_of_submission"].isoformat() if result["date_of_submission"] else None
            }
            campaigns_data.append(campaign_data)
        
        logger.info(f"✅ {len(campaigns_data)} campaigns summary retrieved successfully for user {current_user['email']}")
        
        return {
            "status": "success",
            "data": campaigns_data,
            "count": len(campaigns_data),
            "message": f"Successfully retrieved {len(campaigns_data)} campaigns summary",
            "retrieved_at": datetime.now(timezone.utc).isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error retrieving campaigns summary for user {current_user['id']}: {e}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve campaigns summary: {str(e)}"
        )


@router.delete("/delete-campaign/{campaign_id}")
async def delete_campaign_schedule(
    campaign_id: str,
    current_user: dict = Depends(get_current_user),
    conn=Depends(get_db)
):
    """
    🗑️ Delete Campaign Schedule
    
    Delete a campaign from the campaign_schedules table based on campaign_id.
    Only the campaign owner or super admin can delete campaigns.
    
    Parameters:
    - campaign_id: The ID of the campaign to delete
    
    Returns:
        Success message or error if campaign not found
    """
    try:
        logger.info(f"🗑️ Deleting campaign {campaign_id} for user {current_user['email']}")
        
        # Check user permissions
        if current_user["role"] == "Non_Operators":
            raise HTTPException(
                status_code=403,
                detail="Access denied for non-operators."
            )
        
        cur = conn.cursor()
        
        # First check if the campaign exists and belongs to the user
        cur.execute("""
            SELECT id, campaign_title, status, user_id
            FROM campaign_schedules 
            WHERE campaign_id = %s
        """, (campaign_id,))
        
        campaign = cur.fetchone()
        
        if not campaign:
            raise HTTPException(
                status_code=404,
                detail=f"Campaign with ID {campaign_id} not found in schedules"
            )
        
        # Check if current user owns this campaign or has permission
        if (current_user["role"] not in ["SUPER_ADMIN"] and 
            campaign["user_id"] != current_user["id"]):
            raise HTTPException(
                status_code=403,
                detail="Access denied. You can only delete your own campaigns."
            )
        
        # Delete the campaign from campaign_schedules
        cur.execute("""
            DELETE FROM campaign_schedules 
            WHERE campaign_id = %s AND user_id = %s
        """, (campaign_id, current_user["id"]))
        
        deleted_count = cur.rowcount
        conn.commit()
        
        if deleted_count == 0:
            raise HTTPException(
                status_code=404,
                detail=f"Campaign with ID {campaign_id} not found or already deleted"
            )
        
        logger.info(f"✅ Campaign {campaign_id} deleted successfully")
        
        return {
            "status": "success",
            "message": f"Campaign '{campaign['campaign_title']}' deleted successfully",
            "deleted_campaign": {
                "campaign_id": campaign_id,
                "campaign_title": campaign["campaign_title"],
                "status": campaign["status"]
            },
            "deleted_at": datetime.now(timezone.utc).isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting campaign {campaign_id}: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete campaign: {str(e)}"
        )


@router.post("/save-to-library")
async def save_campaign_to_library(
    request: SaveToLibraryRequest,
    current_user: dict = Depends(get_current_user),
    conn=Depends(get_db)
):
    """
    📚 Save Campaign to Library
    
    Save generated campaign content to user's personal library for future reference.
    Users can save their favorite campaigns and reuse them later.
    
    Parameters:
    - campaign_id: The ID of the campaign to save
    - generated_content: The campaign content to save to library
    
    Returns:
        Success message with library entry details
    """
    try:
        logger.info(f"📚 Saving campaign {request.campaign_id} to library for user {current_user['email']}")
        
        # Check user permissions
        if current_user["role"] == "Non_Operators":
            raise HTTPException(
                status_code=403,
                detail="Access denied for non-operators."
            )
        
        cur = conn.cursor()
        
        # Check if this campaign is already in the user's library
        cur.execute("""
            SELECT id FROM campaign_library 
            WHERE user_id = %s AND campaign_id = %s
        """, (current_user["id"], request.campaign_id))
        
        existing_entry = cur.fetchone()
        
        if existing_entry:
            raise HTTPException(
                status_code=409,
                detail=f"Campaign {request.campaign_id} is already saved in your library"
            )
        
        # Save to library
        cur.execute("""
            INSERT INTO campaign_library (
                user_id, campaign_id, generated_content, content_type, saved_at
            ) VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (
            current_user["id"],
            request.campaign_id,
            request.generated_content,
            request.content_type,
            datetime.now(timezone.utc)
        ))
        
        library_entry = cur.fetchone()
        conn.commit()
        
        logger.info(f"✅ Campaign {request.campaign_id} saved to library successfully")
        
        return {
            "status": "success",
            "message": f"Campaign saved to library successfully",
            "library_entry": {
                "library_id": library_entry["id"],
                "campaign_id": request.campaign_id,
                "content_type": request.content_type,
                "content_preview": request.generated_content[:100] + "..." if len(request.generated_content) > 100 else request.generated_content,
                "saved_at": datetime.now(timezone.utc).isoformat()
            },
            "saved_at": datetime.now(timezone.utc).isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error saving campaign {request.campaign_id} to library: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save campaign to library: {str(e)}"
        )


@router.get("/library")
async def get_campaign_library(
    content_type: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    conn=Depends(get_db)
):
    """
    📚 Get Campaign Library
    
    Retrieve all campaigns saved in the user's personal library.
    Shows saved campaigns with their content and metadata.
    
    Parameters:
    - content_type (optional): Filter campaigns by content type. 
      Valid values: "SMS/Text", "Email". If None, shows all campaigns.
    
    Returns:
        List of saved campaigns from user's library (filtered by content_type if provided)
    """
    try:
        logger.info(f"📚 Fetching campaign library for user {current_user['email']}")
        
        # Check user permissions
        if current_user["role"] == "Non_Operators":
            raise HTTPException(
                status_code=403,
                detail="Access denied for non-operators."
            )
        
        # Validate content_type if provided
        valid_content_types = ["SMS/Text", "Email"]
        if content_type is not None and content_type not in valid_content_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid content_type. Must be one of: {', '.join(valid_content_types)} or None for all campaigns"
            )
        
        cur = conn.cursor()
        
        # Build query based on content_type filter
        if content_type is not None:
            # Filter by content_type
            logger.info(f"📚 Filtering library by content_type: {content_type}")
            cur.execute("""
                SELECT 
                    id,
                    campaign_id,
                    generated_content,
                    content_type,
                    saved_at,
                    created_at
                FROM campaign_library 
                WHERE user_id = %s AND content_type ILIKE %s
                ORDER BY saved_at DESC
            """, (current_user["id"], f"%{content_type}%"))
        else:
            # Get all library entries for the user
            logger.info(f"📚 Fetching all library entries (no content_type filter)")
            cur.execute("""
                SELECT 
                    id,
                    campaign_id,
                    generated_content,
                    content_type,
                    saved_at,
                    created_at
                FROM campaign_library 
                WHERE user_id = %s
                ORDER BY saved_at DESC
            """, (current_user["id"],))
        
        results = cur.fetchall()
        
        if not results:
            filter_msg = f" with content_type '{content_type}'" if content_type else ""
            logger.info(f"⚠️ No campaigns found in library for user {current_user['id']}{filter_msg}")
            return {
                "status": "success",
                "data": [],
                "count": 0,
                "filter": {
                    "content_type": content_type,
                    "applied": content_type is not None
                },
                "message": f"No campaigns found in your library{filter_msg}.",
                "retrieved_at": datetime.now(timezone.utc).isoformat()
            }
        
        library_data = []
        for result in results:
            library_entry = {
                "library_id": result["id"],
                "campaign_id": result["campaign_id"],
                "generated_content": result["generated_content"],
                "content_type": result["content_type"],
                "content_preview": result["generated_content"][:100] + "..." if len(result["generated_content"]) > 100 else result["generated_content"],
                "saved_at": result["saved_at"].isoformat() if result["saved_at"] else None,
                "created_at": result["created_at"].isoformat() if result["created_at"] else None
            }
            library_data.append(library_entry)
        
        filter_msg = f" (filtered by '{content_type}')" if content_type else ""
        logger.info(f"✅ {len(library_data)} library entries retrieved successfully for user {current_user['email']}{filter_msg}")
        
        return {
            "status": "success",
            "data": library_data,
            "count": len(library_data),
            "filter": {
                "content_type": content_type,
                "applied": content_type is not None,
                "valid_options": valid_content_types
            },
            "message": f"Successfully retrieved {len(library_data)} campaigns from library{filter_msg}",
            "retrieved_at": datetime.now(timezone.utc).isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error retrieving campaign library for user {current_user['id']}: {e}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve campaign library: {str(e)}"
        )


@router.get("/latest-campaign-library")
async def get_latest_campaign_from_library(
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    📚 Get Latest Campaign from Library
    
    Returns the most recent campaign content generated by the current user
    from the campaign_library table.
    """
    try:
        logger.info(f"📚 Fetching latest campaign from library for user {current_user['email']}")
        
        # Check user permissions
        if current_user["role"] == "Non_Operators":
            raise HTTPException(
                status_code=403,
                detail="Access denied for non-operators."
            )
        
        cur = conn.cursor()
        
        # Get the latest campaign from campaign_library for this user
        cur.execute("""
            SELECT 
                id,
                campaign_id,
                generated_content,
                content_type,
                saved_at,
                created_at
            FROM campaign_library 
            WHERE user_id = %s 
            ORDER BY saved_at DESC 
            LIMIT 1
        """, (current_user["id"],))
        
        latest_campaign = cur.fetchone()
        
        if not latest_campaign:
            return {
                "status": "success",
                "message": "No campaigns found in library",
                "data": None
            }
        
        # Convert the result to a dictionary
        campaign_data = {
            "id": latest_campaign["id"],
            "campaign_id": latest_campaign["campaign_id"],
            "generated_content": latest_campaign["generated_content"],
            "content_type": latest_campaign["content_type"],
            "saved_at": latest_campaign["saved_at"].isoformat() if latest_campaign["saved_at"] else None,
            "created_at": latest_campaign["created_at"].isoformat() if latest_campaign["created_at"] else None
        }
        
        logger.info(f"✅ Latest campaign retrieved successfully for user {current_user['email']}")
        
        return {
            "status": "success",
            "message": "Latest campaign retrieved successfully",
            "data": campaign_data,
            "user_id": current_user["id"],
            "user_email": current_user["email"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error fetching latest campaign from library: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch latest campaign: {str(e)}"
        )


@router.post("/add-customer", response_model=AddCustomerResponse)
async def add_customer_with_type(
    request: AddCustomerRequest,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    👥 Add Customer with Type-Based Data
    
    Takes customer information and type, then calculates and saves appropriate data
    to the customer table based on the customer type characteristics.
    """
    try:
        logger.info(f"👥 Adding customer {request.customer_name} with type {request.customer_type}")
        
        # Check user permissions
        if current_user["role"] == "Non_Operators":
            raise HTTPException(
                status_code=403,
                detail="Access denied for non-operators."
            )
        
        # Validate customer type
        valid_types = ["frequent_diners", "new", "weekend_visitor", "high_valued", "lapsed_customer"]
        if request.customer_type.lower() not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid customer type. Must be one of: {', '.join(valid_types)}"
            )
        
        # Generate unique customer ID
        import uuid
        customer_id = str(uuid.uuid4())[:12]
        
        cur = conn.cursor()
        records_created = 0
        customer_data = {
            "customer_id": customer_id,
            "customer_name": request.customer_name,
            "email": request.email,
            "phone": request.phone,
            "customer_type": request.customer_type,
            "visit_details": []
        }
        
        # Calculate data based on customer type
        if request.customer_type.lower() == "frequent_diners":
            # Create 6-10 visits over the past few months
            import random
            
            num_visits = random.randint(6, 10)
            total_spent = 0
            
            for i in range(num_visits):
                # Random visit date in past 3 months
                days_ago = random.randint(1, 90)
                visit_date = (datetime.now() - timedelta(days=days_ago)).date()
                
                # Random amount between $25-100 per visit
                paid_amount = round(random.uniform(25.0, 100.0), 2)
                total_spent += paid_amount
                
                cur.execute("""
                    INSERT INTO customer (customer_id, customer_name, email, phone, paid_amount, visit_date)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (customer_id, request.customer_name, request.email, request.phone, paid_amount, visit_date))
                
                customer_data["visit_details"].append({
                    "visit_date": str(visit_date),
                    "paid_amount": paid_amount
                })
                records_created += 1
            
            customer_data["total_visits"] = num_visits
            customer_data["total_spent"] = round(total_spent, 2)
            
        elif request.customer_type.lower() == "high_valued":
            # Create 2-4 visits with high spending (total > $500)
            import random
            
            num_visits = random.randint(2, 4)
            total_spent = 0
            target_total = random.uniform(550.0, 1000.0)  # Ensure > $500
            
            for i in range(num_visits):
                # Random visit date in past 6 months
                days_ago = random.randint(1, 180)
                visit_date = (datetime.now() - timedelta(days=days_ago)).date()
                
                # Distribute the target total across visits
                if i == num_visits - 1:  # Last visit
                    paid_amount = round(target_total - total_spent, 2)
                else:
                    paid_amount = round(target_total / num_visits + random.uniform(-50, 50), 2)
                    paid_amount = max(paid_amount, 50.0)  # Minimum $50 per visit
                
                total_spent += paid_amount
                
                cur.execute("""
                    INSERT INTO customer (customer_id, customer_name, email, phone, paid_amount, visit_date)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (customer_id, request.customer_name, request.email, request.phone, paid_amount, visit_date))
                
                customer_data["visit_details"].append({
                    "visit_date": str(visit_date),
                    "paid_amount": paid_amount
                })
                records_created += 1
            
            customer_data["total_visits"] = num_visits
            customer_data["total_spent"] = round(total_spent, 2)
            
        elif request.customer_type.lower() == "weekend_visitor":
            # Create 2-4 visits, all on weekends
            import random
            
            num_visits = random.randint(2, 4)
            total_spent = 0
            
            for i in range(num_visits):
                # Find weekend dates in the past 2 months
                days_ago = random.randint(1, 60)
                base_date = datetime.now() - timedelta(days=days_ago)
                
                # Adjust to weekend (Saturday=5, Sunday=6)
                weekday = base_date.weekday()
                if weekday < 5:  # Monday-Friday
                    # Move to next Saturday
                    days_to_saturday = 5 - weekday
                    visit_date = (base_date + timedelta(days=days_to_saturday)).date()
                else:  # Already weekend
                    visit_date = base_date.date()
                
                # Random amount between $30-80 per visit
                paid_amount = round(random.uniform(30.0, 80.0), 2)
                total_spent += paid_amount
                
                cur.execute("""
                    INSERT INTO customer (customer_id, customer_name, email, phone, paid_amount, visit_date)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (customer_id, request.customer_name, request.email, request.phone, paid_amount, visit_date))
                
                customer_data["visit_details"].append({
                    "visit_date": str(visit_date),
                    "paid_amount": paid_amount,
                    "weekday": visit_date.strftime("%A")
                })
                records_created += 1
            
            customer_data["total_visits"] = num_visits
            customer_data["total_spent"] = round(total_spent, 2)
            
        elif request.customer_type.lower() == "lapsed_customer":
            # Create 2-3 visits, all more than 30 days ago
            import random
            
            num_visits = random.randint(2, 3)
            total_spent = 0
            
            for i in range(num_visits):
                # Random visit date between 31-120 days ago
                days_ago = random.randint(31, 120)
                visit_date = (datetime.now() - timedelta(days=days_ago)).date()
                
                # Random amount between $20-70 per visit
                paid_amount = round(random.uniform(20.0, 70.0), 2)
                total_spent += paid_amount
                
                cur.execute("""
                    INSERT INTO customer (customer_id, customer_name, email, phone, paid_amount, visit_date)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (customer_id, request.customer_name, request.email, request.phone, paid_amount, visit_date))
                
                customer_data["visit_details"].append({
                    "visit_date": str(visit_date),
                    "paid_amount": paid_amount,
                    "days_ago": days_ago
                })
                records_created += 1
            
            customer_data["total_visits"] = num_visits
            customer_data["total_spent"] = round(total_spent, 2)
            
        elif request.customer_type.lower() == "new":
            # Create 1-2 visits within the last 7 days
            import random
            
            num_visits = random.randint(1, 2)
            total_spent = 0
            
            for i in range(num_visits):
                # Random visit date within last 7 days
                days_ago = random.randint(0, 6)
                visit_date = (datetime.now() - timedelta(days=days_ago)).date()
                
                # Random amount between $15-60 per visit (new customers spend less initially)
                paid_amount = round(random.uniform(15.0, 60.0), 2)
                total_spent += paid_amount
                
                cur.execute("""
                    INSERT INTO customer (customer_id, customer_name, email, phone, paid_amount, visit_date)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (customer_id, request.customer_name, request.email, request.phone, paid_amount, visit_date))
                
                customer_data["visit_details"].append({
                    "visit_date": str(visit_date),
                    "paid_amount": paid_amount,
                    "days_ago": days_ago
                })
                records_created += 1
            
            customer_data["total_visits"] = num_visits
            customer_data["total_spent"] = round(total_spent, 2)
        
        conn.commit()
        
        logger.info(f"✅ Customer {request.customer_name} added with {records_created} records as {request.customer_type}")
        
        return AddCustomerResponse(
            status="success",
            message=f"Customer {request.customer_name} added successfully as {request.customer_type}",
            customer_data=customer_data,
            records_created=records_created,
            customer_type=request.customer_type
        )
        
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"❌ Error adding customer: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to add customer: {str(e)}"
        )

