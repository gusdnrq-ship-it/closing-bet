"""전략 플러그인 인터페이스.

각 전략 모듈은 다음을 구현한다:
    STRATEGY_META: dict  — name(파일명과 동일), display_name, source, caveats
    MIN_ROWS: int        — 최소 필요 데이터 행 수
    generate(df) -> dict | None
        df: index=date(datetime), 컬럼 open/high/low/close/volume (오름차순)
        반환: {"direction": "UP"|"DOWN", "reason": str, "metrics": dict} 또는 None
        (마지막 거래일에 신호가 있으면 반환, 없으면 None)

caveats에는 전략의 한계를 미화하지 않고 그대로 적는다 — 대시보드에 그대로 노출된다.
"""
from importlib import import_module

from app.signals import bnf_oversold, breakout, ssanggul

REGISTRY = {
    breakout.STRATEGY_META["name"]: breakout,
    ssanggul.STRATEGY_META["name"]: ssanggul,
    bnf_oversold.STRATEGY_META["name"]: bnf_oversold,
}


def get(name: str):
    if name not in REGISTRY:
        raise KeyError(f"없는 전략: {name} (가능: {list(REGISTRY)})")
    return REGISTRY[name]


def all_strategies() -> dict:
    return dict(REGISTRY)
