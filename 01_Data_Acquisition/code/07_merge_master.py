"""
07_merge_master.py

SEC Financial Master와
Yahoo Market Master를 병합하여

Integrated Master를 생성한다.
"""

from pathlib import Path

import pandas as pd


# ============================================================
# 1. 경로 설정
# ============================================================

FINANCIAL_PATH = Path(
    "01_Data_Acquisition/output/financial_master_test.csv"
)

YAHOO_PATH = Path(
    "01_Data_Acquisition/output/yahoo_market_test.csv"
)

OUTPUT_CSV = Path(
    "01_Data_Acquisition/output/integrated_master_test.csv"
)

OUTPUT_EXCEL = Path(
    "01_Data_Acquisition/output/integrated_master_test.xlsx"
)


# ============================================================
# 2. 데이터 불러오기
# ============================================================

def load_data():

    financial_df = pd.read_csv(
        FINANCIAL_PATH
    )

    yahoo_df = pd.read_csv(
        YAHOO_PATH
    )

    return financial_df, yahoo_df


# ============================================================
# 3. 병합
# ============================================================

def merge_data(
    financial_df,
    yahoo_df,
):

    merged = pd.merge(
        financial_df,
        yahoo_df,
        on="ticker",
        how="left",
        suffixes=(
            "_sec",
            "_yahoo",
        ),
    )

    return merged


# ============================================================
# 4. 품질검사
# ============================================================

def validate_data(
    merged,
):

    print("=" * 60)
    print("Integrated Master Validation")
    print("=" * 60)

    print()

    print("행 개수 :", len(merged))

    print()

    print("중복 티커 :", merged["ticker"].duplicated().sum())

    print()

    check_columns = [
        "revenue",
        "market_cap",
        "sector",
        "industry",
    ]

    print("결측치")

    for col in check_columns:

        missing = merged[col].isna().sum()

        print(f"{col:<15} : {missing}")


# ============================================================
# 5. 저장
# ============================================================

def save_data(
    merged,
):

    merged.to_csv(
        OUTPUT_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    merged.to_excel(
        OUTPUT_EXCEL,
        index=False,
    )

    print()

    print("저장 완료")

    print(OUTPUT_CSV)

    print(OUTPUT_EXCEL)


# ============================================================
# 6. 실행
# ============================================================

def main():

    financial_df, yahoo_df = load_data()

    merged = merge_data(
        financial_df,
        yahoo_df,
    )

    validate_data(
        merged,
    )

    save_data(
        merged,
    )

    print()

    print("=" * 60)
    print("Integrated Master Preview")
    print("=" * 60)

    preview_columns = [
        "ticker",
        "company_name_sec",
        "revenue",
        "market_cap",
        "sector",
        "industry",
    ]

    available = [
        col
        for col in preview_columns
        if col in merged.columns
    ]

    print(
        merged[
            available
        ]
    )


if __name__ == "__main__":
    main()