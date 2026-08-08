#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
24_special_removal_verification.py

"특별편출 0건" 결론의 근거를 전수 점검표로 재정리한다. 새 추정 없이 기존
가격패널(prices_close_100)·suspension_audit_100·corporate_actions 만 사용한다.

산출:
  1) sr_suspension_100.csv    : 100종목 가격 시작/종료·내부결측·최대결측·flat(가격미갱신 proxy)
  2) sr_corporate_actions.csv : 기업행위 25건 + in-backtest + eff시점 Top30 여부
  3) sr_event_replay.csv      : ONTO/COHR/GEV/CEG 사건 재현(가격·Top30·처리방식)
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "data" / "integrity"
PANEL = INTEG / "prices_close_100.csv"
QQQ = ROOT / "data" / "prices" / "benchmark_qqq.csv"
WEIGHTS = ROOT / "data" / "index" / "index_weights_quarterly.csv"


def longest_flat_run(s: pd.Series) -> int:
    """상장 후 구간에서 종가가 '직전과 완전히 동일'한 최장 연속 거래일 수(가격 미갱신 proxy).
    거래량 자료가 없어 정지 확정 불가 -> proxy 로만 사용."""
    v = s.dropna()
    if len(v) < 2:
        return 0
    same = (v.values[1:] == v.values[:-1])
    best = cur = 0
    for x in same:
        cur = cur + 1 if x else 0
        best = max(best, cur)
    return int(best)


def main():
    px = pd.read_csv(PANEL, index_col=0); px.index = pd.to_datetime(px.index)
    px.columns = [c.upper() for c in px.columns]
    q = pd.read_csv(QQQ, index_col=0); q.index = pd.to_datetime(q.index)
    cal = q.sort_index().index
    px = px.reindex(cal)  # 거래소 달력 정렬
    susp = pd.read_csv(INTEG / "suspension_audit_100.csv", encoding="utf-8-sig")

    # 1) suspension 100 + flat proxy
    rows = []
    for _, r in susp.iterrows():
        t = r["ticker"]
        s = px[t] if t in px.columns else pd.Series(dtype=float)
        rows.append(dict(
            ticker=t, first_valid=r["first_valid"], last_valid=r["last_valid"],
            n_trading_days_listed=int(s.notna().sum()),
            n_interior_missing=r["n_interior_missing"],
            max_interior_gap_days=r["max_gap_len"],
            n_post_end_missing=r["n_post_end_missing"],
            longest_flat_close_run=longest_flat_run(s),
            suspected_suspension=r["suspected_suspension"],
            delisted_or_data_end=r["delisted_or_data_end"],
            detection_basis="PRICE_MISSING_INFERENCE(거래량·공식정지고시 미대조)",
        ))
    s1 = pd.DataFrame(rows)
    s1.to_csv(INTEG / "sr_suspension_100.csv", index=False, encoding="utf-8-sig")

    # 2) corporate actions 25 + Top30
    ca = pd.read_csv(INTEG / "corporate_actions.csv", encoding="utf-8-sig")
    acts = ca[ca.corporate_action_type != "NONE"].copy()
    w = pd.read_csv(WEIGHTS); w["snapshot_date"] = pd.to_datetime(w["snapshot_date"]); w["ticker"] = w["ticker"].str.upper()
    P0, P1 = cal.min(), cal.max()
    crows = []
    REMOVAL_TYPES = {"DELIST", "GO_PRIVATE", "BANKRUPTCY", "MERGER_DISSOLVED"}
    for _, r in acts.iterrows():
        t = r["ticker"]; eff = pd.to_datetime(r["effective_date"], errors="coerce")
        sub = w[w.ticker == t]
        top_before = sub[sub.snapshot_date <= eff].snapshot_date.max() if (pd.notna(eff) and len(sub)) else pd.NaT
        top_after = sub[sub.snapshot_date > eff].snapshot_date.min() if (pd.notna(eff) and len(sub)) else pd.NaT
        crows.append(dict(
            ticker=t, corporate_action_type=r["corporate_action_type"],
            announcement_date=r["announcement_date"], effective_date=r["effective_date"],
            in_backtest_range=bool(pd.notna(eff) and P0 <= eff <= P1),
            is_removal_type=r["corporate_action_type"] in REMOVAL_TYPES,
            n_top30_snapshots=int(len(sub)),
            top30_snapshot_on_or_before_eff=str(top_before.date()) if pd.notna(top_before) else "",
            top30_snapshot_after_eff=str(top_after.date()) if pd.notna(top_after) else "",
            action_source=r.get("action_source", ""),
        ))
    s2 = pd.DataFrame(crows)
    s2.to_csv(INTEG / "sr_corporate_actions.csv", index=False, encoding="utf-8-sig")

    # 3) event replay
    EVENTS = [("ONTO", "2019-10-25", "TICKER_NAME_CHANGE", "NANO/RTEC→ONTO(역합병). yfinance ONTO 이력 미연결"),
              ("COHR", "2022-07-01", "TICKER_NAME_CHANGE", "IIVI→COHR(사명변경). yfinance COHR가 IIVI 이력을 조정연결"),
              ("GEV", "2024-04-02", "SPINOFF_NEW_LISTING", "GE 분할 신규상장"),
              ("CEG", "2022-02-01", "SPINOFF_NEW_LISTING", "Exelon 분할 신규상장")]
    erows = []
    for t, eff, typ, note in EVENTS:
        eff = pd.Timestamp(eff); s = px[t] if t in px.columns else pd.Series(dtype=float)
        fv = s.dropna().index.min() if s.notna().any() else None
        sub = w[w.ticker == t]
        held_before = sub[sub.snapshot_date <= eff]
        held_after = sub[sub.snapshot_date > eff]
        price_before_eff = bool(s[s.index < eff].notna().any())
        price_after_eff = bool(s[s.index >= eff].notna().any())
        # 처리방식 판정
        if not len(sub):
            handling = "Top30 편입 이력 없음 → 지수 무영향"
        elif not price_before_eff:
            handling = "전환 전 신티커 가격 없음 → 해당 진입일 제외·재정규화(교환비율 미모델)"
        else:
            handling = "연속 조정가로 보유(동일법인 CIK 승계, 가격 연결됨)"
        erows.append(dict(
            ticker=t, effective_date=str(eff.date()), type=typ,
            price_first_valid=str(fv.date()) if fv is not None else "",
            price_exists_before_eff=price_before_eff, price_exists_after_eff=price_after_eff,
            n_top30_snapshots=int(len(sub)),
            top30_on_or_before_eff=str(held_before.snapshot_date.max().date()) if len(held_before) else "",
            top30_after_eff=str(held_after.snapshot_date.min().date()) if len(held_after) else "",
            backtest_handling=handling, cash_or_exchange_ratio_modeled=False, note=note,
        ))
    s3 = pd.DataFrame(erows)
    s3.to_csv(INTEG / "sr_event_replay.csv", index=False, encoding="utf-8-sig")

    # 요약 출력
    print("=" * 66); print("특별편출 0건 근거 검증 점검표"); print("=" * 66)
    print(f"[1 거래정지] 100종목: 내부결측 합계 {int(s1.n_interior_missing.sum())}, "
          f"최대 내부결측 {int(s1.max_interior_gap_days.max())}일, "
          f"중도종료 {int((s1.delisted_or_data_end==True).sum())}, "
          f"장기정지의심 {int((s1.suspected_suspension==True).sum())}")
    print(f"   최장 flat-close(가격미갱신 proxy) 최대: {int(s1.longest_flat_close_run.max())}일 "
          f"({s1.loc[s1.longest_flat_close_run.idxmax(),'ticker']}) — 거래량 미대조 proxy")
    print(f"   공식 거래정지 고시 대조: 안 함(PRICE_MISSING_INFERENCE)")
    print(f"[2 기업행위] {len(s2)}건 중 removal-type(합병소멸/폐지/비상장/파산): "
          f"{int(s2.is_removal_type.sum())}건")
    print(f"[3 재현] ONTO/COHR/GEV/CEG:")
    print(s3[["ticker","effective_date","n_top30_snapshots","top30_on_or_before_eff",
              "price_exists_before_eff","backtest_handling"]].to_string(index=False))
    print(f"\n출력: sr_suspension_100.csv, sr_corporate_actions.csv, sr_event_replay.csv")


if __name__ == "__main__":
    main()
