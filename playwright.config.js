import {defineConfig} from '@playwright/test';
export default defineConfig({
  globalSetup: './tests/browser/setup.js',
  testDir: './tests/browser',
  timeout: 90000,
  expect: {timeout: 20000},
  workers: 1,
  outputDir: '.local/browser-results',
  use: {baseURL: process.env.AUTHENTRA_TEST_URL || 'http://127.0.0.1:8000', browserName:'chromium', channel:process.env.AUTHENTRA_BROWSER_CHANNEL || 'msedge', headless:true, screenshot:'only-on-failure'},
  reporter: 'list',
});
