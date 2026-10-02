const DATA = JSON.parse(document.getElementById("rankingData").textContent);
const state = { year: "2026", scope: "all", kind: "player", search: "", resultsExpanded: false };
const searchTexts = new WeakMap();
const $ = id => document.getElementById(id);
const normalizeSearch = value => value.normalize("NFKC").toLocaleLowerCase("ja").replace(/\s+/g, "");
const currentSectionId = () => `sec_${state.year}_${state.kind}_${state.scope}`;
function setActiveButtons(control, value) {
  document.querySelectorAll(`[data-control="${control}"] button`).forEach(btn => {
    btn.classList.toggle("active", btn.dataset.value === value);
    btn.setAttribute("aria-pressed", String(btn.dataset.value === value));
  });
}
function normalizeSelection() {
  if (state.year === "2025" && ["standings", "fixtures", "results"].includes(state.kind)) state.kind = "player";
  if (state.kind === "standings" && state.scope === "all") state.scope = "div1";
  if (state.kind === "fixtures") state.scope = "all";
  document.querySelectorAll('[data-year-only="2026"]').forEach(btn => btn.hidden = state.year !== "2026");
  document.querySelectorAll('[data-control="scope"] button').forEach(btn => {
    btn.hidden = (state.kind === "standings" && btn.dataset.value === "all") ||
      (state.kind === "fixtures" && btn.dataset.value !== "all");
  });
  for (const control of ["year", "kind", "scope"]) setActiveButtons(control, state[control]);
}
function showSection() {
  normalizeSelection();
  document.querySelectorAll(".ranking-section").forEach(section => section.classList.toggle("active", section.id === currentSectionId()));
  applySearch();
}
function matchesQuery(element, query) {
  if (!searchTexts.has(element)) searchTexts.set(element, normalizeSearch(element.textContent));
  return !query || searchTexts.get(element).includes(query);
}
function applySearch() {
  const active = $(currentSectionId());
  if (!active) return;
  const query = normalizeSearch(state.search);
  const selector = state.kind === "results" ? ".match-result-card" : state.kind === "fixtures" ? ".fixture-card" : "tbody tr";
  const rows = active.querySelectorAll(selector);
  let count = 0;
  rows.forEach((row, index) => {
    const withinLimit = state.kind !== "results" || state.resultsExpanded || index === 0 || Boolean(query);
    const visible = matchesQuery(row, query) && withinLimit;
    row.classList.toggle("hidden-row", !visible);
    if (visible) count++;
  });
  const toggle = active.querySelector("[data-results-toggle]");
  if (toggle) {
    toggle.hidden = Boolean(query);
    toggle.textContent = state.resultsExpanded ? "直近1試合だけ表示" : `過去の試合を見る（${Math.max(rows.length - 1, 0)}試合）`;
    toggle.setAttribute("aria-expanded", String(state.resultsExpanded));
  }
  $("searchStatus").textContent = `${count} / ${rows.length} 件を表示`;
  $("emptyState").hidden = count !== 0;
}
function escapeHtml(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}
function openTeamDrawer(team) {
  const rows = (DATA[`${state.year}_player_${state.scope}`] || []).filter(row => row.team.trim() === team);
  const scope = {all: "総合", div1: "1部", div2: "2部"}[state.scope];
  $("drawerTitle").textContent = team;
  $("drawerSub").textContent = `${state.year} / ${scope} / チーム内個人ランキング`;
  let previousGoals = null;
  let teamRank = 0;
  const body = rows.map((row, index) => {
    if (row.goals !== previousGoals) teamRank = index + 1;
    previousGoals = row.goals;
    return `<tr><td class="rank">${teamRank}</td><td class="player">${escapeHtml(row.player)}</td><td class="num">${escapeHtml(row.goals)}</td><td class="num">${escapeHtml(row.match_count)}</td></tr>`;
  }).join("");
  $("drawerBody").innerHTML = rows.length ? `<div class="table-wrap"><table><thead><tr><th>チーム内順位</th><th>選手</th><th>得点</th><th>得点試合</th></tr></thead><tbody>${body}</tbody></table></div>` : "<p>該当選手がありません。</p>";
  $("teamDrawer").classList.add("active");
  $("teamDrawer").showModal();
}
document.querySelectorAll("[data-control] button").forEach(btn => btn.addEventListener("click", () => {
  state[btn.parentElement.dataset.control] = btn.dataset.value;
  state.resultsExpanded = false;
  showSection();
}));
let searchFrame;
$("searchBox").addEventListener("input", event => {
  state.search = event.target.value || "";
  cancelAnimationFrame(searchFrame);
  searchFrame = requestAnimationFrame(applySearch);
});
$("searchClear").addEventListener("click", () => {
  state.search = "";
  $("searchBox").value = "";
  applySearch();
  $("searchBox").focus();
});
document.addEventListener("click", event => {
  if (event.target.closest("[data-results-toggle]")) {
    state.resultsExpanded = !state.resultsExpanded;
    applySearch();
    return;
  }
  const target = event.target.closest(".team-name");
  if (target) openTeamDrawer(target.dataset.team || target.textContent.trim());
});
document.addEventListener("keydown", event => {
  const target = event.target.closest(".team-name");
  if (target && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    openTeamDrawer(target.dataset.team || target.textContent.trim());
  }
});
$("drawerClose").addEventListener("click", () => $("teamDrawer").close());
$("teamDrawer").addEventListener("close", event => event.target.classList.remove("active"));
function updateFixtureNotices() {
  const parts = new Intl.DateTimeFormat("en-CA", {timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit"}).formatToParts(new Date());
  const part = type => parts.find(p => p.type === type).value;
  const today = `${part("year")}-${part("month")}-${part("day")}`;
  document.querySelectorAll(".fixture-section").forEach(section => {
    const old = [...section.querySelectorAll(".fixture-card")].filter(card => card.dataset.date < today);
    const notice = section.querySelector("[data-fixture-warning]");
    notice.hidden = old.length === 0;
    notice.textContent = `予定日を過ぎたカードが${old.length}件あります。結果・延期の情報は未反映です。公式情報をご確認ください。`;
    old.forEach(card => card.classList.add("past-fixture"));
  });
}
updateFixtureNotices();
showSection();
