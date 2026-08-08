#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
08_download_missing13.py

거래정지 검사를 100종목 전체로 확장하기 위해, 가격 패널(prices_close.csv, 87종목)에
없는 13종목의 조정종가를 별도로 내려받는다. 기존 data/prices 는 건드리지 않고
data/integrity/ 에만 저장한다.

13종목은 어느 분기 Top30에도 선정된 적이 없어 05_download_prices 대상(선정종목 합집합)
에서 제외됐던 종목이다(누락 아님, 범위 차이).
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "data" / "integrity"
MISSING = ["CDW", "CEG", "DELL", "GDS", "GEV", "HPE", "JBL", "MOD",
           "NET", "NOK", "NTNX", "SNOW", "VIAV"]
START = "2009-06-01"
END = "2026-07-22"  # 기존 패널 마지막 거래일(2026-07-21) 포함


def main():
    INTEG.mkdir(parents=True, exist_ok=True)
    frames = {}
    meta = []
    for t in MISSING:
        df = yf.download(t, start=START, end=END, auto_adjust=True,
                         progress=False, threads=False)
        if df is None or df.empty:
            meta.append({"ticker": t, "rows": 0, "first": "", "last": "",
                         "status": "NO_DATA"})
            continue
        close = df["Close"]
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        close.name = t
        frames[t] = close
        meta.append({"ticker": t, "rows": int(close.notna().sum()),
                     "first": str(close.dropna().index.min().date()),
                     "last": str(close.dropna().index.max().date()),
                     "status": "OK"})
        print(f"{t:5s} rows={int(close.notna().sum()):5d} "
              f"{meta[-1]['first']} ~ {meta[-1]['last']}")

    panel = pd.concat(frames.values(), axis=1) if frames else pd.DataFrame()
    panel.index.name = "Date"
    panel.to_csv(INTEG / "prices_missing13.csv", encoding="utf-8-sig")
    pd.DataFrame(meta).to_csv(INTEG / "prices_missing13_coverage.csv",
                              index=False, encoding="utf-8-sig")
    print(f"\n저장: {INTEG/'prices_missing13.csv'} ({panel.shape[0]}행 x {panel.shape[1]}종목)")


if __name__ == "__main__":
    main()
