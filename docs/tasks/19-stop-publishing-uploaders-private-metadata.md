From task [12]. Two leaks of personal data from uploads:

- ffmpeg's normal output goes into the public `pipeline.log` (`ingest.py:244-247`). For a phone video it prints the GPS position, phone model and recording time.
- Audio uploads with an audio extension are renamed to `source.*` byte for byte (`ingest.py:223-228`) and served as the "original" with all their tags (ID3, Vorbis comments, cover art, GPS in MP4/M4A).

## Fix

- Run ffmpeg/ffprobe with `-hide_banner -loglevel error` (errors still reach the log) and `-map_metadata -1 -map_chapters -1` so no tags reach `source.*`.
- Pass kept-as-is audio through the same ffmpeg step with `-c:a copy -map_metadata -1` instead of a plain rename, so tags go but the audio stays bit-identical.
- Decide with the user whether to strip existing `source.*` files and `pipeline.log`s in `output/` and the results bucket (one-off; list what would change first).

## Verification

Upload a test MP3 with ID3 tags and a phone-style MP4 with location metadata: `ffprobe -show_format -show_streams` of `source.*` shows no tags, `pipeline.log` contains no `location`/`com.apple`/`creation_time` lines, and the pipeline still runs. README/docs mention that uploads are cleaned of tags.