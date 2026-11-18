# Release guide

1. Bump `VERSION` in nk_core.py and `version` in tool.json (must match).
2. Update CHANGELOG.md.
3. `git add . && git commit -m "Release X.Y.Z" && git push`
4. `git tag vX.Y.Z && git push origin vX.Y.Z`  (needed for update detection)
5. GitHub > Releases > Draft new release > choose tag > attach the Nukepedia zip.
6. Nukepedia: sign in, upload/update entry with the clean zip, add GitHub link,
   Nuke versions, OS, tags, license, screenshot.
7. Test on a clean profile: install from GitHub, push a newer tag, Check for Updates.
