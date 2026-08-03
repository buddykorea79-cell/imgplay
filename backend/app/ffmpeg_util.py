"""ffmpeg subprocess 래퍼.

경로에 한글이 섞이면 셸 인용이 깨질 수 있으므로 **항상 리스트로 전달하고
`shell=True`는 절대 쓰지 않습니다**(섹션 12-1).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

__all__ = ["run_ffmpeg", "ffprobe_duration", "ffmpeg_path", "FFmpegError"]

_TIMEOUT = int(os.environ.get("PVT_FFMPEG_TIMEOUT", "600"))


class FFmpegError(RuntimeError):
    """ffmpeg가 0이 아닌 코드로 종료했을 때. stderr 꼬리를 담습니다."""


def ffmpeg_path() -> str:
    exe = os.environ.get("PVT_FFMPEG", "ffmpeg")
    resolved = shutil.which(exe)
    if resolved is None:
        raise FFmpegError(
            "ffmpeg를 찾을 수 없습니다. Docker 이미지에 포함되어 있어야 합니다 "
            "(docker compose up). 로컬 실행이라면 ffmpeg를 설치하세요."
        )
    return resolved


def ffprobe_path() -> str:
    exe = os.environ.get("PVT_FFPROBE", "ffprobe")
    resolved = shutil.which(exe)
    if resolved is None:
        raise FFmpegError("ffprobe를 찾을 수 없습니다.")
    return resolved


def run_ffmpeg(args: list[str], capture: bool = False, timeout: int | None = None) -> bytes:
    """ffmpeg를 실행한다. `capture=True`면 stdout 바이트를 돌려준다."""
    cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args]
    proc = subprocess.run(  # noqa: S603 - 리스트 인자, shell 미사용
        cmd,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=timeout or _TIMEOUT,
        check=False,
    )
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-8:]
        raise FFmpegError("ffmpeg 실패:\n" + "\n".join(tail))
    return proc.stdout if capture else b""


def ffprobe_duration(path: Path) -> float:
    """미디어 길이(초). 실패하면 0.0."""
    cmd = [
        ffprobe_path(),
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=60, check=False)  # noqa: S603
    try:
        return float(proc.stdout.decode().strip())
    except (ValueError, AttributeError):
        return 0.0
