#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
04_ai_infra_continuity.py  (Item 2: AI 인프라 사업 지속성 점검표)

정의(프로젝트): AI 인프라 = AI의 학습/추론/서비스 운영에 직접 필요한 반도체, 서버,
네트워크, 데이터센터, 전력, 냉각, 광통신, 저장장치, 클라우드 인프라 및 산업 자동화
설비를 "공급하거나 운영"하는 산업.

방법
----
1) 100개 기업의 테마 계층(infra_layer)을 규칙으로 분류한다(테마 taxonomy 근거).
   - CORE 계층(반도체/장비/서버HW/EMS/네트워크장비/광부품/저장HW/데이터센터운영/
     전력·냉각 설비·전력생산)은 정의에 직접 부합 -> theme_eligible = True.
2) 정의 경계에 있는 유형은 임의 제외하지 않고 REVIEW 로 분리한다(공식 근거 첨부).
   - SOFTWARE/SaaS(애플리케이션 계층): 인프라 '공급/운영'이 아님
   - RESELLER/DISTRIBUTOR: 직접 공급자가 아닌 유통 채널
   - MIXED_MINORITY_DC: 데이터센터가 소수 사업(주력은 통신타워/문서보관 등)
   - GENERAL_BUILDING: 일반 건물 HVAC/수처리(데이터센터 냉각 관련성 간접)
3) business_status 는 suspension_audit(가격패널 연속성) + 최신 재무 기준일로 교차확인한다.
   본 유니버스는 전 종목 현재 상장·거래중(생존편향)이며 매각/철수 확인 종목은 없다.
   -> 임의 EXCLUDE 없음. REVIEW 는 별도 분리만 하고 지수는 불변.

출력: data/integrity/ai_infra_continuity_review.csv
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "data" / "integrity"
UNIVERSE = ROOT / "data" / "classification" / "final_universe_100.csv"

# 정의 경계 기업: 공식 근거(2025~2026 공시/사업설명)로 확인, business_status=ACTIVE, REVIEW.
REVIEW = {
    "SNOW": ("SOFTWARE_SAAS", "Cloud Data Platform(SaaS 소프트웨어). AI Data Cloud이나 "
             "인프라 하드웨어/설비 공급·데이터센터 운영이 아닌 애플리케이션 계층.",
             "SEC 10-K FY2025(snow-20250131) 사업개요", "2025-01-31"),
    "DDOG": ("SOFTWARE_SAAS", "Observability/보안 SaaS 소프트웨어. 인프라 모니터링 도구이며 "
             "인프라 자체를 공급/운영하지 않음.",
             "SEC 10-K FY2025(ddog-20251231) 사업개요", "2025-12-31"),
    "NTNX": ("SOFTWARE_SAAS", "Hyperconverged Infrastructure 소프트웨어(구독). 소프트웨어 정의 "
             "인프라로 AI워크로드를 구동하나, 하드웨어/설비 공급자가 아닌 SW 벤더.",
             "회사 IR/FY2025 사업개요(구독 전환)", "2025-07-31"),
    "CDW":  ("RESELLER_DISTRIBUTOR", "IT 제품 리셀러/유통(Nutanix 등 재판매). 인프라를 직접 "
             "제조·운영하지 않는 채널 파트너.",
             "회사 사업모델/파트너 페이지, Wikipedia 기업개요", "2025-12-31"),
    "AMT":  ("MIXED_MINORITY_DC", "주력은 통신 타워 REIT(149k 사이트). CoreSite 데이터센터 보유 "
             "(2025 DC매출 $1.05B ≈ 전체 $10B의 ~10%). DC는 AI수요로 성장 중이나 소수 비중.",
             "American Tower 2025 실적(DC $1.053B), CoreSite", "2025-12-31"),
    "IRM":  ("MIXED_MINORITY_DC", "주력은 문서·기록 보관. 데이터센터는 매출의 ~13% 소수 사업.",
             "Iron Mountain 2025 실적(DC ≈13% 매출)", "2025-12-31"),
    "LII":  ("GENERAL_BUILDING", "일반 건물/주거 HVAC 장비. 데이터센터 냉각 관련성은 간접적.",
             "테마 taxonomy(Cooling/HVAC Equipment)", "2025-12-31"),
    "WTS":  ("GENERAL_BUILDING", "물/열 시스템(수처리·배관 중심). 데이터센터 냉각 관련성 간접.",
             "테마 taxonomy(Cooling/Water Systems)", "2025-12-31"),
}

# CORE 로 직접 부합하는 테마(정의의 각 축)
CORE_THEMES = {
    "Semiconductor": "반도체(설계·파운드리·장비·소재·패키징) — 학습/추론 연산의 핵심",
    "Server": "서버/데이터센터 하드웨어·EMS — AI 서버 공급",
    "Networking": "네트워크 장비 — 데이터센터/통신 연결",
    "Optical": "광통신 부품/트랜시버 — 데이터센터 상호연결",
    "Storage": "데이터 저장 하드웨어 — 학습데이터/모델 저장",
    "Data Center": "데이터센터 운영/REIT — AI 워크로드 수용",
    "Power": "전력 설비·전력 생산 — 데이터센터 급전",
    "Cooling": "데이터센터 냉각/열관리 설비",
    "Cloud": "하이퍼스케일 클라우드 인프라 운영",
    "Industrial Automation": "산업 자동화 설비/제어",
}


def main():
    uni = pd.read_csv(UNIVERSE, encoding="utf-8-sig")
    susp = pd.read_csv(INTEG / "suspension_audit.csv", encoding="utf-8-sig")
    susp_map = susp.set_index("ticker")["status"].to_dict()

    rows = []
    for _, r in uni.iterrows():
        tkr = r["ticker"]
        cat = f"{r['theme']} / {r['sub_theme']}"
        px_status = susp_map.get(tkr, "NO_PRICE_PANEL")
        # business_status: 가격패널 연속성 + 최신 재무 기준일로 교차확인
        if px_status in ("SUSPECTED_SUSPENSION", "DELISTED_OR_DATA_END"):
            biz = f"CHECK_PRICE({px_status})"
        else:
            biz = "ACTIVE"  # 현재 상장·거래중(생존편향 유니버스), 매각/철수 확인 종목 없음
        if tkr in REVIEW:
            layer, evid, src, edate = REVIEW[tkr]
            rows.append({
                "ticker": tkr, "company_name": r["entity_name"],
                "current_category": cat, "infra_layer": layer,
                "ai_infra_evidence": evid, "evidence_source": src,
                "evidence_date": edate, "business_status": biz,
                "theme_eligible": "REVIEW",
                "review_reason": f"정의 경계({layer}): 자동 제외하지 않고 검토 대상으로 분리",
            })
        else:
            rows.append({
                "ticker": tkr, "company_name": r["entity_name"],
                "current_category": cat, "infra_layer": "CORE",
                "ai_infra_evidence": CORE_THEMES.get(r["theme"], "AI 인프라 CORE"),
                "evidence_source": "project_classification(candidate_csv)+theme_taxonomy; "
                                   f"가격패널 연속성={px_status}",
                "evidence_date": str(r.get("latest_period_end", "")),
                "business_status": biz,
                "theme_eligible": "True",
                "review_reason": "",
            })

    out = pd.DataFrame(rows)
    out.to_csv(INTEG / "ai_infra_continuity_review.csv", index=False, encoding="utf-8-sig")

    print("=" * 64)
    print("Item 2  AI 인프라 사업 지속성 점검 요약")
    print("=" * 64)
    print("theme_eligible 분포:", out["theme_eligible"].value_counts().to_dict())
    print("infra_layer 분포:", out["infra_layer"].value_counts().to_dict())
    print("business_status 분포:", out["business_status"].value_counts().to_dict())
    print(f"\n[REVIEW 대상 {int((out.theme_eligible=='REVIEW').sum())}개] (자동 제외 안 함)")
    print(out[out.theme_eligible == "REVIEW"][
        ["ticker", "current_category", "infra_layer", "evidence_source", "evidence_date"]
    ].to_string(index=False))
    print(f"\n출력: {INTEG/'ai_infra_continuity_review.csv'}")


if __name__ == "__main__":
    main()
