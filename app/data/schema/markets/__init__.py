"""市场特化字段。"""

from app.data.schema.markets.cn import CNBasicInfoFields as CNBasicInfoFields
from app.data.schema.markets.hk import (
    HKBasicInfoFields as HKBasicInfoFields,
    HKDailyIndicatorsFields as HKDailyIndicatorsFields,
    HKCorporateActionsFields as HKCorporateActionsFields,
    HKMarketQuotesFields as HKMarketQuotesFields,
    HKFinancialDataFields as HKFinancialDataFields,
)
from app.data.schema.markets.us import (
    USBasicInfoFields as USBasicInfoFields,
    USDailyQuotesFields as USDailyQuotesFields,
    USFinancialDataFields as USFinancialDataFields,
    USMarketQuotesFields as USMarketQuotesFields,
)
