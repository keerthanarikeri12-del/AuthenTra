export const FILE_TYPES = {pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg'};
export const referenceError = value => /^[A-Z0-9][A-Z0-9_-]{2,63}$/i.test(value.trim()) ? '' : 'Use 3–64 letters, numbers, hyphens or underscores.';
export const formatBytes = bytes => bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${(bytes / 1024).toFixed(1)} KB`;
export function fileError(file, limits) {
  const ext = file.name.split('.').pop().toLowerCase();
  if (!FILE_TYPES[ext]) return 'Choose a PDF, PNG or JPG/JPEG. Archives are not supported.';
  if (file.type && file.type !== 'application/octet-stream' && file.type !== FILE_TYPES[ext]) return 'File type does not match its extension.';
  if (!file.size) return 'This file is empty.';
  if (file.size > limits.max_file_bytes) return `File exceeds ${formatBytes(limits.max_file_bytes)}.`;
  return '';
}
export function selectionError(items, limits) {
  if (items.length > limits.max_files) {
    if (limits.max_files === 5) {
      return `Users can upload a maximum of 5 certificate files per batch. You have ${items.length} files selected. Remove extra files to continue.`;
    }
    return `Choose at most ${limits.max_files} files per batch. You have ${items.length} files selected. Remove extra files to continue.`;
  }
  if (items.reduce((sum, item) => sum + item.file.size, 0) > limits.max_batch_bytes) return `Batch exceeds ${formatBytes(limits.max_batch_bytes)}. Remove files to continue.`;
  return '';
}

// Sequential validation keeps decoded images and PDF workers bounded for bulk selections.
export async function inspectFile(file, limits) {
  const error = fileError(file, limits);
  if (error) throw new Error(error);
  const data = new Uint8Array(await file.arrayBuffer());
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', data)), b => b.toString(16).padStart(2, '0')).join('');
  const ext = file.name.split('.').pop().toLowerCase();
  let preview;
  if (ext === 'pdf') {
    if (new TextDecoder().decode(data.slice(0, 5)) !== '%PDF-') throw new Error('This is not a readable PDF.');
    const pdfjs = await import('pdfjs-dist');
    const {default: workerUrl} = await import('pdfjs-dist/build/pdf.worker.min.mjs?url');
    pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
    const task = pdfjs.getDocument({data, isEvalSupported: false, stopAtErrors: true, useSystemFonts: true});
    let timeout;
    try {
      const readPdf = async () => {
      const pdf = await task.promise;
      if (pdf.numPages < 1 || pdf.numPages > 5) throw new Error('PDFs must contain 1–5 pages.');
      for (let i = 1; i <= pdf.numPages; i++) {
        const page = await pdf.getPage(i);
        await page.getOperatorList();
        if (i === 1) {
          const natural = page.getViewport({scale: 1});
          const viewport = page.getViewport({scale: Math.min(240 / natural.width, 240 / natural.height)});
          const canvas = document.createElement('canvas');
          canvas.width = Math.ceil(viewport.width); canvas.height = Math.ceil(viewport.height);
          await page.render({canvasContext: canvas.getContext('2d'), viewport}).promise;
          preview = canvas.toDataURL('image/png');
        }
        page.cleanup();
      }
      };
      await Promise.race([readPdf(), new Promise((_, reject) => {timeout = setTimeout(() => reject(new Error('PDF readability check timed out.')), 15000);})]);
    } catch (e) {
      throw new Error(e.name === 'PasswordException' ? 'Encrypted PDFs are not supported.' : e.message?.includes('pages') ? e.message : 'The PDF could not be read. Choose an unencrypted, readable PDF.');
    } finally {clearTimeout(timeout); await task.destroy();}
  } else {
    const png = data.slice(0, 8).every((v, i) => v === [137,80,78,71,13,10,26,10][i]);
    const jpeg = data[0] === 255 && data[1] === 216 && data[2] === 255;
    if (ext === 'png' ? !png : !jpeg) throw new Error('Image contents do not match the file type.');
    const url = URL.createObjectURL(file);
    try {
      const img = new Image(); img.src = url;
      await img.decode();
      if (img.naturalWidth * img.naturalHeight > 20000000) throw new Error('Image exceeds the 20 megapixel limit.');
      const canvas = document.createElement('canvas');
      const scale = Math.min(240 / img.naturalWidth, 240 / img.naturalHeight);
      canvas.width = Math.max(1, Math.round(img.naturalWidth * scale)); canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
      canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
      preview = canvas.toDataURL('image/png');
    } catch (e) {throw new Error(e.message.includes('megapixel') ? e.message : 'The image could not be read.');}
    finally {URL.revokeObjectURL(url);}
  }
  return {hash, preview};
}

export function sendBatch(form, onProgress, signal) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/uploads');
    xhr.responseType = 'json';
    xhr.timeout = 120000;
    xhr.upload.onprogress = event => {if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100));};
    xhr.onload = () => {
      if (xhr.status === 401) window.dispatchEvent(new Event('authentra-session-expired'));
      const body = xhr.response;
      if (xhr.status === 202 && body?.id) resolve(body);
      else reject(new Error(typeof body?.detail === 'string' ? body.detail : 'The upload was not accepted. Please try again.'));
    };
    xhr.onerror = () => reject(new Error('The connection was interrupted. Check recent batches before uploading again.'));
    xhr.ontimeout = () => reject(new Error('The upload timed out. Check recent batches before uploading again.'));
    xhr.onabort = () => reject(new Error('Upload interrupted. Check recent batches before uploading again.'));
    const abort = () => xhr.abort();
    signal?.addEventListener('abort', abort, {once: true});
    xhr.onloadend = () => signal?.removeEventListener('abort', abort);
    xhr.send(form);
  });
}
