"""
04_build_pit_snapshot.py
============================================================
최종 AI 인프라 유니버스 100개 종목의 재무 팩터를 Point-in-Time(PIT)
기준으로 결합하고, 월말/분기말 리밸런싱용 스냅샷 패널을 생성합니다.

핵심 원칙
------------------------------------------------------------
- 재무정보는 시장에서 확인 가능해진 날짜(availability_date) 이후에만 사용
- 미래 공시를 과거 리밸런싱 시점에 사용하는 Look-ahead Bias 방지
- 각 리밸런싱 날짜마다 팩터별로 해당 날짜 이전에 공개된 최신 유효값을 선택
- 최종 유니버스 100개 종목만 처리

기본 입력
------------------------------------------------------------
data/classification/final_universe_100.parquet
  또는 final_universe_100.csv

data/factors/{CIK}.parquet

기본 출력
------------------------------------------------------------
data/pit/pit_factor_panel.parquet
data/pit/pit_factor_panel.csv
data/pit/pit_snapshot_monthly.parquet
data/pit/pit_snapshot_monthly.csv
data/pit/pit_snapshot_latest.parquet
data/pit/pit_snapshot_latest.csv
data/pit/pit_snapshot_summary.csv
data/pit/pit_snapshot_errors.csv
data/pit/pit_snapshot_run_log.csv

실행
------------------------------------------------------------
python 02_Data_Preprocessing/code/04_build_pit_snapshot.py --overwrite

기간 지정
------------------------------------------------------------
python 02_Data_Preprocessing/code/04_build_pit_snapshot.py ^
  --start-date 2016-01-01 ^
  --end-date 2026-07-20 ^
  --frequency monthly ^
  --overwrite

분기말 스냅샷
------------------------------------------------------------
python 02_Data_Preprocessing/code/04_build_pit_snapshot.py ^
  --frequency quarterly ^
  --overwrite
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


# ============================================================
# 1. 경로
# ============================================================

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]

DEFAULT_CLASSIFICATION_DIR = PROJECT_ROOT / "data" / "classification"
DEFAULT_UNIVERSE_PARQUET = (
    DEFAULT_CLASSIFICATION_DIR / "final_universe_100.parquet"
)
DEFAULT_UNIVERSE_CSV = (
    DEFAULT_CLASSIFICATION_DIR / "final_universe_100.csv"
)

DEFAULT_FACTOR_DIR = PROJECT_ROOT / "data" / "factors"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "pit"

PANEL_PARQUET = DEFAULT_OUTPUT_DIR / "pit_factor_panel.parquet"
PANEL_CSV = DEFAULT_OUTPUT_DIR / "pit_factor_panel.csv"

SNAPSHOT_PARQUET = DEFAULT_OUTPUT_DIR / "pit_snapshot_monthly.parquet"
SNAPSHOT_CSV = DEFAULT_OUTPUT_DIR / "pit_snapshot_monthly.csv"

LATEST_PARQUET = DEFAULT_OUTPUT_DIR / "pit_snapshot_latest.parquet"
LATEST_CSV = DEFAULT_OUTPUT_DIR / "pit_snapshot_latest.csv"

SUMMARY_CSV = DEFAULT_OUTPUT_DIR / "pit_snapshot_summary.csv"
ERRORS_CSV = DEFAULT_OUTPUT_DIR / "pit_snapshot_errors.csv"
RUN_LOG_CSV = DEFAULT_OUTPUT_DIR / "pit_snapshot_run_log.csv"


# ============================================================
# 2. 컬럼 후보
# ============================================================

CIK_COLUMNS = [
    "cik",
    "CIK",
]

TICKER_COLUMNS = [
    "ticker",
    "symbol",
]

ENTITY_COLUMNS = [
    "entity_name",
    "company_name",
    "name",
]

# 실제 시장에 알려진 날짜로 사용할 후보.
# accepted_datetime가 있으면 가장 우선한다.
AVAILABILITY_DATE_COLUMNS = [
    "accepted_datetime",
    "accepted_date",
    "acceptance_datetime",
    "filing_date",
    "filed",
    "filing_datetime",
    "published_date",
    "availability_date",
]

# 재무제표 기준기간 종료일
PERIOD_END_COLUMNS = [
    "period_end",
    "report_date",
    "fiscal_period_end",
    "end_date",
    "period_date",
]

FORM_COLUMNS = [
    "form",
    "form_type",
    "filing_type",
]

ACCESSION_COLUMNS = [
    "accession_number",
    "accession",
    "accession_no",
]

PIT_VALID_COLUMNS = [
    "pit_valid",
    "is_pit_valid",
]

# 실제 지수 스코어링에 사용하는 재무 팩터 컬럼입니다.
# PIT 스냅샷에서는 각 컬럼별로 기준일 이전의 최신 유효값을 독립적으로 선택합니다.
FACTOR_VALUE_COLUMNS = [
    "revenue_growth",
    "operating_income_growth",
    "net_income_growth",
    "asset_growth",
    "operating_margin",
    "net_margin",
    "roa",
    "roe",
    "debt_ratio",
    "debt_to_equity",
    "current_ratio",
    "ocf_to_assets",
    "free_cash_flow_proxy",
]

FACTOR_COLUMNS = FACTOR_VALUE_COLUMNS + [
    "factor_available_count",
    "financial_warning",
    "data_quality_score",
]


# ============================================================
# 3. 로그
# ============================================================

@dataclass
class RunLog:
    universe_count: int
    factor_files_found: int
    successful_entities: int
    failed_entities: int
    panel_rows: int
    rebalance_dates: int
    snapshot_rows: int
    latest_rows: int
    frequency: str
    start_date: str
    end_date: str
    elapsed_seconds: float
    universe_file: str
    factor_dir: str
    output_dir: str


# ============================================================
# 4. 공통 도우미
# ============================================================

def clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""

    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "<na>", "nat"}:
        return ""

    return text


def normalize_ticker(value: object) -> str:
    text = clean_text(value).upper()
    return re.sub(r"[^A-Z0-9.\-]", "", text)


def normalize_cik(value: object) -> str:
    text = clean_text(value)
    digits = re.sub(r"\D", "", text)

    if not digits:
        return ""

    return digits.zfill(10)


def first_existing_column(
    columns: Iterable[str],
    candidates: Iterable[str],
) -> str | None:
    column_set = set(columns)

    for candidate in candidates:
        if candidate in column_set:
            return candidate

    return None


def parse_datetime_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(
        series,
        errors="coerce",
        utc=True,
    ).dt.tz_convert(None)


def parse_bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)

    text = series.astype(str).str.strip().str.lower()
    return text.isin(
        {
            "true",
            "1",
            "yes",
            "y",
            "t",
        }
    )


def resolve_universe_file(
    explicit_path: Path | None,
) -> Path:
    if explicit_path is not None:
        path = explicit_path.resolve()

        if not path.exists():
            raise FileNotFoundError(
                f"유니버스 파일이 없습니다: {path}"
            )

        return path

    if DEFAULT_UNIVERSE_PARQUET.exists():
        return DEFAULT_UNIVERSE_PARQUET

    if DEFAULT_UNIVERSE_CSV.exists():
        return DEFAULT_UNIVERSE_CSV

    raise FileNotFoundError(
        "최종 유니버스 파일을 찾지 못했습니다. "
        f"{DEFAULT_UNIVERSE_PARQUET} 또는 "
        f"{DEFAULT_UNIVERSE_CSV}가 필요합니다."
    )


def load_universe(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        universe = pd.read_parquet(path)
    else:
        universe = pd.read_csv(
            path,
            dtype={"cik": "string"},
        )

    required = [
        "ticker",
        "cik",
    ]
    missing = [
        column
        for column in required
        if column not in universe.columns
    ]

    if missing:
        raise ValueError(
            "최종 유니버스 필수 컬럼 누락: "
            + ", ".join(missing)
        )

    universe = universe.copy()
    universe["ticker"] = universe["ticker"].map(
        normalize_ticker
    )
    universe["cik"] = universe["cik"].map(
        normalize_cik
    )

    universe = universe[
        universe["ticker"].ne("")
        & universe["cik"].ne("")
    ].copy()

    if "selected_for_index" in universe.columns:
        selected_mask = parse_bool_series(
            universe["selected_for_index"]
        )

        # 파일이 이미 최종 100개만 담고 있으면 모두 유지
        if selected_mask.any():
            universe = universe[selected_mask].copy()

    if "universe_rank" in universe.columns:
        universe["_rank_sort"] = pd.to_numeric(
            universe["universe_rank"],
            errors="coerce",
        ).fillna(999999)
    else:
        universe["_rank_sort"] = 999999

    universe = (
        universe.sort_values(
            ["_rank_sort", "ticker"],
            ascending=[True, True],
        )
        .drop_duplicates("ticker", keep="first")
        .drop(columns="_rank_sort")
        .reset_index(drop=True)
    )

    return universe


def find_factor_file(
    factor_dir: Path,
    cik: str,
) -> Path | None:
    candidates = [
        factor_dir / f"{cik}.parquet",
        factor_dir / f"{int(cik)}.parquet",
        factor_dir / f"CIK{cik}.parquet",
    ]

    for path in candidates:
        if path.exists():
            return path

    # 파일명이 예상 형식과 다를 경우 마지막 수단으로 검색
    matches = list(
        factor_dir.glob(f"*{cik}*.parquet")
    )

    if not matches:
        matches = list(
            factor_dir.glob(f"*{int(cik)}*.parquet")
        )

    return matches[0] if matches else None


# ============================================================
# 5. Factor 파일 표준화
# ============================================================

def standardize_factor_file(
    factor_file: Path,
    universe_row: pd.Series,
) -> pd.DataFrame:
    factors = pd.read_parquet(factor_file)

    if factors.empty:
        raise ValueError("Factor 파일이 비어 있습니다.")

    factors = factors.copy()

    availability_column = first_existing_column(
        factors.columns,
        AVAILABILITY_DATE_COLUMNS,
    )

    if availability_column is None:
        raise KeyError(
            "공시 이용가능일 컬럼을 찾지 못했습니다. "
            f"후보: {AVAILABILITY_DATE_COLUMNS}"
        )

    period_end_column = first_existing_column(
        factors.columns,
        PERIOD_END_COLUMNS,
    )
    form_column = first_existing_column(
        factors.columns,
        FORM_COLUMNS,
    )
    accession_column = first_existing_column(
        factors.columns,
        ACCESSION_COLUMNS,
    )
    pit_valid_column = first_existing_column(
        factors.columns,
        PIT_VALID_COLUMNS,
    )

    factors["availability_date"] = parse_datetime_series(
        factors[availability_column]
    )

    if period_end_column is not None:
        factors["period_end"] = parse_datetime_series(
            factors[period_end_column]
        )
    else:
        factors["period_end"] = pd.NaT

    if form_column is not None:
        factors["form"] = (
            factors[form_column]
            .astype(str)
            .str.strip()
            .str.upper()
        )
    else:
        factors["form"] = ""

    if accession_column is not None:
        factors["accession_number"] = (
            factors[accession_column]
            .astype(str)
            .str.strip()
        )
    else:
        factors["accession_number"] = ""

    # Factor Engine에서 이미 PIT 유효성 검사를 수행했다면 활용
    if pit_valid_column is not None:
        factors = factors[
            parse_bool_series(
                factors[pit_valid_column]
            )
        ].copy()

    # 이용가능일이 없는 행은 PIT 패널에 사용할 수 없음
    factors = factors[
        factors["availability_date"].notna()
    ].copy()

    if factors.empty:
        raise ValueError(
            "유효한 availability_date를 가진 행이 없습니다."
        )

    # 10-K/A, 10-Q/A 중심. 다른 양식뿐인 파일은 제거하지 않고 유지한다.
    supported_forms = {
        "10-K",
        "10-K/A",
        "10-Q",
        "10-Q/A",
        "20-F",
        "20-F/A",
        "40-F",
        "40-F/A",
    }

    supported_mask = factors["form"].isin(
        supported_forms
    )

    if supported_mask.any():
        factors = factors[supported_mask].copy()

    # 이용가능일이 재무기간 종료일보다 빠르면 비정상 행
    valid_timing = (
        factors["period_end"].isna()
        | (
            factors["availability_date"]
            >= factors["period_end"]
        )
    )
    factors = factors[valid_timing].copy()

    if factors.empty:
        raise ValueError(
            "PIT 날짜 검증 후 남은 행이 없습니다."
        )

    # 유니버스 메타데이터 부착
    metadata_columns = [
        "ticker",
        "cik",
        "entity_name",
        "theme",
        "sub_theme",
        "candidate_score",
        "selection_score",
        "universe_rank",
    ]

    for column in metadata_columns:
        if column in universe_row.index:
            factors[column] = universe_row[column]

    factors["ticker"] = normalize_ticker(
        universe_row["ticker"]
    )
    factors["cik"] = normalize_cik(
        universe_row["cik"]
    )
    factors["factor_file"] = str(factor_file)

    # 같은 공시/날짜 중복 제거
    dedup_columns = [
        "ticker",
        "availability_date",
        "period_end",
        "form",
        "accession_number",
    ]

    factors = (
        factors.sort_values(
            [
                "availability_date",
                "period_end",
            ],
            ascending=[
                True,
                True,
            ],
            na_position="first",
        )
        .drop_duplicates(
            dedup_columns,
            keep="last",
        )
        .reset_index(drop=True)
    )

    # 결과 컬럼 정리: 식별자와 날짜를 앞쪽에 배치
    leading_columns = [
        "ticker",
        "cik",
        "entity_name",
        "theme",
        "sub_theme",
        "universe_rank",
        "candidate_score",
        "selection_score",
        "availability_date",
        "period_end",
        "form",
        "accession_number",
    ]

    ordered_columns = [
        column
        for column in leading_columns
        if column in factors.columns
    ]

    ordered_columns += [
        column
        for column in FACTOR_COLUMNS
        if (
            column in factors.columns
            and column not in ordered_columns
        )
    ]

    ordered_columns += [
        column
        for column in factors.columns
        if column not in ordered_columns
    ]

    return factors[ordered_columns].copy()


def build_factor_panel(
    universe: pd.DataFrame,
    factor_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    panel_parts: list[pd.DataFrame] = []
    errors: list[dict[str, object]] = []
    files_found = 0

    for _, universe_row in universe.iterrows():
        ticker = normalize_ticker(
            universe_row["ticker"]
        )
        cik = normalize_cik(
            universe_row["cik"]
        )

        factor_file = find_factor_file(
            factor_dir,
            cik,
        )

        if factor_file is None:
            errors.append(
                {
                    "ticker": ticker,
                    "cik": cik,
                    "status": "failed",
                    "error_type": "FileNotFoundError",
                    "error_message": (
                        "CIK에 해당하는 Factor parquet를 "
                        "찾지 못했습니다."
                    ),
                    "factor_file": "",
                }
            )
            continue

        files_found += 1

        try:
            standardized = standardize_factor_file(
                factor_file,
                universe_row,
            )
            panel_parts.append(standardized)

        except Exception as exc:
            errors.append(
                {
                    "ticker": ticker,
                    "cik": cik,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "factor_file": str(factor_file),
                }
            )

    if panel_parts:
        panel = pd.concat(
            panel_parts,
            ignore_index=True,
            sort=False,
        )
    else:
        panel = pd.DataFrame()

    errors_df = pd.DataFrame(
        errors,
        columns=[
            "ticker",
            "cik",
            "status",
            "error_type",
            "error_message",
            "factor_file",
        ],
    )

    return panel, errors_df, files_found


# ============================================================
# 6. PIT 스냅샷 생성
# ============================================================

def frequency_to_pandas_rule(
    frequency: str,
) -> str:
    mapping = {
        "monthly": "ME",
        "quarterly": "QE",
        "yearly": "YE",
    }
    return mapping[frequency]


def build_rebalance_dates(
    panel: pd.DataFrame,
    start_date: str | None,
    end_date: str | None,
    frequency: str,
) -> pd.DatetimeIndex:
    if panel.empty:
        return pd.DatetimeIndex([])

    available_min = panel[
        "availability_date"
    ].min()
    available_max = panel[
        "availability_date"
    ].max()

    start = (
        pd.Timestamp(start_date)
        if start_date
        else pd.Timestamp(available_min)
    )
    end = (
        pd.Timestamp(end_date)
        if end_date
        else pd.Timestamp(available_max)
    )

    if start > end:
        raise ValueError(
            f"start_date({start.date()})가 "
            f"end_date({end.date()})보다 늦습니다."
        )

    rule = frequency_to_pandas_rule(
        frequency
    )

    dates = pd.date_range(
        start=start,
        end=end,
        freq=rule,
    )

    # 기간이 너무 짧아 date_range가 비어도 마지막 날짜를 하나 생성
    if len(dates) == 0:
        dates = pd.DatetimeIndex([end])

    return dates


def build_pit_snapshot(
    panel: pd.DataFrame,
    universe: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex,
) -> pd.DataFrame:
    """리밸런싱 날짜별 PIT 재무 팩터 스냅샷을 생성합니다.

    중요:
    - 공시 메타데이터는 기준일 이전의 최신 공시 행을 사용합니다.
    - 재무 팩터는 행 전체가 아니라 팩터별로 기준일 이전의 최신 유효값을
      독립적으로 선택합니다.
    - 따라서 최신 공시 행의 일부 팩터가 NaN이어도 과거에 공개된 최신
      유효값을 유지하며, 미래 정보는 사용하지 않습니다.
    """
    if panel.empty or len(rebalance_dates) == 0:
        return pd.DataFrame()

    snapshot_parts: list[pd.DataFrame] = []

    universe_metadata_columns = [
        "ticker",
        "cik",
        "entity_name",
        "theme",
        "sub_theme",
        "universe_rank",
        "candidate_score",
        "selection_score",
    ]

    rebalance_frame = pd.DataFrame(
        {"snapshot_date": pd.DatetimeIndex(rebalance_dates)}
    ).sort_values("snapshot_date").reset_index(drop=True)

    for _, universe_row in universe.iterrows():
        ticker = normalize_ticker(universe_row["ticker"])

        company_history = panel[
            panel["ticker"] == ticker
        ].copy()

        if company_history.empty:
            continue

        company_history = company_history.sort_values(
            ["availability_date", "period_end"],
            ascending=[True, True],
            na_position="first",
        ).reset_index(drop=True)

        # ----------------------------------------------------
        # 1) 기준일 이전 최신 공시 메타데이터 선택
        # ----------------------------------------------------
        # 같은 availability_date에 여러 행이 있으면 메타데이터용으로
        # 마지막 행을 사용합니다. 팩터 값은 아래에서 컬럼별로 별도 처리합니다.
        latest_filing_history = (
            company_history
            .drop_duplicates("availability_date", keep="last")
            .sort_values("availability_date")
        )

        merged = pd.merge_asof(
            rebalance_frame,
            latest_filing_history,
            left_on="snapshot_date",
            right_on="availability_date",
            direction="backward",
            allow_exact_matches=True,
        )

        # 첫 공시 이전에는 사용할 수 있는 공개 정보가 없으므로 제거합니다.
        merged = merged[
            merged["availability_date"].notna()
        ].copy()

        if merged.empty:
            continue

        # ----------------------------------------------------
        # 2) 팩터별 최신 유효값 선택
        # ----------------------------------------------------
        # 최신 공시 행 전체를 그대로 쓰면 해당 행의 NaN 때문에 과거의
        # 유효 팩터가 사라집니다. 각 팩터를 독립적으로 backward merge하여
        # 기준일 이전에 공개된 최신 non-null 값을 가져옵니다.
        for factor in FACTOR_VALUE_COLUMNS:
            if factor not in company_history.columns:
                merged[factor] = np.nan
                continue

            factor_history = company_history.loc[
                company_history[factor].notna(),
                ["availability_date", factor],
            ].copy()

            if factor_history.empty:
                merged[factor] = np.nan
                continue

            factor_history[factor] = pd.to_numeric(
                factor_history[factor],
                errors="coerce",
            )
            factor_history = factor_history[
                factor_history[factor].notna()
            ].copy()

            if factor_history.empty:
                merged[factor] = np.nan
                continue

            factor_history = (
                factor_history
                .sort_values("availability_date")
                .drop_duplicates("availability_date", keep="last")
            )

            factor_snapshot = pd.merge_asof(
                merged[["snapshot_date"]].sort_values("snapshot_date"),
                factor_history,
                left_on="snapshot_date",
                right_on="availability_date",
                direction="backward",
                allow_exact_matches=True,
            )

            # merged의 행 순서는 snapshot_date 기준이므로 그대로 대입합니다.
            merged[factor] = factor_snapshot[factor].to_numpy()

        # 실제 확보된 재무 팩터 개수를 다시 계산합니다.
        available_factor_columns = [
            column
            for column in FACTOR_VALUE_COLUMNS
            if column in merged.columns
        ]
        merged["factor_available_count"] = (
            merged[available_factor_columns]
            .notna()
            .sum(axis=1)
            .astype(int)
        )

        # merge 결과의 식별자 결측 방지
        for column in universe_metadata_columns:
            if column in universe_row.index:
                if column not in merged.columns:
                    merged[column] = universe_row[column]
                else:
                    merged[column] = merged[column].fillna(
                        universe_row[column]
                    )

        merged["ticker"] = ticker
        merged["cik"] = normalize_cik(universe_row["cik"])

        # 핵심 PIT 검증 플래그
        merged["pit_valid"] = (
            merged["availability_date"]
            <= merged["snapshot_date"]
        )

        merged["information_age_days"] = (
            merged["snapshot_date"]
            - merged["availability_date"]
        ).dt.days

        merged["stale_365d"] = (
            merged["information_age_days"] > 365
        )

        snapshot_parts.append(merged)

    if not snapshot_parts:
        return pd.DataFrame()

    snapshot = pd.concat(
        snapshot_parts,
        ignore_index=True,
        sort=False,
    )

    snapshot = snapshot[
        snapshot["pit_valid"]
    ].copy()

    snapshot = snapshot.sort_values(
        ["snapshot_date", "universe_rank", "ticker"],
        ascending=[True, True, True],
        na_position="last",
    ).reset_index(drop=True)

    leading_columns = [
        "snapshot_date",
        "ticker",
        "cik",
        "entity_name",
        "theme",
        "sub_theme",
        "universe_rank",
        "availability_date",
        "period_end",
        "form",
        "accession_number",
        "information_age_days",
        "stale_365d",
        "pit_valid",
    ]

    ordered_columns = [
        column
        for column in leading_columns
        if column in snapshot.columns
    ]

    ordered_columns += [
        column
        for column in FACTOR_COLUMNS
        if (
            column in snapshot.columns
            and column not in ordered_columns
        )
    ]

    ordered_columns += [
        column
        for column in snapshot.columns
        if column not in ordered_columns
    ]

    return snapshot[ordered_columns].copy()


def build_latest_snapshot(
    snapshot: pd.DataFrame,
) -> pd.DataFrame:
    if snapshot.empty:
        return pd.DataFrame()

    latest_date = snapshot[
        "snapshot_date"
    ].max()

    latest = snapshot[
        snapshot["snapshot_date"] == latest_date
    ].copy()

    return latest.sort_values(
        [
            "universe_rank",
            "ticker",
        ],
        ascending=[
            True,
            True,
        ],
        na_position="last",
    ).reset_index(drop=True)


# ============================================================
# 7. 요약
# ============================================================

def build_summary(
    universe: pd.DataFrame,
    panel: pd.DataFrame,
    snapshot: pd.DataFrame,
    errors: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    themes = (
        universe["theme"]
        .fillna("Unknown")
        .astype(str)
        .unique()
        .tolist()
        if "theme" in universe.columns
        else ["TOTAL"]
    )

    for theme in themes:
        if "theme" in universe.columns:
            universe_mask = (
                universe["theme"].fillna("Unknown")
                == theme
            )
            universe_count = int(
                universe_mask.sum()
            )
        else:
            universe_count = len(universe)

        panel_count = (
            int(
                panel.loc[
                    panel["theme"].fillna("Unknown")
                    == theme,
                    "ticker",
                ].nunique()
            )
            if (
                not panel.empty
                and "theme" in panel.columns
            )
            else 0
        )

        latest_count = 0

        if (
            not snapshot.empty
            and "theme" in snapshot.columns
        ):
            latest_date = snapshot[
                "snapshot_date"
            ].max()
            latest_count = int(
                snapshot.loc[
                    (
                        snapshot["snapshot_date"]
                        == latest_date
                    )
                    & (
                        snapshot["theme"]
                        .fillna("Unknown")
                        == theme
                    ),
                    "ticker",
                ].nunique()
            )

        rows.append(
            {
                "theme": theme,
                "universe_count": universe_count,
                "entities_with_factor_history": panel_count,
                "entities_in_latest_snapshot": latest_count,
            }
        )

    latest_total = 0
    if not snapshot.empty:
        latest_date = snapshot[
            "snapshot_date"
        ].max()
        latest_total = int(
            snapshot.loc[
                snapshot["snapshot_date"]
                == latest_date,
                "ticker",
            ].nunique()
        )

    rows.append(
        {
            "theme": "TOTAL",
            "universe_count": len(universe),
            "entities_with_factor_history": (
                int(panel["ticker"].nunique())
                if not panel.empty
                else 0
            ),
            "entities_in_latest_snapshot": latest_total,
        }
    )

    return pd.DataFrame(rows)


# ============================================================
# 8. 인수와 실행
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "최종 100개 AI 인프라 종목의 "
            "Point-in-Time 재무 팩터 스냅샷 생성"
        )
    )

    parser.add_argument(
        "--universe-file",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--factor-dir",
        type=Path,
        default=DEFAULT_FACTOR_DIR,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--frequency",
        choices=[
            "monthly",
            "quarterly",
            "yearly",
        ],
        default="monthly",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started = time.perf_counter()

    try:
        universe_file = resolve_universe_file(
            args.universe_file
        )
        factor_dir = args.factor_dir.resolve()
        output_dir = args.output_dir.resolve()

        if not factor_dir.exists():
            raise FileNotFoundError(
                f"Factor 폴더가 없습니다: {factor_dir}"
            )

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        # 사용자 지정 출력 디렉터리 대응
        panel_parquet = (
            output_dir
            / "pit_factor_panel.parquet"
        )
        panel_csv = (
            output_dir
            / "pit_factor_panel.csv"
        )
        snapshot_parquet = (
            output_dir
            / f"pit_snapshot_{args.frequency}.parquet"
        )
        snapshot_csv = (
            output_dir
            / f"pit_snapshot_{args.frequency}.csv"
        )
        latest_parquet = (
            output_dir
            / "pit_snapshot_latest.parquet"
        )
        latest_csv = (
            output_dir
            / "pit_snapshot_latest.csv"
        )
        summary_csv = (
            output_dir
            / "pit_snapshot_summary.csv"
        )
        errors_csv = (
            output_dir
            / "pit_snapshot_errors.csv"
        )
        run_log_csv = (
            output_dir
            / "pit_snapshot_run_log.csv"
        )

        output_files = [
            panel_parquet,
            panel_csv,
            snapshot_parquet,
            snapshot_csv,
            latest_parquet,
            latest_csv,
            summary_csv,
            errors_csv,
            run_log_csv,
        ]

        if (
            any(
                path.exists()
                for path in output_files
            )
            and not args.overwrite
        ):
            print(
                "[SKIP] 기존 결과 파일이 있습니다. "
                "다시 생성하려면 --overwrite를 사용하세요."
            )
            return 0

        universe = load_universe(
            universe_file
        )

        panel, errors, files_found = build_factor_panel(
            universe=universe,
            factor_dir=factor_dir,
        )

        if panel.empty:
            raise RuntimeError(
                "생성된 PIT Factor Panel이 비어 있습니다. "
                "pit_snapshot_errors.csv 또는 Factor 스키마를 "
                "확인하세요."
            )

        rebalance_dates = build_rebalance_dates(
            panel=panel,
            start_date=args.start_date,
            end_date=args.end_date,
            frequency=args.frequency,
        )

        snapshot = build_pit_snapshot(
            panel=panel,
            universe=universe,
            rebalance_dates=rebalance_dates,
        )

        if snapshot.empty:
            raise RuntimeError(
                "생성된 PIT Snapshot이 비어 있습니다."
            )

        latest = build_latest_snapshot(
            snapshot
        )

        summary = build_summary(
            universe=universe,
            panel=panel,
            snapshot=snapshot,
            errors=errors,
        )

        panel.to_parquet(
            panel_parquet,
            index=False,
        )
        panel.to_csv(
            panel_csv,
            index=False,
            encoding="utf-8-sig",
        )

        snapshot.to_parquet(
            snapshot_parquet,
            index=False,
        )
        snapshot.to_csv(
            snapshot_csv,
            index=False,
            encoding="utf-8-sig",
        )

        latest.to_parquet(
            latest_parquet,
            index=False,
        )
        latest.to_csv(
            latest_csv,
            index=False,
            encoding="utf-8-sig",
        )

        summary.to_csv(
            summary_csv,
            index=False,
            encoding="utf-8-sig",
        )
        errors.to_csv(
            errors_csv,
            index=False,
            encoding="utf-8-sig",
        )

        successful_entities = int(
            panel["ticker"].nunique()
        )
        failed_entities = int(
            universe["ticker"].nunique()
            - successful_entities
        )

        run_log = RunLog(
            universe_count=len(universe),
            factor_files_found=files_found,
            successful_entities=successful_entities,
            failed_entities=failed_entities,
            panel_rows=len(panel),
            rebalance_dates=len(rebalance_dates),
            snapshot_rows=len(snapshot),
            latest_rows=len(latest),
            frequency=args.frequency,
            start_date=str(
                rebalance_dates.min().date()
            ),
            end_date=str(
                rebalance_dates.max().date()
            ),
            elapsed_seconds=round(
                time.perf_counter() - started,
                4,
            ),
            universe_file=str(
                universe_file.resolve()
            ),
            factor_dir=str(factor_dir),
            output_dir=str(output_dir),
        )

        pd.DataFrame(
            [asdict(run_log)]
        ).to_csv(
            run_log_csv,
            index=False,
            encoding="utf-8-sig",
        )

        latest_date = (
            latest["snapshot_date"].max()
            if not latest.empty
            else pd.NaT
        )

        print("\n" + "=" * 70)
        print("PIT Snapshot 실행 결과")
        print("=" * 70)
        print(
            f"최종 유니버스         : "
            f"{len(universe):,}"
        )
        print(
            f"Factor 파일 발견      : "
            f"{files_found:,}"
        )
        print(
            f"처리 성공 기업        : "
            f"{successful_entities:,}"
        )
        print(
            f"처리 실패 기업        : "
            f"{failed_entities:,}"
        )
        print(
            f"공시·팩터 패널 행     : "
            f"{len(panel):,}"
        )
        print(
            f"리밸런싱 날짜 수      : "
            f"{len(rebalance_dates):,}"
        )
        print(
            f"PIT 스냅샷 행         : "
            f"{len(snapshot):,}"
        )
        print(
            f"최신 스냅샷 기업 수  : "
            f"{len(latest):,}"
        )
        print(
            f"최신 스냅샷 기준일   : "
            f"{latest_date.date() if pd.notna(latest_date) else '-'}"
        )
        print("-" * 70)
        print(
            f"Factor Panel : {panel_parquet}"
        )
        print(
            f"PIT Snapshot : {snapshot_parquet}"
        )
        print(
            f"Latest       : {latest_parquet}"
        )
        print(
            f"Summary      : {summary_csv}"
        )
        print(
            f"Errors       : {errors_csv}"
        )
        print(
            f"Run Log      : {run_log_csv}"
        )
        print("=" * 70)

        return 0

    except Exception as exc:
        print(
            f"[ERROR] {type(exc).__name__}: {exc}"
        )
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())