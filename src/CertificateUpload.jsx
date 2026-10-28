import React, {useEffect, useRef, useState} from 'react';
import {UploadCloud, FileText, X, LoaderCircle, Download, ShieldCheck, AlertTriangle, RefreshCw, ArrowUpRight, CheckCircle2} from 'lucide-react';
import {FILE_TYPES, formatBytes, inspectFile, referenceError, selectionError, sendBatch} from './uploadValidation';
import {downloadBatchVerificationPdf, isUserRole} from './reportUtils';

const previewCache = new Map();

const stageLabels = {
  QUEUED: 'Queued',
  VALIDATING: 'Validating',
  OCR_PROCESSING: 'OCR Processing',
  AWAITING_REVIEW: 'Awaiting Review',
  PENDING_BLOCKCHAIN: 'Blockchain Registration Pending',
  REGISTERED_ON_BLOCKCHAIN: 'Registered on Blockchain',
  REGISTRATION_FAILED: 'Registration Failed',
  REGISTRATION_STATUS_UNCERTAIN: 'Registration Status Uncertain',
  VERIFIED: 'Verified',
  TAMPERING_DETECTED: 'Tampering Detected',
  POSSIBLE_TAMPERING_OR_FILE_MISMATCH: 'Possible Tampering or File Mismatch',
  NOT_REGISTERED: 'Not Registered',
  INCONCLUSIVE: 'Inconclusive',
  NOT_REGISTERED_OR_INCONCLUSIVE: 'Not Registered or Inconclusive',
  REVOKED: 'Revoked',
  ISSUER_NOT_AUTHORIZED: 'Issuer Not Authorized',
  VERIFICATION_UNAVAILABLE: 'Verification Unavailable',
  INVALID_FILE: 'Invalid File',
  pending: 'Queued',
  processing: 'Processing',
  awaiting_review: 'Awaiting Review',
  rejected: 'Rejected',
  failed: 'Failed',
  succeeded: 'Complete'
};

function getStageLabel(item, issuing) {
  if (issuing) {
    if (
      (item.status === 'REGISTERED_ON_BLOCKCHAIN' ||
       item.result?.registration_status === 'REGISTERED_ON_BLOCKCHAIN' ||
       item.result?.status === 'REGISTERED_ON_BLOCKCHAIN') &&
      item.result?.on_chain_verified !== false
    ) {
      return 'Registered on Blockchain';
    }
    if (item.status === 'REGISTRATION_STATUS_UNCERTAIN' || item.result?.status === 'REGISTRATION_STATUS_UNCERTAIN') {
      return 'Registration Status Uncertain';
    }
    if (item.status === 'REGISTRATION_FAILED' || item.state === 'failed' || item.state === 'rejected' || item.result?.status === 'REGISTRATION_FAILED') {
      return 'Registration Failed';
    }
    if (item.status === 'AWAITING_REVIEW' || item.state === 'awaiting_review') {
      return 'Awaiting Review';
    }
    if (item.status === 'PENDING_BLOCKCHAIN') {
      return 'Blockchain Registration Pending';
    }
    if (item.status === 'OCR_PROCESSING') {
      return 'OCR Processing';
    }
    if (item.status === 'VALIDATING') {
      return 'Validating';
    }
    if (item.status === 'QUEUED') {
      return 'Queued';
    }
    return stageLabels[item.status] || stageLabels[item.state] || 'Queued';
  }
  if (item.result?.label) return item.result.label;
  if (item.result?.category) return stageLabels[item.result.category] || item.result.category;
  if (item.state === 'rejected' || item.status === 'INVALID_FILE') return 'Invalid File';
  if (item.state === 'failed') return 'Verification Unavailable';
  return item.state === 'succeeded' ? item.result?.label || 'Verified' : stageLabels[item.state] || 'Processing';
}

function getBadgeStatus(item, issuing) {
  if (issuing) {
    if (
      (item.status === 'REGISTERED_ON_BLOCKCHAIN' ||
       item.result?.registration_status === 'REGISTERED_ON_BLOCKCHAIN') &&
      item.result?.on_chain_verified !== false
    ) {
      return 'verified';
    }
    if (item.status === 'REGISTRATION_STATUS_UNCERTAIN' || item.result?.status === 'REGISTRATION_STATUS_UNCERTAIN') return 'uncertain';
    if (item.status === 'REGISTRATION_FAILED' || item.state === 'failed' || item.state === 'rejected') return 'not_verified';
    if (item.status === 'AWAITING_REVIEW' || item.state === 'awaiting_review') return 'possible_tampering';
    return 'inconclusive';
  }
  const cat = item.result?.verification_status || item.result?.category;
  const stat = item.result?.status;
  if (cat === 'VERIFIED' || stat === 'verified') return 'verified';
  if (cat === 'TAMPERING_DETECTED' || cat === 'POSSIBLE_TAMPERING_OR_FILE_MISMATCH' || stat === 'possible_tampering') return 'possible_tampering';
  if (cat === 'REVOKED' || stat === 'revoked') return 'revoked';
  if (cat === 'ISSUER_NOT_AUTHORIZED' || stat === 'not_verified') return 'not_verified';
  if (cat === 'INVALID_FILE' || stat === 'invalid_file' || item.state === 'rejected') return 'not_verified';
  if (cat === 'VERIFICATION_UNAVAILABLE' || stat === 'unable_to_authenticate' || item.state === 'failed') return 'unable_to_authenticate';
  return 'inconclusive';
}

export default function CertificateUpload({mode = 'verify', api, Badge, Result, onChange, health, samples = [], user}) {
  const issuing = mode === 'register';
  const defaultLimits = {max_files: issuing ? 100 : 5, max_file_bytes: 10 * 1024 * 1024, max_batch_bytes: (issuing ? 100 : 5) * 10 * 1024 * 1024};
  const [limits, setLimits] = useState(defaultLimits), [items, setItems] = useState([]), [error, setError] = useState('');
  const [checking, setChecking] = useState(false), [sending, setSending] = useState(false), [progress, setProgress] = useState(0);
  const [drag, setDrag] = useState(false), [batch, setBatch] = useState(null), [recent, setRecent] = useState([]), [pollError, setPollError] = useState('');
  const [reviewing, setReviewing] = useState(false);
  const [downloadingBatch, setDownloadingBatch] = useState(false);
  const [batchDownloadError, setBatchDownloadError] = useState(null);
  const [previewSample, setPreviewSample] = useState(null);
  const input = useRef(), mounted = useRef(true), sendingRef = useRef(false), checkRef = useRef(false), request = useRef(), changed = useRef(onChange);
  changed.current = onChange;
  const active = batch && batch.state !== 'completed';
  const busy = checking || sending || active || reviewing;

  useEffect(() => {
    function onKeyDown(e) {
      if (e.key === 'Escape') setPreviewSample(null);
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {mounted.current = true; return () => {mounted.current = false; request.current?.abort();};}, []);
  useEffect(() => {
    let alive = true;
    api('/uploads/limits?mode=' + mode).then(v => {if (alive) setLimits(v);}).catch(e => {if (alive) setError(e.message);});
    api('/uploads?mode=' + mode).then(v => {if (alive) {setRecent(v); const pending = v.find(b => b.state !== 'completed'); if (pending) setBatch(pending);}}).catch(e => {if (alive) setError(e.message);});
    return () => {alive = false;};
  }, [mode, api]);

  useEffect(() => {
    if (!batch || batch.state === 'completed') return;
    let cancelled = false, timer;
    async function poll() {
      try {
        const next = await api('/uploads/' + batch.id);
        if (cancelled) return;
        setBatch(old => {
          const prevMap = new Map();
          (old?.items || []).forEach(it => {
            if (it.preview) prevMap.set(it.id || it.filename, it.preview);
          });
          return {
            ...next,
            items: (next.items || []).map((it, idx) => {
              const p = it.preview || prevMap.get(it.id || it.filename) || old?.items?.[idx]?.preview || previewCache.get(it.filename) || (it.result?.file_hash ? previewCache.get(it.result.file_hash) : null);
              if (p && it.filename) previewCache.set(it.filename, p);
              if (p && it.result?.file_hash) previewCache.set(it.result.file_hash, p);
              return { ...it, preview: p };
            })
          };
        });
        setPollError('');
        if (next.state === 'completed') {changed.current?.(); return;}
      } catch (e) {if (cancelled) return; setPollError(e.message + ' Status will retry automatically.');}
      timer = setTimeout(poll, 1200);
    }
    timer = setTimeout(poll, 600);
    return () => {cancelled = true; clearTimeout(timer);};
  }, [batch?.id, batch?.state, api]);

  const countError = limits ? selectionError(items, limits) : '';
  const duplicateHashes = new Set(), duplicateReferences = new Set();
  const rows = items.map(item => {
    const duplicate = item.hash && duplicateHashes.has(item.hash);
    if (item.hash) duplicateHashes.add(item.hash);
    const normalized = item.reference.trim().toUpperCase();
    const duplicateReference = issuing && normalized && duplicateReferences.has(normalized);
    duplicateReferences.add(normalized);
    const refError = (issuing || item.reference.trim()) ? referenceError(item.reference) : '';
    return {...item, validation: item.error || (duplicate ? 'Duplicate file. Remove this copy.' : '') || refError || (duplicateReference ? 'Use a different certificate ID for each file.' : '')};
  });
  const invalid = !limits || !rows.length || !!countError || rows.some(i => i.validation || i.checking);

  async function choose(files, preset = '') {
    if (!limits || busy || checkRef.current || sendingRef.current) return;
    const selected = Array.from(files);
    if (!selected.length) return;
    if (selected.length + items.length > limits.max_files) {
      if (limits.max_files === 5) {
        setError(`Ordinary users can upload at most 5 certificate files per batch (maximum of 5). You selected ${selected.length + items.length} files. Please select between 1 and 5 files to continue.`);
      } else {
        setError(`Institutions are limited to ${limits.max_files} files per batch. You selected ${selected.length + items.length} files. Remove extra files to continue.`);
      }
      return;
    }
    checkRef.current = true; setChecking(true); setError('');
    const added = selected.map(file => ({id: crypto.randomUUID(), file, reference: preset || (issuing ? file.name.replace(/\.[^.]+$/, '').toUpperCase() : ''), checking: true}));
    setItems(old => [...old, ...added]);
    for (const item of added) {
      if (!mounted.current) break;
      let update;
      try {
        update = await inspectFile(item.file, limits);
        if (update?.preview) {
          previewCache.set(item.file.name, update.preview);
          if (update.hash) previewCache.set(update.hash, update.preview);
        }
      } catch (e) {update = {error: e.message};}
      if (mounted.current) setItems(old => old.map(v => v.id === item.id ? {...v, ...update, checking: false} : v));
    }
    checkRef.current = false;
    if (mounted.current) setChecking(false);
  }

  async function submit(e) {
    e.preventDefault();
    if (invalid || busy || sendingRef.current) return;
    sendingRef.current = true; setSending(true); setProgress(0); setError(''); setPollError('');
    const form = new FormData();
    rows.forEach(item => form.append('files', item.file));
    form.append('references', JSON.stringify(rows.map(item => item.reference.trim()))); form.append('mode', mode);
    request.current = new AbortController();
    try {
      const result = await sendBatch(form, setProgress, request.current.signal);
      if (!mounted.current) return;
        // Preserve preview images from the original rows for post‑verification display
        if (Array.isArray(result.items) && rows.length) {
          result.items = result.items.map((it, i) => {
            const p = rows[i]?.preview || it.preview || previewCache.get(it.filename) || (it.result?.file_hash ? previewCache.get(it.result.file_hash) : null);
            if (p && it.filename) previewCache.set(it.filename, p);
            return {
              ...it,
              preview: p,
            };
          });
        }
        setBatch(result);
        setItems([]);
        setRecent(old => [result, ...old].slice(0, 10));
        if (result.state === 'completed') changed.current?.();
      if (result.state === 'completed') changed.current?.();
    } catch (e) {if (mounted.current) setError(e.message);}
    finally {sendingRef.current = false; if (mounted.current) setSending(false);}
  }

  async function submitReview(itemId, action) {
    if (!batch) return;
    setReviewing(true); setError('');
    try {
      const ref = document.getElementById('review-ref-' + itemId)?.value?.trim() || '';
      const name = document.getElementById('review-name-' + itemId)?.value?.trim() || '';
      const course = document.getElementById('review-course-' + itemId)?.value?.trim() || '';
      const date = document.getElementById('review-date-' + itemId)?.value?.trim() || '';
      const grade = document.getElementById('review-grade-' + itemId)?.value?.trim() || '';
      const payload = {action, reference: ref, name, course, issue_date: date, grade};
      const updated = await api(`/uploads/${batch.id}/items/${itemId}/review`, {
        method: 'POST',
        body: JSON.stringify(payload)
      });
      if (mounted.current) {
        setBatch(updated);
        if (updated.state === 'completed') changed.current?.();
      }
    } catch (e) {
      if (mounted.current) setError(e.message);
    } finally {
      if (mounted.current) setReviewing(false);
    }
  }

  async function retryItem(itemId) {
    if (!batch) return;
    setReviewing(true); setError('');
    try {
      const updated = await api(`/uploads/${batch.id}/items/${itemId}/retry`, {
        method: 'POST'
      });
      if (mounted.current) {
        setBatch(updated);
        if (updated.state === 'completed') changed.current?.();
      }
    } catch (e) {
      if (mounted.current) setError(e.message);
    } finally {
      if (mounted.current) setReviewing(false);
    }
  }

  async function loadRecent() {
    try {setRecent(await api('/uploads?mode=' + mode)); setError('');} catch (e) {setError(e.message);}
  }

  async function sample(s) {
    try {
      const response = await fetch('/api/samples/' + s.name);
      if (!response.ok) throw new Error('Sample is unavailable.');
      await choose([new File([await response.blob()], s.name, {type: FILE_TYPES[s.name.split('.').pop()]})], s.ref);
    } catch (e) {setError(e.message);}
  }

  return <section className="panel certificate-upload">
    <div className="panel-title"><div className="square-icon small">{issuing ? <UploadCloud size={22}/> : <ShieldCheck size={22}/>}</div><div><h3>{issuing ? 'Register original certificates' : 'Upload certificates for verification'}</h3><p>{issuing ? 'Approved institution · Real blockchain registration' : 'Your private verification workspace · Up to 5 files'}</p></div></div>
    <form onSubmit={submit} className="certificate-upload-form">
      <p className="upload-explainer">{issuing ? 'Each uploaded certificate is validated, hashed from original bytes, analyzed with text extraction/OCR, and registered on the blockchain. Successful registration is confirmed only after independent on-chain verification.' : 'Uploading begins verification. It does not itself prove authenticity. Each file is checked against trusted registration records.'}</p>
      <div className={'dropzone ' + (drag ? 'dragging' : '')} onDragOver={e => {e.preventDefault(); if (!busy) setDrag(true);}} onDragLeave={() => setDrag(false)} onDrop={e => {e.preventDefault(); setDrag(false); choose(e.dataTransfer.files);}}>
        <div className="upload-icon"><UploadCloud size={30}/></div><strong>{issuing ? 'Drop your certificate batch here' : 'Drop up to 5 certificates here'}</strong><span>PDF, PNG and JPG/JPEG</span>
        <input ref={input} type="file" hidden multiple accept=".pdf,.png,.jpg,.jpeg" aria-label="Choose certificate files" disabled={busy || !limits} onChange={e => {choose(e.target.files); e.target.value = '';}}/>
        <button type="button" className="secondary" disabled={busy || !limits} onClick={() => input.current.click()}>Browse Files</button>
        <small>{limits ? `${limits.max_files} files maximum · ${formatBytes(limits.max_file_bytes)} per file · ${formatBytes(limits.max_batch_bytes)} per batch` : 'Loading upload limits…'}<br/>PDFs: up to 5 pages · Images: up to 20 megapixels</small>
      </div>
      {health?.demo && samples.length > 0 && (
        <div className="sample-area">
          <div>
            <span>Try a sample certificate</span>
            <small>LOCAL DEMO</small>
          </div>
          <div className="sample-list" role="region" aria-label="Sample demonstration certificates">
            {samples.map(s => {
              const isSelected = previewSample?.name === s.name;
              return (
                <div key={s.name} className="sample-chip-group">
                  <button
                    type="button"
                    className={'sample-btn ' + (isSelected ? 'is-previewing' : '')}
                    disabled={busy || !limits}
                    onClick={() => sample(s)}
                    onMouseEnter={() => setPreviewSample(s)}
                    onMouseLeave={() => setPreviewSample(prev => prev?.name === s.name ? null : prev)}
                    onFocus={() => setPreviewSample(s)}
                    onBlur={() => setPreviewSample(prev => prev?.name === s.name ? null : prev)}
                    aria-describedby={isSelected ? 'sample-preview-panel' : undefined}
                  >
                    {s.label}
                  </button>
                  <button
                    type="button"
                    className={'sample-preview-trigger ' + (isSelected ? 'active' : '')}
                    aria-label={`Preview ${s.label} sample details`}
                    title={`Preview ${s.label} details`}
                    aria-expanded={isSelected}
                    onClick={() => setPreviewSample(prev => prev?.name === s.name ? null : s)}
                  >
                    <FileText size={12} aria-hidden="true" />
                  </button>
                </div>
              );
            })}
          </div>
          {previewSample && (
            <div
              id="sample-preview-panel"
              className="sample-preview-card"
              role="region"
              aria-label="Sample preview"
            >
              <div className="sample-preview-archival-frame">
                <div className="sample-preview-header">
                  <div className="sample-preview-tag">
                    <span className="sample-preview-seal" aria-hidden="true">★</span>
                    <span>Sample preview</span>
                  </div>
                  <button
                    type="button"
                    className="sample-preview-close"
                    aria-label="Close sample preview"
                    onClick={() => setPreviewSample(null)}
                  >
                    <X size={14} />
                  </button>
                </div>
                <div className="sample-preview-body">
                  <div className="sample-preview-watermark" aria-hidden="true">ARCHIVAL DEMO</div>
                  <div className="sample-preview-title-row">
                    <span className="sample-preview-eyebrow">DEMONSTRATION RECORD</span>
                    <h4 className="sample-preview-title">{previewSample.label}</h4>
                  </div>
                  <div className="sample-preview-meta-grid">
                    <div className="sample-preview-field">
                      <span className="sample-preview-label">Certificate ID</span>
                      <strong className="sample-preview-value sample-preview-ref">{previewSample.ref}</strong>
                    </div>
                    <div className="sample-preview-field">
                      <span className="sample-preview-label">Filename</span>
                      <code className="sample-preview-value sample-preview-filename">{previewSample.name}</code>
                    </div>
                  </div>
                  <div className="sample-preview-footer">
                    <p className="sample-preview-note">Activating this sample loads its local demo file.</p>
                    <button
                      type="button"
                      className="sample-preview-load-btn"
                      disabled={busy || !limits}
                      onClick={() => sample(previewSample)}
                    >
                      Load {previewSample.label} demo file <ArrowUpRight size={14} />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
      {rows.length ? <ul className="upload-file-list" aria-label="Selected certificates">{rows.map(item => <li key={item.id} className={'upload-file-card ' + (item.validation ? 'invalid' : '')}>
        <div className="upload-file-top">{item.preview ? <img className="certificate-preview" src={item.preview} alt={'First page preview of ' + item.file.name}/> : <div className="certificate-preview placeholder"><FileText size={24}/></div>}
          <div className="upload-file-info"><strong>{item.file.name}</strong><span>{item.file.name.split('.').pop().toUpperCase()} · {formatBytes(item.file.size)}</span><span className={'upload-file-state ' + (item.validation ? 'bad' : '')}>{item.checking ? <><LoaderCircle size={14} className="spin"/>Checking readability…</> : item.validation ? 'Needs attention' : 'Ready to upload'}</span></div>
          <button type="button" className="secondary remove-file" disabled={sending || active} aria-label={'Remove ' + item.file.name} onClick={() => setItems(old => old.filter(v => v.id !== item.id))}><X size={18}/></button>
        </div>
        <label htmlFor={'ref-' + item.id}>Certificate ID {issuing ? '(required)' : '(optional)'}<input id={'ref-' + item.id} value={item.reference} maxLength={64} disabled={busy} aria-invalid={!!item.validation} aria-describedby={item.validation ? 'error-' + item.id : undefined} onChange={e => setItems(old => old.map(v => v.id === item.id ? {...v, reference: e.target.value} : v))} placeholder="e.g. AT-2026-0001"/></label>
        {item.validation && <p className="upload-file-error" id={'error-' + item.id}><AlertTriangle size={15}/>{item.validation}</p>}
      </li>)}</ul> : <p className="upload-empty">No files selected. Add original digital certificates to get started.</p>}
      {(error || countError) && <div className="error" role="alert"><AlertTriangle size={18}/>{error || countError}</div>}
      {sending && <div className="upload-progress" role="status"><span>{progress < 100 ? `Uploading files · ${progress}%` : 'Upload transferred · Server is validating files…'}</span><progress aria-label="Upload transfer progress" value={progress} max={100}/></div>}
      <div className="upload-actions"><span>{rows.length} selected{checking ? ' · Checking files…' : ''}</span><button className="primary" disabled={invalid || busy}>{sending || active ? <LoaderCircle size={18} className="spin"/> : <UploadCloud size={18}/>} {sending ? 'Uploading…' : active ? 'Batch processing…' : issuing ? 'Register certificates' : 'Begin verification'}</button></div>
      <p className="upload-footnote">Note: SHA-256 is computed directly from original file bytes before any processing. Re-exporting or rescanning a certificate can change its file hash even when visible contents look identical. Full certificate files and personal information are stored off-chain only.</p>
    </form>
    {batch && <div className="upload-batch-results">
      <div className="upload-results-title">
        <div>
          <h3>{batch.state === 'completed' ? 'Batch complete' : 'Processing your batch'}</h3>
          <small>Batch {batch.id.slice(0, 12)}</small>
        </div>
        <div style={{display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap'}}>
          {batch.state === 'completed' && (
            <button type="button" className="secondary" onClick={() => { setBatch(null); setItems([]); setError(''); setBatchDownloadError(null); }}>
              {issuing ? 'Register another batch' : 'Verify another batch'}
            </button>
          )}
          {!issuing && isUserRole(user) && (() => {
            const batchVerificationIds = (batch.items || [])
              .map(i => i.result?.id)
              .filter(Boolean);
            if (batchVerificationIds.length > 1) {
              return (
                <button
                  type="button"
                  className="primary small-button"
                  disabled={downloadingBatch}
                  onClick={() => downloadBatchVerificationPdf(batchVerificationIds, setDownloadingBatch, setBatchDownloadError)}
                  title="Download consolidated PDF verification report for this batch"
                >
                  <FileText size={16}/>{downloadingBatch ? 'Downloading…' : 'Download batch report'}
                </button>
              );
            }
            return null;
          })()}
          <a className="secondary" href={'/api/uploads/' + batch.id + '/report'} download><Download size={16}/>CSV report</a>
        </div>
      </div>
      {batchDownloadError && <div className="error" role="alert" style={{margin: '8px 0'}}>{batchDownloadError}</div>}
      {pollError && <div className="error" role="alert">{pollError}</div>}
      {issuing && batch.summary && (
        <div className="upload-summary" aria-live="polite">
          <div><strong>{batch.summary.total}</strong><span>Total files</span></div>
          {(batch.summary.registered ?? batch.summary.successful) > 0 && <div><strong>{batch.summary.registered ?? batch.summary.successful}</strong><span>Registered</span></div>}
          {batch.summary.failed > 0 && <div><strong>{batch.summary.failed}</strong><span>Failures</span></div>}
          {(batch.summary.uncertain ?? 0) > 0 && <div><strong>{batch.summary.uncertain ?? 0}</strong><span>Status Uncertain</span></div>}
          {(batch.summary.awaiting_review ?? 0) > 0 && <div><strong>{batch.summary.awaiting_review ?? 0}</strong><span>Awaiting Review</span></div>}
          {batch.summary.pending > 0 && <div><strong>{batch.summary.pending}</strong><span>In Queue / Processing</span></div>}
        </div>
      )}
      {!issuing && batch.summary && <div className="upload-summary" aria-live="polite">{[['total','Total files'],['valid','Valid files'],['rejected','Rejected'],['pending','Pending'],['successful','Checks completed'],['failed','Failures']].map(([key, label]) => <div key={key}><strong>{batch.summary[key]}</strong><span>{label}</span></div>)}</div>}
      {!issuing && (batch.items || []).length > 1 && (() => {
        const catCounts = {
          verified: (batch.items || []).filter(i => (i.result?.verification_status === 'VERIFIED' || i.result?.category === 'VERIFIED' || i.result?.status === 'verified')).length,
          mismatched: (batch.items || []).filter(i => (['POSSIBLE_TAMPERING_OR_FILE_MISMATCH', 'TAMPERING_DETECTED'].includes(i.result?.verification_status) || ['POSSIBLE_TAMPERING_OR_FILE_MISMATCH', 'TAMPERING_DETECTED'].includes(i.result?.category) || i.result?.status === 'possible_tampering')).length,
          unregistered: (batch.items || []).filter(i => (['NOT_REGISTERED_OR_INCONCLUSIVE', 'NOT_REGISTERED', 'INCONCLUSIVE'].includes(i.result?.verification_status) || ['NOT_REGISTERED_OR_INCONCLUSIVE', 'NOT_REGISTERED', 'INCONCLUSIVE'].includes(i.result?.category) || ['not_registered', 'inconclusive'].includes(i.result?.status))).length,
          revoked: (batch.items || []).filter(i => (i.result?.verification_status === 'REVOKED' || i.result?.category === 'REVOKED' || i.result?.status === 'revoked')).length,
          issuer_not_authorized: (batch.items || []).filter(i => (i.result?.verification_status === 'ISSUER_NOT_AUTHORIZED' || i.result?.category === 'ISSUER_NOT_AUTHORIZED' || i.result?.status === 'not_verified')).length,
          invalid: (batch.items || []).filter(i => (i.result?.verification_status === 'INVALID_FILE' || i.result?.category === 'INVALID_FILE' || i.state === 'rejected' || i.result?.status === 'invalid_file')).length,
          unavailable: (batch.items || []).filter(i => (i.result?.verification_status === 'VERIFICATION_UNAVAILABLE' || i.result?.category === 'VERIFICATION_UNAVAILABLE' || i.result?.status === 'unable_to_authenticate')).length,
        };
        return (
          <div className="verification-category-summary" style={{display: 'flex', flexWrap: 'wrap', gap: '8px', margin: '12px 0 6px'}} aria-label="Verification category breakdown">
            <span className="badge verified" style={{fontSize: '11px', padding: '4px 9px'}}><strong>{catCounts.verified}</strong> Verified</span>
            <span className="badge possible_tampering" style={{fontSize: '11px', padding: '4px 9px'}}><strong>{catCounts.mismatched}</strong> Potentially Mismatched</span>
            <span className="badge inconclusive" style={{fontSize: '11px', padding: '4px 9px'}}><strong>{catCounts.unregistered}</strong> Unregistered / Inconclusive</span>
            <span className="badge revoked" style={{fontSize: '11px', padding: '4px 9px'}}><strong>{catCounts.revoked}</strong> Revoked</span>
            {catCounts.issuer_not_authorized > 0 && <span className="badge not_verified" style={{fontSize: '11px', padding: '4px 9px'}}><strong>{catCounts.issuer_not_authorized}</strong> Unauthorized Issuer</span>}
            {catCounts.invalid > 0 && <span className="badge not_verified" style={{fontSize: '11px', padding: '4px 9px'}}><strong>{catCounts.invalid}</strong> Invalid</span>}
            {catCounts.unavailable > 0 && <span className="badge unable_to_authenticate" style={{fontSize: '11px', padding: '4px 9px'}}><strong>{catCounts.unavailable}</strong> Unavailable</span>}
          </div>
        );
      })()}
      {batch.summary && <div className="upload-progress"><label htmlFor={'batch-progress-' + mode}>{batch.summary.total - batch.summary.pending} of {batch.summary.total} files processed</label><progress id={'batch-progress-' + mode} value={batch.summary.total - batch.summary.pending} max={batch.summary.total}/></div>}
      {!issuing && <p className="upload-footnote">Completed checks can have any verification outcome. Read each result below.</p>}
      <div className="file-outcomes">{(batch.items || []).map(item => {
        const label = getStageLabel(item, issuing);
        const badgeStatus = getBadgeStatus(item, issuing);
        const isReview = issuing && (item.status === 'AWAITING_REVIEW' || item.state === 'awaiting_review');
        return <article key={item.id} className="file-outcome">
          <div className="file-outcome-heading">
            <FileText size={19}/>
            <div>
              <h4>{item.filename}</h4>
              <small>{item.reference || item.result?.reference || 'ID from document'}</small>
            </div>
            <Badge status={badgeStatus}>{label}</Badge>
          </div>
          {item.result?.error && <p className="upload-file-error"><AlertTriangle size={16}/>{item.result.error}</p>}
          {issuing && item.result?.transaction_hash && (
            <div className="upload-transaction">
              <p>Confirmed on-chain transaction <code>{item.result.transaction_hash}</code></p>
              {item.result?.block_number && <small className="block-number">Block #{item.result.block_number}</small>}
              {item.result?.explorer_url && (
                <a href={item.result.explorer_url} target="_blank" rel="noopener noreferrer" className="explorer-link">
                  View on Block Explorer <ArrowUpRight size={14}/>
                </a>
              )}
            </div>
          )}
          {issuing && item.result?.fields && (
            <div className="extracted-metadata-preview" style={{marginTop: '10px', padding: '10px 12px', border: '1px solid var(--border,#e2e8f0)', borderRadius: '6px', background: '#f8fafc'}}>
              <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px', flexWrap: 'wrap', gap: '6px'}}>
                <span style={{fontSize: '11px', fontWeight: 700, textTransform: 'uppercase', color: '#475569'}}>
                  Issuer Reference Metadata <small style={{color: '#94a3b8'}}>(Schema v2026.1)</small>
                </span>
                {item.result?.metadata_commitment && (
                  <span className="reference-pill mono" style={{fontSize: '9px', background: '#dcfce7', color: '#15803d', padding: '2px 6px', borderRadius: '4px'}}>
                    Cryptographic Commitment Bound
                  </span>
                )}
              </div>
              <div className="extracted-fields-grid">
                {item.result.fields.name && <div><small>Recipient</small><strong>{item.result.fields.name}</strong></div>}
                {item.result.fields.course && <div><small>Course/Qualification</small><strong>{item.result.fields.course}</strong></div>}
                {item.result.fields.institution && <div><small>Institution</small><strong>{item.result.fields.institution}</strong></div>}
                {item.result.fields.issue_date && <div><small>Issue Date</small><strong>{item.result.fields.issue_date}</strong></div>}
                {item.result.fields.grade && <div><small>Grade / Result</small><strong>{item.result.fields.grade}</strong></div>}
              </div>
              {item.result?.metadata_commitment && (
                <div style={{marginTop: '6px', fontSize: '10px', color: '#64748b'}}>
                  Commitment Digest: <code className="mono" style={{fontSize: '10px'}}>{item.result.metadata_commitment}</code>
                  <p style={{margin: '2px 0 0', color: '#94a3b8', fontSize: '9px'}}>Personal metadata remains off-chain; cryptographic commitment proof is stored with the registration.</p>
                </div>
              )}
              {item.result.ocr_confidence != null && (
                <small className="ocr-meta" style={{display: 'block', marginTop: '4px'}}>OCR Confidence: {Math.round(item.result.ocr_confidence)}% ({item.result.extraction_method || 'OCR'})</small>
              )}
            </div>
          )}
          {isReview && (
            <div className="review-card" style={{marginTop: '1rem', padding: '1rem', border: '1px solid var(--border, #e2e8f0)', borderRadius: '8px', background: 'var(--panel-alt, #f8fafc)'}}>
              <div style={{display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px', color: '#b45309'}}>
                <AlertTriangle size={18}/>
                <strong>Human review required before blockchain registration</strong>
              </div>
              <p style={{fontSize: '0.9rem', marginBottom: '12px'}}>{item.result?.message || 'Critical metadata requires verification before writing to the blockchain.'}</p>
              <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '10px', marginBottom: '12px'}}>
                <label style={{fontSize: '0.85rem'}}>Certificate Reference / ID
                  <input style={{width: '100%', padding: '6px 8px', marginTop: '4px'}} defaultValue={item.reference || item.result?.fields?.reference || ''} id={'review-ref-' + item.id} placeholder="e.g. AT-2026-0001"/>
                </label>
                <label style={{fontSize: '0.85rem'}}>Recipient Name
                  <input style={{width: '100%', padding: '6px 8px', marginTop: '4px'}} defaultValue={item.result?.fields?.name || ''} id={'review-name-' + item.id} placeholder="Student name"/>
                </label>
                <label style={{fontSize: '0.85rem'}}>Course / Qualification
                  <input style={{width: '100%', padding: '6px 8px', marginTop: '4px'}} defaultValue={item.result?.fields?.course || ''} id={'review-course-' + item.id} placeholder="Course"/>
                </label>
                <label style={{fontSize: '0.85rem'}}>Issue Date
                  <input style={{width: '100%', padding: '6px 8px', marginTop: '4px'}} type="date" defaultValue={item.result?.fields?.issue_date || ''} id={'review-date-' + item.id}/>
                </label>
                <label style={{fontSize: '0.85rem'}}>Grade / Result
                  <input style={{width: '100%', padding: '6px 8px', marginTop: '4px'}} defaultValue={item.result?.fields?.grade || ''} id={'review-grade-' + item.id} placeholder="e.g. First Class Honours / Distinction"/>
                </label>
              </div>
              <div style={{display: 'flex', gap: '8px'}}>
                <button type="button" className="primary" disabled={busy} onClick={() => submitReview(item.id, 'approve')}>
                  Confirm and Register on Blockchain
                </button>
                <button type="button" className="secondary" disabled={busy} onClick={() => submitReview(item.id, 'reject')}>
                  Reject
                </button>
              </div>
            </div>
          )}
          {issuing && (item.status === 'REGISTRATION_STATUS_UNCERTAIN' || item.result?.status === 'REGISTRATION_STATUS_UNCERTAIN') && (
            <div className="uncertain-card" style={{marginTop: '10px', padding: '10px 12px', border: '1px solid #fde68a', borderRadius: '6px', background: '#fefce8'}}>
              <div style={{display: 'flex', alignItems: 'center', gap: '8px', color: '#92400e', marginBottom: '6px', fontSize: '11px', fontWeight: '600'}}>
                <AlertTriangle size={15}/>
                <span>Registration Status Uncertain</span>
              </div>
              <p style={{fontSize: '11px', color: '#78350f', margin: '0 0 8px', lineHeight: '1.5'}}>
                {item.result?.error || 'Confirmation timed out while awaiting blockchain receipt. The transaction may have mined or may still be pending.'}
              </p>
              {item.result?.transaction_hash && (
                <p style={{fontSize: '10px', color: '#78350f', margin: '0 0 8px'}}>
                  Transaction Hash: <code style={{fontSize: '10px'}}>{item.result.transaction_hash}</code>
                </p>
              )}
              <button type="button" className="secondary" style={{fontSize: '10px', minHeight: '30px', padding: '4px 10px'}} disabled={busy} onClick={() => retryItem(item.id)}>
                <RefreshCw size={12}/> Verify On-Chain Record / Retry
              </button>
            </div>
          )}
          {!issuing && item.result && (
            <Result
              result={item.result}
              autoScroll={false}
              user={user}
              preview={item.preview || previewCache.get(item.filename) || (item.result?.file_hash ? previewCache.get(item.result.file_hash) : null)}
              file={item.file}
            />
          )}
          {['pending','processing'].includes(item.state) && (
            <p className="upload-footnote">
              {item.status === 'OCR_PROCESSING' ? 'Processing OCR and analyzing document contents…' :
               item.status === 'PENDING_BLOCKCHAIN' ? 'Submitting to blockchain and waiting for confirmed receipt…' :
               item.status === 'VALIDATING' ? 'Validating file format and byte integrity…' :
               item.state === 'pending' ? 'Waiting in queue.' :
               issuing ? 'Processing certificate registration…' : 'Analyzing document…'}
            </p>
          )}
        </article>;
      })}</div>
    </div>}
    <details className="upload-recent"><summary>Recent upload batches</summary><button type="button" className="text-button" onClick={loadRecent}><RefreshCw size={14}/>Refresh batches</button>{recent.length ? recent.map(b => <button key={b.id} type="button" className="recent-batch" disabled={sending || checking || !!active} onClick={async () => {try {setBatch(await api('/uploads/' + b.id));} catch (e) {setError(e.message);}}}>{b.id.slice(0,12)} · {b.summary.total} files · View outcomes</button>) : <p className="upload-footnote">Your submitted batches will appear here.</p>}</details>
  </section>;
}
