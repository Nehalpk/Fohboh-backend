# src/restaurant_management.py
import json
from fastapi import HTTPException
import logging
import traceback
from typing import Dict, Any
from src.File_upload import (
    verify_restaurant_access_id,
    get_db_connection,
    return_db_connection,
    s3_client,
    BUCKET_NAME,
    UPLOAD_BASE_DIR
)
from src.chat_gpt import RoleType  # ✅ Add this import

logger = logging.getLogger(__name__)


async def delete_restaurant_completely(restaurant_id: int, current_user: dict) -> Dict[str, Any]:
    """
    Completely delete a restaurant and ALL associated data:
    - All files from S3 (all users, all categories)
    - All database records (sales, inventory, menu, employees)
    - Restaurant assignments
    - Restaurant record itself
    
    Only SUPER_ADMIN or Restaurant Owner can delete
    """
    try:
        # Verify restaurant exists and user has permission
        restaurant = await verify_restaurant_access_id(restaurant_id, current_user)
        
        # Permission check - only SUPER_ADMIN or Restaurant Owner can delete completely
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            
            # Check if user is the owner
            cur.execute("""
                SELECT created_by FROM restaurants WHERE id = %s
            """, (restaurant_id,))
            result = cur.fetchone()
            
            if result:
                created_by = result[0]
                if current_user["role"] not in ["SUPER_ADMIN", "Restaurant Owner"]:
                    raise HTTPException(status_code=403, detail="Only Super Admin or Restaurant Owner can delete restaurants")
                
                if current_user["role"] == "Restaurant Owner" and created_by != current_user["id"]:
                    raise HTTPException(status_code=403, detail="You can only delete restaurants you own")
            
        finally:
            cur.close()
            return_db_connection(conn)
        
        logger.info(f"🗑️ Starting complete deletion of restaurant ID: {restaurant_id} ({restaurant['name']})")
        
        deletion_summary = {
            "restaurant_id": restaurant_id,
            "restaurant_name": restaurant['name'],
            "s3_files_deleted": 0,
            "database_records_deleted": {
                "sales": 0,
                "inventory": 0,
                "menu": 0,
                "employees": 0,
                "staff_info": 0,
                "assignments": 0
            },
            "errors": []
        }
        
        # ============= STEP 1: DELETE ALL FILES FROM S3 =============
        restaurant_folder = f"{UPLOAD_BASE_DIR}/{restaurant_id}"
        logger.info(f"🗑️ Deleting S3 folder: {restaurant_folder}")
        
        try:
            # List all objects in the restaurant folder
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
                    deletion_summary["s3_files_deleted"] += len(batch)
                
                logger.info(f"✅ Deleted {deletion_summary['s3_files_deleted']} files from S3")
            else:
                logger.info(f"ℹ️ No S3 files found for restaurant {restaurant_id}")
                
        except Exception as e:
            error_msg = f"Error deleting S3 files: {str(e)}"
            logger.error(f"❌ {error_msg}")
            deletion_summary["errors"].append(error_msg)
        
        # ============= STEP 2: DELETE ALL DATABASE RECORDS =============
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            
            # Delete sales records
            try:
                logger.info(f"🗑️ Deleting sales records...")
                cur.execute("DELETE FROM sales_graphs WHERE restaurant_id = %s", (restaurant_id,))
                deletion_summary["database_records_deleted"]["sales"] = cur.rowcount
                logger.info(f"✅ Deleted {cur.rowcount} sales records")
            except Exception as e:
                error_msg = f"Error deleting sales: {str(e)}"
                logger.error(f"❌ {error_msg}")
                deletion_summary["errors"].append(error_msg)
            
            # Delete inventory records
            try:
                logger.info(f"🗑️ Deleting inventory records...")
                cur.execute("DELETE FROM inventory_graphs WHERE restaurant_id = %s", (restaurant_id,))
                deletion_summary["database_records_deleted"]["inventory"] = cur.rowcount
                logger.info(f"✅ Deleted {cur.rowcount} inventory records")
            except Exception as e:
                error_msg = f"Error deleting inventory: {str(e)}"
                logger.error(f"❌ {error_msg}")
                deletion_summary["errors"].append(error_msg)
            
            # Delete menu records
            try:
                logger.info(f"🗑️ Deleting menu records...")
                cur.execute("DELETE FROM menu_graphs WHERE restaurant_id = %s", (restaurant_id,))
                deletion_summary["database_records_deleted"]["menu"] = cur.rowcount
                logger.info(f"✅ Deleted {cur.rowcount} menu records")
            except Exception as e:
                error_msg = f"Error deleting menu: {str(e)}"
                logger.error(f"❌ {error_msg}")
                deletion_summary["errors"].append(error_msg)
            
            # Delete employee records
            try:
                logger.info(f"🗑️ Deleting employee records...")
                cur.execute("DELETE FROM employees_graphs WHERE restaurant_id = %s", (restaurant_id,))
                deletion_summary["database_records_deleted"]["employees"] = cur.rowcount
                logger.info(f"✅ Deleted {cur.rowcount} employee records")
            except Exception as e:
                error_msg = f"Error deleting employees: {str(e)}"
                logger.error(f"❌ {error_msg}")
                deletion_summary["errors"].append(error_msg)
            
            # Delete staff_info records
            try:
                logger.info(f"🗑️ Deleting staff_info records...")
                cur.execute("DELETE FROM staff_info WHERE restaurant_id = %s", (restaurant_id,))
                deletion_summary["database_records_deleted"]["staff_info"] = cur.rowcount
                logger.info(f"✅ Deleted {cur.rowcount} staff_info records")
            except Exception as e:
                error_msg = f"Error deleting staff_info: {str(e)}"
                logger.error(f"❌ {error_msg}")
                deletion_summary["errors"].append(error_msg)
            
            # Delete restaurant assignments
            try:
                logger.info(f"🗑️ Deleting restaurant assignments...")
                cur.execute("DELETE FROM restaurant_assignments WHERE restaurant_id = %s", (restaurant_id,))
                deletion_summary["database_records_deleted"]["assignments"] = cur.rowcount
                logger.info(f"✅ Deleted {cur.rowcount} restaurant assignments")
            except Exception as e:
                error_msg = f"Error deleting assignments: {str(e)}"
                logger.error(f"❌ {error_msg}")
                deletion_summary["errors"].append(error_msg)
            
            # Delete the restaurant itself (soft delete - set active=false)
            try:
                logger.info(f"🗑️ Soft deleting restaurant record...")
                cur.execute("""
                    UPDATE restaurants 
                    SET active = false, 
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (restaurant_id,))
                logger.info(f"✅ Restaurant marked as inactive")
            except Exception as e:
                error_msg = f"Error deleting restaurant: {str(e)}"
                logger.error(f"❌ {error_msg}")
                deletion_summary["errors"].append(error_msg)
            
            # Commit all database changes
            conn.commit()
            logger.info(f"✅ All database changes committed")
            
        except Exception as e:
            conn.rollback()
            error_msg = f"Database error during deletion: {str(e)}"
            logger.error(f"❌ {error_msg}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            deletion_summary["errors"].append(error_msg)
            raise HTTPException(status_code=500, detail=error_msg)
        finally:
            cur.close()
            return_db_connection(conn)
        
        # Calculate total records deleted
        total_db_records = sum(deletion_summary["database_records_deleted"].values())
        
        logger.info(f"✅ Restaurant deletion complete!")
        logger.info(f"   - S3 files deleted: {deletion_summary['s3_files_deleted']}")
        logger.info(f"   - Database records deleted: {total_db_records}")
        
        return {
            "message": f"Restaurant '{restaurant['name']}' deleted successfully",
            "status": "success" if not deletion_summary["errors"] else "partial_success",
            "summary": deletion_summary,
            "total_db_records_deleted": total_db_records
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error in delete_restaurant_completely: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error deleting restaurant: {str(e)}")

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