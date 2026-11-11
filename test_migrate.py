"""python test_migrate.py 로 실행 (프레임워크 불필요, pytest 로도 동작)."""
import os
import tempfile
from datetime import datetime

from migrate import convert, parse_mapping, to_strptime


def test_to_strptime():
  assert to_strptime('YYYYMMDD') == '%Y%m%d'
  assert to_strptime('YYYY-MM-DD HH24:MI:SS') == '%Y-%m-%d %H:%M:%S'


def test_convert():
  dateCols = [(1, '%Y%m%d')]
  assert convert(('a', '20240131'), dateCols) == ('a', datetime(2024, 1, 31))
  assert convert(('a', '  '), dateCols) == ('a', None)  # 공백은 NULL
  assert convert(('a', None), dateCols) == ('a', None)
  try:
    convert(('a', '20241301'), dateCols)  # 13월
    assert False, 'ValueError 가 나야 함'
  except ValueError:
    pass


def test_parse_mapping():
  text = '# 주석\nOLD_TB -> NEW_TB\nNM -> NAME\nREG_DT -> CREATED_AT | DATE YYYYMMDD\n'
  with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8') as f:
    f.write(text)
  try:
    assert parse_mapping(f.name) == (
      'OLD_TB', 'NEW_TB', [('NM', 'NAME', None), ('REG_DT', 'CREATED_AT', '%Y%m%d')])
  finally:
    os.unlink(f.name)


def test_bad_identifier():
  with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8') as f:
    f.write('A -> B; DROP TABLE X\nC -> D\n')
  try:
    parse_mapping(f.name)
    assert False, 'ValueError 가 나야 함'
  except ValueError:
    pass
  finally:
    os.unlink(f.name)


if __name__ == '__main__':
  for name, fn in list(globals().items()):
    if name.startswith('test_'):
      fn()
  print('OK')
