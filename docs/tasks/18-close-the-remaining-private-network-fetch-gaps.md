From task [12]. `ingest.check_url` keeps the cloud web app from fetching private addresses, but two gaps remain:

- **DNS rebinding:** the host name is resolved once for the check (`ingest.py:157-161`, `socket.getaddrinfo`) and again by urllib for the download (`ingest.py:212-215`), so a name can answer with a public address first and a private one second. Fix: connect to the address that was checked (pin it), or re-check the peer address of the actual connection, including on every redirect hop.
- **ffmpeg follows addresses inside a downloaded file:** a fetched playlist (HLS `.m3u8`, concat lists, etc.) can name further URLs, including private ones, which ffmpeg/ffprobe open (`ingest.py:234-247`). Fix: run ffprobe/ffmpeg with `-protocol_whitelist file,pipe` (or equivalent) so they read only the local file.

Then update `docs/webapp.md` (the "Not covered: DNS rebinding …" paragraph, around line 143-146) so it describes the guard as it is, without listing open gaps.

## Verification

A mocked resolver that answers public then private is refused at download time; a local `.m3u8` naming `http://127.0.0.1:…` fails without any request reaching that port; ordinary public links, YouTube and Drive still work; `checks/files-sandbox.py` passes.