# Nuke Toolbox Pro - menu. Loaded automatically once this folder is on the plugin path:
#   nuke.pluginAddPath("/path/to/Nuke_Toolbox_Pro")      (put that line in ~/.nuke/init.py)
import nuke

try:
    import nk_tools_installer
    _m = nuke.menu("Nuke").addMenu("Nuke Toolbox Pro")
    _m.addCommand("Open Toolbox...", "import nk_tools_installer; nk_tools_installer.show()")
    _m.addCommand("Check for Updates",
                  "import nk_tools_installer; nk_tools_installer.check_updates_in_nuke()")
    nk_tools_installer.startup_update_check()
except Exception as _e:
    nuke.tprint("Nuke Toolbox Pro menu failed: %s" % _e)
