const profileForm = document.querySelector("#profileForm");
const feeForm = document.querySelector("#feeForm");
const matchesList = document.querySelector("#matchesList");
const matchTemplate = document.querySelector("#matchTemplate");

function getSavedPlan() {
  try {
    return JSON.parse(localStorage.getItem("bursary-radar-plan") || "[]");
  } catch {
    return [];
  }
}

function saveToPlan(match, button) {
  const plan = getSavedPlan();
  const alreadySaved = plan.some((item) => item.name === match.name);

  if (!alreadySaved) {
    plan.push({
      name: match.name,
      provider: match.provider,
      deadline: match.deadline,
      amount: match.amount,
    });
    localStorage.setItem("bursary-radar-plan", JSON.stringify(plan));
  }

  button.classList.remove("button-success");
  void button.offsetWidth;
  button.classList.add(alreadySaved ? "button-added" : "button-success");
  button.textContent = alreadySaved ? "Already in plan" : "Added to plan";
  button.setAttribute("aria-live", "polite");

  const reminderCard = document.querySelector(".reminder-card");
  reminderCard.classList.remove("notice-pulse");
  void reminderCard.offsetWidth;
  reminderCard.classList.add("notice-pulse");
  document.querySelector("#smsText").textContent =
    alreadySaved
      ? `${match.name} is already saved in My Plan.`
      : `${match.name} was added to My Plan.`;

  window.setTimeout(() => {
    button.classList.remove("button-success", "button-added");
    button.textContent = "Add to plan";
  }, 2400);
}

function formDataAsObject(form) {
  const data = new FormData(form);
  return Object.fromEntries(data.entries());
}

profileForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(profileForm);
  const profile = {
    level: formData.get("level"),
    institution_type: formData.get("institution_type"),
    county: formData.get("county"),
    constituency: formData.get("constituency"),
    need_flag: formData.has("need_flag"),
    disability: formData.has("disability"),
  };

  const response = await fetch("/api/matches", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile),
  });
  const matches = await response.json();
  document.querySelector("#matchCount").textContent =
    `${matches.length} ${matches.length === 1 ? "match" : "matches"}`;
  matchesList.replaceChildren();

  matches.forEach((match) => {
    const node = matchTemplate.content.cloneNode(true);
    const card = node.querySelector(".match-card");
    const confidence = node.querySelector(".confidence");
    confidence.textContent = `${match.confidence} confidence`;
    confidence.classList.add(match.confidence.toLowerCase());
    node.querySelector("h3").textContent = match.name;
    node.querySelector(".provider").textContent = match.provider;
    node.querySelector(".deadline").textContent =
      `Deadline: ${match.deadline}`;
    node.querySelector(".amount").textContent = match.amount;
    node.querySelector(".source-link").href = match.source_url;

    node.querySelector(".plan-button").addEventListener("click", (event) => {
      saveToPlan(match, event.currentTarget);
    });

    node.querySelector(".remind-button").addEventListener("click", async () => {
      const smsResponse = await fetch("/api/simulate-sms", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ opportunity: match.name }),
      });
      const sms = await smsResponse.json();
      document.querySelector("#smsText").textContent = sms.message;
      document.querySelector(".reminder-card").scrollIntoView({ behavior: "smooth" });
    });
    matchesList.appendChild(card);
  });

  if (!matches.length) {
    matchesList.innerHTML =
      '<div class="empty-state">No matches found for this profile. Try another constituency or level.</div>';
  }
});

feeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = formDataAsObject(feeForm);
  const response = await fetch("/api/fee-gap", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      fees: values.fees,
      scholarship: values.scholarship,
      helb: values.helb,
    }),
  });
  const result = await response.json();
  if (result.error) {
    alert(result.error);
    return;
  }
  document.querySelector("#gapAmount").textContent =
    `KES ${Number(result.gap).toLocaleString("en-KE")}`;
});

const smsButton = document.querySelector("#smsButton");
if (smsButton) {
  smsButton.addEventListener("click", async () => {
    const response = await fetch("/api/simulate-sms", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ opportunity: "your bursary opportunity" }),
    });
    const result = await response.json();
    document.querySelector("#smsText").textContent = result.message;
  });
}

document.addEventListener("click", (event) => {
  const button = event.target.closest(
    "button.primary-button, button.secondary-button, button.outline-button, button.auth-primary, button.auth-secondary"
  );
  if (!button || button.classList.contains("plan-button")) return;

  button.classList.remove("clicked");
  void button.offsetWidth;
  button.classList.add("clicked");
  window.setTimeout(() => button.classList.remove("clicked"), 420);
});
