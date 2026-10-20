import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';

const extensionNamespace = 'codesim-frontend';
const viewerCommandId = `${extensionNamespace}.openViewer`;
const signalsCommandId = `${extensionNamespace}.openSignals`;
const selectPythonCommandId = `${extensionNamespace}.selectPythonExecutable`;
const selectBackendCommandId = `${extensionNamespace}.selectBackendDirectory`;
const viewerViewId = `${extensionNamespace}.viewer`;
const defaultSystem = 'VSGSMIBSystem';

type AnalysisKind = 'simulation' | 'smallSignal' | 'interaction';

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
		vscode.commands.registerCommand(selectPythonCommandId, () => host.selectPythonExecutable()),
		vscode.commands.registerCommand(selectBackendCommandId, () => host.selectBackendDirectory()),
	);
}

class CodeSimHost {
	private readonly webviews = new Set<vscode.Webview>();
	private readonly output: vscode.OutputChannel;
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
		context.subscriptions.push(this.output, { dispose: () => { void this.stopBackend(); } });
	}

	registerWebview(webview: vscode.Webview): () => void {
		this.webviews.add(webview);
		return () => this.webviews.delete(webview);
	}

	async selectPythonExecutable(): Promise<void> {
		const workspaceUri = vscode.workspace.workspaceFolders?.[0]?.uri;
		const configured = vscode.workspace
			.getConfiguration(extensionNamespace, workspaceUri)
			.get<string>('pythonExecutable', 'python');
		const workspace = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
		const executableNames = process.platform === 'win32'
			? ['python.exe']
			: ['python3', 'python'];
		const candidates = new Set<string>();
		if (path.isAbsolute(configured) && fs.existsSync(configured)) {
			candidates.add(configured);
		}
		if (workspace) {
			for (const environment of ['.venv', 'venv', 'env', '.conda']) {
				for (const name of executableNames) {
					const candidate = path.join(
						workspace, environment,
						process.platform === 'win32' ? 'Scripts' : 'bin', name,
					);
					if (fs.existsSync(candidate)) {
						candidates.add(candidate);
					}
				}
			}
		}
		for (const directory of (process.env.PATH ?? '').split(path.delimiter)) {
			for (const name of executableNames) {
				const candidate = path.join(directory, name);
				if (fs.existsSync(candidate)) {
					candidates.add(candidate);
				}
			}
		}
		type PythonChoice = vscode.QuickPickItem & {
			value?: string;
			action?: 'enter' | 'browse';
		};
		const choices: PythonChoice[] = [
			...Array.from(candidates, (candidate) => ({
				label: path.basename(path.dirname(candidate)),
				description: candidate,
				detail: candidate === configured ? 'Current CodeSim interpreter' : undefined,
				value: candidate,
			})),
			{ label: '$(edit) Enter interpreter path…', action: 'enter' },
			{ label: '$(folder-opened) Browse…', action: 'browse' },
		];
		const choice = await vscode.window.showQuickPick(choices, {
			placeHolder: 'Select the exact Python executable CodeSim should launch',
			title: 'CodeSim: Select Python Executable',
		});
		let executable: string | undefined;
		if (choice?.action === 'enter') {
			executable = await vscode.window.showInputBox({
				prompt: 'Enter a Python executable path or command',
				value: configured,
			});
		} else if (choice?.action === 'browse') {
			const selected = await vscode.window.showOpenDialog({
				canSelectFiles: true,
				canSelectFolders: false,
				canSelectMany: false,
				openLabel: 'Use this Python',
				title: 'Select the Python executable for CodeSim',
			});
			executable = selected?.[0]?.fsPath;
		} else {
			executable = choice?.value;
		}
		if (!executable) {
			return;
		}
		await vscode.workspace.getConfiguration(extensionNamespace, workspaceUri).update(
			'pythonExecutable', executable, vscode.ConfigurationTarget.Workspace,
		);
		void vscode.window.showInformationMessage(
			`CodeSim Python executable: ${executable}. Restart the backend to apply it.`,
		);
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

	async handleMessage(message: WebviewMessage): Promise<void> {
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
				if (this.currentSnapshot) {
					await this.postToWebviews({ type: 'systemSnapshot', snapshot: this.currentSnapshot });
				}
				break;
			case 'loadSystemDescriptor':
				await this.runDescriptor(message.systemName);
				break;
			case 'runAnalysis':
				await this.runAnalysis(message.analysis, message.systemName);
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
						: 'interaction.run';
			const result = await this.request<Record<string, unknown>>(method, {
				systemName,
				parameters: this.parameterOverrides,
				options: {},
			});
			if (typeof result.snapshotFile === 'string') {
				this.currentSnapshotUri = vscode.Uri.file(result.snapshotFile);
			}
			if (!(await this.acceptSnapshot(result.descriptor))) {
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
		this.backendStart = new Promise<void>((resolve, reject) => {
			const workspaceUri = vscode.workspace.workspaceFolders?.[0]?.uri;
			const executable = vscode.workspace
				.getConfiguration(extensionNamespace, workspaceUri)
				.get<string>('pythonExecutable', 'python')
				.trim() || 'python';
			this.output.appendLine(`[backend] Python executable: ${executable}`);
			const process = spawn(executable, ['-u', '-m', 'codesimpy.api.cli'], {
				cwd: this.backendPath(), windowsHide: true, stdio: 'pipe',
			});
			this.backendProcess = process;
			process.stdout.setEncoding('utf8');
			process.stderr.setEncoding('utf8');
			process.stdout.on('data', (chunk: string) => this.readBackendOutput(chunk));
			process.stderr.on('data', (chunk: string) => this.output.append(chunk));
			process.once('spawn', resolve);
			process.once('error', (error) => {
				this.backendProcess = undefined;
				this.backendStart = undefined;
				reject(error);
			});
			process.once('close', (code) => {
				if (this.backendProcess === process) {
					this.backendProcess = undefined;
				}
				this.backendStart = undefined;
				this.activeAction = undefined;
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
				const snapshot = this.currentSnapshot as Record<string, unknown>;
				const current = new Map(
					(snapshot.signals as Array<Record<string, unknown>>).map((signal) => [signal.id, signal]),
				);
				for (const incoming of message.signals as Array<Record<string, unknown>>) {
					const existing = current.get(incoming.id);
					current.set(incoming.id, existing ? {
						...existing,
						time: [...existing.time as number[], ...incoming.time as number[]],
						values: [...existing.values as number[], ...incoming.values as number[]],
					} : incoming);
				}
				snapshot.signals = [...current.values()];
			}
			await this.postToWebviews(message);
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

	private async postToWebviews(message: unknown): Promise<void> {
		await Promise.all(Array.from(
			this.webviews,
			(webview) => webview.postMessage(message),
		));
	}

	private async acceptSnapshot(value: unknown): Promise<boolean> {
		try {
			const snapshot = this.unwrapSnapshot(value);
			if (!this.isSystemSnapshot(snapshot)) {
				throw new Error(
					'The backend response does not contain system, components, connections, and signals.',
				);
			}
			this.currentSnapshot = snapshot;
			await this.postToWebviews({ type: 'systemSnapshot', snapshot });
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
		const unregister = this.host.registerWebview(view.webview);
		const messageSubscription = view.webview.onDidReceiveMessage(
			(message: WebviewMessage) => this.host.handleMessage(message),
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
		this.unregisterWebview = host.registerWebview(this.panel.webview);
		this.panel.onDidDispose(() => this.dispose(), undefined, this.disposables);
		this.panel.webview.onDidReceiveMessage(
			(message: WebviewMessage) => host.handleMessage(message),
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
