// ============================================================
// Loomind VS Code Extension
// Intercepts AI Agent actions, queries the Experience Engine,
// and injects learned suggestions into the agent's prompt.
// ============================================================

import * as vscode from 'vscode';
import { LoomindClient } from '@loomind/client';
import type { InterceptRequest, InterceptResponse } from '@loomind/types';

let client: LoomindClient | undefined;
let statusBarItem: vscode.StatusBarItem;
let outputChannel: vscode.OutputChannel;

// ==================== Activation ====================

export function activate(context: vscode.ExtensionContext): void {
  outputChannel = vscode.window.createOutputChannel('Loomind');
  outputChannel.appendLine('Loomind Experience Engine activated');

  // Initialize client
  const config = vscode.workspace.getConfiguration('loomind');
  const engineUrl = config.get<string>('engineUrl', 'http://localhost:8082');

  client = new LoomindClient({
    baseUrl: engineUrl,
    timeout: 5000,
    healthCheckInterval: 30000,
  });

  // Status bar
  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBarItem.command = 'loomind.showStatus';
  context.subscriptions.push(statusBarItem);
  updateStatusBar('checking');

  // Listen for connection events
  client.on('connected', () => {
    updateStatusBar('connected');
    outputChannel.appendLine('✅ Connected to Experience Engine');
  });

  client.on('disconnected', () => {
    updateStatusBar('disconnected');
    outputChannel.appendLine('🔴 Disconnected from Experience Engine');
  });

  client.on('error', (err: unknown) => {
    outputChannel.appendLine(`❌ Error: ${err}`);
  });

  // Register commands
  context.subscriptions.push(
    vscode.commands.registerCommand('loomind.toggleEnabled', toggleEnabled),
    vscode.commands.registerCommand('loomind.showStatus', showStatus),
  );

  // Register chat participant for Copilot integration
  registerCopilotHooks(context);

  outputChannel.appendLine(`Engine URL: ${engineUrl}`);
}

export function deactivate(): void {
  client?.dispose();
  outputChannel?.dispose();
}

// ==================== Copilot / Agent Hooks ====================

function registerCopilotHooks(context: vscode.ExtensionContext): void {
  // Listen for document changes as a proxy for agent tool use
  // In a real implementation, this would hook into the Copilot/Cursor API
  // when PreToolUse/PostToolUse events become available.

  const changeDisposable = vscode.workspace.onDidChangeTextDocument(async (event) => {
    const config = vscode.workspace.getConfiguration('loomind');
    if (!config.get<boolean>('enabled', true)) return;
    if (!client?.isConnected()) return;

    // Only process significant changes (not single character typing)
    const totalChanges = event.contentChanges.reduce((sum, c) => sum + c.text.length, 0);
    if (totalChanges < 20) return;

    const doc = event.document;
    const request: InterceptRequest = {
      action: `edit file ${doc.fileName}`,
      action_type: 'write',
      file_path: doc.fileName,
      language: doc.languageId,
      context: event.contentChanges.map((c) => c.text).join('\n').slice(0, 500),
    };

    try {
      const response = await client!.intercept(request);
      if (!response.skipped && response.suggestions.length > 0) {
        showSuggestions(response);
      }
    } catch (err) {
      outputChannel.appendLine(`Intercept error: ${err}`);
    }
  });

  context.subscriptions.push(changeDisposable);
}

// ==================== UI ====================

function showSuggestions(response: InterceptResponse): void {
  const config = vscode.workspace.getConfiguration('loomind');
  const maxSuggestions = config.get<number>('maxSuggestions', 3);

  const suggestions = response.suggestions.slice(0, maxSuggestions);

  for (const suggestion of suggestions) {
    const icon = suggestion.severity === 'critical' ? '🔴' : suggestion.severity === 'warning' ? '🟡' : 'ℹ️';
    const message = `${icon} Loomind: ${suggestion.title}\n\n${suggestion.message}`;

    if (suggestion.severity === 'critical') {
      vscode.window.showWarningMessage(message, 'Got it', 'Dismiss');
    } else {
      vscode.window.showInformationMessage(message, 'Got it');
    }
  }

  outputChannel.appendLine(
    `📋 ${suggestions.length} suggestions (${response.latency_ms.toFixed(1)}ms, layers: ${response.layers_executed.join(' → ')})`,
  );
}

function updateStatusBar(state: 'connected' | 'disconnected' | 'checking'): void {
  switch (state) {
    case 'connected':
      statusBarItem.text = '$(check) Loomind';
      statusBarItem.tooltip = 'Experience Engine: Connected';
      statusBarItem.backgroundColor = undefined;
      break;
    case 'disconnected':
      statusBarItem.text = '$(circle-slash) Loomind';
      statusBarItem.tooltip = 'Experience Engine: Disconnected';
      statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
      break;
    case 'checking':
      statusBarItem.text = '$(sync~spin) Loomind';
      statusBarItem.tooltip = 'Experience Engine: Checking...';
      break;
  }
  statusBarItem.show();
}

async function toggleEnabled(): Promise<void> {
  const config = vscode.workspace.getConfiguration('loomind');
  const current = config.get<boolean>('enabled', true);
  await config.update('enabled', !current, vscode.ConfigurationTarget.Global);
  vscode.window.showInformationMessage(`Loomind ${!current ? 'enabled' : 'disabled'}`);
}

async function showStatus(): Promise<void> {
  if (!client) {
    vscode.window.showErrorMessage('Loomind client not initialized');
    return;
  }

  try {
    const health = await client.health();
    const stats = await client.stats();

    const lines = [
      `Status: ${health.status}`,
      `Engine: ${health.engine}`,
      `Qdrant: ${health.qdrant ? '✅' : '❌'}`,
      `Embedder: ${health.embedder_loaded ? '✅' : '❌'}`,
      `LLM: ${health.llm_available ? '✅' : '❌'}`,
      `Uptime: ${Math.floor(health.uptime_seconds / 60)}min`,
      `Version: ${health.version}`,
      `---`,
      `Experiences: ${stats.total_experiences}`,
      `Queries today: ${stats.queries_today}`,
      `Avg latency: ${stats.avg_latency_ms.toFixed(1)}ms`,
      `Queued offline: ${client.queueSize}`,
    ];

    outputChannel.appendLine('\n=== Engine Status ===');
    lines.forEach((l) => outputChannel.appendLine(l));
    outputChannel.show();

    vscode.window.showInformationMessage(`Loomind: ${health.status} (${stats.total_experiences} experiences)`);
  } catch {
    vscode.window.showErrorMessage('Cannot reach Experience Engine');
  }
}
