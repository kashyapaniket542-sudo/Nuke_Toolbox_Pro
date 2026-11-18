# -*- coding: utf-8 -*-
"""
NK_tools core  -  Qt-free logic + command line for the Nuke tool installer.

Everything the UI does lives here, so it can be scripted (render farm, deploy
scripts, CI) and unit-tested without Nuke or PySide.

Layout on disk (install root, default ~/.nuke/NK_tools):
    registry.json            installed tools, versions, profiles
    state.json               enabled/disabled/quarantined + crash-guard state
    audit.jsonl              who installed what, when
    backups/                 timestamped copies of init.py / menu.py
    cache/                   last downloaded zip per URL (offline fallback)
    _runtime/nk_tools_boot.py  tiny module imported from init.py / menu.py
    <scope>/<tool>/<version>/  the tool itself (scope = global, nuke15, td, studio)

Python 3.7+ (Nuke 13+).
"""
from __future__ import print_function

import argparse
import datetime
import getpass
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

VERSION = "2.0.0"

SCOPES = ["Global", "Major version", "TD level", "Studio production level"]
SCOPE_ALIASES = {"global": "Global", "major": "Major version",
                 "td": "TD level", "studio": "Studio production level", "studio production": "Studio production level"}
TOOL_TYPES = ["Auto-detect", "Python", "Gizmo", "TCL", ".nk", "DLL / Plugin"]
ROLE_SCOPES = {
    "artist": ["Global", "Major version"],
    "td": ["Global", "Major version", "TD level"],
    "admin": list(SCOPES),
}
SOURCE_HINTS = {
    "Local zip / folder": "Local", "Local": "Local",
    "GitHub URL": "GitHub URL", "GitLab URL": "GitLab URL",
    "Nukepedia / direct zip URL": "Direct URL", "Direct URL": "Direct URL",
}
SKIP_DIRS = {".git", ".github", "__pycache__", "_deps", "tests", "test",
             "docs", "doc", "node_modules", "__MACOSX"}
BIN_EXT = {".dll", ".so", ".dylib"}

DEFAULT_CONFIG = {
    "splash_title": "Nuke Toolbox Pro",
    "splash_subtitle": "Tool Deployment & Version Management for Nuke",
    "splash_image": "",
    "splash_bg": "#1e1f24",
    "splash_fg": "#f2a33a",
    "splash_ms": 1800,
    "splash_w": 520,              # splash size in pixels (Settings > Splash screen...)
    "splash_h": 260,
    "install_root": "",          # "" -> ~/.nuke/NK_tools
    "init_dir": "",              # where init.py / menu.py are written ("" -> ~/.nuke)
    "role": "td",                # artist | td | admin  (NK_ROLE env overrides)
    "catalog": "",               # studio catalog.json (path or URL)
    "self_update_url": "",       # repo or zip URL of this installer
    "keep_versions": 3,
    "check_updates_on_start": False,
    "artist_name": "",           # "" -> auto (NK_ARTIST, OS full name, login)
    "editor_theme": "",          # PyCharm Darcula | Sublime Monokai
    "icon_dir": "",              # "" -> auto-detect (see find_icon_dir)
    "ui_splitters": {},          # remembered splitter / window sizes
    "pycharm_path": "",          # "" -> auto-detect
    "sublime_path": "",          # "" -> auto-detect
}

DEFAULT_CATALOG = [
    {"name": "LumaNukeGizmos",
     "description": "Open-source gizmos from Luma Pictures",
     "url": "https://github.com/LumaPictures/LumaNukeGizmos",
     "type": "Gizmo", "tags": ["gizmo"]},
    {"name": "Stamps",
     "description": "Smart node connection system for Nuke (Adrian Pueyo)",
     "url": "https://github.com/adrianpueyo/Stamps",
     "type": "Python", "tags": ["python", "workflow"]},
    {"name": "KnobScripter",
     "description": "Script editor for knobs and the Nuke script panel (Adrian Pueyo)",
     "url": "https://github.com/adrianpueyo/KnobScripter",
     "type": "Python", "tags": ["python", "scripting"]},
]


class NKError(Exception):
    pass


class Cancelled(NKError):
    pass


class NullCtx(object):
    """Progress/log/cancel hooks. The UI and CLI subclass this."""

    def progress(self, value):
        pass

    def log(self, msg):
        pass

    def cancelled(self):
        return False

    def check(self):
        if self.cancelled():
            raise Cancelled("Cancelled.")


class PrintCtx(NullCtx):
    def log(self, msg):
        print(msg)


# --------------------------------------------------------------------------
# paths / json / config
# --------------------------------------------------------------------------
def home_nuke():
    return os.environ.get("NK_HOME_NUKE") or os.path.join(os.path.expanduser("~"), ".nuke")


def config_path():
    return os.path.join(home_nuke(), "NK_tools_installer", "data","nk_tools_installer.json")


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    data = _read_json(config_path(), {})
    if isinstance(data, dict):
        cfg.update(data)
    return cfg


def save_config(cfg):
    _write_json(config_path(), cfg)



# --------------------------------------------------------------------------
# icons + external editors (PyCharm / Sublime Text)
# --------------------------------------------------------------------------
ICON_EXTS = (".png", ".svg", ".ico", ".jpg", ".jpeg")
ICON_NAMES = ("pycharm", "sublime", "folder")
ICON_FOLDER_NAMES = ("icons", "icon", "Icons", "resources/icons", "resources", "images", "assets/icons")


def _installer_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _icon_dir_ok(path):
    """A folder counts as an icon folder if it holds at least one known icon, or any image."""
    if not path or not os.path.isdir(path):
        return False
    try:
        names = os.listdir(path)
    except OSError:
        return False
    low = [n.lower() for n in names]
    for base in ICON_NAMES:
        for ext in ICON_EXTS:
            if base + ext in low:
                return True
    return any(os.path.splitext(n)[1] in ICON_EXTS for n in low)


def icon_dir_candidates(cfg=None):
    """Ordered places where an icon folder is looked for (existence not checked)."""
    here = _installer_dir()
    out = []
    if cfg and cfg.get("icon_dir"):
        out.append(cfg["icon_dir"])
    if os.environ.get("NK_ICON_DIR"):
        out.append(os.environ["NK_ICON_DIR"])
    bases = [here, os.path.dirname(here)]
    if cfg is not None:
        bases += [root_dir(cfg), os.path.join(root_dir(cfg), "_installer")]
    bases += [home_nuke()]
    out.append(os.path.join(home_nuke(), "NK_tools_installer", "icons"))
    bases += [p for p in os.environ.get("NUKE_PATH", "").split(os.pathsep) if p]
    for b in bases:
        for n in ICON_FOLDER_NAMES:
            out.append(os.path.join(b, *n.split("/")))
    seen, uniq = set(), []
    for p in out:
        k = os.path.normcase(os.path.abspath(p))
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def find_icon_dir(cfg=None):
    """Automatically detect the icon folder. Returns "" when nothing usable exists."""
    for p in icon_dir_candidates(cfg):
        if _icon_dir_ok(p):
            return os.path.abspath(p)
    return ""


def find_icon(name, cfg=None, icon_dir=None):
    """Path of icon `name` (png/svg/ico...) in the detected icon folder, or ""."""
    d = icon_dir if icon_dir is not None else find_icon_dir(cfg)
    if not d:
        return ""
    try:
        files = {f.lower(): f for f in os.listdir(d)}
    except OSError:
        return ""
    for ext in ICON_EXTS:          # png first: works without Qt's SVG plugin
        f = files.get(name.lower() + ext)
        if f:
            return os.path.join(d, f)
    return ""


def _glob_first(patterns):
    import glob
    hits = []
    for pat in patterns:
        hits += glob.glob(pat)
    hits = [h for h in hits if os.path.exists(h)]
    return sorted(hits)[-1] if hits else ""      # highest version name last


def _editor_search(key):
    """Common install locations per platform (first existing wins)."""
    home = os.path.expanduser("~")
    win = sys.platform.startswith("win")
    mac = sys.platform == "darwin"
    pf = [os.environ.get("ProgramFiles", r"C:\Program Files"),
          os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
          os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")]
    if key == "pycharm":
        if win:
            pats = []
            for base in pf:
                pats += [os.path.join(base, "JetBrains", "PyCharm*", "bin", "pycharm64.exe"),
                         os.path.join(base, "JetBrains", "PyCharm*", "bin", "pycharm.exe"),
                         os.path.join(base, "PyCharm*", "bin", "pycharm64.exe")]
            pats.append(os.path.join(os.environ.get("LOCALAPPDATA", ""), "JetBrains", "Toolbox",
                                     "scripts", "pycharm*.cmd"))
            return _glob_first(pats)
        if mac:
            return _glob_first(["/Applications/PyCharm*.app", os.path.join(home, "Applications", "PyCharm*.app"),
                                os.path.join(home, "Applications", "*", "PyCharm*.app")])
        return _glob_first(["/opt/pycharm*/bin/pycharm.sh", "/opt/pycharm*/bin/pycharm",
                            "/usr/local/bin/pycharm*", "/snap/bin/pycharm*",
                            os.path.join(home, ".local", "share", "JetBrains", "Toolbox", "scripts", "pycharm*"),
                            os.path.join(home, "pycharm*", "bin", "pycharm.sh")])
    if key == "sublime":
        if win:
            pats = []
            for base in pf:
                pats += [os.path.join(base, "Sublime Text*", "sublime_text.exe"),
                         os.path.join(base, "Sublime Text*", "subl.exe")]
            return _glob_first(pats)
        if mac:
            return _glob_first(["/Applications/Sublime Text*.app", os.path.join(home, "Applications", "Sublime Text*.app")])
        return _glob_first(["/opt/sublime_text/sublime_text", "/usr/bin/subl", "/usr/local/bin/subl",
                            "/snap/bin/subl", "/opt/sublime_text*/sublime_text"])
    return ""


EDITORS = {
    "pycharm": {"label": "PyCharm", "cfg": "pycharm_path", "env": "NK_PYCHARM",
                "commands": ("pycharm", "pycharm64", "pycharm.sh", "charm", "pycharm-professional",
                             "pycharm-community")},
    "sublime": {"label": "Sublime Text", "cfg": "sublime_path", "env": "NK_SUBLIME",
                "commands": ("subl", "sublime_text", "sublime", "sublime-text")},
}


def find_editor(key, cfg=None):
    """Locate an editor executable (or .app bundle on macOS). "" when not found.
    Order: Settings path -> environment variable -> PATH -> common install folders."""
    info = EDITORS[key]
    cand = []
    if cfg and cfg.get(info["cfg"]):
        cand.append(cfg[info["cfg"]])
    if os.environ.get(info["env"]):
        cand.append(os.environ[info["env"]])
    for c in cand:
        if os.path.exists(c):
            return c
    for cmd in info["commands"]:
        w = shutil.which(cmd)
        if w:
            return w
    return _editor_search(key)


def editor_command(key, target, cfg=None):
    """argv that opens `target` (file or folder) in the editor, or None if the editor is missing."""
    exe = find_editor(key, cfg)
    if not exe:
        return None
    if sys.platform == "darwin" and exe.endswith(".app"):
        return ["open", "-a", exe, target]
    return [exe, target]


def open_in_editor(key, target, cfg=None):
    """Launch the editor detached. Raises NKError with a helpful message on failure."""
    label = EDITORS[key]["label"]
    if not target or not os.path.exists(target):
        raise NKError("Nothing to open: %s does not exist." % (target or "(no path)"))
    cmd = editor_command(key, target, cfg)
    if not cmd:
        raise NKError("%s was not found. Set its path in Settings (or the %s environment variable)."
                      % (label, EDITORS[key]["env"]))
    kw = {}
    if sys.platform.startswith("win"):
        kw["creationflags"] = 0x00000008 | 0x00000200      # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **kw)
    except Exception as e:
        raise NKError("Could not start %s: %s" % (label, e))
    return cmd



# --------------------------------------------------------------------------
# artist + Foundry Nuke detection
# --------------------------------------------------------------------------
def artist_name(cfg=None):
    """Name shown in the UI: Settings -> NK_ARTIST -> OS full name -> login name."""
    if cfg and (cfg.get("artist_name") or "").strip():
        return cfg["artist_name"].strip()
    if os.environ.get("NK_ARTIST", "").strip():
        return os.environ["NK_ARTIST"].strip()
    try:
        import pwd
        full = pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0].strip()
        if full:
            return full
    except Exception:
        pass
    try:
        user = getpass.getuser()
    except Exception:
        user = os.environ.get("USERNAME") or os.environ.get("USER") or "artist"
    return re.sub(r"[._-]+", " ", user).title()


def _nuke_version_from_name(name):
    """'Nuke15.1v2' / 'Nuke15.1v2.app' -> ('15.1v2', (15, 1, 2)); None if not a Nuke folder."""
    m = re.match(r"^Nuke(?:X|Studio|Indie|Assist)?\s*(\d+)\.(\d+)(?:v(\d+))?", name, re.I)
    if not m:
        return None
    a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    return "%d.%dv%d" % (a, b, c), (a, b, c)


def detect_nuke_installs():
    """Find Foundry Nuke installations on this machine, newest first.
    Each: {"version": "15.1v2", "major": 15, "minor": 1, "path": folder, "exe": executable or ""}"""
    import glob
    roots = []
    if sys.platform.startswith("win"):
        for pf in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                   os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            roots.append(os.path.join(pf, "Nuke*"))
    elif sys.platform == "darwin":
        roots += ["/Applications/Nuke*", os.path.expanduser("~/Applications/Nuke*")]
    else:
        roots += ["/usr/local/Nuke*", "/opt/Nuke*", "/opt/foundry/Nuke*",
                  os.path.expanduser("~/Nuke*"), os.path.expanduser("~/foundry/Nuke*")]
    extra = os.environ.get("NUKE_INSTALL_PATH") or os.environ.get("NK_NUKE_ROOT")
    paths = []
    for r in roots:
        paths += glob.glob(r)
    if extra:
        paths += [extra] + glob.glob(os.path.join(extra, "Nuke*"))
    found, seen = [], set()
    for p in paths:
        if not os.path.isdir(p):
            continue
        v = _nuke_version_from_name(os.path.basename(p.rstrip("/\\")))
        if not v:
            continue
        key = os.path.realpath(p)
        if key in seen:
            continue
        seen.add(key)
        exe = ""
        cands = []
        if sys.platform.startswith("win"):
            cands = glob.glob(os.path.join(p, "Nuke*.exe"))
        elif sys.platform == "darwin":
            cands = glob.glob(os.path.join(p, "Nuke*.app", "Contents", "MacOS", "Nuke*")) + [p]
        else:
            cands = glob.glob(os.path.join(p, "Nuke[0-9]*")) + glob.glob(os.path.join(p, "Nuke"))
        cands = [c for c in cands if os.path.isfile(c) or c.endswith(".app")]
        if cands:
            exe = sorted(cands)[0]
        found.append({"version": v[0], "major": v[1][0], "minor": v[1][1], "patch": v[1][2],
                      "path": p, "exe": exe})
    found.sort(key=lambda d: (d["major"], d["minor"], d["patch"]), reverse=True)
    return found


def nuke_summary(installs=None):
    """One-line text, e.g. 'Nuke 15.1v2 (+1 more)' or 'no Foundry Nuke found'."""
    info = nuke_info()
    if info.get("inside"):
        try:
            import nuke
            return "Nuke %s (running)" % nuke.NUKE_VERSION_STRING
        except Exception:
            pass
    installs = detect_nuke_installs() if installs is None else installs
    if not installs:
        return "no Foundry Nuke found"
    s = "Nuke " + installs[0]["version"]
    return s + (" (+%d more)" % (len(installs) - 1) if len(installs) > 1 else "")


def github_nuke_tools(cfg, query="", online=True):
    """Tools for the side panel: live GitHub search (most starred) merged over the built-in list.
    Never raises - falls back to the built-in list when offline."""
    base = [e for e in DEFAULT_CATALOG]
    base = [_norm_entry(e) for e in base]
    if not online:
        return base, ""
    try:
        live = search("GitHub", query or "nuke gizmo", cfg)
    except Exception as e:
        return base, "GitHub unavailable (%s) - showing built-in list" % e
    seen = {e["url"].lower().rstrip("/") for e in live}
    return live + [e for e in base if e["url"].lower().rstrip("/") not in seen], ""



# --------------------------------------------------------------------------
# code editor support: file listing, error checks, safe save
# --------------------------------------------------------------------------
EDIT_EXTS = {".py", ".tcl", ".gizmo", ".nk", ".json", ".txt", ".md", ".cfg", ".ini", ".yaml", ".yml",
             ".toml", ".ui", ".qss", ".html", ".xml", ".csv", ".bat", ".sh"}
MAX_EDIT_BYTES = 2 * 1024 * 1024


def editable_files(root, limit=1000):
    """Relative paths of text/code files under root (skips .git, _deps, caches, binaries, huge files)."""
    out = []
    if not root or not os.path.isdir(root):
        return out
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in SKIP_DIRS and not d.startswith("."))
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            if os.path.splitext(fn)[1].lower() in EDIT_EXTS:
                try:
                    if os.path.getsize(p) > MAX_EDIT_BYTES:
                        continue
                except OSError:
                    continue
                out.append(os.path.relpath(p, root))
                if len(out) >= limit:
                    return out
    return out


def nuke_startup_files(cfg):
    """init.py / menu.py the installer manages (in the init.py/menu.py folder)."""
    d = init_dir(cfg)
    return [os.path.join(d, n) for n in ("init.py", "menu.py")]


def check_source(text, path=""):
    """Syntax problems of one file as [{"file","line","col","msg","severity"}].
    .py -> Python syntax (what makes Nuke print a traceback at startup);
    .gizmo/.nk/.tcl -> unbalanced { } braces (warning)."""
    ext = os.path.splitext(path)[1].lower()
    probs = []
    if ext == ".py" or not ext:
        try:
            compile(text, path or "<string>", "exec", dont_inherit=True)
        except SyntaxError as e:
            probs.append({"file": path, "line": e.lineno or 1, "col": e.offset or 0,
                          "msg": "%s: %s" % (type(e).__name__, e.msg), "severity": "error"})
        except ValueError as e:                    # e.g. null bytes
            probs.append({"file": path, "line": 1, "col": 0, "msg": str(e), "severity": "error"})
    elif ext in (".gizmo", ".nk", ".tcl"):
        depth, line_open = 0, []
        for n, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            i = 0
            while i < len(line):
                ch = line[i]
                if ch == "\\":
                    i += 2
                    continue
                if ch == "{":
                    depth += 1
                    line_open.append(n)
                elif ch == "}":
                    depth -= 1
                    if depth < 0:
                        probs.append({"file": path, "line": n, "col": i + 1, "msg": "Unmatched '}'",
                                      "severity": "warning"})
                        depth = 0
                    elif line_open:
                        line_open.pop()
                i += 1
        if depth > 0:
            probs.append({"file": path, "line": line_open[0] if line_open else 1, "col": 0,
                          "msg": "Unclosed '{' (%d missing '}')" % depth, "severity": "warning"})
    return probs


def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8"


def scan_folder_errors(folder):
    """Check every editable file of a tool folder. Absolute paths in the result."""
    probs = []
    for rel in editable_files(folder):
        p = os.path.join(folder, rel)
        try:
            text, _ = read_text(p)
        except OSError as e:
            probs.append({"file": p, "line": 1, "col": 0, "msg": "Cannot read: %s" % e, "severity": "error"})
            continue
        probs += check_source(text, p)
    return probs


def save_text(cfg, path, text):
    """Back up the old file (Safety & Log tab can restore it), then write atomically. Returns backup path."""
    bak = backup_file(cfg, path)
    tmp = path + ".nk_tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)
    audit(cfg, "edit", file=path)
    return bak

def root_dir(cfg):
    return cfg.get("install_root") or os.path.join(home_nuke(), "NK_tools")


def init_dir(cfg):
    return cfg.get("init_dir") or home_nuke()


def P(cfg, *parts):
    return os.path.join(root_dir(cfg), *parts)


def _fwd(path):
    return path.replace("\\", "/")


def now_iso():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", (s or "").strip()) or "tool"


def clean_name(s):
    s = re.sub(r"[-_ .]?(main|master|head)$", "", s or "", flags=re.I)
    s = re.sub(r"[-_ ]?v?\d+(\.\d+)+$", "", s)
    return s or "tool"


def ver_key(s):
    return tuple(int(x) for x in re.findall(r"\d+", s or ""))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------
# registry / state / role / audit
# --------------------------------------------------------------------------
def load_registry(cfg):
    reg = _read_json(P(cfg, "registry.json"), {})
    if not isinstance(reg, dict):
        reg = {}
    reg.setdefault("tools", {})
    reg.setdefault("profiles", {})
    return reg


def save_registry(cfg, reg):
    _write_json(P(cfg, "registry.json"), reg)


def load_state(cfg):
    s = _read_json(P(cfg, "state.json"), {})
    if not isinstance(s, dict):
        s = {}
    s.setdefault("disabled", [])
    s.setdefault("quarantined", [])
    s.setdefault("pending", None)
    s.setdefault("pending_started", False)
    return s


def save_state(cfg, state):
    _write_json(P(cfg, "state.json"), state)


def current_role(cfg):
    r = (os.environ.get("NK_ROLE") or cfg.get("role") or "td").lower()
    return r if r in ROLE_SCOPES else "td"


def allowed_scopes(cfg):
    return ROLE_SCOPES[current_role(cfg)]


AUDIT_LISTENERS = []        # callables(record) - lets the UI mirror every audit entry into its log live


def audit(cfg, action, **kw):
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"
    rec = {"time": now_iso(), "user": user, "host": socket.gethostname(),
           "action": action}
    rec.update(kw)
    try:
        os.makedirs(root_dir(cfg), exist_ok=True)
        with open(P(cfg, "audit.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass
    for fn in list(AUDIT_LISTENERS):
        try:
            fn(rec)
        except Exception:
            pass


def delete_audit(cfg, records):
    """Delete audit entries (the given records, as returned by read_audit). The whole file is copied to
    <root>/audit_backups first, and a 'log-delete' entry is written afterwards. Returns how many were removed."""
    if not records:
        return 0
    path = P(cfg, "audit.jsonl")
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except IOError:
        return 0
    todo = list(records)
    kept, removed = [], 0
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            kept.append(line)
            continue
        if rec in todo:
            todo.remove(rec)
            removed += 1
        else:
            kept.append(line)
    if removed:
        bdir = P(cfg, "audit_backups")
        os.makedirs(bdir, exist_ok=True)
        shutil.copy2(path, os.path.join(bdir, "audit-%s.jsonl" % datetime.datetime.now().strftime("%Y%m%d-%H%M%S")))
        with open(path, "w", encoding="utf-8") as f:
            f.write("".join(l + "\n" for l in kept))
        audit(cfg, "log-delete", removed=removed)
    return removed


def read_audit(cfg, limit=500):
    out = []
    try:
        with open(P(cfg, "audit.jsonl"), "r", encoding="utf-8") as f:
            for line in f.readlines()[-limit:]:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except IOError:
        pass
    return list(reversed(out))


# --------------------------------------------------------------------------
# Nuke / scope helpers
# --------------------------------------------------------------------------
def nuke_info():
    try:
        import nuke
        return {"major": int(nuke.NUKE_VERSION_MAJOR),
                "minor": int(nuke.NUKE_VERSION_MINOR), "inside": True}
    except Exception:
        pass
    m = re.match(r"(\d+)\.(\d+)", os.environ.get("NK_NUKE_VERSION", ""))
    if m:
        return {"major": int(m.group(1)), "minor": int(m.group(2)), "inside": False}
    try:
        inst = detect_nuke_installs()
    except Exception:
        inst = []
    if inst:
        return {"major": inst[0]["major"], "minor": inst[0]["minor"], "inside": False}
    return {"major": 15, "minor": 0, "inside": False}


def os_key():
    if sys.platform.startswith("win"):
        return "win"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def scope_folder(scope, major=None):
    major = major or nuke_info()["major"]
    return {"Global": "global", "Major version": "nuke%d" % major,
            "TD level": "td", "Studio production level": "studio"}[scope]


def scope_condition(scope, major=None):
    major = major or nuke_info()["major"]
    return {
        "Global": "True",
        "Major version": "nuke.NUKE_VERSION_MAJOR == %d" % major,
        "TD level": "os.environ.get('NK_LEVEL', '').upper() == 'TD'",
        "Studio production level": "bool(nuke.env.get('studio'))",
    }[scope]


# --------------------------------------------------------------------------
# network helpers (GitHub / GitLab / direct)
# --------------------------------------------------------------------------
def _headers(url):
    h = {"User-Agent": "NK_tools-installer/" + VERSION}
    host = urllib.parse.urlparse(url).netloc.lower()
    if host.endswith("github.com") or host.endswith("githubusercontent.com"):
        tok = os.environ.get("GITHUB_TOKEN")
        if tok:
            h["Authorization"] = "Bearer " + tok
    elif "gitlab" in host:
        tok = os.environ.get("GITLAB_TOKEN")
        if tok:
            h["PRIVATE-TOKEN"] = tok
    return h


def _get_json(api):
    req = urllib.request.Request(api, headers=_headers(api))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise NKError("API rate limit reached. Wait a while, set a GITHUB_TOKEN / "
                          "GITLAB_TOKEN environment variable, or leave the version empty "
                          "to install the default branch.")
        if e.code == 404:
            raise NKError("Repository not found (private, or wrong URL).")
        raise NKError("HTTP error %s for %s" % (e.code, api))
    except urllib.error.URLError as e:
        raise NKError("Network error: %s" % e.reason)
    except (socket.timeout, TimeoutError) as e:
        raise NKError("Network error: timed out")


def parse_github(url):
    m = re.match(r"https?://github\.com/([^/]+)/([^/#?]+?)(?:\.git)?/?$", url.strip())
    return (m.group(1), m.group(2)) if m else None


def _gitlab_parts(url):
    p = urllib.parse.urlparse(re.sub(r"\.git$", "", url.strip().rstrip("/")))
    path = p.path.strip("/")
    if "/-/" in path:
        path = path.split("/-/")[0]
    return "%s://%s" % (p.scheme, p.netloc), path


def repo_name(url):
    return url.strip().rstrip("/").split("/")[-1].replace(".git", "")


def fetch_refs(url, kind, source="GitHub URL"):
    """Branch or tag names; the default branch comes first."""
    endpoint = "branches" if kind == "Branch" else "tags"
    if source == "GitLab URL":
        host, path = _gitlab_parts(url)
        base = "%s/api/v4/projects/%s" % (host, urllib.parse.quote(path, safe=""))
        names = [d["name"] for d in _get_json("%s/repository/%s?per_page=100" % (base, endpoint))]
    else:
        gh = parse_github(url)
        if not gh:
            raise NKError("Not a valid GitHub repo URL (https://github.com/user/repo)")
        base = "https://api.github.com/repos/%s/%s" % gh
        names = [d["name"] for d in _get_json("%s/%s?per_page=100" % (base, endpoint))]
    if kind == "Branch":
        default = _get_json(base).get("default_branch")
        if default in names:
            names.remove(default)
            names.insert(0, default)
    return names


def latest_commit(source, url, ref=""):
    if source == "GitLab URL":
        host, path = _gitlab_parts(url)
        base = "%s/api/v4/projects/%s" % (host, urllib.parse.quote(path, safe=""))
        ref = ref or _get_json(base).get("default_branch", "")
        data = _get_json("%s/repository/commits?ref_name=%s&per_page=1" % (base, urllib.parse.quote(ref)))
        return data[0]["id"] if data else ""
    gh = parse_github(url)
    if not gh:
        return ""
    api = "https://api.github.com/repos/%s/%s/commits/%s" % (gh[0], gh[1], urllib.parse.quote(ref or "HEAD"))
    return _get_json(api).get("sha", "")


def to_archive_url(source, url, ref="", kind="Branch"):
    """Repo URL (+ optional branch/tag) -> zip URL. Empty ref = default branch."""
    url = url.strip().rstrip("/")
    if url.lower().endswith(".zip"):
        return url
    if source == "GitHub URL":
        gh = parse_github(url)
        if not gh:
            raise NKError("Not a valid GitHub repo URL")
        base = "https://codeload.github.com/%s/%s/zip/" % gh
        if not ref:
            return base + "HEAD"
        return base + "refs/%s/%s" % ("tags" if kind.startswith("Release") else "heads", ref)
    if source == "GitLab URL":
        host, path = _gitlab_parts(url)
        api = "%s/api/v4/projects/%s/repository/archive.zip" % (host, urllib.parse.quote(path, safe=""))
        return api + ("?sha=" + urllib.parse.quote(ref, safe="") if ref else "")
    return url


def download(url, dest, ctx):
    req = urllib.request.Request(url, headers=_headers(url))
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                ctx.check()
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    ctx.progress(int(done * 55 / total))
    except urllib.error.HTTPError as e:
        raise NKError("Download failed: HTTP %s for %s" % (e.code, url))
    except urllib.error.URLError as e:
        raise NKError("Download failed: %s" % e.reason)
    except (socket.timeout, TimeoutError):
        raise NKError("Download failed: timed out")


def fetch_zip(url, dest, cfg, ctx):
    """Download with a per-URL cache that serves as an offline fallback."""
    cache_dir = P(cfg, "cache")
    cached = os.path.join(cache_dir, hashlib.sha1(url.encode("utf-8")).hexdigest() + ".zip")
    try:
        download(url, dest, ctx)
        try:
            os.makedirs(cache_dir, exist_ok=True)
            shutil.copyfile(dest, cached)
        except Exception:
            pass
    except NKError as e:
        if isinstance(e, Cancelled):
            raise
        if os.path.isfile(cached):
            ctx.log("%s -- using cached copy" % e)
            shutil.copyfile(cached, dest)
        else:
            raise


def safe_extract(zip_path, dest):
    with zipfile.ZipFile(zip_path) as z:
        base = os.path.realpath(dest)
        if sum(i.file_size for i in z.infolist()) > 2 * 1024 ** 3:
            raise NKError("Archive is larger than 2 GB uncompressed - refusing to extract.")
        for m in z.namelist():
            target = os.path.realpath(os.path.join(dest, m))
            if not (target == base or target.startswith(base + os.sep)):
                raise NKError("Unsafe path in zip: %s" % m)
        z.extractall(dest)


def flatten_single_root(folder):
    items = os.listdir(folder)
    if len(items) == 1 and os.path.isdir(os.path.join(folder, items[0])):
        inner = os.path.join(folder, items[0])
        for n in os.listdir(inner):
            shutil.move(os.path.join(inner, n), os.path.join(folder, n))
        os.rmdir(inner)


# --------------------------------------------------------------------------
# scanning / validation
# --------------------------------------------------------------------------
def load_manifest(stage):
    for n in ("tool.json", "nk_tool.json"):
        p = os.path.join(stage, n)
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                raise NKError("Invalid %s: %s" % (n, e))
            if not isinstance(data, dict):
                raise NKError("%s must contain a JSON object." % n)
            return data
    return {}


def scan_tree(root):
    """Classify a tool folder and work out which sub-folders belong on the plugin path."""
    info = {"gizmos": [], "py": [], "nk": [], "tcl": [], "bins": [], "icons": 0,
            "startup": [], "plugin_dirs": [], "packages": [], "modules": []}
    root = os.path.abspath(root)
    for dp, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        rel = os.path.relpath(dp, root)
        rel = "" if rel == "." else rel
        is_pkg = "__init__.py" in files and dp != root
        reg = (dp == root)
        for f in sorted(files):
            stem, ext = os.path.splitext(f)
            ext = ext.lower()
            relf = os.path.join(rel, f) if rel else f
            if ext == ".gizmo":
                info["gizmos"].append(stem)
                reg = True
            elif ext == ".py":
                info["py"].append(relf)
                reg = True
                if f in ("init.py", "menu.py"):
                    info["startup"].append(relf)
                elif not is_pkg and f != "setup.py":
                    info["modules"].append(stem)
            elif ext == ".nk":
                info["nk"].append(relf)
                reg = True
            elif ext == ".tcl":
                info["tcl"].append(relf)
                reg = True
            elif ext in BIN_EXT:
                info["bins"].append(relf)
                reg = True
            elif ext in (".png", ".xpm", ".jpg"):
                info["icons"] += 1
                reg = True
        if is_pkg:
            if os.path.dirname(rel) == "":
                info["packages"].append(os.path.basename(dp))
            dirs[:] = []
            reg = False
        if reg:
            info["plugin_dirs"].append(rel)
    if "" not in info["plugin_dirs"]:
        info["plugin_dirs"].insert(0, "")
    return info


def detect_type(info, manifest):
    t = manifest.get("type")
    if t in TOOL_TYPES[1:]:
        return t
    if info["bins"]:
        return "DLL / Plugin"
    if info["gizmos"]:
        return "Gizmo"
    if info["py"] and not (info["tcl"] or info["nk"]):
        return "Python"
    if info["tcl"] and not info["py"]:
        return "TCL"
    if info["nk"] and not info["py"]:
        return ".nk"
    return "Python" if info["py"] else ("TCL" if info["tcl"] else (".nk" if info["nk"] else "Python"))


def _vtuple(v):
    k = ver_key(str(v))
    return (k + (0, 0))[:2]


def check_compat(manifest, info, nk):
    errors, warnings = [], []
    cur = (nk["major"], nk["minor"])
    bucket = errors if nk["inside"] else warnings
    if manifest.get("nuke_min") and cur < _vtuple(manifest["nuke_min"]):
        bucket.append("Needs Nuke %s or newer (this is Nuke %d.%d)." % (manifest["nuke_min"], cur[0], cur[1]))
    if manifest.get("nuke_max") and cur > _vtuple(manifest["nuke_max"]):
        bucket.append("Tested up to Nuke %s (this is Nuke %d.%d)." % (manifest["nuke_max"], cur[0], cur[1]))
    plats = [str(p).lower() for p in manifest.get("platforms", [])]
    if plats and os_key() not in plats:
        errors.append("Tool supports %s only; this machine is %s." % ("/".join(plats), os_key()))
    if info["bins"]:
        want = {"win": ".dll", "mac": ".dylib", "linux": ".so"}[os_key()]
        if not any(b.lower().endswith(want) for b in info["bins"]):
            warnings.append("No %s binary found - the compiled plugin may not load on %s." % (want, os_key()))
    return errors, warnings


def validate_python(stage, info):
    warnings = []
    for rel in info["py"][:300]:
        p = os.path.join(stage, rel)
        try:
            if os.path.getsize(p) > 2 * 1024 * 1024:
                continue
            with open(p, "rb") as f:
                compile(f.read(), p, "exec")
        except SyntaxError as e:
            warnings.append("Syntax error in %s line %s (Python 2 code?)." % (rel, e.lineno))
        except Exception:
            pass
    return warnings


def startup_preview(stage, info, lines=12):
    out = []
    for rel in info["startup"]:
        try:
            with open(os.path.join(stage, rel), "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except IOError:
            continue
        out.append((rel, len(text.splitlines()), "\n".join(text.splitlines()[:lines])))
    return out


def find_conflicts(reg, tid, name, provides):
    out = []
    for oid, t in reg["tools"].items():
        if oid == tid:
            continue
        v = active_version(t)
        if not v:
            continue
        if safe_name(t["name"]).lower() == safe_name(name).lower():
            out.append("'%s' is already installed in scope '%s'." % (t["name"], t["scope"]))
        pv = v.get("provides", {})
        for g in sorted(set(provides["gizmos"]) & set(pv.get("gizmos", []))):
            out.append("Gizmo '%s' is also provided by %s." % (g, t["name"]))
        for m in sorted(set(provides["modules"]) & set(pv.get("modules", []))):
            out.append("Python module '%s' is also provided by %s." % (m, t["name"]))
    return out


def active_version(tool):
    for v in tool.get("versions", []):
        if v.get("version") == tool.get("active_version"):
            return v
    return None


# --------------------------------------------------------------------------
# init.py / menu.py management (managed blocks, backups, crash guard)
# --------------------------------------------------------------------------
RUNTIME_SRC = '''# Auto-generated by NK_tools installer - do not edit.
import json, os
_ROOT = __ROOT__
_STATE = os.path.join(_ROOT, "state.json")


def _load():
    try:
        with open(_STATE) as f:
            s = json.load(f)
    except Exception:
        s = {}
    s.setdefault("disabled", [])
    s.setdefault("quarantined", [])
    s.setdefault("pending", None)
    s.setdefault("pending_started", False)
    return s


def _save(s):
    try:
        tmp = _STATE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(s, f, indent=2)
        os.replace(tmp, _STATE)
    except Exception:
        pass


def _gui():
    try:
        import nuke
        return bool(nuke.GUI)
    except Exception:
        return False


def enabled(tool_id):
    s = _load()
    return tool_id not in s["disabled"] and tool_id not in s["quarantined"]


def start():
    """init.py: a freshly installed tool gets one start; if Nuke never reaches
    confirm() (menu.py end) it is quarantined on the next launch."""
    if not _gui():
        return
    s = _load()
    p = s.get("pending")
    if not p:
        return
    if s.get("pending_started"):
        if p not in s["quarantined"]:
            s["quarantined"].append(p)
        s["notice"] = ("Nuke Toolbox Pro: %s was disabled automatically because Nuke did not "
                       "finish starting after it was installed." % p)
        s["pending"] = None
        s["pending_started"] = False
    else:
        s["pending_started"] = True
    _save(s)


def confirm():
    if not _gui():
        return
    s = _load()
    if s.get("pending") and s.get("pending_started"):
        s["pending"] = None
        s["pending_started"] = False
    notice = s.pop("notice", None)
    _save(s)
    if notice:
        import nuke
        nuke.tprint(notice)
        nuke.executeInMainThread(nuke.message, (notice,))
'''


def _markers(tid):
    return "# >>> NK_TOOLS %s >>>" % tid, "# <<< NK_TOOLS %s <<<" % tid


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
            return f.read()
    except IOError:
        return ""


def backup_file(cfg, path):
    if not os.path.isfile(path):
        return None
    bdir = P(cfg, "backups")
    os.makedirs(bdir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = os.path.join(bdir, "%s.%s.bak" % (os.path.basename(path), stamp))
    shutil.copy2(path, dest)
    same = sorted(f for f in os.listdir(bdir) if f.startswith(os.path.basename(path) + "."))
    for old in same[:-30]:
        try:
            os.remove(os.path.join(bdir, old))
        except OSError:
            pass
    return dest


def list_backups(cfg):
    bdir = P(cfg, "backups")
    out = []
    if os.path.isdir(bdir):
        for f in sorted(os.listdir(bdir), reverse=True):
            m = re.match(r"^(init\.py|menu\.py)\.(\d{8}-\d{6})", f)
            if m:
                out.append({"path": os.path.join(bdir, f), "target": m.group(1), "stamp": m.group(2)})
    return out


def restore_backup(cfg, bpath):
    m = re.match(r"^(init\.py|menu\.py)\.", os.path.basename(bpath))
    if not m:
        raise NKError("Not an init.py/menu.py backup.")
    dest = os.path.join(init_dir(cfg), m.group(1))
    backup_file(cfg, dest)
    shutil.copyfile(bpath, dest)
    audit(cfg, "restore-backup", file=m.group(1), backup=os.path.basename(bpath))
    return dest


def _write_text(cfg, path, text):
    old = _read_text(path) if os.path.isfile(path) else None
    if old == text:
        return False
    if old is not None:
        backup_file(cfg, path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", errors="surrogateescape", newline="\n") as f:
        f.write(text)
    return True


def upsert_block(cfg, path, tid, block, position="keep"):
    """position: keep (replace in place / append), top, end."""
    text = _read_text(path)
    s, e = _markers(tid)
    pat = re.compile(re.escape(s) + r".*?" + re.escape(e) + r"\n?", re.S)
    block = block.rstrip("\n") + "\n"
    if pat.search(text) and position == "keep":
        new = pat.sub(lambda m: block, text, count=1)
    else:
        rest = pat.sub("", text).strip("\n")
        if position == "top":
            new = block + ("\n" + rest + "\n" if rest else "")
        else:
            new = (rest + "\n\n" if rest else "") + block
    return _write_text(cfg, path, new)


def remove_block(cfg, path, tid):
    if not os.path.isfile(path):
        return False
    text = _read_text(path)
    s, e = _markers(tid)
    pat = re.compile(re.escape(s) + r".*?" + re.escape(e) + r"\n?", re.S)
    if not pat.search(text):
        return False
    new = re.sub(r"\n{3,}", "\n\n", pat.sub("", text)).strip("\n")
    return _write_text(cfg, path, new + "\n" if new else "")


def ensure_boot(cfg):
    rt = P(cfg, "_runtime")
    os.makedirs(rt, exist_ok=True)
    with open(os.path.join(rt, "nk_tools_boot.py"), "w", encoding="utf-8") as f:
        f.write(RUNTIME_SRC.replace("__ROOT__", repr(_fwd(root_dir(cfg)))))
    boot = "\n".join([
        "# >>> NK_TOOLS __BOOT__ >>>",
        "# NK_tools installer runtime + crash guard (do not edit)",
        "import sys as _sys",
        "_nk_rt = %r" % _fwd(rt),
        "if _nk_rt not in _sys.path:",
        "    _sys.path.insert(0, _nk_rt)",
        "try:",
        "    import nk_tools_boot",
        "    nk_tools_boot.start()",
        "except Exception as _e:",
        "    print('NK_tools boot failed: %s' % _e)",
        "# <<< NK_TOOLS __BOOT__ <<<"])
    confirm = "\n".join([
        "# >>> NK_TOOLS __CONFIRM__ >>>",
        "try:",
        "    import nk_tools_boot",
        "    nk_tools_boot.confirm()",
        "except Exception as _e:",
        "    print('NK_tools confirm failed: %s' % _e)",
        "# <<< NK_TOOLS __CONFIRM__ <<<"])
    upsert_block(cfg, os.path.join(init_dir(cfg), "init.py"), "__BOOT__", boot, "top")
    upsert_block(cfg, os.path.join(init_dir(cfg), "menu.py"), "__CONFIRM__", confirm, "end")


def _q(s):
    return repr(s)


def _comment(s):
    return re.sub(r"[^\w .\-]", "", s or "")


def build_blocks(tool, v):
    """Return (init_block, menu_block_or_empty) text for one tool version."""
    tid, name = tool["id"], tool["name"]
    cond = "nk_tools_boot.enabled(%s) and (%s)" % (
        _q(tid), scope_condition(tool["scope"], tool.get("scope_major")))
    fail = "print('NK_tools: %s failed for %s: %%s' %% _e)"
    head = "# %s %s (%s, %s scope)" % (_comment(name), _comment(v["version"]), tool["type"], tool["scope"])

    ib = ["# >>> NK_TOOLS %s >>>" % tid, head, "try:", "    import nuke, os, nk_tools_boot",
          "    if %s:" % cond]
    for d in v["plugin_dirs"]:
        ib.append("        nuke.pluginAddPath(%s)" % _q(_fwd(d)))
    ib += ["except Exception as _e:", "    " + fail % ("loading", _comment(name)),
           "# <<< NK_TOOLS %s <<<" % tid]
    init_block = "\n".join(ib)

    entries = []
    if v.get("auto_menu"):
        for g in v.get("gizmos", []):
            entries.append("        _m.addCommand(%s, %s)" % (_q(g), _q("nuke.createNode(%s)" % _q(g))))
        for f in v.get("nk_files", []):
            label = os.path.splitext(os.path.basename(f))[0]
            entries.append("        _m.addCommand(%s, %s)" % (_q(label), _q("nuke.nodePaste(%s)" % _q(_fwd(f)))))
    custom = []
    for m in v.get("menu", []):
        if isinstance(m, dict) and m.get("path") and m.get("command"):
            line = "        nuke.menu(%s).addCommand(%s, %s" % (
                _q(m.get("menu", "Nuke")), _q(m["path"]), _q(m["command"]))
            if m.get("shortcut"):
                line += ", %s" % _q(m["shortcut"])
            custom.append(line + ")")
    if not entries and not custom:
        return init_block, ""
    mb = ["# >>> NK_TOOLS %s >>>" % tid, head, "try:", "    import nuke, os, nk_tools_boot",
          "    if %s:" % cond]
    if entries:
        mb.append("        _m = nuke.menu('Nodes').addMenu(%s)" % _q("Nuke Toolbox Pro/" + name))
        mb += entries
    mb += custom
    mb += ["except Exception as _e:", "    " + fail % ("menu", _comment(name)),
           "# <<< NK_TOOLS %s <<<" % tid]
    return init_block, "\n".join(mb)


def write_registration(cfg, tool, v):
    ib, mb = build_blocks(tool, v)
    upsert_block(cfg, os.path.join(init_dir(cfg), "init.py"), tool["id"], ib, "keep")
    menu_path = os.path.join(init_dir(cfg), "menu.py")
    if mb:
        upsert_block(cfg, menu_path, tool["id"], mb, "keep")
    else:
        remove_block(cfg, menu_path, tool["id"])
    ensure_boot(cfg)


def manual_snippets(tool, v):
    """Plain init.py / menu.py code for copy-paste (no NK_tools boot module needed)."""
    ini = ["# %s %s - add to init.py" % (_comment(tool["name"]), _comment(v["version"])), "import nuke"]
    for d in v["plugin_dirs"]:
        ini.append("nuke.pluginAddPath(%s)" % _q(_fwd(d)))
    men = []
    if v.get("auto_menu"):
        for g in v.get("gizmos", []):
            men.append("m.addCommand(%s, %s)" % (_q(g), _q("nuke.createNode(%s)" % _q(g))))
        for f in v.get("nk_files", []):
            men.append("m.addCommand(%s, %s)" % (_q(os.path.splitext(os.path.basename(f))[0]),
                                                 _q("nuke.nodePaste(%s)" % _q(_fwd(f)))))
    for m in v.get("menu", []):
        if isinstance(m, dict) and m.get("path") and m.get("command"):
            men.append("nuke.menu(%s).addCommand(%s, %s)" % (_q(m.get("menu", "Nuke")), _q(m["path"]), _q(m["command"])))
    menu = ""
    if men:
        head = ["# %s - add to menu.py" % _comment(tool["name"]), "import nuke",
                "m = nuke.menu('Nodes').addMenu(%s)" % _q("Nuke Toolbox Pro/" + tool["name"])]
        menu = "\n".join(head + men)
    return "\n".join(ini), menu


def tool_snippets(cfg, tid):
    tool = find_tool(load_registry(cfg), tid)
    v = next((x for x in tool["versions"] if x["version"] == tool.get("active_version")), tool["versions"][-1])
    return manual_snippets(tool, v)


def register_tool(cfg, tid):
    """Switch a manually installed tool to automatic init.py / menu.py registration."""
    reg = load_registry(cfg)
    tool = find_tool(reg, tid)
    v = next((x for x in tool["versions"] if x["version"] == tool.get("active_version")), tool["versions"][-1])
    write_registration(cfg, tool, v)
    tool["registered"] = True
    save_registry(cfg, reg)
    state = load_state(cfg)
    state["pending"], state["pending_started"] = tool["id"], False
    save_state(cfg, state)
    audit(cfg, "register", tool=tool["name"], id=tool["id"])
    return tool


# --------------------------------------------------------------------------
# install pipeline: prepare (download/extract/analyse) -> review -> commit
# --------------------------------------------------------------------------
class InstallParams(object):
    def __init__(self, **kw):
        self.source = "Auto-detect"
        self.src = ""
        self.name = ""
        self.version = ""
        self.ref = ""
        self.ref_kind = "Branch"          # Branch | Release (tag)
        self.scope = "Global"
        self.type = "Auto-detect"
        self.sha256 = ""
        self.requirements = False
        self.group = ""                  # optional sub-folder under the scope folder, e.g. "Nukepedia_tools"
        self.registration = "auto"       # auto | manual (manual = copy init.py / menu.py code yourself)
        self.force = False
        self.__dict__.update(kw)


class Staged(object):
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def discard(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def detect_source(src, hint="Auto-detect"):
    h = SOURCE_HINTS.get(hint)
    if h:
        return h
    s = src.strip().strip('"')
    if os.path.exists(s):
        return "Local"
    low = s.lower()
    if "github.com" in low:
        return "GitHub URL"
    if "gitlab" in low:
        return "GitLab URL"
    if low.startswith("http"):
        return "Direct URL"
    raise NKError("Cannot find '%s' - give an existing zip/folder or a URL." % src)


TOOL_FILE_EXTS = (".gizmo", ".py", ".nk", ".tcl", ".dll", ".so", ".dylib", ".pyd", ".blink", ".cpp", ".ofx", ".toolset")


def normalize_download(path, tmp):
    """Return a zip for whatever the browser saved: zip as-is; tar/tgz converted; a single tool file
    (.gizmo/.py/.nk/.tcl/.dll ...) wrapped; an HTML page is rejected with a clear message."""
    if zipfile.is_zipfile(path):
        return path
    base = os.path.splitext(os.path.basename(path))[0]
    out = os.path.join(tmp, safe_name(base) + "_n.zip")
    import tarfile
    if tarfile.is_tarfile(path):
        with tarfile.open(path) as t, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for m in t.getmembers():
                if m.isfile():
                    z.writestr(m.name, t.extractfile(m).read())
        return out
    with open(path, "rb") as f:
        head = f.read(4096)
    if head.lstrip()[:15].lower().startswith((b"<!doctype", b"<html", b"<?xml")) or b"<html" in head[:600].lower():
        raise NKError("The file is a web page, not a tool - the sign-in / verification was not completed "
                      "in the Nukepedia window.")
    ext = os.path.splitext(path)[1].lower()
    if ext not in TOOL_FILE_EXTS:                         # misnamed (e.g. a gizmo saved as .zip): sniff content
        if head[:2] == b"MZ":
            ext = ".dll"
        elif head[:4] == b"\x7fELF":
            ext = ".so"
        elif head[:4] in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
            ext = ".dylib"
        else:
            txt = head.decode("utf-8", "ignore")
            if re.search(r"^\s*Gizmo\s*\{", txt, re.M) or ("Group {" in txt and "knobs" in txt):
                ext = ".gizmo"
            elif txt.lstrip().startswith(("#! ", "set cut_paste_input", "version ", "Root {")) or re.search(r"^\s*\w+ \{\s*$", txt, re.M):
                ext = ".nk"
            elif re.search(r"^\s*(import |from \w+ import |def |class )", txt, re.M):
                ext = ".py"
            elif re.search(r"^\s*(proc |set |source )", txt, re.M):
                ext = ".tcl"
            else:
                return path
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(path, safe_name(base) + ext)
    return out


def _acquire(p, source, src, tmp, cfg, ctx):
    stage = os.path.join(tmp, "stage")
    if source == "Local":
        if os.path.isdir(src):
            ctx.log("Copying folder %s" % src)
            shutil.copytree(src, stage, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
            return stage, "", "", os.path.basename(src.rstrip("/\\"))
        if not os.path.isfile(src):
            raise NKError("File not found: %s" % src)
        zpath, guess = normalize_download(src, tmp), os.path.splitext(os.path.basename(src))[0]
    else:
        url = to_archive_url(source, src, p.ref, p.ref_kind)
        ctx.log("Downloading %s" % url)
        zpath = os.path.join(tmp, "download.zip")
        fetch_zip(url, zpath, cfg, ctx)
        guess = repo_name(src) if source != "Direct URL" else os.path.splitext(
            os.path.basename(urllib.parse.urlparse(url).path))[0]
    if not zipfile.is_zipfile(zpath):
        hint = (" Nukepedia needs a signed-in download: download the zip in your browser "
                "and use 'Local zip / folder'." if "nukepedia" in src.lower() else "")
        raise NKError("The download is not a valid zip file." + hint)
    zsha = sha256_file(zpath)
    if p.sha256 and zsha.lower() != p.sha256.strip().lower():
        raise NKError("SHA-256 mismatch!\n expected %s\n got      %s" % (p.sha256.strip(), zsha))
    commit = ""
    try:
        with zipfile.ZipFile(zpath) as z:
            c = z.comment.decode("ascii", "ignore").strip()
            if re.match(r"^[0-9a-f]{40}$", c):
                commit = c
    except Exception:
        pass
    os.makedirs(stage)
    ctx.log("Extracting")
    ctx.progress(60)
    safe_extract(zpath, stage)
    shutil.rmtree(os.path.join(stage, "__MACOSX"), ignore_errors=True)
    flatten_single_root(stage)
    return stage, zsha, commit, guess


def derive_version(p, manifest, source, commit):
    if p.version.strip():
        return p.version.strip()
    if p.ref and p.ref_kind.startswith("Release"):
        return p.ref
    if manifest.get("version"):
        return str(manifest["version"])
    base = (p.ref or "default") if source != "Local" else "local"
    return "%s-%s%s" % (base, datetime.date.today().strftime("%Y%m%d"),
                        ("-" + commit[:7]) if commit else "")


def prepare(p, cfg=None, ctx=None):
    cfg = cfg or load_config()
    ctx = ctx or NullCtx()
    if p.scope not in SCOPES:
        raise NKError("Unknown scope '%s'." % p.scope)
    if p.scope not in allowed_scopes(cfg):
        raise NKError("Role '%s' may not install to scope '%s' (allowed: %s)." % (
            current_role(cfg), p.scope, ", ".join(allowed_scopes(cfg))))
    src = (p.src or "").strip().strip('"')
    if not src:
        raise NKError("No zip / folder / URL given.")
    source = detect_source(src, p.source)
    tmp = tempfile.mkdtemp(prefix="nktools_")
    try:
        ctx.check()
        stage, zsha, commit, guess = _acquire(p, source, src, tmp, cfg, ctx)
        ctx.check()
        manifest = load_manifest(stage)
        info = scan_tree(stage)
        nk = nuke_info()
        name = p.name.strip() or str(manifest.get("name") or "") or clean_name(guess)
        ttype = p.type if p.type in TOOL_TYPES[1:] else detect_type(info, manifest)
        version = derive_version(p, manifest, source, commit)
        major = nk["major"]
        tid = "%s.%s" % (safe_name(name), scope_folder(p.scope, major))
        groups = [safe_name(x) for x in re.split(r"[\\/]+", getattr(p, "group", "") or "") if x.strip()]
        # grouped installs (Nukepedia) are flat: <scope>/<group...>/<tool name>/  - no version sub-folder
        tool_dir = os.path.join(*([root_dir(cfg), scope_folder(p.scope, major)] + groups
                                  + [safe_name(name)] + ([] if groups else [safe_name(version)])))

        errors, warnings = check_compat(manifest, info, nk)
        if not (info["gizmos"] or info["py"] or info["nk"] or info["tcl"] or info["bins"]):
            errors.append("No Nuke files (.gizmo .py .nk .tcl .dll/.so/.dylib) found in this package.")
        warnings += validate_python(stage, info)
        provides = {"gizmos": sorted(set(info["gizmos"])),
                    "modules": sorted(set(info["modules"] + info["packages"]))}
        reg = load_registry(cfg)
        conflicts = find_conflicts(reg, tid, name, provides)
        has_menu = any(os.path.basename(s) == "menu.py" for s in info["startup"])
        req_file = os.path.isfile(os.path.join(stage, "requirements.txt"))
        if req_file and not p.requirements:
            warnings.append("requirements.txt found but 'Install requirements' is off.")

        plugin_dirs = [os.path.join(tool_dir, d) if d else tool_dir for d in info["plugin_dirs"]]
        v = {"version": version, "path": tool_dir, "ref": p.ref, "commit": commit,
             "installed_at": now_iso(), "sha256": zsha, "plugin_dirs": plugin_dirs,
             "gizmos": provides["gizmos"],
             "nk_files": [os.path.join(tool_dir, f) for f in info["nk"]],
             "auto_menu": bool(manifest.get("auto_menu", not has_menu)),
             "menu": manifest.get("menu", []) if isinstance(manifest.get("menu", []), list) else [],
             "provides": provides, "description": str(manifest.get("description", ""))}
        tool_stub = {"id": tid, "name": name, "scope": p.scope, "type": ttype, "scope_major": major}
        ib, mb = build_blocks(tool_stub, v)
        plan = {"errors": errors, "warnings": warnings, "conflicts": conflicts,
                "startup": startup_preview(stage, info), "init_block": ib, "menu_block": mb,
                "ventry": v, "requirements": req_file, "gizmo_count": len(provides["gizmos"])}
        return Staged(tmp=tmp, stage=stage, params=p, source=source, src=src, name=name,
                      version=version, scope=p.scope, ttype=ttype, tid=tid, tool_dir=tool_dir,
                      major=major, plan=plan, info=info, manifest=manifest)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def plan_text(st):
    pl, v = st.plan, st.plan["ventry"]
    L = ["Tool      : %s  v%s" % (st.name, st.version),
         "Type      : %s" % st.ttype,
         "Scope     : %s  (id %s)" % (st.scope, st.tid),
         "Install to: %s" % st.tool_dir,
         "Register  : %s" % ("MANUAL - init.py / menu.py will not be touched; code is shown after install"
                             if getattr(st.params, "registration", "auto") == "manual"
                             else "Automatic (init.py + menu.py)"), ""]
    if v.get("description"):
        L += ["About     : %s" % v["description"], ""]
    L.append("Plugin paths (%d):" % len(v["plugin_dirs"]))
    L += ["  " + d for d in v["plugin_dirs"]]
    if v["gizmos"]:
        L.append("Gizmos (%d): %s%s" % (len(v["gizmos"]), ", ".join(v["gizmos"][:12]),
                                       " ..." if len(v["gizmos"]) > 12 else ""))
    if pl["menu_block"]:
        L.append("Menu entries will be added under Nodes > Nuke Toolbox Pro > %s" % st.name)
    for sec, items in (("ERRORS (install blocked)", pl["errors"]),
                       ("CONFLICTS", pl["conflicts"]), ("WARNINGS", pl["warnings"])):
        if items:
            L += ["", sec + ":"] + ["  ! " + i for i in items]
    if pl["startup"]:
        L += ["", "Startup scripts that will RUN every time Nuke starts - review them:"]
        for rel, n, prev in pl["startup"]:
            L.append("  --- %s (%d lines)" % (rel, n))
            L += ["  | " + ln for ln in prev.splitlines()]
    if getattr(st.params, "registration", "auto") != "manual":
        L += ["", "init.py block:", pl["init_block"]]
        if pl["menu_block"]:
            L += ["", "menu.py block:", pl["menu_block"]]
    return "\n".join(L)


def find_python():
    for n in ("python3", "python"):
        p = shutil.which(n)
        if p:
            return p
    if sys.executable and "nuke" not in os.path.basename(sys.executable).lower():
        return sys.executable
    return None


def _install_requirements(tool_dir, ctx):
    req = os.path.join(tool_dir, "requirements.txt")
    if not os.path.isfile(req):
        return None
    py = find_python()
    if not py:
        ctx.log("WARNING: no system Python found for pip - skipped requirements.txt")
        return None
    deps = os.path.join(tool_dir, "_deps")
    ctx.log("pip install -r requirements.txt -> _deps (compiled packages must match Nuke's Python)")
    r = subprocess.run([py, "-m", "pip", "install", "--disable-pip-version-check",
                        "--target", deps, "-r", req], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True, timeout=900)
    ctx.log("\n".join(r.stdout.strip().splitlines()[-6:]))
    if r.returncode != 0:
        raise NKError("pip failed (exit %d) - see log." % r.returncode)
    return deps


def commit(st, cfg=None, ctx=None):
    cfg = cfg or load_config()
    ctx = ctx or NullCtx()
    p, pl = st.params, st.plan
    try:
        if pl["errors"] and not p.force:
            raise NKError("Install blocked: " + "; ".join(pl["errors"]))
        existed = os.path.isdir(st.tool_dir)
        try:
            ctx.check()
            if existed:
                shutil.rmtree(st.tool_dir)
            os.makedirs(os.path.dirname(st.tool_dir), exist_ok=True)
            ctx.log("Installing to %s" % st.tool_dir)
            ctx.progress(75)
            shutil.move(st.stage, st.tool_dir)
            v = dict(pl["ventry"])
            if p.requirements:
                deps = _install_requirements(st.tool_dir, ctx)
                if deps:
                    v["plugin_dirs"] = v["plugin_dirs"] + [deps]
            reg = load_registry(cfg)
            tool = reg["tools"].get(st.tid) or {"id": st.tid, "versions": []}
            tool.update(name=st.name, type=st.ttype, scope=st.scope, scope_major=st.major,
                        source=st.source, source_url=st.src if st.source != "Local" else "",
                        ref=p.ref, ref_kind=p.ref_kind, requirements=bool(p.requirements),
                        group=getattr(p, "group", "") or "")
            if (getattr(p, "group", "") or "").strip():          # flat install: one folder, replaced in place
                tool["versions"] = [v]
            else:
                tool["versions"] = [x for x in tool["versions"] if x["version"] != v["version"]] + [v]
            tool["active_version"] = v["version"]
            tool.pop("update_info", None)
            manual = (getattr(p, "registration", "auto") == "manual")
            tool["registered"] = not manual
            if manual:
                ctx.log("Manual registration chosen - init.py / menu.py left untouched")
            else:
                ctx.log("Registering in init.py / menu.py")
                ctx.progress(90)
                write_registration(cfg, tool, v)
            _prune_versions(cfg, tool)
            reg["tools"][st.tid] = tool
            save_registry(cfg, reg)
            state = load_state(cfg)
            for k in ("disabled", "quarantined"):
                state[k] = [x for x in state[k] if x != st.tid]
            if not manual:
                state["pending"], state["pending_started"] = st.tid, False
            save_state(cfg, state)
            snippets = manual_snippets(tool, v) if manual else None
            audit(cfg, "install", tool=st.name, id=st.tid, version=v["version"], scope=st.scope,
                  type=st.ttype, source=st.source, src=st.src)
            ctx.progress(100)
        except BaseException:
            if not existed:
                shutil.rmtree(st.tool_dir, ignore_errors=True)
            raise
        return {"id": st.tid, "name": st.name, "version": st.version, "path": st.tool_dir,
                "manual": manual, "snippets": snippets}
    finally:
        st.discard()


def _prune_versions(cfg, tool):
    keep = max(1, int(cfg.get("keep_versions", 3)))
    olds = sorted([v for v in tool["versions"] if v["version"] != tool["active_version"]],
                  key=lambda v: v.get("installed_at", ""), reverse=True)
    for v in olds[keep - 1:]:
        shutil.rmtree(v["path"], ignore_errors=True)
        tool["versions"].remove(v)


def install_from(p, cfg=None, ctx=None, review=None, dry_run=False):
    """One-shot install for scripts/CLI. review(staged)->bool lets the caller veto."""
    cfg = cfg or load_config()
    st = prepare(p, cfg, ctx)
    try:
        if dry_run:
            return {"dry_run": True, "plan": plan_text(st)}
        if review and not review(st):
            raise Cancelled("Cancelled.")
    except BaseException:
        st.discard()
        raise
    return commit(st, cfg, ctx)


# --------------------------------------------------------------------------
# managing installed tools
# --------------------------------------------------------------------------
def find_tool(reg, key):
    if key in reg["tools"]:
        return reg["tools"][key]
    hits = [t for t in reg["tools"].values() if t["name"].lower() == key.lower()]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise NKError("'%s' is installed in several scopes - use the id: %s" % (
            key, ", ".join(t["id"] for t in hits)))
    raise NKError("No installed tool '%s'." % key)


def tool_status(cfg, tool, state=None):
    state = state or load_state(cfg)
    if tool["id"] in state["quarantined"]:
        return "Quarantined"
    if tool["id"] in state["disabled"]:
        return "Disabled"
    return "Enabled"


def set_enabled(cfg, tid, enabled):
    state = load_state(cfg)
    for k in ("disabled", "quarantined"):
        state[k] = [x for x in state[k] if x != tid]
    if not enabled:
        state["disabled"].append(tid)
    save_state(cfg, state)
    audit(cfg, "enable" if enabled else "disable", id=tid)


def uninstall(cfg, tid, via=""):
    """Remove a tool completely. Always written to the audit log (what, which versions, where from)."""
    reg = load_registry(cfg)
    tool = find_tool(reg, tid)
    tid = tool["id"]
    removed = [v.get("version", "?") for v in tool.get("versions", [])]
    folders = [v.get("path", "") for v in tool.get("versions", [])]
    remove_block(cfg, os.path.join(init_dir(cfg), "init.py"), tid)
    remove_block(cfg, os.path.join(init_dir(cfg), "menu.py"), tid)
    parents = set()
    for v in tool.get("versions", []):
        shutil.rmtree(v["path"], ignore_errors=True)
        parents.add(os.path.dirname(v["path"]))
    stop = os.path.normcase(os.path.abspath(root_dir(cfg)))
    for d in parents:                                   # remove empty tool + category folders, never above root
        x = d
        while os.path.normcase(os.path.abspath(x)).startswith(stop) and os.path.normcase(os.path.abspath(x)) != stop:
            try:
                os.rmdir(x)
            except OSError:
                break
            x = os.path.dirname(x)
            if os.path.basename(x).lower() in ("global", "td", "studio") or re.match(r"^nuke\d+$", os.path.basename(x).lower()):
                break
    del reg["tools"][tid]
    for name, ids in reg["profiles"].items():
        reg["profiles"][name] = [i for i in ids if i != tid]
    save_registry(cfg, reg)
    state = load_state(cfg)
    for k in ("disabled", "quarantined"):
        state[k] = [x for x in state[k] if x != tid]
    if state["pending"] == tid:
        state["pending"], state["pending_started"] = None, False
    save_state(cfg, state)
    ensure_boot(cfg)
    audit(cfg, "uninstall", tool=tool["name"], id=tid, versions=",".join(removed), scope=tool.get("scope", ""),
          type=tool.get("type", ""), folders=" | ".join(folders), via=via or "api", result="ok")


def rollback(cfg, tid, version):
    reg = load_registry(cfg)
    tool = find_tool(reg, tid)
    v = next((x for x in tool["versions"] if x["version"] == version), None)
    if not v or not os.path.isdir(v["path"]):
        raise NKError("Version '%s' is not available on disk." % version)
    tool["active_version"] = version
    if tool.get("registered", True):
        write_registration(cfg, tool, v)
    save_registry(cfg, reg)
    audit(cfg, "rollback", tool=tool["name"], id=tool["id"], version=version)
    return tool


# --------------------------------------------------------------------------
# updates
# --------------------------------------------------------------------------
def check_update(tool, cfg):
    src, url, v = tool.get("source"), tool.get("source_url"), active_version(tool)
    if src not in ("GitHub URL", "GitLab URL") or not url or not v:
        return {"status": "n/a", "available": False}
    try:
        if tool.get("ref_kind", "").startswith("Release"):
            tags = fetch_refs(url, "Release (tag)", src)
            if not tags:
                return {"status": "ok", "available": False, "latest": v["version"]}
            latest = max(tags, key=ver_key)
            cur = v.get("ref") or v["version"]
            return {"status": "ok", "latest": latest, "available": ver_key(latest) > ver_key(cur)}
        sha = latest_commit(src, url, tool.get("ref", ""))
        known = v.get("commit", "")
        return {"status": "ok", "latest": sha[:7], "latest_commit": sha,
                "available": bool(sha and known and sha != known)}
    except NKError as e:
        return {"status": "error", "error": str(e), "available": False}


def check_all_updates(cfg, ctx=None):
    ctx = ctx or NullCtx()
    reg = load_registry(cfg)
    n = 0
    items = list(reg["tools"].values())
    for i, t in enumerate(items):
        ctx.check()
        ctx.log("Checking %s" % t["name"])
        r = check_update(t, cfg)
        r["checked"] = now_iso()
        t["update_info"] = r
        n += 1 if r.get("available") else 0
        ctx.progress(int((i + 1) * 100 / max(1, len(items))))
    save_registry(cfg, reg)
    audit(cfg, "check-updates", updates=n)
    return n


def params_for_update(tool):
    info = tool.get("update_info") or {}
    tag = tool.get("ref_kind", "").startswith("Release")
    return InstallParams(source=tool["source"], src=tool["source_url"], name=tool["name"],
                         scope=tool["scope"], type=tool["type"],
                         ref=info.get("latest", "") if tag else tool.get("ref", ""),
                         ref_kind=tool.get("ref_kind", "Branch"),
                         requirements=tool.get("requirements", False),
                         registration="auto" if tool.get("registered", True) else "manual",
                         group=tool.get("group", ""))


# --------------------------------------------------------------------------
# profiles, packs
# --------------------------------------------------------------------------
def save_profile(cfg, name, ids=None):
    reg = load_registry(cfg)
    if ids is None:
        state = load_state(cfg)
        ids = [i for i in reg["tools"] if i not in state["disabled"] and i not in state["quarantined"]]
    reg["profiles"][name] = list(ids)
    save_registry(cfg, reg)
    audit(cfg, "profile-save", profile=name, tools=len(ids))


def apply_profile(cfg, name):
    reg = load_registry(cfg)
    if name not in reg["profiles"]:
        raise NKError("No profile '%s'." % name)
    keep = set(reg["profiles"][name])
    state = load_state(cfg)
    state["disabled"] = [i for i in reg["tools"] if i not in keep]
    state["quarantined"] = [i for i in state["quarantined"] if i in keep]
    save_state(cfg, state)
    audit(cfg, "profile-apply", profile=name)


def delete_profile(cfg, name):
    reg = load_registry(cfg)
    reg["profiles"].pop(name, None)
    save_registry(cfg, reg)
    audit(cfg, "profile-delete", profile=name)


def export_pack(cfg, path, name="Nuke Toolbox Pro pack"):
    reg = load_registry(cfg)
    tools, skipped = [], []
    for t in reg["tools"].values():
        v = active_version(t)
        if t["source"] == "Local" or not v:
            skipped.append(t["name"])
            continue
        e = {"name": t["name"], "source": t["source"], "src": t["source_url"], "ref": t.get("ref", ""),
             "ref_kind": t.get("ref_kind", "Branch"), "scope": t["scope"], "type": t["type"],
             "requirements": t.get("requirements", False)}
        if t["source"] == "Direct URL":
            e["sha256"] = v.get("sha256", "")
        tools.append(e)
    _write_json(path, {"pack": name, "created": now_iso(), "installer": VERSION, "tools": tools})
    audit(cfg, "export-pack", file=path, tools=len(tools))
    return skipped


def import_pack(cfg, path, ctx=None, review=None):
    ctx = ctx or NullCtx()
    data = _read_json(path, None)
    if not isinstance(data, dict) or not isinstance(data.get("tools"), list):
        raise NKError("Not a valid pack file.")
    done, failed = [], []
    n = len(data["tools"])
    for i, e in enumerate(data["tools"]):
        ctx.check()
        ctx.log("[%d/%d] %s" % (i + 1, n, e.get("name", "?")))
        try:
            p = InstallParams(**{k: e[k] for k in (
                "name", "source", "src", "ref", "ref_kind", "scope", "type", "requirements", "sha256") if k in e})
            done.append(install_from(p, cfg, ctx, review=review)["name"])
        except Cancelled:
            raise
        except Exception as ex:
            failed.append("%s: %s" % (e.get("name", "?"), ex))
            ctx.log("FAILED %s" % failed[-1])
        ctx.progress(int((i + 1) * 100 / max(1, n)))
    audit(cfg, "import-pack", file=path, ok=len(done), failed=len(failed))
    return {"installed": done, "failed": failed}


# --------------------------------------------------------------------------
# marketplace: search + studio catalog
# --------------------------------------------------------------------------
def _norm_entry(e):
    url = e.get("url", "")
    try:
        source = detect_source(url) if url else "Direct URL"
    except NKError:
        source = "Direct URL"
    return {"name": e.get("name") or repo_name(url), "description": e.get("description", "") or "",
            "url": url, "source": source, "ref": e.get("ref", ""), "version": e.get("version", ""),
            "type": e.get("type", "Auto-detect"), "sha256": e.get("sha256", ""),
            "tags": e.get("tags", []), "stars": e.get("stars", ""), "updated": e.get("updated", "")}


def load_catalog(cfg):
    loc = (cfg.get("catalog") or "").strip()
    if not loc:
        data = DEFAULT_CATALOG
    elif loc.lower().startswith("http"):
        data = _get_json(loc)
    else:
        try:
            with open(loc, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            raise NKError("Cannot read catalog %s: %s" % (loc, e))
    if isinstance(data, dict):
        data = data.get("tools", [])
    return [_norm_entry(e) for e in data if isinstance(e, dict)]


def search(kind, query, cfg):
    query = (query or "").strip()
    if kind == "GitHub":
        q = query if "nuke" in query.lower() else (query + " nuke").strip()
        data = _get_json("https://api.github.com/search/repositories?q=%s&sort=stars&order=desc&per_page=30"
                         % urllib.parse.quote(q or "nuke gizmo"))
        return [_norm_entry({"name": d["full_name"], "description": d.get("description"),
                             "url": d["html_url"], "stars": d.get("stargazers_count", 0),
                             "updated": (d.get("pushed_at") or "")[:10]}) for d in data.get("items", [])]
    if kind == "GitLab":
        data = _get_json("https://gitlab.com/api/v4/projects?search=%s&order_by=last_activity_at&per_page=30"
                         % urllib.parse.quote(query or "nuke"))
        return [_norm_entry({"name": d["path_with_namespace"], "description": d.get("description"),
                             "url": d["web_url"], "stars": d.get("star_count", 0),
                             "updated": (d.get("last_activity_at") or "")[:10]}) for d in data]
    ql = query.lower()
    return [e for e in load_catalog(cfg) if not ql or ql in e["name"].lower()
            or ql in e["description"].lower() or any(ql in t.lower() for t in e["tags"])]


# --------------------------------------------------------------------------
# Nukepedia: sign-in session, search, download, install / uninstall
# --------------------------------------------------------------------------
NUKEPEDIA_URL = "https://www.nukepedia.com"
NP_SECTIONS = ("tools", "gizmos", "python", "plugins", "toolsets", "scripts", "blink", "nuke-scripts")

import html.parser  # noqa: E402
import http.cookiejar  # noqa: E402

_NP = {"opener": None, "user": "", "cookie": "", "anon": None, "pw": ""}


class _NPParser(html.parser.HTMLParser):
    """Collects <a> links and <form> inputs from a page."""

    def __init__(self):
        html.parser.HTMLParser.__init__(self)
        self.links, self.forms = [], []
        self._a, self._form = None, None

    def handle_starttag(self, tag, attrs):
        a = dict((k, v or "") for k, v in attrs)
        if tag == "a" and a.get("href"):
            self._a = {"href": a["href"], "text": "", "title": a.get("title", "")}
        elif tag == "form":
            self._form = {"action": a.get("action", ""), "method": a.get("method", "get").lower(), "inputs": []}
            self.forms.append(self._form)
        elif tag == "input" and self._form is not None:
            self._form["inputs"].append(a)

    def handle_data(self, data):
        if self._a is not None:
            self._a["text"] += data + " "

    def handle_endtag(self, tag):
        if tag == "a" and self._a is not None:
            self._a["text"] = " ".join(self._a["text"].split())
            self.links.append(self._a)
            self._a = None
        elif tag == "form":
            self._form = None


def _np_parse(text):
    p = _NPParser()
    try:
        p.feed(text)
    except Exception:
        pass
    return p


def _np_open(url, data=None, timeout=45):
    op = _NP["opener"]
    if op is None:
        op = _NP["anon"] = _NP.get("anon") or urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    if url.startswith("/"):
        url = NUKEPEDIA_URL + url
    body = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
    hdr = {"User-Agent": "Mozilla/5.0 (NK_tools-installer/%s)" % VERSION, "Accept": "text/html,*/*"}
    if _NP.get("cookie"):
        hdr["Cookie"] = _NP["cookie"]
    req = urllib.request.Request(url, data=body, headers=hdr)
    last = None
    for _attempt in (1, 2):                              # one retry: Cloudflare sometimes stalls the first read
        try:
            return op.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            raise NKError("Nukepedia HTTP %s for %s" % (e.code, url))
        except (socket.timeout, TimeoutError) as e:
            last = "timed out"
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), (socket.timeout, TimeoutError)):
                last = "timed out"
            else:
                raise NKError("Nukepedia network error: %s" % e.reason)
        except OSError as e:
            raise NKError("Nukepedia network error: %s" % e)
    raise NKError("Nukepedia %s (%s)" % (last, url))


def _np_text(url, data=None):
    with _np_open(url, data) as r:
        try:
            return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
        except (socket.timeout, TimeoutError, OSError) as e:
            raise NKError("Nukepedia read timed out (%s)" % url)


def _np_signed_in_page(text):
    low = text.lower()
    return ("task=user.logout" in low or "/logout" in low or "log out" in low or "sign out" in low) \
        and 'type="password"' not in low


def np_credentials():
    """(user, password) of the current in-memory session, or ("", "")."""
    return (_NP["user"], _NP["pw"]) if _NP["pw"] else ("", "")


def np_cookies():
    """Session cookies as [(name, value)] - from the login jar or a pasted browser cookie."""
    out = []
    op = _NP["opener"]
    if op is not None:
        for h in op.handlers:
            jar = getattr(h, "cookiejar", None)
            if jar is not None:
                out += [(c.name, c.value) for c in jar if "nukepedia" in (c.domain or "")]
    if _NP.get("cookie"):
        for part in _NP["cookie"].split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                out.append((k, v))
    return out


def np_logged_in():
    return _NP["opener"] is not None and bool(_NP["user"])


def np_user():
    return _NP["user"]


def np_logout():
    _NP["opener"], _NP["user"], _NP["cookie"], _NP["pw"] = None, "", "", ""


NP_LOGIN_URLS = ["/", "/tools/", "/login", "/login/", "/index.php?option=com_users&view=login", "/user/login",
                 "/account/login", "/accounts/login/", "/wp-login.php", "/signin"]


def _np_find_login_form(text):
    """Any form that has a password input; username = first text/email input before it."""
    for f in _np_parse(text).forms:
        ins = f["inputs"]
        pw = [i for i in ins if i.get("type", "").lower() == "password" and i.get("name")]
        if not pw:
            continue
        user = None
        for i in ins:
            if i is pw[0]:
                break
            if i.get("name") and i.get("type", "text").lower() in ("text", "email", ""):
                user = i
        if user:
            return f, user["name"], pw[0]["name"]
    return None


def _np_debug(cfg, lines, pages):
    try:
        d = P(cfg, "nukepedia_debug")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "log.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        for n, t in enumerate(pages[:3]):
            with open(os.path.join(d, "page%d.html" % n), "w", encoding="utf-8") as f:
                f.write(t)
        return d
    except Exception:
        return ""


def np_login(user, password, cfg=None):
    """Sign in to nukepedia.com (generic form login). Password is kept in memory only."""
    cfg = cfg or load_config()
    user, password = (user or "").strip(), password or ""
    if not user or not password:
        raise NKError("Enter your Nukepedia username and password.")
    _NP["opener"] = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    _NP["cookie"] = ""
    found, log, pages = None, [], []
    for path in NP_LOGIN_URLS:
        try:
            text = _np_text(path)
        except NKError as e:
            log.append("%s -> %s" % (path, e))
            continue
        pages.append(text)
        hit = _np_find_login_form(text)
        log.append("%s -> %d bytes, login form: %s%s" % (
            path, len(text), "yes" if hit else "no",
            " (Cloudflare/JS challenge?)" if re.search(r"just a moment|cf-chl|turnstile|challenges\.cloudflare|enable javascript", text, re.I) else ""))
        if hit:
            found = (path,) + hit
            break
    if not found:
        np_logout()
        d = _np_debug(cfg, log, pages)
        raise NKError("Could not find the Nukepedia login form.\n%s\n\nDebug saved to: %s\n"
                      "Fallback: log in with your browser, then use 'Paste cookie'."
                      % ("\n".join(log[-4:]), d or "(not saved)"))
    path, form, uname, pname = found
    fields = {}
    for i in form["inputs"]:
        n = i.get("name", "")
        t = i.get("type", "").lower()
        if not n or t in ("submit", "button", "image", "checkbox", "radio", "file"):
            continue
        fields[n] = i.get("value", "")
    for i in form["inputs"]:
        if i.get("name") in ("remember", "rememberme") and i.get("type", "").lower() == "checkbox":
            fields[i["name"]] = i.get("value") or "yes"
    fields[uname], fields[pname] = user, password
    base = NUKEPEDIA_URL + (path if path.startswith("/") else "/" + path)
    action = urllib.parse.urljoin(base, form["action"] or "")
    try:
        text = _np_text(action, fields)
    except NKError:
        np_logout()
        raise
    ok = not _np_find_login_form(text) or _np_signed_in_page(text)
    if not ok:
        np_logout()
        _np_debug(cfg, log + ["POST %s -> still shows login form" % action], pages + [text])
        raise NKError("Nukepedia login failed - check username / password.")
    _NP["user"], _NP["pw"] = user, password
    return user


def np_login_cookie(cookie, cfg=None):
    """Fallback: use the Cookie header copied from a browser session that is logged in."""
    cookie = (cookie or "").strip()
    if cookie.lower().startswith("cookie:"):
        cookie = cookie[7:].strip()
    if not cookie:
        raise NKError("Paste the cookie string first.")
    _NP["opener"] = urllib.request.build_opener()
    _NP["cookie"] = cookie
    try:
        text = _np_text("/")
    except NKError:
        np_logout()
        raise
    if _np_find_login_form(text) and not _np_signed_in_page(text):
        np_logout()
        raise NKError("That cookie is not a signed-in Nukepedia session.")
    _NP["user"] = "browser session"
    return _NP["user"]


# ---- categories, listings, deep index -------------------------------------------------
NP_DEFAULT_CATEGORIES = [("Gizmos", "gizmos", 1368), ("Blink", "blink", 89), ("Python", "python", 724),
                         ("Plugins", "plugins", 134), ("Toolsets", "toolsets", 169), ("Presets", "presets", 8),
                         ("Miscellaneous", "miscellaneous", 53), ("Hiero", "hiero", 38),
                         ("Tcl Scripts", "tcl-scripts", 3), ("Das Element", "das-element", 4)]
_TOOL_TAIL = re.compile(r"(?:Rated\s+([\d.]+)\s+\d+\s+ratings?|No ratings yet(?:\s+No ratings yet)?)\s+"
                        r"([\d,]+)\s+downloads?\s+Updated\s+(.+?)\s*$")


def _np_path(url):
    return [x for x in urllib.parse.urlparse(url).path.split("/") if x]


def np_parse_listing(text, page_url):
    """-> (subcategories [(name, url, count)], tools [entry]) from a Nukepedia category page."""
    here = _np_path(page_url)
    subs, tools, seen = [], [], set()
    for a in _np_parse(text).links:
        url = urllib.parse.urljoin(page_url, a["href"].split("#")[0].split("?")[0])
        if not urllib.parse.urlparse(url).netloc.endswith("nukepedia.com") or url in seen:
            continue
        t = " ".join(a["text"].split())
        path = _np_path(url)
        if not path or path[0] != "tools":
            continue
        m = re.match(r"^(.*?)\s+Contributed by\s+(.*)$", t)
        if m:
            rest, rating, dl, upd = m.group(2), "", 0, ""
            tm = _TOOL_TAIL.search(rest)
            if tm:
                rating, dl, upd = tm.group(1) or "", int(tm.group(2).replace(",", "")), tm.group(3)
                rest = rest[:tm.start()].strip()
            seen.add(url)
            tools.append({"name": m.group(1).strip(), "url": url, "description": rest,
                          "category": "/".join(path[1:-1]), "downloads": dl, "rating": rating,
                          "updated": upd, "source": "Nukepedia"})
            continue
        cm = re.match(r"^(.*\S)\s+(\d[\d,]*)$", t)
        if cm and path[:len(here)] == here and len(path) == len(here) + 1:
            seen.add(url)
            subs.append((cm.group(1), url, int(cm.group(2).replace(",", ""))))
    return subs, tools


def np_categories():
    """Top-level download categories with counts (falls back to the built-in list offline)."""
    try:
        subs, _ = np_parse_listing(_np_text("/tools/"), NUKEPEDIA_URL + "/tools/")
        out = [(n, _np_path(u)[1], c) for n, u, c in subs]
        if out:
            return out
    except NKError:
        pass
    return list(NP_DEFAULT_CATEGORIES)


def np_crawl(slug, ctx=None, depth=0):
    """Every tool in a category, following sub-categories."""
    ctx = ctx or NullCtx()
    ctx.check()
    url = "%s/tools/%s/" % (NUKEPEDIA_URL, slug.strip("/"))
    ctx.log("Reading %s" % url)
    subs, tools = np_parse_listing(_np_text(url), url)
    if depth < 3:
        for _n, u, _c in subs:
            tools += np_crawl("/".join(_np_path(u)[1:]), ctx, depth + 1)
    seen, out = set(), []
    for t in tools:
        if t["url"] not in seen:
            seen.add(t["url"])
            out.append(t)
    return out


def _np_index_path(cfg):
    return P(cfg, "cache", "nukepedia_index.json")


def np_index(cfg, ctx=None, slugs=None, force=False, max_age_h=12):
    """Cached tool index {slug: {time, tools}}; crawls only stale / missing categories."""
    ctx = ctx or NullCtx()
    idx = _read_json(_np_index_path(cfg), {})
    if not isinstance(idx, dict):
        idx = {}
    cats = np_categories()
    wanted = [c[1] for c in cats if not slugs or c[1] in slugs]
    now = datetime.datetime.now().timestamp()
    for n, slug in enumerate(wanted):
        ctx.check()
        ctx.progress(int(100 * n / max(1, len(wanted))))
        e = idx.get(slug)
        if not force and e and now - e.get("time", 0) < max_age_h * 3600:
            continue
        try:
            idx[slug] = {"time": now, "tools": np_crawl(slug, ctx)}
        except Cancelled:
            raise
        except NKError as ex:
            ctx.log("Skipped %s: %s" % (slug, ex))
    try:
        os.makedirs(os.path.dirname(_np_index_path(cfg)), exist_ok=True)
        _write_json(_np_index_path(cfg), idx)
    except Exception:
        pass
    return [t for slug in wanted for t in idx.get(slug, {}).get("tools", [])]


def np_rank(tools, query):
    """Deep ranking: all words must match name/description/category; name hits weigh most."""
    words = [w for w in re.split(r"[\s,;]+", (query or "").lower()) if w]
    if not words:
        return sorted(tools, key=lambda t: -t.get("downloads", 0))
    import math

    def score(t, need_all):
        name = t["name"].lower()
        flat = re.sub(r"[_\-.]+", " ", name)
        hay = " ".join((name, flat, t.get("description", "").lower(), t.get("category", "").lower()))
        hits = [w for w in words if w in hay]
        if need_all and len(hits) < len(words):
            return 0
        if not hits:
            return 0
        sc = 10.0 * len(hits)
        for w in words:
            if name == w:
                sc += 100
            elif name.startswith(w):
                sc += 50
            elif w in name or w in flat:
                sc += 30
            if w in t.get("category", "").lower():
                sc += 8
            if w in t.get("description", "").lower():
                sc += 5
        return sc + math.log10(t.get("downloads", 0) + 1)

    for need_all in (True, False):
        res = [(score(t, need_all), t) for t in tools]
        res = [x for x in res if x[0] > 0]
        if res:
            return [t for _s, t in sorted(res, key=lambda x: -x[0])]
    return []


def np_site_search(query):
    """Nukepedia's own /search/?q= results (tools only)."""
    q = urllib.parse.quote((query or "").strip())
    url = "%s/search/?q=%s" % (NUKEPEDIA_URL, q)
    return np_parse_listing(_np_text(url), url)[1]


def np_search(cfg, query, ctx=None, slugs=None, deep=True):
    """Deep search: cached full index of every category + the site's own search, merged and ranked."""
    ctx = ctx or NullCtx()
    found = np_rank(np_index(cfg, ctx, slugs), query) if deep else []
    have = {t["url"] for t in found}
    if (query or "").strip():
        try:
            for t in np_site_search(query):
                if t["url"] not in have:
                    found.append(t)
        except NKError:
            pass
    return found


def np_browse(cfg, slug, ctx=None, sort="downloads"):
    tools = np_index(cfg, ctx, [slug])
    key = {"downloads": lambda t: -t.get("downloads", 0), "name": lambda t: t["name"].lower()}.get(sort)
    return sorted(tools, key=key) if key else tools


NP_DL_EXTS = (".zip", ".gizmo", ".py", ".nk", ".tcl", ".dll", ".so", ".dylib")
NP_PARTIAL = (".crdownload", ".part", ".tmp", ".download", ".opdownload")


def np_download_dirs(cfg=None):
    cfg = cfg or {}
    dirs = [cfg.get("download_dir", ""), os.path.join(os.path.expanduser("~"), "Downloads"),
            os.path.join(os.environ.get("USERPROFILE", ""), "Downloads") if os.environ.get("USERPROFILE") else ""]
    out = []
    for d in dirs:
        if d and os.path.isdir(d) and d not in out:
            out.append(d)
    return out


def np_new_download(dirs, since, ignore=()):
    """Newest finished tool file in the browser download folders created after `since`
    (epoch seconds); None if nothing yet. A file counts once its size stops changing."""
    best, bt = None, 0
    for d in dirs:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            low = n.lower()
            if low.endswith(NP_PARTIAL) or not low.endswith(NP_DL_EXTS):
                continue
            p = os.path.join(d, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if st.st_mtime >= since and st.st_size > 0 and p not in ignore and st.st_mtime > bt:
                best, bt = p, st.st_mtime
    return best


class NPManual(NKError):
    """Automatic download was not possible - the page must be used in a browser."""

    def __init__(self, msg, entry):
        NKError.__init__(self, msg)
        self.entry = entry


def np_find_download(page_url, text):
    p = _np_parse(text)
    for f in p.forms:
        blob = (f.get("action", "") + " " + " ".join(i.get("value", "") + i.get("name", "") for i in f["inputs"])).lower()
        if "download" in blob and not any(i.get("type", "").lower() == "password" for i in f["inputs"]):
            return ("form", f)
    best = ""
    for a in p.links:
        hay = (a["href"] + " " + a["text"] + " " + a["title"]).lower()
        if a["href"].lower().split("?")[0].endswith(".zip") or "download" in hay and "/tools/" not in a["href"]:
            best = a["href"]
            if a["href"].lower().split("?")[0].endswith(".zip"):
                break
    return ("link", urllib.parse.urljoin(page_url, best)) if best else None


def np_download(entry, cfg, ctx=None):
    """Download the tool zip with the signed-in session; raises NPManual if the site needs a browser step."""
    ctx = ctx or NullCtx()
    if not np_logged_in():
        raise NKError("Sign in to Nukepedia first (downloads need an account).")
    ctx.log("Opening %s" % entry["url"])
    try:
        text = _np_text(entry["url"])
    except NKError as e:
        raise NPManual("%s - using the browser instead." % e, entry)
    hit = np_find_download(entry["url"], text)
    d = P(cfg, "cache", "nukepedia")
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, safe_name(clean_name(entry["name"])) + ".zip")
    if not hit:
        raise NPManual("No download link found on the page.", entry)
    try:
        if hit[0] == "form":
            f = hit[1]
            fields = dict((i["name"], i.get("value", "")) for i in f["inputs"]
                          if i.get("name") and i.get("type", "").lower() not in ("submit", "button", "image", "file"))
            for i in f["inputs"]:
                if i.get("type", "").lower() == "submit" and i.get("name"):
                    fields[i["name"]] = i.get("value", "")
            r = _np_open(urllib.parse.urljoin(entry["url"], f["action"] or entry["url"]), fields, timeout=90)
        else:
            r = _np_open(hit[1], timeout=90)
        with r, open(dest, "wb") as fh:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                ctx.check()
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if total:
                    ctx.progress(int(done * 55 / total))
    except Cancelled:
        raise
    except NKError as e:
        raise NPManual(str(e), entry)
    except (socket.timeout, TimeoutError, OSError) as e:
        raise NPManual("Download timed out (%s)" % e, entry)
    if not zipfile.is_zipfile(dest):
        try:
            with open(dest, "rb") as fh:
                head = fh.read(4)
            if head[:2] != b"PK":
                # single-file tools (.gizmo / .py / .nk): wrap into a zip so the normal installer handles them
                with open(dest, "rb") as fh:
                    raw = fh.read()
                if raw[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
                    _np_debug(cfg, ["download of %s returned a web page" % entry["url"]],
                              [raw.decode("utf-8", "replace")])
                    raise NPManual("The site returned a web page (verification step) instead of a file.", entry)
                fname = safe_name(clean_name(entry["name"]))
                ext = ".gizmo" if b"Gizmo" in raw[:4000] or b"Group {" in raw[:4000] else ".py" if b"import" in raw[:4000] else ".nk"
                with zipfile.ZipFile(dest, "w") as z:
                    z.writestr(fname + ext, raw)
        except NPManual:
            raise
        except Exception:
            raise NPManual("Could not read the downloaded file.", entry)
    return dest


NP_GROUP = "Nukepedia_tools"


def np_group(entry):
    """Nukepedia_tools/<category>[/<subcategory>] e.g. Nukepedia_tools/gizmos/keyer"""
    cat = [x for x in re.split(r"[\\/]+", (entry or {}).get("category", "") or "") if x]
    return "/".join([NP_GROUP] + cat)


def np_prepare(entry, cfg=None, ctx=None, scope="Global", registration="auto"):
    cfg = cfg or load_config()
    ctx = ctx or NullCtx()
    zpath = np_download(entry, cfg, ctx)
    return prepare(InstallParams(source="Local zip / folder", src=zpath,
                                 name=clean_name(entry["name"]), scope=scope,
                                 registration=registration, group=np_group(entry)), cfg, ctx)


def np_installed(cfg, entry):
    """Registry tool matching a Nukepedia entry by name, or None."""
    want = clean_name(entry["name"]).lower()
    for t in load_registry(cfg)["tools"].values():
        if t["name"].lower() == want:
            return t
    return None


def np_uninstall(cfg, entry, via="Nukepedia panel"):
    t = np_installed(cfg, entry)
    if not t:
        raise NKError("'%s' is not installed." % entry["name"])
    uninstall(cfg, t["id"], via=via)
    return t["name"]


# --------------------------------------------------------------------------
# self update, deployment helpers
# --------------------------------------------------------------------------
PACKAGE_FILES = ["nk_core.py", "nk_ui.py", "nk_editor.py", "nk_tools_installer.py", "menu.py", "README.md"]


def package_dir():
    return os.path.dirname(os.path.abspath(__file__))


def check_self_update(cfg, ctx=None):
    ctx = ctx or NullCtx()
    url = (cfg.get("self_update_url") or "").strip()
    if not url:
        raise NKError("Set 'Installer update URL' in Settings (GitHub/GitLab repo or .zip URL).")
    source = detect_source(url)
    tmp = tempfile.mkdtemp(prefix="nkself_")
    try:
        zpath = os.path.join(tmp, "u.zip")
        fetch_zip(to_archive_url(source, url), zpath, cfg, ctx)
        if not zipfile.is_zipfile(zpath):
            raise NKError("Update URL did not return a zip.")
        ex = os.path.join(tmp, "x")
        safe_extract(zpath, ex)
        src = None
        for dp, _, files in os.walk(ex):
            if "nk_core.py" in files:
                src = dp
                break
        if not src:
            raise NKError("nk_core.py not found in the downloaded archive.")
        m = re.search(r'^VERSION\s*=\s*"([^"]+)"', _read_text(os.path.join(src, "nk_core.py")), re.M)
        latest = m.group(1) if m else "?"
        return {"current": VERSION, "latest": latest, "newer": ver_key(latest) > ver_key(VERSION),
                "tmp": tmp, "src": src}
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def apply_self_update(cfg, info):
    try:
        pkg = package_dir()
        bdir = P(cfg, "backups")
        os.makedirs(bdir, exist_ok=True)
        z = os.path.join(bdir, "installer_%s_%s" % (VERSION, datetime.datetime.now().strftime("%Y%m%d-%H%M%S")))
        shutil.make_archive(z, "zip", pkg)
        for f in PACKAGE_FILES:
            s = os.path.join(info["src"], f)
            if os.path.isfile(s):
                shutil.copyfile(s, os.path.join(pkg, f))
        audit(cfg, "self-update", old=VERSION, new=info["latest"])
    finally:
        shutil.rmtree(info["tmp"], ignore_errors=True)


def env_paths(cfg, scopes=None):
    reg, state, out = load_registry(cfg), load_state(cfg), []
    for t in reg["tools"].values():
        v = active_version(t)
        if not v or (scopes and t["scope"] not in scopes) or tool_status(cfg, t, state) != "Enabled":
            continue
        out += v["plugin_dirs"]
    return out


def env_snippet(cfg, scopes=None):
    dirs = env_paths(cfg, scopes)
    if sys.platform.startswith("win"):
        return "set NUKE_PATH=" + os.pathsep.join(dirs) + os.pathsep + "%NUKE_PATH%"
    return 'export NUKE_PATH="%s:$NUKE_PATH"' % ":".join(dirs)


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------
def _ask(text):
    print(text)
    return input("\nInstall? [y/N] ").strip().lower() in ("y", "yes")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nk_tools_installer",
                                 description="Nuke Toolbox Pro - install and manage Nuke tools (no args = GUI).")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("install", help="install from zip/folder/GitHub/GitLab/URL")
    s.add_argument("src")
    s.add_argument("--name", default="")
    s.add_argument("--version", default="")
    s.add_argument("--ref", default="")
    s.add_argument("--kind", choices=["branch", "tag"], default="branch")
    s.add_argument("--scope", choices=sorted(SCOPE_ALIASES), default="global")
    s.add_argument("--type", default="Auto-detect", choices=TOOL_TYPES)
    s.add_argument("--sha256", default="")
    s.add_argument("--requirements", action="store_true")
    s.add_argument("--manual", action="store_true", help="do not write init.py/menu.py; print the code instead")
    s.add_argument("--force", action="store_true")
    s.add_argument("--yes", action="store_true", help="no review prompt")
    s.add_argument("--dry-run", action="store_true")
    sub.add_parser("list")
    for c in ("uninstall", "enable", "disable"):
        sub.add_parser(c).add_argument("tool")
    u = sub.add_parser("update")
    u.add_argument("tool", nargs="?")
    u.add_argument("--all", action="store_true")
    u.add_argument("--yes", action="store_true")
    sub.add_parser("check-updates")
    r = sub.add_parser("rollback")
    r.add_argument("tool")
    r.add_argument("version")
    sub.add_parser("export-pack").add_argument("file")
    ip = sub.add_parser("import-pack")
    ip.add_argument("file")
    ip.add_argument("--yes", action="store_true")
    e = sub.add_parser("env")
    e.add_argument("--scope", choices=sorted(SCOPE_ALIASES), action="append")
    sub.add_parser("audit")
    sub.add_parser("self-update").add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 0
    cfg, ctx = load_config(), PrintCtx()
    try:
        if a.cmd == "install":
            p = InstallParams(src=a.src, name=a.name, version=a.version, ref=a.ref,
                              ref_kind="Release (tag)" if a.kind == "tag" else "Branch",
                              scope=SCOPE_ALIASES[a.scope], type=a.type, sha256=a.sha256,
                              requirements=a.requirements, force=a.force,
                              registration="manual" if a.manual else "auto")
            res = install_from(p, cfg, ctx, review=None if a.yes or a.dry_run else (lambda st: _ask(plan_text(st))),
                               dry_run=a.dry_run)
            print(res["plan"] if res.get("dry_run") else "Installed %s v%s -> %s\nRestart Nuke to load it." % (
                res["name"], res["version"], res["path"]))
        elif a.cmd == "list":
            reg, state = load_registry(cfg), load_state(cfg)
            for t in reg["tools"].values():
                ui = t.get("update_info", {})
                print("%-28s %-14s %-12s %-10s %s%s" % (
                    t["id"], t.get("active_version", ""), t["scope"], tool_status(cfg, t, state), t["type"],
                    "  [update: %s]" % ui["latest"] if ui.get("available") else ""))
            if not reg["tools"]:
                print("(nothing installed)")
        elif a.cmd == "uninstall":
            uninstall(cfg, a.tool)
            print("Uninstalled.")
        elif a.cmd in ("enable", "disable"):
            set_enabled(cfg, find_tool(load_registry(cfg), a.tool)["id"], a.cmd == "enable")
            print("%sd. Restart Nuke." % a.cmd.capitalize())
        elif a.cmd == "check-updates":
            print("%d update(s) available." % check_all_updates(cfg, ctx))
        elif a.cmd == "update":
            reg = load_registry(cfg)
            tools = list(reg["tools"].values()) if a.all else [find_tool(reg, a.tool)]
            for t in tools:
                t["update_info"] = check_update(t, cfg)
                if t["update_info"].get("available"):
                    res = install_from(params_for_update(t), cfg, ctx,
                                       review=None if a.yes else (lambda st: _ask(plan_text(st))))
                    print("Updated %s -> %s" % (res["name"], res["version"]))
                else:
                    print("%s: up to date" % t["name"])
        elif a.cmd == "rollback":
            rollback(cfg, a.tool, a.version)
            print("Rolled back. Restart Nuke.")
        elif a.cmd == "export-pack":
            sk = export_pack(cfg, a.file)
            print("Exported." + ("  Skipped (local installs): " + ", ".join(sk) if sk else ""))
        elif a.cmd == "import-pack":
            res = import_pack(cfg, a.file, ctx, review=None if a.yes else (lambda st: _ask(plan_text(st))))
            print("Installed: %s\nFailed: %s" % (res["installed"], res["failed"]))
            return 1 if res["failed"] else 0
        elif a.cmd == "env":
            print(env_snippet(cfg, [SCOPE_ALIASES[x] for x in a.scope] if a.scope else None))
        elif a.cmd == "audit":
            for r_ in read_audit(cfg, 50):
                print(json.dumps(r_))
        elif a.cmd == "self-update":
            info = check_self_update(cfg, ctx)
            print("Installed %s, available %s" % (info["current"], info["latest"]))
            if a.apply and info["newer"]:
                apply_self_update(cfg, info)
                print("Updated. Restart Nuke.")
            else:
                shutil.rmtree(info["tmp"], ignore_errors=True)
        return 0
    except Cancelled:
        print("Cancelled.")
        return 1
    except NKError as ex:
        print("ERROR: %s" % ex)
        return 1


if __name__ == "__main__":
    sys.exit(main())
