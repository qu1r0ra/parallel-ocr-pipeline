# OCR and pipeline contract

This contract lets image recognition and pipeline work proceed independently. [`ImageRecognizer`](../src/parallel_ocr_pipeline/contracts.py) is a typing protocol, not an OCR implementation.

## Boundary

The recognizer accepts an already-loaded in-memory Pillow image and returns recognized text as a string. It performs preprocessing and Tesseract inference. It does not open image files, select work, assign output IDs, measure queue wait, aggregate results, or write CSV. A standalone harness may pass one image directly; it does not need the production pipeline.

The recognizer uses `pytesseract` to invoke the native Tesseract executable and passes the explicit `--tessdata-dir` option for `local-assets/models`. Preprocessing choices belong to the OCR implementation and should be evaluated against the supplied labels.

## Image lifecycle

The loader opens each file, fully loads and detaches its image data, and transfers ownership of that image to the worker. For example, it can copy the opened image before leaving the file context and call `load()` before enqueueing it. The worker owns and closes the image after recognition, including on failure. The recognizer does not close the caller-owned input image; it closes temporary derived images that it creates.

This avoids queueing a lazy file-backed Pillow image after its source file has been closed. It also gives each worker one clear owner for its current image.

## Failure behavior

The recognizer returns text on success and raises an exception on recognition failure. It must not convert a failure into successful empty text. The pipeline makes failures visible and must not report a partial run as complete. The joint concurrency design decides how workers coordinate cancellation, shutdown, and failure reporting.

## Identity, output, and timing

Use deterministic filename order to assign sequential IDs before work begins. Completion order may vary; each result retains its assigned ID and filename. The final CSV has one header and one row for every successfully processed input, with escaped text and time in milliseconds. The pipeline owns result aggregation and CSV writing.

Per-image processing time covers preprocessing and OCR after dequeue and excludes time waiting in the queue. Use a monotonic high-resolution clock. End-to-end timing starts immediately before loading begins and stops after all workers finish and the CSV is closed. Report speedup as the one-worker total elapsed time divided by the corresponding multiworker total elapsed time, using the same workload and boundaries.

## Configuration and decisions left for the team

The future pipeline reads `image_dir` and `n_workers` from `config.txt`; `n_workers` excludes the loader. [`config.example.txt`](../config.example.txt) shows the agreed shape.

Use only Python standard-library concurrency and synchronization. Threads versus processes and the coordination protocol remain for the joint design discussion; this scaffold selects neither.
