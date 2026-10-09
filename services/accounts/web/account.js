import {initializeApp} from 'firebase/app';
import {initializeAuth, inMemoryPersistence, connectAuthEmulator, onAuthStateChanged,
  createUserWithEmailAndPassword, signInWithEmailAndPassword, sendEmailVerification,
  sendPasswordResetEmail, signOut, reload, RecaptchaVerifier, signInWithPhoneNumber,
  browserPopupRedirectResolver, GoogleAuthProvider, signInWithPopup} from 'firebase/auth';

const $ = id => document.getElementById(id);
let auth, config, state, mode = 'signup', method = 'email', busy = false, recaptcha, confirmation;
let generation = 0, emailSentAt = 0, hideTimer;
const intro = $('description').textContent;
const status = (text, error = false) => { $('status').textContent = text; $('status').className = error ? 'error' : ''; };
const clearKey = () => { clearTimeout(hideTimer); $('new-key').value = ''; $('issued').hidden = true; };
const validPhone = value => /^\+[1-9]\d{7,14}$/.test(value);
function buttons() {
  document.querySelectorAll('button').forEach(button => { button.disabled = busy; });
  $('phone-tab').disabled = busy || !config?.phone_enabled;
  $('google-signin').disabled = busy || !config?.google_enabled;
  if (state) $('revoke-key').disabled = busy || state.key?.status !== 'active';
}
function setMode(value) {
  mode = value;
  $('signup-tab').setAttribute('aria-pressed', String(mode === 'signup'));
  $('signin-tab').setAttribute('aria-pressed', String(mode === 'signin'));
  $('confirm-row').hidden = mode !== 'signup'; $('password-confirm').required = mode === 'signup';
  $('password').autocomplete = mode === 'signup' ? 'new-password' : 'current-password';
  $('email-submit').textContent = mode === 'signup' ? 'Create account →' : 'Sign in →';
  $('reset-password').hidden = mode !== 'signin';
  $('password').value = ''; $('password-confirm').value = '';
}
function setMethod(value) {
  method = value; confirmation = undefined;
  $('code').value = '';
  $('email-tab').setAttribute('aria-pressed', String(value === 'email'));
  $('phone-tab').setAttribute('aria-pressed', String(value === 'phone'));
  $('email-form').hidden = value !== 'email'; $('phone-form').hidden = value !== 'phone';
  $('code-form').hidden = true;
}
async function run(work) {
  if (busy) return;
  busy = true; buttons();
  try { await work(); }
  catch (error) {
    const messages = {
      'auth/invalid-credential': 'Sign-in failed. Check your details or reset your password.',
      'auth/email-already-in-use': 'Unable to create this account. Try signing in or resetting your password.',
      'auth/too-many-requests': 'Too many attempts. Wait a little before trying again.',
      'auth/invalid-verification-code': 'That verification code was not accepted.',
      'auth/code-expired': 'The verification code has expired. Request a new one.',
      'auth/operation-not-allowed': 'This sign-in method is not available yet.',
      'auth/quota-exceeded': 'Verification is temporarily unavailable. Please try email.',
      'auth/network-request-failed': 'The verification service could not be reached. Check your connection.',
      'auth/popup-closed-by-user': 'The Google sign-in window was closed. You can try again.',
      'auth/popup-blocked': 'Allow the Google sign-in popup, then try again.',
      'auth/account-exists-with-different-credential': 'Use your existing sign-in method for this email address.',
    };
    status(messages[error.code] || (error.publicMessage ? error.message : 'This request could not be completed. Please try again.'), true);
  } finally { busy = false; buttons(); }
}
function userError(message) { const error = new Error(message); error.publicMessage = true; return error; }
async function api(action, body) {
  const user = auth.currentUser;
  if (!user) throw userError('Sign in to continue.');
  const epoch = generation, token = await user.getIdToken();
  const response = await fetch('/api/' + action, {method: body === undefined ? 'GET' : 'POST',
    headers: {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'X-Cognesia-Account': '1'},
    body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store', credentials: 'omit',
    redirect: 'error', signal: AbortSignal.timeout(20_000)});
  const value = await response.json();
  if (epoch !== generation || auth.currentUser?.uid !== user.uid) throw userError('Your sign-in changed. Please try again.');
  if (!response.ok) throw userError(value.error?.message || 'Account service unavailable.');
  return value;
}
function dashboard(value) {
  state = value;
  $('auth-panel').hidden = true; $('verification-panel').hidden = true; $('dashboard').hidden = false;
  $('heading').textContent = 'Your Cognesia access.'; $('welcome').textContent = value.contact;
  $('description').textContent = 'Manage the key that opens Cognesia on your computer.';
  $('key-summary').textContent = value.key ? `${value.key.status} · expires ${new Date(value.key.expires_at).toLocaleDateString()}` : 'No key yet.';
  $('replace-key').textContent = value.key?.status === 'active' ? 'Replace key' : 'Create new key';
  if (value.issued_key) {
    clearKey(); $('new-key').value = value.issued_key.api_key; $('issued').hidden = false;
    delete value.issued_key; $('copy-key').textContent = 'Copy key';
    hideTimer = setTimeout(clearKey, 5 * 60_000);
    status('Your key is ready.');
  } else status('Signed in.');
  buttons();
}
async function afterSignIn(user) {
  generation++; clearKey(); state = undefined;
  $('dashboard').hidden = true;
  if (!user) {
    setMethod(method); recaptcha?.clear(); recaptcha = undefined;
    $('auth-panel').hidden = false; $('verification-panel').hidden = true;
    $('heading').textContent = 'Get your personal key.'; $('description').textContent = intro; status(''); return;
  }
  if (!user.emailVerified && !user.phoneNumber) {
    $('auth-panel').hidden = true; $('verification-panel').hidden = false;
    $('verification-email').textContent = user.email;
    status('Verify your email to get your key.'); return;
  }
  status('Preparing your account…');
  dashboard(await api('enroll', {}));
}
$('email-form').addEventListener('submit', event => { event.preventDefault(); run(async () => {
  const email = $('email').value.trim(), password = $('password').value;
  if (mode === 'signup' && password !== $('password-confirm').value) throw userError('The passwords do not match.');
  status(mode === 'signup' ? 'Creating your account…' : 'Signing in…');
  if (mode === 'signup') {
    const result = await createUserWithEmailAndPassword(auth, email, password);
    await sendEmailVerification(result.user, {url: location.origin}); emailSentAt = Date.now();
    status('Verification email sent.');
  } else await signInWithEmailAndPassword(auth, email, password);
  $('password').value = ''; $('password-confirm').value = '';
}); });
$('google-signin').addEventListener('click', () => run(async () => {
  if (!config.google_enabled) throw userError('Google sign-in is not available.');
  const provider = new GoogleAuthProvider(); provider.setCustomParameters({prompt:'select_account'});
  await signInWithPopup(auth, provider);
}));
$('check-email').addEventListener('click', () => run(async () => {
  const user = auth.currentUser; if (!user) throw userError('Sign in again.');
  await reload(user); await user.getIdToken(true); await afterSignIn(user);
}));
$('resend-email').addEventListener('click', () => run(async () => {
  if (Date.now() - emailSentAt < 60_000) throw userError('Wait one minute before requesting another email.');
  await sendEmailVerification(auth.currentUser, {url: location.origin}); emailSentAt = Date.now(); status('Verification email sent.');
}));
$('reset-password').addEventListener('click', () => run(async () => {
  if (!$('email').reportValidity()) return;
  try { await sendPasswordResetEmail(auth, $('email').value.trim(), {url: location.origin}); }
  catch (error) { if (error.code !== 'auth/user-not-found') throw error; }
  status('If this address has an account, password-reset instructions will arrive by email.');
}));
$('phone-form').addEventListener('submit', event => { event.preventDefault(); run(async () => {
  if (!config.phone_enabled) throw userError('Phone signup is not enabled yet.');
  const number = $('phone').value.replace(/[\s()-]/g, '');
  if (!validPhone(number)) throw userError('Enter a phone number with its country code, starting with +.');
  recaptcha?.clear(); recaptcha = new RecaptchaVerifier(auth, 'recaptcha', {size: 'normal'});
  status('Complete the verification check to receive an SMS.');
  confirmation = await signInWithPhoneNumber(auth, number, recaptcha);
  $('phone-form').hidden = true; $('code-form').hidden = false; $('code').focus(); status('Enter the six-digit code sent to your phone.');
}); });
$('code-form').addEventListener('submit', event => { event.preventDefault(); run(async () => {
  if (!confirmation) throw userError('Request a new verification code.');
  await confirmation.confirm($('code').value); $('code').value = ''; confirmation = undefined;
}); });
$('change-phone').addEventListener('click', () => { setMethod('phone'); recaptcha?.clear(); recaptcha = undefined; });
for (const value of ['email', 'phone']) $(value + '-tab').addEventListener('click', () => setMethod(value));
for (const value of ['signup', 'signin']) $(value + '-tab').addEventListener('click', () => setMode(value));
for (const id of ['signout', 'verification-signout']) $(id).addEventListener('click', () => run(async () => { clearKey(); await signOut(auth); }));
$('replace-key').addEventListener('click', () => run(async () => { clearKey(); dashboard(await api('replace', {})); }));
$('revoke-key').addEventListener('click', () => run(async () => { clearKey(); dashboard(await api('revoke', {key_id: state.key.key_id})); status('Key revoked.'); }));
$('hide-key').addEventListener('click', () => { clearKey(); status('Key hidden.'); });
$('copy-key').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText($('new-key').value); $('copy-key').textContent = 'Copied'; }
  catch { $('new-key').focus(); $('new-key').select(); status('Press ⌘C or Ctrl+C to copy the selected key.'); }
});
window.addEventListener('pagehide', () => { generation++; clearKey(); $('password').value = ''; $('password-confirm').value = ''; $('code').value = ''; });
window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });

async function start() {
  const local = ['127.0.0.1', 'localhost'].includes(location.hostname);
  const appConfigResponse = await fetch('/portal-config.json', {cache: 'no-store'});
  const appConfig = await appConfigResponse.json();
  if (appConfig.emulator && !local) throw userError('The account service is not configured for public use.');
  const firebaseConfig = appConfig.firebase || await (await fetch('/__/firebase/init.json', {cache: 'no-store'})).json();
  auth = initializeAuth(initializeApp({...firebaseConfig, authDomain: firebaseConfig.authDomain || location.host}),
    {persistence: inMemoryPersistence, popupRedirectResolver:browserPopupRedirectResolver});
  if (appConfig.emulator) {
    document.querySelector('.local-badge').textContent = 'LOCAL TEST PREVIEW';
    $('preview-note').hidden = false;
    connectAuthEmulator(auth, 'http://127.0.0.1:19099', {disableWarnings: true});
    auth.settings.appVerificationDisabledForTesting = true;
  }
  const response = await fetch('/api/config', {cache: 'no-store'});
  config = await response.json();
  if (!response.ok || !config.available) throw userError(config.error?.message || 'Account signup is unavailable right now. Please try again later.');
  $('methods').hidden = !config.phone_enabled;
  $('phone-tab').hidden = !config.phone_enabled;
  $('google-signin').hidden = !config.google_enabled;
  document.querySelectorAll('input').forEach(input => { input.disabled = false; }); buttons();
  onAuthStateChanged(auth, user => afterSignIn(user).catch(error => status(error.publicMessage ? error.message : 'Account service is temporarily unavailable.', true)));
}
start().catch(error => status(error.publicMessage ? error.message : 'Account signup is unavailable right now. Please try again later.', true));
