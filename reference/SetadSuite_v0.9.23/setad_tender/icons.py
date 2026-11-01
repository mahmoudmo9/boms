"""Tinted SVG icons (Lucide, ISC) rendered to QIcon at runtime."""
from __future__ import annotations
from functools import lru_cache
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer
from .icon_data import ICONS


def svg(name: str, color: str='#334155', stroke: float=2.0) -> bytes:
    inner=ICONS.get(name,ICONS['info'])
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{inner}</svg>').encode()


@lru_cache(maxsize=256)
def pixmap(name: str, color: str='#334155', size: int=18, stroke: float=2.0) -> QPixmap:
    ratio=2
    pm=QPixmap(size*ratio,size*ratio)
    pm.fill(Qt.transparent)
    renderer=QSvgRenderer(QByteArray(svg(name,color,stroke)))
    p=QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p,QRectF(0,0,size*ratio,size*ratio))
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def icon(name: str, color: str='#334155', size: int=18, disabled: str='#a7b4c4') -> QIcon:
    ic=QIcon()
    ic.addPixmap(pixmap(name,color,size),QIcon.Normal)
    ic.addPixmap(pixmap(name,disabled,size),QIcon.Disabled)
    return ic
