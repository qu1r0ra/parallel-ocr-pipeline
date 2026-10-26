# OCR recognizer: settings, preprocessing, and evaluation

[`TesseractRecognizer`](../src/parallel_ocr_pipeline/recognizer.py) implements the [`ImageRecognizer`](ocr-contract.md) contract for [#4](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/4). It is independent of the pipeline, configuration parser, loader, and workers.

## Settings

| Setting | Default | Notes |
|---|---|---|
| Executable | `TESSERACT_CMD`, otherwise `tesseract` on `PATH` | Constructor argument `executable` overrides both. |
| Model directory | `local-assets/models` (holds the supplied `eng.traineddata`) | Constructor argument `tessdata_dir`; applied through `TESSDATA_PREFIX`. |
| Language | `eng` | |
| Timeout | 30 s per Tesseract attempt | Constructor argument `timeout`; must be positive. Normal calls take well under a second, so the limit only bounds hangs. |

Build one recognizer per process and share it among workers.

`pytesseract` reads the executable from a module attribute and the model directory from `TESSDATA_PREFIX`, so both are process-wide and the most recently constructed recognizer wins. The model directory uses `TESSDATA_PREFIX` instead of `--tessdata-dir` because `pytesseract` cannot pass a quoted path containing spaces on Windows (the option keeps literal quote characters). Tesseract runs as a separate process. The pipeline defaults `OMP_THREAD_LIMIT` to `1` while preserving explicit overrides; the benchmark pins it to `1` per the [concurrency design](concurrency-design.md). Standalone recognizer and evaluator commands inherit the caller's environment.

## Failures

`recognize(image)` returns text (possibly empty, which is valid inference) or raises a subclass of `RecognitionError`:

| Exception | Meaning | Pipeline treatment |
|---|---|---|
| `RecognitionTimeoutError` | Tesseract exceeded the timeout; the process is killed. | Transient: one retry allowed. |
| `RecognitionFailedError` | Tesseract exited non-zero, or failed to run, for this image (including temp-file I/O errors). | Terminal for that image. |
| `PrerequisiteError` | Executable missing/unstartable, or the model cannot be loaded. | Global failure: stop the run. |

The timeout is detected from `pytesseract`'s `RuntimeError("Tesseract process timeout")`, and model failures from Tesseract's stderr text; both depend on pinned `pytesseract` 0.3.13 and Tesseract 5.4 wording.

## Preprocessing

Applied to a new image; the caller's image is never modified or closed, and every derived image is closed even on failure:

1. Convert to grayscale, compositing any alpha channel onto white (some images are RGBA).
2. Median filter (3 px) to remove the dataset's speckle noise.
3. Autocontrast with a 1% cutoff.
4. Add a 20 px white border.

Tesseract's default page segmentation (`--psm 3`) is used.

### Variants tried (all 100 images, micro character accuracy)

| Preprocessing | Page mode | Accuracy | Exact |
|---|---|---|---|
| none (grayscale only) | 7 (single line) | 0.644 | 49 |
| none | 3 (default) | 0.955 | 85 |
| median 3 | 7 | 0.732 | 64 |
| median 3, upscale 2× | 7 | 0.659 | 54 |
| median 5, upscale 2×, border 20 | 7 | 0.827 | 75 |
| median 3, upscale 2× | 3 | 0.990 | 93 |
| median 5, upscale 2×, border 20, binarized at 160 | 7 | 0.909 | 74 |
| median 3 | 3 | 0.994 | 95 |
| median 5 | 3 | 0.984 | 91 |
| median 3, border 20 | 3 | **0.995** | **96** |

Single-line mode and upscaling hurt on this dataset; the chosen variant is also the cheapest of the strong ones.

## Evaluation

Ground truth is the `word` column of `local-assets/dataset/labels.txt` (filename to word). The evaluator passes only the image to the recognizer and uses the label afterwards for scoring; labels never influence recognition or retries.

- **Normalization:** NFKC, casefold, keep letters and digits only.
- **Metric:** micro-averaged character accuracy, `1 − Σ edit distance ÷ Σ expected characters` (Levenshtein: insertions, deletions, substitutions). An image whose recognition fails is scored against empty text.
- **Criterion:** accuracy ≥ 0.5 (at least half the characters recognized).

Result of the committed configuration on Windows, Python 3.11, Tesseract 5.4.0: **0.9952** character accuracy, 96 of 100 exact matches, no recognition failures. Misses: `fireproof`→`fireprocof`, `elision`→`clision`, `rotan`→`fotan`, `boraginaceae`→`boraginacæe`.

## Repeat the work

```powershell
just recognize local-assets/dataset/images/img0001.png   # one real image
just evaluate                                            # all 100 images, exit 0 when accuracy >= 0.5
just test                                                # behavioral tests (real-OCR tests skip without Tesseract and the model)
```

`just evaluate --verbose` lists every image. Both commands accept `--executable`, `--tessdata-dir`, and `--timeout`.

## Python 3.15.0

The project now targets Python 3.15. The accuracy result above was measured on Python 3.11; rerun the real OCR evaluation on Python 3.15 before treating that result as verified for the current target.
