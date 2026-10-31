import { createWorker } from 'tesseract.js';
import { createRequire } from 'node:module';
import path from 'node:path';
const require = createRequire(import.meta.url);
const langPath = path.join(path.dirname(require.resolve('@tesseract.js-data/eng/package.json')), '4.0.0');
let worker;
try {
  worker = await createWorker('eng', 1, { langPath, cacheMethod: 'none', logger: () => {} });
  try {
    await worker.setParameters({
      tessedit_pageseg_mode: '3',
      preserve_interword_spaces: '1'
    });
  } catch {}
  const { data } = await worker.recognize(process.argv[2]);
  console.log(JSON.stringify({ text: data.text, confidence: data.confidence }));
} finally { if (worker) await worker.terminate(); }
