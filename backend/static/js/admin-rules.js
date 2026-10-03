/* Admin triage rule editor. */

const rulesBody = document.getElementById("rules-body");
const ruleForm = document.getElementById("rule-form");
const ruleMsg = document.getElementById("rule-msg");

let reference = { categories: [], departments: [], priorities: [] };

function option(value, label, selected) {
  const el = document.createElement("option");
  el.value = value;
  el.textContent = label;
  if (selected) el.selected = true;
  return el;
}

async function loadReference() {
  try {
    reference = await apiFetch("/admin/reference-data");
    const cat = document.getElementById("category-select");
    const dept = document.getElementById("dept-select");
    const prio = document.getElementById("priority-select");

    cat.innerHTML = "";
    cat.appendChild(option("", "(none)"));
    reference.categories.forEach((c) => cat.appendChild(option(c.id, c.name)));

    dept.innerHTML = "";
    dept.appendChild(option("", "(none)"));
    reference.departments.forEach((d) => dept.appendChild(option(d.id, d.name)));

    prio.innerHTML = "";
    reference.priorities.forEach((p) =>
      prio.appendChild(option(p.id, `${p.code} (${p.sla_hours}h)`, p.code === "MEDIUM"))
    );
  } catch (err) {
    ruleMsg.innerHTML = `<div class="alert alert-danger small">Could not load reference data: ${err.message}</div>`;
  }
}

async function loadRules() {
  try {
    const rules = await apiFetch("/admin/rules");
    document.getElementById("rule-count").textContent = `${rules.length} rule(s)`;

    if (!rules.length) {
      rulesBody.innerHTML = '<tr><td colspan="9" class="text-muted">No rules configured.</td></tr>';
      return;
    }

    rulesBody.innerHTML = rules
      .map(
        (r) => `<tr class="${r.is_active ? "" : "opacity-50"}">
          <td>${r.rule_id}</td>
          <td><code class="small">${r.rule_type}</code></td>
          <td>${r.category_code || "-"}</td>
          <td>${r.dept_code || "-"}</td>
          <td>${r.keyword || "-"}</td>
          <td>${r.priority_code || "-"}</td>
          <td>${r.match_weight}</td>
          <td>${r.is_active
            ? '<span class="badge text-bg-success">active</span>'
            : '<span class="badge text-bg-secondary">disabled</span>'}</td>
          <td>${r.is_active
            ? `<button class="btn btn-sm btn-outline-secondary deactivate-btn" data-id="${r.rule_id}">Disable</button>`
            : ""}</td>
        </tr>`
      )
      .join("");

    rulesBody.querySelectorAll(".deactivate-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await apiFetch(`/admin/rules/${btn.dataset.id}/deactivate`, { method: "POST" });
          loadRules();
        } catch (err) {
          alert(err.message);
        }
      });
    });
  } catch (err) {
    rulesBody.innerHTML = `<tr><td colspan="9" class="text-danger">${err.message}</td></tr>`;
  }
}

if (ruleForm) {
  ruleForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    ruleMsg.innerHTML = '<div class="alert alert-info py-1 small">Saving rule...</div>';

    const raw = formToObject(ruleForm);
    const payload = {
      rule_type: raw.rule_type,
      category_id: raw.category_id ? Number(raw.category_id) : null,
      dept_id: raw.dept_id ? Number(raw.dept_id) : null,
      priority_id: raw.priority_id ? Number(raw.priority_id) : null,
      keyword: raw.keyword || null,
      match_weight: raw.match_weight ? Number(raw.match_weight) : 0,
    };

    try {
      const created = await apiFetch("/admin/rules", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      ruleMsg.innerHTML = `<div class="alert alert-success py-1 small">
        Rule ${created.rule_id} created. It applies to the very next complaint.
      </div>`;
      ruleForm.reset();
      loadRules();
    } catch (err) {
      ruleMsg.innerHTML = `<div class="alert alert-danger py-1 small">${err.message}</div>`;
    }
  });

  (async () => {
    await loadReference();
    await loadRules();
  })();
}

const previewBtn = document.getElementById("preview-btn");
if (previewBtn) {
  previewBtn.addEventListener("click", async () => {
    const description = document.getElementById("preview-text").value.trim();
    const box = document.getElementById("preview-result");

    if (description.length < 3) {
      box.innerHTML = '<div class="alert alert-secondary py-1 small">Enter some text first.</div>';
      return;
    }

    box.innerHTML = '<div class="alert alert-info py-1 small">Classifying...</div>';
    try {
      // Classify first to find the category, then preview the rule outcome.
      const c = await apiFetch("/ml/classify", {
        method: "POST",
        body: JSON.stringify({ subject: "preview", description }),
      });
      const preview = await apiFetch("/admin/rules/preview", {
        method: "POST",
        body: JSON.stringify({ category_id: c.predicted_category_id, description }),
      });

      const cat = reference.categories.find((x) => x.id === c.predicted_category_id);
      const prio = reference.priorities.find((x) => x.id === preview.priority_id);
      const dept = reference.departments.find((x) => x.id === preview.dept_id);

      const rules = (preview.matched_rules || [])
        .map((r) => `<code class="me-1 small">${r.type}${r.keyword ? `: ${r.keyword}` : ""}</code>`)
        .join(" ");

      box.innerHTML = `<div class="alert alert-light border small">
        <div><strong>Category:</strong> ${cat ? cat.name : c.predicted_category_code}
             (${(c.confidence * 100).toFixed(1)}% confidence${c.is_fallback ? ", heuristic" : ""})</div>
        <div><strong>Priority:</strong> ${prio ? prio.code : preview.priority_id}
             via <em>${preview.priority_source}</em></div>
        <div><strong>Department:</strong> ${dept ? dept.name : preview.dept_id}</div>
        ${rules ? `<div class="mt-1">Rules matched: ${rules}</div>` : ""}
      </div>`;
    } catch (err) {
      box.innerHTML = `<div class="alert alert-danger py-1 small">${err.message}</div>`;
    }
  });
}