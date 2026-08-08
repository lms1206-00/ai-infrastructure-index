# 유니버스 100 종목 선정 사유 문서

근거: `data/classification/final_universe_100.csv` 실측값(임의 서술 없음). 선정 로직: `02_Data_Preprocessing/code/03_classification_rule.py`.

## 선정 방법 요약

1. **후보 풀**: 큐레이션 `ai_infrastructure_candidates.csv`(142행/135티커), 각 종목에 테마·sub_theme·candidate_score(AI인프라 직접성 0~100) 부여.
2. **Entity Master 매칭**: SEC 재무가 있는 후보만 진행(미매칭 7 탈락).
3. **selection_score = 관련성(candidate_score)×0.60 + 데이터품질×0.25 + 팩터가용성×0.15**.
4. **테마 쿼터 선정**: 테마별 상위 selection_score 순으로 쿼터 충족(98건).
5. **부족분 보충**: Storage 후보부족(3<5)으로 빈 2슬롯을 잔여 최고점으로 보충(2건).
6. 정확히 100개 → universe_rank 부여.

- 총 100종목, selection_score 55.2~100.0, theme_quota 98 + shortage_fill 2.


## 테마별 선정 종목 (AI 인프라 축 근거 포함)


### Semiconductor — AI 학습·추론 연산의 핵심(설계·파운드리·장비·소재·패키징) (30종목)

| 랭크 | ticker | sub_theme | cand_score | sel_score | 단계 |
|---|---|---|---|---|---|
| 4 | ASML | Lithography Equipment | 98 | 98.8 | 쿼터 |
| 6 | TSM | Foundry | 98 | 98.8 | 쿼터 |
| 7 | AMD | GPU | 97 | 98.2 | 쿼터 |
| 8 | AVGO | AI Accelerator / Networking ASIC | 96 | 97.6 | 쿼터 |
| 11 | NVDA | GPU | 100 | 97.4 | 쿼터 |
| 13 | AMAT | Wafer Equipment | 94 | 96.4 | 쿼터 |
| 15 | MRVL | Data Center ASIC | 94 | 96.4 | 쿼터 |
| 16 | MU | Memory / HBM | 94 | 96.4 | 쿼터 |
| 27 | LRCX | Wafer Equipment | 94 | 93.8 | 쿼터 |
| 28 | CRDO | High-Speed Connectivity IC | 89 | 93.4 | 쿼터 |
| 32 | ARM | CPU Architecture | 88 | 92.8 | 쿼터 |
| 33 | INTC | CPU / Foundry | 88 | 92.8 | 쿼터 |
| 34 | MPWR | Power Management IC | 87 | 92.2 | 쿼터 |
| 36 | KLAC | Process Control | 93 | 92.0 | 쿼터 |
| 44 | ENTG | Materials / Process Products | 84 | 90.4 | 쿼터 |
| 48 | ONTO | Inspection / Metrology | 84 | 90.4 | 쿼터 |
| 53 | LSCC | FPGA | 83 | 89.8 | 쿼터 |
| 55 | ACLS | Ion Implantation Equipment | 82 | 89.2 | 쿼터 |
| 59 | GFS | Foundry | 82 | 89.2 | 쿼터 |
| 68 | AMKR | Packaging / Testing | 79 | 87.4 | 쿼터 |
| 70 | FORM | Probe Cards | 79 | 87.4 | 쿼터 |
| 73 | ADI | Analog / Signal Processing | 78 | 86.8 | 쿼터 |
| 78 | MKSI | Process Equipment Components | 78 | 86.8 | 쿼터 |
| 79 | ON | Power Semiconductor | 78 | 86.8 | 쿼터 |
| 80 | TXN | Analog / Power Semiconductor | 78 | 86.8 | 쿼터 |
| 83 | NXPI | Processor / Connectivity | 75 | 85.0 | 쿼터 |
| 84 | QCOM | Processor | 79 | 84.8 | 쿼터 |
| 85 | UMC | Foundry | 74 | 84.4 | 쿼터 |
| 87 | COHU | Test / Inspection Equipment | 73 | 83.8 | 쿼터 |
| 88 | MCHP | MCU / Connectivity | 73 | 83.8 | 쿼터 |

### Power — 데이터센터 급전 전력설비·전력생산 (15종목)

| 랭크 | ticker | sub_theme | cand_score | sel_score | 단계 |
|---|---|---|---|---|---|
| 3 | VRT | Data Center Power Management | 100 | 100.0 | 쿼터 |
| 19 | PWR | Grid / Electrical Infrastructure | 92 | 95.2 | 쿼터 |
| 25 | NVT | Electrical Connection / Protection | 90 | 94.0 | 쿼터 |
| 30 | ETN | Electrical Equipment | 95 | 92.9 | 쿼터 |
| 38 | GEV | Grid / Power Generation | 91 | 92.0 | 쿼터 |
| 42 | GNRC | Backup Power | 85 | 91.0 | 쿼터 |
| 50 | HUBB | Electrical Equipment | 88 | 90.2 | 쿼터 |
| 57 | ATKR | Electrical Infrastructure Products | 82 | 89.2 | 쿼터 |
| 58 | CEG | Electric Power Generation | 82 | 89.2 | 쿼터 |
| 62 | MYRG | Electrical Construction | 82 | 89.2 | 쿼터 |
| 71 | VST | Electric Power Generation | 79 | 87.4 | 쿼터 |
| 74 | AME | Electrical Instruments | 78 | 86.8 | 쿼터 |
| 75 | ENS | Energy Storage Systems | 78 | 86.8 | 쿼터 |
| 94 | NRG | Electric Power Generation | 70 | 82.0 | 쿼터 |
| 96 | SO | Electric Utility | 68 | 80.8 | 쿼터 |

### Server — AI 서버/데이터센터 하드웨어·EMS 공급 (10종목)

| 랭크 | ticker | sub_theme | cand_score | sel_score | 단계 |
|---|---|---|---|---|---|
| 2 | SMCI | AI Server | 100 | 100.0 | 쿼터 |
| 20 | DELL | Enterprise / AI Server | 91 | 94.6 | 쿼터 |
| 47 | NTNX | Hyperconverged Infrastructure | 84 | 90.4 | 쿼터 |
| 52 | HPE | Enterprise / HPC Server | 88 | 89.8 | 쿼터 |
| 72 | CLS | Data Center Hardware Manufacturing | 83 | 87.2 | 쿼터 |
| 77 | FLEX | Electronics Manufacturing | 78 | 86.8 | 쿼터 |
| 86 | JBL | Data Center Manufacturing | 84 | 84.3 | 쿼터 |
| 92 | SANM | Electronics Manufacturing | 72 | 83.2 | 쿼터 |
| 95 | CDW | IT Infrastructure Distribution | 68 | 80.8 | 쿼터 |
| 97 | IBM | Enterprise Computing | 74 | 80.6 | 쿼터 |

### Networking — 데이터센터/통신 네트워크 장비 (10종목)

| 랭크 | ticker | sub_theme | cand_score | sel_score | 단계 |
|---|---|---|---|---|---|
| 9 | ANET | Data Center Switching | 100 | 97.4 | 쿼터 |
| 22 | CSCO | Network Equipment | 90 | 94.0 | 쿼터 |
| 35 | NET | Edge Network / CDN | 87 | 92.2 | 쿼터 |
| 56 | AKAM | Edge Network / CDN | 82 | 89.2 | 쿼터 |
| 76 | FFIV | Application Delivery | 78 | 86.8 | 쿼터 |
| 81 | EXTR | Enterprise Networking | 76 | 85.6 | 쿼터 |
| 89 | UI | Network Equipment | 73 | 83.8 | 쿼터 |
| 91 | CALX | Broadband Network Platform | 72 | 83.2 | 쿼터 |
| 93 | ERIC | Telecom Network Equipment | 70 | 82.0 | 쿼터 |
| 99 | NOK | Telecom Network Equipment | 70 | 79.4 | 쿼터 |

### Cooling — 데이터센터 냉각/열관리 설비 (8종목)

| 랭크 | ticker | sub_theme | cand_score | sel_score | 단계 |
|---|---|---|---|---|---|
| 24 | MOD | Thermal Management | 90 | 94.0 | 쿼터 |
| 29 | TT | HVAC / Thermal Management | 93 | 93.2 | 쿼터 |
| 37 | CARR | HVAC / Data Center Cooling | 91 | 92.0 | 쿼터 |
| 45 | FIX | Mechanical / HVAC Services | 84 | 90.4 | 쿼터 |
| 61 | LII | HVAC Equipment | 82 | 89.2 | 쿼터 |
| 65 | AAON | HVAC Equipment | 86 | 88.6 | 쿼터 |
| 67 | SPXC | Cooling / Thermal Equipment | 84 | 87.4 | 쿼터 |
| 82 | WTS | Water / Thermal Systems | 76 | 85.6 | 쿼터 |

### Optical — 데이터센터 광통신 부품·트랜시버 (7종목)

| 랭크 | ticker | sub_theme | cand_score | sel_score | 단계 |
|---|---|---|---|---|---|
| 14 | LITE | Optical Components | 94 | 96.4 | 쿼터 |
| 17 | CIEN | Optical Networking | 92 | 95.2 | 쿼터 |
| 26 | COHR | Optical Components | 96 | 93.8 | 쿼터 |
| 31 | AAOI | Optical Transceivers | 88 | 92.8 | 쿼터 |
| 39 | MTSI | Optical / RF Semiconductors | 86 | 91.6 | 쿼터 |
| 41 | FN | Optical Manufacturing | 85 | 91.0 | 쿼터 |
| 63 | VIAV | Optical Test / Components | 82 | 89.2 | 보충 |

### Data Center — AI 워크로드 수용 데이터센터 운영/REIT (6종목)

| 랭크 | ticker | sub_theme | cand_score | sel_score | 단계 |
|---|---|---|---|---|---|
| 10 | EQIX | Colocation / Interconnection | 100 | 97.4 | 쿼터 |
| 21 | DLR | Data Center REIT | 98 | 94.4 | 쿼터 |
| 23 | GDS | Data Center Operator | 90 | 94.0 | 쿼터 |
| 66 | IRM | Data Center / Digital Infrastructure | 81 | 88.6 | 쿼터 |
| 90 | AMT | Digital Infrastructure REIT | 72 | 83.2 | 쿼터 |
| 98 | VNET | Data Center Operator | 84 | 80.2 | 쿼터 |

### Cloud — 하이퍼스케일 클라우드 인프라 운영 (6종목)

| 랭크 | ticker | sub_theme | cand_score | sel_score | 단계 |
|---|---|---|---|---|---|
| 1 | MSFT | Hyperscale Cloud | 100 | 100.0 | 쿼터 |
| 5 | GOOGL | Hyperscale Cloud | 98 | 98.8 | 쿼터 |
| 12 | AMZN | Hyperscale Cloud | 100 | 97.0 | 쿼터 |
| 18 | ORCL | Cloud Infrastructure | 92 | 95.2 | 쿼터 |
| 54 | SNOW | Cloud Data Platform | 83 | 89.8 | 쿼터 |
| 69 | DDOG | Cloud Monitoring Platform | 79 | 87.4 | 보충 |

### Industrial Automation — 산업 자동화 설비·제어 (5종목)

| 랭크 | ticker | sub_theme | cand_score | sel_score | 단계 |
|---|---|---|---|---|---|
| 43 | CGNX | Machine Vision | 84 | 90.4 | 쿼터 |
| 46 | HON | Automation / Controls | 84 | 90.4 | 쿼터 |
| 51 | ROK | Industrial Controls | 90 | 89.9 | 쿼터 |
| 60 | KEYS | Electronic Test Equipment | 82 | 89.2 | 쿼터 |
| 64 | EMR | Industrial Automation | 88 | 88.7 | 쿼터 |

### Storage — 학습데이터·모델 저장 하드웨어 (3종목)

| 랭크 | ticker | sub_theme | cand_score | sel_score | 단계 |
|---|---|---|---|---|---|
| 40 | WDC | Data Storage Hardware | 86 | 91.6 | 쿼터 |
| 49 | STX | Data Storage Hardware | 84 | 90.4 | 쿼터 |
| 100 | NTAP | Enterprise Data Storage | 92 | 55.2 | 쿼터 |

## 종목별 상세 사유

전체 100종목의 문장형 사유는 `data/integrity/universe_selection_rationale.csv` 의 `selection_reason_doc` 컬럼 참조. 예시:

- **MSFT** (MICROSOFT CORP): Cloud/Hyperscale Cloud 테마. AI인프라 직접성 candidate_score 100, 종합 selection_score 100.0(관련성60%×100 + 품질25%×100 + 팩터15%×100). 테마쿼터 단계·유니버스랭크 1위. 데이터품질 100, 가용팩터 13/13.
- **SMCI** (Super Micro Computer, Inc.): Server/AI Server 테마. AI인프라 직접성 candidate_score 100, 종합 selection_score 100.0(관련성60%×100 + 품질25%×100 + 팩터15%×100). 테마쿼터 단계·유니버스랭크 2위. 데이터품질 100, 가용팩터 13/13.
- **VRT** (Vertiv Holdings Co): Power/Data Center Power Management 테마. AI인프라 직접성 candidate_score 100, 종합 selection_score 100.0(관련성60%×100 + 품질25%×100 + 팩터15%×100). 테마쿼터 단계·유니버스랭크 3위. 데이터품질 100, 가용팩터 13/13.

## 한계·주의

- candidate_score는 큐레이션 사전점수(AI인프라 직접성)로, 개별 공식공시 전수 검증이 아니라 큐레이션 기준이다(SNOW·DDOG·CDW 등 직접성 재검토는 별도 트랙).
- 이 100은 **후보 유니버스**이며, 실제 분기 편입(Top30)은 이후 PIT·자격·Factor Score·테마 적격성 게이트를 추가로 통과해야 한다.
