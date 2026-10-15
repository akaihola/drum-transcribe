From task [12]. A submitted link is written into `pipeline.log` as-is (`ingest.py`, `_log(version_dir, f"   {url}")` and similar). A link containing a line break can forge a stage line such as `== running pipeline: x == not-a-date Z`. `progress._running` then calls `datetime.fromisoformat()` on the forged time (`progress.py:156`) and raises, which breaks the song list for every visitor until that version is deleted.

## Fix

- Refuse or strip control characters (CR, LF, others) in links in `check_url`, and never write raw visitor text into the log on its own line.
- Make `progress.py` robust: a line whose time does not parse is skipped (or treated as no time), so one bad log can never break the pages.

## Verification

A version whose `pipeline.log` contains a forged marker with a bad date still lists on `/` and its own page; `POST /api/create` with a link containing `\n` is a 400; `checks/hostile-names.py` passes.