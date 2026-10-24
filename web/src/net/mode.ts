// Mock-mode switches (SPEC 13): ?mock=1 or VITE_MOCK=1, ?mock_speed, ?mock_fixture.
export interface Mode {
  mock: boolean;
  speed: number;
  fixture: string | null;
}

export function readMode(search: string, env: { VITE_MOCK?: string }): Mode {
  const q = new URLSearchParams(search);
  const mock = q.get("mock") === "1" || env.VITE_MOCK === "1";
  const rawSpeed = Number(q.get("mock_speed") ?? "1");
  const speed = Number.isFinite(rawSpeed) && rawSpeed > 0 ? rawSpeed : 1;
  const fixture = q.get("mock_fixture");
  return { mock, speed, fixture: fixture && /^[a-z0-9_]+$/.test(fixture) ? fixture : null };
}

export function socketUrl(loc: { protocol: string; host: string }): string {
  return `${loc.protocol === "https:" ? "wss" : "ws"}://${loc.host}/v1/ws`;
}
