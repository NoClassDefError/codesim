# CodeSim Python package

`codesimpy` contains the complete Python backend: model construction, symbolic equations, numerical initialization and simulation, stability analysis, snapshot generation, and the resident service used by the VS Code extension.

The package intentionally keeps domain variable names such as `Vb`, `Sb`, `p`, `x`, `u`, `uref`, `f`, `g`, `Inputscale`, and `Outputscale`. MATLAB-only infrastructure such as generated `.m` functions, `.mat` caches, `addpath`, `rehash`, tables, and backend plotting is not carried into the Python implementation.

## Dependencies

- Python 3.10+
- NumPy
- SciPy
- SymPy

From the repository root:

```powershell
python -m pip install numpy scipy sympy
```

## Package layout

```text
codesimpy/
├─ api/
│  ├─ cli.py                    Resident stdin/stdout JSON service
├─ api/
│  └─ output_json_factory.py   Stdout events and persistent snapshots
├─ components/
│  ├─ vsgcc.py, vsgcl.py       Grid-forming converter models
│  ├─ gfl_vsc.py               Grid-following converter model
│  ├─ sg.py                    Synchronous generator
│  ├─ induction_motor.py       Induction motor
│  └─ ...                      Sources, loads, capacitor, and long-term models
├─ core/
│  ├─ device.py                Abstract device contract
│  ├─ system.py                Initialization, integration, and signal assembly
│  ├─ rl_grid.py               Symbolic RL network and power flow
│  ├─ small_signal_analyzer.py Modal and subsystem-interaction analysis
├─ systems/                    Seven registered network studies
└─ tests/                      Unit, migration, simulation, and stdio tests
```

## Class API

```python
from codesimpy.systems import HybridSystem

parameters = HybridSystem.defaultParameters({"SCR": 2.0, "enableGFL": True})
system = HybridSystem(parameters)

operatingPoint = system.initialize(
    ResidualTolerance=parameters["residualTolerance"],
)
analysis = system.smallSignal.analyze(operatingPoint)
```

Each system class owns its complete defaults through `defaultParameters(overrides=None)`, including derived values, fault breakpoints, output step, and initialization tolerance. Construct a system by passing that dictionary directly to its initializer. `network`, `devices`, `base`, and parameters are ordinary dictionaries.

All time-domain models use the same fault parameters:

- `faultStart_s` and `faultComplete_s`: start and end of fault application;
- `recoveryStart_s` and `recoveryComplete_s`: start and end of voltage recovery;
- `faultVoltage`: retained grid-voltage magnitude in per unit.

Legacy aliases are not accepted; use these canonical names throughout the project.

## Resident stdio service

Start the service from the repository root:

```powershell
python -u -m codesimpy.api.cli
```

Every stdin line is a request:

```json
{"id":1,"method":"getSystems","params":{}}
```

Every stdout line is a response or event. The public methods are `getSystems`, `model.load`, `model.reset`, `simulation.start`, `smallSignal.run`, `interaction.run`, and `server.shutdown`.

The service retains the current model and initialized operating point. `model.load` reuses them when the system, parameters, and model options have not changed. `model.reset` clears that in-memory state.

During simulation, stdout contains:

- `simulation.started`
- one or more `simulation.chunk` events
- `simulation.completed`
- the final response matching the request `id`

Each chunk is produced after both `calculateNetworkSignals` and the system's `calculateSignals` have run. Output signals appear first, followed by every state variable. Diagnostics must go to stderr so stdout remains valid JSON.

## Snapshots

`OutputJsonFactory` serves two related purposes:

- translate simulation chunks and responses for stdout;
- write `codegen/<System>-snapshot.json` for persistent results and layouts.

Snapshots are not used as the frontend transport. A final snapshot is written after complete signal calculation. Compatible existing signals, small-signal results, interaction results, and topology layout are preserved when a model descriptor is refreshed.

## Signals

`OutputJsonFactory.buildSignals` serializes plot-oriented output signals in this order:

1. bus voltage magnitude;
2. line current magnitude;
3. active power;
4. reactive power;
5. bus voltage angle;
6. all state variables.

The frontend combines active and reactive power into one default subplot, so these five output groups become four default plots.

## Tests

From the repository root:

```powershell
python -m unittest discover -s codesimpy/tests -t . -v
```

The suite covers the core symbolic/numerical model, migrated inventory, VSG-SMIB behavior, stdio requests, streaming chunks, and final snapshot generation.
