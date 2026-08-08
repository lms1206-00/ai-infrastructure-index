#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
23_membership_ledger.py  (편입·편출 원장 + 시나리오 Top30 차이 규명)

최종 방식(B_pit) 기준으로 분기별 편입·편출 원장을 생성한다.
필드: ticker, rebalance_date, previous_membership, current_membership, action,
      reason_code, factor_score, rank, theme_eligible, data_eligible.

reason_code:
  FACTOR_SCORE_TOP30 / FACTOR_SCORE_OUTSIDE_TOP30 / THEME_DIRECTNESS_LOW /
  BUSINESS_DISCONTINUED / (데이터탈락은 아래 세부: theme4ir 미포함 사유는 원 파이프라인의
  data 스크린 결과라 여기선 DATA_OR_FACTOR_SCREEN 로 집계)

또한 A 대비 B_pit / B_retro 의 Top30 멤버십 변화(ADD/DROP) 를 스냅숏별로 규명한다.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "data" / "integrity"


def wset(weights_file):
    w = pd.read_csv(weights_file); w["ticker"] = w["ticker"].str.upper()
    w["snapshot_date"] = w["snapshot_date"].astype(str)
    return w


def topn_diff(a_w, b_w, label):
    rows = []
    snaps = sorted(set(a_w.snapshot_date) | set(b_w.snapshot_date))
    for s in snaps:
        aset = set(a_w[a_w.snapshot_date == s].ticker)
        bset = set(b_w[b_w.snapshot_date == s].ticker)
        for t in sorted(aset - bset):
            rows.append(dict(snapshot_date=s, ticker=t, change="DROPPED_vs_A"))
        for t in sorted(bset - aset):
            rows.append(dict(snapshot_date=s, ticker=t, change="ADDED_vs_A"))
    df = pd.DataFrame(rows)
    df.to_csv(INTEG / f"topn_diff_{label}.csv", index=False, encoding="utf-8-sig")
    return df


def build_ledger():
    scores = pd.read_csv(INTEG / "scenario_B_pit" / "scores" / "factor_scores_quarterly.csv")
    scores["ticker"] = scores["ticker"].str.upper(); scores["snapshot_date"] = scores["snapshot_date"].astype(str)
    weights = wset(INTEG / "scenario_B_pit" / "weights" / "index_weights_quarterly.csv")
    elig = pd.read_csv(INTEG / "theme_eligibility_pit.csv")
    elig["ticker"] = elig["ticker"].str.upper(); elig["rebalance_date"] = elig["rebalance_date"].astype(str)
    elig_map = {(r.ticker, r.rebalance_date): (r.theme_eligible, r.theme_exclusion_reason)
                for r in elig.itertuples()}
    # 점수 랭킹(스냅숏별)
    scores["rank"] = scores.groupby("snapshot_date")["factor_score"].rank(ascending=False, method="min")
    top = weights.groupby("snapshot_date")["ticker"].apply(set).to_dict()

    # theme_eligibility 는 theme4ir 원(필터 전) 기준의 후보 — B_pit 는 필터 후라 theme-excl 종목이
    # scores 에 없다. 그래서 원장은 (스냅숏의 후보 = elig 테이블의 ticker) 전체를 순회한다.
    snaps = sorted(scores["snapshot_date"].unique())
    prev_top = set()
    rows = []
    # 후보 풀 = 각 스냅숏에서 elig 에 등장한 티커(=그 시점 theme4ir 후보) ∪ 점수 티커
    cand_by_snap = elig.groupby("rebalance_date")["ticker"].apply(set).to_dict()
    for s in snaps:
        cur_top = top.get(s, set())
        sc_s = scores[scores.snapshot_date == s].set_index("ticker")
        cands = cand_by_snap.get(s, set()) | set(sc_s.index)
        for t in sorted(cands):
            te, tereason = elig_map.get((t, s), (True, ""))
            in_scores = t in sc_s.index
            in_top = t in cur_top
            was_top = t in prev_top
            data_elig = in_scores  # 점수화됐다 = 데이터/팩터 심사 통과(+테마적격)
            if in_top:
                action = "MAINTAIN" if was_top else "ADD"
                reason = "FACTOR_SCORE_TOP30"
            else:
                action = "DROP" if was_top else "NONE"
                if not te:
                    reason = tereason or "THEME_DIRECTNESS_LOW"
                elif not in_scores:
                    reason = "DATA_OR_FACTOR_SCREEN"
                else:
                    reason = "FACTOR_SCORE_OUTSIDE_TOP30"
            rows.append(dict(
                ticker=t, rebalance_date=s,
                previous_membership="IN" if was_top else "OUT",
                current_membership="IN" if in_top else "OUT",
                action=action, reason_code=reason,
                factor_score=float(sc_s.at[t, "factor_score"]) if in_scores else None,
                rank=int(sc_s.at[t, "rank"]) if in_scores else None,
                theme_eligible=te, data_eligible=data_elig))
        prev_top = cur_top
    led = pd.DataFrame(rows)
    led.to_csv(INTEG / "membership_ledger_Bpit.csv", index=False, encoding="utf-8-sig")
    return led


def main():
    a_w = wset(INTEG / "scenario_A" / "weights" / "index_weights_quarterly.csv")
    bp_w = wset(INTEG / "scenario_B_pit" / "weights" / "index_weights_quarterly.csv")
    br_w = wset(INTEG / "scenario_B_retro" / "weights" / "index_weights_quarterly.csv")
    dp = topn_diff(a_w, bp_w, "Bpit_vs_A")
    dr = topn_diff(a_w, br_w, "Bretro_vs_A")
    led = build_ledger()

    print("=" * 64); print("편입·편출 원장 + Top30 시나리오 차이"); print("=" * 64)
    print(f"\n[B_pit vs A] Top30 변화 {len(dp)}건")
    print(dp.to_string(index=False) if len(dp) else "  없음")
    print(f"\n[B_retro vs A] Top30 변화 {len(dr)}건")
    print(dr.to_string(index=False) if len(dr) else "  없음")
    print(f"\n원장(B_pit) 행수: {len(led)}")
    print("reason_code 분포:", led["reason_code"].value_counts().to_dict())
    print("theme_eligible=False 행:", int((~led.theme_eligible).sum()),
          "→", sorted(set(led[~led.theme_eligible].ticker)))
    print(f"\n출력: membership_ledger_Bpit.csv, topn_diff_Bpit_vs_A.csv, topn_diff_Bretro_vs_A.csv")


if __name__ == "__main__":
    main()
