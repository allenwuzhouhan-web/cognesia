# Local compute budgets

Open **Compute budget** in Cognesia's existing editor toolbar. The first visit
asks before running the hardware inventory. You may skip it and choose a manual
budget. Allowing the check reads OS/architecture, CPU counts, total/available RAM
and free disk space. It does not enumerate files, applications, serial numbers or
network identities, and sends nothing to a remote service. Revoking access
removes the saved inventory and returns to Starter.

| Tier | Default RAM ceiling | Maximum neural threads | Suggested integration step | Optical samples |
|---|---:|---:|---:|---:|
| Dummy | 2 GB | 1 | Inspection only | — |
| Starter | 4 GB | 2 | 0.1 ms | 4,096 |
| Plus | 8 GB | 4 | 0.1 ms | 4,096 |
| Pro | 16 GB | 8 | 0.05 ms | 8,192 |
| Max | 40 GB | 16 | 0.025 ms | 16,384 |
| Ultra | 80 GB | 32 | 0.025 ms | 16,384 |
| Super | 160 GB | 64 | 0.025 ms | 16,384 |

Max targets a 64 GB class laptop. Recommendation uses installed RAM and CPU
counts, not a performance benchmark; it does not certify that a given model
fits or runs in real time. Ultra and Super require the opt-in inventory.
Their higher ceilings do not add an unimplemented GPU neural solver or remove
the existing recording-size limits. Small tiers may be unable to run a full
connectome; use the existing selective-circuit workflow or increase the budget.

Apply changes only while experiments, paused work and preparation are stopped.
Neural worker threads are capped at launch, and the selected memory limit is
checked cooperatively in the simulation worker and against the viewer's process
tree. This is not a CPU percentage control or a hard OS sandbox. OS process,
memory and disk isolation remain necessary for a public service.

The command-line operator ceiling is 40 GB by default. On suitable hardware,
explicitly authorize a larger service ceiling before selecting a higher tier:

```sh
.venv/bin/flybrain --mem-limit-gb 160 view
```

Even then, the selected ceiling is bounded by the tier and 80% of inventoried
RAM minus the explicit **Reserve for local GPT-OSS** amount. That reserve reduces
the simulator allowance; it is not a hard limit on the model process. Monitor
actual model use, especially when raising context size. The settings remain in
ignored `build/runtime/compute-policy.json`, not the public source package.

Resolution suggestions apply only when you check the explicit option. They do
not change the neural equations or scientific validation thresholds. Finer time
steps need convergence tests, and more computation cannot repair model bias.
Each admitted job records its compute policy separately from scientific options.

The local owner API provides `GET /api/compute`, `POST /api/compute/consent`
(`{"granted":true|false}`) and `POST /api/compute/profile` (`tier`, optional
`memory_gb`, `threads`, `agent_reserve_gb`). Public agents cannot grant hardware
consent or raise operator budgets.
