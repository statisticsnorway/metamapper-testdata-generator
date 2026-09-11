# Metamapper testdata generator

Notebook and setup files for generating deterministic Parquet test data in a
GCS bucket. The generated data contains 150 files with valid names and 50
files with deliberately invalid names for testing metadata discovery and
validation.

This is an open-source utility repository. It contains code and a small,
synthetic test-data definition only. Generated Parquet files and credentials
must never be committed to GitHub.

## Local setup

This project uses `uv`.

```bash
uv sync
uv run python -m ipykernel install --user --name metamapper-testdata-generator \
  --display-name "Python (metamapper testdata generator)"
```

Open `notebooks/generate_test_data.ipynb` and select the registered kernel.

## Dapla Lab

Start a **Vscode-python** service in Dapla Lab and configure:

1. Under **Git/GitHub -> Repo**, enter:

   ```text
   https://github.com/statisticsnorway/metamapper-testdata-generator.git
   ```

2. Select the team and access group that can write to the target bucket.
3. Under **Advanced -> Oppstartsskript -> Bash-skript**, enter only the
   repository name and script path:

   ```text
   metamapper-testdata-generator/init.sh
   ```

   Do not enter the full GitHub URL in the **Bash-skript** field. Leave
   **Arguments** empty.

The repository is cloned into `$HOME/work/metamapper-testdata-generator`. The
startup script then runs `uv sync`, creates the project kernel, and configures
VS Code to use `.venv/bin/python`. Open the notebook and select:
`Python (metamapper testdata generator)`.

The bucket must be available to the Dapla Lab service and the selected access
group must have write access. The default bucket is configured in the notebook
and can be changed in its first code cell.

## Generated files

The notebook writes Parquet files directly to:

```text
gs://ssb-play-enhjoern-a-data-produkt-test
```

Running the notebook again overwrites files with the same paths. It does not
delete other files from the bucket.

## Contributions and maintenance

Changes are made through pull requests to `main`. At least one approval is
required before a pull request can be merged. Please see [SECURITY.md](SECURITY.md)
for reporting security vulnerabilities and [LICENSE.md](LICENSE.md) for the
license.
