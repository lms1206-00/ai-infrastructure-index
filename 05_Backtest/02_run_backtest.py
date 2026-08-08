"""
AI Infrastructure Custom Index - Backtest
Step 2) 지수 레벨 생성 + QQQ 추종 성능 평가

목적
----
프로젝트 목표는 시장을 이기는 것이 아니라, AI Infrastructure Custom Index가
NASDAQ-100(QQQ)을 얼마나 잘 "추종"하는지 검증하는 것이다.

입력
----
data/index/index_weights_quarterly.csv   분기 리밸런싱 편입종목·비중(불변)
data/prices/prices_close.csv             편입종목 조정종가
data/prices/benchmark_qqq.csv            QQQ 조정종가

방식
----
1) 각 리밸런싱 시점 T_i의 Weight로 포트폴리오 구성
2) 다음 리밸런싱 T_{i+1}까지 Buy & Hold (비중은 가격에 따라 drift)
3) 리밸런싱은 T_{i+1} 종가에서 실행 (해당일 수익률까지는 기존 포트폴리오)
4) 기준값 2009-07-01 = 100 으로 Index Level 시계열 생성

편향/결측 처리 (백테스트 무결성)
--------------------------------
- Look-ahead: 비중은 PIT 스냅샷(정보가용일 반영)에서 산출되고, 거래는
  리밸런싱일(분기말) 이후 가격으로만 체결. 가격은 ffill만 사용(bfill 금지)
  → 미래정보 미사용.
- 결측: 상장 이전은 NaN 유지(진입 대상 제외), 상장 후 구간 내 결측은
  직전가로 ffill. 진입일에 가격이 없는 종목은 제외하고 잔여 비중을 재정규화.
- 상장폐지/티커변경: 유니버스가 "현재" 티커라 과거 폐지·변경분은 원천적으로
  미포함(=생존편향). 데이터가 있는 티커의 중간 폐지는 마지막가로 동결.
- 무위험수익률(rf)=0 가정(Sharpe). 연율화 계수 252.

출력
----
data/backtest/index_level.csv
data/backtest/benchmark_qqq.csv
data/backtest/performance_summary.csv
data/backtest/yearly_returns.csv
data/backtest/tracking_metrics.csv
data/backtest/rebalance_weight_check.csv
data/backtest/backtest_diagnostics.csv
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_WEIGHTS = PROJECT_ROOT / "data" / "index" / "index_weights_quarterly.csv"
DEFAULT_PRICES = PROJECT_ROOT / "data" / "prices" / "prices_close.csv"
DEFAULT_QQQ = PROJECT_ROOT / "data" / "prices" / "benchmark_qqq.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "backtest"

BASE_DATE = pd.Timestamp("2009-07-01")
BASE_LEVEL = 100.0
TRADING_DAYS = 252
RISK_FREE = 0.0


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ============================================================
# 데이터 로딩
# ============================================================

def load_prices(prices_path: Path) -> pd.DataFrame:
    px = pd.read_csv(prices_path, index_col=0)
    px.index = pd.to_datetime(px.index)
    px = px.sort_index()
    px.columns = [str(c).upper() for c in px.columns]
    return px


def load_qqq(qqq_path: Path) -> pd.Series:
    q = pd.read_csv(qqq_path, index_col=0)
    q.index = pd.to_datetime(q.index)
    q = q.sort_index()
    col = q.columns[0]
    return q[col].rename("qqq")


def load_weights(weights_path: Path) -> pd.DataFrame:
    w = pd.read_csv(weights_path)
    w["snapshot_date"] = pd.to_datetime(w["snapshot_date"])
    w["ticker"] = w["ticker"].astype(str).str.upper().str.strip()
    return w[["snapshot_date", "ticker", "weight"]].copy()


# ============================================================
# 지수 레벨 생성 (buy & hold, 분기 리밸런싱)
# ============================================================

def build_index_returns(
    weights: pd.DataFrame,
    prices: pd.DataFrame,
) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    """
    일별 지수 수익률 시계열, 진입 진단, 비중합 검증을 반환합니다.

    포트폴리오 i는 (e_i, e_{i+1}] 구간의 일별 수익률을 담당하며,
    리밸런싱은 e_{i+1} 종가에서 실행됩니다.
    """
    # 상장 후 구간 결측만 ffill (선행 NaN은 유지 → 상장 전 진입 방지)
    px = prices.ffill()

    trading_days = px.index
    rebal_dates = sorted(weights["snapshot_date"].unique())

    def first_td_on_or_after(ts: pd.Timestamp) -> pd.Timestamp | None:
        pos = trading_days.searchsorted(ts, side="left")
        if pos >= len(trading_days):
            return None
        return trading_days[pos]

    entry_dates: list[pd.Timestamp] = []
    for rd in rebal_dates:
        e = first_td_on_or_after(pd.Timestamp(rd))
        entry_dates.append(e)

    daily_returns: list[pd.Series] = []
    diagnostics: list[dict] = []
    weight_checks: list[dict] = []

    for i, rd in enumerate(rebal_dates):
        e_i = entry_dates[i]
        if e_i is None:
            continue

        # 다음 진입일 (없으면 마지막 거래일 다음)
        if i + 1 < len(rebal_dates) and entry_dates[i + 1] is not None:
            e_next = entry_dates[i + 1]
        else:
            e_next = None

        w_i = weights.loc[weights["snapshot_date"] == rd, ["ticker", "weight"]]
        w_i = w_i.set_index("ticker")["weight"].astype(float)

        raw_sum = float(w_i.sum())

        # 진입일 가격이 있는 종목만
        entry_prices = px.loc[e_i].reindex(w_i.index)
        valid = entry_prices.notna() & (entry_prices > 0)
        n_total = int(len(w_i))
        n_valid = int(valid.sum())
        dropped = list(w_i.index[~valid])

        w_valid = w_i[valid]
        p_entry = entry_prices[valid]

        # 잔여 비중 재정규화
        renorm_sum = float(w_valid.sum())
        if renorm_sum <= 0:
            continue
        w_renorm = w_valid / renorm_sum

        # 보유 구간 거래일 (진입일 포함 ~ 다음진입일 포함)
        if e_next is not None:
            mask = (trading_days >= e_i) & (trading_days <= e_next)
        else:
            mask = trading_days >= e_i
        period_days = trading_days[mask]

        # 포트폴리오 가치 경로 (진입일 = 1.0)
        shares = w_renorm / p_entry
        period_px = px.loc[period_days, w_valid.index]
        value = period_px.mul(shares, axis=1).sum(axis=1)
        value = value / value.iloc[0]

        # (e_i, e_{i+1}] 구간의 일별 수익률만 취득 (진입일 자체 제외)
        period_ret = value.pct_change(fill_method=None).iloc[1:]
        daily_returns.append(period_ret)

        weight_checks.append(
            {
                "rebalance_date": pd.Timestamp(rd).date(),
                "entry_date": e_i.date(),
                "n_constituents": n_total,
                "raw_weight_sum": round(raw_sum, 10),
                "n_priced": n_valid,
                "renorm_weight_sum": round(float(w_renorm.sum()), 10),
                "n_dropped_no_price": len(dropped),
            }
        )
        diagnostics.append(
            {
                "rebalance_date": pd.Timestamp(rd).date(),
                "entry_date": e_i.date(),
                "dropped_tickers": ",".join(dropped) if dropped else "",
            }
        )

    if not daily_returns:
        raise RuntimeError("일별 수익률을 하나도 생성하지 못했습니다.")

    index_ret = pd.concat(daily_returns)
    index_ret = index_ret[~index_ret.index.duplicated(keep="first")]
    index_ret = index_ret.sort_index()
    index_ret.name = "index_ret"

    return (
        index_ret,
        pd.DataFrame(diagnostics),
        pd.DataFrame(weight_checks),
    )


def build_levels(
    index_ret: pd.Series,
    qqq_close: pd.Series,
) -> pd.DataFrame:
    """기준일 2009-07-01=100으로 Index와 QQQ 레벨을 정렬 생성합니다."""
    # 분석 공통 구간: 첫 지수 수익일 직전(진입일) ~ 마지막
    invest_start = index_ret.index.min()   # 첫 수익일
    end = index_ret.index.max()

    # 기준일 이후 첫 거래일
    qqq = qqq_close.sort_index()
    all_days = qqq.index[(qqq.index >= BASE_DATE) & (qqq.index <= end)]
    base_td = all_days.min()

    # Index Level: 기준일=100, 첫 진입 전(현금)은 flat, 이후 복리
    idx_level = pd.Series(index=all_days, dtype=float)
    idx_level.loc[all_days < invest_start] = BASE_LEVEL

    run = BASE_LEVEL
    prev_set = False
    for d in all_days:
        if d < invest_start:
            idx_level.loc[d] = BASE_LEVEL
            continue
        if not prev_set:
            # 진입 첫날 = 기준 레벨에서 시작
            idx_level.loc[d] = run
            prev_set = True
        else:
            r = index_ret.get(d, 0.0)
            run = run * (1.0 + (r if pd.notna(r) else 0.0))
            idx_level.loc[d] = run

    # QQQ Level: 기준일=100
    qqq_window = qqq.loc[all_days]
    qqq_level = qqq_window / qqq_window.loc[base_td] * BASE_LEVEL

    out = pd.DataFrame(
        {
            "index_level": idx_level,
            "qqq_level": qqq_level,
        }
    )
    out.index.name = "date"
    return out, base_td, invest_start


# ============================================================
# 성과 지표
# ============================================================

def daily_returns(level: pd.Series) -> pd.Series:
    return level.pct_change(fill_method=None).dropna()


def cagr(level: pd.Series) -> float:
    years = (level.index[-1] - level.index[0]).days / 365.25
    if years <= 0:
        return np.nan
    return (level.iloc[-1] / level.iloc[0]) ** (1 / years) - 1


def annual_vol(rets: pd.Series) -> float:
    return float(rets.std(ddof=1) * np.sqrt(TRADING_DAYS))


def sharpe(rets: pd.Series) -> float:
    ann_ret = rets.mean() * TRADING_DAYS
    av = annual_vol(rets)
    if av == 0:
        return np.nan
    return (ann_ret - RISK_FREE) / av


def max_drawdown(level: pd.Series) -> float:
    peak = level.cummax()
    dd = level / peak - 1.0
    return float(dd.min())


def compute_metrics(
    levels: pd.DataFrame,
    eval_start: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """평가 구간(투자 개시 이후) 기준 성과지표를 계산합니다."""
    ev = levels.loc[levels.index >= eval_start].copy()

    idx_ret = daily_returns(ev["index_level"])
    qqq_ret = daily_returns(ev["qqq_level"])

    common = idx_ret.index.intersection(qqq_ret.index)
    ir = idx_ret.loc[common]
    qr = qqq_ret.loc[common]

    active = ir - qr

    # Beta
    cov = np.cov(ir, qr, ddof=1)
    beta = cov[0, 1] / cov[1, 1] if cov[1, 1] != 0 else np.nan

    # Tracking
    te = float(active.std(ddof=1) * np.sqrt(TRADING_DAYS))
    corr = float(ir.corr(qr))
    # Tracking Difference = 연율화 수익률 차 (CAGR 차)
    td_cagr = cagr(ev["index_level"]) - cagr(ev["qqq_level"])

    def block(level: pd.Series, rets: pd.Series) -> dict:
        return {
            "cumulative_return": level.iloc[-1] / level.iloc[0] - 1,
            "cagr": cagr(level),
            "annualized_volatility": annual_vol(rets),
            "sharpe_ratio": sharpe(rets),
            "max_drawdown": max_drawdown(level),
        }

    summary = pd.DataFrame(
        {
            "AI_Custom_Index": block(ev["index_level"], ir),
            "QQQ": block(ev["qqq_level"], qr),
        }
    )
    summary.index.name = "metric"

    tracking = pd.DataFrame(
        {
            "metric": [
                "correlation",
                "tracking_error_annualized",
                "tracking_difference_cagr",
                "beta",
                "eval_start",
                "eval_end",
                "n_days",
            ],
            "value": [
                round(corr, 6),
                round(te, 6),
                round(td_cagr, 6),
                round(float(beta), 6),
                str(ev.index.min().date()),
                str(ev.index.max().date()),
                int(len(common)),
            ],
        }
    )

    return summary, tracking


def yearly_returns(levels: pd.DataFrame) -> pd.DataFrame:
    """연도별(달력연도) 수익률."""
    yearly = {}
    for col, name in [
        ("index_level", "AI_Custom_Index"),
        ("qqq_level", "QQQ"),
    ]:
        lvl = levels[col].dropna()
        year_end = lvl.resample("YE").last()
        year_start = lvl.resample("YE").first()
        # 각 해 첫날 대비 마지막날
        yr = {}
        for year, grp in lvl.groupby(lvl.index.year):
            yr[year] = grp.iloc[-1] / grp.iloc[0] - 1
        yearly[name] = pd.Series(yr)

    out = pd.DataFrame(yearly)
    out.index.name = "year"
    out["active_return"] = out["AI_Custom_Index"] - out["QQQ"]
    return out


# ============================================================
# 시각화
# ============================================================

def make_figures(
    levels: pd.DataFrame,
    eval_start: pd.Timestamp,
    figures_dir: Path,
) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "figure.dpi": 120,
        "font.size": 10,
        "axes.grid": True,
        "grid.alpha": 0.3,
    })

    figures_dir.mkdir(parents=True, exist_ok=True)

    ev = levels.loc[levels.index >= eval_start]
    idx_ret = daily_returns(ev["index_level"])
    qqq_ret = daily_returns(ev["qqq_level"])
    common = idx_ret.index.intersection(qqq_ret.index)
    ir, qr = idx_ret.loc[common], qqq_ret.loc[common]

    C_IDX, C_QQQ = "#2563eb", "#f59e0b"

    # 1) 누적수익률 (Index Level, 기준 100)
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(levels.index, levels["index_level"], color=C_IDX,
            lw=1.4, label="AI Custom Index")
    ax.plot(levels.index, levels["qqq_level"], color=C_QQQ,
            lw=1.4, label="QQQ (NASDAQ-100)")
    ax.set_yscale("log")
    ax.set_title("Cumulative Performance (Base 2009-07-01 = 100, log scale)")
    ax.set_ylabel("Index Level (log)")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(figures_dir / "cumulative_return.png")
    plt.close(fig)

    # 2) Drawdown 비교
    fig, ax = plt.subplots(figsize=(11, 5))
    for col, color, lbl in [
        ("index_level", C_IDX, "AI Custom Index"),
        ("qqq_level", C_QQQ, "QQQ"),
    ]:
        lvl = levels[col]
        dd = (lvl / lvl.cummax() - 1.0) * 100
        ax.plot(lvl.index, dd, color=color, lw=1.1, label=lbl)
        ax.fill_between(lvl.index, dd, 0, color=color, alpha=0.12)
    ax.set_title("Drawdown Comparison")
    ax.set_ylabel("Drawdown (%)")
    ax.legend(loc="lower left")
    fig.tight_layout()
    fig.savefig(figures_dir / "drawdown.png")
    plt.close(fig)

    # 3) Tracking Difference (누적 상대수익, Index/QQQ)
    rel = (ev["index_level"] / ev["index_level"].iloc[0]) / \
          (ev["qqq_level"] / ev["qqq_level"].iloc[0])
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(rel.index, (rel - 1.0) * 100, color="#10b981", lw=1.3)
    ax.axhline(0, color="black", lw=0.8, ls="--")
    ax.set_title("Cumulative Tracking Difference (Index relative to QQQ)")
    ax.set_ylabel("Cumulative Outperformance vs QQQ (%)")
    fig.tight_layout()
    fig.savefig(figures_dir / "tracking_difference.png")
    plt.close(fig)

    # 4) Rolling Tracking Error (63일 ~ 분기, 연율화)
    window = 63
    active = (ir - qr)
    roll_te = active.rolling(window).std(ddof=1) * np.sqrt(TRADING_DAYS) * 100
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(roll_te.index, roll_te, color="#ef4444", lw=1.1)
    ax.set_title(f"Rolling Tracking Error ({window}-day, annualized)")
    ax.set_ylabel("Tracking Error (%)")
    fig.tight_layout()
    fig.savefig(figures_dir / "rolling_tracking_error.png")
    plt.close(fig)


# ============================================================
# 실행
# ============================================================

def run(
    weights_path: Path,
    prices_path: Path,
    qqq_path: Path,
    output_dir: Path,
    figures_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    weights = load_weights(weights_path)
    prices = load_prices(prices_path)
    qqq = load_qqq(qqq_path)

    index_ret, diagnostics, weight_checks = build_index_returns(
        weights, prices
    )

    levels, base_td, invest_start = build_levels(index_ret, qqq)

    summary, tracking = compute_metrics(levels, eval_start=invest_start)
    yearly = yearly_returns(levels)

    # 저장
    levels[["index_level"]].to_csv(
        output_dir / "index_level.csv", encoding="utf-8-sig"
    )
    levels[["qqq_level"]].to_csv(
        output_dir / "benchmark_qqq.csv", encoding="utf-8-sig"
    )
    summary.round(6).to_csv(
        output_dir / "performance_summary.csv", encoding="utf-8-sig"
    )
    yearly.round(6).to_csv(
        output_dir / "yearly_returns.csv", encoding="utf-8-sig"
    )
    tracking.to_csv(
        output_dir / "tracking_metrics.csv", index=False,
        encoding="utf-8-sig"
    )
    weight_checks.to_csv(
        output_dir / "rebalance_weight_check.csv", index=False,
        encoding="utf-8-sig"
    )
    diagnostics.to_csv(
        output_dir / "backtest_diagnostics.csv", index=False,
        encoding="utf-8-sig"
    )

    make_figures(levels, invest_start, figures_dir)

    # 로그 요약
    logging.info("=" * 64)
    logging.info("백테스트 완료")
    logging.info("기준일: %s = %.0f | 투자개시(첫 리밸런싱): %s",
                 base_td.date(), BASE_LEVEL, invest_start.date())
    logging.info("평가구간: %s ~ %s",
                 levels.loc[levels.index >= invest_start].index.min().date(),
                 levels.index.max().date())
    logging.info("-" * 64)
    logging.info("[성과 요약]")
    for metric in summary.index:
        logging.info("  %-24s Index=%+.4f  QQQ=%+.4f",
                     metric, summary.loc[metric, "AI_Custom_Index"],
                     summary.loc[metric, "QQQ"])
    logging.info("-" * 64)
    logging.info("[추종 지표]")
    for _, row in tracking.iterrows():
        logging.info("  %-28s %s", row["metric"], row["value"])
    logging.info("-" * 64)
    wsum_min = weight_checks["renorm_weight_sum"].min()
    wsum_max = weight_checks["renorm_weight_sum"].max()
    raw_min = weight_checks["raw_weight_sum"].min()
    raw_max = weight_checks["raw_weight_sum"].max()
    total_dropped = int(weight_checks["n_dropped_no_price"].sum())
    logging.info("리밸런싱 비중합(원본): %.6f ~ %.6f", raw_min, raw_max)
    logging.info("리밸런싱 비중합(재정규화): %.6f ~ %.6f", wsum_min, wsum_max)
    logging.info("진입일 무가격 제외 종목 총합: %s건", total_dropped)
    logging.info("=" * 64)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="지수 백테스트 및 QQQ 추종 평가")
    p.add_argument("--weights-file", type=Path, default=DEFAULT_WEIGHTS)
    p.add_argument("--prices-file", type=Path, default=DEFAULT_PRICES)
    p.add_argument("--qqq-file", type=Path, default=DEFAULT_QQQ)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--figures-dir", type=Path,
                   default=PROJECT_ROOT / "figures")
    return p.parse_args()


def main() -> None:
    configure_logging()
    args = parse_args()
    run(
        weights_path=args.weights_file,
        prices_path=args.prices_file,
        qqq_path=args.qqq_file,
        output_dir=args.output_dir,
        figures_dir=args.figures_dir,
    )


if __name__ == "__main__":
    main()
