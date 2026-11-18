# -*- coding: utf-8 -*-
"""
Nuke Toolbox Pro - entry point.

  GUI (inside Nuke) : import nk_tools_installer; nk_tools_installer.show()
  GUI (standalone)  : python nk_tools_installer.py
  Command line      : python nk_tools_installer.py install <zip|folder|url> --scope global --yes
                      python nk_tools_installer.py --help
"""
import os
import sys
import threading

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import nk_core  # noqa: E402

VERSION = nk_core.VERSION


def show():
    import nk_ui
    return nk_ui.show()


def check_updates_in_nuke(silent=False):
    """Background update check; reports through a Nuke message / console."""
    import nuke

    def work():
        try:
            cfg = nk_core.load_config()
            n = nk_core.check_all_updates(cfg)
            msg = ("Nuke Toolbox Pro: %d tool update(s) available - open Nuke Toolbox Pro > Open Toolbox > Installed."
                   % n) if n else "Nuke Toolbox Pro: all tools are up to date."
        except Exception as e:  # noqa
            msg = "Nuke Toolbox Pro: update check failed: %s" % e
        nuke.executeInMainThread(nuke.tprint, (msg,))
        if not silent or "available" in msg:
            nuke.executeInMainThread(nuke.message, (msg,))

    threading.Thread(target=work, daemon=True).start()


def startup_update_check():
    if nk_core.load_config().get("check_updates_on_start"):
        check_updates_in_nuke(silent=True)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(nk_core.main())
    show()
