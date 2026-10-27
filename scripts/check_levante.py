"""Read-only E5 integration checks. Run on Levante in an env with cfgrib/eccodes."""

import json
import resource
import time

import numpy as np
import xarray as xr

from era5_levante import TimeCoverageError, open_data, resolve_files


def inspect(name, variable, level_type, resolution, start=None, end=None, **kwargs):
    selected = resolve_files(variable, level_type, resolution, start, end, kind=kwargs.get("kind"))
    assert selected.complete and selected.files, selected
    before = time.perf_counter()
    with open_data(variable, level_type, resolution, start, end, **kwargs) as dataset:
        field = dataset[variable]
        assert hasattr(field.data, "__dask_graph__")
        assert field.attrs["GRIB_shortName"] == variable
        tasks = len(field.data.__dask_graph__())
        selection = {dim: (slice(0, 16) if dim == "values" else 0) for dim in field.dims}
        sample = field.isel(selection).compute()
        assert np.isfinite(sample.values).all()
        if resolution != "IV":
            time_name = "valid_time" if selected.kind == "fc" else "time"
            assert dataset.sizes[time_name] > 0
        if name == "q-pl":
            assert dataset.sizes["time"] == 24
            assert dataset.sizes["isobaricInhPa"] == 37
            assert dataset.step.values == np.timedelta64(0, "ns")
        if name == "r-pl":
            assert dataset.sizes["time"] == 24
            assert dataset.isobaricInhPa.item() == 850
        if name == "tp-hourly":
            assert dataset.sizes["valid_time"] == 48
            hour19 = dataset.sel(valid_time="2000-01-01T19:00:00")
            assert str(hour19.step_range.values.item()) == "0-13"
            assert hour19.step.values == np.timedelta64(13, "h")
            assert hour19.step_start.values == np.timedelta64(0, "h")
            assert hour19.time.values == np.datetime64("2000-01-01T06:00:00", "ns")
            assert hour19.interval_start.values == np.datetime64("2000-01-01T06:00:00", "ns")
            assert dataset["tp"].attrs["units"] == "m"
            with xr.open_dataset(
                selected.files[0], engine="cfgrib",
                backend_kwargs={"indexpath": "", "time_dims": ("valid_time",)},
            ) as raw:
                expected = raw["tp"].sel(valid_time="2000-01-01T19:00:00").isel(values=slice(0, 16)).values
                observed = hour19["tp"].isel(values=slice(0, 16)).compute().values
                np.testing.assert_array_equal(observed, expected)
        if name == "tp-daily":
            assert dataset.sizes["valid_time"] == 3
            assert field.attrs["GRIB_stepType"] == "instant"
        if name == "tp-monthly":
            assert dataset.sizes["valid_time"] == 2
            assert field.attrs["GRIB_stepType"] == "avg"
        result = {
            "case": name,
            "files": len(selected.files),
            "dimensions": dict(dataset.sizes),
            "dask_tasks": tasks,
            "seconds_open_and_sample": round(time.perf_counter() - before, 2),
            "max_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
        }
        print(json.dumps(result), flush=True)


inspect("q-pl", "q", "pl", "1H", "2000-01-01")
inspect("r-pl", "r", "pl", "1H", "2000-01-01", vertical_level=850)
inspect("q-ml", "q", "ml", "1H", "2000-01-01", vertical_level=100)
inspect("tp-hourly", "tp", "sf", "1H", "2000-01-01", "2000-01-02")
inspect("tp-daily", "tp", "sf", "1D", "2000-01-01", "2000-01-03")
inspect("tp-monthly", "tp", "sf", "1M", "2000-01-01", "2000-02-28")
inspect("lsm-iv", "lsm", "sf", "IV", kind="an")

historical = resolve_files("tp", "sf", "1H", "1940-01-01")
if historical.complete:
    try:
        with open_data("tp", "sf", "1H", "1940-01-01"):
            print(json.dumps({"case": "tp-1940-01-01", "coverage": "24 hours"}), flush=True)
    except TimeCoverageError as exc:
        print(json.dumps({"case": "tp-1940-01-01", "coverage": str(exc)}), flush=True)
else:
    print(json.dumps({"case": "tp-1940-01-01", "missing_files": historical.missing}), flush=True)
