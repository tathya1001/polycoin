// A deliberately small markdown for text panels: headings (#, ##, ###), bullet lists (- or *),
// paragraphs, and **bold**, *italic* / _italic_ and `code` inside them. Nothing else is
// interpreted: no HTML, no links, no images. The output is a tree of plain data that React
// renders as elements and text nodes, so what a user writes can never become markup, a link or
// a request. Anything that isn't one of the above simply stays literal text.

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "bold"; children: Inline[] }
  | { kind: "italic"; children: Inline[] }
  | { kind: "code"; text: string };

export type Block =
  | { kind: "heading"; level: 1 | 2 | 3; children: Inline[] }
  | { kind: "paragraph"; children: Inline[] }
  | { kind: "list"; items: Inline[][] };

const WORD = /[\p{L}\p{N}]/u;
const isWord = (char: string | undefined) => char !== undefined && WORD.test(char);

/** Inline markup: bold, italic and code, which may nest (bold around italic) but never cross. */
export function parseInline(source: string): Inline[] {
  const out: Inline[] = [];
  let buffer = "";
  const flush = () => {
    if (buffer) out.push({ kind: "text", text: buffer });
    buffer = "";
  };

  let i = 0;
  while (i < source.length) {
    const char = source[i];

    if (source.startsWith("**", i)) {
      const end = source.indexOf("**", i + 2);
      if (end > i + 2) {
        flush();
        out.push({ kind: "bold", children: parseInline(source.slice(i + 2, end)) });
        i = end + 2;
        continue;
      }
    }

    if (char === "`") {
      const end = source.indexOf("`", i + 1);
      if (end > i + 1) {
        flush();
        out.push({ kind: "code", text: source.slice(i + 1, end) });
        i = end + 1;
        continue;
      }
    }

    if (char === "*" || char === "_") {
      // The opening mark needs a word after it, the closing mark one before it; "_" must also sit
      // at a word edge, so snake_case_names and 2*3*4 stay as written.
      const end = source.indexOf(char, i + 1);
      const opens = source[i + 1] !== undefined && source[i + 1] !== " " && source[i + 1] !== char;
      const closes = end > i + 1 && source[end - 1] !== " ";
      const edges = char === "*" || (!isWord(source[i - 1]) && !isWord(source[end + 1]));
      if (opens && closes && edges) {
        flush();
        out.push({ kind: "italic", children: parseInline(source.slice(i + 1, end)) });
        i = end + 1;
        continue;
      }
    }

    buffer += char;
    i += 1;
  }
  flush();
  return out;
}

const HEADING = /^(#{1,3})\s+(.*)$/;
const BULLET = /^[-*]\s+(.*)$/;

/** Blocks, separated by blank lines. A heading is one line; a list is consecutive bullets. */
export function parseMarkdown(source: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: Inline[][] = [];

  const endParagraph = () => {
    if (paragraph.length) blocks.push({ kind: "paragraph", children: parseInline(paragraph.join("\n")) });
    paragraph = [];
  };
  const endList = () => {
    if (list.length) blocks.push({ kind: "list", items: list });
    list = [];
  };

  for (const raw of source.replace(/\r\n?/g, "\n").split("\n")) {
    const line = raw.trim();
    const heading = HEADING.exec(line);
    const bullet = BULLET.exec(line);

    if (!line) {
      endParagraph();
      endList();
    } else if (heading) {
      endParagraph();
      endList();
      blocks.push({ kind: "heading", level: heading[1].length as 1 | 2 | 3, children: parseInline(heading[2]) });
    } else if (bullet) {
      endParagraph();
      list.push(parseInline(bullet[1]));
    } else {
      endList();
      paragraph.push(line);
    }
  }
  endParagraph();
  endList();
  return blocks;
}
