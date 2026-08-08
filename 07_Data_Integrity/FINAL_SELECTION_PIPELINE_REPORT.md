# 최종 편입종목 선정 파이프라인 — 테마 적격성 게이트 (2026-07-27)

최종 원칙: **"100개 기업은 후보 유니버스로 유지한다. 각 분기 리밸런싱 시점에서 AI 인프라
사업 지속성과 직접성을 먼저 심사하고, 테마 적격 기업 중 데이터·팩터 조건을 충족한 기업만
점수화하여 상위 30개를 편입한다."**

- **SNOW·DDOG·CDW를 원본 100 명단에서 삭제하거나 대체하지 않았다.** 100개는 후보로 유지.
- 각 분기 리밸런싱에 **테마 적격성 게이트**를 추가(직접성/지속성 → theme_eligible).
- 기존 코드·산출물 미변경. 신규 코드 `20~23`, 데이터 `data/integrity/`, 격리 출력 `scenario_*/`.
- 원본 파이프라인 재구성(시나리오 A)이 **커밋 지수와 0.0 일치**(결정성 확인) 후 비교.

## 선정 순서 (구현)
```
100 후보 유니버스
 → 테마 적격성 심사        (21_theme_eligibility.py: theme_eligible)
 → 데이터·필수팩터 심사     (기존 theme4ir: PIT유효·age≤365·품질≥60·warning無·3/4팩터
                            + 회계기준 혼합금지 v2[code14])
 → Factor Score            (03_Methodology, 테마부적격은 score_eligible=False→순위 제외)
 → Top30                   (04_Index, 30개 미만이면 실제 수만 편입, 억지 충원 없음)
 → 점수비례 가중 + 10% cap
final_eligible = theme_eligible AND data_eligible AND required_factor_count≥3
```

## 1. 테마 적격성 심사 (`theme_eligibility_{pit,retro}.csv`)
필드: ticker, rebalance_date, business_status, theme_directness, theme_eligible,
theme_exclusion_reason, evidence_date, evidence_source, evidence_level.

판정 규칙(코드 강제):
- DISCONTINUED → False(BUSINESS_DISCONTINUED) — 현재 해당 0.
- 직접성 LOW & **공식 근거 확인** → False(THEME_DIRECTNESS_LOW): **SNOW·DDOG·CDW**.
- REVIEW/불확실/NOT_REVIEWED → 자동 제외 금지, 기존 자격 유지.
- AI 키워드 감소만으로 False 금지.
- **PIT**: `evidence_date > rebalance_date` 이면 그 시점엔 미적용(기존 자격 유지).

### 소급 vs PIT (별도 시나리오)
directness_evidence_date = 이번에 검토한 **FY2025 10-K 접수일**(가장 보수적 근거일):
SNOW 2026-03-20, DDOG 2026-02-18, CDW 2026-02-20.
- **PIT(최종)**: 근거 공개일 이후 리밸런싱부터만 False → **2026-03-31·2026-06-30 (6행)**.
- **소급(참고용, 최종 결과 아님)**: 전 분기 False → 110행.

## 2. 데이터·팩터 심사
테마 적격 기업에만 기존 조건 적용(원 파이프라인 theme4ir가 PIT유효·age≤365·품질≥60·
warning無·3/4팩터 수행) + **IFRS/US-GAAP 혼합 금지**(code14 v2: 전기·당기 기준 상이시
결측, 공식 동일기준 재작성 수치만 예외). 테마 부적격은 점수화하되 **순위 제외**(score_eligible=False).

## 3. 시나리오 비교 결과 (`scenario_summary.csv`)

| 시나리오 | 테마제외행 | CAGR | Vol | Sharpe | MDD | QQQ CAGR | SOXX corr / TE / beta |
|---|---|---|---|---|---|---|---|
| **A (기존)** | 0 | 26.85% | 26.73% | 1.0262 | −38.95% | 19.51% | 0.944 / 10.33% / 0.821 |
| **B_pit (최종)** | 6 | 26.85% | 26.71% | 1.0265 | −38.95% | 19.51% | 0.944 / 10.33% / 0.821 |
| B_retro (참고) | 110 | 26.75% | 26.74% | 1.0229 | −39.46% | 19.51% | 0.944 / 10.31% / 0.822 |

- **결정성**: 시나리오 A weights = 커밋 지수 **0.0 일치**.
- **B_pit(최종)**: 성과는 A와 사실상 동일(CAGR 26.85%, Sharpe 1.0262→1.0265 미세 개선).
- QQQ 대비 초과 CAGR +7.3%p, SOXX와 corr 0.94(동행)·TE 10.3%·beta 0.82.

### 분기별 카운트 (`scenario_quarterly_counts.csv`)
테마 필터(PIT)는 **2026-03-31·2026-06-30 두 분기에서만** 각 3종목(SNOW·DDOG·CDW) 제외.
scored: 2026-03-31 A=100→B_pit=97, 2026-06-30 A=98→B_pit=95. 그 외 66개 분기는 동일.

## 4. Top30 멤버십 변화 — 무엇이·왜 바뀌었나

### B_pit vs A (`topn_diff_Bpit_vs_A.csv`) — 최종
| 스냅숏 | 편출 | 편입 |
|---|---|---|
| 2026-03-31 | **CLS**(30위 경계, 2.64%) | **KEYS** |

- **원인**: SNOW·DDOG(고성장 SaaS)를 점수 풀에서 제거 → revenue_growth 등 **횡단면 백분위가
  재정규화** → 30위 경계에서 CLS와 KEYS의 복합점수 순위가 역전. CLS는 직접 제외가 아니라
  풀 변경에 따른 경계 탈락(테마 적격 CORE 유지).
- **최신 리밸런싱(2026-06-30) Top30는 불변**(3종목 제외해도 경계 미변동).

### B_retro vs A (`topn_diff_Bretro_vs_A.csv`) — 참고용
18건/9개 분기. 대표: **2020-06-30 DDOG(유일한 Top30 이력) 편출 → FIX 편입**. 나머지는 풀
재정규화에 따른 경계 재배열(COHR/AVGO/MCHP/ETN/VRT 등). → 소급 적용은 과거 다수 분기를
바꾸므로 **참고용**이며 최종 결과로 사용하지 않음.

## 5. 편입·편출 원장 (`membership_ledger_Bpit.csv`)
필드: ticker, rebalance_date, previous_membership, current_membership, action,
reason_code, factor_score, rank, theme_eligible, data_eligible. (5,460행)
reason_code 분포: FACTOR_SCORE_TOP30 2,015 / FACTOR_SCORE_OUTSIDE_TOP30 3,399 /
DATA_OR_FACTOR_SCREEN 40 / **THEME_DIRECTNESS_LOW 6**(SNOW·DDOG·CDW @2026-Q1·Q2).

## 6. PIT 원칙
- 테마 필터는 `evidence_date ≤ rebalance_date` 에서만 적용(21_ 코드 강제).
- 현재 직접성 검토 결과를 과거 전체에 소급한 시나리오(B_retro)는 **별도·참고용**으로 분리,
  최종(B_pit)은 근거 공개일 이후에만 적용.
- 회계기준·팩터의 PIT는 기존 파이프라인 + code14(v2)로 보장.

## 7. 변경 원인 요약 (수치·근거)
| 변화 | 원인 필터 | 근거일 |
|---|---|---|
| 2026-03-31 CLS→KEYS (B_pit) | THEME_DIRECTNESS_LOW(SNOW·DDOG·CDW 풀 제거→백분위 재정규화) | FY2025 10-K 접수일(2026-02~03) |
| 2020-06-30 DDOG→FIX 외 17건 (B_retro) | 동일 필터의 **소급** 적용 | (참고용, 최종 아님) |
| B_retro CAGR 26.85%→26.75% | 과거 다수 분기 경계 재배열 누적 | (참고용) |

## 8. 상태 분류
| 항목 | 상태 |
|---|---|
| 테마 적격성 게이트(PIT/retro) | **IMPLEMENTED** |
| 선정 순서(테마→데이터→점수→Top30→가중) 재구성 | **IMPLEMENTED** |
| 시나리오 A 결정성(커밋 일치) | **VALIDATED**(0.0) |
| B_pit/B_retro 성과·추적·멤버십·원장 | **IMPLEMENTED** |
| SOXX 벤치마크 비교 | **IMPLEMENTED**(신규 다운로드) |
| 직접성 근거일 = FY2025 10-K 접수일 채택 | **DOCUMENTED_ONLY**(더 이른 10-K도 저직접성 근거이나 보수적으로 검토 문서일 채택) |
| 92 NOT_REVIEWED 기업의 개별 직접성 검증 | **UNRESOLVED**(미수행 → 기존 자격 유지) |

## 9. 재현 실행 명령어
```bash
.venv/Scripts/python.exe 08_Data_Integrity/code/20_setup_prices_soxx.py
.venv/Scripts/python.exe 08_Data_Integrity/code/21_theme_eligibility.py
.venv/Scripts/python.exe 08_Data_Integrity/code/22_run_scenarios.py
.venv/Scripts/python.exe 08_Data_Integrity/code/23_membership_ledger.py
```
선행: code 11·14(팩터 v2), 13·15(rerun_orig/rerun_v2 theme4ir). `PYTHONIOENCODING=utf-8`.

## 10. 변경 파일 목록
- 코드: `20_setup_prices_soxx.py`, `21_theme_eligibility.py`, `22_run_scenarios.py`, `23_membership_ledger.py`
- 데이터: `prices_close_100.csv`, `benchmark_soxx.csv`, `theme_eligibility_{pit,retro}.csv`,
  `scenario_summary.csv`, `scenario_quarterly_counts.csv`, `topn_diff_{Bpit,Bretro}_vs_A.csv`,
  `membership_ledger_Bpit.csv`, `scenario_{A,B_pit,B_retro}/`(weights·scores·backtest)
- 원본 파이프라인·산출물: **미변경**(mtime 2026-07-22, A재구성 0.0 일치로 검증)

## 11. 잔여 한계
1. 직접성 근거일을 FY2025 10-K로 보수 채택 → B_pit는 2026-Q1부터만 적용(과거 백테스트 거의 불변).
   더 이른 10-K를 근거일로 쓰면 적용 시점이 앞당겨짐(B_retro가 상한).
2. 92개 NOT_REVIEWED 기업의 직접성은 미검증 → 기존 자격 유지(자동 제외 안 함).
3. 자동 편출은 실행하지 않음 — 상태·후보·시나리오만 제시. 실제 편출은 별도 승인.
