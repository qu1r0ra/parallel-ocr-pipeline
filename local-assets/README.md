# Local course assets

Keep the original course files and all prepared or generated assets local. Git ignores these paths; do not add the files to a commit or upload them to the public repository.

Place the supplied files here:

```text
local-assets/
  supplied/
    dataset.zip
    CSC611M - Parallel OCR Pipeline AY2026-27 T1.pdf
  models/
    eng.traineddata
```

Then run `just prepare-assets`. It writes only the 100 files named `img0001.png` through `img0100.png` to `local-assets/dataset/images/`, and copies `labels.txt` beside that image directory. It skips `__MACOSX` entries and other archive metadata. Keep labels outside the image directory so they are not treated as OCR input.

The supplied English model is separate from both Python dependencies and the Tesseract program. The OCR caller should pass `--tessdata-dir "<absolute path to local-assets/models>"` to Tesseract so it uses the supplied model. `results/` is reserved for generated CSVs and benchmark output and is ignored by Git.

Each teammate needs matching local copies of the dataset archive and `eng.traineddata`. The PDF is kept as a local source reference; [`docs/requirements.md`](../docs/requirements.md) is the repository's shareable summary.
