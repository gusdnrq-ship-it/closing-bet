"""seed DB(클라우드 백업용 축소본) 생성.

최근 360 거래일(약 1.5년) OHLCV + stocks + signals + meta를 복사해
db/seed/closing_seed.zip (sqlite 파일 하나를 gzip)으로 만든다.

사용법: python scripts/make_seed.py [보관 거래일 수, 기본 360]
"""
import gzip
import shutil
import sqlite3
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 360


def main():
    src = sqlite3.connect(str(config.DB_PATH))
    src.row_factory = sqlite3.Row

    dates = [r["date"] for r in src.execute(
        "SELECT DISTINCT date FROM ohlcv ORDER BY date DESC LIMIT ?", (DAYS,))]
    if not dates:
        sys.exit("DB에 ohlcv 데이터가 없습니다")
    cutoff = min(dates)
    print(f"보관 구간: {len(dates)}거래일 ({cutoff} ~ {max(dates)})")

    seed_path = config.DB_PATH.parent / "seed" / "closing_seed.db"
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    if seed_path.exists():
        seed_path.unlink()

    dst = sqlite3.connect(str(seed_path))
    src.backup(dst)  # 스키마·인덱스 통째 복사
    # 보관 기간 초과 OHLCV 제거
    cur = dst.execute("DELETE FROM ohlcv WHERE date < ?", (cutoff,))
    print(f"OHLCV 삭제(초과분): {cur.rowcount}행")

    # WAL 정리 후 일관성 확보
    dst.commit()
    dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    dst.commit()
    n = dst.execute("SELECT COUNT(*) c FROM ohlcv").fetchone()[0]
    s = dst.execute("SELECT COUNT(*) c FROM stocks").fetchone()[0]
    g = dst.execute("SELECT COUNT(*) c FROM signals").fetchone()[0]
    print(f"seed DB: ohlcv {n:,}행 / stocks {s:,}종목 / signals {g:,}건")
    dst.close()
    src.close()

    # gzip (단일 db 파일)
    gz_path = seed_path.with_suffix(".gz")
    with open(seed_path, "rb") as f_in, gzip.open(gz_path, "wb", compresslevel=9) as f_out:
        shutil.copyfileobj(f_in, f_out)

    # zip (Actions artifact / 해제 편의용 — 둘 다 동일 크기 구조)
    zip_path = config.DB_PATH.parent / "seed" / "closing_seed.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.write(seed_path, arcname="closing_seed.db")

    print(f"생성 완료: {zip_path} ({zip_path.stat().st_size/1e6:.1f} MB) / {gz_path} ({gz_path.stat().st_size/1e6:.1f} MB)")
    seed_path.unlink()  # zip에 들어갔으니 원본 제거


if __name__ == "__main__":
    main()
