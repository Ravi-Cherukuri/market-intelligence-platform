"use client";

import { ChangeEvent, useEffect, useRef, useState } from "react";

type Setup = {
  company_id: string;
  company_name: string;
  whatsapp_configured: boolean;
};

type ImportIssue = {
  row: number;
  field: string;
  message: string;
};

type ImportPreview = {
  valid: boolean;
  row_count: number;
  rows: Array<Record<string, unknown>>;
  errors: ImportIssue[];
  committed?: number;
};

type RequestState = "idle" | "previewing" | "ready" | "committing" | "complete" | "failed";

const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

async function readResponse(response: Response): Promise<ImportPreview> {
  const body = (await response.json().catch(() => null)) as ImportPreview | { detail?: string } | null;
  if (!response.ok) {
    const detail = body && "detail" in body ? body.detail : undefined;
    throw new Error(detail || `Upload failed with status ${response.status}.`);
  }
  return body as ImportPreview;
}

export function MasterUploads() {
  const inputRef = useRef<HTMLInputElement>(null);
  const selectedFileRef = useRef<File | null>(null);
  const previewControllerRef = useRef<AbortController | null>(null);
  const [setup, setSetup] = useState<Setup | null>(null);
  const [setupError, setSetupError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [previewedFile, setPreviewedFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [requestState, setRequestState] = useState<RequestState>("idle");
  const [requestError, setRequestError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${apiBase}/admin/setup`, {
      credentials: "same-origin",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("The pilot company has not been initialized.");
        return (await response.json()) as Setup;
      })
      .then(setSetup)
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setSetupError(errorMessage(error));
      });
    return () => controller.abort();
  }, []);

  async function submit(mode: "preview" | "commit") {
    if (!setup || !file) return;
    if (mode === "commit" && previewedFile !== file) return;
    setRequestError("");
    setRequestState(mode === "preview" ? "previewing" : "committing");
    const form = new FormData();
    form.append("file", file);
    try {
      const response = await fetch(
        `${apiBase}/admin/companies/${setup.company_id}/masters/employees/${mode}`,
        { method: "POST", body: form, credentials: "same-origin" },
      );
      const result = await readResponse(response);
      setPreview(result);
      setRequestState(mode === "commit" && result.valid ? "complete" : "ready");
    } catch (error: unknown) {
      setRequestError(errorMessage(error));
      setRequestState("failed");
    }
  }

  async function previewFile(selected: File) {
    if (!setup) return;
    previewControllerRef.current?.abort();
    const controller = new AbortController();
    previewControllerRef.current = controller;
    const form = new FormData();
    form.append("file", selected);
    setRequestState("previewing");
    try {
      const response = await fetch(
        `${apiBase}/admin/companies/${setup.company_id}/masters/employees/preview`,
        { method: "POST", body: form, credentials: "same-origin", signal: controller.signal },
      );
      const result = await readResponse(response);
      if (selectedFileRef.current !== selected) return;
      setPreview(result);
      setPreviewedFile(selected);
      setRequestState("ready");
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      if (selectedFileRef.current !== selected) return;
      setRequestError(errorMessage(error));
      setRequestState("failed");
    }
  }

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0];
    if (!selected) return;
    selectedFileRef.current = selected;
    setFile(selected);
    setPreview(null);
    setPreviewedFile(null);
    setRequestError("");
    void previewFile(selected);
  }

  function closeReview() {
    previewControllerRef.current?.abort();
    selectedFileRef.current = null;
    setFile(null);
    setPreview(null);
    setPreviewedFile(null);
    setRequestError("");
    setRequestState("idle");
    if (inputRef.current) inputRef.current.value = "";
  }

  const reviewOpen = file !== null;
  const busy = requestState === "previewing" || requestState === "committing";

  return (
    <>
      <section className="setup-strip" aria-label="Master data uploads">
        <div>
          <p className="eyebrow">Admin setup</p>
          <h2>Keep field context current</h2>
          <p>
            {setup
              ? `${setup.company_name} · preview and validate files before committing.`
              : setupError || "Loading company setup…"}
          </p>
        </div>
        <div className="upload-actions">
          <label className={setup ? "upload-button" : "upload-button disabled"}>
            Upload employee master
            <input
              ref={inputRef}
              accept=".csv,.xlsx"
              aria-label="Upload employee master"
              disabled={!setup}
              onChange={chooseFile}
              type="file"
            />
          </label>
          {["Organization hierarchy", "Product master", "Competition prices"].map((label) => (
            <button className="upload-button pending" disabled key={label} type="button" title="Coming next">
              {label}
              <small>Coming next</small>
            </button>
          ))}
        </div>
      </section>

      {reviewOpen && (
        <div className="review-backdrop" role="presentation">
          <section aria-labelledby="import-review-title" aria-modal="true" className="import-review" role="dialog">
            <div className="review-heading">
              <div>
                <p className="eyebrow">Employee master</p>
                <h2 id="import-review-title">Validate before importing</h2>
                <p>{file.name} · {(file.size / 1024).toFixed(1)} KB</p>
              </div>
              <button aria-label="Close import review" className="close-button" disabled={busy} onClick={closeReview} type="button">×</button>
            </div>

            {busy && <div className="import-state"><span className="spinner" />{requestState === "committing" ? "Importing records…" : "Validating every row…"}</div>}

            {requestError && (
              <div className="import-alert error" role="alert">
                <strong>Upload could not be processed</strong>
                <p>{requestError}</p>
                <button className="quiet-button" onClick={() => submit("preview")} type="button">Try again</button>
              </div>
            )}

            {preview && !busy && requestState !== "complete" && (
              <>
                <div className={preview.valid ? "import-alert success" : "import-alert error"}>
                  <strong>{preview.valid ? `${preview.row_count} rows ready to import` : `${preview.errors.length} validation issues found`}</strong>
                  <p>{preview.valid ? "No database records have been changed yet." : "Correct the source file and upload it again. Nothing was imported."}</p>
                </div>

                {preview.errors.length > 0 && (
                  <div className="issue-table-wrap">
                    <table className="issue-table">
                      <thead><tr><th>Row</th><th>Field</th><th>Issue</th></tr></thead>
                      <tbody>
                        {preview.errors.map((issue, index) => (
                          <tr key={`${issue.row}-${issue.field}-${index}`}>
                            <td>{issue.row}</td><td>{issue.field}</td><td>{issue.message}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {preview.valid && preview.rows.length > 0 && (
                  <div className="sample-box">
                    <span>Sample</span>
                    <strong>{String(preview.rows[0].employee_code)}</strong>
                    <small>{String(preview.rows[0].employment_type)} · {String(preview.rows[0].state)} · {String(preview.rows[0].whatsapp_number)}</small>
                  </div>
                )}
              </>
            )}

            {requestState === "complete" && preview && (
              <div className="import-alert success complete" role="status">
                <strong>Employee master imported</strong>
                <p>{preview.committed ?? preview.row_count} employee records were created or updated atomically.</p>
              </div>
            )}

            {!busy && (
              <div className="review-actions">
                <a className="template-link" download href="/templates/employee-master.csv">Download CSV template</a>
                <div>
                  <button className="quiet-button" onClick={closeReview} type="button">{requestState === "complete" ? "Done" : "Cancel"}</button>
                  {preview?.valid && previewedFile === file && requestState !== "complete" && (
                    <button className="primary-button" onClick={() => submit("commit")} type="button">Import {preview.row_count} rows</button>
                  )}
                </div>
              </div>
            )}
          </section>
        </div>
      )}
    </>
  );
}
