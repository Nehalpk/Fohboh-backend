import boto3
import os
from datetime import datetime
import psycopg2.extras
from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile, WebSocket, WebSocketDisconnect, Form, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from contextlib import asynccontextmanager
from typing import List, Dict, Optional
import logging
import jwt
import psycopg2
from src.chat_gpt import JWT_SECRET, JWT_ALGORITHM 
import requests
import json
from src.systam import router as notes_router, init_notes_table
from src.settings_and_integrations import router as settings_router, init_settings_tables
from src.fraud_detection_operational_efficiency import router as fraud_router
from src.subscription_management import router as subscription_router, init_subscription_tables
from passlib.context import CryptContext
import traceback
import uuid
security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Import models and dependencies
VALID_CATEGORIES = ["Inventory", "Labor", "Sales", "Menu"]

import asyncio
from src.config import notification_manager


from src.subscription_management import update_usage
from src.chat_gpt import (
    RoleType,
    RegionalManagerCreate,
    RestaurantManagerCreate,
    RestaurantBase,
    RestaurantUpdate,
    UnitIdUpdate,
    OTPRequest,
    PasswordReset,
    PasswordUpdate,
    ProfileUpdate,
    HoursOfOperationUpdate,
    PasswordResetWithToken,
    get_current_user,
    get_db,
    init_db,
    create_initial_super_admins,
    update_restaurant_with_image,
    update_restaurant_unit_id,
    get_unassigned_restaurants,
    clear_user_audios
)

# Import user management functions
from src.users_management import (
    ManagerInvitation,
    ManagerRegistration,
    UserCreate,
    UserProfileUpdate,
    RestaurantOwnerCreate,
    invite_manager,
    register_manager_by_invitation,
    register_user,
    register_restaurant_owner,
    verify_user_email,
    login_user,
    delete_current_user
)

# Import main.py components
from src.main import (

    processor,
    manager
)

from src.main import  ChatHistory as ch_c

from src.main_c import ChatHistory as ch_o



from src.main_c import (
    ChatRequest2,
    processor2,
    manager2,
    FileProcessor2
)

from src.File_upload import(
    list_csv_files,
    download_csv_file,
    delete_csv_file,
    upload_file,
    upload_file_id,
    list_s3_files_id,
    verify_restaurant_access,
    verify_restaurant_access_id,
    list_cat_csv_files,
    delete_all_user_files,
)

from src.dashboard_graphs import get_sales_summary_by_restaurant
from src.dashboard import list_csv_files_only, S3CSVProcessor



 
from src.rag import router as rag_router, init_rag_module,save_chat_history_db
from src.stripe_integration import init_payment_tables
from src.hours_of_operation import (
    router as hours_router,
    init_hours_of_operation_table,
    HoursOfOperationUpdate,
    MealPeriodCreate,
    MealPeriodDelete
)

init_rag_module()
init_notes_table()
init_settings_tables()
init_hours_of_operation_table()
init_subscription_tables()
init_payment_tables()


from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from fastapi import Depends, HTTPException

# Enhanced models to support embeddings
class EmbeddingFilesRequest(BaseModel):
    category: str
    filenames: List[str]

class EnhancedChatRequest(BaseModel):
    question: str
    file_type: Optional[str] = "all"
    file_index: Optional[int] = -1
    include_history: bool = True
    
    # New optional embedding fields
    use_embeddings: Optional[bool] = False
    embedding_model: Optional[str] = "claude"  # or "openai"
    restaurant_name: Optional[str] = None
    embedding_files: Optional[List[EmbeddingFilesRequest]] = None

class MultiRestaurantChatRequest(BaseModel):
    question: str
    include_history: bool = True
    embedding_model: Optional[str] = "claude"  # or "openai"
    restaurant_names: List[str]  # List of restaurant names to query
    conversation_id: Optional[str] = None

class EnhancedChatResponse(BaseModel):
    response: str
    has_history: bool
    embedding_info: Optional[Dict[str, Any]] = None
    history_saved: bool = False
    chat_history: Optional[List[Dict[str, Any]]] = None
    conversation_id : str
    
# Make sure to create tables on application startup
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
        await create_initial_super_admins()
        
        asyncio.create_task(notification_manager.redis_subscriber())
        
        # Start subscription scheduler
        from src.subscription_scheduler import start_subscription_scheduler
        # start_subscription_scheduler()
        
        # Initialize token system tables
        from src.token_system_integration import init_token_system_tables
        init_token_system_tables()
        
        logger.info("Application started and initialized successfully")
    except Exception as e:
        logger.error(f"Startup error: {e}")
        raise
    yield
    # Stop subscription scheduler
    from src.subscription_scheduler import subscription_scheduler
    subscription_scheduler.stop()
    logger.info("Application shutting down")

app = FastAPI(title="Restaurant Management System", lifespan=lifespan)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BUCKET_NAME = "my-audio-demo"
UPLOAD_BASE_DIR = "uploads/users"

# Initialize S3 client globally
s3_client = boto3.client(
    's3',
    region_name='us-east-1',
    aws_access_key_id='AKIA6G75DKGI46PCJQHL',
    aws_secret_access_key='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'
)


# Add subscription middleware
from src.subscription_middleware import verify_subscription
# app.middleware("http")(verify_subscription)

# Add token usage middleware
from src.token_system_middleware import token_usage_middleware
# app.middleware("http")(token_usage_middleware)

# Import token system router
from src.token_system_integration import router as token_system_router

from src.stripe_integration import router as stripe_router

from src.promotion_markiting import router as promotion_router
# @app.lifespan("startup")
# async def startup_event():
#     # Run Redis subscriber as background task
#     asyncio.create_task(notification_manager.redis_subscriber())
#     # Other startup code if any
    

# Add a test endpoint for predefined answers
@app.post("/test-predefined-answers")
async def test_predefined_answers(question: str):
    """Test endpoint for predefined answers without authentication"""
    try:
        # Test with the question directly
        response = await processor.generate_response_with_embeddings(
            question=question,
            user_email="test@example.com",  # Use a fake email
            embedding_info=None,
            file_type="all",
            file_index=-1,
            include_history=True  # Maintain in-memory history
        )
        
        # Get current history after adding this conversation
        current_history = [
            conv for conv in processor.history.conversations 
            if conv.get('user_email') == "test@example.com"
        ]
        
        return {
            "response": response,
            "has_history": len(current_history) > 0,
            "embedding_info": None,
            "history_saved": False,
            "chat_history": current_history
        }
    except Exception as e:
        logger.error(f"Error in test predefined answers: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error generating response: {str(e)}"
        )

# Add a test endpoint for OpenAI predefined answers
@app.post("/test-predefined-answers-openai")
async def test_predefined_answers_openai(question: str):
    """Test endpoint for OpenAI predefined answers without authentication"""
    try:
        # Test with the question directly
        response = await processor2.generate_response_with_embeddings(
            question=question,
            user_email="test@example.com",  # Use a fake email
            embedding_info=None,
            file_type="all",
            file_index=-1,
            include_history=True  # Maintain in-memory history
        )
        
        # Get current history after adding this conversation
        current_history = [
            conv for conv in processor2.history.conversations 
            if conv.get('user_email') == "test@example.com"
        ]
        
        return {
            "response": response,
            "has_history": len(current_history) > 0,
            "embedding_info": None,
            "history_saved": False,
            "chat_history": current_history
        }
    except Exception as e:
        logger.error(f"Error in test OpenAI predefined answers: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error generating response: {str(e)}"
        )

# Add an endpoint to view test chat history without authentication
@app.get("/test-chat-history")
async def get_test_chat_history():
    """Get chat history for the test user without authentication"""
    try:
        # Get test user history from both processors
        claude_history = [
            conv for conv in processor.history.conversations 
            if conv.get('user_email') == "test@example.com"
        ]
        
        openai_history = [
            conv for conv in processor2.history.conversations 
            if conv.get('user_email') == "test@example.com"
        ]
        
        return {
            "claude_history": claude_history,
            "openai_history": openai_history
        }
    except Exception as e:
        logger.error(f"Error retrieving test chat history: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Error retrieving test chat history"
        )


app.include_router(promotion_router)
app.include_router(rag_router)
app.include_router(notes_router)
app.include_router(settings_router)
app.include_router(hours_router)
app.include_router(fraud_router)
app.include_router(subscription_router)
# app.include_router(token_system_router)
app.include_router(stripe_router)

# Auth Routes
# using json body to login
class LoginRequest(BaseModel):
    #email: Optional[str] = None
    #password: Optional[str] = None
    encrypted_data: Optional[str] = None


from src.encryption_utils import decrypt_data, encrypt_data

@app.post("/login")
async def login(request: LoginRequest, conn = Depends(get_db)):
    """
    Login endpoint for all users - supports both regular and encrypted requests
    
    Regular Request Body (JSON):
    {
        "email": "user@example.com",
        "password": "userpassword"
    }
    
    Encrypted Request Body (JSON):
    {
        "encrypted_data": "base64_encoded_encrypted_json"
    }
    """
    try:
        # Check if this is an encrypted request
        if request.encrypted_data:
            # Decrypt the payload
            decrypted_json = decrypt_data(request.encrypted_data)
            login_data = json.loads(decrypted_json)
            
            # Extract email and password from decrypted data
            email = login_data.get("email")
            password = login_data.get("password")
            
            if not email or not password:
                raise HTTPException(
                    status_code=400,
                    detail="Email and password are required in encrypted data"
                )
        else:
            # Regular request - use provided email and password
            if not request.email or not request.password:
                raise HTTPException(
                    status_code=400,
                    detail="Email and password are required"
                )
            email = request.email
            password = request.password
        
        # Use existing login logic
        from src.chat_gpt import login as auth_login
        return await auth_login(email, password, conn)
        
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON in encrypted data"
        )
    except HTTPException:
        # Re-raise HTTP exceptions (like invalid credentials)
        raise
    except Exception as e:
        logger.error(f"Error in login endpoint: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Login processing failed"
        )

@app.post("/managers/login") 
async def manager_login(request: LoginRequest, conn = Depends(get_db)):
    """
    Login endpoint for managers - supports both regular and encrypted requests
    
    Regular Request Body (JSON):
    {
        "email": "manager@example.com", 
        "password": "managerpassword"
    }
    
    Encrypted Request Body (JSON):
    {
        "encrypted_data": "base64_encoded_encrypted_json"
    }
    """
    try:
        # Check if this is an encrypted request
        if request.encrypted_data:
            # Decrypt the payload
            decrypted_json = decrypt_data(request.encrypted_data)
            login_data = json.loads(decrypted_json)
            
            # Extract email and password from decrypted data
            email = login_data.get("email")
            password = login_data.get("password")
            
            if not email or not password:
                raise HTTPException(
                    status_code=400,
                    detail="Email and password are required in encrypted data"
                )
        else:
            # Regular request - use provided email and password
            if not request.email or not request.password:
                raise HTTPException(
                    status_code=400,
                    detail="Email and password are required"
                )
            email = request.email
            password = request.password
        
        # Use existing manager login logic
        from src.chat_gpt import manager_login as auth_manager_login
        return await auth_manager_login(email, password, conn)
        
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON in encrypted data"
        )
    except HTTPException:
        # Re-raise HTTP exceptions (like invalid credentials)
        raise
    except Exception as e:
        logger.error(f"Error in manager login endpoint: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Manager login processing failed"
        )



@app.post("/non-operators/login")
async def login_user_endpoint(
    request: LoginRequest,
    conn = Depends(get_db)
):
    """
    Login endpoint for regular users - supports both regular and encrypted requests
    """
    try:
        # Check if this is an encrypted request
        if request.encrypted_data:
            # Decrypt the payload
            decrypted_json = decrypt_data(request.encrypted_data)
            login_data = json.loads(decrypted_json)
            
            # Extract email and password from decrypted data
            email = login_data.get("email")
            password = login_data.get("password")
            
            if not email or not password:
                raise HTTPException(
                    status_code=400,
                    detail="Email and password are required in encrypted data"
                )
        else:
            # Regular request - use provided email and password
            if not request.email or not request.password:
                raise HTTPException(
                    status_code=400,
                    detail="Email and password are required"
                )
            email = request.email
            password = request.password
        
        # Use existing non-operator login logic
        from src.users_management import login_user
        return await login_user(email, password, conn)
        
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON in encrypted data"
        )
    except HTTPException:
        # Re-raise HTTP exceptions (like invalid credentials)
        raise
    except Exception as e:
        logger.error(f"Error in non-operator login endpoint: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Non-operator login processing failed"
        )
# using query to login
#@app.post("/login")
#async def login(email: str, password: str, conn = Depends(get_db)):
#    """Login endpoint for all users"""
#    from src.chat_gpt import login as auth_login
#    return await auth_login(email, password, conn)
#
#@app.post("/managers/login")
#async def manager_login(email: str, password: str, conn = Depends(get_db)):
#    """Specific login endpoint for managers"""
#    
#    from src.chat_gpt import manager_login as auth_manager_login
#    return await auth_manager_login(email, password, conn)

#
@app.post("/invite/manager")
async def invite_manager_endpoint(
    invitation: ManagerInvitation,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Send invitation to a manager (Regional or Restaurant)
    
    Returns the invitation details including a direct invitation link that can be used for testing.
    The invitation link is also sent via email to the manager.
    """
    return await invite_manager(invitation, current_user, conn)

@app.post("/register/manager-by-invitation")
async def register_manager_by_invitation_endpoint(
    registration: ManagerRegistration,
    conn = Depends(get_db)
):
    """Register a manager (Regional or Restaurant) using an invitation token"""
    return await register_manager_by_invitation(registration, conn)


@app.post("/restaurant-owners/register")
async def register_restaurant_owner_endpoint(
    owner: RestaurantOwnerCreate,
    conn = Depends(get_db)
):
    """Register a new restaurant owner"""
    return await register_restaurant_owner(owner, conn)

# Email Verification Routes
@app.post("/managers/verify")
async def verify_email(email: str, otp: str, conn = Depends(get_db)):
    """Verify manager's email with OTP"""
    from src.chat_gpt import verify_manager_email
    return await verify_manager_email(email, otp, conn)

@app.post("/managers/resend-verification")
async def resend_verification(request: OTPRequest, conn = Depends(get_db)):
    """Resend verification OTP"""
    from src.chat_gpt import resend_verification_otp
    return await resend_verification_otp(request, conn)

@app.post("/managers/forgot-password")
async def forgot_password(request: OTPRequest, conn = Depends(get_db)):
    """Handle forgotten password"""
    from src.chat_gpt import forgot_password as forgot_pwd
    return await forgot_pwd(request, conn)

@app.post("/managers/reset-password")
async def reset_password(reset_data: PasswordReset, conn = Depends(get_db)):
    """Reset password with OTP"""
    from src.chat_gpt import reset_password as reset_pwd
    return await reset_pwd(reset_data, conn)

@app.post("/managers/reset-password-with-token")
async def reset_password_with_token_endpoint(
    reset_data: PasswordResetWithToken,
    conn = Depends(get_db)
):
    from src.chat_gpt import reset_password_with_token
    """Reset password using JWT token received after email verification"""
    return await reset_password_with_token(reset_data, conn)

    

@app.post("/managers/verify-manager-email")
async def verify_manager_email_endpoint(
    email: str,
    otp: str,
    conn = Depends(get_db)
):
    """Verify manager email with OTP and return JWT token"""
    from src.chat_gpt import verify_manager_email_otp
    return await verify_manager_email_otp(email, otp, conn)

@app.post("/non-operators/register")
async def register_user_endpoint(
    user: UserCreate,
    conn = Depends(get_db)
):
    """Register a new regular user (non-operator)"""
    return await register_user(user, conn)


@app.post("/non-operators/verify-email")
async def verify_user_email_endpoint(
    email: str,
    otp: str,
    conn = Depends(get_db)
):
    """Verify a user's email with OTP"""
    return await verify_user_email(email, otp, conn)

#@app.post("/non-operators/login")
#async def login_user_endpoint(
#    email: str,
#    password: str,
#    conn = Depends(get_db)
#):
#    """Login endpoint for regular users"""
#    return await login_user(email, password, conn)

@app.post("/non-operators/resend-verification")
async def resend_verification_non_operator_endpoint(
    request: OTPRequest,
    conn = Depends(get_db)
):
    """Resend verification OTP for non-operator users"""
    from src.users_management import resend_verification_otp_non_operator
    return await resend_verification_otp_non_operator(request, conn)


@app.post("/non-operators/forgot-password")
async def forgot_password_non_operator_endpoint(
    request: OTPRequest,
    conn = Depends(get_db)
):
    """Handle forgotten password for non-operator users"""
    from src.users_management import forgot_password_non_operator
    return await forgot_password_non_operator(request, conn)

@app.post("/non-operators/reset-password")
async def reset_password_non_operator_endpoint(
    email: str,
    otp: str,
    new_password: str,
    conn = Depends(get_db)
):
    """Reset password with OTP for non-operator users"""
    from src.users_management import reset_password_non_operator
    return await reset_password_non_operator(email, otp, new_password, conn)


@app.post("/users/update-password")
async def update_password(
    password_data: PasswordUpdate, 
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Update user's password after verifying the old password"""
    from src.chat_gpt import update_password as update_pwd
    return await update_pwd(password_data, current_user, conn)

# Restaurant Management Routes

# Manager Management Routes
@app.delete("/managers/{manager_id}")
async def delete_manager(
    manager_id: int,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Delete a manager"""
    from src.chat_gpt import delete_manager as delete_mgr
    return await delete_mgr(manager_id, current_user, conn)



@app.get("/managers")
async def get_managers(
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Get all managers"""
    from src.chat_gpt import get_managers as get_mgrs
    return await get_mgrs(current_user, conn)

@app.put("/managers/{manager_id}", response_model=dict)
async def edit_manager(
    manager_id: int,
    full_name: str= None,
    phone_number: str = None,
    profile_image: Optional[UploadFile] = None,
    image_url: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    from src.chat_gpt import update_manager
    """
    Update manager information including optional profile image upload
    """
    return await update_manager(
        manager_id=manager_id,
        full_name=full_name,
        phone_number=phone_number,
        profile_image=profile_image,
        image_url=image_url,
        current_user=current_user,
        conn=conn
    )
    
@app.get("/regional-managers")
async def get_regional_managers(
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Get all regional managers"""
    from src.chat_gpt import get_regional_managers as get_regional
    return await get_regional(current_user, conn)

# Profile Management Routes
@app.get("/profile/me")
async def get_profile(
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Get current user's profile"""
    from src.chat_gpt import get_current_profile
    return await get_current_profile(current_user, conn)

@app.put("/profile/me")
async def update_profile(
    profile: ProfileUpdate,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Update current user's profile"""
    from src.chat_gpt import update_current_profile
    return await update_current_profile(profile, current_user, conn)

@app.post("/profile/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Upload profile image"""
    from src.chat_gpt import upload_profile_image
    return await upload_profile_image(file, current_user, conn)

@app.delete("/profile/me")
async def delete_my_account(
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Permanently delete current user's account and all related data"""
    return await delete_current_user(current_user, conn)


from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Mount static files directory
app.mount("/profile_images", StaticFiles(directory="uploads/profile_images"), name="profile_images")

@app.get("/profile/current-image")
async def get_current_user_image(
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Get current user's profile image"""
    try:
        # Get image info from database
        from src.chat_gpt import get_current_user_profile_image
        image_info = await get_current_user_profile_image(current_user, conn)
        
        # Return the actual file
        return FileResponse(
            image_info["image_path"],
            headers={
                "Content-Disposition": f'inline; filename="{image_info["filename"]}"'
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
#-------------------Just for Now--------------------#    
#@app.post("/restaurants/create")
#async def create_restaurant(
#    restaurant: RestaurantBase,
#    current_user: dict = Depends(get_current_user),
#    conn = Depends(get_db)
#):
#    
#    
#
#    """Create a new restaurant"""
#    from src.chat_gpt import create_restaurant as create_rest
#    return await create_rest(restaurant, current_user, conn)

# Alternative version using the helper function
# Import the helper function: from src.chat_gpt import upload_restaurant_image_to_s3


# S3 Configuration (should be in your config)
async def upload_restaurant_image_to_s3(
    image: UploadFile,
    restaurant_name: str,
    user_id: int,
    old_image_url: Optional[str] = None
) -> str:
    """
    Upload restaurant image to S3 and return the URL.
    If old_image_url is provided, it will attempt to delete the old image.
    
    Args:
        image: The uploaded file
        restaurant_name: Name of the restaurant (used for folder structure)
        user_id: ID of the user uploading the image
        old_image_url: Optional URL of the old image to delete
    
    Returns:
        str: The S3 URL of the uploaded image
    
    Raises:
        HTTPException: If image upload fails
    """
    try:
        # Validate file type
        if not image.content_type.startswith('image/'):
            raise HTTPException(
                status_code=400,
                detail="File must be an image"
            )
        
        # Delete old image if exists
        if old_image_url and BUCKET_NAME in old_image_url:
            try:
                old_key = old_image_url.split(f"{BUCKET_NAME}.s3.amazonaws.com/")[1]
                s3_client.delete_object(Bucket=BUCKET_NAME, Key=old_key)
                logger.info(f"Deleted old image: {old_key}")
            except Exception as e:
                logger.error(f"Error deleting old image: {str(e)}")
                # Continue even if deletion fails
        
        # Create S3 path
        user_folder = f"user_{user_id}"
        restaurant_folder = restaurant_name.lower().replace(' ', '_')
        s3_folder = f"uploads/users/{user_folder}/restaurants/{restaurant_folder}"
        
        # Generate unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_extension = os.path.splitext(image.filename)[1].lower()
        if not file_extension:
            file_extension = '.jpg'  # Default extension if not provided
        new_filename = f"restaurant_{timestamp}{file_extension}"
        s3_key = f"{s3_folder}/{new_filename}"
        
        # Read and upload to S3
        content = await image.read()
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=s3_key,
            Body=content,
            ContentType=image.content_type
        )
        
        # Generate public URL
        image_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}"
        logger.info(f"Image uploaded successfully to S3: {image_url}")
        
        return image_url
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading image to S3: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload image: {str(e)}"
        )

@app.post("/restaurants/create")
async def create_restaurant(
    name: str = Form(...),
    location: str = Form(...),
    city: str = Form(...),
    state: str = Form(...),
    zip_code: str = Form(...),
    country: str = Form(...),
    contact_number: str = Form(...),
    image: Optional[UploadFile] = File(None),
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Create a new restaurant with optional image upload
    """
    # Check permissions
    if current_user["role"] not in ["SUPER_ADMIN", "Restaurant Owner"]:
        raise HTTPException(
            status_code=403, 
            detail="Only SUPER_ADMIN and Restaurant Owner can create restaurants"
        )
    
    try:
        cur = conn.cursor()
        
        # STEP 1: Check if restaurant with this name already exists
        cur.execute("""
            SELECT id FROM restaurants 
            WHERE TRIM(LOWER(name)) = TRIM(LOWER(%s))
        """, (name,))
        
        if cur.fetchone():
            raise HTTPException(
                status_code=400,
                detail="Restaurant with this name already exists"
            )
        
        # STEP 2: Generate unique unit_id
        # If you have a generate_unique_unit_id function, use it
        # Otherwise, generate a simple unique ID
        import uuid
        unit_id = str(uuid.uuid4())[:8].upper()  # Or use your generate_unique_unit_id(conn) function
        
        # STEP 3: Handle image upload if provided
        image_url = None
        if image:
            try:
                # Validate file type
                if not image.content_type.startswith('image/'):
                    raise HTTPException(
                        status_code=400,
                        detail="File must be an image"
                    )
                
                # Create S3 path
                safe_restaurant_name = name.lower().replace(' ', '_')
                user_folder = f"user_{current_user['id']}"
                s3_folder = f"uploads/users/{user_folder}/restaurants/{safe_restaurant_name}"
                
                # Generate unique filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                file_extension = os.path.splitext(image.filename)[1].lower()
                new_filename = f"restaurant_{timestamp}{file_extension}"
                s3_key = f"{s3_folder}/{new_filename}"
                
                # Read and upload to S3
                content = await image.read()
                s3_client.put_object(
                    Bucket=BUCKET_NAME,
                    Key=s3_key,
                    Body=content,
                    ContentType=image.content_type
                )
                
                image_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}"
                logger.info(f"Image uploaded successfully to S3: {image_url}")
                
            except Exception as e:
                logger.error(f"Error uploading image: {str(e)}")
                # Don't fail restaurant creation if image upload fails
                image_url = None
        
        # STEP 4: Insert restaurant WITHOUT ON CONFLICT clause
        cur.execute("""
            INSERT INTO restaurants (
                name, 
                location,
                city,
                state,
                zip_code,
                country,
                contact_number,
                created_by,
                unit_id,
                image_url,
                active
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true)
            RETURNING 
                id,
                name,
                location,
                city,
                state,
                zip_code,
                country,
                contact_number,
                created_at,
                created_by,
                active,
                unit_id,
                image_url
        """, (
            name.strip(),
            location,
            city,
            state,
            zip_code,
            country,
            contact_number,
            current_user["id"],
            unit_id,
            image_url
        ))
        
        new_restaurant = cur.fetchone()
        
        # STEP 5: Get creator's email for response
        cur.execute("""
            SELECT email, full_name 
            FROM managers 
            WHERE id = %s
        """, (current_user["id"],))
        
        creator = cur.fetchone()
        
        # STEP 6: Prepare response
        result = dict(new_restaurant)
        result["created_by_email"] = creator["email"] if creator else None
        result["created_by_name"] = creator["full_name"] if creator else None
        
        # STEP 7: Commit the transaction
        conn.commit()
        logger.info(f"Restaurant '{name}' created successfully by user: {current_user['email']}")
        
        # STEP 8: Update usage tracking (optional, with error handling)
        try:
            from src.subscription_management import update_usage
            await update_usage(
                current_user=current_user,
                conn=conn,
                used_restaurants=True
            )
        except Exception as usage_error:
            logger.warning(f"Failed to update usage tracking: {str(usage_error)}")
            # Don't fail the restaurant creation if usage tracking fails
        
        # STEP 9: Create notification for restaurant creation
        try:
            from src.chat_gpt import create_notification
            await create_notification(
                user_id=current_user["id"],
                title="Restaurant Created",
                message=f"Restaurant '{name}' has been created successfully.",
                type="success",
                restaurant_id=new_restaurant["id"],
                conn=conn
            )
        except Exception as notif_error:
            logger.warning(f"Failed to create notification: {str(notif_error)}")
        
        return {
            "message": "Restaurant created successfully",
            "restaurant": result
        }
        
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating restaurant: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, 
            detail=f"Error creating restaurant: {str(e)}"
        )


@app.put("/restaurants/{restaurant_id}/unit-id")
async def update_restaurant_unit_id_endpoint(
    restaurant_id: int,
    unit_id_data: UnitIdUpdate,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Update unit_id for a specific restaurant"""
    return await update_restaurant_unit_id(restaurant_id, unit_id_data, current_user, conn)





class RestaurantOwner(BaseModel):
    id: int
    full_name: str
    email: str
    role: str


@app.get("/restaurant-owners", response_model=List[dict])
async def get_restaurant_owners(
        current_user: dict = Depends(get_current_user),
        conn=Depends(get_db)
):
    if current_user.get("role") != "SUPER_ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Only admin can access this resource."
        )

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT m.id, m.full_name, m.email, m.role, r.name AS restaurant_name
            FROM managers m
            JOIN restaurants r ON r.created_by = m.id
            WHERE m.role = 'Restaurant Owner'
        """)
        rows = cur.fetchall()

    owners = [
        {
            "id": row["id"],
            "full_name": row["full_name"],
            "email": row["email"],
            "role": row["role"],
            "restaurant_name": row["restaurant_name"]
        }
        for row in rows
    ]
    return owners


from pydantic import BaseModel, EmailStr
class EditOwnerRequest(BaseModel):
    full_name: Optional[str]
    email: Optional[EmailStr]
    restaurant_name: Optional[str]


@app.put("/restaurant-owners/{owner_id}")
async def edit_restaurant_owner(
        owner_id: int,
        payload: EditOwnerRequest,
        current_user: dict = Depends(get_current_user),
        conn=Depends(get_db)
):
    if current_user.get("role") != "SUPER_ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Only Super Admin can edit restaurant owners."
        )

    with conn.cursor() as cur:
        # Check if the restaurant owner exists
        cur.execute("SELECT * FROM managers WHERE id = %s AND role = 'Restaurant Owner'", (owner_id,))
        owner = cur.fetchone()
        if not owner:
            raise HTTPException(status_code=404, detail="Restaurant owner not found.")

        # Update manager table
        if payload.full_name:
            cur.execute("UPDATE managers SET full_name = %s WHERE id = %s", (payload.full_name, owner_id))
        if payload.email:
            cur.execute("UPDATE managers SET email = %s WHERE id = %s", (payload.email, owner_id))

        # Update restaurant name
        if payload.restaurant_name:
            cur.execute("UPDATE restaurants SET name = %s WHERE created_by = %s", (payload.restaurant_name, owner_id))

        conn.commit()

    return {"message": "Restaurant owner updated successfully."}


@app.delete("/restaurants/{restaurant_id}")
async def delete_restaurant(
        restaurant_id: int,
        permanent: bool = False,  # Query parameter to choose between soft and hard delete
        current_user: dict = Depends(get_current_user),
        conn=Depends(get_db)
):
    """
    Delete a restaurant
    
    Args:
        restaurant_id: The ID of the restaurant to delete
        permanent: If True, permanently delete the restaurant (SUPER_ADMIN only).
                  If False (default), soft delete (set active=false)
    """
    logger.info(f"{'Permanently' if permanent else 'Soft'} deleting restaurant with ID: {restaurant_id} by user: {current_user['email']}")
    
    if permanent:
        # Hard delete - permanently remove from database
        from src.chat_gpt import hard_delete_restaurant
        return await hard_delete_restaurant(restaurant_id, current_user, conn)
    else:
        # Soft delete - just mark as inactive
        from src.chat_gpt import soft_delete_restaurant
        return await soft_delete_restaurant(restaurant_id, current_user, conn)


@app.post("/restaurants/{restaurant_id}/reactivate")
async def reactivate_restaurant(
    restaurant_id: int,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Reactivate a restaurant"""
    from src.chat_gpt import reactivate_restaurant as reactivate_rest
    return await reactivate_rest(restaurant_id, current_user, conn)

# Restaurant Listing Routes
@app.get("/restaurants/active")
async def get_active_restaurants(
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Get all active restaurants"""
    from src.chat_gpt import get_active_restaurants as get_active
    return await get_active(current_user, conn)

@app.get("/restaurants/{restaurant_id}/get_details")
async def get_restaurant_details(
    restaurant_id: int,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Get detailed information about a specific restaurant by ID.
    Access is restricted based on user role:
    - SUPER_ADMIN: Can view any restaurant
    - Restaurant Owner: Can only view restaurants they created
    - Regional/Restaurant Manager: Can only view assigned restaurants
    """
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Different query based on user role
        if current_user["role"] == "SUPER_ADMIN":
            # SUPER_ADMIN can access any restaurant
            cur.execute("""
                SELECT r.*, 
                       m.full_name as created_by_name,
                       m2.full_name as deactivated_by_name
                FROM restaurants r
                LEFT JOIN managers m ON r.created_by = m.id
                LEFT JOIN managers m2 ON r.deactivated_by = m2.id
                WHERE r.id = %s
            """, (restaurant_id,))
            
        elif current_user["role"] == "Restaurant Owner":
            # Restaurant owners can only access their own restaurants
            cur.execute("""
                SELECT * FROM restaurants r
                
                WHERE r.id = %s AND r.created_by = %s
            """, (restaurant_id, current_user["id"]))
            
        else:
            # Regional and Restaurant managers can only access assigned restaurants
            cur.execute("""
                SELECT r.*, 
                       m.full_name as created_by_name,
                       m2.full_name as deactivated_by_name
                FROM restaurants r
                LEFT JOIN managers m ON r.created_by = m.id
                LEFT JOIN managers m2 ON r.deactivated_by = m2.id
                JOIN restaurant_assignments ra ON r.id = ra.restaurant_id
                WHERE r.id = %s AND ra.manager_id = %s
            """, (restaurant_id, current_user["id"]))
        
        restaurant = cur.fetchone()
        if not restaurant:
            raise HTTPException(
                status_code=404,
                detail=f"Restaurant with ID {restaurant_id} not found or you don't have access to it"
            )
            
        # Get assigned managers
        cur.execute("""
            SELECT m.id, m.full_name, m.email, m.role, ra.assigned_at
            FROM restaurant_assignments ra
            JOIN managers m ON ra.manager_id = m.id
            WHERE ra.restaurant_id = %s AND m.active = true
            ORDER BY m.role, m.full_name
        """, (restaurant_id,))
        
        assigned_managers = cur.fetchall()
        restaurant["assigned_managers"] = assigned_managers or []
            
        # Get hours of operation if available
        from src.hours_of_operation import get_restaurant_hours_of_operation
        try:
            hours = await get_restaurant_hours_of_operation(restaurant_id, current_user, conn)
            restaurant["hours_of_operation"] = hours
        except:
            restaurant["hours_of_operation"] = []
            
        return restaurant
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving restaurant details: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve restaurant details: {str(e)}"
        )

@app.get("/restaurants/inactive")
async def get_inactive_restaurants(
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Get all inactive restaurants"""
    from src.chat_gpt import get_inactive_restaurants as get_inactive
    return await get_inactive(current_user, conn)

@app.get("/restaurants/all", response_model=List[Dict])
async def get_all_restaurants(
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    if current_user["role"] != RoleType.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Only SUPER_ADMIN can view all restaurants")
        
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                r.id,
                r.name,
                r.location,
                r.contact_number,
                r.created_at,
                r.created_by,
                r.image_url,
                r.unit_id,
                m1.email as created_by_email,
                r.active,
                r.deactivated_at,
                m2.email as deactivated_by_email
            FROM restaurants r
            LEFT JOIN managers m1 ON r.created_by = m1.id
            LEFT JOIN managers m2 ON r.deactivated_by = m2.id
            ORDER BY r.created_at DESC
        """)
        
        restaurants = cur.fetchall()
        return [dict(restaurant) for restaurant in restaurants]
    except Exception as e:
        logger.error(f"Error fetching all restaurants: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



#------------------------------------------ Then add the new endpoint:
@app.get("/restaurants_all/unassigned", response_model=List[Dict])
async def get_unassigned_restaurants_endpoint(
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Get unassigned restaurants based on user role:
    - SUPER_ADMIN: sees all unassigned restaurants
    - Regional Manager: sees only their assigned restaurants that are not assigned to any Restaurant Manager
    """
    return await get_unassigned_restaurants(current_user, conn)

@app.get("/restaurants_all/unassigneds")
async def get_unassigned_restaurants_endpoint(
    role_type: str,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    API endpoint to get unassigned restaurants based on role type.
    
    Args:
        role_type: The role type to check for ('Regional Manager' or 'Restaurant Manager')
        current_user: The authenticated user making the request
        conn: Database connection
        
    Returns:
        List of unassigned restaurants for the specified role
    """

    from src.chat_gpt import get_unassigned_restaurants_by_role

    return await get_unassigned_restaurants_by_role(current_user, role_type, conn)

#-------------------Just for Now--------------------#     
from fastapi import (
    FastAPI, 
    Depends, 
    HTTPException, 
    status, 
    File, 
    UploadFile, 
    Form
)

#
@app.put("/restaurants/{restaurant_id}")
async def update_restaurant(
        restaurant_id: int,
        name: str = Form(..., description="Restaurant name"),
        location: str = Form(..., description="Restaurant location"),
        city: str = Form(..., description="city name"),
        state: str = Form(..., description="state name"),
        zip_code: str = Form(..., description="zip code"),
        country: str = Form(..., description="country name"),
        contact_number: str = Form(..., description="Contact number"),
        unit_id: Optional[str] = Form(default=None, description="Restaurant unit ID"),
        image: Optional[UploadFile] = File(default=None, description="Restaurant image file"),
        image_url: Optional[str] = Form(default=None, description="Restaurant image URL"),
        current_user: dict = Depends(get_current_user),
        conn=Depends(get_db)
):
    """
    Update restaurant details with image upload support and optional unit_id
    """
    try:
        # Create the restaurant update object
        restaurant = RestaurantUpdate(
            name=name,
            location=location,
            contact_number=contact_number,
            city=city,
            state=state,
            zip_code=zip_code,
            country=country
        )
        
        # Handle unit_id update if provided
        if unit_id is not None:
            unit_id_data = UnitIdUpdate(unit_id=unit_id)
            await update_restaurant_unit_id(restaurant_id, unit_id_data, current_user, conn)
        
        # Update restaurant with image support
        result = await update_restaurant_with_image(
            restaurant_id,
            restaurant,
            image,
            image_url,
            current_user,
            conn
        )
        
        # Get the updated restaurant details including unit_id
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, location, city, state, zip_code, country, 
                   contact_number, unit_id, image_url, created_at, created_by, active
            FROM restaurants 
            WHERE id = %s
        """, (restaurant_id,))
        
        updated_restaurant = cur.fetchone()
        if updated_restaurant:
            # Update the result with current restaurant data including unit_id
            if "restaurant" in result:
                result["restaurant"].update({
                    "unit_id": updated_restaurant["unit_id"],
                    "city": updated_restaurant["city"],
                    "state": updated_restaurant["state"],
                    "zip_code": updated_restaurant["zip_code"],
                    "country": updated_restaurant["country"]
                })
        
        logger.info(f"Updated restaurant with ID: {restaurant_id} by user: {current_user['email']}")
        
        # Handle datetime serialization
        if isinstance(result, dict):
            for key, value in result.items():
                if isinstance(value, datetime):
                    result[key] = value.isoformat()
                elif isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        if isinstance(sub_value, datetime):
                            value[sub_key] = sub_value.isoformat()
                    
        return JSONResponse(content=result)
        
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )


@app.get("/restaurants/{restaurant_id}/hours-of-operation")
async def get_restaurant_hours_endpoint(
    restaurant_id: int,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
    ):
    """
    Get hours of operation for a specific restaurant
    
    This endpoint retrieves the hours of operation for a restaurant,
    grouped by meal period (e.g., Breakfast, Lunch, Dinner).
    
    Note: This endpoint is kept for backward compatibility.
    New endpoint is available at /api/hours-of-operation/restaurant/{restaurant_id}
    """
    from src.hours_of_operation import get_restaurant_hours_of_operation
    return await get_restaurant_hours_of_operation(restaurant_id, current_user, conn)

@app.put("/restaurants/{restaurant_id}/hours-of-operation")
async def update_restaurant_hours_endpoint(
    restaurant_id: int,
    hours_data: HoursOfOperationUpdate,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
    ):
    """
    Update hours of operation for a specific restaurant
    
    This endpoint allows updating the hours of operation for a restaurant by meal period,
    including day of week, availability, and time ranges for each day.
    
    Note: This endpoint is kept for backward compatibility.
    New endpoint is available at /api/hours-of-operation/restaurant/{restaurant_id}
    """
    from src.hours_of_operation import update_hours_of_operation
    return await update_hours_of_operation(restaurant_id, hours_data, current_user, conn)

@app.post("/restaurants/{restaurant_id}/hours-of-operation/meal-period")
async def add_meal_period_endpoint(
    restaurant_id: int,
    meal_period_data: MealPeriodCreate,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
    ):
    """
    Add a new meal period with days and time info for a restaurant
    
    This endpoint allows adding a new meal period (e.g., Breakfast, Lunch, Dinner)
    with operating hours for each day of the week.
    
    Note: This endpoint is kept for backward compatibility.
    New endpoint is available at /api/hours-of-operation/restaurant/{restaurant_id}/meal-period
    """
    from src.hours_of_operation import add_meal_period
    return await add_meal_period(restaurant_id, meal_period_data, current_user, conn)

@app.delete("/restaurants/{restaurant_id}/hours-of-operation/meal-period")
async def delete_meal_period_endpoint(
    restaurant_id: int,
    meal_period_data: MealPeriodDelete,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
    ):
    """
    Delete a meal period for a restaurant
    
    This endpoint allows deleting an entire meal period (e.g., Breakfast, Lunch, Dinner)
    and all its associated operating hours.
    
    Note: This endpoint is kept for backward compatibility.
    New endpoint is available at /api/hours-of-operation/restaurant/{restaurant_id}/meal-period
    """
    from src.hours_of_operation import delete_meal_period
    return await delete_meal_period(restaurant_id, meal_period_data, current_user, conn)



@app.post("/restaurants-new/{restaurant_id}/upload-image")
async def upload_restaurant_image(
    restaurant_id: int,
    image: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
    ):
    """Upload image for a specific restaurant"""
    try:
        # Check if restaurant exists and is active
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, image_url
            FROM restaurants 
            WHERE id = %s AND active = true
        """, (restaurant_id,))
        
        existing_restaurant = cur.fetchone()
        if not existing_restaurant:
            raise HTTPException(
                status_code=404,
                detail="Restaurant not found or inactive"
            )

        # Validate file type
        if not image.content_type.startswith('image/'):
            raise HTTPException(
                status_code=400,
                detail="File must be an image"
            )

        if not s3_client:
            raise HTTPException(
                status_code=503,
                detail="Image upload service is not available. Please contact administrator."
            )

        try:
            # Create S3 path
            user_folder = f"user_{current_user['id']}"
            restaurant_folder = f"{existing_restaurant['name'].lower().replace(' ', '_')}"
            s3_folder = f"uploads/users/{user_folder}/restaurants/{restaurant_folder}"
            
            # Generate unique filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_extension = os.path.splitext(image.filename)[1].lower()
            new_filename = f"restaurant_{timestamp}{file_extension}"
            s3_key = f"{s3_folder}/{new_filename}"

            # Delete old image if exists
            if existing_restaurant['image_url']:
                try:
                    old_key = existing_restaurant['image_url'].split(f"{BUCKET_NAME}.s3.amazonaws.com/")[1]
                    logger.info(f"Deleting old image: {old_key}")
                    s3_client.delete_object(
                        Bucket=BUCKET_NAME,
                        Key=old_key
                    )
                except Exception as e:
                    logger.error(f"Error deleting old image: {str(e)}")

            # Upload new image - removed ACL parameter
            content = await image.read()
            s3_client.put_object(
                Bucket=BUCKET_NAME,
                Key=s3_key,
                Body=content,
                ContentType=image.content_type
            )

            new_image_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}"

            # Update restaurant with new image URL
            cur.execute("""
                UPDATE restaurants 
                SET image_url = %s
                WHERE id = %s
                RETURNING id, name, image_url
            """, (new_image_url, restaurant_id))

            updated_restaurant = cur.fetchone()
            conn.commit()

            return {
                "message": "Restaurant image uploaded successfully",
                "restaurant": {
                    "id": updated_restaurant["id"],
                    "name": updated_restaurant["name"],
                    "image_url": updated_restaurant["image_url"]
                }
            }

        except Exception as e:
            logger.error(f"S3 operation error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error processing image: {str(e)}"
            )

    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error uploading restaurant image: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error uploading restaurant image: {str(e)}"
        )


#----------main.py-------------#
# File Processing and Chat Routes
@app.post("/claude-process-files/")
async def process_files(
    files: List[UploadFile],
    current_user: dict = Depends(get_current_user)
    ):
    """Process uploaded files"""
    return await processor.process_files(files, current_user["email"])


#---------------------main_c.py--#
@app.post("/openai-process-files/")
async def process_files(
    files: List[UploadFile],
    current_user: dict = Depends(get_current_user)
):
    """Process uploaded files"""
    return await processor.process_files(files, current_user["email"])





import os
import logging
import os
from anthropic import Anthropic
from openai import OpenAI
logger = logging.getLogger(__name__)

def mask_api_key(key: str) -> str:
    """Safely mask API key for logging"""
    if not key:
        return "NOT SET"
    if len(key) < 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"

def print_environment_config():
    """Print environment configuration safely"""
    logger.info("=" * 60)
    logger.info("🔑 ENVIRONMENT VARIABLE CHECK")
    logger.info("=" * 60)
    
    # Claude API Key
    claude_key = os.getenv("CLAUDE_API_KEY")
    logger.info(f"CLAUDE_API_KEY: {mask_api_key(claude_key) if claude_key else '❌ NOT SET'}")
    
    # OpenAI API Key
    openai_key = os.getenv("OPENAI_API_KEY")
    logger.info(f"OPENAI_API_KEY: {mask_api_key(openai_key) if openai_key else '❌ NOT SET'}")
    
    # Other useful environment variables
    logger.info(f"DATABASE_URL: {mask_api_key(os.getenv('DATABASE_URL', '')) if os.getenv('DATABASE_URL') else '❌ NOT SET'}")
    logger.info(f"ENVIRONMENT: {os.getenv('ENVIRONMENT', 'NOT SET')}")
    
    logger.info("=" * 60)

# Load and verify API keys
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Print on startup
print_environment_config()

# Verify keys are set
if not CLAUDE_API_KEY:
    logger.warning("⚠️ WARNING: CLAUDE_API_KEY is not set!")
if not OPENAI_API_KEY:
    logger.warning("⚠️ WARNING: OPENAI_API_KEY is not set!")

# Initialize clients
try:
    claude_client = Anthropic(api_key=CLAUDE_API_KEY) if CLAUDE_API_KEY else None
    logger.info(f"✅ Claude client initialized: {claude_client is not None}")
except Exception as e:
    logger.error(f"❌ Failed to initialize Claude client: {e}")
    claude_client = None

try:
    openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
    logger.info(f"✅ OpenAI client initialized: {openai_client is not None}")
except Exception as e:
    logger.error(f"❌ Failed to initialize OpenAI client: {e}")
    openai_client = None




from src.adora_db_helper import (
    get_adora_db_connection,
    check_if_adora_restaurants,
    get_store_ids_for_restaurants
)
from src.adora_prompt_executor import try_adora_prompt_query

# Replace the existing /chat-multi_restaurants/ endpoint with this updated version:

@app.post("/chat-multi_restaurants/", response_model=EnhancedChatResponse)
async def chat_multi_restaurants(
        question: str = Form(...),
        include_history: bool = Form(True),
        embedding_model: str = Form("claude"),
        restaurant_names: str = Form("[]"),
        store_ids: str = Form("[]"),  # NEW: For Adora stores
        conversation_id: Optional[str] = Form(None),
        extra_info_files: Optional[List[UploadFile]] = File(None),
        current_user: dict = Depends(get_current_user),
        conn=Depends(get_db)
):
    """
    Chat with restaurant data from multiple sources.
    
    Features:
    - ✅ Fast SQL query system for common questions
    - ✅ Adora restaurant support (queries DB2)
    - ✅ AI generates natural responses using SQL data
    - ✅ JSON file upload support for extra context
    - ✅ KPI data integration from database
    - ✅ Multiple restaurant support
    - ❌ Vector embeddings DISABLED
    
    The AI answers using:
    1. Direct SQL queries (for simple questions like "how many items?")
    2. KPI data from restaurant_kpi_graphs table
    3. Uploaded JSON files (hours of operation, menu details, etc.)
    """
    
    # Helper functions for safe formatting
    def safe_currency(value):
        if value is None:
            return "N/A"
        try:
            return f"${float(value):,.2f}"
        except (ValueError, TypeError):
            return "N/A"
    
    def safe_percentage(value):
        if value is None:
            return "N/A"
        try:
            return f"{float(value):.1f}%"
        except (ValueError, TypeError):
            return "N/A"
    
    def safe_number(value):
        if value is None:
            return "N/A"
        try:
            return f"{float(value):,}"
        except (ValueError, TypeError):
            return "N/A"
    
    try:
        # ========== STEP 1: PARSE RESTAURANT NAMES (UPDATED) ==========
        logger.info(f"🔥 Raw restaurant_names: '{restaurant_names}'")
        logger.info(f"🔥 Raw store_ids: '{store_ids}'")
        
        try:
            # Try parsing as JSON array first
            restaurant_names_list = json.loads(restaurant_names)
            
            if not isinstance(restaurant_names_list, list):
                restaurant_names_list = [str(restaurant_names_list)]
            
            logger.info(f"   ✅ Parsed restaurant_names as JSON array: {restaurant_names_list}")
            
        except (json.JSONDecodeError, ValueError):
            logger.info(f"   ⚠️  Not valid JSON, treating as comma-separated or single restaurant name")
            
            cleaned_name = restaurant_names.strip()
            
            # Remove surrounding brackets if they exist
            if cleaned_name.startswith('[') and cleaned_name.endswith(']'):
                cleaned_name = cleaned_name[1:-1].strip()
                logger.info(f"   🧹 Removed brackets: '{cleaned_name}'")
            
            # Remove quotes if present
            if (cleaned_name.startswith('"') and cleaned_name.endswith('"')) or \
               (cleaned_name.startswith("'") and cleaned_name.endswith("'")):
                cleaned_name = cleaned_name[1:-1].strip()
                logger.info(f"   🧹 Removed quotes: '{cleaned_name}'")
            
            # Check if it's a comma-separated list
            if ',' in cleaned_name:
                # Split by comma and clean each name
                restaurant_names_list = [
                    name.strip().strip('"').strip("'") 
                    for name in cleaned_name.split(',')
                    if name.strip()
                ]
                logger.info(f"   ✅ Split comma-separated values: {restaurant_names_list}")
            elif cleaned_name and cleaned_name != "":
                restaurant_names_list = [cleaned_name]
                logger.info(f"   ✅ Single restaurant: {restaurant_names_list}")
            else:
                restaurant_names_list = []
                logger.info(f"   ⚠️  Empty restaurant list")
        
        except Exception as e:
            logger.error(f"   ❌ Unexpected error parsing restaurant names: {e}")
            restaurant_names_list = []
        
        # Parse store_ids (NEW)
        try:
            store_ids_list = json.loads(store_ids)
            if not isinstance(store_ids_list, list):
                store_ids_list = [str(store_ids_list)]
            logger.info(f"   ✅ Parsed store_ids as JSON array: {store_ids_list}")
        except (json.JSONDecodeError, ValueError):
            logger.info(f"   ⚠️  store_ids not JSON, parsing manually")
            cleaned_ids = store_ids.strip()
            if cleaned_ids.startswith('[') and cleaned_ids.endswith(']'):
                cleaned_ids = cleaned_ids[1:-1].strip()
            if cleaned_ids and cleaned_ids != "":
                store_ids_list = [s.strip().strip('"').strip("'") for s in cleaned_ids.split(',') if s.strip()]
            else:
                store_ids_list = []
        except Exception as e:
            logger.error(f"   ❌ Unexpected error parsing store_ids: {e}")
            store_ids_list = []
        
        logger.info(f"   📋 Final restaurant_names_list: {restaurant_names_list}")
        logger.info(f"   📋 Final store_ids_list: {store_ids_list}")

        # Create request object for validation
        request = MultiRestaurantChatRequest(
            question=question,
            include_history=include_history,
            embedding_model=embedding_model,
            restaurant_names=restaurant_names_list,
            store_ids=store_ids_list,
            conversation_id=conversation_id
        )

        # Validate embedding model
        if request.embedding_model not in ["openai", "claude"]:
            raise HTTPException(
                status_code=400,
                detail="Embedding model must be 'openai' or 'claude'"
            )

        # ========== STEP 2: TRY PROMPT SYSTEMS ==========
        # ========== STEP 2: TRY PROMPT SYSTEMS ==========
        used_prompt_system = False
        prompt_data_context = ""
        original_question = question
        adora_conn = None
        
        # Filter valid store IDs
        if store_ids_list:
            valid_store_ids = [s for s in store_ids_list if s is not None and s != 'null' and s != '']
        else:
            valid_store_ids = []
        
        # Try Adora prompt system ONLY if we have valid store_ids
        if valid_store_ids:
            logger.info(f"🏪 Processing {len(valid_store_ids)} Adora store(s): {valid_store_ids}")
            logger.info(f"🔍 Checking Adora prompt system for: '{question}'")
            
            try:
                # Connect to Adora database
                adora_conn = get_adora_db_connection()
                
                # Try Adora prompt query
                adora_result = await try_adora_prompt_query(
                    user_question=question,
                    store_ids=valid_store_ids,
                    conn=adora_conn
                )
                
                if adora_result and adora_result.get('matched') and adora_result.get('query_executed'):
                    logger.info(f"✅ Matched Adora prompt: {adora_result.get('prompt_id')}")
                    
                    prompt_data_context = adora_result.get('data_for_ai', '')
                    
                    if prompt_data_context:
                        used_prompt_system = True
                        logger.info(f"📊 Adora SQL data retrieved successfully")
                        logger.info(f"   Context length: {len(prompt_data_context)} chars")
                        logger.info(f"   Preview: {prompt_data_context[:150]}...")
                        
                        question = f"""Based on the following database query results, please provide a helpful and conversational answer to the user's question.

User's Question: {original_question}

Database Results (Adora Stores):
{prompt_data_context}

Please provide a clear, friendly, and professional response that directly answers their question using this data. Be conversational and helpful, and offer relevant follow-up suggestions if appropriate."""
                        
                        logger.info("✨ Question enhanced with Adora SQL context")
                    else:
                        logger.info("⚠️  No data context available from Adora prompt system")
                else:
                    if adora_result:
                        logger.info(f"❌ Adora prompt not matched or query failed")
                    else:
                        logger.info(f"❌ Adora prompt system returned None")
                        
            except Exception as e:
                logger.error(f"❌ Error in Adora prompt system: {e}", exc_info=True)
        else:
            logger.info("⚠️ No valid Adora store IDs, skipping Adora system completely")
        
        # Try PostgreSQL prompt system if restaurant_names provided (and Adora didn't match)
        if restaurant_names_list and not used_prompt_system:
            logger.info(f"🏠 Processing {len(restaurant_names_list)} regular restaurant(s): {restaurant_names_list}")
            logger.info(f"🔍 Checking regular prompt system for: '{question}'")
            
            try:
                from src.simple_prompt_executor import try_prompt_query
                
                prompt_result = await try_prompt_query(
                    user_question=question,
                    restaurant_names=restaurant_names_list,
                    conn=conn
                )
                
                if prompt_result and prompt_result.get('matched') and prompt_result.get('query_executed'):
                    logger.info(f"✅ Matched regular prompt: {prompt_result.get('prompt_id')}")
                    
                    prompt_data_context = prompt_result.get('data_for_ai', '')
                    
                    if prompt_data_context:
                        used_prompt_system = True
                        logger.info(f"📊 Regular SQL data retrieved successfully")
                        logger.info(f"   Context length: {len(prompt_data_context)} chars")
                        logger.info(f"   Preview: {prompt_data_context[:150]}...")
                        
                        question = f"""Based on the following database query results, please provide a helpful and conversational answer to the user's question.

User's Question: {original_question}

Database Results:
{prompt_data_context}

Please provide a clear, friendly, and professional response that directly answers their question using this data. Be conversational and helpful, and offer relevant follow-up suggestions if appropriate."""
                        
                        logger.info("✨ Question enhanced with regular SQL context")
                    else:
                        logger.info("⚠️  No data context available from regular prompt system")
                else:
                    if prompt_result:
                        logger.info(f"❌ Regular prompt not matched or query failed")
                    else:
                        logger.info(f"❌ Regular prompt system returned None")
                        
            except ImportError as e:
                logger.error(f"❌ Failed to import regular prompt system: {e}")
            except Exception as e:
                logger.error(f"❌ Error in regular prompt system: {e}", exc_info=True)
        else:
            if not restaurant_names_list:
                logger.info("⚠️  No regular restaurants provided, skipping regular prompt system")
        # ========== STEP 3: PROCESS EXTRA INFO FILES ==========
        extra_context = ""
        extra_info_data = []
        
        if extra_info_files:
            logger.info(f"📎 Processing {len(extra_info_files)} extra info files")
            extra_context = "\n\n=== ADDITIONAL INFORMATION PROVIDED ===\n"
            
            for file in extra_info_files:
                try:
                    content = await file.read()
                    
                    try:
                        json_data = json.loads(content)
                        extra_info_data.append({
                            "filename": file.filename,
                            "data": json_data
                        })
                        
                        extra_context += f"\n--- File: {file.filename} ---\n"
                        
                        # Format JSON data
                        if isinstance(json_data, dict):
                            for key, value in json_data.items():
                                if isinstance(value, (str, int, float, bool)):
                                    extra_context += f"{key}: {value}\n"
                                elif isinstance(value, list):
                                    extra_context += f"{key}: {len(value)} items\n"
                                elif isinstance(value, dict):
                                    extra_context += f"{key}: {len(value)} properties\n"
                        
                        elif isinstance(json_data, list):
                            extra_context += f"Array with {len(json_data)} items\n"
                        
                    except json.JSONDecodeError:
                        # Treat as text
                        text_content = content.decode('utf-8', errors='ignore')
                        extra_info_data.append({
                            "filename": file.filename,
                            "data": text_content
                        })
                        extra_context += f"\n--- File: {file.filename} ---\n{text_content[:500]}...\n"
                        
                except Exception as e:
                    logger.warning(f"Error processing file {file.filename}: {str(e)}")
                    continue
            
            logger.info(f"✅ Processed extra files, context length: {len(extra_context)}")

        # ========== STEP 4: FETCH KPI DATA ==========
        kpi_context = ""
        if restaurant_names_list and not used_prompt_system:
            logger.info(f"📊 Fetching KPI data for {len(restaurant_names_list)} restaurant(s)")
            
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT 
                        r.id,
                        r.name,
                        kpi.graph_data,
                        kpi.updated_at
                    FROM restaurants r
                    LEFT JOIN restaurant_kpi_graphs kpi ON r.id = kpi.restaurant_id
                    WHERE r.name = ANY(%s) AND r.active = true
                """, (restaurant_names_list,))
                
                kpi_results = cur.fetchall()
                
                if kpi_results:
                    kpi_context = "\n\n=== RESTAURANT KPI DATA ===\n"
                    for row in kpi_results:
                        if row['graph_data']:
                            kpi_context += f"\n--- Restaurant: {row['name']} (ID: {row['id']}) ---\n"
                            graph_data = row['graph_data']
                            
                            # Determine time period from question
                            question_lower = original_question.lower()
                            selected_period = 'total'
                            period_label = "All Time"
                            
                            if 'last week' in question_lower or 'past week' in question_lower:
                                selected_period = 'last_week'
                                period_label = "Last Week"
                            elif 'last month' in question_lower or 'past month' in question_lower:
                                selected_period = 'last_month'
                                period_label = "Last Month"
                            elif 'last 6 months' in question_lower or 'past 6 months' in question_lower:
                                selected_period = 'last_6_months'
                                period_label = "Last 6 Months"
                            elif 'last 15 days' in question_lower or 'past 15 days' in question_lower:
                                selected_period = 'last_15_days'
                                period_label = "Last 15 Days"
                            
                            # Check if data has time period structure
                            if isinstance(graph_data, dict) and 'total' in graph_data:
                                # Data has time periods
                                logger.info(f"   Processing time-period KPI data for {row['name']}")
                                
                                period_data = graph_data.get(selected_period, {})
                                if period_data:
                                    kpi_context += f"Period: {period_label}\n"
                                    
                                    # Extract key metrics with safe formatting
                                    if 'Total COGS' in period_data:
                                        kpi_context += f"Total COGS: {safe_currency(period_data['Total COGS'])}\n"
                                    
                                    if 'Total Revenue' in period_data:
                                        kpi_context += f"Total Revenue: {safe_currency(period_data['Total Revenue'])}\n"
                                    
                                    if 'Gross Profit' in period_data:
                                        kpi_context += f"Gross Profit: {safe_currency(period_data['Gross Profit'])}\n"
                                    
                                    if 'Food Cost Percentage' in period_data:
                                        kpi_context += f"Food Cost %: {safe_percentage(period_data['Food Cost Percentage'])}\n"
                                    
                                    if 'Average Order Value' in period_data:
                                        kpi_context += f"Average Order Value: {safe_currency(period_data['Average Order Value'])}\n"
                                    
                                    if 'Inventory Stock Value' in period_data:
                                        kpi_context += f"Inventory Value: {safe_currency(period_data['Inventory Stock Value'])}\n"
                                    
                                    if 'Labor Cost Percentage' in period_data:
                                        kpi_context += f"Labor Cost %: {safe_percentage(period_data['Labor Cost Percentage'])}\n"
                            
                            elif isinstance(graph_data, dict):
                                # Flat structure (old format)
                                logger.info(f"   Processing flat KPI data for {row['name']}")
                                
                                if 'Total COGS' in graph_data:
                                    kpi_context += f"Total COGS: {safe_currency(graph_data['Total COGS'])}\n"
                                
                                if 'Total Revenue' in graph_data:
                                    kpi_context += f"Total Revenue: {safe_currency(graph_data['Total Revenue'])}\n"
                                
                                if 'Gross Profit' in graph_data:
                                    kpi_context += f"Gross Profit: {safe_currency(graph_data['Gross Profit'])}\n"
                                
                                if 'Food Cost Percentage' in graph_data:
                                    kpi_context += f"Food Cost %: {safe_percentage(graph_data['Food Cost Percentage'])}\n"
                            
                            # Add data freshness info
                            if row['updated_at']:
                                kpi_context += f"\nData last updated: {row['updated_at']}\n"
                        else:
                            logger.info(f"   No graph_data found for {row['name']}")
                    
                    logger.info(f"✅ KPI context built, length: {len(kpi_context)} chars")
                    logger.info(f"   KPI preview: {kpi_context[:200]}...")
                else:
                    logger.info("⚠️  No KPI results found for provided restaurants")
            
            except Exception as e:
                logger.error(f"❌ Error fetching KPI data: {str(e)}", exc_info=True)
                kpi_context = ""
        else:
            if not restaurant_names_list:
                logger.info("⚠️  No regular restaurants provided, skipping KPI data")

        # ========== STEP 5: PREPARE EMBEDDING INFO ==========
        all_locations = restaurant_names_list + [f"Store {sid}" for sid in store_ids_list]
        
        embedding_info = {
            "multi_location": len(all_locations) > 1,
            "location_count": len(all_locations),
            "embedding_model": request.embedding_model,
            "embeddings_enabled": False,
            "used_prompt_system": used_prompt_system,
            "adora_stores": len(store_ids_list),
            "regular_restaurants": len(restaurant_names_list),
            "has_kpi_data": bool(kpi_context),
            "extra_info_files": [
                {
                    "filename": info["filename"], 
                    "type": "json" if isinstance(info["data"], (dict, list)) else "text"
                } 
                for info in extra_info_data
            ] if extra_info_data else None
        }

        # ========== STEP 6: GENERATE CONVERSATION ID ==========
        if request.conversation_id is None:
            conversation_id = str(uuid.uuid4().hex[:12])
        else:
            conversation_id = request.conversation_id

        message_id = str(uuid.uuid4())

        # ========== STEP 7: COMBINE ALL CONTEXTS ==========
        enhanced_question = question  # Already enhanced if prompt system was used
        
        logger.info(f"🔧 Combining contexts...")
        logger.info(f"   Used prompt system: {used_prompt_system}")
        logger.info(f"   Has KPI context: {bool(kpi_context)}")
        logger.info(f"   Has extra context: {bool(extra_context)}")
        
        # ALWAYS add KPI context if available
        if kpi_context:
            if used_prompt_system:
                logger.info("   Adding KPI as supplementary context to prompt result")
                enhanced_question += f"\n\nAdditional Restaurant Metrics:\n{kpi_context}"
            else:
                logger.info("   Adding KPI as primary context")
                if any(term in original_question.lower() for term in ['cogs', 'cost', 'revenue', 'profit', 'kpi', 'total', 'inventory', 'labor']):
                    enhanced_question = f"Based on the following restaurant data:\n{kpi_context}\n\nQuestion: {enhanced_question}"
                else:
                    enhanced_question = f"{enhanced_question}\n{kpi_context}"
        
        # ALWAYS add extra file context if available
        if extra_context:
            if used_prompt_system:
                logger.info("   Extra file context already included in Step 3")
            else:
                logger.info("   Adding extra file context")
                enhanced_question += extra_context
        
        logger.info(f"✅ Final enhanced question length: {len(enhanced_question)} chars")
        logger.info(f"   Preview: {enhanced_question[:300]}...")

        # ========== STEP 8: GENERATE AI RESPONSE ==========
        logger.info(f"🤖 Generating AI response using {request.embedding_model}")
        logger.info(f"   Question length: {len(enhanced_question)} chars")
        logger.info(f"   Using prompt system: {used_prompt_system}")
        logger.info(f"   Has KPI data: {bool(kpi_context)}")
        logger.info(f"   Has extra files: {bool(extra_info_data)}")
        logger.info(f"   Embeddings enabled: False")
        
        if request.embedding_model == "claude":
            response = await processor.generate_response_with_embeddings(
                enhanced_question,
                current_user["email"],
                current_user["id"],
                embedding_info,
                "all",
                -1,
                request.include_history
            )

            # Update usage tracking
            try:
                await update_usage(
                    current_user=current_user,
                    conn=conn,
                    used_ai_engagements=True,
                )
            except Exception as usage_error:
                logger.warning(f"Failed to update usage: {usage_error}")

            # Get chat history
            user_history = [
                conv for conv in processor.history.conversations
                if conv.get('user_email') == current_user["email"]
            ]

            # Determine source type
            if used_prompt_system and store_ids_list:
                source_type = 'adora_prompt'
            elif used_prompt_system:
                source_type = 'prompt_with_ai'
            elif kpi_context:
                source_type = 'kpi_with_ai'
            else:
                source_type = 'ai_only'

            # Save to database
            cur = conn.cursor()
            try:
                cur.execute("""
                    INSERT INTO chat_history_claude (
                        user_id, restaurant_names, conversation_id, message_id, 
                        model, timestamp, question, answer, source
                    ) 
                    VALUES (%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,%s,%s,%s)
                    RETURNING *  
                """, (
                    current_user["id"], 
                    all_locations, 
                    conversation_id, 
                    message_id, 
                    request.embedding_model,
                    original_question,
                    response,
                    source_type
                ))

                conn.commit()
                history_saved = True
                logger.info(f"💾 Saved to chat_history_claude with source={source_type}")
                
            except Exception as e:
                conn.rollback()
                logger.error(f"Error saving chat history: {str(e)}")
                history_saved = False

            return {
                "response": response,
                "has_history": len(user_history) > 0,
                "embedding_info": embedding_info,
                "history_saved": history_saved,
                "chat_history": user_history,
                "conversation_id": conversation_id
            }

        else:  # OpenAI
            response = await processor2.generate_response_with_embeddings(
                enhanced_question,
                current_user["email"],
                current_user["id"],
                embedding_info,
                "all",
                -1,
                request.include_history
            )

            # Update usage tracking
            try:
                await update_usage(
                    current_user=current_user,
                    conn=conn,
                    used_ai_engagements=True,
                )
            except Exception as usage_error:
                logger.warning(f"Failed to update usage: {usage_error}")

            # Get chat history
            user_history = [
                conv for conv in processor2.history.conversations
                if conv.get('user_email') == current_user["email"]
            ]

            # Determine source type
            if used_prompt_system and store_ids_list:
                source_type = 'adora_prompt'
            elif used_prompt_system:
                source_type = 'prompt_with_ai'
            elif kpi_context:
                source_type = 'kpi_with_ai'
            else:
                source_type = 'ai_only'

            # Save to database
            cur = conn.cursor()
            try:
                cur.execute("""
                    INSERT INTO chat_history_openai (
                        user_id, restaurant_names, conversation_id, message_id,
                        model, timestamp, question, answer, source
                    ) 
                    VALUES (%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,%s,%s,%s)
                    RETURNING *
                """, (
                    current_user["id"], 
                    all_locations, 
                    conversation_id, 
                    message_id, 
                    request.embedding_model,
                    original_question,
                    response,
                    source_type
                ))

                conn.commit()
                history_saved = True
                logger.info(f"💾 Saved to chat_history_openai with source={source_type}")
                
            except Exception as e:
                conn.rollback()
                logger.error(f"Error saving chat history: {str(e)}")
                history_saved = False

            return {
                "response": response,
                "has_history": len(user_history) > 0,
                "embedding_info": embedding_info,
                "history_saved": history_saved,
                "chat_history": user_history,
                "conversation_id": conversation_id
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in chat_multi_restaurants endpoint: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error generating response: {str(e)}"
        )
    finally:
        # Close Adora connection if opened
        if adora_conn:
            adora_conn.close()
            logger.info("🔌 Closed Adora database connection")

#-------------------------#
from src.Audio_works import process_audio_upload, list_user_audios
from fastapi.responses import Response
# Add these routes to routes.py
# Add these imports at the top of routes.py (if not already present)
from fastapi import Depends, HTTPException, status, File, UploadFile
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import List
import logging

# Add these routes after your existing audio routes
@app.get("/audio/")
async def audio_root(
    current_user: dict = Depends(get_current_user)
):
    """
    Root endpoint for audio API
    Only accessible to authenticated users
    """
    return {
        "message": "Audio Recording and Transcription API",
        "user": {
            "id": current_user["id"],
            "email": current_user["email"],
            "role": current_user["role"]
        }
    }

#---------------------------------------------------#

@app.post("/audio/standalone-upload/")
async def standalone_upload_audio(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload and transcribe audio file - Standalone endpoint
    Only accessible to authenticated users
    """
    try:
        # Check if file is provided
        if not file:
            raise HTTPException(
                status_code=400,
                detail="No file uploaded"
            )
            
        # Check file type
        if not file.filename.lower().endswith(('.wav', '.mp3', '.m4a')):
            raise HTTPException(
                status_code=400,
                detail="File must be an audio file (WAV, MP3, or M4A)"
            )
        
        # Process the upload using the function from Audio_works.py
        result = await process_audio_upload(file, current_user)
        
        # Return the result with user information
        return {
            **result,
            "user": {
                "id": current_user["id"],
                "email": current_user["email"],
                "role": current_user["role"]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in standalone upload: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred during upload: {str(e)}"
        )
    
#-------------------------------------------------------#    
import os    

from src.Audio_works import process_audio_upload, download_file
@app.get("/audio/download/{file_type}/{filename}")
async def download_audio_file(
    file_type: str,
    filename: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Download audio or transcript file
    file_type: 'audio' or 'transcript'
    """
    # Handle the case where the file_type is passed as 'json' for transcripts
    if file_type.lower() in ['json', 'transcript']:
        file_type = 'transcript'
        # Ensure the filename has .json extension
        if not filename.endswith('.json'):
            base_name = os.path.splitext(filename)[0]
            filename = f"{base_name}.json"
    elif file_type.lower() != 'audio':
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Must be 'audio' or 'transcript'"
        )
    
    return await download_file(file_type, filename, current_user)
#----------------------------------------------------------#
from pydantic import BaseModel
class TranscriptChatRequest(BaseModel):
    file_type: str = "all"
    file_index: int = -1
    include_history: bool = True

@app.post("/chat-from-transcript-claude/")
async def chat_from_transcript_claude(
    transcript_file: UploadFile = File(...),
    file_type: str = Form("all"),
    file_index: int = Form(-1),
    include_history: bool = Form(True),
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Chat using transcript from JSON file using Claude."""
    try:
        content = await transcript_file.read()
        transcript_data = json.loads(content)
        
        if "results" in transcript_data and "transcripts" in transcript_data["results"]:
            transcript_text = transcript_data["results"]["transcripts"][0]["transcript"]
        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid transcript JSON format"
            )
        
        request = TranscriptChatRequest(
            file_type=file_type,
            file_index=file_index,
            include_history=include_history
        )
        
        return await processor.chat_from_transcript(
            conn=conn,
            current_user = current_user,
            transcript_text=transcript_text,
            request=request,
            user_email=current_user["email"]
        )
        
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON file"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing transcript: {str(e)}"
        )

#---------------------------------------------------------#

@app.post("/chat-from-transcript-openai/")
async def chat_from_transcript_openai(
    transcript_file: UploadFile = File(...),
    file_type: str = Form("all"),
    file_index: int = Form(-1),
    include_history: bool = Form(True),
    current_user: dict = Depends(get_current_user)
):
    """Chat using transcript from JSON file using OpenAI."""
    try:
        content = await transcript_file.read()
        transcript_data = json.loads(content)
        
        if "results" in transcript_data and "transcripts" in transcript_data["results"]:
            transcript_text = transcript_data["results"]["transcripts"][0]["transcript"]
        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid transcript JSON format"
            )
        
        request = TranscriptChatRequest(
            file_type=file_type,
            file_index=file_index,
            include_history=include_history
        )
        
        return await processor2.chat_from_transcript(
            transcript_text=transcript_text,
            request=request,
            user_email=current_user["email"]
        )
        
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON file"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing transcript: {str(e)}"
        )

#--------------------------------------------------#
# routes.py - Update the imports and WebSocket endpoint


# routes.py - Updated WebSocket endpoint
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import jwt
import json
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from src.chat_gpt import JWT_SECRET, JWT_ALGORITHM, DB_CONFIG
from src.main import processor, manager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """WebSocket endpoint for real-time chat"""
    conn = None
    try:
        # Get the token from the header before accepting the connection
        authorization = websocket.headers.get('authorization')
        if not authorization or not authorization.startswith('Bearer '):
            logger.error("No valid authorization header found")
            await websocket.close(code=4001)
            return

        try:
            # Verify token
            token = authorization.split(' ')[1]
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            email = payload.get("sub")
            
            if not email:
                logger.error("No email found in token")
                await websocket.close(code=4001)
                return

            # Get database connection
            conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
            cur = conn.cursor()
            
            # Verify user
            cur.execute("""
                SELECT * FROM managers 
                WHERE email = %s AND active = true
            """, (email,))
            user = cur.fetchone()

            if not user:
                logger.error(f"No active user found for email {email}")
                await websocket.close(code=4001)
                return

            # Accept connection through manager
            await manager.connect(websocket, client_id)
            logger.info(f"Authenticated user {email}")

            # Main message handling loop
            while True:
                try:
                    data = await websocket.receive_json()
                    logger.info(f"Received message: {data}")
                    
                    if data["type"] == "chat":
                        await processor.generate_streaming_response(
                            question=data["question"],
                            client_id=client_id,
                            manager=manager,
                            user_email=email,
                            file_type=data.get("file_type", "all"),
                            file_index=data.get("file_index", -1),
                            include_history=data.get("include_history", True)
                        )
                except WebSocketDisconnect:
                    logger.info(f"Client {client_id} disconnected")
                    break
                except json.JSONDecodeError:
                    logger.error("Invalid JSON received")
                    continue
                except Exception as e:
                    logger.error(f"Error handling message: {str(e)}")
                    await websocket.send_json({"error": str(e)})

        except jwt.InvalidTokenError:
            logger.error("Invalid token")
            await websocket.close(code=4001)
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            await websocket.close(code=4002)

    except WebSocketDisconnect:
        logger.info(f"Client {client_id} disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
        logger.info(f"Cleaning up connection for client {client_id}")
        if conn:
            conn.close()
        manager.disconnect(client_id)




@app.delete("/audio/clear")
async def clear_audio_files(
    current_user: dict = Depends(get_current_user)
):
    """
    Clear all audio files for the current user
    """
    return await clear_user_audios(current_user)

#-----------------------------------------------------#


@app.get("/restaurants/{restaurant_name}/files/list")
async def list_files_endpoint(
    restaurant_name: str,
    # category: str,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    List all files for a specific restaurant and category
    """
    return await list_csv_files(restaurant_name, current_user)

@app.get("/restaurants/{restaurant_id}/files/list_id")
async def list_files_endpoint_id(
    restaurant_id: int,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    List all files for a specific restaurant and category

    """
    from src.File_upload import list_s3_files_id
    return await list_s3_files_id(restaurant_id,  current_user, conn)

@app.get("/restaurants/{restaurant_name}/category_list")
async def list_cat_files_endpoint(
    restaurant_name: str,
    category: str,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    List all files for a specific restaurant and category
    """
    return await list_cat_csv_files(restaurant_name, category,  current_user)

@app.get("/restaurants/{restaurant_name}/files/csv-only")
async def list_csv_files_endpoint(
    restaurant_name: str,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    List only CSV files for a specific restaurant
    """
    return await list_csv_files_only(restaurant_name, current_user, conn)


@app.get("/restaurants/{restaurant_name}/file/download")
async def download_file_endpoint(
    restaurant_name: str,
    category: str,
    filename: str,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Download a file from a specific restaurant and category
    """

    file_type = filename.split('.')[-1].lower()
    
    
    file_content, headers = await download_csv_file(
        restaurant_name, category, filename, current_user
    )
    return Response(
        content=file_content,
        headers=headers,
        media_type=f"text/{file_type}"
    )

#-----------------------For deleting ----------------
@app.delete("/restaurants/{restaurant_name}/file/delete")
async def delete_file_endpoint(
    restaurant_name: str,
    category: str,
    filename: str,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Delete a file from a specific restaurant and category
    """
    return await delete_csv_file(restaurant_name, category, filename, current_user)



@app.delete("/restaurants/{restaurant_name}/files/delete-all")
async def delete_all_files_endpoint(
    restaurant_name: str,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Delete ALL files for the current user across all categories (Sales, Inventory, Menu, Labor)
    Deletes from both S3 and PostgreSQL
    """
    return await delete_all_user_files(restaurant_name, current_user)
#-------------------------just in case i want to get restaurant name-------------------------------#

@app.get("/restaurants/available-for-file")
async def get_available_restaurants_for_file(
        current_user: dict = Depends(get_current_user),
        conn=Depends(get_db)
):
    """Get available restaurants for file upload based on user role"""
    try:
        cur = conn.cursor()

        if current_user["role"] == "Non_Operators":
            raise HTTPException(
                status_code=403,
                detail="Access denied for non-operators."
            )
        logger.info(f"Fetching available restaurants for user: {current_user['email']} with role: {current_user['role']}")
        if current_user["role"] == "SUPER_ADMIN":
            # SUPER_ADMIN can see all active restaurants
            cur.execute("""
                SELECT 
                    r.id,
                    r.name,
                    r.location,
                    r.contact_number
                FROM restaurants r
                WHERE r.active = true AND r.store_id IS NULL
                ORDER BY r.name ASC 
            """)
        elif current_user["role"] == RoleType.RESTAURANT_OWNER:
            #  Restaurant owners can only see their created restaurants
            cur.execute("""
                SELECT 
                    r.id,
                    r.name,
                    r.location,
                    r.contact_number,
                    r.created_at,
                    r.created_by,
                    r.image_url,
                    m.email as created_by_email,
                    r.active
                FROM restaurants r
                LEFT JOIN managers m ON r.created_by = m.id
                WHERE r.created_by = %s AND r.active = true AND r.store_id IS NULL
                ORDER BY r.created_at DESC
            """, (current_user["id"],))
        else:
            # Regional and Restaurant managers can only see their assigned restaurants
            cur.execute("""
                SELECT 
                    r.id,
                    r.name,
                    r.location,
                    r.contact_number
                FROM restaurants r
                JOIN restaurant_assignments ra ON r.id = ra.restaurant_id
                WHERE ra.manager_id = %s AND r.active = true AND r.store_id IS NULL
                ORDER BY r.name ASC
            """, (current_user["id"],))

        restaurants = cur.fetchall()
        return [dict(restaurant) for restaurant in restaurants]
    except Exception as e:
        logger.error(f"Error fetching available restaurants: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


###############################################################
@app.get("/restaurants/available-for-file-adora")
async def get_available_restaurants_for_file(
        current_user: dict = Depends(get_current_user),
        conn=Depends(get_db)
):
    """Get available restaurants for file upload based on user role"""
    try:
        cur = conn.cursor()

        if current_user["role"] == "Non_Operators":
            raise HTTPException(
                status_code=403,
                detail="Access denied for non-operators."
            )

        if current_user["role"] == "SUPER_ADMIN":
            # SUPER_ADMIN can see all active restaurants
            cur.execute("""
                SELECT 
                    r.id,
                    r.name,
                    r.location,
                    r.contact_number
                FROM restaurants r
                WHERE r.active = true AND r.store_id IS NOT NULL
                ORDER BY r.name ASC
            """)
        elif current_user["role"] == RoleType.RESTAURANT_OWNER:
            #  Restaurant owners can only see their created restaurants
            cur.execute("""
                SELECT 
                    r.id,
                    r.name,
                    r.location,
                    r.contact_number,
                    r.created_at,
                    r.created_by,
                    r.image_url,
                    m.email as created_by_email,
                    r.active
                FROM restaurants r
                LEFT JOIN managers m ON r.created_by = m.id
                WHERE r.created_by = %s AND r.active = true AND r.store_id IS NOT NULL
                ORDER BY r.created_at DESC
            """, (current_user["id"],))
        else:
            # Regional and Restaurant managers can only see their assigned restaurants
            cur.execute("""
                SELECT 
                    r.id,
                    r.name,
                    r.location,
                    r.contact_number
                FROM restaurants r
                JOIN restaurant_assignments ra ON r.id = ra.restaurant_id
                WHERE ra.manager_id = %s AND r.active = true AND r.store_id IS NOT NULL
                ORDER BY r.name ASC
            """, (current_user["id"],))

        restaurants = cur.fetchall()
        return [dict(restaurant) for restaurant in restaurants]
    except Exception as e:
        logger.error(f"Error fetching available restaurants: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/restaurants/{restaurant_name}/upload_file")
async def upload_files_endpoint(
    restaurant_name: str,
    category: str = Form(..., description="Category (Inventory, Labor, Menu, or Sales)"),
    file: UploadFile = File(..., description="PDF, XLS, DOCX, and CSV file to upload"),
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Upload PDF, XLS, DOCX, and CSV file for a specific restaurant and category
    """
    return await upload_file(file, restaurant_name, category, current_user)

@app.post("/restaurants/{restaurant_id}/upload_file_id")
async def upload_files_endpoint_id(
    restaurant_id: int,
    category: str = Form(..., description="Category (Inventory, Labor, Menu, or Sales)"),
    file: UploadFile = File(..., description="PDF, XLS, DOCX, and CSV file to upload"),
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Upload PDF, XLS, DOCX, and CSV file for a specific restaurant and category
    
    """
    from src.File_upload import upload_file_id
    return await upload_file_id(file, restaurant_id, category, current_user)


# @app.get("/restaurants/{restaurant_id}/kpis")
# def get_restaurant_kpis(restaurant_id: int, db=Depends(get_db)):
#     processor = RestaurantKPIs(db)
#     result = processor.get_all_kpis(restaurant_id)

#     if result["status"] == "success":
#         return result["data"]
#     else:
#         raise HTTPException(status_code=500, detail=result["message"])


# @app.get("/restaurants/{restaurant_id}/inv-kpis")
# def get_restaurant_inv_kpis(restaurant_id: int, db=Depends(get_db)):
#     processor = RestaurantKPIs(db)
#     result = processor.get_essential_kpis(restaurant_id)

#     if result["status"] == "success":
#         return result["data"]
#     else:
#         raise HTTPException(status_code=500, detail=result["message"])


# @app.post("/restaurants/all-combined-kpis")
# def get_restaurant_all_combined_kpis(restaurant_name: str, 
#                                      db=Depends(get_db),
#                                      current_user: dict = Depends(get_current_user)
#                                      ):
#     """
#     Get all combined KPIs for a restaurant from all KPI functions.
#     This endpoint combines data from get_all_kpis, get_inventory_recipe_kpis, and get_essential_kpis.
    
#     Note: This endpoint uses database tables for KPI generation.
#     """
#     processor = RestaurantKPIs(db)
#     result = processor.get_all_combined_kpis(restaurant_name)

#     if result["status"] == "success":
#         return result["data"]
#     else:
#         raise HTTPException(status_code=500, detail=result["message"])


@app.post("/restaurants/s3-kpis")
async def get_restaurant_s3_kpis(
    restaurant_name: str,
    background_tasks: BackgroundTasks,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Get all KPIs for a restaurant by processing CSV files from S3 bucket.
    
    This endpoint:
    1. Retrieves all CSV files for the restaurant from S3
    2. Processes files from all categories (Sales, Inventory, Menu, Labor)
    3. Generates comprehensive KPIs using multiprocessing for efficiency
    
    Returns a complete set of KPIs similar to the all-combined-kpis endpoint,
    but sources data directly from S3 instead of database tables.
    """
    try:
        # Create S3 CSV processor
        processor = S3CSVProcessor()
        
        # Schedule cleanup task to run after response is sent
        background_tasks.add_task(processor.cleanup)
        
        # Generate KPIs from S3 data
        result = await processor.generate_kpis_from_s3(restaurant_name, current_user, db)
        
        if result["status"] == "success":
            return result["data"]
        else:
            raise HTTPException(status_code=500, detail=f"error in endpoint: {result['message']}")
            
    except Exception as e:
        logger.error(f"Error generating KPIs from S3: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get-restaurant-graph/{restaurant_id}")
async def get_restaurant_graph(restaurant_id: str, current_user: dict = Depends(get_current_user),conn=Depends(get_db)):
    """
    Endpoint to retrieve the restaurant graph from S3 for a given restaurant_id and user.
    
    Args:
    - restaurant_id: Restaurant ID to load the graph from
    - user: Current user (provided in the query parameters)
    
    Returns:
    - JSON data from S3 (graph data)
    """
    
    from src.File_upload import verify_restaurant_access_id
    
    restaurant = await verify_restaurant_access_id(restaurant_id, current_user, conn)

    if current_user["role"] == "Non_Operators":
        raise HTTPException(status_code=403, detail="Access denied for non-operators.")
    
    GRAPH_BASE_DIR = f'dashboard_graphs/{restaurant_id}/graph.json'
    from src.dashboard import load_file_from_s3
    # Check if the user has access to the restaurant
    
    # Load the results from S3
    results = load_file_from_s3(GRAPH_BASE_DIR)
    
    if results:
        return {"status": "success", "data": results}
    else:
        raise HTTPException(status_code=404, detail="Graph data not found for this restaurant.")


###############################################################

# Notification Endpoints
@app.post("/notifications/create")
async def create_notification_endpoint(
    user_id: int,
    title: str,
    message: str,
    type: str = "info",
    restaurant_id: Optional[int] = None,
    role: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Create a new notification for a user
    
    Only Super Admins, Restaurant Owners, and Regional Managers can create notifications
    """
    # Check permissions
    if current_user["role"] not in [RoleType.SUPER_ADMIN, "Restaurant Owner", "Regional Manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to create notifications"
        )
    
    from src.chat_gpt import create_notification
    return await create_notification(
        user_id=user_id,
        title=title,
        message=message,
        type=type,
        restaurant_id=restaurant_id,
        role=role,
        conn=conn
    )

@app.get("/notifications/me")
async def get_my_notifications(
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Get notifications for the current user
    """
    from src.chat_gpt import get_notifications_by_user_id
    return await get_notifications_by_user_id(
        user_id=current_user["id"],
        limit=limit,
        offset=offset,
        conn=conn
    )



@app.put("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Mark a notification as read
    
    Users can only mark their own notifications as read
    """
    from src.chat_gpt import mark_notification_as_read
    return await mark_notification_as_read(
        notification_id=notification_id,
        user_id=current_user["id"],
        conn=conn
    )

@app.put("/notifications/mark-all-read")
async def mark_all_read_endpoint(
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db)
    ):
    from src.chat_gpt import mark_all_notifications_as_read
    return await mark_all_notifications_as_read(
        user_id=current_user["id"],
        conn=db
    )

@app.delete("/notifications/{notification_id}")
async def delete_notification_endpoint(
    notification_id: int,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db)
    ):
    from src.chat_gpt import delete_notification
    return await delete_notification(
        notification_id=notification_id,
        user_id=current_user["id"],
        conn=db
    )


# Function to convert datetime to ISO format
def datetime_serializer(obj):
    if isinstance(obj, (datetime)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

@app.websocket("/wsn/notifications/{token}")
async def notifications_websocket(websocket: WebSocket, token: str):
    """
    WebSocket endpoint for real-time notifications.
    
    Clients connect to this endpoint to receive real-time notifications.
    Authentication is handled via a token passed in the URL path.
    """
    conn = None
    try:
        # Get the token from the header before accepting the connection
       
        if not token:
            logger.error("No token provided in the URL path for notification websocket")
            await websocket.close(code=4001)
            return

        try:
            # Verify token
            # token = authorization.split(' ')[1]
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            email = payload.get("sub")
            
            if not email:
                logger.error("No email found in token for notification websocket")
                await websocket.close(code=4001)
                return

            # Get database connection
            conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
            cur = conn.cursor()
            
            # Check if user exists in managers table
            cur.execute("""
                SELECT * FROM managers 
                WHERE email = %s AND active = true
            """, (email,))
            user = cur.fetchone()

            # if role == '
            # If not user:
            #     cur.execute("""
            #         SELECT * FROM users 
            #         WHERE email = %s AND active = true
            #     """, (email,))
            #     user = cur.fetchone()
            
            if not user:
                logger.error(f"No active user found for email {email} in notification websocket")
                await websocket.close(code=4001)
                return

            user_id = user["id"]
            
            # Import notification manager
            # from src.chat_gpt import notification_manager
            
            logger.info(f"notification_manager id: {id(notification_manager)}")
            # Accept connection through notification manager
            await notification_manager.connect(websocket, user_id)
            logger.info(f"User {user_id} connected to notification websocket")

            # Send initial notifications (last 10 unread)

            # cur.execute("""
            #     SELECT id, user_id, restaurant_id, role, title, message, type, is_read, created_at
            #     FROM notifications
            #     WHERE user_id = %s AND is_read = FALSE
            #     ORDER BY created_at DESC
            #     LIMIT 10
            # """, (user_id,))
            
            # unread_notifications = cur.fetchall()
            
            # # Convert datetime objects to ISO format
            # notifications_list = []
            # for notification in unread_notifications:
            #     # Ensure that datetime fields like 'created_at' are serialized
            #     notification_dict = dict(notification)
            #     if isinstance(notification_dict.get('created_at'), datetime):
            #         notification_dict['created_at'] = notification_dict['created_at'].isoformat()
            #     notifications_list.append(notification_dict)
            
            # # Send initial notifications
            # await websocket.send_json({
            #     "type": "notification",
            #     "action": "initial",
            #     "data": notifications_list
            # })
            
            # Keep the connection alive until client disconnects
            while True:
                # This will raise WebSocketDisconnect when client disconnects
                data = await websocket.receive_text()
                # We could handle client messages here if needed
        except jwt.InvalidTokenError:
            # logger.error("Invalid token for notification websocket")
            await websocket.close(code=4001)
        except WebSocketDisconnect:
            logger.info(f"User {user_id if 'user_id' in locals() else 'unknown'} disconnected from notification websocket")
        except Exception as e:
            logger.error(f"Error in notification websocket: {str(e)}")
            await websocket.close(code=4002)

    except WebSocketDisconnect:
        logger.error(f"Notification WebSocket error: {str(WebSocketDisconnect)}")
    except Exception as e:
        logger.error(f"Notification WebSocket error: {str(e)}")
    finally:
        # Clean up
        if 'user_id' in locals() and 'notification_manager' in locals():
            notification_manager.disconnect(websocket, user_id)
        
        if conn:
            conn.close()
        
        logger.info(f"Cleaned up notification websocket connection")






        #############################  main ################################

# Add this to your imports
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

# Add these models
class ChatMessage(BaseModel):
    id: int
    message_id: str
    model: str
    timestamp: datetime
    question: str
    answer: str
    source: Optional[str]
    tags: Optional[List[str]]
    restaurant_names: List[str]


class ChatHistoryResponse(BaseModel):
    conversation_id: str
    user_id: int
    messages: List[ChatMessage]

@app.get("/chat-history/{model}", response_model=List[ChatHistoryResponse])
async def get_chat_history(
    model: str,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Get chat history for the current user based on model type
    
    Args:
        model: Either 'openai' or 'claude' 
    """
    try:
        if model not in ["openai", "claude"]:
            raise HTTPException(
                status_code=400,
                detail="Model must be 'openai' or 'claude' "
            )

        # conn = DB_POOL.getconn()
        try:
            cur = conn.cursor()
            
            if model:
                # Query specific model table
                table_name = f"chat_history_{model}"
                cur.execute(f"""
                    SELECT 
                        id, user_id, restaurant_names, conversation_id,
                        message_id, model, timestamp, question, answer,
                        source, tags
                    FROM {table_name}
                    WHERE user_id = %s
                    ORDER BY timestamp DESC
                """, (current_user["id"],))
            
            history = cur.fetchall()
            
            # ✅ Group by conversation_id
            from collections import defaultdict

            grouped_history = defaultdict(list)

            for row in history:
                row_dict = dict(row)
                conv_id = row_dict["conversation_id"]
                grouped_history[conv_id].append({
                    "id": row_dict["id"],
                    "message_id": row_dict["message_id"],
                    "timestamp": row_dict["timestamp"],
                    "question": row_dict["question"],
                    "answer": row_dict["answer"],
                    "model": row_dict["model"],
                    "source": row_dict.get("source"),
                    "tags": row_dict.get("tags"),
                    "restaurant_names": row_dict.get("restaurant_names")
                })

            # ✅ Format into a list of conversations
            response = []
            for conv_id, messages in grouped_history.items():
                response.append({
                    "conversation_id": conv_id,
                    "user_id": messages[0]["id"],  # optional: or rows[0]["user_id"]
                    "messages": messages
                })
            
           
            return response
            
        finally:
            cur.close()
            # DB_POOL.putconn(conn)
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching chat history: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching chat history: {str(e)}"
        )

@app.delete("/chat-history/{model}/{conversation_id}")
async def delete_chat_conversation(
    model: str,
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Delete a specific chat conversation history
    
    Args:
        model: Either 'openai' or 'claude'
        conversation_id: The ID of the conversation to delete
    
    Returns:
        Message confirming deletion
    """
    try:
        # Validate model type
        if model not in ["openai", "claude"]:
            raise HTTPException(
                status_code=400,
                detail="Model must be 'openai' or 'claude'"
            )

        cur = conn.cursor()
        
        try:
            # Check if conversation exists and belongs to user
            table_name = f"chat_history_{model}"
           
            
            # Delete the conversation
            cur.execute(f"""
                DELETE FROM {table_name}
                WHERE conversation_id = %s AND user_id = %s
                RETURNING id
            """, (conversation_id, current_user["id"]))
            
            deleted_rows = cur.fetchone()
            if not deleted_rows:
                raise HTTPException(
                    status_code=404,
                    detail="Conversation not found to delete it"
                )

            conn.commit()
            
            logger.info(f"Deleted  messages from conversation {conversation_id} for user {current_user['id']}")
            
            return {
                "message": f"Successfully deleted conversation {conversation_id}",
                "deleted_messages": deleted_rows
            }
            
        except HTTPException:
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"Error deleting conversation: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete conversation: {str(e)}"
            )
            
    except Exception as e:
        logger.error(f"Error in delete_chat_conversation: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )



from typing import List
from fastapi import Query


@app.get("/restaurants/get-multiple-details")
async def get_restaurant_details(
    restaurant_ids: List[int] = Query(..., description="List of restaurant IDs (max 3)", min_items=1, max_items=3),
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Get detailed information about specific restaurants by IDs.
    Can accept 1-3 restaurant IDs and returns combined results.
    Access is restricted based on user role:
    - SUPER_ADMIN: Can view any restaurant
    - Restaurant Owner: Can only view restaurants they created
    - Regional/Restaurant Manager: Can only view assigned restaurants
    
    Query parameter: restaurant_ids (can be repeated)
    Example: /restaurants/get_details?restaurant_ids=1&restaurant_ids=2&restaurant_ids=3
    """
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Validate input
        if len(restaurant_ids) > 3:
            raise HTTPException(
                status_code=400,
                detail="Maximum 3 restaurant IDs allowed"
            )
        
        # Remove duplicates while preserving order
        unique_ids = list(dict.fromkeys(restaurant_ids))
        
        restaurants_data = []
        not_found_ids = []
        no_access_ids = []
        
        for restaurant_id in unique_ids:
            try:
                # Different query based on user role
                if current_user["role"] == "SUPER_ADMIN":
                    # SUPER_ADMIN can access any restaurant
                    cur.execute("""
                        SELECT r.*, 
                               m.full_name as created_by_name,
                               m2.full_name as deactivated_by_name
                        FROM restaurants r
                        LEFT JOIN managers m ON r.created_by = m.id
                        LEFT JOIN managers m2 ON r.deactivated_by = m2.id
                        WHERE r.id = %s
                    """, (restaurant_id,))
                    
                elif current_user["role"] == "Restaurant Owner":
                    # Restaurant owners can only access their own restaurants
                    cur.execute("""
                        SELECT * FROM restaurants r
                        WHERE r.id = %s AND r.created_by = %s
                    """, (restaurant_id, current_user["id"]))
                    
                else:
                    # Regional and Restaurant managers can only access assigned restaurants
                    cur.execute("""
                        SELECT r.*, 
                               m.full_name as created_by_name,
                               m2.full_name as deactivated_by_name
                        FROM restaurants r
                        LEFT JOIN managers m ON r.created_by = m.id
                        LEFT JOIN managers m2 ON r.deactivated_by = m2.id
                        JOIN restaurant_assignments ra ON r.id = ra.restaurant_id
                        WHERE r.id = %s AND ra.manager_id = %s
                    """, (restaurant_id, current_user["id"]))
                
                restaurant = cur.fetchone()
                
                if not restaurant:
                    # Check if restaurant exists but user doesn't have access
                    cur.execute("SELECT id FROM restaurants WHERE id = %s", (restaurant_id,))
                    if cur.fetchone():
                        no_access_ids.append(restaurant_id)
                    else:
                        not_found_ids.append(restaurant_id)
                    continue
                    
                # Convert to dict for easier manipulation
                restaurant_dict = dict(restaurant)
                
                # Get assigned managers
                cur.execute("""
                    SELECT m.id, m.full_name, m.email, m.role, ra.assigned_at
                    FROM restaurant_assignments ra
                    JOIN managers m ON ra.manager_id = m.id
                    WHERE ra.restaurant_id = %s AND m.active = true
                    ORDER BY m.role, m.full_name
                """, (restaurant_id,))
                
                assigned_managers = cur.fetchall()
                restaurant_dict["assigned_managers"] = [dict(manager) for manager in assigned_managers] if assigned_managers else []
                    
                # Get hours of operation if available
                from src.hours_of_operation import get_restaurant_hours_of_operation
                try:
                    hours = await get_restaurant_hours_of_operation(restaurant_id, current_user, conn)
                    restaurant_dict["hours_of_operation"] = hours
                except:
                    restaurant_dict["hours_of_operation"] = []
                
                restaurants_data.append(restaurant_dict)
                
            except Exception as e:
                logger.error(f"Error retrieving restaurant {restaurant_id} details: {str(e)}")
                # Continue processing other restaurants even if one fails
                continue
        
        # Prepare response
        response = {
            "restaurants": restaurants_data,
            "summary": {
                "requested_count": len(unique_ids),
                "found_count": len(restaurants_data),
                "not_found_ids": not_found_ids,
                "no_access_ids": no_access_ids
            }
        }
        
        # If no restaurants were found at all, return 404
        if not restaurants_data:
            if not_found_ids and not no_access_ids:
                raise HTTPException(
                    status_code=404,
                    detail=f"Restaurants with IDs {not_found_ids} not found"
                )
            elif no_access_ids and not not_found_ids:
                raise HTTPException(
                    status_code=403,
                    detail=f"You don't have access to restaurants with IDs {no_access_ids}"
                )
            else:
                raise HTTPException(
                    status_code=404,
                    detail=f"Restaurants not found or no access: not found {not_found_ids}, no access {no_access_ids}"
                )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving restaurants details: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve restaurants details: {str(e)}"
        )

from src.restaurant_management import (
    delete_restaurant_completely,
    hard_delete_restaurant
)

@app.delete("/restaurants/{restaurant_id}")
async def delete_restaurant_endpoint(
    restaurant_id: int,
    permanent: bool = False,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Delete a restaurant completely (all files, all data)
    
    - By default does SOFT DELETE (sets active=false)
    - Set permanent=true for PERMANENT deletion
    
    Only SUPER_ADMIN or Restaurant Owner can delete
    """
    if permanent:
        return await hard_delete_restaurant(restaurant_id, current_user, conn)  # ✅ Correct name
    else:
        return await delete_restaurant_completely(restaurant_id, current_user, conn)



from datetime import datetime, timedelta
import jwt
from pydantic import BaseModel

# Add these models
class TokenRequest(BaseModel):
    token: str

class TokenExtendResponse(BaseModel):
    message: str
    new_token: str
    new_expiration: datetime
    extended_minutes: int

class TokenInfoResponse(BaseModel):
    email: str
    role: str
    user_id: Optional[int] = None
    issued_at: Optional[datetime] = None
    expires_at: datetime
    time_remaining_minutes: float


@app.post("/auth/token-info", response_model=TokenInfoResponse)
async def get_token_info(
    token_request: TokenRequest,
    conn = Depends(get_db)
):
    """
    Get information from a token including the user's role
    
    Request Body:
    {
        "token": "your-jwt-token-here"
    }
    
    Returns:
    - User email
    - User role
    - User ID (if available)
    - Token issued at timestamp (if available)
    - Token expires at timestamp
    - Time remaining in minutes
    """
    try:
        # Decode the token
        payload = jwt.decode(
            token_request.token, 
            JWT_SECRET, 
            algorithms=[JWT_ALGORITHM]
        )
        
        email = payload.get("sub")
        role = payload.get("role")
        user_id = payload.get("id")
        
        if not email or not role:
            raise HTTPException(
                status_code=400,
                detail="Invalid token structure - missing email or role"
            )
        
        # If no user_id in token, look it up in database
        if not user_id:
            cur = conn.cursor()
            cur.execute("""
                SELECT id FROM managers 
                WHERE email = %s AND active = true
            """, (email,))
            user = cur.fetchone()
            if user:
                user_id = user["id"]
        
        # Get timestamps
        iat_timestamp = payload.get("iat")
        issued_at = datetime.fromtimestamp(iat_timestamp) if iat_timestamp else None
        
        exp_timestamp = payload.get("exp")
        if not exp_timestamp:
            raise HTTPException(
                status_code=400,
                detail="Token has no expiration time"
            )
        
        expires_at = datetime.fromtimestamp(exp_timestamp)
        
        # Calculate time remaining
        time_remaining = expires_at - datetime.now()
        time_remaining_minutes = time_remaining.total_seconds() / 60
        
        if time_remaining_minutes < 0:
            raise HTTPException(
                status_code=401,
                detail="Token has expired"
            )
        
        logger.info(f"✅ Token info retrieved for user {email} with role {role}")
        
        return TokenInfoResponse(
            email=email,
            role=role,
            user_id=user_id,
            issued_at=issued_at,
            expires_at=expires_at,
            time_remaining_minutes=round(time_remaining_minutes, 2)
        )
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token has expired"
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid token: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting token info: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get token info: {str(e)}"
        )

#-------------------help endppoint-----------------------
# Files will be stored in a shared location for all restaurants
# S3 Path: uploads/shared/{category}/{filename}

# 1. POST endpoint - Upload files (SUPER ADMIN ONLY)
@app.post("/shared/upload-category-files")
async def upload_shared_category_files(
    inventory_file: Optional[UploadFile] = File(None, description="Inventory file"),
    sales_file: Optional[UploadFile] = File(None, description="Sales file"),
    labor_file: Optional[UploadFile] = File(None, description="Labor/Employees file"),
    menu_file: Optional[UploadFile] = File(None, description="Menu file"),
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Upload shared files for all restaurants (SUPER ADMIN ONLY).
    Files uploaded here will be accessible to all restaurants.
    """
    try:
        # Check if user is SUPER_ADMIN
        if current_user["role"] != "SUPER_ADMIN":
            raise HTTPException(
                status_code=403,
                detail="Only SUPER_ADMIN can upload shared files"
            )
        
        files_dict = {
            'Inventory': inventory_file,
            'Sales': sales_file,
            'Labor': labor_file,
            'Menu': menu_file
        }
        
        if not any(files_dict.values()):
            raise HTTPException(
                status_code=400, 
                detail="At least one file must be uploaded"
            )
        
        upload_results = {}
        
        for category, file in files_dict.items():
            if file:
                try:
                    # Generate timestamp for unique filename
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    file_extension = os.path.splitext(file.filename)[1]
                    new_filename = f"{category.lower()}_{timestamp}{file_extension}"
                    
                    # Shared S3 path - same for all restaurants
                    s3_key = f"uploads/shared/{category}/{new_filename}"
                    
                    # Upload to S3
                    content = await file.read()
                    s3_client.put_object(
                        Bucket=BUCKET_NAME,
                        Key=s3_key,
                        Body=content,
                        ContentType=file.content_type or 'application/octet-stream'
                    )
                    
                    upload_results[category] = {
                        "status": "success",
                        "filename": new_filename,
                        "original_filename": file.filename,
                        "s3_url": f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}"
                    }
                    
                    logger.info(f"SUPER_ADMIN uploaded shared {category} file: {new_filename}")
                    
                except Exception as e:
                    logger.error(f"Error uploading {category} file: {str(e)}")
                    upload_results[category] = {
                        "status": "failed",
                        "error": str(e)
                    }
        
        return {
            "message": "Shared files upload completed",
            "uploaded_by": current_user["email"],
            "uploaded_files": len([r for r in upload_results.values() if r.get("status") == "success"]),
            "results": upload_results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading shared files: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload shared files: {str(e)}"
        )


# 2. GET endpoint - Retrieve shared files (AVAILABLE TO EVERYONE)
@app.get("/shared/get-category-files/{category}")
async def get_shared_category_files(
    category: str,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Get shared files for a specific category.
    Available to all authenticated users.
    Category must be one of: Inventory, Labor, Menu, Sales
    """
    try:
        # Validate category
        if category not in VALID_CATEGORIES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid category. Must be one of: {', '.join(VALID_CATEGORIES)}"
            )
        
        # Shared S3 path
        s3_folder = f"uploads/shared/{category}/"
        
        try:
            # List files in S3
            response = s3_client.list_objects_v2(
                Bucket=BUCKET_NAME,
                Prefix=s3_folder
            )
            
            files = []
            if 'Contents' in response:
                for obj in response['Contents']:
                    # Skip if it's just the folder
                    if obj['Key'] == s3_folder:
                        continue
                    
                    filename = obj['Key'].split('/')[-1]
                    file_info = {
                        'filename': filename,
                        'size': obj['Size'],
                        'last_modified': obj['LastModified'].isoformat(),
                        's3_key': obj['Key'],
                        'download_url': f"https://{BUCKET_NAME}.s3.amazonaws.com/{obj['Key']}"
                    }
                    files.append(file_info)
            
            # Sort by last_modified (newest first)
            files.sort(key=lambda x: x['last_modified'], reverse=True)
            
            return {
                "category": category,
                "file_count": len(files),
                "files": files,
                "accessed_by": current_user["email"],
                "user_role": current_user["role"]
            }
            
        except Exception as s3_error:
            logger.error(f"S3 error listing files: {str(s3_error)}")
            return {
                "category": category,
                "file_count": 0,
                "files": []
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting shared files: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve shared files: {str(e)}"
        )


# 3. DELETE endpoint - Delete shared files (SUPER ADMIN ONLY)
@app.delete("/shared/delete-category-files")
async def delete_shared_category_files(
    categories: List[str] = Query(..., description="Categories to delete files from"),
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Delete all shared files from specified categories (SUPER ADMIN ONLY).
    Can delete from one or more categories at once.
    
    Query parameter: categories (can be repeated)
    Example: /shared/delete-category-files?categories=Inventory&categories=Sales
    """
    try:
        # Check if user is SUPER_ADMIN
        if current_user["role"] != "SUPER_ADMIN":
            raise HTTPException(
                status_code=403,
                detail="Only SUPER_ADMIN can delete shared files"
            )
        
        # Validate categories
        invalid_categories = [c for c in categories if c not in VALID_CATEGORIES]
        if invalid_categories:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid categories: {', '.join(invalid_categories)}. Must be one of: {', '.join(VALID_CATEGORIES)}"
            )
        
        deletion_results = {}
        total_deleted = 0
        
        for category in categories:
            s3_folder = f"uploads/shared/{category}/"
            
            try:
                # List all files in the category
                response = s3_client.list_objects_v2(
                    Bucket=BUCKET_NAME,
                    Prefix=s3_folder
                )
                
                deleted_count = 0
                if 'Contents' in response:
                    # Prepare list of objects to delete
                    objects_to_delete = []
                    for obj in response['Contents']:
                        if obj['Key'] != s3_folder:  # Don't delete the folder itself
                            objects_to_delete.append({'Key': obj['Key']})
                            deleted_count += 1
                    
                    # Delete all objects
                    if objects_to_delete:
                        s3_client.delete_objects(
                            Bucket=BUCKET_NAME,
                            Delete={'Objects': objects_to_delete}
                        )
                        logger.info(f"SUPER_ADMIN deleted {deleted_count} shared files from {category}")
                
                deletion_results[category] = {
                    "status": "success",
                    "files_deleted": deleted_count
                }
                total_deleted += deleted_count
                
            except Exception as e:
                logger.error(f"Error deleting files from {category}: {str(e)}")
                deletion_results[category] = {
                    "status": "failed",
                    "error": str(e)
                }
        
        return {
            "message": "Shared files deletion completed",
            "deleted_by": current_user["email"],
            "total_files_deleted": total_deleted,
            "results": deletion_results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting shared files: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete shared files: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("routes:app", host="127.0.1.0", port=8000)

