"""
Adora Database Helper - Manages connection to second database
"""
import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# Adora Database Configuration
DB_CONFIG_ADORA = {
    "host": os.getenv("DB_HOST2", "database-4.cboosuomg0xi.us-east-1.rds.amazonaws.com"),
    "database": os.getenv("DB_NAME2", "postgres"),
    "user": os.getenv("DB_USER2", "postgres"),
    "password": os.getenv("DB_PASSWORD2", "8JZDB3J9DsCA2yGzGKVf"),
    "port": int(os.getenv("DB_PORT2", "5432"))
}


def get_adora_db_connection():
    """
    Get connection to Adora database (DB2)
    Returns a psycopg2 connection with RealDictCursor factory
    """
    try:
        conn = psycopg2.connect(
            **DB_CONFIG_ADORA,
            cursor_factory=RealDictCursor
        )
        logger.info("✅ Connected to Adora database")
        return conn
    except Exception as e:
        logger.error(f"❌ Failed to connect to Adora database: {e}")
        raise


async def check_if_adora_restaurants(
    restaurant_names: List[str],
    conn
) -> Dict[str, Optional[str]]:
    """
    Check which restaurants are Adora restaurants (have store_id)
    
    Args:
        restaurant_names: List of restaurant names
        conn: Database connection to primary DB
        
    Returns:
        Dict mapping restaurant_name -> store_id (or None if not Adora)
        Example: {"Restaurant A": "LE5AR", "Restaurant B": None}
    """
    try:
        cur = conn.cursor()
        
        cur.execute("""
            SELECT name, store_id 
            FROM restaurants 
            WHERE name = ANY(%s) AND active = true
        """, (restaurant_names,))
        
        results = cur.fetchall()
        
        # Create mapping
        restaurant_store_map = {}
        for row in results:
            restaurant_name = row['name']
            store_id = row['store_id']
            restaurant_store_map[restaurant_name] = store_id
            
            if store_id:
                logger.info(f"🏪 {restaurant_name} is an Adora store (ID: {store_id})")
            else:
                logger.info(f"🏠 {restaurant_name} is a regular restaurant")
        
        return restaurant_store_map
        
    except Exception as e:
        logger.error(f"Error checking Adora restaurants: {e}")
        return {}


async def get_store_ids_for_restaurants(
    restaurant_names: List[str],
    conn
) -> List[str]:
    """
    Get store_ids for Adora restaurants only
    
    Args:
        restaurant_names: List of restaurant names
        conn: Database connection to primary DB
        
    Returns:
        List of store_ids (only for Adora restaurants)
    """
    restaurant_map = await check_if_adora_restaurants(restaurant_names, conn)
    
    # Extract only non-None store_ids
    store_ids = [
        store_id for store_id in restaurant_map.values() 
        if store_id is not None
    ]
    
    logger.info(f"📋 Found {len(store_ids)} Adora store IDs: {store_ids}")
    return store_ids