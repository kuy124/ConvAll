"""Run the whole verification suite: engine, GUI flow, drag, resize, scroll."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable

SUITE = [
    ('ZIP outputs and PDF documents', 'tests/bundles_test.py'),
    ('per-row advanced settings', 'tests/row_options_test.py'),
    ('dialog and menu UX', 'tests/ux_test.py'),
    ('metadata and subprocesses', 'tests/metadata_test.py'),
    ("preferences and themes", "tests/settings_test.py"),
    ("cross-media routing", "tests/routes_test.py"),
    ("engine routes", "src/convall_engine.py"),
    ("format round trips", "tests/formats_test.py"),
    ("pill centering", "tests/pill_test.py"),
    ("option effects", "tests/options_test.py"),
    ("per-row targets", "tests/perrow_test.py"),
    ("options UI", "tests/options_ui_test.py"),
    ("drag", "tests/drag_test.py"),
    ("resize + selection", "tests/perf_test.py"),
    ("chip scrolling", "tests/scroll_test.py"),
    ("ffmpeg download UI", "tests/ffmpeg_ui_test.py"),
]

failed = []
subprocess.run([PY, str(HERE / "make_samples.py")], check=True)
for name, script in SUITE:
    print(f"\n=== {name} ===")
    r = subprocess.run([PY, str(HERE.parent / script)], capture_output=True,
                       text=True, timeout=900)
    tail = [ln for ln in (r.stdout + r.stderr).strip().splitlines() if ln][-3:]
    for ln in tail:
        print("   ", ln)
    if r.returncode:
        failed.append(name)

print("\n" + ("ALL GREEN" if not failed else f"FAILED: {failed}"))
sys.exit(1 if failed else 0)
