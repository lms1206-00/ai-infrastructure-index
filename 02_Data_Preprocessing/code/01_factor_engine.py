#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
01_factor_engine.py

기업별 SEC Fact Store(parquet)를 읽어 PIT 사용이 가능한 재무 팩터를 생성합니다.

입력 : data/facts/{CIK}.parquet
출력 : data/factors/{CIK}.parquet
로그 : data/factors/factor_engine_run_log.csv
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]
DEFAULT_FACTS_DIR = PROJECT_ROOT / "data" / "facts"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "factors"
DEFAULT_LOG_FILE = DEFAULT_OUTPUT_DIR / "factor_engine_run_log.csv"

# 국내 발행인(10-K/10-Q)뿐 아니라 외국 발행인(20-F/40-F 연차, 6-K 중간)도 지원한다.
# 20-F: 외국 민간 발행인 연차보고서, 40-F: 캐나다 발행인 연차보고서, 6-K: 외국 발행인 중간·수시보고서.
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
QUARTERLY_FORMS = {"10-Q", "10-Q/A", "6-K", "6-K/A"}
SUPPORTED_FORMS = ANNUAL_FORMS | QUARTERLY_FORMS

# anchor(재무제표 기간말) 후보에서 제외할 비재무 taxonomy.
# dei(표지·엔티티 정보), ecd(임원보상), srt/invest/ffd 등은 재무제표 기간말이 아니라
# 표지 "as of" 날짜(예: EntityCommonStockSharesOutstanding = 제출일 근처)를 담아,
# accession별 최대 end로 anchor를 잡으면 실제 재무 기간말과 어긋나 팩터 조인이 실패한다.
# 재무제표 taxonomy(us-gaap, ifrs-full)만 anchor 후보로 사용한다.
FINANCIAL_TAXONOMIES = {"us-gaap", "ifrs-full"}

# taxonomy가 없는 과거 데이터 호환용: 재무제표 기간말을 나타내지 않는 표지성 태그를
# 태그명으로도 직접 제외한다.
NON_PERIOD_TAGS = {
    "EntityCommonStockSharesOutstanding",
    "EntityPublicFloat",
    "DocumentPeriodEndDate",
    "EntityWellKnownSeasonedIssuer",
    "EntityVoluntaryFilers",
    "EntityCurrentReportingStatus",
    "EntityFilerCategory",
    "EntityEmergingGrowthCompany",
    "EntitySmallBusiness",
    "EntityShellCompany",
    "AmendmentFlag",
    "DocumentFiscalYearFocus",
    "DocumentFiscalPeriodFocus",
}

COLUMN_ALIASES = {
    "cik": ["cik", "CIK"],
    "entity_name": ["entity_name", "company_name", "entity", "name"],
    "taxonomy": ["taxonomy", "taxonomy_name", "taxonomy_id"],
    "tag": ["tag", "concept", "fact"],
    "unit": ["unit", "uom"],
    "value": ["value", "val", "fact_value"],
    "start": ["start", "start_date", "period_start"],
    "end": ["end", "end_date", "period_end"],
    "filed": ["filed", "filed_date", "filing_date"],
    "form": ["form", "form_type"],
    "accession": ["accession", "accn", "accession_number"],
    "fy": ["fy", "fiscal_year"],
    "fp": ["fp", "fiscal_period"],
}

# 태그는 우선순위 순서로 나열한다(앞이 우선). US-GAAP 태그를 먼저 두고,
# 외국 발행인(20-F/40-F/6-K)이 쓰는 IFRS(ifrs-full) 표준 태그를 그 뒤에 추가한다.
# IFRS 태그는 US-GAAP 값이 없을 때만 폴백으로 선택된다.
METRIC_TAGS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "SalesRevenueServicesNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        # --- IFRS ---
        "Revenue",
        "RevenueFromContractsWithCustomers",
    ],
    "operating_income": [
        "OperatingIncomeLoss",
        # --- IFRS ---
        "ProfitLossFromOperatingActivities",
    ],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",  # US-GAAP·IFRS 공통 태그명(총이익, NCI 포함)
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        # --- IFRS ---
        "ProfitLossAttributableToOwnersOfParent",
    ],
    "assets": ["Assets"],  # US-GAAP·IFRS 동일 태그명
    "liabilities": ["Liabilities"],  # US-GAAP·IFRS 동일 태그명
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "PartnersCapital",
        # --- IFRS ---
        "Equity",
        "EquityAttributableToOwnersOfParent",
    ],
    "current_assets": [
        "AssetsCurrent",
        # --- IFRS ---
        "CurrentAssets",
    ],
    "current_liabilities": [
        "LiabilitiesCurrent",
        # --- IFRS ---
        "CurrentLiabilities",
    ],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        # --- IFRS ---
        "CashFlowsFromUsedInOperatingActivities",
    ],
    "capital_expenditure": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForAdditionsToPropertyPlantAndEquipment",
        # --- IFRS ---
        "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    ],
}

# 손익·현금흐름처럼 기간(start~end duration)에 따라 값이 달라지는 "플로우" 지표.
# 동일 end date에 단일기간값과 누적(YTD)값이 함께 존재할 수 있어 duration 검토가 필요하다.
# 대차대조표 지표(assets/liabilities/equity/current_*)는 시점값이라 duration 무관.
FLOW_METRICS = {
    "revenue", "operating_income", "net_income",
    "operating_cash_flow", "capital_expenditure",
}

OUTPUT_COLUMNS = [
    "cik", "entity_name", "period_end", "filed", "form", "accession",
    "fiscal_year", "fiscal_period", "period_type",
    "revenue", "operating_income", "net_income", "assets", "liabilities",
    "equity", "current_assets", "current_liabilities",
    "operating_cash_flow", "capital_expenditure",
    "revenue_growth", "operating_income_growth", "net_income_growth",
    "asset_growth", "operating_margin", "net_margin", "roa", "roe",
    "debt_ratio", "debt_to_equity", "current_ratio", "ocf_to_assets",
    "free_cash_flow_proxy", "factor_available_count", "source_fact_count",
    "pit_valid",
]


@dataclass
class BuildResult:
    cik: str
    status: str
    input_rows: int = 0
    output_rows: int = 0
    output_file: str = ""
    elapsed_seconds: float = 0.0
    message: str = ""


def normalize_cik(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(10) if digits else ""


def find_column(df: pd.DataFrame, standard_name: str) -> Optional[str]:
    lower_map = {str(col).lower(): col for col in df.columns}
    for alias in COLUMN_ALIASES[standard_name]:
        if alias in df.columns:
            return alias
        if alias.lower() in lower_map:
            return lower_map[alias.lower()]
    return None


def standardize_fact_store(df: pd.DataFrame, fallback_cik: str) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for name in COLUMN_ALIASES:
        actual = find_column(df, name)
        out[name] = df[actual] if actual else pd.NA

    out["cik"] = out["cik"].map(normalize_cik)
    out.loc[out["cik"].eq(""), "cik"] = fallback_cik
    out["entity_name"] = out["entity_name"].astype("string")
    out["taxonomy"] = out["taxonomy"].astype("string").str.lower().str.strip()
    out["tag"] = out["tag"].astype("string")
    out["unit"] = out["unit"].astype("string")
    out["form"] = out["form"].astype("string").str.upper().str.strip()
    out["accession"] = out["accession"].astype("string")
    out["fp"] = out["fp"].astype("string").str.upper().str.strip()
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out["fy"] = pd.to_numeric(out["fy"], errors="coerce").astype("Int64")

    for col in ["start", "end", "filed"]:
        out[col] = pd.to_datetime(out[col], errors="coerce")

    out = out.dropna(subset=["tag", "value", "end", "filed"])
    out = out[out["form"].isin(SUPPORTED_FORMS)].copy()
    out = out[out["filed"] >= out["end"]].copy()
    out = out.drop_duplicates(
        subset=["cik", "tag", "unit", "value", "start", "end", "filed", "form", "accession", "fy", "fp"],
        keep="last",
    )
    return out.reset_index(drop=True)


def safe_divide(numerator: object, denominator: object) -> float:
    try:
        n, d = float(numerator), float(denominator)
    except (TypeError, ValueError):
        return np.nan
    if not np.isfinite(n) or not np.isfinite(d) or d == 0:
        return np.nan
    return n / d


def safe_growth(current: object, previous: object) -> float:
    try:
        c, p = float(current), float(previous)
    except (TypeError, ValueError):
        return np.nan
    if not np.isfinite(c) or not np.isfinite(p) or p == 0:
        return np.nan
    return c / p - 1.0


def period_type(form: str) -> str:
    return "annual" if form in ANNUAL_FORMS else "quarterly"


def fiscal_period(form: str, fp: object) -> str:
    text = str(fp).upper().strip()
    if text not in {"", "<NA>", "NAN", "NONE"}:
        return text
    return "FY" if form in ANNUAL_FORMS else "Q"


def build_anchors(facts: pd.DataFrame) -> pd.DataFrame:
    # anchor의 기간말(end)은 반드시 재무제표 fact에서만 도출한다.
    # 표지성 fact(dei:EntityCommonStockSharesOutstanding 등)는 제출일 근처 "as of"
    # 날짜를 담아, 이를 anchor로 잡으면 실제 재무 기간말과 어긋나 팩터 조인이 실패한다.
    period_facts = facts
    if "taxonomy" in facts.columns and facts["taxonomy"].notna().any():
        period_facts = facts[facts["taxonomy"].isin(FINANCIAL_TAXONOMIES)]
    # taxonomy가 없거나 필터 결과가 비면(구버전 데이터 호환) 태그명 기반으로 표지 태그만 제외.
    if period_facts.empty:
        period_facts = facts[~facts["tag"].isin(NON_PERIOD_TAGS)]
    else:
        period_facts = period_facts[~period_facts["tag"].isin(NON_PERIOD_TAGS)]
    if period_facts.empty:
        period_facts = facts

    anchors = period_facts[["cik", "entity_name", "end", "filed", "form", "accession", "fy", "fp"]].copy()
    anchors["accession_key"] = anchors["accession"].astype("string")
    missing = anchors["accession_key"].isna() | anchors["accession_key"].isin(["", "<NA>", "nan", "None"])
    anchors.loc[missing, "accession_key"] = (
        anchors.loc[missing, "filed"].astype(str) + "|" +
        anchors.loc[missing, "end"].astype(str) + "|" +
        anchors.loc[missing, "form"].astype(str) + "|" +
        anchors.loc[missing, "fy"].astype(str) + "|" +
        anchors.loc[missing, "fp"].astype(str)
    )
    anchors = anchors.sort_values(["filed", "end", "accession_key"])
    anchors = anchors.drop_duplicates("accession_key", keep="last")
    anchors["period_type"] = anchors["form"].map(period_type)
    anchors["fiscal_period"] = [
        fiscal_period(form, fp) for form, fp in zip(anchors["form"], anchors["fp"])
    ]
    return anchors.reset_index(drop=True)


def choose_metric_fact(
    facts: pd.DataFrame,
    metric: str,
    anchor_end: pd.Timestamp,
    anchor_filed: pd.Timestamp,
    anchor_form: str,
    anchor_fy: object,
    anchor_fp: object,
) -> Optional[pd.Series]:
    tags = METRIC_TAGS[metric]
    candidates = facts[
        facts["tag"].isin(tags)
        & (facts["filed"] <= anchor_filed)
        & (facts["end"] == anchor_end)
    ].copy()
    if candidates.empty:
        return None

    cycle_forms = ANNUAL_FORMS if anchor_form in ANNUAL_FORMS else QUARTERLY_FORMS
    same_cycle = candidates[candidates["form"].isin(cycle_forms)]
    if not same_cycle.empty:
        candidates = same_cycle

    if pd.notna(anchor_fy):
        same_fy = candidates[candidates["fy"] == anchor_fy]
        if not same_fy.empty:
            candidates = same_fy

    fp_text = str(anchor_fp).upper().strip()
    if fp_text not in {"", "<NA>", "NAN", "NONE", "Q"}:
        same_fp = candidates[candidates["fp"] == fp_text]
        if not same_fp.empty:
            candidates = same_fp

    # 플로우 지표는 duration으로 걸러 누적(YTD)값을 단일기간값과 혼동하지 않도록 한다.
    # 연차 앵커는 약 1년(≈365일), 분기 앵커는 단일 분기(≈90일)를 선호한다.
    # start가 없거나 목표 구간에 해당하는 후보가 없으면 필터를 적용하지 않는다(폴백).
    candidates["duration_gap"] = 0
    if metric in FLOW_METRICS and "start" in candidates.columns:
        duration = (candidates["end"] - candidates["start"]).dt.days
        if anchor_form in ANNUAL_FORMS:
            target, low, high = 365, 300, 400
        else:
            target, low, high = 90, 55, 115
        in_band = candidates[duration.between(low, high)].copy()
        if not in_band.empty:
            candidates = in_band
            candidates["duration_gap"] = (
                (candidates["end"] - candidates["start"]).dt.days - target
            ).abs()

    rank = {tag: idx for idx, tag in enumerate(tags)}
    candidates["tag_rank"] = candidates["tag"].map(rank).fillna(len(tags))
    # 태그 우선순위 → duration 근접도 → 최신 제출 → accession 순으로 선택.
    candidates = candidates.sort_values(
        ["tag_rank", "duration_gap", "filed", "accession"],
        ascending=[True, True, False, False],
        na_position="last",
    )
    return candidates.iloc[0]


def previous_comparable(rows: list[dict], current: dict) -> Optional[dict]:
    candidates = [
        row for row in rows
        if row["period_type"] == current["period_type"]
        and pd.Timestamp(row["period_end"]) < pd.Timestamp(current["period_end"])
    ]
    if not candidates:
        return None

    current_fy = current.get("fiscal_year")
    current_fp = current.get("fiscal_period")

    if current["period_type"] == "annual" and pd.notna(current_fy):
        exact = [
            row for row in candidates
            if pd.notna(row.get("fiscal_year")) and int(row["fiscal_year"]) == int(current_fy) - 1
        ]
        if exact:
            return max(exact, key=lambda row: pd.Timestamp(row["period_end"]))

    if current["period_type"] == "quarterly":
        exact = [
            row for row in candidates
            if row.get("fiscal_period") == current_fp
            and (
                pd.isna(current_fy)
                or pd.isna(row.get("fiscal_year"))
                or int(row["fiscal_year"]) == int(current_fy) - 1
            )
        ]
        if exact:
            return max(exact, key=lambda row: pd.Timestamp(row["period_end"]))

    return max(candidates, key=lambda row: pd.Timestamp(row["period_end"]))


def add_derived_factors(row: dict, previous: Optional[dict]) -> None:
    row["revenue_growth"] = safe_growth(row["revenue"], previous["revenue"]) if previous else np.nan
    row["operating_income_growth"] = safe_growth(row["operating_income"], previous["operating_income"]) if previous else np.nan
    row["net_income_growth"] = safe_growth(row["net_income"], previous["net_income"]) if previous else np.nan
    row["asset_growth"] = safe_growth(row["assets"], previous["assets"]) if previous else np.nan

    row["operating_margin"] = safe_divide(row["operating_income"], row["revenue"])
    row["net_margin"] = safe_divide(row["net_income"], row["revenue"])

    avg_assets = row["assets"]
    avg_equity = row["equity"]
    if previous:
        if pd.notna(row["assets"]) and pd.notna(previous.get("assets")):
            avg_assets = (float(row["assets"]) + float(previous["assets"])) / 2
        if pd.notna(row["equity"]) and pd.notna(previous.get("equity")):
            avg_equity = (float(row["equity"]) + float(previous["equity"])) / 2

    row["roa"] = safe_divide(row["net_income"], avg_assets)
    row["roe"] = safe_divide(row["net_income"], avg_equity)
    row["debt_ratio"] = safe_divide(row["liabilities"], row["assets"])
    row["debt_to_equity"] = safe_divide(row["liabilities"], row["equity"])
    row["current_ratio"] = safe_divide(row["current_assets"], row["current_liabilities"])
    row["ocf_to_assets"] = safe_divide(row["operating_cash_flow"], avg_assets)

    if pd.notna(row["operating_cash_flow"]) and pd.notna(row["capital_expenditure"]):
        row["free_cash_flow_proxy"] = float(row["operating_cash_flow"]) - abs(float(row["capital_expenditure"]))
    else:
        row["free_cash_flow_proxy"] = np.nan

    factor_cols = [
        "revenue_growth", "operating_income_growth", "net_income_growth", "asset_growth",
        "operating_margin", "net_margin", "roa", "roe", "debt_ratio",
        "debt_to_equity", "current_ratio", "ocf_to_assets", "free_cash_flow_proxy",
    ]
    row["factor_available_count"] = sum(pd.notna(row[col]) for col in factor_cols)


def build_factor_dataframe(raw: pd.DataFrame, fallback_cik: str) -> pd.DataFrame:
    facts = standardize_fact_store(raw, fallback_cik)
    if facts.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    anchors = build_anchors(facts).sort_values(["end", "filed", "accession_key"])
    rows: list[dict] = []

    for _, anchor in anchors.iterrows():
        row = {
            "cik": normalize_cik(anchor["cik"]),
            "entity_name": anchor["entity_name"],
            "period_end": anchor["end"],
            "filed": anchor["filed"],
            "form": anchor["form"],
            "accession": anchor["accession"],
            "fiscal_year": anchor["fy"],
            "fiscal_period": anchor["fiscal_period"],
            "period_type": anchor["period_type"],
        }

        source_dates: list[pd.Timestamp] = []
        source_count = 0

        for metric in METRIC_TAGS:
            chosen = choose_metric_fact(
                facts=facts,
                metric=metric,
                anchor_end=anchor["end"],
                anchor_filed=anchor["filed"],
                anchor_form=anchor["form"],
                anchor_fy=anchor["fy"],
                anchor_fp=anchor["fp"],
            )
            if chosen is None:
                row[metric] = np.nan
            else:
                row[metric] = chosen["value"]
                source_dates.append(chosen["filed"])
                source_count += 1

        if pd.isna(row["liabilities"]) and pd.notna(row["assets"]) and pd.notna(row["equity"]):
            row["liabilities"] = float(row["assets"]) - float(row["equity"])

        previous = previous_comparable(rows, row)
        add_derived_factors(row, previous)
        row["source_fact_count"] = source_count
        row["pit_valid"] = all(date <= anchor["filed"] for date in source_dates)
        rows.append(row)

    output = pd.DataFrame(rows)
    output = output.replace([np.inf, -np.inf], np.nan)
    output = output.sort_values(["period_end", "filed", "accession"])
    output = output.drop_duplicates(
        subset=["cik", "period_end", "filed", "form", "accession"],
        keep="last",
    )
    for col in OUTPUT_COLUMNS:
        if col not in output.columns:
            output[col] = pd.NA
    return output[OUTPUT_COLUMNS].reset_index(drop=True)


def build_one_file(input_file: Path, output_dir: Path, overwrite: bool) -> BuildResult:
    started = time.perf_counter()
    cik = normalize_cik(input_file.stem)
    output_file = output_dir / f"{cik}.parquet"

    if output_file.exists() and not overwrite:
        return BuildResult(cik, "skipped", output_file=str(output_file), message="output exists")

    try:
        raw = pd.read_parquet(input_file)
        factors = build_factor_dataframe(raw, cik)
        output_dir.mkdir(parents=True, exist_ok=True)
        factors.to_parquet(output_file, index=False)
        return BuildResult(
            cik=cik,
            status="success",
            input_rows=len(raw),
            output_rows=len(factors),
            output_file=str(output_file),
            elapsed_seconds=time.perf_counter() - started,
        )
    except Exception as exc:
        return BuildResult(
            cik=cik,
            status="failed",
            output_file=str(output_file),
            elapsed_seconds=time.perf_counter() - started,
            message=f"{type(exc).__name__}: {exc}",
        )


def discover_files(facts_dir: Path, cik: Optional[str], limit: Optional[int]) -> list[Path]:
    if cik:
        path = facts_dir / f"{normalize_cik(cik)}.parquet"
        if not path.exists():
            raise FileNotFoundError(path)
        files = [path]
    else:
        files = sorted(facts_dir.glob("*.parquet"))
    return files[:limit] if limit is not None else files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SEC Fact Store에서 PIT 재무 팩터를 생성합니다.")
    parser.add_argument("--facts-dir", type=Path, default=DEFAULT_FACTS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG_FILE)
    parser.add_argument("--cik", type=str, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    facts_dir = args.facts_dir.resolve()
    output_dir = args.output_dir.resolve()
    log_file = args.log_file.resolve()

    if not facts_dir.exists():
        print(f"[ERROR] Fact Store 폴더가 없습니다: {facts_dir}")
        return 1

    try:
        files = discover_files(facts_dir, args.cik, args.limit)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1

    if not files:
        print(f"[ERROR] 처리할 parquet 파일이 없습니다: {facts_dir}")
        return 1

    print("=" * 70)
    print("SEC Fact Store → PIT Factor Engine")
    print("=" * 70)
    print(f"입력 폴더 : {facts_dir}")
    print(f"출력 폴더 : {output_dir}")
    print(f"처리 대상 : {len(files):,}개")
    print(f"덮어쓰기 : {args.overwrite}\n")

    results: list[BuildResult] = []
    for idx, input_file in enumerate(files, start=1):
        result = build_one_file(input_file, output_dir, args.overwrite)
        results.append(result)
        if result.status == "success":
            print(
                f"[{idx:,}/{len(files):,}] {result.cik} 성공 | "
                f"입력 {result.input_rows:,}행 → 출력 {result.output_rows:,}행 | "
                f"{result.elapsed_seconds:.2f}초"
            )
        elif result.status == "skipped":
            print(f"[{idx:,}/{len(files):,}] {result.cik} 건너뜀 | 기존 파일 존재")
        else:
            print(f"[{idx:,}/{len(files):,}] {result.cik} 실패 | {result.message}")

    log_file.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([asdict(result) for result in results]).to_csv(
        log_file, index=False, encoding="utf-8-sig"
    )

    status = pd.Series([result.status for result in results]).value_counts()
    print("\n" + "=" * 70)
    print("실행 요약")
    print("=" * 70)
    print(f"전체   : {len(results):,}")
    print(f"성공   : {int(status.get('success', 0)):,}")
    print(f"건너뜀 : {int(status.get('skipped', 0)):,}")
    print(f"실패   : {int(status.get('failed', 0)):,}")
    print(f"로그   : {log_file}")

    return 1 if all(result.status == "failed" for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())