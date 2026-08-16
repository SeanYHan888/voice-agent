import { Link } from "react-router-dom";
import {
  ArrowRight,
  BadgeCheck,
  CalendarCheck,
  ClipboardList,
  Code,
  Headset,
  LockKeyhole,
  MessageCircleQuestion,
  Mic,
  ServerCog,
  Sparkles,
  Stethoscope,
  UserRound,
  UsersRound,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

const REPO_URL = "https://github.com/SeanYHan888/voice-agent";

/** A short, illustrative exchange — the shape of a real Call, not a recording of one. */
const SAMPLE_CALL: { who: "maya" | "caller"; text: string; note?: string }[] = [
  { who: "maya", text: "Thanks for calling Assort Dermatology, this is Maya. How can I help you today?" },
  { who: "caller", text: "Hi, I'd like to move my follow-up to next week." },
  {
    who: "maya",
    text: "Happy to help. First I need to confirm who I'm speaking with — what's the phone number and date of birth on your record?",
  },
  { who: "caller", text: "555-010-0104, January 9th, 1996." },
  {
    who: "maya",
    text: "Thanks, Emma — I've sent a one-time code to that number. Read it back to me when you have it.",
    note: "Verification",
  },
  { who: "caller", text: "It's 482913." },
  {
    who: "maya",
    text: "You're verified. Dr. Chen has Tuesday at 10:15 or Thursday at 2:30 next week. Which works better?",
    note: "find_slots",
  },
  { who: "caller", text: "Tuesday please." },
  {
    who: "maya",
    text: "Done — your follow-up is now Tuesday at 10:15 with Dr. Chen. Anything else I can help with?",
    note: "reschedule_appointment",
  },
];

const CAPABILITIES = [
  {
    icon: CalendarCheck,
    title: "Schedules visits",
    body: "Finds open slots across four providers, books new-patient and follow-up visits, and reschedules or cancels — after the caller proves who they are.",
  },
  {
    icon: MessageCircleQuestion,
    title: "Answers clinic questions",
    body: "Hours, parking, what to bring, skin-check prep, biopsy aftercare, insurance — grounded in the clinic's own FAQ, not the model's guesses.",
  },
  {
    icon: Headset,
    title: "Knows when to stop",
    body: "Medical advice, emergencies, angry callers, and anything outside the clinic's rules go to a human. Maya says so plainly rather than improvising.",
  },
];

const STEPS = [
  {
    icon: Mic,
    title: "Maya answers",
    body: "By voice or by text in the portal — the same conversation either way, and the same one a phone line would reach.",
  },
  {
    icon: BadgeCheck,
    title: "The caller is verified",
    body: "Phone number and date of birth on file, then a one-time code. Nothing personal is shared before this.",
  },
  {
    icon: ServerCog,
    title: "Tools do the work",
    body: "Booking, cancelling, and lookups run against the clinic system, which enforces the rules regardless of what was said.",
  },
  {
    icon: ClipboardList,
    title: "The call is summarised",
    body: "Intent, sentiment, and a short digest land in the patient's record and the staff dashboard.",
  },
];

const PRINCIPLES = [
  {
    icon: LockKeyhole,
    title: "Identity is never the model's call",
    body: "Maya's tools don't take a patient id. It lives in the call session, set only by completing verification. However persuasive a caller is, another patient's records stay out of reach.",
  },
  {
    icon: ServerCog,
    title: "Rules live on the server, not in the prompt",
    body: "Cancelling within 24 hours of a visit doesn't execute — it becomes an approval task for staff, and Maya is told to say so. The tool is the authority; the prompt just relays it.",
  },
  {
    icon: Sparkles,
    title: "Every turn is guarded and traced",
    body: "Input and output guardrails wrap each response, and every call is checkpointed and traced end to end so staff can see exactly what happened.",
  },
];

function Bubble({ who, text, note }: (typeof SAMPLE_CALL)[number]) {
  const isMaya = who === "maya";
  return (
    <div className={cn("flex flex-col gap-1", isMaya ? "items-start" : "items-end")}>
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed",
          isMaya ? "rounded-tl-sm bg-muted text-foreground" : "rounded-tr-sm bg-primary text-primary-foreground",
        )}
      >
        {text}
      </div>
      {note && (
        <Badge variant="outline" className="text-[10px] text-muted-foreground">
          {note}
        </Badge>
      )}
    </div>
  );
}

export function Landing() {
  const { isAuthenticated, role } = useAuth();
  const appHome = role === "admin" ? "/admin" : "/portal";

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-10 border-b bg-white/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-3">
          <Link to="/" className="flex shrink-0 items-center gap-2">
            <Stethoscope className="size-5 text-primary" />
            <span className="font-semibold tracking-tight whitespace-nowrap">Assort Dermatology</span>
          </Link>
          <nav className="hidden items-center gap-1 text-sm lg:flex">
            {[
              ["#what", "What Maya does"],
              ["#how", "How a call works"],
              ["#who", "Patients & staff"],
              ["#why", "Safety by design"],
            ].map(([href, label]) => (
              <a
                key={href}
                href={href}
                className="rounded-md px-3 py-1.5 whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground"
              >
                {label}
              </a>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            {isAuthenticated ? (
              <Button asChild size="sm">
                <Link to={appHome}>
                  Open {role === "admin" ? "dashboard" : "portal"} <ArrowRight />
                </Link>
              </Button>
            ) : (
              <>
                <Button asChild variant="ghost" size="sm">
                  <Link to="/login">Sign in</Link>
                </Button>
                <Button asChild size="sm">
                  <Link to="/register">Create account</Link>
                </Button>
              </>
            )}
          </div>
        </div>
      </header>

      <main>
        {/* Hero */}
        <section className="mx-auto grid max-w-6xl items-center gap-12 px-6 py-16 md:py-24 lg:grid-cols-2">
          <div className="space-y-6">
            <Badge variant="secondary" className="gap-1.5">
              <Sparkles className="size-3" /> AI patient access agent
            </Badge>
            <h1 className="text-4xl font-semibold tracking-tight text-balance md:text-5xl">
              Meet Maya, the voice that answers our phone line.
            </h1>
            <p className="max-w-prose text-lg text-muted-foreground">
              Maya schedules appointments, answers questions about the clinic, and hands the
              conversation to a person the moment it should. Available around the clock — talk
              to her by voice or text, right here in your browser.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              {isAuthenticated ? (
                <Button asChild size="lg">
                  <Link to={appHome}>
                    Continue to {role === "admin" ? "the dashboard" : "your portal"} <ArrowRight />
                  </Link>
                </Button>
              ) : (
                <>
                  <Button asChild size="lg">
                    <Link to="/register">
                      Talk to Maya <ArrowRight />
                    </Link>
                  </Button>
                  <Button asChild size="lg" variant="outline">
                    <Link to="/login">I already have an account</Link>
                  </Button>
                </>
              )}
            </div>
            {!isAuthenticated && (
              <p className="text-sm text-muted-foreground">
                Demo clinic, fictional patients. After signing up, link the sample record{" "}
                <span className="font-medium text-foreground">555-010-0104 · 1996-01-09</span> to
                try a full call.
              </p>
            )}
          </div>

          <Card className="gap-4 pt-4 shadow-lg">
            <CardHeader className="border-b [.border-b]:pb-4">
              <CardTitle className="flex items-center gap-2 text-base">
                <span className="relative flex size-2.5">
                  <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-60" />
                  <span className="relative inline-flex size-2.5 rounded-full bg-success" />
                </span>
                Live call · browser
              </CardTitle>
              <CardDescription>What a typical conversation with Maya looks like.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {SAMPLE_CALL.map((turn, i) => (
                <Bubble key={i} {...turn} />
              ))}
            </CardContent>
          </Card>
        </section>

        {/* What Maya does */}
        <section id="what" className="border-y bg-white">
          <div className="mx-auto max-w-6xl px-6 py-16">
            <SectionHeading
              eyebrow="What Maya does"
              title="The front desk, minus the hold music"
              body="Three jobs, done carefully. Everything else gets a person."
            />
            <div className="mt-10 grid gap-6 md:grid-cols-3">
              {CAPABILITIES.map(({ icon: Icon, title, body }) => (
                <Card key={title}>
                  <CardHeader>
                    <div className="mb-2 flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                      <Icon className="size-5" />
                    </div>
                    <CardTitle className="text-base">{title}</CardTitle>
                    <CardDescription className="leading-relaxed">{body}</CardDescription>
                  </CardHeader>
                </Card>
              ))}
            </div>
          </div>
        </section>

        {/* How a call works */}
        <section id="how" className="mx-auto max-w-6xl px-6 py-16">
          <SectionHeading
            eyebrow="How a call works"
            title="From hello to a written summary"
            body="Every conversation follows the same four beats, whether it started on a phone or in the portal."
          />
          <ol className="mt-10 grid gap-8 md:grid-cols-4">
            {STEPS.map(({ icon: Icon, title, body }, i) => (
              <li key={title} className="relative space-y-3">
                <div className="flex items-center gap-3">
                  <span className="flex size-9 items-center justify-center rounded-full border bg-white text-sm font-semibold text-primary">
                    {i + 1}
                  </span>
                  <Icon className="size-5 text-muted-foreground" />
                </div>
                <h3 className="font-medium">{title}</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">{body}</p>
              </li>
            ))}
          </ol>
        </section>

        {/* Patients & staff */}
        <section id="who" className="border-y bg-white">
          <div className="mx-auto max-w-6xl px-6 py-16">
            <SectionHeading
              eyebrow="Patients & staff"
              title="One agent, two front doors"
              body="Patients get a portal that keeps Maya a click away. Staff get the controls and the visibility."
            />
            <div className="mt-10 grid gap-6 md:grid-cols-2">
              <AudienceCard
                icon={UserRound}
                title="For patients"
                items={[
                  "See upcoming and past visits at a glance",
                  "Talk to Maya by text or voice without leaving the page",
                  "Review call summaries and leave a rating",
                  "Link your clinic record once; verification is quick after that",
                ]}
                cta={isAuthenticated && role === "patient" ? { to: "/portal", label: "Open my portal" } : { to: "/register", label: "Create a patient account" }}
              />
              <AudienceCard
                icon={UsersRound}
                title="For staff"
                items={[
                  "A queue of escalations and approvals that need a human decision",
                  "Every call's summary, intent, and sentiment in one place",
                  "Ask questions about operations in plain English and get real numbers back",
                  "An SMS inbox for messages Maya couldn't handle on the call",
                ]}
                cta={isAuthenticated && role === "admin" ? { to: "/admin", label: "Open the dashboard" } : { to: "/login", label: "Staff sign in" }}
              />
            </div>
          </div>
        </section>

        {/* Safety by design */}
        <section id="why" className="mx-auto max-w-6xl px-6 py-16">
          <SectionHeading
            eyebrow="Safety by design"
            title="Built so a clever caller can't talk their way past the rules"
            body="A few decisions shape everything else in the system."
          />
          <div className="mt-10 grid gap-6 md:grid-cols-3">
            {PRINCIPLES.map(({ icon: Icon, title, body }) => (
              <div key={title} className="space-y-3">
                <Icon className="size-5 text-primary" />
                <h3 className="font-medium">{title}</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">{body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Final CTA */}
        {!isAuthenticated && (
          <section className="border-t bg-white">
            <div className="mx-auto flex max-w-6xl flex-col items-start gap-6 px-6 py-16 md:flex-row md:items-center md:justify-between">
              <div>
                <h2 className="text-2xl font-semibold tracking-tight">Ready to talk to Maya?</h2>
                <p className="mt-1 text-muted-foreground">
                  Create an account, link the sample record, and book a visit in under a minute.
                </p>
              </div>
              <div className="flex gap-3">
                <Button asChild size="lg">
                  <Link to="/register">
                    Get started <ArrowRight />
                  </Link>
                </Button>
                <Button asChild size="lg" variant="outline">
                  <Link to="/login">Sign in</Link>
                </Button>
              </div>
            </div>
          </section>
        )}
      </main>

      <footer className="border-t">
        <div className="mx-auto flex max-w-6xl flex-col gap-3 px-6 py-8 text-sm text-muted-foreground md:flex-row md:items-center md:justify-between">
          <p>
            A demonstration clinic with no real patient data. Modeled on Assort Health's
            patient-access product and built as a GenAI course project.
          </p>
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap hover:text-foreground"
          >
            <Code className="size-4" /> Source on GitHub
          </a>
        </div>
      </footer>
    </div>
  );
}

function SectionHeading({ eyebrow, title, body }: { eyebrow: string; title: string; body: string }) {
  return (
    <div className="max-w-2xl space-y-3">
      <p className="text-sm font-medium uppercase tracking-wide text-primary">{eyebrow}</p>
      <h2 className="text-3xl font-semibold tracking-tight text-balance">{title}</h2>
      <p className="text-muted-foreground">{body}</p>
    </div>
  );
}

function AudienceCard({
  icon: Icon,
  title,
  items,
  cta,
}: {
  icon: typeof UserRound;
  title: string;
  items: string[];
  cta: { to: string; label: string };
}) {
  return (
    <Card>
      <CardHeader>
        <div className="mb-2 flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
          <Icon className="size-5" />
        </div>
        <CardTitle className="text-lg">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <ul className="space-y-2.5 text-sm text-muted-foreground">
          {items.map((item) => (
            <li key={item} className="flex gap-2.5">
              <BadgeCheck className="mt-0.5 size-4 shrink-0 text-primary" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
        <Button asChild variant="outline">
          <Link to={cta.to}>
            {cta.label} <ArrowRight />
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}
