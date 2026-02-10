# 🎵 라디오 플리 (Radio Playlist)

한국 라디오 선곡표를 **Spotify 플레이리스트**로 자동 변환하는 웹 서비스입니다.

## 지원 프로그램

| DJ | 프로그램 | 방송국 |
|---|---|---|
| 이상순 | 이상순의 음악도시 | MBC FM4U |
| 윤상 | 배철수의 음악캠프 | MBC FM4U |
| 이현우 | 이현우의 음악앨범 | KBS Cool FM |
| 전기현 | 세상의 모든 음악 | KBS Classic FM |

## 사용 방법

1. **Spotify 로그인** — 웹 사이트에서 Spotify 계정으로 로그인
2. **프로그램 구독** — 원하는 라디오 프로그램을 선택
3. **자동 플레이리스트** — 매일 밤 9시 새 플레이리스트가 Spotify에 생성됨

## 기술 스택

- **Backend**: Flask, SQLAlchemy, APScheduler
- **Frontend**: Jinja2, Vanilla JS, CSS (Spotify 다크 테마)
- **DB**: SQLite (개발) / PostgreSQL (프로덕션)
- **배포**: Render.com

## 로컬 개발 환경 설정

### 1. Spotify Developer App 생성

[Spotify Developer Dashboard](https://developer.spotify.com/dashboard)에서 앱을 생성하고 `Client ID`와 `Client Secret`을 받으세요.

Redirect URI에 `http://localhost:5000/auth/callback`을 추가하세요.

### 2. 환경변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 열고 다음 값을 채우세요:

```
SPOTIFY_CLIENT_ID=여기에-클라이언트-아이디
SPOTIFY_CLIENT_SECRET=여기에-클라이언트-시크릿
```

암호화 키 생성:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

출력된 키를 `.env`의 `ENCRYPTION_KEY`에 붙여넣으세요.

### 3. 의존성 설치 및 실행

```bash
pip3 install -r requirements.txt
python3 wsgi.py
```

`http://localhost:5000`에서 확인하세요.

## Render.com 배포

### 1. GitHub에 코드 Push

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/korean-radio-spotify.git
git push -u origin main
```

### 2. Render에서 배포

1. [Render Dashboard](https://dashboard.render.com)에서 **New Web Service** 클릭
2. GitHub 저장소 연결
3. 환경변수 설정:
   - `SPOTIFY_CLIENT_ID`
   - `SPOTIFY_CLIENT_SECRET`
   - `ENCRYPTION_KEY` (위에서 생성한 키)
   - `SECRET_KEY` (임의의 긴 문자열)
   - `FLASK_ENV` = `production`
   - `SPOTIFY_REDIRECT_URI` = `https://your-app.onrender.com/auth/callback`
4. **PostgreSQL** 데이터베이스 추가 (Render에서 무료 제공)
5. `DATABASE_URL`은 Render가 자동으로 설정

### 3. Spotify Redirect URI 업데이트

Spotify Developer Dashboard에서 Redirect URI를 배포된 URL로 변경:

```
https://your-app.onrender.com/auth/callback
```

## 프로젝트 구조

```
korean-radio-spotify/
├── app/
│   ├── __init__.py          # Flask 앱 팩토리 + 프로그램 설정
│   ├── config.py            # 환경별 설정
│   ├── models.py            # DB 모델 (User, UserProgram, UserPlaylist, SongCache)
│   ├── radio_scraper.py     # 선곡표 스크래핑 (MBC, KBS, KBS Board)
│   ├── spotify_client.py    # Spotify API 래퍼 (3단계 검색)
│   ├── jobs.py              # 매일 자동 플레이리스트 생성 작업
│   ├── blueprints/
│   │   ├── auth.py          # Spotify OAuth 인증
│   │   ├── routes.py        # 메인 페이지 라우트
│   │   └── api.py           # JSON API 엔드포인트
│   ├── templates/           # Jinja2 HTML 템플릿
│   └── static/              # CSS 스타일
├── wsgi.py                  # Gunicorn 진입점
├── Procfile                 # Render 배포용
├── render.yaml              # Render 자동 배포 설정
├── requirements.txt         # Python 의존성
└── .env.example             # 환경변수 템플릿
```

## API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/` | 랜딩 페이지 |
| GET | `/dashboard` | 대시보드 (로그인 필요) |
| GET | `/admin` | 관리자 페이지 |
| GET | `/auth/spotify` | Spotify OAuth 시작 |
| GET | `/auth/callback` | OAuth 콜백 |
| GET | `/auth/logout` | 로그아웃 |
| GET | `/api/programs/status` | 프로그램 목록 + 구독 상태 |
| POST | `/api/programs/follow` | 프로그램 구독 |
| POST | `/api/programs/unfollow` | 프로그램 구독 취소 |
| GET | `/api/playlists` | 최근 플레이리스트 |
| POST | `/api/playlists/create-now` | 즉시 플레이리스트 생성 |

## 라이선스

이 프로젝트는 개인 학습 및 라디오 애호가들을 위해 만들어졌습니다.
