"""DataInterface's screening namespace; repository details stay in the data layer.

Read methods never refresh market data. Write methods are explicit application
operations, including the atomic guards used by optional paid insight generation.
"""

from typing import Dict, List, Optional

from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo
from app.data.storage.mongo.repositories.screening_insights_repo import ScreeningInsightsRepo
from app.data.storage.mongo.repositories.screening_recommendations_repo import ScreeningRecommendationsRepo


class ScreeningGateway:
    async def latest_factor_trade_date(self, market: str) -> Optional[str]:
        return await FactorScoresRepo().get_latest_trade_date(market)

    async def latest_recommendations(self, market: str,
                                     strategy_id: Optional[str] = None) -> List[Dict]:
        repo = ScreeningRecommendationsRepo()
        if strategy_id:
            doc = await repo.get_latest_by_strategy(market, strategy_id)
            return [doc] if doc else []
        latest = await repo.get_latest_any(market)
        return await repo.list_strategies_on_date(market, latest["trade_date"]) if latest else []

    async def latest_strategy_recommendation(self, market: str,
                                             strategy_id: str) -> Optional[Dict]:
        return await ScreeningRecommendationsRepo().get_latest_by_strategy(market, strategy_id)

    async def save_generated_recommendation(self, doc: Dict, market: str) -> None:
        await ScreeningRecommendationsRepo().upsert_generated(doc, market)

    async def claim_recommendation_insight(self, doc: Dict, market: str) -> bool:
        return await ScreeningRecommendationsRepo().claim_insight(doc, market)

    async def finish_recommendation_insight(self, doc: Dict, market: str) -> bool:
        return await ScreeningRecommendationsRepo().finish_insight(doc, market)

    async def count_completed_manual_insights(self, user_id: str, day: str) -> int:
        return await ScreeningInsightsRepo().count_today_done(user_id, day)

    async def append_insight_audit(self, doc: Dict) -> None:
        await ScreeningInsightsRepo().insert_one(doc)
