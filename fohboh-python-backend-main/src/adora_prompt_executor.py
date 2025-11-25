

"""
Adora Prompt Executor - Matches text and runs SQL queries OR KPI calculations on Adora database
Supports time periods: All time, Last week, Last 15 days, Last month, Last 6 months, Last year
NEW: Supports absolute date ranges with automatic detection
"""
import json
import logging
import os
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import psycopg2.extras
import re
from dateutil import parser as date_parser

logger = logging.getLogger(__name__)


class AdoraPromptExecutor:
    """Execute SQL queries OR KPI calculations for Adora restaurants based on simple text matching"""
    
    def __init__(self, conn):
        self.conn = conn
        self.prompts = self._load_prompts()
    
    def _load_prompts(self) -> List[Dict]:
        """Load Adora prompts from JSON file"""
        prompt_file = os.path.join(os.path.dirname(__file__), 'adora_prompts.json')
        try:
            with open(prompt_file, 'r') as f:
                data = json.load(f)
                logger.info(f"Loaded {len(data.get('prompts', []))} Adora prompts")
                return data.get('prompts', [])
        except Exception as e:
            logger.error(f"Error loading Adora prompts: {e}")
            return []
    
    def match_prompt(self, user_text: str) -> Optional[Dict]:
        """
        Find matching prompt based on text patterns
        Returns the first matching prompt
        """
        user_text_lower = user_text.lower().strip()
        logger.info(f"🔍 Matching Adora text: '{user_text_lower}'")
        
        for prompt in self.prompts:
            for pattern in prompt['text_patterns']:
                if pattern.lower() in user_text_lower:
                    logger.info(f"✅ Matched Adora pattern '{pattern}' in prompt '{prompt['id']}'")
                    return prompt
        
        logger.info("❌ No Adora prompt matched")
        return None
    
    def _parse_date_flexible(self, date_string: str) -> Optional[datetime.date]:
        """
        Parse date from multiple formats:
        - dd/mm/yyyy (05/08/2024)
        - dd-mm-yyyy (05-08-2024)
        - yyyy-mm-dd (2024-08-05)
        - Natural language (6 november 2025, august 5 2024)
        """
        date_string = date_string.strip()
        
        # Try common formats first
        formats = [
            '%d/%m/%Y',  # 05/08/2024
            '%d-%m-%Y',  # 05-08-2024
            '%Y-%m-%d',  # 2024-08-05
            '%Y/%m/%d',  # 2024/08/05
            '%m/%d/%Y',  # 08/05/2024 (US format)
            '%d %B %Y',  # 5 August 2024
            '%d %b %Y',  # 5 Aug 2024
            '%B %d %Y',  # August 5 2024
            '%b %d %Y',  # Aug 5 2024
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_string, fmt).date()
            except ValueError:
                continue
        
        # Try dateutil parser as fallback (handles natural language)
        try:
            parsed = date_parser.parse(date_string, dayfirst=True)
            return parsed.date()
        except:
            pass
        
        return None
    
    def _extract_date_range(self, user_text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Extract absolute date range from user text.
        Returns: (start_date, end_date, description)
        
        Supports patterns:
        - "on 08/05/2024" -> single date
        - "from 05/08/2024 to 10/08/2024" -> date range
        - "between 5 august 2024 and 10 august 2024"
        - "in sales on 08/05/2024"
        
        Maximum 20 days range enforced.
        """
        user_text_lower = user_text.lower().strip()
        
        # Pattern 1: "from DATE to DATE" or "between DATE and DATE"
        range_patterns = [
            r'from\s+([0-9/\-\w\s]+?)\s+to\s+([0-9/\-\w\s]+)',
            r'between\s+([0-9/\-\w\s]+?)\s+and\s+([0-9/\-\w\s]+)',
        ]
        
        for pattern in range_patterns:
            match = re.search(pattern, user_text_lower)
            if match:
                start_str = match.group(1).strip()
                end_str = match.group(2).strip()
                
                start_date = self._parse_date_flexible(start_str)
                end_date = self._parse_date_flexible(end_str)
                
                if start_date and end_date:
                    # Ensure start is before end
                    if start_date > end_date:
                        start_date, end_date = end_date, start_date
                    
                    # Check 20-day limit
                    days_diff = (end_date - start_date).days
                    if days_diff > 20:
                        logger.warning(f"Date range exceeds 20 days ({days_diff} days), capping to 20 days")
                        end_date = start_date + timedelta(days=20)
                    
                    logger.info(f"📅 Detected date range: {start_date} to {end_date} ({days_diff} days)")
                    return (
                        start_date.strftime('%Y-%m-%d'),
                        end_date.strftime('%Y-%m-%d'),
                        f"{start_date.strftime('%d/%m/%Y')} to {end_date.strftime('%d/%m/%Y')}"
                    )
        
        # Pattern 2: "on DATE" - single date
        single_patterns = [
            r'on\s+([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{4})',  # on 08/05/2024
            r'on\s+([0-9]{1,2}\s+\w+\s+[0-9]{4})',  # on 5 august 2024
            r'for\s+([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{4})',  # for 08/05/2024
        ]
        
        for pattern in single_patterns:
            match = re.search(pattern, user_text_lower)
            if match:
                date_str = match.group(1).strip()
                single_date = self._parse_date_flexible(date_str)
                
                if single_date:
                    logger.info(f"📅 Detected single date: {single_date}")
                    return (
                        single_date.strftime('%Y-%m-%d'),
                        single_date.strftime('%Y-%m-%d'),
                        f"on {single_date.strftime('%d/%m/%Y')}"
                    )
        
        # No date range detected
        return None, None, None
    
    def _extract_time_period(self, user_text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Extract relative time period from user text
        Returns: (start_date, end_date, period_name)
        
        Supports:
        - last week / past week / previous week
        - last 15 days / past 15 days / last fifteen days
        - last month / past month / previous month
        - last 6 months / past 6 months / last six months
        - last year / past year / previous year / 365 days
        - all time / all / total (default)
        """
        user_text_lower = user_text.lower().strip()
        today = datetime.now().date()
        
        # Last week
        if any(term in user_text_lower for term in ['last week', 'past week', 'previous week', 'this week']):
            start_date = (today - timedelta(days=7)).strftime('%Y-%m-%d')
            end_date = today.strftime('%Y-%m-%d')
            logger.info(f"📅 Detected time period: Last Week ({start_date} to {end_date})")
            return start_date, end_date, 'Last_week'
        
        # Last 15 days
        elif any(term in user_text_lower for term in [
            'last 15 days', 'past 15 days', 'previous 15 days',
            'last fifteen days', 'past fifteen days', '15 days'
        ]):
            start_date = (today - timedelta(days=15)).strftime('%Y-%m-%d')
            end_date = today.strftime('%Y-%m-%d')
            logger.info(f"📅 Detected time period: Last 15 Days ({start_date} to {end_date})")
            return start_date, end_date, 'Last_15_days'
        
        # Last month
        elif any(term in user_text_lower for term in ['last month', 'past month', 'previous month', 'this month']):
            start_date = (today - timedelta(days=30)).strftime('%Y-%m-%d')
            end_date = today.strftime('%Y-%m-%d')
            logger.info(f"📅 Detected time period: Last Month ({start_date} to {end_date})")
            return start_date, end_date, 'Last_month'
        
        # Last 6 months
        elif any(term in user_text_lower for term in [
            'last 6 months', 'past 6 months', 'previous 6 months',
            'last six months', 'past six months', '6 months'
        ]):
            start_date = (today - timedelta(days=180)).strftime('%Y-%m-%d')
            end_date = today.strftime('%Y-%m-%d')
            logger.info(f"📅 Detected time period: Last 6 Months ({start_date} to {end_date})")
            return start_date, end_date, 'Last_6_months'
        
        # Last year / 365 days
        elif any(term in user_text_lower for term in [
            'last year', 'past year', 'previous year', 
            '365 days', 'last 365 days', 'this year'
        ]):
            start_date = (today - timedelta(days=365)).strftime('%Y-%m-%d')
            end_date = today.strftime('%Y-%m-%d')
            logger.info(f"📅 Detected time period: Last Year ({start_date} to {end_date})")
            return start_date, end_date, 'Last_year'
        
        # All time / total (default)
        else:
            # Use a very old start date to get all data
            start_date = '2000-01-01'
            end_date = today.strftime('%Y-%m-%d')
            logger.info(f"📅 Detected time period: All Time ({start_date} to {end_date})")
            return start_date, end_date, 'All'
    
    def _calculate_kpi(
        self,
        kpi_name: str,
        store_ids: List[str],
        start_date: str,
        end_date: str,
        period_name: str
    ) -> Optional[Dict]:
        """
        Calculate specific KPI using kpi_integration
        
        Args:
            kpi_name: Name of KPI to calculate (e.g., 'total_sales', 'all_kpis')
            store_ids: List of store IDs
            start_date: Start date for analysis
            end_date: End date for analysis
            period_name: Human-readable period name
            
        Returns:
            Dictionary with KPI results or None if error
        """
        try:
            # Import KPI calculator and integration
            from .kpi_integration import calculate_kpis_from_database
            
            logger.info(f"📊 Calculating KPI '{kpi_name}' for stores {store_ids}")
            logger.info(f"   Period: {period_name} ({start_date} to {end_date})")
            
            # Calculate KPIs for each store
            all_store_results = {}
            
            for store_id in store_ids:
                try:
                    # Call KPI calculation
                    results = calculate_kpis_from_database(
                        store_id=store_id,
                        start_date=start_date,
                        end_date=end_date,
                        db_connection=self.conn,
                        time_period=period_name
                    )
                    
                    all_store_results[store_id] = results
                    logger.info(f"   ✅ Calculated KPIs for store {store_id}")
                    
                except Exception as store_error:
                    logger.error(f"   ❌ Error calculating KPIs for store {store_id}: {store_error}")
                    all_store_results[store_id] = {
                        "error": str(store_error),
                        "kpis": {}
                    }
            
            return {
                "kpi_name": kpi_name,
                "period": period_name,
                "date_range": {
                    "start": start_date,
                    "end": end_date
                },
                "stores": all_store_results
            }
            
        except Exception as e:
            logger.error(f"Error calculating KPI '{kpi_name}': {e}", exc_info=True)
            return None
    
    def execute_query(
        self, 
        user_text: str, 
        store_ids: List[str]
    ) -> Optional[Dict]:
        """
        Match user text to a prompt and execute its SQL query OR calculate KPIs
        Returns raw results + formatted context for AI
        
        Args:
            user_text: User's question
            store_ids: List of store IDs to query (e.g., ['LE5AR'])
            
        Returns:
            Dict with 'matched', 'query_executed', 'result', 'data_for_ai'
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
        
        logger.info(f"🎯 Matched Adora prompt: {prompt['id']}")
        
        # Check if this requires KPI calculation
        if prompt.get('requires_kpi_calculation', False):
            return self._execute_kpi_query(prompt, user_text, store_ids)
        else:
            return self._execute_sql_query(prompt, user_text, store_ids)
    
    def _execute_sql_query(
        self,
        prompt: Dict,
        user_text: str,
        store_ids: List[str]
    ) -> Dict:
        """Execute regular SQL query with optional date filtering"""
        try:
            # Use RealDictCursor to get results as dictionaries
            cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            # Get base SQL
            base_sql = prompt['sql']
            params = [tuple(store_ids)]
            
            # Check if prompt supports date filtering
            supports_date_filtering = prompt.get('supports_date_filtering', False)
            date_column = prompt.get('date_column', None)
            
            # Extract dates from user text
            start_date, end_date, date_description = self._extract_date_range(user_text)
            
            # If no absolute dates found, try relative time periods (for KPI-like queries)
            if not start_date and supports_date_filtering:
                start_date, end_date, date_description = self._extract_time_period(user_text)
            
            # Add date filtering to SQL if applicable
            if supports_date_filtering and date_column and start_date and end_date:
                # Modify SQL to add date filter
                # Remove the final ORDER BY and LIMIT if present, we'll add them back
                sql_parts = base_sql.split('ORDER BY')
                where_clause = sql_parts[0]
                order_clause = 'ORDER BY' + sql_parts[1] if len(sql_parts) > 1 else ''
                
                # Add date condition
                if 'GROUP BY' in where_clause:
                    # Insert before GROUP BY
                    parts = where_clause.split('GROUP BY')
                    date_filter = f" AND {date_column} >= %s AND {date_column} <= %s "
                    modified_sql = parts[0] + date_filter + 'GROUP BY' + parts[1] + ' ' + order_clause
                else:
                    # Insert before ORDER BY
                    date_filter = f" AND {date_column} >= %s AND {date_column} <= %s "
                    modified_sql = where_clause + date_filter + order_clause
                
                params.extend([start_date, end_date])
                logger.info(f"📅 Added date filter: {date_column} between {start_date} and {end_date}")
            else:
                modified_sql = base_sql
            
            # Handle queries that need keyword extraction
            if prompt.get('requires_keyword', False):
                keyword = self._extract_keyword(user_text, prompt['text_patterns'])
                if not keyword:
                    logger.warning("Keyword required but not found")
                    return {
                        'matched': True,
                        'query_executed': False,
                        'result': None,
                        'data_for_ai': None
                    }
                
                logger.info(f"🔎 Executing Adora query with keyword: {keyword}")
                params.append(f'%{keyword}%')
            
            logger.info(f"🔎 Executing SQL query...")
            logger.info(f"   SQL: {modified_sql[:200]}...")
            logger.info(f"   Params: {params}")
            
            cur.execute(modified_sql, params)
            
            # Fetch results
            results = cur.fetchall()
            logger.info(f"📊 Adora query returned {len(results)} rows")
            
            if results:
                logger.info(f"First result: {results[0]}")
            
            # Format data for AI to understand
            data_for_ai = self._format_for_ai(prompt, results, store_ids, date_description)
            logger.info(f"✅ Formatted Adora context for AI ({len(data_for_ai)} chars)")
            
            return {
                'matched': True,
                'query_executed': True,
                'prompt_id': prompt['id'],
                'result': results,
                'data_for_ai': data_for_ai,
                'query_type': 'sql',
                'date_range': date_description if start_date else None
            }
            
        except Exception as e:
            logger.error(f"❌ Error executing Adora query: {e}", exc_info=True)
            return {
                'matched': True,
                'query_executed': False,
                'error': str(e),
                'data_for_ai': None
            }
    
    def _execute_kpi_query(
        self,
        prompt: Dict,
        user_text: str,
        store_ids: List[str]
    ) -> Dict:
        """Execute KPI calculation (new functionality)"""
        try:
            kpi_name = prompt.get('kpi_name')
            
            # Handle combined KPI requests (e.g., guest count and average check)
            if kpi_name == 'guest_and_avg_check':
                # This will calculate both guest_count and avg_check
                combined_kpis = ['guest_count', 'avg_check']
            else:
                combined_kpis = None
            
            # Extract time period if supported
            if prompt.get('supports_time_period', False):
                # First try absolute dates
                start_date, end_date, period_name = self._extract_date_range(user_text)
                
                # If no absolute dates, try relative periods
                if not start_date:
                    start_date, end_date, period_name = self._extract_time_period(user_text)
            else:
                # Use current data only
                today = datetime.now().date().strftime('%Y-%m-%d')
                start_date, end_date, period_name = today, today, 'current'
            
            logger.info(f"📊 Executing KPI calculation: {kpi_name}")
            logger.info(f"   Period: {period_name} ({start_date} to {end_date})")
            
            # Calculate KPIs
            kpi_results = self._calculate_kpi(
                kpi_name=kpi_name if not combined_kpis else 'all_kpis',
                store_ids=store_ids,
                start_date=start_date,
                end_date=end_date,
                period_name=period_name
            )
            
            if not kpi_results:
                logger.error("KPI calculation returned None")
                return {
                    'matched': True,
                    'query_executed': False,
                    'error': 'KPI calculation failed',
                    'data_for_ai': None
                }
            
            # Format KPI results for AI
            if combined_kpis:
                data_for_ai = self._format_combined_kpis_for_ai(
                    combined_kpis, kpi_results, period_name
                )
            else:
                data_for_ai = self._format_kpi_for_ai(kpi_name, kpi_results, period_name)
            
            logger.info(f"✅ Formatted KPI context for AI ({len(data_for_ai)} chars)")
            
            return {
                'matched': True,
                'query_executed': True,
                'prompt_id': prompt['id'],
                'result': kpi_results,
                'data_for_ai': data_for_ai,
                'query_type': 'kpi',
                'kpi_name': kpi_name,
                'period': period_name
            }
            
        except Exception as e:
            logger.error(f"❌ Error executing KPI query: {e}", exc_info=True)
            return {
                'matched': True,
                'query_executed': False,
                'error': str(e),
                'data_for_ai': None
            }
    
    def _format_combined_kpis_for_ai(
        self, kpi_names: List[str], kpi_results: Dict, period_name: str
    ) -> str:
        """Format multiple KPIs together for AI context"""
        context = f"Combined KPI Analysis ({period_name}):\n\n"
        
        date_range = kpi_results.get('date_range', {})
        context += f"Analysis Period: {date_range.get('start')} to {date_range.get('end')}\n\n"
        
        stores_data = kpi_results.get('stores', {})
        
        for store_id, store_results in stores_data.items():
            context += f"=== Store {store_id} ===\n\n"
            
            if 'error' in store_results:
                context += f"Error: {store_results['error']}\n\n"
                continue
            
            kpis = store_results.get('kpis', {})
            
            for kpi_name in kpi_names:
                if kpi_name in kpis:
                    context += self._format_single_kpi(kpi_name, kpis[kpi_name])
                    context += "\n"
            
            context += "\n"
        
        return context
    
    def _format_kpi_for_ai(self, kpi_name: str, kpi_results: Dict, period_name: str) -> str:
        """
        Format KPI results into natural language context for AI
        """
        context = f"KPI Analysis Results ({period_name}):\n\n"
        
        date_range = kpi_results.get('date_range', {})
        context += f"Analysis Period: {date_range.get('start')} to {date_range.get('end')}\n\n"
        
        stores_data = kpi_results.get('stores', {})
        
        for store_id, store_results in stores_data.items():
            context += f"=== Store {store_id} ===\n\n"
            
            if 'error' in store_results:
                context += f"Error: {store_results['error']}\n\n"
                continue
            
            kpis = store_results.get('kpis', {})
            errors = store_results.get('errors', [])
            warnings = store_results.get('warnings', [])
            
            # Handle different KPI formats
            if kpi_name == 'all_kpis':
                # Format all KPIs
                context += self._format_all_kpis(kpis)
            else:
                # Format specific KPI
                context += self._format_single_kpi(kpi_name, kpis.get(kpi_name))
            
            # Add errors/warnings
            if errors:
                context += "\n⚠️ Errors:\n"
                for error in errors:
                    context += f"  - {error.get('kpi', 'Unknown')}: {error.get('error', 'Unknown error')}\n"
            
            if warnings:
                context += "\n⚠️ Warnings:\n"
                for warning in warnings:
                    context += f"  - {warning.get('kpi', 'Unknown')}: {warning.get('warning', 'Unknown warning')}\n"
            
            context += "\n"
        
        return context
    
    def _format_all_kpis(self, kpis: Dict) -> str:
        """Format all KPIs for AI context"""
        context = ""
        
        # KPI 1: Total Sales
        if 'total_sales' in kpis:
            ts = kpis['total_sales']
            context += f"**Total Sales:** ${ts.get('value', 0):,.2f}\n"
        
        # KPI 2: Net Revenue
        if 'net_revenue' in kpis:
            nr = kpis['net_revenue']
            context += f"**Net Revenue:** ${nr.get('value', 0):,.2f}\n"
            deductions = nr.get('deductions', {})
            if deductions:
                context += f"  - Comps: ${deductions.get('comps', 0):,.2f}\n"
                context += f"  - Promos: ${deductions.get('promos', 0):,.2f}\n"
                context += f"  - Voids: ${deductions.get('voids', 0):,.2f}\n"
        
        # KPI 3: SPLH
        if 'splh' in kpis:
            splh = kpis['splh']
            context += f"**Sales per Labor Hour (SPLH):** ${splh.get('value', 0):,.2f}\n"
            context += f"  - Labor Hours: {splh.get('labor_hours', 0):,.2f}\n"
        
        # KPI 4: Guest Count
        if 'guest_count' in kpis:
            gc = kpis['guest_count']
            context += f"**Guest Count:** {gc.get('value', 0):,}\n"
        
        # KPI 5: Average Check
        if 'avg_check' in kpis:
            ac = kpis['avg_check']
            context += f"**Average Check:** ${ac.get('value', 0):,.2f}\n"
        
        # KPI 6: Top Items
        if 'top_items' in kpis:
            ti = kpis['top_items']
            items = ti.get('value', [])
            if items:
                context += f"\n**Top Selling Items (Top 5):**\n"
                for i, item in enumerate(items[:5], 1):
                    context += f"  {i}. {item.get('item_name')}: {item.get('quantity_sold')} sold, ${item.get('revenue', 0):,.2f} revenue\n"
        
        # KPI 8: Food Cost %
        if 'food_cost_pct' in kpis:
            fc = kpis['food_cost_pct']
            context += f"\n**Food Cost %:** {fc.get('value', 0):.2f}%\n"
            context += f"  - Total Food Cost: ${fc.get('total_food_cost', 0):,.2f}\n"
            context += f"  - Total Food Sales: ${fc.get('total_food_sales', 0):,.2f}\n"
        
        # KPI 10: Inventory Turnover
        if 'inventory_turnover' in kpis:
            it = kpis['inventory_turnover']
            context += f"**Inventory Turnover:** {it.get('value', 0):.2f}x\n"
        
        # KPI 11: Low Inventory
        if 'low_inventory_warnings' in kpis:
            li = kpis['low_inventory_warnings']
            warnings = li.get('value', [])
            if warnings:
                context += f"\n**Low Inventory Items ({len(warnings)}):**\n"
                for warning in warnings[:5]:
                    context += f"  - {warning.get('ingredient')}: {warning.get('current_quantity')} (Par: {warning.get('par_level')})\n"
        
        # KPI 13: Overtime %
        if 'overtime_pct' in kpis:
            ot = kpis['overtime_pct']
            context += f"\n**Overtime Hours %:** {ot.get('value', 0):.2f}%\n"
            context += f"  - Total Hours: {ot.get('total_hours', 0):,.2f}\n"
            context += f"  - Overtime Hours: {ot.get('total_overtime_hours', 0):,.2f}\n"
        
        return context
    
    def _format_single_kpi(self, kpi_name: str, kpi_data: Optional[Dict]) -> str:
        """Format a single KPI for AI context"""
        if not kpi_data:
            return f"No data available for {kpi_name}\n"
        
        context = ""
        
        if kpi_name == 'total_sales':
            context += f"**Total Sales:** ${kpi_data.get('value', 0):,.2f}\n"
        
        elif kpi_name == 'net_revenue':
            context += f"**Net Revenue:** ${kpi_data.get('value', 0):,.2f}\n"
            context += f"Gross Sales: ${kpi_data.get('gross_sales', 0):,.2f}\n"
            deductions = kpi_data.get('deductions', {})
            if deductions:
                context += "Deductions:\n"
                context += f"  - Comps: ${deductions.get('comps', 0):,.2f}\n"
                context += f"  - Promos: ${deductions.get('promos', 0):,.2f}\n"
                context += f"  - Voids: ${deductions.get('voids', 0):,.2f}\n"
                context += f"  - Discounts: ${deductions.get('discounts', 0):,.2f}\n"
        
        elif kpi_name == 'splh':
            context += f"**Sales per Labor Hour:** ${kpi_data.get('value', 0):,.2f}\n"
            context += f"Net Revenue: ${kpi_data.get('net_revenue', 0):,.2f}\n"
            context += f"Labor Hours: {kpi_data.get('labor_hours', 0):,.2f}\n"
        
        elif kpi_name == 'guest_count':
            context += f"**Guest Count:** {kpi_data.get('value', 0):,}\n"
            context += f"Method: {kpi_data.get('method', 'unknown')}\n"
        
        elif kpi_name == 'avg_check':
            context += f"**Average Check:** ${kpi_data.get('value', 0):,.2f}\n"
            context += f"Net Revenue: ${kpi_data.get('net_revenue', 0):,.2f}\n"
            context += f"Guest Count: {kpi_data.get('guest_count', 0):,}\n"
        
        elif kpi_name == 'top_items':
            items = kpi_data.get('value', [])
            context += f"**Top Selling Items ({len(items)} total):**\n\n"
            for i, item in enumerate(items[:10], 1):
                context += f"{i}. {item.get('item_name')}\n"
                context += f"   - Quantity Sold: {item.get('quantity_sold')}\n"
                context += f"   - Revenue: ${item.get('revenue', 0):,.2f}\n"
        
        elif kpi_name == 'gross_profit_per_item':
            items = kpi_data.get('value', [])
            context += f"**Gross Profit per Item ({len(items)} items):**\n\n"
            for i, item in enumerate(items[:10], 1):
                context += f"{i}. {item.get('item_name')}\n"
                context += f"   - Revenue: ${item.get('revenue', 0):,.2f}\n"
                context += f"   - Cost: ${item.get('cost', 0):,.2f}\n"
                context += f"   - Gross Profit: ${item.get('gross_profit', 0):,.2f}\n"
                context += f"   - Margin: {item.get('margin_percent', 0):.2f}%\n"
                context += f"   - Quantity Sold: {item.get('quantity_sold')}\n"
        
        elif kpi_name == 'food_cost_pct':
            context += f"**Food Cost Percentage:** {kpi_data.get('value', 0):.2f}%\n"
            context += f"Total Food Cost: ${kpi_data.get('total_food_cost', 0):,.2f}\n"
            context += f"Total Food Sales: ${kpi_data.get('total_food_sales', 0):,.2f}\n"
        
        elif kpi_name == 'cogs_by_category':
            categories = kpi_data.get('value', [])
            context += f"**COGS by Category:**\n"
            context += f"Total COGS: ${kpi_data.get('total_cogs', 0):,.2f}\n\n"
            for cat in categories:
                context += f"- {cat.get('category')}: ${cat.get('total_cogs', 0):,.2f}\n"
        
        elif kpi_name == 'inventory_turnover':
            context += f"**Inventory Turnover Rate:** {kpi_data.get('value', 0):.2f}x\n"
            context += f"Total COGS: ${kpi_data.get('total_cogs', 0):,.2f}\n"
            context += f"Avg Inventory Value: ${kpi_data.get('avg_inventory_value', 0):,.2f}\n"
        
        elif kpi_name == 'low_inventory_warnings':
            warnings = kpi_data.get('value', [])
            context += f"**Low Inventory Warnings ({len(warnings)} items):**\n\n"
            for warning in warnings:
                context += f"- {warning.get('ingredient')}\n"
                context += f"  Current: {warning.get('current_quantity')}\n"
                context += f"  Par Level: {warning.get('par_level')}\n"
                context += f"  Shortage: {warning.get('shortage')}\n"
        
        elif kpi_name == 'labor_hours_by_role':
            roles = kpi_data.get('value', [])
            context += f"**Labor Hours by Role:**\n"
            context += f"Total Hours: {kpi_data.get('total_hours', 0):,.2f}\n\n"
            for role in roles:
                context += f"- {role.get('role')}: {role.get('total_hours', 0):,.2f} hours\n"
        
        elif kpi_name == 'overtime_pct':
            context += f"**Overtime Hours Percentage:** {kpi_data.get('value', 0):.2f}%\n"
            context += f"Total Hours: {kpi_data.get('total_hours', 0):,.2f}\n"
            context += f"Overtime Hours: {kpi_data.get('total_overtime_hours', 0):,.2f}\n\n"
            
            by_role = kpi_data.get('by_role', [])
            if by_role:
                context += "**By Role:**\n"
                for role in by_role[:5]:
                    context += f"- {role.get('role')}: {role.get('overtime_pct', 0):.2f}% ({role.get('overtime_hours', 0):.2f}h / {role.get('total_hours', 0):.2f}h)\n"
        
        elif kpi_name == 'popularity_vs_profitability':
            items = kpi_data.get('value', [])
            summary = kpi_data.get('summary', {})
            
            context += f"**Menu Engineering Analysis:**\n"
            context += f"Total Items Analyzed: {summary.get('total_items', 0)}\n"
            context += f"Median Quantity: {summary.get('median_quantity', 0):.2f}\n"
            context += f"Median Profit: ${summary.get('median_profit', 0):,.2f}\n\n"
            
            context += f"**Quadrant Distribution:**\n"
            context += f"- STAR items: {summary.get('stars', 0)} (High popularity, High profitability)\n"
            context += f"- PLOW HORSE items: {summary.get('plow_horses', 0)} (High popularity, Low profitability)\n"
            context += f"- PUZZLE items: {summary.get('puzzles', 0)} (Low popularity, High profitability)\n"
            context += f"- DOG items: {summary.get('dogs', 0)} (Low popularity, Low profitability)\n\n"
            
            # Show top items by quadrant
            stars = [i for i in items if i.get('quadrant') == 'STAR']
            if stars:
                context += "**STAR Items (Keep & Promote):**\n"
                for item in stars[:3]:
                    context += f"- {item.get('item_name')}: {item.get('quantity_sold')} sold, ${item.get('gross_profit', 0):,.2f} profit\n"
            
            puzzles = [i for i in items if i.get('quadrant') == 'PUZZLE']
            if puzzles:
                context += "\n**PUZZLE Items (Hidden Gems - Promote More):**\n"
                for item in puzzles[:3]:
                    context += f"- {item.get('item_name')}: {item.get('quantity_sold')} sold, ${item.get('gross_profit', 0):,.2f} profit\n"
            
            dogs = [i for i in items if i.get('quadrant') == 'DOG']
            if dogs:
                context += "\n**DOG Items (Consider Removing):**\n"
                for item in dogs[:3]:
                    context += f"- {item.get('item_name')}: {item.get('quantity_sold')} sold, ${item.get('gross_profit', 0):,.2f} profit\n"
        
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
    
    def _format_for_ai(self, prompt: Dict, results: List, store_ids: List[str], date_description: Optional[str] = None) -> str:
        """
        Format SQL results into context for AI to understand
        This creates a natural language description of the data
        """
        if not results:
            context = f"No data found for stores: {', '.join(store_ids)}"
            if date_description:
                context += f"\nDate range: {date_description}"
            return context
        
        context = f"Database Query Results (Adora Stores):\n\n"
        
        if date_description:
            context += f"Date Range: {date_description}\n\n"
        
        # ========== INVENTORY PROMPTS ==========
        if prompt['id'] == 'adora_count_inventory':
            context += "Inventory counts by store:\n"
            for row in results:
                store_id = row.get('store_id', 'Unknown')
                total = row.get('total', 0)
                context += f"- Store {store_id}: {total} items\n"
            context += "\nThis shows the total number of inventory items tracked for each store.\n"
        
        elif prompt['id'] == 'adora_list_ingredients':
            context += "Ingredients by store:\n\n"
            current_store = None
            for row in results:
                store_id = row.get('store_id', 'Unknown')
                ingredient = row.get('ingredient', 'Unknown')
                
                if store_id != current_store:
                    context += f"\n**Store {store_id}:**\n"
                    current_store = store_id
                
                if ingredient and ingredient.strip():
                    context += f"  - {ingredient.strip()}\n"
        
        elif prompt['id'] == 'adora_low_stock':
            if results:
                context += "Low stock items by store:\n\n"
                current_store = None
                
                for row in results:
                    store_id = row.get('store_id', 'Unknown')
                    ingredient = row.get('ingredient', 'Unknown')
                    quantity = row.get('quantity', 'N/A')
                    par_level = row.get('par_level', 'N/A')
                    
                    if store_id != current_store:
                        context += f"\n**Store {store_id}:**\n"
                        current_store = store_id
                    
                    context += f"  - {ingredient}: {quantity} units (Par Level: {par_level})\n"
            else:
                context += "No items are currently flagged as low stock.\n"
        
        elif prompt['id'] == 'adora_search_ingredient':
            context += f"Search results across stores ({len(results)} matches):\n\n"
            current_store = None
            
            for i, row in enumerate(results, 1):
                store_id = row.get('store_id', 'Unknown')
                ingredient = row.get('ingredient', '')
                quantity = row.get('quantity', 'N/A')
                
                if store_id != current_store:
                    context += f"\n**Store {store_id}:**\n"
                    current_store = store_id
                
                context += f"  {i}. {ingredient}: {quantity} units\n"
        
        elif prompt['id'] == 'adora_total_inventory_value':
            context += "Total inventory value by store:\n"
            for row in results:
                store_id = row.get('store_id', 'Unknown')
                total_value = row.get('total_value', 0)
                
                if total_value:
                    context += f"- Store {store_id}: ${float(total_value):,.2f}\n"
                else:
                    context += f"- Store {store_id}: $0.00 (no cost data available)\n"
            
            context += "\nThese values represent the sum of all inventory items' costs per store.\n"
        
        elif prompt['id'] == 'adora_waste_items':
            if results:
                context += "Items with waste by store:\n\n"
                current_store = None
                
                for row in results:
                    store_id = row.get('store_id', 'Unknown')
                    ingredient = row.get('ingredient', 'Unknown')
                    quantity = row.get('quantity', 'N/A')
                    waste = row.get('waste', 0)
                    
                    if store_id != current_store:
                        context += f"\n**Store {store_id}:**\n"
                        current_store = store_id
                    
                    context += f"  - {ingredient}: {quantity} units, Waste: {waste}\n"
            else:
                context += "No items with recorded waste.\n"
        
        # ========== MENU PROMPTS ==========
        elif prompt['id'] == 'adora_menu_items':
            context += "Menu items by store:\n\n"
            current_store = None
            
            for row in results:
                store_id = row.get('store_id', 'Unknown')
                menu_item = row.get('menu_item', 'Unknown')
                ingredient = row.get('ingredient', '')
                amount = row.get('amount', '')
                unit_cost = row.get('unit_cost', 0)
                
                if store_id != current_store:
                    context += f"\n**Store {store_id}:**\n"
                    current_store = store_id
                
                cost_str = f" - ${float(unit_cost):.2f}" if unit_cost else ""
                ingredient_str = f" (Contains: {ingredient})" if ingredient else ""
                context += f"  - {menu_item}{cost_str}{ingredient_str}\n"
        
        elif prompt['id'] == 'adora_search_menu_item':
            context += f"Menu item search results ({len(results)} matches):\n\n"
            current_store = None
            
            for row in results:
                store_id = row.get('store_id', 'Unknown')
                menu_item = row.get('menu_item', 'Unknown')
                ingredient = row.get('ingredient', '')
                unit_cost = row.get('unit_cost', 0)
                
                if store_id != current_store:
                    context += f"\n**Store {store_id}:**\n"
                    current_store = store_id
                
                cost_str = f" - ${float(unit_cost):.2f}" if unit_cost else ""
                ingredient_str = f" (Contains: {ingredient})" if ingredient else ""
                context += f"  - {menu_item}{cost_str}{ingredient_str}\n"
        
        elif prompt['id'] == 'adora_menu_by_ingredient':
            context += f"Menu items containing specified ingredient ({len(results)} matches):\n\n"
            current_store = None
            
            for row in results:
                store_id = row.get('store_id', 'Unknown')
                menu_item = row.get('menu_item', 'Unknown')
                ingredient = row.get('ingredient', '')
                amount = row.get('amount', '')
                
                if store_id != current_store:
                    context += f"\n**Store {store_id}:**\n"
                    current_store = store_id
                
                amount_str = f" ({amount})" if amount else ""
                context += f"  - {menu_item}: {ingredient}{amount_str}\n"
        
        elif prompt['id'] == 'adora_expensive_menu_items':
            context += "Most expensive menu items:\n\n"
            current_store = None
            
            for row in results:
                store_id = row.get('store_id', 'Unknown')
                menu_item = row.get('menu_item', 'Unknown')
                unit_cost = row.get('unit_cost', 0)
                
                if store_id != current_store:
                    context += f"\n**Store {store_id}:**\n"
                    current_store = store_id
                
                context += f"  - {menu_item}: ${float(unit_cost):.2f}\n"
        
        # ========== SALES PROMPTS ==========
        elif prompt['id'] in ['adora_sales_today', 'adora_sales_yesterday', 'adora_sales_this_week', 'adora_sales_by_date', 'adora_sales_date_range']:
            period_name = "Today's" if 'today' in prompt['id'] else "Yesterday's" if 'yesterday' in prompt['id'] else "This week's" if 'week' in prompt['id'] else "Sales for specified period"
            
            if date_description:
                context += f"Sales {date_description}:\n\n"
            else:
                context += f"{period_name} sales by store:\n\n"
            
            for row in results:
                store_id = row.get('store_id', 'Unknown')
                total_sales = row.get('total_sales', 0)
                total_revenue = row.get('total_revenue', 0)
                avg_order = row.get('avg_order', None)
                
                context += f"**Store {store_id}:**\n"
                context += f"  - Total Orders: {total_sales}\n"
                context += f"  - Total Revenue: ${float(total_revenue):,.2f}\n"
                if avg_order is not None:
                    context += f"  - Average Order: ${float(avg_order):.2f}\n"
                context += "\n"
        
        elif prompt['id'] == 'adora_top_selling_items':
            context += "Top selling items across stores:\n\n"
            current_store = None
            
            for row in results:
                store_id = row.get('store_id', 'Unknown')
                item_name = row.get('sold_items_name', 'Unknown')
                total_sold = row.get('total_sold', 0)
                order_count = row.get('order_count', 0)
                
                if store_id != current_store:
                    context += f"\n**Store {store_id}:**\n"
                    current_store = store_id
                
                context += f"  - {item_name}: {total_sold} units sold ({order_count} orders)\n"
        
        elif prompt['id'] == 'adora_sales_by_payment':
            context += "Sales breakdown by payment method:\n\n"
            current_store = None
            
            for row in results:
                store_id = row.get('store_id', 'Unknown')
                payment_method = row.get('payment_method', 'Unknown')
                transaction_count = row.get('transaction_count', 0)
                total_revenue = row.get('total_revenue', 0)
                
                if store_id != current_store:
                    context += f"\n**Store {store_id}:**\n"
                    current_store = store_id
                
                context += f"  - {payment_method}: {transaction_count} transactions, ${float(total_revenue):,.2f}\n"
        
        elif prompt['id'] == 'adora_sales_by_order_type':
            context += "Sales breakdown by order type:\n\n"
            current_store = None
            
            for row in results:
                store_id = row.get('store_id', 'Unknown')
                order_type = row.get('order_type', 'Unknown')
                order_count = row.get('order_count', 0)
                total_revenue = row.get('total_revenue', 0)
                
                if store_id != current_store:
                    context += f"\n**Store {store_id}:**\n"
                    current_store = store_id
                
                context += f"  - {order_type}: {order_count} orders, ${float(total_revenue):,.2f}\n"
        
        elif prompt['id'] == 'adora_average_order_value':
            context += "Average order value by store:\n\n"
            
            for row in results:
                store_id = row.get('store_id', 'Unknown')
                avg_order_value = row.get('avg_order_value', 0)
                total_orders = row.get('total_orders', 0)
                
                context += f"**Store {store_id}:**\n"
                context += f"  - Average Order Value: ${float(avg_order_value):.2f}\n"
                context += f"  - Based on {total_orders} orders\n\n"
        
        # ========== EMPLOYEE PROMPTS ==========
        elif prompt['id'] == 'adora_list_employees':
            context += "Employees by store:\n\n"
            current_store = None
            
            for row in results:
                store_id = row.get('store_id', 'Unknown')
                name = row.get('name', 'Unknown')
                role = row.get('role', 'Unknown')
                hire_date = row.get('hire_date', '')
                
                if store_id != current_store:
                    context += f"\n**Store {store_id}:**\n"
                    current_store = store_id
                
                hire_str = f" (Hired: {hire_date})" if hire_date else ""
                context += f"  - {name} - {role}{hire_str}\n"
        
        elif prompt['id'] == 'adora_count_employees':
            context += "Employee count by store:\n\n"
            
            for row in results:
                store_id = row.get('store_id', 'Unknown')
                total = row.get('total_employees', 0)
                context += f"- Store {store_id}: {total} employees\n"
        
        elif prompt['id'] == 'adora_employees_by_role':
            context += "Employees grouped by role:\n\n"
            current_store = None
            
            for row in results:
                store_id = row.get('store_id', 'Unknown')
                role = row.get('role', 'Unknown')
                count = row.get('count', 0)
                employee_names = row.get('employee_names', '')
                
                if store_id != current_store:
                    context += f"\n**Store {store_id}:**\n"
                    current_store = store_id
                
                context += f"  - {role} ({count}): {employee_names}\n"
        
        elif prompt['id'] == 'adora_search_employee':
            context += f"Employee search results ({len(results)} matches):\n\n"
            current_store = None
            
            for row in results:
                store_id = row.get('store_id', 'Unknown')
                name = row.get('name', 'Unknown')
                role = row.get('role', 'Unknown')
                hire_date = row.get('hire_date', '')
                hourly_rate = row.get('hourly_rate', None)
                
                if store_id != current_store:
                    context += f"\n**Store {store_id}:**\n"
                    current_store = store_id
                
                hire_str = f", Hired: {hire_date}" if hire_date else ""
                rate_str = f", Rate: ${float(hourly_rate):.2f}/hr" if hourly_rate else ""
                context += f"  - {name} ({role}{hire_str}{rate_str})\n"
        
        elif prompt['id'] == 'adora_new_hires':
            context += "Recent hires across stores:\n\n"
            current_store = None
            
            for row in results:
                store_id = row.get('store_id', 'Unknown')
                name = row.get('name', 'Unknown')
                role = row.get('role', 'Unknown')
                hire_date = row.get('hire_date', '')
                
                if store_id != current_store:
                    context += f"\n**Store {store_id}:**\n"
                    current_store = store_id
                
                context += f"  - {name} ({role}) - Hired: {hire_date}\n"
        
        else:
            # Generic formatting for unknown prompt types
            context += f"Query returned {len(results)} rows:\n\n"
            for i, row in enumerate(results[:10], 1):
                context += f"Row {i}: {dict(row)}\n"
        
        return context


# Helper function to use in endpoint
async def try_adora_prompt_query(
    user_question: str,
    store_ids: List[str],
    conn
) -> Optional[Dict]:
    """
    Try to match and execute an Adora prompt query (SQL or KPI)
    Returns None if no match, or result dict if matched
    """
    try:
        executor = AdoraPromptExecutor(conn)
        result = executor.execute_query(user_question, store_ids)
        
        if result and result.get('matched'):
            return result
        
        return None
    except Exception as e:
        logger.error(f"Error in try_adora_prompt_query: {e}", exc_info=True)
        return None