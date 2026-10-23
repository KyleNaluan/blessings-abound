# ml

Training for the price model, which predicts a low, typical and high listing price from an item card.
This folder is its own uv project, separate from `api/`, so the API does not install training-only packages.

## Data

The model trains on the Mercari Price Suggestion dataset from the Kaggle competition `mercari-price-suggestion-challenge`.
Data is never committed.
`download_data.py` fetches it into `ml/data/`, which git ignores, and its docstring lists the one-time Kaggle setup.

```sh
cd ml
uv sync
uv run --with kaggle python download_data.py
```

## Training (not written yet)

Training will be a script in this folder, run with `uv run python train.py`, that:

1. reads the raw data from `ml/data/` and filters it to our categories,
2. trains a LightGBM model with a fixed random seed and compares it against the baseline of median price per category and brand,
3. saves the model file to `ml/models/`, which git ignores because model files are binaries,
4. writes its metrics to `ml/results/metrics.json`, which is committed so every change to the model shows up in review.

The API loads the saved model file from `ml/models/`.
To retrain after a change, download the data once and run the training script again.

## Lint and type check

```sh
uv run ruff check . && uv run ruff format --check . && uv run pyright
```
