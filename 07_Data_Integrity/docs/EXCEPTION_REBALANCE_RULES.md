# 예외적 편입·편출 규칙 (Item 4)

본 문서는 AI Infrastructure Custom Index의 **일반 분기 리밸런싱**과 **특별 편출**을
구분해 규정한다. 규칙은 `08_Data_Integrity/code/07_exceptional_rebalance.py`에
`apply_special_removals()` 로 구현되어 있고(내장 self-test 통과), 실제 이벤트 원장은
`data/integrity/special_removal_events.csv`, 리밸런싱 원장은
`data/integrity/rebalance_ledger.csv` 이다.

## 1. 일반 분기 리밸런싱 (NORMAL_REBALANCE)
- 분기말 스냅샷마다 팩터 스코어→랭킹→Top30, 단일종목 10% cap(waterfall)로 재구성.
- 종목별 상태를 diff로 기록: `NEW_ADD` / `MAINTAIN` / `DROP`(reason_code=`NORMAL_REBALANCE(_DROP)`).
- 실측: NEW_ADD 420건, MAINTAIN 1,595건, DROP 390건 (전부 일반 리밸런싱).

## 2. 특별 편출 (분기 사이에도 즉시 반영)
아래 사건이 **시장에 공식 공개된 유효일(effective_date) 이후**에만 반영한다.

| reason_code | 정의 |
|---|---|
| `DELIST` | 상장폐지 |
| `GO_PRIVATE` | 비상장 전환 |
| `BANKRUPTCY` | 파산·청산 |
| `MERGER_DISSOLVED` | 흡수합병으로 소멸(존속기업 아님) |
| `LONG_SUSPENSION` | 장기 거래정지(연속 20 거래일 이상) |
| `CORE_BIZ_EXIT` | AI 인프라 핵심사업 공식 매각·중단 |
| `ACCOUNTING_INTEGRITY` | 재무 신뢰성을 훼손하는 중대한 회계 문제 |

### 처리 원칙 (코드로 강제)
1. **공개 후 반영**: `effective_date` 필수. 사건 발표 이전 과거 시점에 소급 반영 금지(PIT).
2. **pro-rata 재배분**: 편출로 비는 비중을 **잔여 종목에 기존 비중 비례**로 재분배
   (`keep / keep.sum()`). 합=1 유지. self-test로 비율 보존·합 검증.
3. **임의 신규편입 금지**: 분기 리밸런싱 사이에는 대체 종목을 새로 넣지 않는다.
4. **전건 기록**: 모든 편입·편출에 `reason_code`와 적용일 기록.

## 3. 존속·신설기업 재심사 (Item 3 연계)
- **동일 법인 티커·회사명 변경**(예: NANO/RTEC→**ONTO** 2019-10-25, IIVI→**COHR** 2022-07-01):
  동일 CIK 기준으로 **편입 이력 승계**(자동 편출 아님).
- **흡수합병 소멸기업**: 편출(`MERGER_DISSOLVED`).
- **분할 신설기업**(예: **GEV** 2024-04-02, **CEG** 2022-02-01): 자동 편입하지 않고
  다음 분기 리밸런싱에서 **기존 편입 조건으로 재심사**.

## 4. 현재 유니버스 적용 결과
교차확인(`suspension_audit`, `corporate_actions`) 결과 **공식 확인된 특별편출 이벤트 0건**:
- 장기 거래정지 후보 0, 상장폐지/데이터종료 0, 비상장/소멸 0.
- 전 종목 현재 상장·거래중(생존편향 유니버스).
- 따라서 규칙을 적용해도 **실제 지수 비중은 불변**(이벤트 원장 0행).

## 5. 한계
- 공식 corporate-action 피드(거래소/벤더)가 없어 **미래 예정(pending) 이벤트의 전수 자동수집 불가**.
  → 확인된 항목만 기록하며, 신규 이벤트는 `special_removal_events.csv`에 근거와 함께 추가하면
  `apply_special_removals()`가 그대로 반영한다.
- 상태: **IMPLEMENTED**(재배분 로직·원장) + **DOCUMENTED_ONLY**(실제 특별편출 이벤트는 부재).
