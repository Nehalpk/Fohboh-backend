#!/usr/bin/env python3
"""
🤖 Enhanced Adora POS AI Chatbot - Usage Example

This script demonstrates how to use the comprehensive AI-powered 
Adora POS chatbot integration that you've implemented.

Features demonstrated:
- Session initialization
- Natural language queries
- Real-time data fetching
- Historical analysis
- Advanced analytics
- Error handling
"""

import asyncio
import sys
import os

# Add the src directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from adora_pos_ai_chatbot import AdoraPOSAIChatbot, process_chatbot_query
import psycopg2
from datetime import datetime

# Database configuration (replace with your actual database config)
DB_CONFIG = {
    'host': 'localhost',
    'database': 'your_database',
    'user': 'your_username',
    'password': 'your_password',
    'port': 5432
}

async def main():
    """Main function demonstrating the AI chatbot usage"""
    
    print("🚀 Enhanced Adora POS AI Chatbot - Demo")
    print("=" * 50)
    
    # Initialize database connection
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        print("✅ Database connected successfully")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        print("Please update the DB_CONFIG with your database credentials")
        return
    
    try:
        # Method 1: Using the chatbot class directly
        print("\n📊 Method 1: Direct Chatbot Class Usage")
        print("-" * 40)
        
        # Initialize chatbot
        chatbot = AdoraPOSAIChatbot(conn)
        print(f"✅ Chatbot initialized for store: {chatbot.store_id}")
        
        # Get data summary
        summary = chatbot.get_data_summary()
        print(f"\n📈 Data Summary:\n{summary}")
        
        # Ask some questions
        questions = [
            "What are my top 5 selling items?",
            "Show me yesterday's sales performance",
            "How can I improve my restaurant's profitability?",
            "What inventory should I order this week?"
        ]
        
        for question in questions:
            print(f"\n❓ Question: {question}")
            try:
                result = await chatbot.process_query(question, user_id=1)
                print(f"🤖 Answer: {result['answer'][:200]}...")
                print(f"⏱️  Processing time: {result['processing_time_ms']}ms")
            except Exception as e:
                print(f"❌ Error: {e}")
        
        print("\n" + "=" * 50)
        
        # Method 2: Using the helper function (recommended for API integration)
        print("\n📊 Method 2: Helper Function Usage (API Integration)")
        print("-" * 40)
        
        api_questions = [
            "Give me a comprehensive business analysis",
            "What are my peak hours this week?",
            "Compare this week vs last week performance",
            "Show me customer traffic patterns"
        ]
        
        for question in api_questions:
            print(f"\n❓ Question: {question}")
            try:
                result = await process_chatbot_query(
                    query=question,
                    user_id=1,
                    conn=conn
                )
                print(f"🤖 Answer: {result['answer'][:200]}...")
                print(f"⏱️  Processing time: {result['processing_time_ms']}ms")
                print(f"🆔 Conversation ID: {result['conversation_id']}")
            except Exception as e:
                print(f"❌ Error: {e}")
        
        print("\n" + "=" * 50)
        
        # Method 3: Interactive chat simulation
        print("\n💬 Method 3: Interactive Chat Simulation")
        print("-" * 40)
        
        conversation_id = None
        interactive_questions = [
            "help",
            "summary", 
            "What's my average order value?",
            "refresh",
            "Show me menu performance analysis"
        ]
        
        for question in interactive_questions:
            print(f"\n💬 User: {question}")
            try:
                result = await process_chatbot_query(
                    query=question,
                    user_id=1,
                    conn=conn,
                    conversation_id=conversation_id
                )
                
                # Use the same conversation ID for context
                conversation_id = result['conversation_id']
                
                print(f"🤖 Assistant: {result['answer'][:300]}...")
                if result['processing_time_ms'] > 0:
                    print(f"⏱️  Processing time: {result['processing_time_ms']}ms")
                
            except Exception as e:
                print(f"❌ Error: {e}")
        
        print("\n" + "=" * 50)
        print("✅ Demo completed successfully!")
        print("\n🎯 Key Features Demonstrated:")
        print("• Real-time data fetching from Adora POS API")
        print("• Historical data analysis (2 months)")
        print("• GPT-4 AI processing with fallback analysis")
        print("• Natural language query processing")
        print("• Conversation context management")
        print("• Comprehensive business analytics")
        print("• Error handling and graceful degradation")
        
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        
    finally:
        # Close database connection
        if conn:
            conn.close()
            print("\n🔌 Database connection closed")

def interactive_chat():
    """Interactive chat function for manual testing"""
    print("\n🎮 Interactive Chat Mode")
    print("Type 'quit' to exit, 'help' for assistance")
    print("-" * 40)
    
    # This would need to be implemented with proper async handling
    # For now, just show the concept
    print("Note: This is a concept demonstration.")
    print("For actual interactive chat, integrate with your web interface")
    print("or use the API endpoints with proper async handling.")

if __name__ == "__main__":
    print("🤖 Enhanced Adora POS AI Chatbot Example")
    print("Make sure to update DB_CONFIG with your database credentials")
    print("\nRunning demo...")
    
    # Run the async main function
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Demo interrupted by user")
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        print("Please check your database configuration and try again") 