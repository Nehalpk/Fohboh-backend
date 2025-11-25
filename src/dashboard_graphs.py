import pandas as pd
import logging
from collections import defaultdict
import io
from psycopg2.extras import RealDictCursor
import numpy as np
from fastapi import UploadFile
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import asyncio
import time
import os
from functools import partial
from src.fraud_detection_operational_efficiency import FraudDetectionOperationalEfficiency

# Set up basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(filename)s - %(message)s'
)

# Determine optimal number of workers based on CPU cores
# Use N-1 cores to leave one for the main application
CPU_COUNT = max(1, mp.cpu_count() - 1)
logging.info(f"Using {CPU_COUNT} CPU cores for parallel processing")


# Helper functions for parallel processing
def run_detect_sales_anomalies(df):
    """Run sales anomaly detection in a separate process"""
    fraud_detection = FraudDetectionOperationalEfficiency(memory_storage_path="cortex_memory")
    return fraud_detection.detect_sales_anomalies(df)


def run_analyze_operational_efficiency(df, inventory_df=None, employee_df=None):
    """Run operational efficiency analysis in a separate process"""
    fraud_detection = FraudDetectionOperationalEfficiency(memory_storage_path="cortex_memory")
    return fraud_detection.analyze_operational_efficiency(df, inventory_df, employee_df)


def run_generate_fraud_risk_alerts(df, employee_df=None):
    """Run fraud risk alerts generation in a separate process"""
    fraud_detection = FraudDetectionOperationalEfficiency(memory_storage_path="cortex_memory")
    return fraud_detection.generate_fraud_risk_alerts(df, employee_df)


def run_perform_root_cause_analysis(anomaly_results, df, inventory_df=None, employee_df=None):
    """Run root cause analysis in a separate process"""
    fraud_detection = FraudDetectionOperationalEfficiency(memory_storage_path="cortex_memory")
    return fraud_detection.perform_root_cause_analysis(anomaly_results, df, inventory_df, employee_df)


def run_generate_visual_insight_dashboard(anomaly_results, efficiency_results, fraud_alerts, root_causes):
    """Run visual insight dashboard generation in a separate process"""
    fraud_detection = FraudDetectionOperationalEfficiency(memory_storage_path="cortex_memory")
    return fraud_detection.generate_visual_insight_dashboard(anomaly_results, efficiency_results, fraud_alerts,
                                                             root_causes)


class DashboardCSVProcessor:
    def __init__(self):
        self.fraud_detection = FraudDetectionOperationalEfficiency(memory_storage_path="cortex_memory")
        self.executor = ProcessPoolExecutor(max_workers=CPU_COUNT)

    def __del__(self):
        """Clean up resources when the object is garbage collected"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)

    async def cleanup(self):
        """Explicitly clean up resources"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=True)
            logging.info("ProcessPoolExecutor shut down successfully")

    async def process_multiple_files(self, files_dict):
        """
        Process multiple CSV files in parallel and return the results.

        Args:
            files_dict: Dictionary mapping file types to UploadFile objects
                        e.g., {'sales': sales_file, 'inventory': inventory_file, ...}

        Returns:
            Dictionary with processed DataFrames for each file type
        """
        start_time = time.time()
        results = {}
        tasks = []

        # Create async tasks for each file type
        if 'sales' in files_dict and files_dict['sales']:
            tasks.append(('sales', self.process_sales_csv(files_dict['sales'])))

        if 'inventory' in files_dict and files_dict['inventory']:
            tasks.append(('inventory', self.process_inventory_csv(files_dict['inventory'])))

        if 'menu' in files_dict and files_dict['menu']:
            tasks.append(('menu', self.process_menu_csv(files_dict['menu'])))

        if 'employees' in files_dict and files_dict['employees']:
            tasks.append(('employees', self.process_employees_csv(files_dict['employees'])))

        # Run all tasks concurrently
        for file_type, task in tasks:
            try:
                results[file_type] = await task
                logging.info(f"Successfully processed {file_type} file")
            except Exception as e:
                logging.error(f"Error processing {file_type} file: {e}")
                results[file_type] = None

        end_time = time.time()
        total_time = end_time - start_time
        logging.info(f"Processed {len(tasks)} files in {total_time:.2f} seconds")

        return {
            'results': results,
            'processing_time_seconds': round(total_time, 2),
            'files_processed': len(tasks)
        }

    async def process_sales_csv(self, file: UploadFile, conn=None, current_user=None, restaurant_id=None,
                                restaurant_name=None):
        """
        Process sales CSV file from the uploaded file and return relevant columns.
        Includes fraud detection and operational efficiency analysis.
        Uses multiprocessing to speed up analysis.

        Args:
            file: The uploaded CSV file
            conn: Optional database connection for creating notifications
            current_user: Optional current user information for notifications
            restaurant_id: Optional restaurant ID for notifications
            restaurant_name: Optional restaurant name for notifications
        """
        start_time = time.time()
        try:
            await file.seek(0)

            contents = await file.read()
            df = pd.read_csv(io.BytesIO(contents))

            # Data preprocessing - this is fast and doesn't need parallelization
            logging.info(f"Starting data preprocessing for sales CSV")

            df['Date'] = pd.to_datetime(df['Date'], format='%m/%d/%y', errors='coerce')
            df['Time'] = pd.to_datetime(df['Time'], format='%H:%M:%S', errors='coerce').dt.time
            df['Total Amount'] = pd.to_numeric(df['Total Amount'], errors='coerce')
            df['Subtotal'] = pd.to_numeric(df['Subtotal'], errors='coerce')
            df['Tip'] = pd.to_numeric(df['Tip'], errors='coerce')
            df['Discount Percent'] = pd.to_numeric(df['Discount Percent'], errors='coerce')

            columns = [
                'Sale ID', 'Date', 'Time', 'Items Sold', 'Number of Items',
                'Subtotal', 'Tip', 'Total Amount', 'Employee ID',
                'Is Loyalty Member', 'Promotion ID', 'Discount Percent',
                'Order Type', 'Payment Method'
            ]

            processed_df = df[columns]

            # Store sales data in Cortex Memory for future analysis
            self.fraud_detection.save_to_memory("latest_sales", processed_df)

            # Create a thread pool for running CPU-bound tasks in parallel
            # We use ProcessPoolExecutor for CPU-bound tasks
            logging.info(f"Starting parallel analysis tasks for sales CSV")

            # Optimize by running tasks in batches with dependencies
            with ThreadPoolExecutor(max_workers=CPU_COUNT) as executor:
                # First batch: Run independent analysis tasks in parallel
                futures = {
                    'anomaly': executor.submit(run_detect_sales_anomalies, processed_df),
                    'efficiency': executor.submit(run_analyze_operational_efficiency, processed_df),
                    'fraud_alerts': executor.submit(run_generate_fraud_risk_alerts, processed_df)
                }

                # Get results from the first batch as they complete
                anomaly_results = futures['anomaly'].result()
                efficiency_results = futures['efficiency'].result()
                fraud_alerts = futures['fraud_alerts'].result()

                # Save anomaly results to memory for other processes to use
                self.fraud_detection.save_to_memory("latest_anomalies", anomaly_results)

                # Second batch: Run dependent tasks
                root_causes_task = executor.submit(
                    run_perform_root_cause_analysis,
                    anomaly_results,
                    processed_df
                )

                # Get results from the second batch
                root_causes = root_causes_task.result()

                #     # Final task that depends on all previous results
                dashboard_task = executor.submit(
                    run_generate_visual_insight_dashboard,
                    anomaly_results,
                    efficiency_results,
                    fraud_alerts,
                    root_causes
                )

                dashboard_data = dashboard_task.result()

            # # Attach analysis results to the dataframe as metadata
            processed_df.attrs['fraud_detection'] = {
                'anomalies': anomaly_results,
                'efficiency': efficiency_results,
                'fraud_alerts': fraud_alerts,
                'root_causes': root_causes,
                'dashboard': dashboard_data
            }

            # Generate notifications if database connection and user info are provided
            if conn and current_user and restaurant_id:
                from src.fraud_notifications import process_fraud_and_efficiency_notifications
                from src.chat_gpt import create_notification

                # Prepare analysis results for notification processing
                analysis_results = {
                    "fraud_detection": {
                        "anomalies": anomaly_results,
                        "fraud_alerts": fraud_alerts,
                        "root_causes": root_causes
                    },
                    "operational_efficiency": efficiency_results
                }

                # Create a summary notification for the analysis
                await create_notification(
                    user_id=current_user.get("id"),
                    title=f"🔍 Fraud Detection Analysis - {restaurant_name or f'Restaurant {restaurant_id}'}",
                    message=f"Completed fraud detection and operational efficiency analysis. Found {anomaly_results.get('anomaly_count', 0)} anomalies and {fraud_alerts.get('alert_count', 0)} fraud alerts in {file.filename}.",
                    type="info",
                    cat="fraud",
                    restaurant_id=restaurant_id,
                    conn=conn
                )

                # Process detailed notifications asynchronously
                notification_task = asyncio.create_task(
                    process_fraud_and_efficiency_notifications(
                        user_id=current_user.get("id"),
                        restaurant_id=restaurant_id,
                        restaurant_name=restaurant_name,
                        analysis_results=analysis_results,
                        conn=conn
                    )
                )

                # Store the notification task for later retrieval
                processed_df.attrs['notification_task'] = notification_task

            end_time = time.time()
            processing_time = end_time - start_time
            logging.info(
                f"Processed sales CSV successfully with fraud detection and efficiency analysis in {processing_time:.2f} seconds.")
            return processed_df
        except Exception as e:
            logging.error(f"Error processing sales CSV: {e}")
            return None

    async def process_inventory_csv(self, file, conn=None, current_user=None, restaurant_id=None, restaurant_name=None):
        """
        Process inventory CSV file from the uploaded file and return relevant columns.
        Includes operational efficiency analysis for inventory.
        Uses multiprocessing to speed up analysis.

        Args:
            file: The uploaded CSV file
            conn: Optional database connection for creating notifications
            current_user: Optional current user information for notifications
            restaurant_id: Optional restaurant ID for notifications
            restaurant_name: Optional restaurant name for notifications
        """
        start_time = time.time()
        try:
            await file.seek(0)

            contents = await file.read()
            df = pd.read_csv(io.BytesIO(contents))

            # Data preprocessing with error handling for missing columns
            logging.info(f"Starting data preprocessing for inventory CSV")

            # Define required and optional columns
            required_columns = ['Ingredient', 'Quantity']
            optional_columns = ['Date', 'Par Level', 'Unit Cost', 'Is Low']

            # Check for required columns
            missing_required = [col for col in required_columns if col not in df.columns]
            if missing_required:
                logging.warning(f"Missing required columns in inventory CSV: {missing_required}")
                return pd.DataFrame(columns=required_columns + optional_columns)

            # Process columns that exist in the dataframe
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'], format='%m/%d/%y', errors='coerce')
            else:
                df['Date'] = pd.Timestamp.now()

            if 'Quantity' in df.columns:
                df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce')

            if 'Par Level' in df.columns:
                df['Par Level'] = pd.to_numeric(df['Par Level'], errors='coerce')
            else:
                df['Par Level'] = 0

            if 'Unit Cost' in df.columns:
                df['Unit Cost'] = pd.to_numeric(df['Unit Cost'], errors='coerce')
            else:
                df['Unit Cost'] = 0

            if 'Is Low' in df.columns:
                df['Is Low'] = df['Is Low'].astype(bool)
            else:
                # Calculate Is Low based on Quantity and Par Level if available
                if 'Quantity' in df.columns and 'Par Level' in df.columns:
                    df['Is Low'] = df['Quantity'] <= df['Par Level']
                else:
                    df['Is Low'] = False

            # Select all available columns
            available_columns = [col for col in ['Date', 'Ingredient', 'Quantity', 'Par Level', 'Unit Cost', 'Is Low']
                                 if col in df.columns]
            processed_df = df[available_columns]

            # Store inventory data in Cortex Memory for future analysis
            self.fraud_detection.save_to_memory("latest_inventory", processed_df)

            # Check for any sales data to perform combined analysis
            sales_data = self.fraud_detection.load_from_memory("latest_sales")
            if sales_data is not None:
                logging.info(f"Found sales data, starting parallel analysis for inventory CSV")

                try:
                    with ProcessPoolExecutor(max_workers=CPU_COUNT) as executor:
                        # Analyze operational efficiency with inventory context
                        efficiency_task = executor.submit(
                            run_analyze_operational_efficiency,
                            sales_data,
                            processed_df
                        )

                        # Get efficiency results
                        efficiency_results = efficiency_task.result()

                        # Initialize results dictionary
                        analysis_results = {
                            'efficiency': efficiency_results
                        }

                        # Perform root cause analysis with inventory context if anomalies exist
                        anomaly_results = self.fraud_detection.load_from_memory("latest_anomalies")
                        if anomaly_results:
                            try:
                                root_causes_task = executor.submit(
                                    run_perform_root_cause_analysis,
                                    anomaly_results,
                                    sales_data,
                                    processed_df
                                )

                                # Get root causes results
                                root_causes = root_causes_task.result()
                                analysis_results['root_causes'] = root_causes
                            except Exception as e:
                                logging.error(f"Error in root cause analysis for inventory: {e}")
                                analysis_results['root_causes'] = {"error": str(e)}

                        # Attach analysis results to the dataframe as metadata
                        processed_df.attrs['operational_efficiency'] = analysis_results

                        # Step 3: Compute inventory ratio
                        processed_df['inventory_ratio'] = processed_df['Quantity'] / processed_df['Par Level']

                        # Step 4: Categorize inventory levels
                        def get_inventory_alert(ratio):
                            if ratio < 0.4:
                                return "CRITICAL LOW"
                            elif ratio < 0.6:
                                return "LOW"
                            elif ratio > 1.3:
                                return "HIGH"
                            else:
                                return "NORMAL"

                        processed_df['Alert'] = processed_df['inventory_ratio'].apply(get_inventory_alert)
                        processed_df['Is Low'] = processed_df['Alert'].isin(['LOW', 'CRITICAL LOW'])

                        # Generate notifications if database connection and user info are provided
                        if conn and current_user and restaurant_id:
                            from src.chat_gpt import create_notification

                            # Create a summary notification for the analysis
                            low_count = processed_df['Is Low'].sum()
                            total_items = len(processed_df)
                            critical_low_count = (processed_df['Alert'] == 'CRITICAL LOW').sum()
                            high_count = (processed_df['Alert'] == 'HIGH').sum()

                            await create_notification(
                                user_id=current_user["id"],
                                title=f"📊 Inventory Analysis - {restaurant_name or f'Restaurant {restaurant_id}'}",
                                message=(
                                    f"Inventory analysis for **{file.filename if file else 'uploaded file'}** has been successfully completed.\n\n",
                                    f"**Summary of Results:**\n",
                                    f"• **Total Items Analyzed:** {total_items}\n",
                                    f"• **Items Below Par Level:** {low_count} ",
                                    f"(including **{critical_low_count}** marked as *Critical Low*)\n",
                                    f"• **Items Above Optimal Level:** {high_count}\n\n",
                                    f"Please review the flagged items to ensure timely replenishment or adjustment.",
                                ),

                                type="info",
                                cat="file",
                                restaurant_id=restaurant_id,
                                conn=conn
                            )
                except Exception as e:
                    logging.error(f"Error in parallel processing for inventory: {e}")
                    processed_df.attrs['operational_efficiency'] = {"error": str(e)}

            end_time = time.time()
            processing_time = end_time - start_time
            logging.info(
                f"Processed inventory CSV successfully with operational efficiency analysis in {processing_time:.2f} seconds.")
            return processed_df
        except Exception as e:
            logging.error(f"Error processing inventory CSV: {e}")
            # Return empty DataFrame with expected columns instead of None
            return pd.DataFrame(columns=['Date', 'Ingredient', 'Quantity', 'Par Level', 'Unit Cost', 'Is Low'])

    async def process_menu_csv(self, file, conn=None, current_user=None, restaurant_id=None, restaurant_name=None):
        """
        Process menu CSV file from the uploaded file and return relevant columns.

        Args:
            file: The uploaded CSV file
            conn: Optional database connection for creating notifications
            current_user: Optional current user information for notifications
            restaurant_id: Optional restaurant ID for notifications
            restaurant_name: Optional restaurant name for notifications
        """
        start_time = time.time()
        try:
            await file.seek(0)

            contents = await file.read()
            df = pd.read_csv(io.BytesIO(contents))

            # Define required and optional columns
            required_columns = ['Menu Item', 'Ingredient']
            optional_columns = ['Amount', 'Unit Cost', 'Created At', 'Category', 'Description']

            # Check for required columns
            missing_required = [col for col in required_columns if col not in df.columns]
            if missing_required:
                logging.warning(f"Missing required columns in menu CSV: {missing_required}")
                return pd.DataFrame(columns=required_columns + optional_columns)

            # Process columns that exist in the dataframe
            if 'Amount' in df.columns:
                df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce')
            else:
                df['Amount'] = 1.0

            if 'Unit Cost' in df.columns:
                df['Unit Cost'] = pd.to_numeric(df['Unit Cost'], errors='coerce')
            else:
                df['Unit Cost'] = 0.0

            if 'Created At' not in df.columns:
                df['Created At'] = pd.Timestamp.now()

            # Add optional columns if they don't exist
            for col in optional_columns:
                if col not in df.columns and col not in ['Amount', 'Unit Cost', 'Created At']:
                    df[col] = None

            # Select all available columns
            available_columns = [col for col in required_columns + optional_columns if col in df.columns]
            processed_df = df[available_columns]

            # Store menu data in Cortex Memory for future analysis
            self.fraud_detection.save_to_memory("latest_menu", processed_df)

            # Check for sales and inventory data to perform combined analysis
            sales_data = self.fraud_detection.load_from_memory("latest_sales")
            inventory_data = self.fraud_detection.load_from_memory("latest_inventory")

            if sales_data is not None and inventory_data is not None:
                logging.info(f"Found sales and inventory data, starting analysis for menu CSV")

                try:
                    # Calculate menu item profitability
                    menu_profitability = {}

                    # Extract all items from sales data
                    all_items = []
                    item_revenue = defaultdict(float)

                    for _, row in sales_data.iterrows():
                        if 'Items Sold' in row and 'Subtotal' in row:
                            items = [item.strip() for item in str(row['Items Sold']).split(';') if item.strip()]
                            if items:
                                all_items.extend(items)
                                per_item_price = row['Subtotal'] / len(items)
                                for item in items:
                                    item_revenue[item] += per_item_price

                    # Count occurrences of each item
                    item_counts = pd.Series(all_items).value_counts()

                    # Calculate cost for each menu item
                    for menu_item in processed_df['Menu Item'].unique():
                        ingredients = processed_df[processed_df['Menu Item'] == menu_item]
                        cost = 0
                        for _, ing in ingredients.iterrows():
                            if 'Amount' in ing and 'Unit Cost' in ing:
                                cost += float(ing['Amount'] or 0) * float(ing['Unit Cost'] or 0)

                        # Calculate profitability
                        revenue = item_revenue.get(menu_item, 0)
                        count = item_counts.get(menu_item, 0)

                        menu_profitability[menu_item] = {
                            'cost': cost,
                            'revenue': revenue,
                            'profit': revenue - (cost * count),
                            'count': count
                        }

                    # Attach analysis results to the dataframe as metadata
                    processed_df.attrs['menu_analysis'] = {
                        'profitability': menu_profitability,
                        'total_items': len(processed_df['Menu Item'].unique()),
                        'total_ingredients': len(processed_df['Ingredient'].unique())
                    }

                    # Generate notifications if database connection and user info are provided
                    if conn and current_user and restaurant_id:
                        from src.chat_gpt import create_notification

                        # Find most and least profitable items
                        profitable_items = sorted(
                            [(item, data['profit']) for item, data in menu_profitability.items() if data['count'] > 0],
                            key=lambda x: x[1],
                            reverse=True
                        )

                        most_profitable = profitable_items[:3] if profitable_items else []
                        least_profitable = profitable_items[-3:] if len(profitable_items) >= 3 else []

                        # Create a summary notification
                        await create_notification(
                            user_id=current_user.get("id"),
                            title=f"🍽️ Menu Analysis - {restaurant_name or f'Restaurant {restaurant_id}'}",
                            message=f"Completed menu analysis for {file.filename}. Found {len(processed_df['Menu Item'].unique())} menu items using {len(processed_df['Ingredient'].unique())} ingredients.",
                            type="info",
                            cat="file",
                            restaurant_id=restaurant_id,
                            conn=conn
                        )

                        # Create notification for profitable items if available
                        if most_profitable:
                            most_profitable_msg = ", ".join(
                                [f"{item} (${profit:.2f})" for item, profit in most_profitable])
                            await create_notification(
                                user_id=current_user.get("id"),
                                title=f"💰 Most Profitable Menu Items",
                                message=f"Your most profitable menu items are: {most_profitable_msg}",
                                type="info",
                                cat="fraud",
                                restaurant_id=restaurant_id,
                                conn=conn
                            )
                except Exception as e:
                    logging.error(f"Error in menu analysis: {e}")
                    processed_df.attrs['menu_analysis'] = {"error": str(e)}

            end_time = time.time()
            processing_time = end_time - start_time
            logging.info(f"Processed menu CSV successfully in {processing_time:.2f} seconds.")
            return processed_df
        except Exception as e:
            logging.error(f"Error processing menu CSV: {e}")
            # Return empty DataFrame with expected columns instead of None
            return pd.DataFrame(columns=['Menu Item', 'Ingredient', 'Amount', 'Unit Cost', 'Created At'])

    async def process_employees_csv(self, file, conn=None, current_user=None, restaurant_id=None, restaurant_name=None):
        """
        Process employee CSV file from the uploaded file and return relevant columns.
        Handles additional staff information fields if present.
        Includes fraud risk analysis for employees.
        Uses multiprocessing to speed up analysis.

        Args:
            file: The uploaded CSV file
            conn: Optional database connection for creating notifications
            current_user: Optional current user information for notifications
            restaurant_id: Optional restaurant ID for notifications
            restaurant_name: Optional restaurant name for notifications
        """
        start_time = time.time()
        try:
            await file.seek(0)

            contents = await file.read()
            df = pd.read_csv(io.BytesIO(contents))

            # Define required and optional columns
            required_columns = ['Employee ID', 'Name']
            optional_columns = ['Role', 'Hire Date', 'Termination Date', 'Hourly Rate',
                                'Profile Image', 'Contact Number', 'Email', 'Address',
                                'Emergency Contact', 'Notes', 'Department', 'Manager']

            # Check for required columns
            missing_required = [col for col in required_columns if col not in df.columns]
            if missing_required:
                logging.warning(f"Missing required columns in employees CSV: {missing_required}")
                return pd.DataFrame(columns=required_columns + optional_columns)

            # Process columns that exist in the dataframe
            logging.info(f"Starting data preprocessing for employees CSV")

            if 'Hire Date' in df.columns:
                df['Hire Date'] = pd.to_datetime(df['Hire Date'], format='%m/%d/%y', errors='coerce')
            else:
                df['Hire Date'] = pd.NaT

            if 'Termination Date' in df.columns:
                df['Termination Date'] = pd.to_datetime(df['Termination Date'], format='%m/%d/%y', errors='coerce')
            else:
                df['Termination Date'] = pd.NaT

            if 'Hourly Rate' in df.columns:
                df['Hourly Rate'] = pd.to_numeric(df['Hourly Rate'], errors='coerce')
            else:
                df['Hourly Rate'] = 0.0

            if 'Role' not in df.columns:
                df['Role'] = 'Unknown'

            # Add other optional columns if they don't exist
            for col in optional_columns:
                if col not in df.columns and col not in ['Hire Date', 'Termination Date', 'Hourly Rate', 'Role']:
                    df[col] = None

            # Check which columns exist in the dataframe
            available_columns = [col for col in required_columns + optional_columns if col in df.columns]
            processed_df = df[available_columns]

            # Store employee data in Cortex Memory for future analysis
            self.fraud_detection.save_to_memory("latest_employees", processed_df)

            # Check for any sales data to perform combined analysis
            sales_data = self.fraud_detection.load_from_memory("latest_sales")
            if sales_data is not None:
                logging.info(f"Found sales data, starting parallel analysis for employees CSV")

                try:
                    with ProcessPoolExecutor(max_workers=CPU_COUNT) as executor:
                        # Initialize results dictionary
                        analysis_results = {}

                        # Submit first batch of tasks
                        futures = {}

                        # Only run fraud alerts if Employee ID exists in both datasets
                        if 'Employee ID' in processed_df.columns and 'Employee ID' in sales_data.columns:
                            futures['fraud_alerts'] = executor.submit(
                                run_generate_fraud_risk_alerts,
                                sales_data,
                                processed_df
                            )

                        futures['efficiency'] = executor.submit(
                            run_analyze_operational_efficiency,
                            sales_data,
                            None,
                            processed_df
                        )

                        # Get results from first batch
                        if 'fraud_alerts' in futures:
                            try:
                                fraud_alerts = futures['fraud_alerts'].result()
                                analysis_results['fraud_alerts'] = fraud_alerts
                            except Exception as e:
                                logging.error(f"Error generating fraud alerts: {e}")
                                analysis_results['fraud_alerts'] = {"error": str(e)}

                        try:
                            efficiency_results = futures['efficiency'].result()
                            analysis_results['efficiency'] = efficiency_results
                        except Exception as e:
                            logging.error(f"Error analyzing operational efficiency: {e}")
                            analysis_results['efficiency'] = {"error": str(e)}

                        # Perform root cause analysis with employee context if anomalies exist
                        anomaly_results = self.fraud_detection.load_from_memory("latest_anomalies")
                        if anomaly_results:
                            try:
                                # Submit second batch of tasks
                                root_causes_task = executor.submit(
                                    run_perform_root_cause_analysis,
                                    anomaly_results,
                                    sales_data,
                                    None,
                                    processed_df
                                )

                                # Get root causes results
                                root_causes = root_causes_task.result()
                                analysis_results['root_causes'] = root_causes

                                # Only generate dashboard if we have all required data
                                if 'fraud_alerts' in analysis_results and 'efficiency' in analysis_results:
                                    try:
                                        # Generate visual insight dashboard data
                                        dashboard_task = executor.submit(
                                            run_generate_visual_insight_dashboard,
                                            anomaly_results,
                                            efficiency_results,
                                            analysis_results.get('fraud_alerts', {}),
                                            root_causes
                                        )

                                        dashboard_data = dashboard_task.result()
                                        analysis_results['dashboard'] = dashboard_data
                                    except Exception as e:
                                        logging.error(f"Error generating dashboard: {e}")
                                        analysis_results['dashboard'] = {"error": str(e)}
                            except Exception as e:
                                logging.error(f"Error in root cause analysis: {e}")
                                analysis_results['root_causes'] = {"error": str(e)}

                        # Attach analysis results to the dataframe as metadata
                        processed_df.attrs['fraud_detection'] = analysis_results

                        # Generate notifications if database connection and user info are provided
                        if conn and current_user and restaurant_id:
                            from src.chat_gpt import create_notification

                            # Create a summary notification for the analysis
                            fraud_alert_count = analysis_results.get('fraud_alerts', {}).get('alert_count', 0)

                            await create_notification(
                                user_id=current_user.get("id"),
                                title=f"👥 Employee Analysis - {restaurant_name or f'Restaurant {restaurant_id}'}",
                                message=f"Completed employee analysis for {file.filename}. Found {len(processed_df)} employees and {fraud_alert_count} potential fraud alerts.",
                                type="info",
                                cat="fraud",
                                restaurant_id=restaurant_id,
                                conn=conn
                            )

                            # If there are fraud alerts, create a specific notification
                            if fraud_alert_count > 0 and 'fraud_alerts' in analysis_results:
                                try:
                                    top_alerts = analysis_results['fraud_alerts'].get('alerts', [])[:3]
                                    alert_msg = "\n".join(
                                        [f"- {alert.get('description', 'Unknown alert')}" for alert in top_alerts])

                                    await create_notification(
                                        user_id=current_user.get("id"),
                                        title=f"⚠️ Employee Fraud Alerts",
                                        message=f"Top employee fraud alerts:\n{alert_msg}",
                                        type="warning",
                                        cat="fraud",
                                        restaurant_id=restaurant_id,
                                        conn=conn
                                    )
                                except Exception as e:
                                    logging.error(f"Error creating fraud alert notification: {e}")
                except Exception as e:
                    logging.error(f"Error in parallel processing for employees: {e}")
                    processed_df.attrs['fraud_detection'] = {"error": str(e)}

            end_time = time.time()
            processing_time = end_time - start_time
            logging.info(
                f"Processed employees CSV successfully with fraud risk analysis in {processing_time:.2f} seconds.")
            return processed_df
        except Exception as e:
            logging.error(f"Error processing employees CSV: {e}")
            # Return empty DataFrame with expected columns instead of None
            return pd.DataFrame(columns=['Employee ID', 'Name', 'Role', 'Hire Date', 'Termination Date', 'Hourly Rate'])

    async def get_sales_summary(self, sales_df, menu_df):
        """
        Generate sales summary including total revenue, top 4 selling items' profit,
        fraud detection, and operational efficiency analysis.
        Uses multiprocessing to speed up analysis.
        """
        start_time = time.time()
        try:
            logging.info(f"Starting sales summary generation with multiprocessing")

            # --- Run basic sales metrics calculation in the main process ---
            # This is relatively fast and doesn't need parallelization

            # --- Total Revenue ---
            total_revenue = sales_df['Total Amount'].sum()

            # --- Count Item Sales + Revenue Estimation ---
            item_counter = defaultdict(int)
            item_revenue = defaultdict(float)

            for _, row in sales_df.iterrows():
                items = [i.strip() for i in str(row['Items Sold']).split(';')]
                num_items = len(items)
                if num_items == 0:
                    continue

                item_price = row['Subtotal'] / num_items
                for item in items:
                    item_counter[item] += 1
                    item_revenue[item] += item_price

            # --- Recipe Cost Lookup ---
            recipe_costs = {}
            for item in menu_df['Menu Item'].unique():
                ing = menu_df[menu_df['Menu Item'] == item]
                cost = (ing['Amount'] * ing['Unit Cost']).sum()
                recipe_costs[item.strip()] = cost

            # --- Top 4 Selling Items ---
            top_items = sorted(item_counter.items(), key=lambda x: x[1], reverse=True)[:4]
            top_item_names = [item for item, _ in top_items]

            top_items_profit = []
            for item in top_item_names:
                revenue = item_revenue[item]
                cost_per_unit = recipe_costs.get(item, 0)
                cost = cost_per_unit * item_counter[item]
                profit = revenue - cost

                top_items_profit.append({
                    "item": item,
                    "quantity_sold": item_counter[item],
                    "estimated_revenue": round(revenue, 2),
                    "estimated_cost": round(cost, 2),
                    "estimated_profit": round(profit, 2)
                })

            # --- Fraud Detection and Operational Efficiency Analysis ---
            # Store sales data in Cortex Memory for future analysis
            self.fraud_detection.save_to_memory("latest_sales", sales_df)

            # Load additional data
            inventory_df = self.fraud_detection.load_from_memory("latest_inventory")
            employees_df = self.fraud_detection.load_from_memory("latest_employees")

            # Run CPU-intensive analysis tasks in parallel using ProcessPoolExecutor
            with ProcessPoolExecutor(max_workers=CPU_COUNT) as executor:
                # Submit first batch of tasks
                anomaly_task = executor.submit(run_detect_sales_anomalies, sales_df)
                efficiency_task = executor.submit(
                    run_analyze_operational_efficiency,
                    sales_df,
                    inventory_df,
                    employees_df
                )
                fraud_alerts_task = executor.submit(
                    run_generate_fraud_risk_alerts,
                    sales_df,
                    employees_df
                )

                # Get results from first batch
                anomaly_results = anomaly_task.result()
                efficiency_results = efficiency_task.result()
                fraud_alerts = fraud_alerts_task.result()

                # Save anomaly results to memory for future use
                self.fraud_detection.save_to_memory("latest_anomalies", anomaly_results)

                # Submit second batch of tasks that depend on first batch
                root_causes_task = executor.submit(
                    run_perform_root_cause_analysis,
                    anomaly_results,
                    sales_df,
                    inventory_df,
                    employees_df
                )

                # Get root causes results
                root_causes = root_causes_task.result()

                # Submit final task that depends on all previous results
                dashboard_task = executor.submit(
                    run_generate_visual_insight_dashboard,
                    anomaly_results,
                    efficiency_results,
                    fraud_alerts,
                    root_causes
                )

                # Get dashboard data
                dashboard_data = dashboard_task.result()

            end_time = time.time()
            processing_time = end_time - start_time
            logging.info(
                f"Generated sales summary with fraud detection and efficiency analysis in {processing_time:.2f} seconds.")

            return {
                "total_revenue": round(total_revenue, 2),
                "top_4_items_profit": top_items_profit,
                "fraud_detection": {
                    "anomalies": anomaly_results,
                    "fraud_alerts": fraud_alerts,
                    "root_causes": root_causes
                },
                "operational_efficiency": efficiency_results,
                "visual_insights": dashboard_data,
                "processing_time_seconds": round(processing_time, 2)
            }
        except Exception as e:
            logging.error(f"Error generating sales summary: {e}")
            return None


# insert inot DB

class DashboardCSVUploader:
    def __init__(self, conn):
        self.conn = conn

    def insert_sales(self, processed_df, restaurant_id, filename):
        try:
            with self.conn.cursor() as cur:
                query = """
                    INSERT INTO sales_graphs (
                        restaurant_id, sale_id, date, time, items_sold,
                        number_of_items, subtotal, tip, total_amount,
                        payment_method, order_type, filename
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """
                records = [
                    (
                        restaurant_id,
                        str(row['Sale ID']),
                        row['Date'],
                        row['Time'],
                        row['Items Sold'],
                        int(row['Number of Items']),
                        float(row['Subtotal']),
                        float(row['Tip']) if not pd.isna(row['Tip']) else 0.0,
                        float(row['Total Amount']),
                        row['Payment Method'],
                        row['Order Type'],
                        filename
                    )
                    for _, row in processed_df.iterrows()
                ]
                cur.executemany(query, records)
                self.conn.commit()
                logging.info(f"Successfully inserted {len(records)} sales records into the database.")
        except Exception as e:
            self.conn.rollback()
            logging.error(f"Error inserting sales data: {e}")

    def insert_inventory(self, processed_df, restaurant_id, filename):
        try:
            import json
            from datetime import datetime, date
            
            with self.conn.cursor() as cur:
                query = """
                    INSERT INTO inventory_graphs (
                        restaurant_id,
                        date,
                        ingredient,
                        quantity,
                        par_level,
                        unit_cost,
                        is_low,
                        filename,
                        data
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """
                
                records = []
                for _, row in processed_df.iterrows():
                    # Convert all values to JSON-serializable
                    row_data = {key: self.convert_to_json_serializable(value) 
                               for key, value in row.to_dict().items()}
                    
                    # Helper function
                    def get_val(col_name, default=None):
                        return row.get(col_name, default) if col_name in row and pd.notna(row[col_name]) else default
                    
                    def get_date(col_name):
                        val = get_val(col_name)
                        if val is None:
                            return None
                        if isinstance(val, (pd.Timestamp, datetime)):
                            return val.date()
                        if isinstance(val, date):
                            return val
                        return None
                    
                    records.append((
                        restaurant_id,
                        get_date('Date'),
                        str(get_val('Ingredient', '')),
                        float(get_val('Quantity', 0.0)),
                        float(get_val('Par Level', 0.0)),
                        float(get_val('Unit Cost', 0.0)),
                        bool(get_val('Is Low', False)) if get_val('Is Low') is not None else False,
                        filename,
                        json.dumps(row_data)
                    ))
                
                cur.executemany(query, records)
                self.conn.commit()
                logging.info(f"✓ Successfully inserted {len(records)} inventory records into the database.")
        except Exception as e:
            self.conn.rollback()
            logging.error(f"✗ Error inserting inventory data: {e}")
            #logging.error(f"Traceback: {traceback.format_exc()}")



    def insert_menu(self, processed_df, restaurant_id, filename):
        try:
            with self.conn.cursor() as cur:
                query = """
                    INSERT INTO menu_graphs (
                        restaurant_id, menu_item, ingredient,
                        amount, unit_cost, filename
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """
                records = [
                    (
                        restaurant_id,
                        row['Menu Item'],
                        row['Ingredient'],
                        float(row['Amount']),
                        float(row['Unit Cost']),
                        filename
                    )
                    for _, row in processed_df.iterrows()
                ]
                cur.executemany(query, records)
                self.conn.commit()
                logging.info(f"Successfully inserted {len(records)} menu records into the database.")
        except Exception as e:
            self.conn.rollback()
            logging.error(f"Error inserting menu data: {e}")

    def insert_employees(self, processed_df, restaurant_id, filename):
        try:
            with self.conn.cursor() as cur:
                # First, check if the staff_info table exists, if not create it
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS staff_info (
                        id SERIAL PRIMARY KEY,
                        restaurant_id INTEGER NOT NULL,
                        employee_id INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        role TEXT NOT NULL,
                        hire_date DATE NOT NULL,
                        termination_date DATE,
                        hourly_rate DECIMAL(10, 2),
                        profile_image TEXT,
                        contact_number TEXT,
                        email TEXT,
                        address TEXT,
                        emergency_contact TEXT,
                        notes TEXT,
                        filename TEXT NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(restaurant_id, employee_id)
                    )
                """)
    
                # Create index for faster queries
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS staff_info_restaurant_id_idx 
                    ON staff_info(restaurant_id)
                """)
    
                # Insert into new staff_info table with additional fields
                staff_query = """
                    INSERT INTO staff_info (
                        restaurant_id, employee_id, name, role,
                        hire_date, termination_date, hourly_rate, 
                        profile_image, contact_number, email, filename
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (restaurant_id, employee_id) 
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        role = EXCLUDED.role,
                        hire_date = EXCLUDED.hire_date,
                        termination_date = EXCLUDED.termination_date,
                        hourly_rate = EXCLUDED.hourly_rate,
                        filename = EXCLUDED.filename,
                        updated_at = CURRENT_TIMESTAMP
                """
    
                # Extract contact info from CSV if available, otherwise use defaults
                staff_records = []
                for _, row in processed_df.iterrows():
                    # Convert NaT to None for database compatibility
                    hire_date = row['Hire Date'] if pd.notna(row['Hire Date']) else None
                    termination_date = row['Termination Date'] if pd.notna(row['Termination Date']) else None
                    
                    # Skip records without a valid hire date (required field)
                    if hire_date is None:
                        logging.warning(f"Skipping employee {row.get('Name', 'Unknown')} - missing hire date")
                        continue
                    
                    staff_records.append((
                        restaurant_id,
                        int(row['Employee ID']),
                        row['Name'],
                        row['Role'],
                        hire_date,
                        termination_date,
                        float(row['Hourly Rate']),
                        row.get('Profile Image', None) if 'Profile Image' in row else None,
                        row.get('Contact Number', None) if 'Contact Number' in row else None,
                        row.get('Email', None) if 'Email' in row else None,
                        filename
                    ))
                
                if staff_records:
                    cur.executemany(staff_query, staff_records)
                    self.conn.commit()
                    logging.info(f"Successfully inserted {len(staff_records)} employee records into the database.")
                else:
                    logging.warning(f"No valid employee records to insert for restaurant_id: {restaurant_id}")
                    
        except Exception as e:
            self.conn.rollback()
            logging.error(f"Error inserting employee data: {e}")

    def insert_promotions(self, processed_df, restaurant_id, filename):
        try:
            with self.conn.cursor() as cur:
                query = """
                    INSERT INTO promotion_graphs (
                        restaurant_id, promotion_id, promotion_name,
                        start_date, end_date, discount, filename
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """
                records = [
                    (
                        restaurant_id,
                        int(row['Promotion ID']),
                        row['Promotion Name'],
                        row['Start Date'],
                        row['End Date'],
                        row['Discount'],
                        filename
                    )
                    for _, row in processed_df.iterrows()
                ]
                cur.executemany(query, records)
                self.conn.commit()
                logging.info(f"Successfully inserted {len(records)} promotion records into the database.")
        except Exception as e:
            self.conn.rollback()
            logging.error(f"Error inserting promotion data: {e}")


async def get_sales_summary_by_restaurant(restaurant_name: str, current_user: dict, conn) -> dict | None:
    """
    Fetch total revenue and top 4 selling items for a given restaurant for the last 7 days,
    including income and mock expense per item.
    Also performs fraud detection and operational efficiency analysis.
    """
    from src.File_upload import get_restaurant_id_by_name
    from datetime import timedelta
    import psycopg2.extras
    from collections import defaultdict
    import pandas as pd
    from src.fraud_detection_operational_efficiency import FraudDetectionOperationalEfficiency
    from src.fraud_notifications import process_fraud_and_efficiency_notifications

    restaurant_id = get_restaurant_id_by_name(restaurant_name)
    fraud_detection = FraudDetectionOperationalEfficiency(memory_storage_path="cortex_memory")

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # logging.info(f"Restaurant '{restaurant_name}' found with ID: {restaurant_id}")

            # Find latest date
            cur.execute("""
                SELECT MAX(date) AS latest_date
                FROM sales_graphs
                WHERE restaurant_id = %s
            """, (restaurant_id,))
            latest = cur.fetchone()

            if not latest or not latest['latest_date']:
                logging.warning(f"No sales data found for restaurant_id: {restaurant_id}")
                return {"status": "error", "message": "No sales data available."}

            latest_date = latest['latest_date']
            start_date = latest_date - timedelta(days=6)

            # Get sales within last 7 days with all columns for analysis
            cur.execute("""
                SELECT *
                FROM sales_graphs
                WHERE restaurant_id = %s AND date BETWEEN %s AND %s
            """, (restaurant_id, start_date, latest_date))
            rows = cur.fetchall()

            if not rows:
                logging.warning(f"No sales data found for restaurant_id: {restaurant_id} in last 7 days")
                return {"status": "error", "message": "No sales data available in the last week."}

            # Convert to DataFrame for analysis
            sales_df = pd.DataFrame(rows)

            # Get inventory data if available
            cur.execute("""
                SELECT *
                FROM inventory_graphs
                WHERE restaurant_id = %s
                ORDER BY date DESC
                LIMIT 100
            """, (restaurant_id,))
            inventory_rows = cur.fetchall()
            inventory_df = pd.DataFrame(inventory_rows) if inventory_rows else None

            # Get employee data if available
            cur.execute("""
                SELECT *
                FROM employee_graphs
                WHERE restaurant_id = %s
            """, (restaurant_id,))
            employee_rows = cur.fetchall()
            employee_df = pd.DataFrame(employee_rows) if employee_rows else None

            # Get menu data if available
            cur.execute("""
                SELECT *
                FROM menu_graphs
                WHERE restaurant_id = %s
            """, (restaurant_id,))
            menu_rows = cur.fetchall()
            menu_df = pd.DataFrame(menu_rows) if menu_rows else None

            # Calculate basic sales metrics
            total_revenue = 0
            item_counter = defaultdict(int)
            item_revenue = defaultdict(float)

            for row in rows:
                total_amount = float(row['total_amount'])
                subtotal = float(row['subtotal'])
                total_revenue += total_amount

                items = [i.strip() for i in str(row['items_sold']).split(';') if i.strip()]
                if not items:
                    continue

                item_price = subtotal / len(items) if items else 0
                for item in items:
                    item_counter[item] += 1
                    item_revenue[item] += item_price

            top_items = sorted(item_counter.items(), key=lambda x: x[1], reverse=True)[:4]
            top_items_summary = []

            for item, count in top_items:
                income = round(item_revenue[item], 2)
                expense = round(income * 0.6, 2)  # temporary 60% expense
                top_items_summary.append({
                    "item": item,
                    "quantity_sold": count,
                    "income": income,
                    "expense": expense,
                    "profit": round(income - expense, 2)
                })

            # Perform fraud detection and operational efficiency analysis
            # 1. Anomaly detection
            anomaly_results = fraud_detection.detect_sales_anomalies(sales_df)

            # 2. Operational efficiency analysis
            efficiency_results = fraud_detection.analyze_operational_efficiency(
                sales_df, inventory_df, employee_df
            )

            # 3. Fraud risk alerts
            fraud_alerts = fraud_detection.generate_fraud_risk_alerts(
                sales_df, employee_df
            )

            # 4. Root cause analysis
            root_causes = fraud_detection.perform_root_cause_analysis(
                anomaly_results, sales_df, inventory_df, employee_df
            )

            # 5. Visual insight dashboard
            dashboard_data = fraud_detection.generate_visual_insight_dashboard(
                anomaly_results, efficiency_results, fraud_alerts, root_causes
            )

            # 6. Generate notifications for the restaurant owner/manager
            analysis_results = {
                "fraud_detection": {
                    "anomalies": anomaly_results,
                    "fraud_alerts": fraud_alerts,
                    "root_causes": root_causes
                },
                "operational_efficiency": efficiency_results
            }

            notification_counts = await process_fraud_and_efficiency_notifications(
                user_id=current_user["id"],
                restaurant_id=restaurant_id,
                restaurant_name=restaurant_name,
                analysis_results=analysis_results,
                conn=conn
            )

            return {
                "status": "success",
                "restaurant": restaurant_name,
                "total_revenue": round(total_revenue, 2),
                "top_4_items": top_items_summary,
                "period": {
                    "from": str(start_date),
                    "to": str(latest_date)
                },
                "fraud_detection": {
                    "anomalies": anomaly_results,
                    "fraud_alerts": fraud_alerts,
                    "root_causes": root_causes
                },
                "operational_efficiency": efficiency_results,
                "visual_insights": dashboard_data,
                "notifications_created": notification_counts
            }

    except Exception as e:
        logging.error(f"Error in sales summary for restaurant '{restaurant_name}': {e}")
        return {"status": "error", "message": str(e)}


async def get_all_restaurant_summaries(current_user: dict, conn) -> dict:
    """
    Get a summary of fraud detection and operational efficiency metrics for all restaurants
    the user has access to.

    Args:
        current_user: Current user information
        conn: Database connection

    Returns:
        Dictionary containing summaries for all accessible restaurants
    """
    import psycopg2.extras
    from src.fraud_detection_operational_efficiency import FraudDetectionOperationalEfficiency

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Get all restaurants the user has access to
            if current_user["role"] == "Super Admin":
                # Super admins can access all restaurants
                cur.execute("""
                    SELECT r.id, r.name
                    FROM restaurants r
                    WHERE r.active = true
                    ORDER BY r.name
                """)
            elif current_user["role"] == "Restaurant Owner":
                # Restaurant owners can only access their own restaurants
                cur.execute("""
                    SELECT r.id, r.name
                    FROM restaurants r
                    WHERE r.active = true AND r.created_by = %s
                    ORDER BY r.name
                """, (current_user["id"],))
            else:
                # Regional and Restaurant managers can only access assigned restaurants
                cur.execute("""
                    SELECT r.id, r.name
                    FROM restaurants r
                    JOIN restaurant_assignments ra ON r.id = ra.restaurant_id
                    WHERE r.active = true AND ra.manager_id = %s
                    ORDER BY r.name
                """, (current_user["id"],))

            restaurants = cur.fetchall()

            if not restaurants:
                return {
                    "status": "error",
                    "message": "No restaurants found or you don't have access to any restaurants"
                }

            # Initialize fraud detection analyzer
            fraud_detection = FraudDetectionOperationalEfficiency(memory_storage_path="cortex_memory")

            # Prepare results container
            summaries = []

            # Get summary for each restaurant
            for restaurant in restaurants:
                restaurant_id = restaurant['id']
                restaurant_name = restaurant['name']

                # Get latest sales data for the restaurant
                cur.execute("""
                    SELECT *
                    FROM sales_graphs
                    WHERE restaurant_id = %s
                    ORDER BY date DESC
                    LIMIT 100
                """, (restaurant_id,))

                sales_rows = cur.fetchall()

                if not sales_rows:
                    # Skip restaurants with no sales data
                    summaries.append({
                        "restaurant_id": restaurant_id,
                        "restaurant_name": restaurant_name,
                        "status": "no_data",
                        "message": "No sales data available"
                    })
                    continue

                # Convert to DataFrame for analysis
                import pandas as pd
                sales_df = pd.DataFrame(sales_rows)

                # Perform quick analysis
                try:
                    # 1. Anomaly detection
                    anomaly_results = fraud_detection.detect_sales_anomalies(sales_df)

                    # 2. Fraud risk alerts
                    fraud_alerts = fraud_detection.generate_fraud_risk_alerts(sales_df)

                    # Add summary to results
                    summaries.append({
                        "restaurant_id": restaurant_id,
                        "restaurant_name": restaurant_name,
                        "status": "success",
                        "anomaly_count": anomaly_results.get("anomaly_count", 0),
                        "alert_count": fraud_alerts.get("alert_count", 0),
                        "total_revenue": sales_df['total_amount'].sum() if 'total_amount' in sales_df.columns else 0,
                        "transaction_count": len(sales_df),
                        "latest_date": str(sales_df['date'].max()) if 'date' in sales_df.columns else None
                    })
                except Exception as e:
                    import logging
                    logging.error(f"Error analyzing restaurant {restaurant_name}: {e}")
                    summaries.append({
                        "restaurant_id": restaurant_id,
                        "restaurant_name": restaurant_name,
                        "status": "error",
                        "message": str(e)
                    })

            return {
                "status": "success",
                "restaurant_count": len(restaurants),
                "summaries": summaries
            }

    except Exception as e:
        import logging
        logging.error(f"Error in get_all_restaurant_summaries: {e}")
        return {"status": "error", "message": str(e)}


async def get_kpi_metrics(restaurant_name: str, current_user: dict, conn) -> dict:
    from src.File_upload import get_restaurant_id_by_name
    from collections import defaultdict
    import datetime

    restaurant_id = get_restaurant_id_by_name(restaurant_name)
    if not restaurant_id:
        return {"status": "error", "message": "Restaurant not found"}

    today = datetime.date.today()
    last_week = today - datetime.timedelta(days=7)

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT items_sold, number_of_items, subtotal, total_amount
                FROM sales_graphs
                WHERE restaurant_id = %s AND date >= %s
            """, (restaurant_id, last_week))

            rows = cur.fetchall()

        item_sales = defaultdict(int)
        item_revenue = defaultdict(float)

        for row in rows:
            items = [i.strip() for i in str(row[0]).split(';') if i.strip()]
            count = int(row[1])
            subtotal = float(row[2])
            total_amount = float(row[3])

            item_price = subtotal / len(items) if items else 0
            for item in items:
                item_sales[item] += 1
                item_revenue[item] += item_price

        top_items = sorted(item_sales.items(), key=lambda x: x[1], reverse=True)[:5]

        top_items_summary = [
            {
                "item": item,
                "quantity_sold": quantity,
                "revenue": round(item_revenue[item], 2),
                "profit_margin": round(item_revenue[item] * 0.3, 2),  # Dummy 30% profit margin
                "cost": round(item_revenue[item] * 0.7, 2),
                "contribution_margin": round(item_revenue[item] - (item_revenue[item] * 0.7), 2)
            }
            for item, quantity in top_items
        ]

        return {
            "status": "success",
            "restaurant": restaurant_name,
            "top_selling_items": top_items_summary,
            "kpi_info": {
                "generated_at": str(datetime.datetime.now())
            }
        }

    except Exception as e:
        logging.error(f"Error generating KPI metrics: {e}")
        return {"status": "error", "message": str(e)}


class RestaurantKPIs:
    def __init__(self, conn):
        self.conn = conn

    def get_all_kpis(self, restaurant_id: int) -> dict:
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT date, time, items_sold, subtotal, total_amount, number_of_items, sale_id
                    FROM sales_graphs
                    WHERE restaurant_id = %s
                """, (restaurant_id,))
                sales_data = cur.fetchall()

                cur.execute("""
                    SELECT ingredient, quantity, unit_cost, date
                    FROM inventory_graphs
                    WHERE restaurant_id = %s
                """, (restaurant_id,))
                inventory_data = cur.fetchall()

                cur.execute("""
                    SELECT menu_item, ingredient, amount, unit_cost, created_at
                    FROM menu_graphs
                    WHERE restaurant_id = %s
                """, (restaurant_id,))
                menu_data = cur.fetchall()

            if not sales_data:
                return {"status": "error", "message": "No sales data found."}

            sales_df = pd.DataFrame(sales_data)
            sales_df['date'] = pd.to_datetime(sales_df['date'])
            sales_df['subtotal'] = sales_df['subtotal'].apply(float)
            sales_df['total_amount'] = sales_df['total_amount'].apply(float)
            sales_df['number_of_items'] = sales_df['number_of_items'].astype(int)
            sales_df['day'] = sales_df['date'].dt.date
            sales_df['hour'] = pd.to_datetime(sales_df['time'].astype(str), errors='coerce').dt.hour

            menu_df = pd.DataFrame(menu_data)
            menu_df['created_at'] = pd.to_datetime(menu_df['created_at'])

            item_stats = defaultdict(lambda: {
                'sold': 0, 'revenue': 0, 'cost': 0, 'days': defaultdict(float), 'hours': defaultdict(float)
            })

            total_sales = 0
            item_sales = 0

            menu_cost_map = defaultdict(lambda: 0.0)
            ingredient_cost_map = defaultdict(lambda: 0.0)
            ingredient_quantity_map = defaultdict(lambda: 0.0)

            for row in menu_data:
                menu_cost_map[row['menu_item']] += float(row['amount'] or 0) * float(row['unit_cost'] or 0)

            for row in inventory_data:
                ingredient_cost_map[row['ingredient']] += float(row['quantity']) * float(row['unit_cost'] or 0)
                ingredient_quantity_map[row['ingredient']] += float(row['quantity'])

            for _, row in sales_df.iterrows():
                items = [i.strip() for i in row['items_sold'].split(';') if i.strip()]
                if not items:
                    continue
                per_item_price = row['subtotal'] / len(items)
                date_str = row['day'].strftime('%Y-%m-%d')

                for item in items:
                    cost = menu_cost_map.get(item, 0.0)
                    item_stats[item]['sold'] += 1
                    item_stats[item]['revenue'] += per_item_price
                    item_stats[item]['cost'] += cost
                    item_stats[item]['days'][date_str] += per_item_price
                    item_stats[item]['hours'][row['hour']] += per_item_price
                    total_sales += 1
                    item_sales += per_item_price

            results = {
                "Top-Selling Menu Items": [],
                "Least Profitable Menu Items": [],
                "Contribution Margin": [],
                "Food Cost %": [],
                "Popularity vs Profitability": [],
                "Seasonal Performance": [],
                "Time-of-Day Trends": [],
                "Sales Ratio P-Mix": [],
                "Customer Pairing Trends": [],
                "Item Void and Comp Report": [],
                "Avg Check Impact": [],
                "Dish-Level Waste": [],
                "COGS by Category": [],
                "Inventory Depletion": [],
                "Daily Specials Performance": [],
                "Upselling Success Rates": [],
                "Menu Revision Tracker": [],
                "Allergen-Free Sales": [],
                "ROI on Promotions": [],
            }

            for item, stats in item_stats.items():
                revenue = stats['revenue']
                cost = stats['cost']
                sold = stats['sold']
                profit = revenue - cost
                margin = profit / revenue if revenue else 0
                food_cost_pct = cost / revenue if revenue else 0

                results["Top-Selling Menu Items"].append(
                    {"item": item, "units_sold": sold, "revenue": round(revenue, 2)})
                results["Least Profitable Menu Items"].append(
                    {"item": item, "profit_margin": round(margin, 2), "contribution_margin": round(profit, 2)})
                results["Contribution Margin"].append({"item": item, "gross_profit": round(profit, 2)})
                results["Food Cost %"].append(
                    {"item": item, "food_cost_percent": round(food_cost_pct * 100, 2), "cost": round(cost, 2),
                     "price": round(revenue / sold if sold else 0, 2)})
                results["Popularity vs Profitability"].append(
                    {"item": item, "sales_volume": sold, "contribution_margin": round(profit, 2)})
                results["Time-of-Day Trends"].append({"item": item, "sales_by_hour": dict(stats['hours']),
                                                      "revenue_by_hour": {str(hour): round(val, 2) for hour, val in
                                                                          stats['hours'].items()}})
                results["Sales Ratio P-Mix"].append({"item": item, "sales_ratio": round((sold / total_sales) * 100, 2),
                                                     "contribution_margin": round(profit, 2)})

            if not sales_df.empty:
                avg_check = sales_df.groupby('sale_id').agg({'total_amount': 'sum'}).mean()['total_amount']
                results["Avg Check Impact"].append({"average_check": round(avg_check, 2)})

                # Upselling Success Rates: Average items per check
                upsell_rate = sales_df['number_of_items'].mean()
                results["Upselling Success Rates"].append({"avg_items_per_check": round(upsell_rate, 2)})

                # Daily Specials Performance: match "special" keyword in items_sold
                specials = sales_df[sales_df['items_sold'].str.contains('special', case=False, na=False)]
                if not specials.empty:
                    specials_summary = specials.groupby('day').agg({'total_amount': 'sum'}).reset_index()
                    results["Daily Specials Performance"] = specials_summary.to_dict(orient='records')

            # COGS by Category
            ingredient_cogs = []
            for ingredient, total_cost in ingredient_cost_map.items():
                quantity = ingredient_quantity_map[ingredient]
                cogs = round(total_cost, 2)
                ingredient_cogs.append({"ingredient": ingredient, "cogs": cogs, "quantity_used": round(quantity, 2)})
            results["COGS by Category"] = ingredient_cogs

            # Inventory Depletion
            depletion = []
            for ingredient, quantity in ingredient_quantity_map.items():
                depletion.append({"ingredient": ingredient, "quantity_used": round(quantity, 2)})
            results["Inventory Depletion"] = depletion

            # Menu Revision Tracker
            menu_changes = menu_df.groupby(['menu_item', 'ingredient']).agg(
                {"created_at": ["min", "max"]}).reset_index()
            menu_changes.columns = ['menu_item', 'ingredient', 'first_seen', 'last_seen']
            menu_changes['changed'] = menu_changes['first_seen'] != menu_changes['last_seen']
            results["Menu Revision Tracker"] = menu_changes[menu_changes['changed']].to_dict(orient='records')

            return {"status": "success", "data": results}

        except Exception as e:
            logging.error(f"Error generating KPIs: {e}")
            return {"status": "error", "message": str(e)}

    def get_inventory_recipe_kpis(self, restaurant_id: int) -> dict:
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Load sales data
                cur.execute("""
                    SELECT items_sold, subtotal, date FROM sales_graphs
                    WHERE restaurant_id = %s
                """, (restaurant_id,))
                sales_data = cur.fetchall()

                # Load menu data
                cur.execute("""
                    SELECT menu_item, ingredient, amount, unit_cost
                    FROM menu_graphs
                    WHERE restaurant_id = %s
                """, (restaurant_id,))
                menu_data = cur.fetchall()

                # Load inventory data
                cur.execute("""
                    SELECT ingredient, quantity, unit_cost
                    FROM inventory_graphs
                    WHERE restaurant_id = %s
                """, (restaurant_id,))
                inventory_data = cur.fetchall()

            if not sales_data or not menu_data:
                return {"status": "error", "message": "Insufficient data for KPI calculations."}

            # Convert to DataFrames
            sales_df = pd.DataFrame(sales_data)
            sales_df['date'] = pd.to_datetime(sales_df['date'])
            sales_df['subtotal'] = sales_df['subtotal'].astype(float)

            menu_df = pd.DataFrame(menu_data)
            inventory_df = pd.DataFrame(inventory_data)

            # Build cost map per item using menu graphs
            item_cost_map = defaultdict(float)
            cogs_by_category = defaultdict(float)

            for _, row in menu_df.iterrows():
                cost = float(row['amount'] or 0) * float(row['unit_cost'] or 0)
                item_cost_map[row['menu_item']] += cost
                cogs_by_category[row['ingredient']] += cost  # Approx for ingredient-based category

            # Initialize KPI containers
            item_stats = defaultdict(lambda: {'revenue': 0, 'cost': 0, 'units_sold': 0})
            inventory_depletion = defaultdict(float)

            for _, row in sales_df.iterrows():
                items = [i.strip() for i in row['items_sold'].split(';') if i.strip()]
                if not items:
                    continue

                per_item_price = row['subtotal'] / len(items)
                for item in items:
                    item_stats[item]['revenue'] += per_item_price
                    item_stats[item]['cost'] += item_cost_map.get(item, 0)
                    item_stats[item]['units_sold'] += 1

                    # Track ingredient depletion
                    ingredients_used = menu_df[menu_df['menu_item'] == item]
                    for _, ing in ingredients_used.iterrows():
                        inventory_depletion[ing['ingredient']] += float(ing['amount'] or 0)

            results = {
                "Least Profitable Menu Items": [],
                "Contribution Margin per Menu Item": [],
                "Food Cost Percentage per Item": [],
                "Dish-Level Waste Metrics": [],  # From inventory over-usage
                "COGS by Category": [],
                "Inventory Depletion by Menu Item": [],
            }

            for item, stats in item_stats.items():
                revenue = stats['revenue']
                cost = stats['cost']
                units = stats['units_sold']
                profit = revenue - cost
                margin = profit / revenue if revenue else 0
                food_cost_pct = cost / revenue if revenue else 0

                results["Least Profitable Menu Items"].append({
                    "item": item,
                    "profit_margin": round(margin, 2),
                    "contribution_margin": round(profit, 2),
                })

                results["Contribution Margin per Menu Item"].append({
                    "item": item,
                    "gross_profit": round(profit, 2),
                    "units_sold": units
                })

                results["Food Cost Percentage per Item"].append({
                    "item": item,
                    "food_cost_percent": round(food_cost_pct * 100, 2),
                    "cost": round(cost, 2),
                    "revenue": round(revenue, 2)
                })

            # Dish-Level Waste = Ingredient quantity in inventory not used in matching sales
            for _, row in inventory_df.iterrows():
                ing = row['ingredient']
                stocked = float(row['quantity'] or 0)
                used = inventory_depletion.get(ing, 0)
                if used < stocked:
                    results["Dish-Level Waste Metrics"].append({
                        "ingredient": ing,
                        "stocked_quantity": stocked,
                        "used_quantity": used,
                        "waste": round(stocked - used, 2)
                    })

            for cat, val in cogs_by_category.items():
                results["COGS by Category"].append({
                    "ingredient": cat,
                    "cogs": round(val, 2)
                })

            for item in item_stats:
                ingredients = menu_df[menu_df['menu_item'] == item]
                usage = {}
                for _, ing in ingredients.iterrows():
                    usage[ing['ingredient']] = inventory_depletion.get(ing['ingredient'], 0)
                results["Inventory Depletion by Menu Item"].append({
                    "item": item,
                    "ingredients_used": usage
                })

            return {"status": "success", "data": results}

        except Exception as e:
            logging.error(f"Error in Inventory/Recipe KPIs: {e}")
            return {"status": "error", "message": str(e)}

    def get_essential_kpis(self, restaurant_id: int) -> dict:
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Load sales data
                cur.execute("""
                    SELECT items_sold, subtotal, total_amount, date, number_of_items
                    FROM sales_graphs
                    WHERE restaurant_id = %s
                """, (restaurant_id,))
                sales_data = cur.fetchall()

                # Load menu data
                cur.execute("""
                    SELECT menu_item, ingredient, amount, unit_cost
                    FROM menu_graphs
                    WHERE restaurant_id = %s
                """, (restaurant_id,))
                menu_data = cur.fetchall()

                # Load inventory data
                cur.execute("""
                    SELECT ingredient, quantity, unit_cost, is_low, par_level
                    FROM inventory_graphs
                    WHERE restaurant_id = %s
                """, (restaurant_id,))
                inventory_data = cur.fetchall()

                # Load employee data
                cur.execute("""
                    SELECT hourly_rate
                    FROM employee_graphs
                    WHERE restaurant_id = %s
                """, (restaurant_id,))
                employee_data = cur.fetchall()

            if not sales_data:
                return {"status": "error", "message": "No sales data found."}

            sales_df = pd.DataFrame(sales_data)
            sales_df['subtotal'] = sales_df['subtotal'].astype(float)
            sales_df['total_amount'] = sales_df['total_amount'].astype(float)
            sales_df['number_of_items'] = sales_df['number_of_items'].astype(int)

            # Menu cost map
            menu_df = pd.DataFrame(menu_data)
            item_cost_map = defaultdict(float)
            for _, row in menu_df.iterrows():
                item_cost_map[row['menu_item']] += float(row['amount'] or 0) * float(row['unit_cost'] or 0)

            # KPI Calculations
            total_revenue = sales_df['total_amount'].sum()
            avg_order_value = sales_df['total_amount'].mean()
            total_orders = len(sales_df)

            item_sales = defaultdict(lambda: {'revenue': 0, 'units': 0})
            for _, row in sales_df.iterrows():
                items = [i.strip() for i in row['items_sold'].split(';') if i.strip()]
                per_item_price = row['subtotal'] / len(items) if items else 0
                for item in items:
                    item_sales[item]['revenue'] += per_item_price
                    item_sales[item]['units'] += 1

            # Sort by revenue
            top_selling = sorted(item_sales.items(), key=lambda x: x[1]['units'], reverse=True)[:5]
            most_profitable = sorted(item_sales.items(), key=lambda x: x[1]['revenue'] - item_cost_map.get(x[0], 0),
                                     reverse=True)[:5]

            # Total COGS
            total_cogs = sum([
                item_cost_map.get(item, 0) * stats['units']
                for item, stats in item_sales.items()
            ])

            # Inventory value
            # Inventory value and low stock alerts
            inventory_df = pd.DataFrame(inventory_data)
            inventory_df['quantity'] = pd.to_numeric(inventory_df['quantity'], errors='coerce').fillna(0)
            inventory_df['unit_cost'] = pd.to_numeric(inventory_df['unit_cost'], errors='coerce').fillna(0)
            inventory_df['par_level'] = pd.to_numeric(inventory_df['par_level'], errors='coerce').fillna(0)

            inventory_value = (inventory_df['quantity'] * inventory_df['unit_cost']).sum()

            # Identify critically low inventory
            low_inventory_df = inventory_df[inventory_df['quantity'] <= inventory_df['par_level']]
            top_low_inventory = (
                low_inventory_df
                .sort_values('quantity')
                .head(10)
                .to_dict(orient='records')
            )

            # Labor cost approximation: Assuming 8h/day × total orders
            avg_hourly = np.mean(
                [float(e['hourly_rate']) for e in employee_data if e['hourly_rate']]) if employee_data else 0
            estimated_labor_cost = total_orders * 8 * avg_hourly

            gross_profit = total_revenue - total_cogs
            food_cost_pct = (total_cogs / total_revenue * 100) if total_revenue else 0
            labor_cost_pct = (estimated_labor_cost / total_revenue * 100) if total_revenue else 0

            return {
                "status": "success",
                "data": {
                    "Total Revenue": round(total_revenue, 2),
                    "Average Order Value": round(avg_order_value, 2),
                    "Top Selling Items": [{"item": k, "units_sold": v["units"], "revenue": round(v["revenue"], 2)} for
                                          k, v in top_selling],
                    "Most Profitable Items": [{"item": k, "profit": round(v["revenue"] - item_cost_map.get(k, 0), 2)}
                                              for k, v in most_profitable],
                    "Total COGS": round(total_cogs, 2),
                    "Gross Profit": round(gross_profit, 2),
                    "Food Cost Percentage": round(food_cost_pct, 2),
                    "Labor Cost Percentage": round(labor_cost_pct, 2),
                    "Inventory Stock Value": round(inventory_value, 2),
                    "Low Inventory Alerts": top_low_inventory,
                }
            }

        except Exception as e:
            logging.error(f"Essential KPI error: {e}")
            return {"status": "error", "message": str(e)}

    def get_all_combined_kpis(self, restaurant_name: str) -> dict:
        """
        Combines all KPIs from get_all_kpis, get_inventory_recipe_kpis, and get_essential_kpis
        in a single function with optimized database queries.

        Args:
            restaurant_name: The name of the restaurant to get KPIs for

        Returns:
            A dictionary with status and combined KPI data
        """
        from File_upload import get_restaurant_id_by_name
        import numpy as np

        restaurant_id = get_restaurant_id_by_name(restaurant_name)
        try:
            # Fetch all required data with a single query per table
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Load sales data with all needed fields
                cur.execute("""
                    SELECT date, time, items_sold, subtotal, total_amount, number_of_items, sale_id, order_type, payment_method
                    FROM sales_graphs
                    WHERE restaurant_id = %s
                """, (restaurant_id,))
                sales_data = cur.fetchall()

                # Load inventory data with all needed fields
                cur.execute("""
                    SELECT ingredient, quantity, unit_cost, date, is_low, par_level
                    FROM inventory_graphs
                    WHERE restaurant_id = %s
                """, (restaurant_id,))
                inventory_data = cur.fetchall()

                # Load menu data with all needed fields
                cur.execute("""
                    SELECT menu_item, ingredient, amount, unit_cost, created_at
                    FROM menu_graphs
                    WHERE restaurant_id = %s
                """, (restaurant_id,))
                menu_data = cur.fetchall()

                # Load employee data
                cur.execute("""
                    SELECT hourly_rate
                    FROM employee_graphs
                    WHERE restaurant_id = %s
                """, (restaurant_id,))
                employee_data = cur.fetchall()

            # Check if we have enough data
            if not sales_data:
                return {"status": "error", "message": "No sales data found."}

            # Convert to DataFrames and preprocess
            sales_df = pd.DataFrame(sales_data)
            sales_df['date'] = pd.to_datetime(sales_df['date'])
            sales_df['subtotal'] = sales_df['subtotal'].apply(float)
            sales_df['total_amount'] = sales_df['total_amount'].apply(float)
            sales_df['number_of_items'] = sales_df['number_of_items'].astype(int)
            sales_df['day'] = sales_df['date'].dt.date
            sales_df['hour'] = pd.to_datetime(sales_df['time'].astype(str), errors='coerce').dt.hour

            menu_df = pd.DataFrame(menu_data)
            if not menu_df.empty:
                menu_df['created_at'] = pd.to_datetime(menu_df['created_at'])

            inventory_df = pd.DataFrame(inventory_data)
            if not inventory_df.empty:
                inventory_df['quantity'] = pd.to_numeric(inventory_df['quantity'], errors='coerce').fillna(0)
                inventory_df['unit_cost'] = pd.to_numeric(inventory_df['unit_cost'], errors='coerce').fillna(0)
                inventory_df['par_level'] = pd.to_numeric(inventory_df['par_level'], errors='coerce').fillna(0)
                inventory_df['date'] = pd.to_datetime(inventory_df['date'])

            # Initialize data structures for KPI calculations
            item_stats = defaultdict(lambda: {
                'sold': 0, 'revenue': 0, 'cost': 0, 'days': defaultdict(float), 'hours': defaultdict(float)
            })

            total_sales = 0
            item_sales = 0

            # Build cost maps
            menu_cost_map = defaultdict(lambda: 0.0)
            ingredient_cost_map = defaultdict(lambda: 0.0)
            ingredient_quantity_map = defaultdict(lambda: 0.0)

            for _, row in menu_df.iterrows():
                menu_cost_map[row['menu_item']] += float(row['amount'] or 0) * float(row['unit_cost'] or 0)

            for _, row in inventory_df.iterrows():
                ingredient_cost_map[row['ingredient']] += float(row['quantity']) * float(row['unit_cost'] or 0)
                ingredient_quantity_map[row['ingredient']] += float(row['quantity'])

            # Track inventory depletion
            inventory_depletion = defaultdict(float)

            # Process sales data
            for _, row in sales_df.iterrows():
                items = [i.strip() for i in str(row['items_sold']).split(';') if i.strip()]
                if not items:
                    continue

                per_item_price = row['subtotal'] / len(items)
                date_str = row['day'].strftime('%Y-%m-%d')

                for item in items:
                    cost = menu_cost_map.get(item, 0.0)
                    item_stats[item]['sold'] += 1
                    item_stats[item]['revenue'] += per_item_price
                    item_stats[item]['cost'] += cost
                    item_stats[item]['days'][date_str] += per_item_price
                    item_stats[item]['hours'][row['hour']] += per_item_price
                    total_sales += 1
                    item_sales += per_item_price

                    # Track ingredient depletion for this item
                    ingredients_used = menu_df[menu_df['menu_item'] == item]
                    for _, ing in ingredients_used.iterrows():
                        inventory_depletion[ing['ingredient']] += float(ing['amount'] or 0)

            # Calculate essential KPIs
            total_revenue = sales_df['total_amount'].sum()
            avg_order_value = sales_df['total_amount'].mean()
            total_orders = len(sales_df)

            # Calculate total COGS
            total_cogs = sum([
                item_stats[item]['cost'] * item_stats[item]['sold']
                for item in item_stats
            ])

            # Calculate inventory value
            inventory_value = (
                        inventory_df['quantity'] * inventory_df['unit_cost']).sum() if not inventory_df.empty else 0

            # Identify critically low inventory
            low_inventory_df = inventory_df[
                inventory_df['quantity'] <= inventory_df['par_level']] if not inventory_df.empty else pd.DataFrame()
            top_low_inventory = (
                low_inventory_df
                .sort_values('quantity')
                .head(10)
                .to_dict(orient='records')
            ) if not low_inventory_df.empty else []

            # Labor cost approximation
            avg_hourly = np.mean(
                [float(e['hourly_rate']) for e in employee_data if e['hourly_rate']]) if employee_data else 0
            estimated_labor_cost = total_orders * 8 * avg_hourly

            # Calculate profit metrics
            gross_profit = total_revenue - total_cogs
            food_cost_pct = (total_cogs / total_revenue * 100) if total_revenue else 0
            labor_cost_pct = (estimated_labor_cost / total_revenue * 100) if total_revenue else 0

            # Sort items for various KPIs
            top_selling = sorted(
                [(item, {'units': stats['sold'], 'revenue': stats['revenue']})
                 for item, stats in item_stats.items()],
                key=lambda x: x[1]['units'],
                reverse=True
            )[:5]

            most_profitable = sorted(
                [(item, {'revenue': stats['revenue'], 'cost': stats['cost'], 'units': stats['sold']})
                 for item, stats in item_stats.items()],
                key=lambda x: x[1]['revenue'] - x[1]['cost'],
                reverse=True
            )[:5]

            # Initialize results dictionary with all KPIs
            results = {
                # From get_all_kpis
                "Top-Selling Menu Items": [],
                "Least Profitable Menu Items": [],
                "Contribution Margin": [],
                "Food Cost %": [],
                "Popularity vs Profitability": [],
                "Seasonal Performance": [],
                "Time-of-Day Trends": [],
                "Sales Ratio P-Mix": [],
                "Customer Pairing Trends": [],
                "Item Void and Comp Report": [],
                "Avg Check Impact": [],
                "Dish-Level Waste": [],
                "COGS by Category": [],
                "Inventory Depletion": [],
                "Daily Specials Performance": [],
                "Upselling Success Rates": [],
                "Menu Revision Tracker": [],
                "Allergen-Free Sales": [],
                "ROI on Promotions": [],

                # From get_inventory_recipe_kpis
                "Contribution Margin per Menu Item": [],
                "Food Cost Percentage per Item": [],
                "Dish-Level Waste Metrics": [],
                "Inventory Depletion by Menu Item": [],

                # From get_essential_kpis
                "Total Revenue": round(total_revenue, 2),
                "Average Order Value": round(avg_order_value, 2),
                "Top Selling Items": [{"item": k, "units_sold": v["units"], "revenue": round(v["revenue"], 2)} for k, v
                                      in top_selling],
                "Most Profitable Items": [{"item": k, "profit": round(v["revenue"] - v["cost"], 2)} for k, v in
                                          most_profitable],
                "Total COGS": round(total_cogs, 2),
                "Gross Profit": round(gross_profit, 2),
                "Food Cost Percentage": round(food_cost_pct, 2),
                "Labor Cost Percentage": round(labor_cost_pct, 2),
                "Inventory Stock Value": round(inventory_value, 2),
                "Low Inventory Alerts": top_low_inventory,
            }

            # Populate KPIs from item_stats
            for item, stats in item_stats.items():
                revenue = stats['revenue']
                cost = stats['cost']
                sold = stats['sold']
                profit = revenue - cost
                margin = profit / revenue if revenue else 0
                food_cost_pct = cost / revenue if revenue else 0

                # From get_all_kpis
                results["Top-Selling Menu Items"].append(
                    {"item": item, "units_sold": sold, "revenue": round(revenue, 2)})
                results["Least Profitable Menu Items"].append(
                    {"item": item, "profit_margin": round(margin, 2), "contribution_margin": round(profit, 2)})
                results["Contribution Margin"].append({"item": item, "gross_profit": round(profit, 2)})
                results["Food Cost %"].append(
                    {"item": item, "food_cost_percent": round(food_cost_pct * 100, 2), "cost": round(cost, 2),
                     "price": round(revenue / sold if sold else 0, 2)})
                results["Popularity vs Profitability"].append(
                    {"item": item, "sales_volume": sold, "contribution_margin": round(profit, 2)})
                results["Time-of-Day Trends"].append({"item": item, "sales_by_hour": dict(stats['hours']),
                                                      "revenue_by_hour": {str(hour): round(val, 2) for hour, val in
                                                                          stats['hours'].items()}})
                results["Sales Ratio P-Mix"].append({"item": item, "sales_ratio": round((sold / total_sales) * 100, 2),
                                                     "contribution_margin": round(profit, 2)})

                # From get_inventory_recipe_kpis
                results["Contribution Margin per Menu Item"].append({
                    "item": item,
                    "gross_profit": round(profit, 2),
                    "units_sold": sold
                })

                results["Food Cost Percentage per Item"].append({
                    "item": item,
                    "food_cost_percent": round(food_cost_pct * 100, 2),
                    "cost": round(cost, 2),
                    "revenue": round(revenue, 2)
                })

            # Additional KPIs from get_all_kpis
            if not sales_df.empty:
                avg_check = sales_df.groupby('sale_id').agg({'total_amount': 'sum'}).mean()['total_amount']
                results["Avg Check Impact"].append({"average_check": round(avg_check, 2)})

                # Upselling Success Rates: Average items per check
                upsell_rate = sales_df['number_of_items'].mean()
                results["Upselling Success Rates"].append({"avg_items_per_check": round(upsell_rate, 2)})

                # Daily Specials Performance: match "special" keyword in items_sold
                specials = sales_df[sales_df['items_sold'].str.contains('special', case=False, na=False)]
                if not specials.empty:
                    specials_summary = specials.groupby('day').agg({'total_amount': 'sum'}).reset_index()
                    results["Daily Specials Performance"] = specials_summary.to_dict(orient='records')

            # COGS by Category
            ingredient_cogs = []
            for ingredient, total_cost in ingredient_cost_map.items():
                quantity = ingredient_quantity_map[ingredient]
                cogs = round(total_cost, 2)
                ingredient_cogs.append({"ingredient": ingredient, "cogs": cogs, "quantity_used": round(quantity, 2)})
            results["COGS by Category"] = ingredient_cogs

            # Inventory Depletion
            depletion = []
            for ingredient, quantity in ingredient_quantity_map.items():
                depletion.append({"ingredient": ingredient, "quantity_used": round(quantity, 2)})
            results["Inventory Depletion"] = depletion

            # Menu Revision Tracker
            if not menu_df.empty:
                menu_changes = menu_df.groupby(['menu_item', 'ingredient']).agg(
                    {"created_at": ["min", "max"]}).reset_index()
                menu_changes.columns = ['menu_item', 'ingredient', 'first_seen', 'last_seen']
                menu_changes['changed'] = menu_changes['first_seen'] != menu_changes['last_seen']
                results["Menu Revision Tracker"] = menu_changes[menu_changes['changed']].to_dict(orient='records')

            # Dish-Level Waste = Ingredient quantity in inventory not used in matching sales
            for _, row in inventory_df.iterrows():
                ing = row['ingredient']
                stocked = float(row['quantity'] or 0)
                used = inventory_depletion.get(ing, 0)
                if used < stocked:
                    results["Dish-Level Waste Metrics"].append({
                        "ingredient": ing,
                        "stocked_quantity": stocked,
                        "used_quantity": used,
                        "waste": round(stocked - used, 2)
                    })

            # Inventory Depletion by Menu Item
            for item in item_stats:
                ingredients = menu_df[menu_df['menu_item'] == item]
                usage = {}
                for _, ing in ingredients.iterrows():
                    usage[ing['ingredient']] = inventory_depletion.get(ing['ingredient'], 0)
                results["Inventory Depletion by Menu Item"].append({
                    "item": item,
                    "ingredients_used": usage
                })

            return {"status": "success", "data": results}

        except Exception as e:
            logging.error(f"Error generating combined KPIs: {e}")
            return {"status": "error", "message": str(e)}
