"""MongoDB Repository 层。"""

from app.data.storage.mongo.repositories.basic_info_repo import BasicInfoRepo as BasicInfoRepo
from app.data.storage.mongo.repositories.daily_quotes_repo import DailyQuotesRepo as DailyQuotesRepo
from app.data.storage.mongo.repositories.daily_indicators_repo import DailyIndicatorsRepo as DailyIndicatorsRepo
from app.data.storage.mongo.repositories.adj_factors_repo import AdjFactorsRepo as AdjFactorsRepo
from app.data.storage.mongo.repositories.corporate_actions_repo import CorporateActionsRepo as CorporateActionsRepo
from app.data.storage.mongo.repositories.financial_data_repo import FinancialDataRepo as FinancialDataRepo
from app.data.storage.mongo.repositories.market_quotes_repo import MarketQuotesRepo as MarketQuotesRepo
from app.data.storage.mongo.repositories.news_repo import NewsRepo as NewsRepo
from app.data.storage.mongo.repositories.trade_calendar_repo import TradeCalendarRepo as TradeCalendarRepo
from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo as MetadataRepo
from app.data.storage.mongo.repositories.intraday_quotes_repo import IntradayQuotesRepo as IntradayQuotesRepo
from app.data.storage.mongo.repositories.money_flow_repo import MoneyFlowRepo as MoneyFlowRepo
from app.data.storage.mongo.repositories.margin_trading_repo import MarginTradingRepo as MarginTradingRepo
from app.data.storage.mongo.repositories.dragon_tiger_repo import DragonTigerRepo as DragonTigerRepo
from app.data.storage.mongo.repositories.block_trade_repo import BlockTradeRepo as BlockTradeRepo
from app.data.storage.mongo.repositories.connect_status_repo import ConnectStatusRepo as ConnectStatusRepo
from app.data.storage.mongo.repositories.southbound_holding_repo import SouthboundHoldingRepo as SouthboundHoldingRepo
from app.data.storage.mongo.repositories.pre_post_market_repo import PrePostMarketRepo as PrePostMarketRepo
