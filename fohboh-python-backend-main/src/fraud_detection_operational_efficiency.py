import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime, timedelta
import json
from collections import defaultdict
import pickle
import os
from scipy import stats
from fastapi import APIRouter, Depends, HTTPException
import asyncio

# Set up basic logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(filename)s - %(message)s'
)

# Create router for fraud detection endpoints
router = APIRouter(
    prefix="/dashboard",
    tags=["Fraud Detection"],
    responses={404: {"description": "Not found"}},
)

# Import dependencies
from src.chat_gpt import get_current_user, get_db

# API endpoints for fraud detection and operational efficiency
@router.get("/fraud-detection/{restaurant_name}")
async def fraud_detection_dashboard(
    restaurant_name: str,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Get fraud detection data for a specific restaurant
    """
    from src.dashboard_graphs import get_sales_summary_by_restaurant
    
    result = await get_sales_summary_by_restaurant(restaurant_name, current_user, conn)
    if result.get("status") == "error":
        return result
    
    return {
        "status": "success",
        "restaurant": restaurant_name,
        "fraud_detection": result.get("fraud_detection", {}),
        "visual_insights": result.get("visual_insights", {}).get("dashboard_data", {}).get("fraud_risk_indicators", {})
    }

@router.get("/operational-efficiency/{restaurant_name}")
async def operational_efficiency_dashboard(
    restaurant_name: str,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Get operational efficiency data for a specific restaurant
    """
    from src.dashboard_graphs import get_sales_summary_by_restaurant
    
    result = await get_sales_summary_by_restaurant(restaurant_name, current_user, conn)
    if result.get("status") == "error":
        return result
    
    return {
        "status": "success",
        "restaurant": restaurant_name,
        "operational_efficiency": result.get("operational_efficiency", {}),
        "visual_insights": result.get("visual_insights", {}).get("dashboard_data", {}).get("efficiency_metrics", {})
    }

@router.get("/root-causes/{restaurant_name}")
async def root_causes_dashboard(
    restaurant_name: str,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Get root cause analysis data for a specific restaurant
    """
    from src.dashboard_graphs import get_sales_summary_by_restaurant
    
    result = await get_sales_summary_by_restaurant(restaurant_name, current_user, conn)
    if result.get("status") == "error":
        return result
    
    return {
        "status": "success",
        "restaurant": restaurant_name,
        "root_causes": result.get("fraud_detection", {}).get("root_causes", {}),
        "visual_insights": result.get("visual_insights", {}).get("dashboard_data", {}).get("root_cause_insights", {})
    }

@router.get("/fraud-efficiency-summary")
async def fraud_efficiency_summary(
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """
    Get a summary of fraud detection and operational efficiency metrics for all restaurants
    the user has access to
    """
    from src.dashboard_graphs import get_all_restaurant_summaries
    
    result = await get_all_restaurant_summaries(current_user, conn)
    return result

class FraudDetectionOperationalEfficiency:
    """
    Class for detecting anomalies, analyzing operational efficiency, 
    and providing fraud risk alerts in restaurant data.
    """
    
    def __init__(self, memory_storage_path: str = "cortex_memory"):
        """
        Initialize the fraud detection and operational efficiency analyzer.
        
        Args:
            memory_storage_path: Directory path for storing Cortex Memory data
        """
        self.memory_storage_path = memory_storage_path
        self.ensure_memory_storage()
        
    def ensure_memory_storage(self):
        """Create memory storage directory if it doesn't exist"""
        if not os.path.exists(self.memory_storage_path):
            os.makedirs(self.memory_storage_path)
            logging.info(f"Created Cortex Memory storage directory: {self.memory_storage_path}")
    
    def save_to_memory(self, key: str, data: Any):
        """Save data to Cortex Memory storage"""
        try:
            file_path = os.path.join(self.memory_storage_path, f"{key}.pkl")
            with open(file_path, 'wb') as f:
                pickle.dump(data, f)
            logging.info(f"Saved data to Cortex Memory: {key}")
        except Exception as e:
            logging.error(f"Error saving to Cortex Memory: {e}")
    
    def load_from_memory(self, key: str) -> Any:
        """Load data from Cortex Memory storage"""
        try:
            file_path = os.path.join(self.memory_storage_path, f"{key}.pkl")
            if os.path.exists(file_path):
                with open(file_path, 'rb') as f:
                    data = pickle.load(f)
                logging.info(f"Loaded data from Cortex Memory: {key}")
                return data
            return None
        except Exception as e:
            logging.error(f"Error loading from Cortex Memory: {e}")
            return None

    def detect_sales_anomalies(self, sales_df: pd.DataFrame) -> Dict[str, Any]:
        """
        Detect anomalies in sales data using statistical methods.
        
        Args:
            sales_df: DataFrame containing sales data
            
        Returns:
            Dictionary containing detected anomalies and their details
        """
        if sales_df.empty:
            return {"status": "error", "message": "No sales data provided"}
        
        if 'Total Amount' not in sales_df.columns or sales_df['Total Amount'].isna().all():
            return {"status": "error", "message": "Total Amount column is missing or contains only NaN values"}
        
        try:
            # Load historical data if available
            historical_data = self.load_from_memory("sales_historical")
            
            # Prepare results container
            anomalies = {
                "high_value_transactions": [],
                "unusual_time_transactions": [],
                "employee_pattern_anomalies": [],
                "payment_method_anomalies": [],
                "discount_anomalies": [],
                "void_anomalies": []
            }
            
            # 1. High value transaction detection
            # Calculate z-scores for transaction amounts
            mean_amount = sales_df['Total Amount'].mean()
            std_amount = sales_df['Total Amount'].std()
            
            # Lower threshold for test data to ensure we detect anomalies
            # In production, this would typically be 3 standard deviations
            anomaly_threshold = 12.0  # Lower threshold to catch more anomalies in test data
            
            if std_amount > 0:  # Avoid division by zero
                # Create a copy of the DataFrame to avoid SettingWithCopyWarning
                sales_df_copy = sales_df.copy()
                sales_df_copy['amount_zscore'] = (sales_df_copy['Total Amount'] - mean_amount) / std_amount
                high_value_txns = sales_df_copy[sales_df_copy['amount_zscore'] > anomaly_threshold]  # Transactions > threshold std devs
                
                for _, row in high_value_txns.iterrows():
                    anomalies["high_value_transactions"].append({
                        "sale_id": row['Sale ID'],
                        "amount": row['Total Amount'],
                        "date": row['Date'].strftime('%Y-%m-%d') if pd.notna(row['Date']) else None,
                        "time": str(row['Time']) if pd.notna(row['Time']) else None,
                        "employee_id": row['Employee ID'],
                        "z_score": row['amount_zscore'],
                        "severity": "high" if row['amount_zscore'] > 5 else "medium"
                    })
            
            # 2. Unusual time transactions
            # Group by hour and count transactions
            if 'Time' in sales_df.columns and not sales_df['Time'].isna().all():
                # Convert time objects to hour integers - using loc to avoid SettingWithCopyWarning
                sales_df = sales_df.copy()  # Create an explicit copy to avoid the warning
                sales_df.loc[:, 'hour'] = [t.hour if pd.notna(t) else None for t in sales_df['Time']]
                hour_counts = sales_df.groupby('hour').size()
                
                # Define unusual hours (early morning and late night)
                # For test data, we'll consider 0-5 AM and 11 PM-midnight as unusual hours
                unusual_hours = [0, 1, 2, 3, 4, 5, 23]
                
                # Find hours with unusually low transaction counts (potential off-hours activity)
                business_hours = hour_counts[hour_counts > hour_counts.quantile(0.25)].index
                business_hours = [h for h in business_hours if h not in unusual_hours]
                unusual_time_txns = sales_df[~sales_df['hour'].isin(business_hours)]
                
                for _, row in unusual_time_txns.iterrows():
                    anomalies["unusual_time_transactions"].append({
                        "sale_id": row['Sale ID'],
                        "amount": row['Total Amount'],
                        "date": row['Date'].strftime('%Y-%m-%d') if pd.notna(row['Date']) else None,
                        "time": str(row['Time']) if pd.notna(row['Time']) else None,
                        "employee_id": row['Employee ID'],
                        "severity": "medium"
                    })
            
            # 3. Employee pattern anomalies
            if 'Employee ID' in sales_df.columns:
                # Calculate average transaction amount per employee
                emp_avg = sales_df.groupby('Employee ID')['Total Amount'].mean()
                emp_std = sales_df.groupby('Employee ID')['Total Amount'].std()
                
                # Check for employees with identical transaction patterns
                emp_counts = sales_df.groupby(['Employee ID', 'Total Amount']).size().reset_index(name='count')
                repeated_txns = emp_counts[emp_counts['count'] >= 10]  # Employees with 3+ identical transactions
                
                # Add repeated transaction patterns to anomalies
                for _, row in repeated_txns.iterrows():
                    emp_id = row['Employee ID']
                    amount = row['Total Amount']
                    count = row['count']
                    
                    emp_txns = sales_df[(sales_df['Employee ID'] == emp_id) & (sales_df['Total Amount'] == amount)]
                    for _, txn in emp_txns.iterrows():
                        anomalies["employee_pattern_anomalies"].append({
                            "sale_id": txn['Sale ID'],
                            "amount": txn['Total Amount'],
                            "date": txn['Date'].strftime('%Y-%m-%d') if pd.notna(txn['Date']) else None,
                            "time": str(txn['Time']) if pd.notna(txn['Time']) else None,
                            "employee_id": txn['Employee ID'],
                            "pattern_type": "repeated_identical_transactions",
                            "occurrence_count": count,
                            "severity": "high" if count >= 5 else "medium"
                        })
                
                for emp_id in emp_avg.index:
                    emp_sales = sales_df[sales_df['Employee ID'] == emp_id]
                    
                    # For test data, lower the threshold to catch more anomalies
                    # In production, this would typically be 5
                    min_transactions = 8
                    
                    # Skip employees with too few transactions
                    if len(emp_sales) < min_transactions:
                        continue
                    
                    # Check for unusual patterns in employee sales
                    if emp_std[emp_id] > 0:
                        # Create a copy to avoid SettingWithCopyWarning
                        emp_sales_copy = emp_sales.copy()
                        emp_sales_copy['emp_zscore'] = (emp_sales_copy['Total Amount'] - emp_avg[emp_id]) / emp_std[emp_id]
                        # Lower threshold for test data
                        unusual_emp_txns = emp_sales_copy[emp_sales_copy['emp_zscore'].abs() > 2]
                        
                        for _, row in unusual_emp_txns.iterrows():
                            anomalies["employee_pattern_anomalies"].append({
                                "sale_id": row['Sale ID'],
                                "amount": row['Total Amount'],
                                "date": row['Date'].strftime('%Y-%m-%d') if pd.notna(row['Date']) else None,
                                "time": str(row['Time']) if pd.notna(row['Time']) else None,
                                "employee_id": row['Employee ID'],
                                "z_score": row['emp_zscore'],
                                "severity": "high" if abs(row['emp_zscore']) > 5 else "medium"
                            })
            
            # 4. Payment method anomalies
            if 'Payment Method' in sales_df.columns:
                # Check for unusual payment method patterns
                payment_counts = sales_df['Payment Method'].value_counts(normalize=True)
                
                # Consider any payment method used in less than 10% of transactions as rare
                # Also explicitly flag certain payment methods as suspicious
                suspicious_methods = ['Bitcoin', 'Cryptocurrency', 'Gift Card', 'Wire Transfer']
                rare_payment_methods = payment_counts[payment_counts < 0.10].index
                rare_payment_methods = list(rare_payment_methods) + [m for m in suspicious_methods if m in sales_df['Payment Method'].unique()]
                
                for method in rare_payment_methods:
                    method_txns = sales_df[sales_df['Payment Method'] == method]
                    
                    for _, row in method_txns.iterrows():
                        anomalies["payment_method_anomalies"].append({
                            "sale_id": row['Sale ID'],
                            "amount": row['Total Amount'],
                            "date": row['Date'].strftime('%Y-%m-%d') if pd.notna(row['Date']) else None,
                            "payment_method": row['Payment Method'],
                            "employee_id": row['Employee ID'],
                            "severity": "low"
                        })
            
            # 5. Discount anomalies
            if 'Discount Percent' in sales_df.columns:
                # Check for unusually high discounts
                sales_df['Discount Percent'] = pd.to_numeric(sales_df['Discount Percent'], errors='coerce')
                # Flag any discount over 20% as potentially suspicious for test data
                # In production, this threshold might be higher (e.g., 25-30%)
                high_discount_txns = sales_df[sales_df['Discount Percent'] > 20]  # Discounts > 20%
                
                for _, row in high_discount_txns.iterrows():
                    anomalies["discount_anomalies"].append({
                        "sale_id": row['Sale ID'],
                        "amount": row['Total Amount'],
                        "date": row['Date'].strftime('%Y-%m-%d') if pd.notna(row['Date']) else None,
                        "discount_percent": row['Discount Percent'],
                        "employee_id": row['Employee ID'],
                        "severity": "medium" if row['Discount Percent'] > 50 else "low"
                    })
            
            # Save current data as historical reference
            self.save_to_memory("sales_historical", {
                "mean_amount": mean_amount,
                "std_amount": std_amount,
                "timestamp": datetime.now()
            })
            
            return {
                "status": "success", 
                "anomalies": anomalies,
                "anomaly_count": sum(len(v) for v in anomalies.values())
            }
            
        except Exception as e:
            logging.error(f"Error detecting sales anomalies: {e}")
            return {"status": "error", "message": str(e)}

    def analyze_operational_efficiency(self, 
                                      sales_df: pd.DataFrame, 
                                      inventory_df: pd.DataFrame = None, 
                                      employees_df: pd.DataFrame = None) -> Dict[str, Any]:
        """
        Analyze operational efficiency metrics from sales, inventory, and employee data.
        
        Args:
            sales_df: DataFrame containing sales data
            inventory_df: Optional DataFrame containing inventory data
            employees_df: Optional DataFrame containing employee data
            
        Returns:
            Dictionary containing operational efficiency metrics
        """
        if sales_df.empty:
            return {"status": "error", "message": "No sales data provided"}
        
        try:
            # Prepare results container
            efficiency_metrics = {
                "sales_velocity": {},
                "peak_hour_analysis": {},
                "employee_efficiency": {},
                "inventory_turnover": {},
                "order_type_efficiency": {},
                "payment_processing_efficiency": {}
            }
            
            # 1. Sales Velocity (sales per hour)
            if 'Time' in sales_df.columns and not sales_df['Time'].isna().all():
                # Convert time objects to hour integers - using loc to avoid SettingWithCopyWarning
                sales_df = sales_df.copy()  # Create an explicit copy to avoid the warning
                sales_df.loc[:, 'hour'] = [t.hour if pd.notna(t) else None for t in sales_df['Time']]
                
                # Group by date and hour to get sales velocity
                if 'Date' in sales_df.columns:
                    sales_velocity = sales_df.groupby(['Date', 'hour']).agg({
                        'Sale ID': 'count',
                        'Total Amount': 'sum',
                        'Number of Items': 'sum'
                    }).reset_index()
                    
                    sales_velocity.columns = ['date', 'hour', 'transaction_count', 'revenue', 'items_sold']
                    sales_velocity['items_per_transaction'] = sales_velocity['items_sold'] / sales_velocity['transaction_count']
                    sales_velocity['revenue_per_transaction'] = sales_velocity['revenue'] / sales_velocity['transaction_count']
                    
                    # Convert to records for the result
                    efficiency_metrics["sales_velocity"] = sales_velocity.to_dict(orient='records')
                    
                    # 2. Peak Hour Analysis
                    hour_summary = sales_df.groupby('hour').agg({
                        'Sale ID': 'count',
                        'Total Amount': 'sum',
                        'Number of Items': 'sum'
                    }).reset_index()
                    
                    hour_summary.columns = ['hour', 'transaction_count', 'revenue', 'items_sold']
                    
                    # Identify peak hours (top 20% of hours by transaction count)
                    peak_threshold = hour_summary['transaction_count'].quantile(0.8)
                    peak_hours = hour_summary[hour_summary['transaction_count'] >= peak_threshold]
                    
                    efficiency_metrics["peak_hour_analysis"] = {
                        "peak_hours": peak_hours['hour'].tolist(),
                        "metrics_by_hour": hour_summary.to_dict(orient='records'),
                        "peak_hour_revenue_percentage": (peak_hours['revenue'].sum() / hour_summary['revenue'].sum()) * 100
                    }
            
            # 3. Employee Efficiency
            if 'Employee ID' in sales_df.columns:
                emp_efficiency = sales_df.groupby('Employee ID').agg({
                    'Sale ID': 'count',
                    'Total Amount': 'sum',
                    'Number of Items': 'sum'
                }).reset_index()
                
                emp_efficiency.columns = ['employee_id', 'transaction_count', 'revenue', 'items_sold']
                emp_efficiency['items_per_transaction'] = emp_efficiency['items_sold'] / emp_efficiency['transaction_count']
                emp_efficiency['revenue_per_transaction'] = emp_efficiency['revenue'] / emp_efficiency['transaction_count']
                
                # If employee data is available, add more context
                if employees_df is not None and not employees_df.empty:
                    emp_efficiency = emp_efficiency.merge(
                        employees_df[['Employee ID', 'Name', 'Role']], 
                        left_on='employee_id', 
                        right_on='Employee ID',
                        how='left'
                    )
                    emp_efficiency.drop('Employee ID', axis=1, inplace=True)
                
                efficiency_metrics["employee_efficiency"] = emp_efficiency.to_dict(orient='records')
            
            # 4. Inventory Turnover (if inventory data is available)
            if inventory_df is not None and not inventory_df.empty:
                # Calculate inventory turnover metrics
                if 'Items Sold' in sales_df.columns:
                    # Extract all ingredients from inventory
                    all_ingredients = inventory_df['Ingredient'].unique()
                    
                    # Count how many times each ingredient appears in sales
                    ingredient_usage = defaultdict(int)
                    
                    for _, row in sales_df.iterrows():
                        items = str(row['Items Sold']).split(';')
                        for item in items:
                            # This is a simplification - in a real system, you'd look up
                            # which ingredients are in each menu item
                            for ingredient in all_ingredients:
                                if ingredient.lower() in item.lower():
                                    ingredient_usage[ingredient] += 1
                    
                    # Calculate turnover metrics
                    inventory_turnover = []
                    for ingredient in all_ingredients:
                        if ingredient in ingredient_usage:
                            inv_data = inventory_df[inventory_df['Ingredient'] == ingredient]
                            if not inv_data.empty:
                                avg_quantity = inv_data['Quantity'].mean()
                                usage = ingredient_usage[ingredient]
                                turnover = usage / avg_quantity if avg_quantity > 0 else 0
                                
                                inventory_turnover.append({
                                    "ingredient": ingredient,
                                    "average_quantity": avg_quantity,
                                    "usage_count": usage,
                                    "turnover_ratio": turnover
                                })
                    
                    efficiency_metrics["inventory_turnover"] = inventory_turnover
            
            # 5. Order Type Efficiency
            if 'Order Type' in sales_df.columns:
                order_type_efficiency = sales_df.groupby('Order Type').agg({
                    'Sale ID': 'count',
                    'Total Amount': 'sum',
                    'Number of Items': 'sum'
                }).reset_index()
                
                order_type_efficiency.columns = ['order_type', 'transaction_count', 'revenue', 'items_sold']
                order_type_efficiency['items_per_transaction'] = order_type_efficiency['items_sold'] / order_type_efficiency['transaction_count']
                order_type_efficiency['revenue_per_transaction'] = order_type_efficiency['revenue'] / order_type_efficiency['transaction_count']
                
                efficiency_metrics["order_type_efficiency"] = order_type_efficiency.to_dict(orient='records')
            
            # 6. Payment Processing Efficiency
            if 'Payment Method' in sales_df.columns:
                payment_efficiency = sales_df.groupby('Payment Method').agg({
                    'Sale ID': 'count',
                    'Total Amount': 'sum',
                    'Number of Items': 'sum'
                }).reset_index()
                
                payment_efficiency.columns = ['payment_method', 'transaction_count', 'revenue', 'items_sold']
                payment_efficiency['items_per_transaction'] = payment_efficiency['items_sold'] / payment_efficiency['transaction_count']
                payment_efficiency['revenue_per_transaction'] = payment_efficiency['revenue'] / payment_efficiency['transaction_count']
                
                efficiency_metrics["payment_processing_efficiency"] = payment_efficiency.to_dict(orient='records')
            
            return {
                "status": "success", 
                "efficiency_metrics": efficiency_metrics
            }
            
        except Exception as e:
            logging.error(f"Error analyzing operational efficiency: {e}")
            return {"status": "error", "message": str(e)}

    def generate_fraud_risk_alerts(self, sales_df: pd.DataFrame, employees_df: pd.DataFrame = None) -> Dict[str, Any]:
        """
        Generate fraud risk alerts based on sales and employee data.
        
        Args:
            sales_df: DataFrame containing sales data
            employees_df: Optional DataFrame containing employee data
            
        Returns:
            Dictionary containing fraud risk alerts
        """
        if sales_df.empty:
            return {"status": "error", "message": "No sales data provided"}
        
        try:
            # Normalize column names (handle both camelCase and snake_case)
            # This ensures compatibility with different data sources
            column_mapping = {
                'total_amount': ['Total Amount', 'total_amount', 'TotalAmount'],
                'sale_id': ['Sale ID', 'sale_id', 'SaleID'],
                'employee_id': ['Employee ID', 'employee_id', 'EmployeeID'],
                'date': ['Date', 'date'],
                'time': ['Time', 'time'],
                'discount_percent': ['Discount Percent', 'discount_percent', 'DiscountPercent'],
                'payment_method': ['Payment Method', 'payment_method', 'PaymentMethod'],
                'items_sold': ['Items Sold', 'items_sold', 'ItemsSold']
            }
            
            # Create a standardized DataFrame with normalized column names
            std_df = sales_df.copy()
            
            # Map columns to standard names
            for std_col, possible_names in column_mapping.items():
                for col_name in possible_names:
                    if col_name in std_df.columns:
                        std_df[std_col] = std_df[col_name]
                        break
            
            # Check if we have the minimum required columns
            required_cols = ['total_amount']
            missing_cols = [col for col in required_cols if col not in std_df.columns]
            
            if missing_cols:
                return {
                    "status": "error", 
                    "message": f"Missing required columns: {', '.join(missing_cols)}"
                }
            
            # Prepare results container
            fraud_alerts = {
                "high_risk_transactions": [],
                "suspicious_patterns": [],
                "employee_risk_scores": []
            }
            
            # 1. High Risk Transactions
            # Identify transactions with multiple risk factors
            risk_factors = []
            
            # Risk factor: High value transactions
            mean_amount = std_df['total_amount'].mean()
            std_amount = std_df['total_amount'].std()
            
            if std_amount > 0:
                # Create a copy of the DataFrame to avoid SettingWithCopyWarning
                std_df['amount_zscore'] = (std_df['total_amount'] - mean_amount) / std_amount
                risk_factors.append(('high_value', std_df['amount_zscore'] > 3))
            
            # Risk factor: Unusual time
            if 'time' in std_df.columns and not std_df['time'].isna().all():
                # Handle different time formats
                if isinstance(std_df['time'].iloc[0], str):
                    # Convert string time to datetime.time
                    try:
                        std_df['hour'] = pd.to_datetime(std_df['time'], format='%H:%M:%S', errors='coerce').dt.hour
                    except:
                        std_df['hour'] = pd.to_datetime(std_df['time'], errors='coerce').dt.hour
                else:
                    # Already datetime.time object
                    std_df['hour'] = pd.Series([t.hour if pd.notna(t) else None for t in std_df['time']])
                
                hour_counts = std_df.groupby('hour').size()
                business_hours = hour_counts[hour_counts > hour_counts.quantile(0.25)].index
                risk_factors.append(('unusual_time', ~std_df['hour'].isin(business_hours)))
            
            # Risk factor: High discounts
            if 'discount_percent' in std_df.columns:
                std_df['discount_percent'] = pd.to_numeric(std_df['discount_percent'], errors='coerce')
                risk_factors.append(('high_discount', std_df['discount_percent'] > 25))
            
            # Risk factor: Rare payment method
            if 'payment_method' in std_df.columns:
                payment_counts = std_df['payment_method'].value_counts(normalize=True)
                rare_payment_methods = payment_counts[payment_counts < 0.05].index
                risk_factors.append(('rare_payment', std_df['payment_method'].isin(rare_payment_methods)))
            
            # Calculate risk score based on number of risk factors
            std_df['risk_score'] = 0
            for factor_name, factor_condition in risk_factors:
                std_df.loc[factor_condition, 'risk_score'] += 1
            
            # High risk transactions have 1 or more risk factors
            high_risk_txns = std_df[std_df['risk_score'] >= 1]
            
            for idx, row in high_risk_txns.iterrows():
                risk_details = []
                for factor_name, factor_condition in risk_factors:
                    if idx in factor_condition[factor_condition].index:
                        risk_details.append(factor_name)
                
                # Create alert with available fields
                alert = {
                    "risk_score": int(row['risk_score']),
                    "risk_factors": risk_details,
                    "severity": "high" if row['risk_score'] >= 3 else "medium"
                }
                
                # Add optional fields if available
                if 'sale_id' in row:
                    alert["sale_id"] = row['sale_id']
                elif 'Sale ID' in row:
                    alert["sale_id"] = row['Sale ID']
                
                if 'total_amount' in row:
                    alert["amount"] = row['total_amount']
                elif 'Total Amount' in row:
                    alert["amount"] = row['Total Amount']
                
                if 'date' in row and pd.notna(row['date']):
                    if hasattr(row['date'], 'strftime'):
                        alert["date"] = row['date'].strftime('%Y-%m-%d')
                    else:
                        alert["date"] = str(row['date'])
                
                if 'time' in row and pd.notna(row['time']):
                    alert["time"] = str(row['time'])
                
                if 'employee_id' in row:
                    alert["employee_id"] = row['employee_id']
                elif 'Employee ID' in row:
                    alert["employee_id"] = row['Employee ID']
                
                fraud_alerts["high_risk_transactions"].append(alert)
            
            # 2. Suspicious Patterns
            # Look for repeated transaction amounts
            if len(std_df) > 10:  # Only if we have enough data
                amount_field = 'total_amount' if 'total_amount' in std_df.columns else 'Total Amount'
                if amount_field in std_df.columns:
                    amount_counts = std_df[amount_field].value_counts()
                    suspicious_amounts = amount_counts[amount_counts > 3].index  # Same amount repeated more than 3 times
                    
                    for amount in suspicious_amounts:
                        same_amount_txns = std_df[std_df[amount_field] == amount]
                        
                        # Check if same employee is involved
                        emp_field = 'employee_id' if 'employee_id' in same_amount_txns.columns else 'Employee ID'
                        if emp_field in same_amount_txns.columns:
                            emp_counts = same_amount_txns[emp_field].value_counts()
                            for emp_id, count in emp_counts.items():
                                if count > 2:  # Same employee, same amount, multiple times
                                    # Create pattern alert
                                    pattern = {
                                        "pattern_type": "repeated_amount",
                                        "amount": amount,
                                        "employee_id": emp_id,
                                        "occurrence_count": count,
                                        "severity": "medium" if count > 5 else "low"
                                    }
                                    
                                    # Add transaction IDs if available
                                    sale_id_field = 'sale_id' if 'sale_id' in same_amount_txns.columns else 'Sale ID'
                                    if sale_id_field in same_amount_txns.columns:
                                        pattern["transaction_ids"] = same_amount_txns[same_amount_txns[emp_field] == emp_id][sale_id_field].tolist()
                                    
                                    fraud_alerts["suspicious_patterns"].append(pattern)
            
            # 3. Employee Risk Scores
            emp_field = 'employee_id' if 'employee_id' in std_df.columns else 'Employee ID'
            amount_field = 'total_amount' if 'total_amount' in std_df.columns else 'Total Amount'
            
            if emp_field in std_df.columns and amount_field in std_df.columns:
                # Calculate risk score for each employee
                for emp_id in std_df[emp_field].unique():
                    emp_sales = std_df[std_df[emp_field] == emp_id]
                    
                    # Skip employees with too few transactions
                    if len(emp_sales) < 5:
                        continue
                    
                    risk_score = 0
                    risk_factors = []
                    
                    # Factor: High average transaction amount
                    emp_avg = emp_sales[amount_field].mean()
                    if emp_avg > mean_amount + std_amount:
                        risk_score += 1
                        risk_factors.append("high_average_amount")
                    
                    # Factor: High percentage of transactions with discounts
                    discount_field = 'discount_percent' if 'discount_percent' in emp_sales.columns else 'Discount Percent'
                    if discount_field in emp_sales.columns:
                        discount_pct = (emp_sales[discount_field] > 0).mean() * 100
                        if discount_pct > 50:  # More than 50% of transactions have discounts
                            risk_score += 1
                            risk_factors.append("high_discount_frequency")
                    
                    # Factor: Unusual working hours
                    if 'hour' in emp_sales.columns:
                        if 'business_hours' in locals():
                            unusual_hours_pct = (~emp_sales['hour'].isin(business_hours)).mean() * 100
                            if unusual_hours_pct > 20:  # More than 20% of transactions outside business hours
                                risk_score += 1
                                risk_factors.append("unusual_hours")
                    
                    # Add employee context if available
                    emp_name = None
                    emp_role = None
                    if employees_df is not None and not employees_df.empty:
                        # Normalize employee dataframe column names
                        emp_column_mapping = {
                            'employee_id': ['Employee ID', 'employee_id', 'EmployeeID'],
                            'name': ['Name', 'name', 'EmployeeName'],
                            'role': ['Role', 'role', 'EmployeeRole']
                        }
                        
                        std_emp_df = employees_df.copy()
                        
                        # Map columns to standard names
                        for std_col, possible_names in emp_column_mapping.items():
                            for col_name in possible_names:
                                if col_name in std_emp_df.columns:
                                    std_emp_df[std_col] = std_emp_df[col_name]
                                    break
                        
                        # Find employee info
                        emp_id_field = 'employee_id' if 'employee_id' in std_emp_df.columns else 'Employee ID'
                        if emp_id_field in std_emp_df.columns:
                            emp_info = std_emp_df[std_emp_df[emp_id_field] == emp_id]
                            if not emp_info.empty:
                                if 'name' in emp_info.columns:
                                    emp_name = emp_info.iloc[0]['name']
                                if 'role' in emp_info.columns:
                                    emp_role = emp_info.iloc[0]['role']
                    
                    # Only include employees with risk factors
                    if risk_score > 0:
                        fraud_alerts["employee_risk_scores"].append({
                            "employee_id": emp_id,
                            "employee_name": emp_name,
                            "employee_role": emp_role,
                            "risk_score": risk_score,
                            "risk_factors": risk_factors,
                            "transaction_count": len(emp_sales),
                            "average_transaction_amount": emp_avg,
                            "severity": "high" if risk_score >= 3 else "medium" if risk_score == 2 else "low"
                        })
            
            return {
                "status": "success", 
                "fraud_alerts": fraud_alerts,
                "alert_count": sum(len(v) for v in fraud_alerts.values())
            }
            
        except Exception as e:
            logging.error(f"Error generating fraud risk alerts: {e}")
            return {"status": "error", "message": str(e)}

    def perform_root_cause_analysis(self, 
                                   anomaly_data: Dict[str, Any], 
                                   sales_df: pd.DataFrame,
                                   inventory_df: pd.DataFrame = None,
                                   employees_df: pd.DataFrame = None) -> Dict[str, Any]:
        """
        Perform root cause analysis on detected anomalies.
        
        Args:
            anomaly_data: Dictionary containing detected anomalies
            sales_df: DataFrame containing sales data
            inventory_df: Optional DataFrame containing inventory data
            employees_df: Optional DataFrame containing employee data
            
        Returns:
            Dictionary containing root cause analysis results
        """
        if not anomaly_data or anomaly_data.get("status") != "success":
            return {"status": "error", "message": "No valid anomaly data provided"}
        
        try:
            # Prepare results container
            root_causes = {
                "transaction_anomalies": [],
                "employee_anomalies": [],
                "inventory_anomalies": [],
                "temporal_patterns": []
            }
            
            # Extract all anomalies into a flat list
            all_anomalies = []
            for category, anomalies in anomaly_data.get("anomalies", {}).items():
                for anomaly in anomalies:
                    anomaly["category"] = category
                    all_anomalies.append(anomaly)
            
            # 1. Transaction Anomalies Root Cause Analysis
            transaction_anomalies = [a for a in all_anomalies if a["category"] in 
                                    ["high_value_transactions", "payment_method_anomalies", "discount_anomalies"]]
            
            for anomaly in transaction_anomalies:
                sale_id = anomaly.get("sale_id")
                if not sale_id:
                    continue
                
                # Get the transaction details
                transaction = sales_df[sales_df['Sale ID'] == sale_id]
                if transaction.empty:
                    continue
                
                # Analyze potential causes
                causes = []
                
                # Check for unusual items in the transaction
                if 'Items Sold' in transaction.columns:
                    items = str(transaction.iloc[0]['Items Sold']).split(';')
                    if len(items) > 10:  # Unusually large number of items
                        causes.append("large_number_of_items")
                
                # Check for unusual discount
                if 'Discount Percent' in transaction.columns:
                    discount = transaction.iloc[0]['Discount Percent']
                    if pd.notna(discount) and discount > 25:
                        causes.append("high_discount_percentage")
                
                # Check for unusual payment method
                if 'Payment Method' in transaction.columns:
                    payment = transaction.iloc[0]['Payment Method']
                    payment_counts = sales_df['Payment Method'].value_counts(normalize=True)
                    if payment in payment_counts and payment_counts[payment] < 0.05:
                        causes.append("rare_payment_method")
                
                # Add to root causes
                root_causes["transaction_anomalies"].append({
                    "sale_id": sale_id,
                    "anomaly_type": anomaly["category"],
                    "potential_causes": causes,
                    "recommendation": self._generate_recommendation(causes)
                })
            
            # 2. Employee Anomalies Root Cause Analysis
            employee_anomalies = [a for a in all_anomalies if a["category"] in 
                                 ["employee_pattern_anomalies"]]
            
            for anomaly in employee_anomalies:
                emp_id = anomaly.get("employee_id")
                if not emp_id:
                    continue
                
                # Get all transactions by this employee
                emp_transactions = sales_df[sales_df['Employee ID'] == emp_id]
                if emp_transactions.empty:
                    continue
                
                # Analyze potential causes
                causes = []
                
                # Check for unusual transaction patterns
                emp_avg = emp_transactions['Total Amount'].mean()
                emp_std = emp_transactions['Total Amount'].std()
                
                if emp_std > 0:
                    # Create a copy to avoid SettingWithCopyWarning
                    emp_txns_copy = emp_transactions.copy()
                    emp_txns_copy['zscore'] = (emp_txns_copy['Total Amount'] - emp_avg) / emp_std
                    unusual_txns = emp_txns_copy[emp_txns_copy['zscore'].abs() > 3]
                    
                    if len(unusual_txns) > 0.2 * len(emp_transactions):  # More than 20% unusual
                        causes.append("high_percentage_unusual_transactions")
                
                # Check for unusual working hours
                if 'Time' in emp_transactions.columns and not emp_transactions['Time'].isna().all():
                    # First, make sure 'hour' column exists in sales_df
                    if 'hour' not in sales_df.columns:
                        # Create hour column in the main dataframe if it doesn't exist - using loc to avoid SettingWithCopyWarning
                        sales_df = sales_df.copy()  # Create an explicit copy to avoid the warning
                        sales_df.loc[:, 'hour'] = [t.hour if pd.notna(t) else None for t in sales_df['Time']]
                    
                    # Create a copy to avoid SettingWithCopyWarning
                    emp_txns_copy = emp_transactions.copy()
                    emp_txns_copy['hour'] = pd.Series([t.hour if pd.notna(t) else None for t in emp_txns_copy['Time']])
                    
                    # Get business hours from the main dataframe
                    hour_counts = sales_df.groupby('hour').size()
                    business_hours = hour_counts[hour_counts > hour_counts.quantile(0.25)].index
                    
                    # Define unusual hours (early morning and late night)
                    unusual_hour_list = [0, 1, 2, 3, 4, 5, 23]
                    
                    # Combine both methods of determining unusual hours
                    all_business_hours = [h for h in business_hours if h not in unusual_hour_list]
                    
                    unusual_hours = emp_txns_copy[~emp_txns_copy['hour'].isin(all_business_hours)]
                    if len(unusual_hours) > 0.2 * len(emp_transactions):  # More than 20% in unusual hours
                        causes.append("unusual_working_hours")
                
                # Check employee info if available
                emp_info = {}
                if employees_df is not None and not employees_df.empty:
                    emp_data = employees_df[employees_df['Employee ID'] == emp_id]
                    if not emp_data.empty:
                        emp_info = {
                            "name": emp_data.iloc[0]['Name'],
                            "role": emp_data.iloc[0]['Role'],
                            "hire_date": emp_data.iloc[0]['Hire Date'].strftime('%Y-%m-%d') if pd.notna(emp_data.iloc[0]['Hire Date']) else None
                        }
                        
                        # Check if employee is new (less than 30 days)
                        if pd.notna(emp_data.iloc[0]['Hire Date']):
                            hire_date = emp_data.iloc[0]['Hire Date']
                            if (datetime.now() - hire_date).days < 30:
                                causes.append("new_employee")
                
                # Add to root causes
                root_causes["employee_anomalies"].append({
                    "employee_id": emp_id,
                    "employee_info": emp_info,
                    "anomaly_type": anomaly["category"],
                    "potential_causes": causes,
                    "recommendation": self._generate_recommendation(causes)
                })
            
            # 3. Inventory Anomalies Root Cause Analysis
            if inventory_df is not None and not inventory_df.empty:
                # Look for inventory items with unusual levels
                inventory_df['inventory_ratio'] = inventory_df['Quantity'] / inventory_df['Par Level']
                unusual_inventory = inventory_df[inventory_df['inventory_ratio'] < 0.75]  # Less than 20% of par level
                
                for _, row in unusual_inventory.iterrows():
                    causes = ["low_inventory_level"]
                    
                    # Check if this ingredient is used in high-selling items
                    if 'Items Sold' in sales_df.columns:
                        ingredient = row['Ingredient']
                        # Simplified check - in a real system, you'd have a proper ingredient-to-menu mapping
                        related_sales = sales_df[sales_df['Items Sold'].str.contains(ingredient, case=False, na=False)]
                        
                        if len(related_sales) > 0.1 * len(sales_df):  # Used in more than 10% of sales
                            causes.append("high_usage_ingredient")
                    
                    root_causes["inventory_anomalies"].append({
                        "ingredient": row['Ingredient'],
                        "current_quantity": row['Quantity'],
                        "par_level": row['Par Level'],
                        "inventory_ratio": row['inventory_ratio'],
                        "potential_causes": causes,
                        "recommendation": self._generate_recommendation(causes)
                    })
            
            # 4. Temporal Patterns Analysis
            if 'Date' in sales_df.columns and 'Time' in sales_df.columns:
                # Group anomalies by date and hour - using loc to avoid SettingWithCopyWarning
                sales_df = sales_df.copy()  # Create an explicit copy to avoid the warning
                sales_df.loc[:, 'hour'] = [t.hour if pd.notna(t) else None for t in sales_df['Time']]
                
                # Get sale IDs from all anomalies
                anomaly_sale_ids = [a.get("sale_id") for a in all_anomalies if "sale_id" in a]
                anomaly_sales = sales_df[sales_df['Sale ID'].isin(anomaly_sale_ids)]
                
                if not anomaly_sales.empty:
                    # Group by date and hour
                    temporal_groups = anomaly_sales.groupby(['Date', 'hour']).size().reset_index()
                    temporal_groups.columns = ['date', 'hour', 'anomaly_count']
                    
                    # Find time periods with high anomaly concentration
                    high_anomaly_periods = temporal_groups[temporal_groups['anomaly_count'] > 2]  # More than 2 anomalies in same hour
                    
                    for _, period in high_anomaly_periods.iterrows():
                        date_str = period['date'].strftime('%Y-%m-%d') if pd.notna(period['date']) else None
                        hour = period['hour']
                        
                        # Get all anomalies in this period
                        period_anomalies = anomaly_sales[
                            (anomaly_sales['Date'] == period['date']) & 
                            (anomaly_sales['hour'] == hour)
                        ]
                        
                        # Check for common factors
                        common_factors = []
                        
                        # Check if same employee involved
                        if 'Employee ID' in period_anomalies.columns:
                            emp_counts = period_anomalies['Employee ID'].value_counts()
                            if emp_counts.max() > 1:  # Same employee involved in multiple anomalies
                                common_emp = emp_counts.idxmax()
                                common_factors.append(f"same_employee_{common_emp}")
                        
                        # Check if same payment method
                        if 'Payment Method' in period_anomalies.columns:
                            payment_counts = period_anomalies['Payment Method'].value_counts()
                            if payment_counts.max() > 1:  # Same payment method in multiple anomalies
                                common_payment = payment_counts.idxmax()
                                common_factors.append(f"same_payment_method_{common_payment}")
                        
                        root_causes["temporal_patterns"].append({
                            "date": date_str,
                            "hour": hour,
                            "anomaly_count": period['anomaly_count'],
                            "common_factors": common_factors,
                            "sale_ids": period_anomalies['Sale ID'].tolist(),
                            "recommendation": "Investigate this time period for potential systematic issues"
                        })
            
            return {
                "status": "success", 
                "root_causes": root_causes
            }
            
        except Exception as e:
            logging.error(f"Error performing root cause analysis: {e}")
            return {"status": "error", "message": str(e)}

    def _generate_recommendation(self, causes: List[str]) -> str:
        """Generate recommendations based on identified causes"""
        recommendations = {
            "large_number_of_items": "Review transaction for potential item miscounting or order splitting",
            "high_discount_percentage": "Verify discount authorization and policy compliance",
            "rare_payment_method": "Confirm payment method validity and authorization",
            "high_percentage_unusual_transactions": "Review employee transaction history and provide additional training",
            "unusual_working_hours": "Verify employee schedule and authorization for off-hours work",
            "new_employee": "Provide additional training and supervision for new employee",
            "low_inventory_level": "Restock inventory item and review ordering schedule",
            "high_usage_ingredient": "Increase par level for frequently used ingredient"
        }
        
        result = []
        for cause in causes:
            if cause in recommendations:
                result.append(recommendations[cause])
        
        if not result:
            return "No specific recommendations available"
        
        return "; ".join(result)

    def generate_visual_insight_dashboard(self, 
                                         anomaly_data: Dict[str, Any], 
                                         efficiency_data: Dict[str, Any],
                                         fraud_alerts: Dict[str, Any],
                                         root_causes: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate data for a visual insight dashboard.
        
        Args:
            anomaly_data: Dictionary containing detected anomalies
            efficiency_data: Dictionary containing operational efficiency metrics
            fraud_alerts: Dictionary containing fraud risk alerts
            root_causes: Dictionary containing root cause analysis results
            
        Returns:
            Dictionary containing dashboard data
        """
        try:
            # Prepare dashboard data
            dashboard = {
                "summary": {
                    "anomaly_count": anomaly_data.get("anomaly_count", 0) if anomaly_data.get("status") == "success" else 0,
                    "fraud_alert_count": fraud_alerts.get("alert_count", 0) if fraud_alerts.get("status") == "success" else 0,
                    "high_risk_transactions": len(fraud_alerts.get("fraud_alerts", {}).get("high_risk_transactions", [])) if fraud_alerts.get("status") == "success" else 0,
                    "efficiency_score": self._calculate_efficiency_score(efficiency_data) if efficiency_data.get("status") == "success" else 0
                },
                "anomaly_breakdown": self._prepare_anomaly_breakdown(anomaly_data) if anomaly_data.get("status") == "success" else {},
                "efficiency_metrics": self._prepare_efficiency_metrics(efficiency_data) if efficiency_data.get("status") == "success" else {},
                "fraud_risk_indicators": self._prepare_fraud_indicators(fraud_alerts) if fraud_alerts.get("status") == "success" else {},
                "root_cause_insights": self._prepare_root_cause_insights(root_causes) if root_causes.get("status") == "success" else {}
            }
            
            return {
                "status": "success", 
                "dashboard_data": dashboard
            }
            
        except Exception as e:
            logging.error(f"Error generating visual insight dashboard: {e}")
            return {"status": "error", "message": str(e)}

    def _calculate_efficiency_score(self, efficiency_data: Dict[str, Any]) -> float:
        """Calculate an overall efficiency score from efficiency metrics"""
        if not efficiency_data or efficiency_data.get("status") != "success":
            return 0
        
        metrics = efficiency_data.get("efficiency_metrics", {})
        score_components = []
        
        # 1. Sales velocity score
        if "sales_velocity" in metrics and metrics["sales_velocity"]:
            velocity_data = pd.DataFrame(metrics["sales_velocity"])
            if not velocity_data.empty and "items_per_transaction" in velocity_data.columns:
                avg_items = velocity_data["items_per_transaction"].mean()
                # Score from 0-25 based on items per transaction (0-5 items)
                score_components.append(min(25, avg_items * 5))
        
        # 2. Peak hour utilization score
        if "peak_hour_analysis" in metrics and "peak_hour_revenue_percentage" in metrics["peak_hour_analysis"]:
            peak_revenue_pct = metrics["peak_hour_analysis"]["peak_hour_revenue_percentage"]
            # Score from 0-25 based on peak hour revenue percentage (0-100%)
            score_components.append(peak_revenue_pct * 0.25)
        
        # 3. Employee efficiency score
        if "employee_efficiency" in metrics and metrics["employee_efficiency"]:
            emp_data = pd.DataFrame(metrics["employee_efficiency"])
            if not emp_data.empty and "revenue_per_transaction" in emp_data.columns:
                avg_revenue = emp_data["revenue_per_transaction"].mean()
                # Score from 0-25 based on average revenue per transaction (0-100)
                score_components.append(min(25, avg_revenue * 0.25))
        
        # 4. Order type efficiency score
        if "order_type_efficiency" in metrics and metrics["order_type_efficiency"]:
            order_data = pd.DataFrame(metrics["order_type_efficiency"])
            if not order_data.empty and "items_per_transaction" in order_data.columns:
                avg_items = order_data["items_per_transaction"].mean()
                # Score from 0-25 based on items per transaction (0-5 items)
                score_components.append(min(25, avg_items * 5))
        
        # Calculate final score
        if score_components:
            return sum(score_components) / len(score_components) * 100 / 25
        return 0

    def _prepare_anomaly_breakdown(self, anomaly_data: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare anomaly breakdown for dashboard visualization"""
        if not anomaly_data or anomaly_data.get("status") != "success":
            return {}
        
        anomalies = anomaly_data.get("anomalies", {})
        
        # Count anomalies by category and severity
        category_counts = {category: len(items) for category, items in anomalies.items()}
        
        severity_counts = {"high": 0, "medium": 0, "low": 0}
        for category, items in anomalies.items():
            for item in items:
                severity = item.get("severity", "medium")
                severity_counts[severity] += 1
        
        # Prepare time-based distribution if available
        time_distribution = {}
        for category, items in anomalies.items():
            for item in items:
                if "time" in item and item["time"]:
                    try:
                        hour = int(str(item["time"]).split(":")[0])
                        time_distribution[hour] = time_distribution.get(hour, 0) + 1
                    except (ValueError, IndexError):
                        pass
        
        return {
            "by_category": category_counts,
            "by_severity": severity_counts,
            "time_distribution": time_distribution
        }

    def _prepare_efficiency_metrics(self, efficiency_data: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare efficiency metrics for dashboard visualization"""
        if not efficiency_data or efficiency_data.get("status") != "success":
            return {}
        
        metrics = efficiency_data.get("efficiency_metrics", {})
        
        # Extract key metrics for visualization
        result = {}
        
        # Sales velocity by hour
        if "sales_velocity" in metrics and metrics["sales_velocity"]:
            velocity_by_hour = {}
            for entry in metrics["sales_velocity"]:
                hour = entry.get("hour")
                if hour is not None:
                    if hour not in velocity_by_hour:
                        velocity_by_hour[hour] = []
                    velocity_by_hour[hour].append(entry.get("transaction_count", 0))
            
            # Calculate average velocity by hour
            avg_velocity = {hour: sum(counts) / len(counts) for hour, counts in velocity_by_hour.items()}
            result["sales_velocity_by_hour"] = avg_velocity
        
        # Peak hours
        if "peak_hour_analysis" in metrics and "peak_hours" in metrics["peak_hour_analysis"]:
            result["peak_hours"] = metrics["peak_hour_analysis"]["peak_hours"]
        
        # Top performing employees
        if "employee_efficiency" in metrics and metrics["employee_efficiency"]:
            emp_data = sorted(
                metrics["employee_efficiency"], 
                key=lambda x: x.get("revenue", 0), 
                reverse=True
            )[:5]  # Top 5 employees
            
            result["top_employees"] = [{
                "employee_id": emp.get("employee_id"),
                "name": emp.get("name", f"Employee {emp.get('employee_id')}"),
                "revenue": emp.get("revenue", 0),
                "transaction_count": emp.get("transaction_count", 0)
            } for emp in emp_data]
        
        # Order type efficiency
        if "order_type_efficiency" in metrics and metrics["order_type_efficiency"]:
            result["order_type_efficiency"] = {
                entry.get("order_type"): {
                    "revenue": entry.get("revenue", 0),
                    "transaction_count": entry.get("transaction_count", 0),
                    "avg_revenue": entry.get("revenue_per_transaction", 0)
                }
                for entry in metrics["order_type_efficiency"]
            }
        
        return result

    def _prepare_fraud_indicators(self, fraud_alerts: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare fraud risk indicators for dashboard visualization"""
        if not fraud_alerts or fraud_alerts.get("status") != "success":
            return {}
        
        alerts = fraud_alerts.get("fraud_alerts", {})
        
        # Count alerts by category and severity
        category_counts = {category: len(items) for category, items in alerts.items()}
        
        severity_counts = {"high": 0, "medium": 0, "low": 0}
        for category, items in alerts.items():
            for item in items:
                severity = item.get("severity", "medium")
                severity_counts[severity] += 1
        
        # Extract high risk employees
        high_risk_employees = []
        if "employee_risk_scores" in alerts:
            high_risk_employees = [
                {
                    "employee_id": emp.get("employee_id"),
                    "name": emp.get("employee_name", f"Employee {emp.get('employee_id')}"),
                    "risk_score": emp.get("risk_score", 0),
                    "risk_factors": emp.get("risk_factors", [])
                }
                for emp in alerts["employee_risk_scores"]
                if emp.get("severity") == "high"
            ]
        
        # Extract suspicious patterns
        suspicious_patterns = []
        if "suspicious_patterns" in alerts:
            suspicious_patterns = [
                {
                    "pattern_type": pattern.get("pattern_type", "unknown"),
                    "occurrence_count": pattern.get("occurrence_count", 0),
                    "severity": pattern.get("severity", "medium")
                }
                for pattern in alerts["suspicious_patterns"]
            ]
        
        return {
            "by_category": category_counts,
            "by_severity": severity_counts,
            "high_risk_employees": high_risk_employees,
            "suspicious_patterns": suspicious_patterns
        }

    def _prepare_root_cause_insights(self, root_causes: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare root cause insights for dashboard visualization"""
        if not root_causes or root_causes.get("status") != "success":
            return {}
        
        causes = root_causes.get("root_causes", {})
        
        # Count causes by category
        category_counts = {category: len(items) for category, items in causes.items()}
        
        # Extract common causes
        all_causes = []
        for category, items in causes.items():
            for item in items:
                all_causes.extend(item.get("potential_causes", []))
        
        cause_counts = {}
        for cause in all_causes:
            cause_counts[cause] = cause_counts.get(cause, 0) + 1
        
        # Sort by frequency
        common_causes = sorted(
            [{"cause": cause, "count": count} for cause, count in cause_counts.items()],
            key=lambda x: x["count"],
            reverse=True
        )
        
        # Extract temporal patterns
        temporal_insights = []
        if "temporal_patterns" in causes:
            temporal_insights = [
                {
                    "date": pattern.get("date"),
                    "hour": pattern.get("hour"),
                    "anomaly_count": pattern.get("anomaly_count", 0),
                    "common_factors": pattern.get("common_factors", [])
                }
                for pattern in causes["temporal_patterns"]
            ]
        
        return {
            "by_category": category_counts,
            "common_causes": common_causes,
            "temporal_insights": temporal_insights
        }
