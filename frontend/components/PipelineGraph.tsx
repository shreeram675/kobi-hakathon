"use client";

import "reactflow/dist/style.css";
import { useCallback, useMemo } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Handle,
  Position,
  type Edge,
  type Node,
  type NodeProps,
} from "reactflow";
import { AlertCircle, Check, Loader2 } from "lucide-react";
import { PIPELINE_STAGES, type StageId } from "@/lib/schema";
import { stageStat } from "@/lib/stage-stat";
import { cn } from "@/lib/format";
import type { AgentState, StageStatus } from "@/lib/types";

interface StageNodeData {
  index: number;
  label: string;
  status: StageStatus;
  stat: { value: string; label: string } | null;
  focused: boolean;
}

const NODE_W = 248;
const NODE_H = 66;
const Y_STEP = 92;

function StageNode({ data }: NodeProps<StageNodeData>) {
  const { status, focused } = data;
  return (
    <div
      style={{ width: NODE_W }}
      className={cn(
        "group relative flex items-center gap-3 rounded-card border bg-white px-3 py-2.5 transition-all",
        status === "done" && "border-l-4 border-l-green border-line",
        status === "error" && "border-l-4 border-l-red border-line",
        status === "running" && "border-teal shadow-[0_0_0_3px_rgba(15,124,125,0.25)]",
        status === "idle" && "border-line opacity-70",
        focused && "ring-2 ring-navy ring-offset-2",
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-transparent" />
      <StatusDot status={status} index={data.index} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-semibold text-navy">{data.label}</p>
        {data.stat ? (
          <p className="stat-num truncate text-[11px] text-ink/55">
            <span className="font-semibold text-ink">{data.stat.value}</span>{" "}
            {data.stat.label}
          </p>
        ) : (
          <p className="text-[11px] capitalize text-ink/40">{status}</p>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-transparent" />
    </div>
  );
}

function StatusDot({ status, index }: { status: StageStatus; index: number }) {
  return (
    <span
      className={cn(
        "grid h-8 w-8 shrink-0 place-items-center rounded-full text-xs font-semibold",
        status === "done" && "bg-soft-green text-green",
        status === "running" && "bg-[#e2f3f3] text-teal",
        status === "error" && "bg-soft-red text-red",
        status === "idle" && "bg-soft-grey text-ink/40",
      )}
    >
      {status === "done" ? (
        <Check className="h-4 w-4" />
      ) : status === "running" ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : status === "error" ? (
        <AlertCircle className="h-4 w-4" />
      ) : (
        index
      )}
    </span>
  );
}

const nodeTypes = { stage: StageNode };

/** Vertical directed pipeline graph (nodes 1-9) with animated active edges. */
export function PipelineGraph({
  state,
  focused,
  onFocus,
}: {
  state: AgentState;
  focused: StageId | null;
  onFocus: (id: StageId) => void;
}) {
  const nodes: Node<StageNodeData>[] = useMemo(
    () =>
      PIPELINE_STAGES.map((stage, i) => {
        const status = (state.stage_status?.[stage.id] ?? "idle") as StageStatus;
        return {
          id: stage.id,
          type: "stage",
          position: { x: 0, y: i * Y_STEP },
          data: {
            index: stage.index,
            label: stage.label,
            status,
            stat: stageStat(state, stage.id),
            focused: focused === stage.id,
          },
          draggable: false,
          connectable: false,
        };
      }),
    [state, focused],
  );

  const edges: Edge[] = useMemo(
    () =>
      PIPELINE_STAGES.slice(0, -1).map((stage, i) => {
        const next = PIPELINE_STAGES[i + 1];
        const sourceDone = state.stage_status?.[stage.id] === "done";
        const targetRunning = state.stage_status?.[next.id] === "running";
        const bothDone = sourceDone && state.stage_status?.[next.id] === "done";
        const active = sourceDone && targetRunning;
        return {
          id: `${stage.id}-${next.id}`,
          source: stage.id,
          target: next.id,
          type: "smoothstep",
          className: cn(active && "is-active", bothDone && "is-done"),
          animated: false,
        };
      }),
    [state],
  );

  const onNodeClick = useCallback(
    (_: unknown, node: Node) => onFocus(node.id as StageId),
    [onFocus],
  );

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={onNodeClick}
      fitView
      fitViewOptions={{ padding: 0.12 }}
      minZoom={0.4}
      maxZoom={1.3}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable
      panOnScroll
      zoomOnScroll={false}
      zoomOnDoubleClick={false}
      proOptions={{ hideAttribution: true }}
      className="bg-transparent"
    >
      <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#d9e2ec" />
    </ReactFlow>
  );
}
