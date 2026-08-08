"""
03_build_fact_store.py

SEC 기업 마스터에 포함된 기업을 순회하면서
기업별 SEC Company Facts 전체 이력을 PIT용 Parquet 파일로 저장한다.

주요 기능
----------
1. sec_company_master.csv에서 기업 목록 불러오기
2. SEC Company Facts API 요청
3. financial_extractor.py의 Fact Store 변환 함수 재사용
4. 기업별 data/facts/{CIK}.parquet 저장
5. 기존 파일 건너뛰기 및 덮어쓰기 옵션
6. 요청 간 대기 및 재시도
7. 성공·실패·건너뛰기 실행 로그 CSV 저장
8. 일부 기업 테스트 또는 전체 기업 실행 지원
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from financial_extractor_final import (
    COMPANY_MASTER_PATH,
    FACT_STORE_DIR,
    create_fact_store_dataframe,
    request_company_facts,
    save_fact_store,
)


# ============================================================
# 1. 기본 설정
# ============================================================

LOG_DIR = Path(
    "01_Data_Acquisition/output/fact_store_logs"
)

DEFAULT_DELAY_SECONDS = 0.20
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_WAIT_SECONDS = 2.0


# ============================================================
# 2. 기업 마스터 불러오기 및 정리
# ============================================================

def normalize_cik(
    value: Any,
) -> str:
    """
    CIK를 10자리 문자열로 통일한다.
    """

    return (
        str(value)
        .replace(".0", "")
        .strip()
        .zfill(10)
    )


def load_target_companies(
    master_path: Path = COMPANY_MASTER_PATH,
    limit: int | None = None,
    start_index: int = 0,
    ticker: str | None = None,
) -> pd.DataFrame:
    """
    기업 마스터를 불러오고 Fact Store 생성 대상을 정리한다.

    Parameters
    ----------
    master_path:
        SEC 기업 마스터 CSV 경로
    limit:
        처리할 최대 기업 수. None이면 전체 처리
    start_index:
        정렬된 기업 목록에서 시작할 위치
    ticker:
        특정 티커만 실행할 경우 사용
    """

    if not master_path.exists():
        raise FileNotFoundError(
            "기업 마스터 파일을 찾지 못했습니다: "
            f"{master_path}"
        )

    company_master = pd.read_csv(
        master_path,
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

    company_name_column = None

    if "company_name" in company_master.columns:
        company_name_column = "company_name"
    elif "name" in company_master.columns:
        company_name_column = "name"

    if company_name_column is None:
        company_master["company_name"] = None
    elif company_name_column != "company_name":
        company_master["company_name"] = (
            company_master[company_name_column]
        )

    target_df = company_master[
        [
            "cik",
            "ticker",
            "company_name",
            "exchange",
        ]
    ].copy()

    target_df["cik"] = (
        target_df["cik"]
        .map(normalize_cik)
    )

    target_df["ticker"] = (
        target_df["ticker"]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    target_df = target_df.loc[
        target_df["ticker"].ne("")
        & target_df["cik"].ne("0000000000")
    ].copy()

    target_df = (
        target_df
        .drop_duplicates(
            subset=["cik"],
            keep="first",
        )
        .sort_values(
            ["ticker", "cik"]
        )
        .reset_index(drop=True)
    )

    if ticker:
        normalized_ticker = ticker.upper().strip()

        target_df = target_df.loc[
            target_df["ticker"].eq(
                normalized_ticker
            )
        ].copy()

        if target_df.empty:
            raise ValueError(
                f"기업 마스터에서 {normalized_ticker}를 "
                "찾지 못했습니다."
            )

    if start_index < 0:
        raise ValueError(
            "start_index는 0 이상이어야 합니다."
        )

    target_df = target_df.iloc[
        start_index:
    ].copy()

    if limit is not None:
        if limit <= 0:
            raise ValueError(
                "limit은 1 이상이어야 합니다."
            )

        target_df = target_df.head(
            limit
        ).copy()

    return target_df.reset_index(
        drop=True
    )


# ============================================================
# 3. 기업 정보 변환
# ============================================================

def row_to_company_info(
    row: pd.Series,
) -> dict[str, Any]:
    """
    기업 마스터 한 행을 financial_extractor에서 사용하는
    company_info 형식으로 변환한다.
    """

    return {
        "ticker": row["ticker"],
        "company_name": row.get(
            "company_name"
        ),
        "cik": normalize_cik(
            row["cik"]
        ),
        "exchange": row.get(
            "exchange"
        ),
    }


# ============================================================
# 4. SEC 요청 재시도
# ============================================================

def request_company_facts_with_retry(
    cik: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_wait_seconds: float = DEFAULT_RETRY_WAIT_SECONDS,
) -> dict[str, Any]:
    """
    일시적인 네트워크 오류와 SEC 서버 오류에 대비해
    Company Facts 요청을 재시도한다.
    """

    last_error: Exception | None = None

    for attempt in range(
        1,
        max_retries + 1,
    ):
        try:
            return request_company_facts(
                cik
            )

        except requests.HTTPError as error:
            last_error = error

            status_code = (
                error.response.status_code
                if error.response is not None
                else None
            )

            # 데이터가 존재하지 않는 기업은 재시도해도
            # 달라질 가능성이 낮으므로 즉시 실패 처리한다.
            if status_code in {
                400,
                404,
            }:
                raise

            # Rate Limit 또는 SEC 서버 오류만 재시도한다.
            if status_code not in {
                403,
                429,
                500,
                502,
                503,
                504,
            }:
                raise

        except (
            requests.Timeout,
            requests.ConnectionError,
        ) as error:
            last_error = error

        if attempt < max_retries:
            wait_seconds = (
                retry_wait_seconds
                * attempt
            )

            print(
                f"  재시도 대기: {wait_seconds:.1f}초 "
                f"({attempt}/{max_retries})"
            )

            time.sleep(
                wait_seconds
            )

    if last_error is not None:
        raise last_error

    raise RuntimeError(
        "SEC Company Facts 요청에 실패했습니다."
    )


# ============================================================
# 5. 실행 로그 저장
# ============================================================

def create_log_path() -> Path:
    """
    실행 시각이 포함된 로그 파일 경로를 생성한다.
    """

    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    return (
        LOG_DIR
        / f"fact_store_run_{timestamp}.csv"
    )


def save_run_log(
    log_records: list[dict[str, Any]],
    log_path: Path,
) -> None:
    """
    현재까지의 실행 로그를 CSV로 저장한다.
    """

    log_df = pd.DataFrame(
        log_records
    )

    log_df.to_csv(
        log_path,
        index=False,
        encoding="utf-8-sig",
    )


# ============================================================
# 6. 기업 하나 처리
# ============================================================

def process_company(
    company_info: dict[str, Any],
    overwrite: bool,
    max_retries: int,
    retry_wait_seconds: float,
) -> dict[str, Any]:
    """
    기업 하나의 Company Facts를 요청하고
    Fact Store Parquet 파일을 저장한다.
    """

    cik = company_info["cik"]
    ticker = company_info["ticker"]

    output_path = (
        FACT_STORE_DIR
        / f"{cik}.parquet"
    )

    started_at = datetime.now()

    if (
        output_path.exists()
        and not overwrite
    ):
        return {
            "ticker": ticker,
            "cik": cik,
            "status": "skipped",
            "row_count": None,
            "output_path": str(
                output_path
            ),
            "error_type": None,
            "error_message": None,
            "started_at": (
                started_at.isoformat(
                    timespec="seconds"
                )
            ),
            "finished_at": (
                datetime.now().isoformat(
                    timespec="seconds"
                )
            ),
            "elapsed_seconds": 0.0,
        }

    try:
        company_facts = (
            request_company_facts_with_retry(
                cik=cik,
                max_retries=max_retries,
                retry_wait_seconds=(
                    retry_wait_seconds
                ),
            )
        )

        fact_store_df = (
            create_fact_store_dataframe(
                company_info=company_info,
                company_facts=(
                    company_facts
                ),
            )
        )

        if fact_store_df.empty:
            raise ValueError(
                "변환된 Fact Store가 비어 있습니다."
            )

        saved_path = save_fact_store(
            fact_store_df=(
                fact_store_df
            ),
            cik=cik,
        )

        finished_at = datetime.now()

        return {
            "ticker": ticker,
            "cik": cik,
            "status": "success",
            "row_count": int(
                len(fact_store_df)
            ),
            "output_path": str(
                saved_path
            ),
            "error_type": None,
            "error_message": None,
            "started_at": (
                started_at.isoformat(
                    timespec="seconds"
                )
            ),
            "finished_at": (
                finished_at.isoformat(
                    timespec="seconds"
                )
            ),
            "elapsed_seconds": round(
                (
                    finished_at
                    - started_at
                ).total_seconds(),
                3,
            ),
        }

    except Exception as error:
        finished_at = datetime.now()

        return {
            "ticker": ticker,
            "cik": cik,
            "status": "failed",
            "row_count": None,
            "output_path": None,
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(
                error
            ),
            "started_at": (
                started_at.isoformat(
                    timespec="seconds"
                )
            ),
            "finished_at": (
                finished_at.isoformat(
                    timespec="seconds"
                )
            ),
            "elapsed_seconds": round(
                (
                    finished_at
                    - started_at
                ).total_seconds(),
                3,
            ),
        }


# ============================================================
# 7. 전체 기업 일괄 실행
# ============================================================

def build_all_fact_stores(
    target_companies: pd.DataFrame,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    overwrite: bool = False,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_wait_seconds: float = DEFAULT_RETRY_WAIT_SECONDS,
) -> Path:
    """
    대상 기업 전체의 Fact Store를 순차적으로 생성한다.
    """

    if target_companies.empty:
        raise ValueError(
            "처리할 기업이 없습니다."
        )

    if delay_seconds < 0:
        raise ValueError(
            "delay_seconds는 0 이상이어야 합니다."
        )

    FACT_STORE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    log_path = create_log_path()
    log_records: list[
        dict[str, Any]
    ] = []

    total_count = len(
        target_companies
    )

    print()
    print("=" * 70)
    print("PIT Fact Store 일괄 생성")
    print("=" * 70)
    print(
        "대상 기업 수:",
        f"{total_count:,}",
    )
    print(
        "저장 폴더:",
        FACT_STORE_DIR,
    )
    print(
        "기존 파일 덮어쓰기:",
        overwrite,
    )
    print(
        "요청 간 대기:",
        f"{delay_seconds:.2f}초",
    )
    print(
        "실행 로그:",
        log_path,
    )
    print("=" * 70)

    try:
        for position, row in (
            target_companies.iterrows()
        ):
            sequence = position + 1

            company_info = (
                row_to_company_info(
                    row
                )
            )

            ticker = company_info[
                "ticker"
            ]
            cik = company_info[
                "cik"
            ]

            print()
            print(
                f"[{sequence:,}/{total_count:,}] "
                f"{ticker} | CIK {cik}"
            )

            result = process_company(
                company_info=company_info,
                overwrite=overwrite,
                max_retries=max_retries,
                retry_wait_seconds=(
                    retry_wait_seconds
                ),
            )

            log_records.append(
                result
            )

            status = result[
                "status"
            ]

            if status == "success":
                print(
                    "  저장 완료:",
                    result[
                        "output_path"
                    ],
                )
                print(
                    "  행 수:",
                    f"{result['row_count']:,}",
                )
                print(
                    "  소요 시간:",
                    f"{result['elapsed_seconds']:.2f}초",
                )

            elif status == "skipped":
                print(
                    "  건너뜀: 기존 파일 존재"
                )

            else:
                print(
                    "  실패:",
                    result[
                        "error_type"
                    ],
                    "-",
                    result[
                        "error_message"
                    ],
                )

            # 중간에 종료되더라도 완료된 내역이 남도록
            # 매 기업 처리 후 로그를 저장한다.
            save_run_log(
                log_records,
                log_path,
            )

            if (
                sequence < total_count
                and delay_seconds > 0
            ):
                time.sleep(
                    delay_seconds
                )

    except KeyboardInterrupt:
        print()
        print(
            "사용자 중단을 감지했습니다. "
            "현재까지의 로그를 저장합니다."
        )

        save_run_log(
            log_records,
            log_path,
        )

    success_count = sum(
        record["status"] == "success"
        for record in log_records
    )
    skipped_count = sum(
        record["status"] == "skipped"
        for record in log_records
    )
    failed_count = sum(
        record["status"] == "failed"
        for record in log_records
    )

    print()
    print("=" * 70)
    print("Fact Store 실행 결과")
    print("=" * 70)
    print(
        "성공:",
        f"{success_count:,}",
    )
    print(
        "건너뜀:",
        f"{skipped_count:,}",
    )
    print(
        "실패:",
        f"{failed_count:,}",
    )
    print(
        "로그 파일:",
        log_path,
    )

    return log_path


# ============================================================
# 8. 명령행 옵션
# ============================================================

def parse_arguments() -> argparse.Namespace:
    """
    실행 옵션을 읽는다.
    """

    parser = argparse.ArgumentParser(
        description=(
            "SEC 기업별 PIT Fact Store를 "
            "Parquet으로 일괄 생성합니다."
        )
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "처리할 최대 기업 수. "
            "생략하면 전체 기업을 처리합니다."
        ),
    )

    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help=(
            "정렬된 기업 목록에서 시작할 위치 "
            "(기본값: 0)"
        ),
    )

    parser.add_argument(
        "--ticker",
        type=str,
        default=None,
        help=(
            "특정 티커만 실행합니다. "
            "예: --ticker NVDA"
        ),
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=(
            "SEC 요청 사이의 대기 시간(초). "
            f"기본값: {DEFAULT_DELAY_SECONDS}"
        ),
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "기존 Parquet 파일이 있어도 "
            "다시 생성합니다."
        ),
    )

    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=(
            "일시적 요청 오류 발생 시 "
            "최대 재시도 횟수"
        ),
    )

    parser.add_argument(
        "--retry-wait",
        type=float,
        default=DEFAULT_RETRY_WAIT_SECONDS,
        help=(
            "재시도 기본 대기 시간(초)"
        ),
    )

    return parser.parse_args()


# ============================================================
# 9. 실행
# ============================================================

def main() -> None:
    """
    명령행 옵션에 따라 Fact Store 일괄 생성을 실행한다.
    """

    args = parse_arguments()

    target_companies = (
        load_target_companies(
            limit=args.limit,
            start_index=(
                args.start_index
            ),
            ticker=args.ticker,
        )
    )

    build_all_fact_stores(
        target_companies=(
            target_companies
        ),
        delay_seconds=args.delay,
        overwrite=args.overwrite,
        max_retries=args.max_retries,
        retry_wait_seconds=(
            args.retry_wait
        ),
    )


if __name__ == "__main__":
    main()
