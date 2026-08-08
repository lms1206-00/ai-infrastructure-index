# AI 인프라 사업 지속성 — 분기 갱신 절차

목적: 100개 유니버스 기업이 AI 인프라 핵심 사업을 지속하는지를 분기 리밸런싱마다
반복 추적한다. 과거 이력 복원이 목표가 아니라, **각 시점에 공개된 공식 자료로 상태를
갱신**하는 구조다. 구현: `17~19` + `18_status_transition.py`의 `transition()`.

## 1. 분기 리밸런싱 시점 절차 (rebalance_date 기준)

1. **연차 확인(핵심)**: 각 기업의 최신 10-K(미국) 또는 20-F(외국)에서 AI 인프라 핵심
   사업 유지 여부 확인 → 신호 `ANNUAL_CONFIRM` → `ACTIVE`.
   - 단, **filing_date ≤ rebalance_date** 인 문서만 사용(PIT).
2. **분기 사이 이벤트 스캔**: 8-K(미국)·6-K(외국)·기업행위·사업 매각 공시에서
   중단·매각·축소 신호 확인.
   - 일부 매각/매출비중 감소 → `PARTIAL_DIVEST` → `REDUCED`.
   - 매각·철수·중단 공식 확인 → `OFFICIAL_EXIT` → `DISCONTINUED`(+ exclusion_candidate=True).
3. **AI 키워드 감소 처리**: 사업보고서의 AI 키워드가 줄거나 사라진 것**만으로는
   자동 편출하지 않는다** → `KEYWORD_DECLINE` → `UNCERTAIN`(REVIEW 보류). 공식 매각·중단
   근거가 확인될 때만 DISCONTINUED로 전이.
4. **신규 정보 없음**: `NO_NEW_INFO` → 상태 유지.
5. **다음 검토 예정일(next_review_date) 기록**: 통상 다음 분기말.

## 2. 편출 원칙 (자동 편출 금지)
- 이 절차는 **상태 판정과 편출 후보 표시까지만** 한다. `DISCONTINUED` 로 바뀌어도
  **실제 편출은 별도 승인 또는 최종 유니버스 확정 단계에서** 적용한다.
- `EXCLUDE_CANDIDATE`(직접성 사유)와 `DISCONTINUED`(사업 중단 사유)는 별개다.
  전자는 "AI 인프라 직접성 낮음", 후자는 "사업 중단 확인" — 필드·사유를 분리 기록.

## 3. PIT 원칙
- 전이는 `evidence_date ≤ rebalance_date` 인 근거만 사용(`transition()`이 강제; 미래
  공시는 반환값에서 무시하고 `pit_ok=False` 기록).
- 과거 상태를 현재 정보로 소급하지 않는다. 공식 자료가 없으면 `NOT_REVIEWED` 또는
  `UNCERTAIN`, `historical_business_status_unavailable=True`.

## 4. 상태 전이 다이어그램(요약)
```
                ANNUAL_CONFIRM
   NOT_REVIEWED ───────────────▶ ACTIVE ──PARTIAL_DIVEST──▶ REDUCED
        │                          │  │                        │
        │                          │  └──OFFICIAL_EXIT─────────┼──▶ DISCONTINUED (exclusion_candidate)
        │                          │                           │
        └───(검토했으나 불명확)──▶ UNCERTAIN ◀──KEYWORD_DECLINE─┘
```
- KEYWORD_DECLINE → UNCERTAIN(보류), 절대 DISCONTINUED/자동편출 아님.
- DISCONTINUED 는 OFFICIAL_EXIT(공식 확인)에서만.

## 5. 자동화 범위 vs 수동 검토
| 단계 | 자동화 여부 |
|---|---|
| 상태 전이 규칙 적용(transition) | **IMPLEMENTED**(함수+self-test) |
| 원장 기록/이전상태 비교 | **IMPLEMENTED**(status_change_ledger) |
| PIT(evidence_date/filing_date) 검증 | **IMPLEMENTED**(19_pit_validation) |
| 10-K/20-F·8-K/6-K 신호 판독(evidence_kind 부여) | **수동 검토 필요**(자연어 공시 해석은 미자동화) |
| 92개 CORE 개별 공식 대조 | **수동 검토 필요**(이번엔 미수행 → NOT_REVIEWED) |

## 6. 재현 실행
```bash
.venv/Scripts/python.exe 08_Data_Integrity/code/17_business_continuity_tracker.py
.venv/Scripts/python.exe 08_Data_Integrity/code/18_status_transition.py
.venv/Scripts/python.exe 08_Data_Integrity/code/19_pit_validation.py
```
