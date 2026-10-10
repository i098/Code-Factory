Closes #161

See [the frame loop](https://crewship.si/how.html#frame-loop) for rendering changes and touch-device limits.

Recorded hot-path profile before the change (Chromium CPU profile, full grid):
- Primary-ray object tests: 32-48%.
- Shadow rays: 6-24%.
- Terrain/sea march: 13-16%.
- Glyph drawing: about 5% on desktop.

Recorded object tests per frame, before and after:
- Box tests: 390k-509k to 42k-59k.
- Exact tests: 291k-372k to 26k-38k.

Recorded frame rates, before and after:
- WebKit iPhone 15 Pro emulation on the loaded Linux host: 9.4-11.5 to 18.6-25.5 fps.
- Desktop Chromium at 1440x900 on that host: 6.6-10.4 to 17-27 fps.
- Apple M5 headless Chromium at 1440x900: 46-54 fps with shadows dropped to steady 60 fps with shadows kept.
- iOS Simulator Safari (iPhone 15 Pro, Simulator): 59.1-60 to steady 60 fps, with p95 at 17 ms.

Simulator acceptance is approved.
These results do not include a physical iPhone measurement.
The owner checks the preview on his own iPhone before merge.
