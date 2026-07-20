import React from "react";
import { ShieldCheck, ShieldOff, Clock3, Lock, PencilLine } from "lucide-react";
import api from "../lib/api";

/**
 * Reflects the delegated-editing state of a clinical record. States:
 *   - read_only          : "Read Only — Provider Authorization Required"
 *   - draft_editing      : "Draft Editing Authorized"
 *   - awaiting_review    : "Awaiting Provider Review"
 *   - finalized          : "Finalized"
 *
 * Purely presentational — the backend is the source of truth. This component
 * only fetches /delegations/effective when `clientId` is supplied and no
 * explicit `state` prop was provided.
 */
export function AuthorizationBadge({ state, className = "" }) {
  const map = {
    read_only: {
      label: "Read Only — Provider Authorization Required",
      icon: ShieldOff,
      color: "bg-[#f4e4d4] text-[#7a4a2a] border-[#e0c8a0]",
    },
    draft_editing: {
      label: "Draft Editing Authorized",
      icon: PencilLine,
      color: "bg-[#e6efe1] text-[#2f4a3a] border-[#b6cfaf]",
    },
    awaiting_review: {
      label: "Awaiting Provider Review",
      icon: Clock3,
      color: "bg-[#fdf3d0] text-[#8a6a3c] border-[#e6d38a]",
    },
    finalized: {
      label: "Finalized",
      icon: Lock,
      color: "bg-[#e0d6bc] text-[#3a3a3a] border-[#c9b98f]",
    },
  };
  const entry = map[state] || map.read_only;
  const Icon = entry.icon;
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] uppercase tracking-widest ${entry.color} ${className}`}
      data-testid={`auth-badge-${state || "read_only"}`}
    >
      <Icon size={11} /> {entry.label}
    </span>
  );
}

/**
 * Hook that resolves whether the current viewer can edit drafts for a given
 * client. Providers always can. Admin/MA needs an active delegation.
 * Returns: { canEdit, state, delegation, loading, refresh, isProvider }
 */
export function useDelegatedEdit({ role, clientId, recordStatus }) {
  const [canEdit, setCanEdit] = React.useState(role === "practitioner");
  const [delegation, setDelegation] = React.useState(null);
  const [loading, setLoading] = React.useState(false);

  const eligible = role === "admin" || role === "medical_assistant";
  const isProvider = role === "practitioner";

  const load = React.useCallback(async () => {
    if (!eligible || !clientId) return;
    setLoading(true);
    try {
      const r = await api.get("/delegations/effective", { params: { client_id: clientId } });
      setCanEdit(!!r.data?.can_edit_draft);
      setDelegation(r.data?.delegation || null);
    } catch {
      setCanEdit(false);
      setDelegation(null);
    } finally {
      setLoading(false);
    }
  }, [eligible, clientId]);

  React.useEffect(() => {
    if (isProvider) { setCanEdit(true); return; }
    load();
  }, [isProvider, load]);

  const state = (() => {
    const s = (recordStatus || "draft").toLowerCase();
    if (s === "finalized") return "finalized";
    if (isProvider) return "draft_editing";
    if (canEdit) return "draft_editing";
    if (eligible) return "read_only";
    return "read_only";
  })();

  return { canEdit, state, delegation, loading, refresh: load, isProvider };
}
