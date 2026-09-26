# Models (not included in this repo)

HighSpeed decides with a local **openjev NLI 0.8B** model (MIT-licensed). Model weights are
large and are *not* part of this repository.

## Expected layout

Point `SYSTEMONE_MODELS_DIR` at a folder with this structure (the launcher defaults to the
`models/` folder next to this file — i.e. clone the model into `models/` here):

```
models/
└── openjev/
    └── qwen3.5-0.8b-nli-v2s-long/
        ├── config.json
        ├── model.safetensors        (~1.6 GB)
        ├── tokenizer files
        └── modeling_openjev.py      (custom modeling code — ships with the weights)
```

## Where to get the weights

- Project page: https://openjev.tech
- Engine catalogue / docs: https://systemonemodels.org

Download the openjev NLI 0.8B package and place it at `openjev/qwen3.5-0.8b-nli-v2s-long`
inside your models folder. Then either:

- drop it into `models/` next to this README (the default), or
- set `SYSTEMONE_MODELS_DIR` to the folder that contains `openjev/` before launching.

## Runtime dependencies for the engine

`requirements.txt` installs `transformers` + `safetensors`. **PyTorch** is intentionally
*not* pinned there: the launcher creates the venv with `--system-site-packages` so it can
reuse a system-wide CUDA build of torch (~2.5 GB). If you have no torch installed:

```powershell
pip install torch            # CPU build
# or a CUDA build, e.g.:
pip install torch --index-url https://download.pytorch.org/whl/cu128
```

Without CUDA the app still runs — the launcher auto-selects the `cpu-nli` profile
(slower, identical decision contract).
