let language = localStorage.getItem("br-language") || "en";
const languageToggle = document.querySelector("#languageToggle");
if (languageToggle) {
  languageToggle.addEventListener("click", () => {
    language = language === "en" ? "sw" : "en";
    localStorage.setItem("br-language", language);
    languageToggle.textContent = language === "en" ? "Swahili" : "English";
  });
}

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = value == null ? "" : String(value);
  return node.innerHTML;
}

const profileForm = document.querySelector("#profileForm");
if (profileForm) {
  let step = 1;
  const titles = ["Level of study", "Year of study", "Location", "Optional need indicators", "Review"];
  function showStep(nextStep) {
    step = nextStep;
    document.querySelectorAll(".wizard-step").forEach((node) =>
      node.classList.toggle("active", Number(node.dataset.step) === step)
    );
    document.querySelector("#wizardStep").textContent = String(step);
    document.querySelector("#wizardTitle").textContent = titles[step - 1];
    document.querySelector("#wizardBack").hidden = step === 1;
    document.querySelector("#wizardNext").hidden = step === 5;
    document.querySelector("#wizardSubmit").hidden = step !== 5;
  }
  document.querySelector("#wizardNext").addEventListener("click", () => {
    const required = document.querySelector(`.wizard-step[data-step="${step}"] [required]`);
    if (required && !required.value) { required.focus(); return; }
    showStep(Math.min(5, step + 1));
  });
  document.querySelector("#wizardBack").addEventListener("click", () => showStep(Math.max(1, step - 1)));
  document.querySelector("#sampleButton").addEventListener("click", () => {
    profileForm.elements.level.value = "university";
    profileForm.elements.institution_type.value = "public";
    profileForm.elements.year_of_study.value = "1";
    profileForm.elements.county.value = "Machakos";
    profileForm.elements.constituency.value = "Mwala";
    showStep(1);
    document.querySelector("#find").scrollIntoView({ behavior: "smooth" });
  });
  profileForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(profileForm);
    const profile = {
      level:data.get("level"), institution_type:data.get("institution_type") || null,
      institution_name:data.get("institution_name") || null,
      year_of_study:data.get("year_of_study") ? Number(data.get("year_of_study")) : null,
      county:data.get("county") || null, constituency:data.get("constituency") || null,
      need_flags:data.getAll("need_flag"),
    };
    const list = document.querySelector("#matchesList");
    list.innerHTML = '<div class="empty-state">Finding opportunities...</div>';
    try {
      const response = await fetch("/api/match", {method:"POST",headers:{ "Content-Type":"application/json" },body:JSON.stringify(profile)});
      if (!response.ok) throw new Error("Could not match opportunities");
      const result = await response.json();
      list.replaceChildren();
      document.querySelector("#matchCount").textContent = `${result.likely.length + result.check_eligibility.length} opportunities`;
      renderMatchGroup("Likely matches", result.likely, list);
      renderMatchGroup("Check eligibility", result.check_eligibility, list);
    } catch {
      list.innerHTML = '<div class="empty-state">The matching service is unavailable. Please try again.</div>';
    }
  });
}

function renderMatchGroup(title, matches, container) {
  if (!matches.length) return;
  const heading = document.createElement("h3");
  heading.className = "match-group-title";
  heading.textContent = title;
  container.appendChild(heading);
  matches.forEach((match) => {
    const opportunity = match.opportunity;
    const card = document.createElement("article");
    card.className = "match-card";
    card.innerHTML =
      `<div class="match-main"><div class="badge-row"><span class="provider-chip">${escapeHtml(opportunity.provider_type.replaceAll("_"," "))}</span><span class="confidence ${opportunity.confidence.toLowerCase()}">${escapeHtml(opportunity.confidence)}</span></div><h3>${escapeHtml(opportunity.name)}</h3><p>${escapeHtml(opportunity.provider)}</p><div class="meta"><span>${escapeHtml(opportunity.deadline || "Deadline not confirmed")}</span><span>${escapeHtml(opportunity.amount_published ? "Amount published" : "Amount not published")}</span></div><p class="match-reasons">${(match.reasons || []).map(escapeHtml).join(" • ")}</p><details><summary>Documents and how to apply</summary><p>${escapeHtml(opportunity.documents_required ? opportunity.documents_required.join(", ") : "Document checklist not confirmed")}</p><p>${escapeHtml(opportunity.how_to_apply || "Check the source for current instructions.")}</p></details></div>
       <div class="match-actions"><button class="outline-button plan-button" type="button">Add to my plan</button><a class="source-link" href="${escapeHtml(opportunity.apply_url || opportunity.source_url)}" target="_blank" rel="noopener noreferrer">Go to source</a><button class="outline-button report-button" type="button">Report outdated</button></div>`;
    card.querySelector(".plan-button").addEventListener("click", (event) => addToPlan(opportunity, event.currentTarget));
    card.querySelector(".report-button").addEventListener("click", () => reportOpportunity(opportunity));
    container.appendChild(card);
  });
}

function getPlan() {
  try { return JSON.parse(localStorage.getItem("bursary-radar-plan") || "[]"); }
  catch { return []; }
}

function addToPlan(opportunity, button) {
  const plan = getPlan();
  const exists = plan.some((item) => item.id === opportunity.id);
  if (!exists) { plan.push(opportunity); localStorage.setItem("bursary-radar-plan", JSON.stringify(plan)); }
  button.textContent = exists ? "Already in my plan" : "Added to my plan";
  button.classList.remove("button-success","button-added");
  void button.offsetWidth;
  button.classList.add(exists ? "button-added" : "button-success");
  renderPlan();
  window.setTimeout(() => { button.textContent = "Add to my plan"; button.classList.remove("button-success","button-added"); }, 2400);
}

function renderPlan() {
  const plan = getPlan();
  const summary = document.querySelector("#planSummary");
  const list = document.querySelector("#planList");
  if (!summary || !list) return;
  summary.textContent = plan.length ? `${plan.length} opportunity${plan.length === 1 ? "" : "ies"} saved on this device.` : "Nothing saved yet.";
  list.innerHTML = "";
  plan.forEach((opportunity) => {
    const item = document.createElement("article");
    item.className = "plan-item";
    item.innerHTML = `<strong>${escapeHtml(opportunity.name)}</strong><span>${escapeHtml(opportunity.deadline || "Deadline not confirmed")}</span>`;
    list.appendChild(item);
  });
}
renderPlan();

async function reportOpportunity(opportunity) {
  const reason = window.prompt("Reason: deadline_wrong, link_broken, closed, or other", "other");
  if (!reason) return;
  const note = window.prompt("Optional note", "") || "";
  await fetch("/api/reports", {method:"POST",headers:{ "Content-Type":"application/json" },body:JSON.stringify({opportunity_id:opportunity.id,reason,note})});
  alert("Report submitted.");
}

const feeForm = document.querySelector("#feeForm");
if (feeForm) {
  feeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(feeForm);
    const response = await fetch("/api/fee-gap", {
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body:JSON.stringify(Object.fromEntries(data.entries())),
    });
    const result = await response.json();
    if (!response.ok) { alert(result.error?.message || "Invalid amounts"); return; }
    document.querySelector("#gapAmount").textContent =
      `KES ${Number(result.gap).toLocaleString("en-KE")}`;
    document.querySelector("#gapProgress").style.width =
      `${Math.max(0, Math.min(100, result.percent_covered))}%`;
    document.querySelector("#gapSuggestions").innerHTML =
      (result.suggested || []).slice(0,5).map((item) =>
        `<button type="button" class="outline-button gap-suggestion">${escapeHtml(item.name)} — ${escapeHtml(item.amount)}</button>`
      ).join("");
  });
}

const smsButton = document.querySelector("#smsButton");
if (smsButton) {
  smsButton.addEventListener("click", async () => {
    const plan = getPlan();
    if (!plan.length) { alert("Add opportunities to My Plan first."); return; }
    const response = await fetch("/api/reminders/preview", {
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body:JSON.stringify({ opportunity_ids:plan.map((item)=>item.id), lang:language }),
    });
    const result = await response.json();
    let panel = document.querySelector("#smsPreview");
    if (!panel) {
      panel = document.createElement("div");
      panel.id = "smsPreview";
      panel.className = "phone-preview";
      document.querySelector("#plan").appendChild(panel);
    }
    panel.innerHTML =
      result.reminders.map((item) =>
        `<article><strong>${escapeHtml(item.name)}</strong>${item.schedule.map((entry)=>`<p>${escapeHtml(entry.send_on)}: ${escapeHtml(entry.message)}</p>`).join("")}</article>`
      ).join("") +
      result.skipped.map((item)=>`<p>${escapeHtml(item.name)}: ${escapeHtml(item.reason)}</p>`).join("");
  });
}

let rating = 0;
const stars = document.querySelector("#feedbackStars");
if (stars) {
  for (let value=1; value<=5; value+=1) {
    const button = document.createElement("button");
    button.type="button";
    button.textContent="★";
    button.setAttribute("aria-label", `${value} out of 5`);
    button.addEventListener("click", () => {
      rating=value;
      [...stars.children].forEach((star,index)=>star.classList.toggle("selected",index<value));
    });
    stars.appendChild(button);
  }
  document.querySelector("#feedbackSubmit").addEventListener("click", async () => {
    if (!rating) { alert("Choose a rating."); return; }
    await fetch("/api/feedback", {
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body:JSON.stringify({rating,comment:document.querySelector("#feedbackComment").value}),
    });
    alert("Thank you for your feedback.");
  });
}

const pollContainer = document.querySelector("#pollQuestions");
if (pollContainer) {
  async function loadPoll() {
    const response=await fetch("/api/poll");
    const tallies=await response.json();
    pollContainer.innerHTML="";
    Object.entries(tallies).forEach(([key,tally])=>{
      const total=tally.yes+tally.no;
      const yesPercent=total?Math.round(tally.yes*100/total):0;
      const card=document.createElement("article");
      card.className="poll-card";
      card.innerHTML=`<h2>${escapeHtml(tally.question)}</h2><div class="poll-actions"><button type="button" data-answer="yes">Yes</button><button type="button" data-answer="no">No</button></div><div class="poll-tallies"><span>Yes ${tally.yes}</span><span>No ${tally.no}</span></div><div class="progress-track"><div class="progress-fill" style="width:${yesPercent}%"></div></div>`;
      card.querySelectorAll("button").forEach((button)=>button.addEventListener("click",async()=>{
        await fetch("/api/poll",{method:"POST",headers:{ "Content-Type":"application/json" },body:JSON.stringify({question_key:key,answer:button.dataset.answer})});
        loadPoll();
      }));
      pollContainer.appendChild(card);
    });
  }
  loadPoll();
}
