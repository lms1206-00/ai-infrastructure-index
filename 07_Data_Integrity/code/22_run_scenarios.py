#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
22_run_scenarios.py  (최종 선정 순서 시나리오 비교)

선정 순서: 100 후보 → 테마 적격성 → 데이터/팩터 심사 → Factor Score → Top30 → 가중.

시나리오:
  A  (기존)   : 테마 필터 미적용. 원본 theme4ir_pit(커밋본) → scores → weights → backtest.
  B_pit       : 회계원칙(v2) theme4ir + 테마필터(PIT: 근거 공개일 이후만) → scores → weights → backtest.
  B_retro     : 회계원칙(v2) theme4ir + 테마필터(전 분기 소급) → scores → weights → backtest. (참고용)

데이터/팩터 심사(theme4ir 단계, min 3/4·품질60·age365·warning)는 원 파이프라인이 이미 적용.
테마 부적격(ticker,snapshot)은 scores 투입 전에 제거(score_eligible=False → 순위 제외).
30개 미만이면 억지로 채우지 않음(weights 빌더가 실제 종목수만 편입).

원본 산출물 불변. 모든 출력은 data/integrity/scenario_*/ 격리.
QQQ + SOXX 추적 지표 계산.
"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]; PY = sys.executable
INTEG = ROOT / "data" / "integrity"
UNI = ROOT / "data" / "classification" / "final_universe_100.csv"
SCORE = ROOT / "03_Methodology" / "01_build_factor_scores.py"
WEIGHT = ROOT / "04_Index_Construction" / "01_build_index_weights.py"
BACKTEST = ROOT / "05_Backtest" / "02_run_backtest.py"
PRICES100 = INTEG / "prices_close_100.csv"
QQQ = ROOT / "data" / "prices" / "benchmark_qqq.csv"
SOXX = INTEG / "benchmark_soxx.csv"
TRADING = 252


def run(cmd):
    r = subprocess.run([PY, *map(str, cmd)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        print((r.stdout or "")[-1500:]); print((r.stderr or "")[-1500:])
        raise RuntimeError(str(cmd[0]))


def scenario(tag, base_theme4ir, elig_file=None):
    base = INTEG / f"scenario_{tag}"
    th_dir, sc, wt, bt = base/"theme", base/"scores", base/"weights", base/"backtest"
    for d in (th_dir, sc, wt, bt):
        d.mkdir(parents=True, exist_ok=True)
    th = pd.read_csv(base_theme4ir)
    th["ticker"] = th["ticker"].astype(str).str.upper()
    th["snapshot_date"] = th["snapshot_date"].astype(str)
    n_before = len(th)
    n_theme_excl = 0
    if elig_file is not None:
        el = pd.read_csv(elig_file)
        el["ticker"] = el["ticker"].str.upper(); el["rebalance_date"] = el["rebalance_date"].astype(str)
        bad = set(zip(el.loc[~el.theme_eligible, "ticker"], el.loc[~el.theme_eligible, "rebalance_date"]))
        mask = [ (t, s) in bad for t, s in zip(th["ticker"], th["snapshot_date"]) ]
        n_theme_excl = int(sum(mask))
        th = th[[not m for m in mask]].copy()
    th_path = th_dir / "theme4ir_pit.csv"
    th.to_csv(th_path, index=False, encoding="utf-8-sig")
    run([SCORE, "--input-file", th_path, "--output-dir", sc, "--overwrite"])
    run([WEIGHT, "--input-file", sc/"factor_scores_quarterly.csv", "--output-dir", wt,
         "--top-n", "30", "--cap", "0.10", "--overwrite"])
    run([BACKTEST, "--weights-file", wt/"index_weights_quarterly.csv",
         "--prices-file", PRICES100, "--qqq-file", QQQ, "--output-dir", bt,
         "--figures-dir", bt/"figures"])
    return dict(tag=tag, base=base, n_theme_excl=n_theme_excl,
                weights=wt/"index_weights_quarterly.csv",
                scores=sc/"factor_scores_quarterly.csv",
                level=bt/"index_level.csv", perf=bt/"performance_summary.csv")


def soxx_metrics(level_file):
    lvl = pd.read_csv(level_file); lvl.columns = [c.lower() for c in lvl.columns]
    dcol = [c for c in lvl.columns if "date" in c][0]
    icol = [c for c in lvl.columns if "index" in c or "level" in c][0]
    lvl[dcol] = pd.to_datetime(lvl[dcol]); lvl = lvl.set_index(dcol).sort_index()
    idx = lvl[icol].astype(float)
    sx = pd.read_csv(SOXX, index_col=0); sx.index = pd.to_datetime(sx.index)
    sx = sx.iloc[:, 0].reindex(idx.index).ffill()
    ri = idx.pct_change().dropna(); rs = sx.pct_change().reindex(ri.index)
    both = pd.concat([ri, rs], axis=1).dropna(); both.columns = ["i", "s"]
    corr = float(both["i"].corr(both["s"]))
    te = float((both["i"] - both["s"]).std() * np.sqrt(TRADING))
    beta = float(np.cov(both["i"], both["s"])[0, 1] / np.var(both["s"]))
    return dict(soxx_corr=corr, soxx_te=te, soxx_beta=beta)


def main():
    print("=" * 68); print("최종 선정 순서 시나리오 비교 (A 기존 / B_pit / B_retro)"); print("=" * 68)
    orig_theme = INTEG / "rerun_orig" / "theme" / "theme4ir_pit.csv"
    v2_theme = INTEG / "rerun_v2" / "theme" / "theme4ir_pit.csv"
    A = scenario("A", orig_theme, None)
    Bp = scenario("B_pit", v2_theme, INTEG / "theme_eligibility_pit.csv")
    Br = scenario("B_retro", v2_theme, INTEG / "theme_eligibility_retro.csv")

    # 결정성: A weights == 커밋 weights?
    wa = pd.read_csv(A["weights"]); wc = pd.read_csv(ROOT/"data"/"index"/"index_weights_quarterly.csv")
    for df in (wa, wc):
        df["ticker"] = df["ticker"].str.upper()
    ka = wa.set_index(["snapshot_date", "ticker"])["weight"]; kc = wc.set_index(["snapshot_date", "ticker"])["weight"]
    ix = ka.index.union(kc.index); dmax = float((ka.reindex(ix).fillna(0) - kc.reindex(ix).fillna(0)).abs().max())
    print(f"\n[결정성] 시나리오A weights vs 커밋본: 최대 비중차 {dmax:.3e}")

    # 성과 요약 표
    rows = []
    for S in (A, Bp, Br):
        perf = pd.read_csv(S["perf"]); perf = perf.set_index(perf.columns[0])
        m = soxx_metrics(S["level"])
        col = "AI_Custom_Index"
        rows.append(dict(scenario=S["tag"], theme_excluded_rows=S["n_theme_excl"],
                         CAGR=float(perf.loc["cagr", col]), vol=float(perf.loc["annualized_volatility", col]),
                         Sharpe=float(perf.loc["sharpe_ratio", col]), MDD=float(perf.loc["max_drawdown", col]),
                         **m))
    summ = pd.DataFrame(rows)
    summ.to_csv(INTEG / "scenario_summary.csv", index=False, encoding="utf-8-sig")
    print("\n[성과·추적 요약]")
    print(summ.to_string(index=False))

    # Top30 멤버십/비중 변화 (A 대비)
    def wmap(p):
        w = pd.read_csv(p); w["ticker"] = w["ticker"].str.upper()
        return w.set_index(["snapshot_date", "ticker"])["weight"]
    a = wmap(A["weights"])
    for S in (Bp, Br):
        b = wmap(S["weights"]); ix = a.index.union(b.index)
        aa = a.reindex(ix).fillna(0); bb = b.reindex(ix).fillna(0)
        memb = int(((aa > 0) != (bb > 0)).sum()); dmx = float((aa - bb).abs().max())
        chg_snaps = sorted(set(s for (s, t) in ix[((aa > 0) != (bb > 0))]))
        print(f"\n[{S['tag']} vs A] 멤버십 변화 {memb}건, 최대 비중차 {dmx:.3e}")
        if chg_snaps:
            print("  멤버십 변화 스냅숏:", chg_snaps)
    print(f"\n출력: {INTEG/'scenario_summary.csv'}, scenario_*/ (weights·backtest)")


if __name__ == "__main__":
    main()
