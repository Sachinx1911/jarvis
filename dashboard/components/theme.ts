// Colour theme: dark (default), light, or follow the operating system.
// Saved in localStorage; applied as <html data-theme="..."> (see globals.css).

export type ThemeMode = "dark" | "light" | "system";

export const THEME_KEY = "jarvis_theme";
const MODES: ThemeMode[] = ["dark", "light", "system"];

// Runs in <head> before the page paints, so a saved light theme never flashes dark.
export const THEME_SCRIPT = `(function(){try{var t=localStorage.getItem("${THEME_KEY}");if(t==="light"||t==="system"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}})();`;

export function getTheme(): ThemeMode {
  try {
    const t = localStorage.getItem(THEME_KEY);
    if (t === "light" || t === "system" || t === "dark") return t;
  } catch {
    /* storage blocked */
  }
  return "dark";
}

export function setTheme(mode: ThemeMode): void {
  document.documentElement.setAttribute("data-theme", mode);
  try {
    localStorage.setItem(THEME_KEY, mode);
  } catch {
    /* storage blocked: the theme still applies to this page */
  }
}

export function nextTheme(mode: ThemeMode): ThemeMode {
  return MODES[(MODES.indexOf(mode) + 1) % MODES.length];
}

export const THEME_LABEL: Record<ThemeMode, string> = { dark: "Dark", light: "Light", system: "System" };
