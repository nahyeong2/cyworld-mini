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

### 가장 간단한 실행 방법

`start-site.bat`을 더블클릭합니다. 서버 창을 닫으면 사이트도 종료됩니다.

### 일반적인 Python 실행 방법

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

브라우저에서 `http://127.0.0.1:5000`으로 접속합니다. 회원가입 시 Google Authenticator, Microsoft Authenticator 등 TOTP 앱이 필요합니다.

로컬 실행용 보안키는 최초 실행 때 `instance/local-secrets.json`에 무작위로 생성되며 Git에서 제외됩니다. 이 파일을 잃으면 기존 OTP 비밀키를 복호화할 수 없으므로 백업에 포함해야 합니다.

## 운영 배포

- `APP_ENV=production`, `SECRET_KEY`, `TOTP_ENCRYPTION_KEY`가 모두 필요합니다. 누락되면 서버가 의도적으로 실행되지 않습니다.
- `SECRET_KEY`는 최소 64바이트 무작위 값, `TOTP_ENCRYPTION_KEY`는 Fernet 키를 사용합니다.
- TLS를 종료하는 Nginx/ALB 뒤에서 Gunicorn을 실행하고 HTTP를 HTTPS로 강제 전환해야 합니다.
- 다중 서버 환경에서는 SQLite 대신 관리형 PostgreSQL로 마이그레이션하고 인증 시도 제한 저장소도 공유해야 합니다.
- 운영 비밀키는 소스나 이미지에 넣지 말고 AWS Secrets Manager 등의 비밀 저장소에서 주입합니다.

키 생성 예시:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(64))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
