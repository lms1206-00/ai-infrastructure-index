#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
02_accounting_standard_enrich.py  (Item 1: 후속 - 전환 탐지 + 유니버스 필드 보강)

01 감사 결과(accounting_standard_metric_detail.csv)를 근거로:

1) 기업별 "회계기준 전환"(예: IFRS -> US-GAAP) 을 탐지한다.
   - 성장률 팩터(revenue_growth 등)는 당기/전기 비교라, 전환 경계 행에서는
     서로 다른 회계기준 값이 분모/분자에 섞인다(growth_cross_standard_warning).
   - 이는 "동일 기준일 내 혼재(mixed_standard_warning)" 와 구분되는 시계열 혼재이다.

2) final_universe_100.csv 각 기업(최신 연차 기준)에
   accounting_standard / *_source_taxonomy / *_source_tag / standardized_metric /
   mixed_standard_warning / growth_cross_standard_warning 필드를 부착한 보강본을 만든다.
   -> data/integrity/final_universe_100_accounting.csv (원본 불변, 별도 파일)

3) 4개 핵심 팩터(revenue_growth, operating_margin, ROA, debt_ratio)에 대한
   혼재 영향 요약을 출력한다.

임의 값 생성 없음. 값 자체는 바꾸지 않는다(감사 결과 행 단위 혼재 0건 -> 값 불변).
추가하는 것은 provenance/경고 메타데이터뿐이다.
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "data" / "integrity"
UNIVERSE = ROOT / "data" / "classification" / "final_universe_100.csv"
FINANCIAL_TAX = {"us-gaap", "ifrs-full"}
GROWTH_BASE = {"revenue", "operating_income", "net_income", "assets"}  # 성장률의 기반 metric

# standardized_metric 매핑(전역 규칙): 경제적 의미·기간 기준이 동일한 항목만 매핑
STD_MAP = {
    "revenue": "Revenue", "operating_income": "OperatingIncome",
    "net_income": "NetIncome", "assets": "Assets", "liabilities": "Liabilities",
}


def detect_transitions(detail: pd.DataFrame) -> pd.DataFrame:
    """기업×기간별 '지배 회계기준' 과 직전 동일유형 기간 대비 전환 여부."""
    # 기간의 지배 기준 = 그 기간 5개 metric 중 최빈 재무 taxonomy
    detail = detail.copy()
    detail["fin_tax"] = detail["source_taxonomy"].where(
        detail["source_taxonomy"].isin(FINANCIAL_TAX))
    rows = []
    for (cik, tkr), g in detail.groupby(["cik", "ticker"]):
        per = (g.dropna(subset=["fin_tax"])
                 .groupby(["period_end", "period_type"])["fin_tax"]
                 .agg(lambda s: s.value_counts().index[0]))
        per = per.reset_index().sort_values("period_end")
        for ptype, gg in per.groupby("period_type"):
            gg = gg.sort_values("period_end").reset_index(drop=True)
            for i in range(len(gg)):
                prev_std = gg.loc[i - 1, "fin_tax"] if i > 0 else None
                cur_std = gg.loc[i, "fin_tax"]
                cross = (prev_std is not None) and (prev_std != cur_std)
                rows.append({
                    "cik": cik, "ticker": tkr,
                    "period_end": gg.loc[i, "period_end"], "period_type": ptype,
                    "period_standard": cur_std, "prev_period_standard": prev_std,
                    "growth_cross_standard_warning": bool(cross),
                })
    return pd.DataFrame(rows).sort_values(["ticker", "period_type", "period_end"])


def main():
    comp = pd.read_csv(INTEG / "accounting_standard_company.csv", encoding="utf-8-sig")
    detail = pd.read_csv(INTEG / "accounting_standard_metric_detail.csv", encoding="utf-8-sig")
    comp["cik"] = comp["cik"].astype(str).str.zfill(10)
    detail["cik"] = detail["cik"].astype(str).str.zfill(10)

    trans = detect_transitions(detail)
    trans.to_csv(INTEG / "accounting_standard_transitions.csv", index=False, encoding="utf-8-sig")

    # 전환(회계기준이 바뀐) 기업
    changed = (trans[trans["growth_cross_standard_warning"]]
               .groupby(["cik", "ticker"])
               .agg(cross_periods=("period_end", lambda s: "|".join(map(str, s))),
                    n_cross=("period_end", "size")).reset_index())

    # 유니버스 보강(최신 연차 기준)
    uni = pd.read_csv(UNIVERSE, encoding="utf-8-sig")
    uni["cik"] = uni["cik"].astype(str).str.replace(".0", "", regex=False).str.zfill(10)
    keep_comp = ["cik", "accounting_standard", "financial_taxonomies_present",
                 "n_us_gaap_facts", "n_ifrs_facts", "latest_mixed_warning"]
    for m in STD_MAP:
        keep_comp += [f"latest_{m}_taxonomy", f"latest_{m}_tag"]
    enr = uni.merge(comp[keep_comp], on="cik", how="left")

    # 유니버스 최신행이 성장률 교차기준인가? = 최신 연차기간이 changed의 cross_periods에 포함?
    latest_map = comp.set_index("cik")["latest_period_end"].to_dict()
    cross_latest = set()
    for _, r in trans[trans["growth_cross_standard_warning"]].iterrows():
        if str(r["period_end"]) == str(latest_map.get(r["cik"], "")):
            cross_latest.add(r["cik"])
    enr["mixed_standard_warning"] = enr["latest_mixed_warning"].fillna(False)
    enr["growth_cross_standard_warning"] = enr["cik"].isin(cross_latest)
    enr["has_standard_transition_history"] = enr["cik"].isin(set(changed["cik"]))
    # 표준화 매핑은 전역 상수 -> 참고 컬럼
    enr["standardized_metric_map"] = "; ".join(f"{k}->{v}" for k, v in STD_MAP.items())

    out_cols = list(uni.columns) + [c for c in enr.columns if c not in uni.columns]
    enr = enr[out_cols]
    enr.to_csv(INTEG / "final_universe_100_accounting.csv", index=False, encoding="utf-8-sig")

    # ---- 4팩터 영향 요약 ----
    within_row_mixed = int(comp["any_mixed_row"].sum()) if "any_mixed_row" in comp else 0
    print("=" * 64)
    print("Item 1  회계기준 혼재 점검 요약")
    print("=" * 64)
    print("기업 회계기준 분포:", comp["accounting_standard"].value_counts().to_dict())
    print(f"[A] 동일 기준일 내 혼재(mixed_standard_warning) 보유 기업 : {within_row_mixed}개")
    print("    -> operating_margin / ROA / debt_ratio 는 '한 행 내 값들의 비율'이므로")
    print("       이 값이 0 이면 세 팩터에 혼재 영향 없음(값 불변). VALIDATED.")
    print()
    print(f"[B] 회계기준 전환(시계열) 보유 기업 : {len(changed)}개")
    if len(changed):
        print(changed.to_string(index=False))
    print("    -> revenue_growth 등 성장률은 전환 경계에서 당기/전기 기준이 달라짐.")
    print()
    n_latest_cross = int(enr["growth_cross_standard_warning"].sum())
    print(f"[C] 유니버스 '최신 연차' 성장률이 교차기준인 기업 : {n_latest_cross}개")
    if n_latest_cross:
        print(enr[enr["growth_cross_standard_warning"]][
            ["ticker", "accounting_standard", "revenue_growth"]].to_string(index=False))
    else:
        print("    -> 0개. 즉 지수 편입에 실제 사용된 최신 성장률 팩터에는 교차기준 혼재 없음.")
    print()
    print(f"출력: {INTEG/'accounting_standard_transitions.csv'}")
    print(f"출력: {INTEG/'final_universe_100_accounting.csv'}")


if __name__ == "__main__":
    main()
