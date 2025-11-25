
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List
from fastapi import WebSocket
import redis.asyncio as redis  # asyncio compatible redis client

logger = logging.getLogger(__name__)

import platform

if platform.system().lower() == "windows":
    # Connect Redis client (adjust URL if needed)
    redis_client = redis.from_url("redis://localhost:6379")
else:
    redis_client = redis.from_url("redis://redis-server:6379")


## Create singleton notification manager
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional
from fastapi import WebSocket
import redis.asyncio as redis

logger = logging.getLogger(__name__)

import platform

# Make Redis connection optional
redis_client: Optional[redis.Redis] = None
redis_enabled = False
redis_connection_failed = False  # Track if we've already tried and failed

async def _test_redis_connection():
    """Test if Redis is actually reachable"""
    global redis_enabled, redis_connection_failed
    
    if redis_connection_failed:
        return False
    
    try:
        await redis_client.ping()
        redis_enabled = True
        logger.info("✅ Redis connection verified")
        return True
    except Exception as e:
        redis_enabled = False
        redis_connection_failed = True
        logger.warning(f"⚠️ Redis not reachable: {e}. Disabling Redis pub/sub permanently for this session.")
        return False

try:
    if platform.system().lower() == "windows":
        redis_client = redis.from_url("redis://localhost:6379", socket_connect_timeout=2)
    else:
        redis_client = redis.from_url("redis://redis-server:6379", socket_connect_timeout=2)
    
    logger.info("Redis client object created (connection not yet verified)")
except Exception as e:
    logger.warning(f"⚠️ Could not create Redis client: {e}. Running without Redis.")
    redis_client = None
    redis_enabled = False
    redis_connection_failed = True


class NotificationConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}
        self._redis_verified = False

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        logger.info(f"User {user_id} connected to notification websocket")

    def disconnect(self, websocket: WebSocket, user_id: int):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        logger.info(f"User {user_id} disconnected from notification websocket")

    async def broadcast_to_user(self, user_id: int, message: dict):
        """Send notification to all connections for a specific user"""
        # Ensure all datetime fields are serialized to strings
        self._serialize_datetime_in_message(message)
        
        if user_id in self.active_connections:
            disconnected_websockets = []
            for websocket in self.active_connections[user_id]:
                try:
                    await websocket.send_json(message)
                    logger.debug(f"Sent notification to user {user_id}")
                except Exception as e:
                    logger.error(f"Error sending notification to user {user_id}: {str(e)}")
                    disconnected_websockets.append(websocket)

            # Clean up any disconnected websockets
            for websocket in disconnected_websockets:
                self.active_connections[user_id].remove(websocket)

            # If all connections are gone, clean up the user entry
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        else:
            logger.debug(f"No active connections for user {user_id}")

    def _serialize_datetime_in_message(self, message: dict):
        """Helper function to ensure datetime objects are serialized to string"""
        for key, value in message.items():
            if isinstance(value, dict):
                self._serialize_datetime_in_message(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        self._serialize_datetime_in_message(item)
            elif isinstance(value, datetime):
                message[key] = value.isoformat()

    async def publish_notification(self, user_id: int, message: dict):
        """
        Publish notification via Redis (if available) or direct WebSocket.
        Falls back gracefully if Redis is unavailable.
        """
        global redis_enabled, redis_connection_failed
        
        try:
            # Serialize the message
            self._serialize_datetime_in_message(message)
            
            # Always send via direct WebSocket (primary method)
            await self.broadcast_to_user(user_id, message)
            
            # Only try Redis if we haven't already determined it's unavailable
            if redis_client and not redis_connection_failed:
                # Verify Redis connection on first use
                if not self._redis_verified:
                    is_connected = await _test_redis_connection()
                    self._redis_verified = True
                    if not is_connected:
                        return  # Redis is down, skip all future attempts
                
                # Try to publish to Redis
                if redis_enabled:
                    try:
                        payload = json.dumps({"user_id": user_id, "message": message})
                        await redis_client.publish("notifications_channel", payload)
                        logger.debug(f"Published to Redis for user {user_id}")
                    except Exception as redis_error:
                        # Mark Redis as failed to avoid future attempts
                        redis_enabled = False
                        redis_connection_failed = True
                        logger.warning(f"⚠️ Redis publish failed. Disabling Redis for this session: {redis_error}")
                        
        except Exception as e:
            logger.error(f"Failed to publish notification for user {user_id}: {e}", exc_info=True)

    async def redis_subscriber(self):
        """
        Subscribe and listen for notifications from Redis.
        Only runs if Redis is available.
        """
        if redis_connection_failed or not redis_client:
            logger.info("Redis subscriber not started - Redis is disabled")
            return
        
        # Test connection first
        if not await _test_redis_connection():
            return
            
        try:
            pubsub = redis_client.pubsub()
            await pubsub.subscribe("notifications_channel")
            logger.info("✅ Subscribed to Redis notifications_channel")

            async for msg in pubsub.listen():
                if msg is None:
                    continue
                if msg['type'] == 'message':
                    try:
                        data = json.loads(msg['data'])
                        user_id = data.get("user_id")
                        message = data.get("message")
                        if user_id and message:
                            await self.broadcast_to_user(user_id, message)
                    except Exception as e:
                        logger.error(f"Error processing Redis pubsub message: {e}")
        except Exception as e:
            logger.error(f"Redis subscriber failed: {e}. Notifications will work via direct WebSocket only.")
            return


# Create singleton notification manager
notification_manager = NotificationConnectionManager()