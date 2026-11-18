# -*- coding: utf-8 -*-
"""NK_tools code editor: edit a tool's install subfolder (and Nuke's init.py / menu.py) inside Nuke.

PyCharm (Darcula) and Sublime Text (Monokai) colour schemes, line numbers, Python highlighting,
syntax checking with a clickable problems list, automatic backup on save.
All logic that does not need Qt lives in nk_core.
"""
import builtins
import keyword
import os
import re

try:
    from PySide2 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide6 import QtCore, QtGui, QtWidgets

import nk_core as core

THEMES = {
    "PyCharm Darcula": {
        "bg": "#2b2b2b", "fg": "#a9b7c6", "keyword": "#cc7832", "string": "#6a8759", "comment": "#808080",
        "number": "#6897bb", "defname": "#ffc66d", "builtin": "#8888c6", "deco": "#bbb529",
        "gutter_bg": "#313335", "gutter_fg": "#606366", "curline": "#323232", "sel": "#214283",
        "error": "#5a2a2a", "warning": "#4d4526", "icon": "pycharm",
    },
    "Sublime Monokai": {
        "bg": "#272822", "fg": "#f8f8f2", "keyword": "#f92672", "string": "#e6db74", "comment": "#75715e",
        "number": "#ae81ff", "defname": "#a6e22e", "builtin": "#66d9ef", "deco": "#a6e22e",
        "gutter_bg": "#272822", "gutter_fg": "#90908a", "curline": "#3e3d32", "sel": "#49483e",
        "error": "#5a1f2e", "warning": "#4d4526", "icon": "sublime",
    },
}
DEFAULT_THEME = "PyCharm Darcula"

_KW = set(keyword.kwlist) | {"self", "cls", "True", "False", "None"}
_BUILTINS = {n for n in dir(builtins) if not n.startswith("_")} - _KW
_WORD = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_NUM = re.compile(r"\b(?:0[xX][0-9a-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?)\b")
_STR_START = re.compile(r"[rRbBuUfF]{0,2}('''|\"\"\"|'|\")")


def _fmt(color, bold=False, italic=False):
    f = QtGui.QTextCharFormat()
    f.setForeground(QtGui.QColor(color))
    if bold:
        f.setFontWeight(QtGui.QFont.Bold)
    if italic:
        f.setFontItalic(True)
    return f


class CodeHighlighter(QtGui.QSyntaxHighlighter):
    """Small Python-ish highlighter (also fine for Tcl / gizmo: strings, # comments, numbers)."""

    def __init__(self, doc, theme, python=True):
        super().__init__(doc)
        self.python = python
        self.set_theme(theme, rehighlight=False)

    def set_theme(self, theme, rehighlight=True):
        t = THEMES[theme]
        self.f = {"keyword": _fmt(t["keyword"], bold=True), "string": _fmt(t["string"]),
                  "comment": _fmt(t["comment"], italic=True), "number": _fmt(t["number"]),
                  "defname": _fmt(t["defname"]), "builtin": _fmt(t["builtin"]), "deco": _fmt(t["deco"])}
        if rehighlight:
            self.rehighlight()

    def highlightBlock(self, text):
        state_in = self.previousBlockState()      # 1 = inside ''' string, 2 = inside """ string
        pos = 0
        n = len(text)
        if state_in in (1, 2):
            q = "'''" if state_in == 1 else '"""'
            end = text.find(q)
            if end < 0:
                self.setFormat(0, n, self.f["string"])
                self.setCurrentBlockState(state_in)
                return
            self.setFormat(0, end + 3, self.f["string"])
            pos = end + 3
        self.setCurrentBlockState(0)
        spans = []                                # (start, end) of strings/comments already coloured
        i = pos
        while i < n:
            ch = text[i]
            if ch == "#":
                self.setFormat(i, n - i, self.f["comment"])
                spans.append((i, n))
                break
            m = _STR_START.match(text, i)
            if m and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_") or m.start(1) > i):
                q = m.group(1)
                body = m.end()
                j = body
                while j < n:
                    if text[j] == "\\":
                        j += 2
                        continue
                    if text.startswith(q, j):
                        break
                    j += 1
                if j >= n and len(q) == 3:        # triple quote continues on next line
                    self.setFormat(i, n - i, self.f["string"])
                    self.setCurrentBlockState(1 if q == "'''" else 2)
                    spans.append((i, n))
                    break
                end = min(n, j + len(q))
                self.setFormat(i, end - i, self.f["string"])
                spans.append((i, end))
                i = end
                continue
            i += 1

        def covered(a):
            return any(s <= a < e for s, e in spans)

        for m in _NUM.finditer(text, pos):
            if not covered(m.start()):
                self.setFormat(m.start(), m.end() - m.start(), self.f["number"])
        if not self.python:
            return
        prev = ""
        for m in _WORD.finditer(text, pos):
            if covered(m.start()):
                continue
            w = m.group(0)
            if w in _KW:
                self.setFormat(m.start(), len(w), self.f["keyword"])
            elif prev in ("def", "class"):
                self.setFormat(m.start(), len(w), self.f["defname"])
            elif w in _BUILTINS:
                self.setFormat(m.start(), len(w), self.f["builtin"])
            elif m.start() > 0 and text[m.start() - 1] == "@":
                self.setFormat(m.start() - 1, len(w) + 1, self.f["deco"])
            prev = w
        st = text.lstrip()
        if st.startswith("@") and not covered(len(text) - len(st)):
            self.setFormat(len(text) - len(st), len(st.split("(")[0]), self.f["deco"])


class _Gutter(QtWidgets.QWidget):
    def __init__(self, ed):
        super().__init__(ed)
        self.ed = ed

    def sizeHint(self):
        return QtCore.QSize(self.ed.gutter_width(), 0)

    def paintEvent(self, e):
        self.ed.paint_gutter(e)


class CodeEdit(QtWidgets.QPlainTextEdit):
    def __init__(self, path, theme=DEFAULT_THEME, parent=None):
        super().__init__(parent)
        self.path = path
        self.theme = theme
        self.encoding = "utf-8"
        self.problems = []
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.setFont(self._font(11))
        self._gutter = _Gutter(self)
        self.blockCountChanged.connect(self._update_margin)
        self.updateRequest.connect(self._scroll_gutter)
        self.cursorPositionChanged.connect(self.refresh_selections)
        is_py = os.path.splitext(path)[1].lower() in (".py", "")
        self.hl = CodeHighlighter(self.document(), theme, python=is_py)
        self._update_margin()
        self.apply_theme(theme)

    @staticmethod
    def _font(size):
        f = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        f.setPointSize(size)
        return f

    def set_font_size(self, size):
        self.setFont(self._font(size))
        self.setTabStopDistance(4 * self._adv(" "))
        self._update_margin()

    def _adv(self, s):
        fm = self.fontMetrics()
        return fm.horizontalAdvance(s) if hasattr(fm, "horizontalAdvance") else fm.width(s)

    # ----- theme
    def apply_theme(self, theme):
        self.theme = theme
        t = THEMES[theme]
        self.setStyleSheet("QPlainTextEdit { background:%s; color:%s; border:0; selection-background-color:%s; }"
                           % (t["bg"], t["fg"], t["sel"]))
        self.hl.set_theme(theme)
        self.setTabStopDistance(4 * self._adv(" "))
        self.refresh_selections()
        self._gutter.update()

    # ----- gutter
    def gutter_width(self):
        return 14 + self._adv("9") * max(3, len(str(max(1, self.blockCount()))))

    def _update_margin(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _scroll_gutter(self, rect, dy):
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margin()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self._gutter.setGeometry(QtCore.QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, event):
        t = THEMES[self.theme]
        p = QtGui.QPainter(self._gutter)
        p.fillRect(event.rect(), QtGui.QColor(t["gutter_bg"]))
        bad = {pr["line"]: pr["severity"] for pr in self.problems}
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        cur = self.textCursor().blockNumber()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                ln = num + 1
                color = t["gutter_fg"] if num != cur else t["fg"]
                if ln in bad:
                    color = "#ff5555" if bad[ln] == "error" else "#e0b050"
                p.setPen(QtGui.QColor(color))
                p.drawText(0, top, self._gutter.width() - 6, self.fontMetrics().height(),
                           QtCore.Qt.AlignRight, ("\u25cf " if ln in bad else "") + str(ln))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            num += 1

    # ----- highlights (current line + problem lines)
    def set_problems(self, problems):
        self.problems = list(problems)
        self.refresh_selections()
        self._gutter.update()

    def refresh_selections(self):
        t = THEMES[self.theme]
        sels = []
        for pr in self.problems:
            blk = self.document().findBlockByNumber(max(0, pr["line"] - 1))
            if blk.isValid():
                s = QtWidgets.QTextEdit.ExtraSelection()
                s.format.setBackground(QtGui.QColor(t["error"] if pr["severity"] == "error" else t["warning"]))
                s.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
                s.cursor = QtGui.QTextCursor(blk)
                sels.append(s)
        s = QtWidgets.QTextEdit.ExtraSelection()
        s.format.setBackground(QtGui.QColor(t["curline"]))
        s.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
        s.cursor = self.textCursor()
        s.cursor.clearSelection()
        sels.insert(0, s)
        self.setExtraSelections(sels)
        self._gutter.update()

    def goto_line(self, line, col=0):
        blk = self.document().findBlockByNumber(max(0, line - 1))
        if blk.isValid():
            c = QtGui.QTextCursor(blk)
            c.movePosition(QtGui.QTextCursor.Right, QtGui.QTextCursor.MoveAnchor,
                           min(max(col - 1, 0), blk.length() - 1))
            self.setTextCursor(c)
            self.centerCursor()
        self.setFocus()

    # ----- typing helpers: 4-space tab, auto indent, shift+tab dedent
    def keyPressEvent(self, e):
        k = e.key()
        cur = self.textCursor()
        if k == QtCore.Qt.Key_Tab and not cur.hasSelection():
            cur.insertText("    ")
            return
        if k == QtCore.Qt.Key_Backtab or (k == QtCore.Qt.Key_Tab and cur.hasSelection()):
            self._shift_selection(k == QtCore.Qt.Key_Backtab)
            return
        if k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            line = cur.block().text()[:cur.positionInBlock()]
            indent = re.match(r"[ \t]*", line).group(0)
            if line.rstrip().endswith(":"):
                indent += "    "
            super().keyPressEvent(e)
            self.textCursor().insertText(indent)
            return
        super().keyPressEvent(e)

    def _shift_selection(self, dedent):
        cur = self.textCursor()
        doc = self.document()
        a, b = sorted((cur.selectionStart(), cur.selectionEnd()))
        first = doc.findBlock(a).blockNumber()
        last = doc.findBlock(b).blockNumber()
        cur.beginEditBlock()
        for n in range(first, last + 1):
            c = QtGui.QTextCursor(doc.findBlockByNumber(n))
            if dedent:
                txt = c.block().text()
                k = len(txt) - len(txt.lstrip(" "))
                k = min(k, 4)
                for _ in range(k):
                    c.deleteChar()
            else:
                c.insertText("    ")
        cur.endEditBlock()


class EditorTab(QtWidgets.QWidget):
    """File tree + tabbed editors + problems list. Embedded as a tab of the installer window."""

    def __init__(self, cfg, icon_fn=None, warn_fn=None, ask_fn=None, log_fn=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.icon_fn = icon_fn or (lambda name: QtGui.QIcon())
        self.warn = warn_fn or (lambda t, m: None)
        self.ask = ask_fn or (lambda t, m: True)
        self.log = log_fn or (lambda m: None)
        self.theme = cfg.get("editor_theme") if cfg.get("editor_theme") in THEMES else DEFAULT_THEME
        self.font_size = 11
        self.tool_name = ""
        self.tool_dir = ""
        self._build()
        self.reload_tree()

    # ------------------------------------------------------------------ UI
    def _build(self):
        lay = QtWidgets.QVBoxLayout(self)
        bar = QtWidgets.QHBoxLayout()
        self.b_save = QtWidgets.QPushButton("Save")
        self.b_save.setObjectName("primary")
        self.b_save_all = QtWidgets.QPushButton("Save all")
        self.b_check = QtWidgets.QPushButton("Check")
        self.b_check.setToolTip("Check this file for syntax errors")
        self.b_check_all = QtWidgets.QPushButton("Check tool")
        self.b_check_all.setToolTip("Check every file of this tool + init.py / menu.py")
        self.b_reload = QtWidgets.QPushButton("Reload")
        self.b_reload.setToolTip("Reload the file from disk")
        self.theme_box = QtWidgets.QComboBox()
        for name, t in THEMES.items():
            self.theme_box.addItem(self.icon_fn(t["icon"]), name)
        self.theme_box.setCurrentText(self.theme)
        self.theme_box.setMinimumWidth(170)
        self.size_box = QtWidgets.QSpinBox()
        self.size_box.setRange(8, 28)
        self.size_box.setValue(self.font_size)
        self.size_box.setSuffix(" pt")
        self.b_pycharm = QtWidgets.QPushButton()
        self.b_pycharm.setIcon(self.icon_fn("pycharm"))
        self.b_pycharm.setToolTip("Open this file in PyCharm")
        self.b_sublime = QtWidgets.QPushButton()
        self.b_sublime.setIcon(self.icon_fn("sublime"))
        self.b_sublime.setToolTip("Open this file in Sublime Text")
        for b in (self.b_save, self.b_save_all, self.b_check, self.b_check_all, self.b_reload):
            bar.addWidget(b)
        bar.addStretch()
        bar.addWidget(self.theme_box)
        bar.addWidget(self.size_box)
        bar.addWidget(self.b_pycharm)
        bar.addWidget(self.b_sublime)
        lay.addLayout(bar)

        self.find_row = QtWidgets.QHBoxLayout()
        self.find_edit = QtWidgets.QLineEdit()
        self.find_edit.setPlaceholderText("Find in file (Ctrl+F, Enter = next, Shift+Enter = previous)")
        self.b_prev = QtWidgets.QPushButton("Prev")
        self.b_next = QtWidgets.QPushButton("Next")
        self.find_row.addWidget(self.find_edit, 1)
        self.find_row.addWidget(self.b_prev)
        self.find_row.addWidget(self.b_next)
        lay.addLayout(self.find_row)

        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(190)
        split.addWidget(self.tree)
        right = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        right.addWidget(self.tabs)
        self.problems = QtWidgets.QListWidget()
        self.problems.setMaximumHeight(90)
        right.addWidget(self.problems)
        right.setStretchFactor(0, 4)
        split.addWidget(right)
        split.setStretchFactor(1, 4)
        split.setSizes([220, 700])
        lay.addWidget(split, 1)
        self.status = QtWidgets.QLabel("Pick a file on the left. Changes are backed up automatically on save "
                                       "(Safety & Log tab).")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        self.tree.itemDoubleClicked.connect(self._tree_open)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(lambda *_: self._on_tab_changed())
        self.problems.itemClicked.connect(self._problem_clicked)
        self.b_save.clicked.connect(self.save_current)
        self.b_save_all.clicked.connect(self.save_all)
        self.b_check.clicked.connect(self.check_current)
        self.b_check_all.clicked.connect(self.check_tool)
        self.b_reload.clicked.connect(self.reload_current)
        self.theme_box.currentTextChanged.connect(self.set_theme)
        self.size_box.valueChanged.connect(self.set_font_size)
        self.b_pycharm.clicked.connect(lambda: self._external("pycharm"))
        self.b_sublime.clicked.connect(lambda: self._external("sublime"))
        self.find_edit.returnPressed.connect(self.find_next)
        self.b_next.clicked.connect(self.find_next)
        self.b_prev.clicked.connect(lambda: self.find_next(backward=True))
        for seq, fn in (("Ctrl+S", self.save_current), ("Ctrl+F", lambda: self.find_edit.setFocus())):
            sc = QtWidgets.QShortcut(QtGui.QKeySequence(seq), self) if hasattr(QtWidgets, "QShortcut") \
                else QtGui.QShortcut(QtGui.QKeySequence(seq), self)
            sc.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)

    # ------------------------------------------------------------------ tree
    def set_tool(self, name, folder):
        self.tool_name, self.tool_dir = name, folder
        self.reload_tree()

    def reload_tree(self):
        self.tree.clear()
        grp = QtWidgets.QTreeWidgetItem(["Nuke startup  (%s)" % core.init_dir(self.cfg)])
        self.tree.addTopLevelItem(grp)
        for p in core.nuke_startup_files(self.cfg):
            it = QtWidgets.QTreeWidgetItem([os.path.basename(p) + ("" if os.path.isfile(p) else "  (not created yet)")])
            it.setData(0, QtCore.Qt.UserRole, p)
            grp.addChild(it)
        grp.setExpanded(True)
        if self.tool_dir:
            tg = QtWidgets.QTreeWidgetItem(["%s  (%s)" % (self.tool_name or "Tool", self.tool_dir)])
            self.tree.addTopLevelItem(tg)
            folders = {"": tg}
            for rel in core.editable_files(self.tool_dir):
                parent = tg
                acc = ""
                for part in os.path.dirname(rel).split(os.sep):
                    if not part:
                        continue
                    acc = os.path.join(acc, part)
                    if acc not in folders:
                        node = QtWidgets.QTreeWidgetItem([part])
                        folders[os.path.dirname(acc)].addChild(node)
                        folders[acc] = node
                    parent = folders[acc]
                it = QtWidgets.QTreeWidgetItem([os.path.basename(rel)])
                it.setData(0, QtCore.Qt.UserRole, os.path.join(self.tool_dir, rel))
                parent.addChild(it)
            tg.setExpanded(True)
            for node in folders.values():
                node.setExpanded(True)

    def _tree_open(self, item, *_):
        p = item.data(0, QtCore.Qt.UserRole)
        if p:
            self.open_file(p)

    # ------------------------------------------------------------------ files
    def editors(self):
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def current(self):
        return self.tabs.currentWidget()

    def _title(self, ed):
        return os.path.basename(ed.path) + (" *" if ed.document().isModified() else "")

    def _retitle(self, ed):
        i = self.tabs.indexOf(ed)
        if i >= 0:
            self.tabs.setTabText(i, self._title(ed))
            self.tabs.setTabToolTip(i, ed.path)

    def open_file(self, path, line=None, col=0):
        path = os.path.abspath(path)
        for i, ed in enumerate(self.editors()):
            if os.path.normcase(ed.path) == os.path.normcase(path):
                self.tabs.setCurrentIndex(i)
                if line:
                    ed.goto_line(line, col)
                return ed
        if os.path.isfile(path):
            try:
                text, enc = core.read_text(path)
            except OSError as e:
                self.warn("Open file", "Cannot read %s:\n%s" % (path, e))
                return None
        elif path in core.nuke_startup_files(self.cfg):
            text, enc = "", "utf-8"                    # init.py / menu.py not created yet -> new file
        else:
            self.warn("Open file", "File not found:\n%s" % path)
            return None
        ed = CodeEdit(path, self.theme)
        ed.encoding = enc
        ed.setPlainText(text.replace("\r\n", "\n"))
        ed.set_font_size(self.font_size)
        ed.document().setModified(False)
        ed.document().modificationChanged.connect(lambda *_: self._retitle(ed))
        self.tabs.addTab(ed, self._title(ed))
        self.tabs.setCurrentWidget(ed)
        self._retitle(ed)
        if line:
            ed.goto_line(line, col)
        self.check_current(quiet=True)
        return ed

    def close_tab(self, i):
        ed = self.tabs.widget(i)
        if ed is not None and ed.document().isModified():
            if self.ask("Unsaved changes", "Save changes to %s before closing?" % os.path.basename(ed.path)):
                if not self._save(ed):
                    return
        self.tabs.removeTab(i)

    def close_all(self):
        for i in reversed(range(self.tabs.count())):
            self.tabs.removeTab(i)

    def _is_startup(self, path):
        norm = os.path.normcase(os.path.abspath(path))
        return norm in [os.path.normcase(os.path.abspath(p)) for p in core.nuke_startup_files(self.cfg)]

    def _save(self, ed):
        text = ed.toPlainText()
        probs = core.check_source(text, ed.path)
        errs = [p for p in probs if p["severity"] == "error"]
        if errs and self._is_startup(ed.path):
            if not self.ask("Syntax error", "%s has a syntax error (line %d: %s).\n\nA broken init.py / menu.py "
                            "can stop Nuke's menus from loading. Save anyway?"
                            % (os.path.basename(ed.path), errs[0]["line"], errs[0]["msg"])):
                self._show_problems(probs)
                return False
        try:
            os.makedirs(os.path.dirname(ed.path), exist_ok=True)
            core.save_text(self.cfg, ed.path, text)
        except Exception as e:
            self.warn("Save failed", "%s\n\n%s" % (ed.path, e))
            return False
        ed.document().setModified(False)
        ed.set_problems(probs)
        self._show_problems(probs)
        self.status.setText("Saved %s (previous version backed up). Restart Nuke to apply." % ed.path)
        self.log("Saved %s" % ed.path)
        self.reload_tree()
        return True

    def save_current(self):
        ed = self.current()
        return self._save(ed) if ed else False

    def save_all(self):
        for ed in self.editors():
            if ed.document().isModified() and not self._save(ed):
                return False
        return True

    def reload_current(self):
        ed = self.current()
        if not ed or not os.path.isfile(ed.path):
            return
        if ed.document().isModified() and not self.ask("Reload", "Discard your unsaved changes in %s?"
                                                       % os.path.basename(ed.path)):
            return
        text, ed.encoding = core.read_text(ed.path)
        ed.setPlainText(text.replace("\r\n", "\n"))
        ed.document().setModified(False)
        self.check_current(quiet=True)

    # ------------------------------------------------------------------ errors
    def _show_problems(self, probs):
        self.problems.clear()
        for pr in probs:
            it = QtWidgets.QListWidgetItem("%s  %s:%d  %s" % (
                "\u26a0" if pr["severity"] == "warning" else "\u2716",
                os.path.basename(pr["file"]), pr["line"], pr["msg"]))
            it.setData(QtCore.Qt.UserRole, (pr["file"], pr["line"], pr["col"]))
            it.setToolTip(pr["file"])
            self.problems.addItem(it)

    def check_current(self, quiet=False):
        ed = self.current()
        if not ed:
            return []
        probs = core.check_source(ed.toPlainText(), ed.path)
        ed.set_problems(probs)
        self._show_problems(probs)
        if probs:
            self.status.setText("%d problem(s) in %s - click one to jump to it." % (len(probs), os.path.basename(ed.path)))
        elif not quiet:
            self.status.setText("No syntax problems in %s." % os.path.basename(ed.path))
        return probs

    def check_tool(self, open_first=True):
        """Check every file of the current tool folder + the Nuke startup files; list all problems."""
        probs = []
        if self.tool_dir:
            probs += core.scan_folder_errors(self.tool_dir)
        for p in core.nuke_startup_files(self.cfg):
            if os.path.isfile(p):
                probs += core.check_source(core.read_text(p)[0], p)
        self._show_problems(probs)
        for ed in self.editors():
            ed.set_problems([p for p in probs if os.path.normcase(p["file"]) == os.path.normcase(ed.path)])
        if not probs:
            self.status.setText("No problems found in %s." % (self.tool_name or "the Nuke startup files"))
        else:
            self.status.setText("%d problem(s) found - click one to open the file at that line, fix it, then Save."
                                % len(probs))
            if open_first:
                first = probs[0]
                ed = self.open_file(first["file"], first["line"], first["col"])
                if ed:
                    ed.set_problems([p for p in probs if os.path.normcase(p["file"]) == os.path.normcase(ed.path)])
        return probs

    def _problem_clicked(self, item):
        data = item.data(QtCore.Qt.UserRole)
        if data:
            path, line, col = data
            ed = self.open_file(path, line, col)
            if ed and not ed.problems:
                self.check_current(quiet=True)

    def _on_tab_changed(self):
        ed = self.current()
        if ed:
            self._show_problems(ed.problems)

    # ------------------------------------------------------------------ look + external
    def set_theme(self, name):
        if name not in THEMES:
            return
        self.theme = name
        self.cfg["editor_theme"] = name
        for ed in self.editors():
            ed.apply_theme(name)
        try:
            core.save_config(self.cfg)
        except Exception:
            pass

    def set_font_size(self, size):
        self.font_size = size
        for ed in self.editors():
            ed.set_font_size(size)

    def find_next(self, backward=False):
        ed = self.current()
        text = self.find_edit.text()
        if not ed or not text:
            return False
        backward = backward or bool(QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ShiftModifier)

        def go():
            return ed.find(text, QtGui.QTextDocument.FindBackward) if backward else ed.find(text)
        if go():
            return True
        c = ed.textCursor()                              # wrap around
        c.movePosition(QtGui.QTextCursor.End if backward else QtGui.QTextCursor.Start)
        ed.setTextCursor(c)
        return go()

    def _external(self, key):
        ed = self.current()
        if not ed:
            self.warn(core.EDITORS[key]["label"], "Open a file first.")
            return
        if ed.document().isModified() and self.ask("Unsaved changes", "Save %s first so %s sees your edits?"
                                                   % (os.path.basename(ed.path), core.EDITORS[key]["label"])):
            self._save(ed)
        try:
            core.open_in_editor(key, ed.path, self.cfg)
        except core.NKError as e:
            self.warn(core.EDITORS[key]["label"], str(e))
