import { describe, expect, it } from "vitest";
import { parseInline, parseMarkdown, type Inline } from "./markdown";

const text = (value: string): Inline => ({ kind: "text", text: value });

describe("parseInline", () => {
  it("reads bold, italic and code", () => {
    expect(parseInline("a **b** c *d* e _f_ `g`")).toEqual([
      text("a "),
      { kind: "bold", children: [text("b")] },
      text(" c "),
      { kind: "italic", children: [text("d")] },
      text(" e "),
      { kind: "italic", children: [text("f")] },
      text(" "),
      { kind: "code", text: "g" },
    ]);
  });

  it("nests italic inside bold", () => {
    expect(parseInline("**a *b* c**")).toEqual([
      { kind: "bold", children: [text("a "), { kind: "italic", children: [text("b")] }, text(" c")] },
    ]);
  });

  it("leaves code literal: marks inside it are not read", () => {
    expect(parseInline("`**not bold**`")).toEqual([{ kind: "code", text: "**not bold**" }]);
  });

  it.each([
    ["snake_case_name"], // underscores inside a word
    ["2 * 3 * 4"], // spaces next to the stars
    ["a ** b"], // an unclosed bold
    ["a `b"], // an unclosed code mark
    ["**"], // nothing between the marks
    ["a * b"],
  ])("keeps %j as written", (source) => {
    expect(parseInline(source)).toEqual([text(source)]);
  });

  it("never turns anything into HTML, a link or an image", () => {
    const hostile = '<script>alert(1)</script> [click](javascript:alert(1)) ![x](http://evil.example/p.png) <img src=x onerror=alert(1)>';
    expect(parseInline(hostile)).toEqual([text(hostile)]);
  });

  it("copes with a long run of marks quickly", () => {
    const started = performance.now();
    parseInline("*".repeat(2000));
    parseInline("**a".repeat(600));
    expect(performance.now() - started).toBeLessThan(500);
  });
});

describe("parseMarkdown", () => {
  it("reads headings, a paragraph and a list", () => {
    expect(parseMarkdown("# Budget\n\nKeep **food** low.\n\n- rent\n- bills\n")).toEqual([
      { kind: "heading", level: 1, children: [text("Budget")] },
      { kind: "paragraph", children: [text("Keep "), { kind: "bold", children: [text("food")] }, text(" low.")] },
      { kind: "list", items: [[text("rent")], [text("bills")]] },
    ]);
  });

  it("supports three heading levels and no more", () => {
    const [h1, h2, h3, h4] = parseMarkdown("# a\n## b\n### c\n#### d");
    expect([h1, h2, h3].map((h) => (h.kind === "heading" ? h.level : 0))).toEqual([1, 2, 3]);
    expect(h4).toEqual({ kind: "paragraph", children: [text("#### d")] });
  });

  it("keeps the line breaks inside a paragraph", () => {
    expect(parseMarkdown("one\ntwo")).toEqual([{ kind: "paragraph", children: [text("one\ntwo")] }]);
  });

  it("accepts * as a bullet and ends a list at a paragraph", () => {
    expect(parseMarkdown("* a\n* b\nafter")).toEqual([
      { kind: "list", items: [[text("a")], [text("b")]] },
      { kind: "paragraph", children: [text("after")] },
    ]);
  });

  it("treats a # without a space as text", () => {
    expect(parseMarkdown("#hashtag")).toEqual([{ kind: "paragraph", children: [text("#hashtag")] }]);
  });

  it("handles Windows line endings, blank input and extra blank lines", () => {
    expect(parseMarkdown("a\r\n\r\n\r\nb")).toHaveLength(2);
    expect(parseMarkdown("")).toEqual([]);
    expect(parseMarkdown("\n \n")).toEqual([]);
  });
});
