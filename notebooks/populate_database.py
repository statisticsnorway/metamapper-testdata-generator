from __future__ import annotations

import os
from urllib.parse import quote

import gcsfs
import pandas as pd
import requests

from test_data_plan import (
    BUCKET,
    CASCADE_DELETION_PRODUCT,
    INVALID_DATASET_PATHS,
    NAMING_ERROR_PATHS,
    PARTIAL_DELETION_PATH,
    UNTOUCHED_PRODUCT,
    deletion_paths,
    expected_dataset_identities,
    expected_product_names,
    indexed_valid_paths,
    valid_paths,
)

DISPATCHER_URL = os.getenv(
    "METAMAPPER_DISPATCHER_URL",
    "https://metamapper-dispatcher.intern.test.ssb.no",
)


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


def populate_database() -> None:
    print(f"[populate] Starting test data generation in gs://{BUCKET}")
    fs = gcsfs.GCSFileSystem()
    data = _create_test_data()

    for path in valid_paths() + INVALID_DATASET_PATHS:
        _write_parquet(fs, path, data)

    print(f"[populate] Created {len(valid_paths())} valid datasets")
    print(f"[populate] Created {len(INVALID_DATASET_PATHS)} invalid datasets")
    print(f"[populate] Total files:   {len(valid_paths()) + len(INVALID_DATASET_PATHS)}")
    print(f"[populate] Bucket:        gs://{BUCKET}")
    assert len(valid_paths()) == 150
    assert len(INVALID_DATASET_PATHS) == 50


def delete_valid_datasets() -> None:
    """Create partial, full-cascade, and untouched deletion scenarios."""
    print(f"[delete] Starting deletion in gs://{BUCKET}")
    filesystem = gcsfs.GCSFileSystem()
    for path in deletion_paths():
        filesystem.rm(f"{BUCKET}/{path}")
        print(f"[delete] Removed {path}")
    print(f"Deleted valid datasets: {len(deletion_paths())}")
    print(f"Bucket:              gs://{BUCKET}")


def check_deleted_datasets_in_datadoc(api_url: str | None = None) -> None:
    """Verify partial deletion, full cascade deletion, and untouched data."""
    api_url = _datadoc_api_url(api_url)
    all_paths = set(indexed_valid_paths())
    deleted_paths = set(deletion_paths())
    check_paths = all_paths | set(NAMING_ERROR_PATHS)
    statuses = {path: _get_datadoc_file(api_url, path).status_code for path in check_paths}

    print("[datadoc] Test 1/3: partial deletion")
    partial_identity = _dataset_identity(PARTIAL_DELETION_PATH)
    if statuses[PARTIAL_DELETION_PATH] != 404:
        raise AssertionError(f"Partial deletion failed: {PARTIAL_DELETION_PATH} returned HTTP {statuses[PARTIAL_DELETION_PATH]}, expected 404")
    if not any(_dataset_matches(item, partial_identity) for item in _get_datadoc_datasets(api_url, partial_identity[0])):
        raise AssertionError(f"Partial deletion cascade failed: dataset {partial_identity} disappeared after deleting only {PARTIAL_DELETION_PATH}")
    print(f"[datadoc] Partial deletion passed: removed {PARTIAL_DELETION_PATH}; dataset {partial_identity} remains")

    print("[datadoc] Test 2/3: full cascade deletion")
    full_datasets = _get_datadoc_datasets(api_url, CASCADE_DELETION_PRODUCT)
    full_product_status = _get_datadoc_product(api_url, CASCADE_DELETION_PRODUCT).status_code
    still_indexed = [path for path in deleted_paths if statuses[path] == 200]
    if still_indexed:
        raise AssertionError(f"Full cascade deletion failed: deleted files are still indexed: {', '.join(sorted(still_indexed))}")
    if full_datasets or full_product_status != 404:
        raise AssertionError(f"Full cascade deletion failed for {CASCADE_DELETION_PRODUCT}: datasets={full_datasets}, product_status={full_product_status}, expected datasets=[] and product HTTP 404")
    print(f"[datadoc] Full cascade deletion passed: all files, datasets, and data product {CASCADE_DELETION_PRODUCT} were removed")

    print("[datadoc] Test 3/3: untouched data")
    untouched_paths = [
        path for path in check_paths
        if path.startswith(f"{UNTOUCHED_PRODUCT}/") and path != PARTIAL_DELETION_PATH
    ]
    missing = [f"{path} (HTTP {statuses[path]})" for path in untouched_paths if statuses[path] != 200]
    untouched_datasets = _get_datadoc_datasets(api_url, UNTOUCHED_PRODUCT)
    untouched_product_status = _get_datadoc_product(api_url, UNTOUCHED_PRODUCT).status_code
    if missing or untouched_product_status != 200 or not untouched_datasets:
        raise AssertionError(f"Untouched data test failed for {UNTOUCHED_PRODUCT}: missing={missing}, product_status={untouched_product_status}, dataset_count={len(untouched_datasets)}; expected all files HTTP 200, product HTTP 200, and datasets present")
    print(f"[datadoc] Untouched data test passed: {UNTOUCHED_PRODUCT} and its datasets remain available")
    print("[datadoc] All deletion tests passed ✅")


def check_valid_datasets_in_datadoc(api_url: str | None = None) -> None:
    api_url = _datadoc_api_url(api_url)
    print("[datadoc] Checking expected data products, datasets, and files")
    dataset_by_product = {product: [] for product in expected_product_names()}
    for identity in expected_dataset_identities():
        dataset_by_product[identity[0]].append(identity)

    for product in expected_product_names():
        product_status = _get_datadoc_product(api_url, product).status_code
        print(f"[datadoc] Product '{product}': HTTP {product_status}")
        if product_status != 200:
            raise AssertionError(
                f"Product check failed for '{product}': expected HTTP 200, "
                f"got HTTP {product_status}"
            )

        datasets = _get_datadoc_datasets(api_url, product)
        for identity in dataset_by_product[product]:
            if not any(_dataset_matches(dataset, identity) for dataset in datasets):
                raise AssertionError(
                    f"Dataset check failed for product '{product}': expected "
                    f"dataset {identity}, but it was not returned by Datadoc"
                )
            print(f"[datadoc]   Dataset '{identity[1]}/{identity[2]}': present")

        product_paths = [
            path for path in indexed_valid_paths() + NAMING_ERROR_PATHS
            if path.startswith(f"{product}/")
        ]
        file_statuses = {
            path: _get_datadoc_file(api_url, path).status_code
            for path in product_paths
        }
        missing_files = [
            f"{path} (HTTP {status})"
            for path, status in file_statuses.items()
            if status != 200
        ]
        if missing_files:
            raise AssertionError(
                f"File check failed for product '{product}': expected HTTP 200 for "
                + ", ".join(missing_files)
            )
        print(f"[datadoc]   Files: {len(product_paths)} present")

    print(
        f"[datadoc] All {len(expected_product_names())} products, "
        f"{len(expected_dataset_identities())} datasets, and "
        f"{len(indexed_valid_paths()) + len(NAMING_ERROR_PATHS)} files are registered ✅"
    )


def check_invalid_datasets_not_in_datadoc(api_url: str | None = None) -> None:
    api_url = _datadoc_api_url(api_url)
    naming_errors = []
    for path in NAMING_ERROR_PATHS:
        response = _get_datadoc_file(api_url, path)
        if response.status_code != 200:
            raise AssertionError(
                f"Naming-error check failed: {path} returned HTTP "
                f"{response.status_code}, expected 200"
            )
        violations = response.json().get("naming_standard_violations", [])
        if not violations:
            raise AssertionError(
                f"Naming-error check failed: {path} returned 200 but had no "
                "naming_standard_violations"
            )
        naming_errors.append((path, violations))

    rejected = []
    for path in INVALID_DATASET_PATHS:
        if path in NAMING_ERROR_PATHS:
            continue
        if _get_datadoc_file(api_url, path).status_code != 404:
            rejected.append(path)
    if rejected:
        raise AssertionError(f"Rejected-path check failed; expected HTTP 404: {rejected}")
    print(f"[datadoc] Naming errors confirmed for {len(naming_errors)} datasets ✅")
    for path, violations in naming_errors:
        print(f"[datadoc]   {path}: {'; '.join(violations)}")
    print(f"[datadoc] Rejected paths confirmed absent: {len(INVALID_DATASET_PATHS) - len(naming_errors)} ✅")


def check_datasets_in_datadoc(api_url: str | None = None) -> None:
    check_invalid_datasets_not_in_datadoc(api_url)
    check_valid_datasets_in_datadoc(api_url)


def _dataset_identity(path: str) -> tuple[str, str, str]:
    product, state, filename = path.split("/", 2)
    return product, state, filename.split("_p", 1)[0]


def _dataset_matches(dataset: dict, identity: tuple[str, str, str]) -> bool:
    state_names = {"INPUT_DATA": "inndata", "PROCESSED_DATA": "klargjorte-data", "STATISTICS": "statistikk", "OUTPUT_DATA": "utdata"}
    return (dataset.get("product_short_name"), state_names.get(dataset.get("dataset_state"), dataset.get("dataset_state")), dataset.get("short_description")) == identity


def _get_datadoc_datasets(api_url: str, product: str) -> list[dict]:
    response = requests.get(f"{api_url.rstrip('/')}/datasets", params={"product_short_name": product}, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"Datadoc dataset lookup failed with HTTP {response.status_code}")
    return response.json()


def _get_datadoc_product(api_url: str, product: str) -> requests.Response:
    return requests.get(f"{api_url.rstrip('/')}/data-products/{quote(product, safe='')}", timeout=30)


def _datadoc_api_url(api_url: str | None) -> str:
    api_url = api_url or os.getenv("DATADOC_API_URL", "https://metadata.intern.test.ssb.no")
    print(f"[datadoc] Endpoint: {api_url}")
    return api_url


def _get_datadoc_file(api_url: str, path: str) -> requests.Response:
    file_path = f"gs://{BUCKET}/{path}"
    try:
        return requests.get(f"{api_url.rstrip('/')}/data-files/{quote(file_path, safe='')}", timeout=30)
    except requests.RequestException as error:
        raise RuntimeError(f"Could not connect to Datadoc at {api_url}.") from error
