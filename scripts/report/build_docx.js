// Render reports/report_content.json (built by scripts/make_report.py) into a Word report.
//   node scripts/report/build_docx.js reports/report_content.json reports/LogPulse_Report.docx
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, Table, TableRow, TableCell,
  WidthType, ShadingType, BorderStyle, ImageRun, PageBreak, TableOfContents, Footer, PageNumber,
  LevelFormat, Header, TabStopType,
} = require("docx");

const [, , inPath, outPath] = process.argv;
const doc = JSON.parse(fs.readFileSync(inPath, "utf8"));
const ROOT = path.resolve(path.dirname(inPath), "..");

const PAGE_W = 11906, PAGE_H = 16838, MARGIN = 1440;           // A4, 1" margins
const CONTENT_W = PAGE_W - 2 * MARGIN;                           // 9026 DXA
const FONT = "Times New Roman";
const ACCENT = "1C5CAB";
const GRID = "C3C2B7";

// inline **bold**, *italic*, `code`
function runs(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g;
  let last = 0, m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
    const t = m[0];
    if (t.startsWith("**")) out.push(new TextRun({ text: t.slice(2, -2), bold: true, ...base }));
    else if (t.startsWith("`")) out.push(new TextRun({ text: t.slice(1, -1), font: "Consolas", size: (base.size || 24) - 4 }));
    else out.push(new TextRun({ text: t.slice(1, -1), italics: true, ...base }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out;
}

function para(text, opts = {}) {
  return new Paragraph({ children: runs(text), spacing: { after: 120, line: 300 }, alignment: AlignmentType.JUSTIFIED, ...opts });
}

function table(b) {
  const cols = b.columns;
  const weights = b.weights || cols.map((c, i) => Math.max(c.length, ...b.rows.map(r => String(r[i] ?? "").length), 4));
  const total = weights.reduce((a, c) => a + c, 0);
  let widths = weights.map(w => Math.max(700, Math.round(CONTENT_W * w / total)));
  const s = widths.reduce((a, c) => a + c, 0);
  widths = widths.map(w => Math.round(w * CONTENT_W / s));
  widths[widths.length - 1] += CONTENT_W - widths.reduce((a, c) => a + c, 0);
  const border = { style: BorderStyle.SINGLE, size: 4, color: GRID };
  const borders = { top: border, bottom: border, left: border, right: border };
  const cell = (txt, i, head) => new TableCell({
    width: { size: widths[i], type: WidthType.DXA }, borders,
    shading: head ? { fill: "E8F0FB", type: ShadingType.CLEAR, color: "auto" } : undefined,
    margins: { top: 40, bottom: 40, left: 80, right: 80 },
    children: [new Paragraph({ children: runs(String(txt ?? ""), { size: 17, bold: head ? true : undefined }),
      alignment: i === 0 ? AlignmentType.LEFT : AlignmentType.CENTER })],
  });
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: widths,
    rows: [new TableRow({ tableHeader: true, children: cols.map((c, i) => cell(c, i, true)) }),
           ...b.rows.map(r => new TableRow({ children: r.map((v, i) => cell(v, i, false)) }))],
  });
}

function caption(text) {
  return new Paragraph({ children: runs(text, { size: 20, italics: true, color: "52514E" }),
    alignment: AlignmentType.CENTER, spacing: { before: 80, after: 240 } });
}

function figure(b) {
  const file = path.join(ROOT, b.path);
  if (!fs.existsSync(file)) return [para(`[missing figure: ${b.path}]`)];
  const buf = fs.readFileSync(file);
  const w = buf.readUInt32BE(16), h = buf.readUInt32BE(20);              // PNG IHDR
  const maxW = (b.width_in || 6.2) * 96;
  const width = Math.min(maxW, w), height = Math.round(h * width / w);
  return [new Paragraph({ alignment: AlignmentType.CENTER, keepNext: true, spacing: { before: 120 },
    children: [new ImageRun({ type: "png", data: buf, transformation: { width, height },
      altText: { title: b.caption || b.path, description: b.caption || b.path, name: path.basename(b.path) } })] }),
    caption(b.caption || "")];
}

const children = [];
for (const b of doc.blocks) {
  switch (b.type) {
    case "title":
      children.push(new Paragraph({ spacing: { before: 2400 } }));
      children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240 },
        children: [new TextRun({ text: b.text, bold: true, size: 40, color: ACCENT })] }));
      for (const line of b.lines || [])
        children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 }, children: runs(line, { size: 26 }) }));
      children.push(new Paragraph({ children: [new PageBreak()] }));
      break;
    case "toc":
      children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Contents")] }));
      children.push(new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }));
      children.push(new Paragraph({ children: runs("*Right-click → Update field in Word to refresh page numbers.*", { size: 18, color: "898781" }) }));
      children.push(new Paragraph({ children: [new PageBreak()] }));
      break;
    case "h1": children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: !!b.break, children: [new TextRun(b.text)] })); break;
    case "h2": children.push(new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(b.text)] })); break;
    case "h3": children.push(new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(b.text)] })); break;
    case "p": children.push(para(b.text)); break;
    case "bullets":
      for (const it of b.items) children.push(new Paragraph({ numbering: { reference: b.numbered ? "nums" : "bullets", level: 0 },
        children: runs(it), spacing: { after: 60, line: 288 } }));
      break;
    case "table":
      if (b.title) children.push(new Paragraph({ keepNext: true, spacing: { before: 200, after: 80 },
        children: runs(b.title, { bold: true, size: 21 }) }));
      children.push(table(b));
      if (b.note) children.push(caption(b.note)); else children.push(new Paragraph({ spacing: { after: 160 } }));
      break;
    case "figure": children.push(...figure(b)); break;
    case "code":
      for (const line of b.text.split("\n"))
        children.push(new Paragraph({ spacing: { after: 0, line: 240 }, shading: { fill: "F5F5F2", type: ShadingType.CLEAR, color: "auto" },
          children: [new TextRun({ text: line || " ", font: "Consolas", size: 17 })] }));
      children.push(new Paragraph({ spacing: { after: 160 } }));
      break;
    case "pagebreak": children.push(new Paragraph({ children: [new PageBreak()] })); break;
    default: throw new Error("unknown block " + b.type);
  }
}

const document = new Document({
  creator: doc.author || "LogPulse team", title: doc.title, description: "LogPulse project report",
  styles: {
    default: { document: { run: { font: FONT, size: 24 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: FONT, color: ACCENT }, paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 27, bold: true, font: FONT }, paragraph: { spacing: { before: 280, after: 140 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, italics: true, font: FONT }, paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 2 } },
    ],
  },
  numbering: { config: [
    { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] },
    { reference: "nums", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 540, hanging: 300 } } } }] },
  ] },
  sections: [{
    properties: { page: { size: { width: PAGE_W, height: PAGE_H }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
      children: [new TextRun({ text: doc.short_title || doc.title, size: 18, color: "898781" })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ children: [PageNumber.CURRENT], size: 18, color: "898781" })] })] }) },
    children,
  }],
});

Packer.toBuffer(document).then(buf => { fs.writeFileSync(outPath, buf); console.log("wrote", outPath); });
