const node = (tag, value, className) => { const item = document.createElement(tag); item.textContent = value ?? ''; if (className) item.className = className; return item; };

function renderTickets(id, tickets, actionable = false) {
  const container = document.getElementById(id);
  container.replaceChildren();
  if (!tickets.length) { container.append(node('p', 'No requests here right now.', 'portal-empty')); return; }
  for (const ticket of tickets) {
    const card = node('article', '', 'ticket-card');
    card.append(node('h3', `${ticket.subject || ticket.ticket_type} · ${ticket.ticket_id}`));
    card.append(node('p', `${ticket.employee_name} · ${ticket.status === 'created' ? 'Pending review' : ticket.status}`));
    if (ticket.requested_start_date) card.append(node('p', `Dates: ${ticket.requested_start_date} to ${ticket.requested_end_date || ticket.requested_start_date}`));
    if (ticket.description) card.append(node('p', ticket.description));
    if (ticket.review_message) card.append(node('p', `Reviewer response: ${ticket.review_message}`, 'review-response'));
    if (actionable) {
      const form = node('form');
      const label = node('label', 'Message to employee');
      const message = node('textarea'); message.name = 'message'; message.required = true; message.maxLength = 4000; message.rows = 3;
      label.append(message); form.append(label);
      const error = node('p', '', 'form-error');
      for (const decision of ['approved', 'denied']) {
        const button = node('button', decision === 'approved' ? 'Approve' : 'Deny');
        button.type = 'button'; button.addEventListener('click', async () => {
          if (!message.value.trim()) { error.textContent = 'Please add a message for the employee.'; return; }
          if (!confirm(`${decision === 'approved' ? 'Approve' : 'Deny'} ${ticket.ticket_id}?`)) return;
          const response = await fetch(`/portal/tickets/${encodeURIComponent(ticket.ticket_id)}/review`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({decision, message:message.value})});
          if (response.ok) await load(); else error.textContent = (await response.json()).detail || 'Could not save decision.';
        }); form.append(button);
      }
      form.append(error); card.append(form);
    }
    container.append(card);
  }
}

async function load() {
  const [meResponse, ticketsResponse] = await Promise.all([fetch('/portal/me'), fetch('/portal/tickets')]);
  if (meResponse.status === 401 || ticketsResponse.status === 401) { location.href = '/login'; return; }
  if (!meResponse.ok || !ticketsResponse.ok) { document.getElementById('identity').textContent = 'Could not load requests.'; return; }
  const me = await meResponse.json(); const tickets = await ticketsResponse.json();
  document.getElementById('identity').textContent = `${me.name} (${me.employee_id})`;
  document.getElementById('hr-section').hidden = !me.is_hr;
  document.getElementById('manager-section').hidden = !me.is_manager;
  renderTickets('hr-queue', tickets.hr_queue, true);
  renderTickets('manager-queue', tickets.manager_queue, true);
  renderTickets('my-pending', tickets.my_pending);
  renderTickets('my-closed', tickets.my_closed);
}
load();
