"""
AI Infrastructure Custom Index - Backtest
Step 1) 가격 데이터 다운로드 (Yahoo Finance)

대상
----
- index_weights_quarterly.csv에 등장한 전체 편입 티커(전 분기 합집합)
- 벤치마크 QQQ (NASDAQ-100)

방식
----
- yfinance 배치 다운로드, auto_adjust=True
  → 조정 종가(Adjusted Close): 배당·액면분할 반영 = Total Return 기준
- 시작일 버퍼: 기준일(2009-07-01) 이전(2009-06-01)부터 받아
  첫 리밸런싱 진입가를 안전하게 확보

출력
----
data/prices/prices_close.csv     Date × ticker 조정종가 와이드 매트릭스
data/prices/prices_close.parquet
data/prices/benchmark_qqq.csv     QQQ 조정종가
data/prices/prices_coverage.csv   티커별 커버리지(첫/마지막 거래일, 결측)
data/prices/download_missing.csv  데이터 미확보 티커(폐지/티커변경 진단)

주의(생존편향·티커변경)
-----------------------
유니버스 100종목은 "현재" SEC 데이터에서 선정되어, 과거에 상장폐지되었거나
티커가 바뀐 기업은 애초에 포함되지 않는다. 여기서 데이터가 안 잡히는 티커는
그 진단 로그(download_missing.csv)로 남긴다. 백테스트 단계에서 이 한계를
명시적으로 보고한다.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd
import yfinance as yf


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_WEIGHTS_PATH = (
    PROJECT_ROOT / "data" / "index" / "index_weights_quarterly.csv"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "prices"

BENCHMARK_TICKER = "QQQ"

# 기준일 2009-07-01 이전 버퍼
DEFAULT_START = "2009-06-01"
# 종료일(포함 위해 다음날). 데이터 최신일까지 자동 확보
DEFAULT_END = "2026-07-23"


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_universe_tickers(weights_path: Path) -> list[str]:
    df = pd.read_csv(weights_path)
    tickers = (
        df["ticker"].astype(str).str.strip().str.upper().unique()
    )
    tickers = sorted(t for t in tickers if t and t != "NAN")
    return tickers


def download_close(
    tickers: list[str],
    start: str,
    end: str,
) -> pd.DataFrame:
    """조정 종가(Adjusted Close) 와이드 매트릭스를 반환합니다."""
    logging.info("다운로드 시작: %s개 티커", len(tickers))

    raw = yf.download(
        tickers=tickers,
        start=start,
        end=end,
        auto_adjust=True,   # 배당·분할 반영 종가
        progress=False,
        threads=True,
        group_by="column",
    )

    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:
        # 단일 티커인 경우
        close = raw[["Close"]].copy()
        close.columns = tickers

    close.index = pd.to_datetime(close.index)
    close = close.sort_index()

    # 컬럼 순서 정렬
    ordered = [t for t in tickers if t in close.columns]
    close = close[ordered]

    return close


def build_coverage(close: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ticker in close.columns:
        series = close[ticker].dropna()
        if series.empty:
            rows.append(
                {
                    "ticker": ticker,
                    "n_obs": 0,
                    "first_date": None,
                    "last_date": None,
                    "missing_within_range": None,
                }
            )
            continue

        first, last = series.index.min(), series.index.max()
        # 상장 이후 구간 내 결측(거래일 기준)
        in_range = close.loc[first:last, ticker]
        missing = int(in_range.isna().sum())

        rows.append(
            {
                "ticker": ticker,
                "n_obs": int(series.shape[0]),
                "first_date": first.date(),
                "last_date": last.date(),
                "missing_within_range": missing,
            }
        )

    return pd.DataFrame(rows)


def run(
    weights_path: Path,
    output_dir: Path,
    start: str,
    end: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    tickers = load_universe_tickers(weights_path)
    logging.info("유니버스 고유 티커: %s개", len(tickers))

    all_tickers = tickers + [BENCHMARK_TICKER]

    close = download_close(all_tickers, start=start, end=end)

    # 완전 결측(데이터 미확보) 티커 = 폐지/티커변경 후보
    missing_tickers = [
        t
        for t in all_tickers
        if t not in close.columns or close[t].dropna().empty
    ]

    # 벤치마크 분리 저장
    if BENCHMARK_TICKER not in close.columns:
        raise RuntimeError(
            "벤치마크 QQQ 데이터를 받지 못했습니다. 네트워크를 확인하세요."
        )

    qqq = close[[BENCHMARK_TICKER]].dropna().copy()
    qqq.columns = ["qqq_close"]

    constituent_close = close[
        [t for t in tickers if t in close.columns]
    ].copy()

    coverage = build_coverage(constituent_close)

    # 저장
    close_csv = output_dir / "prices_close.csv"
    close_parquet = output_dir / "prices_close.parquet"
    qqq_csv = output_dir / "benchmark_qqq.csv"
    coverage_csv = output_dir / "prices_coverage.csv"
    missing_csv = output_dir / "download_missing.csv"

    constituent_close.to_csv(close_csv, encoding="utf-8-sig")
    constituent_close.to_parquet(close_parquet)
    qqq.to_csv(qqq_csv, encoding="utf-8-sig")
    coverage.to_csv(coverage_csv, index=False, encoding="utf-8-sig")

    pd.DataFrame({"missing_ticker": missing_tickers}).to_csv(
        missing_csv, index=False, encoding="utf-8-sig"
    )

    logging.info("=" * 60)
    logging.info("가격 다운로드 완료")
    logging.info("구성종목 매트릭스: %s (%s행 × %s종목)",
                 close_csv, len(constituent_close), constituent_close.shape[1])
    logging.info("기간: %s ~ %s",
                 constituent_close.index.min().date(),
                 constituent_close.index.max().date())
    logging.info("QQQ: %s (%s행)", qqq_csv, len(qqq))
    logging.info("데이터 미확보 티커(폐지/변경 후보): %s개 %s",
                 len(missing_tickers), missing_tickers)
    logging.info("=" * 60)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="백테스트용 편입종목 및 QQQ 가격 다운로드"
    )
    parser.add_argument(
        "--weights-file", type=Path, default=DEFAULT_WEIGHTS_PATH
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR
    )
    parser.add_argument("--start", type=str, default=DEFAULT_START)
    parser.add_argument("--end", type=str, default=DEFAULT_END)
    return parser.parse_args()


def main() -> None:
    configure_logging()
    args = parse_args()
    run(
        weights_path=args.weights_file,
        output_dir=args.output_dir,
        start=args.start,
        end=args.end,
    )


if __name__ == "__main__":
    main()
