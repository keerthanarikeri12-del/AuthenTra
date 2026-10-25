"""Measure a tiny controlled batch including an intentional duplicate."""
import io
import json
import time
from pathlib import Path
import httpx
from reportlab.pdfgen import canvas
root=Path(__file__).resolve().parents[1]
with httpx.Client(base_url='http://127.0.0.1:8000',timeout=60) as client:
    client.post('/api/auth/login',json={'email':'issuer@authentra.demo','password':'AuthenTra-demo-2026!'}).raise_for_status()
    prefix='AT-BATCH-'+str(int(time.time()))
    ids=[prefix+'-A',prefix+'-B',prefix+'-A']
    files=[]
    for i,reference in enumerate(ids):
        stream=io.BytesIO();c=canvas.Canvas(stream);c.drawString(50,750,'DEMONSTRATION CERTIFICATE');c.drawString(50,700,'Certificate ID: '+reference);c.save()
        files.append(('files',(f'batch-{i}.pdf',stream.getvalue(),'application/pdf')))
    response=client.post('/api/certificates/bulk',files=files,data={'references':json.dumps(ids)})
    response.raise_for_status(); result=response.json()
    assert [r['ok'] for r in result['results']]==[True,True,False], result
    report_path=root/'.local/system-metrics.json'
    report=json.loads(report_path.read_text()) if report_path.exists() else {}
    report['bulk']={'attempted':3,'registered':2,'expected_duplicate_failures':1,'duration_ms':result['duration_ms'],'throughput_per_second':result['throughput_per_second'],'failure_rate':result['failure_rate'],'gas_used':[r['gas_used'] for r in result['results'] if r['ok']],'scope':'Three-file batch; one intentionally repeated ID. This is a functional measurement, not a scalability benchmark.'}
    report_path.write_text(json.dumps(report,indent=2))
    print(json.dumps(report['bulk'],indent=2))
