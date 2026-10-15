"""src/SpecWizard.bas (UTF-8) から Excel 取込用の SpecWizard.bas (Shift-JIS / CRLF) を作る.

日本語版 Excel の VBE は .bas を Shift-JIS (CP932) として読むため、UTF-8 のままでは文字化けする。
src/ を編集したら `python macro/spec_wizard/tools/build_bas.py` で作り直すこと。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "SpecWizard.bas"
DST = ROOT / "SpecWizard.bas"


def build() -> bytes:
    text = SRC.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not text.endswith("\n"):
        text += "\n"
    return text.replace("\n", "\r\n").encode("cp932")


if __name__ == "__main__":
    DST.write_bytes(build())
    print(f"wrote {DST}")
