function ServerCard({ server, selected, onSelect, disabled }) {
  const offline = server.port && !server.live;
  return (
    <button
      type="button"
      className={`server-card${selected ? " selected" : ""}${offline ? " offline" : ""}`}
      onClick={() => onSelect(server)}
      disabled={disabled}
      aria-pressed={selected}
    >
      <div className="server-card-top">
        <span className="server-name">{server.name}</span>
        {server.port ? (
          <span className={`live-dot ${server.live ? "on" : "off"}`}>
            {server.live ? `live :${server.port}` : `offline :${server.port}`}
          </span>
        ) : (
          <span className="live-dot fixture">fixture</span>
        )}
      </div>
      {server.attack_category && (
        <span className="category">{server.attack_category.replaceAll("_", " ")}</span>
      )}
    </button>
  );
}

export default function ServerPicker({ servers, selectedId, onSelect, disabled }) {
  if (!servers) return <p className="muted">Loading servers…</p>;
  return (
    <div className="picker">
      {[
        ["clean", "Clean", "Should pass every stage"],
        ["poisoned", "Poisoned", "Should be caught somewhere"],
      ].map(([group, title, hint]) => (
        <section key={group} className="picker-col">
          <h2>
            <span className={`group-dot ${group}`} /> {title}
            <small>{hint}</small>
          </h2>
          <div className="server-list">
            {servers[group].map((s) => (
              <ServerCard
                key={s.id}
                server={s}
                selected={s.id === selectedId}
                onSelect={onSelect}
                disabled={disabled}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
