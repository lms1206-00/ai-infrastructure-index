#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
25_universe_selection_rationale.py

100개 유니버스 종목의 '선정 사유'를 실제 final_universe_100.csv 값으로 문서화한다.
임의 서술 없음 — 테마/candidate_score/selection_score 구성/선정단계/랭크를 그대로 기술.

출력:
  data/integrity/universe_selection_rationale.csv   (종목별 사유표)
  08_Data_Integrity/UNIVERSE_SELECTION_RATIONALE.md  (방법론 + 테마별 표)
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "data" / "integrity"
DOCS = ROOT / "08_Data_Integrity"
UNI = ROOT / "data" / "classification" / "final_universe_100.csv"

# 테마별 'AI 인프라 축' 근거(정의)
THEME_WHY = {
    "Semiconductor": "AI 학습·추론 연산의 핵심(설계·파운드리·장비·소재·패키징)",
    "Server": "AI 서버/데이터센터 하드웨어·EMS 공급",
    "Networking": "데이터센터/통신 네트워크 장비",
    "Optical": "데이터센터 광통신 부품·트랜시버",
    "Storage": "학습데이터·모델 저장 하드웨어",
    "Data Center": "AI 워크로드 수용 데이터센터 운영/REIT",
    "Power": "데이터센터 급전 전력설비·전력생산",
    "Cooling": "데이터센터 냉각/열관리 설비",
    "Cloud": "하이퍼스케일 클라우드 인프라 운영",
    "Industrial Automation": "산업 자동화 설비·제어",
}
THEME_ORDER = ["Semiconductor", "Power", "Server", "Networking", "Cooling",
               "Optical", "Data Center", "Cloud", "Industrial Automation", "Storage"]


def rationale_sentence(r) -> str:
    stage = "테마쿼터" if r["selection_stage"] == "theme_quota" else "부족분보충(shortage_fill)"
    return (f"{r['theme']}/{r['sub_theme']} 테마. AI인프라 직접성 candidate_score {int(r['candidate_score'])}, "
            f"종합 selection_score {r['selection_score']:.1f}"
            f"(관련성60%×{r['ai_relevance_score']:.0f} + 품질25%×{r['quality_component']:.0f} + "
            f"팩터15%×{r['factor_component']:.0f}). {stage} 단계·유니버스랭크 {int(r['universe_rank'])}위. "
            f"데이터품질 {r['data_quality_score']:.0f}, 가용팩터 {int(r['factor_available_count'])}/13.")


def main():
    u = pd.read_csv(UNI, encoding="utf-8-sig")
    u["selection_reason_doc"] = u.apply(rationale_sentence, axis=1)
    keep = ["universe_rank", "ticker", "entity_name", "theme", "sub_theme", "quota_theme",
            "selection_stage", "candidate_score", "ai_relevance_score", "quality_component",
            "factor_component", "selection_score", "data_quality_score",
            "factor_available_count", "selection_reason_doc"]
    out = u[keep].sort_values("universe_rank")
    out.to_csv(INTEG / "universe_selection_rationale.csv", index=False, encoding="utf-8-sig")

    # 마크다운 문서
    lines = []
    lines.append("# 유니버스 100 종목 선정 사유 문서\n")
    lines.append("근거: `data/classification/final_universe_100.csv` 실측값(임의 서술 없음). "
                 "선정 로직: `02_Data_Preprocessing/code/03_classification_rule.py`.\n")
    lines.append("## 선정 방법 요약\n")
    lines.append("1. **후보 풀**: 큐레이션 `ai_infrastructure_candidates.csv`(142행/135티커), "
                 "각 종목에 테마·sub_theme·candidate_score(AI인프라 직접성 0~100) 부여.\n"
                 "2. **Entity Master 매칭**: SEC 재무가 있는 후보만 진행(미매칭 7 탈락).\n"
                 "3. **selection_score = 관련성(candidate_score)×0.60 + 데이터품질×0.25 + 팩터가용성×0.15**.\n"
                 "4. **테마 쿼터 선정**: 테마별 상위 selection_score 순으로 쿼터 충족(98건).\n"
                 "5. **부족분 보충**: Storage 후보부족(3<5)으로 빈 2슬롯을 잔여 최고점으로 보충(2건).\n"
                 "6. 정확히 100개 → universe_rank 부여.\n")
    lines.append(f"- 총 100종목, selection_score {out.selection_score.min():.1f}~"
                 f"{out.selection_score.max():.1f}, "
                 f"theme_quota {int((out.selection_stage=='theme_quota').sum())} + "
                 f"shortage_fill {int((out.selection_stage=='shortage_fill').sum())}.\n")

    lines.append("\n## 테마별 선정 종목 (AI 인프라 축 근거 포함)\n")
    for th in THEME_ORDER:
        grp = out[out.quota_theme == th].sort_values("universe_rank")
        if not len(grp):
            continue
        lines.append(f"\n### {th} — {THEME_WHY.get(th,'')} ({len(grp)}종목)\n")
        lines.append("| 랭크 | ticker | sub_theme | cand_score | sel_score | 단계 |")
        lines.append("|---|---|---|---|---|---|")
        for _, r in grp.iterrows():
            stg = "쿼터" if r["selection_stage"] == "theme_quota" else "보충"
            lines.append(f"| {int(r['universe_rank'])} | {r['ticker']} | {r['sub_theme']} | "
                         f"{int(r['candidate_score'])} | {r['selection_score']:.1f} | {stg} |")

    lines.append("\n## 종목별 상세 사유\n")
    lines.append("전체 100종목의 문장형 사유는 `data/integrity/universe_selection_rationale.csv` "
                 "의 `selection_reason_doc` 컬럼 참조. 예시:\n")
    for _, r in out.head(3).iterrows():
        lines.append(f"- **{r['ticker']}** ({r['entity_name']}): {r['selection_reason_doc']}")

    lines.append("\n## 한계·주의\n")
    lines.append("- candidate_score는 큐레이션 사전점수(AI인프라 직접성)로, 개별 공식공시 전수 "
                 "검증이 아니라 큐레이션 기준이다(SNOW·DDOG·CDW 등 직접성 재검토는 별도 트랙).\n"
                 "- 이 100은 **후보 유니버스**이며, 실제 분기 편입(Top30)은 이후 PIT·자격·"
                 "Factor Score·테마 적격성 게이트를 추가로 통과해야 한다.\n")

    (DOCS / "UNIVERSE_SELECTION_RATIONALE.md").write_text("\n".join(lines), encoding="utf-8")

    print("생성 완료:")
    print(f"  {INTEG/'universe_selection_rationale.csv'} ({len(out)}종목)")
    print(f"  {DOCS/'UNIVERSE_SELECTION_RATIONALE.md'}")
    print("\n[테마별 종목수]")
    print(out.quota_theme.value_counts().reindex(THEME_ORDER).to_string())


if __name__ == "__main__":
    main()
