import React from "react";
import PortalLayout, { PortalHeader, StatCard } from "../PortalLayout";
import api, { API_BASE, LS } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { useToast } from "../../hooks/use-toast";
import { Download, Wallet, TrendingUp, FileText, FileBarChart } from "lucide-react";

const METHOD_LABELS = {
  chase_pos: "Chase POS", cash: "Cash", check: "Check", card_other: "Card", stripe: "Stripe",
};

export default function Transactions() {
  const { toast } = useToast();
  const [rows, setRows] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [methodFilter, setMethodFilter] = React.useState("all");
  const [search, setSearch] = React.useState("");

  const load = () => api.get("/transactions?limit=500").then((r) => setRows(r.data || [])).finally(() => setLoading(false));
  React.useEffect(() => { load(); }, []);

  const filtered = rows.filter((t) => {
    if (methodFilter !== "all" && t.payment_method !== methodFilter) return false;
    if (search && !((t.client_name || "").toLowerCase().includes(search.toLowerCase()) ||
                     t.id.toLowerCase().includes(search.toLowerCase()))) return false;
    return true;
  });

  const todayStart = new Date(); todayStart.setHours(0, 0, 0, 0);
  const today = rows.filter((t) => t.created_at && new Date(t.created_at) >= todayStart);
  const todayTotal = today.reduce((s, t) => s + (t.total || 0), 0);
  const allTotal = filtered.reduce((s, t) => s + (t.total || 0), 0);

  const downloadReceipt = async (id) => {
    try {
      const token = localStorage.getItem(LS.access);
      const r = await fetch(`${API_BASE}/transactions/${id}/receipt`, { headers: { Authorization: `Bearer ${token}` } });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `receipt-${id.slice(0, 8)}.pdf`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      toast({ title: "Failed to download", description: e.message });
    }
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="Transactions"
        subtitle="Every payment recorded across the practice"
        actions={
          <Button
            onClick={async () => {
              try {
                const token = localStorage.getItem(LS.access);
                const r = await fetch(`${API_BASE}/reports/eod-cash-drawer`, { headers: { Authorization: `Bearer ${token}` } });
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                const blob = await r.blob();
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = `eod-cash-drawer-${new Date().toISOString().slice(0,10)}.pdf`;
                a.click();
                URL.revokeObjectURL(a.href);
              } catch (e) { toast({ title: "Failed to generate report", description: e.message }); }
            }}
            className="rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]"
            data-testid="eod-cash-drawer-btn"
          >
            <FileBarChart size={16} className="mr-2" /> End-of-Day Cash Drawer PDF
          </Button>
        }
      />

      <div className="grid sm:grid-cols-3 gap-4 mb-6">
        <StatCard label="Today's revenue" value={`$${todayTotal.toFixed(2)}`} icon={TrendingUp} />
        <StatCard label="Today's count" value={today.length} icon={FileText} />
        <StatCard label="Filtered total" value={`$${allTotal.toFixed(2)}`} icon={Wallet} />
      </div>

      <div className="flex flex-col md:flex-row gap-3 mb-4">
        <Input
          placeholder="Search by client or transaction id…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-sm bg-[#f6f1e6] border-[#e0d6bc]"
          data-testid="txn-search-input"
        />
        <Select value={methodFilter} onValueChange={setMethodFilter}>
          <SelectTrigger className="w-44 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="txn-method-filter"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All methods</SelectItem>
            {Object.entries(METHOD_LABELS).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden" data-testid="transactions-table">
        <table className="w-full text-sm">
          <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
            <tr>
              <th className="text-left py-3 px-4">Date</th>
              <th className="text-left py-3 px-4">Client</th>
              <th className="text-left py-3 px-4">Items</th>
              <th className="text-left py-3 px-4">Method</th>
              <th className="text-left py-3 px-4">Status</th>
              <th className="text-right py-3 px-4">Total</th>
              <th className="text-right py-3 px-4">Receipt</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="py-8 text-center text-[#6a6a6a]">Loading…</td></tr>}
            {!loading && filtered.length === 0 && <tr><td colSpan={7} className="py-10 text-center text-[#6a6a6a]">No transactions match.</td></tr>}
            {filtered.map((t) => (
              <tr key={t.id} className="border-t border-[#e7dfc9]" data-testid={`txn-row-${t.id}`}>
                <td className="py-3 px-4 text-[#6a6a6a] text-xs">{new Date(t.created_at).toLocaleString()}</td>
                <td className="py-3 px-4">{t.client_name || <span className="text-[#6a6a6a] italic">walk-in</span>}</td>
                <td className="py-3 px-4 text-[#6a6a6a] text-xs">
                  {(t.lines || []).slice(0, 2).map((l) => l.name).join(", ")}
                  {(t.lines || []).length > 2 && ` +${(t.lines || []).length - 2}`}
                </td>
                <td className="py-3 px-4 text-xs">{METHOD_LABELS[t.payment_method] || t.payment_method}</td>
                <td className="py-3 px-4 text-xs">
                  {t.status === "paid"
                    ? <span className="text-[#2f4a3a]">Paid</span>
                    : <span className="text-[#8a6a3c]">{t.status}</span>}
                </td>
                <td className="py-3 px-4 text-right font-display text-[#2f4a3a]">${(t.total || 0).toFixed(2)}</td>
                <td className="py-3 px-4 text-right">
                  <Button size="sm" variant="outline" className="h-7 rounded-full text-xs border-[#2f4a3a] text-[#2f4a3a]" onClick={() => downloadReceipt(t.id)} data-testid={`txn-receipt-${t.id}`}>
                    <Download size={12} className="mr-1" /> PDF
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PortalLayout>
  );
}
