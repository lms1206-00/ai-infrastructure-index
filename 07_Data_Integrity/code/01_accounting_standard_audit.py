#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
01_accounting_standard_audit.py  (Item 1: IFRS / US-GAAP 혼재 점검)

목적
----
final_universe_100.csv 의 100개 기업에 대해, SEC Fact Store(data/facts/{CIK}.parquet)의
원본 taxonomy(us-gaap / ifrs-full / dei / srt ...)를 근거로

  * 기업별 적용 회계기준(accounting_standard)        : US-GAAP / IFRS / MIXED_FILER / UNKNOWN
  * 표준 재무항목 5종(Revenue, Operating Income, Net Income, Assets, Liabilities)의
    원본 taxonomy(source_taxonomy) 및 tag(source_tag) 기록
  * 동일 기업·동일 기준일·동일 표준항목 계산에 서로 다른 회계기준 값이 섞였는지
    (mixed_standard_warning) 판정
  * standardized_metric 매핑

을 산출한다.  값을 임의로 만들지 않는다 — 오직 실제 fact 의 taxonomy/tag 만 기록한다.
선택 로직은 기존 `02_Data_Preprocessing/code/01_factor_engine.py` 를 그대로 import 하여
재현하므로, 실제 팩터가 어느 fact 에서 나왔는지와 100% 일치한다.

입력 : data/classification/final_universe_100.csv , data/facts/{CIK}.parquet
출력 : data/integrity/accounting_standard_company.csv        (기업 1행)
       data/integrity/accounting_standard_metric_detail.csv  (기업×기준일×항목 1행)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

THIS = Path(__file__).resolve()
ROOT = THIS.parents[2]
FACTS_DIR = ROOT / "data" / "facts"
UNIVERSE = ROOT / "data" / "classification" / "final_universe_100.csv"
OUT_DIR = ROOT / "data" / "integrity"
ENGINE_PATH = ROOT / "02_Data_Preprocessing" / "code" / "01_factor_engine.py"

# 표준 재무항목 <- 팩터엔진 metric key 매핑 (Item 1 이 요구하는 5종)
STANDARD_METRICS = {
    "revenue": "Revenue",
    "operating_income": "OperatingIncome",
    "net_income": "NetIncome",
    "assets": "Assets",
    "liabilities": "Liabilities",
}
FINANCIAL_TAX = {"us-gaap", "ifrs-full"}


def load_engine():
    spec = importlib.util.spec_from_file_location("factor_engine", ENGINE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["factor_engine"] = mod  # dataclass 데코레이터가 sys.modules 조회 필요
    spec.loader.exec_module(mod)
    return mod


def classify_standard(fin_tax_counts: dict) -> str:
    present = {k for k in fin_tax_counts if k in FINANCIAL_TAX and fin_tax_counts[k] > 0}
    if present == {"us-gaap"}:
        return "US-GAAP"
    if present == {"ifrs-full"}:
        return "IFRS"
    if present == {"us-gaap", "ifrs-full"}:
        return "MIXED_FILER"
    return "UNKNOWN"


def audit_one(eng, cik: str, ticker: str):
    """returns (company_row_dict, list_of_metric_detail_rows)"""
    f = FACTS_DIR / f"{cik}.parquet"
    if not f.exists():
        return {"cik": cik, "ticker": ticker, "accounting_standard": "NO_FACTS",
                "n_financial_facts": 0}, []

    raw = pd.read_parquet(f)
    facts = eng.standardize_fact_store(raw, cik)
    # 전체 회계기준 분포(원본 taxonomy 기준)
    tax_counts = raw["taxonomy"].astype("string").str.lower().str.strip().value_counts().to_dict()
    std = classify_standard(tax_counts)
    entity_name = facts["entity_name"].dropna().iloc[0] if facts["entity_name"].notna().any() else ""

    if facts.empty:
        return {"cik": cik, "ticker": ticker, "entity_name": entity_name,
                "accounting_standard": std, "n_financial_facts": 0}, []

    anchors = eng.build_anchors(facts).sort_values(["end", "filed", "accession_key"])
    detail_rows = []
    # 각 anchor(기준일=기간말) 별로 표준항목 5종의 source taxonomy/tag 를 기록
    for _, a in anchors.iterrows():
        per_metric_tax = {}
        for m, std_name in STANDARD_METRICS.items():
            chosen = eng.choose_metric_fact(
                facts=facts, metric=m,
                anchor_end=a["end"], anchor_filed=a["filed"], anchor_form=a["form"],
                anchor_fy=a["fy"], anchor_fp=a["fp"],
            )
            if chosen is None:
                src_tax, src_tag, val = pd.NA, pd.NA, np.nan
            else:
                src_tax = chosen.get("taxonomy", pd.NA)
                src_tag = chosen.get("tag", pd.NA)
                val = chosen.get("value", np.nan)
            per_metric_tax[m] = src_tax
            detail_rows.append({
                "cik": cik, "ticker": ticker, "entity_name": entity_name,
                "period_end": a["end"], "period_type": a["period_type"],
                "form": a["form"], "fiscal_year": a["fy"], "fiscal_period": a["fp"],
                "standardized_metric": std_name, "factor_metric": m,
                "source_taxonomy": src_tax, "source_tag": src_tag, "value": val,
            })
        # 행(기준일) 단위 혼재 경고: 서로 다른 재무 taxonomy 가 5종 중에 섞였는가
        fin_used = {str(t).lower() for t in per_metric_tax.values()
                    if pd.notna(t) and str(t).lower() in FINANCIAL_TAX}
        mixed = len(fin_used) > 1
        for r in detail_rows[-len(STANDARD_METRICS):]:
            r["row_financial_taxonomies"] = "|".join(sorted(fin_used))
            r["mixed_standard_warning"] = mixed

    detail_df = pd.DataFrame(detail_rows)
    # 최신 기준일 요약
    latest_end = anchors["end"].max()
    latest = detail_df[detail_df["period_end"] == latest_end]
    latest_map = {row["factor_metric"]: (row["source_taxonomy"], row["source_tag"])
                  for _, row in latest.iterrows()}
    company = {
        "cik": cik, "ticker": ticker, "entity_name": entity_name,
        "accounting_standard": std,
        "financial_taxonomies_present": "|".join(
            sorted(k for k in tax_counts if k in FINANCIAL_TAX)),
        "n_us_gaap_facts": int(tax_counts.get("us-gaap", 0)),
        "n_ifrs_facts": int(tax_counts.get("ifrs-full", 0)),
        "n_financial_facts": int(sum(v for k, v in tax_counts.items() if k in FINANCIAL_TAX)),
        "latest_period_end": latest_end,
        "any_mixed_row": bool(detail_df["mixed_standard_warning"].any()) if len(detail_df) else False,
        "n_mixed_rows": int(detail_df.groupby("period_end")["mixed_standard_warning"].first().sum())
                        if len(detail_df) else 0,
        "latest_mixed_warning": bool(latest["mixed_standard_warning"].any()) if len(latest) else False,
    }
    for m in STANDARD_METRICS:
        tax, tag = latest_map.get(m, (pd.NA, pd.NA))
        company[f"latest_{m}_taxonomy"] = tax
        company[f"latest_{m}_tag"] = tag
    return company, detail_rows


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    eng = load_engine()
    uni = pd.read_csv(UNIVERSE, encoding="utf-8-sig")
    uni["cik"] = uni["cik"].astype(str).str.replace(".0", "", regex=False).str.zfill(10)

    company_rows, detail_all = [], []
    for _, r in uni.iterrows():
        comp, det = audit_one(eng, r["cik"], r["ticker"])
        company_rows.append(comp)
        detail_all.extend(det)
        flag = "  <-- MIXED" if comp.get("any_mixed_row") else ""
        print(f"{r['ticker']:6s} {r['cik']} {comp.get('accounting_standard',''):12s} "
              f"us-gaap={comp.get('n_us_gaap_facts',0):>6} ifrs={comp.get('n_ifrs_facts',0):>6}{flag}")

    comp_df = pd.DataFrame(company_rows)
    det_df = pd.DataFrame(detail_all)
    comp_df.to_csv(OUT_DIR / "accounting_standard_company.csv", index=False, encoding="utf-8-sig")
    det_df.to_csv(OUT_DIR / "accounting_standard_metric_detail.csv", index=False, encoding="utf-8-sig")

    print("\n" + "=" * 60)
    print("회계기준 분포(기업 수):")
    print(comp_df["accounting_standard"].value_counts().to_string())
    print(f"\n혼재행(mixed_standard_warning=True) 보유 기업: "
          f"{int(comp_df['any_mixed_row'].sum())}개")
    mixed_co = comp_df[comp_df["any_mixed_row"]][
        ["ticker", "cik", "accounting_standard", "n_us_gaap_facts", "n_ifrs_facts", "n_mixed_rows"]]
    if len(mixed_co):
        print(mixed_co.to_string(index=False))
    print(f"\n최신 기준일 혼재행 보유 기업: {int(comp_df['latest_mixed_warning'].sum())}개")
    print(f"\n출력: {OUT_DIR/'accounting_standard_company.csv'}")
    print(f"출력: {OUT_DIR/'accounting_standard_metric_detail.csv'}")


if __name__ == "__main__":
    sys.exit(main())
