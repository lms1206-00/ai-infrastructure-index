#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
06_corporate_actions.py  (Item 3: 인수·합병 및 기업행위 처리)

100개 유니버스에 대해 기업행위(M&A/상장폐지/분할/비상장전환/티커·회사명 변경/
파산·회생)를 점검하고 아래 필드를 부착한다.
  listing_status, corporate_action_type, announcement_date, effective_date,
  successor_ticker, action_source, action_status

근거
----
1) 데이터 기반: data/prices 패널의 '최초 거래일'(first_valid) 로 IPO/분할 신규상장/
   티커전환 상장 시점을 도출한다(suspension_audit.csv).
2) 공식 근거: 주요 기업행위(티커·회사명 변경, 분할)는 회사/거래소 공식 공시로 확인.
3) PIT 검증: index_weights_quarterly 편입 시점이 기업행위 유효일과 정합한지 점검.
   - 동일 법인 티커변경(ONTO/COHR)은 CIK 기준으로 편입이력 승계됨(규칙 준수).
   - 미래 분할(GEV 2024/CEG 2022 등 신설법인)은 과거 리밸런싱에 편입되지 않음(PIT 준수).

한계
----
* 공식 corporate-action 피드(예: 거래소/데이터벤더)가 없어, 개별 100종목 전수의
  '미래 예정 이벤트(pending)'는 자동 확보 불가. 본 유니버스는 전 종목 현재 상장 상태
  (생존편향)이며 확인된 상장폐지/비상장전환/파산 진행 종목은 없다.
* 따라서 '자동 편출' 대상은 없으며, 확인된 항목만 기록한다.

출력: data/integrity/corporate_actions.csv
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "data" / "integrity"
UNIVERSE = ROOT / "data" / "classification" / "final_universe_100.csv"

# 공식 근거로 확인된 주요 기업행위. (type, announcement, effective, successor, source, detail)
CURATED = {
    "ONTO": ("TICKER_NAME_CHANGE", "2019-06-24", "2019-10-25", "ONTO",
             "Onto Innovation 8-K/보도(Nanometrics·Rudolph 합병 완료)",
             "NANO(+RTEC 역합병)->ONTO, Nasdaq->NYSE. 존속법인 CIK 0000704532로 이력 승계."),
    "COHR": ("TICKER_NAME_CHANGE", "2021-03-25", "2022-07-01", "COHR",
             "Coherent/II-VI 보도(II-VI가 Coherent Inc 인수 후 사명변경)",
             "II-VI(IIVI)->Coherent Corp(COHR). 존속법인 CIK 0000820318로 이력 승계."),
    "GEV":  ("SPINOFF_NEW_LISTING", "2024-03-27", "2024-04-02", "GEV",
             "GE Vernova 8-K/보도(GE 분할)",
             "GE에서 분할 신규상장(NYSE). 신설법인 -> 자동편입 대상 아님(재심사)."),
    "CEG":  ("SPINOFF_NEW_LISTING", "2022-01-07", "2022-02-01", "CEG",
             "Exelon 보도(Constellation 분할 완료)",
             "Exelon에서 분할 신규상장(Nasdaq). 신설법인 -> 재심사."),
    "CARR": ("SPINOFF_NEW_LISTING", "2019-11-26", "2020-04-03", "CARR",
             "United Technologies/Carrier 분할 보도",
             "UTC에서 분할 신규상장(2020)."),
    "KEYS": ("SPINOFF_NEW_LISTING", "2013-09-19", "2014-11-01", "KEYS",
             "Agilent/Keysight 분할 보도",
             "Agilent에서 분할 신규상장(2014)."),
    "LITE": ("SPINOFF_NEW_LISTING", "2015-02-09", "2015-08-01", "LITE",
             "JDS Uniphase(Viavi) 분할 보도",
             "JDSU에서 Lumentum 분할 신규상장(2015)."),
    "NVT":  ("SPINOFF_NEW_LISTING", "2017-05-09", "2018-04-30", "NVT",
             "Pentair/nVent 분할 보도", "Pentair에서 분할 신규상장(2018)."),
    "HPE":  ("SPINOFF_NEW_LISTING", "2015-06-02", "2015-11-01", "HPE",
             "Hewlett-Packard 분할 보도", "HP에서 HPE 분할 신규상장(2015)."),
    "VST":  ("BANKRUPTCY_ORIGIN_NEW_LISTING", "2016-09-01", "2016-10-03", "VST",
             "Energy Future Holdings(TXU) Ch.11 회생/Vistra 상장 보도",
             "EFH/TXU 회생절차에서 Vistra Energy로 신규상장(2016)."),
    "ARM":  ("REIPO", "2023-08-21", "2023-09-14", "ARM",
             "Arm Holdings IPO(2023, SoftBank 산하)",
             "2016 SoftBank 비상장화 후 2023 재상장(Nasdaq)."),
    "IBM":  ("ACQUISITION_SPINOFF_SURVIVOR", "2020-10-08", "2021-11-03", "IBM",
             "IBM/Kyndryl 분할 보도", "존속법인. Kyndryl(관리서비스) 분할, IBM 존속."),
    "AMT":  ("ACQUISITION_SURVIVOR", "2021-11-15", "2021-12-28", "AMT",
             "American Tower/CoreSite 인수 보도", "존속법인. CoreSite(데이터센터) 인수."),
}
# IPO 로만 분류(패널 최초거래일을 유효일 근거로 사용)
IPO_TICKERS = {"FN", "NXPI", "VNET", "UI", "MTSI", "AAOI", "ANET", "ATKR",
               "VRT", "DDOG", "GFS", "CRDO"}


def main():
    uni = pd.read_csv(UNIVERSE, encoding="utf-8-sig")
    uni["cik"] = uni["cik"].astype(str).str.replace(".0", "", regex=False).str.zfill(10)
    susp = pd.read_csv(INTEG / "suspension_audit.csv", encoding="utf-8-sig")
    first_valid = dict(zip(susp["ticker"], susp["first_valid"]))
    last_valid = dict(zip(susp["ticker"], susp["last_valid"]))
    w = pd.read_csv(ROOT / "data" / "index" / "index_weights_quarterly.csv")
    w["snapshot_date"] = pd.to_datetime(w["snapshot_date"])

    rows = []
    for _, r in uni.iterrows():
        tkr = r["ticker"]
        fv = first_valid.get(tkr, "")
        lv = last_valid.get(tkr, "")
        # PIT 정합성: 편입 스냅샷 중 유효일 이전 개수
        if tkr in CURATED:
            ctype, ann, eff, succ, src, detail = CURATED[tkr]
        elif tkr in IPO_TICKERS:
            ctype, ann, eff, succ, src, detail = (
                "IPO", "", str(fv), tkr,
                "가격패널 최초거래일(data/prices)", f"IPO 상장 추정(최초거래일 {fv}).")
        else:
            ctype, ann, eff, succ, src, detail = (
                "NONE", "", "", tkr, "", "확인된 기업행위 없음(현재 상장 유지).")

        sub = w[w.ticker.str.upper() == tkr]
        pre = 0
        if len(sub) and eff:
            pre = int((sub["snapshot_date"] < pd.Timestamp(eff)).sum())
        pit_note = ""
        if ctype == "TICKER_NAME_CHANGE" and pre > 0:
            pit_note = (f"편입스냅샷 {len(sub)}개 중 {pre}개가 티커변경 이전 시점 -> "
                        f"동일 CIK 재무로 이력승계(백테스트는 신티커 가격 없으면 제외·재정규화).")
        elif ctype.startswith("SPINOFF") and len(sub) == 0:
            pit_note = "분할 신설법인 -> 지수 미편입(PIT 준수: 과거 리밸런싱 미반영)."
        elif eff and pre == 0 and len(sub):
            pit_note = "편입이 유효일 이후에만 발생(PIT 정합)."

        rows.append({
            "ticker": tkr, "cik": r["cik"], "company_name": r["entity_name"],
            "listing_status": "LISTED",  # 유니버스 전 종목 현재 상장(생존편향)
            "corporate_action_type": ctype,
            "announcement_date": ann, "effective_date": eff,
            "successor_ticker": succ,
            "action_source": src, "action_status": "COMPLETED" if ctype != "NONE" else "NONE",
            "first_trading_in_panel": fv, "last_trading_in_panel": lv,
            "n_index_snapshots": int(len(sub)),
            "n_pre_event_snapshots": pre,
            "pit_note": pit_note, "detail": detail,
        })

    out = pd.DataFrame(rows)
    out.to_csv(INTEG / "corporate_actions.csv", index=False, encoding="utf-8-sig")
    print("=" * 64)
    print("Item 3  기업행위·상장상태 점검 요약")
    print("=" * 64)
    print("listing_status:", out["listing_status"].value_counts().to_dict())
    print("corporate_action_type:", out["corporate_action_type"].value_counts().to_dict())
    print(f"\n[확인된 기업행위 {int((out.corporate_action_type!='NONE').sum())}건]")
    print(out[out.corporate_action_type != "NONE"][
        ["ticker", "corporate_action_type", "effective_date", "n_index_snapshots",
         "n_pre_event_snapshots"]].to_string(index=False))
    print(f"\n출력: {INTEG/'corporate_actions.csv'}")


if __name__ == "__main__":
    main()
