"""«محل ذخیرهٔ اسناد»: where purchase attachments and tender documents are kept.

The folder structure inside each root stays exactly as it is (only the root changes). Optionally the old
files are moved to the new root and every stored path in both databases is rewritten to the new place."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QVBoxLayout, QApplication)


def check_writable(path) -> tuple[bool, str]:
    """Create the folder if needed and try to write/delete a small file in it."""
    try:
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        probe = p / f'.setad-write-test-{uuid.uuid4().hex[:8]}'
        probe.write_bytes(b'ok')
        probe.unlink()
        free = shutil.disk_usage(p).free
        return True, f'قابل نوشتن • فضای آزاد: {free / 1024 ** 3:.1f} GB'
    except Exception as e:
        return False, f'قابل نوشتن نیست: {e}'


def move_tree(old, new) -> tuple[int, list[str]]:
    """Move everything inside `old` into `new` (merging folders). Existing files in `new` are never overwritten."""
    old, new = Path(old), Path(new)
    moved, problems = 0, []
    if not old.exists() or old.resolve() == new.resolve():
        return 0, []
    new.mkdir(parents=True, exist_ok=True)
    for child in list(old.iterdir()):
        target = new / child.name
        try:
            if child.is_dir() and target.exists():
                m, p = move_tree(child, target)
                moved += m
                problems += p
                try:
                    child.rmdir()
                except OSError:
                    pass
            elif target.exists():
                problems.append(f'وجود دارد و جابه‌جا نشد: {target}')
            else:
                shutil.move(str(child), str(target))
                moved += 1
        except Exception as e:
            problems.append(f'{child}: {e}')
    return moved, problems


_FORMS = (lambda x: x, lambda x: x.replace('\\', '/'), lambda x: x.replace('/', '\\'),
          lambda x: json.dumps(x)[1:-1], lambda x: json.dumps(x.replace('/', '\\'))[1:-1])


def rebase_paths(conn: sqlite3.Connection, old, new) -> int:
    """Rewrite every stored text value that contains the old root (plain, / or \\ separators, or JSON-escaped)."""
    changed = 0
    pairs = []
    for f in _FORMS:
        ov, nv = f(str(old)), f(str(new))
        if ov and (ov, nv) not in pairs:
            pairs.append((ov, nv))
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for t in tables:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")') if (r[2] or '').upper() in ('TEXT', '')]
        for c in cols:
            for ov, nv in pairs:
                cur = conn.execute(f'UPDATE "{t}" SET "{c}"=REPLACE("{c}",?,?) WHERE instr("{c}",?)>0', (ov, nv, ov))
                changed += max(0, cur.rowcount or 0)
    conn.commit()
    return changed


class StorageDialog(QDialog):
    """Two rows (purchase / tender): path, «تغییر…», writability state."""

    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self.setWindowTitle('محل ذخیرهٔ اسناد')
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(780, 330)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(12)
        t = QLabel('محل ذخیرهٔ اسناد')
        t.setStyleSheet('font-size:13pt; font-weight:800;')
        v.addWidget(t)
        n = QLabel('ساختار پوشه‌های داخل هر محل همان‌طور که هست می‌ماند (برای خرید: یک پوشه به نام شمارهٔ نیاز؛ برای مناقصه: '
                   'پوشهٔ هر فراخوان). با تغییر محل می‌توانید فایل‌های قبلی را هم منتقل کنید؛ مسیرهای ثبت‌شده در برنامه به‌روز می‌شوند.')
        n.setWordWrap(True)
        n.setStyleSheet('color:gray;')
        v.addWidget(n)
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(10)
        self.rows = {}
        for i, (key, title) in enumerate((('inq', 'پیوست‌های خرید (استعلام)'), ('ten', 'اسناد مناقصه'))):
            g.addWidget(QLabel(title), i * 2, 0)
            e = QLineEdit(str(self._current(key) or ''))
            e.setReadOnly(True)
            g.addWidget(e, i * 2, 1)
            b = QPushButton('تغییر…')
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.change(k))
            g.addWidget(b, i * 2, 2)
            o = QPushButton('باز کردن')
            o.setCursor(Qt.PointingHandCursor)
            o.clicked.connect(lambda _=False, k=key: self._open(k))
            g.addWidget(o, i * 2, 3)
            st = QLabel('')
            g.addWidget(st, i * 2 + 1, 1, 1, 3)
            self.rows[key] = (e, st)
        g.setColumnStretch(1, 1)
        v.addLayout(g)
        v.addStretch()
        bar = QHBoxLayout()
        bar.addStretch()
        close = QPushButton('بستن')
        close.clicked.connect(self.accept)
        bar.addWidget(close)
        v.addLayout(bar)
        self._refresh()

    # ------------------------------------------------------------------
    def _current(self, key):
        if key == 'inq':
            return getattr(self.shell.inq, 'output_dir', None)
        return getattr(self.shell.ten, 'download_path', None)

    def _open(self, key):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        p = self._current(key)
        if p:
            Path(p).mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _refresh(self):
        for key, (e, st) in self.rows.items():
            p = self._current(key)
            e.setText(str(p or '—'))
            if p:
                ok, msg = check_writable(p)
                st.setText(('✓ ' if ok else '✕ ') + msg)
                st.setStyleSheet(f"color:{'#15803d' if ok else '#b42318'};")
            else:
                st.setText('این بخش بارگذاری نشده است.')

    def change(self, key):
        old = self._current(key)
        if old is None:
            return
        new = QFileDialog.getExistingDirectory(self, 'انتخاب محل جدید', str(old))
        if not new or Path(new).resolve() == Path(old).resolve():
            return
        ok, msg = check_writable(new)
        if not ok:
            QMessageBox.warning(self, 'محل ذخیره', msg)
            return
        has_files = Path(old).exists() and any(Path(old).iterdir())
        move = False
        if has_files:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Question)
            box.setWindowTitle('فایل‌های قبلی')
            box.setText('فایل‌های فعلی هم به محل جدید منتقل شوند؟')
            box.setInformativeText(f'از:\n{old}\nبه:\n{new}\n\nساختار پوشه‌ها حفظ می‌شود و مسیرهای ثبت‌شده در برنامه به‌روز می‌شوند. '
                                   'فایلی که در مقصد هم‌نام داشته باشد جابه‌جا نمی‌شود.')
            b_move = box.addButton('بله، منتقل شود', QMessageBox.YesRole)
            b_keep = box.addButton('نه، فقط فایل‌های جدید آنجا ذخیره شوند', QMessageBox.NoRole)
            box.addButton('انصراف', QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() not in (b_move, b_keep):
                return
            move = box.clickedButton() is b_move
        report = ''
        if move:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                moved, problems = move_tree(old, new)
                n = 0
                for conn in self._connections():
                    n += rebase_paths(conn, old, new)
            finally:
                QApplication.restoreOverrideCursor()
            report = f'{moved} مورد منتقل شد؛ {n} مسیر ثبت‌شده به‌روز شد.'
            if problems:
                report += f'\n{len(problems)} مورد منتقل نشد:\n' + '\n'.join(problems[:6])
        self._apply(key, new)
        self._refresh()
        QMessageBox.information(self, 'محل ذخیره', 'محل جدید ثبت شد.' + ('\n\n' + report if report else ''))

    def _connections(self):
        out = []
        db = getattr(self.shell.ten, 'db', None)
        if db is not None:
            out.append(db.conn)
        store = getattr(self.shell.inq, 'store', None)
        if store is not None and hasattr(store, 'con'):
            out.append(store.con)
        return out

    def _apply(self, key, new):
        if key == 'inq':
            inq = self.shell.inq
            inq.output_dir = Path(new)
            try:
                inq.settings.setValue('output_dir', str(new))
                inq.dir_edit.setText(str(new))
            except Exception:
                pass
        else:
            ten = self.shell.ten
            ten.download_path = Path(new)
            ten.settings.setValue('download_path', str(new))
            try:
                ten.worker.submit('set_download_dir', path=str(new))
                ten.path_label.setText(str(new))
            except Exception:
                pass
