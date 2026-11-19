const bursaryForm = document.querySelector("#bursaryForm");
const adminStatus = document.querySelector("#adminStatus");
const bursaryList = document.querySelector("#bursaryList");
const countySelect = document.querySelector("#bursaryCounties");
const constituencySelect = document.querySelector("#bursaryConstituencies");
const submitButton = document.querySelector("#submitBursary");
let countyLocations = {};

function showStatus(message, kind = "") {
  adminStatus.textContent = message;
  adminStatus.className = `admin-status ${kind}`.trim();
}

async function responseError(response) {
  const body = await response.json().catch(() => ({}));
  return body.error?.message || `Request failed (${response.status})`;
}

function selectedValues(name) {
  return [...bursaryForm.querySelectorAll(`input[name="${name}"]:checked`)]
    .map((input) => input.value);
}

function optionalInteger(name) {
  const value = new FormData(bursaryForm).get(name);
  return value === "" || value === null ? null : Number(value);
}

function refreshConstituencies() {
  const previous = new Set([...constituencySelect.selectedOptions].map((option) => option.value));
  const counties = [...countySelect.selectedOptions].map((option) => option.value);
  const constituencies = [...new Set(counties.flatMap((county) => countyLocations[county] || []))];
  constituencySelect.replaceChildren();
  constituencies.forEach((constituency) => {
    const option = new Option(constituency, constituency);
    option.selected = previous.has(constituency);
    constituencySelect.add(option);
  });
  constituencySelect.disabled = counties.length === 0;
}

async function loadCountyOptions() {
  const response = await fetch("/static/kenya_locations.json");
  if (!response.ok) throw new Error("Could not load the county list.");
  const data = await response.json();
  countyLocations = data.counties;
  countySelect.replaceChildren();
  Object.keys(countyLocations).forEach((county) => {
    countySelect.add(new Option(county, county));
  });
  countySelect.disabled = false;
}

async function loadBursaries() {
  bursaryList.textContent = "Loading bursaries...";
  try {
    const response = await fetch("/api/admin/opportunities");
    if (!response.ok) throw new Error(await responseError(response));
    const opportunities = await response.json();
    bursaryList.replaceChildren();
    if (!opportunities.length) {
      bursaryList.textContent = "No bursaries have been added yet.";
      return;
    }

    opportunities.forEach((opportunity) => {
      const card = document.createElement("article");
      card.className = "admin-bursary-card";
      const title = document.createElement("h3");
      title.textContent = opportunity.name;
      const provider = document.createElement("p");
      provider.textContent = opportunity.provider;
      const details = document.createElement("p");
      const levels = (opportunity.levels || []).join(", ") || "All levels / not specified";
      const disbursement = opportunity.disbursement_start && opportunity.disbursement_end
        ? `${opportunity.disbursement_start} to ${opportunity.disbursement_end}`
        : "Not provided";
      details.textContent =
        `${opportunity.number_of_bursaries ?? "—"} bursaries · ${levels} · ` +
        `Disbursement: ${disbursement} · Status: ${opportunity.status || "unknown"}`;
      const verified = document.createElement("p");
      verified.textContent = opportunity.last_verified_at
        ? `Last verified ${opportunity.last_verified_at} by ${opportunity.verified_by || "unknown"}`
        : "Not verified";
      const source = document.createElement("a");
      const sourceUrl = new URL(opportunity.source_url, window.location.origin);
      if (!["http:", "https:"].includes(sourceUrl.protocol)) {
        throw new Error("An opportunity has an invalid source URL.");
      }
      source.href = sourceUrl.href;
      source.target = "_blank";
      source.rel = "noopener noreferrer";
      source.textContent = "Open official source";
      const verifyButton = document.createElement("button");
      verifyButton.type = "button";
      verifyButton.textContent = "Mark verified now";
      verifyButton.addEventListener("click", async () => {
        verifyButton.disabled = true;
        try {
          const response = await fetch(`/api/admin/opportunities/${encodeURIComponent(opportunity.id)}/verify`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({}),
          });
          if (!response.ok) throw new Error(await responseError(response));
          showStatus(`${opportunity.name} marked as verified.`, "success");
          await loadBursaries();
        } catch (error) {
          showStatus(error.message || "Could not update verification.", "error");
          verifyButton.disabled = false;
        }
      });
      card.append(title, provider, details, verified, source, verifyButton);
      bursaryList.appendChild(card);
    });
  } catch (error) {
    bursaryList.textContent = error.message || "Could not load bursaries.";
  }
}

bursaryForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedValues("levels").length) {
    showStatus("Select at least one eligible study level.", "error");
    return;
  }

  const formData = new FormData(bursaryForm);
  const payload = {
    name: formData.get("name").trim(),
    provider: formData.get("provider").trim(),
    provider_type: formData.get("provider_type"),
    description: formData.get("description").trim(),
    levels: selectedValues("levels"),
    institution_types: selectedValues("institution_types"),
    institution_name: formData.get("institution_name").trim() || null,
    counties: [...countySelect.selectedOptions].map((option) => option.value),
    constituencies: [...constituencySelect.selectedOptions].map((option) => option.value),
    eligibility_notes: formData.get("eligibility_notes").trim(),
    need_flags: selectedValues("need_flags"),
    gender_restriction: formData.get("gender_restriction") || null,
    amount_published: bursaryForm.elements.amount_published.checked,
    amount_min: optionalInteger("amount_min"),
    amount_max: optionalInteger("amount_max"),
    amount_note: formData.get("amount_note").trim(),
    number_of_bursaries: Number(formData.get("number_of_bursaries")),
    disbursement_start: formData.get("disbursement_start"),
    disbursement_end: formData.get("disbursement_end"),
    deadline: formData.get("deadline") || null,
    window_note: formData.get("window_note").trim(),
    is_recurring: bursaryForm.elements.is_recurring.checked,
    status: formData.get("status"),
    documents_required: formData.get("documents_required").split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
    how_to_apply: formData.get("how_to_apply").trim(),
    apply_url: formData.get("apply_url").trim() || null,
    source_url: formData.get("source_url").trim(),
  };

  submitButton.disabled = true;
  showStatus("Saving bursary...", "pending");
  try {
    const response = await fetch("/api/admin/bursaries", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(await responseError(response));
    bursaryForm.reset();
    constituencySelect.replaceChildren();
    constituencySelect.disabled = true;
    await loadBursaries();
    showStatus("Bursary saved and added to the directory.", "success");
  } catch (error) {
    showStatus(error.message || "Could not save the bursary.", "error");
  } finally {
    submitButton.disabled = false;
  }
});

countySelect.addEventListener("change", refreshConstituencies);
document.querySelector("#refreshBursaries").addEventListener("click", loadBursaries);

loadCountyOptions().catch((error) => {
  countySelect.disabled = true;
  constituencySelect.disabled = true;
  showStatus(error.message, "error");
});
loadBursaries();
