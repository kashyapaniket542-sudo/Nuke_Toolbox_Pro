# Nuke Toolbox Pro

Tool deployment and version management for Nuke (13+).
Install, update, enable/disable and roll back Nuke tools (gizmos, Python,
TCL, .nk, plugins) from local zips, GitHub, GitLab, direct URLs or Nukepedia.

## Install
1. Unzip to `~/.nuke/Nuke_Toolbox_Pro`
2. Add to `~/.nuke/init.py`:
   ```python
   import nuke
   nuke.pluginAddPath("Nuke_Toolbox_Pro")
   ```
3. Restart Nuke. Menu: **Nuke Toolbox Pro > Open Toolbox...**

## Command line (no Nuke needed)
```
python nk_tools_installer.py install <zip|folder|url> --scope global --yes
python nk_tools_installer.py install <url> --dry-run
python nk_tools_installer.py list
python nk_tools_installer.py check-updates
python nk_tools_installer.py update --all --yes
python nk_tools_installer.py rollback <tool> <version>
python nk_tools_installer.py --help
```

## Tips
- Set a `GITHUB_TOKEN` environment variable to avoid GitHub API rate limits.
- Update detection for releases uses git tags (e.g. `v2.1.0`).
- Set "Installer update URL" in Settings to your repo for self-update.

## License
MIT - see LICENSE.
