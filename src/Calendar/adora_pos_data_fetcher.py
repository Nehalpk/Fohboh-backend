import httpx
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import logging

# Configure logging
logger = logging.getLogger(__name__)

class AdoraPOSDataFetcher:
    """
    Data fetcher class for Adora POS API integration
    Provides methods to fetch various types of data from Adora POS
    """
    
    def __init__(self):
        # Adora POS API Configuration
        self.base_url = "https://apiqa.adorapos.com"
        self.store_id = "LE5AR"
        self.cid = "39adc75f-8cfe-42b1-9781-0e10c1d0f322"
        
        # OAuth2 Configuration
        self.token_url = "https://login.microsoftonline.com/4ed8e22a-1960-4475-9718-f1f11f1d0462/oauth2/v2.0/token"
        self.client_id = "2b671252-ab02-453a-ac58-3ddf6ffdf969"
        self.client_secret = "WmA8Q~xSEsu8BPynraA_gfCSb0ai.mQpqIGWRa-4"
        self.scope = "api://08c4a591-c631-4421-8a60-871e631990d7/.default"
        self.grant_type = "client_credentials"
        
        # Token storage
        self.access_token = None
        self.token_expires_at = None
        
        # Data cache
        self.data_cache = {}
        
    def get_access_token(self) -> str:
        """Get OAuth2 access token (synchronous version)"""
        try:
            # Check if token is still valid
            if self.access_token and self.token_expires_at and datetime.now() < self.token_expires_at:
                return self.access_token

            # Request new token
            token_data = {
                "grant_type": self.grant_type,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": self.scope
            }
            
            with httpx.Client() as client:
                response = client.post(
                    self.token_url,
                    data=token_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
                
                if response.status_code != 200:
                    logger.error(f"Failed to get access token: {response.status_code} - {response.text}")
                    raise Exception(f"Failed to authenticate with Adora POS: {response.status_code}")
                
                token_response = response.json()
                self.access_token = token_response.get("access_token")
                expires_in = token_response.get("expires_in", 3600)  # Default 1 hour
                
                # Set expiration time (subtract 5 minutes for safety)
                self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 300)
                
                logger.info("Successfully obtained Adora POS access token")
                return self.access_token
                
        except Exception as e:
            logger.error(f"Error getting access token: {str(e)}")
            raise Exception(f"Authentication error: {str(e)}")

    def make_api_request(self, endpoint: str) -> Dict[str, Any]:
        """Make authenticated API request to Adora POS (synchronous version)"""
        try:
            access_token = self.get_access_token()
            
            # Construct full URL
            if endpoint.startswith('/'):
                endpoint = endpoint[1:]  # Remove leading slash
            
            url = f"{self.base_url}/api/{endpoint}/{self.store_id}/?cid={self.cid}"
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, headers=headers)
                
                if response.status_code == 401:
                    # Token might be expired, retry once with new token
                    logger.info("Token expired, getting new token")
                    self.access_token = None
                    access_token = self.get_access_token()
                    headers["Authorization"] = f"Bearer {access_token}"
                    
                    response = client.get(url, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"API request failed: {response.status_code} - {response.text}")
                    raise Exception(f"Adora POS API error: {response.status_code}")
                
                return response.json()
                
        except httpx.TimeoutException:
            logger.error(f"Timeout occurred while calling Adora POS API: {endpoint}")
            raise Exception("Adora POS API request timeout")
        except Exception as e:
            logger.error(f"Error making API request to {endpoint}: {str(e)}")
            raise Exception(f"API request error: {str(e)}")

    def fetch_menu_data(self) -> Dict[str, Any]:
        """Fetch menu items data"""
        try:
            logger.info("Fetching menu data from Adora POS")
            data = self.make_api_request("Data/menuitems")
            logger.info(f"Successfully fetched menu data: {len(data.get('result', []))} items")
            return data
        except Exception as e:
            logger.error(f"Error fetching menu data: {str(e)}")
            return {"result": [], "error": str(e)}

    def fetch_orders_data(self, date: str) -> Dict[str, Any]:
        """Fetch orders data for a specific date"""
        try:
            logger.info(f"Fetching orders data for date: {date}")
            endpoint = f"Data/orders/{date}"
            data = self.make_api_request(endpoint)
            logger.info(f"Successfully fetched orders data for {date}: {len(data.get('result', []))} orders")
            return data
        except Exception as e:
            logger.error(f"Error fetching orders data for {date}: {str(e)}")
            return {"result": [], "error": str(e)}

    def fetch_sales_data(self, date: str) -> Dict[str, Any]:
        """Fetch sales data for a specific date"""
        try:
            logger.info(f"Fetching sales data for date: {date}")
            endpoint = f"Data/sales/{date}"
            data = self.make_api_request(endpoint)
            logger.info(f"Successfully fetched sales data for {date}")
            return data
        except Exception as e:
            logger.error(f"Error fetching sales data for {date}: {str(e)}")
            return {"result": [], "error": str(e)}

    def fetch_customers_data(self, date: str) -> Dict[str, Any]:
        """Fetch customers data for a specific date"""
        try:
            logger.info(f"Fetching customers data for date: {date}")
            endpoint = f"Data/customers/{date}"
            data = self.make_api_request(endpoint)
            logger.info(f"Successfully fetched customers data for {date}: {len(data.get('result', []))} customers")
            return data
        except Exception as e:
            logger.error(f"Error fetching customers data for {date}: {str(e)}")
            return {"result": [], "error": str(e)}

    def fetch_employees_data(self) -> Dict[str, Any]:
        """Fetch employees data"""
        try:
            logger.info("Fetching employees data from Adora POS")
            data = self.make_api_request("Data/employees")
            logger.info(f"Successfully fetched employees data: {len(data.get('result', []))} employees")
            return data
        except Exception as e:
            logger.error(f"Error fetching employees data: {str(e)}")
            return {"result": [], "error": str(e)}

    def fetch_discounts_data(self) -> Dict[str, Any]:
        """Fetch discounts data"""
        try:
            logger.info("Fetching discounts data from Adora POS")
            data = self.make_api_request("Data/discounts")
            logger.info(f"Successfully fetched discounts data")
            return data
        except Exception as e:
            logger.error(f"Error fetching discounts data: {str(e)}")
            return {"result": [], "error": str(e)}

    def fetch_all_data(self) -> Dict[str, Any]:
        """Fetch all available data types"""
        try:
            logger.info("Starting comprehensive data fetch from Adora POS")
            
            all_data = {}
            
            # Fetch menu data
            all_data['menu'] = self.fetch_menu_data()
            
            # Fetch employees data
            all_data['employees'] = self.fetch_employees_data()
            
            # Fetch discounts data
            all_data['discounts'] = self.fetch_discounts_data()
            
            # Fetch recent orders and sales (last 7 days)
            end_date = datetime.now()
            for i in range(7):
                date = (end_date - timedelta(days=i)).strftime("%Y-%m-%d")
                
                # Fetch orders for this date
                orders_key = f"orders_{date.replace('-', '_')}"
                all_data[orders_key] = self.fetch_orders_data(date)
                
                # Fetch sales for this date
                sales_key = f"sales_{date.replace('-', '_')}"
                all_data[sales_key] = self.fetch_sales_data(date)
                
                # Fetch customers for this date (every other day to reduce load)
                if i % 2 == 0:
                    customers_key = f"customers_{date.replace('-', '_')}"
                    all_data[customers_key] = self.fetch_customers_data(date)
            
            logger.info("Successfully completed comprehensive data fetch")
            return all_data
            
        except Exception as e:
            logger.error(f"Error in comprehensive data fetch: {str(e)}")
            return {"error": str(e)}

    def save_data_to_files(self, data_dir: str, data: Optional[Dict[str, Any]] = None):
        """Save fetched data to JSON files"""
        try:
            # Create directory if it doesn't exist
            if not os.path.exists(data_dir):
                os.makedirs(data_dir)
            
            # If no data provided, fetch all data
            if data is None:
                data = self.fetch_all_data()
            
            # Save each data type to separate files
            for data_type, data_content in data.items():
                if data_content and not data_content.get('error'):
                    filename = f"{data_dir}/{data_type}_data.json"
                    with open(filename, 'w', encoding='utf-8') as f:
                        json.dump(data_content, f, indent=2, default=str)
                    logger.info(f"Saved {data_type} data to {filename}")
            
            logger.info(f"Successfully saved all data to {data_dir}")
            
        except Exception as e:
            logger.error(f"Error saving data to files: {str(e)}")
            raise Exception(f"Failed to save data: {str(e)}")

    def get_data_summary(self) -> Dict[str, Any]:
        """Get a summary of available data"""
        try:
            summary = {
                "store_id": self.store_id,
                "timestamp": datetime.now().isoformat(),
                "data_types": {}
            }
            
            # Get menu summary
            menu_data = self.fetch_menu_data()
            summary["data_types"]["menu"] = {
                "count": len(menu_data.get('result', [])),
                "status": "success" if not menu_data.get('error') else "error"
            }
            
            # Get employees summary
            employees_data = self.fetch_employees_data()
            summary["data_types"]["employees"] = {
                "count": len(employees_data.get('result', [])),
                "status": "success" if not employees_data.get('error') else "error"
            }
            
            # Get recent orders summary (today)
            today = datetime.now().strftime("%Y-%m-%d")
            orders_data = self.fetch_orders_data(today)
            summary["data_types"]["orders_today"] = {
                "count": len(orders_data.get('result', [])),
                "status": "success" if not orders_data.get('error') else "error"
            }
            
            return summary
            
        except Exception as e:
            logger.error(f"Error getting data summary: {str(e)}")
            return {"error": str(e)} 