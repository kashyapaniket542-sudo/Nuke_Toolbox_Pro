# -*- coding: utf-8 -*-
"""UI integration test. Needs PySide2 or PySide6.  Run: python tests/test_ui.py"""
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

try:
    from PySide2 import QtWidgets, QtCore, QtGui
except ImportError:
    from PySide6 import QtWidgets, QtCore, QtGui

import nk_core as core  # noqa: E402
import nk_ui  # noqa: E402
from test_core import make_tool, zip_folder  # noqa: E402

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def pump(win, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        APP.processEvents()
        if not win._threads:
            APP.processEvents()
            return
        time.sleep(0.01)
    raise AssertionError("worker threads did not finish")


class TestUI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nkui_")
        self.home = os.path.join(self.tmp, "dot_nuke")
        os.makedirs(self.home)
        os.environ.update(NK_HOME_NUKE=self.home, NK_NUKE_VERSION="15.1")
        os.environ.pop("NK_ROLE", None)
        self.src = os.path.join(self.tmp, "src")
        os.makedirs(self.src)
        cfg = core.load_config()
        cfg["role"] = "admin"
        self.shown = []
        self.dialog_result = 1
        self.boxes = []
        self._patch()
        self.win = nk_ui.InstallerWindow(cfg)

    def _patch(self):
        QMB = QtWidgets.QMessageBox
        self._orig = (QMB.information, QMB.warning, QMB.critical, QMB.question, nk_ui.run_dialog,
                      QtWidgets.QInputDialog.getItem, QtWidgets.QInputDialog.getText)
        QMB.information = staticmethod(lambda p, t, m, *a: self.boxes.append(("info", t, m)))
        QMB.warning = staticmethod(lambda p, t, m, *a: self.boxes.append(("warn", t, m)))
        QMB.critical = staticmethod(lambda p, t, m, *a: self.boxes.append(("crit", t, m)))
        QMB.question = staticmethod(lambda *a: QMB.Yes)
        nk_ui.run_dialog = lambda d: (self.shown.append(d), self.dialog_result)[1]

    def tearDown(self):
        QMB = QtWidgets.QMessageBox
        (QMB.information, QMB.warning, QMB.critical, QMB.question, nk_ui.run_dialog,
         QtWidgets.QInputDialog.getItem, QtWidgets.QInputDialog.getText) = self._orig
        self.win.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def install_via_ui(self, folder, version="1.0", review=False):
        w = self.win
        w.review_chk.setChecked(review)
        w.src_path.setText(folder)
        w.version.setText(version)
        w.name.setText("")
        w.install_btn.click()
        pump(w)

    def test_install_installed_toggle_rollback_uninstall(self):
        w = self.win
        d = make_tool(self.src, "UiTool", gizmos=("UiGizmo",))
        self.install_via_ui(d, "1.0")
        self.assertEqual(self.boxes[-1][1], "Install complete", self.boxes)
        reg = core.load_registry(w.cfg)
        self.assertIn("UiTool.global", reg["tools"])
        self.assertEqual(w.inst_table.rowCount(), 1)
        self.assertEqual(w.inst_table.item(0, 0).text(), "UiTool")
        self.assertEqual(w.inst_table.item(0, 4).text(), "Enabled")
        # second version + rollback
        self.install_via_ui(d, "2.0")
        w.inst_table.selectRow(0)
        QtWidgets.QInputDialog.getItem = staticmethod(lambda *a, **k: ("1.0", True))
        w.b_roll.click()
        self.assertEqual(core.load_registry(w.cfg)["tools"]["UiTool.global"]["active_version"], "1.0")
        # disable
        w.inst_table.selectRow(0)
        w.b_toggle.click()
        self.assertEqual(w.inst_table.item(0, 4).text(), "Disabled")
        w.b_toggle.click()
        self.assertEqual(w.inst_table.item(0, 4).text(), "Enabled")
        # safety tab shows audit + backups
        w.refresh_safety()
        actions = [w.audit_table.item(r, 2).text() for r in range(w.audit_table.rowCount())]
        self.assertIn("install", actions)
        self.assertIn("rollback", actions)
        self.assertGreater(w.bk_table.rowCount(), 0)
        # uninstall
        w.inst_table.selectRow(0)
        w.b_un.click()
        self.assertEqual(w.inst_table.rowCount(), 0)
        self.assertEqual(core.load_registry(w.cfg)["tools"], {})

    def test_review_dialog_shown_and_cancel_installs_nothing(self):
        d = make_tool(self.src, "Rv", menu_py=True)
        self.dialog_result = 0
        self.install_via_ui(d, "1", review=True)
        self.assertTrue(any(isinstance(x, nk_ui.TextDialog) for x in self.shown))
        self.assertIn("Startup scripts", self.shown[-1].view.toPlainText())
        self.assertEqual(core.load_registry(self.win.cfg)["tools"], {})
        self.dialog_result = 1
        self.install_via_ui(d, "1", review=True)
        self.assertIn("Rv.global", core.load_registry(self.win.cfg)["tools"])

    def test_dry_run(self):
        d = make_tool(self.src, "Dry")
        self.win.dry_chk.setChecked(True)
        self.install_via_ui(d, "1")
        self.assertIn("Plugin paths", self.shown[-1].view.toPlainText())
        self.assertEqual(core.load_registry(self.win.cfg)["tools"], {})

    def test_error_shows_message_and_ui_recovers(self):
        self.install_via_ui(os.path.join(self.tmp, "does_not_exist.zip"))
        self.assertEqual(self.boxes[-1][0], "crit")
        self.assertTrue(self.win.install_btn.isEnabled())

    def test_blocking_error_requires_confirmation(self):
        d = os.path.join(self.src, "empty")
        os.makedirs(d)
        open(os.path.join(d, "a.txt"), "w").close()
        self.install_via_ui(d, "1", review=False)
        self.assertIn("No Nuke files", self.shown[-1].view.toPlainText())
        self.assertIn("empty.global", core.load_registry(self.win.cfg)["tools"])   # user confirmed 'anyway'

    def test_browse_catalog_use_in_install(self):
        w = self.win
        w.search_src.setCurrentText("Studio catalog")
        w.search_q.setText("luma")
        w.search_btn.click()
        pump(w)
        self.assertEqual(w.res_table.rowCount(), 1)
        w.res_table.selectRow(0)
        w.use_btn.click()
        self.assertIn("LumaNukeGizmos", w.src_path.text())
        self.assertEqual(w.name.text(), "LumaNukeGizmos")
        self.assertEqual(w.tabs.currentIndex(), 0)

    def test_profiles_and_pack(self):
        w = self.win
        self.install_via_ui(make_tool(self.src, "A"), "1")
        self.install_via_ui(make_tool(self.src, "B", gizmos=("Bg",)), "1")
        QtWidgets.QInputDialog.getText = staticmethod(lambda *a, **k: ("show1", True))
        w._prof_save()
        self.assertEqual(w.prof_list.count(), 1)
        w.prof_list.setCurrentRow(0)
        core.set_enabled(w.cfg, "B.global", False)
        w._prof_apply()
        self.assertEqual(core.load_state(w.cfg)["disabled"], [])      # profile had both enabled
        w._prof_delete()
        self.assertEqual(w.prof_list.count(), 0)

    def test_settings_role_limits_scopes(self):
        w = self.win
        w.s_role.setCurrentText("artist")
        w._save_settings()
        model = w.scope.model()
        flags = [model.item(i).isEnabled() for i in range(model.rowCount())]
        self.assertEqual(flags, [True, True, False, False])
        w.s_role.setCurrentText("admin")
        w._save_settings()
        self.assertTrue(all(model.item(i).isEnabled() for i in range(4)))
        self.assertEqual(core.load_config()["role"], "admin")

    def test_drop_and_name_guess_and_ref_row(self):
        w = self.win
        z = zip_folder(make_tool(self.src, "Dropped-1.2"), os.path.join(self.tmp, "Dropped-1.2.zip"))
        w._set_source_path(z)
        self.assertEqual(w.name.text(), "Dropped")
        self.assertFalse(w.ref_row.isVisibleTo(w))
        w.src_path.setText("https://github.com/a/b")
        self.assertTrue(w.ref_row.isVisibleTo(w))

    def test_splash_and_settings_dialog(self):
        sp = nk_ui.make_splash(core.load_config())
        self.assertFalse(sp.pixmap().isNull())
        dlg = nk_ui.SplashSettings(core.load_config())
        dlg.title.setText("My Studio")
        self.assertEqual(dlg.result_config()["splash_title"], "My Studio")

    def test_env_snippet_dialog_and_update_check_offline_safe(self):
        self.install_via_ui(make_tool(self.src, "E"), "1")
        self.win._show_env()
        self.assertIn("NUKE_PATH", self.shown[-1].view.toPlainText())
        self.win.b_check.click()                    # local tool: nothing to check, must not crash
        pump(self.win)
        self.assertEqual(self.boxes[-1][1], "Update check")


    def test_editor_buttons_and_icons(self):
        w = self.win
        for b in (w.pycharm_btn, w.sublime_btn, w.b_pycharm, w.b_sublime):
            self.assertFalse(b.icon().isNull())
        self.assertEqual(w.pycharm_btn.text(), "PyCharm")
        self.assertEqual(w.sublime_btn.text(), "Sublime Text")
        launched = []
        orig = core.open_in_editor
        core.open_in_editor = lambda key, path, cfg=None: launched.append((key, path))
        try:
            w.pycharm_btn.click()
            w.sublime_btn.click()
        finally:
            core.open_in_editor = orig
        self.assertEqual([k for k, _ in launched], ["pycharm", "sublime"])
        self.assertTrue(os.path.isdir(launched[0][1]))

    def test_missing_editor_shows_warning(self):
        os.environ.pop("NK_SUBLIME", None)
        self.win.cfg["sublime_path"] = ""
        old = os.environ["PATH"]
        os.environ["PATH"] = os.path.join(self.tmp, "emptybin")
        try:
            if core._editor_search("sublime"):
                self.skipTest("Sublime Text really installed here")
            self.win.sublime_btn.click()
        finally:
            os.environ["PATH"] = old
        self.assertTrue(any(k == "warn" and "Sublime" in t for k, t, _ in self.boxes))

    def test_settings_save_icon_dir_and_paths(self):
        w = self.win
        d = os.path.join(self.tmp, "myicons")
        os.makedirs(d)
        with open(os.path.join(d, "pycharm.png"), "wb") as fh:
            fh.write(b"x")                                    # invalid png on purpose
        w.s_icons[1].setText(d)
        w.s_pycharm[1].setText("/x/pycharm.sh")
        w.s_save.click()
        cfg = core.load_config()
        self.assertEqual(cfg["icon_dir"], d)
        self.assertEqual(cfg["pycharm_path"], "/x/pycharm.sh")
        self.assertFalse(w.pycharm_btn.icon().isNull())       # bad png -> built-in fallback icon


    def test_header_and_github_side_panel(self):
        w = self.win
        self.assertIn(core.artist_name(w.cfg), w.artist_lbl.text())
        self.assertIn("Foundry", w.nuke_lbl.text())
        self.assertGreaterEqual(w.gh_list.count(), 3)             # built-in list shown immediately
        self.assertIsNotNone(w.gh_list.itemWidget(w.gh_list.item(0)))

    def test_side_panel_install_button(self):
        w = self.win
        d = os.path.join(self.src, "GhTool")
        os.makedirs(d)
        with open(os.path.join(d, "init.py"), "w") as fh:
            fh.write("x = 1\n")
        w._gh_populate([core._norm_entry({"name": "someone/GhTool", "url": d, "version": "1.0",
                                          "description": "test", "stars": 12})])
        w.review_chk.setChecked(False)
        w._gh_install(0)
        pump(w)
        self.assertIn("GhTool.global", core.load_registry(w.cfg)["tools"])
        w._gh_install(5)                                          # out of range -> warning, no crash
        self.assertTrue(any(k == "warn" for k, _, _ in self.boxes))

    def test_artist_name_setting_updates_header(self):
        w = self.win
        w.s_artist.setText("Neha K")
        w.s_save.click()
        self.assertIn("Neha K", w.artist_lbl.text())
        self.assertEqual(core.load_config()["artist_name"], "Neha K")


    def _tool_with_error(self):
        d = os.path.join(self.src, "BrokenTool")
        os.makedirs(os.path.join(d, "sub"))
        with open(os.path.join(d, "init.py"), "w") as fh:
            fh.write("import nuke\n")
        with open(os.path.join(d, "sub", "menu.py"), "w") as fh:
            fh.write("import nuke\n\ndef add():\n    nuke.menu('Nuke'\n")
        self.install_via_ui(d, "1.0")
        return d

    def test_editor_check_fix_save(self):
        self._tool_with_error()
        w = self.win
        w.inst_table.selectRow(0)
        w.b_errors.click()                                         # scan + jump to the first error
        ed = w.editor
        self.assertIs(w.tabs.currentWidget(), ed)
        self.assertEqual(ed.problems.count(), 1)
        cur = ed.current()
        self.assertTrue(cur.path.endswith("menu.py"))
        self.assertEqual(cur.textCursor().blockNumber() + 1, cur.problems[0]["line"])
        # tree shows tool files + startup files
        names = []
        it = ed.tree.invisibleRootItem()

        def walk(n):
            for i in range(n.childCount()):
                c = n.child(i)
                names.append(c.text(0))
                walk(c)
        walk(it)
        self.assertTrue(any(n.startswith("init.py") for n in names))
        self.assertIn("menu.py", names)
        # fix the error by typing, save -> backup + no more problems
        cur.selectAll()
        cur.insertPlainText("import nuke\n\ndef add():\n    nuke.menu('Nuke')\n")      # simulates typing
        self.assertTrue(cur.document().isModified())
        self.assertTrue(ed.tabs.tabText(ed.tabs.indexOf(cur)).endswith("*"))
        ed.b_save.click()
        self.assertFalse(cur.document().isModified())
        self.assertEqual(core.scan_folder_errors(os.path.dirname(os.path.dirname(cur.path))), [])
        self.assertTrue(core.list_backups(w.cfg))

    def test_editor_startup_file_syntax_guard_and_themes(self):
        w = self.win
        ed = w.editor
        menu = core.nuke_startup_files(w.cfg)[1]
        e = ed.open_file(menu)                                     # not created yet -> empty new file
        self.assertIsNotNone(e)
        e.setPlainText("print(\n")
        answers = []
        ed.ask = lambda t, m: (answers.append(t), False)[1]        # user refuses to save a broken menu.py
        self.assertFalse(ed.save_current())
        self.assertFalse(os.path.exists(menu))
        self.assertEqual(answers, ["Syntax error"])
        ed.ask = lambda t, m: True
        self.assertTrue(ed.save_current())
        self.assertTrue(os.path.isfile(menu))
        for name in nk_ui.nk_editor.THEMES:
            ed.theme_box.setCurrentText(name)
            self.assertEqual(e.theme, name)
        self.assertEqual(core.load_config()["editor_theme"], "Sublime Monokai")

    def test_editor_typing_helpers_and_find(self):
        ed = self.win.editor
        p = os.path.join(self.tmp, "t.py")
        with open(p, "w") as fh:
            fh.write("def f():\n    pass\n# needle\n")
        e = ed.open_file(p)
        e.setPlainText("if x:")
        e.moveCursor(QtGui.QTextCursor.End)
        ev = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Return, QtCore.Qt.NoModifier)
        e.keyPressEvent(ev)
        self.assertEqual(e.toPlainText(), "if x:\n    ")           # auto indent after ':'
        e.setPlainText("def f():\n    pass\n# needle\n")
        ed.find_edit.setText("needle")
        self.assertTrue(ed.find_next())
        self.assertEqual(e.textCursor().selectedText(), "needle")
        ed.find_edit.setText("absent")
        self.assertFalse(ed.find_next())


if __name__ == "__main__":
    unittest.main()
