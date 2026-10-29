// Records UI effects for the bench server; tasks are verified from these events only.
window.report = (type, data = {}) => fetch('/api/event', {
  method: 'POST', headers: {'content-type': 'application/json'},
  body: JSON.stringify({type, ...data}),
});
