"""Shared Matplotlib configuration for generated figures."""
from __future__ import annotations

from pathlib import Path


_WINDOWS_FONT_FILES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
)

_FONT_FAMILIES = (
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "Noto Sans SC",
    "WenQuanYi Micro Hei",
    "Arial Unicode MS",
    "DejaVu Sans",
)


def configure_matplotlib_fonts() -> None:
    """Configure Matplotlib so Chinese labels render instead of tofu boxes."""
    try:
        import matplotlib
        from matplotlib import font_manager
    except Exception:
        return

    for font_path in _WINDOWS_FONT_FILES:
        path = Path(font_path)
        if not path.exists():
            continue
        try:
            font_manager.fontManager.addfont(str(path))
        except Exception:
            continue

    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = list(_FONT_FAMILIES)
    matplotlib.rcParams["axes.unicode_minus"] = False
