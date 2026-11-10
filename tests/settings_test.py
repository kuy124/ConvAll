"""Preferences survive restart; themes preserve queue; folder actions work."""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import convall_settings as settings
import convall_ui as ui

with tempfile.TemporaryDirectory() as temp:
    with patch.dict(os.environ, {'APPDATA': temp}):
        source = Path(temp) / 'test.txt'
        source.write_text('sample')
        settings.save_settings({'theme': 'Nord', 'output_folder': temp,
                                'options': {'quality': 60}, 'input_folder': temp})
        app = ui.App()
        app.root.update()
        assert app.theme == 'Nord' and app.opts['quality'] == 60
        assert app.outdir == Path(temp)
        with patch.object(app, 'pick_files') as pick:
            app.list.on_pick = app.pick_files
            app.list._dblclick(SimpleNamespace(y=20))
            pick.assert_called_once()
        app.list.add([source])
        for name in settings.THEMES:
            app.change_theme(name)
            app.root.update()
            assert app.list.paths() == [source]
            assert app.root.cget('bg') == settings.THEMES[name][0]
        with patch('os.startfile') as opened:
            app.open_output()
            opened.assert_called_once_with(temp)
        app.set_option('quality', 96)
        app.root.destroy()
        other = ui.App()
        assert other.opts['quality'] == 96 and other.theme == 'Solarized Light'
        other.reset_outdir()
        assert settings.load_settings()['output_folder'] is None
        other.root.destroy()
        settings.settings_path().write_text('broken json')
        assert settings.load_settings() == {}
print('theme switching, persisted settings, double-click and output-folder opening OK')
