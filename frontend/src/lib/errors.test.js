import { getErrorMessage, getErrorCode } from "./errors";

describe("getErrorMessage", () => {
  test("string detail is returned as-is", () => {
    const e = { response: { data: { detail: "Invalid credentials" } } };
    expect(getErrorMessage(e)).toBe("Invalid credentials");
  });

  test("object detail with {code, message} returns message", () => {
    const e = { response: { data: { detail: { code: "auditor_read_only", message: "Auditor accounts cannot upload files." } } } };
    expect(getErrorMessage(e)).toBe("Auditor accounts cannot upload files.");
    // Never render the whole object.
    expect(typeof getErrorMessage(e)).toBe("string");
  });

  test("Pydantic v2 validation array is joined", () => {
    const e = { response: { data: { detail: [{ loc: ["body", "email"], msg: "Field required", type: "missing" }, { loc: ["body", "password"], msg: "min length", type: "value_error" }] } } };
    expect(getErrorMessage(e)).toBe("Field required; min length");
  });

  test("plain JS Error", () => {
    const e = new Error("Network Error");
    expect(getErrorMessage(e)).toBe("Network Error");
  });

  test("unknown object falls back to safe string", () => {
    const e = { response: { data: { detail: { something: 1 } } } };
    expect(getErrorMessage(e)).toBe("Something went wrong.");
  });

  test("null / undefined falls back", () => {
    expect(getErrorMessage(null)).toBe("Something went wrong.");
    expect(getErrorMessage(undefined)).toBe("Something went wrong.");
  });

  test("root data.message is used when no detail", () => {
    const e = { response: { data: { message: "Server ate the request" } } };
    expect(getErrorMessage(e)).toBe("Server ate the request");
  });

  test("custom fallback honoured", () => {
    expect(getErrorMessage(null, "Sign-in failed. Try again.")).toBe("Sign-in failed. Try again.");
  });
});

describe("getErrorCode", () => {
  test("extracts code from detail object", () => {
    const e = { response: { data: { detail: { code: "amendment_reason_required", message: "..." } } } };
    expect(getErrorCode(e)).toBe("amendment_reason_required");
  });

  test("returns null when no code", () => {
    expect(getErrorCode({ response: { data: { detail: "plain" } } })).toBeNull();
    expect(getErrorCode(null)).toBeNull();
  });
});
