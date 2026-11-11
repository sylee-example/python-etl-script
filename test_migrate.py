"""python test_migrate.py 로 실행 (프레임워크 불필요, pytest 로도 동작)."""
import os
import tempfile
from datetime import datetime

from migrate import build_sql, convert, parse_date, parse_mapping

HEADER = '테이블명(TO-BE),필드명(TO-BE),속성명,데이터타입,길이,테이블명(AS-IS),필드명(AS-IS)\n'


def write_csv(text, encoding='utf-8'):
  f = tempfile.NamedTemporaryFile('wb', suffix='.txt', delete=False)
  f.write(text.encode(encoding))
  f.close()
  return f.name


def raises(fn, exc=ValueError):
  try:
    fn()
  except exc:
    return True
  return False


def test_parse_date():
  assert parse_date('20240131') == datetime(2024, 1, 31)
  assert parse_date('20240131123045') == datetime(2024, 1, 31, 12, 30, 45)
  assert parse_date('202401311230') == datetime(2024, 1, 31, 12, 30)  # 12자리는 시:분까지
  assert parse_date('2024-01-31') == datetime(2024, 1, 31)
  assert parse_date('2024-01-31 12:30:45') == datetime(2024, 1, 31, 12, 30, 45)
  assert parse_date('2024/01/31') == datetime(2024, 1, 31)
  assert parse_date('2024.01.31') == datetime(2024, 1, 31)
  assert raises(lambda: parse_date('2024011'))      # 7자리: 느슨하게 파싱되면 안 됨
  assert raises(lambda: parse_date('20241301'))     # 13월
  assert raises(lambda: parse_date('00000000'))
  assert raises(lambda: parse_date('abc'))


def test_convert():
  assert convert(('a', '20240131'), [1]) == ('a', datetime(2024, 1, 31))
  assert convert(('a', '  '), [1]) == ('a', None)  # 공백은 NULL
  assert convert(('a', None), [1]) == ('a', None)
  d = datetime(2024, 1, 31)
  assert convert(('a', d), [1]) == ('a', d)        # 이미 날짜면 그대로
  assert convert(('a', 'x'), []) == ('a', 'x')     # 변환 대상 아님


def test_parse_mapping():
  path = write_csv(
    HEADER +
    'NEW_USER,USER_ID,아이디,VARCHAR2,20,OLD_USER,USER_ID\n'
    'NEW_USER,CREATED_AT,등록일,DATE,,OLD_USER,REG_DT\n'
    'NEW_USER,UPDATED_AT,수정일시,TIMESTAMP(6),,OLD_USER,UPD_DTM\n'
    'NEW_USER,NEW_FLAG,신규,CHAR,1,,\n'
    ',,,,,,\n'
    'NEW_ORDER,ORDER_NO,주문번호,NUMBER,10,OLD_ORDER,ORD_NO\n')
  try:
    m = parse_mapping(path)
  finally:
    os.unlink(path)
  assert list(m) == ['NEW_USER', 'NEW_ORDER']
  dst, src, cols, skipped = m['NEW_USER']
  assert (dst, src) == ('NEW_USER', 'OLD_USER')
  assert cols == [('USER_ID', 'USER_ID', False), ('REG_DT', 'CREATED_AT', True), ('UPD_DTM', 'UPDATED_AT', True)]
  assert skipped == ['NEW_FLAG']


def test_parse_mapping_cp949():
  path = write_csv(HEADER + 'NEW_T,C1,한글속성,VARCHAR2,10,OLD_T,C1\n', encoding='cp949')
  try:
    assert 'NEW_T' in parse_mapping(path)
  finally:
    os.unlink(path)


def test_parse_mapping_errors():
  bad = write_csv(HEADER + 'A,B,x,VARCHAR2,1,C;DROP TABLE X,D\n')
  multi = write_csv(HEADER + 'A,B,x,VARCHAR2,1,T1,D\nA,C,x,VARCHAR2,1,T2,E\n')
  try:
    assert raises(lambda: parse_mapping(bad))
    assert raises(lambda: parse_mapping(multi))  # AS-IS 테이블 2개
  finally:
    os.unlink(bad)
    os.unlink(multi)


def test_build_sql():
  select, insert = build_sql('NEW_T', 'OLD_T', [('A1', 'B1', False), ('A2', 'B2', True)])
  assert select == 'SELECT A1, A2 FROM OLD_T'
  assert insert == 'INSERT INTO NEW_T (B1, B2) VALUES (:1, :2)'


if __name__ == '__main__':
  for name, fn in list(globals().items()):
    if name.startswith('test_'):
      fn()
  print('OK')
