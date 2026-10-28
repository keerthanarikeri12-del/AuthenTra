export function isUserRole(user) {
  if (!user || !user.role) return true;
  const r = String(user.role).trim().toLowerCase();
  return (
    r !== 'admin' &&
    r !== 'owner' &&
    r !== 'system_admin' &&
    r !== 'institution' &&
    r !== 'institution_admin' &&
    r !== 'issuer'
  );
}

export async function downloadVerificationPdf(id, reference, setLoading, setError) {
  if (!id) return;
  if (setLoading) setLoading(true);
  if (setError) setError(null);
  try {
    const res = await fetch(`/api/verifications/${id}/report.pdf`);
    if (res.status === 401) {
      window.dispatchEvent(new Event('authentra-session-expired'));
      throw new Error('Your session has expired. Please sign in again.');
    }
    if (!res.ok) {
      let msg = 'Failed to download report.';
      try {
        const body = await res.json();
        msg = body.detail || msg;
      } catch {
        // non-JSON response
      }
      throw new Error(msg);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `AuthenTra-Report-${id}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) {
    if (setError) setError(err.message || 'Failed to download report.');
  } finally {
    if (setLoading) setLoading(false);
  }
}

export async function downloadBatchVerificationPdf(ids, setLoading, setError) {
  if (!ids || !ids.length) return;
  if (setLoading) setLoading(true);
  if (setError) setError(null);
  try {
    const query = ids.slice(0, 5).join(',');
    const res = await fetch(`/api/verifications/report.pdf?ids=${query}`);
    if (res.status === 401) {
      window.dispatchEvent(new Event('authentra-session-expired'));
      throw new Error('Your session has expired. Please sign in again.');
    }
    if (!res.ok) {
      let msg = 'Failed to download batch report.';
      try {
        const body = await res.json();
        msg = body.detail || msg;
      } catch {
        // non-JSON response
      }
      throw new Error(msg);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'AuthenTra-Batch-Report.pdf';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) {
    if (setError) setError(err.message || 'Failed to download batch report.');
  } finally {
    if (setLoading) setLoading(false);
  }
}

