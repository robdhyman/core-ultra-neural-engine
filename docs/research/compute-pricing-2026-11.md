# Compute and API pricing, November 2026

All sources were read on 2026-11-24 unless stated. Prices are USD. "calc" marks a value computed from a vendor's per-second price (x 3600).

## A. On-demand GPU $/hour

| GPU | Provider | $/GPU-hr | Config / note | Source | Read |
|---|---|---|---|---|---|
| H100 SXM | RunPod | 4.39 | Secure Cloud | https://www.runpod.io/pricing | 2026-11-24 |
| H100 SXM | Lambda | 4.89 | 1x; 4.59 in 8x HGX | https://lambda.com/pricing | 2026-11-24 |
| H100 SXM | Modal | 3.9492 (calc) | per-second $0.001097 | https://modal.com/pricing | 2026-11-24 |
| H100 PCIe | RunPod | 2.89 | Secure Cloud | https://www.runpod.io/pricing | 2026-11-24 |
| H100 PCIe | Lambda | 3.79 | 1x | https://lambda.com/pricing | 2026-11-24 |
| H200 SXM | RunPod | 5.29 | Secure Cloud | https://www.runpod.io/pricing | 2026-11-24 |
| H200 SXM | Modal | 4.5396 (calc) | per-second $0.001261 | https://modal.com/pricing | 2026-11-24 |
| A100 80GB | RunPod | 2.19 (SXM) / 2.09 (PCIe) | Secure Cloud | https://www.runpod.io/pricing | 2026-11-24 |
| A100 80GB | Lambda | 3.19 | 8x HGX only | https://lambda.com/pricing | 2026-11-24 |
| A100 80GB | Modal | 2.4984 (calc) | per-second $0.000694 | https://modal.com/pricing | 2026-11-24 |
| A100 40GB | Lambda | 1.99 | 1x SXM / PCIe | https://lambda.com/pricing | 2026-11-24 |
| A100 40GB | Modal | 2.0988 (calc) | per-second $0.000583 | https://modal.com/pricing | 2026-11-24 |
| L4 | RunPod | 0.69 | Secure Cloud | https://www.runpod.io/pricing | 2026-11-24 |
| L4 | Modal | 0.7992 (calc) | per-second $0.000222 | https://modal.com/pricing | 2026-11-24 |
| T4 | Modal | 0.5904 (calc) | per-second $0.000164 | https://modal.com/pricing | 2026-11-24 |
| A10 (24GB; not A10G) | Lambda | 1.29 | 1x | https://lambda.com/pricing | 2026-11-24 |
| A10 | Modal | 1.1016 (calc) | per-second $0.000306 | https://modal.com/pricing | 2026-11-24 |
| RTX 4090 | RunPod | 0.89 | Secure Cloud | https://www.runpod.io/pricing | 2026-11-24 |
| B200 | RunPod | 7.99 | Secure Cloud | https://www.runpod.io/pricing | 2026-11-24 |
| B200 | Lambda | 7.99 | 1x SXM6; 7.69 in 8x HGX | https://lambda.com/pricing | 2026-11-24 |
| B200 | Modal | 6.2496 (calc) | per-second $0.001736 | https://modal.com/pricing | 2026-11-24 |
| L40S | RunPod | 1.09 | Secure Cloud | https://www.runpod.io/pricing | 2026-11-24 |
| A10G | none confirmed | - | AWS g5 page has no prices | https://aws.amazon.com/ec2/instance-types/g6/ | 2026-11-24 |

Not confirmed on a primary source: L4 and H200 on Lambda (not listed); T4 and A100 40GB on RunPod (not listed); all GPUs on Google Cloud (page truncated, no figures read); AWS prices (instance-type page carries none).

## B. LLM API prices (USD per 1M tokens)

| Model | Vendor | Input | Output | Cache hit / batch | Image input | Source | Read |
|---|---|---|---|---|---|---|---|
| Claude Fable 5.2 | Anthropic | 8 | 40 | cache hit 0.20; batch 4 / 20 | not stated in pricing table | https://platform.claude.com/docs/en/about-claude/pricing | 2026-11-24 |
| Claude Opus 5.5 | Anthropic | 4 | 20 | cache hit 0.20; batch 2 / 10 | not stated in pricing table | same | 2026-11-24 |
| Claude Sonnet 5.5 | Anthropic | 2 | 10 | cache hit 0.10; batch 1 / 5 | not stated in pricing table | same | 2026-11-24 |
| Claude Haiku 5.5 (prompt up to 100k) | Anthropic | 0.10 | 0.50 | cache hit 0.01; batch 0.05 / 0.25 | not stated in pricing table | same | 2026-11-24 |
| Claude Haiku 5.5 (prompt over 100k) | Anthropic | 0.50 | 2.50 | cache hit 0.05 | not stated in pricing table | same | 2026-11-24 |
| gpt-6.2-astra (flagship, identified by page order) | OpenAI | 8.00 | 40.00 | cached input 0.40 | not stated on page | https://developers.openai.com/api/docs/pricing | 2026-11-24 |
| gpt-6-luna (cheapest listed tier) | OpenAI | 0.10 | 0.50 | cached input 0.01 | not stated on page | same | 2026-11-24 |
| gpt-5.4-nano | OpenAI | 0.20 | 1.25 | cached input 0.02 | not stated on page | same | 2026-11-24 |
| Gemini 4 Carbon | Google | 2.00 to Nov 30 2026, then 4.00 | 10.00, then 20.00 | not read | not stated | https://aistudio.google.com/docs/pricing | 2026-11-24 |
| Gemini 3.1 Pro Preview | Google | 2.00 (to 200k), 4.00 (over) | 12.00 / 18.00 | not read | not stated | same | 2026-11-24 |
| Gemini 3.5 Flash-Lite | Google | 0.30 | 2.50 | not read | yes (text/image/video/audio) | same | 2026-11-24 |
| Gemini 3.1 Flash-Lite | Google | 0.25 (text/image/video), 0.50 (audio) | 1.50 | not read | yes | same | 2026-11-24 |

Image-input pricing (per-image token cost) was not read for any vendor. OpenAI's openai.com/api/pricing page carried no API prices (ChatGPT seat prices only). Flagship and cheapest tier labels for OpenAI are inferred from page layout.

## C. Open-weight VLMs and small LLMs

| Model | Params | Licence | Publisher-stated min VRAM | Apple MPS / MLX documented | Source | Read |
|---|---|---|---|---|---|---|
| SmolVLM-256M-Instruct | 0.3B (safetensors) | Apache 2.0 | "under 1GB of GPU RAM" for one image | No (ONNX, vLLM, SGLang, Docker only) | https://huggingface.co/HuggingFaceTB/SmolVLM-256M-Instruct | 2026-11-24 |
| Qwen3-VL-8B-Instruct | 9B (safetensors; name says 8B) | Apache 2.0 | not stated | No (llama.cpp/Ollama/LM Studio only via quantized builds) | https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct | 2026-11-24 |
| Gemma 3 4B IT | 4B | Gemma terms (accept Google usage licence) | not stated | No | https://huggingface.co/google/gemma-3-4b-it | 2026-11-24 |

Not fetched: PaliGemma, Llama, Phi, LLaVA, or any current successors.

## D. PyTorch MPS limits

- MPS has no float64 or complex128 support; Metal Shading Language has no double type. `PYTORCH_ENABLE_MPS_FALLBACK=1` does not help for these dtypes, and `Tensor.to("mps")` on float64 raises an error rather than downcasting. Source: https://docs.pytorch.org/docs/2.15/notes/mps.html (read 2026-11-24).
- The page gives no operator-coverage, conv, or transformer training statements. Gap.

## Gaps

- A10G on-demand price: no primary source found.
- Lambda: no L4, H200, or A100 40GB price, and no RTX 4090 price listed.
- RunPod: no T4 or A100 40GB price.
- Google Cloud and AWS GPU prices: not confirmed (GCP page truncated; AWS page has no prices).
- CoreWeave and Together AI: not checked.
- Image-input token pricing: not confirmed for Anthropic, OpenAI, or Gemini.
- Gemini 4 Carbon and Gemini 3.1 Pro image-input status: not stated on page.
- Gemini cache-hit and batch prices: not read.
- OpenAI flagship/cheapest labels: inferred from layout, not stated by the page.
- Open-weight VLM list: PaliGemma, Llama, Phi, LLaVA not checked.
- PyTorch MPS conv and transformer training limits, and operator coverage: not on the cited page.
