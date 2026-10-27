import { test, expect } from '@playwright/test';

test.describe('Typography Scale, Visual Hierarchy & Responsive Viewports', () => {

  test('Desktop: typography scale maintains comfortable readability and editorial hierarchy', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/');

    // 1. Verify Login Story Display Heading uses Editorial Serif & comfortable size
    const storyH1 = page.locator('.story-content h1');
    await expect(storyH1).toBeVisible();
    const h1Styles = await storyH1.evaluate(el => {
      const s = window.getComputedStyle(el);
      return { fontSize: parseFloat(s.fontSize), fontFamily: s.fontFamily, color: s.color };
    });
    expect(h1Styles.fontSize).toBeGreaterThanOrEqual(32);
    expect(h1Styles.fontFamily.toLowerCase()).toMatch(/newsreader|playfair|georgia|serif/);

    // 2. Verify Body Copy is comfortably readable (>= 14px, not tiny 10-11px)
    const storyP = page.locator('.story-content > p');
    const pSize = await storyP.evaluate(el => parseFloat(window.getComputedStyle(el).fontSize));
    expect(pSize).toBeGreaterThanOrEqual(14);

    // 3. Verify Form Card Heading uses Editorial Serif
    const formH2 = page.locator('.login-inner h2');
    const h2Styles = await formH2.evaluate(el => {
      const s = window.getComputedStyle(el);
      return { fontSize: parseFloat(s.fontSize), fontFamily: s.fontFamily };
    });
    expect(h2Styles.fontSize).toBeGreaterThanOrEqual(24);
    expect(h2Styles.fontFamily.toLowerCase()).toMatch(/newsreader|playfair|georgia|serif/);

    // 4. Verify Form Labels and Inputs have comfortable readable sizes and tap heights
    const label = page.getByLabel('Email address', { exact: true });
    await expect(label).toBeVisible();
    const inputStyles = await label.evaluate(el => {
      const s = window.getComputedStyle(el);
      return { fontSize: parseFloat(s.fontSize), height: parseFloat(s.height) };
    });
    expect(inputStyles.fontSize).toBeGreaterThanOrEqual(14);
    expect(inputStyles.height).toBeGreaterThanOrEqual(40);

    // 5. Verify Primary Button has comfortable size and tap height
    const submitBtn = page.getByRole('button', { name: 'Open workspace' });
    const btnStyles = await submitBtn.evaluate(el => {
      const s = window.getComputedStyle(el);
      return { fontSize: parseFloat(s.fontSize), height: parseFloat(s.height) };
    });
    expect(btnStyles.fontSize).toBeGreaterThanOrEqual(13);
    expect(btnStyles.height).toBeGreaterThanOrEqual(42);

    // 6. Verify Portal Choice Buttons are comfortably readable (>= 13px)
    const portalBtn = page.getByRole('button', { name: 'User Portal' });
    const portalBtnSize = await portalBtn.evaluate(el => parseFloat(window.getComputedStyle(el).fontSize));
    expect(portalBtnSize).toBeGreaterThanOrEqual(13);

    // 7. Verify Captions & footer text are readable (never < 12px)
    const footerText = page.locator('.login-form footer');
    const footerSize = await footerText.evaluate(el => parseFloat(window.getComputedStyle(el).fontSize));
    expect(footerSize).toBeGreaterThanOrEqual(12);

    // 8. Verify no horizontal overflow on desktop
    const desktopOverflow = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
    expect(desktopOverflow).toBe(true);

    // 9. Sign in and test dashboard typography
    await page.getByLabel('Email address', { exact: true }).fill('verifier@authentra.demo');
    await page.getByLabel('Password', { exact: true }).fill('AuthenTra-demo-2026!');
    await submitBtn.click();

    // Verify Dashboard Heading uses Editorial Serif
    const dashboardHeading = page.locator('.welcome-row h1, .dashboard-hero h2').first();
    await expect(dashboardHeading).toBeVisible();
    const headingStyles = await dashboardHeading.evaluate(el => {
      const s = window.getComputedStyle(el);
      return { fontSize: parseFloat(s.fontSize), fontFamily: s.fontFamily };
    });
    expect(headingStyles.fontSize).toBeGreaterThanOrEqual(24);
    expect(headingStyles.fontFamily.toLowerCase()).toMatch(/newsreader|playfair|georgia|serif/);

    // Verify Navigation button font size and height
    const navBtn = page.getByRole('button', { name: 'Verify certificate' });
    const navStyles = await navBtn.evaluate(el => {
      const s = window.getComputedStyle(el);
      return { fontSize: parseFloat(s.fontSize), height: parseFloat(s.height) };
    });
    expect(navStyles.fontSize).toBeGreaterThanOrEqual(13);
    expect(navStyles.height).toBeGreaterThanOrEqual(40);

    // Verify Badges and pills are at least 12px
    const badges = page.locator('.badge');
    const badgeCount = await badges.count();
    if (badgeCount > 0) {
      const badgeSize = await badges.first().evaluate(el => parseFloat(window.getComputedStyle(el).fontSize));
      expect(badgeSize).toBeGreaterThanOrEqual(12);
    }
  });

  test('Mobile: typography scales cleanly without cramped layout or horizontal overflow', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');

    // 1. Mobile login heading adapts without oversized overflow
    const mobileH1 = page.locator('.story-content h1');
    await expect(mobileH1).toBeVisible();
    const h1Size = await mobileH1.evaluate(el => parseFloat(window.getComputedStyle(el).fontSize));
    expect(h1Size).toBeLessThanOrEqual(32);
    expect(h1Size).toBeGreaterThanOrEqual(24);

    // 2. Mobile inputs use >= 16px to prevent iOS auto-zoom
    const emailInput = page.getByLabel('Email address', { exact: true });
    const inputSize = await emailInput.evaluate(el => parseFloat(window.getComputedStyle(el).fontSize));
    expect(inputSize).toBeGreaterThanOrEqual(16);

    // 3. No horizontal overflow on mobile login
    const loginOverflow = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
    expect(loginOverflow).toBe(true);

    // 4. Log in and inspect mobile dashboard
    await emailInput.fill('verifier@authentra.demo');
    await page.getByLabel('Password', { exact: true }).fill('AuthenTra-demo-2026!');
    await page.getByRole('button', { name: 'Open workspace' }).click();

    await expect(page.getByRole('heading', { name: /Certificate Verification/i })).toBeVisible();

    // Verify no horizontal overflow on mobile dashboard
    const dashboardOverflow = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
    expect(dashboardOverflow).toBe(true);

    // Verify sample chips and buttons maintain tap targets
    const browseBtn = page.getByRole('button', { name: 'Browse Files' });
    const btnHeight = await browseBtn.evaluate(el => parseFloat(window.getComputedStyle(el).height));
    expect(btnHeight).toBeGreaterThanOrEqual(38);
  });

});
