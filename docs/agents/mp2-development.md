# MP2 development

The authoritative implementation design is [Build the MP2 distributed OCR pipeline (#22)](https://github.com/qu1r0ra/distributed-ocr-pipeline/issues/22). Read its full body and the relevant approved child ticket before implementation or review. The parent owns the architecture, recovery, output behavior, testing boundary, scope, and deferred experiments. Use its execution map and issue relationships for blockers and work order.

For course requirements, use the [MP2 handout summary](../requirements-mp2.md). Keep assignment requirements distinct from implementation choices recorded in the spec.

## Relationship to MP1

The [MP1 spec](../project-spec.md), [concurrency design](../concurrency-design.md), and [OCR contract](../ocr-contract.md) record the accepted single-machine baseline. Preserve that application's behavior. Their thread-only pipeline, shared in-memory image transfer, Windows-only task assumptions, and measured worker optimum do not prescribe MP2 behavior.

Reuse the image-to-text recognition boundary, recognition evaluation, deterministic identity, and visible failure outputs where the MP2 spec carries them forward. Resolve distributed ownership, timing, transport, process startup, and shutdown through the MP2 spec rather than silently copying MP1 coordination rules.

## Work and evidence

Use the live parent and child issues for implementation state and dependencies. Distinguish the local container run from integrated recovery and cloud evidence. Discover commands from the current task definitions. Add operator instructions with the implementation that makes them work.

Use the [team handoff](../team-handoff.md) for phase context. See [Benchmark evidence](#benchmark-evidence) for datasets and ranges. Follow [cloud containers](../cloud-containers.md) for cloud runs.

## Freeze

The code is frozen at the evidence commit named in the [team handoff](../team-handoff.md). Land tests and docs. Hold `src/` and `scripts/` changes unless a defect is found. A defect fix moves the freeze. Re-run affected runs, update the evidence, and name the new commit in the handoff.

## Container host

The owner's Windows PC cannot start Docker Desktop because of virtualization problems. Run Docker and Compose workflows on the Ubuntu IdeaPad. This includes #26 acceptance and the stopped-worker demonstration. The laptop is linked as T3 environment `qu1r0ra-ideapad-ubuntu`. Pass its `environmentId` to T3 tools.

1. Edit and run `just verify` in a task worktree on either machine.
2. Commit and push the task branch. Git carries code to the laptop.
3. On the laptop, check out that pushed commit, then run the container workflow there. Course inputs (`.env`, dataset, model) stay local to the laptop.

Completion: container evidence records the laptop's hostname and the commit SHA it ran. If the environment reports unreachable, ask the owner to bring the laptop online.

## Benchmark evidence

Two datasets answer different questions. Report each in its own table in [benchmark results](../benchmark-results.md). Do not merge them.

- **Local containers:** The IdeaPad containers share 8 logical CPUs. The node sweep uses 1 to 16 nodes with 1 process each. Process sweeps use 1 to 16 processes at 1 and 2 worker nodes, and 1 to 10 at 3 nodes. This measures overhead and contention, not multi-machine scaling.
- **Cloud:** Three LXC containers run native processes without Docker: 1 master and 2 workers. Read [cloud containers](../cloud-containers.md) before using them. The node sweep compares 1 active worker with 2. The second worker is idle in the 1-worker run. Process sweeps use 1 to 8 processes per node at both node counts. This exceeds the 2-vCPU limit to show saturation. The process sweeps carry most of this dataset because the node count cannot exceed 2.

The runner skips and logs settings where `nodes × procs` exceeds the master's active-process cap. The [RPC contract](../pyro5-rpc-contract.md) states the cap and worker startup behavior. A failed sample is invalid and stays in `invalid_samples`.

Run the local dataset with `just benchmark-cluster` on the container host. Run the cloud dataset with `just benchmark-cloud`. For usage and gotchas, see [cloud containers](../cloud-containers.md#run-the-cloud-benchmark). The cloud runner starts the master and workers natively over SSH. It leaves the Compose runner untouched. Cloud results have their own section in [benchmark results](../benchmark-results.md#mp2-cloud-benchmark-ticket-44). Each table must name its host, commit, container or VM resources, and limits.
