# LEVIX 40-Second Advertisement

This folder contains a complete HyperFrames-style cinematic ad package for LEVIX.

## Files
- `index.html` - 40-second visual composition source.
- `DESIGN.md` - brand and motion identity used by the composition.
- `production-sequence.md` - storyboard, camera, VO, text, transitions, SFX, and soundtrack timing.
- `assets/captures/` - website screenshots captured from the local LEVIX site.
- `assets/brand/` - LEVIX logo assets copied from the repo.

## Notes
The local FastAPI app startup was not run because it can execute database migrations. Public pages were captured from the already-running local server at `127.0.0.1:8000`. The dashboard visuals in the composition are reconstructed from the actual dashboard CSS, navigation structure, product modules, and UI hierarchy.

The HyperFrames CLI was not run because fetching the npm package was blocked. The HTML is still authored as a timed composition and can be rendered when HyperFrames is available locally or explicitly approved.
