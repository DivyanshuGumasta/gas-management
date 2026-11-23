// Data & Backup: record counts, configurable rotation, manual backup and safe merge restore.
(function () {
  const $ = (id) => document.getElementById(id);
  const error = $("data-error");
  const countsRoot = $("data-counts");
  const status = $("data-action-status");
  const settingsForm = $("data-settings-form");
  const FIELDS = ["customers", "sales", "payments", "purchases", "suppliers", "cylinder_types"];
  const number = new Intl.NumberFormat("en-IN");
  let busy = false;

  function showStatus(message, isError) {
    status.hidden = !message;
    status.textContent = message || "";
    status.classList.toggle("is-error", !!isError);
    status.classList.toggle("is-success", !!message && !isError);
  }

  function renderCounts(payload) {
    const counts = payload && payload.counts ? payload.counts : {};
    FIELDS.forEach((key) => {
      const node = $("count-" + key.replace(/_/g, "-"));
      if (node) node.textContent = number.format(Number(counts[key] || 0));
    });
    $("data-updated").textContent = "Updated " + (payload.generated_at || "just now") +
      " · Counts include all saved records, including cancelled or inactive history.";
  }

  async function loadCounts() {
    error.hidden = true;
    countsRoot.setAttribute("aria-busy", "true");
    try {
      renderCounts(await Api.get("/api/data/summary"));
    } catch (err) {
      error.hidden = false;
      error.querySelector("span").textContent = "Could not load database information. " + (err.message || "");
      $("data-updated").textContent = "Record counts are currently unavailable.";
    } finally {
      countsRoot.setAttribute("aria-busy", "false");
    }
  }

  function updateFrequencyLimit() {
    const unit = $("backup-frequency-unit").value;
    const limits = { hours: 8760, days: 365, weeks: 52 };
    const input = $("backup-frequency-value");
    input.max = String(limits[unit] || 365);
    if (Number(input.value) > Number(input.max)) input.value = input.max;
  }

  function renderSettings(settings) {
    $("backup-frequency-value").value = settings.frequency_value || 1;
    $("backup-frequency-unit").value = settings.frequency_unit || "days";
    updateFrequencyLimit();
    $("backup-retention").value = settings.retention_count || 30;
    $("backup-directory").value = settings.directory || "";
    $("backup-settings-note").textContent = "Automatic backups are stored in " + (settings.directory || "the default backup folder") + ".";
  }

  $("backup-frequency-unit").addEventListener("change", updateFrequencyLimit);

  async function loadSettings() {
    try {
      renderSettings(await Api.get("/api/data/backup-settings"));
    } catch (err) {
      $("backup-settings-note").textContent = "Could not load backup settings. " + (err.message || "");
    }
  }

  settingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy) return;
    busy = true;
    const button = $("backup-settings-save");
    button.disabled = true;
    showStatus("Saving backup settings…", false);
    try {
      const saved = await Api.put("/api/data/backup-settings", {
        frequency_value: $("backup-frequency-value").value,
        frequency_unit: $("backup-frequency-unit").value,
        retention_count: $("backup-retention").value,
        directory: $("backup-directory").value.trim(),
      });
      renderSettings(saved);
      showStatus("Backup settings saved successfully.", false);
    } catch (err) {
      showStatus(err.message || "Could not save backup settings.", true);
    } finally {
      busy = false;
      button.disabled = false;
    }
  });

  $("data-manual-backup").addEventListener("click", async () => {
    if (busy) return;
    busy = true;
    const button = $("data-manual-backup");
    button.disabled = true;
    showStatus("Creating manual backup…", false);
    try {
      const result = await Api.post("/api/data/backup", {});
      showStatus("Manual backup created: " + result.filename + " · " + result.directory, false);
    } catch (err) {
      showStatus(err.message || "Could not create a manual backup.", true);
    } finally {
      busy = false;
      button.disabled = false;
    }
  });

  const fileInput = $("data-restore-file");
  const restoreButton = $("data-restore-button");
  fileInput.addEventListener("change", () => {
    const file = fileInput.files && fileInput.files[0];
    $("data-restore-filename").textContent = file ? file.name : "Choose a backup file (.db)";
    restoreButton.disabled = !file || busy;
    showStatus("", false);
  });

  restoreButton.addEventListener("click", async () => {
    const file = fileInput.files && fileInput.files[0];
    if (!file || busy) return;
    const accepted = window.confirm(
      "Restore this Agni backup?\n\nThe app will first create a safety backup, then merge the selected later snapshot. Existing records will not be deleted. If the two copies have conflicting independent changes, the restore will be refused."
    );
    if (!accepted) return;

    busy = true;
    restoreButton.disabled = true;
    showStatus("Checking backup and preparing a safety copy…", false);
    try {
      const form = new FormData();
      form.append("backup_file", file, file.name);
      const result = await Api.postForm("/api/data/restore", form);
      if (result.status === "merged") {
        showStatus(result.message + (result.safety_backup ? " Safety copy: " + result.safety_backup : ""), false);
        await loadCounts();
      } else {
        showStatus(result.message || "No changes were needed.", false);
      }
      fileInput.value = "";
      $("data-restore-filename").textContent = "Choose a backup file (.db)";
    } catch (err) {
      showStatus(err.message || "Could not restore this backup.", true);
    } finally {
      busy = false;
      restoreButton.disabled = !(fileInput.files && fileInput.files[0]);
      $("data-manual-backup").disabled = false;
      $("backup-settings-save").disabled = false;
    }
  });

  $("data-retry").addEventListener("click", loadCounts);
  loadCounts();
  loadSettings();
  if (window.Icons) Icons.render(document);
})();
