// Small inline SVG icon set (24x24 grid, drawn with the current text colour).
// No icon package: each icon is a few path strings.

const PATHS = {
  home: ["M3 10.5 12 3l9 7.5", "M5 9.5V21h5v-6h4v6h5V9.5"],
  chat: ["M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.6A8 8 0 1 1 21 12z", "M8.5 12h.01M12 12h.01M15.5 12h.01"],
  tasks: ["M7 3.5h10a3.5 3.5 0 0 1 3.5 3.5v10a3.5 3.5 0 0 1-3.5 3.5H7A3.5 3.5 0 0 1 3.5 17V7A3.5 3.5 0 0 1 7 3.5z", "m8 12 3 3 5-6"],
  folder: ["M3.5 7.5a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"],
  calendar: ["M6 5h12a2.5 2.5 0 0 1 2.5 2.5v10.5a2.5 2.5 0 0 1-2.5 2.5H6A2.5 2.5 0 0 1 3.5 18V7.5A2.5 2.5 0 0 1 6 5z", "M3.5 10h17M8 3v4M16 3v4"],
  agents: ["M7 8h10a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3v-6a3 3 0 0 1 3-3z", "M12 8V5M9.5 13.5v1.5M14.5 13.5v1.5M2 13v3M22 13v3", "M12 3.2a.8.8 0 1 0 0 1.6.8.8 0 0 0 0-1.6z"],
  teach: ["M2.5 9 12 4.5 21.5 9 12 13.5z", "M6.5 11v4.5c0 1.5 2.5 3 5.5 3s5.5-1.5 5.5-3V11M21.5 9v5"],
  memory: ["M4.5 6c0-1.7 3.4-3 7.5-3s7.5 1.3 7.5 3-3.4 3-7.5 3-7.5-1.3-7.5-3z", "M4.5 6v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6M4.5 12v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6"],
  rupee: ["M7 4.5h10M7 9h10M7 4.5h3.5a4.5 4.5 0 0 1 0 9H7l7.5 6.5"],
  plug: ["M9 3v5M15 3v5M6.5 8h11v3.5a5.5 5.5 0 0 1-11 0zM12 17v4"],
  shield: ["M12 3 4.5 6v5.5c0 4.6 3.2 8.2 7.5 9.5 4.3-1.3 7.5-4.9 7.5-9.5V6z", "m8.8 12 2.2 2.2 4.3-4.4"],
  wrench: ["M14.7 6.3a4.5 4.5 0 0 0-5.9 5.9l-5.3 5.3a2.1 2.1 0 0 0 3 3l5.3-5.3a4.5 4.5 0 0 0 5.9-5.9l-2.8 2.8-2.5-.5-.5-2.5z"],
  sliders: ["M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12", "M16 4v4M10 10v4M18 16v4"],
  menu: ["M4 7h16M4 12h16M4 17h16"],
  x: ["M6 6l12 12M18 6 6 18"],
  sun: ["M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z", "M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"],
  moon: ["M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"],
  monitor: ["M5 4h14a2 2 0 0 1 2 2v8.5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z", "M8.5 20.5h7M12 16.5v4"],
  stop: ["M8.2 3h7.6L21 8.2v7.6L15.8 21H8.2L3 15.8V8.2z", "M9.5 9.5h5v5h-5z"],
  mic: ["M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z", "M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"],
  send: ["M21 3 10 14", "M21 3l-6.5 18-4.5-7-7-4.5z"],
  bell: ["M6 16v-5a6 6 0 1 1 12 0v5l1.5 2h-15z", "M10 20.5a2 2 0 0 0 4 0"],
  chevronLeft: ["m15 5-7 7 7 7"],
  chevronRight: ["m9 5 7 7-7 7"],
  chevronDown: ["m5 9 7 7 7-7"],
  refresh: ["M20 11a8 8 0 0 0-14.3-4.9L4 8M4 4v4h4", "M4 13a8 8 0 0 0 14.3 4.9L20 16M20 20v-4h-4"],
  plus: ["M12 5v14M5 12h14"],
  search: ["M11 4.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13z", "m20 20-4.2-4.2"],
  sparkles: ["M12 3l1.8 4.7 4.7 1.8-4.7 1.8L12 16l-1.8-4.7-4.7-1.8 4.7-1.8z", "M19 15l.8 2.2 2.2.8-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"],
  report: ["M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z", "M14 3v5h5M9 13h6M9 17h6"],
  zap: ["M13 2.5 4.5 13.5H12l-1 8 8.5-11H12z"],
  listCheck: ["M10 6h10M10 12h10M10 18h10", "m3.5 6 1 1 2-2M3.5 12l1 1 2-2M3.5 18l1 1 2-2"],
  alert: ["M10.3 4.2 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0z", "M12 9.5v4.5M12 17.2v.01"],
  check: ["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "m8 12.5 2.8 2.8L16.5 9.5"],
  clock: ["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "M12 7v5l3 2"],
  pen: ["M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17v3z", "m14.5 7.5 3 3"],
  code: ["m8 7-5 5 5 5M16 7l5 5-5 5M14 4l-4 16"],
  pointer: ["M5 3l14 7-6 2-2 6z", "m13 12 6 6"],
  compass: ["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "m15.5 8.5-2 5-5 2 2-5z"],
  wave: ["M4 10v4M8 6v12M12 3v18M16 7v10M20 10v4"],
  pause: ["M8 5v14M16 5v14"],
  play: ["M7 4.5v15l12-7.5z"],
  panel: ["M5.5 4h13A2.5 2.5 0 0 1 21 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5v-11A2.5 2.5 0 0 1 5.5 4z", "M9 4v16"],
  arrowRight: ["M5 12h14M13 6l6 6-6 6"],
  activity: ["M3 12h4l3-8 4 16 3-8h4"],
  eye: ["M2.5 12S6 5 12 5s9.5 7 9.5 7-3.5 7-9.5 7-9.5-7-9.5-7z", "M12 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z"],
  cloud: ["M7 18.5a4.5 4.5 0 0 1-.6-8.96A6 6 0 0 1 18 10.5a4 4 0 0 1-.5 8z"],
  rain: ["M7 15.5a4.5 4.5 0 0 1-.6-8.96A6 6 0 0 1 18 7.5a4 4 0 0 1-.5 8z", "M8 19l-1 2M12 19l-1 2M16 19l-1 2"],
  info: ["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "M12 11v5M12 7.8v.01"],
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({
  name,
  size = 18,
  className,
  title,
}: {
  name: IconName;
  size?: number;
  className?: string;
  title?: string;
}) {
  return (
    <svg
      className={className ? `icon ${className}` : "icon"}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
    >
      {title && <title>{title}</title>}
      {PATHS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}
