#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
09_suspension_audit_100.py  (Item 5 확장: 100종목 전체 거래정지 재검사)

기존 05_suspension_audit 은 백테스트 가격패널(prices_close.csv, 87종목)만 검사했다.
유니버스 100종목 전체를 검사하기 위해 087 패널 + 08 단계에서 별도 수집한 13종목
(prices_missing13.csv)을 합쳐 동일 로직으로 재검사한다. 원본 05 산출물은 덮어쓰지 않고
suspension_audit_100.csv / suspension_events_100.csv 로 별도 저장한다.

범주/한계는 05 와 동일. 거래소 달력 = QQQ 거래일.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "data" / "integrity"
PRICES = ROOT / "data" / "prices" / "prices_close.csv"
MISSING = INTEG / "prices_missing13.csv"
QQQ = ROOT / "data" / "prices" / "benchmark_qqq.csv"
UNIVERSE = ROOT / "data" / "classification" / "final_universe_100.csv"
LONG_GAP_DAYS = 20


def runs_of_true(mask):
    out, n, i = [], len(mask), 0
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            out.append((i, j)); i = j + 1
        else:
            i += 1
    return out


def load_panel():
    px = pd.read_csv(PRICES, index_col=0)
    px.index = pd.to_datetime(px.index)
    add = pd.read_csv(MISSING, index_col=0)
    add.index = pd.to_datetime(add.index)
    px.columns = [str(c).upper() for c in px.columns]
    add.columns = [str(c).upper() for c in add.columns]
    both = [c for c in add.columns if c in px.columns]
    add = add.drop(columns=both)  # 중복 방지
    panel = px.join(add, how="outer").sort_index()
    return panel


def main():
    uni = pd.read_csv(UNIVERSE, encoding="utf-8-sig")
    uni_tickers = [str(t).upper() for t in uni["ticker"]]
    qqq = pd.read_csv(QQQ, index_col=0); qqq.index = pd.to_datetime(qqq.index)
    calendar = qqq.sort_index().index

    panel = load_panel().reindex(calendar)
    present = [t for t in uni_tickers if t in panel.columns]
    absent = [t for t in uni_tickers if t not in panel.columns]

    summary, events = [], []
    for tkr in uni_tickers:
        if tkr not in panel.columns:
            summary.append({"ticker": tkr, "status": "NO_PRICE_DATA",
                            "checkable": False, "first_valid": "", "last_valid": "",
                            "n_pre_listing": "", "n_interior_missing": "",
                            "n_post_end_missing": "", "n_long_gap_runs": "",
                            "max_gap_len": "", "suspected_suspension": "",
                            "delisted_or_data_end": "", "note": "가격 데이터 확보 실패"})
            continue
        s = panel[tkr]; valid = s.notna().values
        if not valid.any():
            summary.append({"ticker": tkr, "status": "NO_DATA", "checkable": True,
                            "first_valid": "", "last_valid": "", "n_pre_listing": len(calendar),
                            "n_interior_missing": 0, "n_post_end_missing": 0,
                            "n_long_gap_runs": 0, "max_gap_len": 0,
                            "suspected_suspension": False, "delisted_or_data_end": False,
                            "note": "패널 전체 결측"})
            continue
        i0 = int(np.argmax(valid)); i1 = len(valid) - 1 - int(np.argmax(valid[::-1]))
        pre = i0; post = (len(valid) - 1) - i1
        interior = ~valid.copy(); interior[:i0 + 1] = False; interior[i1:] = False
        rr = runs_of_true(interior)
        lens = [b - a + 1 for a, b in rr]
        longr = [1 for L in lens if L >= LONG_GAP_DAYS]
        maxg = max(lens) if lens else 0
        delisted = post > 0 and i1 < len(valid) - 1
        suspected = len(longr) > 0
        for a, b in rr:
            L = b - a + 1
            events.append({"ticker": tkr, "gap_start": calendar[a].date(),
                           "gap_end": calendar[b].date(), "trading_days_missing": L,
                           "classification": "suspected_suspension" if L >= LONG_GAP_DAYS else "short_gap"})
        summary.append({"ticker": tkr,
                        "status": "OK" if not (suspected or delisted) else
                                  ("DELISTED_OR_DATA_END" if delisted else "SUSPECTED_SUSPENSION"),
                        "checkable": True,
                        "first_valid": calendar[i0].date(), "last_valid": calendar[i1].date(),
                        "n_pre_listing": int(pre), "n_interior_missing": int(interior.sum()),
                        "n_post_end_missing": int(post), "n_long_gap_runs": len(longr),
                        "max_gap_len": int(maxg), "suspected_suspension": bool(suspected),
                        "delisted_or_data_end": bool(delisted), "note": ""})

    summ = pd.DataFrame(summary)
    summ.to_csv(INTEG / "suspension_audit_100.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(events).to_csv(INTEG / "suspension_events_100.csv", index=False, encoding="utf-8-sig")

    print("=" * 60)
    print(f"유니버스 100종목 거래정지 재검사 (달력 {calendar.min().date()}~{calendar.max().date()})")
    print(f"검사 가능: {len(present)}종목  /  가격 미확보: {len(absent)}종목 {absent}")
    print("-" * 60)
    print("status 분포:", summ["status"].value_counts().to_dict())
    print(f"suspected_suspension True: {int((summ['suspected_suspension']==True).sum())}")
    print(f"delisted_or_data_end True: {int((summ['delisted_or_data_end']==True).sum())}")
    print(f"\n출력: {INTEG/'suspension_audit_100.csv'} / suspension_events_100.csv")


if __name__ == "__main__":
    main()
