# Native runtime setup

Install uv and Python 3.11–3.13, then run `uv sync --frozen` and
`uv run python -m pytest -ra`. The locked Zig package supplies the default
compiler; compilation does not need a JavaScript runtime. ARMASM support is a
subset, not a full ARM assembler. See `toolchain/README.md` for compiler
selection, target libraries, licenses, and hardware limitations.

The existing `start.bat` uses `tools/launch.py`, which synchronizes the locked
Python environment before starting. To build the existing local interface it
also needs Bun. Set `LPC_LAB_PORT` to choose the local server port. Regenerating
newlib with `tools/vendor_c_library.py` needs Bun or the optional zstandard
Python package. The checked-in target archives need no regeneration to compile.
Frozen application packaging is not included; this contribution supports the
source runtime only. CI declares a platform matrix, but only locally reported
results are verified until those jobs run.

The bundled curricular fixtures default to `fixtures/curricular`; set
`CURRICULAR_ES` for an optional external corpus. See its provenance manifest.

## API additions

C remains the default language for `POST /api/compile`; `language: "asm"`
selects the documented ARMASM subset. Successful builds retain ELF debug
metadata in addition to the existing HEX response. `POST /api/debug` supports
register/symbol state, source/address breakpoints, stepping and bounded RAM/flash
reads. Invalid builds and uploads preserve the previous program and wiring.

Individual patch wires use `POST /api/physical` with
`{"action":"connect-wire","a":"CNA.1","b":"CNA1.1"}`. The state includes
wire pairs and live header-contact information. The pre-existing local frontend
is unchanged; it does not gain the separate project's patch-wire editor or
debugger panels. These additions are available through the native API.

Functional timing tests use controlled clocks. The optional wall-clock benchmark
and its unresolved host service-cadence failure are documented in
[REALTIME_PERFORMANCE.md](REALTIME_PERFORMANCE.md). No throughput claim is implied
by excluding that benchmark from the default functional selection.

## Optional original-corpus reports

The self-contained regression suite uses the licensed bundled subset. Full
26-source C and 20-source assembly study reports require an external complete
ES corpus, selected with `--corpus PATH` or `CURRICULAR_ES`. The tools reject
missing full-corpus input before execution rather than treating partial coverage
as a full report. For a bundled C probe, select it explicitly:

```sh
uv run python tools/test_c_course_outputs.py --only Lab6/init.c --opts 2
uv run python tools/test_assembly_corpus.py --corpus path/to/ES --allow-source-issues
```

A selected C report records its selected probes. Full study ledgers can combine
fresh bounded execution with separately referenced checks; a compiled boot or a
reference to another check is not certification of every intended program output.
