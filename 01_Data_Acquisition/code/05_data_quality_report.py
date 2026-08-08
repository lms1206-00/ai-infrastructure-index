"""
05_data_quality_report.py

Financial Master 데이터를 읽어
데이터 품질을 검증한다.
"""

from pathlib import Path

import pandas as pd


# ============================================================
# 1. 경로 설정
# ============================================================

INPUT_PATH = Path(
    "01_Data_Acquisition/output/financial_master_test.csv"
)

OUTPUT_PATH = Path(
    "01_Data_Acquisition/output/coverage_summary.csv"
)


# ============================================================
# 2. 데이터 불러오기
# ============================================================

def load_financial_master() -> pd.DataFrame:

    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"{INPUT_PATH} 파일이 없습니다."
        )

    return pd.read_csv(INPUT_PATH)


# ============================================================
# 3. Coverage 계산
# ============================================================

def calculate_coverage(df: pd.DataFrame) -> pd.DataFrame:

    metrics = [
        "revenue",
        "operating_income",
        "net_income",
        "assets",
        "liabilities",
    ]

    result = []

    total = len(df)

    for metric in metrics:

        available = df[metric].notna().sum()

        missing = df[metric].isna().sum()

        coverage = available / total * 100

        result.append(
            {
                "Metric": metric,
                "Available": available,
                "Missing": missing,
                "Coverage(%)": round(
                    coverage,
                    2,
                ),
            }
        )

    return pd.DataFrame(result)


# ============================================================
# 4. Period Consistency
# ============================================================

def period_consistency(df):

    return (
        df["period_consistent"]
        .value_counts(dropna=False)
    )


# ============================================================
# 5. Summary 출력
# ============================================================

def print_summary(
    coverage_df,
    consistency,
    total,
):

    print("=" * 60)
    print("Financial Data Quality Report")
    print("=" * 60)

    print(f"총 기업 : {total}")

    print()

    print(coverage_df)

    print()

    print("=" * 60)
    print("Period Consistency")
    print("=" * 60)

    print(consistency)


# ============================================================
# 6. 저장
# ============================================================

def save_summary(
    coverage_df,
):

    coverage_df.to_csv(
        OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print()

    print("저장 완료")

    print(OUTPUT_PATH)


# ============================================================
# 7. 실행
# ============================================================

def main():

    df = load_financial_master()

    coverage_df = calculate_coverage(df)

    consistency = period_consistency(df)

    print_summary(
        coverage_df,
        consistency,
        len(df),
    )

    save_summary(
        coverage_df,
    )


if __name__ == "__main__":
    main()