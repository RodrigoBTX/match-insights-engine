# UI test scripts

Browser tests that drive a real Edge (headless) through the DevTools protocol: real clicks and key presses, real
screenshots, console errors reported. They found most of the visual and interaction bugs fixed so far, which unit
tests could not see. They are development tooling, not part of the product.

Requirements: Node 22 (uses the built-in `WebSocket`), Microsoft Edge at
`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` (change `EDGE` at the top of a script if yours is elsewhere),
and the app running on `http://127.0.0.1:8000`. For results that do not depend on Azure start it with
`$env:DEMO_ONLY = "1"`.

| Script | What it does | Arguments |
|---|---|---|
| `ui_audit.mjs` | Screenshots every chart and graphic: each moment's replay, each broadcast graphic, recap, players, the cards | `<outDir>` |
| `ui_select.mjs` | Selection card, previous/next, arrow keys, clickable control cells, players, timing, panel scrolling | `<outDir>` |
| `ui_about.mjs` | The "How it works" panel, the try-this suggestions, and how an automatic revision is shown (simulated result) | `<outDir>` |
| `ui_theme.mjs` | Light and dark theme: WCAG contrast of every visible text (page, selection, result, About), toggle label, persistence after reload, all players listed | `<outDir>` |
| `ui_narrow.mjs` | Phone (390 px) and tablet (820 px) widths: horizontal overflow, small tap targets, screenshots in both themes and of the broadcast view | `<outDir>` |
| `ui_shots.mjs` | The README/submission screenshots (selection card, explanation, all players; dark and light) | `<outDir>` |
| `ui_errors.mjs` | What the user sees when things fail: injected network/HTTP/stream errors, odd and invalid uploads, recovery afterwards | `<outDir> [absolute feed paths]` |
| `ui_demo.mjs` | The walk of someone without Azure: badge, recorded result, language fallback, player, broadcast, new match | `<outDir>` |
| `ui_broadcast.mjs` | Opens the broadcast view for one target and captures it | `<outDir> <moment text or player:Name or recap> [language] [file.png]` |
| `ui_upload.mjs` | Loads real-feed fixtures through the page's file input | `<outDir> <absolute path 1> [path 2 ...]` (relative paths fail inside Edge) |
| `ui_test.mjs` | The explain flow for a moment or a player with live agents | `<outDir> <moment text or player:Name> [audience] [language]` |

Notes learned the hard way:
- Wait about 6 seconds between two runs of the same script. The previous Edge can still be closing and holding the
  debugging port; the next run then fails with "no devtools". That is the harness, not the app.
- Screenshot `clip` coordinates are page coordinates: add `window.scrollX/Y` to `getBoundingClientRect()`.
- Each script uses its own debugging port (9333 to 9338) and profile folder `edge-*` in the temp directory.
  Stop leftovers with `Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" | Where-Object { $_.CommandLine -match "--headless" }`
  and never kill every `msedge.exe`: one of them may be your own browser.
- `contact_sheet.py` (needs `pip install pillow`) tiles screenshots into one image to review many at once.
