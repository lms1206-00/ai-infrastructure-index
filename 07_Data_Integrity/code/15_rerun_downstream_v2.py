#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
15_rerun_downstream_v2.py  (최종 원칙 v2 차단 후 지수영향 + 분기별 평가가능성 실측)

factors_blocked_v2 로 동일 파라미터 체인을 격리 재구성하고:
  - 최종 index_weights 를 원본 재구성본과 diff (지수 순영향)
  - theme4ir_pit 에서 전환기업(CLS)의 분기별 required_factor_count / 편입자격(include)을
    원본 대비 비교 (= '해당 분기 평가 가능 여부'만 바뀌는지, 유니버스 삭제 아님을 확인)
원본 산출물 불변, 출력은 data/integrity/rerun_v2/ 만.
"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]; PY = sys.executable
INTEG = ROOT / "data" / "integrity"
UNI = ROOT / "data" / "classification" / "final_universe_100.csv"
SRC = {"pit": ROOT/"02_Data_Preprocessing"/"code"/"04_build_pit_snapshot.py",
       "theme": ROOT/"02_Data_Preprocessing"/"code"/"05_build_theme4ir_pit.py",
       "score": ROOT/"03_Methodology"/"01_build_factor_scores.py",
       "weight": ROOT/"04_Index_Construction"/"01_build_index_weights.py"}


def run(cmd):
    r = subprocess.run([PY, *map(str, cmd)], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-1500:]); print(r.stderr[-1500:]); raise RuntimeError(cmd[0])


def chain(tag, factor_dir):
    base = INTEG / f"rerun_{tag}"
    pit, th, sc, wt = base/"pit", base/"theme", base/"scores", base/"weights"
    for d in (pit, th, sc, wt):
        d.mkdir(parents=True, exist_ok=True)
    run([SRC["pit"], "--factor-dir", factor_dir, "--universe-file", UNI,
         "--output-dir", pit, "--frequency", "quarterly", "--overwrite"])
    run([SRC["theme"], "--input-file", pit/"pit_snapshot_quarterly.parquet",
         "--output-dir", th, "--min-required-factors", "3", "--overwrite"])
    run([SRC["score"], "--input-file", th/"theme4ir_pit.csv", "--output-dir", sc, "--overwrite"])
    run([SRC["weight"], "--input-file", sc/"factor_scores_quarterly.csv",
         "--output-dir", wt, "--top-n", "30", "--cap", "0.10", "--overwrite"])
    return base


def weight_diff(a, b):
    wa = pd.read_csv(a/"weights"/"index_weights_quarterly.csv")
    wb = pd.read_csv(b/"weights"/"index_weights_quarterly.csv")
    wa["ticker"] = wa.ticker.str.upper(); wb["ticker"] = wb.ticker.str.upper()
    ka = wa.set_index(["snapshot_date", "ticker"])["weight"]
    kb = wb.set_index(["snapshot_date", "ticker"])["weight"]
    idx = ka.index.union(kb.index); ka = ka.reindex(idx).fillna(0); kb = kb.reindex(idx).fillna(0)
    return float((ka-kb).abs().max()), int(((ka > 0) != (kb > 0)).sum())


def cls_quarterly(base, tag):
    th = pd.read_csv(base/"theme"/"theme4ir_pit.csv", dtype={"cik": "string"})
    col_cnt = next((c for c in ["required_factor_count", "available_factor_count",
                                "factor_available_count"] if c in th.columns), None)
    inc = next((c for c in ["include", "eligible", "pit_valid"] if c in th.columns), None)
    cls = th[th.get("ticker", pd.Series(dtype=str)).astype(str).str.upper() == "CLS"]
    return cls, col_cnt, inc, tag


def main():
    print("=" * 64); print("v2 최종 원칙 차단 후 지수영향 + 분기별 평가가능성"); print("=" * 64)
    b_orig = chain("orig", ROOT/"data"/"factors")          # (이미 있으면 재사용되나 안전하게 재실행)
    b_v2 = chain("v2", INTEG/"factors_blocked_v2")
    md, mm = weight_diff(b_v2, b_orig)
    print(f"\n[v2 vs 원본재구성] 최대 비중차 {md:.3e}, 편입멤버십 변화 {mm}건")

    # CLS 편입/평가가능성 비교
    for base, tag in [(b_orig, "orig"), (b_v2, "v2")]:
        w = pd.read_csv(base/"weights"/"index_weights_quarterly.csv")
        cls = w[w.ticker.str.upper() == "CLS"]
        print(f"CLS 편입({tag}): {len(cls)}스냅숏", list(cls.snapshot_date) if len(cls) else "")
    print("\n[CLS 분기별 평가가능성 — 유니버스 삭제 아님, 분기 자격만]")
    for base, tag in [(b_orig, "orig"), (b_v2, "v2")]:
        cls, cnt, inc, _ = cls_quarterly(base, tag)
        if len(cls) and cnt:
            sub = cls[["snapshot_date"] + [c for c in [cnt, inc] if c]].tail(6)
            print(f" [{tag}] (최근 6분기)"); print(sub.to_string(index=False))
    print(f"\n결론: v2 차단 순영향 = 최대비중차 {md:.3e}, 멤버십 {mm}건. "
          f"CLS는 유니버스 유지·분기 자격만 판정.")


if __name__ == "__main__":
    main()
