const PATHS = {
  plus: "M12 5v14M5 12h14",
  close: "M6 6l12 12M18 6L6 18",
  back: "M15 5l-7 7 7 7",
  external: "M14 5h5v5M19 5l-8 8M11 7H6v11h11v-5",
  edit: "M4 20h4L19 9l-4-4L4 16v4zM14 6l4 4",
  trash: "M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13",
  sortUp: "M7 14l5-5 5 5",
  sortDown: "M7 10l5 5 5-5",
  alert: "M12 4l9 16H3L12 4zM12 10v5M12 17.5v.5",
  check: "M5 12.5l4.5 4.5L19 7.5",
  mail: "M4 6h16v12H4zM4 7l8 6 8-6",
  inbox: "M4 13l2.5-8h11L20 13v6H4zM4 13h5l1 2h4l1-2h5",
  refresh: "M19 8a8 8 0 1 0 1 6M19 4v4h-4",
  upload: "M12 16V5M7.5 9.5L12 5l4.5 4.5M5 19h14",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 16 }: { name: IconName; size?: number }) {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
