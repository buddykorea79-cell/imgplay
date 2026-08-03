import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  horizontalListSortingStrategy,
  sortableKeyboardCoordinates,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { api } from "../../api";
import { useStore } from "../../store";
import { Button, ClampBadge } from "../ui";
import type { TimelineItem, TransitionSpec } from "../../types";

function Clip({ item, selected, onSelect }: {
  item: TimelineItem;
  selected: boolean;
  onSelect: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: item.id });

  const zoomLabel =
    item.zoom_start === item.zoom_end
      ? "줌 없음"
      : item.zoom_start < item.zoom_end
        ? `줌인 ${item.zoom_end.toFixed(2)}×`
        : `줌아웃 ${item.zoom_start.toFixed(2)}×`;

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={`shrink-0 ${isDragging ? "z-10 opacity-70" : ""}`}
    >
      <button
        type="button"
        onClick={onSelect}
        {...attributes}
        {...listeners}
        className={`w-32 cursor-grab overflow-hidden rounded border-2 text-left active:cursor-grabbing ${
          selected
            ? "border-sky-400"
            : item.clamped.length
              ? "border-clamp/50"
              : "border-ink-600"
        }`}
      >
        <div className="relative">
          <img
            src={api.originalUrl(item.id, "fit", { longEdge: 200 })}
            alt={item.filename}
            loading="lazy"
            className="h-20 w-full bg-ink-900 object-contain"
          />
          <span className="absolute bottom-0 right-0 bg-ink-900/90 px-1 font-mono text-[10px] text-slate-300">
            {item.duration_sec.toFixed(1)}s
          </span>
          {item.aspect_mode !== "none" && (
            <span className="absolute left-0 top-0 bg-ink-900/90 px-1 text-[10px] text-slate-400">
              {item.aspect_mode}
            </span>
          )}
        </div>
        <div className="space-y-0.5 bg-ink-800 px-1 py-1">
          <p className="truncate text-[10px] text-slate-300">
            {item.index + 1}. {item.filename}
          </p>
          <p className="font-mono text-[9px] text-slate-500">{zoomLabel}</p>
          {item.clamped.length > 0 && <ClampBadge items={item.clamped} />}
        </div>
      </button>
    </div>
  );
}

function Transition({
  spec,
  onPreview,
}: {
  spec: TransitionSpec;
  onPreview: () => void;
}) {
  const isBlack = spec.type === "fadeblack";
  return (
    <button
      type="button"
      onClick={onPreview}
      title={`${spec.reason}\n클릭하면 전환만 미리보기`}
      className="flex w-14 shrink-0 flex-col items-center justify-center gap-0.5 self-center rounded border border-ink-700 px-1 py-2 hover:border-sky-500"
    >
      <span
        className={`text-[10px] font-medium ${isBlack ? "text-clamp" : "text-slate-400"}`}
      >
        {spec.type}
      </span>
      <span className="font-mono text-[9px] text-slate-600">
        {spec.duration_sec.toFixed(1)}s
      </span>
      <span className="font-mono text-[9px] text-slate-600">
        d={spec.hist_distance.toFixed(2)}
      </span>
    </button>
  );
}

export function Timeline({
  selectedId,
  onSelect,
  onPreviewTransition,
}: {
  selectedId: string | null;
  onSelect: (id: string) => void;
  onPreviewTransition: (index: number) => void;
}) {
  const { timeline, transitions, reorder, sortByTime, motionEval } = useStore();
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const onDragEnd = (e: DragEndEvent) => {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    const ids = timeline.map((i) => i.id);
    const next = arrayMove(ids, ids.indexOf(String(active.id)), ids.indexOf(String(over.id)));
    void reorder(next);
  };

  if (!timeline.length) {
    return <p className="p-4 text-sm text-slate-500">타임라인이 비어 있습니다.</p>;
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-baseline gap-3 text-xs">
          <span className="text-slate-400">
            총 길이{" "}
            <span className="font-mono text-base text-slate-200">
              {(motionEval?.total_duration_sec ?? 0).toFixed(1)}초
            </span>
          </span>
          <span className="text-slate-600">
            = 클립 합 {(motionEval?.sum_duration_sec ?? 0).toFixed(1)} − 전환{" "}
            {(motionEval?.transition_saving_sec ?? 0).toFixed(1)}
          </span>
        </div>
        <Button onClick={() => void sortByTime()} title="EXIF 촬영시각 순으로 되돌립니다">
          촬영시각 순 정렬
        </Button>
      </div>

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext
          items={timeline.map((i) => i.id)}
          strategy={horizontalListSortingStrategy}
        >
          <div className="flex items-stretch gap-1 overflow-x-auto rounded-lg bg-ink-900/60 p-2">
            {timeline.map((item, i) => (
              <div key={item.id} className="flex items-stretch gap-1">
                <Clip
                  item={item}
                  selected={selectedId === item.id}
                  onSelect={() => onSelect(item.id)}
                />
                {transitions[i] && (
                  <Transition
                    spec={transitions[i]}
                    onPreview={() => onPreviewTransition(i)}
                  />
                )}
              </div>
            ))}
          </div>
        </SortableContext>
      </DndContext>
      <p className="text-[11px] text-slate-600">
        드래그해서 순서를 바꿀 수 있습니다 · 전환 칩을 누르면 그 전환만 미리보기
      </p>
    </div>
  );
}
