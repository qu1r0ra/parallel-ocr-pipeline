# Plan and scaffold the parallel OCR pipeline for pair development

The project plan and testing seams are confirmed.

## Problem Statement

Two students must implement and explain a parallel OCR pipeline for CSC611M Machine Project 1. The initiating teammate needs to prepare the repository so both teammates can contribute independently, without consuming the substantive implementation work intended for Imman. Both teammates use native Windows.

The assignment requires a Python program with one image loader, a shared image queue, and explicitly created workers that each preprocess an image and perform OCR. Correct synchronization, complete output, clean termination, and demonstrated performance gain matter more than sophisticated recognition. The students also need an output CSV and a slide deck explaining their design and measurements.

The repository currently contains a short README and Python ignore rules. Repository-local agent guidance now selects GitHub Issues, the default triage vocabulary, and single-context domain documentation. The supplied project handout, dataset archive, and fast English Tesseract model are present locally but are untracked. No pipeline or OCR implementation exists yet.

## Solution

Prepare a small, reproducible Windows development environment and a documented collaboration contract. The initiating teammate owns image preprocessing, Tesseract integration, and recognition-quality evaluation. Imman owns configuration, the loader, shared-queue coordination, worker lifecycle, result collection, and CSV output. Both teammates plan the concurrency design, with Imman owning its implementation. Integration, benchmarking, speedup analysis, and the slide deck are joint work.

The preparation phase establishes tooling, package structure, sample configuration, local asset preparation, an environment check, requirements, interfaces, acceptance criteria, benchmark guidance, and a handoff note. It leaves the substantive OCR and pipeline implementations for their respective owners. The initiating teammate's standalone OCR module is their first subsequent implementation task.

The completed course application must:

- Read `config.txt` at startup, accepting `image_dir` and `n_workers`; the worker count excludes the loader.
- Use one loader to load images into a shared queue. Each remaining worker takes an image, preprocesses it, and performs OCR.
- Use only Python's standard library for concurrency and synchronization. OCR and image-processing libraries may be third-party.
- Produce one `ocr_results.csv` with a sequential integer ID, image filename, extracted text, and per-image processing time in milliseconds.
- Finish after all images have been processed and terminate every worker cleanly.
- Recognize at least half of the dataset's characters, with evidence from comparison against the supplied ground-truth labels.
- Benchmark different worker counts, calculate speedup as one-worker total time divided by the corresponding multiworker total time, and identify the best measured configuration.
- Deliver a source-code ZIP, the output CSV, and a PowerPoint file.

## User Stories

1. As the initiating teammate, I want a prepared repository, so that Imman can begin substantive work without repeating setup research.
2. As a student developer, I want native Windows instructions, so that the supported environment matches both teammates' machines.
3. As a student developer, I want an isolated Python environment and committed dependency lockfile, so that both machines resolve the same project dependencies.
4. As a student developer, I want familiar task commands, so that setup, formatting, linting, and verification are easy to discover and repeat.
5. As a student developer, I want fast formatting and lint checks at commit time, so that avoidable style differences do not complicate collaboration.
6. As a student developer, I want non-mutating quality checks, so that I can verify a contribution before requesting review.
7. As a student developer, I want a small Python package layout, so that project code is separate from development tools and generated outputs.
8. As a student developer, I want an environment check for the OCR prerequisites, so that missing executables, model files, or dependencies produce useful setup guidance.
9. As a student developer, I want local asset preparation instructions, so that I can use the supplied dataset and English model without publishing them.
10. As a student developer, I want the source images distinguished from archive metadata and labels, so that only actual images enter the OCR workload.
11. As the OCR implementation owner, I want an image-to-text interface, so that I can develop preprocessing and recognition before the parallel pipeline is implemented.
12. As the OCR implementation owner, I want ground-truth labels, so that preprocessing decisions can be evaluated against recognition evidence.
13. As the pipeline implementation owner, I want a simple substitute recognizer, so that I can validate scheduling, output, and termination independently of real OCR.
14. As a teammate, I want explicit image ownership and error-handling rules, so that integration does not introduce resource leaks or silently omit work.
15. As a teammate, I want responsibilities recorded as a proposal accepted by both students, so that each person has substantial and explainable implementation work.
16. As Imman, I want to own the pipeline's concurrency implementation, so that my contribution directly applies the course's synchronization concepts.
17. As a teammate, I want to plan the concurrency design together, so that both students can explain the worker and shared-resource behavior.
18. As an application user, I want the image directory and worker count read from configuration, so that I can run experiments without modifying implementation code.
19. As an application user, I want every valid input image represented exactly once in the output, so that parallel execution does not lose or duplicate work.
20. As an application user, I want correctly escaped CSV text and millisecond timings, so that the output remains usable when OCR returns punctuation or newlines.
21. As an application user, I want the program and all workers to finish cleanly, so that a completed run leaves no hanging execution.
22. As a student developer, I want invalid configuration and image or OCR failures to be visible, so that a partial run cannot be mistaken for a successful complete run.
23. As a benchmarking teammate, I want measurements at one and multiple worker counts on the same workload, so that reported speedup is based on comparable runs.
24. As a benchmarking teammate, I want the measured machine and software settings recorded, so that the results and optimal configuration have a clear scope.
25. As a presenting teammate, I want diagrams and explanations of shared state, synchronization, and termination, so that the design can be explained during assessment.
26. As a submitting teammate, I want a complete source ZIP, CSV, and slide deck before the deadline, so that submission preparation does not become a last-minute integration task.
27. As a collaborator, I want GitHub issues with clear acceptance criteria and responsibilities, so that the shared work and its prerequisites are visible.
28. As a public-repository reader, I want an original project requirements summary, so that I can understand the work without needing the instructor's original files.

## Implementation Decisions

- **Preparation scope.** Scaffold and document first. Completing repository preparation does not mean that OCR, configuration parsing, loading, synchronization, or CSV output has been implemented. The substantive student implementations are subsequent work.
- **Ownership.** The initiating teammate owns preprocessing, Tesseract integration, and quality evaluation. Imman owns the pipeline and synchronization implementation. Both plan the concurrency design and review integration and benchmark results.
- **Concurrency selection.** Threads versus processes and the specific standard-library coordination constructs are deliberately reserved for the joint design task. The spec requires explicitly created workers and the prescribed shared queue but does not select a worker backend on Imman's behalf.
- **OCR selection.** Use Tesseract with the supplied fast English model. Use Pillow for image handling and pytesseract for the Python-to-Tesseract integration. Preprocessing techniques are chosen and evaluated during the OCR implementation task. pytesseract accepts an in-memory Pillow image and returns text; Windows setup must distinguish the Python dependency, Tesseract executable, and model directory. See the [pytesseract documentation](https://github.com/madmaze/pytesseract/blob/master/README.rst).
- **OCR interface.** The OCR module accepts an already-loaded in-memory image and returns extracted text. It performs preprocessing and inference, while the pipeline owns scheduling, identity, timing, result aggregation, and output. A standalone development harness can supply one image directly; the production pipeline is not a prerequisite for OCR development.
- **Image lifecycle.** The loader must finish reading image data and detach it from the source file before handing it to a worker. The receiving worker owns that job's image until recognition finishes and releases its resources. The recognizer may create temporary derived images but does not take responsibility for closing the caller's input image. This avoids passing a lazy file-backed image whose source has already closed. See [Pillow's image lifecycle documentation](https://github.com/python-pillow/Pillow/blob/main/docs/reference/open_files.rst).
- **Failure contract.** Recognition failures are reported to the caller rather than converted into successful empty text. The pipeline must make failures visible, coordinate shutdown, and never report an incomplete run as complete. The exact recovery and cancellation protocol belongs to the joint concurrency design.
- **Output identity.** Assign sequential IDs from a deterministic filename ordering. Completion order may vary, but each successful result retains its assigned ID and filename. The output contains one row per processed input and a header; the pipeline owns CSV escaping and writing.
- **Timing.** Per-image processing time covers preprocessing and inference, excluding time waiting in the image queue. Benchmark speedup uses total elapsed processing time for the full workload, rather than the sum of per-image timings. Document the total-run timer boundaries and apply them consistently to every worker count.
- **Tooling.** Carry over uv, just with PowerShell-compatible recipes, Ruff, basedpyright, pre-commit, the source-package layout, and LF text endings from the initiating teammate's reference project. Use Python 3.11 as the initial common interpreter target and lock the resolved dependencies. Keep development tools separate from application dependencies and use an independent project environment.
- **Reproducibility.** Generate and commit the dependency lockfile. Verification must reject stale dependency metadata; uv's locked mode checks freshness, while frozen mode trusts an existing lockfile without checking freshness. See [uv's locking and syncing documentation](https://github.com/astral-sh/uv/blob/main/docs/concepts/projects/sync.md).
- **Scaffold commands.** Provide discoverable setup, asset preparation, environment checking, formatting, linting, and verification tasks. Add application and benchmark commands when those implementations exist; scaffolding must not present a placeholder command as a working OCR pipeline.
- **Quality gates.** Use Ruff formatting and linting plus standard-mode basedpyright checks. Commit hooks run the fast fixers; full verification is non-mutating. Include automated repository quality checks, keeping real OCR and performance evidence separate from lightweight tooling checks.
- **Assets and publication.** Keep the repository public. Publish an original requirements summary and project planning documents. Keep the instructor's original PDF, supplied archive, model file, extracted dataset, and generated run outputs local by default. Onboarding describes how both students provide matching local assets.
- **Collaboration.** Track work in this repository's GitHub Issues using the configured default triage labels. Prepare a handoff note for the user to share with Imman. Do not send a message or invitation to Imman automatically. Resolve the coarse implementation tickets separately from this spec publication.

## Testing Decisions

The user confirmed the following test seams before publication.

- **Primary seam: the complete application.** Exercise the public program with an input directory and configuration, then inspect its exit status, output CSV, and termination. Use bounded execution to catch hangs. Favor externally observable results over assertions about private queue operations, locks, helper methods, or module layout.
- **Independent seam: image to text.** Exercise the OCR module directly with an in-memory image. This is the collaboration interface already needed for independent development, rather than a new testing-only abstraction. Check that text is returned, failures are exposed, and caller-owned image resources follow the documented lifecycle.
- **Pipeline isolation.** Use a deterministic substitute recognizer through the same image-to-text interface to verify complete output, unique IDs, filename association, CSV escaping, behavior with one and multiple workers, observable overlapping work, and clean termination without depending on Tesseract accuracy or duration. The substitute must be compatible with the worker backend selected during the joint design.
- **Adverse outcomes.** Exercise malformed or missing configuration, an invalid worker count, missing or empty image directories, unreadable images, and recognition failures. Require a documented observable outcome and bounded termination. Empty-directory behavior and per-image failure recovery are finalized in the pipeline design task, rather than silently assumed by tests.
- **Real recognition acceptance.** Evaluate the real OCR module on the supplied 100 images and compare results against the supplied filename-to-word labels. Document the character-level metric and normalization rules used to substantiate the handout's at-least-half recognition requirement. Ground truth is evaluation input, not input to recognition. The handout does not prescribe an exact scoring formula.
- **Performance evidence.** Compare repeated full-workload measurements at one and multiple worker counts using the same dataset, model, preprocessing, machine, and timer boundaries. Record worker count, total elapsed time, speedup, software versions, and relevant native OCR concurrency settings. Use measurements to identify the best configuration on the tested machine. Avoid fragile speed thresholds in ordinary automated tests.
- **Scaffold verification.** Verify environment preparation, package importability, asset instructions, task discoverability, formatting, linting, and type checking. Write behavioral tests for substantive correctness as implementations arrive; do not add tests that merely repeat scaffolding text or certify placeholders.
- **Prior art.** This repository has no application or tests yet. The reference project's quality gates and separation of source, tooling, and tests inform the scaffold, but its native-code tests and publication-scale benchmark machinery are not copied into this small OCR project.

## Out of Scope

- Implementing the substantive OCR or parallel pipeline during the preparation phase.
- Selecting threads versus processes or completing Imman's synchronization design before the joint design task.
- Comparing multiple OCR engines, training a recognition model, or pursuing high accuracy beyond the course requirement.
- Third-party concurrency or synchronization frameworks.
- A web interface, hosted service, GPU OCR pipeline, distributed system, or platform migration to WSL/Linux.
- Reproducing the reference project's CUDA/native toolchain or research-publication infrastructure.
- Publishing the instructor's original handout, supplied dataset, or supplied model as part of the current repository preparation.
- Automatically contacting Imman, changing repository visibility, or submitting coursework.
- Creating the implementation-ticket breakdown or implementing future tickets as part of this spec-publication operation.

## Further Notes

- **Requirement authority:** the instructor's CSC611M Machine Project 1: Parallel OCR Pipeline handout. The user separately supplied the submission-page deadline: November 5, 2026, at 10:00 AM Asia/Manila.
- **Rubric:** synchronization is 50%, parallel techniques 40%, and technical documentation 10%. The expected result includes complete output, safe shared-resource coordination, clean worker termination, varying-worker benchmarks, and demonstrated performance gain.
- **Available assets:** the local archive contains 100 PNG images, a filename-to-word labels file, and macOS archive metadata. The English fast model is already downloaded. Metadata and the labels file are excluded from the image workload.
- **Course context:** recent classes covered producer-consumer bounded buffers, semaphores, monitors, condition variables, and predicate rechecking. These inform discussion and explanation but do not require a specific synchronization construct beyond the handout's standard-library constraint.
- **Internal milestones:** integrated pipeline by October 22; measurements complete by October 29; submission-ready artifacts by November 3. The submission deadline remains November 5 at 10:00 AM.
- **Planned work areas:** joint concurrency design; the initiating teammate's OCR module; Imman's pipeline; integration and validation; benchmarking and submission preparation. These are coarse work areas, not implementation tickets published by this spec operation.
- **Choices reserved for implementation:** worker backend and coordination protocol are chosen jointly with Imman owning implementation; preprocessing and the documented recognition metric belong to OCR work; concrete worker-count sweep and repetition settings belong to benchmarking. These reserved choices do not block preparing the repository or developing the OCR module independently.
- **Success of preparation:** both teammates can set up the project on Windows, locate and prepare their local assets, run the repository quality and environment checks, understand the shared interface, and identify their next substantive implementation task.

### Approved execution map

- **Batch 1:** [#2 Prepare Windows development and handoff](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/2), [#3 Agree the concurrency and shutdown design](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/3) (parallel candidates; neither has blockers).
- **Batch 2:** [#4 Recognize and evaluate images independently](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/4) (blocked by #2), [#5 Process configured images with synchronized workers](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/5) (blocked by #2 and #3) (parallel candidates with separate implementation owners).
- **Batch 3:** [#6 Validate the integrated OCR application](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/6) (blocked by #4 and #5).
- **Batch 4:** [#7 Benchmark and prepare submission](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/7) (blocked by #6).
