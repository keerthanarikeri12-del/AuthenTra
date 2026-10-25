"""Generate the editable, standalone SVG blueprint (no external assets)."""
from pathlib import Path
from html import escape
root=Path(__file__).resolve().parents[1]
parts=['''<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="1170" viewBox="0 0 1400 1170" role="img" aria-labelledby="title desc">
<title id="title">AuthenTra corrected system architecture</title><desc id="desc">Authenticated roles connect to FastAPI. Trusted checks use certificate ID lookup, revocation, issuer approval and exact SHA-256 file comparison. OCR and Random Forest remain advisory. Personal data is kept off-chain.</desc>
<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#527c78"/></marker></defs>
<rect width="1400" height="1170" fill="#f5f8f7"/>
<style>text{font-family:Arial,sans-serif;fill:#234b49}.title{font-size:34px;font-weight:700;letter-spacing:-1px}.sub{font-size:15px;fill:#748d89}.heading{font-size:18px;font-weight:700}.body{font-size:14px;fill:#5c7a75}.tiny{font-size:12px;fill:#78928c}.label{font-size:11px;font-weight:700;letter-spacing:1.5px;fill:#348b70}.arrow{fill:none;stroke:#527c78;stroke-width:2;marker-end:url(#arrow)}.dashed{stroke-dasharray:6 5}</style>''']
def text(x,y,value,cls='body',fill=None):
    parts.append(f'<text x="{x}" y="{y}" class="{cls}"'+(f' style="fill:{fill}"' if fill else '')+f'>{escape(value)}</text>')
def rect(x,y,w,h,fill='#fff',stroke='#d9e6df',r=12):parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}"/>')
def arrow(d,dash=False):parts.append(f'<path d="{d}" class="arrow'+(' dashed' if dash else '')+'"/>')
def card(x,y,w,h,title,lines,accent='#edf5ef'):
    rect(x,y,w,h);rect(x+1,y+1,w-2,42,accent,accent,11);text(x+18,y+28,title,'heading')
    for i,line in enumerate(lines):text(x+18,y+67+i*23,line)
text(45,55,'AuthenTra','title');text(45,85,'AI assisted Digital Certificate Authenticity Verification using Blockchain','sub')
text(45,116,'CORRECTED ARCHITECTURE  /  RESEARCH PROTOTYPE','label')
card(45,145,400,105,'Verifier',['Sign in • Upload original file • View evidence'])
card(500,145,400,105,'Approved institution',['Sign in • Register in bulk • Revoke own records'])
card(955,145,400,105,'Platform owner',['Verify institution identity • Approve / disable issuers'])
arrow('M 245 250 V 277');arrow('M 700 250 V 277');arrow('M 1155 250 V 277')
rect(45,278,1310,82,'#244b48','#244b48');text(68,308,'React interface → FastAPI authenticated API','heading','#fff');text(68,336,'JWT in HttpOnly cookie • Server-assigned roles • File type / size limits • Protected registration and revocation endpoints','body','#c4ddd3')
arrow('M 230 360 V 395');arrow('M 700 360 V 395');arrow('M 1175 360 V 395')
card(45,398,365,302,'01  Institution registration',[
'1. Validate original PDF / PNG / JPEG',
'2. Confirm a unique certificate ID',
'3. SHA-256 of original uploaded bytes',
'4. Authorized institution signs transaction',
'5. Smart contract checks issuer permission',
'6. Confirm transaction before success',
'Bulk: per-file results, throughput and failures',
'Revocation: issuer of record or platform owner'
])
card(435,398,495,402,'02  Trusted certificate verification',[
'1. Validate the original uploaded file',
'2. Compute SHA-256 of exact file bytes',
'3. Resolve ID: user entry or extracted text',
'    Missing / invalid ID → Inconclusive',
'4. Look up the record using the ID digest',
'    Absent record → Not Registered',
'5. Check revocation → Revoked if withdrawn',
'6. Check issuer approval → Not Verified if disabled',
'7. Compare hashes → Possible Tampering if different',
'8. All checks pass → Verified (Registered and Unchanged)',
'Invalid file / chain failure → Unable to Authenticate',
'Return each check independently with the final result'
])
card(955,398,400,302,'03  Separate advisory analysis',[
'PDF embedded text or Tesseract OCR',
'Extract ID, recipient, course and issue date',
'Validate fields and construct text features',
'Experimental Random Forest model',
'Output: anomaly / no major anomaly / unavailable',
'Synthetic training data; held-out template groups',
'AI never overrides the trusted verification result',
'Extracted personal fields are not saved in history'
],'#eeeff8')
arrow('M 955 730 H 932',True);text(963,724,'OCR supplies a candidate ID.','tiny');text(963,746,'Allow manual correction; never treat OCR as proof.','tiny')
rect(45,730,365,70,'#eef5f0');text(63,757,'PRIVACY BY DESIGN','label');text(63,780,'Temporary uploads removed, including on failure.','tiny')
arrow('M 230 700 V 714 H 26 V 862 H 65');arrow('M 670 800 V 862 H 635')
card(65,826,570,160,'Ethereum / Solidity registry',[
'SHA-256 reference digest • SHA-256 file hash',
'Issuer address • Registration timestamp • Revoked flag',
'Owner-controlled approved-issuer mapping',
'No names, grades, full certificate files or passwords'
])
arrow('M 1330 700 V 815',True)
card(715,826,640,160,'Off-chain operational storage',[
'SQLite: users, password hashes, roles, institution wallets',
'Registration index, verification history and action audit log',
'Signer keys: separate development config / server environment',
'Full documents: not retained. IPFS: optional future extension'
])
rect(45,1016,1310,116,'#e8f2eb','#d5e6da');text(66,1046,'06  MEASUREMENT & PROJECT STRENGTHS','label');text(66,1074,'Outcome correctness • Mean / p95 latency • OCR field extraction • ML precision / recall / F1 • Bulk throughput • Gas used','body');text(66,1102,'An exact hash match supports file integrity. Approved issuance and revocation checks provide the trust context. AI adds advisory evidence.','tiny')
text(45,1155,'Limits: rescanning changes the hash; synthetic AI is not real-world fraud detection; local-chain fees are not public-network cost estimates.','tiny')
parts.append('</svg>')
(root/'public').mkdir(exist_ok=True);(root/'docs').mkdir(exist_ok=True)
svg='\n'.join(parts)
(root/'public/architecture.svg').write_text(svg,encoding='utf-8')
(root/'docs/architecture.svg').write_text(svg,encoding='utf-8')
print('Corrected architecture SVG created.')
