"""マクロ仕様書ウィザード: 取り込み用 .bas が src/ と一致していること."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "macro" / "spec_wizard"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_bas", ROOT / "tools" / "build_bas.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_import_file_is_up_to_date():
    builder = _load_builder()
    assert (ROOT / "SpecWizard.bas").read_bytes() == builder.build(), (
        "src/SpecWizard.bas を編集したら tools/build_bas.py で SpecWizard.bas を作り直すこと"
    )


def test_import_file_format():
    data = (ROOT / "SpecWizard.bas").read_bytes()
    assert data.startswith(b'Attribute VB_Name = "SpecWizard"\r\n')
    assert b"\n" not in data.replace(b"\r\n", b"")  # 改行はすべて CRLF
