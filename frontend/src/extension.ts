import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';

const extensionNamespace = 'codesim-frontend';
const viewerCommandId = `${extensionNamespace}.openViewer`;
const signalsCommandId = `${extensionNamespace}.openSignals`;
const selectBackendCommandId = `${extensionNamespace}.selectBackendDirectory`;
const viewerViewId = `${extensionNamespace}.viewer`;
const backendStatusColorId = 'codesim.backendRunningForeground';
const defaultSystem = 'VSGSMIBSystem';
const pythonExtensionId = 'ms-python.python';

type AnalysisKind = 'simulation' | 'smallSignal' | 'interaction' | 'transientVoltage';
// 'viewer' is the topology sidebar, 'signals' the results panel.
type WebviewRole = 'viewer' | 'signals';
type SnapshotReason = 'load' | 'analysis' | 'request';

// Results the topology viewer never reads. Simulation traces alone can be
// hundreds of MB of JSON for large systems, so they are not sent to it.
const viewerOmittedSnapshotFields = [
	'signals',
	'simulationData',
	'smallSignal',
	'interactionAnalysis',
	'transientVoltage',
];

function appendInPlace(target: unknown[], source: unknown): void {
	if (!Array.isArray(source)) {
		return;
	}
	for (const value of source) {
		target.push(value);
	}
}

interface SourceReference {
	file: string;
	line?: number;
	column?: number;
}

interface WebviewMessage {
	type?: string;
	reference?: SourceReference;
	layout?: unknown;
	systemName?: string;
	analysis?: AnalysisKind;
	parameterName?: string;
	parameterValue?: unknown;
	slowStateNames?: string[];
	maxSamples?: number;
}

interface BackendResponse {
	id?: number;
	ok?: boolean;
	result?: Record<string, unknown> | string[];
	error?: string;
	type?: string;
	requestId?: number;
	[key: string]: unknown;
}

interface PythonEnvironmentPath {
	readonly path: string;
}

interface ResolvedPythonEnvironment {
	readonly executable: {
		readonly uri: vscode.Uri | undefined;
	};
}

interface PythonExtensionApi {
	readonly environments: {
		getActiveEnvironmentPath(
			resource?: vscode.Uri | vscode.WorkspaceFolder,
		): PythonEnvironmentPath | undefined;
		resolveEnvironment(
			environment: PythonEnvironmentPath | string,
		): Promise<ResolvedPythonEnvironment | undefined>;
	};
}

export function activate(context: vscode.ExtensionContext): void {
	const host = new CodeSimHost(context);
	const viewerProvider = new CodeSimViewerProvider(context, host);

	context.subscriptions.push(
		vscode.window.registerWebviewViewProvider(viewerViewId, viewerProvider, {
			webviewOptions: { retainContextWhenHidden: true },
		}),
		vscode.commands.registerCommand(viewerCommandId, async () => {
			await vscode.commands.executeCommand(`${viewerViewId}.focus`);
		}),
		vscode.commands.registerCommand(signalsCommandId, () => {
			SignalsPanel.createOrShow(context, host);
		}),
		vscode.commands.registerCommand(selectBackendCommandId, () => host.selectBackendDirectory()),
	);
}

class CodeSimHost {
	private readonly webviews = new Map<vscode.Webview, WebviewRole>();
	private readonly output: vscode.OutputChannel;
	private readonly backendStatus: vscode.StatusBarItem;
	private currentSnapshotUri: vscode.Uri | undefined;
	private currentSnapshot: unknown;
	private selectedSystem = defaultSystem;
	private parameterOverrides: Record<string, unknown> = {};
	private backendProcess: ChildProcessWithoutNullStreams | undefined;
	private backendStart: Promise<void> | undefined;
	private backendBuffer = '';
	private backendMessageQueue: Promise<void> = Promise.resolve();
	private nextRequestId = 1;
	private activeAction: string | undefined;
	private readonly pendingRequests = new Map<number, {
		resolve: (value: Record<string, unknown> | string[]) => void;
		reject: (error: Error) => void;
	}>();

	constructor(private readonly context: vscode.ExtensionContext) {
		this.output = vscode.window.createOutputChannel('CodeSim');
		this.backendStatus = vscode.window.createStatusBarItem(
			`${extensionNamespace}.backendStatus`,
			vscode.StatusBarAlignment.Left,
			10,
		);
		this.backendStatus.name = 'CodeSim Python backend';
		this.backendStatus.command = viewerCommandId;
		this.setBackendStatus(false);
		this.backendStatus.show();
		context.subscriptions.push(
			this.output,
			this.backendStatus,
			{ dispose: () => { void this.stopBackend(); } },
		);
	}

	private setBackendStatus(running: boolean): void {
		this.backendStatus.text = running
			? '$(vm-running) CodeSim: Running'
			: '$(circle-slash) CodeSim: Stopped';
		this.backendStatus.tooltip = running
			? 'CodeSim Python backend is running. Click to open the System Viewer.'
			: 'CodeSim Python backend is stopped. Click to open the System Viewer.';
		this.backendStatus.color = running
			? new vscode.ThemeColor(backendStatusColorId)
			: undefined;
		this.backendStatus.accessibilityInformation = {
			label: running
				? 'CodeSim Python backend is running'
				: 'CodeSim Python backend is stopped',
		};
	}

	registerWebview(webview: vscode.Webview, role: WebviewRole): () => void {
		this.webviews.set(webview, role);
		return () => this.webviews.delete(webview);
	}

	async selectBackendDirectory(): Promise<void> {
		const workspaceUri = vscode.workspace.workspaceFolders?.[0]?.uri;
		const configured = vscode.workspace
			.getConfiguration(extensionNamespace, workspaceUri)
			.get<string>('backendPath', '');
		const selected = await vscode.window.showOpenDialog({
			canSelectFiles: false,
			canSelectFolders: true,
			canSelectMany: false,
			defaultUri: configured
				? vscode.Uri.file(path.isAbsolute(configured)
					? configured
					: path.resolve(vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? '', configured))
				: vscode.workspace.workspaceFolders?.[0]?.uri,
			openLabel: 'Use this directory',
			title: 'Select the CodeSim backend directory',
		});
		if (!selected?.[0]) {
			return;
		}
		const selectedPath = selected[0].fsPath;
		const backend = fs.existsSync(path.join(selectedPath, 'codesimpy', 'core', 'system.py'))
			? selectedPath
			: fs.existsSync(path.join(selectedPath, 'core', 'system.py'))
				? path.dirname(selectedPath)
				: undefined;
		if (!backend) {
			void vscode.window.showErrorMessage(
				'Select the codesim project directory or its codesimpy package directory.',
			);
			return;
		}
		await vscode.workspace.getConfiguration(extensionNamespace, workspaceUri).update(
			'backendPath', backend, vscode.ConfigurationTarget.Workspace,
		);
		void vscode.window.showInformationMessage(
			`CodeSim backend directory: ${backend}. Restart the backend to apply it.`,
		);
	}

	async handleMessage(message: WebviewMessage, source?: vscode.Webview): Promise<void> {
		switch (message.type) {
			case 'requestBackendInfo':
				await this.sendBackendInfo();
				break;
			case 'startBackend':
				await this.startBackendFromUi();
				break;
			case 'stopBackend':
				await this.stopBackend();
				break;
			case 'requestSystemSnapshot':
				// Answer only the webview that asked: opening the Signals panel
				// must not re-send (and re-lay out) the snapshot in the viewer.
				if (this.currentSnapshot) {
					await this.postSnapshot(this.currentSnapshot, 'request', source);
				}
				break;
			case 'loadSystemDescriptor':
				await this.runDescriptor(message.systemName);
				break;
			case 'runAnalysis':
				await this.runAnalysis(message.analysis, message.systemName);
				break;
			case 'runTransientVoltage':
				await this.runTransientVoltage(
					message.systemName, message.slowStateNames, message.maxSamples,
				);
				break;
			case 'updateSystemParameter':
				this.updateSystemParameter(message.parameterName, message.parameterValue);
				break;
			case 'openSignalsView':
				SignalsPanel.createOrShow(this.context, this);
				break;
			case 'openSource':
				await this.openSource(message.reference);
				break;
			case 'saveLayout':
				await this.saveLayout(message.layout);
				break;
		}
	}

	private async sendBackendInfo(): Promise<void> {
		let systems: string[] = [];
		if (this.backendProcess) {
			try {
				systems = await this.request<string[]>('getSystems', {});
			} catch (error) {
				const detail = error instanceof Error ? error.message : String(error);
				this.output.appendLine(`[backend] ${detail}`);
			}
		}
		await this.postToWebviews({
			type: 'backendInfo',
			systems,
			selectedSystem: this.selectedSystem,
			backendRunning: Boolean(this.backendProcess),
			running: Boolean(this.activeAction),
		});
	}

	private async startBackendFromUi(): Promise<void> {
		try {
			await this.startBackend();
			await this.sendBackendInfo();
		} catch (error) {
			const detail = error instanceof Error ? error.message : String(error);
			void vscode.window.showErrorMessage(`Unable to start CodeSim backend: ${detail}`);
			await this.sendBackendInfo();
		}
	}

	private async runDescriptor(systemName: string | undefined): Promise<void> {
		const selected = await this.validateSystemName(systemName);
		if (selected) {
			this.parameterOverrides = {};
			await this.runBackend('descriptor', selected);
		}
	}

	private updateSystemParameter(name: string | undefined, value: unknown): void {
		if (name) {
			this.parameterOverrides[name] = value;
		}
	}

	private async runAnalysis(
		analysis: AnalysisKind | undefined,
		systemName: string | undefined,
	): Promise<void> {
		if (!analysis) {
			return;
		}
		const selected = await this.validateSystemName(systemName);
		if (!selected) {
			return;
		}
		if (analysis === 'interaction' && selected !== 'HybridSystem') {
			void vscode.window.showWarningMessage(
				'Interaction analysis currently supports HybridSystem only.',
			);
			return;
		}
		await this.runBackend(analysis, selected);
	}

	private async runTransientVoltage(
		systemName: string | undefined,
		slowStateNames: string[] | undefined,
		maxSamples: number | undefined,
	): Promise<void> {
		const selected = await this.validateSystemName(systemName);
		if (!selected) {
			return;
		}
		if (!slowStateNames?.length) {
			void vscode.window.showErrorMessage('Select one or more slow states for voltage decomposition.');
			return;
		}
		await this.runBackend('transientVoltage', selected, {
			slowStateNames,
			maxSamples,
		});
	}

	private async validateSystemName(systemName: string | undefined): Promise<string | undefined> {
		try {
			const systems = await this.request<string[]>('getSystems', {});
			const selected = systemName?.trim();
			if (!selected || !systems.includes(selected)) {
				void vscode.window.showErrorMessage('Select a valid CodeSim System subclass.');
				return undefined;
			}
			this.selectedSystem = selected;
			return selected;
		} catch (error) {
			const detail = error instanceof Error ? error.message : String(error);
			void vscode.window.showErrorMessage(detail);
			return undefined;
		}
	}

	private backendPath(): string {
		const workspaceFolders = vscode.workspace.workspaceFolders ?? [];
		const configuredPaths = new Set<string>();
		for (const uri of [undefined, ...workspaceFolders.map(({ uri }) => uri)]) {
			const configured = vscode.workspace
				.getConfiguration(extensionNamespace, uri)
				.get<string>('backendPath', '')
				.trim();
			if (configured) {
				configuredPaths.add(configured);
			}
		}
		const candidates: string[] = [];
		for (const configured of configuredPaths) {
			if (path.isAbsolute(configured)) {
				candidates.push(configured);
			} else {
				for (const { uri } of workspaceFolders) {
					candidates.push(path.resolve(uri.fsPath, configured));
				}
			}
		}
		for (const { uri } of workspaceFolders) {
			candidates.push(uri.fsPath, path.join(uri.fsPath, 'codesim'));
		}
		candidates.push(path.resolve(this.context.extensionPath, '..'));
		for (const candidate of candidates) {
			if (candidate && fs.existsSync(path.join(candidate, 'codesimpy', 'core', 'system.py'))) {
				return candidate;
			}
			if (candidate && fs.existsSync(path.join(candidate, 'core', 'system.py'))) {
				return path.dirname(candidate);
			}
		}
		this.output.appendLine(`[backend] checked: ${candidates.join(' | ')}`);
		throw new Error(
			`Cannot find codesimpy/core/system.py. backendPath: ${[...configuredPaths].join(' | ') || '(empty)'}.`,
		);
	}

	private async runBackend(
		action: 'descriptor' | AnalysisKind,
		systemName: string,
		analysisParameters: Record<string, unknown> = {},
	): Promise<void> {
		if (this.activeAction) {
			void vscode.window.showWarningMessage('A CodeSim Python task is already running.');
			return;
		}

		try {
			this.activeAction = action;
			this.output.show(true);
			this.output.appendLine('');
			this.output.appendLine(`=== ${systemName} · ${action} ===`);
			await this.postToWebviews({
				type: 'backendStatus',
				running: true,
				action,
				selectedSystem: systemName,
			});
			const method = action === 'descriptor'
				? 'model.load'
				: action === 'simulation'
					? 'simulation.start'
					: action === 'smallSignal'
						? 'smallSignal.run'
						: action === 'interaction'
							? 'interaction.run'
							: 'transientVoltage.run';
			const result = await this.request<Record<string, unknown>>(method, {
				systemName,
				parameters: this.parameterOverrides,
				options: {},
				...analysisParameters,
			});
			if (typeof result.snapshotFile === 'string') {
				this.currentSnapshotUri = vscode.Uri.file(result.snapshotFile);
			}
			const reason: SnapshotReason = action === 'descriptor' ? 'load' : 'analysis';
			if (!(await this.acceptSnapshot(result.descriptor, reason))) {
				throw new Error('Python returned an invalid System descriptor.');
			}
			this.output.appendLine('=== completed ===');
		} catch (error) {
			const detail = error instanceof Error ? error.message : String(error);
			this.output.appendLine(`=== failed · ${detail} ===`);
			void vscode.window.showErrorMessage(`CodeSim backend failed: ${detail}`);
		} finally {
			this.activeAction = undefined;
			await this.postToWebviews({
				type: 'backendStatus',
				running: false,
				selectedSystem: this.selectedSystem,
			});
		}
	}

	private async request<T extends Record<string, unknown> | string[]>(
		method: string,
		params: Record<string, unknown>,
	): Promise<T> {
		if (!this.backendProcess) {
			throw new Error('Start the CodeSim backend first.');
		}
		const id = this.nextRequestId++;
		return await new Promise<T>((resolve, reject) => {
			this.pendingRequests.set(id, {
				resolve: (value) => resolve(value as T),
				reject,
			});
			this.backendProcess?.stdin.write(`${JSON.stringify({ id, method, params })}\n`);
		});
	}

	private async startBackend(): Promise<void> {
		if (this.backendProcess) {
			return;
		}
		if (this.backendStart) {
			return await this.backendStart;
		}
		const executable = await this.pythonExecutable();
		this.backendStart = new Promise<void>((resolve, reject) => {
			this.output.appendLine(`[backend] Python executable: ${executable}`);
			const process = spawn(executable, ['-u', '-m', 'codesimpy.api.cli'], {
				cwd: this.backendPath(), windowsHide: true, stdio: 'pipe',
			});
			this.backendProcess = process;
			process.stdout.setEncoding('utf8');
			process.stderr.setEncoding('utf8');
			process.stdout.on('data', (chunk: string) => this.readBackendOutput(chunk));
			process.stderr.on('data', (chunk: string) => this.output.append(chunk));
			process.once('spawn', () => {
				this.setBackendStatus(true);
				resolve();
			});
			process.once('error', (error) => {
				this.backendProcess = undefined;
				this.backendStart = undefined;
				this.setBackendStatus(false);
				reject(error);
			});
			process.once('close', (code) => {
				if (this.backendProcess === process) {
					this.backendProcess = undefined;
				}
				this.backendStart = undefined;
				this.activeAction = undefined;
				this.setBackendStatus(false);
				const error = new Error(`CodeSim Python backend exited with code ${code}.`);
				for (const pending of this.pendingRequests.values()) {
					pending.reject(error);
				}
				this.pendingRequests.clear();
				void this.postToWebviews({
					type: 'backendInfo',
					systems: [],
					selectedSystem: this.selectedSystem,
					backendRunning: false,
					running: false,
				});
			});
		});
		return await this.backendStart;
	}

	private async pythonExecutable(): Promise<string> {
		const extension = vscode.extensions.getExtension<PythonExtensionApi>(pythonExtensionId);
		if (!extension) {
			throw new Error(
				'Install and enable the Microsoft Python extension, then run "Python: Select Interpreter".',
			);
		}
		const pythonApi = extension.isActive ? extension.exports : await extension.activate();
		const workspace = vscode.workspace.workspaceFolders?.[0];
		const activeEnvironment = pythonApi?.environments
			.getActiveEnvironmentPath(workspace);
		if (!activeEnvironment) {
			throw new Error('Run "Python: Select Interpreter" before starting the CodeSim backend.');
		}
		const resolvedEnvironment = await pythonApi.environments
			.resolveEnvironment(activeEnvironment);
		const executable = resolvedEnvironment?.executable.uri?.fsPath;
		if (!executable || !fs.existsSync(executable)) {
			throw new Error(
				'The interpreter selected by the Microsoft Python extension is unavailable. ' +
				'Run "Python: Select Interpreter" and choose a valid environment.',
			);
		}
		return executable;
	}

	private readBackendOutput(chunk: string): void {
		this.backendBuffer += chunk;
		const lines = this.backendBuffer.split(/\r?\n/);
		this.backendBuffer = lines.pop() ?? '';
		for (const line of lines) {
			if (!line.trim()) {
				continue;
			}
			try {
				const message = JSON.parse(line) as BackendResponse;
				this.backendMessageQueue = this.backendMessageQueue
					.then(() => this.handleBackendMessage(message))
					.catch((error) => {
						this.output.appendLine(`[backend message] ${String(error)}`);
					});
			} catch {
				this.output.appendLine(`[backend stdout] ${line}`);
			}
		}
	}

	private async handleBackendMessage(message: BackendResponse): Promise<void> {
		if (message.type) {
			if (message.type === 'simulation.started' && this.isSystemSnapshot(this.currentSnapshot)) {
				(this.currentSnapshot as Record<string, unknown>).signals = [];
			}
			if (message.type === 'simulation.chunk' && this.isSystemSnapshot(this.currentSnapshot)) {
				this.appendSimulationChunk(
					this.currentSnapshot as Record<string, unknown>,
					message.signals,
				);
			}
			// Streaming events only matter to the Signals panel.
			await this.postToWebviews(
				message,
				message.type.startsWith('simulation.') ? 'signals' : undefined,
			);
			return;
		}
		if (typeof message.id !== 'number') {
			return;
		}
		const pending = this.pendingRequests.get(message.id);
		if (!pending) {
			return;
		}
		this.pendingRequests.delete(message.id);
		if (message.ok) {
			pending.resolve(message.result ?? {});
		} else {
			pending.reject(new Error(message.error ?? 'Python backend request failed.'));
		}
	}

	private async stopBackend(): Promise<void> {
		const process = this.backendProcess;
		if (!process) {
			await this.sendBackendInfo();
			return;
		}
		const id = this.nextRequestId++;
		process.stdin.write(`${JSON.stringify({ id, method: 'server.shutdown', params: {} })}\n`);
		setTimeout(() => {
			if (this.backendProcess === process) {
				process.kill();
			}
		}, 500).unref();
	}

	/**
	 * Fold one streamed chunk into the cached snapshot.
	 *
	 * Each trace keeps one array that grows in place; rebuilding the arrays
	 * per chunk ([...old, ...chunk]) made a run with N samples cost O(N²).
	 */
	private appendSimulationChunk(snapshot: Record<string, unknown>, incoming: unknown): void {
		if (!Array.isArray(incoming)) {
			return;
		}
		const signals = snapshot.signals as Array<Record<string, unknown>>;
		const byId = new Map(signals.map((signal) => [signal.id, signal]));
		for (const signal of incoming as Array<Record<string, unknown>>) {
			const existing = byId.get(signal.id);
			if (existing && Array.isArray(existing.time) && Array.isArray(existing.values)) {
				appendInPlace(existing.time, signal.time);
				appendInPlace(existing.values, signal.values);
			} else if (!existing) {
				// Copy so the cached trace never aliases the message being posted.
				const copy = {
					...signal,
					time: Array.isArray(signal.time) ? [...signal.time] : [],
					values: Array.isArray(signal.values) ? [...signal.values] : [],
				};
				signals.push(copy);
				byId.set(signal.id, copy);
			}
		}
	}

	private async postToWebviews(message: unknown, role?: WebviewRole): Promise<void> {
		await Promise.all(Array.from(this.webviews)
			.filter(([, webviewRole]) => !role || webviewRole === role)
			.map(([webview]) => webview.postMessage(message)));
	}

	/** Send a snapshot; the topology viewer gets it without analysis results. */
	private async postSnapshot(
		snapshot: unknown,
		reason: SnapshotReason,
		only?: vscode.Webview,
	): Promise<void> {
		let viewerMessage: unknown;
		await Promise.all(Array.from(this.webviews)
			.filter(([webview]) => !only || webview === only)
			.map(([webview, role]) => {
				if (role === 'viewer') {
					viewerMessage ??= {
						type: 'systemSnapshot',
						reason,
						snapshot: this.viewerSnapshot(snapshot),
					};
					return webview.postMessage(viewerMessage);
				}
				return webview.postMessage({ type: 'systemSnapshot', reason, snapshot });
			}));
	}

	private viewerSnapshot(snapshot: unknown): unknown {
		if (!snapshot || typeof snapshot !== 'object') {
			return snapshot;
		}
		const trimmed: Record<string, unknown> = { ...snapshot as Record<string, unknown> };
		for (const field of viewerOmittedSnapshotFields) {
			delete trimmed[field];
		}
		trimmed.signals = [];
		return trimmed;
	}

	private async acceptSnapshot(value: unknown, reason: SnapshotReason): Promise<boolean> {
		try {
			const snapshot = this.unwrapSnapshot(value);
			if (!this.isSystemSnapshot(snapshot)) {
				throw new Error(
					'The backend response does not contain system, components, connections, and signals.',
				);
			}
			this.currentSnapshot = snapshot;
			await this.postSnapshot(snapshot, reason);
			return true;
		} catch (error) {
			const detail = error instanceof Error ? error.message : String(error);
			void vscode.window.showErrorMessage(`Unable to load the CodeSim model: ${detail}`);
			return false;
		}
	}

	private async saveLayout(layout: unknown): Promise<void> {
		if (!layout || typeof layout !== 'object') {
			void vscode.window.showErrorMessage('Unable to save the layout: invalid layout data.');
			return;
		}
		const snapshotUri = this.currentSnapshotUri;
		if (!snapshotUri) {
			void vscode.window.showWarningMessage(
				'Load a System descriptor before saving the topology layout.',
			);
			return;
		}

		const temporaryUri = vscode.Uri.file(`${snapshotUri.fsPath}.CodeSim-layout.tmp`);
		try {
			const contents = await vscode.workspace.fs.readFile(snapshotUri);
			const document = JSON.parse(Buffer.from(contents).toString('utf8')) as unknown;
			if (!document || typeof document !== 'object') {
				throw new Error('The snapshot root is not a JSON object.');
			}
			const root = document as Record<string, unknown>;
			const descriptor = root.frontendDescriptor &&
				typeof root.frontendDescriptor === 'object'
				? root.frontendDescriptor as Record<string, unknown>
				: root;
			descriptor.layout = layout;
			const serialized = Buffer.from(`${JSON.stringify(document, null, 2)}\n`, 'utf8');
			await vscode.workspace.fs.writeFile(temporaryUri, serialized);
			await vscode.workspace.fs.rename(temporaryUri, snapshotUri, { overwrite: true });
			void vscode.window.showInformationMessage(
				`Saved topology layout to ${path.basename(snapshotUri.fsPath)}`,
			);
		} catch (error) {
			const detail = error instanceof Error ? error.message : String(error);
			try {
				await vscode.workspace.fs.delete(temporaryUri);
			} catch {
				// The temporary file may not have been created.
			}
			void vscode.window.showErrorMessage(`Unable to save the topology layout: ${detail}`);
		}
	}

	private unwrapSnapshot(value: unknown): unknown {
		if (!value || typeof value !== 'object') {
			return value;
		}
		const record = value as Record<string, unknown>;
		return record.frontendDescriptor ?? value;
	}

	private isSystemSnapshot(value: unknown): boolean {
		if (!value || typeof value !== 'object') {
			return false;
		}
		const record = value as Record<string, unknown>;
		return Boolean(record.system) &&
			Array.isArray(record.components) &&
			Array.isArray(record.connections) &&
			Array.isArray(record.signals);
	}

	private async openSource(reference: SourceReference | undefined): Promise<void> {
		if (!reference || typeof reference.file !== 'string') {
			return;
		}
		try {
			const document = await vscode.workspace.openTextDocument(vscode.Uri.file(reference.file));
			const editor = await vscode.window.showTextDocument(document);
			const line = Math.max(0, (reference.line ?? 1) - 1);
			const column = Math.max(0, (reference.column ?? 1) - 1);
			const position = new vscode.Position(line, column);
			editor.selection = new vscode.Selection(position, position);
			editor.revealRange(
				new vscode.Range(position, position),
				vscode.TextEditorRevealType.InCenter,
			);
		} catch (error) {
			const detail = error instanceof Error ? error.message : String(error);
			void vscode.window.showErrorMessage(`Unable to open source file: ${detail}`);
		}
	}
}

class CodeSimViewerProvider implements vscode.WebviewViewProvider {
	constructor(
		private readonly context: vscode.ExtensionContext,
		private readonly host: CodeSimHost,
	) {}

	resolveWebviewView(view: vscode.WebviewView): void {
		const distUri = vscode.Uri.joinPath(this.context.extensionUri, 'dist');
		view.webview.options = {
			enableScripts: true,
			localResourceRoots: [distUri],
		};
		view.webview.html = getHtml(this.context, view.webview, 'viewer');
		const unregister = this.host.registerWebview(view.webview, 'viewer');
		const messageSubscription = view.webview.onDidReceiveMessage(
			(message: WebviewMessage) => this.host.handleMessage(message, view.webview),
		);
		view.onDidDispose(() => {
			unregister();
			messageSubscription.dispose();
		});
	}
}

class SignalsPanel {
	private static current: SignalsPanel | undefined;
	private readonly disposables: vscode.Disposable[] = [];
	private readonly unregisterWebview: () => void;

	private constructor(
		private readonly panel: vscode.WebviewPanel,
		context: vscode.ExtensionContext,
		host: CodeSimHost,
	) {
		this.panel.webview.html = getHtml(context, this.panel.webview, 'signals');
		this.unregisterWebview = host.registerWebview(this.panel.webview, 'signals');
		this.panel.onDidDispose(() => this.dispose(), undefined, this.disposables);
		this.panel.webview.onDidReceiveMessage(
			(message: WebviewMessage) => host.handleMessage(message, this.panel.webview),
			undefined,
			this.disposables,
		);
	}

	static createOrShow(context: vscode.ExtensionContext, host: CodeSimHost): void {
		if (SignalsPanel.current) {
			SignalsPanel.current.panel.reveal();
			return;
		}
		const distUri = vscode.Uri.joinPath(context.extensionUri, 'dist');
		const panel = vscode.window.createWebviewPanel(
			'CodeSimSignals',
			'CodeSim Signals',
			vscode.window.activeTextEditor?.viewColumn ?? vscode.ViewColumn.One,
			{
				enableScripts: true,
				retainContextWhenHidden: true,
				localResourceRoots: [distUri],
			},
		);
		SignalsPanel.current = new SignalsPanel(panel, context, host);
	}

	private dispose(): void {
		SignalsPanel.current = undefined;
		this.unregisterWebview();
		while (this.disposables.length > 0) {
			this.disposables.pop()?.dispose();
		}
	}
}

function getHtml(
	context: vscode.ExtensionContext,
	webview: vscode.Webview,
	mode: 'viewer' | 'signals',
): string {
	const distUri = vscode.Uri.joinPath(context.extensionUri, 'dist');
	const indexUri = vscode.Uri.joinPath(distUri, 'index.html');
	if (!fs.existsSync(indexUri.fsPath)) {
		return '<!doctype html><html><body><h1>CodeSim</h1><p>The webview has not been built. Run <code>npm run build</code>.</p></body></html>';
	}

	const csp = [
		"default-src 'none'",
		`img-src ${webview.cspSource} data:`,
		`style-src ${webview.cspSource} 'unsafe-inline'`,
		`font-src ${webview.cspSource}`,
		`script-src ${webview.cspSource}`,
	].join('; ');

	return fs
		.readFileSync(indexUri.fsPath, 'utf8')
		.replace('<body>', `<body data-view="${mode}">`)
		.replace(
			/(src|href)="\.\/([^"#?]+)([^"]*)"/g,
			(_match, attribute: string, resource: string, suffix: string) => {
				const resourceUri = vscode.Uri.joinPath(distUri, ...resource.split('/'));
				return `${attribute}="${webview.asWebviewUri(resourceUri)}${suffix}"`;
			},
		)
		.replace('</head>', `<meta http-equiv="Content-Security-Policy" content="${csp}"></head>`);
}

export function deactivate(): void {}
