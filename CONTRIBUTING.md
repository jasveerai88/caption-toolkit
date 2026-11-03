# Contributing

Contributions are welcome — bug reports, fixes and small focused features.

## Ground rules

- **Standard library only.** caption-toolkit's promise is "clone and run".
  Pull requests that add a third-party dependency will not be merged.
- **Local only.** No network calls, no telemetry, no uploads of user files.
- **Timing fixes never alter text.** `fix` may change end times only.
- **Both directions tested.** A gate change needs a test where good input
  passes and bad input fails — not just one side.

## Getting started

```bash
git clone https://github.com/jasveerai88/caption-toolkit
cd caption-toolkit
python3 -m unittest discover -s tests -v
python3 src/caption_toolkit.py check examples/sample.srt
```

## Pull requests

1. Fork, branch, and keep the change to one topic.
2. Add or update tests under `tests/`; the full suite must pass.
3. Note the change in `CHANGELOG.md` under an "Unreleased" heading.
4. Describe the behaviour change with a real before/after run if the CLI
   output changes.
