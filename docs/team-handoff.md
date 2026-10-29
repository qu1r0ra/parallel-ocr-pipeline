# Team handoff

This note records the accepted ownership split and current submission status.

## Accepted ownership split

- **Quirora:** image preprocessing, Tesseract integration, and recognition-quality evaluation against the supplied labels.
- **Imman:** configuration loading, image loading, shared-queue coordination, worker lifecycle, result collection, and CSV output.
- **Both:** agree on the concurrency and shutdown design, integrate the two parts, and explain the shared design. Quirora's machine supplies the submitted benchmark results; Imman confirmed the pipeline works on his Windows machine and agreed to use those results.

The ownership split leaves both students with substantial implementation work while preserving a clean integration boundary: the OCR side accepts one loaded image and returns text; the pipeline side owns scheduling, identity, timing, aggregation, and output. See [`ocr-contract.md`](ocr-contract.md).

## Next steps

1. Use the shared Python 3.15 lockfile and keep local copies of the dataset and supplied model. Imman confirmed the integrated pipeline works on his Windows machine. A separate benchmark sweep on his machine is not required; the report uses Quirora's repeated measurements.
2. The issue #5 pipeline is merged to `main`. Use `just evaluate` for standalone recognition, `just pipeline` for a configured run, and `just evaluate-pipeline` to score a complete pipeline CSV with the same metric.
3. [Issue #6](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/6) is validated on Quirora's Windows machine, and Imman confirmed the integrated pipeline works on his Windows machine. The [local integration evidence](integrated-validation.md) records Quirora's acceptance run; no further collaborator validation is pending.
4. The repeated worker-count measurements and recovery metadata are recorded in [benchmark results](benchmark-results.md). The report recommends four workers for Quirora's measured host and explains variability and bottlenecks.
5. The clean source ZIP and verified complete 100-image CSV are prepared and accepted by Imman. Prepare the Canva presentation covering the design, recovery/shutdown behavior, and benchmark evidence. Keep the November 5, 2026, 10:00 AM Asia/Manila deadline in view; coursework submission remains a human action.

The accepted implementation boundaries and failure behavior remain in the [OCR contract](ocr-contract.md) and [concurrency design](concurrency-design.md).
