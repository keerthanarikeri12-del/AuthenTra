"""Central upload policy and durable, serial batch processing."""
import csv
import logging
from contextlib import contextmanager
import hashlib
import io
import json
import os
import threading
import uuid
from pathlib import Path
from fastapi import HTTPException
from .documents import MAX_BYTES, analyze, validate_document
from .storage import ROOT, connect, ROLE_INSTITUTION_ADMIN, ROLE_SYSTEM_ADMIN, canonical_role
from .registry import Registry, UncertainTransactionError

USER_FILES = 5
BULK_FILES = int(os.getenv('AUTHENTRA_BULK_FILES', '100'))
if BULK_FILES == USER_FILES:
    BULK_FILES = 100  # Protect institutional capacity; never collapse to ordinary user 5-file limit
BULK_BYTES = int(os.getenv('AUTHENTRA_BULK_BYTES', str(100 * 1024 * 1024)))
MAX_ACTIVE = int(os.getenv('AUTHENTRA_UPLOAD_JOBS', '4'))
if not 1 <= BULK_FILES <= 1000 or not MAX_BYTES <= BULK_BYTES <= 1024**3 or not 1 <= MAX_ACTIVE <= 20:
    raise RuntimeError('Invalid upload limits')
MIME = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}

def validate_file(data, filename, content_type):
    suffix = Path(filename or '').suffix.lower()
    if suffix not in MIME:
        raise ValueError('Choose a PDF, PNG or JPG/JPEG file. ZIP archives are not supported.')
    if content_type not in (None, '', 'application/octet-stream', MIME[suffix]):
        raise ValueError('The declared file type does not match its extension.')
    kind = validate_document(data)
    actual = '.pdf' if kind == 'pdf' else '.png' if data.startswith(b'\x89PNG') else '.jpg'
    if MIME[actual] != MIME[suffix]:
        raise ValueError('The file contents do not match its extension.')
    return kind

def initialize_jobs():
    with connect() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS upload_jobs (
          id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), mode TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS upload_items (
          id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES upload_jobs(id), filename TEXT NOT NULL,
          reference TEXT NOT NULL, kind TEXT, state TEXT NOT NULL, data BLOB, result TEXT);
        CREATE INDEX IF NOT EXISTS upload_items_job ON upload_items(job_id);
        CREATE INDEX IF NOT EXISTS upload_items_state ON upload_items(state,id);
        CREATE INDEX IF NOT EXISTS upload_jobs_owner ON upload_jobs(user_id,mode,created_at);
        CREATE INDEX IF NOT EXISTS upload_jobs_state ON upload_jobs(state);
        ''')
        # Additive column migration
        item_cols = {row["name"] for row in conn.execute("PRAGMA table_info(upload_items)")}
        if "status" not in item_cols:
            conn.execute("ALTER TABLE upload_items ADD COLUMN status TEXT DEFAULT 'QUEUED'")
        if "ocr_confidence" not in item_cols:
            conn.execute("ALTER TABLE upload_items ADD COLUMN ocr_confidence REAL")
        if "metadata" not in item_cols:
            conn.execute("ALTER TABLE upload_items ADD COLUMN metadata TEXT")
        if "field_analysis" not in item_cols:
            conn.execute("ALTER TABLE upload_items ADD COLUMN field_analysis TEXT")
        if "visual_tampering" not in item_cols:
            conn.execute("ALTER TABLE upload_items ADD COLUMN visual_tampering TEXT")
        if "transformation_analysis" not in item_cols:
            conn.execute("ALTER TABLE upload_items ADD COLUMN transformation_analysis TEXT")
        if "review_routing" not in item_cols:
            conn.execute("ALTER TABLE upload_items ADD COLUMN review_routing TEXT")

        # A chain transaction may have committed before interruption. Never replay it automatically.
        conn.execute("UPDATE upload_items SET state='failed', status='REGISTRATION_STATUS_UNCERTAIN', data=NULL, result=? WHERE state='processing' AND (status='PENDING_BLOCKCHAIN' OR job_id IN (SELECT id FROM upload_jobs WHERE mode='register'))", (json.dumps({'error': 'Processing was interrupted. Check the registry before retrying.', 'status': 'REGISTRATION_STATUS_UNCERTAIN'}),))
        conn.execute("UPDATE upload_items SET state='failed', status='REGISTRATION_FAILED', data=NULL, result=? WHERE state='processing'", (json.dumps({'error': 'Processing was interrupted. Check the registry before retrying.'}),))
        conn.execute("UPDATE upload_jobs SET state='completed' WHERE NOT EXISTS(SELECT 1 FROM upload_items WHERE job_id=upload_jobs.id AND state IN ('pending','processing','awaiting_review'))")

def create_job(user, mode, items):
    job = uuid.uuid4().hex
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        active = conn.execute("SELECT COUNT(*) FROM upload_jobs WHERE state IN ('pending','processing','awaiting_review')").fetchone()[0]
        if active >= MAX_ACTIVE:
            raise HTTPException(429, 'The upload queue is full. Please retry after a batch finishes.')
        conn.execute('INSERT INTO upload_jobs(id,user_id,mode) VALUES(?,?,?)', (job, user['id'], mode))
        seen, seen_refs = set(), set()
        for filename, reference, data, kind, error in items:
            digest = hashlib.sha256(data).hexdigest() if data else None
            if not error and mode == 'register' and reference in seen_refs:
                error = 'Duplicate certificate ID in this batch.'
            if not error and digest in seen:
                error = 'Duplicate file in this batch. Remove the repeated copy.'
            if not error:
                seen.add(digest)
                seen_refs.add(reference)
            state = 'rejected' if error else 'pending'
            if error:
                if mode == 'register':
                    status = 'REGISTRATION_FAILED'
                    err_res = {'error': error, 'status': 'REGISTRATION_FAILED'}
                else:
                    status = 'INVALID_FILE'
                    err_res = {
                        'error': error,
                        'status': 'invalid_file',
                        'category': 'INVALID_FILE',
                        'label': 'Invalid File',
                        'message': error,
                        'next_action': 'Ensure the file is an unencrypted, valid PDF, PNG, or JPEG under the maximum size limit and try again.',
                        'checks': {'reference_found': False, 'hash_matches': None, 'issuer_approved': None, 'active': None},
                        'file_hash': None,
                        'registered_hash': None,
                        'hash_matches': None,
                        'hash_comparison': 'Cannot hash invalid file',
                        'issuer': None,
                        'issuer_name': None,
                        'issuer_authorized': None,
                        'blockchain_record_status': 'NOT_CHECKED',
                        'fields': {},
                        'ai': {'status': 'unavailable', 'label': 'AI analysis unavailable', 'score': None},
                    }
            else:
                status = 'QUEUED'
                err_res = None
            conn.execute('INSERT INTO upload_items(job_id,filename,reference,kind,state,status,data,result) VALUES(?,?,?,?,?,?,?,?)',
                         (job, filename, reference, kind, state, status, None if error else data, json.dumps(err_res) if err_res else None))
        conn.execute("UPDATE upload_jobs SET state='completed' WHERE id=? AND NOT EXISTS(SELECT 1 FROM upload_items WHERE job_id=? AND state='pending')", (job, job))
    return job

def snapshot(job, user):
    with connect() as conn:
        row = conn.execute('SELECT * FROM upload_jobs WHERE id=? AND user_id=?', (job, user['id'])).fetchone()
        if not row:
            raise HTTPException(404, 'Upload batch not found.')
        items = [dict(r) for r in conn.execute('SELECT id,filename,reference,kind,state,status,ocr_confidence,result,field_analysis,visual_tampering,transformation_analysis,review_routing FROM upload_items WHERE job_id=? ORDER BY id', (job,))]
    for item in items:
        item['result'] = json.loads(item['result']) if item['result'] else None
        item['field_analysis'] = json.loads(item['field_analysis']) if item.get('field_analysis') else (item['result'].get('field_analysis') if item.get('result') else None)
        item['visual_tampering'] = json.loads(item['visual_tampering']) if item.get('visual_tampering') else (item['result'].get('visual_tampering') if item.get('result') else None)
        item['transformation_analysis'] = json.loads(item['transformation_analysis']) if item.get('transformation_analysis') else (item['result'].get('transformation_analysis') if item.get('result') else None)
        item['review_routing'] = json.loads(item['review_routing']) if item.get('review_routing') else (item['result'].get('review_routing') if item.get('result') else None)
        if not item.get('status'):
            if item['state'] == 'succeeded':
                item['status'] = 'REGISTERED_ON_BLOCKCHAIN' if row['mode'] == 'register' else 'VERIFIED'
            elif item['state'] in ('failed', 'rejected'):
                item['status'] = 'REGISTRATION_FAILED'
            elif item['state'] == 'awaiting_review':
                item['status'] = 'AWAITING_REVIEW'
            elif item['state'] == 'processing':
                item['status'] = 'OCR_PROCESSING'
            else:
                item['status'] = 'QUEUED'

    counts = {s: sum(i['state'] == s for i in items) for s in ['pending', 'processing', 'rejected', 'succeeded', 'failed', 'awaiting_review']}
    pending = counts['pending'] + counts['processing'] + counts['awaiting_review']
    reg_counts = {
        'registered': sum(1 for i in items if i.get('status') == 'REGISTERED_ON_BLOCKCHAIN'),
        'uncertain': sum(1 for i in items if i.get('status') == 'REGISTRATION_STATUS_UNCERTAIN'),
        'awaiting_review': sum(1 for i in items if i.get('status') == 'AWAITING_REVIEW'),
        'failed': sum(1 for i in items if i.get('status') == 'REGISTRATION_FAILED' or (i['state'] in ('rejected', 'failed') and i.get('status') != 'REGISTRATION_STATUS_UNCERTAIN')),
    }
    res = {'id': job, 'mode': row['mode'], 'state': 'processing' if pending else 'completed', 'items': items,
           'summary': {'total': len(items), 'valid': len(items) - counts['rejected'], 'rejected': counts['rejected'],
                       'pending': pending, 'successful': counts['succeeded'], 'failed': counts['failed'] + counts['rejected']}}
    if row['mode'] == 'register':
        res['registration_summary'] = reg_counts
    if row['mode'] == 'verify':
        res['verification_summary'] = {
            'verified': sum(1 for i in items if (i.get('result') and (i['result'].get('verification_status') == 'VERIFIED' or i['result'].get('category') == 'VERIFIED' or i['result'].get('status') == 'verified'))),
            'mismatched': sum(1 for i in items if (i.get('result') and (i['result'].get('verification_status') == 'TAMPERING_DETECTED' or i['result'].get('category') in ('POSSIBLE_TAMPERING_OR_FILE_MISMATCH', 'TAMPERING_DETECTED') or i['result'].get('status') in ('possible_tampering', 'TAMPERING_DETECTED')))),
            'unregistered': sum(1 for i in items if (i.get('result') and (i['result'].get('verification_status') in ('NOT_REGISTERED', 'INCONCLUSIVE') or i['result'].get('category') in ('NOT_REGISTERED_OR_INCONCLUSIVE', 'NOT_REGISTERED', 'INCONCLUSIVE') or i['result'].get('status') in ('not_registered', 'inconclusive', 'NOT_REGISTERED', 'INCONCLUSIVE')))),
            'revoked': sum(1 for i in items if (i.get('result') and (i['result'].get('verification_status') == 'REVOKED' or i['result'].get('category') == 'REVOKED' or i['result'].get('status') in ('revoked', 'REVOKED')))),
            'issuer_not_authorized': sum(1 for i in items if (i.get('result') and (i['result'].get('verification_status') == 'ISSUER_NOT_AUTHORIZED' or i['result'].get('category') == 'ISSUER_NOT_AUTHORIZED' or i['result'].get('status') in ('not_verified', 'ISSUER_NOT_AUTHORIZED')))),
            'unavailable': sum(1 for i in items if (i.get('result') and (i['result'].get('verification_status') == 'VERIFICATION_UNAVAILABLE' or i['result'].get('category') == 'VERIFICATION_UNAVAILABLE' or i['result'].get('status') in ('unable_to_authenticate', 'VERIFICATION_UNAVAILABLE')))),
            'invalid': sum(1 for i in items if (i['state'] == 'rejected' or (i.get('result') and (i['result'].get('verification_status') == 'INVALID_FILE' or i['result'].get('category') == 'INVALID_FILE' or i['result'].get('status') in ('invalid_file', 'INVALID_FILE'))))),
        }
    return res

def review_item(job_id, item_id, user, action, fields):
    with connect() as conn:
        job = conn.execute("SELECT * FROM upload_jobs WHERE id=? AND user_id=?", (job_id, user["id"])).fetchone()
        if not job:
            raise HTTPException(404, "Upload batch not found.")
        item = conn.execute("SELECT * FROM upload_items WHERE id=? AND job_id=?", (item_id, job_id)).fetchone()
        if not item:
            raise HTTPException(404, "Upload item not found.")
        if item["state"] != "awaiting_review":
            raise HTTPException(409, "This item is not awaiting review.")

        if action == "reject":
            res = {"status": "REGISTRATION_FAILED", "error": "Registration rejected by reviewer."}
            conn.execute("UPDATE upload_items SET state='failed', status='REGISTRATION_FAILED', data=NULL, result=? WHERE id=?", (json.dumps(res), item_id))
            conn.execute("UPDATE upload_jobs SET state='completed' WHERE id=? AND NOT EXISTS(SELECT 1 FROM upload_items WHERE job_id=? AND state IN ('pending','processing','awaiting_review'))", (job_id, job_id))
        elif action == "approve":
            ref = (fields.get("reference") or "").strip() or item["reference"]
            if not ref:
                raise HTTPException(422, "A certificate reference is required.")
            from .core import normalize_reference
            try:
                ref = normalize_reference(ref)
            except ValueError as exc:
                raise HTTPException(422, str(exc))

            # Update item metadata and reference, and re-enqueue for blockchain registration
            metadata = json.dumps(fields)
            conn.execute("UPDATE upload_items SET reference=?, metadata=?, state='pending', status='PENDING_BLOCKCHAIN' WHERE id=?", (ref, metadata, item_id))
            conn.execute("UPDATE upload_jobs SET state='processing' WHERE id=?", (job_id,))
        else:
            raise HTTPException(422, "Invalid review action.")

    return snapshot(job_id, user)

def retry_item(job_id, item_id, user):
    with connect() as conn:
        job = conn.execute("SELECT * FROM upload_jobs WHERE id=? AND user_id=?", (job_id, user["id"])).fetchone()
        if not job:
            raise HTTPException(404, "Upload batch not found.")
        item = conn.execute("SELECT * FROM upload_items WHERE id=? AND job_id=?", (item_id, job_id)).fetchone()
        if not item:
            raise HTTPException(404, "Upload item not found.")
        item = dict(item)

        # Check if already confirmed on-chain
        promoted = False
        try:
            chain = Registry()
            ref = item.get("reference")
            if ref:
                rec = chain.lookup(ref)
                if rec and not rec["revoked"]:
                    result_json = item.get("result")
                    result_dict = json.loads(result_json) if result_json else {}
                    expected_hash = result_dict.get("file_hash")
                    if not expected_hash and item.get("data"):
                        expected_hash = hashlib.sha256(bytes(item["data"])).hexdigest().lower()

                    if expected_hash and rec["file_hash"].lower() == expected_hash.lower():
                        contract_addr = getattr(chain.contract, "address", "0x0")
                        result_dict.update({
                            "status": "registered",
                            "registration_status": "REGISTERED_ON_BLOCKCHAIN",
                            "on_chain_verified": True,
                            "registered_at": rec["registered_at"],
                            "contract_address": contract_addr,
                            "file_hash": expected_hash,
                            "reference": ref,
                        })
                        conn.execute("UPDATE upload_items SET state='succeeded', status='REGISTERED_ON_BLOCKCHAIN', result=?, data=NULL WHERE id=?", (json.dumps(result_dict), item_id))
                        conn.execute("UPDATE upload_jobs SET state='completed' WHERE id=? AND NOT EXISTS(SELECT 1 FROM upload_items WHERE job_id=? AND state IN ('pending','processing','awaiting_review'))", (job_id, job_id))
                        promoted = True
        except Exception as e:
            logging.warning("Error checking on-chain record during retry: %s", e)

        if not promoted:
            if item.get("data"):
                conn.execute("UPDATE upload_items SET state='pending', status='PENDING_BLOCKCHAIN' WHERE id=?", (item_id,))
                conn.execute("UPDATE upload_jobs SET state='processing' WHERE id=?", (job_id,))
            else:
                raise HTTPException(409, "Original upload data is no longer cached for this item. Re-upload the certificate to retry.")
    return snapshot(job_id, user)

def csv_report(batch):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow([
        'Filename', 'Certificate reference', 'Processing status', 'Registration status',
        'Outcome', 'Message', 'Field Comparison', 'Transformation Advisory', 'Routing Decision', 'Transaction hash'
    ])
    def safe(value):
        value = str(value or '')
        return "'" + value if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else value
    for item in batch['items']:
        result = item['result'] or {}
        fa = item.get('field_analysis') or result.get('field_analysis') or {}
        fa_status = fa.get('status', 'unavailable')
        ta = item.get('transformation_analysis') or result.get('transformation_analysis') or {}
        ta_status = ta.get('advisory_outcome', 'unknown')
        rr = item.get('review_routing') or result.get('review_routing') or {}
        rr_status = rr.get('routing_outcome', 'unknown')

        writer.writerow([safe(v) for v in [
            item['filename'], item['reference'], item['state'],
            item.get('status') or result.get('status'),
            result.get('status') or result.get('category'),
            result.get('error') or result.get('message'),
            fa_status, ta_status, rr_status,
            result.get('transaction_hash')
        ]])
    return stream.getvalue()

def start_worker(verify, register):
    stop = threading.Event()
    def work():
        while not stop.is_set():
            try:
                with connect() as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    item = conn.execute("SELECT i.*,j.user_id,j.mode FROM upload_items i JOIN upload_jobs j ON j.id=i.job_id WHERE i.state='pending' ORDER BY i.id LIMIT 1").fetchone()
                    if item:
                        next_status = 'PENDING_BLOCKCHAIN' if item['status'] == 'PENDING_BLOCKCHAIN' else 'VALIDATING'
                        conn.execute("UPDATE upload_items SET state='processing', status=? WHERE id=?", (next_status, item['id']))
                        item = dict(item)
                if not item:
                    stop.wait(.2)
                    continue
                try:
                    with connect() as conn:
                        user = dict(conn.execute('SELECT * FROM users WHERE id=?', (item['user_id'],)).fetchone())
                    canon = canonical_role(user['role'])
                    if item['mode'] == 'register':
                        if canon == ROLE_SYSTEM_ADMIN:
                            raise ValueError('System administrators do not have certificate registration permissions.')
                        if canon != ROLE_INSTITUTION_ADMIN:
                            raise ValueError('Only approved institutions can register certificates.')
                        if user.get('approval_status') != 'APPROVED':
                            raise ValueError('Institution approval is no longer active.')

                    data_bytes = bytes(item['data'])
                    kind = item['kind']

                    if item['mode'] == 'register':
                        # Step 1: Validate original file and process safely
                        kind = validate_file(data_bytes, item['filename'], None)

                        # Step 5: Compute SHA-256 over exact original file bytes before any conversion or OCR
                        exact_hash = hashlib.sha256(data_bytes).hexdigest().lower()

                        # If already marked PENDING_BLOCKCHAIN (e.g. after approval from review), proceed directly
                        if item['status'] != 'PENDING_BLOCKCHAIN':
                            with connect() as conn:
                                conn.execute("UPDATE upload_items SET status='OCR_PROCESSING' WHERE id=?", (item['id'],))

                            analysis = analyze(data_bytes, kind)
                            fields = analysis.get("fields", {})
                            ocr_confidence = analysis.get("ocr_confidence")
                            extracted_ref = fields.get("reference")
                            supplied_ref = (item.get('reference') or "").strip()
                            ambiguous = fields.get("ambiguous_fields", [])

                            # Require human review if reference is missing or if critical metadata is ambiguous/low confidence
                            needs_review = False
                            reason = None
                            if not supplied_ref and not extracted_ref:
                                needs_review = True
                                reason = "Certificate reference ID could not be detected. Please provide a reference."
                            elif not supplied_ref and "reference" in ambiguous:
                                needs_review = True
                                reason = f"Multiple certificate references found in document ({extracted_ref}). Human review required to confirm."
                            elif not supplied_ref and ocr_confidence is not None and ocr_confidence < 50:
                                needs_review = True
                                reason = f"OCR confidence is low ({ocr_confidence:.0f}%). Human review required."
                            elif "name" in ambiguous or "course" in ambiguous:
                                needs_review = True
                                reason = "Ambiguous recipient or qualification detected in document text. Review required."

                            if needs_review:
                                with connect() as conn:
                                    res = {'status': 'AWAITING_REVIEW', 'message': reason, 'fields': fields, 'ocr_confidence': ocr_confidence, 'file_hash': exact_hash}
                                    conn.execute("UPDATE upload_items SET state='awaiting_review', status='AWAITING_REVIEW', result=?, ocr_confidence=?, metadata=? WHERE id=?",
                                                 (json.dumps(res), ocr_confidence, json.dumps(fields), item['id']))
                                    conn.execute("UPDATE upload_jobs SET state='processing' WHERE id=?", (item['job_id'],))
                                continue

                            ref_to_use = supplied_ref or extracted_ref
                            with connect() as conn:
                                conn.execute("UPDATE upload_items SET reference=?, status='PENDING_BLOCKCHAIN', metadata=? WHERE id=?", (ref_to_use, json.dumps(fields), item['id']))
                            item['reference'] = ref_to_use
                            item['metadata'] = json.dumps(fields)

                        # Perform registration with metadata override (preserves review edits)
                        ref_to_use = item.get('reference')
                        meta_override = json.loads(item['metadata']) if item.get('metadata') else None
                        try:
                            result = register(data_bytes, kind, ref_to_use, user, metadata_override=meta_override)
                        except TypeError:
                            result = register(data_bytes, kind, ref_to_use, user)
                        if result.get('status') not in ('registered', 'REGISTERED_ON_BLOCKCHAIN') or result.get('on_chain_verified') is False or (not result.get('transaction_hash') and not result.get('idempotent')):
                            raise ValueError('No confirmed and independently verified registration receipt was returned.')
                        result.setdefault('on_chain_verified', True)
                        state = 'succeeded'
                        status = 'REGISTERED_ON_BLOCKCHAIN'
                    else:
                        # Verify mode
                        with connect() as conn:
                            conn.execute("UPDATE upload_items SET status='VALIDATING' WHERE id=?", (item['id'],))
                        result = verify(data_bytes, kind, item['reference'], user)
                        state = 'succeeded'
                        status = result.get('category') or result.get('status', 'VERIFIED').upper()
                except UncertainTransactionError as exc:
                    result = {
                        'error': str(exc),
                        'status': 'REGISTRATION_STATUS_UNCERTAIN',
                        'transaction_hash': exc.tx_hash,
                        'reference': item.get('reference'),
                        'file_hash': exact_hash if 'exact_hash' in locals() else None,
                        'retryable': True
                    }
                    state = 'failed'
                    status = 'REGISTRATION_STATUS_UNCERTAIN'
                except Exception as exc:
                    if isinstance(exc, HTTPException):
                        detail = str(exc.detail)
                    elif isinstance(exc, (ValueError, UncertainTransactionError)):
                        detail = str(exc)
                    elif isinstance(exc, TimeoutError):
                        detail = "Transaction confirmation timed out. Check the registry before retrying."
                    else:
                        detail = 'Processing failed. Check the registry before retrying.'
                    if item['mode'] == 'register':
                        is_uncertain = (
                            isinstance(exc, (TimeoutError, UncertainTransactionError))
                            or (isinstance(exc, HTTPException) and exc.status_code == 504)
                            or "timed out" in detail.lower()
                            or "timeout" in detail.lower()
                            or "uncertain" in detail.lower()
                        )
                        if is_uncertain:
                            result = {
                                'error': detail,
                                'status': 'REGISTRATION_STATUS_UNCERTAIN',
                                'transaction_hash': getattr(exc, 'tx_hash', None),
                                'reference': item.get('reference'),
                                'file_hash': exact_hash if 'exact_hash' in locals() else None,
                                'retryable': True
                            }
                            state = 'failed'
                            status = 'REGISTRATION_STATUS_UNCERTAIN'
                        else:
                            result = {'error': detail, 'status': 'REGISTRATION_FAILED', 'reference': item.get('reference'), 'file_hash': exact_hash if 'exact_hash' in locals() else None}
                            state = 'failed'
                            status = 'REGISTRATION_FAILED'
                    else:
                        result = {
                            'error': detail,
                            'status': 'unable_to_authenticate',
                            'category': 'VERIFICATION_UNAVAILABLE',
                            'label': 'Verification Unavailable',
                            'message': detail,
                            'next_action': 'Retry the verification in a few moments, or check blockchain connectivity.',
                            'checks': {'reference_found': None, 'hash_matches': None, 'issuer_approved': None, 'active': None},
                            'file_hash': None,
                            'registered_hash': None,
                            'hash_matches': None,
                            'hash_comparison': 'Blockchain service unreachable',
                            'issuer': None,
                            'issuer_name': None,
                            'issuer_authorized': None,
                            'blockchain_record_status': 'UNAVAILABLE',
                            'transaction_hash': None,
                            'explorer_url': None,
                            'fields': {},
                            'ai': {'status': 'unavailable', 'label': 'AI analysis unavailable', 'score': None},
                        }
                        state = 'failed'
                        status = 'VERIFICATION_UNAVAILABLE'
                fa_json = json.dumps(result["field_analysis"]) if (isinstance(result, dict) and result.get("field_analysis")) else None
                vt_json = json.dumps(result["visual_tampering"]) if (isinstance(result, dict) and result.get("visual_tampering")) else None
                ta_json = json.dumps(result["transformation_analysis"]) if (isinstance(result, dict) and result.get("transformation_analysis")) else None
                rr_json = json.dumps(result["review_routing"]) if (isinstance(result, dict) and result.get("review_routing")) else None
                with connect() as conn:
                    if status in ('REGISTRATION_STATUS_UNCERTAIN', 'AWAITING_REVIEW'):
                        conn.execute('UPDATE upload_items SET state=?,status=?,result=?,field_analysis=?,visual_tampering=?,transformation_analysis=?,review_routing=? WHERE id=?',
                                     (state, status, json.dumps(result), fa_json, vt_json, ta_json, rr_json, item['id']))
                    else:
                        conn.execute('UPDATE upload_items SET state=?,status=?,result=?,field_analysis=?,visual_tampering=?,transformation_analysis=?,review_routing=?,data=NULL WHERE id=?',
                                     (state, status, json.dumps(result), fa_json, vt_json, ta_json, rr_json, item['id']))
                    conn.execute("UPDATE upload_jobs SET state='completed' WHERE id=? AND NOT EXISTS(SELECT 1 FROM upload_items WHERE job_id=? AND state IN ('pending','processing','awaiting_review'))", (item['job_id'], item['job_id']))
            except Exception:
                logging.exception('Upload worker error')
                stop.wait(1)
    thread = threading.Thread(target=work, name='authentra-upload-worker', daemon=True)
    thread.start()
    return stop, thread


@contextmanager
def worker_guard():
    """One app worker per SQLite database; fail closed instead of replaying live jobs."""
    path = Path(os.getenv('AUTHENTRA_DB', str(ROOT / '.local/authentra.db'))).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + '.uploads.lock', 'a+b') as handle:
        handle.seek(0)
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('Run one AuthenTra server worker per database. Another upload worker is active.') from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
