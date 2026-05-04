import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../../components/ui/dialog";
import { useToast } from "../../hooks/use-toast";
import { Plus, Pencil, Trash2 } from "lucide-react";

const empty = { name: "", category: "", duration_min: 60, price: 0, sku: "", description: "", active: true };

export default function Treatments() {
  const { toast } = useToast();
  const [items, setItems] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [edit, setEdit] = React.useState(null);
  const [form, setForm] = React.useState(empty);

  const load = () =>
    api.get("/treatments").then((r) => setItems(r.data || [])).finally(() => setLoading(false));
  React.useEffect(() => { load(); }, []);

  const openNew = () => { setEdit("new"); setForm(empty); };
  const openEdit = (t) => { setEdit(t.id); setForm({ ...empty, ...t }); };

  const save = async () => {
    if (!form.name || form.price === "") { toast({ title: "Name and price required" }); return; }
    try {
      const payload = {
        ...form,
        duration_min: parseInt(form.duration_min) || 60,
        price: parseFloat(form.price) || 0,
        category: form.category || null,
        sku: form.sku || null,
        description: form.description || null,
      };
      if (edit === "new") {
        await api.post("/treatments", payload);
      } else {
        await api.put(`/treatments/${edit}`, payload);
      }
      toast({ title: "Saved" });
      setEdit(null); load();
    } catch (e) {
      toast({ title: "Failed", description: e?.response?.data?.detail || "" });
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete treatment?")) return;
    try {
      await api.delete(`/treatments/${id}`);
      toast({ title: "Deleted" }); load();
    } catch (e) {
      toast({ title: "Failed", description: e?.response?.data?.detail || "" });
    }
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="Treatments"
        subtitle={`${items.length} services in catalog`}
        actions={
          <Button onClick={openNew} className="btn-lift rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]" data-testid="treatments-new-btn">
            <Plus size={16} className="mr-2" /> New treatment
          </Button>
        }
      />

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden" data-testid="treatments-table">
        <table className="w-full text-sm">
          <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
            <tr>
              <th className="text-left py-3 px-4">Name</th>
              <th className="text-left py-3 px-4">Category</th>
              <th className="text-left py-3 px-4">Duration</th>
              <th className="text-left py-3 px-4">Price</th>
              <th className="text-left py-3 px-4">Status</th>
              <th className="text-right py-3 px-4">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={6} className="py-8 text-center text-[#6a6a6a]">Loading…</td></tr>}
            {!loading && items.length === 0 && <tr><td colSpan={6} className="py-10 text-center text-[#6a6a6a]">No treatments yet. Click <em>New treatment</em>.</td></tr>}
            {items.map((t) => (
              <tr key={t.id} className="border-t border-[#e7dfc9]" data-testid={`treatment-row-${t.id}`}>
                <td className="py-3 px-4 font-medium text-[#1f2a22]">{t.name}</td>
                <td className="py-3 px-4 text-[#6a6a6a]">{t.category || "—"}</td>
                <td className="py-3 px-4 text-[#6a6a6a]">{t.duration_min} min</td>
                <td className="py-3 px-4 font-display text-[#2f4a3a]">${t.price.toFixed(2)}</td>
                <td className="py-3 px-4 text-xs">
                  {t.active ? <span className="text-[#2f4a3a]">Active</span> : <span className="text-[#7a2a2a]">Inactive</span>}
                </td>
                <td className="py-3 px-4 text-right">
                  <Button size="sm" variant="outline" className="h-7 rounded-full text-xs mr-1 border-[#2f4a3a] text-[#2f4a3a]" onClick={() => openEdit(t)} data-testid={`treatment-edit-${t.id}`}>
                    <Pencil size={12} className="mr-1" /> Edit
                  </Button>
                  <Button size="sm" variant="outline" className="h-7 rounded-full text-xs border-[#7a2a2a] text-[#7a2a2a]" onClick={() => remove(t.id)} data-testid={`treatment-delete-${t.id}`}>
                    <Trash2 size={12} />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={!!edit} onOpenChange={(o) => !o && setEdit(null)}>
        <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9]">
          <DialogHeader><DialogTitle>{edit === "new" ? "New treatment" : "Edit treatment"}</DialogTitle></DialogHeader>
          <div className="grid md:grid-cols-2 gap-4">
            <div className="md:col-span-2"><Label>Name</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="tx-name" /></div>
            <div><Label>Category</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} data-testid="tx-category" /></div>
            <div><Label>SKU</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} /></div>
            <div><Label>Duration (min)</Label><Input type="number" className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.duration_min} onChange={(e) => setForm({ ...form, duration_min: e.target.value })} data-testid="tx-duration" /></div>
            <div><Label>Price</Label><Input type="number" step="0.01" className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} data-testid="tx-price" /></div>
            <div className="md:col-span-2"><Label>Description</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
            <div className="md:col-span-2"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} data-testid="tx-active" /> Active (available for booking & POS)</label></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEdit(null)}>Cancel</Button>
            <Button onClick={save} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]" data-testid="tx-save-btn">Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PortalLayout>
  );
}
