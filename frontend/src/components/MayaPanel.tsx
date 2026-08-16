import { useEffect, useRef, useState } from "react";
import { Mic, Send, Wrench, ShieldAlert, BadgeCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { api, type ChatTurn } from "@/lib/api";
import { cn } from "@/lib/utils";

type Message = {
  who: "maya" | "you";
  text: string;
  tools?: string[];
  guard?: string | null;
};

const AGENT_ID = import.meta.env.VITE_ELEVENLABS_AGENT_ID as string | undefined;

/**
 * Maya's conversation surface. Text is the always-available path; when an ElevenLabs
 * agent is configured, the same session is also reachable by voice — both drive the
 * identical LangGraph workflow on the agent service.
 */
export function MayaPanel({ onCallChanged }: { onCallChanged?: () => void }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [verified, setVerified] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .post<{ session_id: string; greeting: string; verified: boolean }>("/agent/session", {
        transport: "browser",
      })
      .then((session) => {
        setSessionId(session.session_id);
        setVerified(session.verified);
        setMessages([{ who: "maya", text: session.greeting }]);
      })
      .catch(() => {
        setMessages([{ who: "maya", text: "Maya is unavailable right now." }]);
      });
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  // The voice widget dispatches `elevenlabs-convai:call` just before it connects, with a
  // mutable session config. Stamp our session id on it as the user id and as a dynamic
  // variable the agent's system prompt interpolates, so the voice turns land in the same
  // LangGraph thread as the text ones. Without this every voice turn is a stranger and
  // Maya re-asks what she already knows.
  //
  // Deliberately NOT set: customLlmExtraBody. ElevenLabs treats that as an override the
  // agent must explicitly permit, and refuses the whole call otherwise ("Custom LLM extra
  // body override is not allowed for this AI agent"). The two channels above need no
  // dashboard permission.
  useEffect(() => {
    if (!AGENT_ID || !sessionId) return;
    const widget = document.getElementById("voice-widget");
    if (!widget) return;
    const stamp = (event: Event) => {
      const config = (event as CustomEvent<{ config: Record<string, unknown> }>).detail?.config;
      if (!config) return;
      config.userId = sessionId;
      config.dynamicVariables = {
        ...((config.dynamicVariables as Record<string, unknown> | undefined) ?? {}),
        session_id: sessionId,
      };
    };
    widget.addEventListener("elevenlabs-convai:call", stamp);
    return () => widget.removeEventListener("elevenlabs-convai:call", stamp);
  }, [sessionId]);

  async function send() {
    const text = draft.trim();
    if (!text || !sessionId || busy) return;
    setDraft("");
    setMessages((prev) => [...prev, { who: "you", text }]);
    setBusy(true);
    try {
      const turn = await api.post<ChatTurn>("/agent/chat", { session_id: sessionId, message: text });
      setVerified(turn.verified);
      setMessages((prev) => [
        ...prev,
        { who: "maya", text: turn.reply, tools: turn.tools_called, guard: turn.guard },
      ]);
      if (turn.tools_called.some((t) => t.includes("appointment"))) onCallChanged?.();
    } catch {
      setMessages((prev) => [
        ...prev,
        { who: "maya", text: "Sorry — I couldn't reach the clinic system just then." },
      ]);
    } finally {
      setBusy(false);
    }
  }

  async function endCall() {
    if (!sessionId) return;
    await api.post(`/agent/calls/${sessionId}/wrapup`).catch(() => {});
    setMessages((prev) => [...prev, { who: "maya", text: "— call ended, summary being written —" }]);
    onCallChanged?.();
  }

  return (
    <div className="flex h-[32rem] flex-col overflow-hidden rounded-xl border bg-white">
      <div className="flex items-center gap-2 border-b px-4 py-3">
        <span className="relative flex size-2">
          <span className="absolute inline-flex size-2 animate-ping rounded-full bg-success opacity-60" />
          <span className="relative inline-flex size-2 rounded-full bg-success" />
        </span>
        <span className="font-medium">Maya</span>
        <span className="text-xs text-muted-foreground">scheduling assistant</span>
        {verified && (
          <Badge variant="secondary" className="ml-2 gap-1 text-xs">
            <BadgeCheck className="size-3" /> verified
          </Badge>
        )}
        <Button variant="ghost" size="sm" className="ml-auto text-xs" onClick={endCall}>
          End call
        </Button>
      </div>

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {messages.map((message, index) => (
          <div
            key={index}
            className={cn("flex flex-col gap-1", message.who === "you" ? "items-end" : "items-start")}
          >
            <div
              className={cn(
                "max-w-[85%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed",
                message.who === "you"
                  ? "bg-primary text-primary-foreground"
                  : "bg-secondary text-secondary-foreground",
              )}
            >
              {message.text}
            </div>
            {(message.tools?.length || message.guard) && (
              <div className="flex flex-wrap gap-1 px-1">
                {message.guard && (
                  <Badge variant="outline" className="gap-1 text-[10px] text-destructive">
                    <ShieldAlert className="size-3" />
                    {message.guard}
                  </Badge>
                )}
                {message.tools?.map((tool, i) => (
                  <Badge key={i} variant="outline" className="gap-1 text-[10px] font-normal">
                    <Wrench className="size-3" />
                    {tool}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && <p className="px-1 text-xs text-muted-foreground">Maya is thinking…</p>}
      </div>

      <form
        className="flex items-center gap-2 border-t px-3 py-3"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <Input
          value={draft}
          disabled={!sessionId || busy}
          placeholder="Ask about hours, or book a visit…"
          onChange={(e) => setDraft(e.target.value)}
        />
        <Button type="submit" size="icon" disabled={!draft.trim() || busy}>
          <Send className="size-4" />
        </Button>
        {AGENT_ID && (
          <Button type="button" variant="outline" size="icon" title="Talk to Maya" asChild>
            <a href="#voice">
              <Mic className="size-4" />
            </a>
          </Button>
        )}
      </form>

      {AGENT_ID && sessionId && (
        // ElevenLabs web component; it connects to the same agent, which calls our
        // OpenAI-compatible endpoint for every turn.
        <div id="voice" className="border-t px-3 py-2">
          {/* @ts-expect-error custom element provided by the ElevenLabs widget script */}
          <elevenlabs-convai
            id="voice-widget"
            agent-id={AGENT_ID}
            user-id={sessionId}
            dynamic-variables={JSON.stringify({ session_id: sessionId })}
          />
        </div>
      )}
    </div>
  );
}
