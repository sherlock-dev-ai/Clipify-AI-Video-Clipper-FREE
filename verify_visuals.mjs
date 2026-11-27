import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  
  // 1. Check Trending
  await page.goto('http://127.0.0.1:5000/#trending', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: 'C:/Users/Dell/.gemini/antigravity/brain/5bf1f793-a593-488a-8501-e22f375c5231/trending_fixed_v503.png' });

  // 2. Check Editor
  await page.goto('http://127.0.0.1:5000/#editor', { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  const txtInput = await page.locator('#editorTextValue');
  if (await txtInput.count() > 0) {
    await txtInput.fill('wassap');
    await txtInput.dispatchEvent('input');
  }
  await page.waitForTimeout(500);
  await page.screenshot({ path: 'C:/Users/Dell/.gemini/antigravity/brain/5bf1f793-a593-488a-8501-e22f375c5231/editor_fixed_nobox_v503.png' });

  await browser.close();
  console.log('Screenshots captured successfully!');
})();

