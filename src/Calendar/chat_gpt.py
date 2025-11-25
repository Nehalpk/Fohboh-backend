from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, validator
from typing import Optional, Dict, List, Any, Union
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv
import logging
from enum import Enum
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import random
import string
import uuid
import aiofiles
from contextlib import asynccontextmanager
from jwt import PyJWTError
# Load environment variables
load_dotenv()

from src.config import notification_manager

# from smtp_send_email import send_email_api
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info(f"notification_manager id: {id(notification_manager)}")

# Utility functions
def generate_unit_id():
    """Generate a unique unit ID with format UNIT-XXXXXXXX"""
    import secrets
    random_part = secrets.token_hex(4).upper()  # 8 characters
    return f"UNIT-{random_part}"

def generate_unique_unit_id(conn):
    """Generate a unique unit ID that doesn't exist in database"""
    max_attempts = 100
    for _ in range(max_attempts):
        unit_id = generate_unit_id()
        cur = conn.cursor()
        cur.execute("SELECT id FROM restaurants WHERE unit_id = %s", (unit_id,))
        if not cur.fetchone():
            return unit_id
    raise Exception("Unable to generate unique unit ID after maximum attempts")

# Constants
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 300

SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = os.getenv("SMTP_PORT")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")


# SMTP_SERVER = "smtp.hostinger.com"
# SMTP_PORT = 465
# SENDER_EMAIL = "info@octalooptechnologies.com"
# SENDER_PASSWORD = "Poi098))"


UPLOAD_BASE_DIR = "uploads/users"

# Database configuration
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "database": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "port": os.getenv("DB_PORT")
}

# Security setup
security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Models
class RoleType(str, Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    RESTAURANT_OWNER = "Restaurant Owner"
    REGIONAL_MANAGER = "Regional Manager"
    RESTAURANT_MANAGER = "Restaurant Manager"

class ManagerBase(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    phone_number: str

    # @validator('password')
    # def validate_password(cls, v):
    #     if len(v) < 8:
    #         raise ValueError('Password must be at least 8 characters long')
    #     if not any(c.isupper() for c in v):
    #         raise ValueError('Password must contain at least one uppercase letter')
    #     if not any(c.islower() for c in v):
    #         raise ValueError('Password must contain at least one lowercase letter')
    #     if not any(c.isdigit() for c in v):
    #         raise ValueError('Password must contain at least one number')
    #     return v

class RegionalManagerCreate(ManagerBase):
    restaurant_names: List[str]

class RestaurantManagerCreate(ManagerBase):
    restaurant_name: str
    regional_manager_id: Optional[int] = None

#class RestaurantBase(BaseModel):
#    name: str
#    location: str
#    contact_number: str
class RestaurantBase(BaseModel):
    name: str
    location: str
    city: str
    state: str
    zip_code: str
    country: str
    contact_number: str
#class RestaurantUpdate(BaseModel):
#    name: str
#    location: str
#    contact_number: str

class RestaurantUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    contact_number: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    image_url: Optional[str] = None

class UnitIdUpdate(BaseModel):
    unit_id: str

class OTPRequest(BaseModel):
    email: EmailStr

class PasswordReset(BaseModel):
    email: EmailStr
    otp: str
    new_password: str

class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    address: Optional[str] = None

class PasswordUpdate(BaseModel):
    old_password: str
    new_password: str
    
    # @validator('new_password')
    # def validate_password(cls, v):
    #     if len(v) < 8:
    #         raise ValueError('Password must be at least 8 characters long')
    #     if not any(c.isupper() for c in v):
    #         raise ValueError('Password must contain at least one uppercase letter')
    #     if not any(c.islower() for c in v):
    #         raise ValueError('Password must contain at least one lowercase letter')
    #     if not any(c.isdigit() for c in v):
    #         raise ValueError('Password must contain at least one number')
    #     return v

class HoursOfOperationItem(BaseModel):
    day_of_week: str  # e.g., 'Mon', 'Tue', etc.
    meal_period: str  # e.g., 'Breakfast', 'Lunch', etc.
    is_available: bool = False
    start_time: Optional[str] = None  # Format: "HH:MM:SS"
    end_time: Optional[str] = None    # Format: "HH:MM:SS"

class HoursOfOperationUpdate(BaseModel):
    hours: List[HoursOfOperationItem]

# Utility Functions
def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)

def generate_otp(length: int = 6) -> str:
    return ''.join(random.choices(string.digits, k=length))

# Database Functions
def get_db():
    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    conn = Depends(get_db)
) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        email: str = payload.get("sub")
        role: str = payload.get("role")
        if email is None:
            raise credentials_exception
        if role is None:
            raise credentials_exception
        cur = conn.cursor()

        # if role != 'Non_Operators':
        cur.execute("""
                SELECT * FROM managers 
                WHERE email = %s AND active = true
            """, (email,))
        user = cur.fetchone()

        if user:
                return user
        # else:

        #     cur.execute("""
        #         SELECT * FROM users 
        #         WHERE email = %s AND active = true
        #         """, (email,))
        #     user = cur.fetchone()
                
        #     if user is None:
        #             raise credentials_exception
            
        #     return user
                    
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:  # Changed from JWTError to PyJWTError
        raise credentials_exception
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        raise credentials_exception

# checking validation of restaurant assignment
async def validate_restaurant_assignment(restaurant_name: str, conn) -> dict:
    """
    Validate if a restaurant can be assigned.
    Returns restaurant details if it can be assigned, raises HTTPException if it cannot.
    """
    try:
        cur = conn.cursor()
        
        # Check if restaurant exists and is active
        cur.execute("""
            SELECT r.id, r.name
            FROM restaurants r
            WHERE r.name = %s AND r.active = true
        """, (restaurant_name,))
        
        restaurant = cur.fetchone()
        if not restaurant:
            raise HTTPException(
                status_code=400,
                detail=f"Restaurant '{restaurant_name}' not found or not active"
            )

        # Check if restaurant is already assigned
        cur.execute("""
            SELECT 
                m.email,
                m.role
            FROM restaurant_assignments ra
            JOIN managers m ON ra.manager_id = m.id
            WHERE ra.restaurant_id = %s AND m.active = true
        """, (restaurant["id"],))
        
        existing_assignment = cur.fetchone()
        if existing_assignment:
            raise HTTPException(
                status_code=400,
                detail=f"Restaurant '{restaurant_name}' is already assigned to {existing_assignment['role']} ({existing_assignment['email']})"
            )

        return restaurant
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating restaurant assignment: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



# Email Functions
# def send_email(to_email: str, subject: str, html_content: str) -> bool:
#     try:
#         message = MIMEMultipart("alternative")
#         message["Subject"] = subject
#         message["From"] = SENDER_EMAIL
#         message["To"] = to_email
        
#         html_part = MIMEText(html_content, "html")
#         message.attach(html_part)
        
#         with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
#             server.starttls()
#             server.login(SENDER_EMAIL, SENDER_PASSWORD)
#             server.send_message(message)
#             logger.info(f"Email sent successfully to {to_email}")
#             return True
#     except Exception as e:
#         logger.error(f"Failed to send email to {to_email}: {str(e)}")
#         return False
def send_email(to_email: str, subject: str, html_content: str) -> bool:
    try:
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = SENDER_EMAIL
        message["To"] = to_email
        
        html_part = MIMEText(html_content, "html")
        message.attach(html_part)
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(message)
            logger.info(f"Email sent successfully to {to_email}")
            return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {str(e)}")
        return False
def send_verification_email(email: str, otp: str) -> bool:
    subject = "Email Verification Required"
    html_content = f"""
    <html>
        <body>
            <h2>Welcome to Our Platform!</h2>
            <p>Please verify your email address using the following OTP:</p>
            <h3 style="background-color: #f0f0f0; padding: 10px; text-align: center;">{otp}</h3>
            <p>This OTP will expire in 15 minutes.</p>
        </body>
    </html>
    """
    return send_email(email, subject, html_content)

def send_password_reset_email(email: str, otp: str) -> bool:
    subject = "Password Reset Request"
    html_content = f"""
    <html>
        <body>
            <h2>Password Reset Request</h2>
            <p>Use the following OTP to reset your password:</p>
            <h3 style="background-color: #f0f0f0; padding: 10px; text-align: center;">{otp}</h3>
            <p>This OTP will expire in 15 minutes.</p>
        </body>
    </html>
    """
    return send_email(email, subject, html_content)

# File Management Functions
def get_user_folder_path(user_id: int, email: str, role: str) -> str:
    safe_email = email.replace('@', '_at_')
    folder_name = f"{user_id}_{safe_email}_{role}"
    user_folder = os.path.join(UPLOAD_BASE_DIR, folder_name)
    profile_folder = os.path.join(user_folder, "profile_picture")
    os.makedirs(profile_folder, exist_ok=True)
    return profile_folder

def get_safe_filename(original_filename: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    extension = os.path.splitext(original_filename)[1].lower()
    return f"profile_picture_{timestamp}{extension}"


def init_db():
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        
        # Create role_type enum
        cur.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'role_type') THEN
                    CREATE TYPE role_type AS ENUM (
                        'SUPER_ADMIN',
                        'Regional Manager',
                        'Restaurant Manager',
                        'Restaurant Owner',
                        'Non_Operators'
                    );
                END IF;
            END $$;
        """)
        # cur.execute("""
        #     DO $$ 
        #     BEGIN 
        #         -- Check if the enum value exists
        #         IF NOT EXISTS (
        #             SELECT 1 FROM pg_enum 
        #             WHERE enumlabel = 'Restaurant Owner' 
        #             AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'role_type')
        #         ) THEN
        #             -- Add the new enum value
        #             ALTER TYPE role_type ADD VALUE 'Restaurant Owner';
        #         END IF;
        #     END $$;
        #  """)
        
        # Create managers table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS managers (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                role role_type NOT NULL,
                active BOOLEAN DEFAULT true,
                email_verified BOOLEAN DEFAULT false,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                created_by INTEGER REFERENCES managers(id) ON DELETE CASCADE,
                regional_manager_id INTEGER REFERENCES managers(id) ON DELETE CASCADE,
                full_name VARCHAR(100),
                phone_number VARCHAR(20),
                address TEXT,
                profile_image VARCHAR(255)
            )
        """)
          # Create users  table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                role TEXT NOT NULL,
                active BOOLEAN DEFAULT true,
                email_verified BOOLEAN DEFAULT false,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                
                
                full_name VARCHAR(100),
                phone_number VARCHAR(20),
                address TEXT,
                profile_image VARCHAR(255)
            )
        """)

        cur.execute("""
                    CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    action VARCHAR(50) NOT NULL,
                    entity_type VARCHAR(50) NOT NULL,
                    entity_id INTEGER NOT NULL,
                    entity_name VARCHAR(255) NOT NULL,
                    performed_by INTEGER REFERENCES managers(id) ON DELETE CASCADE,
                    details JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
        """)


#  Create the notifications table
        cur.execute("""  

                    CREATE TABLE IF NOT EXISTS notifications (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES managers(id) ON DELETE CASCADE,
                    restaurant_id INTEGER REFERENCES restaurants(id) ON DELETE CASCADE,
                    role VARCHAR(50),                          -- e.g., 'operator', 'admin', 'manager', 'viewer'
                    title VARCHAR(255),
                    message TEXT,
                    type VARCHAR(50),                          -- e.g., 'alert', 'info', 'warning'
                    is_read BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW()
                )

                    """)
        # create table for user setting for notifications
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_notification_settings (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES managers(id) ON DELETE CASCADE,
                    
                    -- Fraud and Security Notifications
                    fraud_alerts BOOLEAN DEFAULT false,
                    
                   
                    -- System Notifications
                    account_notifications BOOLEAN DEFAULT true,
                    subscription_alerts BOOLEAN DEFAULT true,
                    
                    -- Document Processing Notifications
                    file_processing_updates BOOLEAN DEFAULT false,
                    
                    -- Communication Preferences
                    -- email_notifications BOOLEAN DEFAULT false,
                    
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    
                    -- Ensure one settings record per user
                    CONSTRAINT unique_user_settings UNIQUE (user_id)
)
                    
                    """)

        # Create restaurants table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS restaurants (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) UNIQUE NOT NULL,
                location VARCHAR(255),
                contact_number VARCHAR(20),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                created_by INTEGER REFERENCES managers(id) ON DELETE CASCADE,
                active BOOLEAN DEFAULT true,
                deactivated_at TIMESTAMP WITH TIME ZONE,
                deactivated_by INTEGER REFERENCES managers(id)
            )
        """)

        # Create restaurants Hours Of Operations By Day table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS hours_of_operation (
            id SERIAL PRIMARY KEY,
            restaurant_id INTEGER REFERENCES restaurants(id) ON DELETE CASCADE,
            day_of_week VARCHAR(10) NOT NULL,           -- e.g., 'Mon', 'Tue', etc.
            meal_period VARCHAR(50) NOT NULL,           -- e.g., 'Breakfast', 'Lunch', etc.
            is_available BOOLEAN DEFAULT FALSE,         -- If that meal is available that day
            start_time TIME,                            -- From time (e.g., 09:00:00)
            end_time TIME,                              -- To time (e.g., 11:00:00)
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
                """)
        
        # Create restaurant_assignments table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS restaurant_assignments (
                id SERIAL PRIMARY KEY,
                manager_id INTEGER REFERENCES managers(id) ON DELETE CASCADE,
                restaurant_id INTEGER REFERENCES restaurants(id) ON DELETE CASCADE,
                assigned_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                assigned_by INTEGER REFERENCES managers(id)
            )
        """)
        cur.execute("""
                  DO $$ 
                  BEGIN
                      IF NOT EXISTS (
                          SELECT column_name 
                          FROM information_schema.columns 
                          WHERE table_name='restaurants' AND column_name='image_url'
                      ) THEN
                          ALTER TABLE restaurants ADD COLUMN image_url VARCHAR(255);
                      END IF;
                  END $$;
              """)
        
        # Add unit_id column if it doesn't exist
        cur.execute("""
                  DO $$ 
                  BEGIN
                      IF NOT EXISTS (
                          SELECT column_name 
                          FROM information_schema.columns 
                          WHERE table_name='restaurants' AND column_name='unit_id'
                      ) THEN
                          ALTER TABLE restaurants ADD COLUMN unit_id VARCHAR(50) UNIQUE;
                      END IF;
                  END $$;
              """)
        
        # Drop old constraint if it exists
        cur.execute("""
            DO $$ 
            BEGIN 
                IF EXISTS (
                    SELECT 1 
                    FROM pg_constraint 
                    WHERE conname = 'unique_restaurant_assignment'
                ) THEN
                    ALTER TABLE restaurant_assignments 
                    DROP CONSTRAINT unique_restaurant_assignment;
                END IF;
            END $$;
        """)


        
        
        # Create a view to help with constraint checking
        cur.execute("""
            CREATE OR REPLACE VIEW restaurant_manager_assignments AS
            SELECT ra.restaurant_id, m.role, COUNT(*) as count
            FROM restaurant_assignments ra
            JOIN managers m ON ra.manager_id = m.id
            WHERE m.role = 'Restaurant Manager'
            GROUP BY ra.restaurant_id, m.role;
        """)
        
        # Create trigger function for restaurant manager assignment check
        cur.execute("""
            CREATE OR REPLACE FUNCTION check_restaurant_manager_assignment()
            RETURNS TRIGGER AS $$
            DECLARE
                manager_role role_type;
            BEGIN
                -- Get the role of the manager being assigned
                SELECT role INTO manager_role
                FROM managers
                WHERE id = NEW.manager_id;
                
                -- If it's a Restaurant Manager, check if one already exists
                IF manager_role = 'Restaurant Manager' THEN
                    IF EXISTS (
                        SELECT 1
                        FROM restaurant_assignments ra
                        JOIN managers m ON ra.manager_id = m.id
                        WHERE ra.restaurant_id = NEW.restaurant_id
                        AND m.role = 'Restaurant Manager'
                        AND ra.id != COALESCE(NEW.id, 0)
                    ) THEN
                        RAISE EXCEPTION 'Restaurant already has a Restaurant Manager assigned';
                    END IF;
                END IF;
                
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
        
        # Create trigger
        cur.execute("""
            DROP TRIGGER IF EXISTS enforce_single_restaurant_manager ON restaurant_assignments;
            
            CREATE TRIGGER enforce_single_restaurant_manager
            BEFORE INSERT OR UPDATE ON restaurant_assignments
            FOR EACH ROW
            EXECUTE FUNCTION check_restaurant_manager_assignment();
        """)
        
        # Create restaurant_assignment_history table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS restaurant_assignment_history (
                id SERIAL PRIMARY KEY,
                restaurant_id INTEGER REFERENCES restaurants(id),
                manager_id INTEGER REFERENCES managers(id),
                assigned_by INTEGER REFERENCES managers(id),
                assigned_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                unassigned_at TIMESTAMP WITH TIME ZONE,
                unassigned_by INTEGER REFERENCES managers(id)
            )
        """)
        
        # Create manager_otps table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS manager_otps (
                id SERIAL PRIMARY KEY,
                manager_id INTEGER REFERENCES managers(id) ON DELETE CASCADE,
                otp VARCHAR(6) NOT NULL,
                purpose VARCHAR(20) NOT NULL,
                expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                used BOOLEAN DEFAULT false,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create manager_invitations table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS manager_invitations (
                id VARCHAR(36) PRIMARY KEY,
                email VARCHAR(255) NOT NULL,
                full_name VARCHAR(100) NOT NULL,
                phone_number VARCHAR(20) NOT NULL,
                role role_type NOT NULL,
                created_by INTEGER REFERENCES managers(id),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                used BOOLEAN DEFAULT false,
                restaurant_ids INTEGER[],
                regional_manager_id INTEGER REFERENCES managers(id)
            )
        """)
        
        conn.commit()
        logger.info("Database initialized successfully")
    except Exception as e:
        conn.rollback()
        logger.error(f"Database initialization error: {str(e)}")
        raise
    finally:
        conn.close()



async def create_initial_super_admins():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Create initial super admin if not exists
        cur.execute("""
            INSERT INTO managers (
                email,
                password_hash,
                role,
                email_verified,
                full_name
            )
            SELECT 
                'admin@example.com',
                %s,
                'SUPER_ADMIN',
                true,
                'Super Admin'
            WHERE NOT EXISTS (
                SELECT 1 FROM managers WHERE role = 'SUPER_ADMIN'
            )
        """, (get_password_hash("admin123"),))
        
        conn.commit()
        logger.info("Initial super admin created successfully")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating super admin: {e}")
        raise
    finally:
        conn.close()


# Authentication Routes
 #Now, let's update the login function
async def login(email: str, password: str, conn = None, remember_me: bool = False):
    try:
        cur = conn.cursor()
        
        # First, log the attempt
        logger.info(f"Login attempt for email: {email}")
        
        cur.execute("""
            SELECT 
                id, 
                email, 
                password_hash, 
                role,
                active
            FROM managers 
            WHERE email = %s AND role = 'SUPER_ADMIN'
        """, (email,))
        
        user = cur.fetchone()
        
        # Debug logging
        if user:
            logger.info(f"Found user with role: {user['role']}")
        else:
            logger.info("No user found")
            
        if not user or not user['active']:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Access denied. Only super administrators can log in through this endpoint."
            )
            
        # Verify password
        if not verify_password(password, user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Access denied. Only super administrators can log in through this endpoint."
            )

        # ========== ADD THIS SECTION HERE ========== ✅
        if remember_me:
            expiration_time = datetime.now() + timedelta(days=14)
            token_duration = "14 days"
        else:
            expiration_time = datetime.now() + timedelta(hours=1)
            token_duration = "1 hour"
        # ============================================

        # Create access token
        token_payload = {
            "sub": user["email"],
            "id": user["id"],
            "role": user["role"],
            "iat": datetime.now(),
            "exp": expiration_time  # ← Use the expiration_time from above
        }
        
        access_token = jwt.encode(token_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        
        logger.info(f"✅ User {email} logged in with {token_duration} token")
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "role": user["role"],
            "expires_in": token_duration,      # ← ADD this line
            "remember_me": remember_me          # ← ADD this line
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def manager_login(email: str, password: str, conn = None, remember_me: bool = False):
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, email, password_hash, role, email_verified 
            FROM managers 
            WHERE email = %s AND active = true
        """, (email,))
        
        manager = cur.fetchone()
        if not manager or not verify_password(password, manager["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password"
            )
        
        if manager["role"] == "Non_Operators":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )

        if not manager["email_verified"]:
            # Generate new OTP for verification
            otp = generate_otp()
            otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

            try:
                cur.execute("SELECT 1 FROM manager_otps WHERE manager_id = %s", (manager["id"],))
                if cur.fetchone():
                    cur.execute("DELETE FROM manager_otps WHERE manager_id = %s", (manager["id"],))
                    logger.info(f"Email verification record for {email} deleted successfully.")
                else:
                    logger.info(f"No email verification record found for {email}.")
            except Exception as e:
                conn.rollback()
                logger.error(f"Error deleting email verification record: {str(e)}")
            
            cur.execute("""
            INSERT INTO manager_otps (manager_id, otp, purpose, expires_at)
            VALUES (%s, %s, 'signup verification', %s)
            """, (manager["id"], otp, otp_expires_at))
            
            email_sent = send_verification_email(email, otp)
            
            conn.commit()
            
            return {
                "status": "unverified",
                "message": "Email not verified. A new verification code has been sent.",
                "email_sent": email_sent
            }
            
        from src.settings_and_integrations import get_notification_settings
        await get_notification_settings(manager, conn)

        # ========== ADD THIS SECTION HERE ========== ✅
        if remember_me:
            expiration_time = datetime.now() + timedelta(days=14)
            token_duration = "14 days"
        else:
            expiration_time = datetime.now() + timedelta(hours=1)
            token_duration = "1 hour"
        # ============================================

        token_payload = {
            "sub": manager["email"],
            "id": manager["id"],
            "role": manager["role"],
            "iat": datetime.now(),
            "exp": expiration_time  # ← Use the expiration_time from above
        }
        
        access_token = jwt.encode(token_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        
        logger.info(f"✅ Manager {email} logged in with {token_duration} token")
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "role": manager["role"],
            "expires_in": token_duration,      # ← ADD this line
            "remember_me": remember_me          # ← ADD this line
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Manager login error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
# Registration Routes
async def register_regional_manager(
    manager: RegionalManagerCreate,
    current_user: dict,
    conn = None
):
    if current_user["role"] != RoleType.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Only SUPER_ADMIN can register Regional Managers")

    try:
        cur = conn.cursor()
        
        # Check if email exists
        cur.execute("SELECT id FROM managers WHERE email = %s", (manager.email,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Email already registered")

        # Validate minimum and maximum number of restaurants
        if not manager.restaurant_names:
            raise HTTPException(
                status_code=400,
                detail="At least one restaurant must be assigned to the Regional Manager"
            )
            
        if len(manager.restaurant_names) > 10:  # Adjust limit as needed
            raise HTTPException(
                status_code=400,
                detail="Maximum number of restaurants that can be assigned to a Regional Manager is 10"
            )

        # Verify restaurants exist and are not already assigned
        restaurant_ids = []
        already_assigned = []
        
        for restaurant_name in manager.restaurant_names:
            # Check restaurant exists and is active
            cur.execute("""
                SELECT id 
                FROM restaurants 
                WHERE name = %s AND active = true
            """, (restaurant_name,))
            
            result = cur.fetchone()
            if not result:
                raise HTTPException(
                    status_code=400,
                    detail=f"Restaurant '{restaurant_name}' not found or not active"
                )
                
            # Check if restaurant is already assigned
            cur.execute("""
                SELECT 
                    r.name as restaurant_name,
                    m.email as manager_email,
                    m.full_name as manager_name,
                    m.role as manager_role
                FROM restaurant_assignments ra
                JOIN restaurants r ON ra.restaurant_id = r.id
                JOIN managers m ON ra.manager_id = m.id
                WHERE ra.restaurant_id = %s AND m.active = true
            """, (result["id"],))
            
            assignment = cur.fetchone()
            if assignment:
                already_assigned.append({
                    'restaurant': assignment['restaurant_name'],
                    'assigned_to': f"{assignment['manager_role']} ({assignment['manager_email']})"
                })
            else:
                restaurant_ids.append(result["id"])

        # If any restaurants are already assigned, raise error with details
        if already_assigned:
            detail = "The following restaurants are already assigned:\n"
            for item in already_assigned:
                detail += f"- {item['restaurant']} → {item['assigned_to']}\n"
            raise HTTPException(status_code=400, detail=detail)

        # Create regional manager
        cur.execute("""
            INSERT INTO managers (
                email, 
                password_hash, 
                role, 
                created_by, 
                email_verified,
                full_name,
                phone_number
            )
            VALUES (%s, %s, 'Regional Manager', %s, false, %s, %s)
            RETURNING id
        """, (
            manager.email, 
            get_password_hash(manager.password), 
            current_user["id"],
            manager.full_name,
            manager.phone_number
        ))
        
        manager_id = cur.fetchone()["id"]

        # Generate verification OTP
        otp = generate_otp()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

        try:
            cur.execute("DELETE FROM manager_otps WHERE manager_id = %s", (manager_id,))
            logger.info(f"OTP records deleted for manager_id: {manager_id}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error deleting OTPs for manager_id {manager_id}: {str(e)}")

        
        cur.execute("""
            INSERT INTO manager_otps (manager_id, otp, purpose, expires_at)
            VALUES (%s, %s, 'verification', %s)
        """, (manager_id, otp, expires_at))

        # Assign restaurants and record in history
        assigned_restaurants = []
        for restaurant_id in restaurant_ids:
            # Create assignment
            cur.execute("""
                INSERT INTO restaurant_assignments (
                    manager_id, 
                    restaurant_id, 
                    assigned_by,
                    assigned_at
                )
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            """, (manager_id, restaurant_id, current_user["id"]))
            
            # Record in assignment history
            cur.execute("""
                INSERT INTO restaurant_assignment_history (
                    restaurant_id,
                    manager_id,
                    assigned_by,
                    assigned_at
                )
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            """, (restaurant_id, manager_id, current_user["id"]))
            
            # Get restaurant details for response
            cur.execute("""
                SELECT name, location 
                FROM restaurants 
                WHERE id = %s
            """, (restaurant_id,))
            restaurant = cur.fetchone()
            assigned_restaurants.append({
                'name': restaurant['name'],
                'location': restaurant['location']
            })

        # Send verification email
        email_sent = send_verification_email(manager.email, otp)

        conn.commit()
        
        return {
            "message": "Regional Manager registered successfully. Verification email sent.",
            "manager": {
                "id": manager_id,
                "email": manager.email,
                "full_name": manager.full_name,
                "role": "Regional Manager",
                "phone_number": manager.phone_number,
                "email_verified": False,
                "assigned_restaurants": assigned_restaurants
            },
            "verification_email_sent": email_sent
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error registering regional manager: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



async def register_restaurant_manager(
    manager: RestaurantManagerCreate,
    current_user: dict,
    conn = None
):
    if current_user["role"] not in [RoleType.SUPER_ADMIN, RoleType.REGIONAL_MANAGER]:
        raise HTTPException(status_code=403, detail="Not authorized to register Restaurant Managers")

    try:
        cur = conn.cursor()
        
        # Check if email exists
        cur.execute("SELECT id FROM managers WHERE email = %s", (manager.email,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Email already registered")

        # Determine and validate regional manager ID
        regional_manager_id = None
        if current_user["role"] == RoleType.REGIONAL_MANAGER:
            regional_manager_id = current_user["id"]
        else:
            if not manager.regional_manager_id:
                raise HTTPException(status_code=400, detail="Regional manager ID is required")
                
            cur.execute("""
                SELECT id, email, full_name
                FROM managers 
                WHERE id = %s AND role = 'Regional Manager' AND active = true
            """, (manager.regional_manager_id,))
            regional_manager = cur.fetchone()
            
            if not regional_manager:
                raise HTTPException(status_code=400, detail="Invalid regional manager ID")
            regional_manager_id = manager.regional_manager_id

        # Check if restaurant exists and is active
        cur.execute("""
            SELECT id, name, location, contact_number
            FROM restaurants 
            WHERE name = %s AND active = true
        """, (manager.restaurant_name,))
        
        restaurant = cur.fetchone()
        if not restaurant:
            raise HTTPException(
                status_code=400, 
                detail=f"Restaurant '{manager.restaurant_name}' not found or not active"
            )

        # Verify restaurant belongs to regional manager
        cur.execute("""
            SELECT ra.manager_id 
            FROM restaurant_assignments ra
            WHERE ra.restaurant_id = %s 
            AND ra.manager_id = %s
        """, (restaurant["id"], regional_manager_id))
        
        if not cur.fetchone():
            raise HTTPException(
                status_code=403, 
                detail=f"Restaurant '{manager.restaurant_name}' is not assigned to the specified regional manager"
            )

        # Check if restaurant is already assigned to a restaurant manager
        cur.execute("""
            SELECT 
                m.email,
                m.full_name,
                m.role
            FROM restaurant_assignments ra
            JOIN managers m ON ra.manager_id = m.id
            WHERE ra.restaurant_id = %s 
            AND m.role = 'Restaurant Manager'
            AND m.active = true
        """, (restaurant["id"],))
        
        existing_assignment = cur.fetchone()
        if existing_assignment:
            raise HTTPException(
                status_code=400,
                detail=f"Restaurant '{manager.restaurant_name}' is already assigned to Restaurant Manager {existing_assignment['full_name']} ({existing_assignment['email']})"
            )

        # Create restaurant manager
        cur.execute("""
            INSERT INTO managers (
                email, 
                password_hash, 
                role, 
                created_by, 
                email_verified,
                regional_manager_id,
                full_name,
                phone_number
            )
            VALUES (%s, %s, 'Restaurant Manager', %s, false, %s, %s, %s)
            RETURNING id
        """, (
            manager.email, 
            get_password_hash(manager.password), 
            current_user["id"],
            regional_manager_id,
            manager.full_name,
            manager.phone_number
        ))
        
        manager_id = cur.fetchone()["id"]

        # Generate verification OTP
        otp = generate_otp()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
        
        cur.execute("""
            INSERT INTO manager_otps (manager_id, otp, purpose, expires_at)
            VALUES (%s, %s, 'verification', %s)
        """, (manager_id, otp, expires_at))

        # Assign restaurant and record in history
        cur.execute("""
            INSERT INTO restaurant_assignments (
                manager_id, 
                restaurant_id, 
                assigned_by,
                assigned_at
            )
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
        """, (manager_id, restaurant["id"], current_user["id"]))

        # Record in assignment history
        cur.execute("""
            INSERT INTO restaurant_assignment_history (
                restaurant_id,
                manager_id,
                assigned_by,
                assigned_at
            )
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
        """, (restaurant["id"], manager_id, current_user["id"]))

        # Get regional manager details for response
        cur.execute("""
            SELECT email, full_name
            FROM managers
            WHERE id = %s
        """, (regional_manager_id,))
        regional_manager_details = cur.fetchone()

        # Send verification email
        email_sent = send_verification_email(manager.email, otp)

        conn.commit()
        
        return {
            "message": "Restaurant Manager registered successfully. Verification email sent.",
            "manager": {
                "id": manager_id,
                "email": manager.email,
                "full_name": manager.full_name,
                "role": "Restaurant Manager",
                "phone_number": manager.phone_number,
                "email_verified": False,
                "regional_manager": {
                    "id": regional_manager_id,
                    "email": regional_manager_details["email"],
                    "full_name": regional_manager_details["full_name"]
                },
                "assigned_restaurant": {
                    "name": restaurant["name"],
                    "location": restaurant["location"],
                    "contact_number": restaurant["contact_number"]
                }
            },
            "verification_email_sent": email_sent
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error registering restaurant manager: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Email Verification Routes
async def verify_manager_email(email: str, otp: str, conn = None):
    try:
        cur = conn.cursor()

        
        cur.execute("""
            UPDATE managers 
            SET email_verified = true 
            WHERE id IN (
                SELECT manager_id 
                FROM manager_otps 
                WHERE otp = %s 
                
                AND expires_at > CURRENT_TIMESTAMP
                AND used = false
            )
            AND email = %s
            AND active = true
            RETURNING id, email, role
        """, (otp, email))
        
        if cur.rowcount == 0:
            raise HTTPException(status_code=400, detail="Invalid or expired OTP")
            
        verified_manager = cur.fetchone()
        
        # Mark OTP as used
        cur.execute("""
            DELETE FROM manager_otps 
            WHERE manager_id = %s AND otp = %s 
        """, (verified_manager["id"] ,otp,))
        
        conn.commit()
        return {
            "message": "Email verified successfully",
            "role": verified_manager["role"]
        }
    except HTTPException:
        raise  # ⚠️ Let FastAPI handle HTTPExceptions properly

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

async def resend_verification_otp(request: OTPRequest, conn = None):
    try:
        cur = conn.cursor()  #AND active = true
        query = """
            SELECT id, email, email_verified
            FROM managers 
            WHERE email = %s AND active = true
        """
        try:
            cur.execute(query, (request.email,))
        
            manager = cur.fetchone()
        except:
            raise HTTPException(status_code=404, detail="Manager not found")
            
        if not manager:
            raise HTTPException(status_code=404, detail="Manager not found")
        
        if manager["email_verified"]:
            raise HTTPException(status_code=400, detail="Email already verified")
        
        # Generate new OTP
        otp = generate_otp()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

        try:
            cur.execute("DELETE FROM manager_otps WHERE manager_id = %s", (manager["id"],))
            # logger.info(f"OTP records deleted for manager_id: {manager["id"]}")
        except Exception as e:
            conn.rollback()
            # logger.error(f"Error deleting OTPs for manager_id {manager["id"]}: {str(e)}")
        
        cur.execute("""
            INSERT INTO manager_otps (manager_id, otp, purpose, expires_at)
            VALUES (%s, %s, 'verification', %s)
        """, (manager["id"], otp, expires_at))
        
        # Send verification email
        send_verification_email(request.email, otp)
        
        conn.commit()
        return {"message": "Verification OTP resent successfully"}
    except HTTPException:
        raise  # ⚠️ Let FastAPI handle HTTPExceptions properly
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail="Internal server error. Please check logs.")


# Password Reset Routes
async def forgot_password(request: OTPRequest, conn = None):
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, email
            FROM managers 
            WHERE email = %s AND active = true
        """, (request.email,))
        
        manager = cur.fetchone()
        if not manager:
            raise HTTPException(status_code=404, detail="Manager not found")
        
        # Generate password reset OTP
        otp = generate_otp()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

        try:
            cur.execute("DELETE FROM manager_otps WHERE manager_id = %s", (manager["id"],))
            # logger.info(f"OTP records deleted for manager_id: {manager["id"]}")
        except Exception as e:
            conn.rollback()
            # logger.error(f"Error deleting OTPs for manager_id {manager["id"]}: {str(e)}")
        
        cur.execute("""
            INSERT INTO manager_otps (manager_id, otp, purpose, expires_at)
            VALUES (%s, %s, 'password_reset', %s)
        """, (manager["id"], otp, expires_at))
        
        # Send password reset email
        sent = send_password_reset_email(request.email, otp)

        if sent:
            conn.commit()
            return {"message": "Password reset OTP sent successfully"}
        else:
            return {"message": "Password reset OTP not sent successfully"}

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"ERROR in forgot password {e}")

async def reset_password(reset_data: PasswordReset, conn = None):
    try:
        cur = conn.cursor()
        cur.execute("""
            WITH valid_otp AS (
                SELECT manager_id 
                FROM manager_otps 
                WHERE otp = %s 
                AND purpose = 'password_reset'
                AND expires_at > CURRENT_TIMESTAMP
                AND used = false
            )
            UPDATE managers 
            SET password_hash = %s
            WHERE email = %s 
            AND id IN (SELECT manager_id FROM valid_otp)
            RETURNING id
        """, (reset_data.otp, get_password_hash(reset_data.new_password), reset_data.email))
        
        if cur.rowcount == 0:
            raise HTTPException(status_code=400, detail="Invalid or expired OTP")
        
        # Mark OTP as used
        cur.execute("""
            UPDATE manager_otps 
            SET used = true 
            WHERE otp = %s AND purpose = 'password_reset'
        """, (reset_data.otp,))
        
        conn.commit()
        return {"message": "Password reset successfully"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Invalid or expired OTP: {e}")
    
async def verify_manager_email_otp(
    email: str,
    otp: str,
    conn = None
):
    """
    Verify a manager's email with OTP and generate JWT token
    
    Args:
        email: Manager's email address
        otp: One-time password received via email
        conn: Database connection
        
    Returns:
        Dict containing JWT token and manager details
        
    Raises:
        HTTPException: For invalid OTP or database errors
    """
    try:
        cur = conn.cursor()
        
        # Check if OTP exists and is valid
        cur.execute("""
            SELECT 
                m.id,
                m.email,
                m.full_name,
                m.role,
                mo.otp,
                mo.expires_at
            FROM managers m
            JOIN manager_otps mo ON m.id = mo.manager_id
            WHERE m.email = %s 
            AND mo.otp = %s 
            AND mo.expires_at > CURRENT_TIMESTAMP
            AND m.active = true
        """, (email, otp))
        
        verification = cur.fetchone()
        if not verification:
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired OTP"
            )
        
        # Update manager's email_verified status
        cur.execute("""
            UPDATE managers
            SET email_verified = true
            WHERE email = %s
            RETURNING id, email, full_name, role
        """, (email,))
        
        manager = cur.fetchone()
        if not manager:
            raise HTTPException(
                status_code=404,
                detail="Manager not found"
            )
        
        # Delete the used OTP
        cur.execute("""
            DELETE FROM manager_otps 
            WHERE manager_id = %s AND otp = %s
        """, (manager["id"], otp))
        
        # Create access token
        access_token_expires = timedelta(minutes=60)
        access_token = create_access_token(
            data={
                "sub": email,
                "role": manager["role"],
                "verified": True
            },
            expires_delta=access_token_expires
        )
        
        # Create notification for successful verification
        await create_notification(
            user_id=manager["id"],
            title="Email Verified",
            message="✔ Your email has been successfully verified.",
            type="success",
            cat= "account",
            conn=conn
        )
        
        conn.commit()
        
        return {
            "message": "Email verified successfully",
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": manager["id"],
                "email": manager["email"],
                "full_name": manager["full_name"],
                "role": manager["role"],
                "email_verified": True
            }
        }
        
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error verifying manager email: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error verifying email: {str(e)}"
        )

class PasswordResetWithToken(BaseModel):
    """Schema for password reset with JWT token"""
    token: str
    new_password: str

    # @validator('new_password')
    # def validate_password(cls, v):
    #     if len(v) < 8:
    #         raise ValueError('Password must be at least 8 characters long')
    #     if not any(c.isupper() for c in v):
    #         raise ValueError('Password must contain at least one uppercase letter')
    #     if not any(c.islower() for c in v):
    #         raise ValueError('Password must contain at least one lowercase letter')
    #     if not any(c.isdigit() for c in v):
    #         raise ValueError('Password must contain at least one number')
    #     return v

async def reset_password_with_token(
    reset_data: PasswordResetWithToken,
    conn = None
) -> dict:
    """
    Reset password using JWT token received after email verification
    
    Args:
        reset_data: PasswordResetWithToken model containing token and new password
        conn: Database connection
        
    Returns:
        Dict with success message
        
    Raises:
        HTTPException: For invalid token or database errors
    """
    try:
        # Verify JWT token
        try:
            payload = jwt.decode(
                reset_data.token, 
                JWT_SECRET, 
                algorithms=[JWT_ALGORITHM]
            )
            email = payload.get("sub")
            verified = payload.get("verified")
            
            if not email or not verified:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid token"
                )
                
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=401,
                detail="Token has expired"
            )
        except jwt.JWTError:
            raise HTTPException(
                status_code=401,
                detail="Could not validate token"
            )

        cur = conn.cursor()
        
        # Hash the new password
        password_hash = get_password_hash(reset_data.new_password)
        
        # Update password in database
        cur.execute("""
            UPDATE managers 
            SET password_hash = %s
            WHERE email = %s AND active = true
            RETURNING id, email, role
        """, (password_hash, email))
        
        updated_user = cur.fetchone()
        if not updated_user:
            raise HTTPException(
                status_code=404,
                detail="User not found or inactive"
            )

        # Create audit log entry
        try:
            cur.execute("""
                INSERT INTO audit_log (
                    action,
                    entity_type,
                    entity_id,
                    entity_name,
                    performed_by,
                    details
                ) VALUES (
                    'PASSWORD_RESET',
                    'MANAGER',
                    %s,
                    %s,
                    %s,
                    %s
                )
            """, (
                updated_user["id"],
                updated_user["email"],
                updated_user["id"],
                json.dumps({"method": "token_reset", "timestamp": datetime.now().isoformat()})
            ))
        except Exception as e:
            logger.error(f"Error creating audit log: {str(e)}")

        # Create notification for password reset
        await create_notification(
            user_id=updated_user["id"],
            title="Password Reset Successful",
            message="Your password has been successfully reset.",
            type="success",
            cat = "account",
            conn=conn
        )
        
        conn.commit()
        
        return {
            "message": "Password reset successfully",
            "email": updated_user["email"],
            "role": updated_user["role"]
        }
        
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error resetting password with token: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error resetting password: {str(e)}"
        )   
async def update_password(password_data: PasswordUpdate, current_user: dict, conn = None):
    """
    Update a user's password after verifying the old password.
    
    Args:
        password_data: Contains old_password and new_password
        current_user: The authenticated user whose password will be updated
        conn: Database connection
        
    Returns:
        A message indicating success
    """
    try:
        cur = conn.cursor()

        # if current_user["role"] != "Non_Operators":
        query = """
            SELECT password_hash 
            FROM managers 
            WHERE id = %s AND active = true
        """
        # else:
        #     query = """
        #     SELECT password_hash
        #     FROM users
        #     WHERE id = %s AND active = true
        # """
        
        # Get the current password hash
        cur.execute(query, (current_user["id"],))
        
        user = cur.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Verify the old password
        if not verify_password(password_data.old_password, user["password_hash"]):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        
        # Update the password
        cur.execute("""
            UPDATE managers 
            SET password_hash = %s
            WHERE id = %s
            RETURNING id
        """, (get_password_hash(password_data.new_password), current_user["id"]))
        
        conn.commit()
        return {"message": "Password updated successfully"}
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error updating password: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Restaurant Management Routes
#async def create_restaurant(
#    restaurant: RestaurantBase,
#    current_user: dict,
#    conn = None
#):
#    if current_user["role"] not in [RoleType.SUPER_ADMIN, RoleType.RESTAURANT_OWNER]:
#    # if current_user["role"] != RoleType.SUPER_ADMIN or current_user["role"] != RoleType.RESTAURANT_OWNER:
#        raise HTTPException(status_code=403, detail="Only SUPER_ADMIN and RESTAURANT_OWNER can create restaurants")
#        
#    try:
#        cur = conn.cursor()
#        
#        # Check if restaurant name exists
#        cur.execute("""
#            SELECT id FROM restaurants WHERE TRIM(name) = TRIM(%s)  """, (restaurant.name,))
#        
#        if cur.fetchone():
#            raise HTTPException(
#                status_code=400,
#                detail="Restaurant with this name already exists"
#            )
#        
#            # Check if email already exists in managers table
#        # cur.execute("SELECT id FROM managers WHERE email = %s", (owner_data.email,))
#        # if cur.fetchone():
#        #     raise HTTPException(status_code=400, detail="Email already registered")
#
#
#        # Generate unique unit_id
#        unit_id = generate_unique_unit_id(conn)
#
#        # Create new restaurant
#        cur.execute("""
#            INSERT INTO restaurants (
#                name, 
#                location, 
#                contact_number, 
#                created_by,
#                unit_id
#            )
#            VALUES (%s, %s, %s, %s, %s)
#            RETURNING 
#                id,
#                name,
#                location,
#                contact_number,
#                created_at,
#                created_by,
#                active,
#                unit_id
#        """, (
#            restaurant.name,
#            restaurant.location,
#            restaurant.contact_number,
#            current_user["id"],
#            unit_id
#        ))
#        
#        new_restaurant = cur.fetchone()
#        
#        # Get creator's email
#        cur.execute("""
#            SELECT email 
#            FROM managers 
#            WHERE id = %s
#        """, (current_user["id"],))
#        
#        creator = cur.fetchone()
#        
#        result = dict(new_restaurant)
#        result["created_by_email"] = creator["email"] if creator else None
#        
#        conn.commit()
#        from src.subscription_management import update_usage
#        resulted = await update_usage(
#        current_user=current_user,
#        conn=conn,
#        
#        used_restaurants=True,  
#    )
#
#        return {
#            "message": "Restaurant created successfully",
#            "restaurant": result
#        }
#    except HTTPException:
#        conn.rollback()
#        raise
#        
#    except Exception as e:
#        conn.rollback()
#        logger.error(f"Error creating restaurant: {str(e)}")
#        raise HTTPException(status_code=500, detail=str(e))

async def create_restaurant(
    restaurant: RestaurantBase,
    current_user: dict,
    conn = None
):
    if current_user["role"] not in [RoleType.SUPER_ADMIN, RoleType.RESTAURANT_OWNER]:
        raise HTTPException(status_code=403, detail="Only SUPER_ADMIN and RESTAURANT_OWNER can create restaurants")
        
    try:
        cur = conn.cursor()
        
        # Check if restaurant name exists
        cur.execute("""
            SELECT id FROM restaurants WHERE TRIM(name) = TRIM(%s)
        """, (restaurant.name,))
        
        if cur.fetchone():
            raise HTTPException(
                status_code=400,
                detail="Restaurant with this name already exists"
            )

        # Generate unique unit_id
        unit_id = generate_unique_unit_id(conn)

        # Create new restaurant with ALL fields from RestaurantBase
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
                unit_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                unit_id
        """, (
            restaurant.name,
            restaurant.location,
            restaurant.city,        # Added
            restaurant.state,        # Added
            restaurant.zip_code,     # Added
            restaurant.country,      # Added
            restaurant.contact_number,
            current_user["id"],
            unit_id
        ))
        
        new_restaurant = cur.fetchone()
        
        # Get creator's email
        cur.execute("""
            SELECT email 
            FROM managers 
            WHERE id = %s
        """, (current_user["id"],))
        
        creator = cur.fetchone()
        
        result = dict(new_restaurant)
        result["created_by_email"] = creator["email"] if creator else None
        
        conn.commit()
        
        # Try to update usage (with error handling)
        try:
            from src.subscription_management import update_usage
            resulted = await update_usage(
                current_user=current_user,
                conn=conn,
                used_restaurants=True,  
            )
        except Exception as usage_error:
            logger.warning(f"Failed to update usage tracking: {str(usage_error)}")
            # Don't fail the restaurant creation if usage tracking fails

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
        raise HTTPException(status_code=500, detail=f"Error creating restaurant: {str(e)}")

async def update_restaurant_unit_id(
    restaurant_id: int,
    unit_id_data: UnitIdUpdate,
    current_user: dict,
    conn = None
):
    """Update unit_id for a specific restaurant"""
    if current_user["role"] not in [RoleType.SUPER_ADMIN, RoleType.RESTAURANT_OWNER]:
        raise HTTPException(status_code=403, detail="Only SUPER_ADMIN and RESTAURANT_OWNER can update unit_id")
        
    try:
        cur = conn.cursor()
        
        # Check if restaurant exists and user has permission to modify it
        if current_user["role"] == RoleType.RESTAURANT_OWNER:
            # Restaurant owners can only update their own restaurants
            cur.execute("""
                SELECT id, name, unit_id FROM restaurants 
                WHERE id = %s AND created_by = %s AND active = true
            """, (restaurant_id, current_user["id"]))
        else:
            # SUPER_ADMIN can update any restaurant
            cur.execute("""
                SELECT id, name, unit_id FROM restaurants 
                WHERE id = %s AND active = true
            """, (restaurant_id,))
        
        restaurant = cur.fetchone()
        if not restaurant:
            raise HTTPException(
                status_code=404,
                detail="Restaurant not found or you don't have permission to modify it"
            )
        
        # Check if the new unit_id already exists (excluding current restaurant)
        cur.execute("""
            SELECT id FROM restaurants 
            WHERE unit_id = %s AND id != %s
        """, (unit_id_data.unit_id, restaurant_id))
        
        if cur.fetchone():
            raise HTTPException(
                status_code=400,
                detail="Unit ID already exists for another restaurant"
            )
        
        # Update the unit_id
        cur.execute("""
            UPDATE restaurants 
            SET unit_id = %s
            WHERE id = %s
            RETURNING id, name, unit_id
        """, (unit_id_data.unit_id, restaurant_id))
        
        updated_restaurant = cur.fetchone()
        conn.commit()
        
        return {
            "message": "Unit ID updated successfully",
            "restaurant": {
                "id": updated_restaurant["id"],
                "name": updated_restaurant["name"],
                "unit_id": updated_restaurant["unit_id"]
            }
        }
        
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error updating unit ID: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def update_restaurant(
    restaurant_id: int,
    restaurant: RestaurantUpdate,
    current_user: dict,
    conn = None
):
    """
    Update restaurant details with validation and permission checks.
    
    Args:
        restaurant_id: ID of the restaurant to update
        restaurant: RestaurantUpdate model with new details
        current_user: Current authenticated user information
        conn: Database connection object
    
    Returns:
        Dict containing updated restaurant information
    
    Raises:
        HTTPException: For validation errors, permissions, or database issues
    """
    # Permission check
    if current_user["role"] not in [RoleType.SUPER_ADMIN, RoleType.RESTAURANT_OWNER]:
        raise HTTPException(
            status_code=403,
            detail="Only SUPER_ADMIN and RESTAURANT_OWNER can update restaurants"
        )
        
    try:
        cur = conn.cursor()
        
        # Check if the restaurant exists and is active
        cur.execute("""
            SELECT 
                id,
                name,
                location,
                contact_number,
                created_by,
                active
            FROM restaurants 
            WHERE id = %s
        """, (restaurant_id,))
        
        existing_restaurant = cur.fetchone()
        if not existing_restaurant:
            raise HTTPException(
                status_code=404,
                detail="Restaurant not found"
            )
            
        if not existing_restaurant["active"]:
            raise HTTPException(
                status_code=400,
                detail="Cannot update inactive restaurant"
            )

        # Check if new name conflicts with other restaurants (if name is being changed)
        if restaurant.name != existing_restaurant["name"]:
            cur.execute("""
                SELECT id 
                FROM restaurants 
                WHERE name = %s AND id != %s
            """, (restaurant.name, restaurant_id))
            
            if cur.fetchone():
                raise HTTPException(
                    status_code=400,
                    detail="A restaurant with this name already exists"
                )

        # Update restaurant details
        cur.execute("""
            UPDATE restaurants 
            SET 
                name = %s,
                location = %s,
                contact_number = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s 
            AND active = true
            RETURNING 
                id, 
                name, 
                location, 
                contact_number, 
                created_at,
                created_by,
                active,
                updated_at
        """, (
            restaurant.name,
            restaurant.location,
            restaurant.contact_number,
            restaurant_id
        ))
            
        updated_restaurant = cur.fetchone()
        
        # Get creator's and updater's details
        cur.execute("""
            SELECT m1.email as created_by_email, m2.email as updated_by_email
            FROM restaurants r
            LEFT JOIN managers m1 ON r.created_by = m1.id
            LEFT JOIN managers m2 ON %s = m2.id
            WHERE r.id = %s
        """, (current_user["id"], restaurant_id))
        
        email_details = cur.fetchone()
        
        # Prepare response data
        result = dict(updated_restaurant)
        result.update({
            "created_by_email": email_details["created_by_email"],
            "updated_by_email": email_details["updated_by_email"],
            "updated_by_id": current_user["id"]
        })
        
        # Log the update
        logger.info(
            f"Restaurant {restaurant_id} updated by {current_user['email']} "
            f"(ID: {current_user['id']})"
        )
        
        # Commit the transaction
        conn.commit()
        
        return {
            "message": "Restaurant updated successfully",
            "restaurant": result
        }
        
    except psycopg2.Error as e:
        conn.rollback()
        logger.error(f"Database error updating restaurant: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Database error occurred while updating restaurant"
        )
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating restaurant: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while updating restaurant"
        )



# Continuing Restaurant Management Routes
async def soft_delete_restaurant(
    restaurant_id: int,
    current_user: dict,
    conn = None
):
    if current_user["role"] not in [RoleType.SUPER_ADMIN, RoleType.RESTAURANT_OWNER]:
        raise HTTPException(status_code=403, detail="Only SUPER_ADMIN and RESTAURANT_OWNER can delete restaurants")
        
    try:
        cur = conn.cursor()
        
        # Get restaurant details first
        cur.execute("""
            SELECT name 
            FROM restaurants 
            WHERE id = %s AND active = true
        """, (restaurant_id,))
        
        restaurant = cur.fetchone()
        if not restaurant:
            raise HTTPException(status_code=404, detail="Restaurant not found")

        # Soft delete the restaurant
        cur.execute("""
            UPDATE restaurants 
            SET active = false,
                deactivated_at = CURRENT_TIMESTAMP,
                deactivated_by = %s
            WHERE id = %s
            RETURNING id, name
        """, (current_user["id"], restaurant_id))
        
        deleted_restaurant = cur.fetchone()
        
        # Get affected managers
        cur.execute("""
            SELECT DISTINCT m.id, m.email, m.role
            FROM managers m
            JOIN restaurant_assignments ra ON m.id = ra.manager_id
            WHERE ra.restaurant_id = %s AND m.active = true
        """, (restaurant_id,))
        
        affected_managers = cur.fetchall()

        affected_summary = {
            "restaurant_managers": [],
            "regional_managers": []
        }

        for manager in affected_managers:
            if manager["role"] == "Restaurant Manager":
                # Check if this is their only restaurant
                cur.execute("""
                    SELECT COUNT(*) 
                    FROM restaurant_assignments ra
                    WHERE ra.manager_id = %s 
                    AND ra.restaurant_id != %s
                """, (manager["id"], restaurant_id))
                
                if cur.fetchone()["count"] == 0:
                    # Deactivate restaurant manager
                    cur.execute("""
                        UPDATE managers 
                        SET active = false 
                        WHERE id = %s
                    """, (manager["id"],))
                    affected_summary["restaurant_managers"].append(manager["email"])
            else:
                affected_summary["regional_managers"].append(manager["email"])

        # Delete restaurant assignments
        cur.execute("""
            DELETE FROM restaurant_assignments 
            WHERE restaurant_id = %s
        """, (restaurant_id,))

        conn.commit()
        return {
            "message": f"Restaurant {deleted_restaurant['name']} deleted successfully",
            "affected_managers": affected_summary
        }
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting restaurant: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
import json

import traceback
async def hard_delete_restaurant(
        restaurant_id: int,
        current_user: dict,
        conn=None
):
    """
    Permanently delete a restaurant and all associated data.
    Only SUPER_ADMIN and Restaurant Owner can perform this operation.
    """
    if current_user["role"] not in [RoleType.SUPER_ADMIN, RoleType.RESTAURANT_OWNER]:
        raise HTTPException(
            status_code=403, 
            detail="Only SUPER_ADMIN and RESTAURANT_OWNER can delete restaurants"
        )

    try:
        cur = conn.cursor()

        # First get restaurant details for the response
        cur.execute("""
            SELECT 
                r.id,
                r.name,
                r.image_url,
                r.created_by,
                array_agg(DISTINCT m.email) as affected_managers
            FROM restaurants r
            LEFT JOIN restaurant_assignments ra ON r.id = ra.restaurant_id
            LEFT JOIN managers m ON ra.manager_id = m.id
            WHERE r.id = %s
            GROUP BY r.id, r.name, r.image_url, r.created_by
        """, (restaurant_id,))

        restaurant = cur.fetchone()
        if not restaurant:
            raise HTTPException(status_code=404, detail="Restaurant not found")

        # Additional permission check for Restaurant Owner
        if current_user["role"] == RoleType.RESTAURANT_OWNER:
            if restaurant['created_by'] != current_user["id"]:
                raise HTTPException(
                    status_code=403,
                    detail="You can only delete restaurants you own"
                )

        restaurant_name = restaurant["name"]
        
        logger.info(f"🗑️ Starting hard delete for restaurant: {restaurant_name} (ID: {restaurant_id})")

        deletion_summary = {
            "restaurant_name": restaurant["name"],
            "deleted_data": {
                "s3_files": 0,
                "notifications": 0,
                "hours_of_operation": 0,
                "assignments": 0,
                "assignment_history": 0,
                "embeddings": {"openai": 0, "claude": 0},
                "sales_graphs": 0,
                "inventory_graphs": 0,
                "menu_graphs": 0,
                "employees_graphs": 0,
                "staff_info": 0,
                "affected_managers": restaurant["affected_managers"] if restaurant["affected_managers"][0] else []
            }
        }

        # ============= DELETE ALL S3 FILES =============
        try:
            # Delete restaurant files (uploads/restaurants/{restaurant_id}/)
            restaurant_folder = f"uploads/restaurants/{restaurant_id}"
            
            logger.info(f"🗑️ Deleting S3 files from: {restaurant_folder}")
            
            # Use paginator to handle large number of files
            paginator = s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=BUCKET_NAME, Prefix=f"{restaurant_folder}/")
            
            objects_to_delete = []
            for page in pages:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        objects_to_delete.append({'Key': obj['Key']})
            
            # Delete in batches of 1000 (S3 limit)
            if objects_to_delete:
                for i in range(0, len(objects_to_delete), 1000):
                    batch = objects_to_delete[i:i + 1000]
                    s3_client.delete_objects(
                        Bucket=BUCKET_NAME,
                        Delete={'Objects': batch}
                    )
                    deletion_summary["deleted_data"]["s3_files"] += len(batch)
                
                logger.info(f"✅ Deleted {deletion_summary['deleted_data']['s3_files']} files from S3")
            
            # Also delete restaurant image if exists
            if restaurant["image_url"]:
                try:
                    # Extract S3 key from URL
                    s3_key = restaurant["image_url"].split(f"{BUCKET_NAME}.s3.amazonaws.com/")[1]
                    s3_client.delete_object(Bucket=BUCKET_NAME, Key=s3_key)
                    logger.info(f"✅ Deleted restaurant image: {s3_key}")
                except Exception as e:
                    logger.error(f"❌ Error deleting restaurant image: {str(e)}")
            
        except Exception as e:
            logger.error(f"❌ Error deleting S3 files: {str(e)}")
            # Continue with database deletion even if S3 fails

        # ============= DELETE DATABASE RECORDS =============
        
        # Delete embeddings
        try:
            cur.execute("DELETE FROM openai_embeddings WHERE restaurant_name = %s", (restaurant_name,))
            deletion_summary["deleted_data"]["embeddings"]["openai"] = cur.rowcount
            
            cur.execute("DELETE FROM claude_embeddings WHERE restaurant_name = %s", (restaurant_name,))
            deletion_summary["deleted_data"]["embeddings"]["claude"] = cur.rowcount
            
            logger.info(f"✅ Deleted embeddings")
        except Exception as e:
            logger.error(f"❌ Error deleting embeddings: {str(e)}")

        # Delete sales graphs
        try:
            cur.execute("DELETE FROM sales_graphs WHERE restaurant_id = %s", (restaurant_id,))
            deletion_summary["deleted_data"]["sales_graphs"] = cur.rowcount
            logger.info(f"✅ Deleted {cur.rowcount} sales records")
        except Exception as e:
            logger.error(f"❌ Error deleting sales: {str(e)}")

        # Delete inventory graphs
        try:
            cur.execute("DELETE FROM inventory_graphs WHERE restaurant_id = %s", (restaurant_id,))
            deletion_summary["deleted_data"]["inventory_graphs"] = cur.rowcount
            logger.info(f"✅ Deleted {cur.rowcount} inventory records")
        except Exception as e:
            logger.error(f"❌ Error deleting inventory: {str(e)}")

        # Delete menu graphs
        try:
            cur.execute("DELETE FROM menu_graphs WHERE restaurant_id = %s", (restaurant_id,))
            deletion_summary["deleted_data"]["menu_graphs"] = cur.rowcount
            logger.info(f"✅ Deleted {cur.rowcount} menu records")
        except Exception as e:
            logger.error(f"❌ Error deleting menu: {str(e)}")

        # Delete employees graphs
        try:
            cur.execute("DELETE FROM employees_graphs WHERE restaurant_id = %s", (restaurant_id,))
            deletion_summary["deleted_data"]["employees_graphs"] = cur.rowcount
            logger.info(f"✅ Deleted {cur.rowcount} employee records")
        except Exception as e:
            logger.error(f"❌ Error deleting employees: {str(e)}")

        # Delete staff info
        try:
            cur.execute("DELETE FROM staff_info WHERE restaurant_id = %s", (restaurant_id,))
            deletion_summary["deleted_data"]["staff_info"] = cur.rowcount
            logger.info(f"✅ Deleted {cur.rowcount} staff info records")
        except Exception as e:
            logger.error(f"❌ Error deleting staff info: {str(e)}")

        # Delete notifications
        try:
            cur.execute("DELETE FROM notifications WHERE restaurant_id = %s", (restaurant_id,))
            deletion_summary["deleted_data"]["notifications"] = cur.rowcount
            logger.info(f"✅ Deleted {cur.rowcount} notifications")
        except Exception as e:
            logger.error(f"❌ Error deleting notifications: {str(e)}")

        # Delete hours of operation
        try:
            cur.execute("DELETE FROM hours_of_operation WHERE restaurant_id = %s", (restaurant_id,))
            deletion_summary["deleted_data"]["hours_of_operation"] = cur.rowcount
            logger.info(f"✅ Deleted {cur.rowcount} hours of operation")
        except Exception as e:
            logger.error(f"❌ Error deleting hours of operation: {str(e)}")

        # Delete assignment history
        try:
            cur.execute("DELETE FROM restaurant_assignment_history WHERE restaurant_id = %s", (restaurant_id,))
            deletion_summary["deleted_data"]["assignment_history"] = cur.rowcount
            logger.info(f"✅ Deleted {cur.rowcount} assignment history records")
        except Exception as e:
            logger.error(f"❌ Error deleting assignment history: {str(e)}")

        # Delete current assignments
        try:
            cur.execute("DELETE FROM restaurant_assignments WHERE restaurant_id = %s", (restaurant_id,))
            deletion_summary["deleted_data"]["assignments"] = cur.rowcount
            logger.info(f"✅ Deleted {cur.rowcount} assignments")
        except Exception as e:
            logger.error(f"❌ Error deleting assignments: {str(e)}")

        # Finally delete the restaurant
        try:
            cur.execute("DELETE FROM restaurants WHERE id = %s RETURNING id", (restaurant_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=500, detail="Failed to delete restaurant")
            logger.info(f"✅ Deleted restaurant record")
        except Exception as e:
            logger.error(f"❌ Error deleting restaurant: {str(e)}")
            raise

        # Create audit log
        try:
            cur.execute("""
                INSERT INTO audit_log (
                    action, entity_type, entity_id, entity_name, performed_by, details
                ) VALUES ('HARD_DELETE', 'RESTAURANT', %s, %s, %s, %s)
            """, (
                restaurant_id,
                restaurant["name"],
                current_user["id"],
                json.dumps(deletion_summary)
            ))
        except Exception as e:
            logger.error(f"❌ Error creating audit log: {str(e)}")

        conn.commit()
        logger.info(f"✅ Restaurant {restaurant_name} permanently deleted")

        return {
            "message": f"Restaurant '{restaurant['name']}' and all associated data permanently deleted",
            "deletion_summary": deletion_summary
        }

    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"❌ Error performing hard delete of restaurant: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error performing hard delete: {str(e)}"
        )


async def delete_all_restaurant_files(
    restaurant_name: str,
    current_user: dict,
    conn = None
) -> Dict[str, Any]:
    """
    Delete all files associated with a restaurant from S3
    
    Args:
        restaurant_name: Name of the restaurant
        current_user: Current authenticated user information
        conn: Database connection
        
    Returns:
        Dict containing deletion summary
    """
    try:
        from src.File_upload import list_csv_files
        # First get all files
        # Remove the conn parameter here - list_csv_files only takes 2 arguments
        files_response = await list_csv_files(restaurant_name, current_user)  # <- Fixed: removed conn
        files = files_response.get("files", [])
        
        if not files:
            logger.info(f"No files found for restaurant: {restaurant_name}")
            return {
                "message": "No files found to delete",
                "total_files": 0
            }

        # Delete files in batches of 1000 (S3 delete_objects limit)
        deletion_summary = {
            "total_files": len(files),
            "deleted_files": [],
            "failed_deletes": [],
            "deleted_size": 0
        }

        # Create batches of 10 files (you can increase to 1000 for production)
        batch_size = 10
        file_batches = [files[i:i + batch_size] for i in range(0, len(files), batch_size)]

        for batch in file_batches:
            try:
                # Prepare objects for deletion
                objects_to_delete = [{'Key': file['s3_key']} for file in batch]
                
                # Delete objects in batch
                response = s3_client.delete_objects(
                    Bucket=BUCKET_NAME,
                    Delete={
                        'Objects': objects_to_delete,
                        'Quiet': False
                    }
                )

                # Process successful deletions
                if 'Deleted' in response:
                    for deleted in response['Deleted']:
                        matching_file = next(
                            (f for f in batch if f['s3_key'] == deleted['Key']), 
                            None
                        )
                        if matching_file:
                            deletion_summary["deleted_files"].append({
                                "filename": matching_file["filename"],
                                "s3_key": matching_file["s3_key"],
                                "category": matching_file["category"],
                                "size": matching_file["size"]
                            })
                            deletion_summary["deleted_size"] += matching_file["size"]

                # Process failed deletions
                if 'Errors' in response:
                    for error in response['Errors']:
                        deletion_summary["failed_deletes"].append({
                            "key": error['Key'],
                            "error": error['Message']
                        })

            except Exception as e:
                logger.error(f"Error deleting batch of files: {str(e)}")
                deletion_summary["failed_deletes"].extend([{
                    "key": file['s3_key'],
                    "error": str(e)
                } for file in batch])

        # Log deletion summary
        logger.info(
            f"Deleted {len(deletion_summary['deleted_files'])} files "
            f"({deletion_summary['deleted_size']} bytes) for restaurant {restaurant_name}"
        )
        
        if deletion_summary["failed_deletes"]:
            logger.warning(
                f"Failed to delete {len(deletion_summary['failed_deletes'])} files "
                f"for restaurant {restaurant_name}"
            )

        return {
            "message": "Restaurant files deletion completed",
            "restaurant": restaurant_name,
            "total_files": deletion_summary["total_files"],
            "deleted_files_count": len(deletion_summary["deleted_files"]),
            "failed_deletes_count": len(deletion_summary["failed_deletes"]),
            "total_size_deleted": deletion_summary["deleted_size"],
            "failed_deletes": deletion_summary["failed_deletes"] if deletion_summary["failed_deletes"] else None
        }

    except Exception as e:
        logger.error(f"Error deleting restaurant files: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting restaurant files: {str(e)}"
        )

    
async def reactivate_restaurant(
    restaurant_id: int,
    current_user: dict,
    conn = None
):
    if current_user["role"] not in [RoleType.SUPER_ADMIN, RoleType.RESTAURANT_OWNER]:
        raise HTTPException(status_code=403, detail="Only SUPER_ADMIN can reactivate restaurants")
        
    try:
        cur = conn.cursor()
        
        # Check if restaurant exists and is inactive
        cur.execute("""
            SELECT name, deactivated_at 
            FROM restaurants 
            WHERE id = %s AND active = false
        """, (restaurant_id,))
        
        restaurant = cur.fetchone()
        if not restaurant:
            raise HTTPException(status_code=404, detail="Inactive restaurant not found")

        # Get previously associated managers
        cur.execute("""
            SELECT 
                m.id,
                m.email,
                m.role,
                m.active
            FROM managers m
            WHERE m.id IN (
                SELECT manager_id
                FROM restaurant_assignments
                WHERE restaurant_id = %s
            )
        """, (restaurant_id,))
        
        previous_managers = cur.fetchall()

        # Reactivate the restaurant
        cur.execute("""
            UPDATE restaurants 
            SET active = true,
                deactivated_at = NULL,
                deactivated_by = NULL
            WHERE id = %s
            RETURNING id, name
        """, (restaurant_id,))
        
        reactivated_restaurant = cur.fetchone()

        reactivation_summary = {
            "restaurant_name": reactivated_restaurant["name"],
            "regional_managers_restored": [],
            "restaurant_managers_restored": []
        }

        # Process each previously associated manager
        for manager in previous_managers:
            if not manager["active"]:
                if manager["role"] == "Restaurant Manager":
                    # Reactivate restaurant manager
                    cur.execute("""
                        UPDATE managers 
                        SET active = true 
                        WHERE id = %s
                        RETURNING email
                    """, (manager["id"],))
                    reactivated_manager = cur.fetchone()
                    reactivation_summary["restaurant_managers_restored"].append(
                        reactivated_manager["email"]
                    )

                # Restore restaurant assignment
                cur.execute("""
                    INSERT INTO restaurant_assignments 
                        (manager_id, restaurant_id, assigned_by)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (manager_id, restaurant_id) DO NOTHING
                """, (manager["id"], restaurant_id, current_user["id"]))

        conn.commit()
        return {
            "message": f"Restaurant {reactivated_restaurant['name']} reactivated successfully",
            "reactivation_summary": reactivation_summary
        }
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error reactivating restaurant: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
# Restaurant Listing Routes

async def get_active_restaurants(current_user: dict, conn=None):
    try:
        cur = conn.cursor()

        if current_user["role"] == RoleType.SUPER_ADMIN:
            # SUPER_ADMIN can see all active restaurants
            cur.execute("""
                SELECT 
                    r.id,
                    r.name,
                    r.location,
                    r.contact_number,
                    r.created_at,
                    r.created_by,
                    r.image_url,
                    r.store_id,
                    m.email as created_by_email,
                    r.active
                FROM restaurants r
                LEFT JOIN managers m ON r.created_by = m.id
                WHERE r.active = true
                ORDER BY r.created_at DESC
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
                    r.store_id,
                    m.email as created_by_email,
                    r.active
                FROM restaurants r
                LEFT JOIN managers m ON r.created_by = m.id
                WHERE r.created_by = %s AND r.active = true
                ORDER BY r.created_at DESC
            """, (current_user["id"],))
        else:
            # Regional and Restaurant managers can only see their assigned restaurants
            cur.execute("""
                SELECT 
                    r.id,
                    r.name,
                    r.location,
                    r.contact_number,
                    r.created_at,
                    r.created_by,
                    r.image_url,
                    r.store_id,
                    m.email as created_by_email,
                    r.active
                FROM restaurants r
                JOIN restaurant_assignments ra ON r.id = ra.restaurant_id
                LEFT JOIN managers m ON r.created_by = m.id
                WHERE ra.manager_id = %s AND r.active = true
                ORDER BY r.created_at DESC
            """, (current_user["id"],))

        restaurants = cur.fetchall()
        
        # Add restaurant_type based on store_id
        result = []
        for restaurant in restaurants:
            restaurant_dict = dict(restaurant)
            if restaurant_dict.get('store_id') is not None:
                restaurant_dict['restaurant_type'] = 'adora'
            result.append(restaurant_dict)
        
        return result
    except Exception as e:
        logger.error(f"Error fetching active restaurants: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def get_inactive_restaurants(current_user: dict, conn = None):
    if current_user["role"] not in [RoleType.SUPER_ADMIN, RoleType.RESTAURANT_OWNER]:
        raise HTTPException(status_code=403, detail="Only SUPER_ADMIN can view inactive restaurants")
        
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
            WHERE r.active = false
            ORDER BY r.deactivated_at DESC
        """)
        
        restaurants = cur.fetchall()
        return [dict(restaurant) for restaurant in restaurants]
    except Exception as e:
        logger.error(f"Error fetching inactive restaurants: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

#restaurant not assigned
async def get_unassigned_restaurants(current_user: dict, conn = None):
    """
    Get unassigned restaurants based on user role:
    - SUPER_ADMIN: sees all unassigned restaurants
    - Regional Manager: sees only their assigned restaurants that are not assigned to any Restaurant Manager
    
    Args:
        current_user: Dict containing current user information
        conn: Database connection object
        
    Returns:
        List of dictionaries containing unassigned restaurant information
    """
    if current_user["role"] not in [RoleType.SUPER_ADMIN, RoleType.REGIONAL_MANAGER, RoleType.RESTAURANT_OWNER]:
        raise HTTPException(
            status_code=403,
            detail="Only SUPER_ADMIN and Regional Managers can view unassigned restaurants"
        )

    try:
        cur = conn.cursor()
        
        base_query = """
            SELECT DISTINCT
                r.id,
                r.name,
                r.location,
                r.contact_number,
                r.created_at,
                r.created_by,
                r.image_url,
                m.email as created_by_email,
                m.full_name as created_by_name
            FROM restaurants r
            LEFT JOIN managers m ON r.created_by = m.id
            WHERE r.active = true 
        """

        if current_user["role"] == RoleType.SUPER_ADMIN:
        # if current_user["role"] in [RoleType.SUPER_ADMIN, RoleType.RESTAURANT_OWNER]:
            # SUPER_ADMIN sees all unassigned restaurants
            query = base_query + """
                AND NOT EXISTS (
                    SELECT 1 
                    FROM restaurant_assignments ra 
                    WHERE ra.restaurant_id = r.id
                )
            """
            cur.execute(query)
        elif current_user["role"] in [RoleType.RESTAURANT_OWNER]:
            # SUPER_ADMIN sees all unassigned restaurants
            query = """
                    SELECT DISTINCT
                        r.id,
                        r.name,
                        r.location,
                        r.contact_number,
                        r.created_at,
                        r.created_by,
                        r.image_url,
                        m.email as created_by_email,
                        m.full_name as created_by_name
                    FROM restaurants r
                    LEFT JOIN managers m ON r.created_by = m.id
                    WHERE r.active = true AND r.created_by = %s
                
                AND NOT EXISTS (
                    SELECT 1 
                    FROM restaurant_assignments ra 
                    WHERE ra.restaurant_id = r.id
                    
                )
            """
            cur.execute(query, (current_user["id"],))
            
        else:  # Regional Manager
            # Regional Manager sees only their assigned restaurants that haven't been assigned to Restaurant Managers
            query = base_query + """
                AND EXISTS (
                    -- Restaurant is assigned to this Regional Manager
                    SELECT 1 
                    FROM restaurant_assignments ra1 
                    WHERE ra1.restaurant_id = r.id 
                    AND ra1.manager_id = %s
                )
                AND NOT EXISTS (
                    -- Restaurant is not assigned to any Restaurant Manager
                    SELECT 1 
                    FROM restaurant_assignments ra2
                    JOIN managers m2 ON ra2.manager_id = m2.id
                    WHERE ra2.restaurant_id = r.id 
                    AND m2.role = 'Restaurant Manager'
                )
                ORDER BY r.created_at DESC
            """
            cur.execute(query, (current_user["id"],))

        restaurants = cur.fetchall()
        return [dict(restaurant) for restaurant in restaurants]
        
    except Exception as e:
        logger.error(f"Error fetching unassigned restaurants: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching unassigned restaurants: {str(e)}"
        )

async def get_unassigned_restaurants_by_role(
    current_user: dict, 
    role_type: str,
    conn = None
):
    """
    Get unassigned restaurants based on specific role type:
    - For Regional Manager role: returns restaurants with no regional manager assigned
    - For Restaurant Manager role: returns restaurants with available slots for restaurant managers
    
    Args:
        current_user: Dict containing current user information
        role_type: String specifying the role type ('Regional Manager' or 'Restaurant Manager')
        conn: Database connection object
        
    Returns:
        List of dictionaries containing unassigned restaurant information
    """
    if current_user["role"] not in [RoleType.SUPER_ADMIN, RoleType.REGIONAL_MANAGER, RoleType.RESTAURANT_OWNER]:
        raise HTTPException(
            status_code=403,
            detail="Only SUPER_ADMIN, Regional Managers, and Restaurant Owners can view unassigned restaurants"
        )

    try:
        cur = conn.cursor()
        
        # Base query for common restaurant information
        base_query = """
            SELECT DISTINCT
                r.id,
                r.name,
                r.location,
                r.contact_number,
                r.created_at,
                r.created_by,
                r.image_url,
                m.email as created_by_email,
                m.full_name as created_by_name
            FROM restaurants r
            LEFT JOIN managers m ON r.created_by = m.id
            WHERE r.active = true
        """

        if role_type not in ['Regional Manager', 'Restaurant Manager']:
            raise HTTPException(
                status_code=400,
                detail="Invalid role type. Must be either 'Regional Manager' or 'Restaurant Manager'"
            )

        if role_type == 'Regional Manager':
            # For Regional Manager role, find restaurants with no regional manager
            if current_user["role"] == RoleType.SUPER_ADMIN:
                query = base_query + """
                    AND NOT EXISTS (
                        SELECT 1 
                        FROM restaurant_assignments ra
                        JOIN managers rm ON ra.manager_id = rm.id
                        WHERE ra.restaurant_id = r.id
                        AND rm.role = 'Regional Manager'
                    )
                    ORDER BY r.created_at DESC
                """
                cur.execute(query)
            elif current_user["role"] == RoleType.RESTAURANT_OWNER:
                query = base_query + """
                    AND r.created_by = %s
                    AND NOT EXISTS (
                        SELECT 1 
                        FROM restaurant_assignments ra
                        JOIN managers rm ON ra.manager_id = rm.id
                        WHERE ra.restaurant_id = r.id
                        AND rm.role = 'Regional Manager'
                    )
                    ORDER BY r.created_at DESC
                """
                cur.execute(query, (current_user["id"],))
        else:  # Restaurant Manager role
            # For Restaurant Manager role, find restaurants that have less than 10 restaurant managers
            if current_user["role"] == RoleType.SUPER_ADMIN:
                query = base_query + """
                    AND (
                        SELECT COUNT(*)
                        FROM restaurant_assignments ra
                        JOIN managers rm ON ra.manager_id = rm.id
                        WHERE ra.restaurant_id = r.id
                        AND rm.role = 'Restaurant Manager'
                    ) < 10
                    ORDER BY r.created_at DESC
                """
                cur.execute(query)
            elif current_user["role"] == RoleType.RESTAURANT_OWNER:
                query = base_query + """
                    AND r.created_by = %s
                    AND (
                        SELECT COUNT(*)
                        FROM restaurant_assignments ra
                        JOIN managers rm ON ra.manager_id = rm.id
                        WHERE ra.restaurant_id = r.id
                        AND rm.role = 'Restaurant Manager'
                    ) < 10
                    ORDER BY r.created_at DESC
                """
                cur.execute(query, (current_user["id"],))
            elif current_user["role"] == RoleType.REGIONAL_MANAGER:
                # Regional managers can only see restaurants assigned to them
                query = base_query + """
                    AND EXISTS (
                        SELECT 1 
                        FROM restaurant_assignments ra
                        WHERE ra.restaurant_id = r.id
                        AND ra.manager_id = %s
                    )
                    AND (
                        SELECT COUNT(*)
                        FROM restaurant_assignments ra
                        JOIN managers rm ON ra.manager_id = rm.id
                        WHERE ra.restaurant_id = r.id
                        AND rm.role = 'Restaurant Manager'
                    ) < 10
                    ORDER BY r.created_at DESC
                """
                cur.execute(query, (current_user["id"],))

        restaurants = cur.fetchall()
        result = []
        
        for restaurant in restaurants:
            restaurant_dict = dict(restaurant)
            
            # Add count of current restaurant managers
            if role_type == 'Restaurant Manager':
                cur.execute("""
                    SELECT COUNT(*) as manager_count
                    FROM restaurant_assignments ra
                    JOIN managers rm ON ra.manager_id = rm.id
                    WHERE ra.restaurant_id = %s
                    AND rm.role = 'Restaurant Manager'
                """, (restaurant["id"],))
                manager_count = cur.fetchone()["manager_count"]
                restaurant_dict["current_manager_count"] = manager_count
                restaurant_dict["available_slots"] = 10 - manager_count
            
            result.append(restaurant_dict)
            
        return result
        
    except Exception as e:
        logger.error(f"Error fetching unassigned restaurants by role: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching unassigned restaurants: {str(e)}"
        )

# API endpoint for unassigned restaurants by role


# Manager Management Routes
async def get_regional_managers(current_user: dict, conn = None):
    if current_user["role"] not in [RoleType.SUPER_ADMIN, RoleType.RESTAURANT_OWNER]:
        raise HTTPException(status_code=403, detail="Only SUPER_ADMIN, RESTAURANT_OWNER can view regional managers list")
        
    try:
        cur = conn.cursor()
        
        if current_user["role"] == RoleType.RESTAURANT_OWNER:
            query = """
            SELECT 
                m.id,
                m.email,
                m.full_name,
                m.phone_number,
                m.created_at,
                array_agg(DISTINCT r.name) as assigned_restaurants
            FROM managers m
            LEFT JOIN restaurant_assignments ra ON m.id = ra.manager_id
            LEFT JOIN restaurants r ON ra.restaurant_id = r.id
            WHERE m.role = 'Regional Manager' AND r.created_by = %s
            AND m.active = true
            GROUP BY m.id, m.email, m.full_name, m.phone_number, m.created_at
            ORDER BY m.created_at DESC
        """
            cur.execute(query, (current_user["id"],))
        else:
            query = """
            SELECT 
                m.id,
                m.email,
                m.full_name,
                m.phone_number,
                m.created_at,
                array_agg(DISTINCT r.name) as assigned_restaurants
            FROM managers m
            LEFT JOIN restaurant_assignments ra ON m.id = ra.manager_id
            LEFT JOIN restaurants r ON ra.restaurant_id = r.id
            WHERE m.role = 'Regional Manager' 
            AND m.active = true
            GROUP BY m.id, m.email, m.full_name, m.phone_number, m.created_at
            ORDER BY m.created_at DESC
        """
            cur.execute(query)
        
        regional_managers = cur.fetchall()
        return [dict(manager) for manager in regional_managers]
    except Exception as e:
        logger.error(f"Error fetching regional managers: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def get_restaurant_managers(current_user: dict, conn = None):
    if current_user["role"] not in [RoleType.SUPER_ADMIN, RoleType.REGIONAL_MANAGER]:
        raise HTTPException(status_code=403, detail="Not authorized to view restaurant managers")
        
    try:
        cur = conn.cursor()
        
        if current_user["role"] == RoleType.SUPER_ADMIN:
            cur.execute("""
                SELECT 
                    m.id,
                    m.email,
                    m.full_name,
                    m.phone_number,
                    m.created_at,
                    m2.email as regional_manager_email,
                    array_agg(DISTINCT r.name) as assigned_restaurants
                FROM managers m
                LEFT JOIN managers m2 ON m.regional_manager_id = m2.id
                LEFT JOIN restaurant_assignments ra ON m.id = ra.manager_id
                LEFT JOIN restaurants r ON ra.restaurant_id = r.id
                WHERE m.role = 'Restaurant Manager' 
                AND m.active = true
                GROUP BY m.id, m.email, m.full_name, m.phone_number, m.created_at, m2.email
                ORDER BY m.created_at DESC
            """)
        else:
            # Regional managers can only see their restaurant managers
            cur.execute("""
                SELECT 
                    m.id,
                    m.email,
                    m.full_name,
                    m.phone_number,
                    m.created_at,
                    array_agg(DISTINCT r.name) as assigned_restaurants
                FROM managers m
                LEFT JOIN restaurant_assignments ra ON m.id = ra.manager_id
                LEFT JOIN restaurants r ON ra.restaurant_id = r.id
                WHERE m.role = 'Restaurant Manager' 
                AND m.regional_manager_id = %s
                AND m.active = true
                GROUP BY m.id, m.email, m.full_name, m.phone_number, m.created_at
                ORDER BY m.created_at DESC
            """, (current_user["id"],))
        
        restaurant_managers = cur.fetchall()
        return [dict(manager) for manager in restaurant_managers]
    except Exception as e:
        logger.error(f"Error fetching restaurant managers: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

#async def get_managers(current_user: dict, conn = None):
#    """
#    Get list of managers based on user role and permissions.
#    """
#    if current_user["role"] not in [RoleType.SUPER_ADMIN, RoleType.REGIONAL_MANAGER]:
#        raise HTTPException(status_code=403, detail="Not authorized to view managers list")
#        
#    try:
#        cur = conn.cursor()
#        
#        if current_user["role"] == RoleType.SUPER_ADMIN:
#            # SUPER_ADMIN can see all managers
#            cur.execute("""
#                SELECT 
#                    m.id,
#                    m.email,
#                    m.role,
#                    m.full_name,
#                    m.phone_number,
#                    m.created_at,
#                    m.active,
#                    m2.email as regional_manager_email,
#                    array_agg(DISTINCT r.name) as assigned_restaurants
#                FROM managers m
#                LEFT JOIN managers m2 ON m.regional_manager_id = m2.id
#                LEFT JOIN restaurant_assignments ra ON m.id = ra.manager_id
#                LEFT JOIN restaurants r ON ra.restaurant_id = r.id AND r.active = true
#                GROUP BY 
#                    m.id, 
#                    m.email, 
#                    m.role,
#                    m.full_name,
#                    m.phone_number,
#                    m.created_at,
#                    m.active,
#                    m2.email
#                ORDER BY m.created_at DESC
#            """)
#        else:
#            # Regional managers can see managers they created OR managers assigned to them
#            cur.execute("""
#                SELECT 
#                    m.id,
#                    m.email,
#                    m.role,
#                    m.full_name,
#                    m.phone_number,
#                    m.created_at,
#                    m.active,
#                    m2.email as regional_manager_email,
#                    array_agg(DISTINCT r.name) as assigned_restaurants
#                FROM managers m
#                LEFT JOIN managers m2 ON m.regional_manager_id = m2.id
#                LEFT JOIN restaurant_assignments ra ON m.id = ra.manager_id
#                LEFT JOIN restaurants r ON ra.restaurant_id = r.id AND r.active = true
#                WHERE (m.created_by = %s OR m.regional_manager_id = %s)
#                  AND m.role = 'Restaurant Manager'
#                  AND m.active = true
#                GROUP BY 
#                    m.id, 
#                    m.email, 
#                    m.role,
#                    m.full_name,
#                    m.phone_number,
#                    m.created_at,
#                    m.active,
#                    m2.email
#                ORDER BY m.created_at DESC
#            """, (current_user["id"], current_user["id"]))
#        
#        managers = cur.fetchall()
#        return [dict(manager) for manager in managers]
#    except Exception as e:
#        logger.error(f"Error fetching managers: {str(e)}")
#        raise HTTPException(status_code=500, detail=str(e))

async def get_managers(current_user: dict, conn = None):
    """
    Get list of managers with complete S3 image URLs for profile images
    """
    if current_user["role"] not in [RoleType.SUPER_ADMIN, RoleType.REGIONAL_MANAGER, RoleType.RESTAURANT_OWNER]:
        raise HTTPException(status_code=403, detail="Not authorized to view managers list")
        
    try:
        cur = conn.cursor()
        
        if current_user["role"] == RoleType.SUPER_ADMIN:
            # SUPER_ADMIN can see all managers
            cur.execute("""
                SELECT 
                    DISTINCT ON (m.id) m.id,
                    m.email,
                    m.role,
                    m.full_name,
                    m.phone_number,
                    m.created_at,
                    m.active,
                    m.profile_image,
                    m2.email as regional_manager_email,
                    COALESCE(array_agg(r.name) FILTER (WHERE r.name IS NOT NULL), ARRAY[]::varchar[]) as assigned_restaurants
                FROM managers m
                LEFT JOIN managers m2 ON m.regional_manager_id = m2.id
                LEFT JOIN restaurant_assignments ra ON m.id = ra.manager_id
                LEFT JOIN restaurants r ON ra.restaurant_id = r.id AND r.active = true
                GROUP BY 
                    m.id, 
                    m.email, 
                    m.role,
                    m.full_name,
                    m.phone_number,
                    m.created_at,
                    m.active,
                    m.profile_image,
                    m2.email
                ORDER BY m.id, m.created_at DESC
            """)
        elif current_user["role"] == RoleType.RESTAURANT_OWNER:
            # SUPER_ADMIN can see all managers
            cur.execute("""
                SELECT 
                    DISTINCT ON (m.id) m.id,
                    m.email,
                    m.role,
                    m.full_name,
                    m.phone_number,
                    m.created_at,
                    m.active,
                    m.profile_image,
                    m2.email as regional_manager_email,
                    COALESCE(array_agg(r.name) FILTER (WHERE r.name IS NOT NULL), ARRAY[]::varchar[]) as assigned_restaurants
                FROM managers m
                LEFT JOIN managers m2 ON m.regional_manager_id = m2.id
                LEFT JOIN restaurant_assignments ra ON m.id = ra.manager_id
                LEFT JOIN restaurants r ON ra.restaurant_id = r.id AND r.active = true
                WHERE r.created_by = %s
                GROUP BY 
                    m.id, 
                    m.email, 
                    m.role,
                    m.full_name,
                    m.phone_number,
                    m.created_at,
                    m.active,
                    m.profile_image,
                    m2.email
                ORDER BY m.id, m.created_at DESC
            """, (current_user["id"],))
        else:
            # Regional managers see only their restaurant managers
            cur.execute("""
                SELECT 
                    DISTINCT ON (m.id) m.id,
                    m.email,
                    m.role,
                    m.full_name,
                    m.phone_number,
                    m.created_at,
                    m.active,
                    m.profile_image,
                    m2.email as regional_manager_email,
                    COALESCE(array_agg(r.name) FILTER (WHERE r.name IS NOT NULL), ARRAY[]::varchar[]) as assigned_restaurants
                FROM managers m
                LEFT JOIN managers m2 ON m.regional_manager_id = m2.id
                LEFT JOIN restaurant_assignments ra ON m.id = ra.manager_id
                LEFT JOIN restaurants r ON ra.restaurant_id = r.id AND r.active = true
                WHERE (m.created_by = %s OR m.regional_manager_id = %s)
                  AND m.role = 'Restaurant Manager'
                  AND m.active = true
                GROUP BY 
                    m.id, 
                    m.email, 
                    m.role,
                    m.full_name,
                    m.phone_number,
                    m.created_at,
                    m.active,
                    m.profile_image,
                    m2.email
                ORDER BY m.id, m.created_at DESC
            """, (current_user["id"], current_user["id"]))

        managers = cur.fetchall()
        
        # Add S3 URLs for profile images
        managers_with_urls = []
        for manager in managers:
            try:
                manager_dict = dict(manager)
                if manager_dict.get("profile_image"):  # Use get() to safely check for profile_image
                    user_folder = f"user_{manager_dict['id']}"
                    s3_key = f"uploads/profile_images/{user_folder}/{manager_dict['profile_image']}"
                    manager_dict["image_url"] = f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}"
                else:
                    manager_dict["image_url"] = None
                managers_with_urls.append(manager_dict)
            except Exception as e:
                logger.error(f"Error processing manager {manager.get('id', 'unknown')}: {str(e)}")
                # Continue processing other managers even if one fails
                continue
            
        return managers_with_urls
        
    except Exception as e:
        logger.error(f"Error fetching managers: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
import time
async def update_manager(
    manager_id: int,
    full_name: Optional[str] = None,
    phone_number: Optional[str] = None,
    profile_image: Optional[UploadFile] = None,
    image_url: Optional[str] = None,
    current_user: dict = None,
    conn = None
) -> dict:
    """
    Update manager information including profile image
    """
    if current_user["role"] not in [RoleType.SUPER_ADMIN, RoleType.REGIONAL_MANAGER, RoleType.RESTAURANT_OWNER]:
        raise HTTPException(status_code=403, detail="Not authorized to update manager information")

    try:
        cur = conn.cursor()
        
        # Check if manager exists and validate permissions
        cur.execute("""
            SELECT id, email, role, regional_manager_id, profile_image
            FROM managers 
            WHERE id = %s AND active = true
        """, (manager_id,))
        
        manager = cur.fetchone()
        if not manager:
            raise HTTPException(status_code=404, detail="Manager not found")
            
        # Regional managers can only update their own restaurant managers
        if current_user["role"] == RoleType.REGIONAL_MANAGER:
            if manager["role"] != RoleType.RESTAURANT_MANAGER or manager["regional_manager_id"] != current_user["id"]:
                raise HTTPException(status_code=403, detail="Not authorized to update this manager")

        update_fields = []
        update_values = []
        
        if full_name is not None:
            update_fields.append("full_name = %s")
            update_values.append(full_name)
            
        if phone_number is not None:
            update_fields.append("phone_number = %s")
            update_values.append(phone_number)

        # Handle profile image upload if provided
        if profile_image:
            try:
                # Create unique filename
                file_extension = profile_image.filename.split('.')[-1]
                new_filename = f"profile_{int(time.time())}.{file_extension}"
                
                # Create S3 key
                user_folder = f"user_{manager_id}"
                s3_key = f"uploads/profile_images/{user_folder}/{new_filename}"
                
                # Upload to S3
                await profile_image.seek(0)
                s3_client.upload_fileobj(
                    profile_image.file,
                    BUCKET_NAME,
                    s3_key,
                    ExtraArgs={'ContentType': profile_image.content_type}
                )
                
                # Add profile image to update fields
                update_fields.append("profile_image = %s")
                update_values.append(new_filename)
                
            except Exception as e:
                logger.error(f"Error uploading profile image: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail="Error uploading profile image"
                )
                
        elif image_url:
            update_fields.append("profile_image = %s")
            update_values.append(image_url)
        else:
            update_fields.append("profile_image = %s")
            update_values.append(None)
            
        

        if not update_fields:
            raise HTTPException(status_code=400, detail="No fields to update")
            
        # Add manager_id to values
        update_values.append(manager_id)
        
        # Construct and execute update query
        query = f"""
            UPDATE managers 
            SET {", ".join(update_fields)}
            WHERE id = %s
            RETURNING id, email, role, full_name, phone_number, profile_image, created_at
        """
        
        cur.execute(query, update_values)
        updated_manager = cur.fetchone()
        
        # Add S3 URL for profile image if exists
        manager_dict = dict(updated_manager)
        if manager_dict.get("profile_image"):
            user_folder = f"user_{manager_dict['id']}"
            s3_key = f"uploads/profile_images/{user_folder}/{manager_dict['profile_image']}"
            manager_dict["image_url"] = f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}"
        else:
            manager_dict["image_url"] = None
            
        # if not profile_image:
        #     manager_dict["image_url"] = None
            
        conn.commit()
        return manager_dict
        
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating manager: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



async def delete_manager(manager_id: int, current_user: dict, conn=None):
    """
    Delete a manager (Restaurant Manager or Regional Manager) and all related data
    """
    if current_user["role"] not in [RoleType.SUPER_ADMIN, RoleType.REGIONAL_MANAGER, RoleType.RESTAURANT_OWNER]:
        raise HTTPException(status_code=403, detail="Not authorized to delete managers")

    try:
        cur = conn.cursor()

        # Get manager details first
        cur.execute("""
            SELECT 
                id,
                email,
                role,
                full_name,
                regional_manager_id,
                active
            FROM managers 
            WHERE id = %s
        """, (manager_id,))

        manager = cur.fetchone()
        if not manager:
            raise HTTPException(status_code=404, detail="Manager not found")

        manager_role = manager["role"]
        manager_email = manager["email"]
        manager_name = manager["full_name"] or manager["email"]

        # Check permissions based on who is deleting whom
        if current_user["role"] == RoleType.REGIONAL_MANAGER:
            # Regional managers can only delete their own restaurant managers
            if manager_role != "Restaurant Manager" or manager["regional_manager_id"] != current_user["id"]:
                raise HTTPException(
                    status_code=403,
                    detail="Regional Managers can only delete their own Restaurant Managers"
                )

        # Get information about what will be affected
        affected_data = {
            "manager_role": manager_role,
            "manager_email": manager_email,
            "assigned_restaurants": [],
            "subordinate_managers": []
        }

        # Get assigned restaurants
        cur.execute("""
            SELECT r.id, r.name
            FROM restaurants r
            JOIN restaurant_assignments ra ON r.id = ra.restaurant_id
            WHERE ra.manager_id = %s
        """, (manager_id,))
        affected_data["assigned_restaurants"] = [{"id": row["id"], "name": row["name"]} for row in cur.fetchall()]

        # If deleting a Regional Manager, get their Restaurant Managers
        if manager_role == "Regional Manager":
            cur.execute("""
                SELECT id, email, full_name
                FROM managers
                WHERE regional_manager_id = %s AND active = true
            """, (manager_id,))
            affected_data["subordinate_managers"] = [
                {"id": row["id"], "email": row["email"], "name": row["full_name"] or row["email"]} 
                for row in cur.fetchall()
            ]

        # Start deletion process
        logger.info(f"Starting deletion of {manager_role}: {manager_email} (ID: {manager_id})")

        # Handle Regional Manager specific deletions
        if manager_role == "Regional Manager":
            # First handle subordinate Restaurant Managers
            if affected_data["subordinate_managers"]:
                if current_user["role"] == RoleType.SUPER_ADMIN:
                    # Option 1: Delete all subordinate managers (cascade)
                    for subordinate in affected_data["subordinate_managers"]:
                        # Recursively delete each restaurant manager
                        await delete_manager(subordinate["id"], current_user, conn)
                else:
                    # Option 2: Orphan the restaurant managers (set regional_manager_id to NULL)
                    cur.execute("""
                        UPDATE managers 
                        SET regional_manager_id = NULL 
                        WHERE regional_manager_id = %s
                    """, (manager_id,))
                    logger.info(f"Orphaned {len(affected_data['subordinate_managers'])} Restaurant Managers")

        # Delete all related data in correct order (same for both Regional and Restaurant Managers)
        
        # 1. Delete from restaurant_kpi_graphs
        cur.execute("DELETE FROM restaurant_kpi_graphs WHERE created_by = %s", (manager_id,))
        
        # 2. Delete manager's OTPs
        cur.execute("DELETE FROM manager_otps WHERE manager_id = %s", (manager_id,))
        
        # 3. Delete restaurant assignments
        cur.execute("DELETE FROM restaurant_assignments WHERE manager_id = %s", (manager_id,))
        
        # 4. Delete from restaurant_assignment_history
        cur.execute("""
            DELETE FROM restaurant_assignment_history 
            WHERE manager_id = %s OR assigned_by = %s OR unassigned_by = %s
        """, (manager_id, manager_id, manager_id))
        
        # 5. Delete notifications
        cur.execute("DELETE FROM notifications WHERE user_id = %s", (manager_id,))
        
        # 6. Delete user notification settings
        cur.execute("DELETE FROM user_notification_settings WHERE user_id = %s", (manager_id,))
        
        # 7. Delete chat history
        cur.execute("DELETE FROM chat_history_claude WHERE user_id = %s", (manager_id,))
        cur.execute("DELETE FROM chat_history_openai WHERE user_id = %s", (manager_id,))
        
        # 8. Delete embeddings
        cur.execute("DELETE FROM openai_embeddings WHERE user_id = %s", (manager_id,))
        cur.execute("DELETE FROM claude_embeddings WHERE user_id = %s", (manager_id,))
        
        # 9. Update restaurants - set NULL for created_by and deactivated_by
        cur.execute("UPDATE restaurants SET created_by = NULL WHERE created_by = %s", (manager_id,))
        cur.execute("UPDATE restaurants SET deactivated_by = NULL WHERE deactivated_by = %s", (manager_id,))
        
        # 10. Update other managers
        cur.execute("UPDATE managers SET created_by = NULL WHERE created_by = %s", (manager_id,))
        
        # 11. Delete audit log entries
        cur.execute("DELETE FROM audit_log WHERE performed_by = %s", (manager_id,))
        
        # 12. Delete manager invitations
        cur.execute("""
            DELETE FROM manager_invitations 
            WHERE created_by = %s OR 
                  (regional_manager_id = %s AND %s = 'Regional Manager')
        """, (manager_id, manager_id, manager_role))
        
        # 13. Finally delete the manager
        cur.execute("DELETE FROM managers WHERE id = %s RETURNING email, full_name", (manager_id,))
        deleted_manager = cur.fetchone()

        if not deleted_manager:
            raise HTTPException(status_code=404, detail="Manager not found during deletion")

        conn.commit()
        
        # Prepare response message
        response_message = f"{manager_role} {manager_name} permanently deleted"
        
        response = {
            "message": response_message,
            "deleted_manager": {
                "id": manager_id,
                "email": manager_email,
                "role": manager_role,
                "name": manager_name
            },
            "affected_restaurants": affected_data["assigned_restaurants"],
            "details": "All related history and assignments have been removed"
        }
        
        # Add subordinate managers info if it was a Regional Manager
        if manager_role == "Regional Manager" and affected_data["subordinate_managers"]:
            if current_user["role"] == RoleType.SUPER_ADMIN:
                response["subordinate_managers_deleted"] = affected_data["subordinate_managers"]
            else:
                response["subordinate_managers_orphaned"] = affected_data["subordinate_managers"]
        
        logger.info(f"Successfully deleted {manager_role}: {manager_email}")
        return response

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting manager: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting manager: {str(e)}")


async def upload_profile_image(file: UploadFile, current_user: dict, conn) -> dict:
    """
    Upload and save user profile image, replacing any existing image
    """
    try:
        # Validate file type
        if not file.content_type.startswith('image/'):
            raise HTTPException(
                status_code=400,
                detail="File must be an image"
            )
        
        # Base directory for all profile images
        PROFILE_IMAGES_DIR = "uploads/profile_images"
        
        # Create user-specific folder name
        user_folder_name = f"user_{current_user['id']}"
        user_folder_path = os.path.join(PROFILE_IMAGES_DIR, user_folder_name)
        
        # Create directories if they don't exist
        os.makedirs(user_folder_path, exist_ok=True)
        
        # Get current profile image if exists
        cur = conn.cursor()
        cur.execute("""
            SELECT profile_image 
            FROM managers 
            WHERE id = %s
        """, (current_user["id"],))
        result = cur.fetchone()
        
        # Delete old profile image if it exists
        if result and result["profile_image"]:
            old_image_path = os.path.join(user_folder_path, result["profile_image"])
            try:
                if os.path.exists(old_image_path):
                    os.remove(old_image_path)
                    logger.info(f"Deleted old profile image: {old_image_path}")
            except Exception as e:
                logger.error(f"Error deleting old profile image: {str(e)}")

        # Generate new filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_extension = os.path.splitext(file.filename)[1].lower()
        new_filename = f"profile_{timestamp}{file_extension}"
        file_path = os.path.join(user_folder_path, new_filename)
        
        # Save new file
        try:
            async with aiofiles.open(file_path, 'wb') as f:
                content = await file.read()
                await f.write(content)
            logger.info(f"Saved new profile image: {file_path}")
        except Exception as e:
            logger.error(f"Error saving new file: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Error saving file"
            )
        
        # Update database with new image path (removed updated_at)
        cur.execute("""
            UPDATE managers 
            SET profile_image = %s
            WHERE id = %s
            RETURNING id, email, profile_image
        """, (new_filename, current_user["id"]))
        
        updated_user = cur.fetchone()
        if not updated_user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )
            
        conn.commit()
        
        return {
            "message": "Profile image updated successfully",
            "file_path": f"/profile_images/{user_folder_name}/{new_filename}",
            "user_id": current_user["id"],
            "email": updated_user["email"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error uploading profile image: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error uploading profile image: {str(e)}"
        )

async def get_current_profile(current_user: dict, conn = None):
    """
    Get current user's profile details.
    
    Args:
        current_user: Dict containing current user information
        conn: Database connection object
        
    Returns:
        Dict with user profile information
    """

    try:
        cur = conn.cursor()

        # if current_user["role"] != "Non_Operators":
        cur.execute("""
                SELECT 
                    id,
                    email,
                    role,
                    full_name,
                    phone_number,
                    address,
                    profile_image,
                    created_at
                FROM managers 
                WHERE id = %s AND active = true
            """, (current_user["id"],))
            
        profile = cur.fetchone()

        # else:
        #     cur.execute("""
        #         SELECT 
        #             id,
        #             email,
        #             role,
        #             full_name,
        #             phone_number,
        #             address,
        #             profile_image,
        #             created_at
        #         FROM users 
        #         WHERE id = %s AND active = true
        #     """, (current_user["id"],))
            
        # profile = cur.  fetchone()


        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
            
            
        profile_dict= dict(profile)
        if profile_dict["profile_image"]:
            user_folder= f"user_{current_user['id']}"
            s3_key=f"uploads/profile_images/{user_folder}/{profile_dict['profile_image']}"
            profile_dict["image_url"]=f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}"

        return profile_dict
    except Exception as e:
        logger.error(f"Error fetching profile: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



import boto3
BUCKET_NAME = "my-audio-demo"
UPLOAD_BASE_DIR = "uploads/users"

# Add to chat_gpt.py
s3_client = boto3.client(
    's3',
    region_name='us-east-1',
    aws_access_key_id='AKIA6G75DKGI46PCJQHL',
    aws_secret_access_key='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'
)


async def update_current_profile(profile: ProfileUpdate, current_user: dict, conn = None):
    """
    Update current user's profile.
    
    Args:
        profile: ProfileUpdate model with new details
        current_user: Dict containing current user information
        conn: Database connection object
        
    Returns:
        Dict with updated profile information
    """
    try:
        cur = conn.cursor()
        
        update_fields = []
        update_values = []
        
        if profile.full_name is not None:
            update_fields.append("full_name = %s")
            update_values.append(profile.full_name)
        
        if profile.phone_number is not None:
            update_fields.append("phone_number = %s")
            update_values.append(profile.phone_number)
        
        if profile.address is not None:
            update_fields.append("address = %s")
            update_values.append(profile.address)
        
        if not update_fields:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        # Add user ID to values
        update_values.append(current_user["id"])

        # if current_user["role"] != "Non_Operators":
        
        query = f"""
                UPDATE managers 
                SET {", ".join(update_fields)}
                WHERE id = %s AND active = true
                RETURNING 
                    id,
                    email,
                    role,
                    full_name,
                    phone_number,
                    address,
                    profile_image
            """
        # else:
        #     query = f"""
        #         UPDATE users 
        #         SET {", ".join(update_fields)}
        #         WHERE id = %s AND active = true
        #         RETURNING 
        #             id,
        #             email,
        #             role,
        #             full_name,
        #             phone_number,
        #             address,
        #             profile_image
        #     """
        
        cur.execute(query, update_values)
        updated_profile = cur.fetchone()
        
        if not updated_profile:
            raise HTTPException(status_code=404, detail="Profile not found")
            
        conn.commit()
        return dict(updated_profile)
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating profile: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


#async def get_current_user_profile_image(current_user: dict, conn) -> dict:
#    """
#    Get current user's profile image
#    """
#    try:
#        # Query database for profile image path
#        cur = conn.cursor()
#        cur.execute("""
#            SELECT id, email, profile_image
#            FROM managers 
#            WHERE id = %s AND active = true
#        """, (current_user["id"],))
#        
#        user = cur.fetchone()
#        if not user or not user["profile_image"]:
#            raise HTTPException(status_code=404, detail="No profile image found")
#            
#        # Construct file path
#        user_folder = f"user_{current_user['id']}"
#        folder_path = os.path.join("uploads/profile_images", user_folder)
#        image_path = os.path.join(folder_path, user["profile_image"])
#        
#        # Verify file exists
#        if not os.path.exists(image_path):
#            raise HTTPException(status_code=404, detail="Profile image file not found")
#            
#        return {
#            "image_path": image_path,
#            "filename": user["profile_image"]
#        }
#        
#    except HTTPException:
#        raise
#    except Exception as e:
#        logger.error(f"Error retrieving profile image: {str(e)}")
#        raise HTTPException(
#            status_code=500,
#            detail=f"Error retrieving profile image: {str(e)}"
#        )
#
## Profile Management Routes
#async def update_profile(current_user: dict, profile_update: ProfileUpdate, conn = None):
#    try:
#        cur = conn.cursor()
#        
#        update_fields = []
#        update_values = []
#        
#        if profile_update.full_name is not None:
#            update_fields.append("full_name = %s")
#            update_values.append(profile_update.full_name)
#        
#        if profile_update.phone_number is not None:
#            update_fields.append("phone_number = %s")
#            update_values.append(profile_update.phone_number)
#        
#        if profile_update.address is not None:
#            update_fields.append("address = %s")
#            update_values.append(profile_update.address)
#        
#        if not update_fields:
#            raise HTTPException(status_code=400, detail="No fields to update")
#        
#        # Add user ID to values
#        update_values.append(current_user["id"])
#        
#        query = f"""
#            UPDATE managers 
#            SET {", ".join(update_fields)}
#            WHERE id = %s
#            RETURNING id, email, role, full_name, phone_number, address
#        """
#        
#        cur.execute(query, update_values)
#        updated_profile = cur.fetchone()
#        
#        conn.commit()
#        return dict(updated_profile)
#    except Exception as e:
#        conn.rollback()
#        logger.error(f"Error updating profile: {str(e)}")
#        raise HTTPException(status_code=500, detail=str(e))

async def upload_profile_image(file: UploadFile, current_user: dict, conn) -> dict:
    """
    Upload and save user profile image to S3, replacing any existing image
    """
    try:
        # Validate file type
        if not file.content_type.startswith('image/'):
            raise HTTPException(
                status_code=400,
                detail="File must be an image"
            )

        # Create S3 path structure
        user_folder = f"user_{current_user['id']}"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_extension = os.path.splitext(file.filename)[1].lower()
        new_filename = f"profile_{timestamp}{file_extension}"
        s3_key = f"uploads/profile_images/{user_folder}/{new_filename}"

        # Get current profile image if exists
        cur = conn.cursor()
        # if current_user["role"] != "Non_Operators":
        query = """
            SELECT profile_image 
            FROM managers 
            WHERE id = %s
        """
        # else:
        #     query = """
        #     SELECT profile_image
        #     FROM users
        #     WHERE id = %s
        # """
        cur.execute(query, (current_user["id"],))
        result = cur.fetchone()

        # Delete old image from S3 if it exists
        if result and result["profile_image"]:
            try:
                old_key = f"uploads/profile_images/{user_folder}/{result['profile_image']}"
                logger.info(f"Deleting old image: {old_key}")
                s3_client.delete_object(
                    Bucket=BUCKET_NAME,
                    Key=old_key
                )
            except Exception as e:
                logger.error(f"Error deleting old image from S3: {str(e)}")

        # Upload new image to S3
        try:
            content = await file.read()
            s3_client.put_object(
                Bucket=BUCKET_NAME,
                Key=s3_key,
                Body=content,
                ContentType=file.content_type,
               # ACL='public-read'  # Make the image publicly accessible
            )

            # Generate the S3 URL
            image_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}"

            # Update database with new image information
            cur.execute("""
                UPDATE managers 
                SET profile_image = %s
                WHERE id = %s
                RETURNING id, email, profile_image
            """, (new_filename, current_user["id"]))

            updated_user = cur.fetchone()
            if not updated_user:
                raise HTTPException(
                    status_code=404,
                    detail="User not found"
                )

            conn.commit()

            return {
                "message": "Profile image updated successfully",
                "image_url": image_url,
                "user_id": current_user["id"],
                "email": updated_user["email"]
            }

        except Exception as e:
            logger.error(f"Error uploading to S3: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error uploading image to S3: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error uploading profile image: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error uploading profile image: {str(e)}"
        )

async def get_current_user_profile_image(current_user: dict, conn) -> dict:
    """
    Get current user's profile image from S3
    """
    try:
        # Query database for profile image information
        cur = conn.cursor()
        # if current_user["role"] != "Non_Operators":
        query = """
            SELECT id, email, profile_image
            FROM managers
            WHERE id = %s AND active = true
        """
        # else:
        #     query = """
        #     SELECT id, email, profile_image
        #     FROM users
        #     WHERE id = %s AND active = true
        # """
        cur.execute(query, (current_user["id"],))
        
        user = cur.fetchone()
        if not user or not user["profile_image"]:
            raise HTTPException(status_code=404, detail="No profile image found")
            
        # Construct S3 path
        user_folder = f"user_{current_user['id']}"
        s3_key = f"uploads/profile_images/{user_folder}/{user['profile_image']}"
        
        try:
            # Check if file exists in S3
            s3_client.head_object(
                Bucket=BUCKET_NAME,
                Key=s3_key
            )
            
            # Generate presigned URL for temporary access
            url = s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': BUCKET_NAME,
                    'Key': s3_key
                },
                ExpiresIn=3600  # URL expires in 1 hour
            )
            
            return {
                "image_url": url,
                "filename": user["profile_image"],
                "s3_key": s3_key
            }
            
        except s3_client.exceptions.NoSuchKey:
            raise HTTPException(status_code=404, detail="Profile image file not found in S3")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving profile image: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving profile image: {str(e)}"
        )

async def update_profile(current_user: dict, profile_update: ProfileUpdate, conn = None):
    """
    Update user profile information
    """
    try:
        cur = conn.cursor()
        
        update_fields = []
        update_values = []
        
        if profile_update.full_name is not None:
            update_fields.append("full_name = %s")
            update_values.append(profile_update.full_name)
        
        if profile_update.phone_number is not None:
            update_fields.append("phone_number = %s")
            update_values.append(profile_update.phone_number)
        
        if profile_update.address is not None:
            update_fields.append("address = %s")
            update_values.append(profile_update.address)
        
        if not update_fields:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        # Add user ID to values
        update_values.append(current_user["id"])
        
        query = f"""
            UPDATE managers 
            SET {", ".join(update_fields)}
            WHERE id = %s
            RETURNING 
                id, 
                email, 
                role, 
                full_name, 
                phone_number, 
                address,
                profile_image
        """
        
        cur.execute(query, update_values)
        updated_profile = cur.fetchone()
        
        # If user has a profile image, add the S3 URL
        if updated_profile and updated_profile["profile_image"]:
            user_folder = f"user_{updated_profile['id']}"
            s3_key = f"uploads/profile_images/{user_folder}/{updated_profile['profile_image']}"
            image_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}"
            updated_profile = dict(updated_profile)
            updated_profile["image_url"] = image_url
        
        conn.commit()
        return updated_profile
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error updating profile: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error updating profile: {str(e)}"
        )




# async def update_restaurant_with_image(
#     restaurant_id: int,
#     restaurant: RestaurantUpdate,
#     image: Optional[UploadFile],
#     current_user: dict,
#     conn = None
# ) -> dict:
#     """
#     Update restaurant details and handle image upload to S3
#     """
#     try:
#         cur = conn.cursor()
        
#         # Check if restaurant exists and is active
#         cur.execute("""
#             SELECT 
#                 id, name, image_url
#             FROM restaurants 
#             WHERE id = %s AND active = true
#         """, (restaurant_id,))
        
#         existing_restaurant = cur.fetchone()
#         if not existing_restaurant:
#             raise HTTPException(
#                 status_code=404,
#                 detail="Restaurant not found or inactive"
#             )

#         # Handle image upload if provided
#         new_image_url = None
#         if image:
#             logger.info(f"Processing image upload: {image.filename}")
            
#             if not image.content_type.startswith('image/'):
#                 raise HTTPException(
#                     status_code=400,
#                     detail="File must be an image"
#                 )

#             try:
#                 # Create S3 path
#                 user_folder = f"user_{current_user['id']}"
#                 restaurant_folder = f"{existing_restaurant['name'].lower().replace(' ', '_')}"
#                 s3_folder = f"uploads/users/{user_folder}/restaurants/{restaurant_folder}"
#                 timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
#                 file_extension = os.path.splitext(image.filename)[1].lower()
#                 new_filename = f"restaurant_{timestamp}{file_extension}"
#                 s3_key = f"{s3_folder}/{new_filename}"

#                 # Delete old image if exists
#                 if existing_restaurant['image_url']:
#                     try:
#                         old_key = existing_restaurant['image_url'].split(f"{BUCKET_NAME}.s3.amazonaws.com/")[1]
#                         logger.info(f"Deleting old image: {old_key}")
#                         s3_client.delete_object(
#                             Bucket=BUCKET_NAME,
#                             Key=old_key
#                         )
#                     except Exception as e:
#                         logger.error(f"Error deleting old image: {str(e)}")

#                 # Read and upload new image
#                 content = await image.read()
#                 logger.info(f"Uploading new image: {s3_key}")
                
#                 response = s3_client.put_object(
#                     Bucket=BUCKET_NAME,
#                     Key=s3_key,
#                     Body=content,
#                     ContentType=image.content_type,
#                     #ACL='public-read'
#                 )
                
#                 logger.info(f"S3 upload response: {response}")
#                 new_image_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}"
                
#             except Exception as e:
#                 logger.error(f"S3 operation error: {str(e)}")
#                 raise HTTPException(
#                     status_code=500,
#                     detail=f"Error processing image: {str(e)}"
#                 )

#         # Update restaurant in database
#         update_fields = ["name = %s", "location = %s", "contact_number = %s"]
#         update_values = [restaurant.name, restaurant.location, restaurant.contact_number]

#         if new_image_url:
#             update_fields.append("image_url = %s")
#             update_values.append(new_image_url)

#         update_values.append(restaurant_id)  # For WHERE clause

#         query = f"""
#             UPDATE restaurants 
#             SET {', '.join(update_fields)}
#             WHERE id = %s
#             RETURNING 
#                 id, 
#                 name, 
#                 location, 
#                 contact_number,
#                 image_url,
#                 created_at,
#                 created_by
#         """

#         cur.execute(query, update_values)
#         updated_restaurant = cur.fetchone()
        
#         # Get creator's details
#         cur.execute("""
#             SELECT email as created_by_email
#             FROM managers 
#             WHERE id = %s
#         """, (updated_restaurant["created_by"],))
        
#         creator = cur.fetchone()
        
#         # Prepare response
#         result = dict(updated_restaurant)
#         result.update({
#             "created_by_email": creator["created_by_email"] if creator else None,
#             "updated_by_email": current_user["email"],
#             "updated_by_id": current_user["id"]
#         })
        
#         # Convert datetime objects to strings for JSON serialization
#         for key, value in result.items():
#             if isinstance(value, datetime):
#                 result[key] = value.isoformat()
        
#         conn.commit()
        
#         return {
#             "message": "Restaurant updated successfully",
#             "restaurant": result
#         }
        
#     except HTTPException:
#         if conn:
#             conn.rollback()
#         raise
#     except Exception as e:
#         if conn:
#             conn.rollback()
#         logger.error(f"Error updating restaurant: {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error updating restaurant: {str(e)}"
#         )


#async def update_restaurant_with_image(
#    restaurant_id: int,
#    restaurant: RestaurantUpdate,
#    image: Optional[UploadFile],
#    image_url: Optional[str],
#    current_user: dict,
#    conn = None
#) -> dict:
#    """
#    Update restaurant details and handle multiple S3 path updates:
#    - Image path: uploads/users/user_{id}/restaurants/{restaurant_name}/
#    - Files path: uploads/restaurants/{restaurant_name}/user_{id}/
#    When restaurant name changes, update all associated S3 file paths.
#    """
#    try:
#        cur = conn.cursor()
#        
#        # Check if restaurant exists and is active
#        cur.execute("""
#            SELECT 
#                id, name, image_url
#            FROM restaurants 
#            WHERE id = %s AND active = true
#        """, (restaurant_id,))
#        
#        existing_restaurant = cur.fetchone()
#        if not existing_restaurant:
#            raise HTTPException(
#                status_code=404,
#                detail="Restaurant not found or inactive"
#            )
#
#        # Check if restaurant name is changing
#        name_changed = existing_restaurant['name'] != restaurant.name
#        old_restaurant_name = existing_restaurant['name'].lower().replace(' ', '_')
#        new_restaurant_name = restaurant.name.lower().replace(' ', '_')
#
#        # If name is changing, update all S3 files in both paths
#        if name_changed:
#            try:
#                # 1. Update image path files
#                image_prefix = f"uploads/users/user_{current_user['id']}/restaurants/{old_restaurant_name}/"
#                # 2. Update general files path
#                files_prefix = f"uploads/restaurants/{old_restaurant_name}/user_{current_user['id']}/"
#                
#                # List and update all objects in both paths
#                for prefix in [image_prefix, files_prefix]:
#                    response = s3_client.list_objects_v2(
#                        Bucket=BUCKET_NAME,
#                        Prefix=prefix
#                    )
#                    
#                    if 'Contents' in response:
#                        for obj in response['Contents']:
#                            old_key = obj['Key']
#                            
#                            # Create new key based on path type
#                            if "uploads/users/user_" in old_key:
#                                # Image path
#                                new_key = old_key.replace(
#                                    f"restaurants/{old_restaurant_name}/",
#                                    f"restaurants/{new_restaurant_name}/"
#                                )
#                            else:
#                                # Files path
#                                new_key = old_key.replace(
#                                    f"restaurants/{old_restaurant_name}/",
#                                    f"restaurants/{new_restaurant_name}/"
#                                )
#                            
#                            # Copy object to new location
#                            s3_client.copy_object(
#                                Bucket=BUCKET_NAME,
#                                CopySource={'Bucket': BUCKET_NAME, 'Key': old_key},
#                                Key=new_key
#                            )
#                            
#                            # Delete old object
#                            s3_client.delete_object(
#                                Bucket=BUCKET_NAME,
#                                Key=old_key
#                            )
#                            
#                            logger.info(f"Moved S3 object from {old_key} to {new_key}")
#
#                            # Update image_url in database if this is the restaurant image
#                            if existing_restaurant['image_url'] and old_key in existing_restaurant['image_url']:
#                                new_image_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{new_key}"
#                                cur.execute("""
#                                    UPDATE restaurants 
#                                    SET image_url = %s 
#                                    WHERE id = %s
#                                """, (new_image_url, restaurant_id))
#
#            except Exception as e:
#                logger.error(f"Error updating S3 paths: {str(e)}")
#                raise HTTPException(
#                    status_code=500,
#                    detail=f"Error updating file paths: {str(e)}"
#                )
#
#        # Handle new image upload if provided
#        new_image_url = None
#        if image:
#            logger.info(f"Processing new image upload: {image.filename}")
#            
#            if not image.content_type.startswith('image/'):
#                raise HTTPException(
#                    status_code=400,
#                    detail="File must be an image"
#                )
#
#            try:
#                # Create S3 path using new restaurant name
#                s3_folder = f"uploads/users/user_{current_user['id']}/restaurants/{new_restaurant_name}"
#                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
#                file_extension = os.path.splitext(image.filename)[1].lower()
#                new_filename = f"restaurant_{timestamp}{file_extension}"
#                s3_key = f"{s3_folder}/{new_filename}"
#
#                # Delete old image if exists
#                if existing_restaurant['image_url']:
#                    try:
#                        old_key = existing_restaurant['image_url'].split(f"{BUCKET_NAME}.s3.amazonaws.com/")[1]
#                        logger.info(f"Deleting old image: {old_key}")
#                        s3_client.delete_object(
#                            Bucket=BUCKET_NAME,
#                            Key=old_key
#                        )
#                    except Exception as e:
#                        logger.error(f"Error deleting old image: {str(e)}")
#
#                # Upload new image
#                content = await image.read()
#                logger.info(f"Uploading new image: {s3_key}")
#                
#                s3_client.put_object(
#                    Bucket=BUCKET_NAME,
#                    Key=s3_key,
#                    Body=content,
#                    ContentType=image.content_type
#                )
#                
#                new_image_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}"
#                
#            except Exception as e:
#                logger.error(f"S3 operation error: {str(e)}")
#                raise HTTPException(
#                    status_code=500,
#                    detail=f"Error processing image: {str(e)}"
#                )
#        elif image_url:
#            # If image_url is provided, use it directly
#            new_image_url = image_url
#        else:
#            new_image_url = None
#            
#
#        # Update restaurant in database
#        update_fields = ["name = %s", "location = %s", "contact_number = %s"]
#        update_values = [restaurant.name, restaurant.location, restaurant.contact_number]
#
#        if new_image_url:
#            update_fields.append("image_url = %s")
#            update_values.append(new_image_url)
#        else:
#            update_fields.append("image_url = %s")
#            update_values.append(None)
#
#        update_values.append(restaurant_id)  # For WHERE clause
#
#        query = f"""
#            UPDATE restaurants 
#            SET {', '.join(update_fields)}
#            WHERE id = %s
#            RETURNING 
#                id, 
#                name, 
#                location, 
#                contact_number,
#                image_url,
#                created_at,
#                created_by
#        """
#
#        cur.execute(query, update_values)
#        updated_restaurant = cur.fetchone()
#        
#        # Get creator's details
#        cur.execute("""
#            SELECT email as created_by_email
#            FROM managers 
#            WHERE id = %s
#        """, (updated_restaurant["created_by"],))
#        
#        creator = cur.fetchone()
#        
#        # Prepare response with path update summary
#        result = dict(updated_restaurant)
#        result.update({
#            "created_by_email": creator["created_by_email"] if creator else None,
#            "updated_by_email": current_user["email"],
#            "updated_by_id": current_user["id"],
#            "path_updates": {
#                "name_changed": name_changed,
#                "old_name": old_restaurant_name if name_changed else None,
#                "new_name": new_restaurant_name if name_changed else None,
#                "image_updated": bool(new_image_url)
#            }
#        })
#        
#        # Convert datetime objects to strings
#        for key, value in result.items():
#            if isinstance(value, datetime):
#                result[key] = value.isoformat()
#        
#        conn.commit()
#        
#        return {
#            "message": "Restaurant updated successfully",
#            "restaurant": result
#        }
#        
#    except HTTPException:
#        if conn:
#            conn.rollback()
#        raise
#    except Exception as e:
#        if conn:
#            conn.rollback()
#        logger.error(f"Error updating restaurant: {str(e)}")
#        raise HTTPException(
#            status_code=500,
#            detail=f"Error updating restaurant: {str(e)}"
#        )
#    
async def update_restaurant_with_image(
    restaurant_id: int,
    restaurant: RestaurantUpdate,
    image: Optional[UploadFile],
    image_url: Optional[str],
    current_user: dict,
    conn
):
    """
    Update restaurant with optional image upload and complete location details
    """
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Check if restaurant exists and user has permission
        if current_user["role"] == "SUPER_ADMIN":
            cur.execute("""
                SELECT * FROM restaurants 
                WHERE id = %s AND active = true
            """, (restaurant_id,))
        elif current_user["role"] == "Restaurant Owner":
            cur.execute("""
                SELECT * FROM restaurants 
                WHERE id = %s AND created_by = %s AND active = true
            """, (restaurant_id, current_user["id"]))
        else:
            cur.execute("""
                SELECT r.* FROM restaurants r
                JOIN restaurant_assignments ra ON r.id = ra.restaurant_id
                WHERE r.id = %s AND ra.manager_id = %s AND r.active = true
            """, (restaurant_id, current_user["id"]))
        
        existing_restaurant = cur.fetchone()
        if not existing_restaurant:
            raise HTTPException(
                status_code=404,
                detail="Restaurant not found or you don't have permission to update it"
            )
        
        # Handle image upload if provided
        final_image_url = image_url
        if image:
            try:
                # Validate file type
                if not image.content_type.startswith('image/'):
                    raise ValueError("File must be an image")
                
                # Create S3 path
                user_folder = f"user_{current_user['id']}"
                restaurant_folder = existing_restaurant['name'].lower().replace(' ', '_')
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
                        s3_client.delete_object(Bucket=BUCKET_NAME, Key=old_key)
                    except Exception as e:
                        logger.error(f"Error deleting old image: {str(e)}")
                
                # Upload new image
                content = await image.read()
                s3_client.put_object(
                    Bucket=BUCKET_NAME,
                    Key=s3_key,
                    Body=content,
                    ContentType=image.content_type
                )
                
                final_image_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}"
                
            except Exception as e:
                logger.error(f"Error processing image: {str(e)}")
                raise ValueError(f"Error processing image: {str(e)}")
        elif image_url:
            final_image_url = image_url
        else:
            final_image_url = existing_restaurant['image_url']
        
        # Build update query with ALL fields including city, state, zip_code, country
        update_fields = []
        update_values = []
        
        # Always update these core fields
        if restaurant.name is not None:
            update_fields.append("name = %s")
            update_values.append(restaurant.name)
        
        if restaurant.location is not None:
            update_fields.append("location = %s")
            update_values.append(restaurant.location)
        
        if restaurant.contact_number is not None:
            update_fields.append("contact_number = %s")
            update_values.append(restaurant.contact_number)
        
        # Update location detail fields - Handle None and empty strings properly
        if restaurant.city is not None:  # This will include empty strings
            update_fields.append("city = %s")
            update_values.append(restaurant.city if restaurant.city else None)
        
        if restaurant.state is not None:
            update_fields.append("state = %s")
            update_values.append(restaurant.state if restaurant.state else None)
        
        if restaurant.zip_code is not None:
            update_fields.append("zip_code = %s")
            update_values.append(restaurant.zip_code if restaurant.zip_code else None)
        
        if restaurant.country is not None:
            update_fields.append("country = %s")
            update_values.append(restaurant.country if restaurant.country else None)
        
        # Handle image URL
        if final_image_url is not None:
            update_fields.append("image_url = %s")
            update_values.append(final_image_url)
        
        if not update_fields:
            raise ValueError("No fields to update")
        
        # Add restaurant_id to the end of values for WHERE clause
        update_values.append(restaurant_id)
        
        # Execute update query
        query = f"""
            UPDATE restaurants 
            SET {', '.join(update_fields)}
            WHERE id = %s
            RETURNING *
        """
        
        logger.info(f"Update query: {query}")
        logger.info(f"Update values: {update_values}")
        
        cur.execute(query, update_values)
        updated_restaurant = cur.fetchone()
        
        if not updated_restaurant:
            raise ValueError("Failed to update restaurant")
        
        conn.commit()
        
        logger.info(f"Successfully updated restaurant {restaurant_id} with fields: {update_fields}")
        
        return dict(updated_restaurant)
        
    except ValueError:
        if conn:
            conn.rollback()
        raise
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error updating restaurant: {str(e)}")
        raise ValueError(f"Error updating restaurant: {str(e)}")
    
async def clear_user_audios(current_user: dict) -> dict:
    """
    Clear all .wav audio files and .json transcript files for a specific user from S3
    """
    try:
        # Construct the exact folder path as it appears in S3
        safe_email = current_user['email'].replace('@', '_at_')
        user_prefix = f"uploads/users/{current_user['id']}_{safe_email}_{current_user['role']}/audio/"
        
        # List all objects in the user's folder
        try:
            response = s3_client.list_objects_v2(
                Bucket=BUCKET_NAME,
                Prefix=user_prefix
            )
            
            if 'Contents' not in response:
                return {
                    "message": "No files found",
                    "deleted": {
                        "audio_files": 0,
                        "transcript_files": 0,
                        "total": 0
                    }
                }

            # Initialize counters
            deleted_stats = {
                "audio_files": 0,  # .wav files
                "transcript_files": 0,  # .json files
                "deleted_files": []  # List of deleted file names
            }

            # Delete objects that end with .wav or .json
            for obj in response['Contents']:
                file_key = obj['Key']
                file_name = file_key.split('/')[-1].lower()
                
                # Only process .wav and .json files
                if not (file_name.endswith('.wav') or file_name.endswith('.json')):
                    continue

                try:
                    logger.info(f"Attempting to delete file: {file_key}")
                    s3_client.delete_object(
                        Bucket=BUCKET_NAME,
                        Key=file_key
                    )
                    
                    # Update statistics
                    if file_name.endswith('.wav'):
                        deleted_stats["audio_files"] += 1
                    elif file_name.endswith('.json'):
                        deleted_stats["transcript_files"] += 1
                        
                    deleted_stats["deleted_files"].append(file_name)
                    logger.info(f"Successfully deleted file: {file_name}")
                    
                except Exception as e:
                    logger.error(f"Error deleting file {file_name}: {str(e)}")
                    continue

            total_deleted = deleted_stats["audio_files"] + deleted_stats["transcript_files"]
            
            return {
                "message": "Files cleared successfully" if total_deleted > 0 else "No files to clear",
                "deleted": {
                    "audio_files": deleted_stats["audio_files"],
                    "transcript_files": deleted_stats["transcript_files"],
                    "total": total_deleted,
                    "files": deleted_stats["deleted_files"]
                }
            }

        except s3_client.exceptions.NoSuchKey:
            return {
                "message": "No files found",
                "deleted": {
                    "audio_files": 0,
                    "transcript_files": 0,
                    "total": 0
                }
            }
            
    except Exception as e:
        logger.error(f"Error clearing audio files: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error clearing audio files: {str(e)}"
        )

 #Export all functions that will be used in routes.py
__all__ = [
    'login',
    'manager_login',
    'register_regional_manager',
    'register_restaurant_manager',
    'verify_manager_email',
    'resend_verification_otp',
    'forgot_password',
    'reset_password',
    'create_restaurant',
    'update_restaurant',
    'delete_restaurant',
    'reactivate_restaurant',
    'get_active_restaurants',
    'get_inactive_restaurants',
    'get_regional_managers',
    'get_restaurant_managers',
    'update_profile',
    'get_current_user',
    'init_db',
    'create_initial_super_admins',
    'RoleType',
    'upload_profile_image',
    'get_current_user_profile_image',
    'get_all_restaurants',
    'update_restaurant_with_image',
    'get_unassigned_restaurants',
    'clear_user_audios',
    'create_notification',
    'get_notifications_by_user_id',
    'mark_notification_as_read'
]

# WebSocket Notification Manager
from datetime import datetime

# class NotificationConnectionManager:
#     def __init__(self):
#         # Dictionary mapping user_id to list of active WebSocket connections
#         self.active_connections: Dict[int, List[WebSocket]] = {}
    
#     async def connect(self, websocket: WebSocket, user_id: int):
#         await websocket.accept()
#         if user_id not in self.active_connections:
#             self.active_connections[user_id] = []
#         self.active_connections[user_id].append(websocket)
#         logger.info(f"User {user_id} connected to notification websocket")
    
#     def disconnect(self, websocket: WebSocket, user_id: int):
#         if user_id in self.active_connections:
#             if websocket in self.active_connections[user_id]:
#                 self.active_connections[user_id].remove(websocket)
#             # Clean up empty lists
#             if not self.active_connections[user_id]:
#                 del self.active_connections[user_id]
#         logger.info(f"User {user_id} disconnected from notification websocket")
    
#     async def broadcast_to_user(self, user_id: int, message: dict):
#         """Send notification to all connections for a specific user"""
#         logger.info(f"Message type: {message.get('type')}")
#         # Ensure all datetime fields are serialized to strings
#         self._serialize_datetime_in_message(message)
#         # logger.info(f"Message type: {message.get('type')}")
#         if user_id in self.active_connections:
#             disconnected_websockets = []
#             for websocket in self.active_connections[user_id]:
#                 try:
#                     await websocket.send_json(message)
#                     logger.info(f"Broadcasting notification: sent to user {user_id}")
#                 except Exception as e:
#                     logger.error(f"Error sending notification to user {user_id}: {str(e)}")
#                     disconnected_websockets.append(websocket)
            
#             # Clean up any disconnected websockets
#             for websocket in disconnected_websockets:
#                 self.active_connections[user_id].remove(websocket)
            
#             # If all connections are gone, clean up the user entry
#             if not self.active_connections[user_id]:
#                 del self.active_connections[user_id]
#         else:
#             logger.info(f"No active connections for user {user_id} to send notification")
#     def _serialize_datetime_in_message(self, message: dict):
#         """Helper function to ensure datetime objects are serialized to string"""
#         for key, value in message.items():
#             if isinstance(value, dict):
#                 # Recursively serialize datetime objects in nested dicts
#                 self._serialize_datetime_in_message(value)
#             elif isinstance(value, list):
#                 # Handle lists of items that might contain datetime objects
#                 for item in value:
#                     if isinstance(item, dict):
#                         self._serialize_datetime_in_message(item)
#             elif isinstance(value, datetime):
#                 # Serialize datetime to ISO format
#                 message[key] = value.isoformat()

# Initialize the notification manager
# notification_manager = NotificationConnectionManager()

# Notification Functions ...
from typing import Optional
from fastapi import HTTPException

async def create_notification(
    user_id: int,
    title: str,
    message: str,
    type: str = "info",
    cat: Optional[str] = None,
    restaurant_id: Optional[int] = None,
    role: Optional[str] = None,
    conn=None
):
    """
    Create a new notification for a user
    
    Args:
        user_id: The ID of the user to notify
        title: The notification title
        message: The notification message content
        type: The notification type (e.g., 'info', 'alert', 'warning')
        restaurant_id: Optional restaurant ID if notification is related to a specific restaurant
        role: Optional role information
        conn: Database connection
    
    Returns:
        The created notification details
    
    cat:
    - fraud
    - account
    - subscription
    - file
    - email
    """
    try:
        cur = conn.cursor()
    except Exception as e:
        logger.error(f"Failed to create cursor: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create cursor: {e}")

    try:
        # Fetch user notification settings
        cur.execute("""
            SELECT 
                fraud_alerts,
                account_notifications,
                subscription_alerts,
                file_processing_updates
            FROM user_notification_settings
            WHERE user_id = %s
        """, (user_id,))
        settings = cur.fetchone()
        if settings is None:
            raise HTTPException(status_code=404, detail=f"No notification settings found for user {user_id}")
    except Exception as e:
        logger.error(f"Error fetching user notification settings: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching user notification settings: {e}")

    try:
        # Insert notification based on category and user preferences
        should_insert = False
        if cat == "fraud" and settings["fraud_alerts"]:
            should_insert = True
        elif cat == "account" and settings["account_notifications"]:
            should_insert = True
        elif cat == "subscription" and settings["subscription_alerts"]:
            should_insert = True
        elif cat == "file" and settings["file_processing_updates"]:
            should_insert = True
        elif cat not in ("fraud", "account", "subscription", "file"):
            # Unknown or unspecified category defaults to inserting
            should_insert = True

        notification = None
        if should_insert:
            cur.execute("""
                INSERT INTO notifications 
                (user_id, restaurant_id, role, title, message, type)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, user_id, restaurant_id, role, title, message, type, is_read, created_at
            """, (user_id, restaurant_id, role, title, message, type))
            notification = cur.fetchone()
            if notification is None:
                raise HTTPException(status_code=500, detail="Failed to create notification record")
        else:
            logger.info(f"User {user_id} opted out of '{cat}' notifications.")
    except Exception as e:
        logger.error(f"Error inserting notification: {e}")
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error inserting notification: {e}")

    try:
        conn.commit()
    except Exception as e:
        logger.error(f"Error committing transaction: {e}")
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error committing transaction: {e}")

    if notification:
        try:
            logger.info(f"📢 Created notification {notification['id']} for user {user_id}")
        except Exception as e:
            logger.warning(f"Could not log notification id: {e}")

        try:
            # await notification_manager.broadcast_to_user(
            #     user_id=user_id,
            #     message={
            #         "type": "notification",
            #         "action": "new",
            #         "data": dict(notification)
            #     }
            # )
            message={
                    "type": "notification",
                    "action": "new",
                    "data": dict(notification)
                }
            
            await notification_manager.publish_notification(user_id, message)
        except Exception as e:
            logger.error(f"Error broadcasting notification: {e}")
            # Do NOT raise; broadcasting failure shouldn't break main flow

    return notification


async def get_notifications_by_user_id(user_id: int, limit: int = 50, offset: int = 0, conn = None):
    """
    Get notifications for a specific user
    
    Args:
        user_id: The ID of the user
        limit: Maximum number of notifications to return
        offset: Number of notifications to skip (for pagination)
        conn: Database connection
    
    Returns:
        List of notifications for the user
    """
    try:
        cur = conn.cursor()
        
        # Get notifications for the user
        cur.execute("""
            SELECT id, user_id, restaurant_id, role, title, message, type, is_read, created_at
            FROM notifications
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, (user_id, limit, offset))
        
        notifications = cur.fetchall()
        
        # Get total count for pagination
        cur.execute("SELECT COUNT(*) as total FROM notifications WHERE user_id = %s", (user_id,))
        total_count = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) as unread FROM notifications WHERE user_id = %s AND is_read = FALSE", (user_id,))
        unread_count = cur.fetchone()['unread']

        return {
            "notifications": notifications,
            "total": total_count,
            "unread_count": unread_count,
            "read_count": total_count - unread_count,
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        logger.error(f"Error fetching notifications: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch notifications: {str(e)}")

async def mark_notification_as_read(notification_id: int, user_id: int, conn = None):
    """
    Mark a notification as read
    
    Args:
        notification_id: The ID of the notification to mark as read
        user_id: The ID of the user who owns the notification (for security check)
        conn: Database connection
    
    Returns:
        The updated notification details
    """
    try:
        cur = conn.cursor()
        
        # First check if the notification exists and belongs to the user
        cur.execute("""
            SELECT id, user_id, is_read
            FROM notifications
            WHERE id = %s
        """, (notification_id,))
        
        notification = cur.fetchone()
        
        if not notification:
            raise HTTPException(status_code=404, detail="Notification not found")
            
        # Security check: ensure the notification belongs to the user
        if notification['user_id'] != user_id:
            raise HTTPException(
                status_code=403, 
                detail="You don't have permission to update this notification"
            )
            
        # If already read, just return the notification
        if notification['is_read']:
            # Get full notification details
            cur.execute("""
                SELECT id, user_id, restaurant_id, role, title, message, type, is_read, created_at
                FROM notifications
                WHERE id = %s
            """, (notification_id,))
            return cur.fetchone()
        
        # Update the notification to mark it as read
        cur.execute("""
            UPDATE notifications
            SET is_read = TRUE
            WHERE id = %s
            RETURNING id, user_id, restaurant_id, role, title, message, type, is_read, created_at
        """, (notification_id,))
        
        updated_notification = cur.fetchone()
        conn.commit()
        
        logger.info(f"Marked notification {notification_id} as read for user {user_id}")
        
        # Broadcast the notification update to connected users via WebSocket
        # try:
        #     # await notification_manager.broadcast_to_user(
        #     #     user_id=user_id,
        #     #     message={
        #     #         "type": "notification",
        #     #         "action": "updated",
        #     #         "data": dict(updated_notification)
        #     #     }
        #     # )
        #     message={
        #             "type": "notification",
        #             "action": "updated",
        #             "data": dict(updated_notification)
        #         }
            
        #     await notification_manager.publish_notification(user_id, message)
        # except Exception as e:
        #     logger.error(f"Error broadcasting notification update: {str(e)}")
            
            
            # We don't want to fail the notification update if broadcasting fails
        
        return updated_notification
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error marking notification as read: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to mark notification as read: {str(e)}")

async def mark_all_notifications_as_read(user_id: int, conn = None):
    """
    Mark all notifications as read for a specific user
    
    Args:
        user_id: The ID of the user
        conn: Database connection
    
    Returns:
        Dict containing number of notifications marked as read
    """
    try:
        cur = conn.cursor()
        
        # Update all unread notifications for the user
        cur.execute("""
            UPDATE notifications
            SET is_read = TRUE
            WHERE user_id = %s AND is_read = FALSE
            RETURNING id
        """, (user_id,))
        
        updated_count = cur.rowcount
        conn.commit()
        
        logger.info(f"Marked {updated_count} notifications as read for user {user_id}")
        
        return {
            "message": f"Marked {updated_count} notifications as read",
            "updated_count": updated_count,
            "user_id": user_id
        }
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error marking all notifications as read: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to mark notifications as read: {str(e)}"
        )

async def delete_notification(notification_id: int, user_id: int, conn = None):
    """
    Delete a specific notification
    
    Args:
        notification_id: The ID of the notification to delete
        user_id: The ID of the user who owns the notification (for security check)
        conn: Database connection
    
    Returns:
        Dict containing deletion confirmation
    """
    try:
        cur = conn.cursor()
        
        # First check if the notification exists and belongs to the user
        cur.execute("""
            SELECT id, user_id
            FROM notifications
            WHERE id = %s
        """, (notification_id,))
        
        notification = cur.fetchone()
        
        if not notification:
            raise HTTPException(
                status_code=404, 
                detail="Notification not found"
            )
            
        # Security check: ensure the notification belongs to the user
        if notification['user_id'] != user_id:
            raise HTTPException(
                status_code=403, 
                detail="You don't have permission to delete this notification"
            )
        
        # Delete the notification
        cur.execute("""
            DELETE FROM notifications
            WHERE id = %s
            RETURNING id
        """, (notification_id,))
        
        conn.commit()
        
        logger.info(f"Deleted notification {notification_id} for user {user_id}")
        
        return {
            "message": "Notification deleted successfully",
            "notification_id": notification_id,
            "user_id": user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting notification: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete notification: {str(e)}"
        )
# Continue with all other route implementations...
# Including registration, email verification, restaurant management
