"""
测试基础设施 - 模拟数据库和 Redis 实现

提供 SimulatedMongoDB 和 SimulatedRedis，使用内存数据结构模拟真实服务
"""

import os
from contextlib import contextmanager
import uuid


@contextmanager
def env_vars(mapping: dict, clear: bool = False):
    """临时设置环境变量的上下文管理器（替代 unittest.mock.patch.dict）"""
    original = {}
    if clear:
        original = dict(os.environ)
        os.environ.clear()
    for key, value in mapping.items():
        original[key] = os.environ.get(key, _SENTINEL)
        os.environ[key] = value
    try:
        yield
    finally:
        for key, old_value in original.items():
            if old_value is _SENTINEL:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


_SENTINEL = object()


def _match_filter(doc: dict, filter_dict: dict) -> bool:
    """判断文档是否匹配 MongoDB 风格过滤条件，支持 $or/$ne 等操作符。"""
    for key, condition in filter_dict.items():
        if key == "$or":
            if not any(_match_filter(doc, sub) for sub in condition):
                return False
            continue
        if key == "$and":
            if not all(_match_filter(doc, sub) for sub in condition):
                return False
            continue
        value = doc.get(key)
        if isinstance(condition, dict):
            # 操作符条件，如 {"$ne": "value"}
            for op, op_val in condition.items():
                if op == "$ne":
                    if value == op_val:
                        return False
                elif op == "$gt":
                    if value is None or value <= op_val:
                        return False
                elif op == "$gte":
                    if value is None or value < op_val:
                        return False
                elif op == "$lt":
                    if value is None or value >= op_val:
                        return False
                elif op == "$lte":
                    if value is None or value > op_val:
                        return False
                elif op == "$in":
                    if value not in op_val:
                        return False
                elif op == "$nin":
                    if value in op_val:
                        return False
                elif op == "$exists":
                    if op_val and key not in doc:
                        return False
                    if not op_val and key in doc:
                        return False
                else:
                    # 未知操作符，回退到等值匹配
                    if value != condition:
                        return False
        else:
            if value != condition:
                return False
    return True


class SimulatedMongoCollection:
    """使用内存字典模拟 MongoDB 集合行为"""

    def __init__(self, initial_data=None):
        self._data = {}
        self._counter = 0
        if initial_data:
            for doc in initial_data:
                self._insert(doc)

    def _insert(self, doc):
        self._counter += 1
        if "_id" not in doc:
            doc["_id"] = uuid.uuid4().hex[:24]
        self._data[str(doc["_id"])] = doc
        return doc["_id"]

    async def insert_one(self, doc):
        oid = self._insert(doc)
        return type("Result", (), {"inserted_id": oid})()

    async def find_one(self, filter_dict=None, projection=None):
        if not filter_dict:
            return next(iter(self._data.values()), None)
        for doc in self._data.values():
            if _match_filter(doc, filter_dict):
                return doc
        return None

    async def update_one(self, filter_dict, update_dict, **kwargs):
        upsert = kwargs.get("upsert", False)
        doc = await self.find_one(filter_dict)
        if doc:
            if "$set" in update_dict:
                doc.update(update_dict["$set"])
            elif "$inc" in update_dict:
                for k, v in update_dict["$inc"].items():
                    doc[k] = doc.get(k, 0) + v
            else:
                doc.update(update_dict)
            return type("Result", (), {"modified_count": 1, "matched_count": 1})()
        elif upsert:
            new_doc = dict(filter_dict)
            if "$set" in update_dict:
                new_doc.update(update_dict["$set"])
            else:
                new_doc.update(update_dict)
            self._insert(new_doc)
            return type("Result", (), {"modified_count": 0, "matched_count": 0, "upserted_id": new_doc["_id"]})()
        return type("Result", (), {"modified_count": 0, "matched_count": 0})()

    async def delete_one(self, filter_dict):
        for key, doc in list(self._data.items()):
            if _match_filter(doc, filter_dict):
                del self._data[key]
                return type("Result", (), {"deleted_count": 1})()
        return type("Result", (), {"deleted_count": 0})()

    async def delete_many(self, filter_dict):
        """批量删除匹配的文档。"""
        deleted = 0
        for key, doc in list(self._data.items()):
            if _match_filter(doc, filter_dict):
                del self._data[key]
                deleted += 1
        return type("Result", (), {"deleted_count": deleted})()

    async def count_documents(self, filter_dict=None):
        if not filter_dict:
            return len(self._data)
        return sum(1 for doc in self._data.values()
                   if _match_filter(doc, filter_dict))

    def find(self, filter_dict=None, *args, **kwargs):
        return SimulatedCursor(self._data.values(), filter_dict)

    def aggregate(self, pipeline, *args, **kwargs):
        return SimulatedCursor(self._data.values(), {})

    async def create_index(self, *args, **kwargs):
        pass

    async def insert_many(self, docs):
        """批量插入文档。"""
        ids = []
        for doc in docs:
            oid = self._insert(doc)
            ids.append(oid)
        return type("Result", (), {"inserted_ids": ids})()

    async def distinct(self, field, filter_dict=None):
        """获取指定字段的不重复值列表。"""
        values = set()
        for doc in self._data.values():
            if filter_dict is None or _match_filter(doc, filter_dict):
                val = doc.get(field)
                if val is not None:
                    values.add(val)
        return list(values)


class SimulatedCursor:
    """模拟 MongoDB 游标"""

    def __init__(self, docs, filter_dict=None):
        self._docs = list(docs)
        if filter_dict:
            self._docs = [d for d in self._docs if _match_filter(d, filter_dict)]
        self._skip = 0
        self._limit = 0

    def sort(self, *args, **kwargs):
        # 排序不影响模拟结果，直接返回自身
        if args and isinstance(args[0], list):
            pass  # MongoDB 格式: [("field", 1), ...]
        return self

    def skip(self, n):
        self._skip = n
        return self

    def limit(self, n):
        self._limit = n
        return self

    async def to_list(self, length=None):
        result = self._docs[self._skip:]
        if length and length > 0:
            result = result[:length]
        return result

    def __aiter__(self):
        sliced = self._docs[self._skip:]
        if self._limit and self._limit > 0:
            sliced = sliced[:self._limit]
        self._iter = iter(sliced)
        self._consumed = 0
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class SimulatedMongoDB:
    """使用内存字典模拟 MongoDB 数据库"""

    def __init__(self):
        self._collections = {}

    def __getattr__(self, name):
        if name.startswith("_"):
            return object.__getattribute__(self, name)
        if name not in self._collections:
            self._collections[name] = SimulatedMongoCollection()
        return self._collections[name]

    def __getitem__(self, name):
        """支持 db["collection"] 语法。"""
        return self.__getattr__(name)

    async def list_collection_names(self):
        return list(self._collections.keys())

    async def command(self, cmd, **kwargs):
        return {"ok": 1}


class SimulatedRedis:
    """使用内存字典模拟 Redis 客户端"""

    def __init__(self):
        self._data = {}
        self._sets = {}
        self._lists = {}
        self._hashes = {}
        # sorted set: key → list of (member, score)，保持插入顺序便于测试可预测
        self._zsets = {}

    async def ping(self):
        return True

    async def get(self, key):
        return self._data.get(key)

    async def set(self, key, value, **kwargs):
        self._data[key] = value
        return True

    async def delete(self, *keys):
        count = 0
        for k in keys:
            hit = False
            if k in self._data:
                del self._data[k]
                hit = True
            if k in self._zsets:
                del self._zsets[k]
                hit = True
            if k in self._sets:
                del self._sets[k]
                hit = True
            if k in self._lists:
                del self._lists[k]
                hit = True
            if hit:
                count += 1
        return count

    async def exists(self, key):
        return 1 if key in self._data else 0

    async def expire(self, key, ttl):
        return True

    async def close(self):
        pass

    async def hset(self, name, key=None, value=None, mapping=None, **kwargs):
        if name not in self._hashes:
            self._hashes[name] = {}
        if mapping:
            self._hashes[name].update(mapping)
        elif key is not None:
            self._hashes[name][key] = value

    async def hgetall(self, name):
        return self._hashes.get(name, {})

    async def lpush(self, key, *values):
        if key not in self._lists:
            self._lists[key] = []
        for v in values:
            self._lists[key].insert(0, v)
        return len(self._lists[key])

    async def rpop(self, key, **kwargs):
        if key not in self._lists or not self._lists[key]:
            return None
        return self._lists[key].pop()

    async def sadd(self, key, *values):
        if key not in self._sets:
            self._sets[key] = set()
        self._sets[key].update(values)
        return len(values)

    async def scard(self, key):
        return len(self._sets.get(key, set()))

    async def incr(self, key):
        val = int(self._data.get(key, 0)) + 1
        self._data[key] = str(val)
        return val

    # ── Sorted set 操作（用于限流器）────────────────────────────────
    async def zadd(self, key, mapping):
        """mapping: {member: score}，相同 member 更新 score。"""
        zset = self._zsets.setdefault(key, {})
        for member, score in mapping.items():
            zset[member] = float(score)
        return len(mapping)

    async def zremrangebyscore(self, key, min_score, max_score):
        """删除 score 在 [min, max] 区间内的所有 member。"""
        zset = self._zsets.get(key, {})
        if not zset:
            return 0
        # min/max 可以是数字或字符串（含 "(" 表示开区间），这里简化为闭区间数字
        def _to_float(v):
            if isinstance(v, (int, float)):
                return float(v), True
            if isinstance(v, str) and v.startswith("("):
                return float(v[1:]), False  # 开区间
            return float(v), True
        lo, lo_inclusive = _to_float(min_score)
        hi, hi_inclusive = _to_float(max_score)
        removed = 0
        for member in list(zset.keys()):
            score = zset[member]
            ok_low = score >= lo if lo_inclusive else score > lo
            ok_high = score <= hi if hi_inclusive else score < hi
            if ok_low and ok_high:
                del zset[member]
                removed += 1
        return removed

    async def zcard(self, key):
        return len(self._zsets.get(key, {}))

    def pipeline(self):
        """返回一个支持上下文管理器的 SimulatedPipeline。

        pipeline 缓存命令并在 execute() 时按顺序执行，返回结果列表。
        """
        return SimulatedPipeline(self)


class SimulatedPipeline:
    """模拟 redis-py 的 Pipeline：缓存命令、按序执行、返回结果列表。"""

    def __init__(self, redis: "SimulatedRedis"):
        self._redis = redis
        self._commands = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            # 不立即执行，留给 execute() 触发；模拟 redis-py 行为
            pass
        return False

    def zadd(self, key, mapping):
        self._commands.append(("zadd", key, mapping))
        return self

    def zremrangebyscore(self, key, min_score, max_score):
        self._commands.append(("zremrangebyscore", key, min_score, max_score))
        return self

    def zcard(self, key):
        self._commands.append(("zcard", key))
        return self

    def expire(self, key, ttl):
        self._commands.append(("expire", key, ttl))
        return self

    async def execute(self):
        results = []
        for cmd in self._commands:
            op = cmd[0]
            if op == "zadd":
                _, key, mapping = cmd
                results.append(await self._redis.zadd(key, mapping))
            elif op == "zremrangebyscore":
                _, key, lo, hi = cmd
                results.append(await self._redis.zremrangebyscore(key, lo, hi))
            elif op == "zcard":
                _, key = cmd
                results.append(await self._redis.zcard(key))
            elif op == "expire":
                results.append(True)
            else:
                raise NotImplementedError(f"SimulatedPipeline 不支持命令: {op}")
        self._commands.clear()
        return results
