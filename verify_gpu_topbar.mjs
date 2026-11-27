import puppeteer from 'puppeteer';

(async () => {
  const browser = await puppeteer.launch({ headless: 'new' });
  const page = await browser.newPage();
  await page.setViewport({ width: 1400, height: 900 });
  await page.goto('http://127.0.0.1:5000/', { waitUntil: 'networkidle2', timeout: 20000 });
  await new Promise(r => setTimeout(r, 1200));

  await page.screenshot({ path: 'C:/Users/Dell/.gemini/antigravity/brain/5bf1f793-a593-488a-8501-e22f375c5231/top_bar_gpu.png' });
  console.log('Saved top_bar_gpu.png');

  // Click GPU dropdown
  const gpuBtn = await page.$('#gpuDropdownBtn');
  if (gpuBtn) {
    await gpuBtn.click();
    await new Promise(r => setTimeout(r, 600));
    await page.screenshot({ path: 'C:/Users/Dell/.gemini/antigravity/brain/5bf1f793-a593-488a-8501-e22f375c5231/top_bar_gpu_open.png' });
    console.log('Saved top_bar_gpu_open.png');
  } else {
    console.log('Could not find #gpuDropdownBtn');
  }

  // Navigate to Trending and test hover preview
  await page.click('#navTrendingLink');
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: 'C:/Users/Dell/.gemini/antigravity/brain/5bf1f793-a593-488a-8501-e22f375c5231/trending_page_pc.png' });
  console.log('Saved trending_page_pc.png');

  // Hover first card
  const firstCard = await page.$('.trending-card');
  if (firstCard) {
    await firstCard.hover();
    await new Promise(r => setTimeout(r, 800));
    await page.screenshot({ path: 'C:/Users/Dell/.gemini/antigravity/brain/5bf1f793-a593-488a-8501-e22f375c5231/trending_card_hover.png' });
    console.log('Saved trending_card_hover.png');
  }

  await browser.close();
})();

