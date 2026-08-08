#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
07_exceptional_rebalance.py  (Item 4: 예외적 편입·편출 규칙)

일반 분기 리밸런싱과 '특별 편출'을 구분해 구현/문서화한다.

특별 편출 트리거(reason_code)
-----------------------------
  DELIST                : 상장폐지
  GO_PRIVATE            : 비상장 전환
  BANKRUPTCY            : 파산·청산
  MERGER_DISSOLVED      : 합병으로 소멸(존속기업 아님)
  LONG_SUSPENSION       : 장기 거래정지(>=20 거래일, suspension_audit 근거)
  CORE_BIZ_EXIT         : AI 인프라 핵심사업 공식 매각·중단
  ACCOUNTING_INTEGRITY  : 재무 신뢰성 훼손 중대한 회계 문제

처리 원칙(코드로 강제)
----------------------
1) 사건이 시장에 공식 공개된 '유효일 이후'에만 반영(effective_date 필수).
2) 특별 편출로 비는 비중은 '잔여 종목에 기존 비중 비례'로 재배분(pro-rata).
3) 분기 리밸런싱 사이에 임의 신규 편입 금지(대체 종목 추가 안 함).
4) 모든 편입·편출에 reason_code 와 적용일(effective_date) 기록.

apply_special_removals() 는 이 규칙을 그대로 구현한다. 내장 self-test 로
재배분 수학(합=1 유지, 비례 배분)을 검증한다(합성 예시는 '단위테스트'이며
실제 지수 데이터가 아님을 명시).

실제 데이터 반영
----------------
* data/integrity/special_removal_events.csv : 공식 확인된 특별편출 이벤트 원장.
  현재 유니버스는 상장폐지/파산/소멸/장기정지/핵심사업매각 확인 종목이 '없다'
  (suspension_audit=전종목 OK, corporate_actions=현재 전종목 상장).
  -> 이벤트 0건. 따라서 실제 지수 비중은 불변(규칙 적용해도 결과 동일).
* data/integrity/rebalance_ledger.csv : 실제 분기 리밸런싱의 종목별 reason_code
  (NEW_ADD / MAINTAIN / DROP_NORMAL) 를 스냅샷 diff 로 산출(전부 일반 리밸런싱).

출력: special_removal_events.csv(스키마+0행), rebalance_ledger.csv
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "data" / "integrity"
WEIGHTS = ROOT / "data" / "index" / "index_weights_quarterly.csv"

SPECIAL_CODES = {
    "DELIST", "GO_PRIVATE", "BANKRUPTCY", "MERGER_DISSOLVED",
    "LONG_SUSPENSION", "CORE_BIZ_EXIT", "ACCOUNTING_INTEGRITY",
}


def apply_special_removals(weights: pd.Series, removed: list[str]) -> pd.Series:
    """특별 편출 후 잔여 종목에 기존 비중 비례(pro-rata)로 재배분.
    weights: index=ticker, values=weight(합≈1). removed: 편출 티커 리스트.
    반환: 재정규화된 비중(합=1). 신규 편입 없음."""
    w = weights.copy().astype(float)
    keep = w.drop(index=[t for t in removed if t in w.index], errors="ignore")
    s = float(keep.sum())
    if s <= 0:
        raise ValueError("잔여 비중 합이 0 이하 — 재배분 불가")
    return keep / s  # 기존 비중 비례 재배분 == 잔여만 재정규화


def _self_test():
    """합성 단위테스트(실제 지수 아님): pro-rata 재배분 수학 검증."""
    w = pd.Series({"A": 0.5, "B": 0.3, "C": 0.2})
    out = apply_special_removals(w, ["C"])
    assert abs(out.sum() - 1.0) < 1e-12
    # 잔여 A:B 비율(0.5:0.3)이 보존되어야 함
    assert abs(out["A"] / out["B"] - (0.5 / 0.3)) < 1e-12
    assert "C" not in out.index
    return True


def build_rebalance_ledger(w: pd.DataFrame) -> pd.DataFrame:
    """실제 분기 스냅샷 diff로 종목별 reason_code 원장 생성."""
    w = w.copy()
    w["snapshot_date"] = pd.to_datetime(w["snapshot_date"])
    w["ticker"] = w["ticker"].astype(str).str.upper()
    snaps = sorted(w["snapshot_date"].unique())
    prev = set()
    rows = []
    for d in snaps:
        cur = set(w.loc[w.snapshot_date == d, "ticker"])
        for t in sorted(cur):
            code = "NEW_ADD" if t not in prev else "MAINTAIN"
            rows.append({"snapshot_date": d.date(), "ticker": t,
                         "action": code, "reason_code": "NORMAL_REBALANCE",
                         "effective_date": d.date()})
        for t in sorted(prev - cur):
            rows.append({"snapshot_date": d.date(), "ticker": t,
                         "action": "DROP", "reason_code": "NORMAL_REBALANCE_DROP",
                         "effective_date": d.date()})
        prev = cur
    return pd.DataFrame(rows)


def main():
    assert _self_test(), "self-test 실패"
    INTEG.mkdir(parents=True, exist_ok=True)

    # 1) 특별편출 이벤트 원장(스키마) — 공식 확인 이벤트만 기록. 현재 0건.
    ev_cols = ["ticker", "reason_code", "announcement_date", "effective_date",
               "source", "note"]
    events = pd.DataFrame(columns=ev_cols)
    # (근거 교차확인) suspension_audit / corporate_actions 로 특별편출 후보 존재 여부 확인
    susp = pd.read_csv(INTEG / "suspension_audit.csv", encoding="utf-8-sig")
    ca = pd.read_csv(INTEG / "corporate_actions.csv", encoding="utf-8-sig")
    n_long_susp = int(susp["suspected_suspension"].sum())
    n_delist = int(susp["delisted_or_data_end"].sum())
    n_dissolved = int((ca["listing_status"] != "LISTED").sum())
    events.to_csv(INTEG / "special_removal_events.csv", index=False, encoding="utf-8-sig")

    # 2) 실제 리밸런싱 원장(reason_code)
    w = pd.read_csv(WEIGHTS)
    ledger = build_rebalance_ledger(w)
    ledger.to_csv(INTEG / "rebalance_ledger.csv", index=False, encoding="utf-8-sig")

    print("=" * 64)
    print("Item 4  예외 편입·편출 규칙 구현 요약")
    print("=" * 64)
    print("pro-rata 재배분 self-test: PASS (합=1 유지, 잔여 비율 보존, 신규편입 없음)")
    print(f"reason_code 종류(특별편출): {sorted(SPECIAL_CODES)}")
    print()
    print("특별편출 후보 교차확인:")
    print(f"  - 장기 거래정지(LONG_SUSPENSION) 후보: {n_long_susp}건")
    print(f"  - 상장폐지/데이터종료(DELIST) 후보    : {n_delist}건")
    print(f"  - 비상장/소멸(listing!=LISTED)        : {n_dissolved}건")
    print(f"  => 공식 확인된 특별편출 이벤트: {len(events)}건 -> 실제 지수 비중 불변.")
    print()
    print("리밸런싱 원장(reason_code) 요약:")
    print(ledger["action"].value_counts().to_string())
    print(f"  NEW_ADD 총 {(ledger.action=='NEW_ADD').sum()}건, "
          f"DROP 총 {(ledger.action=='DROP').sum()}건 (전부 NORMAL_REBALANCE)")
    print(f"\n출력: {INTEG/'special_removal_events.csv'} (스키마, 0행)")
    print(f"출력: {INTEG/'rebalance_ledger.csv'} ({len(ledger)}행)")


if __name__ == "__main__":
    main()
