"""
AI Infrastructure Custom Index
Index Weight & Constituent Builder

파이프라인 흐름
---------------
⑧ Factor Score → ⑨ Ranking (03_Methodology/01_build_factor_scores.py)
        │
        ▼
⑩ Weight            : 점수 기반 가중 + 단일 종목 상한(cap)
⑪ Custom Index      : 리밸런싱 시점별 최종 편입종목 + 비중 확정
⑫ Quarterly Rebal.  : 모든 분기 스냅샷을 리밸런싱 시점으로 처리

입력
----
data/scores/factor_scores_quarterly.csv

출력
----
data/index/index_weights_quarterly.csv   전체 리밸런싱 시점 편입종목 + 비중
data/index/index_weights_latest.csv       최신 리밸런싱 시점 편입종목 + 비중
data/index/index_rebalance_summary.csv    리밸런싱 시점별 요약
data/index/index_construction_metadata.json

비중 산정 규칙
--------------
1) 각 리밸런싱 시점에서 factor_rank 상위 N종목(기본 30) 선택
2) raw weight = factor_score / Σ factor_score  (점수 기반 가중)
3) 단일 종목 상한(cap, 기본 10%)을 초과하는 종목은 cap으로 고정하고,
   초과분을 미고정 종목에 점수 비례로 재분배 (waterfall 반복, 수렴까지)
4) 최종 비중 합계는 1.0(=100%)

주의
----
이 단계는 지수의 "구성(편입종목·비중)"을 확정합니다.
지수 레벨(수익률 기반 값) 시계열은 과거 가격 데이터 확보 후
05_Backtest 단계에서 별도로 계산합니다.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


# ============================================================
# 프로젝트 경로
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_INPUT_PATH = (
    PROJECT_ROOT / "data" / "scores" / "factor_scores_quarterly.csv"
)

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "index"


# ============================================================
# 컬럼 후보명
# ============================================================

DATE_COLUMN_ALIASES = [
    "snapshot_date",
    "rebalance_date",
    "as_of_date",
    "date",
]

TICKER_COLUMN_ALIASES = [
    "ticker",
    "symbol",
]

SCORE_COLUMN_ALIASES = [
    "factor_score",
    "composite_score",
    "score",
]

RANK_COLUMN_ALIASES = [
    "factor_rank",
    "rank",
]

COMPANY_COLUMN_ALIASES = [
    "entity_name",
    "company_name",
    "name",
]

# 있으면 결과에 함께 담을 메타데이터 컬럼
OPTIONAL_METADATA_COLUMNS = [
    "cik",
    "sub_theme",
    "theme",
    "sector",
    "industry",
    "available_factor_count",
    "revenue_growth",
    "operating_margin",
    "roa",
    "debt_ratio",
    "factor_score_percentile",
]


# ============================================================
# 로깅
# ============================================================

def configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ============================================================
# 유틸리티
# ============================================================

def find_column(
    df: pd.DataFrame,
    aliases: list[str],
    required: bool = True,
) -> str | None:
    """여러 후보 컬럼명 중 실제 존재하는 컬럼을 반환합니다."""

    lower_map = {
        str(column).lower().strip(): column
        for column in df.columns
    }

    for alias in aliases:
        normalized = alias.lower().strip()

        if normalized in lower_map:
            return lower_map[normalized]

    if required:
        raise KeyError(
            f"필요한 컬럼을 찾지 못했습니다.\n"
            f"후보: {aliases}\n"
            f"현재 컬럼: {list(df.columns)}"
        )

    return None


def apply_weight_cap(
    scores: np.ndarray,
    cap: float,
    tolerance: float = 1e-12,
    max_iterations: int = 1000,
) -> np.ndarray:
    """
    점수 비례 비중에 단일 종목 상한(cap)을 적용합니다.

    Waterfall 방식
    --------------
    - cap을 초과하는 종목은 cap으로 고정
    - 남은 비중(1 - 고정합)을 미고정 종목에 점수 비례로 재분배
    - 더 이상 cap을 넘는 종목이 없을 때까지 반복

    cap * len(scores) < 1 이면 합계 1을 만들 수 없으므로 예외 처리합니다.
    """

    n = len(scores)

    if n == 0:
        return np.array([], dtype=float)

    if cap * n < 1.0 - tolerance:
        raise ValueError(
            f"cap({cap})과 종목 수({n})로는 비중 합 1.0을 만들 수 없습니다. "
            f"cap × N = {cap * n:.4f} < 1.0. cap을 높이거나 종목 수를 늘리세요."
        )

    scores = np.asarray(scores, dtype=float)

    # 점수가 모두 0/음수면 동일 가중으로 대체
    if not np.any(scores > 0):
        scores = np.ones(n, dtype=float)

    weights = scores / scores.sum()

    capped = np.zeros(n, dtype=bool)

    for _ in range(max_iterations):
        over = (weights > cap + tolerance) & (~capped)

        if not over.any():
            break

        capped = capped | (weights >= cap - tolerance)

        # cap 이상인 종목은 정확히 cap으로 고정
        weights[capped] = cap

        capped_total = weights[capped].sum()
        remaining = 1.0 - capped_total

        free = ~capped
        free_scores = scores[free]

        if free_scores.sum() <= 0 or remaining <= 0:
            # 재분배 대상이 없으면 균등 처리
            if free.any():
                weights[free] = remaining / free.sum()
            break

        weights[free] = remaining * (
            free_scores / free_scores.sum()
        )

    return weights


# ============================================================
# 데이터 로딩
# ============================================================

def load_scores(input_path: Path) -> pd.DataFrame:
    if not input_path.exists():
        raise FileNotFoundError(
            f"입력 파일을 찾을 수 없습니다: {input_path}"
        )

    logging.info("Factor Score 로딩: %s", input_path)

    if input_path.suffix.lower() == ".parquet":
        df = pd.read_parquet(input_path)
    else:
        df = pd.read_csv(input_path, low_memory=False)

    if df.empty:
        raise ValueError("입력 데이터가 비어 있습니다.")

    logging.info("원본: %s행, %s열", len(df), len(df.columns))

    return df


# ============================================================
# 지수 구성
# ============================================================

def build_index(
    df: pd.DataFrame,
    top_n: int,
    cap: float,
) -> tuple[pd.DataFrame, dict[str, str]]:
    date_col = find_column(df, DATE_COLUMN_ALIASES)
    ticker_col = find_column(df, TICKER_COLUMN_ALIASES)
    score_col = find_column(df, SCORE_COLUMN_ALIASES)
    rank_col = find_column(df, RANK_COLUMN_ALIASES, required=False)
    company_col = find_column(df, COMPANY_COLUMN_ALIASES, required=False)

    resolved = {
        "date": date_col,
        "ticker": ticker_col,
        "score": score_col,
        "rank": rank_col,
        "company": company_col,
    }

    prepared = df.copy()

    prepared[date_col] = pd.to_datetime(
        prepared[date_col], errors="coerce"
    )

    prepared[ticker_col] = (
        prepared[ticker_col].astype(str).str.strip().str.upper()
    )

    prepared[score_col] = pd.to_numeric(
        prepared[score_col], errors="coerce"
    )

    prepared = prepared.loc[
        prepared[date_col].notna()
        & prepared[ticker_col].notna()
        & prepared[ticker_col].ne("")
        & prepared[ticker_col].ne("NAN")
        & prepared[score_col].notna()
    ].copy()

    if prepared.empty:
        raise ValueError("유효한 점수 데이터가 없습니다.")

    frames: list[pd.DataFrame] = []

    for rebalance_date, group in prepared.groupby(date_col):
        group = group.copy()

        # 종목 중복 시 최고 점수만 유지
        group = (
            group.sort_values(score_col, ascending=False)
            .drop_duplicates(subset=[ticker_col], keep="first")
        )

        # 상위 N 선택 (rank 있으면 rank, 없으면 score 기준)
        if rank_col is not None:
            group["_rank"] = pd.to_numeric(
                group[rank_col], errors="coerce"
            )
            group = group.sort_values(
                ["_rank", score_col],
                ascending=[True, False],
            )
        else:
            group = group.sort_values(score_col, ascending=False)

        selected = group.head(top_n).copy()

        n_selected = len(selected)

        if n_selected == 0:
            continue

        # cap × N < 1 인 경우(종목 수 부족) 해당 시점 cap을 완화
        effective_cap = cap
        if cap * n_selected < 1.0:
            effective_cap = 1.0 / n_selected
            logging.warning(
                "%s: 종목 %s개, cap %.1f%%로는 100%% 불가 → "
                "해당 시점 cap을 %.2f%%(=1/N)로 완화",
                pd.Timestamp(rebalance_date).date(),
                n_selected,
                cap * 100,
                effective_cap * 100,
            )

        raw_scores = selected[score_col].to_numpy(dtype=float)

        raw_weights = (
            raw_scores / raw_scores.sum()
            if raw_scores.sum() > 0
            else np.full(n_selected, 1.0 / n_selected)
        )

        final_weights = apply_weight_cap(
            scores=raw_scores,
            cap=effective_cap,
        )

        selected["raw_weight"] = raw_weights
        selected["weight"] = final_weights
        selected["weight_capped"] = (
            final_weights >= effective_cap - 1e-9
        )
        selected["effective_cap"] = effective_cap
        selected["n_constituents"] = n_selected

        # 리밸런싱 시점 내 최종 비중 순위
        selected["index_rank"] = (
            pd.Series(final_weights, index=selected.index)
            .rank(method="first", ascending=False)
            .astype(int)
        )

        frames.append(selected)

    if not frames:
        raise ValueError("편입 종목이 하나도 산출되지 않았습니다.")

    index_df = pd.concat(frames, ignore_index=True)

    index_df = index_df.sort_values(
        [date_col, "index_rank"],
        ascending=[True, True],
    ).reset_index(drop=True)

    return index_df, resolved


def build_output(
    index_df: pd.DataFrame,
    resolved: dict[str, str | None],
) -> pd.DataFrame:
    date_col = str(resolved["date"])
    ticker_col = str(resolved["ticker"])
    score_col = str(resolved["score"])
    company_col = resolved.get("company")

    ordered = [date_col, ticker_col]

    if company_col and company_col in index_df.columns:
        ordered.append(company_col)

    for column in OPTIONAL_METADATA_COLUMNS:
        if column in index_df.columns and column not in ordered:
            ordered.append(column)

    for column in [
        score_col,
        "raw_weight",
        "weight",
        "weight_capped",
        "effective_cap",
        "index_rank",
        "n_constituents",
    ]:
        if column in index_df.columns and column not in ordered:
            ordered.append(column)

    ordered = [c for c in ordered if c in index_df.columns]

    return index_df[ordered].copy()


def build_rebalance_summary(
    index_df: pd.DataFrame,
    date_col: str,
) -> pd.DataFrame:
    summary = (
        index_df.groupby(date_col)
        .agg(
            n_constituents=("weight", "size"),
            total_weight=("weight", "sum"),
            max_weight=("weight", "max"),
            min_weight=("weight", "min"),
            n_capped=("weight_capped", "sum"),
            effective_cap=("effective_cap", "first"),
        )
        .reset_index()
    )

    # 상위 5종목 집중도(HHI 대용)
    top5 = (
        index_df.sort_values("weight", ascending=False)
        .groupby(date_col)
        .head(5)
        .groupby(date_col)["weight"]
        .sum()
        .rename("top5_weight")
        .reset_index()
    )

    hhi = (
        index_df.assign(_w2=index_df["weight"] ** 2)
        .groupby(date_col)["_w2"]
        .sum()
        .rename("hhi")
        .reset_index()
    )

    summary = summary.merge(top5, on=date_col, how="left")
    summary = summary.merge(hhi, on=date_col, how="left")

    # 유효 종목수 = 1 / HHI
    summary["effective_n"] = 1.0 / summary["hhi"]

    return summary


def save_metadata(
    output_dir: Path,
    input_path: Path,
    top_n: int,
    cap: float,
    latest_date: pd.Timestamp,
    latest_count: int,
    n_rebalances: int,
) -> None:
    metadata: dict[str, Any] = {
        "input_file": str(input_path),
        "weight_method": "score_proportional_with_cap",
        "top_n": top_n,
        "single_name_cap": cap,
        "cap_algorithm": "iterative_waterfall_redistribution",
        "n_rebalance_dates": n_rebalances,
        "latest_rebalance_date": str(latest_date.date()),
        "latest_constituent_count": latest_count,
        "note": (
            "지수 구성(편입종목·비중) 확정 단계. "
            "지수 레벨 시계열은 05_Backtest에서 가격 데이터로 계산."
        ),
    }

    path = output_dir / "index_construction_metadata.json"

    with path.open("w", encoding="utf-8") as file:
        json.dump(metadata, file, ensure_ascii=False, indent=2)


# ============================================================
# 실행
# ============================================================

def run(
    input_path: Path,
    output_dir: Path,
    top_n: int,
    cap: float,
    overwrite: bool,
) -> None:
    if top_n < 1:
        raise ValueError("top_n은 1 이상이어야 합니다.")

    if not (0 < cap <= 1.0):
        raise ValueError("cap은 (0, 1] 범위여야 합니다.")

    output_dir.mkdir(parents=True, exist_ok=True)

    quarterly_path = output_dir / "index_weights_quarterly.csv"
    latest_path = output_dir / "index_weights_latest.csv"
    summary_path = output_dir / "index_rebalance_summary.csv"

    output_files = [quarterly_path, latest_path, summary_path]

    if not overwrite:
        existing = [p for p in output_files if p.exists()]

        if existing:
            raise FileExistsError(
                "출력 파일이 이미 존재합니다. --overwrite 사용:\n"
                + "\n".join(str(p) for p in existing)
            )

    df = load_scores(input_path)

    index_df, resolved = build_index(df, top_n=top_n, cap=cap)

    date_col = str(resolved["date"])

    output_df = build_output(index_df, resolved)

    summary_df = build_rebalance_summary(index_df, date_col)

    latest_date = output_df[date_col].max()

    latest_df = (
        output_df.loc[output_df[date_col].eq(latest_date)]
        .sort_values("index_rank")
        .reset_index(drop=True)
    )

    output_df.to_csv(
        quarterly_path, index=False, encoding="utf-8-sig"
    )
    latest_df.to_csv(
        latest_path, index=False, encoding="utf-8-sig"
    )
    summary_df.to_csv(
        summary_path, index=False, encoding="utf-8-sig"
    )

    save_metadata(
        output_dir=output_dir,
        input_path=input_path,
        top_n=top_n,
        cap=cap,
        latest_date=latest_date,
        latest_count=len(latest_df),
        n_rebalances=int(output_df[date_col].nunique()),
    )

    # 검증: 각 리밸런싱 시점 비중 합 ≈ 1
    weight_sums = output_df.groupby(date_col)["weight"].sum()
    max_dev = float((weight_sums - 1.0).abs().max())

    logging.info("=" * 60)
    logging.info("Index 구성 완료 (점수 기반 가중 + %.0f%% cap)", cap * 100)
    logging.info("리밸런싱 시점 수: %s", output_df[date_col].nunique())
    logging.info("전체 편입 레코드: %s행", len(output_df))
    logging.info("최신 리밸런싱: %s", latest_date.date())
    logging.info("최신 편입 종목수: %s", len(latest_df))
    logging.info("비중 합 최대 오차: %.2e", max_dev)
    logging.info("-" * 60)
    logging.info("전체 비중: %s", quarterly_path)
    logging.info("최신 비중: %s", latest_path)
    logging.info("리밸런싱 요약: %s", summary_path)
    logging.info("=" * 60)

    if max_dev > 1e-6:
        logging.warning(
            "일부 시점 비중 합이 1.0에서 벗어납니다 (max_dev=%.2e)",
            max_dev,
        )

    ticker_col = str(resolved["ticker"])
    company_col = resolved.get("company")

    preview_cols = [
        c
        for c in [
            ticker_col,
            company_col,
            "sub_theme",
            str(resolved["score"]),
            "weight",
            "weight_capped",
            "index_rank",
        ]
        if c is not None and c in latest_df.columns
    ]

    latest_display = latest_df[preview_cols].copy()
    if "weight" in latest_display.columns:
        latest_display["weight"] = (
            latest_display["weight"] * 100
        ).round(2).astype(str) + "%"

    print(f"\n최신 리밸런싱({latest_date.date()}) 편입 상위 10종목")
    print("-" * 80)
    print(latest_display.head(10).to_string(index=False))


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Factor Score 기반으로 AI Infrastructure Custom Index의 "
            "분기별 편입종목과 비중을 산출합니다."
        )
    )

    parser.add_argument(
        "--input-file",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="factor_scores_quarterly CSV 또는 Parquet 경로",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="지수 구성 결과 저장 폴더",
    )

    parser.add_argument(
        "--top-n",
        type=int,
        default=30,
        help="리밸런싱 시점별 편입 종목 수 (기본값: 30)",
    )

    parser.add_argument(
        "--cap",
        type=float,
        default=0.10,
        help="단일 종목 비중 상한 (기본값: 0.10 = 10%%)",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="기존 결과 파일 덮어쓰기",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="상세 로그 출력",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    configure_logging(verbose=args.verbose)

    run(
        input_path=args.input_file,
        output_dir=args.output_dir,
        top_n=args.top_n,
        cap=args.cap,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
