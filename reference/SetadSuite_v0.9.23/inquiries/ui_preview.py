"""v0.9.14: in-app preview window for a need's downloaded attachments.

A separate, non-modal window (it never touches the layout of the main window):
PDF (QtPdf), images, text/CSV, Word (.docx) and Excel (.xlsx) as plain content, ZIP/7z/RAR as a file list;
anything else offers «باز کردن با برنامهٔ ویندوز». Nothing is executed or extracted.
"""
from __future__ import annotations

import html
import shutil
import tempfile
import zipfile
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QImageReader, QPixmap, QTransform
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QScrollArea, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget, QHeaderView, QAbstractItemView, QApplication,
)

from storage import load_manifest, safe_filename
from ui_kit import button, fa, hline, label, rtl

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
TEXT_EXT = {".txt", ".csv", ".log", ".md", ".json", ".xml", ".ini"}
MAX_OFFICE_BYTES = 40 * 1024 * 1024
MAX_EXTRACT_BYTES = 200 * 1024 * 1024
MAX_TEXT_BYTES = 1024 * 1024
MAX_TABLE_ROWS, MAX_TABLE_COLS = 500, 40

_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


ARCHIVE_EXT = {".zip", ".7z", ".rar"}


class ArcMember:
    """One file inside an archive: shown name, size, encrypted flag and the backend's own handle."""
    __slots__ = ("name", "size", "enc", "ref")

    def __init__(self, name: str, size: int, enc: bool, ref):
        self.name, self.size, self.enc, self.ref = name, size, enc, ref


class ArchiveError(Exception):
    pass


def _zip_display(info: zipfile.ZipInfo) -> str:
    """Names without the UTF-8 flag are decoded as cp437 by zipfile; recover Persian names written in cp1256."""
    name = info.filename
    if info.flag_bits & 0x800:
        return name
    try:
        raw = name.encode("cp437")
    except UnicodeEncodeError:
        return name
    for enc in ("utf-8", "cp1256"):
        try:
            fixed = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if any("\u0600" <= ch <= "\u06ff" for ch in fixed):
            return fixed
    return name


def _copy_limited(src, dest: Path):
    copied = 0
    with dest.open("wb") as out:
        while True:
            chunk = src.read(1024 * 256)
            if not chunk:
                break
            copied += len(chunk)
            if copied > MAX_EXTRACT_BYTES:
                raise ArchiveError("حجم فایل بیش از حد مجاز است")
            out.write(chunk)


class ZipArchive:
    def __init__(self, path: Path):
        self.path = path

    def members(self) -> list[ArcMember]:
        with zipfile.ZipFile(str(self.path)) as z:
            return [ArcMember(_zip_display(i), i.file_size, bool(i.flag_bits & 1), i)
                    for i in z.infolist()[:3000] if not i.is_dir()]

    def extract(self, m: ArcMember, dest: Path):
        with zipfile.ZipFile(str(self.path)) as z, z.open(m.ref) as src:
            _copy_limited(src, dest)


class SevenZipArchive:
    def __init__(self, path: Path):
        self.path = path

    @staticmethod
    def _lib():
        try:
            import py7zr
            return py7zr
        except ImportError:
            raise ArchiveError("برای پیش‌نمایش 7z کتابخانهٔ py7zr نصب نیست (pip install py7zr).")

    def members(self) -> list[ArcMember]:
        py7zr = self._lib()
        try:
            with py7zr.SevenZipFile(str(self.path)) as z:
                enc = bool(z.needs_password())
                return [ArcMember(f.filename, int(f.uncompressed or 0), enc, f.filename)
                        for f in z.list() if not f.is_directory][:3000]
        except py7zr.exceptions.PasswordRequired:
            raise ArchiveError("این فایل 7z رمز دارد و داخل برنامه باز نمی‌شود.")

    def extract(self, m: ArcMember, dest: Path):
        py7zr = self._lib()
        scratch = Path(tempfile.mkdtemp(prefix="arc7z_", dir=str(dest.parent)))
        try:
            with py7zr.SevenZipFile(str(self.path)) as z:
                z.extract(path=str(scratch), targets=[m.ref])
            found = [f for f in scratch.rglob("*") if f.is_file()]
            if not found:
                raise ArchiveError("فایل از آرشیو بیرون نیامد.")
            if found[0].stat().st_size > MAX_EXTRACT_BYTES:
                raise ArchiveError("حجم فایل بیش از حد مجاز است")
            shutil.move(str(found[0]), str(dest))
        finally:
            shutil.rmtree(scratch, ignore_errors=True)


def _rar_tools() -> dict:
    """Extractors found on this computer: UnRAR/WinRAR, 7-Zip, Windows' own tar.exe (bsdtar reads RAR) and unar."""
    import os
    pf = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")

    def first(*cands):
        for c in cands:
            hit = shutil.which(c)
            if hit:
                return hit
            if os.path.isabs(c) and Path(c).is_file():
                return c
        return None
    tools = {
        "unrar": first("unrar", "UnRAR.exe", *[str(Path(b) / "WinRAR" / "UnRAR.exe") for b in pf]),
        "7z": first("7z", "7za", "7zz", *[str(Path(b) / "7-Zip" / "7z.exe") for b in pf]),
        "bsdtar": first("bsdtar", str(Path(sysroot) / "System32" / "tar.exe")),
    }
    return {k: v for k, v in tools.items() if v}


def _run_to_file(cmd: list[str], dest: Path):
    import subprocess
    import sys
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=flags) as pr:
        try:
            _copy_limited(pr.stdout, dest)
        finally:
            pr.stdout.close()
        if pr.wait() != 0:
            raise ArchiveError("ابزار باز کردن rar خطا داد.")


class RarArchive:
    """Listing is pure Python (rarfile); extracting a member needs one of the external tools above."""

    def __init__(self, path: Path):
        self.path = path

    @staticmethod
    def _lib():
        try:
            import rarfile
            return rarfile
        except ImportError:
            raise ArchiveError("برای پیش‌نمایش rar کتابخانهٔ rarfile نصب نیست (pip install rarfile).")

    def members(self) -> list[ArcMember]:
        rarfile = self._lib()
        try:
            with rarfile.RarFile(str(self.path)) as r:
                return [ArcMember(i.filename, int(i.file_size or 0), bool(i.needs_password()), i)
                        for i in r.infolist()[:3000] if not i.is_dir()]
        except rarfile.PasswordRequired:
            raise ArchiveError("این فایل rar رمز دارد و داخل برنامه باز نمی‌شود.")
        except rarfile.Error as exc:
            raise ArchiveError("این فایل rar خراب است یا قابل خواندن نیست.") from exc

    def extract(self, m: ArcMember, dest: Path):
        tools = _rar_tools()
        if not tools:
            raise ArchiveError("برای باز کردن rar به یکی از برنامه‌های WinRAR، 7-Zip یا UnRAR نیاز است؛ "
                               "با «باز کردن با برنامهٔ ویندوز» ببینید.")
        arc, name = str(self.path), m.name
        cmds = []
        if "bsdtar" in tools:
            cmds.append([tools["bsdtar"], "-xOf", arc, name])
        if "7z" in tools:
            cmds.append([tools["7z"], "e", "-so", "-y", arc, name])
        if "unrar" in tools:
            cmds.append([tools["unrar"], "p", "-inul", "-y", arc, name])
        last = None
        for cmd in cmds:      # the first tool that yields the exact size wins (older 7-Zip cannot read RAR5)
            try:
                _run_to_file(cmd, dest)
                if m.size and dest.stat().st_size != m.size:
                    raise ArchiveError("خروجی ناقص بود.")
                return
            except Exception as exc:
                last = exc
                try:
                    dest.unlink()
                except OSError:
                    pass
        raise ArchiveError(str(last) if last else "باز کردن فایل ممکن نشد.")


def open_archive(path: Path):
    ext = path.suffix.lower()
    return {".zip": ZipArchive, ".7z": SevenZipArchive, ".rar": RarArchive}[ext](path)


def find_local(folder: Path, name: str) -> Path | None:
    """The downloaded copy of attachment `name` in `folder` (None if it was not downloaded). Never creates anything."""
    try:
        if not folder.is_dir():
            return None
        for entry in load_manifest(folder).values():
            if isinstance(entry, dict) and entry.get("original_name") == name:
                p = folder / str(entry.get("saved_as", ""))
                if p.is_file() and p.stat().st_size > 0:
                    return p
        p = folder / safe_filename(name)
        return p if p.is_file() and p.stat().st_size > 0 else None
    except OSError:
        return None


def _human_size(n: int) -> str:
    for unit in ("بایت", "کیلوبایت", "مگابایت", "گیگابایت"):
        if n < 1024 or unit == "گیگابایت":
            return (f"{n:.0f}" if unit == "بایت" else f"{n:.1f}").translate(_FA) + " " + unit
        n /= 1024
    return ""


def _read_text(path: Path) -> str:
    raw = path.read_bytes()[:MAX_TEXT_BYTES]
    for enc in ("utf-8-sig", "utf-16", "cp1256", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("utf-8", "replace")



class PdfPagesView(QScrollArea):
    """v0.9.14: lazy multi-page PDF view with zoom, fit-to-width and 90° rotation (QPdfView cannot rotate)."""
    GAP, MARGIN = 10, 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(False)
        self._holder = QWidget()
        self._holder.setStyleSheet("background:#8A8F98;")
        self.setWidget(self._holder)
        self._doc = None
        self._labels: list[QLabel] = []
        self._tops: list[int] = []
        self._rot = 0
        self._fit_mode = True
        self._scale = 96 / 72                    # pixels per PDF point
        self._cache: dict[int, tuple] = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._render_visible)
        self.verticalScrollBar().valueChanged.connect(lambda *_: self._timer.start())

    # -- model
    def set_document(self, doc):
        self._doc = doc
        for lb in self._labels:
            lb.deleteLater()
        self._labels = []
        self._cache.clear()
        for _ in range(doc.pageCount()):
            lb = QLabel(self._holder)
            lb.setStyleSheet("background:#FFFFFF;")
            lb.setAlignment(Qt.AlignCenter)
            lb.show()
            self._labels.append(lb)
        self._fit_mode = True
        self.verticalScrollBar().setValue(0)
        self._relayout()

    def set_rotation(self, deg: int):
        self._rot = deg % 360
        self._relayout(keep_position=True)

    def rotation(self) -> int:
        return self._rot

    def fit(self):
        self._fit_mode = True
        self._relayout(keep_position=True)

    def zoom_by(self, mult: float):
        self._fit_mode = False
        self._scale = max(0.15, min(self._scale * mult, 8.0))
        self._relayout(keep_position=True)

    def _size_pt(self, i: int):
        sz = self._doc.pagePointSize(i)
        w, h = sz.width() or 595.0, sz.height() or 842.0
        return (h, w) if self._rot in (90, 270) else (w, h)

    def _relayout(self, keep_position: bool = False):
        if self._doc is None or not self._labels:
            return
        bar = self.verticalScrollBar()
        ratio = bar.value() / bar.maximum() if keep_position and bar.maximum() else 0.0
        n = len(self._labels)
        if self._fit_mode:
            widest = max(self._size_pt(i)[0] for i in range(min(n, 50)))
            avail = self.viewport().width() - 2 * self.MARGIN
            self._scale = max(0.15, min(avail / widest, 8.0))
        sizes = [(int(self._size_pt(i)[0] * self._scale), int(self._size_pt(i)[1] * self._scale)) for i in range(n)]
        width = max(self.viewport().width(), max(w for w, _ in sizes) + 2 * self.MARGIN)
        y = self.GAP
        self._tops = []
        for lb, (w, h) in zip(self._labels, sizes):
            lb.setGeometry((width - w) // 2, y, w, h)
            lb.clear()
            self._tops.append(y)
            y += h + self.GAP
        self._holder.resize(width, y)
        self._cache.clear()
        bar.setValue(int(ratio * bar.maximum()))
        self._timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fit_mode:
            self._relayout(keep_position=True)
        else:
            self._timer.start()

    # -- rendering (only the pages near the viewport)
    def _render_visible(self):
        if self._doc is None or not self._labels:
            return
        from PySide6.QtPdf import QPdfDocumentRenderOptions
        top = self.verticalScrollBar().value()
        bottom = top + self.viewport().height()
        margin = self.viewport().height()
        rot = {0: QPdfDocumentRenderOptions.Rotation.None_, 90: QPdfDocumentRenderOptions.Rotation.Clockwise90,
               180: QPdfDocumentRenderOptions.Rotation.Clockwise180, 270: QPdfDocumentRenderOptions.Rotation.Clockwise270}[self._rot]
        dpr = self.devicePixelRatioF()
        for i, lb in enumerate(self._labels):
            y0, y1 = self._tops[i], self._tops[i] + lb.height()
            near = y1 >= top - margin and y0 <= bottom + margin
            if near and i not in self._cache:
                opts = QPdfDocumentRenderOptions()
                opts.setRotation(rot)
                img = self._doc.render(i, QSize(int(lb.width() * dpr), int(lb.height() * dpr)), opts)
                pix = QPixmap.fromImage(img)
                pix.setDevicePixelRatio(dpr)
                lb.setPixmap(pix)
                self._cache[i] = True
            elif not near and i in self._cache and (y1 < top - 3 * margin or y0 > bottom + 3 * margin):
                lb.clear()
                del self._cache[i]

    def page_count(self) -> int:
        return len(self._labels)


class PreviewWindow(QDialog):
    """Non-modal preview of the files of one need; ‹ › moves between them."""

    def __init__(self, ui, need_no: str, files: list[tuple[str, Path]], start: int = 0):
        super().__init__(None, Qt.Window)
        self.ui = ui
        self.need_no = need_no
        self.files = files
        self.index = start
        self._zoom = 1.0
        self._pixmap: QPixmap | None = None
        self._pixmap_src: QPixmap | None = None
        self._pdf = None
        self._rotations: dict[str, int] = {}
        self._cur_path: Path | None = None
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setLayoutDirection(Qt.RightToLeft)
        try:                                   # a top-level window does not inherit the page's style sheet
            from ui_kit import build_stylesheet
            self.setStyleSheet(build_stylesheet(QApplication.font().family()))
        except Exception:
            pass
        self._tmp: Path | None = None             # extracted zip members live here until the window closes
        self._trail: list[tuple[str, Path]] = []  # (container title, container path) while viewing a file inside a zip
        self._zip_members: list = []
        self._zip_path: Path | None = None
        self.setMinimumSize(560, 420)
        self.resize(1000, 760)
        try:
            geo = QSettings("SetadiranManager", "SetadiranManager").value("preview_geometry")
            if geo:
                self.restoreGeometry(geo)
        except Exception:
            pass

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.b_prev = button("", "arrow_prev", None, "سند قبلی")
        self.b_next = button("", "arrow_next", None, "سند بعدی")
        self.b_prev.clicked.connect(lambda: self.go(self.index - 1))
        self.b_next.clicked.connect(lambda: self.go(self.index + 1))
        self.counter = label("", "muted")
        self.title = label("", "detailSection")
        self.title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bar.addWidget(self.b_prev)
        bar.addWidget(self.b_next)
        bar.addWidget(self.counter)
        self.b_back = button("بازگشت به فایل فشرده", "arrow_prev", None, "برگشت به فهرست فایل فشرده")
        self.b_back.clicked.connect(self._back)
        self.b_back.hide()
        bar.addWidget(self.b_back)
        bar.addStretch(1)
        self.b_zoom_out = button("−", None, None, "کوچک‌نمایی")
        self.b_zoom_in = button("+", None, None, "بزرگ‌نمایی")
        self.b_fit = button("عرض صفحه", None, None, "تناسب با عرض پنجره")
        for b in (self.b_zoom_out, self.b_zoom_in):
            b.setFixedWidth(38)
        self.b_zoom_out.clicked.connect(lambda: self._zoom_by(1 / 1.25))
        self.b_zoom_in.clicked.connect(lambda: self._zoom_by(1.25))
        self.b_fit.clicked.connect(self._fit)
        self.b_rot_l = button("", "rotate_ccw", None, "چرخش ۹۰ درجه به چپ")
        self.b_rot_r = button("", "rotate_cw", None, "چرخش ۹۰ درجه به راست")
        self.b_rot_l.clicked.connect(lambda: self._rotate(-90))
        self.b_rot_r.clicked.connect(lambda: self._rotate(90))
        self.b_external = button("باز کردن با ویندوز", "external", None, "باز کردن با برنامهٔ پیش‌فرض ویندوز")
        self.b_external.clicked.connect(self._open_external)
        self.b_folder = button("نمایش در پوشه", "folder", None)
        self.b_folder.clicked.connect(self._open_folder)
        for b in (self.b_rot_l, self.b_rot_r, self.b_zoom_out, self.b_zoom_in, self.b_fit, self.b_external, self.b_folder):
            bar.addWidget(b)
        root.addWidget(self.title)
        root.addLayout(bar)
        root.addWidget(hline())

        self.stack = QStackedWidget()
        self.page_msg = QWidget()
        ml = QVBoxLayout(self.page_msg)
        ml.addStretch(1)
        self.msg = label("", "muted", wrap=True)
        self.msg.setAlignment(Qt.AlignCenter)
        ml.addWidget(self.msg)
        ml.addStretch(1)
        self.stack.addWidget(self.page_msg)                       # 0 message
        self.pdf_host = QWidget()                                  # 1 PDF (built lazily)
        QVBoxLayout(self.pdf_host).setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.pdf_host)
        self.img_scroll = QScrollArea()                            # 2 image
        self.img_scroll.setAlignment(Qt.AlignCenter)
        self.img_label = QLabel()
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_scroll.setWidget(self.img_label)
        self.stack.addWidget(self.img_scroll)
        self.text_view = QPlainTextEdit()                          # 3 text
        self.text_view.setReadOnly(True)
        self.stack.addWidget(self.text_view)
        self.rich_view = QTextBrowser()                            # 4 Word
        self.rich_view.setOpenLinks(False)
        self.stack.addWidget(self.rich_view)
        self.sheet_host = QWidget()                                # 5 Excel / ZIP table
        sl = QVBoxLayout(self.sheet_host)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)
        self.sheet_combo = QComboBox()
        self.sheet_combo.currentIndexChanged.connect(self._sheet_changed)
        sl.addWidget(self.sheet_combo)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        sl.addWidget(self.table, 1)
        self.zip_bar = QWidget()
        zl = QHBoxLayout(self.zip_bar)
        zl.setContentsMargins(0, 0, 0, 0)
        zl.setSpacing(8)
        self.b_zip_prev = button("پیش‌نمایش", "eye", None, "فایل انتخاب‌شده در پوشهٔ موقت باز و پیش‌نمایش می‌شود")
        self.b_zip_prev.setEnabled(False)
        self.b_zip_prev.clicked.connect(self._preview_zip_member)
        self.zip_note = label("یک فایل را انتخاب کنید؛ دابل‌کلیک هم پیش‌نمایش را باز می‌کند.", "muted")
        zl.addWidget(self.b_zip_prev)
        zl.addWidget(self.zip_note, 1)
        sl.addWidget(self.zip_bar)
        self.zip_bar.hide()
        self.table.itemSelectionChanged.connect(self._zip_selection)
        self.table.cellDoubleClicked.connect(lambda *_: self._preview_zip_member())
        self.stack.addWidget(self.sheet_host)
        root.addWidget(self.stack, 1)
        self._sheets: dict[str, list[list[str]]] = {}
        self.go(start)

    # ------------------------------------------------------------------ navigation
    def go(self, i: int):
        if not self.files:
            return
        self.index = max(0, min(i, len(self.files) - 1))
        self._trail = []
        self.b_back.hide()
        name, path = self.files[self.index]
        self._current_title = name
        self.setWindowTitle(rtl(f"پیش‌نمایش — {name}"))
        self.title.setText(rtl(f"{name}   ({_human_size(path.stat().st_size) if path.exists() else ''})"))
        self.counter.setText(rtl(f"{str(self.index + 1).translate(_FA)} از {str(len(self.files)).translate(_FA)}"))
        self.b_prev.setEnabled(self.index > 0)
        self.b_next.setEnabled(self.index < len(self.files) - 1)
        self._load(path)

    def show_file(self, name: str):
        for i, (n, _) in enumerate(self.files):
            if n == name:
                self.go(i)
                return

    def _message(self, text: str):
        self.msg.setText(rtl(text))
        self.stack.setCurrentIndex(0)
        self._set_zoom_enabled(False)

    def _set_zoom_enabled(self, on: bool):
        for b in (self.b_zoom_in, self.b_zoom_out, self.b_fit, self.b_rot_l, self.b_rot_r):
            b.setVisible(on)

    # ------------------------------------------------------------------ loading
    def _load(self, path: Path):
        ext = path.suffix.lower()
        self._cur_path = path
        self.zip_bar.hide()
        self._set_zoom_enabled(False)
        try:
            if not path.is_file():
                self._message("فایل پیدا نشد؛ شاید پاک یا جابه‌جا شده است.")
            elif ext == ".pdf":
                self._load_pdf(path)
            elif ext in IMAGE_EXT:
                self._load_image(path)
            elif ext in TEXT_EXT:
                self.text_view.setPlainText(_read_text(path))
                self.stack.setCurrentIndex(3)
            elif ext == ".docx":
                self._load_docx(path)
            elif ext in (".xlsx", ".xlsm"):
                self._load_xlsx(path)
            elif ext in ARCHIVE_EXT:
                self._load_zip(path)
            else:
                self._message("برای این نوع فایل پیش‌نمایش داخل برنامه نداریم. با دکمهٔ «باز کردن با برنامهٔ ویندوز» ببینید.")
        except Exception as exc:  # a damaged file must never crash the app
            self._message(f"این فایل قابل نمایش نبود: {str(exc).splitlines()[0][:150] if str(exc) else 'خطای ناشناخته'}")

    def _load_pdf(self, path: Path):
        from PySide6.QtPdf import QPdfDocument
        if self._pdf is None:
            self._doc = QPdfDocument(self)
            self._pdf = PdfPagesView(self.pdf_host)
            self.pdf_host.layout().addWidget(self._pdf)
        err = self._doc.load(str(path))
        if err != QPdfDocument.Error.None_:
            if err == QPdfDocument.Error.IncorrectPassword:
                self._message("این PDF رمز دارد و داخل برنامه باز نمی‌شود. با برنامهٔ ویندوز باز کنید.")
            else:
                self._message("این PDF خراب است یا قابل خواندن نیست.")
            return
        self.stack.setCurrentIndex(1)
        self._set_zoom_enabled(True)
        self._pdf._rot = self._rotations.get(str(path), 0)
        self._pdf.set_document(self._doc)

    def _load_image(self, path: Path):
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        img = reader.read()
        if img.isNull():
            self._message("تصویر خوانده نشد: " + (reader.errorString() or "قالب ناشناخته"))
            return
        self._pixmap_src = QPixmap.fromImage(img)
        self._pixmap = self._rotated(self._pixmap_src, self._rotations.get(str(path), 0))
        self.stack.setCurrentIndex(2)
        self._set_zoom_enabled(True)
        self._fit()

    def _load_docx(self, path: Path):
        if path.stat().st_size > MAX_OFFICE_BYTES:
            self._message("این فایل Word برای پیش‌نمایش بزرگ است. با برنامهٔ ویندوز باز کنید.")
            return
        try:
            import docx
        except ImportError:
            self._message("برای پیش‌نمایش Word بستهٔ python-docx لازم است؛ با برنامهٔ ویندوز باز کنید.")
            return
        d = docx.Document(str(path))
        parts = ['<div dir="rtl">']
        for block in d.element.body.iterchildren():
            tag = block.tag.rsplit("}", 1)[-1]
            if tag == "p":
                text = "".join(t.text or "" for t in block.iter() if t.tag.endswith("}t"))
                if text.strip():
                    parts.append(f"<p>{html.escape(fa(text))}</p>")
            elif tag == "tbl":
                parts.append('<table border="1" cellspacing="0" cellpadding="5" width="100%">')
                for tr in block.iter():
                    if tr.tag.endswith("}tr"):
                        cells = []
                        for tc in tr.iterchildren():
                            if tc.tag.endswith("}tc"):
                                cells.append("".join(t.text or "" for t in tc.iter() if t.tag.endswith("}t")))
                        parts.append("<tr>" + "".join(f"<td>{html.escape(fa(c))}</td>" for c in cells) + "</tr>")
                parts.append("</table>")
            if len(parts) > 6000:
                parts.append("<p>… ادامهٔ سند نمایش داده نشد.</p>")
                break
        parts.append("</div>")
        self.rich_view.setHtml("".join(parts))
        self.stack.setCurrentIndex(4)

    def _load_xlsx(self, path: Path):
        if path.stat().st_size > MAX_OFFICE_BYTES:
            self._message("این فایل Excel برای پیش‌نمایش بزرگ است. با برنامهٔ ویندوز باز کنید.")
            return
        try:
            import openpyxl
        except ImportError:
            self._message("برای پیش‌نمایش Excel بستهٔ openpyxl لازم است؛ با برنامهٔ ویندوز باز کنید.")
            return
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        self._sheets = {}
        try:
            for ws in wb.worksheets:
                rows: list[list[str]] = []
                for r in ws.iter_rows(max_row=MAX_TABLE_ROWS, max_col=MAX_TABLE_COLS, values_only=True):
                    rows.append(["" if v is None else str(v) for v in r])
                while rows and not any(rows[-1]):
                    rows.pop()
                self._sheets[ws.title] = rows
        finally:
            wb.close()
        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        self.sheet_combo.addItems(list(self._sheets))
        self.sheet_combo.blockSignals(False)
        self.sheet_combo.setVisible(len(self._sheets) > 1)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.verticalHeader().setVisible(True)
        self._sheet_changed()
        self.stack.setCurrentIndex(5)

    @staticmethod
    def _zip_name(info) -> str:
        return _zip_display(info)

    def _load_zip(self, path: Path):
        self._zip_path = path
        try:
            self._arc = open_archive(path)
            members = self._arc.members()
        except ArchiveError as exc:
            self._message(str(exc))
            return
        if not members:
            self._message("این فایل فشرده فایلی ندارد یا خراب است.")
            return
        self._zip_members = members
        self.sheet_combo.hide()
        self._sheets = {}
        self.table.clear()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnCount(2)
        self.table.setRowCount(len(members))
        self.table.setHorizontalHeaderLabels(["نام فایل", "اندازه"])
        for r, m in enumerate(members):
            self.table.setItem(r, 0, QTableWidgetItem(m.name + ("  🔒" if m.enc else "")))
            self.table.setItem(r, 1, QTableWidgetItem(_human_size(m.size)))
        self.table.setColumnWidth(0, max(300, self.table.width() - 180))
        self.table.setColumnWidth(1, 130)
        self.zip_bar.show()
        self.b_zip_prev.setEnabled(False)
        self.stack.setCurrentIndex(5)

    def _zip_selection(self):
        if self.zip_bar.isVisible():
            self.b_zip_prev.setEnabled(bool(self.table.selectedItems()))

    def _preview_zip_member(self):
        rows = sorted({i.row() for i in self.table.selectedItems()})
        if not rows or self._zip_path is None or rows[0] >= len(self._zip_members):
            return
        m = self._zip_members[rows[0]]
        shown = m.name
        if m.enc:
            self.zip_note.setText(rtl("این فایل رمز دارد و داخل برنامه باز نمی‌شود."))
            return
        if m.size > MAX_EXTRACT_BYTES:
            self.zip_note.setText(rtl("این فایل برای باز کردن موقت بزرگ است."))
            return
        try:
            if self._tmp is None:
                self._tmp = Path(tempfile.mkdtemp(prefix="setad_preview_"))
            dest = self._tmp / f"{len(list(self._tmp.iterdir())) + 1}_{safe_filename(Path(shown.replace(chr(92), '/')).name)}"
            open_archive(self._zip_path).extract(m, dest)
        except Exception as exc:
            self.zip_note.setText(rtl("باز کردن این فایل شدنی نبود: " + (str(exc).splitlines()[0][:160] if str(exc) else "خطا")))
            return
        self._trail.append((self._current_title, self._zip_path))
        self._current_title = f"{self._current_title} ‹ {Path(shown.replace(chr(92), '/')).name}"
        self.title.setText(rtl(f"{self._current_title}   ({_human_size(dest.stat().st_size)})"))
        self.b_back.show()
        self._load(dest)

    def _back(self):
        if not self._trail:
            return
        title, container = self._trail.pop()
        self._current_title = title
        self.title.setText(rtl(f"{title}"))
        if not self._trail:
            self.b_back.hide()
        self._load(container)

    def _sheet_changed(self):
        rows = self._sheets.get(self.sheet_combo.currentText(), [])
        ncols = max((len(r) for r in rows), default=0)
        self.table.clear()
        self.table.setRowCount(len(rows))
        self.table.setColumnCount(ncols)
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(fa(val)[:300]))
        self.table.resizeColumnsToContents()
        for c in range(ncols):
            if self.table.columnWidth(c) > 420:
                self.table.setColumnWidth(c, 420)

    # ------------------------------------------------------------------ zoom
    @staticmethod
    def _rotated(pix: QPixmap, deg: int) -> QPixmap:
        return pix if deg % 360 == 0 else pix.transformed(QTransform().rotate(deg), Qt.SmoothTransformation)

    def _fit(self):
        if self.stack.currentIndex() == 1 and self._pdf is not None:
            self._pdf.fit()
        elif self._pixmap is not None:
            avail = max(100, self.img_scroll.viewport().width() - 8)
            self._zoom = min(1.0, avail / max(1, self._pixmap.width()))
            self._apply_image_zoom()

    def _zoom_by(self, mult: float):
        if self.stack.currentIndex() == 1 and self._pdf is not None:
            self._pdf.zoom_by(mult)
        elif self._pixmap is not None:
            self._zoom = max(0.05, min(self._zoom * mult, 8.0))
            self._apply_image_zoom()

    def _rotate(self, delta: int):
        if self._cur_path is None:
            return
        key = str(self._cur_path)
        deg = (self._rotations.get(key, 0) + delta) % 360
        self._rotations[key] = deg
        if self.stack.currentIndex() == 1 and self._pdf is not None:
            self._pdf.set_rotation(deg)
        elif self._pixmap_src is not None and self.stack.currentIndex() == 2:
            self._pixmap = self._rotated(self._pixmap_src, deg)
            self._fit()

    def _apply_image_zoom(self):
        if self._pixmap is None:
            return
        size = QSize(int(self._pixmap.width() * self._zoom), int(self._pixmap.height() * self._zoom))
        self.img_label.setPixmap(self._pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.img_label.resize(size)

    # ------------------------------------------------------------------ external
    def _open_external(self):
        if self.files:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.files[self.index][1])))

    def _open_folder(self):
        if self.files:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.files[self.index][1].parent)))

    def closeEvent(self, event):
        try:
            QSettings("SetadiranManager", "SetadiranManager").setValue("preview_geometry", self.saveGeometry())
        except Exception:
            pass
        if self._tmp is not None:
            shutil.rmtree(self._tmp, ignore_errors=True)
        wins = getattr(self.ui, "_preview_windows", None)
        if isinstance(wins, dict) and wins.get(self.need_no) is self:
            wins.pop(self.need_no, None)
        super().closeEvent(event)


def open_files_preview(ui, key: str, files: list[tuple[str, Path]], start: int = 0) -> PreviewWindow | None:
    """Open (or reuse) the preview window identified by `key`; `files` = [(shown name, local path)]."""
    if not files:
        return None
    start = max(0, min(start, len(files) - 1))
    wins = getattr(ui, "_preview_windows", None)
    if wins is None:
        wins = ui._preview_windows = {}
    win = wins.get(key)
    if win is not None:
        try:
            win.files = files
            win.go(start)
            win.show()
            win.raise_()
            win.activateWindow()
            return win
        except RuntimeError:           # window already destroyed
            wins.pop(key, None)
    win = PreviewWindow(ui, key, files, start)
    wins[key] = win
    win.show()
    return win


def open_preview(ui, need_no: str, names: list[str], current: str) -> PreviewWindow | None:
    """Purchase page: preview of the downloaded attachments of `need_no`, starting at attachment `current`."""
    folder = ui.output_dir / need_no
    files = []
    for n in names:
        p = find_local(folder, n)
        if p is not None:
            files.append((n, p))
    if not any(n == current for n, _ in files):
        return None
    return open_files_preview(ui, need_no, files, next(i for i, (n, _) in enumerate(files) if n == current))
