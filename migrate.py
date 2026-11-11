"""Oracle -> Oracle 테이블 1개 이관 (TRUNCATE 후 재적재).

사용: python migrate.py mapping.txt [--yes]
환경변수: SRC_USER SRC_PASSWORD SRC_DSN DST_USER DST_PASSWORD DST_DSN
  예) set -a; source .env; set +a
"""
import argparse
import os
import re
import sys
from datetime import datetime

BATCH = 5000  # 한 번에 읽고 넣는 건수
IDENT = re.compile(r'^[A-Za-z_][\w$#]*(\.[A-Za-z_][\w$#]*)?$')
# Oracle 날짜 포맷 -> strptime 포맷 (치환 순서 중요)
FMT_MAP = [('YYYY', '%Y'), ('HH24', '%H'), ('MM', '%m'), ('DD', '%d'), ('MI', '%M'), ('SS', '%S')]


def to_strptime(fmt):
  for oracleToken, pyToken in FMT_MAP:
    fmt = fmt.replace(oracleToken, pyToken)
  return fmt


def parse_mapping(path):
  """첫 줄: AS_IS_TABLE -> TO_BE_TABLE, 이후: AS_IS_COL -> TO_BE_COL [| DATE 포맷]"""
  with open(path, encoding='utf-8-sig') as f:
    lines = [l.strip() for l in f if l.strip() and not l.strip().startswith('#')]
  if len(lines) < 2:
    raise ValueError('매핑 파일에 테이블 줄과 컬럼 줄이 필요합니다')
  srcTable, dstTable = [x.strip() for x in lines[0].split('->')]
  cols = []
  for line in lines[1:]:
    names, _, conv = line.partition('|')
    srcCol, dstCol = [x.strip() for x in names.split('->')]
    pyFmt = None
    if conv.strip():
      pyFmt = to_strptime(conv.split(None, 1)[1].strip())  # 첫 토큰(DATE)은 무시
    cols.append((srcCol, dstCol, pyFmt))
  for name in [srcTable, dstTable] + [c[0] for c in cols] + [c[1] for c in cols]:
    if not IDENT.match(name):
      raise ValueError(f'허용되지 않는 식별자: {name!r}')
  return srcTable, dstTable, cols


def convert(row, dateCols):
  """dateCols: [(인덱스, strptime 포맷)]. 빈 문자열은 NULL, 파싱 실패는 ValueError."""
  out = list(row)
  for i, fmt in dateCols:
    v = out[i]
    if isinstance(v, str):
      v = v.strip()
      out[i] = datetime.strptime(v, fmt) if v else None
  return tuple(out)


def env(name):
  v = os.environ.get(name)
  if not v:
    sys.exit(f'환경변수 {name} 가 없습니다')
  return v


def main():
  import oracledb  # 테스트에서 드라이버 없이 import 가능하도록 지연 import

  ap = argparse.ArgumentParser()
  ap.add_argument('mapping')
  ap.add_argument('--yes', action='store_true', help='TRUNCATE 확인 생략')
  args = ap.parse_args()

  srcTable, dstTable, cols = parse_mapping(args.mapping)
  dateCols = [(i, c[2]) for i, c in enumerate(cols) if c[2]]
  oracledb.defaults.fetch_lobs = False  # CLOB/BLOB 을 str/bytes 로 바로 받음

  src = oracledb.connect(user=env('SRC_USER'), password=env('SRC_PASSWORD'), dsn=env('SRC_DSN'))
  dst = oracledb.connect(user=env('DST_USER'), password=env('DST_PASSWORD'), dsn=env('DST_DSN'))

  if not args.yes:
    ans = input(f'[{env("DST_DSN")}] {dstTable} 을 TRUNCATE 합니다 (되돌릴 수 없음). 계속? (y/N) ')
    if ans.strip().lower() != 'y':
      return

  sc, dc = src.cursor(), dst.cursor()
  dc.execute(f'TRUNCATE TABLE {dstTable}')

  sc.arraysize = BATCH
  sc.execute(f'SELECT {", ".join(c[0] for c in cols)} FROM {srcTable}')
  insertSql = (f'INSERT INTO {dstTable} ({", ".join(c[1] for c in cols)}) '
               f'VALUES ({", ".join(f":{i + 1}" for i in range(len(cols)))})')

  read = inserted = rejected = 0
  with open(f'reject_{dstTable.replace(".", "_")}.log', 'w', encoding='utf-8') as rej:
    while rows := sc.fetchmany(BATCH):
      good = []
      for r in rows:
        try:
          good.append(convert(r, dateCols))
        except ValueError as e:
          rejected += 1
          rej.write(f'변환실패\t{e}\t{r}\n')
      if good:
        dc.executemany(insertSql, good, batcherrors=True)
        errors = dc.getbatcherrors()
        for e in errors:
          rej.write(f'적재실패\t{e.message.strip()}\t{good[e.offset]}\n')
        rejected += len(errors)
        inserted += len(good) - len(errors)
      dst.commit()  # batcherrors 사용 시 명시적 commit 필수
      read += len(rows)
      print(f'진행: 읽음 {read} / 적재 {inserted} / 실패 {rejected}', flush=True)

  sc.execute(f'SELECT COUNT(*) FROM {srcTable}')
  srcCount = sc.fetchone()[0]
  dc.execute(f'SELECT COUNT(*) FROM {dstTable}')
  dstCount = dc.fetchone()[0]
  ok = srcCount == dstCount + rejected
  print(f'as-is {srcCount} / to-be {dstCount} / 실패 {rejected} -> {"일치" if ok else "불일치, 확인 필요"}')
  if rejected:
    print('실패 행은 reject_*.log 확인')


if __name__ == '__main__':
  main()
