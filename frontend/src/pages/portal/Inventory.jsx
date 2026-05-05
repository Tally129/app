import React from "react";
import PortalLayout, { PortalHeader, StatCard } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { useToast } from "../../hooks/use-toast";
import { Plus, Pencil, AlertTriangle, Boxes, Sliders } from "lucide-react";

const empty = { name: "", sku: "", category: "", stock: 0, unit_price: 0, low_stock_threshold: 5, active: true };

export default function Inventory() {
  const { toast } = useToast();
  const [items, setItems] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [edit, setEdit] = React.useState(null);
  const [form, setForm] = React.useState(empty);
  const [adjust, setAdjust] = React.useState(null);
  const [adjustForm, setAdjustForm] = React.useState({ delta: 0, reason: "manual", note: "" });

  const load = () => api.get("/inventory").then((r) => setItems(r.data || [])).finally(() => setLoading(false));
  React.useEffect(() => { load(); }, []);

  const lowStock = items.filter((i) => (i.stock || 0) <= (i.low_stock_threshold || 5));

  const openNew = () => { setEdit("new"); setForm(empty); };
  const openEdit = (i) => { setEdit(i.id); setForm({ ...empty, ...i }); };
  const save = async () => {
    if (!form.name) { toast({ title: "Name required" }); return; }
    try {
      const payload = {
        ...form,
        stock: parseInt(form.stock) || 0,
        unit_price: parseFloat(form.unit_price) || 0,
        low_stock_threshold: parseInt(form.low_stock_threshold) || 5,
        sku: form.sku || null,
        category: form.category || null,
      };
      if (edit === "new") await api.post("/inventory", payload);
      else await api.put(`/inventory/${edit}`, payload);
      toast({ title: "Saved" });
      setEdit(null); load();
    } catch (e) {
      toast({ title: "Failed", description: e?.response?.data?.detail || "" });
    }
  };

  const doAdjust = async () => {
    if (!adjust) return;
    try {
      await api.post(`/inventory/${adjust.id}/adjust`, {
        delta: parseInt(adjustForm.delta) || 0,
        reason: adjustForm.reason || "manual",
        note: adjustForm.note || null,
      });
      toast({ title: "Stock adjusted" });
      setAdjust(null); setAdjustForm({ delta: 0, reason: "manual", note: "" });
      load();
    } catch (e) {
      toast({ title: "Failed", description: e?.response?.data?.detail || "" });
    }
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="Inventory"
        subtitle={`${items.length} items · auto-decrements on POS sales`}
        actions={
          <Button onClick={openNew} className="btn-lift rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]" data-testid="inv-new-btn">
            <Plus size={16} className="mr-2" /> New item
          </Button>
        }
      />

      <div className="grid sm:grid-cols-3 gap-4 mb-6">
        <StatCard label="Total items" value={items.length} icon={Boxes} />
        <StatCard label="Low stock" value={lowStock.length} icon={AlertTriangle} accent={lowStock.length ? "text-[#7a2a2a]" : ""} />
        <StatCard label="Stock value" value={`$${items.reduce((s, i) => s + (i.stock || 0) * (i.unit_price || 0), 0).toFixed(2)}`} icon={Boxes} />
      </div>

      {lowStock.length > 0 && (
        <div className="mb-6 rounded-2xl border-2 border-[#7a2a2a] bg-[#fff5f5] p-4 text-sm" data-testid="low-stock-banner">
          <div className="flex items-center gap-2 font-semibold text-[#7a2a2a] mb-2">
            <AlertTriangle size={16} /> Low stock alerts
          </div>
          <div className="text-[#5e1f1f] space-y-1">
            {lowStock.map((i) => (
              <div key={i.id}>· <strong>{i.name}</strong>: {i.stock} left (threshold {i.low_stock_threshold})</div>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden" data-testid="inventory-table">
        <table className="w-full text-sm">
          <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
            <tr>
              <th className="text-left py-3 px-4">Item</th>
              <th className="text-left py-3 px-4">SKU</th>
              <th className="text-left py-3 px-4">Category</th>
              <th className="text-left py-3 px-4">Stock</th>
              <th className="text-left py-3 px-4">Threshold</th>
              <th className="text-left py-3 px-4">Price</th>
              <th className="text-right py-3 px-4">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="py-8 text-center text-[#6a6a6a]">Loading…</td></tr>}
            {!loading && items.length === 0 && <tr><td colSpan={7} className="py-10 text-center text-[#6a6a6a]">No inventory items yet.</td></tr>}
            {items.map((i) => {
              const low = (i.stock || 0) <= (i.low_stock_threshold || 5);
              return (
                <tr key={i.id} className="border-t border-[#e7dfc9]" data-testid={`inv-row-${i.id}`}>
                  <td className="py-3 px-4 font-medium text-[#1f2a22]">{i.name}</td>
                  <td className="py-3 px-4 text-[#6a6a6a]">{i.sku || "—"}</td>
                  <td className="py-3 px-4 text-[#6a6a6a]">{i.category || "—"}</td>
                  <td className={`py-3 px-4 font-display text-[18px] ${low ? "text-[#7a2a2a]" : "text-[#2f4a3a]"}`}>
                    {i.stock || 0}{low && <span className="text-xs ml-1">low</span>}
                  </td>
                  <td className="py-3 px-4 text-[#6a6a6a]">{i.low_stock_threshold || 5}</td>
                  <td className="py-3 px-4 font-display text-[#2f4a3a]">${(i.unit_price || 0).toFixed(2)}</td>
                  <td className="py-3 px-4 text-right space-x-1">
                    <Button size="sm" variant="outline" className="h-7 rounded-full text-xs border-[#c19a4b] text-[#8a6a3c]" onClick={() => setAdjust(i)} data-testid={`inv-adjust-${i.id}`}>
                      <Sliders size={12} className="mr-1" /> Adjust
                    </Button>
                    <Button size="sm" variant="outline" className="h-7 rounded-full text-xs border-[#2f4a3a] text-[#2f4a3a]" onClick={() => openEdit(i)} data-testid={`inv-edit-${i.id}`}>
                      <Pencil size={12} />
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <Dialog open={!!edit} onOpenChange={(o) => !o && setEdit(null)}>
        <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9]">
          <DialogHeader>
            <DialogTitle>{edit === "new" ? "New inventory item" : "Edit item"}</DialogTitle>
            <DialogDescription>Stock items decrement automatically on POS sale.</DialogDescription>
          </DialogHeader>
          <div className="grid md:grid-cols-2 gap-4">
            <div className="md:col-span-2"><Label>Name</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="inv-name" /></div>
            <div><Label>SKU</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} /></div>
            <div><Label>Category</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} /></div>
            <div><Label>Stock</Label><Input type="number" className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.stock} onChange={(e) => setForm({ ...form, stock: e.target.value })} data-testid="inv-stock" /></div>
            <div><Label>Unit price</Label><Input type="number" step="0.01" className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: e.target.value })} data-testid="inv-price" /></div>
            <div><Label>Low-stock threshold</Label><Input type="number" className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.low_stock_threshold} onChange={(e) => setForm({ ...form, low_stock_threshold: e.target.value })} /></div>
            <div className="flex items-end"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} /> Active</label></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEdit(null)}>Cancel</Button>
            <Button onClick={save} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]" data-testid="inv-save-btn">Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!adjust} onOpenChange={(o) => !o && setAdjust(null)}>
        <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9]">
          <DialogHeader>
            <DialogTitle>Adjust stock — {adjust?.name}</DialogTitle>
            <DialogDescription>Record a manual stock change (restock, shrinkage, count).</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="text-sm text-[#6a6a6a]">Current stock: <strong>{adjust?.stock}</strong></div>
            <div><Label>Change (use negative for shrinkage)</Label><Input type="number" className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={adjustForm.delta} onChange={(e) => setAdjustForm({ ...adjustForm, delta: e.target.value })} data-testid="inv-adjust-delta" /></div>
            <div><Label>Reason</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={adjustForm.reason} onChange={(e) => setAdjustForm({ ...adjustForm, reason: e.target.value })} placeholder="restock / shrinkage / count" /></div>
            <div><Label>Note</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={adjustForm.note} onChange={(e) => setAdjustForm({ ...adjustForm, note: e.target.value })} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAdjust(null)}>Cancel</Button>
            <Button onClick={doAdjust} className="bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]" data-testid="inv-adjust-confirm">Apply</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PortalLayout>
  );
}
