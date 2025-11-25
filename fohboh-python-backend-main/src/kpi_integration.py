# kpi_integration.py
"""
Integration layer between database and KPI Calculator
Converts database query results to pandas DataFrames for KPI calculations
Maps database columns to match comprehensive KPI Calculator expectations
"""

import pandas as pd
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)


class KPIDataAdapter:
    """Adapts database query results to pandas DataFrames for KPI calculations"""
    
    def __init__(self, db_connection):
        self.db_connection = db_connection
    
    def fetch_data_for_kpis(self, store_id: str, start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
        """
        Fetch all required data from database and convert to DataFrames
        
        Args:
            store_id: Store identifier
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        
        Returns:
            Dictionary with DataFrames: sales_df, inventory_df, menu_df, labor_df
        """
        try:
            cursor = self.db_connection.cursor()
            
            # Fetch Sales Data
            logger.info(f"Fetching sales data for {store_id} from {start_date} to {end_date}")
            sales_df = self._fetch_sales_data(cursor, store_id, start_date, end_date)
            
            # Fetch Inventory Data
            logger.info(f"Fetching inventory data for {store_id}")
            inventory_df = self._fetch_inventory_data(cursor, store_id, start_date, end_date)
            
            # Fetch Menu Data
            logger.info(f"Fetching menu data for {store_id}")
            menu_df = self._fetch_menu_data(cursor, store_id)
            
            # Fetch Labor/Employee Data
            logger.info(f"Fetching employee data for {store_id}")
            labor_df = self._fetch_employee_data(cursor, store_id)
            
            cursor.close()
            
            logger.info(f"Data fetch complete - Sales: {len(sales_df)}, Inventory: {len(inventory_df)}, "
                       f"Menu: {len(menu_df)}, Employees: {len(labor_df)}")
            
            return {
                'sales_df': sales_df,
                'inventory_df': inventory_df,
                'menu_df': menu_df,
                'labor_df': labor_df
            }
            
        except Exception as e:
            logger.error(f"Error fetching data for KPIs: {e}")
            raise
    
    def _fetch_sales_data(self, cursor, store_id: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Fetch sales data and convert to DataFrame matching KPI Calculator format
        
        Database columns → KPI Calculator expected columns:
        - sold_items_name → items_sold
        - sale_date → date
        - sale_time → time
        - subtotal → subtotal, gross_sales
        - total_amount → total_amount
        - guest_count → covers
        - discount_applied → discount_percent (needs conversion)
        """
        
        query = """
            SELECT 
                sale_id,
                sale_date,
                sale_time,
                sold_items_name,
                number_of_items,
                subtotal,
                tip,
                total_amount,
                payment_method,
                order_type,
                customer_id,
                is_loyalty,
                promotion_id,
                discount_applied,
                table_number,
                guest_count,
                void_status,
                reason,
                daypart
            FROM store_sales
            WHERE store_id = %s
            AND sale_date >= %s
            AND sale_date <= %s
            ORDER BY sale_date, sale_time
        """
        
        cursor.execute(query, (store_id, start_date, end_date))
        results = cursor.fetchall()
        
        if not results:
            logger.warning(f"No sales data found for {store_id}")
            return pd.DataFrame()
        
        # Convert to list of dictionaries with proper column mapping
        sales_data = []
        for row in results:
            try:
                # Handle both dict-like and tuple-like results
                if hasattr(row, 'get'):
                    # Dict-like (RealDictCursor)
                    subtotal = float(row.get('subtotal') or 0)
                    total_amount = float(row.get('total_amount') or 0)
                    discount_applied = float(row.get('discount_applied') or 0)
                    void_status = row.get('void_status')
                    
                    # Calculate discount percentage from discount amount
                    discount_percent = 0
                    if subtotal > 0 and discount_applied > 0:
                        discount_percent = (discount_applied / subtotal) * 100
                    
                    # Determine comps and voids
                    comps = 0
                    voids = 0
                    if void_status is True or void_status == 'TRUE':
                        voids = abs(total_amount)
                    elif total_amount == 0 and subtotal > 0:
                        comps = subtotal
                    
                    sale_dict = {
                        # Required columns for KPI Calculator
                        'sale_id': row.get('sale_id'),
                        'date': row.get('sale_date'),  # Will be converted to datetime
                        'time': row.get('sale_time'),
                        'items_sold': row.get('sold_items_name'),  # DB: sold_items_name → items_sold
                        'number_of_items': float(row.get('number_of_items') or 0),
                        'subtotal': subtotal,
                        'gross_sales': subtotal,  # KPI Calculator expects this
                        'tip': float(row.get('tip') or 0),
                        'total_amount': total_amount,
                        'covers': int(row.get('guest_count') or 1),  # DB: guest_count → covers
                        
                        # Discount/Promo columns
                        'discount_percent': round(discount_percent, 2),
                        'discount_applied': discount_applied,
                        'comps': comps,
                        'voids': voids,
                        'promos': discount_applied,
                        'promotion_id': row.get('promotion_id'),
                        
                        # Additional columns
                        'payment_method': row.get('payment_method'),
                        'order_type': row.get('order_type'),
                        'customer_id': row.get('customer_id'),
                        'is_loyalty': row.get('is_loyalty'),
                        'is_loyalty_member': row.get('is_loyalty'),  # Alias for compatibility
                        'table_number': row.get('table_number'),
                        'void_status': void_status,
                        'reason': row.get('reason'),
                        'daypart': row.get('daypart')
                    }
                else:
                    # Tuple-style access (standard cursor)
                    subtotal = float(row[5] or 0)
                    total_amount = float(row[7] or 0)
                    discount_applied = float(row[13] or 0)
                    void_status = row[16] if len(row) > 16 else None
                    
                    # Calculate discount percentage
                    discount_percent = 0
                    if subtotal > 0 and discount_applied > 0:
                        discount_percent = (discount_applied / subtotal) * 100
                    
                    # Determine comps and voids
                    comps = 0
                    voids = 0
                    if void_status is True or void_status == 'TRUE':
                        voids = abs(total_amount)
                    elif total_amount == 0 and subtotal > 0:
                        comps = subtotal
                    
                    sale_dict = {
                        'sale_id': row[0],
                        'date': row[1],
                        'time': row[2],
                        'items_sold': row[3],
                        'number_of_items': float(row[4] or 0),
                        'subtotal': subtotal,
                        'gross_sales': subtotal,
                        'tip': float(row[6] or 0),
                        'total_amount': total_amount,
                        'covers': int(row[15] or 1),
                        'discount_percent': round(discount_percent, 2),
                        'discount_applied': discount_applied,
                        'comps': comps,
                        'voids': voids,
                        'promos': discount_applied,
                        'promotion_id': row[12],
                        'payment_method': row[8],
                        'order_type': row[9],
                        'customer_id': row[10],
                        'is_loyalty': row[11],
                        'is_loyalty_member': row[11],
                        'table_number': row[14],
                        'void_status': void_status,
                        'reason': row[17] if len(row) > 17 else None,
                        'daypart': row[18] if len(row) > 18 else None
                    }
                
                sales_data.append(sale_dict)
                
            except Exception as row_error:
                logger.warning(f"Error processing sales row: {row_error}")
                continue
        
        df = pd.DataFrame(sales_data)
        
        # Convert date to datetime
        if not df.empty and 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
        
        # Add hour column for time-of-day analysis
        if not df.empty and 'time' in df.columns:
            try:
                df['hour'] = pd.to_datetime(df['time'], format='%H:%M:%S', errors='coerce').dt.hour
            except:
                df['hour'] = None
        
        logger.info(f"Processed {len(df)} sales records")
        return df
    
    def _fetch_inventory_data(self, cursor, store_id: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Fetch inventory data and convert to DataFrame
        
        Database columns → KPI Calculator expected columns:
        - inventory_date → date
        - All other columns map directly
        """
        
        query = """
            SELECT 
                inventory_date,
                ingredient,
                quantity,
                par_level,
                unit_cost,
                is_low,
                waste
            FROM store_inventory
            WHERE store_id = %s
            AND inventory_date >= %s
            AND inventory_date <= %s
            ORDER BY inventory_date, ingredient
        """
        
        cursor.execute(query, (store_id, start_date, end_date))
        results = cursor.fetchall()
        
        if not results:
            logger.warning(f"No inventory data found for {store_id}")
            return pd.DataFrame()
        
        inventory_data = []
        for row in results:
            try:
                if hasattr(row, 'get'):
                    inv_dict = {
                        'date': row.get('inventory_date'),  # DB: inventory_date → date
                        'ingredient': row.get('ingredient'),
                        'quantity': float(row.get('quantity') or 0),
                        'par_level': float(row.get('par_level') or 0),
                        'unit_cost': float(row.get('unit_cost') or 0),
                        'is_low': row.get('is_low'),
                        'waste': float(row.get('waste') or 0)
                    }
                else:
                    inv_dict = {
                        'date': row[0],
                        'ingredient': row[1],
                        'quantity': float(row[2] or 0),
                        'par_level': float(row[3] or 0),
                        'unit_cost': float(row[4] or 0),
                        'is_low': row[5],
                        'waste': float(row[6] or 0) if len(row) > 6 else 0
                    }
                
                inventory_data.append(inv_dict)
                
            except Exception as row_error:
                logger.warning(f"Error processing inventory row: {row_error}")
                continue
        
        df = pd.DataFrame(inventory_data)
        
        if not df.empty and 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
        
        logger.info(f"Processed {len(df)} inventory records")
        return df
    
    def _fetch_menu_data(self, cursor, store_id: str) -> pd.DataFrame:
        """
        Fetch menu/recipe data and convert to DataFrame
        All columns map directly - no transformation needed
        """
        
        query = """
            SELECT 
                menu_item,
                ingredient,
                amount,
                unit_cost
            FROM store_menu
            WHERE store_id = %s
            ORDER BY menu_item, ingredient
        """
        
        cursor.execute(query, (store_id,))
        results = cursor.fetchall()
        
        if not results:
            logger.warning(f"No menu data found for {store_id}")
            return pd.DataFrame()
        
        menu_data = []
        for row in results:
            try:
                if hasattr(row, 'get'):
                    menu_dict = {
                        'menu_item': row.get('menu_item'),
                        'ingredient': row.get('ingredient'),
                        'amount': float(row.get('amount') or 0),
                        'unit_cost': float(row.get('unit_cost') or 0)
                    }
                else:
                    menu_dict = {
                        'menu_item': row[0],
                        'ingredient': row[1],
                        'amount': float(row[2] or 0),
                        'unit_cost': float(row[3] or 0)
                    }
                
                menu_data.append(menu_dict)
                
            except Exception as row_error:
                logger.warning(f"Error processing menu row: {row_error}")
                continue
        
        df = pd.DataFrame(menu_data)
        logger.info(f"Processed {len(df)} menu records")
        return df
    
    def _fetch_employee_data(self, cursor, store_id: str) -> pd.DataFrame:
        """
        Fetch employee/labor data and convert to DataFrame
        
        Database columns → KPI Calculator expected columns:
        - role → position
        - Estimate hours_worked (160 hours/month for full-time)
        - Calculate is_salaried based on role
        """
        
        query = """
            SELECT 
                employee_id,
                name,
                role,
                hire_date,
                termination_date,
                hourly_rate
            FROM store_employees
            WHERE store_id = %s
            AND (termination_date IS NULL OR termination_date > CURRENT_DATE)
            ORDER BY name
        """
        
        cursor.execute(query, (store_id,))
        results = cursor.fetchall()
        
        if not results:
            logger.warning(f"No employee data found for {store_id}")
            return pd.DataFrame()
        
        employee_data = []
        for row in results:
            try:
                if hasattr(row, 'get'):
                    role = row.get('role', '')
                    hourly_rate = float(row.get('hourly_rate') or 0)
                    
                    # Determine if salaried based on role
                    is_salaried = any(keyword in str(role).lower() 
                                     for keyword in ['manager', 'supervisor', 'director', 'chef'])
                    
                    # Estimate hours worked (160 for full-time, 80 for part-time/hourly)
                    hours_worked = 160 if is_salaried else 120
                    
                    emp_dict = {
                        'employee_id': row.get('employee_id'),
                        'name': row.get('name'),
                        'position': role,  # DB: role → position
                        'hire_date': row.get('hire_date'),
                        'termination_date': row.get('termination_date'),
                        'hourly_rate': hourly_rate,
                        'is_salaried': is_salaried,
                        'hours_worked': hours_worked,
                        'overtime_hours': 0,  # Default to 0 (can be enhanced with actual data)
                        'date': datetime.now().date()  # Add current date for filtering
                    }
                else:
                    role = row[2] if len(row) > 2 else ''
                    hourly_rate = float(row[5] or 0) if len(row) > 5 else 0
                    
                    is_salaried = any(keyword in str(role).lower() 
                                     for keyword in ['manager', 'supervisor', 'director', 'chef'])
                    
                    hours_worked = 160 if is_salaried else 120
                    
                    emp_dict = {
                        'employee_id': row[0],
                        'name': row[1],
                        'position': role,
                        'hire_date': row[3] if len(row) > 3 else None,
                        'termination_date': row[4] if len(row) > 4 else None,
                        'hourly_rate': hourly_rate,
                        'is_salaried': is_salaried,
                        'hours_worked': hours_worked,
                        'overtime_hours': 0,
                        'date': datetime.now().date()
                    }
                
                employee_data.append(emp_dict)
                
            except Exception as row_error:
                logger.warning(f"Error processing employee row: {row_error}")
                continue
        
        df = pd.DataFrame(employee_data)
        logger.info(f"Processed {len(df)} employee records")
        return df


def calculate_kpis_from_database(store_id: str, start_date: str, end_date: str, 
                                 db_connection, time_period: str = None) -> Dict[str, Any]:
    """
    Main function to calculate KPIs using the comprehensive KPICalculator
    
    Args:
        store_id: Store identifier
        start_date: Start date for analysis (YYYY-MM-DD)
        end_date: End date for analysis (YYYY-MM-DD)
        db_connection: Database connection
        time_period: Optional time period string for metadata
    
    Returns:
        Dictionary with comprehensive KPI results
    """
    try:
        # Import comprehensive KPI Calculator
        from .kpi_calculator2 import KPICalculator
        
        # Initialize adapter and fetch data
        adapter = KPIDataAdapter(db_connection)
        data = adapter.fetch_data_for_kpis(store_id, start_date, end_date)
        
        # Initialize KPI Calculator
        calculator = KPICalculator()
        
        # Calculate all KPIs using the comprehensive calculator
        logger.info(f"Calculating KPIs for store {store_id}")
        results = calculator.calculate_all_kpis(
            sales_df=data['sales_df'],
            inventory_df=data['inventory_df'],
            menu_df=data['menu_df'],
            labor_df=data['labor_df'],
            time_period=time_period
        )
        
        # Add metadata
        if 'metadata' not in results:
            results['metadata'] = {}
        
        results['metadata']['store_id'] = store_id
        results['metadata']['date_range'] = {
            'start_date': start_date,
            'end_date': end_date
        }
        
        logger.info(f"✅ KPI calculation complete for {store_id}")
        return results
        
    except Exception as e:
        logger.error(f"Error calculating KPIs: {e}")
        logger.exception("Full error details:")
        raise