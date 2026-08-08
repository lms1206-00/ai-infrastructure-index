#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
03_factors_enriched.py  (Item 1: 팩터 데이터에 5개 필드 실제 부착)

기존 팩터 값(data/factors/{cik}.parquet)은 바꾸지 않는다(행 단위 혼재 0건 -> 값 불변).
대신 감사 결과를 조인해 유니버스 100개 기업의 팩터 패널에

  accounting_standard, <metric>_source_taxonomy, <metric>_source_tag,
  standardized_metric_map, mixed_standard_warning, growth_cross_standard_warning

를 부착한 보강 패널을 만든다. 값 재계산 없음, 순수 provenance 부착.

출력: data/integrity/factors_enriched_universe.csv
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "data" / "integrity"
FACTORS = ROOT / "data" / "factors"
UNIVERSE = ROOT / "data" / "classification" / "final_universe_100.csv"
METRICS = ["revenue", "operating_income", "net_income", "assets", "liabilities"]
STD_MAP = "revenue->Revenue; operating_income->OperatingIncome; net_income->NetIncome; assets->Assets; liabilities->Liabilities"
FACTOR_COLS = ["period_end", "period_type", "fiscal_year", "revenue", "operating_income",
               "net_income", "assets", "liabilities", "revenue_growth",
               "operating_margin", "roa", "debt_ratio"]


def main():
    comp = pd.read_csv(INTEG / "accounting_standard_company.csv", encoding="utf-8-sig")
    detail = pd.read_csv(INTEG / "accounting_standard_metric_detail.csv", encoding="utf-8-sig")
    trans = pd.read_csv(INTEG / "accounting_standard_transitions.csv", encoding="utf-8-sig")
    comp["cik"] = comp["cik"].astype(str).str.zfill(10)
    detail["cik"] = detail["cik"].astype(str).str.zfill(10)
    trans["cik"] = trans["cik"].astype(str).str.zfill(10)
    detail["period_end"] = detail["period_end"].astype(str)
    trans["period_end"] = trans["period_end"].astype(str)

    std_map = comp.set_index("cik")["accounting_standard"].to_dict()

    # metric_detail(long) -> wide: cik,period_end 별 metric별 taxonomy/tag + row mixed
    wide = detail.pivot_table(index=["cik", "ticker", "period_end"],
                              columns="factor_metric",
                              values=["source_taxonomy", "source_tag"],
                              aggfunc="first")
    wide.columns = [f"{m}_{v.replace('source_','source_')}" for v, m in wide.columns]
    wide = wide.reset_index()
    mixed = (detail.groupby(["cik", "period_end"])["mixed_standard_warning"]
             .first().reset_index())
    growth = trans[["cik", "period_end", "growth_cross_standard_warning", "period_standard"]]

    uni = pd.read_csv(UNIVERSE, encoding="utf-8-sig")
    uni["cik"] = uni["cik"].astype(str).str.replace(".0", "", regex=False).str.zfill(10)

    out = []
    for cik in uni["cik"].unique():
        f = FACTORS / f"{cik}.parquet"
        if not f.exists():
            continue
        fac = pd.read_parquet(f)
        fac["cik"] = cik
        fac["period_end"] = fac["period_end"].astype(str).str[:10]
        keep = [c for c in FACTOR_COLS if c in fac.columns]
        fac = fac[["cik"] + keep].copy()
        fac["accounting_standard"] = std_map.get(cik, "UNKNOWN")
        fac["standardized_metric_map"] = STD_MAP
        fac = fac.merge(wide[wide.cik == cik].drop(columns=["ticker"]),
                        on=["cik", "period_end"], how="left")
        fac = fac.merge(mixed[mixed.cik == cik], on=["cik", "period_end"], how="left")
        fac = fac.merge(growth[growth.cik == cik], on=["cik", "period_end"], how="left")
        out.append(fac)

    res = pd.concat(out, ignore_index=True)
    res["mixed_standard_warning"] = res["mixed_standard_warning"].fillna(False)
    res["growth_cross_standard_warning"] = res["growth_cross_standard_warning"].fillna(False)
    # 티커 부착
    res = res.merge(uni[["cik", "ticker"]], on="cik", how="left")
    front = ["cik", "ticker", "period_end", "period_type", "accounting_standard"]
    res = res[front + [c for c in res.columns if c not in front]]
    res.to_csv(INTEG / "factors_enriched_universe.csv", index=False, encoding="utf-8-sig")

    print(f"보강 팩터 패널 행수: {len(res):,}  기업수: {res['cik'].nunique()}")
    print(f"mixed_standard_warning=True 행: {int(res['mixed_standard_warning'].sum())}")
    print(f"growth_cross_standard_warning=True 행: {int(res['growth_cross_standard_warning'].sum())}")
    gc = res[res["growth_cross_standard_warning"]]
    if len(gc):
        print("\n[교차기준 성장률 행]")
        print(gc[["ticker", "period_end", "period_type", "revenue", "revenue_growth"]].to_string(index=False))
    print(f"\n출력: {INTEG/'factors_enriched_universe.csv'}")


if __name__ == "__main__":
    main()
