# CSC611M Machine Project 1: requirements summary

This is an original summary of the local course handout, prepared so contributors can understand the assignment without publishing the instructor's PDF. The supplied handout remains under `local-assets/supplied/` and is ignored by Git.

## Required application

Build a Python program that reads image-directory and worker-count settings from `config.txt`. One loader loads the images into a shared queue. The remaining explicitly created workers each preprocess an image, run OCR, and contribute a result. The worker count excludes the loader. Python's standard library must provide concurrency and synchronization; image and OCR dependencies may be third-party.

Write a single `ocr_results.csv` with a header and one row per image. Each row contains a sequential integer ID, image filename, extracted text, and image processing time in milliseconds. The program must finish after all images are processed and every worker must terminate cleanly.

## Recognition and performance

The project must recognize at least half of the characters in the supplied dataset, supported by comparison with its filename-to-word ground-truth labels. Labels are for evaluation and must not be sent to the recognizer. Document the character metric and its normalization rules.

Measure the same full workload at one and multiple worker counts. Calculate speedup as:

```text
speedup(n) = total elapsed time with 1 worker / total elapsed time with n workers
```

Record the tested machine, software versions, worker count, total runtime, and relevant native OCR concurrency settings. Use repeated comparable runs to identify the best measured configuration; do not treat the per-image timing sum as total runtime when workers overlap.

The implementation plan defines per-image processing time as preprocessing plus OCR after a worker dequeues an image, excluding queue wait. For comparable end-to-end runs, begin timing immediately before loading starts and stop after all workers have finished and the CSV has been closed. Keep these boundaries constant across worker counts.

## Submission and grading

The final course submission consists of a source-code ZIP, the output CSV, and a PowerPoint presentation. The presentation explains the pipeline, parallelization, synchronization, and benchmark results.

The rubric assigns 50% to synchronization, 40% to parallel techniques, and 10% to technical documentation. Complete output, correct coordination, clean termination, demonstrated performance gain, and a clear explanation of the design are central requirements.
