import { useTheme, isDark } from "../store/theme";
import { Icon } from "./Icon";

/** One button: switches between the light and the dark look (the first press leaves "follow the system"). */
export function ThemeToggle() {
  const { mode, set } = useTheme();
  const dark = isDark(mode);
  return (
    <button type="button" className="btn btn-soft" onClick={() => set(dark ? "light" : "dark")} aria-label={dark ? "Switch to the light theme" : "Switch to the dark theme"} title={dark ? "Light theme" : "Dark theme"}>
      <Icon name={dark ? "sun" : "moon"} size={16} />
      <span className="tb-label">{dark ? "Light" : "Dark"}</span>
    </button>
  );
}
