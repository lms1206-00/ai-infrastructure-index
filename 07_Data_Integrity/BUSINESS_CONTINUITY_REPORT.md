# AI 인프라 사업 지속성 추적 — 최종 보고서 (2026-07-27)

두 번째 핵심 보완 과제. 목표는 100개 기업의 과거 이력 완전 복원이 아니라, **현재 확인
가능한 공식 자료로 사업 지속성 상태를 기록**하고 **분기 리밸런싱에서 반복 적용 가능한
추적 구조**를 구현하는 것이다. 기존 코드·산출물은 덮어쓰지 않았고 `08_Data_Integrity/
code/17~19`, `data/integrity/`에만 추가했다.

> **과장 금지 원칙 준수**: "100개 기업 모두 검증 완료"가 **아니다**. 이번 작업에서
> **공식 자료로 직접 검증한 기업은 경계 8개뿐**이고, **나머지 92개는 기존 분류만
> 보유(NOT_REVIEWED)** 이며 ACTIVE로 추정하지 않았다.

---

## 1. 100개 기업 사업 지속성 추적 테이블 (`business_continuity_tracker.csv`)

필드: ticker, company_name, ai_infra_category, ai_infra_directness,
related_revenue_disclosed, divest_reduce_discontinue_signal, evidence_date,
evidence_source, evidence_document_type, evidence_level, business_status,
previous_status, status_changed, change_reason, filing_date, next_review_date,
historical_business_status_unavailable, recommendation, note.

### 상태 집계
| 구분 | 값 |
|---|---|
| business_status | **ACTIVE 8, NOT_REVIEWED 92** (REDUCED 0, DISCONTINUED 0, UNCERTAIN 0) |
| evidence_level | OFFICIAL_FILING_VERIFIED 3, OFFICIAL_WEBSITE_VERIFIED 4, KEYWORD_ONLY 1, EXISTING_CLASSIFICATION_ONLY 92 |
| recommendation | EXCLUDE_CANDIDATE 3, REVIEW 5, KEEP_PENDING_REVIEW 92 |
| **직접 검증 기업** | **8** |
| **기존 분류만(NOT_REVIEWED)** | **92** |
| historical_business_status_unavailable | 100 (전건 True — 과거상태 소급 안 함) |

- ACTIVE 8개는 **모두 경계 8개**로, 최신 공식 자료에서 사업 지속 확인. **DISCONTINUED·REDUCED
  로 확인된 종목은 이번 검증 범위(8개)에서 0건**(단, AMT는 아래 참고).

---

## 2. 경계 8개 상세 검토표 (`boundary8_detail.csv`)

"AI 인프라 직접성이 낮음"과 "사업을 중단함"은 **별개 판단**으로 분리 기록했다.

| ticker | AI인프라 직접성 | 관련매출 확인 | 매각/축소/중단 신호 | business_status | 권고 | 근거(evidence_level) |
|---|---|---|---|---|---|---|
| SNOW | LOW | N/A(SaaS) | 없음(+29%) | ACTIVE | **EXCLUDE 후보**(직접성) | 10-K FY2025 (FILING) |
| DDOG | LOW | N/A(SaaS) | 없음(+28%) | ACTIVE | **EXCLUDE 후보**(직접성) | 10-K FY2025 (FILING) |
| CDW | LOW | 해당없음(재판매) | 없음 | ACTIVE | **EXCLUDE 후보**(직접성) | 제3자 개요 (KEYWORD_ONLY) |
| NTNX | MEDIUM | SW구독 100% | 없음(+18%) | ACTIVE | REVIEW | 회사 IR (WEBSITE) |
| AMT | MEDIUM | 가능: DC ~10%($1.05B) | **회사전체 축소**: 2024 인도 타워매각 ~$2.5bn(비-AI). DC는 성장 | ACTIVE | REVIEW | 실적+매각공시 (WEBSITE) |
| IRM | MEDIUM | 가능: DC ~13%(+27%) | 없음(DC 확장) | ACTIVE | REVIEW | 실적 (WEBSITE) |
| LII | MEDIUM | 가능(신규): 2025 DC 냉각 전담사업 출범 | **AI인프라 진입**(중단 아님) | ACTIVE | REVIEW | 회사 발표 (WEBSITE) |
| WTS | LOW | 가능: 10-K DC >3% 고성장 | 없음(성장) | ACTIVE | REVIEW | 10-K FY2025 (FILING) |

### 핵심 관찰(공식 자료 기반)
- **매각·철수·중단(DISCONTINUED) 종목 0건.** 8개 모두 관련 사업 지속.
- **AMT**: 2024년 인도 타워 사업을 ~$2.5bn에 매각(회사 전체로는 축소)했으나, 이는
  **비-AI 인프라(통신 타워) 세그먼트**이고 **AI 인프라(CoreSite 데이터센터)는 성장 중** →
  AI 인프라 지속성엔 영향 없음(신호는 별도 기록).
- **LII·WTS**: 오히려 2025년 **AI 인프라(DC 냉각) 사업을 신규/확대** — LII는 전용 데이터센터
  냉각 사업부(Lennox Data Centre Solutions) 출범, WTS는 10-K에 DC 매출 >3% 고성장 공시.
  → 중단이 아니라 진입/확대. 관련 매출 확인 가능성이 이전보다 향상됨(직접성 재평가 여지).
- **SNOW·DDOG·CDW**: 사업은 지속(ACTIVE)이나 AI 인프라 **직접성 LOW** → **직접성 사유의
  EXCLUDE 후보**(사업 중단 사유가 아님).

---

## 3. 상태 변경 이력 원장 (`status_change_ledger.csv`) + 전이 함수

- `18_status_transition.py`의 `transition(prev, evidence_kind, evidence_date, rebalance_date)`
  구현, **self-test PASS**:
  - `KEYWORD_DECLINE` → `UNCERTAIN`(REVIEW 보류), **자동 편출 아님**.
  - `OFFICIAL_EXIT` → `DISCONTINUED` + `exclusion_candidate=True`(실제 편출은 별도 승인).
  - 미래 evidence_date → **PIT 차단**(소급 금지, pit_ok=False).
  - `PARTIAL_DIVEST` → `REDUCED`.
- 원장 baseline 100행(최초 관측, previous_status=NONE, status_changed=False).
  다음 분기부터 이전 상태 대비 변화가 기록된다. exclusion_candidate=True 3건(SNOW·DDOG·CDW).

---

## 4. 분기별 갱신 절차 문서
`docs/BUSINESS_CONTINUITY_PROCEDURE.md`: 연차(10-K/20-F) 확인 → 분기간(8-K/6-K·기업행위)
신호 스캔 → 키워드 감소는 REVIEW로만 → 공식 매각·중단시 DISCONTINUED → next_review 기록.
자동 편출 금지, PIT 강제.

---

## 5. PIT 검증 결과 (`pit_validation_report.csv`)
| 검증 | 결과 |
|---|---|
| evidence_date ≤ 관측일(2026-07-27) | PASS(위반 0) |
| evidence_date ≤ next_review_date | PASS(위반 0) |
| filing_date ≤ 관측일 | PASS(위반 0) |
| 과거상태 소급 없음(hist_unavailable=True·prev=NONE·changed=False) | PASS(전건) |

직접검증 8개 evidence_date 범위 2025-01-31 ~ 2025-12-31 (모두 사용 시점 이전). **전체 PASS.**

---

## 6. 자동화된 부분 vs 수동 검토 필요
| 부분 | 상태 |
|---|---|
| 상태 전이 규칙·원장·PIT 검증 | **IMPLEMENTED**(코드+self-test) |
| 100개 추적 테이블 생성/집계 | **IMPLEMENTED** |
| 경계 8개 공식자료 판독→상태 부여 | **VALIDATED**(이번에 수동 검증) |
| 10-K/20-F·8-K/6-K 자연어 신호 판독 자동화 | **DOCUMENTED_ONLY**(수동 검토 필요) |
| 92개 CORE 개별 공식 대조 | **UNRESOLVED**(미수행 → NOT_REVIEWED) |

---

## 7. 요구사항 상태 분류
| 요구사항 | 상태 |
|---|---|
| 100개 추적 테이블(전 필드) | **IMPLEMENTED** |
| 기존분류만→NOT_REVIEWED/EXISTING_CLASSIFICATION_ONLY(ACTIVE 추정 금지) | **IMPLEMENTED** |
| 경계 8개 공식자료 검증(직접성·지속·매출·매각신호 분리) | **VALIDATED** |
| status transition 함수 + 변경 이력 원장 | **IMPLEMENTED** |
| 분기 갱신 절차 문서 | **DOCUMENTED_ONLY**(절차 확정, 자연어 판독은 수동) |
| PIT(evidence_date/filing_date·소급 금지) | **IMPLEMENTED / VALIDATED** |
| 자동 편출 금지·후보만 제시 | **IMPLEMENTED**(exclusion_candidate 표기, 실제 편출 안 함) |
| 92개 개별 공식 검증 | **UNRESOLVED**(범위상 미수행, 정직 고지) |

---

## 8. 재현 실행 명령어
```bash
.venv/Scripts/python.exe 08_Data_Integrity/code/17_business_continuity_tracker.py
.venv/Scripts/python.exe 08_Data_Integrity/code/18_status_transition.py
.venv/Scripts/python.exe 08_Data_Integrity/code/19_pit_validation.py
```
(`PYTHONIOENCODING=utf-8` 권장; CSV는 utf-8-sig)

## 9. 잔여 한계 (정직 고지)
1. **직접 검증 8개 / 기존분류만 92개** — 100개 전수 검증 아님. 92개는 NOT_REVIEWED.
2. 사업보고서 자연어(핵심사업 유지/키워드) 판독은 수동. 자동 evidence_kind 부여 미구현.
3. 과거 시점의 사업 지속성 상태는 공식 자료 부재로 복원하지 않음(historical_business_status_unavailable=True 전건).
4. 지속성 판정은 지수 비중을 바꾸지 않는다(자동 편출 없음). 실제 편출은 별도 승인 절차.
