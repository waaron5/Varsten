"use client";

import type { FormEvent } from "react";
import { useMemo, useState } from "react";
import { RequireSession } from "@/components/RequireSession";
import { useProjectResource } from "@/components/useProjectResource";
import {
  CollectionState,
  numberValue,
  PageHeader,
  PageState,
  Tabs,
  titleize,
} from "@/components/viewPrimitives";
import { api } from "@/lib/api";
import { compact, relativeTime, usd } from "@/lib/format";
import type {
  AdminBillingSecurity,
  AdminConnections,
  AdminTeam,
  AnalysisCustomers,
  AnalysisModels,
  AnalysisSpend,
  ApiKeyCreated,
  ProviderConnection,
} from "@/lib/types";

const ANALYSIS_TABS = [
  { href: "/analysis/spend", label: "Spend" },
  { href: "/analysis/customers", label: "Customers" },
  { href: "/analysis/models", label: "Models" },
];

const ADMIN_TABS = [
  { href: "/admin/connections", label: "Connections" },
  { href: "/admin/team", label: "Team" },
  { href: "/admin/billing-security", label: "Billing & security" },
];
const PROVIDERS = [
  { id: "openai", label: "OpenAI", placeholder: "sk-..." },
  { id: "anthropic", label: "Anthropic", placeholder: "sk-ant-..." },
  { id: "gemini", label: "Gemini", placeholder: "AIza..." },
];

type ProviderBusyAction = "save" | "disconnect";
type ProviderBusy = { provider: string; action: ProviderBusyAction } | null;

function providerStatusTone(status: string): string {
  if (status === "connected") return "green";
  if (status === "error") return "amber";
  return "neutral";
}

function marginPct(revenue: string | number | null, margin: string | number | null): string {
  const rev = numberValue(revenue);
  if (!rev || margin === null) return "-";
  return `${Math.round((numberValue(margin) / rev) * 100)}%`;
}

export function AnalysisSpendView() {
  return <RequireSession><AnalysisSpendBody /></RequireSession>;
}

function AnalysisSpendBody() {
  const { data, loading, error } = useProjectResource<AnalysisSpend>(["analysisSpend"], api.analysisSpend);
  const total = useMemo(() => data?.rows.reduce((sum, row) => sum + numberValue(row.spend_usd), 0) ?? 0, [data]);
  return (
    <div className="view">
      <PageHeader section="Analysis" title="Spend" description="Supporting investigation by team, feature, and provider." />
      <Tabs tabs={ANALYSIS_TABS} active="/analysis/spend" />
      <div className="card">
        <div className="card-head"><h3>Spend drivers</h3><div className="right"><span className="pill neutral">{usd(total, 0)} total</span></div></div>
        <CollectionState
          loading={loading}
          error={error}
          items={data?.rows}
          empty="No spend rows yet"
          emptyDetail="Ingest usage with team, feature, and provider metadata to populate this view."
        >
          {(rows) => (
            <table className="tbl">
            <thead><tr><th>Team</th><th>Feature</th><th>Provider</th><th className="r">Requests</th><th className="r">Spend</th></tr></thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={`${row.team}-${row.feature}-${row.provider}-${index}`}>
                  <td>{row.team ?? "Unknown"}</td>
                  <td className="muted">{row.feature ?? "Unlabeled"}</td>
                  <td>{row.provider ?? "Unknown"}</td>
                  <td className="r">{compact(row.requests)}</td>
                  <td className="r">{usd(row.spend_usd, 0)}</td>
                </tr>
              ))}
            </tbody>
            </table>
          )}
        </CollectionState>
      </div>
    </div>
  );
}

export function AnalysisCustomersView() {
  return <RequireSession><AnalysisCustomersBody /></RequireSession>;
}

function AnalysisCustomersBody() {
  const { data, loading, error } = useProjectResource<AnalysisCustomers>(["analysisCustomers"], api.analysisCustomers);
  return (
    <div className="view">
      <PageHeader section="Analysis" title="Customers" description="Customer-level AI economics for margin and value decisions." />
      <Tabs tabs={ANALYSIS_TABS} active="/analysis/customers" />
      <div className="card">
        <div className="card-head"><h3>Customer AI margin</h3></div>
        {loading || error || !data ? (
          <PageState loading={loading} error={error} empty={!data && !loading ? "No customer rows yet" : undefined} />
        ) : data.rows.length === 0 ? (
          <PageState empty="No customer rows yet" emptyDetail="Attach customer_id and revenue data to usage for margin analysis." />
        ) : (
          <table className="tbl">
            <thead><tr><th>Customer</th><th>Status</th><th className="r">Revenue</th><th className="r">AI cost</th><th className="r">Margin</th><th className="r">Requests</th></tr></thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={row.customer_id}>
                  <td><div className="name">{row.customer_name ?? row.customer_id}</div></td>
                  <td><span className={`pill ${row.status === "healthy" ? "green" : row.status === "negative_margin" ? "amber" : "neutral"}`}>{titleize(row.status)}</span></td>
                  <td className="r">{row.revenue_usd === null ? "-" : usd(row.revenue_usd, 0)}</td>
                  <td className="r">{usd(row.ai_cost_usd, 0)}</td>
                  <td className="r">{row.gross_margin_usd === null ? "-" : `${usd(row.gross_margin_usd, 0)} (${marginPct(row.revenue_usd, row.gross_margin_usd)})`}</td>
                  <td className="r">{compact(row.requests)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export function AnalysisModelsView() {
  return <RequireSession><AnalysisModelsBody /></RequireSession>;
}

function AnalysisModelsBody() {
  const { data, loading, error } = useProjectResource<AnalysisModels>(["analysisModels"], api.analysisModels);
  return (
    <div className="view">
      <PageHeader section="Analysis" title="Models" description="Model cost, request volume, and average cost per request." />
      <Tabs tabs={ANALYSIS_TABS} active="/analysis/models" />
      <div className="card">
        <div className="card-head"><h3>Model economics</h3></div>
        {loading || error || !data ? (
          <PageState loading={loading} error={error} empty={!data && !loading ? "No model rows yet" : undefined} />
        ) : data.rows.length === 0 ? (
          <PageState empty="No model rows yet" emptyDetail="Ingest usage events to compare provider and model cost." />
        ) : (
          <table className="tbl">
            <thead><tr><th>Provider</th><th>Model</th><th className="r">Requests</th><th className="r">Spend</th><th className="r">Avg/request</th></tr></thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={`${row.provider}-${row.model}`}>
                  <td>{row.provider}</td>
                  <td className="mono">{row.model}</td>
                  <td className="r">{compact(row.requests)}</td>
                  <td className="r">{usd(row.spend_usd, 0)}</td>
                  <td className="r">{row.avg_cost_per_request_usd === null ? "-" : usd(row.avg_cost_per_request_usd, 4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export function AdminConnectionsView() {
  return <RequireSession><AdminConnectionsBody /></RequireSession>;
}

function ProviderConnectionsCard({
  activeProjectId,
  busy,
  data,
  error,
  keyDrafts,
  loading,
  onDisconnect,
  onKeyDraft,
  onSave,
}: {
  activeProjectId: string | null;
  busy: ProviderBusy;
  data: AdminConnections | null | undefined;
  error: string | null;
  keyDrafts: Record<string, string>;
  loading: boolean;
  onDisconnect: (provider: string) => void;
  onKeyDraft: (provider: string, value: string) => void;
  onSave: (event: FormEvent, provider: string) => void;
}) {
  const connections = useMemo(() => {
    const byProvider = new Map((data?.provider_connections ?? []).map((connection) => [connection.provider, connection]));
    return PROVIDERS.map((provider) => ({
      provider,
      connection: byProvider.get(provider.id) ?? null,
    }));
  }, [data]);

  return (
    <div className="card">
      <div className="card-head"><h3>Provider connections</h3></div>
      {loading || error || !data ? (
        <PageState loading={loading} error={error} empty={!data && !loading ? "No connection data" : undefined} />
      ) : (
        <table className="tbl">
          <thead>
            <tr>
              <th>Provider</th>
              <th>Status</th>
              <th>Last verified</th>
              <th>Key</th>
              <th className="r">Actions</th>
            </tr>
          </thead>
          <tbody>
          {connections.map(({ provider, connection }) => (
            <ProviderConnectionRow
              activeProjectId={activeProjectId}
              busy={busy}
              connection={connection}
              key={provider.id}
              keyDraft={keyDrafts[provider.id] ?? ""}
              onDisconnect={onDisconnect}
              onKeyDraft={onKeyDraft}
              onSave={onSave}
              provider={provider}
            />
          ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function ProviderConnectionRow({
  activeProjectId,
  busy,
  connection,
  keyDraft,
  onDisconnect,
  onKeyDraft,
  onSave,
  provider,
}: {
  activeProjectId: string | null;
  busy: ProviderBusy;
  connection: ProviderConnection | null;
  keyDraft: string;
  onDisconnect: (provider: string) => void;
  onKeyDraft: (provider: string, value: string) => void;
  onSave: (event: FormEvent, provider: string) => void;
  provider: { id: string; label: string; placeholder: string };
}) {
  const state = providerConnectionRowState({ activeProjectId, busy, connection, providerId: provider.id });
  return (
    <tr>
      <ProviderNameCell connection={connection} label={provider.label} />
      <td>
        <ProviderConnectionStatus connection={connection} status={state.status} />
      </td>
      <td>{state.lastVerified}</td>
      <td>
        <ProviderKeyInlineForm
          disabled={state.disabled}
          keyDraft={keyDraft}
          onKeyDraft={(value) => onKeyDraft(provider.id, value)}
          onSave={(event) => onSave(event, provider.id)}
          placeholder={provider.placeholder}
          saving={state.saving}
          vaulted={state.vaulted}
        />
      </td>
      <td className="r">
        <DisconnectProviderButton
          disabled={state.disabled}
          disconnecting={state.disconnecting}
          onDisconnect={() => onDisconnect(provider.id)}
          vaulted={state.vaulted}
        />
      </td>
    </tr>
  );
}

function providerConnectionRowState({
  activeProjectId,
  busy,
  connection,
  providerId,
}: {
  activeProjectId: string | null;
  busy: ProviderBusy;
  connection: ProviderConnection | null;
  providerId: string;
}) {
  const action = busyActionForProvider(busy, providerId);
  return {
    disabled: providerActionDisabled(activeProjectId, busy),
    disconnecting: action === "disconnect",
    lastVerified: lastVerifiedLabel(connection),
    saving: action === "save",
    status: connectionStatus(connection),
    vaulted: connection?.key_vaulted === true,
  };
}

function busyActionForProvider(busy: ProviderBusy, providerId: string): ProviderBusyAction | null {
  return busy?.provider === providerId ? busy.action : null;
}

function providerActionDisabled(activeProjectId: string | null, busy: ProviderBusy): boolean {
  return Boolean(busy) || !activeProjectId;
}

function lastVerifiedLabel(connection: ProviderConnection | null): string {
  return connection?.last_verified_at ? relativeTime(connection.last_verified_at) : "-";
}

function connectionStatus(connection: ProviderConnection | null): string {
  return connection?.status ?? "not_connected";
}

function ProviderNameCell({ connection, label }: { connection: ProviderConnection | null; label: string }) {
  return (
    <td>
      <div className="name">{label}</div>
      <div className="muted">{connection?.connection_method ? titleize(connection.connection_method) : "Secrets Manager"}</div>
    </td>
  );
}

function ProviderConnectionStatus({
  connection,
  status,
}: {
  connection: ProviderConnection | null;
  status: string;
}) {
  return (
    <>
      <span className={`pill ${providerStatusTone(status)}`}>{titleize(status)}</span>
      {connection?.last_error ? <div className="form-error">{connection.last_error}</div> : null}
    </>
  );
}

function ProviderKeyInlineForm({
  disabled,
  keyDraft,
  onKeyDraft,
  onSave,
  placeholder,
  saving,
  vaulted,
}: {
  disabled: boolean;
  keyDraft: string;
  onKeyDraft: (value: string) => void;
  onSave: (event: FormEvent) => void;
  placeholder: string;
  saving: boolean;
  vaulted: boolean;
}) {
  return (
    <form className="inline-form" onSubmit={onSave}>
      <input
        className="input"
        type="password"
        autoComplete="off"
        placeholder={placeholder}
        value={keyDraft}
        onChange={(event) => onKeyDraft(event.target.value)}
      />
      <button className="btn primary" disabled={disabled || !keyDraft.trim()} type="submit">
        {saving ? "Saving..." : vaulted ? "Rotate" : "Connect"}
      </button>
    </form>
  );
}

function DisconnectProviderButton({
  disabled,
  disconnecting,
  onDisconnect,
  vaulted,
}: {
  disabled: boolean;
  disconnecting: boolean;
  onDisconnect: () => void;
  vaulted: boolean;
}) {
  return (
    <button
      className="btn danger"
      disabled={disabled || !vaulted}
      onClick={onDisconnect}
      type="button"
    >
      {disconnecting ? "Disconnecting..." : "Disconnect"}
    </button>
  );
}

function ApiKeysCard({
  activeProjectId,
  busy,
  created,
  data,
  loading,
  name,
  onName,
  onSubmit,
}: {
  activeProjectId: string | null;
  busy: boolean;
  created: ApiKeyCreated | null;
  data: AdminConnections | null | undefined;
  loading: boolean;
  name: string;
  onName: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
}) {
  const canCreate = !!activeProjectId && !!name.trim();
  return (
    <div className="card">
      <div className="card-head"><h3>API keys</h3></div>
      {data && data.api_keys.length > 0 ? (
        <table className="tbl"><thead><tr><th>Name</th><th>Prefix</th><th className="r">Last used</th></tr></thead><tbody>
          {data.api_keys.map((key) => (
            <tr key={key.id}><td>{key.name}</td><td className="mono">{key.key_prefix}</td><td className="r">{key.last_used_at ? relativeTime(key.last_used_at) : "Never"}</td></tr>
          ))}
        </tbody></table>
      ) : !loading ? (
        <PageState empty="No API keys" emptyDetail="Create a key to start sending usage events." />
      ) : null}
      <form className="config-form" onSubmit={onSubmit}>
        <input className="input" value={name} onChange={(e) => onName(e.target.value)} placeholder="API key name" />
        <button className="btn primary" type="submit" disabled={busy || !canCreate}>{busy ? "Creating..." : "Create API key"}</button>
        {created ? <div className="code">{created.plaintext_key}</div> : null}
      </form>
    </div>
  );
}

function AdminConnectionsBody() {
  const { activeProjectId, data, error, getToken, loading, reload, setError } =
    useProjectResource<AdminConnections>(["adminConnections"], api.adminConnections);
  const [name, setName] = useState("Production ingestion");
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [busy, setBusy] = useState(false);
  const [providerBusy, setProviderBusy] = useState<ProviderBusy>(null);
  const [providerKeys, setProviderKeys] = useState<Record<string, string>>({});

  const setProviderKey = (provider: string, value: string) => {
    setProviderKeys((current) => ({ ...current, [provider]: value }));
  };

  const saveProviderKey = async (event: FormEvent, provider: string) => {
    event.preventDefault();
    if (!activeProjectId || !providerKeys[provider]?.trim()) return;
    setProviderBusy({ provider, action: "save" });
    setError(null);
    try {
      await api.upsertProviderConnection(await getToken(), activeProjectId, provider, providerKeys[provider].trim());
      setProviderKeys((current) => ({ ...current, [provider]: "" }));
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setProviderBusy(null);
    }
  };

  const disconnectProvider = async (provider: string) => {
    if (!activeProjectId) return;
    setProviderBusy({ provider, action: "disconnect" });
    setError(null);
    try {
      await api.disconnectProviderConnection(await getToken(), activeProjectId, provider);
      setProviderKeys((current) => ({ ...current, [provider]: "" }));
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setProviderBusy(null);
    }
  };

  const createKey = async (event: FormEvent) => {
    event.preventDefault();
    if (!activeProjectId || !name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const key = await api.createApiKey(await getToken(), activeProjectId, name.trim());
      setCreated(key);
      setName("Production ingestion");
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="view">
      <PageHeader section="Admin" title="Connections" description="Provider connections and project ingestion keys." />
      <Tabs tabs={ADMIN_TABS} active="/admin/connections" />
      <div className="grid cols-2">
        <ProviderConnectionsCard
          activeProjectId={activeProjectId}
          busy={providerBusy}
          data={data}
          error={error}
          keyDrafts={providerKeys}
          loading={loading}
          onDisconnect={disconnectProvider}
          onKeyDraft={setProviderKey}
          onSave={saveProviderKey}
        />
        <ApiKeysCard
          activeProjectId={activeProjectId}
          busy={busy}
          created={created}
          data={data}
          loading={loading}
          name={name}
          onName={setName}
          onSubmit={createKey}
        />
      </div>
    </div>
  );
}

export function AdminTeamView() {
  return <RequireSession><AdminTeamBody /></RequireSession>;
}

function AdminTeamBody() {
  const { data, loading, error } = useProjectResource<AdminTeam>(["adminTeam"], api.adminTeam);
  return (
    <div className="view">
      <PageHeader section="Admin" title="Team" description="Organization members and roles, including finance-friendly Proof access." />
      <Tabs tabs={ADMIN_TABS} active="/admin/team" />
      <div className="card">
        <div className="card-head"><h3>Members</h3><div className="right">{data?.roles.map((role) => <span className="pill neutral" key={role}>{titleize(role)}</span>)}</div></div>
        {loading || error || !data ? (
          <PageState loading={loading} error={error} empty={!data && !loading ? "No team data" : undefined} />
        ) : data.members.length === 0 ? (
          <PageState empty="No members" emptyDetail="Members appear here after account sync." />
        ) : (
          <table className="tbl"><thead><tr><th>Name</th><th>Email</th><th className="r">Role</th></tr></thead><tbody>
            {data.members.map((member) => (
              <tr key={member.id}><td>{member.name ?? "-"}</td><td>{member.email}</td><td className="r"><span className="pill neutral">{titleize(member.role)}</span></td></tr>
            ))}
          </tbody></table>
        )}
      </div>
    </div>
  );
}

export function AdminBillingSecurityView() {
  return <RequireSession><AdminBillingSecurityBody /></RequireSession>;
}

function AdminBillingSecurityBody() {
  const { data, loading, error } = useProjectResource<AdminBillingSecurity>(["adminBillingSecurity"], api.adminBillingSecurity);
  return (
    <div className="view">
      <PageHeader section="Admin" title="Billing & Security" description="Verified-savings commercial model and deployment security posture." />
      <Tabs tabs={ADMIN_TABS} active="/admin/billing-security" />
      {loading || error || !data ? (
        <div className="card"><PageState loading={loading} error={error} empty={!data && !loading ? "No billing data" : undefined} /></div>
      ) : (
        <div className="grid cols-2">
          <div className="card">
            <div className="card-head"><h3>Billing model</h3></div>
            <div className="card-pad">
              <div className="mini-title">{titleize(data.plan)}</div>
              <p className="muted-copy">{titleize(data.pricing_model)}</p>
              <div className="hero-note" style={{ marginTop: 14 }}>Verified savings fee: {data.verified_savings_fee_percent === null ? "Not set" : `${data.verified_savings_fee_percent}%`}</div>
              <div className="meta-row" style={{ marginTop: 14 }}>
                <span className="pill neutral">{titleize(data.plan_tier)}</span>
                <span className="pill neutral">{titleize(data.subscription_status)}</span>
                <span className={`pill ${data.payment_method_ready_at ? "green" : "neutral"}`}>
                  {data.payment_method_ready_at ? "Payment method ready" : "No payment method"}
                </span>
              </div>
            </div>
          </div>
          <div className="card">
            <div className="card-head"><h3>Security posture</h3></div>
            <div className="card-pad">
              <div className="meta-row">
                <span className="pill accent">{titleize(data.security_posture.deployment_mode)}</span>
                <span className="pill neutral">{titleize(data.security_posture.soc2_status)}</span>
              </div>
              <p className="muted-copy" style={{ marginTop: 12 }}>{titleize(data.security_posture.content_storage)}</p>
              <div className="meta-row" style={{ marginTop: 14 }}>
                {data.security_posture.data_controls.map((control) => <span className="pill green" key={control}>{titleize(control)}</span>)}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
