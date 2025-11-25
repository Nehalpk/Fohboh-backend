import psycopg2
import psycopg2.errors
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)

def init_adora_pos_tables(conn):
    """Initialize Adora POS database tables with deadlock prevention"""
    if not conn or conn.closed:
        logger.error("❌ Database connection is closed or invalid")
        return False
        
    try:
        cur = conn.cursor()
        
        # Use a shorter lock timeout to detect deadlocks faster
        cur.execute("SET lock_timeout = '10s'")
        
        # Create adora_pos_menu_items table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS adora_pos_menu_items (
                id SERIAL PRIMARY KEY,
                store_id VARCHAR(50) NOT NULL,
                item_id VARCHAR(100),
                name VARCHAR(255) NOT NULL,
                description TEXT,
                category VARCHAR(100),
                price DECIMAL(10,2),
                cost DECIMAL(10,2),
                active BOOLEAN DEFAULT true,
                data_json JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create adora_pos_orders table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS adora_pos_orders (
                id SERIAL PRIMARY KEY,
                store_id VARCHAR(50) NOT NULL,
                order_id VARCHAR(100),
                order_date DATE NOT NULL,
                order_time TIMESTAMP,
                total_amount DECIMAL(10,2),
                customer_name VARCHAR(255),
                status VARCHAR(50),
                items_json JSONB,
                data_json JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(store_id, order_id, order_date)
            )
        """)
        
        # Create adora_pos_sales table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS adora_pos_sales (
                id SERIAL PRIMARY KEY,
                store_id VARCHAR(50) NOT NULL,
                sale_date DATE NOT NULL,
                total_revenue DECIMAL(10,2),
                total_orders INTEGER,
                avg_order_value DECIMAL(10,2),
                top_items JSONB,
                hourly_breakdown JSONB,
                data_json JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(store_id, sale_date)
            )
        """)
        
        # Create adora_pos_customers table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS adora_pos_customers (
                id SERIAL PRIMARY KEY,
                store_id VARCHAR(50) NOT NULL,
                customer_id VARCHAR(100),
                name VARCHAR(255),
                email VARCHAR(255),
                phone VARCHAR(50),
                last_visit_date DATE,
                total_visits INTEGER DEFAULT 0,
                total_spent DECIMAL(10,2) DEFAULT 0,
                data_json JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(store_id, customer_id)
            )
        """)
        
        # Create adora_pos_chat_history table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS adora_pos_chat_history (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                store_id VARCHAR(50) NOT NULL,
                conversation_id VARCHAR(100),
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                data_context JSONB,
                processing_time_ms INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes for better performance
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_adora_orders_date 
            ON adora_pos_orders(store_id, order_date);
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_adora_sales_date 
            ON adora_pos_sales(store_id, sale_date);
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_adora_chat_history_user 
            ON adora_pos_chat_history(user_id, created_at);
        """)
        
        conn.commit()
        cur.close()
        logger.info("✅ Adora POS database tables initialized successfully")
        return True
        
    except psycopg2.errors.DeadlockDetected as e:
        try:
            if conn and not conn.closed:
                conn.rollback()
        except:
            pass
        logger.warning(f"⚠️ Deadlock detected during Adora POS table initialization: {str(e)}")
        return False
        
    except psycopg2.errors.LockNotAvailable as e:
        try:
            if conn and not conn.closed:
                conn.rollback()
        except:
            pass
        logger.warning(f"⚠️ Lock timeout during Adora POS table initialization: {str(e)}")
        return False
        
    except Exception as e:
        try:
            if conn and not conn.closed:
                conn.rollback()
        except:
            pass
        logger.error(f"❌ Error initializing Adora POS tables: {str(e)}")
        return False

def save_menu_data(conn, store_id: str, menu_data: Dict[str, Any]):
    """Save menu data to database"""
    try:
        cur = conn.cursor()
        
        # Clear existing menu data for this store
        cur.execute("DELETE FROM adora_pos_menu_items WHERE store_id = %s", (store_id,))
        
        if isinstance(menu_data, dict) and 'result' in menu_data:
            menu_items = menu_data['result']
        elif isinstance(menu_data, list):
            menu_items = menu_data
        else:
            menu_items = [menu_data]
        
        # Insert new menu data
        for item in menu_items:
            cur.execute("""
                INSERT INTO adora_pos_menu_items 
                (store_id, item_id, name, description, category, price, cost, data_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                store_id,
                item.get('id', ''),
                item.get('name', ''),
                item.get('description', ''),
                item.get('category', ''),
                float(item.get('price', 0)) if item.get('price') else 0,
                float(item.get('cost', 0)) if item.get('cost') else 0,
                json.dumps(item)
            ))
        
        conn.commit()
        logger.info(f"✅ Saved {len(menu_items)} menu items for store {store_id}")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error saving menu data: {str(e)}")
        raise

def save_orders_data(conn, store_id: str, orders_data: Dict[str, Any], order_date: str):
    """Save orders data to database"""
    try:
        cur = conn.cursor()
        
        if isinstance(orders_data, dict) and 'result' in orders_data:
            orders = orders_data['result']
        elif isinstance(orders_data, list):
            orders = orders_data
        else:
            orders = [orders_data]
        
        for order in orders:
            try:
                order_time = None
                if order.get('created_at'):
                    try:
                        order_time = datetime.fromisoformat(order['created_at'].replace('Z', '+00:00'))
                    except:
                        pass
                
                cur.execute("""
                    INSERT INTO adora_pos_orders 
                    (store_id, order_id, order_date, order_time, total_amount, 
                     customer_name, status, items_json, data_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (store_id, order_id, order_date) DO UPDATE SET
                    total_amount = EXCLUDED.total_amount,
                    items_json = EXCLUDED.items_json,
                    data_json = EXCLUDED.data_json
                """, (
                    store_id,
                    order.get('id', ''),
                    order_date,
                    order_time,
                    float(order.get('total', 0)) if order.get('total') else 0,
                    order.get('customer_name', ''),
                    order.get('status', ''),
                    json.dumps(order.get('items', [])),
                    json.dumps(order)
                ))
            except Exception as e:
                logger.warning(f"Failed to save order {order.get('id', '')}: {str(e)}")
                continue
        
        conn.commit()
        logger.info(f"✅ Saved {len(orders)} orders for store {store_id} on {order_date}")
        
        # Generate and save sales summary after saving orders
        try:
            save_sales_summary(conn, store_id, order_date, orders)
        except Exception as e:
            logger.warning(f"Failed to generate sales summary: {str(e)}")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error saving orders data: {str(e)}")
        raise

def save_sales_summary(conn, store_id: str, sale_date: str, orders_data: List[Dict]):
    """Calculate and save sales summary from orders data"""
    try:
        cur = conn.cursor()
        
        total_revenue = 0
        total_orders = len(orders_data)
        item_counts = {}
        hourly_breakdown = {}
        
        for order in orders_data:
            order_total = float(order.get('total', 0))
            total_revenue += order_total
            
            # Count items
            for item in order.get('items', []):
                item_name = item.get('menu_item_name', 'Unknown')
                quantity = int(item.get('quantity', 1))
                item_counts[item_name] = item_counts.get(item_name, 0) + quantity
            
            # Track hourly sales
            if order.get('created_at'):
                try:
                    hour = datetime.fromisoformat(order['created_at'].replace('Z', '+00:00')).hour
                    hourly_breakdown[str(hour)] = hourly_breakdown.get(str(hour), 0) + order_total
                except:
                    pass
        
        avg_order_value = total_revenue / total_orders if total_orders > 0 else 0
        
        # Get top 10 items
        top_items = dict(sorted(item_counts.items(), key=lambda x: x[1], reverse=True)[:10])
        
        cur.execute("""
            INSERT INTO adora_pos_sales 
            (store_id, sale_date, total_revenue, total_orders, avg_order_value, 
             top_items, hourly_breakdown, data_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (store_id, sale_date) DO UPDATE SET
            total_revenue = EXCLUDED.total_revenue,
            total_orders = EXCLUDED.total_orders,
            avg_order_value = EXCLUDED.avg_order_value,
            top_items = EXCLUDED.top_items,
            hourly_breakdown = EXCLUDED.hourly_breakdown,
            data_json = EXCLUDED.data_json
        """, (
            store_id,
            sale_date,
            total_revenue,
            total_orders,
            avg_order_value,
            json.dumps(top_items),
            json.dumps(hourly_breakdown),
            json.dumps({
                'total_revenue': total_revenue,
                'total_orders': total_orders,
                'avg_order_value': avg_order_value
            })
        ))
        
        conn.commit()
        logger.info(f"✅ Saved sales summary for {store_id} on {sale_date}")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error saving sales summary: {str(e)}")
        raise

def get_last_7_days_data(conn, store_id: str) -> Dict[str, Any]:
    """Get comprehensive data for last 7 days"""
    try:
        cur = conn.cursor()
        
        # Get date range
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=6)
        
        # Get sales summary
        cur.execute("""
            SELECT sale_date, total_revenue, total_orders, avg_order_value, 
                   top_items, hourly_breakdown
            FROM adora_pos_sales 
            WHERE store_id = %s AND sale_date BETWEEN %s AND %s
            ORDER BY sale_date DESC
        """, (store_id, start_date, end_date))
        
        sales_data = []
        for row in cur.fetchall():
            sales_data.append({
                'date': row[0].strftime('%Y-%m-%d'),
                'total_revenue': float(row[1]) if row[1] else 0,
                'total_orders': row[2] or 0,
                'avg_order_value': float(row[3]) if row[3] else 0,
                'top_items': row[4] if row[4] else {},
                'hourly_breakdown': row[5] if row[5] else {}
            })
        
        # Get menu items
        cur.execute("""
            SELECT name, category, price, cost 
            FROM adora_pos_menu_items 
            WHERE store_id = %s AND active = true
        """, (store_id,))
        
        menu_items = []
        for row in cur.fetchall():
            menu_items.append({
                'name': row[0],
                'category': row[1],
                'price': float(row[2]) if row[2] else 0,
                'cost': float(row[3]) if row[3] else 0
            })
        
        # Get recent orders
        cur.execute("""
            SELECT order_date, total_amount, items_json
            FROM adora_pos_orders 
            WHERE store_id = %s AND order_date BETWEEN %s AND %s
            ORDER BY order_date DESC, order_time DESC
            LIMIT 100
        """, (store_id, start_date, end_date))
        
        recent_orders = []
        for row in cur.fetchall():
            recent_orders.append({
                'date': row[0].strftime('%Y-%m-%d'),
                'total': float(row[1]) if row[1] else 0,
                'items': row[2] if row[2] else []
            })
        
        return {
            'sales_summary': sales_data,
            'menu_items': menu_items,
            'recent_orders': recent_orders,
            'date_range': {
                'start': start_date.strftime('%Y-%m-%d'),
                'end': end_date.strftime('%Y-%m-%d')
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting last 7 days data: {str(e)}")
        return {}

def save_chat_history(conn, user_id: int, store_id: str, conversation_id: str, 
                     question: str, answer: str, data_context: Dict, processing_time_ms: int):
    """Save chat interaction to database"""
    try:
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO adora_pos_chat_history 
            (user_id, store_id, conversation_id, question, answer, data_context, processing_time_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            user_id,
            store_id,
            conversation_id,
            question,
            answer,
            json.dumps(data_context),
            processing_time_ms
        ))
        
        conn.commit()
        logger.info(f"✅ Saved chat history for user {user_id}")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error saving chat history: {str(e)}")

def cleanup_old_data(conn, store_id: str, days_to_keep: int = 30):
    """Clean up old data beyond specified days"""
    try:
        cur = conn.cursor()
        cutoff_date = datetime.now().date() - timedelta(days=days_to_keep)
        
        # Clean up old orders
        cur.execute("""
            DELETE FROM adora_pos_orders 
            WHERE store_id = %s AND order_date < %s
        """, (store_id, cutoff_date))
        
        # Clean up old sales data
        cur.execute("""
            DELETE FROM adora_pos_sales 
            WHERE store_id = %s AND sale_date < %s
        """, (store_id, cutoff_date))
        
        # Clean up old chat history (keep 90 days)
        chat_cutoff = datetime.now() - timedelta(days=90)
        cur.execute("""
            DELETE FROM adora_pos_chat_history 
            WHERE store_id = %s AND created_at < %s
        """, (store_id, chat_cutoff))
        
        conn.commit()
        logger.info(f"✅ Cleaned up old data for store {store_id}")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error cleaning up old data: {str(e)}") 