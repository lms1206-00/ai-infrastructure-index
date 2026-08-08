#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
13_rerun_downstream_blocked.py  (후속검증 항목3: 차단 적용 후 지수 영향 실측)

블록 적용 팩터(data/integrity/factors_blocked)와 원본 팩터(data/factors)를 각각
동일 파라미터 체인(PIT quarterly -> theme4ir min3 -> scores -> weights top30/cap0.10)으로
격리 폴더에 재구성하고, 최종 index_weights_quarterly 를 diff 한다.

원본 산출물(data/pit, data/scores, data/index)은 절대 덮어쓰지 않는다 —
모든 출력은 data/integrity/rerun_{orig,blocked}/ 하위로만 나간다.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable
INTEG = ROOT / "data" / "integrity"
UNI = ROOT / "data" / "classification" / "final_universe_100.csv"
PIT_SRC = ROOT / "02_Data_Preprocessing" / "code" / "04_build_pit_snapshot.py"
THEME_SRC = ROOT / "02_Data_Preprocessing" / "code" / "05_build_theme4ir_pit.py"
SCORE_SRC = ROOT / "03_Methodology" / "01_build_factor_scores.py"
WEIGHT_SRC = ROOT / "04_Index_Construction" / "01_build_index_weights.py"


def run(cmd):
    print("  $", " ".join(str(c) for c in cmd[-4:]))
    r = subprocess.run([PY, *map(str, cmd)], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:]); print(r.stderr[-2000:])
        raise RuntimeError(f"실패: {cmd[0]}")


def chain(tag, factor_dir):
    base = INTEG / f"rerun_{tag}"
    pit, theme, score, weight = base/"pit", base/"theme", base/"scores", base/"weights"
    for d in (pit, theme, score, weight):
        d.mkdir(parents=True, exist_ok=True)
    run([PIT_SRC, "--factor-dir", factor_dir, "--universe-file", UNI,
         "--output-dir", pit, "--frequency", "quarterly", "--overwrite"])
    run([THEME_SRC, "--input-file", pit/"pit_snapshot_quarterly.parquet",
         "--output-dir", theme, "--min-required-factors", "3", "--overwrite"])
    run([SCORE_SRC, "--input-file", theme/"theme4ir_pit.csv",
         "--output-dir", score, "--overwrite"])
    run([WEIGHT_SRC, "--input-file", score/"factor_scores_quarterly.csv",
         "--output-dir", weight, "--top-n", "30", "--cap", "0.10", "--overwrite"])
    return weight / "index_weights_quarterly.csv"


def compare(a_path, b_path, label):
    a = pd.read_csv(a_path); b = pd.read_csv(b_path)
    a["ticker"] = a["ticker"].str.upper(); b["ticker"] = b["ticker"].str.upper()
    ka = a.set_index(["snapshot_date", "ticker"])["weight"]
    kb = b.set_index(["snapshot_date", "ticker"])["weight"]
    idx = ka.index.union(kb.index)
    ka = ka.reindex(idx).fillna(0); kb = kb.reindex(idx).fillna(0)
    maxdiff = float((ka - kb).abs().max())
    memb = (ka > 0) != (kb > 0)
    print(f"[{label}] 행수 {len(a)} vs {len(b)}, "
          f"최대 비중차 {maxdiff:.3e}, 편입멤버십 상이 {int(memb.sum())}건")
    return maxdiff, int(memb.sum())


def main():
    print("=" * 64)
    print("항목3  차단 적용 후 지수 영향 실측 (격리 재실행)")
    print("=" * 64)
    print("[1] 원본 팩터로 체인 재구성(결정성/기준선 확인)")
    w_orig = chain("orig", ROOT / "data" / "factors")
    print("[2] 블록 팩터로 체인 재구성")
    w_block = chain("blocked", INTEG / "factors_blocked")

    print("\n--- 비교 ---")
    base_committed = ROOT / "data" / "index" / "index_weights_quarterly.csv"
    compare(w_orig, base_committed, "원본재구성 vs 커밋본(결정성)")
    md, mm = compare(w_block, w_orig, "블록 vs 원본재구성(차단 순영향)")

    # CLS 편입 여부 비교
    for tag, wp in [("orig", w_orig), ("blocked", w_block)]:
        w = pd.read_csv(wp); cls = w[w.ticker.str.upper() == "CLS"]
        print(f"CLS 편입({tag}): {len(cls)}개 스냅샷",
              list(cls["snapshot_date"]) if len(cls) else "")
    print(f"\n결론: 블록 적용 순영향 = 최대비중차 {md:.3e}, 멤버십변화 {mm}건")


if __name__ == "__main__":
    main()
