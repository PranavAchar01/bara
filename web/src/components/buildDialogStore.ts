// Whether the Build pop-up is open, kept apart from the pop-up itself so the landing can open it
// without loading the workspace code the pop-up's prompt brings along.
import { create } from "zustand";

export const useBuildDialog = create<{ open: boolean; seed: string | null }>(() => ({ open: false, seed: null }));
/** Opens the dialog; with a seed, its prompt starts filled in (an example, or a gallery build to make again). */
export const openBuildDialog = (seed: string | null = null) => useBuildDialog.setState({ open: true, seed });
export const closeBuildDialog = () => useBuildDialog.setState({ open: false, seed: null });
