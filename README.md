# Miniroom

싸이월드의 개인 공간 감성을 현대적으로 재해석한 Flask 기반 미니홈피형 SNS입니다.

## 기능

- 회원가입과 안전한 비밀번호 해시
- TOTP 기반 OTP 2차 인증
- 사용자별 미니홈피, 상태메시지, 소개
- 게시글 작성·조회·수정·삭제와 댓글
- 공개/비밀 방명록
- 일별·누적 방문자 수와 이웃 탐색
- 반응형 복고풍 UI
- 전 요청 CSRF 검증과 보안 응답 헤더
- 암호화된 TOTP 비밀키와 OTP 재사용 차단
- 로그인·OTP·가입 시도 제한
- 현재 비밀번호+OTP 기반 비밀번호 변경
- 일회용 복구 코드 기반 비밀번호 재설정 및 기존 세션 무효화
- 세션 만료와 안전한 쿠키 정책
- 이미지 실내용 검증, 크기 제한, 재인코딩

## 실행

### 일반적인 Python 실행 방법

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

브라우저에서 `http://127.0.0.1:5000`으로 접속합니다. 회원가입 시 Google Authenticator, Microsoft Authenticator 등 TOTP 앱이 필요합니다.

로컬 실행용 보안키는 최초 실행 때 `instance/local-secrets.json`에 무작위로 생성되며 Git에서 제외됩니다. 이 파일을 잃으면 기존 OTP 비밀키를 복호화할 수 없으므로 백업에 포함해야 합니다.

## Docker 실행

Docker Desktop을 설치한 뒤 Docker Compose로 빌드하고 실행합니다.

```bash
docker compose up --build -d
```

웹사이트는 `http://localhost:8000`, 상태 확인은 `/healthz`에서 가능합니다.
회원 데이터와 업로드 사진은 각각 `miniroom-db`, `miniroom-uploads` Docker 볼륨에
보존됩니다. 중지는 `docker compose down`, 재실행은 `docker compose up -d`를
사용합니다. 데이터를 유지하려면 `docker compose down -v`는 사용하지 않습니다.

모든 소스 파일과 Linux 컨테이너의 로케일, Python 입출력 및 HTTP 텍스트 응답은
UTF-8로 고정되어 있습니다.

컨테이너를 처음 시작할 때 `openssl`이 Flask 세션 키와 TOTP 암호화 키를 자동으로
생성합니다. 키는 이미지나 저장소가 아닌 `miniroom-db` 볼륨의 `runtime-secrets`
파일에 권한 `600`으로 보관되므로 컨테이너를 다시 만들어도 유지됩니다.

기본 Compose 설정은 `http://localhost:8000` 로컬 접속을 위해 `COOKIE_SECURE=0`을
사용합니다. HTTPS 프록시 뒤에 배포할 때는 반드시 `COOKIE_SECURE=1`로 변경합니다.
- TLS를 종료하는 Nginx/ALB 뒤에서 Gunicorn을 실행하고 HTTP를 HTTPS로 강제 전환해야 합니다.
- 다중 서버 환경에서는 SQLite 대신 관리형 PostgreSQL로 마이그레이션하고 인증 시도 제한 저장소도 공유해야 합니다.
- 다중 서버 운영에서는 자동 생성 파일 대신 AWS Secrets Manager 등의 비밀 저장소를 사용해야 합니다.
