"""Redis 成绩文档存储：按（年级 + 班级）桶隔离，桶内支持多份考试文档"""

import json
import time
from typing import List, Optional
from urllib.parse import quote

import redis

from config.settings import settings

# 数据默认保留时间（秒）
TTL_SECONDS = 86400


def bucket_key(grade: str, className: str) -> str:
    """将（年级 + 班级）规范化为可读的桶 ID（原生 UTF-8，便于 Redis 查看）"""
    return f"{grade}::{className}"


class RedisGradeDocumentStore:
    """桶级成绩文档存储：原文 / 解析记录 / chunk 向量 / 桶聚合检索源"""

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
            self.migrate_legacy_encoded_keys()
        except Exception as e:
            print(f"Redis连接失败: {str(e)}")
            self.redis_client = None
            self.connected = False

    # ---------- key 构造 ----------
    @staticmethod
    def _meta_key(grade: str, className: str) -> str:
        return f"document:grade:bucket:{bucket_key(grade, className)}"

    @classmethod
    def _doc_key(cls, grade: str, className: str, exam_name: str) -> str:
        return f"{cls._meta_key(grade, className)}:doc:{exam_name}"

    @classmethod
    def _records_key(cls, grade: str, className: str, exam_name: str) -> str:
        return f"{cls._doc_key(grade, className, exam_name)}:records"

    @classmethod
    def _chunks_key(cls, grade: str, className: str, exam_name: str) -> str:
        return f"{cls._doc_key(grade, className, exam_name)}:chunks"

    @classmethod
    def _bucket_chunks_key(cls, grade: str, className: str) -> str:
        return f"{cls._meta_key(grade, className)}:chunks"

    def _set_ttl(self, key: str):
        if self.connected:
            self.redis_client.expire(key, TTL_SECONDS)

    # ---------- 旧版百分号编码 key 迁移（幂等） ----------
    def _copy_key(self, src: str, dst: str) -> bool:
        """按类型复制一个 key 的值到新 key（源不存在视为已复制）"""
        if not self.connected:
            return False
        try:
            t = self.redis_client.type(src)
            if t == "string":
                val = self.redis_client.get(src)
                if val is None:
                    return True
                self.redis_client.set(dst, val)
            elif t == "list":
                vals = self.redis_client.lrange(src, 0, -1)
                if not vals:
                    return True
                self.redis_client.rpush(dst, *vals)
            else:
                return True
            self._set_ttl(dst)
            return True
        except Exception as e:
            print(f"Redis迁移复制失败: {str(e)}")
            return False

    def _delete_legacy_bucket(self, meta_key: str, metadata: dict):
        """删除旧版命名（百分号编码）的整个桶 key 集合"""
        try:
            for doc in metadata.get("docs", []):
                exam_name = doc.get("examName", "")
                old_doc = f"{meta_key}:doc:{quote(exam_name, safe='')}"
                self.redis_client.delete(
                    old_doc,
                    old_doc + ":records",
                    old_doc + ":chunks",
                )
            self.redis_client.delete(meta_key, meta_key + ":chunks")
        except Exception as e:
            print(f"Redis删除旧桶失败: {str(e)}")

    def migrate_legacy_encoded_keys(self) -> int:
        """将旧版百分号编码的桶 key 迁移为可读的原生 UTF-8 key（幂等，可重复执行）"""
        if not self.connected:
            return 0
        prefix = "document:grade:bucket:"
        migrated = 0
        try:
            for key in list(self.redis_client.scan_iter(match=f"{prefix}*")):
                suffix = key[len(prefix):]
                if ":doc:" in suffix or suffix.endswith(":chunks"):
                    continue
                if "%" not in suffix:
                    continue
                raw = self.redis_client.get(key)
                if not raw:
                    continue
                try:
                    metadata = json.loads(raw)
                except Exception:
                    continue
                grade = metadata.get("grade", "")
                className = metadata.get("className", "")
                if not grade or not className:
                    continue
                new_meta_key = self._meta_key(grade, className)
                if self.redis_client.exists(new_meta_key):
                    # 新键已存在（之前迁移过），仅清理旧键
                    self._delete_legacy_bucket(key, metadata)
                    migrated += 1
                    continue
                all_moved = True
                for doc in metadata.get("docs", []):
                    exam_name = doc.get("examName", "")
                    old_doc = f"{key}:doc:{quote(exam_name, safe='')}"
                    pairs = [
                        (old_doc, self._doc_key(grade, className, exam_name)),
                        (old_doc + ":records", self._records_key(grade, className, exam_name)),
                        (old_doc + ":chunks", self._chunks_key(grade, className, exam_name)),
                    ]
                    for old_k, new_k in pairs:
                        if not self._copy_key(old_k, new_k):
                            all_moved = False
                old_agg = key + ":chunks"
                new_agg = self._bucket_chunks_key(grade, className)
                if not self._copy_key(old_agg, new_agg):
                    all_moved = False
                if all_moved:
                    metadata["bucketId"] = bucket_key(grade, className)
                    self.redis_client.set(
                        new_meta_key,
                        json.dumps(metadata, ensure_ascii=False)
                    )
                    self._set_ttl(new_meta_key)
                    self._delete_legacy_bucket(key, metadata)
                    migrated += 1
                else:
                    print(f"Redis键迁移不完整，保留旧键以便重试: {key}")
        except Exception as e:
            print(f"Redis迁移失败: {str(e)}")
        return migrated

    # ---------- 桶元数据与文档写入 ----------
    def store_document(self, grade: str, className: str, exam_name: str, text: str,
                       records: List[dict], chunks: List[dict],
                       filename: str = "", student_count: int = 0,
                       subject_count: int = 0):
        """存储 / 替换单份考试文档，并重建桶聚合检索源"""
        if not self.connected:
            return
        try:
            meta_key = self._meta_key(grade, className)
            doc_key = self._doc_key(grade, className, exam_name)
            records_key = self._records_key(grade, className, exam_name)
            chunks_key = self._chunks_key(grade, className, exam_name)

            self.redis_client.set(doc_key, text)
            self.redis_client.delete(records_key, chunks_key)
            if records:
                self.redis_client.rpush(
                    records_key,
                    *[json.dumps(r, ensure_ascii=False) for r in records]
                )
            if chunks:
                self.redis_client.rpush(
                    chunks_key,
                    *[json.dumps(c, ensure_ascii=False) for c in chunks]
                )
            for key in (doc_key, records_key, chunks_key):
                self._set_ttl(key)

            metadata = self.get_bucket_metadata(grade, className) or {
                "grade": grade,
                "className": className,
                "bucketId": bucket_key(grade, className),
                "docs": [],
            }
            docs = [d for d in metadata.get("docs", []) if d.get("examName") != exam_name]
            docs.append({
                "examName": exam_name,
                "filename": filename,
                "uploadedAt": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "textLength": len(text or ""),
                "studentCount": student_count,
                "subjectCount": subject_count,
            })
            metadata["docs"] = docs
            self.redis_client.set(meta_key, json.dumps(metadata, ensure_ascii=False))
            self._set_ttl(meta_key)

            self.rebuild_bucket_chunks(grade, className)
        except Exception as e:
            print(f"Redis存储失败: {str(e)}")

    def get_bucket_metadata(self, grade: str, className: str) -> Optional[dict]:
        if not self.connected:
            return None
        try:
            raw = self.redis_client.get(self._meta_key(grade, className))
            if not raw:
                return None
            metadata = json.loads(raw)
            # 归一化 bucketId（兼容旧版百分号编码元数据）
            metadata["bucketId"] = bucket_key(grade, className)
            return metadata
        except Exception as e:
            print(f"Redis获取桶元数据失败: {str(e)}")
            return None

    def list_buckets(self) -> List[dict]:
        """列出全部桶（scan_iter 代替 keys，避免阻塞）"""
        if not self.connected:
            return []
        try:
            prefix = "document:grade:bucket:"
            buckets = []
            for key in self.redis_client.scan_iter(match=f"{prefix}*"):
                suffix = key[len(prefix):]
                # 子键（:doc: / :chunks）不是桶元数据
                if ":doc:" in suffix or suffix.endswith(":chunks"):
                    continue
                raw = self.redis_client.get(key)
                if raw:
                    metadata = json.loads(raw)
                    # 归一化 bucketId（兼容旧版百分号编码元数据）
                    metadata["bucketId"] = bucket_key(
                        metadata.get("grade", ""),
                        metadata.get("className", ""),
                    )
                    buckets.append(metadata)
            buckets.sort(key=lambda b: (b.get("grade", ""), b.get("className", "")))
            return buckets
        except Exception as e:
            print(f"Redis列出桶失败: {str(e)}")
            return []

    # ---------- 单份考试读写 ----------
    def get_document(self, grade: str, className: str, exam_name: str) -> Optional[str]:
        if not self.connected:
            return None
        try:
            return self.redis_client.get(self._doc_key(grade, className, exam_name))
        except Exception as e:
            print(f"Redis获取文档失败: {str(e)}")
            return None

    def get_records(self, grade: str, className: str, exam_name: str) -> List[dict]:
        if not self.connected:
            return []
        try:
            values = self.redis_client.lrange(
                self._records_key(grade, className, exam_name), 0, -1
            )
            return [json.loads(v) for v in values]
        except Exception as e:
            print(f"Redis获取记录失败: {str(e)}")
            return []

    def get_doc_chunks(self, grade: str, className: str, exam_name: str) -> List[dict]:
        if not self.connected:
            return []
        try:
            values = self.redis_client.lrange(
                self._chunks_key(grade, className, exam_name), 0, -1
            )
            return [json.loads(v) for v in values]
        except Exception as e:
            print(f"Redis获取chunk失败: {str(e)}")
            return []

    # ---------- 桶聚合检索源 ----------
    def get_bucket_chunks(self, grade: str, className: str) -> List[dict]:
        if not self.connected:
            return []
        try:
            values = self.redis_client.lrange(
                self._bucket_chunks_key(grade, className), 0, -1
            )
            return [json.loads(v) for v in values]
        except Exception as e:
            print(f"Redis获取聚合chunk失败: {str(e)}")
            return []

    def rebuild_bucket_chunks(self, grade: str, className: str):
        """将桶内所有考试文档的 chunk 平铺合并为聚合检索源"""
        if not self.connected:
            return
        try:
            metadata = self.get_bucket_metadata(grade, className)
            agg_key = self._bucket_chunks_key(grade, className)
            self.redis_client.delete(agg_key)
            if not metadata:
                return
            all_chunks = []
            for doc in metadata.get("docs", []):
                exam_name = doc.get("examName", "")
                chunks = self.get_doc_chunks(grade, className, exam_name)
                if chunks:
                    all_chunks.extend(chunks)
            if all_chunks:
                self.redis_client.rpush(
                    agg_key,
                    *[json.dumps(c, ensure_ascii=False) for c in all_chunks]
                )
                self._set_ttl(agg_key)
        except Exception as e:
            print(f"Redis重建聚合chunk失败: {str(e)}")

    def get_bucket_full_text(self, grade: str, className: str) -> Optional[str]:
        """兜底：无向量 chunk 时拼接桶内全部原文"""
        if not self.connected:
            return None
        try:
            metadata = self.get_bucket_metadata(grade, className)
            if not metadata:
                return None
            parts = []
            for doc in metadata.get("docs", []):
                exam_name = doc.get("examName", "")
                text = self.get_document(grade, className, exam_name)
                if text:
                    parts.append(f"【{grade}{className}·{exam_name}】\n{text}")
            return "\n\n---\n\n".join(parts) if parts else None
        except Exception as e:
            print(f"Redis获取桶原文失败: {str(e)}")
            return None

    # ---------- 删除 ----------
    def delete_document(self, grade: str, className: str, exam_name: str):
        """删除单份考试文档；桶内无文档时删除桶元数据"""
        if not self.connected:
            return
        try:
            self.redis_client.delete(
                self._doc_key(grade, className, exam_name),
                self._records_key(grade, className, exam_name),
                self._chunks_key(grade, className, exam_name),
            )
            metadata = self.get_bucket_metadata(grade, className)
            if metadata:
                docs = [d for d in metadata.get("docs", []) if d.get("examName") != exam_name]
                if docs:
                    metadata["docs"] = docs
                    self.redis_client.set(
                        self._meta_key(grade, className),
                        json.dumps(metadata, ensure_ascii=False)
                    )
                    self._set_ttl(self._meta_key(grade, className))
                else:
                    self.redis_client.delete(self._meta_key(grade, className))
            self.rebuild_bucket_chunks(grade, className)
        except Exception as e:
            print(f"Redis删除文档失败: {str(e)}")

    def delete_bucket(self, grade: str, className: str):
        """删除整个桶（含全部考试文档与聚合检索源）"""
        if not self.connected:
            return
        try:
            metadata = self.get_bucket_metadata(grade, className)
            if metadata:
                for doc in metadata.get("docs", []):
                    exam_name = doc.get("examName", "")
                    self.redis_client.delete(
                        self._doc_key(grade, className, exam_name),
                        self._records_key(grade, className, exam_name),
                        self._chunks_key(grade, className, exam_name),
                    )
            self.redis_client.delete(
                self._meta_key(grade, className),
                self._bucket_chunks_key(grade, className),
            )
        except Exception as e:
            print(f"Redis删除桶失败: {str(e)}")
