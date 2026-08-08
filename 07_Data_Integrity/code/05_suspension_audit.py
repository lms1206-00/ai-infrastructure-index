#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
05_suspension_audit.py  (Item 5: 거래정지 처리)

목적
----
가격 데이터 결측을 "거래정지"로 단정하지 않고 아래 5범주로 구분한다.
  (H) exchange_holiday        : 거래소 휴장일 -> 애초에 달력에서 제외(구조적으로 미발생)
  (P) pre_listing             : 최초 상장(첫 유효가) 이전 -> 결측이 정상
  (D) delisted_or_data_end    : 마지막 유효가 이후 패널 종료 -> 상장폐지 또는 데이터 종료
  (G) short_gap               : 상장 구간 내부의 짧은(<20 거래일) 결측 -> 일시적 결측/공급오류 의심
  (S) suspected_suspension    : 상장 구간 내부의 장기(>=20 연속 거래일) 결측 -> 거래정지 의심

거래소 달력은 QQQ(NASDAQ-100 ETF) 실제 거래일을 정본으로 사용한다.
QQQ 는 매 정규장 세션마다 거래되므로 그 인덱스가 NYSE/NASDAQ 세션의 신뢰 가능한
근사 달력이며, 휴장일은 인덱스에 아예 없어 "휴장 vs 결측"이 구조적으로 분리된다.

한계(반드시 명시)
------------------
* 본 패널에는 개별종목 "거래량" 과 공식 "거래정지(halt) 고시" 가 없어,
  장기 내부결측이 (1) 실제 종목 거래정지인지 (2) 데이터 공급 누락인지 자동 확정 불가.
  -> 따라서 자동 편출하지 않고 'suspected_suspension' 으로만 표기(사람 검토 대상).
* 20 거래일 임계는 프로젝트 규정값이며, 실제 거래정지는 수시간~수일이 대부분이라
  일별 종가 패널로는 단기 halt 를 탐지할 수 없다(경계의 한계).

입력 : data/prices/prices_close.csv , data/prices/benchmark_qqq.csv
출력 : data/integrity/suspension_audit.csv        (종목 1행 요약)
       data/integrity/suspension_events.csv        (내부결측 run 1행)
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PRICES = ROOT / "data" / "prices" / "prices_close.csv"
QQQ = ROOT / "data" / "prices" / "benchmark_qqq.csv"
OUT = ROOT / "data" / "integrity"
LONG_GAP_DAYS = 20  # 프로젝트 규정: 장기 거래정지 = 연속 20 거래일 이상


def runs_of_true(mask: np.ndarray):
    """연속 True 구간의 (start_idx, end_idx_inclusive) 리스트."""
    out = []
    n = len(mask)
    i = 0
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    px = pd.read_csv(PRICES, index_col=0)
    px.index = pd.to_datetime(px.index)
    px = px.sort_index()
    qqq = pd.read_csv(QQQ, index_col=0)
    qqq.index = pd.to_datetime(qqq.index)
    qqq = qqq.sort_index()

    # 거래소 달력 = QQQ 거래일(휴장일은 이 인덱스에 존재하지 않음)
    calendar = qqq.index
    px = px.reindex(calendar)  # 패널을 거래소 달력에 정렬 -> 휴장일 구조적 제외
    panel_end = calendar.max()

    summary_rows = []
    event_rows = []
    for tkr in px.columns:
        s = px[tkr]
        valid = s.notna().values
        if not valid.any():
            summary_rows.append({
                "ticker": tkr, "status": "NO_DATA", "first_valid": pd.NaT,
                "last_valid": pd.NaT, "n_trading_days": len(calendar),
                "n_pre_listing": len(calendar), "n_interior_missing": 0,
                "n_post_end_missing": 0, "n_interior_gap_runs": 0,
                "n_long_gap_runs": 0, "max_gap_len": 0,
                "suspected_suspension": False, "delisted_or_data_end": False,
                "note": "패널 전체 결측",
            })
            continue

        idx_first = int(np.argmax(valid))                 # 첫 유효가 위치
        idx_last = len(valid) - 1 - int(np.argmax(valid[::-1]))  # 마지막 유효가 위치

        pre = idx_first                                    # pre-listing 결측 수
        post = (len(valid) - 1) - idx_last                 # 마지막 유효가 이후 결측 수
        interior = ~valid.copy()
        interior[:idx_first + 1] = False
        interior[idx_last:] = False                        # 내부 결측만 True

        interior_runs = runs_of_true(interior)
        gap_lens = [(b - a + 1) for a, b in interior_runs]
        long_runs = [r for r, L in zip(interior_runs, gap_lens) if L >= LONG_GAP_DAYS]
        max_gap = max(gap_lens) if gap_lens else 0

        delisted = post > 0 and idx_last < len(valid) - 1  # 마지막 유효가가 패널 끝 이전
        suspected = len(long_runs) > 0

        for a, b in interior_runs:
            L = b - a + 1
            event_rows.append({
                "ticker": tkr,
                "gap_start": calendar[a].date(),
                "gap_end": calendar[b].date(),
                "trading_days_missing": L,
                "classification": "suspected_suspension" if L >= LONG_GAP_DAYS else "short_gap",
            })

        summary_rows.append({
            "ticker": tkr,
            "status": "OK" if not (suspected or delisted) else
                      ("DELISTED_OR_DATA_END" if delisted else "SUSPECTED_SUSPENSION"),
            "first_valid": calendar[idx_first].date(),
            "last_valid": calendar[idx_last].date(),
            "n_trading_days": len(calendar),
            "n_pre_listing": int(pre),
            "n_interior_missing": int(interior.sum()),
            "n_post_end_missing": int(post),
            "n_interior_gap_runs": len(interior_runs),
            "n_long_gap_runs": len(long_runs),
            "max_gap_len": int(max_gap),
            "suspected_suspension": bool(suspected),
            "delisted_or_data_end": bool(delisted),
            "note": "" ,
        })

    summ = pd.DataFrame(summary_rows).sort_values(
        ["suspected_suspension", "delisted_or_data_end", "ticker"], ascending=[False, False, True])
    events = pd.DataFrame(event_rows)
    summ.to_csv(OUT / "suspension_audit.csv", index=False, encoding="utf-8-sig")
    events.to_csv(OUT / "suspension_events.csv", index=False, encoding="utf-8-sig")

    print("=" * 60)
    print(f"거래소 달력(QQQ 거래일): {calendar.min().date()} ~ {panel_end.date()}  "
          f"({len(calendar):,} 거래일), 종목 {len(px.columns)}개")
    print("-" * 60)
    print("status 분포:", summ["status"].value_counts().to_dict())
    print(f"장기(>= {LONG_GAP_DAYS}거래일) 내부결측(suspected_suspension) 종목: "
          f"{int(summ['suspected_suspension'].sum())}개")
    print(f"마지막유효가가 패널끝 이전(delisted/data-end) 종목: "
          f"{int(summ['delisted_or_data_end'].sum())}개")
    sus = summ[summ["suspected_suspension"] | summ["delisted_or_data_end"]]
    if len(sus):
        print("\n[검토 대상]")
        print(sus[["ticker", "status", "first_valid", "last_valid",
                   "n_long_gap_runs", "max_gap_len", "n_post_end_missing"]].to_string(index=False))
    else:
        print("\n장기 내부결측/중도종료 종목 없음 -> 전 종목 정상 커버리지.")
    print(f"\n출력: {OUT/'suspension_audit.csv'}")
    print(f"출력: {OUT/'suspension_events.csv'}")


if __name__ == "__main__":
    main()
