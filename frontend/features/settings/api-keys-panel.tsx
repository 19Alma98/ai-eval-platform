"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, LogOut, Plus } from "lucide-react";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/api-key-gate";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { PageIntro } from "@/components/page-intro";
import { RelativeTime } from "@/components/relative-time";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  type ApiKey,
  type ApiKeyScope,
  type CreatedApiKey,
  createApiKey,
  listApiKeys,
  revokeApiKey,
} from "@/lib/api/auth";
import { formatErrorForUi } from "@/lib/api/client";
import { cn } from "@/lib/cn";

const apiKeysQueryKey = ["api-keys"] as const;

const SCOPES: { value: ApiKeyScope; label: string; description: string }[] = [
  {
    value: "ingest",
    label: "Ingest",
    description:
      "Send traces, scores and feedback. For apps in production. Cannot open the dashboard or read data.",
  },
  {
    value: "read",
    label: "Read",
    description: "Open the dashboard and read everything. Cannot change anything.",
  },
  {
    value: "admin",
    label: "Admin",
    description:
      "Everything, including experiments, deletes and managing keys. For CI and administrators.",
  },
];

export function ApiKeysPanel() {
  const { status, signOut } = useAuth();

  return (
    <section>
      <PageIntro
        title="Settings"
        glossary="API keys let apps, CI and people reach this server. There are no user accounts: each key has a name and a scope."
        actions={
          status.auth_required ? (
            <Button type="button" variant="outline" size="sm" onClick={() => void signOut()}>
              <LogOut className="size-4" />
              Sign out
            </Button>
          ) : null
        }
      />
      {!status.auth_required ? (
        <EmptyState
          title="Authentication is off"
          description="This server accepts every request. Set OPENGRADE_API_KEY on the server and restart it to require API keys; that key is the admin key you use to create the others here."
        />
      ) : status.scope !== "admin" ? (
        <EmptyState
          title="Admin key required"
          description={`You opened the dashboard with "${status.key_name ?? "a key"}", which has the ${status.scope} scope. Sign out and use an admin key to manage API keys.`}
        />
      ) : (
        <ApiKeysList />
      )}
    </section>
  );
}

function ApiKeysList() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: apiKeysQueryKey, queryFn: listApiKeys });
  const [createOpen, setCreateOpen] = useState(false);
  const [pendingRevoke, setPendingRevoke] = useState<ApiKey | null>(null);

  const revoke = useMutation({
    mutationFn: (id: string) => revokeApiKey(id),
    onSuccess: async () => {
      setPendingRevoke(null);
      await queryClient.invalidateQueries({ queryKey: apiKeysQueryKey });
      toast.success("Key revoked");
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });

  if (query.isLoading) return <LoadingBlock className="min-h-[160px]" />;
  if (query.isError) {
    return (
      <ErrorState
        title="Could not load API keys"
        message={formatErrorForUi(query.error)}
        onRetry={() => void query.refetch()}
      />
    );
  }

  const keys = query.data ?? [];

  return (
    <>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold tracking-tight text-foreground">API keys</h2>
        {keys.length > 0 ? (
          <Button type="button" size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="size-4" />
            New key
          </Button>
        ) : null}
      </div>

      {keys.length === 0 ? (
        <EmptyState
          title="No API keys yet"
          description="Only the OPENGRADE_API_KEY admin key works for now. Create an ingest key for each app that sends traces, and read keys for people who only look at the dashboard."
          action={
            <Button type="button" size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="size-4" />
              New key
            </Button>
          }
        />
      ) : (
        <ul className="divide-y divide-border rounded-md border border-border bg-surface">
          {keys.map((k) => (
            <li
              key={k.id}
              className={cn("flex items-center gap-3 px-3 py-2.5", k.revoked_at && "opacity-60")}
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-medium text-foreground">{k.name}</span>
                  <Badge variant={k.scope === "admin" ? "default" : "secondary"}>{k.scope}</Badge>
                  {k.revoked_at ? <Badge variant="destructive">revoked</Badge> : null}
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                  <code className="font-mono">{k.prefix}…</code>
                  <span>
                    Created <RelativeTime date={k.created_at} />
                  </span>
                  <span>
                    {k.last_used_at ? (
                      <>
                        Last used <RelativeTime date={k.last_used_at} />
                      </>
                    ) : (
                      "Never used"
                    )}
                  </span>
                </div>
              </div>
              {!k.revoked_at ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="shrink-0 text-muted-foreground hover:text-status-fail"
                  onClick={() => setPendingRevoke(k)}
                >
                  Revoke
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      <CreateApiKeyDialog open={createOpen} onOpenChange={setCreateOpen} />

      <Dialog
        open={pendingRevoke != null}
        onOpenChange={(open) => {
          if (revoke.isPending) return;
          if (!open) setPendingRevoke(null);
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Revoke key</DialogTitle>
            <DialogDescription>
              Revoke{" "}
              <span className="font-medium text-foreground">{pendingRevoke?.name}</span>? Every
              app or person using it is rejected from now on. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={revoke.isPending}
              onClick={() => setPendingRevoke(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={revoke.isPending || pendingRevoke == null}
              onClick={() => pendingRevoke && revoke.mutate(pendingRevoke.id)}
            >
              {revoke.isPending ? "Revoking…" : "Revoke key"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function CreateApiKeyDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [scope, setScope] = useState<ApiKeyScope>("ingest");
  const [created, setCreated] = useState<CreatedApiKey | null>(null);
  const [copied, setCopied] = useState(false);

  const create = useMutation({
    mutationFn: () => createApiKey({ name: name.trim(), scope }),
    onSuccess: async (key) => {
      setCreated(key);
      await queryClient.invalidateQueries({ queryKey: apiKeysQueryKey });
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });

  function close(next: boolean) {
    if (create.isPending) return;
    onOpenChange(next);
    if (!next) {
      // Drop the key from memory once the dialog closes: it is never shown again.
      setCreated(null);
      setCopied(false);
      setName("");
      setScope("ingest");
    }
  }

  function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!name.trim()) return;
    create.mutate();
  }

  async function copy() {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.key);
      setCopied(true);
    } catch {
      toast.error("Could not copy. Select the key and copy it manually.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-lg">
        {created ? (
          <>
            <DialogHeader>
              <DialogTitle>Copy your new key</DialogTitle>
              <DialogDescription>
                This is the only time the key is shown: the server keeps only a hash of it. Store
                it as a secret, e.g. <code className="font-mono">OPENGRADE_API_KEY</code> in the
                environment of <span className="font-medium text-foreground">{created.name}</span>.
              </DialogDescription>
            </DialogHeader>
            <div className="flex items-center gap-2 py-4">
              <Input
                readOnly
                value={created.key}
                aria-label="New API key"
                className="font-mono text-xs"
                onFocus={(e) => e.currentTarget.select()}
              />
              <Button type="button" variant="outline" size="sm" onClick={() => void copy()}>
                {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
            <DialogFooter>
              <Button type="button" onClick={() => close(false)}>
                Done
              </Button>
            </DialogFooter>
          </>
        ) : (
          <form onSubmit={onSubmit}>
            <DialogHeader>
              <DialogTitle>New API key</DialogTitle>
              <DialogDescription>
                Give each app or person its own key, so you can revoke one without touching the
                others.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-4 py-4">
              <div className="flex flex-col gap-2">
                <label htmlFor="api-key-name" className="text-sm font-medium">
                  Name
                </label>
                <Input
                  id="api-key-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="prod chatbot"
                  maxLength={200}
                  required
                />
              </div>
              <fieldset className="flex flex-col gap-2">
                <legend className="mb-2 text-sm font-medium">Scope</legend>
                {SCOPES.map((s) => (
                  <label
                    key={s.value}
                    className={cn(
                      "flex cursor-pointer gap-3 rounded-md border border-border px-3 py-2 transition-colors hover:bg-row-hover",
                      scope === s.value && "border-primary bg-row-selected",
                    )}
                  >
                    <input
                      type="radio"
                      name="api-key-scope"
                      value={s.value}
                      checked={scope === s.value}
                      onChange={() => setScope(s.value)}
                      className="mt-1 accent-primary"
                    />
                    <span>
                      <span className="block text-sm font-medium text-foreground">{s.label}</span>
                      <span className="block text-xs text-muted-foreground">{s.description}</span>
                    </span>
                  </label>
                ))}
              </fieldset>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => close(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={!name.trim() || create.isPending}>
                {create.isPending ? "Creating…" : "Create key"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
