/** v0.10.1 section 3.5: a file's type as people say it — Word, PDF, Excel, Image… — never a MIME string. */
export type FileKind = "pdf" | "word" | "excel" | "image" | "text" | "archive" | "email" | "other";

const BY_EXT: Record<string, FileKind> = {
  pdf: "pdf", doc: "word", docx: "word", rtf: "word", odt: "word", xls: "excel", xlsx: "excel", csv: "excel", ods: "excel",
  png: "image", jpg: "image", jpeg: "image", gif: "image", webp: "image", tif: "image", tiff: "image", bmp: "image", heic: "image",
  txt: "text", md: "text", zip: "archive", rar: "archive", "7z": "archive", eml: "email", msg: "email",
};

export function fileKind(mime: string | null | undefined, name?: string | null): FileKind {
  const m = (mime ?? "").toLowerCase();
  if (m === "application/pdf") return "pdf";
  if (m.includes("wordprocessingml") || m === "application/msword" || m.includes("opendocument.text")) return "word";
  if (m.includes("spreadsheetml") || m === "application/vnd.ms-excel" || m === "text/csv" || m.includes("opendocument.spreadsheet")) return "excel";
  if (m.startsWith("image/")) return "image";
  if (m === "message/rfc822" || m.includes("outlook")) return "email";
  if (m.includes("zip") || m.includes("rar") || m.includes("7z")) return "archive";
  const ext = (name ?? "").toLowerCase().split(".").pop() ?? "";
  if (BY_EXT[ext]) return BY_EXT[ext];
  if (m.startsWith("text/")) return "text";
  return "other";
}

export const FILE_ICON: Record<FileKind, string> = { pdf: "file", word: "file", excel: "grid", image: "eye", text: "list", archive: "box", email: "inbox", other: "file" };
