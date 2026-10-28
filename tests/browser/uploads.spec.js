import {test, expect} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

async function login(page, institution = false) {
  await page.goto('/');
  if (institution) await page.getByRole('button', {name:'Institution Login', exact:true}).click();
  await page.getByLabel(institution ? 'Official email address' : 'Email address', {exact:true}).fill(institution ? 'issuer@authentra.demo' : 'verifier@authentra.demo');
  await page.getByLabel('Password', {exact:true}).fill('AuthenTra-demo-2026!');
  await page.getByRole('button', {name:'Open workspace'}).click();
  if (institution) {
    await page.getByRole('button', {name: 'Register Credentials'}).click();
  }
  await expect(page.getByRole('button', {name:'Browse Files'})).toBeVisible();
}
const originals = ['samples/original.pdf', 'samples/modified.pdf'].map(f => path.resolve(f));

test('user validation, previews, removal, and real per-file verification', async ({page}) => {
  const errors=[]; page.on('pageerror', error=>errors.push(error.message));
  await login(page);
  const picker = page.getByLabel('Choose certificate files');
  await picker.setInputFiles({name:'broken.pdf',mimeType:'application/pdf',buffer:Buffer.from('unreadable')});
  await expect(page.getByText('This is not a readable PDF.')).toBeVisible();
  await expect(page.getByRole('button',{name:'Begin verification'})).toBeDisabled();
  await page.getByRole('button',{name:'Remove broken.pdf'}).click();
  await picker.setInputFiles(Array.from({length:6},(_,i)=>({name:`file-${i}.pdf`,mimeType:'application/pdf',buffer:fs.readFileSync(originals[0])})));
  await expect(page.getByRole('alert').filter({hasText:'at most 5'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Begin verification'})).toBeDisabled();
  await picker.setInputFiles(originals);
  await expect(page.locator('.upload-file-card')).toHaveCount(2);
  await expect(page.locator('.certificate-preview:not(.placeholder)')).toHaveCount(2);
  await expect(page.getByRole('button',{name:'Begin verification'})).toBeEnabled();
  await page.screenshot({path:'.local/upload-user-desktop.png',fullPage:true});
  await page.getByRole('button',{name:'Begin verification'}).click();
  await expect(page.getByRole('heading',{name:'Batch complete',exact:true})).toBeVisible();
  await expect(page.locator('.file-outcome')).toHaveCount(2);
  await expect(page.locator('.file-outcome').nth(0).getByRole('heading',{name:'Verified',exact:true})).toBeVisible();
  await expect(page.locator('.file-outcome').nth(1).getByRole('heading',{name:/Possible Tampering/})).toBeVisible();
  const report = await page.request.get(await page.getByRole('link',{name:'CSV report'}).getAttribute('href'));
  expect(report.status()).toBe(200); expect(await report.text()).toContain('possible_tampering');
  await page.reload();
  await page.getByText('Recent upload batches', {exact:true}).click();
  await expect(page.locator('.recent-batch').first()).toBeVisible();
  expect(errors).toEqual([]);
});

test('institution registration confirms real receipts and preserves partial failures', async ({page}) => {
  await login(page,true);
  await page.getByLabel('Choose certificate files').setInputFiles(['.local/e2e-first.pdf','.local/e2e-second.pdf'].map(f=>path.resolve(f)));
  const fields = page.locator('.upload-file-card input');
  await expect(page.locator('.certificate-preview:not(.placeholder)')).toHaveCount(2);
  await fields.nth(0).fill('AT-UI-' + Date.now());
  await fields.nth(1).fill('AT-2026-0001');
  await page.getByRole('button',{name:'Register certificates',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Batch complete',exact:true})).toBeVisible();
  await expect(page.locator('.file-outcome').nth(0).getByText(/Registered/i)).toBeVisible();
  await expect(page.locator('.file-outcome').nth(0).locator('.upload-transaction code')).toContainText(/[a-f0-9]{64}/i);
  await expect(page.locator('.file-outcome').nth(1).getByText(/Registration Failed|Failed/i)).toBeVisible();
  await expect(page.locator('.file-outcome').nth(1)).toContainText('already exists');
  await page.screenshot({path:'.local/upload-institution-results.png',fullPage:true});
});

test('UI never displays successful registration before confirmed on-chain registration', async ({page}) => {
  let stage = 'PENDING_BLOCKCHAIN';
  await page.route('**/api/uploads/job-mock-test', async route => {
    if (stage === 'PENDING_BLOCKCHAIN') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'job-mock-test',
          mode: 'register',
          state: 'processing',
          summary: {total: 1, valid: 1, rejected: 0, pending: 1, successful: 0, failed: 0},
          items: [{
            id: 101,
            filename: 'cert-pending.pdf',
            reference: 'AT-PENDING-001',
            kind: 'pdf',
            state: 'processing',
            status: 'PENDING_BLOCKCHAIN',
            result: null
          }]
        })
      });
    } else if (stage === 'AWAITING_REVIEW') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'job-mock-test',
          mode: 'register',
          state: 'processing',
          summary: {total: 1, valid: 1, rejected: 0, pending: 1, successful: 0, failed: 0},
          items: [{
            id: 101,
            filename: 'cert-pending.pdf',
            reference: '',
            kind: 'pdf',
            state: 'awaiting_review',
            status: 'AWAITING_REVIEW',
            ocr_confidence: 42,
            result: {status: 'AWAITING_REVIEW', message: 'Low OCR confidence. Human review required.'}
          }]
        })
      });
    } else if (stage === 'REGISTRATION_FAILED') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'job-mock-test',
          mode: 'register',
          state: 'processing',
          summary: {total: 1, valid: 1, rejected: 0, pending: 1, successful: 0, failed: 1},
          items: [{
            id: 101,
            filename: 'cert-pending.pdf',
            reference: 'AT-PENDING-001',
            kind: 'pdf',
            state: 'failed',
            status: 'REGISTRATION_FAILED',
            result: {status: 'REGISTRATION_FAILED', error: 'Blockchain transaction reverted: Execution reverted'}
          }]
        })
      });
    } else if (stage === 'REGISTERED_ON_BLOCKCHAIN') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'job-mock-test',
          mode: 'register',
          state: 'completed',
          summary: {total: 1, valid: 1, rejected: 0, pending: 0, successful: 1, failed: 0},
          items: [{
            id: 101,
            filename: 'cert-pending.pdf',
            reference: 'AT-PENDING-001',
            kind: 'pdf',
            state: 'succeeded',
            status: 'REGISTERED_ON_BLOCKCHAIN',
            result: {
              status: 'REGISTERED_ON_BLOCKCHAIN',
              transaction_hash: '0x1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff',
              block_number: 142,
              on_chain_verified: true,
              explorer_url: 'https://sepolia.etherscan.io/tx/0x1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff'
            }
          }]
        })
      });
    }
  });

  await page.route('**/api/uploads?mode=register', async route => {
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([{
        id: 'job-mock-test',
        mode: 'register',
        state: 'processing',
        summary: {total: 1, valid: 1, rejected: 0, pending: 1, successful: 0, failed: 0}
      }])
    });
  });

  await login(page, true);

  // 1. In PENDING_BLOCKCHAIN state:
  await expect(page.getByText('Blockchain Registration Pending')).toBeVisible();
  // PROVE: "Registered on Blockchain" and transaction hashes MUST NOT be visible
  await expect(page.getByText('Registered on Blockchain')).not.toBeVisible();
  await expect(page.locator('.upload-transaction')).not.toBeVisible();
  await expect(page.locator('.explorer-link')).not.toBeVisible();

  // 2. Transition to AWAITING_REVIEW state:
  stage = 'AWAITING_REVIEW';
  await expect(page.getByText('Awaiting Review')).toBeVisible();
  await expect(page.getByText('Human review required before blockchain registration')).toBeVisible();
  // PROVE: STILL not registered
  await expect(page.getByText('Registered on Blockchain')).not.toBeVisible();
  await expect(page.locator('.upload-transaction')).not.toBeVisible();

  // 3. Transition to REGISTRATION_FAILED state (e.g. reverted transaction):
  stage = 'REGISTRATION_FAILED';
  await expect(page.getByText('Registration Failed')).toBeVisible();
  await expect(page.getByText('Blockchain transaction reverted')).toBeVisible();
  // PROVE: NEVER shows registered when transaction reverts
  await expect(page.getByText('Registered on Blockchain')).not.toBeVisible();
  await expect(page.locator('.upload-transaction')).not.toBeVisible();

  // 4. ONLY in confirmed REGISTERED_ON_BLOCKCHAIN state:
  stage = 'REGISTERED_ON_BLOCKCHAIN';
  await expect(page.getByText('Registered on Blockchain')).toBeVisible();
  await expect(page.locator('.upload-transaction code')).toContainText('0x1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff');
  await expect(page.locator('.explorer-link')).toBeVisible();
});

test('mobile selection remains accessible without horizontal overflow', async ({page}) => {
  await page.setViewportSize({width:390,height:844});
  await login(page);
  await page.getByLabel('Choose certificate files').setInputFiles(originals[0]);
  await expect(page.locator('.certificate-preview:not(.placeholder)')).toHaveCount(1);
  await page.getByRole('button',{name:'Browse Files'}).focus();
  await expect(page.getByRole('button',{name:'Browse Files'})).toBeFocused();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.screenshot({path:'.local/upload-user-mobile.png',fullPage:true});
  await page.getByRole('button',{name:'Remove original.pdf'}).click();
  await expect(page.getByText('No files selected.',{exact:false})).toBeVisible();
});

test('PNG and JPEG previews and duplicate selections are validated locally', async ({page}) => {
  await login(page);
  const picker=page.getByLabel('Choose certificate files');
  await picker.setInputFiles([path.resolve('samples/scan.png'), path.resolve('.local/e2e-image.jpg')]);
  await expect(page.locator('.certificate-preview:not(.placeholder)')).toHaveCount(2);
  await expect(page.getByRole('button',{name:'Begin verification'})).toBeEnabled();
  await picker.setInputFiles(path.resolve('.local/e2e-image.jpg'));
  await expect(page.getByText('Duplicate file. Remove this copy.',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Begin verification'})).toBeDisabled();
});
