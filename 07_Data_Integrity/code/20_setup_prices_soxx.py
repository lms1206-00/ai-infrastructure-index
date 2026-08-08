#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
20_setup_prices_soxx.py

시나리오 백테스트용 준비:
  (1) 100종목 통합 가격패널 = prices_close(87) + prices_missing13(13) 합집합
      -> data/integrity/prices_close_100.csv (원본 data/prices 불변)
  (2) SOXX(iShares Semiconductor ETF) 벤치마크 다운로드
      -> data/integrity/benchmark_soxx.csv
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "data" / "integrity"
PRICES = ROOT / "data" / "prices" / "prices_close.csv"
MISSING = INTEG / "prices_missing13.csv"


def main():
    INTEG.mkdir(parents=True, exist_ok=True)
    px = pd.read_csv(PRICES, index_col=0); px.index = pd.to_datetime(px.index)
    add = pd.read_csv(MISSING, index_col=0); add.index = pd.to_datetime(add.index)
    px.columns = [c.upper() for c in px.columns]; add.columns = [c.upper() for c in add.columns]
    add = add.drop(columns=[c for c in add.columns if c in px.columns])
    panel = px.join(add, how="outer").sort_index()
    panel.index.name = "Date"
    panel.to_csv(INTEG / "prices_close_100.csv", encoding="utf-8-sig")
    print(f"통합 패널: {panel.shape[0]}행 x {panel.shape[1]}종목 -> prices_close_100.csv")

    # SOXX
    soxx = yf.download("SOXX", start="2009-06-01", end="2026-07-22",
                       auto_adjust=True, progress=False, threads=False)
    close = soxx["Close"]
    if hasattr(close, "columns"):
        close = close.iloc[:, 0]
    close.name = "SOXX"
    close.index.name = "Date"
    close.to_frame().to_csv(INTEG / "benchmark_soxx.csv", encoding="utf-8-sig")
    print(f"SOXX: {int(close.notna().sum())}거래일 "
          f"{close.dropna().index.min().date()}~{close.dropna().index.max().date()} -> benchmark_soxx.csv")


if __name__ == "__main__":
    main()
