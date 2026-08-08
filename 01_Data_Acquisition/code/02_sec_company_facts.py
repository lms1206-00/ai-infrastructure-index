"""
02_sec_company_facts.py

SEC 기업 마스터에서 CIK를 조회하고,
SEC Company Facts API에 연결하여
US-GAAP 핵심 재무 태그를 확인하고
최신 연간 매출액을 추출한다.
"""

from pathlib import Path

import pandas as pd
import requests


# ============================================================
# 1. 기본 설정
# ============================================================

COMPANY_MASTER_PATH = Path(
    "01_Data_Acquisition/output/sec_company_master.csv"
)

SEC_COMPANY_FACTS_URL = (
    "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
)

HEADERS = {
    "User-Agent": "AI_Custom_Index pskl1206@example.com",
    "Accept-Encoding": "gzip, deflate",
}


# ============================================================
# 2. 기업 마스터 불러오기
# ============================================================

def load_company_master() -> pd.DataFrame:
    """
    저장된 SEC 기업 마스터 CSV 파일을 불러온다.
    """

    company_master = pd.read_csv(
        COMPANY_MASTER_PATH,
        dtype={"cik": str},
    )

    return company_master


# ============================================================
# 3. 티커로 CIK 찾기
# ============================================================

def find_cik(
    company_master: pd.DataFrame,
    ticker: str,
) -> str:
    """
    입력한 티커에 해당하는 SEC CIK를 반환한다.
    """

    ticker_series = (
        company_master["ticker"]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    target = company_master.loc[
        ticker_series == ticker.upper().strip()
    ]

    if target.empty:
        raise ValueError(
            f"기업 마스터에서 {ticker}를 찾지 못했습니다."
        )

    cik = str(target.iloc[0]["cik"]).zfill(10)

    return cik


# ============================================================
# 4. SEC Company Facts 요청
# ============================================================

def request_company_facts(cik: str) -> requests.Response:
    """
    SEC Company Facts API에 기업 재무데이터를 요청한다.
    """

    url = SEC_COMPANY_FACTS_URL.format(cik=cik)

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    return response


# ============================================================
# 5. US-GAAP 태그 검색
# ============================================================

def search_tag(
    us_gaap: dict,
    keyword: str,
) -> list[str]:
    """
    US-GAAP 태그 중 특정 키워드가 포함된 태그를 검색한다.
    """

    matched_tags = []

    for tag in us_gaap.keys():
        if keyword.lower() in tag.lower():
            matched_tags.append(tag)

    return matched_tags


# ============================================================
# 6. 대표 매출 태그 선택
# ============================================================

def find_revenue_tag(
    us_gaap: dict,
) -> str | None:
    """
    기업의 대표 매출 태그를 우선순위에 따라 선택한다.
    """

    priority_tags = [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ]

    for tag in priority_tags:
        if tag in us_gaap:
            return tag

    return None


# ============================================================
# 7. 특정 태그 구조 확인
# ============================================================

def show_tag_structure(
    us_gaap: dict,
    tag_name: str,
) -> None:
    """
    특정 US-GAAP 태그의 내부 구조를 출력한다.
    """

    if tag_name not in us_gaap:
        print(f"{tag_name} 태그를 찾지 못했습니다.")
        return

    tag_data = us_gaap[tag_name]

    print("태그명:", tag_name)
    print("라벨:", tag_data.get("label"))
    print("설명:", tag_data.get("description"))
    print("내부 키:", tag_data.keys())
    print(
        "단위 목록:",
        tag_data.get("units", {}).keys(),
    )


# ============================================================
# 8. 최신 연간 재무값 추출
# ============================================================

def extract_latest_annual_value(
    us_gaap: dict,
    tag_name: str,
    unit: str = "USD",
) -> dict | None:
    """
    특정 US-GAAP 태그에서 최신 10-K 연간 값을 추출한다.
    """

    if tag_name not in us_gaap:
        return None

    tag_data = us_gaap[tag_name]

    unit_data = (
        tag_data
        .get("units", {})
        .get(unit, [])
    )

    if not unit_data:
        return None

    financial_df = pd.DataFrame(unit_data)

    required_columns = {
        "val",
        "form",
        "filed",
    }

    if not required_columns.issubset(
        financial_df.columns
    ):
        return None

    # 10-K 데이터만 선택
    annual_df = financial_df.loc[
        financial_df["form"] == "10-K"
    ].copy()

    if annual_df.empty:
        return None

    # FY 값이 있으면 연간 실적만 우선 선택
    if "fp" in annual_df.columns:
        fy_rows = annual_df.loc[
            annual_df["fp"] == "FY"
        ].copy()

        if not fy_rows.empty:
            annual_df = fy_rows

    # 숫자·날짜 오류 방지를 위한 정리
    if "fy" in annual_df.columns:
        annual_df["fy"] = pd.to_numeric(
            annual_df["fy"],
            errors="coerce",
        )

    annual_df["filed"] = pd.to_datetime(
        annual_df["filed"],
        errors="coerce",
    )

    # 동일 회계연도에 여러 공시가 있으면
    # 가장 최근 제출 공시를 사용
    if "fy" in annual_df.columns:
        annual_df = (
            annual_df
            .sort_values(["fy", "filed"])
            .drop_duplicates(
                subset=["fy"],
                keep="last",
            )
        )
    else:
        annual_df = annual_df.sort_values(
            "filed"
        )

    if annual_df.empty:
        return None

    latest_row = annual_df.iloc[-1]

    fiscal_year = latest_row.get("fy")

    if pd.notna(fiscal_year):
        fiscal_year = int(fiscal_year)
    else:
        fiscal_year = None

    filed_date = latest_row.get("filed")

    if pd.notna(filed_date):
        filed_date = filed_date.strftime(
            "%Y-%m-%d"
        )
    else:
        filed_date = None

    return {
        "tag": tag_name,
        "unit": unit,
        "fiscal_year": fiscal_year,
        "period": latest_row.get("fp"),
        "start_date": latest_row.get("start"),
        "end_date": latest_row.get("end"),
        "value": latest_row.get("val"),
        "filed_date": filed_date,
        "form": latest_row.get("form"),
        "accession_number": latest_row.get("accn"),
    }


# ============================================================
# 9. 실행 흐름
# ============================================================

def main() -> None:
    """
    기업 마스터 조회부터 최신 연간 매출 추출까지 실행한다.
    """

    test_ticker = "NVDA"

    # 1. 기업 마스터 불러오기
    company_master = load_company_master()

    # 2. 티커에 해당하는 CIK 조회
    cik = find_cik(
        company_master,
        test_ticker,
    )

    print("=" * 60)
    print("SEC Company Facts 데이터 확인")
    print("=" * 60)
    print("테스트 티커:", test_ticker)
    print("CIK:", cik)

    # 3. SEC Company Facts 요청
    response = request_company_facts(cik)

    print("Status Code:", response.status_code)

    # 4. JSON 변환
    data = response.json()

    print("기업명:", data.get("entityName"))
    print("최상위 키:", data.keys())
    print(
        "재무 기준 목록:",
        data.get("facts", {}).keys(),
    )

    # 5. US-GAAP 데이터 접근
    us_gaap = (
        data
        .get("facts", {})
        .get("us-gaap", {})
    )

    if not us_gaap:
        raise ValueError(
            "응답에서 US-GAAP 데이터를 찾지 못했습니다."
        )

    print()
    print("US-GAAP 태그 개수:", len(us_gaap))

    # 6. 핵심 재무 태그 검색
    search_keywords = [
        "Revenue",
        "NetIncome",
        "OperatingIncome",
        "Assets",
        "Liabilities",
        "StockholdersEquity",
        "EarningsPerShare",
    ]

    print()
    print("=" * 60)
    print("US-GAAP 핵심 태그 검색")
    print("=" * 60)

    for keyword in search_keywords:
        matched_tags = search_tag(
            us_gaap,
            keyword,
        )

        print()
        print(f"[{keyword}]")

        if matched_tags:
            for tag in matched_tags:
                print("  →", tag)
        else:
            print("  → 관련 태그 없음")

    # 7. 대표 매출 태그 선택
    revenue_tag = find_revenue_tag(
        us_gaap
    )

    print()
    print("=" * 60)
    print("대표 Revenue 태그 확인")
    print("=" * 60)

    if revenue_tag is None:
        print("대표 매출 태그를 찾지 못했습니다.")
        return

    show_tag_structure(
        us_gaap,
        revenue_tag,
    )

    # 8. 최신 연간 매출액 추출
    latest_revenue = extract_latest_annual_value(
        us_gaap,
        revenue_tag,
        unit="USD",
    )

    print()
    print("=" * 60)
    print("최신 연간 Revenue")
    print("=" * 60)

    if latest_revenue is None:
        print("연간 매출 데이터를 추출하지 못했습니다.")
        return

    revenue_value = latest_revenue["value"]

    print(
        "회계연도:",
        latest_revenue["fiscal_year"],
    )

    print(
        "기간:",
        latest_revenue["start_date"],
        "~",
        latest_revenue["end_date"],
    )

    if pd.notna(revenue_value):
        print(
            "매출액:",
            f"{float(revenue_value):,.0f}",
            latest_revenue["unit"],
        )
    else:
        print("매출액: 값 없음")

    print(
        "공시일:",
        latest_revenue["filed_date"],
    )

    print(
        "공시 유형:",
        latest_revenue["form"],
    )

    print(
        "Accession Number:",
        latest_revenue["accession_number"],
    )


if __name__ == "__main__":
    main()