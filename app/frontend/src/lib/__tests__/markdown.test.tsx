// Server rendering verifies the Markdown reader without a browser.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Markdown } from "../../components/Markdown";

describe("markdown reader", () => {
  it("renders headings, emphasis, code, and GitHub tables", () => {
    const html = renderToStaticMarkup(<Markdown text={"### Results\n**145 × 80 × 95 mm**\n\n| Deliverable | Artifact ID |\n|---|---|\n| STEP | `art_1` |"} />);
    expect(html).toContain("<h3>Results</h3>");
    expect(html).toContain("<strong>145 × 80 × 95 mm</strong>");
    expect(html).toContain("<table>");
    expect(html).toContain("<code>art_1</code>");
  });

  it("escapes raw HTML in the note", () => {
    const html = renderToStaticMarkup(<Markdown text={'<img src=x onerror="alert(1)">'} />);
    expect(html).not.toContain("<img");
  });
});
