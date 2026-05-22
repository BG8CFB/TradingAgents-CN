"""MongoDB 存储层。"""

from app.data.storage.mongo.client import get_motor_db as get_motor_db
from app.data.storage.mongo.collections import get_collection_name as get_collection_name
from app.data.storage.mongo.indexes import ensure_indexes as ensure_indexes
