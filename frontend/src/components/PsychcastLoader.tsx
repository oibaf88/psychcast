interface Props {
  size?: "sm" | "md" | "lg";
  label?: string;
  className?: string;
}

/**
 * Brand-native wait indicator used while screens or model-backed actions are
 * actually pending. The MP4 is muted, inline, looped and same-origin so it
 * does not add a third-party dependency or unexpected audio.
 *
 * Reduced-motion users receive the static mark instead of the animation.
 */
export default function PsychcastLoader({ size = "md", label, className }: Props) {
  const classes = [
    "psychcast-loader",
    `psychcast-loader--${size}`,
    className,
  ].filter(Boolean).join(" ");

  return (
    <div
      className={classes}
      role={label ? "status" : undefined}
      aria-live={label ? "polite" : undefined}
    >
      <video
        className="psychcast-loader__video"
        autoPlay
        loop
        muted
        playsInline
        preload="auto"
        poster="/psychcast-icon.svg"
        aria-hidden="true"
      >
        <source src="/psychcast-mark-animation.mp4" type="video/mp4" />
      </video>
      <img
        className="psychcast-loader__fallback"
        src="/psychcast-icon.svg"
        alt=""
        aria-hidden="true"
        draggable={false}
      />
      {label && <span className="psychcast-loader__label">{label}</span>}
    </div>
  );
}
