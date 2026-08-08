"""
05_build_theme4ir_pit.py
============================================================
분기 PIT Snapshot을 바탕으로 리밸런싱 시점별 편입 가능 여부와
편입·제외 근거를 생성하고 theme4ir_pit.json으로 저장합니다.

입력
------------------------------------------------------------
data/pit/pit_snapshot_quarterly.parquet
  또는 data/pit/pit_snapshot_quarterly.csv

출력
------------------------------------------------------------
data/pit/theme4ir_pit.json
data/pit/theme4ir_pit.csv
data/pit/pit_inclusion_summary.csv
data/pit/pit_inclusion_reasons.csv
data/pit/theme4ir_pit_run_log.csv

기본 스크리닝 규칙
------------------------------------------------------------
1. PIT 유효성: pit_valid == True
2. 정보 신선도: information_age_days <= 365
3. 필수 팩터 가용성:
   - revenue_growth
   - operating_margin
   - roa
   - debt_ratio
   기본값은 4개 모두 존재해야 통과
4. 데이터 품질: data_quality_score >= 60
5. 재무 경고 없음: financial_warning == False
6. 핵심 재무 데이터 존재:
   - revenue
   - assets
   - net_income

주의
------------------------------------------------------------
실제 Factor 파일에 revenue/assets/net_income 컬럼이 없으면 해당 조건은
'검사 불가'로 기록하고, 기본값에서는 자동 탈락시키지 않습니다.
엄격하게 적용하려면 --require-core-financials 옵션을 사용하세요.

실행
------------------------------------------------------------
python 02_Data_Preprocessing/code/05_build_theme4ir_pit.py --overwrite

엄격한 핵심 재무데이터 검사
------------------------------------------------------------
python 02_Data_Preprocessing/code/05_build_theme4ir_pit.py ^
  --require-core-financials ^
  --overwrite
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# 1. 경로
# ============================================================

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]

DEFAULT_PIT_DIR = PROJECT_ROOT / "data" / "pit"
DEFAULT_INPUT_PARQUET = DEFAULT_PIT_DIR / "pit_snapshot_quarterly.parquet"
DEFAULT_INPUT_CSV = DEFAULT_PIT_DIR / "pit_snapshot_quarterly.csv"

DEFAULT_JSON = DEFAULT_PIT_DIR / "theme4ir_pit.json"
DEFAULT_CSV = DEFAULT_PIT_DIR / "theme4ir_pit.csv"
DEFAULT_SUMMARY = DEFAULT_PIT_DIR / "pit_inclusion_summary.csv"
DEFAULT_REASONS = DEFAULT_PIT_DIR / "pit_inclusion_reasons.csv"
DEFAULT_RUN_LOG = DEFAULT_PIT_DIR / "theme4ir_pit_run_log.csv"


# ============================================================
# 2. 기본값
# ============================================================

DEFAULT_MIN_REQUIRED_FACTORS = 4
DEFAULT_MIN_DATA_QUALITY = 60.0
DEFAULT_MAX_INFORMATION_AGE = 365

# STALE 유예(grace) 버퍼. 0이면 기능 완전 비활성 → 판정/산출물 기존과 100% 동일.
# 값 N(분기)이면, "직전 N개 스냅숏 안에서 (유예 없이) 편입 자격이 있었고 이번
# 스냅숏에서 '오직 신선도(STALE)만' 위반한" 종목을 유예 편입시킨다. N분기 연속
# STALE이면 유예가 끊겨 자연 탈락한다. 채택 시 신규 규칙이므로 장부 기록 필수.
DEFAULT_STALE_GRACE_QUARTERS = 0
STALE_FAIL_PREFIX = "STALE_INFORMATION_OVER_"

CORE_FINANCIAL_COLUMNS = [
    "revenue",
    "assets",
    "net_income",
]

# 필수 팩터는 이름 차이를 고려해 별칭을 함께 지원합니다.
REQUIRED_FACTOR_ALIASES = {
    "revenue_growth": [
        "revenue_growth",
        "revenue_growth_yoy",
        "sales_growth",
        "sales_growth_yoy",
    ],
    "operating_margin": [
        "operating_margin",
        "op_margin",
        "operating_income_margin",
    ],
    "roa": [
        "roa",
        "return_on_assets",
    ],
    "debt_ratio": [
        "debt_ratio",
        "liabilities_to_assets",
        "debt_to_assets",
    ],
}


# ============================================================
# 3. 로그
# ============================================================

@dataclass
class RunLog:
    input_rows: int
    snapshot_dates: int
    unique_tickers: int
    eligible_rows: int
    excluded_rows: int
    latest_snapshot_date: str
    latest_eligible_count: int
    min_required_factors: int
    required_factors: str
    min_data_quality: float
    max_information_age_days: int
    require_core_financials: bool
    elapsed_seconds: float
    input_file: str
    output_json: str
    stale_grace_quarters: int = 0
    grace_promoted_rows: int = 0


# ============================================================
# 4. 도우미
# ============================================================

def clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "<na>", "nat"} else text


def parse_bool_value(value: object, default: bool = False) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value is None or pd.isna(value):
        return default
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "t"}:
        return True
    if text in {"false", "0", "no", "n", "f"}:
        return False
    return default


def safe_number(value: object) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        number = float(value)
        return number if np.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def find_factor_value(row: pd.Series, aliases: list[str]) -> tuple[str | None, float | None]:
    """Return the first existing alias and its finite numeric value."""
    lower_map = {str(column).lower(): column for column in row.index}

    for alias in aliases:
        actual_column = lower_map.get(alias.lower())
        if actual_column is None:
            continue

        value = safe_number(row.get(actual_column))
        if value is not None:
            return str(actual_column), value

    return None, None


def resolve_input_file(explicit_path: Path | None) -> Path:
    if explicit_path is not None:
        path = explicit_path.resolve()
        if not path.exists():
            raise FileNotFoundError(f"PIT Snapshot 파일이 없습니다: {path}")
        return path

    if DEFAULT_INPUT_PARQUET.exists():
        return DEFAULT_INPUT_PARQUET

    if DEFAULT_INPUT_CSV.exists():
        return DEFAULT_INPUT_CSV

    raise FileNotFoundError(
        "분기 PIT Snapshot을 찾지 못했습니다. "
        f"{DEFAULT_INPUT_PARQUET} 또는 {DEFAULT_INPUT_CSV}가 필요합니다."
    )


def load_snapshot(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, dtype={"cik": "string"})

    required = ["snapshot_date", "ticker", "theme"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError("PIT Snapshot 필수 컬럼 누락: " + ", ".join(missing))

    df = df.copy()
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"], errors="coerce")
    df = df[df["snapshot_date"].notna()].copy()

    if "availability_date" in df.columns:
        df["availability_date"] = pd.to_datetime(
            df["availability_date"], errors="coerce"
        )

    if "period_end" in df.columns:
        df["period_end"] = pd.to_datetime(df["period_end"], errors="coerce")

    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["theme"] = df["theme"].fillna("Unknown").astype(str).str.strip()

    # 같은 날짜·티커 중복이 있으면 이용가능일이 가장 최신인 행 사용
    sort_columns = ["snapshot_date", "ticker"]
    if "availability_date" in df.columns:
        sort_columns.append("availability_date")

    df = (
        df.sort_values(sort_columns)
        .drop_duplicates(["snapshot_date", "ticker"], keep="last")
        .reset_index(drop=True)
    )

    return df


# ============================================================
# 5. 스크리닝
# ============================================================

def evaluate_row(
    row: pd.Series,
    min_required_factors: int,
    min_data_quality: float,
    max_information_age: int,
    require_core_financials: bool,
) -> dict[str, object]:
    passed_reasons: list[str] = []
    failed_reasons: list[str] = []
    unavailable_checks: list[str] = []

    # 1. PIT Valid
    if "pit_valid" in row.index:
        pit_valid = parse_bool_value(row.get("pit_valid"), default=False)
        if pit_valid:
            passed_reasons.append("PIT_VALID")
        else:
            failed_reasons.append("PIT_INVALID")
    else:
        unavailable_checks.append("PIT_VALID_NOT_AVAILABLE")

    # 2. 정보 신선도
    age = safe_number(row.get("information_age_days"))
    if age is None:
        unavailable_checks.append("INFORMATION_AGE_NOT_AVAILABLE")
    elif age <= max_information_age:
        passed_reasons.append("INFORMATION_FRESH")
    else:
        failed_reasons.append(f"STALE_INFORMATION_OVER_{max_information_age}D")

    # 3. 필수 팩터 가용성
    available_required_factors: list[str] = []
    missing_required_factors: list[str] = []
    required_factor_columns: dict[str, str | None] = {}

    for factor_name, aliases in REQUIRED_FACTOR_ALIASES.items():
        actual_column, factor_value = find_factor_value(row, aliases)
        required_factor_columns[factor_name] = actual_column

        if factor_value is None:
            missing_required_factors.append(factor_name)
        else:
            available_required_factors.append(factor_name)
            passed_reasons.append(f"REQUIRED_FACTOR_{factor_name.upper()}_AVAILABLE")

    required_factor_count = len(available_required_factors)

    if required_factor_count >= min_required_factors:
        passed_reasons.append(
            f"REQUIRED_FACTOR_COVERAGE_{required_factor_count}_OF_{len(REQUIRED_FACTOR_ALIASES)}"
        )
    else:
        failed_reasons.append(
            f"REQUIRED_FACTOR_COUNT_BELOW_{min_required_factors}"
        )
        failed_reasons.extend(
            [f"MISSING_REQUIRED_FACTOR_{name.upper()}" for name in missing_required_factors]
        )

    # 4. 데이터 품질
    quality = safe_number(row.get("data_quality_score"))
    if quality is None:
        unavailable_checks.append("DATA_QUALITY_NOT_AVAILABLE")
    elif quality >= min_data_quality:
        passed_reasons.append("DATA_QUALITY_PASS")
    else:
        failed_reasons.append(f"DATA_QUALITY_BELOW_{min_data_quality:g}")

    # 5. Financial warning
    if "financial_warning" in row.index:
        warning = parse_bool_value(row.get("financial_warning"), default=False)
        if warning:
            failed_reasons.append("FINANCIAL_WARNING")
        else:
            passed_reasons.append("NO_FINANCIAL_WARNING")
    else:
        unavailable_checks.append("FINANCIAL_WARNING_NOT_AVAILABLE")

    # 6. 핵심 재무 데이터
    missing_core = []
    checked_core = []

    for column in CORE_FINANCIAL_COLUMNS:
        if column not in row.index:
            unavailable_checks.append(f"{column.upper()}_COLUMN_NOT_AVAILABLE")
            continue

        checked_core.append(column)
        value = safe_number(row.get(column))
        if value is None:
            missing_core.append(column)
        else:
            passed_reasons.append(f"{column.upper()}_AVAILABLE")

    if missing_core:
        if require_core_financials:
            failed_reasons.extend(
                [f"MISSING_{column.upper()}" for column in missing_core]
            )
        else:
            unavailable_checks.extend(
                [f"MISSING_{column.upper()}_NOT_ENFORCED" for column in missing_core]
            )

    eligible = len(failed_reasons) == 0

    if eligible:
        decision_reason = "ELIGIBLE"
    else:
        decision_reason = " | ".join(failed_reasons)

    return {
        "eligible": eligible,
        "decision": "INCLUDE" if eligible else "EXCLUDE",
        "decision_reason": decision_reason,
        "passed_reasons": passed_reasons,
        "failed_reasons": failed_reasons,
        "unavailable_checks": unavailable_checks,
        "passed_reason_count": len(passed_reasons),
        "failed_reason_count": len(failed_reasons),
        "unavailable_check_count": len(unavailable_checks),
        "required_factor_count": required_factor_count,
        "available_required_factors": available_required_factors,
        "missing_required_factors": missing_required_factors,
        "required_factor_columns": required_factor_columns,
    }


def build_theme4ir(
    snapshot: pd.DataFrame,
    min_required_factors: int,
    min_data_quality: float,
    max_information_age: int,
    require_core_financials: bool,
) -> pd.DataFrame:
    results = []

    for _, row in snapshot.iterrows():
        evaluation = evaluate_row(
            row=row,
            min_required_factors=min_required_factors,
            min_data_quality=min_data_quality,
            max_information_age=max_information_age,
            require_core_financials=require_core_financials,
        )

        record = row.to_dict()
        record.update(evaluation)
        results.append(record)

    result = pd.DataFrame(results)

    # 사람이 보기 쉬운 문자열 컬럼
    result["passed_reasons_text"] = result["passed_reasons"].map(
        lambda values: " | ".join(values)
    )
    result["failed_reasons_text"] = result["failed_reasons"].map(
        lambda values: " | ".join(values)
    )
    result["unavailable_checks_text"] = result["unavailable_checks"].map(
        lambda values: " | ".join(values)
    )
    result["available_required_factors_text"] = result["available_required_factors"].map(
        lambda values: " | ".join(values)
    )
    result["missing_required_factors_text"] = result["missing_required_factors"].map(
        lambda values: " | ".join(values)
    )

    result = result.sort_values(
        ["snapshot_date", "eligible", "universe_rank", "ticker"],
        ascending=[True, False, True, True],
        na_position="last",
    ).reset_index(drop=True)

    return result


def apply_stale_grace(
    result: pd.DataFrame,
    grace_quarters: int,
) -> pd.DataFrame:
    """
    STALE 유예(grace) 버퍼 post-pass.

    grace_quarters <= 0 이면 입력을 그대로 반환한다(완전 no-op). 이 경우
    반환 객체는 컬럼/값 모두 기존과 동일하므로 하류(scores/weights/backtest)
    산출물이 100% 재현된다.

    grace_quarters = N > 0 이면:
      - '이번 스냅숏에서 오직 신선도(STALE_INFORMATION_OVER_*)만' 위반한 행을
        대상으로 한다(다른 사유가 하나라도 있으면 제외).
      - 해당 종목이 직전 N개 스냅숏 안에서 '유예 없이(base)' 편입 자격이
        있었으면 이번 스냅숏에 유예 편입시킨다.
      - base 자격을 앵커로 쓰므로 유예가 연쇄되지 않는다(N분기 연속 STALE시
        자연 탈락).
      - 신규 컬럼 stale_grace_applied(bool), stale_grace_source_date 를
        추가한다. grace_quarters<=0 에서는 이 컬럼도 추가되지 않는다.
    """
    if grace_quarters is None or grace_quarters <= 0:
        return result

    df = result.copy()

    ordered_dates = sorted(df["snapshot_date"].unique())
    date_to_idx = {date: idx for idx, date in enumerate(ordered_dates)}
    snap_idx = df["snapshot_date"].map(date_to_idx)

    # base(유예 이전) 자격 조회표: (ticker, snapshot_index) -> bool
    base_eligible = {
        (ticker, idx): bool(elig)
        for ticker, idx, elig in zip(df["ticker"], snap_idx, df["eligible"])
    }

    df["stale_grace_applied"] = False
    df["stale_grace_source_date"] = pd.NaT

    for pos, idx in zip(df.index, snap_idx):
        if bool(df.at[pos, "eligible"]):
            continue

        failed = df.at[pos, "failed_reasons"]
        only_stale = (
            isinstance(failed, list)
            and len(failed) == 1
            and str(failed[0]).startswith(STALE_FAIL_PREFIX)
        )
        if not only_stale:
            continue

        ticker = df.at[pos, "ticker"]
        for back in range(1, grace_quarters + 1):
            if base_eligible.get((ticker, idx - back), False):
                df.at[pos, "eligible"] = True
                df.at[pos, "decision"] = "INCLUDE"
                df.at[pos, "decision_reason"] = "ELIGIBLE_VIA_STALE_GRACE"
                df.at[pos, "stale_grace_applied"] = True
                df.at[pos, "stale_grace_source_date"] = ordered_dates[idx - back]
                passed = df.at[pos, "passed_reasons"]
                if isinstance(passed, list):
                    df.at[pos, "passed_reasons"] = passed + ["STALE_GRACE_APPLIED"]
                break

    # 변경된 행의 사람이 읽는 텍스트 컬럼 갱신
    df["passed_reasons_text"] = df["passed_reasons"].map(
        lambda values: " | ".join(values) if isinstance(values, list) else values
    )

    df = df.sort_values(
        ["snapshot_date", "eligible", "universe_rank", "ticker"],
        ascending=[True, False, True, True],
        na_position="last",
    ).reset_index(drop=True)

    return df


# ============================================================
# 6. 요약 및 JSON
# ============================================================

def build_summary(result: pd.DataFrame) -> pd.DataFrame:
    summary = (
        result.groupby("snapshot_date", as_index=False)
        .agg(
            total_companies=("ticker", "nunique"),
            eligible_companies=("eligible", "sum"),
        )
    )

    summary["excluded_companies"] = (
        summary["total_companies"] - summary["eligible_companies"]
    )
    summary["eligible_pct"] = (
        summary["eligible_companies"]
        / summary["total_companies"]
        * 100
    ).round(2)

    return summary


def build_reason_summary(result: pd.DataFrame) -> pd.DataFrame:
    records = []

    for _, row in result.iterrows():
        for reason in row["passed_reasons"]:
            records.append(
                {
                    "snapshot_date": row["snapshot_date"],
                    "ticker": row["ticker"],
                    "eligible": row["eligible"],
                    "reason_type": "PASS",
                    "reason": reason,
                }
            )

        for reason in row["failed_reasons"]:
            records.append(
                {
                    "snapshot_date": row["snapshot_date"],
                    "ticker": row["ticker"],
                    "eligible": row["eligible"],
                    "reason_type": "FAIL",
                    "reason": reason,
                }
            )

        for reason in row["unavailable_checks"]:
            records.append(
                {
                    "snapshot_date": row["snapshot_date"],
                    "ticker": row["ticker"],
                    "eligible": row["eligible"],
                    "reason_type": "UNAVAILABLE",
                    "reason": reason,
                }
            )

    return pd.DataFrame(
        records,
        columns=[
            "snapshot_date",
            "ticker",
            "eligible",
            "reason_type",
            "reason",
        ],
    )


def json_safe(value: object) -> object:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def build_json_payload(
    result: pd.DataFrame,
    settings: dict[str, object],
) -> dict[str, object]:
    snapshots = []

    for snapshot_date, group in result.groupby("snapshot_date", sort=True):
        companies = []

        for _, row in group.iterrows():
            companies.append(
                {
                    "ticker": json_safe(row.get("ticker")),
                    "cik": json_safe(row.get("cik")),
                    "entity_name": json_safe(row.get("entity_name")),
                    "theme": json_safe(row.get("theme")),
                    "sub_theme": json_safe(row.get("sub_theme")),
                    "universe_rank": json_safe(row.get("universe_rank")),
                    "eligible": bool(row["eligible"]),
                    "decision": row["decision"],
                    "passed_reasons": row["passed_reasons"],
                    "failed_reasons": row["failed_reasons"],
                    "unavailable_checks": row["unavailable_checks"],
                    "availability_date": json_safe(row.get("availability_date")),
                    "period_end": json_safe(row.get("period_end")),
                    "information_age_days": json_safe(
                        row.get("information_age_days")
                    ),
                    "factor_available_count": json_safe(
                        row.get("factor_available_count")
                    ),
                    "required_factor_count": json_safe(
                        row.get("required_factor_count")
                    ),
                    "available_required_factors": row.get(
                        "available_required_factors", []
                    ),
                    "missing_required_factors": row.get(
                        "missing_required_factors", []
                    ),
                    "required_factor_columns": row.get(
                        "required_factor_columns", {}
                    ),
                    "data_quality_score": json_safe(
                        row.get("data_quality_score")
                    ),
                    "financial_warning": json_safe(
                        row.get("financial_warning")
                    ),
                    "selection_score": json_safe(
                        row.get("selection_score")
                    ),
                }
            )

        eligible_count = int(group["eligible"].sum())

        snapshots.append(
            {
                "snapshot_date": snapshot_date.strftime("%Y-%m-%d"),
                "total_companies": int(group["ticker"].nunique()),
                "eligible_companies": eligible_count,
                "excluded_companies": int(len(group) - eligible_count),
                "companies": companies,
            }
        )

    return {
        "index_name": "Theme4IR AI Infrastructure Index",
        "rebalance_frequency": "quarterly",
        "screening_settings": settings,
        "snapshot_count": len(snapshots),
        "snapshots": snapshots,
    }


# ============================================================
# 7. 실행
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="분기 PIT Snapshot에서 편입 가능 여부와 근거를 생성합니다."
    )

    parser.add_argument("--input-file", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_PIT_DIR)
    parser.add_argument(
        "--min-required-factors",
        type=int,
        default=DEFAULT_MIN_REQUIRED_FACTORS,
        choices=range(1, len(REQUIRED_FACTOR_ALIASES) + 1),
        metavar=f"1-{len(REQUIRED_FACTOR_ALIASES)}",
        help="필수 팩터 4개 중 최소 몇 개가 존재해야 통과할지 설정합니다.",
    )
    parser.add_argument(
        "--min-data-quality",
        type=float,
        default=DEFAULT_MIN_DATA_QUALITY,
    )
    parser.add_argument(
        "--max-information-age",
        type=int,
        default=DEFAULT_MAX_INFORMATION_AGE,
    )
    parser.add_argument(
        "--require-core-financials",
        action="store_true",
    )
    parser.add_argument(
        "--stale-grace-quarters",
        type=int,
        default=DEFAULT_STALE_GRACE_QUARTERS,
        metavar="N",
        help=(
            "STALE 유예(grace) 버퍼(분기). 0(기본)이면 비활성 → 기존 산출물과 "
            "100%% 동일. N>0이면 직전 N개 스냅숏 안에서 편입 자격이 있었고 이번 "
            "스냅숏에서 신선도만 위반한 종목을 유예 편입. 신규 규칙이므로 채택 시 "
            "장부 기록 필수."
        ),
    )
    parser.add_argument("--overwrite", action="store_true")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started = time.perf_counter()

    try:
        input_file = resolve_input_file(args.input_file)
        output_dir = args.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        json_file = output_dir / "theme4ir_pit.json"
        csv_file = output_dir / "theme4ir_pit.csv"
        summary_file = output_dir / "pit_inclusion_summary.csv"
        reasons_file = output_dir / "pit_inclusion_reasons.csv"
        run_log_file = output_dir / "theme4ir_pit_run_log.csv"

        output_files = [
            json_file,
            csv_file,
            summary_file,
            reasons_file,
            run_log_file,
        ]

        if any(path.exists() for path in output_files) and not args.overwrite:
            print(
                "[SKIP] 기존 결과 파일이 있습니다. "
                "다시 생성하려면 --overwrite를 사용하세요."
            )
            return 0

        snapshot = load_snapshot(input_file)

        result = build_theme4ir(
            snapshot=snapshot,
            min_required_factors=args.min_required_factors,
            min_data_quality=args.min_data_quality,
            max_information_age=args.max_information_age,
            require_core_financials=args.require_core_financials,
        )

        # STALE 유예 post-pass. grace=0(기본)이면 result 불변(no-op).
        result = apply_stale_grace(
            result=result,
            grace_quarters=args.stale_grace_quarters,
        )
        grace_promoted_rows = (
            int(result["stale_grace_applied"].sum())
            if "stale_grace_applied" in result.columns
            else 0
        )

        summary = build_summary(result)
        reason_summary = build_reason_summary(result)

        settings = {
            "pit_valid_required": True,
            "required_factor_rule": "minimum available required factors",
            "required_factor_aliases": REQUIRED_FACTOR_ALIASES,
            "min_required_factors": args.min_required_factors,
            "min_data_quality_score": args.min_data_quality,
            "max_information_age_days": args.max_information_age,
            "financial_warning_allowed": False,
            "core_financial_columns": CORE_FINANCIAL_COLUMNS,
            "require_core_financials": args.require_core_financials,
        }
        # 유예를 켰을 때만 설정에 기록한다. grace=0에서는 키를 추가하지 않아
        # theme4ir_pit.json 이 변경 이전과 바이트 단위로 동일하게 유지된다.
        if args.stale_grace_quarters > 0:
            settings["stale_grace_quarters"] = args.stale_grace_quarters

        payload = build_json_payload(
            result=result,
            settings=settings,
        )

        with json_file.open("w", encoding="utf-8") as file:
            json.dump(
                payload,
                file,
                ensure_ascii=False,
                indent=2,
            )

        # 리스트 컬럼은 CSV에서 텍스트로 저장
        csv_output = result.drop(
            columns=[
                "passed_reasons",
                "failed_reasons",
                "unavailable_checks",
                "available_required_factors",
                "missing_required_factors",
                "required_factor_columns",
            ],
            errors="ignore",
        ).copy()

        csv_output.to_csv(
            csv_file,
            index=False,
            encoding="utf-8-sig",
        )
        summary.to_csv(
            summary_file,
            index=False,
            encoding="utf-8-sig",
        )
        reason_summary.to_csv(
            reasons_file,
            index=False,
            encoding="utf-8-sig",
        )

        latest_date = result["snapshot_date"].max()
        latest = result[result["snapshot_date"] == latest_date]

        run_log = RunLog(
            input_rows=len(snapshot),
            snapshot_dates=result["snapshot_date"].nunique(),
            unique_tickers=result["ticker"].nunique(),

            eligible_rows=int(result["eligible"].sum()),
            excluded_rows=int((~result["eligible"]).sum()),

            latest_snapshot_date=latest_date.strftime("%Y-%m-%d"),
            latest_eligible_count=int(latest["eligible"].sum()),

            min_required_factors=args.min_required_factors,
            required_factors=", ".join(REQUIRED_FACTOR_ALIASES.keys()),

            min_data_quality=args.min_data_quality,
            max_information_age_days=args.max_information_age,

            require_core_financials=args.require_core_financials,

            elapsed_seconds=round(time.perf_counter()-started,4),

            input_file=str(input_file.resolve()),
            output_json=str(json_file),

            stale_grace_quarters=args.stale_grace_quarters,
            grace_promoted_rows=grace_promoted_rows,
        )

        pd.DataFrame([asdict(run_log)]).to_csv(
            run_log_file,
            index=False,
            encoding="utf-8-sig",
        )

        print("\n" + "=" * 70)
        print("theme4ir_pit 생성 결과")
        print("=" * 70)
        print(f"입력 PIT 행           : {len(snapshot):,}")
        print(f"분기 스냅샷 수       : {result['snapshot_date'].nunique():,}")
        print(f"고유 종목 수          : {result['ticker'].nunique():,}")
        print(f"전체 편입 판정 수     : {int(result['eligible'].sum()):,}")
        print(f"전체 제외 판정 수     : {int((~result['eligible']).sum()):,}")
        print(f"최신 스냅샷 기준일   : {latest_date.date()}")
        print(f"최신 편입 가능 종목   : {int(latest['eligible'].sum()):,}")
        print(f"최신 제외 종목        : {int((~latest['eligible']).sum()):,}")
        print(
            f"필수 팩터 기준        : "
            f"{args.min_required_factors}/{len(REQUIRED_FACTOR_ALIASES)}개 이상"
        )
        if args.stale_grace_quarters > 0:
            print(
                f"STALE 유예(분기)      : {args.stale_grace_quarters} "
                f"(유예 편입 {grace_promoted_rows}건)"
            )
        print("-" * 70)
        print(f"JSON          : {json_file}")
        print(f"전체 판정 CSV : {csv_file}")
        print(f"분기 요약     : {summary_file}")
        print(f"사유 상세     : {reasons_file}")
        print(f"실행 로그     : {run_log_file}")
        print("=" * 70)

        return 0

    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())