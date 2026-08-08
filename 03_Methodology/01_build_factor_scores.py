"""
AI Infrastructure Custom Index
Factor Score Builder

입력
----
data/pit/theme4ir_pit.csv

출력
----
data/scores/factor_scores_quarterly.csv
data/scores/factor_scores_latest.csv
data/scores/factor_score_summary.csv

점수 기준
---------
Revenue Growth   : 35%, 높을수록 좋음
Operating Margin : 30%, 높을수록 좋음
ROA              : 20%, 높을수록 좋음
Debt Ratio       : 15%, 낮을수록 좋음

결측치 처리
-----------
필수 팩터 4개 중 3개 이상 보유한 종목을 대상으로,
존재하는 팩터들의 가중치를 다시 비례 조정하여 최종 점수를 계산합니다.
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
    PROJECT_ROOT / "data" / "pit" / "theme4ir_pit.csv"
)

DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "data" / "scores"
)


# ============================================================
# 팩터 설정
# ============================================================

FACTOR_CONFIG: dict[str, dict[str, Any]] = {
    "revenue_growth": {
        "weight": 0.35,
        "higher_is_better": True,
        "aliases": [
            "revenue_growth",
            "revenue_growth_yoy",
            "revenue_yoy",
            "sales_growth",
            "revenue_growth_pct",
        ],
    },
    "operating_margin": {
        "weight": 0.30,
        "higher_is_better": True,
        "aliases": [
            "operating_margin",
            "op_margin",
            "operating_income_margin",
            "operating_margin_pct",
        ],
    },
    "roa": {
        "weight": 0.20,
        "higher_is_better": True,
        "aliases": [
            "roa",
            "return_on_assets",
            "return_on_asset",
            "roa_pct",
        ],
    },
    "debt_ratio": {
        "weight": 0.15,
        "higher_is_better": False,
        "aliases": [
            "debt_ratio",
            "debt_to_assets",
            "liabilities_to_assets",
            "total_debt_ratio",
            "debt_ratio_pct",
        ],
    },
}


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

COMPANY_COLUMN_ALIASES = [
    "company_name",
    "entity_name",
    "name",
]

ELIGIBLE_COLUMN_ALIASES = [
    "eligible",
    "is_eligible",
    "inclusion_flag",
    "included",
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
    """
    여러 후보 컬럼명 중 실제 데이터에 존재하는 컬럼을 반환합니다.
    대소문자 차이도 허용합니다.
    """

    lower_map = {
        str(column).lower().strip(): column
        for column in df.columns
    }

    for alias in aliases:
        normalized_alias = alias.lower().strip()

        if normalized_alias in lower_map:
            return lower_map[normalized_alias]

    if required:
        raise KeyError(
            f"필요한 컬럼을 찾지 못했습니다.\n"
            f"후보 컬럼: {aliases}\n"
            f"현재 컬럼: {list(df.columns)}"
        )

    return None


def parse_boolean_series(series: pd.Series) -> pd.Series:
    """
    문자열, 숫자, 불리언 형태의 편입 여부 컬럼을 Boolean으로 변환합니다.
    """

    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)

    normalized = (
        series.astype(str)
        .str.strip()
        .str.lower()
    )

    true_values = {
        "true",
        "1",
        "yes",
        "y",
        "eligible",
        "included",
        "include",
    }

    return normalized.isin(true_values)


def safe_numeric(series: pd.Series) -> pd.Series:
    """
    문자열 숫자, 쉼표, %, inf 등을 안전하게 숫자로 변환합니다.
    """

    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.strip()
    )

    numeric = pd.to_numeric(cleaned, errors="coerce")

    return numeric.replace(
        [np.inf, -np.inf],
        np.nan,
    )


def percentile_score(
    series: pd.Series,
    higher_is_better: bool,
) -> pd.Series:
    """
    분기 내 팩터 값을 0~100 Percentile Score로 변환합니다.

    값이 1개뿐인 경우 50점을 부여합니다.
    Debt Ratio처럼 낮을수록 좋은 팩터는 순위를 반대로 계산합니다.
    """

    result = pd.Series(
        np.nan,
        index=series.index,
        dtype=float,
    )

    valid = series.dropna()

    if valid.empty:
        return result

    if len(valid) == 1:
        result.loc[valid.index] = 50.0
        return result

    ascending = higher_is_better

    ranks = valid.rank(
        method="average",
        pct=True,
        ascending=ascending,
    )

    result.loc[valid.index] = ranks * 100

    return result


def detect_factor_columns(
    df: pd.DataFrame,
) -> dict[str, str]:
    """
    FACTOR_CONFIG의 alias를 이용해 실제 팩터 컬럼을 탐색합니다.
    """

    resolved: dict[str, str] = {}

    for factor_name, config in FACTOR_CONFIG.items():
        column = find_column(
            df=df,
            aliases=config["aliases"],
            required=False,
        )

        if column is not None:
            resolved[factor_name] = column

    missing = [
        factor
        for factor in FACTOR_CONFIG
        if factor not in resolved
    ]

    if missing:
        raise KeyError(
            "다음 팩터 컬럼을 찾지 못했습니다: "
            f"{missing}\n"
            f"현재 컬럼: {list(df.columns)}"
        )

    return resolved


# ============================================================
# 데이터 로딩
# ============================================================

def load_input_data(input_path: Path) -> pd.DataFrame:
    if not input_path.exists():
        raise FileNotFoundError(
            f"입력 파일을 찾을 수 없습니다: {input_path}"
        )

    logging.info("입력 파일 로딩: %s", input_path)

    if input_path.suffix.lower() == ".parquet":
        df = pd.read_parquet(input_path)
    else:
        df = pd.read_csv(
            input_path,
            low_memory=False,
        )

    if df.empty:
        raise ValueError("입력 데이터가 비어 있습니다.")

    logging.info(
        "원본 데이터: %s행, %s열",
        len(df),
        len(df.columns),
    )

    return df


# ============================================================
# 전처리
# ============================================================

def prepare_data(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, str]]:
    date_column = find_column(
        df,
        DATE_COLUMN_ALIASES,
    )

    ticker_column = find_column(
        df,
        TICKER_COLUMN_ALIASES,
    )

    eligible_column = find_column(
        df,
        ELIGIBLE_COLUMN_ALIASES,
    )

    company_column = find_column(
        df,
        COMPANY_COLUMN_ALIASES,
        required=False,
    )

    factor_columns = detect_factor_columns(df)

    prepared = df.copy()

    prepared[date_column] = pd.to_datetime(
        prepared[date_column],
        errors="coerce",
    )

    prepared[ticker_column] = (
        prepared[ticker_column]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    prepared["_eligible_boolean"] = parse_boolean_series(
        prepared[eligible_column]
    )

    prepared = prepared.loc[
        prepared["_eligible_boolean"]
    ].copy()

    prepared = prepared.loc[
        prepared[date_column].notna()
        & prepared[ticker_column].notna()
        & prepared[ticker_column].ne("")
        & prepared[ticker_column].ne("NAN")
    ].copy()

    for factor_name, source_column in factor_columns.items():
        prepared[factor_name] = safe_numeric(
            prepared[source_column]
        )

    prepared = prepared.sort_values(
        [date_column, ticker_column]
    ).reset_index(drop=True)

    resolved_columns = {
        "date": date_column,
        "ticker": ticker_column,
        "eligible": eligible_column,
        "company": company_column,
        **{
            f"source_{factor}": source
            for factor, source in factor_columns.items()
        },
    }

    logging.info(
        "Eligible 필터 후 데이터: %s행",
        len(prepared),
    )

    if prepared.empty:
        raise ValueError(
            "Eligible 조건을 통과한 데이터가 없습니다."
        )

    return prepared, resolved_columns


# ============================================================
# 팩터 점수 계산
# ============================================================

def calculate_factor_scores(
    df: pd.DataFrame,
    date_column: str,
) -> pd.DataFrame:
    scored = df.copy()

    for factor_name, config in FACTOR_CONFIG.items():
        score_column = f"{factor_name}_score"

        scored[score_column] = (
            scored.groupby(
                date_column,
                group_keys=False,
            )[factor_name]
            .apply(
                lambda series: percentile_score(
                    series=series,
                    higher_is_better=config[
                        "higher_is_better"
                    ],
                )
            )
        )

    return scored


def calculate_composite_score(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    사용 가능한 팩터만 이용하여 가중치를 다시 정규화합니다.

    예:
    Debt Ratio가 없는 경우
    0.35 + 0.30 + 0.20 = 0.85

    최종점수 =
    (성장점수×0.35 + 마진점수×0.30 + ROA점수×0.20) / 0.85
    """

    scored = df.copy()

    weighted_score_sum = pd.Series(
        0.0,
        index=scored.index,
    )

    available_weight_sum = pd.Series(
        0.0,
        index=scored.index,
    )

    available_factor_count = pd.Series(
        0,
        index=scored.index,
        dtype=int,
    )

    for factor_name, config in FACTOR_CONFIG.items():
        score_column = f"{factor_name}_score"
        weight = float(config["weight"])

        available = scored[score_column].notna()

        weighted_score_sum = weighted_score_sum.add(
            scored[score_column].fillna(0) * weight,
            fill_value=0,
        )

        available_weight_sum = available_weight_sum.add(
            available.astype(float) * weight,
            fill_value=0,
        )

        available_factor_count = (
            available_factor_count
            + available.astype(int)
        )

        effective_weight_column = (
            f"{factor_name}_effective_weight"
        )

        scored[effective_weight_column] = np.where(
            available_weight_sum > 0,
            np.nan,
            np.nan,
        )

    scored["available_factor_count"] = (
        available_factor_count
    )

    scored["available_weight_sum"] = (
        available_weight_sum
    )

    scored["factor_score"] = np.where(
        available_weight_sum > 0,
        weighted_score_sum / available_weight_sum,
        np.nan,
    )

    # 각 종목의 실제 적용 가중치
    for factor_name, config in FACTOR_CONFIG.items():
        score_column = f"{factor_name}_score"
        effective_weight_column = (
            f"{factor_name}_effective_weight"
        )

        factor_available = scored[score_column].notna()

        scored[effective_weight_column] = np.where(
            factor_available
            & scored["available_weight_sum"].gt(0),
            float(config["weight"])
            / scored["available_weight_sum"],
            0.0,
        )

    return scored


def add_rankings(
    df: pd.DataFrame,
    date_column: str,
) -> pd.DataFrame:
    ranked = df.copy()

    ranked["factor_rank"] = (
        ranked.groupby(date_column)["factor_score"]
        .rank(
            method="first",
            ascending=False,
        )
        .astype("Int64")
    )

    ranked["candidate_count"] = (
        ranked.groupby(date_column)["factor_score"]
        .transform("count")
        .astype("Int64")
    )

    ranked["factor_score_percentile"] = (
        ranked.groupby(date_column)["factor_score"]
        .rank(
            method="average",
            pct=True,
            ascending=True,
        )
        * 100
    )

    return ranked


# ============================================================
# 결과 정리
# ============================================================

def build_output_dataframe(
    df: pd.DataFrame,
    resolved_columns: dict[str, str | None],
) -> pd.DataFrame:
    date_column = str(resolved_columns["date"])
    ticker_column = str(resolved_columns["ticker"])
    company_column = resolved_columns.get("company")

    base_columns = [
        date_column,
        ticker_column,
    ]

    if (
        company_column is not None
        and company_column in df.columns
    ):
        base_columns.append(company_column)

    optional_metadata = [
        "cik",
        "exchange",
        "sector",
        "industry",
        "ai_infrastructure_theme",
        "primary_theme",
        "sub_theme",
        "theme",
        "information_age_days",
        "data_quality_score",
        "required_factor_count",
        "financial_warning",
        "pit_valid",
    ]

    for column in optional_metadata:
        if (
            column in df.columns
            and column not in base_columns
        ):
            base_columns.append(column)

    factor_value_columns = list(
        FACTOR_CONFIG.keys()
    )

    factor_score_columns = [
        f"{factor}_score"
        for factor in FACTOR_CONFIG
    ]

    effective_weight_columns = [
        f"{factor}_effective_weight"
        for factor in FACTOR_CONFIG
    ]

    result_columns = (
        base_columns
        + factor_value_columns
        + factor_score_columns
        + effective_weight_columns
        + [
            "available_factor_count",
            "available_weight_sum",
            "factor_score",
            "factor_score_percentile",
            "factor_rank",
            "candidate_count",
        ]
    )

    result_columns = [
        column
        for column in result_columns
        if column in df.columns
    ]

    output = df[result_columns].copy()

    output = output.sort_values(
        [date_column, "factor_rank"],
        ascending=[True, True],
    ).reset_index(drop=True)

    return output


def build_summary(
    scored: pd.DataFrame,
    date_column: str,
) -> pd.DataFrame:
    summary = (
        scored.groupby(date_column)
        .agg(
            candidate_count=(
                "factor_score",
                "count",
            ),
            mean_factor_score=(
                "factor_score",
                "mean",
            ),
            median_factor_score=(
                "factor_score",
                "median",
            ),
            min_factor_score=(
                "factor_score",
                "min",
            ),
            max_factor_score=(
                "factor_score",
                "max",
            ),
            three_factor_companies=(
                "available_factor_count",
                lambda series: int(
                    series.eq(3).sum()
                ),
            ),
            four_factor_companies=(
                "available_factor_count",
                lambda series: int(
                    series.eq(4).sum()
                ),
            ),
        )
        .reset_index()
    )

    return summary


def save_metadata(
    output_dir: Path,
    input_path: Path,
    latest_date: pd.Timestamp,
    latest_count: int,
) -> None:
    metadata = {
        "input_file": str(input_path),
        "latest_snapshot_date": str(
            latest_date.date()
        ),
        "latest_candidate_count": int(latest_count),
        "factor_method": "percentile_rank",
        "missing_factor_method": (
            "available factor weight renormalization"
        ),
        "factor_config": {
            factor_name: {
                "weight": config["weight"],
                "higher_is_better": config[
                    "higher_is_better"
                ],
            }
            for factor_name, config
            in FACTOR_CONFIG.items()
        },
    }

    metadata_path = (
        output_dir / "factor_score_metadata.json"
    )

    with metadata_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            metadata,
            file,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# 실행
# ============================================================

def run(
    input_path: Path,
    output_dir: Path,
    min_required_factors: int,
    overwrite: bool,
) -> None:
    if min_required_factors < 1:
        raise ValueError(
            "min_required_factors는 1 이상이어야 합니다."
        )

    if min_required_factors > len(FACTOR_CONFIG):
        raise ValueError(
            "min_required_factors는 팩터 수보다 클 수 없습니다."
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    quarterly_output_path = (
        output_dir / "factor_scores_quarterly.csv"
    )

    latest_output_path = (
        output_dir / "factor_scores_latest.csv"
    )

    summary_output_path = (
        output_dir / "factor_score_summary.csv"
    )

    output_files = [
        quarterly_output_path,
        latest_output_path,
        summary_output_path,
    ]

    if not overwrite:
        existing = [
            path
            for path in output_files
            if path.exists()
        ]

        if existing:
            raise FileExistsError(
                "출력 파일이 이미 존재합니다. "
                "--overwrite 옵션을 사용하세요.\n"
                + "\n".join(
                    str(path)
                    for path in existing
                )
            )

    raw_df = load_input_data(input_path)

    prepared_df, resolved_columns = prepare_data(
        raw_df
    )

    date_column = str(resolved_columns["date"])

    scored_df = calculate_factor_scores(
        prepared_df,
        date_column=date_column,
    )

    scored_df = calculate_composite_score(
        scored_df
    )

    before_min_factor_filter = len(scored_df)

    scored_df = scored_df.loc[
        scored_df["available_factor_count"]
        >= min_required_factors
    ].copy()

    logging.info(
        "최소 팩터 수 필터: %s개 이상 | %s행 → %s행",
        min_required_factors,
        before_min_factor_filter,
        len(scored_df),
    )

    if scored_df.empty:
        raise ValueError(
            "팩터 수 조건을 통과한 종목이 없습니다."
        )

    scored_df = add_rankings(
        scored_df,
        date_column=date_column,
    )

    output_df = build_output_dataframe(
        scored_df,
        resolved_columns,
    )

    summary_df = build_summary(
        scored_df,
        date_column=date_column,
    )

    latest_date = output_df[date_column].max()

    latest_df = (
        output_df.loc[
            output_df[date_column].eq(latest_date)
        ]
        .sort_values("factor_rank")
        .reset_index(drop=True)
    )

    output_df.to_csv(
        quarterly_output_path,
        index=False,
        encoding="utf-8-sig",
    )

    latest_df.to_csv(
        latest_output_path,
        index=False,
        encoding="utf-8-sig",
    )

    summary_df.to_csv(
        summary_output_path,
        index=False,
        encoding="utf-8-sig",
    )

    save_metadata(
        output_dir=output_dir,
        input_path=input_path,
        latest_date=latest_date,
        latest_count=len(latest_df),
    )

    logging.info("=" * 60)
    logging.info("Factor Score 생성 완료")
    logging.info("전체 점수 데이터: %s행", len(output_df))
    logging.info(
        "리밸런싱 시점 수: %s",
        output_df[date_column].nunique(),
    )
    logging.info(
        "최신 Snapshot: %s",
        latest_date.date(),
    )
    logging.info(
        "최신 후보군: %s개",
        len(latest_df),
    )
    logging.info(
        "평균 Factor Score: %.2f",
        latest_df["factor_score"].mean(),
    )
    logging.info("-" * 60)
    logging.info(
        "전체 결과: %s",
        quarterly_output_path,
    )
    logging.info(
        "최신 결과: %s",
        latest_output_path,
    )
    logging.info(
        "요약 결과: %s",
        summary_output_path,
    )
    logging.info("=" * 60)

    preview_columns = [
        column
        for column in [
            resolved_columns["ticker"],
            resolved_columns.get("company"),
            "revenue_growth",
            "operating_margin",
            "roa",
            "debt_ratio",
            "available_factor_count",
            "factor_score",
            "factor_rank",
        ]
        if column is not None
        and column in latest_df.columns
    ]

    print("\n최신 Factor Score 상위 10개")
    print("-" * 80)
    print(
        latest_df[preview_columns]
        .head(10)
        .to_string(index=False)
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Theme4IR PIT 후보군의 분기별 "
            "Factor Score를 계산합니다."
        )
    )

    parser.add_argument(
        "--input-file",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=(
            "theme4ir_pit CSV 또는 Parquet 경로"
        ),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="점수 결과 저장 폴더",
    )

    parser.add_argument(
        "--min-required-factors",
        type=int,
        default=3,
        help=(
            "최종 점수 계산에 필요한 최소 팩터 수 "
            "(기본값: 3)"
        ),
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

    configure_logging(
        verbose=args.verbose
    )

    run(
        input_path=args.input_file,
        output_dir=args.output_dir,
        min_required_factors=(
            args.min_required_factors
        ),
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()