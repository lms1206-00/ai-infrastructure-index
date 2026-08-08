#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
16_strict_scenario.py  (worst-case 한정: 재작성 무시하고 전환 성장/ROA 순수 NaN)

최종 원칙은 '재작성치 있으면 재계산'이나, 만약 재작성 근거를 아예 인정하지 않는
가장 보수적 해석(무조건 NaN)을 택하면 지수가 얼마나 바뀌는지 상한을 실측한다.
-> factors_blocked_v2 를 복제하되 CLS FY2024 의 지수팩터(revenue_growth, roa) 및
   나머지 성장률을 강제로 NaN 처리한 factors_strict 생성. (op_margin/debt_ratio 는
   행내 동일기준이라 유지.)

이는 '재작성치가 없었다면'을 가정한 상한 시나리오이며, 실제로는 CLS가 공식 재작성을
했으므로 채택 시나리오가 아님을 명시한다.
출력: data/integrity/factors_strict/{cik}.parquet
"""
from __future__ import annotations
import shutil
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "data" / "integrity"
SRC = INTEG / "factors_blocked_v2"
OUT = INTEG / "factors_strict"
NULL_COLS = ["revenue_growth", "operating_income_growth", "net_income_growth",
             "asset_growth", "roa"]


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    cls_cik = "0001030894"
    for f in SRC.glob("*.parquet"):
        df = pd.read_parquet(f)
        if f.stem == cls_cik:
            m = (pd.to_datetime(df["period_end"]).dt.strftime("%Y-%m-%d") == "2024-12-31") \
                & (df["period_type"] == "annual")
            for c in NULL_COLS:
                if c in df.columns:
                    df.loc[m, c] = np.nan
        df.to_parquet(OUT / f.name, index=False)
    print(f"strict 시나리오 factors 생성: {OUT} (CLS FY2024 revenue_growth/roa/성장률 강제 NaN)")


if __name__ == "__main__":
    main()
