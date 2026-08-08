# EXECUTION_REPORT — 데이터 무결성 보완 (Item 1~5)

- 작성일: 2026-07-27
- 범위: AI 인프라 커스텀 인덱스 파이프라인의 회계기준 혼재·사업 지속성·기업행위·
  예외 편출·거래정지 5개 항목 점검 및 보완
- **원칙 준수**: 기존 코드/산출물은 **한 줄도 덮어쓰지 않았다**. 모든 보완은
  `08_Data_Integrity/`(코드·문서)와 `data/integrity/`(신규 데이터)에만 추가했다.
  세션 시작 시점 백업(`08_Data_Integrity/backup_baseline/`) 대비 원본 산출물
  (final_universe_100, index_weights_latest, factor_scores_latest, performance_summary)은
  **바이트 동일(UNCHANGED)**, `01_factor_engine.py`도 미변경, `data/factors/*`도 재생성 없음.
- 임의 데이터 생성 없음. 모든 판정은 (a) 실제 fact/가격 데이터 또는 (b) 회사·거래소
  **공식 공시/보도**만 근거로 한다.

---

## 0. 수정·추가한 코드와 파일 목록 (출력물 #1)

### 코드 (`08_Data_Integrity/code/`)
| 파일 | 항목 | 역할 |
|---|---|---|
| `01_accounting_standard_audit.py` | 1 | 실제 팩터엔진 import → 5항목의 source taxonomy/tag 기록, 회계기준 분류 |
| `02_accounting_standard_enrich.py` | 1 | 회계기준 전환 탐지 + 유니버스 5필드 보강 + 4팩터 영향 요약 |
| `03_factors_enriched.py` | 1 | 팩터 패널에 5필드 부착(값 불변, provenance만) |
| `04_ai_infra_continuity.py` | 2 | 100기업 AI 인프라 지속성 판정표(REVIEW 분리) |
| `05_suspension_audit.py` | 5 | 가격결측 5범주 분류(거래정지 판별) |
| `06_corporate_actions.py` | 3 | 기업행위·상장상태 7필드 + PIT 정합성 점검 |
| `07_exceptional_rebalance.py` | 4 | pro-rata 특별편출 로직(self-test) + reason_code 원장 |

### 신규 데이터 (`data/integrity/`)
`accounting_standard_company.csv`, `accounting_standard_metric_detail.csv`,
`accounting_standard_transitions.csv`, `final_universe_100_accounting.csv`,
`factors_enriched_universe.csv`, `ai_infra_continuity_review.csv`,
`suspension_audit.csv`, `suspension_events.csv`, `corporate_actions.csv`,
`special_removal_events.csv`(스키마·0행), `rebalance_ledger.csv`.

### 문서 (`08_Data_Integrity/docs/`)
`EXCEPTION_REBALANCE_RULES.md`(Item 4 규칙), 본 `EXECUTION_REPORT.md`.

---

## 1. IFRS / US-GAAP 혼재 점검 결과 (출력물 #2)

### 방법
Fact Store(`data/facts/{CIK}.parquet`)에는 원본 `taxonomy` 컬럼(us-gaap / ifrs-full /
dei / srt)이 존재한다. 기존 `01_factor_engine.py`를 **그대로 import**하여
`choose_metric_fact()`가 실제로 선택한 fact의 `taxonomy`·`tag`를 5항목
(Revenue, Operating Income, Net Income, Assets, Liabilities)에 대해 기록했다.
→ 실제 팩터가 나온 근거와 100% 일치.

### 결과
- **기업별 회계기준**: US-GAAP 94, IFRS 4(TSM·GFS·UMC·NOK), MIXED_FILER 2(CLS·ERIC).
- **추가 필드**(요구된 5종 전부 데이터에 반영):
  `accounting_standard`, `<metric>_source_taxonomy`, `<metric>_source_tag`,
  `standardized_metric_map`(revenue→Revenue …), `mixed_standard_warning`
  + 파생 `growth_cross_standard_warning`.
  → `final_universe_100_accounting.csv`(기업 100행), `factors_enriched_universe.csv`(5,227행).

**[A] 동일 기준일 내 혼재(mixed_standard_warning) = 0건.**
CLS·ERIC처럼 fact 저장소에 두 taxonomy가 섞여 있어도, 한 기준일(anchor=accession 단위)의
5개 항목은 **모두 같은 재무 taxonomy**로 해석된다. 팩터엔진이 anchor를 accession별로 잡고
tag 우선순위·form cycle·fy/fp로 후보를 좁히기 때문. 따라서
- **operating_margin / ROA / debt_ratio**(한 행 내부 값들의 비율)에 혼재 영향 **없음 → 값 불변**.

**[B] 회계기준 전환(시계열) = 1건: CLS(Celestica).**
CLS는 2017~2023 IFRS(ifrs-full) → **FY2024(2024-12-31)부터 US-GAAP**로 전환.
성장률 팩터는 당기/전기 비교라, **FY2024 revenue_growth(0.2117)** 는 분자(US-GAAP 2024)와
분모(IFRS 2023)가 서로 다른 기준 → `growth_cross_standard_warning=True`로 플래그.
ERIC은 핵심 5항목이 전 기간 IFRS(us-gaap 6건은 미사용)로 전환 없음.

**[C] 실제 지수에 사용된 최신 성장률의 교차기준 = 0건.**
- CLS 유니버스 최신행은 **FY2025÷FY2024(둘 다 US-GAAP) = 깨끗**(revenue_growth 0.2846).
- CLS 지수 편입은 **2026-03-31 스냅샷 1회(비중 2.64%)뿐**이며, 현재(2026-06-30) Top30에는
  **미포함**. 교차기준 경계(FY2024)는 지수 비중·백테스트에 **한 번도 사용되지 않았다.**

### 4팩터 영향 결론
| 팩터 | 혼재 유형 | 영향 | 상태 |
|---|---|---|---|
| operating_margin | 행 내부 비율 | 혼재 0건 → 값 불변 | VALIDATED |
| roa | 행 내부 비율 | 혼재 0건 → 값 불변 | VALIDATED |
| debt_ratio | 행 내부 비율 | 혼재 0건 → 값 불변 | VALIDATED |
| revenue_growth | 시계열 전환 | CLS FY2024 1건 플래그, **지수 미사용** | IMPLEMENTED(플래그) |

**차단 원리**: 회계기준이 불명확·비교불가한 경우 값을 임의로 잇지 않는다. 팩터엔진은
tag가 없으면 해당 metric을 NaN 처리하고(예: ERIC liabilities=NaN, 임의 대입 안 함),
전환 경계는 플래그로 하류가 인지·배제할 수 있게 한다.

---

## 2. 100개 기업 AI 인프라 사업 지속성 점검표 (출력물 #3)

파일: `data/integrity/ai_infra_continuity_review.csv`
(컬럼: ticker, company_name, current_category, infra_layer, ai_infra_evidence,
evidence_source, evidence_date, business_status, theme_eligible, review_reason)

- **theme_eligible=True(CORE): 92개** — 반도체30·전력15·서버10·네트워크10·냉각8·광통신7·
  클라우드6·데이터센터6·산업자동화5·저장3 중 정의(공급/운영)에 직접 부합.
- **theme_eligible=REVIEW: 8개**(자동 제외하지 않고 분리). business_status 전 종목 **ACTIVE**.

| ticker | 계층 | REVIEW 사유 | 공식 근거 |
|---|---|---|---|
| SNOW | SOFTWARE_SAAS | 클라우드 데이터플랫폼 SW(인프라 공급/운영 아님) | SEC 10-K FY2025 |
| DDOG | SOFTWARE_SAAS | Observability SaaS SW | SEC 10-K FY2025 |
| NTNX | SOFTWARE_SAAS | HCI 소프트웨어(구독) | 회사 IR FY2025 |
| CDW | RESELLER | IT 제품 리셀러/유통 | 회사 사업모델·Wikipedia |
| AMT | MIXED_MINORITY_DC | 주력 통신타워 REIT, DC(CoreSite)는 매출 ~10% | AMT 2025 실적 |
| IRM | MIXED_MINORITY_DC | 주력 문서보관, DC는 매출 ~13% | IRM 2025 실적 |
| LII | GENERAL_BUILDING | 일반/주거 HVAC(DC 냉각 간접) | 테마 taxonomy |
| WTS | GENERAL_BUILDING | 수처리·열 시스템(DC 냉각 간접) | 테마 taxonomy |

business_status는 `suspension_audit`(가격패널 연속성=전종목 OK)와 최신 재무 기준일로
교차확인. 매각·철수·중단 확인 종목 없음. **REVIEW는 지수에서 제거하지 않았다**(동결 지수 불변).

**한계**: 92개 CORE의 evidence_source는 프로젝트 분류(candidate_csv)+테마 taxonomy+가격패널
연속성이며, 8개 REVIEW만 개별 공식공시로 신규 검증했다. 100개 전수의 최신 사업보고서
개별 대조는 범위상 수행하지 않았다(→ 아래 상태표 참고).

---

## 3. 기업행위 및 상장 상태 점검표 (출력물 #4)

파일: `data/integrity/corporate_actions.csv`
(컬럼: listing_status, corporate_action_type, announcement_date, effective_date,
successor_ticker, action_source, action_status + PIT 진단 컬럼)

- **listing_status**: 전 종목 LISTED(현재 상장, 생존편향).
- **확인된 기업행위 25건**(가격패널 최초거래일 + 공식 공시 교차):
  - 티커·회사명 변경(동일법인, 이력승계): **ONTO**(NANO/RTEC→ONTO, 2019-10-25),
    **COHR**(IIVI→COHR, 2022-07-01).
  - 분할 신규상장: **GEV**(2024-04-02), **CEG**(2022-02-01), CARR, KEYS, LITE, NVT, HPE.
  - IPO: FN·NXPI·UI·MTSI·AAOI·ANET·ATKR·VRT·DDOG·GFS·CRDO·VNET(최초거래일=근거).
  - 회생·재상장: VST(EFH/TXU Ch.11→Vistra), ARM(2016 비상장화→2023 재상장).
  - 존속 인수/분할: IBM(Kyndryl 분할), AMT(CoreSite 인수).

### PIT 정합성
- **GEV·CEG 등 분할 신설법인 → 지수 미편입**(과거 리밸런싱 미반영 = **PIT 준수**).
- **ONTO**: 편입 32스냅샷 중 15개가 티커변경 이전 시점 → 동일 CIK 재무로 **이력 승계**.
  백테스트는 신티커(ONTO) 가격이 없는 진입일에 해당 종목을 제외·재정규화 → **가격 look-ahead 없음**.
  (기업행위 라벨의 소급은 있으나 수익률에는 영향 없음. 이 티커연속 아티팩트는 생존편향의 일부로 명시.)
- **COHR**: 31스냅샷 전부 동일법인(CIK 0000820318) 승계, 가격은 전신(IIVI) 이력을 stitch.

**한계**: 공식 corporate-action 피드 부재로 미래 pending 이벤트 전수 자동수집 불가.
확인된 항목만 기록.

---

## 4. 예외 편입·편출 규칙 문서 (출력물 #5)

전체 규칙: `08_Data_Integrity/docs/EXCEPTION_REBALANCE_RULES.md`.
구현: `07_exceptional_rebalance.py`의 `apply_special_removals()`(pro-rata 재배분,
self-test PASS: 합=1 유지·잔여비율 보존·신규편입 없음).

- 특별편출 reason_code 7종(DELIST/GO_PRIVATE/BANKRUPTCY/MERGER_DISSOLVED/
  LONG_SUSPENSION/CORE_BIZ_EXIT/ACCOUNTING_INTEGRITY).
- **교차확인 결과 공식 확인된 특별편출 이벤트 0건** → 실제 지수 비중 불변.
- 실제 리밸런싱 원장(`rebalance_ledger.csv`, 2,405행): NEW_ADD 420 / MAINTAIN 1,595 /
  DROP 390, 전부 `NORMAL_REBALANCE`.

---

## 5. 거래정지 점검표 (출력물 #6)

파일: `data/integrity/suspension_audit.csv`, `suspension_events.csv`
거래소 달력은 **QQQ 실제 거래일**(2009-06-01~2026-07-21, 4,311 거래일)을 정본으로 사용 →
휴장일은 구조적으로 배제. 가격결측을 5범주로 구분:
휴장(구조배제)/상장전(pre-listing)/중도종료(delist·data-end)/단기결측(<20거래일)/
**장기결측 = suspected_suspension(≥20 연속 거래일)**.

- **결과(87 종목 전부 status=OK)**: 장기 내부결측 0, 중도종료 0, 상장전 결측만 존재.
  → **suspected_suspension 0건, 자동 편출 0건.** 현재 티커 패널의 생존편향을 재확인.
- **한계**: 개별종목 **거래량**과 공식 halt 고시가 패널에 없어, 장기 내부결측이 실제
  거래정지인지 데이터 공급오류인지 자동 확정 불가 → 발견 시 `suspected_suspension`로만
  표기(자동 편출 금지). 20거래일 임계는 프로젝트 규정값이며 일별 종가로는 수시간~수일
  단기 halt는 탐지 불가.

---

## 6. 수정 전후 비교 (출력물 #7)

**모든 보완은 부가 메타데이터이며, 지수 구성 로직·값은 재계산하지 않았다.**

| 대상 | 전 | 후 | 근거 |
|---|---|---|---|
| 편입 종목 수(현재 Top30) | 30 | 30 (불변) | index_weights_latest UNCHANGED |
| 비중 합 | 1.000000 | 1.000000 (불변) | 동일 파일 |
| 4팩터 값(op_margin/roa/debt_ratio) | — | 불변 | 행내 혼재 0건, 재계산 없음 |
| revenue_growth | — | 값 불변 + CLS FY2024 1행에 교차기준 플래그(지수 미사용) | factors_enriched |
| 지수 CAGR | 26.85% | 26.85% (불변) | performance_summary UNCHANGED |
| QQQ CAGR / Sharpe / MDD | 19.51% / 1.03 / -38.95% | 동일 | performance_summary UNCHANGED |
| theme_eligible | 100 True | 92 True + 8 REVIEW(제거 안 함) | ai_infra_continuity |
| 특별편출 이벤트 | 0 | 0 | special_removal_events(0행) |

**왜 결과가 안 바뀌었는가(수치·파일 근거)**:
1. 회계기준 혼재가 **행 단위 0건**이라 비율형 팩터 값이 바뀔 여지가 없음(§1-A).
2. 유일한 시계열 전환(CLS FY2024)은 **현재 지수 미편입**이라 비중/수익률에 무영향(§1-C).
3. 거래정지·특별편출·상장폐지 이벤트가 **실측 0건**이라 편출·재배분이 발동하지 않음(§4,§5).
4. REVIEW 8종목은 **분리만 하고 제거하지 않았으므로**(요구사항) 동결 지수가 유지됨.

---

## 7. 해결하지 못한 항목과 그 이유 (출력물 #8)

| 항목 | 미해결 내용 | 이유 |
|---|---|---|
| Item 2 | 92개 CORE 기업의 개별 최신 사업보고서 전수 대조 | 100종목 공식공시 전수 검증은 범위 초과. 테마 taxonomy+가격연속성으로 대체, 경계 8종만 신규 공식검증 |
| Item 3 | 미래 pending 기업행위 전수 수집 | 공식 corporate-action 데이터 피드 부재 |
| Item 5 | 거래정지 vs 데이터오류 자동 구분, 단기 halt 탐지 | 개별 거래량·공식 halt 고시·intraday 데이터 부재 |
| 전반 | 과거 폐지·변경 종목의 원천 편입(생존편향 제거) | 유니버스가 "현재" SEC 티커 기준 — 과거 소멸종목 원천 미포함(기존 파이프라인 구조적 한계) |

---

## 8. 재현 가능한 실행 명령어 (출력물 #9)

프로젝트 루트에서(가상환경 `.venv`), **순서대로**:
```bash
.venv/Scripts/python.exe 08_Data_Integrity/code/01_accounting_standard_audit.py
.venv/Scripts/python.exe 08_Data_Integrity/code/02_accounting_standard_enrich.py
.venv/Scripts/python.exe 08_Data_Integrity/code/03_factors_enriched.py
.venv/Scripts/python.exe 08_Data_Integrity/code/05_suspension_audit.py
.venv/Scripts/python.exe 08_Data_Integrity/code/04_ai_infra_continuity.py   # suspension_audit 선행 필요
.venv/Scripts/python.exe 08_Data_Integrity/code/06_corporate_actions.py     # suspension_audit 선행 필요
.venv/Scripts/python.exe 08_Data_Integrity/code/07_exceptional_rebalance.py  # 앞 산출 선행 필요
```
의존: 01→02→03(Item1), 05→(04, 06)→07. 기존 파이프라인(01~05단계) **재실행 불필요**
(원본 산출물 미변경). 한글 콘솔 깨짐 방지: `PYTHONIOENCODING=utf-8`(CSV는 utf-8-sig).

---

## 9. 요구사항 상태 분류 (출력물 #10)

| # | 요구사항 | 상태 | 근거 |
|---|---|---|---|
| 1 | IFRS/US-GAAP 혼재 점검·필드 추가 | **IMPLEMENTED** | 5필드 데이터 반영, 전환 플래그 구현, 감사 코드 |
| 1 | 비율형 4팩터 혼재 영향 | **VALIDATED** | 행내 혼재 0건 → 값 불변 확인 |
| 2 | AI 인프라 지속성(92 CORE) | **VALIDATED** | 테마 taxonomy+가격연속성 근거 유지 |
| 2 | 경계 8종 REVIEW 분리 | **IMPLEMENTED** | 공식공시 신규검증, REVIEW 플래그(제거 안 함) |
| 2 | 92종 개별 공시 전수검증 | **DOCUMENTED_ONLY** | 범위 초과(§7) |
| 3 | 기업행위 7필드·PIT 점검 | **IMPLEMENTED** | 25건 확인, PIT 정합성 진단 |
| 3 | 미래 pending 전수수집 | **UNRESOLVED** | 공식 피드 부재(§7) |
| 4 | pro-rata 특별편출 로직·reason_code | **IMPLEMENTED** | self-test PASS, 원장 생성 |
| 4 | 실제 특별편출 반영 | **DOCUMENTED_ONLY** | 확인 이벤트 0건 |
| 5 | 거래정지 5범주 판별 | **IMPLEMENTED** | 87종목 감사, QQQ 달력 |
| 5 | 정지 vs 데이터오류·단기halt | **DOCUMENTED_ONLY** | 거래량·halt고시 부재(§7) |
| 5 | 자동 편출 억제 | **VALIDATED** | suspected 0건, 편출 0 |
| — | 원본 파이프라인 재현 무결성 | **VALIDATED** | 원본 산출물 바이트 동일 |

**총평**: 데이터로 확정 가능한 항목(회계기준 provenance·거래정지 판별·기업행위·
재배분 로직)은 코드·데이터에 실제 반영(IMPLEMENTED)했고, 실측 이벤트가 없는 규칙과
외부 피드가 필요한 부분은 근거와 함께 문서화(DOCUMENTED_ONLY)했다. 결과가 바뀌지
않은 것은 "개선"이 아니라 **혼재·이벤트가 실측 0건**이기 때문이며, 그 근거를 수치·파일로
제시했다(§6).
