import * as assert from 'assert';

// You can import and use all API from the 'vscode' module
// as well as import your extension to test it
import * as vscode from 'vscode';
// import * as myExtension from '../../extension';

suite('Extension Test Suite', () => {
	test('activates and registers the contributed commands', async () => {
		const extension = vscode.extensions.getExtension(
			'hanchen-ge.codesim-frontend',
		);
		assert.ok(extension, 'The CodeSim extension was not discovered.');
		await extension.activate();

		const commands = await vscode.commands.getCommands(true);
		assert.ok(commands.includes('codesim-frontend.openViewer'));
		assert.ok(commands.includes('codesim-frontend.openSignals'));
		await vscode.commands.executeCommand('codesim-frontend.openViewer');
	});
});
