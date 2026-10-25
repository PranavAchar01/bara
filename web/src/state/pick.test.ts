import { beforeEach, describe, expect, it } from "vitest";
import { pickPart, select, setPlayGuard, useApp } from "./store";

describe("pickPart", () => {
  let playing = false;
  beforeEach(() => {
    playing = false;
    setPlayGuard(() => playing);
    useApp.setState({ explode: 0, focusKey: null, selection: null, overlay: null });
  });
  it("a plain click on the assembled device never pulls a part out", () => {
    pickPart("p:switch");
    expect(useApp.getState().focusKey).toBeNull();
  });
  it("in the exploded view a click lifts the part out and a second puts it back", () => {
    useApp.setState({ explode: 1 });
    pickPart("p:switch");
    expect(useApp.getState().focusKey).toBe("p:switch");
    pickPart("p:switch");
    expect(useApp.getState().focusKey).toBeNull();
  });
  it("while playing a click neither picks, pulls out nor selects", () => {
    playing = true;
    useApp.setState({ explode: 1 });
    pickPart("p:switch");
    select("sw1");
    expect(useApp.getState().focusKey).toBeNull();
    expect(useApp.getState().selection).toBeNull();
  });
});
