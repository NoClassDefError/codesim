<p align="center">
  <img src="media/Icon.png" alt="CodeSim icon" width="160">
</p>

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
├─ media/                       Extension logo and activity-bar icon
├─ dist/                        Generated webview bundle
├─ out/                         Generated extension host JavaScript
└─ package.json                 Contributions, settings, and scripts
```

## User commands

| Command | Purpose |
| --- | --- |
| `CodeSim: Select Backend Directory` | Select the project root or its `codesimpy` package directory |
| `codesim: Open System Viewer` | Focus the topology view |
| `codesim: Open Signals` | Open the signals and analysis panel |

The extension uses the active interpreter selected by the Microsoft Python extension for the current workspace. Run `Python: Select Interpreter` to change it, then restart the CodeSim backend. There is no separate `codesim-frontend.pythonExecutable` setting. CodeSim contributes only the `codesim-frontend.backendPath` setting; when that path is unavailable, it also checks the open workspace folders.

## Runtime flow

1. The topology power button starts `<selected Python interpreter> -u -m codesimpy.api.cli`.
2. The extension sends line-delimited JSON requests through stdin.
3. It reads responses and live simulation events from stdout.
4. Webview messages update topology, parameters, plots, and analysis panels.
5. The stop button sends `server.shutdown` before terminating the process.

The snapshot remains a persistent artifact; normal frontend/backend communication does not poll files from disk.

## Interface behavior

- **Topology View** shows backend power, system selection, Signals, refresh, automatic layout, and save-layout actions.
- The VS Code status bar always shows whether the Python backend is stopped or running; its CodeSim indicator turns green while the backend process is active.
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
