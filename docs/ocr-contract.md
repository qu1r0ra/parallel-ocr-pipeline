# OCR and pipeline contract

This contract lets image recognition and pipeline work proceed independently. [`ImageRecognizer`](../src/parallel_ocr_pipeline/contracts.py) is a typing protocol, not an OCR implementation.

## Boundary

The recognizer accepts an already-loaded in-memory Pillow image and returns recognized text as a string. It performs preprocessing and Tesseract inference. It does not open image files, select work, assign output IDs, measure queue wait, aggregate results, or write CSV. A standalone harness may pass one image directly; it does not need the production pipeline.

The recognizer uses `pytesseract` to invoke the native Tesseract executable and passes the explicit `--tessdata-dir` option for `local-assets/models`. Preprocessing choices belong to the OCR implementation and should be evaluated against the supplied labels.

## Image lifecycle

The loader opens each file, fully loads and detaches its image data, and transfers ownership through the queue to the worker. For example, it can copy the opened image before leaving the file context and call `load()` before enqueueing it. The loader closes an image if enqueueing fails; the worker owns and closes a dequeued image after recognition, including on failure or cancellation. The recognizer preserves the caller-owned input across retry attempts and does not close it; it closes temporary derived images that it creates.

This avoids queueing a lazy file-backed Pillow image after its source file has been closed. It also gives each worker one clear owner for its current image.

## Failure behavior

The recognizer returns text on success and raises an exception on recognition failure. It must not convert a failure into successful empty text. A legitimate empty OCR result is successful inference. The pipeline allows one additional attempt for known transient recognition failures, records terminal failures, and continues other images. It publishes a complete CSV only when every input succeeds; otherwise it preserves successful rows as partial output and reports failures separately. Global errors and cancellation stop further processing. See the accepted [concurrency and shutdown design](concurrency-design.md).

## Identity, output, and timing

Use deterministic filename order to assign sequential IDs before work begins. Completion order may vary; each result retains its assigned ID and filename. A complete successful CSV has one header and exactly one row for every input, with escaped text and time in milliseconds. Incomplete runs use a distinct partial filename and failure report. The pipeline owns result aggregation and locked CSV writing.

Per-image processing time covers preprocessing and all OCR attempts after dequeue and excludes loading, queue wait, and output-lock wait. Use a monotonic high-resolution clock. End-to-end timing starts immediately before thread startup/loading and stops after all threads finish, streams close, and output is published. Report speedup as the one-worker total elapsed time divided by the corresponding multiworker total elapsed time, using complete successful runs with the same workload, recovery policy, and boundaries.

## Configuration and agreed coordination

The future pipeline reads `image_dir` and `n_workers` from `config.txt`; `n_workers` excludes the loader. [`config.example.txt`](../config.example.txt) shows the agreed shape.

Use only Python standard-library concurrency and synchronization: explicitly created threads, a bounded `queue.Queue`, an output `Lock`, and an `Event` for global stopping. The accepted design targets Python 3.15.0; the current Python 3.11 scaffold must be migrated before using `Queue.shutdown()`.
