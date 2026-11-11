# 환경변수 (DB 접속 정보)

`migrate.py`는 아래 6개 환경변수로 as-is / to-be Oracle에 접속한다.

## as-is (읽기)

| 키 | 의미 | 예 |
|---|---|---|
| `SRC_USER` | 계정 | `as_is_user` |
| `SRC_PASSWORD` | 비밀번호 | |
| `SRC_DSN` | 접속 주소 | `10.0.0.1:1521/ASISDB` |

## to-be (쓰기, TRUNCATE 대상)

| 키 | 의미 | 예 |
|---|---|---|
| `DST_USER` | 계정 | `to_be_user` |
| `DST_PASSWORD` | 비밀번호 | |
| `DST_DSN` | 접속 주소 | `10.0.0.2:1521/TOBEDB` |

## DSN 형식

`호스트:포트/서비스명`

- SID로 접속하는 서버는 서비스명이 달라 `ORA-12514`가 날 수 있다. DBA에게 서비스명을 확인한다.
- `DST_*`가 가리키는 DB에서 `TRUNCATE`가 실행된다. 실행 전 확인 프롬프트에서 접속 대상을 꼭 확인한다.

## 적용 방법

```bash
cp .env.sample .env          # 값 수정
set -a; source .env; set +a  # 환경변수 적용
python migrate.py mapping.txt
```

`.env`에는 비밀번호가 들어간다. git으로 관리할 경우 `.gitignore`에 `.env`를 추가한다.
