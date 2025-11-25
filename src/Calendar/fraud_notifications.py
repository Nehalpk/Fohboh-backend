import logging
from typing import Dict, List, Any, Optional
import asyncio
from datetime import datetime

# Set up basic logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(filename)s - %(message)s'
)

async def create_fraud_detection_notifications(
    user_id: int,
    restaurant_id: int,
    restaurant_name: str,
    anomaly_data: Dict[str, Any],
    fraud_alerts: Dict[str, Any],
    root_causes: Dict[str, Any],
    conn
):
    """
    Create notifications for fraud detection alerts, anomalies, and root causes.
    
    Args:
        user_id: The ID of the user to notify
        restaurant_id: The ID of the restaurant
        restaurant_name: The name of the restaurant
        anomaly_data: Dictionary containing detected anomalies
        fraud_alerts: Dictionary containing fraud risk alerts
        root_causes: Dictionary containing root cause analysis results
        conn: Database connection
    
    Returns:
        List of created notification IDs
    """
    from src.chat_gpt import create_notification
    
    notification_ids = []
    
    try:
        # Process anomalies
        if anomaly_data and anomaly_data.get("status") == "success":
            anomalies = anomaly_data.get("anomalies", {})
            
            # High value transaction anomalies
            high_value_txns = anomalies.get("high_value_transactions", [])
            if high_value_txns:
                # Group by severity
                high_severity = [t for t in high_value_txns if t.get("severity") == "high"]
                medium_severity = [t for t in high_value_txns if t.get("severity") == "medium"]
                
                if high_severity:
                    # Create a detailed message with transaction information
                    details = "\n\nDetails of high-value transactions:\n"
                    for i, txn in enumerate(high_severity[:5]):  # Show first 5 transactions
                        details += f"• Transaction #{txn.get('sale_id')}: ${txn.get('amount', 0):.2f} "
                        details += f"({txn.get('date', '')} {txn.get('time', '')})\n"
                    
                    if len(high_severity) > 5:
                        details += f"... and {len(high_severity) - 5} more transactions\n"
                    
                    details += "\nRecommendation: Review these transactions immediately for potential fraud."
                    
                    notification = await create_notification(
                        user_id=user_id,
                        title=f"🚨 High Value Transaction Alert - {restaurant_name}",
                        message=f"Detected {len(high_severity)} unusually high value transactions that require immediate review." + details,
                        type="alert",
                        cat = "fraud",
                        restaurant_id=restaurant_id,
                        conn=conn
                    )
                    notification_ids.append(notification["id"])
                
                if medium_severity:
                    # Create a detailed message with transaction information
                    details = "\n\nDetails of unusual transactions:\n"
                    for i, txn in enumerate(medium_severity[:5]):  # Show first 5 transactions
                        details += f"• Transaction #{txn.get('sale_id')}: ${txn.get('amount', 0):.2f} "
                        details += f"({txn.get('date', '')} {txn.get('time', '')})\n"
                    
                    if len(medium_severity) > 5:
                        details += f"... and {len(medium_severity) - 5} more transactions\n"
                    
                    details += "\nRecommendation: Review these transactions for potential issues."
                    
                    notification = await create_notification(
                        user_id=user_id,
                        title=f"⚠️ Unusual Transaction Alert - {restaurant_name}",
                        message=f"Detected {len(medium_severity)} transactions with values above normal range." + details,
                        type="warning",
                        cat = "fraud",
                        restaurant_id=restaurant_id,
                        conn=conn
                    )
                    notification_ids.append(notification["id"])
            
            # Unusual time transactions
            unusual_time_txns = anomalies.get("unusual_time_transactions", [])
            if unusual_time_txns:
                # Group transactions by hour
                hour_groups = {}
                for txn in unusual_time_txns:
                    time_str = txn.get('time', '')
                    hour = time_str.split(':')[0] if time_str and ':' in time_str else 'Unknown'
                    if hour not in hour_groups:
                        hour_groups[hour] = []
                    hour_groups[hour].append(txn)
                
                # Create a detailed message with transaction information
                details = "\n\nDetails of off-hours transactions:\n"
                for hour, txns in sorted(hour_groups.items()):
                    details += f"• {hour}:00 hour: {len(txns)} transactions\n"
                
                details += "\nSpecific transactions:\n"
                for i, txn in enumerate(unusual_time_txns[:5]):  # Show first 5 transactions
                    details += f"• Transaction #{txn.get('sale_id')}: ${txn.get('amount', 0):.2f} "
                    details += f"at {txn.get('time', '')} by Employee #{txn.get('employee_id', 'Unknown')}\n"
                
                if len(unusual_time_txns) > 5:
                    details += f"... and {len(unusual_time_txns) - 5} more transactions\n"
                
                details += "\nRecommendation: Verify if these transactions were authorized and review your business hours settings."
                
                notification = await create_notification(
                    user_id=user_id,
                    title=f"🕒 Off-Hours Activity - {restaurant_name}",
                    message=f"Detected {len(unusual_time_txns)} transactions outside normal business hours." + details,
                    type="warning",
                    cat = "fraud",
                    restaurant_id=restaurant_id,
                    conn=conn
                )
                notification_ids.append(notification["id"])
            
            # Payment method anomalies
            payment_anomalies = anomalies.get("payment_method_anomalies", [])
            if payment_anomalies:
                # Group by payment method
                payment_groups = {}
                for anomaly in payment_anomalies:
                    payment = anomaly.get("payment_method", "Unknown")
                    if payment not in payment_groups:
                        payment_groups[payment] = []
                    payment_groups[payment].append(anomaly)
                
                details = "\n\nUnusual payment methods detected:\n"
                for payment, txns in payment_groups.items():
                    details += f"• {payment}: {len(txns)} transactions\n"
                
                details += "\nRecommendation: Review these payment methods for potential fraud risks."
                
                notification = await create_notification(
                    user_id=user_id,
                    title=f"💳 Unusual Payment Methods - {restaurant_name}",
                    message=f"Detected {len(payment_anomalies)} transactions with unusual payment methods." + details,
                    type="warning",
                    cat = "fraud",
                    restaurant_id=restaurant_id,
                    conn=conn
                )
                notification_ids.append(notification["id"])
            
            # Discount anomalies
            discount_anomalies = anomalies.get("discount_anomalies", [])
            if discount_anomalies:
                details = "\n\nHigh discount transactions:\n"
                for i, txn in enumerate(discount_anomalies[:5]):
                    details += f"• Transaction #{txn.get('sale_id')}: {txn.get('discount_percent', 0)}% discount "
                    details += f"on ${txn.get('amount', 0):.2f} by Employee #{txn.get('employee_id', 'Unknown')}\n"
                
                if len(discount_anomalies) > 5:
                    details += f"... and {len(discount_anomalies) - 5} more transactions\n"
                
                details += "\nRecommendation: Review discount authorization policies and employee discount privileges."
                
                notification = await create_notification(
                    user_id=user_id,
                    title=f"🏷️ High Discount Alert - {restaurant_name}",
                    message=f"Detected {len(discount_anomalies)} transactions with unusually high discounts." + details,
                    type="warning",
                    cat = "fraud",
                    restaurant_id=restaurant_id,
                    conn=conn
                )
                notification_ids.append(notification["id"])
            
            # Employee pattern anomalies
            employee_anomalies = anomalies.get("employee_pattern_anomalies", [])
            if employee_anomalies:
                # Group by employee
                emp_anomalies = {}
                for anomaly in employee_anomalies:
                    emp_id = anomaly.get("employee_id")
                    if emp_id not in emp_anomalies:
                        emp_anomalies[emp_id] = []
                    emp_anomalies[emp_id].append(anomaly)
                
                # Create notification for each employee with multiple anomalies
                for emp_id, anomalies in emp_anomalies.items():
                    if len(anomalies) >= 5:  # Only notify if multiple anomalies
                        details = f"\n\nEmployee #{emp_id} has the following unusual patterns:\n"
                        
                        # Group by pattern type
                        pattern_types = {}
                        for anomaly in anomalies:
                            pattern_type = anomaly.get("pattern_type", "unusual_transaction")
                            if pattern_type not in pattern_types:
                                pattern_types[pattern_type] = []
                            pattern_types[pattern_type].append(anomaly)
                        
                        for pattern, pattern_anomalies in pattern_types.items():
                            details += f"• {pattern.replace('_', ' ').title()}: {len(pattern_anomalies)} instances\n"
                        
                        details += "\nSample transactions:\n"
                        for i, anomaly in enumerate(anomalies[:3]):
                            details += f"• Transaction #{anomaly.get('sale_id')}: ${anomaly.get('amount', 0):.2f} "
                            details += f"({anomaly.get('date', '')} {anomaly.get('time', '')})\n"
                        
                        details += "\nRecommendation: Review this employee's transaction history and consider additional training or supervision."
                        
                        notification = await create_notification(
                            user_id=user_id,
                            title=f"👤 Employee Transaction Pattern Alert - {restaurant_name}",
                            message=f"Employee ID {emp_id} has {len(anomalies)} unusual transaction patterns that require review." + details,
                            type="alert",
                            cat = "fraud",
                            restaurant_id=restaurant_id,
                            conn=conn
                        )
                        notification_ids.append(notification["id"])
        
        # Process fraud alerts
        if fraud_alerts and fraud_alerts.get("status") == "success":
            alerts = fraud_alerts.get("fraud_alerts", {})
            
            # High risk transactions
            high_risk_txns = alerts.get("high_risk_transactions", [])
            if high_risk_txns:
                high_severity = [t for t in high_risk_txns if t.get("severity") == "high"]
                if high_severity:
                    details = "\n\nHigh risk transactions detected:\n"
                    
                    for i, txn in enumerate(high_severity[:5]):
                        details += f"• Transaction #{txn.get('sale_id')}: ${txn.get('amount', 0):.2f} "
                        details += f"with risk factors: {', '.join(txn.get('risk_factors', []))}\n"
                    
                    if len(high_severity) > 5:
                        details += f"... and {len(high_severity) - 5} more transactions\n"
                    
                    details += "\nRecommendation: These transactions show multiple fraud indicators and should be investigated immediately."
                    
                    notification = await create_notification(
                        user_id=user_id,
                        title=f"🚨 Fraud Risk Alert - {restaurant_name}",
                        message=f"Detected {len(high_severity)} high-risk transactions with multiple fraud indicators." + details,
                        type="alert",
                        cat = "fraud",
                        restaurant_id=restaurant_id,
                        conn=conn
                    )
                    notification_ids.append(notification["id"])
            
            # Employee risk scores
            high_risk_employees = alerts.get("employee_risk_scores", [])
            high_risk_employees = [e for e in high_risk_employees if e.get("severity") == "high"]
            if high_risk_employees:
                details = "\n\nEmployees with high fraud risk scores:\n"
                
                for i, emp in enumerate(high_risk_employees):
                    details += f"• Employee #{emp.get('employee_id')}"
                    if emp.get('employee_name'):
                        details += f" ({emp.get('employee_name')})"
                    details += f": Risk score {emp.get('risk_score', 0)}\n"
                    details += f"  Risk factors: {', '.join(emp.get('risk_factors', []))}\n"
                
                details += "\nRecommendation: Review these employees' transaction histories and consider additional oversight measures."
                
                notification = await create_notification(
                    user_id=user_id,
                    title=f"👤 Employee Fraud Risk Alert - {restaurant_name}",
                    message=f"Detected {len(high_risk_employees)} employees with high fraud risk scores." + details,
                    type="alert",
                    cat = "fraud",
                    restaurant_id=restaurant_id,
                    conn=conn
                )
                notification_ids.append(notification["id"])
        
        # Process root causes
        if root_causes and root_causes.get("status") == "success":
            causes = root_causes.get("root_causes", {})
            
            # Transaction anomalies root causes
            transaction_causes = causes.get("transaction_anomalies", [])
            if transaction_causes:
                details = "\n\nRoot causes for transaction anomalies:\n"
                
                # Group by cause type
                cause_types = {}
                for cause in transaction_causes:
                    for potential_cause in cause.get("potential_causes", []):
                        if potential_cause not in cause_types:
                            cause_types[potential_cause] = []
                        cause_types[potential_cause].append(cause)
                
                for cause_type, related_causes in cause_types.items():
                    details += f"• {cause_type.replace('_', ' ').title()}: {len(related_causes)} instances\n"
                
                details += "\nRecommendation: Address these root causes to prevent future anomalies."
                
                notification = await create_notification(
                    user_id=user_id,
                    title=f"🔍 Transaction Root Cause Analysis - {restaurant_name}",
                    message=f"Identified root causes for {len(transaction_causes)} transaction anomalies." + details,
                    type="info",
                    cat = "file",
                    restaurant_id=restaurant_id,
                    conn=conn
                )
                notification_ids.append(notification["id"])
            
            # Employee anomalies root causes
            employee_causes = causes.get("employee_anomalies", [])
            if employee_causes:
                details = "\n\nRoot causes for employee anomalies:\n"
                
                # Group by employee
                emp_causes = {}
                for cause in employee_causes:
                    emp_id = cause.get("employee_id")
                    if emp_id not in emp_causes:
                        emp_causes[emp_id] = []
                    emp_causes[emp_id].append(cause)
                
                for emp_id, emp_cause_list in emp_causes.items():
                    details += f"• Employee #{emp_id}: "
                    all_causes = []
                    for cause in emp_cause_list:
                        all_causes.extend(cause.get("potential_causes", []))
                    details += f"{', '.join(set(all_causes))}\n"
                
                details += "\nRecommendation: Address these employee-related issues through training or policy changes."
                
                notification = await create_notification(
                    user_id=user_id,
                    title=f"👤 Employee Behavior Analysis - {restaurant_name}",
                    message=f"Identified root causes for unusual behavior in {len(emp_causes)} employees." + details,
                    type="info",
                    cat = "fraud",
                    restaurant_id=restaurant_id,
                    conn=conn
                )
                notification_ids.append(notification["id"])
            
            # Temporal patterns (multiple anomalies in same time period)
            temporal_patterns = causes.get("temporal_patterns", [])
            if temporal_patterns:
                details = "\n\nTime periods with multiple anomalies:\n"
                
                for i, pattern in enumerate(temporal_patterns[:5]):
                    details += f"• {pattern.get('date', '')} {pattern.get('time_period', '')}: "
                    details += f"{pattern.get('anomaly_count', 0)} anomalies\n"
                
                if len(temporal_patterns) > 5:
                    details += f"... and {len(temporal_patterns) - 5} more time periods\n"
                
                details += "\nRecommendation: Investigate these time periods for potential systematic issues or policy violations."
                
                notification = await create_notification(
                    user_id=user_id,
                    title=f"⏱️ Time Pattern Alert - {restaurant_name}",
                    message=f"Detected {len(temporal_patterns)} time periods with multiple anomalies, suggesting systematic issues." + details,
                    type="warning",
                    cat = "fraud",
                    restaurant_id=restaurant_id,
                    conn=conn
                )
                notification_ids.append(notification["id"])
        
        return notification_ids
    
    except Exception as e:
        logging.error(f"Error creating fraud detection notifications: {str(e)}")
        return notification_ids

async def create_operational_efficiency_notifications(
    user_id: int,
    restaurant_id: int,
    restaurant_name: str,
    efficiency_data: Dict[str, Any],
    conn
):
    """
    Create notifications for operational efficiency recommendations.
    
    Args:
        user_id: The ID of the user to notify
        restaurant_id: The ID of the restaurant
        restaurant_name: The name of the restaurant
        efficiency_data: Dictionary containing operational efficiency metrics
        conn: Database connection
    
    Returns:
        List of created notification IDs
    """
    from src.chat_gpt import create_notification
    
    notification_ids = []
    
    try:
        if not efficiency_data or efficiency_data.get("status") != "success":
            return notification_ids
        
        metrics = efficiency_data.get("efficiency_metrics", {})
        
        # Sales velocity recommendations
        if "sales_velocity" in metrics and metrics["sales_velocity"]:
            velocity_data = metrics["sales_velocity"]
            
            # Check for low sales velocity periods
            low_velocity_periods = []
            for entry in velocity_data:
                if entry.get("transaction_count", 0) < 5 and entry.get("hour") not in [0, 1, 2, 3, 4, 5, 23]:
                    # Skip early morning and late night hours
                    low_velocity_periods.append(entry)
            
            if low_velocity_periods:
                # Group by hour
                hour_groups = {}
                for period in low_velocity_periods:
                    hour = period.get("hour", "Unknown")
                    if hour not in hour_groups:
                        hour_groups[hour] = []
                    hour_groups[hour].append(period)
                
                details = "\n\nHours with low sales activity:\n"
                for hour, periods in sorted(hour_groups.items()):
                    avg_txns = sum(p.get("transaction_count", 0) for p in periods) / len(periods)
                    avg_revenue = sum(p.get("revenue", 0) for p in periods) / len(periods)
                    details += f"• {hour}:00 hour: {avg_txns:.1f} transactions, ${avg_revenue:.2f} average revenue\n"
                
                details += "\nRecommendations:\n"
                details += "• Consider running promotions during these slow periods\n"
                details += "• Adjust staffing levels to match customer demand\n"
                details += "• Evaluate if operating during these hours is cost-effective\n"
                
                notification = await create_notification(
                    user_id=user_id,
                    title=f"📉 Low Sales Activity - {restaurant_name}",
                    message=f"Detected {len(low_velocity_periods)} time periods with unusually low sales activity." + details,
                    type="info",
                    cat = "fraud",
                    restaurant_id=restaurant_id,
                    conn=conn
                )
                notification_ids.append(notification["id"])
        
        # Peak hour analysis recommendations
        if "peak_hour_analysis" in metrics and "peak_hours" in metrics["peak_hour_analysis"]:
            peak_hours = metrics["peak_hour_analysis"]["peak_hours"]
            peak_revenue_pct = metrics["peak_hour_analysis"].get("peak_hour_revenue_percentage", 0)
            
            if peak_revenue_pct > 80:
                details = "\n\nPeak hours analysis:\n"
                
                # Format peak hours for display
                peak_hours_str = ", ".join([f"{hour}:00" for hour in sorted(peak_hours)])
                details += f"• Peak hours: {peak_hours_str}\n"
                details += f"• Revenue during peak hours: {round(peak_revenue_pct)}% of total\n"
                
                details += "\nRecommendations:\n"
                details += "• Ensure adequate staffing during peak hours to maintain service quality\n"
                details += "• Consider special promotions during off-peak hours to distribute demand\n"
                details += "• Evaluate if reservation systems or queue management could improve customer flow\n"
                details += "• Analyze menu items that are popular during peak hours for potential price optimization\n"
                
                notification = await create_notification(
                    user_id=user_id,
                    title=f"⏰ Peak Hour Concentration - {restaurant_name}",
                    message=f"Over {round(peak_revenue_pct)}% of revenue is concentrated in peak hours. Consider strategies to distribute sales more evenly." + details,
                    type="info",
                    cat = "fraud",
                    restaurant_id=restaurant_id,
                    conn=conn
                )
                notification_ids.append(notification["id"])
        
        # Employee efficiency recommendations
        if "employee_efficiency" in metrics and metrics["employee_efficiency"]:
            emp_data = metrics["employee_efficiency"]
            
            # Find employees with low efficiency
            low_efficiency_employees = []
            for emp in emp_data:
                if emp.get("items_per_transaction", 0) < 1.5 or emp.get("revenue_per_transaction", 0) < 10:
                    low_efficiency_employees.append(emp)
            
            if len(low_efficiency_employees) > 0:
                details = "\n\nEmployees with efficiency opportunities:\n"
                
                for i, emp in enumerate(low_efficiency_employees[:5]):
                    details += f"• Employee #{emp.get('employee_id')}: "
                    details += f"{emp.get('items_per_transaction', 0):.1f} items/transaction, "
                    details += f"${emp.get('revenue_per_transaction', 0):.2f} revenue/transaction\n"
                
                if len(low_efficiency_employees) > 5:
                    details += f"... and {len(low_efficiency_employees) - 5} more employees\n"
                
                details += "\nRecommendations:\n"
                details += "• Provide additional training on upselling techniques\n"
                details += "• Review menu knowledge and product recommendations\n"
                details += "• Consider implementing sales incentives or friendly competitions\n"
                details += "• Pair lower-performing employees with high performers for mentoring\n"
                
                notification = await create_notification(
                    user_id=user_id,
                    title=f"👤 Employee Efficiency Opportunity - {restaurant_name}",
                    message=f"Identified {len(low_efficiency_employees)} employees who may benefit from additional training or support." + details,
                    type="info",
                    cat = "fraud",
                    restaurant_id=restaurant_id,
                    conn=conn
                )
                notification_ids.append(notification["id"])
        
        # Inventory turnover recommendations
        if "inventory_turnover" in metrics and metrics["inventory_turnover"]:
            inventory_data = metrics["inventory_turnover"]
            
            # Find low turnover ingredients
            low_turnover = [item for item in inventory_data if item.get("turnover_ratio", 0) < 0.1]
            
            if low_turnover:
                details = "\n\nIngredients with low turnover rates:\n"
                
                for i, item in enumerate(low_turnover[:5]):
                    details += f"• {item.get('ingredient', 'Unknown')}: "
                    details += f"{item.get('turnover_ratio', 0)*100:.1f}% turnover rate, "
                    details += f"${item.get('inventory_value', 0):.2f} inventory value\n"
                
                if len(low_turnover) > 5:
                    details += f"... and {len(low_turnover) - 5} more ingredients\n"
                
                details += "\nRecommendations:\n"
                details += "• Reduce order quantities for these ingredients\n"
                details += "• Create specials to use excess inventory\n"
                details += "• Review menu items containing these ingredients for popularity\n"
                details += "• Consider removing or replacing these ingredients in your menu\n"
                
                notification = await create_notification(
                    user_id=user_id,
                    title=f"🧾 Inventory Optimization - {restaurant_name}",
                    message=f"Identified {len(low_turnover)} ingredients with low turnover rates. Consider adjusting inventory levels." + details,
                    type="info",
                    cat = "fraud",
                    restaurant_id=restaurant_id,
                    conn=conn
                )
                notification_ids.append(notification["id"])
        
        # Order type efficiency recommendations
        if "order_type_efficiency" in metrics and metrics["order_type_efficiency"]:
            order_data = metrics["order_type_efficiency"]
            
            # Find order types with low efficiency
            low_efficiency_types = []
            for order_type in order_data:
                if order_type.get("items_per_transaction", 0) < 1.5 or order_type.get("revenue_per_transaction", 0) < 10:
                    low_efficiency_types.append(order_type)
            
            if low_efficiency_types:
                details = "\n\nOrder types with optimization opportunities:\n"
                
                for i, order_type in enumerate(low_efficiency_types):
                    details += f"• {order_type.get('order_type', 'Unknown')}: "
                    details += f"{order_type.get('items_per_transaction', 0):.1f} items/transaction, "
                    details += f"${order_type.get('revenue_per_transaction', 0):.2f} revenue/transaction\n"
                
                details += "\nRecommendations:\n"
                details += "• Review pricing and bundling strategies for these order types\n"
                details += "• Implement targeted promotions to increase average order value\n"
                details += "• Train staff on specific upselling techniques for these order types\n"
                details += "• Consider delivery fees or minimum order requirements if applicable\n"
                
                notification = await create_notification(
                    user_id=user_id,
                    title=f"🍽️ Order Type Optimization - {restaurant_name}",
                    message=f"Identified {len(low_efficiency_types)} order types with lower than average efficiency." + details,
                    type="info",
                    cat = "fraud",
                    restaurant_id=restaurant_id,
                    conn=conn
                )
                notification_ids.append(notification["id"])
        
        # Create a summary notification with overall efficiency score
        overall_score = efficiency_data.get("overall_efficiency_score", 0)
        if overall_score > 0:
            score_category = "Excellent" if overall_score > 85 else "Good" if overall_score > 70 else "Average" if overall_score > 50 else "Needs Improvement"
            
            details = "\n\nEfficiency metrics summary:\n"
            for metric_name, metric_data in metrics.items():
                if isinstance(metric_data, list) and metric_data:
                    details += f"• {metric_name.replace('_', ' ').title()}: {len(metric_data)} data points analyzed\n"
                elif isinstance(metric_data, dict) and metric_data:
                    details += f"• {metric_name.replace('_', ' ').title()}: Analysis completed\n"
            
            details += f"\nOverall efficiency score: {overall_score}/100 ({score_category})\n"
            details += "\nView detailed reports in the Analytics dashboard for more insights."
            
            notification = await create_notification(
                user_id=user_id,
                title=f"📊 Operational Efficiency Summary - {restaurant_name}",
                message=f"Completed operational efficiency analysis with {len(notification_ids)} improvement opportunities identified." + details,
                type="info",
                cat = "fraud",
                restaurant_id=restaurant_id,
                conn=conn
            )
            notification_ids.append(notification["id"])
        
        return notification_ids
    
    except Exception as e:
        logging.error(f"Error creating operational efficiency notifications: {str(e)}")
        return notification_ids

async def process_fraud_and_efficiency_notifications(
    user_id: int,
    restaurant_id: int,
    restaurant_name: str,
    analysis_results: Dict[str, Any],
    conn
):
    """
    Process all fraud detection and operational efficiency notifications.
    
    Args:
        user_id: The ID of the user to notify
        restaurant_id: The ID of the restaurant
        restaurant_name: The name of the restaurant
        analysis_results: Dictionary containing all analysis results
        conn: Database connection
    
    Returns:
        Dictionary with counts of created notifications
    """
    notification_counts = {
        "fraud_detection": 0,
        "operational_efficiency": 0
    }
    
    try:
        # Extract analysis components
        anomaly_data = analysis_results.get("fraud_detection", {}).get("anomalies", {})
        fraud_alerts = analysis_results.get("fraud_detection", {}).get("fraud_alerts", {})
        root_causes = analysis_results.get("fraud_detection", {}).get("root_causes", {})
        efficiency_data = analysis_results.get("operational_efficiency", {})
        
        # Create fraud detection notifications
        fraud_notification_ids = await create_fraud_detection_notifications(
            user_id=user_id,
            restaurant_id=restaurant_id,
            restaurant_name=restaurant_name,
            anomaly_data=anomaly_data,
            fraud_alerts=fraud_alerts,
            root_causes=root_causes,
            conn=conn
        )
        notification_counts["fraud_detection"] = len(fraud_notification_ids)
        
        # Create operational efficiency notifications
        efficiency_notification_ids = await create_operational_efficiency_notifications(
            user_id=user_id,
            restaurant_id=restaurant_id,
            restaurant_name=restaurant_name,
            efficiency_data=efficiency_data,
            conn=conn
        )
        notification_counts["operational_efficiency"] = len(efficiency_notification_ids)
        
        return notification_counts
    
    except Exception as e:
        logging.error(f"Error processing fraud and efficiency notifications: {str(e)}")
        return notification_counts