import { useState } from "react";
import { Database, Send, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { ErrorNote } from "@/components/States";

type Answer = {
  answer: string;
  sql: string | null;
  row_count: number;
  rows: Record<string, unknown>[];
  attempts: number;
  error: string | null;
};

const EXAMPLES = [
  "How many calls did we get each day this week?",
  "Which provider has the most booked appointments?",
  "What's the average feedback rating by call intent?",
  "How many changes are waiting for staff approval?",
];

export function AdminAnalytics() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function ask(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError("");
    setAnswer(null);
    try {
      setAnswer(await api.post<Answer>("/agent/analytics", { question: trimmed }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not answer that");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Ask the data</h1>
        <p className="text-sm text-muted-foreground">
          Plain-English questions about clinic operations. The agent may only read, and only
          from clinic tables — it shows you exactly what it ran.
        </p>
      </div>

      <Card>
        <CardContent className="pt-6">
          <div className="flex gap-2">
            <Input
              value={question}
              placeholder="Which provider has the most cancellations?"
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && ask(question)}
            />
            <Button onClick={() => ask(question)} disabled={busy || !question.trim()}>
              <Send className="size-4" />
              Ask
            </Button>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                className="rounded-full border px-3 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
                onClick={() => {
                  setQuestion(example);
                  ask(example);
                }}
              >
                {example}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {busy && <p className="text-sm text-muted-foreground">Working it out…</p>}
      {error && <ErrorNote message={error} />}

      {answer && (
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Sparkles className="size-4 text-primary" /> Answer
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="leading-relaxed">{answer.answer}</p>
              {answer.attempts > 1 && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Took {answer.attempts} attempts — the first query was rejected and repaired.
                </p>
              )}
            </CardContent>
          </Card>

          {answer.sql && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Database className="size-4" /> Query it ran
                </CardTitle>
                <CardDescription>{answer.row_count} rows returned</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <pre className="overflow-x-auto rounded-lg bg-secondary p-3 text-xs leading-relaxed">
                  {answer.sql}
                </pre>
                {answer.rows.length > 0 && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-left text-muted-foreground">
                          {Object.keys(answer.rows[0]).map((key) => (
                            <th key={key} className="py-2 pr-4 font-medium">
                              {key}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {answer.rows.map((row, index) => (
                          <tr key={index} className="border-b last:border-0">
                            {Object.values(row).map((value, i) => (
                              <td key={i} className="py-2 pr-4">
                                {String(value ?? "—")}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
