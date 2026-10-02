const form = document.getElementById('compare-form');
const messageEl = document.getElementById('message');
const teamAOutput = document.getElementById('teamAOutput');
const teamBOutput = document.getElementById('teamBOutput');

form.addEventListener('submit', async (event) => {
  event.preventDefault();

  const formData = new FormData(form);
  const file = formData.get('file');

  if (!file || file.size === 0) {
    showMessage('Please select a PDF file first.', 'error');
    return;
  }

  const teamAUrl = formData.get('team_a_url')?.toString().trim();
  const teamBUrl = formData.get('team_b_url')?.toString().trim();

  if (!teamAUrl || !teamBUrl) {
    showMessage('Please enter both Team A and Team B base URLs.', 'error');
    return;
  }

  showMessage('Sending PDF to both systems...', '');
  teamAOutput.textContent = 'Waiting for response...';
  teamBOutput.textContent = 'Waiting for response...';

  try {
    const response = await fetch('/api/compare', {
      method: 'POST',
      body: formData,
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || 'Comparison request failed.');
    }

    const teamA = data.team_a || {};
    const teamB = data.team_b || {};

    teamAOutput.textContent = JSON.stringify(teamA, null, 2);
    teamBOutput.textContent = JSON.stringify(teamB, null, 2);

    showMessage(
      `Completed. Team A status: ${teamA.success ? 'success' : 'error'} | Team B status: ${teamB.success ? 'success' : 'error'}`,
      teamA.success && teamB.success ? 'success' : 'error'
    );
  } catch (error) {
    teamAOutput.textContent = 'Request failed';
    teamBOutput.textContent = 'Request failed';
    showMessage(error.message || 'Something went wrong.', 'error');
  }
});

function showMessage(text, type) {
  messageEl.textContent = text;
  messageEl.className = 'status';
  if (type) {
    messageEl.classList.add(type);
  }
  messageEl.style.display = 'block';
}
