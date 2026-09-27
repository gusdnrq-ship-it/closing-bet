"""종가배팅 CLI.

사용법 (프로젝트 폴더에서):
    python run.py universe          # 종목 목록 수집
    python run.py backfill          # 전체 5년 백필 (약 5~10분)
    python run.py backfill --sample 5   # 샘플 5종목만 (검증용)
    python run.py refresh           # 최근 데이터 증분 갱신
    python run.py scan              # 시그널 스캔 + 정산
    python run.py backtest          # 전 전략 백테스트 (기본 360거래일, --days 0=전체)
    python run.py export            # 정적 대시보드 JSON/site 발행
    python run.py status            # 현재 상태 요약
    python run.py serve             # 대시보드 실행 (http://127.0.0.1:8788)
"""
import argparse
import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config  # noqa: E402
from app import data, db, export, universe  # noqa: E402
from app import scanner  # noqa: E402


def progress(i, total, done, failed):
    print(f"  진행 {i}/{total} (성공 {done} / 실패 {failed})", flush=True)


def main():
    p = argparse.ArgumentParser(description="종가배팅 CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("universe", help="코스피/코스닥 전체 종목 목록 수집")

    bf = sub.add_parser("backfill", help="전체/샘플 OHLCV 백필")
    bf.add_argument("--sample", type=int, default=0, help="시총 상위 N종목만")
    bf.add_argument("--codes", nargs="*", help="지정 종목코드만")

    sub.add_parser("refresh", help="최근 데이터 증분 갱신")
    sc = sub.add_parser("scan", help="시그널 스캔 + 정산")
    sc.add_argument("--strategy", nargs="*", help="지정 전략만 (기본 전체)")

    bt = sub.add_parser("backtest", help="전 전략 과거 재생 백테스트")
    bt.add_argument("--days", type=int, default=360, help="최근 N거래일 (0=전체)")
    bt.add_argument("--strategy", nargs="*", help="지정 전략만 (기본 전체)")

    sub.add_parser("export", help="정적 대시보드 JSON/site 발행")
    sub.add_parser("status", help="현재 상태 요약")

    sv = sub.add_parser("serve", help="대시보드 서버 실행")
    sv.add_argument("--host", default=config.HOST)
    sv.add_argument("--port", type=int, default=config.PORT)

    args = p.parse_args()
    conn = db.connect()

    if args.cmd == "universe":
        rows = universe.refresh_universe(conn)
        kospi = sum(1 for r in rows if r["market"] == "KOSPI")
        print(f"유니버스 수집 완료: {len(rows)}종목 (코스피 {kospi} / 코스닥 {len(rows)-kospi})")

    elif args.cmd == "backfill":
        codes = args.codes
        if args.sample:
            codes = [r["code"] for r in conn.execute(
                "SELECT code FROM stocks ORDER BY market_sum DESC LIMIT ?", (args.sample,))]
        elif not codes:
            if conn.execute("SELECT COUNT(*) c FROM stocks").fetchone()["c"] == 0:
                print("stocks 테이블이 비어 있습니다 — 'python run.py universe' 먼저 실행")
                sys.exit(1)
        print(f"백필 시작 (총 {len(codes) if codes else '전체'} 종목)...")
        res = data.backfill_all(conn, codes, progress=progress)
        print(f"완료: 성공 {res['done']}/{res['total']}, 실패 {len(res['failed'])}")
        for f in res["failed"][:10]:
            print(f"  실패 {f['code']}: {f['error']}")

    elif args.cmd == "refresh":
        print("증분 갱신 시작...")
        res = data.refresh_all(conn)
        print(f"완료: 성공 {res['done']}/{res['total']}, 실패 {len(res['failed'])}")
        export.export_api(conn)

    elif args.cmd == "scan":
        res = scanner.run_scan(conn, strategy_names=args.strategy)
        print(res)
        export.export_api(conn)

    elif args.cmd == "backtest":
        import json
        from app import backtest
        res = backtest.run(conn, strategy_names=args.strategy, days=args.days)
        print(json.dumps(res, ensure_ascii=False, indent=2))

    elif args.cmd == "export":
        st = export.run(conn)
        print(f"발행 완료: {st['exported']} · site/ ({st['stocks']}종목, 시그널 {st['signals']}건)")

    elif args.cmd == "status":
        from app import scoreboard
        print(scoreboard.scoreboard(conn))

    elif args.cmd == "serve":
        import uvicorn
        export.export_api(conn)
        print(f"대시보드: http://{args.host}:{args.port}")
        uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="info")

    conn.close()


if __name__ == "__main__":
    main()
