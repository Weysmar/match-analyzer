import { expect, test } from "vitest";
import { product } from "./smoke";

test("the placeholder module loads", () => {
  expect(product).toBe("match-analyzer");
});
