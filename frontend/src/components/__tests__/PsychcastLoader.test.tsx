import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import PsychcastLoader from "../PsychcastLoader";

describe("PsychcastLoader", () => {
  it("uses the repository-owned animated logo asset", () => {
    const { container } = render(<PsychcastLoader label="Preparando respuesta…" />);
    const video = container.querySelector("video");
    const source = container.querySelector("source");

    expect(video).toBeInTheDocument();
    expect(video).toHaveAttribute("autoplay");
    expect(video).toHaveAttribute("loop");
    expect((video as HTMLVideoElement).muted).toBe(true);
    expect(video).toHaveAttribute("playsinline");
    expect(source).toHaveAttribute("src", "/psychcast-mark-animation.mp4");
    expect(video).toHaveAttribute("poster", "/psychcast-icon.svg");
    expect(screen.getByRole("status")).toHaveTextContent("Preparando respuesta…");
  });
});
