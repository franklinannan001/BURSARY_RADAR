const profileForm = document.querySelector("#profileForm");
const feeForm = document.querySelector("#feeForm");
const matchesList = document.querySelector("#matchesList");
const matchTemplate = document.querySelector("#matchTemplate");

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
