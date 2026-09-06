"""Bounded, local UI preferences; corrupt files fall back to defaults."""
import json
import re
from pathlib import Path

DEFAULTS = {'theme': 'dark', 'font_size': 10}
LIGHT = {'#101522':'#f3f6fc', '#e8edf8':'#162339', '#79dac8':'#087764',
         '#99a8c4':'#536580', '#1a2233':'#ffffff', '#2b3850':'#d2dbea',
         '#293750':'#e6edf7', '#3a4b67':'#bccbdd', '#364967':'#d9e7f9',
         '#86a8e5':'#4a7fca', '#18243a':'#d3e1f2', '#72dbc4':'#97e7d5',
         '#092c2b':'#12332e', '#9ae9d9':'#acecde', '#63728b':'#8a96a8',
         '#1f293a':'#e8edf4', '#111a2b':'#ffffff', '#485974':'#a4b6cf',
         '#1a263b':'#ffffff', '#345170':'#cce2f8', '#111a29':'#ffffff',
         '#385776':'#cae1fa', '#9aabc7':'#5b6c84', '#182033':'#e5ecf6',
         '#2a3a50':'#d6ece7', '#8de4d0':'#08644f', '#151d2e':'#edf2f9',
         '#445571':'#b3c2d8'}


def load_preferences(folder):
    try:
        path = Path(folder) / 'ui.json'
        if path.stat().st_size > 65536:
            return dict(DEFAULTS)
        result = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(result, dict):
            return dict(DEFAULTS)
        theme = result.get('theme', 'dark')
        font = result.get('font_size', 10)
        result['theme'] = theme if theme in ('dark', 'light') else 'dark'
        result['font_size'] = max(9, min(14, font)) if type(font) is int else 10
        return result
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_preferences(folder, settings):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / 'ui.json'
    temporary = folder / 'ui.json.tmp'
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(target)


def style_for(base, theme, font_size):
    css = base + '''
QTableWidget, QLineEdit, QListWidget { background: #111a29; border: 1px solid #485974; border-radius: 6px; padding: 4px; }
QHeaderView::section { background: #293750; color: #e8edf8; padding: 7px; border: 1px solid #3a4b67; }
QTableCornerButton::section { background: #293750; border: 1px solid #3a4b67; }
QTableWidget::item:selected, QListWidget::item:selected { background: #345170; color: #e8edf8; }
QSpinBox { padding: 6px; border: 1px solid #485974; border-radius: 5px; }
'''
    if theme == 'light':
        css = re.sub(r'#[0-9a-fA-F]{6}', lambda match: LIGHT.get(match[0].lower(), match[0]), css)
    css = re.sub(r'font-size: (\d+)pt', lambda match: f'font-size: {round(int(match[1]) * font_size / 10)}pt', css)
    return css
