let matches = JSON.parse(localStorage.getItem('freetify-matches') || 'null') || [
  ['Mirage','Premier','WIN','13 : 9','1.34','18 / 12','Today'],['Inferno','Premier','WIN','13 : 7','1.21','17 / 11','Yesterday'],['Ancient','Premier','LOSS','8 : 13','0.94','13 / 16','Sep 10'],['Anubis','Competitive','WIN','13 : 10','1.18','21 / 18','Sep 09'],['Nuke','Premier','WIN','13 : 5','1.27','19 / 10','Sep 08'],['Vertigo','Premier','LOSS','11 : 13','1.02','16 / 17','Sep 07'],['Dust II','Competitive','WIN','13 : 6','1.30','20 / 9','Sep 05'],['Mirage','Premier','WIN','13 : 11','1.16','18 / 15','Sep 04']
];
const row = m => `<div class="match-row"><span class="map-name">${m[0]} <small class="map-mode">${m[1]}</small></span><span class="result ${m[2] === 'WIN' ? 'win' : 'loss'}">${m[2]} &nbsp; <em>${m[3]}</em></span><span class="rating">${m[4]}</span><span class="kd">${m[5]}</span><span class="date">${m[6]}</span><span class="row-arrow">›</span></div>`;
function renderMatches() { document.querySelector('#recent-matches').innerHTML = matches.slice(0, 4).map(row).join(''); document.querySelector('#all-matches').innerHTML = matches.map(row).join(''); document.querySelector('.count').textContent = matches.length; }
renderMatches();
const views = { dashboard: ['PERSONAL ANALYTICS', 'Overview'], matches: ['MATCH HISTORY', 'Matches'], settings: ['PREFERENCES', 'Settings'] };
function showView(name) { const safe = views[name] ? name : 'dashboard'; document.querySelectorAll('.view').forEach(v => v.classList.remove('active-view')); document.querySelector(`#${safe}-view`).classList.add('active-view'); document.querySelectorAll('.nav-link').forEach(a => a.classList.toggle('active', a.dataset.view === safe)); document.querySelector('#page-kicker').textContent = views[safe][0]; document.querySelector('#page-title').textContent = views[safe][1]; history.replaceState(null, '', `#${safe}`); }
document.querySelectorAll('[data-view]').forEach(a => a.addEventListener('click', e => { e.preventDefault(); showView(a.dataset.view); })); showView(location.hash.slice(1) || 'dashboard');
const toast = document.querySelector('#toast');
function notify(message) { toast.textContent = message; toast.classList.add('show'); setTimeout(() => toast.classList.remove('show'), 3500); }
let selectedFiles = [];
async function scan() {
  if (!selectedFiles.length) { notify('Choose your demo folder in Settings first'); return; }
  if (location.protocol === 'file:') { notify('Run server.py first for real analysis'); return; }
  const demos = selectedFiles.filter(file => file.name.toLowerCase().endsWith('.dem'));
  if (!demos.length) { notify('No .dem files found in that folder'); return; }
  notify(`Analyzing ${demos.length} demo${demos.length === 1 ? '' : 's'} locally…`);
  const form = new FormData(); demos.forEach(file => form.append('demos', file, file.name));
  try {
    const response = await fetch('/api/analyze', { method: 'POST', body: form }); const payload = await response.json();
    const good = payload.results.filter(result => !result.error);
    good.forEach(result => { const player = [...result.players].sort((a, b) => b.kills - a.kills)[0]; if (!player) return; const header = result.header || {}; const map = header.map_name || header.map || 'Unknown'; matches.unshift([map, 'Parsed demo', 'ANALYZED', '-', `${player.kd}`, `${player.kills} / ${player.deaths}`, 'Just now']); });
    localStorage.setItem('freetify-matches', JSON.stringify(matches.slice(0, 50))); renderMatches(); notify(`${good.length} demo${good.length === 1 ? '' : 's'} analyzed. ${payload.results.length - good.length ? 'Some files failed.' : ''}`);
  } catch (error) { notify('Analyzer unavailable — start server.py and try again'); }
}
document.querySelector('#scan-button').onclick = scan; document.querySelector('#matches-scan').onclick = scan;
const input = document.querySelector('#folder-input'), path = document.querySelector('#folder-path'); document.querySelector('#choose-folder').onclick = () => input.click();
input.addEventListener('change', () => { selectedFiles = [...input.files]; if (!selectedFiles.length) return; const first = selectedFiles[0]; const parts = first.webkitRelativePath.split('/'); parts.pop(); const chosen = parts.join(' / '); path.textContent = chosen || first.name; localStorage.setItem('freetify-folder', chosen); document.querySelector('#saved-note').textContent = `${selectedFiles.filter(file => file.name.toLowerCase().endsWith('.dem')).length} demos ready to analyze`; notify('Folder selected — press Scan for new demos'); });
const stored = localStorage.getItem('freetify-folder'); if (stored) path.textContent = stored;
if ('serviceWorker' in navigator && location.protocol !== 'file:') navigator.serviceWorker.register('./sw.js');
