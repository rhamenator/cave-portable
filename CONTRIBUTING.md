# Contributing

Issues and pull requests are welcome. Describe the weather workflow, the authoritative data source, and how the change behaves when data is missing or stale. Keep the UI responsive by doing network and image work away from Tk's main thread. Bound downloads and avoid user-configurable URLs unless the security model is updated.

Run `python -m unittest discover -s tests -v` and smoke-test interface changes on a desktop. New forecast products need visible issue and valid times, attribution, and an explanation of limits. Contributions are licensed under GPL-3.0-only; include any third-party notices needed for new dependencies or assets.
