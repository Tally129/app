import React from "react";

/**
 * Top-level React error boundary.
 * Catches render-time exceptions so a single crashing component doesn't
 * blank the whole app.
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }
  componentDidCatch(error, info) {
    // Debug-level so it's not lost, but not surfaced as a red console error
    // by default. If a real observability backend is wired later, ship here.
    // eslint-disable-next-line no-console
    console.debug("[nms] error boundary caught:", error, info?.componentStack);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 40, fontFamily: "system-ui, sans-serif" }}>
          <h1 style={{ fontSize: 22, marginBottom: 12 }}>Something went wrong.</h1>
          <p style={{ color: "#6b7280", marginBottom: 20 }}>
            The page hit an unexpected error. Reload to try again, or sign out and
            back in.
          </p>
          <button
            style={{ padding: "8px 16px", border: "1px solid #d1d5db", borderRadius: 6, background: "#f9fafb", cursor: "pointer" }}
            onClick={() => window.location.reload()}
          >
            Reload page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
