const form = document.getElementById('compare-form');
const messageEl = document.getElementById('message');
const teamAOutput = document.getElementById('teamAOutput');
const teamBOutput = document.getElementById('teamBOutput');
const team3Form = document.getElementById('team3-form');
const team3Message = document.getElementById('team3Message');
const team3Download = document.getElementById('team3Download');
let team3DownloadUrl = null;

team3Form.addEventListener('submit', async (event) => {
  event.preventDefault();

  const formData = new FormData(team3Form);
  const file = formData.get('file');
  if (!file || !file.name) {
    showTeam3Message('Please select a file first.', 'error');
    return;
  }

  showTeam3Message('Sending file to Team 3...', '');
  team3Download.hidden = true;

  try {
    const response = await fetch('/api/team3/process', {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Team 3 processing request failed.');
    }

    if (!response.headers.get('content-type')?.toLowerCase().startsWith('application/zip')) {
      throw new Error('The interface did not return a ZIP. Restart the updated interface service.');
    }
    const output = await response.blob();
    if (output.size === 0) {
      throw new Error('The returned ZIP is empty.');
    }
    if (team3DownloadUrl) {
      URL.revokeObjectURL(team3DownloadUrl);
    }
    team3DownloadUrl = URL.createObjectURL(output);
    team3Download.href = team3DownloadUrl;
    team3Download.download = file.name.replace(/(?!^)\.[^.]+$/, '') + '_review.zip';
    team3Download.hidden = false;
    showTeam3Message('Download the review ZIP. Rejected uploads include the original file and JSON report; valid uploads also include the output PDF and report PDF.', 'success');
  } catch (error) {
    showTeam3Message(error.message || 'Team 3 processing failed.', 'error');
  }
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();

  const formData = new FormData(form);
  const file = formData.get('file');

  if (!file || !file.name) {
    showMessage('Please select a file first.', 'error');
    return;
  }

  const teamAUrl = formData.get('team_a_url')?.toString().trim();
  const teamBUrl = formData.get('team_b_url')?.toString().trim();

  if (!teamAUrl || !teamBUrl) {
    showMessage('Please enter both Team A and Team B base URLs.', 'error');
    return;
  }

  clearDownloads();
  showMessage('Setting up sessions and sending the file to both systems...', '');
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

    renderDownloads("teamADownloads", teamA);
    renderDownloads("teamBDownloads", teamB);
    teamAOutput.textContent = JSON.stringify(teamA, displayJson, 2);
    teamBOutput.textContent = JSON.stringify(teamB, displayJson, 2);

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

function showTeam3Message(text, type) {
  team3Message.textContent = text;
  team3Message.className = 'status';
  if (type) {
    team3Message.classList.add(type);
  }
  team3Message.style.display = 'block';
}

// Keep the result readable while PDF downloads preserve the actual bytes.
function displayJson(key, value) {
  return key === 'content_base64' ? '[PDF data available in downloads]' : value;
}

const comparisonUrls = [];
function clearDownloads() {
  comparisonUrls.splice(0).forEach(url => URL.revokeObjectURL(url));
  for (const id of ['teamADownloads', 'teamBDownloads']) document.getElementById(id).replaceChildren();
}
function renderDownloads(id, result) {
  const target = document.getElementById(id);
  if (!result.body || !result.contract_valid) return;
  const add = (label, name, blob) => {
    const url = URL.createObjectURL(blob);
    comparisonUrls.push(url);
    const link = document.createElement('a');
    link.textContent = label;
    link.download = name;
    link.href = url;
    link.style.marginRight = '16px';
    target.appendChild(link);
  };
  add('Download JSON', 'report.json', new Blob([JSON.stringify(result.body, null, 2)], {type:'application/json'}));
  if (result.body.status === 'completed') {
    for (const [key, label] of [['output_pdf', 'Output PDF'], ['report_pdf', 'Report PDF']]) {
      const file = result.body[key];
      const bytes = Uint8Array.from(atob(file.content_base64), char => char.charCodeAt(0));
      add(label, file.file_name.replace(/.*[\\/]/, ''), new Blob([bytes], {type:'application/pdf'}));
    }
  }
}
