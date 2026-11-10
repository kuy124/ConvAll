import sys
import tempfile
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'src'))
import convall_ui as ui

app = ui.App(paths=[ROOT/'tests/samples/blue.png', ROOT/'tests/samples/warm.jpg'])
app.root.update()
app.set_target('pdf')
first, second = app.list.items
app.apply_row_options([first], {'output_name': 'Faris', 'title': 'Only this file'})
assert app.row_options(first)['output_name'] == 'Faris'
assert not app.row_options(second).get('output_name')
assert 'output_name' not in app.opts
app.list.sel = {0}
app.advanced_options()
dialog = app._advanced_dialog
fields = [w for w in ui._descendants(dialog) if isinstance(w, ui.tk.Entry)]
assert fields[0].get() == 'Faris'
dialog.event_generate('<Escape>')
app.root.update()
with tempfile.TemporaryDirectory() as d:
    app.outdir = Path(d)
    app.start()
    deadline = time.time() + 20
    while app.running and time.time() < deadline:
        app.root.update()
        time.sleep(.02)
    assert not app.running
    assert {p.name for p in Path(d).iterdir()} == {'Faris.pdf', 'warm.pdf'}
app.apply_row_options([first], {'output_name': 'Shared'}, all_rows=True)
assert all(app.row_options(row)['output_name'] == 'Shared' for row in app.list.items)
app.root.destroy()
print('selected row naming, dialog preload, isolated jobs, explicit all-files opt-in OK')
