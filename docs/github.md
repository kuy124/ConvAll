# GitHub repository setup

Suggested **About** description (paste into the repository sidebar):

> Offline Windows file converter with per-file targets, images/audio/video/PDF/documents/tables, metadata controls, and familiar themes. No uploads.

Suggested topics:

`windows` `desktop-app` `file-converter` `offline` `ffmpeg` `python` `tkinter`
`pdf` `image-converter` `audio-converter` `video-converter` `privacy`

## Release checklist

- Run `python tests/make_samples.py` and `python tests/verify.py`.
- Run `powershell -ExecutionPolicy Bypass -File scripts/build.ps1`.
- Smoke-test `dist/ConvAll.exe` on Windows.
- Create a versioned GitHub release with a brief changelog and known limitations.
- Attach `dist/ConvAll.exe` and include its SHA-256 checksum.
- Once the repository is public and has a release, add its real
  `/releases/latest` URL to the README's Download section.

No repository settings, tags, or releases are created by these documentation files.
