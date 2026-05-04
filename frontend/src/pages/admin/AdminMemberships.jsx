import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { useToast } from "../../hooks/use-toast";
import { Crown } from "lucide-react";

export default function AdminMemberships() {
  const { toast } = useToast();
  const [items, setItems] = React.useState([]);
  const load = () => api.get("/memberships").then((r) => setItems(r.data || []));
  React.useEffect(() => { load(); }, []);

  const setStatus = async (m, status) => {
    try {
      await api.put(`/memberships/${m.id}/status`, { status });
      toast({ title: `Set to ${status}` });
      load();
    } catch { toast({ title: "Failed" }); }
  };

  return (
    <PortalLayout>
      <PortalHeader title="Memberships" subtitle={`${items.length} total`} />
      {items.length === 0 ? (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-10 text-center text-[#6a6a6a]">
          <Crown size={28} className="mx-auto text-[#c19a4b]" />
          <div className="mt-3">No memberships yet.</div>
        </div>
      ) : (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
              <tr>
                <th className="text-left py-3 px-4">Client</th>
                <th className="text-left py-3 px-4">Tier</th>
                <th className="text-left py-3 px-4">Price</th>
                <th className="text-left py-3 px-4">Method</th>
                <th className="text-left py-3 px-4">Next bill</th>
                <th className="text-left py-3 px-4">Status</th>
              </tr>
            </thead>
            <tbody>
              {items.map((m) => (
                <tr key={m.id} className="border-t border-[#e7dfc9]">
                  <td className="py-3 px-4">{m.client_name || "—"}</td>
                  <td className="py-3 px-4 capitalize">{m.tier}</td>
                  <td className="py-3 px-4">${m.price.toFixed(2)}</td>
                  <td className="py-3 px-4 text-xs">{m.billing_method.replace("_", " ")}</td>
                  <td className="py-3 px-4 text-xs text-[#6a6a6a]">{m.next_bill_date ? new Date(m.next_bill_date).toLocaleDateString() : "—"}</td>
                  <td className="py-3 px-4">
                    <Select value={m.status} onValueChange={(v) => setStatus(m, v)}>
                      <SelectTrigger className="h-8 w-32 bg-[#f6f1e6] border-[#e0d6bc] text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {["active", "paused", "canceled"].map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PortalLayout>
  );
}
