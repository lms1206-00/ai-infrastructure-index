"""
08_integrated_master_report.py

SEC 재무데이터와 Yahoo 시장데이터를 결합한
Integrated Master의 품질을 검증하고
요약 리포트를 생성한다.
"""

from pathlib import Path

import pandas as pd


# ============================================================
# 1. 경로 설정
# ============================================================

INPUT_PATH = Path(
    "01_Data_Acquisition/output/integrated_master_test.csv"
)

OUTPUT_DIR = Path(
    "01_Data_Acquisition/output"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

COVERAGE_OUTPUT_PATH = (
    OUTPUT_DIR / "integrated_coverage_report.csv"
)

SUMMARY_OUTPUT_PATH = (
    OUTPUT_DIR / "integrated_summary_report.csv"
)

SECTOR_OUTPUT_PATH = (
    OUTPUT_DIR / "sector_distribution.csv"
)

INDUSTRY_OUTPUT_PATH = (
    OUTPUT_DIR / "industry_distribution.csv"
)


# ============================================================
# 2. 검증 대상 컬럼
# ============================================================

QUALITY_COLUMNS = [
    "revenue",
    "operating_income",
    "net_income",
    "assets",
    "liabilities",
    "market_cap",
    "sector",
    "industry",
    "country",
    "average_volume",
    "latest_close",
]

NUMERIC_SUMMARY_COLUMNS = [
    "revenue",
    "operating_income",
    "net_income",
    "assets",
    "liabilities",
    "market_cap",
    "average_volume",
    "latest_close",
]


# ============================================================
# 3. 데이터 불러오기
# ============================================================

def load_integrated_master() -> pd.DataFrame:
    """
    Integrated Master CSV 파일을 불러온다.
    """

    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"Integrated Master 파일을 찾지 못했습니다: "
            f"{INPUT_PATH}"
        )

    integrated_df = pd.read_csv(
        INPUT_PATH,
        dtype={"cik": str},
    )

    if integrated_df.empty:
        raise ValueError(
            "Integrated Master 데이터가 비어 있습니다."
        )

    if "ticker" not in integrated_df.columns:
        raise ValueError(
            "Integrated Master에 ticker 컬럼이 없습니다."
        )

    return integrated_df


# ============================================================
# 4. 기본 데이터 현황 계산
# ============================================================

def calculate_basic_summary(
    integrated_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    전체 행 수, 컬럼 수, 중복 티커 수 등을 계산한다.
    """

    summary_rows = [
        {
            "item": "total_companies",
            "value": len(integrated_df),
        },
        {
            "item": "total_columns",
            "value": len(integrated_df.columns),
        },
        {
            "item": "duplicate_tickers",
            "value": int(
                integrated_df["ticker"]
                .duplicated()
                .sum()
            ),
        },
        {
            "item": "unique_tickers",
            "value": int(
                integrated_df["ticker"]
                .nunique(dropna=True)
            ),
        },
    ]

    if "period_consistent" in integrated_df.columns:
        consistent_count = (
            integrated_df["period_consistent"]
            .eq(True)
            .sum()
        )

        inconsistent_count = (
            integrated_df["period_consistent"]
            .eq(False)
            .sum()
        )

        summary_rows.extend(
            [
                {
                    "item": "period_consistent_true",
                    "value": int(consistent_count),
                },
                {
                    "item": "period_consistent_false",
                    "value": int(inconsistent_count),
                },
            ]
        )

    return pd.DataFrame(summary_rows)


# ============================================================
# 5. 컬럼별 Coverage 계산
# ============================================================

def calculate_coverage_report(
    integrated_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    주요 컬럼의 확보 개수, 결측 개수, 확보율을 계산한다.
    """

    total_count = len(integrated_df)
    coverage_rows = []

    for column in QUALITY_COLUMNS:
        if column not in integrated_df.columns:
            coverage_rows.append(
                {
                    "column": column,
                    "exists": False,
                    "available": 0,
                    "missing": total_count,
                    "coverage_pct": 0.0,
                }
            )
            continue

        available_count = int(
            integrated_df[column]
            .notna()
            .sum()
        )

        missing_count = int(
            integrated_df[column]
            .isna()
            .sum()
        )

        coverage_pct = (
            available_count
            / total_count
            * 100
            if total_count
            else 0.0
        )

        coverage_rows.append(
            {
                "column": column,
                "exists": True,
                "available": available_count,
                "missing": missing_count,
                "coverage_pct": round(
                    coverage_pct,
                    2,
                ),
            }
        )

    return pd.DataFrame(coverage_rows)


# ============================================================
# 6. 숫자형 데이터 요약통계
# ============================================================

def calculate_numeric_summary(
    integrated_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    시가총액 및 주요 재무데이터의 요약통계를 계산한다.
    """

    summary_rows = []

    for column in NUMERIC_SUMMARY_COLUMNS:
        if column not in integrated_df.columns:
            continue

        numeric_series = pd.to_numeric(
            integrated_df[column],
            errors="coerce",
        )

        valid_series = numeric_series.dropna()

        if valid_series.empty:
            summary_rows.append(
                {
                    "column": column,
                    "count": 0,
                    "mean": None,
                    "median": None,
                    "min": None,
                    "max": None,
                    "std": None,
                }
            )
            continue

        summary_rows.append(
            {
                "column": column,
                "count": int(
                    valid_series.count()
                ),
                "mean": float(
                    valid_series.mean()
                ),
                "median": float(
                    valid_series.median()
                ),
                "min": float(
                    valid_series.min()
                ),
                "max": float(
                    valid_series.max()
                ),
                "std": float(
                    valid_series.std()
                )
                if len(valid_series) > 1
                else 0.0,
            }
        )

    return pd.DataFrame(summary_rows)


# ============================================================
# 7. Sector 분포
# ============================================================

def calculate_sector_distribution(
    integrated_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Sector별 기업 수와 비중을 계산한다.
    """

    if "sector" not in integrated_df.columns:
        return pd.DataFrame(
            columns=[
                "sector",
                "company_count",
                "share_pct",
            ]
        )

    sector_series = (
        integrated_df["sector"]
        .fillna("Missing")
        .astype(str)
        .str.strip()
        .replace("", "Missing")
    )

    sector_df = (
        sector_series
        .value_counts(dropna=False)
        .rename_axis("sector")
        .reset_index(name="company_count")
    )

    sector_df["share_pct"] = (
        sector_df["company_count"]
        / len(integrated_df)
        * 100
    ).round(2)

    return sector_df


# ============================================================
# 8. Industry 분포
# ============================================================

def calculate_industry_distribution(
    integrated_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Industry별 기업 수와 비중을 계산한다.
    """

    if "industry" not in integrated_df.columns:
        return pd.DataFrame(
            columns=[
                "industry",
                "company_count",
                "share_pct",
            ]
        )

    industry_series = (
        integrated_df["industry"]
        .fillna("Missing")
        .astype(str)
        .str.strip()
        .replace("", "Missing")
    )

    industry_df = (
        industry_series
        .value_counts(dropna=False)
        .rename_axis("industry")
        .reset_index(name="company_count")
    )

    industry_df["share_pct"] = (
        industry_df["company_count"]
        / len(integrated_df)
        * 100
    ).round(2)

    return industry_df


# ============================================================
# 9. 이상값 간단 검증
# ============================================================

def validate_numeric_values(
    integrated_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    음수 또는 비정상적인 숫자 데이터 개수를 확인한다.
    """

    check_rules = {
        "revenue": "negative",
        "assets": "negative",
        "liabilities": "negative",
        "market_cap": "non_positive",
        "average_volume": "negative",
        "latest_close": "non_positive",
    }

    issue_rows = []

    for column, rule in check_rules.items():
        if column not in integrated_df.columns:
            continue

        values = pd.to_numeric(
            integrated_df[column],
            errors="coerce",
        )

        if rule == "negative":
            issue_count = int(
                values.lt(0).sum()
            )

        elif rule == "non_positive":
            issue_count = int(
                values.le(0).sum()
            )

        else:
            issue_count = 0

        issue_rows.append(
            {
                "column": column,
                "rule": rule,
                "issue_count": issue_count,
            }
        )

    return pd.DataFrame(issue_rows)


# ============================================================
# 10. 콘솔 출력
# ============================================================

def print_report(
    integrated_df: pd.DataFrame,
    basic_summary_df: pd.DataFrame,
    coverage_df: pd.DataFrame,
    numeric_summary_df: pd.DataFrame,
    sector_df: pd.DataFrame,
    industry_df: pd.DataFrame,
    numeric_issues_df: pd.DataFrame,
) -> None:
    """
    통합 데이터 품질 리포트를 터미널에 출력한다.
    """

    print("=" * 70)
    print("Integrated Master Quality Report")
    print("=" * 70)

    print()
    print("[기본 현황]")
    print(
        basic_summary_df.to_string(
            index=False
        )
    )

    print()
    print("[컬럼별 확보율]")
    print(
        coverage_df.to_string(
            index=False
        )
    )

    print()
    print("[Period Consistency]")

    if "period_consistent" in integrated_df.columns:
        print(
            integrated_df[
                "period_consistent"
            ].value_counts(
                dropna=False
            )
        )
    else:
        print(
            "period_consistent 컬럼이 없습니다."
        )

    print()
    print("[Sector 분포]")
    print(
        sector_df.to_string(
            index=False
        )
    )

    print()
    print("[Industry 분포]")
    print(
        industry_df.head(20).to_string(
            index=False
        )
    )

    print()
    print("[숫자형 요약통계]")
    print(
        numeric_summary_df.to_string(
            index=False
        )
    )

    print()
    print("[숫자 데이터 이상값]")
    print(
        numeric_issues_df.to_string(
            index=False
        )
    )


# ============================================================
# 11. 파일 저장
# ============================================================

def save_reports(
    basic_summary_df: pd.DataFrame,
    coverage_df: pd.DataFrame,
    numeric_summary_df: pd.DataFrame,
    sector_df: pd.DataFrame,
    industry_df: pd.DataFrame,
    numeric_issues_df: pd.DataFrame,
) -> None:
    """
    분석 결과를 CSV와 하나의 Excel 파일로 저장한다.
    """

    coverage_df.to_csv(
        COVERAGE_OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    basic_summary_df.to_csv(
        SUMMARY_OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    sector_df.to_csv(
        SECTOR_OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    industry_df.to_csv(
        INDUSTRY_OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    excel_path = (
        OUTPUT_DIR
        / "integrated_master_quality_report.xlsx"
    )

    with pd.ExcelWriter(
        excel_path,
        engine="openpyxl",
    ) as writer:
        basic_summary_df.to_excel(
            writer,
            sheet_name="basic_summary",
            index=False,
        )

        coverage_df.to_excel(
            writer,
            sheet_name="coverage",
            index=False,
        )

        numeric_summary_df.to_excel(
            writer,
            sheet_name="numeric_summary",
            index=False,
        )

        sector_df.to_excel(
            writer,
            sheet_name="sector",
            index=False,
        )

        industry_df.to_excel(
            writer,
            sheet_name="industry",
            index=False,
        )

        numeric_issues_df.to_excel(
            writer,
            sheet_name="numeric_issues",
            index=False,
        )

    print()
    print("=" * 70)
    print("리포트 저장 완료")
    print("=" * 70)
    print("Coverage:", COVERAGE_OUTPUT_PATH)
    print("Summary:", SUMMARY_OUTPUT_PATH)
    print("Sector:", SECTOR_OUTPUT_PATH)
    print("Industry:", INDUSTRY_OUTPUT_PATH)
    print("Excel:", excel_path)


# ============================================================
# 12. 실행 흐름
# ============================================================

def main() -> None:
    """
    Integrated Master 품질 검증 전체 흐름을 실행한다.
    """

    integrated_df = (
        load_integrated_master()
    )

    basic_summary_df = (
        calculate_basic_summary(
            integrated_df
        )
    )

    coverage_df = (
        calculate_coverage_report(
            integrated_df
        )
    )

    numeric_summary_df = (
        calculate_numeric_summary(
            integrated_df
        )
    )

    sector_df = (
        calculate_sector_distribution(
            integrated_df
        )
    )

    industry_df = (
        calculate_industry_distribution(
            integrated_df
        )
    )

    numeric_issues_df = (
        validate_numeric_values(
            integrated_df
        )
    )

    print_report(
        integrated_df=integrated_df,
        basic_summary_df=basic_summary_df,
        coverage_df=coverage_df,
        numeric_summary_df=numeric_summary_df,
        sector_df=sector_df,
        industry_df=industry_df,
        numeric_issues_df=numeric_issues_df,
    )

    save_reports(
        basic_summary_df=basic_summary_df,
        coverage_df=coverage_df,
        numeric_summary_df=numeric_summary_df,
        sector_df=sector_df,
        industry_df=industry_df,
        numeric_issues_df=numeric_issues_df,
    )


if __name__ == "__main__":
    main()