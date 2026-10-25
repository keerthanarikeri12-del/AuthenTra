"""Small real-chain integration demonstration, not a load test."""
import json
import statistics
import time
from pathlib import Path
import httpx

root = Path(__file__).resolve().parents[1]
client = httpx.Client(base_url="http://127.0.0.1:8000", timeout=90)
owner = httpx.Client(base_url="http://127.0.0.1:8000", timeout=60)
def login(session, role):
    r=session.post('/api/auth/login', json={'email':role+'@authentra.demo','password':'AuthenTra-demo-2026!'})
    r.raise_for_status()
login(client,'verifier'); login(owner,'owner')
cases=[]; durations=[]
def verify(name,filename,reference,expected):
    start=time.perf_counter()
    r=client.post('/api/verify', files={'file':(filename,(root/'samples'/filename).read_bytes())},data={'reference':reference})
    r.raise_for_status(); result=r.json(); elapsed=(time.perf_counter()-start)*1000
    durations.append(elapsed)
    cases.append({'name':name,'expected':expected,'actual':result['status'],'passed':result['status']==expected,'duration_ms':round(elapsed,1)})
    return result
verify('Unchanged registered original','original.pdf','AT-2026-0001','verified')
verify('Changed name, same certificate ID','modified.pdf','AT-2026-0001','possible_tampering')
verify('Unknown certificate ID','unregistered.pdf','AT-2026-9999','not_registered')
verify('Revoked original','revoked.pdf','AT-2026-0002','revoked')
verify('Revoked record with different hash','modified.pdf','AT-2026-0002','revoked')
institutions=owner.get('/api/institutions').json()
issuer=next(r for r in institutions if r['email']=='issuer@authentra.demo')
try:
    owner.post(f"/api/institutions/{issuer['id']}/approval",json={'approved':False}).raise_for_status()
    verify('Issuer approval withdrawn','original.pdf','AT-2026-0001','not_verified')
finally:
    owner.post(f"/api/institutions/{issuer['id']}/approval",json={'approved':True}).raise_for_status()
scan=verify('Scanned copy of original','scan.png','','possible_tampering')
bad=client.post('/api/verify',files={'file':('bad.pdf',b'not a PDF')}).json()
cases.append({'name':'Invalid uploaded file','expected':'unable_to_authenticate','actual':bad['status'],'passed':bad['status']=='unable_to_authenticate'})
expected_fields={'reference':'AT-2026-0001','name':'Alex Morgan','course':'Blockchain Fundamentals','issue_date':'2025-06-12'}
ocr={'field_count':4,'correct':sum(scan['fields'].get(k)==v for k,v in expected_fields.items()),'method':scan['extraction_method']}
ocr['field_accuracy']=ocr['correct']/ocr['field_count']
output={'total':len(cases),'passed':sum(c['passed'] for c in cases),'mean_ms':round(statistics.mean(durations),1),'p95_ms':round(sorted(durations)[-1],1),'cases':cases,'ocr':ocr,'scope':'Eight controlled cases on a local development chain, seven timed requests. The 95th percentile is the slowest request in this small set. Scanned OCR is included; results are hardware- and workload-dependent.'}
(root/'.local/system-metrics.json').write_text(json.dumps(output,indent=2))
print(json.dumps(output,indent=2))
client.close();owner.close()
if output['passed'] != output['total']: raise SystemExit(1)
