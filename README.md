# 종가배팅 (Closing Bet)

코스피/코스닥 전체 종목을 대상으로 **내일 종가 방향(상승/하락) 베팅 후보 시그널**을 매일 스캔하고,
**익일 거래일 종가로 적중/미달을 판정**해 방향 적중률을 누적하는 실전 연동 시스템.

- 시그널 판정: T일 시그널 → T+1 거래일 종가로 판정 (동일가·거래정지 등은 `SETTLE_VOID_DAYS` 내 미결제 시 VOID)
- 스코어보드: **방향 적중률만** 표시 (가상손익 없음), 항상 **표본수 + 전략 caveats 병기**
- 실행 방식: **GitHub Actions가 매일(평일) 자동 갱신** + 웹 대시보드(GitHub Pages), 로컬에서는 수동 `scan` 버튼도 가능
- 데이터 출처: 네이버 증권 read-only API (유니버스 + OHLCV)

## 웹 대시보드 (자동 갱신)

**https://gusdnrq-ship-it.github.io/closing-bet/**

- **GitHub Actions** (`.github/workflows/daily.yml`)가 평일 UTC 12:00 (한국 21:00, 장 마감 후)에 자동 실행:
  `refresh` (증분 갱신) → `scan` (스캔+정산) → `export` (정적 JSON 발행) → GitHub Pages 배포
- **DB 연속성**: 실행마다 직전 run의 `db` artifact(90일 보관)를 복원하고, 없으면 `seed` release(1.5년 축소본)로 시작
- 수동 실행: GitHub Actions 탭 → `daily-update` → **Run workflow**
- 웹 버전은 **조회 전용** (스캔·차트 API는 로컬 `serve` 전용, 웹에서는 정적 JSON으로 시그널 이력·후보 제공)

## 알림 (Discord 웹훅 · GitHub 이슈 자동 대체)

매일 런 직후 오늘의 스캔 결과를 보낸다 (`app/notify.py` → `python run.py notify`).

- 알림 내용: 시그널 수(전략별 분포) · ★ 선택 목록(신고가 돌파폭) · 최근 판정 배치 적중률 · 매도 추적 상태(TP/SL/보유) · 오늘 청산 건 · 대시보드 링크
- **채널 자동 선택 (추가 설정 불필요)**:
  1. `DISCORD_WEBHOOK_URL` 시크릿이 있으면 → Discord로 전송
  2. 없으면(Actions 기본) → 저장소 이슈 **`📡 일일 알림`** 에 자동 댓글 (날짜순으로 쌓임, GitHub 알림으로 수신)
  3. 둘 다 없으면 → 로컬 출력 후 건너뜀 (런은 항상 계속)
- Discord로 바꾸려면: Discord 채널 → 설정 → 통합 → 웹훅 → URL 복사 →
  GitHub **Settings → Secrets → Actions** 에 `DISCORD_WEBHOOK_URL` 등록 (등록 즉시 자동 우선).

## 빠른 시작

```powershell
python run.py universe        # 종목 목록 수집 (~2,500종목)
python run.py backfill        # 전체 5년 OHLCV 백필 (~10분)
python run.py scan            # 시그널 스캔 + 익일 판정
python run.py serve           # 대시보드 http://127.0.0.1:8788
```

부가 명령: `backfill --sample N` (시총 상위 N종목 검증용), `backfill --codes 005930 ...`,
`refresh` (최근 데이터 증분 갱신), `status` (상태 요약).

## 전략

| ID | 이름 | 규칙 |
|----|------|------|
| `breakout` | 20일 신고가 돌파 + 거래량 급증 | 종가 > 직전 20일 고가 AND 거래량 ≥ 1.5× 20일 평균 → UP |
| `ssanggul_bollinger` | 쌍굴파기 이중 볼린저밴드 | technical-trading 1호 전략 재구현 (원본 caveats 승계, 빈번한 신호 아님) |
| `bnf_oversold` | BNF 이격도 80 역반등 매수 | 당일 ≤ -2% 급락 AND 이격도(60일MA) ≤ 80 AND RSI ≤ 30 AND MACD 히스토그램 음수 → UP (유튜브 쇼츠 학습, 파라미터 일부 가정) |

파라미터는 `config.py`에서 조정합니다 (`BREAKOUT_*`, `SSANGGUL_*`, `BNF_*`).

과거 재생 백테스트: `python run.py backtest --days 360` (0=전체 기간, `--strategy`로 지정).

## 종목선택 랭커 · 매도 타이밍

- **종목선택 랭커** (`app/ranker.py`): 당일 후보를 압축해 ★ 선택 표시.
  점수는 **5년 재생 검증(2021-10~2026-09, 신호 90,544건)을 통과한 것만** 사용:
  - **breakout** = 신고가 돌파폭(dist_high) 백분위 상위 5종목 → 집계 **+3.6p [유의]**,
    그룹 크기 4/4 구간에서 양수(일관). 거래량 배수는 −5.8p·거래대금은 예측 기여 없음(−2.3p)으로 폐기.
  - **bnf_oversold** = 점수화 **비활성화**(순위 없음, 나열만): 전 점수 변형이 집계 −10.8~−12.1p —
    원인은 시장 급락 대형그룹(100+ 신호일)이며 일반적 6~100개 후보일은 −1.1~+1.3p로 무의미.
  - ★ 선택 = 상위 5종목 + 5일 평균 대금 10억 이상(체결 마진 하한 — 예측 기여 없음으로 검증됨).
  *전부 in-sample 검증 — 미래 성과를 보장하지 않는다.*
- **매도 타이밍** (`app/sell_timing.py`): 최근 15거래일 매수(UP) 신호를 "다음 날 시가에 샀다"고 가정하고
  원 영상 매도 규칙으로 추적 — **익절** = 가격이 60일선 회귀(원 영상의 '이격도 0' 해석),
  **손절** = 신호 이전 60일 최저가 하회('이전 저점', 룩백 가정).
  실제 보유가 아닌 **가상 추적**이며, 규칙의 검증 결과는 아래 '매도 규칙 백테스트' 참조.
- 파라미터: `config.py`의 `RANK_*`, `SELL_*`.

## 매도 규칙 백테스트 (5년, 93,752건 · 개발/검증 분할)

진입 = 신호 다음 거래일 시가, 매도 = 원 영상 규칙(TP=60일선 회귀 / SL=신호 이전 60일 최저가),
대조군 = 같은 진입으로 T+1/5/20/60 종가 보유. 개발(2021-10~2023-12) / 검증(2024-01~2026-09) 분할.

| 항목 | bnf_oversold (24,526건) | breakout (69,020건) | 쌍굴파기 (206건) |
|------|------------------------|--------------------|------------------|
| TP 평균 (개발→검증) | +27.5% → **+30.2% (유효**, T+20 보유 +21~23%보다 우수) | −0.1% (신고가 종목이라 **97.6%가 즉시 TP = T+1 매도와 동일**) | +5.5% (표본 작음) |
| SL | 95% 발동: **72%는 진입 시가<손절선 → 0% 즉시 출구**(보유 시 +5% 기회상실), 실손절 23%는 T+20과 동일 손실 | **손절 −15.7% vs 동일 거래 T+20 −13.4% → 바닥권 체결, 손실 확대** (검증 −2.3p 일관) | 72건 −8.9% (유의성 없음) |
| R 기대값 (전체→검증) | +0.68R → **+0.28R (절반 감소 = 과적합 경고)** | −0.01R (0) | +0.08R (표본 부족) |
| 결론 | **TP는 유효, SL은 검증 실패** | **TP/SL 모두 무가치** (≈ T+1 매도) | **5년 206건 — 결론 불가** |

- 고정 보유 대비: BNF는 T+5/T+20/T+60 평균이 모두 **양수(+3.6~+5.6%)**로 규칙(+0.25%)보다 유리 —
  손절선이 진입가에 너무 가까워 갭 출발 시 보유를 못 함.
- 부수 발견: breakout은 방향 적중률 45.5%(기준 44.2% 상회)이나 **평균수익은 음수(−0.46% T+1)** —
  적중률 지표가 수익 구조를 가림. 랭커의 적중률 기준(+3.6p)도 수익 기준으로 재검증 과제.
- 규칙은 원 영상 그대로 유지하며 위 검증 결과를 caveat으로 노출한다 (임의 수정 없음).

## 구조

```
run.py              CLI (universe/backfill/refresh/scan/export/notify/status/serve)
config.py           설정 (경로, 필터, 전략 파라미터)
app/
  universe.py       유니버스 수집 (네이버 stock API)
  data.py           OHLCV 수집/백필/증분
  scanner.py        시그널 스캔 + 익일 종가 정산
  scoreboard.py     적중률/후보/상세 조회
  ranker.py         종목선택 랭커 (후보 압축)
  sell_timing.py    매도 타이밍 모니터 (익절/손절 가상 추적)
  notify.py         Discord 웹훅 알림 (스캔·판정·매도 요약)
  main.py           FastAPI 라우트 (/api/...)
  export.py         정적 JSON (app/static/api/) + site/ 발행
  signals/          전략 플러그인 (base, breakout, ssanggul, bnf_oversold)
  static/           대시보드 (index.html, app.js, style.css)
scripts/make_seed.py  seed DB(360거래일 축소본) 생성
.github/workflows/daily.yml  Actions 자동 갱신 + Pages 배포
db/closing_bet.db   SQLite (stocks, ohlcv, signals, meta) — git 제외
docs/               사용법 PDF (종가배팅_사용법.pdf)
```

## 데이터 수집 함정 (검증 완료)

- 유니버스 API `startIdx`는 **아이템 오프셋이 아니라 페이지 번호(0,1,2,…)** 이다.
  항목 범위 = `[startIdx * pageSize, (startIdx+1) * pageSize)`. 오프셋으로 해석하면
  대부분 빈 배열이 반환된다 (전체 수집 실패의 원인).
- 유니버스는 시총 상위 약 2,900종목까지만 제공 → 필터(ETF/ETN·KONEX·거래정지·관리종목 제외) 후 약 2,500종목.
- OHLCV는 `api.finance.naver.com/siseJson.naver` (일봉). 5년 백필 시 약 1,223 거래일.

## 유의사항

시그널은 참고용 정보이며 매매 추천이 아닙니다. 적중률은 표본수와 함께 확인하세요
(표본 10건 미만은 통계적 유의성이 없습니다). 전략별 caveats는 스코어보드에 항상 표시됩니다.
