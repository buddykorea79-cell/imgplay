# 사진 → 영상 2단계 튜닝 웹앱

사진 폴더를 업로드해서 **두 단계를 순서대로 튜닝하고 검증하는 도구**입니다.

```
1단계  화질 보정      측정 → 규칙 적용 → 눈으로 확인
         ↓  [그레이딩 확정]  ← 명시적 게이트
2단계  영상 효과      줌·팬·전환 → 클립 미리보기 → 타임라인 렌더
         ↓
       최종 mp4 + 재현 가능한 설정 파일
```

최종 산출물은 영상 파일 하나가 아니라 **검증된 `grade.yaml` + `motion.yaml`**입니다.
나중에 만들 배치 파이프라인이 이 두 파일만 읽어서 수백 장을 자동 처리하게 됩니다.
UI의 존재 이유는 *규칙이 깨지는 사진을 빨리 찾는 것*입니다.

LLM이나 VLM은 사용하지 않습니다. 모든 판단은 이미지 통계와 EXIF에서 결정적으로
계산됩니다.

**두 단계를 분리하는 이유**: 화질과 모션은 판단 기준이 다릅니다. 화질은 정지
상태에서 픽셀을 봐야 하고, 모션은 재생하면서 리듬을 봐야 합니다. 섞으면 둘 다
제대로 못 봅니다. 그래서 1단계를 확정하기 전에는 2단계 탭이 잠겨 있습니다
(API도 `409`를 돌려줍니다).

---

## 실행

### Docker (권장)

ffmpeg가 이미지에 포함되어 있어 버전 차이로 결과가 갈라지지 않습니다.

```bash
docker compose up --build
# → http://localhost:8000
```

`grade.yaml`, `motion.yaml`, `work/`가 바인드 마운트되어 컨테이너 안에서 튜닝한
값이 저장소에 그대로 남습니다.

### 로컬 개발

ffmpeg가 `PATH`에 있어야 합니다.

```bash
# 백엔드
cd backend
uv venv && uv pip install -e ".[dev]"
uv run uvicorn app.main:app --reload --port 8000

# 프론트엔드 (다른 터미널)
cd frontend
npm install && npm run dev      # → http://localhost:5173
```

`frontend/dist`가 빌드되어 있으면 FastAPI가 정적 서빙해 단일 프로세스로 돕니다
(`npm run build` 후 `http://localhost:8000`).

### 환경 변수

| 변수 | 기본값 | 용도 |
|---|---|---|
| `PVT_WORK_DIR` | `<저장소>/work` | 업로드·중간본·클립·최종 출력 |
| `PVT_RULES_DIR` | `<저장소>` | `grade.yaml`, `motion.yaml` 위치 |
| `PVT_STATIC_DIR` | `<저장소>/frontend/dist` | 빌드된 UI. 패키지를 site-packages에 설치하면 저장소 경로 추론이 빗나가므로 컨테이너에서는 못 박습니다 |
| `PVT_RENDER_PARALLEL` | `3` | 동시 ffmpeg 개수 |
| `PVT_FFMPEG` / `PVT_FFPROBE` | `ffmpeg` / `ffprobe` | 바이너리 경로 |
| `PVT_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 프론트를 다른 호스트에 올렸을 때 그 주소 (쉼표 구분) |
| `PVT_CORS_ORIGIN_REGEX` | 없음 | Vercel 프리뷰처럼 주소가 매번 바뀔 때 |

프론트엔드는 빌드 시점에 `VITE_API_BASE`를 읽습니다. 비워두면 같은 출처의
`/api`를 씁니다 (로컬 개발에서는 Vite 프록시가 처리).

---

## Vercel 배포

**Vercel에는 프론트엔드만 올라갑니다.** 백엔드는 ffmpeg 시스템 바이너리를
`subprocess`로 부르고, `work/`에 중간본과 클립 캐시를 쌓고, 렌더가 수 분씩
걸립니다. 서버리스에는 ffmpeg가 없고 파일시스템이 읽기 전용이며 실행 시간
제한이 있어 셋 다 성립하지 않습니다.

### 1. 백엔드를 먼저 띄웁니다

이 저장소의 `Dockerfile`을 그대로 받는 곳이면 됩니다 (Fly.io, Railway, Render,
직접 굴리는 서버 등).

```bash
docker build -t photo-video-tuner .
docker run -p 8000:8000 \
  -e PVT_CORS_ORIGINS=https://내-프로젝트.vercel.app \
  photo-video-tuner
```

디스크는 영속 볼륨으로 `/app/work`에 붙이세요. 없으면 재시작할 때마다 중간본과
캐시가 날아갑니다.

> 인증이 없는 앱입니다. 공개 주소에 백엔드를 띄우면 아무나 업로드·렌더를
> 돌릴 수 있으니, 접근 제한을 걸거나 사설망에 두세요.

### 2. Vercel 프로젝트 설정

저장소를 그대로 import하면 됩니다. **Root Directory는 기본값(저장소 루트)
그대로 두세요** — 빌드 방법은 루트의 `vercel.json`에 들어 있습니다.

```
루트 package.json   Vercel이 Node 프로젝트로 인식하게 하고 frontend/로 빌드를 위임
vercel.json         installCommand · buildCommand · outputDirectory(frontend/dist)
```

빌드 명령이 `npm --prefix frontend ci`가 아니라 `cd frontend && npm ci`인 것은
의도적입니다. `--prefix`는 npm 버전에 따라 `ci`가 락파일을 찾는 위치가 달라져
`EUSAGE` 오류로 죽습니다.

루트 `package.json`이 없으면 Vercel은 이 저장소를 **정적 사이트로 취급해
`vercel.json`의 빌드 명령을 실행하지 않습니다.** 그러면 루트에 `index.html`이
없으므로 배포는 성공했는데 접속하면 `404: NOT_FOUND`가 뜹니다.

환경변수 하나만 추가합니다.

| 이름 | 값 |
|---|---|
| `VITE_API_BASE` | `https://내-백엔드-주소/api` |

끝에 `/api`까지 포함해야 합니다. 빌드 시점에 번들에 박히므로, 값을 바꾸면
재배포해야 반영됩니다.

브라우저가 백엔드로 직접 요청합니다. `vercel.json`의 rewrite로 프록시하지
않는 이유는 두 가지입니다 — Vercel은 rewrite 목적지에 환경변수를 넣지 못하고,
프록시를 거치면 클립 mp4가 응답 크기 제한에 걸립니다.

### 백엔드 없이 열면

"백엔드에 연결할 수 없습니다" 안내와 함께 해결 방법이 표시됩니다. 빈 화면이나
정체불명의 오류가 뜨지는 않습니다.

### 그래도 404가 뜬다면

배포 자체가 실패했거나 빌드가 안 돌았다는 뜻입니다. Vercel 대시보드에서
확인하세요.

1. **Deployment → Building 로그**에 `installCommand` / `buildCommand`가 찍혔는지.
   안 찍혔다면 Vercel이 빌드 단계를 건너뛴 것입니다.
2. **Settings → General → Root Directory**가 비어 있는지(= 저장소 루트).
   `frontend`로 바꿔 두었다면 루트의 `vercel.json`이 읽히지 않습니다. 비우거나,
   `frontend`를 쓸 거라면 Framework Preset을 Vite로 두고 Output Directory는
   `dist`로 두세요.
3. **Settings → Build & Deployment**에서 Output Directory를 손으로 덮어쓰지
   않았는지. `vercel.json`의 `frontend/dist`와 어긋나면 빈 배포가 됩니다.

### 얼굴 검출 모델 (선택)

없어도 동작합니다. 있으면 채도 상한(`skin_max`)과 2단계 줌 목표점에 얼굴이
반영됩니다.

```bash
./scripts/fetch_face_model.sh
```

---

## CLI로 먼저 검증하기

UI를 먼저 보면 계산 로직 버그가 UI 버그로 위장돼 디버깅이 몇 배 어려워집니다.
백엔드만 따로 확인할 수 있는 CLI가 있습니다.

```bash
cd backend
uv run pvt ingest ~/사진/여행    # 측정 + 통계 표
uv run pvt grade                 # 보정 파라미터 + 클램프 히트율
uv run pvt commit                # work/graded/ 에 PNG 생성
uv run pvt poi --out ./poi       # POI 마커를 그려 눈으로 검증
uv run pvt motion                # 모션 파라미터 + 전환 + 총 길이
uv run pvt clip 0 --out c.mp4    # 단일 클립 렌더
uv run pvt render                # 전체 렌더
uv run pvt export ./export.zip
```

---

## 규칙 파일

전부 yaml에서 옵니다. 코드에 상수를 심지 않습니다 — 심는 순간 UI에서 튜닝한
값과 배치 파이프라인이 읽는 값이 갈라집니다.

| 파일 | 내용 |
|---|---|
| `grade.yaml` | 목표 밝기/대비/채도, 클램프 범위, 야간·로우키·고대비 가드 |
| `motion.yaml` | 출력 규격, 지속시간, 줌·팬, 종횡비 처리, 전환 판단 임계값 |

### 클램프 히트가 이 도구의 실질적 출력입니다

규칙을 적용하다 상·하한에 걸리면 그 항목을 기록해 UI에 배지로 띄웁니다.
클램프에 걸렸다는 건 **규칙이 감당하지 못하는 사진**이라는 뜻입니다.

사진 20~30장으로 돌려보고 단계별 히트율을 보세요.

**1단계 (화질)**
- 10% 미만 → 규칙이 잘 맞습니다. 그대로 진행
- 10~30% → 클램프 범위나 `target` 조정으로 해결 가능
- 30% 초과 → 사진 성격이 너무 다양합니다. 촬영 조건별로 `grade.yaml`을 분리하거나,
  이 지점에서 비로소 VLM 보조를 검토할 근거가 생깁니다

**2단계 (모션)**
- `max_zoom` 히트가 많으면 → 원본 해상도가 부족합니다. 출력을 1080p로 낮추거나
  `zoom.amount`를 줄이세요
- 종횡비 편차 히트가 많으면 → 세로·가로가 섞여 있습니다. `blur_fill`을 기본으로 두세요
- 미리보기가 어지럽다면 → `zoom.amount`보다 `duration.base_sec`을 먼저 늘려보세요.
  같은 줌량이라도 시간이 길면 훨씬 편안합니다

---

## 내보내기

`GET /api/export`가 zip을 돌려줍니다.

| 파일 | 내용 |
|---|---|
| `grade.yaml` / `motion.yaml` | 검증된 규칙 — 진짜 산출물 |
| `build.sh` | UI와 동일한 mp4를 만드는 재현 스크립트 |
| `stats.csv` | 사진별 측정값·적용값·클램프 히트 |

```bash
unzip photo-video-tuner-export.zip -d out && cd out
./build.sh ./photos ./final.mp4
```

`build.sh`는 UI와 **같은 코드가 만든 같은 필터 문자열**을 그대로 담습니다.
결과가 갈라질 여지가 없고, 이를 테스트로 검증합니다
(`test_build_sh가_동일한_영상을_만든다`, PSNR 비교).

---

## 구조

```
├─ grade.yaml / motion.yaml    규칙 (진짜 산출물)
├─ Dockerfile                  ffmpeg 포함
├─ backend/app/
│  ├─ imageio.py               한글 경로 안전 입출력, EXIF 회전 정규화
│  ├─ measure.py               이미지 → 통계
│  ├─ exif.py                  EXIF 추출
│  ├─ grade.py                 통계 + grade.yaml → 보정 파라미터 (+ 클램프 기록)
│  ├─ ffmpeg_grade.py          보정 필터 조립
│  ├─ compose.py               POI, 안전 줌 상한, 종횡비 편차
│  ├─ motion.py                구도 + motion.yaml → 모션 파라미터
│  ├─ timeline.py              정렬, 전환 판단, 총 길이, xfade 오프셋
│  ├─ ffmpeg_motion.py         클립 렌더, 전환, 이어붙이기
│  ├─ render.py / export.py    작업 큐 / 내보내기
│  └─ main.py / cli.py         API / CLI
└─ frontend/src/
   ├─ App.tsx                  2단계 탭 셸 (게이트)
   └─ components/stage1, stage2
```

`work/`는 gitignore됩니다: `uploads/`(원본 사본), `graded/`(확정 중간본 PNG),
`clips/`(클립 캐시), `out/`(최종 mp4).

---

## 설계상 지켜지는 것들

이 항목들은 테스트로 고정되어 있습니다 (`backend/tests/`, 92개).

- **한글 경로** — `cv2.imread`는 비ASCII 경로에서 예외 없이 `None`을 돌려줍니다.
  `imageio.py`만 사용하고, 로딩 실패는 반드시 예외로 터집니다. ffmpeg에는
  `subprocess` 리스트로 넘기고 `shell=True`를 쓰지 않습니다.
- **EXIF 회전** — 읽는 시점에 정규화합니다. 놓치면 종횡비 판정까지 틀어집니다.
- **선명도 해상도 정규화** — 라플라시안 분산은 해상도에 비례하므로 긴 변 1024px로
  줄여 측정합니다.
- **미리보기는 ffmpeg로** — CSS 필터나 OpenCV로 흉내내지 않습니다. 눈으로 튜닝한
  값이 재현되지 않으면 이 도구는 무의미합니다.
- **중간본은 PNG** — JPEG면 2단계에서 재인코딩 손실이 누적됩니다.
- **캐시 키는 파일 해시** — 파일명은 중복되고 바뀝니다.
- **원본 파일을 수정하지 않습니다.**
- **줌 떨림 방지** — `zoompan`은 크롭 좌표를 정수로 자릅니다. 출력의 4배로 먼저
  업스케일해 계단을 1/4로 줄입니다. 측정값: 프레임당 이탈 σ 0.91px → 0.15px.
- **클립 개별 렌더 후 결합** — 200장을 하나의 `filter_complex`로 묶지 않습니다.
  캐시 키가 이미지 해시 + 모션 파라미터라 바뀐 클립만 다시 렌더됩니다.
- **`d`는 프레임 수** — `zoompan`의 `d`는 초가 아닙니다. `fps`도 명시하지 않으면
  25로 잡힙니다.
- **블러 배경은 zoompan보다 먼저** — 순서가 반대면 배경까지 같이 줌돼서 어지럽습니다.

---

## 성능 (4코어 컨테이너 기준)

| 작업 | 시간 |
|---|---|
| 12MP 사진 30장 측정 (콜드) | 4.1초 |
| 같은 사진 재측정 (캐시 히트) | 0.1초 |
| `grade/evaluate`, `motion/evaluate` | 수십 ms (재측정 없음) |
| 단일 클립 미리보기 540p / 5초 분량 | 약 1.7초 (360p면 약 1.1초) |

`evaluate`가 순수 계산이라 슬라이더를 만져도 재측정이 없습니다. 프론트는 150ms
디바운스로 호출합니다.

클립 미리보기는 4배 업스케일 필터링이 시간의 대부분(약 1.2초)을 차지해 5초 분량
540p에서 1초 아래로 내려가지 않습니다. `motion.yaml`의 `output.preview_height`가
이 트레이드오프를 조절하는 손잡이입니다 (360p면 약 1.1초).

---

## 개발

```bash
cd backend && uv run ruff check . && uv run pytest -q
cd frontend && npm run typecheck && npm run build
```

CI(`.github/workflows/ci.yml`)가 위 검사와 Docker 이미지 빌드·헬스체크를 돌립니다.

**GitHub Pages 배포는 불가능합니다** — 정적 호스팅이라 파이썬 백엔드가 돌지
않습니다. 이 도구는 자기 사진으로 튜닝하는 게 목적이므로 로컬 실행이 맞습니다.
