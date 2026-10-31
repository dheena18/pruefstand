# data/: external sources, pinned and verified (T2.1)

`make data` downloads every external source into `data/raw/` (git-ignored), checks SHA-256 and the
licence against `sources.yaml`, and writes `data/raw/MANIFEST.json`. Nothing raw is ever committed
(`make check` runs `scripts/check_no_raw_data.py`).

| Path | What |
| --- | --- |
| `data/sources.yaml` | the pins (committed): one entry per source, per-kind `defaults` |
| `data/download.py`, `data_sources.py`, `data_fetch.py` | downloader and verifier (stdlib + `httpx` + `huggingface_hub`) |
| `data/raw/<kind>/<source_id>/...` | downloaded files (git-ignored) |
| `data/raw/MANIFEST.json` | `{source_id: {"pin": revision \| commit \| date, "files": {name: sha256}}}` |

Layout (binding for T2.2 to T2.4): `gii:<abbrev>` is `raw/gii/<abbrev>/xml.zip`, `eurlex:<celex>` is
`raw/eurlex/<celex>/{de,en}.html`, Hugging Face ids (`oldp_decisions`, `oldp_laws`, `oldp_citation_graph`,
`germanquad`, `germandpr`, `germanrag`, `prompt_injections`) are `raw/hf/<id>/<file in the repo>`, and
`memerag` is `raw/github/memerag/<repo path>`. Loaders read these directories, never the HF cache.

## Commands

```bash
make data                                   # download + verify all, exit 0 only if nothing is wrong
make data-verify                            # offline: hash files on disk (exit 1, names the source id)
uv run python data/download.py --only gii:kschg --only germanrag
uv run python data/download.py --update-pins            # re-download, rewrite pins, print a diff
```

Exit codes: 0 ok, 1 checksum / missing / unpinned / download error, 2 Hugging Face config missing
(the message lists the existing configs), 3 licence mismatch, 4 usage error. A rerun with valid files
downloads nothing. `.part` files are resumed with `Range`. At most 4 connections, `User-Agent:
pruefstand-data/<version> (+repo URL)`, retries with backoff. `--update-pins` refuses to run when `CI`
is set. Set `HF_TOKEN` only in your shell (never in a file we commit); it is not printed.

## Pins

* HF datasets are pinned by 40-hex commit SHA. `deepset/germanquad` and `deepset/germandpr` are
  script-based on `main` and their data URL (`germanquad.s3.amazonaws.com`) returns 404, so they are
  pinned to a commit of the Hub's `refs/convert/parquet` branch (`ref: refs/convert/parquet` in the
  entry; `--update-pins` follows that ref). Their licence is read from the card on `main`.
* GII and EUR-Lex change when a law is amended: the pin is the `pinned` download date plus the
  SHA-256 of each file. `version_date` per law is parsed in T2.2.
* The OLDP datasets use the `dump-20260520-1k` config. A larger config is an edit of `config:` and
  `files:` followed by `--update-pins`.
* MEMERAG (CC BY-NC 4.0, `redistribute: false`) is download-only: calibration use, never copied into
  `datasets/`, never in the HF release, never used for training. The guard fails on any tracked
  path with a `memerag` component.

## EUR-Lex source and pending pins

* **EUR-Lex** (eur-lex.europa.eu) answers automated requests with an AWS WAF challenge, which we never
  try to get around. The files come from the Publications Office **CELLAR**:
  `https://publications.europa.eu/resource/celex/<celex>` with `Accept-Language: deu|eng`, the official
  XHTML rendition of the act, stored as `raw/eurlex/<celex>/{de,en}.html`.
* **`oldp_decisions` and `oldp_laws`** are gated on the Hub. Their sha256 stay `null` until pinned with
  `HF_TOKEN=... python data/download.py --update-pins --only oldp_decisions --only oldp_laws` (token from
  an account that accepted the terms; set it in your shell, never in a committed file). Until then
  `make data` exits non-zero for these two.
* Documented licence overrides (`card_license`) are listed in `DATA_LICENSES.md` section 7.
