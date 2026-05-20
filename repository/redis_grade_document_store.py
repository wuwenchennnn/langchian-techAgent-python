import redis
from typing import Optional
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
            # 测试连接
            self.redis_client.ping()
            self.connected = True
        except Exception as e:
            print(f"Redis连接失败: {str(e)}")
            self.redis_client = None
            self.connected = False
    
    def store_document(self, memory_id: str, content: str):
        """存储文档内容到Redis"""
        if not self.connected:
            return
        try:
            key = f"document:grade:{memory_id}"
            self.redis_client.set(key, content)
            # 设置过期时间为24小时
            self.redis_client.expire(key, 86400)
        except Exception as e:
            print(f"Redis存储失败: {str(e)}")
    
    def get_document(self, memory_id: str) -> Optional[str]:
        """获取指定memory_id的文档内容"""
        if not self.connected:
            return None
        try:
            key = f"document:grade:{memory_id}"
            return self.redis_client.get(key)
        except Exception as e:
            print(f"Redis获取失败: {str(e)}")
            return None
    
    def delete_document(self, memory_id: str):
        """删除指定memory_id的文档内容"""
        if not self.connected:
            return
        try:
            key = f"document:grade:{memory_id}"
            self.redis_client.delete(key)
        except Exception as e:
            print(f"Redis删除失败: {str(e)}")