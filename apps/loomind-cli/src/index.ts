// ============================================================
// Loomind CLI — Command-line tool for managing the engine
// Usage: loomind status | list | add | search | delete | export | import
//        loomind approve | update | fleet | goal
// ============================================================

import { Command } from 'commander';
import { LoomindClient } from '@loomind/client';
import * as fs from 'node:fs';
import * as readline from 'node:readline';

const program = new Command();

program
  .name('loomind')
  .description('Loomind Experience Engine CLI')
  .version('0.1.0')
  .addHelpText('before', `
 _____              _     ____  _                     __  __   ____ _     ___
|_   _| ___  ___ __| |__ / ___|| |__   ___ _ __ ___  \\ \\/ /  / ___| |   |_ _|
  | |  / _ \\/ __/ _\` | '_ \\___ \\| '_ \\ / _ \\ '__/ _ \\  \\  /  | |   | |    | |
  | | |  __/ (_| (_| | | | |___) | |_) |  __/ | |  __/  /  \\  | |___| |___ | |
  |_|  \\___|\\___\\__,_|_| |_|____/| .__/ \\___|_|  \\___| /_/\\_\\  \\____|_____|___|
                                 |_|
  `);

// Helper to create a client with common options
function createClient(url: string): LoomindClient {
  return new LoomindClient({ baseUrl: url, healthCheckInterval: 0 });
}

// ---- status ----
program
  .command('status')
  .description('Show engine health and stats')
  .option('-u, --url <url>', 'Engine URL', 'http://127.0.0.1:8082')
  .action(async (opts: { url: string }) => {
    const client = createClient(opts.url);
    try {
      const health = await client.health();
      const stats = await client.stats();
      console.log(`
 _____              _     ____  _                     __  __   ____ _     ___
|_   _| ___  ___ __| |__ / ___|| |__   ___ _ __ ___  \\ \\/ /  / ___| |   |_ _|
  | |  / _ \\/ __/ _\` | '_ \\___ \\| '_ \\ / _ \\ '__/ _ \\  \\  /  | |   | |    | |
  | | |  __/ (_| (_| | | | |___) | |_) |  __/ | |  __/  /  \\  | |___| |___ | |
  |_|  \\___|\\___\\__,_|_| |_|____/| .__/ \\___|_|  \\___| /_/\\_\\  \\____|_____|___|
                                 |_|
      `);
      console.log('  ─────────────────────────────────────────────────────────────────────────────');
      console.log(`  Status:        ${health.status === 'ok' ? '[OK]' : '[FAIL]'} ${health.status}`);
      console.log(`  Qdrant:        ${health.qdrant ? '[OK]' : '[X]'}`);
      console.log(`  Embedder:      ${health.embedder_loaded ? '[OK]' : '[X]'}`);
      console.log(`  LLM:           ${health.llm_available ? '[OK]' : '[X]'}`);
      console.log(`  Uptime:        ${Math.floor(health.uptime_seconds / 60)} min`);
      console.log(`  Version:       ${health.version}`);
      console.log(`  Experiences:   ${stats.total_experiences}`);
      console.log(`  Queries today: ${stats.queries_today}`);
      console.log(`  Avg latency:   ${stats.avg_latency_ms.toFixed(1)} ms\n`);
    } catch {
      console.error('  [FAIL] Cannot reach Experience Engine at', opts.url);
    }
    client.dispose();
  });

// ---- list ----
program
  .command('list')
  .description('List stored experiences')
  .option('-u, --url <url>', 'Engine URL', 'http://127.0.0.1:8082')
  .option('-l, --limit <n>', 'Max results', '20')
  .action(async (opts: { url: string; limit: string }) => {
    const client = createClient(opts.url);
    try {
      const result = await client.getExperiences({ limit: parseInt(opts.limit, 10) });
      console.log(`\n  Experiences (${result.total} total):`);
      for (const exp of result.items) {
        const icon = exp.severity === 'critical' ? '[!!]' : exp.severity === 'warning' ? '[!]' : '[i]';
        console.log(`  ${icon} [${exp.category}] ${exp.title}`);
      }
      console.log('');
    } catch {
      console.error('  [FAIL] Cannot reach Experience Engine at', opts.url);
    }
    client.dispose();
  });

// ---- add ----
program
  .command('add')
  .description('Add a new experience')
  .requiredOption('-t, --title <title>', 'Experience title')
  .requiredOption('-d, --description <desc>', 'Experience description')
  .option('-c, --category <cat>', 'Category', 'pattern')
  .option('-s, --severity <sev>', 'Severity (info|warning|critical)', 'info')
  .option('--tags <tags>', 'Comma-separated tags', '')
  .option('-u, --url <url>', 'Engine URL', 'http://127.0.0.1:8082')
  .action(async (opts: { url: string; title: string; description: string; category: string; severity: string; tags: string }) => {
    const client = createClient(opts.url);
    try {
      const exp = await client.addExperience({
        title: opts.title,
        description: opts.description,
        category: opts.category,
        severity: opts.severity as 'info' | 'warning' | 'critical',
        tags: opts.tags ? opts.tags.split(',').map((t: string) => t.trim()) : [],
      });
      console.log(`  [OK] Experience added: ${exp.id}`);
    } catch {
      console.error('  [FAIL] Failed to add experience');
    }
    client.dispose();
  });

// ---- search ----
program
  .command('search <query>')
  .description('Search experiences by text similarity')
  .option('-u, --url <url>', 'Engine URL', 'http://127.0.0.1:8082')
  .action(async (query: string, opts: { url: string }) => {
    const client = createClient(opts.url);
    try {
      const results = await client.searchExperiences(query);
      if (results.length === 0) {
        console.log('\n  No matching experiences found.\n');
      } else {
        console.log(`\n  Found ${results.length} matching experiences:\n`);
        for (const exp of results) {
          const icon = exp.severity === 'critical' ? '[!!]' : exp.severity === 'warning' ? '[!]' : '[i]';
          console.log(`  ${icon} ${exp.title}`);
          console.log(`      ${exp.description.substring(0, 100)}${exp.description.length > 100 ? '...' : ''}`);
          console.log(`      Tags: ${exp.tags.join(', ') || '(none)'}\n`);
        }
      }
    } catch {
      console.error('  [FAIL] Cannot reach Experience Engine at', opts.url);
    }
    client.dispose();
  });

// ---- delete ----
program
  .command('delete <id>')
  .description('Delete an experience by ID')
  .option('-u, --url <url>', 'Engine URL', 'http://127.0.0.1:8082')
  .action(async (id: string, opts: { url: string }) => {
    const client = createClient(opts.url);
    try {
      await client.deleteExperience(id);
      console.log(`  [OK] Deleted experience: ${id}`);
    } catch {
      console.error(`  [FAIL] Failed to delete experience: ${id}`);
    }
    client.dispose();
  });

// ---- export ----
program
  .command('export [filename]')
  .description('Export all experiences to a JSON file')
  .option('-u, --url <url>', 'Engine URL', 'http://127.0.0.1:8082')
  .action(async (filename: string | undefined, opts: { url: string }) => {
    const client = createClient(opts.url);
    const outFile = filename || `experiences_backup_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.json`;
    try {
      const data = await client.exportExperiences();
      fs.writeFileSync(outFile, JSON.stringify(data, null, 2), 'utf-8');
      const sizeKb = (fs.statSync(outFile).size / 1024).toFixed(1);
      console.log(`  [OK] Exported ${data.total} experiences to ${outFile} (${sizeKb} KB)`);
    } catch {
      console.error('  [FAIL] Cannot reach Experience Engine at', opts.url);
    }
    client.dispose();
  });

// ---- import ----
program
  .command('import <filename>')
  .description('Import experiences from a JSON file')
  .option('-u, --url <url>', 'Engine URL', 'http://127.0.0.1:8082')
  .option('--overwrite', 'Overwrite existing experiences with same ID', false)
  .action(async (filename: string, opts: { url: string; overwrite: boolean }) => {
    const client = createClient(opts.url);
    try {
      if (!fs.existsSync(filename)) {
        console.error(`  [FAIL] File not found: ${filename}`);
        return;
      }

      const raw = JSON.parse(fs.readFileSync(filename, 'utf-8'));

      // Support both ExportBundle and plain array
      let experiences: Record<string, unknown>[];
      if (Array.isArray(raw)) {
        experiences = raw;
      } else if (raw.experiences && Array.isArray(raw.experiences)) {
        experiences = raw.experiences;
      } else {
        console.error('  [FAIL] Invalid format. Expected ExportBundle or array.');
        return;
      }

      console.log(`  Loading ${experiences.length} experiences from ${filename}...`);
      console.log(`  Mode: ${opts.overwrite ? 'OVERWRITE existing' : 'SKIP duplicates'}`);

      const result = await client.importExperiences(experiences, opts.overwrite);
      console.log('\n  Import result:');
      console.log(`    Imported: ${result.imported}`);
      console.log(`    Skipped:  ${result.skipped}`);
      console.log(`    Failed:   ${result.failed}`);
      console.log(`    Total:    ${result.total_in_file}\n`);
    } catch (err) {
      console.error('  [FAIL] Import failed:', (err as Error).message);
    }
    client.dispose();
  });

// ---- approve ----
program
  .command('approve')
  .description('Approve a HITL pending task')
  .option('-u, --url <url>', 'Engine URL', 'http://127.0.0.1:8082')
  .option('--goal <goal_id>', 'Goal ID')
  .option('--task <task_id>', 'Task ID')
  .option('--pending', 'List all HITL pending tasks and prompt which to approve')
  .action(async (opts: { url: string; goal?: string; task?: string; pending?: boolean }) => {
    if (opts.pending) {
      // List all HITL pending tasks and prompt user
      try {
        const resp = await fetch(`${opts.url}/api/goals?limit=50`);
        if (!resp.ok) {
          console.error(`  [FAIL] Failed to fetch goals: HTTP ${resp.status}`);
          return;
        }
        const data = (await resp.json()) as { items?: unknown[]; goals?: unknown[] } | unknown[];
        const goals: unknown[] = Array.isArray(data)
          ? data
          : (data as { items?: unknown[]; goals?: unknown[] }).items ??
            (data as { items?: unknown[]; goals?: unknown[] }).goals ??
            [];

        type TaskEntry = { goalId: string; goalText: string; taskId: string; taskDescription: string };
        const pending: TaskEntry[] = [];

        for (const g of goals) {
          const goal = g as { id: string; goal?: string; text?: string; tasks?: unknown[] };
          const tasks: unknown[] = goal.tasks ?? [];
          for (const t of tasks) {
            const task = t as { id: string; status: string; description?: string; task_type?: string };
            if (task.status === 'hitl_pending') {
              pending.push({
                goalId: goal.id,
                goalText: goal.goal ?? goal.text ?? goal.id,
                taskId: task.id,
                taskDescription: task.description ?? task.task_type ?? task.id,
              });
            }
          }
        }

        if (pending.length === 0) {
          console.log('\n  No HITL pending tasks found.\n');
          return;
        }

        console.log(`\n  HITL Pending Tasks (${pending.length}):\n`);
        pending.forEach((entry, i) => {
          const goalTrunc = entry.goalText.length > 50 ? entry.goalText.substring(0, 47) + '...' : entry.goalText;
          const taskTrunc = entry.taskDescription.length > 60 ? entry.taskDescription.substring(0, 57) + '...' : entry.taskDescription;
          console.log(`  [${i + 1}] Goal: ${goalTrunc}`);
          console.log(`       Task: ${taskTrunc}`);
          console.log(`       IDs:  goal=${entry.goalId}  task=${entry.taskId}\n`);
        });

        const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
        rl.question('  Enter number to approve (or q to quit): ', async (answer: string) => {
          rl.close();
          if (answer.trim().toLowerCase() === 'q' || answer.trim() === '') {
            console.log('  Cancelled.');
            return;
          }
          const idx = parseInt(answer.trim(), 10) - 1;
          if (isNaN(idx) || idx < 0 || idx >= pending.length) {
            console.error('  [FAIL] Invalid selection.');
            return;
          }
          const chosen = pending[idx];
          try {
            const approveResp = await fetch(
              `${opts.url}/api/ba/goals/${chosen.goalId}/tasks/${chosen.taskId}/approve`,
              {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ approved: true }),
              },
            );
            if (!approveResp.ok) {
              console.error(`  [FAIL] Approve failed: HTTP ${approveResp.status}`);
              return;
            }
            console.log(`  [OK] Task approved: ${chosen.taskId}`);
          } catch (err) {
            console.error('  [FAIL] Approve request failed:', (err as Error).message);
          }
        });
      } catch (err) {
        console.error('  [FAIL] Cannot reach Experience Engine at', opts.url, '-', (err as Error).message);
      }
    } else if (opts.goal && opts.task) {
      // Direct approve by IDs
      try {
        const approveResp = await fetch(
          `${opts.url}/api/ba/goals/${opts.goal}/tasks/${opts.task}/approve`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ approved: true }),
          },
        );
        if (!approveResp.ok) {
          console.error(`  [FAIL] Approve failed: HTTP ${approveResp.status}`);
          return;
        }
        console.log(`  [OK] Task approved: ${opts.task}`);
      } catch (err) {
        console.error('  [FAIL] Cannot reach Experience Engine at', opts.url, '-', (err as Error).message);
      }
    } else {
      console.error('  [FAIL] Provide --goal <id> --task <id>, or use --pending to list and choose.');
    }
  });

// ---- update ----
program
  .command('update <id>')
  .description('Update an existing experience by ID')
  .option('-u, --url <url>', 'Engine URL', 'http://127.0.0.1:8082')
  .option('-t, --title <title>', 'New title')
  .option('-d, --description <desc>', 'New description')
  .option('-c, --category <cat>', 'New category')
  .option('-s, --severity <sev>', 'New severity (info|warning|critical)')
  .option('--tags <tags>', 'Comma-separated tags (replaces existing)')
  .action(async (
    id: string,
    opts: { url: string; title?: string; description?: string; category?: string; severity?: string; tags?: string },
  ) => {
    if (!opts.title && !opts.description && !opts.category && !opts.severity && opts.tags === undefined) {
      console.error('  [FAIL] Provide at least one of: -t, -d, -c, -s, --tags');
      return;
    }
    const client = createClient(opts.url);
    try {
      const existing = await client.getExperience(id);
      const payload = {
        title: opts.title ?? existing.title,
        description: opts.description ?? existing.description,
        category: opts.category ?? existing.category,
        severity: (opts.severity ?? existing.severity) as 'info' | 'warning' | 'critical',
        tags: opts.tags !== undefined ? opts.tags.split(',').map((t: string) => t.trim()) : existing.tags,
      };
      await client.updateExperience(id, payload);
      console.log(`  [OK] Updated: ${id}`);
    } catch (err) {
      console.error(`  [FAIL] Failed to update experience ${id}:`, (err as Error).message);
    }
    client.dispose();
  });

// ---- fleet ----
program
  .command('fleet')
  .description('Show live agent fleet status')
  .option('-u, --url <url>', 'Engine URL', 'http://127.0.0.1:8082')
  .action(async (opts: { url: string }) => {
    try {
      type AgentEntry = {
        cli_name?: string;
        name?: string;
        id?: string;
        status?: string;
        current_task?: string;
        current_task_description?: string;
        tasks_done?: number;
        completed_tasks?: number;
        last_seen?: string;
        last_heartbeat?: string;
      };

      const [fleetResp, goalsResp] = await Promise.all([
        fetch(`${opts.url}/api/agents/fleet`),
        fetch(`${opts.url}/api/goals?limit=50`),
      ]);

      // Fleet table
      if (!fleetResp.ok) {
        console.error(`  [FAIL] Failed to fetch fleet: HTTP ${fleetResp.status}`);
      } else {
        const fleetData = (await fleetResp.json()) as { agents?: AgentEntry[] } | AgentEntry[];
        const agents: AgentEntry[] = Array.isArray(fleetData)
          ? fleetData
          : (fleetData as { agents?: AgentEntry[] }).agents ?? [];

        console.log('\n  ─────────────────────────────────────────────────────────────────────────────');
        console.log('  AGENT FLEET');
        console.log('  ─────────────────────────────────────────────────────────────────────────────');

        if (agents.length === 0) {
          console.log('  (no agents registered)\n');
        } else {
          const nameW = 20;
          const statusW = 10;
          const taskW = 42;
          const doneW = 10;
          const seenW = 20;
          const header =
            '  ' +
            'CLI NAME'.padEnd(nameW) +
            'STATUS'.padEnd(statusW) +
            'CURRENT TASK'.padEnd(taskW) +
            'TASKS DONE'.padEnd(doneW) +
            'LAST SEEN';
          console.log(header);
          console.log('  ' + '─'.repeat(nameW + statusW + taskW + doneW + seenW));

          for (const agent of agents) {
            const name = (agent.cli_name ?? agent.name ?? agent.id ?? 'unknown').substring(0, nameW - 1).padEnd(nameW);
            const rawStatus = (agent.status ?? 'unknown').toLowerCase();
            let statusLabel: string;
            if (rawStatus === 'busy' || rawStatus === 'running') statusLabel = '[BUSY]';
            else if (rawStatus === 'online' || rawStatus === 'idle') statusLabel = '[ONLINE]';
            else if (rawStatus === 'waiting') statusLabel = '[IDLE]';
            else if (rawStatus === 'offline' || rawStatus === 'disconnected') statusLabel = '[OFFLINE]';
            else statusLabel = `[${rawStatus.toUpperCase().substring(0, 7)}]`;
            const statusCol = statusLabel.padEnd(statusW);

            const rawTask = agent.current_task ?? agent.current_task_description ?? '';
            const taskTrunc = rawTask.length > taskW - 2 ? rawTask.substring(0, taskW - 5) + '...' : rawTask;
            const taskCol = taskTrunc.padEnd(taskW);

            const done = String(agent.tasks_done ?? agent.completed_tasks ?? 0).padEnd(doneW);

            const rawSeen = agent.last_seen ?? agent.last_heartbeat ?? '';
            const seenCol = rawSeen ? new Date(rawSeen).toLocaleTimeString() : '(never)';

            console.log(`  ${name}${statusCol}${taskCol}${done}${seenCol}`);
          }
          console.log('');
        }
      }

      // HITL pending count from goals
      if (goalsResp.ok) {
        const goalsData = (await goalsResp.json()) as { items?: unknown[]; goals?: unknown[] } | unknown[];
        const goals: unknown[] = Array.isArray(goalsData)
          ? goalsData
          : (goalsData as { items?: unknown[]; goals?: unknown[] }).items ??
            (goalsData as { items?: unknown[]; goals?: unknown[] }).goals ??
            [];

        let hitlCount = 0;
        for (const g of goals) {
          const goal = g as { tasks?: unknown[] };
          for (const t of goal.tasks ?? []) {
            const task = t as { status: string };
            if (task.status === 'hitl_pending') hitlCount++;
          }
        }
        console.log(`  HITL Pending Tasks: ${hitlCount}`);
        if (hitlCount > 0) {
          console.log('  Run: loomind approve --pending   to review and approve');
        }
        console.log('');
      }
    } catch (err) {
      console.error('  [FAIL] Cannot reach Experience Engine at', opts.url, '-', (err as Error).message);
    }
  });

// ---- goal ----
program
  .command('goal [text]')
  .description('Submit a goal to the engine, or list recent goals')
  .option('-u, --url <url>', 'Engine URL', 'http://127.0.0.1:8082')
  .option('--agent <submitted_by>', 'Agent/submitter name', 'cli')
  .option('--list', 'List recent goals with status')
  .action(async (text: string | undefined, opts: { url: string; agent: string; list?: boolean }) => {
    if (opts.list) {
      // List recent goals
      try {
        const resp = await fetch(`${opts.url}/api/goals?limit=10`);
        if (!resp.ok) {
          console.error(`  [FAIL] Failed to fetch goals: HTTP ${resp.status}`);
          return;
        }
        const data = (await resp.json()) as { items?: unknown[]; goals?: unknown[] } | unknown[];
        const goals: unknown[] = Array.isArray(data)
          ? data
          : (data as { items?: unknown[]; goals?: unknown[] }).items ??
            (data as { items?: unknown[]; goals?: unknown[] }).goals ??
            [];

        if (goals.length === 0) {
          console.log('\n  No goals found.\n');
          return;
        }

        console.log('\n  ─────────────────────────────────────────────────────────────────────────────');
        console.log('  RECENT GOALS');
        console.log('  ─────────────────────────────────────────────────────────────────────────────');

        const goalW = 44;
        const statusW = 16;
        const tasksW = 14;
        const header = '  ' + 'GOAL'.padEnd(goalW) + 'STATUS'.padEnd(statusW) + 'TASKS DONE/TOTAL';
        console.log(header);
        console.log('  ' + '─'.repeat(goalW + statusW + tasksW));

        for (const g of goals) {
          const goal = g as {
            goal?: string;
            text?: string;
            id: string;
            status?: string;
            tasks?: unknown[];
          };
          const rawText = goal.goal ?? goal.text ?? goal.id;
          const textTrunc = rawText.length > goalW - 2 ? rawText.substring(0, goalW - 5) + '...' : rawText;
          const goalCol = textTrunc.padEnd(goalW);

          const status = (goal.status ?? 'unknown').padEnd(statusW);

          const tasks = (goal.tasks ?? []) as { status: string }[];
          const total = tasks.length;
          const done = tasks.filter((t) => t.status === 'done' || t.status === 'completed').length;
          const tasksCol = total > 0 ? `${done}/${total}` : '-';

          console.log(`  ${goalCol}${status}${tasksCol}`);
        }
        console.log('');
      } catch (err) {
        console.error('  [FAIL] Cannot reach Experience Engine at', opts.url, '-', (err as Error).message);
      }
    } else if (text) {
      // Submit new goal
      try {
        const resp = await fetch(`${opts.url}/api/goals`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ goal: text, submitted_by: opts.agent }),
        });
        if (!resp.ok) {
          console.error(`  [FAIL] Failed to submit goal: HTTP ${resp.status}`);
          return;
        }
        const created = (await resp.json()) as {
          id?: string;
          goal_id?: string;
          goal?: string;
          tasks?: { task_type?: string; description?: string; id?: string }[];
        };
        const goalId = created.id ?? created.goal_id ?? '(unknown)';
        console.log(`\n  [OK] Goal submitted: ${goalId}`);

        const tasks = created.tasks ?? [];
        if (tasks.length > 0) {
          console.log(`\n  Decomposed tasks (${tasks.length}):\n`);
          tasks.forEach((t, i) => {
            const type = t.task_type ?? 'task';
            const desc = t.description ?? t.id ?? '(no description)';
            console.log(`  [${i + 1}] [${type}] ${desc}`);
          });
        }
        console.log('');
      } catch (err) {
        console.error('  [FAIL] Cannot reach Experience Engine at', opts.url, '-', (err as Error).message);
      }
    } else {
      console.error('  [FAIL] Provide goal text, or use --list to show recent goals.');
    }
  });

program.parse();
