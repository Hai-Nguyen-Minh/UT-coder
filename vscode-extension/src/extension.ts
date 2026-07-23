/**
 * UTcoder VS Code Extension
 *
 * Python client:
 *   - Right-click a Python file in Explorer or Editor
 *   - Sends file content to UTcoder HTTP server
 *   - Receives sandbox-verified generated unit test code
 *   - Creates test file alongside source file
 *   - The server performs pytest, coverage, and self-reflection
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';

// ─── Constants ─────────────────────────────────────────────────────────────

const SUPPORTED_EXTENSIONS = new Set(['.py']);
const API_TOKEN_SECRET = 'utcoder.apiToken';
let extensionContext: vscode.ExtensionContext | undefined;

// ─── Configuration ─────────────────────────────────────────────────────────

interface ServerConfig {
    url: string;
    timeout: number;
    token: string;
}

async function getServerConfig(): Promise<ServerConfig> {
    const cfg = vscode.workspace.getConfiguration('utcoder');
    return {
        url: cfg.get<string>('serverUrl', 'http://localhost:8000'),
        timeout: cfg.get<number>('serverTimeout', 120000),
        token: (await extensionContext?.secrets.get(API_TOKEN_SECRET)) || '',
    };
}

// ─── Helpers ───────────────────────────────────────────────────────────────

function detectLanguage(fileName: string): string {
    return path.extname(fileName).toLowerCase() === '.py' ? 'python' : 'unknown';
}

function getTestFileName(sourceFileName: string): string {
    const ext = path.extname(sourceFileName).toLowerCase();
    const stem = path.basename(sourceFileName, ext);

    return ext === '.py' ? `test_${stem}.py` : `test_${sourceFileName}`;
}

async function readFileContent(filePath: string): Promise<string> {
    return fs.promises.readFile(filePath, 'utf-8');
}

function getFileToProcess(uri?: vscode.Uri): string | undefined {
    if (uri) return uri.fsPath;
    const editor = vscode.window.activeTextEditor;
    if (editor) return editor.document.uri.fsPath;
    return undefined;
}

// ─── Types ─────────────────────────────────────────────────────────────────

interface GenerateResponse {
    success: boolean;
    accepted?: boolean;
    code?: string;
    error?: string;
    coverage?: number | null;
    execution_status?: string;
    status?: string;
    test_file_name?: string;
}

interface HealthResponse {
    ready: boolean;
    message: string;
    version?: string;
    language?: string;
}

// ─── HTTP client ───────────────────────────────────────────────────────────

function requestHeaders(config: ServerConfig): Record<string, string> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (config.token) {
        headers.Authorization = `Bearer ${config.token}`;
    }
    return headers;
}

async function fetchWithTimeout(
    url: string,
    init: RequestInit,
    timeoutMs: number,
    externalSignal?: AbortSignal,
): Promise<Response> {
    const controller = new AbortController();
    let timedOut = false;
    const onExternalAbort = () => controller.abort();
    if (externalSignal?.aborted) {
        controller.abort();
    } else {
        externalSignal?.addEventListener('abort', onExternalAbort, { once: true });
    }
    const timer = setTimeout(() => {
        timedOut = true;
        controller.abort();
    }, timeoutMs);

    try {
        return await fetch(url, { ...init, signal: controller.signal });
    } catch (error) {
        if (timedOut) {
            throw new Error(`Request timed out after ${timeoutMs} ms`);
        }
        throw error;
    } finally {
        clearTimeout(timer);
        externalSignal?.removeEventListener('abort', onExternalAbort);
    }
}

async function callGenerateAPI(
    fileName: string,
    sourceCode: string,
    signal?: AbortSignal,
): Promise<GenerateResponse> {
    const config = await getServerConfig();
    const url = `${config.url.replace(/\/+$/, '')}/api/generate`;

    const response = await fetchWithTimeout(
        url,
        {
            method: 'POST',
            headers: requestHeaders(config),
            body: JSON.stringify({
                file_name: fileName,
                source_code: sourceCode,
                language: detectLanguage(fileName),
            }),
        },
        config.timeout,
        signal,
    );

    if (!response.ok) {
        const text = await response.text().catch(() => 'No response body');
        return { success: false, error: `Server returned ${response.status}: ${text}` };
    }

    return (await response.json()) as GenerateResponse;
}

async function healthCheck(signal?: AbortSignal): Promise<HealthResponse> {
    const config = await getServerConfig();
    const url = `${config.url.replace(/\/+$/, '')}/api/health`;

    const response = await fetchWithTimeout(
        url,
        { headers: requestHeaders(config) },
        Math.min(config.timeout, 10000),
        signal,
    );
    if (!response.ok) {
        const payload = await response.json().catch(() => ({})) as Partial<HealthResponse> & { error?: string };
        return {
            ready: false,
            message: payload.message || payload.error || `Server returned ${response.status}`,
        };
    }
    return (await response.json()) as HealthResponse;
}

// ─── Main command handler ──────────────────────────────────────────────────

async function generateTestsForFile(uri?: vscode.Uri) {
    const filePath = getFileToProcess(uri);
    if (!filePath) {
        vscode.window.showWarningMessage(
            'UTcoder: No file selected. Right-click a file in the Explorer or open one in the editor.',
        );
        return;
    }

    const ext = path.extname(filePath).toLowerCase();
    if (!SUPPORTED_EXTENSIONS.has(ext)) {
        vscode.window.showWarningMessage(
            `UTcoder currently supports Python .py files only (received "${ext}").`,
        );
        return;
    }

    const fileName = path.basename(filePath);

    await vscode.window.withProgress(
        {
            location: vscode.ProgressLocation.Notification,
            title: `UTcoder: Generating tests for ${fileName}...`,
            cancellable: true,
        },
        async (progress, token) => {
            const requestController = new AbortController();
            token.onCancellationRequested(() => requestController.abort());
            progress.report({ message: 'Reading file...' });
            let sourceCode: string;
            try {
                sourceCode = await readFileContent(filePath);
            } catch (err: any) {
                vscode.window.showErrorMessage(
                    `UTcoder: Cannot read file - ${err?.message || err}`,
                );
                return;
            }

            progress.report({ message: 'Connecting to UTcoder server...' });
            try {
                const health = await healthCheck(requestController.signal);
                if (!health.ready) {
                    const action = await vscode.window.showErrorMessage(
                        `UTcoder server not reachable: ${health.message}`,
                        'Configure Server URL',
                        'Retry',
                    );
                    if (action === 'Configure Server URL') {
                        await vscode.commands.executeCommand(
                            'workbench.action.openSettings',
                            'utcoder.serverUrl',
                        );
                    }
                    return;
                }
            } catch {
                vscode.window.showErrorMessage(
                    'UTcoder: Cannot connect to server. Check server URL setting.',
                );
                return;
            }

            progress.report({ message: 'Generating unit tests...' });
            if (token.isCancellationRequested) return;

            let result: GenerateResponse;
            try {
                result = await callGenerateAPI(
                    fileName,
                    sourceCode,
                    requestController.signal,
                );
            } catch (err: any) {
                const msg =
                    err?.name === 'AbortError'
                        ? 'Request cancelled'
                        : err?.message || String(err);
                vscode.window.showErrorMessage(`UTcoder: Generation failed - ${msg}`);
                return;
            }

            if (!result.success || !result.code) {
                const diagnostic = [
                    result.error,
                    result.execution_status ? `status=${result.execution_status}` : '',
                    typeof result.coverage === 'number' ? `coverage=${result.coverage.toFixed(1)}%` : '',
                ].filter(Boolean).join(', ');
                vscode.window.showErrorMessage(
                    `UTcoder: Generation was not accepted - ${diagnostic || 'Unknown error'}`,
                );
                return;
            }

            progress.report({ message: 'Writing test file...' });
            if (token.isCancellationRequested) return;

            const testFileName = result.test_file_name || getTestFileName(fileName);
            let outputDir = path.dirname(filePath);

            // Try to use workspace tests/ directory
            const workspaceFolders = vscode.workspace.workspaceFolders;
            if (workspaceFolders && workspaceFolders.length > 0) {
                const root = workspaceFolders[0].uri.fsPath;
                if (filePath.startsWith(root)) {
                    const relPath = path.relative(root, filePath);
                    for (const testDir of ['tests', 'test', '__tests__']) {
                        const candidate = path.join(root, testDir, relPath);
                        const candidateDir = path.dirname(candidate);
                        try {
                            await fs.promises.access(candidateDir);
                            outputDir = candidateDir;
                            break;
                        } catch {
                            // dir doesn't exist, continue
                        }
                    }
                }
            }

            const testFilePath = path.join(outputDir, testFileName);

            try {
                await fs.promises.mkdir(outputDir, { recursive: true });

                try {
                    await fs.promises.access(testFilePath, fs.constants.F_OK);
                    const choice = await vscode.window.showWarningMessage(
                        `Test file already exists: ${testFileName}`,
                        { modal: true },
                        'Overwrite',
                        'Cancel',
                    );
                    if (choice !== 'Overwrite') return;
                } catch {
                    // file doesn't exist, proceed
                }

                await fs.promises.writeFile(testFilePath, result.code, 'utf-8');
            } catch (err: any) {
                vscode.window.showErrorMessage(
                    `UTcoder: Failed to write test file - ${err?.message || err}`,
                );
                return;
            }

            try {
                const doc = await vscode.workspace.openTextDocument(testFilePath);
                await vscode.window.showTextDocument(doc, vscode.ViewColumn.Beside);
            } catch {
                // ignore
            }

            const coverageText = typeof result.coverage === 'number'
                ? ` (${result.coverage.toFixed(1)}% coverage)`
                : '';
            vscode.window.showInformationMessage(
                `UTcoder: ✅ Verified tests generated → ${testFileName}${coverageText}`,
            );
        },
    );
}

// ─── Activation ────────────────────────────────────────────────────────────

export function activate(context: vscode.ExtensionContext) {
    extensionContext = context;
    console.log('[UTcoder] Activating simplified extension...');

    const generateCmd = vscode.commands.registerCommand(
        'utcoder.generateTests',
        (uri?: vscode.Uri) => generateTestsForFile(uri),
    );

    const healthCmd = vscode.commands.registerCommand(
        'utcoder.checkHealth',
        async () => {
            try {
                const health = await healthCheck();
                if (health.ready) {
                    const ver = (health as HealthResponse).version;
                    vscode.window.showInformationMessage(
                        `UTcoder server is ready. ${health.message}${ver ? ` (v${ver})` : ''}`,
                    );
                } else {
                    const action = await vscode.window.showErrorMessage(
                        `UTcoder server: ${health.message}`,
                        'Configure Server URL',
                    );
                    if (action === 'Configure Server URL') {
                        await vscode.commands.executeCommand(
                            'workbench.action.openSettings',
                            'utcoder.serverUrl',
                        );
                    }
                }
            } catch {
                const action = await vscode.window.showErrorMessage(
                    'UTcoder server: Connection failed',
                    'Configure Server URL',
                );
                if (action === 'Configure Server URL') {
                    await vscode.commands.executeCommand(
                        'workbench.action.openSettings',
                        'utcoder.serverUrl',
                    );
                }
            }
        },
    );

    const tokenCmd = vscode.commands.registerCommand(
        'utcoder.setApiToken',
        async () => {
            const token = await vscode.window.showInputBox({
                prompt: 'Bearer token matching UTCODER_API_TOKEN (leave empty to remove)',
                password: true,
                ignoreFocusOut: true,
            });
            if (token === undefined) return;
            if (token.trim()) {
                await context.secrets.store(API_TOKEN_SECRET, token.trim());
                vscode.window.showInformationMessage('UTcoder API token saved securely.');
            } else {
                await context.secrets.delete(API_TOKEN_SECRET);
                vscode.window.showInformationMessage('UTcoder API token removed.');
            }
        },
    );

    context.subscriptions.push(generateCmd, healthCmd, tokenCmd);

    // Background health check on activation
    healthCheck().then((health) => {
        if (!health.ready) {
            console.log('[UTcoder] Server not reachable on startup:', health.message);
        }
    });

    console.log('[UTcoder] Simplified extension activated.');
}

export function deactivate() {
    extensionContext = undefined;
    console.log('[UTcoder] Deactivated.');
}
