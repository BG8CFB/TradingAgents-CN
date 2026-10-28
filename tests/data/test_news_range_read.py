"""news 区间读取测试 — Reader news 分支与 NewsRepo 增量/区间方法。

使用 inject_sim_db（内存 Mongo，真实代码路径），验证：
- Reader 按 symbol + 日期区间读取 news（DataInterface 标准签名透传）
- NewsRepo.get_updated_since 增量扫描（知识库索引游标）
- count_by_market / latest_publish_time（知识库语料概览）
"""

from app.data.core.reader import Reader
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.news_repo import NewsRepo


def _news_doc(symbol: str, title: str, publish_time: str, updated_at: str) -> dict:
    return {
        "symbol": symbol,
        "market": "CN",
        "data_source": "akshare",
        "title": title,
        "content": f"{title} 正文",
        "publish_time": publish_time,
        "updated_at": updated_at,
        "type": "news",
        "url": "",
    }


class TestReaderNewsRange:
    async def test_symbol_with_date_range_filters_by_publish_time(self, inject_sim_db):
        coll = inject_sim_db[get_collection_name("news", "CN")]
        await coll.insert_many([
            _news_doc("000001", "范围内-早", "2024-06-02 09:00:00", "2024-06-02 09:00:05"),
            _news_doc("000001", "范围内-晚", "2024-06-20 15:00:00", "2024-06-20 15:00:05"),
            _news_doc("000001", "范围外-前", "2024-05-31 23:00:00", "2024-05-31 23:00:05"),
            _news_doc("000001", "范围外-后", "2024-07-01 08:00:00", "2024-07-01 08:00:05"),
            _news_doc("600000", "其它标的", "2024-06-10 10:00:00", "2024-06-10 10:00:05"),
        ])

        reader = Reader()
        data, _freshness = await reader.get_data(
            "CN", "news",
            symbol="000001",
            start_date="2024-06-01",
            end_date="2024-06-30",
            filters={},
        )
        titles = {d["title"] for d in data}
        assert titles == {"范围内-早", "范围内-晚"}

    async def test_symbol_without_range_falls_back_to_recent(self, inject_sim_db):
        coll = inject_sim_db[get_collection_name("news", "CN")]
        await coll.insert_many([
            _news_doc("000001", "新闻A", "2024-06-01 09:00:00", "2024-06-01 09:00:05"),
            _news_doc("600000", "新闻B", "2024-06-02 09:00:00", "2024-06-02 09:00:05"),
        ])

        reader = Reader()
        data, _freshness = await reader.get_data(
            "CN", "news", symbol="000001", filters={},
        )
        assert [d["title"] for d in data] == ["新闻A"]

    async def test_hk_market_uses_suffixed_collection(self, inject_sim_db):
        coll = inject_sim_db[get_collection_name("news", "HK")]
        await coll.insert_many([
            {
                "symbol": "00700", "market": "HK", "data_source": "akshare_hk",
                "title": "腾讯新闻", "publish_time": "2024-06-15 10:00:00",
                "updated_at": "2024-06-15 10:00:05", "type": "news",
            },
        ])

        reader = Reader()
        data, _freshness = await reader.get_data(
            "HK", "news", symbol="00700",
            start_date="2024-06-01", end_date="2024-06-30", filters={},
        )
        assert [d["title"] for d in data] == ["腾讯新闻"]


class TestNewsRepoIncremental:
    async def test_get_updated_since_checkpoint(self, inject_sim_db):
        coll = inject_sim_db[get_collection_name("news", "CN")]
        await coll.insert_many([
            _news_doc("000001", "第一批", "2024-06-01 09:00:00", "2024-06-01 09:00:05"),
            _news_doc("000001", "第二批", "2024-06-02 09:00:00", "2024-06-02 09:00:05"),
            _news_doc("000001", "第三批", "2024-06-03 09:00:00", "2024-06-03 09:00:05"),
        ])

        repo = NewsRepo()
        all_docs = await repo.get_updated_since("CN", None)
        assert {d["title"] for d in all_docs} == {"第一批", "第二批", "第三批"}

        incremental = await repo.get_updated_since("CN", "2024-06-01 09:00:05")
        assert {d["title"] for d in incremental} == {"第二批", "第三批"}

        fresh = await repo.get_updated_since("CN", "2024-06-03 09:00:05")
        assert fresh == []

    async def test_count_and_latest_publish(self, inject_sim_db):
        coll = inject_sim_db[get_collection_name("news", "CN")]
        await coll.insert_many([
            _news_doc("000001", "新闻1", "2024-06-01 09:00:00", "2024-06-01 09:00:05"),
            _news_doc("600000", "新闻2", "2024-06-05 09:00:00", "2024-06-05 09:00:05"),
        ])

        repo = NewsRepo()
        assert await repo.count_by_market("CN") == 2
        assert await repo.latest_publish_time("CN") == "2024-06-05 09:00:00"
