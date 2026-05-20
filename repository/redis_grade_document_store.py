import json
from typing import List, Optional

import redis

from config.settings import settings


class RedisGradeDocumentStore:
    def __init__(self):
        try:
            self.redis_client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_database,
                password=settings.redis_password,
                decode_responses=True
            )
            self.redis_client.ping()
            self.connected = True
        except Exception as e:
            print(f"Redis连接失败: {str(e)}")
            self.redis_client = None
            self.connected = False

    def store_document(self, memory_id: str, content: str):
        if not self.connected:
            return
        try:
            key = f"document:grade:{memory_id}"
            self.redis_client.set(key, content)
            self.redis_client.expire(key, 86400)
        except Exception as e:
            print(f"Redis存储失败: {str(e)}")

    def get_document(self, memory_id: str) -> Optional[str]:
        if not self.connected:
            return None
        try:
            key = f"document:grade:{memory_id}"
            return self.redis_client.get(key)
        except Exception as e:
            print(f"Redis获取失败: {str(e)}")
            return None

    def store_chunks(self, memory_id: str, chunks: List[dict]):
        if not self.connected:
            return
        try:
            key = f"document:grade:{memory_id}:chunks"
            self.redis_client.delete(key)
            if chunks:
                self.redis_client.rpush(key, *[json.dumps(chunk, ensure_ascii=False) for chunk in chunks])
            self.redis_client.expire(key, 86400)
        except Exception as e:
            print(f"Redis切块存储失败: {str(e)}")

    def get_chunks(self, memory_id: str) -> List[dict]:
        if not self.connected:
            return []
        try:
            key = f"document:grade:{memory_id}:chunks"
            values = self.redis_client.lrange(key, 0, -1)
            return [json.loads(value) for value in values]
        except Exception as e:
            print(f"Redis切块获取失败: {str(e)}")
            return []

    def delete_document(self, memory_id: str):
        if not self.connected:
            return
        try:
            document_key = f"document:grade:{memory_id}"
            chunks_key = f"document:grade:{memory_id}:chunks"
            self.redis_client.delete(document_key, chunks_key)
        except Exception as e:
            print(f"Redis删除失败: {str(e)}")
