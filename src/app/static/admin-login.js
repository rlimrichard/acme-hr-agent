// Note: /admin/login (POST) responds with plain JSON (not a redirect) --
// this keeps success/failure unambiguous to fetch(), since a fetch with a
// followed redirect can't distinguish "redirected to /admin" (success)
// from "redirected to /admin/login?error=1" (failure) without exposing
// the target URL, which same-origin opaque redirects deliberately hide.

const form = document.getElementById('login-form');
const errorBox = document.getElementById('login-error');
const submitBtn = document.getElementById('login-submit');

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  errorBox.hidden = true;
  submitBtn.disabled = true;
  submitBtn.textContent = 'Signing in…';

  const formData = new FormData(form);

  try {
    const res = await fetch('/admin/login', { method: 'POST', body: formData });

    if (res.ok) {
      window.location.href = '/admin';
      return;
    }

    if (res.status === 401) {
      errorBox.textContent = 'Incorrect username or password.';
    } else {
      errorBox.textContent = `Something went wrong (${res.status}). Please try again.`;
    }
    errorBox.hidden = false;
  } catch (err) {
    errorBox.textContent = 'Could not reach the server. Please try again.';
    errorBox.hidden = false;
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Sign in';
  }
});
