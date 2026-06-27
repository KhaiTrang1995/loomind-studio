#!/usr/bin/env node
/**
 * Screenshot capture script for Loomind Dashboard
 * Requires: npm install -D playwright chromium
 */

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const DASHBOARD_URL = 'http://localhost:5173';
const SCREENSHOT_DIR = path.join(__dirname, '..', 'screenshots');

const PAGES = [
  { path: '', name: 'dashboard' },
  { path: '/goals', name: 'goals' },
  { path: '/fleet', name: 'fleet' },
  { path: '/experiences', name: 'experiences' },
  { path: '/agents', name: 'agents' },
  { path: '/monitor', name: 'monitor' },
];

async function takeScreenshots() {
  let browser;
  try {
    browser = await chromium.launch();

    // Create directory if doesn't exist
    if (!fs.existsSync(SCREENSHOT_DIR)) {
      fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
    }

    console.log(`📸 Capturing dashboard screenshots...`);

    for (const page of PAGES) {
      const context = await browser.createIncognitoBrowser();
      const browserPage = await context.newPage();

      // Set viewport for consistent screenshots
      await browserPage.setViewportSize({ width: 1280, height: 800 });

      try {
        const url = `${DASHBOARD_URL}${page.path}`;
        console.log(`  → ${url}`);
        await browserPage.goto(url, { waitUntil: 'networkidle' });

        // Wait for content to load
        await browserPage.waitForTimeout(1000);

        const filename = path.join(SCREENSHOT_DIR, `${page.name}.png`);
        await browserPage.screenshot({ path: filename, fullPage: false });
        console.log(`     ✓ Saved: screenshots/${page.name}.png`);
      } catch (err) {
        console.log(`     ✗ Failed: ${err.message}`);
      }

      await context.close();
    }

    console.log(`\n✅ Screenshots saved to ./screenshots/`);
    console.log(`\n📝 Add to README.md:`);
    console.log(`
## Dashboard Screenshots

### Main Dashboard
![Dashboard](screenshots/dashboard.png)

### Goals Management
![Goals](screenshots/goals.png)

### Agent Fleet
![Fleet](screenshots/fleet.png)

### Experience Base
![Experiences](screenshots/experiences.png)

### Agent Monitoring
![Agents](screenshots/agents.png)

### System Monitor
![Monitor](screenshots/monitor.png)
    `);
  } catch (err) {
    console.error('❌ Error:', err.message);
    process.exit(1);
  } finally {
    if (browser) {
      await browser.close();
    }
  }
}

takeScreenshots();
