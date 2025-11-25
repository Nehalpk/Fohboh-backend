#from fastapi import APIRouter, Depends, HTTPException, status
#from pydantic import BaseModel, Field
#from typing import List, Dict, Any, Optional
#import logging
#import psycopg2
#from psycopg2.extras import RealDictCursor
#import json
#import uuid
#from datetime import datetime
#from src.chat_gpt import get_current_user, get_db, DB_CONFIG
#from src.subscription_management import update_usage
#
## Configure logging
#logging.basicConfig(level=logging.INFO)
#logger = logging.getLogger(__name__)
#
## Router
#router = APIRouter(prefix="/settings", tags=["Settings and Integrations"])
#
#
## Models
#class IntegrationCreate(BaseModel):
#    name: str = Field(..., description="Integration name", min_length=1, max_length=100)
#    api_key: str = Field(..., description="API key for the integration")
#
#
#class IntegrationResponse(BaseModel):
#    id: int
#    name: str
#    api_key: str
#    enabled: bool
#    created_at: datetime
#
#
#class IntegrationUpdate(BaseModel):
#    name: Optional[str] = Field(None, description="Integration name", min_length=1, max_length=100)
#    api_key: Optional[str] = Field(None, description="API key for the integration")
#    enabled: Optional[bool] = Field(None, description="Whether the integration is enabled")
#
#
## Database Functions
#def init_settings_tables():
#    """Initialize the database tables for settings, integrations, and staff if they don't exist"""
#    conn = None
#    try:
#        conn = psycopg2.connect(**DB_CONFIG)
#        cur = conn.cursor()
#
#        # Create table for system integrations
#        cur.execute("""
#        CREATE TABLE IF NOT EXISTS integrations (
#            id SERIAL PRIMARY KEY,
#            user_id INTEGER REFERENCES managers(id) ON DELETE CASCADE,
#            name VARCHAR(100) NOT NULL,
#            api_key TEXT NOT NULL,
#            enabled BOOLEAN DEFAULT true,
#            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
#        )
#        """)
#
#        # Create table for staff information
#        cur.execute("""
#        CREATE TABLE IF NOT EXISTS staff_info (
#            id SERIAL PRIMARY KEY,
#            restaurant_id INTEGER NOT NULL,
#            employee_id INTEGER NOT NULL,
#            name TEXT NOT NULL,
#            role TEXT NOT NULL,
#            hire_date DATE NOT NULL,
#            termination_date DATE,
#            hourly_rate DECIMAL(10, 2),
#            profile_image TEXT,
#            contact_number TEXT,
#            email TEXT,
#            address TEXT,
#            emergency_contact TEXT,
#            notes TEXT,
#            filename TEXT NOT NULL,
#            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
#            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
#            UNIQUE(restaurant_id, employee_id)
#        )
#        """)
#
#        # Create index for faster queries
#        cur.execute("""
#        CREATE INDEX IF NOT EXISTS staff_info_restaurant_id_idx 
#        ON staff_info(restaurant_id)
#        """)
#
#        conn.commit()
#        logger.info("Settings and staff tables initialized successfully")
#
#
#    except Exception as e:
#        if conn:
#            conn.rollback()
#        logger.error(f"Error initializing settings tables: {str(e)}")
#        raise
#    finally:
#        if conn:
#            cur.close()
#            conn.close()
#
#
## API Routes
#
## Integration management endpoints
#@router.post("/integrations/create", response_model=IntegrationResponse, status_code=status.HTTP_201_CREATED)
#async def create_integration(
#        integration: IntegrationCreate,
#        current_user: dict = Depends(get_current_user),
#        db=Depends(get_db)
#):
#    """
#    Create a new integration with API key
#    Only accessible to super admins
#    """
#    # Check if user is a Operators
#    if current_user["role"] != "SUPER_ADMIN":
#        raise HTTPException(
#            status_code=status.HTTP_403_FORBIDDEN,
#            detail="Only SUPER_ADMIN can manage integrations"
#        )
#
#    try:
#        cur = db.cursor(cursor_factory=RealDictCursor)
#
#        # Check if integration with this name already exists
#        cur.execute(
#            "SELECT id FROM integrations WHERE name = %s AND user_id = %s",
#            (integration.name, current_user["id"])
#        )
#
#        if cur.fetchone():
#            raise HTTPException(
#                status_code=status.HTTP_409_CONFLICT,
#                detail=f"Integration with name '{integration.name}' already exists"
#            )
#
#        # Insert new integration
#        cur.execute(
#            """
#            INSERT INTO integrations (name, api_key, user_id)
#            VALUES (%s, %s, %s)
#            RETURNING id, name, api_key, enabled, created_at
#            """,
#            (integration.name, integration.api_key, current_user["id"])
#        )
#
#        new_integration = cur.fetchone()
#        db.commit()
#
#        resulted = await update_usage(
#            current_user=current_user,
#            conn=db,
#            used_integrations=True,
#        )
#
#        logger.info(f"Integration '{integration.name}' created by {current_user['email']}")
#        return new_integration
#
#    except HTTPException:
#        db.rollback()
#        raise
#    except Exception as e:
#        db.rollback()
#        logger.error(f"Error creating integration: {str(e)}")
#        raise HTTPException(
#            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#            detail=f"Failed to create integration: {str(e)}"
#        )
#
#
#@router.get("/integrations", response_model=List[IntegrationResponse])
#async def get_integrations(
#        current_user: dict = Depends(get_current_user),
#        db=Depends(get_db)
#):
#    """
#    Get all integrations
#    Only accessible to super admins
#    """
#    # Check if user is a Operators
#    allowed_roles = ["SUPER_ADMIN", "Restaurant Owner", "Restaurant Manager"]
#    if current_user["role"] not in allowed_roles:
#        raise HTTPException(
#            status_code=status.HTTP_403_FORBIDDEN,
#            detail="You do not have permission to manage integrations"
#        )
#
#    try:
#        cur = db.cursor(cursor_factory=RealDictCursor)
#        cur.execute(
#            """
#            SELECT id, name, api_key, enabled, created_at
#            FROM integrations
#            WHERE user_id = %s
#            ORDER BY created_at DESC
#            """, (current_user["id"],)
#        )
#
#        integrations = cur.fetchall()
#        return integrations
#
#    except Exception as e:
#        logger.error(f"Error fetching integrations: {str(e)}")
#        raise HTTPException(
#            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#            detail=f"Failed to fetch integrations: {str(e)}"
#        )
#
#
#@router.put("/integrations/{integration_id}", response_model=IntegrationResponse)
#async def update_integration(
#        integration_id: int,
#        integration: IntegrationUpdate,
#        current_user: dict = Depends(get_current_user),
#        db=Depends(get_db)
#):
#    """
#    Update an existing integration
#    Only accessible to super admins
#    """
#    # Check if user is a Operators
#    if current_user["role"] == "Non_Operators":
#        raise HTTPException(
#            status_code=status.HTTP_403_FORBIDDEN,
#            detail="Only Operators can manage integrations"
#        )
#
#    try:
#        cur = db.cursor(cursor_factory=RealDictCursor)
#
#        # Check if integration exists
#        cur.execute(
#            "SELECT id FROM integrations WHERE id = %s",
#            (integration_id,)
#        )
#
#        if not cur.fetchone():
#            raise HTTPException(
#                status_code=status.HTTP_404_NOT_FOUND,
#                detail=f"Integration with ID {integration_id} not found"
#            )
#
#        # Build update query dynamically based on provided fields
#        update_fields = []
#        params = []
#
#        if integration.name is not None:
#            update_fields.append("name = %s")
#            params.append(integration.name)
#
#        if integration.api_key is not None:
#            update_fields.append("api_key = %s")
#            params.append(integration.api_key)
#
#        if integration.enabled is not None:
#            update_fields.append("enabled = %s")
#            params.append(integration.enabled)
#
#        if not update_fields:
#            # No fields to update
#            cur.execute(
#                """
#                SELECT id, name, api_key, enabled, created_at
#                FROM integrations
#                WHERE id = %s
#                """,
#                (integration_id,)
#            )
#            return cur.fetchone()
#
#        # Add integration_id to params
#        params.append(integration_id)
#
#        # Execute update query
#        cur.execute(
#            f"""
#            UPDATE integrations
#            SET {", ".join(update_fields)}
#            WHERE id = %s
#            RETURNING id, name, api_key, enabled, created_at
#            """,
#            tuple(params)
#        )
#
#        updated_integration = cur.fetchone()
#        db.commit()
#
#        logger.info(f"Integration ID {integration_id} updated by {current_user['email']}")
#        return updated_integration
#
#    except HTTPException:
#        db.rollback()
#        raise
#    except Exception as e:
#        db.rollback()
#        logger.error(f"Error updating integration: {str(e)}")
#        raise HTTPException(
#            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#            detail=f"Failed to update integration: {str(e)}"
#        )
#
#
#@router.delete("/integrations/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
#async def delete_integration(
#        integration_id: int,
#        current_user: dict = Depends(get_current_user),
#        db=Depends(get_db)
#):
#    """
#    Delete an integration
#    Only accessible to super admins
#    """
#    # Check if user is a Operators
#    if current_user["role"] == "Non_Operators":
#        raise HTTPException(
#            status_code=status.HTTP_403_FORBIDDEN,
#            detail="Only Operators can manage integrations"
#        )
#
#    try:
#        cur = db.cursor()
#
#        # Check if integration exists
#        cur.execute(
#            "SELECT id FROM integrations WHERE id = %s",
#            (integration_id,)
#        )
#
#        if not cur.fetchone():
#            raise HTTPException(
#                status_code=status.HTTP_404_NOT_FOUND,
#                detail=f"Integration with ID {integration_id} not found"
#            )
#
#        # Delete the integration
#        cur.execute(
#            "DELETE FROM integrations WHERE id = %s",
#            (integration_id,)
#        )
#
#        db.commit()
#
#        logger.info(f"Integration ID {integration_id} deleted by {current_user['email']}")
#        return None
#
#    except HTTPException:
#        db.rollback()
#        raise
#    except Exception as e:
#        db.rollback()
#        logger.error(f"Error deleting integration: {str(e)}")
#        raise HTTPException(
#            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#            detail=f"Failed to delete integration: {str(e)}"
#        )
#
#
## Staff Models
#class StaffResponse(BaseModel):
#    id: int
#    employee_id: int
#    name: str
#    role: str
#    hire_date: datetime
#    termination_date: Optional[datetime] = None
#    hourly_rate: float
#    profile_image: Optional[str] = None
#    contact_number: Optional[str] = None
#    email: Optional[str] = None
#    address: Optional[str] = None
#    emergency_contact: Optional[str] = None
#    notes: Optional[str] = None
#    created_at: datetime
#    updated_at: datetime
#
#
## Staff Endpoints
#@router.get("/staff/{restaurant_name}", response_model=List[StaffResponse])
#async def get_restaurant_staff(
#        restaurant_name: str,
#        current_user: dict = Depends(get_current_user),
#        db=Depends(get_db)
#):
#    """
#    Get all staff members for a specific restaurant.
#    Access is based on user role:
#    - SUPER_ADMIN: Can view staff for any restaurant
#    - Restaurant Owner: Can view staff for restaurants they created
#    - Regional/Restaurant Manager: Can view staff for assigned restaurants
#    """
#    try:
#        cur = db.cursor(cursor_factory=RealDictCursor)
#
#        # Different query based on user role
#        if current_user["role"] == "SUPER_ADMIN":
#            # SUPER_ADMIN can access any restaurant's staff
#            cur.execute("""
#                SELECT s.*, r.name as restaurant_name
#                FROM staff_info s
#                JOIN restaurants r ON s.restaurant_id = r.id
#                WHERE r.name = %s AND r.active = true
#                ORDER BY s.name
#            """, (restaurant_name,))
#
#        elif current_user["role"] == "Restaurant Owner":
#            # Restaurant owners can only access their own restaurants' staff
#            cur.execute("""
#                SELECT s.*, r.name as restaurant_name
#                FROM staff_info s
#                JOIN restaurants r ON s.restaurant_id = r.id
#                WHERE r.name = %s AND r.active = true AND r.created_by = %s
#                ORDER BY s.name
#            """, (restaurant_name, current_user["id"]))
#
#        else:
#            # Regional and Restaurant managers can only access assigned restaurants' staff
#            cur.execute("""
#                SELECT s.*, r.name as restaurant_name
#                FROM staff_info s
#                JOIN restaurants r ON s.restaurant_id = r.id
#                JOIN restaurant_assignments ra ON r.id = ra.restaurant_id
#                WHERE r.name = %s AND r.active = true AND ra.manager_id = %s
#                ORDER BY s.name
#            """, (restaurant_name, current_user["id"]))
#
#        staff = cur.fetchall()
#
#        if not staff:
#            # Check if restaurant exists but has no staff
#            cur.execute("""
#                SELECT id FROM restaurants WHERE name = %s AND active = true
#            """, (restaurant_name,))
#
#            if not cur.fetchone():
#                raise HTTPException(
#                    status_code=status.HTTP_404_NOT_FOUND,
#                    detail=f"Restaurant '{restaurant_name}' not found or you don't have access to it"
#                )
#
#        return staff
#
#    except HTTPException:
#        raise
#    except Exception as e:
#        logger.error(f"Error fetching staff data: {str(e)}")
#        raise HTTPException(
#            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#            detail=f"Failed to fetch staff data: {str(e)}"
#        )
#
#
#from psycopg2.extras import DictCursor
#
#
#@router.get("/staff/role-count/{restaurant_id}")
#def get_role_counts(restaurant_id: int, conn=Depends(get_db)):
#    try:
#        cur = conn.cursor(cursor_factory=DictCursor)
#        cur.execute("""
#            SELECT role, COUNT(*) AS count
#            FROM staff_info
#            WHERE restaurant_id = %s
#            GROUP BY role
#        """, (restaurant_id,))
#        results = cur.fetchall()
#        return [{"role": row["role"], "count": row["count"]} for row in results]
#    except Exception as e:
#        raise HTTPException(status_code=500, detail=f"Error retrieving role counts: {str(e)}")
#
#
#@router.get("/staff", response_model=Dict[str, List[StaffResponse]])
#async def get_all_staff(
#        current_user: dict = Depends(get_current_user),
#        db=Depends(get_db)
#):
#    """
#    Get all staff members grouped by restaurant.
#    Access is based on user role:
#    - SUPER_ADMIN: Can view staff for all restaurants
#    - Restaurant Owner: Can view staff for restaurants they created
#    - Regional/Restaurant Manager: Can view staff for assigned restaurants
#    """
#    try:
#        cur = db.cursor(cursor_factory=RealDictCursor)
#
#        # Different query based on user role
#        if current_user["role"] == "SUPER_ADMIN":
#            # SUPER_ADMIN can access all restaurants' staff
#            cur.execute("""
#                SELECT s.*, r.name as restaurant_name
#                FROM staff_info s
#                JOIN restaurants r ON s.restaurant_id = r.id
#                WHERE r.active = true
#                ORDER BY r.name, s.name
#            """)
#
#        elif current_user["role"] == "Restaurant Owner":
#            # Restaurant owners can only access their own restaurants' staff
#            cur.execute("""
#                SELECT s.*, r.name as restaurant_name
#                FROM staff_info s
#                JOIN restaurants r ON s.restaurant_id = r.id
#                WHERE r.active = true AND r.created_by = %s
#                ORDER BY r.name, s.name
#            """, (current_user["id"],))
#
#        else:
#            # Regional and Restaurant managers can only access assigned restaurants' staff
#            cur.execute("""
#                SELECT s.*, r.name as restaurant_name
#                FROM staff_info s
#                JOIN restaurants r ON s.restaurant_id = r.id
#                JOIN restaurant_assignments ra ON r.id = ra.restaurant_id
#                WHERE r.active = true AND ra.manager_id = %s
#                ORDER BY r.name, s.name
#            """, (current_user["id"],))
#
#        all_staff = cur.fetchall()
#
#        # Group staff by restaurant
#        staff_by_restaurant = {}
#        for staff_member in all_staff:
#            restaurant_name = staff_member.pop('restaurant_name')
#            if restaurant_name not in staff_by_restaurant:
#                staff_by_restaurant[restaurant_name] = []
#            staff_by_restaurant[restaurant_name].append(staff_member)
#
#        return staff_by_restaurant
#
#    except Exception as e:
#        logger.error(f"Error fetching all staff data: {str(e)}")
#        raise HTTPException(
#            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#            detail=f"Failed to fetch staff data: {str(e)}"
#        )
#
#
## Add these imports at the top if not already present
#from pydantic import BaseModel
#from typing import Optional
#
#
## Add these models after your existing models
#class NotificationSettingsResponse(BaseModel):
#    id: int
#    user_id: int
#    fraud_alerts: bool
#    account_notifications: bool
#    subscription_alerts: bool
#    file_processing_updates: bool
#    created_at: datetime
#    updated_at: datetime
#
#
#class NotificationSettingsUpdate(BaseModel):
#    fraud_alerts: Optional[bool] = None
#    account_notifications: Optional[bool] = None
#    subscription_alerts: Optional[bool] = None
#    file_processing_updates: Optional[bool] = None
#
#
## Add these new endpoints before init_settings_tables()
#@router.get("/notifications_settings", response_model=NotificationSettingsResponse)
#async def get_notification_settings(
#        current_user: dict = Depends(get_current_user),
#        db=Depends(get_db)
#):
#    """Get notification settings for the current user"""
#    try:
#        cur = db.cursor(cursor_factory=RealDictCursor)
#
#        # Check if settings exist for the user
#        cur.execute("""
#            SELECT * FROM user_notification_settings 
#            WHERE user_id = %s
#        """, (current_user["id"],))
#
#        settings = cur.fetchone()
#
#        # If no settings exist, create default settings
#        if not settings:
#            cur.execute("""
#                INSERT INTO user_notification_settings 
#                (user_id, fraud_alerts, account_notifications, 
#                subscription_alerts, file_processing_updates)
#                VALUES (%s, false, true, true, false)
#                RETURNING *
#            """, (current_user["id"],))
#            settings = cur.fetchone()
#            db.commit()
#
#        logger.info(f"Default notification settings created for user {current_user['email']}")
#
#        return settings
#
#    except Exception as e:
#        logger.error(f"Error fetching notification settings: {str(e)}")
#        raise HTTPException(
#            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#            detail=f"Failed to fetch notification settings: {str(e)}"
#        )
#
#
#@router.put("/notifications_settings", response_model=NotificationSettingsResponse)
#async def update_notification_settings(
#        settings: NotificationSettingsUpdate,
#        current_user: dict = Depends(get_current_user),
#        db=Depends(get_db)
#):
#    """Update notification settings for the current user"""
#    try:
#        cur = db.cursor(cursor_factory=RealDictCursor)
#
#        # Build update query dynamically based on provided fields
#        update_fields = []
#        params = []
#
#        if settings.fraud_alerts is not None:
#            update_fields.append("fraud_alerts = %s")
#            params.append(settings.fraud_alerts)
#
#        if settings.account_notifications is not None:
#            update_fields.append("account_notifications = %s")
#            params.append(settings.account_notifications)
#
#        if settings.subscription_alerts is not None:
#            update_fields.append("subscription_alerts = %s")
#            params.append(settings.subscription_alerts)
#
#        if settings.file_processing_updates is not None:
#            update_fields.append("file_processing_updates = %s")
#            params.append(settings.file_processing_updates)
#
#        if not update_fields:
#            # No fields to update, return current settings
#            cur.execute("""
#                SELECT * FROM user_notification_settings 
#                WHERE user_id = %s
#            """, (current_user["id"],))
#            return cur.fetchone()
#
#        # Add user_id and updated_at to params
#        params.append(current_user["id"])
#
#        # Execute update query
#        cur.execute(f"""
#            UPDATE user_notification_settings
#            SET {", ".join(update_fields)}, updated_at = CURRENT_TIMESTAMP
#            WHERE user_id = %s
#            RETURNING *
#        """, tuple(params))
#
#        updated_settings = cur.fetchone()
#
#        # If no settings were updated (user didn't have any), create new settings
#        if not updated_settings:
#            cur.execute("""
#                INSERT INTO user_notification_settings 
#                (user_id, fraud_alerts, account_notifications, 
#                subscription_alerts, file_processing_updates)
#                VALUES (%s, %s, %s, %s, %s)
#                RETURNING *
#            """, (
#                current_user["id"],
#                settings.fraud_alerts if settings.fraud_alerts is not None else True,
#                settings.account_notifications if settings.account_notifications is not None else True,
#                settings.subscription_alerts if settings.subscription_alerts is not None else True,
#                settings.file_processing_updates if settings.file_processing_updates is not None else True
#            ))
#            updated_settings = cur.fetchone()
#
#        db.commit()
#        logger.info(f"Notification settings updated for user {current_user['email']}")
#
#        return updated_settings
#
#    except Exception as e:
#        db.rollback()
#        logger.error(f"Error updating notification settings: {str(e)}")
#        raise HTTPException(
#            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#            detail=f"Failed to update notification settings: {str(e)}"
#        )
#
#
## Initialize the tables when module is imported
#init_settings_tables()
#
#------------------------------previous Implementations-----------------------------------#

#from fastapi import APIRouter, Depends, HTTPException, status
#from pydantic import BaseModel, Field
#from typing import List, Dict, Any, Optional
#import logging
#import psycopg2
#from psycopg2.extras import RealDictCursor
#import json
#import uuid
#from datetime import datetime
#from src.chat_gpt import get_current_user, get_db, DB_CONFIG
#from src.subscription_management import update_usage
#
## Configure logging
#logging.basicConfig(level=logging.INFO)
#logger = logging.getLogger(__name__)
#
## Router
#router = APIRouter(prefix="/settings", tags=["Settings and Integrations"])
#
#
## Models
#class IntegrationCreate(BaseModel):
#    name: str = Field(..., description="Integration name", min_length=1, max_length=100)
#    api_key: str = Field(..., description="API key for the integration")
#
#
#class IntegrationResponse(BaseModel):
#    id: int
#    name: str
#    api_key: str
#    enabled: bool
#    created_at: datetime
#
#
#class IntegrationUpdate(BaseModel):
#    name: Optional[str] = Field(None, description="Integration name", min_length=1, max_length=100)
#    api_key: Optional[str] = Field(None, description="API key for the integration")
#    enabled: Optional[bool] = Field(None, description="Whether the integration is enabled")
#
#
## Database Functions
#def init_settings_tables():
#    """Initialize the database tables for settings, integrations, and staff if they don't exist"""
#    conn = None
#    try:
#        conn = psycopg2.connect(**DB_CONFIG)
#        cur = conn.cursor()
#
#        # Create table for system integrations
#        cur.execute("""
#        CREATE TABLE IF NOT EXISTS integrations (
#            id SERIAL PRIMARY KEY,
#            user_id INTEGER REFERENCES managers(id) ON DELETE CASCADE,
#            name VARCHAR(100) NOT NULL,
#            api_key TEXT NOT NULL,
#            enabled BOOLEAN DEFAULT true,
#            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
#        )
#        """)
#
#        # Create table for staff information
#        cur.execute("""
#        CREATE TABLE IF NOT EXISTS staff_info (
#            id SERIAL PRIMARY KEY,
#            restaurant_id INTEGER NOT NULL,
#            employee_id INTEGER NOT NULL,
#            name TEXT NOT NULL,
#            role TEXT NOT NULL,
#            hire_date DATE NOT NULL,
#            termination_date DATE,
#            hourly_rate DECIMAL(10, 2),
#            profile_image TEXT,
#            contact_number TEXT,
#            email TEXT,
#            address TEXT,
#            emergency_contact TEXT,
#            notes TEXT,
#            filename TEXT NOT NULL,
#            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
#            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
#            UNIQUE(restaurant_id, employee_id)
#        )
#        """)
#
#        # Create index for faster queries
#        cur.execute("""
#        CREATE INDEX IF NOT EXISTS staff_info_restaurant_id_idx 
#        ON staff_info(restaurant_id)
#        """)
#
#        conn.commit()
#        logger.info("Settings and staff tables initialized successfully")
#
#
#    except Exception as e:
#        if conn:
#            conn.rollback()
#        logger.error(f"Error initializing settings tables: {str(e)}")
#        raise
#    finally:
#        if conn:
#            cur.close()
#            conn.close()
#
#
## API Routes
#
## Integration management endpoints
#@router.post("/integrations/create", response_model=IntegrationResponse, status_code=status.HTTP_201_CREATED)
#async def create_integration(
#        integration: IntegrationCreate,
#        current_user: dict = Depends(get_current_user),
#        db=Depends(get_db)
#):
#    """
#    Create a new integration with API key
#    Only accessible to super admins
#    """
#    # Check if user is a Operators
#    if current_user["role"] != "SUPER_ADMIN":
#        raise HTTPException(
#            status_code=status.HTTP_403_FORBIDDEN,
#            detail="Only SUPER_ADMIN can manage integrations"
#        )
#
#    try:
#        cur = db.cursor(cursor_factory=RealDictCursor)
#
#        # Check if integration with this name already exists
#        cur.execute(
#            "SELECT id FROM integrations WHERE name = %s AND user_id = %s",
#            (integration.name, current_user["id"])
#        )
#
#        if cur.fetchone():
#            raise HTTPException(
#                status_code=status.HTTP_409_CONFLICT,
#                detail=f"Integration with name '{integration.name}' already exists"
#            )
#
#        # Insert new integration
#        cur.execute(
#            """
#            INSERT INTO integrations (name, api_key, user_id)
#            VALUES (%s, %s, %s)
#            RETURNING id, name, api_key, enabled, created_at
#            """,
#            (integration.name, integration.api_key, current_user["id"])
#        )
#
#        new_integration = cur.fetchone()
#        db.commit()
#
#        resulted = await update_usage(
#            current_user=current_user,
#            conn=db,
#            used_integrations=True,
#        )
#
#        logger.info(f"Integration '{integration.name}' created by {current_user['email']}")
#        return new_integration
#
#    except HTTPException:
#        db.rollback()
#        raise
#    except Exception as e:
#        db.rollback()
#        logger.error(f"Error creating integration: {str(e)}")
#        raise HTTPException(
#            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#            detail=f"Failed to create integration: {str(e)}"
#        )
#
#
#@router.get("/integrations", response_model=List[IntegrationResponse])
#async def get_integrations(
#        current_user: dict = Depends(get_current_user),
#        db=Depends(get_db)
#):
#    """
#    Get all integrations
#    Only accessible to super admins
#    """
#    # Check if user is a Operators
#    allowed_roles = ["SUPER_ADMIN", "Restaurant Owner", "Restaurant Manager"]
#    if current_user["role"] not in allowed_roles:
#        raise HTTPException(
#            status_code=status.HTTP_403_FORBIDDEN,
#            detail="You do not have permission to manage integrations"
#        )
#
#    try:
#        cur = db.cursor(cursor_factory=RealDictCursor)
#        cur.execute(
#            """
#            SELECT id, name, api_key, enabled, created_at
#            FROM integrations
#            WHERE user_id = %s
#            ORDER BY created_at DESC
#            """, (current_user["id"],)
#        )
#
#        integrations = cur.fetchall()
#        return integrations
#
#    except Exception as e:
#        logger.error(f"Error fetching integrations: {str(e)}")
#        raise HTTPException(
#            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#            detail=f"Failed to fetch integrations: {str(e)}"
#        )
#
#
#@router.put("/integrations/{integration_id}", response_model=IntegrationResponse)
#async def update_integration(
#        integration_id: int,
#        integration: IntegrationUpdate,
#        current_user: dict = Depends(get_current_user),
#        db=Depends(get_db)
#):
#    """
#    Update an existing integration
#    Only accessible to super admins
#    """
#    # Check if user is a Operators
#    if current_user["role"] == "Non_Operators":
#        raise HTTPException(
#            status_code=status.HTTP_403_FORBIDDEN,
#            detail="Only Operators can manage integrations"
#        )
#
#    try:
#        cur = db.cursor(cursor_factory=RealDictCursor)
#
#        # Check if integration exists
#        cur.execute(
#            "SELECT id FROM integrations WHERE id = %s",
#            (integration_id,)
#        )
#
#        if not cur.fetchone():
#            raise HTTPException(
#                status_code=status.HTTP_404_NOT_FOUND,
#                detail=f"Integration with ID {integration_id} not found"
#            )
#
#        # Build update query dynamically based on provided fields
#        update_fields = []
#        params = []
#
#        if integration.name is not None:
#            update_fields.append("name = %s")
#            params.append(integration.name)
#
#        if integration.api_key is not None:
#            update_fields.append("api_key = %s")
#            params.append(integration.api_key)
#
#        if integration.enabled is not None:
#            update_fields.append("enabled = %s")
#            params.append(integration.enabled)
#
#        if not update_fields:
#            # No fields to update
#            cur.execute(
#                """
#                SELECT id, name, api_key, enabled, created_at
#                FROM integrations
#                WHERE id = %s
#                """,
#                (integration_id,)
#            )
#            return cur.fetchone()
#
#        # Add integration_id to params
#        params.append(integration_id)
#
#        # Execute update query
#        cur.execute(
#            f"""
#            UPDATE integrations
#            SET {", ".join(update_fields)}
#            WHERE id = %s
#            RETURNING id, name, api_key, enabled, created_at
#            """,
#            tuple(params)
#        )
#
#        updated_integration = cur.fetchone()
#        db.commit()
#
#        logger.info(f"Integration ID {integration_id} updated by {current_user['email']}")
#        return updated_integration
#
#    except HTTPException:
#        db.rollback()
#        raise
#    except Exception as e:
#        db.rollback()
#        logger.error(f"Error updating integration: {str(e)}")
#        raise HTTPException(
#            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#            detail=f"Failed to update integration: {str(e)}"
#        )
#
#
#@router.delete("/integrations/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
#async def delete_integration(
#        integration_id: int,
#        current_user: dict = Depends(get_current_user),
#        db=Depends(get_db)
#):
#    """
#    Delete an integration
#    Only accessible to super admins
#    """
#    # Check if user is a Operators
#    if current_user["role"] == "Non_Operators":
#        raise HTTPException(
#            status_code=status.HTTP_403_FORBIDDEN,
#            detail="Only Operators can manage integrations"
#        )
#
#    try:
#        cur = db.cursor()
#
#        # Check if integration exists
#        cur.execute(
#            "SELECT id FROM integrations WHERE id = %s",
#            (integration_id,)
#        )
#
#        if not cur.fetchone():
#            raise HTTPException(
#                status_code=status.HTTP_404_NOT_FOUND,
#                detail=f"Integration with ID {integration_id} not found"
#            )
#
#        # Delete the integration
#        cur.execute(
#            "DELETE FROM integrations WHERE id = %s",
#            (integration_id,)
#        )
#
#        db.commit()
#
#        logger.info(f"Integration ID {integration_id} deleted by {current_user['email']}")
#        return None
#
#    except HTTPException:
#        db.rollback()
#        raise
#    except Exception as e:
#        db.rollback()
#        logger.error(f"Error deleting integration: {str(e)}")
#        raise HTTPException(
#            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#            detail=f"Failed to delete integration: {str(e)}"
#        )
#
#
## Staff Models
#class StaffResponse(BaseModel):
#    id: int
#    employee_id: int
#    name: str
#    role: str
#    hire_date: datetime
#    termination_date: Optional[datetime] = None
#    hourly_rate: float
#    profile_image: Optional[str] = None
#    contact_number: Optional[str] = None
#    email: Optional[str] = None
#    address: Optional[str] = None
#    emergency_contact: Optional[str] = None
#    notes: Optional[str] = None
#    created_at: datetime
#    updated_at: datetime
#
#
## Staff Endpoints
#@router.get("/staff/{restaurant_name}", response_model=List[StaffResponse])
#async def get_restaurant_staff(
#        restaurant_name: str,
#        current_user: dict = Depends(get_current_user),
#        db=Depends(get_db)
#):
#    """
#    Get all staff members for a specific restaurant.
#    Access is based on user role:
#    - SUPER_ADMIN: Can view staff for any restaurant
#    - Restaurant Owner: Can view staff for restaurants they created
#    - Regional/Restaurant Manager: Can view staff for assigned restaurants
#    """
#    try:
#        cur = db.cursor(cursor_factory=RealDictCursor)
#
#        # Different query based on user role
#        if current_user["role"] == "SUPER_ADMIN":
#            # SUPER_ADMIN can access any restaurant's staff
#            cur.execute("""
#                SELECT s.*, r.name as restaurant_name
#                FROM staff_info s
#                JOIN restaurants r ON s.restaurant_id = r.id
#                WHERE r.name = %s AND r.active = true
#                ORDER BY s.name
#            """, (restaurant_name,))
#
#        elif current_user["role"] == "Restaurant Owner":
#            # Restaurant owners can only access their own restaurants' staff
#            cur.execute("""
#                SELECT s.*, r.name as restaurant_name
#                FROM staff_info s
#                JOIN restaurants r ON s.restaurant_id = r.id
#                WHERE r.name = %s AND r.active = true AND r.created_by = %s
#                ORDER BY s.name
#            """, (restaurant_name, current_user["id"]))
#
#        else:
#            # Regional and Restaurant managers can only access assigned restaurants' staff
#            cur.execute("""
#                SELECT s.*, r.name as restaurant_name
#                FROM staff_info s
#                JOIN restaurants r ON s.restaurant_id = r.id
#                JOIN restaurant_assignments ra ON r.id = ra.restaurant_id
#                WHERE r.name = %s AND r.active = true AND ra.manager_id = %s
#                ORDER BY s.name
#            """, (restaurant_name, current_user["id"]))
#
#        staff = cur.fetchall()
#
#        if not staff:
#            # Check if restaurant exists but has no staff
#            cur.execute("""
#                SELECT id FROM restaurants WHERE name = %s AND active = true
#            """, (restaurant_name,))
#
#            if not cur.fetchone():
#                raise HTTPException(
#                    status_code=status.HTTP_404_NOT_FOUND,
#                    detail=f"Restaurant '{restaurant_name}' not found or you don't have access to it"
#                )
#
#        return staff
#
#    except HTTPException:
#        raise
#    except Exception as e:
#        logger.error(f"Error fetching staff data: {str(e)}")
#        raise HTTPException(
#            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#            detail=f"Failed to fetch staff data: {str(e)}"
#        )
#
#
#from psycopg2.extras import DictCursor
#
#
#@router.get("/staff/role-count/{restaurant_id}")
#def get_role_counts(restaurant_id: int, conn=Depends(get_db)):
#    try:
#        cur = conn.cursor(cursor_factory=DictCursor)
#        cur.execute("""
#            SELECT role, COUNT(*) AS count
#            FROM staff_info
#            WHERE restaurant_id = %s
#            GROUP BY role
#        """, (restaurant_id,))
#        results = cur.fetchall()
#        return [{"role": row["role"], "count": row["count"]} for row in results]
#    except Exception as e:
#        raise HTTPException(status_code=500, detail=f"Error retrieving role counts: {str(e)}")
#
#
#@router.get("/staff", response_model=Dict[str, List[StaffResponse]])
#async def get_all_staff(
#        current_user: dict = Depends(get_current_user),
#        db=Depends(get_db)
#):
#    """
#    Get all staff members grouped by restaurant.
#    Access is based on user role:
#    - SUPER_ADMIN: Can view staff for all restaurants
#    - Restaurant Owner: Can view staff for restaurants they created
#    - Regional/Restaurant Manager: Can view staff for assigned restaurants
#    """
#    try:
#        cur = db.cursor(cursor_factory=RealDictCursor)
#
#        # Different query based on user role
#        if current_user["role"] == "SUPER_ADMIN":
#            # SUPER_ADMIN can access all restaurants' staff
#            cur.execute("""
#                SELECT s.*, r.name as restaurant_name
#                FROM staff_info s
#                JOIN restaurants r ON s.restaurant_id = r.id
#                WHERE r.active = true
#                ORDER BY r.name, s.name
#            """)
#
#        elif current_user["role"] == "Restaurant Owner":
#            # Restaurant owners can only access their own restaurants' staff
#            cur.execute("""
#                SELECT s.*, r.name as restaurant_name
#                FROM staff_info s
#                JOIN restaurants r ON s.restaurant_id = r.id
#                WHERE r.active = true AND r.created_by = %s
#                ORDER BY r.name, s.name
#            """, (current_user["id"],))
#
#        else:
#            # Regional and Restaurant managers can only access assigned restaurants' staff
#            cur.execute("""
#                SELECT s.*, r.name as restaurant_name
#                FROM staff_info s
#                JOIN restaurants r ON s.restaurant_id = r.id
#                JOIN restaurant_assignments ra ON r.id = ra.restaurant_id
#                WHERE r.active = true AND ra.manager_id = %s
#                ORDER BY r.name, s.name
#            """, (current_user["id"],))
#
#        all_staff = cur.fetchall()
#
#        # Group staff by restaurant
#        staff_by_restaurant = {}
#        for staff_member in all_staff:
#            restaurant_name = staff_member.pop('restaurant_name')
#            if restaurant_name not in staff_by_restaurant:
#                staff_by_restaurant[restaurant_name] = []
#            staff_by_restaurant[restaurant_name].append(staff_member)
#
#        return staff_by_restaurant
#
#    except Exception as e:
#        logger.error(f"Error fetching all staff data: {str(e)}")
#        raise HTTPException(
#            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#            detail=f"Failed to fetch staff data: {str(e)}"
#        )
#
#
## Add these imports at the top if not already present
#from pydantic import BaseModel
#from typing import Optional
#
#
## Add these models after your existing models
#class NotificationSettingsResponse(BaseModel):
#    id: int
#    user_id: int
#    fraud_alerts: bool
#    account_notifications: bool
#    subscription_alerts: bool
#    file_processing_updates: bool
#    created_at: datetime
#    updated_at: datetime
#
#
#class NotificationSettingsUpdate(BaseModel):
#    fraud_alerts: Optional[bool] = None
#    account_notifications: Optional[bool] = None
#    subscription_alerts: Optional[bool] = None
#    file_processing_updates: Optional[bool] = None
#
#
## Add these new endpoints before init_settings_tables()
#@router.get("/notifications_settings", response_model=NotificationSettingsResponse)
#async def get_notification_settings(
#        current_user: dict = Depends(get_current_user),
#        db=Depends(get_db)
#):
#    """Get notification settings for the current user"""
#    try:
#        cur = db.cursor(cursor_factory=RealDictCursor)
#
#        # Check if settings exist for the user
#        cur.execute("""
#            SELECT * FROM user_notification_settings 
#            WHERE user_id = %s
#        """, (current_user["id"],))
#
#        settings = cur.fetchone()
#
#        # If no settings exist, create default settings
#        if not settings:
#            cur.execute("""
#                INSERT INTO user_notification_settings 
#                (user_id, fraud_alerts, account_notifications, 
#                subscription_alerts, file_processing_updates)
#                VALUES (%s, false, true, true, false)
#                RETURNING *
#            """, (current_user["id"],))
#            settings = cur.fetchone()
#            db.commit()
#
#        logger.info(f"Default notification settings created for user {current_user['email']}")
#
#        return settings
#
#    except Exception as e:
#        logger.error(f"Error fetching notification settings: {str(e)}")
#        raise HTTPException(
#            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#            detail=f"Failed to fetch notification settings: {str(e)}"
#        )
#
#
#@router.put("/notifications_settings", response_model=NotificationSettingsResponse)
#async def update_notification_settings(
#        settings: NotificationSettingsUpdate,
#        current_user: dict = Depends(get_current_user),
#        db=Depends(get_db)
#):
#    """Update notification settings for the current user"""
#    try:
#        cur = db.cursor(cursor_factory=RealDictCursor)
#
#        # Build update query dynamically based on provided fields
#        update_fields = []
#        params = []
#
#        if settings.fraud_alerts is not None:
#            update_fields.append("fraud_alerts = %s")
#            params.append(settings.fraud_alerts)
#
#        if settings.account_notifications is not None:
#            update_fields.append("account_notifications = %s")
#            params.append(settings.account_notifications)
#
#        if settings.subscription_alerts is not None:
#            update_fields.append("subscription_alerts = %s")
#            params.append(settings.subscription_alerts)
#
#        if settings.file_processing_updates is not None:
#            update_fields.append("file_processing_updates = %s")
#            params.append(settings.file_processing_updates)
#
#        if not update_fields:
#            # No fields to update, return current settings
#            cur.execute("""
#                SELECT * FROM user_notification_settings 
#                WHERE user_id = %s
#            """, (current_user["id"],))
#            return cur.fetchone()
#
#        # Add user_id and updated_at to params
#        params.append(current_user["id"])
#
#        # Execute update query
#        cur.execute(f"""
#            UPDATE user_notification_settings
#            SET {", ".join(update_fields)}, updated_at = CURRENT_TIMESTAMP
#            WHERE user_id = %s
#            RETURNING *
#        """, tuple(params))
#
#        updated_settings = cur.fetchone()
#
#        # If no settings were updated (user didn't have any), create new settings
#        if not updated_settings:
#            cur.execute("""
#                INSERT INTO user_notification_settings 
#                (user_id, fraud_alerts, account_notifications, 
#                subscription_alerts, file_processing_updates)
#                VALUES (%s, %s, %s, %s, %s)
#                RETURNING *
#            """, (
#                current_user["id"],
#                settings.fraud_alerts if settings.fraud_alerts is not None else True,
#                settings.account_notifications if settings.account_notifications is not None else True,
#                settings.subscription_alerts if settings.subscription_alerts is not None else True,
#                settings.file_processing_updates if settings.file_processing_updates is not None else True
#            ))
#            updated_settings = cur.fetchone()
#
#        db.commit()
#        logger.info(f"Notification settings updated for user {current_user['email']}")
#
#        return updated_settings
#
#    except Exception as e:
#        db.rollback()
#        logger.error(f"Error updating notification settings: {str(e)}")
#        raise HTTPException(
#            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#            detail=f"Failed to update notification settings: {str(e)}"
#        )
#
#
## Initialize the tables when module is imported
#init_settings_tables()
#
#---------Testing New Table------------------#

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import uuid
from datetime import datetime
from src.chat_gpt import get_current_user, get_db, DB_CONFIG
from src.subscription_management import update_usage

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Router
router = APIRouter(prefix="/settings", tags=["Settings and Integrations"])


# Models
class IntegrationCreate(BaseModel):
    name: str = Field(..., description="Integration name", min_length=1, max_length=100)
    api_key: str = Field(..., description="API key for the integration")


class IntegrationResponse(BaseModel):
    id: int
    name: str
    api_key: str
    enabled: bool
    created_at: datetime


class IntegrationUpdate(BaseModel):
    name: Optional[str] = Field(None, description="Integration name", min_length=1, max_length=100)
    api_key: Optional[str] = Field(None, description="API key for the integration")
    enabled: Optional[bool] = Field(None, description="Whether the integration is enabled")


# Database Functions
def init_settings_tables():
    """Initialize the database tables for settings, integrations, and employees if they don't exist"""
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        # Create table for system integrations
        cur.execute("""
        CREATE TABLE IF NOT EXISTS integrations (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES managers(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            api_key TEXT NOT NULL,
            enabled BOOLEAN DEFAULT true,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Create table for employee information (using employees_graphs structure)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS employees_graphs (
            id SERIAL PRIMARY KEY,
            restaurant_id INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            employee_name TEXT,
            role TEXT NOT NULL,
            position TEXT,
            hire_date DATE NOT NULL,
            termination_date DATE,
            hourly_rate DECIMAL(10, 2),
            hours_worked DECIMAL(10, 2),
            total_wages DECIMAL(10, 2),
            overtime_hours DECIMAL(10, 2),
            profile_image TEXT,
            contact_number TEXT,
            email TEXT,
            address TEXT,
            emergency_contact TEXT,
            notes TEXT,
            filename TEXT NOT NULL,
            data JSONB,
            date DATE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(restaurant_id, employee_id)
        )
        """)

        # Create index for faster queries
        cur.execute("""
        CREATE INDEX IF NOT EXISTS employees_graphs_restaurant_id_idx 
        ON employees_graphs(restaurant_id)
        """)

        conn.commit()
        logger.info("Settings and employees tables initialized successfully")

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error initializing settings tables: {str(e)}")
        raise
    finally:
        if conn:
            cur.close()
            conn.close()


# API Routes

# Integration management endpoints
@router.post("/integrations/create", response_model=IntegrationResponse, status_code=status.HTTP_201_CREATED)
async def create_integration(
        integration: IntegrationCreate,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
):
    """
    Create a new integration with API key
    Only accessible to super admins
    """
    # Check if user is a Operators
    if current_user["role"] != "SUPER_ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only SUPER_ADMIN can manage integrations"
        )

    try:
        cur = db.cursor(cursor_factory=RealDictCursor)

        # Check if integration with this name already exists
        cur.execute(
            "SELECT id FROM integrations WHERE name = %s AND user_id = %s",
            (integration.name, current_user["id"])
        )

        if cur.fetchone():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Integration with name '{integration.name}' already exists"
            )

        # Insert new integration
        cur.execute(
            """
            INSERT INTO integrations (name, api_key, user_id)
            VALUES (%s, %s, %s)
            RETURNING id, name, api_key, enabled, created_at
            """,
            (integration.name, integration.api_key, current_user["id"])
        )

        new_integration = cur.fetchone()
        db.commit()

        resulted = await update_usage(
            current_user=current_user,
            conn=db,
            used_integrations=True,
        )

        logger.info(f"Integration '{integration.name}' created by {current_user['email']}")
        return new_integration

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating integration: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create integration: {str(e)}"
        )


@router.get("/integrations", response_model=List[IntegrationResponse])
async def get_integrations(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
):
    """
    Get all integrations
    Only accessible to super admins
    """
    # Check if user is a Operators
    allowed_roles = ["SUPER_ADMIN", "Restaurant Owner", "Restaurant Manager"]
    if current_user["role"] not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage integrations"
        )

    try:
        cur = db.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, name, api_key, enabled, created_at
            FROM integrations
            WHERE user_id = %s
            ORDER BY created_at DESC
            """, (current_user["id"],)
        )

        integrations = cur.fetchall()
        return integrations

    except Exception as e:
        logger.error(f"Error fetching integrations: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch integrations: {str(e)}"
        )


@router.put("/integrations/{integration_id}", response_model=IntegrationResponse)
async def update_integration(
        integration_id: int,
        integration: IntegrationUpdate,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
):
    """
    Update an existing integration
    Only accessible to super admins
    """
    # Check if user is a Operators
    if current_user["role"] == "Non_Operators":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Operators can manage integrations"
        )

    try:
        cur = db.cursor(cursor_factory=RealDictCursor)

        # Check if integration exists
        cur.execute(
            "SELECT id FROM integrations WHERE id = %s",
            (integration_id,)
        )

        if not cur.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Integration with ID {integration_id} not found"
            )

        # Build update query dynamically based on provided fields
        update_fields = []
        params = []

        if integration.name is not None:
            update_fields.append("name = %s")
            params.append(integration.name)

        if integration.api_key is not None:
            update_fields.append("api_key = %s")
            params.append(integration.api_key)

        if integration.enabled is not None:
            update_fields.append("enabled = %s")
            params.append(integration.enabled)

        if not update_fields:
            # No fields to update
            cur.execute(
                """
                SELECT id, name, api_key, enabled, created_at
                FROM integrations
                WHERE id = %s
                """,
                (integration_id,)
            )
            return cur.fetchone()

        # Add integration_id to params
        params.append(integration_id)

        # Execute update query
        cur.execute(
            f"""
            UPDATE integrations
            SET {", ".join(update_fields)}
            WHERE id = %s
            RETURNING id, name, api_key, enabled, created_at
            """,
            tuple(params)
        )

        updated_integration = cur.fetchone()
        db.commit()

        logger.info(f"Integration ID {integration_id} updated by {current_user['email']}")
        return updated_integration

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating integration: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update integration: {str(e)}"
        )


@router.delete("/integrations/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration(
        integration_id: int,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
):
    """
    Delete an integration
    Only accessible to super admins
    """
    # Check if user is a Operators
    if current_user["role"] == "Non_Operators":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Operators can manage integrations"
        )

    try:
        cur = db.cursor()

        # Check if integration exists
        cur.execute(
            "SELECT id FROM integrations WHERE id = %s",
            (integration_id,)
        )

        if not cur.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Integration with ID {integration_id} not found"
            )

        # Delete the integration
        cur.execute(
            "DELETE FROM integrations WHERE id = %s",
            (integration_id,)
        )

        db.commit()

        logger.info(f"Integration ID {integration_id} deleted by {current_user['email']}")
        return None

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting integration: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete integration: {str(e)}"
        )


# Staff Models
class StaffResponse(BaseModel):
    id: int
    employee_id: int
    name: str
    role: str
    hire_date: Optional[datetime] = None  # Changed from datetime to Optional[datetime]
    termination_date: Optional[datetime] = None
    hourly_rate: Optional[float] = None
    hours_worked: Optional[float] = None
    total_wages: Optional[float] = None
    overtime_hours: Optional[float] = None
    profile_image: Optional[str] = None
    contact_number: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    emergency_contact: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

# Staff Endpoints
@router.get("/staff/{restaurant_name}", response_model=List[StaffResponse])
async def get_restaurant_staff(
        restaurant_name: str,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
):
    """
    Get all staff members for a specific restaurant.
    Access is based on user role:
    - SUPER_ADMIN: Can view staff for any restaurant
    - Restaurant Owner: Can view staff for restaurants they created
    - Regional/Restaurant Manager: Can view staff for assigned restaurants
    """
    try:
        cur = db.cursor(cursor_factory=RealDictCursor)

        # Different query based on user role
        if current_user["role"] == "SUPER_ADMIN":
            # SUPER_ADMIN can access any restaurant's staff
            cur.execute("""
                SELECT e.*, r.name as restaurant_name
                FROM employees_graphs e
                JOIN restaurants r ON e.restaurant_id = r.id
                WHERE r.name = %s AND r.active = true
                ORDER BY e.name
            """, (restaurant_name,))

        elif current_user["role"] == "Restaurant Owner":
            # Restaurant owners can only access their own restaurants' staff
            cur.execute("""
                SELECT e.*, r.name as restaurant_name
                FROM employees_graphs e
                JOIN restaurants r ON e.restaurant_id = r.id
                WHERE r.name = %s AND r.active = true AND r.created_by = %s
                ORDER BY e.name
            """, (restaurant_name, current_user["id"]))

        else:
            # Regional and Restaurant managers can only access assigned restaurants' staff
            cur.execute("""
                SELECT e.*, r.name as restaurant_name
                FROM employees_graphs e
                JOIN restaurants r ON e.restaurant_id = r.id
                JOIN restaurant_assignments ra ON r.id = ra.restaurant_id
                WHERE r.name = %s AND r.active = true AND ra.manager_id = %s
                ORDER BY e.name
            """, (restaurant_name, current_user["id"]))

        staff = cur.fetchall()

        if not staff:
            # Check if restaurant exists but has no staff
            cur.execute("""
                SELECT id FROM restaurants WHERE name = %s AND active = true
            """, (restaurant_name,))

            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Restaurant '{restaurant_name}' not found or you don't have access to it"
                )

        return staff

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching staff data: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch staff data: {str(e)}"
        )


from psycopg2.extras import DictCursor


@router.get("/staff/role-count/{restaurant_id}")
def get_role_counts(restaurant_id: int, conn=Depends(get_db)):
    try:
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("""
            SELECT role, COUNT(*) AS count
            FROM employees_graphs
            WHERE restaurant_id = %s
            GROUP BY role
        """, (restaurant_id,))
        results = cur.fetchall()
        return [{"role": row["role"], "count": row["count"]} for row in results]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving role counts: {str(e)}")


@router.get("/staff", response_model=Dict[str, List[StaffResponse]])
async def get_all_staff(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
):
    """
    Get all staff members grouped by restaurant.
    Access is based on user role:
    - SUPER_ADMIN: Can view staff for all restaurants
    - Restaurant Owner: Can view staff for restaurants they created
    - Regional/Restaurant Manager: Can view staff for assigned restaurants
    """
    try:
        cur = db.cursor(cursor_factory=RealDictCursor)

        # Different query based on user role
        if current_user["role"] == "SUPER_ADMIN":
            # SUPER_ADMIN can access all restaurants' staff
            cur.execute("""
                SELECT e.*, r.name as restaurant_name
                FROM employees_graphs e
                JOIN restaurants r ON e.restaurant_id = r.id
                WHERE r.active = true
                ORDER BY r.name, e.name
            """)

        elif current_user["role"] == "Restaurant Owner":
            # Restaurant owners can only access their own restaurants' staff
            cur.execute("""
                SELECT e.*, r.name as restaurant_name
                FROM employees_graphs e
                JOIN restaurants r ON e.restaurant_id = r.id
                WHERE r.active = true AND r.created_by = %s
                ORDER BY r.name, e.name
            """, (current_user["id"],))

        else:
            # Regional and Restaurant managers can only access assigned restaurants' staff
            cur.execute("""
                SELECT e.*, r.name as restaurant_name
                FROM employees_graphs e
                JOIN restaurants r ON e.restaurant_id = r.id
                JOIN restaurant_assignments ra ON r.id = ra.restaurant_id
                WHERE r.active = true AND ra.manager_id = %s
                ORDER BY r.name, e.name
            """, (current_user["id"],))

        all_staff = cur.fetchall()

        # Group staff by restaurant
        staff_by_restaurant = {}
        for staff_member in all_staff:
            restaurant_name = staff_member.pop('restaurant_name')
            if restaurant_name not in staff_by_restaurant:
                staff_by_restaurant[restaurant_name] = []
            staff_by_restaurant[restaurant_name].append(staff_member)

        return staff_by_restaurant

    except Exception as e:
        logger.error(f"Error fetching all staff data: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch staff data: {str(e)}"
        )


# Add these imports at the top if not already present
from pydantic import BaseModel
from typing import Optional


# Add these models after your existing models
class NotificationSettingsResponse(BaseModel):
    id: int
    user_id: int
    fraud_alerts: bool
    account_notifications: bool
    subscription_alerts: bool
    file_processing_updates: bool
    created_at: datetime
    updated_at: datetime


class NotificationSettingsUpdate(BaseModel):
    fraud_alerts: Optional[bool] = None
    account_notifications: Optional[bool] = None
    subscription_alerts: Optional[bool] = None
    file_processing_updates: Optional[bool] = None


# Add these new endpoints before init_settings_tables()
@router.get("/notifications_settings", response_model=NotificationSettingsResponse)
async def get_notification_settings(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
):
    """Get notification settings for the current user"""
    try:
        cur = db.cursor(cursor_factory=RealDictCursor)

        # Check if settings exist for the user
        cur.execute("""
            SELECT * FROM user_notification_settings 
            WHERE user_id = %s
        """, (current_user["id"],))

        settings = cur.fetchone()

        # If no settings exist, create default settings
        if not settings:
            cur.execute("""
                INSERT INTO user_notification_settings 
                (user_id, fraud_alerts, account_notifications, 
                subscription_alerts, file_processing_updates)
                VALUES (%s, false, true, true, false)
                RETURNING *
            """, (current_user["id"],))
            settings = cur.fetchone()
            db.commit()

        logger.info(f"Default notification settings created for user {current_user['email']}")

        return settings

    except Exception as e:
        logger.error(f"Error fetching notification settings: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch notification settings: {str(e)}"
        )


@router.put("/notifications_settings", response_model=NotificationSettingsResponse)
async def update_notification_settings(
        settings: NotificationSettingsUpdate,
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
):
    """Update notification settings for the current user"""
    try:
        cur = db.cursor(cursor_factory=RealDictCursor)

        # Build update query dynamically based on provided fields
        update_fields = []
        params = []

        if settings.fraud_alerts is not None:
            update_fields.append("fraud_alerts = %s")
            params.append(settings.fraud_alerts)

        if settings.account_notifications is not None:
            update_fields.append("account_notifications = %s")
            params.append(settings.account_notifications)

        if settings.subscription_alerts is not None:
            update_fields.append("subscription_alerts = %s")
            params.append(settings.subscription_alerts)

        if settings.file_processing_updates is not None:
            update_fields.append("file_processing_updates = %s")
            params.append(settings.file_processing_updates)

        if not update_fields:
            # No fields to update, return current settings
            cur.execute("""
                SELECT * FROM user_notification_settings 
                WHERE user_id = %s
            """, (current_user["id"],))
            return cur.fetchone()

        # Add user_id and updated_at to params
        params.append(current_user["id"])

        # Execute update query
        cur.execute(f"""
            UPDATE user_notification_settings
            SET {", ".join(update_fields)}, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = %s
            RETURNING *
        """, tuple(params))

        updated_settings = cur.fetchone()

        # If no settings were updated (user didn't have any), create new settings
        if not updated_settings:
            cur.execute("""
                INSERT INTO user_notification_settings 
                (user_id, fraud_alerts, account_notifications, 
                subscription_alerts, file_processing_updates)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
            """, (
                current_user["id"],
                settings.fraud_alerts if settings.fraud_alerts is not None else True,
                settings.account_notifications if settings.account_notifications is not None else True,
                settings.subscription_alerts if settings.subscription_alerts is not None else True,
                settings.file_processing_updates if settings.file_processing_updates is not None else True
            ))
            updated_settings = cur.fetchone()

        db.commit()
        logger.info(f"Notification settings updated for user {current_user['email']}")

        return updated_settings

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating notification settings: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update notification settings: {str(e)}"
        )


# Initialize the tables when module is imported
#init_settings_tables()
