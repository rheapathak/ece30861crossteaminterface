'use strict';

const form = document.getElementById('compare-form');
const messageEl = document.getElementById('message');
const runButton = document.getElementById('run-button');
const inputs = ['teamAUrl', 'teamBUrl', 'uploadFile'].map(id => document.getElementById(id));
const urls = [];
let currentRun = null;

function message(text, error = false) {
  messageEl.textContent = text;
  messageEl.className = error ? 'status error' : 'status';
}

function resetResults() {
  currentRun = null;
  urls.splice(0).forEach(url => URL.revokeObjectURL(url));
  for (const side of ['A', 'B']) {
    document.getElementById(`team${side}Downloads`).replaceChildren();
    document.getElementById(`team${side}Status`).textContent = '';
    document.getElementById(`team${side}Output`).textContent = 'Choose a file and run both reviews.';
  }
  message('');
}

for (const input of inputs) input.addEventListener(input.type === 'file' ? 'change' : 'input', resetResults);

function displayJson(key, value) {
  return key === 'content_base64' ? '[PDF data available in downloads]' : value;
}

function addLink(target, label, name, blob) {
  const link = document.createElement('a');
  const url = URL.createObjectURL(blob);
  urls.push(url);
  link.href = url;
  link.download = name.replace(/.*[\\/]/, '');
  link.textContent = label;
  target.appendChild(link);
  return link;
}

async function downloadReview(side, result, snapshot, button) {
  if (currentRun !== snapshot) return;
  button.disabled = true;
  const status = document.getElementById(`team${side}Status`);
  const previousStatus = status.textContent;
  status.textContent = 'Preparing review ZIP…';
  try {
    const data = new FormData();
    data.append('file', snapshot.file);
    data.append('report', new Blob([JSON.stringify(result.body)], {type: 'application/json'}), 'report.json');
    const response = await fetch('/api/review-download', {method: 'POST', body: data});
    if (!response.ok) {
      const error = await response.json();
      throw new Error(typeof error.detail === 'string' ? error.detail : 'Unable to prepare the review ZIP.');
    }
    if (response.headers.get('content-type')?.split(';')[0].trim() !== 'application/zip') throw new Error('The response was not a ZIP.');
    const blob = await response.blob();
    if (!blob.size) throw new Error('The review ZIP is empty.');
    if (currentRun !== snapshot) return;
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    urls.push(url);
    link.href = url;
    link.download = snapshot.file.name.replace(/(?!^)\.[^.]+$/, '') + `_Team_${side}_review.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    status.textContent = previousStatus;
  } catch (error) {
    if (currentRun === snapshot) status.textContent = error.message || 'ZIP download failed. Please try again.';
  } finally {
    button.disabled = false;
  }
}

function renderTeam(side, result, snapshot) {
  const output = document.getElementById(`team${side}Output`);
  const status = document.getElementById(`team${side}Status`);
  const downloads = document.getElementById(`team${side}Downloads`);
  output.textContent = JSON.stringify(result.body ?? {source: result.source, error: result.error || 'No response received.'}, displayJson, 2);
  if (!result.body) {
    status.textContent = result.error || 'No response received.';
    return;
  }
  const completed = result.body.status === 'completed';
  status.textContent = completed ? 'Review completed.' : `File rejected: ${result.body.error_code || 'review error'}.`;
  if (!result.contract_valid) status.textContent += ' Contract warning: ' + (result.contract_errors || []).join('; ');
  if (!['completed', 'error'].includes(result.body.status)) return;
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = `Download Team ${side} review ZIP`;
  button.addEventListener('click', () => downloadReview(side, result, snapshot, button));
  downloads.appendChild(button);
  addLink(downloads, 'JSON', `Team_${side}_report.json`, new Blob([JSON.stringify(result.body, null, 2)], {type: 'application/json'}));
  if (completed && result.contract_valid) {
    for (const [key, label] of [['output_pdf', 'Output PDF'], ['report_pdf', 'Report PDF']]) {
      const file = result.body[key];
      const bytes = Uint8Array.from(atob(file.content_base64), char => char.charCodeAt(0));
      addLink(downloads, label, file.file_name, new Blob([bytes], {type: 'application/pdf'}));
    }
  }
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  const data = new FormData(form);
  const file = data.get('file');
  if (!file || !file.name) { message('Please choose a file.', true); return; }
  if (!data.get('team_a_url')?.trim() || !data.get('team_b_url')?.trim()) { message('Enter both teams’ base URLs.', true); return; }
  resetResults();
  const snapshot = {file};
  currentRun = snapshot;
  runButton.disabled = true;
  inputs.forEach(input => { input.disabled = true; });
  message('Running both reviews…');
  for (const side of ['A', 'B']) document.getElementById(`team${side}Output`).textContent = 'Waiting for response…';
  try {
    const response = await fetch('/api/compare', {method: 'POST', body: data});
    const results = await response.json();
    if (!response.ok) throw new Error(typeof results.detail === 'string' ? results.detail : 'The reviews could not be run.');
    if (currentRun !== snapshot) return;
    renderTeam('A', results.team_a || {}, snapshot);
    renderTeam('B', results.team_b || {}, snapshot);
    message('Both reviews finished. Each team’s JSON and available downloads are shown below.');
  } catch (error) {
    if (currentRun === snapshot) {
      currentRun = null;
      message(error.message || 'Unable to run the reviews.', true);
      for (const side of ['A', 'B']) document.getElementById(`team${side}Output`).textContent = 'No review result received.';
    }
  } finally {
    runButton.disabled = false;
    inputs.forEach(input => { input.disabled = false; });
  }
});
