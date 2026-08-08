"""
02_entity_master.py

기업별 Factor parquet를 읽어 최신 기업 단위 Entity Master를 생성합니다.

입력
----
data/factors/{CIK}.parquet
data/facts/{CIK}.parquet          # ticker 보완용, 선택적

출력
----
data/entity_master/entity_master.parquet
data/entity_master/entity_master.csv
data/entity_master/entity_master_run_log.csv
data/entity_master/entity_master_errors.csv

기본 선택 규칙
--------------
1. 기업별 annual(10-K) 레코드를 우선 사용
2. annual이 없으면 quarterly(10-Q) 최신 레코드 사용
3. 같은 결산일이면 filed가 가장 최근인 레코드 사용
4. PIT 유효 레코드를 우선 사용
5. ticker는 factor에 없으면 facts 파일에서 보완

실행 예시
---------
python 02_Data_Preprocessing/code/02_entity_master.py

python 02_Data_Preprocessing/code/02_entity_master.py --limit 10 --overwrite

python 02_Data_Preprocessing/code/02_entity_master.py \
    --selection-mode latest_any \
    --overwrite
"""

from __future__ import annotations

import argparse
import math
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# ============================================================
# 1. 경로 설정
# ============================================================

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]

DEFAULT_FACTORS_DIR = PROJECT_ROOT / "data" / "factors"
DEFAULT_FACTS_DIR = PROJECT_ROOT / "data" / "facts"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "entity_master"

# 회사명 원천 (name이 100% 채워진 SEC master, cik+ticker 키)
DEFAULT_COMPANY_MASTER_PATH = (
    PROJECT_ROOT
    / "01_Data_Acquisition"
    / "output"
    / "sec_company_master.csv"
)

DEFAULT_PARQUET_FILE = DEFAULT_OUTPUT_DIR / "entity_master.parquet"
DEFAULT_CSV_FILE = DEFAULT_OUTPUT_DIR / "entity_master.csv"
DEFAULT_LOG_FILE = DEFAULT_OUTPUT_DIR / "entity_master_run_log.csv"
DEFAULT_ERROR_FILE = DEFAULT_OUTPUT_DIR / "entity_master_errors.csv"


# ============================================================
# 2. 출력 컬럼
# ============================================================

FINANCIAL_COLUMNS = [
    "revenue",
    "operating_income",
    "net_income",
    "assets",
    "liabilities",
    "equity",
    "current_assets",
    "current_liabilities",
    "operating_cash_flow",
    "capital_expenditure",
    "free_cash_flow_proxy",
]

FACTOR_COLUMNS = [
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
]

QUALITY_COLUMNS = [
    "factor_available_count",
    "source_fact_count",
    "pit_valid",
]

CLASSIFICATION_PLACEHOLDERS = [
    "exchange",
    "sector",
    "industry",
    "theme",
    "sub_theme",
    "market_cap",
    "is_ai_infrastructure",
    "classification_rule",
    "classification_score",
]

OUTPUT_COLUMNS = [
    "cik",
    "ticker",
    "entity_name",
    "latest_period_end",
    "latest_filed",
    "latest_form",
    "latest_accession",
    "latest_fiscal_year",
    "latest_fiscal_period",
    "latest_period_type",
    *FINANCIAL_COLUMNS,
    *FACTOR_COLUMNS,
    *QUALITY_COLUMNS,
    "financial_warning",
    "data_quality_score",
    "selection_reason",
    "factor_file",
    *CLASSIFICATION_PLACEHOLDERS,
]


# ============================================================
# 3. 로그 구조
# ============================================================

@dataclass
class EntityBuildResult:
    cik: str
    status: str
    factor_file: str
    selected_period_end: str = ""
    selected_filed: str = ""
    selected_period_type: str = ""
    factor_rows: int = 0
    ticker_found: bool = False
    elapsed_seconds: float = 0.0
    message: str = ""


# ============================================================
# 4. 공통 함수
# ============================================================

def normalize_cik(value: object) -> str:
    """CIK를 10자리 문자열로 정규화합니다."""
    if value is None:
        return ""

    if isinstance(value, float) and math.isnan(value):
        return ""

    text = str(value).strip()

    if text.endswith(".0"):
        text = text[:-2]

    digits = "".join(character for character in text if character.isdigit())

    return digits.zfill(10) if digits else ""


def clean_text(value: object) -> str:
    """결측 문자열을 빈 문자열로 정리합니다."""
    if value is None or pd.isna(value):
        return ""

    text = str(value).strip()

    if text.lower() in {"", "nan", "none", "<na>", "nat"}:
        return ""

    return text


def first_valid_text(series: pd.Series) -> str:
    """Series에서 첫 번째 유효 문자열을 반환합니다."""
    if series is None:
        return ""

    for value in series:
        text = clean_text(value)
        if text:
            return text

    return ""


def ensure_columns(
    df: pd.DataFrame,
    columns: list[str],
    default: object = np.nan,
) -> pd.DataFrame:
    """없는 컬럼을 추가합니다."""
    result = df.copy()

    for column in columns:
        if column not in result.columns:
            result[column] = default

    return result


def safe_bool(value: object) -> bool:
    """다양한 값을 안전하게 bool로 변환합니다."""
    if value is None or pd.isna(value):
        return False

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, np.integer)):
        return bool(value)

    text = str(value).strip().lower()

    return text in {"true", "1", "yes", "y", "t"}


def safe_float(value: object) -> float:
    """숫자 변환 실패 시 NaN을 반환합니다."""
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return np.nan

    return converted if np.isfinite(converted) else np.nan


def discover_factor_files(
    factors_dir: Path,
    cik: Optional[str],
    limit: Optional[int],
) -> list[Path]:
    """처리할 factor 파일을 찾습니다."""
    if cik:
        normalized = normalize_cik(cik)
        target = factors_dir / f"{normalized}.parquet"

        if not target.exists():
            raise FileNotFoundError(
                f"Factor 파일이 없습니다: {target}"
            )

        files = [target]
    else:
        files = sorted(
            path
            for path in factors_dir.glob("*.parquet")
            if path.name != "entity_master.parquet"
        )

    if limit is not None:
        files = files[:limit]

    return files


# ============================================================
# 5. Factor 데이터 표준화
# ============================================================

def standardize_factor_dataframe(
    raw: pd.DataFrame,
    fallback_cik: str,
) -> pd.DataFrame:
    """Factor Engine 출력의 자료형과 필수 컬럼을 정리합니다."""
    required_identity = [
        "cik",
        "entity_name",
        "period_end",
        "filed",
        "form",
        "accession",
        "fiscal_year",
        "fiscal_period",
        "period_type",
    ]

    all_required = (
        required_identity
        + FINANCIAL_COLUMNS
        + FACTOR_COLUMNS
        + QUALITY_COLUMNS
    )

    df = ensure_columns(raw, all_required)

    df["cik"] = df["cik"].map(normalize_cik)
    df.loc[df["cik"].eq(""), "cik"] = fallback_cik

    df["entity_name"] = df["entity_name"].astype("string")
    df["form"] = (
        df["form"]
        .astype("string")
        .str.upper()
        .str.strip()
    )

    df["accession"] = df["accession"].astype("string")
    df["fiscal_period"] = (
        df["fiscal_period"]
        .astype("string")
        .str.upper()
        .str.strip()
    )

    df["period_type"] = (
        df["period_type"]
        .astype("string")
        .str.lower()
        .str.strip()
    )

    df["period_end"] = pd.to_datetime(
        df["period_end"],
        errors="coerce",
    )

    df["filed"] = pd.to_datetime(
        df["filed"],
        errors="coerce",
    )

    df["fiscal_year"] = pd.to_numeric(
        df["fiscal_year"],
        errors="coerce",
    ).astype("Int64")

    numeric_columns = (
        FINANCIAL_COLUMNS
        + FACTOR_COLUMNS
        + [
            "factor_available_count",
            "source_fact_count",
        ]
    )

    for column in numeric_columns:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        )

    df["pit_valid"] = df["pit_valid"].map(safe_bool)

    # period_type이 비어 있는 과거 파일 호환
    missing_period_type = (
        df["period_type"].isna()
        | df["period_type"].isin(["", "<na>", "nan"])
    )

    df.loc[
        missing_period_type
        & df["form"].isin(["10-K", "10-K/A"]),
        "period_type",
    ] = "annual"

    df.loc[
        missing_period_type
        & df["form"].isin(["10-Q", "10-Q/A"]),
        "period_type",
    ] = "quarterly"

    df = df.dropna(
        subset=["period_end", "filed"]
    ).copy()

    df = df[
        df["filed"] >= df["period_end"]
    ].copy()

    df = df.drop_duplicates(
        subset=[
            "cik",
            "period_end",
            "filed",
            "form",
            "accession",
        ],
        keep="last",
    )

    return df.reset_index(drop=True)


# ============================================================
# 6. 최신 레코드 선택
# ============================================================

def choose_latest_record(
    factors: pd.DataFrame,
    selection_mode: str,
) -> tuple[pd.Series, str]:
    """
    기업별 최신 대표 레코드를 선택합니다.

    selection_mode
    --------------
    annual_preferred:
        annual 최신값 우선, annual이 없으면 전체 최신값

    annual_only:
        annual 데이터만 허용

    latest_any:
        annual/quarterly 구분 없이 가장 최신값
    """
    if factors.empty:
        raise ValueError("선택 가능한 Factor 레코드가 없습니다.")

    candidates = factors.copy()

    if selection_mode == "annual_only":
        annual = candidates[
            candidates["period_type"].eq("annual")
        ].copy()

        if annual.empty:
            raise ValueError("annual Factor 레코드가 없습니다.")

        candidates = annual
        selection_reason = "latest_annual"

    elif selection_mode == "annual_preferred":
        annual = candidates[
            candidates["period_type"].eq("annual")
        ].copy()

        if not annual.empty:
            candidates = annual
            selection_reason = "latest_annual"
        else:
            selection_reason = "annual_missing_latest_any"

    elif selection_mode == "latest_any":
        selection_reason = "latest_any"

    else:
        raise ValueError(
            f"지원하지 않는 selection_mode입니다: {selection_mode}"
        )

    # PIT 유효한 값이 하나라도 있으면 유효 레코드만 사용
    if candidates["pit_valid"].any():
        candidates = candidates[
            candidates["pit_valid"]
        ].copy()
        selection_reason += "_pit_valid"

    candidates = candidates.sort_values(
        by=[
            "period_end",
            "filed",
            "factor_available_count",
            "source_fact_count",
            "accession",
        ],
        ascending=[
            False,
            False,
            False,
            False,
            False,
        ],
        na_position="last",
    )

    return candidates.iloc[0], selection_reason


# ============================================================
# 7. ticker 보완
# ============================================================

def extract_ticker_from_facts(
    facts_file: Path,
) -> str:
    """Fact Store에서 ticker를 가져옵니다."""
    if not facts_file.exists():
        return ""

    try:
        facts = pd.read_parquet(
            facts_file,
            columns=["ticker"],
        )
    except Exception:
        try:
            facts = pd.read_parquet(facts_file)
        except Exception:
            return ""

    if "ticker" not in facts.columns:
        return ""

    ticker_series = (
        facts["ticker"]
        .dropna()
        .astype(str)
        .str.strip()
    )

    ticker_series = ticker_series[
        ~ticker_series.str.lower().isin(
            ["", "nan", "none", "<na>"]
        )
    ]

    if ticker_series.empty:
        return ""

    # 가장 자주 등장하는 ticker를 우선 사용
    counts = ticker_series.value_counts()

    if not counts.empty:
        return clean_text(counts.index[0])

    return clean_text(ticker_series.iloc[0])


# ============================================================
# 8. 데이터 품질 계산
# ============================================================

def calculate_financial_warning(
    row: pd.Series,
) -> bool:
    """핵심 재무 데이터 이상 여부를 계산합니다."""
    revenue = safe_float(row.get("revenue"))
    assets = safe_float(row.get("assets"))
    net_income = safe_float(row.get("net_income"))

    if not np.isfinite(revenue):
        return True

    if not np.isfinite(assets):
        return True

    if not np.isfinite(net_income):
        return True

    if revenue <= 0:
        return True

    if assets <= 0:
        return True

    if not safe_bool(row.get("pit_valid")):
        return True

    return False


def calculate_data_quality_score(
    row: pd.Series,
) -> float:
    """
    0~100 범위 데이터 품질 점수를 계산합니다.

    구성
    ----
    핵심 재무항목 가용성: 40점
    주요 팩터 가용성:    35점
    PIT 유효성:          15점
    source fact 수:      10점
    """
    core_financials = [
        "revenue",
        "net_income",
        "assets",
        "liabilities",
        "equity",
    ]

    major_factors = [
        "revenue_growth",
        "operating_margin",
        "net_margin",
        "roa",
        "roe",
        "debt_ratio",
        "free_cash_flow_proxy",
    ]

    core_available = sum(
        pd.notna(row.get(column))
        for column in core_financials
    )

    factor_available = sum(
        pd.notna(row.get(column))
        for column in major_factors
    )

    core_score = (
        core_available
        / len(core_financials)
        * 40
    )

    factor_score = (
        factor_available
        / len(major_factors)
        * 35
    )

    pit_score = (
        15
        if safe_bool(row.get("pit_valid"))
        else 0
    )

    source_count = safe_float(
        row.get("source_fact_count")
    )

    if not np.isfinite(source_count):
        source_score = 0
    else:
        source_score = min(
            max(source_count, 0) / 9 * 10,
            10,
        )

    total = (
        core_score
        + factor_score
        + pit_score
        + source_score
    )

    return round(float(total), 2)


# ============================================================
# 9. 기업별 Entity 행 생성
# ============================================================

def build_entity_row(
    factor_file: Path,
    facts_dir: Path,
    selection_mode: str,
) -> tuple[dict[str, object], EntityBuildResult]:
    """기업 하나의 Entity Master 행을 생성합니다."""
    started = time.perf_counter()
    cik = normalize_cik(factor_file.stem)

    raw = pd.read_parquet(factor_file)

    factors = standardize_factor_dataframe(
        raw=raw,
        fallback_cik=cik,
    )

    if factors.empty:
        raise ValueError(
            "표준화 후 사용 가능한 Factor 레코드가 없습니다."
        )

    selected, selection_reason = choose_latest_record(
        factors=factors,
        selection_mode=selection_mode,
    )

    facts_file = facts_dir / f"{cik}.parquet"
    ticker = extract_ticker_from_facts(facts_file)

    entity_name = first_valid_text(
        factors["entity_name"]
    )

    if not entity_name:
        entity_name = clean_text(
            selected.get("entity_name")
        )

    entity: dict[str, object] = {
        "cik": cik,
        "ticker": ticker,
        "entity_name": entity_name,
        "latest_period_end": selected.get("period_end"),
        "latest_filed": selected.get("filed"),
        "latest_form": clean_text(selected.get("form")),
        "latest_accession": clean_text(
            selected.get("accession")
        ),
        "latest_fiscal_year": selected.get(
            "fiscal_year"
        ),
        "latest_fiscal_period": clean_text(
            selected.get("fiscal_period")
        ),
        "latest_period_type": clean_text(
            selected.get("period_type")
        ),
        "selection_reason": selection_reason,
        "factor_file": str(factor_file),
    }

    for column in FINANCIAL_COLUMNS:
        entity[column] = selected.get(column, np.nan)

    for column in FACTOR_COLUMNS:
        entity[column] = selected.get(column, np.nan)

    for column in QUALITY_COLUMNS:
        entity[column] = selected.get(column, np.nan)

    entity["pit_valid"] = safe_bool(
        entity["pit_valid"]
    )

    entity["financial_warning"] = (
        calculate_financial_warning(selected)
    )

    entity["data_quality_score"] = (
        calculate_data_quality_score(selected)
    )

    # Classification 단계에서 채울 자리
    entity["exchange"] = pd.NA
    entity["sector"] = pd.NA
    entity["industry"] = pd.NA
    entity["theme"] = pd.NA
    entity["sub_theme"] = pd.NA
    entity["market_cap"] = np.nan
    entity["is_ai_infrastructure"] = False
    entity["classification_rule"] = pd.NA
    entity["classification_score"] = np.nan

    result = EntityBuildResult(
        cik=cik,
        status="success",
        factor_file=str(factor_file),
        selected_period_end=(
            str(pd.Timestamp(entity["latest_period_end"]).date())
            if pd.notna(entity["latest_period_end"])
            else ""
        ),
        selected_filed=(
            str(pd.Timestamp(entity["latest_filed"]).date())
            if pd.notna(entity["latest_filed"])
            else ""
        ),
        selected_period_type=clean_text(
            entity["latest_period_type"]
        ),
        factor_rows=len(factors),
        ticker_found=bool(ticker),
        elapsed_seconds=time.perf_counter() - started,
    )

    return entity, result


# ============================================================
# 9-b. 회사명(entity_name) 보정
# ============================================================

def _build_name_maps(
    company_master_path: Path,
) -> tuple[dict[str, str], dict[str, str], int, int]:
    """
    sec_company_master.csv에서 cik→name, ticker→name 매핑을 만듭니다.

    반환: (cik_to_name, ticker_to_name, cik_dup_count, ticker_dup_count)

    - name 컬럼(없으면 company_name)에서 이름을 읽습니다.
    - 같은 cik/ticker에 서로 다른 이름이 매핑되는 "중복 매핑"은
      건수를 세어 반환하고, 첫 유효값을 대표로 사용합니다.
    """

    master = pd.read_csv(
        company_master_path,
        dtype=str,
        low_memory=False,
    )

    name_col = None
    for candidate in ["name", "company_name", "entity_name", "title"]:
        if candidate in master.columns:
            name_col = candidate
            break

    if name_col is None:
        raise KeyError(
            f"회사명 컬럼을 찾지 못했습니다: {company_master_path} "
            f"(컬럼: {list(master.columns)})"
        )

    master["_cik10"] = master["cik"].map(normalize_cik)
    master["_name"] = master[name_col].map(clean_text)

    master["_ticker"] = (
        master["ticker"].map(clean_text).str.upper()
        if "ticker" in master.columns
        else ""
    )

    valid = master.loc[master["_name"].ne("")].copy()

    # --- cik → name (서로 다른 이름이 걸린 cik = 중복 매핑) ---
    cik_valid = valid.loc[valid["_cik10"].ne("")]
    cik_distinct = (
        cik_valid.groupby("_cik10")["_name"].nunique()
    )
    cik_dup_count = int((cik_distinct > 1).sum())

    cik_to_name = (
        cik_valid.drop_duplicates(subset=["_cik10"], keep="first")
        .set_index("_cik10")["_name"]
        .to_dict()
    )

    # --- ticker → name (폴백용) ---
    ticker_valid = valid.loc[valid["_ticker"].ne("")]
    ticker_distinct = (
        ticker_valid.groupby("_ticker")["_name"].nunique()
    )
    ticker_dup_count = int((ticker_distinct > 1).sum())

    ticker_to_name = (
        ticker_valid.drop_duplicates(subset=["_ticker"], keep="first")
        .set_index("_ticker")["_name"]
        .to_dict()
    )

    return (
        cik_to_name,
        ticker_to_name,
        cik_dup_count,
        ticker_dup_count,
    )


def enrich_entity_names(
    master: pd.DataFrame,
    company_master_path: Path,
) -> pd.DataFrame:
    """
    entity_name을 sec_company_master 기준으로 보정합니다.

    우선순위
    --------
    1. 기존 entity_name 값이 있으면 그대로 유지
    2. 비어 있으면 cik 기준 name 사용
    3. cik 매칭이 안 되면 ticker 기준 name으로 폴백
    4. 중복 매핑은 cik 매칭을 우선하고 경고 로그 출력

    점수/선정/팩터 로직과 무관하게 entity_name 컬럼만 채웁니다.
    """

    if master.empty or "entity_name" not in master.columns:
        return master

    if not company_master_path.exists():
        print(
            f"[WARN] 회사명 원천 파일이 없어 entity_name 보정을 건너뜁니다: "
            f"{company_master_path}"
        )
        return master

    (
        cik_to_name,
        ticker_to_name,
        cik_dup_count,
        ticker_dup_count,
    ) = _build_name_maps(company_master_path)

    if cik_dup_count or ticker_dup_count:
        print(
            f"[WARN] 회사명 중복 매핑 감지 "
            f"(cik 기준 {cik_dup_count}건, ticker 기준 {ticker_dup_count}건). "
            f"cik 매칭을 우선하고 첫 유효값을 사용합니다."
        )

    enriched = master.copy()

    existing = enriched["entity_name"].map(clean_text)
    cik_key = enriched["cik"].map(normalize_cik)
    ticker_key = enriched["ticker"].map(clean_text).str.upper()

    cik_name = cik_key.map(cik_to_name).map(clean_text)
    ticker_name = ticker_key.map(ticker_to_name).map(clean_text)

    before_filled = int(existing.ne("").sum())

    # 1) 기존값 우선 → 2) cik name → 3) ticker name
    filled = existing.where(existing.ne(""), cik_name)
    filled = filled.where(filled.ne(""), ticker_name)
    filled = filled.fillna("")

    used_cik = (existing.eq("") & cik_name.ne("")).sum()
    used_ticker = (
        existing.eq("") & cik_name.eq("") & ticker_name.ne("")
    ).sum()

    total = len(enriched)
    unmatched_mask = filled.eq("")
    unmatched = int(unmatched_mask.sum())

    enriched["entity_name"] = filled.replace("", pd.NA)

    after_filled = int(filled.ne("").sum())

    print("\n" + "-" * 70)
    print("entity_name 보정 결과")
    print("-" * 70)
    print(f"대상 기업 수        : {total:,}")
    print(
        f"보정 전 채워짐      : {before_filled:,} "
        f"({before_filled / total * 100:.2f}%)"
    )
    print(f"cik 기준 채움       : {int(used_cik):,}")
    print(f"ticker 폴백 채움    : {int(used_ticker):,}")
    print(
        f"보정 후 채워짐      : {after_filled:,} "
        f"({after_filled / total * 100:.2f}%)"
    )
    print(f"미매칭(빈 값 유지)  : {unmatched:,}")
    if unmatched:
        sample = (
            enriched.loc[unmatched_mask, ["cik", "ticker"]]
            .head(10)
            .to_dict("records")
        )
        print(f"미매칭 예시(최대 10) : {sample}")
    print("-" * 70)

    return enriched


# ============================================================
# 10. Entity Master 후처리
# ============================================================

def finalize_entity_master(
    entities: list[dict[str, object]],
) -> pd.DataFrame:
    """전체 Entity 행을 정리하고 중복을 제거합니다."""
    if not entities:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    master = pd.DataFrame(entities)

    master = ensure_columns(
        master,
        OUTPUT_COLUMNS,
    )

    date_columns = [
        "latest_period_end",
        "latest_filed",
    ]

    for column in date_columns:
        master[column] = pd.to_datetime(
            master[column],
            errors="coerce",
        )

    numeric_columns = (
        FINANCIAL_COLUMNS
        + FACTOR_COLUMNS
        + [
            "factor_available_count",
            "source_fact_count",
            "data_quality_score",
            "market_cap",
            "classification_score",
        ]
    )

    for column in numeric_columns:
        master[column] = pd.to_numeric(
            master[column],
            errors="coerce",
        )

    master["pit_valid"] = master[
        "pit_valid"
    ].map(safe_bool)

    master["financial_warning"] = master[
        "financial_warning"
    ].map(safe_bool)

    master["is_ai_infrastructure"] = master[
        "is_ai_infrastructure"
    ].map(safe_bool)

    # CIK 중복이 있다면 품질점수가 높은 행을 유지
    master = master.sort_values(
        by=[
            "cik",
            "data_quality_score",
            "latest_filed",
            "latest_period_end",
        ],
        ascending=[
            True,
            False,
            False,
            False,
        ],
        na_position="last",
    )

    master = master.drop_duplicates(
        subset=["cik"],
        keep="first",
    )

    # ticker 중복은 ADR, 클래스주 등에서 가능하므로 제거하지 않음
    master = master.sort_values(
        by=[
            "ticker",
            "entity_name",
            "cik",
        ],
        ascending=True,
        na_position="last",
    ).reset_index(drop=True)

    return master[OUTPUT_COLUMNS]


# ============================================================
# 11. 품질 요약
# ============================================================

def print_quality_summary(
    master: pd.DataFrame,
) -> None:
    """Entity Master 품질 요약을 출력합니다."""
    total = len(master)

    if total == 0:
        print("Entity Master가 비어 있습니다.")
        return

    ticker_available = int(
        master["ticker"].astype(str).str.strip().ne("").sum()
    )

    annual_count = int(
        master["latest_period_type"].eq("annual").sum()
    )

    quarterly_count = int(
        master["latest_period_type"].eq("quarterly").sum()
    )

    pit_valid_count = int(
        master["pit_valid"].sum()
    )

    warning_count = int(
        master["financial_warning"].sum()
    )

    quality_mean = master[
        "data_quality_score"
    ].mean()

    print("\n" + "=" * 70)
    print("Entity Master 품질 요약")
    print("=" * 70)
    print(f"기업 수                 : {total:,}")
    print(
        f"ticker 확보             : "
        f"{ticker_available:,} "
        f"({ticker_available / total * 100:.2f}%)"
    )
    print(f"annual 선택             : {annual_count:,}")
    print(f"quarterly 선택          : {quarterly_count:,}")
    print(
        f"PIT 유효                : "
        f"{pit_valid_count:,} "
        f"({pit_valid_count / total * 100:.2f}%)"
    )
    print(
        f"재무 경고               : "
        f"{warning_count:,} "
        f"({warning_count / total * 100:.2f}%)"
    )
    print(
        f"평균 데이터 품질점수    : "
        f"{quality_mean:.2f}"
    )
    print("=" * 70)


# ============================================================
# 12. CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "기업별 Factor parquet를 읽어 "
            "Entity Master를 생성합니다."
        )
    )

    parser.add_argument(
        "--factors-dir",
        type=Path,
        default=DEFAULT_FACTORS_DIR,
        help="기업별 Factor parquet 폴더",
    )

    parser.add_argument(
        "--facts-dir",
        type=Path,
        default=DEFAULT_FACTS_DIR,
        help="ticker 보완용 Fact Store 폴더",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Entity Master 출력 폴더",
    )

    parser.add_argument(
        "--company-master",
        type=Path,
        default=DEFAULT_COMPANY_MASTER_PATH,
        help="entity_name 보정용 sec_company_master.csv 경로",
    )

    parser.add_argument(
        "--cik",
        type=str,
        default=None,
        help="특정 CIK 한 개만 처리",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="앞에서부터 지정 개수만 처리",
    )

    parser.add_argument(
        "--selection-mode",
        choices=[
            "annual_preferred",
            "annual_only",
            "latest_any",
        ],
        default="annual_preferred",
        help=(
            "대표 레코드 선택 방식 "
            "(기본: annual_preferred)"
        ),
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="기존 Entity Master 결과 덮어쓰기",
    )

    return parser.parse_args()


# ============================================================
# 13. Main
# ============================================================

def main() -> int:
    args = parse_args()

    factors_dir = args.factors_dir.resolve()
    facts_dir = args.facts_dir.resolve()
    output_dir = args.output_dir.resolve()

    parquet_file = (
        output_dir / DEFAULT_PARQUET_FILE.name
    )

    csv_file = (
        output_dir / DEFAULT_CSV_FILE.name
    )

    log_file = (
        output_dir / DEFAULT_LOG_FILE.name
    )

    error_file = (
        output_dir / DEFAULT_ERROR_FILE.name
    )

    if not factors_dir.exists():
        print(
            f"[ERROR] Factors 폴더가 없습니다: "
            f"{factors_dir}"
        )
        return 1

    if parquet_file.exists() and not args.overwrite:
        print(
            f"[SKIP] 기존 Entity Master가 있습니다: "
            f"{parquet_file}"
        )
        print(
            "다시 생성하려면 --overwrite를 사용하세요."
        )
        return 0

    try:
        factor_files = discover_factor_files(
            factors_dir=factors_dir,
            cik=args.cik,
            limit=args.limit,
        )
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1

    if not factor_files:
        print(
            f"[ERROR] 처리할 Factor parquet가 없습니다: "
            f"{factors_dir}"
        )
        return 1

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 70)
    print("Factor Store → Entity Master")
    print("=" * 70)
    print(f"Factors 폴더    : {factors_dir}")
    print(f"Facts 폴더      : {facts_dir}")
    print(f"출력 폴더       : {output_dir}")
    print(f"처리 대상       : {len(factor_files):,}개")
    print(f"선택 방식       : {args.selection_mode}")
    print(f"덮어쓰기        : {args.overwrite}")
    print("=" * 70)

    entities: list[dict[str, object]] = []
    results: list[EntityBuildResult] = []
    errors: list[dict[str, str]] = []

    for index, factor_file in enumerate(
        factor_files,
        start=1,
    ):
        cik = normalize_cik(factor_file.stem)

        try:
            entity, result = build_entity_row(
                factor_file=factor_file,
                facts_dir=facts_dir,
                selection_mode=args.selection_mode,
            )

            entities.append(entity)
            results.append(result)

            ticker_display = (
                entity["ticker"]
                if entity["ticker"]
                else "-"
            )

            print(
                f"[{index:,}/{len(factor_files):,}] "
                f"{cik} | {ticker_display} | 성공 | "
                f"{result.selected_period_type} | "
                f"{result.selected_period_end} | "
                f"{result.elapsed_seconds:.2f}초"
            )

        except Exception as exc:
            result = EntityBuildResult(
                cik=cik,
                status="failed",
                factor_file=str(factor_file),
                message=(
                    f"{type(exc).__name__}: {exc}"
                ),
            )

            results.append(result)

            errors.append(
                {
                    "cik": cik,
                    "factor_file": str(factor_file),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )

            print(
                f"[{index:,}/{len(factor_files):,}] "
                f"{cik} | 실패 | "
                f"{type(exc).__name__}: {exc}"
            )

    master = finalize_entity_master(entities)

    # 회사명 보정: sec_company_master.csv name을 cik 우선(→ticker 폴백)으로 조인
    master = enrich_entity_names(
        master=master,
        company_master_path=args.company_master.resolve(),
    )

    master.to_parquet(
        parquet_file,
        index=False,
    )

    master.to_csv(
        csv_file,
        index=False,
        encoding="utf-8-sig",
    )

    pd.DataFrame(
        [asdict(result) for result in results]
    ).to_csv(
        log_file,
        index=False,
        encoding="utf-8-sig",
    )

    if errors:
        pd.DataFrame(errors).to_csv(
            error_file,
            index=False,
            encoding="utf-8-sig",
        )
    elif error_file.exists():
        error_file.unlink()

    status_counts = pd.Series(
        [result.status for result in results]
    ).value_counts()

    success_count = int(
        status_counts.get("success", 0)
    )

    failed_count = int(
        status_counts.get("failed", 0)
    )

    print_quality_summary(master)

    print("\n저장 완료")
    print(f"Parquet : {parquet_file}")
    print(f"CSV     : {csv_file}")
    print(f"로그    : {log_file}")

    if errors:
        print(f"오류    : {error_file}")

    print("\n" + "=" * 70)
    print("실행 결과")
    print("=" * 70)
    print(f"전체    : {len(results):,}")
    print(f"성공    : {success_count:,}")
    print(f"실패    : {failed_count:,}")
    print(f"출력 행 : {len(master):,}")
    print("=" * 70)

    return 1 if success_count == 0 else 0


if __name__ == "__main__":
    sys.exit(main())