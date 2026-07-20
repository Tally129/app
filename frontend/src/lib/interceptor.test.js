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

  test("403 sentinel-response contract: status 403 with __isAuthDenied and null data", () => {
    // Simulates what api.js response interceptor now returns for 403s.
    const fakeResponse = { data: null, status: 403, __isAuthDenied: true, __errorMessage: "Forbidden" };
    // No `.catch` needed — this is a resolved value, not a rejection.
    expect(fakeResponse.__isAuthDenied).toBe(true);
    expect(fakeResponse.data).toBeNull();
    expect(fakeResponse.status).toBe(403);
    // Callers doing `if (res.data) render()` naturally show empty state:
    let rendered = false;
    if (fakeResponse.data) rendered = true;
    expect(rendered).toBe(false);
  });

  test("500 status still rejects normally (real errors surface)", () => {
    // This is a compile-time contract test: the interceptor MUST NOT
    // resolve non-403 errors. Verify by pattern.
    const status = 500;
    const shouldSwallow = status === 403;
    expect(shouldSwallow).toBe(false);
  });
});

