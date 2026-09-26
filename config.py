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

# 서버
HOST = "127.0.0.1"
PORT = 8788
