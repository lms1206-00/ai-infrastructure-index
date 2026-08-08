"""
06_yahoo_market_data.py

Yahoo Finance에서 기업별 시장·산업 데이터를 수집하고
CSV와 Excel 파일로 저장한다.

수집 항목
- 기업명
- 시가총액
- 섹터
- 산업
- 국가
- 직원 수
- 발행주식수
- 베타
- 평균 거래량
- 통화
- 거래소
- 최근 종가
"""

from pathlib import Path
import time
from typing import Any

import pandas as pd
import yfinance as yf


# ============================================================
# 1. 기본 설정
# ============================================================

OUTPUT_DIR = Path(
    "01_Data_Acquisition/output"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

OUTPUT_CSV_PATH = (
    OUTPUT_DIR / "yahoo_market_test.csv"
)

OUTPUT_EXCEL_PATH = (
    OUTPUT_DIR / "yahoo_market_test.xlsx"
)

ERROR_LOG_PATH = (
    OUTPUT_DIR / "yahoo_market_errors.csv"
)

TEST_TICKERS = [
    "NVDA",
    "AMD",
    "AVGO",
    "ANET",
    "VRT",
]

REQUEST_INTERVAL_SECONDS = 1.0


# ============================================================
# 2. 보조 함수
# ============================================================

def safe_get(
    data: dict,
    key: str,
) -> Any:
    """
    딕셔너리에서 값을 안전하게 가져온다.
    """

    value = data.get(key)

    if value in ("", "N/A", "None"):
        return None

    return value


def safe_fast_info_get(
    fast_info: Any,
    key: str,
) -> Any:
    """
    yfinance fast_info에서 값을 안전하게 가져온다.
    """

    try:
        return fast_info.get(key)
    except (
        AttributeError,
        KeyError,
        TypeError,
    ):
        return None


# ============================================================
# 3. 최근 가격 데이터 추출
# ============================================================

def extract_latest_price(
    ticker_object: yf.Ticker,
) -> dict:
    """
    최근 거래일의 종가와 거래량을 가져온다.
    """

    history = ticker_object.history(
        period="5d",
        interval="1d",
        auto_adjust=False,
    )

    if history.empty:
        return {
            "latest_price_date": None,
            "latest_close": None,
            "latest_volume": None,
        }

    history = history.dropna(
        subset=["Close"]
    )

    if history.empty:
        return {
            "latest_price_date": None,
            "latest_close": None,
            "latest_volume": None,
        }

    latest_row = history.iloc[-1]
    latest_date = history.index[-1]

    if hasattr(latest_date, "strftime"):
        latest_date = latest_date.strftime(
            "%Y-%m-%d"
        )

    return {
        "latest_price_date": latest_date,
        "latest_close": latest_row.get("Close"),
        "latest_volume": latest_row.get("Volume"),
    }


# ============================================================
# 4. 기업 하나의 Yahoo 데이터 수집
# ============================================================

def collect_single_ticker(
    ticker: str,
) -> dict:
    """
    Yahoo Finance에서 기업 하나의 데이터를 수집한다.
    """

    normalized_ticker = ticker.upper().strip()

    ticker_object = yf.Ticker(
        normalized_ticker
    )

    # 기업·산업 정보
    info = ticker_object.get_info()

    if not isinstance(info, dict):
        info = {}

    # 일부 시장 데이터는 fast_info에서 보완
    fast_info = ticker_object.fast_info

    price_data = extract_latest_price(
        ticker_object
    )

    market_cap = safe_get(
        info,
        "marketCap",
    )

    if market_cap is None:
        market_cap = safe_fast_info_get(
            fast_info,
            "market_cap",
        )

    shares_outstanding = safe_get(
        info,
        "sharesOutstanding",
    )

    if shares_outstanding is None:
        shares_outstanding = (
            safe_fast_info_get(
                fast_info,
                "shares",
            )
        )

    currency = safe_get(
        info,
        "currency",
    )

    if currency is None:
        currency = safe_fast_info_get(
            fast_info,
            "currency",
        )

    exchange = safe_get(
        info,
        "exchange",
    )

    if exchange is None:
        exchange = safe_fast_info_get(
            fast_info,
            "exchange",
        )

    return {
        "ticker": normalized_ticker,
        "company_name": (
            safe_get(info, "longName")
            or safe_get(info, "shortName")
        ),
        "quote_type": safe_get(
            info,
            "quoteType",
        ),
        "market_cap": market_cap,
        "sector": safe_get(
            info,
            "sector",
        ),
        "industry": safe_get(
            info,
            "industry",
        ),
        "country": safe_get(
            info,
            "country",
        ),
        "full_time_employees": safe_get(
            info,
            "fullTimeEmployees",
        ),
        "shares_outstanding": (
            shares_outstanding
        ),
        "beta": safe_get(
            info,
            "beta",
        ),
        "average_volume": (
            safe_get(info, "averageVolume")
            or safe_get(
                info,
                "averageDailyVolume10Day",
            )
        ),
        "currency": currency,
        "exchange": exchange,
        "exchange_name": safe_get(
            info,
            "fullExchangeName",
        ),
        "website": safe_get(
            info,
            "website",
        ),
        "latest_price_date": price_data[
            "latest_price_date"
        ],
        "latest_close": price_data[
            "latest_close"
        ],
        "latest_volume": price_data[
            "latest_volume"
        ],
    }


# ============================================================
# 5. 여러 기업 반복 수집
# ============================================================

def collect_yahoo_market_data(
    tickers: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    여러 티커의 Yahoo 데이터를 반복 수집한다.
    """

    successful_results = []
    error_results = []

    total_count = len(tickers)

    for index, ticker in enumerate(
        tickers,
        start=1,
    ):
        print()
        print("=" * 70)
        print(
            f"[{index}/{total_count}] "
            f"{ticker} 수집 시작"
        )
        print("=" * 70)

        start_time = time.perf_counter()

        try:
            result = collect_single_ticker(
                ticker
            )

            elapsed_seconds = (
                time.perf_counter()
                - start_time
            )

            result["response_seconds"] = round(
                elapsed_seconds,
                3,
            )

            successful_results.append(
                result
            )

            print(f"{ticker} 수집 성공")
            print(
                "기업명:",
                result.get("company_name"),
            )
            print(
                "시가총액:",
                result.get("market_cap"),
            )
            print(
                "Sector:",
                result.get("sector"),
            )
            print(
                "Industry:",
                result.get("industry"),
            )
            print(
                "응답시간:",
                result.get("response_seconds"),
                "초",
            )

        except Exception as error:
            elapsed_seconds = (
                time.perf_counter()
                - start_time
            )

            error_results.append(
                {
                    "ticker": ticker,
                    "error_type": type(
                        error
                    ).__name__,
                    "error_message": str(
                        error
                    ),
                    "response_seconds": round(
                        elapsed_seconds,
                        3,
                    ),
                }
            )

            print(f"{ticker} 수집 실패")
            print(
                type(error).__name__,
                ":",
                error,
            )

        if index < total_count:
            time.sleep(
                REQUEST_INTERVAL_SECONDS
            )

    market_df = pd.DataFrame(
        successful_results
    )

    error_df = pd.DataFrame(
        error_results
    )

    return market_df, error_df


# ============================================================
# 6. 데이터 품질 확인
# ============================================================

def validate_market_data(
    market_df: pd.DataFrame,
) -> None:
    """
    수집된 Yahoo 데이터의 기본 품질을 확인한다.
    """

    print()
    print("=" * 70)
    print("Yahoo Market Data 검증")
    print("=" * 70)

    print(
        "성공 기업 수:",
        len(market_df),
    )

    if market_df.empty:
        print("수집된 데이터가 없습니다.")
        return

    key_columns = [
        "company_name",
        "market_cap",
        "sector",
        "industry",
        "country",
        "shares_outstanding",
        "average_volume",
        "latest_close",
    ]

    available_columns = [
        column
        for column in key_columns
        if column in market_df.columns
    ]

    quality_rows = []

    total_count = len(market_df)

    for column in available_columns:
        available_count = (
            market_df[column]
            .notna()
            .sum()
        )

        missing_count = (
            market_df[column]
            .isna()
            .sum()
        )

        coverage = (
            available_count
            / total_count
            * 100
        )

        quality_rows.append(
            {
                "column": column,
                "available": available_count,
                "missing": missing_count,
                "coverage_pct": round(
                    coverage,
                    2,
                ),
            }
        )

    quality_df = pd.DataFrame(
        quality_rows
    )

    print()
    print("[컬럼별 확보율]")
    print(quality_df.to_string(index=False))

    if "sector" in market_df.columns:
        print()
        print("[Sector 분포]")
        print(
            market_df["sector"]
            .value_counts(
                dropna=False
            )
        )

    if "response_seconds" in market_df.columns:
        print()
        print(
            "평균 응답시간:",
            round(
                market_df[
                    "response_seconds"
                ].mean(),
                3,
            ),
            "초",
        )


# ============================================================
# 7. 파일 저장
# ============================================================

def save_results(
    market_df: pd.DataFrame,
    error_df: pd.DataFrame,
) -> None:
    """
    Yahoo 수집 결과와 오류 로그를 저장한다.
    """

    if not market_df.empty:
        market_df.to_csv(
            OUTPUT_CSV_PATH,
            index=False,
            encoding="utf-8-sig",
        )

        market_df.to_excel(
            OUTPUT_EXCEL_PATH,
            index=False,
        )

        print()
        print("Yahoo 데이터 저장 완료")
        print("CSV:", OUTPUT_CSV_PATH)
        print("Excel:", OUTPUT_EXCEL_PATH)

    if not error_df.empty:
        error_df.to_csv(
            ERROR_LOG_PATH,
            index=False,
            encoding="utf-8-sig",
        )

        print()
        print("오류 로그 저장 완료")
        print(
            "Error Log:",
            ERROR_LOG_PATH,
        )
    else:
        print()
        print("수집 오류가 없습니다.")


# ============================================================
# 8. 실행 흐름
# ============================================================

def main() -> None:
    """
    테스트 기업 5개의 Yahoo 데이터를 수집한다.
    """

    print("=" * 70)
    print("Yahoo Market Data 테스트 수집 시작")
    print("=" * 70)
    print("대상 티커:", TEST_TICKERS)

    market_df, error_df = (
        collect_yahoo_market_data(
            TEST_TICKERS
        )
    )

    validate_market_data(
        market_df
    )

    save_results(
        market_df,
        error_df,
    )

    print()
    print("=" * 70)
    print("수집 완료")
    print("=" * 70)

    if not market_df.empty:
        display_columns = [
            "ticker",
            "company_name",
            "market_cap",
            "sector",
            "industry",
            "country",
            "average_volume",
            "latest_close",
        ]

        available_columns = [
            column
            for column in display_columns
            if column in market_df.columns
        ]

        print(
            market_df[
                available_columns
            ].to_string(
                index=False
            )
        )


if __name__ == "__main__":
    main()