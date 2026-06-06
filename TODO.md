# TODO.md

All issues from the previous TODO are resolved in the restructured scripts. Open items:

- [ ] `poolcam_snap.yml` still uses `actions/checkout@v5` — update to @v4 when touching that file
- [ ] `leslies_api.py` CSS class selectors are fragile — monitor for Leslie's page changes
- [ ] Flume password grant OAuth may be sunset — no known timeline, but watch for auth failures
- [ ] Consider pinning pip dependency versions in workflows (currently unpinned)
