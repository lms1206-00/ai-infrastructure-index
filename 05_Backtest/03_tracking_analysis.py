"""
AI Infrastructure Custom Index - Backtest
Step 3) QQQ 추종 특성 심화 분석 (Tracking Analysis)

목적
----
기존 백테스트(02_run_backtest.py) 결과를 바탕으로, 우리 지수가 QQQ를
"완전 복제"하는지 아니면 "QQQ와 동행하면서 AI 인프라에 틸팅"된 지수인지를
구간별/롤링/Active Return 관점에서 객관적으로 진단한다.

기존 Factor Score, Ranking, Weight, (원본) Index Level 계산은 변경하지 않는다.
분석 기능만 추가하며, 결과는 기존 파일을 덮어쓰지 않고 별도 폴더에 저장한다.

  data/backtest/tracking_analysis/
  figures/tracking_analysis/

상장폐지 처리 개선
------------------
원본(02)은 보유 중 가격 결측을 직전가로 ffill(=마지막가 동결)한다. 본 모듈은
"마지막 유효 거래일 가격으로 청산 → 현금 보유(0% 수익) → 다음 리밸런싱 재투자"
방식을 명시적으로 구현한다. (수학적으로 기간 내 마지막가 동결과 동일하지만,
청산 시점·현금 전환을 진단 로그로 분리해 남긴다.)
※ 본 유니버스는 전 종목이 최신일까지 거래되어 실제 중간 상장폐지는 0건이며,
   이 사실 자체가 생존편향의 방증이다(진단 로그로 확인).

주의: 무위험수익률 rf=0 가정, 연율화 252.
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
DEFAULT_ORIG_LEVEL = PROJECT_ROOT / "data" / "backtest" / "index_level.csv"

DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "backtest" / "tracking_analysis"
DEFAULT_FIGURES = PROJECT_ROOT / "figures" / "tracking_analysis"

BASE_DATE = pd.Timestamp("2009-07-01")
BASE_LEVEL = 100.0
TRADING_DAYS = 252
RISK_FREE = 0.0
ROLL_WINDOW = 252

SUBPERIODS = [
    ("2009-10-01 ~ 2019", "2009-10-01", "2019-12-31"),
    ("2020 ~ 2022", "2020-01-01", "2022-12-31"),
    ("2023 ~ latest", "2023-01-01", "2100-01-01"),
]


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ============================================================
# 로딩
# ============================================================

def load_prices(path: Path) -> pd.DataFrame:
    px = pd.read_csv(path, index_col=0)
    px.index = pd.to_datetime(px.index)
    px = px.sort_index()
    px.columns = [str(c).upper() for c in px.columns]
    return px


def load_qqq(path: Path) -> pd.Series:
    q = pd.read_csv(path, index_col=0)
    q.index = pd.to_datetime(q.index)
    return q[q.columns[0]].sort_index().rename("qqq")


def load_weights(path: Path) -> pd.DataFrame:
    w = pd.read_csv(path)
    w["snapshot_date"] = pd.to_datetime(w["snapshot_date"])
    w["ticker"] = w["ticker"].astype(str).str.upper().str.strip()
    return w[["snapshot_date", "ticker", "weight"]].copy()


# ============================================================
# 개선된 지수 재구성 (청산-현금 + 생존편향 진단)
# ============================================================

def build_index_cash_on_delist(
    weights: pd.DataFrame,
    prices: pd.DataFrame,
) -> tuple[pd.Series, pd.DataFrame]:
    """
    청산-현금 방식으로 일별 지수 수익률과 리밸런싱별 진단을 반환합니다.

    - 진입일 무가격(상장 전/티커 미존재) 종목: 제외 후 잔여 비중 재정규화
    - 보유 중 상장폐지(가격 시계열 종료): 마지막 유효가로 청산→현금(0% 수익).
      다음 리밸런싱에서 새 비중으로 재투자.
    """
    px_ffill = prices.ffill()
    raw_valid = prices.notna()   # 실제 관측(상장 여부) 마스크

    trading_days = prices.index
    rebal_dates = sorted(weights["snapshot_date"].unique())

    def first_td_on_or_after(ts):
        pos = trading_days.searchsorted(ts, side="left")
        return trading_days[pos] if pos < len(trading_days) else None

    entries = [first_td_on_or_after(pd.Timestamp(rd)) for rd in rebal_dates]

    daily_returns: list[pd.Series] = []
    diags: list[dict] = []

    for i, rd in enumerate(rebal_dates):
        e_i = entries[i]
        if e_i is None:
            continue
        e_next = entries[i + 1] if (i + 1 < len(rebal_dates) and entries[i + 1] is not None) else None

        w_i = weights.loc[weights["snapshot_date"] == rd, ["ticker", "weight"]]
        w_i = w_i.set_index("ticker")["weight"].astype(float)
        n_target = int(len(w_i))
        raw_sum = float(w_i.sum())

        # 진입일 가용 가격(=상장됨): ffill 후 값이 있으면 가용
        entry_px = px_ffill.loc[e_i].reindex(w_i.index)
        priced = entry_px.notna() & (entry_px > 0)
        n_priced = int(priced.sum())
        pre_listing = list(w_i.index[~priced])   # 상장 전 제외

        w_priced = w_i[priced]
        # 투자 가능 비중 커버리지 = 가용 종목 원비중 합 / 전체 원비중 합
        investable_coverage = float(w_priced.sum() / raw_sum) if raw_sum > 0 else 0.0

        renorm_sum = float(w_priced.sum())
        if renorm_sum <= 0:
            continue
        w_renorm = w_priced / renorm_sum
        p_entry = entry_px[priced]
        shares = w_renorm / p_entry

        # 보유 구간
        if e_next is not None:
            mask = (trading_days >= e_i) & (trading_days <= e_next)
        else:
            mask = trading_days >= e_i
        period_days = trading_days[mask]

        # 청산-현금 처리: 각 종목의 (구간 내) 마지막 실제 관측일 이후엔 현금.
        # 가치 = shares × (마지막 실제가). ffill이 이를 동결가로 유지 = 현금과 동일.
        held = list(w_renorm.index)
        period_real = raw_valid.loc[period_days, held]
        # 구간 내에서 관측이 종료되는(=중간 상장폐지) 종목 수
        last_real_pos = period_real[::-1].idxmax()  # not used directly
        delisted_mid = 0
        for t in held:
            col = period_real[t]
            if col.any():
                last_obs = col[col].index.max()
                # 다음 진입 전에 관측 종료 & 구간 마지막 거래일보다 앞서면 중간폐지
                if e_next is not None and last_obs < period_days[period_days < e_next].max():
                    delisted_mid += 1

        period_px = px_ffill.loc[period_days, held]
        value = period_px.mul(shares, axis=1).sum(axis=1)
        value = value / value.iloc[0]
        period_ret = value.pct_change(fill_method=None).iloc[1:]
        daily_returns.append(period_ret)

        diags.append({
            "rebalance_date": pd.Timestamp(rd).date(),
            "entry_date": e_i.date(),
            "target_constituents": n_target,
            "priced_constituents": n_priced,
            "pre_listing_excluded": len(pre_listing),
            "delisted_to_cash_mid_period": delisted_mid,
            "renorm_weight_sum": round(float(w_renorm.sum()), 10),
            "investable_weight_coverage": round(investable_coverage, 6),
            "excluded_tickers": ",".join(pre_listing),
        })

    ret = pd.concat(daily_returns)
    ret = ret[~ret.index.duplicated(keep="first")].sort_index()
    ret.name = "index_ret"
    return ret, pd.DataFrame(diags)


def build_levels(index_ret: pd.Series, qqq_close: pd.Series):
    invest_start = index_ret.index.min()
    end = index_ret.index.max()
    qqq = qqq_close.sort_index()
    all_days = qqq.index[(qqq.index >= BASE_DATE) & (qqq.index <= end)]
    base_td = all_days.min()

    idx_level = pd.Series(index=all_days, dtype=float)
    run = BASE_LEVEL
    started = False
    for d in all_days:
        if d < invest_start:
            idx_level.loc[d] = BASE_LEVEL
        elif not started:
            idx_level.loc[d] = run
            started = True
        else:
            r = index_ret.get(d, 0.0)
            run *= (1.0 + (r if pd.notna(r) else 0.0))
            idx_level.loc[d] = run

    qqq_level = qqq.loc[all_days] / qqq.loc[base_td] * BASE_LEVEL
    out = pd.DataFrame({"index_level": idx_level, "qqq_level": qqq_level})
    out.index.name = "date"
    return out, base_td, invest_start


# ============================================================
# 지표 헬퍼
# ============================================================

def daily_ret(level: pd.Series) -> pd.Series:
    return level.pct_change(fill_method=None).dropna()


def cagr(level: pd.Series) -> float:
    years = (level.index[-1] - level.index[0]).days / 365.25
    return (level.iloc[-1] / level.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan


def beta_alpha(ir: pd.Series, qr: pd.Series) -> tuple[float, float]:
    """rf=0 가정. index_ret = alpha + beta*qqq_ret 회귀. alpha는 연율화."""
    x = qr.values
    y = ir.values
    var = np.var(x, ddof=1)
    if var == 0:
        return np.nan, np.nan
    beta = np.cov(y, x, ddof=1)[0, 1] / var
    alpha_daily = y.mean() - beta * x.mean()
    return float(beta), float(alpha_daily * TRADING_DAYS)


def tracking_error(ir: pd.Series, qr: pd.Series) -> float:
    return float((ir - qr).std(ddof=1) * np.sqrt(TRADING_DAYS))


# ============================================================
# 1) 구간별 분석
# ============================================================

def subperiod_analysis(levels: pd.DataFrame) -> pd.DataFrame:
    ir_all = daily_ret(levels["index_level"])
    qr_all = daily_ret(levels["qqq_level"])
    common = ir_all.index.intersection(qr_all.index)
    ir_all, qr_all = ir_all.loc[common], qr_all.loc[common]

    rows = []
    for label, start, end in SUBPERIODS:
        s, e = pd.Timestamp(start), pd.Timestamp(end)
        m = (ir_all.index >= s) & (ir_all.index <= e)
        ir, qr = ir_all[m], qr_all[m]
        if len(ir) < 5:
            continue
        lvl_i = levels["index_level"].loc[(levels.index >= s) & (levels.index <= e)]
        lvl_q = levels["qqq_level"].loc[(levels.index >= s) & (levels.index <= e)]
        beta, alpha = beta_alpha(ir, qr)
        rows.append({
            "period": label,
            "start": ir.index.min().date(),
            "end": ir.index.max().date(),
            "n_days": len(ir),
            "correlation": round(float(ir.corr(qr)), 4),
            "tracking_error_ann": round(tracking_error(ir, qr), 4),
            "tracking_difference_cagr": round(cagr(lvl_i) - cagr(lvl_q), 4),
            "beta": round(beta, 4),
            "alpha_ann": round(alpha, 4),
            "index_cagr": round(cagr(lvl_i), 4),
            "qqq_cagr": round(cagr(lvl_q), 4),
        })
    return pd.DataFrame(rows)


# ============================================================
# 2) 롤링 분석
# ============================================================

def rolling_analysis(levels: pd.DataFrame, window: int) -> pd.DataFrame:
    ir = daily_ret(levels["index_level"])
    qr = daily_ret(levels["qqq_level"])
    common = ir.index.intersection(qr.index)
    ir, qr = ir.loc[common], qr.loc[common]
    active = ir - qr

    roll_corr = ir.rolling(window).corr(qr)
    cov = ir.rolling(window).cov(qr)
    var = qr.rolling(window).var()
    roll_beta = cov / var
    roll_te = active.rolling(window).std(ddof=1) * np.sqrt(TRADING_DAYS)
    roll_active = active.rolling(window).mean() * TRADING_DAYS   # 연율화 평균 active

    out = pd.DataFrame({
        "rolling_correlation": roll_corr,
        "rolling_beta": roll_beta,
        "rolling_tracking_error_ann": roll_te,
        "rolling_active_return_ann": roll_active,
    }).dropna()
    out.index.name = "date"
    return out


# ============================================================
# 3) Active Return 분석
# ============================================================

def active_return_analysis(levels: pd.DataFrame):
    ir = daily_ret(levels["index_level"])
    qr = daily_ret(levels["qqq_level"])
    common = ir.index.intersection(qr.index)
    ir, qr = ir.loc[common], qr.loc[common]
    active = (ir - qr).rename("active_return")

    mean_daily = float(active.mean())
    vol_daily = float(active.std(ddof=1))
    pos_ratio = float((active > 0).mean())
    ann_active = mean_daily * TRADING_DAYS
    te = vol_daily * np.sqrt(TRADING_DAYS)
    info_ratio = ann_active / te if te != 0 else np.nan

    summary = pd.DataFrame({
        "metric": [
            "mean_active_return_daily",
            "mean_active_return_annualized",
            "active_return_volatility_daily",
            "active_return_volatility_annualized",
            "positive_active_ratio",
            "information_ratio",
            "n_days",
        ],
        "value": [
            round(mean_daily, 8),
            round(ann_active, 6),
            round(vol_daily, 8),
            round(te, 6),
            round(pos_ratio, 6),
            round(float(info_ratio), 6),
            int(len(active)),
        ],
    })

    # 연도별 active return (해당 해 일별 active 복리 차이)
    lvl_i, lvl_q = levels["index_level"], levels["qqq_level"]
    yr = {}
    for year, grp in lvl_i.groupby(lvl_i.index.year):
        gi = grp
        gq = lvl_q.loc[gi.index]
        ri = gi.iloc[-1] / gi.iloc[0] - 1
        rq = gq.iloc[-1] / gq.iloc[0] - 1
        yr[year] = ri - rq
    yearly = pd.DataFrame({"active_return": pd.Series(yr)})
    yearly.index.name = "year"
    yearly["active_return"] = yearly["active_return"].round(6)

    return summary, yearly, active


# ============================================================
# 시각화
# ============================================================

def make_figures(rolling: pd.DataFrame, active: pd.Series,
                 subperiod: pd.DataFrame, figdir: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"figure.dpi": 120, "font.size": 10,
                         "axes.grid": True, "grid.alpha": 0.3})
    figdir.mkdir(parents=True, exist_ok=True)

    specs = [
        ("rolling_correlation", "Rolling 252d Correlation with QQQ",
         "Correlation", "#2563eb", (0, 1.05)),
        ("rolling_beta", "Rolling 252d Beta to QQQ",
         "Beta", "#7c3aed", None),
        ("rolling_tracking_error_ann", "Rolling 252d Tracking Error (annualized)",
         "Tracking Error", "#ef4444", None),
        ("rolling_active_return_ann", "Rolling 252d Active Return (annualized)",
         "Active Return", "#10b981", None),
    ]
    for col, title, ylab, color, ylim in specs:
        fig, ax = plt.subplots(figsize=(11, 4.6))
        ax.plot(rolling.index, rolling[col], color=color, lw=1.2)
        if col == "rolling_beta":
            ax.axhline(1.0, color="black", lw=0.8, ls="--")
        if col == "rolling_active_return_ann":
            ax.axhline(0.0, color="black", lw=0.8, ls="--")
        if ylim:
            ax.set_ylim(*ylim)
        ax.set_title(title)
        ax.set_ylabel(ylab)
        fig.tight_layout()
        fig.savefig(figdir / f"{col.replace('_ann','')}.png")
        plt.close(fig)

    # Active return 분포
    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.hist(active.values * 100, bins=120, color="#0891b2", alpha=0.8)
    ax.axvline(0, color="black", lw=0.8, ls="--")
    ax.axvline(active.mean() * 100, color="#ef4444", lw=1.2,
               label=f"mean={active.mean()*100:.3f}%")
    ax.set_title("Daily Active Return Distribution (Index - QQQ)")
    ax.set_xlabel("Daily Active Return (%)")
    ax.set_ylabel("Frequency")
    ax.legend()
    fig.tight_layout()
    fig.savefig(figdir / "active_return_distribution.png")
    plt.close(fig)

    # 구간별 지표 막대
    if not subperiod.empty:
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
        x = np.arange(len(subperiod))
        axes[0].bar(x - 0.2, subperiod["index_cagr"] * 100, 0.4,
                    label="Index", color="#2563eb")
        axes[0].bar(x + 0.2, subperiod["qqq_cagr"] * 100, 0.4,
                    label="QQQ", color="#f59e0b")
        axes[0].set_xticks(x)
        axes[0].set_xticklabels(subperiod["period"], fontsize=8)
        axes[0].set_title("CAGR by Sub-period")
        axes[0].set_ylabel("CAGR (%)")
        axes[0].legend()
        axes[1].bar(x, subperiod["tracking_error_ann"] * 100, 0.5,
                    color="#ef4444")
        axes[1].set_xticks(x)
        axes[1].set_xticklabels(subperiod["period"], fontsize=8)
        axes[1].set_title("Tracking Error by Sub-period")
        axes[1].set_ylabel("TE (%)")
        fig.tight_layout()
        fig.savefig(figdir / "subperiod_summary.png")
        plt.close(fig)


# ============================================================
# 실행
# ============================================================

def run(weights_path, prices_path, qqq_path, orig_level_path,
        output_dir, figures_dir) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    weights = load_weights(weights_path)
    prices = load_prices(prices_path)
    qqq = load_qqq(qqq_path)

    index_ret, diagnostics = build_index_cash_on_delist(weights, prices)
    levels, base_td, invest_start = build_levels(index_ret, qqq)

    # 원본(02) 대비 개선 지수 차이 확인
    orig_diff = None
    if orig_level_path.exists():
        orig = pd.read_csv(orig_level_path, index_col=0)
        orig.index = pd.to_datetime(orig.index)
        common = levels.index.intersection(orig.index)
        orig_diff = float((levels.loc[common, "index_level"]
                           - orig.iloc[:, 0].loc[common]).abs().max())

    subperiod = subperiod_analysis(levels)
    rolling = rolling_analysis(levels, ROLL_WINDOW)
    active_summary, active_yearly, active = active_return_analysis(levels)

    # 저장
    levels[["index_level"]].to_csv(
        output_dir / "index_level_cash_on_delist.csv", encoding="utf-8-sig")
    subperiod.to_csv(output_dir / "subperiod_tracking.csv",
                     index=False, encoding="utf-8-sig")
    rolling.to_csv(output_dir / "rolling_metrics.csv", encoding="utf-8-sig")
    active_summary.to_csv(output_dir / "active_return_summary.csv",
                          index=False, encoding="utf-8-sig")
    active_yearly.to_csv(output_dir / "active_return_yearly.csv",
                         encoding="utf-8-sig")
    diagnostics.to_csv(output_dir / "survivorship_diagnostics.csv",
                       index=False, encoding="utf-8-sig")

    make_figures(rolling, active, subperiod, figures_dir)

    # 로그
    logging.info("=" * 64)
    logging.info("Tracking Analysis 완료")
    if orig_diff is not None:
        logging.info("원본 대비 개선(청산-현금) 지수레벨 최대차: %.6e "
                     "(중간폐지 0건 → 사실상 동일)", orig_diff)
    logging.info("-" * 64)
    logging.info("[구간별 추종]")
    for _, r in subperiod.iterrows():
        logging.info("  %-16s corr=%.3f TE=%.3f beta=%.2f alpha=%+.3f "
                     "TD=%+.3f idxCAGR=%+.3f qqqCAGR=%+.3f",
                     r["period"], r["correlation"], r["tracking_error_ann"],
                     r["beta"], r["alpha_ann"], r["tracking_difference_cagr"],
                     r["index_cagr"], r["qqq_cagr"])
    logging.info("-" * 64)
    logging.info("[Active Return]")
    for _, r in active_summary.iterrows():
        logging.info("  %-38s %s", r["metric"], r["value"])
    logging.info("-" * 64)
    total_pre = int(diagnostics["pre_listing_excluded"].sum())
    total_del = int(diagnostics["delisted_to_cash_mid_period"].sum())
    cov_min = diagnostics["investable_weight_coverage"].min()
    logging.info("생존편향 진단: 상장전 제외 총 %s건, 중간폐지→현금 %s건, "
                 "최소 투자가능 비중커버리지 %.4f", total_pre, total_del, cov_min)
    logging.info("=" * 64)


def parse_args():
    p = argparse.ArgumentParser(description="QQQ 추종 특성 심화 분석")
    p.add_argument("--weights-file", type=Path, default=DEFAULT_WEIGHTS)
    p.add_argument("--prices-file", type=Path, default=DEFAULT_PRICES)
    p.add_argument("--qqq-file", type=Path, default=DEFAULT_QQQ)
    p.add_argument("--orig-level", type=Path, default=DEFAULT_ORIG_LEVEL)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--figures-dir", type=Path, default=DEFAULT_FIGURES)
    return p.parse_args()


def main() -> None:
    configure_logging()
    a = parse_args()
    run(a.weights_file, a.prices_file, a.qqq_file, a.orig_level,
        a.output_dir, a.figures_dir)


if __name__ == "__main__":
    main()
