"""Resolve E5 paths and open small, homogeneous selections lazily."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .catalog import Parameter, ProductAvailability, get_parameter


DEFAULT_ROOT = Path("/pool/data/ERA5/E5")
_LEVELS = {"sf", "pl", "ml"}
_RESOLUTIONS = {"1H", "1D", "1M", "IV"}


@dataclass(frozen=True)
class FileSelection:
    parameter: Parameter
    level_type: str
    kind: str
    resolution: str
    start: date | None
    end: date | None
    files: tuple[Path, ...]
    missing: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.missing

    def require_complete(self) -> FileSelection:
        if self.missing:
            raise MissingCoverageError(self)
        return self


class MissingCoverageError(FileNotFoundError):
    def __init__(self, selection: FileSelection):
        self.selection = selection
        excerpt = ", ".join(selection.missing[:8])
        if len(selection.missing) > 8:
            excerpt += f", ... ({len(selection.missing)} periods total)"
        super().__init__(
            f"missing E5 {selection.parameter.short_name} {selection.level_type}/{selection.kind}/"
            f"{selection.resolution} files for {excerpt}"
        )


class TimeCoverageError(ValueError):
    """An existing file has no GRIB validity time for a requested period."""


class IncompatibleGribError(ValueError):
    """The selected files cannot be interpreted as one homogeneous variable."""


def _date(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"expected ISO date YYYY-MM-DD, got {value!r}") from exc


def _periods(start: date, end: date, resolution: str):
    if resolution == "1H":
        current = start
        while current <= end:
            yield current.isoformat()
            current += timedelta(days=1)
    elif resolution == "1D":
        year, month = start.year, start.month
        while (year, month) <= (end.year, end.month):
            yield f"{year:04d}-{month:02d}"
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    else:  # 1M
        for year in range(start.year, end.year + 1):
            yield f"{year:04d}"


def _availability(parameter: Parameter, level_type: str, resolution: str, kind: str | None) -> ProductAvailability:
    options = [
        item
        for item in parameter.availability
        if item.level_type == level_type and resolution in item.resolutions
    ]
    if kind is not None:
        if kind not in {"an", "fc"}:
            raise ValueError("kind must be 'an' or 'fc'")
        options = [item for item in options if item.kind == kind]
    if not options:
        choices = ", ".join(
            f"{item.level_type}/{item.kind} ({','.join(item.resolutions)})"
            for item in parameter.availability
        )
        raise ValueError(
            f"{parameter.short_name} ({parameter.code:03d}) is not cataloged for "
            f"{level_type}/{kind or '*'}/{resolution}; cataloged: {choices}"
        )
    if len(options) != 1:
        raise ValueError(
            f"{parameter.short_name} has both analysis and forecast {level_type}/{resolution}; "
            "pass kind='an' or kind='fc'"
        )
    return options[0]


def resolve_files(
    variable: str | int | Parameter,
    level_type: str,
    resolution: str,
    start: str | date | datetime | None = None,
    end: str | date | datetime | None = None,
    *,
    kind: str | None = None,
    root: str | Path = DEFAULT_ROOT,
) -> FileSelection:
    """Find sorted E5 GRIB files, with one missing label per absent file period.

    ``root`` is the E5 directory itself. For 1H/1D/1M, a date range is
    inclusive; one file contains a day/month/year, respectively. IV has no
    date range and resolves one invariant file.
    """
    if level_type not in _LEVELS:
        raise ValueError(f"level_type must be one of {sorted(_LEVELS)}")
    if resolution not in _RESOLUTIONS:
        raise ValueError(f"resolution must be one of {sorted(_RESOLUTIONS)}")
    parameter = get_parameter(variable)
    product = _availability(parameter, level_type, resolution, kind)
    base = Path(root) / level_type / product.kind / resolution / f"{parameter.code:03d}"
    stem = f"E5{level_type}{'00' if product.kind == 'an' else '12'}_{resolution}_"
    suffix = f"_{parameter.code:03d}.grb"

    if resolution == "IV":
        if start is not None or end is not None:
            raise ValueError("IV fields are time-invariant; omit start and end")
        canonical = base / f"{stem}INVARIANT{suffix}"
        dated = base / f"{stem}2000-01-01{suffix}"
        found = canonical if canonical.is_file() else dated if dated.is_file() else None
        return FileSelection(
            parameter, level_type, product.kind, resolution, None, None,
            (found,) if found else (), () if found else ("INVARIANT",),
        )

    if start is None:
        raise ValueError("start is required for 1H, 1D and 1M")
    first = _date(start)
    last = _date(end) if end is not None else first
    if last < first:
        raise ValueError("end precedes start")
    found_files = []
    missing = []
    for stamp in _periods(first, last, resolution):
        path = base / f"{stem}{stamp}{suffix}"
        if path.is_file():
            found_files.append(path)
        else:
            missing.append(stamp)
    return FileSelection(
        parameter, level_type, product.kind, resolution, first, last,
        tuple(found_files), tuple(missing),
    )


def _forecast_coordinates(path: Path, dataset):
    """Restore each GRIB message's reference time and step after flat cfgrib opening."""
    import numpy as np
    from eccodes import codes_get, codes_grib_new_from_file, codes_release

    records = {}
    with path.open("rb") as stream:
        while (message := codes_grib_new_from_file(stream)) is not None:
            try:
                valid_date = int(codes_get(message, "validityDate"))
                valid_clock = int(codes_get(message, "validityTime"))
                reference_date = int(codes_get(message, "dataDate"))
                reference_clock = int(codes_get(message, "dataTime"))
                start_step = int(codes_get(message, "startStep"))
                end_step = int(codes_get(message, "endStep"))
                step_range = str(codes_get(message, "stepRange"))
            finally:
                codes_release(message)
            valid = _grib_datetime(valid_date, valid_clock)
            reference = _grib_datetime(reference_date, reference_clock)
            if valid in records:
                raise IncompatibleGribError(f"duplicate forecast validity time {valid} in {path}")
            records[valid] = (reference, start_step, end_step, step_range)

    values = dataset["valid_time"].values.astype("datetime64[ns]")
    if len(records) != values.size:
        raise IncompatibleGribError(f"cfgrib and GRIB message counts differ in {path}")
    try:
        ordered = [records[valid] for valid in values]
    except KeyError as exc:
        raise IncompatibleGribError(f"cfgrib validity time differs from GRIB header in {path}") from exc
    references = np.array([item[0] for item in ordered], dtype="datetime64[ns]")
    starts = np.array([item[1] for item in ordered], dtype="timedelta64[h]").astype("timedelta64[ns]")
    steps = values - references
    if any(
        step != np.timedelta64(item[2], "h") for step, item in zip(steps, ordered)
    ):
        raise IncompatibleGribError(f"GRIB endStep and validity time disagree in {path}")
    coords = {
        "time": ("valid_time", references),
        "step": ("valid_time", steps),
        "step_start": ("valid_time", starts),
        "step_range": ("valid_time", [item[3] for item in ordered]),
    }
    if dataset[next(iter(dataset.data_vars))].attrs.get("GRIB_stepType") == "accum":
        coords["interval_start"] = ("valid_time", references + starts)
    return dataset.assign_coords(coords)


def _grib_datetime(yyyymmdd: int, hhmm: int):
    import numpy as np

    return np.datetime64(
        f"{yyyymmdd // 10000:04d}-{yyyymmdd // 100 % 100:02d}-{yyyymmdd % 100:02d}T"
        f"{hhmm // 100:02d}:{hhmm % 100:02d}",
        "ns",
    )


def _clip_and_check(dataset, selection: FileSelection, dimension: str):
    import numpy as np

    values = dataset[dimension].values.astype("datetime64[ns]")
    if values.ndim != 1 or (values.size > 1 and np.any(values[1:] <= values[:-1])):
        raise IncompatibleGribError(f"{dimension} is not strictly increasing and unique")
    if selection.resolution == "IV":
        return dataset

    assert selection.start is not None and selection.end is not None
    if selection.resolution == "1M":
        lower = np.datetime64(selection.start.strftime("%Y-%m"), "M")
        upper = np.datetime64(selection.end.strftime("%Y-%m"), "M") + np.timedelta64(1, "M")
        actual = values.astype("datetime64[M]")
        expected = np.arange(lower, upper, np.timedelta64(1, "M"))
    elif selection.resolution == "1D":
        lower = np.datetime64(selection.start, "D")
        upper = np.datetime64(selection.end, "D") + np.timedelta64(1, "D")
        actual = values.astype("datetime64[D]")
        expected = np.arange(lower, upper, np.timedelta64(1, "D"))
    else:
        lower = np.datetime64(selection.start, "h")
        upper = np.datetime64(selection.end + timedelta(days=1), "h")
        actual = values.astype("datetime64[h]")
        expected = np.arange(lower, upper, np.timedelta64(1, "h"))
    keep = (actual >= lower) & (actual < upper)
    dataset = dataset.isel({dimension: np.flatnonzero(keep)})
    actual = actual[keep]
    missing = np.setdiff1d(expected, actual)
    if missing.size:
        excerpt = ", ".join(str(item) for item in missing[:8])
        if missing.size > 8:
            excerpt += f", ... ({missing.size} periods total)"
        raise TimeCoverageError(
            f"missing GRIB validity periods for {selection.parameter.short_name} "
            f"{selection.level_type}/{selection.kind}/{selection.resolution}: {excerpt}"
        )
    if actual.size != expected.size:
        raise IncompatibleGribError(f"duplicate or unexpected {selection.resolution} validity periods")
    return dataset


def open_data(
    variable: str | int | Parameter,
    level_type: str,
    resolution: str,
    start: str | date | datetime | None = None,
    end: str | date | datetime | None = None,
    *,
    kind: str | None = None,
    root: str | Path = DEFAULT_ROOT,
    vertical_level: int | None = None,
    time_chunk: int = 6,
    max_files: int = 31,
):
    """Return a lazy xarray Dataset for a small, complete E5 selection.

    ``time`` is the analysis reference/validity time. Forecasts use a flat
    ``valid_time`` dimension with message-wise ``time`` (reference time),
    ``step`` (end step), ``step_start`` and raw ``step_range`` coordinates.
    Accumulated forecasts additionally carry ``interval_start``. No values or
    units are transformed. Call ``dataset.close()`` when finished.
    """
    if not isinstance(max_files, int) or max_files < 1:
        raise ValueError("max_files must be a positive integer")
    if not isinstance(time_chunk, int) or time_chunk < 1:
        raise ValueError("time_chunk must be a positive integer")
    if vertical_level is not None:
        if level_type == "sf" or not isinstance(vertical_level, int) or vertical_level < 1:
            raise ValueError("vertical_level must be a positive integer for pl or ml")
    if resolution in {"1H", "1D", "1M"} and start is not None:
        first = _date(start)
        last = _date(end) if end is not None else first
        if last >= first:
            count = {
                "1H": (last - first).days + 1,
                "1D": (last.year - first.year) * 12 + last.month - first.month + 1,
                "1M": last.year - first.year + 1,
            }[resolution]
            if count > max_files:
                raise ValueError(
                    f"selection needs {count} files, exceeding max_files={max_files}; "
                    "open shorter date ranges or explicitly raise the limit"
                )

    selection = resolve_files(
        variable, level_type, resolution, start, end, kind=kind, root=root
    ).require_complete()
    import xarray as xr

    opened = []
    datasets = []
    dimension = "valid_time" if selection.kind == "fc" and resolution != "IV" else "time"
    signature = None
    try:
        for path in selection.files:
            backend = {"indexpath": "", "errors": "raise"}
            filters = {"shortName": selection.parameter.short_name}
            if vertical_level is not None:
                filters["level"] = vertical_level
            backend["filter_by_keys"] = filters
            if selection.kind == "fc" and resolution != "IV":
                backend["time_dims"] = ("valid_time",)
            raw = xr.open_dataset(path, engine="cfgrib", backend_kwargs=backend)
            opened.append(raw)
            if len(raw.data_vars) != 1:
                raise IncompatibleGribError(f"expected one GRIB variable in {path}")
            actual_name = next(iter(raw.data_vars))
            attrs = raw[actual_name].attrs
            if attrs.get("GRIB_paramId") != selection.parameter.eccodes_param_id:
                raise IncompatibleGribError(
                    f"{path} has GRIB paramId {attrs.get('GRIB_paramId')}, expected "
                    f"{selection.parameter.eccodes_param_id}"
                )
            dataset = raw.rename({actual_name: selection.parameter.short_name})
            if selection.kind == "fc" and resolution != "IV":
                dataset = _forecast_coordinates(path, dataset)
            current = tuple(
                dataset[selection.parameter.short_name].attrs.get(key)
                for key in ("GRIB_paramId", "GRIB_typeOfLevel", "GRIB_stepType", "GRIB_gridType", "units")
            )
            if signature is not None and current != signature:
                raise IncompatibleGribError(f"GRIB parameter, level, step type, grid or units change in {path}")
            signature = current
            chunks = {}
            if dimension in dataset.dims:
                chunks[dimension] = time_chunk
            for vertical in ("isobaricInhPa", "hybrid"):
                if vertical in dataset.dims:
                    chunks[vertical] = 1
            datasets.append(dataset.chunk(chunks))

        combined = (
            datasets[0]
            if len(datasets) == 1
            else xr.concat(
                datasets, dim=dimension, join="exact", coords="minimal",
                compat="equals", combine_attrs="drop_conflicts",
            )
        )
        if resolution != "IV":
            combined = _clip_and_check(combined, selection, dimension)
        combined[selection.parameter.short_name].attrs["era5_levante_hourly_representation"] = (
            _availability(selection.parameter, level_type, resolution, selection.kind).hourly_representation
        )
        combined.set_close(lambda: [dataset.close() for dataset in opened])
        return combined
    except Exception:
        for dataset in opened:
            dataset.close()
        raise
