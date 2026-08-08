#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
14_factor_engine_blocked_v2.py  (최종 원칙: 회계기준 전환시 혼합 금지, 전 팩터)

원칙(사용자 확정)
-----------------
1) 전기·당기 accounting_standard 가 다르면 성장률(revenue_growth 등)은 NaN.
2) 단, 공식 공시에서 전기를 당기와 '동일 회계기준으로 재작성'한 경우에만, 그 재작성된
   동일기준 값끼리 재계산.
3) **숫자가 같다는 이유로 비교가능으로 판단하지 않는다** — 비교가능 판정은 오직 fact 의
   원본 taxonomy 일치(공식 재작성 fact 존재)로만 한다. (본 코드는 항상 taxonomy==현재기준
   인 fact 만 재작성치로 채택하며, 값 일치 여부는 판정에 쓰지 않는다.)
4) 공식 재작성 근거가 없거나 불확실하면 무조건 NaN.
5) 동일 연도/동일 기준일의 비율형 팩터(operating_margin, roa, debt_ratio)도 분자와 분모의
   taxonomy 가 다르면 NaN. (ROA 의 평균자산은 전기 자산을 포함하므로, 전기 자산의 기준이
   당기와 다르면 재작성 자산으로만 평균, 없으면 NaN.)
6) 결측 처리 후 기존 최소 3/4 팩터 조건(theme4ir --min-required-factors 3)을 적용한다.
7) 기업을 100 후보 유니버스에서 삭제하지 않는다 — 해당 분기의 '평가 가능 여부'만 바뀐다
   (팩터 NaN → 그 분기 required_factor_count 감소 → 3/4 미달시 그 분기만 제외).

원본 data/factors 불변. 출력: data/integrity/factors_blocked_v2/{cik}.parquet,
결정로그 growth_blocking_decisions_v2.csv.
"""
from __future__ import annotations
import importlib.util
import shutil
import sys
from pathlib import Path
import numpy as np
import pandas as pd

THIS = Path(__file__).resolve(); ROOT = THIS.parents[2]
FACTS = ROOT / "data" / "facts"; FACTORS = ROOT / "data" / "factors"
INTEG = ROOT / "data" / "integrity"; OUT = INTEG / "factors_blocked_v2"
UNI = ROOT / "data" / "classification" / "final_universe_100.csv"
ENGINE = ROOT / "02_Data_Preprocessing" / "code" / "01_factor_engine.py"
FIN = {"us-gaap", "ifrs-full"}
GROWTH = {"revenue_growth": "revenue", "operating_income_growth": "operating_income",
          "net_income_growth": "net_income", "asset_growth": "assets"}


def load_engine():
    spec = importlib.util.spec_from_file_location("factor_engine", ENGINE)
    m = importlib.util.module_from_spec(spec); sys.modules["factor_engine"] = m
    spec.loader.exec_module(m); return m


def restated_prev(eng, facts, metric, cur_std, prev_end, prev_form, prev_fy, prev_fp, as_of):
    """전기 metric 값을 '당기 taxonomy(cur_std)' 로만 탐색 = 공식 재작성치.
    값 일치가 아니라 taxonomy 일치로 판정. 없으면 None."""
    sub = facts[facts["taxonomy"] == cur_std]
    if sub.empty:
        return None
    ch = eng.choose_metric_fact(facts=sub, metric=metric, anchor_end=prev_end,
                                anchor_filed=pd.Timestamp(as_of), anchor_form=prev_form,
                                anchor_fy=prev_fy, anchor_fp=prev_fp)
    return None if ch is None else (float(ch["value"]), str(ch["taxonomy"]))


def process(eng, cik, tkr, detail_c):
    orig = pd.read_parquet(FACTORS / f"{cik}.parquet")
    if orig.empty:
        return orig, []
    blocked = orig.copy()
    blocked["period_end"] = pd.to_datetime(blocked["period_end"])
    # 행별 per-metric taxonomy (metric_detail)
    dd = detail_c.copy(); dd["period_end"] = pd.to_datetime(dd["period_end"])
    tax = dd.pivot_table(index="period_end", columns="factor_metric",
                         values="source_taxonomy", aggfunc="first")

    def rowtax(pe, m):
        try:
            v = tax.at[pe, m]
            return v if v in FIN else None
        except Exception:
            return None

    decisions = []
    has_transition = False
    facts = None
    for ptype, grp in blocked.groupby("period_type"):
        g = grp.sort_values("period_end")
        prev = None
        for idx in g.index:
            pe = blocked.at[idx, "period_end"]
            s = {m: rowtax(pe, m) for m in ["revenue", "operating_income",
                                            "net_income", "assets", "liabilities"]}
            # (5) 비율형 행내 분자/분모 taxonomy 불일치 -> NaN
            if s["operating_income"] and s["revenue"] and s["operating_income"] != s["revenue"]:
                blocked.at[idx, "operating_margin"] = np.nan
                decisions.append(dict(ticker=tkr, cik=cik, period_end=str(pe.date()),
                                      factor="operating_margin", decision="BLOCKED_NULLED",
                                      reason="within-row op_income/revenue taxonomy 상이"))
            if s["liabilities"] and s["assets"] and s["liabilities"] != s["assets"]:
                blocked.at[idx, "debt_ratio"] = np.nan
                decisions.append(dict(ticker=tkr, cik=cik, period_end=str(pe.date()),
                                      factor="debt_ratio", decision="BLOCKED_NULLED",
                                      reason="within-row liabilities/assets taxonomy 상이"))
            if s["net_income"] and s["assets"] and s["net_income"] != s["assets"]:
                blocked.at[idx, "roa"] = np.nan
                decisions.append(dict(ticker=tkr, cik=cik, period_end=str(pe.date()),
                                      factor="roa", decision="BLOCKED_NULLED",
                                      reason="within-row net_income/assets taxonomy 상이"))
            # 전환 경계 처리 (성장률 + ROA 평균자산)
            if prev is not None:
                cur_std = s["assets"] or s["revenue"] or s["net_income"]
                prev_pe = blocked.at[prev, "period_end"]
                prev_std = rowtax(prev_pe, "assets") or rowtax(prev_pe, "revenue")
                if cur_std and prev_std and cur_std != prev_std:
                    has_transition = True
                    if facts is None:
                        facts = eng.standardize_fact_store(pd.read_parquet(FACTS / f"{cik}.parquet"), cik)
                    prev_form = blocked.at[prev, "form"]; prev_fy = blocked.at[prev, "fiscal_year"]
                    prev_fp = blocked.at[prev, "fiscal_period"]; as_of = blocked.at[idx, "filed"]
                    # (1)(2)(4) 성장률
                    for gcol, metric in GROWTH.items():
                        cur_val = orig.at[idx, metric]
                        rp = restated_prev(eng, facts, metric, cur_std, prev_pe,
                                           prev_form, prev_fy, prev_fp, as_of)
                        if rp is not None and pd.notna(cur_val) and rp[0] != 0:
                            blocked.at[idx, gcol] = float(cur_val) / rp[0] - 1.0
                            dec, note = "RECOMPUTED_RESTATED", f"restated prev={rp[0]:.0f}(tax={rp[1]})"
                        else:
                            blocked.at[idx, gcol] = np.nan
                            dec, note = "BLOCKED_NULLED", "공식 재작성 전기치 없음 -> NaN"
                        decisions.append(dict(ticker=tkr, cik=cik, period_end=str(pe.date()),
                                              factor=gcol, decision=dec, reason=note))
                    # (5-ROA) 평균자산: 전기 자산 기준이 다르면 재작성 자산으로만 평균, 없으면 NaN
                    ni = orig.at[idx, "net_income"]; a_cur = orig.at[idx, "assets"]
                    rp_a = restated_prev(eng, facts, "assets", cur_std, prev_pe,
                                         prev_form, prev_fy, prev_fp, as_of)
                    if pd.notna(blocked.at[idx, "roa"]):  # within-row 통과한 경우만
                        if rp_a is not None and pd.notna(ni) and pd.notna(a_cur):
                            avg = (float(a_cur) + rp_a[0]) / 2.0
                            blocked.at[idx, "roa"] = float(ni) / avg if avg else np.nan
                            decisions.append(dict(ticker=tkr, cik=cik, period_end=str(pe.date()),
                                                  factor="roa", decision="RECOMPUTED_RESTATED",
                                                  reason=f"avg_assets 재작성 전기자산={rp_a[0]:.0f}(tax={rp_a[1]})"))
                        else:
                            blocked.at[idx, "roa"] = np.nan
                            decisions.append(dict(ticker=tkr, cik=cik, period_end=str(pe.date()),
                                                  factor="roa", decision="BLOCKED_NULLED",
                                                  reason="전기 자산 재작성치 없음(평균 혼합) -> NaN"))
            prev = idx
    return blocked, decisions


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    eng = load_engine()
    uni = pd.read_csv(UNI, encoding="utf-8-sig")
    uni["cik"] = uni["cik"].astype(str).str.replace(".0", "", regex=False).str.zfill(10)
    detail = pd.read_csv(INTEG / "accounting_standard_metric_detail.csv", encoding="utf-8-sig")
    detail["cik"] = detail["cik"].astype(str).str.zfill(10)

    all_dec = []
    for _, r in uni.iterrows():
        cik, tkr = r["cik"], r["ticker"]
        dc = detail[detail.cik == cik]
        blocked, dec = process(eng, cik, tkr, dc)
        blocked.to_parquet(OUT / f"{cik}.parquet", index=False)
        all_dec.extend(dec)

    dd = pd.DataFrame(all_dec)
    dd.to_csv(INTEG / "growth_blocking_decisions_v2.csv", index=False, encoding="utf-8-sig")
    print("=" * 64)
    print("v2 최종 원칙 차단 실행 (성장률 + 비율형 전 팩터)")
    print("=" * 64)
    print(f"블록 v2 파일: {OUT} (100개)")
    print(f"결정 로그 행수: {len(dd)}")
    if len(dd):
        print("\n결정 분포:", dd["decision"].value_counts().to_dict())
        print("\n[결정 로그]")
        print(dd.to_string(index=False))
    print(f"\n출력: {INTEG/'growth_blocking_decisions_v2.csv'}")


if __name__ == "__main__":
    main()
