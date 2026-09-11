from __future__ import annotations

import gcsfs
import pandas as pd


BUCKET = "ssb-play-enhjoern-a-data-produkt-test"
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


def _create_test_data() -> pd.DataFrame:
    return pd.DataFrame({
        "region": ["0301", "1103", "4601", "5001", "0301"],
        "year": [2024, 2024, 2024, 2024, 2025],
        "value": [100, 250, 175, 320, 125],
    })


def _write_parquet(fs: gcsfs.GCSFileSystem, path: str, data: pd.DataFrame) -> None:
    with fs.open(f"{BUCKET}/{path}", "wb") as file:
        data.to_parquet(file, index=False)


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
    fs = gcsfs.GCSFileSystem()
    data = _create_test_data()
    valid_count = 0
    invalid_count = 0

    for product, state, description in VALID_DATASETS:
        for period, version in PERIODS_AND_VERSIONS:
            path = f"{product}/{state}/{description}_p{period}_v{version}.parquet"
            _write_parquet(fs, path, data)
            valid_count += 1

    for path in _invalid_files():
        _write_parquet(fs, path, data)
        invalid_count += 1

    print("Finished generating test files.")
    print(f"Valid files:   {valid_count}")
    print(f"Invalid files: {invalid_count}")
    print(f"Total files:   {valid_count + invalid_count}")
    print(f"Bucket:        gs://{BUCKET}")
    assert valid_count == 150
    assert invalid_count == 50
