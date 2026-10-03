/* Shared front-end helpers: token storage and JSON fetch wrappers. */

const API = "/api/v1";

function getToken() {
  return localStorage.getItem("access_token");
}

function setTokens(access, refresh) {
  localStorage.setItem("access_token", access);
  localStorage.setItem("refresh_token", refresh);
}

function clearTokens() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
}

/* Fetch wrapper.
 *
 * IMPORTANT: Content-Type is only set for JSON bodies. Passing a FormData body
 * (file upload) must let the browser set multipart/form-data itself, including
 * the boundary. Forcing application/json on FormData produces a request the
 * server cannot parse - 400 with an unhelpful message.
 */
async function apiFetch(path, options = {}) {
  const { raw, headers: customHeaders, body, ...rest } = options;
  const headers = Object.assign({}, customHeaders || {});

  const isFormData = typeof FormData !== "undefined" && body instanceof FormData;
  if (!isFormData && body !== undefined && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(`${API}${path}`, Object.assign({}, rest, { body, headers }));
  let data = null;
  try {
    data = await response.json();
  } catch (e) {
    data = { detail: `Unexpected response (HTTP ${response.status})` };
  }
  if (!response.ok) {
    const err = new Error(data.detail || "Request failed");
    err.status = response.status;
    throw err;
  }
  return data;
}

function formToObject(form) {
  const out = {};
  new FormData(form).forEach((value, key) => {
    if (value !== "") out[key] = value;
  });
  return out;
}

/* ---- Login ---- */
const loginForm = document.getElementById("login-form");
if (loginForm) {
  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = document.getElementById("login-msg");
    msg.innerHTML = '<div class="alert alert-info">Signing in...</div>';
    try {
      const data = await apiFetch("/auth/login", {
        method: "POST",
        body: JSON.stringify(formToObject(loginForm)),
      });
      setTokens(data.access_token, data.refresh_token);
      msg.innerHTML = `<div class="alert alert-success">Welcome, ${data.user.full_name}. Redirecting...</div>`;
      setTimeout(() => (window.location.href = "/complaints"), 600);
    } catch (err) {
      msg.innerHTML = `<div class="alert alert-danger">${err.message}</div>`;
    }
  });
}

/* ---- Register ---- */
const registerForm = document.getElementById("register-form");
if (registerForm) {
  registerForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = document.getElementById("register-msg");
    msg.innerHTML = '<div class="alert alert-info">Creating account...</div>';
    try {
      const data = await apiFetch("/auth/register", {
        method: "POST",
        body: JSON.stringify(formToObject(registerForm)),
      });
      msg.innerHTML = `<div class="alert alert-success">Account created for ${data.username}. You can sign in now.</div>`;
      registerForm.reset();
    } catch (err) {
      msg.innerHTML = `<div class="alert alert-danger">${err.message}</div>`;
    }
  });
}

/* ---- Complaint list ---- */
const complaintsBody = document.getElementById("complaints-body");
const listSubtitle = document.getElementById("list-subtitle");
const searchInput = document.getElementById("search");
const statusFilter = document.getElementById("filter-status");

/* Escape text before interpolating into innerHTML. Complaint subjects and
   comments are user-supplied; injecting them raw is a stored-XSS vector. */
function esc(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

const STATUS_LABELS = {
  SUBMITTED: "Submitted",
  TRIAGED: "Triaged",
  ASSIGNED: "Assigned",
  IN_PROGRESS: "In progress",
  RESOLVED: "Resolved",
  CLOSED: "Closed",
  REJECTED: "Rejected",
};

const PRIORITY_CLASS = {
  LOW: "text-bg-success",
  MEDIUM: "text-bg-info",
  HIGH: "text-bg-warning",
  CRITICAL: "text-bg-danger",
};

const STATUS_CLASS = {
  SUBMITTED: "text-bg-secondary",
  TRIAGED: "text-bg-info",
  ASSIGNED: "text-bg-primary",
  IN_PROGRESS: "text-bg-warning",
  RESOLVED: "text-bg-success",
  CLOSED: "text-bg-dark",
  REJECTED: "text-bg-danger",
};

function statusBadge(code) {
  const cls = STATUS_CLASS[code] || "text-bg-secondary";
  return `<span class="badge ${cls}">${esc(STATUS_LABELS[code] || code || "")}</span>`;
}

function priorityBadge(code) {
  const cls = PRIORITY_CLASS[code] || "text-bg-secondary";
  return `<span class="badge ${cls}">${esc(code || "")}</span>`;
}

function renderComplaints(data) {
  if (!data.items.length) {
    complaintsBody.innerHTML =
      '<tr><td colspan="6" class="text-muted py-4 text-center">No complaints found.</td></tr>';
    return;
  }

  complaintsBody.innerHTML = data.items
    .map(
      (c) => `<tr>
        <td data-label="Ticket">
          <a href="/complaints/${c.complaint_id}">${esc(c.ticket_no)}</a>
        </td>
        <td data-label="Subject">${esc(c.subject)}</td>
        <td data-label="Status">${statusBadge(c.status_code)}</td>
        <td data-label="Priority">${priorityBadge(c.priority_code)}</td>
        <td data-label="Department">${esc(c.dept_name || "")}</td>
        <td data-label="Raised">${esc(new Date(c.created_at).toLocaleDateString())}</td>
      </tr>`
    )
    .join("");
}

async function loadComplaints() {
  try {
    const params = new URLSearchParams({ page_size: "50" });
    if (searchInput && searchInput.value.trim()) {
      params.set("search", searchInput.value.trim());
    }
    if (statusFilter && statusFilter.value) {
      params.set("status_id", statusFilter.value);
    }

    const data = await apiFetch(`/complaints?${params.toString()}`);
    renderComplaints(data);
    if (listSubtitle) {
      listSubtitle.textContent = `${data.total} complaint${data.total === 1 ? "" : "s"} visible to you`;
    }
  } catch (err) {
    complaintsBody.innerHTML = `<tr><td colspan="6" class="text-danger">${esc(err.message)}</td></tr>`;
    if (listSubtitle) listSubtitle.textContent = "";
  }
}

if (complaintsBody) {
  // Populate the status filter from the reference data the API exposes.
  if (statusFilter) {
    Object.entries(STATUS_LABELS).forEach(([code, label]) => {
      const opt = document.createElement("option");
      opt.value = code;
      opt.textContent = label;
      statusFilter.appendChild(opt);
    });
  }

  loadComplaints();

  let listTimer = null;
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      clearTimeout(listTimer);
      listTimer = setTimeout(loadComplaints, 350);
    });
  }
  if (statusFilter) statusFilter.addEventListener("change", loadComplaints);
}

/* ---- Complaint detail ---- */
const detailBox = document.getElementById("complaint-detail");
if (detailBox) {
  const id = window.location.pathname.split("/").pop();

  (async () => {
    try {
      const c = await apiFetch(`/complaints/${id}`);
      document.getElementById("detail-title").textContent = c.subject;
      document.getElementById("detail-ticket").textContent =
        `${c.ticket_no} · raised by ${c.reporter_name || "unknown"}`;

      detailBox.innerHTML = `<div class="card"><div class="card-body">
        <p style="white-space: pre-wrap">${esc(c.description)}</p>
        <div class="d-flex flex-wrap gap-2 mt-3">
          ${statusBadge(c.status_code)}
          ${priorityBadge(c.priority_code)}
          <span class="badge text-bg-light border">${esc(c.dept_name || "")}</span>
          ${c.is_user_overridden
            ? '<span class="badge text-bg-light border" title="The submitter changed the auto-suggested category">edited by user</span>'
            : ""}
        </div>
        <dl class="row small mt-3 mb-0">
          <dt class="col-5 col-sm-3">Raised</dt>
          <dd class="col-7 col-sm-9">${esc(new Date(c.created_at).toLocaleString())}</dd>
          <dt class="col-5 col-sm-3">Priority</dt>
          <dd class="col-7 col-sm-9">${esc(c.priority_code || "")}${
            c.category_confidence !== null && c.category_confidence !== undefined
              ? ` <span class="text-muted">(classifier ${(c.category_confidence * 100).toFixed(0)}% confident)</span>`
              : ""
          }</dd>
          ${c.resolved_at
            ? `<dt class="col-5 col-sm-3">Resolved</dt>
               <dd class="col-7 col-sm-9">${esc(new Date(c.resolved_at).toLocaleString())}</dd>`
            : ""}
        </dl>
      </div></div>`;
    } catch (err) {
      detailBox.innerHTML = `<div class="alert alert-danger">${esc(err.message)}</div>`;
    }
  })();

  /* ---- photo gallery ---- */
  const grid = document.getElementById("attachments-grid");
  const emptyNote = document.getElementById("attachments-empty");
  const attachInput = document.getElementById("photo-input-detail");
  const attachMsg = document.getElementById("attach-msg");

  function humanSize(bytes) {
    if (!bytes && bytes !== 0) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  async function loadAttachments() {
    if (!grid) return;
    try {
      const data = await apiFetch(`/complaints/${id}/attachments`);
      const items = data.items || [];

      if (!items.length) {
        grid.innerHTML = "";
        emptyNote.classList.remove("d-none");
        return;
      }

      emptyNote.classList.add("d-none");
      grid.innerHTML = items
        .map(
          (a) => `<div class="col-6 col-md-4 col-lg-3">
            <a href="${esc(a.url)}" target="_blank" rel="noopener">
              <img class="attachment-thumb" src="${esc(a.url)}"
                   alt="${esc(a.file_name)}" loading="lazy">
            </a>
            <div class="small text-muted mt-1 text-truncate">${esc(a.file_name)}</div>
            <div class="small text-muted">${esc(humanSize(a.file_size))}</div>
          </div>`
        )
        .join("");
    } catch (err) {
      grid.innerHTML = `<div class="col-12"><div class="alert alert-secondary small">${esc(err.message)}</div></div>`;
    }
  }

  if (attachInput) {
    attachInput.addEventListener("change", async () => {
      const files = Array.from(attachInput.files || []);
      attachInput.value = "";
      if (!files.length) return;

      attachMsg.innerHTML = '<div class="alert alert-info py-1 small mb-0">Uploading&hellip;</div>';
      let ok = 0;
      const errors = [];

      for (const file of files) {
        const body = new FormData();
        body.append("file", file, file.name);
        try {
          await apiFetch(`/complaints/${id}/attachments`, { method: "POST", body });
          ok += 1;
        } catch (err) {
          errors.push(`${file.name}: ${err.message}`);
        }
      }

      if (!errors.length) {
        attachMsg.innerHTML = `<div class="alert alert-success py-1 small mb-0">${ok} photo(s) attached.</div>`;
      } else {
        attachMsg.innerHTML = `<div class="alert alert-warning py-1 small mb-0">${
          ok ? `${ok} attached. ` : ""
        }Failed: ${errors.join("; ")}</div>`;
      }
      await loadAttachments();
    });
  }

  loadAttachments();

  (async () => {
    const box = document.getElementById("timeline");
    try {
      const t = await apiFetch(`/complaints/${id}/timeline`);
      const events = t.events || [];
      const counter = document.getElementById("event-count");
      if (counter) counter.textContent = `${events.length} event${events.length === 1 ? "" : "s"}`;

      if (!events.length) {
        box.innerHTML = '<p class="text-muted mb-0">No activity recorded yet.</p>';
        return;
      }
      box.innerHTML = events
        .map(
          (ev) => `<div class="timeline-item pb-2 mb-2">
            <div class="small text-muted">
              ${esc(new Date(ev.occurred_at).toLocaleString())} &middot;
              ${esc(ev.actor?.username || "")}
            </div>
            <div><strong>${esc(ev.event_type)}</strong>
              ${ev.payload?.body ? `— ${esc(ev.payload.body)}` : ""}
              ${ev.payload?.file_name ? `— ${esc(ev.payload.file_name)}` : ""}
            </div>
          </div>`
        )
        .join("");
    } catch (err) {
      box.innerHTML = `<p class="text-danger mb-0">${esc(err.message)}</p>`;
    }
  })();

  const commentForm = document.getElementById("comment-form");
  if (commentForm) {
    commentForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await apiFetch(`/complaints/${id}/comments`, {
          method: "POST",
          body: JSON.stringify(formToObject(commentForm)),
        });
        commentForm.reset();
        loadAttachments();
        const box = document.getElementById("timeline");
        const refreshed = await apiFetch(`/complaints/${id}/timeline`);
        const events = refreshed.events || [];
        const counter = document.getElementById("event-count");
        if (counter) counter.textContent = `${events.length} events`;
        box.innerHTML = events
          .map(
            (ev) => `<div class="timeline-item pb-2 mb-2">
              <div class="small text-muted">${esc(new Date(ev.occurred_at).toLocaleString())} &middot; ${esc(ev.actor?.username || "")}</div>
              <div><strong>${esc(ev.event_type)}</strong> ${ev.payload?.body ? `— ${esc(ev.payload.body)}` : ""}</div>
            </div>`
          )
          .join("");
      } catch (err) {
        alert(err.message);
      }
    });
  }
}
