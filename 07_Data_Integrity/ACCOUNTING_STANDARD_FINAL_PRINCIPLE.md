# 회계기준 전환 최종 원칙 — 구현·실측 (2026-07-27)

사용자 확정 원칙을 팩터 입력 단계에 최종 반영했다. 기존 파일은 덮어쓰지 않고
`08_Data_Integrity/code/14~16`, `data/integrity/`에만 추가했다. 원본 파이프라인 산출물
(data/pit·scores·index, final_universe_100)은 재확인 결과 **여전히 미변경(mtime 2026-07-22)**.
모든 재실행은 `data/integrity/rerun_*` 격리 출력으로만 나갔다.

## 1. 적용 원칙 (코드로 강제 — `14_factor_engine_blocked_v2.py`)

| # | 원칙 | 구현 |
|---|---|---|
| 1 | 전기·당기 accounting_standard 상이 → 성장률 NaN | 전환 경계에서 성장률 기본 NaN |
| 2 | 단, 공식 재작성(동일기준)만 그 값끼리 재계산 | 전기값을 **당기 taxonomy 로만** 탐색(재작성 fact) |
| 3 | **숫자 동일은 비교가능 근거 아님** | 판정은 오직 fact 의 원본 taxonomy 일치. 값 비교 미사용. 로그에 재작성 fact 의 `tax=` 명기 |
| 4 | 재작성 근거 없거나 불확실 → 무조건 NaN | 당기 taxonomy fact 부재 시 NaN(else 분기) |
| 5 | 동일연도/기준일 비율형도 분자·분모 taxonomy 상이 → NaN | operating_margin·debt_ratio·roa 행내 num/denom taxonomy 검사. **ROA 평균자산**의 전기자산이 기준 상이면 재작성 자산만 평균, 없으면 NaN |
| 6 | 결측 후 최소 3/4 팩터 조건 적용 | 하류 `--min-required-factors 3` 그대로 |
| 7 | 유니버스 삭제 금지, 분기 평가가능성만 | 팩터 NaN→해당 분기 required_factor_count 감소→3/4 미달시 그 분기만 제외. 100 유니버스 유지 |

**비교가능성 판정 = taxonomy 일치(공식 재작성 존재)**. 예: CLS revenue 는 IFRS·US-GAAP 값이
우연히 같지만($7,961M), 그 이유로 비교하지 않는다. CLS 가 FY2024 10-K 에서 FY2023 을
**us-gaap 로 공식 재작성한 fact 가 존재**하기 때문에만 재계산한다(로그 `tax=us-gaap`).

## 2. CLS 결정 로그 (`growth_blocking_decisions_v2.csv`)

CLS 는 FY2024 US-GAAP 10-K(2025-03-03 접수)에서 FY2023 전 항목을 US-GAAP 로 재작성했다.
따라서 전환 경계(2024-12-31)의 5개 팩터 전부 **RECOMPUTED_RESTATED**(공식 재작성치 존재):

| factor | 재작성 전기값(us-gaap) | 결정 |
|---|---|---|
| revenue_growth | 7,961M | RECOMPUTED_RESTATED (0.211657, 값 자체는 동일하나 판정은 taxonomy 근거) |
| operating_income_growth | 338.3M | RECOMPUTED_RESTATED |
| net_income_growth | 244.4M | RECOMPUTED_RESTATED |
| asset_growth | 5,890.5M | RECOMPUTED_RESTATED |
| roa(평균자산) | 5,890.5M | RECOMPUTED_RESTATED |

- **비율형 행내(operating_margin/debt_ratio/roa num·denom) taxonomy 불일치 = 100종목 0건**
  → 이 규칙으로 NaN 되는 행 없음(엔진이 한 행에서 기준을 섞지 않음). 규칙은 방어적으로 상시 적용.
- CLS 외 전환 기업 없음 → 다른 기업 팩터 불변.

## 3. 지수 영향 실측 (격리 재실행)

동일 파라미터 체인(PIT quarterly → theme4ir **min 3/4** → scores → weights top30/cap0.10)으로
비교. 원본 팩터 재구성본이 커밋 지수와 0.0 일치(결정성 확인)한 뒤:

| 시나리오 | 최대 비중차 | 편입멤버십 변화 | CLS 편입 | CLS 분기자격 |
|---|---|---|---|---|
| **v2 (최종원칙: 재작성 재계산)** | **0.000e+00** | **0건** | 2026-03-31 1회(불변) | 6분기 모두 4팩터·eligible |
| worst-case strict (재작성 무시·순수 NaN)\* | 1.763e-04 (0.018%) | **0건** | 2026-03-31 1회(불변) | (참고: 편입종목 불변) |

\* strict 는 '재작성치가 없었다면'을 가정한 **상한 참고 시나리오**로, CLS 가 실제로 공식
재작성을 했으므로 채택 대상이 아니다. 이 극단 가정에서도 **편입 종목은 하나도 바뀌지 않고**
비중만 0.018% 미만 이동한다.

**결론**: 최종 원칙을 팩터 입력에 강제해도 **현재 지수는 수치적으로 완전 불변**(v2 = 0.0).
CLS 는 공식 재작성 덕분에 동일기준 재계산이 가능해 4팩터를 유지하며, 유니버스에서 삭제되지
않고 매 분기 자격만 판정된다. 원칙은 향후 '재작성 없는 전환' 사례를 위해 코드로 상시 작동한다.

## 4. 산출물
- 코드: `14_factor_engine_blocked_v2.py`, `15_rerun_downstream_v2.py`, `16_strict_scenario.py`
- 데이터: `factors_blocked_v2/`(100), `growth_blocking_decisions_v2.csv`,
  `factors_strict/`(상한 시나리오), `rerun_{v2,strict}/`(격리 재구성)

## 5. 잔여 한계
- 비율형 행내 taxonomy 불일치·재작성 없는 전환은 현재 유니버스에 실데이터 0건 →
  해당 NaN 분기는 규칙·self-test 로만 검증(실측 미발생).
- 값 자체의 동일성(예: CLS revenue IFRS=US-GAAP)은 **판정 근거로 쓰지 않았음**을 명시.
