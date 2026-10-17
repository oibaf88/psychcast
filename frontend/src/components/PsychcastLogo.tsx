interface Props {
  className?: string;
  alt?: string;
}

/** Static Psychcast brand mark. The asset is repository-owned and same-origin. */
export default function PsychcastLogo({ className, alt = "" }: Props) {
  return (
    <img
      className={className ? `psychcast-logo ${className}` : "psychcast-logo"}
      src="/psychcast-icon.svg"
      alt={alt}
      draggable={false}
    />
  );
}
