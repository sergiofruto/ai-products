import IntakeDemo from "./intake-demo";

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6">
      <header className="max-w-3xl">
        <p className="text-sm font-medium text-accent">ElevenAgents demo · Sergio Fruto</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
          Voice intake for a physical therapy clinic
        </h1>
        <p className="mt-3 text-muted">
          A bilingual voice agent collects the patient&apos;s details and books a first evaluation.
          The agent handles the conversation; a Python clinic API checks every field and owns the
          schedule. The right panel shows each tool call as it happens.
        </p>
      </header>

      <div className="mt-8">
        <IntakeDemo />
      </div>

      <footer className="mt-10 grid gap-4 text-sm text-muted sm:grid-cols-3">
        <p>
          <span className="font-medium text-foreground">The model talks, code decides.</span> Slots,
          validation and confirmation codes only come from the clinic API.
        </p>
        <p>
          <span className="font-medium text-foreground">Errors are part of the flow.</span> A
          rejected booking returns every problem at once, and the agent fixes it with the patient.
        </p>
        <p>
          Demo data only: fictional clinic, no real patient data stored.{" "}
          <a className="underline" href="https://github.com/sergiofruto/agents-ops">
            Source on GitHub
          </a>
        </p>
      </footer>
    </main>
  );
}
