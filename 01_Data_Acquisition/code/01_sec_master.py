"""
01_sec_master.py

SEC에서 미국 상장기업 마스터 데이터를 수집하고
CSV와 Excel 파일로 저장한다.
"""

from pathlib import Path

import pandas as pd
import requests


# ============================================================
# 1. 기본 설정
# ============================================================

SEC_URL = "https://www.sec.gov/files/company_tickers_exchange.json"

HEADERS = {
    "User-Agent": "AI_Custom_Index pskl1206@gmail.com"
}


# ============================================================
# 2. SEC 기업 마스터 요청
# ============================================================

def request_company_master() -> requests.Response:
    """
    SEC에서 기업명, CIK, 티커, 거래소 정보를 요청한다.
    """

    response = requests.get(
        SEC_URL,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    return response


# ============================================================
# 3. JSON → DataFrame 변환
# ============================================================

def convert_to_dataframe(data: dict) -> pd.DataFrame:
    """
    SEC JSON 응답을 Pandas DataFrame으로 변환한다.
    """

    df = pd.DataFrame(
        data["data"],
        columns=data["fields"]
    )

    return df


# ============================================================
# 4. 데이터 저장
# ============================================================

def save_company_master(df: pd.DataFrame) -> None:
    """
    SEC 기업 마스터 데이터를 CSV와 Excel로 저장한다.
    """

    output_dir = Path("01_Data_Acquisition/output")
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "sec_company_master.csv"
    excel_path = output_dir / "sec_company_master.xlsx"

    df.to_csv(
        csv_path,
        index=False,
        encoding="utf-8-sig"
    )

    df.to_excel(
        excel_path,
        index=False
    )

    print()
    print("=" * 50)
    print("저장 완료")
    print("=" * 50)
    print("CSV 파일  :", csv_path)
    print("Excel 파일:", excel_path)


# ============================================================
# 5. 실행 흐름
# ============================================================

def main() -> None:
    """
    전체 실행 흐름을 관리한다.
    """

    print("=" * 50)
    print("SEC 기업 마스터 데이터 수집 시작")
    print("=" * 50)

    # 1. SEC API 요청
    response = request_company_master()

    print("Status Code:", response.status_code)

    # 2. JSON 변환
    data = response.json()

    # 3. DataFrame 변환
    df = convert_to_dataframe(data)

    # 4. 데이터 확인
    print()
    print("[데이터 미리보기]")
    print(df.head())

    print()
    print("[데이터 구조]")
    df.info()

    print()
    print("[데이터 크기]")
    print(df.shape)

    print()
    print("[거래소별 기업 수]")
    print(df["exchange"].value_counts(dropna=False))

    print()
    print("[결측치 개수]")
    print(df.isna().sum())

    # 5. 파일 저장
    save_company_master(df)


if __name__ == "__main__":
    main()