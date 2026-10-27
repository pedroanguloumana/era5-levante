"""Read-only cfgrib probe; run on Levante with ``python - < scripts/probe_levante.py``.

No GRIB index is written. The date is deliberately fixed for comparable results.
"""

import resource
import time

import cfgrib
import dask
import xarray as xr


ROOT = "/pool/data/ERA5/E5"
CASES = (
    ("tp-default", "sf/fc/1H/228/E5sf12_1H_2000-01-01_228.grb", {}, {"time": 1, "step": 1}),
    ("tp-valid", "sf/fc/1H/228/E5sf12_1H_2000-01-01_228.grb", {"time_dims": ("valid_time",)}, {"valid_time": 1}),
    ("q", "pl/an/1H/133/E5pl00_1H_2000-01-01_133.grb", {}, {"time": 1, "isobaricInhPa": 1}),
    ("r", "pl/an/1H/157/E5pl00_1H_2000-01-01_157.grb", {}, {"time": 1, "isobaricInhPa": 1}),
)


print("versions", cfgrib.__version__, xr.__version__, dask.__version__, flush=True)
for name, relpath, options, chunks in CASES:
    path = f"{ROOT}/{relpath}"
    print("start", name, path, flush=True)
    start = time.perf_counter()
    try:
        with xr.open_dataset(
            path,
            engine="cfgrib",
            backend_kwargs={"indexpath": "", **options},
            chunks=chunks,
        ) as ds:
            var_name = next(iter(ds.data_vars))
            var = ds[var_name]
            print("opened", name, round(time.perf_counter() - start, 2), "s", "rss_kib", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, flush=True)
            print("dims", dict(ds.sizes), "chunks", var.chunks, "tasks", len(var.data.__dask_graph__()), flush=True)
            for coord_name in ("time", "step", "valid_time"):
                if coord_name in ds:
                    coord = ds[coord_name]
                    print("coord", coord_name, coord.dims, coord.values.ravel()[:5], coord.values.ravel()[-5:], flush=True)
            print("attrs", {k: v for k, v in var.attrs.items() if k in ("units", "GRIB_shortName", "GRIB_paramId", "GRIB_stepType", "GRIB_stepRange", "GRIB_startStep", "GRIB_typeOfLevel")}, flush=True)
            selection = {dim: (slice(0, 16) if dim == "values" else 0) for dim in var.dims}
            sample_start = time.perf_counter()
            sample = var.isel(selection).compute()
            print("sample", name, round(time.perf_counter() - sample_start, 2), "s", "size", sample.size, "rss_kib", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, flush=True)
    except Exception as exc:
        print("ERROR", name, type(exc).__name__, str(exc), flush=True)
