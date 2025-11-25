from fastapi import HTTPException, BackgroundTasks
import boto3
import os
import logging
import pandas as pd
import io
import asyncio
import time
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from collections import defaultdict
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from functools import partial
import math

from src.File_upload import verify_restaurant_access

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# AWS Configuration
BUCKET_NAME = "my-audio-demo"
UPLOAD_BASE_DIR = "uploads/restaurants"

# Initialize S3 client
s3_client = boto3.client(
    's3',
    region_name='us-east-1',
    aws_access_key_id='AKIA6G75DKGISWQMC7CR',
    aws_secret_access_key='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'
)

# Valid categories
VALID_CATEGORIES = ["Inventory", "Labor", "Sales", "Menu"]

# Determine optimal number of workers based on CPU cores
# Use N-1 cores to leave one for the main application
CPU_COUNT = max(1, mp.cpu_count() - 1)
logger.info(f"Using {CPU_COUNT} CPU cores for parallel processing")


def get_restaurant_folder_path(restaurant_name: str) -> str:
    """Create sanitized folder path for a restaurant"""
    # Sanitize restaurant name for folder name
    safe_name = restaurant_name.replace(" ", "_").lower()
    return f"{UPLOAD_BASE_DIR}/{safe_name}"


def get_user_restaurant_path(restaurant_name: str, user_id: int) -> str:
    """Get the S3 path for a user's restaurant folder"""
    restaurant_folder = get_restaurant_folder_path(restaurant_name)
    return f"{restaurant_folder}/user_{user_id}"


import json
from datetime import date, datetime


def custom_serializer(obj):
    """Custom serializer for non-serializable types like date."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()  # Convert date/datetime to ISO string
    raise TypeError(f"Type {type(obj)} not serializable")


def save_to_s3(bucket_name, key, data):
    """
    Save data as a JSON file to the given S3 bucket and key.
    """
    try:
        # Convert the data to JSON using custom serializer
        json_data = json.dumps(data, default=custom_serializer)

        # Save to S3
        s3_client.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=json_data,
            ContentType='application/json'
        )
        print(f"Data successfully saved to {bucket_name}/{key}")
    except Exception as e:
        print(f"Error saving data to S3: {e}")


# Example of usage
# your_data = your_dataframe_or_dict_with_dates
# save_to_s3('BUCKET_NAME', 'path/to/your/file.json', your_data)
from botocore.exceptions import ClientError


def load_file_from_s3(s3_key: str):
    """
    Fetch the content of a file from S3 and parse it as JSON.

    Args:
    - bucket_name: S3 bucket name
    - s3_key: S3 key (path to the file)

    Returns:
    - The parsed JSON data as a Python object, or None if there's an error.
    """
    # restaurant = await verify_restaurant_access(restaurant_name, current_user, conn)

    try:
        # Fetch the object from S3
        bucket_name = BUCKET_NAME  # Replace with your S3 bucket name
        response = s3_client.get_object(Bucket=bucket_name, Key=s3_key)

        # Check if the response contains the 'Body' attribute
        if 'Body' in response:
            # Read the content of the S3 object and parse it as JSON
            json_data = response['Body'].read().decode('utf-8')
            data = json.loads(json_data)
            return data
        else:
            print(f"Error: 'Body' not found in the S3 response for key: {s3_key}")
            return None

    except ClientError as e:
        # Catch and handle AWS ClientErrors
        print(f"Error loading file {s3_key} from S3: {e}")

        # Additional checks based on specific error codes
        if e.response['Error']['Code'] == 'NoSuchKey':
            print(f"Error: The specified key does not exist in the bucket: {s3_key}")
        elif e.response['Error']['Code'] == 'AccessDenied':
            print(f"Error: Access denied to the S3 object: {s3_key}")
        else:
            print(f"General ClientError: {e}")

        return None

    except Exception as e:
        # Catch any other exceptions
        print(f"Unexpected error: {e}")
        return None


class S3CSVProcessor:
    """
    Class for processing CSV files from S3 bucket for KPI generation.
    Uses multiprocessing for efficient data processing.
    """

    def __init__(self):
        self.executor = ProcessPoolExecutor(max_workers=CPU_COUNT)
        self.memory_cache = {}

    def __del__(self):
        """Clean up resources when the object is garbage collected"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)

    async def cleanup(self):
        """Explicitly clean up resources"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=True)
            logger.info("ProcessPoolExecutor shut down successfully")

    def _read_csv_from_s3(self, s3_key: str) -> pd.DataFrame:
        """
        Read a CSV file directly from S3 bucket.

        Args:
            s3_key: The S3 key of the CSV file

        Returns:
            DataFrame containing the CSV data
        """
        try:
            response = s3_client.get_object(Bucket=BUCKET_NAME, Key=s3_key)
            content = response['Body'].read()
            return pd.read_csv(io.BytesIO(content))
        except Exception as e:
            logger.error(f"Error reading CSV from S3 (key: {s3_key}): {e}")
            return pd.DataFrame()

    def _process_sales_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Process sales data with standard column transformations"""
        try:
            # Apply standard transformations



            # Rename columns to match the expected format
            column_mapping = {
                'Sale ID': 'sale_id',
                'Date': 'date',
                'Time': 'time',
                'Items Sold': 'items_sold',
                'Number of Items': 'number_of_items',
                'Subtotal': 'subtotal',
                'Tip': 'tip',
                'Total Amount': 'total_amount',
                'Employee ID': 'employee_id',
                'Is Loyalty Member': 'is_loyalty_member',
                'Promotion ID': 'promotion_id',
                'Discount Percent': 'discount_percent',
                'Order Type': 'order_type',
                'Payment Method': 'payment_method'
            }

            # Apply column renaming where columns exist
            for old_col, new_col in column_mapping.items():
                if old_col in df.columns:
                    df[new_col] = df[old_col]

            # Add derived columns
            df['day'] = df['date'].dt.date
            df['hour'] = pd.to_datetime(df['time'].astype(str), format='%H:%M:%S', errors='coerce').dt.hour

            return df
        except Exception as e:
            logger.error(f"Error processing sales data: {e}")
            return df

    def _process_inventory_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Process inventory data with standard column transformations"""
        try:
            # Apply standard transformations
            df['Date'] = pd.to_datetime(df['Date'], format='%m/%d/%y', errors='coerce')
            df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce')
            df['Par Level'] = pd.to_numeric(df['Par Level'], errors='coerce')
            df['Unit Cost'] = pd.to_numeric(df['Unit Cost'], errors='coerce')

            if 'Is Low' in df.columns:
                df['Is Low'] = df['Is Low'].astype(bool)

            # Rename columns to match the expected format
            column_mapping = {
                'Date': 'date',
                'Ingredient': 'ingredient',
                'Quantity': 'quantity',
                'Par Level': 'par_level',
                'Unit Cost': 'unit_cost',
                'Is Low': 'is_low'
            }

            # Apply column renaming where columns exist
            for old_col, new_col in column_mapping.items():
                if old_col in df.columns:
                    df[new_col] = df[old_col]

            return df
        except Exception as e:
            logger.error(f"Error processing inventory data: {e}")
            return df

    def _process_menu_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Process menu data with standard column transformations"""
        try:
            # Apply standard transformations
            df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce')
            df['Unit Cost'] = pd.to_numeric(df['Unit Cost'], errors='coerce')

            # Add created_at column if not present
            if 'Created At' not in df.columns:
                df['Created At'] = pd.Timestamp.now()

            # Rename columns to match the expected format
            column_mapping = {
                'Menu Item': 'menu_item',
                'Ingredient': 'ingredient',
                'Amount': 'amount',
                'Unit Cost': 'unit_cost',
                'Created At': 'created_at'
            }

            # Apply column renaming where columns exist
            for old_col, new_col in column_mapping.items():
                if old_col in df.columns:
                    df[new_col] = df[old_col]

            return df
        except Exception as e:
            logger.error(f"Error processing menu data: {e}")
            return df

    def _process_employee_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Process employee data with standard column transformations"""
        try:
            # Apply standard transformations
            if 'Hourly Rate' in df.columns:
                df['Hourly Rate'] = pd.to_numeric(df['Hourly Rate'], errors='coerce')

            # Rename columns to match the expected format
            column_mapping = {
                'Employee ID': 'employee_id',
                'Name': 'name',
                'Position': 'position',
                'Hourly Rate': 'hourly_rate',
                'Hours Worked': 'hours_worked'
            }

            # Apply column renaming where columns exist
            for old_col, new_col in column_mapping.items():
                if old_col in df.columns:
                    df[new_col] = df[old_col]

            return df
        except Exception as e:
            logger.error(f"Error processing employee data: {e}")
            return df

    async def get_restaurant_csv_files(self, restaurant_name: str, current_user: dict, conn) -> Dict[str, Any]:
        """
        Get all CSV files for a restaurant, organized by category.

        Args:
            restaurant_name: Name of the restaurant
            current_user: Current user information
            conn: Database connection

        Returns:
            Dictionary with CSV files organized by category
        """
        try:
            # Verify restaurant access
            restaurant = await verify_restaurant_access(restaurant_name, current_user)

            # Generate S3 path
            s3_folder = get_user_restaurant_path(restaurant_name, current_user["id"])

            # List objects in the folder
            response = s3_client.list_objects_v2(
                Bucket=BUCKET_NAME,
                Prefix=f"{s3_folder}/"
            )

            # Organize files by category
            files_by_category = {category: [] for category in VALID_CATEGORIES}

            if 'Contents' in response:
                for obj in response['Contents']:
                    # Skip folders themselves
                    if obj['Key'].endswith('/'):
                        continue

                    filename = os.path.basename(obj['Key'])

                    # Only include CSV files
                    if filename and filename.lower().endswith('.csv'):
                        # Extract category from path
                        path_parts = obj['Key'].split('/')
                        if len(path_parts) >= 2:
                            category = path_parts[-2]

                            # Only include files from valid categories
                            if category in VALID_CATEGORIES:
                                files_by_category[category].append({
                                    "filename": filename,
                                    "size": obj['Size'],
                                    "last_modified": obj['LastModified'].strftime("%Y-%m-%d %H:%M:%S"),
                                    "s3_key": obj['Key'],
                                    "category": category,
                                    "url": f"https://{BUCKET_NAME}.s3.amazonaws.com/{obj['Key']}"
                                })

            return {
                "restaurant": restaurant_name,
                "files_by_category": files_by_category,
                "total_count": sum(len(files) for files in files_by_category.values())
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting restaurant CSV files: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error retrieving CSV files: {e}"
            )

    async def load_category_data(self, restaurant_name: str, current_user: dict, conn, category: str) -> pd.DataFrame:
        """
        Load and combine all CSV files for a specific category.

        Args:
            restaurant_name: Name of the restaurant
            current_user: Current user information
            conn: Database connection
            category: Category of data to load (Sales, Inventory, Menu, Labor)

        Returns:
            Combined DataFrame with all data from the category
        """
        try:
            # Get all files for the restaurant
            files_info = await self.get_restaurant_csv_files(restaurant_name, current_user, conn)

            # Get files for the specified category
            category_files = files_info["files_by_category"].get(category, [])

            if not category_files:
                logger.warning(f"No {category} CSV files found for restaurant {restaurant_name}")
                return pd.DataFrame()

            # Use ThreadPoolExecutor for I/O-bound tasks (reading from S3)
            with ThreadPoolExecutor(max_workers=min(len(category_files), CPU_COUNT)) as executor:
                # Submit tasks to read all CSV files
                future_to_file = {
                    executor.submit(self._read_csv_from_s3, file_info["s3_key"]): file_info
                    for file_info in category_files
                }

                # Collect results
                dataframes = []
                for future in future_to_file:
                    try:
                        df = future.result()
                        if not df.empty:
                            dataframes.append(df)
                    except Exception as e:
                        file_info = future_to_file[future]
                        logger.error(f"Error processing {file_info['filename']}: {e}")

            if not dataframes:
                logger.warning(f"No valid data found in {category} CSV files for restaurant {restaurant_name}")
                return pd.DataFrame()

            # Combine all dataframes
            combined_df = pd.concat(dataframes, ignore_index=True)

            # Process data based on category
            if category == "Sales":
                return self._process_sales_data(combined_df)
            elif category == "Inventory":
                return self._process_inventory_data(combined_df)
            elif category == "Menu":
                return self._process_menu_data(combined_df)
            elif category == "Labor":
                return self._process_employee_data(combined_df)
            else:
                return combined_df

        except Exception as e:
            logger.error(f"Error loading {category} data: {e}")
            return pd.DataFrame()

    async def load_all_category_data(self, restaurant_name: str, current_user: dict, conn) -> Dict[str, pd.DataFrame]:
        """
        Load data from all categories in parallel.

        Args:
            restaurant_name: Name of the restaurant
            current_user: Current user information
            conn: Database connection

        Returns:
            Dictionary with DataFrames for each category
        """
        try:
            # Create tasks for loading each category
            tasks = []
            for category in VALID_CATEGORIES:
                task = asyncio.create_task(
                    self.load_category_data(restaurant_name, current_user, conn, category)
                )
                tasks.append((category, task))

            # Wait for all tasks to complete
            results = {}
            for category, task in tasks:
                try:
                    results[category] = await task
                except Exception as e:
                    logger.error(f"Error loading {category} data: {e}")
                    results[category] = pd.DataFrame()

            return results

        except Exception as e:
            logger.error(f"Error loading all category data: {e}")
            return {category: pd.DataFrame() for category in VALID_CATEGORIES}

    async def generate_kpis_from_s3(self, restaurant_name: str, current_user: dict, conn) -> Dict[str, Any]:
        """
        Generate KPIs from S3 CSV data for a restaurant.

        Args:

            restaurant_name: Name of the restaurant
            current_user: Current user information
            conn: Database connection

        Returns:
            Dictionary with KPI data based on available category data
        """
        start_time = time.time()
        logger.info(f"Starting KPI generation for restaurant {restaurant_name}")

        try:
            # Load all category data
            category_data = await self.load_all_category_data(restaurant_name, current_user, conn)

            # Extract dataframes
            sales_df = category_data.get("Sales", pd.DataFrame())
            inventory_df = category_data.get("Inventory", pd.DataFrame())
            menu_df = category_data.get("Menu", pd.DataFrame())
            employee_df = category_data.get("Labor", pd.DataFrame())

            # Track available categories
            available_categories = []
            if not sales_df.empty:
                available_categories.append("Sales")
            if not inventory_df.empty:
                available_categories.append("Inventory")
            if not menu_df.empty:
                available_categories.append("Menu")
            if not employee_df.empty:
                available_categories.append("Labor")

            logger.info(f"Available data categories: {available_categories}")
            from src.File_upload import get_restaurant_id_by_name

            restaurant_id = get_restaurant_id_by_name(
                restaurant_name)  # Replace with actual function to get restaurant ID

            # Use ThreadPoolExecutor for CPU-bound tasks (KPI calculations)
            with ThreadPoolExecutor(max_workers=CPU_COUNT) as executor:
                # Submit task to calculate KPIs
                future = executor.submit(
                    self._calculate_kpis_resilient,
                    sales_df.to_dict('records') if not sales_df.empty else [],
                    inventory_df.to_dict('records') if not inventory_df.empty else [],
                    menu_df.to_dict('records') if not menu_df.empty else [],
                    employee_df.to_dict('records') if not employee_df.empty else [],
                    available_categories
                )

                # Get results
                results = future.result()

                bucket_name = BUCKET_NAME  # Replace with your S3 bucket name
                # restaurant_id = 'resturant_id'  # Replace with the actual restaurant ID
                GRAPH_BASE_DIR = f'dashboard_graphs/{restaurant_id}/graph.json'  # Replace with your S3 key

                if results and restaurant_id:  # Save results to S3
                    save_to_s3(bucket_name, GRAPH_BASE_DIR, results)

            end_time = time.time()
            processing_time = end_time - start_time
            logger.info(f"KPI generation completed in {processing_time:.2f} seconds")
            if math.isnan(processing_time) or math.isinf(processing_time):
                processing_time = 3.0  # Or another fallback value

            return {
                "status": "success",
                "data": results,
                "available_categories": available_categories,
                "processing_time_seconds": round(processing_time, 2)
            }
        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Error generating KPIs from S3: {e}")
            return {"status": "error", "message": str(e)}

    def _calculate_kpis_resilient(self, sales_data, inventory_data, menu_data, employee_data, available_categories):
        """
        Calculate KPIs from the provided data with resilience to missing categories.
        This function runs in a separate process.

        Args:
            sales_data: List of sales records
            inventory_data: List of inventory records
            menu_data: List of menu records
            employee_data: List of employee records
            available_categories: List of available data categories

        Returns:
            Dictionary with KPI data based on available categories
        """
        try:
            # Initialize results dictionary with all possible KPIs
            results = self._initialize_kpi_results()

            # Convert to DataFrames
            sales_df = pd.DataFrame(sales_data)
            inventory_df = pd.DataFrame(inventory_data)
            menu_df = pd.DataFrame(menu_data)
            employee_df = pd.DataFrame(employee_data)

            # Process each category independently
            if "Sales" in available_categories:
                self._process_sales_kpis(sales_df, results)

            if "Inventory" in available_categories:
                self._process_inventory_kpis(inventory_df, results)

            if "Menu" in available_categories:
                self._process_menu_kpis(menu_df, results)

            if "Labor" in available_categories:
                self._process_labor_kpis(employee_df, results)

            # Process cross-category KPIs when multiple categories are available
            if "Sales" in available_categories and "Menu" in available_categories:
                self._process_sales_menu_kpis(sales_df, menu_df, results)

            if "Sales" in available_categories and "Inventory" in available_categories and "Menu" in available_categories:
                self._process_sales_inventory_menu_kpis(sales_df, inventory_df, menu_df, results)

            return results

        except Exception as e:
            logger.error(f"Error calculating KPIs: {e}")
            return self._initialize_kpi_results()

    def _initialize_kpi_results(self):
        """Initialize an empty results dictionary with all possible KPIs"""
        return {
            # Sales KPIs
            "Total Revenue": 0,
            "Average Order Value": 0,
            "Top Selling Items": [],
            "Avg Check Impact": [],
            "Upselling Success Rates": [],
            "Daily Specials Performance": [],
            "Time-of-Day Trends": [],
            "Sales Ratio P-Mix": [],

            # Inventory KPIs
            "Inventory Stock Value": 0,
            "Low Inventory Alerts": [],
            "Inventory Depletion": [],

            # Menu KPIs
            "Menu Revision Tracker": [],

            # Labor KPIs
            "Labor Cost Percentage": 0,

            # Cross-category KPIs (Sales + Menu)
            "Top-Selling Menu Items": [],
            "Most Profitable Items": [],
            "Least Profitable Menu Items": [],
            "Contribution Margin": [],
            "Food Cost %": [],
            "Popularity vs Profitability": [],
            "Contribution Margin per Menu Item": [],
            "Food Cost Percentage per Item": [],

            # Cross-category KPIs (Sales + Inventory + Menu)
            "Total COGS": 0,
            "Gross Profit": 0,
            "Food Cost Percentage": 0,
            "COGS by Category": [],
            "Dish-Level Waste Metrics": [],
            "Inventory Depletion by Menu Item": [],

            # Placeholder for other KPIs
            "Customer Pairing Trends": [],
            "Item Void and Comp Report": [],
            "Dish-Level Waste": [],
            "Allergen-Free Sales": [],
            "ROI on Promotions": [],
            "Seasonal Performance": [],
        }

    def _check_required_columns(self, df, required_columns, operation_name):
        """Check if DataFrame has all required columns"""
        if df.empty:
            return False

        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            logger.warning(f"Cannot perform {operation_name}: Missing columns {missing_columns}")
            return False
        return True

    def _process_sales_kpis(self, sales_df, results):
        """Process KPIs that only require sales data"""
        try:
            # Basic sales metrics
            if self._check_required_columns(sales_df, ['total_amount'], "basic sales metrics"):
                results["Total Revenue"] = round(sales_df['total_amount'].sum(), 2)
                results["Average Order Value"] = round(sales_df['total_amount'].mean(), 2)

            # Average check impact
            if self._check_required_columns(sales_df, ['sale_id', 'total_amount'], "average check calculation"):
                avg_check = sales_df.groupby('sale_id').agg({'total_amount': 'sum'}).mean()['total_amount']
                results["Avg Check Impact"] = [{"average_check": round(avg_check, 2)}]

            # Upselling metrics
            if self._check_required_columns(sales_df, ['number_of_items'], "upselling metrics"):
                upsell_rate = sales_df['number_of_items'].mean()
                results["Upselling Success Rates"] = [{"avg_items_per_check": round(upsell_rate, 2)}]

            # Daily specials
            if self._check_required_columns(sales_df, ['items_sold', 'day', 'total_amount'], "daily specials"):
                try:
                    specials = sales_df[sales_df['items_sold'].str.contains('special', case=False, na=False)]
                    if not specials.empty:
                        specials_summary = (
                            specials
                            .groupby('day')
                            .agg({'total_amount': 'sum'})
                            .reset_index()
                            .sort_values(by='total_amount', ascending=False)  # Sort by total_amount descending
                            .head(10)  # Keep top 10
                        )
                        results["Daily Specials Performance"] = specials_summary.to_dict(orient='records')
                except Exception as e:
                    logger.warning(f"Error processing daily specials: {e}")

            # Top selling items (simplified version without menu data)
            if self._check_required_columns(sales_df, ['items_sold'], "top selling items"):
                try:
                    # Extract all items from items_sold
                    all_items = []
                    for items_str in sales_df['items_sold'].dropna():
                        items = [item.strip() for item in str(items_str).split(';') if item.strip()]
                        all_items.extend(items)

                    # Count occurrences
                    item_counts = pd.Series(all_items).value_counts()
                    top_items = [{"item": item, "units_sold": count, "revenue": 0}
                                 for item, count in item_counts.head(5).items()]

                    results["Top Selling Items"] = top_items
                except Exception as e:
                    logger.warning(f"Error processing top selling items: {e}")

        except Exception as e:
            logger.error(f"Error in _process_sales_kpis: {e}")

    def _process_inventory_kpis(self, inventory_df, results):
        """Process KPIs that only require inventory data"""
        try:
            # Inventory value
            if self._check_required_columns(inventory_df, ['quantity', 'unit_cost'], "inventory value"):
                inventory_value = (inventory_df['quantity'] * inventory_df['unit_cost']).sum()
                results["Inventory Stock Value"] = round(inventory_value, 2)

            # Low inventory alerts
            if self._check_required_columns(inventory_df, ['quantity', 'par_level'], "low inventory alerts"):
                try:
                    low_inventory_df = inventory_df[inventory_df['quantity'] <= inventory_df['par_level']]
                    if not low_inventory_df.empty:
                        top_low_inventory = (
                            low_inventory_df
                            .sort_values('quantity')
                            .head(10)
                            .to_dict(orient='records')
                        )
                        results["Low Inventory Alerts"] = top_low_inventory
                except Exception as e:
                    logger.warning(f"Error processing low inventory alerts: {e}")

            # Basic inventory depletion (without sales data)
            if self._check_required_columns(inventory_df, ['ingredient', 'quantity'], "inventory depletion"):
                try:
                    ingredient_quantity_map = defaultdict(float)
                    for _, row in inventory_df.iterrows():
                        ingredient_quantity_map[row['ingredient']] += float(row['quantity'] or 0)

                    depletion = []
                    for ingredient, quantity in ingredient_quantity_map.items():
                        depletion.append({"ingredient": ingredient, "quantity_available": round(quantity, 2)})

                    results["Inventory Depletion"] = depletion
                except Exception as e:
                    logger.warning(f"Error processing inventory depletion: {e}")

        except Exception as e:
            logger.error(f"Error in _process_inventory_kpis: {e}")

    def _process_menu_kpis(self, menu_df, results):
        """Process KPIs that only require menu data"""
        try:
            # Menu revision tracker
            if self._check_required_columns(menu_df, ['menu_item', 'ingredient', 'created_at'],
                                            "menu revision tracker"):
                try:
                    menu_changes = menu_df.groupby(['menu_item', 'ingredient']).agg(
                        {"created_at": ["min", "max"]}).reset_index()
                    menu_changes.columns = ['menu_item', 'ingredient', 'first_seen', 'last_seen']
                    menu_changes['changed'] = menu_changes['first_seen'] != menu_changes['last_seen']
                    results["Menu Revision Tracker"] = menu_changes[menu_changes['changed']].to_dict(orient='records')
                except Exception as e:
                    logger.warning(f"Error processing menu revision tracker: {e}")

        except Exception as e:
            logger.error(f"Error in _process_menu_kpis: {e}")

    def _process_labor_kpis(self, employee_df, results):
        """Process KPIs that only require labor data"""
        try:
            # Basic labor metrics
            if self._check_required_columns(employee_df, ['hourly_rate'], "labor metrics"):
                try:
                    avg_hourly = employee_df['hourly_rate'].mean()
                    results["Labor Cost Percentage"] = round(avg_hourly, 2)
                except Exception as e:
                    logger.warning(f"Error processing labor metrics: {e}")

        except Exception as e:
            logger.error(f"Error in _process_labor_kpis: {e}")

    def _process_sales_menu_kpis(self, sales_df, menu_df, results):
        """Process KPIs that require both sales and menu data"""
        try:
            # Check required columns for sales-menu combined metrics
            if not self._check_required_columns(sales_df, ['items_sold', 'subtotal'], "sales-menu metrics"):
                return

            if not self._check_required_columns(menu_df, ['menu_item', 'amount', 'unit_cost'], "sales-menu metrics"):
                return

            try:
                # Build cost map from menu data
                menu_cost_map = defaultdict(float)
                for _, row in menu_df.iterrows():
                    if 'menu_item' in row and 'amount' in row and 'unit_cost' in row:
                        menu_cost_map[row['menu_item']] += float(row['amount'] or 0) * float(row['unit_cost'] or 0)

                # Initialize item stats
                item_stats = defaultdict(lambda: {
                    'sold': 0, 'revenue': 0, 'cost': 0, 'hours': defaultdict(float)
                })

                total_sales = 0

                # Process sales data
                for _, row in sales_df.iterrows():
                    if 'items_sold' not in row or 'subtotal' not in row:
                        continue

                    items = [i.strip() for i in str(row['items_sold']).split(';') if i.strip()]
                    if not items:
                        continue

                    per_item_price = row['subtotal'] / len(items)

                    for item in items:
                        cost = menu_cost_map.get(item, 0.0)
                        item_stats[item]['sold'] += 1
                        item_stats[item]['revenue'] += per_item_price
                        item_stats[item]['cost'] += cost

                        if 'hour' in row:
                            item_stats[item]['hours'][row['hour']] += per_item_price

                        total_sales += 1

                # Calculate KPIs from item_stats
                top_selling = sorted(
                    [(item, {'units': stats['sold'], 'revenue': stats['revenue']})
                     for item, stats in item_stats.items()],
                    key=lambda x: x[1]['units'],
                    reverse=True
                )[:5]

                top_selling_menu_items = sorted(
                    [(item, {'units': stats['sold'], 'revenue': stats['revenue'], 'cost': stats['cost']})
                     for item, stats in item_stats.items()],
                    key=lambda x: x[1]['units'],
                    reverse=True
                )[:15]

                under_performer_menu_items = sorted(
                    [(item, {'units': stats['sold'], 'revenue': stats['revenue'], 'cost': stats['cost']})
                     for item, stats in item_stats.items()],
                    key=lambda x: x[1]['units'],
                    reverse=False
                )[:15]

                most_profitable = sorted(
                    [(item, {'revenue': stats['revenue'], 'cost': stats['cost'], 'units': stats['sold']})
                     for item, stats in item_stats.items()],
                    key=lambda x: x[1]['revenue'] - x[1]['cost'],
                    reverse=True
                )[:5]

                # Update results
                results["Top Selling Items"] = [{"item": k, "units_sold": v["units"], "revenue": round(v["revenue"], 2)}
                                                for k, v in top_selling]
                results["Most Profitable Items"] = [{"item": k, "profit": round(v["revenue"] - v["cost"], 2)} for k, v
                                                    in most_profitable]

                results["Top-Selling Menu Items"] = [
                    {"item": k, "units_sold": v["units"], "revenue": round(v["revenue"], 2),
                     "cost": round(v["cost"], 2), "profit": round(v["revenue"] - v["cost"], 2)} for k, v in
                    top_selling_menu_items]
                results["Underperformer Menu Items"] = [
                    {"item": k, "units_sold": v["units"], "revenue": round(v["revenue"], 2),
                     "cost": round(v["cost"], 2), "profit": round(v["revenue"] - v["cost"], 2)} for k, v in
                    under_performer_menu_items]
                # Populate KPIs from item_stats
                for item, stats in item_stats.items():
                    revenue = stats['revenue']
                    cost = stats['cost']
                    sold = stats['sold']
                    profit = revenue - cost
                    margin = profit / revenue if revenue else 0
                    food_cost_pct = cost / revenue if revenue else 0

                    # Add to results
                    # results["Top-Selling Menu Items"].append({"item": item, "units_sold": sold, "revenue": round(revenue, 2)})
                    results["Least Profitable Menu Items"].append(
                        {"item": item, "profit_margin": round(margin, 2), "contribution_margin": round(profit, 2)})
                    results["Contribution Margin"].append({"item": item, "gross_profit": round(profit, 2)})
                    results["Food Cost %"].append(
                        {"item": item, "food_cost_percent": round(food_cost_pct * 100, 2), "cost": round(cost, 2),
                         "price": round(revenue / sold if sold else 0, 2)})
                    results["Popularity vs Profitability"].append(
                        {"item": item, "sales_volume": sold, "contribution_margin": round(profit, 2)})

                    if 'hours' in stats:
                        results["Time-of-Day Trends"].append({"item": item,
                                                              "revenue_by_hour": {str(hour): round(val, 2) for hour, val
                                                                                  in stats['hours'].items()}})

                    results["Sales Ratio P-Mix"].append(
                        {"item": item, "sales_ratio": round((sold / total_sales) * 100, 2) if total_sales else 0,
                         "contribution_margin": round(profit, 2)})

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

            except Exception as e:
                logger.warning(f"Error processing sales-menu metrics: {e}")

        except Exception as e:
            logger.error(f"Error in _process_sales_menu_kpis: {e}")

    def _process_sales_inventory_menu_kpis(self, sales_df, inventory_df, menu_df, results):
        """Process KPIs that require sales, inventory, and menu data"""
        try:
            # Check required columns
            if not self._check_required_columns(sales_df, ['total_amount', 'items_sold'],
                                                "sales-inventory-menu metrics"):
                return

            if not self._check_required_columns(inventory_df, ['ingredient', 'quantity', 'unit_cost'],
                                                "sales-inventory-menu metrics"):
                return

            if not self._check_required_columns(menu_df, ['menu_item', 'ingredient', 'amount', 'unit_cost'],
                                                "sales-inventory-menu metrics"):
                return

            try:
                # Build cost maps
                menu_cost_map = defaultdict(float)
                for _, row in menu_df.iterrows():
                    menu_cost_map[row['menu_item']] += float(row['amount'] or 0) * float(row['unit_cost'] or 0)

                ingredient_cost_map = defaultdict(float)
                ingredient_quantity_map = defaultdict(float)
                for _, row in inventory_df.iterrows():
                    ingredient_cost_map[row['ingredient']] += float(row['quantity']) * float(row['unit_cost'] or 0)
                    ingredient_quantity_map[row['ingredient']] += float(row['quantity'])

                # Initialize item stats
                item_stats = defaultdict(lambda: {
                    'sold': 0, 'revenue': 0, 'cost': 0
                })

                # Track inventory depletion
                inventory_depletion = defaultdict(float)

                # Process sales data
                for _, row in sales_df.iterrows():
                    items = [i.strip() for i in str(row['items_sold']).split(';') if i.strip()]
                    if not items:
                        continue

                    per_item_price = row['subtotal'] / len(items) if 'subtotal' in row else 0

                    for item in items:
                        cost = menu_cost_map.get(item, 0.0)
                        item_stats[item]['sold'] += 1
                        item_stats[item]['revenue'] += per_item_price
                        item_stats[item]['cost'] += cost

                        # Track ingredient depletion for this item
                        ingredients_used = menu_df[menu_df['menu_item'] == item]
                        for _, ing in ingredients_used.iterrows():
                            inventory_depletion[ing['ingredient']] += float(ing['amount'] or 0)

                # Calculate total COGS
                total_cogs = sum([
                    item_stats[item]['cost'] * item_stats[item]['sold']
                    for item in item_stats
                ])

                # Calculate profit metrics
                total_revenue = sales_df['total_amount'].sum()
                gross_profit = total_revenue - total_cogs
                food_cost_pct = (total_cogs / total_revenue * 100) if total_revenue else 0

                # Update results
                results["Total COGS"] = round(total_cogs, 2)
                results["Gross Profit"] = round(gross_profit, 2)
                results["Food Cost Percentage"] = round(food_cost_pct, 2)

                # COGS by Category
                ingredient_cogs = []
                for ingredient, total_cost in ingredient_cost_map.items():
                    quantity = ingredient_quantity_map[ingredient]
                    cogs = round(total_cost, 2)
                    ingredient_cogs.append(
                        {"ingredient": ingredient, "cogs": cogs, "quantity_used": round(quantity, 2)})
                results["COGS by Category"] = ingredient_cogs

                # Dish-Level Waste
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

            except Exception as e:
                logger.warning(f"Error processing sales-inventory-menu metrics: {e}")

        except Exception as e:
            logger.error(f"Error in _process_sales_inventory_menu_kpis: {e}")

    def _calculate_kpis(self, sales_data, inventory_data, menu_data, employee_data):
        """
        Legacy method for backward compatibility.
        Delegates to the new resilient implementation.
        """
        available_categories = []
        if sales_data:
            available_categories.append("Sales")
        if inventory_data:
            available_categories.append("Inventory")
        if menu_data:
            available_categories.append("Menu")
        if employee_data:
            available_categories.append("Labor")

        return self._calculate_kpis_resilient(sales_data, inventory_data, menu_data, employee_data,
                                              available_categories)


class RestaurantCSVManager:
    def __init__(self, restaurant_name: str):
        self.restaurant_name = restaurant_name
        self.s3_folder = f"restaurants/{restaurant_name}/combined_data/"
        self.combined_csv_key = f"{self.s3_folder}combined_data.csv"

    async def process_uploaded_file_and_save_to_s3(self, processed_df: pd.DataFrame, filename: str) -> Dict[str, Any]:
        """
        Process an uploaded file, append to the combined CSV for the restaurant,
        and save the updated CSV back to S3.
        """
        # try:
        # Step 1: Read the uploaded file into a DataFrame
        # In case the file reading is involved (currently commented out)
        # await file_data.seek(0)
        # contents = await file_data.read()
        # uploaded_df = pd.read_csv(io.BytesIO(contents))

        # uploaded_df = pd.read_csv(io.BytesIO(file_data))

        # Step 2: Process the file based on its category (Sales, Inventory, Menu, Labor)
        # processed_df = self._process_file_by_category(uploaded_df, category)

        # Step 3: Fetch the existing combined CSV
        try:
            combined_df = self._get_combined_csv()
        except Exception as e:
            logger.error(f"Failed to fetch combined CSV: {e}")
            return {"error": "Failed to fetch combined CSV", "message": str(e)}

        # Step 4: Add a 'filename' column to track the source of the data (for future deletions)
        try:
            processed_df['filename'] = filename
        except Exception as e:
            logger.error(f"Failed to add filename column: {e}")
            return {"error": "Failed to add filename column", "message": str(e)}

        # Step 5: Append the new data to the combined DataFrame
        try:
            combined_df = pd.concat([combined_df, processed_df], ignore_index=True)
        except Exception as e:
            logger.error(f"Failed to append data to combined DataFrame: {e}")
            return {"error": "Failed to append data", "message": str(e)}

        # Step 6: Save the updated combined DataFrame back to S3
        try:
            await self._save_combined_csv(combined_df)
        except Exception as e:
            logger.error(f"Failed to save combined CSV to S3: {e}")
            return {"error": "Failed to save CSV to S3", "message": str(e)}

        logger.info("CSV file processed for graphs and saved to combined CSV")

        return True

        # Step 7: Return KPIs based on the updated combined DataFrame
        # try:
        #     return await self._calculate_kpis_from_combined_df(combined_df)
        # except Exception as e:
        #     logger.error(f"Failed to calculate KPIs: {e}")
        #     return {"error": "Failed to calculate KPIs", "message": str(e)}

    def _process_file_by_category(self, df: pd.DataFrame, category: str) -> pd.DataFrame:
        """Process the file data based on its category."""

        s3csv = S3CSVProcessor()

        if category == "Sales":
            return s3csv._process_sales_data(df)
        elif category == "Inventory":
            return s3csv._process_inventory_data(df)
        elif category == "Menu":
            return s3csv._process_menu_data(df)
        elif category == "Labor":
            return s3csv._process_employee_data(df)
        else:
            return df  # In case of an unknown category

    async def _save_combined_csv(self, combined_df: pd.DataFrame):
        """Save the combined DataFrame back to S3."""
        try:
            csv_buffer = io.StringIO()
            combined_df.to_csv(csv_buffer, index=False)
            s3_client.put_object(Bucket=BUCKET_NAME, Key=self.combined_csv_key, Body=csv_buffer.getvalue())
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error saving combined CSV for {self.restaurant_name}: {e}")

    def _get_combined_csv(self) -> pd.DataFrame:
        """Fetch the combined CSV from S3 for a specific restaurant."""
        try:
            # Create an S3 client using boto3
            # s3_client = boto3.client('s3')

            # Try to get the object from S3
            response = s3_client.get_object(Bucket=BUCKET_NAME, Key=self.combined_csv_key)
            content = response['Body'].read()

            # Convert the binary content to a pandas DataFrame
            return pd.read_csv(io.BytesIO(content))

        except ClientError as e:
            # Log the error if the object doesn't exist or there is an access issue
            logger.error(f"Error fetching the combined CSV from S3: {e}")
            # Check if it's a 'NoSuchKey' error (indicating the file doesn't exist)
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.info(f"CSV not found in S3 bucket. Returning an empty DataFrame.")
            return pd.DataFrame()

        except Exception as e:
            # Catch any other unexpected errors
            logger.error(f"Unexpected error occurred while fetching CSV: {e}")
            return pd.DataFrame()


async def list_csv_files_only(
        restaurant_name: str,
        current_user: dict,
        conn
) -> Dict[str, Any]:
    """List only CSV files for a restaurant in S3"""
    try:
        # Verify restaurant access
        restaurant = await verify_restaurant_access(restaurant_name, current_user)

        # Generate S3 path without category
        s3_folder = get_user_restaurant_path(restaurant_name, current_user["id"])

        # List objects in the folder
        try:
            response = s3_client.list_objects_v2(
                Bucket=BUCKET_NAME,
                Prefix=f"{s3_folder}/"
            )

            csv_files = []

            if 'Contents' in response:
                for obj in response['Contents']:
                    # Skip folders themselves
                    if obj['Key'].endswith('/'):
                        continue

                    filename = os.path.basename(obj['Key'])

                    # Only include CSV files
                    if filename and filename.lower().endswith('.csv'):
                        csv_files.append({
                            "filename": filename,
                            "size": obj['Size'],
                            "last_modified": obj['LastModified'].strftime("%Y-%m-%d %H:%M:%S"),
                            "s3_key": obj['Key'],
                            "category": str(obj['Key']).split("/")[-2],
                            "url": f"https://{BUCKET_NAME}.s3.amazonaws.com/{obj['Key']}"
                        })

            return {
                "restaurant": restaurant_name,
                "files": csv_files,
                "count": len(csv_files)
            }

        except Exception as e:
            logger.error(f"Error listing CSV files from S3: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error retrieving CSV file list: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in list_csv_files_only: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error listing CSV files: {str(e)}"
        )
