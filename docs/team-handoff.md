# Team handoff

This note records the MP1 ownership split and phase status. The owner has confirmed that MP1 deliverables were submitted; older pre-submission notes in historical validation and benchmark records do not indicate outstanding submission work.

## Accepted MP1 ownership split

- **Quirora:** image preprocessing, Tesseract integration, and recognition-quality evaluation against the supplied labels.
- **Imman:** configuration loading, image loading, shared-queue coordination, worker lifecycle, result collection, and CSV output.
- **Both:** agree on the concurrency and shutdown design, integrate the two parts, and explain the shared design. Quirora's machine supplies the benchmark evidence; Imman confirmed the integrated pipeline works on his Windows machine.

The OCR side accepts one loaded image and returns text. The pipeline side owns scheduling, identity, timing, aggregation, and output. See [`ocr-contract.md`](ocr-contract.md).

## MP1 status

- The issue #5 pipeline is merged to `main`. Use `just evaluate` for standalone recognition, `just pipeline` for a configured run, and `just evaluate-pipeline` to score a complete pipeline CSV with the same metric.
- Issue #6 is validated on Quirora's Windows machine, and Imman confirmed the integrated pipeline works on his Windows machine. The [local integration evidence](integrated-validation.md) records Quirora's acceptance run.
- The full 1–32 worker sweep, machine details, analysis, and chart are recorded in [benchmark results](benchmark-results.md). Eleven workers had the lowest measured median on Quirora's AMD Ryzen 5 5600X (6 physical cores / 12 logical processors); `config.txt` uses 11 for this host.
- The supplied PowerPoint has slides 6 and 7 updated with the new chart and current benchmark, correctness, recovery, and setup details.
- A source-only ZIP, the fresh 11-worker output CSV, and the PowerPoint were collated as separate local deliverables. The owner subsequently confirmed submission. Course inputs remain local.

The accepted implementation boundaries and failure behavior remain in the [OCR contract](ocr-contract.md) and [concurrency design](concurrency-design.md).

## MP2 handoff

The agreed design, responsibilities, and live dependency map are in [spec #22](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/22). The partners reviewed the shared contract and agreed to the split: Imman leads master recovery (#24); Quirora leads workers and deployment (#25) and local resource-dependent validation. Both contribute to integration, benchmarking, and deliverables. The MP1 split above is historical.

Issues #23 to #26 are done; their live state is on GitHub. Evidence: stopped-worker recovery in [cluster acceptance](cluster-acceptance.md), and local container benchmarking (#27) in [benchmark results](benchmark-results.md#mp2-cluster-benchmark-ticket-27) (linear 1 to 16 sweeps on the Ubuntu laptop; best measured configuration 1 worker node × 8 processes, 2.088 s window). Cloud evidence is a separate dataset in [benchmark results](benchmark-results.md#mp2-cloud-benchmark-ticket-44) (3 LXC containers; best measured configuration 2 worker nodes × 2 processes, 2.327 s window).

### Remaining #27 work

- **Code freeze:** `main` at `6575099` is the evidence commit; the cloud sweep, fault runs, and recorded demo ran on this code. Land only tests and docs. A change to `src/` or `scripts/` voids that evidence: re-run the affected runs and re-record before the deadline.
- **Cloud runs (done):** 3 LXC containers (1 master, 2 workers), its own dataset; operate it with [cloud containers](cloud-containers.md) (`just benchmark-cloud`). The fault demo is recorded (hard-stop of one worker, master requeues its image after the 90 s deadline) and results and recording are copied off the containers to the owner's PC; the containers expire 2026-12-20.
- **Deck (assigned to the owner's groupmate):** the deck is the presentation, presented live with the demo clip embedded. The owner supplies a trimmed clip, chart PNGs, and a numbers README through the shared Drive folder. Sections needed: overview, distribution, synchronization, recovery evidence ([cluster acceptance](cluster-acceptance.md)), and benchmarking.
- **Submission (human action):** commit everything, then run `just package-submission --csv <output.csv> --deck <deck.pptx>`. Submit a cloud 2 nodes × 2 processes run CSV (100 rows, accuracy 0.9964). It builds the source-only ZIP from `HEAD`, rejects environments, secrets, course inputs, models, and run outputs, scores the CSV, and requires the deck. The handout asks for ZIP, CSV, and PPT only; no video.

Use the [MP2 development guide](agents/mp2-development.md) for contributor entry points and the live issues for current status.
