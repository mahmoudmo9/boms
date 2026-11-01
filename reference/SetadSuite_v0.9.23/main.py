"""سامانه مناقصات و استعلام‌های ستاد — entry point.

Sections:
  * استعلام‌ها (خرید): the inquiries app (needs board → RFQs → proforma), folder «inquiries».
  * مناقصه‌ها: the tenders app (etend.setadiran.ir), package «setad_tender».
Each section keeps its own database and settings in the same places as the stand-alone apps,
so existing data shows up unchanged."""
import sys
import traceback
from pathlib import Path

BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
sys.path.insert(0, str(BASE))
sys.path.insert(1, str(BASE / 'inquiries'))   # the inquiries app uses top-level imports

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


def load_fonts():
    fam = None
    for folder in (BASE / 'assets' / 'fonts', BASE / 'inquiries' / 'fonts'):
        for path in sorted(folder.glob('*.ttf')):
            fid = QFontDatabase.addApplicationFont(str(path))
            fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            if fams and fam is None and 'FD' not in fams[0]:
                fam = fams[0]
    return fam or 'Tahoma'


def make_inquiries(tenders):
    """The inquiries section, running its browser tasks in the tenders section's browser thread
    (one shared Setad browser, one active role at a time)."""
    import ui_kit
    from app import ManagerUI
    from engine import BrowserEngine
    tw = getattr(tenders, 'worker', None)

    class SharedEngine(BrowserEngine):
        def start(self):
            tw.attach_inquiries(self)

        def is_alive(self):
            return bool(tw.isRunning() and tw.inq_alive)

    factory = (lambda tasks, events, cancel, home: SharedEngine(tasks, events, cancel, home)) if tw is not None else None
    w = ManagerUI(engine_factory=factory, embedded=True)
    w.setStyleSheet(ui_kit.build_stylesheet(ui_kit.load_fonts()))
    return w


def make_tenders():
    from setad_tender.ui import MainWindow
    return MainWindow(embedded=True)


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName('Setad Suite')
    app.setOrganizationName('Blue Alvand Industry')
    app.setLayoutDirection(Qt.RightToLeft)
    app.setStyle('Fusion')
    app.setQuitOnLastWindowClosed(False)
    font = QFont(load_fonts(), 10)
    font.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(font)
    from suite import design
    design.apply_tokens(design.saved_theme())        # one set of color tokens for every section
    from suite.shell import Shell
    win = Shell(make_inquiries, make_tenders)
    win.showMaximized()
    sys.exit(app.exec())


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log = Path.home() / 'SetadSuite-error.txt'
        log.write_text(traceback.format_exc(), encoding='utf-8')
        raise
