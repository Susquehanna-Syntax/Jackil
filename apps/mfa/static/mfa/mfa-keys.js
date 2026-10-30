/* Security keys and passkeys (apps/mfa): the sign-in tap, and adding or
 * removing a key on the Security page. Plain JS with its own base64url
 * helpers, because the sign-in step runs before any other script loads.
 */
(function () {
  const csrfInput = document.querySelector('input[name=csrfmiddlewaretoken]');
  const cookie = document.cookie.split('; ').find((c) => c.startsWith('csrftoken='));
  const csrf = csrfInput ? csrfInput.value : (cookie ? decodeURIComponent(cookie.split('=')[1]) : '');
  const errBox = document.getElementById('key-error');

  function b64urlToBytes(value) {
    const s = String(value).replace(/-/g, '+').replace(/_/g, '/');
    const bin = atob(s + '='.repeat((4 - (s.length % 4)) % 4));
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function bytesToB64url(buf) {
    const bytes = new Uint8Array(buf);
    let bin = '';
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function showError(message) {
    if (!errBox) return;
    errBox.textContent = message;
    errBox.hidden = false;
  }

  function clearError() {
    if (errBox) errBox.hidden = true;
  }

  function explain(e) {
    // NotAllowedError is the browser's word for "cancelled or timed out".
    if (e && e.name === 'NotAllowedError') return 'The key request was cancelled or timed out.';
    if (e && e.name === 'InvalidStateError') return 'That key is already set up for this account.';
    return (e && e.message) || "That key was not accepted. Try again or use a code.";
  }

  async function post(url, body) {
    const r = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
      body: JSON.stringify(body || {}),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || "That key was not accepted. Try again or use a code.");
    return data;
  }

  /* An assertion: options from one URL, the signed answer to another. */
  async function assert(optionsUrl, verifyUrl) {
    const opts = await post(optionsUrl);
    const cred = await navigator.credentials.get({ publicKey: {
      challenge: b64urlToBytes(opts.challenge).buffer,
      timeout: opts.timeout || 60000,
      rpId: opts.rpId,
      userVerification: opts.userVerification || 'preferred',
      allowCredentials: (opts.allowCredentials || []).map((c) => ({
        type: c.type || 'public-key', id: b64urlToBytes(c.id).buffer, transports: c.transports,
      })),
    } });
    const r = cred.response;
    return post(verifyUrl, { credential: {
      id: cred.id || bytesToB64url(cred.rawId),
      rawId: bytesToB64url(cred.rawId),
      type: cred.type || 'public-key',
      response: {
        clientDataJSON: bytesToB64url(r.clientDataJSON),
        authenticatorData: bytesToB64url(r.authenticatorData),
        signature: bytesToB64url(r.signature),
        userHandle: r.userHandle ? bytesToB64url(r.userHandle) : null,
      },
    } });
  }

  /* ── The sign-in step ─────────────────────────────────────────────── */

  const signin = document.getElementById('mfa-key-signin');
  if (signin) {
    if (!window.PublicKeyCredential) {
      signin.hidden = true;
    } else {
      signin.addEventListener('click', async () => {
        clearError();
        signin.disabled = true;
        try {
          const result = await assert(signin.dataset.options, signin.dataset.verify);
          window.location.assign(result.next || '/');
        } catch (e) {
          showError(explain(e));
          signin.disabled = false;
        }
      });
    }
  }

  /* ── The Security page ────────────────────────────────────────────── */

  const urlsEl = document.getElementById('mfa-key-urls');
  const card = document.getElementById('mfa-confirm-card');
  if (!urlsEl || !card) return;
  const urls = JSON.parse(urlsEl.textContent);
  const codeInput = document.getElementById('id_confirm_code');
  const keyConfirm = document.getElementById('mfa-key-confirm');
  let pending = null;

  if (!window.PublicKeyCredential) {
    const add = document.getElementById('mfa-key-add');
    if (add) add.disabled = true;
    showError('This browser cannot use security keys.');
  }
  // Only offer the key tap to confirm when this account already has a key.
  if (keyConfirm && !document.querySelector('[data-remove]')) keyConfirm.hidden = true;

  /* Ask for the current factor, then run ``action(code)`` with what was given. */
  function confirmThen(reason, action) {
    clearError();
    pending = action;
    document.getElementById('mfa-confirm-reason').textContent = reason;
    codeInput.value = '';
    card.hidden = false;
    codeInput.focus();
  }

  async function finish(code) {
    const action = pending;
    pending = null;
    card.hidden = true;
    try {
      await action(code);
      window.location.reload();
    } catch (e) {
      showError(explain(e));
    }
  }

  document.getElementById('mfa-confirm-go').addEventListener('click', () => {
    const code = codeInput.value.trim();
    if (!code) { codeInput.focus(); return; }
    finish(code);
  });
  codeInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); document.getElementById('mfa-confirm-go').click(); }
  });
  if (keyConfirm) {
    keyConfirm.addEventListener('click', async () => {
      try {
        const result = await assert(urls.options, urls.verify);
        finish(result.token);
      } catch (e) {
        showError(explain(e));
      }
    });
  }
  document.getElementById('mfa-confirm-cancel').addEventListener('click', () => {
    pending = null;
    card.hidden = true;
  });

  const add = document.getElementById('mfa-key-add');
  if (add) {
    add.addEventListener('click', () => {
      const name = document.getElementById('id_key_name').value.trim() || 'Security key';
      confirmThen(`Adding “${name}”.`, async (code) => {
        const opts = await post(add.dataset.options, { code });
        const cred = await navigator.credentials.create({ publicKey: {
          challenge: b64urlToBytes(opts.challenge).buffer,
          rp: opts.rp,
          user: {
            id: b64urlToBytes(opts.user.id).buffer,
            name: opts.user.name,
            displayName: opts.user.displayName,
          },
          pubKeyCredParams: opts.pubKeyCredParams,
          timeout: opts.timeout || 60000,
          attestation: opts.attestation || 'none',
          authenticatorSelection: opts.authenticatorSelection,
          excludeCredentials: (opts.excludeCredentials || []).map((c) => ({
            type: c.type || 'public-key', id: b64urlToBytes(c.id).buffer,
          })),
        } });
        const r = cred.response;
        await post(add.dataset.register, { name, credential: {
          id: cred.id || bytesToB64url(cred.rawId),
          rawId: bytesToB64url(cred.rawId),
          type: cred.type || 'public-key',
          response: {
            clientDataJSON: bytesToB64url(r.clientDataJSON),
            attestationObject: bytesToB64url(r.attestationObject),
            transports: r.getTransports ? r.getTransports() : [],
          },
        } });
      });
    });
  }

  document.querySelectorAll('[data-remove]').forEach((btn, index) => {
    btn.addEventListener('click', () => {
      confirmThen(`Removing “${btn.dataset.name}”.`, (code) => post(urls.remove[index], { code }));
    });
  });
})();
