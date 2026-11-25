# Grilling round 1: decisions, compute cost, design source

Written 2026-11-24 for Rob. Source: the grilling of `CORE_ULTRA_NEURAL_ENGINE_CLAUDE_CODE_HANDOFF.md`.
Unit prices come from `docs/research/compute-pricing-2026-11.md` (14 sources). Design sources come from `docs/research/design-sources-2026-11.md` (9 sources, plus 2 repo checks through `gh`).

## 1. Settled so far

| Decision | Answer | Who decided |
| --- | --- | --- |
| Where the first spec stops | M3 exit: a person creates, edits, closes and reopens a document through the neural interface | Rob |
| Rendering mode names | "A, Reference", "B, Neural Raw", "C, Neural Exact Text". Letter always with name | Rob |
| Log of real use | On whenever the app runs. Pointer, key presses and typed text inside the app window only; stored in `artifacts/sessions/` on this Mac; never uploaded; removed by deleting the folder | Rob |
| Who performs the M3 exit check | Scripted driver gates on 100 held-out episodes; Rob confirms once by hand | Rob |
| A gate fails at M3 | One diagnosed retrain, then report. B, Neural Raw text failing is reported, not tuned | Rob |
| Text scope | Latin, accents, emoji verified by real typing. CJK composition by synthesized events only until M4 | Rob |
| Compute | This Mac first. Up to $50 of rented cloud GPU is pre-approved for the small model if the timed pilot shows the Mac is the limit. Rob creates the cloud account and enters payment | Rob |
| Repo visibility | Stays public. Spec and tickets are published as public GitHub issues | Rob |
| Cloud card if the $50 is used | One RTX 4090 on RunPod at $0.89/h, the cheapest confirmed rate (about 56 hours for $50) | Claude |
| Display scaling | Model output is letterboxed and scaled to the window; exact text is drawn at the screen's native resolution | Claude |
| Names for study alternatives | Variant 1, 2, 3 (letters are taken by rendering modes) | Claude |
| Earlier handoff `CORE_ULTRA_CLAUDE_CODE_HANDOFF.md` | Not on this Mac. Build proceeds without it; A, Reference is the only baseline | Claude |
| Tested platform | macOS 27 on Apple M5 only. No cross-platform claim | Claude |
| Python setup | Python 3.12 managed with `uv`, locked dependencies | Claude |
| Weights, datasets, use log | Stay local and gitignored; only manifests and hashes are committed | Claude |
| Demo clip | Built from the app's own presented frames, not from screen recording | Claude |

Reference look (Rob): Claude writes an original, neutral DESIGN.md in the Google Labs format; A, Reference draws from it. Refero pages are a model of structure only.

Nothing is open. Rob confirmed the grilling is done on 2026-11-24.

## 2. Compute cost per model

Every figure below is an estimate from published unit prices times an assumed quantity. Nothing has been run on this Mac yet. M0's benchmark replaces the assumed hours with measured ones.

Formula: cost = hours × hourly rate, or tokens × price per million tokens.

### 2.1 Models this engine trains

| Model | What it is | Where it runs | Assumed compute | Estimated cost |
| --- | --- | --- | --- | --- |
| Small layout encoder + conv decoder (the brief's first model) | Trained from scratch, 256×160 then 512×320 | This Mac (M5, 16 GB) | Smoke 10 min, pilot 2 h (the brief's caps) | $0 |
| Same model, pilot moved to cloud | Same | 1 rented L4 or RTX 4090 | 2 h at $0.69 to $0.89/h | $1.40 to $1.80 |
| Same model, full dataset (100,000 frames) | 20× the pilot's data | 1 rented RTX 4090 | 10 to 40 h at $0.89/h (hours are a guess until the pilot is timed) | $9 to $36 |
| Same model, full dataset, fastest card | Same | 1 rented H100 | 5 to 15 h at $3.95 to $4.89/h | $20 to $73 |
| Small diffusion or flow renderer (the brief's fallback if the decoder blurs) | Tens to hundreds of millions of parameters | 1 rented H100 | 50 to 500 h at $3.95 to $4.89/h | $200 to $2,450 |
| Research-scale GUI world model (NeuralOS, for scale only) | Recurrent state + diffusion | H200 and H100 fleet | 17,000 H200 h + 6,000 H100 h as its paper reports | $100,900 (Modal rates) to $116,300 (RunPod rates) |

The last row is the reason the brief starts small: reproducing a research system costs over 1,000 times the dearest small-model row ($73).

### 2.2 Vision-language models (possible uses: judging rendered frames, later intent work)

| Model | Tier | Where it runs | Assumed use | Estimated cost |
| --- | --- | --- | --- | --- |
| SmolVLM-256M (Apache 2.0) | Small open VLM | This Mac, under 1 GB | Any amount | $0 |
| Qwen3-VL-8B (Apache 2.0, 9B parameters) | Mid open VLM | Does not fit this Mac unquantized (about 18 GB at 16-bit, my calculation). Rented A100 40 GB | Inference at $1.99 to $2.10/h | About $2 per hour of use |
| Qwen3-VL-8B, light fine-tune | Mid open VLM | Rented A100 80 GB | 10 to 50 h at $2.19 to $2.50/h | $22 to $125 |
| Gemma 3 4B (Gemma terms) | Small open VLM | Likely fits this Mac when quantized; publisher states no memory figure | Any amount | $0 if it fits |
| Hosted frontier VLM judging 1,000 held-out frames | Frontier API | Claude Fable 5.2 at $8 in / $40 out | 1,800 tokens in, 200 out per frame (image token count is my assumption; image pricing was not confirmed) | About $22 |
| Hosted mid-tier VLM, same job | Mid API | Claude Sonnet 5.5 at $2 / $10 | Same | About $5.60 |
| Hosted cheap VLM, same job | Cheap API | Gemini 3.5 Flash-Lite at $0.30 / $2.50 (lists image input) | Same | About $1.04 |

### 2.3 Language model APIs (M6 intent and discussion; never per click or per frame)

Assumed request: 3,000 tokens in, 500 tokens out.

| Model | Tier | Price per million tokens (in / out) | Per request | Per 1,000 requests |
| --- | --- | --- | --- | --- |
| Claude Fable 5.2 | Frontier | $8 / $40 | $0.044 | $44 |
| OpenAI gpt-6.2-astra | Frontier | $8 / $40 | $0.044 | $44 |
| Claude Opus 5.5 | Near frontier | $4 / $20 | $0.022 | $22 |
| Gemini 4 Carbon | Near frontier | $2 / $10 until 2026-11-30, then $4 / $20 | $0.011, then $0.022 | $11, then $22 |
| Claude Sonnet 5.5 | Mid | $2 / $10 | $0.011 | $11 |
| Gemini 3.5 Flash-Lite | Cheap | $0.30 / $2.50 | $0.0022 | $2.15 |
| Gemini 3.1 Flash-Lite | Cheap | $0.25 / $1.50 | $0.0015 | $1.50 |
| OpenAI gpt-5.4-nano | Cheap | $0.20 / $1.25 | $0.0012 | $1.23 |
| Claude Haiku 5.5 | Cheap | $0.10 / $0.50 (prompts up to 100k tokens) | $0.00055 | $0.55 |
| OpenAI gpt-6-luna | Cheap | $0.10 / $0.50 | $0.00055 | $0.55 |

### 2.4 What this means for the decision

- Through M3 the engine's own compute is $0 on this Mac, and under $40 if the pilot shows the Mac is the limit and the full dataset moves to a rented RTX 4090.
- The first real money appears only if the small decoder is not good enough and a diffusion renderer is tried: hundreds of dollars, up to about $2,450.
- Language and vision APIs are outside the M3 spec. When they arrive in M6, 1,000 intent requests cost between $0.55 and $44 depending on tier.

### 2.5 Not confirmed

- Image-input pricing for Anthropic, OpenAI and Google. The frame-judging rows assume an image costs about 1,500 input tokens.
- Which OpenAI models are the flagship and the cheapest was read from page layout, not stated.
- AWS, Google Cloud, CoreWeave and Together GPU prices. A10G has no confirmed price.
- Training hours for every row except the brief's own caps. They are guesses until M0 and the pilot time them.
- How well PyTorch's Apple GPU path (MPS) covers this model's operations. Only the lack of 64-bit float support is confirmed.

## 3. Machine-readable design source

Asked for: a link to a machine-readable UX/UI repo or a robust design.md, like the styles on Refero.

| Source | Link | Format | Licence | Checked |
| --- | --- | --- | --- | --- |
| Google Labs DESIGN.md (the format itself) | https://github.com/google-labs-code/design.md | Markdown with YAML tokens: colour, type, spacing, radius, motion, components. Exports to W3C design-token JSON, Tailwind, CSS | Apache-2.0 | 29,091 stars, last push 2026-11-18. Alpha |
| VoltAgent awesome-design-md (a collection of DESIGN.md files modelled on popular brands) | https://github.com/VoltAgent/awesome-design-md | DESIGN.md files, one per brand | MIT | 128,926 stars, last push 2026-10-28 |
| GitHub Primer primitives | https://github.com/primer/primitives | Design-token JSON5: colour, type, spacing | MIT | No radius or elevation tokens |
| W3C Design Tokens format | https://www.designtokens.org/tr/drafts/format/ | JSON token standard (draft of 2026-09-08) | Not confirmed | A format, not a design |

Refero itself (4 more sources):

- Refero has its own DESIGN.md library: https://styles.refero.design/ ("Website Styles & DESIGN.md Library").
- A style page, for example https://refero.design/styles/8b0c66e4-0163-4880-b27f-3fd0fc39264e (teenage engineering), shows hex colours, a pixel type scale with weights and line heights, and Do/Don't guidelines, with DESIGN.md, Copy .md and Download .md controls visible without signing in.
- Not confirmed: whether the download needs Refero Pro, and Refero's terms on reusing a style. Each style is extracted from another company's product, and this repo is public, so a Refero file should stay out of git until the terms are read.
- The awesome-design-md collection's README says its files are extracted from public websites and provided "as is". Calm-workspace entries it names: Notion, Mintlify, Linear. Their file URLs were not opened.

How it is used here: one original DESIGN.md in the Google Labs format becomes the specification that A, Reference draws from, and its tokens are the declared factors a design condition varies.
