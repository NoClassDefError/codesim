# CodeSim Python core

This package is the Python-first replacement for the MATLAB `core`,
`components`, `systems`, and API packages.

It deliberately keeps the MATLAB domain names (`Vb`, `Sb`, `p`, `x`, `u`,
`uref`, `f`, `g`, `Inputscale`, `Outputscale`) so the component classes can be
ported mechanically. MATLAB-only infrastructure was removed: generated `.m`
functions, `.mat` caches, source hashing, `addpath`/`rehash`, mixins, tables,
and backend plotting.

Runtime dependencies are `numpy`, `scipy`, and `sympy`.

The VS Code backend is a resident line-delimited JSON service:

```bash
python -u -m codesimpy.api.cli
```

It accepts `getSystems`, `model.load`, `model.reset`, `simulation.start`,
`smallSignal.run`, `interaction.run`, and `server.shutdown`. Simulation chunks
are written directly to stdout; snapshot files are still saved after complete
calculations but are no longer used to transport results to the frontend.

All 14 MATLAB component models and all 7 system models are available through
the class-based API. `SystemFactory.systemNames` contains the runnable systems.

```python
from codesimpy.api import SystemFactory

system, parameters, options = SystemFactory.create("HybridSystem")
operatingPoint = system.initialize()
analysis = system.smallSignal.analyze(operatingPoint)
```

`network`, `devices`, `base`, parameters, and options are plain dictionaries.
No compatibility wrappers or module-level helper functions are used.
