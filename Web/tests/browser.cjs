const { chromium } = require('../.qa/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');

(async () => {
  const browser = await chromium.launch({
    executablePath: ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
      'C:/Program Files/Google/Chrome/Application/chrome.exe'].find(path => fs.existsSync(path)),
    headless: true,
    args: ['--no-proxy-server'],
  });
  const errors = [];
  async function load(context) {
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://127.0.0.1:5000/', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => !document.getElementById('search').disabled, { timeout: 25000 });
    await page.waitForFunction(() => {
      const tiles = Array.from(document.querySelectorAll('img.leaflet-tile'));
      return tiles.length > 0 && tiles.every(image => image.complete && image.naturalWidth > 0);
    }, { timeout: 15000 }).catch(() => console.log('Basemap tiles not fully loaded; checking data layers.'));
    return page;
  }
  try {
    const context = await browser.newContext({ viewport: { width: 1366, height: 900 },
      permissions: ['geolocation'], geolocation: { latitude: -7.782911, longitude: 110.367, accuracy: 8 }, acceptDownloads: true });
    const page = await load(context);
    assert.equal(await page.locator('.place-item').count(), 6);
    assert.equal(await page.locator('#category-field').isVisible(), false);
    await page.screenshot({ path: '.qa/desktop.png', fullPage: true });
    await page.locator('#search').fill('Keraton');
    assert.equal(await page.locator('.place-item').count(), 1);
    await page.locator('.place-item').click();
    assert.match(await page.locator('.leaflet-popup-content').innerText(), /Keraton Yogyakarta/);
    await page.locator('#search').fill('tidak ada nama');
    assert.equal(await page.locator('#search-empty').isVisible(), true);
    await page.locator('#search').fill('');
    await page.locator('.leaflet-marker-icon').first().click();
    assert.equal(await page.locator('.leaflet-popup-content').count(), 1);
    await page.locator('.fit-control button').click();
    await page.locator('#tab-rute').click();
    assert.equal(await page.locator('#calculate-button').isDisabled(), true);
    await page.locator('#locate-button').click();
    await page.waitForFunction(() => !document.getElementById('calculate-button').disabled);
    for (const scenario of ['rute-1', 'rute-2', 'rute-3']) {
      await page.locator('#scenario').selectOption(scenario);
      await page.locator('#calculate-button').click();
      await page.waitForFunction(() => !document.getElementById('route-summary').hidden, { timeout: 12000 });
      assert.ok(Number((await page.locator('#total-distance').innerText()).replace(',', '.')) > 0);
      console.log(scenario, await page.locator('#total-distance').innerText(), 'km');
      assert.equal(await page.locator('.number-marker').count(), scenario === 'rute-1' ? 4 : scenario === 'rute-2' ? 3 : 6);
    }
    await page.screenshot({ path: '.qa/desktop-route.png', fullPage: true });
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#download-route').click();
    const download = await downloadPromise;
    await download.saveAs('.qa/download.geojson');
    const exported = JSON.parse(fs.readFileSync('.qa/download.geojson', 'utf8'));
    assert.equal(exported.features[0].properties.route_id, 'rute-3');
    await page.locator('#clear-route').click();
    assert.equal(await page.locator('#route-summary').isVisible(), false);
    assert.equal(await page.locator('#download-route').isDisabled(), true);
    await page.locator('#pick-button').click();
    const bounds = await page.locator('#map').boundingBox();
    await page.mouse.click(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
    assert.match(await page.locator('#start-label').innerText(), /Pilihan peta/);
    await page.locator('#calculate-button').click();
    await page.waitForFunction(() => !document.getElementById('route-summary').hidden);
    await page.locator('.leaflet-control-layers').hover();
    const layers = page.locator('.leaflet-control-layers-overlays label');
    await layers.filter({ hasText: 'Jaringan jalan' }).locator('input').check();
    await layers.filter({ hasText: 'Rute simulasi' }).locator('input').uncheck();
    assert.match(await page.locator('#map-caption').innerText(), /disembunyikan/);
    await layers.filter({ hasText: 'Rute simulasi' }).locator('input').check();
    await page.locator('#about-button').click();
    assert.equal(await page.locator('#about-dialog').isVisible(), true);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#about-dialog').isVisible(), false);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);

    // Hasil permintaan lama tidak boleh muncul setelah skenario diganti.
    await page.locator('#clear-route').click();
    await page.route('**/api/rute', async route => {
      await new Promise(resolve => setTimeout(resolve, 300));
      await route.continue().catch(() => {});
    });
    const oldRequest = page.waitForRequest('**/api/rute');
    await page.locator('#calculate-button').click();
    await oldRequest;
    await page.locator('#scenario').selectOption('rute-2');
    await page.waitForTimeout(500);
    assert.equal(await page.locator('#route-summary').isVisible(), false);
    await page.unroute('**/api/rute');

    const phoneContext = await browser.newContext({ viewport: { width: 390, height: 844 },
      deviceScaleFactor: 1, isMobile: true, hasTouch: true,
      permissions: ['geolocation'], geolocation: { latitude: -7.782911, longitude: 110.367 } });
    const phone = await load(phoneContext);
    assert.equal(await phone.locator('#sidebar').isVisible(), false);
    await phone.screenshot({ path: '.qa/mobile.png', fullPage: true });
    await phone.locator('#mobile-explore').click();
    assert.equal(await phone.locator('#sidebar').isVisible(), true);
    await phone.screenshot({ path: '.qa/mobile-panel.png', fullPage: true });
    await phone.locator('#tab-rute').click();
    await phone.locator('#locate-button').click();
    await phone.waitForFunction(() => !document.getElementById('calculate-button').disabled);
    await phone.locator('#calculate-button').click();
    await phone.waitForFunction(() => !document.getElementById('route-summary').hidden);
    assert.equal(await phone.locator('#sidebar').isVisible(), false);
    await phone.screenshot({ path: '.qa/mobile-route.png', fullPage: true });
    await phone.locator('#panel-toggle').click();
    assert.equal(await phone.locator('#route-summary').isVisible(), true);
    assert.equal(await phone.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await phone.setViewportSize({ width: 844, height: 390 });
    assert.equal(await phone.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.equal(await phone.evaluate(() => document.documentElement.scrollHeight > innerHeight), false);

    const missingContext = await browser.newContext();
    await missingContext.route('**/api/wisata', route => route.fulfill({ status: 503,
      contentType: 'application/json', body: JSON.stringify({ error: { message: 'Data wisata tidak tersedia.' } }) }));
    const missingPage = await missingContext.newPage();
    missingPage.on('pageerror', error => errors.push(error.message));
    await missingPage.goto('http://127.0.0.1:5000/');
    await missingPage.waitForFunction(() => document.getElementById('app-shell').getAttribute('aria-busy') === 'false');
    assert.match(await missingPage.locator('#app-status').innerText(), /Data wisata tidak tersedia/);
    assert.equal(await missingPage.locator('#calculate-button').isDisabled(), true);
    await missingContext.close();

    for (const code of [1, 2, 3]) {
      const failContext = await browser.newContext({ viewport: { width: 1024, height: 768 } });
      await failContext.addInitScript((errorCode) => {
        Object.defineProperty(navigator, 'geolocation', { value: { getCurrentPosition(_success, failure) { failure({ code: errorCode }); } } });
      }, code);
      const failing = await load(failContext);
      await failing.locator('#tab-rute').click();
      await failing.locator('#locate-button').click();
      assert.equal(await failing.locator('#route-status.notice-error').isVisible(), true);
      assert.equal(await failing.locator('#calculate-button').isDisabled(), true);
      await failContext.close();
    }
    const outsideContext = await browser.newContext({ permissions: ['geolocation'], geolocation: { latitude: -6.2, longitude: 106.8 } });
    const outside = await load(outsideContext);
    await outside.locator('#tab-rute').click();
    await outside.locator('#locate-button').click();
    await outside.waitForFunction(() => !document.getElementById('calculate-button').disabled);
    await outside.locator('#calculate-button').click();
    await outside.waitForFunction(() => document.getElementById('route-status').classList.contains('notice-error'));
    assert.equal(await outside.locator('#route-summary').isVisible(), false);
    assert.match(await outside.locator('#route-status').innerText(), /batasnya/);
    await outside.locator('#pick-button').click();
    const outsideBounds = await outside.locator('#map').boundingBox();
    await outside.mouse.click(outsideBounds.x + outsideBounds.width / 2, outsideBounds.y + outsideBounds.height / 2);
    assert.match(await outside.locator('#start-label').innerText(), /Pilihan peta.*-7\./);
    await outside.locator('#calculate-button').click();
    await outside.waitForFunction(() => !document.getElementById('route-summary').hidden);
    assert.deepEqual(errors, []);
    console.log('PASS: desktop, mobile viewport, search, popup, GPS mocks, manual start, 3 routes, export, layers, reset, errors; no JavaScript exceptions.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
