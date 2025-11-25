"""
Simple Prompt Executor - Matches text and runs SQL queries or KPI calculations
"""
import json
import logging
import os
import re
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import psycopg2.extras
import pandas as pd
import numpy as np

# Import KPI Calculator
from .kpi_calculator import KPICalculator

logger = logging.getLogger(__name__)


class SimplePromptExecutor:
    """Execute SQL queries or KPI calculations based on simple text matching"""
    
    def __init__(self, conn):
        self.conn = conn
        self.prompts = self._load_prompts()
        self.kpi_calculator = KPICalculator()


        self.column_mappings = {
            'sales_graphs': {
                'total amount': 'total_amount',
                'total_amount': 'total_amount',
                'amount': 'total_amount',
                'subtotal': 'subtotal',
                'tips': 'tip',
                'tip': 'tip',
                'comps': 'comps',
                'voids': 'voids',
                'promos': 'promos',
                'discount': 'discount_applied',
                'tax': 'tax',
                'revenue': 'total_amount'
            },
            'inventory_graphs': {
                'quantity': 'quantity',
                'stock': 'quantity',
                'amount': 'quantity',
                'unit cost': 'unit_cost',
                'cost': 'unit_cost',
                'par level': 'par_level',
                'par': 'par_level'
            },
            'menu_graphs': {
                'selling price': 'selling_price',
                'price': 'selling_price',
                'unit cost': 'unit_cost',
                'cost': 'unit_cost',
                'profit margin': 'profit_margin',
                'margin': 'profit_margin'
            },
            'employees_graphs': {
                'hours worked': 'hours_worked',
                'hours': 'hours_worked',
                'total wages': 'total_wages',
                'wages': 'total_wages',
                'hourly rate': 'hourly_rate',
                'rate': 'hourly_rate',
                'overtime': 'overtime_hours',
                'overtime hours': 'overtime_hours'
            }
        }
    
    def _load_prompts(self) -> List[Dict]:
        """Load prompts from JSON file"""
        prompt_file = os.path.join(os.path.dirname(__file__), 'simple_prompts.json')
        try:
            with open(prompt_file, 'r') as f:
                data = json.load(f)
                logger.info(f"Loaded {len(data.get('prompts', []))} prompts")
                return data.get('prompts', [])
        except Exception as e:
            logger.error(f"Error loading prompts: {e}")
            return []
    
    def match_prompt(self, user_text: str) -> Optional[Dict]:
        """Find matching prompt based on text patterns"""
        user_text_lower = user_text.lower().strip()
        logger.info(f"🔍 Matching text: '{user_text_lower}'")
        
        # Check if query mentions a time period
        time_period_keywords = [
            'last week', 'past week', 'this week',
            'last 15 days', 'past 15 days', 'last fifteen days',
            'last month', 'past month', 'this month',
            'last 6 months', 'past 6 months', 'last six months',
            'last year', 'past year', 'this year',
            'all time', 'overall'
        ]
        has_time_period = any(keyword in user_text_lower for keyword in time_period_keywords)
        
        # First pass: Try to match KPI prompts if time period is mentioned
        if has_time_period:
            logger.info(f"⏰ Time period detected, prioritizing KPI prompts")
            for prompt in self.prompts:
                if prompt.get('category') == 'kpi':
                    for pattern in prompt['text_patterns']:
                        if pattern.lower() in user_text_lower:
                            logger.info(f"✅ Matched KPI pattern '{pattern}' in prompt '{prompt['id']}'")
                            return prompt
        
        # Second pass: Try date range prompts
        for prompt in self.prompts:
            if prompt.get('requires_date_range'):
                for pattern in prompt['text_patterns']:
                    if pattern.lower() in user_text_lower:
                        logger.info(f"✅ Matched date range pattern '{pattern}' in prompt '{prompt['id']}'")
                        return prompt
        
        # Third pass: Try regular prompts
        for prompt in self.prompts:
            # Skip date-specific prompts if time period is mentioned
            if has_time_period and prompt['id'] in ['sales_on_date']:
                continue
            
            for pattern in prompt['text_patterns']:
                if pattern.lower() in user_text_lower:
                    logger.info(f"✅ Matched pattern '{pattern}' in prompt '{prompt['id']}'")
                    return prompt
        
        logger.info("❌ No prompt matched")
        return None
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """
        Parse date from multiple formats:
        - dd/mm/yyyy
        - dd-mm-yyyy
        - yyyy-mm-dd
        - "6 november 2025"
        - "november 6 2025"
        - "6 nov 2025"
        """
        date_str = date_str.strip()
        
        # Try different date formats
        formats = [
            '%d/%m/%Y',      # 05/10/2025
            '%d-%m-%Y',      # 05-10-2025
            '%Y-%m-%d',      # 2025-10-05
            '%m/%d/%Y',      # 10/05/2025 (US format)
            '%d %B %Y',      # 6 November 2025
            '%B %d %Y',      # November 6 2025
            '%d %b %Y',      # 6 Nov 2025
            '%b %d %Y',      # Nov 6 2025
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        # Try relative dates
        date_str_lower = date_str.lower()
        if 'today' in date_str_lower:
            return datetime.now()
        elif 'yesterday' in date_str_lower:
            return datetime.now() - timedelta(days=1)
        
        return None
    
    def _extract_time_period(self, user_text: str) -> Optional[str]:
        """Extract time period from user text"""
        user_text_lower = user_text.lower()
        
        if any(term in user_text_lower for term in ['last week', 'past week', 'this week']):
            return 'Last_week'
        elif any(term in user_text_lower for term in ['last 15 days', 'past 15 days', 'last fifteen days']):
            return 'Last_15_days'
        elif any(term in user_text_lower for term in ['last month', 'past month', 'this month']):
            return 'Last_month'
        elif any(term in user_text_lower for term in ['last 6 months', 'past 6 months', 'last six months', 'past six months']):
            return 'Last_6_months'
        elif any(term in user_text_lower for term in ['last year', 'past year', 'this year']):
            return 'Last_year'
        elif any(term in user_text_lower for term in ['all time', 'total', 'overall', 'entire history']):
            return None
        
        return None

    def _load_restaurant_data(self, restaurant_names: List[str], time_period: Optional[str] = None) -> Dict[str, pd.DataFrame]:
        """
        Load data from database tables for KPI calculation
        
        Args:
            restaurant_names: List of restaurant names (e.g., ['Restaurant A', 'Restaurant B'])
            time_period: Optional time period filter (e.g., 'Last_week', 'Last_month', etc.)
            
        Returns:
            Dictionary containing 4 DataFrames:
            {
                'sales': DataFrame with sales data,
                'inventory': DataFrame with inventory data,
                'menu': DataFrame with menu data,
                'labor': DataFrame with labor/employee data
            }
        """
        try:
            logger.info(f"🏪 Loading data for restaurants: {restaurant_names}")
            logger.info(f"📅 Time period requested: {time_period or 'All time'}")
            
            # ============================================================
            # STEP 1: Get Restaurant IDs from Names
            # ============================================================
            # We need to convert restaurant names to IDs because the 
            # other tables use restaurant_id as foreign key
            
            cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT id, name FROM restaurants 
                WHERE name = ANY(%s) AND active = true
            """, (restaurant_names,))
            restaurant_rows = cur.fetchall()
            restaurant_ids = [row['id'] for row in restaurant_rows]
            
            # If no restaurants found, return empty DataFrames
            if not restaurant_ids:
                logger.warning(f"❌ No active restaurants found for names: {restaurant_names}")
                return {
                    'sales': pd.DataFrame(),
                    'inventory': pd.DataFrame(),
                    'menu': pd.DataFrame(),
                    'labor': pd.DataFrame()
                }
            
            logger.info(f"✅ Found {len(restaurant_ids)} restaurant(s): {[r['name'] for r in restaurant_rows]}")
            
            # ============================================================
            # STEP 2: Calculate Date Cutoff (if time_period specified)
            # ============================================================
            # This section converts time periods like 'Last_week' into 
            # actual dates by subtracting days from today
            
            cutoff_date = None
            
            if time_period:
                # Map time period strings to number of days
                days_map = {
                    'Last_week': 7,           # Last 7 days
                    'Last_15_days': 15,       # Last 15 days
                    'Last_month': 30,         # Last 30 days
                    'Last_6_months': 180,     # Last 180 days (6 months)
                    'Last_year': 365          # Last 365 days (1 year)
                }
                
                # Get the number of days for the requested period
                days = days_map.get(time_period)
                
                if days:
                    # Calculate the cutoff date
                    # Example: If today is Nov 6, 2025 and days=7
                    # cutoff_date = Nov 6 - 7 days = Oct 30, 2025
                    cutoff_datetime = datetime.now() - timedelta(days=days)
                    cutoff_date = cutoff_datetime.date()  # Convert to date only (no time)
                    logger.info(f"📆 Cutoff date calculated: {cutoff_date} ({days} days ago)")
                else:
                    logger.warning(f"⚠️ Unknown time period: {time_period}, loading all data")
            
            # If time_period is None or not recognized, cutoff_date stays None
            # This means we'll load ALL historical data (no date filter)
            
            # ============================================================
            # STEP 3: Check Available Data Range (Optional but helpful)
            # ============================================================
            # This helps us see what data actually exists in the database
            # before we try to filter it
            
            cur.execute("""
                SELECT 
                    MIN(date) as min_date, 
                    MAX(date) as max_date,
                    COUNT(*) as total_records
                FROM sales_graphs 
                WHERE restaurant_id = ANY(%s)
            """, (restaurant_ids,))
            date_info = cur.fetchone()
            
            if date_info and date_info['total_records'] > 0:
                logger.info(f"📊 Database date range: {date_info['min_date']} to {date_info['max_date']}")
                logger.info(f"   Total records in DB: {date_info['total_records']}")
                
                # Warn if our cutoff date is beyond available data
                # Example: If cutoff_date is Nov 1 but latest data is Oct 15,
                # we won't get any results
                if cutoff_date and date_info['max_date'] and cutoff_date > date_info['max_date']:
                    logger.warning(f"⚠️ Requested cutoff ({cutoff_date}) is after latest data ({date_info['max_date']})")
                    logger.warning(f"   No data will match this filter! Using all available data instead.")
                    cutoff_date = None  # Fall back to all data
            else:
                logger.warning(f"⚠️ No sales data found in database for these restaurants")
            
            # ============================================================
            # STEP 4: LOAD SALES DATA
            # ============================================================
            logger.info(f"💰 Loading sales data...")
            
            if cutoff_date:
                # Query WITH date filter (only recent data)
                sales_query = """
                    SELECT 
                        date,
                        subtotal as gross_sales,
                        COALESCE(comps, 0) as comps,
                        COALESCE(voids, 0) as voids,
                        COALESCE(promos, 0) as promos,
                        COALESCE(discount_applied, 0) as discount_amount,
                        items_sold,
                        number_of_items,
                        total_amount,
                        COALESCE(guest_count, 1) as covers,
                        payment_method,
                        order_type,
                        tip
                    FROM sales_graphs 
                    WHERE restaurant_id = ANY(%s)
                    AND date >= %s
                    ORDER BY date
                """
                logger.info(f"   Executing with cutoff: {cutoff_date}")
                cur.execute(sales_query, (restaurant_ids, cutoff_date))
            else:
                # Query WITHOUT date filter (all historical data)
                sales_query = """
                    SELECT 
                        date,
                        subtotal as gross_sales,
                        COALESCE(comps, 0) as comps,
                        COALESCE(voids, 0) as voids,
                        COALESCE(promos, 0) as promos,
                        COALESCE(discount_applied, 0) as discount_amount,
                        items_sold,
                        number_of_items,
                        total_amount,
                        COALESCE(guest_count, 1) as covers,
                        payment_method,
                        order_type,
                        tip
                    FROM sales_graphs 
                    WHERE restaurant_id = ANY(%s)
                    ORDER BY date
                """
                logger.info(f"   Executing for all time")
                cur.execute(sales_query, (restaurant_ids,))
            
            # Fetch results and convert to pandas DataFrame
            sales_results = cur.fetchall()
            sales_df = pd.DataFrame(sales_results)
            
            if not sales_df.empty:
                logger.info(f"✅ Loaded {len(sales_df)} sales records")
                logger.info(f"   Date range in results: {sales_df['date'].min()} to {sales_df['date'].max()}")
                logger.info(f"   Total gross sales: ${sales_df['gross_sales'].sum():,.2f}")
            else:
                logger.warning(f"⚠️ No sales data loaded")
            
            # ============================================================
            # STEP 5: LOAD INVENTORY DATA
            # ============================================================
            logger.info(f"📦 Loading inventory data...")
            
            if cutoff_date:
                inventory_query = """
                    SELECT 
                        ingredient,
                        quantity,
                        par_level,
                        unit_cost,
                        date
                    FROM inventory_graphs 
                    WHERE restaurant_id = ANY(%s)
                    AND date >= %s
                    ORDER BY date DESC
                """
                cur.execute(inventory_query, (restaurant_ids, cutoff_date))
            else:
                inventory_query = """
                    SELECT 
                        ingredient,
                        quantity,
                        par_level,
                        unit_cost,
                        date
                    FROM inventory_graphs 
                    WHERE restaurant_id = ANY(%s)
                    ORDER BY date DESC
                """
                cur.execute(inventory_query, (restaurant_ids,))
            
            inventory_results = cur.fetchall()
            inventory_df = pd.DataFrame(inventory_results)
            logger.info(f"{'✅' if not inventory_df.empty else '⚠️'} Loaded {len(inventory_df)} inventory records")
            
            # ============================================================
            # STEP 6: LOAD MENU DATA
            # ============================================================
            logger.info(f"🍽️ Loading menu data...")
            
            # NOTE: Menu data typically doesn't have date filtering
            # because menu items are relatively static
            menu_query = """
                SELECT 
                    item_name as menu_item,
                    ingredients as ingredient,
                    amount,
                    unit_cost,
                    selling_price as item_price,
                    category
                FROM menu_graphs 
                WHERE restaurant_id = ANY(%s)
            """
            cur.execute(menu_query, (restaurant_ids,))
            menu_results = cur.fetchall()
            menu_df = pd.DataFrame(menu_results)
            logger.info(f"{'✅' if not menu_df.empty else '⚠️'} Loaded {len(menu_df)} menu records")
            
            # ============================================================
            # STEP 7: LOAD LABOR/EMPLOYEE DATA
            # ============================================================
            logger.info(f"👷 Loading labor data...")
            
            if cutoff_date:
                labor_query = """
                    SELECT 
                        employee_id,
                        employee_name,
                        position,
                        role,
                        hours_worked,
                        COALESCE(overtime_hours, 0) as overtime_hours,
                        hourly_rate,
                        total_wages,
                        date,
                        CASE 
                            WHEN position ILIKE '%manager%' OR position ILIKE '%chef%' 
                            THEN true 
                            ELSE false 
                        END as is_salaried
                    FROM employees_graphs 
                    WHERE restaurant_id = ANY(%s)
                    AND date >= %s
                    ORDER BY date
                """
                cur.execute(labor_query, (restaurant_ids, cutoff_date))
            else:
                labor_query = """
                    SELECT 
                        employee_id,
                        employee_name,
                        position,
                        role,
                        hours_worked,
                        COALESCE(overtime_hours, 0) as overtime_hours,
                        hourly_rate,
                        total_wages,
                        date,
                        CASE 
                            WHEN position ILIKE '%manager%' OR position ILIKE '%chef%' 
                            THEN true 
                            ELSE false 
                        END as is_salaried
                    FROM employees_graphs 
                    WHERE restaurant_id = ANY(%s)
                    ORDER BY date
                """
                cur.execute(labor_query, (restaurant_ids,))
            
            labor_results = cur.fetchall()
            labor_df = pd.DataFrame(labor_results)
            logger.info(f"{'✅' if not labor_df.empty else '⚠️'} Loaded {len(labor_df)} labor records")
            
            if not labor_df.empty and 'date' in labor_df.columns:
                logger.info(f"   Labor date range: {labor_df['date'].min()} to {labor_df['date'].max()}")
            
            # ============================================================
            # STEP 8: Close Database Cursor
            # ============================================================
            cur.close()
            
            # ============================================================
            # STEP 9: Log Summary
            # ============================================================
            logger.info(f"📋 Data loading summary:")
            logger.info(f"   Sales: {len(sales_df)} records")
            logger.info(f"   Inventory: {len(inventory_df)} records")
            logger.info(f"   Menu: {len(menu_df)} records")
            logger.info(f"   Labor: {len(labor_df)} records")
            
            # ============================================================
            # STEP 10: Return All Data as Dictionary
            # ============================================================
            return {
                'sales': sales_df,
                'inventory': inventory_df,
                'menu': menu_df,
                'labor': labor_df
            }
            
        except Exception as e:
            # If anything goes wrong, log error and return empty DataFrames
            logger.error(f"❌ Error loading restaurant data: {e}", exc_info=True)
            return {
                'sales': pd.DataFrame(),
                'inventory': pd.DataFrame(),
                'menu': pd.DataFrame(),
                'labor': pd.DataFrame()
            }
    def _execute_kpi_calculation(
    self, 
    prompt: Dict, 
    restaurant_names: List[str],
    user_text: str
    ) -> Optional[Dict]:
       """
       Execute KPI calculation based on prompt
       
       This function:
       1. Determines which KPI to calculate
       2. Extracts time period from user question
       3. Loads restaurant data
       4. Calculates the requested KPI(s)
       5. Formats results for AI
       
       Args:
           prompt: Matched prompt dictionary from simple_prompts.json
           restaurant_names: List of restaurant names to analyze
           user_text: Original user question
           
       Returns:
           Dictionary with calculation results or error
       """
       try:
           # ============================================================
           # STEP 1: Extract KPI Type and Time Period
           # ============================================================
           # Get which KPI to calculate from the prompt
           # Examples: 'total_sales', 'food_cost_pct', 'all_kpis'
           kpi_type = prompt.get('kpi_type')
           
           # Extract time period if the prompt supports it
           # Examples: 'Last_week', 'Last_month', None (for all time)
           time_period = self._extract_time_period(user_text) if prompt.get('supports_time_period') else None
           
           logger.info(f"📊 Calculating KPI: {kpi_type}")
           logger.info(f"📅 Time period: {time_period or 'All time'}")
           
           # ============================================================
           # STEP 2: Load Data from Database
           # ============================================================
           # This loads all 4 tables (sales, inventory, menu, labor)
           # filtered by time period if specified
           data = self._load_restaurant_data(restaurant_names, time_period)
           
           # Check if we have any data at all
           if all(df.empty for df in data.values()):
               return {
                   'matched': True,
                   'query_executed': False,
                   'error': 'No data available for KPI calculation',
                   'data_for_ai': None
               }
           
           # ============================================================
           # STEP 3: Calculate KPIs
           # ============================================================
           # Initialize results structure
           results = {'kpis': {}, 'errors': [], 'warnings': []}
           
           # Check if user wants ALL KPIs calculated
           if kpi_type == 'all_kpis':
               logger.info("📊 Calculating ALL KPIs...")
               results = self.kpi_calculator.calculate_all_kpis(
                   sales_df=data['sales'],
                   inventory_df=data['inventory'],
                   menu_df=data['menu'],
                   labor_df=data['labor'],
                   time_period=time_period
               )
           
           # Otherwise calculate specific KPI based on type
           else:
               logger.info(f"📊 Calculating specific KPI: {kpi_type}")
               
               # -------------------- KPI 1: Total Sales --------------------
               if kpi_type == 'total_sales' and not data['sales'].empty:
                   logger.info("   Calculating Total Sales...")
                   results['kpis']['total_sales'] = self.kpi_calculator.calculate_total_sales(data['sales'])
               
               # -------------------- KPI 2: Net Revenue --------------------
               elif kpi_type == 'net_revenue' and not data['sales'].empty:
                   logger.info("   Calculating Net Revenue...")
                   results['kpis']['net_revenue'] = self.kpi_calculator.calculate_net_revenue(data['sales'])
               
               # -------------------- KPI 3: SPLH (Sales per Labor Hour) --------------------
               elif kpi_type == 'splh' and not data['sales'].empty and not data['labor'].empty:
                   logger.info("   Calculating SPLH...")
                   results['kpis']['splh'] = self.kpi_calculator.calculate_splh(data['sales'], data['labor'])
               
               # -------------------- KPI 4: Guest Count --------------------
               elif kpi_type == 'guest_count' and not data['sales'].empty:
                   logger.info("   Calculating Guest Count...")
                   results['kpis']['guest_count'] = self.kpi_calculator.calculate_guest_count(data['sales'])
               
               # -------------------- KPI 5: Average Check --------------------
               elif kpi_type == 'avg_check' and not data['sales'].empty:
                   logger.info("   Calculating Average Check...")
                   results['kpis']['avg_check'] = self.kpi_calculator.calculate_avg_check(data['sales'])
               
               # -------------------- KPI 6: Top Selling Items --------------------
               elif kpi_type == 'top_items' and not data['sales'].empty:
                   logger.info("   Calculating Top Items...")
                   results['kpis']['top_items'] = self.kpi_calculator.calculate_top_items(data['sales'])
               
               # -------------------- KPI 7: Gross Profit per Item --------------------
               elif kpi_type == 'gross_profit_per_item' and not data['sales'].empty and not data['menu'].empty:
                   logger.info("   Calculating Gross Profit per Item...")
                   results['kpis']['gross_profit_per_item'] = self.kpi_calculator.calculate_gross_profit_per_item(
                       data['sales'], data['menu']
                   )
               
               # -------------------- KPI 8: Food Cost % --------------------
               elif kpi_type == 'food_cost_pct' and not data['sales'].empty and not data['menu'].empty:
                   logger.info("   Calculating Food Cost %...")
                   results['kpis']['food_cost_pct'] = self.kpi_calculator.calculate_food_cost_pct(
                       data['sales'], data['menu']
                   )
               
               # -------------------- KPI 9: COGS by Category --------------------
               elif kpi_type == 'cogs_by_category' and not data['sales'].empty and not data['menu'].empty:
                   logger.info("   Calculating COGS by Category...")
                   results['kpis']['cogs_by_category'] = self.kpi_calculator.calculate_cogs_by_category(
                       data['sales'], data['menu']
                   )
               
               # -------------------- KPI 10: Inventory Turnover --------------------
               elif kpi_type == 'inventory_turnover' and not data['sales'].empty and not data['menu'].empty and not data['inventory'].empty:
                   logger.info("   Calculating Inventory Turnover...")
                   results['kpis']['inventory_turnover'] = self.kpi_calculator.calculate_inventory_turnover(
                       data['sales'], data['menu'], data['inventory']
                   )
               
               # -------------------- KPI 19: Low Inventory Warnings --------------------
               elif kpi_type == 'low_inventory_warnings' and not data['inventory'].empty:
                   logger.info("   Calculating Low Inventory Warnings...")
                   results['kpis']['low_inventory_warnings'] = self.kpi_calculator.calculate_low_inventory_warnings(
                       data['inventory']
                   )
               
               # -------------------- KPI 15: Labor Hours by Role --------------------
               elif kpi_type == 'labor_hours_by_role' and not data['labor'].empty:
                   logger.info("   Calculating Labor Hours by Role...")
                   results['kpis']['labor_hours_by_role'] = self.kpi_calculator.calculate_labor_hours_by_role(
                       data['labor']
                   )
               
               # -------------------- KPI 16: Overtime % --------------------
               elif kpi_type == 'overtime_pct' and not data['labor'].empty:
                   logger.info("   Calculating Overtime %...")
                   results['kpis']['overtime_pct'] = self.kpi_calculator.calculate_overtime_pct(data['labor'])
               
               # -------------------- KPI 14: Popularity vs Profitability --------------------
               elif kpi_type == 'popularity_vs_profitability' and not data['sales'].empty and not data['menu'].empty:
                   logger.info("   Calculating Popularity vs Profitability...")
                   results['kpis']['popularity_vs_profitability'] = self.kpi_calculator.calculate_popularity_vs_profitability(
                       data['sales'], data['menu']
                   )
               
               # -------------------- KPI Not Available --------------------
               else:
                   logger.warning(f"⚠️ KPI '{kpi_type}' cannot be calculated - missing required data")
                   results['errors'].append({
                       'kpi': kpi_type,
                       'error': 'Missing required data tables',
                       'missing': [
                           'sales' if data['sales'].empty else None,
                           'inventory' if data['inventory'].empty else None,
                           'menu' if data['menu'].empty else None,
                           'labor' if data['labor'].empty else None
                       ]
                   })
           
           # ============================================================
           # STEP 4: Format Results for AI
           # ============================================================
           logger.info(f"✅ KPI calculation complete. Formatting for AI...")
           data_for_ai = self._format_kpi_results_for_ai(results, restaurant_names, time_period)
           
           # ============================================================
           # STEP 5: Return Results
           # ============================================================
           return {
               'matched': True,
               'query_executed': True,
               'prompt_id': prompt['id'],
               'result': results,
               'data_for_ai': data_for_ai
           }
           
       except Exception as e:
           # If anything goes wrong, log and return error
           logger.error(f"❌ Error executing KPI calculation: {e}", exc_info=True)
           return {
               'matched': True,
               'query_executed': False,
               'error': str(e),
               'data_for_ai': None
           }
       
    def _format_kpi_results_for_ai(self, results: Dict, restaurant_names: List[str], time_period: Optional[str]) -> str:
        """
        Format KPI calculation results into readable text for AI to understand
        
        This creates a human-readable summary that Claude can use to answer
        the user's question naturally.
        
        Args:
            results: Dictionary with KPI calculation results
            restaurant_names: List of restaurant names
            time_period: Time period used (e.g., 'Last_week', None for all time)
            
        Returns:
            Formatted string with all KPI results
        """
        # ============================================================
        # STEP 1: Create Header
        # ============================================================
        context = "=== KPI CALCULATION RESULTS ===\n\n"
        context += f"Restaurants: {', '.join(restaurant_names)}\n"
        context += f"Time Period: {time_period or 'All Time'}\n\n"
        
        # Extract KPIs from results
        kpis = results.get('kpis', {})
        
        # If no KPIs calculated, return error message
        if not kpis:
            context += "No KPIs were calculated. This may be due to missing data.\n"
            if results.get('errors'):
                context += "\nErrors:\n"
                for error in results['errors']:
                    context += f"- {error.get('kpi', 'Unknown')}: {error.get('error', 'Unknown error')}\n"
            return context
        
        # ============================================================
        # STEP 2: Format Each KPI
        # ============================================================
        
        # -------------------- KPI 1: Total Sales --------------------
        if 'total_sales' in kpis:
            kpi = kpis['total_sales']
            context += f"📊 **Total Sales**: ${kpi['value']:,.2f}\n"
            context += f"   Column used: {kpi.get('column_used', 'N/A')}\n"
            context += f"   Validation: {'✅ Passed' if kpi.get('validation_passed') else '⚠️ Warning'}\n\n"
        
        # -------------------- KPI 2: Net Revenue --------------------
        if 'net_revenue' in kpis:
            kpi = kpis['net_revenue']
            context += f"💰 **Net Revenue**: ${kpi['value']:,.2f}\n"
            context += f"   Gross Sales: ${kpi['gross_sales']:,.2f}\n"
            context += f"   Deductions:\n"
            for key, val in kpi['deductions'].items():
                context += f"      - {key.title()}: ${val:,.2f}\n"
            context += f"   Final Net: ${kpi['value']:,.2f}\n\n"
        
        # -------------------- KPI 3: SPLH (Sales per Labor Hour) --------------------
        if 'splh' in kpis:
            kpi = kpis['splh']
            if kpi['value']:
                context += f"⏱️ **Sales per Labor Hour (SPLH)**: ${kpi['value']:,.2f}/hour\n"
                context += f"   Net Revenue: ${kpi['net_revenue']:,.2f}\n"
                context += f"   Labor Hours: {kpi['labor_hours']:,.2f} hours\n"
                context += f"   Interpretation: For every hour worked, ${kpi['value']:,.2f} in sales generated\n\n"
            else:
                context += f"⏱️ **Sales per Labor Hour (SPLH)**: N/A (no labor hours)\n\n"
        
        # -------------------- KPI 4: Guest Count --------------------
        if 'guest_count' in kpis:
            kpi = kpis['guest_count']
            context += f"👥 **Guest Count**: {kpi['value']:,} guests\n"
            context += f"   Method: {kpi.get('method', 'N/A')}\n\n"
        
        # -------------------- KPI 5: Average Check --------------------
        if 'avg_check' in kpis:
            kpi = kpis['avg_check']
            if kpi['value']:
                context += f"🧾 **Average Check**: ${kpi['value']:,.2f} per guest\n"
                context += f"   Based on {kpi['guest_count']:,} guests\n"
                context += f"   Total Revenue: ${kpi['net_revenue']:,.2f}\n"
                context += f"   Interpretation: Each customer spends ${kpi['value']:,.2f} on average\n\n"
            else:
                context += f"🧾 **Average Check**: N/A (no guests)\n\n"
        
        # -------------------- KPI 6: Top Selling Items --------------------
        if 'top_items' in kpis:
            kpi = kpis['top_items']
            context += "🌟 **Top Selling Items**:\n"
            for i, item in enumerate(kpi['value'][:10], 1):
                context += f"   {i}. {item['item_name']}\n"
                context += f"      - Quantity Sold: {item['quantity_sold']}\n"
                context += f"      - Revenue: ${item['revenue']:,.2f}\n"
            context += f"\n   Total unique items: {kpi.get('total_unique_items', 'N/A')}\n\n"
        
        # -------------------- KPI 7: Gross Profit per Item --------------------
        if 'gross_profit_per_item' in kpis:
            kpi = kpis['gross_profit_per_item']
            context += "💵 **Gross Profit per Item** (Top 10 by profit):\n"
            for i, item in enumerate(kpi['value'][:10], 1):
                context += f"   {i}. {item['item_name']}\n"
                context += f"      - Revenue: ${item['revenue']:,.2f}\n"
                context += f"      - Cost: ${item['cost']:,.2f}\n"
                context += f"      - Gross Profit: ${item['gross_profit']:,.2f}\n"
                context += f"      - Margin: {item['margin_percent']:.2f}%\n"
                context += f"      - Qty Sold: {item['quantity_sold']}\n"
            context += "\n"
        
        # -------------------- KPI 8: Food Cost % --------------------
        if 'food_cost_pct' in kpis:
            kpi = kpis['food_cost_pct']
            if kpi['value']:
                context += f"🍽️ **Food Cost Percentage**: {kpi['value']:.2f}%\n"
                context += f"   Total Food Cost: ${kpi['total_food_cost']:,.2f}\n"
                context += f"   Total Food Sales: ${kpi['total_food_sales']:,.2f}\n"
                
                # Add interpretation
                if kpi['value'] < 25:
                    context += f"   ✅ Excellent! Food cost is low (ideal: 25-35%)\n"
                elif kpi['value'] <= 35:
                    context += f"   ✅ Good! Food cost is within healthy range (ideal: 25-35%)\n"
                elif kpi['value'] <= 40:
                    context += f"   ⚠️ Slightly high (ideal: 25-35%)\n"
                else:
                    context += f"   ❌ Too high! (ideal: 25-35%) - Review pricing or portion sizes\n"
                context += "\n"
            else:
                context += f"🍽️ **Food Cost Percentage**: N/A (missing data)\n\n"
        
        # -------------------- KPI 9: COGS by Category --------------------
        if 'cogs_by_category' in kpis:
            kpi = kpis['cogs_by_category']
            context += "📦 **COGS by Category**:\n"
            for cat in kpi['value']:
                context += f"   - {cat['category']}: ${cat['total_cogs']:,.2f}\n"
            context += f"\n   Total COGS: ${kpi['total_cogs']:,.2f}\n\n"
        
        # -------------------- KPI 10: Inventory Turnover --------------------
        if 'inventory_turnover' in kpis:
            kpi = kpis['inventory_turnover']
            if kpi['value']:
                context += f"🔄 **Inventory Turnover Rate**: {kpi['value']:.2f}x\n"
                context += f"   Total COGS: ${kpi['total_cogs']:,.2f}\n"
                context += f"   Avg Inventory Value: ${kpi['avg_inventory_value']:,.2f}\n"
                
                # Add interpretation
                if kpi['value'] < 4:
                    context += f"   ⚠️ Low turnover - inventory sitting too long\n"
                elif kpi['value'] <= 6:
                    context += f"   ✅ Good turnover rate\n"
                else:
                    context += f"   ⚠️ Very high turnover - may need more inventory buffer\n"
                context += "\n"
            else:
                context += f"🔄 **Inventory Turnover Rate**: N/A\n\n"
        
        # -------------------- KPI 19: Low Inventory Warnings --------------------
        if 'low_inventory_warnings' in kpis:
            kpi = kpis['low_inventory_warnings']
            context += f"⚠️ **Low Inventory Warnings**: {kpi['total_low_items']} items below par\n"
            if kpi['value']:
                context += "   Items needing reorder:\n"
                for item in kpi['value'][:10]:
                    shortage = item['shortage']
                    context += f"      - {item['ingredient']}: {item['current_quantity']:.1f} units "
                    context += f"(par: {item['par_level']:.1f}, need {shortage:.1f} more)\n"
            else:
                context += "   ✅ All inventory levels are adequate!\n"
            context += "\n"
        
        # -------------------- KPI 15: Labor Hours by Role --------------------
        if 'labor_hours_by_role' in kpis:
            kpi = kpis['labor_hours_by_role']
            context += "👔 **Labor Hours by Role**:\n"
            for role in kpi['value'][:10]:
                context += f"   - {role['role']}: {role['total_hours']:,.2f} hours\n"
            context += f"\n   Total Hours: {kpi['total_hours']:,.2f}\n\n"
        
        # -------------------- KPI 16: Overtime % --------------------
        if 'overtime_pct' in kpis:
            kpi = kpis['overtime_pct']
            context += f"⏰ **Overtime Percentage**: {kpi['value']:.2f}%\n"
            context += f"   Total Hours: {kpi['total_hours']:,.2f}\n"
            context += f"   Overtime Hours: {kpi['total_overtime_hours']:,.2f}\n"
            
            # Add interpretation
            if kpi['value'] < 5:
                context += f"   ✅ Excellent - minimal overtime\n"
            elif kpi['value'] <= 10:
                context += f"   ✅ Good - reasonable overtime levels\n"
            elif kpi['value'] <= 15:
                context += f"   ⚠️ Moderate - watch for trends\n"
            else:
                context += f"   ❌ High - may indicate understaffing\n"
            
            # Show by role if available
            if kpi.get('by_role'):
                context += "\n   Overtime by Role:\n"
                for role in kpi['by_role'][:5]:
                    context += f"      - {role['role']}: {role['overtime_pct']:.2f}% "
                    context += f"({role['overtime_hours']:.1f} OT hours out of {role['total_hours']:.1f})\n"
            context += "\n"
        
        # -------------------- KPI 14: Popularity vs Profitability (Menu Engineering) --------------------
        if 'popularity_vs_profitability' in kpis:
            kpi = kpis['popularity_vs_profitability']
            summary = kpi.get('summary', {})
            
            context += "🎯 **Menu Engineering Analysis**:\n"
            context += "   (Popularity vs Profitability Matrix)\n\n"
            
            # Show quadrant summary
            context += f"   ⭐ Stars (High Sales, High Profit): {summary.get('stars', 0)} items\n"
            context += f"      → Keep and promote these winners!\n\n"
            
            context += f"   🐴 Plow Horses (High Sales, Low Profit): {summary.get('plow_horses', 0)} items\n"
            context += f"      → Increase price or reduce cost\n\n"
            
            context += f"   🧩 Puzzles (Low Sales, High Profit): {summary.get('puzzles', 0)} items\n"
            context += f"      → Hidden gems - promote more!\n\n"
            
            context += f"   🐶 Dogs (Low Sales, Low Profit): {summary.get('dogs', 0)} items\n"
            context += f"      → Consider removing from menu\n\n"
            
            context += f"   Median Quantity Sold: {summary.get('median_quantity', 0):.2f}\n"
            context += f"   Median Profit: ${summary.get('median_profit', 0):.2f}\n\n"
            
            # Show top items by quadrant
            if kpi['value']:
                context += "   Top Items by Quadrant:\n"
                
                # Group by quadrant
                stars = [i for i in kpi['value'] if i['quadrant'] == 'STAR']
                plowhorses = [i for i in kpi['value'] if i['quadrant'] == 'PLOW HORSE']
                puzzles = [i for i in kpi['value'] if i['quadrant'] == 'PUZZLE']
                dogs = [i for i in kpi['value'] if i['quadrant'] == 'DOG']
                
                if stars:
                    context += "\n   ⭐ STARS:\n"
                    for item in stars[:3]:
                        context += f"      - {item['item_name']}: "
                        context += f"Sold {item['quantity_sold']}x, Profit ${item['gross_profit']:.2f}\n"
                
                if plowhorses:
                    context += "\n   🐴 PLOW HORSES:\n"
                    for item in plowhorses[:3]:
                        context += f"      - {item['item_name']}: "
                        context += f"Sold {item['quantity_sold']}x, Profit ${item['gross_profit']:.2f}\n"
                
                if puzzles:
                    context += "\n   🧩 PUZZLES:\n"
                    for item in puzzles[:3]:
                        context += f"      - {item['item_name']}: "
                        context += f"Sold {item['quantity_sold']}x, Profit ${item['gross_profit']:.2f}\n"
                
                if dogs:
                    context += "\n   🐶 DOGS:\n"
                    for item in dogs[:3]:
                        context += f"      - {item['item_name']}: "
                        context += f"Sold {item['quantity_sold']}x, Profit ${item['gross_profit']:.2f}\n"
            
            context += "\n"
        
        # ============================================================
        # STEP 3: Add Warnings
        # ============================================================
        if results.get('warnings'):
            context += "⚠️ **Warnings**:\n"
            for warning in results['warnings']:
                context += f"   - {warning.get('kpi', 'Unknown')}: {warning.get('warning', 'Unknown warning')}\n"
            context += "\n"
        
    # ============================================================
    # STEP 4: Add Errors
    # ============================================================
        if results.get('errors'):
            context += "❌ **Errors**:\n"
            for error in results['errors']:
                context += f"   - {error.get('kpi', 'Unknown')}: {error.get('error', 'Unknown error')}\n"
            context += "\n"
        
        return context
    
    def execute_query(
        self, 
        user_text: str, 
        restaurant_names: List[str]
    ) -> Optional[Dict]:
        """
        Main entry point: Match user text to a prompt and execute appropriate query
        
        This function routes the user's question to the correct handler:
        - Single date queries → _execute_single_date_query
        - Date range queries → _execute_date_range_query
        - KPI calculations → _execute_kpi_calculation
        - Regular SQL queries → Direct SQL execution
        
        Args:
            user_text: User's question (e.g., "what is total sales last week?")
            restaurant_names: List of restaurant names to query
            
        Returns:
            Dictionary with query results or None if no match
            {
                'matched': bool,           # Was a prompt matched?
                'query_executed': bool,    # Did the query execute successfully?
                'prompt_id': str,          # ID of matched prompt
                'result': Any,             # Raw query results
                'data_for_ai': str,        # Formatted text for AI
                'error': str (optional)    # Error message if failed
            }
        """
        
        # ============================================================
        # STEP 1: Find Matching Prompt
        # ============================================================
        prompt = self.match_prompt(user_text)
        
        # If no prompt matched, return no match
        if not prompt:
            logger.info("❌ No matching prompt found")
            return {
                'matched': False,
                'query_executed': False,
                'result': None,
                'data_for_ai': None
            }
        
        logger.info(f"🎯 Matched prompt: {prompt['id']}")
        logger.info(f"   Category: {prompt.get('category', 'N/A')}")
        logger.info(f"   Requires date range: {prompt.get('requires_date_range', False)}")
        logger.info(f"   Requires single date: {prompt.get('requires_single_date', False)}")
        logger.info(f"   Requires keyword: {prompt.get('requires_keyword', False)}")
        
        # ============================================================
        # STEP 2: Route to Appropriate Handler
        # ============================================================
        
        # ---------- HANDLER 1: Date Range Queries ----------
        # Example: "sales from 05/10/2025 to 13/10/2025"
        # Returns only 'date' and 'data' columns
        if prompt.get('requires_date_range'):
            logger.info("📅 Routing to DATE RANGE query handler")
            return self._execute_date_range_query(prompt, restaurant_names, user_text)
        
        # ---------- HANDLER 2: Single Date Queries ----------
        # Example: "tips on 14/10/2025"
        # Returns only 'date' and 'data' columns for one specific date
        if prompt.get('requires_single_date'):
            logger.info("📆 Routing to SINGLE DATE query handler")
            return self._execute_single_date_query(prompt, restaurant_names, user_text)
        
        # ---------- HANDLER 3: KPI Calculations ----------
        # Example: "show me food cost last week"
        # Calculates metrics using KPI calculator
        if prompt.get('category') == 'kpi':
            logger.info("📊 Routing to KPI CALCULATION handler")
            return self._execute_kpi_calculation(prompt, restaurant_names, user_text)
        
        # ---------- HANDLER 4: Regular SQL Queries ----------
        # Example: "how many employees", "list menu items", "sales on 2025-11-06"
        # Executes SQL directly from prompt
        logger.info("💾 Routing to REGULAR SQL query handler")
        
        try:
            # Initialize database cursor
            cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            # ========== SUB-HANDLER 4A: Queries Requiring Single Date ==========
            if prompt.get('requires_date', False):
                logger.info("   📆 Query requires single date parameter")
                
                # Extract date from user text
                date = self._extract_date(user_text)
                
                if not date:
                    logger.warning("   ⚠️ Date required but not found in text")
                    return {
                        'matched': True,
                        'query_executed': False,
                        'error': 'Could not extract date from query. Please specify a date (e.g., 14/10/2025, October 14 2025, 2025-10-14).',
                        'data_for_ai': None
                    }
                
                logger.info(f"   ✅ Executing query with date: {date}")
                
                # Execute SQL with date parameter
                # SQL format: WHERE date = %s
                cur.execute(prompt['sql'], (restaurant_names, date))
            
            # ========== SUB-HANDLER 4B: Queries Requiring Date Range ==========
            elif prompt.get('requires_date_range_old', False):  # Old style date range (deprecated)
                logger.info("   📅 Query requires date range parameter")
                
                # Extract date range from user text
                date_range = self._extract_date_range(user_text)
                
                if not date_range:
                    logger.warning("   ⚠️ Date range required but not found")
                    return {
                        'matched': True,
                        'query_executed': False,
                        'error': 'Could not extract date range from query. Please use format: from DATE to DATE or between DATE and DATE.',
                        'data_for_ai': None
                    }
                
                start_date, end_date = date_range
                logger.info(f"   ✅ Executing query with date range: {start_date.date()} to {end_date.date()}")
                
                # Execute SQL with date range parameters
                # SQL format: WHERE date >= %s AND date <= %s
                cur.execute(prompt['sql'], (restaurant_names, start_date.date(), end_date.date()))
            
            # ========== SUB-HANDLER 4C: Queries Requiring Keyword Search ==========
            elif prompt.get('requires_keyword', False):
                logger.info("   🔍 Query requires keyword parameter")
                
                # Extract keyword from user text
                keyword = self._extract_keyword(user_text, prompt['text_patterns'])
                
                if not keyword:
                    logger.warning("   ⚠️ Keyword required but not found")
                    return {
                        'matched': True,
                        'query_executed': False,
                        'error': 'Could not extract keyword from query. Please be more specific (e.g., "search for tomato").',
                        'data_for_ai': None
                    }
                
                logger.info(f"   ✅ Executing query with keyword: '{keyword}'")
                
                # Execute SQL with keyword parameter (using ILIKE for case-insensitive search)
                # SQL format: WHERE column ILIKE %s
                cur.execute(prompt['sql'], (restaurant_names, f'%{keyword}%'))
            
            # ========== SUB-HANDLER 4D: Simple Queries (No Special Parameters) ==========
            else:
                logger.info("   💡 Executing simple query (no special parameters)")
                
                # Execute SQL with only restaurant names
                # SQL format: WHERE restaurant_id = ANY(%s)
                cur.execute(prompt['sql'], (restaurant_names,))
            
            # ============================================================
            # STEP 3: Fetch and Log Results
            # ============================================================
            results = cur.fetchall()
            logger.info(f"📊 Query returned {len(results)} rows")
            
            # Log sample of first result (if any)
            if results and len(results) > 0:
                first_result = dict(results[0])
                logger.info(f"   First result sample: {first_result}")
                
                # Log column names
                if first_result:
                    logger.info(f"   Columns: {list(first_result.keys())}")
            else:
                logger.info("   ⚠️ Query returned no results")
            
            # ============================================================
            # STEP 4: Format Results for AI
            # ============================================================
            logger.info(f"✨ Formatting results for AI...")
            data_for_ai = self._format_for_ai(prompt, results, restaurant_names)
            logger.info(f"   ✅ Formatted context: {len(data_for_ai)} characters")
            logger.info(f"   Preview: {data_for_ai[:200]}...")
            
            # ============================================================
            # STEP 5: Close Cursor
            # ============================================================
            cur.close()
            logger.info("   🔌 Database cursor closed")
            
            # ============================================================
            # STEP 6: Return Results
            # ============================================================
            return {
                'matched': True,
                'query_executed': True,
                'prompt_id': prompt['id'],
                'result': results,
                'data_for_ai': data_for_ai,
                'row_count': len(results)
            }
            
        except psycopg2.Error as db_error:
            # Database-specific errors
            logger.error(f"❌ Database error executing query: {db_error}", exc_info=True)
            logger.error(f"   SQL State: {db_error.pgcode}")
            logger.error(f"   Error Message: {db_error.pgerror}")
            
            return {
                'matched': True,
                'query_executed': False,
                'error': f'Database error: {str(db_error)}',
                'data_for_ai': None
            }
        
        except Exception as e:
            # General errors
            logger.error(f"❌ Error executing query: {e}", exc_info=True)
            logger.error(f"   Error type: {type(e).__name__}")
            
            return {
                'matched': True,
                'query_executed': False,
                'error': f'Query execution error: {str(e)}',
                'data_for_ai': None
            }
        
        finally:
            # Always try to close cursor if it was opened
            try:
                if 'cur' in locals() and cur is not None:
                    cur.close()
                    logger.info("   🔌 Database cursor closed in finally block")
            except:
                pass

    


    def _extract_date(self, user_text: str) -> Optional[str]:
        """Extract single date from user text"""
        from datetime import datetime
        
        # Try different date patterns
        patterns = [
            r'(\d{4}-\d{2}-\d{2})',  # YYYY-MM-DD
            r'(\d{2}/\d{2}/\d{4})',  # MM/DD/YYYY
            r'(\d{2}-\d{2}-\d{4})',  # MM-DD-YYYY
        ]
        
        for pattern in patterns:
            match = re.search(pattern, user_text)
            if match:
                date_str = match.group(1)
                try:
                    if '/' in date_str:
                        date_obj = datetime.strptime(date_str, '%m/%d/%Y')
                    elif '-' in date_str and date_str[4] == '-':
                        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                    elif '-' in date_str:
                        date_obj = datetime.strptime(date_str, '%m-%d-%Y')
                    
                    return date_obj.strftime('%Y-%m-%d')
                except:
                    continue
        
        # Try relative dates
        user_text_lower = user_text.lower()
        if 'today' in user_text_lower:
            return datetime.now().strftime('%Y-%m-%d')
        elif 'yesterday' in user_text_lower:
            return (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        return None


    def _extract_keyword(self, user_text: str, patterns: List[str]) -> Optional[str]:
        """Extract keyword from user text after matching pattern"""
        user_text_lower = user_text.lower().strip()
        
        for pattern in patterns:
            if pattern.lower() in user_text_lower:
                # Get text after the pattern_extract_date_range
                parts = user_text_lower.split(pattern.lower(), 1)
                if len(parts) > 1:
                    keyword = parts[1].strip()
                    # Remove common words
                    keyword = keyword.replace('for', '').replace('the', '').strip()
                    if keyword:
                        return keyword
        
        return None
    
    
    def _format_for_ai(self, prompt: Dict, results: List, restaurant_names: List[str]) -> str:
        """Format regular SQL results into context for AI"""
        if not results:
            return f"No data found for restaurants: {', '.join(restaurant_names)}"
        
        context = f"Database Query Results for {', '.join(restaurant_names)}:\n\n"
        
        # Format based on prompt category
        category = prompt.get('category', 'unknown')
        
        if category == 'sales':
            context += "Sales Data:\n"
            for row in results[:20]:  # Limit to 20 rows
                context += f"  - {dict(row)}\n"
        
        elif category == 'inventory':
            context += "Inventory Data:\n"
            for row in results[:20]:
                context += f"  - {dict(row)}\n"
        
        elif category == 'employees':
            context += "Employee Data:\n"
            for row in results[:20]:
                context += f"  - {dict(row)}\n"
        
        elif category == 'menu':
            context += "Menu Data:\n"
            for row in results[:20]:
                context += f"  - {dict(row)}\n"
        
        else:
            context += f"Query returned {len(results)} rows\n"
        
        return context

    def _validate_date_range(self, start_date: datetime, end_date: datetime) -> bool:
        """Validate that date range is <= 20 days"""
        delta = abs((end_date - start_date).days)
        
        if delta > 20:
            logger.warning(f"⚠️ Date range too large: {delta} days (max 20)")
            return False
        
        logger.info(f"✅ Date range valid: {delta} days")
        return True
    
    def _extract_data_column(self, user_text: str, table_name: str) -> str:
        """
        Extract the data column name from user query
        Returns the actual column name from the table
        """
        user_text_lower = user_text.lower()
        
        # Get column mappings for this table
        mappings = self.column_mappings.get(table_name, {})
        
        # Check each possible keyword
        for keyword, column_name in mappings.items():
            if keyword in user_text_lower:
                logger.info(f"📊 Detected data column: '{column_name}' from keyword '{keyword}'")
                return column_name
        
        # Default columns if nothing matched
        defaults = {
            'sales_graphs': 'total_amount',
            'inventory_graphs': 'quantity',
            'menu_graphs': 'selling_price',
            'employees_graphs': 'hours_worked'
        }
        
        default_col = defaults.get(table_name, 'id')
        logger.info(f"📊 Using default data column: '{default_col}'")
        return default_col
    

    def _format_date_range_for_ai(
        self,
        results: List,
        restaurant_names: List[str],
        data_column: str,
        start_date: datetime,
        end_date: datetime,
        table_name: str
    ) -> str:
        """Format date range query results for AI"""
        if not results:
            return f"No data found for {', '.join(restaurant_names)} from {start_date.date()} to {end_date.date()}"
        
        context = f"=== DATE RANGE QUERY RESULTS ===\n\n"
        context += f"Restaurants: {', '.join(restaurant_names)}\n"
        context += f"Date Range: {start_date.date()} to {end_date.date()} ({(end_date - start_date).days + 1} days)\n"
        context += f"Table: {table_name}\n"
        context += f"Data Column: {data_column}\n\n"
        
        # Calculate summary statistics
        data_values = [float(row['data']) for row in results if row['data'] is not None]
        
        if data_values:
            total = sum(data_values)
            avg = total / len(data_values)
            min_val = min(data_values)
            max_val = max(data_values)
            
            context += f"📊 SUMMARY:\n"
            context += f"   Total: {total:,.2f}\n"
            context += f"   Average: {avg:,.2f}\n"
            context += f"   Min: {min_val:,.2f}\n"
            context += f"   Max: {max_val:,.2f}\n"
            context += f"   Count: {len(data_values)} records\n\n"
        
        context += f"📅 DAILY BREAKDOWN:\n"
        for row in results:
            date = row['date']
            data = row['data']
            data_str = f"{float(data):,.2f}" if data is not None else "N/A"
            context += f"   {date}: {data_str}\n"
        
        return context

    def _execute_date_range_query(
        self,
        prompt: Dict,
        restaurant_names: List[str],
        user_text: str
    ) -> Optional[Dict]:
        """
        Execute date range query returning only date and data columns
        """
        try:
            # Extract date range
            date_range = self._extract_date_range(user_text)
            
            if not date_range:
                return {
                    'matched': True,
                    'query_executed': False,
                    'error': 'Could not extract date range from query',
                    'data_for_ai': None
                }
            
            start_date, end_date = date_range
            
            # Validate date range (max 20 days)
            if not self._validate_date_range(start_date, end_date):
                return {
                    'matched': True,
                    'query_executed': False,
                    'error': 'Date range exceeds 20 days. Please use a shorter range.',
                    'data_for_ai': None
                }
            
            # Get table name
            table_name = prompt.get('table')
            if not table_name:
                return {
                    'matched': True,
                    'query_executed': False,
                    'error': 'No table specified in prompt',
                    'data_for_ai': None
                }
            
            # Extract data column
            data_column = self._extract_data_column(user_text, table_name)
            
            # Get restaurant IDs
            cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT id, name FROM restaurants 
                WHERE name = ANY(%s) AND active = true
            """, (restaurant_names,))
            restaurant_rows = cur.fetchall()
            restaurant_ids = [row['id'] for row in restaurant_rows]
            
            if not restaurant_ids:
                return {
                    'matched': True,
                    'query_executed': False,
                    'error': f'No active restaurants found: {restaurant_names}',
                    'data_for_ai': None
                }
            
            # Build and execute query
            query = f"""
                SELECT 
                    date,
                    {data_column} as data
                FROM {table_name}
                WHERE restaurant_id = ANY(%s)
                  AND date >= %s
                  AND date <= %s
                ORDER BY date
            """
            
            logger.info(f"🔍 Executing date range query:")
            logger.info(f"   Table: {table_name}")
            logger.info(f"   Data column: {data_column}")
            logger.info(f"   Date range: {start_date.date()} to {end_date.date()}")
            logger.info(f"   Restaurant IDs: {restaurant_ids}")
            
            cur.execute(query, (restaurant_ids, start_date.date(), end_date.date()))
            results = cur.fetchall()
            
            logger.info(f"📊 Query returned {len(results)} rows")
            
            # Format for AI
            data_for_ai = self._format_date_range_for_ai(
                results, 
                restaurant_names, 
                data_column, 
                start_date, 
                end_date,
                table_name
            )
            
            return {
                'matched': True,
                'query_executed': True,
                'prompt_id': prompt['id'],
                'result': results,
                'data_for_ai': data_for_ai,
                'date_range': {
                    'start': start_date.date().isoformat(),
                    'end': end_date.date().isoformat(),
                    'days': (end_date - start_date).days + 1
                }
            }
            
        except Exception as e:
            logger.error(f"❌ Error executing date range query: {e}", exc_info=True)
            return {
                'matched': True,
                'query_executed': False,
                'error': str(e),
                'data_for_ai': None
            }
    
    def _extract_date_range(self, user_text: str) -> Optional[Tuple[datetime, datetime]]:
        """
        Extract date range from user text
        Supports: "from X to Y", "between X and Y", "X to Y"
        Returns tuple of (start_date, end_date) or None
        """
        user_text_lower = user_text.lower()
        
        # Pattern 1: "from DATE to DATE"
        pattern1 = r'from\s+([^\s]+(?:\s+[^\s]+){0,2})\s+to\s+([^\s]+(?:\s+[^\s]+){0,2})'
        match = re.search(pattern1, user_text_lower, re.IGNORECASE)
        
        if match:
            date1_str = match.group(1)
            date2_str = match.group(2)
            
            date1 = self._parse_date(date1_str)
            date2 = self._parse_date(date2_str)
            
            if date1 and date2:
                logger.info(f"📅 Extracted date range: {date1.date()} to {date2.date()}")
                return (date1, date2)
        
        # Pattern 2: "between DATE and DATE"
        pattern2 = r'between\s+([^\s]+(?:\s+[^\s]+){0,2})\s+and\s+([^\s]+(?:\s+[^\s]+){0,2})'
        match = re.search(pattern2, user_text_lower, re.IGNORECASE)
        
        if match:
            date1_str = match.group(1)
            date2_str = match.group(2)
            
            date1 = self._parse_date(date1_str)
            date2 = self._parse_date(date2_str)
            
            if date1 and date2:
                logger.info(f"📅 Extracted date range: {date1.date()} to {date2.date()}")
                return (date1, date2)
        
        # Pattern 3: Find two dates in text
        date_patterns = [
            r'\d{1,2}[/-]\d{1,2}[/-]\d{4}',
            r'\d{4}[/-]\d{1,2}[/-]\d{1,2}',
            r'\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}',
        ]
        
        all_dates = []
        for pattern in date_patterns:
            matches = re.findall(pattern, user_text_lower, re.IGNORECASE)
            for match in matches:
                parsed = self._parse_date(match)
                if parsed:
                    all_dates.append(parsed)
        
        if len(all_dates) >= 2:
            logger.info(f"📅 Extracted date range: {all_dates[0].date()} to {all_dates[1].date()}")
            return (all_dates[0], all_dates[1])
        
        logger.warning("⚠️ Could not extract date range from text")
        return None
    

    def _extract_single_date(self, user_text: str) -> Optional[datetime]:
        """
        Extract single date from user text
        Supports: "on DATE", "for DATE", or just "DATE"
        Returns datetime object or None
        """
        user_text_lower = user_text.lower()
        
        # Pattern 1: "on DATE"
        pattern1 = r'on\s+([^\s]+(?:\s+[^\s]+){0,2})'
        match = re.search(pattern1, user_text_lower, re.IGNORECASE)
        
        if match:
            date_str = match.group(1)
            # Remove trailing words like "show", "get"
            date_str = date_str.split()[0] if ' ' in date_str else date_str
            
            date = self._parse_date(date_str)
            if date:
                logger.info(f"📅 Extracted single date: {date.date()}")
                return date
        
        # Pattern 2: "for DATE"
        pattern2 = r'for\s+([^\s]+(?:\s+[^\s]+){0,2})'
        match = re.search(pattern2, user_text_lower, re.IGNORECASE)
        
        if match:
            date_str = match.group(1)
            date_str = date_str.split()[0] if ' ' in date_str else date_str
            
            date = self._parse_date(date_str)
            if date:
                logger.info(f"📅 Extracted single date: {date.date()}")
                return date
        
        # Pattern 3: Find any date in text
        date_patterns = [
            r'\d{1,2}[/-]\d{1,2}[/-]\d{4}',
            r'\d{4}[/-]\d{1,2}[/-]\d{1,2}',
            r'\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}',
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, user_text_lower, re.IGNORECASE)
            if match:
                parsed = self._parse_date(match.group(0))
                if parsed:
                    logger.info(f"📅 Extracted single date: {parsed.date()}")
                    return parsed
        
        logger.warning("⚠️ Could not extract date from text")
        return None
    

    def _execute_single_date_query(
            self,
            prompt: Dict,
            restaurant_names: List[str],
            user_text: str
        ) -> Optional[Dict]:
            """
            Execute single date query returning only date and data columns
            This is similar to date range but for a specific single date
            """
            try:
                # Extract single date
                single_date = self._extract_single_date(user_text)
                
                if not single_date:
                    return {
                        'matched': True,
                        'query_executed': False,
                        'error': 'Could not extract date from query',
                        'data_for_ai': None
                    }
                
                # Get table name
                table_name = prompt.get('table')
                if not table_name:
                    return {
                        'matched': True,
                        'query_executed': False,
                        'error': 'No table specified in prompt',
                        'data_for_ai': None
                    }
                
                # Extract data column
                data_column = self._extract_data_column(user_text, table_name)
                
                # Get restaurant IDs
                cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("""
                    SELECT id, name FROM restaurants 
                    WHERE name = ANY(%s) AND active = true
                """, (restaurant_names,))
                restaurant_rows = cur.fetchall()
                restaurant_ids = [row['id'] for row in restaurant_rows]
                
                if not restaurant_ids:
                    return {
                        'matched': True,
                        'query_executed': False,
                        'error': f'No active restaurants found: {restaurant_names}',
                        'data_for_ai': None
                    }
                
                # Build and execute query for single date
                query = f"""
                    SELECT 
                        date,
                        {data_column} as data
                    FROM {table_name}
                    WHERE restaurant_id = ANY(%s)
                      AND date = %s
                    ORDER BY date
                """
                
                logger.info(f"🔍 Executing single date query:")
                logger.info(f"   Table: {table_name}")
                logger.info(f"   Data column: {data_column}")
                logger.info(f"   Date: {single_date.date()}")
                logger.info(f"   Restaurant IDs: {restaurant_ids}")
                
                cur.execute(query, (restaurant_ids, single_date.date()))
                results = cur.fetchall()
                
                logger.info(f"📊 Query returned {len(results)} rows")
                
                # Format for AI
                data_for_ai = self._format_single_date_for_ai(
                    results, 
                    restaurant_names, 
                    data_column, 
                    single_date,
                    table_name
                )
                
                return {
                    'matched': True,
                    'query_executed': True,
                    'prompt_id': prompt['id'],
                    'result': results,
                    'data_for_ai': data_for_ai,
                    'date': single_date.date().isoformat()
                }
                
            except Exception as e:
                logger.error(f"❌ Error executing single date query: {e}", exc_info=True)
                return {
                    'matched': True,
                    'query_executed': False,
                    'error': str(e),
                    'data_for_ai': None
                }
        

    def _format_single_date_for_ai(
        self,
        results: List,
        restaurant_names: List[str],
        data_column: str,
        date: datetime,
        table_name: str
    ) -> str:
        """Format single date query results for AI"""
        if not results:
            return f"No data found for {', '.join(restaurant_names)} on {date.date()}"
        
        context = f"=== SINGLE DATE QUERY RESULTS ===\n\n"
        context += f"Restaurants: {', '.join(restaurant_names)}\n"
        context += f"Date: {date.strftime('%A, %B %d, %Y')} ({date.date()})\n"
        context += f"Table: {table_name}\n"
        context += f"Data Column: {data_column}\n\n"
        
        # Calculate summary statistics
        data_values = [float(row['data']) for row in results if row['data'] is not None]
        
        if data_values:
            total = sum(data_values)
            avg = total / len(data_values) if data_values else 0
            min_val = min(data_values)
            max_val = max(data_values)
            
            context += f"📊 SUMMARY FOR THIS DATE:\n"
            context += f"   Total: {total:,.2f}\n"
            context += f"   Average: {avg:,.2f}\n"
            context += f"   Min: {min_val:,.2f}\n"
            context += f"   Max: {max_val:,.2f}\n"
            context += f"   Count: {len(data_values)} records\n\n"
        
        # Show individual records if not too many
        if len(results) <= 20:
            context += f"📋 INDIVIDUAL RECORDS:\n"
            for i, row in enumerate(results, 1):
                date_val = row['date']
                data = row['data']
                data_str = f"{float(data):,.2f}" if data is not None else "N/A"
                context += f"   {i}. Date: {date_val}, {data_column}: {data_str}\n"
        else:
            context += f"📋 {len(results)} records found (showing summary only)\n"
        
        return context

    def _extract_keyword(self, user_text: str, patterns: List[str]) -> Optional[str]:
        """Extract keyword from user text after matching pattern"""
        user_text_lower = user_text.lower().strip()
        
        for pattern in patterns:
            if pattern.lower() in user_text_lower:
                # Get text after the pattern
                parts = user_text_lower.split(pattern.lower(), 1)
                if len(parts) > 1:
                    keyword = parts[1].strip()
                    # Remove common words
                    keyword = keyword.replace('for', '').replace('the', '').strip()
                    if keyword:
                        return keyword
        
        return None
    
    def _format_for_ai(self, prompt: Dict, results: List, restaurant_names: List[str]) -> str:
        """Format SQL results into context for AI"""
        if not results:
            return f"No data found for restaurants: {', '.join(restaurant_names)}"
        
        context = f"Database Query Results:\n\n"
        
        # ============ INVENTORY ============
        if prompt['id'] == 'count_inventory':
            context += "Total inventory row count by restaurant:\n"
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                total_rows = row.get('total_rows', 0)
                context += f"- {restaurant}: {total_rows} inventory entries\n"
        
        elif prompt['id'] == 'list_unique_ingredients':
            context += "Unique ingredients by restaurant:\n\n"
            current_restaurant = None
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                ingredient = row.get('ingredient', 'Unknown')
                
                if restaurant != current_restaurant:
                    context += f"\n**{restaurant}:**\n"
                    current_restaurant = restaurant
                
                context += f"  - {ingredient}\n"
        
        elif prompt['id'] == 'list_all_ingredients':
            context += "All ingredients with quantities:\n\n"
            current_restaurant = None
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                ingredient = row.get('ingredient', 'Unknown')
                quantity = row.get('quantity', 0)
                unit_cost = row.get('unit_cost', 0)
                
                if restaurant != current_restaurant:
                    context += f"\n**{restaurant}:**\n"
                    current_restaurant = restaurant
                
                cost_str = f"${float(unit_cost):.2f}" if unit_cost else "N/A"
                context += f"  - {ingredient}: {quantity} units @ {cost_str}\n"
        
        elif prompt['id'] == 'ingredient_quantity_total':
            context += "Total quantities by ingredient name:\n\n"
            current_restaurant = None
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                ingredient = row.get('ingredient', 'Unknown')
                total_quantity = row.get('total_quantity', 0)
                entry_count = row.get('entry_count', 0)
                
                if restaurant != current_restaurant:
                    context += f"\n**{restaurant}:**\n"
                    current_restaurant = restaurant
                
                context += f"  - {ingredient}: {total_quantity} units total ({entry_count} entries)\n"
        
        elif prompt['id'] == 'search_ingredient':
            context += "Ingredient search results:\n\n"
            current_restaurant = None
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                ingredient = row.get('ingredient', 'Unknown')
                quantity = row.get('quantity', 0)
                unit_cost = row.get('unit_cost', 0)
                
                if restaurant != current_restaurant:
                    context += f"\n**{restaurant}:**\n"
                    current_restaurant = restaurant
                
                cost_str = f"${float(unit_cost):.2f}" if unit_cost else "N/A"
                context += f"  - {ingredient}: {quantity} units @ {cost_str}\n"
        
        # ============ EMPLOYEES ============
        elif prompt['id'] == 'list_employee_names':
            context += "Employee names and positions:\n\n"
            current_restaurant = None
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                employee_name = row.get('employee_name', 'Unknown')
                position = row.get('position') or row.get('role', 'N/A')
                
                if restaurant != current_restaurant:
                    context += f"\n**{restaurant}:**\n"
                    current_restaurant = restaurant
                
                context += f"  - {employee_name} ({position})\n"
        
        elif prompt['id'] == 'employee_roles_positions':
            context += "Employee roles and positions:\n\n"
            current_restaurant = None
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                employee_name = row.get('employee_name', 'Unknown')
                position_role = row.get('position_role', 'N/A')
                
                if restaurant != current_restaurant:
                    context += f"\n**{restaurant}:**\n"
                    current_restaurant = restaurant
                
                context += f"  - {employee_name}: {position_role}\n"
        
        elif prompt['id'] == 'employee_hourly_rate':
            context += "Employee hourly rates:\n\n"
            current_restaurant = None
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                employee_name = row.get('employee_name', 'Unknown')
                position = row.get('position', 'N/A')
                hourly_rate = row.get('hourly_rate', 0)
                
                if restaurant != current_restaurant:
                    context += f"\n**{restaurant}:**\n"
                    current_restaurant = restaurant
                
                rate_str = f"${float(hourly_rate):.2f}/hr" if hourly_rate else "N/A"
                context += f"  - {employee_name} ({position}): {rate_str}\n"
        
        elif prompt['id'] == 'count_employees':
            context += "Employee count by restaurant:\n"
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                total_employees = row.get('total_employees', 0)
                context += f"- {restaurant}: {total_employees} employees\n"
        
        elif prompt['id'] == 'employees_by_position':
            context += "Employees by position:\n\n"
            current_restaurant = None
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                position_role = row.get('position_role', 'Unknown')
                employee_count = row.get('employee_count', 0)
                
                if restaurant != current_restaurant:
                    context += f"\n**{restaurant}:**\n"
                    current_restaurant = restaurant
                
                context += f"  - {position_role}: {employee_count} employees\n"
        
        # ============ MENU ============
        elif prompt['id'] == 'list_menu_items':
            context += "Menu item names:\n\n"
            current_restaurant = None
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                item_name = row.get('item_name', 'Unknown')
                
                if restaurant != current_restaurant:
                    context += f"\n**{restaurant}:**\n"
                    current_restaurant = restaurant
                
                context += f"  - {item_name}\n"
        
        elif prompt['id'] == 'menu_item_cost':
            context += "Menu item costs:\n\n"
            current_restaurant = None
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                item_name = row.get('item_name', 'Unknown')
                unit_cost = row.get('unit_cost', 0)
                selling_price = row.get('selling_price', 0)
                profit_margin = row.get('profit_margin', 0)
                
                if restaurant != current_restaurant:
                    context += f"\n**{restaurant}:**\n"
                    current_restaurant = restaurant
                
                cost_str = f"${float(unit_cost):.2f}" if unit_cost else "N/A"
                price_str = f"${float(selling_price):.2f}" if selling_price else "N/A"
                margin_str = f"{float(profit_margin):.1f}%" if profit_margin else "N/A"
                context += f"  - {item_name}: Cost {cost_str}, Price {price_str}, Margin {margin_str}\n"
        
        elif prompt['id'] == 'menu_item_ingredients':
            context += "Menu item ingredients:\n\n"
            current_restaurant = None
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                item_name = row.get('item_name', 'Unknown')
                ingredients = row.get('ingredients', 'N/A')
                
                if restaurant != current_restaurant:
                    context += f"\n**{restaurant}:**\n"
                    current_restaurant = restaurant
                
                context += f"  - **{item_name}:** {ingredients}\n"
        
        elif prompt['id'] == 'count_menu_items':
            context += "Menu item count by restaurant:\n"
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                total_items = row.get('total_items', 0)
                context += f"- {restaurant}: {total_items} menu items\n"
        
        elif prompt['id'] == 'menu_by_category':
            context += "Menu items by category:\n\n"
            current_restaurant = None
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                category = row.get('category', 'Unknown')
                item_count = row.get('item_count', 0)
                
                if restaurant != current_restaurant:
                    context += f"\n**{restaurant}:**\n"
                    current_restaurant = restaurant
                
                context += f"  - {category}: {item_count} items\n"
        
        # ============ SALES ============
        elif prompt['id'] == 'total_sales':
            context += "Sales summary by restaurant:\n\n"
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                transaction_count = row.get('transaction_count', 0)
                total_subtotal = row.get('total_subtotal', 0)
                total_amount = row.get('total_amount', 0)
                avg_subtotal = row.get('avg_subtotal', 0)
                
                context += f"**{restaurant}:**\n"
                context += f"  - Transactions: {transaction_count}\n"
                context += f"  - Total Subtotal: ${float(total_subtotal):,.2f}\n"
                context += f"  - Total Amount (with tax/tip): ${float(total_amount):,.2f}\n"
                context += f"  - Average Subtotal: ${float(avg_subtotal):,.2f}\n\n"
        
        elif prompt['id'] == 'sales_by_payment':
            context += "Sales by payment method:\n\n"
            current_restaurant = None
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                payment_method = row.get('payment_method', 'Unknown')
                transaction_count = row.get('transaction_count', 0)
                total_subtotal = row.get('total_subtotal', 0)
                
                if restaurant != current_restaurant:
                    context += f"\n**{restaurant}:**\n"
                    current_restaurant = restaurant
                
                context += f"  - {payment_method}: {transaction_count} transactions, ${float(total_subtotal):,.2f}\n"
        
        elif prompt['id'] == 'sales_by_order_type':
            context += "Sales by order type:\n\n"
            current_restaurant = None
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                order_type = row.get('order_type', 'Unknown')
                order_count = row.get('order_count', 0)
                total_subtotal = row.get('total_subtotal', 0)
                
                if restaurant != current_restaurant:
                    context += f"\n**{restaurant}:**\n"
                    current_restaurant = restaurant
                
                context += f"  - {order_type}: {order_count} orders, ${float(total_subtotal):,.2f}\n"
        
        elif prompt['id'] == 'top_selling_items':
            context += "Top selling items:\n\n"
            current_restaurant = None
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                items_sold = row.get('items_sold', 'Unknown')
                times_ordered = row.get('times_ordered', 0)
                total_quantity = row.get('total_quantity', 0)
                
                if restaurant != current_restaurant:
                    context += f"\n**{restaurant}:**\n"
                    current_restaurant = restaurant
                
                context += f"  - {items_sold}: {times_ordered} orders, {total_quantity} units sold\n"
        
        elif prompt['id'] == 'average_tip':
            context += "Tip statistics:\n\n"
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                avg_tip = row.get('avg_tip', 0)
                total_tips = row.get('total_tips', 0)
                
                context += f"**{restaurant}:**\n"
                context += f"  - Average Tip: ${float(avg_tip):,.2f}\n"
                context += f"  - Total Tips: ${float(total_tips):,.2f}\n\n"
        
        elif prompt['id'] == 'sales_on_date':
            context += "Sales data for specific date:\n\n"
            for row in results:
                restaurant = row.get('restaurant_name', 'Unknown')
                transaction_count = row.get('transaction_count', 0)
                total_subtotal = row.get('total_subtotal', 0)
                total_amount = row.get('total_amount', 0)
                avg_subtotal = row.get('avg_subtotal', 0)
                
                context += f"**{restaurant}:**\n"
                context += f"  - Transactions: {transaction_count}\n"
                context += f"  - Total Sales (Subtotal): ${float(total_subtotal):,.2f}\n"
                context += f"  - Total Amount (with tax/tip): ${float(total_amount):,.2f}\n"
                context += f"  - Average Order: ${float(avg_subtotal):,.2f}\n\n"
        
        else:
            # Generic formatting
            context += f"Query returned {len(results)} rows:\n\n"
            for i, row in enumerate(results[:10], 1):
                context += f"Row {i}: {dict(row)}\n"
        
        return context


# Helper function to use in endpoint
async def try_prompt_query(user_question: str, restaurant_names: List[str], conn) -> Optional[Dict]:
    """Try to match and execute a prompt query"""
    try:
        executor = SimplePromptExecutor(conn)
        result = executor.execute_query(user_question, restaurant_names)
        
        if result and result.get('matched'):
            return result
        
        return None
    except Exception as e:
        logger.error(f"Error in try_prompt_query: {e}", exc_info=True)
        return None