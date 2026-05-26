---
date: '2026-04-09'
company: '[[MegaTrain]]'
product: MegaTrain
action: release
significance: 4
tags:
- developer-tools
- research
sources:
- AI-Brief
---

## MegaTrain enables full-precision training of 120B parameter models on a single GPU.

MegaTrain introduces a technique to offload parameters to CPU memory, allowing 120B parameter models to be trained on a single H200 GPU. By using pipeline double-buffering and stateless layer templates, it achieves 1.84x faster throughput than DeepSpeed ZeRO-3.

## Sources
- [AI-Brief](https://ai-brief.liziran.com/en/daily/2026-04-09-single-gpu-120b-video-benchmark-bias.html)

## Related
- [[Large Language Models]]
