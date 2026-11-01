// Builds the proforma (پیش‌فاکتور) Word template on the company letterhead.
// Placeholders use Jinja syntax ({{ ... }}) and are filled later by docxtpl.
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Header, Footer, Table, TableRow, TableCell,
  AlignmentType, WidthType, ShadingType, BorderStyle, VerticalAlign, LevelFormat,
  HorizontalPositionRelativeFrom, VerticalPositionRelativeFrom, TextWrappingType, HeightRule,
} = require("docx");

const FONT = "B Nazanin";
const NAVY = "0E2B6A";
const CM = 567;                       // twips per cm
const EMU_CM = 360000;                // EMU per cm
const PX_CM = 96 / 2.54;              // docx-js image px per cm
const S = 21 / 2200;                  // cm per letterhead pixel (image width = page width)

function r(text, o = {}) {
  return new TextRun({
    text, font: FONT, rightToLeft: true,
    bold: !!o.b, boldComplexScript: !!o.b,
    size: o.sz || 24, sizeComplexScript: o.sz || 24,
    color: o.color,
  });
}
function p(runs, o = {}) {
  return new Paragraph({
    bidirectional: true,
    alignment: o.align || AlignmentType.START,
    spacing: { before: o.before || 0, after: o.after ?? 80, line: o.line || 300 },
    indent: o.indent,
    numbering: o.bullet ? { reference: "bullets", level: 0 } : undefined,
    keepNext: o.keepNext,
    children: Array.isArray(runs) ? runs : [runs],
  });
}
function floatImg(file, xCm, yCm, wCm, hCm) {
  return new ImageRun({
    type: "png",
    data: fs.readFileSync(file),
    transformation: { width: wCm * PX_CM, height: hCm * PX_CM },
    floating: {
      horizontalPosition: { relative: HorizontalPositionRelativeFrom.PAGE, offset: Math.round(xCm * EMU_CM) },
      verticalPosition: { relative: VerticalPositionRelativeFrom.PAGE, offset: Math.round(yCm * EMU_CM) },
      behindDocument: true, allowOverlap: true, lockAnchor: true,
      wrap: { type: TextWrappingType.NONE },
    },
  });
}

// ---------------------------------------------------------------- header: letterhead pieces + شماره/تاریخ/پیوست
const labelIndent = Math.round((21 - 2.0 - 704 * S) * CM);   // right edge of printed labels in the original design
const headerLine = (label, value, first) => new Paragraph({
  bidirectional: true, alignment: AlignmentType.START,
  indent: { start: labelIndent },
  spacing: { before: 0, after: 0, line: Math.round(1.1 * CM), lineRule: "exact" },
  children: [
    ...(first ? [
      floatImg("band.png", 0, 0, 94 * S, 29.7),
      floatImg("hdr_logo.png", 1640 * S, 60 * S, 520 * S, 440 * S),
      floatImg("ftr_contact.png", 300 * S, 29.7 - 200 * S, 1600 * S, 200 * S),
    ] : []),
    r(label + " ", { b: true, sz: 24 }),
    r(value, { sz: 24 }),
  ],
});

const header = new Header({
  children: [
    headerLine("شماره:", "{{ شماره }}", true),
    headerLine("تاریخ:", "{{ تاریخ }}"),
    headerLine("پیوست:", "{{ پیوست }}"),
  ],
});

// ---------------------------------------------------------------- tables
const W = 11906 - Math.round(2.2 * CM) - Math.round(2.0 * CM);   // content width (twips)
const thin = { style: BorderStyle.SINGLE, size: 4, color: "9AA6B8" };
const borders = { top: thin, bottom: thin, left: thin, right: thin };

function cell(text, width, o = {}) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    columnSpan: o.span,
    borders,
    verticalAlign: VerticalAlign.CENTER,
    shading: o.fill ? { type: ShadingType.CLEAR, color: "auto", fill: o.fill } : undefined,
    margins: { top: 70, bottom: 70, left: 100, right: 100 },
    children: [p(r(text, { b: o.b, sz: o.sz || 22, color: o.color }), {
      align: o.align || AlignmentType.CENTER, after: 0, line: 276,
    })],
  });
}

// info table (seller / buyer)
const half = Math.round(W / 2);
const infoTable = new Table({
  visuallyRightToLeft: true,
  width: { size: W, type: WidthType.DXA },
  columnWidths: [half, W - half],
  rows: [
    new TableRow({ children: [
      cell("فروشنده: {{ نام_فروشنده }}", half, { align: AlignmentType.START, fill: "F3F6FA" }),
      cell("شناسه ملی: {{ شناسه_ملی }}     کد اقتصادی: {{ کد_اقتصادی }}", W - half, { align: AlignmentType.START, fill: "F3F6FA" }),
    ] }),
    new TableRow({ children: [
      cell("خریدار: {{ خریدار }}", half, { align: AlignmentType.START }),
      cell("شماره نیاز در سامانه ستاد: {{ شماره_نیاز }}", W - half, { align: AlignmentType.START }),
    ] }),
  ],
});

// items table — columns from right to left
const cols = [820, 3405, 900, 1000, 1650, W - (650 + 3575 + 900 + 1000 + 1650)];
const headers = ["ردیف", "شرح کالا / خدمات", "تعداد", "واحد", "فی (ریال)", "مبلغ کل (ریال)"];
const loopRow = (tag) => new TableRow({ children: [cell(tag, W, { span: 6 })] });
const totalRow = (label, value, o = {}) => new TableRow({ cantSplit: true, children: [
  cell(label, W - cols[5], { span: 5, align: AlignmentType.END, b: o.b, fill: o.fill }),
  cell(value, cols[5], { b: o.b, fill: o.fill }),
] });

const itemsTable = new Table({
  visuallyRightToLeft: true,
  width: { size: W, type: WidthType.DXA },
  columnWidths: cols,
  rows: [
    new TableRow({ tableHeader: true, cantSplit: true, height: { value: 480, rule: HeightRule.ATLEAST },
      children: headers.map((h, i) => cell(h, cols[i], { b: true, fill: NAVY, color: "FFFFFF" })) }),
    loopRow("{%tr for قلم in اقلام %}"),
    new TableRow({ cantSplit: true, children: [
      cell("{{ قلم.ردیف }}", cols[0]),
      cell("{{ قلم.شرح }}", cols[1], { align: AlignmentType.START }),
      cell("{{ قلم.تعداد }}", cols[2]),
      cell("{{ قلم.واحد }}", cols[3]),
      cell("{{ قلم.فی }}", cols[4]),
      cell("{{ قلم.مبلغ }}", cols[5]),
    ] }),
    loopRow("{%tr endfor %}"),
    totalRow("جمع", "{{ جمع }}"),
    totalRow("مالیات و عوارض ارزش افزوده ({{ نرخ_مالیات }} درصد)", "{{ مالیات }}"),
    totalRow("مبلغ قابل پرداخت", "{{ جمع_کل }}", { b: true, fill: "E8EEF7" }),
    new TableRow({ cantSplit: true, children: [
      cell("مبلغ به حروف: {{ جمع_به_حروف }} ریال", W, { span: 6, align: AlignmentType.START, fill: "F3F6FA" }),
    ] }),
  ],
});

// ---------------------------------------------------------------- body
const body = [
  p(r("پیش‌فاکتور", { b: true, sz: 34, color: NAVY }), { align: AlignmentType.CENTER, after: 200 }),
  p(r("{{ خطاب }}", { b: true, sz: 26 }), { after: 60 }),
  p([r("موضوع: ", { b: true }), r("پیش‌فاکتور نیاز شماره {{ شماره_نیاز }} – {{ شرح_نیاز }}")], { after: 160 }),
  p(r("با سلام و احترام؛"), { after: 60 }),
  p(r("عطف به نیاز شماره {{ شماره_نیاز }} مورخ {{ تاریخ_اعلان }} منتشرشده در سامانه تدارکات الکترونیکی دولت (ستاد)، بدین‌وسیله پیش‌فاکتور اقلام درخواستی به شرح جدول زیر تقدیم می‌گردد:"),
    { align: AlignmentType.BOTH, after: 160 }),
  infoTable,
  p(r(""), { after: 80 }),
  itemsTable,
  p(r(""), { after: 60 }),
  p(r("شرایط:", { b: true }), { after: 40, keepNext: true }),
  p([r("اعتبار پیش‌فاکتور: ", { b: true }), r("تا تاریخ {{ اعتبار_تا }}")], { bullet: true, after: 20 }),
  p([r("زمان تحویل: ", { b: true }), r("{{ زمان_تحویل }}")], { bullet: true, after: 20 }),
  p([r("محل تحویل: ", { b: true }), r("{{ محل_تحویل }}")], { bullet: true, after: 20 }),
  p([r("نحوه پرداخت: ", { b: true }), r("{{ نحوه_پرداخت }}")], { bullet: true, after: 20 }),
  p([r("هزینه حمل و ارسال: ", { b: true }), r("{{ هزینه_حمل }}")], { bullet: true, after: 20 }),
  p(r("{%p if توضیحات %}"), { after: 0 }),
  p([r("توضیحات: ", { b: true }), r("{{ توضیحات }}")], { bullet: true, after: 20 }),
  p(r("{%p endif %}"), { after: 0 }),
  p(r(""), { after: 200 }),
  // closing block, centred over the left half of the page (customary place for signature)
  ...[
    [r("با تجدید احترام")],
    [r("{{ نام_فروشنده }}", { b: true })],
    [r("{{ امضاکننده }}")],
    [r("مهر و امضا", { sz: 20, color: "8A94A6" })],
  ].map((runs) => p(runs, { align: AlignmentType.CENTER, indent: { start: Math.round(W * 0.55) }, after: 40, keepNext: true })),
];

const doc = new Document({
  creator: "Setadiran Manager",
  title: "قالب پیش‌فاکتور",
  styles: { default: { document: { run: { font: FONT, size: 24, sizeComplexScript: 24, rightToLeft: true } } } },
  numbering: { config: [{ reference: "bullets", levels: [{
    level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.START,
    style: { paragraph: { indent: { start: 420, hanging: 280 } } },
  }] }] },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838 },
        margin: {
          top: Math.round(5.3 * CM), bottom: Math.round(2.6 * CM),
          left: Math.round(2.2 * CM), right: Math.round(2.0 * CM),
          header: Math.round(1.15 * CM), footer: Math.round(0.5 * CM),
        },
      },
    },
    headers: { default: header },
    footers: { default: new Footer({ children: [new Paragraph({ children: [] })] }) },
    children: body,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(process.argv[2] || "proforma_template.docx", buf);
  console.log("written");
});
