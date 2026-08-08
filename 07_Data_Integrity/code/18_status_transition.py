#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
18_status_transition.py  (2차 과제: 상태 전이 함수 + 변경 이력 원장)

사업 지속성 상태(business_status)의 분기별 갱신을 위한 전이 규칙을 코드로 구현한다.

상태: ACTIVE / REDUCED / DISCONTINUED / UNCERTAIN / NOT_REVIEWED
갱신 신호(evidence_kind):
  ANNUAL_CONFIRM   : 최신 10-K/20-F 에서 핵심사업 유지 확인 -> ACTIVE
  KEYWORD_DECLINE  : AI 키워드 감소/소멸만 관측(공식 매각·중단 아님) -> REVIEW 전환(자동편출 금지)
  PARTIAL_DIVEST   : 일부 매각·축소·매출비중 감소 공식확인 -> REDUCED
  OFFICIAL_EXIT    : 매각·철수·중단 공식확인 -> DISCONTINUED
  NO_NEW_INFO      : 신규 공식정보 없음 -> 상태 유지

핵심 원칙(코드 강제):
  * KEYWORD_DECLINE 만으로 DISCONTINUED/편출 금지 -> REVIEW(=UNCERTAIN 로 보류) 로만.
  * DISCONTINUED 는 OFFICIAL_EXIT(공식 확인) 에서만.
  * PIT: 전이는 evidence_date <= rebalance_date 인 근거만 사용(미래 공시 소급 금지).
  * DISCONTINUED 라도 '실제 편출'은 이 함수가 하지 않는다 -> exclusion_candidate=True 로 표시만.

출력: data/integrity/status_change_ledger.csv (현재 스냅숏 = 최초 관측 baseline)
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "data" / "integrity"
VALID = {"ACTIVE", "REDUCED", "DISCONTINUED", "UNCERTAIN", "NOT_REVIEWED"}


def transition(prev_status: str, evidence_kind: str, evidence_date: str,
               rebalance_date: str) -> dict:
    """이전 상태 + 갱신 신호 -> 새 상태. PIT: 미래 근거는 무시.
    반환: {new_status, status_changed, change_reason, exclusion_candidate, pit_ok}."""
    # PIT 검증: 근거가 리밸런싱일 이후면 이번 시점엔 사용 불가
    pit_ok = True
    if evidence_date and rebalance_date and str(evidence_date) > str(rebalance_date):
        pit_ok = False
        return {"new_status": prev_status, "status_changed": False,
                "change_reason": f"PIT: evidence_date {evidence_date} > rebalance {rebalance_date} → 미적용",
                "exclusion_candidate": prev_status == "DISCONTINUED", "pit_ok": pit_ok}

    reason, excl = "", False
    if evidence_kind == "OFFICIAL_EXIT":
        new = "DISCONTINUED"; reason = "공식 매각/철수/중단 확인 → DISCONTINUED"; excl = True
    elif evidence_kind == "PARTIAL_DIVEST":
        new = "REDUCED"; reason = "일부 매각·축소·매출비중 감소 공식확인 → REDUCED"
    elif evidence_kind == "KEYWORD_DECLINE":
        # 키워드 감소만 → 자동편출 금지, REVIEW(보류=UNCERTAIN)
        new = "UNCERTAIN"; reason = "AI 키워드 감소/소멸만 관측(공식 매각·중단 아님) → REVIEW 보류"
    elif evidence_kind == "ANNUAL_CONFIRM":
        new = "ACTIVE"; reason = "최신 10-K/20-F 핵심사업 유지 확인 → ACTIVE"
    elif evidence_kind == "NO_NEW_INFO":
        new = prev_status; reason = "신규 공식정보 없음 → 상태 유지"
    else:
        new = prev_status; reason = f"알 수 없는 신호({evidence_kind}) → 상태 유지"

    if new not in VALID:
        new = prev_status
    excl = excl or (new == "DISCONTINUED")
    return {"new_status": new, "status_changed": (new != prev_status),
            "change_reason": reason, "exclusion_candidate": excl, "pit_ok": pit_ok}


def _self_test():
    # 키워드 감소만으로는 DISCONTINUED/편출 금지
    r = transition("ACTIVE", "KEYWORD_DECLINE", "2026-06-01", "2026-06-30")
    assert r["new_status"] == "UNCERTAIN" and not r["exclusion_candidate"], r
    # 공식 매각확인 → DISCONTINUED + 편출후보(자동편출 아님)
    r = transition("ACTIVE", "OFFICIAL_EXIT", "2026-06-10", "2026-06-30")
    assert r["new_status"] == "DISCONTINUED" and r["exclusion_candidate"], r
    # PIT: 미래 근거는 소급 금지
    r = transition("ACTIVE", "OFFICIAL_EXIT", "2026-07-15", "2026-06-30")
    assert r["new_status"] == "ACTIVE" and not r["pit_ok"], r
    # 일부 매각 → REDUCED
    r = transition("ACTIVE", "PARTIAL_DIVEST", "2026-05-01", "2026-06-30")
    assert r["new_status"] == "REDUCED", r
    return True


def main():
    assert _self_test(), "self-test 실패"
    tracker = pd.read_csv(INTEG / "business_continuity_tracker.csv", encoding="utf-8-sig")
    # 최초 관측 baseline 을 원장에 기록(previous=NONE, status_changed=False)
    ledger = pd.DataFrame({
        "observation_date": "2026-07-27",
        "rebalance_date": tracker["next_review_date"],
        "ticker": tracker["ticker"],
        "previous_status": "NONE",
        "new_status": tracker["business_status"],
        "status_changed": False,
        "evidence_kind": tracker["business_status"].map(
            lambda s: "ANNUAL_CONFIRM" if s == "ACTIVE" else "NOT_REVIEWED"),
        "evidence_date": tracker["evidence_date"],
        "evidence_level": tracker["evidence_level"],
        "change_reason": "최초 관측 baseline",
        "exclusion_candidate": tracker["recommendation"].eq("EXCLUDE_CANDIDATE"),
        "pit_ok": True,
    })
    ledger.to_csv(INTEG / "status_change_ledger.csv", index=False, encoding="utf-8-sig")

    print("=" * 64); print("2차 과제  상태 전이 함수 + 변경 이력 원장"); print("=" * 64)
    print("transition self-test: PASS")
    print("  - KEYWORD_DECLINE → UNCERTAIN(REVIEW), 편출 아님")
    print("  - OFFICIAL_EXIT → DISCONTINUED + exclusion_candidate(실제 편출은 별도 승인)")
    print("  - 미래 evidence_date → PIT 차단(소급 금지)")
    print(f"\n원장 baseline 행수: {len(ledger)}")
    print("exclusion_candidate=True:", int(ledger["exclusion_candidate"].sum()),
          "→", list(ledger[ledger.exclusion_candidate].ticker))
    print("status_changed=True:", int(ledger["status_changed"].sum()),
          "(최초 관측이라 0 — 다음 분기부터 이전상태 대비 변화 기록)")
    print(f"\n출력: {INTEG/'status_change_ledger.csv'}")


if __name__ == "__main__":
    main()
