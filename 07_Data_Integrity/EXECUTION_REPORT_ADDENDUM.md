# EXECUTION_REPORT 애드덤 — 후속 검증 5건 (2026-07-27)

본 애드덤은 기존 `EXECUTION_REPORT.md`를 덮어쓰지 않고, 사용자 후속 지적 5건에 대한
추가 검증·정정·구현을 기록한다. 신규 코드/데이터는 `08_Data_Integrity/code/08~13`,
`data/integrity/`에만 추가했다. **원본 파이프라인 산출물(data/pit·scores·index·backtest,
final_universe_100)은 재확인 결과 여전히 바이트 동일(UNCHANGED)** — 하류 재실행은 전부
`data/integrity/rerun_*` 격리 폴더로만 나갔다.

---

## 후속1. 거래정지 검사 87 → 100종목으로 확장

### 왜 87이었나
`suspension_audit`는 백테스트 가격패널 `prices_close.csv`(87종목)만 검사했다. 이 패널은
**어느 분기 Top30에도 편입된 적 있는 종목들의 합집합**(=05_download_prices 대상)이라,
100 유니버스 중 **한 번도 Top30에 선정되지 않은 13종목**은 애초에 가격을 내려받지
않았다. **단순 누락이 아니라 범위 차이**이나, 지적대로 100종목 전체를 검사해야 하므로
13종목 가격을 별도 수집(`08_download_missing13.py`)해 재검사(`09_suspension_audit_100.py`)했다.

### 13종목 표 (`data/integrity/missing13_table.csv`)
| ticker | 제외 사유 | 가격데이터 | rows | 상장일 | 재검사 | 검사가능 | 기업행위 |
|---|---|---|---|---|---|---|---|
| CDW | Top30 미선정→패널 제외 | 신규 확보 | 3285 | 2013-06-27 | OK | ✔ | - |
| CEG | 〃 | 신규 확보 | 1129 | 2022-01-19 | OK | ✔ | 분할신규상장 |
| DELL | 〃 | 신규 확보 | 2494 | 2016-08-17 | OK | ✔ | - |
| GDS | 〃 | 신규 확보 | 2440 | 2016-11-02 | OK | ✔ | - |
| GEV | 〃 | 신규 확보 | 580 | 2024-03-27 | OK | ✔ | 분할신규상장 |
| HPE | 〃 | 신규 확보 | 2703 | 2015-10-19 | OK | ✔ | 분할신규상장 |
| JBL | 〃 | 신규 확보 | 4311 | 2009-06-01 | OK | ✔ | - |
| MOD | 〃 | 신규 확보 | 4311 | 2009-06-01 | OK | ✔ | - |
| NET | 〃 | 신규 확보 | 1721 | 2019-09-13 | OK | ✔ | - |
| NOK | 〃 | 신규 확보 | 4311 | 2009-06-01 | OK | ✔ | - |
| NTNX | 〃 | 신규 확보 | 2463 | 2016-09-30 | OK | ✔ | - |
| SNOW | 〃 | 신규 확보 | 1467 | 2020-09-16 | OK | ✔ | - |
| VIAV | 〃 | 신규 확보 | 4311 | 2009-06-01 | OK | ✔ | - |

### 100종목 재검사 결과 (`data/integrity/suspension_audit_100.csv`)
- 검사 가능 **100/100**, 가격 미확보 0.
- status 분포: **OK 100** (suspected_suspension 0, delisted_or_data_end 0).
- 상장일 편차(GEV 2024·CEG 2022·SNOW 2020·NET 2019)는 상장 이전 결측(pre-listing)으로
  정상 처리, 내부 장기결측 아님.

---

## 후속2. AI 지속성 "공식 공시 검증" 표현 모순 정정 — evidence_level 도입

지적이 타당하다. 기존 표현은 92개 CORE를 사실상 기존 분류만으로 True 처리하면서
"공식 공시 검증"으로 오인될 수 있었다. **실제 이번 점검에서 공식 자료를 직접 확인한
기업은 8개 REVIEW 중 5개뿐**이다. `10_evidence_level.py`로 기업별 근거 수준을 정직하게
구분했다(`ai_infra_continuity_review_v2.csv`).

| evidence_level | 기업 수 | 의미 |
|---|---|---|
| OFFICIAL_FILING_VERIFIED | 2 | SNOW·DDOG (이번에 SEC 10-K 사업개요 직접 확인) |
| OFFICIAL_WEBSITE_VERIFIED | 3 | NTNX·AMT·IRM (회사 IR/실적 세그먼트 확인) |
| KEYWORD_ONLY | 1 | CDW (제3자 개요만, 공식 미대조) |
| EXISTING_CLASSIFICATION_ONLY | 94 | 92 CORE + LII·WTS (candidate_csv+테마 taxonomy만) |

- **business_status 정정**: 일괄 "ACTIVE"(검증된 사실처럼 보임)를 폐기하고,
  '관측 신호'로 표기 — `LISTED_TRADING(~가격패널 마지막일)` + `ACTIVE_FILER(최근 공시일)`.
  매각/철수/중단은 개별 확인하지 않았으므로 단정하지 않는다.
- 즉 "전 종목 공식 공시 검증"은 **오표현이었고 정정**한다. 92 CORE는 개별 공식공시
  대조를 하지 않은 **EXISTING_CLASSIFICATION_ONLY**이다.

---

## 후속3. CLS 교차기준 성장률 — 플래그가 아니라 실제 차단 옵션 구현 + 지수영향 실측

### 기존 상태
기존 파이프라인은 CLS FY2024 revenue_growth를 **플래그만** 했고 팩터 입력에서 차단하지
않았다(값 그대로 사용). 지적대로 **원칙 차단 옵션**을 구현했다.

### 구현 (`11_factor_engine_blocked.py`)
규칙: 전기/당기 회계기준이 다르면 성장률을 **원칙적으로 결측(NaN)** 처리하되,
**동일 기준으로 재작성(restated)된 전기 비교치가 있으면 그 값으로 재계산**한다.
재작성치는 당기 공시에 담기므로 as-of를 **당기 filed**로 제약(PIT 정합).

### CLS 결정 로그 (`data/integrity/growth_blocking_decisions.csv`)
CLS는 FY2024 US-GAAP 10-K(2025-03-03 접수)에서 **FY2023 비교연도를 US-GAAP로 재작성**했다.
따라서 4개 성장률 모두 재작성치 존재 → **RECOMPUTED_RESTATED**(결측 아님):

| growth_factor | 원본값 | 재작성 전기값 | 재계산값 | 결정 |
|---|---|---|---|---|
| revenue_growth | 0.211657 | 7,961M(us-gaap) | **0.211657 (동일)** | RECOMPUTED_RESTATED |
| operating_income_growth | 0.563935 | 338.3M | 0.771505 | RECOMPUTED_RESTATED |
| net_income_growth | 0.749796 | 244.4M | 0.751227 | RECOMPUTED_RESTATED |
| asset_growth | 0.016552 | 5,890.5M | 0.016586 | RECOMPUTED_RESTATED |

**revenue_growth(지수가 쓰는 유일한 성장팩터)는 재작성 US-GAAP 매출이 IFRS 매출과
동일($7,961M)이라 재계산해도 0.211657로 불변.** 나머지 3개는 지수 미사용 팩터.
(만약 재작성치가 없었다면 규칙에 따라 NaN 차단된다 — self-test로 null 분기도 검증.)

### 지수 영향 실측 (`13_rerun_downstream_blocked.py`)
블록 팩터와 원본 팩터를 **동일 파라미터 체인**(PIT quarterly → theme4ir min3 →
scores → weights top30/cap0.10)으로 격리 재구성해 최종 비중을 diff:

| 비교 | 최대 비중차 | 편입멤버십 변화 |
|---|---|---|
| 원본재구성 vs 커밋 지수(결정성) | **0.000e+00** | 0건 |
| **블록 vs 원본(차단 순영향)** | **0.000e+00** | **0건** |

- **CLS 편입 전후 동일**: 양쪽 모두 2026-03-31 스냅숏 1회만(비중 2.64%).
- 이유: CLS의 지수 편입 시점(2026-03-31)은 FY2025÷FY2024(둘 다 US-GAAP) 성장률을 쓰고,
  교차기준이 걸리는 2025-03-31·2025-06-30 분기의 revenue_growth(=FY2024 vintage)도
  재작성 재계산 결과가 **동일**해 스코어가 바뀌지 않는다.
- 결론: 차단 옵션을 켜도 **현재 지수는 수치적으로 완전 불변**(0.0). 옵션은 향후 재작성치가
  없는 전환 사례를 위해 코드로 상시 제공된다.

---

## 후속4. REVIEW 8종목 개별 권고 (`data/integrity/review_recommendations.csv`)

**자동 편출 없음 — 권고만. 현재 지수 불변.** 세 축(직접성/지속성/관련매출 확인가능)으로 구분.

| ticker | 권고 | AI인프라 직접성 | 관련매출 비중 확인 | 근거 |
|---|---|---|---|---|
| SNOW | **제외 권고** | LOW | N/A(100% SaaS) | 데이터플랫폼 SW, 인프라 공급/운영 아님 |
| DDOG | **제외 권고** | LOW | N/A(100% SaaS) | Observability SW |
| CDW | **제외 권고** | LOW | 해당없음(재판매) | IT 리셀러/유통, 공급자 아님 |
| NTNX | 추가검토 | MEDIUM | SW구독 100% | HCI SW-정의 인프라, 경계 |
| AMT | 추가검토 | MEDIUM | **가능**: DC $1.05B(~10%) | 주력 통신타워, DC 세그먼트만 부분적격 |
| IRM | 추가검토 | MEDIUM | **가능**: DC ~13% | 주력 문서보관, DC 소수 |
| LII | 추가검토 | LOW | **불가**: DC냉각 매출 미공개 | 일반 HVAC, 관련매출 확인 전 보류 |
| WTS | 추가검토 | LOW | **불가**: DC 매출 미공개 | 수처리·열, 관련매출 확인 전 보류 |

요약: 제외 권고 3(SaaS·리셀러), 추가검토 5. AMT·IRM은 DC 매출 비중이 **공시로 확인
가능**해 세그먼트 기준 재분류 논의 가능. LII·WTS는 DC 관련 매출 자체가 확인 불가.

---

## 후속5. "생존편향" 표현 정정 — 제거가 아니라 존재 재확인

지적 반영. 표현을 다음과 같이 명확히 한다(EXECUTION_REPORT §5·§7 의 취지 강화):

- 소급 백테스트·모든 감사는 **"현재" 최종 유니버스 100종목(현재 SEC 티커)만** 대상으로 한다.
- **historical constituent(과거 시점 실제 편입종목)와 과거 상장폐지·피합병 소멸 종목은
  원천적으로 포함되지 않았다.** 따라서 **생존편향은 제거되지 않았다.**
- 후속1의 "suspected_suspension 0·delisted 0" 결과는 생존편향이 없다는 증거가 **아니라**,
  패널이 현재 상장 종목으로만 구성된 데 따른 **직접적 귀결**이다. (폐지된 종목은 애초에
  패널에 없으므로 폐지가 관측될 수 없다.)
- 기존 표현 "생존편향 재확인"은 '편향이 존재함을 재확인'의 뜻으로 정확하나, 오해 방지를
  위해 **"생존편향 존재(제거 아님)"** 로 통일한다.

### 검증 범위·한계 (정정본)
| 항목 | 범위 | 한계 |
|---|---|---|
| 거래정지 감사 | 현재 100종목 | 과거 폐지·피합병 종목 미포함 → 편향 존재 |
| 백테스트 | 현재 선정 티커(87) | 과거 시점 실제 구성 미복원 → 상방편향 가능 |
| 기업행위 | 현재 상장 100종목 | 소멸·폐지 종목 원천 부재 |
| 개선 방안(미구현) | — | point-in-time 유니버스(각 리밸런스 시점의 실제 상장·후보군) 재구축 필요. 현재 데이터로는 불가(DOCUMENTED_ONLY) |

---

## 후속 산출물 목록
- 코드: `08_download_missing13.py`, `09_suspension_audit_100.py`, `10_evidence_level.py`,
  `11_factor_engine_blocked.py`, `12_review_recommendations.py`, `13_rerun_downstream_blocked.py`
- 데이터: `prices_missing13.csv`(+coverage), `missing13_table.csv`,
  `suspension_audit_100.csv`(+events), `ai_infra_continuity_review_v2.csv`,
  `growth_blocking_decisions.csv`, `factors_blocked/`(100), `review_recommendations.csv`,
  `rerun_{orig,blocked}/`(격리 재구성).

## 잔여 한계
1. 92 CORE 개별 공식공시 전수 대조는 여전히 미수행(EXISTING_CLASSIFICATION_ONLY) — 범위상 보류.
2. **생존편향은 제거되지 않음** — point-in-time 유니버스 재구축이 근본 해법이나 현재 데이터
   부재로 DOCUMENTED_ONLY.
3. LII·WTS의 DC 관련 매출 비중은 공시상 분리 불가 → REVIEW 유지.
4. 차단 옵션은 CLS 외 전환 사례가 유니버스에 없어 null 분기는 self-test로만 검증(실데이터 0건).
