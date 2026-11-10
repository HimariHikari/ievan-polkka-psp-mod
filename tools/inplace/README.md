# In-place patch tools (used for v1.1)

These patch a modded ISO directly, without the original ISO or the source assets.

- `isotool.py`: replaces AFS entries inside an ISO in place (same padded slot; updates only the TOC size), patches bytes in a file inside the ISO, and builds test-only "no notes" scripts. It keeps sizes the same, because size changes broke the PV.
- `make_v13.py`: retimes the leek animations in `pve_27` to song time (stage files play on the song clock).
- `make_payload_v11.py`: builds the installer payload from the v1.0 release exe's payload, swapping only changed files, and checks them against a modded ISO.
- `ramdump.py`: dumps PSP RAM from a running PPSSPP over its remote debugger (for finding the PV Mode lock).

They expect `repo/tools` at `./repo/tools` next to them (the layout used in the work folder); adjust `sys.path` if you move them.
