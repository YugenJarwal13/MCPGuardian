/** The shared on/off switch for scrolling to each new section automatically. */
export default function AutoFollowToggle({ enabled, onChange }) {
  return (
    <label className="switch autofollow" title="When a step finishes, move the page to the next one">
      <input type="checkbox" role="switch" checked={enabled} onChange={(e) => onChange(e.target.checked)} />
      Auto-follow
    </label>
  );
}
