/**
 * Canonical Agent Hub context delivery for Pi.
 *
 * Pi keeps its native system prompt. On every agent start this extension asks
 * the shared Agent Hub client for one versioned delivery contract, then appends
 * the exact rendered payload to Pi's already-built system prompt. The same path
 * runs after resume, fork, and compaction because Pi rebuilds the system prompt
 * for each agent start.
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";

import type { AnyModel, Provider } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const CONTEXT_CLIENT =
	process.env.AGENT_HUB_CONTEXT_CLIENT ?? `${process.env.HOME}/.local/bin/agent-hub-context-client`;
const SCHEMA_VERSION = "agent-hub.context.v1";
const CLIENT_TIMEOUT_MS = Number.parseInt(
	process.env.AGENT_HUB_CONTEXT_ADAPTER_TIMEOUT_MS ?? "20000",
	10,
);

/** Model metadata also reaches compaction and nested native provider calls. */
export function daybreakProvider(provider: Provider, enabled: boolean): Provider {
	const select = <T extends AnyModel>(model: T): T => {
		if (model.type !== "chat" || model.id !== "gpt-6-sol" || model.api !== "openai-responses") {
			return model;
		}
		return {
			...model,
			samplingParams: {
				...model.samplingParams,
				access_programs: { cyber: enabled ? "daybreak_blue" : "standard" },
			},
		};
	};
	return {
		...provider,
		getModels: () => provider.getModels().map(select),
		getAllModels: () => (provider.getAllModels?.() ?? provider.getModels()).map(select),
	};
}

function daybreakSelection(): boolean | undefined {
	const selection = process.env.AICO_ROOT_DAYBREAK;
	if (selection !== "true" && selection !== "false") return undefined;
	if (process.env.AICO_ROOT_MODEL !== "openai/gpt-6-sol") {
		throw new Error("Pi Daybreak requires the explicit model openai/gpt-6-sol");
	}
	return selection === "true";
}

function configureDaybreak(pi: ExtensionAPI, ctx: ExtensionContext, enabled: boolean): void {
	// Use Pi's live provider through its public extension context. The extension
	// source lives outside Pi's package tree, so bare package imports do not resolve.
	const provider = ctx.modelRegistry.getProvider("openai");
	if (!provider) throw new Error("Pi OpenAI provider is unavailable for Daybreak");
	pi.registerProvider(daybreakProvider(provider, enabled));
}

// Agent Hub's launch rules (the deny rows `st aico create` and the host shim obey), asked per model.
const LAUNCH_RULES_URL = `${(process.env.AGENT_HUB_URL || "http://127.0.0.1:8003").replace(/\/+$/, "")}/api/models/launch-defaults`;
const LAUNCH_RULES_TIMEOUT_MS = 10_000;

type LaunchVerdict = { allowed: true } | { allowed: false; reason: string };

/** Agent Hub's answer for running `model` through Pi in this work role and project, or undefined
 * when the rules can't be read. */
async function launchVerdict(role: string, project: string | undefined, model: string): Promise<LaunchVerdict | undefined> {
	const query = new URLSearchParams({ role, tool: "pi", model, ...(project ? { project } : {}) });
	try {
		const response = await fetch(`${LAUNCH_RULES_URL}?${query}`, {
			headers: { Accept: "application/json" },
			signal: AbortSignal.timeout(LAUNCH_RULES_TIMEOUT_MS),
		});
		if (!response.ok) return undefined;
		const data = (await response.json()) as { rows?: unknown };
		const row = Array.isArray(data.rows) && data.rows.length === 1 ? (data.rows[0] as Record<string, unknown>) : undefined;
		if (typeof row?.allowed !== "boolean") return undefined;
		if (row.allowed) return { allowed: true };
		const reason = String(row.deny_reason || "Agent Hub's launch rules deny it").split(/\s+/).join(" ").slice(0, 300);
		return { allowed: false, reason };
	} catch {
		return undefined;
	}
}

function modelKey(model: { provider: string; id: string }): string {
	return `${model.provider}/${model.id}`;
}

function say(ctx: ExtensionContext, message: string, level: "warning" | "error"): void {
	if (ctx.hasUI) ctx.ui.notify(message, level);
	else process.stderr.write(`${message}\n`);
}

/** Keeps a session on models its work role and project may use: refuses a denied /model pick and
 * aborts any provider request on a denied model. Pi shares one login file, so without this a session
 * whose role is denied Claude could still switch to it. Without a work role there is nothing to check;
 * when the rules can't be read the session keeps its choice and is told once. */
function installModelGuard(pi: ExtensionAPI): void {
	const role = process.env.ST_WORK_ROLE?.trim();
	if (!role) return;
	const project = process.env.AICO_PROJECT_ID?.trim() || undefined;
	const verdicts = new Map<string, LaunchVerdict>();
	let unreadableSaid = false;

	const denial = async (model: string, ctx: ExtensionContext): Promise<string | undefined> => {
		let verdict = verdicts.get(model);
		if (!verdict) {
			verdict = await launchVerdict(role, project, model);
			if (!verdict) {
				if (!unreadableSaid) {
					unreadableSaid = true;
					say(ctx, `Agent Hub's launch rules could not be read, so models are not checked against ${role} work's deny rows in this session.`, "warning");
				}
				return undefined;
			}
			verdicts.set(model, verdict);
		}
		return verdict.allowed ? undefined : `${model} is not allowed for ${role} work: ${verdict.reason}`;
	};

	pi.on("session_start", async (_event, ctx) => {
		if (!ctx.model) return;
		const refused = await denial(modelKey(ctx.model), ctx);
		if (refused) say(ctx, `${refused}. Its requests are blocked; pick another model with /model.`, "error");
	});

	pi.on("model_select", async (event, ctx) => {
		const refused = await denial(modelKey(event.model), ctx);
		if (!refused) return;
		const previous = event.previousModel;
		let restored = false;
		if (previous && !(await denial(modelKey(previous), ctx))) {
			try {
				restored = await pi.setModel(previous);
			} catch {
				restored = false;
			}
		}
		// Pi prints its own "Model: ..." line after this handler; say the refusal after it.
		const message = restored && previous
			? `${refused}. Staying on ${modelKey(previous)}.`
			: `${refused}. Its requests are blocked; pick another model with /model.`;
		setTimeout(() => say(ctx, message, "error"), 0);
	});

	// Backstop: a throw here is only reported, so a denied request is stopped by aborting the run.
	pi.on("before_provider_request", async (event, ctx) => {
		const models = ctx.model ? [modelKey(ctx.model)] : [];
		const wire = (event.payload as { model?: unknown } | null)?.model;
		if (typeof wire === "string" && wire !== ctx.model?.id) models.push(wire);
		for (const model of models) {
			const refused = await denial(model, ctx);
			if (refused) {
				ctx.abort();
				say(ctx, `Request blocked: ${refused}. Pick another model with /model.`, "error");
				return undefined;
			}
		}
		return undefined;
	});
}

type DeliveryContract = {
	schema_version: string;
	status: "ok" | "failed";
	delivery_mode: "additive";
	recommended_role: "developer";
	native_context_policy: "preserve";
	payload_hash: string;
	rendered: string;
	estimated_tokens: number;
	metadata: { project_id?: string | null };
};

type CommandResult = { code: number; stdout: string; stderr: string };

function runClient(args: string[]): Promise<CommandResult> {
	return new Promise((resolve, reject) => {
		if (!Number.isFinite(CLIENT_TIMEOUT_MS) || CLIENT_TIMEOUT_MS <= 0) {
			reject(new Error("AGENT_HUB_CONTEXT_ADAPTER_TIMEOUT_MS must be a positive integer"));
			return;
		}
		const child = spawn(CONTEXT_CLIENT, args, {
			detached: true,
			stdio: ["ignore", "pipe", "pipe"],
		});
		const stdout: Buffer[] = [];
		const stderr: Buffer[] = [];
		let settled = false;
		const finish = (callback: () => void) => {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			callback();
		};
		const timer = setTimeout(() => {
			if (child.pid) {
				try {
					process.kill(-child.pid, "SIGKILL");
				} catch {
					child.kill("SIGKILL");
				}
			}
			finish(() => reject(new Error(`context client exceeded ${CLIENT_TIMEOUT_MS}ms`)));
		}, CLIENT_TIMEOUT_MS);
		child.stdout.on("data", (chunk: Buffer) => stdout.push(chunk));
		child.stderr.on("data", (chunk: Buffer) => stderr.push(chunk));
		child.on("error", (error) => finish(() => reject(error)));
		child.on("close", (code) => {
			finish(() =>
				resolve({
					code: code ?? 1,
					stdout: Buffer.concat(stdout).toString("utf8"),
					stderr: Buffer.concat(stderr).toString("utf8"),
				}),
			);
		});
	});
}

function sessionId(ctx: ExtensionContext): string {
	return ctx.sessionManager.getSessionId();
}

function validateContract(value: unknown): DeliveryContract {
	if (!value || typeof value !== "object") throw new Error("delivery is not an object");
	const contract = value as Partial<DeliveryContract>;
	if (contract.schema_version !== SCHEMA_VERSION) throw new Error("unexpected schema version");
	if (contract.status !== "ok" && contract.status !== "failed") throw new Error("invalid status");
	if (contract.delivery_mode !== "additive") throw new Error("delivery is not additive");
	if (contract.native_context_policy !== "preserve") throw new Error("native context is not preserved");
	if (typeof contract.rendered !== "string" || !contract.rendered.trim()) {
		throw new Error("rendered context is empty");
	}
	return contract as DeliveryContract;
}

function degradedWarning(error: unknown): string {
	const message = error instanceof Error ? error.message : String(error);
	return `Agent Hub supplemental context is unavailable; Pi is continuing with native context only. PiAdapterError: ${message}`;
}

function reportDegraded(ctx: ExtensionContext, warning: string): void {
	if (ctx.hasUI) {
		ctx.ui.setStatus("agent-hub", "AH: DEGRADED");
		ctx.ui.notify(warning, "warning");
	} else {
		process.stderr.write(`${warning}\n`);
	}
}

async function deliver(
	ctx: ExtensionContext,
	prompt: string,
	currentSessionId: string,
	hasShell: boolean,
): Promise<DeliveryContract> {
	const args = [
		"deliver",
		"--surface",
		"pi",
		"--cwd",
		ctx.cwd,
		"--session",
		process.env.AICO_SESSION_ID ?? currentSessionId,
		"--query",
		prompt,
		"--phase",
		"before_agent_start",
		"--emit",
		"json",
	];
	if (hasShell) args.push("--capability", "bash");
	if (ctx.model?.provider) args.push("--provider", ctx.model.provider);
	if (ctx.model?.id) args.push("--model", ctx.model.id);
	if (process.env.SUMMITFLOW_TASK_ID) args.push("--task", process.env.SUMMITFLOW_TASK_ID);
	if (process.env.AICO_ROOT_AGENT_HUB_CONTEXT === "false") args.push("--optional-context", "off");

	const result = await runClient(args);
	if (result.stderr) process.stderr.write(result.stderr);
	if (result.code !== 0 && result.code !== 2) {
		throw new Error(`context client exited ${result.code}`);
	}
	let parsed: unknown;
	try {
		parsed = JSON.parse(result.stdout);
	} catch {
		throw new Error("context client returned invalid JSON");
	}
	const contract = validateContract(parsed);
	const expectedCode = contract.status === "ok" ? 0 : 2;
	if (result.code !== expectedCode) throw new Error("context client status/exit mismatch");
	return contract;
}

export default async function agentHubContext(pi: ExtensionAPI) {
	const daybreakEnabled = daybreakSelection();
	let daybreakConfigured = false;
	let currentSessionId = "";
	let lastHash = "";
	let lastStatus: "idle" | "ok" | "failed" = "idle";
	let pendingContract: DeliveryContract | undefined;
	let pendingFailure: string | undefined;
	installModelGuard(pi);

	const sync = async (ctx: ExtensionContext, phase: string) => {
		const file = ctx.sessionManager.getSessionFile();
		// Pi can advertise a transcript path before its first event creates the file.
		if (!file || !ctx.model || !existsSync(file)) return;
		const args = ["sync-pi", "--surface", "pi", "--cwd", ctx.cwd,
			"--session", sessionId(ctx), "--transcript", file,
			"--provider", ctx.model.provider, "--model", ctx.model.id, "--phase", phase];
		if (process.env.AICO_PROJECT_ID) args.push("--project", process.env.AICO_PROJECT_ID);
		if (process.env.AICO_SESSION_ID) args.push("--aico-session", process.env.AICO_SESSION_ID);
		try {
			const result = await runClient(args);
			if (result.code !== 0) throw new Error("sync failed");
			if (ctx.hasUI) ctx.ui.setStatus("agent-hub-sync", undefined);
		} catch {
			// Failed ingestion never consumes input or changes provider selection.
			if (ctx.hasUI) ctx.ui.setStatus("agent-hub-sync", "AH: sync unavailable");
			else process.stderr.write("Pi session sync unavailable\n");
		}
	};

	pi.on("session_start", async (_event, ctx) => {
		if (daybreakEnabled !== undefined && !daybreakConfigured) {
			configureDaybreak(pi, ctx, daybreakEnabled);
			daybreakConfigured = true;
		}
		currentSessionId = sessionId(ctx);
		process.env.PI_SESSION_ID = currentSessionId;
		lastHash = "";
		lastStatus = "idle";
		pendingContract = undefined;
		pendingFailure = undefined;
		if (ctx.hasUI) ctx.ui.setStatus("agent-hub", "AH: ready");
		await sync(ctx, "idle");
	});

	pi.on("agent_start", async (_event, ctx) => { await sync(ctx, "working"); });
	// Pi persists the assistant and tool results before turn_end. Fresh sessions
	// may have no transcript at agent_start; long runs must not wait until idle.
	pi.on("turn_end", async (_event, ctx) => { await sync(ctx, "working"); });
	// agent_end can precede automatic retries, recovery, or queued work.
	pi.on("agent_settled", async (_event, ctx) => { await sync(ctx, "idle"); });

	pi.on("input", async (event, ctx) => {
		// Steering/follow-up input belongs to an agent turn whose exact canonical
		// prompt was already assembled. A new idle prompt gets a best-effort
		// preflight; delivery failure never consumes or blocks the native prompt.
		if (event.streamingBehavior) return { action: "continue" };
		currentSessionId ||= sessionId(ctx);
		pendingContract = undefined;
		pendingFailure = undefined;
		try {
			const contract = await deliver(
				ctx, event.text, currentSessionId, pi.getActiveTools().includes("bash"),
			);
			lastHash = contract.payload_hash;
			lastStatus = contract.status === "ok" ? "ok" : "failed";
			if (contract.status === "failed") {
				pendingFailure = degradedWarning("canonical delivery reported failed status");
				reportDegraded(ctx, pendingFailure);
				return { action: "continue" };
			}
			pendingContract = contract;
			return { action: "continue" };
		} catch (error) {
			lastStatus = "failed";
			pendingFailure = degradedWarning(error);
			reportDegraded(ctx, pendingFailure);
			return { action: "continue" };
		}
	});

	pi.on("before_agent_start", async (event, ctx) => {
		currentSessionId ||= sessionId(ctx);
		if (pendingFailure) {
			pendingFailure = undefined;
			return { systemPrompt: event.systemPrompt };
		}
		try {
			const contract =
				pendingContract ?? (await deliver(
					ctx, "prompt" in event ? event.prompt : "startup context", currentSessionId, pi.getActiveTools().includes("bash"),
				));
			pendingContract = undefined;
			lastHash = contract.payload_hash;
			lastStatus = contract.status === "ok" ? "ok" : "failed";
			if (contract.status === "failed") {
				reportDegraded(ctx, degradedWarning("canonical delivery reported failed status"));
				return { systemPrompt: event.systemPrompt };
			}
			if (ctx.hasUI) {
				ctx.ui.setStatus("agent-hub", `AH: ${contract.payload_hash.slice(0, 8)}`);
			}
			return { systemPrompt: `${event.systemPrompt}\n\n${contract.rendered}` };
		} catch (error) {
			lastStatus = "failed";
			reportDegraded(ctx, degradedWarning(error));
			return { systemPrompt: event.systemPrompt };
		}
	});

	pi.on("session_shutdown", async (_event, ctx) => {
		await sync(ctx, "shutdown");
		if (ctx.hasUI) ctx.ui.setStatus("agent-hub", undefined);
	});

	pi.registerCommand("ah-status", {
		description: "Show canonical Agent Hub context delivery status.",
		handler: async (_args, ctx) => {
			ctx.ui.notify(
				`session: ${currentSessionId || "(none)"}\nstatus: ${lastStatus}\npayload: ${lastHash || "(none)"}`,
				"info",
			);
		},
	});
}
