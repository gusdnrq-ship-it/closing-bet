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

## 구조

```
run.py              CLI (universe/backfill/refresh/scan/export/status/serve)
config.py           설정 (경로, 필터, 전략 파라미터)
app/
  universe.py       유니버스 수집 (네이버 stock API)
  data.py           OHLCV 수집/백필/증분
  scanner.py        시그널 스캔 + 익일 종가 정산
  scoreboard.py     적중률/후보/상세 조회
  main.py           FastAPI 라우트 (/api/...)
  export.py         정적 JSON (app/static/api/) + site/ 발행
  signals/          전략 플러그인 (base, breakout, ssanggul)
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
