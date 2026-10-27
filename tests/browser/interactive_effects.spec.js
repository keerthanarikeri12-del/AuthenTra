import { test, expect } from '@playwright/test';

test.describe('AuthenTra Interactive Effects, Scroll Wave & Accessibility', () => {

  test('Page scroll progress: decorative crimson wave is present and updates on scroll', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 600 });
    await page.goto('/');

    // 1. Verify scroll wave container and SVG exist
    const waveContainer = page.locator('.scroll-wave-container');
    await expect(waveContainer).toBeAttached();
    
    // Pointer events must be none so native scrolling and clicks are never intercepted
    const pointerEvents = await waveContainer.evaluate(el => window.getComputedStyle(el).pointerEvents);
    expect(pointerEvents).toBe('none');

    // 2. Verify wave stroke color is Crimson Red (#D21319)
    const wavePath = page.locator('.scroll-wave-path');
    await expect(wavePath).toBeAttached();
    const strokeColor = await wavePath.evaluate(el => window.getComputedStyle(el).stroke);
    // rgb(210, 19, 25) is #D21319
    expect(strokeColor).toMatch(/rgb\(210,\s*19,\s*25\)/);

    // Verify at top of page, offset is 100 (unfilled wave)
    const initialDashOffset = await wavePath.evaluate(el => parseFloat(el.getAttribute('stroke-dashoffset') || '100'));
    expect(initialDashOffset).toBe(100);

    // 3. Log in to dashboard which has a scrollable content area
    await page.getByLabel('Email address', { exact: true }).fill('verifier@authentra.demo');
    await page.getByLabel('Password', { exact: true }).fill('AuthenTra-demo-2026!');
    await page.getByRole('button', { name: 'Open workspace' }).click();

    await expect(page.getByRole('heading', { name: /Certificate Verification/i })).toBeVisible();

    // Ensure we start at top of dashboard
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(150);
    const topDashOffset = await wavePath.evaluate(el => parseFloat(el.getAttribute('stroke-dashoffset') || '100'));
    expect(topDashOffset).toBeGreaterThanOrEqual(95);

    // Scroll down window
    await page.evaluate(() => window.scrollTo(0, 500));
    await page.waitForTimeout(250);

    const scrolledDashOffset = await wavePath.evaluate(el => parseFloat(el.getAttribute('stroke-dashoffset') || '100'));
    
    // As user scrolls down, stroke-dashoffset decreases so the wave fills in
    const maxScroll = await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight);
    if (maxScroll > 50) {
      expect(scrolledDashOffset).toBeLessThan(topDashOffset);
    }
  });

  test('Reduced motion: decorative wave is hidden and scroll reveals are disabled', async ({ page }) => {
    // Emulate reduced motion
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');

    const waveContainer = page.locator('.scroll-wave-container');
    const isWaveHidden = await waveContainer.evaluate(el => {
      const style = window.getComputedStyle(el);
      return style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0';
    });
    expect(isWaveHidden).toBe(true);

    // Verify all scroll reveal items remain 100% visible with transform none
    const revealItems = page.locator('.scroll-reveal');
    const count = await revealItems.count();
    if (count > 0) {
      for (let i = 0; i < Math.min(count, 5); i++) {
        const item = revealItems.nth(i);
        const styles = await item.evaluate(el => {
          const s = window.getComputedStyle(el);
          return { opacity: parseFloat(s.opacity), transform: s.transform };
        });
        expect(styles.opacity).toBe(1);
        expect(styles.transform).toBe('none');
      }
    }

    // Verify login form is immediately visible and usable
    await expect(page.getByRole('button', { name: 'Open workspace' })).toBeVisible();
  });

  test('Keyboard accessibility: visible focus states and complete keyboard navigability', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/');

    // Focus email input and verify focus state
    const emailInput = page.getByLabel('Email address', { exact: true });
    await emailInput.focus();
    
    const emailFocused = await emailInput.evaluate(el => document.activeElement === el);
    expect(emailFocused).toBe(true);

    // Type credentials via keyboard
    await page.keyboard.type('verifier@authentra.demo');
    
    // Tab to password
    await page.keyboard.press('Tab');
    const passwordFocused = await page.getByLabel('Password', { exact: true }).evaluate(el => document.activeElement === el);
    expect(passwordFocused).toBe(true);

    await page.keyboard.type('AuthenTra-demo-2026!');

    // Tab to submit button
    await page.keyboard.press('Tab');
    const submitBtn = page.getByRole('button', { name: 'Open workspace' });
    const submitFocused = await submitBtn.evaluate(el => document.activeElement === el);
    expect(submitFocused).toBe(true);

    // Verify submit button has visible outline
    const submitOutline = await submitBtn.evaluate(el => {
      const s = window.getComputedStyle(el);
      return s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2;
    });
    expect(submitOutline).toBe(true);

    // Press Enter to submit
    await page.keyboard.press('Enter');

    // Verify successful login via keyboard
    await expect(page.getByRole('heading', { name: /Certificate Verification/i })).toBeVisible();

    // Verify sidebar navigation button can receive focus with visible outline
    const navBtn = page.getByRole('button', { name: 'Verify certificate' });
    await navBtn.focus();
    const navBtnFocus = await navBtn.evaluate(el => {
      const s = window.getComputedStyle(el);
      return s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2;
    });
    expect(navBtnFocus).toBe(true);
  });

  test('Mobile responsive & zero horizontal overflow', async ({ page }) => {
    // Narrow mobile viewport (360px width)
    await page.setViewportSize({ width: 360, height: 740 });
    await page.goto('/');

    // Check login page horizontal overflow
    let hasOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(hasOverflow).toBe(false);

    // Login and check dashboard
    await page.getByLabel('Email address', { exact: true }).fill('verifier@authentra.demo');
    await page.getByLabel('Password', { exact: true }).fill('AuthenTra-demo-2026!');
    await page.getByRole('button', { name: 'Open workspace' }).click();

    await expect(page.getByRole('heading', { name: /Certificate Verification/i })).toBeVisible();

    // Check dashboard horizontal overflow
    hasOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(hasOverflow).toBe(false);
  });

  test('Micro-interactions: interactive elements have transition and hover styles', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/');

    // Log in
    await page.getByLabel('Email address', { exact: true }).fill('verifier@authentra.demo');
    await page.getByLabel('Password', { exact: true }).fill('AuthenTra-demo-2026!');
    await page.getByRole('button', { name: 'Open workspace' }).click();

    await expect(page.getByRole('heading', { name: /Certificate Verification/i })).toBeVisible();

    // Verify stat-card has transition property for smooth hover
    const statCard = page.locator('.stat-card').first();
    const cardTransition = await statCard.evaluate(el => window.getComputedStyle(el).transition);
    expect(cardTransition).toMatch(/transform|box-shadow|all/);

    // Verify primary buttons have transition property
    const primaryBtn = page.locator('button.primary').first();
    const btnTransition = await primaryBtn.evaluate(el => window.getComputedStyle(el).transition);
    expect(btnTransition).toMatch(/transform|background|all/);
  });

  test('Sample certificates: hover and keyboard focus preview, zero eager loading, and activation loading', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/');

    // 1. Log in to Verifier dashboard where sample certificates exist
    await page.getByLabel('Email address', { exact: true }).fill('verifier@authentra.demo');
    await page.getByLabel('Password', { exact: true }).fill('AuthenTra-demo-2026!');
    await page.getByRole('button', { name: 'Open workspace' }).click();

    await expect(page.getByRole('heading', { name: /Certificate Verification/i })).toBeVisible();

    // 2. Ensure initially no files are selected
    await expect(page.getByText('No files selected')).toBeVisible();
    await expect(page.locator('.upload-file-card')).toHaveCount(0);
    const previewPanel = page.locator('#sample-preview-panel');
    await expect(previewPanel).toHaveCount(0);

    // 3. Test Hover on "Original" sample button
    const originalBtn = page.getByRole('button', { name: 'Original', exact: true });
    await expect(originalBtn).toBeVisible();
    await originalBtn.hover();

    // Verify preview card appears
    await expect(previewPanel).toBeVisible();
    await expect(previewPanel.getByText('Sample preview')).toBeVisible();
    await expect(previewPanel.getByText(/Activating this sample loads its local demo file/i)).toBeVisible();
    await expect(previewPanel.locator('.sample-preview-title')).toHaveText('Original');
    await expect(previewPanel.locator('.sample-preview-ref')).toHaveText('AT-2026-0001');
    await expect(previewPanel.locator('.sample-preview-filename')).toHaveText('original.pdf');

    // Crucial check: verify that hovering did NOT load or select any file
    await expect(page.locator('.upload-file-card')).toHaveCount(0);
    await expect(page.getByText('No files selected')).toBeVisible();

    // Un-hover
    await page.mouse.move(0, 0);
    await page.waitForTimeout(200);

    // 4. Test Keyboard Focus on "Modified" sample button
    const modifiedBtn = page.getByRole('button', { name: 'Modified', exact: true });
    await modifiedBtn.focus();

    // Verify preview card updates on keyboard focus
    await expect(previewPanel).toBeVisible();
    await expect(previewPanel.locator('.sample-preview-title')).toHaveText('Modified');
    await expect(previewPanel.locator('.sample-preview-ref')).toHaveText('AT-2026-0001');
    await expect(previewPanel.locator('.sample-preview-filename')).toHaveText('modified.pdf');

    // Still no files selected before activation
    await expect(page.locator('.upload-file-card')).toHaveCount(0);

    // 5. Test real sample loading upon activation
    await originalBtn.focus();
    await page.keyboard.press('Enter');

    // Verify file is now selected and loaded
    await expect(page.locator('.upload-file-card')).toHaveCount(1);
    await expect(page.locator('.upload-file-info strong')).toHaveText('original.pdf');
    await expect(page.locator('input[id^="ref-"]')).toHaveValue('AT-2026-0001');
  });

});

