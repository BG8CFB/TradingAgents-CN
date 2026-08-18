"""
Backup, import, and export routines extracted from DatabaseService.
"""

from __future__ import annotations

import json
import os
import re
import gzip
import asyncio
import subprocess
import shutil
import tempfile
from typing import Any, Dict, List, Optional
import logging

from bson import ObjectId

from app.core.database import get_mongo_db
from app.core.config import settings
from .serialization import serialize_document
from app.utils.timezone import now_utc, format_date_compact

logger = logging.getLogger(__name__)

# 备份名称安全字符：字母、数字、下划线、中划线、中文
_BACKUP_NAME_RE = re.compile(r"^[a-zA-Z0-9_一-鿿\-]{1,120}$")


def _build_mongodump_args_and_env(
    backup_path: str, collection_name: Optional[str]
) -> tuple[List[str], Dict[str, str]]:
    """构建 mongodump 命令参数，不含任何凭据（凭据通过 --config 临时 YAML 文件传递）。

    将 MongoDB 凭据从 ``--uri`` 命令行参数迁移到 mongodump 的 ``--config`` YAML 配置文件，
    避免 ``ps aux`` 等进程列表暴露完整 URI（含用户名密码）。

    YAML 配置文件在调用方创建、使用后立即删除（见 ``_run_mongodump``）。

    Args:
        backup_path: mongodump --out 输出目录
        collection_name: 可选的集合名

    Returns:
        (cmd_args, env_overlay) — env_overlay 始终为空 dict（保留接口兼容）
    """
    cmd = [
        "mongodump",
        "--host",
        settings.MONGODB_HOST,
        "--port",
        str(settings.MONGODB_PORT),
        "--db",
        settings.MONGODB_DATABASE,
        "--out",
        backup_path,
        "--gzip",
    ]
    if settings.MONGODB_USERNAME:
        cmd.extend(["--username", settings.MONGODB_USERNAME])
    auth_source = getattr(settings, "MONGODB_AUTH_SOURCE", "admin")
    if auth_source:
        cmd.extend(["--authenticationDatabase", auth_source])

    if collection_name:
        cmd.extend(["--collection", collection_name])

    return cmd, {}


def _check_mongodump_available() -> bool:
    """检查 mongodump 命令是否可用"""
    return shutil.which("mongodump") is not None


def _validate_backup_name(name: str) -> str:
    """校验备份名称，防止路径遍历。

    允许：字母、数字、下划线、中划线、中文（1-120 字符）。
    禁止：路径分隔符（/ \\）、点号点（..）、空字符等。

    Args:
        name: 用户传入的备份名称。

    Returns:
        校验通过后的安全名称（basename 后的安全值）。

    Raises:
        ValueError: 名称包含非法字符。
    """
    if not name:
        raise ValueError("备份名称不能为空")

    # 先取 basename 防御性剥离路径分隔符
    safe_name = os.path.basename(name)

    if safe_name != name:
        raise ValueError(f"备份名称不能包含路径分隔符: {name!r}")

    if ".." in name:
        raise ValueError("备份名称不能包含路径遍历字符 '..'")

    if not _BACKUP_NAME_RE.match(name):
        raise ValueError("备份名称只能包含字母、数字、下划线、中划线和中文，长度 1-120")

    return safe_name


async def create_backup_native(
    name: str,
    backup_dir: str,
    collections: Optional[List[str]] = None,
    user_id: str | None = None,
) -> Dict[str, Any]:
    """
    使用 MongoDB 原生 mongodump 命令创建备份（推荐，速度快）

    优势：
    - 速度快（直接操作 BSON，不需要 JSON 转换）
    - 压缩效率高
    - 支持大数据量
    - 并行处理多个集合

    要求：
    - 系统中需要安装 MongoDB Database Tools
    - mongodump 命令在 PATH 中可用
    """
    if not _check_mongodump_available():
        raise RuntimeError(
            "mongodump 命令不可用，请安装 MongoDB Database Tools 或使用 create_backup() 方法"
        )

    name = _validate_backup_name(name)

    db = get_mongo_db()

    backup_id = str(ObjectId())
    timestamp = format_date_compact(now_utc()) + "_" + now_utc().strftime("%H%M%S")
    backup_dirname = f"backup_{name}_{timestamp}"
    backup_path = os.path.join(backup_dir, backup_dirname)

    os.makedirs(backup_dir, exist_ok=True)

    # mongodump 的 --collection 是覆盖语义（一次仅支持单集合）。
    # 多集合时需逐个执行，否则 --collection 循环追加后只备份最后一个（R14 SVC-01）。
    collections_to_dump = list(collections) if collections else [None]

    logger.info(f"🔄 开始执行 mongodump 备份: {name}")

    # 🔥 使用 asyncio.to_thread 在线程池中执行阻塞的 subprocess 调用
    def _run_mongodump():
        last_result = None

        for collection_name in collections_to_dump:
            cmd, _ = _build_mongodump_args_and_env(backup_path, collection_name)

            # 将密码写入临时 YAML 配置文件，通过 --config 传递
            # mongodump 100.x+ 支持 --config，凭据不出现在 ps ARGV 列
            config_path: Optional[str] = None
            try:
                if settings.MONGODB_PASSWORD:
                    import yaml as _yaml

                    config_path = tempfile.mktemp(
                        suffix=".yaml", prefix="mongodump_cfg_"
                    )
                    config_content = {"password": settings.MONGODB_PASSWORD}
                    with open(config_path, "w", encoding="utf-8") as f:
                        _yaml.dump(config_content, f, default_flow_style=False)
                    os.chmod(config_path, 0o600)
                    cmd = ["mongodump", "--config", config_path] + cmd[1:]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=3600,  # 1小时超时
                )
            finally:
                # 用完即删，避免凭据残留
                if config_path and os.path.exists(config_path):
                    try:
                        os.unlink(config_path)
                    except OSError:
                        logger.warning(f"无法删除临时配置文件: {config_path}")
            if result.returncode != 0:
                coll_desc = f"（集合 {collection_name}）" if collection_name else ""
                raise RuntimeError(f"mongodump 执行失败{coll_desc}: {result.stderr}")
            last_result = result
        return last_result

    try:
        await asyncio.to_thread(_run_mongodump)
        logger.info(f"✅ mongodump 备份完成: {name}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("备份超时（超过1小时）")
    except Exception as e:
        logger.error(f"❌ mongodump 备份失败: {e}")
        # 清理失败的备份目录
        if os.path.exists(backup_path):
            await asyncio.to_thread(shutil.rmtree, backup_path)
        raise

    # 计算备份大小
    def _get_dir_size(path):
        total = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                total += os.path.getsize(filepath)
        return total

    file_size = await asyncio.to_thread(_get_dir_size, backup_path)

    # 获取实际备份的集合列表
    if not collections:
        collections = await db.list_collection_names()
        collections = [c for c in collections if not c.startswith("system.")]

    backup_meta = {
        "_id": ObjectId(backup_id),
        "name": name,
        "filename": backup_dirname,
        "file_path": backup_path,
        "size": file_size,
        "collections": collections,
        "created_at": now_utc(),
        "created_by": user_id,
        "backup_type": "mongodump",  # 标记备份类型
    }

    await db.database_backups.insert_one(backup_meta)

    return {
        "id": backup_id,
        "name": name,
        "filename": backup_dirname,
        "file_path": backup_path,
        "size": file_size,
        "collections": collections,
        "created_at": backup_meta["created_at"].isoformat(),
        "backup_type": "mongodump",
    }


async def create_backup(
    name: str,
    backup_dir: str,
    collections: Optional[List[str]] = None,
    user_id: str | None = None,
) -> Dict[str, Any]:
    """
    创建数据库备份（Python 实现，兼容性好但速度较慢）

    对于大数据量（>100MB），建议使用 create_backup_native() 方法
    """
    name = _validate_backup_name(name)

    db = get_mongo_db()

    backup_id = str(ObjectId())
    timestamp = format_date_compact(now_utc()) + "_" + now_utc().strftime("%H%M%S")
    backup_filename = f"backup_{name}_{timestamp}.json.gz"
    backup_path = os.path.join(backup_dir, backup_filename)

    if not collections:
        # 过滤 system. 前缀集合（含 system_secrets 等敏感集合），
        # 与 create_backup_native() 行 150 / export_data() 行 508 对齐，避免密钥泄漏到备份文件
        collections = [
            c for c in await db.list_collection_names() if not c.startswith("system.")
        ]

    backup_data: Dict[str, Any] = {
        "backup_id": backup_id,
        "name": name,
        "created_at": now_utc().isoformat(),
        "created_by": user_id,
        "collections": collections,
        "data": {},
    }

    for collection_name in collections:
        collection = db[collection_name]
        documents: List[dict] = []
        async for doc in collection.find():
            documents.append(serialize_document(doc))
        backup_data["data"][collection_name] = documents

    os.makedirs(backup_dir, exist_ok=True)

    # 🔥 使用 asyncio.to_thread 将阻塞的文件 I/O 操作放到线程池执行
    def _write_backup():
        with gzip.open(backup_path, "wt", encoding="utf-8") as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2)
        return os.path.getsize(backup_path)

    file_size = await asyncio.to_thread(_write_backup)

    backup_meta = {
        "_id": ObjectId(backup_id),
        "name": name,
        "filename": backup_filename,
        "file_path": backup_path,
        "size": file_size,
        "collections": collections,
        "created_at": now_utc(),
        "created_by": user_id,
    }

    await db.database_backups.insert_one(backup_meta)

    return {
        "id": backup_id,
        "name": name,
        "filename": backup_filename,
        "file_path": backup_path,
        "size": file_size,
        "collections": collections,
        "created_at": backup_meta["created_at"].isoformat(),
    }


async def list_backups() -> List[Dict[str, Any]]:
    db = get_mongo_db()
    backups: List[Dict[str, Any]] = []
    async for backup in db.database_backups.find().sort("created_at", -1):
        backups.append(
            {
                "id": str(backup["_id"]),
                "name": backup["name"],
                "filename": backup["filename"],
                "size": backup["size"],
                "collections": backup["collections"],
                "created_at": backup["created_at"].isoformat(),
                "created_by": backup.get("created_by"),
            }
        )
    return backups


async def delete_backup(backup_id: str) -> None:
    db = get_mongo_db()
    backup = await db.database_backups.find_one({"_id": ObjectId(backup_id)})
    if not backup:
        raise RuntimeError("备份不存在")
    if os.path.exists(backup["file_path"]):
        # 🔥 使用 asyncio.to_thread 将阻塞的文件删除操作放到线程池执行
        backup_type = backup.get("backup_type", "python")
        if backup_type == "mongodump":
            # mongodump 备份是目录，需要递归删除
            await asyncio.to_thread(shutil.rmtree, backup["file_path"])
        else:
            # Python 备份是单个文件
            await asyncio.to_thread(os.remove, backup["file_path"])
    await db.database_backups.delete_one({"_id": ObjectId(backup_id)})


def _convert_date_fields(doc: dict) -> dict:
    """
    转换文档中的日期字段（字符串 -> datetime）

    常见的日期字段：
    - created_at, updated_at, completed_at
    - started_at, finished_at
    - analysis_date (保持字符串格式，因为是日期而非时间戳)
    """
    from dateutil import parser

    date_fields = [
        "created_at",
        "updated_at",
        "completed_at",
        "started_at",
        "finished_at",
        "deleted_at",
        "last_login",
        "last_modified",
        "timestamp",
    ]

    for field in date_fields:
        if field in doc and isinstance(doc[field], str):
            try:
                # 尝试解析日期字符串
                doc[field] = parser.parse(doc[field])
                logger.debug(f"✅ 转换日期字段 {field}: {doc[field]}")
            except Exception as e:
                logger.warning(f"⚠️ 无法解析日期字段 {field}: {doc[field]}, 错误: {e}")

    return doc


async def import_data(
    content: bytes,
    collection: str,
    *,
    format: str = "json",
    overwrite: bool = False,
    filename: str | None = None,
) -> Dict[str, Any]:
    """
    导入数据到数据库

    支持两种导入模式：
    1. 单集合模式：导入数据到指定集合
    2. 多集合模式：导入包含多个集合的导出文件（自动检测）
    """
    db = get_mongo_db()

    if format.lower() == "json":
        # 🔥 使用 asyncio.to_thread 将阻塞的 JSON 解析放到线程池执行
        def _parse_json():
            return json.loads(content.decode("utf-8"))

        data = await asyncio.to_thread(_parse_json)
    else:
        raise RuntimeError(f"不支持的格式: {format}")

    # 检测是否为多集合导出格式
    logger.info(f"🔍 [导入检测] 数据类型: {type(data)}")

    # 🔥 新格式：包含 export_info 和 data 的字典
    if isinstance(data, dict) and "export_info" in data and "data" in data:
        logger.info("📦 检测到新版多集合导出文件（包含 export_info）")
        export_info = data.get("export_info", {})
        logger.info(
            f"📋 导出信息: 创建时间={export_info.get('created_at')}, 集合数={len(export_info.get('collections', []))}"
        )

        # 提取实际数据
        data = data["data"]
        logger.info(f"📦 包含 {len(data)} 个集合: {list(data.keys())}")

    # 🔥 旧格式：直接是集合名到文档列表的映射
    if isinstance(data, dict):
        logger.info(f"🔍 [导入检测] 字典包含 {len(data)} 个键")
        logger.info(f"🔍 [导入检测] 键列表: {list(data.keys())[:10]}")  # 只显示前10个

        # 检查每个键值对的类型
        for k, v in list(data.items())[:5]:  # 只检查前5个
            logger.info(
                f"🔍 [导入检测] 键 '{k}': 值类型={type(v)}, 是否为列表={isinstance(v, list)}"
            )
            if isinstance(v, list):
                logger.info(f"🔍 [导入检测] 键 '{k}': 列表长度={len(v)}")

    if isinstance(data, dict) and all(
        isinstance(k, str) and isinstance(v, list) for k, v in data.items()
    ):
        # 多集合模式
        logger.info(f"📦 确认为多集合导入模式，包含 {len(data)} 个集合")

        total_inserted = 0
        imported_collections = []

        for coll_name, documents in data.items():
            # 防御性校验：拒绝非法集合名（路由层已校验单集合参数，此处覆盖多集合文件内容）
            if not re.match(
                r"^[a-zA-Z_][a-zA-Z0-9_]*$", coll_name
            ) or coll_name.startswith("system."):
                logger.warning(f"⚠️ 跳过非法集合名: {coll_name}")
                continue

            if not documents:  # 跳过空集合
                logger.info(f"⏭️ 跳过空集合: {coll_name}")
                continue

            collection_obj = db[coll_name]

            if overwrite:
                deleted_count = await collection_obj.delete_many({})
                logger.info(
                    f"🗑️ 清空集合 {coll_name}：删除 {deleted_count.deleted_count} 条文档"
                )

            # 处理 _id 字段和日期字段
            for doc in documents:
                # 转换 _id
                if "_id" in doc and isinstance(doc["_id"], str):
                    try:
                        doc["_id"] = ObjectId(doc["_id"])
                    except Exception as e:
                        logger.debug(f"ObjectId转换失败: {e}")
                        del doc["_id"]

                # 🔥 转换日期字段（字符串 -> datetime）
                # 适用于用户配置备份
                _convert_date_fields(doc)

            # 插入数据
            if documents:
                res = await collection_obj.insert_many(documents)
                inserted_count = len(res.inserted_ids)
                total_inserted += inserted_count
                imported_collections.append(coll_name)
                logger.info(f"✅ 导入集合 {coll_name}：{inserted_count} 条文档")

        return {
            "mode": "multi_collection",
            "collections": imported_collections,
            "total_collections": len(imported_collections),
            "total_inserted": total_inserted,
            "filename": filename,
            "format": format,
            "overwrite": overwrite,
        }
    else:
        # 单集合模式（兼容旧版本）
        logger.info(f"📄 单集合导入模式，目标集合: {collection}")
        logger.info(f"🔍 [单集合模式] 数据类型: {type(data)}")

        if isinstance(data, dict):
            logger.info(f"🔍 [单集合模式] 字典包含 {len(data)} 个键")
            logger.info(f"🔍 [单集合模式] 键列表: {list(data.keys())[:10]}")

        collection_obj = db[collection]

        if not isinstance(data, list):
            logger.info("🔍 [单集合模式] 数据不是列表，转换为列表")
            data = [data]

        logger.info(f"🔍 [单集合模式] 准备插入 {len(data)} 条文档")

        if overwrite:
            deleted_count = await collection_obj.delete_many({})
            logger.info(
                f"🗑️ 清空集合 {collection}：删除 {deleted_count.deleted_count} 条文档"
            )

        for doc in data:
            # 转换 _id
            if "_id" in doc and isinstance(doc["_id"], str):
                try:
                    doc["_id"] = ObjectId(doc["_id"])
                except Exception as e:
                    logger.debug(f"ObjectId转换失败: {e}")
                    del doc["_id"]

            # 🔥 转换日期字段（字符串 -> datetime）
            # 适用于系统配置备份
            _convert_date_fields(doc)

        inserted_count = 0
        if data:
            res = await collection_obj.insert_many(data)
            inserted_count = len(res.inserted_ids)

        return {
            "mode": "single_collection",
            "collection": collection,
            "inserted_count": inserted_count,
            "filename": filename,
            "format": format,
            "overwrite": overwrite,
        }


def _sanitize_document(doc: Any) -> Any:
    """
    递归清空文档中的敏感字段

    敏感字段关键词：api_key, api_secret, secret, token, password,
                    client_secret, webhook_secret, private_key

    排除字段：max_tokens, timeout, retry_times 等配置字段（不是敏感信息）
    """
    SENSITIVE_KEYWORDS = [
        "api_key",
        "api_secret",
        "secret",
        "token",
        "password",
        "client_secret",
        "webhook_secret",
        "private_key",
    ]

    # 排除的字段（虽然包含敏感关键词，但不是敏感信息）
    EXCLUDED_FIELDS = [
        "max_tokens",  # LLM 配置：最大 token 数
        "timeout",  # 超时时间
        "retry_times",  # 重试次数
        "context_length",  # 上下文长度
    ]

    if isinstance(doc, dict):
        sanitized = {}
        for k, v in doc.items():
            # 检查是否在排除列表中
            if k.lower() in [f.lower() for f in EXCLUDED_FIELDS]:
                # 保留该字段
                if isinstance(v, (dict, list)):
                    sanitized[k] = _sanitize_document(v)
                else:
                    sanitized[k] = v
            # 检查字段名是否包含敏感关键词（忽略大小写）
            elif any(keyword in k.lower() for keyword in SENSITIVE_KEYWORDS):
                sanitized[k] = ""  # 清空敏感字段
            elif isinstance(v, (dict, list)):
                sanitized[k] = _sanitize_document(v)  # 递归处理
            else:
                sanitized[k] = v
        return sanitized
    elif isinstance(doc, list):
        return [_sanitize_document(item) for item in doc]
    else:
        return doc


async def export_data(
    collections: Optional[List[str]] = None,
    *,
    export_dir: str,
    format: str = "json",
    sanitize: bool = False,
) -> str:
    """导出数据库数据到文件。

    JSON 格式使用流式写入（逐集合逐文档序列化），避免全量数据驻留内存。
    CSV/XLSX 格式逐集合处理（pandas 仍需单集合驻留，但不再同时持有所有集合）。
    """
    import pandas as pd

    db = get_mongo_db()
    timestamp = format_date_compact(now_utc()) + "_" + now_utc().strftime("%H%M%S")

    if not collections:
        collections = await db.list_collection_names()
        collections = [c for c in collections if not c.startswith("system.")]

    os.makedirs(export_dir, exist_ok=True)

    if format.lower() == "json":
        filename = f"export_{timestamp}.json.gz"
        file_path = os.path.join(export_dir, filename)

        # 流式 JSON 写入：逐集合迭代 cursor，逐文档序列化到 gzip 文件。
        # 生产者-消费者模式：async 端迭代 cursor 入队，线程端消费写文件。
        doc_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        _SENTINEL = object()

        async def _produce():
            """异步生产者：逐集合迭代 cursor，批量入队。"""
            try:
                for collection_name in collections:
                    if sanitize and collection_name == "users":
                        await doc_queue.put((collection_name, []))
                        continue

                    collection = db[collection_name]
                    batch: List[dict] = []
                    async for doc in collection.find():
                        serialized = serialize_document(doc)
                        if sanitize:
                            serialized = _sanitize_document(serialized)
                        batch.append(serialized)
                        if len(batch) >= 200:
                            await doc_queue.put((collection_name, batch))
                            batch = []
                    if batch:
                        await doc_queue.put((collection_name, batch))
            finally:
                await doc_queue.put(_SENTINEL)

        def _consume(loop: asyncio.AbstractEventLoop) -> int:
            """同步消费者：从队列读取数据，流式写入 gzip JSON 文件。"""
            with gzip.open(file_path, "wt", encoding="utf-8") as f:
                # 写入 JSON 头部
                f.write("{")
                f.write('"export_info": {')
                f.write(f'"created_at": "{now_utc().isoformat()}", ')
                f.write(
                    f'"collections": {json.dumps(collections, ensure_ascii=False)}, '
                )
                f.write('"format": "json"')
                f.write("}, ")
                f.write('"data": {')

                first_collection = True
                current_collection: Optional[str] = None
                collection_first_doc = True

                while True:
                    fut = asyncio.run_coroutine_threadsafe(doc_queue.get(), loop)
                    item = fut.result(timeout=3600)

                    if item is _SENTINEL:
                        if current_collection is not None:
                            f.write("]")
                        break

                    coll_name, docs = item

                    if coll_name != current_collection:
                        if current_collection is not None:
                            f.write("]")
                        if not first_collection:
                            f.write(", ")
                        f.write(f'"{coll_name}": [')
                        current_collection = coll_name
                        first_collection = False
                        collection_first_doc = True

                    for doc in docs:
                        if not collection_first_doc:
                            f.write(", ")
                        f.write(json.dumps(doc, ensure_ascii=False))
                        collection_first_doc = False

                f.write("}}")

            return os.path.getsize(file_path)

        loop = asyncio.get_running_loop()
        producer_task = asyncio.create_task(_produce())
        await asyncio.to_thread(_consume, loop)
        await producer_task

        return file_path

    # ── CSV 格式：逐文档流式写入，分批 flush ──
    if format.lower() == "csv":
        filename = f"export_{timestamp}.csv"
        file_path = os.path.join(export_dir, filename)

        async def _produce_csv(row_queue: asyncio.Queue):
            try:
                for collection_name in collections:
                    if sanitize and collection_name == "users":
                        continue
                    collection = db[collection_name]
                    async for doc in collection.find():
                        serialized = serialize_document(doc)
                        if sanitize:
                            serialized = _sanitize_document(serialized)
                        row = {**serialized, "_collection": collection_name}
                        await row_queue.put(row)
            finally:
                await row_queue.put(_SENTINEL)

        row_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

        def _consume_csv(loop: asyncio.AbstractEventLoop) -> int:
            rows_buffer: List[dict] = []
            first_write = True

            def _flush():
                nonlocal first_write
                if not rows_buffer:
                    return
                df = pd.DataFrame(rows_buffer)
                df.to_csv(
                    file_path,
                    index=False,
                    encoding="utf-8-sig",
                    mode="w" if first_write else "a",
                    header=first_write,
                )
                rows_buffer.clear()
                first_write = False

            while True:
                fut = asyncio.run_coroutine_threadsafe(row_queue.get(), loop)
                item = fut.result(timeout=3600)

                if item is _SENTINEL:
                    _flush()
                    break

                rows_buffer.append(item)
                if len(rows_buffer) >= 1000:
                    _flush()

            return os.path.getsize(file_path) if os.path.exists(file_path) else 0

        loop = asyncio.get_running_loop()
        producer_task = asyncio.create_task(_produce_csv(row_queue))
        await asyncio.to_thread(_consume_csv, loop)
        await producer_task
        return file_path

    # ── XLSX 格式：逐集合写入 sheet ──
    if format.lower() in ["xlsx", "excel"]:
        filename = f"export_{timestamp}.xlsx"
        file_path = os.path.join(export_dir, filename)

        collection_data: Dict[str, List[dict]] = {}

        for collection_name in collections:
            if sanitize and collection_name == "users":
                collection_data[collection_name] = []
                continue

            collection = db[collection_name]
            docs: List[dict] = []
            async for doc in collection.find():
                serialized = serialize_document(doc)
                if sanitize:
                    serialized = _sanitize_document(serialized)
                docs.append(serialized)
            collection_data[collection_name] = docs

        def _write_excel():
            with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
                for collection_name, documents in collection_data.items():
                    df = pd.DataFrame(documents) if documents else pd.DataFrame()
                    sheet = collection_name[:31]
                    df.to_excel(writer, sheet_name=sheet, index=False)

        await asyncio.to_thread(_write_excel)
        return file_path

    raise RuntimeError(f"不支持的导出格式: {format}")
