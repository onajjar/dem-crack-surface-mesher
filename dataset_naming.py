"""Parse DEAP dataset metadata from the canonical surface CSV filenames."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_DATASET_NAMING = ("60", "1", "0.05", "50", "1e-6")

_METADATA_PATTERN = re.compile(
    r"_ti(?P<ti>\d+)"
    r"_crpa(?P<crpa>\d+)"
    r"_smfa(?P<smfa>\d+)"
    r"_numsp(?P<numspa>\d+)"
    r"(?:_opmin(?P<opmin>\d+))?"
    r"\.csv$",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class DatasetNaming:
    """Decoded naming values used by Cast3M and DEAP fitting."""

    ti: int
    crpa: int
    smfa: float
    numspa: int
    opmin: float

    @property
    def ui_values(self) -> tuple[str, str, str, str, str]:
        return (
            str(self.ti),
            str(self.crpa),
            format(self.smfa, ".12g"),
            str(self.numspa),
            format(self.opmin, ".12g"),
        )


def parse_csv_filename_metadata(path: Path | str) -> DatasetNaming:
    """Decode the five values from one canonical surface CSV filename."""

    name = Path(path).name
    match = _METADATA_PATTERN.search(name)
    if match is None:
        raise ValueError(
            "CSV filename does not contain supported metadata "
            "'_tiN_crpaN_smfaN_numspN[_opminN].csv': "
            + name
        )
    values = {
        key: int(value)
        for key, value in match.groupdict().items()
        if value is not None
    }
    return DatasetNaming(
        ti=values["ti"],
        crpa=values["crpa"],
        smfa=values["smfa"] / 100.0,
        numspa=values["numspa"],
        opmin=values.get("opmin", 1) / 1_000_000.0,
    )


def parse_csv_set_metadata(paths: Iterable[Path | str]) -> DatasetNaming:
    """Decode and cross-check metadata from a complete CSV surface set."""

    materialized = tuple(paths)
    if not materialized:
        raise ValueError("At least one CSV filename is required to derive metadata.")
    decoded = tuple(parse_csv_filename_metadata(path) for path in materialized)
    expected = decoded[0]
    inconsistent = [
        Path(path).name
        for path, metadata in zip(materialized, decoded, strict=True)
        if metadata != expected
    ]
    if inconsistent:
        raise ValueError(
            "Selected CSV filenames contain inconsistent dataset metadata: "
            + ", ".join(inconsistent)
        )
    return expected
