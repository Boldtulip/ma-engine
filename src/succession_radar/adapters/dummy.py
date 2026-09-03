"""Synthetic demo data.

Generates a deterministic set of fictional Chinese SMEs whose owners,
shareholders, and finances look statistically plausible. Every name
and company here is invented; any match with a real person or company
is coincidence. This is the fuel the repository ships so the engine
runs out of the box — real fuel is plugged in through the other
adapters.
"""

from __future__ import annotations

import random
from typing import Iterable

from succession_radar.adapters.base import Adapter, Company, Person

SURNAMES = ["王", "李", "张", "刘", "陈", "杨", "黄", "赵", "周", "吴",
            "徐", "孙", "马", "朱", "胡", "郭", "何", "林", "郑", "宋"]

# Given names grouped by generation (matching the cohort table).
OLD_GIVEN = ["建国", "建华", "国庆", "建军", "卫东", "志强", "志国", "建平",
             "秀兰", "桂英", "秀英", "玉兰", "凤英", "淑英", "国强", "爱国",
             "春华", "军", "勇", "华", "明"]
MID_GIVEN = ["伟", "强", "涛", "斌", "辉", "红", "梅", "艳", "娟", "芳",
             "丽", "晓东", "晓明", "雪梅", "燕", "霞", "萍"]
YOUNG_GIVEN = ["磊", "静", "杰", "娜", "婷", "超", "鹏", "雪", "帅", "浩",
               "宇", "俊杰", "文静", "丹"]

REGIONS = ["浙江温州", "浙江宁波", "江苏苏州", "江苏无锡", "广东东莞",
           "广东佛山", "福建泉州", "山东青岛", "河北沧州", "上海"]

INDUSTRIES = ["精密机械制造", "汽车零部件", "纺织服装", "塑料制品", "五金工具",
              "食品加工", "包装印刷", "电子元器件", "建材", "化工原料"]

COMPANY_WORDS = ["宏", "泰", "利", "丰", "顺", "达", "鑫", "隆", "华", "盛",
                 "永", "昌", "瑞", "凯", "腾", "旭", "威", "捷", "恒", "远"]


class DummyAdapter(Adapter):
    name = "dummy"

    def __init__(self, n: int = 200, seed: int = 42):
        self.n = n
        self.seed = seed

    def companies(self) -> Iterable[Company]:
        rng = random.Random(self.seed)
        for i in range(self.n):
            surname = rng.choice(SURNAMES)
            # Two thirds of founders belong to the older generations.
            pool = OLD_GIVEN if rng.random() < 0.45 else (
                MID_GIVEN if rng.random() < 0.7 else YOUNG_GIVEN)
            founder = surname + rng.choice(pool)

            region = rng.choice(REGIONS)
            industry = rng.choice(INDUSTRIES)
            word = rng.choice(COMPANY_WORDS) + rng.choice(COMPANY_WORDS)
            cname = f"{region[:2]}{word}{industry[:2]}有限公司"

            founded = rng.randint(1988, 2018)
            own_pct = rng.choice([100.0, 90.0, 80.0, 70.0, 60.0, 51.0])

            shareholders = [Person(founder, "股东", own_pct)]
            rest = 100.0 - own_pct
            executives = [Person(founder, "执行董事")]

            # Some companies have a visible heir: a younger person with
            # the same surname holding shares or a post.
            if rest > 0 and rng.random() < 0.35:
                heir = surname + rng.choice(YOUNG_GIVEN)
                shareholders.append(Person(heir, "股东", rest))
                if rng.random() < 0.5:
                    executives.append(Person(heir, "监事"))
            elif rest > 0:
                partner = rng.choice(SURNAMES) + rng.choice(MID_GIVEN)
                shareholders.append(Person(partner, "股东", rest))

            revenue = round(rng.uniform(20, 800), 1)
            yield Company(
                name=cname,
                industry=industry,
                region=region,
                founded_year=founded,
                legal_rep=founder,
                legal_rep_since=founded if rng.random() < 0.85 else founded + rng.randint(1, 10),
                shareholders=shareholders,
                executives=executives,
                revenue_m=revenue,
                net_profit_m=round(revenue * rng.uniform(0.02, 0.15), 1),
                pledge_ratio=round(rng.random(), 2) if rng.random() < 0.15 else 0.0,
                litigation_count=rng.randint(1, 8) if rng.random() < 0.2 else 0,
                source="dummy",
            )
