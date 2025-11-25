# 🤖 Enhanced Adora POS AI Chatbot - Complete Integration Guide

## Overview

یہ comprehensive AI-powered chatbot integration آپ کو natural language میں اپنے restaurant کے Adora POS data کے ساتھ advanced interaction کی اجازت دیتا ہے۔ یہ enhanced system automatically:

- ✅ **Real-time data fetching** - Adora POS API سے live data fetch کرتا ہے
- ✅ **Historical analysis** - پچھلے 2 months کا comprehensive data store کرتا ہے  
- ✅ **GPT-4 AI processing** - OpenAI GPT-4 سے intelligent insights فراہم کرتا ہے
- ✅ **Enhanced fallback analysis** - AI fail ہونے پر advanced analytics provide کرتا ہے
- ✅ **Automatic data sync** - ہر 30 منٹ میں data refresh کرتا ہے
- ✅ **Advanced business analytics** - Deep insights اور actionable recommendations دیتا ہے
- ✅ **Natural language processing** - Complex queries کو سمجھتا اور process کرتا ہے

## 🚀 Main Endpoints

### POST `/adora-pos/ai-chat`

**Primary AI-powered endpoint for restaurant data queries**

### POST `/adora-pos/start-chat-session`

**Initialize comprehensive AI chatbot session with full data loading**

#### Request
```bash
curl -X POST "http://your-api-url/adora-pos/start-chat-session" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json"
```

#### Response
```json
{
  "status": "success",
  "message": "🤖 AI-Powered Adora POS Assistant Initialized",
  "session_info": {
    "store_id": "LE5AR",
    "data_directory": "adora_pos_data",
    "last_refresh": "2024-01-15T10:30:00Z",
    "openai_enabled": true
  },
  "data_summary": "📊 CURRENT DATA SUMMARY:\n========================================\n• MENU: 45 records\n• EMPLOYEES: 12 records\n• DISCOUNTS: 5 records\n\n📈 HISTORICAL ORDERS: 14 dates\n📈 HISTORICAL CUSTOMERS: 7 dates",
  "help_message": "🤖 AI-Powered Adora POS Assistant\n\nI can help you with:\n📋 Menu & Products\n👥 Staff Management\n💰 Sales & Orders\n📊 Analytics\n\nJust ask me anything about your restaurant data in natural language!",
  "available_commands": [
    "help - Show help message",
    "refresh - Refresh all data",
    "summary - Show data summary",
    "Any natural language question about your restaurant data"
  ],
  "examples": [
    "What are my top selling items?",
    "Show me yesterday's sales",
    "How can I improve labor costs?",
    "What should I order for inventory?",
    "Analyze my customer trends",
    "Compare this week vs last week"
  ]
}
```

### POST `/adora-pos/ai-chat` (Enhanced)
```bash
curl -X POST "http://your-api-url/adora-pos/ai-chat" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are my top selling items this week?"
  }'
```

#### Example Questions You Can Ask:

**Sales & Revenue:**
- "What are my total sales for this week?"
- "Show me yesterday's revenue breakdown"
- "Which day performed best this month?"
- "What's my average order value?"

**Menu & Items:**
- "What are my top selling items?"
- "Which menu items have the highest profit margin?"
- "Show me underperforming products"
- "What should I remove from my menu?"

**Business Insights:**
- "How can I improve my restaurant's profitability?"
- "What are the peak hours for my restaurant?"
- "Give me inventory recommendations for next week"
- "How does this week compare to last week?"

**Operational:**
- "How many staff should I schedule for Friday?"
- "What are my labor cost recommendations?"
- "Show me fraud detection alerts"
- "Give me operational efficiency suggestions"

#### Response Format:
```json
{
  "status": "success",
  "question": "What are my top selling items this week?",
  "answer": "📊 TOP SELLING ITEMS ANALYSIS:\n\nBased on your last 7 days data:\n\n🏆 TOP PERFORMERS:\n1. Chicken Burger: 45 units sold ($540 revenue)\n2. Fish & Chips: 38 units sold ($456 revenue)\n3. Caesar Salad: 31 units sold ($310 revenue)\n\n💰 PROFITABILITY INSIGHTS:\n• Chicken Burger: 65% profit margin\n• Fish & Chips: 58% profit margin  \n• Caesar Salad: 72% profit margin\n\n🎯 RECOMMENDATIONS:\n1. Promote Caesar Salad more (highest margin)\n2. Create combo deals with top items\n3. Consider seasonal variations\n4. Stock up on high-demand ingredients\n\n📈 WEEKLY PERFORMANCE:\n• Total Revenue: $4,250\n• Total Orders: 125\n• Average Order Value: $34.00",
  "conversation_id": "conv_abc123",
  "store_id": "LE5AR",
  "processing_time_ms": 1250,
  "timestamp": "2024-01-15T10:30:00Z",
  "data_freshness": "2024-01-15T10:15:00Z",
  "user_id": 123,
  "user_email": "manager@restaurant.com",
  "user_role": "Restaurant Manager"
}
```

## 🔧 Utility Endpoints

### 1. Data Sync
```bash
POST /adora-pos/sync-data
```
Manually trigger data sync from Adora POS API (normally happens automatically every hour).

### 2. Business Insights
```bash
GET /adora-pos/insights
```
Quick pre-calculated metrics for last 7 days.

### 3. Health Check
```bash
GET /adora-pos/health
```
System health status including database, OpenAI, and data freshness.

### 4. Test Enhanced Chatbot
```bash
POST /adora-pos/test-queries
```
Comprehensive testing of the AI chatbot with 10 sample queries to demonstrate all features including real-time data fetching, historical analysis, and advanced analytics.

## 📊 Database Schema

The system automatically creates these tables:

### `adora_pos_menu_items`
- Stores menu items with pricing and category info
- Updated when menu data is synced

### `adora_pos_orders`
- Stores individual orders with items and totals
- Updated daily for last 7 days

### `adora_pos_sales`
- Aggregated daily sales summaries
- Includes top items and hourly breakdowns

### `adora_pos_chat_history`
- Stores all AI conversations for analytics
- Includes processing time and context

## 🔒 Authentication & Permissions

**Required Roles:**
- ✅ SUPER_ADMIN
- ✅ Restaurant Owner  
- ✅ Regional Manager
- ✅ Restaurant Manager
- ❌ Non_Operators (access denied)

**JWT Token Required:**
```bash
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

## 💡 Best Practices

### 1. **Question Formulation**
- Be specific: "Show me yesterday's sales" vs "Show me sales"
- Use business terms: "profit margin", "peak hours", "inventory needs"
- Ask for comparisons: "How does this week compare to last week?"

### 2. **Data Freshness**
- System syncs data hourly automatically
- Use `/sync-data` endpoint if you need immediate updates
- Check `data_freshness` field in responses

### 3. **Performance Optimization**
- AI processing takes 1-3 seconds typically
- Database queries are optimized with indexes
- Use `/insights` endpoint for quick metrics

### 4. **Error Handling**
```javascript
try {
  const response = await fetch('/adora-pos/ai-chat', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      question: "What are my sales today?"
    })
  });
  
  const result = await response.json();
  
  if (result.status === 'success') {
    console.log(result.answer);
  } else {
    console.error('Error:', result.answer);
  }
} catch (error) {
  console.error('Request failed:', error);
}
```

## 🎯 Advanced Use Cases

### 1. **Daily Management Dashboard**
```javascript
// Get morning briefing
const morningBrief = await askAdoraPOS(
  "Give me a morning briefing: yesterday's performance, today's recommendations, and what I should focus on"
);

// Check inventory needs
const inventoryNeeds = await askAdoraPOS(
  "What ingredients should I order based on this week's sales patterns?"
);

// Staff scheduling
const staffingAdvice = await askAdoraPOS(
  "How many staff should I schedule for today based on predicted sales?"
);
```

### 2. **Weekly Performance Review**
```javascript
const weeklyReview = await askAdoraPOS(`
  Give me a comprehensive weekly performance review including:
  - Revenue vs targets
  - Top and bottom performing items  
  - Customer satisfaction insights
  - Cost optimization opportunities
  - Next week's action items
`);
```

### 3. **Menu Optimization**
```javascript
const menuAnalysis = await askAdoraPOS(
  "Analyze my menu performance and suggest which items to promote, modify, or remove for better profitability"
);
```

## 🔧 Technical Configuration

### Environment Variables
```bash
# OpenAI Configuration
OPENAI_API_KEY=sk-proj-your-openai-key

# Adora POS Configuration  
ADORA_BASE_URL=https://apiqa.adorapos.com
ADORA_STORE_ID=LE5AR
ADORA_CLIENT_ID=2b671252-ab02-453a-ac58-3ddf6ffdf969
ADORA_CLIENT_SECRET=WmA8Q~xSEsu8BPynraA_gfCSb0ai.mQpqIGWRa-4

# Database Configuration
DATABASE_URL=postgresql://user:pass@localhost/dbname
```

### Installation
```bash
# Install dependencies
pip install -r requirements.txt

# Run migrations (automatic on startup)
python -c "from src.adora_pos_database import init_adora_pos_tables; init_adora_pos_tables(conn)"

# Start server
uvicorn routes:app --host 0.0.0.0 --port 8000
```

## 📈 Monitoring & Analytics

### Response Time Tracking
All requests include `processing_time_ms` field for performance monitoring.

### Usage Analytics
Check `adora_pos_chat_history` table for:
- Most asked questions
- User engagement patterns
- System performance metrics

### Health Monitoring
Use `/adora-pos/health` endpoint to monitor:
- Database connectivity
- OpenAI API status
- Data freshness
- System performance

## 🚨 Troubleshooting

### Common Issues:

**1. "No data available"**
- Solution: Call `/adora-pos/sync-data` to fetch fresh data

**2. "OpenAI API error"**
- Check API key validity
- Verify internet connectivity
- System falls back to basic analysis

**3. "Authentication failed"**
- Verify JWT token
- Check user role permissions
- Ensure token hasn't expired

**4. "Slow response times"**
- Check database indexes
- Monitor OpenAI API latency
- Consider data volume optimization

## 💬 Example Conversations

**Business Owner:**
```
Q: "How is my restaurant performing financially?"
A: 📊 FINANCIAL PERFORMANCE ANALYSIS:

💰 REVENUE OVERVIEW (Last 7 Days):
• Total Revenue: $8,450
• Daily Average: $1,207
• Growth vs Last Week: +12%

🎯 KEY METRICS:
• Average Order Value: $34.50
• Total Orders: 245
• Customer Return Rate: 68%

📈 TREND ANALYSIS:
• Best Day: Friday ($1,580)
• Peak Hours: 12-2 PM, 6-8 PM
• Strongest Category: Main Courses (65% of sales)

🚀 RECOMMENDATIONS:
1. Extend Friday promotions to Saturday
2. Add lunch specials for 12-2 PM rush
3. Promote appetizers to increase order value
4. Consider weekend brunch menu
```

**Manager:**
```
Q: "What should I focus on today?"
A: 🎯 TODAY'S PRIORITY FOCUS:

⚠️ IMMEDIATE ACTIONS:
1. Restock Chicken Burgers (trending item, low inventory)
2. Schedule extra staff 6-8 PM (predicted busy period)
3. Promote Caesar Salad (highest margin item)

📊 TODAY'S PREDICTIONS:
• Expected Orders: 35-40
• Estimated Revenue: $1,200-1,400
• Peak Time: 7:30 PM

💡 OPPORTUNITIES:
• Push dessert sales (currently only 15% attachment rate)
• Upsell beverages with combo deals
• Test new appetizer special
```

---

## 🎉 Getting Started

1. **Setup Authentication** - Get your JWT token
2. **Test Health Check** - Call `/adora-pos/health`
3. **Sync Initial Data** - Call `/adora-pos/sync-data`
4. **Start Asking Questions** - Use `/adora-pos/ai-chat`

**Your first question could be:**
```json
{
  "question": "Give me an overview of my restaurant's performance and what I should focus on"
}
```

Happy analyzing! 🚀📊 