"""
04_financial_master_final.py

SEC 기업 마스터에서 일반 운영기업 후보를 선택하고,
SEC Company Facts API를 이용해 Financial Master를 구축한다.

주요 기능
----------
1. Nasdaq·NYSE 상장기업 선택
2. SPAC, Unit, Warrant, Right 등 특수 증권 후보 제외
3. N개 또는 전체 기업 수집
4. 네트워크 오류 재시도
5. 구조적 데이터 부재 오류는 즉시 기록
6. 일정 기업 수마다 체크포인트 저장
7. 중단 후 재실행 시 이어서 수집
8. 기존 실패 기업 재시도
9. 재무데이터 품질 리포트 생성
"""

from pathlib import Path
import time
from typing import Any

import pandas as pd
import requests

from financial_extractor import (
    calculate_financial_ratios,
    extract_company_financials,
    find_company_info,
    load_company_master,
    request_company_facts,
    validate_period_consistency,
)


# ============================================================
# 1. 수집 설정
# ============================================================

# 50개 테스트
#SAMPLE_SIZE: int | None = 50

# 500개 테스트
#SAMPLE_SIZE = 500

# Nasdaq·NYSE 전체
SAMPLE_SIZE = None

TARGET_EXCHANGES = [
    "Nasdaq",
    "NYSE",
]

# API 요청 간 기본 대기시간
REQUEST_INTERVAL_SECONDS = 0.3

# 네트워크 오류 최대 요청 횟수
MAX_RETRIES = 3

# 재시도 대기시간
RETRY_WAIT_SECONDS = 3

# 몇 개 기업마다 저장할지
CHECKPOINT_INTERVAL = 10

# 기존 결과가 있으면 이어서 수집
RESUME_FROM_EXISTING = False

# 기존 오류 기업도 다시 시도
RETRY_EXISTING_ERRORS = True


# ============================================================
# 2. 특수 증권 제외 설정
# ============================================================

SPECIAL_TICKER_SUFFIXES = (
    "-UN",
    "-U",
    "-WT",
    "-WS",
    "-RT",
    "-R",
)

SPECIAL_NAME_KEYWORDS = (
    "WARRANT",
    "RIGHT",
    "UNIT",
    "BLANK CHECK",
    "ACQUISITION CORP",
    "ACQUISITION CORPORATION",
    "ACQUISITION CO",
)


# ============================================================
# 3. 저장 경로 설정
# ============================================================

OUTPUT_DIR = Path(
    "01_Data_Acquisition/output"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

OUTPUT_SUFFIX = (
    "all"
    if SAMPLE_SIZE is None
    else str(SAMPLE_SIZE)
)

OUTPUT_CSV_PATH = (
    OUTPUT_DIR
    / f"financial_master_{OUTPUT_SUFFIX}.csv"
)

OUTPUT_EXCEL_PATH = (
    OUTPUT_DIR
    / f"financial_master_{OUTPUT_SUFFIX}.xlsx"
)

ERROR_LOG_PATH = (
    OUTPUT_DIR
    / f"financial_master_errors_{OUTPUT_SUFFIX}.csv"
)

QUALITY_REPORT_PATH = (
    OUTPUT_DIR
    / f"financial_master_quality_{OUTPUT_SUFFIX}.csv"
)

RUN_SUMMARY_PATH = (
    OUTPUT_DIR
    / f"financial_master_run_summary_{OUTPUT_SUFFIX}.csv"
)


# ============================================================
# 4. 수집 대상 필터링
# ============================================================

def select_target_tickers(
    company_master: pd.DataFrame,
    sample_size: int | None,
) -> list[str]:
    """
    SEC 기업 마스터에서 일반 운영기업 후보를 선택한다.

    제외 대상
    ----------
    - Nasdaq·NYSE 이외 거래소
    - 빈 티커와 중복 티커
    - 하이픈 포함 특수 티커
    - Unit, Warrant, Right 등 특수 증권
    - 회사명에 SPAC 관련 표현이 포함된 기업
    """

    required_columns = {
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

    target_df = company_master.copy()

    # 거래소 필터
    target_df = target_df.loc[
        target_df["exchange"].isin(
            TARGET_EXCHANGES
        )
    ].copy()

    # 티커 정리
    target_df["ticker"] = (
        target_df["ticker"]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    # 회사명 컬럼 확인
    name_column = None

    if "company_name" in target_df.columns:
        name_column = "company_name"

    elif "name" in target_df.columns:
        name_column = "name"

    if name_column is not None:
        target_df["_normalized_name"] = (
            target_df[name_column]
            .fillna("")
            .astype(str)
            .str.upper()
            .str.strip()
        )

    # 빈 티커 제거
    target_df = target_df.loc[
        target_df["ticker"].ne("")
    ].copy()

    # 중복 티커 제거
    target_df = target_df.drop_duplicates(
        subset=["ticker"],
        keep="first",
    )

    # 알려진 특수 접미사 제외
    special_suffix_mask = (
        target_df["ticker"]
        .str.endswith(
            SPECIAL_TICKER_SUFFIXES
        )
    )

    target_df = target_df.loc[
        ~special_suffix_mask
    ].copy()

    # 하이픈 포함 티커 제외
    target_df = target_df.loc[
        ~target_df["ticker"].str.contains(
            "-",
            regex=False,
        )
    ].copy()

    # 영문자와 숫자만 허용
    target_df = target_df.loc[
        target_df["ticker"].str.match(
            r"^[A-Z0-9]+$",
            na=False,
        )
    ].copy()

    # 회사명 기준 SPAC 및 특수 증권 후보 제외
    if name_column is not None:
        special_name_mask = pd.Series(
            False,
            index=target_df.index,
        )

        for keyword in SPECIAL_NAME_KEYWORDS:
            special_name_mask = (
                special_name_mask
                | target_df[
                    "_normalized_name"
                ].str.contains(
                    keyword,
                    regex=False,
                    na=False,
                )
            )

        target_df = target_df.loc[
            ~special_name_mask
        ].copy()

    target_df = (
        target_df
        .sort_values("ticker")
        .reset_index(drop=True)
    )

    if sample_size is not None:
        if sample_size <= 0:
            raise ValueError(
                "SAMPLE_SIZE는 양수 또는 None이어야 합니다."
            )

        target_df = target_df.head(
            sample_size
        )

    print()
    print("=" * 70)
    print("수집 대상 필터링 결과")
    print("=" * 70)
    print(
        "최종 수집 대상:",
        f"{len(target_df):,}개",
    )
    print(
        "앞부분 티커:",
        target_df["ticker"]
        .head(20)
        .tolist(),
    )

    return target_df["ticker"].tolist()


# ============================================================
# 5. 기존 성공 결과 불러오기
# ============================================================

def load_existing_results(
) -> tuple[list[dict[str, Any]], set[str]]:
    """
    기존 Financial Master를 불러와
    결과 목록과 완료 티커 집합을 반환한다.
    """

    if (
        not RESUME_FROM_EXISTING
        or not OUTPUT_CSV_PATH.exists()
    ):
        return [], set()

    existing_df = pd.read_csv(
        OUTPUT_CSV_PATH,
        dtype={"cik": str},
    )

    if existing_df.empty:
        return [], set()

    existing_df["ticker"] = (
        existing_df["ticker"]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    existing_df = (
        existing_df
        .loc[
            existing_df["ticker"].ne("")
        ]
        .drop_duplicates(
            subset=["ticker"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    collected_tickers = set(
        existing_df["ticker"].tolist()
    )

    existing_results = (
        existing_df
        .where(
            pd.notna(existing_df),
            None,
        )
        .to_dict(
            orient="records"
        )
    )

    print()
    print(
        "기존 성공 결과:",
        len(existing_results),
        "개",
    )

    return (
        existing_results,
        collected_tickers,
    )


# ============================================================
# 6. 기존 오류 로그 불러오기
# ============================================================

def load_existing_errors(
) -> list[dict[str, Any]]:
    """
    기존 오류 로그가 있으면 불러온다.
    """

    if (
        not RESUME_FROM_EXISTING
        or not ERROR_LOG_PATH.exists()
    ):
        return []

    error_df = pd.read_csv(
        ERROR_LOG_PATH
    )

    if error_df.empty:
        return []

    error_df["ticker"] = (
        error_df["ticker"]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    error_df = error_df.drop_duplicates(
        subset=["ticker"],
        keep="last",
    )

    return (
        error_df
        .where(
            pd.notna(error_df),
            None,
        )
        .to_dict(
            orient="records"
        )
    )


# ============================================================
# 7. 기업 하나 수집
# ============================================================

def collect_single_company(
    company_master: pd.DataFrame,
    ticker: str,
) -> dict[str, Any]:
    """
    기업 하나의 SEC 재무데이터를 수집하고
    품질 검증과 재무비율을 계산한다.
    """

    company_info = find_company_info(
        company_master,
        ticker,
    )

    company_facts = request_company_facts(
        company_info["cik"]
    )

    financials = extract_company_financials(
        company_info,
        company_facts,
    )

    validation = validate_period_consistency(
        financials
    )

    ratios = calculate_financial_ratios(
        financials
    )

    result = {
        **financials,
        **ratios,
        "period_consistent": validation[
            "is_consistent"
        ],
        "period_issues": (
            str(validation["mismatches"])
            if validation["mismatches"]
            else None
        ),
    }

    return result


# ============================================================
# 8. 오류 유형 판별
# ============================================================

def is_structural_data_error(
    error: Exception,
) -> bool:
    """
    재요청으로 해결되지 않는 구조적 데이터 오류인지 판별한다.
    """

    if not isinstance(error, ValueError):
        return False

    structural_messages = (
        "US-GAAP 데이터를 찾지 못했습니다",
        "최신 연간 Revenue 데이터를 찾지 못했습니다",
        "Revenue 기준일을 확인하지 못했습니다",
    )

    error_message = str(error)

    return any(
        message in error_message
        for message in structural_messages
    )


# ============================================================
# 9. 재시도 포함 수집
# ============================================================

def collect_with_retry(
    company_master: pd.DataFrame,
    ticker: str,
) -> dict[str, Any]:
    """
    네트워크 오류는 재시도하고,
    구조적 데이터 부재는 즉시 실패 처리한다.
    """

    last_error: Exception | None = None

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):
        try:
            return collect_single_company(
                company_master,
                ticker,
            )

        except Exception as error:
            last_error = error

            if is_structural_data_error(
                error
            ):
                raise

            retryable = isinstance(
                error,
                (
                    requests.RequestException,
                    KeyError,
                    TypeError,
                    IndexError,
                ),
            )

            if not retryable:
                raise

            print(
                f"  요청 실패 "
                f"({attempt}/{MAX_RETRIES}): "
                f"{type(error).__name__}: {error}"
            )

            if attempt < MAX_RETRIES:
                wait_seconds = (
                    RETRY_WAIT_SECONDS
                    * attempt
                )

                print(
                    f"  {wait_seconds}초 후 재시도"
                )

                time.sleep(
                    wait_seconds
                )

    if last_error is None:
        raise RuntimeError(
            f"{ticker} 수집 중 알 수 없는 오류가 발생했습니다."
        )

    raise last_error


# ============================================================
# 10. 체크포인트 저장
# ============================================================

def save_checkpoint(
    successful_results: list[dict[str, Any]],
    error_results: list[dict[str, Any]],
) -> None:
    """
    현재까지의 성공 결과와 오류 로그를 저장한다.
    """

    if successful_results:
        financial_df = pd.DataFrame(
            successful_results
        )

        financial_df = (
            financial_df
            .drop_duplicates(
                subset=["ticker"],
                keep="last",
            )
            .sort_values("ticker")
            .reset_index(drop=True)
        )

        financial_df.to_csv(
            OUTPUT_CSV_PATH,
            index=False,
            encoding="utf-8-sig",
        )

    if error_results:
        error_df = pd.DataFrame(
            error_results
        )

        error_df = (
            error_df
            .drop_duplicates(
                subset=["ticker"],
                keep="last",
            )
            .sort_values("ticker")
            .reset_index(drop=True)
        )

        error_df.to_csv(
            ERROR_LOG_PATH,
            index=False,
            encoding="utf-8-sig",
        )


# ============================================================
# 11. 여러 기업 반복 수집
# ============================================================

def collect_financial_master(
    company_master: pd.DataFrame,
    tickers: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    여러 기업을 반복 수집한다.
    """

    successful_results, collected_tickers = (
        load_existing_results()
    )

    error_results = load_existing_errors()

    target_ticker_set = set(
        tickers
    )

    existing_count = len(
        collected_tickers.intersection(
            target_ticker_set
        )
    )

    if RETRY_EXISTING_ERRORS:
        remaining_tickers = [
            ticker
            for ticker in tickers
            if ticker not in collected_tickers
        ]

    else:
        failed_tickers = {
            str(row.get("ticker", ""))
            .upper()
            .strip()
            for row in error_results
        }

        remaining_tickers = [
            ticker
            for ticker in tickers
            if (
                ticker not in collected_tickers
                and ticker not in failed_tickers
            )
        ]

    total_target_count = len(
        tickers
    )

    remaining_count = len(
        remaining_tickers
    )

    print()
    print("=" * 70)
    print("수집 진행 현황")
    print("=" * 70)
    print("전체 대상:", total_target_count)
    print("기존 완료:", existing_count)
    print("남은 기업:", remaining_count)

    start_time = time.perf_counter()
    current_run_success = 0
    current_run_failure = 0

    for index, ticker in enumerate(
        remaining_tickers,
        start=1,
    ):
        overall_number = (
            existing_count
            + index
        )

        print()
        print("=" * 70)
        print(
            f"[{overall_number}/"
            f"{total_target_count}] "
            f"{ticker} 수집 시작"
        )
        print("=" * 70)

        company_start_time = (
            time.perf_counter()
        )

        try:
            result = collect_with_retry(
                company_master,
                ticker,
            )

            elapsed_seconds = (
                time.perf_counter()
                - company_start_time
            )

            result["response_seconds"] = round(
                elapsed_seconds,
                3,
            )

            successful_results.append(
                result
            )

            # 이전 오류가 있으면 제거
            error_results = [
                row
                for row in error_results
                if (
                    str(
                        row.get(
                            "ticker",
                            "",
                        )
                    )
                    .upper()
                    .strip()
                    != ticker
                )
            ]

            current_run_success += 1

            print(f"{ticker} 수집 성공")
            print(
                "기준일:",
                result.get(
                    "target_end_date"
                ),
            )
            print(
                "Revenue:",
                result.get(
                    "revenue"
                ),
            )
            print(
                "기간 정합성:",
                result.get(
                    "period_consistent"
                ),
            )
            print(
                "오래된 데이터:",
                result.get(
                    "is_stale"
                ),
            )
            print(
                "재무 경고:",
                result.get(
                    "financial_warning"
                ),
            )
            print(
                "처리시간:",
                result.get(
                    "response_seconds"
                ),
                "초",
            )

        except Exception as error:
            elapsed_seconds = (
                time.perf_counter()
                - company_start_time
            )

            error_results = [
                row
                for row in error_results
                if (
                    str(
                        row.get(
                            "ticker",
                            "",
                        )
                    )
                    .upper()
                    .strip()
                    != ticker
                )
            ]

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
                    "structural_error": (
                        is_structural_data_error(
                            error
                        )
                    ),
                }
            )

            current_run_failure += 1

            print(f"{ticker} 수집 실패")
            print(
                type(error).__name__,
                ":",
                error,
            )

        if (
            index % CHECKPOINT_INTERVAL == 0
            or index == remaining_count
        ):
            save_checkpoint(
                successful_results,
                error_results,
            )

            print()
            print(
                "체크포인트 저장 완료:",
                f"{overall_number}/"
                f"{total_target_count}",
            )

        if index < remaining_count:
            time.sleep(
                REQUEST_INTERVAL_SECONDS
            )

    total_elapsed_seconds = (
        time.perf_counter()
        - start_time
    )

    financial_df = pd.DataFrame(
        successful_results
    )

    if not financial_df.empty:
        financial_df = (
            financial_df
            .drop_duplicates(
                subset=["ticker"],
                keep="last",
            )
            .sort_values("ticker")
            .reset_index(drop=True)
        )

    error_df = pd.DataFrame(
        error_results
    )

    if not error_df.empty:
        error_df = (
            error_df
            .drop_duplicates(
                subset=["ticker"],
                keep="last",
            )
            .sort_values("ticker")
            .reset_index(drop=True)
        )

    run_summary = {
        "target_count": total_target_count,
        "existing_success_count": existing_count,
        "remaining_count": remaining_count,
        "current_run_success": (
            current_run_success
        ),
        "current_run_failure": (
            current_run_failure
        ),
        "final_success_count": len(
            financial_df
        ),
        "final_error_count": len(
            error_df
        ),
        "elapsed_seconds": round(
            total_elapsed_seconds,
            2,
        ),
        "elapsed_minutes": round(
            total_elapsed_seconds / 60,
            2,
        ),
    }

    return (
        financial_df,
        error_df,
        run_summary,
    )


# ============================================================
# 12. 품질 리포트 생성
# ============================================================

def create_quality_report(
    financial_df: pd.DataFrame,
    target_count: int,
) -> pd.DataFrame:
    """
    Financial Master의 컬럼별 확보율과
    품질 플래그 비율을 계산한다.
    """

    report_rows = []

    successful_count = len(
        financial_df
    )

    collection_coverage = (
        successful_count
        / target_count
        * 100
        if target_count
        else 0.0
    )

    report_rows.append(
        {
            "metric": "collection_success",
            "available": successful_count,
            "missing": (
                target_count
                - successful_count
            ),
            "coverage_pct": round(
                collection_coverage,
                2,
            ),
        }
    )

    coverage_columns = [
        "revenue",
        "operating_income",
        "net_income",
        "assets",
        "liabilities",
        "period_consistent",
        "liabilities_calculated",
        "data_age_days",
        "is_stale",
        "financial_warning",
    ]

    for column in coverage_columns:
        if column not in financial_df.columns:
            available_count = 0

        else:
            available_count = int(
                financial_df[column]
                .notna()
                .sum()
            )

        missing_count = (
            successful_count
            - available_count
        )

        coverage_pct = (
            available_count
            / successful_count
            * 100
            if successful_count
            else 0.0
        )

        report_rows.append(
            {
                "metric": column,
                "available": available_count,
                "missing": missing_count,
                "coverage_pct": round(
                    coverage_pct,
                    2,
                ),
            }
        )

    # Boolean 품질 지표의 True 비율
    boolean_columns = [
        "period_consistent",
        "liabilities_calculated",
        "is_stale",
        "financial_warning",
    ]

    for column in boolean_columns:
        if column not in financial_df.columns:
            continue

        true_count = int(
            financial_df[column]
            .eq(True)
            .sum()
        )

        false_count = int(
            financial_df[column]
            .eq(False)
            .sum()
        )

        true_pct = (
            true_count
            / successful_count
            * 100
            if successful_count
            else 0.0
        )

        report_rows.append(
            {
                "metric": (
                    f"{column}_true"
                ),
                "available": true_count,
                "missing": false_count,
                "coverage_pct": round(
                    true_pct,
                    2,
                ),
            }
        )

    return pd.DataFrame(
        report_rows
    )


# ============================================================
# 13. 최종 저장
# ============================================================

def save_final_results(
    financial_df: pd.DataFrame,
    error_df: pd.DataFrame,
    quality_df: pd.DataFrame,
    run_summary: dict,
) -> None:
    """
    최종 Financial Master와 관련 리포트를 저장한다.
    """

    if not financial_df.empty:
        financial_df.to_csv(
            OUTPUT_CSV_PATH,
            index=False,
            encoding="utf-8-sig",
        )

        financial_df.to_excel(
            OUTPUT_EXCEL_PATH,
            index=False,
        )

        print()
        print("Financial Master 저장 완료")
        print("CSV:", OUTPUT_CSV_PATH)
        print("Excel:", OUTPUT_EXCEL_PATH)

    if not error_df.empty:
        error_df.to_csv(
            ERROR_LOG_PATH,
            index=False,
            encoding="utf-8-sig",
        )

        print(
            "오류 로그:",
            ERROR_LOG_PATH,
        )

    elif ERROR_LOG_PATH.exists():
        ERROR_LOG_PATH.unlink()

    quality_df.to_csv(
        QUALITY_REPORT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    run_summary_df = pd.DataFrame(
        [run_summary]
    )

    run_summary_df.to_csv(
        RUN_SUMMARY_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print(
        "품질 리포트:",
        QUALITY_REPORT_PATH,
    )
    print(
        "실행 요약:",
        RUN_SUMMARY_PATH,
    )


# ============================================================
# 14. 결과 미리보기
# ============================================================

def print_final_preview(
    financial_df: pd.DataFrame,
) -> None:
    """
    핵심 컬럼을 터미널에 출력한다.
    """

    if financial_df.empty:
        return

    preview_columns = [
        "ticker",
        "target_end_date",
        "revenue",
        "operating_income",
        "net_income",
        "assets",
        "liabilities",
        "liabilities_calculated",
        "period_consistent",
        "is_stale",
        "financial_warning",
        "warning_messages",
    ]

    available_columns = [
        column
        for column in preview_columns
        if column in financial_df.columns
    ]

    print()
    print("=" * 100)
    print("Financial Master Preview")
    print("=" * 100)

    print(
        financial_df[
            available_columns
        ].head(30).to_string(
            index=False
        )
    )


# ============================================================
# 15. 실행 흐름
# ============================================================

def main() -> None:
    """
    Financial Master 구축 전체 흐름을 실행한다.
    """

    print("=" * 70)
    print("Financial Master 최종 구축 시작")
    print("=" * 70)
    print("대상 거래소:", TARGET_EXCHANGES)
    print("SAMPLE_SIZE:", SAMPLE_SIZE)
    print("출력 구분:", OUTPUT_SUFFIX)
    print(
        "이어받기:",
        RESUME_FROM_EXISTING,
    )
    print(
        "기존 오류 재시도:",
        RETRY_EXISTING_ERRORS,
    )

    company_master = load_company_master()

    target_tickers = select_target_tickers(
        company_master,
        SAMPLE_SIZE,
    )

    (
        financial_df,
        error_df,
        run_summary,
    ) = collect_financial_master(
        company_master,
        target_tickers,
    )

    quality_df = create_quality_report(
        financial_df,
        len(target_tickers),
    )

    print()
    print("=" * 70)
    print("Financial Master 품질 요약")
    print("=" * 70)

    print(
        quality_df.to_string(
            index=False
        )
    )

    save_final_results(
        financial_df=financial_df,
        error_df=error_df,
        quality_df=quality_df,
        run_summary=run_summary,
    )

    print()
    print("=" * 70)
    print("Financial Master 최종 구축 완료")
    print("=" * 70)

    for key, value in run_summary.items():
        print(f"{key}: {value}")

    print_final_preview(
        financial_df
    )


if __name__ == "__main__":
    main()