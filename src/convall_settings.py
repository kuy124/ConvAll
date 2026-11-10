"""Small, atomic per-user preferences. No queued files or file contents saved."""
import json
import os
from pathlib import Path

THEMES = {
    'Dark+': ('#1e1e1e', '#252526', '#333333', '#454545', '#d4d4d4', '#b0b0b0', '#909090', '#007acc', '#168bd2', '#094771'),
    'Light+': ('#f3f3f3', '#ffffff', '#e8e8e8', '#cccccc', '#242424', '#555555', '#666666', '#007acc', '#006bb3', '#d6ebff'),
    'Nord': ('#2e3440', '#3b4252', '#434c5e', '#4c566a', '#eceff4', '#d8dee9', '#aab6cc', '#5e81ac', '#81a1c1', '#434c5e'),
    'Dracula': ('#282a36', '#303341', '#44475a', '#6272a4', '#f8f8f2', '#c5c6d0', '#a4abc2', '#bd93f9', '#caa9fa', '#44475a'),
    'Solarized Dark': ('#002b36', '#073642', '#164653', '#586e75', '#fdf6e3', '#93a1a1', '#839496', '#268bd2', '#2aa198', '#164653'),
    'Solarized Light': ('#fdf6e3', '#eee8d5', '#e4ddc8', '#93a1a1', '#073642', '#586e75', '#657b83', '#268bd2', '#2aa198', '#d7e8df'),
}


def settings_path():
    base = Path(os.environ.get('APPDATA') or Path.home() / '.config')
    return base / 'ConvAll' / 'settings.json'


def load_settings():
    try:
        data = json.loads(settings_path().read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data):
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, path)
