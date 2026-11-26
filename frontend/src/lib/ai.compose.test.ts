/** v0.10.1 (0.4.1): a preset chip fills or extends «دستور به هوش», and a second press takes it out again. */
import { describe, expect, it } from "vitest";

import { togglePreset } from "./ai";

describe("instruction presets", () => {
  it("fills an empty instruction, extends a typed one and toggles off", () => {
    expect(togglePreset("", "رسمی")).toBe("رسمی");
    expect(togglePreset("زمان تحویل را بپرس", "کوتاه")).toBe("زمان تحویل را بپرس، کوتاه");
    expect(togglePreset("زمان تحویل را بپرس، کوتاه", "کوتاه")).toBe("زمان تحویل را بپرس");
    expect(togglePreset("ask MOQ, short", "formal")).toBe("ask MOQ، short، formal");
  });
});
