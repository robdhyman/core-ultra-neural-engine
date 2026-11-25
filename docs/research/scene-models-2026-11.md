# Scene models: layout, vector and UI-structure generation (research, 2026-11)

Question: has any published model generated a design scene (elements, geometry, style values, relationships, interaction states) from pixels plus text, non-autoregressively, trained by rendering the scene and comparing it with a visual target; and what do the nearest published systems, renderers, datasets and licence terms say about building one at small scale?

Sources opened: 94 (distinct URLs, each repository counted once). Three further URLs failed: one arXiv PDF returned unreadable binary, one old Rico URL returned HTTP 404, and one ar5iv page redirected to the abstract only.

How to read this file:

- All pages were read on 2026-11-24. Papers were read on the arXiv abstract page, the arXiv HTML full text, or the ar5iv HTML rendering of the same arXiv paper; the Source column gives the URL actually opened.
- "Not stated" means the value was not seen on the source opened. It does not mean the value does not exist elsewhere.
- Where only the abstract page was opened, the row says "abstract only".
- Repository facts (licence, last commit, stars, file tree) come from the public GitHub API and raw files of the named repository.
- Terms and licence wording in section 7 is paraphrased by clause, with one short verbatim quote of the decisive clause.

## 1. Layout generation

### 1a. Models that generate element sets directly (boxes, classes, attributes)

| System | Method | Output per element | Conditioning | Datasets | Parameters | Training compute | Source |
|---|---|---|---|---|---|---|---|
| LayoutGAN (2019) | GAN; generator refines randomly placed elements with self-attention; one discriminator sees a differentiable wireframe rendering of the layout | Class probabilities and geometry (points, rectangles, triangles) | Random initial layout | MNIST points, about 25,000 document layouts, clipart scenes, 149 tangrams, Rico | Not stated | Not stated | https://ar5iv.labs.arxiv.org/html/1901.06767 |
| LayoutTransformer (ICCV 2021) | Autoregressive Transformer decoder, one attribute token at a time | Class plus x, y, h, w (8-bit quantised) | Empty set or seed elements (completion) | COCO boxes 118,280; Rico 62,951; PubLayNet 335,703; PartNet | 19.2 in the "# params" column for d=512 (unit not printed; d=32 row shows 0.8) | About 6 hours on one NVIDIA GTX1080 for the COCO model; 30 epochs per dataset | https://ar5iv.labs.arxiv.org/html/2006.14615 |
| CanvasVAE (2021) | VAE with Transformer blocks, one-shot (non-autoregressive) decoding | Crello: type, position, size, colour, opacity, image feature. Rico: component, position, size, icon, button text, clickable flag | Latent sample | Crello 23,182 templates; Rico | Not stated | Not stated (500 epochs) | https://ar5iv.labs.arxiv.org/html/2108.01249 |
| CLG-LO on LayoutGAN++ (ACM MM 2021) | Constrained optimisation of the latent code of a pretrained Transformer GAN (augmented Lagrangian; Adam or CMA-ES) | Bounding box per element | Alignment, non-overlap and relational constraints ("larger", "above") written as cost functions | Rico, PubLayNet, Magazine | Not stated | LayoutGAN++: six hours on one RTX 2080Ti, 200,000 iterations | https://ar5iv.labs.arxiv.org/html/2108.00871 |
| LayoutDM (2023) | Discrete diffusion, denoising from an all-masked state | Class plus quantised x, y, w, h | Unconditional; class; class+size; completion; refinement; relationship constraints applied by logit adjustment at sampling time | Rico 35,851 train; PubLayNet 315,757 train | 12.4M | Hardware not stated; 50 epochs (Rico), 20 (PubLayNet). Repo is Apache-2.0 with pretrained weights | https://ar5iv.labs.arxiv.org/html/2303.08137 and https://github.com/CyberAgentAILab/layout-dm |
| LayoutDiffusion (Zhang et al., 2023) | Discrete diffusion with a block-wise transition matrix | Type token plus left, top, right, bottom tokens | Unconditional; type-conditioned; refinement | Rico 66K+; PubLayNet 360K+ | Not stated in the paper (BERT-base-sized encoder); the LayoutFlow paper's Table 8 lists it at 86M | 2 V100 GPUs for 175,000 steps (Rico); 4 V100 for 350,000 steps (PubLayNet) | https://ar5iv.labs.arxiv.org/html/2303.11589 |
| DLT (2023) | Joint continuous (boxes) and discrete (classes) diffusion, Transformer encoder | Class logits plus box coordinates | Any subset of class, location, size | Rico 91K; PubLayNet 330K; Magazine 4K | Not stated in the paper; the LayoutFlow paper's Table 8 lists it at 9.0M | Not stated | https://ar5iv.labs.arxiv.org/html/2303.03755 |
| PLay (2023) | Latent diffusion over a layout autoencoder | Class plus box, up to 128 elements | Guidelines: horizontal and vertical lines given as axis plus position | CLAY about 50K; RICO-Semantic about 43K; PubLayNet about 330K | Not stated | 8 Google Cloud TPU v4 cores for 47 hours, 500k steps | https://arxiv.org/html/2301.11529v2 |
| FlexDM (2023) | Masked field prediction, encoder-decoder Transformer (non-autoregressive) | Type, position, size, colour, font, image and text embeddings (CLIP, 768-d), other attributes | Any masked subset of fields | Rico 45,012 train; Crello 18,738 train | Not stated in absolute terms | Not stated (500 epochs, batch 256) | https://ar5iv.labs.arxiv.org/html/2303.18248 |
| GUILGET (2023) | Transformer; boxes sampled from a Gaussian mixture, then refined | Bounding box per element | GUI arrangement graph of triplets with predicates left, right, top, bottom, inside | CLAY 59,555 | Not stated | Not stated | https://ar5iv.labs.arxiv.org/html/2304.09012 |
| Spot the Error (2024) | Non-autoregressive iterative refinement; a locator reads a wireframe image rendered from the current layout and marks attributes to re-predict | Category, position, size tokens | Not detailed on the page | Rico, PubLayNet | Not stated | Not stated | https://arxiv.org/html/2401.16375 |
| LACE (2024) | Continuous diffusion with differentiable alignment and overlap losses on geometry | Class vector plus centre x, y, width, height | Unconditional; class; class+size; completion; refinement | PubLayNet 315,757 train; Rico 35,851 train | Not stated | Not stated | https://arxiv.org/html/2402.04754 |
| LayoutFlow (2024) | Flow matching, 4-layer Transformer | Box (cx, cy, w, h) plus type as analog bits | Unconditional; type; type+size; completion; refinement | Rico 66K+; PubLayNet 360K+ | "around 15M" in the text, 12.7M in Table 8 | Not stated. Repo is MIT with pretrained weights | https://arxiv.org/html/2403.18187 and https://github.com/JulianGuerreiro/LayoutFlow |
| WebRPG (2024) | VAE over rendering parameters, then either autoregressive or diffusion generation | 13 CSS properties per element: left, top, width, height, seven text properties, color, background-color | The page's HTML (structure and text) | 88,418 samples built from the Klarna product-page set | About 50M per baseline | Hardware not stated; 1M steps, batch 300 | https://arxiv.org/html/2407.15502 |
| Interleaved Gibbs Diffusion (2025) | Gibbs-style discrete-continuous diffusion (abstract only) | Layouts are one of three evaluation tasks | Conditional generation by state-space doubling | Not stated on the abstract page | Not stated | Not stated | https://arxiv.org/abs/2502.13450 |
| LayoutRAG (2025) | Flow matching (built on LayoutFlow) with a retrieved reference layout | Bounding boxes | Class, size, location subsets; completion | Rico, PubLayNet | Not stated | Not stated | https://arxiv.org/html/2506.02697v1 |

Published numbers seen for this family:

- LayoutRAG's Table 1 reports unconditional FID on Rico of 1.96 (LayoutRAG), 2.37 (LayoutFlow) and 4.43 (LayoutDM, retrained by those authors); on PubLayNet 8.28, 8.87 and 8.94. LayoutRAG leads on seven of eight task and dataset pairs in that table; LACE is not in the table (https://arxiv.org/html/2506.02697v1).
- LayoutFlow's Table 8 lists size and sampling speed: LayoutDiffusion 86M and 1600 ms; LayoutDM 12.4M and 16.6 ms; DLT 9.0M and 3.5 ms; LayoutFlow 12.7M and 1.75 ms per layout (https://arxiv.org/html/2403.18187).
- Name collision: arXiv 2303.17189, also called LayoutDiffusion, is a layout-to-image model (boxes in, image out; 569M and 142M variants) and is not a layout generator (https://ar5iv.labs.arxiv.org/html/2303.17189).

### 1b. Language-model systems that write layout or design code

| System | Method | Output | Conditioning | Datasets | Parameters | Training compute | Source |
|---|---|---|---|---|---|---|---|
| LayoutGPT (2023) | In-context prompting, no training | CSS-style lines: object name plus width, height, left, top | Text prompt | NSR-1K (from MSCOCO); 3D-FRONT | Not applicable (GPT-3.5, GPT-4, Codex) | None | https://ar5iv.labs.arxiv.org/html/2305.15393 |
| LayoutPrompter (2023) | In-context prompting with exemplar selection and a ranker, no training | HTML-like div per element with class and left, top, width, height | Types; types+sizes; element relationships; completion; refinement; content-aware; text-to-layout | Rico, PubLayNet, PosterLayout, WebUI | Not applicable (text-davinci-003) | None | https://arxiv.org/html/2311.06495 |
| LayoutNUWA (2023) | Fine-tuned LLM filling masked values in HTML/SVG code | rect tags with category, x, y, width, height | Masked partial layout | Rico, PubLayNet, Magazine | Two 7B LLMs (LLaMA 2, CodeLLaMA) | 64 NVIDIA V100 GPUs; time not stated | https://ar5iv.labs.arxiv.org/html/2309.09506 |
| PosterLlama (2024) | Fine-tuned CodeLlama with LoRA and a DINOv2 image encoder | HTML with rect tags (category, x, y, width, height) | Poster image, text, category and size constraints | CGL 60,548; PKU 9,974 | Not stated | Five days on two A100 GPUs | https://arxiv.org/html/2404.00995 |
| COLE (2023) | Pipeline of five generative models: Llama 2 13B planner, DeepFloyd IF image models, LLaVA-1.5-13B typography and reflection models | Background, object and text layers; typography JSON with about 15 attributes; compiled to SVG | Text intention | About 100,000 collected designs | Per-component mapping not recovered | Not stated | https://arxiv.org/html/2311.16974 |
| OpenCOLE (2024) | GPT-3.5 plan, fine-tuned SDXL image, fine-tuned LLaVA-1.5-7B typography, renderer | Raster image plus typography JSON (font, size, colour, letter spacing) | Text intention | Crello (about 22k) | Not stated | Not stated | https://arxiv.org/html/2406.08232 |
| Graphist (2024) | Multimodal LLM, sequence generation | JSON with left, top, width, height and layer order per input element | RGBA element images | Crello 19,095 train; CGL-v2; 80k in-house | Qwen1.5-0.5B (Tiny) or 7B (Base) LLM plus ViT-L/14 | Base: 5 days; Tiny: 2 days; hardware not stated | https://arxiv.org/html/2404.14368 |
| PosterO (CVPR 2025) | LLM in-context learning over layout trees written in SVG (abstract only) | SVG layout trees | Poster image, design intent | PStylish7 | Not stated | Not stated | https://arxiv.org/abs/2505.07843 |
| CreatiPoster (2025) | Multimodal LLM writes a JSON protocol; a diffusion model paints the background; a rendering engine (Skia is named as an example) draws the layers | Ordered layers; text layers carry content, font, size, position, colour, stroke, rotation, bold, italic, underline, alignment, line and character spacing; asset layers carry position, crop, rotation, mask | Prompt, canvas size, optional RGBA assets | In-house; releases 100,000 multi-layer designs | Not stated | 8 A100 GPUs; about 5 days (protocol model) and 3 days (background model) | https://arxiv.org/html/2506.10890v1 |
| PLAYGROUND (Oct 2026) | Planner, layout generator and visual verifier in a loop that reads the rendered canvas at each step (abstract only) | Editable layout attributes | Unordered input elements, retrieved reference designs | Crello, LICA | Not stated | Not stated | https://arxiv.org/abs/2610.18865 |

### 1c. Layered raster design models (large, pixel layers rather than attributes)

| System | Method | Output | Training data | Parameters | Training compute | Source |
|---|---|---|---|---|---|---|
| Qwen-Image-Layered (Dec 2025) | Diffusion with an RGBA VAE (abstract only) | A variable number of RGBA layers from one RGB image | Layers extracted from PSD files | Not stated | Not stated | https://arxiv.org/abs/2512.15603 |
| LaDe (Mar 2026) | Latent diffusion Transformer | Full design plus n RGBA layers; no per-layer attributes | Private: 8M designs, 1.5M vectors, 2M layered images, 80M natural images | About 11B | 256 H100 GPUs; time not stated | https://arxiv.org/html/2603.17965v1 |
| MRT (May 2026) | Masked region diffusion (abstract only) | Layered transparent images; text-to-layers, image-to-layers, layers-to-layers | More than 10M design samples | 20B | Not stated | https://arxiv.org/abs/2605.27235 |
| CreatiParser (Apr 2026) | Vision-language model for text plus multi-branch diffusion for background and stickers (abstract only) | Editable text, background and sticker layers from a raster design | Parser-40K, Crello | Not stated | Not stated | https://arxiv.org/abs/2604.19632 |
| LayerD (ICCV 2025) | Iterative extraction of unoccluded foreground layers (abstract only) | Raster layers from a flattened design | Not stated on the abstract page | Not stated | Not stated | https://arxiv.org/abs/2509.25134 |

What the layout rows show about the four scene ingredients:

- Geometry and class: every row.
- Style values as native outputs: CanvasVAE, FlexDM, WebRPG, COLE, OpenCOLE, CreatiPoster. The small diffusion and flow models (LayoutDM, DLT, LACE, LayoutFlow, LayoutRAG) output class and box only.
- Relationships: present as inputs or constraints (LayoutDM relationship conditioning, CLG-LO cost functions, GUILGET arrangement graph, PLay guidelines, LayoutPrompter relation prompts, LACE alignment and overlap losses). Layer order is an output in Graphist and CreatiPoster. No row outputs explicit aligned-to, inside or repeats relations.
- Interaction states: no row outputs them. The closest field is the Rico "clickable" flag in CanvasVAE.

## 2. Image-to-vector and vector generation

| System | Method | Training or optimisation signal | Output | Conditioning | Data | Parameters | Compute | Source |
|---|---|---|---|---|---|---|---|---|
| DiffVG (SIGGRAPH Asia 2020) | Differentiable rasteriser (analytical or multisampled prefiltering) | Gradients of pixels with respect to shape parameters | Not a model; a renderer | n/a | n/a | n/a | n/a | https://people.csail.mit.edu/tzumao/diffvg/ |
| DeepSVG (2020) | Hierarchical Transformer VAE, feed-forward (non-autoregressive) decoding | Cross-entropy on commands, arguments, visibility, fill, plus KL; no rendering loss | Paths as move, line, cubic, close commands | Latent | SVG-Icons8, 100,000 icons | Not stated | 100 epochs on two 1080Ti GPUs, about one day | https://ar5iv.labs.arxiv.org/html/2007.11301 |
| Im2Vec (2021) | VAE with a vector decoder | Render-and-compare against raster images through DiffVG; no vector supervision | Depth-ordered closed Bezier paths | Raster image | Fonts, MNIST, Emojis, Icons (sizes not stated) | Not stated | Not stated (100 to 1000 epochs) | https://ar5iv.labs.arxiv.org/html/2102.02798 |
| LIVE (2022) | Per-image optimisation, no network | Pixel loss through DiffVG, paths added layer by layer | Layered closed cubic Bezier paths | Raster image | 134 emoji, 153 pictures | None | 500 iterations per stage; time not stated | https://ar5iv.labs.arxiv.org/html/2206.04655 |
| VectorFusion (2022) | Per-prompt optimisation | Score distillation from Stable Diffusion through DiffVG | Bezier paths, polygons | Text | None | None | 10 to 20 minutes per SVG on an RTX 2080ti | https://ar5iv.labs.arxiv.org/html/2211.11319 |
| SVGDreamer (2023) | Per-prompt optimisation | Score distillation through a differentiable renderer | Paths with colour | Text | None | None | 6m45s to 13m15s per run in Table 2; at least 31 GB on a V100 for six SVGs in parallel | https://arxiv.org/html/2312.16476 |
| IconShop (2023) | Autoregressive Transformer decoder | Token cross-entropy | Icon as M, L, C command tokens | Text or none | FIGR-8-SVG, 300,000 used | Not stated | Not stated (300 epochs) | https://ar5iv.labs.arxiv.org/html/2304.14400 |
| StarVector (2023, revised 2025) | Autoregressive SVG code from a code LLM | Next-token cross-entropy; the paper says no pixel reconstruction objective | SVG code | Image or text | SVG-Stack, 2.1M train | 1B variant; 8B variant | 1B: 7 days on 8 A100; 8B: 10 days on 64 H100 | https://arxiv.org/html/2312.11556 |
| RLRF (2025) | Reinforcement learning on top of an SVG-writing VLM (abstract only) | Reward from rendering the generated SVG and comparing it with the input image; the abstract says differentiable rendering is unavailable for autoregressive SVG code | SVG code | Image | Not stated | Not stated | Not stated | https://arxiv.org/abs/2505.20793 |
| SuperSVG (2024) | Feed-forward ViT predicts paths per superpixel | Render-and-compare through DiffVG: pixel, boundary and path-efficiency losses | Closed paths, 28 parameters each | Raster image | ImageNet | Not stated | 200K iterations per stage; experiments on one RTX 4090 | https://arxiv.org/html/2406.09794 |
| LLM4SVG (2024) | Instruction-tuned LLMs (GPT-2, Phi-2, Falcon) with SVG semantic tokens | Autoregressive token loss | SVG code | Text, optional image | 250k SVGs, 580k instruction samples | Not stated | 8 NVIDIA A800 GPUs, 2 epochs | https://arxiv.org/html/2412.11102 |
| SVGFusion (2024, revised 2026) | VAE that encodes SVG code together with its rendered image, then a diffusion Transformer in that latent space (abstract only) | Not described on the abstract page | Editable SVG | Text | SVGX, 240k SVGs | Not stated | Not stated | https://arxiv.org/abs/2412.10437 |
| LayerTracer (2025) | Diffusion Transformer generates raster construction stages, then layer-wise vectorisation (abstract only) | Not described on the abstract page | Layered SVG | Text or image | Sequential design operations | Not stated | Not stated | https://arxiv.org/abs/2502.01105 |
| OmniSVG (2025) | Autoregressive VLM (Qwen2.5-VL) over command and coordinate tokens | Next-token prediction | SVG token sequences, reported beyond 30k tokens | Text, image, character reference | MMSVG-2M | 4B (3.7B in Table 4) and 8B | Hardware and time not stated | https://arxiv.org/html/2504.06263 |
| Vec2Pix (Feb 2026) | Vectorisation stage optimised through Bezier Splatting; generator trained with flow matching | Pixel L1 through the differentiable renderer in the vectorisation stage only | Hierarchical simplified SVG, then an image conditioned on it | Image | About 5M LAION images | LoRA: about 14.5M trainable | 4 A100 80GB; 50K plus 10K iterations | https://arxiv.org/html/2602.14443 |
| AnchorFlow (May 2026) | Network predicts a sparse anchor field; a deterministic resolver turns it into a path | Rendering errors update a latent perturbation at inference; weights frozen | Cubic Bezier SVG | Image | 17K SVG-derived samples | Not stated | One A100 80GB for experiments | https://arxiv.org/html/2605.19551v1 |
| VectorArk (CVPR 2026) | VLM with a rounded-polygon representation (abstract only) | Not stated on the abstract page | Rounded polygons | Image | Not named | Not stated | Not stated | https://arxiv.org/abs/2605.24398 |

Render-and-compare through a differentiable rasteriser: Im2Vec and SuperSVG (trained networks); LIVE, VectorFusion, SVGDreamer and the vectorisation stage of Vec2Pix (per-image or per-prompt optimisation). Render used as a non-differentiable reward or feedback: RLRF (training reward), AnchorFlow (inference-time refinement). Token likelihood only: DeepSVG, IconShop, StarVector, LLM4SVG, OmniSVG. Not determined from the page opened: SVGFusion, LayerTracer, VectorArk.

## 3. Screenshot to UI structure

| System | Input | Output | Method and loss | Parameters | Training compute | Interaction states | Source |
|---|---|---|---|---|---|---|---|
| Screen Parsing (2021) | Screenshot | UI elements and their grouping relationships (abstract only) | Not detailed on the abstract page | Not stated | Not stated | Not mentioned | https://arxiv.org/abs/2109.08763 |
| Pix2Struct (2022) | Masked web screenshot | Simplified HTML text (pretraining task) | Autoregressive image-to-text | 282M (base), 1.3B (large) | Large: 170K steps, batch 1024, on 128 Google Cloud TPUs; 80M screenshot and HTML pairs | Not covered | https://ar5iv.labs.arxiv.org/html/2210.03347 |
| ScreenAI (2024) | Screenshot | Screen annotation: element type, quantised box, OCR text, nesting by parentheses | Autoregressive | 675M, 1.88B, 4.62B | Hardware not stated; about 353M generated annotation samples | Not stated | https://arxiv.org/html/2402.04615 |
| Design2Code (2024) | Screenshot | One HTML file with CSS | Benchmark of MLLMs; fine-tuned CogAgent-18B; judged by comparing rendered screenshots (CLIP, block match, text, position, colour) | 18B | 4 NVIDIA A6000, about 2 days, LoRA | Excluded: the prompt says no JavaScript for dynamic interactions | https://arxiv.org/html/2403.03163 |
| WebSight / Sightseer (2024) | Screenshot | HTML with Tailwind CSS | Autoregressive VLM fine-tuned with DoRA | Base VLM of 8B | Not stated | Not stated | https://arxiv.org/html/2403.09029 |
| Interaction2Code (ASE 2025) | Interactive prototype | Interactive web page code | Benchmark of MLLMs: 127 pages, 374 interactions, 31 interaction categories (abstract only) | n/a | n/a | The subject of the benchmark; the abstract reports MLLMs generate interactions less adequately than full pages | https://arxiv.org/abs/2411.03292 |
| MLS (Dec 2025) | Screenshot | Serialized layout tree, then framework code through an LLM (abstract only) | Encoder to tree, heuristics, constrained LLM generation | Not stated | Not stated | Not mentioned | https://arxiv.org/abs/2512.18996 |
| VisRefiner (Feb 2026) | Screenshot | HTML and CSS | Qwen2.5-VL-7B; supervised fine-tuning on render differences, then reinforcement learning with a CLIP reward computed on rendered output | 7B | 8 A100 80GB; about 6 hours plus about 20 hours | Not stated | https://arxiv.org/html/2602.05998v1 |
| ScreenParse / ScreenVLM (2026) | Web screenshot | ScreenTag markup: 55 element classes, boxes, text, parent and child indices | Autoregressive; structure-weighted cross-entropy | 316M | 287,500 steps on 16 NVIDIA H100 | Not stated | https://arxiv.org/html/2602.14276 |
| Figma2Code (ICLR 2026) | Figma metadata, assets and screenshot | UI code | Benchmark of ten MLLMs (abstract only) | n/a | n/a | Not mentioned | https://arxiv.org/abs/2604.13648 |
| CANVAS (Nov 2025) | Target design image | Tool calls that build or edit a Figma node tree | Benchmark of VLMs using design tools | n/a | n/a | Not stated | https://arxiv.org/html/2511.20737 |
| ReDesign (ECCV 2026) | Raster design image | Editable layer hierarchy (typography, vector geometry, colour, grouping, layer order) | Agentic composition of specialised tools with local verification (abstract only) | Not stated | Not stated | Not mentioned | https://arxiv.org/abs/2607.25565 |
| OUI-1 (Sep 2026) | Text brief plus a component library's signatures | openui-lang: one component per line, wired into a root | Text diffusion: 256-token blocks denoised in 48 steps; LoRA fine-tune of DiffusionGemma 26B-A4B | 26B total, 4B active | Training hardware and data not stated; inference peaks at about 52 GiB in bf16 | Not stated | https://huggingface.co/thesysdev/OUI-1 |

Does any published model already do what is proposed? Nothing found does. No source opened describes a model that takes pixels plus text, emits a design scene with relationships and interaction states by a non-autoregressive method, and is trained by rendering that scene and comparing it with a visual target. The nearest ones each cover part of it:

- OUI-1 generates a UI component tree by block-wise text diffusion, so it is non-autoregressive within a block. Its card describes a text brief as input, does not describe a render-based loss, does not mention states, and the model is 26B parameters (https://huggingface.co/thesysdev/OUI-1).
- WebRPG's diffusion baseline generates per-element style and geometry (13 CSS properties) at about 50M parameters. It needs the HTML as input, has no render-based loss, and no states (https://arxiv.org/html/2407.15502).
- LayoutDM, DLT, LACE and LayoutFlow are small and non-autoregressive, but output class and box only, take no pixels, and train on layout likelihood or denoising, not on a render (https://ar5iv.labs.arxiv.org/html/2303.08137, https://ar5iv.labs.arxiv.org/html/2303.03755, https://arxiv.org/html/2402.04754, https://arxiv.org/html/2403.18187).
- FlexDM and CanvasVAE are non-autoregressive and output style attributes, but take no screenshot, use no render-based loss, and have no relationships or states (https://ar5iv.labs.arxiv.org/html/2303.18248, https://ar5iv.labs.arxiv.org/html/2108.01249).
- LayoutGAN is judged by its render: a differentiable wireframe rasterisation feeds a discriminator. It covers outlines of points, rectangles and triangles only (https://ar5iv.labs.arxiv.org/html/1901.06767).
- Im2Vec and SuperSVG train networks purely by render-and-compare, but their scenes are Bezier paths, not UI elements with style, relationships or states (https://ar5iv.labs.arxiv.org/html/2102.02798, https://arxiv.org/html/2406.09794).
- ScreenAI, ScreenVLM and ReDesign recover hierarchy from pixels, but autoregressively or with agent tools, with token losses or no training described, and no states (https://arxiv.org/html/2402.04615, https://arxiv.org/html/2602.14276, https://arxiv.org/abs/2607.25565).
- VisRefiner and RLRF are judged by their render, but through a reinforcement-learning reward on an autoregressive code model (https://arxiv.org/html/2602.05998v1, https://arxiv.org/abs/2505.20793).
- Interaction states appear only in Interaction2Code, which is a benchmark for code-writing MLLMs (https://arxiv.org/abs/2411.03292).

## 4. Differentiable vector renderers

| Renderer | Primitives seen on the source | Rounded rectangle | Text | Shadow or blur | Gradient | Licence | Maintenance | Apple Silicon | Source |
|---|---|---|---|---|---|---|---|---|---|
| DiffVG / pydiffvg | Circle, Ellipse, Path (Bezier), Polygon, Rect (two corner points), stroke width, fill and stroke colours, shape groups with transforms | No radius parameter on Rect; expressible as a Path | No text class in `pydiffvg/shape.py` | The SVG parser prints a warning and ignores `filter` | LinearGradient and RadialGradient classes | Apache-2.0 | Not archived; 1,294 stars; 67 open issues and pull requests; latest commit on master 2024-09-17; not on PyPI under `diffvg` or `pydiffvg` (HTTP 404), so it is built from source with CMake | CPU: CMake has a `DIFFVG_CUDA` option with a non-CUDA Thrust path, and a pull request updating the build for macOS on ARM was merged 2023-01-09. MPS: issue 72, open since 2023-10-17, reports segfaults on an M1 Max with `mps`; a commenter notes the C++ code calls CUDA directly. `pydiffvg/device.py` picks `cuda` if available, otherwise `cpu` | https://github.com/BachiLi/diffvg and https://github.com/BachiLi/diffvg/issues/72 |
| Bezier Splatting (NeurIPS 2025) | Open Bezier curves with learnable width; closed curves with flat fill; 2D Gaussians sampled along and inside curves | Not a primitive | Not a primitive | Not stated | Partly: the appendix describes linear gradients through per-segment colour and opacity | MIT | 61 stars; last push 2025-12-18 | Not stated. The required rasteriser (a gsplat fork) builds a CUDA extension with nvcc in its `setup.py`; no MPS statement on any page opened. Speed tests were on an RTX 4090 | https://arxiv.org/html/2503.16424, https://github.com/xiliu8006/Bezier_splatting, https://github.com/XingtongGe/gsplat |
| NURBS Splatting (ECCV 2026) | Rational curves as Gaussian fields; long splines; closed-region filling (abstract only) | Not stated | Not stated | Not stated | Not stated | No code link on the abstract page | n/a | Not stated | https://arxiv.org/abs/2606.31764 |
| Differentiable Drawing and Sketching (2021) | Points, lines, curves, relaxed through distance transforms; README describes the implementation as PyTorch tensor operations only | Not a primitive | No | No | No | BSD-3-Clause | 141 stars; last push 2023-08-09 | Not stated on the source | https://arxiv.org/abs/2103.16194 and https://github.com/jonhare/DifferentiableSketching |
| LayoutGAN wireframe layer (2019) | Points, rectangles, triangles rendered as wireframes, one channel per element class; differentiable in class probabilities and coordinates | No | No | No | No | Paper only; no code opened | n/a | n/a | https://ar5iv.labs.arxiv.org/html/1901.06767 |

Speed figure seen: Bezier Splatting reports, for 2,048 open curves at 2,040 by 1,344 pixels, forward 4.5 ms against DiffVG's 141.3 ms and backward 4.7 ms against 701.3 ms (https://arxiv.org/html/2503.16424).

SDF-based alternatives: two web searches and three GitHub repository searches did not turn up a maintained, licensed, SDF-based differentiable 2D renderer with rounded-rectangle, text or shadow primitives. This is a negative search result, not proof that none exists.

Non-differentiable renderers used inside training or generation loops in the sources above: a browser through Playwright (WebSight data, ScreenParse data, VisRefiner reward) and a rendering engine such as Skia (CreatiPoster) (https://arxiv.org/html/2403.09029, https://arxiv.org/html/2602.14276, https://arxiv.org/html/2602.05998v1, https://arxiv.org/html/2506.10890v1).

## 5. Paired UI and design datasets

| Dataset | Size | Structure that accompanies each image | Interaction states | Licence as seen | Source |
|---|---|---|---|---|---|
| Rico | 9.3k+ Android apps, 66k+ unique screens, 3M elements (figures on the official page today) | View hierarchy JSON; 64-dimensional layout vector; separate semantic annotations with 24 component categories, 197 text-button concepts, 97 icon classes | 10,811 user interaction traces (tap and swipe coordinates) and transition animations as GIFs; no per-component hover, pressed or disabled variants described | Not stated in the page text; a Copyright Notice link was not opened | https://interactionmining.org/rico |
| CLAY | 59,555 human-annotated screen layouts on top of Rico | Object type labels per node, as label files and split lists | None | Not stated on the repo page; repository archived 2026-04-19 | https://arxiv.org/abs/2201.04100 and https://github.com/google-research-datasets/clay |
| WebUI | 400K rendered web pages | Accessibility tree; four box-model boxes per element; computed CSS per element; viewport and full-page screenshots on multiple simulated devices | Not stated | Not stated on the pages opened; the repo points to a COPYRIGHT.txt (not opened). The Hugging Face release is filtered and smaller than the paper's set | https://uimodeling.github.io/ and https://github.com/js0nwu/webui |
| MUD | 18,132 UIs from 3.3k Android apps | View hierarchy | None; the paper lists traces as future work | Not stated | https://arxiv.org/html/2405.07090v1 |
| PixelWeb | Over 100,000 web pages (URLs taken from WebUI) | Per element: transparent image, z layer, mask, contour, box, class; page hierarchy code and computed styles | Not stated | Not stated for the dataset | https://arxiv.org/html/2504.16419v2 |
| ScreenParse | 771,458 web screenshots, 21,094,243 element annotations, 55 classes | Boxes, text, parent and child indices from the DOM | Not stated | Not stated for the dataset | https://arxiv.org/html/2602.14276 |
| WebSight | v0.1: 822,987 pairs; v0.2 viewer shows 1.92M rows; 2,745,658 rows in total | HTML with CSS (v0.1) or Tailwind (v0.2), plus screenshot; synthetic, written by LLMs and rendered with Playwright | Not stated | CC-BY-4.0 | https://huggingface.co/datasets/HuggingFaceM4/WebSight |
| Crello (v5.1.0) | 19,479 / 1,852 / 1,971 train, validation, test | Per element: type, left, top, width, height, angle, opacity, colour, image, text, font, size, bold, italic, text colour, alignment, capitalisation, line height, letter spacing; per-element PNG and template preview | None | CDLA-Permissive-2.0; the card adds that the distributor does not own the copyright of the original templates and that users must agree to the VistaCreate licence agreements | https://huggingface.co/datasets/cyberagent/crello |
| LICA | 1,550,244 layouts, 971,850 templates, about 24.7M components; 27,261 animated layouts | Text, image, vector and group components with position, size, opacity, visibility, transform, fonts; keyframes for animated layouts; groups are flattened in the release | None (animation keyframes only) | Not stated for the dataset in the paper; the paper says 1k layouts are released | https://arxiv.org/html/2603.16098v2 |
| CreatiPoster corpus | 100,000 multi-layer designs, described as copyright-free | Layer protocol as in section 1b | None | Not checked beyond the paper | https://arxiv.org/html/2506.10890v1 |
| CANVAS | 598 tasks sampled from 3.3K mobile UI designs from Figma Community | Image plus JSON of Figma's node tree (position, size, colour; vector, text, rectangle, group, frame) | Not stated | CC BY 4.0 per the paper's footnote | https://arxiv.org/html/2511.20737 |
| Figma2Code | 3,055 samples; 213 curated | Design image plus Figma metadata file | Not mentioned | Not stated on the abstract page | https://arxiv.org/abs/2604.13648 |
| ReDesign Figma-909 | 909 Figma Community designs, 3.77 GB | Layer tree, geometry, z-order, per-element PNGs, original render | Not stated | CC BY 4.0 with attribution | https://huggingface.co/datasets/Jintae-Park/ReDesign-Figma909 |
| Interaction2Code | 127 web pages, 374 interactions, 31 categories | Interactive prototypes (abstract only) | Yes, as interactions; benchmark scale | Not stated on the abstract page | https://arxiv.org/abs/2411.03292 |

No dataset opened pairs a screen with per-component state variants (hover, pressed, disabled, focus). Rico's traces and Interaction2Code's interactions are the only interaction data seen.

Evidence on synthetic design data: a 2026 study of layer decomposition reports that training on purely synthetic layered data can outperform a widely used real dataset and that gains begin to saturate at around 50K samples (abstract only; https://arxiv.org/abs/2605.15167). WebSight is fully synthetic at about 2M pairs (https://arxiv.org/html/2403.09029).

## 6. Small-scale feasibility

Smallest systems from sections 1 to 3 with published size or compute:

| System | What it produced | Parameters | Published training hardware and time | Source |
|---|---|---|---|---|
| DLT | Class and box by joint diffusion | 9.0M (as listed in LayoutFlow's Table 8) | Not stated | https://arxiv.org/html/2403.18187 |
| LayoutDM | Class and box by discrete diffusion | 12.4M | Not stated; 50 epochs on 35,851 Rico layouts | https://ar5iv.labs.arxiv.org/html/2303.08137 |
| LayoutFlow | Class and box by flow matching; 1.75 ms per layout at inference | 12.7M (Table 8), "around 15M" (text) | Not stated; the repo recommends a single GPU | https://arxiv.org/html/2403.18187 and https://github.com/JulianGuerreiro/LayoutFlow |
| LayoutTransformer | Class and box, autoregressive | 19.2 in the "# params" column (unit not printed) | About 6 hours on one GTX1080 (COCO model) | https://ar5iv.labs.arxiv.org/html/2006.14615 |
| LayoutGAN++ | Boxes | Not stated (8 blocks, dimension 256) | Six hours on one RTX 2080Ti | https://ar5iv.labs.arxiv.org/html/2108.00871 |
| PLay | Class and box, latent diffusion | Not stated | 47 hours on 8 Google Cloud TPU v4 cores | https://arxiv.org/html/2301.11529v2 |
| DeepSVG | Icon paths, feed-forward VAE | Not stated (4 layers, dimension 256) | About one day on two 1080Ti GPUs | https://ar5iv.labs.arxiv.org/html/2007.11301 |
| WebRPG | 13 CSS properties per element | About 50M | Hardware not stated; 1M steps at batch 300 | https://arxiv.org/html/2407.15502 |
| Pix2Struct base | Screenshot to simplified HTML | 282M | 64 Google Cloud TPUs (base) | https://ar5iv.labs.arxiv.org/html/2210.03347 |
| ScreenVLM | Screenshot to hierarchical markup | 316M | 287,500 steps on 16 H100 | https://arxiv.org/html/2602.14276 |
| Graphist-Tiny | Layout JSON from RGBA elements | 0.5B LLM plus ViT-L/14 | 2 days; hardware not stated | https://arxiv.org/html/2404.14368 |

No source opened reports training or inference on Apple Silicon, MPS or an M-series chip for any of these systems.

Calculation 1 (labelled arithmetic, not a measurement): memory floor for training state in 32-bit floats.

- Formula: bytes = parameters x 4 bytes x 4 copies (weights, gradients, Adam first moment, Adam second moment). Activations, data and framework overhead are excluded, so real use is higher.
- LayoutDM, 12.4M: 12.4e6 x 16 = 198 MB.
- WebRPG, 50M: 50e6 x 16 = 800 MB.
- Pix2Struct base, 282M: 282e6 x 16 = 4.5 GB.
- ScreenVLM, 316M: 316e6 x 16 = 5.1 GB.
- OUI-1 is outside this formula's useful range: its card gives a 52 GiB inference peak, above 16 GB before any training state (https://huggingface.co/thesysdev/OUI-1).

Calculation 2 (formula only, not evaluated): training time on another machine.

- Formula: T_target = T_published x (R_published / R_target), where R is training throughput in samples per second for the same model, batch size and precision.
- No source opened gives R for an Apple M5 or for any published system on Apple hardware, so no M5 time is computed here.

## 7. Design-library terms

### Refero

Source: Terms of Use, last updated November 12, 2026, linked as "Terms" from https://refero.design/ and served at https://doc.refero.design/legal/terms-of-use.

- Section 10 says Refero Styles (on refero.design and styles.refero.design) is part of the Service and that its design guides, previews and DESIGN.md exports are Refero Content, prepared by analysing publicly available websites. It adds that copying or downloading a guide does not grant permission to reuse third-party materials such as images, logos, fonts or code.
- Section 10 lists what a user may not do unless Refero expressly allows it. One item is to "use Refero Content to train, fine-tune, evaluate, or improve machine learning models or datasets". The other items are reselling, redistributing, sublicensing or syndicating Refero Content; scraping or systematic extraction outside documented download features; removing attribution or source context; and infringing or misleading use of third-party screenshots, logos or trademarks.
- Section 10 also says what is allowed: using Refero Content for design research, inspiration, internal reference and ordinary product design work, and using what is learned to design and build one's own products. It permits including Refero Content as reference material in presentations, moodboards, Figma files and client or internal design work. It states that this does not allow publishing the content as a standalone library or dataset, and that turning Refero Content into a competing dataset, repository or AI/ML asset is not allowed.
- Section 13 repeats the restriction for MCP and API access: no model training, fine-tuning, benchmarking, dataset creation or model evaluation using Refero Content unless agreed in writing, and no resale or redistribution without a separate agreement.

Read plainly, these terms do not permit using Refero styles or DESIGN.md exports as model training input, nor committing them to a public repository, without Refero's express permission. Using a guide as a reference while doing one's own design work is within the allowed uses listed in section 10.

### VoltAgent/awesome-design-md

Sources: https://github.com/VoltAgent/awesome-design-md (LICENSE, README.md, file tree, and `design-md/notion/DESIGN.md` and `design-md/notion/README.md`).

- Licence: MIT, copyright 2026 VoltAgent. The MIT text grants use, copy, modify, merge, publish, distribute, sublicense and sell, on condition that the copyright and permission notice stay in all copies or substantial portions, and disclaims all warranty.
- README: describes the repository as a curated collection of design system documents extracted from public websites; says the tokens represent publicly visible CSS values; says the maintainers do not claim ownership of any site's visual identity; says the files are provided as is, without warranty; and says the documents exist to help AI agents generate consistent UI. It says nothing about model training or about redistribution beyond the MIT licence.
- Contents on 2026-11-24: the tree holds 84 `design-md/<site>/DESIGN.md` files. The Notion file is 35,176 bytes and starts with YAML front matter (`version: alpha`, a `colors` map including pressed variants such as `primary-pressed`). The per-site README in that folder says the design system details have moved to getdesign.md.
- Repository state: MIT, not archived, latest commit 2026-10-28, about 128.9k stars.

Read plainly, the MIT licence permits copying these files into a public repository and using them as input, provided the notice is kept. The licence is granted by VoltAgent over its own files; the README itself disclaims ownership of the underlying sites' visual identities, so the licence does not speak for those sites' trademarks or brand assets. The terms of getdesign.md were not opened.

## Gaps

- Extraction method: full-text pages were read through an automated page reader that answers questions about a fetched page. Eight load-bearing numbers (LayoutTransformer, LayoutDM, LayoutFlow, PLay, DeepSVG, LayoutGAN++, WebRPG, ScreenVLM) were re-checked by searching the page text directly and matched. Other numbers were not re-checked.
- Abstract only (no full text opened): Interleaved Gibbs Diffusion, PosterO, PLAYGROUND, Qwen-Image-Layered, MRT, CreatiParser, LayerD, SynLayers, RLRF, SVGFusion, LayerTracer, VectorArk, NURBS Splatting, Differentiable Drawing and Sketching (paper), Screen Parsing, Interaction2Code, MLS, Figma2Code, ReDesign, CLAY, WebUI (paper). Their parameter counts and compute are therefore unknown here, not confirmed absent.
- Truncated reads: the automated reader stopped at 100,000 characters on StarVector, SVGDreamer, OmniSVG, AnchorFlow, ScreenParse, CANVAS and LayoutDiffusion (Zhang); appendices beyond that point were not read. The COLE tail was read but its parameter table did not survive extraction, so the per-component parameter mapping is unconfirmed.
- Venues: stated only where the opened page showed them. Venues for LayoutDM, LayoutDiffusion, DLT, LACE, LayoutFlow, LayoutGPT, LayoutNUWA, PosterLlama, FlexDM, CanvasVAE, Graphist, COLE and others were not shown on the pages opened.
- Inconsistencies left as found: LayoutFlow gives 12.7M in a table and "around 15M" in text; the same paper gives 100 and 50 sampling steps in different places. LayoutTransformer's parameter column has no unit. Rico is 66k+ screens and 9.3k+ apps on its official page but 72k and 9.7k in the LACE paper. LICA's own counts differ slightly between abstract, introduction and tables.
- "Newer" coverage: found by web searches (19 in total across all seven questions). Two searches for 2026 diffusion or flow layout generators beyond LayoutRAG returned nothing new; that is a search result, not a survey. Conference proceedings for 2026 were not browsed directly.
- OUI-1: only the model card was opened. Its training data and method beyond "LoRA fine-tune" are not on the card; claims in secondary articles about self-training with a parser were not used. The base model's own card was not opened.
- DiffVG: the paper PDF was not read, so primitive coverage comes from the repository source files. No build was attempted on any machine. Whether the CPU path performs acceptably on Apple Silicon is not reported in any source opened.
- Bezier Splatting: whether it runs without CUDA was not tested; the fork's `setup.py` shows a `BUILD_NO_CUDA` flag whose effect was not investigated.
- PyTorch-SVGRender (MPL-2.0, last push 2025-02-25): only repository metadata was read; its README and install notes were not opened.
- SDF-based renderers: none found; searches were shallow (two web, three GitHub).
- Licences not confirmed: Rico (Copyright Notice not opened), WebUI (COPYRIGHT.txt not opened), CLAY, MUD, PixelWeb, ScreenParse, LICA full set, Figma2Code, Interaction2Code, the CreatiPoster corpus.
- Not opened at all: Rewire (CHI 2018), Sketch2Code, pix2code, Enrico, AndroidInTheWild, OmniParser, PrismLayers, Prototype2Code, the 2024 layer-grouping paper, getdesign.md and its terms, Refero's Copyright Policy and Privacy Policy, and any individual Refero style export.
- Starting-point names: all were found as real papers. LayoutDiffusion resolves to two different papers (see section 1a).
- Sketch-conditioned layout or UI generation was not searched specifically.

## What this means for a scene model

- No published system found matches the proposal; the combination of pixel-plus-text input, non-autoregressive scene output, render-based training, relationships and states is not covered by any row in sections 1 to 3.
- Non-autoregressive generation of element sets works at 9M to 13M parameters (DLT, LayoutDM, LayoutFlow in section 6), but those models output class and box only and take no image input.
- Style values as native outputs have precedent at small and medium size: CanvasVAE and FlexDM (attributes on Crello and Rico) and WebRPG (13 CSS properties, about 50M). None of them trains on a render.
- Relationships exist in the literature as conditioning or constraints (LayoutDM, CLG-LO, GUILGET, PLay, LACE), and hierarchy as output exists only in autoregressive or agentic systems (ScreenAI, ScreenVLM, Graphist, ReDesign). Aligned-to and repeats as generated outputs were not found.
- Interaction states are absent from every model output and every dataset in sections 1, 3 and 5 except the Interaction2Code benchmark; a synthetic generator is the only source of paired state data identified, and two sources report useful results from synthetic design data (WebSight, SynLayers).
- Training by render-and-compare has working precedents for Bezier paths (Im2Vec, SuperSVG through DiffVG) and for box wireframes (LayoutGAN); code-writing models use rendering only as a reward (RLRF, VisRefiner), and the RLRF abstract says differentiable rendering is unavailable for that setting.
- No differentiable renderer in section 4 offers text, shadow or a rounded-rectangle primitive; DiffVG has gradients and basic shapes, was last committed to in September 2024, is CPU-only on Apple Silicon according to its sources, and Bezier Splatting depends on a CUDA build.
- Published compute for the smallest systems is hours to about a day on one or two consumer GPUs (LayoutTransformer, LayoutGAN++, DeepSVG) or 47 hours on 8 TPU cores (PLay); none reports Apple Silicon. On terms, Refero prohibits training and dataset use of its DESIGN.md exports, while the 84 files in VoltAgent/awesome-design-md are MIT-licensed.
