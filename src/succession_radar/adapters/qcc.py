"""QCC (企查查) adapter — bring your own credentials.

This adapter shows the shape of the private-company data path. It
calls the official QCC open platform (openapi.qcc.com), which
requires a corporate-verified account and paid API credits. Without
credentials it raises immediately and tells you why.

Why there is no scraping fallback: scraping Chinese registry data
behind anti-bot measures has led to criminal convictions in China,
and the "it was public anyway" defense has been rejected in court
((2019)闽0524刑初397号). The official API is the only path this
project supports. For access from outside mainland China, QCC's
Singapore entity (qcckyc.com) is the sanctioned route.

Endpoints used (per QCC's published catalog):
- 企业工商详情 (ECIV4/GetBasicDetailsByName): registration, legal rep, capital
- 股东信息: shareholder names and percentages
- 变更记录: change history, used to compute legal-rep tenure
- 疑似实际控制人: suspected actual controller
"""

from __future__ import annotations

import os
from typing import Iterable

from succession_radar.adapters.base import Adapter, Company


class QccAdapter(Adapter):
    name = "qcc"

    def __init__(self, app_key: str | None = None, secret: str | None = None):
        self.app_key = app_key or os.environ.get("QCC_APP_KEY")
        self.secret = secret or os.environ.get("QCC_SECRET_KEY")
        if not self.app_key or not self.secret:
            raise RuntimeError(
                "QCC credentials missing. Set QCC_APP_KEY and QCC_SECRET_KEY. "
                "You need a corporate-verified account on openapi.qcc.com "
                "(or qcckyc.com from outside mainland China). "
                "This is deliberate: the data layer is the part you bring."
            )

    def companies(self) -> Iterable[Company]:
        raise NotImplementedError(
            "Wire this to the QCC endpoints listed in the module docstring. "
            "The mapping target is the Company dataclass in adapters/base.py."
        )
