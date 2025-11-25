# kpi_calculator.py
"""
KPI Calculator implementing formulas from FohBoh_KPI_Formulas Excel file
Calculates 14 specific KPIs for restaurant analytics
Works with database data via kpi_integration.py
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, List
from datetime import datetime, timedelta
from collections import defaultdict
import traceback

logger = logging.getLogger(__name__)


class KPICalculationError(Exception):
    """Custom exception for KPI calculation errors"""
    def __init__(self, kpi_name: str, message: str, missing_columns: List[str] = None):
        self.kpi_name = kpi_name
        self.message = message
        self.missing_columns = missing_columns or []
        super().__init__(f"KPI '{kpi_name}' Error: {message}")


class KPICalculator:
    """
    Calculate 14 KPIs based on formulas from FohBoh_KPI_Formulas Excel file
    Designed to work with database data
    """
    
    def __init__(self):
        self.errors = []
        self.warnings = []
    
    def check_required_columns(self, df: pd.DataFrame, required_cols: List[str], kpi_name: str) -> bool:
        """Check if DataFrame has required columns"""
        if df.empty:
            error_msg = f"Empty DataFrame"
            self.errors.append({
                "kpi": kpi_name,
                "error": error_msg,
                "missing_columns": []
            })
            return False
        
        missing_cols = [col for col in required_cols if col not in df.columns]
        
        if missing_cols:
            error_msg = f"Missing required columns: {', '.join(missing_cols)}"
            self.errors.append({
                "kpi": kpi_name,
                "error": error_msg,
                "missing_columns": missing_cols
            })
            return False
        
        return True
    
    def safe_divide(self, numerator: float, denominator: float, default: float = None) -> float:
        """Safely divide two numbers, returning None or default if denominator is 0"""
        if denominator == 0 or pd.isna(denominator):
            return default
        return numerator / denominator
    
    # ==================== KPI 1: Total Sales ====================
    def calculate_total_sales(self, sales_df: pd.DataFrame) -> Dict[str, Any]:
        """
        KPI 1: Total Sales
        Formula: total_sales = SUM(gross_sales_pre_discounts_excl_tax)
        Required: sales[gross_sales] or sales[subtotal] or sales[total_amount]
        """
        kpi_name = "Total Sales"
        
        # Try multiple possible column names
        possible_cols = ['gross_sales', 'subtotal', 'total_amount']
        sales_col = None
        
        for col in possible_cols:
            if col in sales_df.columns:
                sales_col = col
                break
        
        if not sales_col:
            raise KPICalculationError(
                kpi_name,
                f"No valid sales column found. Tried: {', '.join(possible_cols)}",
                possible_cols
            )
        
        try:
            total_sales = float(sales_df[sales_col].sum())
            
            # Validation: total_sales >= 0
            if total_sales < 0:
                self.warnings.append({
                    "kpi": kpi_name,
                    "warning": f"Total sales is negative: {total_sales}"
                })
            
            return {
                "value": round(total_sales, 2),
                "column_used": sales_col,
                "validation_passed": total_sales >= 0
            }
        
        except Exception as e:
            raise KPICalculationError(kpi_name, str(e))
    
    # ==================== KPI 2: Net Revenue ====================
    def calculate_net_revenue(self, sales_df: pd.DataFrame) -> Dict[str, Any]:
        """
        KPI 2: Net Revenue (after comps/voids)
        Formula: net_revenue = gross_sales_pre_discounts_excl_tax - comps - promos - voids
        Required: sales[gross_sales, comps, voids, promos] (optional columns default to 0)
        """
        kpi_name = "Net Revenue"
        
        # Find gross sales column
        gross_cols = ['gross_sales', 'subtotal', 'total_amount']
        gross_col = None
        for col in gross_cols:
            if col in sales_df.columns:
                gross_col = col
                break
        
        if not gross_col:
            raise KPICalculationError(
                kpi_name,
                f"No valid gross sales column found. Tried: {', '.join(gross_cols)}",
                gross_cols
            )
        
        try:
            # Start with gross sales
            gross_sales = sales_df[gross_col].sum()
            
            # Subtract comps, promos, voids (default to 0 if not present)
            comps = sales_df['comps'].sum() if 'comps' in sales_df.columns else 0
            promos = sales_df['promos'].sum() if 'promos' in sales_df.columns else 0
            voids = sales_df['voids'].sum() if 'voids' in sales_df.columns else 0
            
            # Calculate discount from discount_percent if available
            discount_amount = 0
            if 'discount_percent' in sales_df.columns and gross_col in sales_df.columns:
                sales_df_copy = sales_df.copy()
                sales_df_copy['discount_amount'] = (
                    sales_df_copy[gross_col] * sales_df_copy['discount_percent'] / 100
                )
                discount_amount = sales_df_copy['discount_amount'].sum()
            
            net_revenue = gross_sales - comps - promos - voids - discount_amount
            
            # Validation
            if net_revenue < 0:
                self.warnings.append({
                    "kpi": kpi_name,
                    "warning": f"Net revenue is negative: {net_revenue}"
                })
            
            return {
                "value": round(net_revenue, 2),
                "gross_sales": round(gross_sales, 2),
                "deductions": {
                    "comps": round(comps, 2),
                    "promos": round(promos, 2),
                    "voids": round(voids, 2),
                    "discounts": round(discount_amount, 2)
                },
                "validation_passed": net_revenue >= 0
            }
        
        except Exception as e:
            raise KPICalculationError(kpi_name, str(e))
    
    # ==================== KPI 3: SPLH ====================
    def calculate_splh(self, sales_df: pd.DataFrame, labor_df: pd.DataFrame) -> Dict[str, Any]:
        """
        KPI 3: Sales per Labor Hour (SPLH)
        Formula: splh = net_revenue / labor_hours_hourly
        Required: sales[net_revenue], labor[hours_worked, is_salaried]
        """
        kpi_name = "Sales per Labor Hour (SPLH)"
        
        try:
            # Calculate net revenue
            net_revenue_result = self.calculate_net_revenue(sales_df)
            net_revenue = net_revenue_result["value"]
            
            # Calculate labor hours (exclude salaried if possible)
            if 'is_salaried' in labor_df.columns:
                hourly_hours = labor_df[labor_df['is_salaried'] == False]['hours_worked'].sum()
            elif 'hours_worked' in labor_df.columns:
                hourly_hours = labor_df['hours_worked'].sum()
                self.warnings.append({
                    "kpi": kpi_name,
                    "warning": "is_salaried column not found, using all labor hours"
                })
            else:
                raise KPICalculationError(
                    kpi_name,
                    "Missing required column: hours_worked",
                    ["hours_worked"]
                )
            
            splh = self.safe_divide(net_revenue, hourly_hours)
            
            return {
                "value": round(splh, 2) if splh is not None else None,
                "net_revenue": round(net_revenue, 2),
                "labor_hours": round(hourly_hours, 2),
                "validation_passed": splh is not None and splh >= 0
            }
        
        except Exception as e:
            raise KPICalculationError(kpi_name, str(e))
    
    # ==================== KPI 4: Guest Count ====================
    def calculate_guest_count(self, sales_df: pd.DataFrame) -> Dict[str, Any]:
        """
        KPI 4: Guest Count / Covers
        Formula: guest_count = SUM(covers) OR COUNT(DISTINCT check_id)
        Required: sales[covers] or sales[sale_id]
        """
        kpi_name = "Guest Count"
        
        try:
            if 'covers' in sales_df.columns:
                guest_count = int(sales_df['covers'].sum())
                method = "explicit_covers"
            elif 'number_of_items' in sales_df.columns:
                # Fallback: count number of transactions
                guest_count = len(sales_df)
                method = "transaction_count"
                self.warnings.append({
                    "kpi": kpi_name,
                    "warning": "covers column not found, using transaction count as approximation"
                })
            else:
                guest_count = len(sales_df)
                method = "transaction_count"
                self.warnings.append({
                    "kpi": kpi_name,
                    "warning": "covers column not found, using transaction count"
                })
            
            return {
                "value": guest_count,
                "method": method,
                "validation_passed": guest_count >= 0
            }
        
        except Exception as e:
            raise KPICalculationError(kpi_name, str(e))
    
    # ==================== KPI 5: Average Check ====================
    def calculate_avg_check(self, sales_df: pd.DataFrame) -> Dict[str, Any]:
        """
        KPI 5: Average Spend per Guest
        Formula: avg_check = net_revenue / guest_count
        Required: sales[net_revenue, covers]
        """
        kpi_name = "Average Check"
        
        try:
            net_revenue_result = self.calculate_net_revenue(sales_df)
            net_revenue = net_revenue_result["value"]
            
            guest_count_result = self.calculate_guest_count(sales_df)
            guest_count = guest_count_result["value"]
            
            avg_check = self.safe_divide(net_revenue, guest_count)
            
            return {
                "value": round(avg_check, 2) if avg_check is not None else None,
                "net_revenue": round(net_revenue, 2),
                "guest_count": guest_count,
                "validation_passed": avg_check is not None and avg_check >= 0
            }
        
        except Exception as e:
            raise KPICalculationError(kpi_name, str(e))
    
    # ==================== KPI 6: Top Selling Items ====================
    def calculate_top_items(self, sales_df: pd.DataFrame, limit: int = 10) -> Dict[str, Any]:
        """
        KPI 6: Top Selling Menu Items
        Formula: top_items = ORDER BY SUM(qty) DESC
        Required: sales[items_sold, total_amount]
        """
        kpi_name = "Top Selling Items"
        
        if not self.check_required_columns(sales_df, ['items_sold'], kpi_name):
            raise KPICalculationError(
                kpi_name,
                "Missing required column: items_sold",
                ["items_sold"]
            )
        
        try:
            # Parse items sold and aggregate
            item_stats = defaultdict(lambda: {'qty': 0, 'revenue': 0})
            
            for _, row in sales_df.iterrows():
                items_sold = row['items_sold']
                total_amount = row.get('total_amount', 0) or row.get('subtotal', 0)
                
                if pd.isna(items_sold) or not items_sold:
                    continue
                
                # Parse items
                if isinstance(items_sold, str):
                    if items_sold.startswith('['):
                        import json
                        try:
                            items = json.loads(items_sold)
                        except:
                            items = [i.strip() for i in items_sold.split(';') if i.strip()]
                    else:
                        items = [i.strip() for i in items_sold.split(';') if i.strip()]
                else:
                    items = [str(items_sold)]
                
                # Calculate revenue per item
                revenue_per_item = total_amount / len(items) if items else 0
                
                for item in items:
                    item_stats[item]['qty'] += 1
                    item_stats[item]['revenue'] += revenue_per_item
            
            # Convert to list and sort
            top_items = [
                {
                    "item_name": item,
                    "quantity_sold": stats['qty'],
                    "revenue": round(stats['revenue'], 2)
                }
                for item, stats in item_stats.items()
            ]
            
            top_items.sort(key=lambda x: x['quantity_sold'], reverse=True)
            top_items = top_items[:limit]
            
            return {
                "value": top_items,
                "total_unique_items": len(item_stats),
                "validation_passed": True
            }
        
        except Exception as e:
            raise KPICalculationError(kpi_name, str(e))
    
    # ==================== KPI 7: Gross Profit per Item ====================
    def calculate_gross_profit_per_item(self, sales_df: pd.DataFrame, menu_df: pd.DataFrame) -> Dict[str, Any]:
        """
        KPI 7: Gross Profit per Menu Item
        Formula: gp_per_item = item_price_net - item_cost
        Required: sales[items_sold, total_amount], menu[menu_item, unit_cost, amount]
        """
        kpi_name = "Gross Profit per Item"
        
        required_sales_cols = ['items_sold']
        required_menu_cols = ['menu_item', 'ingredient', 'amount', 'unit_cost']
        
        if not self.check_required_columns(sales_df, required_sales_cols, kpi_name):
            raise KPICalculationError(kpi_name, "Missing sales columns", required_sales_cols)
        
        if not self.check_required_columns(menu_df, required_menu_cols, kpi_name):
            raise KPICalculationError(kpi_name, "Missing menu columns", required_menu_cols)
        
        try:
            # Build menu cost map
            menu_cost_map = {}
            for _, row in menu_df.iterrows():
                menu_item = row['menu_item']
                amount = float(row.get('amount', 0))
                unit_cost = float(row.get('unit_cost', 0))
                
                if menu_item not in menu_cost_map:
                    menu_cost_map[menu_item] = 0
                menu_cost_map[menu_item] += amount * unit_cost
            
            # Calculate profit per item
            item_profits = []
            item_stats = defaultdict(lambda: {'revenue': 0, 'cost': 0, 'qty': 0})
            
            for _, row in sales_df.iterrows():
                items_sold = row['items_sold']
                total_amount = row.get('total_amount', 0) or row.get('subtotal', 0)
                
                if pd.isna(items_sold) or not items_sold:
                    continue
                
                # Parse items
                if isinstance(items_sold, str):
                    if items_sold.startswith('['):
                        import json
                        try:
                            items = json.loads(items_sold)
                        except:
                            items = [i.strip() for i in items_sold.split(';') if i.strip()]
                    else:
                        items = [i.strip() for i in items_sold.split(';') if i.strip()]
                else:
                    items = [str(items_sold)]
                
                revenue_per_item = total_amount / len(items) if items else 0
                
                for item in items:
                    cost = menu_cost_map.get(item, 0)
                    item_stats[item]['revenue'] += revenue_per_item
                    item_stats[item]['cost'] += cost
                    item_stats[item]['qty'] += 1
            
            # Create result list
            for item, stats in item_stats.items():
                profit = stats['revenue'] - stats['cost']
                margin_pct = (profit / stats['revenue'] * 100) if stats['revenue'] > 0 else 0
                
                item_profits.append({
                    "item_name": item,
                    "revenue": round(stats['revenue'], 2),
                    "cost": round(stats['cost'], 2),
                    "gross_profit": round(profit, 2),
                    "margin_percent": round(margin_pct, 2),
                    "quantity_sold": stats['qty']
                })
            
            # Sort by gross profit
            item_profits.sort(key=lambda x: x['gross_profit'], reverse=True)
            
            return {
                "value": item_profits,
                "total_items": len(item_profits),
                "validation_passed": True
            }
        
        except Exception as e:
            raise KPICalculationError(kpi_name, str(e))
    
    # ==================== KPI 8: Food Cost % ====================
    def calculate_food_cost_pct(self, sales_df: pd.DataFrame, menu_df: pd.DataFrame) -> Dict[str, Any]:
        """
        KPI 8: Food Cost % (Actual vs Theoretical)
        Formula: food_cost_pct = actual_food_cost / food_sales
        Required: sales[items_sold, total_amount], menu[menu_item, unit_cost, amount]
        """
        kpi_name = "Food Cost %"
        
        try:
            # Calculate using gross profit calculation
            gp_result = self.calculate_gross_profit_per_item(sales_df, menu_df)
            items = gp_result["value"]
            
            total_revenue = sum(item['revenue'] for item in items)
            total_cost = sum(item['cost'] for item in items)
            
            food_cost_pct = self.safe_divide(total_cost, total_revenue) * 100
            
            # Validation: 0 <= pct <= 100
            validation_passed = food_cost_pct is not None and 0 <= food_cost_pct <= 100
            
            if not validation_passed:
                self.warnings.append({
                    "kpi": kpi_name,
                    "warning": f"Food cost % is out of expected range: {food_cost_pct}"
                })
            
            return {
                "value": round(food_cost_pct, 2) if food_cost_pct is not None else None,
                "total_food_cost": round(total_cost, 2),
                "total_food_sales": round(total_revenue, 2),
                "validation_passed": validation_passed
            }
        
        except Exception as e:
            raise KPICalculationError(kpi_name, str(e))
    
    # ==================== KPI 9: COGS by Category ====================
    def calculate_cogs_by_category(self, sales_df: pd.DataFrame, menu_df: pd.DataFrame) -> Dict[str, Any]:
        """
        KPI 9: COGS by Category
        Formula: cogs_by_cat = SUM(cost) GROUP BY category
        Required: sales[items_sold], menu[menu_item, ingredient, unit_cost, amount]
        """
        kpi_name = "COGS by Category"
        
        try:
            # Build ingredient to menu item mapping
            menu_cost_map = defaultdict(lambda: defaultdict(float))
            
            for _, row in menu_df.iterrows():
                menu_item = row['menu_item']
                ingredient = row['ingredient']
                amount = float(row.get('amount', 0))
                unit_cost = float(row.get('unit_cost', 0))
                
                menu_cost_map[menu_item][ingredient] = amount * unit_cost
            
            # Track ingredient usage from sales
            ingredient_usage = defaultdict(float)
            
            for _, row in sales_df.iterrows():
                items_sold = row['items_sold']
                
                if pd.isna(items_sold) or not items_sold:
                    continue
                
                # Parse items
                if isinstance(items_sold, str):
                    if items_sold.startswith('['):
                        import json
                        try:
                            items = json.loads(items_sold)
                        except:
                            items = [i.strip() for i in items_sold.split(';') if i.strip()]
                    else:
                        items = [i.strip() for i in items_sold.split(';') if i.strip()]
                else:
                    items = [str(items_sold)]
                
                for item in items:
                    if item in menu_cost_map:
                        for ingredient, cost in menu_cost_map[item].items():
                            ingredient_usage[ingredient] += cost
            
            # Create category mapping (simplified - you can customize this)
            cogs_by_category = []
            
            for ingredient, cost in ingredient_usage.items():
                # Categorize ingredients (simplified logic)
                category = "Food"  # Default category
                
                # You can add more sophisticated categorization here
                ingredient_lower = ingredient.lower()
                if any(word in ingredient_lower for word in ['beer', 'wine', 'liquor', 'whiskey', 'vodka']):
                    category = "Alcohol"
                elif any(word in ingredient_lower for word in ['soda', 'juice', 'water', 'coffee', 'tea']):
                    category = "Beverages"
                
                cogs_by_category.append({
                    "ingredient": ingredient,
                    "category": category,
                    "cost": round(cost, 2)
                })
            
            # Aggregate by category
            category_totals = defaultdict(float)
            for item in cogs_by_category:
                category_totals[item['category']] += item['cost']
            
            category_summary = [
                {"category": cat, "total_cogs": round(cost, 2)}
                for cat, cost in category_totals.items()
            ]
            
            return {
                "value": category_summary,
                "detailed": cogs_by_category,
                "total_cogs": round(sum(category_totals.values()), 2),
                "validation_passed": True
            }
        
        except Exception as e:
            raise KPICalculationError(kpi_name, str(e))
    
    # ==================== KPI 10: Inventory Turnover ====================
    def calculate_inventory_turnover(self, sales_df: pd.DataFrame, menu_df: pd.DataFrame, 
                                    inventory_df: pd.DataFrame) -> Dict[str, Any]:
        """
        KPI 10: Inventory Turnover Rate
        Formula: inventory_turn = COGS / AVG(inventory_value)
        Required: sales, menu (for COGS), inventory[quantity, unit_cost]
        """
        kpi_name = "Inventory Turnover Rate"
        
        try:
            # Calculate COGS
            cogs_result = self.calculate_cogs_by_category(sales_df, menu_df)
            total_cogs = cogs_result["total_cogs"]
            
            # Calculate average inventory value
            if not self.check_required_columns(inventory_df, ['quantity', 'unit_cost'], kpi_name):
                raise KPICalculationError(kpi_name, "Missing inventory columns", ['quantity', 'unit_cost'])
            
            inventory_df['value'] = inventory_df['quantity'] * inventory_df['unit_cost']
            avg_inventory_value = inventory_df['value'].mean()
            
            turnover = self.safe_divide(total_cogs, avg_inventory_value)
            
            # Validation: reasonable bounds [0, 100]
            validation_passed = turnover is not None and 0 <= turnover <= 100
            
            if not validation_passed:
                self.warnings.append({
                    "kpi": kpi_name,
                    "warning": f"Inventory turnover out of reasonable range: {turnover}"
                })
            
            return {
                "value": round(turnover, 2) if turnover is not None else None,
                "total_cogs": round(total_cogs, 2),
                "avg_inventory_value": round(avg_inventory_value, 2),
                "validation_passed": validation_passed
            }
        
        except Exception as e:
            raise KPICalculationError(kpi_name, str(e))
    
    # ==================== KPI 11: Low Inventory Warnings ====================
    def calculate_low_inventory_warnings(self, inventory_df: pd.DataFrame) -> Dict[str, Any]:
        """
        KPI 11: Low Inventory Warnings
        Formula: low_inventory = on_hand_qty <= par_level
        """
        kpi_name = "Low Inventory Warnings"
        
        required_cols = ['ingredient', 'quantity', 'par_level']
        if not self.check_required_columns(inventory_df, required_cols, kpi_name):
            raise KPICalculationError(kpi_name, "Missing required columns", required_cols)
        
        try:
            low_items = inventory_df[inventory_df['quantity'] <= inventory_df['par_level']].copy()
            
            warnings = []
            for _, row in low_items.iterrows():
                warnings.append({
                    "ingredient": row['ingredient'],
                    "current_quantity": float(row['quantity']),
                    "par_level": float(row['par_level']),
                    "shortage": float(row['par_level'] - row['quantity'])
                })
            
            return {
                "value": warnings,
                "total_low_items": len(warnings),
                "validation_passed": True
            }
        
        except Exception as e:
            raise KPICalculationError(kpi_name, str(e))
    
    # ==================== KPI 12: Labor Hours by Role ====================
    def calculate_labor_hours_by_role(self, labor_df: pd.DataFrame) -> Dict[str, Any]:
        """
        KPI 12: Labor Hours by Role
        Formula: labor_hours_by_role = SUM(hours) GROUP BY role
        """
        kpi_name = "Labor Hours by Role"
        
        required_cols = ['hours_worked', 'position']
        if not self.check_required_columns(labor_df, required_cols, kpi_name):
            raise KPICalculationError(kpi_name, "Missing required columns", required_cols)
        
        try:
            # Group by role/position
            hours_by_role = labor_df.groupby('position')['hours_worked'].sum().reset_index()
            
            result = []
            for _, row in hours_by_role.iterrows():
                result.append({
                    "role": row['position'],
                    "total_hours": round(float(row['hours_worked']), 2)
                })
            
            result.sort(key=lambda x: x['total_hours'], reverse=True)
            
            return {
                "value": result,
                "total_hours": round(labor_df['hours_worked'].sum(), 2),
                "validation_passed": True
            }
        
        except Exception as e:
            raise KPICalculationError(kpi_name, str(e))
    
    # ==================== KPI 13: Overtime Hours % ====================
    def calculate_overtime_pct(self, labor_df: pd.DataFrame) -> Dict[str, Any]:
        """
        KPI 13: Overtime Hours %
        Formula: overtime_pct = overtime_hours / total_hours
        Required: labor[hours_worked, overtime_hours]
        """
        kpi_name = "Overtime Hours %"
        
        logger.info(f"\n=== Calculating {kpi_name} ===")
        logger.info(f"DataFrame shape: {labor_df.shape}")
        logger.info(f"Available columns: {list(labor_df.columns)}")
        
        # Check for required columns
        required_cols = ['hours_worked']
        if not self.check_required_columns(labor_df, required_cols, kpi_name):
            raise KPICalculationError(kpi_name, "Missing required columns", required_cols)
        
        try:
            # Check if overtime_hours column exists
            if 'overtime_hours' not in labor_df.columns:
                self.warnings.append({
                    "kpi": kpi_name,
                    "warning": "overtime_hours column not found, assuming 0 overtime"
                })
                # Create overtime_hours column with 0 values
                labor_df = labor_df.copy()
                labor_df['overtime_hours'] = 0
            
            # Exclude salaried employees if possible
            if 'is_salaried' in labor_df.columns:
                working_df = labor_df[labor_df['is_salaried'] == False].copy()
                logger.info(f"Excluded salaried employees, {len(working_df)} hourly employees remaining")
            else:
                working_df = labor_df.copy()
                self.warnings.append({
                    "kpi": kpi_name,
                    "warning": "is_salaried column not found, including all employees"
                })
            
            # Calculate totals
            total_hours = float(working_df['hours_worked'].sum())
            total_overtime_hours = float(working_df['overtime_hours'].sum())
            
            # Calculate overall overtime percentage
            overall_overtime_pct = self.safe_divide(total_overtime_hours, total_hours, 0) * 100
            
            # Calculate by role/position
            by_role = []
            if 'position' in working_df.columns:
                role_groups = working_df.groupby('position').agg({
                    'hours_worked': 'sum',
                    'overtime_hours': 'sum'
                }).reset_index()
                
                for _, row in role_groups.iterrows():
                    role_hours = float(row['hours_worked'])
                    role_ot = float(row['overtime_hours'])
                    role_ot_pct = self.safe_divide(role_ot, role_hours, 0) * 100
                    
                    by_role.append({
                        "role": row['position'],
                        "total_hours": round(role_hours, 2),
                        "overtime_hours": round(role_ot, 2),
                        "overtime_pct": round(role_ot_pct, 2)
                    })
                
                # Sort by overtime percentage (highest first)
                by_role.sort(key=lambda x: x['overtime_pct'], reverse=True)
            
            # Validation: overtime should not exceed total hours
            validation_passed = total_overtime_hours <= total_hours
            
            if not validation_passed:
                self.warnings.append({
                    "kpi": kpi_name,
                    "warning": f"Overtime hours ({total_overtime_hours}) exceeds total hours ({total_hours}) - data error"
                })
            
            # Also check if overtime percentage is unreasonably high (>50%)
            if overall_overtime_pct > 50:
                self.warnings.append({
                    "kpi": kpi_name,
                    "warning": f"Overtime percentage is very high: {overall_overtime_pct:.2f}%"
                })
            
            logger.info(f"Overall overtime: {overall_overtime_pct:.2f}%")
            logger.info(f"Total hours: {total_hours}, Overtime hours: {total_overtime_hours}")
            
            return {
                "value": round(overall_overtime_pct, 2),
                "total_hours": round(total_hours, 2),
                "total_overtime_hours": round(total_overtime_hours, 2),
                "by_role": by_role,
                "validation_passed": validation_passed
            }
        
        except Exception as e:
            logger.error(f"Error in {kpi_name}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise KPICalculationError(kpi_name, str(e))
    
    # ==================== KPI 14: Popularity vs Profitability ====================
    def calculate_popularity_vs_profitability(self, sales_df: pd.DataFrame, menu_df: pd.DataFrame) -> Dict[str, Any]:
        """
        KPI 14: Menu Item Popularity vs Profitability
        Formula: popularity = volume_rank; profitability = contribution_margin; quadrant mapping via medians
        Required: sales[items_sold, total_amount], menu[menu_item, ingredient, amount, unit_cost]
        """
        kpi_name = "Menu Item Popularity vs Profitability"
        
        logger.info(f"\n=== Calculating {kpi_name} ===")
        
        try:
            # Use existing Gross Profit per Item calculation (KPI 7)
            gp_result = self.calculate_gross_profit_per_item(sales_df, menu_df)
            items = gp_result["value"]
            
            if not items or len(items) == 0:
                raise KPICalculationError(
                    kpi_name,
                    "No items found - need sales and menu data"
                )
            
            logger.info(f"Processing {len(items)} menu items")
            
            # Extract metrics for median calculation
            quantities = [item['quantity_sold'] for item in items]
            margins = [item['gross_profit'] for item in items]
            
            # Calculate medians (as per Excel formula)
            median_quantity = float(np.median(quantities))
            median_margin = float(np.median(margins))
            
            logger.info(f"Median quantity: {median_quantity}, Median margin: {median_margin}")
            
            # Classify each item into quadrants
            quadrant_counts = {
                "STAR": 0,
                "PLOW HORSE": 0,
                "PUZZLE": 0,
                "DOG": 0
            }
            
            for item in items:
                qty = item['quantity_sold']
                margin = item['gross_profit']
                
                # Quadrant classification based on medians
                if qty >= median_quantity and margin >= median_margin:
                    quadrant = "STAR"
                    recommendation = "Keep & Promote - This is a winning item"
                    
                elif qty >= median_quantity and margin < median_margin:
                    quadrant = "PLOW HORSE"
                    recommendation = "Increase price or reduce cost - Popular but not profitable"
                    
                elif qty < median_quantity and margin >= median_margin:
                    quadrant = "PUZZLE"
                    recommendation = "Promote more - Hidden gem with great margins"
                    
                else:  # qty < median_quantity and margin < median_margin
                    quadrant = "DOG"
                    recommendation = "Consider removing - Low sales and low profit"
                
                item['quadrant'] = quadrant
                item['recommendation'] = recommendation
                
                # Add popularity and profitability ranks
                item['is_high_popularity'] = qty >= median_quantity
                item['is_high_profitability'] = margin >= median_margin
                
                quadrant_counts[quadrant] += 1
            
            # Sort by profitability (highest margin first), then by popularity
            items.sort(key=lambda x: (x['gross_profit'], x['quantity_sold']), reverse=True)
            
            # Add ranks
            for i, item in enumerate(items):
                item['profitability_rank'] = i + 1
            
            # Sort by popularity for popularity rank
            items_by_qty = sorted(items, key=lambda x: x['quantity_sold'], reverse=True)
            for i, item in enumerate(items_by_qty):
                item['popularity_rank'] = i + 1
            
            # Resort by profitability for final output
            items.sort(key=lambda x: x['gross_profit'], reverse=True)
            
            logger.info(f"Quadrant distribution: {quadrant_counts}")
            
            return {
                "value": items,
                "summary": {
                    "total_items": len(items),
                    "stars": quadrant_counts["STAR"],
                    "plow_horses": quadrant_counts["PLOW HORSE"],
                    "puzzles": quadrant_counts["PUZZLE"],
                    "dogs": quadrant_counts["DOG"],
                    "median_quantity": round(median_quantity, 2),
                    "median_profit": round(median_margin, 2)
                },
                "validation_passed": True
            }
        
        except Exception as e:
            logger.error(f"Error in {kpi_name}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise KPICalculationError(kpi_name, str(e))
    
    # ==================== Main Calculate All KPIs ====================
    
    def calculate_all_kpis(self, sales_df: pd.DataFrame, inventory_df: pd.DataFrame, 
                          menu_df: pd.DataFrame, labor_df: pd.DataFrame, 
                          time_period: str = None) -> Dict[str, Any]:
        """
        Calculate all 14 KPIs based on available data
        
        Args:
            sales_df: Sales DataFrame
            inventory_df: Inventory DataFrame
            menu_df: Menu DataFrame
            labor_df: Labor DataFrame
            time_period: Optional time period filter (Last_week, Last_month, etc.)
        
        Returns:
            Dictionary with all KPI results and errors
        """
        
        results = {
            "kpis": {},
            "errors": [],
            "warnings": [],
            "metadata": {
                "calculation_timestamp": datetime.now().isoformat(),
                "time_period": time_period,
                "data_availability": {
                    "sales": not sales_df.empty,
                    "inventory": not inventory_df.empty,
                    "menu": not menu_df.empty,
                    "labor": not labor_df.empty
                },
                "data_row_counts": {
                    "sales": len(sales_df),
                    "inventory": len(inventory_df),
                    "menu": len(menu_df),
                    "labor": len(labor_df)
                }
            }
        }
        
        # Reset errors and warnings
        self.errors = []
        self.warnings = []
        
        # KPI 1: Total Sales
        if not sales_df.empty:
            try:
                results["kpis"]["total_sales"] = self.calculate_total_sales(sales_df)
            except KPICalculationError as e:
                self.errors.append({"kpi": e.kpi_name, "error": str(e), "missing_columns": e.missing_columns})
        
        # KPI 2: Net Revenue
        if not sales_df.empty:
            try:
                results["kpis"]["net_revenue"] = self.calculate_net_revenue(sales_df)
            except KPICalculationError as e:
                self.errors.append({"kpi": e.kpi_name, "error": str(e), "missing_columns": e.missing_columns})
        
        # KPI 3: SPLH
        if not sales_df.empty and not labor_df.empty:
            try:
                results["kpis"]["splh"] = self.calculate_splh(sales_df, labor_df)
            except KPICalculationError as e:
                self.errors.append({"kpi": e.kpi_name, "error": str(e), "missing_columns": e.missing_columns})
        
        # KPI 4: Guest Count
        if not sales_df.empty:
            try:
                results["kpis"]["guest_count"] = self.calculate_guest_count(sales_df)
            except KPICalculationError as e:
                self.errors.append({"kpi": e.kpi_name, "error": str(e), "missing_columns": e.missing_columns})
        
        # KPI 5: Average Check
        if not sales_df.empty:
            try:
                results["kpis"]["avg_check"] = self.calculate_avg_check(sales_df)
            except KPICalculationError as e:
                self.errors.append({"kpi": e.kpi_name, "error": str(e), "missing_columns": e.missing_columns})
        
        # KPI 6: Top Selling Items
        if not sales_df.empty:
            try:
                results["kpis"]["top_items"] = self.calculate_top_items(sales_df)
            except KPICalculationError as e:
                self.errors.append({"kpi": e.kpi_name, "error": str(e), "missing_columns": e.missing_columns})
        
        # KPI 7: Gross Profit per Item
        if not sales_df.empty and not menu_df.empty:
            try:
                results["kpis"]["gross_profit_per_item"] = self.calculate_gross_profit_per_item(sales_df, menu_df)
            except KPICalculationError as e:
                self.errors.append({"kpi": e.kpi_name, "error": str(e), "missing_columns": e.missing_columns})
        
        # KPI 8: Food Cost %
        if not sales_df.empty and not menu_df.empty:
            try:
                results["kpis"]["food_cost_pct"] = self.calculate_food_cost_pct(sales_df, menu_df)
            except KPICalculationError as e:
                self.errors.append({"kpi": e.kpi_name, "error": str(e), "missing_columns": e.missing_columns})
        
        # KPI 9: COGS by Category
        if not sales_df.empty and not menu_df.empty:
            try:
                results["kpis"]["cogs_by_category"] = self.calculate_cogs_by_category(sales_df, menu_df)
            except KPICalculationError as e:
                self.errors.append({"kpi": e.kpi_name, "error": str(e), "missing_columns": e.missing_columns})
        
        # KPI 10: Inventory Turnover
        if not sales_df.empty and not menu_df.empty and not inventory_df.empty:
            try:
                results["kpis"]["inventory_turnover"] = self.calculate_inventory_turnover(sales_df, menu_df, inventory_df)
            except KPICalculationError as e:
                self.errors.append({"kpi": e.kpi_name, "error": str(e), "missing_columns": e.missing_columns})
        
        # KPI 11: Low Inventory Warnings
        if not inventory_df.empty:
            try:
                results["kpis"]["low_inventory_warnings"] = self.calculate_low_inventory_warnings(inventory_df)
            except KPICalculationError as e:
                self.errors.append({"kpi": e.kpi_name, "error": str(e), "missing_columns": e.missing_columns})
        
        # KPI 12: Labor Hours by Role
        if not labor_df.empty:
            try:
                results["kpis"]["labor_hours_by_role"] = self.calculate_labor_hours_by_role(labor_df)
            except KPICalculationError as e:
                self.errors.append({"kpi": e.kpi_name, "error": str(e), "missing_columns": e.missing_columns})
        
        # KPI 13: Overtime Hours %
        if not labor_df.empty:
            try:
                results["kpis"]["overtime_pct"] = self.calculate_overtime_pct(labor_df)
            except KPICalculationError as e:
                self.errors.append({"kpi": e.kpi_name, "error": str(e), "missing_columns": e.missing_columns})
        
        # KPI 14: Popularity vs Profitability
        if not sales_df.empty and not menu_df.empty:
            try:
                results["kpis"]["popularity_vs_profitability"] = self.calculate_popularity_vs_profitability(sales_df, menu_df)
            except KPICalculationError as e:
                self.errors.append({"kpi": e.kpi_name, "error": str(e), "missing_columns": e.missing_columns})
        
        # Add collected errors and warnings
        results["errors"] = self.errors
        results["warnings"] = self.warnings
        
        return results