"""任务注册表。"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class JobRegistry:
    """同步任务注册表。"""

    def __init__(self):
        self._jobs: Dict[str, dict] = {}

    def register(self, domain: str, market: str, job_class) -> None:
        key = f"{market}_{domain}"
        self._jobs[key] = {"domain": domain, "market": market, "class": job_class}
        logger.debug(f"注册任务: {key}")

    def get_job(self, domain: str, market: str) -> Optional[dict]:
        return self._jobs.get(f"{market}_{domain}")

    def list_jobs(self, market: Optional[str] = None) -> List[dict]:
        if market:
            return [v for v in self._jobs.values() if v["market"] == market]
        return list(self._jobs.values())
