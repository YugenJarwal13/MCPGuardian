function ServerCard({ server, selected, onSelect, disabled }) {
  const offline = server.port && !server.live;
  return (
    <button type="button" className={`server-card${offline ? " offline" : ""}`} onClick={() => onSelect(server)}
      disabled={disabled} aria-pressed={selected}>
      <span className="server-name">{server.name}</span>
      <span className="server-meta">
        {server.port ? (
          <span className={`live-dot ${server.live ? "on" : "off"}`}>{server.live ? `live · :${server.port}` : `offline · :${server.port}`}</span>
        ) : (
          <span>in-process fixture</span>
        )}
        {server.attack_category && <span>· {server.attack_category.replaceAll("_", " ")}</span>}
      </span>
    </button>
  );
}

export default function ServerPicker({ servers, selectedId, onSelect, disabled }) {
  if (!servers) return <p className="muted">Loading servers…</p>;
  return (
    <div>
      {[
        ["clean", "Clean servers", "should pass every stage"],
        ["poisoned", "Poisoned servers", "should be caught"],
      ].map(([group, title, hint]) => (
        <section key={group} className="picker-group">
          <h2><span className={`group-dot ${group}`} />{title}<small>{hint}</small></h2>
          <div className="server-list">
            {servers[group].map((s) => (
              <ServerCard key={s.id} server={s} selected={s.id === selectedId} onSelect={onSelect} disabled={disabled} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
