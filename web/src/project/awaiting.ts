// Canvases whose device was asked for as a companion: linked to the others once it is built.
// Kept apart from project.ts so the network client can mark one without importing the scene.
export const awaitingLink = new Set<string>();

export function linkWhenBuilt(canvasId: string): void {
  awaitingLink.add(canvasId);
}
