# AI Infrastructure Custom Index

> **SEC 재무데이터를 기반으로 AI 인프라 기업을 선별하고, 팩터 기반 방법론을 적용하여 구축한 커스텀 인덱스 프로젝트입니다.**

AI 산업의 성장을 뒷받침하는 핵심 인프라 기업을 정의하고,  
SEC 공시 데이터와 재무 팩터를 활용하여 **10개 테마 · 100개 종목으로 구성된 AI Infrastructure Custom Index**를 구축했습니다.

---

## 📌 프로젝트 소개

기존 AI 관련 ETF를 분석하면서 반도체·데이터센터와 같은 인프라 기업뿐만 아니라  
AI 소프트웨어 및 서비스 기업까지 폭넓게 포함되어 있다는 점에 주목했습니다.

이에 본 프로젝트에서는 단순히 AI를 활용하는 기업이 아닌,  
**AI가 실제로 학습되고 서비스될 수 있도록 기반을 제공하는 기업**에 집중했습니다.

AI Infrastructure를 **반도체, 서버, 네트워크, 전력, 냉각, 광통신, 데이터센터, 클라우드, 스토리지, 산업자동화**의 10개 테마로 정의하고, SEC 공시 기반 재무데이터를 활용하여 최종 **100개 기업으로 구성된 Custom Index**를 구축했습니다.

단순한 종목 선정에 그치지 않고,

**데이터 확보 → 전처리 → 유니버스 선정 → 재무 팩터 산출 → 편입 기준 → 가중치 산정 → 리밸런싱 → 백테스트 → 데이터 검증**

으로 이어지는 인덱스 구축 프로세스를 구현했습니다.

---

## 🎯 프로젝트 목표

- AI Infrastructure 산업의 범위 및 10개 테마 정의
- SEC 공시 데이터를 활용한 기업 재무데이터 구축
- 사업 관련성 및 데이터 품질을 고려한 투자 유니버스 선정
- 재무 팩터 기반 종목 편입 기준 설계
- Score 기반 가중치 및 리밸런싱 방법론 구축
- Historical Backtest를 통한 인덱스 성과 검증
- Point-in-Time 기반 데이터 검증 및 Look-ahead Bias 방지
- 구축된 인덱스를 관리하기 위한 Monitoring System 구현

---

## 🏗️ AI Infrastructure 정의

본 프로젝트에서는 AI Infrastructure를  
**AI 모델의 학습·추론·서비스에 필요한 물리적·디지털 기반을 제공하는 산업**으로 정의했습니다.

| Theme | 주요 영역 |
|---|---|
| Semiconductor | GPU, CPU, AI Accelerator 및 반도체 |
| Server | AI 연산 서버 및 컴퓨팅 시스템 |
| Networking | 데이터센터 네트워크 및 연결 인프라 |
| Power | 데이터센터 전력 공급 및 전력 인프라 |
| Cooling | 데이터센터 냉각 및 열관리 시스템 |
| Optical | 고속 광통신 및 데이터 전송 인프라 |
| Data Center | 데이터센터 운영 및 관련 인프라 |
| Cloud | AI 연산을 지원하는 클라우드 인프라 |
| Storage | 대규모 데이터 저장 및 스토리지 |
| Industrial Automation | 생산 및 운영을 지원하는 자동화 기술 |

---

## 🔄 Index Construction Process

AI Infrastructure의 범위를 정의한 이후 기업 데이터 확보부터 최종 인덱스 산출까지 단계적으로 구축했습니다.

```text
AI Infrastructure 범위 정의
            ↓
후보 기업 Universe 구축
            ↓
SEC Company Facts 데이터 확보
            ↓
데이터 정제 및 Entity Matching
            ↓
AI Infrastructure 관련성 평가
            ↓
Selection Score 산출
            ↓
Theme Quota 적용
            ↓
최종 100개 Universe 선정
            ↓
재무 Factor 산출
            ↓
Eligibility 판단
            ↓
Scoring & Weighting
            ↓
분기별 Rebalancing
            ↓
Index Backtest & Validation
```

---

## 📥 데이터 확보 및 전처리

기업의 재무정보는 **SEC Company Facts**를 중심으로 구축했습니다.

주요 공시 데이터는 다음과 같습니다.

- 10-K
- 10-Q
- 20-F
- 40-F
- 6-K
- US-GAAP / IFRS 기반 재무정보

기업별 공시 데이터를 수집한 뒤 **Entity Master 및 Fact Store** 형태로 정리하여 기업별·시점별 재무 데이터를 활용할 수 있도록 구성했습니다.

### Point-in-Time

백테스트 과정에서 미래의 재무정보가 과거 시점의 종목 선정에 사용되는 것을 방지하기 위해 **Point-in-Time(PIT)** 원칙을 적용했습니다.

각 리밸런싱 시점에서 당시 실제로 이용 가능한 재무정보만 사용하도록 구성하여 **Look-ahead Bias를 최소화**했습니다.

> 대용량 SEC 원천 데이터 및 Historical Price Data는 Repository 용량을 고려하여 제외했습니다.

---

## 📊 Universe Selection

초기 AI Infrastructure 후보군을 구성한 뒤 기업의 **AI Infrastructure 관련성, 데이터 품질, 재무 팩터 가용성**을 종합적으로 평가했습니다.

### Selection Score

| 평가 항목 | 비중 |
|---|---:|
| AI Infrastructure 관련성 | 60% |
| Data Quality | 25% |
| Factor Availability | 15% |

단순 시가총액 순위가 아니라 **AI Infrastructure와의 직접성과 실제 인덱스 산출에 필요한 데이터 품질**을 함께 고려했습니다.

또한 특정 산업에 종목이 과도하게 집중되는 것을 방지하기 위해 **Theme Quota**를 적용하여 최종 **100개 종목 Universe**를 구성했습니다.

---

## 📐 Fundamental Factors

기업의 성장성·수익성·효율성·재무 안정성을 평가하기 위해 다음 4개 핵심 재무 팩터를 활용했습니다.

| Factor | 의미 |
|---|---|
| Revenue Growth | 매출 성장성 |
| Operating Margin | 영업 수익성 |
| ROA | 자산 활용 효율성 |
| Debt Ratio | 재무 안정성 |

각 리밸런싱 시점에서 필요한 재무 팩터의 가용 여부와 데이터 품질을 확인한 후 종목의 편입 가능 여부를 판단했습니다.

---

## ⚙️ Index Methodology

### Eligibility

종목의 인덱스 편입 여부는 다음 과정을 통해 판단하도록 설계했습니다.

```text
AI Infrastructure Relevance
            ↓
Business Continuity
            ↓
Financial Data Availability
            ↓
Factor Availability
            ↓
Data Quality
            ↓
Eligibility
```

초기 Universe에 포함된 기업을 그대로 유지하는 것이 아니라,  
각 리밸런싱 시점에서 기준을 충족하는 기업을 대상으로 인덱스를 구성했습니다.

### Weighting

초기 동일가중 방식에서 발전시켜 최종적으로 **Score 기반 비중 배분 방식**을 적용했습니다.

- Score-based Weighting
- 상위 Score 종목 중심 구성
- 개별 종목 최대 비중 **10%**
- Quarterly Rebalancing

이를 통해 높은 평가를 받은 기업에 상대적으로 높은 비중을 부여하면서도 특정 종목에 대한 과도한 집중을 제한했습니다.

---

## 🔁 Rebalancing

인덱스는 **분기 단위(Quarterly)**로 리밸런싱되도록 설계했습니다.

```text
Financial Data Update
        ↓
Factor Calculation
        ↓
Eligibility Check
        ↓
Scoring
        ↓
Constituent Selection
        ↓
Weight Calculation
        ↓
Index Rebalancing
```

기업의 재무상태와 AI Infrastructure 사업 관련성의 변화가 정기적으로 인덱스에 반영되도록 구성했습니다.

---

## 📈 Backtest & Performance

구축한 Custom Index의 과거 성과를 확인하기 위해 Historical Backtest를 수행했습니다.

주요 성과 평가지표는 다음과 같습니다.

- CAGR
- Maximum Drawdown (MDD)
- Sharpe Ratio
- Cumulative Return
- Volatility

단순 누적수익률뿐만 아니라 **수익성과 위험을 함께 평가**하여 인덱스의 특성을 검증했습니다.

---

## 🛡️ Data Integrity & Validation

금융 데이터 기반 프로젝트에서는 성과뿐만 아니라 **데이터의 신뢰성과 재현성**이 중요하다고 판단했습니다.

이에 따라 다음 항목을 중심으로 검증을 수행했습니다.

- Point-in-Time 데이터 사용 여부
- Look-ahead Bias 점검
- 재무 데이터 기준일 검증
- 구성 종목 검증
- Index Weight 검증
- Index Level 검증
- Price Data 검증
- Missing Data 처리 검증

이를 통해 데이터 수집부터 최종 지수 산출까지의 과정이 일관되게 연결되는지 확인했습니다.

---

## 🖥️ Monitoring System

구축된 인덱스를 일회성 분석으로 끝내지 않고 지속적으로 관리할 수 있도록  
**팀 프로젝트 차원에서 Monitoring Dashboard를 구현했습니다.**

Monitoring System에서는 다음과 같은 정보를 확인할 수 있도록 구성했습니다.

- Index Performance
- Current Constituents
- Theme Allocation
- Individual Stock Information
- Rebalancing History
- Inclusion / Exclusion
- Watchlist
- Risk & Technical Indicators

이를 통해 팀 프로젝트의 최종 결과물로 **Index Construction → Backtest → Monitoring**으로 이어지는 프로세스를 구현했습니다.

---

## 👤 My Contribution

본 프로젝트는 팀 프로젝트로 진행되었으며, 저는 **AI Infrastructure Custom Index 설계 및 투자 유니버스 구축을 중심으로 담당했습니다.**

### 주요 담당 업무

- AI Infrastructure 산업 범위 정의
- 10개 Infrastructure Theme 구조화
- 초기 투자 후보군 구성
- SEC 기반 기업 데이터 확보 과정 설계
- 후보 기업과 SEC Entity 데이터 매칭
- AI Infrastructure 관련성 평가 기준 설계
- Selection Score 설계
- Theme Quota 기반 최종 100개 Universe 구성
- 재무 Factor 및 Eligibility 기준 설계
- Index 편입 및 리밸런싱 방법론 설계
- 인덱스 구축 과정 문서화 및 결과 검증

특히 기존 AI ETF의 구성종목을 단순 활용하는 방식이 아니라,  
**AI Infrastructure의 범위를 정의하고 기업 데이터를 확보하여 투자 유니버스를 처음부터 구축하는 과정**에 집중했습니다.

---

## 🛠️ Tech Stack

**Language & Data Processing**

`Python` `Pandas` `NumPy`

**Financial Data**

`SEC Company Facts` `yfinance`

**Analysis**

`Financial Factor Analysis` `Point-in-Time Data` `Backtesting`

**Visualization & Monitoring**

`Streamlit` `Plotly` `Matplotlib`

---

## 📂 Repository Structure

```text
ai-infrastructure-index/
│
├── 01_Data_Acquisition/
│   └── SEC 및 기업 데이터 수집
│
├── 02_Data_Preprocessing/
│   └── 데이터 정제 및 기업 매칭
│
├── 03_Methodology/
│   └── Universe 및 Index Methodology
│
├── 04_Index_Construction/
│   └── Index 구성 및 Weight 계산
│
├── 05_Backtest/
│   └── Historical Backtesting
│
├── 06_Evaluation/
│   └── Performance Evaluation
│
├── 07_Data_Integrity/
│   └── 데이터 및 Index 무결성 검증
│
├── docs/
│   └── 프로젝트 관련 문서
│
├── figures/
│   └── 결과 및 시각화 자료
│
├── .gitignore
└── README.md
```

> 대용량 Raw SEC Data 및 Historical Price Data는 Repository에서 제외했습니다.  
> 본 Repository는 **Index Construction Methodology, 구현 코드 및 검증 과정**을 중심으로 구성했습니다.

---

## 💡 Key Takeaways

본 프로젝트를 통해 단순히 주어진 금융 데이터를 분석하는 것을 넘어,

**산업 정의 → 데이터 확보 → 투자 유니버스 구축 → 팩터 설계 → 인덱스 구성 → 백테스트 → 검증**

으로 이어지는 **Quantitative Investment Research Process**를 경험했습니다.

특히 금융 데이터 분석에서는 단순한 수익률 개선뿐만 아니라  
**공시 시점, 데이터 기준일, 결측치, 데이터 품질 및 Look-ahead Bias를 통제하는 과정이 중요하다**는 점을 확인했습니다.

---

### Team Project

본 Repository는 AI Quant Bootcamp에서 진행한 팀 프로젝트를 기반으로 하며,  
개인적으로 담당한 **AI Infrastructure Universe 구축 및 Custom Index 설계 영역을 중심으로 정리했습니다.**
