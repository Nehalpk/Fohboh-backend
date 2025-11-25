from fastapi import HTTPException, status, Depends, UploadFile
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, validator
from typing import Optional, Dict, List
from datetime import datetime, timedelta, timezone
import jwt
import logging
import uuid
import os
from dotenv import load_dotenv

security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Import from chat_gpt.py
from src.chat_gpt import (
    RoleType,
    JWT_SECRET,
    JWT_ALGORITHM,
    get_password_hash,
    verify_password,
    validate_restaurant_assignment,
    generate_otp,
    send_verification_email,
    create_access_token,
    send_password_reset_email,
    OTPRequest,
    send_email,
    create_notification
)

# Import from smtp_send_email.py
# from smtp_send_email import send_email_api

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Constants
INVITATION_TOKEN_EXPIRE_DAYS = 7
FRONTEND_URL = os.getenv("FRONTEND_URL",
                         "https://staging.fohboh.ai")


# Models
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    phone_number: str
    address: Optional[str] = None
    role: str = "Non_Operators"  # Default role for regular users

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


class RestaurantOwnerCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    phone_number: str
    address: Optional[str] = None

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


class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    address: Optional[str] = None


class ManagerInvitation(BaseModel):
    email: EmailStr
    full_name: str
    phone_number: str
    # profile_image: Optional[UploadFile] = None
    role: str  # "Regional Manager" or "Restaurant Manager"
    restaurant_names: List[str]
    regional_manager_id: Optional[int] = None  # Only required for Restaurant Managers

    @validator('role')
    def validate_role(cls, v):
        if v not in [RoleType.REGIONAL_MANAGER, RoleType.RESTAURANT_MANAGER]:
            raise ValueError(f'Role must be either "{RoleType.REGIONAL_MANAGER}" or "{RoleType.RESTAURANT_MANAGER}"')
        return v

    @validator('regional_manager_id')
    def validate_regional_manager_id(cls, v, values):
        if 'role' in values and values['role'] == RoleType.RESTAURANT_MANAGER and v is None:
            raise ValueError(f'regional_manager_id is required for {RoleType.RESTAURANT_MANAGER}')
        return v


class ManagerRegistration(BaseModel):
    token: str
    password: str

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


# Invitation Functions
def create_invitation_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create a JWT token for invitation"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(days=INVITATION_TOKEN_EXPIRE_DAYS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_invitation_token(token: str):
    """Verify the invitation token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation link has expired"
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid invitation link"
        )


def send_invitation_email(email: str, full_name: str, token: str, role: str) -> bool:
    """Send invitation email with registration link"""
    subject = f"Invitation to Join as {role}"
    registration_url = f"{FRONTEND_URL}/register/invitation?token={token}"
    print("token", token)
    html_content = f"""
    <html>
        <body>
            <h2>Welcome to FOHBOH!</h2>
            <p>Hello {full_name},</p>
            <p>You have been invited to join our platform as a {role}.</p>
            <p>Please click the link below to complete your registration:</p>
            <a href="{registration_url}" style="display: inline-block; background-color: #4CAF50; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Complete Registration</a>
            <p>This invitation link will expire in {INVITATION_TOKEN_EXPIRE_DAYS} days.</p>
            <p>If you did not request this invitation, please ignore this email.</p>
        </body>
    </html>
    """
    return send_email(email, subject, html_content)


def send_welcome_email(email: str, full_name: str, user_role: str = "User") -> bool:
    """Send welcome email to new users after email verification"""
    subject = f"🎉 Welcome to FOHBOH, {full_name}!"
    html_content = f"""
    <html>
      <body style="font-family: 'Arial', sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">

        <!-- Header -->
        <div style="background: linear-gradient(135deg, #4CAF50, #45a049); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
          <h1 style="margin: 0; font-size: 28px;">🎉 Welcome to FOHBOH!</h1>
          <p style="margin: 10px 0 0 0; font-size: 16px; opacity: 0.9;">Your Restaurant Management Platform</p>
        </div>

        <!-- Main Content -->
        <div style="background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px;">
          <h2 style="color: #4CAF50; margin-top: 0;">Hello {full_name}! 👋</h2>

          <p style="font-size: 16px;">We're absolutely thrilled to have you join the FOHBOH family! Your email has been successfully verified and your account is now active.</p>

          <div style="background: white; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #4CAF50;">
            <h3 style="color: #333; margin-top: 0;">🚀 What You Can Do Now:</h3>
            <ul style="padding-left: 20px;">
              <li><strong>📊 AI-Powered Analytics:</strong> Get instant insights from your restaurant data</li>
              <li><strong>📈 Dashboard & KPIs:</strong> Track sales, inventory, and labor costs</li>
              <li><strong>🤖 Smart Assistant:</strong> Ask questions about your business in natural language</li>
              <li><strong>📁 File Management:</strong> Upload and analyze CSV, PDF, and Excel files</li>
              <li><strong>🔔 Real-time Notifications:</strong> Stay updated on important business metrics</li>
              <li><strong>🏪 Multi-Restaurant Management:</strong> Manage multiple locations efficiently</li>
            </ul>
          </div>

          <div style="background: #e8f5e8; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <h4 style="color: #2e7d32; margin: 0 0 10px 0;">🎯 Your Account Details:</h4>
            <p style="margin: 5px 0;"><strong>Email:</strong> {email}</p>
            <p style="margin: 5px 0;"><strong>Role:</strong> {user_role}</p>
            <p style="margin: 5px 0;"><strong>Status:</strong> ✅ Verified & Active</p>
          </div>

          <div style="text-align: center; margin: 30px 0;">
            <h3 style="color: #4CAF50;">🌟 Ready to Get Started?</h3>
            <p>Log in to your dashboard and start exploring the powerful features that will transform how you manage your restaurant!</p>
          </div>

          <div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <h4 style="color: #856404; margin: 0 0 10px 0;">💡 Need Help?</h4>
            <p style="margin: 0; color: #856404;">Our support team is here to help you succeed. If you have any questions or need assistance, don't hesitate to reach out!</p>
          </div>

          <!-- Footer -->
          <div style="text-align: center; margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd;">
            <p style="color: #666; margin: 0;">Happy restaurant managing! 🍽️</p>
            <p style="color: #4CAF50; font-weight: bold; margin: 10px 0;">The FOHBOH Team ✨</p>
            <p style="color: #999; font-size: 12px; margin: 0;">© 2024 FOHBOH. All rights reserved.</p>
          </div>
        </div>

      </body>
    </html>
    """
    return send_email(email, subject, html_content)


async def invite_manager(
        invitation: ManagerInvitation,
        current_user: dict,
        conn=None
):
    """Send invitation to a manager (Regional or Restaurant)"""
    # Check permissions based on role
    if invitation.role == RoleType.REGIONAL_MANAGER and current_user["role"] not in [RoleType.SUPER_ADMIN,
                                                                                     RoleType.RESTAURANT_OWNER]:
        raise HTTPException(status_code=403, detail=f"Only SUPER_ADMIN can invite {RoleType.REGIONAL_MANAGER}s")

    if invitation.role == RoleType.RESTAURANT_MANAGER and current_user["role"] not in [RoleType.SUPER_ADMIN,
                                                                                       RoleType.REGIONAL_MANAGER,
                                                                                       RoleType.RESTAURANT_OWNER]:
        raise HTTPException(status_code=403,
                            detail=f"Only SUPER_ADMIN or {RoleType.REGIONAL_MANAGER} can invite {RoleType.RESTAURANT_MANAGER}s")

    try:
        cur = conn.cursor()

        # Check if email exists
        cur.execute("SELECT id FROM managers WHERE email = %s", (invitation.email,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Email already registered")

        # Validate minimum and maximum number of restaurants based on role
        if not invitation.restaurant_names:
            raise HTTPException(
                status_code=400,
                detail=f"At least one restaurant must be assigned to the {invitation.role}"
            )

        # Regional Managers can have multiple restaurants, Restaurant Managers only one
        if invitation.role == RoleType.RESTAURANT_MANAGER and len(invitation.restaurant_names) > 1:
            raise HTTPException(
                status_code=400,
                detail=f"A {RoleType.RESTAURANT_MANAGER} can only be assigned to one restaurant"
            )

        if invitation.role == RoleType.REGIONAL_MANAGER and len(
                invitation.restaurant_names) > 10:  # Adjust limit as needed
            raise HTTPException(
                status_code=400,
                detail=f"Maximum number of restaurants that can be assigned to a {RoleType.REGIONAL_MANAGER} is 10"
            )

        # Verify restaurants exist and are not already assigned
        restaurant_ids = []
        already_assigned = []

        for restaurant_name in invitation.restaurant_names:
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

            # Check if restaurant is already assigned based on role
            if invitation.role == RoleType.REGIONAL_MANAGER:
                # For Regional Manager, check if restaurant is already assigned to another Regional Manager
                cur.execute("""
                    SELECT 
                        r.name as restaurant_name,
                        m.email as manager_email,
                        m.full_name as manager_name,
                        m.role as manager_role
                    FROM restaurant_assignments ra
                    JOIN restaurants r ON ra.restaurant_id = r.id
                    JOIN managers m ON ra.manager_id = m.id
                    WHERE ra.restaurant_id = %s AND m.active = true AND m.role = %s
                """, (result["id"], RoleType.REGIONAL_MANAGER))
            else:
                # For Restaurant Manager, check if restaurant is already assigned to another Restaurant Manager
                cur.execute("""
                    SELECT 
                        r.name as restaurant_name,
                        m.email as manager_email,
                        m.full_name as manager_name,
                        m.role as manager_role
                    FROM restaurant_assignments ra
                    JOIN restaurants r ON ra.restaurant_id = r.id
                    JOIN managers m ON ra.manager_id = m.id
                    WHERE ra.restaurant_id = %s AND m.active = true AND m.role = %s
                """, (result["id"], RoleType.RESTAURANT_MANAGER))

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
            detail = f"The following restaurants are already assigned to another {invitation.role}:\n"
            for item in already_assigned:
                detail += f"- {item['restaurant']} → {item['assigned_to']}\n"
            raise HTTPException(status_code=400, detail=detail)

        # For Restaurant Managers, verify the regional manager exists
        regional_manager_id = None
        if invitation.role == RoleType.RESTAURANT_MANAGER:
            if invitation.regional_manager_id is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"A Regional Manager must be assigned to the Restaurant Manager"
                )

            # Verify the regional manager exists and is active
            cur.execute("""
                SELECT id, email 
                FROM managers 
                WHERE id = %s AND role = %s AND active = true
            """, (invitation.regional_manager_id, RoleType.REGIONAL_MANAGER))

            regional_manager = cur.fetchone()
            if not regional_manager:
                raise HTTPException(
                    status_code=400,
                    detail=f"Regional Manager with ID {invitation.regional_manager_id} not found or not active"
                )

            regional_manager_id = invitation.regional_manager_id

        # Create invitation record in database
        invitation_id = str(uuid.uuid4())

        expires_at = datetime.now(timezone.utc) + timedelta(days=INVITATION_TOKEN_EXPIRE_DAYS)

        # Check if we need to alter the table to add regional_manager_id column
        cur.execute("""
            DO $$ 
            BEGIN
                IF NOT EXISTS (
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='manager_invitations' AND column_name='regional_manager_id'
                ) THEN
                    ALTER TABLE manager_invitations ADD COLUMN regional_manager_id INTEGER REFERENCES managers(id);
                END IF;
            END $$;
        """)

        cur.execute("""
            INSERT INTO manager_invitations (
                id, 
                email, 
                full_name, 
                phone_number, 
                role, 
                created_by, 
                expires_at, 
                restaurant_ids,
                regional_manager_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            invitation_id,
            invitation.email,
            invitation.full_name,
            invitation.phone_number,
            invitation.role,
            current_user["id"],
            expires_at,
            restaurant_ids,
            regional_manager_id
        ))

        # Create invitation token
        token_data = {
            "sub": invitation.email,
            "invitation_id": invitation_id,
            "role": invitation.role,
            "name": invitation.full_name
        }

        # Include regional_manager_id in token data if it's a Restaurant Manager
        if invitation.role == RoleType.RESTAURANT_MANAGER and regional_manager_id:
            token_data["regional_manager_id"] = regional_manager_id

        invitation_token = create_invitation_token(token_data)

        # Generate invitation link for response
        invitation_link = f"{FRONTEND_URL}/register/invitation?token={invitation_token}"

        # Send invitation email
        email_sent = send_invitation_email(
            invitation.email,
            invitation.full_name,
            invitation_token,
            invitation.role
        )

        # Get restaurant details for response
        assigned_restaurants = []
        for restaurant_id in restaurant_ids:
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

        conn.commit()

        # Generate the invitation link
        invitation_link = f"{FRONTEND_URL}/register/invitation?token={invitation_token}"

        response_data = {
            "message": f"{invitation.role} invitation sent successfully.",
            "invitation": {
                "id": invitation_id,
                "email": invitation.email,
                "full_name": invitation.full_name,
                "role": invitation.role,
                "phone_number": invitation.phone_number,
                "expires_at": expires_at.isoformat(),
                "assigned_restaurants": assigned_restaurants,
                "invitation_link": invitation_link
            },
            "invitation_email_sent": email_sent
        }

        # Include regional_manager_id in response if it's a Restaurant Manager
        if invitation.role == RoleType.RESTAURANT_MANAGER and regional_manager_id:
            response_data["invitation"]["regional_manager_id"] = regional_manager_id

            # Get regional manager details
            cur.execute("""
                SELECT email, full_name 
                FROM managers 
                WHERE id = %s
            """, (regional_manager_id,))

            rm = cur.fetchone()
            if rm:
                response_data["invitation"]["regional_manager"] = {
                    "id": regional_manager_id,
                    "email": rm["email"],
                    "full_name": rm["full_name"]
                }

        await create_notification(
            user_id=current_user["id"],
            title="Invited Successfully!",
            message=(
                f"🎉 Congratulations! You have successfully invited {invitation.full_name} "
                f"to join your team as a {invitation.role}. 👏\n\n"
                f"They are now part of the restaurant(s): {invitation.restaurant_names}. 🍽️\n\n"
                "We're excited to see the great things you'll accomplish together! 🚀"
            ),

            type="info",
            cat="account",
            conn=conn
        )

        return response_data
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error inviting {invitation.role}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# non operators
async def register_user(
        user_data: UserCreate,
        conn=None
):
    """Register a new regular user"""
    try:
        cur = conn.cursor()

        # Check if email already exists
        cur.execute("SELECT id FROM managers WHERE email = %s", (user_data.email,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Email already registered")

        # Hash the password
        password_hash = get_password_hash(user_data.password)

        # Generate OTP for email verification
        otp = generate_otp()
        otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

        try:
            # Optional: Check if the email exists
            cur.execute("SELECT 1 FROM email_verification WHERE email = %s", (user_data.email,))
            if cur.fetchone():
                cur.execute("DELETE FROM email_verification WHERE email = %s", (user_data.email,))

                logger.info(f"Email verification record for {user_data.email} deleted successfully.")
            else:
                logger.info(f"No email verification record found for {user_data.email}.")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error deleting email verification record: {str(e)}")

        # Check if we need to create the email_verification table
        # cur.execute("""
        #     CREATE TABLE IF NOT EXISTS email_verification (
        #         id SERIAL PRIMARY KEY,
        #         email VARCHAR(255) UNIQUE NOT NULL,
        #         otp VARCHAR(10) NOT NULL,
        #         expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
        #         created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        #     )
        # """)

        # Insert the user
        cur.execute("""
            INSERT INTO managers (
                email, password_hash, role, full_name, phone_number, address
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            user_data.email,
            password_hash,
            user_data.role,
            user_data.full_name,
            user_data.phone_number,
            user_data.address
        ))

        user_id = cur.fetchone()["id"]

        # Create default notification settings for the new user
        try:
            cur.execute("""
                INSERT INTO user_notification_settings 
                (user_id, fraud_alerts, account_notifications, 
                subscription_alerts, file_processing_updates)
                VALUES (%s, false, true, true, false)
            """, (user_id,))
            logger.info(f"Default notification settings created for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to create default notification settings for user {user_id}: {str(e)}")
            # Continue with registration even if notification settings creation fails

        # Store OTP for verification
        cur.execute("""
            INSERT INTO email_verification (email, otp, expires_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (email) 
            DO UPDATE SET otp = EXCLUDED.otp, expires_at = EXCLUDED.expires_at
        """, (user_data.email, otp, otp_expires_at))

        # Send verification email
        email_sent = send_verification_email(user_data.email, otp)

        conn.commit()

        return {
            "message": "User registered successfully. Please verify your email.",
            "user_id": user_id,
            "email": user_data.email,
            "verification_email_sent": email_sent
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error registering user: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def resend_verification_otp_non_operator(request: OTPRequest, conn=None):
    """Resend verification OTP for non-operator users"""
    try:
        cur = conn.cursor()

        # Check if user exists and is not verified
        cur.execute("""
            SELECT id, email, email_verified
            FROM managers 
            WHERE email = %s AND active = true
        """, (request.email,))

        user = cur.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # if user["email_verified"]:
        #     raise HTTPException(status_code=400, detail="Email already verified")

        # Generate new OTP
        otp = generate_otp()
        otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

        # Delete any existing OTP for this email
        try:
            cur.execute("DELETE FROM email_verification WHERE email = %s", (request.email,))
            logger.info(f"Email verification record for {request.email} deleted successfully.")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error deleting email verification record: {str(e)}")

        # Store new OTP
        cur.execute("""
            INSERT INTO email_verification (email, otp, expires_at)
            VALUES (%s, %s, %s)
        """, (request.email, otp, otp_expires_at))

        # Send verification email
        email_sent = send_verification_email(request.email, otp)

        conn.commit()

        return {
            "message": "Verification OTP resent successfully",
            "email": request.email,
            "verification_email_sent": email_sent
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error resending verification OTP: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def login_user(
        email: str,
        password: str,
        conn=None
):
    """Login for regular users"""
    try:
        cur = conn.cursor()

        # Get user by email
        cur.execute("""
            SELECT id, email, password_hash, role, full_name, email_verified, active
            FROM managers
            WHERE email = %s
        """, (email,))

        user = cur.fetchone()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )

        if user["role"] != "Non_Operators":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )

        # Check if user is active
        if not user["active"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is deactivated"
            )

        # Verify password
        if not verify_password(password, user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )

        # Check if email is verified
        if not user["email_verified"]:
            # Generate new OTP for verification
            otp = generate_otp()
            otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

            try:
                # Optional: Check if the email exists
                cur.execute("SELECT 1 FROM email_verification WHERE email = %s", (email,))
                if cur.fetchone():
                    cur.execute("DELETE FROM email_verification WHERE email = %s", (email,))

                    logger.info(f"Email verification record for {email} deleted successfully.")
                else:
                    logger.info(f"No email verification record found for {email}.")
            except Exception as e:
                conn.rollback()
                logger.error(f"Error deleting email verification record: {str(e)}")

                # Update or insert OTP
                cur.execute("""
                    INSERT INTO email_verification (email, otp, expires_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (email) 
                    DO UPDATE SET otp = EXCLUDED.otp, expires_at = EXCLUDED.expires_at
                """, (email, otp, otp_expires_at))

                # Send verification email
                email_sent = send_verification_email(email, otp)

            conn.commit()

            return {
                "status": "unverified",
                "message": "Email not verified. A new verification code has been sent.",
                "email_sent": email_sent
            }

        from src.settings_and_integrations import get_notification_settings
        await get_notification_settings(user, conn)

        # Create access token
        access_token_expires = timedelta(minutes=60)  # Adjust as needed
        access_token = create_access_token(
            data={"sub": email, "role": user["role"]},
            expires_delta=access_token_expires
        )

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "role": user["role"],
            "user": {
                "id": user["id"],
                "email": user["email"],
                "full_name": user["full_name"],
                "role": user["role"]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error logging in user: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def register_restaurant_owner(
        owner_data: RestaurantOwnerCreate,
        conn=None
):
    """Register a new restaurant owner in the managers table"""
    try:
        cur = conn.cursor()

        # Check if email already exists in managers table
        cur.execute("SELECT id FROM managers WHERE email = %s", (owner_data.email,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Email already registered")

        # Hash the password
        password_hash = get_password_hash(owner_data.password)

        # Generate OTP for email verification
        otp = generate_otp()
        otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

        try:
            # Optional: Check if the email exists
            cur.execute("SELECT 1 FROM email_verification WHERE email = %s", (owner_data.email,))
            if cur.fetchone():
                cur.execute("DELETE FROM email_verification WHERE email = %s", (owner_data.email,))

                logger.info(f"Email verification record for {owner_data.email} deleted successfully.")
            else:
                logger.info(f"No email verification record found for {owner_data.email}.")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error deleting email verification record: {str(e)}")

        # Insert the restaurant owner into managers table hlo
        cur.execute("""
            INSERT INTO managers (
                email, password_hash, role, full_name, phone_number, address
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            owner_data.email,
            password_hash,
            RoleType.RESTAURANT_OWNER,
            owner_data.full_name,
            owner_data.phone_number,
            owner_data.address
        ))

        owner_id = cur.fetchone()["id"]
        # here, I'm assuming you're storing the OTP in a separate table named manager_otps
        # Store OTP for verification
        # cur.execute("""
        #     INSERT INTO email_verification (email, otp, expires_at)
        #     VALUES (%s, %s, %s)
        #     ON CONFLICT (email)
        #     DO UPDATE SET otp = EXCLUDED.otp, expires_at = EXCLUDED.expires_at
        # """, (owner_data.email, otp, otp_expires_at))

        cur.execute("""
            INSERT INTO manager_otps (manager_id, otp, purpose, expires_at)
            VALUES (%s, %s, 'signup verification', %s)
        """, (owner_id, otp, otp_expires_at))

        # Create default notification settings for the new user
        try:
            cur.execute("""
                INSERT INTO user_notification_settings 
                (user_id, fraud_alerts, account_notifications, 
                subscription_alerts, file_processing_updates)
                VALUES (%s, false, true, true, false)
            """, (owner_id,))
            logger.info(f"Default notification settings created for user {owner_id}")
        except Exception as e:
            logger.error(f"Failed to create default notification settings for user {owner_id}: {str(e)}")
            # Continue with registration even if notification settings creation fails

        # Send verification email
        email_sent = send_verification_email(owner_data.email, otp)

        # Create free trial subscription before committing
        from src.subscription_management import SubscriptionManager
        
        try:
            subscription_result = await SubscriptionManager.create_free_trial(owner_id, conn)
            logger.info(f"Free trial subscription created successfully for owner {owner_id}")
        except Exception as e:
            logger.error(f"Failed to create free trial subscription for owner {owner_id}: {str(e)}")
            # Don't fail the registration if subscription creation fails
            subscription_result = None

        conn.commit()

        await create_notification(
            user_id=owner_id,
            title="Account Created!",
            message="Restaurant owner registered successfully. Please verify your email.",
            type="info",
            cat="account",
            conn=conn
        )

        response_data = {
            "message": "Restaurant owner registered successfully. Please verify your email.",
            "owner_id": owner_id,
            "email": owner_data.email,
            "verification_email_sent": email_sent
        }
        
        # Add subscription info to response if creation was successful
        if subscription_result:
            response_data["subscription_created"] = True
            response_data["subscription_id"] = subscription_result
        else:
            response_data["subscription_created"] = False
            response_data["subscription_note"] = "Free trial subscription will be created on first login"

        return response_data
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error registering restaurant owner: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def verify_user_email(
        email: str,
        otp: str,
        conn=None
):
    """Verify a user's email with OTP"""
    try:
        cur = conn.cursor()

        # Check if OTP exists and is valid
        cur.execute("""
            SELECT * FROM email_verification
            WHERE email = %s AND otp = %s AND expires_at > NOW()
        """, (email, otp))

        verification = cur.fetchone()
        if not verification:
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired OTP"
            )

        # First check if email exists in managers table
        cur.execute("""
            UPDATE managers
            SET email_verified = true
            WHERE email = %s
            RETURNING id, email, full_name, role
        """, (email,))

        user = cur.fetchone()

        # If not found in managers, check users table
        # if not user:
        #     cur.execute("""
        #         UPDATE users
        #         SET email_verified = true
        #         WHERE email = %s
        #         RETURNING id, email, full_name, role
        #     """, (email,))

        #     user = cur.fetchone()
        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        # Delete the verification record
        cur.execute("DELETE FROM email_verification WHERE email = %s", (email,))

        # Create access token
        access_token_expires = timedelta(minutes=60)  # Adjust as needed
        access_token = create_access_token(
            data={"sub": email, "role": user["role"]},
            expires_delta=access_token_expires
        )

        conn.commit()

        # Send welcome email after successful verification
        try:
            welcome_sent = send_welcome_email(user["email"], user["full_name"], user["role"])
            if welcome_sent:
                logger.info(f"Welcome email sent successfully to {user['email']}")
            else:
                logger.warning(f"Failed to send welcome email to {user['email']}")
        except Exception as e:
            logger.error(f"Error sending welcome email to {user['email']}: {str(e)}")
            # Don't fail the verification if welcome email fails

        return {
            "message": "Email verified successfully",
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user["id"],
                "email": user["email"],
                "full_name": user["full_name"],
                "role": user["role"]
            }
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error verifying user email: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def register_manager_by_invitation(
        registration: ManagerRegistration,
        conn=None
):
    """Register a manager (Regional or Restaurant) using an invitation token"""
    try:
        # Verify the invitation token
        payload = verify_invitation_token(registration.token)
        email = payload.get("sub")
        invitation_id = payload.get("invitation_id")
        role = payload.get("role")

        if not email or not invitation_id or role not in [RoleType.REGIONAL_MANAGER, RoleType.RESTAURANT_MANAGER]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid invitation token"
            )

        cur = conn.cursor()

        # Check if the invitation exists and is not used
        cur.execute("""
            SELECT 
                id, 
                email, 
                full_name, 
                phone_number, 
                role, 
                created_by, 
                expires_at, 
                restaurant_ids
            FROM manager_invitations 
            WHERE id = %s AND email = %s AND used = false AND expires_at > CURRENT_TIMESTAMP
        """, (invitation_id, email))

        invitation = cur.fetchone()
        if not invitation:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired invitation"
            )

        # Check if email is already registered
        cur.execute("SELECT id FROM managers WHERE email = %s", (email,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Email already registered")

        # Get regional_manager_id if this is a Restaurant Manager
        regional_manager_id = None
        if invitation["role"] == RoleType.RESTAURANT_MANAGER:
            # Check if column exists
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='manager_invitations' AND column_name='regional_manager_id'
            """)

            if cur.fetchone():
                # Get regional_manager_id from invitation
                cur.execute("""
                    SELECT regional_manager_id 
                    FROM manager_invitations 
                    WHERE id = %s
                """, (invitation_id,))

                result = cur.fetchone()
                if result and result["regional_manager_id"]:
                    regional_manager_id = result["regional_manager_id"]
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=f"No Regional Manager assigned to this Restaurant Manager invitation"
                    )
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Database schema is outdated. Please contact administrator."
                )

        # Create manager
        if invitation["role"] == RoleType.RESTAURANT_MANAGER:
            cur.execute("""
                INSERT INTO managers (
                    email, 
                    password_hash, 
                    role, 
                    created_by, 
                    email_verified,
                    full_name,
                    phone_number,
                    regional_manager_id
                )
                VALUES (%s, %s, %s, %s, true, %s, %s, %s)
                RETURNING *
            """, (
                email,
                get_password_hash(registration.password),
                invitation["role"],
                invitation["created_by"],
                invitation["full_name"],
                invitation["phone_number"],
                regional_manager_id
            ))
        else:
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
                VALUES (%s, %s, %s, %s, true, %s, %s)
                RETURNING *
            """, (
                email,
                get_password_hash(registration.password),
                invitation["role"],
                invitation["created_by"],
                invitation["full_name"],
                invitation["phone_number"]
            ))

        manager = cur.fetchone()
        manager_id = manager["id"]

        # Assign restaurants and record in history
        assigned_restaurants = []
        for restaurant_id in invitation["restaurant_ids"]:
            # Create assignment
            cur.execute("""
                INSERT INTO restaurant_assignments (
                    manager_id, 
                    restaurant_id, 
                    assigned_by,
                    assigned_at
                )
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            """, (manager_id, restaurant_id, invitation["created_by"]))

            # Record in assignment history
            cur.execute("""
                INSERT INTO restaurant_assignment_history (
                    restaurant_id,
                    manager_id,
                    assigned_by,
                    assigned_at
                )
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            """, (restaurant_id, manager_id, invitation["created_by"]))

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

        # Mark invitation as used
        cur.execute("""
            UPDATE manager_invitations 
            SET used = true 
            WHERE id = %s
        """, (invitation_id,))

        # Create free trial subscription for managers
        from src.subscription_management import SubscriptionManager
        
        try:
            subscription_result = await SubscriptionManager.create_free_trial(manager_id, conn)
            logger.info(f"Free trial subscription created successfully for manager {manager_id}")
        except Exception as e:
            logger.error(f"Failed to create free trial subscription for manager {manager_id}: {str(e)}")
            # Don't fail the registration if subscription creation fails
            subscription_result = None

        from src.settings_and_integrations import get_notification_settings
        await get_notification_settings(manager, conn)

        await create_notification(
            user_id=manager_id,
            title="Account Verified!",
            message="Manager registered and verified successfully!",
            type="info",
            cat="account",
            conn=conn
        )

        response_data = {
            "message": f"{invitation['role']} registered successfully.",
            "manager": {
                "id": manager_id,
                "email": email,
                "full_name": invitation["full_name"],
                "role": invitation["role"],
                "phone_number": invitation["phone_number"],
                "email_verified": True,
                "assigned_restaurants": assigned_restaurants
            }
        }

        # Add subscription info to response if creation was successful
        if subscription_result:
            response_data["subscription_created"] = True
            response_data["subscription_id"] = subscription_result
        else:
            response_data["subscription_created"] = False
            response_data["subscription_note"] = "Free trial subscription will be created on first login"

        # Include regional_manager_id in response if it's a Restaurant Manager
        if invitation["role"] == RoleType.RESTAURANT_MANAGER and regional_manager_id:
            response_data["manager"]["regional_manager_id"] = regional_manager_id

            # Get regional manager details
            cur.execute("""
                SELECT email, full_name 
                FROM managers 
                WHERE id = %s
            """, (regional_manager_id,))

            rm = cur.fetchone()
            if rm:
                response_data["manager"]["regional_manager"] = {
                    "id": regional_manager_id,
                    "email": rm["email"],
                    "full_name": rm["full_name"]
                }

        conn.commit()

        # Send welcome email after successful registration
        try:
            welcome_sent = send_welcome_email(
                email,
                invitation["full_name"],
                invitation["role"]
            )
            if welcome_sent:
                logger.info(f"Welcome email sent successfully to {email}")
            else:
                logger.warning(f"Failed to send welcome email to {email}")
        except Exception as e:
            logger.error(f"Error sending welcome email to {email}: {str(e)}")
            # Don't fail the registration if welcome email fails

        return response_data
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error registering manager by invitation: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


from src.chat_gpt import hard_delete_restaurant


#async def delete_current_user(current_user: dict, conn=None):
#    """
#    Permanently delete the current user based on their role.
#    For non-operators, delete from users table.
#    For managers, delete from managers table.
#    All related records and assignments will be deleted first.
#    """
#    if not conn:
#        raise HTTPException(status_code=500, detail="Database connection not available")
#
#    try:
#        cur = conn.cursor()
#        user_role = current_user.get("role")
#        user_id = current_user.get("id")
#        user_email = current_user.get("email")
#
#        if not user_id or not user_email:
#            raise HTTPException(status_code=400, detail="Invalid user information")
#        if user_role == "SUPER_ADMIN":
#            raise HTTPException(status_code=400, detail="SUPER_ADMIN user cannot be deleted")
#
#        # Handle non-operator users
#        if user_role == "Non_Operators":
#            # Check if user exists
#            cur.execute("""
#                SELECT id, email FROM managers 
#                WHERE id = %s
#            """, (user_id,))
#
#            if not cur.fetchone():
#                raise HTTPException(status_code=404, detail="User not found")
#
#            # Delete any email verification records
#            cur.execute("DELETE FROM email_verification WHERE email = %s", (user_email,))
#
#            # Delete chat history for this user
#            cur.execute("DELETE FROM chat_history_claude WHERE user_id = %s", (user_id,))
#            cur.execute("DELETE FROM chat_history_openai WHERE user_id = %s", (user_id,))
#
#            # Delete any text notes created by this user
#            cur.execute("DELETE FROM text_notes WHERE user_email = %s", (user_email,))
#
#            # Finally, delete the user completely
#            cur.execute("""
#                DELETE FROM managers 
#                WHERE id = %s
#                RETURNING id, email
#            """, (user_id,))
#
#            deleted_user = cur.fetchone()
#            if not deleted_user:
#                raise HTTPException(status_code=404, detail="Failed to delete user")
#
#            conn.commit()
#
#            return {
#                "message": f"User account {deleted_user['email']} has been permanently deleted",
#                "user_id": deleted_user["id"]
#            }
#
#        # Handle manager users (SUPER_ADMIN, Regional Manager, Restaurant Manager)
#        else:
#            # Check if manager exists
#            cur.execute("""
#                SELECT 
#                    id,
#                    email,
#                    role
#                FROM managers 
#                WHERE id = %s
#            """, (user_id,))
#
#            manager = cur.fetchone()
#            if not manager:
#                raise HTTPException(status_code=404, detail="Manager not found")
#
#            # Get assigned restaurants before deletion
#            cur.execute("""
#                SELECT r.id, r.name
#                FROM restaurants r
#                JOIN restaurant_assignments ra ON r.id = ra.restaurant_id
#                WHERE ra.manager_id = %s
#            """, (user_id,))
#
#            assigned_restaurants = [{"id": row["id"], "name": row["name"]} for row in cur.fetchall()]
#
#            # Delete manager's OTPs
#            cur.execute("DELETE FROM manager_otps WHERE manager_id = %s", (user_id,))
#
#            # Delete manager's invitations
#            cur.execute("DELETE FROM manager_invitations WHERE created_by = %s", (user_id,))
#
#            # Delete from restaurant_assignment_history where this manager is involved
#            cur.execute("""
#                DELETE FROM restaurant_assignment_history 
#                WHERE manager_id = %s OR assigned_by = %s OR unassigned_by = %s
#            """, (user_id, user_id, user_id))
#
#            # Delete restaurant assignments
#            cur.execute("DELETE FROM restaurant_assignments WHERE manager_id = %s", (user_id,))
#
#            # Delete chat history for this manager
#            cur.execute("DELETE FROM chat_history_claude WHERE user_id = %s", (user_id,))
#            cur.execute("DELETE FROM chat_history_openai WHERE user_id = %s", (user_id,))
#
#            # Delete any text notes created by this manager
#            cur.execute("DELETE FROM text_notes WHERE user_email = %s", (user_email,))
#
#            # If this is a restaurant manager, check if they created any restaurants
#            if manager["role"] in ("Restaurant Manager", "Regional Manager", "Restaurant Owner"):
#
#                # Get restaurants created by this manager
#                cur.execute("""
#                    SELECT id, name FROM restaurants WHERE created_by = %s
#                """, (user_id,))
#
#                created_restaurants = [{"id": row["id"], "name": row["name"]} for row in cur.fetchall()]
#
#                # For each restaurant created by this manager, delete related data
#                for restaurant in created_restaurants:
#                    # Delete restaurant-related data from various tables
#                    restaurant_id = restaurant["id"]
#
#                    await hard_delete_restaurant(
#                        restaurant_id,
#                        current_user,
#                        conn
#                    )
#
#                    # Delete all assignments for this restaurant
#                    cur.execute("DELETE FROM restaurant_assignments WHERE restaurant_id = %s", (restaurant_id,))
#
#                    # Delete assignment history for this restaurant
#                    cur.execute("DELETE FROM restaurant_assignment_history WHERE restaurant_id = %s", (restaurant_id,))
#
#                # Finally delete the restaurants created by this manager
#                if created_restaurants:
#                    restaurant_ids = [r["id"] for r in created_restaurants]
#                    placeholders = ','.join(['%s'] * len(restaurant_ids))
#                    cur.execute(f"DELETE FROM restaurants WHERE id IN ({placeholders})", restaurant_ids)
#
#            cur.execute("""
#                SELECT id FROM managers WHERE created_by = %s
#            """, (user_id,))
#
#            created_users = cur.fetchone()
#
#            if created_users:
#                # Delete all users created by this manager
#                logger.info(f"Deleting users created by manager {user_id}")
#                # Delete any email verification records for these users
#                cur.execute("DELETE FROM managers WHERE id = %s", (created_users["id"],))
#
#                # Delete chat history for these users
#                cur.execute("DELETE FROM chat_history_claude WHERE user_id = %s", (created_users["id"],))
#                cur.execute("DELETE FROM chat_history_openai WHERE user_id = %s", (created_users["id"],))
#
#                # Delete any text notes created by these users
#                # cur.execute("DELETE FROM text_notes WHERE user_email = %s", (created_users["email"],))
#
#            # Finally, delete the manager completely
#            cur.execute("""
#                DELETE FROM managers 
#                WHERE id = %s
#                RETURNING id, email, role
#            """, (user_id,))
#
#            deleted_manager = cur.fetchone()
#            if not deleted_manager:
#                raise HTTPException(status_code=404, detail="Failed to delete manager")
#
#            conn.commit()
#
#            return {
#                "message": f"Manager account {deleted_manager['email']} has been permanently deleted",
#                "user_id": deleted_manager["id"],
#                "role": deleted_manager["role"],
#                "affected_restaurants": [r["name"] for r in assigned_restaurants]
#            }
#
#    except HTTPException:
#        conn.rollback()
#        raise
#    except Exception as e:
#        conn.rollback()
#        logger.error(f"Error deleting user: {str(e)}")
#        raise HTTPException(status_code=500, detail=f"Error deleting user: {str(e)}")

import traceback  # Add this to your imports at the top if not already there

async def delete_current_user(current_user: dict, conn) -> dict:
    """
    Permanently delete current user's account and all related data.
    Handles all foreign key constraints properly.
    """
    try:
        cur = conn.cursor()
        user_id = current_user["id"]
        user_email = current_user["email"]
        user_role = current_user.get("role")
        
        logger.info(f"Starting deletion process for user {user_id} ({user_email})")
        
        # Don't allow SUPER_ADMIN deletion
        if user_role == "SUPER_ADMIN":
            raise HTTPException(
                status_code=403,
                detail="SUPER_ADMIN accounts cannot be deleted"
            )
        
        # Helper function to check if table exists
        def table_exists(table_name):
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = %s
                );
            """, (table_name,))
            return cur.fetchone()['exists']
        
        # 1. First handle critical deletions that must succeed
        try:
            # Delete restaurant_kpi_graphs created by this user
            cur.execute("""
                DELETE FROM restaurant_kpi_graphs 
                WHERE created_by = %s
            """, (user_id,))
            deleted_count = cur.rowcount
            logger.info(f"Deleted {deleted_count} KPI graphs created by user {user_id}")
            
            # If user is a Restaurant Owner, also delete KPI graphs for their restaurants
            if user_role == "Restaurant Owner":
                cur.execute("""
                    DELETE FROM restaurant_kpi_graphs 
                    WHERE restaurant_id IN (
                        SELECT id FROM restaurants WHERE created_by = %s
                    )
                """, (user_id,))
                deleted_count = cur.rowcount
                logger.info(f"Deleted {deleted_count} KPI graphs for restaurants owned by user {user_id}")
            
            # Commit critical deletions
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to delete KPI graphs: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete user data (KPI graphs): {str(e)}"
            )
        
        # 2. Delete from all dependent tables (check existence first)
        tables_to_clean = [
            ('subscriptions', 'user_id'),
            ('user_notification_settings', 'user_id'),
            ('notifications', 'user_id'),
            ('chat_history_claude', 'user_id'),
            ('chat_history_openai', 'user_id'),
            ('notes', 'user_id'),
            ('text_notes', 'user_email', user_email),  # This uses email instead of user_id
            ('audit_log', 'performed_by'),
            ('manager_otps', 'manager_id'),
            ('email_verification', 'email', user_email),  # This uses email
        ]
        
        for table_name, column_name, *value in tables_to_clean:
            try:
                if table_exists(table_name):
                    # Use provided value or default to user_id
                    delete_value = value[0] if value else user_id
                    cur.execute(f"DELETE FROM {table_name} WHERE {column_name} = %s", (delete_value,))
                    count = cur.rowcount
                    if count > 0:
                        logger.info(f"Deleted {count} records from {table_name}")
                else:
                    logger.info(f"Table {table_name} does not exist, skipping")
            except Exception as e:
                logger.warning(f"Could not delete from {table_name}: {e}")
                # Don't stop, continue with other deletions
        
        # Commit non-critical deletions
        try:
            conn.commit()
        except:
            conn.rollback()
        
        # 3. Handle manager invitations
        try:
            if table_exists('manager_invitations'):
                cur.execute("""
                    DELETE FROM manager_invitations 
                    WHERE created_by = %s OR regional_manager_id = %s
                """, (user_id, user_id))
                logger.info(f"Deleted invitations for user {user_id}")
                conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning(f"Could not delete invitations: {e}")
        
        # 4. Handle restaurant assignments
        try:
            if table_exists('restaurant_assignment_history'):
                cur.execute("""
                    DELETE FROM restaurant_assignment_history 
                    WHERE manager_id = %s OR assigned_by = %s OR unassigned_by = %s
                """, (user_id, user_id, user_id))
            
            if table_exists('restaurant_assignments'):
                cur.execute("""
                    DELETE FROM restaurant_assignments 
                    WHERE manager_id = %s OR assigned_by = %s
                """, (user_id, user_id))
            
            logger.info(f"Deleted restaurant assignments for user {user_id}")
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning(f"Error deleting assignments: {e}")
        
        # 5. Handle restaurants if user is Restaurant Owner
        if user_role == "Restaurant Owner":
            try:
                # Get all restaurants created by this user
                cur.execute("""
                    SELECT id, name FROM restaurants 
                    WHERE created_by = %s
                """, (user_id,))
                owned_restaurants = cur.fetchall()
                
                for restaurant in owned_restaurants:
                    restaurant_id = restaurant['id']
                    restaurant_name = restaurant['name']
                    
                    try:
                        # Delete all related data for each restaurant
                        tables_to_clean_for_restaurant = [
                            ('hours_of_operation', 'restaurant_id', restaurant_id),
                            ('notifications', 'restaurant_id', restaurant_id),
                            ('restaurant_assignment_history', 'restaurant_id', restaurant_id),
                            ('restaurant_assignments', 'restaurant_id', restaurant_id),
                            ('openai_embeddings', 'restaurant_name', restaurant_name),
                            ('claude_embeddings', 'restaurant_name', restaurant_name),
                        ]
                        
                        for table, column, value in tables_to_clean_for_restaurant:
                            if table_exists(table):
                                cur.execute(f"DELETE FROM {table} WHERE {column} = %s", (value,))
                        
                        # Delete the restaurant itself
                        cur.execute("DELETE FROM restaurants WHERE id = %s", (restaurant_id,))
                        logger.info(f"Deleted restaurant {restaurant_name} (ID: {restaurant_id})")
                        
                        # Commit after each restaurant
                        conn.commit()
                        
                    except Exception as e:
                        logger.error(f"Error deleting restaurant {restaurant_name}: {e}")
                        conn.rollback()
                
            except Exception as e:
                conn.rollback()
                logger.warning(f"Error handling owned restaurants: {e}")
        
        # 6. Update foreign key references (set to NULL)
        try:
            update_queries = [
                ("UPDATE restaurants SET deactivated_by = NULL WHERE deactivated_by = %s", (user_id,)),
                ("UPDATE managers SET created_by = NULL WHERE created_by = %s", (user_id,)),
                ("UPDATE managers SET regional_manager_id = NULL WHERE regional_manager_id = %s", (user_id,)),
            ]
            
            # Only update created_by for restaurants if not a Restaurant Owner
            if user_role != "Restaurant Owner":
                update_queries.append(
                    ("UPDATE restaurants SET created_by = NULL WHERE created_by = %s", (user_id,))
                )
            
            for query, params in update_queries:
                try:
                    cur.execute(query, params)
                except Exception as e:
                    logger.warning(f"Could not execute update: {e}")
            
            conn.commit()
            logger.info(f"Updated all foreign key references for user {user_id}")
            
        except Exception as e:
            conn.rollback()
            logger.warning(f"Error updating references: {e}")
        
        # 7. Clean up S3 files (non-critical)
        try:
            # Import S3 client
            try:
                from src.chat_gpt import s3_client, BUCKET_NAME
            except ImportError:
                logger.warning("Could not import S3 client")
                s3_client = None
                BUCKET_NAME = None
            
            if s3_client and BUCKET_NAME:
                # Delete profile image from S3
                if current_user.get('profile_image'):
                    user_folder = f"user_{user_id}"
                    s3_key = f"uploads/profile_images/{user_folder}/{current_user['profile_image']}"
                    try:
                        s3_client.delete_object(Bucket=BUCKET_NAME, Key=s3_key)
                        logger.info(f"Deleted profile image from S3")
                    except Exception as e:
                        logger.warning(f"Could not delete S3 profile image: {e}")
                
                # Delete audio files
                safe_email = user_email.replace('@', '_at_')
                audio_prefix = f"uploads/users/{user_id}_{safe_email}_{user_role}/audio/"
                
                try:
                    response = s3_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=audio_prefix)
                    if 'Contents' in response:
                        for obj in response['Contents']:
                            s3_client.delete_object(Bucket=BUCKET_NAME, Key=obj['Key'])
                        logger.info(f"Deleted audio files from S3")
                except Exception as e:
                    logger.warning(f"Could not delete S3 audio files: {e}")
                    
        except Exception as e:
            logger.warning(f"S3 cleanup error (non-critical): {e}")
        
        # 8. Finally, delete the user from managers table
        try:
            cur.execute("""
                DELETE FROM managers 
                WHERE id = %s
                RETURNING email, full_name
            """, (user_id,))
            
            deleted_user = cur.fetchone()
            
            if deleted_user:
                # Final commit
                conn.commit()
                
                logger.info(f"Successfully deleted user account: {deleted_user['email']} (ID: {user_id})")
                
                return {
                    "message": "Account successfully deleted",
                    "deleted_user": {
                        "email": deleted_user['email'],
                        "full_name": deleted_user['full_name'],
                        "user_id": user_id
                    }
                }
            else:
                conn.rollback()
                raise HTTPException(
                    status_code=404,
                    detail="User not found or already deleted"
                )
                
        except HTTPException:
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to delete user from managers table: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to complete user deletion: {str(e)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error deleting user: {str(e)}")
        logger.error(f"Full error traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting user: {str(e)}"
        )


async def forgot_password_non_operator(request: OTPRequest, conn=None):
    """
    Generate and send OTP for password reset for non-operator users

    Args:
        request: OTPRequest containing the email
        conn: Database connection

    Returns:
        Message indicating if OTP was sent successfully
    """
    try:
        cur = conn.cursor()

        # Check if user exists and is active
        cur.execute("""
            SELECT id, email
            FROM managers 
            WHERE email = %s AND active = true
        """, (request.email,))

        user = cur.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found or account is inactive")

        # Generate password reset OTP
        otp = generate_otp()
        otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

        try:
            # Optional: Check if the email exists
            cur.execute("SELECT 1 FROM email_verification WHERE email = %s", (request.email,))
            if cur.fetchone():
                cur.execute("DELETE FROM email_verification WHERE email = %s", (request.email,))

                logger.info(f"Email verification record for {request.email} deleted successfully.")
            else:
                logger.info(f"No email verification record found for {request.email}.")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error deleting email verification record: {str(e)}")

        # Ensure email_verification table exists
        # cur.execute("""
        #     CREATE TABLE IF NOT EXISTS email_verification (
        #         id SERIAL PRIMARY KEY,
        #         email VARCHAR(255) UNIQUE NOT NULL,
        #         otp VARCHAR(10) NOT NULL,
        #         expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
        #         created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        #     )
        # """)

        # Add purpose column if it doesn't exist
        # cur.execute("""
        #     DO $$
        #     BEGIN
        #         IF NOT EXISTS (
        #             SELECT column_name
        #             FROM information_schema.columns
        #             WHERE table_name='email_verification' AND column_name='purpose'
        #         ) THEN
        #             ALTER TABLE email_verification ADD COLUMN purpose VARCHAR(20) DEFAULT 'verification';
        #         END IF;
        #     END $$;
        # """)

        # Store OTP for password reset
        cur.execute("""
            INSERT INTO email_verification (email, otp, expires_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (email) 
            DO UPDATE SET 
                otp = EXCLUDED.otp,
                expires_at = EXCLUDED.expires_at,

                created_at = CURRENT_TIMESTAMP
        """, (request.email, otp, otp_expires_at))

        # Send password reset email
        sent = send_password_reset_email(request.email, otp)

        if sent:
            conn.commit()
            return {"message": "Password reset OTP sent successfully"}
        else:
            conn.rollback()
            raise HTTPException(status_code=500, detail="Failed to send password reset email")

    except HTTPException:
        conn.rollback() if conn else None
        raise
    except Exception as e:
        conn.rollback() if conn else None
        logger.error(f"Error in forgot password for non-operator: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error in forgot password: {str(e)}")


async def reset_password_non_operator(email: str, otp: str, new_password: str, conn=None):
    """
    Reset password for non-operator users using OTP

    Args:
        email: User's email
        otp: One-time password received via email
        new_password: New password to set
        conn: Database connection

    Returns:
        Message indicating password was reset successfully
    """
    try:
        cur = conn.cursor()

        # Validate the OTP
        cur.execute("""
            SELECT * FROM email_verification
            WHERE email = %s 
            AND otp = %s 

            AND expires_at > NOW()
        """, (email, otp))

        verification = cur.fetchone()
        if not verification:
            raise HTTPException(status_code=400, detail="Invalid or expired OTP")

        # Hash the new password
        password_hash = get_password_hash(new_password)

        # Update the user's password
        cur.execute("""
            UPDATE managers 
            SET password_hash = %s
            WHERE email = %s AND active = true
            RETURNING id
        """, (password_hash, email))

        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found or account is inactive")

        # Delete the verification record
        cur.execute("""
            DELETE FROM email_verification 
            WHERE email = %s 
        """, (email,))

        conn.commit()
        return {"message": "Password reset successfully"}

    except HTTPException:
        conn.rollback() if conn else None
        raise
    except Exception as e:
        conn.rollback() if conn else None
        logger.error(f"Error in reset password for non-operator: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error in reset password: {str(e)}")

