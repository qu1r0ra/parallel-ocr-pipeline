# Team handoff

This note is prepared for Quirora to share with Imman. No message or invitation has been sent.

## Accepted ownership split

- **Quirora:** image preprocessing, Tesseract integration, and recognition-quality evaluation against the supplied labels.
- **Imman:** configuration loading, image loading, shared-queue coordination, worker lifecycle, result collection, and CSV output.
- **Both:** agree on the concurrency and shutdown design, integrate the two parts, compare benchmark results, and prepare the course presentation and submission artifacts.

The ownership split leaves both students with substantial implementation work while preserving a clean integration boundary: the OCR side accepts one loaded image and returns text; the pipeline side owns scheduling, identity, timing, aggregation, and output. See [`ocr-contract.md`](ocr-contract.md).

## Next steps

1. Both teammates use the shared Python 3.15 lockfile and keep local copies of the dataset and supplied model. Run `just check-environment` and `just verify` on each Windows machine.
2. The issue #5 pipeline is merged to `main`. Use `just evaluate` for standalone recognition, `just pipeline` for a configured run, and `just evaluate-pipeline` to score a complete pipeline CSV with the same metric.
3. Finish [issue #6](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/6) by recording the collaborator's standalone and pipeline scores and reviewing setup or OCR differences against the [local integration evidence](integrated-validation.md).
4. Then complete the repeated worker-count measurements and recovery metadata in [benchmark results](benchmark-results.md). Discuss variability and bottlenecks with both teammates and agree on a defensible worker-count recommendation.
5. Jointly prepare and review the submission artifacts: a clean source ZIP, a verified complete 100-image CSV, and the PowerPoint covering the design, recovery/shutdown behavior, and benchmark evidence. Keep the November 5, 2026, 10:00 AM Asia/Manila deadline in view; coursework submission remains a human action.

The accepted implementation boundaries and failure behavior remain in the [OCR contract](ocr-contract.md) and [concurrency design](concurrency-design.md).
