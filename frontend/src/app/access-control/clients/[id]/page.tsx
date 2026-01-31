"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Shield, ArrowLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import { buildApiUrl, fetchApi } from "@/lib/api-config";
import { ClientDetailsCard } from "./components/ClientDetailsCard";
import { ActionButtons } from "./components/ActionButtons";
import { NewSecretBanner } from "./components/NewSecretBanner";
import { EditClientModal } from "./components/EditClientModal";
import { ConfirmationModal } from "./components/ConfirmationModal";
import { useClientMutations } from "./hooks/useClientMutations";

interface ClientResponse {
  client_id: string;
  display_name: string;
  secret_prefix: string;
  client_type: string;
  status: string;
  rate_limit_rpm: number;
  rate_limit_tpm: number;
  allowed_projects: string[] | null;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
  suspended_at: string | null;
  suspended_by: string | null;
  suspension_reason: string | null;
}

async function fetchClient(clientId: string): Promise<ClientResponse> {
  const response = await fetchApi(buildApiUrl(`/api/access-control/clients/${clientId}`), {
    headers: {
      "X-Agent-Hub-Internal": "agent-hub-internal-v1",
    },
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch client: ${response.statusText}`);
  }
  return response.json();
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "Never";
  return new Date(dateStr).toLocaleString();
}

export default function ClientDetailPage() {
  const params = useParams();
  const router = useRouter();
  const clientId = params.id as string;

  const [showSuspendModal, setShowSuspendModal] = useState(false);
  const [showBlockModal, setShowBlockModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [newSecret, setNewSecret] = useState<string | null>(null);

  const { data: client, isLoading, error } = useQuery({
    queryKey: ["access-control-client", clientId],
    queryFn: () => fetchClient(clientId),
    refetchInterval: 10000,
  });

  const { suspendMutation, activateMutation, blockMutation, rotateSecretMutation, updateMutation } =
    useClientMutations(clientId);

  function handleRotateSecret() {
    rotateSecretMutation.mutate(undefined, {
      onSuccess: (data) => setNewSecret(data.secret),
    });
  }

  function handleSuspend(reason: string) {
    suspendMutation.mutate(reason, {
      onSuccess: () => setShowSuspendModal(false),
    });
  }

  function handleBlock(reason: string) {
    blockMutation.mutate(reason, {
      onSuccess: () => setShowBlockModal(false),
    });
  }

  function handleUpdate(updates: any) {
    updateMutation.mutate(updates, {
      onSuccess: () => setShowEditModal(false),
    });
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="animate-spin h-8 w-8 border-2 border-blue-500 border-t-transparent rounded-full" />
      </div>
    );
  }

  if (error || !client) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-400 mb-4">Failed to load client</p>
          <button
            onClick={() => router.push("/access-control/clients")}
            className="text-blue-400 hover:text-blue-300"
          >
            Back to clients
          </button>
        </div>
      </div>
    );
  }

  const statusConfig = {
    active: { color: "text-emerald-400", bg: "bg-emerald-500/10", label: "Active" },
    suspended: { color: "text-amber-400", bg: "bg-amber-500/10", label: "Suspended" },
    blocked: { color: "text-red-400", bg: "bg-red-500/10", label: "Blocked" },
  };
  const config = statusConfig[client.status as keyof typeof statusConfig] || statusConfig.active;

  return (
    <div className="min-h-screen bg-slate-950">
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />

      <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8 h-12 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => router.push("/access-control/clients")}
              className="p-1 rounded hover:bg-slate-800 transition-colors"
            >
              <ArrowLeft className="h-5 w-5 text-slate-400" />
            </button>
            <Shield className="h-5 w-5 text-slate-400" />
            <h1 className="text-base font-semibold text-slate-100">{client.display_name}</h1>
            <span className={cn("text-xs px-2 py-1 rounded", config.bg, config.color)}>
              {config.label}
            </span>
          </div>
        </div>
      </header>

      <main className="relative max-w-3xl mx-auto px-6 py-8">
        {newSecret && <NewSecretBanner secret={newSecret} onDismiss={() => setNewSecret(null)} />}

        <ClientDetailsCard client={client} formatDate={formatDate} statusConfig={config} />

        <ActionButtons
          clientStatus={client.status}
          onEdit={() => setShowEditModal(true)}
          onRotateSecret={handleRotateSecret}
          onSuspend={() => setShowSuspendModal(true)}
          onActivate={() => activateMutation.mutate()}
          onBlock={() => setShowBlockModal(true)}
          isRotating={rotateSecretMutation.isPending}
          isActivating={activateMutation.isPending}
        />
      </main>

      <ConfirmationModal
        isOpen={showSuspendModal}
        onClose={() => setShowSuspendModal(false)}
        onConfirm={handleSuspend}
        title="Suspend Client"
        description="The client will be temporarily blocked. You can reactivate it later."
        confirmText="Suspend"
        confirmClassName="bg-amber-600 hover:bg-amber-500"
        isPending={suspendMutation.isPending}
      />

      <ConfirmationModal
        isOpen={showBlockModal}
        onClose={() => setShowBlockModal(false)}
        onConfirm={handleBlock}
        title="Block Client Permanently"
        description="This action cannot be undone. The client will be permanently blocked."
        confirmText="Block Permanently"
        confirmClassName="bg-red-600 hover:bg-red-500"
        isPending={blockMutation.isPending}
        isDanger
      />

      <EditClientModal
        client={client}
        isOpen={showEditModal}
        onClose={() => setShowEditModal(false)}
        onUpdate={handleUpdate}
        isPending={updateMutation.isPending}
      />
    </div>
  );
}
