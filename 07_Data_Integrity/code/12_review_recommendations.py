#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
12_review_recommendations.py  (후속검증 항목4: REVIEW 8종목 개별 권고)

REVIEW 8종목 각각에 대해 KEEP_CORE / RECOMMEND_EXCLUDE / NEEDS_FURTHER_REVIEW 중
어떤 판단이 적절한지 근거와 함께 제안한다. **자동 편출은 하지 않는다**(권고만).
세 축으로 구분:
  - ai_infra_directness : AI 인프라 공급/운영의 직접성 (HIGH/MEDIUM/LOW)
  - business_continuity : 사업 지속성 (관측 신호)
  - related_revenue_disclosed : AI 인프라 관련 매출 비중 확인 가능 여부

출력: data/integrity/review_recommendations.csv
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "data" / "integrity"

REC = {
    "SNOW": dict(rec="RECOMMEND_EXCLUDE", directness="LOW", continuity="HIGH(매출 $3.6B, +29%)",
                 rev_disclosed="N/A(100% SaaS SW, 인프라 매출 없음)",
                 rationale="클라우드 데이터플랫폼 SaaS. 인프라 하드웨어 공급/DC 운영이 아닌 "
                           "애플리케이션 계층 SW → 정의상 직접성 없음.",
                 evidence="SEC 10-K FY2025"),
    "DDOG": dict(rec="RECOMMEND_EXCLUDE", directness="LOW", continuity="HIGH(매출 $3.4B, +28%)",
                 rev_disclosed="N/A(100% SaaS SW)",
                 rationale="Observability/보안 SaaS. 인프라 모니터링 도구이며 인프라 자체를 "
                           "공급/운영하지 않음.",
                 evidence="SEC 10-K FY2025"),
    "CDW":  dict(rec="RECOMMEND_EXCLUDE", directness="LOW", continuity="HIGH(대형 IT 유통)",
                 rev_disclosed="해당없음(재판매 마진, 자체 인프라 생산·운영 없음)",
                 rationale="IT 제품 리셀러/유통 채널. 인프라를 직접 제조·운영하지 않음 → "
                           "공급자(supplier)로 보기 어려움.",
                 evidence="회사 사업모델(제3자 개요, KEYWORD_ONLY)"),
    "NTNX": dict(rec="NEEDS_FURTHER_REVIEW", directness="MEDIUM", continuity="HIGH(매출 $2.5B, +18%)",
                 rev_disclosed="소프트웨어 구독 100%(HW 아님)",
                 rationale="HCI 소프트웨어 정의 인프라. AI 워크로드 구동 SW지만 HW/설비 "
                           "공급자는 아님 → SW-정의 인프라로 볼지 경계 판단 필요.",
                 evidence="회사 IR FY2025"),
    "AMT":  dict(rec="NEEDS_FURTHER_REVIEW", directness="MEDIUM", continuity="HIGH(매출 ~$10B)",
                 rev_disclosed="가능: DC(CoreSite) 세그먼트 매출 $1.053B ≈ 전체 ~10%",
                 rationale="주력은 통신 타워 REIT. DC 운영(CoreSite)은 AI 수요로 성장 중이나 "
                           "매출 소수(~10%) → DC 세그먼트만 부분 적격, 재분류/부분편입 검토.",
                 evidence="회사 2025 실적"),
    "IRM":  dict(rec="NEEDS_FURTHER_REVIEW", directness="MEDIUM", continuity="HIGH(매출 $10.6B, +5%)",
                 rev_disclosed="가능: DC 매출 비중 ~13%",
                 rationale="주력은 문서·기록 보관. DC는 매출 ~13% 소수 → 부분 적격, 재분류 검토.",
                 evidence="회사 2025 실적"),
    "LII":  dict(rec="NEEDS_FURTHER_REVIEW", directness="LOW", continuity="HIGH(HVAC 대형)",
                 rev_disclosed="불가: DC 전용 냉각 매출 별도 미공개(대부분 주거·상업 HVAC)",
                 rationale="일반/주거 HVAC 중심. DC 냉각 관련성 간접·매출 비중 확인 불가 → "
                           "관련 매출 확인 전까지 판단 보류.",
                 evidence="테마 taxonomy"),
    "WTS":  dict(rec="NEEDS_FURTHER_REVIEW", directness="LOW", continuity="HIGH(수처리·열 시스템)",
                 rev_disclosed="불가: DC 관련 매출 별도 미공개",
                 rationale="물/열 시스템(수처리·배관 중심). DC 냉각 관련성 간접·매출 비중 "
                           "확인 불가 → 판단 보류.",
                 evidence="테마 taxonomy"),
}


def main():
    cont = pd.read_csv(INTEG / "ai_infra_continuity_review.csv", encoding="utf-8-sig")
    review = cont[cont.theme_eligible == "REVIEW"]
    rows = []
    for _, r in review.iterrows():
        t = r["ticker"]; d = REC.get(t, {})
        rows.append({
            "ticker": t, "company_name": r["company_name"],
            "current_category": r["current_category"], "infra_layer": r["infra_layer"],
            "recommendation": d.get("rec", "NEEDS_FURTHER_REVIEW"),
            "ai_infra_directness": d.get("directness", ""),
            "business_continuity": d.get("continuity", ""),
            "related_revenue_disclosed": d.get("rev_disclosed", ""),
            "rationale": d.get("rationale", ""),
            "evidence": d.get("evidence", ""),
            "note": "자동 편출 아님 — 권고만. 현재 지수 불변.",
        })
    out = pd.DataFrame(rows)
    out.to_csv(INTEG / "review_recommendations.csv", index=False, encoding="utf-8-sig")
    print("=" * 64)
    print("항목4  REVIEW 8종목 권고 (자동 편출 없음)")
    print("=" * 64)
    print(out["recommendation"].value_counts().to_string())
    print()
    print(out[["ticker", "recommendation", "ai_infra_directness",
               "related_revenue_disclosed"]].to_string(index=False))
    print(f"\n출력: {INTEG/'review_recommendations.csv'}")


if __name__ == "__main__":
    main()
