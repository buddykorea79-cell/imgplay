"""API 스펙 (섹션 11). 특히 2단계 잠금(409)을 검증합니다."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from conftest import make_image
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg가 없습니다")


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    """격리된 work 디렉터리를 쓰는 테스트 클라이언트."""
    monkeypatch.setenv("PVT_WORK_DIR", str(tmp_path / "work"))
    import app.state as state_mod

    state_mod._state = None  # 전역 상태를 테스트마다 새로 만든다
    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as c:
        yield c
    state_mod._state = None


@pytest.fixture
def photos(tmp_path: Path) -> list[Path]:
    d = tmp_path / "원본 사진"
    d.mkdir()
    return [
        make_image(d / "가로 １.jpg", 1600, 1200, brightness=150,
                   exif={"DateTimeOriginal": "2024:05:01 10:00:00", "ISOSpeedRatings": 100}),
        make_image(d / "세로 ２.jpg", 1200, 1600, brightness=90,
                   exif={"DateTimeOriginal": "2024:05:01 10:10:00", "ISOSpeedRatings": 200}),
    ]


def _upload(client, paths: list[Path]):
    files = [("files", (p.name, p.read_bytes(), "image/jpeg")) for p in paths]
    r = client.post("/api/photos", files=files)
    assert r.status_code == 200, r.text
    return r.json()


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_규칙_읽기_쓰기(client):
    r = client.get("/api/rules/grade")
    assert r.status_code == 200
    rules = r.json()
    assert rules["target"]["median_L"] == 50.0

    rules["target"]["median_L"] = 55.0
    assert client.put("/api/rules/grade", json=rules).status_code == 200
    assert client.get("/api/rules/grade").json()["target"]["median_L"] == 55.0


def test_잘못된_규칙은_422(client):
    assert client.put("/api/rules/grade", json={"오타난키": 1}).status_code == 422


def test_업로드와_측정(client, photos):
    data = _upload(client, photos)
    assert len(data) == 2
    for item in data:
        assert item["stats"]["median_L"] > 0
        assert item["width"] > 0
    portrait = next(d for d in data if "세로" in d["filename"])
    assert portrait["height"] > portrait["width"]


def test_지원하지_않는_확장자(client, tmp_path: Path):
    bad = tmp_path / "문서.txt"
    bad.write_text("hello")
    r = client.post("/api/photos", files=[("files", (bad.name, b"hello", "text/plain"))])
    assert r.status_code == 422


def test_evaluate는_클램프를_돌려준다(client, photos):
    _upload(client, photos)
    rules = client.get("/api/rules/grade").json()
    r = client.post("/api/grade/evaluate", json={"rules": rules})
    assert r.status_code == 200
    body = r.json()
    assert len(body["params"]) == 2
    assert "clamp_rate" in body and "clamp_counts" in body


def test_미리보기와_원본은_같은_스케일(client, photos):
    ids = [d["id"] for d in _upload(client, photos)]
    pid = ids[0]
    a = client.get(f"/api/grade/preview/{pid}?mode=fit&long_edge=400")
    b = client.get(f"/api/grade/original/{pid}?mode=fit&long_edge=400")
    assert a.status_code == b.status_code == 200
    assert a.headers["content-type"] == "image/jpeg"

    import cv2
    import numpy as np

    ia = cv2.imdecode(np.frombuffer(a.content, np.uint8), cv2.IMREAD_COLOR)
    ib = cv2.imdecode(np.frombuffer(b.content, np.uint8), cv2.IMREAD_COLOR)
    assert ia.shape == ib.shape, "비교 뷰의 스케일이 다릅니다"
    assert max(ia.shape[:2]) == 400
    assert not np.array_equal(ia, ib), "보정본과 원본이 동일합니다"


def test_100퍼센트_크롭_모드(client, photos):
    pid = _upload(client, photos)[0]["id"]
    r = client.get(f"/api/grade/preview/{pid}?mode=crop&crop_size=300")
    assert r.status_code == 200

    import cv2
    import numpy as np

    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[:2] == (300, 300)


def test_2단계는_확정_전에_409(client, photos):
    """1단계 확정 전에 2단계 접근을 허용하면 안 됩니다."""
    _upload(client, photos)
    motion = client.get("/api/rules/motion").json()

    assert client.get("/api/timeline").status_code == 409
    assert client.post("/api/motion/evaluate", json={"rules": motion}).status_code == 409
    assert client.put("/api/timeline/order", json={"order": []}).status_code == 409
    assert client.post(
        "/api/render", json={"motion_rules": motion}
    ).status_code == 409


def test_확정_후_2단계가_열린다(client, photos):
    _upload(client, photos)
    grade = client.get("/api/rules/grade").json()

    status = client.get("/api/grade/status").json()
    assert status["stage2_unlocked"] is False

    with client.stream("POST", "/api/grade/commit", json={"rules": grade}) as r:
        assert r.status_code == 200
        events = [line for line in r.iter_lines() if line.startswith("data:")]
    assert events, "SSE 진행률이 오지 않았습니다"

    status = client.get("/api/grade/status").json()
    assert status["committed"] is True
    assert status["stage2_unlocked"] is True
    assert status["committed_count"] == 2

    tl = client.get("/api/timeline")
    assert tl.status_code == 200
    body = tl.json()
    assert len(body["items"]) == 2
    assert len(body["transitions"]) == 1
    assert body["total_duration_sec"] == pytest.approx(
        body["sum_duration_sec"] - body["transition_saving_sec"]
    )


def test_되돌아가면_다시_잠긴다(client, photos):
    _upload(client, photos)
    grade = client.get("/api/rules/grade").json()
    with client.stream("POST", "/api/grade/commit", json={"rules": grade}) as r:
        list(r.iter_lines())

    assert client.get("/api/timeline").status_code == 200
    assert client.post("/api/grade/uncommit").status_code == 200
    assert client.get("/api/timeline").status_code == 409


def test_타임라인_재배치(client, photos):
    _upload(client, photos)
    grade = client.get("/api/rules/grade").json()
    with client.stream("POST", "/api/grade/commit", json={"rules": grade}) as r:
        list(r.iter_lines())

    order = client.get("/api/timeline").json()["order"]
    reversed_order = list(reversed(order))
    r = client.put("/api/timeline/order", json={"order": reversed_order})
    assert r.status_code == 200
    assert client.get("/api/timeline").json()["order"] == reversed_order

    # 촬영시각 순으로 되돌리기
    assert client.post("/api/timeline/sort").json()["order"] == order


def test_알_수_없는_id는_400(client, photos):
    _upload(client, photos)
    grade = client.get("/api/rules/grade").json()
    with client.stream("POST", "/api/grade/commit", json={"rules": grade}) as r:
        list(r.iter_lines())
    assert client.put("/api/timeline/order", json={"order": ["없는id"]}).status_code == 400


def test_클립_미리보기(client, photos):
    ids = [d["id"] for d in _upload(client, photos)]
    grade = client.get("/api/rules/grade").json()
    with client.stream("POST", "/api/grade/commit", json={"rules": grade}) as r:
        list(r.iter_lines())

    motion = client.get("/api/rules/motion").json()
    motion["output"]["width"], motion["output"]["height"] = 640, 360
    motion["output"]["preview_height"] = 180
    motion["duration"]["base_sec"] = motion["duration"]["min_sec"] = 1.0

    r = client.post(f"/api/motion/clip/{ids[0]}", json={"rules": motion})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "video/mp4"
    assert len(r.content) > 1000


def test_전체_렌더(client, photos):
    _upload(client, photos)
    grade = client.get("/api/rules/grade").json()
    with client.stream("POST", "/api/grade/commit", json={"rules": grade}) as r:
        list(r.iter_lines())

    motion = client.get("/api/rules/motion").json()
    motion["output"]["width"], motion["output"]["height"] = 480, 270
    motion["duration"]["base_sec"] = motion["duration"]["min_sec"] = 1.0

    job_id = client.post("/api/render", json={"motion_rules": motion}).json()["job_id"]
    with client.stream("GET", f"/api/render/{job_id}") as r:
        events = [line for line in r.iter_lines() if line.startswith("data:")]
    assert events

    status = client.get(f"/api/render/{job_id}/status").json()
    assert status["phase"] == "done", status
    assert client.get(f"/api/render/{job_id}/file").headers["content-type"] == "video/mp4"


def test_export_zip(client, photos):
    _upload(client, photos)
    grade = client.get("/api/rules/grade").json()
    with client.stream("POST", "/api/grade/commit", json={"rules": grade}) as r:
        list(r.iter_lines())

    r = client.get("/api/export")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"

    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert {"grade.yaml", "motion.yaml", "build.sh", "stats.csv"} <= set(z.namelist())


def test_규칙_저장이_설명_주석을_유지한다(client, isolated_rules):
    """확정할 때마다 파일을 덮어쓰므로, 설명이 매번 다시 붙어야 합니다."""
    import yaml

    rules = client.get("/api/rules/grade").json()
    rules["target"]["median_L"] = 52.0
    client.put("/api/rules/grade", json=rules)

    text = (isolated_rules / "grade.yaml").read_text(encoding="utf-8")
    assert text.startswith("#"), "헤더 주석이 없습니다"
    assert "# 밝기." in text, "섹션 설명이 없습니다"
    # 주석이 붙어도 값은 그대로 되읽혀야 한다
    assert yaml.safe_load(text)["target"]["median_L"] == 52.0
    assert client.get("/api/rules/grade").json()["target"]["median_L"] == 52.0


def test_cors_기본값은_로컬만_허용한다(client):
    """인증이 없는 앱이라 기본값이 넓으면 안 됩니다."""
    r = client.options(
        "/api/grade/evaluate",
        headers={
            "Origin": "https://somewhere-else.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_cors_출처를_환경변수로_열_수_있다(tmp_path: Path, monkeypatch):
    """프론트를 다른 호스트(Vercel 등)에 올렸을 때 필요합니다."""
    monkeypatch.setenv("PVT_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("PVT_CORS_ORIGINS", "https://my-app.vercel.app, http://localhost:5173")

    import importlib

    import app.main as main_mod
    import app.state as state_mod

    state_mod._state = None
    reloaded = importlib.reload(main_mod)
    try:
        with TestClient(reloaded.app) as c:
            r = c.options(
                "/api/grade/evaluate",
                headers={
                    "Origin": "https://my-app.vercel.app",
                    "Access-Control-Request-Method": "POST",
                },
            )
            assert r.headers["access-control-allow-origin"] == "https://my-app.vercel.app"
    finally:
        state_mod._state = None
        monkeypatch.delenv("PVT_CORS_ORIGINS")
        importlib.reload(main_mod)  # 다른 테스트에 새지 않도록 되돌린다
