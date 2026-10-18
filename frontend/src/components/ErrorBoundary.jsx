import { Component } from "react";

/** A render fault in one view must never blank the whole app. */
export default class ErrorBoundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="page">
        <div className="notice error" role="alert">
          <strong>Something went wrong while drawing this view.</strong>
          <div style={{ marginTop: 6 }}>{String(this.state.error?.message || this.state.error)}</div>
          <div className="row" style={{ marginTop: 10 }}>
            <button type="button" className="btn" onClick={() => this.setState({ error: null })}>Try again</button>
            <button type="button" className="btn quiet" onClick={() => window.location.reload()}>Reload</button>
          </div>
        </div>
      </main>
    );
  }
}
