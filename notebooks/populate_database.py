from __future__ import annotations

import os
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
    ("befolkning", "klargjorte-data", "befolkning"),
    ("befolkning", "utdata", "befolkning"),
    ("sysselsetting", "inndata", "sysselsetting"),
    ("sysselsetting", "klargjorte-data", "sysselsetting"),
    ("sysselsetting", "utdata", "sysselsetting"),
    ("utdanning", "klargjorte-data", "utdanning"),
    ("utdanning", "statistikk", "utdanning-nivaa"),
    ("utdanning", "utdata", "utdanning"),
    ("inntekt", "inndata", "personinntekt"),
    ("inntekt", "klargjorte-data", "personinntekt"),
    ("inntekt", "utdata", "personinntekt"),
    ("varehandel", "statistikk", "varehandel-imputert"),
    ("varehandel", "klargjorte-data", "varehandel"),
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
            f"{product}/invalid-state/{name}_p2026-Q1.parquet",
            f"{product}/invalid-state/{name}_p2026-Q1_v1.parquet",
            f"{product}/invalid-state/{name}_2026-Q1_v1.parquet",
            f"{product}/invalid-state/{name}_p2026-Q1_1.parquet",
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
    """Create partial, full-cascade, and untouched deletion scenarios."""
    print(f"[delete] Starting deletion in gs://{BUCKET}")
    filesystem = gcsfs.GCSFileSystem()
    paths = _deleted_valid_paths()

    for path in paths:
        filesystem.rm(f"{BUCKET}/{path}")
        print(f"[delete] Removed {path}")

    print(f"Deleted valid datasets: {len(paths)}")
    print(f"Bucket:              gs://{BUCKET}")


def check_deleted_datasets_in_datadoc(
    api_url: str | None = None,
) -> None:
    """Verify partial deletion, full cascade deletion, and untouched data."""
    api_url = _datadoc_api_url(api_url)
    all_paths = set(_allowed_valid_paths())
    partial_path = _partial_deleted_path()
    full_product = "befolkning"
    untouched_product = "sysselsetting"
    full_paths = {path for path in all_paths if path.startswith(f"{full_product}/")}
    deleted_paths = {partial_path} | full_paths

    print("[datadoc] Test 1/3: partial deletion")
    statuses = {
        path: _get_datadoc_file(api_url, path).status_code
        for path in all_paths
    }
    errors = [(path, status) for path, status in statuses.items() if status not in (200, 404)]
    still_indexed = [path for path in deleted_paths if statuses[path] == 200]
    missing_retained = [path for path in all_paths - deleted_paths if statuses[path] == 404]

    partial_dataset = _dataset_identity(partial_path)
    datasets = _get_datadoc_datasets(api_url, partial_dataset[0])
    partial_remains = any(_dataset_matches(item, partial_dataset) for item in datasets)
    if statuses[partial_path] != 404:
        raise AssertionError(
            "Partial deletion failed: "
            f"{partial_path} returned HTTP {statuses[partial_path]}, expected 404"
        )
    if not partial_remains:
        raise AssertionError(
            "Partial deletion cascade failed: dataset "
            f"{partial_dataset} disappeared after deleting only {partial_path}"
        )
    print(
        "[datadoc] Partial deletion passed: removed "
        f"{partial_path}; dataset {partial_dataset} remains"
    )

    print("[datadoc] Test 2/3: full cascade deletion")
    full_datasets = _get_datadoc_datasets(api_url, full_product)
    full_product_status = _get_datadoc_product(api_url, full_product).status_code
    if still_indexed:
        raise AssertionError(
            "Full cascade deletion failed: deleted files are still indexed: "
            + ", ".join(sorted(still_indexed))
        )
    if full_datasets:
        raise AssertionError(
            "Full cascade deletion failed: data product "
            f"{full_product} still has datasets: {full_datasets}"
        )
    if full_product_status != 404:
        raise AssertionError(
            "Full cascade deletion failed: data product "
            f"{full_product} returned HTTP {full_product_status}, expected 404"
        )
    print(
        "[datadoc] Full cascade deletion passed: all files, datasets, and "
        f"data product {full_product} were removed"
    )

    print("[datadoc] Test 3/3: untouched data")
    untouched_datasets = _get_datadoc_datasets(api_url, untouched_product)
    untouched_product_status = _get_datadoc_product(api_url, untouched_product).status_code

    untouched_paths = [
        path for path in all_paths if path.startswith(f"{untouched_product}/")
    ]
    missing_untouched = [
        path for path in untouched_paths
        if path != partial_path and statuses[path] != 200
    ]
    if missing_untouched:
        raise AssertionError(
            "Untouched data test failed: expected HTTP 200 for "
            "these datasets, but got: "
            + ", ".join(
                f"{path} (HTTP {statuses[path]})" for path in sorted(missing_untouched)
            )
        )
    if untouched_product_status != 200:
        raise AssertionError(
            "Untouched data test failed: data product "
            f"{untouched_product} returned HTTP {untouched_product_status}, expected 200"
        )
    if not untouched_datasets:
        raise AssertionError(
            "Untouched data test failed: data product "
            f"{untouched_product} has no datasets"
        )
    print(
        "[datadoc] Untouched data test passed: "
        f"{untouched_product} and its datasets remain available"
    )

    if missing_retained:
        raise AssertionError(
            "Retained dataset test failed: expected HTTP 200 for "
            + ", ".join(sorted(missing_retained))
        )
    if errors:
        raise AssertionError(
            "Deletion check returned unexpected HTTP statuses: "
            + ", ".join(f"{path} (HTTP {status})" for path, status in errors)
        )

    print("[datadoc] All deletion tests passed ✅")


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
    check_invalid_datasets_not_in_datadoc(api_url)
    check_valid_datasets_in_datadoc(api_url)


def _deleted_valid_paths() -> list[str]:
    paths = _allowed_valid_paths()
    partial_path = _partial_deleted_path()
    full_paths = [path for path in paths if path.startswith("befolkning/")]
    return [partial_path, *full_paths]


def _partial_deleted_path() -> str:
    return "sysselsetting/klargjorte-data/sysselsetting_p2024_v1.parquet"


def _dataset_identity(path: str) -> tuple[str, str, str]:
    product, state, filename = path.split("/", 2)
    return product, state, filename.split("_p", 1)[0]


def _dataset_matches(dataset: dict, identity: tuple[str, str, str]) -> bool:
    state_names = {
        "INPUT_DATA": "inndata",
        "PROCESSED_DATA": "klargjorte-data",
        "STATISTICS": "statistikk",
        "OUTPUT_DATA": "utdata",
    }
    return (
        dataset.get("product_short_name"),
        state_names.get(dataset.get("dataset_state"), dataset.get("dataset_state")),
        dataset.get("short_description"),
    ) == (identity[0], identity[1], identity[2])


def _get_datadoc_datasets(api_url: str, product: str) -> list[dict]:
    response = requests.get(
        f"{api_url.rstrip('/')}/datasets",
        params={"product_short_name": product},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Datadoc dataset lookup failed with HTTP {response.status_code}")
    return response.json()


def _get_datadoc_product(api_url: str, product: str) -> requests.Response:
    return requests.get(
        f"{api_url.rstrip('/')}/data-products/{quote(product, safe='')}",
        timeout=30,
    )


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
