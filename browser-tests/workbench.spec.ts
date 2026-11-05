import {test, expect} from '@playwright/test';

test.beforeEach(async ({request}) => {
 await request.post('/api/control', {data:{action:'stop'}});
 await request.post('/api/settings', {data:{target:'als', timing:'realtime'}});
 await request.post('/api/circuit', {data:{action:'clear'}});
});

test.afterEach(async ({request}) => {
 await request.post('/api/circuit', {data:{action:'clear'}});
 await request.post('/api/settings', {data:{target:'als', timing:'realtime'}});
});

test('catalogue search finds parts by intent and tolerates typos', async ({page}) => {
 await page.goto('/#bench');
 const search = page.getByLabel('Search components');
 await search.fill('measure distance');
 await expect(page.locator('.bench-card').first()).toContainText(/HC-SR04|Sharp/);
 await search.fill('ultrasonc');
 await expect(page.getByRole('button', {name:'Place HC-SR04 ultrasonic sensor'})).toBeVisible();
 await search.fill('');
 await page.getByLabel('Compatibility').selectOption('needs');
 await expect(page.getByRole('button', {name:'Place Breadboard', exact:true})).toHaveCount(0);
 await expect(page.getByRole('button', {name:/Place MQ-2/})).toBeVisible();
});

test('3D bench renders the kit and placed parts', async ({page, request}) => {
 await request.post('/api/circuit', {data:{action:'add', type:'breadboard', id:'bb1', placement:{x:20, z:0, rot:0}}});
 await request.post('/api/circuit', {data:{action:'add', type:'led', id:'led1', placement:{x:20+13*2.54, z:-5.08, rot:0},
  mount:{A:'bb1.c14', K:'bb1.c15'}}});
 await page.goto('/#bench');
 await expect(page.locator('canvas')).toBeVisible();
 await page.waitForTimeout(1500);
 await page.screenshot({path:'test-results/workbench-3d.png'});
 const lit = await page.locator('canvas').evaluate((c:HTMLCanvasElement) => {
  const ctx = document.createElement('canvas').getContext('2d')!;
  ctx.canvas.width = 64; ctx.canvas.height = 64; ctx.drawImage(c, 0, 0, 64, 64);
  const data = ctx.getImageData(0, 0, 64, 64).data;
  let colours = new Set<number>();
  for (let i = 0; i < data.length; i += 4) colours.add((data[i] >> 4) << 8 | (data[i+1] >> 4) << 4 | data[i+2] >> 4);
  return colours.size;
 });
 expect(lit).toBeGreaterThan(20);  // not a blank clear colour
});

test('Circuit Doctor explains a 5 V supply on a 3.3 V sensor and applies the fix', async ({page, request}) => {
 await request.post('/api/settings', {data:{target:'mbed'}});
 for (const step of [
  {action:'add', type:'bmp280', id:'bmp', placement:{x:30, z:-30, rot:0}},
  {action:'connect', a:'mbed.VU', b:'bmp.VCC'},
  {action:'connect', a:'mbed.GND', b:'bmp.GND'}]) await request.post('/api/circuit', {data:step});
 await page.goto('/#bench');
 const finding = page.locator('.finding', {hasText:'supply is 5.0 V'});
 await expect(finding).toBeVisible();
 await expect(finding).toContainText('absolute maximum 4.25 V');
 await finding.getByRole('button', {name:'Apply fix'}).first().click();
 await expect(page.locator('.finding', {hasText:'supply is 5.0 V'})).toHaveCount(0);
 const state = await (await request.get('/api/state')).json();
 expect(state.circuit.wires.some((w:string[]) => w.includes('mbed.VOUT') && w.includes('bmp.VCC'))).toBe(true);
});

test('serial monitor shows UART output from a bench example', async ({page}) => {
 await page.goto('/#bench');
 await page.getByLabel('Load a bench example').selectOption('uart_hello');
 await expect(page.getByText(/circuit wired and firmware compiled/)).toBeVisible({timeout:30000});
 await page.locator('.bench-toolbar').getByRole('button', {name:'▶ Run'}).click();
 await page.getByRole('tab', {name:'Serial'}).click();
 await expect(page.getByLabel('Received text')).toContainText('Hello from the LPC1768', {timeout:15000});
 await page.getByLabel('Text to send').fill('abc');
 await page.getByRole('button', {name:'Send', exact:true}).click();
 await expect(page.getByLabel('Received text')).toContainText('abc', {timeout:15000});
});

test('exam board screen is unchanged and free of Workbench hints', async ({page}) => {
 await page.goto('/#board');
 await expect(page.getByRole('button', {name:'Header CNA', exact:true})).toBeVisible();
 await expect(page.locator('.finding')).toHaveCount(0);
 await expect(page.getByText('Circuit Doctor')).toHaveCount(0);
});
