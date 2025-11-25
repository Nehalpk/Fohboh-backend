from fastapi import Depends, HTTPException, status, APIRouter
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from enum import Enum
from datetime import datetime

# Import dependencies from chat_gpt.py
from src.chat_gpt import get_db, get_current_user, RoleType

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(
    prefix="/hours-of-operation",
    tags=["Hours of Operation"]
)

# Models
class DayOfWeek(str, Enum):
    MONDAY = "Mon"
    TUESDAY = "Tue"
    WEDNESDAY = "Wed"
    THURSDAY = "Thu"
    FRIDAY = "Fri"
    SATURDAY = "Sat"
    SUNDAY = "Sun"

class HoursOfOperationDayItem(BaseModel):
    
    day_of_week: List[str]
    start_time: Optional[str] = None  # Format: "HH:MM:SS"
    end_time: Optional[str] = None    # Format: "HH:MM:SS"

class HoursOfOperationItem(BaseModel):
    id: Optional[int] = None
    restaurant_id: int
    meal_period: str
    day_of_week: List[str]
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    is_available: bool = True
    
    class Config:
        from_attributes = True

class HoursOfOperationResponse(BaseModel):
    id: int
    restaurant_id: int
    meal_period: str
    day_of_week: List[str]
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    is_available: bool = True
    
    class Config:
        from_attributes = True

class MealPeriodHours(BaseModel):
    id: Optional[int] = None
    meal_period: str
    is_available: bool = True
    day_of_week: List[str] = []
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    # days: List[HoursOfOperationDayItem]

class HoursOfOperationUpdate(BaseModel):
    meal_periods: List[MealPeriodHours]

class HoursOfOperationUpdateById(BaseModel):
    meal_period: Optional[str] = None
    day_of_week: Optional[List[str]] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    is_available: Optional[bool] = None

class MealPeriodCreate(BaseModel):
    meal_period: str
    is_available: bool = True
    days: List[HoursOfOperationDayItem]

class MealPeriodDelete(BaseModel):
    meal_period: str

# Database initialization
def init_hours_of_operation_table():
    """Initialize the hours_of_operation table if it doesn't exist."""
    conn = None
    try:
        # Get database configuration from chat_gpt.py
        from src.chat_gpt import DB_CONFIG
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Create hours_of_operation table if it doesn't exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS hours_of_operation (
                id SERIAL PRIMARY KEY,
                restaurant_id INTEGER NOT NULL,
                day_of_week VARCHAR(3)[] NOT NULL,
                meal_period VARCHAR(50) NOT NULL,
                start_time TIME,
                end_time TIME,
                is_available BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_restaurant
                    FOREIGN KEY(restaurant_id)
                    REFERENCES restaurants(id)
                    ON DELETE CASCADE
            )
        """)
        
        # Create index for faster lookups
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_hours_restaurant_id
            ON hours_of_operation(restaurant_id)
        """)
        
        # Add is_available column if it doesn't exist (for backward compatibility)
        try:
            cur.execute("""
                ALTER TABLE hours_of_operation 
                ADD COLUMN IF NOT EXISTS is_available BOOLEAN DEFAULT TRUE
            """)
        except Exception as e:
            logger.warning(f"Error adding is_available column (may already exist): {str(e)}")
        
        conn.commit()
        logger.info("Hours of operation table initialized successfully")
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error initializing hours of operation table: {str(e)}")
        raise
    finally:
        if conn:
            conn.close()

# Helper functions
def check_restaurant_exists(restaurant_id: int, cur):
    """Check if a restaurant exists and return its details."""
    cur.execute("""
        SELECT id, name, active
        FROM restaurants 
        WHERE id = %s
    """, (restaurant_id,))
    
    existing_restaurant = cur.fetchone()
    if not existing_restaurant:
        raise HTTPException(
            status_code=404,
            detail="Restaurant not found"
        )
    
    return existing_restaurant

def check_user_permission(current_user: dict, restaurant_id: int = None):
    """Check if the user has permission to manage hours of operation."""
    # Super admin can manage all restaurants
    if current_user["role"] == RoleType.SUPER_ADMIN:
        return True
    
    # Restaurant owners and managers can only manage their assigned restaurants
    if current_user["role"] in [RoleType.RESTAURANT_OWNER, RoleType.RESTAURANT_MANAGER, RoleType.REGIONAL_MANAGER]:
        # If no restaurant_id is provided, just check role
        if restaurant_id is None:
            return True
            
        # Otherwise, check if the user is assigned to this restaurant
        conn = None
        try:
            from src.chat_gpt import DB_CONFIG
            conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
            cur = conn.cursor()
            if current_user["role"] == RoleType.RESTAURANT_OWNER:
                query = """
                SELECT 1
                FROM restaurants
                WHERE created_by = %s AND id = %s
            """
            else:
                query = """
                SELECT 1
                FROM restaurant_assignments
                WHERE manager_id = %s AND restaurant_id = %s
            """
            
            cur.execute(query, (current_user["id"], restaurant_id))
            
            if cur.fetchone():
                return True
                
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to manage this restaurant"
            )
        finally:
            if conn:
                conn.close()
    
    # Other roles don't have permission
    raise HTTPException(
        status_code=403,
        detail="Only SUPER_ADMIN, RESTAURANT_OWNER, and RESTAURANT_MANAGER can manage hours of operation"
    )

# Main functions
async def get_restaurant_hours_of_operation(
    restaurant_id: int,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Get all hours of operation for a restaurant."""
    try:
        # Check if restaurant exists
        cur = conn.cursor(cursor_factory=RealDictCursor)
        check_restaurant_exists(restaurant_id, cur)
        
        # Get all hours of operation for this restaurant
        cur.execute("""
            SELECT id, restaurant_id, meal_period, day_of_week, 
                   start_time, end_time, is_available
            FROM hours_of_operation
            WHERE restaurant_id = %s
            ORDER BY meal_period, day_of_week 
        """, (restaurant_id,))
        
        hours_records = cur.fetchall()
        
        # Group by meal period
        meal_periods = {}

        for record in hours_records:
            meal_period = record['meal_period']
            # Convert times to strings (same as your code)
            if record['start_time']:
                record['start_time'] = str(record['start_time'])
            if record['end_time']:
                record['end_time'] = str(record['end_time'])

            # Initialize list if not exists
            if meal_period not in meal_periods:
                meal_periods[meal_period] = []

            # Append this record's info to the list for this meal_period
            meal_periods[meal_period].append({
                'meal_period': meal_period,
                'is_available': record['is_available'],
                'id': record['id'],
                'day_of_week': record['day_of_week'],
                'start_time': record['start_time'],
                'end_time': record['end_time'],
            })

        flat_list = []
        for records in meal_periods.values():
                flat_list.extend(records)

        return flat_list # dict of meal_period -> list of records
        
    except psycopg2.Error as e:
        logger.error(f"Database error getting hours of operation: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Database error occurred while retrieving hours of operation"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting hours of operation: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while retrieving hours of operation"
        )

async def get_hours_of_operation_by_id(
    hours_id: int,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Get hours of operation by ID."""
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get the hours record
        cur.execute("""
            SELECT id, restaurant_id, meal_period, day_of_week, 
                   start_time, end_time, is_available
            FROM hours_of_operation
            WHERE id = %s
        """, (hours_id,))
        
        hours_record = cur.fetchone()
        
        if not hours_record:
            raise HTTPException(
                status_code=404,
                detail="Hours of operation record not found"
            )
        
        # Check permission for this restaurant
        check_user_permission(current_user, hours_record['restaurant_id'])
        
        # Convert time objects to strings
        if hours_record['start_time']:
            hours_record['start_time'] = str(hours_record['start_time'])
        if hours_record['end_time']:
            hours_record['end_time'] = str(hours_record['end_time'])
        
        return hours_record
        
    except psycopg2.Error as e:
        logger.error(f"Database error getting hours of operation: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Database error occurred while retrieving hours of operation"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting hours of operation: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while retrieving hours of operation"
        )

async def update_hours_of_operation(
    restaurant_id: int,
    hours_data: HoursOfOperationUpdate,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Update hours of operation for a restaurant."""
    # Check user permission
    check_user_permission(current_user, restaurant_id)

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Check if restaurant exists
        check_restaurant_exists(restaurant_id, cur)
        
        # Begin transaction
        conn.autocommit = False
        
        # Delete existing hours for this restaurant
        cur.execute("""
            DELETE FROM hours_of_operation
            WHERE restaurant_id = %s
        """, (restaurant_id,))
        
        # Insert new hours
        for meal_period_data in hours_data.meal_periods:
            meal_period = meal_period_data.meal_period
            is_available = meal_period_data.is_available
            
            for day_item in meal_period_data.days:
                day = day_item.day_of_week.value
                start_time = day_item.start_time
                end_time = day_item.end_time
                
                cur.execute("""
                    INSERT INTO hours_of_operation 
                    (restaurant_id, meal_period, day_of_week, start_time, end_time, is_available)
                    VALUES (%s, %s, ARRAY[%s], %s, %s, %s)
                    RETURNING id
                """, (
                    restaurant_id, 
                    meal_period, 
                    day, 
                    start_time, 
                    end_time,
                    is_available
                ))
        
        # Commit transaction
        conn.commit()
        conn.autocommit = True
        
        # Return updated hours
        return await get_restaurant_hours_of_operation(restaurant_id, current_user, conn)

    except HTTPException:
        conn.rollback()
        conn.autocommit = True
        raise
    except psycopg2.Error as e:
        conn.rollback()
        conn.autocommit = True
        logger.error(f"Database error updating hours of operation: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Database error occurred while updating hours of operation"
        )
    except Exception as e:
        conn.rollback()
        conn.autocommit = True
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while updating hours of operation"
        )

async def update_hours_of_operation_by_id(
    hours_id: int,
    hours_data: HoursOfOperationUpdateById,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Update a specific hours of operation record by ID."""
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get the hours record to check permissions
        cur.execute("""
            SELECT restaurant_id
            FROM hours_of_operation
            WHERE id = %s
        """, (hours_id,))
        hours_record = cur.fetchone()

        if not hours_record:
            raise HTTPException(
                status_code=404,
                detail="Hours of operation record not found"
            )

        # Check permission for this restaurant
        check_user_permission(current_user, hours_record['restaurant_id'])
        # Convert list of objects to list of day strings
        # days_list = [day_item.day_of_week for day_item in meal_period_data.days]  # adjust attribute as needed

        cur.execute("""
            SELECT 1
            FROM hours_of_operation
            WHERE restaurant_id = %s AND meal_period = %s AND id != %s AND day_of_week && %s::varchar[]
            LIMIT 1
        """, (hours_record['restaurant_id'], hours_data.meal_period,hours_id, hours_data.day_of_week))

        if cur.fetchone():
            raise HTTPException(
                status_code=400,
                detail=f"Meal period '{hours_data.meal_period}' already exists for this restaurant"
            )


        update_fields = []
        params = []

        if hours_data.meal_period is not None:
            update_fields.append("meal_period = %s")
            params.append(hours_data.meal_period)

        if hours_data.day_of_week is not None:
            for day in hours_data.day_of_week:
                if day not in [d.value for d in DayOfWeek]:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid day of week: {day}. Must be one of: {[d.value for d in DayOfWeek]}"
                    )
            update_fields.append("day_of_week = %s")
            params.append(hours_data.day_of_week)

        if hours_data.start_time is not None:
            update_fields.append("start_time = %s")
            params.append(hours_data.start_time)

        if hours_data.end_time is not None:
            update_fields.append("end_time = %s")
            params.append(hours_data.end_time)

        if hours_data.is_available is not None:
            update_fields.append("is_available = %s")
            params.append(hours_data.is_available)

        update_fields.append("updated_at = CURRENT_TIMESTAMP")

        if not update_fields:
            raise HTTPException(
                status_code=400,
                detail="No fields provided for update"
            )

        query = f"""
            UPDATE hours_of_operation
            SET {", ".join(update_fields)}
            WHERE id = %s
            RETURNING id
        """
        params.append(hours_id)

        # Safe transaction block
        with conn:
            cur.execute(query, params)
            updated_record = cur.fetchone()

            if not updated_record:
                raise HTTPException(
                    status_code=404,
                    detail="Hours of operation record not found"
                )

        return await get_hours_of_operation_by_id(hours_id, current_user, conn)

    except HTTPException:
        raise
    except psycopg2.Error as e:
        logger.error(f"Database error updating hours of operation: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Database error occurred while updating hours of operation"
        )
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while updating hours of operation"
        )


async def add_meal_period(
    restaurant_id: int,
    meal_period_data: MealPeriodCreate,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Add a new meal period with hours of operation."""
    # Check user permission
    check_user_permission(current_user, restaurant_id)

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if restaurant exists
        check_restaurant_exists(restaurant_id, cur)
        # Convert list of objects to list of day strings
        days_list = [day_item.day_of_week for day_item in meal_period_data.days]  # adjust attribute as needed

        # Check if meal period already exists
        cur.execute("""
            SELECT 1
            FROM hours_of_operation
            WHERE restaurant_id = %s AND meal_period = %s AND day_of_week && %s::varchar[]
            LIMIT 1
        """, (restaurant_id, meal_period_data.meal_period, days_list))

        if cur.fetchone():
            raise HTTPException(
                status_code=400,
                detail=f"Meal period '{meal_period_data.meal_period}' OverLapping with existing days {days_list}"
            )

        meal_period = meal_period_data.meal_period
        is_available = meal_period_data.is_available
        inserted_ids = []

        # Start a safe transaction block
        with conn:
            for day_item in meal_period_data.days:
                days = day_item.day_of_week
                start_time = day_item.start_time
                end_time = day_item.end_time

                # Validate day names
                for day in days:
                    if day not in [d.value for d in DayOfWeek]:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Invalid day of week: {day}. Must be one of: {[d.value for d in DayOfWeek]}"
                        )

                # Insert a single row per entry (can be extended to one row per day if needed)
                cur.execute("""
                    INSERT INTO hours_of_operation 
                    (restaurant_id, meal_period, day_of_week, start_time, end_time, is_available)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    restaurant_id,
                    meal_period,
                    days,
                    start_time,
                    end_time,
                    is_available
                ))

                inserted_ids.append(cur.fetchone()['id'])

        return {
            "meal_period": meal_period,
            "is_available": is_available,
            "days": meal_period_data.days,
            "ids": inserted_ids
        }

    except HTTPException:
        raise
    except psycopg2.Error as e:
        logger.error(f"Database error adding meal period: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Database error occurred while adding meal period"
        )
    except Exception as e:
        logger.error(f"Error adding meal period: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while adding meal period"
        )


async def delete_meal_period(
    restaurant_id: int,
    meal_period_data: MealPeriodDelete,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Delete a meal period and all its hours of operation."""
    # Check user permission
    check_user_permission(current_user, restaurant_id)
        
    try:
        cur = conn.cursor()
        
        # Check if restaurant exists
        check_restaurant_exists(restaurant_id, cur)
        
        # Check if meal period exists
        cur.execute("""
            SELECT 1
            FROM hours_of_operation
            WHERE restaurant_id = %s AND meal_period = %s
            LIMIT 1
        """, (restaurant_id, meal_period_data.meal_period))
        
        if not cur.fetchone():
            raise HTTPException(
                status_code=404,
                detail=f"Meal period '{meal_period_data.meal_period}' not found for this restaurant"
            )
        
        # Begin transaction
        conn.autocommit = False
        
        # Delete the meal period
        cur.execute("""
            DELETE FROM hours_of_operation
            WHERE restaurant_id = %s AND meal_period = %s
            RETURNING id
        """, (restaurant_id, meal_period_data.meal_period))
        
        deleted_ids = [row[0] for row in cur.fetchall()]
        
        # Commit transaction
        conn.commit()
        conn.autocommit = True
        
        return {
            "message": f"Meal period '{meal_period_data.meal_period}' deleted successfully",
            "deleted_ids": deleted_ids
        }
        
    except HTTPException:
        if not conn.autocommit:
            conn.rollback()
            conn.autocommit = True
        raise
    except psycopg2.Error as e:
        if not conn.autocommit:
            conn.rollback()
            conn.autocommit = True
        logger.error(f"Database error deleting meal period: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Database error occurred while deleting meal period"
        )
    except Exception as e:
        if not conn.autocommit:
            conn.rollback()
            conn.autocommit = True
        logger.error(f"Error deleting meal period: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while deleting meal period"
        )

async def delete_hours_by_id(
    hours_id: int,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Delete a specific hours of operation record by ID."""
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get the hours record to check permissions
        cur.execute("""
            SELECT restaurant_id, meal_period
            FROM hours_of_operation
            WHERE id = %s
        """, (hours_id,))
        hours_record = cur.fetchone()

        if not hours_record:
            raise HTTPException(
                status_code=404,
                detail="Hours of operation record not found"
            )

        # Check permission for this restaurant
        check_user_permission(current_user, hours_record['restaurant_id'])

         # Check if it's the only record for that restaurant
        cur.execute("""
            SELECT COUNT(*) AS count
            FROM hours_of_operation
            WHERE restaurant_id = %s
        """, (hours_record['restaurant_id'],))
        count_result = cur.fetchone()

        if count_result['count'] <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete the last daypart. A restaurant must have at least one hours of operation record."
            )

        # Use safe transaction block
        with conn:
            cur.execute("""
                DELETE FROM hours_of_operation
                WHERE id = %s
                RETURNING id
            """, (hours_id,))
            deleted_record = cur.fetchone()

            if not deleted_record:
                raise HTTPException(
                    status_code=404,
                    detail="Hours of operation record not found"
                )

        return {
            "message": f"Hours of operation record with ID {hours_id} deleted successfully",
            "deleted_id": hours_id,
            "meal_period": hours_record['meal_period']
        }

    except HTTPException:
        raise
    except psycopg2.Error as e:
        logger.error(f"Database error deleting hours of operation: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Database error occurred while deleting hours of operation"
        )
    except Exception as e:
        logger.error(f"Error deleting hours of operation: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while deleting hours of operation"
        )

# Register API routes
@router.post("/{restaurant_id}/add_meal-period")
async def api_add_meal_period(
    restaurant_id: int,
    meal_period_data: MealPeriodCreate,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Add a new meal period with hours of operation."""
    return await add_meal_period(restaurant_id, meal_period_data, current_user, conn)

@router.get("/{restaurant_id}/get_restaurant_hours", response_model=List[MealPeriodHours])
async def api_get_restaurant_hours(
    restaurant_id: int,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Get all hours of operation for a restaurant."""
    return await get_restaurant_hours_of_operation(restaurant_id, current_user, conn)

# @router.get("/{hours_id}", response_model=HoursOfOperationResponse)
# async def api_get_hours_by_id(
#     hours_id: int,
#     current_user: dict = Depends(get_current_user),
#     conn = Depends(get_db)
# ):
#     """Get hours of operation by ID."""
#     return await get_hours_of_operation_by_id(hours_id, current_user, conn)

# @router.put("/restaurant/{restaurant_id}/update_restaurant_hours")
# async def api_update_restaurant_hours(
#     restaurant_id: int,
#     hours_data: HoursOfOperationUpdate,
#     current_user: dict = Depends(get_current_user),
#     conn = Depends(get_db)
# ):
#     """Update all hours of operation for a restaurant."""
#     return await update_hours_of_operation(restaurant_id, hours_data, current_user, conn)

@router.put("/{hours_id}/update_hours")
async def api_update_hours_by_id(
    hours_id: int,
    hours_data: HoursOfOperationUpdateById,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Update a specific hours of operation record by ID."""
    return await update_hours_of_operation_by_id(hours_id, hours_data, current_user, conn)


# @router.delete("/restaurant/{restaurant_id}/meal-period")
# async def api_delete_meal_period(
#     restaurant_id: int,
#     meal_period_data: MealPeriodDelete,
#     current_user: dict = Depends(get_current_user),
#     conn = Depends(get_db)
# ):
#     """Delete a meal period and all its hours of operation."""
#     return await delete_meal_period(restaurant_id, meal_period_data, current_user, conn)

@router.delete("/{hours_id}")
async def api_delete_hours_by_id(
    hours_id: int,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Delete a specific hours of operation record by ID."""
    return await delete_hours_by_id(hours_id, current_user, conn)