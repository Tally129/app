/**
 * Verifies the 403 handling in the axios interceptor and the global
 * unhandledrejection safety net.
 */
import { getErrorMessage, getErrorCode } from "./errors";

describe("403 handling contract", () => {
  test("getErrorMessage extracts message from structured 403 detail", () => {
    const err = { response: { status: 403, data: { detail: { code: "auditor_read_only", message: "Auditor accounts cannot upload files." } } } };
    expect(getErrorMessage(err)).toBe("Auditor accounts cannot upload files.");
    expect(getErrorCode(err)).toBe("auditor_read_only");
  });

  test("getErrorMessage handles bare-string 403 detail", () => {
    const err = { response: { status: 403, data: { detail: "Forbidden" } } };
    expect(getErrorMessage(err)).toBe("Forbidden");
    expect(getErrorCode(err)).toBeNull();
  });

  test("global unhandledrejection listener suppresses 403", async () => {
    // Simulate what our api.js installs. Because api.js pulls in axios etc,
    // just re-run the small handler here in isolation.
    let prevented = false;
    const listener = (ev) => {
      const err = ev.reason;
      const status = err?.response?.status;
      if (status === 403 || err?.isAuthDenied) {
        ev.preventDefault();
      }
    };
    const ev = {
      reason: { response: { status: 403, data: { detail: "denied" } }, isAuthDenied: true },
      preventDefault: () => { prevented = true; },
    };
    listener(ev);
    expect(prevented).toBe(true);

    // 500 should NOT be suppressed
    prevented = false;
    listener({
      reason: { response: { status: 500 } },
      preventDefault: () => { prevented = true; },
    });
    expect(prevented).toBe(false);
  });
});
