"""실제 모드 체험(샌드박스) 진입점 — 회사 공유폴더 없이 실제 모드 화면·동작을 직접 써 볼 수 있다.

합성 Windows 공유(가상 문서, 접근 거부 폴더 포함)를 임시 폴더에 만들고 OS 파일 API 대신 연결한다.
설정·색인은 임시 폴더(APP_HOME)에 저장되며 실제 네트워크·회사 자료에는 접속하지 않는다. 운영용이 아니다.
공유 등록 화면에서 UNC 경로로 아래 값을 입력하세요:  \\\\fs-corp01.example.invalid\\계리평가팀
"""
import os
import runpy
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
os.environ["APP_MODE"] = "real"
os.environ.setdefault("APP_HOME", str(Path(tempfile.gettempdir()) / "actuarial_sandbox_home"))

import streamlit as st  # noqa: E402


@st.cache_resource
def sandbox_fs():
    from winshare import UNC_ROOT, build_windows_share
    w = build_windows_share(Path(tempfile.mkdtemp(prefix="winshare_sandbox_")))
    w.fs.deny_read(UNC_ROOT + "\\기밀")        # 목록에는 보이지만 열 수 없음 (권한 없음 체험)
    w.fs.deny_list(UNC_ROOT + "\\목록거부")    # 폴더 목록 열람 거부
    return w.fs


import core.services as cs  # noqa: E402

cs.LocalFS = lambda *a, **k: sandbox_fs()
st.sidebar.info("🧪 샌드박스: 합성 공유 사용 중 — 등록 경로 `\\\\fs-corp01.example.invalid\\계리평가팀`")
runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
