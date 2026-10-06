# Team handoff

This note is prepared for Quirora to share with Imman. No message or invitation has been sent.

## Accepted ownership split

- **Quirora:** image preprocessing, Tesseract integration, and recognition-quality evaluation against the supplied labels.
- **Imman:** configuration loading, image loading, shared-queue coordination, worker lifecycle, result collection, and CSV output.
- **Both:** agree on the concurrency and shutdown design, integrate the two parts, compare benchmark results, and prepare the course presentation and submission artifacts.

The ownership split leaves both students with substantial implementation work while preserving a clean integration boundary: the OCR side accepts one loaded image and returns text; the pipeline side owns scheduling, identity, timing, aggregation, and output. See [`ocr-contract.md`](ocr-contract.md).

## Next steps

1. Both teammates set up the same Python 3.11 lockfile and prepare matching local dataset and model files. Run `just check-environment` on each machine.
2. Agree on the worker backend, shared queue, synchronization, cancellation, and clean shutdown in [issue #3](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/3).
3. Quirora implements and evaluates the standalone image recognizer in [issue #4](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/4).
4. Imman implements the configured parallel pipeline in [issue #5](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/5), using the agreed design and the OCR contract.
5. Integrate, verify real recognition and failure behavior, benchmark comparable worker counts, and prepare the CSV and slides in the later validation and submission issues.

The scaffold intentionally contains no working recognizer, config parser, loader, worker pool, output writer, or benchmark command. Add each when its owner starts the corresponding implementation.
