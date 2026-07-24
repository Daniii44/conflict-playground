#!/usr/bin/env python3

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass

from loguru import logger

from common.redis_util import setup_redis_connection
from info.conflict.analysis.tilt_analysis import (
    CONFLICT_TYPE_SUBDATASETS,
    CONTENT_SUBDATASET,
    InfoConflictTilt,
    MODIFY_DELETE_SUBDATASET,
    RENAME_SUBDATASET,
)


INFO_TILT_PREFIX = "info:conflict:tilt:"
DATASET_TILT_PREFIX = "dataset:tilt:"
SUBDATASETS = (
    CONTENT_SUBDATASET,
    MODIFY_DELETE_SUBDATASET,
    RENAME_SUBDATASET,
)
SUBDATASET_LABELS = {
    CONTENT_SUBDATASET: "Content",
    MODIFY_DELETE_SUBDATASET: "Modify/delete",
    RENAME_SUBDATASET: "Rename",
}


@dataclass(frozen=True)
class TiltCorrelationTable:
    counts: dict[str, Counter[str]]
    normalized: dict[str, dict[str, float]]
    record_count: int


def load_json_value(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def subdataset_counts(tilt_info: InfoConflictTilt) -> Counter[str]:
    counts: Counter[str] = Counter()
    for conflict_type, count in tilt_info.conflict_type_counts.items():
        subdataset = CONFLICT_TYPE_SUBDATASETS.get(conflict_type)
        if subdataset in SUBDATASETS:
            counts[subdataset] += count
    return counts


def build_correlation_table(redis) -> TiltCorrelationTable:
    counts = {
        row: Counter({column: 0 for column in SUBDATASETS})
        for row in SUBDATASETS
    }
    record_count = 0

    for key in sorted(redis.scan_iter(match=f"{DATASET_TILT_PREFIX}*")):
        record = redis.json().get(key)
        if record is None:
            logger.warning("Skipping missing tilt dataset record at {}", key)
            continue

        record = load_json_value(record)
        row = record.get("subdataset") if isinstance(record, dict) else None
        if row not in SUBDATASETS:
            logger.warning("Skipping tilt dataset record with unknown subdataset at {}", key)
            continue

        source_info_key = record.get("source_info_key")
        if not isinstance(source_info_key, str) or not source_info_key.startswith(INFO_TILT_PREFIX):
            logger.warning("Skipping tilt dataset record with missing source_info_key at {}", key)
            continue

        data = redis.json().get(source_info_key)
        if data is None:
            logger.warning("Skipping tilt dataset record with missing source info at {}", key)
            continue

        tilt_info = InfoConflictTilt.model_validate(load_json_value(data))
        current_counts = subdataset_counts(tilt_info)
        record_count += 1

        for column, column_count in current_counts.items():
            counts[row][column] += column_count

    normalized = {}
    for row in SUBDATASETS:
        row_baseline = counts[row][row]
        normalized[row] = {
            column: counts[row][column] / row_baseline if row_baseline else 0.0
            for column in SUBDATASETS
        }

    return TiltCorrelationTable(
        counts=counts,
        normalized=normalized,
        record_count=record_count,
    )


def latex_float(value: float) -> str:
    return f"{value:.3f}"


def print_latex_table(table: TiltCorrelationTable, *, include_counts: bool) -> None:
    print(r"\begin{tabular}{lrrr}")
    print(r"\toprule")
    header = "Subdataset"
    for subdataset in SUBDATASETS:
        header += f" & {SUBDATASET_LABELS[subdataset]}"
    print(f"{header} \\\\")
    print(r"\midrule")

    for row in SUBDATASETS:
        values = []
        for column in SUBDATASETS:
            if include_counts:
                values.append(str(table.counts[row][column]))
            else:
                values.append(latex_float(table.normalized[row][column]))

        print(f"{SUBDATASET_LABELS[row]} & {' & '.join(values)} \\\\")

    print(r"\bottomrule")
    print(r"\end{tabular}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Print a LaTeX 4x4 TILT subdataset correlation table from "
            "dataset:tilt Redis records."
        )
    )
    parser.add_argument(
        "--counts",
        action="store_true",
        help="Print raw logical-conflict counts instead of row-normalized values.",
    )
    args = parser.parse_args()

    table = build_correlation_table(setup_redis_connection())
    print_latex_table(table, include_counts=args.counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
