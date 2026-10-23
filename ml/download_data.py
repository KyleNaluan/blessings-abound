"""Download the Mercari Price Suggestion dataset into ml/data/, which git ignores.

Source: the Kaggle competition "mercari-price-suggestion-challenge"
(https://www.kaggle.com/competitions/mercari-price-suggestion-challenge/data).
It holds about 1.48M Mercari listings with name, brand, category, item condition and price.
The license, the full contents and whether its price is a sold or a listing price are still to be
verified, so check the competition's rules and data pages before relying on it.

Before the first run:
1. Sign in to Kaggle and accept the competition rules on its page, or the download is refused.
2. Create an API token under Kaggle account settings and save it as ~/.kaggle/kaggle.json.

Then run, from ml/:
    uv run --with kaggle python download_data.py

This script is a stub: it downloads the competition archive and leaves extraction for the
training work, since the data files inside it are 7z archives.
"""

import shutil
import subprocess
import sys
from pathlib import Path

COMPETITION = "mercari-price-suggestion-challenge"
DATA_DIR = Path(__file__).resolve().parent / "data"


def main() -> int:
    DATA_DIR.mkdir(exist_ok=True)
    kaggle = shutil.which("kaggle")
    if kaggle is None:
        print("The kaggle CLI is not installed, run: uv run --with kaggle python download_data.py")
        return 1
    command = [kaggle, "competitions", "download", "-c", COMPETITION, "-p", str(DATA_DIR)]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
