# IoT Doctor — Copilot Rules

- Existing Python/FastAPI IoT diagnostic project. Do not rewrite from scratch.
- Inspect the current implementation before editing.
- Make the smallest correct change for the requested task.
- Preserve working behavior unless the task requires changing it.
- Keep transport, parser, normalization, metrics, diagnostics, storage, API, and UI responsibilities separate.
- Keep device-specific logic out of generic core code.
- Diagnostics must be deterministic and evidence-based; never invent evidence.
- Distinguish current state from historical incidents/findings.
- Keep live, replay, and imported-analysis state separate.
- Add regression tests for meaningful behavior changes.
- Run `python -m pytest -q` after backend/shared changes.
- Run `python -m compileall core tests start.py` after backend changes.
- Do not add future-phase features unless explicitly requested.
- Do not add network scanning, packet capture, credential collection, cloud upload, or proprietary protocol reverse engineering.
- Real company/customer/device logs must not be committed.