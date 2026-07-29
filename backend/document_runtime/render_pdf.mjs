import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
import { chromium } from "playwright";

const [, , htmlInput, pdfOutput] = process.argv;
if (!htmlInput || !pdfOutput) {
  process.stderr.write("usage: render_pdf.mjs <input.html> <output.pdf>\n");
  process.exit(2);
}

const inputPath = resolve(htmlInput);
const outputPath = resolve(pdfOutput);
let browser;

try {
  browser = await chromium.launch({
    headless: true,
    args: ["--disable-dev-shm-usage", "--no-sandbox"],
  });
  const context = await browser.newContext({
    javaScriptEnabled: false,
    locale: "ko-KR",
  });
  await context.route("**/*", async (route) => {
    const url = route.request().url();
    if (url.startsWith("file:") || url.startsWith("data:")) {
      await route.continue();
    } else {
      await route.abort("blockedbyclient");
    }
  });
  const page = await context.newPage();
  await page.emulateMedia({ media: "print" });
  await page.goto(pathToFileURL(inputPath).href, {
    waitUntil: "load",
    timeout: 30000,
  });
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  await page.pdf({
    path: outputPath,
    format: "A4",
    printBackground: true,
    preferCSSPageSize: true,
    displayHeaderFooter: false,
    tagged: true,
  });
  const title = await page.title();
  await context.close();
  process.stdout.write(
    `${JSON.stringify({
      engine: "chromium",
      playwrightVersion: "1.58.2",
      title,
      externalRequestsBlocked: true,
    })}\n`,
  );
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.stack : String(error)}\n`);
  process.exitCode = 1;
} finally {
  if (browser) {
    await browser.close();
  }
}
