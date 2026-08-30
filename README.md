# Xync

Linux 미러 저장소를 동기화하고 관리하는 CLI 도구입니다.

`xync`는 `rsync`, `wget` 기반 미러링을 설정 파일로 관리하고, 상태 확인·로그 조회·데몬 실행·REST API·Telegram/Discord 알림까지 제공합니다.

> [!NOTE]
> Built with Python · [uv](https://docs.astral.sh/uv/) · [Typer](https://typer.tiangolo.com/) · [Rich](https://rich.readthedocs.io/)

---

## 주요 기능

- **rsync 미러 동기화**: `rsync://` 소스 동기화, 옵션 커스터마이징, 대역폭 제한 지원
- **HTTP/HTTPS/FTP 미러 동기화**: `wget` 기반 미러링 지원
- **미러 변경 미리보기**: `xync mirror diff`로 `rsync --dry-run --itemize-changes` 결과 확인
- **병렬 동기화**: `parallel_jobs` 설정으로 여러 미러를 동시에 동기화
- **백그라운드 데몬**: interval 또는 cron schedule 기반 자동 동기화
- **REST API**: 미러 목록, 상태, 크기 정보를 HTTP API로 조회
- **알림**: Telegram Bot API, Discord Webhook 알림 지원
- **상태/로그 관리**: 마지막 동기화 상태, 크기 변화, 실행 로그 조회
- **헬스 체크**: 필수 도구, 경로 권한, URL 스킴, 디스크 사용률 검사
- **Rich CLI 출력**: 테이블, 색상, 상태 표시를 활용한 읽기 쉬운 출력

---

## 요구 사항

### 런타임

- Linux 환경
<!--- Python `>= 3.11`-->
- [`uv`](https://docs.astral.sh/uv/) 패키지/툴 매니저
- `rsync` — rsync 미러 사용 시 필요
- `wget` — HTTP/HTTPS/FTP 미러 사용 시 필요

---

## 설치

### 권장: uv tool로 설치

```bash
uv tool install xync
xync --help
```

업데이트:

```bash
uv tool upgrade xync
```

제거:

```bash
uv tool uninstall xync
```

> [!TIP]
> `uv tool install`은 CLI 애플리케이션을 격리된 환경에 설치하고 실행 파일을 PATH에 노출합니다. PATH 설정이 필요하다는 안내가 나오면 `uv tool update-shell`을 실행하거나 uv가 안내하는 경로를 셸 PATH에 추가하세요.

### 소스에서 설치

```bash
git clone https://github.com/xeon-dot/xync.git
cd xync
uv tool install .
xync --help
```

### 개발용 실행

```bash
git clone https://github.com/xeon-dot/xync.git
cd xync
uv sync
uv run xync --help
```

---

## 빠른 시작

```bash
# 1. 설정 파일 초기화
xync init

# 2. rsync 미러 추가
xync mirror add ubuntu rsync://mirror.kakao.com/ubuntu /srv/mirrors/ubuntu

# 3. HTTP 미러 추가
xync mirror add debian http://ftp.debian.org/debian /srv/mirrors/debian --type http

# 4. 등록된 미러 확인
xync mirror list

# 5. 동기화 실행
xync sync

# 6. 상태 확인
xync status
```

설정 파일은 기본적으로 다음 위치에 생성됩니다.

```text
~/.config/xync/config.toml
```

다른 설정 디렉터리를 쓰고 싶다면 모든 명령에 `--config-dir` 또는 `-C`를 사용할 수 있습니다.

```bash
xync status --config-dir /etc/xync
```

환경 변수로도 지정할 수 있습니다.

```bash
export xync_CONFIG_DIR=/etc/xync
xync status
```

---

## 명령어

### `xync init`

설정 디렉터리와 기본 설정 파일을 생성합니다.

```bash
xync init
xync init --config-dir /etc/xync
```

---

## 미러 관리

### `xync mirror add`

미러를 추가합니다.

```bash
xync mirror add NAME URL LOCAL_PATH [OPTIONS]
```

예시:

```bash
xync mirror add ubuntu rsync://mirror.kakao.com/ubuntu /srv/mirrors/ubuntu
xync mirror add debian http://ftp.debian.org/debian /srv/mirrors/debian --type http
xync mirror add arch rsync://mirror.example.org/archlinux /srv/mirrors/arch --bwlimit 50m
```

옵션:

| 옵션                  | 설명                                 |
| --------------------- | ------------------------------------ |
| `--type`, `-t`        | 미러 타입: `rsync`, `http`, `ftp`    |
| `--description`, `-d` | 미러 설명                            |
| `--bwlimit`, `-b`     | rsync 대역폭 제한. 예: `10m`, `50m`  |
| `--rsync-opts`        | 기본 rsync 옵션을 대체할 옵션 문자열 |

미러 이름은 영문/숫자/하이픈/언더스코어만 사용할 수 있습니다.

### `xync mirror list`

등록된 미러 목록을 출력합니다.

```bash
xync mirror list
```

### `xync mirror show`

특정 미러의 상세 설정을 출력합니다.

```bash
xync mirror show ubuntu
```

### `xync mirror enable` / `disable`

미러를 활성화하거나 비활성화합니다. 비활성화된 미러는 전체 동기화에서 제외됩니다.

```bash
xync mirror disable ubuntu
xync mirror enable ubuntu
```

### `xync mirror diff`

rsync 미러에서 실제 동기화 전에 변경될 항목을 확인합니다.

```bash
xync mirror diff ubuntu
```

> `mirror diff`는 rsync 미러에서만 동작합니다.

### `xync mirror remove`

미러 설정을 제거합니다.

```bash
xync mirror remove ubuntu
xync mirror remove ubuntu --yes
```

---

## 동기화

### `xync sync`

활성화된 전체 미러 또는 지정한 미러를 동기화합니다.

```bash
# 전체 활성 미러 동기화
xync sync

# 특정 미러만 동기화
xync sync ubuntu

# 여러 미러 동기화
xync sync ubuntu debian
```

옵션:

| 옵션              | 설명                              |
| ----------------- | --------------------------------- |
| `--dry-run`, `-n` | 실제 실행 없이 동기화 명령만 출력 |
| `--verbose`, `-v` | 하위 프로세스 출력을 콘솔에 표시  |

예시:

```bash
xync sync ubuntu --dry-run
xync sync ubuntu --verbose
```

---

## 상태, 로그, 점검

### `xync status`

미러의 마지막 동기화 상태, 시각, 크기, 크기 변화량을 출력합니다.

```bash
xync status
xync status ubuntu debian
```

### `xync log`

특정 미러의 최신 동기화 로그를 출력합니다.

```bash
xync log ubuntu
xync log ubuntu --lines 100
```

### `xync health`

설정 파일, 필수 도구, URL 스킴, 로컬 경로 권한, 디스크 사용률, 알림 설정(텔레그램/디스코드)을 점검합니다.

```bash
xync health
xync health ubuntu
```

---

## 데몬

`xync daemon`은 백그라운드에서 주기적으로 미러를 동기화합니다.

### 시작

```bash
xync daemon start
```

특정 미러만 대상으로 실행:

```bash
xync daemon start ubuntu debian
```

동기화 주기를 명령에서 지정:

```bash
xync daemon start --interval 3600
```

API 서버를 함께 실행:

```bash
xync daemon start --api --api-port 58080
```

### 상태 확인

```bash
xync daemon status
```

### 중지

```bash
xync daemon stop
xync daemon stop --force
```

### 재시작

```bash
xync daemon restart
xync daemon restart --interval 1800 --api
```

데몬은 기본적으로 설정 디렉터리에 PID 파일과 로그 파일을 생성합니다.

---

## REST API

API 서버는 미러 상태를 HTTP로 조회할 수 있게 합니다.

### 단독 실행

```bash
xync api start
xync api start --port 58080
```

### 상태 확인 / 중지

```bash
xync api status
xync api stop
xync api stop --force
```

### 엔드포인트

| Method | Path                       | 설명                       |
| ------ | -------------------------- | -------------------------- |
| `GET`  | `/api/status`              | 전체 미러 상태와 데몬 상태 |
| `GET`  | `/api/mirrors`             | 미러 이름 목록             |
| `GET`  | `/api/mirrors/{name}`      | 특정 미러 상태             |
| `GET`  | `/api/mirrors/{name}/size` | 특정 미러 크기 정보        |

예시:

```bash
curl http://127.0.0.1:58080/api/status
```

---

## 알림

Telegram과 Discord 알림을 설정할 수 있습니다.

지원 이벤트:

- 동기화 성공
- 동기화 실패
- 동기화 시작
- 동기화 종료
- 진행률 10% 단위 알림
- 디스크 사용률 임계치 초과 경고

### Telegram 설정

```bash
xync config set telegram.bot_token "123456:ABC-DEF"
xync config set telegram.chat_id "-100123456"
```

### Discord 설정

```bash
xync config set discord.webhook_url "https://discord.com/api/webhooks/..."
```

### 알림 옵션 변경

```bash
xync config set telegram.notify_on_start true
xync config set telegram.notify_on_progress true
xync config set discord.notify_on_failure true
```

### 테스트 알림

```bash
xync notify test
xync notify test telegram
xync notify test discord
```

---

## 설정

전역 설정은 `xync config set KEY VALUE`로 변경할 수 있습니다.

```bash
xync config show
xync config set parallel_jobs 4
xync config set daemon_interval 3600
xync config set daemon_schedule "0 */6 * * *"
xync config set disk_usage_warning_percent 85
```

### 주요 설정 키

| 키                           | 기본값                 | 설명                            |
| ---------------------------- | ---------------------- | ------------------------------- |
| `default_rsync_options`      | `-avz --delete`        | 기본 rsync 옵션                 |
| `log_dir`                    | 설정 디렉터리의 `logs` | 동기화 로그 저장 경로           |
| `max_log_files`              | `30`                   | 미러별 보관할 최대 로그 파일 수 |
| `parallel_jobs`              | `1`                    | 병렬 동기화 작업 수             |
| `daemon_interval`            | `3600`                 | 데몬 동기화 주기(초)            |
| `daemon_schedule`            | 비어 있음              | cron 표현식 기반 스케줄         |
| `api_enabled`                | `false`                | 데몬 시작 시 API 서버 함께 실행 |
| `api_port`                   | `58080`                | API 서버 포트                   |
| `disk_usage_warning_percent` | `90`                   | 디스크 사용률 경고 임계치       |
| `telegram.bot_token`         | 없음                   | Telegram Bot API 토큰           |
| `telegram.chat_id`           | 없음                   | Telegram 채팅 ID                |
| `discord.webhook_url`        | 없음                   | Discord Webhook URL             |

알림 플래그는 Telegram/Discord 각각에 대해 설정할 수 있습니다.

| 키 패턴                | 기본값  | 설명                 |
| ---------------------- | ------- | -------------------- |
| `*.notify_on_success`  | `true`  | 성공 시 알림         |
| `*.notify_on_failure`  | `true`  | 실패 시 알림         |
| `*.notify_on_start`    | `false` | 시작 시 알림         |
| `*.notify_on_finish`   | `false` | 종료 시 알림         |
| `*.notify_on_progress` | `false` | 진행률 10% 단위 알림 |

예시:

```bash
xync config set telegram.notify_on_success true
xync config set discord.notify_on_progress false
```

### 설정 파일 예시

```toml
version = 1

[global]
default_rsync_options = ["-avz", "--delete"]
log_dir = ""
max_log_files = 30
parallel_jobs = 1
daemon_interval = 3600
daemon_schedule = ""
api_enabled = false
api_port = 58080
disk_usage_warning_percent = 90

[global.telegram]
bot_token = ""
chat_id = ""
notify_on_success = true
notify_on_failure = true
notify_on_start = false
notify_on_finish = false
notify_on_progress = false

[global.discord]
webhook_url = ""
notify_on_success = true
notify_on_failure = true
notify_on_start = false
notify_on_finish = false
notify_on_progress = false

[mirrors.ubuntu]
url = "rsync://mirror.kakao.com/ubuntu"
local_path = "/srv/mirrors/ubuntu"
mirror_type = "rsync"
enabled = true
description = "Ubuntu mirror"
rsync_options = ["-avz", "--delete"]
http_options = []
bandwidth_limit = "50m"
last_status = "never"
```

---

## 스케줄링

데몬은 두 가지 방식으로 동작할 수 있습니다.

### Interval 방식

`daemon_interval` 초마다 동기화합니다.

```bash
xync config set daemon_interval 3600
xync daemon start
```

### Cron 방식

`daemon_schedule`에 cron 표현식을 설정하면 해당 스케줄을 사용합니다.

```bash
xync config set daemon_schedule "0 */6 * * *"
xync daemon start
```

예시 cron 표현식:

| 표현식        | 의미              |
| ------------- | ----------------- |
| `0 */6 * * *` | 6시간마다 정각    |
| `0 3 * * *`   | 매일 03:00        |
| `30 2 * * 0`  | 매주 일요일 02:30 |

---

## 셸 자동완성

Typer 기반 자동완성을 사용할 수 있습니다.

```bash
xync --install-completion
```

지원 셸은 Typer가 감지합니다. 설치 후 새 셸을 열거나 셸 설정 파일을 다시 로드하세요.

---

## 개발

```bash
# 의존성 설치
uv sync

# CLI 실행
uv run xync --help

# 테스트
uv run pytest

# 특정 테스트 실행
uv run pytest tests/test_cli.py -v

# 린트
uv run ruff check src/ tests/
```

빌드:

```bash
uv build
```

---

## 문제 해결

### `rsync not found on PATH`

rsync 미러를 사용하려면 `rsync`가 설치되어 있어야 합니다.

```bash
sudo apt install -y rsync
```

### `wget not found on PATH`

HTTP/HTTPS/FTP 미러를 사용하려면 `wget`이 설치되어 있어야 합니다.

```bash
sudo apt install -y wget
```

### 미러 경로 권한 오류

동기화 대상 경로의 부모 디렉터리가 존재하고, 현재 사용자가 쓸 수 있어야 합니다.

```bash
sudo mkdir -p /srv/mirrors/ubuntu
sudo chown -R "$USER:$USER" /srv/mirrors/ubuntu
xync health ubuntu
```

### 설정 확인

```bash
xync config show
xync health
```

---

## 라이선스

[AGPL-3.0-or-later](LICENSE)
