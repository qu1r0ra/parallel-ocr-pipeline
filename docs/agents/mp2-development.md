# MP2 development

The authoritative implementation design is [Build the MP2 distributed OCR pipeline (#22)](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/22). Read its full body and the relevant approved child ticket before implementation or review. The parent owns the accepted architecture, recovery and output behavior, testing boundary, scope, and deferred experimental choices. Use its approved execution map and native issue relationships for blockers and work order; provisional responsibilities do not finalize partner assignments.

For course requirements, use the [MP2 handout summary](../requirements-mp2.md). Keep assignment requirements distinct from implementation choices recorded in the spec.

## Relationship to MP1

The [MP1 spec](../project-spec.md), [concurrency design](../concurrency-design.md), and [OCR contract](../ocr-contract.md) record the accepted single-machine baseline. Preserve that application's behavior. Their thread-only pipeline, shared in-memory image transfer, Windows-only task assumptions, and measured worker optimum do not prescribe MP2 behavior.

Reuse the image-to-text recognition boundary, recognition evaluation, deterministic identity, and visible failure outputs where the MP2 spec carries them forward. Resolve distributed ownership, timing, transport, process startup, and shutdown through the MP2 spec rather than silently copying MP1 coordination rules.

## Work and evidence

Use the live parent and child issues for implementation state and dependencies. Documentation publication does not establish that containers, distributed recovery, or cloud deployment work. Discover executable commands from the current task definitions; add operator instructions with the implementation that makes them work.

Use the [team handoff](../team-handoff.md) for phase context. MP2 responsibilities remain provisional until the partners settle them. Local container testing can proceed before school-cloud access; cloud provisioning and benchmark ranges remain deferred as recorded in the spec.
