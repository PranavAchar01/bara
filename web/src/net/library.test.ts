import { describe, expect, it } from "vitest";
import { RestClient, paths } from "./rest";

describe("library rest", () => {
  it("encodes the build id and uses DELETE", async () => {
    const seen: string[] = [];
    const rc = new RestClient(async (method, path) => {
      seen.push(`${method} ${path}`);
      return { status: 200, body: { deleted: "b_x" } };
    });
    expect((await rc.delete(paths.libraryBuild("b_x"))).ok).toBe(true);
    expect(seen).toEqual(["DELETE /v1/library/b_x"]);
    expect(paths.libraryBuild("../x")).toBe("/v1/library/..%2Fx");
  });

  it("reports failure when the stub has no library (callers show an empty list)", async () => {
    const rc = new RestClient(async () => ({
      status: 404,
      body: { error: { code: "E_NOT_FOUND", message: "x", retryable: false } },
    }));
    expect((await rc.get(paths.library())).ok).toBe(false);
  });
});
