import { describe, expect, it } from "vitest";

import { fileKind } from "./fileKind";

describe("friendly file types (v0.10.1 section 3.5)", () => {
  it("names files as Word, PDF, Excel or Image, by type and else by extension", () => {
    expect(fileKind("application/vnd.openxmlformats-officedocument.wordprocessingml.document")).toBe("word");
    expect(fileKind("application/pdf")).toBe("pdf");
    expect(fileKind("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).toBe("excel");
    expect(fileKind("image/jpeg")).toBe("image");
    expect(fileKind("application/octet-stream", "offer.XLSX")).toBe("excel");
    expect(fileKind(null, "mystery.bin")).toBe("other");
  });
});
