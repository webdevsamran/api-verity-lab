/**
 * A thin client over `apiverity lsp`.
 *
 * Thin is the whole design. Every rule, every severity and every message comes
 * from the server, so this extension cannot drift from the CLI: there is
 * nothing here to drift. What it owns is the part an editor has to own —
 * finding the executable, saying something useful when it is not there, and
 * restarting cleanly.
 *
 * ## The failure this spends most of its code on
 *
 * An extension whose server binary is missing usually does one of two things,
 * and both are bad: it fails silently, so the user concludes the linter has no
 * opinions about their file; or it throws a stack trace naming a spawn error,
 * which says nothing about what to install.
 *
 * So the executable is checked before the client starts, and a failure is a
 * message naming the command that was tried and the page that says how to get
 * it.
 */

import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

import * as vscode from 'vscode';
import {
  DocumentSelector,
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
  TransportKind,
} from 'vscode-languageclient/node';

const run = promisify(execFile);

/** The languages the server has an opinion about. Kept in step with
 * `apiverity/lsp/diagnostics.py`'s EXTENSIONS — a document selector wider than
 * the server's own list means the client starts for files it will never hear
 * back about. */
const SELECTOR: DocumentSelector = [
  { scheme: 'file', language: 'yaml' },
  { scheme: 'file', language: 'json' },
  { scheme: 'file', language: 'jsonc' },
  { scheme: 'file', language: 'graphql' },
  { scheme: 'file', language: 'proto' },
  { scheme: 'file', language: 'proto3' },
  // `.wsdl` is `xml` to an editor, and the server lints WSDL. Leaving xml out
  // would mean the one contract format nobody thinks of never getting
  // diagnostics -- the client would simply never start for it.
  { scheme: 'file', language: 'xml' },
];

const INSTALL_DOCS = 'https://github.com/webdevsamran/api-verity-lab/blob/main/docs/install.md';

let client: LanguageClient | undefined;
// A `LogOutputChannel`, not a plain one: vscode-languageclient 10 requires
// the logging interface, and the difference is not cosmetic -- it is what gives
// the channel a level filter, so `apiverity.trace.server: verbose` can be read
// without drowning the ordinary lines.
let output: vscode.LogOutputChannel | undefined;

function settings(): vscode.WorkspaceConfiguration {
  return vscode.workspace.getConfiguration('apiverity');
}

/**
 * Whether the configured executable exists and is the right tool.
 *
 * `--version` rather than a presence check on the path: a `apiverity` on PATH
 * that is somebody else's script, or a stale shim pointing at a removed
 * virtualenv, both pass a file check and fail at the first message.
 */
async function check(command: string): Promise<string | undefined> {
  try {
    const { stdout } = await run(command, ['--version'], { timeout: 20_000 });
    return stdout.trim();
  } catch {
    return undefined;
  }
}

async function start(): Promise<void> {
  const config = settings();
  if (!config.get<boolean>('enable', true)) {
    return;
  }

  const command = config.get<string>('serverPath', 'apiverity') || 'apiverity';
  const args = config.get<string[]>('args', ['lsp']);

  const version = await check(command);
  if (version === undefined) {
    // Named, with the fix. A silent failure here reads as "this file has no
    // findings", which is the most misleading thing a linter can say.
    const choice = await vscode.window.showWarningMessage(
      `apiverity: could not run \`${command} --version\`. The language server is not running, ` +
        'so no contract diagnostics will appear.',
      'How to install',
      'Set the path',
    );
    if (choice === 'How to install') {
      await vscode.env.openExternal(vscode.Uri.parse(INSTALL_DOCS));
    } else if (choice === 'Set the path') {
      await vscode.commands.executeCommand('workbench.action.openSettings', 'apiverity.serverPath');
    }
    return;
  }

  output ??= vscode.window.createOutputChannel('apiverity', { log: true });
  output.appendLine(`starting ${command} ${args.join(' ')} (${version})`);

  const serverOptions: ServerOptions = {
    command,
    args,
    transport: TransportKind.stdio,
  };

  const clientOptions: LanguageClientOptions = {
    documentSelector: SELECTOR,
    outputChannel: output,
    // The server's diagnostics are about the document, not about the
    // workspace, and a save-triggered re-read of every file would be a
    // surprise on a large repository.
    synchronize: {
      configurationSection: 'apiverity',
    },
  };

  client = new LanguageClient('apiverity', 'api-verity-lab', serverOptions, clientOptions);
  await client.start();
}

async function stop(): Promise<void> {
  const existing = client;
  client = undefined;
  if (existing) {
    // `stop()` sends `shutdown`/`exit` and waits. Killing the process instead
    // would leave the scratch files the server removes on its way out.
    await existing.stop();
  }
}

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  context.subscriptions.push(
    vscode.commands.registerCommand('apiverity.restart', async () => {
      await stop();
      await start();
    }),
    vscode.commands.registerCommand('apiverity.showOutput', () => {
      output?.show(true);
    }),
    vscode.workspace.onDidChangeConfiguration(async (event) => {
      // A changed executable or argument list means the running server is the
      // wrong one, and leaving it running would show diagnostics from a tool
      // the user has just replaced.
      if (
        event.affectsConfiguration('apiverity.serverPath') ||
        event.affectsConfiguration('apiverity.args') ||
        event.affectsConfiguration('apiverity.enable')
      ) {
        await stop();
        await start();
      }
    }),
  );

  await start();
}

export async function deactivate(): Promise<void> {
  await stop();
}
