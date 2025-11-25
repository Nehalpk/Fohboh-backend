from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import uuid
from datetime import datetime, timedelta
import statistics
from src.chat_gpt import get_current_user, get_db, DB_CONFIG
from src.subscription_management import update_usage
import random
from typing import List, Dict
import openai

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Router
router = APIRouter(prefix="/promotions", tags=["Marketing and Promotions"])


class PromotionAnalyzer:
    def __init__(self):
        # Step 1: AI-Powered Promotion Suggestions
        self.dip_threshold_pct: float = 20.0
        self.low_sales_threshold: float = 0.5
        self.surplus_threshold: float = 1500.0

        with open("src/Calendar/us_events.json", "r", encoding="utf-8") as f:
            self.event_data = json.load(f)

        self.api_key = "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"

        self.OPENAI_SYSTEM_PROMPT = """
                        You are a creative marketing copywriter for a restaurant brand.

                        Your job is to generate short, engaging, emoji-enhanced marketing campaigns based on structured promotion suggestions provided by the restaurant’s analytics engine.

                        Each `suggestion` contains:
                        - item: the food or beverage being promoted (e.g. "Sriracha Mayo")
                        - offer_details: the promotional offer (e.g. "Happy hour pricing on selected items")
                        - reason: why it's being promoted (e.g. "High surplus alert: stock level at 1636.8 units")
                        - suggested_offer: the type of offer (e.g. "Happy Hour Feature")

                        Your task is to use these fields to write:
                        1. ✉️ **Email**: include a subject line + a short friendly body. Mention the item, the offer, and the reason.
                        2. 📱 **SMS**: 1-line catchy message with a call to action.
                        3. 📣 **Social Media Post**: punchy, fun, emoji-rich, with hashtags where appropriate.

                        Tone: energetic, positive, brand-friendly  
                        Audience: everyday restaurant guests  
                        Avoid: overly formal or generic language

                        Make it clear, exciting, and actionable — and always include relevant emojis! 🎯
                        ⚠️ Output must always be returned in this **strict JSON format**:

                        {
                        "email": "Your subject line and message here",
                        "sms": "Your 1-line SMS here",
                        "social": "Your social media post here"
                        }

                        """

        self.AGENT_SYSTEM_PROMPT = """
                    You are a smart and friendly restaurant marketing assistant. Every week, your job is to:

                    1. Review the restaurant's sales performance and inventory.
                    2. Summarize insights (top performers, dips, surplus, trends).
                    3. Recommend creative, effective promotional campaigns.
                    4. Use clear, human language and fun emoji-enhanced style.
                    5. Always include specific item names, reasons, and offer ideas.

                  Your responses should be helpful, casual, and practical—like chatting with a marketing manager who wants quick insights and actionable tips. Act as a Marketing & Promotions Agent who:

                    Shares proactive weekly campaign ideas
                    Reviews and summarizes past campaign performance
                    Recommends clear improvements
                    Suggests next steps based on results or any lagging sales
                    Keep it focused, easy to understand, and oriented toward driving results.
                    """

        self.time_segments = {
            "breakfast": range(6, 11),  # 6:00 AM - 10:59 AM
            "lunch": range(11, 15),  # 11:00 AM - 2:59 PM
            "afternoon": range(15, 17),  # 3:00 PM - 4:59 PM
            "dinner": range(17, 23),  # 5:00 PM - 10:59 PM
            "late_night": list(range(23, 24)) + list(range(0, 6))  # 11:00 PM - 5:59 AM
        }

        self.segment_promotions = {
            "breakfast": [
                {
                    "title": "Rise & Shine Special",
                    "description": "Start your day with 20% off all breakfast entrées.\nValid 6AM-9AM daily, includes free coffee upgrade.",
                    "emoji": "🌅"
                },
                {
                    "title": "Morning Power Bundle",
                    "description": "Any breakfast entrée + coffee + fresh juice at $12.99.\nPerfect fuel for busy mornings!",
                    "emoji": "🍳"
                },
                {
                    "title": "Early Bird Rewards",
                    "description": "Double loyalty points on breakfast orders before 8AM.\nPlus free pastry with any breakfast combo.",
                    "emoji": "🥐"
                }
            ],
            "lunch": [
                {
                    "title": "Lunch Express Combo",
                    "description": "Any main + side + drink in 30 mins or less.\nPerfect for busy professionals, guaranteed fast service.",
                    "emoji": "⚡"
                },
                {
                    "title": "Office Group Special",
                    "description": "15% off group orders over $100.\nFree delivery for office orders within 3 miles.",
                    "emoji": "👥"
                },
                {
                    "title": "Midday Feast Deal",
                    "description": "Build your perfect lunch: Main + 2 sides + dessert.\nSave 25% compared to à la carte pricing.",
                    "emoji": "🥗"
                }
            ],
            "afternoon": [
                {
                    "title": "Afternoon Delight Bundle",
                    "description": "Any coffee/tea + dessert combo at 30% off.\nPerfect for your afternoon break!",
                    "emoji": "☕"
                },
                {
                    "title": "Social Hour Specials",
                    "description": "Half-price appetizers & special drink prices.\nValid 2PM-5PM, perfect for casual meetings.",
                    "emoji": "🌟"
                },
                {
                    "title": "Sweet Tooth Happy Hour",
                    "description": "Buy any dessert, get one 50% off.\nPlus $2 off any specialty coffee drink.",
                    "emoji": "🧁"
                }
            ],
            "dinner": [
                {
                    "title": "Family Feast Package",
                    "description": "Family-style dinner for 4: 2 mains + 3 sides + dessert.\nSave 30% + free appetizer for family groups.",
                    "emoji": "👨‍👩‍👧‍👦"
                },
                {
                    "title": "Date Night Special",
                    "description": "2 entrées + shared appetizer + dessert + wine.\nRomantic dinner bundle with candlelit service.",
                    "emoji": "🌹"
                },
                {
                    "title": "Sunset Dinner Deal",
                    "description": "Early dinner discount: 25% off entire bill 5PM-7PM.\nIncludes complimentary chef's special appetizer.",
                    "emoji": "🌅"
                }
            ],
            "late_night": [
                {
                    "title": "Midnight Munchies Bundle",
                    "description": "Late night special: Any 2 items from our night menu.\nIncludes free midnight snack surprise!",
                    "emoji": "🌙"
                },
                {
                    "title": "Night Owl Special",
                    "description": "35% off all menu items after 11PM.\nLate night exclusive menu items available.",
                    "emoji": "🦉"
                },
                {
                    "title": "Late Night Bites Box",
                    "description": "Custom box with your favorite late-night treats.\nMix & match any 4 items for special price.",
                    "emoji": "📦"
                }
            ]
        }

        self.inventory_segments = {
            "critical_surplus": 2000,  # Very high stock
            "high_surplus": 1500,  # High stock
            "moderate_surplus": 1000,  # Moderate stock
            "optimal": 500,  # Optimal stock level
        }

        # Add detailed promotion templates for inventory
        self.inventory_promotions = {
            "critical_surplus": [
                {
                    "title": "Flash Sale Blitz",
                    "description": "48-hour special promotion with 40% off on selected items.\nQuick inventory turnover with limited time urgency.",
                    "emoji": "⚡"
                },
                {
                    "title": "Bulk Buy Bonanza",
                    "description": "Buy 3 get 1 free on featured items.\nPerfect for group orders and family packages.",
                    "emoji": "📦"
                }
            ],
            "high_surplus": [
                {
                    "title": "Combo Deal Special",
                    "description": "Create special combos featuring surplus items at 25% off.\nPair with popular menu items for better visibility.",
                    "emoji": "🎁"
                },
                {
                    "title": "Happy Hour Feature",
                    "description": "Special happy hour pricing on selected items.\nTime-limited offers during slower periods.",
                    "emoji": "🕒"
                }
            ],
            "moderate_surplus": [
                {
                    "title": "Weekend Special",
                    "description": "20% off on featured items during weekends.\nPerfect for family gatherings and group dining.",
                    "emoji": "🎈"
                },
                {
                    "title": "Loyalty Member Deal",
                    "description": "Extra points or discount for loyalty program members.\nDrive repeat customer visits while managing inventory.",
                    "emoji": "💫"
                }
            ]
        }

        # Step 2: Smart Menu Item Targeting

    def generate_promotion_suggestions(self, data: Dict) -> List[Dict]:
        """Generate all promotion suggestions by analyzing different metrics."""

        top_n: int = 5
        sales_suggestions = self.analyze_sales_dips(data.get("Daily Specials Performance", []))
        daypart_suggestions = self.analyze_daypart_trends(data.get("Time-of-Day Trends", []))
        inventory_suggestions = self.analyze_inventory(data.get("Inventory Depletion", []))

        return sales_suggestions[:top_n] + daypart_suggestions[:top_n] + inventory_suggestions[:top_n]

    def analyze_sales_dips(self, daily_sales: List[Dict]) -> List[Dict]:
        """Analyze sales dips and generate suggestions for improvements."""
        sales_sorted = sorted(daily_sales, key=lambda x: x["day"])
        amounts = [entry["total_amount"] for entry in sales_sorted]
        if not amounts:
            return []

        avg_sales = statistics.mean(amounts)
        suggestions = []

        # Define sales dip severity levels
        severity_levels = {
            40: {"level": "Critical", "emoji": "🚨", "discount": "40%", "urgency": "Immediate action required"},
            30: {"level": "High", "emoji": "⚠️", "discount": "30%", "urgency": "Urgent attention needed"},
            20: {"level": "Moderate", "emoji": "📊", "discount": "20%", "urgency": "Monitor closely"}
        }

        # Define promotion templates
        promotion_templates = [
            {
                "title": "Flash Sale Boost",
                "description": "Limited time {discount} off on all menu items.\nValid only for {day}, drive immediate sales boost.",
                "emoji": "⚡"
            },
            {
                "title": "Combo Value Deal",
                "description": "Buy any main course, get appetizer {discount} off.\nPerfect for increasing average order value.",
                "emoji": "🎁"
            },
            {
                "title": "Happy Hour Extension",
                "description": "Extended happy hour with {discount} off.\nBoost traffic during traditionally slow periods.",
                "emoji": "🕒"
            }
        ]

        for entry in sales_sorted:
            drop_pct = (avg_sales - entry["total_amount"]) / avg_sales * 100

            # Find appropriate severity level
            for threshold, severity in severity_levels.items():
                if drop_pct >= threshold:
                    import random
                    promo = random.choice(promotion_templates)

                    suggestions.append({
                        "item": f"All menu items (Low sales on {entry['day']})",
                        "severity": severity["level"],
                        "reason": (f"{severity['emoji']} Sales on {entry['day']} dropped by "
                                   f"{round(drop_pct, 1)}% compared to daily average of ${avg_sales:.2f}"),
                        "suggested_offer": promo["title"],
                        "offer_details": promo["description"].format(
                            discount=severity["discount"],
                            day=entry['day']
                        ),
                        "promotion_emoji": promo["emoji"],
                        "urgency_level": severity["urgency"],
                        "estimated_impact": (f"Potential to recover ${round(avg_sales - entry['total_amount'], 2)} "
                                             f"in lost revenue"),
                        "recommended_duration": "24 hours",
                        "implementation_priority": severity["level"]
                    })
                    break

        return suggestions

    # Helper function to get time segment
    def get_time_segment(self, hour: int) -> str:
        """Determine which time segment an hour belongs to."""
        for segment, hours in self.time_segments.items():
            if hour in hours:
                return segment
        return "other"

    def analyze_daypart_trends(self, trends: List[Dict]) -> List[Dict]:
        """Analyze daypart trends and generate suggestions for improvements."""
        suggestions = []

        for trend in trends:
            item = trend["item"]
            hourly = trend["revenue_by_hour"]
            revenues = list(hourly.values())
            if not revenues:
                continue

            avg = statistics.mean(revenues)

            # Track low performance by segment
            segment_performance = {segment: [] for segment in self.time_segments.keys()}

            for hour_str, revenue in hourly.items():
                hour = int(hour_str)
                if revenue < avg * self.low_sales_threshold:
                    segment = self.get_time_segment(hour)
                    time_label = f"{hour:02d}:00"
                    segment_performance[segment].append((time_label, revenue))

            # Generate segment-specific suggestions
            for segment, low_periods in segment_performance.items():
                if low_periods:
                    time_ranges = ", ".join([time for time, _ in low_periods])
                    avg_segment_revenue = sum([rev for _, rev in low_periods]) / len(low_periods)

                    # Get random promotion suggestion for this segment
                    import random
                    promo = random.choice(self.segment_promotions[segment])

                    suggestions.append({
                        "item": item,
                        "segment": segment.title(),
                        "reason": (f"{promo['emoji']} Low {segment} sales for {item} during {time_ranges}. "
                                   f"Average revenue: ${avg_segment_revenue:.2f}"),
                        "suggested_offer": promo["title"],
                        "offer_details": promo["description"],
                        "time_period": time_ranges,
                        "estimated_impact": "Potential to increase sales by 25-40% during affected hours"
                    })

        return suggestions

    def analyze_inventory(self, inventory: List[Dict]) -> List[Dict]:
        """Analyze inventory levels and generate detailed suggestions for improvements."""
        suggestions = []

        for ing in inventory:
            quantity = ing["quantity_available"]

            # Determine inventory segment
            segment = None
            for seg, threshold in sorted(self.inventory_segments.items(),
                                         key=lambda x: x[1], reverse=True):
                if quantity >= threshold:
                    segment = seg
                    break

            if segment and segment != "optimal":
                # Get random promotion for this segment
                import random
                promo = random.choice(self.inventory_promotions[segment])

                suggestions.append({
                    "item": ing["ingredient"],
                    "segment": segment.replace("_", " ").title(),
                    "reason": (f"{promo['emoji']} {segment.replace('_', ' ').title()} Alert: "
                               f"*{ing['ingredient']}* stock level at {round(quantity, 1)} units"),
                    "suggested_offer": promo["title"],
                    "offer_details": promo["description"],
                    "urgency_level": "High" if segment == "critical_surplus" else "Medium",
                    "potential_savings": f"Prevent potential waste of {round(quantity - self.inventory_segments['optimal'], 1)} units"
                })

        return suggestions

    # Step 2: Smart Menu Item Targeting
    def analyze_smart_menu_targets(self, data: Dict, surplus_threshold: float = 1500.0, top_n: int = 5) -> List[Dict]:
        """Identify smart menu items to target for promotions based on profit, popularity, and surplus ingredients."""

        # Define promotion templates for different item categories
        promotion_templates = {
            "premium": [
                {
                    "title": "Premium Spotlight Deal",
                    "description": "Feature this top-selling item with a 15% discount.\nHighlight quality and value proposition.",
                    "emoji": "⭐"
                },
                {
                    "title": "Gourmet Bundle",
                    "description": "Pair with complementary appetizer or dessert.\nCreate an exclusive dining experience.",
                    "emoji": "✨"
                }
            ],
            "popular": [
                {
                    "title": "Fan Favorite Special",
                    "description": "Buy one get one 30% off on our most loved items.\nLimited time offer to drive immediate sales.",
                    "emoji": "🔥"
                },
                {
                    "title": "Trending Item Deal",
                    "description": "Create a combo with this popular item as the star.\nInclude drink and side at special price.",
                    "emoji": "📈"
                }
            ],
            "surplus_reduction": [
                {
                    "title": "Chef's Special Feature",
                    "description": "Special menu items featuring surplus ingredients.\nCreative new dishes at promotional prices.",
                    "emoji": "👨‍🍳"
                },
                {
                    "title": "Limited Time Creation",
                    "description": "Unique menu item available for one week only.\nMade with fresh surplus ingredients.",
                    "emoji": "⏰"
                }
            ]
        }

        top_selling_items = data.get("Top Selling Items", [])
        top_selling_menu_items = data.get("Top-Selling Menu Items", [])
        most_profitable_items = data.get("Most Profitable Items", [])
        inventory = data.get("Inventory Depletion", [])
        inventory_depletion_by_item = data.get("Inventory Depletion by Menu Item", [])

        # Extract item names from the data
        top_selling_items = set(item["item"] if isinstance(item, dict) else item
                                for item in data.get("Top Selling Items", []))
        top_selling_menu_items = set(item["item"] if isinstance(item, dict) else item
                                     for item in data.get("Top-Selling Menu Items", []))
        most_profitable_items = set(item["item"] if isinstance(item, dict) else item
                                    for item in data.get("Most Profitable Items", []))

        menu_ingredients_map = {}
        for entry in inventory_depletion_by_item:
            item = entry.get("item")
            ingredients_dict = entry.get("ingredients_used", {})
            if item and ingredients_dict:
                menu_ingredients_map[item] = list(ingredients_dict.keys())

        # Identify surplus ingredients
        surplus_ingredients = {
            ing["ingredient"]: ing["quantity_available"]
            for ing in inventory
            if ing["quantity_available"] >= surplus_threshold
        }

        combined_top_items = top_selling_items.union(top_selling_menu_items)
        smart_suggestions = []

        for item in combined_top_items:
            ingredients = menu_ingredients_map.get(item, [])
            matching_surplus = [ing for ing in ingredients if ing in surplus_ingredients]

            # Determine item category for promotion type
            category = "premium" if item in most_profitable_items else "popular"
            if matching_surplus:
                category = "surplus_reduction"

            import random
            promo = random.choice(promotion_templates[category])

            # Calculate potential metrics
            profit_potential = "High" if item in most_profitable_items else "Medium"
            popularity_score = len([x for x in [top_selling_items, top_selling_menu_items] if item in x])

            smart_suggestions.append({
                "item": item,
                "category": category.replace("_", " ").title(),
                "suggested_offer": promo["title"],
                "offer_details": promo["description"],
                "reason": self._generate_reason(item, matching_surplus,
                                                item in most_profitable_items,
                                                popularity_score),
                "metrics": {
                    "profit_potential": profit_potential,
                    "popularity_level": f"{popularity_score}/2",
                    "surplus_ingredients": matching_surplus if matching_surplus else "None"
                },
                "implementation": {
                    "suggested_duration": "7 days",
                    "target_audience": self._get_target_audience(category),
                    "marketing_channels": self._get_marketing_channels(category)
                },
                "promotion_emoji": promo["emoji"]
            })

        # Sort by profit potential and popularity
        smart_suggestions.sort(key=lambda x: (
            x["metrics"]["profit_potential"] == "High",
            int(x["metrics"]["popularity_level"][0]),
            len(x["metrics"]["surplus_ingredients"])
        ), reverse=True)

        return smart_suggestions[:top_n]

    def _generate_reason(self, item: str, surplus_ingredients: List[str],
                         is_profitable: bool, popularity_score: int) -> str:
        """Generate detailed reasoning for the promotion suggestion."""
        reasons = []

        if is_profitable:
            reasons.append("💰 High profit margin item with proven returns")

        if popularity_score == 2:
            reasons.append("🌟 Consistently top-performing menu item")
        elif popularity_score == 1:
            reasons.append("📈 Growing customer favorite")

        if surplus_ingredients:
            reasons.append(f"📦 Helps reduce surplus of: {', '.join(surplus_ingredients)}")

        return "\n".join(reasons)

    def _get_target_audience(self, category: str) -> List[str]:
        """Define target audience based on promotion category."""
        audiences = {
            "premium": ["Fine dining enthusiasts", "Special occasion diners", "Food critics"],
            "popular": ["Regular customers", "Social media followers", "Value seekers"],
            "surplus_reduction": ["Price-sensitive customers", "Bulk buyers", "Large groups"]
        }
        return audiences.get(category, ["General audience"])

    def _get_marketing_channels(self, category: str) -> List[str]:
        """Suggest marketing channels based on promotion category."""
        channels = {
            "premium": ["Email newsletter", "Instagram", "Direct SMS to VIP customers"],
            "popular": ["Social media", "In-app notifications", "Table displays"],
            "surplus_reduction": ["Push notifications", "Daily specials board", "Staff recommendations"]
        }
        return channels.get(category, ["All channels"])

    # Feature 3: Simple Campaign Builder ✅
    def generate_campaign_copy(self, suggestions: List[Dict]) -> List[Dict]:
        """Generate rich, varied marketing campaign text for email, SMS, and social using full suggestion metadata."""

        email_templates = [
            "Subject: 🎉 Just Dropped — {item} Promo!\n\nYour taste buds are in for a treat! Enjoy our latest offer: {offer_details}\n\nWhy now? {reason}\n\nAvailable for a limited time only — stop in and savor the flavor! 🍽️",
            "Subject: 😋 Special on {item} — You Deserve This!\n\nWe're featuring {item} with an exclusive deal: {offer_details}\n\nHere's the scoop: {reason}\n\nCome enjoy it while supplies last!",
            "Subject: 🚨 {item} Spotlight Offer!\n\nCraving something bold? Try our {item} today.\n\nDeal of the week: {offer_details}\n{reason}\n\nDon’t miss this limited-time offer! 🔥",
            "Subject: 🔥 Hot Deal on {item}!\n\n{offer_details}\n\nWhy? {reason}\n\nSwing by and enjoy the savings while it lasts!",
            "Subject: 🕒 Time-Limited {item} Offer!\n\nAct fast — {offer_details}\n\nWhy now? {reason}\n\nYour next favorite meal is just a visit away."
        ]

        sms_templates = [
            "🔥 {item} Deal: {offer_details} — ",  # {reason.split(':')[0]}!
            "🚨 Promo Alert! {item}: {offer_details}.  Now live!",  # {reason.split('*')[0].strip()}
            "{item} just got better — {offer_details} available now! Limited time 🕒",
            "⏰ Hurry! {item} offer: {offer_details}. ",  # {reason.split('—')[-1].strip()}
            "📢 Flash Deal: {item} | {offer_details}. Stop in while it lasts!"
        ]

        social_templates = [
            "🎉 Introducing our latest feature: {item}!\n{offer_details}\n{reason}\n#LimitedTime #FoodieFav",
            "🔥 You asked, we delivered. {item} is now on promo!\nDeal: {offer_details}\n{reason}\nCome grab yours today 🍔",
            "🚨 {item} Special Alert!\n{offer_details}\nBecause: {reason}\nAvailable for a limited time only!",
            "🍽️ Spotlight on {item}!\nGet it now with: {offer_details}\n{reason}\n#HappyHour #RestaurantDeals",
            "✨ Crave-worthy Deal: {item}\n{offer_details}\n{reason}\nTag a friend and share the love! 💬"
        ]

        campaign_copies = []

        for suggestion in suggestions:
            item = suggestion.get("item", "Item")
            reason = suggestion.get("reason", "Because it’s a fan favorite!")
            offer_details = suggestion.get("offer_details", "Special offer available this week.")
            suggested_offer = suggestion.get("suggested_offer", "Special Deal")

            campaign_copies.append({
                "item": item,
                "reason": reason,
                "offer_details": offer_details,
                "suggested_offer": suggested_offer,
                "email": random.choice(email_templates).format(item=item, offer_details=offer_details, reason=reason),
                "sms": random.choice(sms_templates).format(item=item, offer_details=offer_details, reason=reason),
                "social": random.choice(social_templates).format(item=item, offer_details=offer_details, reason=reason)
            })

        return campaign_copies

    def generate_campaign_from_openai(self, suggestion: dict) -> dict:

        # Set the OpenAI API key
        openai.api_key = self.api_key

        # Extract data from suggestion
        item = suggestion.get("item", "use All_data")
        offer = suggestion.get("offer_details", suggestion.get("suggested_offer", "use All_data"))
        reason = suggestion.get("reason", "use All_data")

        # Build dynamic user prompt
        user_prompt = f"""

                All_data : {suggestion}
                Item: {item}
                Offer: {offer}
                Reason for Promotion: {reason}

                Please return the result strictly in this JSON format:
                {{
                "email": "Short subject + friendly body including item, offer, and reason",
                "sms": "One-line text with urgency and emoji",
                "social": "Fun, emoji-rich post with hashtags"
                }}
    """

        try:
            # Prepare messages
            messages = [
                {"role": "system", "content": self.OPENAI_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ]

            # Call OpenAI with specified model
            response = openai.chat.completions.create(
                model="gpt-4-0125-preview",
                messages=messages,
                max_tokens=1000
            )

            # Extract content
            content = response.choices[0].message.content.strip()

            # Parse JSON response
            try:
                return json.loads(content)
            except json.JSONDecodeError as json_error:
                return {
                    "error": f"Invalid JSON returned from OpenAI: {json_error}",
                    "raw_response": content,
                    "fallback": {
                        "email": f"Subject: {item} Deal!\nTry our limited-time offer: {offer}. {reason}",
                        "sms": f"{item} now on offer! {offer} — {reason}",
                        "social": f"{item} is 🔥 this week! {offer} — {reason}"
                    }
                }

        except Exception as e:
            return {
                "error": str(e),
                "fallback": {
                    "email": f"Subject: {item} Deal!\nTry our limited-time offer: {offer}. {reason}",
                    "sms": f"{item} now on offer! {offer} — {reason}",
                    "social": f"{item} is 🔥 this week! {offer} — {reason}"
                }
            }

    def get_upcoming_event_campaigns(self, days_ahead: int = 7) -> List[Dict]:
        """Return upcoming events (today + next X days), grouped by date."""
        today = datetime.today().date()
        target_dates = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_ahead + 1)]

        grouped_events = {}
        for event in self.event_data:
            event_date = event.get("date")
            if event_date in target_dates:
                if event_date not in grouped_events:
                    grouped_events[event_date] = []
                grouped_events[event_date].append({
                    "event": event.get("event"),
                    "suggested_offer": event.get("suggested_offer"),
                    "campaign_prompt": event.get("campaign_prompt")
                })

        return [
            {"date": date, "events": grouped_events[date]}
            for date in sorted(grouped_events)
        ]

    def build_companion_user_prompt(self, data: dict) -> str:

        days_ahead: int = 7
        upcoming_campaigns = analyzer.get_upcoming_event_campaigns(days_ahead)

        prompt = f"""
                    Here’s this week’s data snapshot:

                    Top Selling Items:
                    {data.get("Top Selling Items", []) or "None"}

                    📈 High Profit Items:
                    {data.get("Most Profitable Items", []) or "None"}

                    🔥 High Selling Menu Items:
                    {data.get("Top-Selling Menu Items", []) or "None"}

                    📉 Low Performing Items:
                    {data.get("Least Profitable Menu Items", []) or "None"}

                    📅 Upcoming 7-Day Events:
                    {upcoming_campaigns or "None"}

                    📦 High Inventory (Surplus Stock):
                    {data.get("Inventory Depletion", []) or "None"}

                    Please provide a brief performance summary and suggest smart, creative weekly promotions. Use emojis, highlight key opportunities, and explain why each promotion matters—all in a marketing-friendly, upbeat tone.
                                        """

        return prompt

    def generate_weekly_companion_summary(self, data: dict) -> dict:
        """
        Generates a weekly performance summary + promotional ideas based on provided campaign data.
        Uses:
        - self.aoikey (OpenAI key)
        - self.agent_prompt (system prompt for companion agent)
        """

        openai.api_key = self.api_key
        user_prompt = self.build_companion_user_prompt(data)

        try:
            response = openai.chat.completions.create(
                model="gpt-4-0125-preview",
                messages=[
                    {"role": "system", "content": self.AGENT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=1000,
                temperature=0.8
            )

            return {
                "Response": response.choices[0].message.content
            }

        except Exception as e:
            return {
                "error": str(e),
                "fallback": "⚠️ Unable to generate weekly summary at the moment. Please try again later."
            }


class PromotionRequest(BaseModel):
    restaurant_id: str = Field(..., description="Restaurant ID to analyze")


# Initialize the analyzer
analyzer = PromotionAnalyzer()


@router.get("/suggestions/{restaurant_id}", response_model=Dict[str, Any])
async def get_promotion_suggestions(
        restaurant_id: str,
        current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Generate promotion suggestions for a restaurant based on their historical data.
    """
    try:
        # Update API usage for the user
        # await update_usage(current_user["uid"])
        # Define the S3 path for the restaurant's data
        graph_base_dir = f'dashboard_graphs/{restaurant_id}/graph.json'
        # Load data from S3
        from src.dashboard import load_file_from_s3
        # Load the graph data from S3
        results = load_file_from_s3(graph_base_dir)
        if not results:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Graph data not found for this restaurant."
            )
        # Generate suggestions using the loaded data
        suggestions = analyzer.generate_promotion_suggestions(results)

        return {
            "status": "success",
            "restaurant_id": restaurant_id,
            "suggestions": suggestions,
            "generated_at": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error generating promotion suggestions: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating promotion suggestions: {str(e)}"
        )


@router.get("/smart-menu-targets/{restaurant_id}", response_model=Dict[str, Any])
async def get_smart_menu_targets(
        restaurant_id: str,
        top_n: int = 5,
        current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Generate smart menu targeting suggestions based on historical data from S3.

    Parameters:
    - restaurant_id: Unique identifier for the restaurant
    - surplus_threshold: Threshold for considering inventory as surplus (default: 1500.0)
    - top_n: Number of top suggestions to return (default: 5)

    """

    surplus_threshold: float = 1500.0
    try:
        # Update API usage for the user
        # await update_usage(current_user["uid"])

        # Load data from S3
        from src.dashboard import load_file_from_s3

        # Load data from S3
        graph_base_dir = f'dashboard_graphs/{restaurant_id}/graph.json'
        results = load_file_from_s3(graph_base_dir)

        if not results:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Graph data not found for this restaurant."
            )

        # Generate smart menu targeting suggestions
        smart_suggestions = analyzer.analyze_smart_menu_targets(
            data=results,
            surplus_threshold=surplus_threshold,
            top_n=top_n
        )

        # Add metadata and return response
        return {
            "status": "success",
            "restaurant_id": restaurant_id,
            "analysis_parameters": {
                "surplus_threshold": surplus_threshold,
                "top_n": top_n
            },
            "smart_menu_suggestions": smart_suggestions,
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "suggestion_count": len(smart_suggestions),
                "data_source": graph_base_dir
            }
        }

    except Exception as e:
        logger.error(f"Error generating smart menu targets: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating smart menu targets: {str(e)}"
        )


class CampaignRequest(BaseModel):
    suggestions: Dict[str, Any] = Field(..., description="List of promotion suggestions to generate campaigns for")


@router.post("/campaign-copy", response_model=Dict[str, Any])
async def generate_campaign_copy(
        request: CampaignRequest,
        current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Generate marketing campaign copy (email, SMS, social) for given promotion suggestions.

    Parameters:
    - suggestions: List of promotion suggestions to generate campaign copy for
    """
    try:
        # Update API usage for the user
        # await update_usage(current_user["uid"])

        # Generate campaign copies using the analyzer
        campaign_copies = analyzer.generate_campaign_from_openai(request.suggestions)

        # Add metadata and return response
        return {
            "status": "success",
            "campaign_copies": campaign_copies,
            "suggestions": request.suggestions,
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "generated_by": current_user.get("email", "Unknown"),
                "campaign_count": len(campaign_copies),
                "channels": ["email", "sms", "social"],
            },

        }

    except Exception as e:
        logger.error(f"Error generating campaign copy: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating campaign copy: {str(e)}"
        )


# First, add the request model
class EventCampaignRequest(BaseModel):
    days_ahead: int = Field(7, description="Number of days ahead to look for events", ge=1, le=30)


@router.get("/upcoming-events", response_model=Dict[str, Any])
async def get_upcoming_events(
        days_ahead: int = 7,
        current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get upcoming events and their suggested campaigns for the next X days.

    Parameters:
    - days_ahead: Number of days to look ahead (default: 7, max: 30)
    """
    try:
        # # Update API usage for the user
        # await update_usage(current_user["uid"])

        # Get upcoming event campaigns
        upcoming_campaigns = analyzer.get_upcoming_event_campaigns(days_ahead)

        # Add metadata and return response
        return {
            "status": "success",
            "upcoming_campaigns": upcoming_campaigns,
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "generated_by": current_user.get("email", "Unknown"),
                "date_range": {
                    "start_date": datetime.today().strftime("%Y-%m-%d"),
                    "end_date": (datetime.today() + timedelta(days=days_ahead)).strftime("%Y-%m-%d"),
                    "total_days": days_ahead
                },
                "total_events": sum(len(day["events"]) for day in upcoming_campaigns),
                "days_with_events": len(upcoming_campaigns)
            },
            "usage_tips": {
                "planning": "Plan campaigns at least 1 week in advance",
                "implementation": "Consider combining events on the same day",
                "customization": "Adapt campaign prompts to your brand voice"
            }
        }

    except Exception as e:
        logger.error(f"Error getting upcoming event campaigns: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting upcoming event campaigns: {str(e)}"
        )

    # Add this to your promotion_markiting.py file


@router.get("/weekly-summary-agent/{restaurant_id}", response_model=Dict[str, Any])
async def get_weekly_companion_summary(
        restaurant_id: str,
        current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Generate a weekly performance summary and promotional ideas for a restaurant
    using AI-powered analysis of their historical data.

    Parameters:
    - restaurant_id: Unique identifier for the restaurant
    """
    try:
        # Update API usage for the user
        # await update_usage(current_user["uid"])

        from src.dashboard import load_file_from_s3

        # Load data from S3
        graph_base_dir = f'dashboard_graphs/{restaurant_id}/graph.json'
        results = load_file_from_s3(graph_base_dir)

        if not results:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Graph data not found for this restaurant."
            )

        # Generate weekly summary using the analyzer
        summary = analyzer.generate_weekly_companion_summary(results)

        # Check for errors in the summary
        if "error" in summary:
            logger.error(f"Error in generating summary: {summary['error']}")
            return {
                "status": "partial_success",
                "restaurant_id": restaurant_id,
                "summary": summary["fallback"],
                "error": summary["error"],
                "metadata": {
                    "generated_at": datetime.now().isoformat(),
                    "generated_by": current_user.get("email", "Unknown"),
                    "data_source": graph_base_dir,
                    "status": "fallback_content"
                }
            }

        # Return successful response
        return {
            "status": "success",
            "restaurant_id": restaurant_id,
            "summary": summary["Response"],
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "generated_by": current_user.get("email", "Unknown"),
                "data_source": graph_base_dir,
                # "analysis_coverage": {
                #     "sales_data": bool(results.get("Top Selling Items")),
                #     "inventory_data": bool(results.get("Inventory Depletion")),
                #     "profit_data": bool(results.get("Most Profitable Items")),
                #     "events_data": bool(analyzer.event_data)
                # }
            },
            "usage_tips": {
                "frequency": "Generate new summaries weekly for best results",
                "implementation": "Use insights to plan next week's promotions",
                "customization": "Adapt suggestions to your specific market and audience"
            }
        }

    except Exception as e:
        logger.error(f"Error generating weekly summary: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating weekly summary: {str(e)}"
        )


