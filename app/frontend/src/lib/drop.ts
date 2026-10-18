import type { DragEvent } from "react";

/** Props for an area that accepts dragged files; `onDrag` reports whether something is hovering over it. */
export function dropTarget(onFiles: (files: File[]) => void, onDrag: (over: boolean) => void) {
  return {
    onDragOver: (evt: DragEvent) => { evt.preventDefault(); onDrag(true); },
    onDragLeave: () => onDrag(false),
    onDrop: (evt: DragEvent) => {
      evt.preventDefault();
      onDrag(false);
      onFiles([...evt.dataTransfer.files]);
    },
  };
}
