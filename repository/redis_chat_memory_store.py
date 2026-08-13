import redis
import json
from typing import List, Optional
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
        self.redis_client.lpush(key, json.dumps(message, ensure_ascii=False))
        # 保留时长由 REDIS_TTL_SECONDS 配置（默认 30 天）
        self.redis_client.expire(key, settings.redis_ttl_seconds)
    
    def get_messages(self, memory_id: str) -> List[dict]:
        """获取指定memory_id的所有消息"""
        key = f"chat:memory:{memory_id}"
        messages = self.redis_client.lrange(key, 0, -1)
        return [json.loads(msg) for msg in messages]

    def get_summary(self, memory_id: str) -> Optional[str]:
        """获取会话滚动摘要（早期对话压缩结果）"""
        key = f"chat:memory:{memory_id}:summary"
        return self.redis_client.get(key)

    def save_summary(self, memory_id: str, summary: str):
        """保存会话滚动摘要"""
        key = f"chat:memory:{memory_id}:summary"
        self.redis_client.set(key, summary)
        self.redis_client.expire(key, settings.redis_ttl_seconds)

    def trim_messages(self, memory_id: str, keep: int):
        """只保留最新的 keep 条消息（列表按新→旧存储，旧的从尾部移除）"""
        key = f"chat:memory:{memory_id}"
        self.redis_client.ltrim(key, 0, keep - 1)
    
    def delete_messages(self, memory_id: str):
        """删除指定memory_id的聊天记忆与滚动摘要"""
        key = f"chat:memory:{memory_id}"
        summary_key = f"chat:memory:{memory_id}:summary"
        self.redis_client.delete(key, summary_key)
