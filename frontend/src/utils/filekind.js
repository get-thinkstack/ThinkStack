/**
 * What kind of file this is, by name.
 *
 * Its own module because FileTree exports a component: a file that exports both
 * a component and plain helpers breaks Vite's fast refresh, so editing the tree
 * would reload the whole module and drop the app's state on every keystroke.
 *
 * By extension rather than by content because the tree only ever has a name to
 * go on -- the listing endpoint deliberately does not read every file to sniff
 * its type.
 */

const IMAGE = ['.png', '.jpg', '.jpeg', '.svg'];

/** shown in the editor pane as a picture. */
export const isImage = (path) =>
  IMAGE.some((s) => String(path).toLowerCase().endsWith(s));

/** shown in the PREVIEW pane, since that is already a PDF viewer. */
export const isPdf = (path) => String(path).toLowerCase().endsWith('.pdf');
