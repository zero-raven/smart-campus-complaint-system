/* New-complaint form: live NLP triage preview + optional photo attachments.
 *
 * Mobile-first: the dropzone is a full-width tap target and works with touch,
 * mouse and keyboard. Photos are uploaded AFTER the complaint exists, because
 * the complaint creation endpoint returns the id that the attachment endpoint
 * requires. Uploading first would mean holding the complaint in a two-phase
 * commit for no benefit.
 */

const MAX_FILES = 3;
const MAX_BYTES = 5 * 1024 * 1024;

const form = document.getElementById("complaint-form");
const suggestionBox = document.getElementById("suggestion-box");
const messageBox = document.getElementById("complaint-msg");

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("photo-input");
const previewGrid = document.getElementById("preview-grid");
const photoMsg = document.getElementById("photo-msg");

/** Selected files, kept as File objects so the real bytes are submitted. */
let selectedFiles = [];

let debounceTimer = null;

/* ------------------------------------------------------------------ photos */

function humanSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function renderPreviews() {
  previewGrid.innerHTML = "";
  selectedFiles.forEach((file, index) => {
    const item = document.createElement("div");
    item.className = "preview-item";

    const img = document.createElement("img");
    img.src = URL.createObjectURL(file);
    img.alt = file.name;
    img.addEventListener("load", () => URL.revokeObjectURL(img.src));

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "preview-remove";
    remove.innerHTML = "&times;";
    remove.setAttribute("aria-label", `Remove ${file.name}`);
    remove.addEventListener("click", () => {
      selectedFiles.splice(index, 1);
      renderPreviews();
    });

    item.appendChild(img);
    item.appendChild(remove);
    previewGrid.appendChild(item);
  });

  const remaining = MAX_FILES - selectedFiles.length;
  const hint = dropzone.querySelector(".small");
  if (hint) {
    hint.textContent =
      selectedFiles.length === 0
        ? `Up to ${MAX_FILES} images, 5 MB each. JPEG, PNG, WebP, GIF or HEIC.`
        : `${selectedFiles.length} selected (${remaining} slot${remaining === 1 ? "" : "s"} left) · ${humanSize(
            selectedFiles.reduce((sum, f) => sum + f.size, 0)
          )} total`;
  }
}

function addFiles(fileList) {
  const incoming = Array.from(fileList || []);
  let rejected = [];

  for (const file of incoming) {
    if (selectedFiles.length >= MAX_FILES) {
      rejected.push(`${file.name} (limit is ${MAX_FILES} photos)`);
      continue;
    }
    if (file.size > MAX_BYTES) {
      rejected.push(`${file.name} (${humanSize(file.size)}, limit is 5 MB)`);
      continue;
    }
    if (!file.type.startsWith("image/")) {
      rejected.push(`${file.name} (not an image)`);
      continue;
    }
    selectedFiles.push(file);
  }

  renderPreviews();

  photoMsg.innerHTML = rejected.length
    ? `<div class="alert alert-warning py-1 small mb-0">Not added: ${rejected.join(", ")}</div>`
    : "";
}

if (dropzone) {
  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });

  fileInput.addEventListener("change", () => {
    addFiles(fileInput.files);
    fileInput.value = ""; // allow re-selecting the same file
  });

  // Drag and desktop drop. Guarded so it never blocks touch interaction.
  ["dragenter", "dragover"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add("is-dragover");
    })
  );
  ["dragleave", "drop"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.remove("is-dragover");
    })
  );
  dropzone.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
}

/* ------------------------------------------------------------------ upload */

async function uploadPhotos(complaintId) {
  if (!selectedFiles.length) return { uploaded: 0, failed: 0, errors: [] };

  let uploaded = 0;
  const errors = [];

  for (const file of selectedFiles) {
    const body = new FormData();
    body.append("file", file, file.name);
    try {
      await apiFetch(`/complaints/${complaintId}/attachments`, {
        method: "POST",
        body,
      });
      uploaded += 1;
    } catch (err) {
      errors.push(`${file.name}: ${err.message}`);
    }
  }

  return { uploaded, failed: selectedFiles.length - uploaded, errors };
}

/* ------------------------------------------------------------------- triage */

function renderSuggestion(data) {
  const top = (data.top_k || [])
    .map(
      (p) => `<li class="mb-2">
        <div class="d-flex justify-content-between small">
          <span>${p.label}</span><span>${(p.score * 100).toFixed(1)}%</span>
        </div>
        <div class="confidence-bar"><span style="width:${(p.score * 100).toFixed(1)}%"></span></div>
      </li>`
    )
    .join("");

  const rules = (data.matched_rules || [])
    .map((r) => `<code class="me-1 small">${r.type}${r.keyword ? `: ${r.keyword}` : ""}</code>`)
    .join(" ");

  const fallbackNote = data.is_fallback
    ? '<div class="alert alert-warning py-1 small mb-2">Heuristic preview &mdash; no trained model is active yet.</div>'
    : "";

  suggestionBox.innerHTML = `<div class="card bg-light"><div class="card-body">
    <div class="fw-semibold mb-2">Suggested triage</div>
    ${fallbackNote}
    <dl class="row mb-2 small">
      <dt class="col-5 col-sm-4">Category</dt>
      <dd class="col-7 col-sm-8">${data.predicted_category_code}
        <span class="text-muted">(${(data.confidence * 100).toFixed(1)}%)</span></dd>
      <dt class="col-5 col-sm-4">Priority</dt>
      <dd class="col-7 col-sm-8">${data.suggested_priority_id}
        <span class="text-muted">via ${data.priority_source}</span></dd>
      <dt class="col-5 col-sm-4">Department</dt>
      <dd class="col-7 col-sm-8">${data.suggested_dept_id}</dd>
    </dl>
    ${rules ? `<p class="small mb-2">Rules matched: ${rules}</p>` : ""}
    <ul class="list-unstyled small mb-0">${top}</ul>
  </div></div>`;
}

async function previewTriage() {
  const subject = form.subject.value.trim();
  const description = form.description.value.trim();
  if (description.length < 10) return;

  try {
    const data = await apiFetch("/ml/classify", {
      method: "POST",
      body: JSON.stringify({ subject, description }),
    });
    renderSuggestion(data);
  } catch (err) {
    suggestionBox.innerHTML = `<div class="alert alert-secondary small">Preview unavailable: ${err.message}</div>`;
  }
}

/* -------------------------------------------------------------------- submit */

if (form) {
  renderPreviews();

  form.addEventListener("input", (e) => {
    if (e.target.name !== "description") return;
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(previewTriage, 800);
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    if (!form.checkValidity()) {
      form.classList.add("was-validated");
      form.reportValidity();
      return;
    }

    const submitBtn = document.getElementById("submit-btn");
    submitBtn.disabled = true;
    messageBox.innerHTML = '<div class="alert alert-info">Submitting&hellip;</div>';

    let created;
    try {
      created = await apiFetch("/complaints", {
        method: "POST",
        body: JSON.stringify(formToObject(form)),
      });
    } catch (err) {
      submitBtn.disabled = false;
      messageBox.innerHTML = `<div class="alert alert-danger">${err.message}</div>`;
      return;
    }

    const complaintId = created.complaint.complaint_id;

    // Photos are optional; a failure here must not lose the complaint, which
    // has already been created and is safe.
    if (selectedFiles.length) {
      messageBox.innerHTML = `<div class="alert alert-info">
        Complaint ${created.complaint.ticket_no} created. Uploading photos&hellip;
      </div>`;
      const result = await uploadPhotos(complaintId);

      if (result.failed === 0) {
        messageBox.innerHTML = `<div class="alert alert-success">
          Complaint <strong>${created.complaint.ticket_no}</strong> created with
          ${result.uploaded} photo${result.uploaded === 1 ? "" : "s"}.
          <a href="/complaints/${complaintId}">View complaint</a>
        </div>`;
      } else {
        messageBox.innerHTML = `<div class="alert alert-warning">
          Complaint <strong>${created.complaint.ticket_no}</strong> created, but
          ${result.failed} photo(s) failed to upload: ${result.errors.join("; ")}.
          <a href="/complaints/${complaintId}">View complaint</a>
        </div>`;
      }
    } else {
      messageBox.innerHTML = `<div class="alert alert-success">
        Complaint <strong>${created.complaint.ticket_no}</strong> created.
        <a href="/complaints/${complaintId}">View complaint</a>
      </div>`;
    }

    form.reset();
    form.classList.remove("was-validated");
    selectedFiles = [];
    renderPreviews();
    suggestionBox.innerHTML = "";
    submitBtn.disabled = false;
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}