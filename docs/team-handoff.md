# Team handoff

This note is prepared for Quirora to share with Imman. No message or invitation has been sent.

## Accepted ownership split

- **Quirora:** image preprocessing, Tesseract integration, and recognition-quality evaluation against the supplied labels.
- **Imman:** configuration loading, image loading, shared-queue coordination, worker lifecycle, result collection, and CSV output.
- **Both:** agree on the concurrency and shutdown design, integrate the two parts, compare benchmark results, and prepare the course presentation and submission artifacts.

The ownership split leaves both students with substantial implementation work while preserving a clean integration boundary: the OCR side accepts one loaded image and returns text; the pipeline side owns scheduling, identity, timing, aggregation, and output. See [`ocr-contract.md`](ocr-contract.md).

## Next steps

1. Both teammates set up the same Python 3.15 lockfile and prepare matching local dataset and model files. Run `just check-environment` on each machine.
2. Follow the accepted [concurrency and shutdown design](concurrency-design.md) from [issue #3](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/3): threads, bounded `queue.Queue`, locked CSV writes, bounded per-image recovery, and distinguishable partial output.
3. The standalone recognizer and configured pipeline are implemented. Use `just evaluate` for recognition quality, `just pipeline` for a configured run, and `just benchmark` for the repeatable worker-count comparison.
4. Quirora should run `just check-environment`, `just verify`, `just evaluate`, and `just benchmark` on their Windows machine. Record the machine-specific OCR and benchmark results in [benchmark results](benchmark-results.md); results from Imman's machine do not establish performance on Quirora's host.
5. Close the remaining acceptance-test gaps: explicitly exercise cancellation while the queue is full, and score a complete pipeline-produced CSV against the labels using the documented metric. Preserve the current successful output while testing failed reruns.
6. Complete the benchmark record with dependency versions and recovery activity, and discuss variability and likely bottlenecks with both teammates. Confirm that the measured gain and worker-count recommendation are defensible for each machine.
7. Jointly prepare and review the submission artifacts: a clean source ZIP, a verified complete 100-image CSV, and the PowerPoint covering the design, recovery/shutdown behavior, and benchmark evidence. Keep the November 5, 2026, 10:00 AM Asia/Manila submission deadline in view; coursework submission remains a human action.
8. Do not merge `issue-5` into `main` until Quirora has tested the branch on their machine and the outstanding integration checks have been reviewed. If any compatibility or correctness concern remains, leave the branch unmerged for collaborator testing.

The accepted implementation boundaries and failure behavior remain in the [OCR contract](ocr-contract.md) and [concurrency design](concurrency-design.md).
