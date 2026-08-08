"""
financial_extractor.py

SEC Company Facts 데이터를 이용해 기업별 핵심 재무지표를 추출한다.

주요 기능
----------
1. Revenue 기준으로 최신 연간 회계기간 결정
2. 모든 재무지표를 동일한 기준일로 정렬
3. Revenue, Operating Income, Net Income, Assets, Liabilities 추출
4. Liabilities가 없으면 부채·자본총계 - 자본으로 대체 계산
5. 오래된 재무데이터 표시
6. 비정상적인 재무값 자동 경고
7. 기간 정합성 및 주요 재무비율 계산
"""

from pathlib import Path
from typing import Any

import pandas as pd
import requests


# ============================================================
# 1. 기본 설정
# ============================================================

COMPANY_MASTER_PATH = Path(
    "01_Data_Acquisition/output/sec_company_master.csv"
)

# PIT용 기업별 전체 공시 이력 저장 경로
FACT_STORE_DIR = Path(
    "data/facts"
)

SEC_COMPANY_FACTS_URL = (
    "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
)

HEADERS = {
    "User-Agent": "AI_Custom_Index pskl1206@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}

# 기준일이 현재로부터 2년을 초과하면 오래된 데이터로 표시
MAX_DATA_AGE_DAYS = 730


# ============================================================
# 2. 재무 태그 후보
# ============================================================

FINANCIAL_TAG_CANDIDATES = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "SalesRevenueServicesNet",
        "RegulatedAndUnregulatedOperatingRevenue",
    ],
    "operating_income": [
        "OperatingIncomeLoss",
    ],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
    ],
    "assets": [
        "Assets",
    ],
    "liabilities": [
        "Liabilities",
    ],
}


# 총부채 직접 태그가 없는 경우 사용하는 대체 태그
LIABILITY_FALLBACK_TAGS = {
    "liabilities_and_equity": [
        "LiabilitiesAndStockholdersEquity",
        "LiabilitiesAndPartnersCapital",
        "LiabilitiesAndMembersEquity",
    ],
    "equity": [
        "StockholdersEquity",
        (
            "StockholdersEquityIncludingPortion"
            "AttributableToNoncontrollingInterest"
        ),
        "PartnersCapital",
        "MembersEquity",
    ],
}


FLOW_METRICS = {
    "revenue",
    "operating_income",
    "net_income",
}

STOCK_METRICS = {
    "assets",
    "liabilities",
}


# ============================================================
# 3. 기업 마스터 불러오기
# ============================================================

def load_company_master() -> pd.DataFrame:
    """
    저장된 SEC 기업 마스터 CSV를 불러온다.
    """

    if not COMPANY_MASTER_PATH.exists():
        raise FileNotFoundError(
            "기업 마스터 파일을 찾지 못했습니다: "
            f"{COMPANY_MASTER_PATH}"
        )

    company_master = pd.read_csv(
        COMPANY_MASTER_PATH,
        dtype={"cik": str},
    )

    required_columns = {
        "cik",
        "ticker",
        "exchange",
    }

    missing_columns = (
        required_columns
        - set(company_master.columns)
    )

    if missing_columns:
        raise ValueError(
            "기업 마스터에 필수 컬럼이 없습니다: "
            f"{sorted(missing_columns)}"
        )

    return company_master


# ============================================================
# 4. 티커로 기업 정보 찾기
# ============================================================

def find_company_info(
    company_master: pd.DataFrame,
    ticker: str,
) -> dict[str, Any]:
    """
    티커에 해당하는 기업명, CIK, 거래소를 반환한다.
    """

    normalized_ticker = (
        ticker
        .upper()
        .strip()
    )

    ticker_series = (
        company_master["ticker"]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    target = company_master.loc[
        ticker_series == normalized_ticker
    ]

    if target.empty:
        raise ValueError(
            f"기업 마스터에서 {normalized_ticker}를 "
            "찾지 못했습니다."
        )

    row = target.iloc[0]

    if "company_name" in company_master.columns:
        company_name = row.get("company_name")
    else:
        company_name = row.get("name")

    cik = (
        str(row["cik"])
        .replace(".0", "")
        .zfill(10)
    )

    return {
        "ticker": normalized_ticker,
        "company_name": company_name,
        "cik": cik,
        "exchange": row.get("exchange"),
    }


# ============================================================
# 5. SEC Company Facts 요청
# ============================================================

def request_company_facts(
    cik: str,
) -> dict[str, Any]:
    """
    SEC Company Facts API에서 기업 재무데이터를 요청한다.
    """

    url = SEC_COMPANY_FACTS_URL.format(
        cik=cik
    )

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    return response.json()




# ============================================================
# 6. PIT용 Fact Store 생성
# ============================================================

FACT_STORE_COLUMNS = [
    "cik",
    "ticker",
    "taxonomy",
    "tag",
    "unit",
    "start",
    "end",
    "val",
    "filed",
    "form",
    "accn",
    "fy",
    "fp",
]


def create_fact_store_dataframe(
    company_info: dict,
    company_facts: dict,
) -> pd.DataFrame:
    """
    SEC Company Facts의 모든 taxonomy, tag, unit, 공시 이력을
    PIT용 Long Format DataFrame으로 변환한다.

    수집 단계에서는 공시 형식, 수정공시, 중복 레코드를
    제거하지 않으며 filed, form, accn을 그대로 보존한다.
    """

    facts_root = company_facts.get(
        "facts",
        {},
    )

    if not facts_root:
        raise ValueError(
            "Company Facts에서 facts 데이터를 "
            "찾지 못했습니다."
        )

    rows = []

    for taxonomy, taxonomy_facts in facts_root.items():
        if not isinstance(taxonomy_facts, dict):
            continue

        for tag_name, tag_data in taxonomy_facts.items():
            if not isinstance(tag_data, dict):
                continue

            units = tag_data.get(
                "units",
                {},
            )

            if not isinstance(units, dict):
                continue

            for unit_name, records in units.items():
                if not isinstance(records, list):
                    continue

                for record in records:
                    if not isinstance(record, dict):
                        continue

                    rows.append(
                        {
                            "cik": (
                                str(company_info["cik"])
                                .replace(".0", "")
                                .zfill(10)
                            ),
                            "ticker": company_info["ticker"],
                            "taxonomy": taxonomy,
                            "tag": tag_name,
                            "unit": unit_name,
                            "start": record.get("start"),
                            "end": record.get("end"),
                            "val": record.get("val"),
                            "filed": record.get("filed"),
                            "form": record.get("form"),
                            "accn": record.get("accn"),
                            "fy": record.get("fy"),
                            "fp": record.get("fp"),
                        }
                    )

    fact_store_df = pd.DataFrame(
        rows,
        columns=FACT_STORE_COLUMNS,
    )

    if fact_store_df.empty:
        return fact_store_df

    for column in [
        "start",
        "end",
        "filed",
    ]:
        fact_store_df[column] = pd.to_datetime(
            fact_store_df[column],
            errors="coerce",
        )

    fact_store_df["val"] = pd.to_numeric(
        fact_store_df["val"],
        errors="coerce",
    )

    fact_store_df["fy"] = (
        pd.to_numeric(
            fact_store_df["fy"],
            errors="coerce",
        )
        .astype("Int64")
    )

    fact_store_df = (
        fact_store_df
        .sort_values(
            [
                "taxonomy",
                "tag",
                "unit",
                "end",
                "filed",
                "accn",
            ],
            na_position="last",
        )
        .reset_index(drop=True)
    )

    return fact_store_df


def save_fact_store(
    fact_store_df: pd.DataFrame,
    cik: str,
    output_dir: Path = FACT_STORE_DIR,
) -> Path:
    """
    기업별 Fact Store를 CIK.parquet 형식으로 저장한다.
    """

    if fact_store_df.empty:
        raise ValueError(
            "저장할 Fact Store 데이터가 없습니다."
        )

    normalized_cik = (
        str(cik)
        .replace(".0", "")
        .zfill(10)
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_dir
        / f"{normalized_cik}.parquet"
    )

    fact_store_df.to_parquet(
        output_path,
        index=False,
    )

    return output_path


# ============================================================
# 6. 날짜 형식 정리
# ============================================================

def format_date(
    value: Any,
) -> str | None:
    """
    날짜 값을 YYYY-MM-DD 문자열로 변환한다.
    """

    if value is None or pd.isna(value):
        return None

    parsed_value = pd.to_datetime(
        value,
        errors="coerce",
    )

    if pd.isna(parsed_value):
        return None

    return parsed_value.strftime(
        "%Y-%m-%d"
    )


# ============================================================
# 7. 태그 데이터를 DataFrame으로 변환
# ============================================================

def create_fact_dataframe(
    us_gaap: dict,
    tag_name: str,
    unit: str = "USD",
) -> pd.DataFrame:
    """
    특정 US-GAAP 태그의 레코드를 DataFrame으로 변환한다.
    """

    if tag_name not in us_gaap:
        return pd.DataFrame()

    records = (
        us_gaap[tag_name]
        .get("units", {})
        .get(unit, [])
    )

    if not records:
        return pd.DataFrame()

    fact_df = pd.DataFrame(
        records
    )

    if fact_df.empty:
        return fact_df

    for column in [
        "start",
        "end",
        "filed",
    ]:
        if column in fact_df.columns:
            fact_df[column] = pd.to_datetime(
                fact_df[column],
                errors="coerce",
            )

    if "fy" in fact_df.columns:
        fact_df["fy"] = pd.to_numeric(
            fact_df["fy"],
            errors="coerce",
        )

    if "val" in fact_df.columns:
        fact_df["val"] = pd.to_numeric(
            fact_df["val"],
            errors="coerce",
        )

    return fact_df


# ============================================================
# 8. 연간 Flow 데이터 정제
# ============================================================

def prepare_annual_flow_data(
    us_gaap: dict,
    tag_name: str,
    unit: str = "USD",
) -> pd.DataFrame:
    """
    매출·영업이익·순이익 등 기간형 재무데이터를 정제한다.
    """

    fact_df = create_fact_dataframe(
        us_gaap,
        tag_name,
        unit,
    )

    required_columns = {
        "val",
        "form",
        "filed",
        "start",
        "end",
    }

    if (
        fact_df.empty
        or not required_columns.issubset(
            fact_df.columns
        )
    ):
        return pd.DataFrame()

    annual_df = fact_df.loc[
        fact_df["form"].isin(
            ["10-K", "10-K/A"]
        )
    ].copy()

    if annual_df.empty:
        return annual_df

    # FY 표시가 있는 데이터 우선
    if "fp" in annual_df.columns:
        fy_df = annual_df.loc[
            annual_df["fp"].eq("FY")
        ].copy()

        if not fy_df.empty:
            annual_df = fy_df

    # 약 1년 길이의 데이터만 선택
    annual_df["duration_days"] = (
        annual_df["end"]
        - annual_df["start"]
    ).dt.days

    full_year_df = annual_df.loc[
        annual_df["duration_days"].between(
            300,
            400,
            inclusive="both",
        )
    ].copy()

    if not full_year_df.empty:
        annual_df = full_year_df

    annual_df = annual_df.dropna(
        subset=[
            "val",
            "end",
            "filed",
        ]
    )

    # 동일 기준일이 여러 공시에 포함된 경우
    # 가장 최근 제출된 값 사용
    annual_df = (
        annual_df
        .sort_values(
            ["end", "filed"]
        )
        .drop_duplicates(
            subset=["end"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return annual_df


# ============================================================
# 9. 연말 Stock 데이터 정제
# ============================================================

def prepare_annual_stock_data(
    us_gaap: dict,
    tag_name: str,
    unit: str = "USD",
) -> pd.DataFrame:
    """
    자산·부채·자본 등 시점형 재무데이터를 정제한다.
    """

    fact_df = create_fact_dataframe(
        us_gaap,
        tag_name,
        unit,
    )

    required_columns = {
        "val",
        "form",
        "filed",
        "end",
    }

    if (
        fact_df.empty
        or not required_columns.issubset(
            fact_df.columns
        )
    ):
        return pd.DataFrame()

    annual_df = fact_df.loc[
        fact_df["form"].isin(
            ["10-K", "10-K/A"]
        )
    ].copy()

    if annual_df.empty:
        return annual_df

    if "fp" in annual_df.columns:
        fy_df = annual_df.loc[
            annual_df["fp"].eq("FY")
        ].copy()

        if not fy_df.empty:
            annual_df = fy_df

    annual_df = annual_df.dropna(
        subset=[
            "val",
            "end",
            "filed",
        ]
    )

    annual_df = (
        annual_df
        .sort_values(
            ["end", "filed"]
        )
        .drop_duplicates(
            subset=["end"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return annual_df


# ============================================================
# 10. 후보 태그 중 최신 데이터 선택
# ============================================================

def find_best_tag_and_latest_record(
    us_gaap: dict,
    candidate_tags: list[str],
    metric_type: str,
    unit: str = "USD",
) -> tuple[str | None, dict | None]:
    """
    후보 태그 중 가장 최신 기준일의 연간 데이터를 가진
    태그와 레코드를 선택한다.
    """

    best_tag = None
    best_record = None
    best_end_date = None

    for tag_name in candidate_tags:
        if metric_type == "flow":
            metric_df = prepare_annual_flow_data(
                us_gaap,
                tag_name,
                unit,
            )

        elif metric_type == "stock":
            metric_df = prepare_annual_stock_data(
                us_gaap,
                tag_name,
                unit,
            )

        else:
            raise ValueError(
                "metric_type은 flow 또는 stock이어야 합니다."
            )

        if metric_df.empty:
            continue

        latest_row = metric_df.iloc[-1]
        end_date = latest_row.get("end")

        if pd.isna(end_date):
            continue

        if (
            best_end_date is None
            or end_date > best_end_date
        ):
            best_tag = tag_name
            best_record = latest_row.to_dict()
            best_end_date = end_date

    return best_tag, best_record


# ============================================================
# 11. 특정 기준일의 값 추출
# ============================================================

def extract_value_for_end_date(
    us_gaap: dict,
    candidate_tags: list[str],
    metric_type: str,
    target_end_date: str,
    unit: str = "USD",
) -> dict | None:
    """
    후보 태그에서 목표 기준일과 동일한 재무값을 추출한다.
    """

    target_date = pd.to_datetime(
        target_end_date,
        errors="coerce",
    )

    if pd.isna(target_date):
        return None

    best_result = None
    best_filed_date = None

    for tag_name in candidate_tags:
        if metric_type == "flow":
            metric_df = prepare_annual_flow_data(
                us_gaap,
                tag_name,
                unit,
            )

        elif metric_type == "stock":
            metric_df = prepare_annual_stock_data(
                us_gaap,
                tag_name,
                unit,
            )

        else:
            raise ValueError(
                "metric_type은 flow 또는 stock이어야 합니다."
            )

        if metric_df.empty:
            continue

        matched_df = metric_df.loc[
            metric_df["end"].eq(
                target_date
            )
        ].copy()

        if matched_df.empty:
            continue

        matched_df = matched_df.sort_values(
            "filed"
        )

        row = matched_df.iloc[-1]
        filed_date = row.get("filed")

        if (
            best_filed_date is not None
            and pd.notna(filed_date)
            and filed_date <= best_filed_date
        ):
            continue

        fiscal_year = row.get("fy")

        if pd.notna(fiscal_year):
            fiscal_year = int(
                fiscal_year
            )
        else:
            fiscal_year = None

        best_result = {
            "tag": tag_name,
            "value": row.get("val"),
            "unit": unit,
            "fiscal_year": fiscal_year,
            "start_date": format_date(
                row.get("start")
            ),
            "end_date": format_date(
                row.get("end")
            ),
            "filed_date": format_date(
                row.get("filed")
            ),
            "form": row.get("form"),
            "accession_number": row.get(
                "accn"
            ),
        }

        best_filed_date = filed_date

    return best_result


# ============================================================
# 12. 최신 Revenue 기준일 결정
# ============================================================

def determine_target_period(
    us_gaap: dict,
) -> dict:
    """
    가장 최신 연간 Revenue 데이터를 찾아
    전체 재무데이터의 기준일로 사용한다.
    """

    revenue_tag, revenue_record = (
        find_best_tag_and_latest_record(
            us_gaap=us_gaap,
            candidate_tags=(
                FINANCIAL_TAG_CANDIDATES[
                    "revenue"
                ]
            ),
            metric_type="flow",
        )
    )

    if (
        revenue_tag is None
        or revenue_record is None
    ):
        raise ValueError(
            "최신 연간 Revenue 데이터를 찾지 못했습니다."
        )

    target_end_date = format_date(
        revenue_record.get("end")
    )

    if target_end_date is None:
        raise ValueError(
            "Revenue 기준일을 확인하지 못했습니다."
        )

    return {
        "revenue_tag": revenue_tag,
        "target_end_date": target_end_date,
    }


# ============================================================
# 13. 총부채 대체 계산
# ============================================================

def calculate_liabilities_fallback(
    us_gaap: dict,
    target_end_date: str,
) -> dict | None:
    """
    Liabilities 직접 태그가 없을 경우 아래 식으로 계산한다.

    총부채 = 부채및자본총계 - 자본
    """

    liabilities_and_equity = (
        extract_value_for_end_date(
            us_gaap=us_gaap,
            candidate_tags=(
                LIABILITY_FALLBACK_TAGS[
                    "liabilities_and_equity"
                ]
            ),
            metric_type="stock",
            target_end_date=target_end_date,
        )
    )

    equity = extract_value_for_end_date(
        us_gaap=us_gaap,
        candidate_tags=(
            LIABILITY_FALLBACK_TAGS[
                "equity"
            ]
        ),
        metric_type="stock",
        target_end_date=target_end_date,
    )

    if (
        liabilities_and_equity is None
        or equity is None
    ):
        return None

    total_value = (
        liabilities_and_equity
        .get("value")
    )
    equity_value = equity.get("value")

    if (
        total_value is None
        or equity_value is None
    ):
        return None

    try:
        liabilities_value = (
            float(total_value)
            - float(equity_value)
        )

    except (
        TypeError,
        ValueError,
    ):
        return None

    if liabilities_value < 0:
        return None

    return {
        "tag": (
            "CALCULATED:"
            f"{liabilities_and_equity.get('tag')}"
            "-"
            f"{equity.get('tag')}"
        ),
        "value": liabilities_value,
        "unit": "USD",
        "fiscal_year": (
            liabilities_and_equity
            .get("fiscal_year")
        ),
        "start_date": None,
        "end_date": target_end_date,
        "filed_date": (
            liabilities_and_equity
            .get("filed_date")
        ),
        "form": (
            liabilities_and_equity
            .get("form")
        ),
        "accession_number": (
            liabilities_and_equity
            .get("accession_number")
        ),
        "is_calculated": True,
        "calculation_method": (
            "LiabilitiesAndEquity "
            "- Equity"
        ),
    }


# ============================================================
# 14. 결과값 보조 함수
# ============================================================

def get_result_value(
    result: dict | None,
) -> int | float | None:
    """
    추출 결과에서 숫자 값을 반환한다.
    """

    if result is None:
        return None

    return result.get("value")


def get_result_tag(
    result: dict | None,
) -> str | None:
    """
    추출 결과에서 사용된 태그명을 반환한다.
    """

    if result is None:
        return None

    return result.get("tag")


def get_result_date(
    result: dict | None,
) -> str | None:
    """
    추출 결과에서 기준일을 반환한다.
    """

    if result is None:
        return None

    return result.get("end_date")


# ============================================================
# 15. 최신성 검사
# ============================================================

def check_data_freshness(
    target_end_date: str | None,
    max_age_days: int = MAX_DATA_AGE_DAYS,
) -> dict:
    """
    재무 기준일이 현재 시점에서 얼마나 오래됐는지 계산한다.
    """

    target_date = pd.to_datetime(
        target_end_date,
        errors="coerce",
    )

    if pd.isna(target_date):
        return {
            "data_age_days": None,
            "is_stale": True,
        }

    today = pd.Timestamp.today().normalize()

    data_age_days = int(
        (today - target_date).days
    )

    return {
        "data_age_days": data_age_days,
        "is_stale": (
            data_age_days
            > max_age_days
        ),
    }


# ============================================================
# 16. 재무 논리 경고
# ============================================================

def create_financial_warnings(
    revenue: int | float | None,
    operating_income: int | float | None,
    net_income: int | float | None,
    assets: int | float | None,
    liabilities: int | float | None,
) -> dict:
    """
    재무값의 기본적인 논리 이상 여부를 점검한다.
    """

    warnings = []

    if revenue is not None:
        if revenue <= 0:
            warnings.append(
                "revenue_non_positive"
            )

        if (
            operating_income is not None
            and operating_income > revenue
        ):
            warnings.append(
                "operating_income_exceeds_revenue"
            )

        if (
            net_income is not None
            and net_income > revenue
        ):
            warnings.append(
                "net_income_exceeds_revenue"
            )

    if (
        assets is not None
        and assets <= 0
    ):
        warnings.append(
            "assets_non_positive"
        )

    if (
        liabilities is not None
        and liabilities < 0
    ):
        warnings.append(
            "liabilities_negative"
        )

    if (
        assets is not None
        and liabilities is not None
        and liabilities > assets
    ):
        warnings.append(
            "liabilities_exceed_assets"
        )

    return {
        "financial_warning": bool(
            warnings
        ),
        "warning_count": len(
            warnings
        ),
        "warning_messages": (
            "|".join(warnings)
            if warnings
            else None
        ),
    }


# ============================================================
# 17. 기업별 재무데이터 추출
# ============================================================

def extract_company_financials(
    company_info: dict,
    company_facts: dict,
) -> dict:
    """
    기업 하나의 핵심 재무데이터를 동일 기준일로 정렬하고,
    총부채 대체 계산과 품질 플래그를 추가한다.
    """

    us_gaap = (
        company_facts
        .get("facts", {})
        .get("us-gaap", {})
    )

    if not us_gaap:
        raise ValueError(
            "US-GAAP 데이터를 찾지 못했습니다."
        )

    target_period = determine_target_period(
        us_gaap
    )

    target_end_date = target_period[
        "target_end_date"
    ]

    results = {}

    for metric_name, candidate_tags in (
        FINANCIAL_TAG_CANDIDATES.items()
    ):
        if metric_name in FLOW_METRICS:
            metric_type = "flow"

        elif metric_name in STOCK_METRICS:
            metric_type = "stock"

        else:
            continue

        results[metric_name] = (
            extract_value_for_end_date(
                us_gaap=us_gaap,
                candidate_tags=candidate_tags,
                metric_type=metric_type,
                target_end_date=(
                    target_end_date
                ),
            )
        )

    revenue = results.get(
        "revenue"
    )
    operating_income = results.get(
        "operating_income"
    )
    net_income = results.get(
        "net_income"
    )
    assets = results.get(
        "assets"
    )
    liabilities = results.get(
        "liabilities"
    )

    liabilities_calculated = False
    liabilities_method = None

    # 직접 총부채 태그가 없을 경우 대체 계산
    if liabilities is None:
        liabilities = (
            calculate_liabilities_fallback(
                us_gaap=us_gaap,
                target_end_date=(
                    target_end_date
                ),
            )
        )

        if liabilities is not None:
            liabilities_calculated = True
            liabilities_method = (
                liabilities.get(
                    "calculation_method"
                )
            )

    revenue_value = get_result_value(
        revenue
    )

    operating_income_value = (
        get_result_value(
            operating_income
        )
    )

    net_income_value = get_result_value(
        net_income
    )

    assets_value = get_result_value(
        assets
    )

    liabilities_value = (
        get_result_value(
            liabilities
        )
    )

    freshness = check_data_freshness(
        target_end_date
    )

    warning_result = (
        create_financial_warnings(
            revenue=(
                revenue_value
            ),
            operating_income=(
                operating_income_value
            ),
            net_income=(
                net_income_value
            ),
            assets=(
                assets_value
            ),
            liabilities=(
                liabilities_value
            ),
        )
    )

    return {
        "ticker": company_info[
            "ticker"
        ],
        "company_name": company_info[
            "company_name"
        ],
        "cik": company_info[
            "cik"
        ],
        "exchange": company_info[
            "exchange"
        ],

        "target_end_date": (
            target_end_date
        ),

        "revenue": revenue_value,
        "operating_income": (
            operating_income_value
        ),
        "net_income": (
            net_income_value
        ),
        "assets": assets_value,
        "liabilities": (
            liabilities_value
        ),

        "revenue_tag": get_result_tag(
            revenue
        ),
        "operating_income_tag": (
            get_result_tag(
                operating_income
            )
        ),
        "net_income_tag": (
            get_result_tag(
                net_income
            )
        ),
        "assets_tag": (
            get_result_tag(
                assets
            )
        ),
        "liabilities_tag": (
            get_result_tag(
                liabilities
            )
        ),

        "liabilities_calculated": (
            liabilities_calculated
        ),
        "liabilities_method": (
            liabilities_method
        ),

        "revenue_end_date": (
            get_result_date(
                revenue
            )
        ),
        "operating_income_end_date": (
            get_result_date(
                operating_income
            )
        ),
        "net_income_end_date": (
            get_result_date(
                net_income
            )
        ),
        "assets_end_date": (
            get_result_date(
                assets
            )
        ),
        "liabilities_end_date": (
            get_result_date(
                liabilities
            )
        ),

        "revenue_fiscal_year": (
            revenue.get(
                "fiscal_year"
            )
            if revenue
            else None
        ),
        "revenue_filed_date": (
            revenue.get(
                "filed_date"
            )
            if revenue
            else None
        ),

        "data_age_days": freshness[
            "data_age_days"
        ],
        "is_stale": freshness[
            "is_stale"
        ],

        "financial_warning": (
            warning_result[
                "financial_warning"
            ]
        ),
        "warning_count": (
            warning_result[
                "warning_count"
            ]
        ),
        "warning_messages": (
            warning_result[
                "warning_messages"
            ]
        ),
    }


# ============================================================
# 18. 기간 정합성 검사
# ============================================================

def validate_period_consistency(
    financials: dict,
) -> dict:
    """
    각 재무지표의 기준일이 목표 기준일과 일치하는지 검증한다.
    """

    target_end_date = financials.get(
        "target_end_date"
    )

    date_columns = {
        "revenue": financials.get(
            "revenue_end_date"
        ),
        "operating_income": financials.get(
            "operating_income_end_date"
        ),
        "net_income": financials.get(
            "net_income_end_date"
        ),
        "assets": financials.get(
            "assets_end_date"
        ),
        "liabilities": financials.get(
            "liabilities_end_date"
        ),
    }

    mismatches = {}

    for metric, end_date in (
        date_columns.items()
    ):
        if end_date is None:
            mismatches[metric] = (
                "값 없음"
            )

        elif end_date != target_end_date:
            mismatches[metric] = (
                end_date
            )

    return {
        "is_consistent": (
            not mismatches
        ),
        "target_end_date": (
            target_end_date
        ),
        "mismatches": (
            mismatches
        ),
    }


# ============================================================
# 19. 재무비율 계산
# ============================================================

def calculate_financial_ratios(
    financials: dict,
) -> dict:
    """
    동일 기간 재무데이터로 기초 재무비율을 계산한다.
    """

    revenue = financials.get(
        "revenue"
    )

    operating_income = (
        financials.get(
            "operating_income"
        )
    )

    net_income = financials.get(
        "net_income"
    )

    assets = financials.get(
        "assets"
    )

    liabilities = financials.get(
        "liabilities"
    )

    operating_margin = None
    net_margin = None
    liability_to_assets = None

    if revenue not in (
        None,
        0,
    ):
        if operating_income is not None:
            operating_margin = (
                operating_income
                / revenue
            )

        if net_income is not None:
            net_margin = (
                net_income
                / revenue
            )

    if assets not in (
        None,
        0,
    ):
        if liabilities is not None:
            liability_to_assets = (
                liabilities
                / assets
            )

    return {
        "operating_margin": (
            operating_margin
        ),
        "net_margin": (
            net_margin
        ),
        "liability_to_assets": (
            liability_to_assets
        ),
    }


# ============================================================
# 20. 결과 출력
# ============================================================

def print_financial_summary(
    financials: dict,
    validation: dict,
    ratios: dict,
) -> None:
    """
    추출된 재무데이터와 검증 결과를 출력한다.
    """

    print()
    print("=" * 70)
    print("기업 핵심 재무데이터")
    print("=" * 70)

    print(
        "티커:",
        financials["ticker"],
    )
    print(
        "기업명:",
        financials["company_name"],
    )
    print(
        "CIK:",
        financials["cik"],
    )
    print(
        "거래소:",
        financials["exchange"],
    )
    print(
        "통일 기준일:",
        financials[
            "target_end_date"
        ],
    )

    metrics = [
        (
            "Revenue",
            "revenue",
            "revenue_end_date",
        ),
        (
            "Operating Income",
            "operating_income",
            "operating_income_end_date",
        ),
        (
            "Net Income",
            "net_income",
            "net_income_end_date",
        ),
        (
            "Assets",
            "assets",
            "assets_end_date",
        ),
        (
            "Liabilities",
            "liabilities",
            "liabilities_end_date",
        ),
    ]

    print()

    for (
        label,
        value_key,
        date_key,
    ) in metrics:
        value = financials.get(
            value_key
        )
        end_date = financials.get(
            date_key
        )

        if value is None:
            print(
                f"{label}: 값 없음 "
                f"(기준일: {end_date})"
            )

        else:
            print(
                f"{label}: "
                f"{float(value):,.0f} USD "
                f"(기준일: {end_date})"
            )

    print()
    print(
        "총부채 대체 계산:",
        financials.get(
            "liabilities_calculated"
        ),
    )
    print(
        "총부채 계산 방법:",
        financials.get(
            "liabilities_method"
        ),
    )
    print(
        "데이터 경과일:",
        financials.get(
            "data_age_days"
        ),
    )
    print(
        "오래된 데이터:",
        financials.get(
            "is_stale"
        ),
    )
    print(
        "재무 경고:",
        financials.get(
            "financial_warning"
        ),
    )
    print(
        "경고 내용:",
        financials.get(
            "warning_messages"
        ),
    )

    print()
    print("=" * 70)
    print("회계기간 정합성 검증")
    print("=" * 70)

    if validation[
        "is_consistent"
    ]:
        print(
            "정상: 모든 확보 지표가 동일 기준일입니다."
        )
    else:
        print(
            "주의: 일부 지표가 없거나 기준일이 다릅니다."
        )

        for metric, issue in (
            validation[
                "mismatches"
            ].items()
        ):
            print(
                f"- {metric}: {issue}"
            )

    print()
    print("=" * 70)
    print("기초 재무비율")
    print("=" * 70)

    ratio_labels = {
        "operating_margin": (
            "영업이익률"
        ),
        "net_margin": (
            "순이익률"
        ),
        "liability_to_assets": (
            "부채/자산"
        ),
    }

    for key, label in (
        ratio_labels.items()
    ):
        value = ratios.get(
            key
        )

        if value is None:
            print(
                f"{label}: 계산 불가"
            )
        else:
            print(
                f"{label}: {value:.2%}"
            )


# ============================================================
# 21. 단독 실행 테스트
# ============================================================

def main() -> None:
    """
    NVDA를 대상으로 추출 기능을 테스트한다.
    """

    test_ticker = "NVDA"

    company_master = (
        load_company_master()
    )

    company_info = (
        find_company_info(
            company_master,
            test_ticker,
        )
    )

    print(
        "SEC Company Facts 요청 중..."
    )
    print(
        "테스트 티커:",
        test_ticker,
    )
    print(
        "CIK:",
        company_info["cik"],
    )

    company_facts = (
        request_company_facts(
            company_info["cik"]
        )
    )

    print(
        "PIT Fact Store 생성 중..."
    )

    fact_store_df = (
        create_fact_store_dataframe(
            company_info=company_info,
            company_facts=company_facts,
        )
    )

    fact_store_path = (
        save_fact_store(
            fact_store_df=fact_store_df,
            cik=company_info["cik"],
        )
    )

    print(
        "Fact Store 행 수:",
        len(fact_store_df),
    )
    print(
        "Fact Store 저장 완료:",
        fact_store_path,
    )

    financials = (
        extract_company_financials(
            company_info,
            company_facts,
        )
    )

    validation = (
        validate_period_consistency(
            financials
        )
    )

    ratios = (
        calculate_financial_ratios(
            financials
        )
    )

    print_financial_summary(
        financials,
        validation,
        ratios,
    )

    result = {
        **financials,
        **ratios,
        "period_consistent": (
            validation[
                "is_consistent"
            ]
        ),
        "period_issues": (
            str(
                validation[
                    "mismatches"
                ]
            )
            if validation[
                "mismatches"
            ]
            else None
        ),
    }

    result_df = pd.DataFrame(
        [result]
    )

    print()
    print("=" * 70)
    print("DataFrame 결과")
    print("=" * 70)
    print(
        result_df.T
    )


if __name__ == "__main__":
    main()