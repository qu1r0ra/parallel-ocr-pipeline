# CSC611M Machine Project 2: distributed OCR requirements

This is an original summary of the three-page Machine Project 2 handout. It is a planning reference, not a reproduction of the instructor PDF.

## Required system and topology

- Extend the Machine Project 1 OCR pipeline into a Python distributed system with one master node and at least two worker nodes. Each node must run on a separate physical machine, virtual machine, or container. (Handout p. 1; p. 2)
- The master is the only node that has access to the image dataset. It owns the image queue; worker nodes request tasks from it over the network. Images and OCR results cross node boundaries over the network. Nodes do not share memory or storage, and there may be no shared folders or volumes. (Handout p. 1-2)
- Each worker node runs one or more worker processes. A worker process requests and receives an image, preprocesses it, performs OCR inference, and returns the result to the master. (Handout p. 1)

## Work accounting, output, and shutdown

- The master tracks each image as pending, in progress, or completed. If a worker node fails or disconnects before returning a result, the master reassigns its unfinished images to another worker. (Handout p. 1)
- The master writes one `ocr_results.csv`. Each image must appear exactly once, with a sequential integer ID, image filename, extracted text, and processing time measured on the worker node in milliseconds. (Handout p. 1)
- After all images are processed, the master signals every worker node to shut down and the program terminates. The rubric also expects clean shutdown without races or deadlocks. (Handout p. 1, p. 3)

## Startup configuration

Both programs read a text configuration file at startup. The handout's sample keys and values are:

`master_config.txt`

```text
image_dir=/your_image_directory
port=5000
```

`worker_config.txt`

```text
master_host=10.0.0.1
master_port=5000
n_workers=2
```

The master settings identify the image directory and listening port. The worker settings identify the master's host and port and the number of worker processes to run on that worker node. (Handout p. 2)

## Allowed libraries and recognition target

- Use Python standard-library facilities for synchronization and communication between processes and machines; the handout names sockets and shared objects as examples. Pyro may be used for remote objects. Other third-party concurrency, synchronization, or messaging libraries are not allowed. (Handout p. 2)
- Any OCR library and image preprocessing technique may be used. Tesseract is recommended as a lightweight, easy-to-use option. (Handout p. 2)
- The system should recognize at least half of the characters in the dataset. High OCR accuracy beyond that threshold is not the goal stated in the handout. (Handout p. 2)

## Required presentation

The PPT deck must explain:

- **Project overview:** the distributed OCR pipeline and its components.
- **Distribution:** how the master assigns work and sends images and results over the network.
- **Synchronization:** synchronization within the master and worker nodes, the shared state on each, coordination between nodes, and shutdown.
- **Fault tolerance:** how the master detects a failed worker and reassigns its images; demonstrate a worker node being stopped while processing.
- **Benchmarking:** results for varying worker-node counts, using the same configuration for every node, plus performance analysis and the application's optimal configuration. Report speedup and efficiency as `S = T1 / Tn` and `E = S / n`, where `T1` is total processing time with one worker node, `Tn` is total processing time with `n` worker nodes, and `n` counts worker nodes (the master is not included). (Handout p. 2)

## Submission and grading

Submit a source-code ZIP, the output CSV, and the PPT file. (Handout p. 3)

| Criterion | Weight | Points by band (exemplary / satisfactory / developing / beginning) | Exemplary result described by the rubric |
| --- | ---: | ---: | --- |
| Technical documentation | 10% | 10 / 7 / 3 / 0 | Clearly explain architecture, communication, synchronization, and failure handling; analyze benchmarks across worker-node counts using speedup and efficiency; identify the optimal configuration. |
| Distributed techniques | 40% | 40 / 28 / 12 / 0 | Run one master and at least two workers on separate machines or containers; communicate only over the network; distribute work through the master's image queue; produce complete, consistent results and demonstrate performance gain. |
| Synchronization | 50% | 50 / 35 / 15 / 0 | Protect shared resources within each node, coordinate nodes, reassign work from failed workers, emit each image once, and shut down cleanly without races or deadlocks. |

The lower rubric bands describe progressively weaker documentation or benchmark analysis, deviations from the distributed topology or incomplete output, and synchronization gaps such as unhandled worker failures, duplicate or missing results, races, deadlocks, or improper termination. (Handout p. 3)

## Details left to implementation

The handout sets the required topology, queue states, failure outcome, output fields, and library limits, but leaves the concrete transport and message format, failure-detection method, and worker-process count per node to the implementation. It also does not prescribe CSV header spelling, the worker-time measurement boundary, or a character-scoring/normalization procedure. The handout permits multiple OCR and preprocessing choices; it recommends Tesseract but does not require it. These are open implementation details, not additional course requirements. (Handout p. 1-2)

## Scheduling note supplied by the project owner

The owner supplied a planning deadline of **December 5, 2026, at 10:00 AM Asia/Manila**. This date and time do not appear in the handout.

## Source and coverage

Source handout: `CSC611M - Distributed OCR Pipeline AY2026-27 T1.pdf` (3 pages), SHA-256 `CAF72BD022DD8E462ECD26A987D827A297481C8BC4913B360BD68C31FABD29EB`. Coverage was checked against all three extracted pages: page 1 for topology, queue lifecycle, output, and shutdown; page 2 for configuration, constraints, recognition threshold, presentation, and benchmark formulas; page 3 for deliverables and rubric. The instructor PDF is not included here.

See the [MP1 requirements summary](requirements.md) for the prior project phase.
