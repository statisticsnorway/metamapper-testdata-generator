from __future__ import annotations

import os
from urllib.parse import quote

import gcsfs
import pandas as pd
import requests


BUCKET = "ssb-play-enhjoern-a-data-produkt-test"
DISPATCHER_URL = os.getenv(
    "METAMAPPER_DISPATCHER_URL",
    "https://metamapper-dispatcher.test.ssb.no",
)
VALID_DATASETS = [
    ("befolkning", "inndata", "befolkning"),
    ("befolkning", "statistikk", "befolkning-kommuner"),
    ("befolkning", "utdata", "befolkning"),
    ("sysselsetting", "inndata", "sysselsetting"),
    ("sysselsetting", "statistikk", "sysselsetting-kjonn"),
    ("sysselsetting", "utdata", "sysselsetting"),
    ("utdanning", "klargjorte-data", "utdanning"),
    ("utdanning", "statistikk", "utdanning-nivaa"),
    ("utdanning", "utdata", "utdanning"),
    ("inntekt", "inndata", "personinntekt"),
    ("inntekt", "statistikk", "personinntekt-kommuner"),
    ("inntekt", "utdata", "personinntekt"),
    ("varehandel", "inndata", "varehandel"),
    ("varehandel", "statistikk", "varehandel-imputert"),
    ("varehandel", "utdata", "varehandel"),
]
PERIODS_AND_VERSIONS = [
    ("2024", 1), ("2025", 1), ("2026", 1), ("2025-Q1", 1),
    ("2025-Q2", 1), ("2025-Q3", 1), ("2025-Q4", 1), ("2026-Q1", 2),
    ("2026-Q2", 2), ("2026-Q3", 2),
]


def _valid_paths() -> list[str]:
    return [
        f"{product}/{state}/{description}_p{period}_v{version}.parquet"
        for product, state, description in VALID_DATASETS
        for period, version in PERIODS_AND_VERSIONS
    ]


def _create_test_data() -> pd.DataFrame:
    return pd.DataFrame({
        "region": ["0301", "1103", "4601", "5001", "0301"],
        "year": [2024, 2024, 2024, 2024, 2025],
        "value": [100, 250, 175, 320, 125],
    })


def _write_parquet(fs: gcsfs.GCSFileSystem, path: str, data: pd.DataFrame) -> None:
    with fs.open(f"{BUCKET}/{path}", "wb") as file:
        data.to_parquet(file, index=False)


def _trigger_dispatcher() -> None:
    """Ask the dispatcher to reload its configured bucket."""
    print(f"[dispatcher] Triggering bucket reload at {DISPATCHER_URL}")
    response = requests.post(
        f"{DISPATCHER_URL.rstrip('/')}/manual-bucket-loads",
        timeout=30,
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"Dispatcher trigger failed with HTTP {response.status_code}: "
            f"{response.text}"
        )
    print(f"[dispatcher] Bucket reload queued (HTTP {response.status_code})")


def _invalid_files() -> list[str]:
    products = {
        "befolkning": "befolkning",
        "sysselsetting": "sysselsetting",
        "utdanning": "utdanning",
        "inntekt": "personinntekt",
        "varehandel": "varehandel",
    }
    files = []
    for product, name in products.items():
        files.extend([
            f"{product}/statistikk/{name}_p2025.parquet",
            f"{product}/statistikk/{name}_p2025_v1.parquet",
            f"{product}/statistikk/{name}_2025_v1.parquet",
            f"{product}/statistikk/{name}_p2025_1.parquet",
            f"{product}/utdata/{name}_p2026-Q1.parquet",
            f"{product}/utdata/{name}_p2026-Q1_v1.parquet",
            f"{product}/utdata/{name}_2026-Q1_v1.parquet",
            f"{product}/utdata/{name}_p2026-Q1_1.parquet",
        ])
    return files + [
        f"{product}/{folder}/{name}_p2025_v1.parquet"
        for product, folder, name in [
            ("befolkning", "data", "befolkning"),
            ("sysselsetting", "raw", "sysselsetting"),
            ("utdanning", "statistikkdata", "utdanning"),
            ("inntekt", "processed", "personinntekt"),
            ("varehandel", "output", "varehandel"),
        ]
    ] + [
        f"{product}/{name}_p2025_v1.parquet"
        for product, name in products.items()
    ]


def populate_database() -> None:
    print(f"[populate] Starting test data generation in gs://{BUCKET}")
    fs = gcsfs.GCSFileSystem()
    data = _create_test_data()
    valid_count = 0
    invalid_count = 0

    for product, state, description in VALID_DATASETS:
        for period, version in PERIODS_AND_VERSIONS:
            path = f"{product}/{state}/{description}_p{period}_v{version}.parquet"
            _write_parquet(fs, path, data)
            valid_count += 1
    print(f"[populate] Created {valid_count} valid datasets")

    for path in _invalid_files():
        _write_parquet(fs, path, data)
        invalid_count += 1
    print(f"[populate] Created {invalid_count} invalid datasets")

    print("Finished generating test files.")
    print(f"Valid files:   {valid_count}")
    print(f"Invalid files: {invalid_count}")
    print(f"Total files:   {valid_count + invalid_count}")
    print(f"Bucket:        gs://{BUCKET}")
    assert valid_count == 150
    assert invalid_count == 50
    _trigger_dispatcher()


def delete_valid_datasets() -> None:
    """Delete 20 valid datasets to simulate missing files."""
    print(f"[delete] Starting deletion in gs://{BUCKET}")
    filesystem = gcsfs.GCSFileSystem()
    paths = [
        f"{product}/{state}/{description}_p{period}_v{version}.parquet"
        for product, state, description in VALID_DATASETS[:2]
        for period, version in PERIODS_AND_VERSIONS[:10]
    ]

    for path in paths:
        filesystem.rm(f"{BUCKET}/{path}")
        print(f"[delete] Removed {path}")

    print(f"Deleted valid datasets: {len(paths)}")
    print(f"Bucket:              gs://{BUCKET}")
    _trigger_dispatcher()


def check_valid_datasets_in_datadoc(
    api_url: str | None = None,
    token: str | None = None,
) -> None:
    """Verify that all valid datasets are registered in Datadoc."""
    api_url = api_url or os.getenv(
        "DATADOC_API_URL",
        "https://metadata.intern.ssb.no",
    )
    token = token or os.getenv("DATADOC_API_TOKEN")
    if token is None:
        from dapla_auth_client import AuthClient

        token = AuthClient.fetch_personal_token()

    headers = {"Authorization": f"Bearer {token}"}
    missing = []
    unexpected_statuses = []
    paths = _valid_paths()
    print(f"[datadoc] Checking {len(paths)} valid datasets at {api_url}")

    for path in paths:
        file_path = f"gs://{BUCKET}/{path}"
        response = requests.get(
            f"{api_url.rstrip('/')}/data-files/{quote(file_path, safe='')}",
            headers=headers,
            timeout=30,
        )
        if response.status_code == 404:
            missing.append(path)
        elif response.status_code != 200:
            unexpected_statuses.append((path, response.status_code))

    print(f"[datadoc] Found:   {len(paths) - len(missing) - len(unexpected_statuses)}")
    print(f"[datadoc] Missing:  {len(missing)}")
    print(f"[datadoc] Errors:   {len(unexpected_statuses)}")

    if missing:
        print("[datadoc] Missing datasets:")
        for path in missing:
            print(f"[datadoc]   {path}")
    if unexpected_statuses:
        print("[datadoc] Unexpected responses:")
        for path, status in unexpected_statuses:
            print(f"[datadoc]   {status}: {path}")

    if missing or unexpected_statuses:
        raise AssertionError("Datadoc does not contain all valid datasets")

    print("[datadoc] All valid datasets are registered")
