import type { DragEvent } from "react";

/** Props für eine Fläche, auf die man Dateien ziehen kann; `onDrag` meldet, ob gerade etwas darüber schwebt. */
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
