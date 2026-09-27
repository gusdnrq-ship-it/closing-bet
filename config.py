"""종가배팅 프로젝트 공통 설정."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "db" / "closing_bet.db"

# 데이터 수집
YEARS_BACKFILL = 5
FETCH_DELAY = (0.05, 0.15)   # 요청 사이 랜덤 대기(초)
FETCH_RETRY = 3
REFRESH_DAYS = 10            # 증분 갱신 시 최근 N일만 다시 받음

# 유니버스 필터
EXCLUDE_ETF_ETN = True       # type 이 ST/PS 가 아닌 것 제외 (ETF·ETN·채권 등)
EXCLUDE_KONEX = True         # 코넥스 제외
EXCLUDE_HALTED = True        # 거래정지(tradeStopYn=Y) 제외
EXCLUDE_MANAGEMENT = True    # 관리종목/투자주의 이상(manageStatusGb!=0) 제외

# 스캔
MIN_ROWS = 60                # 이 행 수 미만 종목은 스캔 제외
SETTLE_VOID_DAYS = 30        # 시그널 후 30일 내 결제 데이터가 없으면 VOID(상장폐지 등)

# 전략 파라미터
BREAKOUT_LOOKBACK = 20       # 신고가/거래량 비교 윈도우
BREAKOUT_VOL_MULT = 1.5      # 거래량이 직전 20일 평균의 몇 배여야 하는가

SSANGGUL_BB_PERIOD = 60
SSANGGUL_MULT_NARROW = 2.0
SSANGGUL_MULT_WIDE = 3.5
SSANGGUL_CONFIRM_WINDOW = 10
SSANGGUL_TREND_FILTER = True
SSANGGUL_TREND_LOOKBACK = 20
SSANGGUL_TREND_MIN_SLOPE = 0.0

# BNF 이격도 역반등 (유튜브 쇼츠 — 파라미터 일부는 영상 미명시로 가정)
BNF_MA_PERIOD = 60        # 이격도 기준 이동평균 (가정: 영상 미명시)
BNF_DEV_MAX = 80.0        # 이격도 하한 — 종가/MA×100 ≤ 80
BNF_RSI_PERIOD = 14
BNF_RSI_MAX = 30.0        # RSI 과매도
BNF_MACD_FAST = 12
BNF_MACD_SLOW = 26
BNF_MACD_SIGNAL = 9
BNF_DROP_MAX = -2.0       # "강한 하락" = 당일 등락률 ≤ -2% (가정: 영상 미명시)

# 종목선택 랭커 (당일 후보 → 상위 N 선택)
RANK_TOP_N = 5           # 전략별 상위 N종목에 '선택' 표시
RANK_MIN_MONEY = 1_000_000_000   # 선택 최소 조건: 5일 평균 일 거래대금 1억 이상
RANK_W_DEV = 0.40        # 이격도 가중치 (낮을수록 좋음 — 평균회귀 여력)
RANK_W_RSI = 0.30        # RSI 가중치 (낮을수록 좋음 — 과매도 깊이)
RANK_W_MONEY = 0.30      # 거래대금 가중치 (높을수록 좋음 — 체결 가능성)

# 매도 타이밍 모니터 (원 영상 규칙: 익절=이격도 0, 손절=이전 저점)
SELL_TRACK_DAYS = 15     # 최근 N거래일 시그널의 보유 상태를 추적
SELL_STOP_LOOKBACK = 60  # 손절선 = 신호일 이전 N거래일 최저가 (영상 미명시 — 가정)

# 서버
HOST = "127.0.0.1"
PORT = 8788
