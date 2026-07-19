/**
 * Centralised error-to-string normaliser.
 *
 * The backend now returns HTTPException detail values that can be:
 *   - a plain string:                       "Something failed"
 *   - a structured error:                   { code: "auditor_read_only", message: "..." }
 *   - Pydantic validation output:           [ { loc, msg, type } ]
 *   - or simply missing (network failure)
 *
 * Rendering these directly in JSX crashes React with
 *   "Objects are not valid as a React child (found: object with keys {code, message})".
 * Use `getErrorMessage(err)` everywhere we render an error to a user, and
 * use `getErrorCode(err)` when we need to branch on the machine-readable code.
 */
export function getErrorMessage(error, fallback = "Something went wrong.") {
  if (!error) return fallback;

  // 1) Axios error with a response payload
  const detail = error && error.response && error.response.data && error.response.data.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (detail && typeof detail === "object") {
    if (typeof detail.message === "string" && detail.message.trim()) return detail.message;
    if (typeof detail.detail === "string" && detail.detail.trim()) return detail.detail;
    // Pydantic v2 validation array
    if (Array.isArray(detail) && detail.length && typeof detail[0]?.msg === "string") {
      return detail.map((d) => d.msg).join("; ");
    }
  }

  const data = error && error.response && error.response.data;
  if (typeof data === "string" && data.trim()) return data;
  if (data && typeof data === "object") {
    if (typeof data.message === "string" && data.message.trim()) return data.message;
    if (typeof data.error === "string" && data.error.trim()) return data.error;
  }

  // 2) Fetch-style / plain JS Error
  if (typeof error === "string" && error.trim()) return error;
  if (typeof error?.message === "string" && error.message.trim()) return error.message;

  return fallback;
}

/**
 * Machine-readable code for branching logic. Never render this to the user.
 */
export function getErrorCode(error) {
  const detail = error && error.response && error.response.data && error.response.data.detail;
  if (detail && typeof detail === "object" && typeof detail.code === "string") return detail.code;
  const data = error && error.response && error.response.data;
  if (data && typeof data === "object" && typeof data.code === "string") return data.code;
  return null;
}
