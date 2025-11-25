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
        """
        Find matching prompt based on text patterns
        Returns the first matching prompt
        
        Priority order:
        1. KPI prompts (if time period mentioned)
        2. SQL prompts with exact matches
        3. General SQL prompts
        """
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
        
        # Second pass: Try regular prompts
        for prompt in self.prompts:
            # Skip date-specific prompts if time period is mentioned
            if has_time_period and prompt['id'] in ['sales_on_date', 'sales_date_range']:
                continue
            
            for pattern in prompt['text_patterns']:
                if pattern.lower() in user_text_lower:
                    logger.info(f"✅ Matched pattern '{pattern}' in prompt '{prompt['id']}'")
                    return prompt
        
        logger.info("❌ No prompt matched")
        return None
    
    def _extract_time_period(self, user_text: str) -> Optional[str]:
        """
        Extract time period from user text
        Returns one of: Last_week, Last_month, Last_6_months, Last_15_days, Last_year, or None (for all time)
        """
        user_text_lower = user_text.lower()
        
        # Check for specific time periods
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
            return None  # All time
        
        # Default to None (all time) if no specific period mentioned
        return None
    
    def _load_restaurant_data(self, restaurant_names: List[str], time_period: Optional[str] = None) -> Dict[str, pd.DataFrame]:
        """
        Load data from database tables for KPI calculation
        Returns dict with DataFrames for sales, inventory, menu, and labor
        """
        try:
            logger.info(f"🏪 Loading data for restaurants: {restaurant_names}")
            logger.info(f"📅 Time period requested: {time_period or 'All time'}")
            
            # Get restaurant IDs
            cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT id, name FROM restaurants 
                WHERE name = ANY(%s) AND active = true
            """, (restaurant_names,))
            restaurant_rows = cur.fetchall()
            restaurant_ids = [row['id'] for row in restaurant_rows]
            
            if not restaurant_ids:
                logger.warning(f"❌ No active restaurants found for names: {restaurant_names}")
                return {
                    'sales': pd.DataFrame(),
                    'inventory': pd.DataFrame(),
                    'menu': pd.DataFrame(),
                    'labor': pd.DataFrame()
                }
            
            logger.info(f"✅ Found {len(restaurant_ids)} restaurant(s): {[r['name'] for r in restaurant_rows]}")
            
            # Calculate date filter if time_period is specified
            cutoff_date = None
            if time_period:
                days_map = {
                    'Last_week': 7,
                    'Last_15_days': 15,
                    'Last_month': 30,
                    'Last_6_months': 180,
                    'Last_year': 365
                }
                
                days = days_map.get(time_period)
                
                if days:
                    cutoff_datetime = datetime.now() - timedelta(days=days)
                    cutoff_date = cutoff_datetime.date()
                    logger.info(f"📆 Cutoff date calculated: {cutoff_date} ({days} days ago)")
                else:
                    logger.warning(f"⚠️ Unknown time period: {time_period}, loading all data")
            
            # Check actual data range before filtering
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
                
                # Warn if cutoff is beyond available data
                if cutoff_date and date_info['max_date'] and cutoff_date > date_info['max_date']:
                    logger.warning(f"⚠️ Requested cutoff ({cutoff_date}) is after latest data ({date_info['max_date']})")
                    logger.warning(f"   No data will match this filter! Using all available data instead.")
                    cutoff_date = None  # Fall back to all data
            else:
                logger.warning(f"⚠️ No sales data found in database for these restaurants")
            
            # ============ LOAD SALES DATA ============
            logger.info(f"💰 Loading sales data...")
            
            if cutoff_date:
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
            
            sales_results = cur.fetchall()
            sales_df = pd.DataFrame(sales_results)
            
            if not sales_df.empty:
                logger.info(f"✅ Loaded {len(sales_df)} sales records")
                logger.info(f"   Date range in results: {sales_df['date'].min()} to {sales_df['date'].max()}")
                logger.info(f"   Total gross sales: ${sales_df['gross_sales'].sum():,.2f}")
            else:
                logger.warning(f"⚠️ No sales data loaded")
            
            # ============ LOAD INVENTORY DATA ============
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
            
            # ============ LOAD MENU DATA ============
            logger.info(f"🍽️ Loading menu data...")
            
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
            
            # ============ LOAD LABOR DATA ============
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
                            WHEN position ILIKE '%%manager%%' OR position ILIKE '%%chef%%' 
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
                            WHEN position ILIKE '%%manager%%' OR position ILIKE '%%chef%%' 
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
            
            cur.close()
            
            # ============ SUMMARY ============
            logger.info(f"📋 Data loading summary:")
            logger.info(f"   Sales: {len(sales_df)} records")
            logger.info(f"   Inventory: {len(inventory_df)} records")
            logger.info(f"   Menu: {len(menu_df)} records")
            logger.info(f"   Labor: {len(labor_df)} records")
            
            return {
                'sales': sales_df,
                'inventory': inventory_df,
                'menu': menu_df,
                'labor': labor_df
            }
            
        except Exception as e:
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
        """
        try:
            kpi_type = prompt.get('kpi_type')
            time_period = self._extract_time_period(user_text) if prompt.get('supports_time_period') else None
            
            logger.info(f"🔢 Calculating KPI: {kpi_type}")
            logger.info(f"📅 Time period: {time_period or 'All time'}")
            
            # Load data
            data = self._load_restaurant_data(restaurant_names, time_period)
            
            # Check if we have data
            if all(df.empty for df in data.values()):
                return {
                    'matched': True,
                    'query_executed': False,
                    'error': 'No data available for KPI calculation',
                    'data_for_ai': None
                }
            
            # Calculate KPIs
            if kpi_type == 'all_kpis':
                results = self.kpi_calculator.calculate_all_kpis(
                    sales_df=data['sales'],
                    inventory_df=data['inventory'],
                    menu_df=data['menu'],
                    labor_df=data['labor'],
                    time_period=time_period
                )
            else:
                # Calculate specific KPI
                results = {'kpis': {}, 'errors': [], 'warnings': []}
                
                if kpi_type == 'total_sales' and not data['sales'].empty:
                    results['kpis']['total_sales'] = self.kpi_calculator.calculate_total_sales(data['sales'])
                
                elif kpi_type == 'net_revenue' and not data['sales'].empty:
                    results['kpis']['net_revenue'] = self.kpi_calculator.calculate_net_revenue(data['sales'])
                
                elif kpi_type == 'splh' and not data['sales'].empty and not data['labor'].empty:
                    results['kpis']['splh'] = self.kpi_calculator.calculate_splh(data['sales'], data['labor'])
                
                elif kpi_type == 'guest_count' and not data['sales'].empty:
                    results['kpis']['guest_count'] = self.kpi_calculator.calculate_guest_count(data['sales'])
                
                elif kpi_type == 'avg_check' and not data['sales'].empty:
                    results['kpis']['avg_check'] = self.kpi_calculator.calculate_avg_check(data['sales'])
                
                elif kpi_type == 'top_items' and not data['sales'].empty:
                    results['kpis']['top_items'] = self.kpi_calculator.calculate_top_items(data['sales'])
                
                elif kpi_type == 'food_cost_pct' and not data['sales'].empty and not data['menu'].empty:
                    results['kpis']['food_cost_pct'] = self.kpi_calculator.calculate_food_cost_pct(data['sales'], data['menu'])
                
                elif kpi_type == 'cogs_by_category' and not data['sales'].empty and not data['menu'].empty:
                    results['kpis']['cogs_by_category'] = self.kpi_calculator.calculate_cogs_by_category(data['sales'], data['menu'])
                
                elif kpi_type == 'inventory_turnover' and not data['sales'].empty and not data['menu'].empty and not data['inventory'].empty:
                    results['kpis']['inventory_turnover'] = self.kpi_calculator.calculate_inventory_turnover(
                        data['sales'], data['menu'], data['inventory']
                    )
                
                elif kpi_type == 'low_inventory_warnings' and not data['inventory'].empty:
                    results['kpis']['low_inventory_warnings'] = self.kpi_calculator.calculate_low_inventory_warnings(data['inventory'])
                
                elif kpi_type == 'labor_hours_by_role' and not data['labor'].empty:
                    results['kpis']['labor_hours_by_role'] = self.kpi_calculator.calculate_labor_hours_by_role(data['labor'])
                
                elif kpi_type == 'overtime_pct' and not data['labor'].empty:
                    results['kpis']['overtime_pct'] = self.kpi_calculator.calculate_overtime_pct(data['labor'])
                
                elif kpi_type == 'popularity_vs_profitability' and not data['sales'].empty and not data['menu'].empty:
                    results['kpis']['popularity_vs_profitability'] = self.kpi_calculator.calculate_popularity_vs_profitability(
                        data['sales'], data['menu']
                    )
            
            # Format for AI
            data_for_ai = self._format_kpi_results_for_ai(results, restaurant_names, time_period)
            
            return {
                'matched': True,
                'query_executed': True,
                'prompt_id': prompt['id'],
                'result': results,
                'data_for_ai': data_for_ai
            }
            
        except Exception as e:
            logger.error(f"Error executing KPI calculation: {e}", exc_info=True)
            return {
                'matched': True,
                'query_executed': False,
                'error': str(e),
                'data_for_ai': None
            }
    
    def _format_kpi_results_for_ai(self, results: Dict, restaurant_names: List[str], time_period: Optional[str]) -> str:
        """Format KPI calculation results for AI to understand"""
        context = "=== KPI CALCULATION RESULTS ===\n\n"
        context += f"Restaurants: {', '.join(restaurant_names)}\n"
        context += f"Time Period: {time_period or 'All Time'}\n\n"
        
        kpis = results.get('kpis', {})
        
        if not kpis:
            context += "No KPIs were calculated. This may be due to missing data.\n"
            if results.get('errors'):
                context += "\nErrors:\n"
                for error in results['errors']:
                    context += f"- {error.get('kpi', 'Unknown')}: {error.get('error', 'Unknown error')}\n"
            return context
        
        # Total Sales
        if 'total_sales' in kpis:
            kpi = kpis['total_sales']
            context += f"📊 **Total Sales**: ${kpi['value']:,.2f}\n"
            context += f"   Column used: {kpi.get('column_used', 'N/A')}\n\n"
        
        # Net Revenue
        if 'net_revenue' in kpis:
            kpi = kpis['net_revenue']
            context += f"💰 **Net Revenue**: ${kpi['value']:,.2f}\n"
            context += f"   Gross Sales: ${kpi['gross_sales']:,.2f}\n"
            context += f"   Deductions:\n"
            for key, val in kpi['deductions'].items():
                context += f"      - {key.title()}: ${val:,.2f}\n"
            context += "\n"
        
        # SPLH
        if 'splh' in kpis:
            kpi = kpis['splh']
            if kpi['value']:
                context += f"⏱️ **Sales per Labor Hour (SPLH)**: ${kpi['value']:,.2f}\n"
                context += f"   Net Revenue: ${kpi['net_revenue']:,.2f}\n"
                context += f"   Labor Hours: {kpi['labor_hours']:,.2f}\n\n"
        
        # Guest Count
        if 'guest_count' in kpis:
            kpi = kpis['guest_count']
            context += f"👥 **Guest Count**: {kpi['value']:,}\n"
            context += f"   Method: {kpi.get('method', 'N/A')}\n\n"
        
        # Average Check
        if 'avg_check' in kpis:
            kpi = kpis['avg_check']
            if kpi['value']:
                context += f"🧾 **Average Check**: ${kpi['value']:,.2f}\n"
                context += f"   Based on {kpi['guest_count']:,} guests and ${kpi['net_revenue']:,.2f} revenue\n\n"
        
        # Top Items
        if 'top_items' in kpis:
            kpi = kpis['top_items']
            context += "🌟 **Top Selling Items**:\n"
            for i, item in enumerate(kpi['value'][:10], 1):
                context += f"   {i}. {item['item_name']}: {item['quantity_sold']} sold, ${item['revenue']:,.2f} revenue\n"
            context += f"\n   Total unique items: {kpi.get('total_unique_items', 'N/A')}\n\n"
        
        # Food Cost %
        if 'food_cost_pct' in kpis:
            kpi = kpis['food_cost_pct']
            if kpi['value']:
                context += f"🍽️ **Food Cost Percentage**: {kpi['value']:.2f}%\n"
                context += f"   Total Food Cost: ${kpi['total_food_cost']:,.2f}\n"
                context += f"   Total Food Sales: ${kpi['total_food_sales']:,.2f}\n\n"
        
        # COGS by Category
        if 'cogs_by_category' in kpis:
            kpi = kpis['cogs_by_category']
            context += "📦 **COGS by Category**:\n"
            for cat in kpi['value']:
                context += f"   - {cat['category']}: ${cat['total_cogs']:,.2f}\n"
            context += f"\n   Total COGS: ${kpi['total_cogs']:,.2f}\n\n"
        
        # Inventory Turnover
        if 'inventory_turnover' in kpis:
            kpi = kpis['inventory_turnover']
            if kpi['value']:
                context += f"🔄 **Inventory Turnover Rate**: {kpi['value']:.2f}x\n"
                context += f"   Total COGS: ${kpi['total_cogs']:,.2f}\n"
                context += f"   Avg Inventory Value: ${kpi['avg_inventory_value']:,.2f}\n\n"
        
        # Low Inventory Warnings
        if 'low_inventory_warnings' in kpis:
            kpi = kpis['low_inventory_warnings']
            context += f"⚠️ **Low Inventory Warnings**: {kpi['total_low_items']} items\n"
            if kpi['value']:
                context += "   Items needing reorder:\n"
                for item in kpi['value'][:10]:
                    context += f"      - {item['ingredient']}: {item['current_quantity']:.1f} (par: {item['par_level']:.1f})\n"
            context += "\n"
        
        # Labor Hours by Role
        if 'labor_hours_by_role' in kpis:
            kpi = kpis['labor_hours_by_role']
            context += "👔 **Labor Hours by Role**:\n"
            for role in kpi['value'][:10]:
                context += f"   - {role['role']}: {role['total_hours']:,.2f} hours\n"
            context += f"\n   Total Hours: {kpi['total_hours']:,.2f}\n\n"
        
        # Overtime %
        if 'overtime_pct' in kpis:
            kpi = kpis['overtime_pct']
            context += f"⏰ **Overtime Percentage**: {kpi['value']:.2f}%\n"
            context += f"   Total Hours: {kpi['total_hours']:,.2f}\n"
            context += f"   Overtime Hours: {kpi['total_overtime_hours']:,.2f}\n"
            if kpi.get('by_role'):
                context += "   By Role:\n"
                for role in kpi['by_role'][:5]:
                    context += f"      - {role['role']}: {role['overtime_pct']:.2f}% ({role['overtime_hours']:.1f} OT hours)\n"
            context += "\n"
        
        # Popularity vs Profitability
        if 'popularity_vs_profitability' in kpis:
            kpi = kpis['popularity_vs_profitability']
            summary = kpi.get('summary', {})
            context += "🎯 **Menu Engineering Analysis**:\n"
            context += f"   Stars (High Sales, High Profit): {summary.get('stars', 0)} items\n"
            context += f"   Plow Horses (High Sales, Low Profit): {summary.get('plow_horses', 0)} items\n"
            context += f"   Puzzles (Low Sales, High Profit): {summary.get('puzzles', 0)} items\n"
            context += f"   Dogs (Low Sales, Low Profit): {summary.get('dogs', 0)} items\n\n"
            
            if kpi['value']:
                context += "   Top Items by Quadrant:\n"
                for item in kpi['value'][:10]:
                    context += f"      - {item['item_name']}: {item['quadrant']} "
                    context += f"(Sold: {item['quantity_sold']}, Profit: ${item['gross_profit']:.2f})\n"
            context += "\n"
        
        # Add warnings
        if results.get('warnings'):
            context += "⚠️ **Warnings**:\n"
            for warning in results['warnings']:
                context += f"   - {warning.get('kpi', 'Unknown')}: {warning.get('warning', 'Unknown warning')}\n"
            context += "\n"
        
        # Add errors
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
        Match user text to a prompt and execute its SQL query or KPI calculation
        Returns raw results + formatted context for AI
        """
        # Find matching prompt
        prompt = self.match_prompt(user_text)
        
        if not prompt:
            return {
                'matched': False,
                'query_executed': False,
                'result': None,
                'data_for_ai': None
            }
        
        logger.info(f"🎯 Matched prompt: {prompt['id']}")
        
        # Check if this is a KPI calculation
        if prompt.get('category') == 'kpi':
            return self._execute_kpi_calculation(prompt, restaurant_names, user_text)
        
        # Otherwise, execute SQL query
        try:
            cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            # Handle date-based queries
            if prompt.get('requires_date', False):
                date = self._extract_date(user_text)
                if not date:
                    logger.warning("Date required but not found")
                    return {
                        'matched': True,
                        'query_executed': False,
                        'error': 'Could not extract date from query',
                        'data_for_ai': None
                    }
                
                logger.info(f"📅 Executing query with date: {date}")
                cur.execute(prompt['sql'], (restaurant_names, date))
                
            elif prompt.get('requires_date_range', False):
                date_range = self._extract_date_range(user_text)
                if not date_range:
                    logger.warning("Date range required but not found")
                    return {
                        'matched': True,
                        'query_executed': False,
                        'error': 'Could not extract date range from query',
                        'data_for_ai': None
                    }
                
                logger.info(f"📅 Executing query with date range: {date_range[0]} to {date_range[1]}")
                cur.execute(prompt['sql'], (restaurant_names, date_range[0], date_range[1]))
                
            elif prompt.get('requires_keyword', False):
                keyword = self._extract_keyword(user_text, prompt['text_patterns'])
                if not keyword:
                    logger.warning("Keyword required but not found")
                    return {
                        'matched': True,
                        'query_executed': False,
                        'result': None,
                        'data_for_ai': None
                    }
                
                logger.info(f"🔎 Executing query with keyword: {keyword}")
                cur.execute(prompt['sql'], (restaurant_names, f'%{keyword}%'))
            else:
                logger.info(f"🔍 Executing query for restaurants: {restaurant_names}")
                cur.execute(prompt['sql'], (restaurant_names,))
            
            # Fetch results
            results = cur.fetchall()
            logger.info(f"📊 Query returned {len(results)} rows")
            
            if results:
                logger.info(f"First result: {results[0]}")
            
            # Format data for AI to understand
            data_for_ai = self._format_for_ai(prompt, results, restaurant_names)
            logger.info(f"✅ Formatted context for AI ({len(data_for_ai)} chars)")
            
            return {
                'matched': True,
                'query_executed': True,
                'prompt_id': prompt['id'],
                'result': results,
                'data_for_ai': data_for_ai
            }
            
        except Exception as e:
            logger.error(f"❌ Error executing query: {e}", exc_info=True)
            return {
                'matched': True,
                'query_executed': False,
                'error': str(e),
                'data_for_ai': None
            }
    
    def _extract_date(self, user_text: str) -> Optional[str]:
        """Extract date from user text"""
        from datetime import datetime
        
        # Try different date patterns
        patterns = [
            r'(\d{4}-\d{2}-\d{2})',  # YYYY-MM-DD
            r'(\d{2}/\d{2}/\d{4})',  # MM/DD/YYYY
            r'(\d{2}-\d{2}-\d{4})',  # MM-DD-YYYY
            r'(\d{1,2}/\d{1,2}/\d{4})',  # M/D/YYYY or MM/DD/YYYY
        ]
        
        for pattern in patterns:
            match = re.search(pattern, user_text)
            if match:
                date_str = match.group(1)
                # Try to parse and standardize to YYYY-MM-DD
                try:
                    # Handle different formats
                    if '/' in date_str:
                        if len(date_str.split('/')[2]) == 4:  # MM/DD/YYYY
                            date_obj = datetime.strptime(date_str, '%m/%d/%Y')
                        else:
                            date_obj = datetime.strptime(date_str, '%m/%d/%y')
                    elif '-' in date_str and date_str[4] == '-':  # YYYY-MM-DD
                        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                    elif '-' in date_str:  # MM-DD-YYYY
                        date_obj = datetime.strptime(date_str, '%m-%d-%Y')
                    
                    return date_obj.strftime('%Y-%m-%d')
                except:
                    continue
        
        # Try to extract relative dates
        user_text_lower = user_text.lower()
        if 'today' in user_text_lower:
            return datetime.now().strftime('%Y-%m-%d')
        elif 'yesterday' in user_text_lower:
            return (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        return None
    
    def _extract_date_range(self, user_text: str) -> Optional[Tuple[str, str]]:
        """Extract date range from user text"""
        # Look for two dates
        pattern = r'(\d{4}-\d{2}-\d{2})'
        matches = re.findall(pattern, user_text)
        
        if len(matches) >= 2:
            return (matches[0], matches[1])
        
        # Look for "between DATE and DATE" pattern
        pattern = r'between\s+(\S+)\s+and\s+(\S+)'
        match = re.search(pattern, user_text.lower())
        if match:
            date1 = self._extract_date(match.group(1))
            date2 = self._extract_date(match.group(2))
            if date1 and date2:
                return (date1, date2)
        
        return None

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
async def try_prompt_query(
    user_question: str,
    restaurant_names: List[str],
    conn
) -> Optional[Dict]:
    """
    Try to match and execute a prompt query
    Returns None if no match, or result dict if matched
    """
    try:
        executor = SimplePromptExecutor(conn)
        result = executor.execute_query(user_question, restaurant_names)
        
        if result and result.get('matched'):
            return result
        
        return None
    except Exception as e:
        logger.error(f"Error in try_prompt_query: {e}", exc_info=True)
        return None