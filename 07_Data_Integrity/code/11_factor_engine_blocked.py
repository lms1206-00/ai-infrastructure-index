#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
11_factor_engine_blocked.py  (후속검증 항목3: 교차기준 성장률 실입력 차단 옵션)

원칙: 전기와 당기의 회계기준이 다르면 성장률(revenue/operating_income/net_income/
asset _growth)을 **원칙적으로 결측 처리**하고, **동일 기준으로 재작성(restated)된 전기
비교 수치가 있을 때만** 그 값으로 재계산한다.

구현
----
기존 01_factor_engine.py 를 import 하여 원본 팩터를 재현하고, 각 성장률에 대해:
  1) 당기 선택 fact 의 taxonomy(S_cur) 확인.
  2) 직전 비교기간(previous_comparable)의 동일 metric fact 중 **taxonomy==S_cur** 인
     값(=재작성 비교치)을 facts 에서 탐색.
  3) - S_prev == S_cur 이면: 원본과 동일(변경 없음), 결정=SAME_STANDARD.
     - S_prev != S_cur 이고 재작성치 존재: 그 값으로 재계산, 결정=RECOMPUTED_RESTATED.
     - S_prev != S_cur 이고 재작성치 없음: 결측(NaN), 결정=BLOCKED_NULLED.

원본 data/factors 는 덮어쓰지 않는다. 블록 적용본은 data/integrity/factors_blocked/{cik}.parquet.
결정 로그: data/integrity/growth_blocking_decisions.csv (전환기업만 기록).

이 옵션은 factor 입력 단계의 차단이며, 하류(PIT->scores->weights)를 이 블록 dir 로
재실행하면 지수 영향을 실측할 수 있다(12_ 스크립트).
"""
from __future__ import annotations
import importlib.util
import shutil
import sys
from pathlib import Path
import numpy as np
import pandas as pd

THIS = Path(__file__).resolve()
ROOT = THIS.parents[2]
FACTS = ROOT / "data" / "facts"
FACTORS = ROOT / "data" / "factors"
INTEG = ROOT / "data" / "integrity"
BLOCK_DIR = INTEG / "factors_blocked"
UNIVERSE = ROOT / "data" / "classification" / "final_universe_100.csv"
ENGINE = ROOT / "02_Data_Preprocessing" / "code" / "01_factor_engine.py"
FIN_TAX = {"us-gaap", "ifrs-full"}
GROWTH = {"revenue_growth": "revenue", "operating_income_growth": "operating_income",
          "net_income_growth": "net_income", "asset_growth": "assets"}


def load_engine():
    spec = importlib.util.spec_from_file_location("factor_engine", ENGINE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["factor_engine"] = mod
    spec.loader.exec_module(mod)
    return mod


def prev_value_same_tax(eng, facts, metric, cur_std, prev_anchor, as_of_filed):
    """직전 비교기간의 metric 값을 current taxonomy(cur_std) 로 탐색(재작성 비교치).
    재작성값은 당기 공시에 담기므로 as-of 는 '당기 filed'(as_of_filed)로 제약한다."""
    sub = facts[facts["taxonomy"] == cur_std] if "taxonomy" in facts else facts
    chosen = eng.choose_metric_fact(
        facts=sub, metric=metric, anchor_end=prev_anchor["period_end"],
        anchor_filed=pd.Timestamp(as_of_filed),
        anchor_form=prev_anchor["form"], anchor_fy=prev_anchor.get("fiscal_year"),
        anchor_fp=prev_anchor.get("fiscal_period"))
    return None if chosen is None else float(chosen["value"])


def process_cik(eng, cik, tkr):
    fpath = FACTS / f"{cik}.parquet"
    orig = pd.read_parquet(FACTORS / f"{cik}.parquet")
    if not fpath.exists() or orig.empty:
        return orig, []
    facts = eng.standardize_fact_store(pd.read_parquet(fpath), cik)
    # 각 행(anchor)의 지배 taxonomy: 5 metric 최빈 재무 taxonomy 재계산
    anchors = eng.build_anchors(facts)
    end_to_std = {}
    for _, a in anchors.iterrows():
        taxs = []
        for m in ["revenue", "operating_income", "net_income", "assets", "liabilities"]:
            ch = eng.choose_metric_fact(facts=facts, metric=m, anchor_end=a["end"],
                                        anchor_filed=a["filed"], anchor_form=a["form"],
                                        anchor_fy=a["fy"], anchor_fp=a["fp"])
            if ch is not None and str(ch.get("taxonomy", "")) in FIN_TAX:
                taxs.append(str(ch["taxonomy"]))
        if taxs:
            end_to_std[pd.Timestamp(a["end"])] = max(set(taxs), key=taxs.count)

    blocked = orig.copy()
    decisions = []
    changed = False
    df_sorted = blocked.sort_values(["period_type", "period_end"]).reset_index()
    for ptype, grp in df_sorted.groupby("period_type"):
        grp = grp.sort_values("period_end")
        prev_row = None
        for _, row in grp.iterrows():
            cur_end = pd.Timestamp(row["period_end"])
            cur_std = end_to_std.get(cur_end)
            if prev_row is not None and cur_std is not None:
                prev_end = pd.Timestamp(prev_row["period_end"])
                prev_std = end_to_std.get(prev_end)
                if prev_std is not None and prev_std != cur_std:
                    # 전환 경계: 각 성장률 처리
                    for gcol, metric in GROWTH.items():
                        cur_val = row.get(metric)
                        prev_anchor = {"period_end": prev_end, "filed": prev_row["filed"],
                                       "form": prev_row["form"],
                                       "fiscal_year": prev_row.get("fiscal_year"),
                                       "fiscal_period": prev_row.get("fiscal_period")}
                        restated = prev_value_same_tax(eng, facts, metric, cur_std,
                                                       prev_anchor, as_of_filed=row["filed"])
                        idx = int(row["index"])
                        orig_val = orig.at[idx, gcol] if gcol in orig.columns else np.nan
                        if restated is not None and pd.notna(cur_val) and restated != 0:
                            newv = float(cur_val) / restated - 1.0
                            decision = "RECOMPUTED_RESTATED"
                        else:
                            newv = np.nan
                            decision = "BLOCKED_NULLED"
                        blocked.at[idx, gcol] = newv
                        if not (pd.isna(orig_val) and pd.isna(newv)):
                            changed = changed or (pd.isna(orig_val) != pd.isna(newv)
                                                  or abs(float(orig_val or 0) - float(newv or 0)) > 1e-12)
                        decisions.append({
                            "ticker": tkr, "cik": cik, "period_end": str(cur_end.date()),
                            "period_type": ptype, "growth_factor": gcol,
                            "prev_standard": prev_std, "cur_standard": cur_std,
                            "orig_value": orig_val, "restated_prev_value": restated,
                            "blocked_value": newv, "decision": decision})
            prev_row = row
    return blocked, decisions, changed


def main():
    if BLOCK_DIR.exists():
        shutil.rmtree(BLOCK_DIR)
    BLOCK_DIR.mkdir(parents=True, exist_ok=True)
    eng = load_engine()
    uni = pd.read_csv(UNIVERSE, encoding="utf-8-sig")
    uni["cik"] = uni["cik"].astype(str).str.replace(".0", "", regex=False).str.zfill(10)

    all_dec = []
    n_changed = 0
    for _, r in uni.iterrows():
        cik, tkr = r["cik"], r["ticker"]
        res = process_cik(eng, cik, tkr)
        blocked, decisions = res[0], res[1]
        changed = res[2] if len(res) > 2 else False
        blocked.to_parquet(BLOCK_DIR / f"{cik}.parquet", index=False)
        all_dec.extend(decisions)
        if changed:
            n_changed += 1
            print(f"  변경 발생: {tkr} ({cik})")

    dec = pd.DataFrame(all_dec)
    dec.to_csv(INTEG / "growth_blocking_decisions.csv", index=False, encoding="utf-8-sig")
    print("=" * 64)
    print("항목3  교차기준 성장률 차단 옵션 실행")
    print("=" * 64)
    print(f"블록 팩터 파일: {BLOCK_DIR} (100개)")
    print(f"성장률 값이 원본과 달라진 기업 수: {n_changed}")
    if len(dec):
        print("\n[전환 경계 성장률 결정 로그]")
        print(dec[["ticker", "period_end", "growth_factor", "prev_standard",
                   "cur_standard", "orig_value", "restated_prev_value",
                   "blocked_value", "decision"]].to_string(index=False))
    print(f"\n출력: {INTEG/'growth_blocking_decisions.csv'}")


if __name__ == "__main__":
    main()
