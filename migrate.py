"""Oracle -> Oracle 테이블 이관 (TRUNCATE 후 재적재).

사용:
  python migrate.py mapping.txt --list                  # 매핑 파일의 TO-BE 테이블 목록
  python migrate.py mapping.txt TB_USER --dry-run       # DB 접속 없이 SQL 만 확인
  python migrate.py mapping.txt TB_USER [TB_ORDER ...]  # 지정한 TO-BE 테이블만 이관
  (--yes: TRUNCATE 확인 생략)

매핑 텍스트 파일(콤마 구분) 컬럼 순서 (첫 줄 헤더는 자동 제외):
  테이블명(TO-BE),필드명(TO-BE),속성명,데이터타입,길이,테이블명(AS-IS),필드명(AS-IS)

환경변수: SRC_USER SRC_PASSWORD SRC_DSN DST_USER DST_PASSWORD DST_DSN (ENV_KEYS.md 참고)
"""
import argparse
import csv
import io
import os
import re
import sys
from datetime import datetime

BATCH = 5000  # 한 번에 읽고 넣는 건수
IDENT = re.compile(r'^[A-Za-z_][\w$#]*(\.[A-Za-z_][\w$#]*)?$')
DATE_TYPE = re.compile(r'^(DATE|DATETIME|TIMESTAMP)')  # TO-BE 데이터타입이 이걸로 시작하면 날짜 변환
# 숫자만 있는 날짜 문자열: 자리수로 포맷 결정 (strptime 이 짧은 값을 느슨하게 받아들이는 것 방지)
DIGIT_FORMATS = {8: '%Y%m%d', 12: '%Y%m%d%H%M', 14: '%Y%m%d%H%M%S'}
SEP_FORMATS = ['%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M',
               '%Y/%m/%d', '%Y/%m/%d %H:%M:%S', '%Y.%m.%d', '%Y.%m.%d %H:%M:%S']


def parse_date(s):
  """as-is 문자열 날짜를 datetime 으로. 인식 못 하면 ValueError."""
  if s.isdigit():
    if len(s) not in DIGIT_FORMATS:
      raise ValueError(f'날짜 자리수 오류: {s!r}')
    return datetime.strptime(s, DIGIT_FORMATS[len(s)])
  for fmt in SEP_FORMATS:
    try:
      return datetime.strptime(s, fmt)
    except ValueError:
      pass
  raise ValueError(f'날짜 형식 인식 불가: {s!r}')


def convert(row, dateIdx):
  """dateIdx 위치의 문자열을 datetime 으로 변환. 빈 문자열은 NULL."""
  out = list(row)
  for i in dateIdx:
    v = out[i]
    if isinstance(v, str):
      v = v.strip()
      out[i] = parse_date(v) if v else None
  return tuple(out)


def read_text(path):
  """엑셀 CSV 는 CP949 인 경우가 많아 UTF-8 실패 시 CP949 로 읽는다."""
  with open(path, 'rb') as f:
    raw = f.read()
  try:
    return raw.decode('utf-8-sig')
  except UnicodeDecodeError:
    return raw.decode('cp949')


def parse_mapping(path):
  """반환: {TO-BE 테이블(대문자): (dstTable, srcTable, cols, skipped)}
  cols = [(srcCol, dstCol, isDate)], skipped = AS-IS 매핑이 없어 적재 제외되는 TO-BE 컬럼"""
  tables = {}
  for n, row in enumerate(csv.reader(io.StringIO(read_text(path))), 1):
    row = [c.strip() for c in row] + [''] * 7
    dstTable, dstCol, _attr, dtype, _length, srcTable, srcCol = row[:7]
    if not dstTable or (n == 1 and 'TO-BE' in dstTable.upper()):
      continue  # 빈 줄, 헤더
    used = [dstTable, dstCol] + ([srcTable, srcCol] if srcTable and srcCol else [])
    for name in used:
      if not IDENT.match(name):
        raise ValueError(f'{n}번째 줄: 허용되지 않는 식별자 {name!r}')
    t = tables.setdefault(dstTable.upper(), {'dst': dstTable, 'src': set(), 'cols': [], 'skipped': []})
    if srcTable and srcCol:
      t['src'].add(srcTable)
      t['cols'].append((srcCol, dstCol, bool(DATE_TYPE.match(dtype.upper()))))
    else:
      t['skipped'].append(dstCol)

  result = {}
  for key, t in tables.items():
    if not t['cols']:
      raise ValueError(f'{t["dst"]}: AS-IS 매핑된 컬럼이 없습니다')
    if len(t['src']) != 1:
      raise ValueError(f'{t["dst"]}: AS-IS 테이블이 {len(t["src"])}개입니다 ({sorted(t["src"])}), 1개만 지원')
    result[key] = (t['dst'], next(iter(t['src'])), t['cols'], t['skipped'])
  return result


def build_sql(dstTable, srcTable, cols):
  select = f'SELECT {", ".join(c[0] for c in cols)} FROM {srcTable}'
  insert = (f'INSERT INTO {dstTable} ({", ".join(c[1] for c in cols)}) '
            f'VALUES ({", ".join(f":{i + 1}" for i in range(len(cols)))})')
  return select, insert


def env(name):
  v = os.environ.get(name)
  if not v:
    sys.exit(f'환경변수 {name} 가 없습니다')
  return v


def migrate_table(src, dst, dstTable, srcTable, cols):
  selectSql, insertSql = build_sql(dstTable, srcTable, cols)
  dateIdx = [i for i, c in enumerate(cols) if c[2]]
  sc, dc = src.cursor(), dst.cursor()

  dc.execute(f'TRUNCATE TABLE {dstTable}')
  sc.arraysize = BATCH
  sc.execute(selectSql)

  read = inserted = rejected = 0
  with open(f'reject_{dstTable.replace(".", "_")}.log', 'w', encoding='utf-8') as rej:
    while rows := sc.fetchmany(BATCH):
      good = []
      for r in rows:
        try:
          good.append(convert(r, dateIdx))
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
      print(f'  진행: 읽음 {read} / 적재 {inserted} / 실패 {rejected}', flush=True)

  sc.execute(f'SELECT COUNT(*) FROM {srcTable}')
  srcCount = sc.fetchone()[0]
  dc.execute(f'SELECT COUNT(*) FROM {dstTable}')
  dstCount = dc.fetchone()[0]
  ok = srcCount == dstCount + rejected
  print(f'  as-is {srcCount} / to-be {dstCount} / 실패 {rejected} -> {"일치" if ok else "불일치, 확인 필요"}')
  if rejected:
    print(f'  실패 행은 reject_{dstTable.replace(".", "_")}.log 확인')


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument('mapping')
  ap.add_argument('tables', nargs='*', help='이관할 TO-BE 테이블명 (여러 개 가능)')
  ap.add_argument('--list', action='store_true', help='매핑 파일의 TO-BE 테이블 목록 출력')
  ap.add_argument('--dry-run', action='store_true', help='DB 접속 없이 SQL 만 출력')
  ap.add_argument('--yes', action='store_true', help='TRUNCATE 확인 생략')
  args = ap.parse_args()

  mapping = parse_mapping(args.mapping)
  if args.list:
    for t in mapping.values():
      print(f'{t[0]}  <-  {t[1]}  (컬럼 {len(t[2])}개, 제외 {len(t[3])}개)')
    return
  if not args.tables:
    sys.exit('이관할 TO-BE 테이블명을 지정하세요 (--list 로 목록 확인)')
  unknown = [t for t in args.tables if t.upper() not in mapping]
  if unknown:
    sys.exit(f'매핑 파일에 없는 테이블: {unknown} (--list 로 목록 확인)')
  targets = [mapping[t.upper()] for t in args.tables]

  for dstTable, srcTable, cols, skipped in targets:
    if skipped:
      print(f'[경고] {dstTable}: AS-IS 매핑 없는 컬럼 {skipped} 은 적재 제외 (NOT NULL 이면 실패)')
  if args.dry_run:
    for dstTable, srcTable, cols, _ in targets:
      selectSql, insertSql = build_sql(dstTable, srcTable, cols)
      print(f'\n-- {srcTable} -> {dstTable}\n{selectSql}\n{insertSql}')
      print(f'-- 날짜 변환 컬럼: {[c[0] for c in cols if c[2]]}')
    return

  import oracledb  # 테스트/dry-run 에서 드라이버 없이 동작하도록 지연 import
  oracledb.defaults.fetch_lobs = False  # CLOB/BLOB 을 str/bytes 로 바로 받음
  src = oracledb.connect(user=env('SRC_USER'), password=env('SRC_PASSWORD'), dsn=env('SRC_DSN'))
  dst = oracledb.connect(user=env('DST_USER'), password=env('DST_PASSWORD'), dsn=env('DST_DSN'))

  if not args.yes:
    names = ', '.join(t[0] for t in targets)
    ans = input(f'[{env("DST_DSN")}] {names} 을 TRUNCATE 합니다 (되돌릴 수 없음). 계속? (y/N) ')
    if ans.strip().lower() != 'y':
      return

  for dstTable, srcTable, cols, _ in targets:
    print(f'\n[{srcTable} -> {dstTable}]')
    migrate_table(src, dst, dstTable, srcTable, cols)


if __name__ == '__main__':
  main()
