#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
21_theme_eligibility.py  (최종 선정: 테마 적격성 심사 게이트)

각 리밸런싱 시점(theme4ir_pit 스냅숏)별로 종목의 테마 적격성을 판정한다.

필드: ticker, rebalance_date, business_status, theme_directness, theme_eligible,
      theme_exclusion_reason, evidence_date, evidence_source, evidence_level

판정 규칙:
  - DISCONTINUED -> theme_eligible=False (BUSINESS_DISCONTINUED)
  - 직접성 LOW & 공식 근거 확인 -> theme_eligible=False (THEME_DIRECTNESS_LOW)
  - REVIEW/불확실/NOT_REVIEWED -> 자동 제외 금지, 기존 자격 유지(True)
  - AI 키워드 감소만으로 False 금지
  - PIT: evidence_date(직접성 근거 공개일) > rebalance_date 이면 그 시점엔 미적용(기존 자격 유지)

두 모드 산출:
  - theme_eligibility_pit.csv  : evidence_date 이후 리밸런싱부터만 False (최종)
  - theme_eligibility_retro.csv: 전 분기 소급 False (참고용)

현재 검토상 SNOW/DDOG/CDW 만 직접성 LOW(공식 확인) -> 제외 후보.
directness_evidence_date = 이번에 검토한 FY2025 10-K 접수일(가장 보수적 근거일).
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "data" / "integrity"
THEME4IR = ROOT / "data" / "pit" / "theme4ir_pit.csv"
TRACKER = INTEG / "business_continuity_tracker.csv"

# 직접성 LOW & 공식확인 종목 + 근거 공개일(검토한 FY2025 10-K 접수일)
DIRECTNESS_LOW = {
    "SNOW": dict(edate="2026-03-20", src="SEC 10-K FY2025(snow-20250131)", level="OFFICIAL_FILING_VERIFIED"),
    "DDOG": dict(edate="2026-02-18", src="SEC 10-K FY2025(ddog-20251231)", level="OFFICIAL_FILING_VERIFIED"),
    "CDW":  dict(edate="2026-02-20", src="회사 사업모델/제3자 개요(공식 10-K 미대조)", level="KEYWORD_ONLY"),
}


def build(mode: str) -> pd.DataFrame:
    th = pd.read_csv(THEME4IR)
    tr = pd.read_csv(TRACKER, encoding="utf-8-sig")
    biz = dict(zip(tr.ticker, tr.business_status))
    directness = dict(zip(tr.ticker, tr.ai_infra_directness))
    rows = []
    for _, r in th[["snapshot_date", "ticker"]].drop_duplicates().iterrows():
        tkr = str(r["ticker"]).upper(); rb = str(r["snapshot_date"])
        bs = biz.get(tkr, "NOT_REVIEWED")
        elig, reason, edate, src, lvl = True, "", "", "", "EXISTING_CLASSIFICATION_ONLY"
        dn = directness.get(tkr, "NOT_ASSESSED")
        if bs == "DISCONTINUED":
            elig, reason = False, "BUSINESS_DISCONTINUED"
        elif tkr in DIRECTNESS_LOW:
            d = DIRECTNESS_LOW[tkr]; edate, src, lvl = d["edate"], d["src"], d["level"]
            dn = "LOW"
            apply = (mode == "retro") or (rb >= d["edate"])  # PIT: 근거 공개일 이후만
            if apply:
                elig, reason = False, "THEME_DIRECTNESS_LOW"
            else:
                elig, reason = True, "PIT_EVIDENCE_NOT_YET_AVAILABLE(기존 자격 유지)"
        rows.append(dict(ticker=tkr, rebalance_date=rb, business_status=bs,
                         theme_directness=dn, theme_eligible=elig,
                         theme_exclusion_reason=reason, evidence_date=edate,
                         evidence_source=src, evidence_level=lvl))
    return pd.DataFrame(rows)


def main():
    for mode in ("pit", "retro"):
        df = build(mode)
        df.to_csv(INTEG / f"theme_eligibility_{mode}.csv", index=False, encoding="utf-8-sig")
        n_excl = int((~df.theme_eligible).sum())
        by = df[~df.theme_eligible].groupby("ticker")["rebalance_date"].agg(["count", "min", "max"])
        print(f"[{mode}] theme_eligible=False 행: {n_excl}")
        if len(by):
            print(by.to_string())
        print()
    print("출력: theme_eligibility_pit.csv / theme_eligibility_retro.csv")


if __name__ == "__main__":
    main()
