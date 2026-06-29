"use client";

import { useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { AgentState } from "@/lib/types";

interface Props {
  state: AgentState;
  variant: "single" | "compare";
  size?: "sm" | "md" | "lg";
  className?: string;
}

export function DownloadPDFButton({ state, variant, size = "sm", className }: Props) {
  const [loading, setLoading] = useState(false);

  const handleDownload = async () => {
    setLoading(true);
    try {
      const { pdf } = await import("@react-pdf/renderer");
      const today   = new Date().toISOString().slice(0, 10);

      let fileName: string;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let doc: any;

      if (variant === "single") {
        const { SingleRunPDFDoc } = await import("@/components/pdf/SingleRunPDFDoc");
        const name = (state.program_name ?? state.user_input)
          .replace(/[^\w\s-]/g, "")
          .replace(/\s+/g, "_")
          .slice(0, 40);
        fileName = `Analysis_${name}_${today}.pdf`;
        doc      = <SingleRunPDFDoc state={state} />;
      } else {
        const { ComparisonPDFDoc } = await import("@/components/pdf/ComparisonPDFDoc");
        const compRun  = state.comparison_run;
        const programs = compRun?.programs ?? [
          state.program_name ?? state.user_input,
          state.compare_b?.program_name ?? "Program_B",
        ];
        const nameStr =
          programs.length === 2
            ? `${programs[0].replace(/\W+/g, "_")}_vs_${programs[1].replace(/\W+/g, "_")}`
            : `${programs.length}_Programs`;
        fileName = `Comparison_${nameStr.slice(0, 60)}_${today}.pdf`;
        doc      = <ComparisonPDFDoc state={state} />;
      }

      const blob = await pdf(doc).toBlob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href     = url;
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("PDF generation failed:", err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Button
      size={size}
      variant="outline"
      onClick={handleDownload}
      disabled={loading}
      className={className}
    >
      {loading ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <Download className="h-4 w-4" />
      )}
      {loading ? "Generating PDF…" : "Download PDF"}
    </Button>
  );
}
