# era5-levante

Find and lazily open **final ERA5 (E5)** GRIB files in DKRZ Levante's
`/pool/data/ERA5/E5` archive. The package does not transfer data and is meant
to run where that archive is mounted. It does not search ERA5T, ERA5.1, or
ERA5-Land.

## Install

On Levante, install ecCodes/cfgrib and xarray/Dask in a Conda environment,
then install this repository through SSH:

```bash
conda install -c conda-forge eccodes cfgrib xarray dask
pip install git+ssh://git@github.com/pedroanguloumana/era5-levante.git
```

GitHub SSH authentication must be configured on the machine running `pip`.
Use `pip install --upgrade git+ssh://git@github.com/pedroanguloumana/era5-levante.git`
to update an existing installation.

## Use in a script

```python
from era5_levante import search, resolve_files, open_data

for p in search("humidity"):
    print(p.code, p.name, p.short_name, p.units)
    for available in p.availability:
        print(" ", available.level_type, available.kind,
              available.resolutions, available.hourly_representation)
# 133 specific humidity: q, kg kg-1, pl and ml, instantaneous
# 157 relative humidity: r, %, pl, instantaneous

selection = resolve_files("q", "pl", "1H", "2000-01-01", "2000-01-03")
print(selection.files)     # sorted paths
print(selection.missing)   # missing daily file stamps, if any

with open_data("q", "pl", "1H", "2000-01-01", "2000-01-03",
               vertical_level=850) as ds:
    q = ds["q"]             # Dask-backed; still in kg kg-1
    subset = q.isel(values=slice(0, 100)).compute()

with open_data("tp", "sf", "1H", "2000-01-01", kind="fc") as ds:
    tp = ds["tp"]           # metres of accumulated water, no conversion
    print(ds[["time", "step", "step_start", "step_range", "valid_time"]])
    print(ds["interval_start"])
```

`open_data` raises `MissingCoverageError` if a requested file is absent and
`TimeCoverageError` if an existing file lacks a requested hour/day/month.
`resolve_files` reports absent file periods without raising; call
`selection.require_complete()` to raise. Dates are inclusive ISO calendar
dates. For `1H`, `1D`, and `1M`, files cover days, months, and years,
respectively; `open_data` clips daily/monthly values to the requested range.
For `IV`, omit dates and the single invariant file is returned. Pass
`root="/some/test/E5"` to either function for another archive root.

For variables with both surface analysis and forecast products, such as
`sst`, pass `kind="an"` or `kind="fc"`; the package never chooses one silently.
Pressure/model level selections accept `vertical_level=850` (hPa) or
`vertical_level=100` (model-level number). Without this filter all levels stay
lazy. Geographic data in the sampled E5 reduced Gaussian files use a
`values` dimension with latitude and longitude coordinates.

## Time and aggregation

For analyses, `time` is the GRIB reference time, `step` is zero, and
`valid_time` agrees with `time`. For forecasts, the data dimension is
`valid_time`; message-wise `time` is the forecast reference time and `step`
is the lead to validity. `step_start` and `step_range` preserve the GRIB
interval metadata. Accumulations also have `interval_start`. The API does
not turn accumulations into rates, change units, difference fields, or
rewrite time coordinates. Inspect `step_range` before interpreting an hourly
accumulation: in the sampled `tp` file, the value valid at
`2000-01-01 19:00` has **`step_range="0-13"`**, with reference time 06:00.
Its raw GRIB interval is therefore longer than one hour. The sampled
`1940-01-01` hourly `tp` file lacks validity times 00:00–06:00; `open_data`
reports this instead of returning a seemingly complete day.

DKRZ computes `1D` instantaneous fields as daily means and accumulated
fields as daily sums. `1M` fields are monthly **means of those daily
statistics**; `1M` precipitation is a mean daily total, not a monthly total.
The derived files' GRIB `stepType` may describe their stored representation
rather than the original hourly operation. Their `time` and `step` are the
derived file's GRIB fields, not the original hourly forecast initialization.
See DKRZ's
[ERA5 documentation](https://docs.dkrz.de/doc/dataservices/finding_and_accessing_data/era_data/)
and `/pool/data/ERA5/READMEs/README_ERA5_{1D,1M}_files.txt`.

## Resource and archive behavior

cfgrib's `.idx` writing is disabled with `indexpath=""`; the package needs
no writable cache and writes nothing beside GRIB files. Each file is opened
individually, checked for compatible GRIB metadata, and concatenated only
along its time dimension. The default Dask chunks contain six time steps and
one vertical level, with the full reduced Gaussian grid per chunk. A call is
limited to 31 files by default (`max_files` can be raised explicitly); use
several calls for long hourly series. Call `ds.close()` or use `with` to close
the underlying files.

In a read-only Levante probe (cfgrib 0.9.15.1, xarray 2025.10.1, Dask
2026.1.2), one full pressure-level `q` day opened and sampled in 2–4 s with
297 Dask tasks and about 240 MiB process peak RSS at that point. One-step
chunks had 889 tasks for the same day. Two surface forecast `tp` days used
26 tasks. Seven sequential opens and tiny sample reads reached 415–435 MiB
process peak RSS in repeated probes. These are observed timings on one
login node, not an upper bound for computations or other dates. The scripts
in `scripts/` reproduce the probes without creating GRIB indexes.

## Catalog and tests

Names, units, and IDs come from DKRZ's
`/pool/data/ERA5/READMEs/README_ERA5_PARAMIDs.txt`; level/type availability
reflects an E5 directory inspection on 2026-10-28. DKRZ's online table
lists `r` on model levels, but the inspected E5 archive has `r` on pressure
levels. A directory is only a hint of availability: each requested path is
checked. The E5 catalog also includes `ptype` (DKRZ number 527) from its
inspected GRIB header, which is absent from the parameter README.

Offline path/catalog tests:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

`scripts/check_levante.py` is a read-only integration probe for selected E5
GRIBs and requires the archive and Python dependencies on Levante.
