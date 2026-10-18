import { Moon, Sun } from "./Icons.jsx";

export default function ThemeToggle({ theme, onToggle }) {
  const dark = theme === "dark";
  return (
    <button type="button" className="icon-btn" onClick={onToggle} aria-pressed={dark}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"} title={dark ? "Light theme" : "Dark theme"}>
      {dark ? <Sun /> : <Moon />}
    </button>
  );
}
