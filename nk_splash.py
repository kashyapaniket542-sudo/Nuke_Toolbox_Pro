# -*- coding: utf-8 -*-
"""
Nuke Toolbox Pro splash screen - separate, easy-to-customize module.

Edit the SPLASH_STYLE block below to change the look (size, fonts, positions,
accent line, version text). Title, subtitle, image, colours and duration still
come from the saved settings (Settings > Splash screen...), which use the
SplashSettings dialog defined at the bottom of this file.

Public API (used by nk_ui):
    make_splash(cfg)  -> QSplashScreen
    SplashSettings    -> settings dialog
"""
import os

try:
    from PySide2 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide6 import QtCore, QtGui, QtWidgets

import nk_core as core

# --------------------------------------------------------------------------
# CUSTOMIZE HERE
# --------------------------------------------------------------------------
# Default credit lines (bottom-left). Used until you change them in
# Settings > Splash screen... (an empty field there hides the line).
DEFAULT_AUTHOR = "Nitin Kashyap  |  VFX Artist & Tools Developer"
DEFAULT_COPYRIGHT = "\u00a9 2026 Nitin Kashyap. All rights reserved."

SPLASH_STYLE = {
    "size": (520, 260),                 # width, height in pixels
    "font_family": "Arial",
    "title_font_size": 34,
    "title_bold": True,
    "title_rect_y": (70, 70),           # (top, height) of the title text
    "subtitle_font_size": 13,
    "subtitle_rect_y": (140, 40),
    "version_font_size": 9,
    "version_rect_y": (225, 24),
    "show_version": True,
    "version_prefix": "v",
    "line_visible": True,               # accent line under the subtitle
    "line_y": 200,
    "line_margin": 60,                  # distance from the left / right edge
    "line_width": 3,
    "border_width": 0,                  # outer border in the text colour (0 = none)
    "extra_text": "",                   # optional small text, e.g. studio name
    "extra_text_font_size": 9,
    "extra_text_rect_y": (8, 24),
    "always_on_top": True,
    "credit_font_size": 8,              # author + copyright text (bottom-left)
    "credit_margin": 14,                # distance from the left / bottom edge
    "credit_line_gap": 14,               # space between the author and copyright lines
    # With a splash image: False = show the image alone (it has its own logo/text);
    # True = also draw title, subtitle and line on top of the image.
    "text_over_image": False,
    "version_corner_with_image": True,   # small version text, bottom-right, when image-only
}
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Auto-detect the splash image
# --------------------------------------------------------------------------
IMAGE_EXTS = (".png", ".jpg", ".jpeg")
SPLASH_DIR_NAMES = ("splashscreen", "splash")            # compared without case / spaces / _ / -
TOOLBOX_DIR_NAMES = ("nuketoolboxpro", "nktools", "nktoolsinstaller")


def _norm(name):
    return "".join(c for c in name.lower() if c.isalnum())


def _pick_image(folder):
    """First image in folder (names starting with 'splash' win), or ''."""
    try:
        files = sorted(f for f in os.listdir(folder)
                       if f.lower().endswith(IMAGE_EXTS) and os.path.isfile(os.path.join(folder, f)))
    except OSError:
        return ""
    files.sort(key=lambda f: not f.lower().startswith("splash"))
    return os.path.join(folder, files[0]) if files else ""


def _subdirs(base):
    try:
        return [d for d in sorted(os.listdir(base)) if os.path.isdir(os.path.join(base, d))]
    except OSError:
        return []


def splash_folders():
    """Folders searched for a splash image, in priority order:
         ~/.nuke/<Nuke Toolbox Pro | Nuke Toolbox_Pro | NK_tools>/<splash screen>
         <installer folder>/<splash screen>
    """
    out = []
    home = core.home_nuke()
    for d in _subdirs(home):
        if _norm(d) in TOOLBOX_DIR_NAMES:
            for sd in _subdirs(os.path.join(home, d)):
                if _norm(sd) in SPLASH_DIR_NAMES:
                    out.append(os.path.join(home, d, sd))
    here = os.path.dirname(os.path.abspath(__file__))
    for sd in _subdirs(here):
        if _norm(sd) in SPLASH_DIR_NAMES:
            out.append(os.path.join(here, sd))
    return out


def find_splash_image(cfg=None):
    """Image set in Settings (if the file exists), else the first image found in splash_folders()."""
    img = (cfg or {}).get("splash_image")
    if img and os.path.isfile(img):
        return img
    for folder in splash_folders():
        found = _pick_image(folder)
        if found:
            return found
    return ""


def _rect(w, y_h):
    return QtCore.QRect(0, y_h[0], w, y_h[1])


def make_splash(cfg, style=None):
    """Build the splash from the saved settings (cfg) and SPLASH_STYLE."""
    s = dict(SPLASH_STYLE)
    if style:
        s.update(style)
    base_w, base_h = s["size"]
    w = int(cfg.get("splash_w") or base_w)
    h = int(cfg.get("splash_h") or base_h)
    sx, sy = w / float(base_w), h / float(base_h)
    k = min(sx, sy)                       # text scales with the splash size

    def rect(y_h):
        return QtCore.QRect(0, int(y_h[0] * sy), w, max(1, int(y_h[1] * sy)))

    def fs(size):
        return max(1, int(round(size * k)))
    pm = QtGui.QPixmap(w, h)
    pm.fill(QtGui.QColor(cfg["splash_bg"]))
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    img = find_splash_image(cfg)
    has_img = bool(img)
    fg = QtGui.QColor(cfg["splash_fg"])
    fam = s["font_family"]
    if has_img:
        scaled = QtGui.QPixmap(img).scaled(
            w, h, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation)
        p.drawPixmap((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
    if has_img and not s["text_over_image"]:
        if s["show_version"] and s["version_corner_with_image"]:
            p.setPen(fg)
            p.setFont(QtGui.QFont(fam, fs(s["version_font_size"])))
            p.drawText(QtCore.QRect(0, h - 26, w - 12, 20), QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                       s["version_prefix"] + core.VERSION)
    else:
        p.setPen(fg)
        weight = QtGui.QFont.Bold if s["title_bold"] else QtGui.QFont.Normal
        p.setFont(QtGui.QFont(fam, fs(s["title_font_size"]), weight))
        p.drawText(rect(s["title_rect_y"]), QtCore.Qt.AlignCenter, cfg["splash_title"])
        p.setFont(QtGui.QFont(fam, fs(s["subtitle_font_size"])))
        p.drawText(rect(s["subtitle_rect_y"]), QtCore.Qt.AlignCenter, cfg["splash_subtitle"])
        if s["show_version"]:
            p.setFont(QtGui.QFont(fam, fs(s["version_font_size"])))
            p.drawText(rect(s["version_rect_y"]), QtCore.Qt.AlignCenter,
                       s["version_prefix"] + core.VERSION)
        if s["line_visible"]:
            p.setPen(QtGui.QPen(fg, s["line_width"]))
            m = int(s["line_margin"] * sx)
            y = int(s["line_y"] * sy)
            p.drawLine(m, y, w - m, y)
    # author + copyright, bottom-left (shown with or without an image)
    author = (cfg.get("splash_author", DEFAULT_AUTHOR) or "").strip()
    copy_ = (cfg.get("splash_copyright", DEFAULT_COPYRIGHT) or "").strip()
    if author or copy_:
        p.setPen(fg)
        p.setFont(QtGui.QFont(fam, fs(s["credit_font_size"])))
        mx = int(s["credit_margin"] * sx)
        gap = int(s["credit_line_gap"] * k)
        y = h - int(s["credit_margin"] * sy)
        flags = QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom
        if copy_:
            p.drawText(QtCore.QRect(mx, y - gap, w - 2 * mx, gap), flags, copy_)
            y -= gap
        if author:
            p.drawText(QtCore.QRect(mx, y - gap, w - 2 * mx, gap), flags, author)
    if s["extra_text"]:
        p.setPen(fg)
        p.setFont(QtGui.QFont(fam, fs(s["extra_text_font_size"])))
        p.drawText(rect(s["extra_text_rect_y"]), QtCore.Qt.AlignCenter, s["extra_text"])
    if s["border_width"]:
        p.setPen(QtGui.QPen(fg, s["border_width"]))
        b = s["border_width"] // 2
        p.drawRect(b, b, w - 2 * b - 1, h - 2 * b - 1)
    p.end()
    flags = QtCore.Qt.WindowStaysOnTopHint if s["always_on_top"] else QtCore.Qt.Widget
    return QtWidgets.QSplashScreen(pm, flags)


class SplashSettings(QtWidgets.QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Splash Screen Settings")
        self.cfg = cfg
        form = QtWidgets.QFormLayout(self)
        self.title = QtWidgets.QLineEdit(cfg["splash_title"])
        self.sub = QtWidgets.QLineEdit(cfg["splash_subtitle"])
        self.img = QtWidgets.QLineEdit(cfg["splash_image"])
        auto = find_splash_image({})
        self.img.setPlaceholderText("Auto: " + auto if auto else
                                    "Auto: put an image in ~/.nuke/Nuke Toolbox Pro/splash screen")
        b = QtWidgets.QPushButton("...")
        b.setFixedWidth(30)
        b.clicked.connect(self._pick_img)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.img)
        row.addWidget(b)
        self.bg = QtWidgets.QPushButton(cfg["splash_bg"])
        self.fg = QtWidgets.QPushButton(cfg["splash_fg"])
        self.bg.clicked.connect(lambda: self._pick_color(self.bg))
        self.fg.clicked.connect(lambda: self._pick_color(self.fg))
        self.ms = QtWidgets.QSpinBox()
        self.ms.setRange(300, 10000)
        self.ms.setSuffix(" ms")
        self.ms.setValue(cfg["splash_ms"])
        self.author = QtWidgets.QLineEdit(cfg.get("splash_author", DEFAULT_AUTHOR))
        self.copy = QtWidgets.QLineEdit(cfg.get("splash_copyright", DEFAULT_COPYRIGHT))
        self.w_sp = QtWidgets.QSpinBox()
        self.w_sp.setRange(200, 3000)
        self.w_sp.setSuffix(" px")
        self.w_sp.setValue(int(cfg.get("splash_w") or 520))
        self.h_sp = QtWidgets.QSpinBox()
        self.h_sp.setRange(100, 2000)
        self.h_sp.setSuffix(" px")
        self.h_sp.setValue(int(cfg.get("splash_h") or 260))
        self.fit = QtWidgets.QPushButton("Fit to image")
        self.fit.clicked.connect(self._fit_image)
        size_row = QtWidgets.QHBoxLayout()
        size_row.addWidget(QtWidgets.QLabel("W"))
        size_row.addWidget(self.w_sp)
        size_row.addWidget(QtWidgets.QLabel("H"))
        size_row.addWidget(self.h_sp)
        size_row.addWidget(self.fit)
        size_row.addStretch(1)
        for lab, w in (("Title", self.title), ("Subtitle", self.sub)):
            form.addRow(lab, w)
        form.addRow("Image", row)
        form.addRow("Background", self.bg)
        form.addRow("Text colour", self.fg)
        form.addRow("Author", self.author)
        form.addRow("Copyright", self.copy)
        form.addRow("Size", size_row)
        form.addRow("Duration", self.ms)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
                                        | QtWidgets.QDialogButtonBox.Reset)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(QtWidgets.QDialogButtonBox.Reset).clicked.connect(self._reset)
        form.addRow(bb)
        tp = _ui().load_tooltips().get("splash", {})
        for attr, key in (("title", "title"), ("sub", "sub"), ("img", "img"), ("bg", "bg"), ("fg", "fg"), ("ms", "ms"), ("author", "author"), ("copy", "copyright"), ("w_sp", "w"), ("h_sp", "h"), ("fit", "fit")):
            if tp.get(key):
                _ui().set_tip(getattr(self, attr), tp[key])
        _ui().tip_buttons(self)
        for std, tx in ((QtWidgets.QDialogButtonBox.Ok, "Apply the splash settings."),
                        (QtWidgets.QDialogButtonBox.Cancel, "Close without changes."),
                        (QtWidgets.QDialogButtonBox.Reset, "Restore the default splash settings.")):
            _ui().set_tip(bb.button(std), tx)

    def _fit_image(self):
        path = find_splash_image({"splash_image": self.img.text().strip()})
        pm = QtGui.QPixmap(path) if path else QtGui.QPixmap()
        if not pm.isNull():
            self.w_sp.setValue(pm.width())
            self.h_sp.setValue(pm.height())

    def _pick_img(self):
        f, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Splash image", "", "Images (*.png *.jpg *.jpeg)")
        if f:
            self.img.setText(f)

    def _pick_color(self, btn):
        c = QtWidgets.QColorDialog.getColor(QtGui.QColor(btn.text()), self)
        if c.isValid():
            btn.setText(c.name())

    def _reset(self):
        d = core.DEFAULT_CONFIG
        self.title.setText(d["splash_title"])
        self.sub.setText(d["splash_subtitle"])
        self.img.setText("")
        self.bg.setText(d["splash_bg"])
        self.fg.setText(d["splash_fg"])
        self.ms.setValue(d["splash_ms"])
        self.author.setText(DEFAULT_AUTHOR)
        self.copy.setText(DEFAULT_COPYRIGHT)
        self.w_sp.setValue(d["splash_w"])
        self.h_sp.setValue(d["splash_h"])

    def result_config(self):
        self.cfg.update(splash_title=self.title.text(), splash_subtitle=self.sub.text(),
                        splash_image=self.img.text(), splash_bg=self.bg.text(),
                        splash_fg=self.fg.text(), splash_ms=self.ms.value(),
                        splash_author=self.author.text(), splash_copyright=self.copy.text(),
                        splash_w=self.w_sp.value(), splash_h=self.h_sp.value())
        return self.cfg


def _ui():
    """Late import: nk_ui imports this module, so import it only when needed."""
    import nk_ui
    return nk_ui
