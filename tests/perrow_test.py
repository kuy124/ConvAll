"""Drive the per-row-target flow: different files, different formats, one run."""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import convall_ui as ui  # noqa: E402

S = ROOT / "tests" / "samples"
OUT = ROOT / "tests" / "guiout"
shutil.rmtree(OUT, ignore_errors=True)
OUT.mkdir(parents=True)

app = ui.App(paths=[S / "blue.png", S / "clip.mp4", S / "notes.md",
                    S / "rows.csv"])
app.outdir = OUT
app.out_lbl.configure(text=str(OUT))
results = []


def pick(rows, fmt):
    """Select rows the way a user would, then click the format chip."""
    app.list.select_none()
    app.list.sel = set(rows)
    app.list._notify_select()
    app.list.draw()
    app.root.update_idletasks()
    chip = app.chips.get(fmt)
    assert chip is not None, f"no {fmt} chip for rows {rows}"
    chip._on_release(None)


def phase1():
    pick([0], "jpg")        # image  -> jpg
    pick([1], "mp3")        # video  -> mp3
    pick([2], "pdf")        # notes  -> pdf
    pick([3], "json")       # csv    -> json
    cta = app.btn_go.text_
    print("CTA:", cta)
    app.root.update_idletasks()
    app.start()


def done():
    print("status:", app.status_lbl.cget("text"))
    print("targets:", [i["target"] for i in app.list.items])
    print("states:", [i["state"] for i in app.list.items])
    print("files:", sorted(p.name for p in OUT.iterdir()))
    results.append([i["state"] for i in app.list.items])
    app.root.destroy()


app.root.after(600, phase1)
app.root.after(900, lambda: (app.running and app.root.after(200, lambda: None)))
app.root.after(5000, done)
app.root.after(30000, done)
app.root.mainloop()

states = results[0]
assert states == ["ok"] * 4, f"not all converted: {states}"
print("per-row targets OK")