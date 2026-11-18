# -*- coding: utf-8 -*-
"""Nuke Toolbox Pro UI (PySide2, falls back to PySide6). All logic lives in nk_core."""
import os
import re
import sys
import webbrowser

try:
    from PySide2 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide6 import QtCore, QtGui, QtWidgets

import nk_core as core
import nk_editor

MARKETPLACES = {
    "Nukepedia": "https://www.nukepedia.com/",
    "GitHub": "https://github.com/search?q=nuke+gizmo&type=repositories",
    "GitLab": "https://gitlab.com/explore/projects?name=nuke",
}
SOURCE_ITEMS = ["Auto-detect", "Local zip / folder", "GitHub URL", "GitLab URL", "Nukepedia / direct zip URL"]

STYLE_DIR_NAME = "Style"
STYLE_FILE_NAME = "style.qss"


def find_style_file():
    """Auto-detect Style/style.qss next to this script (nuke/NK_tools_installer/Style), case-insensitive."""
    return _find_in_folder(STYLE_DIR_NAME, STYLE_FILE_NAME)


def load_stylesheet():
    """Return the contents of Style/style.qss, or "" (default Qt look) if it is missing/unreadable."""
    path = find_style_file()
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


TOOLTIP_DIR_NAME = "tooltips"
TOOLTIP_FILE_NAME = "tooltips.json"
_TIPS_CACHE = {}


def _find_in_folder(folder_name, file_name):
    """Auto-detect <this script's folder>/<folder_name>/<file_name>, tolerant of folder / file name casing."""
    base = os.path.dirname(os.path.abspath(__file__))
    try:
        for d in os.listdir(base):
            if d.lower() == folder_name.lower() and os.path.isdir(os.path.join(base, d)):
                for f in os.listdir(os.path.join(base, d)):
                    if f.lower() == file_name.lower():
                        return os.path.join(base, d, f)
    except OSError:
        pass
    return ""


def load_tooltips():
    """Contents of tooltips/tooltips.json ({} if missing / invalid - the UI then simply has no extra tooltips)."""
    if "data" not in _TIPS_CACHE:
        data = {}
        path = _find_in_folder(TOOLTIP_DIR_NAME, TOOLTIP_FILE_NAME)
        if path:
            try:
                import json
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                data = {}
        _TIPS_CACHE["data"] = data if isinstance(data, dict) else {}
    return _TIPS_CACHE["data"]


def set_tip(widget, html, extra=""):
    """Rich-text tooltip, wrapped to a readable width. 'extra' (e.g. a detected path) is shown below a rule."""
    widget.setProperty("base_tip", html)
    if extra:
        html = html + "<hr><span style='color:#8d8e96'>%s</span>" % extra
    widget.setToolTip("<table width='340'><tr><td>%s</td></tr></table>" % html)


def _resolve(root, path):
    """'name', 'a.b', 'name[1]' or 'name[Key]' -> object (None if it does not exist)."""
    obj = root
    for part in path.split("."):
        m = re.match(r"^(\w+)(?:\[(.+)\])?$", part)
        if not m:
            return None
        obj = getattr(obj, m.group(1), None)
        if obj is not None and m.group(2) is not None:
            key = m.group(2)
            try:
                obj = obj[int(key)] if isinstance(obj, (tuple, list)) else obj[key]
            except (KeyError, IndexError, ValueError, TypeError):
                return None
        if obj is None:
            return None
    return obj


def tip_buttons(root):
    """Tooltips for push buttons that only have a caption (dialogs, '...' browse buttons, Install / Uninstall)."""
    by_text = load_tooltips().get("dialog_buttons", {})
    for b in root.findChildren(QtWidgets.QPushButton):
        if by_text.get(b.text()) and not b.toolTip():
            set_tip(b, "<b>%s</b><br>%s" % (b.text().rstrip("."), by_text[b.text()]) if b.text() != "..."
                    else by_text["..."])


def apply_tooltips(win):
    """Attach the full tooltip set (tooltips/tooltips.json) to every panel, button, field, table and tab."""
    tips = load_tooltips()
    if not tips:
        return
    for key, html in tips.get("widgets", {}).items():
        w = _resolve(win, key)
        if isinstance(w, QtWidgets.QWidget):
            extra = ""
            if key in ("pycharm_btn", "b_pycharm", "sublime_btn", "b_sublime"):
                k = "pycharm" if "pycharm" in key else "sublime"
                exe = core.find_editor(k, win.cfg)
                extra = exe if exe else "(not found - set the path in Settings)"
            elif key == "nuke_lbl":
                extra = "<br>".join("%s - %s" % (i["version"], i["path"]) for i in getattr(win, "_nuke_installs", []))
            set_tip(w, html, extra)
    for lbl in win.findChildren(QtWidgets.QLabel):
        for text, html in tips.get("labels", {}).items():
            if lbl.text() == text or (text == "Role" and lbl.text().startswith("Role (")):
                set_tip(lbl, html)
                break
    for tabs, section in ((win.tabs, "tabs"), (getattr(win, "side_tabs", None), "side_tabs")):
        if tabs is not None:
            for i in range(tabs.count()):
                t = tips.get(section, {}).get(tabs.tabText(i).replace("&&", "&"))
                if t:
                    tabs.tabBar().setTabToolTip(i, "<table width='340'><tr><td>%s</td></tr></table>" % t)
    for tname, cols in tips.get("table_headers", {}).items():
        t = getattr(win, tname, None)
        if t is not None:
            for c in range(t.columnCount()):
                it = t.horizontalHeaderItem(c)
                if it is not None and cols.get(it.text()):
                    it.setToolTip(cols[it.text()])
    tip_buttons(win)


def run_dialog(d):
    return d.exec() if hasattr(d, "exec") and QtCore.__name__.startswith("PySide6") else d.exec_()


def mono():
    f = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
    f.setPointSize(9)
    return f


_FALLBACK_COLORS = {"pycharm": ("#21d66f", "#0878be", "PC"), "sublime": ("#ff9800", "#ff5722", "S"),
                    "folder": ("#5c6478", "#343846", ""),
                    "global": ("#4aa3ff", "#1d5fa8", "G"), "major": ("#9b6bff", "#5a34b5", "M"),
                    "td": ("#2fd0a0", "#12806a", "TD"), "studio": ("#f2a33a", "#b5601a", "S"),
                    "automatic": ("#21d66f", "#0f8a47", "A"), "manual": ("#8d8e96", "#4a4b52", "M"),
                    "review": ("#4aa3ff", "#1d5fa8", "R"), "requirements": ("#ff7ab0", "#b53468", "pip"),
                    "dryrun": ("#e6c84a", "#a08512", "D"), "deep": ("#2fd0a0", "#12806a", "?")}


def _painted_icon(name, size=64):
    """Built-in icon used when no icon file can be loaded (e.g. no icon folder, no SVG plugin)."""
    c1, c2, txt = _FALLBACK_COLORS.get(name, ("#5c6478", "#343846", "?"))
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    g = QtGui.QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QtGui.QColor(c1))
    g.setColorAt(1, QtGui.QColor(c2))
    p.setBrush(QtGui.QBrush(g))
    p.setPen(QtCore.Qt.NoPen)
    p.drawRoundedRect(0, 0, size, size, size * 0.2, size * 0.2)
    p.setPen(QtGui.QColor("white"))
    p.setFont(QtGui.QFont("Arial", int(size * 0.38), QtGui.QFont.Bold))
    p.drawText(QtCore.QRect(0, 0, size, size), QtCore.Qt.AlignCenter, txt)
    p.end()
    return QtGui.QIcon(pm)


def load_icon(name, cfg=None):
    """QIcon from the auto-detected icon folder; built-in painted icon if the file is missing/unreadable."""
    path = core.find_icon(name, cfg)
    if path:
        ic = QtGui.QIcon(path)
        if not ic.isNull() and not ic.pixmap(16, 16).isNull():
            return ic
        # SVG plugin missing -> try a PNG sibling
        png = os.path.splitext(path)[0] + ".png"
        if os.path.isfile(png):
            ic = QtGui.QIcon(png)
            if not ic.isNull():
                return ic
    return _painted_icon(name)


TOGGLE_ICON_SIZE = QtCore.QSize(30, 16)       # on / off switch shown on every toggle button


def _painted_switch(on):
    """Built-in on/off switch, used when icons/toggle_on.png / toggle_off.png are missing."""
    w, h = 96, 52
    pm = QtGui.QPixmap(w, h)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor("#2ac4f2" if on else "#b0b0b0"))
    p.drawRoundedRect(0, 0, w, h, h / 2.0, h / 2.0)
    p.setBrush(QtGui.QColor("white"))
    d = h - 12
    p.drawEllipse(w - d - 6 if on else 6, 6, d, d)
    p.end()
    return QtGui.QIcon(pm)


def switch_icon(on, cfg=None):
    """toggle_on / toggle_off icon from the icon folder (painted fallback)."""
    name = "toggle_on" if on else "toggle_off"
    path = core.find_icon(name, cfg)
    if path:
        ic = QtGui.QIcon(path)
        if not ic.isNull() and not ic.pixmap(16, 16).isNull():
            return ic
    return _painted_switch(on)


def refresh_toggle_icon(b, cfg=None):
    b.setIcon(switch_icon(b.isChecked(), cfg))


def toggle_button(text, icon, cfg, tip="", checked=False):
    """Checkable push button drawn with an on / off switch (icons/toggle_on.png, toggle_off.png).
    Same isChecked()/setChecked()/toggled API as a checkbox, so existing code keeps working.
    'icon' is kept for compatibility (old per-button icon name)."""
    b = QtWidgets.QPushButton(text)
    b.setCheckable(True)
    b.setChecked(checked)
    b.setProperty("toggle", True)
    b.setIconSize(TOGGLE_ICON_SIZE)
    b.setCursor(QtCore.Qt.PointingHandCursor)
    b._icon_name = icon
    refresh_toggle_icon(b, cfg)
    b.toggled.connect(lambda _on, _b=b, _c=cfg: refresh_toggle_icon(_b, _c))
    if tip:
        b.setToolTip(tip)
    return b


SCOPE_BUTTONS = [("Global", "global", "Global"), ("Nuke Version", "major", "Major version"),
                 ("TD", "td", "TD level"), ("Studio", "studio", "Studio production level")]


def editor_button(key, cfg, tip=None):
    """Push button with the editor's icon, tooltip showing the detected executable."""
    b = QtWidgets.QPushButton(core.EDITORS[key]["label"])
    b.setIcon(load_icon(key, cfg))
    b.setIconSize(QtCore.QSize(18, 18))
    exe = core.find_editor(key, cfg)
    set_tip(b, tip or "Open in %s" % core.EDITORS[key]["label"],
            exe if exe else "(not found - set the path in Settings)")
    return b


# --------------------------------------------------------------------------
# splash: now lives in nk_splash.py (customize it there)
# --------------------------------------------------------------------------
from nk_splash import make_splash, SplashSettings  # noqa: E402,F401


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
class _ThreadCtx(core.NullCtx):
    def __init__(self, t):
        self.t = t

    def progress(self, v):
        self.t.progress.emit(int(v))

    def log(self, m):
        self.t.message.emit(str(m))

    def cancelled(self):
        return self.t._cancel


class TaskThread(QtCore.QThread):
    progress = QtCore.Signal(int)
    message = QtCore.Signal(str)
    result = QtCore.Signal(object)
    error = QtCore.Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            res = self.fn(_ThreadCtx(self))
        except core.Cancelled:
            self.error.emit("")
        except Exception as e:  # noqa
            self.error.emit(str(e) or e.__class__.__name__)
        else:
            self.result.emit(res)


class TextDialog(QtWidgets.QDialog):
    """Read-only text with optional accept button (used for plan review, snippets)."""

    def __init__(self, title, text, accept_text=None, parent=None, danger=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 560)
        lay = QtWidgets.QVBoxLayout(self)
        self.view = QtWidgets.QPlainTextEdit(text)
        self.view.setReadOnly(True)
        self.view.setFont(mono())
        self.view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        lay.addWidget(self.view)
        row = QtWidgets.QHBoxLayout()
        row.addStretch()
        if accept_text:
            ok = QtWidgets.QPushButton(accept_text)
            ok.setObjectName("primary")
            ok.clicked.connect(self.accept)
            row.addWidget(ok)
        cancel = QtWidgets.QPushButton("Cancel" if accept_text else "Close")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        lay.addLayout(row)
        set_tip(self.view, "<b>Preview</b><br>Read-only text. Select and copy with Ctrl+C.")
        if accept_text:
            set_tip(ok, "<b>%s</b><br>Confirm and continue." % accept_text)
        tip_buttons(self)


def _webengine():
    """(QWebEngineView, QWebEnginePage, QWebEngineProfile) or None when Nuke has no QtWebEngine."""
    try:
        try:
            from PySide2.QtWebEngineWidgets import QWebEngineView, QWebEnginePage, QWebEngineProfile
        except ImportError:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        return QWebEngineView, QWebEnginePage, QWebEngineProfile
    except Exception:
        return None


def _run_js(page, js, cb=None):
    """runJavaScript works differently in PySide2 (js, cb) and PySide6 (js, worldId, cb)."""
    if cb is None:
        page.runJavaScript(js)
        return
    try:
        page.runJavaScript(js, 0, cb)
    except TypeError:
        page.runJavaScript(js, cb)


_SIGNED_IN_JS = "/sign out|log out|logout/i.test(document.body.innerText)"
_LOGIN_JS = """(function(u,p,allow){
 function setv(el,v){var s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
  s.call(el,v);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}
 var pw=document.querySelector('input[type=password]');
 if(!pw){var t=[].slice.call(document.querySelectorAll('a,button')).filter(function(x){
   return x.textContent.trim().toLowerCase()==='sign in';});if(t.length){t[0].click();}return 'opened';}
 var f=pw.form,all=[].slice.call((f||document).querySelectorAll('input')),user=null;
 for(var i=0;i<all.length;i++){if(all[i]===pw)break;var ty=(all[i].type||'text').toLowerCase();
   if(ty==='text'||ty==='email')user=all[i];}
 if(user&&user.value!==u)setv(user,u);
 if(pw.value!==p)setv(pw,p);
 var tok=(f||document).querySelector('input[name="cf-turnstile-response"]');
 var widget=(f||document).querySelector('.cf-turnstile,iframe[src*="challenges.cloudflare"]');
 if((widget||tok)&&!(tok&&tok.value))return 'waiting';
 if(!allow)return 'waiting';
 var b=(f||document).querySelector('button[type=submit],input[type=submit]');
 if(!b){var c=[].slice.call((f||document).querySelectorAll('button')).filter(function(x){
   return x.textContent.trim().toLowerCase()==='sign in';});b=c[0];}
 if(b){b.click();}else if(f&&f.requestSubmit){f.requestSubmit();}else if(f){f.submit();}
 return 'submitted';})(%s,%s,%s)"""
_CLICK_DOWNLOAD_JS = ("(function(){var e=[].slice.call(document.querySelectorAll('a,button,li,span,div'))"
                      ".filter(function(x){return x.children.length<3&&x.textContent.trim().toLowerCase()==='download';});"
                      "if(e.length){e[0].click();return true}return false})()")


# Any Cloudflare Turnstile / challenge failure printed to the page console ("Verification failed",
# error 300010 / 600010 / 110200 ...) -> hand over to the real browser instead of leaving the user stuck.
_TURNSTILE_FAIL = re.compile(
    r"TurnstileError|turnstile[^\n]{0,80}(error|fail)|(error|fail)[^\n]{0,80}turnstile|"
    r"challenges\.cloudflare[^\n]{0,120}(error|fail|refused)|\b(3000\d\d|6000\d\d|1102\d\d)\b|cf-chl[^\n]{0,60}fail",
    re.I)

_WEB_PROFILE = [None]


def _web_profile(cfg):
    """One shared persistent profile per Nuke session (a new profile per dialog locks the storage files)."""
    if _WEB_PROFILE[0] is None:
        QWebEngineProfile = _webengine()[2]
        prof = QWebEngineProfile("nk_nukepedia")          # no parent: lives for the whole session
        path = os.path.join(core.root_dir(cfg), "webprofile")
        try:
            os.makedirs(path, exist_ok=True)
            prof.setPersistentStoragePath(path)
        except Exception:
            pass
        try:                                            # no on-disk HTTP cache (avoids "Unable to move the cache")
            cache = getattr(QWebEngineProfile, "HttpCacheType", None) or QWebEngineProfile
            prof.setHttpCacheType(getattr(cache, "MemoryHttpCache"))
        except Exception:
            pass
        try:                                            # Turnstile (error 300010) rejects the stock QtWebEngine UA
            ua = prof.httpUserAgent()
            prof.setHttpUserAgent(re.sub(r"\s*QtWebEngine/\S+", "", ua))
        except Exception:
            pass
        try:                                            # keep the login between sessions
            pol = getattr(QWebEngineProfile, "PersistentCookiesPolicy", None) or QWebEngineProfile
            prof.setPersistentCookiesPolicy(getattr(pol, "ForcePersistentCookies"))
        except Exception:
            pass
        _WEB_PROFILE[0] = prof
    return _WEB_PROFILE[0]


class _WebDownload(QtWidgets.QDialog):
    """Nukepedia page inside Nuke: sign in / pass the verification here, the file is captured automatically."""

    def __init__(self, parent, entry, folder, cfg):
        super().__init__(parent)
        QWebEngineView, QWebEnginePage, QWebEngineProfile = _webengine()
        self.setWindowTitle("Nukepedia - %s" % entry["name"])
        self.resize(980, 720)
        self.path, self._folder = "", folder
        lay = QtWidgets.QVBoxLayout(self)
        bar = QtWidgets.QHBoxLayout()
        self.info = QtWidgets.QLabel("Sign in if asked, then press Download and finish the verification. "
                                     "The file is taken automatically.")
        self.info.setWordWrap(True)
        self.b_dl = QtWidgets.QPushButton("Press Download")
        self.b_dl.setObjectName("primary")
        cancel = QtWidgets.QPushButton("Cancel")
        self.b_ext = QtWidgets.QPushButton("Open in browser")
        self.b_ext.setToolTip("If the verification keeps failing here (Cloudflare error 300010), "
                              "use your normal browser; the downloaded file is picked up from your Downloads folder.")
        self.b_ext.clicked.connect(self._use_browser)
        bar.addWidget(self.info, 1)
        bar.addWidget(self.b_dl)
        bar.addWidget(self.b_ext)
        bar.addWidget(cancel)
        lay.addLayout(bar)
        tip_buttons(self)
        set_tip(self.info, "<b>Nukepedia download</b><br>Sign in if asked, press Download on the page and finish the verification. "
                           "The downloaded file is taken automatically.")
        self.profile = _web_profile(cfg)
        self.view = QWebEngineView()
        owner = self

        class _Page(QWebEnginePage):
            def javaScriptConsoleMessage(self, *a):
                msg = " ".join(str(x) for x in a[:2])
                if _TURNSTILE_FAIL.search(msg):
                    QtCore.QTimer.singleShot(0, owner._turnstile_failed)

        self.page = _Page(self.profile, self.view)
        self.finished.connect(lambda _r: self._cleanup())
        self.view.setPage(self.page)
        lay.addWidget(self.view, 1)
        self._share_session()
        self._tried = False
        self.profile.downloadRequested.connect(self._on_download)
        self.page.loadFinished.connect(lambda ok: QtCore.QTimer.singleShot(1200, self._after_load))
        self.b_dl.clicked.connect(self._click)
        cancel.clicked.connect(self.reject)
        self._auto = True
        self._url, self._cfg = entry["url"], cfg
        self.view.load(QtCore.QUrl(entry["url"]))

    def _cleanup(self):
        try:
            self._wt.stop()
        except Exception:
            pass
        try:
            self._login_timer.stop()
        except Exception:
            pass
        try:
            self.profile.downloadRequested.disconnect(self._on_download)
        except Exception:
            pass
        self.view.setPage(None)
        self.page.deleteLater()

    def _share_session(self):
        """Hand the installer's Nukepedia login cookies to the embedded browser."""
        try:
            try:
                from PySide2.QtNetwork import QNetworkCookie
            except ImportError:
                from PySide6.QtNetwork import QNetworkCookie
            store = self.profile.cookieStore()
            for k, v in core.np_cookies():
                c = QNetworkCookie(k.encode(), v.encode())
                c.setDomain("www.nukepedia.com")
                c.setPath("/")
                store.setCookie(c, QtCore.QUrl("https://www.nukepedia.com/"))
        except Exception:
            pass

    def _after_load(self):
        _run_js(self.page, "document.body ? document.body.innerText.trim().slice(0,400) : ''", self._check_json)

    def _check_json(self, txt):
        """The login endpoint answers with raw JSON; don't leave the user stranded on it."""
        txt = txt or ""
        if txt.startswith("{") and '"success"' in txt:
            import json
            try:
                data = json.loads(txt)
            except Exception:
                data = {}
            if data.get("success"):
                self.view.load(QtCore.QUrl(self._url))
            else:
                self._tried = True              # don't retry the same wrong credentials
                self.info.setText("Nukepedia: %s Sign in manually in this window, then press Download."
                                  % (data.get("message") or "Login failed."))
                self.view.load(QtCore.QUrl(self._url))
            return
        _run_js(self.page, _SIGNED_IN_JS, self._signed_in)

    def _signed_in(self, yes):
        user, pw = core.np_credentials()
        if yes:
            self.info.setText("Signed in. Press Download / finish the verification.")
            self._click()
        elif user and not self._tried:
            self._tried = True
            self._login_ticks = 0
            self._login_user, self._login_pw = user, pw
            self.info.setText("Signing in to Nukepedia... if 'Verify you are human' shows, tick it - "
                              "sign-in and download continue automatically.")
            self._login_timer = QtCore.QTimer(self)
            self._login_timer.timeout.connect(self._login_tick)
            self._login_timer.start(1000)
        else:
            self.info.setText("Please sign in in this window (top right), then press Download.")

    def _turnstile_failed(self):
        if not getattr(self, "_ext", False):
            self._use_browser()

    def _use_browser(self):
        """Cloudflare's check cannot run in Nuke's old embedded browser: use the real browser and
        pick the finished download up from the Downloads folder."""
        if getattr(self, "_ext", False):
            return
        import time
        self._ext, self._since, self._last = True, time.time() - 2, None
        self._dirs = core.np_download_dirs(self._cfg)
        try:
            self._login_timer.stop()
        except Exception:
            pass
        webbrowser.open(self._url)
        self.b_dl.setEnabled(False)
        self.info.setText("Cloudflare's check does not work inside Nuke. Your browser opened the page: sign in, "
                          "click Download there. The file is picked up automatically from your Downloads folder.")
        self._wt = QtCore.QTimer(self)
        self._wt.timeout.connect(self._watch)
        self._wt.start(1000)

    def _watch(self):
        p = core.np_new_download(self._dirs, self._since)
        if not p:
            return
        size = os.path.getsize(p)
        if self._last == (p, size):
            self._wt.stop()
            self.path = p
            self.accept()
        else:
            self._last = (p, size)
            self.info.setText("Downloading %s ..." % os.path.basename(p))

    def _login_tick(self):
        import json
        self._login_ticks += 1
        if self._login_ticks > 120:
            self._login_timer.stop()
            self.info.setText("Sign-in timed out. Sign in manually in this window, then press Download.")
            return
        js = _LOGIN_JS % (json.dumps(self._login_user), json.dumps(self._login_pw),
                          "true" if self._login_ticks >= 3 else "false")
        _run_js(self.page, js, self._login_state)

    def _login_state(self, res):
        if res == "submitted":
            self._login_timer.stop()
            self.info.setText("Signing in...")
        elif res == "waiting" and self._login_ticks >= 3:
            self.info.setText("Tick 'Verify you are human' - sign-in continues automatically.")

    def _click(self):
        _run_js(self.page, _CLICK_DOWNLOAD_JS)
        if not getattr(self, "_armed", False):          # Cloudflare's iframe can't be read: if no file
            self._armed = True                          # starts within 25 s, hand over to the real browser
            QtCore.QTimer.singleShot(15000, self._no_download)

    def _no_download(self):
        if not getattr(self, "_got_dl", False) and not getattr(self, "_ext", False) and self.isVisible():
            self._use_browser()

    def _on_download(self, item):
        self._got_dl = True
        name = os.path.basename(item.suggestedFileName() if hasattr(item, "suggestedFileName")
                                else item.downloadFileName()) or "download.zip"
        os.makedirs(self._folder, exist_ok=True)
        if hasattr(item, "setDownloadDirectory"):
            item.setDownloadDirectory(self._folder)
            item.setDownloadFileName(name)
        else:
            item.setPath(os.path.join(self._folder, name))
        full = os.path.join(self._folder, name)
        self.info.setText("Downloading %s ..." % name)
        done = (lambda *_: self._finished(item, full))
        if hasattr(item, "isFinishedChanged"):
            item.isFinishedChanged.connect(done)
        else:
            item.finished.connect(done)
        item.accept()

    def _finished(self, item, full):
        if hasattr(item, "isFinished") and not item.isFinished():
            return
        if os.path.isfile(full) and os.path.getsize(full) > 0:
            self.path = full
            self.accept()


class _WaitDownload(QtWidgets.QDialog):
    """Waits for the browser to finish downloading the tool, then returns its path automatically."""

    def __init__(self, parent, name, why, dirs, since):
        super().__init__(parent)
        self.setWindowTitle("Waiting for the browser download")
        self.setMinimumWidth(480)
        self.path, self._dirs, self._since, self._last = "", dirs, since, None
        lay = QtWidgets.QVBoxLayout(self)
        lbl = QtWidgets.QLabel(
            "<b>%s</b><br>%s<br><br>The tool page is open in your browser. Click <b>Download</b> there "
            "(complete the verification). This window picks the file up automatically as soon as it "
            "lands in:<br><span style='color:#8d8e96'>%s</span>" % (
                name, why, "<br>".join(dirs) or "(no Downloads folder found)"))
        lbl.setWordWrap(True)
        lbl.setTextFormat(QtCore.Qt.RichText)
        lay.addWidget(lbl)
        self.status = QtWidgets.QLabel("Waiting...")
        self.status.setObjectName("hint")
        lay.addWidget(self.status)
        row = QtWidgets.QHBoxLayout()
        row.addStretch()
        pick = QtWidgets.QPushButton("Choose file...")
        cancel = QtWidgets.QPushButton("Cancel")
        row.addWidget(pick)
        row.addWidget(cancel)
        lay.addLayout(row)
        pick.clicked.connect(self._pick)
        cancel.clicked.connect(self.reject)
        self._t = QtCore.QTimer(self)
        self._t.timeout.connect(self._poll)
        self._t.start(1000)
        tip_buttons(self)
        set_tip(self.status, "<b>Download status</b><br>Shows the file being downloaded. The installer continues automatically when it finishes.")

    def _poll(self):
        p = core.np_new_download(self._dirs, self._since)
        if not p:
            return
        size = os.path.getsize(p)
        if self._last == (p, size):          # size unchanged for one second -> finished
            self.path = p
            self._t.stop()
            self.accept()
        else:
            self._last = (p, size)
            self.status.setText("Downloading %s ..." % os.path.basename(p))

    def _pick(self):
        start = self._dirs[0] if self._dirs else ""
        path, _f = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select the downloaded file", start, "Tool files (*.zip *.gizmo *.py *.nk);;All files (*)")
        if path:
            self.path = path
            self._t.stop()
            self.accept()


def table(headers, widths=None):
    t = QtWidgets.QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    t.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
    t.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setStretchLastSection(True)
    for i, w in enumerate(widths or []):
        t.setColumnWidth(i, w)
    return t


def fill(t, rows, keys=None):
    keep = selected_key(t) if keys else None      # keep the selected row across refreshes
    t.setRowCount(0)
    for r, row in enumerate(rows):
        t.insertRow(r)
        for c, val in enumerate(row):
            it = QtWidgets.QTableWidgetItem(str(val))
            if c == 0 and keys:
                it.setData(QtCore.Qt.UserRole, keys[r])
            t.setItem(r, c, it)
    if keep is not None and keys and keep in keys:
        t.selectRow(keys.index(keep))


def selected_key(t):
    r = t.currentRow()
    if r < 0 or not t.item(r, 0):
        return None
    k = t.item(r, 0).data(QtCore.Qt.UserRole)
    return k if k is not None else r


# --------------------------------------------------------------------------
# main window
# --------------------------------------------------------------------------
AUDIT_FILTERS = {                      # combo text -> action prefixes (None = everything)
    "All actions": None,
    "Uninstall (all uninstall log)": ("uninstall",),
    "Install / update": ("install", "self-update", "check-updates"),
    "Enable / disable / rollback": ("enable", "disable", "rollback", "register"),
    "Profiles & packs": ("profile", "import-pack", "export-pack"),
    "Edits & backups": ("edit", "restore-backup"),
    "Settings & login": ("settings", "splash", "np-"),
    "Failed / cancelled": ("-failed", "-cancelled"),
}


def audit_match(action, prefixes):
    if not prefixes:
        return True
    return any((p.startswith("-") and action.endswith(p)) or (not p.startswith("-") and action.startswith(p))
               for p in prefixes)


def audit_text(rec):
    """One audit record as a single log line: time, action, details."""
    detail = " ".join("%s=%s" % (k, v) for k, v in rec.items() if k not in ("time", "user", "host", "action"))
    return "[AUDIT] %s  %s  %s  %s" % (rec.get("time", "").replace("T", " "), rec.get("user", ""),
                                       rec.get("action", ""), detail)


class InstallerWindow(QtWidgets.QWidget):
    audit_line = QtCore.Signal(str)          # thread-safe path from core.audit() to the log panel

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._threads = []
        self._staged = None
        self._busy_buttons = []
        self._results = []
        self.setWindowTitle("Nuke Toolbox Pro  v%s" % core.VERSION)
        self.setMinimumSize(640, 420)
        self.resize(1180, 720)
        self.setAcceptDrops(True)
        self.setStyleSheet(load_stylesheet())

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.addWidget(self._build_header())
        # main splitter: [ tabs | log ]  |  side panel      (drag the handles; sizes are remembered)
        self.split_main = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.split_main.setChildrenCollapsible(False)
        outer.addWidget(self.split_main, 1)
        self.split_left = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.split_left.setChildrenCollapsible(False)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setMinimumSize(320, 200)
        self.split_left.setMinimumWidth(320)
        self.split_left.addWidget(self.tabs)
        side = self._build_side_panel()
        self.split_main.addWidget(self.split_left)
        self.split_main.addWidget(side)
        self._build_install()
        self._build_installed()
        self._build_editor()
        self._build_browse()
        self._build_profiles()
        self._build_safety()
        self._build_settings()
        # shared progress + log
        self.bar = QtWidgets.QProgressBar()
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(mono())
        logbox = QtWidgets.QWidget()
        lb = QtWidgets.QVBoxLayout(logbox)
        lb.setContentsMargins(0, 0, 0, 0)
        lb.addWidget(self.bar)
        lb.addWidget(self.log, 1)
        logbox.setMinimumHeight(60)
        self.split_left.addWidget(logbox)
        self.split_main.setStretchFactor(0, 1)
        self.split_main.setStretchFactor(1, 0)
        self.split_left.setStretchFactor(0, 1)
        self.split_left.setStretchFactor(1, 0)
        self._restore_splitters()
        self._setup_audit_mirror()
        self.tabs.currentChanged.connect(self._tab_changed)
        self._apply_role()
        self.refresh_all()
        apply_tooltips(self)

    # ---------- header (artist + detected Nuke) and GitHub side panel
    def _build_header(self):
        w = QtWidgets.QFrame()
        w.setObjectName("header")
        h = QtWidgets.QHBoxLayout(w)
        h.setContentsMargins(10, 6, 10, 6)
        self.artist_lbl = QtWidgets.QLabel()
        self.artist_lbl.setObjectName("artist")
        self.nuke_lbl = QtWidgets.QLabel()
        self.nuke_lbl.setObjectName("hint")
        h.addWidget(self.artist_lbl)
        h.addStretch()
        h.addWidget(self.nuke_lbl)
        self._refresh_header()
        return w

    def _refresh_header(self):
        self.artist_lbl.setText("VFX Artist: <b>%s</b>" % core.artist_name(self.cfg))
        try:
            self._nuke_installs = core.detect_nuke_installs()
        except Exception:
            self._nuke_installs = []
        self.nuke_lbl.setText(("Foundry " + core.nuke_summary(self._nuke_installs)) if self._nuke_installs or core.nuke_info()["inside"]
                              else "Foundry Nuke: not detected")
        tip = "\n".join("%s  -  %s" % (i["version"], i["path"]) for i in self._nuke_installs)
        self.nuke_lbl.setToolTip(tip or "Set NUKE_INSTALL_PATH if Nuke is installed in a custom folder.")
        if hasattr(self, "tabs"):
            apply_tooltips(self)

    def _build_side_panel(self):
        w = QtWidgets.QFrame()
        w.setObjectName("side")
        w.setMinimumWidth(300)
        outer_v = QtWidgets.QVBoxLayout(w)
        outer_v.setContentsMargins(4, 4, 4, 4)
        self.side_tabs = QtWidgets.QTabWidget()
        outer_v.addWidget(self.side_tabs)
        rg = QtWidgets.QHBoxLayout()
        rg.addWidget(QtWidgets.QLabel("init.py / menu.py:"))
        self.reg_auto = toggle_button("Automatic", "automatic", self.cfg, checked=True)
        self.reg_manual = toggle_button("Manual", "manual", self.cfg)
        self._reg_group = QtWidgets.QButtonGroup(self)          # exclusive, like the old radio buttons
        self._reg_group.setExclusive(True)
        self._reg_group.addButton(self.reg_auto)
        self._reg_group.addButton(self.reg_manual)
        self.reg_auto.setToolTip("Installer writes the init.py / menu.py registration for you")
        self.reg_manual.setToolTip("Files are installed only; you get the init.py / menu.py code to paste yourself")
        rg.addWidget(self.reg_auto)
        rg.addWidget(self.reg_manual)
        rg.addStretch()
        outer_v.addLayout(rg)
        gh_page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(gh_page)
        t = QtWidgets.QLabel("<b>Nuke tools on GitHub</b>")
        v.addWidget(t)
        row = QtWidgets.QHBoxLayout()
        self.gh_q = QtWidgets.QLineEdit()
        self.gh_q.setPlaceholderText("filter / search GitHub")
        self.gh_refresh = QtWidgets.QPushButton("Search")
        row.addWidget(self.gh_q)
        row.addWidget(self.gh_refresh)
        v.addLayout(row)
        self.gh_list = QtWidgets.QListWidget()
        self.gh_list.setSpacing(2)
        self.gh_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        v.addWidget(self.gh_list, 1)
        self.gh_status = QtWidgets.QLabel("")
        self.gh_status.setObjectName("hint")
        self.gh_status.setWordWrap(True)
        v.addWidget(self.gh_status)
        self.gh_install = QtWidgets.QPushButton("Install selected")
        self.gh_install.setObjectName("primary")
        v.addWidget(self.gh_install)
        self._gh_entries = []
        self.gh_refresh.clicked.connect(self._gh_search)
        self.gh_q.returnPressed.connect(self._gh_search)
        self.gh_install.clicked.connect(lambda: self._gh_install(self.gh_list.currentRow()))
        self.gh_list.itemDoubleClicked.connect(lambda it: self._gh_install(self.gh_list.row(it)))
        self._gh_populate(core.github_nuke_tools(self.cfg, online=False)[0])
        self.side_tabs.addTab(gh_page, "GitHub")
        self.side_tabs.addTab(self._build_np_page(), "Nukepedia")
        return w

    # ---------- Nukepedia panel: login, categories, deep search, install / uninstall
    def _build_np_page(self):
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)
        self.np_user = QtWidgets.QLineEdit(self.cfg.get("nukepedia_user", ""))
        self.np_user.setPlaceholderText("Username or email")
        self.np_pass = QtWidgets.QLineEdit()
        self.np_pass.setPlaceholderText("password")
        self.np_pass.setEchoMode(QtWidgets.QLineEdit.Password)
        self.np_login_btn = QtWidgets.QPushButton("Login")
        self.np_login_btn.setObjectName("primary")
        v.addWidget(self.np_user)
        lr = QtWidgets.QHBoxLayout()
        lr.addWidget(self.np_pass, 1)
        lr.addWidget(self.np_login_btn)
        v.addLayout(lr)
        self.np_cookie_btn = QtWidgets.QPushButton("Paste browser cookie (fallback)")
        self.np_cookie_btn.clicked.connect(self._np_cookie)
        v.addWidget(self.np_cookie_btn)
        # categories (same list as nukepedia.com/tools)
        self.np_cat = QtWidgets.QComboBox()
        self._np_cats = list(core.NP_DEFAULT_CATEGORIES)
        self._np_fill_cats()
        self.np_browse_btn = QtWidgets.QPushButton("Browse")
        cr = QtWidgets.QHBoxLayout()
        cr.addWidget(self.np_cat, 1)
        cr.addWidget(self.np_browse_btn)
        v.addLayout(cr)
        sr = QtWidgets.QHBoxLayout()
        self.np_q = QtWidgets.QLineEdit()
        self.np_q.setPlaceholderText("deep search all categories")
        self.np_search_btn = QtWidgets.QPushButton("Search")
        sr.addWidget(self.np_q, 1)
        sr.addWidget(self.np_search_btn)
        v.addLayout(sr)
        self.np_deep = toggle_button("Search every category (deep)", "deep", self.cfg,
                                     "Search all Nukepedia categories instead of only the selected one", True)
        v.addWidget(self.np_deep)
        v.addWidget(QtWidgets.QLabel("Install scope:"))
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(4)
        self.np_scope_btns = {}
        self._np_scope_group = QtWidgets.QButtonGroup(self)
        self._np_scope_group.setExclusive(True)
        for n, (label, icon, scope) in enumerate(SCOPE_BUTTONS):
            b = toggle_button(label, icon, self.cfg, "Install Nukepedia tools to: %s" % scope, n == 0)
            self._np_scope_group.addButton(b)
            self.np_scope_btns[scope] = b
            grid.addWidget(b, n // 2, n % 2)
        v.addLayout(grid)
        self.np_list = QtWidgets.QListWidget()
        self.np_list.setSpacing(2)
        self.np_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        v.addWidget(self.np_list, 1)
        self.np_status = QtWidgets.QLabel("Not signed in.")
        self.np_status.setObjectName("hint")
        self.np_status.setWordWrap(True)
        v.addWidget(self.np_status)
        self._np_entries = []
        self.np_login_btn.clicked.connect(self._np_login_clicked)
        self.np_pass.returnPressed.connect(self._np_login_clicked)
        self.np_search_btn.clicked.connect(self._np_search)
        self.np_q.returnPressed.connect(self._np_search)
        self.np_browse_btn.clicked.connect(self._np_browse)
        self.np_cat.activated.connect(lambda _i: self._np_browse())
        self._busy_buttons += [self.np_login_btn, self.np_search_btn, self.np_cookie_btn, self.np_browse_btn]
        self._np_sync()
        return page

    def _np_fill_cats(self):
        self.np_cat.clear()
        for name, slug, n in self._np_cats:
            self.np_cat.addItem("%s  (%d)" % (name, n), slug)

    def _np_sync(self):
        on = core.np_logged_in()
        self.np_login_btn.setText("Logout" if on else "Login")
        self.np_user.setEnabled(not on)
        self.np_pass.setEnabled(not on)
        self.np_cookie_btn.setEnabled(not on)
        if not self._threads:
            self.np_status.setText("Signed in as %s." % core.np_user() if on
                                   else "Not signed in (needed to install; browse/search work without).")

    def _np_login_clicked(self):
        if core.np_logged_in():
            core.np_logout()
            self._audit("np-logout")
            self._np_sync()
            return
        user, pw = self.np_user.text().strip(), self.np_pass.text()
        self.np_status.setText("Signing in...")
        self._run(lambda ctx: core.np_login(user, pw, self.cfg), self._np_logged)

    def _np_cookie(self):
        txt, ok = QtWidgets.QInputDialog.getMultiLineText(
            self, "Nukepedia cookie", "Log in at nukepedia.com in your browser, then paste the request "
            "'Cookie:' header (DevTools > Network):")
        if ok and txt.strip():
            self.np_status.setText("Checking cookie...")
            self._run(lambda ctx: core.np_login_cookie(txt, self.cfg), self._np_logged)

    def _np_logged(self, user):
        self._audit("np-login", user=user)
        self.np_pass.clear()
        if user != "browser session":
            self.cfg["nukepedia_user"] = user
            try:
                core.save_config(self.cfg)
            except Exception:
                pass
        self._np_sync()
        self.np_status.setText("Signed in as %s." % user)
        if not self._np_entries:
            self._np_browse()

    def _np_slug(self):
        return self.np_cat.currentData()

    def _np_browse(self):
        slug = self._np_slug()
        self.np_status.setText("Loading %s (first time reads every sub-category)..." % slug)
        self.bar.setValue(0)

        def work(ctx):
            try:
                cats = core.np_categories()
            except Exception:
                cats = None
            return cats, core.np_browse(self.cfg, slug, ctx)
        self._run(work, self._np_browsed)

    def _np_browsed(self, res):
        cats, tools = res
        if cats and cats != self._np_cats:
            cur = self._np_slug()
            self._np_cats = cats
            self._np_fill_cats()
            self.np_cat.setCurrentIndex(max(0, self.np_cat.findData(cur)))
        self.bar.setValue(100)
        self._np_show(tools, "in this category")

    def _np_search(self):
        q = self.np_q.text().strip()
        deep = self.np_deep.isChecked()
        slugs = None if deep else [self._np_slug()]
        self.np_status.setText("Deep search \"%s\" (first run indexes all categories)..." % q if deep
                               else "Searching...")
        self.bar.setValue(0)
        self._run(lambda ctx: core.np_search(self.cfg, q, ctx, slugs, True), self._np_searched)

    def _np_searched(self, tools):
        self.bar.setValue(100)
        self._np_show(tools, "match")

    SHOW_MAX = 150

    def _np_show(self, tools, what):
        self._np_entries = list(tools)[:self.SHOW_MAX]
        self.np_list.clear()
        for i, e in enumerate(self._np_entries):
            item = QtWidgets.QListWidgetItem()
            item.setToolTip("%s\n%s" % (e["url"], e.get("description", "")))
            box = QtWidgets.QWidget()
            h = QtWidgets.QHBoxLayout(box)
            h.setContentsMargins(4, 2, 4, 2)
            meta = "%s  \u2193%s%s" % (e.get("category", ""), "{:,}".format(e.get("downloads", 0)),
                                       ("  \u2605%s" % e["rating"]) if e.get("rating") else "")
            lbl = QtWidgets.QLabel("<b>%s</b><br><span style='color:#8d8e96'>%s</span>" % (
                e["name"][:28].replace("<", "&lt;"), meta[:40]))
            lbl.setTextFormat(QtCore.Qt.RichText)
            bi = QtWidgets.QPushButton("Install")
            bi.setFixedWidth(60)
            bi.clicked.connect(lambda _=False, n=i: self._np_install(n))
            bu = QtWidgets.QPushButton("Uninstall")
            bu.setFixedWidth(76)
            bu.setEnabled(core.np_installed(self.cfg, e) is not None)
            bu.clicked.connect(lambda _=False, n=i: self._np_uninstall(n))
            h.addWidget(lbl, 1)
            h.addWidget(bi)
            h.addWidget(bu)
            item.setSizeHint(QtCore.QSize(300, 46))
            self.np_list.addItem(item)
            tip_buttons(box)
            self.np_list.setItemWidget(item, box)
        total = len(tools)
        self.np_status.setText(("%d tool(s) %s" % (total, what)) + (
            " - showing first %d, refine the search" % self.SHOW_MAX if total > self.SHOW_MAX else ""))

    def _np_install(self, row):
        if row < 0 or row >= len(self._np_entries):
            return
        e = self._np_entries[row]
        self._flow = {"dry": self.dry_chk.isChecked(), "review": self.review_chk.isChecked()}
        scope = self.scope.currentText()
        reg = self._registration()
        self.bar.setValue(0)

        def work(ctx):
            try:
                return core.np_prepare(e, self.cfg, ctx, scope, reg)
            except core.NPManual as m:
                return ("manual", e, str(m))
        self._run(work, self._np_prepared)

    def _np_prepared(self, res):
        if not isinstance(res, tuple):
            self._prepared(res)
            return
        _tag, e, why = res
        self._log("Download needs the site's verification: %s" % why)
        if _webengine():
            dlg = _WebDownload(self, e, os.path.join(core.P(self.cfg, "cache", "nukepedia")), self.cfg)
        else:
            self._log("QtWebEngine is not available in this Nuke - using the system browser instead")
            import time
            webbrowser.open(e["url"])
            dlg = _WaitDownload(self, e["name"], why, core.np_download_dirs(self.cfg), time.time() - 2)
        run_dialog(dlg)
        path = dlg.path
        if not path:
            return
        scope = self.scope.currentText()
        name = core.clean_name(e["name"])
        reg = self._registration()
        self._log("Using downloaded file %s" % path)
        self._run(lambda ctx: core.prepare(core.InstallParams(
            source="Local zip / folder", src=path, name=name, scope=scope, registration=reg,
            group=core.np_group(e)), self.cfg, ctx), self._prepared)

    def _np_uninstall(self, row):
        if row < 0 or row >= len(self._np_entries):
            return
        e = self._np_entries[row]
        if not self._ask("Uninstall", "Remove %s and its init.py/menu.py entries?" % e["name"]):
            self._audit("uninstall-cancelled", tool=e["name"], via="Nukepedia panel")
            return
        try:
            name = core.np_uninstall(self.cfg, e, via="Nukepedia panel")
        except Exception as ex:
            self._audit("uninstall-failed", tool=e["name"], via="Nukepedia panel", error=str(ex))
            self._warn("Uninstall failed", str(ex))
            return
        self.refresh_all()
        self._np_show(self._np_entries, "shown")
        self._log("Uninstalled %s (Nukepedia panel) - see Safety & Log" % name)

    def _gh_populate(self, entries):
        self._gh_entries = list(entries)
        self.gh_list.clear()
        for i, e in enumerate(self._gh_entries):
            item = QtWidgets.QListWidgetItem()
            item.setToolTip("%s\n%s" % (e["url"], e["description"]))
            box = QtWidgets.QWidget()
            h = QtWidgets.QHBoxLayout(box)
            h.setContentsMargins(4, 2, 4, 2)
            lbl = QtWidgets.QLabel("<b>%s</b><br><span style='color:#8d8e96'>%s%s</span>" % (
                e["name"].split("/")[-1],
                ("\u2605 %s  " % e["stars"]) if e["stars"] != "" else "",
                (e["description"] or "")[:48]))
            lbl.setTextFormat(QtCore.Qt.RichText)
            b = QtWidgets.QPushButton("Install")
            b.setFixedWidth(64)
            b.clicked.connect(lambda _=False, n=i: self._gh_install(n))
            h.addWidget(lbl, 1)
            h.addWidget(b)
            item.setSizeHint(QtCore.QSize(260, 46))
            self.gh_list.addItem(item)
            tip_buttons(box)
            self.gh_list.setItemWidget(item, box)

    def _gh_search(self):
        q = self.gh_q.text()
        self.gh_status.setText("Searching GitHub...")
        self._run(lambda ctx: core.github_nuke_tools(self.cfg, q), self._gh_got)

    def _gh_got(self, res):
        entries, warn = res
        self._gh_populate(entries)
        self.gh_status.setText(warn or "%d tool(s) from GitHub" % len(entries))

    def _gh_install(self, row):
        if row is None or row < 0 or row >= len(self._gh_entries):
            self._warn("Select a tool", "Select a tool in the GitHub list first.")
            return
        self._apply_entry(self._gh_entries[row])
        self.install_btn.click()          # honours review / dry-run / scope choices on the Install tab

    def _restore_splitters(self):
        sz = self.cfg.get("ui_splitters") or {}
        a = sz.get("main") or [820, 360]
        b = sz.get("left") or [560, 120]
        self.split_main.setSizes(a)
        self.split_left.setSizes(b)
        if sz.get("window"):
            self.resize(*sz["window"])

    def closeEvent(self, e):
        try:
            self.cfg["ui_splitters"] = {"main": self.split_main.sizes(), "left": self.split_left.sizes(),
                                        "window": [self.width(), self.height()]}
            core.save_config(self.cfg)
        except Exception:
            pass
        super().closeEvent(e)

    def _registration(self):
        return "manual" if self.reg_manual.isChecked() else "auto"

    # ---------- small utils
    def _log(self, text):
        self.log.appendPlainText(text)

    def _setup_audit_mirror(self):
        """Show the recent audit history in the log panel and mirror every new audit entry (uninstall, install,
        enable / disable ...) into it live."""
        recent = core.read_audit(self.cfg, 25)
        if recent:
            self._log("--- Recent audit log (full history: Safety && Log tab) ---".replace("&&", "&"))
            for rec in reversed(recent):
                self._log(audit_text(rec))
        self.audit_line.connect(self._log)
        self._audit_cb = lambda rec: self.audit_line.emit(audit_text(rec))
        core.AUDIT_LISTENERS.append(self._audit_cb)
        self.destroyed.connect(lambda *_a, cb=self._audit_cb: core.AUDIT_LISTENERS.remove(cb)
                               if cb in core.AUDIT_LISTENERS else None)

    def _info(self, title, text):
        QtWidgets.QMessageBox.information(self, title, text)

    def _warn(self, title, text):
        QtWidgets.QMessageBox.warning(self, title, text)

    def _ask(self, title, text):
        return QtWidgets.QMessageBox.question(self, title, text) == QtWidgets.QMessageBox.Yes

    def _run(self, fn, on_result):
        t = TaskThread(fn)
        t.progress.connect(self.bar.setValue)
        t.message.connect(self._log)
        t.result.connect(on_result)
        t.error.connect(self._on_error)
        t.finished.connect(self._thread_done)
        self._threads.append(t)
        self._set_busy(True)
        t.start()

    def _thread_done(self):
        self._threads = [t for t in self._threads if t.isRunning()]
        if not self._threads:
            self._set_busy(False)

    def _set_busy(self, busy):
        for b in self._busy_buttons:
            b.setEnabled(not busy)
        self.cancel_btn.setText("Cancel" if busy else "Close")
        if not busy and hasattr(self, "np_login_btn"):
            self._np_sync()

    def _on_error(self, msg):
        self.bar.setValue(0)
        if not msg:
            self._log("Cancelled.")
            return
        self._log("ERROR: " + msg)
        QtWidgets.QMessageBox.critical(self, "Error", msg)

    def _tab_changed(self, i):
        if self.tabs.tabText(i).replace("&&", "&") == "Safety & Log":
            self.refresh_safety()
        elif self.tabs.tabText(i) == "Installed":
            self.refresh_installed()
        elif self.tabs.tabText(i) == "Profiles":
            self.refresh_profiles()

    def refresh_all(self):
        self._update_preview()
        self.refresh_installed()
        self.refresh_profiles()
        self.refresh_safety()

    # ---------- INSTALL tab
    def _build_install(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        mk = QtWidgets.QHBoxLayout()
        mk.addWidget(QtWidgets.QLabel("Marketplace:"))
        for name, url in MARKETPLACES.items():
            b = QtWidgets.QPushButton(name)
            b.clicked.connect(lambda _=False, u=url: webbrowser.open(u))
            mk.addWidget(b)
        mk.addStretch()
        lay.addLayout(mk)
        hint = QtWidgets.QLabel("Tip: drag a zip or tool folder onto this window.")
        hint.setObjectName("hint")
        lay.addWidget(hint)

        form = QtWidgets.QFormLayout()
        self.source = QtWidgets.QComboBox()
        self.source.addItems(SOURCE_ITEMS)
        self.src_path = QtWidgets.QLineEdit()
        self.src_path.setPlaceholderText("zip / folder path, or GitHub / GitLab / zip URL")
        self.browse_zip = QtWidgets.QPushButton("Zip...")
        self.browse_dir = QtWidgets.QPushButton("Folder...")
        row = QtWidgets.QHBoxLayout()
        for x in (self.src_path, self.browse_zip, self.browse_dir):
            row.addWidget(x)
        form.addRow("Source", self.source)
        form.addRow("Zip / folder / URL", row)

        self.ref_kind = QtWidgets.QComboBox()
        self.ref_kind.addItems(["Branch", "Release (tag)"])
        self.ref = QtWidgets.QComboBox()
        self.ref.setEditable(True)
        self.ref.lineEdit().setPlaceholderText("empty = default branch")
        self.fetch_btn = QtWidgets.QPushButton("Fetch versions")
        self.ref_row = QtWidgets.QWidget()
        rr = QtWidgets.QHBoxLayout(self.ref_row)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.addWidget(self.ref_kind)
        rr.addWidget(self.ref, 1)
        rr.addWidget(self.fetch_btn)
        self.ref_label = QtWidgets.QLabel("Download")
        form.addRow(self.ref_label, self.ref_row)

        self.type = QtWidgets.QComboBox()
        self.type.addItems(core.TOOL_TYPES)
        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("auto (tool.json / repo name)")
        self.version = QtWidgets.QLineEdit()
        self.version.setPlaceholderText("auto (tag / tool.json / date)")
        self.scope = QtWidgets.QComboBox()
        self.scope.addItems(core.SCOPES)
        self.sha = QtWidgets.QLineEdit()
        self.sha.setPlaceholderText("optional - verify the download")
        self.preview = QtWidgets.QLabel()
        self.preview.setObjectName("hint")
        self.preview.setWordWrap(True)
        form.addRow("Tool type", self.type)
        form.addRow("Tool folder name", self.name)
        form.addRow("Tool version", self.version)
        form.addRow("Install scope", self.scope)
        form.addRow("SHA-256", self.sha)
        form.addRow("Install to", self.preview)
        lay.addLayout(form)

        self.review_chk = toggle_button("Review what will be installed first (recommended)", "review", self.cfg,
                                        "Show the file list before anything is written", True)
        self.req_chk = toggle_button("Install requirements.txt (pip, into the tool's _deps folder)", "requirements",
                                     self.cfg, "pip install the tool's requirements into its _deps folder")
        self.dry_chk = toggle_button("Dry run - show the plan only, change nothing", "dryrun", self.cfg,
                                     "Show what would happen without changing anything")
        for c in (self.review_chk, self.req_chk, self.dry_chk):
            lay.addWidget(c)
        lay.addStretch()

        btns = QtWidgets.QHBoxLayout()
        self.install_btn = QtWidgets.QPushButton("Install")
        self.install_btn.setObjectName("primary")
        self.install_btn.setDefault(True)
        self.cancel_btn = QtWidgets.QPushButton("Close")
        self.open_btn = QtWidgets.QPushButton("Open folder")
        self.open_btn.setIcon(load_icon("folder", self.cfg))
        self.pycharm_btn = editor_button("pycharm", self.cfg, "Open the install folder in PyCharm")
        self.sublime_btn = editor_button("sublime", self.cfg, "Open the install folder in Sublime Text")
        btns.addWidget(self.open_btn)
        btns.addWidget(self.pycharm_btn)
        btns.addWidget(self.sublime_btn)
        btns.addStretch()
        btns.addWidget(self.install_btn)
        btns.addWidget(self.cancel_btn)
        lay.addLayout(btns)
        self.tabs.addTab(w, "Install")

        self.browse_zip.clicked.connect(self._browse_zip)
        self.browse_dir.clicked.connect(self._browse_dir)
        self.fetch_btn.clicked.connect(self._fetch_refs)
        self.install_btn.clicked.connect(self._on_install)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.open_btn.clicked.connect(self._open_folder)
        self.pycharm_btn.clicked.connect(lambda: self._open_editor("pycharm", self._install_target()))
        self.sublime_btn.clicked.connect(lambda: self._open_editor("sublime", self._install_target()))
        self.source.currentIndexChanged.connect(self._source_changed)
        self.src_path.textChanged.connect(self._source_changed)
        for x in (self.name, self.version):
            x.textChanged.connect(self._update_preview)
        self.scope.currentIndexChanged.connect(self._update_preview)
        self._wire_scope_toggles()
        self._busy_buttons.append(self.install_btn)
        self._source_changed()

    def _guess_source(self):
        try:
            return core.detect_source(self.src_path.text(), self.source.currentText())
        except core.NKError:
            return "Local"

    def _source_changed(self, *_):
        remote = self._guess_source() in ("GitHub URL", "GitLab URL") and bool(self.src_path.text().strip()) \
            or self.source.currentText() in ("GitHub URL", "GitLab URL")
        self.ref_row.setVisible(remote)
        self.ref_label.setVisible(remote)

    def _set_source_path(self, path):
        self.src_path.setText(path)
        if not self.name.text():
            base = os.path.basename(path.rstrip("/\\"))
            self.name.setText(core.clean_name(os.path.splitext(base)[0] if os.path.isfile(path) else base))

    def _browse_zip(self):
        f, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select tool zip", "", "Zip (*.zip)")
        if f:
            self._set_source_path(f)

    def _browse_dir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Select tool folder")
        if d:
            self._set_source_path(d)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if u.isLocalFile():
                self.tabs.setCurrentIndex(0)
                self._set_source_path(u.toLocalFile())
                return

    def _update_preview(self, *_):
        scope = self.scope.currentText()
        self.preview.setText(os.path.join(
            core.root_dir(self.cfg), core.scope_folder(scope),
            core.safe_name(self.name.text() or "<name>"),
            core.safe_name(self.version.text() or "<version>")))

    def _install_target(self):
        path = self.preview.text()
        while path and not os.path.isdir(path):
            nxt = os.path.dirname(path)
            if nxt == path:
                break
            path = nxt
        return path or core.root_dir(self.cfg)

    def _open_folder(self):
        self._open_path(self._install_target())

    def _open_editor(self, key, path):
        """Open a folder in PyCharm / Sublime Text; explain clearly if the editor can't be found."""
        try:
            core.open_in_editor(key, path, self.cfg)
            self._log("Opened %s in %s" % (path, core.EDITORS[key]["label"]))
        except core.NKError as e:
            self._warn(core.EDITORS[key]["label"], str(e))

    def _open_path(self, path):
        if not os.path.isdir(path):
            return
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            QtCore.QProcess.startDetached("open", [path])
        else:
            QtCore.QProcess.startDetached("xdg-open", [path])

    def _fetch_refs(self):
        url, source = self.src_path.text().strip(), self._guess_source()
        if source not in ("GitHub URL", "GitLab URL"):
            self._warn("Fetch versions", "Enter a GitHub or GitLab repository URL first.")
            return
        self._pending_fetch = (url, self.ref_kind.currentText(), source)
        self._run(lambda ctx: core.fetch_refs(*self._pending_fetch), self._got_refs)

    def _got_refs(self, refs):
        self.ref.clear()
        self.ref.addItems(refs)
        if not self.name.text():
            self.name.setText(core.repo_name(self.src_path.text()))
        kind = self.ref_kind.currentText().lower()
        self._log("Found %d %s(s)" % (len(refs), kind))
        if not refs:
            self._info("No versions found", "This repo has no %ss. Leave the version empty to install "
                                            "the default branch." % kind)

    def _params(self):
        return core.InstallParams(
            source=self.source.currentText(), src=self.src_path.text().strip(),
            name=self.name.text().strip(), version=self.version.text().strip(),
            ref=self.ref.currentText().strip() if self.ref_row.isVisible() else "",
            ref_kind=self.ref_kind.currentText(), scope=self.scope.currentText(),
            type=self.type.currentText(), sha256=self.sha.text().strip(),
            requirements=self.req_chk.isChecked(), registration=self._registration())

    # ---------- install flow: prepare -> review -> commit
    def _on_install(self):
        if not self.src_path.text().strip():
            self._warn("Missing info", "Choose a zip/folder or paste a URL first.")
            return
        self._start_install(self._params(), self.dry_chk.isChecked(), self.review_chk.isChecked())

    def _start_install(self, params, dry, review):
        self._flow = {"dry": dry, "review": review}
        self.bar.setValue(0)
        self._run(lambda ctx: core.prepare(params, self.cfg, ctx), self._prepared)

    def _prepared(self, st):
        pl = st.plan
        text = core.plan_text(st)
        if self._flow["dry"]:
            run_dialog(TextDialog("Dry run - nothing was installed", text, None, self))
            st.discard()
            self.bar.setValue(0)
            return
        if self._flow["review"] or pl["errors"] or pl["conflicts"] or pl["warnings"]:
            label = "Install anyway (errors!)" if pl["errors"] else "Install"
            dlg = TextDialog("Review install: %s" % st.name, text, label, self)
            if not run_dialog(dlg):
                st.discard()
                self.bar.setValue(0)
                self._log("Cancelled.")
                return
            if pl["errors"]:
                if not self._ask("Install despite errors?", "This package has blocking errors:\n\n- " +
                                 "\n- ".join(pl["errors"]) + "\n\nInstall anyway?"):
                    st.discard()
                    return
                st.params.force = True
        self._staged = st
        self._run(self._do_commit, self._installed)

    def _do_commit(self, ctx):
        return core.commit(self._staged, self.cfg, ctx)

    def _installed(self, res):
        self.bar.setValue(100)
        self.refresh_all()
        if res.get("manual"):
            self._info("Install complete (manual registration)",
                       "%s v%s installed to:\n%s\n\ninit.py / menu.py were NOT changed. Paste the code "
                       "shown next into your own init.py / menu.py." % (res["name"], res["version"], res["path"]))
            self._show_snippets(res["name"], *res["snippets"])
            return
        self._info("Install complete", "%s v%s installed to:\n%s\n\nRestart Nuke to load the tool. If Nuke "
                                       "fails to start, the crash guard disables it automatically."
                   % (res["name"], res["version"], res["path"]))

    def _show_snippets(self, name, init_code, menu_code):
        text = init_code + ("\n\n" + menu_code if menu_code else "")
        d = TextDialog("Manual registration - %s" % name, text, "Copy to clipboard", self)
        if run_dialog(d):
            QtWidgets.QApplication.clipboard().setText(text)
            self._log("Registration code copied to the clipboard")

    def _on_cancel(self):
        running = [t for t in self._threads if t.isRunning()]
        if running:
            for t in running:
                t.cancel()
            self._log("Cancelling...")
        else:
            self.close()

    # ---------- INSTALLED tab
    def _build_installed(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        self.inst_table = table(["Name", "Active", "Scope", "Type", "Status", "Update", "Versions"],
                                [170, 110, 100, 90, 90, 110])
        lay.addWidget(self.inst_table)
        row = QtWidgets.QHBoxLayout()
        self.b_check = QtWidgets.QPushButton("Check updates")
        self.b_update = QtWidgets.QPushButton("Update")
        self.b_roll = QtWidgets.QPushButton("Rollback...")
        self.b_toggle = QtWidgets.QPushButton("Enable / Disable")
        self.b_open = QtWidgets.QPushButton("Open folder")
        self.b_open.setIcon(load_icon("folder", self.cfg))
        self.b_pycharm = editor_button("pycharm", self.cfg, "Open the selected tool in PyCharm")
        self.b_sublime = editor_button("sublime", self.cfg, "Open the selected tool in Sublime Text")
        self.b_un = QtWidgets.QPushButton("Uninstall")
        self.b_edit = QtWidgets.QPushButton("Edit code")
        self.b_edit.setObjectName("primary")
        self.b_edit.setToolTip("Open this tool's install subfolder (incl. its init.py / menu.py) in the built-in "
                               "code editor")
        self.b_register = QtWidgets.QPushButton("Register (auto)")
        self.b_register.setToolTip("Write init.py / menu.py registration for a tool installed with Manual registration")
        self.b_code = QtWidgets.QPushButton("Show init/menu code")
        self.b_errors = QtWidgets.QPushButton("Check / fix errors")
        self.b_errors.setToolTip("Scan the tool for syntax errors and jump to the first one in the code editor")
        for b in (self.b_check, self.b_update, self.b_roll, self.b_toggle, self.b_un):
            row.addWidget(b)
        lay.addLayout(row)
        row2 = QtWidgets.QHBoxLayout()
        for b in (self.b_edit, self.b_errors, self.b_register, self.b_code, self.b_open, self.b_pycharm, self.b_sublime):
            row2.addWidget(b)
        row2.addStretch()
        lay.addLayout(row2)
        note = QtWidgets.QLabel("Changes take effect after restarting Nuke. Quarantined = switched off "
                                "by the crash guard; Enable to try again.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.tabs.addTab(w, "Installed")
        self.b_check.clicked.connect(self._check_updates)
        self.b_update.clicked.connect(self._do_update)
        self.b_roll.clicked.connect(self._do_rollback)
        self.b_toggle.clicked.connect(self._do_toggle)
        self.b_open.clicked.connect(self._open_tool)
        self.b_edit.clicked.connect(lambda: self._edit_tool(False))
        self.b_errors.clicked.connect(lambda: self._edit_tool(True))
        self.b_pycharm.clicked.connect(lambda: self._open_tool_in("pycharm"))
        self.b_sublime.clicked.connect(lambda: self._open_tool_in("sublime"))
        self.b_un.clicked.connect(self._do_uninstall)
        self.b_register.clicked.connect(self._do_register)
        self.b_code.clicked.connect(self._do_code)
        self._busy_buttons += [self.b_check, self.b_update]

    def refresh_installed(self):
        reg, state = core.load_registry(self.cfg), core.load_state(self.cfg)
        rows, keys = [], []
        for tid, t in sorted(reg["tools"].items()):
            ui = t.get("update_info") or {}
            upd = ("-> " + str(ui.get("latest"))) if ui.get("available") else (
                "up to date" if ui.get("status") == "ok" else ("error" if ui.get("status") == "error" else ""))
            rows.append([t["name"], t.get("active_version", ""), t["scope"], t["type"],
                         core.tool_status(self.cfg, t, state) + ("" if t.get("registered", True) else " (manual)"), upd, len(t.get("versions", []))])
            keys.append(tid)
        fill(self.inst_table, rows, keys)

    def _sel_tool(self):
        tid = selected_key(self.inst_table)
        if tid is None:
            self._warn("Select a tool", "Select a tool in the list first.")
            return None
        return core.load_registry(self.cfg)["tools"].get(tid)

    def _check_updates(self):
        self._run(lambda ctx: core.check_all_updates(self.cfg, ctx), self._checked)

    def _checked(self, n):
        self.refresh_installed()
        self._info("Update check", "%d update(s) available." % n if n else "Everything is up to date "
                                                                             "(or not tracked by a repo).")

    def _do_update(self):
        t = self._sel_tool()
        if not t:
            return
        if not (t.get("update_info") or {}).get("available"):
            self._info("No update known", "Run 'Check updates' first - no newer version found for %s." % t["name"])
            return
        self._start_install(core.params_for_update(t), False, True)

    def _do_rollback(self):
        t = self._sel_tool()
        if not t:
            return
        vs = [v["version"] for v in sorted(t["versions"], key=lambda v: v.get("installed_at", ""), reverse=True)]
        cur = vs.index(t["active_version"]) if t["active_version"] in vs else 0
        v, ok = QtWidgets.QInputDialog.getItem(self, "Rollback", "Activate version of %s:" % t["name"], vs, cur, False)
        if ok and v != t["active_version"]:
            try:
                core.rollback(self.cfg, t["id"], v)
            except core.NKError as e:
                self._warn("Rollback failed", str(e))
                return
            self.refresh_installed()
            self._info("Rolled back", "%s now uses %s. Restart Nuke." % (t["name"], v))

    def _do_toggle(self):
        t = self._sel_tool()
        if not t:
            return
        enable = core.tool_status(self.cfg, t) != "Enabled"
        core.set_enabled(self.cfg, t["id"], enable)
        self.refresh_installed()
        self._log("%s %s (restart Nuke)" % (t["name"], "enabled" if enable else "disabled"))

    def _open_tool(self):
        t = self._sel_tool()
        v = t and core.active_version(t)
        if v:
            self._open_path(v["path"])

    def _build_editor(self):
        self.editor = nk_editor.EditorTab(self.cfg, icon_fn=lambda n: load_icon(n, self.cfg),
                                          warn_fn=self._warn, ask_fn=self._ask, log_fn=self._log)
        self.tabs.addTab(self.editor, "Code Editor")

    def _edit_tool(self, check=False):
        """Show the selected tool's install subfolder in the code editor (optionally scan for errors)."""
        t = self._sel_tool()
        v = t and core.active_version(t)
        if not v:
            return
        self.editor.set_tool("%s %s" % (t["name"], v.get("version", "")), v["path"])
        self.tabs.setCurrentWidget(self.editor)
        if check:
            self.editor.check_tool()

    def _open_tool_in(self, key):
        t = self._sel_tool()
        v = t and core.active_version(t)
        if v:
            self._open_editor(key, v["path"])

    def _do_register(self):
        t = self._sel_tool()
        if not t:
            return
        try:
            core.register_tool(self.cfg, t["id"])
        except Exception as e:
            self._warn("Register failed", str(e))
            return
        self.refresh_all()
        self._log("Registered %s in init.py / menu.py - restart Nuke" % t["name"])

    def _do_code(self):
        t = self._sel_tool()
        if t:
            self._show_snippets(t["name"], *core.tool_snippets(self.cfg, t["id"]))

    def _do_uninstall(self):
        t = self._sel_tool()
        if t and self._ask("Uninstall", "Remove %s (all %d version folders) and its init.py/menu.py entries?"
                           % (t["name"], len(t["versions"]))):
            try:
                core.uninstall(self.cfg, t["id"], via="Installed tab")
            except Exception as e:
                self._audit("uninstall-failed", tool=t["name"], id=t["id"], via="Installed tab", error=str(e))
                self._warn("Uninstall failed", str(e))
                return
            self.refresh_all()
            self._log("Uninstalled %s (%d version folder(s) removed, init.py / menu.py entries removed) - see Safety & Log"
                      % (t["name"], len(t["versions"])))
        elif t:
            self._audit("uninstall-cancelled", tool=t["name"], id=t["id"], via="Installed tab")

    # ---------- BROWSE tab
    def _build_browse(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        row = QtWidgets.QHBoxLayout()
        self.search_src = QtWidgets.QComboBox()
        self.search_src.addItems(["GitHub", "GitLab", "Studio catalog"])
        self.search_q = QtWidgets.QLineEdit()
        self.search_q.setPlaceholderText("search, e.g. 'gizmo', 'stamps', 'roto'")
        self.search_btn = QtWidgets.QPushButton("Search")
        self.search_btn.setObjectName("primary")
        for x in (self.search_src, self.search_q, self.search_btn):
            row.addWidget(x)
        row.setStretch(1, 1)
        lay.addLayout(row)
        self.res_table = table(["Name", "Stars", "Updated", "Description"], [240, 60, 90])
        lay.addWidget(self.res_table)
        brow = QtWidgets.QHBoxLayout()
        self.use_btn = QtWidgets.QPushButton("Use in Install tab")
        self.web_btn = QtWidgets.QPushButton("Open in browser")
        brow.addStretch()
        brow.addWidget(self.web_btn)
        brow.addWidget(self.use_btn)
        lay.addLayout(brow)
        self.tabs.addTab(w, "Browse")
        self.search_btn.clicked.connect(self._search)
        self.search_q.returnPressed.connect(self._search)
        self.use_btn.clicked.connect(self._use_result)
        self.res_table.doubleClicked.connect(self._use_result)
        self.web_btn.clicked.connect(self._open_result)
        self._busy_buttons += [self.search_btn, self.gh_refresh]

    def _search(self):
        kind, q = self.search_src.currentText(), self.search_q.text()
        self._run(lambda ctx: core.search(kind, q, self.cfg), self._got_results)

    def _got_results(self, res):
        self._results = res
        fill(self.res_table, [[r["name"], r["stars"], r["updated"], r["description"]] for r in res],
             list(range(len(res))))
        self._log("%d result(s)" % len(res))

    def _sel_result(self):
        k = selected_key(self.res_table)
        return self._results[k] if k is not None and k < len(self._results) else None

    def _use_result(self, *_):
        r = self._sel_result()
        if r:
            self._apply_entry(r)

    def _apply_entry(self, r):
        self.tabs.setCurrentIndex(0)
        self.source.setCurrentIndex(SOURCE_ITEMS.index("Auto-detect"))
        self.src_path.setText(r["url"])
        self.name.setText(core.clean_name(r["name"].split("/")[-1]))
        self.version.setText(r["version"])
        self.sha.setText(r["sha256"])
        if r["type"] in core.TOOL_TYPES:
            self.type.setCurrentText(r["type"])
        self.ref.setEditText(r["ref"])

    def _open_result(self):
        r = self._sel_result()
        if r:
            webbrowser.open(r["url"])

    # ---------- PROFILES tab
    def _build_profiles(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(QtWidgets.QLabel("Profiles - a saved set of enabled tools (per show / shot / department):"))
        self.prof_list = QtWidgets.QListWidget()
        lay.addWidget(self.prof_list)
        row = QtWidgets.QHBoxLayout()
        self.p_save = QtWidgets.QPushButton("Save current as...")
        self.p_apply = QtWidgets.QPushButton("Apply")
        self.p_del = QtWidgets.QPushButton("Delete")
        for b in (self.p_save, self.p_apply, self.p_del):
            row.addWidget(b)
        lay.addLayout(row)
        lay.addWidget(QtWidgets.QLabel("Tool packs - share a whole setup with a team:"))
        row2 = QtWidgets.QHBoxLayout()
        self.p_export = QtWidgets.QPushButton("Export pack...")
        self.p_import = QtWidgets.QPushButton("Import pack (batch install)...")
        row2.addWidget(self.p_export)
        row2.addWidget(self.p_import)
        lay.addLayout(row2)
        note = QtWidgets.QLabel("Applying a profile enables its tools and disables all others. "
                                "Restart Nuke afterwards. Packs list repo URLs (local installs are skipped).")
        note.setObjectName("hint")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch()
        self.tabs.addTab(w, "Profiles")
        self.p_save.clicked.connect(self._prof_save)
        self.p_apply.clicked.connect(self._prof_apply)
        self.p_del.clicked.connect(self._prof_delete)
        self.p_export.clicked.connect(self._pack_export)
        self.p_import.clicked.connect(self._pack_import)
        self._busy_buttons.append(self.p_import)

    def refresh_profiles(self):
        reg = core.load_registry(self.cfg)
        self.prof_list.clear()
        for n, ids in sorted(reg["profiles"].items()):
            self.prof_list.addItem("%s   (%d tools)" % (n, len(ids)))
            self.prof_list.item(self.prof_list.count() - 1).setData(QtCore.Qt.UserRole, n)

    def _prof_name(self):
        it = self.prof_list.currentItem()
        return it.data(QtCore.Qt.UserRole) if it else None

    def _prof_save(self):
        n, ok = QtWidgets.QInputDialog.getText(self, "Save profile", "Profile name:")
        if ok and n.strip():
            core.save_profile(self.cfg, n.strip())
            self.refresh_profiles()

    def _prof_apply(self):
        n = self._prof_name()
        if not n:
            return
        try:
            core.apply_profile(self.cfg, n)
        except core.NKError as e:
            self._warn("Profile", str(e))
            return
        self.refresh_installed()
        self._info("Profile applied", "Profile '%s' applied. Restart Nuke." % n)

    def _prof_delete(self):
        n = self._prof_name()
        if n and self._ask("Delete profile", "Delete profile '%s'?" % n):
            core.delete_profile(self.cfg, n)
            self.refresh_profiles()

    def _pack_export(self):
        f, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export pack", "nk_tools_pack.json", "JSON (*.json)")
        if f:
            skipped = core.export_pack(self.cfg, f)
            self._info("Pack exported", f + ("\n\nSkipped (installed from local files): " + ", ".join(skipped)
                                             if skipped else ""))

    def _pack_import(self):
        f, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import pack", "", "JSON (*.json)")
        if not f:
            return
        if not self._ask("Import pack", "Install every tool listed in this pack?\n\nEach package is validated; "
                                         "failures are skipped and reported."):
            return
        self._run(lambda ctx: core.import_pack(self.cfg, f, ctx), self._pack_done)

    def _pack_done(self, res):
        self.refresh_all()
        self._info("Pack import", "Installed: %s\n\nFailed: %s" % (
            ", ".join(res["installed"]) or "-", "\n".join(res["failed"]) or "-"))

    # ---------- SAFETY tab
    def _build_safety(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        frow = QtWidgets.QHBoxLayout()
        frow.addWidget(QtWidgets.QLabel("Audit log (who installed what, when):"))
        frow.addStretch()
        self.audit_filter = QtWidgets.QComboBox()
        self.audit_filter.addItems(list(AUDIT_FILTERS))
        self.audit_count = QtWidgets.QLabel("")
        self.audit_count.setObjectName("hint")
        frow.addWidget(self.audit_count)
        frow.addWidget(QtWidgets.QLabel("Show:"))
        frow.addWidget(self.audit_filter)
        lay.addLayout(frow)
        self.audit_filter.currentIndexChanged.connect(lambda _i: self.refresh_safety())
        self.audit_table = table(["Time", "User", "Action", "Tool / detail"], [150, 100, 120])
        self.audit_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        lay.addWidget(self.audit_table)
        arow = QtWidgets.QHBoxLayout()
        self.log_del_sel = QtWidgets.QPushButton("Delete selected")
        self.log_del_all = QtWidgets.QPushButton("Delete all shown")
        self.log_del_all.setProperty("color", "red")
        arow.addStretch()
        arow.addWidget(self.log_del_sel)
        arow.addWidget(self.log_del_all)
        lay.addLayout(arow)
        self.log_del_sel.clicked.connect(self._log_delete_selected)
        self.log_del_all.clicked.connect(self._log_delete_all)
        self._audit_recs = []
        lay.addWidget(QtWidgets.QLabel("init.py / menu.py backups (made automatically before every change):"))
        self.bk_table = table(["File", "Saved"], [100])
        self.bk_table.setMaximumHeight(140)
        lay.addWidget(self.bk_table)
        row = QtWidgets.QHBoxLayout()
        self.bk_restore = QtWidgets.QPushButton("Restore selected backup")
        self.bk_view = QtWidgets.QPushButton("View selected")
        self.bk_open = QtWidgets.QPushButton("Open backup folder")
        for b in (self.bk_restore, self.bk_view, self.bk_open):
            row.addWidget(b)
        lay.addLayout(row)
        self.tabs.addTab(w, "Safety && Log")
        self.bk_restore.clicked.connect(self._bk_restore)
        self.bk_view.clicked.connect(self._bk_view)
        self.bk_open.clicked.connect(lambda: self._open_path(core.P(self.cfg, "backups")))

    def _audit(self, action, **kw):
        """Write one audit-log entry and refresh the Safety & Log table right away."""
        try:
            core.audit(self.cfg, action, **kw)
            self.refresh_safety()
        except Exception:
            pass

    def refresh_safety(self):
        rows = []
        prefixes = AUDIT_FILTERS.get(self.audit_filter.currentText())
        total = 0
        self._audit_recs = []
        for a in core.read_audit(self.cfg, 5000):
            total += 1
            if not audit_match(a.get("action", ""), prefixes):
                continue
            self._audit_recs.append(a)
            detail = " ".join("%s=%s" % (k, v) for k, v in a.items()
                              if k not in ("time", "user", "host", "action"))
            rows.append([a.get("time", "").replace("T", " "), a.get("user", ""), a.get("action", ""), detail])
        fill(self.audit_table, rows)
        self.audit_count.setText("%d of %d entries" % (len(rows), total))
        for r, row in enumerate(rows):                       # full line as tooltip (details can be long)
            for c in range(len(row)):
                it = self.audit_table.item(r, c)
                if it is not None:
                    it.setToolTip("%s  %s  %s\n%s" % (row[0], row[1], row[2], row[3]))
        self._backups = core.list_backups(self.cfg)
        fill(self.bk_table, [[b["target"], b["stamp"]] for b in self._backups], list(range(len(self._backups))))

    def _log_delete(self, recs, what):
        if not recs:
            self._info("Delete log", "Nothing to delete.")
            return
        if not self._ask("Delete log", "Delete %s (%d entr%s) from the audit log?\n\nA copy of the whole log is kept in "
                         "the audit_backups folder, and the deletion itself is logged."
                         % (what, len(recs), "y" if len(recs) == 1 else "ies")):
            return
        try:
            n = core.delete_audit(self.cfg, recs)
        except Exception as e:
            self._warn("Delete failed", str(e))
            return
        self._log("Deleted %d audit log entr%s (%s)" % (n, "y" if n == 1 else "ies", what))
        self.refresh_safety()

    def _log_delete_selected(self):
        rows = sorted({i.row() for i in self.audit_table.selectedIndexes()})
        self._log_delete([self._audit_recs[r] for r in rows if r < len(self._audit_recs)], "the selected entries")

    def _log_delete_all(self):
        flt = self.audit_filter.currentText()
        self._log_delete(list(self._audit_recs), "all entries" if flt == "All actions" else "all shown entries (%s)" % flt)

    def _sel_backup(self):
        k = selected_key(self.bk_table)
        return self._backups[k] if k is not None and k < len(self._backups) else None

    def _bk_restore(self):
        b = self._sel_backup()
        if b and self._ask("Restore backup", "Replace the current %s with the backup from %s?\n\n"
                                              "(The current file is backed up first. Tools registered after "
                                              "that backup will stop loading until reinstalled.)"
                           % (b["target"], b["stamp"])):
            core.restore_backup(self.cfg, b["path"])
            self.refresh_safety()
            self._info("Restored", "%s restored. Restart Nuke." % b["target"])

    def _bk_view(self):
        b = self._sel_backup()
        if b:
            run_dialog(TextDialog("%s  %s" % (b["target"], b["stamp"]), core._read_text(b["path"]), None, self))

    # ---------- SETTINGS tab
    def _build_settings(self):
        w = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(w)
        self.s_role = QtWidgets.QComboBox()
        self.s_role.addItems(["artist", "td", "admin"])
        self.s_role.setCurrentText(core.current_role(self.cfg))
        env_role = bool(os.environ.get("NK_ROLE"))
        self.s_role.setEnabled(not env_role)
        self.s_root = QtWidgets.QLineEdit(self.cfg["install_root"] or core.root_dir(self.cfg))
        self.s_init = QtWidgets.QLineEdit(self.cfg["init_dir"] or core.init_dir(self.cfg))
        self.s_catalog = QtWidgets.QLineEdit(self.cfg["catalog"])
        self.s_catalog.setPlaceholderText("studio catalog.json - path or URL")
        self.s_self = QtWidgets.QLineEdit(self.cfg["self_update_url"])
        self.s_self.setPlaceholderText("GitHub / GitLab repo URL or zip of this installer")
        self.s_keep = QtWidgets.QSpinBox()
        self.s_keep.setRange(1, 20)
        self.s_keep.setValue(int(self.cfg["keep_versions"]))
        self.s_artist = QtWidgets.QLineEdit(self.cfg.get("artist_name", ""))
        self.s_artist.setPlaceholderText("auto: " + core.artist_name({}))
        self.s_icons = self._path_row(self.cfg.get("icon_dir", ""), core.find_icon_dir(self.cfg),
                                      "Icon folder", folder=True)
        self.s_pycharm = self._path_row(self.cfg.get("pycharm_path", ""), core.find_editor("pycharm", self.cfg),
                                        "PyCharm executable")
        self.s_sublime = self._path_row(self.cfg.get("sublime_path", ""), core.find_editor("sublime", self.cfg),
                                        "Sublime Text executable")
        self.s_startup = QtWidgets.QCheckBox("Check for tool updates when Nuke starts")
        self.s_startup.setChecked(bool(self.cfg["check_updates_on_start"]))
        form.addRow("Role" + (" (set by NK_ROLE)" if env_role else ""), self.s_role)
        form.addRow("Install root", self.s_root)
        form.addRow("init.py / menu.py folder", self.s_init)
        form.addRow("Studio catalog", self.s_catalog)
        form.addRow("Installer update URL", self.s_self)
        form.addRow("Artist name", self.s_artist)
        form.addRow("Icon folder", self.s_icons[0])
        form.addRow("PyCharm", self.s_pycharm[0])
        form.addRow("Sublime Text", self.s_sublime[0])
        form.addRow("Versions to keep per tool", self.s_keep)
        form.addRow("", self.s_startup)
        row = QtWidgets.QHBoxLayout()
        self.s_save = QtWidgets.QPushButton("Save settings")
        self.s_save.setObjectName("primary")
        self.s_splash = QtWidgets.QPushButton("Splash screen...")
        self.s_env = QtWidgets.QPushButton("NUKE_PATH snippet...")
        self.s_upd = QtWidgets.QPushButton("Update installer")
        for b in (self.s_save, self.s_splash, self.s_env, self.s_upd):
            row.addWidget(b)
        form.addRow(row)
        note = QtWidgets.QLabel("Role limits which install scopes this panel offers (artist: Global/Major, td: + TD, "
                                "admin: + Studio). It is a guard rail, not security - for hard enforcement make the "
                                "init.py folder read-only and set NK_ROLE in your launcher. Point 'init.py / menu.py "
                                "folder' at a shared NUKE_PATH folder for studio-wide deployment.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        form.addRow(note)
        self.tabs.addTab(w, "Settings")
        self.s_save.clicked.connect(self._save_settings)
        self.s_splash.clicked.connect(self._splash_settings)
        self.s_env.clicked.connect(self._show_env)
        self.s_upd.clicked.connect(self._self_update)
        self._busy_buttons.append(self.s_upd)

    def _path_row(self, value, detected, title, folder=False):
        """Line edit + Browse button. Empty value = auto-detect; the placeholder shows what was found."""
        box = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        edit = QtWidgets.QLineEdit(value or "")
        edit.setPlaceholderText(("auto: " + detected) if detected else "auto-detect (nothing found yet)")
        btn = QtWidgets.QPushButton("...")
        btn.setFixedWidth(34)
        h.addWidget(edit)
        h.addWidget(btn)

        def pick():
            if folder:
                p = QtWidgets.QFileDialog.getExistingDirectory(self, title, edit.text() or detected or "")
            else:
                p = QtWidgets.QFileDialog.getOpenFileName(self, title, edit.text() or detected or "")[0]
            if p:
                edit.setText(p)
        btn.clicked.connect(pick)
        return box, edit

    def _refresh_icons(self):
        """Re-apply icons/tooltips after the icon folder or editor paths changed."""
        for key, btns in (("pycharm", (self.pycharm_btn, self.b_pycharm)),
                          ("sublime", (self.sublime_btn, self.b_sublime))):
            exe = core.find_editor(key, self.cfg)
            for b in btns:
                b.setIcon(load_icon(key, self.cfg))
                set_tip(b, b.property("base_tip") or "Open in %s" % core.EDITORS[key]["label"],
                        exe if exe else "(not found - set the path in Settings)")
        for b in (self.open_btn, self.b_open):
            b.setIcon(load_icon("folder", self.cfg))
        for b in ([self.reg_auto, self.reg_manual, self.np_deep, self.review_chk, self.req_chk, self.dry_chk]
                  + list(self.np_scope_btns.values())):
            refresh_toggle_icon(b, self.cfg)

    def _wire_scope_toggles(self):
        """Nukepedia-tab scope buttons <-> the Install tab's scope combo (one shared value)."""
        for scope, b in self.np_scope_btns.items():
            b.toggled.connect(lambda on, sc=scope: on and self.scope.setCurrentText(sc))
        self.scope.currentTextChanged.connect(self._sync_scope_buttons)
        self._sync_scope_buttons(self.scope.currentText())

    def _sync_scope_buttons(self, text):
        b = self.np_scope_btns.get(text)
        if b is not None and not b.isChecked():
            b.setChecked(True)

    def _apply_role(self):
        allowed = core.allowed_scopes(self.cfg)
        model = self.scope.model()
        for i, s in enumerate(core.SCOPES):
            item = model.item(i)
            if item is not None:
                item.setEnabled(s in allowed)
        if self.scope.currentText() not in allowed:
            self.scope.setCurrentText(allowed[0])
        for sc, b in getattr(self, "np_scope_btns", {}).items():
            b.setEnabled(sc in allowed)

    def _save_settings(self):
        old_root = core.root_dir(self.cfg)
        root = self.s_root.text().strip()
        self.cfg.update(role=self.s_role.currentText(),
                        install_root="" if root == os.path.join(core.home_nuke(), "NK_tools") else root,
                        init_dir="" if self.s_init.text().strip() == core.home_nuke() else self.s_init.text().strip(),
                        catalog=self.s_catalog.text().strip(), self_update_url=self.s_self.text().strip(),
                        keep_versions=self.s_keep.value(), check_updates_on_start=self.s_startup.isChecked(),
                        artist_name=self.s_artist.text().strip(),
                        icon_dir=self.s_icons[1].text().strip(),
                        pycharm_path=self.s_pycharm[1].text().strip(),
                        sublime_path=self.s_sublime[1].text().strip())
        core.save_config(self.cfg)
        self._audit("settings-save", role=self.cfg["role"], root=core.root_dir(self.cfg), init_dir=core.init_dir(self.cfg),
                    keep_versions=self.cfg["keep_versions"], check_on_start=self.cfg["check_updates_on_start"])
        self._refresh_header()
        self._refresh_icons()
        self._apply_role()
        self.refresh_all()
        msg = "Settings saved."
        if core.root_dir(self.cfg) != old_root:
            msg += "\n\nInstall root changed: tools already installed stay in the old location and are no " \
                   "longer listed here."
        self._info("Settings", msg)

    def _splash_settings(self):
        d = SplashSettings(self.cfg, self)
        if run_dialog(d):
            self.cfg = d.result_config()
            self.editor.cfg = self.cfg
            core.save_config(self.cfg)
            self._audit("splash-save", title=self.cfg.get("splash_title", ""))
            self._info("Saved", "Splash settings saved. They show next time the tool opens.")

    def _show_env(self):
        run_dialog(TextDialog("NUKE_PATH for launchers (Rez / scripts)",
                              core.env_snippet(self.cfg) + "\n\nNote: TD/Studio scope conditions are evaluated "
                              "inside Nuke; this lists the paths of all enabled tools.", None, self))

    def _self_update(self):
        self._run(lambda ctx: core.check_self_update(self.cfg, ctx), self._self_checked)

    def _self_checked(self, info):
        if not info["newer"]:
            import shutil
            shutil.rmtree(info["tmp"], ignore_errors=True)
            self._info("Installer", "You have the latest version (%s)." % info["current"])
            return
        if self._ask("Update installer", "Update %s -> %s?\n\nThe current files are backed up first. "
                                         "Restart Nuke afterwards." % (info["current"], info["latest"])):
            core.apply_self_update(self.cfg, info)
            self._info("Installer updated", "Updated to %s. Restart Nuke." % info["latest"])
        else:
            import shutil
            shutil.rmtree(info["tmp"], ignore_errors=True)


# --------------------------------------------------------------------------
# entry
# --------------------------------------------------------------------------
_window = None


def show():
    """Open the installer (splash first). Works inside Nuke or standalone."""
    global _window
    cfg = core.load_config()
    app = QtWidgets.QApplication.instance()
    standalone = app is None
    if standalone:
        app = QtWidgets.QApplication(sys.argv)
    splash = make_splash(cfg)
    splash.show()
    app.processEvents()
    parent = None
    if not standalone:
        parent = next((w for w in app.topLevelWidgets() if w.inherits("QMainWindow")), None)
    _window = InstallerWindow(cfg, parent)
    _window.setWindowFlags(_window.windowFlags() | QtCore.Qt.Window)

    def open_main():
        splash.finish(_window)
        _window.show()
        _window.raise_()
        _window._gh_search()          # load the live GitHub list (falls back to the built-in one)

    QtCore.QTimer.singleShot(cfg["splash_ms"], open_main)
    if standalone:
        code = app.exec() if hasattr(app, "exec") and QtCore.__name__.startswith("PySide6") else app.exec_()
        sys.exit(code)
    return _window
