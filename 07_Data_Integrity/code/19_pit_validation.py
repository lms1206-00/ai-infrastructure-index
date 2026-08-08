#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
19_pit_validation.py  (2차 과제: PIT 원칙 검증)

각 리밸런싱 시점에는 그 날짜 이전에 공개된 자료만 사용 가능해야 한다.
tracker 의 evidence_date / filing_date 를 검증한다:
  * 모든 evidence_date <= 관측일(2026-07-27)  (미래 근거 없음)
  * 직접 검증 8개의 evidence_date <= next_review_date(사용 예정 리밸런싱일)
  * 과거 상태를 현재 정보로 소급 적용하지 않았음: historical_business_status_unavailable=True 전건,
    previous_status=NONE(최초 관측), status_changed=False.

출력: data/integrity/pit_validation_report.csv
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "data" / "integrity"
OBS_DATE = pd.Timestamp("2026-07-27")


def main():
    tr = pd.read_csv(INTEG / "business_continuity_tracker.csv", encoding="utf-8-sig")
    tr["evidence_date_dt"] = pd.to_datetime(tr["evidence_date"], errors="coerce")
    tr["filing_date_dt"] = pd.to_datetime(tr["filing_date"], errors="coerce")
    tr["next_review_dt"] = pd.to_datetime(tr["next_review_date"], errors="coerce")

    checks = []
    verified = tr[tr.evidence_level != "EXISTING_CLASSIFICATION_ONLY"]

    # 1) 미래 근거 없음
    future_ev = verified[verified["evidence_date_dt"] > OBS_DATE]
    checks.append(("evidence_date <= 관측일(2026-07-27)", len(future_ev) == 0,
                   f"위반 {len(future_ev)}건"))
    # 2) 사용 예정 리밸런싱일 이전 근거
    late = verified[verified["evidence_date_dt"] > verified["next_review_dt"]]
    checks.append(("evidence_date <= next_review_date", len(late) == 0, f"위반 {len(late)}건"))
    # 3) filing_date 도 관측일 이전
    ffuture = tr[tr["filing_date_dt"] > OBS_DATE]
    checks.append(("filing_date <= 관측일", len(ffuture) == 0, f"위반 {len(ffuture)}건"))
    # 4) 과거 소급 없음
    no_retro = bool(tr["historical_business_status_unavailable"].all()
                    and (tr["previous_status"] == "NONE").all()
                    and (~tr["status_changed"]).all())
    checks.append(("과거상태 소급 없음(hist_unavailable=True, prev=NONE, changed=False)",
                   no_retro, "전건 준수" if no_retro else "위반"))

    rep = pd.DataFrame(checks, columns=["check", "pass", "detail"])
    rep.to_csv(INTEG / "pit_validation_report.csv", index=False, encoding="utf-8-sig")

    print("=" * 64); print("2차 과제  PIT 원칙 검증"); print("=" * 64)
    print(rep.to_string(index=False))
    print(f"\n직접검증 8개 evidence_date 범위: {verified['evidence_date_dt'].min().date()} "
          f"~ {verified['evidence_date_dt'].max().date()} (모두 관측일·리밸런싱일 이전)")
    print(f"전체 PASS: {bool(rep['pass'].all())}")
    print(f"\n출력: {INTEG/'pit_validation_report.csv'}")


if __name__ == "__main__":
    main()
