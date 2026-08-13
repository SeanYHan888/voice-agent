import { useCallback, useEffect, useState } from "react";
import { Phone, Star } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Empty, ErrorNote, Loading } from "@/components/States";
import { api, type Call } from "@/lib/api";
import { cn } from "@/lib/utils";

const SENTIMENT_STYLE: Record<string, string> = {
  positive: "bg-success/10 text-success border-success/20",
  negative: "bg-destructive/10 text-destructive border-destructive/20",
};

function FeedbackForm({ call, onDone }: { call: Call; onDone: () => void }) {
  const [stars, setStars] = useState(0);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    if (!stars) return;
    setBusy(true);
    try {
      await api.post("/domain/feedback", { call_id: call.id, stars, comment: comment || null });
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save your feedback");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 rounded-lg border bg-secondary/40 p-3">
      <div className="flex items-center gap-1">
        <span className="mr-2 text-sm text-muted-foreground">How did Maya do?</span>
        {[1, 2, 3, 4, 5].map((value) => (
          <button
            key={value}
            type="button"
            aria-label={`${value} star${value > 1 ? "s" : ""}`}
            onClick={() => setStars(value)}
          >
            <Star
              className={cn(
                "size-5 transition-colors",
                value <= stars ? "fill-amber-400 text-amber-400" : "text-muted-foreground/40",
              )}
            />
          </button>
        ))}
      </div>
      <Textarea
        rows={2}
        placeholder="Anything you'd like the clinic to know? (optional)"
        value={comment}
        onChange={(e) => setComment(e.target.value)}
      />
      {error && <ErrorNote message={error} />}
      <Button size="sm" disabled={!stars || busy} onClick={submit}>
        {busy ? "Sending…" : "Send feedback"}
      </Button>
    </div>
  );
}

export function CallHistory() {
  const [calls, setCalls] = useState<Call[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setCalls(await api.get<Call[]>("/domain/calls/me"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load your calls");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <Loading label="Loading your calls…" />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Call history</h1>
        <p className="text-sm text-muted-foreground">
          Every conversation with Maya, summarised automatically once the call ends.
        </p>
      </div>

      {error && <ErrorNote message={error} />}
      {calls.length === 0 && !error && <Empty>No calls yet.</Empty>}

      <div className="space-y-4">
        {calls.map((call) => (
          <Card key={call.id}>
            <CardHeader className="pb-3">
              <div className="flex flex-wrap items-center gap-2">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Phone className="size-4" />
                  {new Date(call.started_at).toLocaleString(undefined, {
                    month: "short",
                    day: "numeric",
                    hour: "numeric",
                    minute: "2-digit",
                  })}
                </CardTitle>
                {call.intent && <Badge variant="secondary">{call.intent.replace("_", " ")}</Badge>}
                {call.sentiment && (
                  <Badge variant="outline" className={SENTIMENT_STYLE[call.sentiment] ?? ""}>
                    {call.sentiment}
                  </Badge>
                )}
                {!call.ended_at && <Badge variant="outline">in progress</Badge>}
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm leading-relaxed">
                {call.summary ?? (
                  <span className="text-muted-foreground">Summary not written yet.</span>
                )}
              </p>
              {call.ended_at && !call.has_feedback && <FeedbackForm call={call} onDone={load} />}
              {call.has_feedback && (
                <p className="text-xs text-muted-foreground">Thanks — your feedback was recorded.</p>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
