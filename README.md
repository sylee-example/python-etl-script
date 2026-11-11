# Oracle 데이터 이관 (as-is -> to-be)

Oracle 서버 간 테이블 데이터를 이관하는 Python 스크립트.
테이블명과 필드명이 바뀐 경우를 매핑 파일로 처리하고, 테이블을 지정해서 하나씩 실행한다.

## 파일 구성

| 파일 | 설명 |
|---|---|
| `migrate.py` | 이관 본체 |
| `test_migrate.py` | 매핑 파싱, 날짜 변환 테스트 |
| `mapping.sample.txt` | 매핑 파일 샘플 (복사해서 사용) |
| `.env.sample` | 접속 정보 샘플 (복사해서 `.env`로 사용) |
| `ENV_KEYS.md` | 환경변수 키 설명 |

## 준비

```bash
pip install oracledb          # Oracle Client 설치 불필요 (thin 모드)

cp .env.sample .env           # 접속 정보 수정 (키 설명: ENV_KEYS.md)
cp mapping.sample.txt mapping.txt   # 실제 매핑으로 교체
```

## 실행

```bash
set -a; source .env; set +a                          # 환경변수 적용

python migrate.py mapping.txt --list                 # 매핑 파일의 TO-BE 테이블 목록
python migrate.py mapping.txt NEW_USER --dry-run     # DB 접속 없이 SQL만 확인
python migrate.py mapping.txt NEW_USER               # 지정한 테이블 이관
python migrate.py mapping.txt NEW_USER NEW_ORDER     # 여러 개 지정도 가능
```

| 옵션 | 설명 |
|---|---|
| `--list` | 매핑 파일의 TO-BE 테이블 목록 출력 |
| `--dry-run` | DB 접속 없이 SELECT/INSERT 문만 출력 |
| `--yes` | TRUNCATE 확인 프롬프트 생략 |

- 테이블명을 지정하지 않으면 실행하지 않는다. 전체 테이블을 실수로 TRUNCATE하는 것을 막기 위해서다.
- 테이블명은 대소문자를 구분하지 않는다.
- 사내망에서는 먼저 `--dry-run`으로 SQL이 의도대로 나오는지 확인한 뒤 실행한다.

## 매핑 파일 형식

콤마 구분 텍스트 파일. 첫 줄 헤더(`TO-BE`가 들어간 줄)는 자동으로 건너뛴다.
UTF-8과 CP949를 모두 읽는다.

```
테이블명(TO-BE),필드명(TO-BE),속성명,데이터타입,길이,테이블명(AS-IS),필드명(AS-IS)
NEW_USER_TABLE,USER_ID,사용자ID,VARCHAR2,20,OLD_USER_TB,USER_ID
NEW_USER_TABLE,CREATED_AT,등록일,DATE,,OLD_USER_TB,REG_DT
NEW_USER_TABLE,USE_YN,사용여부,CHAR,1,,
```

- `속성명`, `길이`는 읽기만 하고 사용하지 않는다.
- AS-IS 테이블이나 필드가 비어 있는 행(신규 컬럼)은 적재에서 제외하고 경고를 출력한다. 해당 컬럼이 NOT NULL이면 INSERT가 실패한다.
- 한 TO-BE 테이블에 AS-IS 테이블이 둘 이상이면 에러로 멈춘다. 1:1 이관만 지원한다.
- 테이블명과 필드명은 영문, 숫자, `_`, `$`, `#`만 허용한다(`스키마.테이블` 가능).

## 동작 방식

1. 지정한 TO-BE 테이블을 `TRUNCATE`한다 (실행 전 확인 프롬프트, 되돌릴 수 없음).
2. as-is에서 5000건씩 읽어 to-be에 `INSERT`하고 배치마다 `COMMIT`한다.
3. 끝나면 `as-is 건수 = to-be 건수 + 실패 건수`인지 비교해서 출력한다.

재실행하면 TRUNCATE 후 처음부터 다시 적재한다.

### 날짜 변환

TO-BE 데이터타입이 `DATE`, `DATETIME`, `TIMESTAMP`로 시작하면 as-is 문자열을 값 모양으로 자동 인식해서 변환한다.

| as-is 값 | 변환 |
|---|---|
| `20240131` (8자리) | `YYYYMMDD` |
| `202401311230` (12자리) | `YYYYMMDDHH24MI` |
| `20240131123045` (14자리) | `YYYYMMDDHH24MISS` |
| `2024-01-31`, `2024/01/31`, `2024.01.31` | 날짜 |
| `2024-01-31 12:30:45` 등 | 날짜 + 시간 |
| 빈 문자열, 공백 | `NULL` |

위 형식이 아닌 값(7자리, `00000000`, 13월 등)은 그 행만 실패 처리된다.

### 실패 행 처리

한 행 때문에 전체가 멈추지 않는다. 실패한 행은 건너뛰고 `reject_<TO-BE테이블>.log`에 남긴다.

- `변환실패`: 날짜 형식을 인식하지 못한 경우
- `적재실패`: INSERT 오류. 예) 길이 초과 `ORA-12899`, 제약조건 위반

## 주의

- `TRUNCATE`는 되돌릴 수 없다. 확인 프롬프트에 표시되는 `DST_DSN`이 이관 대상 DB가 맞는지 꼭 확인한다.
- to-be 테이블을 참조하는 FK가 있으면 `TRUNCATE`가 `ORA-02266`으로 실패한다.
- `.env`에는 비밀번호가 들어간다. git으로 관리할 경우 `.gitignore`에 추가한다.
- CLOB/BLOB은 문자열/바이트로 읽는다. 매우 큰 LOB은 메모리를 많이 쓸 수 있다.

## 테스트

```bash
python test_migrate.py        # 출력: OK
```

DB 접속 없이 매핑 파싱, 날짜 변환, SQL 생성만 검증한다. TRUNCATE, 적재, 건수 비교는 DB가 있는 환경에서 확인해야 한다.
