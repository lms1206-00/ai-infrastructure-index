"""
03_classification_rule.py
---------------------------------
AI 인프라 후보군을 Entity Master와 매칭한 뒤, 테마별 쿼터와 데이터 품질
점수를 적용해 최종 100개 종목을 선정합니다.

입력
----
data/entity_master/entity_master.parquet
data/classification/ai_infrastructure_candidates.csv

출력
----
data/classification/classified_entity_master.parquet
data/classification/classified_entity_master.csv
data/classification/final_universe_100.parquet
data/classification/final_universe_100.csv
data/classification/classification_summary.csv
data/classification/unmatched_candidates.csv
data/classification/classification_run_log.csv

기본 선정 규칙
-------------
1. 후보 CSV에 등록된 티커만 AI 인프라 후보로 인정
2. Entity Master와 티커 기준 매칭
3. 다음 점수로 테마 내부 순위 산정
   - AI 관련성 점수: 60%
   - 데이터 품질 점수: 25%
   - 팩터 가용성 점수: 15%
4. 테마별 목표 종목 수를 우선 충족
5. 테마 부족분은 전체 잔여 후보 중 고득점 순으로 보충
6. 기본적으로 정확히 100개가 안 되면 오류 처리

실행
----
python 02_Data_Preprocessing/code/03_classification_rule.py --overwrite

100개 미만도 임시 허용하려면
----
python 02_Data_Preprocessing/code/03_classification_rule.py --overwrite --allow-fewer
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# 1. 경로
# ============================================================

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]

DEFAULT_INPUT_FILE = PROJECT_ROOT / "data" / "entity_master" / "entity_master.parquet"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "classification"
DEFAULT_CANDIDATE_FILE = DEFAULT_OUTPUT_DIR / "ai_infrastructure_candidates.csv"

DEFAULT_CLASSIFIED_PARQUET = DEFAULT_OUTPUT_DIR / "classified_entity_master.parquet"
DEFAULT_CLASSIFIED_CSV = DEFAULT_OUTPUT_DIR / "classified_entity_master.csv"
DEFAULT_UNIVERSE_PARQUET = DEFAULT_OUTPUT_DIR / "final_universe_100.parquet"
DEFAULT_UNIVERSE_CSV = DEFAULT_OUTPUT_DIR / "final_universe_100.csv"
DEFAULT_SUMMARY_FILE = DEFAULT_OUTPUT_DIR / "classification_summary.csv"
DEFAULT_UNMATCHED_FILE = DEFAULT_OUTPUT_DIR / "unmatched_candidates.csv"
DEFAULT_LOG_FILE = DEFAULT_OUTPUT_DIR / "classification_run_log.csv"


# ============================================================
# 2. 목표 테마 쿼터: 합계 100
# ============================================================

THEME_QUOTAS = {
    "Semiconductor": 30,
    "Server": 10,
    "Networking": 10,
    "Data Center": 6,
    "Power": 15,
    "Cooling": 8,
    "Optical": 6,
    "Storage": 5,
    "Cloud": 5,
    "Industrial Automation": 5,
}

TARGET_COUNT = sum(THEME_QUOTAS.values())


# ============================================================
# 3. 기본 후보군
#    candidate_score: AI 인프라 직접 관련성 사전점수(0~100)
# ============================================================

SEED_CANDIDATES = [
    # Semiconductor
    ("NVDA", "Semiconductor", "GPU", 100),
    ("AMD", "Semiconductor", "GPU", 97),
    ("AVGO", "Semiconductor", "AI Accelerator / Networking ASIC", 96),
    ("MRVL", "Semiconductor", "Data Center ASIC", 94),
    ("INTC", "Semiconductor", "CPU / Foundry", 88),
    ("MU", "Semiconductor", "Memory / HBM", 94),
    ("QCOM", "Semiconductor", "Processor", 79),
    ("TXN", "Semiconductor", "Analog / Power Semiconductor", 78),
    ("ADI", "Semiconductor", "Analog / Signal Processing", 78),
    ("MCHP", "Semiconductor", "MCU / Connectivity", 73),
    ("NXPI", "Semiconductor", "Processor / Connectivity", 75),
    ("ON", "Semiconductor", "Power Semiconductor", 78),
    ("MPWR", "Semiconductor", "Power Management IC", 87),
    ("SWKS", "Semiconductor", "Connectivity Semiconductor", 70),
    ("QRVO", "Semiconductor", "RF Semiconductor", 69),
    ("LSCC", "Semiconductor", "FPGA", 83),
    ("ALGM", "Semiconductor", "Power / Sensor IC", 72),
    ("ARM", "Semiconductor", "CPU Architecture", 88),
    ("TSM", "Semiconductor", "Foundry", 98),
    ("GFS", "Semiconductor", "Foundry", 82),
    ("UMC", "Semiconductor", "Foundry", 74),
    ("ASX", "Semiconductor", "Packaging / Testing", 76),
    ("ASML", "Semiconductor", "Lithography Equipment", 98),
    ("AMAT", "Semiconductor", "Wafer Equipment", 94),
    ("LRCX", "Semiconductor", "Wafer Equipment", 94),
    ("KLAC", "Semiconductor", "Process Control", 93),
    ("TER", "Semiconductor", "Test Equipment", 83),
    ("ENTG", "Semiconductor", "Materials / Process Products", 84),
    ("MKSI", "Semiconductor", "Process Equipment Components", 78),
    ("ACLS", "Semiconductor", "Ion Implantation Equipment", 82),
    ("COHU", "Semiconductor", "Test / Inspection Equipment", 73),
    ("ONTO", "Semiconductor", "Inspection / Metrology", 84),
    ("FORM", "Semiconductor", "Probe Cards", 79),
    ("AMKR", "Semiconductor", "Packaging / Testing", 79),
    ("WOLF", "Semiconductor", "Power Semiconductor", 69),
    ("CRDO", "Semiconductor", "High-Speed Connectivity IC", 89),

    # Server
    ("SMCI", "Server", "AI Server", 100),
    ("DELL", "Server", "Enterprise / AI Server", 91),
    ("HPE", "Server", "Enterprise / HPC Server", 88),
    ("IBM", "Server", "Enterprise Computing", 74),
    ("JBL", "Server", "Data Center Manufacturing", 84),
    ("FLEX", "Server", "Electronics Manufacturing", 78),
    ("CLS", "Server", "Data Center Hardware Manufacturing", 83),
    ("SANM", "Server", "Electronics Manufacturing", 72),
    ("CDW", "Server", "IT Infrastructure Distribution", 68),
    ("NTNX", "Server", "Hyperconverged Infrastructure", 84),
    ("VYX", "Server", "Enterprise Hardware", 60),
    ("PAR", "Server", "Computing Systems", 55),

    # Networking
    ("ANET", "Networking", "Data Center Switching", 100),
    ("CSCO", "Networking", "Network Equipment", 90),
    ("JNPR", "Networking", "Network Equipment", 87),
    ("FFIV", "Networking", "Application Delivery", 78),
    ("UI", "Networking", "Network Equipment", 73),
    ("EXTR", "Networking", "Enterprise Networking", 76),
    ("CALX", "Networking", "Broadband Network Platform", 72),
    ("COMM", "Networking", "Network Infrastructure", 71),
    ("NOK", "Networking", "Telecom Network Equipment", 70),
    ("ERIC", "Networking", "Telecom Network Equipment", 70),
    ("CMBM", "Networking", "Wireless Networking", 62),
    ("AKAM", "Networking", "Edge Network / CDN", 82),
    ("NET", "Networking", "Edge Network / CDN", 87),
    ("CSGS", "Networking", "Network Software Infrastructure", 58),

    # Data Center
    ("EQIX", "Data Center", "Colocation / Interconnection", 100),
    ("DLR", "Data Center", "Data Center REIT", 98),
    ("IRM", "Data Center", "Data Center / Digital Infrastructure", 81),
    ("AMT", "Data Center", "Digital Infrastructure REIT", 72),
    ("CCI", "Data Center", "Digital Infrastructure REIT", 68),
    ("SBAC", "Data Center", "Digital Infrastructure REIT", 65),
    ("GDS", "Data Center", "Data Center Operator", 90),
    ("VNET", "Data Center", "Data Center Operator", 84),
    ("UNIT", "Data Center", "Fiber / Digital Infrastructure REIT", 66),

    # Power
    ("VRT", "Power", "Data Center Power Management", 100),
    ("ETN", "Power", "Electrical Equipment", 95),
    ("PWR", "Power", "Grid / Electrical Infrastructure", 92),
    ("HUBB", "Power", "Electrical Equipment", 88),
    ("GNRC", "Power", "Backup Power", 85),
    ("NVT", "Power", "Electrical Connection / Protection", 90),
    ("GEV", "Power", "Grid / Power Generation", 91),
    ("CMI", "Power", "Power Generation Equipment", 78),
    ("MTZ", "Power", "Infrastructure Construction", 75),
    ("MYRG", "Power", "Electrical Construction", 82),
    ("ATKR", "Power", "Electrical Infrastructure Products", 82),
    ("ENS", "Power", "Energy Storage Systems", 78),
    ("ABB", "Power", "Electrification", 91),
    ("AME", "Power", "Electrical Instruments", 78),
    ("PH", "Power", "Motion / Power Systems", 75),
    ("AEP", "Power", "Electric Utility", 67),
    ("CEG", "Power", "Electric Power Generation", 82),
    ("NRG", "Power", "Electric Power Generation", 70),
    ("VST", "Power", "Electric Power Generation", 79),
    ("NEE", "Power", "Electric Utility", 71),
    ("SO", "Power", "Electric Utility", 68),
    ("DUK", "Power", "Electric Utility", 67),

    # Cooling
    ("CARR", "Cooling", "HVAC / Data Center Cooling", 91),
    ("TT", "Cooling", "HVAC / Thermal Management", 93),
    ("JCI", "Cooling", "Building Cooling Systems", 86),
    ("MOD", "Cooling", "Thermal Management", 90),
    ("AAON", "Cooling", "HVAC Equipment", 86),
    ("FIX", "Cooling", "Mechanical / HVAC Services", 84),
    ("WTS", "Cooling", "Water / Thermal Systems", 76),
    ("BMI", "Cooling", "Flow Measurement", 66),
    ("LII", "Cooling", "HVAC Equipment", 82),
    ("NDSN", "Cooling", "Precision Fluid Systems", 68),
    ("SPXC", "Cooling", "Cooling / Thermal Equipment", 84),
    ("ITRI", "Cooling", "Energy / Water Management", 65),

    # Optical
    ("COHR", "Optical", "Optical Components", 96),
    ("LITE", "Optical", "Optical Components", 94),
    ("CIEN", "Optical", "Optical Networking", 92),
    ("VIAV", "Optical", "Optical Test / Components", 82),
    ("AAOI", "Optical", "Optical Transceivers", 88),
    ("IPGP", "Optical", "Fiber Lasers", 72),
    ("MTSI", "Optical", "Optical / RF Semiconductors", 86),
    ("FN", "Optical", "Optical Manufacturing", 85),
    ("GLW", "Optical", "Fiber / Glass Infrastructure", 78),

    # Storage
    ("PSTG", "Storage", "Enterprise Flash Storage", 96),
    ("NTAP", "Storage", "Enterprise Data Storage", 92),
    ("WDC", "Storage", "Data Storage Hardware", 86),
    ("STX", "Storage", "Data Storage Hardware", 84),
    ("DELL", "Storage", "Enterprise Storage", 84),
    ("HPE", "Storage", "Enterprise Storage", 80),
    ("IBM", "Storage", "Enterprise Storage", 66),

    # Cloud
    ("MSFT", "Cloud", "Hyperscale Cloud", 100),
    ("AMZN", "Cloud", "Hyperscale Cloud", 100),
    ("GOOGL", "Cloud", "Hyperscale Cloud", 98),
    ("GOOG", "Cloud", "Hyperscale Cloud", 98),
    ("ORCL", "Cloud", "Cloud Infrastructure", 92),
    ("IBM", "Cloud", "Hybrid Cloud", 72),
    ("SNOW", "Cloud", "Cloud Data Platform", 83),
    ("DDOG", "Cloud", "Cloud Monitoring Platform", 79),
    ("DOCN", "Cloud", "Cloud Infrastructure", 75),
    ("MDB", "Cloud", "Cloud Database Platform", 71),

    # Industrial Automation
    ("ROK", "Industrial Automation", "Industrial Controls", 90),
    ("EMR", "Industrial Automation", "Industrial Automation", 88),
    ("HON", "Industrial Automation", "Automation / Controls", 84),
    ("ABB", "Industrial Automation", "Automation / Electrification", 88),
    ("PH", "Industrial Automation", "Motion / Control", 78),
    ("AME", "Industrial Automation", "Electronic Instruments", 76),
    ("KEYS", "Industrial Automation", "Electronic Test Equipment", 82),
    ("TRMB", "Industrial Automation", "Industrial Technology", 70),
    ("CGNX", "Industrial Automation", "Machine Vision", 84),
    ("ZBRA", "Industrial Automation", "Enterprise Automation Hardware", 74),
    ("NOVT", "Industrial Automation", "Precision Technology", 72),
]


# ============================================================
# 4. 도우미
# ============================================================

@dataclass
class RunLog:
    total_entities: int
    candidate_rows: int
    unique_candidate_tickers: int
    matched_candidates: int
    unmatched_candidates: int
    selected_count: int
    target_count: int
    elapsed_seconds: float
    input_file: str
    candidate_file: str
    output_file: str


def clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "<na>", "nat"} else text


def normalize_ticker(value: object) -> str:
    text = clean_text(value).upper()
    return re.sub(r"[^A-Z0-9.\-]", "", text)


def minmax_score(series: pd.Series, default: float = 50.0) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() == 0:
        return pd.Series(default, index=series.index, dtype=float)

    low = numeric.min()
    high = numeric.max()

    if not np.isfinite(low) or not np.isfinite(high) or high == low:
        result = pd.Series(default, index=series.index, dtype=float)
        result.loc[numeric.notna()] = default
        return result

    return ((numeric - low) / (high - low) * 100).fillna(default)


def create_candidate_file(path: Path) -> None:
    if path.exists():
        return

    path.parent.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(
        SEED_CANDIDATES,
        columns=[
            "ticker",
            "theme",
            "sub_theme",
            "candidate_score",
        ],
    )

    df["include"] = True
    df["note"] = ""
    df.to_csv(path, index=False, encoding="utf-8-sig")


def read_entity_master(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Entity Master가 없습니다: {path}")

    if path.suffix.lower() == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, dtype={"cik": "string"})

    for required in ["cik", "ticker", "entity_name"]:
        if required not in df.columns:
            raise ValueError(f"Entity Master 필수 컬럼 누락: {required}")

    df = df.copy()
    df["ticker"] = df["ticker"].map(normalize_ticker)
    df = df[df["ticker"].ne("")].copy()

    # 동일 티커가 여러 번 있으면 데이터 품질이 가장 높은 행을 사용
    if "data_quality_score" not in df.columns:
        df["data_quality_score"] = np.nan
    if "factor_available_count" not in df.columns:
        df["factor_available_count"] = np.nan

    df["_quality_sort"] = pd.to_numeric(
        df["data_quality_score"], errors="coerce"
    ).fillna(-1)

    df = (
        df.sort_values(["ticker", "_quality_sort"], ascending=[True, False])
        .drop_duplicates("ticker", keep="first")
        .drop(columns="_quality_sort")
        .reset_index(drop=True)
    )

    return df


def read_candidates(path: Path) -> pd.DataFrame:
    create_candidate_file(path)
    df = pd.read_csv(path, dtype={"ticker": "string"})

    required = ["ticker", "theme", "sub_theme", "candidate_score"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"후보 CSV 필수 컬럼 누락: {missing}")

    if "include" not in df.columns:
        df["include"] = True
    if "note" not in df.columns:
        df["note"] = ""

    df["ticker"] = df["ticker"].map(normalize_ticker)
    df["theme"] = df["theme"].map(clean_text)
    df["sub_theme"] = df["sub_theme"].map(clean_text)
    df["candidate_score"] = pd.to_numeric(
        df["candidate_score"], errors="coerce"
    ).fillna(0).clip(0, 100)

    include_text = df["include"].astype(str).str.strip().str.lower()
    df["include"] = include_text.isin({"true", "1", "yes", "y", "t"})

    df = df[df["include"] & df["ticker"].ne("")].copy()

    invalid_themes = sorted(set(df["theme"]) - set(THEME_QUOTAS))
    if invalid_themes:
        raise ValueError(
            "후보 CSV에 쿼터가 정의되지 않은 테마가 있습니다: "
            + ", ".join(invalid_themes)
        )

    # 동일 티커가 여러 테마에 중복된 경우 candidate_score가 높은 행 우선
    df = (
        df.sort_values(
            ["ticker", "candidate_score"],
            ascending=[True, False],
        )
        .drop_duplicates("ticker", keep="first")
        .reset_index(drop=True)
    )

    return df


def build_candidate_table(
    entities: pd.DataFrame,
    candidates: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    merged = candidates.merge(
        entities,
        on="ticker",
        how="left",
        suffixes=("_candidate", ""),
        indicator=True,
    )

    unmatched = merged[merged["_merge"] == "left_only"].copy()
    matched = merged[merged["_merge"] == "both"].copy()

    matched = matched.drop(columns="_merge")
    unmatched = unmatched.drop(columns="_merge")

    # Entity Master에 기존 theme/sub_theme 등이 있으면 merge 후 후보 CSV 컬럼이
    # theme_candidate, sub_theme_candidate 형태로 바뀔 수 있다.
    # 최종 분류에는 반드시 후보 CSV의 값을 사용하도록 표준 컬럼으로 복원한다.
    candidate_column_map = {
        "theme_candidate": "theme",
        "sub_theme_candidate": "sub_theme",
        "candidate_score_candidate": "candidate_score",
        "include_candidate": "include",
        "note_candidate": "note",
    }

    for source_column, target_column in candidate_column_map.items():
        if source_column in matched.columns:
            matched[target_column] = matched[source_column]
        if source_column in unmatched.columns:
            unmatched[target_column] = unmatched[source_column]

    # 혹시 기존 Entity Master 분류 컬럼이 남아 있어도 후보 CSV 기준 컬럼이
    # 존재하는지 확인한다.
    required_candidate_columns = [
        "theme",
        "sub_theme",
        "candidate_score",
    ]
    missing_candidate_columns = [
        column
        for column in required_candidate_columns
        if column not in matched.columns
    ]
    if missing_candidate_columns:
        raise KeyError(
            "후보 분류 컬럼을 복원하지 못했습니다: "
            + ", ".join(missing_candidate_columns)
        )

    quality_score = minmax_score(matched["data_quality_score"])
    factor_score = minmax_score(matched["factor_available_count"])

    matched["ai_relevance_score"] = matched["candidate_score"]
    matched["quality_component"] = quality_score
    matched["factor_component"] = factor_score

    matched["selection_score"] = (
        matched["ai_relevance_score"] * 0.60
        + matched["quality_component"] * 0.25
        + matched["factor_component"] * 0.15
    ).round(4)

    matched["is_ai_infrastructure"] = True
    matched["classification_rule"] = "curated_candidate_universe"
    matched["classification_source"] = "candidate_csv"
    matched["classification_score"] = matched["ai_relevance_score"]

    return matched, unmatched


def select_exact_universe(
    matched: pd.DataFrame,
    target_count: int,
) -> pd.DataFrame:
    selected_parts: list[pd.DataFrame] = []
    selected_tickers: set[str] = set()

    # 1차: 테마별 쿼터
    for theme, quota in THEME_QUOTAS.items():
        theme_rows = matched[
            (matched["theme"] == theme)
            & (~matched["ticker"].isin(selected_tickers))
        ].sort_values(
            ["selection_score", "candidate_score", "ticker"],
            ascending=[False, False, True],
        )

        chosen = theme_rows.head(quota).copy()
        chosen["quota_theme"] = theme
        chosen["selection_stage"] = "theme_quota"

        selected_parts.append(chosen)
        selected_tickers.update(chosen["ticker"].tolist())

    selected = (
        pd.concat(selected_parts, ignore_index=True)
        if selected_parts
        else pd.DataFrame(columns=matched.columns)
    )

    # 2차: 테마 부족분을 전체 잔여 고득점 후보로 보충
    shortage = target_count - len(selected)

    if shortage > 0:
        remaining = matched[
            ~matched["ticker"].isin(selected_tickers)
        ].sort_values(
            ["selection_score", "candidate_score", "ticker"],
            ascending=[False, False, True],
        )

        filler = remaining.head(shortage).copy()
        filler["quota_theme"] = filler["theme"]
        filler["selection_stage"] = "shortage_fill"

        selected = pd.concat(
            [selected, filler],
            ignore_index=True,
        )

    # 3차: 정확히 target_count만 유지
    selected = (
        selected.sort_values(
            ["selection_score", "candidate_score", "ticker"],
            ascending=[False, False, True],
        )
        .drop_duplicates("ticker", keep="first")
        .head(target_count)
        .reset_index(drop=True)
    )

    selected["universe_rank"] = np.arange(1, len(selected) + 1)
    selected["selected_for_index"] = True

    return selected


def build_summary(
    matched: pd.DataFrame,
    selected: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for theme, quota in THEME_QUOTAS.items():
        candidate_count = int((matched["theme"] == theme).sum())
        selected_count = int((selected["theme"] == theme).sum())

        rows.append(
            {
                "theme": theme,
                "target_quota": quota,
                "matched_candidates": candidate_count,
                "selected_count": selected_count,
                "quota_gap": selected_count - quota,
            }
        )

    rows.append(
        {
            "theme": "TOTAL",
            "target_quota": TARGET_COUNT,
            "matched_candidates": len(matched),
            "selected_count": len(selected),
            "quota_gap": len(selected) - TARGET_COUNT,
        }
    )

    return pd.DataFrame(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI 인프라 후보군에서 최종 100개 종목을 선정합니다."
    )

    parser.add_argument("--input-file", type=Path, default=DEFAULT_INPUT_FILE)
    parser.add_argument("--candidate-file", type=Path, default=DEFAULT_CANDIDATE_FILE)
    parser.add_argument("--target-count", type=int, default=TARGET_COUNT)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--allow-fewer",
        action="store_true",
        help="매칭 후보가 부족할 경우 100개 미만 결과도 저장",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started = time.perf_counter()

    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_files = [
        DEFAULT_CLASSIFIED_PARQUET,
        DEFAULT_CLASSIFIED_CSV,
        DEFAULT_UNIVERSE_PARQUET,
        DEFAULT_UNIVERSE_CSV,
        DEFAULT_SUMMARY_FILE,
        DEFAULT_UNMATCHED_FILE,
        DEFAULT_LOG_FILE,
    ]

    if any(path.exists() for path in output_files) and not args.overwrite:
        print("[SKIP] 기존 결과 파일이 있습니다. 다시 생성하려면 --overwrite를 사용하세요.")
        return 0

    try:
        entities = read_entity_master(args.input_file.resolve())
        candidates = read_candidates(args.candidate_file.resolve())

        matched, unmatched = build_candidate_table(
            entities=entities,
            candidates=candidates,
        )

        selected = select_exact_universe(
            matched=matched,
            target_count=args.target_count,
        )

        if len(selected) < args.target_count and not args.allow_fewer:
            raise RuntimeError(
                f"최종 {args.target_count}개를 채우지 못했습니다. "
                f"현재 매칭 후보는 {len(matched):,}개, 최종 선택은 {len(selected):,}개입니다. "
                f"{DEFAULT_UNMATCHED_FILE.name}을 확인해 후보 티커를 보완하거나 "
                "--allow-fewer 옵션으로 임시 실행하세요."
            )

        # 전체 Entity Master에 분류 결과 표시
        classification_columns = matched[
            [
                "ticker",
                "theme",
                "sub_theme",
                "candidate_score",
                "selection_score",
                "is_ai_infrastructure",
                "classification_rule",
                "classification_source",
                "classification_score",
            ]
        ].copy()

        # 이전 실행 결과가 Entity Master에 남아 있어도 _x / _y 충돌이 발생하지 않도록
        # 기존 분류 관련 컬럼을 제거한 뒤 새 분류 결과를 병합한다.
        classification_output_columns = [
            "theme",
            "sub_theme",
            "candidate_score",
            "selection_score",
            "is_ai_infrastructure",
            "classification_rule",
            "classification_source",
            "classification_score",
            "selected_for_index",
            "universe_rank",
        ]

        entities_clean = entities.drop(
            columns=[
                column
                for column in classification_output_columns
                if column in entities.columns
            ],
            errors="ignore",
        ).copy()

        classified = entities_clean.merge(
            classification_columns,
            on="ticker",
            how="left",
            validate="one_to_one",
        )

        # 매칭 결과가 0개인 경우에도 컬럼이 항상 존재하도록 방어적으로 생성
        if "is_ai_infrastructure" not in classified.columns:
            classified["is_ai_infrastructure"] = False
        else:
            classified["is_ai_infrastructure"] = (
                classified["is_ai_infrastructure"].fillna(False).astype(bool)
            )

        classified["selected_for_index"] = classified["ticker"].isin(
            selected["ticker"]
        )

        rank_map = (
            selected.set_index("ticker")["universe_rank"]
            if not selected.empty
            else pd.Series(dtype=float)
        )
        classified["universe_rank"] = classified["ticker"].map(rank_map)

        summary = build_summary(matched, selected)

        classified.to_parquet(DEFAULT_CLASSIFIED_PARQUET, index=False)
        classified.to_csv(
            DEFAULT_CLASSIFIED_CSV,
            index=False,
            encoding="utf-8-sig",
        )

        selected.to_parquet(DEFAULT_UNIVERSE_PARQUET, index=False)
        selected.to_csv(
            DEFAULT_UNIVERSE_CSV,
            index=False,
            encoding="utf-8-sig",
        )

        summary.to_csv(
            DEFAULT_SUMMARY_FILE,
            index=False,
            encoding="utf-8-sig",
        )

        unmatched.to_csv(
            DEFAULT_UNMATCHED_FILE,
            index=False,
            encoding="utf-8-sig",
        )

        run_log = RunLog(
            total_entities=len(entities),
            candidate_rows=len(candidates),
            unique_candidate_tickers=candidates["ticker"].nunique(),
            matched_candidates=len(matched),
            unmatched_candidates=len(unmatched),
            selected_count=len(selected),
            target_count=args.target_count,
            elapsed_seconds=round(time.perf_counter() - started, 4),
            input_file=str(args.input_file.resolve()),
            candidate_file=str(args.candidate_file.resolve()),
            output_file=str(DEFAULT_UNIVERSE_PARQUET),
        )

        pd.DataFrame([asdict(run_log)]).to_csv(
            DEFAULT_LOG_FILE,
            index=False,
            encoding="utf-8-sig",
        )

        print("\n" + "=" * 70)
        print("AI 인프라 최종 유니버스 선정 결과")
        print("=" * 70)
        print(f"Entity Master 기업 수 : {len(entities):,}")
        print(f"후보 티커 수          : {len(candidates):,}")
        print(f"매칭 성공             : {len(matched):,}")
        print(f"매칭 실패             : {len(unmatched):,}")
        print(f"최종 선정             : {len(selected):,} / {args.target_count:,}")
        print("-" * 70)

        for _, row in summary[summary["theme"] != "TOTAL"].iterrows():
            print(
                f"{row['theme']:<24} "
                f"{int(row['selected_count']):>3} / {int(row['target_quota']):>3}"
            )

        print("=" * 70)
        print(f"최종 유니버스 : {DEFAULT_UNIVERSE_CSV}")
        print(f"분류 전체본   : {DEFAULT_CLASSIFIED_CSV}")
        print(f"테마 요약     : {DEFAULT_SUMMARY_FILE}")
        print(f"미매칭 후보   : {DEFAULT_UNMATCHED_FILE}")
        print(f"실행 로그     : {DEFAULT_LOG_FILE}")

        return 0

    except Exception as exc:
        import traceback

        print(f"[ERROR] {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())