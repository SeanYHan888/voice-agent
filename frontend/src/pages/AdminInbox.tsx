import { useEffect, useState } from "react";
import { MessageSquare, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, ErrorNote, Loading } from "@/components/States";
import { api } from "@/lib/api";

type Code = {
  patient_id: number;
  phone: string;
  code: string;
  expires_at: string;
  consumed: boolean;
};

/**
 * Stands in for the patient's phone. Seeded patients carry fictional numbers no SMS can
 * reach, so verification codes surface here instead — admin-only, and the only reason
 * this page exists is the demo.
 */
export function AdminInbox() {
  const [codes, setCodes] = useState<Code[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    try {
      setCodes(await api.get<Code[]>("/domain/verification/debug/recent"));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load codes");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, []);

  if (loading) return <Loading label="Loading codes…" />;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">SMS inbox</h1>
          <p className="text-sm text-muted-foreground">
            Verification codes Maya issued. Stands in for the patient's phone, since mock
            patients use fictional numbers.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load}>
          <RefreshCw className="size-4" /> Refresh
        </Button>
      </div>

      {error && <ErrorNote message={error} />}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <MessageSquare className="size-4" /> Recent codes
          </CardTitle>
          <CardDescription>Each code lasts ten minutes and works once.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {codes.length === 0 ? (
            <Empty>No codes issued yet.</Empty>
          ) : (
            codes.map((code, index) => (
              <div key={index} className="flex items-center justify-between rounded-lg border px-4 py-3">
                <div>
                  <p className="font-mono text-lg tracking-widest">{code.code}</p>
                  <p className="text-sm text-muted-foreground">{code.phone}</p>
                </div>
                <Badge variant={code.consumed ? "outline" : "secondary"}>
                  {code.consumed ? "used" : "active"}
                </Badge>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
