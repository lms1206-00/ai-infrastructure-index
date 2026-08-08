#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
10_evidence_level.py  (후속검증 항목2: evidence_level 정직 구분)

기존 ai_infra_continuity_review.csv 는 92개 CORE를 사실상 기존 분류만으로 True 처리하고
business_status 를 일괄 ACTIVE 로 적어 "공식 공시 검증"으로 오인될 수 있었다.
이를 정정해 기업별 evidence_level 을 실제 확인 수준으로 구분한다.

evidence_level 정의
-------------------
  OFFICIAL_FILING_VERIFIED     : 이번 점검에서 SEC 공식 공시(10-K/20-F 등) 사업개요를 직접 확인
  OFFICIAL_WEBSITE_VERIFIED    : 회사 공식 IR/실적발표(세그먼트 매출 등)를 확인
  EXISTING_CLASSIFICATION_ONLY : 프로젝트 기존 분류(candidate_csv)+테마 taxonomy 만 근거
  KEYWORD_ONLY                 : 제3자 개요/키워드 수준만 확인(공식 아님)
  NOT_VERIFIED                 : 사업 실체를 이번 점검에서 확인하지 못함

business_status 도 '검증된 사실'이 아니라 '관측된 신호'로 정정한다:
  - LISTED_TRADING(가격패널 마지막 거래일까지 거래) : suspension_audit_100 근거
  - ACTIVE_FILER(최근 공시일)                        : entity 재무 최신 filing 근거
매각/철수/중단은 이번 점검에서 개별 확인하지 않았으므로 단정하지 않는다.

기존 파일 미변경. 출력: data/integrity/ai_infra_continuity_review_v2.csv
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "data" / "integrity"
UNIVERSE = ROOT / "data" / "classification" / "final_universe_100.csv"

# 이번 점검에서 실제 확인한 근거 수준(REVIEW 8종 + 근거 있는 기타)
EVIDENCE = {
    "SNOW": ("OFFICIAL_FILING_VERIFIED", "SEC 10-K FY2025(snow-20250131) 사업개요 직접 확인"),
    "DDOG": ("OFFICIAL_FILING_VERIFIED", "SEC 10-K FY2025(ddog-20251231) 사업개요 직접 확인"),
    "NTNX": ("OFFICIAL_WEBSITE_VERIFIED", "회사 IR/FY2025 실적(구독전환) 확인"),
    "AMT":  ("OFFICIAL_WEBSITE_VERIFIED", "회사 2025 실적: DC 세그먼트 매출 $1.053B(~10%) 확인"),
    "IRM":  ("OFFICIAL_WEBSITE_VERIFIED", "회사 2025 실적: DC 매출 비중 ~13% 확인"),
    "CDW":  ("KEYWORD_ONLY", "제3자 개요(리셀러/유통) 확인, 공식 공시 미대조"),
    "LII":  ("EXISTING_CLASSIFICATION_ONLY", "테마 taxonomy(HVAC)만 근거, 개별 공시 미대조"),
    "WTS":  ("EXISTING_CLASSIFICATION_ONLY", "테마 taxonomy(Water/Thermal)만 근거, 개별 공시 미대조"),
}


def main():
    uni = pd.read_csv(UNIVERSE, encoding="utf-8-sig")
    cont = pd.read_csv(INTEG / "ai_infra_continuity_review.csv", encoding="utf-8-sig")
    susp = pd.read_csv(INTEG / "suspension_audit_100.csv", encoding="utf-8-sig")
    filed = dict(zip(uni["ticker"], uni.get("latest_filed", pd.Series())))
    pend = dict(zip(uni["ticker"], uni.get("latest_period_end", pd.Series())))
    susp_last = dict(zip(susp["ticker"], susp["last_valid"]))
    susp_stat = dict(zip(susp["ticker"], susp["status"]))

    rows = []
    for _, r in cont.iterrows():
        tkr = r["ticker"]
        if tkr in EVIDENCE:
            lvl, note = EVIDENCE[tkr]
        else:
            # 92 CORE(및 근거 없는 나머지): 기존 분류만
            lvl, note = ("EXISTING_CLASSIFICATION_ONLY",
                         "candidate_csv+테마 taxonomy만 근거(개별 공식 공시 미대조)")
        last = susp_last.get(tkr, "")
        stat = susp_stat.get(tkr, "NO_PRICE")
        biz = []
        if stat == "OK" and str(last):
            biz.append(f"LISTED_TRADING(~{last})")
        elif stat in ("SUSPECTED_SUSPENSION", "DELISTED_OR_DATA_END"):
            biz.append(f"CHECK({stat})")
        if pd.notna(filed.get(tkr)) and str(filed.get(tkr)):
            biz.append(f"ACTIVE_FILER({filed.get(tkr)})")
        rows.append({
            "ticker": tkr, "company_name": r["company_name"],
            "current_category": r["current_category"], "infra_layer": r["infra_layer"],
            "theme_eligible": r["theme_eligible"],
            "evidence_level": lvl,
            "evidence_note": note,
            "business_status_observed": "; ".join(biz) if biz else "UNVERIFIED",
            "latest_filed": filed.get(tkr, ""), "latest_period_end": pend.get(tkr, ""),
            "review_reason": r.get("review_reason", ""),
        })
    out = pd.DataFrame(rows)
    out.to_csv(INTEG / "ai_infra_continuity_review_v2.csv", index=False, encoding="utf-8-sig")

    print("=" * 64)
    print("항목2  evidence_level 정직 구분")
    print("=" * 64)
    print("evidence_level 분포:")
    print(out["evidence_level"].value_counts().to_string())
    print("\n[공식 확인(FILING/WEBSITE) 기업]")
    print(out[out.evidence_level.str.startswith("OFFICIAL")][
        ["ticker", "evidence_level", "evidence_note"]].to_string(index=False))
    print("\n주의: 92 CORE는 EXISTING_CLASSIFICATION_ONLY (개별 공식 공시 미대조).")
    print("business_status 는 '검증된 사실'이 아니라 가격패널·filing 관측 신호로 표기.")
    print(f"\n출력: {INTEG/'ai_infra_continuity_review_v2.csv'}")


if __name__ == "__main__":
    main()
