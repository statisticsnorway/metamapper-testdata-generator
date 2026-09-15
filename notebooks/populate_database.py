from __future__ import annotations

import os
import time
from urllib.parse import quote

import gcsfs
import pandas as pd
import requests


BUCKET = "ssb-play-enhjoern-a-data-produkt-test"
DISPATCHER_URL = os.getenv(
    "METAMAPPER_DISPATCHER_URL",
    "https://metamapper-dispatcher.intern.test.ssb.no",
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
ALLOWED_DATASET_STATES = {"klargjorte-data", "utdata"}


def _valid_paths() -> list[str]:
    return [
        f"{product}/{state}/{description}_p{period}_v{version}.parquet"
        for product, state, description in VALID_DATASETS
        for period, version in PERIODS_AND_VERSIONS
    ]


def _allowed_valid_paths() -> list[str]:
    return [
        path
        for path in _valid_paths()
        if any(f"/{state}/" in path for state in ALLOWED_DATASET_STATES)
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


def trigger_dispatcher() -> None:
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


def check_deleted_datasets_in_datadoc(
    api_url: str | None = None,
) -> None:
    """Verify that the 20 deleted datasets are absent from Datadoc."""
    api_url = _datadoc_api_url(api_url)
    paths = _deleted_valid_paths()
    print(f"[datadoc] Checking {len(paths)} deleted datasets at {api_url}")

    remaining = [(path, 200) for path in paths]
    for attempt in range(1, 13):
        remaining = []
        for path in paths:
            response = _get_datadoc_file(api_url, path)
            if response.status_code != 404:
                remaining.append((path, response.status_code))
        if not remaining:
            break
        print(f"[datadoc] Waiting for deletion ({attempt}/12)")
        time.sleep(5)

    print(f"[datadoc] Still indexed: {len(remaining)}")
    if remaining:
        for path, status in remaining:
            print(f"[datadoc]   {status}: {path}")
        raise AssertionError("Deleted datasets are still indexed in Datadoc")

    print("[datadoc] All deleted datasets are absent")


def check_valid_datasets_in_datadoc(
    api_url: str | None = None,
) -> None:
    """Verify that all valid datasets are registered in Datadoc."""
    api_url = _datadoc_api_url(api_url)
    paths = _allowed_valid_paths()
    print(f"[datadoc] Checking {len(paths)} valid datasets at {api_url}")

    missing = set()
    unexpected_statuses = []
    for path in paths:
        response = _get_datadoc_file(api_url, path)
        if response.status_code == 404:
            missing.add(path)
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

    print("[datadoc] All allowed datasets are registered ✅")


def check_invalid_datasets_not_in_datadoc(
    api_url: str | None = None,
) -> None:
    """Verify that deliberately invalid dataset paths are absent from Datadoc."""
    api_url = _datadoc_api_url(api_url)
    paths = _invalid_files()
    print(f"[datadoc] Checking {len(paths)} invalid datasets at {api_url}")

    indexed = []
    unexpected_statuses = []
    for path in paths:
        response = _get_datadoc_file(api_url, path)
        if response.status_code == 200:
            indexed.append(path)
        elif response.status_code != 404:
            unexpected_statuses.append((path, response.status_code))

    print(f"[datadoc] Not indexed: {len(paths) - len(indexed) - len(unexpected_statuses)}")
    print(f"[datadoc] Indexed:     {len(indexed)}")
    print(f"[datadoc] Errors:       {len(unexpected_statuses)}")

    if indexed:
        print("[datadoc] Invalid datasets found in Datadoc:")
        for path in indexed:
            print(f"[datadoc]   {path}")
    if unexpected_statuses:
        print("[datadoc] Unexpected responses:")
        for path, status in unexpected_statuses:
            print(f"[datadoc]   {status}: {path}")

    if indexed or unexpected_statuses:
        raise AssertionError("Datadoc contains invalid datasets")

    print("[datadoc] No invalid datasets are registered ✅")


def check_datasets_in_datadoc(api_url: str | None = None) -> None:
    """Verify allowed datasets are registered and invalid datasets are absent."""
    check_valid_datasets_in_datadoc(api_url)
    check_invalid_datasets_not_in_datadoc(api_url)


def _deleted_valid_paths() -> list[str]:
    return [
        f"{product}/{state}/{description}_p{period}_v{version}.parquet"
        for product, state, description in VALID_DATASETS[:2]
        for period, version in PERIODS_AND_VERSIONS[:10]
    ]


def _datadoc_api_url(api_url: str | None) -> str:
    api_url = api_url or os.getenv(
        "DATADOC_API_URL",
        "https://metadata.intern.test.ssb.no",
    )
    print(f"[datadoc] Endpoint: {api_url}")
    return api_url


def _get_datadoc_file(
    api_url: str,
    path: str,
) -> requests.Response:
    file_path = f"gs://{BUCKET}/{path}"
    try:
        return requests.get(
            f"{api_url.rstrip('/')}/data-files/{quote(file_path, safe='')}",
            timeout=30,
        )
    except requests.RequestException as error:
        raise RuntimeError(
            f"Could not connect to Datadoc at {api_url}. "
            "Set DATADOC_API_URL if another environment is required."
        ) from error
