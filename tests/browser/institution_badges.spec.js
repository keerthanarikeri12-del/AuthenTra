import { test, expect } from '@playwright/test';

test.describe('Institution Governance Status Badges', () => {

  test('Desktop (1280px): approval and contract authorization badges are stacked vertically in upper-right without overlap', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });

    // 1. Log in as System Administrator at /#admin
    await page.goto('/#admin');
    await expect(page.getByRole('heading', { name: 'Administrator Portal' })).toBeVisible();
    await page.getByLabel('Administrator email', { exact: true }).fill('owner@authentra.demo');
    await page.getByLabel('Password', { exact: true }).fill('AuthenTra-demo-2026!');
    await page.getByRole('button', { name: 'Sign in to Admin Console' }).click();

    // 2. Wait for admin console landing and navigate to Institution Governance
    await expect(page.getByRole('button', { name: 'Admin Overview' })).toBeVisible();
    await page.getByRole('button', { name: 'Institution Governance' }).click();

    // Verify Institution Access Management page is displayed
    await expect(page.locator('.institution-grid')).toBeVisible();

    // 3. Switch to Pending Review tab if present
    const pendingTab = page.locator('.filter-tab:has-text("Pending Review")');
    if (await pendingTab.count() > 0) {
      await pendingTab.click();
    }

    // Locate the first institution card with PENDING_APPROVAL
    const card = page.locator('.institution-card:has-text("PENDING_APPROVAL")').first();
    await expect(card).toBeVisible();

    // 4. Verify both badges are present and visible inside the card status stack
    const statusStack = card.locator('.institution-status-stack');
    await expect(statusStack).toBeVisible();

    const approvalBadge = statusStack.locator('.badge:has-text("PENDING_APPROVAL")');
    const contractBadge = statusStack.locator('.badge:has-text("Not Authorized on Contract")');

    await expect(approvalBadge).toBeVisible();
    await expect(contractBadge).toBeVisible();

    // 5. Measure bounding boxes
    const box1 = await approvalBadge.boundingBox();
    const box2 = await contractBadge.boundingBox();
    const cardBox = await card.boundingBox();

    expect(box1).not.toBeNull();
    expect(box2).not.toBeNull();
    expect(cardBox).not.toBeNull();

    // 6. Strict No-Overlap Assertion:
    const horizontalOverlap = box1.x < box2.x + box2.width && box1.x + box1.width > box2.x;
    const verticalOverlap = box1.y < box2.y + box2.height && box1.y + box1.height > box2.y;
    expect(horizontalOverlap && verticalOverlap).toBe(false);

    // 7. Vertical Stack Verification:
    // The contract badge must appear below the approval badge with comfortable spacing (at least 4px)
    expect(box2.y).toBeGreaterThanOrEqual(box1.y + box1.height + 4);

    // 8. Desktop Placement:
    // Badges must be positioned in the card's upper right
    expect(box1.x + box1.width).toBeGreaterThan(cardBox.x + cardBox.width * 0.5);
    expect(box1.y).toBeLessThan(cardBox.y + cardBox.height * 0.4);
  });

  test('Mobile (390px): badges remain stacked, visible, non-overlapping, and placed below the title', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });

    // 1. Log in as System Administrator at /#admin
    await page.goto('/#admin');
    await expect(page.getByRole('heading', { name: 'Administrator Portal' })).toBeVisible();
    await page.getByLabel('Administrator email', { exact: true }).fill('owner@authentra.demo');
    await page.getByLabel('Password', { exact: true }).fill('AuthenTra-demo-2026!');
    await page.getByRole('button', { name: 'Sign in to Admin Console' }).click();

    // 2. Wait for admin console landing and navigate to Institution Governance
    await expect(page.locator('.welcome-row h1, .dashboard-hero h2, h2:has-text("System Administration Console")')).toBeVisible();
    await page.evaluate(() => { window.location.hash = 'institutions'; });
    await expect(page.locator('.institution-grid')).toBeVisible();

    // 3. Switch to Pending Review tab if present
    const pendingTab = page.locator('.filter-tab:has-text("Pending Review")');
    if (await pendingTab.count() > 0) {
      await pendingTab.click();
    }

    const card = page.locator('.institution-card:has-text("PENDING_APPROVAL")').first();
    await expect(card).toBeVisible();

    const statusStack = card.locator('.institution-status-stack');
    await expect(statusStack).toBeVisible();

    const approvalBadge = statusStack.locator('.badge:has-text("PENDING_APPROVAL")');
    const contractBadge = statusStack.locator('.badge:has-text("Not Authorized on Contract")');

    await expect(approvalBadge).toBeVisible();
    await expect(contractBadge).toBeVisible();

    // 4. Measure bounding boxes
    const box1 = await approvalBadge.boundingBox();
    const box2 = await contractBadge.boundingBox();
    const titleBox = await card.locator('.institution-card-title').boundingBox();

    expect(box1).not.toBeNull();
    expect(box2).not.toBeNull();
    expect(titleBox).not.toBeNull();

    // 5. Strict No-Overlap Assertion:
    const horizontalOverlap = box1.x < box2.x + box2.width && box1.x + box1.width > box2.x;
    const verticalOverlap = box1.y < box2.y + box2.height && box1.y + box1.height > box2.y;
    expect(horizontalOverlap && verticalOverlap).toBe(false);

    // 6. Vertical Stack Verification:
    expect(box2.y).toBeGreaterThanOrEqual(box1.y + box1.height + 4);

    // 7. Mobile Placement:
    // On mobile viewports, the badge stack moves below the institution title
    expect(box1.y).toBeGreaterThanOrEqual(titleBox.y + titleBox.height - 2);
  });

});
