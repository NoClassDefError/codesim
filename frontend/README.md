# CodeSim VS Code extension

This directory contains the VS Code extension host and the React webviews used for topology, parameters, signals, small-signal results, and interaction analysis.

## Structure

```text
frontend/
├─ src/
│  ├─ extension.ts              Extension activation and Python process host
│  └─ test/                     VS Code extension tests
├─ webview/src/
│  ├─ App.tsx                   Topology view
│  ├─ SignalsApp.tsx            Signal and analysis view
│  ├─ bridge/                   Typed VS Code message bridge
│  ├─ components/               Toolbars, plots, tables, and panels
│  ├─ model/                    Snapshot schema and view-model conversion
│  └─ styles/                   Theme-aware webview styles
├─ media/                       Activity-bar icon
├─ dist/                        Generated webview bundle
├─ out/                         Generated extension host JavaScript
└─ package.json                 Contributions, settings, and scripts
```

## User commands

| Command | Purpose |
| --- | --- |
| `CodeSim: Select Python Executable` | Select a configured, workspace, or PATH interpreter, or browse to one manually |
| `CodeSim: Select Backend Directory` | Select the project root or its `codesimpy` package directory |
| `codesim: Open System Viewer` | Focus the topology view |
| `codesim: Open Signals` | Open the signals and analysis panel |

The extension contributes `codesim-frontend.pythonExecutable` and `codesim-frontend.backendPath`. Configuration is read across applicable workspace and folder scopes. When a configured backend path is unavailable, the extension also checks the open workspace folders.

## Runtime flow

1. The topology power button starts `python -u -m codesimpy.api.cli`.
2. The extension sends line-delimited JSON requests through stdin.
3. It reads responses and live simulation events from stdout.
4. Webview messages update topology, parameters, plots, and analysis panels.
5. The stop button sends `server.shutdown` before terminating the process.

The snapshot remains a persistent artifact; normal frontend/backend communication does not poll files from disk.

## Interface behavior

- **Topology View** shows backend power, system selection, Signals, refresh, automatic layout, and save-layout actions.
- Choosing a system loads it immediately; there is no separate Load button.
- **Signals View** contains Simulate, Small signal, and Interaction analysis actions.
- Four plots are created by default: bus voltage magnitude, line current, device active/reactive power, and bus voltage angle.
- Users can add or close plots, select a plot, and assign signals from the right-hand list.
- Trace colors are distinct within each plot.
- Derived signals can calculate magnitude, power, or error from two chosen signals.
- Colors use VS Code theme variables for light and dark themes.

## Development

Install dependencies:

```powershell
npm install
```

Compile the extension host and webview:

```powershell
npm run compile
```

Run static checks:

```powershell
npm run lint
```

Build the VSIX:

```powershell
npm run package:vsix
```

The package is written as `codesim-frontend-<version>.vsix` in this directory.

## Important files

- `src/extension.ts`: backend lifecycle, settings, stdio protocol, snapshots, and VS Code commands.
- `webview/src/components/Toolbar.tsx`: topology and Signals toolbar actions.
- `webview/src/components/WaveformPanel.tsx`: configurable waveform plots.
- `webview/src/components/SignalSidebar.tsx`: signal assignment and derived-signal calculations.
- `webview/src/components/SmallSignalPanel.tsx`: modes and symbolic expressions.
- `webview/src/components/InteractionAnalysisPanel.tsx`: interaction matrices and modal shifts.
- `webview/src/model/flowModel.ts`: converts backend descriptors to topology nodes, connections, and signals.
