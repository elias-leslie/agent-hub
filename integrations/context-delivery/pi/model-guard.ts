/**
 * Keeps a Pi session on the models Agent Hub's launch rules allow for its work role and project.
 *
 * Pi shares one login file, so without this a session whose role is denied Claude (the deny rows of
 * `st models route`) could still switch to it with /model. A denied pick goes back to the previous
 * model, and a provider request on a denied model is aborted before it is sent. Tether sets the
 * session's work role (ST_WORK_ROLE) and project (AICO_PROJECT_ID); without a work role there is
 * nothing to check. Normal sessions load this from ~/.pi/agent/extensions; Blank Slate passes it with -e.
 */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

// The same launch-defaults answer `st aico create` and the remote host shim obey.
const LAUNCH_RULES_URL = `${(process.env.AGENT_HUB_URL || "http://127.0.0.1:8003").replace(/\/+$/, "")}/api/models/launch-defaults`;
const LOOKUP_TIMEOUT_MS = 10_000;
// A provider request waits on this lookup, so it gets a short one.
const REQUEST_LOOKUP_TIMEOUT_MS = 2_000;
const VERDICT_TTL_MS = 5 * 60_000;
const FAILED_LOOKUP_PAUSE_MS = 60_000;
// Pi's provider for Claude logins. A model on it is asked about as the claude-code tool, which the
// launch rules always count as Claude (the host shim does the same), so a new Claude id can't slip past.
const CLAUDE_PROVIDER = "anthropic";

type Verdict =
	| { kind: "allowed" }
	| { kind: "denied"; reason: string }
	// A 4xx: the launch table doesn't know this work role or model.
	| { kind: "unknown" };

type Subject = { key: string; provider?: string };

async function lookup(role: string, project: string | undefined, subject: Subject, timeoutMs: number): Promise<Verdict | undefined> {
	const claude = subject.provider === CLAUDE_PROVIDER;
	const query = new URLSearchParams({
		role,
		tool: claude ? "claude-code" : "pi",
		...(claude ? {} : { model: subject.key }),
		...(project ? { project } : {}),
	});
	try {
		const response = await fetch(`${LAUNCH_RULES_URL}?${query}`, {
			headers: { Accept: "application/json" },
			signal: AbortSignal.timeout(timeoutMs),
		});
		if (response.status >= 400 && response.status < 500) return { kind: "unknown" };
		if (!response.ok) return undefined;
		const data = (await response.json()) as { rows?: unknown };
		const row = Array.isArray(data.rows) && data.rows.length === 1 ? (data.rows[0] as Record<string, unknown>) : undefined;
		if (typeof row?.allowed !== "boolean") return undefined;
		if (row.allowed) return { kind: "allowed" };
		const reason = String(row.deny_reason || "Agent Hub's launch rules deny it").split(/\s+/).join(" ").slice(0, 300);
		return { kind: "denied", reason };
	} catch {
		return undefined;
	}
}

function sessionSubject(model: { provider: string; id: string }): Subject {
	return { key: `${model.provider}/${model.id}`, provider: model.provider };
}

/** The model a serialized provider request names, when the payload carries one. */
function wireModel(payload: unknown): string | undefined {
	if (!payload || typeof payload !== "object") return undefined;
	const fields = payload as { model?: unknown; modelId?: unknown };
	const value = typeof fields.model === "string" ? fields.model : fields.modelId;
	return typeof value === "string" && value ? value : undefined;
}

function say(ctx: ExtensionContext, message: string, level: "warning" | "error"): void {
	if (ctx.hasUI) ctx.ui.notify(message, level);
	else process.stderr.write(`${message}\n`);
}

export default function modelGuard(pi: ExtensionAPI): void {
	const role = process.env.ST_WORK_ROLE?.trim();
	if (!role) return;
	const project = process.env.AICO_PROJECT_ID?.trim() || undefined;
	const verdicts = new Map<string, { verdict: Verdict; at: number }>();
	const toldUnknown = new Set<string>();
	let lookupsPausedUntil = 0;
	let toldUnreadable = false;
	let toldNoWireModel = false;

	/** Why this model may not run here, or undefined. Unreadable rules keep the session's choice. */
	const denial = async (subject: Subject, ctx: ExtensionContext, timeoutMs: number): Promise<string | undefined> => {
		const cached = verdicts.get(subject.key);
		let verdict = cached && Date.now() - cached.at < VERDICT_TTL_MS ? cached.verdict : undefined;
		if (!verdict) {
			if (Date.now() < lookupsPausedUntil) return undefined;
			verdict = await lookup(role, project, subject, timeoutMs);
			if (!verdict) {
				lookupsPausedUntil = Date.now() + FAILED_LOOKUP_PAUSE_MS;
				if (!toldUnreadable) {
					toldUnreadable = true;
					say(ctx, `Agent Hub's launch rules could not be read, so models are not checked against ${role} work's deny rows until they can be.`, "warning");
				}
				return undefined;
			}
			verdicts.set(subject.key, { verdict, at: Date.now() });
		}
		if (verdict.kind === "allowed") return undefined;
		if (verdict.kind === "denied") return `${subject.key} is not allowed for ${role} work: ${verdict.reason}`;
		const claude = subject.provider === CLAUDE_PROVIDER;
		if (!toldUnknown.has(subject.key)) {
			toldUnknown.add(subject.key);
			say(ctx, `${role}/${subject.key} is not known to the launch table; ${claude ? "Claude is refused without it" : "allowing it"}.`, "warning");
		}
		return claude ? `${subject.key} is not allowed for ${role} work: the launch table does not know this work role` : undefined;
	};

	pi.on("session_start", async (_event, ctx) => {
		if (!ctx.model) return;
		const refused = await denial(sessionSubject(ctx.model), ctx, LOOKUP_TIMEOUT_MS);
		if (refused) say(ctx, `${refused}. Its requests are blocked; pick another model with /model.`, "error");
	});

	pi.on("model_select", async (event, ctx) => {
		const refused = await denial(sessionSubject(event.model), ctx, LOOKUP_TIMEOUT_MS);
		if (!refused) return;
		const previous = event.previousModel;
		let restored = false;
		if (previous && !(await denial(sessionSubject(previous), ctx, LOOKUP_TIMEOUT_MS))) {
			try {
				restored = await pi.setModel(previous);
			} catch {
				restored = false;
			}
		}
		const message = restored && previous
			? `${refused}. Staying on ${sessionSubject(previous).key}.`
			: `${refused}. Its requests are blocked; pick another model with /model.`;
		// Pi prints its own "Model: ..." line after this handler; say the refusal after it.
		setTimeout(() => {
			try {
				say(ctx, message, "error");
			} catch {
				process.stderr.write(`${message}\n`);
			}
		}, 0);
	});

	// Backstop. A throw here is only reported, so a denied request is stopped by aborting the run.
	pi.on("before_provider_request", async (event, ctx) => {
		const subjects: Subject[] = ctx.model ? [sessionSubject(ctx.model)] : [];
		const wire = wireModel(event.payload);
		if (wire === undefined) {
			if (!toldNoWireModel && ctx.model) {
				toldNoWireModel = true;
				say(ctx, `This provider's requests don't name their model, so they are checked as the session model ${sessionSubject(ctx.model).key}.`, "warning");
			}
		} else if (wire !== ctx.model?.id && wire !== subjects[0]?.key) {
			subjects.push({ key: wire });
		}
		for (const subject of subjects) {
			const refused = await denial(subject, ctx, REQUEST_LOOKUP_TIMEOUT_MS);
			if (refused) {
				ctx.abort();
				say(ctx, `Request blocked: ${refused}. Pick another model with /model.`, "error");
				return undefined;
			}
		}
		return undefined;
	});
}
