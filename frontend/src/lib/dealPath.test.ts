/** v0.10.0 deal path from the line items and the case status. */
import { describe, expect, it } from "vitest";

import { pathPercent, pathSteps, reached } from "./dealPath";

describe("deal path", () => {
  it("an inquiry without offers is at the inquiry step", () => {
    expect(reached([], "open")).toBe(0);
    expect(reached(["uncovered", "rfq_sent"], "open")).toBe(0);
  });
  it("offers, then the order, then shipping when a shipment exists", () => {
    expect(reached(["has_offer", "uncovered"], "open")).toBe(1);
    expect(reached(["selected", "sold"], "open")).toBe(2);
    expect(reached(["sold"], "open", true)).toBe(3);
  });
  it("delivery while some items are delivered, closing when all are, done when the case is closed", () => {
    expect(reached(["delivered", "sold"], "open")).toBe(4);
    expect(reached(["delivered", "delivered", "cancelled"], "open")).toBe(5);
    expect(reached(["delivered"], "closed")).toBe(6);
  });
  it("cancelled items do not count", () => {
    expect(reached(["cancelled"], "open")).toBe(0);
  });
  it("marks the steps and the share done", () => {
    expect(pathSteps(["sold"], "open", true).map((s) => s.state)).toEqual(["done", "done", "done", "current", "upcoming", "upcoming"]);
    expect(pathSteps([], "closed").every((s) => s.state === "done")).toBe(true);
    expect(pathPercent(["sold"], "open", true)).toBe(50);
  });
});
