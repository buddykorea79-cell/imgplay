import { useCallback, useRef, useState } from "react";
import { useStore } from "../store";

const ACCEPT = ".jpg,.jpeg,.png,.tif,.tiff,.webp,.bmp,.heic,.heif";

/** 폴더 드롭을 지원합니다 — 사진은 보통 폴더 단위로 존재합니다. */
async function filesFromDataTransfer(dt: DataTransfer): Promise<File[]> {
  const entries = Array.from(dt.items)
    .map((i) => (i.kind === "file" ? i.webkitGetAsEntry?.() : null))
    .filter(Boolean) as FileSystemEntry[];

  if (!entries.length) return Array.from(dt.files);

  const out: File[] = [];
  const walk = async (entry: FileSystemEntry): Promise<void> => {
    if (entry.isFile) {
      const file = await new Promise<File>((res, rej) =>
        (entry as FileSystemFileEntry).file(res, rej),
      );
      out.push(file);
      return;
    }
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    // readEntries는 한 번에 최대 100개만 돌려주므로 빌 때까지 반복해야 합니다.
    for (;;) {
      const batch = await new Promise<FileSystemEntry[]>((res, rej) =>
        reader.readEntries(res, rej),
      );
      if (!batch.length) break;
      for (const e of batch) await walk(e);
    }
  };
  for (const e of entries) await walk(e);
  return out;
}

export function UploadZone({ compact = false }: { compact?: boolean }) {
  const addFiles = useStore((s) => s.addFiles);
  const busy = useStore((s) => s.busy);
  const [over, setOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const accept = useCallback(
    (files: File[]) => {
      const images = files.filter((f) =>
        ACCEPT.split(",").some((ext) => f.name.toLowerCase().endsWith(ext)),
      );
      if (images.length) void addFiles(images);
    },
    [addFiles],
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        void filesFromDataTransfer(e.dataTransfer).then(accept);
      }}
      onClick={() => inputRef.current?.click()}
      className={`cursor-pointer rounded-lg border-2 border-dashed text-center transition ${
        over ? "border-sky-400 bg-sky-500/10" : "border-ink-600 hover:border-ink-600/80"
      } ${compact ? "px-3 py-3" : "px-6 py-12"}`}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => {
          accept(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
      {busy ? (
        <p className="text-sm text-sky-300">{busy}…</p>
      ) : compact ? (
        <p className="text-xs text-slate-400">+ 사진 추가</p>
      ) : (
        <>
          <p className="text-sm text-slate-300">사진 폴더를 여기에 끌어다 놓으세요</p>
          <p className="mt-1 text-xs text-slate-500">
            폴더째 드롭할 수 있습니다 · 한글 파일명 지원 · 원본은 수정되지 않습니다
          </p>
        </>
      )}
    </div>
  );
}
