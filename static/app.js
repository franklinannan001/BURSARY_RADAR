const locale = {
  en: {
    "nav.find": "Find funding",
    "nav.fees": "Fee-gap planner",
    "nav.plan": "My plan",
    "nav.verify": "How we verify",
    "hero.title": "Find funding you can apply for.",
    "hero.copy": "A private, browser-first way to understand opportunities and prepare before deadlines.",
  },
  sw: {
    "nav.find": "Tafuta ufadhili",
    "nav.fees": "Mpangilio wa ada",
    "nav.plan": "Mpango wangu",
    "nav.verify": "Tunavyothibitisha",
    "hero.title": "Pata ufadhili unaweza kuomba.",
    "hero.copy": "Njia ya faragha ya kuelewa fursa na kujiandaa kabla ya tarehe za mwisho.",
  },
};

let language = localStorage.getItem("br-language") || "en";

function applyLanguage() {
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    const value = locale[language]?.[element.dataset.i18n];
    if (value) element.textContent = value;
  });
  const toggle = document.querySelector("#languageToggle");
  if (toggle) toggle.textContent = language === "en" ? "Swahili" : "English";
  document.documentElement.lang = language;
}

applyLanguage();

const languageToggle = document.querySelector("#languageToggle");
if (languageToggle) {
  languageToggle.addEventListener("click", () => {
    language = language === "en" ? "sw" : "en";
    localStorage.setItem("br-language", language);
    applyLanguage();
  });
}

const profileForm = document.querySelector("#profileForm");
if (profileForm) {
  let wizardStep = 1;
  const titles = ["Level of study", "Year of study", "Location", "Optional need indicators", "Review"];

  function showWizardStep(step) {
    wizardStep = step;
    document.querySelectorAll(".wizard-step").forEach((node) => {
      node.classList.toggle("active", Number(node.dataset.step) === step);
    });
    document.querySelector("#wizardStep").textContent = String(step);
    document.querySelector("#wizardTitle").textContent = titles[step - 1];
    document.querySelector("#wizardBack").hidden = step === 1;
    document.querySelector("#wizardNext").hidden = step === 5;
    document.querySelector("#wizardSubmit").hidden = step !== 5;
    if (step === 5) {
      const data = new FormData(profileForm);
      document.querySelector("#profileReview").innerHTML =
        `<dl><dt>Level</dt><dd>${data.get("level") || "Not selected"}</dd>` +
        `<dt>Institution</dt><dd>${data.get("institution_type") || "Not sure"}</dd>` +
        `<dt>County</dt><dd>${data.get("county") || "Not selected"}</dd>` +
        `<dt>Constituency</dt><dd>${data.get("constituency") || "Not sure"}</dd></dl>`;
    }
  }

  document.querySelector("#wizardNext").addEventListener("click", () => {
    const active = document.querySelector(`.wizard-step[data-step="${wizardStep}"]`);
    const required = active.querySelector("[required]");
    if (required && !required.value) {
      required.focus();
      return;
    }
    showWizardStep(Math.min(5, wizardStep + 1));
  });
  document.querySelector("#wizardBack").addEventListener("click", () => showWizardStep(Math.max(1, wizardStep - 1)));

  document.querySelector("#sampleButton").addEventListener("click", () => {
    profileForm.elements.level.value = "university";
    profileForm.elements.institution_type.value = "public";
    profileForm.elements.year_of_study.value = "1";
    profileForm.elements.county.value = "Machakos";
    profileForm.elements.constituency.value = "Mwala";
    showWizardStep(1);
    document.querySelector("#find").scrollIntoView({ behavior: "smooth" });
  });

  profileForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(profileForm);
    const needFlags = data.getAll("need_flag");
    const profile = {
      level: data.get("level"),
      institution_type: data.get("institution_type") || null,
      institution_name: data.get("institution_name") || null,
      year_of_study: data.get("year_of_study") ? Number(data.get("year_of_study")) : null,
      county: data.get("county") || null,
      constituency: data.get("constituency") || null,
      need_flags: needFlags,
    };
    const list = document.querySelector("#matchesList");
    list.innerHTML = '<div class="empty-state">Finding opportunities...</div>';
    try {
      const response = await fetch("/api/match", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(profile),
      });
      if (!response.ok) throw new Error("Could not match opportunities");
      const result = await response.json();
      const likely = result.likely || [];
      const check = result.check_eligibility || [];
      document.querySelector("#matchCount").textContent =
        `${likely.length + check.length} opportunities`;
      list.replaceChildren();
      renderMatchGroup("Likely matches", likely, list);
      renderMatchGroup("Check eligibility", check, list);
      fetch("/api/events", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: "profile_completed" }),
      }).catch(() => {});
    } catch (error) {
      list.innerHTML = '<div class="empty-state">The matching service is unavailable. Please try again.</div>';
    }
  });
}

function amountLabel(opportunity) {
  if (!opportunity.amount_published) return "Amount not published";
  if (opportunity.amount_min != null || opportunity.amount_max != null) {
    const low = opportunity.amount_min != null ? `KES ${Number(opportunity.amount_min).toLocaleString("en-KE")}` : "";
    const high = opportunity.amount_max != null ? `KES ${Number(opportunity.amount_max).toLocaleString("en-KE")}` : "";
    return low && high ? `${low} - ${high}` : low || high;
  }
  return "Amount not published";
}

function deadlineLabel(opportunity) {
  if (!opportunity.deadline) return "Deadline not confirmed";
  const date = new Date(`${opportunity.deadline}T00:00:00`);
  const days = Math.ceil((date - new Date()) / 86400000);
  if (days >= 0) return `${opportunity.deadline} (${days} days remaining)`;
  return `${opportunity.deadline} (Closed)`;
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
    const confidence = opportunity.confidence || "RED";
    const icon = confidence === "GREEN" ? "●" : confidence === "AMBER" ? "◆" : "▲";
    card.innerHTML =
      `<div class="match-main">
        <div class="badge-row">
          <span class="provider-chip">${escapeHtml(opportunity.provider_type.replaceAll("_", " "))}</span>
          <span class="confidence ${confidence.toLowerCase()}" aria-label="${confidence} confidence">${icon} ${confidence}</span>
        </div>
        <h3>${escapeHtml(opportunity.name)}</h3>
        <p class="provider">${escapeHtml(opportunity.provider)}</p>
        <div class="meta"><span>${escapeHtml(deadlineLabel(opportunity))}</span><span>${escapeHtml(amountLabel(opportunity))}</span></div>
        <p class="match-reasons">${(match.reasons || []).map(escapeHtml).join(" • ")}</p>
        <small>Last checked: ${opportunity.last_verified_at ? escapeHtml(opportunity.last_verified_at.slice(0, 10)) : "Not confirmed"}${opportunity.verified_by ? " by " + escapeHtml(opportunity.verified_by) : ""}</small>
        <details><summary>Documents and how to apply</summary>
          <p>${escapeHtml(opportunity.documents_required ? opportunity.documents_required.join(", ") : "Document checklist not confirmed")}</p>
          <p>${escapeHtml(opportunity.how_to_apply || "Check the source for current application instructions.")}</p>
        </details>
      </div>
      <div class="match-actions">
        <button class="outline-button plan-button" type="button">Add to my plan</button>
        <a class="source-link" href="${escapeHtml(opportunity.apply_url || opportunity.source_url)}" target="_blank" rel="noopener noreferrer">Go to source</a>
        <button class="outline-button report-button" type="button">Report outdated</button>
      </div>`;
    card.querySelector(".plan-button").addEventListener("click", () => addToPlan(opportunity));
    card.querySelector(".report-button").addEventListener("click", () => reportOpportunity(opportunity));
    container.appendChild(card);
  });
}

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = value == null ? "" : String(value);
  return node.innerHTML;
}

async function reportOpportunity(opportunity) {
  const reason = window.prompt("Reason: deadline_wrong, link_broken, closed, or other", "other");
  if (!reason) return;
  const note = window.prompt("Optional note (300 characters maximum)", "") || "";
  await fetch("/api/reports", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ opportunity_id: opportunity.id, reason, note }),
  });
  alert("Report submitted.");
}

function getPlan() {
  return JSON.parse(localStorage.getItem("bursary-radar-plan") || "[]");
}

function addToPlan(opportunity) {
  const plan = getPlan();
  if (!plan.some((item) => item.id === opportunity.id)) {
    plan.push(opportunity);
    localStorage.setItem("bursary-radar-plan", JSON.stringify(plan));
  }
  renderPlan();
  fetch("/api/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type: "plan_item_added", value: opportunity.id }),
  }).catch(() => {});
}

function renderPlan() {
  const plan = getPlan();
  const summary = document.querySelector("#planSummary");
  const list = document.querySelector("#planList");
  if (!summary || !list) return;
  summary.textContent = plan.length
    ? `${plan.length} opportunity${plan.length === 1 ? "" : "ies"} saved on this device.`
    : "Nothing saved yet. Use “Add to my plan” on an opportunity.";
  list.innerHTML = "";
  plan.forEach((opportunity) => {
    const item = document.createElement("article");
    item.className = "plan-item";
    item.innerHTML =
      `<strong>${escapeHtml(opportunity.name)}</strong><span>${escapeHtml(deadlineLabel(opportunity))}</span>` +
      `<label><input type="checkbox" class="plan-check"> Documents prepared</label>`;
    list.appendChild(item);
  });
}

renderPlan();

const feeForm = document.querySelector("#feeForm");
if (feeForm) {
  feeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(feeForm);
    try {
      const response = await fetch("/api/fee-gap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.fromEntries(data.entries())),
      });
      if (!response.ok) throw new Error("Could not calculate the fee gap");
      const result = await response.json();
      document.querySelector("#gapAmount").textContent =
        `KES ${Number(result.gap).toLocaleString("en-KE")}${result.surplus > 0 ? " (surplus " + Number(result.surplus).toLocaleString("en-KE") + ")" : ""}`;
      document.querySelector("#gapProgress").style.width =
        `${Math.max(0, Math.min(100, result.percent_covered))}%`;
      document.querySelector("#gapSuggestions").innerHTML =
        (result.suggested || []).slice(0, 4).map((item) =>
          `<button type="button" class="outline-button gap-suggestion" data-id="${escapeHtml(item.id)}">${escapeHtml(item.name)} — ${escapeHtml(item.amount)}</button>`
        ).join("");
    } catch (error) {
      alert(error.message);
    }
  });
}

const smsButton = document.querySelector("#smsButton");
if (smsButton) {
  smsButton.addEventListener("click", async () => {
    const plan = getPlan();
    if (!plan.length) {
      alert("Add opportunities to My Plan before previewing SMS reminders.");
      return;
    }
    try {
      const response = await fetch("/api/reminders/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          opportunity_ids: plan.map((item) => item.id),
          lang: language === "sw" ? "sw" : "en",
        }),
      });
      const result = await response.json();
      let panel = document.querySelector("#smsPreview");
      if (!panel) {
        panel = document.createElement("div");
        panel.id = "smsPreview";
        panel.className = "phone-preview";
        document.querySelector("#plan").appendChild(panel);
      }
      panel.innerHTML = result.reminders.map((reminder) =>
        `<article><strong>${escapeHtml(reminder.name)}</strong>` +
        reminder.schedule.map((item) => `<p>${escapeHtml(item.send_on)}: ${escapeHtml(item.message)}</p>`).join("") +
        `</article>`
      ).join("") + result.skipped.map((item) =>
        `<p>${escapeHtml(item.name)}: ${escapeHtml(item.reason)}</p>`
      ).join("");
      fetch("/api/events", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: "reminder_previewed" }),
      }).catch(() => {});
    } catch (error) {
      alert("Could not preview reminders.");
    }
  });
}

let feedbackRating = 0;
const feedbackStars = document.querySelector("#feedbackStars");
if (feedbackStars) {
  for (let rating = 1; rating <= 5; rating += 1) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "★";
    button.setAttribute("aria-label", `${rating} out of 5`);
    button.addEventListener("click", () => {
      feedbackRating = rating;
      [...feedbackStars.children].forEach((star, index) => {
        star.classList.toggle("selected", index < rating);
      });
    });
    feedbackStars.appendChild(button);
  }
  document.querySelector("#feedbackSubmit").addEventListener("click", async () => {
    if (!feedbackRating) {
      alert("Choose a rating from 1 to 5.");
      return;
    }
    await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rating: feedbackRating,
        comment: document.querySelector("#feedbackComment").value,
      }),
    });
    alert("Thank you for your feedback.");
  });
}

const pollContainer = document.querySelector("#pollQuestions");
if (pollContainer) {
  async function loadPoll() {
    const response = await fetch("/api/poll");
    const tallies = await response.json();
    pollContainer.innerHTML = "";
    Object.entries(tallies).forEach(([key, tally]) => {
      const total = tally.yes + tally.no;
      const yesPercent = total ? Math.round((tally.yes / total) * 100) : 0;
      const card = document.createElement("article");
      card.className = "poll-card";
      card.innerHTML =
        `<h2>${escapeHtml(tally.question)}</h2>
        <div class="poll-actions">
          <button type="button" data-answer="yes">Yes</button>
          <button type="button" data-answer="no">No</button>
        </div>
        <div class="poll-tallies"><span>Yes ${tally.yes}</span><span>No ${tally.no}</span></div>
        <div class="progress-track"><div class="progress-fill" style="width:${yesPercent}%"></div></div>`;
      card.querySelectorAll("button").forEach((button) => {
        button.addEventListener("click", async () => {
          await fetch("/api/poll", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question_key: key, answer: button.dataset.answer }),
          });
          loadPoll();
        });
      });
      pollContainer.appendChild(card);
    });
  }
  loadPoll();
}

const adminLogin = document.querySelector("#adminLogin");
if (adminLogin) {
  adminLogin.addEventListener("submit", async (event) => {
    event.preventDefault();
    const token = document.querySelector("#adminToken").value;
    try {
      const [metricsResponse, opportunitiesResponse, reportsResponse] = await Promise.all([
        fetch("/api/admin/metrics", { headers: { "X-Admin-Token": token } }),
        fetch("/api/admin/opportunities", { headers: { "X-Admin-Token": token } }),
        fetch("/api/admin/reports", { headers: { "X-Admin-Token": token } }),
      ]);
      if ([metricsResponse, opportunitiesResponse, reportsResponse].some((item) => item.status !== 200)) {
        throw new Error("Invalid or missing admin token");
      }
      const [metrics, opportunities, reports] = await Promise.all([
        metricsResponse.json(),
        opportunitiesResponse.json(),
        reportsResponse.json(),
      ]);
      document.querySelector("#adminOutput").innerHTML =
        `<div class="admin-cards">
          <article><strong>${metrics.unreviewed_reports}</strong><span>Unreviewed reports</span></article>
          <article><strong>${metrics.feedback_count}</strong><span>Feedback entries</span></article>
          <article><strong>${opportunities.length}</strong><span>Opportunities</span></article>
        </div>
        <h2>Verification tools</h2>
        ${opportunities.map((item) =>
          `<article class="admin-row">
            <div><strong>${escapeHtml(item.name)}</strong><span class="confidence ${item.confidence.toLowerCase()}">${escapeHtml(item.confidence)}</span></div>
            <button type="button" data-verify="${escapeHtml(item.id)}">Mark verified</button>
          </article>`
        ).join("")}
        <h2>Reports</h2>
        ${reports.length ? reports.map((item) => `<p>${escapeHtml(item.reason)} — ${escapeHtml(item.note || "")}</p>`).join("") : "<p>No reports.</p>"}`;
      document.querySelectorAll("[data-verify]").forEach((button) => {
        button.addEventListener("click", async () => {
          await fetch(`/api/admin/opportunities/${encodeURIComponent(button.dataset.verify)}/verify`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Admin-Token": token,
            },
            body: JSON.stringify({ verified_by: "Hackathon team" }),
          });
          adminLogin.dispatchEvent(new Event("submit"));
        });
      });
    } catch (error) {
      document.querySelector("#adminOutput").innerHTML =
        `<p class="auth-error">${escapeHtml(error.message)}</p>`;
    }
  });
}
