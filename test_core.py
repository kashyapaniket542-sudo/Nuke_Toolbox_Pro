# -*- coding: utf-8 -*-
"""Run:  python -m unittest discover -s tests -v     (from the NK_tools_installer folder)
Set NK_TEST_NET=1 to also run the real GitHub download test."""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import nk_core as core  # noqa: E402


def make_tool(base, name, gizmos=("MyGizmo",), py=None, menu_py=False, manifest=None, extra=None):
    d = os.path.join(base, name)
    os.makedirs(os.path.join(d, "gizmos"), exist_ok=True)
    for g in gizmos:
        with open(os.path.join(d, "gizmos", g + ".gizmo"), "w") as f:
            f.write("Group {\n name %s\n}\n" % g)
    for rel, text in (py or {}).items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
    if menu_py:
        with open(os.path.join(d, "menu.py"), "w") as f:
            f.write("print('my own menu')\n")
    if manifest is not None:
        with open(os.path.join(d, "tool.json"), "w") as f:
            json.dump(manifest, f)
    for rel, text in (extra or {}).items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
    return d


def zip_folder(folder, out, wrap=True):
    with zipfile.ZipFile(out, "w") as z:
        for dp, _, files in os.walk(folder):
            for f in files:
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, folder)
                z.write(full, os.path.join(os.path.basename(folder), rel) if wrap else rel)
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nktest_")
        self.home = os.path.join(self.tmp, "dot_nuke")
        os.makedirs(self.home)
        os.environ["NK_HOME_NUKE"] = self.home
        os.environ["NK_NUKE_VERSION"] = "15.1"
        os.environ.pop("NK_ROLE", None)
        self.cfg = core.load_config()
        self.cfg["role"] = "admin"
        self.src = os.path.join(self.tmp, "src")
        os.makedirs(self.src)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def install(self, folder, **kw):
        p = core.InstallParams(src=folder, **kw)
        return core.install_from(p, self.cfg)

    def init_text(self):
        return open(os.path.join(self.home, "init.py")).read()

    def menu_text(self):
        return open(os.path.join(self.home, "menu.py")).read()


class TestInstall(Base):
    def test_gizmo_install_registers(self):
        d = make_tool(self.src, "Stamps", gizmos=("Stamps", "Anchor"))
        r = self.install(d, version="1.0")
        self.assertTrue(os.path.isfile(os.path.join(r["path"], "gizmos", "Stamps.gizmo")))
        reg = core.load_registry(self.cfg)
        t = reg["tools"]["Stamps.global"]
        self.assertEqual(t["type"], "Gizmo")
        self.assertEqual(t["active_version"], "1.0")
        self.assertIn("NK_TOOLS Stamps.global", self.init_text())
        self.assertIn("pluginAddPath", self.init_text())
        self.assertIn("NK_TOOLS __BOOT__", self.init_text())
        self.assertTrue(self.init_text().startswith("# >>> NK_TOOLS __BOOT__"))
        self.assertIn("createNode('Anchor')", self.menu_text())
        self.assertTrue(self.menu_text().rstrip().endswith("# <<< NK_TOOLS __CONFIRM__ <<<"))
        self.assertTrue(os.path.isfile(os.path.join(self.home, "NK_tools", "_runtime", "nk_tools_boot.py")))
        self.assertEqual(core.load_state(self.cfg)["pending"], "Stamps.global")

    def test_generated_scripts_run_against_fake_nuke(self):
        d = make_tool(self.src, "Stamps", gizmos=("Stamps",))
        r = self.install(d, version="1.0")
        calls = {"paths": [], "cmds": []}
        nuke = types.ModuleType("nuke")
        nuke.GUI = True
        nuke.NUKE_VERSION_MAJOR = 15
        nuke.env = {}
        nuke.tprint = lambda *a: None
        nuke.executeInMainThread = lambda f, a=(): None
        nuke.message = lambda *a: None
        nuke.pluginAddPath = lambda p: calls["paths"].append(p)

        class M:
            def addMenu(self, n):
                calls["cmds"].append(("menu", n))
                return self

            def addCommand(self, label, cmd, *a):
                calls["cmds"].append((label, cmd))
        nuke.menu = lambda n: M()
        sys.modules["nuke"] = nuke
        try:
            for mod in [m for m in sys.modules if m == "nk_tools_boot"]:
                del sys.modules[mod]
            g = {"__name__": "init"}
            exec(compile(self.init_text(), "init.py", "exec"), g)
            exec(compile(self.menu_text(), "menu.py", "exec"), g)
        finally:
            del sys.modules["nuke"]
            sys.modules.pop("nk_tools_boot", None)
            if os.path.join(self.home, "NK_tools", "_runtime").replace("\\", "/") in sys.path:
                sys.path.remove(os.path.join(self.home, "NK_tools", "_runtime").replace("\\", "/"))
        self.assertIn(os.path.join(r["path"], "gizmos").replace("\\", "/"), calls["paths"])
        self.assertIn(("Stamps", "nuke.createNode('Stamps')"), calls["cmds"])
        self.assertIsNone(core.load_state(self.cfg)["pending"])  # confirm() ran

    def test_python_tool_with_package_and_own_menu(self):
        d = make_tool(self.src, "pytool", gizmos=(), py={"mypkg/__init__.py": "X=1\n", "mypkg/sub/a.py": "Y=2\n",
                                                          "helper.py": "Z=3\n"}, menu_py=True)
        r = self.install(d, version="1")
        reg = core.load_registry(self.cfg)
        v = reg["tools"]["pytool.global"]["versions"][0]
        self.assertEqual(reg["tools"]["pytool.global"]["type"], "Python")
        self.assertEqual(v["plugin_dirs"], [r["path"]])              # package internals not registered
        self.assertIn("mypkg", v["provides"]["modules"])
        self.assertIn("helper", v["provides"]["modules"])
        self.assertFalse(v["auto_menu"])                              # tool ships its own menu.py
        self.assertNotIn("NK_TOOLS pytool.global", self.menu_text())

    def test_type_detection(self):
        for name, kw, want in (
                ("a", dict(gizmos=(), extra={"x.dll": "bin"}), "DLL / Plugin"),
                ("b", dict(gizmos=(), extra={"x.tcl": "proc a {} {}"}), "TCL"),
                ("c", dict(gizmos=(), extra={"x.nk": "set cut_paste_input []"}), ".nk"),
                ("d", dict(gizmos=("G",)), "Gizmo")):
            d = make_tool(self.src, name, **kw)
            self.install(d, version="1")
            self.assertEqual(core.load_registry(self.cfg)["tools"][name + ".global"]["type"], want)

    def test_nk_file_gets_menu_entry(self):
        d = make_tool(self.src, "snip", gizmos=(), extra={"nodes/cool.nk": "set cut_paste_input []"})
        self.install(d, version="1")
        self.assertIn("nodePaste", self.menu_text())

    def test_zip_with_wrapper_folder_and_name_clean(self):
        d = make_tool(self.src, "Foo-1.2.3")
        z = zip_folder(d, os.path.join(self.tmp, "Foo-1.2.3.zip"))
        r = self.install(z)
        self.assertEqual(r["name"], "Foo")
        self.assertTrue(os.path.isfile(os.path.join(r["path"], "gizmos", "MyGizmo.gizmo")))

    def test_dry_run_changes_nothing(self):
        d = make_tool(self.src, "Dry")
        res = core.install_from(core.InstallParams(src=d, version="1"), self.cfg, dry_run=True)
        self.assertTrue(res["dry_run"])
        self.assertIn("Startup scripts", core.plan_text(core.prepare(core.InstallParams(src=make_tool(
            self.src, "Dry2", menu_py=True), version="1"), self.cfg)))
        self.assertFalse(os.path.exists(os.path.join(self.home, "init.py")))
        self.assertEqual(core.load_registry(self.cfg)["tools"], {})

    def test_review_veto_cancels(self):
        d = make_tool(self.src, "Veto")
        with self.assertRaises(core.Cancelled):
            core.install_from(core.InstallParams(src=d), self.cfg, review=lambda st: False)
        self.assertEqual(core.load_registry(self.cfg)["tools"], {})

    def test_sha256_check(self):
        d = make_tool(self.src, "Sha")
        z = zip_folder(d, os.path.join(self.tmp, "Sha.zip"))
        good = core.sha256_file(z)
        self.install(z, sha256=good, version="1")
        with self.assertRaises(core.NKError):
            self.install(z, sha256="0" * 64, version="2")

    def test_zip_slip_rejected(self):
        z = os.path.join(self.tmp, "evil.zip")
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("../evil.txt", "x")
        with self.assertRaises(core.NKError):
            self.install(z)

    def test_empty_package_blocked(self):
        d = os.path.join(self.src, "empty")
        os.makedirs(d)
        open(os.path.join(d, "readme.txt"), "w").write("hi")
        with self.assertRaises(core.NKError):
            self.install(d, version="1")

    def test_python2_syntax_warning(self):
        d = make_tool(self.src, "py2", py={"old.py": "print 'hello'\n"})
        st = core.prepare(core.InstallParams(src=d, version="1"), self.cfg)
        self.assertTrue(any("Syntax error" in w for w in st.plan["warnings"]))
        st.discard()


class TestCompatAndRoles(Base):
    def test_manifest_incompatible_blocks_unless_forced(self):
        os.environ["NK_NUKE_VERSION"] = "13.0"
        d = make_tool(self.src, "Needs15", manifest={"name": "Needs15", "nuke_min": "15.0"})
        st = core.prepare(core.InstallParams(src=d, version="1"), self.cfg)
        # standalone (not inside Nuke) -> warning only
        self.assertTrue(any("15.0" in w for w in st.plan["warnings"]))
        st.discard()
        d = make_tool(self.src, "OnlyWin", manifest={"platforms": ["win"] if core.os_key() != "win" else ["mac"]})
        with self.assertRaises(core.NKError):
            self.install(d, version="1")
        r = self.install(d, version="1", force=True)
        self.assertEqual(r["name"], "OnlyWin")

    def test_manifest_name_version_menu(self):
        d = make_tool(self.src, "x", manifest={"name": "Pretty", "version": "2.5", "description": "d",
                                               "menu": [{"menu": "Nuke", "path": "NK/Pretty/Run",
                                                         "command": "print(1)", "shortcut": "ctrl+shift+p"}]})
        r = self.install(d)
        self.assertEqual((r["name"], r["version"]), ("Pretty", "2.5"))
        self.assertIn("ctrl+shift+p", self.menu_text())

    def test_role_blocks_studio_scope(self):
        self.cfg["role"] = "artist"
        d = make_tool(self.src, "R")
        with self.assertRaises(core.NKError):
            self.install(d, version="1", scope="Studio production level")
        self.install(d, version="1", scope="Global")
        os.environ["NK_ROLE"] = "admin"
        self.install(d, version="1", scope="Studio production level")

    def test_scope_conditions_in_init(self):
        d = make_tool(self.src, "S")
        self.install(d, version="1", scope="Major version")
        self.install(d, version="1", scope="TD level")
        self.install(d, version="1", scope="Studio production level")
        t = self.init_text()
        self.assertIn("nuke.NUKE_VERSION_MAJOR == 15", t)
        self.assertIn("NK_LEVEL", t)
        self.assertIn("nuke.env.get('studio')", t)
        self.assertTrue(os.path.isdir(os.path.join(self.home, "NK_tools", "nuke15", "S", "1")))


class TestManage(Base):
    def test_conflicts_detected(self):
        self.install(make_tool(self.src, "One", gizmos=("Shared",)), version="1")
        st = core.prepare(core.InstallParams(src=make_tool(self.src, "Two", gizmos=("Shared",)), version="1"), self.cfg)
        self.assertTrue(any("Shared" in c for c in st.plan["conflicts"]))
        st.discard()

    def test_disable_enable_and_boot_enabled(self):
        self.install(make_tool(self.src, "T"), version="1")
        core.set_enabled(self.cfg, "T.global", False)
        self.assertEqual(core.tool_status(self.cfg, core.load_registry(self.cfg)["tools"]["T.global"]), "Disabled")
        spec = importlib.util.spec_from_file_location("boot", os.path.join(self.home, "NK_tools", "_runtime", "nk_tools_boot.py"))
        boot = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(boot)
        self.assertFalse(boot.enabled("T.global"))
        core.set_enabled(self.cfg, "T.global", True)
        self.assertTrue(boot.enabled("T.global"))

    def test_crash_guard_quarantines(self):
        self.install(make_tool(self.src, "Crashy"), version="1")
        spec = importlib.util.spec_from_file_location("boot2", os.path.join(self.home, "NK_tools", "_runtime", "nk_tools_boot.py"))
        boot = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(boot)
        boot._gui = lambda: True
        boot.start()                    # launch 1 starts ... and "crashes" (confirm never called)
        self.assertTrue(boot.enabled("Crashy.global"))
        boot.start()                    # launch 2 -> quarantined
        self.assertFalse(boot.enabled("Crashy.global"))
        self.assertEqual(core.tool_status(self.cfg, core.load_registry(self.cfg)["tools"]["Crashy.global"]), "Quarantined")

    def test_versions_rollback_and_prune(self):
        d = make_tool(self.src, "V")
        self.cfg["keep_versions"] = 2
        r1 = self.install(d, version="1.0")
        r2 = self.install(d, version="2.0")
        self.assertIn(r2["path"].replace("\\", "/"), self.init_text())
        core.rollback(self.cfg, "V", "1.0")
        self.assertIn(r1["path"].replace("\\", "/"), self.init_text())
        self.assertNotIn(r2["path"].replace("\\", "/"), self.init_text())
        self.assertEqual(core.load_registry(self.cfg)["tools"]["V.global"]["active_version"], "1.0")
        self.install(d, version="3.0")                 # keep 2 -> oldest non-active removed
        vs = [v["version"] for v in core.load_registry(self.cfg)["tools"]["V.global"]["versions"]]
        self.assertEqual(len(vs), 2)
        self.assertIn("3.0", vs)
        with self.assertRaises(core.NKError):
            core.rollback(self.cfg, "V", "9.9")

    def test_uninstall_cleans_everything(self):
        d = make_tool(self.src, "Gone")
        r = self.install(d, version="1")
        open(os.path.join(self.home, "init.py"), "a").write("\nprint('user code')\n")
        core.uninstall(self.cfg, "Gone")
        self.assertFalse(os.path.exists(r["path"]))
        self.assertNotIn("NK_TOOLS Gone.global", self.init_text())
        self.assertIn("user code", self.init_text())
        self.assertNotIn("Gone.global", self.menu_text())
        self.assertEqual(core.load_registry(self.cfg)["tools"], {})

    def test_backups_and_restore(self):
        init = os.path.join(self.home, "init.py")
        open(init, "w").write("print('original')\n")
        self.install(make_tool(self.src, "B"), version="1")
        bk = [b for b in core.list_backups(self.cfg) if b["target"] == "init.py"]
        self.assertTrue(bk)
        core.restore_backup(self.cfg, bk[-1]["path"])        # oldest = the original
        self.assertEqual(open(init).read(), "print('original')\n")

    def test_user_content_preserved_and_idempotent(self):
        init = os.path.join(self.home, "init.py")
        open(init, "w").write("import os\nprint('mine')\n")
        d = make_tool(self.src, "I")
        self.install(d, version="1")
        first = self.init_text()
        self.install(d, version="1")
        self.assertEqual(first, self.init_text())
        self.assertEqual(self.init_text().count("NK_TOOLS I.global >>>"), 1)
        self.assertIn("print('mine')", self.init_text())
        compile(self.init_text(), "init.py", "exec")
        compile(self.menu_text(), "menu.py", "exec")

    def test_profiles(self):
        self.install(make_tool(self.src, "A"), version="1")
        self.install(make_tool(self.src, "B", gizmos=("Bg",)), version="1")
        core.save_profile(self.cfg, "only_a", ["A.global"])
        core.apply_profile(self.cfg, "only_a")
        st = core.load_state(self.cfg)
        self.assertEqual(st["disabled"], ["B.global"])
        core.save_profile(self.cfg, "all")
        self.assertEqual(sorted(core.load_registry(self.cfg)["profiles"]["all"]), ["A.global"])
        core.delete_profile(self.cfg, "only_a")
        self.assertNotIn("only_a", core.load_registry(self.cfg)["profiles"])

    def test_pack_export_skips_local(self):
        self.install(make_tool(self.src, "Loc"), version="1")
        out = os.path.join(self.tmp, "pack.json")
        self.assertEqual(core.export_pack(self.cfg, out), ["Loc"])
        self.assertEqual(json.load(open(out))["tools"], [])

    def test_pack_import_roundtrip_with_zip_url(self):
        d = make_tool(self.src, "Pk", gizmos=("Pkg",))
        z = zip_folder(d, os.path.join(self.tmp, "Pk.zip"))
        pack = os.path.join(self.tmp, "p.json")
        json.dump({"tools": [{"name": "Pk", "src": z, "scope": "Global", "ref": ""}]}, open(pack, "w"))
        res = core.import_pack(self.cfg, pack)
        self.assertEqual(res["installed"], ["Pk"])
        self.assertEqual(res["failed"], [])
        json.dump({"tools": [{"name": "Bad", "src": "/nope.zip"}]}, open(pack, "w"))
        self.assertEqual(len(core.import_pack(self.cfg, pack)["failed"]), 1)

    def test_audit_log(self):
        self.install(make_tool(self.src, "Au"), version="1")
        core.uninstall(self.cfg, "Au")
        acts = [a["action"] for a in core.read_audit(self.cfg)]
        self.assertEqual(acts[:2], ["uninstall", "install"])

    def test_env_snippet(self):
        r = self.install(make_tool(self.src, "E"), version="1")
        self.assertIn(r["path"], core.env_snippet(self.cfg))
        core.set_enabled(self.cfg, "E.global", False)
        self.assertNotIn(r["path"], core.env_snippet(self.cfg))

    def test_custom_init_dir_for_shared_deployment(self):
        shared = os.path.join(self.tmp, "shared_nuke_path")
        self.cfg["init_dir"] = shared
        self.install(make_tool(self.src, "Sh"), version="1")
        self.assertTrue(os.path.isfile(os.path.join(shared, "init.py")))
        self.assertFalse(os.path.exists(os.path.join(self.home, "init.py")))


class TestUpdates(Base):
    def test_ver_key(self):
        self.assertTrue(core.ver_key("v1.10.0") > core.ver_key("v1.9.3"))
        self.assertEqual(core.ver_key("none"), ())

    def test_tag_update_detection_and_params(self):
        self.install(make_tool(self.src, "U"), version="v1.0", ref="v1.0", ref_kind="Release (tag)")
        reg = core.load_registry(self.cfg)
        t = reg["tools"]["U.global"]
        t["source"], t["source_url"] = "GitHub URL", "https://github.com/a/b"
        orig = core.fetch_refs
        try:
            core.fetch_refs = lambda *a, **k: ["v1.0", "v1.2", "v1.10"]
            r = core.check_update(t, self.cfg)
            self.assertTrue(r["available"])
            self.assertEqual(r["latest"], "v1.10")
            t["update_info"] = r
            p = core.params_for_update(t)
            self.assertEqual((p.ref, p.ref_kind, p.name), ("v1.10", "Release (tag)", "U"))
            core.fetch_refs = lambda *a, **k: ["v1.0"]
            self.assertFalse(core.check_update(t, self.cfg)["available"])
        finally:
            core.fetch_refs = orig

    def test_branch_update_uses_commit(self):
        self.install(make_tool(self.src, "Br"), version="x")
        reg = core.load_registry(self.cfg)
        t = reg["tools"]["Br.global"]
        t["source"], t["source_url"] = "GitHub URL", "https://github.com/a/b"
        t["versions"][0]["commit"] = "a" * 40
        orig = core.latest_commit
        try:
            core.latest_commit = lambda *a, **k: "b" * 40
            self.assertTrue(core.check_update(t, self.cfg)["available"])
            core.latest_commit = lambda *a, **k: "a" * 40
            self.assertFalse(core.check_update(t, self.cfg)["available"])
        finally:
            core.latest_commit = orig

    def test_archive_urls(self):
        self.assertEqual(core.to_archive_url("GitHub URL", "https://github.com/a/b.git"),
                         "https://codeload.github.com/a/b/zip/HEAD")
        self.assertEqual(core.to_archive_url("GitHub URL", "https://github.com/a/b", "v1", "Release (tag)"),
                         "https://codeload.github.com/a/b/zip/refs/tags/v1")
        self.assertIn("projects/g%2Fs%2Fp/repository/archive.zip?sha=dev",
                      core.to_archive_url("GitLab URL", "https://gitlab.com/g/s/p.git", "dev"))

    def test_catalog_default_and_file(self):
        self.assertEqual(core.search("Studio catalog", "luma", self.cfg)[0]["source"], "GitHub URL")
        cat = os.path.join(self.tmp, "catalog.json")
        json.dump({"tools": [{"name": "Studio Tool", "url": "https://x/y.zip", "tags": ["comp"]}]}, open(cat, "w"))
        self.cfg["catalog"] = cat
        res = core.search("Studio catalog", "comp", self.cfg)
        self.assertEqual((res[0]["name"], res[0]["source"]), ("Studio Tool", "Direct URL"))


class TestIconsAndEditors(Base):
    def setUp(self):
        super().setUp()
        for k in ("NK_ICON_DIR", "NK_PYCHARM", "NK_SUBLIME", "NUKE_PATH"):
            os.environ.pop(k, None)

    def _icons(self, parent, name="icons", files=("pycharm.png", "sublime.png")):
        d = os.path.join(parent, name)
        os.makedirs(d)
        for f in files:
            with open(os.path.join(d, f), "wb") as fh:
                fh.write(b"x")
        return d

    def test_icon_dir_autodetected_next_to_installer(self):
        d = core.find_icon_dir(self.cfg)
        self.assertTrue(d.endswith("icons"))
        self.assertTrue(core.find_icon("pycharm", self.cfg).lower().endswith((".png", ".svg")))

    def test_icon_dir_priority_config_then_env(self):
        a = self._icons(self.tmp, "cfg_icons")
        b = self._icons(self.tmp, "env_icons")
        self.cfg["icon_dir"] = a
        os.environ["NK_ICON_DIR"] = b
        self.assertEqual(core.find_icon_dir(self.cfg), os.path.abspath(a))
        self.cfg["icon_dir"] = ""
        self.assertEqual(core.find_icon_dir(self.cfg), os.path.abspath(b))

    def test_icon_dir_candidates_include_home_and_nuke_path(self):
        h = self._icons(self.home)
        np_ = os.path.join(self.tmp, "plugins")
        os.makedirs(np_)
        os.environ["NUKE_PATH"] = np_
        cands = core.icon_dir_candidates(self.cfg)
        self.assertIn(h, cands)
        self.assertIn(os.path.join(np_, "icons"), cands)
        self.assertTrue(core._icon_dir_ok(h))

    def test_empty_or_missing_folder_is_not_an_icon_dir(self):
        e = os.path.join(self.tmp, "empty")
        os.makedirs(e)
        self.assertFalse(core._icon_dir_ok(e))
        self.assertFalse(core._icon_dir_ok(os.path.join(self.tmp, "none")))
        self.assertFalse(core._icon_dir_ok(""))

    def test_find_icon_prefers_png_and_is_case_insensitive(self):
        d = self._icons(self.tmp, "ic", ("PyCharm.SVG", "pycharm.png"))
        self.assertTrue(core.find_icon("pycharm", icon_dir=d).lower().endswith(".png"))
        self.assertEqual(core.find_icon("sublime", icon_dir=d), "")

    def _fake_exe(self, name, body="#!/bin/sh\n"):
        p = os.path.join(self.tmp, name)
        with open(p, "w") as fh:
            fh.write(body)
        os.chmod(p, 0o755)
        return p

    def test_find_editor_config_env_path(self):
        exe = self._fake_exe("mypycharm")
        self.cfg["pycharm_path"] = exe
        self.assertEqual(core.find_editor("pycharm", self.cfg), exe)
        self.cfg["pycharm_path"] = ""
        os.environ["NK_PYCHARM"] = exe
        self.assertEqual(core.find_editor("pycharm", self.cfg), exe)
        os.environ.pop("NK_PYCHARM")
        subl = self._fake_exe("subl")
        old = os.environ["PATH"]
        os.environ["PATH"] = self.tmp + os.pathsep + old
        try:
            self.assertEqual(os.path.realpath(core.find_editor("sublime", self.cfg)), os.path.realpath(subl))
        finally:
            os.environ["PATH"] = old

    @unittest.skipIf(sys.platform.startswith("win"), "uses a shell-script fake editor")
    def test_open_in_editor_launches_and_errors(self):
        marker = os.path.join(self.tmp, "launched.txt")
        exe = self._fake_exe("fake_subl", "#!/bin/sh\necho \"$1\" > %s\n" % marker)
        self.cfg["sublime_path"] = exe
        cmd = core.open_in_editor("sublime", self.src, self.cfg)
        self.assertEqual(cmd, [exe, self.src])
        import time
        for _ in range(100):
            if os.path.exists(marker):
                break
            time.sleep(0.05)
        with open(marker) as fh:
            self.assertEqual(fh.read().strip(), self.src)
        with self.assertRaises(core.NKError):                        # missing target
            core.open_in_editor("sublime", os.path.join(self.tmp, "gone"), self.cfg)
        self.cfg["sublime_path"] = ""
        old = os.environ["PATH"]
        os.environ["PATH"] = os.path.join(self.tmp, "emptybin")
        try:
            if not core._editor_search("sublime"):
                with self.assertRaises(core.NKError):                # editor not installed
                    core.open_in_editor("sublime", self.src, self.cfg)
        finally:
            os.environ["PATH"] = old


class TestArtistAndNuke(Base):
    def setUp(self):
        super().setUp()
        for k in ("NK_ARTIST", "NUKE_INSTALL_PATH", "NK_NUKE_ROOT", "NK_NUKE_VERSION"):
            os.environ.pop(k, None)

    def tearDown(self):
        os.environ["NK_NUKE_VERSION"] = "15.1"
        super().tearDown()

    def test_artist_name_priority(self):
        self.assertTrue(core.artist_name(self.cfg))
        os.environ["NK_ARTIST"] = "Env Artist"
        self.assertEqual(core.artist_name(self.cfg), "Env Artist")
        self.cfg["artist_name"] = "  Jane Doe "
        self.assertEqual(core.artist_name(self.cfg), "Jane Doe")

    def test_version_from_folder_name(self):
        self.assertEqual(core._nuke_version_from_name("Nuke15.1v2")[0], "15.1v2")
        self.assertEqual(core._nuke_version_from_name("Nuke14.0v5.app")[1], (14, 0, 5))
        self.assertEqual(core._nuke_version_from_name("NukeStudio13.2v1")[1], (13, 2, 1))
        self.assertIsNone(core._nuke_version_from_name("Houdini19"))

    def test_detect_installs_newest_first(self):
        root = os.path.join(self.tmp, "foundry")
        for n in ("Nuke14.0v5", "Nuke15.1v2", "Nuke15.0v4", "Other"):
            os.makedirs(os.path.join(root, n))
        exe = os.path.join(root, "Nuke15.1v2", "Nuke15.1")
        open(exe, "w").close()
        os.environ["NUKE_INSTALL_PATH"] = root
        found = core.detect_nuke_installs()
        self.assertEqual([f["version"] for f in found], ["15.1v2", "15.0v4", "14.0v5"])
        if not sys.platform.startswith("win") and sys.platform != "darwin":
            self.assertEqual(found[0]["exe"], exe)
        self.assertEqual(core.nuke_summary(found), "Nuke 15.1v2 (+2 more)")
        self.assertEqual(core.nuke_summary([]), "no Foundry Nuke found")

    def test_nuke_info_uses_detected_install(self):
        root = os.path.join(self.tmp, "foundry")
        os.makedirs(os.path.join(root, "Nuke16.0v1"))
        os.environ["NUKE_INSTALL_PATH"] = root
        self.assertEqual(core.nuke_info()["major"], 16)
        os.environ["NK_NUKE_VERSION"] = "14.1"                     # explicit override still wins
        self.assertEqual(core.nuke_info()["major"], 14)

    def test_github_tools_offline_and_fallback(self):
        tools, warn = core.github_nuke_tools(self.cfg, online=False)
        self.assertEqual(warn, "")
        self.assertTrue(any("github.com" in e["url"] for e in tools))
        orig = core.search
        core.search = lambda *a, **k: (_ for _ in ()).throw(core.NKError("offline"))
        try:
            tools2, warn2 = core.github_nuke_tools(self.cfg, "x")
        finally:
            core.search = orig
        self.assertEqual(len(tools2), len(tools))
        self.assertIn("offline", warn2)

    def test_github_tools_live_results_first_no_duplicates(self):
        live = [core._norm_entry({"name": "a/b", "url": "https://github.com/a/b", "stars": 5}),
                core._norm_entry({"name": "adrianpueyo/Stamps", "url": "https://github.com/adrianpueyo/Stamps/"})]
        orig = core.search
        core.search = lambda *a, **k: live
        try:
            tools, warn = core.github_nuke_tools(self.cfg)
        finally:
            core.search = orig
        urls = [e["url"].lower().rstrip("/") for e in tools]
        self.assertEqual(urls[0], "https://github.com/a/b")
        self.assertEqual(len(urls), len(set(urls)))


class TestEditorCore(Base):
    def test_check_source_python(self):
        self.assertEqual(core.check_source("x = 1\n", "a.py"), [])
        p = core.check_source("def f(:\n    pass\n", "a.py")
        self.assertEqual((p[0]["line"], p[0]["severity"]), (1, "error"))
        self.assertIn("TabError", core.check_source("if 1:\n\tx=1\n        y=2\n", "a.py")[0]["msg"])
        self.assertTrue(core.check_source("x = 1\0", "a.py"))                 # null byte -> error, no crash

    def test_check_source_gizmo_braces(self):
        self.assertEqual(core.check_source("Group {\n name a\n}\n", "a.gizmo"), [])
        self.assertEqual(core.check_source("# {\nA {\n b \\{ \n}\n", "a.gizmo"), [])   # comment + escaped
        w = core.check_source("Group {\n name a\n", "a.gizmo")
        self.assertEqual(w[0]["severity"], "warning")
        self.assertTrue(core.check_source("}\n", "a.nk"))

    def test_editable_files_skips_junk(self):
        for rel, data in (("init.py", "a"), ("sub/menu.py", "b"), ("sub/x.gizmo", "c"), ("_deps/lib.py", "d"),
                          (".git/config.txt", "e"), ("bin/tool.dll", "f"), ("tests/t.py", "g")):
            p = os.path.join(self.src, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as fh:
                fh.write(data)
        got = sorted(core.editable_files(self.src))
        self.assertEqual(got, sorted(["init.py", os.path.join("sub", "menu.py"), os.path.join("sub", "x.gizmo")]))

    def test_scan_folder_and_save_with_backup(self):
        good = os.path.join(self.src, "good.py")
        bad = os.path.join(self.src, "menu.py")
        with open(good, "w") as fh:
            fh.write("x = 1\n")
        with open(bad, "w") as fh:
            fh.write("import nuke\nnuke.menu(\n")
        probs = core.scan_folder_errors(self.src)
        self.assertEqual([os.path.basename(p["file"]) for p in probs], ["menu.py"])
        bak = core.save_text(self.cfg, bad, "import nuke\n")
        self.assertTrue(os.path.isfile(bak))
        with open(bad) as fh:
            self.assertEqual(fh.read(), "import nuke\n")
        with open(bak) as fh:
            self.assertIn("nuke.menu(", fh.read())
        self.assertEqual(core.scan_folder_errors(self.src), [])

    def test_read_text_encodings(self):
        p = os.path.join(self.src, "a.py")
        with open(p, "wb") as fh:
            fh.write("# caf\xe9\n".encode("cp1252"))
        text, enc = core.read_text(p)
        self.assertIn("caf\xe9", text)

    def test_startup_files_follow_init_dir(self):
        self.assertEqual([os.path.basename(p) for p in core.nuke_startup_files(self.cfg)], ["init.py", "menu.py"])
        self.assertTrue(core.nuke_startup_files(self.cfg)[0].startswith(self.home))


@unittest.skipUnless(os.environ.get("NK_TEST_NET"), "set NK_TEST_NET=1 for network tests")
class TestNetwork(Base):
    def test_real_github_install_default_branch(self):
        r = core.install_from(core.InstallParams(src="https://github.com/LumaPictures/LumaNukeGizmos"), self.cfg)
        self.assertEqual(r["name"], "LumaNukeGizmos")
        t = core.load_registry(self.cfg)["tools"]["LumaNukeGizmos.global"]
        self.assertEqual(len(t["versions"][0]["commit"]), 40)
        self.assertTrue(t["versions"][0]["gizmos"])


if __name__ == "__main__":
    unittest.main()
