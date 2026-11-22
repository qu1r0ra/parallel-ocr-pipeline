# MP2 development

The authoritative implementation design is [Build the MP2 distributed OCR pipeline (#22)](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/22). Read its full body and the relevant approved child ticket before implementation or review. The parent owns the accepted architecture, recovery and output behavior, testing boundary, scope, and deferred experimental choices. Use its approved execution map and native issue relationships for blockers and work order.

For course requirements, use the [MP2 handout summary](../requirements-mp2.md). Keep assignment requirements distinct from implementation choices recorded in the spec.

## Relationship to MP1

The [MP1 spec](../project-spec.md), [concurrency design](../concurrency-design.md), and [OCR contract](../ocr-contract.md) record the accepted single-machine baseline. Preserve that application's behavior. Their thread-only pipeline, shared in-memory image transfer, Windows-only task assumptions, and measured worker optimum do not prescribe MP2 behavior.

Reuse the image-to-text recognition boundary, recognition evaluation, deterministic identity, and visible failure outputs where the MP2 spec carries them forward. Resolve distributed ownership, timing, transport, process startup, and shutdown through the MP2 spec rather than silently copying MP1 coordination rules.

## Work and evidence

Use the live parent and child issues for implementation state and dependencies. Distinguish the successful local container run from integrated recovery and cloud evidence. Discover executable commands from the current task definitions; add operator instructions with the implementation that makes them work.

Use the [team handoff](../team-handoff.md) for phase context. Benchmark datasets and ranges follow [Benchmark evidence](#benchmark-evidence); cloud provisioning remains deferred as recorded in the spec.

## Container host

The owner's Windows PC cannot start Docker Desktop (no virtualization), so every Docker or Compose workflow, including the #26 acceptance and stopped-worker demonstration, runs on the Ubuntu IdeaPad, linked as T3 environment `qu1r0ra-ideapad-ubuntu` (pass its `environmentId` to T3 tools).

1. Edit and run `just verify` in a task worktree on either machine.
2. Commit and push the task branch; Git carries code to the laptop.
3. On the laptop, check out that pushed commit, then run the container workflow there. Course inputs (`.env`, dataset, model) stay local to the laptop.

Completion: container evidence records the laptop's hostname and the commit SHA it ran. If the environment reports unreachable, ask the owner to bring the laptop online.

## Benchmark evidence

Two datasets answer different questions; report each in its own table in [benchmark results](../benchmark-results.md) and never merge them.

- **Local container** (IdeaPad; every container shares 8 logical CPUs): node counts 1 to 16 at 1 process per node, and process counts 1 to 16 at 1 and 2 worker nodes, 1 to 10 at 3. It measures design overhead and contention, not multi-machine scaling.
- **Cloud** (3 VMs: 1 master, 2 workers): node scaling is one matched pair, 1 active worker (the other VM idle) against 2. Process sweeps run at both. Node count cannot exceed 2, so the process sweeps carry most of this dataset.

The master admits at most `MAX_ACTIVE_WORKERS` (32) worker processes cluster-wide, so `nodes × procs` above 32 is rejected; the runner skips those settings and reports each skip. The local sweep also fails 13 or more simultaneous container starts when Docker DNS misses a lookup, because workers do not retry their first connection; a failed sample is invalid and stays in `invalid_samples`.

Run both with `just benchmark-cluster` on the host that owns the cluster. Completion: each table names its host, commit, container or VM resources, and states what the data cannot show.
