import CertificateUpload from './CertificateUpload';
import React, { useEffect, useRef, useState } from 'react';
import {
  ShieldCheck, ScanLine, History, Building2, ChartNoAxesCombined, Workflow,
  ArrowUpRight, ArrowRight, UploadCloud, FileText, Check, X, Clock3,
  LockKeyhole, Fingerprint, ChevronRight, LogOut, Download, AlertTriangle,
  CircleHelp, Search, Layers3, Activity, BrainCircuit, CheckCircle2,
  LoaderCircle, Plus, Ban, Copy, Menu
} from 'lucide-react';

const ROLE_USER = 'USER';
const ROLE_INSTITUTION_ADMIN = 'INSTITUTION_ADMIN';
const ROLE_SYSTEM_ADMIN = 'SYSTEM_ADMIN';

function getCanonicalRole(role) {
  if (!role) return ROLE_USER;
  const r = String(role).toUpperCase();
  if (r === 'SYSTEM_ADMIN' || r === 'OWNER') return ROLE_SYSTEM_ADMIN;
  if (r === 'INSTITUTION_ADMIN' || r === 'INSTITUTION') return ROLE_INSTITUTION_ADMIN;
  return ROLE_USER;
}

const labels = {
  verified: 'Verified',
  VERIFIED: 'Verified',
  possible_tampering: 'Possible Tampering',
  tampering_detected: 'Possible Tampering or File Mismatch',
  TAMPERING_DETECTED: 'Possible Tampering or File Mismatch',
  POSSIBLE_TAMPERING_OR_FILE_MISMATCH: 'Possible Tampering or File Mismatch',
  not_registered: 'Not Registered',
  NOT_REGISTERED: 'Not Registered',
  inconclusive: 'Inconclusive',
  INCONCLUSIVE: 'Inconclusive',
  NOT_REGISTERED_OR_INCONCLUSIVE: 'Not Registered or Inconclusive',
  revoked: 'Revoked',
  REVOKED: 'Revoked',
  not_verified: 'Issuer Not Authorized',
  ISSUER_NOT_AUTHORIZED: 'Issuer Not Authorized',
  unable_to_authenticate: 'Verification Unavailable',
  VERIFICATION_UNAVAILABLE: 'Verification Unavailable',
  invalid_file: 'Invalid File',
  INVALID_FILE: 'Invalid File',
};

const sampleItems = [
  {name:'original.pdf',label:'Original',ref:'AT-2026-0001'},
  {name:'modified.pdf',label:'Modified',ref:'AT-2026-0001'},
  {name:'unregistered.pdf',label:'Unregistered',ref:'AT-2026-9999'},
  {name:'revoked.pdf',label:'Revoked',ref:'AT-2026-0002'},
  {name:'scan.png',label:'Scanned copy',ref:'AT-2026-0001'}
];

async function api(path, options = {}) {
  const response = await fetch('/api' + path, {
    ...options,
    headers: {
      ...(options.body && !(options.body instanceof FormData) ? {'Content-Type': 'application/json'} : {}),
      ...options.headers
    }
  });
  let value;
  try {
    value = await response.json();
  } catch {
    throw new Error('The service could not respond. Please try again.');
  }
  if (response.status === 401 && !path.startsWith('/auth/')) {
    window.dispatchEvent(new Event('authentra-session-expired'));
  }
  if (!response.ok) {
    const detail = value.detail;
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(d => d.msg).join('; ') : 'The request failed.');
  }
  return value;
}

const fmtTime = value => value ? new Date(value.replace(' ', 'T') + (value.endsWith('Z') ? '' : 'Z')).toLocaleString(undefined, {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—';

function saveFile(name, content, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([content], {type}));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Badge({status, children}) {
  const norm = (status || '').toLowerCase();
  const cls = norm === 'verified' ? 'verified' :
              norm.includes('tampering') || norm.includes('mismatch') ? 'possible_tampering' :
              norm.includes('revoked') ? 'revoked' :
              norm.includes('not_authorized') || norm.includes('not_verified') || norm.includes('invalid') ? 'not_verified' :
              norm.includes('unavailable') || norm.includes('unable') ? 'unable_to_authenticate' :
              norm.includes('registered') || norm.includes('inconclusive') ? 'inconclusive' : norm;
  return <span className={'badge ' + cls}><span className="badge-dot"/>{children || labels[status] || status}</span>;
}

function RoleBadge({role}) {
  const canon = getCanonicalRole(role);
  if (canon === ROLE_SYSTEM_ADMIN) {
    return <span className="role-badge admin"><ShieldCheck size={12}/> Platform Administrator</span>;
  }
  if (canon === ROLE_INSTITUTION_ADMIN) {
    return <span className="role-badge institution"><Building2 size={12}/> Institution Administrator</span>;
  }
  return <span className="role-badge user"><LockKeyhole size={12}/> Standard User</span>;
}

function Spinner() { return <LoaderCircle size={18} className="spin"/>; }
function Brand() {
  return (
    <div className="brand">
      <div className="brand-symbol"><ShieldCheck size={27}/></div>
      <span>Authen<span className="brand-accent">Tra</span><small>CERTIFICATE INTELLIGENCE</small></span>
    </div>
  );
}

function ErrorMessage({message}) {
  return message ? <div className="error" role="alert"><AlertTriangle size={18}/>{message}</div> : null;
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.616z"/>
      <path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.258c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z"/>
      <path fill="#FBBC05" d="M3.964 10.707c-.18-.54-.282-1.117-.282-1.707s.102-1.167.282-1.707V4.961H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.039l3.007-2.332z"/>
      <path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.961L3.964 7.293C4.672 5.166 6.656 3.58 9 3.58z"/>
    </svg>
  );
}

function AppleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 170 170" fill="currentColor" aria-hidden="true">
      <path d="M150.37 130.25c-2.45 5.66-5.35 10.87-8.71 15.66-4.58 6.53-8.33 11.05-11.22 13.56-4.48 4.12-9.28 6.23-14.42 6.35-3.69 0-8.14-1.05-13.32-3.18-5.19-2.12-9.97-3.17-14.34-3.17-4.58 0-9.49 1.05-14.75 3.17-5.26 2.13-9.5 3.24-12.74 3.35-4.35.13-9.16-1.9-14.42-6.08-3.69-3.04-7.67-7.81-11.96-14.3-5.88-8.91-10.4-18.99-13.56-30.24-3.16-11.26-4.74-21.78-4.74-31.57 0-14.45 3.65-26.68 10.96-36.68 7.3-10.01 16.59-15.11 27.87-15.31 4.58 0 9.8 1.19 15.66 3.58 5.86 2.39 9.8 3.69 11.83 3.91 1.74-.22 5.88-1.57 12.41-4.04 6.53-2.47 11.75-3.58 15.66-3.34 11.96.65 21.64 4.89 29.04 12.72-10.66 6.52-15.88 15.44-15.66 26.75.22 8.91 3.7 16.3 10.44 22.18 6.74 5.87 14.68 9.35 23.82 10.44-2.18 6.31-4.79 12.61-7.83 18.91zm-32.39-106.63c-.11 3.04-.92 6.19-2.44 9.45-1.52 3.26-3.69 6.2-6.52 8.81-3.15 2.93-6.69 5.05-10.61 6.36-3.92 1.3-7.56 1.85-10.93 1.63-.22-3.04.54-6.19 2.28-9.45 1.74-3.26 4.02-6.09 6.85-8.48 3.15-2.72 6.68-4.78 10.6-6.19 3.91-1.42 7.5-2.13 10.77-2.13z"/>
    </svg>
  );
}

function Login({onLogin, health, sessionMessage}) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [signup, setSignup] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [accountType, setAccountType] = useState(() => (window.location.hash === '#admin' ? 'admin' : 'user'));
  const [reference, setReference] = useState('');
  const [info, setInfo] = useState('');
  const [wallet, setWallet] = useState('');
  const [verifyEmailState, setVerifyEmailState] = useState(null);
  const [verifyCode, setVerifyCode] = useState('');
  const [demoCode, setDemoCode] = useState('');
  const [pendingCard, setPendingCard] = useState(null);

  useEffect(() => {
    function onHash() {
      if (window.location.hash === '#admin') {
        setAccountType('admin');
        setSignup(false);
      }
    }
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  async function triggerOAuth(provider) {
    setBusy(true); setError(''); setNotice('');
    try {
      const res = await api(`/auth/oauth/${provider}/url`);
      if (res?.url) window.location.href = res.url;
      else throw new Error(`Could not initiate ${provider} login.`);
    } catch(e) {
      setError(e.message);
      setBusy(false);
    }
  }

  async function handleVerifyEmail(e) {
    e?.preventDefault();
    setBusy(true); setError(''); setNotice('');
    try {
      const res = await api('/auth/verify-email', {
        method: 'POST',
        body: JSON.stringify({email: verifyEmailState.email, code: verifyCode.trim()})
      });
      setNotice(res.message || 'Email verified successfully. Your application is now pending platform administrator approval.');
      setVerifyEmailState(null);
      setVerifyCode('');
      setPendingCard({email: verifyEmailState.email, name: verifyEmailState.name || 'Institution'});
    } catch(e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function resendVerificationCode() {
    if (!verifyEmailState?.email) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const res = await api('/auth/resend-verification', {
        method: 'POST',
        body: JSON.stringify({email: verifyEmailState.email})
      });
      setNotice(res.message || 'Verification code resent.');
      if (res.demo_verification_code) setDemoCode(res.demo_verification_code);
    } catch(e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function checkInstitutionStatus(emailToCheck) {
    setBusy(true); setError(''); setNotice('');
    try {
      const res = await api(`/auth/institution-status?email=${encodeURIComponent(emailToCheck)}`);
      if (res.approved) {
        setNotice('Congratulations! Your institution has been approved. You can now sign in to your workspace.');
        setPendingCard(null);
      } else {
        setNotice(`Status: ${res.approval_status}. ${res.status_description}`);
      }
    } catch(e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function submit(e, preset) {
    e?.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      if(signup && !preset) {
        if (accountType === 'institution') {
          const res = await api('/auth/institution-signup', {
            method: 'POST',
            body: JSON.stringify({email, password, name, institution_reference: reference, verification_info: info, wallet})
          });
          setSignup(false);
          if (res.demo_verification_code) setDemoCode(res.demo_verification_code);
          setVerifyEmailState({email, name});
          setNotice('Application submitted. Please enter the 6-digit verification code sent to your official institutional email.');
        } else {
          await api('/auth/signup', {method: 'POST', body: JSON.stringify({email, password, name})});
          setSignup(false);
          setNotice('Account created. Sign in to your verification workspace.');
        }
      } else {
        const endpoint = accountType === 'admin' ? '/auth/admin-login' : '/auth/login';
        const payload = accountType === 'admin' ? {email, password} : {email, password, account_type: accountType};
        const user = await api(endpoint, {
          method: 'POST',
          body: JSON.stringify(payload)
        });
        onLogin(user);
      }
    } catch(e) {
      const msg = e.message || '';
      if (msg.includes('verify your institutional email')) {
        setVerifyEmailState({email});
        setError('Please verify your email address to continue.');
      } else if (msg.includes('awaiting approval') || msg.includes('PENDING_APPROVAL')) {
        setPendingCard({email, name});
        setError('');
      } else {
        setError(msg);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-shell">
      <section className="login-story">
        <Brand/>
        <div className="story-content">
          <span className="eyebrow light">ROLE-BASED CREDENTIAL ASSURANCE</span>
          <h1>A certificate.<br/>A verifiable<br/><em>source of trust.</em></h1>
          <p>
            Cryptographic SHA-256 integrity, smart contract issuer governance, and AI-assisted advisory analysis in three distinct operational roles.
          </p>
          <div className="credential-art">
            <div className="art-line"/><ShieldCheck size={46}/><div className="art-rule wide"/><div className="art-rule"/>
            <div className="art-footer"><span>REGISTERED & UNCHANGED</span><CheckCircle2 size={25}/></div>
            <div className="art-seal"><Fingerprint size={38}/></div>
          </div>
          <div className="story-points">
            <span><LockKeyhole size={16}/> Role separation & privacy</span>
            <span><Layers3 size={16}/> Blockchain-backed records</span>
          </div>
        </div>
        <small className="story-bottom">AuthenTra · Digital Certificate Verification / 2026</small>
      </section>

      <section className="login-form">
        <div className="login-top">
          <span>AUTHENTRUST PORTAL</span>
          <Badge status={health?.blockchain ? 'verified' : 'inconclusive'}>
            {health?.blockchain ? 'Local chain connected' : 'Connecting to services'}
          </Badge>
        </div>

        <div className="login-inner">
          <div className="square-icon">
            {accountType === 'admin' ? <LockKeyhole size={25}/> : accountType === 'institution' ? <Building2 size={25}/> : <ScanLine size={25}/>}
          </div>
          <h2>
            {signup
              ? (accountType === 'institution' ? 'Register your institution' : 'Create your user account')
              : (accountType === 'institution' ? 'Institution Login' : accountType === 'admin' ? 'Administrator Portal' : 'User Login')}
          </h2>
          <p>
            {accountType === 'institution'
              ? 'Register and manage certificates through your approved institution.'
              : accountType === 'admin'
              ? 'Platform governance, institution approvals, and registry oversight.'
              : 'Verify certificates and view your private verification history.'}
          </p>

          <div className="login-choices" aria-label="Choose login experience">
            {[
              ['user', 'User Portal'],
              ['institution', 'Institution Portal'],
              ['admin', 'Admin Portal']
            ].map(([id, label]) => (
              <button
                type="button"
                key={id}
                disabled={busy}
                className={accountType === id ? 'primary' : 'secondary'}
                aria-pressed={accountType === id}
                aria-label={id === 'institution' ? 'Institution Login' : label}
                onClick={() => {
                  setAccountType(id);
                  setSignup(false);
                  setError('');
                  setNotice('');
                  setPassword('');
                  setVerifyEmailState(null);
                  setPendingCard(null);
                  if (id === 'admin') window.location.hash = 'admin';
                  else if (window.location.hash === '#admin') window.location.hash = '';
                }}
              >
                {label}
              </button>
            ))}
          </div>

          <ErrorMessage message={sessionMessage}/>
          <ErrorMessage message={error}/>
          {notice && <p className="success-note"><CheckCircle2 size={16}/>{notice}</p>}

          {/* Institutional Email Verification View */}
          {verifyEmailState && (
            <div className="pending-institution-card" role="region" aria-label="Email Verification">
              <h3><ShieldCheck size={20}/> Verify Institutional Email</h3>
              <p>We sent a 6-digit confirmation code to <strong>{verifyEmailState.email}</strong>.</p>
              {demoCode && (
                <p style={{background:'#eef2ff',padding:'6px 10px',borderRadius:'5px',color:'#3730a3',fontSize:'11px'}}>
                  Demo verification code: <strong className="mono">{demoCode}</strong>
                </p>
              )}
              <form onSubmit={handleVerifyEmail} style={{marginTop:'12px'}}>
                <label>
                  Enter 6-digit verification code
                  <div className="verification-code-box">
                    <input
                      type="text"
                      inputMode="numeric"
                      pattern="[0-9]{6}"
                      maxLength={6}
                      required
                      placeholder="123456"
                      value={verifyCode}
                      onChange={e => setVerifyCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                      autoFocus
                    />
                    <button type="submit" className="primary" disabled={busy || verifyCode.trim().length !== 6}>
                      {busy ? <Spinner/> : 'Confirm code'}
                    </button>
                  </div>
                </label>
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginTop:'10px'}}>
                  <button type="button" className="text-button" onClick={resendVerificationCode} disabled={busy}>
                    Resend code
                  </button>
                  <button type="button" className="text-button" onClick={() => { setVerifyEmailState(null); setSignup(false); setPendingCard(null); }}>
                    Back to login
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* Pending Approval Screen */}
          {pendingCard && !verifyEmailState && (
            <div className="pending-institution-card" role="region" aria-label="Pending Approval">
              <h3><Clock3 size={20}/> Institutional Approval Pending</h3>
              <p>
                Your application for <strong>{pendingCard.name || pendingCard.email}</strong> is awaiting verification by the platform administrator.
              </p>
              <div className="pending-institution-meta">
                <span>Account: <strong>{pendingCard.email}</strong></span>
                <span>Status: <Badge status="inconclusive">PENDING_APPROVAL</Badge></span>
              </div>
              <p style={{fontSize:'11px',color:'#6b7280'}}>
                Protected operations such as certificate registration and bulk upload remain disabled until an administrator configures your signer wallet on the blockchain.
              </p>
              <div style={{display:'flex',gap:'10px',marginTop:'14px'}}>
                <button
                  type="button"
                  className="primary"
                  style={{flex:1}}
                  disabled={busy}
                  onClick={() => checkInstitutionStatus(pendingCard.email)}
                >
                  {busy ? <Spinner/> : 'Check Approval Status'}
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={() => { setPendingCard(null); setSignup(false); }}
                >
                  Back to login
                </button>
              </div>
            </div>
          )}

          {/* Main Login / Registration Form */}
          {!verifyEmailState && !pendingCard && (
            <>
              {/* Administrator Portal Notice */}
              {accountType === 'admin' && (
                <div className="admin-portal-card" role="region" aria-label="Administrator Portal Security Info">
                  <div className="admin-portal-header">
                    <ShieldCheck size={18}/>
                    <strong>Restricted Access · System Administrator Portal</strong>
                  </div>
                  <p>
                    Strictly authorized administrator accounts only. Provides institutional access governance, platform-wide audit trail, and certificate registry oversight.
                  </p>
                  <div className="admin-portal-notice">
                    <AlertTriangle size={15}/>
                    <span>Certificate upload, bulk registration, and blockchain signing are strictly disabled for System Administrators.</span>
                  </div>
                  <p style={{fontSize:'10px',color:'#94a3b8',marginTop:'8px',marginBottom:0}}>
                    Administrative accounts must be securely provisioned via administrative CLI (<code>python scripts/create_admin.py</code>). Public registration is disabled.
                  </p>
                </div>
              )}

              {/* User Login Experience: Google & Apple OAuth */}
              {accountType === 'user' && !signup && (
                <>
                  <div className="oauth-section">
                    <button
                      type="button"
                      className="oauth-btn google"
                      onClick={() => triggerOAuth('google')}
                      disabled={busy}
                    >
                      <GoogleIcon/> Continue with Google
                    </button>
                    <button
                      type="button"
                      className="oauth-btn apple"
                      onClick={() => triggerOAuth('apple')}
                      disabled={busy}
                    >
                      <AppleIcon/> Continue with Apple
                    </button>
                  </div>
                  <div className="oauth-divider">
                    <span>or sign in with password</span>
                  </div>
                </>
              )}

              {/* Institution Login Experience: Policy Banner */}
              {accountType === 'institution' && (
                <div className="domain-policy-card">
                  <strong>Accredited Institutional Email Policy</strong>
                  Official educational domains ending in <code>.edu</code>, <code>.ac.in</code>, <code>.edu.in</code>, <code>.res.in</code>, or verified allowlist registries are accepted. Personal freemail (@gmail, @yahoo, etc.) and generic .in domains are rejected.
                </div>
              )}

              <form onSubmit={submit}>
                {signup && (
                  <label>
                    {accountType === 'institution' ? 'Institution name' : 'Full name'}
                    <input
                      required
                      minLength={2}
                      maxLength={100}
                      value={name}
                      onChange={e => setName(e.target.value)}
                      autoComplete="name"
                      placeholder={accountType === 'institution' ? 'e.g. Stanford University' : 'Your full name'}
                    />
                  </label>
                )}

                {signup && accountType === 'institution' && (
                  <>
                    <label>
                      Institution ID / registration reference
                      <input
                        required
                        minLength={3}
                        maxLength={200}
                        value={reference}
                        onChange={e => setReference(e.target.value)}
                        placeholder="e.g. STAN-2026-REG"
                      />
                    </label>
                    <label>
                      Verification information
                      <input
                        required
                        minLength={10}
                        maxLength={2000}
                        placeholder="Official website, office address, and authorized contact"
                        value={info}
                        onChange={e => setInfo(e.target.value)}
                      />
                    </label>
                    <label>
                      Institution Ethereum wallet
                      <input
                        required
                        pattern="0x[0-9a-fA-F]{40}"
                        value={wallet}
                        onChange={e => setWallet(e.target.value)}
                        placeholder="0x..."
                      />
                      <small>Provide your institution wallet address. Never enter a private key.</small>
                    </label>
                  </>
                )}

                <label>
                  {accountType === 'institution' ? 'Official email address' : accountType === 'admin' ? 'Administrator email' : 'Email address'}
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={e => setEmail(e.target.value)}
                    placeholder={accountType === 'institution' ? 'issuer@institution.edu' : accountType === 'admin' ? 'sysadmin@authentra.gov' : 'user@example.com'}
                    autoComplete="username"
                  />
                </label>

                <label>
                  Password
                  <input
                    type="password"
                    required
                    minLength={signup ? 12 : 1}
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    placeholder={signup ? 'At least 12 characters' : 'Enter your password'}
                    autoComplete={signup ? 'new-password' : 'current-password'}
                  />
                </label>

                <button className="primary full" disabled={busy}>
                  {busy ? <Spinner/> : signup ? (accountType === 'institution' ? 'Apply for approval' : 'Create user account') : accountType === 'admin' ? 'Sign in to Admin Console' : 'Open workspace'}
                  <ArrowRight size={18}/>
                </button>
              </form>

              {accountType !== 'admin' && (
                <button
                  type="button"
                  className="text-button account-toggle"
                  disabled={busy}
                  onClick={() => {
                    setSignup(!signup);
                    setError('');
                    setNotice('');
                  }}
                >
                  {signup
                    ? 'Already registered? Sign in'
                    : accountType === 'institution'
                    ? 'New institution? Apply for approval'
                    : 'New here? Create a user account'}
                </button>
              )}
            </>
          )}
        </div>

        <footer>AI assists the analysis. Trusted records determine the result.</footer>
      </section>
    </div>
  );
}

function Verification({health, onChange}) {
  return (
    <>
      <div className="section-heading">
        <div>
          <span className="eyebrow">VERIFY WITH CONFIDENCE</span>
          <h2>Every credential has a story.<br/>Check the evidence.</h2>
          <p>Verify original issued files against their trusted blockchain records. (Maximum 5 files per verification batch)</p>
        </div>
        <div className="heading-mark"><Fingerprint size={65} strokeWidth={1}/></div>
      </div>
      <div className="verify-layout">
        <CertificateUpload api={api} Badge={Badge} Result={Result} onChange={onChange} health={health} samples={sampleItems}/>
        <aside className="verification-aside">
          <section className="panel process-panel">
            <div className="panel-title">
              <div className="square-icon small"><ShieldCheck size={21}/></div>
              <h3>Evidence, in the right order</h3>
            </div>
            <div className="timeline">
              {[
                [FileText, 'Validate the document', 'Check file type, size and readability (max 5 per batch).'],
                [Search, 'Find the registration', 'Look up the certificate ID, not just its hash.'],
                [Building2, 'Check issuer & status', 'Confirm approval and check revocation.'],
                [Fingerprint, 'Compare file integrity', 'Match SHA-256 against the original.']
              ].map(([Icon, title, desc], i) => (
                <div className="timeline-item" key={title}>
                  <span><Icon size={17}/></span>
                  <div>
                    <small>0{i + 1}</small>
                    <h4>{title}</h4>
                    <p>{desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>
          <div className="ai-note">
            <BrainCircuit size={24}/>
            <div>
              <h4>A second perspective, from AI</h4>
              <p>OCR and an advisory Random Forest model flag text anomalies. AI never overrides the verification result.</p>
              <span>ADVISORY ANALYSIS ONLY</span>
            </div>
          </div>
          <div className="hint">
            <CircleHelp size={18}/>
            <p>Scans and re-saved copies may have a different hash. For an exact match, use the original digital file.</p>
          </div>
        </aside>
      </div>
    </>
  );
}

function Result({result: r, autoScroll = true}) {
  const ref = useRef();
  useEffect(() => {
    if (autoScroll) ref.current?.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }, [r, autoScroll]);

  const checks = [
    ['reference_found', 'Registration found on blockchain'],
    ['active', 'Certificate active & not revoked'],
    ['issuer_approved', 'Issuer approved by platform'],
    ['hash_matches', 'Original file matches registered record']
  ];
  const category = r.verification_status || r.category || (r.status === 'verified' ? 'VERIFIED' : (r.status === 'possible_tampering' || r.status === 'tampering_detected') ? 'TAMPERING_DETECTED' : r.status === 'revoked' ? 'REVOKED' : r.status === 'not_verified' ? 'ISSUER_NOT_AUTHORIZED' : r.status === 'unable_to_authenticate' ? 'VERIFICATION_UNAVAILABLE' : r.status === 'invalid_file' ? 'INVALID_FILE' : 'NOT_REGISTERED_OR_INCONCLUSIVE');
  const badgeClass = category === 'VERIFIED' ? 'verified' : (category === 'TAMPERING_DETECTED' || category === 'POSSIBLE_TAMPERING_OR_FILE_MISMATCH') ? 'possible_tampering' : (category === 'REVOKED' || category === 'ISSUER_NOT_AUTHORIZED') ? 'revoked' : category === 'INVALID_FILE' ? 'not_verified' : category === 'VERIFICATION_UNAVAILABLE' ? 'unable_to_authenticate' : 'inconclusive';
  const isHashMatch = r.hash_matches === true;
  const isHashMismatch = r.hash_matches === false;

  return (
    <section ref={ref} className={'panel result-panel result-' + (r.status || 'unknown')} aria-live="polite">
      <div className="result-header">
        <div className="result-icon">{category === 'VERIFIED' ? <ShieldCheck size={32}/> : <AlertTriangle size={32}/>}</div>
        <div style={{flex: 1}}>
          <div style={{display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', marginBottom: '6px'}}>
            <span className="eyebrow">VERIFICATION RESULT</span>
            <Badge status={badgeClass}>{(r.status === 'possible_tampering' || category === 'TAMPERING_DETECTED' || category === 'POSSIBLE_TAMPERING_OR_FILE_MISMATCH') ? 'Possible Tampering or File Mismatch' : (r.label || labels[category] || category)}</Badge>
            {r.reference && <span className="reference-pill mono" style={{background: 'var(--line,#e5ebed)', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 600}}>ID: {r.reference}</span>}
          </div>
          <h2>{(r.status === 'possible_tampering' || category === 'TAMPERING_DETECTED' || category === 'POSSIBLE_TAMPERING_OR_FILE_MISMATCH') ? 'Possible Tampering or File Mismatch' : (r.label || labels[category] || category)}</h2>
          <p className="result-explanation" style={{marginTop: '4px', fontSize: '13px', lineHeight: 1.6}}>{r.message}</p>
        </div>
        <button className="secondary small-button" onClick={() => saveFile('authentra-verification-' + (r.reference || 'report') + '.json', JSON.stringify(r, null, 2))}>
          <Download size={16}/>Save report
        </button>
      </div>

      {r.next_action && (
        <div className="next-action-card" style={{margin: '12px 0', padding: '10px 14px', borderRadius: '7px', background: category === 'VERIFIED' ? '#eef7f2' : '#fdf6e7', borderLeft: `4px solid ${category === 'VERIFIED' ? 'var(--green,#087d6a)' : '#d97706'}`}}>
          <strong style={{display: 'block', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '1px', color: category === 'VERIFIED' ? 'var(--green,#087d6a)' : '#b45309', marginBottom: '2px'}}>Recommended Next Action</strong>
          <span style={{fontSize: '12px', color: '#1f2937'}}>{r.next_action}</span>
        </div>
      )}

      <div className="evidence-summary-grid" style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '10px', margin: '14px 0'}}>
        <div className="evidence-card" style={{background: '#fff', border: '1px solid var(--line,#e5ebed)', borderRadius: '7px', padding: '10px 12px'}}>
          <small style={{display: 'block', color: 'var(--muted,#7b8b90)', fontWeight: 600, textTransform: 'uppercase', fontSize: '10px'}}>Hash Comparison</small>
          <div style={{display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px'}}>
            {isHashMatch ? <Check size={16} color="#087d6a"/> : isHashMismatch ? <X size={16} color="#dc2626"/> : <span>—</span>}
            <strong style={{fontSize: '12px', color: isHashMatch ? '#087d6a' : isHashMismatch ? '#dc2626' : 'inherit'}}>{isHashMatch ? 'Exact Match' : isHashMismatch ? 'Hash Mismatch' : 'Not Compared'}</strong>
          </div>
          <p style={{fontSize: '11px', color: '#6b7280', margin: '4px 0 0'}}>{r.hash_comparison || (isHashMatch ? 'Uploaded file exactly matches on-chain record.' : 'No hash comparison.')}</p>
        </div>

        <div className="evidence-card" style={{background: '#fff', border: '1px solid var(--line,#e5ebed)', borderRadius: '7px', padding: '10px 12px'}}>
          <small style={{display: 'block', color: 'var(--muted,#7b8b90)', fontWeight: 600, textTransform: 'uppercase', fontSize: '10px'}}>Issuing Institution & Status</small>
          <strong style={{display: 'block', fontSize: '12px', marginTop: '4px'}}>{r.issuer_name || (r.issuer ? `Wallet ${r.issuer.slice(0, 10)}…` : 'Not available')}</strong>
          <div style={{display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px', fontSize: '11px'}}>
            <span style={{color: r.issuer_authorized ? '#087d6a' : r.issuer_authorized === false ? '#dc2626' : '#6b7280'}}>
              {r.issuer_authorized ? '● Authorized Issuer' : r.issuer_authorized === false ? '✕ Unauthorized Issuer' : '○ Not Checked'}
            </span>
          </div>
        </div>

        <div className="evidence-card" style={{background: '#fff', border: '1px solid var(--line,#e5ebed)', borderRadius: '7px', padding: '10px 12px'}}>
          <small style={{display: 'block', color: 'var(--muted,#7b8b90)', fontWeight: 600, textTransform: 'uppercase', fontSize: '10px'}}>Blockchain Record Status</small>
          <strong style={{display: 'block', fontSize: '12px', marginTop: '4px'}}>
            {r.blockchain_record_status === 'ACTIVE' ? 'Active On-Chain' : r.blockchain_record_status === 'REVOKED' ? 'Revoked On-Chain' : r.blockchain_record_status === 'ISSUER_UNAUTHORIZED' ? 'Issuer Disabled' : r.blockchain_record_status === 'NOT_FOUND' ? 'Not Found On-Chain' : r.blockchain_record_status || 'Unavailable'}
          </strong>
          {r.transaction_hash && (
            <div style={{marginTop: '4px'}}>
              {r.explorer_url ? <a href={r.explorer_url} target="_blank" rel="noreferrer" style={{color: 'var(--green,#087d6a)', fontSize: '11px', display: 'inline-flex', alignItems: 'center', gap: '3px'}}>Block Explorer <ArrowUpRight size={12}/></a> : <small className="mono" style={{fontSize: '10px', color: '#6b7280'}}>Tx: {r.transaction_hash.slice(0, 10)}…</small>}
            </div>
          )}
        </div>

        <div className="evidence-card" style={{background: '#fff', border: '1px solid var(--line,#e5ebed)', borderRadius: '7px', padding: '10px 12px'}}>
          <small style={{display: 'block', color: 'var(--muted,#7b8b90)', fontWeight: 600, textTransform: 'uppercase', fontSize: '10px'}}>Verification Timestamp</small>
          <strong style={{display: 'block', fontSize: '12px', marginTop: '4px'}}>{fmtTime(r.verified_at || r.created_at)}</strong>
          <small style={{color: '#6b7280', fontSize: '11px'}}>{r.duration_ms != null ? `${(r.duration_ms / 1000).toFixed(2)}s latency` : 'Direct response'}</small>
        </div>
      </div>

      <div className="check-grid">
        {checks.map(([key, label]) => (
          <div key={key}>
            <span role="img" aria-label={r.checks?.[key] === true ? "Passed" : r.checks?.[key] === false ? "Failed" : "Not checked"} className={r.checks?.[key] === true ? 'check-pass' : r.checks?.[key] === false ? 'check-fail' : 'check-skip'}>
              {r.checks?.[key] === true ? <Check size={16}/> : r.checks?.[key] === false ? <X size={16}/> : <span>—</span>}
            </span>{label}
          </div>
        ))}
      </div>

      <div className="extracted-metadata-section" style={{marginTop: '14px', padding: '12px 14px', border: '1px solid var(--line,#e5ebed)', borderRadius: '7px', background: '#fafbfc'}}>
        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', marginBottom: '8px'}}>
          <span style={{fontSize: '11px', fontWeight: 700, letterSpacing: '0.5px', textTransform: 'uppercase', color: '#4b5563'}}>
            Extracted Certificate Metadata <span style={{fontWeight: 400, color: '#9ca3af'}}>(OCR-Extracted)</span>
          </span>
          <span style={{fontSize: '11px', color: '#6b7280'}}>
            Method: {r.extraction_method || 'Direct / OCR'} {r.ocr_confidence != null ? `· ${Math.round(r.ocr_confidence)}% confidence` : ''}
          </span>
        </div>
        <div className="extracted" style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '8px'}}>
          {[
            ['Certificate ID', r.fields?.reference || r.reference],
            ['Recipient Name', r.fields?.name],
            ['Course / Qualification', r.fields?.course],
            ['Issuing Institution', r.fields?.institution || r.issuer_name],
            ['Issue Date', r.fields?.issue_date]
          ].map(([label, val]) => (
            <div key={label} style={{padding: '6px 8px', background: '#fff', borderRadius: '5px', border: '1px solid #f1f3f5'}}>
              <small style={{display: 'block', color: '#9ca3af', fontSize: '10px'}}>{label}</small>
              <strong style={{fontSize: '12px', color: val ? '#111827' : '#9ca3af'}}>{val || 'Not detected'}</strong>
            </div>
          ))}
        </div>
        <p className="muted" style={{marginTop: '6px', fontSize: '10px', color: '#9ca3af'}}>
          Extracted fields are provided for inspection and advisory context. Cryptographic SHA-256 hash matching against the immutable blockchain registry determines authenticity.
        </p>
      </div>

      {r.file_hash && (
        <details style={{marginTop: '10px'}}>
          <summary style={{cursor: 'pointer', fontSize: '12px', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: '4px', color: '#4b5563'}}>
            Cryptographic SHA-256 digests <ChevronRight size={14}/>
          </summary>
          <div className="hash-grid" style={{marginTop: '8px'}}>
            <label>Uploaded file SHA-256 <code>{r.file_hash}</code></label>
            <label>Registered on-chain SHA-256 <code>{r.registered_hash || 'No trusted record available on blockchain'}</code></label>
          </div>
        </details>
      )}

      <div className="result-details" style={{marginTop: '12px'}}>
        <div className="advisory">
          <BrainCircuit size={21}/>
          <div>
            <small>SEPARATE AI FINDING (ADVISORY ONLY)</small>
            <strong>{r.ai?.label || 'AI analysis complete'}</strong>
            <p>{r.ai?.scope || 'AI does not determine authenticity.'}{r.ai?.score != null ? ` Model anomaly score: ${(r.ai.score * 100).toFixed(0)}%.` : ''}</p>
          </div>
        </div>
        <div className="processing">
          <Clock3 size={18}/>
          <span>{r.duration_ms != null ? `${(r.duration_ms / 1000).toFixed(2)}s processing time` : 'File validation stopped'}<small>{r.extraction_method || 'No text extraction performed'}</small></span>
        </div>
      </div>
      {r.warnings?.map(w => <p className="warning-line" key={w} style={{marginTop: '8px'}}><AlertTriangle size={15}/>{w}</p>)}
    </section>
  );
}

function HistoryPage({data}) {
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const rows = data.filter(r => (r.reference || '').toLowerCase().includes(query.toLowerCase()) && (status === 'all' || r.status === status));
  function exportCsv() {
    saveFile('authentra-history.csv', 'Certificate ID,Result,Duration ms,Time UTC\n' + rows.map(r => [r.reference || '', labels[r.status], r.duration_ms, r.created_at].map(v => '"' + String(v).replaceAll('"', '""') + '"').join(',')).join('\n'), 'text/csv');
  }
  return (
    <>
      <PageHeading eyebrow="YOUR PRIVATE ACTIVITY" title="Verification history" text="A secure record of your personal certificate checks. Private to your account."/>
      <section className="panel">
        <div className="table-toolbar">
          <div className="search-field">
            <Search size={17}/>
            <input aria-label="Search history" placeholder="Search certificate ID" value={query} onChange={e => setQuery(e.target.value)}/>
          </div>
          <select aria-label="Filter by result" value={status} onChange={e => setStatus(e.target.value)}>
            <option value="all">All results</option>
            {Object.entries(labels).map(([v, l]) => <option value={v} key={v}>{l}</option>)}
          </select>
          <button className="secondary" onClick={exportCsv}><Download size={16}/>Export CSV</button>
        </div>
        <HistoryTable rows={rows}/>
      </section>
    </>
  );
}

function HistoryTable({rows}) {
  return rows.length ? (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Certificate ID</th>
            <th>Verification result</th>
            <th>Processing time</th>
            <th>Checked on</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.id}>
              <td><div className="cell-icon"><FileText size={17}/><strong>{r.reference || 'ID unavailable'}</strong></div></td>
              <td><Badge status={r.status}/></td>
              <td>{r.duration_ms != null ? (r.duration_ms / 1000).toFixed(2) + 's' : '—'}</td>
              <td>{fmtTime(r.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <Empty icon={History} title="No verification records" text="Run a certificate check to start building your history."/>
  );
}

function PageHeading({eyebrow, title, text, children}) {
  return (
    <div className="page-heading">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h2>{title}</h2>
        <p>{text}</p>
      </div>
      {children}
    </div>
  );
}

function Empty({icon: Icon = FileText, title, text}) {
  return <div className="empty"><Icon size={30}/><h3>{title}</h3><p>{text}</p></div>;
}

// ==============================================================================
// ROLE 2: INSTITUTION ADMIN VIEWS
// ==============================================================================

function InstitutionDashboardView({user, dashboard, setPage}) {
  return (
    <>
      <div className="dashboard-hero">
        <div className="dashboard-hero-content">
          <div>
            <span className="eyebrow light">INSTITUTION WORKSPACE</span>
            <h2>{user.name}</h2>
            <p>
              Accredited institutional credential authority. Register official certificates, manage on-chain status, and review issuance outcomes.
            </p>
            <div className="dashboard-hero-meta">
              <span className="dashboard-meta-chip">
                <Building2 size={13}/> Domain: <strong>{user.institution_domain || 'Accredited (.edu / .ac.in)'}</strong>
              </span>
              <span className="dashboard-meta-chip">
                <ShieldCheck size={13}/> Signer Wallet: <code>{user.wallet || 'Not configured'}</code>
              </span>
              <span className="dashboard-meta-chip">
                Status: <Badge status={dashboard?.issuer_approved ? 'verified' : 'inconclusive'}>{dashboard?.issuer_approved ? 'APPROVED ISSUER' : 'PENDING APPROVAL'}</Badge>
              </span>
            </div>
          </div>
          <button className="primary" onClick={() => setPage('register')} style={{marginTop: '10px'}}>
            <UploadCloud size={16}/> Bulk Register Certificates
          </button>
        </div>
      </div>

      <div className="stat-grid">
        {[
          [Layers3, 'Issued Certificates', dashboard?.registered ?? 0, 'On-chain registered records'],
          [ShieldCheck, 'Contract Authorization', dashboard?.issuer_approved ? 'Active' : 'Pending', 'Smart contract signer status'],
          [ScanLine, 'Verifications Received', dashboard?.total ?? 0, 'Verification checks on your records'],
          [Clock3, 'Average Speed', dashboard?.mean_ms != null ? (dashboard.mean_ms / 1000).toFixed(2) + 's' : '—', 'Processing latency']
        ].map(([Icon, label, value, caption]) => (
          <div className="stat-card" key={label}>
            <div><span>{label}</span><Icon size={18}/></div>
            <strong>{value}</strong>
            <small>{caption}</small>
          </div>
        ))}
      </div>

      <section className="panel recent-panel">
        <div className="panel-title">
          <h3>Recently Registered Certificates</h3>
          <button className="text-button" onClick={() => setPage('registry')}>
            View full registry <ArrowUpRight size={15}/>
          </button>
        </div>
        {dashboard?.recent_registrations?.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Certificate ID</th>
                  <th>Registered Date</th>
                  <th>Issuer Name</th>
                  <th>Transaction Reference</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.recent_registrations.map(r => (
                  <tr key={r.id || r.reference}>
                    <td><strong>{r.reference}</strong></td>
                    <td>{fmtTime(r.created_at)}</td>
                    <td>{r.issuer_name || user.name}</td>
                    <td><span className="mono">{r.transaction_hash ? r.transaction_hash.slice(0, 16) + '…' : '—'}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty icon={Layers3} title="No credentials registered yet" text="Use the Register Certificates portal to issue your first batch of certificates on the blockchain."/>
        )}
      </section>
    </>
  );
}

function RegisterPage({user, onChange}) {
  return (
    <>
      <PageHeading
        eyebrow="BATCH CREDENTIAL ISSUANCE"
        title="Register Certificates on Blockchain"
        text="Upload certificates in bulk (up to 100 files). Automated OCR extracts candidate IDs, while cryptographic SHA-256 hashes are committed to the smart contract."
      />
      <div className="verify-layout">
        <CertificateUpload mode="register" api={api} Badge={Badge} Result={Result} onChange={onChange}/>
        <aside className="verification-aside">
          <section className="panel process-panel">
            <div className="panel-title">
              <div className="square-icon small"><ShieldCheck size={21}/></div>
              <h3>Institutional Registration Protocol</h3>
            </div>
            <div className="timeline">
              {[
                [FileText, 'Document Validation', 'Files are checked for supported format (PDF, PNG, JPEG) and size.'],
                [BrainCircuit, 'OCR Metadata Extraction', 'Certificate references and recipient fields are extracted for review.'],
                [Fingerprint, 'Cryptographic Hashing', 'Unique SHA-256 digest is generated from raw document bytes.'],
                [Layers3, 'Blockchain Commitment', 'Signed by authorized institution wallet on the smart contract registry.']
              ].map(([Icon, title, desc], i) => (
                <div className="timeline-item" key={title}>
                  <span><Icon size={17}/></span>
                  <div>
                    <small>0{i + 1}</small>
                    <h4>{title}</h4>
                    <p>{desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>
          <div className="hint">
            <LockKeyhole size={18}/>
            <p>Registration operations are strictly restricted to approved institutions whose wallet is configured in the smart contract.</p>
          </div>
        </aside>
      </div>
    </>
  );
}

function RegistryPage({user, onChange}) {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [revokeId, setRevokeId] = useState(null);
  const [query, setQuery] = useState('');

  async function load() {
    try {
      setRows(await api('/certificates'));
    } catch(e) {
      setError(e.message);
    }
  }

  useEffect(() => { load(); }, []);

  async function revoke() {
    setBusy(true);
    try {
      await api('/certificates/' + encodeURIComponent(revokeId) + '/revoke', {method: 'POST'});
      setRevokeId(null);
      await load();
      onChange();
    } catch(e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const filtered = rows.filter(r => (r.reference || '').toLowerCase().includes(query.toLowerCase()));

  return (
    <>
      <PageHeading eyebrow="ISSUER WORKSPACE" title="Certificate Registry" text="Manage credentials issued by your institution. Revoke compromised or superseded credentials permanently."/>
      <ErrorMessage message={error}/>
      <div className="verify-layout" style={{marginBottom: '28px'}}>
        <CertificateUpload mode="register" api={api} Badge={Badge} Result={Result} onChange={() => { load(); onChange?.(); }}/>
      </div>
      <section className="panel">
        <div className="panel-title">
          <h3>Issued Certificates</h3>
          <span className="count-pill">{filtered.length} records</span>
          <div className="search-field" style={{maxWidth: '260px', marginLeft: 'auto'}}>
            <Search size={16}/>
            <input placeholder="Search certificate ID" value={query} onChange={e => setQuery(e.target.value)}/>
          </div>
        </div>
        {filtered.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Certificate ID</th>
                  <th>Status</th>
                  <th>Issuer</th>
                  <th>Transaction Reference</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(r => (
                  <tr key={r.reference}>
                    <td>
                      <strong>{r.reference}</strong>
                    </td>
                    <td>
                      <Badge status={r.revoked ? 'revoked' : r.issuer_approved ? 'verified' : 'not_verified'}>
                        {r.revoked ? 'Revoked' : r.issuer_approved ? 'Active' : 'Issuer disabled'}
                      </Badge>
                    </td>
                    <td>{r.issuer_name}</td>
                    <td>
                      {r.explorer_url ? (
                        <a href={r.explorer_url} target="_blank" rel="noreferrer" className="mono" style={{color: 'var(--green,#087d6a)', display: 'inline-flex', alignItems: 'center', gap: '3px'}}>
                          {r.transaction_hash?.slice(0, 16)}… <ArrowUpRight size={12}/>
                        </a>
                      ) : (
                        <span className="mono">{r.transaction_hash ? r.transaction_hash.slice(0, 16) + '…' : '—'}</span>
                      )}
                    </td>
                    <td>
                      <button className="danger-text" disabled={busy || r.revoked} onClick={() => setRevokeId(r.reference)}>
                        <Ban size={15}/>{r.revoked ? 'Revoked' : 'Revoke'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="Your registry starts here" text="Register an original certificate to create a trusted on-chain record."/>
        )}
      </section>

      {revokeId && (
        <div className="modal-backdrop">
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="revoke-title">
            <div className="square-icon warning"><Ban size={25}/></div>
            <h2 id="revoke-title">Revoke {revokeId}?</h2>
            <p>
              This permanently marks the blockchain record as revoked. Future verification checks will show Revoked. The action is recorded on the blockchain and audit logs.
            </p>
            <div className="modal-actions">
              <button className="secondary" disabled={busy} onClick={() => setRevokeId(null)}>Cancel</button>
              <button className="danger" disabled={busy} onClick={revoke}>
                {busy ? <Spinner/> : 'Revoke Certificate'}
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}

// ==============================================================================
// ROLE 3: SYSTEM ADMIN VIEWS (STRICTLY NO UPLOAD/REGISTER INTERFACES)
// ==============================================================================

function AdminDashboardView({dashboard, setPage}) {
  return (
    <>
      <div className="dashboard-hero">
        <div className="dashboard-hero-content">
          <div>
            <span className="eyebrow light">PLATFORM GOVERNANCE & OVERSIGHT</span>
            <h2>System Administration Console</h2>
            <p>
              Platform governance, institutional access authorization, on-chain smart contract issuer management, and immutable system audit logging.
            </p>
            <div className="dashboard-hero-meta">
              <span className="dashboard-meta-chip">
                <ShieldCheck size={13}/> Role: <strong>SYSTEM_ADMIN</strong>
              </span>
              <span className="dashboard-meta-chip">
                <LockKeyhole size={13}/> Separation of Duties: <strong>Enforced</strong>
              </span>
              <span className="dashboard-meta-chip">
                <Building2 size={13}/> Approved Issuers: <strong>{dashboard?.approved_institutions ?? 0}</strong>
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="governance-notice" role="alert">
        <AlertTriangle size={18}/>
        <div>
          <strong>SEPARATION OF DUTIES ENFORCED:</strong> System Administrators possess governance oversight and institution verification authority. Certificate uploading, batch registration, and blockchain issuance are strictly disabled for administrator accounts.
        </div>
      </div>

      <div className="stat-grid">
        {[
          [Building2, 'Approved Institutions', dashboard?.approved_institutions ?? 0, 'Authorized smart contract issuers'],
          [Clock3, 'Pending Applications', dashboard?.pending_institutions ?? 0, 'Awaiting administrator review'],
          [Layers3, 'Registered Certificates', dashboard?.registered ?? 0, 'Platform-wide credentials'],
          [ScanLine, 'Total Verifications', dashboard?.total ?? 0, 'Platform-wide checks conducted']
        ].map(([Icon, label, value, caption]) => (
          <div className="stat-card" key={label}>
            <div><span>{label}</span><Icon size={18}/></div>
            <strong>{value}</strong>
            <small>{caption}</small>
          </div>
        ))}
      </div>

      <div className="action-queue-grid">
        {dashboard?.pending_institutions > 0 && (
          <div className="action-queue-card" style={{borderLeft: '4px solid #ca8a04', background: '#fffdf5'}}>
            <h4>Action Required: Pending Institution Approvals</h4>
            <p>
              There are <strong>{dashboard.pending_institutions}</strong> institution applications awaiting administrative review and blockchain signer authorization.
            </p>
            <div className="actions">
              <button className="primary" onClick={() => setPage('institutions')}>
                Review Institutions <ArrowRight size={15}/>
              </button>
            </div>
          </div>
        )}
        <div className="action-queue-card">
          <h4>Institution Governance</h4>
          <p>Review accredited institution applications, approve or revoke access, and manage authorized smart contract signers.</p>
          <div className="actions">
            <button className="secondary" onClick={() => setPage('institutions')}>
              <Building2 size={14}/> Manage Institutions
            </button>
          </div>
        </div>
        <div className="action-queue-card">
          <h4>Issuer History & Registrations</h4>
          <p>Inspect certificate registrations, on-chain transaction hashes, and status changes per accredited institution.</p>
          <div className="actions">
            <button className="secondary" onClick={() => setPage('admin_issuer_history')}>
              <Layers3 size={14}/> Inspect Issuer History
            </button>
          </div>
        </div>
        <div className="action-queue-card">
          <h4>User Verification History</h4>
          <p>Search platform verification outcomes, timestamps, user identifiers, and failure reasons with date and status filters.</p>
          <div className="actions">
            <button className="secondary" onClick={() => setPage('admin_verifications')}>
              <Search size={14}/> Search User History
            </button>
          </div>
        </div>
      </div>

      <section className="panel recent-panel">
        <div className="panel-title">
          <h3>Recent Administrative & Issuer Events</h3>
          <button className="text-button" onClick={() => setPage('admin_audit')}>
            View full audit trail <ArrowUpRight size={15}/>
          </button>
        </div>
        {dashboard?.recent_audits?.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Action</th>
                  <th>Actor</th>
                  <th>Reference</th>
                  <th>Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.recent_audits.map(a => (
                  <tr key={a.id}>
                    <td><strong className="capitalize">{a.action?.replaceAll('_', ' ')}</strong></td>
                    <td>{a.actor || a.actor_email || 'System'}</td>
                    <td><span className="mono">{a.reference || '—'}</span></td>
                    <td>{fmtTime(a.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty icon={Activity} title="No audit events yet" text="Privileged administrative actions will be recorded here."/>
        )}
      </section>
    </>
  );
}

function AdminCertificatesPage() {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');

  useEffect(() => {
    api('/admin/certificates').then(setRows).catch(e => setError(e.message));
  }, []);

  const filtered = rows.filter(r => {
    const matchQ = (r.reference || '').toLowerCase().includes(query.toLowerCase()) ||
                   (r.issuer_name || '').toLowerCase().includes(query.toLowerCase());
    const matchS = status === 'all' || (status === 'revoked' ? r.revoked : !r.revoked);
    return matchQ && matchS;
  });

  function exportCsv() {
    saveFile(
      'authentra-admin-certificates.csv',
      'Certificate ID,Issuer Name,Issuer Wallet,Registered Hash,Status,Tx Hash,Created At\n' +
      filtered.map(r => [r.reference, r.issuer_name, r.issuer_wallet, r.file_hash, r.revoked ? 'REVOKED' : 'ACTIVE', r.transaction_hash, r.created_at].map(v => '"' + String(v || '').replaceAll('"', '""') + '"').join(',')).join('\n'),
      'text/csv'
    );
  }

  return (
    <>
      <PageHeading
        eyebrow="SYSTEM OVERSIGHT"
        title="Certificate Oversight"
        text="Platform-wide inspection of credentials registered across all institutions. System Administrators have read-only oversight to inspect cryptographic digests and transaction references."
      />
      <ErrorMessage message={error}/>
      <section className="panel">
        <div className="table-toolbar">
          <div className="search-field">
            <Search size={17}/>
            <input placeholder="Search certificate ID or institution name" value={query} onChange={e => setQuery(e.target.value)}/>
          </div>
          <select value={status} onChange={e => setStatus(e.target.value)}>
            <option value="all">All statuses</option>
            <option value="active">Active credentials</option>
            <option value="revoked">Revoked credentials</option>
          </select>
          <button className="secondary" onClick={exportCsv}><Download size={16}/>Export CSV</button>
        </div>
        {filtered.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Certificate ID</th>
                  <th>Issuing Institution</th>
                  <th>Issuer Wallet</th>
                  <th>Status</th>
                  <th>On-Chain Transaction Reference</th>
                  <th>Registered On</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(r => (
                  <tr key={r.id || r.reference}>
                    <td><strong className="mono">{r.reference}</strong></td>
                    <td>{r.issuer_name}</td>
                    <td><code style={{fontSize: '10px'}}>{r.issuer_wallet}</code></td>
                    <td>
                      <Badge status={r.revoked ? 'revoked' : 'verified'}>
                        {r.revoked ? 'REVOKED' : 'ACTIVE'}
                      </Badge>
                    </td>
                    <td>
                      {r.explorer_url ? (
                        <a href={r.explorer_url} target="_blank" rel="noreferrer" className="mono" style={{color: 'var(--green,#087d6a)', display: 'inline-flex', alignItems: 'center', gap: '3px'}}>
                          {r.transaction_hash?.slice(0, 16)}… <ArrowUpRight size={12}/>
                        </a>
                      ) : (
                        <span className="mono">{r.transaction_hash ? r.transaction_hash.slice(0, 16) + '…' : '—'}</span>
                      )}
                    </td>
                    <td>{fmtTime(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty icon={Layers3} title="No certificate records found" text="No registered certificates match your query."/>
        )}
      </section>
    </>
  );
}

function AdminVerificationsPage() {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [result, setResult] = useState('all');
  const [userId, setUserId] = useState('');
  const [reference, setReference] = useState('');

  async function fetchLogs() {
    setBusy(true);
    setError('');
    try {
      const params = new URLSearchParams();
      if (dateFrom) params.set('date_from', dateFrom);
      if (dateTo) params.set('date_to', dateTo);
      if (result && result !== 'all') params.set('result', result);
      if (userId.trim()) params.set('user_id', userId.trim());
      if (reference.trim()) params.set('reference', reference.trim());
      const qs = params.toString() ? '?' + params.toString() : '';
      const data = await api('/admin/verifications' + qs);
      setRows(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    fetchLogs();
  }, []);

  function handleFilterSubmit(e) {
    e.preventDefault();
    fetchLogs();
  }

  function handleReset() {
    setDateFrom('');
    setDateTo('');
    setResult('all');
    setUserId('');
    setReference('');
    api('/admin/verifications').then(setRows).catch(e => setError(e.message));
  }

  function exportCsv() {
    saveFile(
      'authentra-user-verification-history.csv',
      'User Identifier,Verification Timestamp,Certificate Reference,Verification Result,Issuer Identity,Processing Outcome,Transaction Reference,Failure or Inconclusive Reason\n' +
      rows.map(r => [
        r.user_identifier,
        r.created_at,
        r.reference || '',
        labels[r.status] || r.status,
        r.issuer_name || r.issuer || '',
        r.processing_outcome || r.category || r.status,
        r.transaction_hash || '',
        r.failure_reason || r.message || ''
      ].map(v => '"' + String(v || '').replaceAll('"', '""') + '"').join(',')).join('\n'),
      'text/csv'
    );
  }

  return (
    <>
      <PageHeading
        eyebrow="AUDIT & COMPLIANCE"
        title="User Verification History"
        text="Search and inspect platform-wide verification history, issuer identities, processing outcomes, and blockchain references under permission-controlled governance. Certificate file contents remain private."
      />
      <ErrorMessage message={error}/>
      <section className="panel">
        <form className="history-filter-bar" onSubmit={handleFilterSubmit}>
          <div className="history-filter-group">
            <label>From</label>
            <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)}/>
          </div>
          <div className="history-filter-group">
            <label>To</label>
            <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)}/>
          </div>
          <div className="history-filter-group">
            <label>Result</label>
            <select value={result} onChange={e => setResult(e.target.value)}>
              <option value="all">All verification results</option>
              <option value="VERIFIED">Verified (Active on Blockchain)</option>
              <option value="POSSIBLE_TAMPERING_OR_FILE_MISMATCH">Possible Tampering / Mismatch</option>
              <option value="NOT_REGISTERED_OR_INCONCLUSIVE">Not Registered / Inconclusive</option>
              <option value="REVOKED">Revoked Certificate</option>
              <option value="INVALID_FILE">Invalid Document / Format</option>
              <option value="ISSUER_NOT_AUTHORIZED">Issuer Not Authorized</option>
              <option value="VERIFICATION_UNAVAILABLE">Service Unavailable</option>
            </select>
          </div>
          <div className="history-filter-group" style={{flex: 1, minWidth: '130px'}}>
            <label>User ID / Email</label>
            <input type="text" placeholder="Search user ID or email" value={userId} onChange={e => setUserId(e.target.value)}/>
          </div>
          <div className="history-filter-group" style={{flex: 1, minWidth: '130px'}}>
            <label>Certificate ID</label>
            <input type="text" placeholder="Search certificate ID" value={reference} onChange={e => setReference(e.target.value)}/>
          </div>
          <div style={{display: 'flex', gap: '8px', alignItems: 'flex-end'}}>
            <button type="submit" className="primary" disabled={busy} style={{height: '36px', minHeight: '36px'}}>
              {busy ? <Spinner/> : <Search size={14}/>} Apply Filters
            </button>
            <button type="button" className="secondary" onClick={handleReset} disabled={busy} style={{height: '36px', minHeight: '36px'}}>
              Reset
            </button>
            <button type="button" className="secondary" onClick={exportCsv} disabled={!rows.length} style={{height: '36px', minHeight: '36px'}}>
              <Download size={14}/> Export CSV
            </button>
          </div>
        </form>

        <div style={{padding: '12px 20px', background: '#f8fafc', borderBottom: '1px solid var(--line)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '11px', color: '#64748b'}}>
          <span>Showing <strong>{rows.length}</strong> matching verification events</span>
          <span style={{display: 'flex', alignItems: 'center', gap: '6px'}}><ShieldCheck size={14} style={{color: 'var(--green)'}}/> Privacy Protected · Off-chain raw bytes and private keys are never exposed</span>
        </div>

        {rows.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>User Identifier</th>
                  <th>Verification Timestamp</th>
                  <th>Certificate Reference</th>
                  <th>Verification Result</th>
                  <th>Issuer Identity</th>
                  <th>Processing Outcome</th>
                  <th>Blockchain Tx Reference</th>
                  <th>Failure / Inconclusive Reason</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.id}>
                    <td><strong>{r.user_identifier}</strong></td>
                    <td>{fmtTime(r.created_at)}</td>
                    <td><strong className="mono">{r.reference || '—'}</strong></td>
                    <td><Badge status={r.status}/></td>
                    <td>
                      <div>
                        <strong>{r.issuer_name || '—'}</strong>
                        {r.issuer && <code style={{display: 'block', fontSize: '9px', color: '#64748b'}}>{r.issuer.slice(0, 8)}…{r.issuer.slice(-6)}</code>}
                      </div>
                    </td>
                    <td>
                      <span className="mono" style={{fontSize: '10px'}}>{r.processing_outcome || r.category || r.status}</span>
                    </td>
                    <td>
                      {r.transaction_hash ? (
                        <a href={r.explorer_url} target="_blank" rel="noreferrer" className="mono" style={{color: 'var(--green,#087d6a)', display: 'inline-flex', alignItems: 'center', gap: '3px'}}>
                          {r.transaction_hash.slice(0, 14)}… <ArrowUpRight size={11}/>
                        </a>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td style={{maxWidth: '240px', fontSize: '11px', overflowWrap: 'anywhere'}}>
                      {r.failure_reason || r.message || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty icon={Search} title="No verification records found" text="Try adjusting your filter criteria to locate verification events."/>
        )}
      </section>
    </>
  );
}

function AdminIssuerHistoryPage({initialId}) {
  const [institutions, setInstitutions] = useState([]);
  const [selectedId, setSelectedId] = useState(initialId || '');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api('/institutions').then(list => {
      setInstitutions(list);
      if (!selectedId && list.length > 0) {
        setSelectedId(list[0].id);
      }
    }).catch(e => setError(e.message));
  }, []);

  useEffect(() => {
    if (initialId) setSelectedId(initialId);
  }, [initialId]);

  useEffect(() => {
    if (!selectedId) return;
    setLoading(true);
    setError('');
    api(`/admin/institutions/${selectedId}/history`)
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [selectedId]);

  const inst = data?.institution;
  const registrations = data?.registrations || [];
  const auditEvents = data?.audit_events || [];

  return (
    <>
      <PageHeading
        eyebrow="INSTITUTION OVERSIGHT"
        title="Issuer History & Audit Records"
        text="Inspect an individual institution's credentials lifecycle, smart contract authorization status, submitted registrations, and cryptographically recorded audit trail."
      />
      <ErrorMessage message={error}/>

      <section className="panel" style={{padding: '16px 20px', display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap'}}>
        <label style={{display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '10px', fontSize: '12px', fontWeight: 600, color: 'var(--dark)'}}>
          <Building2 size={18} style={{color: 'var(--green)'}}/>
          Select Institution:
          <select
            value={selectedId}
            onChange={e => setSelectedId(e.target.value)}
            style={{minWidth: '280px', fontWeight: 500}}
          >
            {institutions.map(i => (
              <option key={i.id} value={i.id}>
                {i.name} ({i.approval_status}) — {i.institution_reference || i.email}
              </option>
            ))}
          </select>
        </label>
        {loading && <Spinner/>}
      </section>

      {inst && (
        <>
          <section className="panel">
            <div className="issuer-profile-card">
              <div>
                <span className="eyebrow">INSTITUTION IDENTITY</span>
                <h2 style={{fontSize: '22px', margin: '6px 0 12px', color: 'var(--dark)'}}>{inst.name}</h2>
                <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px', fontSize: '12px'}}>
                  <div>
                    <span style={{color: '#64748b', fontSize: '10px', display: 'block', textTransform: 'uppercase'}}>Official Email</span>
                    <strong>{inst.email}</strong>
                  </div>
                  <div>
                    <span style={{color: '#64748b', fontSize: '10px', display: 'block', textTransform: 'uppercase'}}>Institutional Domain</span>
                    <strong>{inst.institution_domain || inst.email?.split('@')[1] || '—'}</strong>
                  </div>
                  <div>
                    <span style={{color: '#64748b', fontSize: '10px', display: 'block', textTransform: 'uppercase'}}>Registration Identifier</span>
                    <strong className="mono">{inst.institution_reference || '—'}</strong>
                  </div>
                  <div>
                    <span style={{color: '#64748b', fontSize: '10px', display: 'block', textTransform: 'uppercase'}}>Application Date</span>
                    <span>{fmtTime(inst.created_at)}</span>
                  </div>
                </div>
                <div style={{marginTop: '14px'}}>
                  <span style={{color: '#64748b', fontSize: '10px', display: 'block', textTransform: 'uppercase', marginBottom: '3px'}}>Authorized Ethereum Wallet</span>
                  <code style={{fontSize: '11px', background: '#f1f5f9', padding: '6px 10px', borderRadius: '5px', display: 'inline-block'}}>{inst.wallet || '—'}</code>
                </div>
              </div>

              <div style={{background: '#f8fafc', padding: '18px', borderRadius: '8px', border: '1px solid #e2e8f0', display: 'flex', flexDirection: 'column', gap: '12px'}}>
                <span className="eyebrow">AUTHORIZATION STATUS</span>
                <div style={{display: 'flex', flexDirection: 'column', gap: '8px'}}>
                  <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                    <span style={{fontSize: '11px', color: '#64748b'}}>Governance State:</span>
                    <Badge status={inst.approval_status === 'APPROVED' ? 'verified' : inst.approval_status === 'PENDING_APPROVAL' ? 'pending' : inst.approval_status === 'SUSPENDED' ? 'suspended' : 'revoked'}>
                      {inst.approval_status}
                    </Badge>
                  </div>
                  <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                    <span style={{fontSize: '11px', color: '#64748b'}}>Smart Contract Status:</span>
                    {inst.onchain_approved ? (
                      <span className="badge onchain"><Layers3 size={11}/> Approved on Chain</span>
                    ) : (
                      <span className="badge offchain"><X size={11}/> Not Authorized on Chain</span>
                    )}
                  </div>
                </div>
                <div className="institution-notes-box" style={{margin: '6px 0 0'}}>
                  <strong>Review Notes / Policy Reason</strong>
                  <p style={{margin: 0, fontSize: '11px'}}>{inst.review_notes || 'No review notes on file.'}</p>
                </div>
              </div>
            </div>
          </section>

          {/* Submitted Certificate Registrations */}
          <section className="panel">
            <div className="panel-title">
              <Layers3 size={20} style={{color: 'var(--green)'}}/>
              <div>
                <h3>Submitted Certificate Registrations</h3>
                <p>On-chain certificate registrations executed by {inst.name}. Registrations are verified directly against the smart contract state.</p>
              </div>
              <span className="count-pill">{registrations.length} total</span>
            </div>
            {registrations.length ? (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Certificate Reference</th>
                      <th>Registration Timestamp</th>
                      <th>Recipient / Course</th>
                      <th>Verification Status</th>
                      <th>Lifecycle State</th>
                      <th>Blockchain Transaction</th>
                    </tr>
                  </thead>
                  <tbody>
                    {registrations.map(r => (
                      <tr key={r.reference}>
                        <td><strong className="mono">{r.reference}</strong></td>
                        <td>{fmtTime(r.created_at || r.registered_at)}</td>
                        <td>
                          <div>
                            <strong>{r.metadata?.recipient_name || '—'}</strong>
                            <span style={{display: 'block', fontSize: '10px', color: '#64748b'}}>{r.metadata?.course || '—'}</span>
                          </div>
                        </td>
                        <td>
                          {r.on_chain_verified ? (
                            <span className="badge onchain"><ShieldCheck size={11}/> ON-CHAIN VERIFIED</span>
                          ) : (
                            <span className="badge inconclusive"><AlertTriangle size={11}/> UNVERIFIED</span>
                          )}
                        </td>
                        <td>
                          <Badge status={r.revoked ? 'revoked' : 'verified'}>
                            {r.revoked ? 'REVOKED' : 'ACTIVE'}
                          </Badge>
                        </td>
                        <td>
                          {r.transaction_hash ? (
                            <a href={r.explorer_url} target="_blank" rel="noreferrer" className="mono" style={{color: 'var(--green,#087d6a)', display: 'inline-flex', alignItems: 'center', gap: '3px'}}>
                              {r.transaction_hash.slice(0, 16)}… <ArrowUpRight size={11}/>
                            </a>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty icon={Layers3} title="No certificate registrations found" text="This institution has not yet registered any certificates on the blockchain."/>
            )}
          </section>

          {/* Revocations, Status Changes, and Relevant Audit Events */}
          <section className="panel">
            <div className="panel-title">
              <ShieldCheck size={20} style={{color: 'var(--green)'}}/>
              <div>
                <h3>Revocations, Status Changes & Relevant Audit Events</h3>
                <p>Cryptographically logged administrative decisions and smart contract state changes for this institution.</p>
              </div>
              <span className="count-pill">{auditEvents.length} events</span>
            </div>
            {auditEvents.length ? (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Action</th>
                      <th>Classification</th>
                      <th>Actor</th>
                      <th>Target Reference</th>
                      <th>Transaction Reference</th>
                      <th>Administrative Reason / Details</th>
                      <th>Timestamp</th>
                    </tr>
                  </thead>
                  <tbody>
                    {auditEvents.map(a => (
                      <tr key={a.id}>
                        <td><strong className="capitalize">{a.action?.replaceAll('_', ' ')}</strong></td>
                        <td>
                          {a.is_onchain ? (
                            <span className="badge onchain"><Layers3 size={11}/> On-Chain Tx</span>
                          ) : (
                            <span className="badge offchain"><ShieldCheck size={11}/> Off-Chain Audit</span>
                          )}
                        </td>
                        <td>{a.actor_name || a.actor_email || (a.user_id ? 'User #' + a.user_id : 'System')}</td>
                        <td><span className="mono">{a.reference || '—'}</span></td>
                        <td>
                          {a.transaction_hash ? (
                            <a href={a.explorer_url} target="_blank" rel="noreferrer" className="mono" style={{color: 'var(--green)', display: 'inline-flex', alignItems: 'center', gap: '3px'}}>
                              {a.transaction_hash.slice(0, 14)}… <ArrowUpRight size={11}/>
                            </a>
                          ) : (
                            <span className="muted" style={{fontSize: '10px'}}>— (Off-Chain Event)</span>
                          )}
                        </td>
                        <td style={{maxWidth: '260px', fontSize: '11px', overflowWrap: 'anywhere'}}>{a.details || '—'}</td>
                        <td>{fmtTime(a.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty icon={Activity} title="No audit events found" text="No administrative or lifecycle events have been recorded for this institution."/>
            )}
          </section>
        </>
      )}
    </>
  );
}

function AdminAuditPage() {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [actionFilter, setActionFilter] = useState('all');

  useEffect(() => {
    api('/admin/audit').then(setRows).catch(e => setError(e.message));
  }, []);

  const filtered = rows.filter(r => {
    const matchQ = (r.actor || '').toLowerCase().includes(query.toLowerCase()) ||
                   (r.reference || '').toLowerCase().includes(query.toLowerCase()) ||
                   (r.details || '').toLowerCase().includes(query.toLowerCase());
    const matchA = actionFilter === 'all' || r.action === actionFilter;
    return matchQ && matchA;
  });

  const actions = Array.from(new Set(rows.map(r => r.action)));

  function exportCsv() {
    saveFile(
      'authentra-system-audit.csv',
      'Action,Actor,User ID,Reference,Tx Hash,IP Address,Details,Created At\n' +
      filtered.map(r => [r.action, r.actor, r.user_id, r.reference, r.transaction_hash, r.ip_address, r.details, r.created_at].map(v => '"' + String(v || '').replaceAll('"', '""') + '"').join(',')).join('\n'),
      'text/csv'
    );
  }

  return (
    <>
      <PageHeading
        eyebrow="SECURITY & COMPLIANCE"
        title="System Audit Trail"
        text="Cryptographically recorded audit history of administrator and issuer actions, smart contract authorizations, and status changes."
      />
      <ErrorMessage message={error}/>
      <section className="panel">
        <div className="table-toolbar">
          <div className="search-field">
            <Search size={17}/>
            <input placeholder="Search actor, reference, or details" value={query} onChange={e => setQuery(e.target.value)}/>
          </div>
          <select value={actionFilter} onChange={e => setActionFilter(e.target.value)}>
            <option value="all">All actions</option>
            {actions.map(a => <option value={a} key={a}>{a.replaceAll('_', ' ')}</option>)}
          </select>
          <button className="secondary" onClick={exportCsv}><Download size={16}/>Export CSV</button>
        </div>
        {filtered.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Action</th>
                  <th>Classification</th>
                  <th>Actor</th>
                  <th>Reference</th>
                  <th>Tx Hash</th>
                  <th>Client IP</th>
                  <th>Details</th>
                  <th>Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(r => (
                  <tr key={r.id}>
                    <td><strong className="capitalize">{r.action?.replaceAll('_', ' ')}</strong></td>
                    <td>
                      {r.transaction_hash ? (
                        <span className="badge onchain"><Layers3 size={11}/> On-Chain Tx</span>
                      ) : (
                        <span className="badge offchain"><ShieldCheck size={11}/> Off-Chain Audit</span>
                      )}
                    </td>
                    <td>{r.actor || (r.user_id ? `User #${r.user_id}` : 'System')}</td>
                    <td><span className="mono">{r.reference || '—'}</span></td>
                    <td>
                      {r.transaction_hash ? (
                        <span className="mono">{r.transaction_hash.slice(0, 14)}…</span>
                      ) : (
                        <span className="muted" style={{fontSize: '10px'}}>— (Off-Chain)</span>
                      )}
                    </td>
                    <td><code style={{fontSize: '10px'}}>{r.ip_address || '—'}</code></td>
                    <td style={{maxWidth: '220px', fontSize: '10px', overflowWrap: 'anywhere'}}>{r.details || '—'}</td>
                    <td>{fmtTime(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty icon={ShieldCheck} title="No audit entries found" text="Privileged platform events are logged here."/>
        )}
      </section>
    </>
  );
}

function InstitutionsPage({onSelectHistory}) {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [add, setAdd] = useState(false);
  const [notice, setNotice] = useState('');
  const [tab, setTab] = useState('ALL');
  const [modalAction, setModalAction] = useState(null);
  const [adminReason, setAdminReason] = useState('');

  async function load() {
    try {
      setRows(await api('/institutions'));
    } catch(e) {
      setError(e.message);
    }
  }

  useEffect(() => { load(); }, []);

  function promptAction(institution, targetStatus) {
    setModalAction({institution, targetStatus});
    setAdminReason('');
  }

  async function confirmModalAction(e) {
    e.preventDefault();
    if (!modalAction) return;
    const {institution, targetStatus} = modalAction;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const res = await api(`/institutions/${institution.id}/approval`, {
        method: 'POST',
        body: JSON.stringify({
          status: targetStatus,
          reason: adminReason.trim() || undefined
        })
      });
      setNotice(res.message || `Institution marked as ${targetStatus}. Administrative decision and audit reason recorded.`);
      setModalAction(null);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function create(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const data = Object.fromEntries(new FormData(e.target));
      const result = await api('/institutions', {method: 'POST', body: JSON.stringify(data)});
      setNotice(result.message);
      setAdd(false);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const filteredRows = rows.filter(r => {
    if (tab === 'ALL') return true;
    if (tab === 'PENDING') return r.approval_status === 'PENDING_APPROVAL';
    if (tab === 'APPROVED') return r.approval_status === 'APPROVED';
    if (tab === 'SUSPENDED') return r.approval_status === 'SUSPENDED';
    if (tab === 'REVOKED') return r.approval_status === 'REVOKED';
    if (tab === 'REJECTED') return r.approval_status === 'REJECTED';
    return true;
  });

  return (
    <>
      <PageHeading eyebrow="TRUST GOVERNANCE" title="Institution Access Management" text="Review pending institution applications, authorize or revoke smart contract issuer privileges, record compliance audit reasons, and inspect institution lifecycles.">
        <button className="primary" onClick={() => setAdd(!add)}><Plus size={16}/>Add institution</button>
      </PageHeading>
      <ErrorMessage message={error}/>
      {notice && <p className="success-note"><CheckCircle2 size={16}/>{notice}</p>}

      {/* Filter Tabs */}
      <div className="filter-tabs" role="tablist">
        {[
          ['ALL', `All Institutions (${rows.length})`],
          ['PENDING', `Pending Review (${rows.filter(r => r.approval_status === 'PENDING_APPROVAL').length})`],
          ['APPROVED', `Approved Issuers (${rows.filter(r => r.approval_status === 'APPROVED').length})`],
          ['SUSPENDED', `Suspended (${rows.filter(r => r.approval_status === 'SUSPENDED').length})`],
          ['REVOKED', `Revoked (${rows.filter(r => r.approval_status === 'REVOKED').length})`],
          ['REJECTED', `Rejected (${rows.filter(r => r.approval_status === 'REJECTED').length})`]
        ].map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={'filter-tab ' + (tab === key ? 'active' : '')}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {add && (
        <form className="panel institution-form" onSubmit={create}>
          {[
            ['Institution name', 'name', 'text'],
            ['Official email address', 'email', 'email'],
            ['Initial password (12+ characters)', 'password', 'password'],
            ['Ethereum wallet address', 'wallet', 'text'],
            ['Registration reference', 'institution_reference', 'text'],
            ['Verification details', 'verification_info', 'text']
          ].map(([l, n, t]) => (
            <label key={n}>{l}
              <input required name={n} type={t} minLength={n === 'password' ? 12 : undefined}/>
            </label>
          ))}
          <button className="primary" disabled={busy}>Create institution</button>
        </form>
      )}

      {/* Confirmation Modal for Consequential Actions */}
      {modalAction && (
        <div className="admin-modal-backdrop" role="dialog" aria-modal="true">
          <div className="admin-modal">
            <div className="admin-modal-header">
              <ShieldCheck size={22} style={{color: 'var(--green)'}}/>
              <h3>Confirm Administrative Action</h3>
            </div>
            <form onSubmit={confirmModalAction}>
              <div className="admin-modal-body">
                <p>
                  You are changing the authorization status of <strong>{modalAction.institution.name}</strong> ({modalAction.institution.institution_reference}) to <strong className="mono">{modalAction.targetStatus}</strong>.
                </p>

                {modalAction.targetStatus === 'APPROVED' && (
                  <div className="admin-modal-impact success">
                    <strong>Smart Contract Impact:</strong> Approving authorizes this institution's signer wallet (<code>{modalAction.institution.wallet}</code>) on the Ethereum blockchain to register verifiable credentials.
                  </div>
                )}
                {modalAction.targetStatus === 'RESTORED' && (
                  <div className="admin-modal-impact success">
                    <strong>Smart Contract Impact:</strong> Restoring re-enables this institution's signer wallet on the Ethereum smart contract.
                  </div>
                )}
                {modalAction.targetStatus === 'SUSPENDED' && (
                  <div className="admin-modal-impact">
                    <strong>Smart Contract Impact:</strong> Suspending disables smart contract issuance on-chain. Existing certificates remain on-chain with unchanged status.
                  </div>
                )}
                {modalAction.targetStatus === 'REVOKED' && (
                  <div className="admin-modal-impact danger">
                    <strong>Smart Contract Impact:</strong> Revoking revokes the institution's smart contract authorization. This is a consequential governance decision.
                  </div>
                )}
                {modalAction.targetStatus === 'REJECTED' && (
                  <div className="admin-modal-impact danger">
                    <strong>Governance Impact:</strong> Rejecting declines the institution's application. No smart contract access is granted.
                  </div>
                )}

                <label>
                  Administrative Reason / Justification (Mandatory for compliance):
                  <textarea
                    required
                    className="reason-textarea"
                    placeholder="Enter the justification for this administrative decision (recorded in immutable audit log)..."
                    value={adminReason}
                    onChange={e => setAdminReason(e.target.value)}
                    autoFocus
                  />
                </label>
              </div>
              <div className="admin-modal-footer">
                <button type="button" className="secondary" onClick={() => setModalAction(null)} disabled={busy}>
                  Cancel
                </button>
                <button
                  type="submit"
                  className={modalAction.targetStatus === 'REVOKED' || modalAction.targetStatus === 'REJECTED' ? 'danger' : 'primary'}
                  disabled={busy || !adminReason.trim()}
                >
                  {busy ? <Spinner/> : `Confirm ${modalAction.targetStatus}`}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {filteredRows.length ? (
        <div className="institution-grid">
          {filteredRows.map(r => (
            <section className="panel institution-card" key={r.id}>
              <div className="institution-card-header">
                <div className="institution-card-title">
                  <span className="eyebrow">INSTITUTION ID: {r.institution_reference || '—'}</span>
                  <h3>{r.name}</h3>
                  <span>{r.institution_domain || (r.email?.includes('@') ? r.email.split('@')[1] : '—')}</span>
                </div>
                <Badge status={r.approval_status === 'APPROVED' ? 'verified' : r.approval_status === 'PENDING_APPROVAL' ? 'pending' : r.approval_status === 'SUSPENDED' ? 'suspended' : 'revoked'}>
                  {r.approval_status}
                </Badge>
              </div>

              <div className="institution-meta-table">
                <div className="institution-meta-row">
                  <span className="label">Official Email:</span>
                  <span className="val">{r.email}</span>
                </div>
                <div className="institution-meta-row">
                  <span className="label">Domain:</span>
                  <span className="val">{r.institution_domain || (r.email?.includes('@') ? r.email.split('@')[1] : '—')}</span>
                </div>
                <div className="institution-meta-row">
                  <span className="label">Registered On:</span>
                  <span className="val">{fmtTime(r.created_at)}</span>
                </div>
                <div className="institution-meta-row">
                  <span className="label">Latest Activity:</span>
                  <span className="val">{r.latest_activity || '—'}</span>
                </div>
                <div className="institution-meta-row">
                  <span className="label">On-Chain State:</span>
                  <span className="val">
                    {r.approved ? (
                      <span className="badge onchain" style={{fontSize: '9px', padding: '2px 6px'}}>Synchronized on Contract</span>
                    ) : (
                      <span className="badge offchain" style={{fontSize: '9px', padding: '2px 6px'}}>Not Authorized on Contract</span>
                    )}
                  </span>
                </div>
              </div>

              {r.review_notes && (
                <div className="institution-notes-box">
                  <strong>Review Notes / Policy Reason</strong>
                  <p style={{margin: 0}}>{r.review_notes}</p>
                </div>
              )}

              <code style={{margin: '8px 0 12px'}}>{r.wallet}</code>

              <div className="institution-actions-bar">
                {r.approval_status === 'PENDING_APPROVAL' && (
                  <>
                    <button className="primary" onClick={() => promptAction(r, 'APPROVED')} disabled={busy}>
                      <Check size={14}/> Approve Application
                    </button>
                    <button className="danger" onClick={() => promptAction(r, 'REJECTED')} disabled={busy}>
                      <X size={14}/> Reject Application
                    </button>
                  </>
                )}
                {r.approval_status === 'APPROVED' && (
                  <>
                    <button className="secondary" onClick={() => promptAction(r, 'SUSPENDED')} disabled={busy}>
                      <Clock3 size={14}/> Suspend Access
                    </button>
                    <button className="danger" onClick={() => promptAction(r, 'REVOKED')} disabled={busy}>
                      <Ban size={14}/> Revoke Access
                    </button>
                  </>
                )}
                {r.approval_status === 'SUSPENDED' && (
                  <>
                    <button className="primary" onClick={() => promptAction(r, 'RESTORED')} disabled={busy}>
                      <Check size={14}/> Restore Access
                    </button>
                    <button className="danger" onClick={() => promptAction(r, 'REVOKED')} disabled={busy}>
                      <Ban size={14}/> Revoke Access
                    </button>
                  </>
                )}
                {r.approval_status === 'REVOKED' && (
                  <button className="primary" onClick={() => promptAction(r, 'RESTORED')} disabled={busy}>
                    <Check size={14}/> Restore Access
                  </button>
                )}
                {r.approval_status === 'REJECTED' && (
                  <button className="primary" onClick={() => promptAction(r, 'APPROVED')} disabled={busy}>
                    <Check size={14}/> Reconsider & Approve
                  </button>
                )}
                <button
                  type="button"
                  className="secondary"
                  onClick={() => onSelectHistory ? onSelectHistory(r.id) : null}
                  style={{marginLeft: 'auto'}}
                >
                  <Layers3 size={14}/> View Issuer History
                </button>
              </div>
            </section>
          ))}
        </div>
      ) : (
        <Empty icon={Building2} title="No institutions in this view" text="No institution accounts match the selected filter tab."/>
      )}

      <div className="hint" style={{marginTop: '20px'}}>
        <LockKeyhole size={18}/>
        <p>
          Consequential actions require administrative confirmation and a documented policy reason. Approvals are cryptographically synchronized with the smart contract (<code>setIssuer</code>). Institutions cannot approve themselves, and historical blockchain transactions cannot be rewritten.
        </p>
      </div>
    </>
  );
}

const gaps = [
  ['01', 'Automated verification', 'Upload once. Extract details, find the trusted record and display understandable evidence.'],
  ['02', 'ID-first record lookup', 'Distinguish a changed registered file from a certificate ID with no registration.'],
  ['03', 'Separate AI advice', 'Show model findings without letting AI overrule file integrity, issuer trust or revocation.'],
  ['04', 'Issuer governance', 'Platform-approved issuers, contract permissions and permanent certificate revocation.'],
  ['05', 'Minimal on-chain data', 'Store digests and lifecycle metadata. Keep personal fields and certificate files off-chain.'],
  ['06', 'Measured outcomes', 'Track result correctness, latency, bulk throughput, OCR extraction and transaction gas.']
];

function Architecture() {
  return (
    <>
      <PageHeading eyebrow="THE AUTHENTRA BLUEPRINT" title="Designed around the research gaps" text="A practical combination of trust checks, advisory analysis and measurable evidence."/>
      <section className="architecture-intro">
        <div>
          <span className="eyebrow light">ONE RULE AT THE CENTER</span>
          <h3>Trusted records decide.<br/>AI adds context.</h3>
          <p>A successful result means registered, unchanged, active and issued by a currently approved institution.</p>
        </div>
        <ShieldCheck size={88} strokeWidth={1}/>
      </section>
      <section className="panel architecture-image">
        <div className="panel-title">
          <h3>Corrected system architecture</h3>
          <a className="secondary" href="/architecture.svg" target="_blank" rel="noreferrer"><ArrowUpRight size={15}/>Open diagram</a>
        </div>
        <img src="/architecture.svg" alt="AuthenTra corrected architecture: authenticated React roles connect to FastAPI; original bytes go to SHA-256 and ID-first blockchain checks, while OCR and Random Forest provide separate advisory findings. System Admin approves institutions. SQLite holds minimal operational data."/>
      </section>
      <div className="gap-grid">
        {gaps.map(([n, title, desc]) => (
          <section className="panel gap-card" key={n}>
            <span>{n}</span>
            <h3>{title}</h3>
            <p>{desc}</p>
          </section>
        ))}
      </div>
      <div className="hint">
        <CircleHelp size={19}/>
        <p>These are implemented project strengths, not proof of global research novelty. Novelty claims require a cited comparison with existing systems.</p>
      </div>
    </>
  );
}

function EvidencePage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    api('/evaluation').then(setData).catch(e => setError(e.message));
  }, []);
  const m = data?.model;
  const s = data?.system;
  return (
    <>
      <PageHeading eyebrow="MEASURE, THEN CLAIM" title="Evaluation & evidence" text="Measured prototype results, with dataset scope and limitations kept visible."/>
      <ErrorMessage message={error}/>
      <div className="evidence-grid">
        <section className="panel">
          <div className="panel-title">
            <BrainCircuit size={21}/>
            <h3>Experimental AI model</h3>
            <Badge status="inconclusive">Synthetic data</Badge>
          </div>
          {m ? (
            <>
              <div className="metric-grid">
                {[['Precision', m.precision], ['Recall', m.recall], ['F1 score', m.f1]].map(([l, v]) => (
                  <div key={l}>
                    <strong>{(v * 100).toFixed(1)}<small>%</small></strong>
                    <span>{l}</span>
                  </div>
                ))}
              </div>
              <p className="panel-copy">{m.train_samples} training examples · {m.test_samples} held-out examples · Template groups separated between training and testing.</p>
              <div className="confusion">
                <h4>Confusion matrix</h4>
                <small>Rows: actual normal / anomaly. Columns: predicted normal / anomaly.</small>
                <div>{m.confusion_matrix.flat().map((n, i) => <span key={i}>{n}</span>)}</div>
              </div>
              <p className="warning-copy">{m.limitations}</p>
            </>
          ) : (
            <Empty icon={BrainCircuit} title="No model evaluation yet" text="Train and evaluate the advisory model before making performance claims."/>
          )}
        </section>

        <section className="panel">
          <div className="panel-title">
            <Activity size={21}/>
            <h3>System verification</h3>
          </div>
          {s ? (
            <>
              <div className="metric-grid">
                <div><strong>{s.passed}/{s.total}</strong><span>Expected outcomes</span></div>
                <div><strong>{(s.mean_ms / 1000).toFixed(2)}<small>s</small></strong><span>Mean verification</span></div>
                <div><strong>{(s.p95_ms / 1000).toFixed(2)}<small>s</small></strong><span>95th percentile</span></div>
              </div>
              <div className="scenario-list">
                {s.cases.map(c => (
                  <div key={c.name}>
                    {c.passed ? <CheckCircle2 size={17}/> : <X size={17}/>}
                    <span>{c.name}</span>
                    <Badge status={c.actual}/>
                  </div>
                ))}
              </div>
              <p className="panel-copy">{s.scope}</p>
              <p className="panel-copy">OCR field accuracy: {s.ocr?.field_accuracy != null ? (s.ocr.field_accuracy * 100).toFixed(0) + '% on ' + s.ocr.field_count + ' fields in one generated scan' : 'Not measured'}.</p>
              <p className="warning-copy">Local-chain transaction fees are development measurements, not estimates of public-network prices. This small demonstration is not a scalability study.</p>
            </>
          ) : (
            <Empty icon={Activity} title="Evaluation has not run yet" text="Run the end-to-end evaluation script against the local application."/>
          )}
        </section>
      </div>
    </>
  );
}

function AuditPage() {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState('');
  useEffect(() => {
    api('/audit').then(setRows).catch(e => setError(e.message));
  }, []);
  return (
    <>
      <PageHeading eyebrow="ACCOUNTABILITY" title="Institution activity" text="Registration, issuer approval and revocation events recorded for review."/>
      <ErrorMessage message={error}/>
      <section className="panel">
        {rows.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Action</th>
                  <th>Actor</th>
                  <th>Reference</th>
                  <th>Time</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.id}>
                    <td className="capitalize">{r.action?.replaceAll('_', ' ')}</td>
                    <td>{r.actor}</td>
                    <td className="mono">{r.reference}</td>
                    <td>{fmtTime(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="No activity recorded" text="Institution actions will appear here."/>
        )}
      </section>
    </>
  );
}

// ==============================================================================
// MAIN APP COMPONENT WITH ROLE-SPECIFIC ROUTING
// ==============================================================================

export default function App() {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);
  const [health, setHealth] = useState(null);
  const [page, setPage] = useState('verify');
  const [dashboard, setDashboard] = useState(null);
  const [history, setHistory] = useState([]);
  const [mobile, setMobile] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [sessionMessage, setSessionMessage] = useState('');
  const [selectedIssuerHistoryId, setSelectedIssuerHistoryId] = useState(null);

  const canonicalRole = user ? getCanonicalRole(user.role) : null;

  function getDefaultPage(role) {
    const c = getCanonicalRole(role);
    if (c === ROLE_SYSTEM_ADMIN) return 'dashboard';
    if (c === ROLE_INSTITUTION_ADMIN) return 'registry';
    return 'verify';
  }

  function getNav(role) {
    const c = getCanonicalRole(role);
    if (c === ROLE_SYSTEM_ADMIN) {
      return [
        ['dashboard', 'Admin Overview', Activity],
        ['institutions', 'Institution Governance', Building2],
        ['admin_issuer_history', 'Issuer History', Layers3],
        ['admin_verifications', 'User History', Search],
        ['admin_audit', 'System Audit Trail', ShieldCheck],
        ['architecture', 'System Architecture', Workflow],
        ['evidence', 'Evaluation & Evidence', ChartNoAxesCombined]
      ];
    }
    if (c === ROLE_INSTITUTION_ADMIN) {
      return [
        ['registry', 'Certificate Registry', Layers3],
        ['dashboard', 'Institution Dashboard', Building2],
        ['register', 'Register Credentials', UploadCloud],
        ['audit', 'Activity Log', Activity],
        ['architecture', 'System Architecture', Workflow],
        ['evidence', 'Evaluation & Evidence', ChartNoAxesCombined]
      ];
    }
    // ROLE_USER
    return [
      ['verify', 'Verify Certificate', ScanLine],
      ['history', 'Verification History', History],
      ['architecture', 'System Architecture', Workflow],
      ['evidence', 'Evaluation & Evidence', ChartNoAxesCombined]
    ];
  }

  useEffect(() => {
    api('/auth/me').then(u => {
      setUser(u);
      const def = getDefaultPage(u.role);
      const hash = window.location.hash.replace('#', '');
      const validNav = getNav(u.role).some(n => n[0] === hash);
      setPage(validNav ? hash : def);
    }).catch(() => {}).finally(() => setReady(true));
    api('/health').then(setHealth).catch(() => {});
  }, []);

  useEffect(() => {
    function onHashChange() {
      if (!user) return;
      const hash = window.location.hash.replace('#', '');
      if (hash && getNav(user.role).some(n => n[0] === hash)) {
        setPage(hash);
      }
    }
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, [user]);

  function navigateTo(newPage) {
    setPage(newPage);
    window.location.hash = newPage;
    setMobile(false);
  }

  useEffect(() => {
    const expire = () => {
      setSessionMessage('Your session expired. Please sign in again.');
      setUser(null);
      setDashboard(null);
      setHistory([]);
      window.location.hash = '';
    };
    window.addEventListener('authentra-session-expired', expire);
    return () => window.removeEventListener('authentra-session-expired', expire);
  }, []);

  async function refresh() {
    if (!user) return;
    try {
      const canon = getCanonicalRole(user.role);
      const requests = [api('/dashboard'), api('/health')];
      if (canon === ROLE_USER) requests.push(api('/history'));
      const [d, h, hist] = await Promise.all(requests);
      setDashboard(d);
      setHealth(h);
      if (hist) setHistory(hist);
      setLoadError('');
    } catch(e) {
      setLoadError(e.message);
    }
  }

  useEffect(() => {
    if (user) refresh();
  }, [user]);

  async function logout() {
    try {
      await api('/auth/logout', {method: 'POST'});
      setUser(null);
      setDashboard(null);
      window.location.hash = '';
    } catch(e) {
      setLoadError(e.message);
    }
  }

  if (!ready) {
    return (
      <div className="loading-screen">
        <Brand/>
        <Spinner/>
      </div>
    );
  }

  if (!user) {
    return (
      <Login
        sessionMessage={sessionMessage}
        onLogin={u => {
          setSessionMessage('');
          setUser(u);
          const def = getDefaultPage(u.role);
          navigateTo(def);
        }}
        health={health}
      />
    );
  }

  const nav = getNav(user.role);
  const current = nav.find(n => n[0] === page) || nav[0];

  return (
    <div className="app-shell">
      <aside className={'sidebar ' + (mobile ? 'open' : '')}>
        <Brand/>
        <div className="workspace-label">
          {canonicalRole === ROLE_SYSTEM_ADMIN ? 'ADMIN GOVERNANCE' : canonicalRole === ROLE_INSTITUTION_ADMIN ? 'ISSUER WORKSPACE' : 'USER WORKSPACE'}
        </div>
        <nav>
          {nav.map(([id, label, Icon]) => (
            <button
              key={id}
              className={page === id ? 'active' : ''}
              onClick={() => navigateTo(id)}
            >
              <Icon size={19}/>
              {label}
              {page === id && <span className="nav-indicator"/>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="chain-card">
            <span className={'connection-dot ' + (!health?.blockchain ? 'offline' : '')}/>
            <div>
              <strong>{health?.blockchain ? 'Blockchain connected' : 'Blockchain unavailable'}</strong>
              <small>{health?.demo ? 'Local development network' : 'Configured network'}</small>
            </div>
            <Layers3 size={20}/>
          </div>
          <div className="sidebar-user">
            <div className="avatar">
              {user.name.split(' ').slice(0, 2).map(s => s[0]).join('')}
            </div>
            <div>
              <strong>{user.name}</strong>
              <small>
                {canonicalRole === ROLE_SYSTEM_ADMIN ? 'System Administrator' : canonicalRole === ROLE_INSTITUTION_ADMIN ? 'Institution Administrator' : 'Standard User'}
              </small>
            </div>
            <button title="Sign out" aria-label="Sign out" onClick={logout}>
              <LogOut size={17}/>
            </button>
          </div>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <button className="mobile-menu" aria-label="Toggle navigation" onClick={() => setMobile(!mobile)}>
            <Menu size={22}/>
          </button>
          <div className="breadcrumb">
            Workspace
            <ChevronRight size={13}/>
            <strong>{current?.[1]}</strong>
          </div>
          <div className="topbar-right">
            <RoleBadge role={user.role}/>
            <div className="topbar-rule"/>
            <ShieldCheck size={17}/>
            <span>AuthenTra Assured</span>
          </div>
        </header>

        <main>
          <ErrorMessage message={loadError}/>

          {/* Institution Approval Warning if Pending */}
          {canonicalRole === ROLE_INSTITUTION_ADMIN && dashboard?.issuer_approved === false && (
            <div className="error">
              <AlertTriangle size={18}/>
              Your institution is awaiting administrator authorization. Smart contract registration is disabled until your signer wallet is approved.
            </div>
          )}

          {/* ================= USER ROUTES ================= */}
          {canonicalRole === ROLE_USER && page === 'verify' && (
            <>
              <div className="welcome-row">
                <div>
                  <h1>Certificate Verification</h1>
                  <p>Check authenticity against immutable smart contract records. (Batch upload up to 5 certificates)</p>
                </div>
                <Badge status="verified">Private Processing</Badge>
              </div>
              <div className="stat-grid">
                {[
                  [ScanLine, 'Certificates checked', dashboard?.total ?? 0, 'Your verification activity'],
                  [ShieldCheck, 'Verified certificates', dashboard?.verified ?? 0, 'Registered and unchanged'],
                  [AlertTriangle, 'Other outcomes', dashboard?.review ?? 0, 'Review result details'],
                  [Clock3, 'Average verification', dashboard?.mean_ms != null ? (dashboard.mean_ms / 1000).toFixed(2) + 's' : '—', 'Measured across your checks']
                ].map(([Icon, label, value, caption]) => (
                  <div className="stat-card" key={label}>
                    <div><span>{label}</span><Icon size={18}/></div>
                    <strong>{value}</strong>
                    <small>{caption}</small>
                  </div>
                ))}
              </div>
              <Verification health={health} onChange={refresh}/>
              <section className="panel recent-panel">
                <div className="panel-title">
                  <h3>Recent Verifications</h3>
                  <button className="text-button" onClick={() => navigateTo('history')}>
                    View all activity <ArrowUpRight size={15}/>
                  </button>
                </div>
                <HistoryTable rows={dashboard?.recent || []}/>
              </section>
            </>
          )}

          {canonicalRole === ROLE_USER && page === 'history' && (
            <HistoryPage data={history}/>
          )}

          {/* ================= INSTITUTION ADMIN ROUTES ================= */}
          {canonicalRole === ROLE_INSTITUTION_ADMIN && page === 'dashboard' && (
            <InstitutionDashboardView user={user} dashboard={dashboard} setPage={navigateTo}/>
          )}

          {canonicalRole === ROLE_INSTITUTION_ADMIN && page === 'register' && (
            <RegisterPage user={user} onChange={refresh}/>
          )}

          {canonicalRole === ROLE_INSTITUTION_ADMIN && page === 'registry' && (
            <RegistryPage user={user} onChange={refresh}/>
          )}

          {canonicalRole === ROLE_INSTITUTION_ADMIN && page === 'audit' && (
            <AuditPage/>
          )}

          {/* ================= SYSTEM ADMIN ROUTES ================= */}
          {canonicalRole === ROLE_SYSTEM_ADMIN && page === 'dashboard' && (
            <AdminDashboardView dashboard={dashboard} setPage={navigateTo}/>
          )}

          {canonicalRole === ROLE_SYSTEM_ADMIN && page === 'institutions' && (
            <InstitutionsPage onSelectHistory={id => { setSelectedIssuerHistoryId(id); navigateTo('admin_issuer_history'); }}/>
          )}

          {canonicalRole === ROLE_SYSTEM_ADMIN && page === 'admin_issuer_history' && (
            <AdminIssuerHistoryPage initialId={selectedIssuerHistoryId}/>
          )}

          {canonicalRole === ROLE_SYSTEM_ADMIN && page === 'admin_certificates' && (
            <AdminCertificatesPage/>
          )}

          {canonicalRole === ROLE_SYSTEM_ADMIN && page === 'admin_verifications' && (
            <AdminVerificationsPage/>
          )}

          {canonicalRole === ROLE_SYSTEM_ADMIN && page === 'admin_audit' && (
            <AdminAuditPage/>
          )}

          {/* ================= SHARED REFERENCE ROUTES ================= */}
          {page === 'evidence' && <EvidencePage/>}
          {page === 'architecture' && <Architecture/>}

          <footer className="workspace-footer">
            <span>AuthenTra <span> / </span> Verify · Authenticate · Build trust</span>
            <span>Cryptographic integrity. Role-based accountability.</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
