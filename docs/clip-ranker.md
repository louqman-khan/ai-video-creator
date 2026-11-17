# CLIP picture ranker (task 5.3)

For every scene the app searches stock media and picks the best candidate. The default ranker (`heuristic`) looks at tags, resolution, orientation and
duration. The **CLIP ranker** also looks at the pictures: it compares each candidate's preview with the words of the scene.

## Install (once, about 155 MB)
`avc fetch-models --clip` (downloads OpenAI CLIP ViT-B/32, MIT licence, as int8 ONNX files made by Xenova, into `assets/models/clip/`). Then nothing else:
`MEDIA_RANKER=auto` (default) uses CLIP when the files are there, otherwise the heuristic. `MEDIA_RANKER=clip` / `heuristic` force one. `avc doctor` shows which is active.
Runs on the CPU with onnxruntime (no PyTorch); needs `pillow` and `tokenizers`, both normal dependencies.

## How it scores
`score = heuristic score + 100 x cosine(text embedding of the scene's query, image embedding of the candidate's preview)`.
The preview is the candidate's own `thumb_url` (a few KB; for local files the file itself). A candidate's embedding is remembered in
`work/cache/clip/`. A candidate without a usable preview keeps its heuristic score; if the model itself fails the heuristic result is returned, never an error.
Speed on the dev Mac (Intel i7, CPU): text 5 ms, image about 70 ms; ranking 20 new candidates takes a second or two, repeats are instant.

## Measured
Retrieval test on real Pixabay results: 12 topics x 12 candidates pooled (144 pictures, chance = 0.08), each topic asked for with a *paraphrase* that shares no words
with the search (e.g. "athletes kicking a ball in front of a cheering crowd" for "football match stadium"): **precision@5 heuristic 0.73, CLIP 0.93.**
(With the same words as the search the heuristic is also perfect, because the tags match: CLIP matters when the planner's wording differs from the tags.)
