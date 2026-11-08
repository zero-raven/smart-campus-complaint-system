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

  const response = await fetch(`${API}${path}`, Object.assign({}, rest, { body, headers, credentials: "include" }));
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

// Make apiFetch globally available for other scripts (classify.js, etc.)
window.apiFetch = apiFetch;

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
    .replace(/&/g, "&")
    .replace(/</g, "<")
    .replace(/>/g, ">")
    .replace(/"/g, '"')
    .replace(/'/g, "'");
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
    const colspan = (window.currentUser && window.currentUser.role === 'ADMIN') ? 7 : 6;
    complaintsBody.innerHTML =
      `<tr><td colspan="${colspan}" class="text-muted py-4 text-center">No complaints found.</td></tr>`;
    return;
  }

  const isAdmin = window.currentUser && window.currentUser.role === 'ADMIN';

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
        ${isAdmin ? `<td><button class="btn btn-sm btn-outline-danger delete-btn" data-id="${c.complaint_id}" data-ticket="${esc(c.ticket_no)}" title="Delete complaint">Delete</button></td>` : ''}
      </tr>`
    )
    .join("");

  // Attach delete button handlers
  if (isAdmin) {
    complaintsBody.querySelectorAll(".delete-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.dataset.id;
        try {
          await apiFetch(`/complaints/${id}`, { method: "DELETE" });
          loadComplaints();
        } catch (err) {
          alert(err.message);
        }
      });
    });
  }
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
    apiFetch("/reference/statuses")
      .then((data) => {
        const items = data.items || [];
        items.forEach((s) => {
          const opt = document.createElement("option");
          opt.value = s.status_id;
          opt.textContent = s.status_name;
          statusFilter.appendChild(opt);
        });
      })
      .catch(() => {
        // Fallback to hardcoded labels if API fails
        Object.entries(STATUS_LABELS).forEach(([code, label]) => {
          const opt = document.createElement("option");
          opt.value = code;
          opt.textContent = label;
          statusFilter.appendChild(opt);
        });
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

  // Status & priority & category & department selectors
  const statusSelect = document.getElementById("status-select");
  const prioritySelect = document.getElementById("priority-select");
  const categorySelect = document.getElementById("category-select");
  const deptSelect = document.getElementById("dept-select");
  const saveStatusBtn = document.getElementById("save-status-btn");
  const savePriorityBtn = document.getElementById("save-priority-btn");
  const saveCategoryBtn = document.getElementById("save-category-btn");
  const saveDeptBtn = document.getElementById("save-dept-btn");
  const actionButtons = document.getElementById("action-buttons");
  const statusHint = document.getElementById("status-hint");
  const priorityHint = document.getElementById("priority-hint");
  const categoryHint = document.getElementById("category-hint");
  const deptHint = document.getElementById("dept-hint");
  const statusRemarkRow = document.getElementById("status-remark-row");
  const statusRemarkInput = document.getElementById("status-remark");
  const statusRemarkHint = document.getElementById("status-remark-hint");

  let currentStatusId = null;
  let currentPriorityId = null;
  let currentCategoryId = null;
  let currentDeptId = null;
  let validTransitions = [];

  async function loadReferenceData() {
    try {
      const [statusesRes, prioritiesRes, categoriesRes, deptsRes, transitionsRes] = await Promise.all([
        apiFetch("/reference/statuses"),
        apiFetch("/reference/priorities"),
        apiFetch("/reference/categories"),
        apiFetch("/reference/departments"),
        apiFetch("/reference/transitions"),
      ]);
      const statuses = statusesRes.items || [];
      const priorities = prioritiesRes.items || [];
      const categories = categoriesRes.items || [];
      const departments = deptsRes.items || [];
      validTransitions = transitionsRes.items || [];

      if (statusSelect) {
        statusSelect.innerHTML = '<option value="">Select status...</option>' +
          statuses.map(s => `<option value="${s.status_id}">${esc(s.status_name)} (${esc(s.status_code)})</option>`).join("");
      }
      if (prioritySelect) {
        prioritySelect.innerHTML = '<option value="">Select priority...</option>' +
          priorities.map(p => `<option value="${p.priority_id}">${esc(p.priority_name)} (${esc(p.priority_code)})</option>`).join("");
      }
      if (categorySelect) {
        categorySelect.innerHTML = '<option value="">Select category...</option>' +
          categories.map(c => `<option value="${c.category_id}">${esc(c.category_name)} (${esc(c.category_code)})</option>`).join("");
      }
      if (deptSelect) {
        deptSelect.innerHTML = '<option value="">Select department...</option>' +
          departments.map(d => `<option value="${d.dept_id}">${esc(d.dept_name)} (${esc(d.dept_code)})</option>`).join("");
      }
    } catch (err) {
      console.warn("Failed to load reference data:", err);
    }
  }

  function filterStatusOptions() {
    if (!statusSelect || !currentStatusId) return;
    const user = window.currentUser;
    const userRole = user?.role || "STUDENT";

    // Admin and Staff can transition to ANY status (bypass state machine)
    if (userRole === "ADMIN" || userRole === "STAFF") {
        Array.from(statusSelect.options).forEach(opt => {
            if (!opt.value) return; // keep "Select status..."
            opt.style.display = "";
        });
        if (statusHint) {
            statusHint.textContent = `${userRole}: all statuses available`;
        }
        return;
    }

    // Find valid transitions from current status for user's role
    const allowed = validTransitions.filter(t => 
      t.from_status_id === currentStatusId && 
      (t.required_role === userRole || t.required_role === "ADMIN")
    );

    const allowedToIds = new Set(allowed.map(t => t.to_status_id));

    // Hide/show options based on valid transitions
    Array.from(statusSelect.options).forEach(opt => {
      if (!opt.value) return; // keep "Select status..."
      const show = allowedToIds.has(parseInt(opt.value));
      opt.style.display = show ? "" : "none";
      if (!show && opt.selected) {
        statusSelect.value = "";
      }
    });

    // Update hint
    if (statusHint) {
      if (allowed.length === 0) {
        statusHint.textContent = "No valid transitions from current status";
      } else {
        statusHint.textContent = `Valid: ${allowed.map(t => {
          const opt = statusSelect.querySelector(`option[value="${t.to_status_id}"]`);
          return opt ? opt.textContent : t.to_status_id;
        }).join(", ")}`;
      }
    }
  }

  function updateStatusRemark() {
    if (!statusSelect || !statusRemarkRow || !statusRemarkHint) return;
    const user = window.currentUser;
    const userRole = user?.role || "STUDENT";
    const selectedId = parseInt(statusSelect.value);
    if (!selectedId || !currentStatusId) {
      statusRemarkRow.style.display = "none";
      return;
    }

    // Admin and Staff: remark required for terminal statuses
    if (userRole === "ADMIN" || userRole === "STAFF") {
      const targetStatus = statusSelect.querySelector(`option[value="${selectedId}"]`);
      const targetCode = targetStatus ? targetStatus.textContent.match(/\(([^)]+)\)/)?.[1] : "";
      const terminalCodes = ["RESOLVED", "CLOSED", "REJECTED"];
      const needsRemark = terminalCodes.some(code => targetCode?.includes(code));
      if (needsRemark) {
        statusRemarkRow.style.display = "block";
        statusRemarkHint.textContent = "Remark is required for this transition";
        statusRemarkInput.required = true;
      } else {
        statusRemarkRow.style.display = "none";
        statusRemarkInput.required = false;
      }
      return;
    }

    // Student: check transition from validTransitions
    const transition = validTransitions.find(t => 
      t.from_status_id === currentStatusId && t.to_status_id === selectedId
    );
    if (transition && transition.requires_remark) {
      statusRemarkRow.style.display = "block";
      statusRemarkHint.textContent = "Remark is required for this transition";
      statusRemarkInput.required = true;
    } else {
      statusRemarkRow.style.display = "none";
      statusRemarkInput.required = false;
    }
  }

  function updateActionButtons() {
    const canChangeStatus = statusSelect && statusSelect.value && statusSelect.value != currentStatusId;
    const canChangePriority = prioritySelect && prioritySelect.value && prioritySelect.value != currentPriorityId;
    const canChangeCategory = categorySelect && categorySelect.value && categorySelect.value != currentCategoryId;
    const canChangeDept = deptSelect && deptSelect.value && deptSelect.value != currentDeptId;
    if (actionButtons) actionButtons.style.display = (canChangeStatus || canChangePriority || canChangeCategory || canChangeDept) ? "flex" : "none";
    if (saveStatusBtn) saveStatusBtn.disabled = !canChangeStatus;
    if (savePriorityBtn) savePriorityBtn.disabled = !canChangePriority;
    if (saveCategoryBtn) saveCategoryBtn.disabled = !canChangeCategory;
    if (saveDeptBtn) saveDeptBtn.disabled = !canChangeDept;
  }

  if (statusSelect) {
    statusSelect.addEventListener("change", () => {
      updateActionButtons();
      filterStatusOptions();
      updateStatusRemark();
    });
  }
  if (prioritySelect) prioritySelect.addEventListener("change", updateActionButtons);
  if (categorySelect) categorySelect.addEventListener("change", updateActionButtons);
  if (deptSelect) deptSelect.addEventListener("change", updateActionButtons);

  if (saveStatusBtn) {
    saveStatusBtn.addEventListener("click", async () => {
      if (!statusSelect.value || statusSelect.value == currentStatusId) return;
      const remark = statusRemarkInput?.value?.trim() || "";
      try {
        await apiFetch(`/complaints/${id}/status`, {
          method: "POST",
          body: JSON.stringify({ status_id: parseInt(statusSelect.value), remark }),
        });
        currentStatusId = parseInt(statusSelect.value);
        statusRemarkInput.value = "";
        updateActionButtons();
        filterStatusOptions();
        updateStatusRemark();
        loadAttachments(); // refresh timeline
      } catch (err) {
        alert(err.message);
      }
    });
  }

  if (savePriorityBtn) {
    savePriorityBtn.addEventListener("click", async () => {
      if (!prioritySelect.value || prioritySelect.value == currentPriorityId) return;
      try {
        await apiFetch(`/complaints/${id}/priority`, {
          method: "POST",
          body: JSON.stringify({ priority_id: parseInt(prioritySelect.value), remark: "" }),
        });
        currentPriorityId = parseInt(prioritySelect.value);
        updateActionButtons();
        loadAttachments(); // refresh timeline
      } catch (err) {
        alert(err.message);
      }
    });
  }

  if (saveCategoryBtn) {
    saveCategoryBtn.addEventListener("click", async () => {
      if (!categorySelect.value || categorySelect.value == currentCategoryId) return;
      try {
        await apiFetch(`/complaints/${id}/category`, {
          method: "POST",
          body: JSON.stringify({ category_id: parseInt(categorySelect.value), remark: "" }),
        });
        currentCategoryId = parseInt(categorySelect.value);
        updateActionButtons();
        loadAttachments(); // refresh timeline
      } catch (err) {
        alert(err.message);
      }
    });
  }

  if (saveDeptBtn) {
    saveDeptBtn.addEventListener("click", async () => {
      if (!deptSelect.value || deptSelect.value == currentDeptId) return;
      try {
        await apiFetch(`/complaints/${id}/department`, {
          method: "POST",
          body: JSON.stringify({ dept_id: parseInt(deptSelect.value), remark: "" }),
        });
        currentDeptId = parseInt(deptSelect.value);
        updateActionButtons();
        loadAttachments(); // refresh timeline
      } catch (err) {
        alert(err.message);
      }
    });
  }

  (async () => {
    try {
      const c = await apiFetch(`/complaints/${id}`);
      currentStatusId = c.status_id;
      currentPriorityId = c.priority_id;
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

      // Enable selectors if user has permission (staff/admin)
      const user = window.currentUser;
      if (user && (user.role === "STAFF" || user.role === "ADMIN")) {
        if (statusSelect) statusSelect.disabled = false;
        if (prioritySelect) prioritySelect.disabled = false;
        if (categorySelect) categorySelect.disabled = false;
        if (statusHint) statusHint.textContent = "Select a new status and click Save Status";
        if (priorityHint) priorityHint.textContent = "Select a new priority and click Save Priority";
        if (categoryHint) categoryHint.textContent = "Select a new category and click Save Category";
        if (user.role === "ADMIN") {
          if (deptSelect) deptSelect.disabled = false;
          if (deptHint) deptHint.textContent = "Select a new department and click Save Department";
        } else if (deptHint) {
          deptHint.textContent = "Only administrators can change department";
        }
      } else if (statusHint) {
        statusHint.textContent = "Only staff and administrators can change status";
      } else if (priorityHint) {
        priorityHint.textContent = "Only staff and administrators can change priority";
      } else if (categoryHint) {
        categoryHint.textContent = "Only staff and administrators can change category";
      }

      await loadReferenceData();

      // Set current values
      if (statusSelect) statusSelect.value = c.status_id || "";
      if (prioritySelect) prioritySelect.value = c.priority_id || "";
      if (categorySelect) categorySelect.value = c.category_id || "";
      if (deptSelect) deptSelect.value = c.dept_id || "";
      currentDeptId = c.dept_id;
      updateActionButtons();
      filterStatusOptions();
      updateStatusRemark();
    } catch (err) {
      detailBox.innerHTML = `<div class="alert alert-danger">${esc(err.message)}</div>`;
    }
  })();

  /* ---- photo gallery ---- */
  const grid = document.getElementById("attachments-grid");
  const emptyNote = document.getElementById("attachments-empty");
  const attachInput = document.getElementById("photo-input-detail");
  const attachMsg = document.getElementById("attach-msg-detail");
  const dropzone = document.getElementById("dropzone-detail");
  const previewGrid = document.getElementById("preview-grid-detail");

  let detailSelectedFiles = [];

  function humanSize(bytes) {
    if (!bytes && bytes !== 0) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function renderDetailPreviews() {
    if (!previewGrid) return;
    previewGrid.innerHTML = "";
    detailSelectedFiles.forEach((file, index) => {
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
        detailSelectedFiles.splice(index, 1);
        renderDetailPreviews();
      });

      item.appendChild(img);
      item.appendChild(remove);
      previewGrid.appendChild(item);
    });

    const remaining = 3 - detailSelectedFiles.length;
    const hint = dropzone?.querySelector(".small");
    if (hint) {
      hint.textContent =
        detailSelectedFiles.length === 0
          ? `Up to 3 images, 5 MB each. JPEG, PNG, WebP, GIF or HEIC.`
          : `${detailSelectedFiles.length} selected (${remaining} slot${remaining === 1 ? "" : "s"} left) · ${humanSize(
              detailSelectedFiles.reduce((sum, f) => sum + f.size, 0)
            )} total`;
    }
  }

  function addDetailFiles(fileList) {
    const incoming = Array.from(fileList || []);
    let rejected = [];

    for (const file of incoming) {
      if (detailSelectedFiles.length >= 3) {
        rejected.push(`${file.name} (limit is 3 photos)`);
        continue;
      }
      if (file.size > 5 * 1024 * 1024) {
        rejected.push(`${file.name} (${humanSize(file.size)}, limit is 5 MB)`);
        continue;
      }
      if (!file.type.startsWith("image/")) {
        rejected.push(`${file.name} (not an image)`);
        continue;
      }
      detailSelectedFiles.push(file);
    }

    renderDetailPreviews();

    if (attachMsg) {
      attachMsg.innerHTML = rejected.length
        ? `<div class="alert alert-warning py-1 small mb-0">Not added: ${rejected.join(", ")}</div>`
        : "";
    }
  }

  if (dropzone) {
    dropzone.addEventListener("click", () => attachInput.click());
    dropzone.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        attachInput.click();
      }
    });

    attachInput.addEventListener("change", () => {
      addDetailFiles(attachInput.files);
      attachInput.value = "";
      updatePreviewActions();
    });

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
    dropzone.addEventListener("drop", (e) => {
      addDetailFiles(e.dataTransfer.files);
      updatePreviewActions();
    });
  }

  function updatePreviewActions() {
    const actions = document.getElementById("preview-actions");
    if (actions) {
      actions.style.display = detailSelectedFiles.length ? "flex" : "none";
    }
  }

  const uploadBtn = document.getElementById("upload-photos-btn");
  const clearBtn = document.getElementById("clear-photos-btn");

  if (uploadBtn) {
    uploadBtn.addEventListener("click", async () => {
      console.log("Upload photos clicked, files:", detailSelectedFiles.length);
      if (!detailSelectedFiles.length) return;
      uploadBtn.disabled = true;
      if (attachMsg) attachMsg.innerHTML = '<div class="alert alert-info py-1 small mb-0">Uploading&hellip;</div>';
      try {
        const result = await uploadDetailPhotos(id);
        if (result.failed === 0) {
          if (attachMsg) attachMsg.innerHTML = `<div class="alert alert-success py-1 small mb-0">${result.uploaded} photo${result.uploaded === 1 ? "" : "s"} uploaded.</div>`;
        } else {
          if (attachMsg) attachMsg.innerHTML = `<div class="alert alert-warning py-1 small mb-0">${result.uploaded} uploaded, ${result.failed} failed: ${result.errors.join("; ")}</div>`;
        }
        detailSelectedFiles = [];
        renderDetailPreviews();
        updatePreviewActions();
        await loadAttachments();
      } catch (err) {
        if (attachMsg) attachMsg.innerHTML = `<div class="alert alert-danger py-1 small mb-0">Upload error: ${err.message}</div>`;
      } finally {
        uploadBtn.disabled = false;
      }
    });
  } else {
    console.warn("upload-photos-btn not found in DOM");
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      console.log("Clear photos clicked");
      detailSelectedFiles = [];
      renderDetailPreviews();
      updatePreviewActions();
      if (attachMsg) attachMsg.innerHTML = "";
    });
  } else {
    console.warn("clear-photos-btn not found in DOM");
  }

  async function uploadDetailPhotos(complaintId) {
    if (!detailSelectedFiles.length) return { uploaded: 0, failed: 0, errors: [] };

    let uploaded = 0;
    const errors = [];

    for (const file of detailSelectedFiles) {
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

    return { uploaded, failed: detailSelectedFiles.length - uploaded, errors };
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
            <img class="attachment-thumb" src="${esc(a.url)}"
                 alt="${esc(a.file_name)}" loading="lazy"
                 data-full="${esc(a.url)}" data-name="${esc(a.file_name)}" style="cursor: zoom-in;">
            <div class="small text-secondary mt-1 text-truncate">${esc(a.file_name)}</div>
            <div class="small text-secondary">${esc(humanSize(a.file_size))}</div>
          </div>`
        )
        .join("");

      // Add click-to-enlarge handlers
      grid.querySelectorAll(".attachment-thumb").forEach((img) => {
        img.addEventListener("click", () => openImageModal(img.dataset.full, img.dataset.name));
      });
    } catch (err) {
      grid.innerHTML = `<div class="col-12"><div class="alert alert-secondary small">${esc(err.message)}</div></div>`;
    }
  }

  function openImageModal(src, name) {
    // Remove existing modal if any
    const existing = document.getElementById("image-modal");
    if (existing) existing.remove();

    const modal = document.createElement("div");
    modal.id = "image-modal";
    modal.className = "modal fade";
    modal.tabIndex = -1;
    modal.innerHTML = `
      <div class="modal-dialog modal-lg modal-dialog-centered">
        <div class="modal-content glass-overlay border-0">
          <div class="modal-header border-0">
            <h5 class="modal-title" style="color: var(--text-primary);">${esc(name)}</h5>
            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body p-0 text-center">
            <img src="${esc(src)}" alt="${esc(name)}" style="max-width: 100%; max-height: 70vh; object-fit: contain;">
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();
    modal.addEventListener("hidden.bs.modal", () => modal.remove());
  }

  loadAttachments();

  // Render timeline events
  function renderTimeline(events) {
    const box = document.getElementById("timeline");
    const counter = document.getElementById("event-count");
    if (counter) counter.textContent = `${events.length} event${events.length === 1 ? "" : "s"}`;

    if (!events.length) {
      box.innerHTML = '<p class="text-secondary mb-0">No activity recorded yet.</p>';
      return;
    }
    box.innerHTML = events
      .map(
        (ev) => {
          let payloadHtml = "";
          const p = ev.payload || {};
          if (ev.event_type === "COMMENT_ADDED" && p.body) {
            payloadHtml = `— ${esc(p.body)}`;
          } else if (ev.event_type === "ATTACHMENT_ADDED" && p.file_name) {
            payloadHtml = `— ${esc(p.file_name)}`;
          } else if (ev.event_type === "STATUS_CHANGED") {
            payloadHtml = `— ${esc(p.from_status_code || "")} → ${esc(p.to_status_code || "")}${p.remark ? ` (${esc(p.remark)})` : ""}`;
          } else if (ev.event_type === "PRIORITY_CHANGED") {
            payloadHtml = `— Priority changed${p.remark ? ` (${esc(p.remark)})` : ""}`;
          } else if (ev.event_type === "CATEGORY_CHANGED") {
            payloadHtml = `— Category changed${p.remark ? ` (${esc(p.remark)})` : ""}`;
          } else if (ev.event_type === "DEPARTMENT_CHANGED") {
            payloadHtml = `— Department changed${p.remark ? ` (${esc(p.remark)})` : ""}`;
          } else if (ev.event_type === "ASSIGNED") {
            payloadHtml = `— Assigned to staff${p.remark ? ` (${esc(p.remark)})` : ""}`;
          } else if (ev.event_type === "RESOLVED" || ev.event_type === "REOPENED" || ev.event_type === "ESCALATED") {
            payloadHtml = p.remark ? `— ${esc(p.remark)}` : "";
          }
          return `<div class="timeline-item pb-2 mb-2">
            <div class="small text-muted">
              ${esc(new Date(ev.occurred_at).toLocaleString())} &middot;
              ${esc(ev.actor?.username || "")} (${esc(ev.actor?.role || "")})
            </div>
            <div><strong>${esc(ev.event_type)}</strong> ${payloadHtml}</div>
          </div>`;
        }
      )
      .join("");
  }

  (async () => {
    try {
      const t = await apiFetch(`/complaints/${id}/timeline`);
      renderTimeline(t.events || []);
    } catch (err) {
      document.getElementById("timeline").innerHTML = `<p class="text-danger mb-0">${esc(err.message)}</p>`;
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
        const refreshed = await apiFetch(`/complaints/${id}/timeline`);
        renderTimeline(refreshed.events || []);
      } catch (err) {
        alert(err.message);
      }
    });
  }
}