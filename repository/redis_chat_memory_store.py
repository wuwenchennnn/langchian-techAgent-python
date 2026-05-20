import redis
import json
from typing import List
from config.settings import settings


class RedisChatMemoryStore:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_database,
            password=settings.redis_password,
            decode_responses=True
        )
    
    def save_message(self, memory_id: str, role: str, content: str):
        """保存消息到Redis"""
        key = f"chat:memory:{memory_id}"
        message = {
            "role": role,
            "content": content,
            "timestamp": json.dumps({"$date": "2024-01-01T00:00:00Z"})
        }
        self.redis_client.lpush(key, json.dumps(message))
        # 设置过期时间为24小时
        self.redis_client.expire(key, 86400)
    
    def get_messages(self, memory_id: str) -> List[dict]:
        """获取指定memory_id的所有消息"""
        key = f"chat:memory:{memory_id}"
        messages = self.redis_client.lrange(key, 0, -1)
        return [json.loads(msg) for msg in messages]
    
    def delete_messages(self, memory_id: str):
        """删除指定memory_id的所有消息"""
        key = f"chat:memory:{memory_id}"
        self.redis_client.delete(key)
