"""Offline E5 parameter catalog.

Names, units and GRIB identifiers come from DKRZ's README_ERA5_PARAMIDs.txt.
The availability lists reflect E5 directories inspected on 2026-10-28; a
directory alone does not guarantee coverage for a particular date.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files


@dataclass(frozen=True)
class ProductAvailability:
    level_type: str
    kind: str
    resolutions: tuple[str, ...]
    hourly_representation: str


@dataclass(frozen=True)
class Parameter:
    code: int  # DKRZ directory/file number, not always ecCodes paramId
    name: str
    short_name: str
    units: str
    grib_table: int
    grib_code: int
    availability: tuple[ProductAvailability, ...]

    @property
    def level_types(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.level_type for item in self.availability))

    @property
    def eccodes_param_id(self) -> int:
        if self.grib_table == 128:
            return self.grib_code
        return self.grib_table * 1000 + self.grib_code


def _codes(text: str) -> set[int]:
    return {int(code) for code in text.split()}


# E5 directory inventory, not a claim of complete dates in each directory.
_SF_AN = _codes(
    "031 032 033 034 035 036 037 038 039 040 041 042 134 136 137 139 "
    "141 151 159 164 165 166 167 168 170 183 186 187 188 198 206 232 "
    "235 236 238 243 244 245 502 503"
)
_SF_FC = _codes(
    "008 034 044 045 049 050 057 059 066 067 078 079 137 142 143 144 "
    "145 146 147 159 164 169 175 176 177 178 179 180 181 182 195 196 "
    "197 201 202 205 208 209 210 211 212 228 239 240 243 244 245 "
    "259 277 278 279 285 345 346 385 386 474 475 476 477 507"
)
_PL_AN = _codes("060 075 076 129 130 131 132 133 135 138 155 157 203 246 247 248")
_ML_AN = _codes("075 076 077 129 130 131 132 133 135 138 152 155 203 246 247 248")
_SF_AN_IV = _codes("026 027 028 029 030 043 074 129 160 161 162 163 172 263")
_SF_FC_IV = _codes("026 129 172 263")
_ACC = _codes(
    "008 044 045 050 057 142 143 144 145 146 147 169 175 176 177 178 "
    "179 180 181 182 195 196 197 205 208 209 210 211 212 228 239 240 "
    "277 278 385 386 507"
)
_MIN = {202}
_MAX = {49, 201}
_DYNAMIC = ("1H", "1D", "1M")


def _hourly(code: int, resolutions: tuple[str, ...]) -> str:
    if "1H" not in resolutions:
        return "time-invariant" if "IV" in resolutions else "not provided hourly"
    if code in _ACC:
        return "accumulated"
    if code in _MIN:
        return "minimum"
    if code in _MAX:
        return "maximum"
    return "instantaneous"


@lru_cache(maxsize=1)
def _catalog() -> tuple[Parameter, ...]:
    groups = (
        ("sf", "an", _DYNAMIC, _SF_AN),
        ("sf", "an", ("1M",), {207}),
        ("sf", "an", ("IV",), _SF_AN_IV),
        ("sf", "fc", _DYNAMIC, _SF_FC),
        ("sf", "fc", ("1H",), {527}),
        ("sf", "fc", ("IV",), _SF_FC_IV),
        ("pl", "an", _DYNAMIC, _PL_AN),
        ("ml", "an", _DYNAMIC, _ML_AN),
    )
    result = []
    with files("era5_levante").joinpath("data/parameters.csv").open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            code = int(row["code"])
            availability = tuple(
                ProductAvailability(level, kind, resolutions, _hourly(code, resolutions))
                for level, kind, resolutions, codes in groups
                if code in codes
            )
            if availability:
                result.append(
                    Parameter(
                        code,
                        row["name"],
                        row["short_name"],
                        row["units"],
                        int(row["grib_table"]),
                        int(row["grib_code"]),
                        availability,
                    )
                )
    return tuple(result)


def search(query: str) -> list[Parameter]:
    """Search by name, GRIB short name, or DKRZ parameter number.

    Exact short names and numeric codes take precedence over broad name matches.
    """
    term = query.strip().casefold()
    if not term:
        raise ValueError("search query must not be empty")
    catalog = _catalog()
    if term.isdecimal():
        return [p for p in catalog if p.code == int(term)]
    exact = [p for p in catalog if p.short_name.casefold() == term]
    if exact:
        return exact
    words = term.split()
    return [p for p in catalog if all(word in p.name.casefold() for word in words)]


def get_parameter(variable: str | int | Parameter) -> Parameter:
    """Resolve one parameter; reject ambiguous descriptive names."""
    if isinstance(variable, Parameter):
        return variable
    matches = search(str(variable))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"unknown E5 variable {variable!r}")
    choices = ", ".join(f"{p.short_name} ({p.code:03d})" for p in matches[:12])
    raise ValueError(f"ambiguous E5 variable {variable!r}: {choices}")
