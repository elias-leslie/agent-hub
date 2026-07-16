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
import { randomUUID } from "node:crypto";
import { basename } from "node:path";

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const CONTEXT_CLIENT =
	process.env.AGENT_HUB_CONTEXT_CLIENT ?? `${process.env.HOME}/.local/bin/agent-hub-context-client`;
const SCHEMA_VERSION = "agent-hub.context.v1";
const CLIENT_TIMEOUT_MS = Number.parseInt(
	process.env.AGENT_HUB_CONTEXT_ADAPTER_TIMEOUT_MS ?? "20000",
	10,
);

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
	const file = ctx.sessionManager.getSessionFile();
	if (!file) return randomUUID();
	const stem = basename(file).replace(/\.jsonl$/, "");
	const uuid = stem.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
	return uuid?.[0] ?? stem;
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

async function deliver(ctx: ExtensionContext, prompt: string, currentSessionId: string): Promise<DeliveryContract> {
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
	if (ctx.model?.provider) args.push("--provider", ctx.model.provider);
	if (ctx.model?.id) args.push("--model", ctx.model.id);
	if (process.env.SUMMITFLOW_TASK_ID) args.push("--task", process.env.SUMMITFLOW_TASK_ID);

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

export default function agentHubContext(pi: ExtensionAPI) {
	let currentSessionId = "";
	let lastHash = "";
	let lastStatus: "idle" | "ok" | "failed" = "idle";
	let pendingContract: DeliveryContract | undefined;
	let pendingFailure: string | undefined;

	pi.on("session_start", async (_event, ctx) => {
		currentSessionId = sessionId(ctx);
		lastHash = "";
		lastStatus = "idle";
		pendingContract = undefined;
		pendingFailure = undefined;
		if (ctx.hasUI) ctx.ui.setStatus("agent-hub", "AH: ready");
	});

	pi.on("input", async (event, ctx) => {
		// Steering/follow-up input belongs to an agent turn whose exact canonical
		// prompt was already assembled. A new idle prompt gets a best-effort
		// preflight; delivery failure never consumes or blocks the native prompt.
		if (event.streamingBehavior) return { action: "continue" };
		currentSessionId ||= sessionId(ctx);
		pendingContract = undefined;
		pendingFailure = undefined;
		try {
			const contract = await deliver(ctx, event.text, currentSessionId);
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
				pendingContract ?? (await deliver(ctx, event.prompt, currentSessionId));
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
