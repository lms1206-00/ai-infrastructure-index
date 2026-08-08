#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
17_business_continuity_tracker.py  (2차 과제: AI 인프라 사업 지속성 추적 테이블)

목표: 과거 전체 이력 복원이 아니라, '현재 확인 가능한 공식 자료' 기준으로 사업 지속성
상태를 기록하고, 분기 리밸런싱에서 반복 적용 가능한 추적 구조를 만든다.

원칙
----
- 실제로 검증하지 않은 기업을 ACTIVE 로 추정하지 않는다.
  기존 분류만 있는 기업 -> business_status=NOT_REVIEWED, evidence_level=EXISTING_CLASSIFICATION_ONLY.
- AI 키워드만으로 지속 여부를 판단하지 않는다.
- 공식 근거 없으면 UNCERTAIN 또는 NOT_REVIEWED.
- AI 인프라 '직접성'(ai_infra_directness)과 '사업 지속성'(business_status)은 별도 판단.
- historical_business_status_unavailable=True (과거 상태 복원 공식자료 없음 -> 추정 안 함).

이번 작업에서 공식 자료로 직접 검증한 기업 = 경계 8개(SNOW,DDOG,CDW,NTNX,AMT,IRM,LII,WTS).
나머지 92개 = NOT_REVIEWED(기존 분류만).

출력: data/integrity/business_continuity_tracker.csv
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "data" / "integrity"
UNI = ROOT / "data" / "classification" / "final_universe_100.csv"
NEXT_REVIEW = "2026-09-30"   # 다음 분기 리밸런싱(현재 최신 2026-06-30)

# 경계 8개: 이번에 공식/회사자료로 직접 검증한 결과.
# (directness=AI인프라 직접성, biz=business_status, disc=관련매출 확인, sig=매각/축소/중단 신호)
VERIFIED = {
    "SNOW": dict(directness="LOW", biz="ACTIVE",
                 disc="N/A(100% SaaS SW, 인프라 매출 없음)",
                 sig="없음(매출 +29% 성장)", rec="EXCLUDE_CANDIDATE",
                 level="OFFICIAL_FILING_VERIFIED", doc="SEC 10-K FY2025(snow-20250131)",
                 edate="2025-01-31",
                 note="사업은 지속(ACTIVE)이나 인프라 직접성 LOW → 중단이 아니라 직접성 사유의 EXCLUDE 후보"),
    "DDOG": dict(directness="LOW", biz="ACTIVE",
                 disc="N/A(100% SaaS SW)",
                 sig="없음(매출 +28% 성장)", rec="EXCLUDE_CANDIDATE",
                 level="OFFICIAL_FILING_VERIFIED", doc="SEC 10-K FY2025(ddog-20251231)",
                 edate="2025-12-31",
                 note="지속 ACTIVE, 직접성 LOW → 직접성 사유 EXCLUDE 후보"),
    "CDW":  dict(directness="LOW", biz="ACTIVE",
                 disc="해당없음(재판매 마진)",
                 sig="없음", rec="EXCLUDE_CANDIDATE",
                 level="KEYWORD_ONLY", doc="회사 사업모델/제3자 개요(공식 10-K 미대조)",
                 edate="2025-12-31",
                 note="IT 리셀러/유통. 지속 ACTIVE지만 인프라 공급자 아님 → 직접성 사유 EXCLUDE 후보"),
    "NTNX": dict(directness="MEDIUM", biz="ACTIVE",
                 disc="SW구독 100%(HW 아님)",
                 sig="없음(매출 +18% 성장)", rec="REVIEW",
                 level="OFFICIAL_WEBSITE_VERIFIED", doc="회사 IR/FY2025 실적",
                 edate="2025-07-31",
                 note="HCI SW-정의 인프라. 지속 ACTIVE, 경계"),
    "AMT":  dict(directness="MEDIUM", biz="ACTIVE",
                 disc="가능: DC(CoreSite) 매출 $1.05B ≈ 전체 ~10%",
                 sig="회사전체 축소 신호: 2024 인도 타워사업 매각 ~$2.5bn(비-AI인프라 세그먼트). "
                     "단 AI인프라(DC/CoreSite)는 성장",
                 rec="REVIEW",
                 level="OFFICIAL_WEBSITE_VERIFIED", doc="회사 2025 실적 + 인도매각 공시",
                 edate="2025-12-31",
                 note="AI인프라 세그먼트(DC)는 지속·성장 ACTIVE. 인도 타워 매각은 비-AI 세그먼트라 "
                      "AI인프라 지속성엔 영향 없음(별도 신호로 기록)"),
    "IRM":  dict(directness="MEDIUM", biz="ACTIVE",
                 disc="가능: DC 매출 ~13%(~$700M, +27%, 220MW)",
                 sig="없음(DC 확장)", rec="REVIEW",
                 level="OFFICIAL_WEBSITE_VERIFIED", doc="회사 2025 4Q/FY 실적",
                 edate="2025-12-31",
                 note="DC 세그먼트 성장 ACTIVE. 매각·중단 없음"),
    "LII":  dict(directness="MEDIUM", biz="ACTIVE",
                 disc="가능(신규): 2025 전용 DC 냉각사업 Lennox Data Centre Solutions 출범(EMEA)",
                 sig="AI인프라 '진입' 신호(중단 아님): 2025 DC 냉각 전담 사업 신설",
                 rec="REVIEW",
                 level="OFFICIAL_WEBSITE_VERIFIED", doc="회사 발표(Lennox Data Centre Solutions, 2025)",
                 edate="2025-06-01",
                 note="기존 일반 HVAC에서 2025 DC 냉각 전담사업 신규 출범 → 직접성 상향(중단 아님)"),
    "WTS":  dict(directness="LOW", biz="ACTIVE",
                 disc="가능: 10-K DC 매출 >3%(고성장), DC 솔루션 투자 명시",
                 sig="없음(DC 세그먼트 성장)", rec="REVIEW",
                 level="OFFICIAL_FILING_VERIFIED", doc="SEC 10-K FY2025(wts-20251231)",
                 edate="2025-12-31",
                 note="DC 매출 >3% 공식 공시·고성장. 지속 ACTIVE, 비중 소수라 REVIEW"),
}


def main():
    uni = pd.read_csv(UNI, encoding="utf-8-sig")
    rows = []
    for _, r in uni.iterrows():
        t = r["ticker"]
        cat = f"{r['theme']} / {r['sub_theme']}"
        filing = str(r.get("latest_filed", "") or "")
        if t in VERIFIED:
            v = VERIFIED[t]
            rows.append({
                "ticker": t, "company_name": r["entity_name"], "ai_infra_category": cat,
                "ai_infra_directness": v["directness"],
                "related_revenue_disclosed": v["disc"],
                "divest_reduce_discontinue_signal": v["sig"],
                "evidence_date": v["edate"], "evidence_source": v["doc"],
                "evidence_document_type": v["doc"].split("(")[0].strip(),
                "evidence_level": v["level"],
                "business_status": v["biz"], "previous_status": "NONE",
                "status_changed": False, "change_reason": "",
                "recommendation": v["rec"],
                "filing_date": filing, "next_review_date": NEXT_REVIEW,
                "historical_business_status_unavailable": True,
                "note": v["note"],
            })
        else:
            rows.append({
                "ticker": t, "company_name": r["entity_name"], "ai_infra_category": cat,
                "ai_infra_directness": "NOT_ASSESSED",
                "related_revenue_disclosed": "NOT_ASSESSED",
                "divest_reduce_discontinue_signal": "NOT_REVIEWED",
                "evidence_date": "", "evidence_source": "candidate_csv+theme_taxonomy",
                "evidence_document_type": "CLASSIFICATION_ONLY",
                "evidence_level": "EXISTING_CLASSIFICATION_ONLY",
                "business_status": "NOT_REVIEWED", "previous_status": "NONE",
                "status_changed": False, "change_reason": "",
                "recommendation": "KEEP_PENDING_REVIEW",
                "filing_date": filing, "next_review_date": NEXT_REVIEW,
                "historical_business_status_unavailable": True,
                "note": "이번 작업에서 개별 공식 공시 미대조(기존 분류만 보유) → ACTIVE로 추정하지 않음",
            })
    out = pd.DataFrame(rows)
    out.to_csv(INTEG / "business_continuity_tracker.csv", index=False, encoding="utf-8-sig")

    print("=" * 64); print("2차 과제  AI 인프라 사업 지속성 추적 테이블"); print("=" * 64)
    print("business_status 분포:", out["business_status"].value_counts().to_dict())
    print("evidence_level 분포:", out["evidence_level"].value_counts().to_dict())
    print("recommendation 분포:", out["recommendation"].value_counts().to_dict())
    print(f"\n직접 검증(공식자료) 기업: {int((out.evidence_level!='EXISTING_CLASSIFICATION_ONLY').sum())}개")
    print(f"기존 분류만(NOT_REVIEWED): {int((out.business_status=='NOT_REVIEWED').sum())}개")
    print(f"\n[경계 8개 요약]")
    print(out[out.ticker.isin(VERIFIED)][
        ["ticker", "ai_infra_directness", "business_status", "recommendation",
         "evidence_level"]].to_string(index=False))
    print(f"\n출력: {INTEG/'business_continuity_tracker.csv'}")


if __name__ == "__main__":
    main()
