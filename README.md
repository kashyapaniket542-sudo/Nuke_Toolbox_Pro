# Nuke_Toolbox_Pro
Nuke Toolbox Pro is a tool deployment and version manager for Nuke 13 and newer. It replaces manual copying of gizmos and scripts into ~/.nuke and hand-editing init.py and menu.py.


# Nuke Toolbox Pro

![Nuke 13+](https://img.shields.io/badge/Nuke-13%2B-orange)
![Python 3.7+](https://img.shields.io/badge/Python-3.7%2B-blue)
![License MIT](https://img.shields.io/badge/License-MIT-green)
![Platforms](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

**Install, update, enable and roll back Nuke tools from GitHub, GitLab, Nukepedia, URLs or local zips, all from one panel inside Nuke or from the command line.**

Nuke Toolbox Pro is a tool deployment and version manager for Nuke 13 and newer. It replaces manual copying of gizmos and scripts into `~/.nuke` and hand-editing `init.py` and `menu.py`.

## Features

- **Installs from anywhere:** local zip or folder, GitHub, GitLab, any direct zip URL, or Nukepedia (sign in, browse, search and install).
- **Detects the tool type for you:** gizmos, Python, TCL, `.nk` scripts and compiled plugins (`.dll`, `.so`, `.dylib`).
- **Reviews before it installs:** a plan screen and a dry-run mode show what will be added to `init.py` and `menu.py`. You can also choose manual registration and just get the code to paste.
- **Keeps your startup files safe:** backs up `init.py` and `menu.py` before every change, writes only its own marked blocks, and can restore from a backup.
- **Manages versions:** keeps the last 3 versions of each tool, checks for updates (release tags or latest commit) and rolls back with one command.
- **Checks compatibility:** reads an optional `tool.json` (`nuke_min`, `nuke_max`, `platforms`) and warns or blocks when a tool doesn't fit your Nuke version or OS.
- **Install scopes:** Global, Major version (for example Nuke 15 only), TD level and Studio production level, with artist, TD and admin roles controlling which scopes are allowed.
- **Enable, disable and uninstall:** switch tools off without deleting them, and use profiles to turn sets of tools on together.
- **Studio features:** shared tool catalog, export and import of tool packs, and an audit log of who installed what and when.
- **Built-in editing:** a code editor with theme options, plus buttons to open files in PyCharm or Sublime Text.
- **Command line:** every action works without Nuke, so it can be scripted for render farms, deploy scripts and CI.
- **Self-update:** can update itself from your repo.

## Installation

1. Download the latest release zip and unzip it to `~/.nuke/Nuke_Toolbox_Pro`
2. Add this to `~/.nuke/init.py`:
   ```python
   import nuke
   nuke.pluginAddPath("Nuke_Toolbox_Pro")
   ```
3. Restart Nuke and open **Nuke Toolbox Pro > Open Toolbox...**

## Command line

No Nuke needed:

```bash
python nk_tools_installer.py install <zip|folder|url> --scope global --yes
python nk_tools_installer.py install <url> --dry-run
python nk_tools_installer.py list
python nk_tools_installer.py check-updates
python nk_tools_installer.py update --all --yes
python nk_tools_installer.py rollback <tool> <version>
python nk_tools_installer.py export-pack studio_pack.json
python nk_tools_installer.py self-update --apply
python nk_tools_installer.py --help
```

## Making your own tool installable

Add an optional `tool.json` to the root of your tool:

```json
{
  "name": "My Tool",
  "version": "1.0.0",
  "type": "Gizmo",
  "nuke_min": "13.0",
  "nuke_max": "16.0",
  "platforms": ["win", "mac", "linux"]
}
```

Push git tags such as `v1.0.0` so update checks can detect new releases.

## Notes

- Set a `GITHUB_TOKEN` environment variable if you hit GitHub API rate limits (`GITLAB_TOKEN` for GitLab).
- Nukepedia downloads sometimes need a manual browser step because of the site's protection. The tool detects the file in your Downloads folder and continues.
- To enable self-update, set **Installer update URL** in Settings to this repository.

## Contributing

Issues and pull requests are welcome. Please run `test_core.py` before submitting changes.

## License

MIT. See [LICENSE](LICENSE).
