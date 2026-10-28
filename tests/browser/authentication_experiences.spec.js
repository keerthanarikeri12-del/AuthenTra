import { test, expect } from '@playwright/test';

test.describe('Two Separate Authentication Experiences', () => {
  test('User Login Experience: Google, Apple buttons and Verifier dashboard access', async ({ page }) => {
    await page.goto('/');

    // 1. Check User Login heading and options
    await expect(page.getByRole('heading', { name: 'User Login' })).toBeVisible();
    await expect(page.getByText('Verify certificates and view your private verification history.')).toBeVisible();

    // 2. Check Continue with Google & Continue with Apple buttons
    const googleBtn = page.getByRole('button', { name: 'Continue with Google' });
    const appleBtn = page.getByRole('button', { name: 'Continue with Apple' });
    await expect(googleBtn).toBeVisible();
    await expect(appleBtn).toBeVisible();

    // 3. Password login for Verifier role
    await page.getByLabel('Email address', { exact: true }).fill('verifier@authentra.demo');
    await page.getByLabel('Password', { exact: true }).fill('AuthenTra-demo-2026!');
    await page.getByRole('button', { name: 'Open workspace' }).click();

    // 4. Verify landing on User Dashboard (Verification interface)
    await expect(page.getByRole('heading', { name: 'Certificate verification' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Browse Files' })).toBeVisible();

    // 5. Verify User role nav items
    await expect(page.getByRole('button', { name: 'Verify certificate' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Verification history' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'System Architecture' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Evaluation & Evidence' })).toHaveCount(0);
    // Verifier should NOT have Certificate registry or Institutions management
    await expect(page.getByRole('button', { name: 'Certificate Registry' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Institutions' })).toHaveCount(0);

    // Playwright check: navigate to /#evidence as verifier and expect fallback to Certificate verification
    await page.goto('/#evidence');
    await expect(page.getByRole('heading', { name: 'Certificate verification' })).toBeVisible();
    await expect(page.getByText('MEASURE, THEN CLAIM')).toHaveCount(0);

    // 6. Sign out
    await page.getByRole('button', { name: 'Sign out' }).click();
    await expect(page.getByRole('heading', { name: 'User Login' })).toBeVisible();
  });

  test('Institution Login Experience: Domain Policy, Signup, Verification, and Approved Access', async ({ page }) => {
    await page.goto('/');

    // 1. Switch to Institution Login
    await page.getByRole('button', { name: 'Institution Login', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Institution Login' })).toBeVisible();
    await expect(page.getByText('Accredited Institutional Email Policy')).toBeVisible();
    await expect(page.getByText('Official educational domains ending in .edu, .ac.in, .edu.in')).toBeVisible();

    // 2. Open Institution Registration
    await page.getByRole('button', { name: 'New institution? Apply for approval' }).click();
    await expect(page.getByRole('heading', { name: 'Register your institution' })).toBeVisible();
    await expect(page.getByLabel('Institution name')).toBeVisible();
    await expect(page.getByLabel('Institution ID / registration reference')).toBeVisible();
    await expect(page.getByLabel('Verification information')).toBeVisible();
    await expect(page.getByLabel('Institution Ethereum wallet')).toBeVisible();
    await expect(page.getByLabel('Official email address')).toBeVisible();

    // 3. Test rejection of fake domain (e.g. attacker@fakeedu.com)
    await page.getByLabel('Institution name').fill('Spoofed University');
    await page.getByLabel('Institution ID / registration reference').fill('FAKE-2026-001');
    await page.getByLabel('Verification information').fill('https://fakeedu.com office headquarters');
    await page.getByLabel('Institution Ethereum wallet').fill('0x1111111111111111111111111111111111111111');
    await page.getByLabel('Official email address').fill('admin@fakeedu.com');
    await page.getByLabel('Password').fill('StrongPass123456!');
    await page.getByRole('button', { name: 'Apply for approval' }).click();

    // Expect domain policy rejection error
    await expect(page.getByRole('alert')).toContainText(/not recognized as an official educational institution/i);

    // 4. Test valid institutional domain submission (e.g. registrar@iitb.ac.in)
    const testWallet = '0x' + Array.from({length: 40}, () => Math.floor(Math.random()*16).toString(16)).join('');
    const testEmail = `registrar.${Date.now()}@iitb.ac.in`;
    await page.getByLabel('Institution name').fill('Indian Institute of Technology Bombay');
    await page.getByLabel('Institution ID / registration reference').fill('IITB-REG-2026');
    await page.getByLabel('Verification information').fill('https://www.iitb.ac.in Powai, Mumbai 400076');
    await page.getByLabel('Institution Ethereum wallet').fill(testWallet);
    await page.getByLabel('Official email address').fill(testEmail);
    await page.getByRole('button', { name: 'Apply for approval' }).click();

    // Expect transition to Email Verification card
    await expect(page.getByText('Verify Institutional Email')).toBeVisible();
    await expect(page.getByText('Enter 6-digit verification code')).toBeVisible();

    // 5. Approved Institution Sign in
    await page.getByRole('button', { name: 'Back to login' }).click();
    await page.getByLabel('Official email address', { exact: true }).fill('issuer@authentra.demo');
    await page.getByLabel('Password', { exact: true }).fill('AuthenTra-demo-2026!');
    await page.getByRole('button', { name: 'Open workspace' }).click();

    // Verify access to Issuer workspace (Institution Dashboard & Issued certificates)
    await expect(page.getByRole('heading', { name: 'Institution Dashboard' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Institution Dashboard' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Bulk Register Certificates' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Issued certificates' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Certificate Registry' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Evaluation & Evidence' })).toHaveCount(0);

    // Playwright check: click "Bulk Register Certificates" and expect the "Register Certificates on Blockchain" heading
    await page.getByRole('button', { name: 'Bulk Register Certificates' }).click();
    await expect(page.getByRole('heading', { name: 'Register Certificates on Blockchain' })).toBeVisible();

    // Playwright check: navigate to /#registry and /#evidence and expect to land on the Institution Dashboard
    await page.goto('/#registry');
    await expect(page.getByRole('heading', { name: 'Institution Dashboard' })).toBeVisible();

    await page.goto('/#evidence');
    await expect(page.getByRole('heading', { name: 'Institution Dashboard' })).toBeVisible();
  });

  test('System Admin Login Experience: Admin navigation and Evaluation & Evidence unreachable', async ({ page }) => {
    await page.goto('/#admin');
    await expect(page.getByRole('heading', { name: 'Administrator Portal' })).toBeVisible();
    await page.getByLabel('Administrator email', { exact: true }).fill('owner@authentra.demo');
    await page.getByLabel('Password', { exact: true }).fill('AuthenTra-demo-2026!');
    await page.getByRole('button', { name: 'Sign in to Admin Console' }).click();

    // Verify System Admin navigation: Admin Overview and System Architecture visible, Evaluation & Evidence not present
    await expect(page.getByRole('button', { name: 'Admin Overview' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'System Architecture' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Evaluation & Evidence' })).toHaveCount(0);

    // Playwright check: navigate to /#evidence as owner and expect to land on Admin Overview
    await page.goto('/#evidence');
    await expect(page.getByRole('heading', { name: 'System Administration Console' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Admin Overview' })).toBeVisible();
    await expect(page.getByText('MEASURE, THEN CLAIM')).toHaveCount(0);
  });
});
