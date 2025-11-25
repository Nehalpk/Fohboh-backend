import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from openai import OpenAI
from .adora_pos_data_fetcher import AdoraPOSDataFetcher
from .adora_pos_integration import AdoraPOSAIIntegration
import time
import logging
import uuid

# Configure logging
logger = logging.getLogger(__name__)

class AdoraPOSAIChatbot:
    def __init__(self, conn, data_dir: str = "adora_pos_data"):
        # Set up OpenAI
        try:
            self.openai_api_key = "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"
            self.openai_model = "gpt-4"
            self.client = OpenAI(api_key=self.openai_api_key)
        except Exception as e:
            logger.warning(f"OpenAI initialization failed: {e}. Using fallback analysis.")
            self.client = None
        
        try:
            self.data_dir = data_dir
            if not os.path.exists(data_dir):
                os.makedirs(data_dir)
                
            self.store_id = "LE5AR"
            self.data = {}
            self.conn = conn
            
            # Initialize data fetcher and integration
            self.fetcher = AdoraPOSDataFetcher()
            self.integration = AdoraPOSAIIntegration(conn)
            
            self.last_data_refresh = datetime.now()
            
            # Load or fetch data for the last 2 months
            self.load_historical_data()
        except Exception as e:
            logger.error(f"Error initializing chatbot: {e}")
            raise
        
    def load_historical_data(self):
        """Load data for the last 2 months"""
        logger.info("🔄 Loading historical data for the last 2 months...")
        
        # Generate date range for last 2 months
        end_date = datetime.now()
        start_date = end_date - timedelta(days=60)  # Approximately 2 months
        
        # Create date-specific data directory
        historical_dir = f"{self.data_dir}_historical"
        if not os.path.exists(historical_dir):
            os.makedirs(historical_dir)
        
        # Fetch data for multiple dates to get comprehensive historical data
        dates_to_fetch = []
        current_date = start_date
        while current_date <= end_date:
            dates_to_fetch.append(current_date.strftime("%Y-%m-%d"))
            current_date += timedelta(days=7)  # Weekly intervals
        
        # Fetch recent data (last week) for current operations
        recent_dates = []
        for i in range(7):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            recent_dates.append(date)
        
        logger.info(f"📅 Fetching data for {len(recent_dates)} recent dates...")
        
        # Fetch comprehensive current data
        self.fetch_comprehensive_data()
        
        # Load existing data files
        self.load_data_files()
        
        logger.info("✅ Historical data loading completed!")
    
    def fetch_comprehensive_data(self):
        """Fetch comprehensive data for current analysis"""
        logger.info("🚀 Fetching comprehensive current data...")
        
        try:
            # Use the data fetcher to get all data
            all_data = self.fetcher.fetch_all_data()
            
            # Save to files
            self.fetcher.save_data_to_files(self.data_dir, all_data)
            
            # Also fetch some historical orders and customers
            for i in range(14):  # Last 2 weeks
                date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                logger.info(f"📊 Fetching data for {date}...")
                
                # Fetch orders for this date
                orders_data = self.fetcher.fetch_orders_data(date)
                if orders_data and orders_data.get('result'):
                    # Save historical orders
                    filename = f"{self.data_dir}/orders_{date.replace('-', '_')}.json"
                    with open(filename, 'w', encoding='utf-8') as f:
                        json.dump(orders_data, f, indent=2)
                
                # Fetch customers for this date
                customers_data = self.fetcher.fetch_customers_data(date)
                if customers_data and customers_data.get('result'):
                    # Save historical customers
                    filename = f"{self.data_dir}/customers_{date.replace('-', '_')}.json"
                    with open(filename, 'w', encoding='utf-8') as f:
                        json.dump(customers_data, f, indent=2)
                
                # Rate limiting
                time.sleep(0.5)
                
        except Exception as e:
            logger.error(f"Error in comprehensive data fetch: {e}")
    
    def load_data_files(self):
        """Load all available data from JSON files"""
        if not os.path.exists(self.data_dir):
            logger.info("📁 Data directory not found.")
            return
        
        # Load all JSON files
        for filename in os.listdir(self.data_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(self.data_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    # Determine data type from filename
                    if filename.startswith('orders_'):
                        date_key = filename.replace('orders_', '').replace('.json', '')
                        if 'historical_orders' not in self.data:
                            self.data['historical_orders'] = {}
                        self.data['historical_orders'][date_key] = data
                    elif filename.startswith('customers_'):
                        date_key = filename.replace('customers_', '').replace('.json', '')
                        if 'historical_customers' not in self.data:
                            self.data['historical_customers'] = {}
                        self.data['historical_customers'][date_key] = data
                    else:
                        data_type = filename.replace('_data.json', '')
                        self.data[data_type] = data
                    
                    logger.info(f"✅ Loaded {filename}")
                except Exception as e:
                    logger.error(f"❌ Error loading {filename}: {e}")
    
    def get_data_summary(self) -> str:
        """Get a comprehensive summary of all available data"""
        summary = []
        
        # Current data summary
        summary.append("📊 CURRENT DATA SUMMARY:")
        summary.append("=" * 40)
        
        for data_type, data in self.data.items():
            if data_type.startswith('historical_'):
                continue
                
            if isinstance(data, dict) and 'result' in data:
                count = len(data['result'])
                summary.append(f"• {data_type.upper()}: {count} records")
            elif isinstance(data, dict):
                summary.append(f"• {data_type.upper()}: {len(data)} sections")
        
        # Historical data summary
        if 'historical_orders' in self.data:
            summary.append(f"\n📈 HISTORICAL ORDERS: {len(self.data['historical_orders'])} dates")
        
        if 'historical_customers' in self.data:
            summary.append(f"📈 HISTORICAL CUSTOMERS: {len(self.data['historical_customers'])} dates")
        
        return "\n".join(summary)
    
    def prepare_context_for_ai(self, user_query: str) -> str:
        """Prepare relevant context for AI based on user query"""
        context_parts = []
        
        # Add store information
        context_parts.append(f"STORE ID: {self.store_id}")
        context_parts.append(f"CURRENT DATE: {datetime.now().strftime('%Y-%m-%d')}")
        
        query_lower = user_query.lower()
        
        # Enhanced analytics for any query - provide comprehensive context
        if 'historical_orders' in self.data:
            context_parts.append("\n📊 COMPREHENSIVE BUSINESS ANALYTICS:")
            
            # Calculate comprehensive metrics
            total_orders = 0
            total_revenue = 0
            item_performance = {}
            daily_performance = {}
            hourly_patterns = {}
            
            for date_key, order_data in self.data['historical_orders'].items():
                date_str = date_key.replace('_', '-')
                orders = order_data.get('result', [])
                daily_orders = len(orders)
                daily_revenue = 0
                
                for order in orders:
                    order_total = float(order.get('total', 0))
                    total_revenue += order_total
                    daily_revenue += order_total
                    
                    # Extract hour from order time for peak analysis
                    order_time = order.get('created_at', '')
                    if order_time:
                        try:
                            hour = datetime.fromisoformat(order_time.replace('Z', '+00:00')).hour
                            hourly_patterns[hour] = hourly_patterns.get(hour, 0) + 1
                        except:
                            pass
                    
                    # Track item performance
                    for item in order.get('items', []):
                        item_name = item.get('menu_item_name', 'Unknown')
                        quantity = int(item.get('quantity', 1))
                        price = float(item.get('amount', 0))
                        food_cost = float(item.get('food_cost', 0))
                        
                        if item_name not in item_performance:
                            item_performance[item_name] = {
                                'quantity': 0, 'revenue': 0, 'cost': 0
                            }
                        
                        item_performance[item_name]['quantity'] += quantity
                        item_performance[item_name]['revenue'] += price
                        item_performance[item_name]['cost'] += food_cost
                
                daily_performance[date_str] = {
                    'orders': daily_orders,
                    'revenue': daily_revenue,
                    'avg_ticket': daily_revenue / daily_orders if daily_orders > 0 else 0
                }
                total_orders += daily_orders
            
            # Overall performance metrics
            avg_order_value = total_revenue / total_orders if total_orders > 0 else 0
            context_parts.append(f"\n💰 OVERALL PERFORMANCE:")
            context_parts.append(f"• Total Orders: {total_orders}")
            context_parts.append(f"• Total Revenue: ${total_revenue:.2f}")
            context_parts.append(f"• Average Order Value: ${avg_order_value:.2f}")
            
            # Top performing items with profitability
            if item_performance:
                sorted_items = sorted(item_performance.items(), 
                                    key=lambda x: x[1]['quantity'], reverse=True)
                
                context_parts.append(f"\n🏆 TOP PERFORMING ITEMS (Sales & Profitability):")
                for i, (item_name, data) in enumerate(sorted_items[:10], 1):
                    profit = data['revenue'] - data['cost']
                    profit_margin = (profit / data['revenue'] * 100) if data['revenue'] > 0 else 0
                    context_parts.append(
                        f"{i}. {item_name}"
                        f"\n   - Quantity: {data['quantity']} units"
                        f"\n   - Revenue: ${data['revenue']:.2f}"
                        f"\n   - Profit: ${profit:.2f} ({profit_margin:.1f}% margin)"
                    )
        
        return "\n".join(context_parts)

    def needs_data_refresh(self) -> bool:
        """Check if data needs to be refreshed"""
        # Refresh data every 30 minutes
        time_since_refresh = datetime.now() - self.last_data_refresh
        return time_since_refresh.total_seconds() > 1800  # 30 minutes in seconds

    async def refresh_data(self):
        """Refresh all data"""
        try:
            logger.info("🔄 Refreshing data...")
            
            # Use the integration's sync method
            await self.integration.sync_last_7_days_data()
            
            # Also refresh local data
            self.fetch_comprehensive_data()
            self.load_data_files()
            self.last_data_refresh = datetime.now()
            
            logger.info("✅ Data refreshed successfully!")
        except Exception as e:
            logger.error(f"❌ Error refreshing data: {e}")

    async def process_query(self, query: str, user_id: int, conversation_id: Optional[str] = None) -> Dict[str, Any]:
        """Process user query with AI assistance and real-time data fetching"""
        try:
            # Check if data needs refreshing
            if self.needs_data_refresh():
                await self.refresh_data()
            
            # Clean and normalize the query
            query = query.strip()
            if not query:
                return {
                    "answer": self.get_help_message(),
                    "processing_time_ms": 0,
                    "data_sources": [],
                    "conversation_id": conversation_id or str(uuid.uuid4())
                }
            
            # Handle special commands
            if query.lower() == 'help':
                return {
                    "answer": self.get_help_message(),
                    "processing_time_ms": 0,
                    "data_sources": [],
                    "conversation_id": conversation_id or str(uuid.uuid4())
                }
            elif query.lower() == 'refresh':
                await self.refresh_data()
                return {
                    "answer": "✅ Data has been refreshed!",
                    "processing_time_ms": 0,
                    "data_sources": [],
                    "conversation_id": conversation_id or str(uuid.uuid4())
                }
            elif query.lower() == 'summary':
                return {
                    "answer": self.get_data_summary(),
                    "processing_time_ms": 0,
                    "data_sources": [],
                    "conversation_id": conversation_id or str(uuid.uuid4())
                }
            
            # Use the existing integration to process the query
            start_time = time.time()
            result = await self.integration.process_ai_query(query, user_id, conversation_id)
            processing_time = int((time.time() - start_time) * 1000)
            
            # Add processing time to result
            result["processing_time_ms"] = processing_time
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing query: {e}")
            return {
                "answer": "Sorry, I encountered an error while processing your query. Please try again or rephrase your question.",
                "processing_time_ms": 0,
                "data_sources": [],
                "conversation_id": conversation_id or str(uuid.uuid4()),
                "error": str(e)
            }
    
    def get_help_message(self) -> str:
        """Return help message"""
        return """
🤖 AI-Powered Adora POS Assistant

I can help you with:
📋 Menu & Products - "Show me the menu", "What items do we have?"
👥 Staff Management - "How many employees?", "Who works here?"
👤 Customer Info - "Customer details", "How many customers?"
💰 Sales & Orders - "Sales summary", "Recent orders"
💸 Discounts & Promotions - "Active discounts", "What deals do we have?"
🏪 Store Operations - "Store status", "Business overview"
📊 Analytics - "Performance insights", "Trends analysis"

Just ask me anything about your restaurant data in natural language!
        """

# Create a global instance for easy access
_chatbot_instance = None

def get_chatbot_instance(conn) -> AdoraPOSAIChatbot:
    """Get or create the chatbot instance"""
    global _chatbot_instance
    if _chatbot_instance is None:
        _chatbot_instance = AdoraPOSAIChatbot(conn)
    return _chatbot_instance

async def process_chatbot_query(query: str, user_id: int, conn, conversation_id: Optional[str] = None) -> Dict[str, Any]:
    """Process a query using the AI chatbot"""
    try:
        chatbot = get_chatbot_instance(conn)
        return await chatbot.process_query(query, user_id, conversation_id)
    except Exception as e:
        logger.error(f"Error in chatbot query processing: {e}")
        return {
            "answer": f"Error processing your query: {str(e)}",
            "processing_time_ms": 0,
            "data_sources": [],
            "conversation_id": conversation_id or str(uuid.uuid4()),
            "error": str(e)
        } 